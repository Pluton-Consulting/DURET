"""
Banc « LES IMAGES NE SE MENTIONNENT QUE LÀ OÙ ELLES EXISTENT » (08/09).

Demande de Noa : « pour Duret, enlève toutes mentions de génération d'images ».
L'offre visuelle (moteur `visuels/nano_banana.py`, skills `*_visuel`) n'existe
que chez Symbiose ; pourtant le socle en parlait des deux côtés : la consigne
des images ordonnait d'appeler `modifier_visuel`, la vision promettait « je
peux produire une variante », Paramètres montrait un modèle d'images « choix
arrêté », le tableau de bord nommait « L'expert plans & visuels ». Chez Duret,
tout cela décrivait une chose qui ne tourne pas.

CE QUE CE BANC PROUVE, DES DEUX CÔTÉS AVEC LE MÊME FICHIER : chaque mention
suit la PRÉSENCE RÉELLE du moteur et du skill (le registre et le module font
foi, pas un drapeau). Là où l'offre existe, la consigne de retouche reste
entière ; là où elle n'existe pas, rien ne la promet. Les fonctions sont
EXÉCUTÉES contre un registre doublé dans les deux configurations. Tombe sur la
version d'avant.
"""
import pathlib
import re
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
FRONTEND = BACKEND.parent / "frontend"
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


OFFRE_VISUELLE = (BACKEND / "visuels" / "nano_banana.py").exists()
print(f"\n═══ LES IMAGES SELON L'OFFRE — {BACKEND.parent}  "
      f"(moteur d'images : {'PRÉSENT' if OFFRE_VISUELLE else 'ABSENT'})\n")


def _extraire(source: str, debut: str, fin: str) -> str:
    """Le texte d'une ou plusieurs fonctions, de `debut` (inclus) à `fin` (exclu)."""
    i = source.find(debut)
    j = source.find(fin, i + 1)
    if i < 0 or j < 0:
        return ""
    return source[i:j]


def _registre(avec_retouche: bool):
    """Un `skills.registre` doublé : `fonction(nom)` rend quelque chose ou None."""
    mod = types.ModuleType("skills.registre")
    mod.fonction = lambda nom: (lambda: None) if (avec_retouche and nom == "modifier_visuel") else None
    sys.modules["skills"] = types.ModuleType("skills")
    sys.modules["skills.registre"] = mod


# ── 1. agent1 : la consigne des images EXÉCUTÉE dans les deux configurations ──
agent1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
code = _extraire(agent1, "def _retouche_disponible", "async def forcer_action_node")
verifier("agent1 porte `_retouche_disponible` puis `_consigne_images` (le registre fait foi)",
         "def _retouche_disponible" in code and "def _consigne_images" in code)
if code:
    for avec in (True, False):
        _registre(avec)
        esp = {"cles_images_du_fil": lambda state: ["abc123", "def456"], "AgentState": dict}
        exec(compile(code, "agent1_extrait", "exec"), esp)
        consigne = esp["_consigne_images"]({})
        if avec:
            verifier("AVEC le skill : la consigne ordonne `modifier_visuel` et garde ses deux références",
                     "modifier_visuel" in consigne and "abc123" in consigne and "def456" in consigne)
            verifier("AVEC le skill : la règle « une demande qui CHANGE l'image est un appel » reste",
                     "TOUTE demande qui CHANGE" in consigne)
        else:
            verifier("SANS le skill : la consigne ne nomme ni `modifier_visuel`, ni retouche, ni variante",
                     "modifier_visuel" not in consigne and "RETOUCHER" not in consigne
                     and "variante" not in consigne, consigne)
            verifier("SANS le skill : les références restent (remontrer une photo est légitime)",
                     "abc123" in consigne and "def456" in consigne and "visuel" in consigne)
            verifier("SANS le skill : la consigne dit qu'aucune génération n'est possible ici",
                     "Aucune retouche ni génération d'image" in consigne)
    # Sans registre du tout (import qui échoue) : on n'en parle pas.
    sys.modules.pop("skills.registre", None)
    sys.modules["skills"] = types.ModuleType("skills")
    esp = {"cles_images_du_fil": lambda state: ["abc123"], "AgentState": dict}
    exec(compile(code, "agent1_extrait", "exec"), esp)
    verifier("registre indisponible : traité comme « pas de retouche », sans exception",
             "modifier_visuel" not in esp["_consigne_images"]({}))

# ── 2. agent2 : la vision ne promet une variante que si la retouche existe ──
agent2 = (BACKEND / "agents" / "agent2.py").read_text(encoding="utf-8")
verifier("agent2 porte `_retouche_disponible` (même règle, même source de vérité)",
         "def _retouche_disponible" in agent2 and 'fonction("modifier_visuel")' in agent2)
bloc = _extraire(agent2, "        if mode_reponse:\n            pass", "    # CE QUE LA VISION A LU")
verifier("« je peux produire une variante » n'est écrit QUE derrière `_retouche_disponible()`",
         "elif not _retouche_disponible():" in bloc
         and bloc.find("elif not _retouche_disponible():") < bloc.find("produire une variante"))
verifier("sans retouche, la référence de la photo est quand même dite (les filets la lisent)",
         "Photo enregistrée sous la référence" in bloc.split("elif len(photos) == 1")[0])

# ── 3. Paramètres : le modèle d'images suit la présence du moteur (EXÉCUTÉ) ──
settings_src = (BACKEND / "routers" / "settings.py").read_text(encoding="utf-8")
fn = _extraire(settings_src, "def _moteur_images_present", "@router.get(\"/modeles\")")
verifier("settings.py porte `_moteur_images_present` (le module fait foi)", bool(fn))
if fn:
    # Le paquet `visuels` doublé pointe sur le VRAI dossier livré : find_spec dit
    # la vérité de ce dépôt, sans importer le reste du backend.
    paquet = types.ModuleType("visuels")
    paquet.__path__ = [str(BACKEND / "visuels")]
    sys.modules["visuels"] = paquet
    esp = {}
    exec(compile(fn, "settings_extrait", "exec"), esp)
    present = esp["_moteur_images_present"]()
    verifier(f"`_moteur_images_present()` rend {OFFRE_VISUELLE} sur ce dépôt (le moteur est "
             f"{'là' if OFFRE_VISUELLE else 'absent'})", present is OFFRE_VISUELLE, present)
    paquet.__path__ = [str(BACKEND / "visuels_inexistant")]
    verifier("sans le dossier du moteur, il rend False", esp["_moteur_images_present"]() is False)
verifier("`modele_image` n'entre dans la réponse de /modeles que si le moteur est présent",
         re.search(r'\*\*\(\{"modele_image":.*?\}\} if _moteur_images_present\(\) else \{\}\)',
                   settings_src, re.S) is not None)
cles_tab = (FRONTEND / "components" / "settings" / "ClesApiTab.tsx").read_text(encoding="utf-8")
verifier("l'écran tait la carte quand la réponse ne porte pas `modele_image`",
         "{image && (" in cles_tab and "modele_image || null" in cles_tab)

# ── 4. Les libellés d'écran viennent de la donnée par client ──
tableau = (FRONTEND / "components" / "tableau" / "TableauDeBord.tsx").read_text(encoding="utf-8")
verifier("le tableau de bord ne recopie plus les noms d'experts en dur (il lit EXPERTS)",
         "EXPERTS.map((e) => [e.cle" in tableau and '"L\'expert plans & visuels"' not in tableau)
file_attente = (FRONTEND / "components" / "chat" / "FileAttente.tsx").read_text(encoding="utf-8")
verifier("l'attente après accord ne parle plus de « visuel »",
         "Un visuel ou un envoi" not in file_attente)
routeur = (BACKEND / "agents" / "router.py").read_text(encoding="utf-8")
verifier("la passe de main nomme l'expert par ce qu'il fait, pas par une offre",
         "qui lit les plans et les photos" in routeur and 'f"plans & visuels :' not in routeur)

# ── 5. Là où l'offre n'existe pas : plus une mention à l'écran ni au modèle ──
if not OFFRE_VISUELLE:
    permissions = (FRONTEND / "lib" / "permissions.ts").read_text(encoding="utf-8")
    frise = (FRONTEND / "components" / "chat" / "ReasoningPath.tsx").read_text(encoding="utf-8")
    page = (FRONTEND / "app" / "(app)" / "conception" / "page.tsx").read_text(encoding="utf-8")
    nas = (BACKEND / "skills" / "nas.py").read_text(encoding="utf-8")
    prompt1 = _extraire(agent1, "SYSTEM_PROMPT", "\ndef ")
    verifier("les experts (permissions.ts) ne portent pas « visuel »", "visuel" not in permissions.lower())
    frise_code = "\n".join(l for l in frise.splitlines() if not l.strip().startswith("//"))
    verifier("la frise « En coulisses » ne porte pas « visuel » (hors commentaires)", "visuel" not in frise_code.lower())
    verifier("la page Conception ne titre plus « Visuels »", "Visuels" not in page)
    verifier("`nas_photos` ne parle ni de rendu généré ni de simulation",
             "genere" not in nas and "images générées" not in nas and "simulation" not in nas)
    verifier("le prompt de l'assistant ne cite ni « produire un visuel » ni la pierre naturelle",
             "produire un visuel" not in prompt1 and "pierre naturelle" not in prompt1)
else:
    permissions = (FRONTEND / "lib" / "permissions.ts").read_text(encoding="utf-8")
    verifier("là où l'offre existe, l'expert plans & visuels garde son nom", "plans & visuels" in permissions)

print(f"\n{'═' * 72}")
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs))
    sys.exit(1)
print("✓ 0 échec")
