"""
CHANGER DE MODÈLE D'EMBEDDING, ET RE-VECTORISER TOUT LE CORPUS.

POURQUOI CE MODULE EXISTE (02/09, demande de Noa). Deux vecteurs ne sont
comparables que s'ils viennent du MÊME modèle : une « distance » entre un
vecteur Gemini et un vecteur Ollama n'a aucun sens géométrique, même quand les
deux ont 1536 composantes. Changer de modèle sans re-vectoriser ne casse donc
rien de visible — c'est bien pire : la recherche continue de répondre, avec des
résultats faux que rien ne signale.

CE QUI A DÉCLENCHÉ LE CHANTIER, MESURÉ EN PRODUCTION le 02/09 : 9 427 morceaux,
dont 2 913 vectorisés seulement. Les 6 514 autres attendent depuis des jours
derrière un quota Gemini épuisé en permanence (pauses jusqu'à 480 s, cadence
tombée à 20 s). La sortie n'est pas d'attendre, c'est de changer de fournisseur.

LES TROIS PIÈGES QUE CE MODULE FERME :

  1. LA DIMENSION SE MESURE, ELLE NE SE DEVINE PAS. Chaque modèle rend une
     taille de vecteur qui lui est propre (768, 1024, 1536, 3072...), les
     catalogues ne l'annoncent pas, et une table codée en dur se périme au
     premier modèle ajouté par le fournisseur. On demande donc UN embedding
     d'essai au modèle choisi et on mesure ce qui revient. C'est la seule
     source de vérité qui ne mente jamais.

  2. LA BASE PORTE DEUX COLONNES DE VECTEURS, pas une : `documents.embedding`
     (le corpus) et `conversation_memoire.embedding` (le rappel vectoriel des
     conversations, migration 025). Ne traiter que la première laisserait la
     seconde déclarée `vector(1536)` face à un modèle qui rend autre chose :
     toute écriture y échouerait, en silence, longtemps après l'opération.

  3. UN INDEX HNSW EST LIÉ À SA DIMENSION. `ALTER COLUMN ... TYPE vector(N)` est
     refusé tant que l'index existe. On le supprime, on change le type, on le
     recrée. Le recréer sur une colonne vide ne coûte rien et ne reproduit pas
     le piège de la migration 001 (un ivfflat construit sur une table vide
     garde des centroïdes calculés sans données) : HNSW se construit au fil des
     insertions.

CE QUE L'OPÉRATION NE CASSE PAS. Pendant toute la re-vectorisation, la
recherche continue de répondre : `search_hybrid` interroge TOUJOURS les deux
voies, et la voie lexicale (plein texte français + trigrammes) ne dépend
d'aucun vecteur. Les résultats sont moins fins, ils ne sont pas absents — et
c'est la raison pour laquelle on peut se permettre de vider les vecteurs d'un
coup plutôt que de tenir deux colonnes en parallèle.
"""
from __future__ import annotations

import logging
from typing import Optional

from database.connection import get_db

logger = logging.getLogger("duret.revectorisation")

# Les deux colonnes de vecteurs de la base. Toute nouvelle colonne `vector()`
# doit entrer ici, sinon elle restera à l'ancienne dimension sans que personne
# ne s'en aperçoive avant la première écriture ratée.
COLONNES_VECTEUR = (
    ("documents", "embedding"),
    ("conversation_memoire", "embedding"),
)

# L'index vectoriel du corpus, posé par la migration 027. `conversation_memoire`
# n'en a pas (quelques centaines de lignes : un parcours séquentiel suffit).
INDEX_VECTORIEL = "idx_documents_embedding_hnsw"

# Bornes admises pour une dimension mesurée. En dessous, ce n'est pas un
# embedding ; au-dessus, aucun modèle courant ne va, et pgvector plafonne
# l'indexation HNSW à 2000 dimensions — au-delà l'index ne se crée pas.
DIMENSION_MIN = 64
DIMENSION_MAX_INDEXABLE = 2000


# La dimension déclarée par la colonne, mise en cache : elle est lue à chaque
# écriture de vecteur, et une requête au catalogue par morceau serait payée
# 9 400 fois pour une valeur qui ne change qu'à la re-vectorisation.
_DIMENSION_BASE: Optional[int] = None


async def dimension_attendue() -> int:
    """La dimension que la COLONNE déclare, et non celle que la configuration
    espère.

    LA BASE FAIT FOI — même leçon que les permissions de la migration 028. Le
    garde-fou d'écriture lisait `settings.embedding_dimensions`, une valeur du
    fichier de configuration : après une re-vectorisation vers 768, elle serait
    restée à 1536 et TOUS les vecteurs du nouveau modèle auraient été refusés,
    avec un message accusant le modèle alors que la base était d'accord avec
    lui. Une valeur qu'il faut tenir synchrone finit toujours par ne plus
    l'être ; celle qu'on lit ne se désynchronise jamais.
    """
    global _DIMENSION_BASE
    if _DIMENSION_BASE:
        return _DIMENSION_BASE
    from config import settings
    defaut = int(getattr(settings, "embedding_dimensions", 1536) or 1536)
    try:
        async with get_db() as conn:
            brut = await conn.fetchval(
                """SELECT format_type(a.atttypid, a.atttypmod)
                   FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
                   WHERE c.relname = 'documents' AND a.attname = 'embedding'""")
        # « vector(1536) » -> 1536
        n = int(str(brut or "").split("(")[1].rstrip(")"))
        _DIMENSION_BASE = n
        return n
    except Exception:  # noqa: BLE001 — un catalogue illisible garde le défaut
        return defaut


def oublier_dimension() -> None:
    """Vide le cache : appelé après une re-vectorisation, et par les bancs."""
    global _DIMENSION_BASE
    _DIMENSION_BASE = None


async def mesurer_dimension(modele: str = "") -> tuple[Optional[int], str]:
    """La dimension que rend RÉELLEMENT le modèle d'embedding choisi.

    Rend (dimension, explication). `None` quand la mesure échoue — et
    l'explication dit pourquoi, parce qu'un échec silencieux ici ferait
    re-vectoriser tout un corpus vers une taille supposée.
    """
    from vectorstore.embeddings import embed_texts

    # Un texte court et neutre : on mesure la forme de la réponse, pas son sens.
    vecteurs = await embed_texts(["essai de dimension"], modele_force=modele)
    vecteur = vecteurs[0] if vecteurs else None
    if not vecteur:
        return None, ("Le modèle n'a rendu aucun vecteur. Vérifiez la clé du "
                      "fournisseur et le nom du modèle avant de relancer.")
    taille = len(vecteur)
    if taille < DIMENSION_MIN:
        return None, (f"Le modèle a rendu {taille} valeurs : trop peu pour un "
                      "embedding. Le nom du modèle est probablement erroné.")
    detail = f"{taille} dimensions"
    if taille > DIMENSION_MAX_INDEXABLE:
        detail += (f" — au-delà de {DIMENSION_MAX_INDEXABLE}, pgvector ne sait "
                   "pas construire d'index HNSW : la recherche vectorielle "
                   "fonctionnerait, mais en parcourant tout le corpus")
    return taille, detail


async def etat() -> dict:
    """Où en est le corpus : ce qui est vectorisé, ce qui attend, et sous quelle
    dimension la base est déclarée."""
    async with get_db() as conn:
        corpus = await conn.fetchrow(
            "SELECT count(*) AS total, count(embedding) AS vectorises FROM documents")
        file = await conn.fetch(
            "SELECT status, count(*) AS n FROM embedding_jobs GROUP BY status")
        dims = await conn.fetch(
            """SELECT c.relname AS table, format_type(a.atttypid, a.atttypmod) AS type
               FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
               WHERE a.attname = 'embedding' AND c.relkind = 'r'""")
    total = int(corpus["total"] or 0)
    faits = int(corpus["vectorises"] or 0)
    return {
        "morceaux": total,
        "vectorises": faits,
        "restants": total - faits,
        # Le pourcentage est arrondi À L'ENTIER INFÉRIEUR : afficher « 100 % »
        # alors qu'il reste des morceaux ferait croire l'opération finie.
        "avancement": int(faits * 100 / total) if total else 100,
        "file": {r["status"]: int(r["n"]) for r in file},
        "colonnes": {r["table"]: r["type"] for r in dims},
    }


async def revectoriser(dimension: int, modele: str = "") -> dict:
    """Vide les vecteurs, aligne la base sur `dimension`, et remet tout le
    corpus en file d'attente.

    TOUT SE FAIT DANS UNE SEULE TRANSACTION. Une opération interrompue à
    mi-chemin laisserait la base avec deux dimensions mélangées : des vecteurs
    de l'ancien modèle jugés comparables à ceux du nouveau, c'est-à-dire des
    résultats de recherche faux et silencieux. Ou tout passe, ou rien ne bouge.
    """
    if not isinstance(dimension, int) or dimension < DIMENSION_MIN:
        raise ValueError(f"Dimension invalide : {dimension}")

    async with get_db() as conn:
        async with conn.transaction():
            # 1. Les vecteurs partent. Ils ne sont plus comparables à ceux que
            #    le nouveau modèle produira : les garder serait pire que de les
            #    perdre, puisqu'ils continueraient de remonter dans les
            #    résultats en se faisant passer pour pertinents.
            for table, colonne in COLONNES_VECTEUR:
                await conn.execute(
                    f"UPDATE {table} SET {colonne} = NULL WHERE {colonne} IS NOT NULL")

            # 2. L'index doit tomber AVANT le changement de type : Postgres
            #    refuse d'altérer une colonne qu'un index vectoriel occupe.
            await conn.execute(f"DROP INDEX IF EXISTS {INDEX_VECTORIEL}")

            # 3. La base change de dimension. Les colonnes étant vides, la
            #    conversion est immédiate et ne peut pas échouer sur une donnée.
            for table, colonne in COLONNES_VECTEUR:
                await conn.execute(
                    f"ALTER TABLE {table} ALTER COLUMN {colonne} TYPE vector({dimension})")

            # 4. L'index revient, sauf si la dimension dépasse ce que pgvector
            #    sait indexer. Dans ce cas on le DIT plutôt que de faire échouer
            #    toute l'opération : une recherche non indexée reste une
            #    recherche, sur 9 400 morceaux elle est simplement plus lente.
            indexe = dimension <= DIMENSION_MAX_INDEXABLE
            if indexe:
                await conn.execute(
                    f"CREATE INDEX {INDEX_VECTORIEL} ON documents "
                    "USING hnsw (embedding vector_cosine_ops)")

            # 5. Tout le corpus retourne en file. `attempts` DOIT repartir de
            #    zéro : un job qui a déjà épuisé ses trois tentatives sous
            #    l'ancien modèle ne serait jamais repris, et son morceau
            #    resterait invisible pour toujours.
            await conn.execute(
                """UPDATE embedding_jobs
                   SET status = 'pending', attempts = 0,
                       error_message = NULL, processed_at = NULL""")
            # Et les morceaux qui n'ont JAMAIS eu de job en reçoivent un : la
            # file et le corpus ont pu diverger (ingestion interrompue, job
            # supprimé en cascade).
            manquants = await conn.execute(
                """INSERT INTO embedding_jobs (document_id, status)
                   SELECT d.id, 'pending' FROM documents d
                   WHERE NOT EXISTS (SELECT 1 FROM embedding_jobs j
                                     WHERE j.document_id = d.id)""")

            total = await conn.fetchval("SELECT count(*) FROM documents")

    # Le cache du garde-fou d'écriture porte l'ANCIENNE dimension : sans
    # cet oubli, il refuserait tous les vecteurs du nouveau modèle jusqu'au
    # prochain redémarrage du conteneur.
    oublier_dimension()

    logger.warning(
        "Re-vectorisation lancée : dimension %d, %s morceaux en file, "
        "index %s. Modèle : %s",
        dimension, total, "recréé" if indexe else "NON recréé (dimension trop grande)",
        modele or "(celui du réglage)")
    return {
        "dimension": dimension,
        "morceaux_en_file": int(total or 0),
        "index_recree": indexe,
        "jobs_ajoutes": manquants,
    }


# ── Le catalogue des modèles d'embedding, avec leur dimension ────────────
#
# DEMANDE DE NOA (02/09) : « dis-moi quels modèles j'ai accès pour l'embedding
# et l'OCR/vision avec ma clé, et fais en sorte que je puisse les sélectionner
# dans l'interface ». La réponse ne peut pas être une liste écrite à la main :
# elle dépend de l'abonnement, elle change, et la DIMENSION — qui décide de
# tout ici — n'est annoncée nulle part.
#
# On la mesure donc, modèle par modèle, en cache d'une heure : un catalogue de
# fournisseur ne bouge pas dans la journée, et un appel par modèle à chaque
# ouverture de l'écran serait payé pour rien. Le cache porte la dimension ET
# l'échec : un modèle qui ne répond pas ne doit pas être re-sondé à chaque
# affichage.
_CATALOGUE_DIMS: dict = {}
_CATALOGUE_EXPIRE: dict = {}
_DUREE_CATALOGUE_S = 3600


async def catalogue_embeddings(rafraichir: bool = False) -> list[dict]:
    """Les modèles d'embedding accessibles, chacun avec sa dimension MESURÉE.

    Un modèle dont la dimension ne peut pas être mesurée est rendu quand même,
    avec sa raison : le taire laisserait croire qu'il n'existe pas, alors que
    c'est peut-être la clé qui manque.
    """
    import time as _t

    from llm.router import catalogue_modeles, usage_du_modele

    attendue = await dimension_attendue()
    sortie: list[dict] = []
    for fiche in catalogue_modeles():
        if not fiche.get("cle_presente"):
            continue
        for m in fiche.get("modeles") or []:
            nom = m.get("id") or ""
            if usage_du_modele(nom) != "embedding":
                continue
            ref = f"{fiche['fournisseur']}:{nom}"
            frais = (not rafraichir
                     and ref in _CATALOGUE_DIMS
                     and _t.monotonic() < _CATALOGUE_EXPIRE.get(ref, 0))
            if not frais:
                dim, detail = await mesurer_dimension(ref)
                _CATALOGUE_DIMS[ref] = (dim, detail)
                _CATALOGUE_EXPIRE[ref] = _t.monotonic() + _DUREE_CATALOGUE_S
            dim, detail = _CATALOGUE_DIMS[ref]
            sortie.append({
                "reference": ref,
                "fournisseur": fiche["fournisseur"],
                "libelle": fiche["libelle"],
                "modele": nom,
                "dimension": dim,
                "detail": detail,
                # CE QUI DÉCIDE POUR L'UTILISATEUR : un modèle de la même
                # dimension que la base entre sans re-vectorisation forcée par
                # le schéma (il en faut une quand même, les vecteurs n'étant
                # pas comparables — mais l'opération est plus légère).
                "meme_dimension": bool(dim and dim == attendue),
                "utilisable": dim is not None,
            })
    return sortie
