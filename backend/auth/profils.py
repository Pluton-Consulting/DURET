"""
LES PROFILS D'UNE BOÎTE PARTAGÉE — plusieurs prénoms derrière une même adresse.

LA DEMANDE (11/09, Noa, Duret) : « tout le monde a le même mail » — la boîte
de l'entreprise, reliée par mot de passe d'application. Après le lien magique,
un compte qui n'est pas administrateur arrive sur un écran de cartes : on
clique sur son prénom, et l'on entre dans SA vue de l'application — son chat,
ses consignes, ses documents, ses tâches — comme si chacun avait son adresse.

LE MÉCANISME TIENT EN UNE IDÉE. Chaque prénom est une ligne de `users`, avec
son propre identifiant : tout ce qui est « à quelqu'un » est déjà rangé par
`users.id` (fils, messages, validations, atelier, connexions…). Il suffisait
de lever l'unicité de l'adresse (migration 040) et de faire CHOISIR, au moment
où le lien magique ne sait dire que « cette boîte ».

LA SÉCURITÉ, DITE TELLE QU'ELLE EST. Qui ouvre la boîte partagée peut entrer
sous n'importe lequel de ses prénoms — il n'y a pas de mot de passe par
prénom, c'est la boîte qui prouve l'identité, comme avant. D'où deux gardes,
ICI et pas à l'écran :
  * un compte ADMINISTRATEUR (super_admin, direction) ne partage jamais son
    adresse : sans quoi n'importe quel porteur de la boîte deviendrait
    administrateur en un clic ;
  * on ne passe d'un profil à l'autre qu'à l'intérieur de la MÊME adresse.

Fonctions pures d'abord (le banc les exécute), accès base ensuite.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
from typing import NamedTuple, Optional

logger = logging.getLogger("duret.auth.profils")

# Les rôles qui ne partagent JAMAIS leur adresse — mêmes que ceux qui ouvrent
# une boîte sur simple demande (`mail.authorization.ROLES_ACCES_SUR_DEMANDE`).
ROLES_ADMIN = frozenset({"super_admin", "direction"})


def est_admin(role: Optional[str]) -> bool:
    return (role or "").strip().lower() in ROLES_ADMIN


# ── Le code d'une carte (13/09) ──────────────────────────────────────────
# La direction peut avoir sa carte sur la page de connexion, derrière un code.
# Le super_admin n'est jamais une carte de la PAGE : depuis que le lien magique
# est coupé (15/09), il entre par le bouton « Admin » et son code
# (`cartes_admin`, `/api/auth/connexion/admin`).
ROLES_JAMAIS_EN_CARTE = frozenset({"super_admin"})
ROLES_CARTE_ADMIN = frozenset({"super_admin"})
ROLES_CODE_OBLIGATOIRE = frozenset({"direction"})
ESSAIS_CODE_MAX = 5
BLOCAGE_CODE_MINUTES = 15
_ITERATIONS = 200_000


def code_valide(code: Optional[str]) -> bool:
    """4 à 6 chiffres : se tape sur un téléphone, s'oublie peu."""
    return bool(re.fullmatch(r"\d{4,6}", (code or "").strip()))


def hacher_code(code: str) -> str:
    """L'empreinte stockée — sel propre, PBKDF2-SHA256. Jamais le code."""
    sel = secrets.token_bytes(16)
    brut = hashlib.pbkdf2_hmac("sha256", code.strip().encode(), sel, _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${sel.hex()}${brut.hex()}"


def code_correct(code: Optional[str], empreinte: Optional[str]) -> bool:
    try:
        algo, iterations, sel, attendu = (empreinte or "").split("$")
        if algo != "pbkdf2_sha256":
            return False
        calcule = hashlib.pbkdf2_hmac("sha256", (code or "").strip().encode(),
                                      bytes.fromhex(sel), int(iterations))
        return hmac.compare_digest(calcule.hex(), attendu)
    except (ValueError, TypeError):
        return False


# LE CODE SE RELIT (14/09, migration 042). Noa veut VOIR les codes depuis
# l'administration. L'empreinte ne se relit pas : on garde donc aussi le code
# chiffré (Fernet). La vérification reste sur l'empreinte — une clé changée rend
# le code illisible à l'écran, il continue d'ouvrir la carte.
#
# LA CLÉ EST SÉPARÉE DU SECRET JWT (16/09, audit D-19) : les deux n'ont ni le
# même usage ni la même vie — changer le secret des sessions rendait illisibles
# tous les codes, et une fuite de l'un donnait l'autre. `CODE_CHIFFREMENT_CLE`
# porte désormais la clé ; sans elle, on retombe sur l'ancienne dérivation pour
# ne rien perdre, et tout code relu est RÉÉCRIT avec la nouvelle clé
# (`rechiffrer_si_besoin`) : la rotation se fait sans perte, sans migration.
def _cles_fernet() -> list:
    """La clé d'écriture d'abord, les anciennes ensuite (lecture seulement)."""
    cles = []
    try:
        import base64
        from cryptography.fernet import Fernet
        from config import settings
        propre = str(getattr(settings, "code_chiffrement_cle", "") or "").strip()
        if propre:
            graine = hashlib.sha256(b"pluton:code-carte:" + propre.encode()).digest()
            cles.append(Fernet(base64.urlsafe_b64encode(graine)))
        ancienne = hashlib.sha256(b"pluton:code-carte:" + str(settings.jwt_secret_key).encode()).digest()
        cles.append(Fernet(base64.urlsafe_b64encode(ancienne)))
    except Exception:  # noqa: BLE001 — sans bibliothèque ni secret : code non relisible
        return []
    return cles


def _fernet():
    cles = _cles_fernet()
    return cles[0] if cles else None


def chiffrer_code(code: Optional[str]) -> Optional[str]:
    f = _fernet()
    if not code or f is None:
        return None
    return f.encrypt(code.strip().encode()).decode()


def dechiffrer_code(chiffre: Optional[str]) -> Optional[str]:
    """Le code en clair, lu avec la clé d'aujourd'hui ou celle d'hier."""
    if not chiffre:
        return None
    for f in _cles_fernet():
        try:
            return f.decrypt(chiffre.encode()).decode()
        except Exception:  # noqa: BLE001 — pas cette clé-là
            continue
    return None                      # clé perdue : illisible, pas une panne


def rechiffre_avec_la_cle_du_jour(chiffre: Optional[str]) -> Optional[str]:
    """Le même code, chiffré avec la clé d'écriture, ou None s'il l'est déjà
    (ou s'il est illisible). Sert la rotation : on réécrit ce qu'on relit."""
    cles = _cles_fernet()
    if not chiffre or len(cles) < 2:
        return None
    try:
        cles[0].decrypt(chiffre.encode())
        return None                  # déjà à jour
    except Exception:  # noqa: BLE001
        pass
    clair = dechiffrer_code(chiffre)
    return chiffrer_code(clair) if clair else None


def a_un_code(p: dict) -> bool:
    return bool(p.get("a_code") or p.get("code_pin_hash"))


def refus_sur_boite(role: str, nom: Optional[str], avec_code: bool,
                    existants: list[dict], soi: Optional[str] = None) -> Optional[str]:
    """Pourquoi ce profil ne peut PAS vivre sur la boîte de l'entreprise, ou None.

    `existants` : les comptes déjà sur l'adresse ; `soi` : l'identifiant du
    profil qu'on modifie (il ne se compte pas lui-même).
    """
    autres = [e for e in existants if str(e.get("id")) != str(soi or "")]
    r = (role or "").strip().lower()
    if r in ROLES_JAMAIS_EN_CARTE:
        return ("Un super administrateur garde sa propre adresse et le lien magique : "
                "la boîte de l'entreprise ouvre une carte sans mail.")
    if r in ROLES_CODE_OBLIGATOIRE and not avec_code:
        return ("Un profil de direction sur la boîte de l'entreprise a besoin d'un code "
                "(4 à 6 chiffres) : sans lui, n'importe qui entrerait en direction d'un clic.")
    if not normaliser_nom(nom):
        return ("Un profil de la boîte de l'entreprise a besoin d'un nom : c'est lui "
                "qui s'affiche sur sa carte à la connexion.")
    if any(normaliser_nom(e.get("name")) == normaliser_nom(nom) for e in autres):
        return f"Un profil « {(nom or '').strip()} » existe déjà sur cette adresse."
    return None


def normaliser_nom(nom: Optional[str]) -> str:
    """Pour comparer deux prénoms : casse et espaces ne font pas deux personnes."""
    return " ".join((nom or "").split()).lower()


def choisir(profils: list[dict], user_id: Optional[str] = None):
    """Qui entre, parmi les comptes ACTIFS d'une adresse.

    Rend le profil retenu, None si personne ne peut entrer, ou la chaîne
    « choix » quand il faut montrer les cartes. Un `user_id` désigne le
    prénom cliqué : il doit appartenir à l'adresse, et un administrateur ne
    s'atteint jamais par ce chemin quand l'adresse est partagée.
    """
    if not profils:
        return None
    if user_id:
        retenu = next((p for p in profils if str(p["id"]) == str(user_id)), None)
        if retenu is None:
            return None
        if len(profils) > 1 and est_admin(retenu.get("role")):
            return None
        return retenu
    if len(profils) == 1:
        return profils[0]
    return "choix"


def cartes(profils: list[dict]) -> list[dict]:
    """Ce que l'écran des cartes montre : l'identifiant et le nom, rien d'autre
    (ni rôle, ni adresse — tout le monde la connaît déjà). Les administrateurs
    n'y figurent pas."""
    return [{"id": str(p["id"]), "nom": (p.get("name") or "").strip() or "Sans nom",
             "code": a_un_code(p)}
            for p in profils if not est_admin(p.get("role"))]


def refus_creation(role: str, nom: Optional[str], existants: list[dict]) -> Optional[str]:
    """Pourquoi un compte ne peut PAS être créé sur cette adresse, ou None.

    `existants` : les comptes (actifs ou non) qui portent déjà l'adresse.
    """
    if not existants:
        return None
    if est_admin(role):
        return ("Un compte administrateur a sa propre adresse : cette adresse est déjà "
                "utilisée. Sinon, n'importe qui ouvrant la boîte pourrait entrer en "
                "administrateur.")
    if any(est_admin(e.get("role")) for e in existants):
        return ("Cette adresse appartient à un compte administrateur : elle ne peut pas "
                "être partagée avec d'autres profils.")
    if not normaliser_nom(nom):
        return ("Cette adresse est déjà utilisée : pour créer un autre profil dessus, "
                "donnez-lui un prénom (c'est lui qui s'affichera sur la carte).")
    if any(normaliser_nom(e.get("name")) == normaliser_nom(nom) for e in existants):
        return f"Un profil « {(nom or '').strip()} » existe déjà sur cette adresse."
    return None


def meme_adresse(a: Optional[str], b: Optional[str]) -> bool:
    return bool(a and b) and a.strip().lower() == b.strip().lower()


def en_carte(p: dict) -> bool:
    """Ce compte a-t-il une carte sur la page de connexion ? Jamais le
    super_admin ; la direction seulement derrière un code."""
    r = (p.get("role") or "").strip().lower()
    if r in ROLES_JAMAIS_EN_CARTE:
        return False
    if r in ROLES_CODE_OBLIGATOIRE and not a_un_code(p):
        return False
    return bool(p.get("actif", True))


def cartes_de_connexion(profils: list[dict], boite: Optional[str] = None) -> list[dict]:
    """LA PAGE DE CONNEXION : les cartes des profils, à choisir SANS lien magique.

    (14/09, demande de Noa : « chacun peut se connecter à son compte avec son
    prénom même si l'adresse mail n'est pas configurée ».) Les cartes ne
    dépendent PLUS de la boîte de l'entreprise : jusqu'ici, sans boîte reliée,
    aucune carte ne s'affichait, et un profil créé avant de relier la boîte
    n'avait aucun moyen d'entrer. L'adresse ne sert désormais qu'au mail.

    Seulement : des comptes actifs ; jamais un super_admin ; la direction
    seulement si elle a un code. La carte dit s'il faut un code (`code`),
    jamais le rôle ni l'adresse. `boite` n'est plus lu (gardé pour les appels).
    """
    return [{"id": str(p["id"]), "nom": (p.get("name") or "").strip() or "Sans nom",
             "code": a_un_code(p)}
            for p in profils if en_carte(p)]


def entree_par_carte(profils: list[dict], boite: Optional[str], user_id: Optional[str]):
    """Le profil qu'ouvre un clic sur une carte, ou None.

    Tout est revérifié ici, rien n'est cru de l'écran : l'identifiant doit
    être une des cartes que `cartes_de_connexion` montrerait — donc jamais un
    super_admin, jamais une direction sans code, jamais un compte désactivé.
    """
    if not user_id:
        return None
    permis = {c["id"] for c in cartes_de_connexion(profils, boite)}
    if str(user_id) not in permis:
        return None
    return next((p for p in profils if str(p["id"]) == str(user_id)), None)


# ── Accès base ───────────────────────────────────────────────────────────
async def _profils(filtre: str, *args) -> list[dict]:
    """`a_code` dit si la carte a un code — jamais l'empreinte. Sans la
    migration 041, aucune carte n'a de code (et la direction n'en a donc pas)."""
    from database.connection import get_db, schema_incomplet
    async with get_db() as conn:
        try:
            lignes = await conn.fetch(
                "SELECT id, email, name, role, actif, (code_pin_hash IS NOT NULL) AS a_code "
                "FROM users " + filtre, *args)
        except Exception as e:  # noqa: BLE001
            if not schema_incomplet(e):
                raise
            lignes = await conn.fetch(
                "SELECT id, email, name, role, actif, false AS a_code FROM users " + filtre, *args)
    return [dict(l) for l in lignes]


async def profils_de(email: str, actifs: bool = True) -> list[dict]:
    """Les comptes qui portent cette adresse (insensible à la casse)."""
    return await _profils(
        "WHERE lower(email) = lower($1) " + ("AND actif = true " if actifs else "") +
        "ORDER BY lower(coalesce(name, '')), created_at", (email or "").strip())


async def profils_tous(actifs: bool = True) -> list[dict]:
    """Tous les comptes, dans l'ordre des cartes (14/09 : les cartes ne
    dépendent plus d'une adresse)."""
    return await _profils(("WHERE actif = true " if actifs else "") +
                          "ORDER BY lower(coalesce(name, '')), created_at")


async def profils_partages(user_id: str) -> list[dict]:
    """Les profils entre lesquels CE compte peut basculer (« Changer de
    profil ») : les mêmes cartes que la page de connexion (14/09 : plus
    seulement celles de son adresse). Rien pour un administrateur, rien s'il
    n'y a pas d'autre carte que la sienne."""
    from database.connection import get_db
    async with get_db() as conn:
        moi = await conn.fetchrow(
            "SELECT email, role FROM users WHERE id = $1::uuid AND actif = true", str(user_id))
    if not moi or est_admin(moi["role"]):
        return []
    profils = [p for p in await profils_tous() if en_carte(p)]
    return profils if len(profils) > 1 else []


async def code_obligatoire(role: Optional[str], email: Optional[str]) -> bool:
    """La direction garde un code dès que son adresse est partagée — la boîte
    de l'entreprise ou une adresse que porte un autre profil : sans lui, sa
    carte n'existe pas et n'importe qui entrerait en direction d'un clic."""
    if (role or "").strip().lower() not in ROLES_CODE_OBLIGATOIRE:
        return False
    if meme_adresse(email, await adresse_partagee()):
        return True
    return len(await profils_de(email or "", actifs=False)) > 1


def cartes_admin(profils: list[dict]) -> list[dict]:
    """Les cartes du bouton « Admin » : les super_admin actifs, TOUJOURS à code."""
    return [{"id": str(p["id"]), "nom": (p.get("name") or "Administrateur").strip() or "Administrateur",
             "code": True}
            for p in profils
            if (p.get("role") or "").strip().lower() in ROLES_CARTE_ADMIN and p.get("actif", True)]


def code_admin_defaut() -> str:
    try:
        from config import settings
        return str(getattr(settings, "code_admin_defaut", "") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


class Verdict(NamedTuple):
    """Ce que dit le contrôle d'un code. `ok` seul autorise l'entrée.

    `raison` (quand on refuse) : « code_requis », « code_faux », « code_bloque »,
    « code_a_poser » (le code de première entrée a déjà servi),
    « indisponible » (schéma incomplet, profil inconnu, configuration illisible —
    un défaut d'installation ne doit JAMAIS ouvrir la porte).
    `doit_changer` : entré avec le code de première entrée — il faut en poser un.
    """
    ok: bool
    raison: Optional[str] = None
    doit_changer: bool = False


AUTORISE = Verdict(True)


async def _verdict_sous_verrou(conn, user_id: str, code: Optional[str], attendu: Optional[str],
                               exige: bool, avec_044: bool, refus_technique: "Verdict",
                               voie_admin: bool = False) -> "Verdict":
    """Le contrôle lui-même, la ligne du profil VERROUILLÉE (`FOR UPDATE`) :
    deux essais simultanés ne se recouvrent plus."""
    from datetime import datetime, timedelta, timezone
    colonne = "code_defaut_le" if avec_044 else "NULL::timestamptz AS code_defaut_le"
    ligne = await conn.fetchrow(
        f"SELECT code_pin_hash, code_pin_echecs, code_pin_bloque_jusqu, {colonne} "
        "FROM users WHERE id = $1::uuid FOR UPDATE", str(user_id))
    if ligne is None:
        logger.warning("Code de carte : profil inconnu — entrée refusée.")
        return refus_technique
    empreinte = ligne["code_pin_hash"]
    premiere_entree = empreinte is None and attendu is not None
    if premiere_entree and not avec_044:
        # Sans la 044, on ne saurait pas que le code de première entrée a déjà
        # servi : il deviendrait un accès permanent. On refuse.
        logger.warning("Migration 044 absente : le code de première entrée est refusé.")
        return refus_technique
    if premiere_entree and ligne["code_defaut_le"] is not None:
        return Verdict(False, "code_a_poser")      # il a déjà servi : passer par le script
    if empreinte is None and not premiere_entree:
        if voie_admin:
            # Aucun code posé, et aucun code de première entrée utilisable : la
            # reprise passe par `scripts/code_admin.py`, sur le serveur.
            logger.warning("Entrée administrateur : aucun code posé — reprise par le script.")
            return Verdict(False, "code_a_poser")
        if exige:
            logger.warning("Code de carte exigé, aucune empreinte enregistrée — entrée refusée.")
            return refus_technique
        return AUTORISE                            # carte ordinaire, sans code : d'un clic
    maintenant = datetime.now(timezone.utc)
    if ligne["code_pin_bloque_jusqu"] and ligne["code_pin_bloque_jusqu"] > maintenant:
        return Verdict(False, "code_bloque")
    if not (code or "").strip():
        return Verdict(False, "code_requis")
    juste = (hmac.compare_digest((code or "").strip(), attendu or "") if premiere_entree
             else code_correct(code, empreinte))
    if juste:
        if premiere_entree:
            await conn.execute(
                "UPDATE users SET code_pin_echecs = 0, code_pin_bloque_jusqu = NULL, "
                "code_defaut_le = $2 WHERE id = $1::uuid", str(user_id), maintenant)
            return Verdict(True, None, doit_changer=True)
        await conn.execute("UPDATE users SET code_pin_echecs = 0, code_pin_bloque_jusqu = NULL "
                           "WHERE id = $1::uuid", str(user_id))
        return AUTORISE
    echecs = int(ligne["code_pin_echecs"] or 0) + 1
    if echecs >= ESSAIS_CODE_MAX:
        await conn.execute(
            "UPDATE users SET code_pin_echecs = 0, code_pin_bloque_jusqu = $2 WHERE id = $1::uuid",
            str(user_id), maintenant + timedelta(minutes=BLOCAGE_CODE_MINUTES))
        return Verdict(False, "code_bloque")
    await conn.execute("UPDATE users SET code_pin_echecs = $2 WHERE id = $1::uuid",
                       str(user_id), echecs)
    return Verdict(False, "code_faux")


async def controler_code(user_id: str, code: Optional[str], defaut: Optional[str] = None,
                         exige: bool = False) -> Verdict:
    """Vérifie le code d'une carte, compte les échecs, bloque au cinquième.

    FAIL-CLOSED (16/09, audit D-19). Avant, un schéma incomplet, un profil
    inconnu ou une empreinte absente rendaient None — et None voulait dire
    « entre ». Désormais, dès qu'un code est EXIGÉ (carte à code, entrée
    administrateur), tout ce qui empêche de le vérifier REFUSE, avec la raison
    « indisponible » : un défaut d'installation n'ouvre jamais la porte. Un
    profil ordinaire volontairement sans code garde son entrée d'un clic.

    `defaut` : le code de PREMIÈRE ENTRÉE d'un administrateur qui n'en a pas
    encore posé. Il ne sert QU'UNE FOIS (colonne `code_defaut_le`, migration
    044) et oblige à en poser un vrai ; ensuite, seul le script d'exploitation
    `scripts/code_admin.py` peut en redonner un.
    """
    from database.connection import get_db, schema_incomplet
    refus_technique = Verdict(False, "indisponible") if (exige or defaut) else AUTORISE
    attendu = defaut.strip() if (defaut and code_valide(defaut)) else None
    # Deux tours au plus : avec la colonne de la 044, puis sans (une requête
    # refusée annule toute la transaction — il faut en rouvrir une).
    for avec_044 in (True, False):
        try:
            async with get_db() as conn:
                async with conn.transaction():
                    return await _verdict_sous_verrou(conn, user_id, code, attendu, exige,
                                                      avec_044, refus_technique,
                                                      voie_admin=defaut is not None)
        except Exception as e:  # noqa: BLE001 — une base muette ne doit pas ouvrir la porte
            if schema_incomplet(e) and avec_044:
                continue
            logger.warning("Code de carte : contrôle impossible (%s) — entrée refusée.",
                           type(e).__name__)
            if exige or defaut:
                return Verdict(False, "indisponible")
            raise
    logger.warning("Code de carte : schéma incomplet (migrations 041/042/044) — entrée refusée.")
    return refus_technique


async def adresse_partagee() -> Optional[str]:
    """L'adresse de la boîte de l'entreprise (Paramètres → Clés API, ou .env) :
    celle que partagent les profils des cartes. None si aucune n'est reliée."""
    try:
        from llm.cles import rafraichir
        await rafraichir()
    except Exception:  # noqa: BLE001 — sans cache de clés, le .env fait foi
        pass
    try:
        from mail.imap import boite_unique
        return boite_unique()
    except Exception:  # noqa: BLE001
        return None
