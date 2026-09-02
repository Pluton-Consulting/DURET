"""
Banc « une seule salve de questions, jamais deux » — 02/09.

Règle de Noa, verbatim : « il faut qu'il soit tout le temps très proactif,
qu'il trouve des solutions de lui-même et qu'il ne fasse pas beaucoup de
demandes avant d'agir : au maximum UN message avec une ou des questions
complémentaires avant d'agir, mais s'il peut y en avoir zéro ou trouver la
réponse tout seul, qu'il le fasse. »

CE QUI EXISTAIT, ET POURQUOI ÇA NE SUFFISAIT PAS. La règle « ESSAIE D'ABORD »
(31/08) et `propose_au_lieu_d_agir` couvrent le cas où l'assistant OFFRE de
faire au lieu de faire : « je n'ai pas de commande pour… que préférez-vous ? ».
Ils ne couvrent PAS la question de clarification, qui est légitime — une fois.

Et c'est là que rien ne tenait : aucune borne sur le NOMBRE de salves. Deux,
trois tours de questions d'affilée passaient tous les filets, parce que chacun
est défendable pris isolément. Le défaut n'est pas dans la réponse, il est dans
sa RÉPÉTITION : deux tours entiers dépensés sans qu'aucun travail n'avance. Il
ne se voit qu'en comparant au tour précédent, et c'est exactement ce que fait
`deuxieme_salve_de_questions`.

Le banc EXÉCUTE les prédicats sur des réponses réalistes, et vérifie le
branchement sur le source. Sans base ni réseau.
"""
import ast
import pathlib
import re
import sys
import unicodedata

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ UNE SEULE SALVE — {BACKEND.resolve().parent}\n")

# Le module livré, exécuté tel quel (il ne dépend de rien).
src = (BACKEND / "agents" / "annonce.py").read_text(encoding="utf-8")
espace: dict = {"re": re, "unicodedata": unicodedata}
exec(compile(src, "annonce", "exec"), espace)
pose = espace["pose_des_questions"]
deux = espace["deuxieme_salve_de_questions"]

# ── 1. RECONNAÎTRE UNE VRAIE DEMANDE DE PRÉCISION ────────────────────────
DEMANDES = [
    "Quelle est l'adresse du destinataire ?",
    "Pouvez-vous me préciser le montant à facturer ?",
    "Souhaitez-vous que je commence par les mails ou par les devis ?",
    "J'ai besoin de savoir sur quelle période porter la recherche.",
    "Merci de me confirmer le nom exact du client ?",
    "Combien de pages dois-je analyser ?",
]
for t in DEMANDES:
    verifier(f"reconnu comme une question : « {t[:46]}… »", pose(t) is True)

# ── 2. NE PAS CONFONDRE AVEC UNE RÉPONSE QUI CONTIENT UN « ? » ───────────
# Une analyse pose souvent des questions rhétoriques qui portent leur réponse.
# Les prendre pour des demandes ferait forcer un tour qui a parfaitement
# travaillé — un filet qui se déclenche à tort est pire que pas de filet.
PAS_DES_DEMANDES = [
    "J'ai trouvé 12 devis. Le plus récent date du 3 avril 2026.",
    "La surface est de 32 m², et pourquoi cet écart ? parce que le plan est coté.",
    "Voici la liste des clients, triée par chiffre d'affaires décroissant.",
    "Le mail est prêt. Vous validerez l'envoi.",
    "",
    "   ",
]
for t in PAS_DES_DEMANDES:
    verifier(f"n'est PAS une demande : « {(t or '(vide)')[:46]}… »", pose(t) is False)

# ── 3. LA PREMIÈRE SALVE RESTE PERMISE, LA SECONDE NON ───────────────────
verifier("UNE question après une réponse qui n'en posait pas : PERMIS",
         deux("Quelle adresse ?", "Voici les 12 devis trouvés.") is False)
verifier("LE CAS DE NOA — deux salves d'affilée : REFUSÉ",
         deux("Quel montant dois-je indiquer ?", "Quelle est l'adresse ?") is True)
verifier("une réponse qui travaille après une question : PERMIS",
         deux("J'ai envoyé la demande, voici le résultat.", "Quelle adresse ?") is False)
verifier("aucun antécédent (premier tour du fil) : PERMIS",
         deux("Quelle adresse ?", "") is False)

# ── 4. LE BRANCHEMENT, LU SUR LE SOURCE ──────────────────────────────────
agent = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("le prédicat est importé", "deuxieme_salve_de_questions)" in agent)
verifier("la dernière réponse de l'assistant est relue dans le fil",
         "def _derniere_reponse_assistant" in agent)
verifier("le filet ne mord QUE si aucun geste n'a tourné",
         "deux_salves = (" in agent
         and 'and not any(r.get("ok") for r in (state.get("tool_results") or []))'
             in agent.split("deux_salves = (")[1][:400])
verifier("ni quand une action attend un accord",
         'and not state.get("pending_action")' in agent.split("deux_salves = (")[1][:500])
verifier("il envoie au FORCEUR, comme les autres filets",
         "or deja_fait or deux_salves)" in agent)
verifier("et il se déclare en Console développeur, en échec du modèle",
         '_tracer_filet(state, "forcage", "deuxieme_salve_de_questions"' in agent)
# L'ORDRE COMPTE : un tour peut cocher plusieurs filets, et deux traces pour un
# même tour rendraient le journal illisible. Chaque filet s'efface devant les
# précédents, comme `deja_fait` s'efface devant `sans_agir`.
verifier("il s'efface devant les filets déjà posés (une trace par tour)",
         "if deux_salves and not fantome and not sans_agir and not deja_fait:" in agent)

# ── 5. LA RÈGLE EST DITE AU MODÈLE, PAS SEULEMENT IMPOSÉE ────────────────
# Un filet rattrape ; il n'apprend rien. La règle au prompt est ce qui fait que
# le cas ne se présente pas — le filet n'est que le dernier recours.
verifier("le prompt borne le nombre de salves",
         "UNE SEULE SALVE DE QUESTIONS, JAMAIS DEUX" in agent)
verifier("il dit de tout demander EN UNE FOIS",
         "pose TOUT ce qui te manque en UN message" in agent)
verifier("il dit où chercher plutôt que de redemander",
         "une adresse est dans l'annuaire" in agent)
verifier("il autorise l'hypothèse, à condition de la DIRE",
         "l'hypothèse la plus raisonnable EN LA DISANT" in agent)
verifier("et il pose la préférence : zéro question d'abord",
         "Zéro question vaut mieux qu'une" in agent)

# Le prédicat doit être déclaré comme les autres, sinon il ne survivra pas au
# prochain nettoyage d'imports.
arbre = ast.parse(src)
noms = {n.name for n in arbre.body if isinstance(n, ast.FunctionDef)}
verifier("les deux prédicats sont exposés par le module",
         {"pose_des_questions", "deuxieme_salve_de_questions"} <= noms)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
