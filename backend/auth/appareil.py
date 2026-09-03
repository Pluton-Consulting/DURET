"""
LA SESSION D'APPAREIL — prouver son identité une fois, pas tous les jours.

LE BESOIN (03/09, Noa) : « sans resaisir le mail et sans aller cliquer sur le
magic link à chaque fois, ça prend beaucoup trop de temps ».

LE MÉCANISME, en une phrase : le lien magique reste la seule porte d'entrée,
mais en la franchissant l'appareil reçoit un JETON DURABLE qu'il échange
ensuite, tout seul, contre un JWT frais. La personne ne revoit plus jamais
l'écran de connexion sur ce poste.

DEUX JETONS, DEUX MÉTIERS — les confondre serait l'erreur :
  · le JWT (`auth/jwt_handler.py`) est COURT (24 h) et porte les droits. Il ne
    se révoque qu'à la peine (liste noire `revoked_tokens`), donc il ne doit
    jamais être long ;
  · le jeton d'appareil est LONG (sans échéance par défaut) mais ne donne
    AUCUN droit par lui-même : il ne sert qu'à demander un JWT. Il vit dans une
    ligne de base, donc il se coupe d'un clic — c'est ce qui rend acceptable
    qu'il ne périme pas.

CE QUI EST STOCKÉ EST UNE EMPREINTE, jamais le jeton. Une lecture de la table
ne permet de se connecter nulle part.

DÉGRADATION. Si la migration 034 n'est pas encore appliquée, la connexion par
lien magique continue de marcher exactement comme avant — sans session durable,
avec un avertissement dans les journaux qui NOMME la migration. Un écran de
connexion qui reviendrait chaque jour est un désagrément ; un backend qui
refuse la connexion serait une panne.
"""
from __future__ import annotations

import hashlib
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import settings
from database.connection import get_db, schema_incomplet

logger = logging.getLogger("duret.auth.appareil")

# Ce que l'on dit quand la table manque — le nom de la migration, pas un 500 nu.
MIGRATION = "034_sessions_appareil"

# 32 octets d'aléa : de l'ordre du jeton de session d'un site bancaire, et le
# même calibre que le lien magique (`secrets.token_urlsafe(32)`).
OCTETS_JETON = 32


def hacher(jeton: str) -> str:
    """L'empreinte stockée en base. SHA-256 nu : le jeton est déjà 256 bits
    d'aléa, il n'a rien à dériver — un KDF lent n'ajouterait ici qu'une attente
    à chaque ouverture de page (ce n'est pas un mot de passe humain)."""
    return hashlib.sha256(jeton.encode("utf-8")).hexdigest()


# Reconnaissance volontairement grossière : on veut « Chrome sur Mac », pas une
# empreinte de navigateur. L'ordre compte — Edge et Chrome se déclarent tous
# deux « Chrome », Chrome se déclare aussi « Safari ».
_NAVIGATEURS = [
    ("Edg", "Edge"), ("OPR", "Opera"), ("Firefox", "Firefox"),
    ("Chrome", "Chrome"), ("Safari", "Safari"),
]
_SYSTEMES = [
    ("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"),
    ("Mac OS X", "Mac"), ("Macintosh", "Mac"), ("Windows", "Windows"),
    ("Linux", "Linux"),
]


def nommer_appareil(user_agent: str) -> str:
    """« Chrome sur Mac » — de quoi RECONNAÎTRE son poste dans la liste.

    Fonction pure : c'est ce qui la rend vérifiable au banc. Ce qu'on ne sait
    pas lire devient « Appareil inconnu » plutôt qu'une chaîne technique
    recopiée telle quelle — un en-tête brut à l'écran n'apprend rien à personne.
    """
    ua = (user_agent or "").strip()
    if not ua:
        return "Appareil inconnu"
    navigateur = next((nom for cle, nom in _NAVIGATEURS if cle in ua), "")
    systeme = next((nom for cle, nom in _SYSTEMES if cle in ua), "")
    if navigateur and systeme:
        return f"{navigateur} sur {systeme}"
    if navigateur or systeme:
        return navigateur or systeme
    # Ni l'un ni l'autre : un client non-navigateur (script, application). On
    # garde un fragment court, sans jamais dépasser la largeur d'une ligne.
    fragment = re.sub(r"[^\w .()/-]", "", ua)[:40].strip()
    return fragment or "Appareil inconnu"


def expiration(depuis: Optional[datetime] = None) -> Optional[datetime]:
    """L'échéance à poser, ou None quand la session est illimitée.

    `session_appareil_jours = 0` (le défaut, décision de Noa du 03/09) veut dire
    « illimité tant qu'on ne se déconnecte pas ». Toute autre valeur donne une
    échéance GLISSANTE : elle est repoussée à chaque utilisation, donc un poste
    dont on se sert ne se déconnecte jamais, et un poste oublié finit par tomber.
    """
    jours = int(getattr(settings, "session_appareil_jours", 0) or 0)
    if jours <= 0:
        return None
    return (depuis or datetime.now(timezone.utc)) + timedelta(days=jours)


async def creer(user_id, user_agent: str = "") -> Optional[str]:
    """Ouvre une session durable pour cet appareil et rend le jeton EN CLAIR.

    C'est la seule fois où le jeton existe hors du navigateur ; il n'est ni
    journalisé, ni renvoyé ailleurs. Rend None si la table manque — la
    connexion du jour reste valide, elle ne durera simplement pas.
    """
    jeton = secrets.token_urlsafe(OCTETS_JETON)
    try:
        async with get_db() as conn:
            await conn.execute(
                """INSERT INTO sessions_appareil (user_id, jeton_hash, appareil, expire_le)
                   VALUES ($1, $2, $3, $4)""",
                user_id, hacher(jeton), nommer_appareil(user_agent), expiration(),
            )
    except Exception as e:
        if schema_incomplet(e):
            logger.warning(
                "Session d'appareil non ouverte : la migration %s n'est pas appliquée "
                "sur ce serveur — la connexion reste valable %s h, puis le lien magique "
                "sera redemandé.", MIGRATION, settings.jwt_expire_hours)
        else:
            logger.error("Ouverture de session d'appareil impossible : %s", e)
        return None
    return jeton


async def compte_de(jeton: str) -> Optional[dict]:
    """Le compte derrière ce jeton, si la session est vivante — et la prolonge.

    Trois refus, tous silencieux pour l'appelant (un 401 ne dit pas POURQUOI à
    qui présente un jeton) : session inconnue ou révoquée, échéance passée,
    compte désactivé. Le dernier point compte : désactiver quelqu'un dans
    Paramètres doit fermer ses appareils, pas seulement l'empêcher de se
    reconnecter.
    """
    if not jeton:
        return None
    empreinte = hacher(jeton)
    maintenant = datetime.now(timezone.utc)
    try:
        async with get_db() as conn:
            row = await conn.fetchrow(
                """SELECT s.id, s.expire_le, u.id AS user_id, u.email, u.role
                     FROM sessions_appareil s
                     JOIN users u ON u.id = s.user_id
                    WHERE s.jeton_hash = $1
                      AND s.revoque_le IS NULL
                      AND u.actif = true""",
                empreinte,
            )
            if row is None:
                return None
            if row["expire_le"] is not None and row["expire_le"] < maintenant:
                return None
            # L'usage repousse l'échéance (quand il y en a une) et date la
            # ligne : c'est ce que la liste des appareils montre.
            await conn.execute(
                """UPDATE sessions_appareil
                      SET derniere_utilisation = $1, expire_le = $2
                    WHERE id = $3""",
                maintenant, expiration(maintenant), row["id"],
            )
    except Exception as e:
        if schema_incomplet(e):
            logger.warning("Session d'appareil ignorée : migration %s absente.", MIGRATION)
        else:
            logger.error("Lecture de session d'appareil impossible : %s", e)
        return None
    return {"id": str(row["id"]), "user_id": row["user_id"],
            "email": row["email"], "role": row["role"]}


async def revoquer(jeton: str) -> bool:
    """Ferme CET appareil (« Se déconnecter »). Idempotent."""
    if not jeton:
        return False
    try:
        async with get_db() as conn:
            fait = await conn.execute(
                """UPDATE sessions_appareil SET revoque_le = NOW()
                    WHERE jeton_hash = $1 AND revoque_le IS NULL""",
                hacher(jeton),
            )
    except Exception as e:
        if not schema_incomplet(e):
            logger.error("Révocation de session impossible : %s", e)
        return False
    return fait.endswith("1")


async def revoquer_une(user_id, session_id) -> bool:
    """Ferme un appareil DE SON PROPRE COMPTE, désigné dans la liste.

    Le `user_id` est dans la clause WHERE, pas seulement vérifié avant : sans
    lui, un identifiant deviné fermerait la session de quelqu'un d'autre.
    """
    try:
        async with get_db() as conn:
            fait = await conn.execute(
                """UPDATE sessions_appareil SET revoque_le = NOW()
                    WHERE id = $1 AND user_id = $2 AND revoque_le IS NULL""",
                session_id, user_id,
            )
    except Exception as e:
        if not schema_incomplet(e):
            logger.error("Révocation de session impossible : %s", e)
        return False
    return fait.endswith("1")


async def revoquer_tout(user_id) -> int:
    """Ferme TOUS les appareils d'un compte. Deux appelants : la personne
    elle-même (« déconnecter tous mes appareils », en cas de perte), et la
    désactivation d'un compte."""
    try:
        async with get_db() as conn:
            fait = await conn.execute(
                """UPDATE sessions_appareil SET revoque_le = NOW()
                    WHERE user_id = $1 AND revoque_le IS NULL""",
                user_id,
            )
    except Exception as e:
        if not schema_incomplet(e):
            logger.error("Révocation des sessions impossible : %s", e)
        return 0
    try:
        return int(fait.rsplit(" ", 1)[-1])
    except ValueError:
        return 0


async def lister(user_id) -> Optional[list[dict]]:
    """Les appareils vivants de ce compte, le plus récemment utilisé en tête.

    Rend None — et pas une liste vide — quand la table manque : « aucun
    appareil » et « je ne peux pas le savoir » ne se disent pas de la même
    façon à l'écran.
    """
    try:
        async with get_db() as conn:
            rows = await conn.fetch(
                """SELECT id, appareil, cree_le, derniere_utilisation, expire_le
                     FROM sessions_appareil
                    WHERE user_id = $1 AND revoque_le IS NULL
                      AND (expire_le IS NULL OR expire_le > NOW())
                    ORDER BY derniere_utilisation DESC""",
                user_id,
            )
    except Exception as e:
        if schema_incomplet(e):
            return None
        logger.error("Lecture des appareils impossible : %s", e)
        return None
    return [
        {
            "id": str(r["id"]),
            "appareil": r["appareil"],
            "depuis": r["cree_le"].isoformat() if r["cree_le"] else None,
            "derniere_utilisation": (r["derniere_utilisation"].isoformat()
                                     if r["derniere_utilisation"] else None),
            "expire_le": r["expire_le"].isoformat() if r["expire_le"] else None,
        }
        for r in rows
    ]
