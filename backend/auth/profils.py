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

from typing import Optional

# Les rôles qui ne partagent JAMAIS leur adresse — mêmes que ceux qui ouvrent
# une boîte sur simple demande (`mail.authorization.ROLES_ACCES_SUR_DEMANDE`).
ROLES_ADMIN = frozenset({"super_admin", "direction"})


def est_admin(role: Optional[str]) -> bool:
    return (role or "").strip().lower() in ROLES_ADMIN


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
    return [{"id": str(p["id"]), "nom": (p.get("name") or "").strip() or "Sans nom"}
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


# ── Accès base ───────────────────────────────────────────────────────────
async def profils_de(email: str, actifs: bool = True) -> list[dict]:
    """Les comptes qui portent cette adresse (insensible à la casse)."""
    from database.connection import get_db
    async with get_db() as conn:
        lignes = await conn.fetch(
            "SELECT id, email, name, role, actif FROM users "
            "WHERE lower(email) = lower($1) " + ("AND actif = true " if actifs else "") +
            "ORDER BY lower(coalesce(name, '')), created_at",
            (email or "").strip())
    return [dict(l) for l in lignes]


async def profils_partages(user_id: str) -> list[dict]:
    """Les profils entre lesquels CE compte peut basculer : ceux de son
    adresse, s'il en partage une et n'est pas administrateur. Sinon, rien."""
    from database.connection import get_db
    async with get_db() as conn:
        moi = await conn.fetchrow(
            "SELECT email, role FROM users WHERE id = $1::uuid AND actif = true", str(user_id))
    if not moi or est_admin(moi["role"]):
        return []
    profils = await profils_de(moi["email"])
    return profils if len(profils) > 1 else []
