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
import secrets
import time
from typing import Optional

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status
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
        elif source == "synology":
            from ingestion.connectors.synology import sync as run
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


# ── Import manuel de fichiers (paramètres > Import de données) ──────────────
# Deux temps VOLONTAIRES : /analyze ne fait qu'analyser et proposer, /commit
# écrit. L'utilisateur voit ce qui sera enregistré, corrige le type et la
# colonne identifiante, puis valide. L'IA propose, l'humain décide.

_IMPORTS: dict[str, dict] = {}          # token -> {user_id, expire, structure, meta}
_IMPORT_TTL_S = 1800                    # 30 min pour confirmer
_IMPORT_MAX = 20                        # analyses simultanées conservées


def _purger_imports() -> None:
    maintenant = time.monotonic()
    for k in [k for k, v in _IMPORTS.items() if v["expire"] < maintenant]:
        _IMPORTS.pop(k, None)
    while len(_IMPORTS) > _IMPORT_MAX:   # garde les plus récents
        _IMPORTS.pop(min(_IMPORTS, key=lambda k: _IMPORTS[k]["expire"]), None)


class ImportConfirm(BaseModel):
    token: str
    source_type: str
    id_col: Optional[str] = None
    access_level: str = "all"
    anonymize: bool = False


@router.post("/analyze")
async def analyser_fichier(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Lit un fichier déposé, fait deviner sa nature par l'IA, renvoie un APERÇU.

    N'écrit RIEN : retourne un token à confirmer via /import/commit.
    """
    if not has_permission(current_user.role, "import_documents"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusée")

    brut = await file.read()
    if not brut:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Fichier vide")
    if len(brut) > settings.max_body_mb * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail=f"Fichier trop volumineux (max {settings.max_body_mb} Mo)")

    from ingestion.parsers import analyser, ligne_en_texte, FichierNonSupporte
    from ingestion.detection import detecter, TYPES

    try:
        structure = await asyncio.to_thread(analyser, file.filename or "", brut)
    except FichierNonSupporte as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception as e:
        logger.warning("Lecture de %s impossible : %s", file.filename, e)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"Lecture impossible : {e}")

    detection = await detecter(file.filename or "", structure)

    if structure["kind"] == "tabulaire":
        apercu = [ligne_en_texte(l) for l in structure["rows"][:3]]
    else:
        apercu = [structure["text"][:800]]

    _purger_imports()
    token = secrets.token_urlsafe(24)
    _IMPORTS[token] = {
        "user_id": str(current_user.id),
        "expire": time.monotonic() + _IMPORT_TTL_S,
        "structure": structure,
        "filename": file.filename or "import",
    }

    return {
        "token": token,
        "filename": file.filename,
        "kind": structure["kind"],
        "columns": structure["columns"],
        "documents": structure["documents_estimes"],
        "detection": detection,
        "apercu": apercu,
        "types_possibles": [{"cle": k, "libelle": v} for k, v in TYPES.items()],
    }


@router.post("/commit")
async def confirmer_import(body: ImportConfirm, current_user: User = Depends(get_current_user)):
    """Ingère réellement le fichier analysé, avec les réglages validés par l'humain."""
    if not has_permission(current_user.role, "import_documents"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusée")

    _purger_imports()
    entree = _IMPORTS.get(body.token)
    if not entree:
        raise HTTPException(status_code=status.HTTP_410_GONE,
                            detail="Analyse expirée ou inconnue — relancez l'import du fichier.")
    if entree["user_id"] != str(current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cette analyse ne vous appartient pas")

    structure = entree["structure"]
    nom = entree["filename"]
    from ingestion.parsers import ligne_en_texte

    documents: list[tuple[str, str]] = []          # (source_id, texte)
    if structure["kind"] == "tabulaire":
        id_col = body.id_col if body.id_col in (structure["columns"] or []) else None
        for i, ligne in enumerate(structure["rows"], 1):
            texte = ligne_en_texte(ligne)
            if not texte:
                continue
            cle = (ligne.get(id_col) or "").strip() if id_col else ""
            documents.append((f"{body.source_type}:{cle or f'{nom}#{i}'}", texte))
    else:
        documents.append((f"{body.source_type}:{nom}", structure["text"]))

    if not documents:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Aucun document exploitable")

    total_chunks = 0
    echecs = 0
    for source_id, texte in documents:
        try:
            total_chunks += await ingest_document(
                text=texte,
                source_type=body.source_type,
                source_id=source_id,
                source_filename=nom,
                access_level=body.access_level,
                anonymize=body.anonymize,
            )
        except Exception as e:  # noqa: BLE001 - une ligne fautive ne doit pas tout annuler
            echecs += 1
            logger.warning("Ingestion de %s échouée : %s", source_id, e)

    _IMPORTS.pop(body.token, None)
    await log_action(action="import_fichier", user_id=str(current_user.id),
                     metadata={"fichier": nom, "source_type": body.source_type,
                               "documents": len(documents), "chunks": total_chunks, "echecs": echecs})
    return {"ok": True, "documents": len(documents) - echecs, "chunks": total_chunks, "echecs": echecs}


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
