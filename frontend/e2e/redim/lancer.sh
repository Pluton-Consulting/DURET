#!/bin/bash
# Banc de la poignée de redimensionnement des blocs du chat (24/09), joué dans un
# VRAI navigateur, sans backend.
#
# Le 24/09 au matin, la poignée NATIVE (`resize: both`) était déployée et Noa n'a
# pas pu tirer un tableau : personne ne l'avait vue dans un navigateur. Ce banc
# assemble par esbuild le VRAI `BlocRedimensionnable` autour d'un VRAI `SimpleTable`
# de 40 lignes, avec les VRAIES feuilles `theme.css` et `mobile.css`, puis tire la
# poignée à la souris : le cadre grandit en largeur et en hauteur, le tableau suit,
# le double-clic remet la taille d'origine, et au téléphone la poignée n'existe pas.
#
#   bash frontend/e2e/redim/lancer.sh          (depuis la racine du dépôt)
#   CHROME=/chemin/vers/chrome bash …           (autre navigateur)
#
# Rien n'est installé dans le projet : esbuild et playwright-core viennent de npx,
# dans un dossier temporaire.
set -euo pipefail
ICI="$(cd "$(dirname "$0")" && pwd)"
FRONT="$(cd "$ICI/../.." && pwd)"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
( cd "$T" && npm init -y >/dev/null && npm i --silent esbuild playwright-core@1.57 >/dev/null )
NODE_PATH="$FRONT/node_modules" "$T/node_modules/.bin/esbuild" "$ICI/page.tsx" --bundle --outfile="$T/page.js" \
  --jsx=automatic --alias:@="$FRONT" --loader:.css=empty --log-level=warning \
  --define:process.env.NODE_ENV='"production"' --define:process.env.NEXT_PUBLIC_API_URL='""'
# Les feuilles réelles, telles quelles : c'est leur cascade qu'on juge.
{
  printf '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><style>'
  cat "$FRONT/app/theme.css" "$FRONT/app/mobile.css"
  printf '</style></head><body><div id="app"></div><script src="page.js"></script></body></html>'
} > "$T/page.html"
cp "$ICI/banc.mjs" "$T/"
cd "$T"
node banc.mjs "$T"
