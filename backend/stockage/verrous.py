"""Verrou réentrant entre threads/processus, avec essai non bloquant pour la purge."""
from contextlib import contextmanager
import fcntl
import hashlib
from pathlib import Path
import threading
import weakref

_garde = threading.Lock()
_verrous = weakref.WeakValueDictionary()
_local = threading.local()

@contextmanager
def verrou_fichier(dossier, cle, bloquant=True):
    base = Path(dossier) / ".verrous"
    base.mkdir(parents=True, exist_ok=True)
    chemin = str((base / (hashlib.sha256(str(cle).encode()).hexdigest() + ".lock")).resolve())
    with _garde:
        verrou = _verrous.setdefault(chemin, threading.RLock())
    if not verrou.acquire(blocking=bloquant):
        yield False
        return
    try:
        actifs = getattr(_local, "actifs", None)
        if actifs is None:
            actifs = _local.actifs = set()
        if chemin in actifs:
            # La purge ne doit pas supprimer le parent de sa propre révision.
            yield bool(bloquant)
            return
        with open(chemin, "a+b") as fichier:
            try:
                fcntl.flock(fichier, fcntl.LOCK_EX | (0 if bloquant else fcntl.LOCK_NB))
            except BlockingIOError:
                yield False
                return
            actifs.add(chemin)
            try:
                yield True
            finally:
                actifs.remove(chemin)
                fcntl.flock(fichier, fcntl.LOCK_UN)
    finally:
        verrou.release()
