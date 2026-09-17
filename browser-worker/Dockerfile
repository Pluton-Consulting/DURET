# Image officielle browser-use : inclut browser-use + Chromium + dépendances système,
# via un venv à /app/.venv (appartenant à root) et un utilisateur d'exécution `browseruse`.
FROM browseruse/browseruse@sha256:689123c4998749972d320d6560f81f13595135ee5caea4093fbbc99b8bd039eb

# Installer les deps du worker DANS le venv de l'image. Le venv est géré par `uv`
# (pas de `pip` dedans) et appartient à root → on installe via uv, en root.
USER root
COPY requirements.lock /tmp/worker-requirements.lock
RUN uv pip install --python /app/.venv/bin/python --no-cache --require-hashes -r /tmp/worker-requirements.lock

RUN mkdir -p /sessions && chown browseruse:browseruse /sessions

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
