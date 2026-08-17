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

# LES CONNECTEURS DE CE CLIENT, ET EUX SEULS.
#
# Cette liste était copiée telle quelle d'un projet à l'autre. Duret & Sols lit
# son courrier dans Google Workspace et ses documents sur le SERVEUR DE
# FICHIERS : Google Drive n'y sert à rien, le NAS le remplace. Le proposer à
# l'écran invitait à lancer une synchronisation qui ne pouvait rien trouver.
# La liste se change en dupliquant le projet, comme `skills/` et `outils/`.
CONNECTEURS = {
    "outlook": ("Messagerie Microsoft 365", "ingestion.connectors.outlook"),
    "gmail": ("Messagerie Google Workspace", "ingestion.connectors.gmail"),
    "extrabat": ("Extrabat", "ingestion.connectors.extrabat"),
    "deytime": ("Deytime", "ingestion.connectors.deytime"),
    "synology": ("NAS Synology", "ingestion.connectors.synology"),
}

# UN CONNECTEUR ANNONCÉ DOIT EXISTER. Le contrôle se fait au démarrage, pas au
# clic : découvrir un module manquant le jour où quelqu'un lance la
# synchronisation, c'est le découvrir devant l'utilisateur. `find_spec` ne
# charge rien — il regarde seulement si le module est trouvable.
def _verifier_connecteurs() -> None:
    import importlib.util
    for nom, (_, module) in CONNECTEURS.items():
        try:
            trouve = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            trouve = False
        if not trouve:
            logger.error("Connecteur « %s » déclaré mais introuvable : %s. "
                         "Il apparaîtra à l'écran et échouera au clic.",
                         nom, module)


_verifier_connecteurs()


async def requalifier_syncs_interrompues() -> int:
    """Les synchros tuées par un redémarrage ne doivent pas rester « en cours ».

    Même mécanisme que les tâches différées : leur coroutine n'existe plus, et
    une ligne « en cours » éternelle bloquerait l'index unique — donc toute
    nouvelle synchronisation de cette source, pour toujours.

    RÉSERVE : ceci suppose UN SEUL processus, ce qui est vrai aujourd'hui
    (uvicorn sans --workers). Le jour où l'on passe à plusieurs workers, il
    faudra y ajouter le filtre d'ancienneté utilisé plus bas, sinon on tuerait
    la ligne d'un frère bien vivant.
    """
    try:
        async with get_db() as conn:
            n = await conn.fetchval(
                """WITH maj AS (
                       UPDATE synchronisations
                          SET statut = 'interrompue', termine_a = NOW(), maj_a = NOW(),
                              erreur = 'redémarrage du serveur pendant la synchronisation'
                        WHERE statut = 'en_cours' RETURNING 1)
                   SELECT count(*) FROM maj""")
        if n:
            logger.info("Synchronisations requalifiées « interrompue » : %d", n)
        return int(n or 0)
    except Exception as e:  # noqa: BLE001 - un démarrage ne tombe pas là-dessus
        logger.warning("Requalification des synchronisations impossible : %s", e)
        return 0


async def _avancement(sync_id: str):
    """Fabrique le rapporteur d'avancement passé au connecteur.

    L'ÉCRITURE EST ESPACÉE. Un compteur écrit à chaque document ferait des
    milliers d'UPDATE sur une ingestion de Drive, pour un écran qui se
    rafraîchit toutes les deux secondes : personne ne verrait la différence, et
    Postgres porterait la charge. Une écriture par seconde au plus suffit.
    """
    import time
    dernier = {"t": 0.0}

    async def _poser(traites: int, total, etape: str) -> None:
        if time.monotonic() - dernier["t"] < 1.0:
            return
        dernier["t"] = time.monotonic()
        async with get_db() as conn:
            await conn.execute(
                "UPDATE synchronisations SET traites=$1, total=$2, etape=$3, "
                "maj_a=NOW() WHERE id=$4::uuid",
                int(traites or 0), total, (etape or "")[:200], sync_id)

    return _poser


async def _conclure(sync_id: str, statut: str, *, resultat=None, erreur=None) -> None:
    """Écrit l'état final. NE LÈVE JAMAIS.

    Une panne d'écriture ici laisserait la ligne « en cours », et l'index unique
    interdirait alors toute nouvelle synchronisation de cette source.
    """
    import json as _json
    try:
        async with get_db() as conn:
            await conn.execute(
                "UPDATE synchronisations SET statut=$1, resultat=$2::jsonb, "
                "erreur=$3, termine_a=NOW(), maj_a=NOW() WHERE id=$4::uuid",
                statut, _json.dumps(resultat or {}, ensure_ascii=False, default=str),
                (erreur or None), sync_id)
    except Exception as e:  # noqa: BLE001
        logger.error("Synchronisation %s laissée « %s » : %s", sync_id, statut, e)


async def _executer_sync(source: str, module: str, user_id: str,
                         sync_id: str) -> None:
    """Déroule la synchronisation en tâche de fond et consigne le résultat."""
    import inspect
    import time
    etat = _SYNCS[source]
    try:
        run = __import__(module, fromlist=["sync"]).sync
        # COMPATIBILITÉ : seuls les connecteurs qui SAVENT rendre compte
        # reçoivent le rapporteur. Imposer le paramètre casserait les autres,
        # qui n'ont aucune raison d'être réécrits pour un compteur.
        if "avancer" in inspect.signature(run).parameters:
            resultat = await run(avancer=await _avancement(sync_id))
        else:
            resultat = await run()
        etat.update({"etat": "terminee", "resultat": resultat or {},
                     "fin": time.time()})
        await _conclure(sync_id, "terminee", resultat=resultat)
        await log_action(action="ingestion_sync", user_id=user_id,
                         metadata={"source": source, **(resultat or {})})
    except NotImplementedError as e:
        etat.update({"etat": "non_configure", "erreur": str(e), "fin": time.time()})
        await _conclure(sync_id, "non_configure", erreur=str(e)[:400])
    except Exception as e:  # noqa: BLE001
        logger.warning("Sync %s échouée : %s", source, e)
        etat.update({"etat": "echec", "erreur": str(e)[:400], "fin": time.time()})
        await _conclure(sync_id, "echec", erreur=str(e)[:400])


@router.get("/sync")
async def etat_syncs(current_user: User = Depends(get_current_user)):
    """Connecteurs disponibles et état de la dernière synchronisation de chacun.

    LU EN BASE, plus en mémoire. `_SYNCS` mourait avec le processus : après un
    redémarrage, l'écran annonçait « Jamais lancée » sur des connecteurs qui
    venaient de tourner. Il reste en mémoire pour la compatibilité, mais c'est
    la base qui fait foi.
    """
    if not has_permission(current_user.role, "manage_system"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Réservé au super admin")

    lignes = {}
    try:
        async with get_db() as conn:
            # La DERNIÈRE exécution de chaque source, plus la dernière RÉUSSITE :
            # un échec d'aujourd'hui ne doit pas effacer « dernière synchro
            # réussie hier à 9 h », qui est ce que le gérant veut savoir.
            for r in await conn.fetch(
                    """SELECT DISTINCT ON (source) source, statut, etape, traites,
                              total, erreur, lance_par_email, demarre_a, termine_a, maj_a
                         FROM synchronisations ORDER BY source, demarre_a DESC"""):
                lignes[r["source"]] = dict(r)
            for r in await conn.fetch(
                    """SELECT DISTINCT ON (source) source, termine_a
                         FROM synchronisations WHERE statut = 'terminee'
                        ORDER BY source, termine_a DESC"""):
                if r["source"] in lignes:
                    lignes[r["source"]]["derniere_reussite"] = r["termine_a"]
    except Exception as e:  # noqa: BLE001 - l'écran doit s'afficher même sans historique
        logger.warning("Historique des synchronisations illisible : %s", e)

    sortie = []
    for cle, (libelle, _) in CONNECTEURS.items():
        l = lignes.get(cle)
        if not l:
            # « jamais » n'est pas un statut stocké : c'est l'absence de ligne.
            sortie.append({"source": cle, "libelle": libelle, "etat": "jamais"})
            continue
        sortie.append({
            "source": cle, "libelle": libelle, "etat": l["statut"],
            "etape": l["etape"], "traites": l["traites"], "total": l["total"],
            "erreur": l["erreur"], "par": l["lance_par_email"],
            "debut": l["demarre_a"].isoformat() if l["demarre_a"] else None,
            "fin": l["termine_a"].isoformat() if l["termine_a"] else None,
            "battement": l["maj_a"].isoformat() if l["maj_a"] else None,
            "derniere_reussite": (l["derniere_reussite"].isoformat()
                                  if l.get("derniere_reussite") else None),
            # Le pourcentage se CALCULE ici, il ne se stocke pas : stocké, il
            # finirait par contredire les compteurs. Absent quand le total est
            # inconnu — la barre est alors indéterminée, elle n'invente rien.
            "pourcentage": (round(100 * l["traites"] / l["total"])
                            if l["total"] else None),
        })
    return sortie


async def demarrer_sync(source: str, current_user) -> dict:
    """Déclenche une synchronisation, quelle qu'en soit la porte d'entrée.

    EXTRAIT DE LA ROUTE POUR ÊTRE PARTAGÉ. Le chat a maintenant son geste
    d'ingestion du Drive, et il ne doit surtout pas réimplémenter ceci : la
    ligne `synchronisations`, l'index unique partiel qui empêche deux
    campagnes simultanées, la libération des synchros pendues et la remontée
    d'avancement vivent tous ici. Une seconde implémentation, c'est un second
    endroit où le verrou anti-doublon peut manquer.

    Elle tourne en TÂCHE DE FOND : parcourir un Drive ou plusieurs boîtes prend
    des minutes à des heures, et chaque document consomme un embedding. Une
    requête HTTP expirerait bien avant la fin.
    """
    import asyncio
    import time

    if not has_permission(getattr(current_user, "role", ""), "manage_system"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Réservé au super admin")

    if source not in CONNECTEURS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Connecteur inconnu : {source}")

    libelle, module = CONNECTEURS[source]
    async with get_db() as conn:
        # UNE SYNCHRO PENDUE NE DOIT PAS BLOQUER LA SOURCE POUR TOUJOURS. Si le
        # processus est mort sans écrire son état final, la ligne reste « en
        # cours » et l'index unique refuserait toute relance. On libère celles
        # qui n'ont plus donné signe de vie depuis une demi-heure.
        await conn.execute(
            """UPDATE synchronisations
                  SET statut='interrompue', termine_a=NOW(), maj_a=NOW(),
                      erreur='aucune nouvelle depuis 30 minutes'
                WHERE source=$1 AND statut='en_cours'
                  AND maj_a < NOW() - INTERVAL '30 minutes'""", source)
        ligne = await conn.fetchrow(
            "INSERT INTO synchronisations (source, statut, etape, lance_par, "
            "lance_par_email) VALUES ($1,'en_cours','je démarre',$2,$3) "
            # L'index unique partiel fait le garde-fou anti-doublon : il tient
            # au redémarrage et tiendrait à plusieurs workers, ce que le
            # dictionnaire en mémoire ne faisait ni l'un ni l'autre.
            "ON CONFLICT DO NOTHING RETURNING id",
            source, current_user.id, current_user.email)
    if ligne is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"Une synchronisation {source} est déjà en cours.")

    _SYNCS[source] = {"etat": "en_cours", "libelle": libelle, "debut": time.time(),
                      "par": current_user.email, "resultat": None, "erreur": None}
    asyncio.create_task(_executer_sync(source, module, str(current_user.id),
                                       str(ligne["id"])))
    return {"source": source, "lance": True,
            "note": "Synchronisation lancée en tâche de fond ; l'avancement s'affiche ici."}


@router.post("/sync/{source}")
async def trigger_sync(source: str, current_user: User = Depends(get_current_user)):
    """Porte HTTP de `demarrer_sync` — l'écran de synchronisation."""
    return await demarrer_sync(source, current_user)


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
    # Association colonne -> champ commun, proposée à l'analyse et révisable.
    # Revalidée côté serveur : ce qui revient du navigateur n'est jamais cru.
    mapping: Optional[dict] = None


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
                            detail="Analyse expirée ou inconnue. Relancez l'import du fichier.")
    if entree["user_id"] != str(current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cette analyse ne vous appartient pas")

    structure = entree["structure"]
    nom = entree["filename"]
    from ingestion import import_masse
    from ingestion.schema import valider

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
        access_level=body.access_level, anonymize=body.anonymize,
        mapping=valider(body.source_type, body.mapping or {},
                        structure.get("columns") or [])))

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
