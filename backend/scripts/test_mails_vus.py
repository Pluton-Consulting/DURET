"""
Banc des MAILS DÉJÀ VUS DANS LA CONVERSATION (17/09, Duret) : « pourquoi je suis
obligé de rementionner le mail à chaque fois ? » — la `ref` d'un message ne
survivait pas au tour. Exécuté sur les modules livrés, registre dans un dossier
temporaire ; sans base ni réseau.

    python backend/scripts/test_mails_vus.py backend
"""
import asyncio, os, sys, tempfile
from pathlib import Path

BACKEND = Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
sys.path.insert(0, str(BACKEND))
TEMP = tempfile.TemporaryDirectory(prefix="banc-mails-vus-")
os.environ["DOCUMENTS_DIR"] = TEMP.name
for k, v in {"DATABASE_URL": "postgresql://x:x@localhost/x", "JWT_SECRET_KEY": "x" * 40, "RESEND_API_KEY": "x"}.items():
    os.environ.setdefault(k, v)
ECHECS = []


def verifier(nom, condition, detail=""):
    print(("  ✓ " if condition else "  ✗ ") + nom + (f"  → {detail}" if detail and not condition else ""))
    if not condition:
        ECHECS.append(nom)


from mail import vus
from security.conversation import fil_courant

BOITE = "boite@exemple-sols.fr"
fil_courant.set("fil-A")
vus.noter([{"ref": "aaaa1111bbbb2222", "objet": "Devis chape R+1", "de": "Client <c@exemple.fr>", "date_iso": "2026-09-16T09:00:00"},
           {"ref": "cccc3333dddd4444", "objet": "Relance planning", "de": "MOE <m@exemple.fr>", "date_iso": "2026-09-15T09:00:00"}], BOITE)
vus.noter([{"ref": "eeee5555ffff6666", "objet": "Maxime - Mémoire Technique", "de": "Noa <n@exemple.fr>", "date_iso": "2026-09-17T15:31:00", "corps": "SECRET"}], BOITE)
boite, liste = vus.du_fil("fil-A")
verifier("la conversation retient ce qu'elle a vu, le plus récent en tête", boite == BOITE and [x["ref"] for x in liste] == ["eeee5555ffff6666", "aaaa1111bbbb2222", "cccc3333dddd4444"], str(liste))
verifier("aucun contenu de message n'est gardé, seulement de quoi le retrouver", "SECRET" not in str(liste) and set(liste[0]) == {"ref", "objet", "de", "date"})
verifier("« ce mail » = le dernier vu", vus.retrouver("fil-A", BOITE) == "eeee5555ffff6666")
verifier("par son objet, sans accent ni casse exacts", vus.retrouver("fil-A", BOITE, objet="devis CHAPE") == "aaaa1111bbbb2222")
verifier("par son expéditeur", vus.retrouver("fil-A", BOITE, de="moe") == "cccc3333dddd4444")
verifier("un objet jamais vu ne désigne rien (pas le dernier par défaut)", vus.retrouver("fil-A", BOITE, objet="facture inconnue") is None)
verifier("une autre conversation ne voit rien", vus.du_fil("fil-B") == ("", []) and vus.retrouver("fil-B", BOITE) is None)
verifier("une autre boîte ne reçoit pas ces références", vus.retrouver("fil-A", "autre@exemple-sols.fr") is None)
vus.noter([{"ref": "aaaa1111bbbb2222", "objet": "Devis chape R+1", "de": "Client", "date_iso": ""}], BOITE)
verifier("un mail revu remonte en tête, sans doublon", [x["ref"] for x in vus.du_fil("fil-A")[1]][:2] == ["aaaa1111bbbb2222", "eeee5555ffff6666"] and len(vus.du_fil("fil-A")[1]) == 3)
fil_courant.set(None)
vus.noter([{"ref": "zzzz", "objet": "hors conversation"}], BOITE)
verifier("hors conversation (tâche de fond), rien n'est noté et rien ne plante", len(vus.du_fil("fil-A")[1]) == 3)

agent = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
gestion = (BACKEND / "skills" / "gestion_mail.py").read_text(encoding="utf-8")
lecture = (BACKEND / "mail" / "lecture.py").read_text(encoding="utf-8")
verifier("les deux lectures notent ce qu'elles ont vu", lecture.count("_noter_vus(") == 3)
verifier("le prompt rappelle les mails vus à chaque tour", "system_prompt += _consigne_mails(state)" in agent and "ne demande JAMAIS qu'on te recite le mail" in agent)
verifier("les gestes de messagerie connaissent leur conversation", all(('"%s"' % k) in agent[agent.index("SKILLS_QUI_CONNAISSENT_LE_FIL"):agent.index("SKILLS_QUI_CONNAISSENT_LE_FIL") + 1600] for k in ("lire_mails", "lire_mail", "modifier_indicateurs_mail")))
verifier("marquer un mail n'exige plus de référence au catalogue, et se rabat sur le mail vu", "requis=[],optionnels=['ref','objet','de'" in gestion and "vus.retrouver(" in gestion)
print(("✗ %d échec(s)" % len(ECHECS)) if ECHECS else "✓ 0 échec")
sys.exit(1 if ECHECS else 0)
