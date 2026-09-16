"""
RETROUVER LA MÊME SOURCE APRÈS UN REDÉMARRAGE (16/09, audit D-07/S-07).

CE QUI ÉTAIT FAUX. Un message de la messagerie et une pièce jointe ne sont
désignés au modèle que par une `ref` courte (16 hexadécimaux) — l'identifiant
du fournisseur, lui, fait 150 caractères opaques. Cette table de correspondance
vivait UNIQUEMENT dans la mémoire du processus. Après un redémarrage :

  · un brouillon en attente d'accord qui citait une pièce jointe ne la
    retrouvait plus (« pièce inconnue ») ;
  · « ouvre la pièce jointe dont on parlait » repartait chercher un message au
    hasard par son objet ;
  · une validation en attente depuis la veille ne pouvait plus s'exécuter.

CE QUE FAIT CE MODULE. Il retient les références utiles dans un fichier du
VOLUME des documents — le même qui garde les Word rendus et les visuels, donc
celui qui survit aux redéploiements. Le cache mémoire reste devant : il n'est
plus le seul support.

POURQUOI PAS UNE TABLE POSTGRES TOUT DE SUITE. Les fonctions qui mémorisent une
référence sont SYNCHRONES, appelées au milieu de la lecture d'un mail ; les
passer en base demanderait de rendre asynchrone toute cette chaîne pour un
gain nul à ce stade. Le registre en base (`resource_refs` de l'audit) reste la
cible quand documents, visuels et mails le partageront ; l'API ci-dessous ne
changera pas ce jour-là — seul son entrepôt changera.

RÈGLES. On garde ce qui sert à rouvrir, jamais le contenu : pas d'octets, pas
de corps de message. Le fichier est écrit ATOMIQUEMENT (temporaire + renommage)
et borné : au-delà de `MAX_PAR_TYPE`, les plus anciennes références partent.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import threading
import time
from typing import Optional

logger = logging.getLogger("duret.ressources.registre")

FICHIER = "ressources.json"
MAX_PAR_TYPE = 4000
# Ce qu'on refuse d'écrire : le contenu n'a rien à faire dans un registre de
# références (il vit dans la boîte mail, sur le NAS, ou dans l'atelier).
CLES_INTERDITES = frozenset({"octets", "octets_b64", "contenu", "corps", "texte", "body"})

_MEMOIRE: dict = {}
_CHARGE = False
_VERROU = threading.RLock()


def _chemin() -> pathlib.Path:
    return pathlib.Path(os.environ.get("DOCUMENTS_DIR", "/tmp/duret-documents")) / FICHIER


def _charger() -> dict:
    global _CHARGE
    if _CHARGE:
        return _MEMOIRE
    with _VERROU:
        if not _CHARGE:
            try:
                brut = json.loads(_chemin().read_text(encoding="utf-8"))
                if isinstance(brut, dict):
                    _MEMOIRE.update({k: v for k, v in brut.items() if isinstance(v, dict)})
            except (OSError, ValueError):
                pass
            _CHARGE = True
    return _MEMOIRE


def _ecrire() -> None:
    chemin = _chemin()
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        temporaire = chemin.with_name(f"{chemin.name}.{os.getpid()}.tmp")
        temporaire.write_text(json.dumps(_MEMOIRE, ensure_ascii=False), encoding="utf-8")
        os.replace(temporaire, chemin)
    except OSError as e:  # noqa: BLE001 — un registre d'appoint ne casse pas une lecture de mail
        logger.warning("Registre des ressources non écrit : %s", e)


def noter(type_: str, ref: str, donnees: dict) -> None:
    """Retient de quoi rouvrir cette source. Best-effort, ne lève jamais."""
    ref = (ref or "").strip()
    if not ref or not type_:
        return
    propre = {k: v for k, v in (donnees or {}).items()
              if k not in CLES_INTERDITES and isinstance(v, (str, int, float, bool, type(None)))}
    propre["vu_le"] = time.time()
    with _VERROU:
        table = _charger().setdefault(type_, {})
        if ref in table and table[ref] == {**propre, "vu_le": table[ref].get("vu_le")}:
            return                          # rien de neuf : on n'écrit pas pour rien
        table[ref] = propre
        if len(table) > MAX_PAR_TYPE:
            anciens = sorted(table.items(), key=lambda kv: kv[1].get("vu_le") or 0)
            for cle, _ in anciens[: len(table) - MAX_PAR_TYPE]:
                table.pop(cle, None)
        _ecrire()


def lire(type_: str, ref: str) -> Optional[dict]:
    """Ce qu'on sait de cette référence, ou None."""
    return (_charger().get(type_) or {}).get((ref or "").strip())


def oublier(type_: str, ref: str) -> None:
    with _VERROU:
        if (_charger().get(type_) or {}).pop((ref or "").strip(), None) is not None:
            _ecrire()


def combien(type_: str) -> int:
    return len(_charger().get(type_) or {})


def recharger() -> None:
    """Relit le fichier (utile après un redémarrage simulé, et pour les bancs)."""
    global _CHARGE
    with _VERROU:
        _MEMOIRE.clear()
        _CHARGE = False
        _charger()
