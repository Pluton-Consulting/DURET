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
    async with get_db() as conn:
        user = await conn.fetchrow(
            "SELECT id FROM users WHERE email = $1 AND actif = true",
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
    if row["used"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Lien déjà utilisé")
    if row["expires_at"] < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Lien expiré")

    async with get_db() as conn:
        await conn.execute(
            "UPDATE verification_tokens SET used = true WHERE token = $1",
            body.token,
        )
        user = await conn.fetchrow(
            "SELECT * FROM users WHERE email = $1 AND actif = true",
            body.email,
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
    }


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
