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
celui qui survit aux redéploiements. Chaque opération relit le fichier sous
verrou pour voir aussi les références créées par les autres processus.

POURQUOI PAS UNE TABLE POSTGRES TOUT DE SUITE. Les fonctions qui mémorisent une
référence sont SYNCHRONES, appelées au milieu de la lecture d'un mail ; les
passer en base demanderait de rendre asynchrone toute cette chaîne pour un
gain nul à ce stade. Le registre en base (`resource_refs` de l'audit) reste la
cible quand documents, visuels et mails le partageront ; l'API ci-dessous ne
changera pas ce jour-là — seul son entrepôt changera.

RÈGLES. On garde ce qui sert à rouvrir, jamais le contenu : pas d'octets, pas
de corps de message. Le fichier est écrit ATOMIQUEMENT (temporaire + renommage)
sous verrou interprocessus. Les références restent jusqu’à suppression explicite.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import threading
from contextlib import contextmanager
from stockage.verrous import verrou_fichier
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
_EMPREINTE_FICHIER = None
_VERROU = threading.RLock()


def _chemin() -> pathlib.Path:
    return pathlib.Path(os.environ.get("DOCUMENTS_DIR", "/tmp/duret-documents")) / FICHIER


@contextmanager
def _transaction():
    # Relire sous le même verrou que l'écriture évite les mises à jour perdues
    # et rend visibles les références créées par un autre worker.
    with _VERROU, verrou_fichier(_chemin().parent, FICHIER):
        yield


def _charger() -> dict:
    global _CHARGE, _EMPREINTE_FICHIER
    try:
        stat = _chemin().stat()
        empreinte = (stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        if _CHARGE and empreinte == _EMPREINTE_FICHIER:
            return _MEMOIRE
        brut = json.loads(_chemin().read_text(encoding="utf-8"))
        if not isinstance(brut, dict):
            raise ValueError("registre invalide")
        _MEMOIRE.clear()
        _MEMOIRE.update({k: v for k, v in brut.items() if isinstance(v, dict)})
        _EMPREINTE_FICHIER = empreinte
    except FileNotFoundError:
        _MEMOIRE.clear()
        _EMPREINTE_FICHIER = None
    # Un registre corrompu n'est pas écrasé par une table vide.
    _CHARGE = True
    return _MEMOIRE


def _ecrire() -> None:
    global _EMPREINTE_FICHIER
    _EMPREINTE_FICHIER = None  # Une écriture ratée impose de relire les octets réellement conservés.
    chemin = _chemin()
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        temporaire = chemin.with_name(f"{chemin.name}.{os.getpid()}.tmp")
        fd=os.open(temporaire,os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as fichier:
            json.dump(_MEMOIRE,fichier,ensure_ascii=False);fichier.flush();os.fsync(fichier.fileno())
        os.replace(temporaire, chemin)
        fd=os.open(chemin.parent,os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)
    except OSError as e:
        logger.error("Registre des ressources non écrit : %s", e)
        raise OSError("Impossible de conserver la référence : stockage indisponible.") from e


def noter(type_: str, ref: str, donnees: dict) -> None:
    """Retient de quoi rouvrir cette source, sans éviction des références actives."""
    ref = (ref or "").strip()
    if not ref or not type_:
        return
    propre = {k: v for k, v in (donnees or {}).items()
              if k not in CLES_INTERDITES and isinstance(v, (str, int, float, bool, type(None)))}
    propre["vu_le"] = time.time()
    with _transaction():
        table = _charger().setdefault(type_, {})
        if ref in table and table[ref] == {**propre, "vu_le": table[ref].get("vu_le")}:
            return                          # rien de neuf : on n'écrit pas pour rien
        table[ref] = propre
        # Une référence peut encore appartenir à un brouillon approuvé :
        # ne pas l'évincer à cause du nombre de lectures d'autres messages.
        _ecrire()


def lire(type_: str, ref: str) -> Optional[dict]:
    """Ce qu'on sait de cette référence, ou None."""
    with _transaction():
        valeur = (_charger().get(type_) or {}).get((ref or "").strip())
        return dict(valeur) if isinstance(valeur, dict) else None


def oublier(type_: str, ref: str) -> None:
    with _transaction():
        if (_charger().get(type_) or {}).pop((ref or "").strip(), None) is not None:
            _ecrire()


def combien(type_: str) -> int:
    with _transaction():
        return len(_charger().get(type_) or {})


def recharger() -> None:
    """Relit le fichier (utile après un redémarrage simulé, et pour les bancs)."""
    global _CHARGE
    with _transaction():
        _MEMOIRE.clear()
        _CHARGE = False
        _charger()
