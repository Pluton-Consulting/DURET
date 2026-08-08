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
import hmac
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
    # compare_digest : la comparaison naïve `!=` s'arrête au premier octet différent,
    # ce qui laisse mesurer le secret caractère par caractère. Sans conséquence pour
    # l'ingestion seule, mais ce webhook servira à DÉCLENCHER des agents.
    if not hmac.compare_digest(x_ingestion_secret or "", settings.ingestion_webhook_secret):
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


# État des synchronisations lancées depuis l'interface. En mémoire : une
# synchronisation interrompue par un redémarrage se relance, elle est idempotente.
_SYNCS: dict[str, dict] = {}

CONNECTEURS = {
    "outlook": ("Messagerie Microsoft 365", "ingestion.connectors.outlook"),
    "gmail": ("Messagerie Google Workspace", "ingestion.connectors.gmail"),
    "google_drive": ("Google Drive", "ingestion.connectors.google_drive"),
    "extrabat": ("Extrabat", "ingestion.connectors.extrabat"),
    "deytime": ("Deytime", "ingestion.connectors.deytime"),
    "synology": ("NAS Synology", "ingestion.connectors.synology"),
}


async def _executer_sync(source: str, module: str, user_id: str) -> None:
    """Déroule la synchronisation en tâche de fond et consigne le résultat."""
    import time
    etat = _SYNCS[source]
    try:
        run = __import__(module, fromlist=["sync"]).sync
        resultat = await run()
        etat.update({"etat": "terminee", "resultat": resultat or {},
                     "fin": time.time()})
        await log_action(action="ingestion_sync", user_id=user_id,
                         metadata={"source": source, **(resultat or {})})
    except NotImplementedError as e:
        etat.update({"etat": "non_configure", "erreur": str(e), "fin": time.time()})
    except Exception as e:  # noqa: BLE001
        logger.warning("Sync %s échouée : %s", source, e)
        etat.update({"etat": "echec", "erreur": str(e)[:400], "fin": time.time()})


@router.get("/sync")
async def etat_syncs(current_user: User = Depends(get_current_user)):
    """Connecteurs disponibles et état de la dernière synchronisation de chacun."""
    if not has_permission(current_user.role, "manage_system"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Réservé au super admin")
    return [{"source": cle, "libelle": libelle, **_SYNCS.get(cle, {"etat": "jamais"})}
            for cle, (libelle, _) in CONNECTEURS.items()]


@router.post("/sync/{source}")
async def trigger_sync(source: str, current_user: User = Depends(get_current_user)):
    """Déclenche une synchronisation. Administration système.

    Elle tourne en TÂCHE DE FOND : parcourir plusieurs boîtes prend des minutes,
    et chaque message consomme un embedding. Une requête HTTP expirerait bien
    avant la fin, et l'utilisateur ne saurait pas si le travail a abouti.
    L'avancement se lit sur `GET /sync`.
    """
    import asyncio
    import time

    if not has_permission(current_user.role, "manage_system"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Réservé au super admin")

    if source not in CONNECTEURS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Connecteur inconnu : {source}")
    if _SYNCS.get(source, {}).get("etat") == "en_cours":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"Une synchronisation {source} est déjà en cours.")

    libelle, module = CONNECTEURS[source]
    _SYNCS[source] = {"etat": "en_cours", "libelle": libelle, "debut": time.time(),
                      "par": current_user.email, "resultat": None, "erreur": None}
    asyncio.create_task(_executer_sync(source, module, str(current_user.id)))
    return {"source": source, "lance": True,
            "note": "Synchronisation lancée en tâche de fond ; l'avancement s'affiche ici."}


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
    from ingestion import import_masse

    if import_masse.etat()["en_cours"]:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Un import est deja en cours. Attendez qu'il se termine.")

    _IMPORTS.pop(body.token, None)
    await log_action(action="import_fichier", user_id=str(current_user.id),
                     metadata={"fichier": nom, "source_type": body.source_type,
                               "lignes": structure["documents_estimes"]})

    # EN TACHE DE FOND. La boucle tournait dans la requete : nginx coupe `/api/`
    # a 300 s, donc au-dela de quelques milliers de lignes l'import etait tue en
    # cours de route, sans reprise ni marqueur. On rend la main tout de suite et
    # l'avancement se suit sur GET /import/etat.
    asyncio.create_task(import_masse.executer(
        structure.get("rows") or [], structure.get("columns") or [],
        texte_unique=structure.get("text") if structure["kind"] != "tabulaire" else None,
        fichier=nom, source_type=body.source_type, id_col=body.id_col,
        access_level=body.access_level, anonymize=body.anonymize))

    return {"ok": True, "lance": True, "lignes": structure["documents_estimes"],
            "message": "Import lance. Suivez l'avancement sur cette page."}


@router.get("/import/etat")
async def import_etat(current_user: User = Depends(get_current_user)):
    """Avancement de l'import en cours (ou du dernier termine)."""
    if not has_permission(current_user.role, "import_documents"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusee")
    from ingestion import import_masse
    return import_masse.etat()


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
