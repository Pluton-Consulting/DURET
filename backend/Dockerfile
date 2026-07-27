FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Modèle spaCy français (NER pour l'anonymisation RGPD) — OBLIGATOIRE.
# `md` plutôt que `lg` : ~10× plus léger et nettement plus rapide par requête, pour une
# précision NER quasi identique (le regex métier couvre déjà email/tél/IBAN/SIRET/montants).
# Repli `sm`. Si AUCUN ne s'installe, le build ÉCHOUE volontairement : sans NER, les
# noms/adresses/organisations partiraient en clair aux LLM externes (fuite PII).
RUN python -m spacy download fr_core_news_md \
    || python -m spacy download fr_core_news_sm

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
