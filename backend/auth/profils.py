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
import re
import secrets
from typing import Optional

# Les rôles qui ne partagent JAMAIS leur adresse — mêmes que ceux qui ouvrent
# une boîte sur simple demande (`mail.authorization.ROLES_ACCES_SUR_DEMANDE`).
ROLES_ADMIN = frozenset({"super_admin", "direction"})


def est_admin(role: Optional[str]) -> bool:
    return (role or "").strip().lower() in ROLES_ADMIN


# ── Le code d'une carte (13/09) ──────────────────────────────────────────
# La direction peut avoir sa carte sur la page de connexion, derrière un code.
# Le super_admin, jamais : c'est le compte du développeur, il garde le lien.
ROLES_JAMAIS_EN_CARTE = frozenset({"super_admin"})
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
# chiffré (Fernet, clé dérivée du secret JWT). La vérification reste sur
# l'empreinte — un secret changé rend le code illisible à l'écran, il continue
# d'ouvrir la carte.
def _fernet():
    try:
        import base64
        from cryptography.fernet import Fernet
        from config import settings
        cle = hashlib.sha256(b"pluton:code-carte:" + str(settings.jwt_secret_key).encode()).digest()
        return Fernet(base64.urlsafe_b64encode(cle))
    except Exception:  # noqa: BLE001 — sans bibliothèque ou sans secret : code non relisible
        return None


def chiffrer_code(code: Optional[str]) -> Optional[str]:
    f = _fernet()
    if not code or f is None:
        return None
    return f.encrypt(code.strip().encode()).decode()


def dechiffrer_code(chiffre: Optional[str]) -> Optional[str]:
    f = _fernet()
    if not chiffre or f is None:
        return None
    try:
        return f.decrypt(chiffre.encode()).decode()
    except Exception:  # noqa: BLE001 — secret changé : illisible, pas une panne
        return None


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


async def controler_code(user_id: str, code: Optional[str]) -> Optional[str]:
    """Vérifie le code d'une carte, compte les échecs, bloque au cinquième.

    Rend None si l'entrée est permise (pas de code, ou le bon), sinon la
    raison : « code_requis », « code_faux », « code_bloque ». Un code faux
    n'apprend rien d'autre ; le blocage est dit, pour qu'on n'insiste pas.
    """
    from datetime import datetime, timedelta, timezone
    from database.connection import get_db, schema_incomplet
    async with get_db() as conn:
        try:
            ligne = await conn.fetchrow(
                "SELECT code_pin_hash, code_pin_echecs, code_pin_bloque_jusqu "
                "FROM users WHERE id = $1::uuid", str(user_id))
        except Exception as e:  # noqa: BLE001
            if schema_incomplet(e):
                return None
            raise
        if not ligne or not ligne["code_pin_hash"]:
            return None
        maintenant = datetime.now(timezone.utc)
        if ligne["code_pin_bloque_jusqu"] and ligne["code_pin_bloque_jusqu"] > maintenant:
            return "code_bloque"
        if not (code or "").strip():
            return "code_requis"
        if code_correct(code, ligne["code_pin_hash"]):
            await conn.execute(
                "UPDATE users SET code_pin_echecs = 0, code_pin_bloque_jusqu = NULL "
                "WHERE id = $1::uuid", str(user_id))
            return None
        echecs = int(ligne["code_pin_echecs"] or 0) + 1
        if echecs >= ESSAIS_CODE_MAX:
            await conn.execute(
                "UPDATE users SET code_pin_echecs = 0, code_pin_bloque_jusqu = $2 "
                "WHERE id = $1::uuid", str(user_id),
                maintenant + timedelta(minutes=BLOCAGE_CODE_MINUTES))
            return "code_bloque"
        await conn.execute("UPDATE users SET code_pin_echecs = $2 WHERE id = $1::uuid",
                           str(user_id), echecs)
        return "code_faux"


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
