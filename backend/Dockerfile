FROM python:3.12-slim

WORKDIR /app

# tesseract-ocr : reconnaissance de caractères pour les PDF scannés et les photos
# de documents (import de données). Le pack `fra` est indispensable — sans lui,
# tesseract lit le français avec le modèle anglais et produit du charabia.
# OCR LOCAL et volontaire : aucune image de document ne part vers un service externe.
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    tesseract-ocr \
    tesseract-ocr-fra \
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

# Le modèle Whisper LOCAL (transcription de la voix sans jeton d'IA), téléchargé
# AU BUILD pour que la première dictée ne fasse pas attendre 460 Mo. S'il ne
# se télécharge pas ici (réseau), l'image se construit quand même : le modèle
# viendra au premier usage, dans le volume des documents, et Google sert de
# secours entre-temps.
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('base', device='cpu', compute_type='int8')" \
    || echo "modele Whisper non pre-telecharge : il viendra au premier usage"

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
