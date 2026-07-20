"""
Couche d'ingestion — Phase 2.

Reçoit des documents/données depuis les sources externes (Google Drive, Outlook,
Extrabat, Deytime) et les fait entrer dans la base documentaire (RAG) via un
pipeline commun : découpage → (anonymisation optionnelle) → insertion vectorielle.

Chaque connecteur (ingestion/connectors/*) ne fait que RÉCUPÉRER les données brutes
puis appelle `pipeline.ingest_document(...)`. Le connecteur ne connaît pas la base.
"""
from ingestion.pipeline import ingest_document, chunk_text

__all__ = ["ingest_document", "chunk_text"]
