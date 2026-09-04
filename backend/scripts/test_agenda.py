"""
Banc de L'AGENDA — lire les rendez-vous, trouver un créneau, en poser un.

LA DEMANDE (04/09, Noa) : « prépare dans le code la gestion calendrier du mail ».
L'assistant lisait les mails d'une boîte sans jamais voir l'agenda qui va avec :
« quand suis-je libre jeudi ? » n'avait aucun geste, et le modèle répondait de
mémoire.

CE QUE CE BANC PROUVE, `mail/agenda.py` EXÉCUTÉ (Graph doublé) :
  · LE CALCUL DES CRÉNEAUX est du code, pas du modèle. C'est le cœur : à qui
    l'on donne quinze rendez-vous et qu'on laisse en déduire les trous, il
    oublie un chevauchement, ignore la pause de midi, propose un dimanche.
    Chacun de ces trois pièges a son contrôle ici ;
  · une journée entière occupe le jour entier (un congé n'est pas un trou) ;
  · un 403 de Microsoft NOMME l'autorisation qui manque, au lieu d'envoyer
    chercher au mauvais endroit ;
  · créer un rendez-vous est un effet EXTERNE (accord humain), lire ne l'est pas ;
  · sur une messagerie Google, le geste dit ce qui reste à connecter — jamais
    un `ModuleNotFoundError`.
"""
import asyncio
import pathlib
import sys
import types
from datetime import datetime, timedelta, timezone

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ L'AGENDA — {BACKEND.parent}\n")
source = BACKEND / "mail" / "agenda.py"
if not source.exists():
    print("  ✗ backend/mail/agenda.py est absent — l'agenda n'existe pas.")
    sys.exit(1)

# ── LES DOUBLURES ─────────────────────────────────────────────────────────
ETAT = {"fournisseur": "outlook", "reponses": [], "requetes": []}


class _Reponse:
    def __init__(self, statut, charge=None, texte=""):
        self.status_code = statut
        self._json = charge if charge is not None else {}
        self.text = texte
        self.content = b"x"

    def json(self):
        return self._json


class _Client:
    def __init__(self, timeout=None):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def request(self, methode, url, params=None, json=None, headers=None):
        ETAT["requetes"].append({"methode": methode, "url": url, "params": params,
                                 "json": json, "headers": headers})
        return ETAT["reponses"].pop(0) if ETAT["reponses"] else _Reponse(200, {"value": []})


mod_httpx = types.ModuleType("httpx")
mod_httpx.AsyncClient = _Client
sys.modules["httpx"] = mod_httpx
mod_config = types.ModuleType("config")
mod_config.settings = types.SimpleNamespace(
    agenda_heure_debut=8, agenda_heure_fin=18, agenda_pause_debut=12,
    agenda_pause_fin=13, agenda_jours="0,1,2,3,4")
sys.modules["config"] = mod_config
mod_collecte = types.ModuleType("mail.collecte")
mod_collecte.fournisseur = lambda: ETAT["fournisseur"]
sys.modules["mail"] = types.ModuleType("mail")
sys.modules["mail.collecte"] = mod_collecte
mod_ing = types.ModuleType("ingestion")
mod_conn = types.ModuleType("ingestion.connectors")
mod_out = types.ModuleType("ingestion.connectors.outlook")


async def _faux_jeton():
    return "JETON-DE-BANC"


mod_out._jeton = _faux_jeton
sys.modules["ingestion"] = mod_ing
sys.modules["ingestion.connectors"] = mod_conn
sys.modules["ingestion.connectors.outlook"] = mod_out

agenda = types.ModuleType("agenda")
agenda.__dict__["__file__"] = str(source)
exec(compile(source.read_text(encoding="utf-8"), str(source), "exec"), agenda.__dict__)

PARIS = timezone(timedelta(hours=2))


def h(jour, heure, minute=0):
    """Un instant du LUNDI 7 septembre 2026 + `jour`, heure locale."""
    return datetime(2026, 9, 7 + jour, heure, minute, tzinfo=PARIS)


# ── 1. LE CALCUL DES CRÉNEAUX : les trois pièges du modèle ───────────────
BORNES = (8, 18, 12, 13)
OUVRES = {0, 1, 2, 3, 4}

libres = agenda.creneaux_libres([], h(0, 0), h(0, 23, 59), 60, OUVRES, BORNES)
verifier("une journée vide donne le matin et l'après-midi, pas une seule plage",
         [(d.hour, f.hour) for d, f in libres] == [(8, 12), (13, 18)], str(libres))

verifier("LA PAUSE DE MIDI N'EST JAMAIS PROPOSÉE",
         all(not (d.hour < 13 and f.hour > 12 and d.hour >= 8) or f.hour <= 12
             for d, f in libres))

# Deux rendez-vous qui SE CHEVAUCHENT : le « trou » entre les deux n'existe pas.
chevauchants = [(h(0, 9), h(0, 11)), (h(0, 10), h(0, 12))]
entre = agenda.creneaux_libres(chevauchants, h(0, 8), h(0, 18), 60, OUVRES, BORNES)
verifier("deux rendez-vous qui se chevauchent ne créent pas un faux trou entre eux",
         [(d.hour, f.hour) for d, f in entre] == [(8, 9), (13, 18)], str(entre))
verifier("rien n'est proposé pendant la période occupée fondue (9 h – 12 h)",
         all(f <= h(0, 9) or d >= h(0, 12) for d, f in entre))

verifier("les périodes occupées se fondent quand elles se recouvrent",
         agenda.fusionner(chevauchants) == [(h(0, 9), h(0, 12))])

# Le week-end : samedi 12 et dimanche 13 septembre 2026.
verifier("AUCUN CRÉNEAU LE WEEK-END",
         agenda.creneaux_libres([], h(5, 0), h(6, 23), 60, OUVRES, BORNES) == [])

# Un créneau trop court n'est pas un créneau.
serre = [(h(0, 8), h(0, 11, 30)), (h(0, 12), h(0, 18))]
verifier("un trou plus court que la durée demandée n'est pas proposé",
         agenda.creneaux_libres(serre, h(0, 8), h(0, 18), 60, OUVRES, BORNES) == [])
verifier("le même trou est proposé si la durée demandée y tient",
         len(agenda.creneaux_libres(serre, h(0, 8), h(0, 18), 20, OUVRES, BORNES)) == 1)

# La recherche ne remonte pas dans le passé.
tard = agenda.creneaux_libres([], h(0, 15), h(0, 18), 60, OUVRES, BORNES)
verifier("un créneau ne commence jamais avant l'instant demandé",
         all(d >= h(0, 15) for d, _ in tard), str(tard))

verifier("le nombre de créneaux rendus est borné",
         len(agenda.creneaux_libres([], h(0, 0), h(20, 0), 60, OUVRES, BORNES, maximum=5)) == 5)


# ── 2. LA LECTURE : `calendarView`, et la journée entière ─────────────────
def _ev(debut, fin, titre="RDV", entiere=False):
    return {"subject": titre, "isAllDay": entiere,
            "start": {"dateTime": debut}, "end": {"dateTime": fin},
            "location": {"displayName": "La Teste"},
            "organizer": {"emailAddress": {"address": "b@symbiose-paysage.fr"}},
            "attendees": [{"emailAddress": {"address": "client@exemple.fr"}}]}


ETAT["requetes"].clear()
ETAT["reponses"] = [_Reponse(200, {"value": [_ev("2026-09-08T09:00:00.0000000",
                                                 "2026-09-08T10:30:00.0000000")]})]
evs = asyncio.run(agenda.lire("b@symbiose-paysage.fr", h(0, 0), h(7, 0)))
verifier("un rendez-vous se lit avec ce qu'un humain regarde",
         evs and evs[0]["titre"] == "RDV" and evs[0]["lieu"] == "La Teste"
         and evs[0]["participants"] == ["client@exemple.fr"], str(evs))
req = ETAT["requetes"][0]
verifier("la lecture passe par `calendarView` (les récurrences sont déployées)",
         "/calendarView" in req["url"] and req["methode"] == "GET")
verifier("la période part et revient triée par début",
         req["params"]["$orderby"] == "start/dateTime"
         and "startDateTime" in req["params"] and "endDateTime" in req["params"])
verifier("le jeton d'application voyage en en-tête, jamais dans l'URL",
         req["headers"]["Authorization"] == "Bearer JETON-DE-BANC"
         and "JETON" not in req["url"])

ETAT["reponses"] = [_Reponse(200, {"value": [_ev("2026-09-08T00:00:00.0000000",
                                                 "2026-09-08T00:00:00.0000000",
                                                 "Congé", entiere=True)]})]
prises = asyncio.run(agenda.occupations("b@symbiose-paysage.fr", h(0, 0), h(7, 0)))
verifier("UNE JOURNÉE ENTIÈRE OCCUPE LE JOUR ENTIER (un congé n'est pas un trou)",
         prises and (prises[0][1] - prises[0][0]) >= timedelta(days=1), str(prises))


# ── 3. LES REFUS, qui disent quoi faire ──────────────────────────────────
ETAT["reponses"] = [_Reponse(403, {}, "Insufficient privileges")]
try:
    asyncio.run(agenda.lire("b@symbiose-paysage.fr", h(0, 0), h(1, 0)))
    verifier("un 403 en LECTURE nomme Calendars.Read", False)
except agenda.AgendaIndisponible as e:
    verifier("un 403 en LECTURE nomme Calendars.Read",
             "Calendars.Read" in str(e) and "consentement administrateur" in str(e))

ETAT["reponses"] = [_Reponse(403, {}, "Insufficient privileges")]
try:
    asyncio.run(agenda.creer("b@symbiose-paysage.fr", "Visite", h(0, 9), h(0, 10)))
    verifier("un 403 en ÉCRITURE nomme Calendars.ReadWrite", False)
except agenda.AgendaIndisponible as e:
    verifier("un 403 en ÉCRITURE nomme Calendars.ReadWrite", "Calendars.ReadWrite" in str(e))

ETAT["fournisseur"] = "gmail"
try:
    asyncio.run(agenda.lire("x@duret-sols.fr", h(0, 0), h(1, 0)))
    verifier("sur une messagerie Google, le geste dit ce qui reste à connecter", False)
except agenda.AgendaIndisponible as e:
    verifier("sur une messagerie Google, le geste dit ce qui reste à connecter",
             "Google Calendar" in str(e))
ETAT["fournisseur"] = "outlook"

try:
    asyncio.run(agenda.creer("b@symbiose-paysage.fr", "Visite", h(0, 10), h(0, 9)))
    verifier("une fin avant le début est refusée", False)
except agenda.AgendaIndisponible as e:
    verifier("une fin avant le début est refusée", "doit suivre" in str(e))


# ── 4. LA CRÉATION : ce qui part chez Microsoft ──────────────────────────
ETAT["requetes"].clear()
ETAT["reponses"] = [_Reponse(201, _ev("2026-09-08T09:00:00.0000000",
                                      "2026-09-08T10:00:00.0000000", "Visite Duval"))]
cree = asyncio.run(agenda.creer("b@symbiose-paysage.fr", "Visite Duval", h(1, 9), h(1, 10),
                                ["client@exemple.fr", "pas-une-adresse"], "La Teste", "Devis terrasse"))
envoi = ETAT["requetes"][0]
verifier("la création POSTe un événement sur la boîte visée",
         envoi["methode"] == "POST" and envoi["url"].endswith("/users/b@symbiose-paysage.fr/events"))
verifier("le titre, le lieu et la note partent",
         envoi["json"]["subject"] == "Visite Duval"
         and envoi["json"]["location"]["displayName"] == "La Teste"
         and envoi["json"]["body"]["content"] == "Devis terrasse")
verifier("seules les VRAIES adresses sont invitées",
         [a["emailAddress"]["address"] for a in envoi["json"]["attendees"]] == ["client@exemple.fr"])
verifier("les heures partent en UTC, sans fuseau (ce que Graph attend)",
         envoi["json"]["start"]["timeZone"] == "UTC"
         and envoi["json"]["start"]["dateTime"] == "2026-09-08T07:00:00")
verifier("la fiche rendue est celle d'un rendez-vous, pas la réponse brute",
         cree.get("titre") == "Visite Duval" and "boite" in cree)


# ── 5. LES SKILLS, LEURS EFFETS ET LE CATALOGUE ──────────────────────────
skills = (BACKEND / "mail" / "skills.py").read_text(encoding="utf-8")
for nom in ("mon_agenda", "creneaux_agenda", "creer_rendez_vous"):
    verifier(f"le skill `{nom}` est déclaré", f'SKILLS_NATIFS["{nom}"] = {nom}' in skills)
verifier("lire l'agenda et chercher un créneau sont des LECTURES",
         '"mon_agenda": "lecture"' in skills and '"creneaux_agenda": "lecture"' in skills)
verifier("POSER un rendez-vous est un effet EXTERNE (il invite de vraies gens)",
         '"creer_rendez_vous": "externe"' in skills)
verifier("créer exige le droit d'écrire au nom de la boîte (envoi=True)",
         "await boite_par_defaut(user),\n                                 envoi=True)" in skills)
verifier("une adresse d'invité inventée est refusée",
         "n'est pas une vraie adresse" in skills)
verifier("les deux lectures garantissent leur tableau à l'écran",
         skills.count('"bloc_garanti": True') >= 3)
verifier("le modèle ne doit PAS déduire les créneaux lui-même",
         "ne déduis JAMAIS " in skills and "les disponibilités toi-même" in skills
         and "invente aucun, n'en déduis pas d'autres" in skills)

protocole = (BACKEND / "skills" / "protocol.py").read_text(encoding="utf-8")
for nom in ("mon_agenda", "creneaux_agenda", "creer_rendez_vous"):
    verifier(f"`{nom}` est au catalogue du modèle", f'"{nom}": (' in protocole)
verifier("le catalogue exige `titre` et `debut` pour créer",
         '["titre", "debut"]' in protocole)
journal = (BACKEND / "agents" / "journal.py").read_text(encoding="utf-8")
verifier("l'écran dit ce qu'il fait pendant ce temps",
         '"mon_agenda": "je regarde l\'agenda"' in journal
         and '"creer_rendez_vous": "je pose le rendez-vous"' in journal)
config = (BACKEND / "config.py").read_text(encoding="utf-8")
verifier("les heures ouvrées sont des réglages, pas des chiffres en dur",
         "agenda_heure_debut: int = 8" in config and 'agenda_jours: str = "0,1,2,3,4"' in config)
env = (BACKEND.parent / ".env.example").read_text(encoding="utf-8")
verifier("le .env d'exemple les documente, et nomme les autorisations Microsoft",
         "AGENDA_JOURS=0,1,2,3,4" in env and "Calendars.ReadWrite" in env)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
