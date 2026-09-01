"""
Banc « une demande répétée se refait, un chiffre ne s'estime pas » — 01/09.

Deux relevés de Noa le même jour, une seule racine : le modèle répond de
MÉMOIRE de conversation au lieu de refaire le geste.
  · « fais le point sur les mails » → « cela a déjà été fait tout à l'heure » ;
  · la veille un geste avait compté 66 mails, le lendemain il dit « 70 ».
Ce banc prouve : le prédicat `renvoie_au_deja_fait` reconnaît le renvoi au
passé (et pas une vraie réponse), `demande_sur_le_passe` protège la question
légitime (« as-tu envoyé le mail ? »), le routeur force quand aucun geste n'a
tourné, le prompt porte les deux règles, et la mémoire de conversation dit
que ses chiffres datent — et ne les arrondit plus au résumé.
"""
import importlib.util
import pathlib
import re
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


spec = importlib.util.spec_from_file_location("annonce_banc", BACKEND / "agents" / "annonce.py")
annonce = importlib.util.module_from_spec(spec)
spec.loader.exec_module(annonce)
p = getattr(annonce, "renvoie_au_deja_fait", None)
q = getattr(annonce, "demande_sur_le_passe", None)
print(f"\n═══ REFAIRE ET CHIFFRES EXACTS — {BACKEND.parent}\n")
verifier("le prédicat `renvoie_au_deja_fait` existe", callable(p))
verifier("le prédicat `demande_sur_le_passe` existe", callable(q))
if callable(p):
    verifier("« le point a déjà été fait tout à l'heure » est reconnu",
             p("Le point sur vos mails a déjà été fait tout à l'heure. Souhaitez-vous autre chose ?"))
    verifier("« cette analyse a déjà été réalisée ce matin » est reconnu",
             p("Cette analyse a déjà été réalisée ce matin, vous la trouverez plus haut."))
    verifier("« je vous ai déjà transmis cette liste » est reconnu",
             p("Je vous ai déjà transmis cette liste précédemment."))
    verifier("« je vous l'ai déjà envoyé » est reconnu",
             p("Je vous l'ai déjà envoyé hier en fin de journée."))
    verifier("« comme indiqué précédemment, vous aviez 70 mails » est reconnu (le chiffre de mémoire)",
             p("Comme indiqué précédemment, vous aviez 70 mails hier."))
    verifier("« voir ma réponse précédente » est reconnu",
             p("Reportez-vous à ma réponse précédente pour le détail."))
    verifier("« je viens de faire le point » (sans geste au tour) est reconnu",
             p("Je viens de le faire, le point est au-dessus."))
    verifier("une réponse qui LIVRE n'est pas reconnue",
             not p("Voici le point sur vos mails : 66 messages reçus hier, dont 4 non lus."))
    verifier("« j'ai fait le tri, voici le résultat » n'est pas reconnu",
             not p("J'ai fait le tri et voici le résultat : 12 messages à traiter."))
    verifier("« comme demandé, voici la liste » n'est pas reconnu",
             not p("Comme demandé, voici la liste des clients."))
    verifier("vide → faux", not p("") and not p(None))
if callable(q):
    verifier("« as-tu envoyé le mail à Martin ? » interroge le passé", q("As-tu envoyé le mail à Martin ?"))
    verifier("« est-ce que tu as déjà analysé ce devis ? » interroge le passé",
             q("Est-ce que tu as déjà analysé ce devis ?"))
    verifier("« le mail est-il parti ? » interroge le passé", q("Le mail est-il parti ce matin ?"))
    verifier("« fais le point sur mes mails » n'interroge PAS le passé", not q("Fais le point sur mes mails."))
    verifier("« refais le point sur les mails » n'interroge PAS le passé",
             not q("Refais le point sur les mails de la semaine."))
    verifier("vide → faux", not q("") and not q(None))

agent1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("le routeur applique le prédicat quand aucun geste n'a tourné, sauf question sur le passé",
         re.search(r"deja_fait = \(\s*renvoie_au_deja_fait\(visible\).*?not any\(r\.get\(\"ok\"\).*?"
                   r"demande_sur_le_passe\(state\.get\(\"query\"\)", agent1, re.S))
verifier("le renvoi au déjà-fait repart au forceur (même chemin que la livraison fantôme)",
         "or sans_agir or deja_fait" in agent1)
verifier("le filet se déclare en Console (`renvoi_au_deja_fait`)", '"renvoi_au_deja_fait"' in agent1)
verifier("le prompt : UNE DEMANDE RÉPÉTÉE SE REFAIT, jamais « cela a déjà été fait »",
         "UNE DEMANDE RÉPÉTÉE SE REFAIT" in agent1 and "cela a déjà été fait" in agent1)
verifier("le prompt : UN CHIFFRE SE LIT, IL NE S'ESTIME JAMAIS — un chiffre ancien est périmé",
         "UN CHIFFRE SE LIT, IL NE S'ESTIME JAMAIS" in agent1 and "PÉRIMÉ" in agent1
         and "environ" in agent1)

# La mémoire de conversation : le module s'importe avec un `settings` doublé
# (aucun réglage requis, `_reglage` a ses défauts), et `bloc_memoire` est pur.
sys.modules.setdefault("config", types.SimpleNamespace(settings=types.SimpleNamespace()))
spec_m = importlib.util.spec_from_file_location("memoire_banc",
                                                BACKEND / "agents" / "memoire_conversation.py")
memoire = importlib.util.module_from_spec(spec_m)
spec_m.loader.exec_module(memoire)
bloc = memoire.bloc_memoire("Le 31/08 : 66 mails reçus, 4 non lus.", [])
verifier("le bloc mémoire dit que ses chiffres DATENT et qu'un geste les refait",
         "DATENT" in bloc and "refais le geste" in bloc)
verifier("le bloc mémoire porte toujours le résumé", "66 mails" in bloc)
verifier("la consigne du résumé glissant interdit d'arrondir les chiffres",
         "jamais arrondi" in memoire.CONSIGNE_RESUME)
print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
