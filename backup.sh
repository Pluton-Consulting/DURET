#!/usr/bin/env bash
# =====================================================================
#  SAUVEGARDE DE DURET & SOLS — la base ET les fichiers, en un seul jeu.
#
#  Ce que couvrait l'ancienne version : le dump PostgreSQL et le .env.
#  Ce qui manquait (16/09, audit D-23) : le volume des documents produits —
#  les Word et Excel rendus, les VISUELS et leurs propriétaires, les pièces
#  de l'atelier — et le dossier des secrets des connecteurs. Une base restaurée
#  sans eux rend des conversations qui citent des fichiers absents.
#  Les TRAMES, elles, sont en base (BYTEA) : le dump les porte déjà.
#
#  Un jeu de sauvegarde = un DOSSIER horodaté qui contient :
#     base.sql.gz          le dump (DROP + CREATE inclus)
#     documents.tar.gz     le volume des documents produits (visuels compris)
#     sessions.tar.gz      les sessions du navigateur (si SAUVEGARDER_SESSIONS=1)
#     secrets.tar.gz[.enc] le .env et backend/secrets — CHIFFRÉS si possible
#     manifeste.txt        commit, migrations appliquées, comptes, empreintes
#     EMPREINTES.sha256    de quoi prouver que rien n'a bougé
#
#  À lancer depuis le dossier du projet, idéalement en CRON quotidien :
#      chmod +x backup.sh && ./backup.sh
#  Réglages (variables d'environnement) :
#      BACKUP_DIR (défaut ~/duret-backups)   RETENTION_DAYS (défaut 14)
#      GARDER_AU_MOINS (défaut 3)            SAUVEGARDER_SESSIONS (défaut 0)
#      BACKUP_PASSPHRASE (chiffre les secrets ; à garder AILLEURS)
#      BACKUP_DISTANT (ex. user@hote:/chemin — copie hors de la machine)
#
#  RESTAURATION : ./restaurer.sh <dossier du jeu>  (copie ISOLÉE, jamais la prod)
# =====================================================================
set -euo pipefail
umask 077                     # les secrets ne sont lisibles que par leur propriétaire
cd "$(dirname "$0")"

BACKUP_DIR="${BACKUP_DIR:-$HOME/duret-backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
GARDER_AU_MOINS="${GARDER_AU_MOINS:-3}"
SAUVEGARDER_SESSIONS="${SAUVEGARDER_SESSIONS:-0}"
STAMP="$(date +%Y-%m-%d_%H%M)"
mkdir -p "$BACKUP_DIR"

COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
# Lit une variable du .env (1re occurrence, robuste aux doublons et commentaires).
env_get() { awk -F= -v k="$1" '$1==k{sub(/^[^=]*=/,"");sub(/[[:space:]]+#.*$/,"");sub(/[[:space:]]*$/,"");print;exit}' .env; }
PG_USER="$(env_get POSTGRES_USER)"
PG_DB="$(env_get POSTGRES_DB)"
PROJET="$(env_get COMPOSE_PROJECT_NAME)"
PROJET="${PROJET:-duret-sols}"
: "${PG_USER:?POSTGRES_USER manquant dans .env}"
: "${PG_DB:?POSTGRES_DB manquant dans .env}"

# ON ÉCRIT DANS UN DOSSIER PROVISOIRE, ON PUBLIE À LA FIN. Un jeu à moitié écrit
# ne doit jamais ressembler à un jeu utilisable : c'est ce qui fait qu'on croit
# avoir une sauvegarde le jour où l'on en a besoin.
TMP="$BACKUP_DIR/.en-cours_$STAMP"
CIBLE="$BACKUP_DIR/duret_$STAMP"
rm -rf "$TMP"
mkdir -p "$TMP"
nettoyer() { rm -rf "$TMP"; }
trap nettoyer EXIT

echo "==> 1/6  Base de données ($PG_DB)…"
$COMPOSE exec -T postgres pg_dump -U "$PG_USER" --clean --if-exists "$PG_DB" | gzip > "$TMP/base.sql.gz"
gzip -t "$TMP/base.sql.gz"

# Le suivi des migrations et quelques comptes : le manifeste doit permettre de
# dire, plus tard, CE QUE ce jeu contient — pas seulement qu'il existe.
PSQL() { $COMPOSE exec -T postgres psql -tA -U "$PG_USER" -d "$PG_DB" "$@"; }
MIGRATIONS="$(PSQL -c "SELECT string_agg(filename, ' ' ORDER BY filename) FROM schema_migrations;" || echo "(illisible)")"
COMPTES="$(PSQL -c "SELECT 'utilisateurs=' || (SELECT count(*) FROM users) || ' conversations=' || (SELECT count(*) FROM threads) || ' messages=' || (SELECT count(*) FROM messages) || ' documents=' || (SELECT count(*) FROM documents) || ' trames=' || (SELECT count(*) FROM trames);" 2>/dev/null || echo "(comptes illisibles)")"

echo "==> 2/6  Volume des documents produits (Word, Excel, visuels, atelier)…"
sauver_volume() {          # $1 = nom du volume, $2 = fichier de sortie
  if ! docker volume inspect "$1" >/dev/null 2>&1; then
    return 1
  fi
  docker run --rm -v "$1":/source:ro -v "$TMP":/sortie alpine:3.20 \
      tar czf "/sortie/$2" -C /source . 2>/dev/null
  tar tzf "$TMP/$2" >/dev/null       # l'archive s'ouvre : vérifié tout de suite
}
if ! sauver_volume "${PROJET}_documents_produits" documents.tar.gz; then
  echo "ERREUR : volume ${PROJET}_documents_produits introuvable." >&2
  echo "  Une sauvegarde sans les documents produits n'est pas restaurable telle quelle." >&2
  echo "  Vérifiez COMPOSE_PROJECT_NAME dans .env (attendu : $PROJET)." >&2
  exit 1
fi
if [ "$SAUVEGARDER_SESSIONS" = "1" ]; then
  sauver_volume "${PROJET}_browser_sessions" sessions.tar.gz \
    || echo "    (pas de volume de sessions navigateur — ignoré)"
fi

echo "==> 3/6  Secrets (.env, backend/secrets)…"
tar czf "$TMP/secrets.tar.gz" .env $( [ -d backend/secrets ] && echo backend/secrets )
if [ -n "${BACKUP_PASSPHRASE:-}" ]; then
  openssl enc -aes-256-cbc -pbkdf2 -salt -in "$TMP/secrets.tar.gz" \
      -out "$TMP/secrets.tar.gz.enc" -pass env:BACKUP_PASSPHRASE
  rm -f "$TMP/secrets.tar.gz"
  echo "    secrets chiffrés (la phrase de passe se garde AILLEURS que les sauvegardes)"
else
  echo "    ⚠ secrets NON chiffrés (posez BACKUP_PASSPHRASE) — fichiers en 600, dossier privé"
fi

echo "==> 4/6  Manifeste et empreintes…"
{
  echo "jeu                : duret_$STAMP"
  echo "date               : $(date '+%F %T %z')"
  echo "projet compose     : $PROJET"
  echo "commit du code     : $(git rev-parse HEAD 2>/dev/null || echo '(hors dépôt git)')"
  echo "branche            : $(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '-')"
  echo "migrations en base : $MIGRATIONS"
  echo "comptes            : $COMPTES"
  echo "sessions incluses  : $( [ -f "$TMP/sessions.tar.gz" ] && echo oui || echo non )"
  echo "secrets chiffrés   : $( [ -f "$TMP/secrets.tar.gz.enc" ] && echo oui || echo NON )"
} > "$TMP/manifeste.txt"
( cd "$TMP" && sha256sum ./* > EMPREINTES.sha256 )
( cd "$TMP" && sha256sum -c --quiet EMPREINTES.sha256 )

echo "==> 5/6  Publication du jeu…"
mv "$TMP" "$CIBLE"
trap - EXIT
chmod 700 "$CIBLE"
ln -sfn "$CIBLE" "$BACKUP_DIR/DERNIER"

if [ -n "${BACKUP_DISTANT:-}" ]; then
  echo "    copie hors de la machine vers $BACKUP_DISTANT…"
  rsync -a --chmod=D700,F600 "$CIBLE" "$BACKUP_DISTANT/" \
    || echo "    ⚠ copie distante ÉCHOUÉE — le jeu local, lui, est complet"
fi

# RÉTENTION : on ne supprime QU'APRÈS avoir publié un jeu complet, et l'on garde
# toujours les `GARDER_AU_MOINS` derniers, même vieux. Un dossier de sauvegarde
# vide parce que la rétention a bien fait son travail est le pire des cas.
echo "==> 6/6  Rétention ($RETENTION_DAYS jours, au moins $GARDER_AU_MOINS jeux)…"
# (`mapfile` n'existe pas en bash 3 : on reste portable.)
JEUX=""
while IFS= read -r jeu; do JEUX="$JEUX$jeu"$'\n'; done < <(find "$BACKUP_DIR" -maxdepth 1 -type d -name 'duret_*' | sort)
TOTAL="$(printf '%s' "$JEUX" | grep -c . || true)"
A_EXAMINER="$(( TOTAL > GARDER_AU_MOINS ? TOTAL - GARDER_AU_MOINS : 0 ))"
if [ "$A_EXAMINER" -gt 0 ]; then
  printf '%s' "$JEUX" | head -n "$A_EXAMINER" | while IFS= read -r jeu; do
    [ -n "$jeu" ] || continue
    if [ -n "$(find "$jeu" -maxdepth 0 -mtime +"$RETENTION_DAYS")" ]; then
      rm -rf "$jeu"
      echo "    retiré : $(basename "$jeu")"
    fi
  done
fi
# Les vieux fichiers de l'ancienne forme (db_*.sql.gz / env_*.bak) suivent la même règle.
find "$BACKUP_DIR" -maxdepth 1 -name 'db_*.sql.gz' -mtime +"$RETENTION_DAYS" -delete
find "$BACKUP_DIR" -maxdepth 1 -name 'env_*.bak' -mtime +"$RETENTION_DAYS" -delete

echo
echo "OK $(date '+%F %T') → $CIBLE ($(du -sh "$CIBLE" | cut -f1))"
echo "Restauration (copie ISOLÉE, jamais la production) :  ./restaurer.sh $CIBLE"
