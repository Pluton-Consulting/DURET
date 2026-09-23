import asyncio
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from database.connection import init_db
from routers import auth, users, chat, dashboard, validation, settings as settings_router, ingestion, browser, skills as skills_router, mail as mail_router, tasks as tasks_router, hooks as hooks_router, learning as learning_router, documents_produits, file_attente, navigateur_interne, tableau, google_perso as google_perso_router
from agents.runtime import init_runtime, shutdown_runtime
from config import settings

# ── AUCUNE CLÉ NE DOIT SE RETROUVER DANS LES JOURNAUX ────────────────────
#
# Le masquage vit dans `security/secrets.py` (le banc l'exécute). Ce qui se
# décide ICI, c'est OÙ il est posé : sur les HANDLERS, et pas seulement sur le
# logger racine. Un enregistrement émis par `logging.getLogger("duret.mail")`
# ne passe pas par les filtres de la racine — il remonte vers ses handlers.
# Posé sur la racine seule, le filtre ne voyait donc presque rien (16/09,
# audit D-22). Il est reposé au démarrage, après qu'uvicorn a installé les
# siens. httpx et httpcore restent à WARNING : leur ligne par requête n'apprend
# rien en exploitation, et c'est une source de fuite en moins.
from security.secrets import poser_filtre as _poser_filtre_secrets

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
for _bavard in ("httpx", "httpcore"):
    logging.getLogger(_bavard).setLevel(logging.WARNING)
_poser_filtre_secrets()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Les handlers d'uvicorn existent maintenant : le filtre des secrets les
    # couvre aussi (audit D-22).
    _poser_filtre_secrets()
    await init_db()
    try:
        from security.rbac import reload_permissions
        await reload_permissions()
    except Exception as e:
        logging.getLogger("duret").error("reload_permissions a échoué : %s", e)
    try:
        await init_runtime()
    except Exception as e:  # le graph ne doit pas empêcher l'API de démarrer
        logging.getLogger("duret").error("init_runtime a échoué : %s", e)
    # LE RÔLE DE CE PROCESSUS (16/09, audit D-18). Toutes les boucles de fond
    # vivaient dans le serveur du chat, et un second processus les aurait
    # relancées une deuxième fois — deux ordonnanceurs, deux synchronisations,
    # deux workers d'embeddings sur la même file. Le rôle se pose dans la
    # configuration (`ROLE_PROCESSUS`) ; « complet » reste le défaut, donc rien
    # ne change pour le déploiement d'aujourd'hui.
    role = str(getattr(settings, "role_processus", "complet") or "complet").strip().lower()
    travaux_de_fond = role in ("complet", "fond")
    logging.getLogger("duret").info("Rôle du processus : %s (boucles de fond : %s)",
                                    role, "oui" if travaux_de_fond else "non")
    try:
        from security.cleanup import start_validation_cleanup
        await start_validation_cleanup()
    except Exception as e:
        logging.getLogger("duret").error("start_validation_cleanup a échoué : %s", e)
    # Les caches sont prêts AVANT les workers ; l'échec d'un connecteur
    # ne doit pas empêcher les autres réglages de se charger.
    try:
        from llm.cles import rafraichir as rafraichir_cles
        await rafraichir_cles(force=True)
    except Exception as e:
        logging.getLogger("infra").error("Cache llm.cles non chargé : %s", type(e).__name__)
    try:
        from llm.reglages import rafraichir as rafraichir_reglages
        await rafraichir_reglages(force=True)
    except Exception as e:
        logging.getLogger("infra").error("Cache llm.reglages non chargé : %s", type(e).__name__)
    try:
        from mail.google_perso import rafraichir as rafraichir_google
        await rafraichir_google(force=True)
    except Exception as e:
        logging.getLogger("infra").error("Cache mail.google_perso non chargé : %s", type(e).__name__)
    if travaux_de_fond:
        from ressources.documents_file import demarrer as demarrer_documents
        await demarrer_documents()
    if travaux_de_fond:
        try:
            from vectorstore.worker import start_embedding_worker
            await start_embedding_worker()
        except Exception as e:
            logging.getLogger("duret").error("start_embedding_worker a échoué : %s", e)
        try:
            from tasks.worker import start_task_worker
            await start_task_worker()
        except Exception as e:
            logging.getLogger("duret").error("start_task_worker a échoué : %s", e)
    try:
        # Les tâches de la file tuées par l'arrêt précédent : leur asyncio.Task
        # n'existe plus, les laisser « en cours » afficherait une progression
        # figée pour toujours. On dit la vérité : interrompues.
        from routers.file_attente import requalifier_interrompues
        await requalifier_interrompues()
        # Même raison pour les SYNCHRONISATIONS : une ligne « en cours »
        # éternelle afficherait une barre figée, et l'index unique refuserait
        # toute relance de cette source.
        from routers.ingestion import requalifier_syncs_interrompues
        await requalifier_syncs_interrompues()
    except Exception as e:
        logging.getLogger("duret").error("requalifier_interrompues a échoué : %s", e)
    try:
        from security.anonymizer import anonymizer
        if not anonymizer.spacy_available:
            logging.getLogger("duret").critical(
                "⚠ Anonymiseur NER (spaCy) INDISPONIBLE — mode regex-only. "
                "Les appels LLM externes seront refusés (block_external_llm_without_ner=%s). "
                "Installez fr_core_news_md pour rétablir la protection des noms/adresses/organisations.",
                settings.block_external_llm_without_ner,
            )
    except Exception:
        pass
    # LA VOIX : le modèle Whisper local se charge en arrière-plan dès le
    # démarrage, pour que la première dictée ne paie pas ses secondes de
    # chargement (03/09, « beaucoup trop lent »). Fire-and-forget : rien
    # n'attend, rien ne casse si le modèle manque.
    if travaux_de_fond:
        try:
            from voix.transcription import prechauffer
            asyncio.create_task(prechauffer())
        except Exception:
            pass
    # LE CATALOGUE DU SERVEUR DE FICHIERS (08/09) : là où un NAS est branché,
    # son arborescence se construit en tâche de fond dès le démarrage et se
    # rafraîchit seule — la recherche par nom devient un filtre en mémoire.
    # Sans module `nas` (le jumeau sur Drive), l'import échoue et rien ne part.
    try:
        from nas.acces import demarrer_catalogue
        asyncio.create_task(demarrer_catalogue())
    except Exception:
        pass
    # L'OCR DES SCANS, LA NUIT (15/09, `nas/tri.py`) : la synchronisation de jour
    # les met de côté ; cette boucle lance, une fois par nuit, la lecture de ce
    # qui attend. Sans module `nas`, rien ne part.
    if travaux_de_fond:
        try:
            from nas.tri import boucle_continue, boucle_de_nuit
            from routers.ingestion import lancer_en_fond
            lancer_en_fond(boucle_de_nuit())
            # Un palier de lecture toutes les dix minutes, lancé par le serveur.
            lancer_en_fond(boucle_continue())
        except Exception:
            pass
    # LA CARTE DU CLASSEMENT (08/09 soir) : l'architecture du stockage relevée
    # en fond, gardée en mémoire (prompt, `ou_chercher`) et écrite dans la base
    # vectorisée (recherche documentaire). Six heures entre deux relevés.
    if travaux_de_fond:
        try:
            from classement.carte import demarrer_carte
            asyncio.create_task(demarrer_carte())
        except Exception:
            pass
    yield
    from ressources.documents_file import arreter as arreter_documents
    await arreter_documents()
    try:
        from vectorstore.worker import stop_embedding_worker
        await stop_embedding_worker()
    except Exception:
        pass
    try:
        from tasks.worker import stop_task_worker
        await stop_task_worker()
    except Exception:
        pass
    try:
        from security.cleanup import stop_validation_cleanup
        await stop_validation_cleanup()
    except Exception:
        pass
    await shutdown_runtime()
    from database.connection import close_db
    await close_db()
    try:
        from observability import flush
        flush()
    except Exception:
        pass


app = FastAPI(
    title="Duret & Sols API",
    version="1.0.0",
    docs_url="/api/docs" if settings.debug else None,
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _limit_body_size(request, call_next):
    """Anti-DoS mémoire : rejette (413) tout corps dont Content-Length dépasse la limite."""
    cl = request.headers.get("content-length")
    plafond = settings.max_chat_body_mb if request.url.path == "/api/chat/" else settings.max_body_mb
    if cl and cl.isdigit() and int(cl) > plafond * 1024 * 1024:
        from starlette.responses import JSONResponse
        return JSONResponse(status_code=413, content={"detail": "Corps de requête trop volumineux"})
    return await call_next(request)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(validation.router, prefix="/api/validations", tags=["validations"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(settings_router.router, prefix="/api/settings", tags=["settings"])
app.include_router(ingestion.router, prefix="/api/ingestion", tags=["ingestion"])
app.include_router(browser.router, prefix="/api/browser", tags=["browser"])
app.include_router(skills_router.router, prefix="/api/skills", tags=["skills"])
app.include_router(mail_router.router, prefix="/api/mail", tags=["mail"])
# La connexion Google PERSONNELLE de chaque utilisateur (Paramètres > Ma boîte
# Google). Le retour OAuth (/api/google/retour) est public par nature : c'est
# le navigateur redirigé par Google qui y arrive, l'identité voyage dans le
# state signé.
app.include_router(google_perso_router.router, prefix="/api/google", tags=["google"])
app.include_router(tasks_router.router, prefix="/api/tasks", tags=["tasks"])
app.include_router(learning_router.router, prefix="/api/learning", tags=["learning"])
app.include_router(documents_produits.router, prefix="/api/documents", tags=["documents"])
# Guichet du conteneur navigateur : il raconte, le backend écrit. NON EXPOSÉ
# par nginx — aucun bloc `location` ne le route, il ne vit que sur le réseau
# interne, et chaque appel porte le secret partagé.
app.include_router(navigateur_interne.router, prefix="/api/interne/navigateur",
                   tags=["navigateur-interne"])
# /api/hooks : PAS de JWT — authentification par signature HMAC (voir routers/hooks.py).
app.include_router(hooks_router.router, prefix="/api/hooks", tags=["hooks"])
app.include_router(file_attente.router, prefix="/api/file", tags=["file"])
# Le tableau de bord de direction : même préfixe que `dashboard`, routes distinctes.
app.include_router(tableau.router, prefix="/api/dashboard", tags=["tableau"])

# Offre visuelle (propre au client) : la route ne se monte que la ou le module
# existe — l'import optionnel garde ce fichier IDENTIQUE chez tous les clients.
try:
    from routers import visuels as visuels_router
    app.include_router(visuels_router.router, prefix="/api/visuels", tags=["visuels"])
except ImportError:
    pass

# Niveau d'accès par dossier du serveur de fichiers (propre au socle NAS) :
# même import optionnel, pour la même raison.
try:
    from routers import nas_niveaux as nas_niveaux_router
    app.include_router(nas_niveaux_router.router, prefix="/api/nas-niveaux", tags=["nas"])
except ImportError:
    pass

# Le tri avant la lecture du NAS (15/09) : même import optionnel.
try:
    from routers import nas_tri as nas_tri_router
    app.include_router(nas_tri_router.router, prefix="/api/nas-tri", tags=["nas"])
except ImportError:
    pass


# L'explorateur du NAS du tableau de bord (23/09, super_admin seul) : même import optionnel.
try:
    from routers import nas_explorateur as nas_explorateur_router
    app.include_router(nas_explorateur_router.router, prefix="/api/nas-explorateur", tags=["nas"])
except ImportError:
    pass


# ── VIVANT N'EST PAS PRÊT (16/09, audit D-26) ──────────────────────────────
# `/api/health` disait « ok » dès que le processus répondait : il disait donc
# « ok » avec un schéma incomplet, une base injoignable ou la mémoire des
# conversations en mode volatil. On sépare :
#   · /api/health  — LIVENESS : le processus vit (c'est tout, et c'est voulu) ;
#   · /api/ready   — READINESS : base joignable, migrations du disque toutes
#                    suivies, checkpointer durable — et le COMMIT livré.
# Une source facultative en panne (NAS, mail, modèle) ne rend pas le site
# inutilisable : elle est DITE dégradée, elle n'empêche pas d'être prêt.
def version_livree() -> dict:
    """Le commit réellement en service, écrit par `deploy.sh` (backend/.version)."""
    fiche = {}
    try:
        import pathlib as _pathlib
        for ligne in (_pathlib.Path(__file__).with_name(".version")).read_text(encoding="utf-8").splitlines():
            if "=" in ligne:
                cle, valeur = ligne.split("=", 1)
                fiche[cle.strip()] = valeur.strip()
    except Exception:  # noqa: BLE001 — hors déploiement (poste de dev), on ne sait pas
        pass
    return fiche


async def _etat_du_service() -> dict:
    """Ce qui doit être vrai pour servir : base, schéma, mémoire durable."""
    from pathlib import Path as _Path
    etat = {"base": False, "schema": False, "checkpointer": False, "manquantes": [],
            "version": version_livree()}
    try:
        from database.connection import get_db
        async with get_db() as conn:
            await conn.fetchval("SELECT 1")
            etat["base"] = True
            suivies = {r["filename"] for r in await conn.fetch("SELECT filename FROM schema_migrations")}
        fichiers = {f.name for f in (_Path(__file__).parent / "database" / "migrations").glob("[0-9]*.sql")}
        etat["manquantes"] = sorted(fichiers - suivies)
        etat["schema"] = not etat["manquantes"]
    except Exception as e:  # noqa: BLE001 — une base muette n'est pas « prête »
        etat["erreur_base"] = str(e)[:200]
    try:
        from agents.checkpointer import get_checkpointer
        saver = await get_checkpointer()
        etat["checkpointer"] = type(saver).__name__ != "MemorySaver"
        etat["checkpointer_type"] = type(saver).__name__
    except Exception as e:  # noqa: BLE001
        etat["erreur_checkpointer"] = str(e)[:200]
    try:
        from agents.runtime import get_graph
        etat["graphe"] = await get_graph() is not None
    except Exception:
        etat["graphe"] = False
    try:
        import tempfile
        import os
        from bureautique.atelier import DOSSIER
        dossier = DOSSIER
        os.makedirs(dossier, exist_ok=True)
        with tempfile.TemporaryFile(dir=dossier) as controle:
            controle.write(b"controle")
            controle.flush()
        from stockage.capacite import etat as capacite_disque
        etat["disque_documents"] = capacite_disque(dossier)
        etat["documents"] = True
    except (OSError, ValueError):
        etat["documents"] = False
    etat["pret"] = bool(etat["base"] and etat["schema"] and etat["checkpointer"]
                        and etat["graphe"] and etat["documents"])
    return etat


@app.get("/api/health")
async def health():
    """LIVENESS : le processus répond. Ne dit RIEN de la base ni du schéma."""
    return {"status": "ok", "service": "duret-pluton", **version_livree()}


@app.get("/api/ready")
async def ready():
    """READINESS : ce qu'il faut pour servir vraiment. 503 tant que ça manque."""
    from fastapi.responses import JSONResponse
    etat = await _etat_du_service()
    return JSONResponse(status_code=200 if etat["pret"] else 503, content=etat)
