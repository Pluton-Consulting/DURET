#!/usr/bin/env sh
# ---------------------------------------------------------------------------
# Compteur de derive entre les deux depots jumeaux.
#
#   ./scripts/derive.sh --autre /chemin/vers/l-autre-depot
#   ./scripts/derive.sh --autre ... --detail     # montre ce qui differe vraiment
#   ./scripts/derive.sh --autre ... --json       # sortie machine
#
# Le chemin du jumeau peut aussi venir de la variable DERIVE_AUTRE, ou du
# fichier scripts/derive.jumeau.local (une ligne, le chemin ; propre a la
# machine, a ne pas versionner - a ajouter au .gitignore).
#
# Code de sortie : 0 si toute divergence est declaree, 1 sinon, 2 si le
# compteur n'a pas pu tourner. Ce 1 est fait pour etre branche un jour en
# verification automatique.
#
# Ce script ne fait qu'appeler derive.py, qui porte toute la mesure. Deux
# implementations paralleles (sh et PowerShell) finiraient par rendre deux
# chiffres differents, et un compteur qui varie ne mesure rien.
# ---------------------------------------------------------------------------

DOSSIER=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 2

trouver_python() {
    for candidat in "$DERIVE_PYTHON" python3 python py; do
        [ -n "$candidat" ] || continue
        command -v "$candidat" >/dev/null 2>&1 || continue
        # Le moteur demande 3.9 : bornes d'expression reguliere en Unicode et
        # annotations differees.
        if "$candidat" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
            >/dev/null 2>&1; then
            printf '%s\n' "$candidat"
            return 0
        fi
    done
    return 1
}

PYTHON=$(DERIVE_PYTHON="${DERIVE_PYTHON:-}" trouver_python)
if [ -z "$PYTHON" ]; then
    echo "Python 3.9 ou plus recent est introuvable." >&2
    echo "Indiquez-le par la variable DERIVE_PYTHON, par exemple :" >&2
    echo "  DERIVE_PYTHON=/c/Python314/python ./scripts/derive.sh --autre ..." >&2
    exit 2
fi

exec "$PYTHON" "$DOSSIER/derive.py" "$@"
