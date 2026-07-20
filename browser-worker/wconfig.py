"""
Configuration du worker navigateur — lue depuis l'environnement (partagé via .env
+ overrides docker-compose). Volontairement autonome : n'importe AUCUN code backend.
"""
import os


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


DATABASE_URL = os.environ.get("DATABASE_URL", "")

# LLM
LLM_PROVIDER = os.environ.get("BROWSER_LLM_PROVIDER", "deepseek").lower()
LLM_MODEL = os.environ.get("BROWSER_LLM_MODEL", "deepseek-chat")

# Comportement de l'agent
MAX_STEPS = int(os.environ.get("BROWSER_AGENT_MAX_STEPS", "40"))
APPROVAL_TIMEOUT_S = int(os.environ.get("BROWSER_APPROVAL_TIMEOUT_S", "1800"))
USE_VISION = _bool("BROWSER_USE_VISION", False)
# Lecture seule : exclut input_text/send_keys (pas de saisie ni soumission de formulaire).
READONLY = _bool("BROWSER_READONLY", True)

# Secrets par site + sessions connectées (montés dans le conteneur)
SITE_CREDENTIALS_FILE = os.environ.get("SITE_CREDENTIALS_FILE", "/secrets/site_credentials.json")
SESSIONS_DIR = os.environ.get("BROWSER_SESSIONS_DIR", "/sessions")

# Réinjection RAG via le webhook d'ingestion du backend
BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000")
INGESTION_WEBHOOK_SECRET = os.environ.get("INGESTION_WEBHOOK_SECRET", "")

# Capture d'écran : largeur max (downscale) pour limiter la taille en base
SCREENSHOT_MAX_WIDTH = int(os.environ.get("BROWSER_SCREENSHOT_MAX_WIDTH", "1000"))
