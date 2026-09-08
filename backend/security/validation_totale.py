"""
L'ACCORD HUMAIN AVANT CHAQUE ACTION — règle de Noa du 08/09.

« Sur toutes les actions — lecture du drive, modifier un document, créer un
document, rechercher sur Internet, etc. — il y a une validation humaine à
chaque fois. Vraiment à chaque fois. »

Le modèle de sécurité du projet réserve l'accord humain aux effets `externe`
(envoi, dépôt, tirage) : une lecture s'exécute tout de suite. Ce réglage
(`validation_totale`, Paramètres → Clés API, ou VALIDATION_TOTALE dans le
`.env`) PROMEUT tout effet en `externe` dans le CHAT : chaque geste passe par
la carte d'accord, lié à l'empreinte de ses arguments — ce qui est approuvé
est exactement ce qui s'exécute —, puis LE TOUR REPREND avec le résultat
(`reprise_apres_accord`) au lieu de se terminer comme après un envoi.

Les tâches planifiées ne sont PAS promues : une tâche de 7 h 30 bloquée sur
« approuver la lecture des mails » ne servirait à personne ; leurs effets
externes, eux, attendent toujours l'accord (tableau de bord → À valider).

Le DÉFAUT est propre à chaque client (`config.py`) : « active » chez Duret
(la demande), « desactivee » chez Symbiose (Noa : « laisser l'accord humain
comme avant »). Un clic dans Paramètres change de régime.
"""
from __future__ import annotations

from config import settings

DECLENCHEURS_PROMUS = ("chat", "resume", "ws", "post")


def active() -> bool:
    """Le réglage vaut « active » ? Base d'abord (Paramètres), `.env` sinon."""
    try:
        from llm.reglages import valeur
        brut = valeur("validation_totale")
    except Exception:  # noqa: BLE001 — jamais une panne
        brut = getattr(settings, "validation_totale", None)
    if brut is None:
        brut = getattr(settings, "validation_totale", "desactivee")
    # Sans réglage lisible : l'ancien régime. Le défaut de chaque client vit
    # dans SON config.py (Duret : active ; Symbiose : desactivee).
    return str(brut or "").strip().lower() == "active"


def effet_effectif(effet_declare: str, trigger_kind: str | None) -> str:
    """L'effet qui décide de l'accord : promu en `externe` dans le chat quand
    le réglage est actif ; inchangé pour une tâche planifiée ou un webhook."""
    if effet_declare == "externe":
        return "externe"
    if (trigger_kind or "chat") not in DECLENCHEURS_PROMUS:
        return effet_declare
    return "externe" if active() else effet_declare


def raison_d_accord(skill: str, effet_declare: str) -> str:
    """Ce que la carte d'accord dit de l'action."""
    if effet_declare == "externe":
        return f"Action à effet externe : {skill}"
    return f"Accord demandé avant chaque action : {skill}"


def consigne() -> str:
    """Ce que le modèle doit savoir quand chaque action attend un accord."""
    if not active():
        return ""
    return ("\n\nCHAQUE ACTION ATTEND L'ACCORD DE LA PERSONNE avant de s'exécuter (réglage "
            "de l'entreprise). Émets UNE action à la fois, précédée d'une phrase courte qui "
            "dit ce que tu vas faire et pourquoi : c'est ce que la personne lit sur la carte "
            "d'accord. Après l'accord, tu reçois le résultat et tu continues — ne redemande "
            "jamais l'accord d'une action déjà approuvée, ne t'excuse pas de demander.")
