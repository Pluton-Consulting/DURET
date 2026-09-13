"""
QUI LIT — le rôle de la personne pour qui un geste s'exécute.

POURQUOI UN CONTEXTE ET PAS UN PARAMÈTRE (13/09, Duret). Le niveau d'accès se
règle désormais PAR DOSSIER du serveur de fichiers : « Compta » pour la
direction seule, « Appels d'offres » pour le bureau d'études et au-dessus. Or
un chemin du NAS traverse une vingtaine de fonctions avant d'être lu (listage,
recherche, résolution d'un nom, pièce jointe d'un mail, image d'un Word,
inventaire…) et aucune ne connaît la personne. Passer `user` à chacune aurait
laissé la première oubliée ouvrir ce qu'on voulait cacher.

Le rôle est donc posé UNE fois, au goulot par lequel passent tous les skills
natifs (`skills/executor.execute_skill`), et relu là où le chemin se vérifie
(`nas.acces.verifier`). `asyncio.gather` et `to_thread` copient le contexte :
les listages menés de front voient le même lecteur.

SANS LECTEUR = LE SYSTÈME. La synchronisation, le catalogue de fond et les
campagnes d'enrichissement doivent TOUT voir pour tout ranger — chacun à son
niveau. Ils ne passent pas par l'exécuteur de skills, donc n'ont pas de
lecteur. Tout geste lancé depuis le chat, lui, en a un.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional

_ROLE: ContextVar[Optional[str]] = ContextVar("role_lecteur", default=None)


def role_lecteur() -> Optional[str]:
    """Le rôle de la personne pour qui l'on lit, ou None (le système)."""
    return _ROLE.get()


@contextmanager
def en_systeme():
    """Le temps d'un traitement commun (catalogue, carte), AUCUN lecteur.

    Une tâche lancée depuis un geste hérite du contexte de ce geste : le
    catalogue du NAS, reconstruit à la demande d'un profil « terrain », serait
    sinon filtré à SES droits — puis servi à tout le monde, synchronisation
    comprise. Ce qui est partagé se construit toujours avec la vue entière.
    """
    jeton = _ROLE.set(None)
    try:
        yield
    finally:
        _ROLE.reset(jeton)


@contextmanager
def au_nom_de(user):
    """Le temps d'un geste, les lectures se font avec les droits de `user`.

    Un utilisateur sans rôle lisible obtient une chaîne vide, pas None : il
    reste une PERSONNE (niveau le plus bas), jamais le système qui voit tout.
    """
    jeton = _ROLE.set(str(getattr(user, "role", "") or ""))
    try:
        yield
    finally:
        _ROLE.reset(jeton)
