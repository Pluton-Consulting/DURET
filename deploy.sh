#!/usr/bin/env bash
# =====================================================================
#  DÉPLOIEMENT / MISE À JOUR DE DURET & SOLS sur le VPS.
#
#  À lancer depuis le dossier du projet, APRÈS avoir rempli .env :
#      chmod +x deploy.sh && ./deploy.sh
#  Idempotent : relançable pour appliquer une mise à jour (git pull puis ./deploy.sh).
#  Détail des étapes : voir DEPLOY.md.
#
#  CE QUI A CHANGÉ LE 16/09 (audit D-26). Avant, le script démarrait TOUT, puis
#  migrait ; une migration en échec était signalée… et la livraison continuait.
#  Pire : sur une base déjà en service dont le suivi était vide, il marquait
#  TOUTES les migrations « appliquées » sans regarder si leurs objets existaient
#  — une migration manquée le restait pour toujours, en silence.
#  Désormais, dans cet ordre : on construit, on SAUVEGARDE, on démarre la base
#  seule, on MIGRE (un échec arrête tout), on vérifie le schéma, puis seulement
#  on bascule l'application et l'on attend qu'elle se déclare PRÊTE.
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
SAUVEGARDE_AVANT="${SAUVEGARDE_AVANT:-1}"
MIGRATIONS="backend/database/migrations"

echo "==> 1/7  Version livrée…"
# Le commit est écrit dans un fichier lu par l'application : `/api/ready` le
# rend, et l'on sait enfin QUELLE version tourne (audit D-26). Le conteneur n'a
# pas le dépôt git ; ce fichier, lui, est monté avec le code.
{
  echo "commit=$(git rev-parse HEAD 2>/dev/null || echo inconnu)"
  echo "branche=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo inconnue)"
  echo "livre_le=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
} > backend/.version
echo "    $(head -1 backend/.version)"

echo "==> 2/7  Construction des images (sans bascule)…"
$COMPOSE build

if [ "$SAUVEGARDE_AVANT" = "1" ] && [ -x ./backup.sh ]; then
  echo "==> 3/7  Sauvegarde AVANT migration…"
  # Une migration se joue sur une base dont on a une copie de moins d'une minute.
  if ! ./backup.sh; then
    echo "ERREUR : la sauvegarde a échoué — livraison arrêtée." >&2
    echo "  (pour passer outre, en connaissance de cause : SAUVEGARDE_AVANT=0 ./deploy.sh)" >&2
    exit 1
  fi
else
  echo "==> 3/7  Sauvegarde : IGNORÉE (SAUVEGARDE_AVANT=0 ou backup.sh absent)"
fi

echo "==> 4/7  Base de données seule, et son healthcheck…"
$COMPOSE up -d postgres
cid="$($COMPOSE ps -q postgres)"
until [ "$(docker inspect -f '{{.State.Health.Status}}' "$cid" 2>/dev/null || echo starting)" = "healthy" ]; do
  printf '.'; sleep 3
done
echo " ok"

echo "==> 5/7  Migrations (ligne de base vérifiée ; un échec ARRÊTE la livraison)…"
PSQL() { $COMPOSE exec -T postgres psql -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"; }
PSQL -q -c "CREATE TABLE IF NOT EXISTS schema_migrations (filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ DEFAULT now());" >/dev/null

# LA LIGNE DE BASE, VÉRIFIÉE OBJET PAR OBJET. Sur une base déjà en service dont
# le suivi est vide, on ne marque « appliquée » que la migration dont l'objet
# est RÉELLEMENT là (`attendus.tsv`). Les autres seront jouées.
if [ "$(PSQL -c "SELECT count(*) FROM schema_migrations;" | tr -d '[:space:]')" = "0" ] \
   && [ "$(PSQL -c "SELECT (to_regclass('public.users') IS NOT NULL);" | tr -d '[:space:]')" = "t" ]; then
  echo "    base existante : marquage des migrations DONT L'OBJET EST PRÉSENT"
  while IFS=$'\t' read -r nom requete; do
    case "$nom" in \#*|"") continue;; esac
    [ -f "$MIGRATIONS/$nom" ] || continue
    if [ "$(PSQL -c "$requete" | tr -d '[:space:]')" = "t" ]; then
      PSQL -q -c "INSERT INTO schema_migrations(filename) VALUES ('$nom') ON CONFLICT DO NOTHING;" >/dev/null
    else
      echo "      · $nom : objet ABSENT → elle sera jouée"
    fi
  done < "$MIGRATIONS/attendus.tsv"
fi

for f in "$MIGRATIONS"/[0-9]*.sql; do
  nom="$(basename "$f")"
  if [ "$(PSQL -c "SELECT 1 FROM schema_migrations WHERE filename='$nom';" | tr -d '[:space:]')" = "1" ]; then
    continue
  fi
  echo "    - $nom"
  if $COMPOSE exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -q -f "/migrations/$nom"; then
    PSQL -q -c "INSERT INTO schema_migrations(filename) VALUES ('$nom') ON CONFLICT DO NOTHING;" >/dev/null
  else
    echo >&2
    echo "ERREUR : la migration $nom a échoué — LIVRAISON ARRÊTÉE." >&2
    echo "  L'application n'a pas été basculée : la version en service est celle d'avant." >&2
    echo "  Corrigez la migration, puis relancez ./deploy.sh (elle sera retentée seule)." >&2
    exit 1
  fi
done

# LE SCHÉMA EST-IL COMPLET ? Une migration présente sur le disque et absente du
# suivi, c'est une livraison qui ne tient pas ses promesses.
manquantes=""
for f in "$MIGRATIONS"/[0-9]*.sql; do
  nom="$(basename "$f")"
  [ "$(PSQL -c "SELECT 1 FROM schema_migrations WHERE filename='$nom';" | tr -d '[:space:]')" = "1" ] || manquantes="$manquantes $nom"
done
if [ -n "$manquantes" ]; then
  echo "ERREUR : migrations non appliquées :$manquantes — livraison arrêtée." >&2
  exit 1
fi
echo "    schéma complet ($(PSQL -c "SELECT count(*) FROM schema_migrations;" | tr -d '[:space:]') migrations suivies)"

echo "==> 6/7  Bascule de l'application…"
$COMPOSE up -d
# nginx met en cache l'IP des upstreams (backend/frontend) à son démarrage. Après un
# rebuild qui recrée backend/frontend (nouvelles IP Docker), nginx garde d'anciennes IP
# -> erreurs 502 sur /api/. On le redémarre pour qu'il re-résolve les IP courantes.
$COMPOSE restart nginx >/dev/null 2>&1 || true

echo "    administrateur + catalogue de skills…"
# Plus d'unicité sur l'adresse seule depuis la 040 (profils d'une boîte
# partagée) : l'administrateur est créé s'il manque, et promu seulement s'il
# est SEUL sur son adresse — jamais tous les profils d'une adresse partagée.
if [ -n "${FIRST_ADMIN_EMAIL:-}" ]; then
  $COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -q -c \
    "INSERT INTO users (email, name, role) SELECT '${FIRST_ADMIN_EMAIL}', 'Administrateur', 'super_admin' WHERE NOT EXISTS (SELECT 1 FROM users WHERE lower(email) = lower('${FIRST_ADMIN_EMAIL}')); UPDATE users SET role='super_admin', actif=true WHERE lower(email) = lower('${FIRST_ADMIN_EMAIL}') AND (SELECT count(*) FROM users WHERE lower(email) = lower('${FIRST_ADMIN_EMAIL}')) = 1;" \
    && echo "      super_admin : ${FIRST_ADMIN_EMAIL}"
fi
$COMPOSE exec -T backend sh -c "PYTHONPATH=. python scripts/seed_skills_catalogue.py" >/dev/null \
  && echo "      catalogue de skills : ok" || echo "      (seed skills ignoré — relançable plus tard)"

echo "==> 7/7  L'application se déclare-t-elle PRÊTE ?"
# Readiness ≠ liveness : le processus peut répondre alors que le schéma, la
# base ou la mémoire durable des conversations manquent (audit D-26).
pret=""
for _ in $(seq 1 40); do
  if reponse="$($COMPOSE exec -T backend python -c "
import json, urllib.request
print(urllib.request.urlopen('http://localhost:8000/api/ready', timeout=5).read().decode())" 2>/dev/null)"; then
    pret="$reponse"
    break
  fi
  printf '.'; sleep 5
done
echo
if [ -n "$pret" ]; then
  echo "    $pret"
else
  echo "⚠ L'application ne s'est pas déclarée prête. Ce qu'elle dit :" >&2
  $COMPOSE exec -T backend python -c "
import urllib.error, urllib.request
try:
    urllib.request.urlopen('http://localhost:8000/api/ready', timeout=5)
except urllib.error.HTTPError as e:
    print(e.read().decode()[:800])
except Exception as e:
    print('injoignable :', e)" 2>/dev/null || true
  echo >&2
  echo "  RETOUR ARRIÈRE : git checkout <commit précédent> && ./deploy.sh" >&2
  echo "  (les migrations additives de cette version restent en place : l'ancienne image les ignore)" >&2
  exit 1
fi

echo
$COMPOSE ps
echo
echo "Terminé. Suivre les logs :  $COMPOSE logs -f backend"
