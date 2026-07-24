#!/bin/bash
# Crée un snapshot Daytona avec Playwright + Chromium pré-installés.
# À exécuter UNE SEULE FOIS — réduit le démarrage sandbox de ~60s à <90ms.
#
# Usage :
#   bash scripts/setup_daytona_browser_snapshot.sh
#
# Prérequis :
#   - daytona CLI installé et authentifié
#   - jq installé
#
# Après exécution, mettre à jour DaytonaBrowserClient._run_in_sandbox() :
#   sandbox = self._daytona.create(snapshot="noa-browser-playwright")

set -euo pipefail

SNAPSHOT_NAME="noa-browser-playwright"
echo "Création du snapshot Daytona browser..."

# Créer un sandbox temporaire
SANDBOX_ID=$(daytona sandbox create --image python:3.12-slim --json | jq -r '.id')
echo "Sandbox créé : $SANDBOX_ID"

# Installer Playwright et Chromium
echo "Installation de Playwright + Chromium..."
daytona sandbox exec "$SANDBOX_ID" \
    "pip install playwright==1.44.0 -q && python -m playwright install chromium --with-deps"

# Créer le snapshot
echo "Création du snapshot..."
daytona sandbox snapshot create "$SANDBOX_ID" \
    --name "$SNAPSHOT_NAME" \
    --description "Python 3.12 + Playwright + Chromium pour Pluton browser agent"

# Supprimer le sandbox temporaire
daytona sandbox delete "$SANDBOX_ID"
echo "Sandbox temporaire supprimé."

echo ""
echo "Snapshot '$SNAPSHOT_NAME' créé avec succès."
echo ""
echo "Pour l'utiliser, mettre à jour backend/browser/daytona_browser.py :"
echo "  sandbox = self._daytona.create(snapshot=\"$SNAPSHOT_NAME\")"
