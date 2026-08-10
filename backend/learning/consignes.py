"""
Consignes permanentes : apprendre quelque chose à l'assistant depuis le chat.

CE QUE ÇA RÉSOUT. La mémoire d'entreprise retrouve par ressemblance : une
connaissance remonte quand la question lui ressemble. Parfait pour un fait,
inutilisable pour une règle de comportement. « Chez nous, "le serveur" désigne
le NAS » doit être présent AVANT que le modèle choisisse son action, à chaque
tour, que la question y ressemble ou non — sinon la règle s'applique une fois
sur deux, ce qui est pire qu'une règle absente : personne ne peut prévoir quand
elle vaudra.

Les consignes sont donc INJECTÉES, jamais cherchées.

CE QUI LES BORNE, et pourquoi c'est essentiel. Elles occupent la place du prompt
système à chaque appel. Sans limite, elles finiraient par le noyer : quarante
consignes contradictoires accumulées en six mois valent moins que zéro, parce
que le modèle en suivra une au hasard. D'où un plafond par personne, un plafond
de caractères, et l'obligation de pouvoir les LIRE et les RETIRER aussi
facilement qu'on les ajoute.

QUI PEUT ENSEIGNER QUOI. Chacun peut poser ses propres consignes. Écrire pour
TOUTE L'ENTREPRISE change le comportement de l'assistant chez les collègues :
réservé à la direction et à l'administrateur.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("duret.learning.consignes")

MAX_PAR_PERSONNE = 25
MAX_ENTREPRISE = 40
MAX_CARACTERES = 400
MAX_TOTAL_INJECTE = 4000

# Rôles autorisés à poser une consigne valable pour tout le monde.
ROLES_ENTREPRISE = ("super_admin", "direction")


def peut_enseigner_a_tous(role: str | None) -> bool:
    return (role or "").strip() in ROLES_ENTREPRISE


async def ajouter(texte: str, user, pour_tous: bool = False,
                  access_level: str = "all") -> dict:
    """Enregistre une consigne. Rend un compte rendu, ne lève pas."""
    from database.connection import get_db

    propre = " ".join((texte or "").split())[:MAX_CARACTERES]
    if len(propre) < 5:
        return {"ok": False, "message": "Consigne trop courte pour être utile."}

    role = getattr(user, "role", "")
    if pour_tous and not peut_enseigner_a_tous(role):
        return {"ok": False,
                "message": ("Seule la direction peut poser une consigne valable pour "
                            "toute l'entreprise. Celle-ci sera enregistrée pour vous "
                            "seul si vous la reformulez sans « pour tout le monde ».")}

    proprietaire = None if pour_tous else str(getattr(user, "id", "") or "")
    if not pour_tous and not proprietaire:
        return {"ok": False, "message": "Compte non identifié."}

    try:
        async with get_db() as conn:
            plafond = MAX_ENTREPRISE if pour_tous else MAX_PAR_PERSONNE
            actuel = await conn.fetchval(
                "SELECT COUNT(*) FROM consignes WHERE actif "
                + ("AND user_id IS NULL" if pour_tous else "AND user_id = $1::uuid"),
                *([] if pour_tous else [proprietaire]))
            if (actuel or 0) >= plafond:
                return {"ok": False, "nombre": actuel,
                        "message": (f"Limite atteinte ({plafond} consignes). Retirez-en "
                                    "une avant d'en ajouter : au-delà, elles se diluent "
                                    "et le modèle n'en suit plus aucune de façon fiable.")}

            await conn.execute(
                "INSERT INTO consignes (texte, user_id, access_level, cree_par) "
                "VALUES ($1, $2::uuid, $3, $4::uuid) "
                # Réactiver plutôt que dupliquer : réapprendre une consigne
                # retirée est un geste normal, pas une erreur.
                "ON CONFLICT (COALESCE(user_id, '00000000-0000-0000-0000-000000000000'::uuid), "
                "             lower(texte)) WHERE actif DO NOTHING",
                propre, proprietaire, access_level,
                str(getattr(user, "id", "") or "") or None)
    except Exception as e:  # noqa: BLE001
        logger.warning("Consigne non enregistrée : %s", e)
        return {"ok": False, "message": f"La consigne n'a pas pu être enregistrée ({e})."}

    logger.info("Consigne ajoutée (%s) : %s",
                "entreprise" if pour_tous else "personnelle", propre[:80])
    return {"ok": True, "texte": propre,
            "portee": "toute l'entreprise" if pour_tous else "vous seul",
            "message": ("C'est retenu. Cette consigne s'appliquera désormais à chaque "
                        "échange, sans qu'il faille la rappeler.")}


async def lister(user) -> list[dict]:
    """Consignes actives visibles par cette personne. Ne lève jamais."""
    from database.connection import get_db
    from security.acces import niveaux_visibles

    uid = str(getattr(user, "id", "") or "") or None
    niveaux = sorted(niveaux_visibles(getattr(user, "role", "")))
    try:
        async with get_db() as conn:
            lignes = await conn.fetch(
                "SELECT id, texte, user_id, created_at FROM consignes "
                "WHERE actif AND ("
                "      (user_id IS NULL AND access_level = ANY($2::text[]))"
                "   OR (user_id = $1::uuid)) "
                "ORDER BY user_id NULLS FIRST, created_at",
                uid, niveaux)
    except Exception as e:  # noqa: BLE001
        logger.info("Consignes illisibles : %s", e)
        return []
    return [{"id": str(l["id"]), "texte": l["texte"],
             "portee": "entreprise" if l["user_id"] is None else "personnelle"}
            for l in lignes]


async def retirer(reference: str, user) -> dict:
    """Désactive une consigne, par son identifiant ou son texte."""
    from database.connection import get_db

    ref = (reference or "").strip()
    if not ref:
        return {"ok": False, "message": "Précisez la consigne à retirer."}

    uid = str(getattr(user, "id", "") or "") or None
    peut_tous = peut_enseigner_a_tous(getattr(user, "role", ""))
    try:
        async with get_db() as conn:
            # On ne retire QUE ce qu'on a le droit de retirer : sa propre
            # consigne, ou une consigne d'entreprise si l'on est direction.
            lignes = await conn.fetch(
                "UPDATE consignes SET actif = false "
                "WHERE actif AND (user_id = $1::uuid OR (user_id IS NULL AND $2)) "
                "  AND (id::text = $3 OR lower(texte) LIKE '%' || lower($3) || '%') "
                "RETURNING texte",
                uid, peut_tous, ref)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": f"Retrait impossible ({e})."}

    if not lignes:
        return {"ok": False,
                "message": ("Aucune consigne correspondante que vous puissiez retirer. "
                            "Demandez la liste pour voir leurs formulations exactes.")}
    return {"ok": True, "retirees": [l["texte"] for l in lignes],
            "message": f"{len(lignes)} consigne(s) retirée(s)."}


async def texte_injecte(user_id: str | None, role: str | None) -> str:
    """Bloc à coller dans le prompt système. Vide si rien à dire.

    Appelé à CHAQUE tour : il doit être bon marché et ne jamais lever. Une
    consigne illisible ne doit pas empêcher de répondre.
    """
    from database.connection import get_db
    from security.acces import niveaux_visibles

    try:
        async with get_db() as conn:
            lignes = await conn.fetch(
                "SELECT texte FROM consignes WHERE actif AND ("
                "      (user_id IS NULL AND access_level = ANY($2::text[]))"
                "   OR (user_id = $1::uuid)) "
                "ORDER BY user_id NULLS FIRST, created_at LIMIT 80",
                str(user_id) if user_id else None,
                sorted(niveaux_visibles(role)))
    except Exception as e:  # noqa: BLE001
        logger.debug("Consignes non injectées : %s", e)
        return ""

    retenues, total = [], 0
    for l in lignes:
        t = (l["texte"] or "").strip()
        if not t:
            continue
        # Plafond global : au-delà, les consignes noieraient le reste du prompt
        # et se diluteraient entre elles.
        if total + len(t) > MAX_TOTAL_INJECTE:
            logger.info("Consignes tronquées à %d caractères", MAX_TOTAL_INJECTE)
            break
        retenues.append(t)
        total += len(t)

    if not retenues:
        return ""
    return ("\n\nCONSIGNES DE L'ENTREPRISE — apprises par les utilisateurs, elles "
            "priment sur tes habitudes générales et s'appliquent à CHAQUE échange :\n"
            + "\n".join(f"- {t}" for t in retenues))
