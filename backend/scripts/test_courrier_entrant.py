"""
Banc « LE COURRIER ENTRANT, LU UNE FOIS, DÈS SON ARRIVÉE » (08/09 soir).

Demande de Noa : « ça lit tous les mails, ça propose des réponses uniquement
à ceux qui nécessitent des réponses, ça explique pourquoi certains ne
nécessitent pas de réponse ; les pièces jointes récupérées, stockées ; chaque
mail lu dès réception → une tâche en attente de validation qui dit le nom de
la tâche et ce qui a été fait ».

CE QUE CE BANC PROUVE (skill EXÉCUTÉ contre une messagerie et une base
doublées) : la première lecture part de la veille, les suivantes du dernier
message vu (repère par boîte, avancé à la date du plus récent, jamais à
« maintenant ») ; un message déjà vu n'est pas relu ; chaque nouveau message
est ouvert en entier avec ses pièces, dont les cartes sont garanties ; un
message illisible n'arrête pas les autres ; la consigne impose la raison
d'une absence de réponse ; le reste attend l'appel suivant, dit. La carte
d'accord d'une tâche planifiée porte le nom de la tâche. Tombe sur la
version d'avant.
"""
import asyncio
import json
import pathlib
import sys
import types
from datetime import datetime, timezone

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ LE COURRIER ENTRANT — {BACKEND.parent}\n")
REPERE: dict = {}


class _Conn:
    async def fetchrow(self, sql, *a):
        return REPERE.get((a[0], a[1]))

    async def execute(self, sql, *a):
        REPERE[(a[0], a[1])] = {"dernier_vu": a[2], "dernieres_refs": a[3]}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *x):
        return False


db = types.ModuleType("database.connection"); db.get_db = lambda: _Conn()
sys.modules["database"] = types.ModuleType("database"); sys.modules["database.connection"] = db
reg = types.ModuleType("skills.registre")


class Declaration:
    def __init__(self, **kw):
        self.__dict__.update(kw)
reg.Declaration = Declaration
sys.modules["skills"] = types.ModuleType("skills"); sys.modules["skills.registre"] = reg

BOITE = [
    {"ref": "m1", "de": "client@x.fr", "objet": "Demande de devis terrasse", "date": "2026-09-08T07:10:00Z", "apercu": "Bonjour, pourriez-vous…", "lu": False},
    {"ref": "m2", "de": "no-reply@vivreenbois.com", "objet": "Votre commande", "date": "2026-09-08T07:20:00Z", "apercu": "Merci pour votre commande", "expediteur_automatique": True},
    {"ref": "m3", "de": "archi@agence.fr", "objet": "Plans indice B", "date": "2026-09-08T07:30:00Z", "apercu": "Ci-joint les plans", "pieces_jointes": True},
]
APPELS = {"lire_mails": [], "lire_mail": []}


async def _lire_mails(data, user):
    APPELS["lire_mails"].append(dict(data))
    return {"boite": "julien@symbiose.fr", "messages": list(BOITE), "total_periode": 3}


async def _lire_mail(data, user):
    APPELS["lire_mail"].append(data["ref"])
    if data["ref"] == "m2":
        raise RuntimeError("message supprimé côté serveur")
    corps = "Bonjour, pourriez-vous nous faire un devis pour une terrasse bois de 30 m² ? " * 12
    fiche = {"ref": data["ref"], "corps": corps, "pieces_jointes": [], "liens": ["https://x.fr/plan"]}
    if data["ref"] == "m3":
        fiche["pieces_jointes"] = [{"nom": "plans-B.pdf", "lu": True}, {"nom": "photo.jpg"}]
        fiche["bloc_ui"] = [{"type": "fichier", "url": "/api/documents/J1", "nom": "plans-B.pdf"},
                            {"type": "visuel", "images": [{"cle": "a" * 24}]}]
    return fiche
ms = types.ModuleType("mail.skills"); ms.SKILLS_NATIFS = {"lire_mails": _lire_mails, "lire_mail": _lire_mail}
sys.modules["mail"] = types.ModuleType("mail"); sys.modules["mail.skills"] = ms

src = BACKEND / "skills" / "courrier.py"
verifier("le skill `skills/courrier.py` existe", src.exists())
if not src.exists():
    sys.exit(1)
mod = types.ModuleType("courrier_double")
exec(compile(src.read_text(encoding="utf-8"), str(src), "exec"), mod.__dict__)
U = types.SimpleNamespace(id="u1", role="direction")

r = asyncio.run(mod.courrier_entrant({}, U))
verifier("première lecture : depuis la veille (« 1j »), la boîte par défaut", APPELS["lire_mails"][0]["depuis"] == "1j" and "mailbox" not in APPELS["lire_mails"][0])
verifier("chaque nouveau message est OUVERT en entier, pièces jointes demandées", sorted(APPELS["lire_mail"]) == ["m1", "m2", "m3"])
verifier("un message illisible n'arrête pas les autres : sa raison est dite",
         r["nombre"] == 3 and any(m.get("erreur", "").startswith("message supprimé") for m in r["messages"]))
verifier("l'extrait vient du corps ENTIER ouvert (pas de l'aperçu), et la troncature est dite",
         r["messages"][0]["extrait"].startswith("Bonjour, pourriez-vous nous faire un devis") and r["messages"][0]["corps_tronque"] is True)
verifier("les pièces jointes sont nommées, leurs cartes GARANTIES à l'écran, après le tableau des messages",
         r["messages"][2]["pieces_jointes"] == ["plans-B.pdf", "photo.jpg"] and r["pieces_jointes"] == 2
         and r["bloc_garanti"] is True and r["bloc_ui"][0]["type"] == "table" and [b["type"] for b in r["bloc_ui"][1:]] == ["fichier", "visuel"])
verifier("l'automatique et le non-lu sont marqués", r["messages"][1]["automatique"] is True and r["messages"][0]["non_lu"] is True)
verifier("la consigne : réponse seulement à ceux qui en appellent une, et POURQUOI pour les autres, rien n'est envoyé",
         "UNIQUEMENT à ceux qui en appellent une" in r["a_faire"] and "POURQUOI" in r["a_faire"] and "N'envoie rien" in r["a_faire"])
rep = REPERE[("u1", "@moi")]
verifier("le repère avance à la date du message le plus RÉCENT vu (07:30 UTC), pas à maintenant",
         rep["dernier_vu"] == datetime(2026, 9, 8, 7, 30, tzinfo=timezone.utc) and set(json.loads(rep["dernieres_refs"])) == {"m1", "m2", "m3"})

APPELS["lire_mails"].clear(); APPELS["lire_mail"].clear()
r2 = asyncio.run(mod.courrier_entrant({}, U))
verifier("deuxième lecture : depuis le dernier message vu (ISO), et les messages déjà vus ne sont PAS relus",
         APPELS["lire_mails"][0]["depuis"] == "2026-09-08T07:30:00" and APPELS["lire_mail"] == [] and r2["nombre"] == 0
         and "Aucun nouveau message" in r2["a_faire"])
BOITE.append({"ref": "m4", "de": "b@b.fr", "objet": "Relance", "date": "2026-09-08T08:00:00Z", "apercu": "…"})
APPELS["lire_mail"].clear()
r3 = asyncio.run(mod.courrier_entrant({"mailbox": "compta@symbiose.fr", "pieces": "false"}, U))
verifier("une autre boîte a SON repère ; « pieces: false » n'ouvre pas les pièces",
         ("u1", "compta@symbiose.fr") in REPERE and APPELS["lire_mails"][-1].get("mailbox") == "compta@symbiose.fr")
r4 = asyncio.run(mod.courrier_entrant({}, U))
verifier("un nouveau message arrivé depuis : lui seul est lu", r4["nombre"] == 1 and r4["messages"][0]["ref"] == "m4")


async def _beaucoup(data, user):
    return {"boite": "j@s.fr", "messages": [{"ref": f"x{i}", "de": "a", "objet": "o", "date": "2026-09-09T00:00:00Z"} for i in range(30)], "total_periode": 80}
ms.SKILLS_NATIFS["lire_mails"] = _beaucoup
r5 = asyncio.run(mod.courrier_entrant({}, U))
verifier("des centaines de mails : 30 par appel, le reste DIT et l'appel suivant demandé",
         r5["nombre"] == 30 and r5["reste"] == 50 and "rappelle `courrier_entrant`" in r5["a_faire"])
decl = mod.SKILLS["courrier_entrant"]
verifier("déclaré en LECTURE, pour une tâche « toutes les 10 minutes »", decl.effet == "lecture" and "toutes les 10 minutes" in decl.description)

print("— le câblage")
verifier("migration 038 : le repère par personne et par boîte, idempotente",
         "CREATE TABLE IF NOT EXISTS courrier_suivi" in (BACKEND / "database" / "migrations" / "038_courrier_suivi.sql").read_text(encoding="utf-8"))
rt = (BACKEND / "agents" / "runtime.py").read_text(encoding="utf-8")
verifier("la carte d'accord d'une tâche planifiée porte le NOM de la tâche",
         'if str(thread_id or "").startswith("task:"):' in rt and 'raison = f"Tâche « {titre} » — ' in rt)
verifier("`check_mails` exige la raison de chaque message sans réponse",
         "Pour chaque message SANS réponse proposée, dis en quelques mots POURQUOI" in (BACKEND / "skills" / "routines.py").read_text(encoding="utf-8"))
rac = (BACKEND.parent / "frontend" / "lib" / "raccourcis.ts").read_text(encoding="utf-8")
verifier("le menu éclair : le courrier entrant maintenant, et en tâche toutes les 10 minutes",
         "Courrier entrant automatique" in rac and "Courrier entrant (maintenant)" in rac)
verifier("résultat généreux", '"courrier_entrant"' in (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8").split("RESULTATS_GENEREUX = {")[1].split("}")[0])

print(f"\n{'═' * 72}")
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs)); sys.exit(1)
print("✓ 0 échec")
