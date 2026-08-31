"""
Banc « agir au lieu de demander » — la réponse relevée par Noa le 31/08.

« Liste toutes les adresses mail que tu as » → « je n'ai pas de commande pour
lister… je peux : 1. chercher sur le Drive 2. vous demander les adresses. Que
préférez-vous ? ». Le geste existait (les boîtes accessibles, l'annuaire du
domaine) ; le modèle a répondu par une question à choix au lieu d'essayer.
Ce banc prouve : le prédicat `propose_au_lieu_d_agir` reconnaît cette réponse
(et pas une vraie clarification), le routeur l'envoie au forceur quand aucun
geste n'a tourné, le skill `boites_mail` existe et le prompt ne dit plus
« pose 2 ou 3 questions » à la première difficulté.
"""
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


spec = importlib.util.spec_from_file_location("annonce_banc", BACKEND / "agents" / "annonce.py")
annonce = importlib.util.module_from_spec(spec)
spec.loader.exec_module(annonce)
p = getattr(annonce, "propose_au_lieu_d_agir", None)
print(f"\n═══ AGIR AU LIEU DE DEMANDER — {BACKEND.parent}\n")
verifier("le prédicat existe", callable(p))
if callable(p):
    prod = ("Je comprends votre demande, mais je n'ai pas de commande pour lister toutes les adresses mail "
            "auxquelles j'ai accès. Ce que je sais, c'est que j'ai accès à toutes les boîtes du domaine.\n\n"
            "Pour obtenir cette liste, je peux :\n\n    Chercher sur le Drive\n    Vous demander de me donner "
            "les adresses qui vous intéressent\n\nQue préférez-vous ?")
    verifier("la réponse EXACTE de prod est reconnue", p(prod))
    verifier("« je n'ai pas d'outil pour … » est reconnu", p("Je n'ai pas d'outil pour consulter l'agenda."))
    verifier("« aucune commande ne me permet de … » est reconnu", p("Aucune commande ne me permet de lister les comptes."))
    verifier("« Voulez-vous que je lance la recherche ? » (offre de faire) est reconnu", p("Voulez-vous que je lance la recherche dans les devis ?"))
    verifier("« Souhaitez-vous que je prépare le mail ? » est reconnu", p("Je peux préparer une réponse. Souhaitez-vous que je la rédige ?"))
    verifier("une vraie clarification n'est PAS reconnue : « à quelle adresse ? »", not p("À quelle adresse dois-je envoyer ce mail ?"))
    verifier("« quel montant faut-il indiquer ? » n'est PAS reconnu", not p("Quel montant faut-il indiquer sur le devis ?"))
    verifier("une réponse qui AGIT n'est pas reconnue", not p("Voici les 12 boîtes mail accessibles : contact@…, benjamin@…"))
    verifier("une question de suite APRÈS un résultat n'est pas visée par le texte seul (le routeur exige « aucun geste »)",
             p("J'ai trouvé 3 devis. Voulez-vous que je les envoie ?"))  # vrai ici, filtré par le routeur
    verifier("vide → faux", not p("") and not p(None))

agent1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("le routeur importe et applique le prédicat quand aucun geste n'a tourné",
         "propose_au_lieu_d_agir" in agent1 and "proposition_sans_acte" in agent1
         and re.search(r"sans_agir = \(.*?propose_au_lieu_d_agir\(visible\).*?not any\(r\.get\(\"ok\"\)", agent1, re.S))
verifier("la réponse repart au forceur (même chemin que la livraison fantôme)", "or fantome or sans_agir" in agent1)
verifier("le prompt : ESSAIE D'ABORD, plus de « pose 2 ou 3 questions » à la première difficulté",
         "Pose 2 ou 3 questions COURTES" not in agent1 and "ESSAIE D'ABORD" in agent1 and "que préférez-vous" in agent1.lower())
verifier("le prompt nomme `boites_mail` pour la liste des boîtes", "`boites_mail`" in agent1)
skills = (BACKEND / "mail" / "skills.py").read_text(encoding="utf-8")
verifier("skill `boites_mail` déclaré, effet lecture, filtré par les droits, annuaire du domaine pour un administrateur",
         'SKILLS_NATIFS["boites_mail"]' in skills and re.search(r'"boites_mail":\s*"lecture"', skills)
         and "boites_visibles(user)" in skills.split("async def boites_mail(")[1][:1500]
         and "boites_du_domaine" in skills.split("async def boites_mail(")[1][:2500])
protocole = (BACKEND / "skills" / "protocol.py").read_text(encoding="utf-8")
verifier("le contrat des actions : PAS BESOIN d'une action du même nom, composer, essayer",
         "PAS BESOIN D'UNE ACTION DU MÊME NOM" in protocole and "composes-en" in protocole
         and "ESSAIE avant de dire que tu ne peux pas" in protocole)
verifier("le forceur : choisir l'action dont le RÉSULTAT contient l'information",
         "presque jamais d'action du MÊME NOM" in agent1 and "s'essaie sans coût" in agent1)
verifier("catalogue : boites_mail", '"boites_mail": (' in protocole and "adresses mail" in protocole.split('"boites_mail": (')[1][:400])
verifier("journal : « je liste les boîtes mail »", '"boites_mail"' in (BACKEND / "agents" / "journal.py").read_text(encoding="utf-8"))
print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
