FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Modèle spaCy français (NER pour l'anonymisation RGPD) — OBLIGATOIRE.
# Essaie lg (idéal) puis md, puis sm. Si AUCUN ne s'installe, le build ÉCHOUE
# volontairement : sans NER, les noms/adresses/organisations ne seraient pas masqués
# avant envoi aux LLM externes (fuite PII). Ne jamais accepter un build sans modèle.
RUN python -m spacy download fr_core_news_lg \
    || python -m spacy download fr_core_news_md \
    || python -m spacy download fr_core_news_sm

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
