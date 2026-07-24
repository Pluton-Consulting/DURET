#!/usr/bin/env bash
# =====================================================================
#  Sauvegarde de Symbiose : base de données (données client) + .env.
#  À lancer depuis le dossier symbiose-noa/. Idéal en CRON quotidien.
#      chmod +x backup.sh && ./backup.sh
#  Réglages (optionnels, via variables d'env) :
#      BACKUP_DIR (défaut ~/symbiose-backups)  RETENTION_DAYS (défaut 14)
#  RESTAURATION : voir la fin de ce fichier.
# =====================================================================
set -euo pipefail
cd "$(dirname "$0")"

BACKUP_DIR="${BACKUP_DIR:-$HOME/symbiose-backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
STAMP="$(date +%Y-%m-%d_%H%M)"
mkdir -p "$BACKUP_DIR"

COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
# Lit POSTGRES_USER / POSTGRES_DB depuis .env (1re occurrence, robuste aux doublons).
env_get() { awk -F= -v k="$1" '$1==k{sub(/^[^=]*=/,"");sub(/[[:space:]]+#.*$/,"");sub(/[[:space:]]*$/,"");print;exit}' .env; }
PG_USER="$(env_get POSTGRES_USER)"
PG_DB="$(env_get POSTGRES_DB)"

# 1) Dump de la base — restaurable tel quel (DROP + CREATE inclus), compressé.
$COMPOSE exec -T postgres pg_dump -U "$PG_USER" --clean --if-exists "$PG_DB" \
  | gzip > "$BACKUP_DIR/db_${STAMP}.sql.gz"

# 2) Copie du .env (secrets + config, NON versionnés → indispensables à une restauration).
cp .env "$BACKUP_DIR/env_${STAMP}.bak"

# 3) Purge des sauvegardes de plus de RETENTION_DAYS jours.
find "$BACKUP_DIR" -name 'db_*.sql.gz' -mtime +"$RETENTION_DAYS" -delete
find "$BACKUP_DIR" -name 'env_*.bak'   -mtime +"$RETENTION_DAYS" -delete

echo "OK $(date '+%F %T') -> $BACKUP_DIR/db_${STAMP}.sql.gz ($(du -h "$BACKUP_DIR/db_${STAMP}.sql.gz" | cut -f1))"

# =====================================================================
#  RESTAURER une sauvegarde (manuel) :
#    gunzip -c ~/symbiose-backups/db_AAAA-MM-JJ_HHMM.sql.gz \
#      | docker compose -f docker-compose.yml -f docker-compose.prod.yml \
#          exec -T postgres psql -U noa_user -d symbiose_noa
# =====================================================================
