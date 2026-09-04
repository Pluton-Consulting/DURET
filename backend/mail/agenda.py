"""
L'AGENDA DE LA MESSAGERIE — lire les rendez-vous, trouver un créneau, en poser un.

LA DEMANDE (04/09, Noa) : « prépare dans le code la gestion calendrier du mail ».
Jusqu'ici l'assistant lisait les mails d'une boîte sans jamais voir l'agenda qui
va avec : « quand suis-je libre jeudi ? », « cale une visite chez M. Duval »
n'avaient aucun geste, et le modèle répondait de mémoire ou refusait.

CE MODULE EST DU SOCLE, l'aiguillage est celui de `mail/lecture.py` :
`fournisseur()` décide, et chaque fournisseur a sa fonction. Aujourd'hui la voie
MICROSOFT GRAPH est implémentée (Symbiose) ; la voie Google Calendar ne l'est
pas, et le dit — un connecteur absent doit se lire comme une configuration à
faire, jamais comme un `ModuleNotFoundError` (même choix que `mail/collecte.py`).

TROIS GESTES, ET PAS UN DE PLUS :
  · LIRE une période — c'est 90 % des demandes (« mon planning de la semaine ») ;
  · CHERCHER LES CRÉNEAUX LIBRES — calculé ICI, mécaniquement, à partir des
    événements lus. Un modèle à qui l'on donne quinze rendez-vous et qui doit
    en déduire les trous se trompe : il oublie un chevauchement, il ignore la
    pause de midi, il propose un créneau un dimanche. Le calcul est du code ;
  · CRÉER un rendez-vous — effet EXTERNE : il part chez de vraies personnes,
    il attend donc l'accord humain comme un envoi de mail.

CE QU'IL NE FAIT PAS. Ni modifier, ni annuler un rendez-vous existant : ces
gestes touchent l'agenda de quelqu'un d'autre à son insu, et méritent leur
propre tour de réflexion. Ni gérer les récurrences : Graph les rend « déployées »
dans une vue de période (`calendarView`), ce qui suffit à lire ; les créer
demanderait un vocabulaire de récurrence que personne n'a réclamé.

LES DROITS. `verifier_acces` du socle mail décide, comme pour les messages :
sa boîte, ses délégations, toute boîte NOMMÉE pour super_admin et direction.
L'agenda d'une personne est au moins aussi sensible que ses mails.

⚠️ CÔTÉ MICROSOFT, il faut la permission d'APPLICATION `Calendars.Read`
(lecture) et `Calendars.ReadWrite` (création), avec consentement administrateur.
Sans elles, Graph répond 403 et les gestes le disent en nommant la permission.
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from typing import Optional

logger = logging.getLogger("duret.mail.agenda")

GRAPH = "https://graph.microsoft.com/v1.0"
# Une vue d'agenda tient dans quelques dizaines d'événements ; au-delà, ce n'est
# plus un planning qu'on lit, c'est un export.
MAX_EVENEMENTS = 100
# Bornes d'une recherche de créneaux : personne ne cale une visite à trois
# semaines sans regarder son planning autrement.
MAX_JOURS = 60


class AgendaIndisponible(RuntimeError):
    """Connecteur absent, permission refusée, service muet. Dit quoi faire."""


# ── Les heures ouvrées, réglables mais posées ────────────────────────────
def heures_ouvrees() -> tuple[int, int, int, int]:
    """(début, fin, début de pause, fin de pause) en heures locales.

    Un créneau proposé à 6 h du matin ou un dimanche n'est pas un créneau : ce
    sont les bornes qui rendent la recherche utile. Réglables par `.env`
    (`AGENDA_*`) sans toucher au code.
    """
    from config import settings
    return (int(getattr(settings, "agenda_heure_debut", 8) or 8),
            int(getattr(settings, "agenda_heure_fin", 18) or 18),
            int(getattr(settings, "agenda_pause_debut", 12) or 12),
            int(getattr(settings, "agenda_pause_fin", 13) or 13))


def jours_ouvres() -> set[int]:
    """Les jours travaillés, 0 = lundi. Par défaut du lundi au vendredi."""
    from config import settings
    brut = str(getattr(settings, "agenda_jours", "0,1,2,3,4") or "0,1,2,3,4")
    jours = set()
    for morceau in brut.split(","):
        morceau = morceau.strip()
        if morceau.isdigit() and 0 <= int(morceau) <= 6:
            jours.add(int(morceau))
    return jours or {0, 1, 2, 3, 4}


# ── Fonctions PURES : c'est là que vit le calcul ─────────────────────────
def fusionner(occupes: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    """Les périodes occupées, triées et fondues quand elles se chevauchent.

    Deux rendez-vous qui se recouvrent ne font qu'UNE indisponibilité : sans
    cette fusion, le trou « entre les deux » serait proposé alors qu'il n'existe
    pas. Fonction pure, exercée au banc.
    """
    propres = sorted((d, f) for d, f in occupes if f > d)
    fondus: list[tuple[datetime, datetime]] = []
    for debut, fin in propres:
        if fondus and debut <= fondus[-1][1]:
            fondus[-1] = (fondus[-1][0], max(fondus[-1][1], fin))
        else:
            fondus.append((debut, fin))
    return fondus


def creneaux_libres(occupes: list[tuple[datetime, datetime]],
                    depuis: datetime, jusqu_a: datetime, duree_min: int,
                    ouvres: Optional[set[int]] = None,
                    bornes: Optional[tuple[int, int, int, int]] = None,
                    maximum: int = 12) -> list[tuple[datetime, datetime]]:
    """Les créneaux d'au moins `duree_min` minutes, dans les heures ouvrées.

    Le cœur du module, et une fonction PURE : elle ne connaît ni Graph, ni la
    base, ni l'heure qu'il est. Elle découpe chaque jour ouvré en plages
    (matin, après-midi), en retire ce qui est occupé, et garde ce qui reste
    d'assez long. La pause de midi est retirée comme une occupation : c'est ce
    qui évite de proposer « 11 h 45 – 13 h 15 ».
    """
    h_debut, h_fin, p_debut, p_fin = bornes or heures_ouvrees()
    ouvres = ouvres if ouvres is not None else jours_ouvres()
    fondus = fusionner(occupes)
    libres: list[tuple[datetime, datetime]] = []
    jour = depuis.replace(hour=0, minute=0, second=0, microsecond=0)
    limite = jusqu_a

    while jour <= limite and len(libres) < maximum:
        if jour.weekday() in ouvres:
            for a, b in ((h_debut, p_debut), (p_fin, h_fin)):
                if b <= a:
                    continue
                plage_debut = max(jour.replace(hour=a), depuis)
                plage_fin = min(jour.replace(hour=b), limite)
                curseur = plage_debut
                for occ_debut, occ_fin in fondus:
                    if occ_fin <= curseur or occ_debut >= plage_fin:
                        continue
                    if occ_debut - curseur >= timedelta(minutes=duree_min):
                        libres.append((curseur, occ_debut))
                    curseur = max(curseur, occ_fin)
                if plage_fin - curseur >= timedelta(minutes=duree_min):
                    libres.append((curseur, plage_fin))
        jour += timedelta(days=1)
    return libres[:maximum]


def _iso(d: datetime) -> str:
    """Graph veut une date sans fuseau, exprimée en UTC."""
    return d.astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def _fiche(ev: dict, boite: str) -> dict:
    """Un événement Graph, réduit à ce qu'un humain lit."""
    debut = (ev.get("start") or {}).get("dateTime") or ""
    fin = (ev.get("end") or {}).get("dateTime") or ""
    lieu = ((ev.get("location") or {}).get("displayName") or "").strip()
    organisateur = (((ev.get("organizer") or {}).get("emailAddress") or {}).get("address") or "")
    participants = [((p.get("emailAddress") or {}).get("address") or "")
                    for p in (ev.get("attendees") or [])]
    return {
        "titre": (ev.get("subject") or "(sans titre)").strip(),
        "debut": debut, "fin": fin,
        "journee_entiere": bool(ev.get("isAllDay")),
        "lieu": lieu,
        "organisateur": organisateur,
        "participants": [p for p in participants if p][:12],
        "boite": boite,
        "en_ligne": (ev.get("onlineMeetingUrl") or "") or None,
    }


def _analyser(iso: str) -> Optional[datetime]:
    """« 2026-09-08T09:00:00.0000000 » → datetime UTC. Graph rend l'UTC nu."""
    if not iso:
        return None
    texte = str(iso).replace("Z", "+00:00")
    if "." in texte:
        avant, _, apres = texte.partition(".")
        fuseau = ""
        for marque in ("+", "-"):
            if marque in apres:
                _, _, reste = apres.partition(marque)
                fuseau = marque + reste
                break
        texte = avant + fuseau
    try:
        d = datetime.fromisoformat(texte)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# ── LA VOIE MICROSOFT GRAPH ──────────────────────────────────────────────
async def _graph(methode: str, chemin: str, *, params=None, json=None) -> dict:
    import httpx
    from ingestion.connectors.outlook import _jeton
    jeton = await _jeton()
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.request(methode, f"{GRAPH}{chemin}",
                                 params=params, json=json,
                                 headers={"Authorization": f"Bearer {jeton}",
                                          "Prefer": 'outlook.timezone="Europe/Paris"'})
    if r.status_code in (401, 403):
        # LA PERMISSION MANQUANTE SE NOMME. Un 403 nu envoie chercher au mauvais
        # endroit ; le nom de l'autorisation Graph mène droit au bon écran.
        besoin = "Calendars.ReadWrite" if methode.upper() == "POST" else "Calendars.Read"
        raise AgendaIndisponible(
            f"L'agenda de cette boîte est refusé par Microsoft. L'application a besoin de "
            f"l'autorisation « {besoin} » (type Application) avec consentement administrateur.")
    if r.status_code == 404:
        raise AgendaIndisponible("Cette boîte n'a pas d'agenda accessible.")
    if r.status_code >= 400:
        logger.warning("Graph agenda %s %s : HTTP %s — %s", methode, chemin,
                       r.status_code, r.text[:200])
        raise AgendaIndisponible("L'agenda n'a pas pu être lu. Réessayez dans un instant.")
    return r.json() if r.content else {}


async def _lire_outlook(boite: str, depuis: datetime, jusqu_a: datetime,
                        limite: int) -> list[dict]:
    """`calendarView` : la période DÉPLOYÉE, récurrences comprises."""
    corps = await _graph("GET", f"/users/{boite}/calendarView", params={
        "startDateTime": _iso(depuis), "endDateTime": _iso(jusqu_a),
        "$orderby": "start/dateTime", "$top": limite,
        "$select": "subject,start,end,isAllDay,location,organizer,attendees,onlineMeetingUrl",
    })
    return [_fiche(e, boite) for e in corps.get("value", [])]


async def _creer_outlook(boite: str, titre: str, debut: datetime, fin: datetime,
                         participants: list[str], lieu: str, note: str) -> dict:
    evenement = {
        "subject": titre,
        "start": {"dateTime": _iso(debut), "timeZone": "UTC"},
        "end": {"dateTime": _iso(fin), "timeZone": "UTC"},
    }
    if lieu:
        evenement["location"] = {"displayName": lieu}
    if note:
        evenement["body"] = {"contentType": "text", "content": note}
    if participants:
        evenement["attendees"] = [
            {"emailAddress": {"address": a}, "type": "required"} for a in participants]
    cree = await _graph("POST", f"/users/{boite}/events", json=evenement)
    return _fiche(cree, boite)


# ── L'ENTRÉE, commune ────────────────────────────────────────────────────
def _voie() -> str:
    from mail.collecte import fournisseur
    nom = fournisseur()
    if nom != "outlook":
        raise AgendaIndisponible(
            "L'agenda n'est branché que sur Microsoft 365 pour l'instant. Sur une "
            "messagerie Google, il reste à connecter (API Google Calendar).")
    return nom


async def lire(boite: str, depuis: datetime, jusqu_a: datetime,
               limite: int = MAX_EVENEMENTS) -> list[dict]:
    """Les rendez-vous d'une boîte sur une période. L'appelant a vérifié l'accès."""
    _voie()
    limite = max(1, min(int(limite or MAX_EVENEMENTS), MAX_EVENEMENTS))
    return await _lire_outlook(boite, depuis, jusqu_a, limite)


async def occupations(boite: str, depuis: datetime, jusqu_a: datetime) -> list[tuple[datetime, datetime]]:
    """Les périodes prises, prêtes pour `creneaux_libres`.

    Une journée entière occupe le jour entier : sans cela, un congé posé en
    « toute la journée » laissait l'assistant proposer des visites en plein
    milieu.
    """
    prises: list[tuple[datetime, datetime]] = []
    for ev in await lire(boite, depuis, jusqu_a):
        d, f = _analyser(ev.get("debut")), _analyser(ev.get("fin"))
        if not d or not f:
            continue
        if ev.get("journee_entiere"):
            d = d.replace(hour=0, minute=0, second=0, microsecond=0)
            f = max(f, d + timedelta(days=1))
        prises.append((d, f))
    return prises


async def creer(boite: str, titre: str, debut: datetime, fin: datetime,
                participants: Optional[list[str]] = None,
                lieu: str = "", note: str = "") -> dict:
    """Pose un rendez-vous. À n'appeler qu'après l'accord humain (effet externe)."""
    _voie()
    if fin <= debut:
        raise AgendaIndisponible("La fin du rendez-vous doit suivre son début.")
    return await _creer_outlook(boite, titre.strip() or "Rendez-vous", debut, fin,
                                [a for a in (participants or []) if a and "@" in a],
                                lieu.strip(), note.strip())
