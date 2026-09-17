#!/usr/bin/env python3
"""Un seul jeu cohérent par projet sur cet hôte, même depuis deux versions."""
import fcntl
import hashlib
import os
import sys
import tempfile

projet, script, *arguments = sys.argv[1:]
chemin = os.path.join(tempfile.gettempdir(), "infra-ia-backup-" + hashlib.sha256(projet.encode()).hexdigest() + ".lock")
fd = os.open(chemin, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    sys.exit("Une sauvegarde de ce projet est déjà en cours ; aucun service modifié.")
os.set_inheritable(fd, True)
os.environ["INFRA_BACKUP_VERROU"] = projet
os.execvp("bash", ["bash", script, *arguments])
