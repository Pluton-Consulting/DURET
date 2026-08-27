"""
Banc de la FENÊTRE RÉCENTE — ce que le modèle voit vraiment d'une conversation.

Écrit le 27/08 après un défaut observé à l'écran : « résume-moi tout ce qu'on
s'est dit depuis le début » a répondu « la conversation débute à peine », sur un
fil de ONZE échanges, en présentant au passage les instructions système comme un
message de l'utilisateur.

CE BANC N'A PAS TROUVÉ LA CAUSE, ET C'EST UTILE DE LE DIRE. La fenêtre récente
se comporte correctement sur tous les cas essayés ici : elle garde les échanges
les plus récents, commence par une question, ignore les messages système, tient
son budget, et rend un fil court intact. La piste du budget trop serré a été
explorée puis ABANDONNÉE : la limite qui mord est `optim_history_keep` (16
messages, soit 8 échanges), pas le budget en caractères, puisque chaque message
est déjà taillé à `memoire_message_max_chars`.

Il reste donc ici comme FILET : il fige le comportement actuel, pour qu'un
prochain réglage de ces trois nombres ne dégrade pas la fenêtre sans qu'on le
voie. La cause de l'amnésie observée se cherche dans les journaux du backend,
qui portent déjà la ligne « Historique VIDE alors que le fil porte N messages ».

Ni base, ni réseau, ni LLM : la fonction est pure, on l'exerce directement.

  python3 scripts/test_memoire_fenetre.py backend
"""
import sys, types, pathlib

BACKEND = sys.argv[1] if len(sys.argv) > 1 else "backend"
sys.path.insert(0, BACKEND)

VERT, ROUGE, GRIS, RAZ = "\x1b[92m", "\x1b[91m", "\x1b[90m", "\x1b[0m"
echecs = 0


def controle(titre, ok, detail=""):
    global echecs
    if ok:
        print(f"  {VERT}✓{RAZ} {titre}")
    else:
        echecs += 1
        print(f"  {ROUGE}✗{RAZ} {titre}" + (f"{GRIS} — {detail}{RAZ}" if detail else ""))


# Doublures : le module ne demande que des objets porteurs de `type` et `content`.
class _Msg:
    def __init__(self, type_, content):
        self.type = type_
        self.content = content


# `config` tire pydantic_settings, absent de cette machine : on le double par
# un objet vide, ce qui fait rendre à `_reglage` ses valeurs par défaut — c'est
# exactement la configuration livrée.
faux_config = types.ModuleType("config")
faux_config.settings = types.SimpleNamespace()
sys.modules["config"] = faux_config

faux = types.ModuleType("langchain_core.messages")
faux.HumanMessage = lambda content: _Msg("human", content)
faux.AIMessage = lambda content: _Msg("ai", content)
sys.modules.setdefault("langchain_core", types.ModuleType("langchain_core"))
sys.modules["langchain_core.messages"] = faux

from agents.memoire_conversation import fenetre_recente  # noqa: E402


def fil(nb_echanges: int, taille_reponse: int) -> list:
    """Un fil de N échanges, avec des réponses d'une taille donnée."""
    msgs = []
    for i in range(nb_echanges):
        msgs.append(_Msg("human", f"question numero {i + 1}"))
        msgs.append(_Msg("ai", f"reponse {i + 1} " + "x" * taille_reponse))
    return msgs


print("\n\x1b[1mON PERD DU DÉTAIL, JAMAIS UN ÉCHANGE\x1b[0m\n")

# LE CAS RÉEL : onze échanges dont les réponses sont de gros tableaux.
longs = fil(11, 3000)
fenetre, anciens = fenetre_recente(longs)
humains = [m for m in fenetre if m.type == "human"]
controle("un fil de 11 échanges à réponses longues garde plusieurs échanges",
         len(humains) >= 4, f"{len(humains)} question(s) gardée(s) sur 11")
controle("la fenêtre commence bien par une question",
         bool(fenetre) and fenetre[0].type == "human")
controle("les échanges gardés sont les plus RÉCENTS",
         bool(humains) and "11" in humains[-1].content, 
         humains[-1].content if humains else "(vide)")
controle("le compte des anciens reste cohérent",
         anciens == len(longs) - len(fenetre), f"anciens={anciens}")

# Le détail est perdu — c'est voulu — mais le message reste là.
# Les QUESTIONS sont courtes par nature : on ne juge que les réponses, qui sont
# les seules à subir la taille.
reponses = [len(m.content) for m in fenetre if m.type == "ai"]
controle("chaque réponse gardée est taillée, pas vidée",
         bool(reponses) and all(t >= 200 for t in reponses),
         f"min={min(reponses) if reponses else 0}")
controle("le budget reste tenu malgré le plancher",
         sum(len(m.content) for m in fenetre) <= 16000 * 1.5,
         f"total={sum(len(m.content) for m in fenetre)}")

# Un fil court doit rester INTÉGRAL : le plancher ne doit rien tronquer d'inutile.
courts = fil(3, 200)
f2, a2 = fenetre_recente(courts)
controle("un fil court passe en entier", len(f2) == 6 and a2 == 0, f"{len(f2)} messages, {a2} anciens")
controle("un fil court n'est pas tronqué",
         all("x" * 200 in m.content for m in f2 if m.type == "ai"))

# Les cas limites ne doivent pas casser.
controle("un fil vide rend une fenêtre vide", fenetre_recente([]) == ([], 0))
f3, _ = fenetre_recente([_Msg("ai", "reponse orpheline")])
controle("une réponse sans question n'ouvre pas la fenêtre", f3 == [])
f4, _ = fenetre_recente([_Msg("system", "consigne"), _Msg("human", "salut"), _Msg("ai", "bonjour")])
controle("les messages système sont ignorés",
         len(f4) == 2 and all(m.type != "system" for m in f4))

print()
if echecs:
    print(f"{ROUGE}{echecs} contrôle(s) en échec.{RAZ}")
    sys.exit(1)
print(f"{VERT}Tous les contrôles passent.{RAZ}")
