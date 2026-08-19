"""
LES APERÇUS DE PAGES WEB, gardés le temps d'une conversation.

Le conteneur navigateur rend une capture (JPEG) de chaque page qu'il lit. Elle
ne doit PAS voyager vers le modèle (des kilooctets de base64 dans un résultat
d'outil, c'est du jeton brûlé pour rien) ; elle doit atteindre l'ÉCRAN, qui
la montre dans un composant `site` avec le titre et le lien.

Un dépôt en mémoire, borné, suffit : une capture vit le temps qu'on la
regarde. Cent entrées, les plus anciennes poussées dehors ; rien sur disque,
rien en base. Au redémarrage, les aperçus des anciennes conversations
disparaissent — le lien, lui, reste.
"""
from __future__ import annotations

import base64
import hashlib
import time
from collections import OrderedDict

_DEPOT: "OrderedDict[str, tuple[bytes, float]]" = OrderedDict()
_MAX = 100


def deposer(url: str, png_b64: str) -> str:
    """Range une capture et rend sa clé (stable pour une même adresse)."""
    cle = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    try:
        octets = base64.b64decode(png_b64)
    except Exception:  # noqa: BLE001 - une image illisible n'est pas un aperçu
        return ""
    _DEPOT[cle] = (octets, time.time())
    _DEPOT.move_to_end(cle)
    while len(_DEPOT) > _MAX:
        _DEPOT.popitem(last=False)
    return cle


def lire(cle: str) -> bytes | None:
    entree = _DEPOT.get(cle)
    return entree[0] if entree else None
