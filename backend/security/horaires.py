"""
La plage horaire d'accès, lue à l'HEURE LOCALE de l'entreprise.

RELEVÉ DE NOA DU 08/09 (Symbiose) : « une employée a essayé de se connecter
dans les heures bloquées, ça n'a pas marché ; là elle essaie dans les bonnes
heures, c'est toujours bloqué ». Cause : `routers/chat.py` et le nœud
`check_schedule` comparaient la plage (8 h–18 h) à `datetime.now()` — l'heure
du CONTENEUR, en UTC, aucun fuseau n'étant posé dans Docker. À 8 h 12 à Paris,
le serveur lisait 6 h 12 et refusait ; et le message disait « Accès refusé à
6h12 » à quelqu'un dont la pendule marquait 8 h 12. Le blocage durait jusqu'à
10 h du matin, et l'accès restait ouvert jusqu'à 20 h le soir.

Ce module est le SEUL endroit qui décide si l'on est dans la plage : les deux
gardes l'appellent. Le fuseau est un réglage (`fuseau_horaire`, défaut
Europe/Paris) ; un nom de fuseau inconnu retombe sur Paris plutôt que sur
UTC — une faute de frappe dans le `.env` ne doit pas rebloquer tout le monde.
"""
from __future__ import annotations

from datetime import datetime, timezone

FUSEAU_PAR_DEFAUT = "Europe/Paris"


def fuseau():
    """Le fuseau de l'entreprise, jamais UTC par accident."""
    from zoneinfo import ZoneInfo
    try:
        from config import settings
        nom = (getattr(settings, "fuseau_horaire", None) or "").strip() or FUSEAU_PAR_DEFAUT
    except Exception:  # noqa: BLE001 — config absente (banc, script) : Paris
        nom = FUSEAU_PAR_DEFAUT
    try:
        return ZoneInfo(nom)
    except Exception:  # noqa: BLE001 — nom inconnu : Paris, pas UTC
        return ZoneInfo(FUSEAU_PAR_DEFAUT)


def maintenant(instant: datetime | None = None) -> datetime:
    """L'instant donné (ou maintenant), exprimé dans le fuseau de l'entreprise.
    Un instant naïf est pris pour de l'UTC : c'est ce que rend `datetime.now()`
    dans un conteneur sans fuseau."""
    i = instant or datetime.now(timezone.utc)
    if i.tzinfo is None:
        i = i.replace(tzinfo=timezone.utc)
    return i.astimezone(fuseau())


def dans_la_plage(debut: int, fin: int, instant: datetime | None = None) -> tuple[bool, datetime]:
    """(dans la plage ?, l'heure locale qui a servi à décider)."""
    local = maintenant(instant)
    return (int(debut) <= local.hour < int(fin)), local


def message_refus(local: datetime, debut: int, fin: int) -> str:
    """Le refus dit l'heure LOCALE et la plage — la phrase que l'écran reconnaît."""
    return (f"Accès refusé à {local.hour}h{local.minute:02d} (heure locale). "
            f"Plage autorisée : {int(debut)}h00–{int(fin)}h00.")
