"""
Calcul des échéances de tâches planifiées.

Récurrence en champs STRUCTURÉS (`interval` / `daily` / `weekly`) plutôt qu'en
expression cron : trois formes couvrent le besoin métier, elles sont lisibles
dans une interface, validables, et n'ajoutent aucune dépendance.

Le calcul se fait en heure de PARIS, explicitement. Une planification « tous les
jours à 7h30 » désigne 7h30 pour l'équipe, pas 7h30 UTC : sans fuseau explicite,
l'heure glisserait de soixante minutes deux fois par an.
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger("duret.tasks.scheduler")


def _fuseau_paris():
    """Fuseau de Paris, avec repli.

    `zoneinfo` a besoin d'une base de fuseaux : les images Python « slim » n'en
    embarquent pas toujours, d'où la dépendance `tzdata` dans requirements.txt.
    Si elle manque malgré tout, on retombe sur UTC plutôt que de faire échouer
    l'import du module — ce qui emporterait le worker de tâches entier. Les
    heures planifiées seront alors décalées d'une à deux heures : le message
    d'alerte doit le dire clairement.
    """
    try:
        return ZoneInfo("Europe/Paris")
    except Exception as e:  # noqa: BLE001
        logger.critical(
            "Base de fuseaux horaires absente (%s) — repli sur UTC. Les tâches "
            "planifiées se déclencheront avec 1 à 2 heures de décalage. "
            "Installez le paquet tzdata.", e)
        return timezone.utc


PARIS = _fuseau_paris()

INTERVALLE_MINIMAL = 5      # garde-fou : en dessous, une tâche s'emballe
# « every_days » (tous les N jours à H) et « monthly » (le N de chaque mois à
# H) : demande de Noa du 08/09 — « tous les X jours ou tous les X du mois, à
# telle heure ».
FORMES = ("interval", "daily", "weekly", "every_days", "monthly")


def _jour_du_mois_borne(annee: int, mois: int, jour: int) -> int:
    """Le 31 d'un mois de 30 jours est son dernier jour : on ne saute pas le mois."""
    import calendar
    return min(max(int(jour), 1), calendar.monthrange(annee, mois)[1])


def rythme_lisible(tache: dict) -> str:
    """« tous les 3 jours à 09:00 », « le 5 de chaque mois à 09:00 »… ce que
    l'écran et le chat disent d'une planification. Fonction pure."""
    forme = (tache.get("schedule_kind") or "").strip().lower()
    heure = tache.get("time_of_day")
    if isinstance(heure, time):
        h = f"{heure.hour:02d}:{heure.minute:02d}"
    else:
        h = str(heure or "")[:5]
    if forme == "interval":
        return f"toutes les {int(tache.get('interval_minutes') or 0)} min"
    if forme == "daily":
        return f"tous les jours à {h}"
    if forme == "weekly":
        noms = {1: "lundi", 2: "mardi", 3: "mercredi", 4: "jeudi", 5: "vendredi", 6: "samedi", 7: "dimanche"}
        jours = [noms[int(j)] for j in (tache.get("days_of_week") or []) if int(j) in noms]
        return ("chaque " + ", ".join(jours) if jours else "chaque semaine") + f" à {h}"
    if forme == "every_days":
        n = int(tache.get("interval_days") or 1)
        return (f"tous les {n} jours" if n > 1 else "tous les jours") + f" à {h}"
    if forme == "monthly":
        j = int(tache.get("day_of_month") or 1)
        return f"le {j} de chaque mois à {h}"
    return "sur demande"


def _paris(moment: Optional[datetime] = None) -> datetime:
    moment = moment or datetime.now(PARIS)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=PARIS)
    return moment.astimezone(PARIS)


def prochaine_echeance(tache: dict, apres: Optional[datetime] = None) -> Optional[datetime]:
    """Prochaine exécution d'une tâche, ou None si elle n'est pas planifiée.

    `apres` sert de point de départ (par défaut : maintenant). Le résultat est
    toujours STRICTEMENT postérieur, ce qui évite qu'une tâche se redéclenche en
    boucle sur la même échéance.
    """
    forme = (tache.get("schedule_kind") or "").strip().lower()
    if forme not in FORMES:
        return None

    depart = _paris(apres)

    if forme == "interval":
        minutes = max(int(tache.get("interval_minutes") or 0), INTERVALLE_MINIMAL)
        return depart + timedelta(minutes=minutes)

    heure = tache.get("time_of_day") or time(hour=8)
    if isinstance(heure, str):                    # « 07:30 » ou « 07:30:00 »
        morceaux = [int(x) for x in heure.split(":")[:2]]
        heure = time(hour=morceaux[0], minute=morceaux[1] if len(morceaux) > 1 else 0)

    candidat = depart.replace(hour=heure.hour, minute=heure.minute,
                              second=0, microsecond=0)
    if candidat <= depart:
        candidat += timedelta(days=1)

    if forme == "daily":
        return candidat

    if forme == "every_days":
        # Tous les N jours : on compte depuis la DERNIÈRE échéance quand on la
        # connaît (celle qui vient d'être consommée), sinon depuis aujourd'hui.
        n = max(int(tache.get("interval_days") or 1), 1)
        base = tache.get("next_run_at")
        if base:
            suivant = _paris(base).replace(hour=heure.hour, minute=heure.minute,
                                           second=0, microsecond=0)
            for _ in range(3660):
                suivant += timedelta(days=n)
                if suivant > depart:
                    return suivant
        return candidat

    if forme == "monthly":
        jour = int(tache.get("day_of_month") or 1)
        annee, mois = depart.year, depart.month
        for _ in range(14):
            cand = depart.replace(year=annee, month=mois, day=_jour_du_mois_borne(annee, mois, jour),
                                  hour=heure.hour, minute=heure.minute, second=0, microsecond=0)
            if cand > depart:
                return cand
            mois += 1
            if mois > 12:
                mois, annee = 1, annee + 1
        return None

    # weekly : jours ISO (1 = lundi … 7 = dimanche). Sans jour précisé, on se
    # rabat sur un rythme quotidien plutôt que de ne jamais déclencher.
    jours = [int(j) for j in (tache.get("days_of_week") or []) if 1 <= int(j) <= 7]
    if not jours:
        return candidat
    for _ in range(8):
        if candidat.isoweekday() in jours:
            return candidat
        candidat += timedelta(days=1)
    return candidat


def heure_du_jour(brut) -> Optional[time]:
    """« 07:30 » ou « 7h30 » vers un `time`, ou None.

    POURQUOI CETTE FONCTION EXISTE (01/09). L'heure partait en base sous forme
    de CHAÎNE vers un paramètre `$8::time`. asyncpg n'accepte pas ça : il exige
    un `datetime.time` pour ce type et lève `DataError`. Conséquence mesurée :
    « chaque matin à 7h30, trie les mails » faisait échouer le skill, et le
    tour rendait « ERREUR : invalid input for query argument $8 ». Autrement
    dit, AUCUNE tâche quotidienne ou hebdomadaire ne pouvait être créée — seule
    la récurrence par intervalle passait, parce qu'elle ne pose pas d'heure.

    Le cast SQL `::time` ne sauve pas : il s'applique APRÈS l'encodage du
    paramètre, et c'est l'encodage qui refuse.
    """
    if brut is None or isinstance(brut, time):
        return brut
    texte = str(brut).strip().lower().replace("h", ":")
    if not texte:
        return None
    morceaux = texte.split(":")
    try:
        h = int(morceaux[0])
        m = int(morceaux[1]) if len(morceaux) > 1 and morceaux[1] else 0
    except (ValueError, IndexError):
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return time(hour=h, minute=m)


def valider_planification(donnees: dict) -> Optional[str]:
    """Retourne un message d'erreur si la planification est incohérente, sinon None."""
    forme = (donnees.get("schedule_kind") or "").strip().lower()
    if not forme:
        return None                                # tâche non planifiée : valide
    if forme not in FORMES:
        return f"Type de planification inconnu : {forme}. Attendu : {', '.join(FORMES)}."
    if forme == "interval":
        minutes = donnees.get("interval_minutes")
        if not minutes or int(minutes) < INTERVALLE_MINIMAL:
            return (f"L'intervalle doit valoir au moins {INTERVALLE_MINIMAL} minutes "
                    "(en deçà, la tâche s'emballe).")
    if forme in ("daily", "weekly", "every_days", "monthly") and not donnees.get("time_of_day"):
        return "Précisez l'heure d'exécution (time_of_day)."
    if forme == "every_days":
        n = donnees.get("interval_days")
        if not n or int(n) < 1:
            return "Précisez tous les combien de jours (interval_days, 1 au moins)."
    if forme == "monthly":
        j = donnees.get("day_of_month")
        if not j or not (1 <= int(j) <= 31):
            return "Précisez le jour du mois (day_of_month, de 1 à 31)."
    if forme == "weekly":
        jours = donnees.get("days_of_week") or []
        if not jours or any(not (1 <= int(j) <= 7) for j in jours):
            return "Précisez les jours (1 = lundi … 7 = dimanche)."
    return None
