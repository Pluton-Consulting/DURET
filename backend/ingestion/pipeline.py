"""
Pipeline d'ingestion commun (source-agnostique).

ingest_document(texte, ...) : découpe le texte en chunks avec chevauchement,
anonymise si demandé, puis insère chaque chunk dans la base vectorielle via
vectorstore.insert_document_chunk (qui met en file un job de vectorisation si
aucun embedding n'est fourni).

Ne dépend d'AUCUN service externe — appelé par les connecteurs.
"""
import logging
from typing import Optional

from vectorstore.client import vectorstore

logger = logging.getLogger("duret.ingestion")

# Découpage : ~512 « mots » par chunk avec chevauchement pour ne pas couper le sens.
DEFAULT_CHUNK_WORDS = 380
DEFAULT_OVERLAP_WORDS = 60


def chunk_text(text: str, chunk_words: int = DEFAULT_CHUNK_WORDS,
               overlap_words: int = DEFAULT_OVERLAP_WORDS) -> list[str]:
    """
    Découpe un texte en morceaux qui se chevauchent (par mots).
    Le chevauchement préserve le contexte entre chunks pour la recherche.
    """
    if not text or not text.strip():
        return []
    words = text.split()
    if len(words) <= chunk_words:
        return [" ".join(words)]

    step = max(1, chunk_words - overlap_words)
    chunks: list[str] = []
    for start in range(0, len(words), step):
        piece = words[start:start + chunk_words]
        if piece:
            chunks.append(" ".join(piece))
        if start + chunk_words >= len(words):
            break
    return chunks


async def ingest_document(
    text: str,
    source_type: str,
    source_id: str,
    source_filename: Optional[str] = None,
    access_level: str = "all",
    anonymize: bool = False,
    replace_existing: bool = True,
) -> int:
    """
    Ingère un document texte dans la base documentaire.

    Args:
        text: contenu textuel (déjà extrait des PDF/emails/etc. par le connecteur).
        source_type: 'devis', 'chantier', 'client', 'email', 'planning', 'catalogue_fournisseur'…
        source_id: identifiant stable de la source (permet la ré-ingestion sans doublon).
        source_filename: nom de fichier / sujet d'email (traçabilité).
        access_level: 'all', 'commercial_plus', 'bureau_etudes_plus', 'direction_only', 'admin_only'.
        anonymize: si True, retire les PII (noms/montants/SIRET…) avant stockage (RGPD strict).
        replace_existing: supprime les chunks précédents de cette source avant réinsertion.

    Returns:
        Nombre de chunks insérés. Ne lève pas : logge et renvoie 0 en cas d'échec.
    """
    try:
        content = text or ""
        if anonymize:
            from security.anonymizer import anonymizer
            content, _ = anonymizer.anonymize(content)

        chunks = chunk_text(content)
        if not chunks:
            # UN TEXTE VIDE NE REMPLACE PAS UNE VERSION VALIDE (16/09, audit
            # D-08) : une extraction défaillante (PDF illisible ce jour-là,
            # OCR en panne) effaçait ce que la mémoire savait déjà.
            logger.info("Ingestion %s/%s : document vide, ignoré (l'ancienne version reste)",
                        source_type, source_id)
            return 0

        # LA NOUVELLE GÉNÉRATION BASCULE EN UNE FOIS (audit D-08). Avant :
        # suppression, puis N insertions séparées — une coupure au milieu
        # laissait le document absent de la recherche alors qu'il y était.
        if replace_existing:
            total = await vectorstore.remplacer_source(
                chunks, source_type=source_type, source_id=source_id,
                source_filename=source_filename, access_level=access_level,
                contains_pii=not anonymize, is_anonymized=True)
        else:
            total = len(chunks)
            for i, chunk in enumerate(chunks):
                await vectorstore.insert_document_chunk(
                    content=chunk,
                    source_type=source_type,
                    source_id=source_id,
                    access_level=access_level,
                    source_filename=source_filename,
                    chunk_index=i,
                    chunk_total=total,
                    embedding=None,          # vectorisation différée (embedding_jobs)
                    contains_pii=not anonymize,
                    is_anonymized=True,       # visible par la recherche (contenu interne validé)
                )

        logger.info("Ingestion %s/%s : %d chunks insérés (source=%s)",
                    source_type, source_id, total, source_filename or "—")
        return total
    except Exception as e:
        logger.warning("Échec ingestion %s/%s : %s", source_type, source_id, e)
        return 0


async def copier_document(source_id_origine: str, source_type: str, source_id: str,
                          source_filename: Optional[str] = None, access_level: str = "all") -> int:
    """Une copie RECONNUE À SON CONTENU (même empreinte que `source_id_origine`)
    reprend les morceaux de l'original sous sa propre source, son nom et son
    niveau d'accès : ni relecture ni OCR, ni nouvel appel d'embedding quand
    l'original est vectorisé (16/09, audit D-27). Rend le nombre de morceaux
    repris, 0 si l'original n'en a plus. Ne lève pas."""
    try:
        return await vectorstore.copier_source(source_id_origine, source_type, source_id,
                                               source_filename, access_level)
    except Exception as e:  # noqa: BLE001 — la copie ratée se rattrape par une relecture
        logger.warning("Copie %s → %s impossible : %s", source_id_origine, source_id, e)
        return 0
