"""Tickets à usage unique partagés entre processus sur le volume local.

SQLite sérialise consommation et émission ; seul le hachage du ticket est
conservé. Aucun secret de session existant n'est remplacé. Ces tickets courts
ne justifient pas une connexion SQL métier synchrone dans une route OAuth.
"""
import hashlib
import os
from pathlib import Path
import sqlite3
import time
from contextlib import contextmanager, closing

@contextmanager
def _base():
    from ressources.registre import _chemin
    chemin = _chemin().parent / "auth-ephemere.sqlite3"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    # Créer privé dès le premier octet, pas après une première écriture.
    fd = os.open(chemin, os.O_CREAT | os.O_RDWR, 0o600)
    os.close(fd)
    with closing(sqlite3.connect(chemin, timeout=5)) as conn, conn:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("CREATE TABLE IF NOT EXISTS tickets (usage TEXT NOT NULL, empreinte TEXT NOT NULL, valeur TEXT NOT NULL, expire REAL NOT NULL, PRIMARY KEY(usage,empreinte))")
        conn.execute("CREATE INDEX IF NOT EXISTS tickets_expiration ON tickets(expire)")
        yield conn

def _empreinte(ticket):
    return hashlib.sha256(str(ticket).encode()).hexdigest()

def emettre(usage, ticket, valeur, secondes):
    if not ticket or len(str(ticket)) > 512:
        raise ValueError("Ticket invalide")
    with _base() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM tickets WHERE expire <= ?", (time.time(),))
        if conn.execute("SELECT count(*) FROM tickets").fetchone()[0] >= 20000:
            raise ValueError("Trop de connexions en attente ; réessayez plus tard")
        conn.execute("INSERT INTO tickets VALUES (?,?,?,?)", (usage,_empreinte(ticket),str(valeur),time.time()+max(1,float(secondes))))

def consommer(usage, ticket):
    if not ticket or len(str(ticket)) > 512:
        return None
    with _base() as conn:
        conn.execute("BEGIN IMMEDIATE")
        ligne = conn.execute("DELETE FROM tickets WHERE usage=? AND empreinte=? RETURNING valeur, expire",(usage,_empreinte(ticket))).fetchone()
        return ligne[0] if ligne and ligne[1] > time.time() else None
