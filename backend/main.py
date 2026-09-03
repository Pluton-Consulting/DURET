import asyncio
import logging
import re as _re_logs
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from database.connection import init_db
from routers import auth, users, chat, dashboard, validation, settings as settings_router, ingestion, browser, skills as skills_router, mail as mail_router, tasks as tasks_router, hooks as hooks_router, learning as learning_router, documents_produits, file_attente, navigateur_interne, tableau, google_perso as google_perso_router
from agents.runtime import init_runtime, shutdown_runtime
from config import settings

# ── AUCUNE CLÉ NE DOIT SE RETROUVER DANS LES JOURNAUX ────────────────────
#
# Relevé le 27/08 en lisant `docker compose logs backend` : httpx journalise en
# INFO chaque requête avec son URL COMPLÈTE, et les API Google portent la clé
# dans la query string. La clé s'affichait donc en clair, lisible par quiconque
# ouvre les journaux ou en poste une capture d'écran. Aucune ligne de code ne
# l'écrivait : c'est la bibliothèque HTTP qui la recopiait.
#
# Deux protections, dans cet ordre :
#   1. un FILTRE sur la racine, qui masque le secret quel que soit le logger —
#      httpx aujourd'hui, une autre bibliothèque demain ;
#   2. httpx et httpcore remontés à WARNING : leur ligne par requête n'apprend
#      rien en exploitation, et c'est une source de fuite en moins.
#
# Le filtre garde les SIX DERNIERS caractères : c'est ce qui permet de dire
# « c'est bien la clé du fichier de configuration, pas celle de la base » sans
# jamais livrer la clé elle-même.
_SECRETS = _re_logs.compile(
    r"(?i)\b(key|api[_-]?key|access[_-]?token|token|apikey|password|secret)"
    r"(=|%3D|\"?\s*:\s*\"?)([A-Za-z0-9._\-]{12,})")


def _masquer(texte: str) -> str:
    def _remplacer(m):
        valeur = m.group(3)
        return f"{m.group(1)}{m.group(2)}***{valeur[-6:]}"
    return _SECRETS.sub(_remplacer, texte)


class _FiltreSecrets(logging.Filter):
    """Masque toute valeur qui ressemble à une clé, message ET arguments.

    On réécrit `msg` et `args` plutôt que le message formaté : le formatage
    n'a pas encore eu lieu quand le filtre passe, et une clé arrivée par `%s`
    échapperait à un filtre qui ne regarderait que `msg`.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str) and "=" in record.msg or ":" in str(record.msg):
                record.msg = _masquer(str(record.msg))
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {k: _masquer(v) if isinstance(v, str) else v
                                   for k, v in record.args.items()}
                else:
                    record.args = tuple(_masquer(a) if isinstance(a, str) else a
                                        for a in record.args)
        except Exception:  # noqa: BLE001 — un journal ne fait jamais tomber l'app
            pass
        return True


logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logging.getLogger().addFilter(_FiltreSecrets())
for _bavard in ("httpx", "httpcore"):
    logging.getLogger(_bavard).setLevel(logging.WARNING)
    logging.getLogger(_bavard).addFilter(_FiltreSecrets())


@asynccontextmanager
async def lifespan(app: FastAPI):
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
        from security.cleanup import start_validation_cleanup
        await start_validation_cleanup()
    except Exception as e:
        logging.getLogger("duret").error("start_validation_cleanup a échoué : %s", e)
    try:
        # Les clés saisies dans Paramètres priment sur le `.env` — encore
        # faut-il les CHARGER : sans ce rafraîchissement de démarrage, le
        # cache restait vide jusqu'à l'ouverture de la page Paramètres, et
        # chaque redéploiement faisait retomber l'application sur les clés
        # du fichier.
        from llm.cles import rafraichir as rafraichir_cles
        await rafraichir_cles(force=True)
        # Même raison, même piège : un réglage saisi dans Paramètres serait
        # ignoré après chaque redéploiement si son cache n'était rempli qu'à
        # l'ouverture de la page.
        from llm.reglages import rafraichir as rafraichir_reglages
        await rafraichir_reglages(force=True)
        # Les boîtes Google reliées par les utilisateurs : même piège que les
        # clés — le connecteur (qui tourne dans des threads) ne lit qu'un
        # cache, il faut le remplir dès le démarrage.
        from mail.google_perso import rafraichir as rafraichir_google
        await rafraichir_google(force=True)
    except Exception as e:
        logging.getLogger("duret").error("rafraichir_cles a échoué : %s", e)
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
    try:
        from voix.transcription import prechauffer
        asyncio.create_task(prechauffer())
    except Exception:
        pass
    yield
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
    if cl and cl.isdigit() and int(cl) > settings.max_body_mb * 1024 * 1024:
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


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "duret-pluton"}
