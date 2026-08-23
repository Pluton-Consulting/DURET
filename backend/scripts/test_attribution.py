"""
Banc de l'attribution d'expert — sans base ni réseau.

POURQUOI. Le graphe exécute presque tout dans agent1 : les skills de conception
(visuels) y tournent aussi, et `threads.agent_type` restait figé à « agent1 ».
Résultat à l'écran : la carte « plans & visuels » à zéro, son historique vide
pour toujours, les demandes d'accord attribuées au mauvais expert. Le correctif
tient en trois pièces : la déclaration d'un skill porte son `expert`, le tour
est réattribué quand un tel skill travaille, et le fil suit l'expert effectif.

Ce banc vérifie la mécanique du registre EN VRAI (import isolé, cache injecté)
et la présence des branchements dans les fichiers livrés (contrôles statiques,
comme l'audit du 22/08) : il teste le code tel qu'il partira, pas une doublure.
"""
import importlib.util
import pathlib
import sys

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")

echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ ATTRIBUTION D'EXPERT — {BACKEND}\n")

# ── 1. La mécanique du registre, exécutée pour de vrai ───────────────
spec = importlib.util.spec_from_file_location("registre_banc", BACKEND / "skills" / "registre.py")
registre = importlib.util.module_from_spec(spec)
# Inscrit AVANT l'exécution : les dataclasses (Python 3.9) relisent le module
# dans sys.modules pour résoudre les annotations — sans cela, l'import isolé plante.
sys.modules["registre_banc"] = registre
spec.loader.exec_module(registre)

print("1. Le registre : le champ `expert` et son accesseur")
d_conception = registre.Declaration(fonction=None, description="essai", expert="agent2")
d_ordinaire = registre.Declaration(fonction=None, description="essai")
verifier("une déclaration sans expert reste muette (défaut vide)", d_ordinaire.expert == "")
registre._CACHE = {"generer_visuel": d_conception, "lire_mails": d_ordinaire}
verifier("expert('generer_visuel') rend agent2", registre.expert("generer_visuel") == "agent2")
verifier("expert d'un skill sans déclaration d'expert rend None", registre.expert("lire_mails") is None)
verifier("expert d'un skill inconnu rend None", registre.expert("inconnu") is None)

# ── 2. Les branchements, dans les fichiers livrés ────────────────────
print("\n2. Les branchements (contrôles statiques sur les fichiers livrés)")


def source(chemin):
    return (BACKEND / chemin).read_text(encoding="utf-8")


executor = source("skills/executor.py")
verifier("executor : expert_du_skill existe", "def expert_du_skill(" in executor)
verifier("executor : il lit la déclaration du registre",
         "from skills.registre import expert as expert_declare" in executor)

agent1 = source("agents/agent1.py")
verifier("agent1 : expert_du_skill importé", "expert_du_skill" in agent1)
verifier("agent1 : l'ARMEMENT d'une validation porte l'expert",
         'armement["target_agent"] = exp' in agent1)
verifier("agent1 : une action RÉUSSIE porte l'expert", 'maj["target_agent"] = exp' in agent1)

routeur = source("agents/router.py")
verifier("router : le chemin post-validation porte l'expert",
         'sortie["target_agent"] = exp' in routeur)

chat = source("routers/chat.py")
verifier("chat : _actualiser_expert existe", "async def _actualiser_expert(" in chat)
verifier("chat : appelé sur le chemin POST et sur le WebSocket",
         chat.count("await _actualiser_expert(") == 2,
         f"{chat.count('await _actualiser_expert(')} appel(s)")
verifier("chat : montée seule — agent1 ne réécrit jamais un fil",
         'if agent_used in (None, "", "agent1"):' in chat)
verifier("chat : l'expert effectif se lit sur TOUS les nœuds du flux",
         'cible = (event.get("data") or {}).get("target_agent")' in chat)
verifier("chat : un PDF de plan quasi sans texte part à la vision",
         'structure["kind"] != "tabulaire"' in chat and "< 300" in chat)

validation = source("routers/validation.py")
verifier("validation : le fil suit l'expert après une reprise",
         "agent_apres" in validation and "agent_type IS DISTINCT FROM" in validation)

# ── 3. Les skills de conception du projet, s'il en a ─────────────────
visuels = BACKEND / "skills" / "visuels.py"
if visuels.exists():
    print("\n3. Les visuels (module propre au projet)")
    contenu = visuels.read_text(encoding="utf-8")
    nb = contenu.count('expert="agent2"')
    verifier("les 4 skills visuels déclarent expert=agent2", nb == 4,
             f"{nb} déclaration(s)")
else:
    print("\n3. Pas de module de conception propre au projet : rien à déclarer, mécanique en place")

print(f"\n═══ {len(echecs)} échec(s)" + (f" : {', '.join(echecs)}" if echecs else " — tout passe"))
sys.exit(1 if echecs else 0)
