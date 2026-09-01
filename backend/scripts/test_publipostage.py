"""
Banc « un mail à 100 clients = 100 cartes » — le publipostage mécanique, 01/09.

Demande de Noa : des quantités ILLIMITÉES de cartes de mail (100 clients →
100 cartes, sur mesure ou depuis un gabarit), sans que rien ne parte jamais
tout seul. Faire écrire cent cartes par le modèle est impossible (plafond de
sortie) : `mail/publipostage.py` les FABRIQUE depuis un gabarit à variables,
par pages de 40, et le skill `preparer_envois` les affiche en bloc garanti.

Ce banc prouve : la substitution des variables (et [À COMPLÉTER] pour ce qui
manque), le corps sur mesure par destinataire, la pagination sans perte, le
skill déclaré partout (effet lecture, catalogue, journal, prompt), et le
préprompt de chiffrage de la vision (échelle, trois régimes de mesure).
"""
import ast
import importlib.util
import pathlib
import re
import sys

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ PUBLIPOSTAGE ET CHIFFRAGE — {BACKEND.resolve().parent}\n")

spec = importlib.util.spec_from_file_location("publi_banc", BACKEND / "mail" / "publipostage.py")
publi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publi)

dests = [{"email": f"client{i}@ex.fr", "nom": f"Client {i}"} for i in range(100)]
r = publi.construire_cartes("Relance {nom}", "Bonjour {nom},\nvotre devis {reference} attend.", dests)
verifier("100 destinataires → 100 comptés, page 1 de 40 cartes, 3 pages",
         r["nombre"] == 100 and r["pages"] == 3 and len(r["cartes"]) == 40
         and "page=2" in r["pour_continuer"])
c = r["cartes"][0]
verifier("les variables du gabarit ET du sujet sont substituées",
         c["objet"] == "Relance Client 0" and "Bonjour Client 0," in c["reponse"]
         and c["de"] == "client0@ex.fr")
verifier("une variable absente devient [À COMPLÉTER], jamais une invention",
         "[À COMPLÉTER]" in c["reponse"])
r3 = publi.construire_cartes("s", "g", dests, page=3)
verifier("la page 3 rend la FIN (20 cartes), sans pour_continuer",
         len(r3["cartes"]) == 20 and "pour_continuer" not in r3)
sur_mesure = publi.construire_cartes("Objet {nom}", "",
                                     [{"email": "a@b.fr", "nom": "Dupont",
                                       "reponse": "Corps écrit à la main pour Dupont."}])
verifier("un corps SUR MESURE par destinataire prime sur le gabarit",
         sur_mesure["cartes"][0]["reponse"] == "Corps écrit à la main pour Dupont.")
verifier("une adresse nue suffit, un destinataire sans adresse est compté à part",
         publi.construire_cartes("s", "g", ["x@y.fr"])["cartes"][0]["de"] == "x@y.fr"
         and publi.construire_cartes("s", "g", [{"nom": "sans mail"}]).get("sans_adresse") == 1)

skills = (BACKEND / "mail" / "skills.py").read_text(encoding="utf-8")
verifier("le skill preparer_envois existe, effet LECTURE (rien ne part d'ici)",
         'SKILLS_NATIFS["preparer_envois"]' in skills
         and re.search(r'"preparer_envois": "lecture"', skills))
verifier("les cartes partent en bloc reponses_mail GARANTI à l'écran",
         '"type": "reponses_mail"' in skills and '"bloc_garanti"] = True' in skills)
protocole = (BACKEND / "skills" / "protocol.py").read_text(encoding="utf-8")
verifier("le catalogue : sans limite, gabarit à variables, validation par envoi",
         '"preparer_envois": (' in protocole and "sans limite" in protocole
         and "sa validation" in protocole.split('"preparer_envois": (')[1][:700])
agent1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("le prompt nomme `preparer_envois` pour un mail à plusieurs destinataires",
         "`preparer_envois`" in agent1 and "sans limite" in agent1)
verifier("journal : « je prépare les cartes d'envoi »",
         '"preparer_envois"' in (BACKEND / "agents" / "journal.py").read_text(encoding="utf-8"))

agent2 = (BACKEND / "agents" / "agent2.py").read_text(encoding="utf-8")
verifier("le préprompt de chiffrage : inventaire, ÉCHELLE déduite, fourchettes",
         "INVENTAIRE EXHAUSTIF" in agent2 and "ÉCHELLE" in agent2
         and "FOURCHETTE" in agent2 and "DÉDUIRE" in agent2)
verifier("trois régimes de mesure, jamais confondus : LU, ESTIMÉ, NON MESURABLE",
         "mesure LUE se " in agent2 and "ESTIMÉE s'annonce comme telle" in agent2
         and "NON MESURABLE" in agent2)
verifier("plusieurs images se CROISENT (plan + photo), contradictions signalées",
         "CROISE-les" in agent2 and "contradiction" in agent2)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
