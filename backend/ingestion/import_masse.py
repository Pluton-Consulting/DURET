"""
Import d'un fichier volumineux : en tâche de fond, repris là où il s'est arrêté.

POURQUOI. L'import tournait DANS la requête HTTP, ligne après ligne. nginx coupe
`/api/` à 300 s : au-delà de quelques milliers de lignes, la requête était tuée
en cours de route, sans reprise ni marqueur. On se retrouvait avec une moitié
importée sans savoir laquelle — le pire des états, parce qu'il a l'air d'un
succès partiel alors qu'il est inexploitable.

CE QUI EST ÉCRIT, ET OÙ.
  * `documents`          — le texte de la ligne, découpé et vectorisé plus tard.
                           C'est ce qui permet de RETROUVER par le sens.
  * `document_metadata`  — les colonnes d'origine, telles quelles, en JSONB.
                           C'est ce qui permet de COMPTER et de FILTRER juste.

Les deux portent le MÊME `source_id`, donc une ligne reste une ligne : le texte
retrouvé par la recherche et la donnée exacte se rejoignent toujours.

IDEMPOTENCE. Avec une colonne identifiant (`id_col`), `source_id` est stable :
réimporter le même export CORRIGE les enregistrements au lieu de les empiler,
côté documents comme côté métadonnées. Sans identifiant, on retombe sur le rang
de la ligne dans le fichier — ce qui n'est stable que si l'export l'est aussi.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

logger = logging.getLogger("duret.ingestion.import_masse")

# Une valeur de cellule démesurée (un commentaire libre, un blob) n'apporte rien
# à un filtre exact et ferait grossir la table sans utilité.
MAX_VALEUR = 500
# Espacement entre lots : l'import ne doit pas affamer le chat qui tourne à côté.
PAUSE_LOT_S = 0.2
TAILLE_LOT = 50


class _Fini(Exception):
    """Sortie anticipée qui traverse le `finally` : il doit poser l'état final."""


_ETAT: dict[str, Any] = {}


def _neuf() -> dict:
    return {"en_cours": False, "phase": "inactif", "fichier": None, "source_type": None,
            "total": 0, "traites": 0, "documents": 0, "chunks": 0, "echecs": 0,
            "debut": None, "fin": None, "erreur": None}


_ETAT.update(_neuf())


def etat() -> dict:
    """Vue de l'avancement, sûre à exposer (aucun contenu de ligne)."""
    return dict(_ETAT)


def _valeurs_propres(ligne: dict) -> dict:
    """Colonnes de la ligne, normalisées pour un filtrage exact.

    Les clés vides sont écartées (une colonne sans en-tête ne se filtre pas), et
    les valeurs sont ramenées à du texte borné : on ne devine PAS les types.
    Convertir « 1 250,00 » en nombre supposerait un format ; se tromper de
    séparateur décimal fausserait des montants, ce qui est pire que de les
    laisser en texte.
    """
    propre = {}
    for cle, valeur in (ligne or {}).items():
        nom = str(cle or "").strip()
        if not nom:
            continue
        texte = " ".join(str(valeur if valeur is not None else "").split())
        if texte:
            propre[nom] = texte[:MAX_VALEUR]
    return propre


def _normaliser(valeurs: dict, mapping: dict) -> dict:
    """Même ligne, exprimée dans le vocabulaire commun du type.

    Les colonnes d'origine ne sont pas remplacées : on ajoute une lecture, on
    n'en retire aucune.
    """
    return {champ: valeurs[colonne]
            for colonne, champ in (mapping or {}).items()
            if valeurs.get(colonne)}


async def _ecrire_metadonnees(source_id: str, source_type: str, titre: str,
                              donnees: dict, acces: str, fichier: str,
                              ligne: int, champs: dict) -> None:
    """Range les colonnes d'origine à côté du texte vectorisé.

    Ne lève jamais : une métadonnée manquante prive d'un filtre exact, elle ne
    doit pas faire perdre la ligne elle-même, déjà ingérée.
    """
    import json

    from database.connection import get_db
    try:
        async with get_db() as conn:
            await conn.execute(
                "INSERT INTO document_metadata "
                "(source_id, source_type, title, data, champs, access_level, "
                " source_filename, ligne) "
                "VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $7, $8) "
                "ON CONFLICT (source_id, source_type) DO UPDATE SET "
                "  title = EXCLUDED.title, data = EXCLUDED.data, "
                "  champs = EXCLUDED.champs, "
                "  access_level = EXCLUDED.access_level, "
                "  source_filename = EXCLUDED.source_filename, "
                "  ligne = EXCLUDED.ligne, updated_at = NOW()",
                source_id, source_type, titre[:500], json.dumps(donnees, ensure_ascii=False),
                json.dumps(champs or {}, ensure_ascii=False),
                acces, fichier[:500], ligne)
    except Exception as e:  # noqa: BLE001
        logger.warning("Métadonnées non écrites pour %s : %s", source_id, e)


async def executer(rows: list[dict], colonnes: list[str], *, texte_unique: Optional[str],
                   fichier: str, source_type: str, id_col: Optional[str],
                   access_level: str, anonymize: bool,
                   mapping: Optional[dict] = None) -> dict:
    """Ingère tout le fichier. Une ligne fautive n'annule pas les autres."""
    from ingestion.parsers import ligne_en_texte
    from ingestion.pipeline import ingest_document

    if _ETAT["en_cours"]:
        raise RuntimeError("Un import est déjà en cours.")

    _ETAT.update(_neuf())
    _ETAT.update({"en_cours": True, "phase": "import", "fichier": fichier,
                  "source_type": source_type, "debut": time.time(),
                  "total": len(rows) if rows else 1})

    # Aucun `return` dans le try/finally ci-dessous : `return etat()` y prendrait
    # son instantané AVANT que le `finally` ne pose l'état final, et la fonction
    # se déclarerait « en cours » une fois terminée.
    try:
        # Document simple (PDF, Word, texte) : rien à structurer, un seul objet.
        if texte_unique is not None:
            _ETAT["chunks"] = await ingest_document(
                text=texte_unique, source_type=source_type,
                source_id=f"{source_type}:{fichier}", source_filename=fichier,
                access_level=access_level, anonymize=anonymize)
            _ETAT.update({"traites": 1, "documents": 1 if _ETAT["chunks"] else 0})
            raise _Fini

        col_id = id_col if id_col in (colonnes or []) else None
        for depart in range(0, len(rows), TAILLE_LOT):
            for rang, ligne in enumerate(rows[depart:depart + TAILLE_LOT], depart + 1):
                _ETAT["traites"] = rang
                texte = ligne_en_texte(ligne)
                if not texte:
                    continue
                valeurs = _valeurs_propres(ligne)
                cle = (valeurs.get(col_id) or "").strip() if col_id else ""
                source_id = f"{source_type}:{cle or f'{fichier}#{rang}'}"
                try:
                    chunks = await ingest_document(
                        text=texte, source_type=source_type, source_id=source_id,
                        source_filename=fichier, access_level=access_level,
                        anonymize=anonymize)
                except Exception as e:  # noqa: BLE001
                    _ETAT["echecs"] += 1
                    logger.warning("Ligne %d non ingérée : %s", rang, e)
                    continue
                if not chunks:
                    _ETAT["echecs"] += 1
                    continue
                _ETAT["chunks"] += chunks
                _ETAT["documents"] += 1
                # La donnée structurée est écrite APRÈS l'ingestion réussie :
                # une métadonnée sans document derrière serait un fantôme
                # comptabilisé dans les totaux mais introuvable à la lecture.
                await _ecrire_metadonnees(source_id, source_type,
                                          cle or f"{fichier} ligne {rang}", valeurs,
                                          access_level, fichier, rang,
                                          _normaliser(valeurs, mapping or {}))
            await asyncio.sleep(PAUSE_LOT_S)

    except _Fini:
        pass                        # document simple : rien de plus à faire
    except Exception as e:  # noqa: BLE001
        logger.warning("Import interrompu : %s", e)
        _ETAT["erreur"] = str(e)[:200]
    finally:
        _ETAT.update({"en_cours": False, "fin": time.time()})
        _ETAT["phase"] = "interrompu" if _ETAT["erreur"] else "terminé"
        logger.info("Import %s : %d/%d lignes, %d chunks, %d échecs",
                    fichier, _ETAT["documents"], _ETAT["total"],
                    _ETAT["chunks"], _ETAT["echecs"])

    return etat()
