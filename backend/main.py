import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from database.connection import init_db
from routers import auth, users, chat, dashboard, validation, settings as settings_router, ingestion, browser, skills as skills_router, mail as mail_router, tasks as tasks_router, hooks as hooks_router, learning as learning_router, documents_produits
from agents.runtime import init_runtime, shutdown_runtime
from config import settings

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)


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
app.include_router(tasks_router.router, prefix="/api/tasks", tags=["tasks"])
app.include_router(learning_router.router, prefix="/api/learning", tags=["learning"])
app.include_router(documents_produits.router, prefix="/api/documents", tags=["documents"])
# /api/hooks : PAS de JWT — authentification par signature HMAC (voir routers/hooks.py).
app.include_router(hooks_router.router, prefix="/api/hooks", tags=["hooks"])


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "duret-sols"}
