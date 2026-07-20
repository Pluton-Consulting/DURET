# Setup Duret & Sols — Duret & Sols

## Prérequis
- Ubuntu 24.04
- Docker + Docker Compose installés
- Headscale installé et configuré
- Domaine Google Workspace pour OAuth2

## Étapes

### 1. Cloner et configurer
```bash
git clone <repo>
cd duret-sols
cp .env.example .env
# Éditer .env avec les vraies valeurs
```

### 2. Générer les secrets
```bash
openssl rand -base64 32  # → NEXTAUTH_SECRET
openssl rand -hex 32     # → JWT_SECRET_KEY
openssl rand -hex 32     # → LANGFUSE_SECRET_KEY
openssl rand -hex 16     # → LANGFUSE_SALT
```

### 3. Configurer Google OAuth2
- Aller sur console.cloud.google.com
- Créer un projet → APIs → OAuth 2.0 Client IDs
- URI de redirection autorisé : `http://<HEADSCALE_IP>/api/auth/callback/google`
- Ajouter `GOOGLE_CLIENT_ID` et `GOOGLE_CLIENT_SECRET` dans `.env`

### 4. Créer le réseau Docker partagé (requis avant Langfuse)
```bash
docker network create noa_network
```

### 5. Lancer l'infrastructure principale
```bash
docker compose up -d
```

### 6. Initialiser la base de données
```bash
docker compose exec postgres psql -U noa_user -d duret_noa -f /migrations/001_initial_schema.sql
```

### 7. Vérifier les extensions pgvector
```bash
docker compose exec postgres psql -U noa_user -d duret_noa -c "\dx"
# Doit afficher : vector, pg_trgm, uuid-ossp
```

### 8. Lancer Langfuse
```bash
docker compose -f docker-compose.langfuse.yml up -d
```

### 9. Configurer Langfuse
- Accéder à `http://<HEADSCALE_IP>:3001`
- Créer un compte admin → créer un projet
- Récupérer `LANGFUSE_PUBLIC_KEY` → mettre dans `.env`
- Redémarrer le backend : `docker compose restart backend`

### 10. Installer Ollama (optionnel — palier léger local)
```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull mistral:7b
```
Mettre à jour `OLLAMA_BASE_URL` dans `.env` avec l'IP de l'hôte accessible depuis Docker.

### 11. Vérifier le déploiement
```bash
curl http://<HEADSCALE_IP>/api/health
# → {"status": "ok", "service": "duret-sols"}
```

## Modèle spaCy français (inclus dans le Dockerfile)
```bash
# Installé automatiquement au build via :
# python -m spacy download fr_core_news_lg
```

## Daytona (phase 2)
- Créer un compte sur app.daytona.io
- Récupérer l'API key → `DAYTONA_API_KEY` dans `.env`
- Sans cette clé, l'Agent 3 utilise le fallback subprocess local
