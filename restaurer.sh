#!/usr/bin/env bash
# =====================================================================
#  RESTAURER UN JEU DE SAUVEGARDE — dans une copie ISOLÉE (16/09, audit D-23).
#
#  Une sauvegarde qu'on n'a jamais restaurée n'est pas une sauvegarde : c'est
#  une intention. Ce script reconstitue le projet À CÔTÉ de la production —
#  autre nom de projet Compose, donc AUTRES VOLUMES, autres ports — puis coupe
#  tout ce qui pourrait sortir : aucune clé d'API, aucune boîte mail reliée,
#  ni tâches planifiées, ni lecture automatique du NAS. Sans cela, une copie
#  restaurée enverrait de VRAIS mails aux clients avec de vieux brouillons.
#
#  Il ne touche JAMAIS la base ni les volumes de production : il refuse de
#  tourner sous le nom de projet de production, et ne joue aucun DROP ailleurs
#  que dans la base de la copie.
#
#  USAGE (sur le VPS, depuis le dossier du projet) :
#      chmod +x restaurer.sh
#      ./restaurer.sh ~/duret-backups/duret_2026-09-16_0300
#      # puis, quand les contrôles sont faits :
#      ./restaurer.sh --arreter
#
#  Réglages : PROJET_COPIE (défaut duret-restauration), PORT_FRONT (3100),
#             PORT_API (8100), BACKUP_PASSPHRASE (si les secrets sont chiffrés).
# =====================================================================
set -euo pipefail
umask 077
cd "$(dirname "$0")"

PROJET_COPIE="${PROJET_COPIE:-duret-restauration}"
PORT_FRONT="${PORT_FRONT:-3100}"
PORT_API="${PORT_API:-8100}"
DOSSIER_COPIE=".restauration"
SURCOUCHE="$DOSSIER_COPIE/docker-compose.restauration.yml"

champ_config() {
  docker compose $(python3 scripts/compose_livraison.py "$PWD") config --format json | python3 -c 'import sys,json; c=json.load(sys.stdin); k=sys.argv[1]; print(c["name"] if k=="projet" else c["services"]["postgres"]["environment"][k])' "$1"
}
PROJET_PROD="$(champ_config projet)"
PG_USER="$(champ_config POSTGRES_USER)"
PG_DB="$(champ_config POSTGRES_DB)"

# Les anciennes commandes/cron suivent le dossier réellement actif après une
# livraison en parallèle. Un backend arrêté ne redirige pas la sauvegarde de bascule.
ACTIF_ID="$(docker ps -q --filter "label=com.docker.compose.project=${PROJET_PROD}" --filter label=com.docker.compose.service=backend)"
if [ -n "$ACTIF_ID" ] && [ "$(printf '%s\n' "$ACTIF_ID" | wc -l | tr -d ' ')" = "1" ]; then
  ACTIF_DOSSIER="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' "$ACTIF_ID")"
  if [ -n "$ACTIF_DOSSIER" ] && [ -f "$ACTIF_DOSSIER/restaurer.sh" ] && [ "$(cd "$ACTIF_DOSSIER" && pwd -P)" != "$(pwd -P)" ]; then
    exec bash "$ACTIF_DOSSIER/restaurer.sh" "$@"
  fi
fi


# GARDE-FOU N°1 : on ne restaure jamais SUR la production.
if [ "$PROJET_COPIE" = "$PROJET_PROD" ]; then
  echo "REFUS : PROJET_COPIE ($PROJET_COPIE) est le projet de PRODUCTION." >&2
  echo "  Une restauration se fait à côté, jamais par-dessus." >&2
  exit 1
fi

# Fichier AUTONOME : une surcouche de production conserverait env_file: .env,
# les ports et les montages de secrets, même avec --env-file.
COPIE="docker compose -p $PROJET_COPIE --env-file $DOSSIER_COPIE/.env -f $SURCOUCHE"

if [ "${1:-}" = "--arreter" ]; then
  echo "==> Arrêt de la copie $PROJET_COPIE (ses volumes sont conservés)…"
  $COPIE down
  echo "Pour effacer aussi ses données :  docker volume rm ${PROJET_COPIE}_postgres_data ${PROJET_COPIE}_documents_produits"
  exit 0
fi

JEU="${1:-}"
if [ -z "$JEU" ] || [ ! -d "$JEU" ]; then
  echo "USAGE : ./restaurer.sh <dossier du jeu de sauvegarde>   (ou --arreter)" >&2
  exit 1
fi

echo "==> 1/6  Contrôle du jeu ${JEU}…"
[ -f "$JEU/base.sql.gz" ] || { echo "ERREUR : base.sql.gz manquant." >&2; exit 1; }
( cd "$JEU" && sha256sum -c --quiet EMPREINTES.sha256 ) \
  || { echo "ERREUR : les empreintes ne correspondent pas — jeu abîmé." >&2; exit 1; }
sed -n '1,20p' "$JEU/manifeste.txt"

echo "==> 2/6  Configuration ISOLÉE (aucune sortie possible)…"
mkdir -p "$DOSSIER_COPIE"
if [ -f "$SURCOUCHE" ]; then
  # La copie est arrêtée avant toute restauration ; aucun worker ne lit la
  # base pendant son remplacement. Les volumes de production sont distincts.
  $COPIE down
fi
# Le code de la copie ne monte pas le dossier backend de production, qui
# contient aussi les fichiers de credentials. Copie sans secrets ni caches.
if [ -d "$DOSSIER_COPIE/backend" ]; then
  mv "$DOSSIER_COPIE/backend" "$DOSSIER_COPIE/backend.precedent.$(date +%s).$$"
fi
mkdir -p "$DOSSIER_COPIE/backend"
tar --exclude='secrets' --exclude='.env*' --exclude='__pycache__' --exclude='.venv' \
    -cf - -C backend . | tar -xf - -C "$DOSSIER_COPIE/backend"
mkdir -p "$DOSSIER_COPIE/backend/secrets"
printf '{}\n' > "$DOSSIER_COPIE/backend/secrets/site_credentials.json"
# Le .env de la copie : celui de la production, PRIVÉ DE TOUT CE QUI SORT.
# Les clés et identifiants deviennent vides ; le lien magique et les tâches
# planifiées sont coupés. Ce qui n'a pas d'identifiant ne peut rien envoyer.
awk -F= '
  BEGIN { OFS="=" }
  /^(RESEND_API_KEY|SMTP_|MAIL_IMAP_|GOOGLE_|MS_|GMAIL_|OPENAI_|ANTHROPIC_|GROQ_|DEEPSEEK_|OPENROUTER_|LONGCAT_|OLLAMA_|LANGFUSE_|SYNOLOGY_PASSWORD|BROWSER_|DAYTONA_|MAIL_SMTP_|JETONS_CHIFFREMENT_)/ { next }
  /^COMPOSE_PROJECT_NAME=/ { next }
  /^AGENT_TASKS_ENABLED=/ { next }
  /^EMBEDDING_WORKER_ENABLED=/ { next }
  /^(JWT_SECRET_KEY|NEXTAUTH_SECRET|ENVIRONMENT|ROLE_PROCESSUS)=/ { next }
  { print }
' .env > "$DOSSIER_COPIE/.env"
{
  echo "COMPOSE_PROJECT_NAME=$PROJET_COPIE"
  echo "AGENT_TASKS_ENABLED=false"
  echo "EMBEDDING_WORKER_ENABLED=false"
  echo "ENVIRONMENT=restauration"
  echo "ROLE_PROCESSUS=api"
  echo "BROWSER_ENABLED=false"
  echo "BROWSER_AGENT_ENABLED=false"
  echo "RESEND_API_KEY="
  echo "JWT_SECRET_KEY=$(openssl rand -hex 32)"
  echo "NEXTAUTH_SECRET=$(openssl rand -hex 32)"
} >> "$DOSSIER_COPIE/.env"

cat > "$SURCOUCHE" <<YAML
# Surcouche de RESTAURATION (produite par restaurer.sh) : d'autres ports, et
# rien qui parle à l'extérieur. Les volumes portent le nom du projet
# $PROJET_COPIE : ceux de la production ne sont jamais montés ici.
services:
  postgres:
    image: pgvector/pgvector:pg16
    env_file: .env
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $PG_USER -d $PG_DB"]
      interval: 3s
      timeout: 3s
      retries: 40
    networks: [restauration]
  backend:
    build: ./backend
    env_file: .env
    environment:
      DOCUMENTS_DIR: /documents
      ROLE_PROCESSUS: api
      AGENT_TASKS_ENABLED: "false"
      EMBEDDING_WORKER_ENABLED: "false"
    volumes:
      - documents_produits:/documents
    ports:
      - "127.0.0.1:$PORT_API:8000"
    networks: [restauration]
  frontend:
    build:
      context: ../frontend
      args:
        NEXT_PUBLIC_API_URL: "http://localhost:$PORT_API"
    ports:
      - "127.0.0.1:$PORT_FRONT:3000"
    env_file: .env
    environment:
      NEXT_PUBLIC_API_URL: "http://localhost:$PORT_API"
      BACKEND_URL: "http://backend:8000"
      NEXTAUTH_URL: "http://localhost:$PORT_FRONT"
      HOSTNAME: "0.0.0.0"
      PORT: "3000"
    networks: [restauration]
volumes:
  postgres_data:
  documents_produits:
networks:
  restauration:
    internal: true
YAML

echo "==> 3/6  Démarrage de la base de la copie…"
$COPIE up -d postgres
cid="$($COPIE ps -q postgres)"
attentes=0
until [ "$(docker inspect -f '{{.State.Health.Status}}' "$cid" 2>/dev/null || echo starting)" = "healthy" ]; do
  attentes=$((attentes + 1))
  if [ "$attentes" -ge 60 ]; then
    echo "ERREUR : la base restaurée reste indisponible après 180 secondes." >&2
    exit 1
  fi
  printf '.'; sleep 3
done
echo " ok"

echo "==> 4/6  Restauration de la base…"
$COPIE exec -T postgres psql -v ON_ERROR_STOP=1 -q -U "$PG_USER" -d "$PG_DB" <<'SQL'
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='infra_ia_lecteur_rls') THEN
    CREATE ROLE infra_ia_lecteur_rls NOLOGIN NOSUPERUSER NOBYPASSRLS;
  END IF;
  EXECUTE format('GRANT infra_ia_lecteur_rls TO %I',current_user);
END $$;
SQL
gunzip -c "$JEU/base.sql.gz" | $COPIE exec -T postgres psql -v ON_ERROR_STOP=1 -q -U "$PG_USER" -d "$PG_DB" >/dev/null

# Une sauvegarde peut précéder les migrations du code utilisé pour la recette.
# Les appliquer uniquement à la COPIE avant de démarrer le backend.
python3 - "$PROJET_COPIE" "$SURCOUCHE" "$DOSSIER_COPIE/.env" <<'PYTHON'
import importlib.util,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('livrer',Path('scripts/livrer.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
l=m.Livraison(Path.cwd())
l.compose=['docker','compose','-p',sys.argv[1],'--env-file',sys.argv[3],'-f',sys.argv[2]]
l.charger_config();l.migrations()
PYTHON

echo "==> 5/6  Restauration des documents, puis coupure des sorties…"
if [ -f "$JEU/documents.tar.gz" ]; then
  docker volume create "${PROJET_COPIE}_documents_produits" >/dev/null
  docker run --rm -v "${PROJET_COPIE}_documents_produits":/cible \
      -v "$(cd "$JEU" && pwd)":/jeu:ro alpine:3.20 \
      sh -c 'find /cible -mindepth 1 -maxdepth 1 -exec rm -rf {} + && tar xzf /jeu/documents.tar.gz -C /cible'
fi
# GARDE-FOU N°2 : LE .env NE SUFFIT PAS. Les clés vivent AUSSI en base
# (`cles_api` prime sur le .env), et les comptes Google reliés portent des
# REFRESH TOKENS toujours valables. On coupe chaque source SÉPARÉMENT : une
# table absente d'un vieux jeu ne doit pas annuler les autres coupures (un seul
# `psql -c` est une seule transaction — tout serait défait).
couper() {   # $1 = phrase SQL, $2 = ce qu'elle coupe (pour le message)
  $COPIE exec -T postgres psql -q -v ON_ERROR_STOP=1 -U "$PG_USER" -d "$PG_DB" -c "$1" >/dev/null 2>&1 \
    && echo "    coupé : $2" || { echo "ERREUR : coupure non vérifiée : $2. Application non démarrée." >&2; exit 1; }
}
couper "DELETE FROM cles_api;"                   "clés d'API enregistrées à l'écran"
couper "DELETE FROM connexions_google;"          "comptes Google reliés (refresh tokens)"
couper "UPDATE agent_tasks SET enabled = false;" "tâches planifiées"
couper "INSERT INTO reglages (cle, valeur) VALUES ('nas_integration_continue', 'desactivee') ON CONFLICT (cle) DO UPDATE SET valeur = 'desactivee';" "lecture automatique du NAS"

echo "==> 6/6  Démarrage de l'application restaurée…"
$COPIE --parallel 1 build backend frontend
$COPIE up -d --no-build backend frontend
attentes=0
until $COPIE exec -T backend python -c "import json,urllib.request; r=json.load(urllib.request.urlopen('http://localhost:8000/api/ready',timeout=5)); assert r.get('pret') is True" >/dev/null 2>&1; do
  attentes=$((attentes + 1))
  if [ "$attentes" -ge 120 ]; then
    echo "ERREUR : la copie ne devient pas prête ; consulter les journaux du projet $PROJET_COPIE." >&2
    exit 1
  fi
  sleep 3
done

cat <<FIN

Copie restaurée : $PROJET_COPIE
  application  : http://localhost:$PORT_FRONT      (API : http://localhost:$PORT_API/api/ready)
  base         : volume ${PROJET_COPIE}_postgres_data
  documents    : volume ${PROJET_COPIE}_documents_produits
  sorties      : AUCUNE (clés vidées, boîte mail non reliée, tâches coupées)

LES QUATRE OBJETS À ROUVRIR (recette de l'audit D-23) :
  1. une CONVERSATION passée : ses messages, ses pièces jointes s'affichent ;
  2. une TRAME enregistrée : elle se rouvre et se remplit ;
  3. un DOCUMENT avec image : l'image est là (elle vient du volume restauré) ;
  4. un BROUILLON de mail lié à un document : le document est toujours joint.
Notez le temps qu'a pris la reprise et l'heure du dernier point restaurable
(manifeste du jeu) : c'est ce couple qui dit ce que la maison peut perdre.

Quand c'est fini :  ./restaurer.sh --arreter
FIN
