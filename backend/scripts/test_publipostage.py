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
# 03/09 : TOUTES les cartes d'un coup — la pagination du skill ne servait qu'à
# multiplier les blocs (neuf appels, six blocs, 207 cartes pour 95 clients).
# C'est l'écran qui pagine. La borne reste, très haute.
verifier("100 destinataires → 100 comptés, 100 cartes, UNE page",
         r["nombre"] == 100 and r["pages"] == 1 and len(r["cartes"]) == 100)
verifier("la borne du skill est haute (mille), et l'écran pagine",
         publi.PAR_PAGE >= 500)
c = r["cartes"][0]
verifier("les variables du gabarit ET du sujet sont substituées",
         c["objet"] == "Relance Client 0" and "Bonjour Client 0," in c["reponse"]
         and c["de"] == "client0@ex.fr")
verifier("une variable absente devient [À COMPLÉTER], jamais une invention",
         "[À COMPLÉTER]" in c["reponse"])
# La borne existe toujours (pour un tableau de dix mille lignes) : on la
# force à 40 pour l'exercer, puisque le défaut ne pagine plus 100 destinataires.
r3 = publi.construire_cartes("s", "g", dests, page=3, par_page=40)
verifier("au-delà de la borne, la page 3 rend la FIN (20 cartes), sans pour_continuer",
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
         # 04/09 : l'entrée s'est allongée (`@tableau`, `personnaliser`) — la fenêtre suit.
         and "sa validation" in protocole.split('"preparer_envois": (')[1][:1400])
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


# ── 03/09 : LA QUANTITÉ SANS DOUBLON ─────────────────────────────────────
# Export Langfuse de 15:00 : `{Nom ?}` (l'en-tête EXACT du tableau) n'était pas
# reconnu comme variable → 95 mails avec « {Nom ?} » en clair → envoi refusé →
# le modèle a rappelé le skill neuf fois avec d'autres graphies → six blocs à
# l'écran, 207 cartes.
verifier("`{Nom ?}` — n'importe quel en-tête entre accolades — est une variable",
         publi._substituer("Bonjour {Prénom} {Nom ?}", {"Prénom": "Karine", "Nom ?": "ASTRUC"})
         == "Bonjour Karine ASTRUC")
verifier("`{prenom}` retrouve « Prénom » (accents, casse, ponctuation ignorés)",
         publi._substituer("{prenom}", {"Prénom": "Karine"}) == "Karine")
verifier("les variables disponibles sont dites au modèle (il n'a plus à deviner)",
         publi.variables_de([{"Prénom": "a", "Nom ?": "b", "E-mail": "c", "Colonne AG": "d"}])
         == ["prenom", "nom", "email"])
agent1_src = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("UN SEUL bloc de cartes par message : le dernier remplace les précédents",
         'uniques = ("reponses_mail",)' in agent1_src
         and "[du_genre[-1]]" in agent1_src)
verifier("un bloc de cartes recopié par le modèle cède la place au bloc mécanique",
         '"bloc_unique_recopie"' in agent1_src)
skills_src = (BACKEND / "mail" / "skills.py").read_text(encoding="utf-8")
verifier("la consigne interdit de rappeler le skill dans le tour (un rappel REMPLACE)",
         "NE RAPPELLE PAS ce skill dans ce tour" in skills_src)
verifier("elle explique « [À COMPLÉTER] » au lieu de laisser le modèle réessayer",
         "N'essaie pas d'autres noms de variables" in skills_src
         and "cartes_avec_manque" in skills_src)
verifier("elle nomme les variables reconnues", "Variables reconnues pour ces destinataires" in skills_src)


# ── 04/09 : LA PERSONNALISATION PAR L'HISTORIQUE, un travail de skill ─────
# Export de 18:48 : « adapte les 95 mails, lis l'historique de chaque client »
# → un plan, un Excel, des recherches Drive, jamais les mails. 95 lectures de
# boîte en chaîne ne sont pas une boucle de modèle : le skill les fait.
verifier("l'historique d'un destinataire se résume en quelques lignes lisibles",
         publi.historique_en_texte([{"objet": "Devis terrasse", "apercu": "Bonjour, suite à notre visite…",
                                     "date": "2026-04-14", "dossier": "envoyes"}])
         == "- 2026-04-14 (envoyé) « Devis terrasse » : Bonjour, suite à notre visite…")
verifier("au plus six messages, jamais l'archive entière",
         publi.historique_en_texte([{"objet": f"m{i}"} for i in range(20)]).count("\n") == 5)
verifier("la consigne du rédacteur interdit d'inventer (chantier, montant, date)",
         "N'INVENTE RIEN" in publi.CONSIGNE_PERSONNALISATION and "[À COMPLÉTER]" in publi.CONSIGNE_PERSONNALISATION)
verifier("le skill sait personnaliser (lecture de la boîte, reçus ET envoyés, trois de front)",
         "async def _personnaliser_cartes" in skills_src and 'for dossier in ("recus", "envoyes")' in skills_src
         and "asyncio.Semaphore(3)" in skills_src)
verifier("le catalogue nomme `personnaliser` comme LE geste d'une adaptation par client",
         "`personnaliser: true` ADAPTE" in (BACKEND / "skills" / "protocol.py").read_text(encoding="utf-8")
         and "pas une lecture de mails par client" in (BACKEND / "skills" / "protocol.py").read_text(encoding="utf-8"))
verifier("le catalogue ne dit plus « pages de 40 : enchaîne »",
         "pages de 40" not in (BACKEND / "skills" / "protocol.py").read_text(encoding="utf-8"))

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
