"""
LE TEMPS D'UNE DEMANDE SE COMPTE UNE FOIS (16/09, audit D-16/S-16).

CE QUI ÉTAIT FAUX. Chaque étage avait son délai : le routeur, chaque candidat de
la cascade, les tentatives, les outils, le relecteur. Personne ne regardait
l'heure de la DEMANDE — d'où des tours de trois minutes composés de délais qui,
pris un par un, semblaient tous raisonnables.

CE QUE FAIT CE MODULE. Un objet `Budget`, créé au début du tour, qui dit combien
de temps il reste. Chaque étape lui demande son délai au lieu de fixer le sien :
un appel de modèle ne peut pas durer plus que ce qui reste, et la dernière étape
sait qu'elle n'a plus que deux secondes — donc qu'il vaut mieux répondre avec ce
qu'on a que commencer autre chose.

HORLOGE MONOTONE, JAMAIS L'HEURE DU MUR : l'heure système peut sauter (NTP,
veille), et une soustraction de dates devient alors négative ou énorme.

RIEN N'EST GLOBAL : le budget voyage avec la demande. Une variable de module
partagée entre deux tours concurrents dirait à l'un le temps de l'autre.
"""
from __future__ import annotations

import time
from typing import Optional


class Budget:
    """Ce qu'il reste de temps pour CETTE demande."""

    def __init__(self, secondes: float, debut: Optional[float] = None):
        self.total = max(1.0, float(secondes))
        self.debut = debut if debut is not None else time.monotonic()

    def ecoule(self) -> float:
        return max(0.0, time.monotonic() - self.debut)

    def restant(self) -> float:
        return max(0.0, self.total - self.ecoule())

    def expire(self) -> bool:
        return self.restant() <= 0

    def delai(self, souhaite: float, plancher: float = 1.0) -> float:
        """Le délai à donner à une étape : ce qu'elle voudrait, borné par ce
        qu'il reste. Jamais moins que `plancher` — un délai de zéro ferait
        échouer l'appel avant même de partir, ce qui n'aide personne."""
        return max(plancher, min(float(souhaite), self.restant()))

    def assez_pour(self, secondes: float) -> bool:
        """Reste-t-il de quoi tenter une étape de cette durée ?"""
        return self.restant() >= max(0.0, float(secondes))

    def __repr__(self) -> str:  # pragma: no cover — confort de journal
        return f"<Budget {self.restant():.0f}s restantes sur {self.total:.0f}>"


# ── CLASSER LES PANNES (audit D-16/S-16, point 2) ───────────────────────────────
# Toutes les erreurs d'un fournisseur ne se valent pas, et les traiter pareil
# fait perdre du temps à chaque tour : une clé invalide ne deviendra pas valide
# en trois secondes, alors qu'un 429 passe. Trois familles, trois conduites.
CONFIGURATION = "configuration"   # clé refusée, modèle inconnu : ne pas retenter
QUOTA = "quota"                   # 429 : attendre le délai dit, puis réessayer
RESEAU = "reseau"                 # coupure, délai dépassé : quelques essais
INCONNUE = "inconnue"


def classer(erreur: BaseException) -> str:
    """La famille d'une panne de fournisseur, d'après ce qu'il a répondu."""
    texte = f"{type(erreur).__name__}: {erreur}".lower()
    if any(m in texte for m in ("401", "403", "invalid api key", "invalid auth",
                                "unauthorized", "user not found", "api key not valid")):
        return CONFIGURATION
    if any(m in texte for m in ("404", "model not found", "does not exist",
                                "unknown model", "no such model", "decommissioned")):
        return CONFIGURATION
    if any(m in texte for m in ("429", "quota", "rate limit", "too many requests",
                                "resource exhausted")):
        return QUOTA
    if any(m in texte for m in ("timeout", "timed out", "connection", "connexion",
                                "502", "503", "504", "reset by peer", "temporarily")):
        return RESEAU
    return INCONNUE


def a_retenter(famille: str) -> bool:
    """Retenter tout de suite a-t-il une chance d'aboutir ?"""
    return famille in (RESEAU, QUOTA)
