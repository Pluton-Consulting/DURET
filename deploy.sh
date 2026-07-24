#!/usr/bin/env bash
# =====================================================================
#  Déploiement / mise à jour de Symbiose sur le VPS.
#  À lancer depuis le dossier symbiose-noa/ APRÈS avoir rempli .env :
#      chmod +x deploy.sh
#      ./deploy.sh
#  Idempotent : relançable pour appliquer une mise à jour (git pull puis ./deploy.sh).
#  Détail des étapes : voir DEPLOY.md.
# =====================================================================
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "ERREUR : fichier .env manquant. Copie .env.example vers .env puis remplis-le." >&2
  exit 1
fi

# Lit une variable du .env SANS le sourcer : le .env (format Docker Compose) peut contenir
# des espaces / des caractères < > qui casseraient `. .env`. On ne prend que la PREMIÈRE
# occurrence (robuste si le .env a été collé en double), et on retire un éventuel
# commentaire de fin de ligne + les espaces.
env_get() { awk -F= -v k="$1" '$1==k{sub(/^[^=]*=/,"");sub(/[[:space:]]+#.*$/,"");sub(/[[:space:]]*$/,"");print;exit}' .env; }
POSTGRES_USER="$(env_get POSTGRES_USER)"
POSTGRES_DB="$(env_get POSTGRES_DB)"
FIRST_ADMIN_EMAIL="$(env_get FIRST_ADMIN_EMAIL)"
: "${POSTGRES_USER:?POSTGRES_USER manquant dans .env}"
: "${POSTGRES_DB:?POSTGRES_DB manquant dans .env}"

COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"

echo "==> 1/5  Build des images + démarrage (détaché)…"
$COMPOSE up -d --build

# nginx met en cache l'IP des upstreams (backend/frontend) à son démarrage. Après un
# rebuild qui recrée backend/frontend (nouvelles IP Docker), nginx garde d'anciennes IP
# -> erreurs 502 sur /api/. On le redémarre pour qu'il re-résolve les IP courantes.
$COMPOSE restart nginx >/dev/null 2>&1 || true

echo "==> 2/5  Attente de Postgres (healthcheck)…"
cid="$($COMPOSE ps -q postgres)"
until [ "$(docker inspect -f '{{.State.Health.Status}}' "$cid" 2>/dev/null || echo starting)" = "healthy" ]; do
  printf '.'; sleep 3
done
echo " ok"

echo "==> 3/5  Migrations SQL (seulement les nouvelles — RBAC non écrasé)…"
# Raccourci psql (tuples-only, unaligned) pour les tests/inserts de suivi.
PSQL() { $COMPOSE exec -T postgres psql -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"; }

# Table de suivi des migrations déjà appliquées (idempotent).
PSQL -q -c "CREATE TABLE IF NOT EXISTS schema_migrations (filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ DEFAULT now());" >/dev/null

# Backfill de transition : base DÉJÀ initialisée (table users présente) mais suivi vide
# = migrations jouées par un ancien deploy → on les marque appliquées SANS les rejouer
# (sinon la 011 réécraserait les permissions RBAC personnalisées à chaque déploiement).
if [ "$(PSQL -c "SELECT count(*) FROM schema_migrations;" | tr -d '[:space:]')" = "0" ] \
   && [ "$(PSQL -c "SELECT (to_regclass('public.users') IS NOT NULL);" | tr -d '[:space:]')" = "t" ]; then
  echo "    (base existante détectée → marquage des migrations en place, sans rejeu)"
  for f in backend/database/migrations/[0-9]*.sql; do
    PSQL -q -c "INSERT INTO schema_migrations(filename) VALUES ('$(basename "$f")') ON CONFLICT DO NOTHING;" >/dev/null
  done
fi

# Application des seules migrations NON encore suivies (les nouvelles).
for f in backend/database/migrations/[0-9]*.sql; do
  name="$(basename "$f")"
  if [ "$(PSQL -c "SELECT 1 FROM schema_migrations WHERE filename='$name';" | tr -d '[:space:]')" = "1" ]; then
    continue
  fi
  echo "    - $name"
  if $COMPOSE exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -q -f "/migrations/$name" >/dev/null 2>&1; then
    PSQL -q -c "INSERT INTO schema_migrations(filename) VALUES ('$name') ON CONFLICT DO NOTHING;" >/dev/null
  else
    echo "      ⚠ échec de $name — non enregistrée, sera retentée au prochain deploy"
  fi
done

echo "==> 4/5  Administrateur + catalogue de skills…"
if [ -n "${FIRST_ADMIN_EMAIL:-}" ]; then
  $COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -q -c \
    "INSERT INTO users (email, name, role) VALUES ('${FIRST_ADMIN_EMAIL}', 'Administrateur', 'super_admin') ON CONFLICT (email) DO UPDATE SET role='super_admin', actif=true;" \
    && echo "    super_admin : ${FIRST_ADMIN_EMAIL}"
fi
$COMPOSE exec -T backend sh -c "PYTHONPATH=. python scripts/seed_skills_catalogue.py" \
  && echo "    catalogue de skills : ok" || echo "    (seed skills ignoré — relançable plus tard)"

echo "==> 5/5  État des services :"
$COMPOSE ps
echo
echo "Terminé. Suivre les logs :  $COMPOSE logs -f backend"
