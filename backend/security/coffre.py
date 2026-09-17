"""
LE COFFRE — chiffrer au repos ce qui ouvre une porte ailleurs (16/09, audit D-19).

CE QUI ÉTAIT FAUX. Le jeton de rafraîchissement d'un compte Google était écrit
EN CLAIR dans `connexions_google.refresh_token`. Ce n'est pas un mot de passe
qu'on peut changer en cinq minutes : c'est une clé permanente qui ouvre le
Drive et la boîte de la personne, valable tant qu'elle ne la révoque pas. Une
sauvegarde égarée, un accès en lecture à la base, un dump partagé pour
diagnostic, et la clé part avec.

CE QUE FAIT CE MODULE. Un secret est chiffré avant d'être écrit, déchiffré à la
lecture, et la clé est **séparée de celle des sessions** (`JETONS_CHIFFREMENT_CLE`
et non `JWT_SECRET_KEY`) : les deux n'ont ni le même usage ni la même vie —
changer le secret des sessions ne doit pas rendre illisibles tous les comptes
reliés, et une fuite de l'un ne doit pas donner l'autre.

TROIS PRÉCAUTIONS, apprises ailleurs :
  * **L'USAGE fait partie de la clé.** Un secret chiffré pour les jetons Google
    ne se déchiffre pas avec la clé d'un autre usage : un coffre unique
    transformerait n'importe quelle lecture en lecture de tout.
  * **LECTURE TRANSITOIRE DU CLAIR.** Les lignes écrites avant ce correctif ne
    sont pas chiffrées. Les refuser couperait tous les comptes reliés le jour
    du déploiement : on les lit telles quelles, et `a_rechiffrer` dit à
    l'appelant de les réécrire — la migration se fait toute seule, à l'usage.
  * **SANS BIBLIOTHÈQUE NI CLÉ, ON NE MENT PAS.** Si `cryptography` manque ou
    qu'aucun secret n'est posé, `chiffrer` refuse l'écriture. Les anciennes
    valeurs en clair restent lisibles pour permettre leur migration.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Optional

logger = logging.getLogger("duret.security.coffre")

# Ce qui marque une valeur passée par le coffre. Fernet produit du base64url
# commençant par « gAAAAA » ; on préfixe quand même, pour que la lecture soit
# une DÉCISION et non une devinette sur la forme du texte.
MARQUE = "coffre1:"


def _cles(usage: str) -> list:
    """La clé d'écriture d'abord, les anciennes ensuite (lecture seulement)."""
    cles = []
    try:
        import base64

        from cryptography.fernet import Fernet

        from config import settings
        propre = str(getattr(settings, "jetons_chiffrement_cle", "") or "").strip()
        if propre:
            graine = hashlib.sha256(f"pluton:{usage}:".encode() + propre.encode()).digest()
            cles.append(Fernet(base64.urlsafe_b64encode(graine)))
        # Repli : dérivation depuis le secret des sessions. Elle permet de
        # chiffrer AVANT que l'exploitant ait posé une clé dédiée — et elle
        # reste lisible ensuite, le temps que la rotation passe.
        secret = str(getattr(settings, "jwt_secret_key", "") or "")
        if secret:
            graine = hashlib.sha256(f"pluton:{usage}:".encode() + secret.encode()).digest()
            cles.append(Fernet(base64.urlsafe_b64encode(graine)))
    except Exception as e:  # noqa: BLE001 — bibliothèque absente : pas de coffre
        logger.debug("Coffre indisponible (%s) : écriture des secrets suspendue", e)
        return []
    return cles


def disponible() -> bool:
    """Le coffre peut-il chiffrer ? (bibliothèque présente ET secret posé)"""
    return bool(_cles("controle"))


def chiffre(valeur: Optional[str]) -> bool:
    """Cette valeur est-elle déjà passée par le coffre ?"""
    return bool(valeur) and str(valeur).startswith(MARQUE)


def chiffrer(secret: Optional[str], usage: str) -> Optional[str]:
    """Le secret chiffré pour cet usage ; refuse une écriture sans coffre."""
    if not secret:
        return secret
    if chiffre(secret):
        return secret
    cles = _cles(usage)
    if not cles:
        raise RuntimeError("Coffre indisponible : le secret n'a pas été enregistré en clair.")
    return MARQUE + cles[0].encrypt(str(secret).encode()).decode()


def dechiffrer(valeur: Optional[str], usage: str) -> Optional[str]:
    """Le secret en clair. Une valeur NON marquée est rendue telle quelle : ce
    sont les enregistrements d'avant le coffre, et les couper serait pire que
    le défaut qu'on corrige."""
    if not valeur:
        return valeur
    if not chiffre(valeur):
        return valeur
    charge = str(valeur)[len(MARQUE):].encode()
    for f in _cles(usage):
        try:
            return f.decrypt(charge).decode()
        except Exception:  # noqa: BLE001 — pas cette clé-là
            continue
    # Clé perdue ou changée : on le DIT plutôt que de rendre une chaîne
    # inutilisable qui provoquerait une erreur incompréhensible plus loin.
    logger.warning("Secret %s illisible : la clé de chiffrement a changé", usage)
    return None


def a_rechiffrer(valeur: Optional[str], usage: str = "google") -> bool:
    """Migrer le clair et les valeurs encore chiffrées avec l'ancienne clé."""
    if not valeur:
        return False
    cles = _cles(usage)
    if not cles:
        return False
    if not chiffre(valeur):
        return True
    try:
        cles[0].decrypt(str(valeur)[len(MARQUE):].encode())
        return False
    except Exception:
        return dechiffrer(valeur, usage) is not None
