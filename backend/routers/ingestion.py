"""
Ingestion — réception de documents depuis les sources externes.

- POST /api/ingestion/webhook : point d'entrée pour les scénarios Make.com
  (Google Drive « Watch Files » / Outlook « Watch Emails » → HTTP POST ici).
  Sécurisé par un secret partagé (en-tête X-Ingestion-Secret = settings.ingestion_webhook_secret).
- POST /api/ingestion/sync/{source} : déclenche un connecteur API direct (super_admin).
- GET  /api/ingestion/status : compteurs d'ingestion (documents par source, jobs de vectorisation).

Le contenu est poussé dans le pipeline commun (ingestion.pipeline) qui découpe et insère
dans la base documentaire (RAG).
"""
import asyncio
import base64
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel

from auth.dependencies import get_current_user
from database.models import User
from database.connection import get_db
from security.rbac import has_permission
from security.audit import log_action
from config import settings
from ingestion.pipeline import ingest_document

logger = logging.getLogger("duret.ingestion.api")
router = APIRouter()


class WebhookDocument(BaseModel):
    source_type: str                 # 'devis', 'chantier', 'client', 'email', 'planning', 'catalogue_fournisseur'...
    source_id: str                   # identifiant stable (id fichier Drive, id email...) — évite les doublons
    filename: Optional[str] = None   # nom de fichier / sujet d'email
    text: Optional[str] = None       # contenu déjà en texte (corps d'email, doc texte)
    content_base64: Optional[str] = None  # binaire encodé (PDF, txt) si pas de texte fourni
    mime_type: Optional[str] = None
    access_level: str = "all"
    anonymize: bool = False


def _extract_text(doc: WebhookDocument) -> Optional[str]:
    """Récupère le texte : champ `text` direct, sinon décodage du base64 (txt / PDF)."""
    if doc.text and doc.text.strip():
        return doc.text
    if not doc.content_base64:
        return None
    try:
        raw = base64.b64decode(doc.content_base64)
    except Exception:
        return None
    if len(raw) > settings.max_body_mb * 1024 * 1024:
        logger.warning("Binaire d'ingestion trop volumineux (%d octets) — rejeté", len(raw))
        return None

    mime = (doc.mime_type or "").lower()
    name = (doc.filename or "").lower()

    if mime.startswith("text/") or mime in ("application/json",) or name.endswith((".txt", ".md", ".csv")):
        return raw.decode("utf-8", errors="replace")

    if mime == "application/pdf" or name.endswith(".pdf"):
        try:
            import io
            import pdfplumber  # dépendance optionnelle
            parts = []
            with pdfplumber.open(io.BytesIO(raw)) as pdf:
                for i, page in enumerate(pdf.pages):
                    if i >= 200:  # borne anti « PDF bomb » (nb de pages)
                        break
                    parts.append(page.extract_text() or "")
            return "\n\n".join(parts)
        except Exception as e:
            logger.warning("Extraction PDF impossible (%s) : %s", doc.filename, e)
            return None

    # Types non gérés ici (docx, images) : à traiter par le connecteur ou Make en amont.
    return None


@router.post("/webhook")
async def ingestion_webhook(
    doc: WebhookDocument,
    x_ingestion_secret: Optional[str] = Header(default=None),
):
    """Reçoit un document (typiquement depuis un scénario Make.com) et l'ingère."""
    if not settings.ingestion_webhook_secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Ingestion webhook non configuré (INGESTION_WEBHOOK_SECRET manquant)")
    if x_ingestion_secret != settings.ingestion_webhook_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Secret d'ingestion invalide")

    text = await asyncio.to_thread(_extract_text, doc)  # extraction hors boucle d'événements
    if not text:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Aucun texte exploitable (fournir `text`, ou un `content_base64` txt/PDF)")

    chunks = await ingest_document(
        text=text,
        source_type=doc.source_type,
        source_id=doc.source_id,
        source_filename=doc.filename,
        access_level=doc.access_level,
        anonymize=doc.anonymize,
    )
    await log_action(action="document_ingested",
                     metadata={"source_type": doc.source_type, "source_id": doc.source_id, "chunks": chunks})
    return {"ok": True, "source_id": doc.source_id, "chunks": chunks}


@router.post("/sync/{source}")
async def trigger_sync(source: str, current_user: User = Depends(get_current_user)):
    """Déclenche une synchronisation via un connecteur API direct (super_admin)."""
    if not has_permission(current_user.role, "manage_system"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Réservé au super admin")

    try:
        if source == "google_drive":
            from ingestion.connectors.google_drive import sync as run
        elif source == "outlook":
            from ingestion.connectors.outlook import sync as run
        elif source == "extrabat":
            from ingestion.connectors.extrabat import sync as run
        elif source == "deytime":
            from ingestion.connectors.deytime import sync as run
        else:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Connecteur inconnu : {source}")
    except HTTPException:
        raise

    try:
        result = await run()
    except NotImplementedError as e:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(e))
    except Exception as e:
        logger.warning("Sync %s échouée : %s", source, e)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Connecteur {source} : {e}")

    await log_action(action="ingestion_sync", user_id=str(current_user.id), metadata={"source": source, **(result or {})})
    return {"source": source, **(result or {})}


@router.get("/status")
async def ingestion_status(current_user: User = Depends(get_current_user)):
    """Compteurs d'ingestion : documents par type de source + jobs de vectorisation."""
    if not has_permission(current_user.role, "view_dashboard_global"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusée")
    async with get_db() as conn:
        by_source = await conn.fetch(
            "SELECT source_type, COUNT(*) AS chunks, COUNT(DISTINCT source_id) AS documents "
            "FROM documents GROUP BY source_type ORDER BY chunks DESC"
        )
        jobs = await conn.fetchrow(
            "SELECT "
            "COUNT(*) FILTER (WHERE status='pending')   AS en_attente, "
            "COUNT(*) FILTER (WHERE status='completed') AS vectorises, "
            "COUNT(*) FILTER (WHERE status='failed')    AS echecs "
            "FROM embedding_jobs"
        )
    return {
        "by_source": [dict(r) for r in by_source],
        "embedding_jobs": dict(jobs) if jobs else {},
    }
