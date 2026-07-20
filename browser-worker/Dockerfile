# Image officielle browser-use : inclut browser-use + Chromium + dépendances système,
# via un venv à /app/.venv (appartenant à root) et un utilisateur d'exécution `browseruse`.
FROM browseruse/browseruse:latest

# Installer les deps du worker DANS le venv de l'image. Le venv est géré par `uv`
# (pas de `pip` dedans) et appartient à root → on installe via uv, en root.
USER root
RUN uv pip install --python /app/.venv/bin/python --no-cache \
    fastapi "uvicorn[standard]" asyncpg httpx pillow pydantic

WORKDIR /app
COPY . .

ENV PYTHONUNBUFFERED=1 \
    IN_DOCKER=True \
    PYTHONIOENCODING=utf-8

# Repasser en utilisateur non-root pour exécuter Chromium (browser-use ajoute --no-sandbox
# en contexte Docker via IN_DOCKER). Service interne, pas de port publié.
USER browseruse
ENTRYPOINT []
CMD ["/app/.venv/bin/python", "-m", "uvicorn", "worker:app", "--host", "0.0.0.0", "--port", "9000"]
