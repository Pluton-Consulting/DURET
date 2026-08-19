#!/usr/bin/env bash
# ============================================================
#  INTERFACE V2 — déployer la refonte, et SAVOIR REVENIR EN DIX SECONDES.
# ============================================================
#
# La refonte de l'interface (tableau de bord, chat, connaissances) vit sur la
# branche `interface-v2`. Elle se déploie comme le reste, mais avec une
# précaution qui change tout : AVANT de reconstruire, les images qui tournent
# sont étiquetées `v1`. Revenir en arrière ne rebuild rien : on remet
# l'étiquette `latest` sur les images `v1` et on relance les conteneurs —
# dix secondes, pas dix minutes. La base n'est pas touchée dans un sens ni
# dans l'autre : la refonte n'a aucune migration qui lui soit propre.
#
#   ./scripts/interface-v2.sh sauvegarder   # étiquette les images actuelles en v1 (à faire UNE fois, avant)
#   ./scripts/interface-v2.sh deployer      # bascule sur interface-v2, reconstruit frontend + backend
#   ./scripts/interface-v2.sh revenir       # remet v1 en dix secondes, sans rebuild
#   ./scripts/interface-v2.sh etat          # quelle version tourne
#
# Le code revient lui aussi sur la branche précédente (`master`) au retour, pour
# que le prochain `git pull` ne réapplique pas la refonte par surprise.
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
[ -f docker-compose.https.yml ] && COMPOSE="$COMPOSE -f docker-compose.https.yml"
PROJET="$(basename "$(pwd)")"           # préfixe des images : <projet>-frontend, <projet>-backend
BRANCHE_V2="interface-v2"
BRANCHE_V1="$(git rev-parse --abbrev-ref HEAD)"
[ "$BRANCHE_V1" = "$BRANCHE_V2" ] && BRANCHE_V1="main"

# L'image d'un service EN COURS : lue sur le conteneur, pas devinée.
image_de() {
  local cid; cid="$($COMPOSE ps -q "$1" 2>/dev/null | head -1)"
  [ -n "$cid" ] && docker inspect -f '{{.Config.Image}}' "$cid" 2>/dev/null || true
}

case "${1:-}" in
  sauvegarder)
    for s in frontend backend; do
      img="$(image_de "$s")"
      if [ -z "$img" ]; then echo "⚠ aucune image en cours pour $s" >&2; continue; fi
      docker tag "$img" "${PROJET}-${s}:v1"
      echo "✓ $img → ${PROJET}-${s}:v1"
    done
    git rev-parse HEAD > .interface-v1.commit
    echo "✓ commit v1 noté : $(cat .interface-v1.commit)"
    ;;
  deployer)
    if ! docker image inspect "${PROJET}-frontend:v1" >/dev/null 2>&1; then
      echo "✗ Lance d'abord : $0 sauvegarder (sinon pas de retour possible en dix secondes)" >&2; exit 1
    fi
    git fetch --all --quiet
    git checkout "$BRANCHE_V2"
    git pull --ff-only
    $COMPOSE up -d --build frontend backend
    echo "✓ interface-v2 déployée. Retour : $0 revenir"
    ;;
  revenir)
    for s in frontend backend; do
      docker image inspect "${PROJET}-${s}:v1" >/dev/null 2>&1 || { echo "✗ image ${PROJET}-${s}:v1 absente" >&2; exit 1; }
      docker tag "${PROJET}-${s}:v1" "${PROJET}-${s}:latest"
    done
    $COMPOSE up -d --no-build frontend backend
    if [ -f .interface-v1.commit ]; then git checkout --quiet "$(cat .interface-v1.commit)" 2>/dev/null || true; fi
    git checkout --quiet "$BRANCHE_V1" 2>/dev/null || true
    echo "✓ version précédente rétablie (images v1, sans rebuild)."
    ;;
  etat)
    echo "branche : $(git rev-parse --abbrev-ref HEAD) @ $(git rev-parse --short HEAD)"
    for s in frontend backend; do echo "$s : $(image_de "$s")"; done
    docker image inspect "${PROJET}-frontend:v1" >/dev/null 2>&1 && echo "sauvegarde v1 : présente" || echo "sauvegarde v1 : ABSENTE"
    ;;
  *)
    sed -n '2,22p' "$0"; exit 1 ;;
esac
