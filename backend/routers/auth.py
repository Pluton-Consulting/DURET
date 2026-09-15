import logging
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from database.connection import get_db
from auth import appareil
from auth.jwt_handler import create_access_token, decode_access_token
from auth.dependencies import get_current_user
from security import tentatives
from database.models import User
from security.audit import log_action
from emails.envoi import envoyer
from emails.gabarit import mail_connexion
from config import settings

_bearer = HTTPBearer()

router = APIRouter()

MAGIC_LINK_EXPIRE_MINUTES = 15


class MagicLinkRequest(BaseModel):
    email: str


class VerifyTokenRequest(BaseModel):
    token: str
    email: str
    # Le prénom cliqué sur l'écran des cartes, quand l'adresse porte plusieurs
    # profils (11/09). Absent : un seul compte sur l'adresse, rien à choisir.
    user_id: str | None = None


class ChangerProfilRequest(BaseModel):
    user_id: str
    # Le code de la carte, quand elle en a un (13/09, migration 041).
    code: str | None = None


# ── Les essais de code, PAR ORIGINE (16/09, audit D-19) ────────────────────
# Le compteur par profil protège UNE carte, pas la boîte partagée d'un balayage
# qui les essaie toutes. La borne par origine vit dans `security/tentatives.py`
# (le banc l'exécute) ; ici on ne fait que lire la demande.
def _origine(request: Request) -> str:
    return tentatives.origine_de(request.headers.get("x-forwarded-for") or "",
                                 getattr(request.client, "host", "") or "")


def _refus_code(raison: str) -> HTTPException:
    """Le refus, avec le bon code HTTP. « indisponible » et « code_a_poser » ne
    sont pas des erreurs de la personne : ce sont des états du serveur."""
    statut = {"code_bloque": status.HTTP_429_TOO_MANY_REQUESTS,
              "origine_bloquee": status.HTTP_429_TOO_MANY_REQUESTS,
              "indisponible": status.HTTP_503_SERVICE_UNAVAILABLE,
              "code_a_poser": status.HTTP_503_SERVICE_UNAVAILABLE}.get(
                  raison, status.HTTP_401_UNAUTHORIZED)
    return HTTPException(status_code=statut, detail=raison)


async def _exiger_code(profil: dict, code: str | None, action: str,
                       request: Request | None = None) -> None:
    """Une carte à code ne s'ouvre qu'avec lui. Le refus porte une raison
    courte que l'écran traduit : code_requis, code_faux, code_bloque,
    indisponible (le serveur ne peut pas vérifier — on n'entre pas)."""
    from auth import profils as _profils
    if not _profils.a_un_code(profil):
        return
    if request is not None and tentatives.saturee(_origine(request)):
        raise _refus_code("origine_bloquee")
    verdict = await _profils.controler_code(str(profil["id"]), code, exige=True)
    if verdict.ok:
        if request is not None:
            tentatives.oublier(_origine(request))
        return
    if request is not None:
        tentatives.noter_echec(_origine(request))
    await log_action(action=f"{action}_code_refuse", user_id=str(profil["id"]), success=False,
                     error_message=verdict.raison)
    raise _refus_code(verdict.raison or "code_faux")


class RefreshRequest(BaseModel):
    """Le jeton d'appareil posé lors de la dernière connexion par lien magique."""
    refresh_token: str


class LogoutRequest(BaseModel):
    """`refresh_token` optionnel : sans lui, seul le JWT courant est révoqué et
    l'appareil resterait connecté au rechargement — ce serait un mensonge
    d'écran (« Fermer la session sur cet appareil »)."""
    refresh_token: str | None = None


async def _send_magic_link_email(to_email: str, magic_link: str) -> None:
    """Envoie le lien de connexion. En debug, l'affiche AUSSI en console.

    Le contenu a quitté ce fichier : il vit dans `emails/`, gabarit commun aux
    deux clients et marque isolée dans un seul module. Ce routeur ne connaît
    plus ni HTML ni Resend — c'est ce qui garantit qu'une correction de mise en
    page se pose des deux côtés d'un seul geste.
    """
    if settings.debug:
        print(f"\nMAGIC LINK (dev) → {magic_link}\n")
        # Pas de return : l'email part quand même en mode debug.

    objet, _apercu, html = mail_connexion(magic_link, MAGIC_LINK_EXPIRE_MINUTES)
    # Le logo voyage AVEC le message (pièce jointe « inline », référencée par
    # `cid:` dans l'en-tête du gabarit) : un logo distant serait bloqué par la
    # plupart des clients, et celui-ci vit derrière le VPN de toute façon.
    from emails.marque import logo_image
    logo = logo_image()
    await envoyer(to_email, objet, html, images=[logo] if logo else None)


@router.post("/magic-link/request")
async def request_magic_link(body: MagicLinkRequest):
    """
    Génère un token et envoie un lien de connexion par email.
    Retourne toujours le même message pour ne pas révéler si l'email existe.
    """
    if not getattr(settings, "lien_magique_actif", True):
        raise HTTPException(status_code=status.HTTP_410_GONE,
                            detail="La connexion par lien magique est désactivée : entrez par votre "
                                   "carte, ou par le bouton « Admin » et votre code.")
    async with get_db() as conn:
        # Insensible à la casse, et plusieurs comptes possibles sur l'adresse
        # (profils d'une boîte partagée, 040) : il suffit qu'UN soit actif.
        user = await conn.fetchrow(
            "SELECT id FROM users WHERE lower(email) = lower($1) AND actif = true LIMIT 1",
            body.email,
        )

    if not user:
        await log_action(
            action="login_attempt_unknown",
            success=False,
            error_message="Email non enregistré",
        )
        # Réponse UNIFORME (anti-énumération de comptes) — voir aussi le chemin "connu".
        return {"ok": True}

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=MAGIC_LINK_EXPIRE_MINUTES)

    async with get_db() as conn:
        await conn.execute(
            "INSERT INTO verification_tokens (email, token, expires_at) VALUES ($1, $2, $3)",
            body.email, token, expires_at,
        )

    magic_link = f"{settings.app_url}/verify?token={token}&email={body.email}"
    await _send_magic_link_email(body.email, magic_link)
    return {"ok": True}


@router.post("/magic-link/verify")
async def verify_magic_link(body: VerifyTokenRequest, request: Request):
    """Vérifie le token, le consomme, retourne un JWT backend ET ouvre la
    session durable de CET appareil (03/09).

    C'est ici, et seulement ici, que naît un jeton d'appareil : le lien magique
    reste l'unique preuve d'identité. Ce qui change, c'est qu'on ne la redemande
    plus tous les jours au même poste.
    """
    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM verification_tokens WHERE token = $1 AND email = $2",
            body.token, body.email,
        )

    if not row:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Lien invalide")
    # UN LIEN PEUT SERVIR PLUSIEURS FOIS (03/09, migration 035) : PC puis
    # téléphone, chacun ouvrant sa propre session d'appareil. Le compteur fait
    # foi quand il existe ; `used` reste le verrou du lien envoyé par mail et
    # celui d'une base sans la migration — dans ce cas tout lien vaut une fois.
    d = dict(row)
    maxi = int(d.get("utilisations_max") or 1)
    faites = int(d.get("utilisations") or 0)
    if row["used"] or faites >= maxi:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Lien déjà utilisé")
    if row["expires_at"] < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Lien expiré")

    # QUI ENTRE (11/09). L'adresse peut porter plusieurs profils — la boîte
    # partagée de l'entreprise : il faut alors que le prénom ait été choisi sur
    # l'écran des cartes. Décidé AVANT de consommer le lien : l'écran des
    # cartes rappelle cette route avec le prénom, le lien doit encore valoir.
    from auth import profils as _profils
    retenu = _profils.choisir(await _profils.profils_de(body.email), body.user_id)
    if retenu == "choix":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="choix_profil")
    if retenu is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès non autorisé")
    # Un profil à CODE d'une adresse partagée ne s'ouvre pas par le lien : le
    # lien prouve la boîte, que tout le monde partage ; le code prouve la
    # personne. Il se choisit sur la page de connexion (13/09).
    if retenu.get("a_code") and len(await _profils.profils_de(body.email)) > 1:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Ce profil est protégé par un code : choisissez-le sur la page de connexion.")

    async with get_db() as conn:
        try:
            # Une utilisation de plus ; le lien se ferme quand le compte est
            # plein. Écrit en UNE requête pour que deux appareils qui cliquent
            # au même instant ne consomment pas la même utilisation.
            await conn.execute(
                """UPDATE verification_tokens
                      SET utilisations = utilisations + 1,
                          used = (utilisations + 1 >= utilisations_max)
                    WHERE token = $1""",
                body.token,
            )
        except Exception as e:  # noqa: BLE001
            from database.connection import schema_incomplet
            if not schema_incomplet(e):
                raise
            # Migration 035 absente : comportement d'avant, à usage unique.
            await conn.execute(
                "UPDATE verification_tokens SET used = true WHERE token = $1",
                body.token,
            )
        user = await conn.fetchrow(
            "SELECT * FROM users WHERE id = $1 AND actif = true",
            retenu["id"],
        )

    if not user:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès non autorisé")

    async with get_db() as conn:
        await conn.execute(
            "UPDATE users SET last_login = $1 WHERE id = $2",
            datetime.now(timezone.utc), user["id"],
        )

    await log_action(action="login", user_id=str(user["id"]))

    access_token = create_access_token({"sub": str(user["id"]), "role": user["role"]})
    jeton_appareil = await appareil.creer(user["id"], request.headers.get("user-agent", ""))
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user["role"],
        # None si la migration 034 n'est pas encore appliquée : le navigateur
        # retombe alors sur le comportement d'avant (lien magique tous les jours).
        "refresh_token": jeton_appareil,
        # L'identité du PROFIL (11/09) : deux prénoms d'une même adresse ne
        # doivent pas partager ce que l'écran range par personne (le fil
        # courant), et l'en-tête affiche le prénom, pas l'adresse commune.
        "user_id": str(user["id"]),
        "nom": user["name"],
    }


@router.post("/magic-link/etat")
async def etat_magic_link(body: VerifyTokenRequest):
    """POURQUOI ce lien a été refusé — sans rien consommer ni modifier.

    RELEVÉ DE NOA DU 08/09 : une employée n'arrive pas à se connecter, et
    l'écran répond « Lien invalide ou expiré » quoi qu'il arrive. Le serveur,
    lui, distingue quatre situations très différentes — lien inconnu, déjà
    utilisé, périmé, compte désactivé — dont trois appellent un geste précis.
    Sans cette route, il faut ouvrir la base pour savoir laquelle : c'est la
    même faute que le 429 sans cause de Nano Banana ou le refus Drive muet.

    ⚠️ ANTI-ÉNUMÉRATION. On ne répond en détail QUE si le couple (jeton,
    adresse) existe vraiment : le porteur du lien connaît déjà l'adresse, on
    ne lui apprend rien. À un jeton inventé, la réponse reste générique — sinon
    la route deviendrait un moyen de tester des adresses.
    """
    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM verification_tokens WHERE token = $1 AND email = $2",
            body.token, body.email,
        )
        actif = None
        if row:
            # Plusieurs profils possibles sur l'adresse : elle est ouverte si
            # l'un d'eux l'est (NULL = aucun compte).
            actif = await conn.fetchval(
                "SELECT bool_or(actif) FROM users WHERE lower(email) = lower($1)", body.email)

    if not row:
        return {"raison": "inconnu",
                "message": ("Ce lien ne correspond à rien. Demandez-en un nouveau "
                            "depuis la page de connexion.")}

    d = dict(row)
    maxi = int(d.get("utilisations_max") or 1)
    faites = int(d.get("utilisations") or 0)
    if d.get("used") or faites >= maxi:
        return {"raison": "deja_utilise",
                "message": ("Ce lien a déjà servi" + (f" ({faites} fois sur {maxi})" if maxi > 1 else "")
                            + ". Demandez-en un nouveau : chaque lien ne vaut "
                              "que pour une ouverture de session.")}
    if d["expires_at"] < datetime.now(timezone.utc):
        return {"raison": "expire",
                "message": (f"Ce lien a expiré (il vaut {MAGIC_LINK_EXPIRE_MINUTES} minutes). "
                            "Demandez-en un nouveau et ouvrez-le tout de suite.")}
    if actif is False:
        return {"raison": "compte_desactive",
                "message": ("Ce compte est désactivé : aucun lien ne l'ouvrira. "
                            "Demandez à un administrateur de le réactiver dans "
                            "Paramètres puis Utilisateurs.")}
    if actif is None:
        return {"raison": "compte_absent",
                "message": ("Aucun compte ne porte cette adresse. Un administrateur "
                            "doit la créer, ou corriger l'orthographe.")}
    return {"raison": "valide",
            "message": ("Ce lien est encore valable. Si la connexion échoue quand même, "
                        "le serveur n'a pas répondu : réessayez dans un instant.")}


@router.post("/magic-link/profils")
async def profils_du_lien(body: VerifyTokenRequest):
    """Les cartes à montrer après le lien magique — sans rien consommer.

    Rend les profils de l'adresse quand il faut CHOISIR (plusieurs comptes
    actifs, non administrateurs), une liste vide sinon. ⚠️ ANTI-ÉNUMÉRATION :
    seulement contre un lien VALIDE (existant, non épuisé, non périmé) — le
    porteur d'un lien valide a déjà la boîte, on ne lui apprend rien.
    """
    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM verification_tokens WHERE token = $1 AND email = $2",
            body.token, body.email,
        )
    if not row:
        return {"profils": []}
    d = dict(row)
    if d.get("used") or int(d.get("utilisations") or 0) >= int(d.get("utilisations_max") or 1) \
            or d["expires_at"] < datetime.now(timezone.utc):
        return {"profils": []}
    from auth import profils as _profils
    tous = await _profils.profils_de(body.email)
    # Les cartes à code ne s'ouvrent pas depuis un lien : elles n'y figurent pas.
    return {"profils": [c for c in _profils.cartes(tous) if not c["code"]]
            if _profils.choisir(tous) == "choix" else []}


@router.get("/connexion/profils")
async def profils_de_connexion():
    """LA PAGE DE CONNEXION EST UN CHOIX DE PRÉNOM (13/09, Duret).

    Demande de Noa : tout le monde partage la boîte Gmail de l'entreprise, et
    la page de connexion n'est plus qu'une rangée de cartes, « comme Netflix » ;
    le lien magique ne sert plus qu'aux administrateurs, derrière un petit
    bouton. Rend les cartes des profils de la boîte unique — ni rôle, ni
    adresse, ni administrateur. Aucune boîte reliée : aucune carte, et l'écran
    montre le lien magique à tout le monde, comme avant.

    ⚠️ SANS AUTHENTIFICATION, ET C'EST LE BUT. Les prénoms des profils sont
    lisibles de quiconque atteint la page — c'est-à-dire du réseau privé
    (Headscale) : l'application n'est pas exposée ailleurs.
    """
    from auth import profils as _profils
    # LES CARTES NE DÉPENDENT PLUS DE LA BOÎTE (14/09, Noa : « chacun peut se
    # connecter avec son prénom même si l'adresse mail n'est pas configurée »).
    # Une page vide dit seulement qu'aucun profil n'existe encore.
    cartes = _profils.cartes_de_connexion(await _profils.profils_tous())
    return {"profils": cartes, "raison": None if cartes else "aucun_profil"}


@router.post("/connexion/profil")
async def entrer_par_carte(body: ChangerProfilRequest, request: Request):
    """Ouvre la session du prénom cliqué sur la page de connexion.

    ⚠️ CE QUI PROUVE L'IDENTITÉ, DIT TEL QUEL. Plus rien : c'est le réseau
    privé qui fait la porte, et la carte dit seulement QUI entre (son chat, ses
    documents, ses dossiers du mail). Les gardes tiennent donc au périmètre :
    un profil de la boîte de l'entreprise, actif, et JAMAIS un administrateur
    (`auth/profils.entree_par_carte`) — un compte qui voit tout ou gère les
    utilisateurs passe toujours par le lien magique. Chaque entrée est tracée.
    """
    from auth import profils as _profils
    tous = await _profils.profils_tous()
    retenu = _profils.entree_par_carte(tous, None, body.user_id)
    if retenu is None:
        await log_action(action="connexion_carte_refusee", success=False,
                         error_message="profil hors des cartes de connexion")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Ce profil ne s'ouvre pas depuis la page de connexion.")
    await _exiger_code(retenu, body.code, "connexion_carte", request)
    async with get_db() as conn:
        await conn.execute("UPDATE users SET last_login = $1 WHERE id = $2::uuid",
                           datetime.now(timezone.utc), str(retenu["id"]))
    await log_action(action="login", user_id=str(retenu["id"]),
                     metadata={"par": "carte_profil"})
    access_token = create_access_token({"sub": str(retenu["id"]), "role": retenu["role"]})
    jeton_appareil = await appareil.creer(retenu["id"], request.headers.get("user-agent", ""))
    return {"access_token": access_token, "token_type": "bearer",
            "role": retenu["role"], "refresh_token": jeton_appareil,
            "user_id": str(retenu["id"]), "nom": retenu.get("name")}


@router.get("/connexion/admins")
async def admins_de_connexion():
    """Les cartes du bouton « Admin » (15/09, Duret) : le nom seul, jamais le rôle
    ni l'adresse. Sans authentification, comme les cartes : la porte est le VPN."""
    from auth import profils as _profils
    return {"profils": _profils.cartes_admin(await _profils.profils_tous())}


@router.post("/connexion/admin")
async def entrer_en_admin(body: ChangerProfilRequest, request: Request):
    """Ouvre la session d'un administrateur par son CODE (15/09, Duret).

    Le lien magique est coupé : l'administrateur choisit sa carte derrière le
    bouton « Admin » et tape son code — celui qu'il a posé dans Paramètres, ou,
    tant qu'il n'en a posé aucun, le code de PREMIÈRE ENTRÉE du serveur, qui ne
    sert QU'UNE FOIS et oblige aussitôt à en poser un vrai (16/09, audit D-19).
    Gardes : cinq essais faux par carte, quinze minutes de blocage, une borne
    par origine, tout est tracé — et si le serveur ne peut pas vérifier le code,
    il REFUSE.
    """
    from auth import profils as _profils
    tous = await _profils.profils_tous()
    ids = {c["id"] for c in _profils.cartes_admin(tous)}
    retenu = next((p for p in tous if str(p["id"]) == str(body.user_id or "")), None)
    if retenu is None or str(retenu["id"]) not in ids:
        await log_action(action="connexion_admin_refusee", success=False,
                         error_message="profil hors des cartes admin")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Ce profil ne s'ouvre pas par le bouton Admin.")
    if tentatives.saturee(_origine(request)):
        raise _refus_code("origine_bloquee")
    verdict = await _profils.controler_code(str(retenu["id"]), body.code, exige=True,
                                            defaut=_profils.code_admin_defaut())
    if not verdict.ok:
        tentatives.noter_echec(_origine(request))
        await log_action(action="connexion_admin_code_refuse", user_id=str(retenu["id"]),
                         success=False, error_message=verdict.raison)
        raise _refus_code(verdict.raison or "code_faux")
    async with get_db() as conn:
        await conn.execute("UPDATE users SET last_login = $1 WHERE id = $2::uuid",
                           datetime.now(timezone.utc), str(retenu["id"]))
    tentatives.oublier(_origine(request))
    await log_action(action="login", user_id=str(retenu["id"]),
                     metadata={"par": "carte_admin",
                               "premiere_entree": bool(verdict.doit_changer)})
    access_token = create_access_token({"sub": str(retenu["id"]), "role": retenu["role"]})
    jeton_appareil = await appareil.creer(retenu["id"], request.headers.get("user-agent", ""))
    return {"access_token": access_token, "token_type": "bearer",
            "role": retenu["role"], "refresh_token": jeton_appareil,
            "user_id": str(retenu["id"]), "nom": retenu.get("name"),
            # Entré avec le code de première entrée : il vient d'être consommé,
            # l'écran fait poser un vrai code avant d'aller plus loin.
            "code_a_changer": bool(verdict.doit_changer)}


@router.get("/profils")
async def mes_profils(current_user: User = Depends(get_current_user)):
    """Les profils entre lesquels ce compte peut basculer (bouton « Changer de
    profil ») : ceux de son adresse partagée. Vide pour un compte seul sur son
    adresse, et pour un administrateur."""
    from auth import profils as _profils
    partages = await _profils.profils_partages(str(current_user.id))
    return {"profils": _profils.cartes_de_connexion(partages), "actuel": str(current_user.id)}


@router.post("/profils/changer")
async def changer_de_profil(body: ChangerProfilRequest, request: Request,
                            current_user: User = Depends(get_current_user)):
    """Passe à un autre prénom de la MÊME adresse, sans nouveau lien magique.

    C'est la boîte partagée qui prouve l'identité, et celui qui parle l'a déjà
    prouvée : on n'exige rien de plus, mais on ne sort jamais de l'adresse, et
    l'on n'atteint jamais un administrateur. Une nouvelle session d'appareil
    naît pour le profil choisi : c'est lui que l'appareil retrouvera demain.
    """
    from auth import profils as _profils
    partages = await _profils.profils_partages(str(current_user.id))
    retenu = _profils.entree_par_carte(partages, None, body.user_id) if partages else None
    if not isinstance(retenu, dict):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Ce profil n'est pas accessible depuis ce compte.")
    await _exiger_code(retenu, body.code, "changement_profil", request)
    async with get_db() as conn:
        await conn.execute("UPDATE users SET last_login = $1 WHERE id = $2::uuid",
                           datetime.now(timezone.utc), str(retenu["id"]))
    await log_action(action="changement_profil", user_id=str(retenu["id"]),
                     metadata={"depuis": str(current_user.id)})
    access_token = create_access_token({"sub": str(retenu["id"]), "role": retenu["role"]})
    jeton_appareil = await appareil.creer(retenu["id"], request.headers.get("user-agent", ""))
    return {"access_token": access_token, "token_type": "bearer",
            "role": retenu["role"], "refresh_token": jeton_appareil,
            "user_id": str(retenu["id"]), "nom": retenu.get("name")}


@router.post("/refresh")
async def refresh_session(body: RefreshRequest):
    """Échange le jeton d'appareil contre un JWT frais — sans mail, sans clic.

    Appelée par le navigateur dès que le JWT approche de son terme. Un refus
    ne dit pas POURQUOI (session inconnue, révoquée, échue, compte désactivé) :
    à qui présente un jeton, on répond « reconnectez-vous », pas un diagnostic.
    """
    compte = await appareil.compte_de(body.refresh_token)
    if compte is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session close : reconnectez-vous.",
        )
    access_token = create_access_token({"sub": str(compte["user_id"]), "role": compte["role"]})
    return {"access_token": access_token, "token_type": "bearer", "role": compte["role"]}


@router.post("/appareils/fermer-jeton")
async def fermer_par_jeton(body: RefreshRequest):
    """Ferme la session de CET appareil sur présentation de son propre jeton.

    POURQUOI SANS JWT. C'est la route qu'appelle « Se déconnecter ». Or on se
    déconnecte souvent d'un onglet dont le JWT a déjà expiré : exiger un JWT
    valide laisserait alors l'appareil se reconnecter tout seul à la page
    suivante — le bouton mentirait. Le jeton d'appareil EST la preuve, et le
    pire qu'en fasse quelqu'un qui l'aurait volé est de nous déconnecter.
    """
    ferme = await appareil.revoquer(body.refresh_token)
    return {"ok": ferme}


@router.get("/appareils")
async def lister_appareils(current_user: User = Depends(get_current_user)):
    """Les appareils qui restent connectés à SON compte.

    La contrepartie d'une session qui ne périme pas : on ne peut l'accepter que
    si l'on voit ce qui est ouvert, et que l'on peut le fermer. `disponible:
    false` dit « je ne peux pas le savoir » (migration absente) — ce n'est pas
    « aucun appareil ».
    """
    appareils = await appareil.lister(current_user.id)
    if appareils is None:
        return {"disponible": False, "appareils": [], "migration_absente": appareil.MIGRATION}
    return {"disponible": True, "appareils": appareils}


@router.delete("/appareils/{session_id}")
async def fermer_appareil(session_id: UUID, current_user: User = Depends(get_current_user)):
    """Ferme UN appareil de son propre compte."""
    ferme = await appareil.revoquer_une(current_user.id, session_id)
    if ferme:
        await log_action(action="session_appareil_fermee", user_id=str(current_user.id))
    return {"ok": ferme}


@router.post("/appareils/tout-fermer")
async def fermer_tous_les_appareils(current_user: User = Depends(get_current_user)):
    """Ferme TOUS ses appareils — le geste d'un poste perdu ou d'un doute."""
    combien = await appareil.revoquer_tout(current_user.id)
    await log_action(action="sessions_appareil_toutes_fermees", user_id=str(current_user.id))
    return {"ok": True, "fermes": combien}


@router.post("/logout")
async def logout(
    body: LogoutRequest | None = None,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    current_user: User = Depends(get_current_user),
):
    """Révoque le JWT actuel — inscrit le jti en blacklist jusqu'à expiration —
    ET ferme la session durable de cet appareil (03/09).

    Les deux vont ensemble : révoquer le seul JWT laisserait l'appareil se
    reconnecter tout seul à la page suivante.
    """
    if body and body.refresh_token:
        await appareil.revoquer(body.refresh_token)
    try:
        payload = decode_access_token(credentials.credentials)
        jti = payload.get("jti")
        exp = payload.get("exp")
        if jti and exp:
            async with get_db() as conn:
                await conn.execute(
                    """INSERT INTO revoked_tokens (jti, user_id, expires_at)
                       VALUES ($1, $2, to_timestamp($3))
                       ON CONFLICT DO NOTHING""",
                    UUID(jti), current_user.id, float(exp),
                )
    except Exception:
        pass  # Toujours renvoyer OK même si l'inscription blacklist échoue

    await log_action(action="logout", user_id=str(current_user.id))
    return {"ok": True}
