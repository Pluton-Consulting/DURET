"""
Skill natif : restituer ce que l'assistant a APPRIS.

« Que sais-tu de notre entreprise ? » n'est pas une question de recherche, c'est
une question d'INVENTAIRE. La recherche sémantique y échoue par construction :
elle compare une formulation abstraite à des faits concrets, la similarité passe
sous le seuil, et rien ne remonte — alors que la campagne d'enrichissement vient
d'écrire cinquante-cinq connaissances et quarante-huit manières de faire.

Observé exactement ainsi en production, campagne terminée : « mes recherches
n'ont rien donné », suivi d'une proposition de relancer la campagne qui venait
d'aboutir.

Ici, aucun embedding, aucun seuil : on LIT ce qui a été appris, dans l'ordre où
ça a été écrit. Le cloisonnement par rôle reste appliqué — une connaissance
rangée en accès direction ne remonte pas à un profil terrain.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("duret.skills.connaissances")

# Ce que la campagne et le débrief écrivent en mémoire.
TYPES_APPRIS = ("apprentissage", "procedure")

MAX_ELEMENTS = 40
MAX_EXTRAIT = 400


async def connaissances_acquises(data: dict, user) -> dict:
    """Ce que l'assistant a retenu, listé — pas cherché."""
    from database.connection import get_db
    from security.acces import niveaux_visibles

    sujet = (data.get("sujet") or "").strip()
    niveaux = sorted(niveaux_visibles(getattr(user, "role", "")))

    # Une requête PAR TYPE, et non une seule tronquée. Un plafond global trié par
    # date rendrait, sur un corpus déséquilibré, quarante procédures et zéro
    # connaissance : la réponse paraîtrait complète tout en étant amputée d'une
    # moitié du sujet. Chaque catégorie a donc sa part.
    par_type: dict[str, list[dict]] = {t: [] for t in TYPES_APPRIS}
    try:
        async with get_db() as conn:
            for type_source in TYPES_APPRIS:
                # Filtre LEXICAL et non sémantique : sur une question d'inventaire,
                # « devis » doit rendre ce qui CONTIENT « devis », pas ce qui lui
                # ressemble vaguement.
                clauses = ["source_type = ANY($1::text[])",
                           "access_level = ANY($2::text[])"]
                params: list = [[type_source], niveaux]
                if sujet:
                    params.append(f"%{sujet}%")
                    clauses.append(f"(content ILIKE ${len(params)} "
                                   f"OR COALESCE(source_filename, '') ILIKE ${len(params)})")
                params.append(MAX_ELEMENTS // len(TYPES_APPRIS))
                par_type[type_source] = list(await conn.fetch(
                    f"SELECT source_type, source_filename, content, created_at "
                    f"FROM documents WHERE {' AND '.join(clauses)} "
                    f"ORDER BY created_at DESC LIMIT ${len(params)}",
                    *params))
    except Exception as e:  # noqa: BLE001 - une lecture ratée n'est pas une panne du chat
        logger.warning("Lecture des connaissances impossible : %s", e)
        return {"nombre": 0, "message": "La mémoire est momentanément indisponible."}

    def _presenter(lignes) -> list[dict]:
        return [{"titre": (l["source_filename"] or "").strip() or "(sans titre)",
                 "extrait": " ".join((l["content"] or "").split())[:MAX_EXTRAIT]}
                for l in lignes]

    connaissances = _presenter(par_type["apprentissage"])
    procedures = _presenter(par_type["procedure"])

    total = len(connaissances) + len(procedures)
    if not total:
        return {
            "nombre": 0, "sujet": sujet,
            "message": (f"Rien d'appris sur « {sujet} »." if sujet else
                        "L'assistant n'a encore rien appris : aucune campagne "
                        "d'enrichissement n'a produit de connaissances, ou celles "
                        "qui existent ne sont pas visibles à ce profil."),
        }

    return {
        "nombre": total,
        "sujet": sujet or None,
        "connaissances": connaissances,
        "procedures": procedures,
        "note": (f"{len(connaissances)} connaissance(s) et {len(procedures)} manière(s) "
                 f"de faire, les plus récentes d'abord (au plus {MAX_ELEMENTS}). "
                 "Ce sont des ACQUIS : présente-les, ne relance pas de campagne."),
    }
