"""
Banc de L'IMAGE DU FIL — une photo réelle n'est jamais une invention.

LE CAS (export Langfuse de Symbiose, 03/09, 13:07 → 13:47). Une photo jointe
avec « intègre une piscine de 4,5 × 2,2 m » : la vision a rendu une ANALYSE DE
CHIFFRAGE et jamais l'image (le verbe « intègre » n'était pas dans le
vocabulaire de la retouche). Puis « montre moi la photo » : le modèle a écrit
le bloc `visuel` avec la BONNE clé — celle que la vision lui avait donnée — et
deux filets l'ont pris pour une invention : le forceur a relancé (« la photo
est affichée ci-dessus », au-dessus de rien), puis le bloc a été EFFACÉ. À
l'écran : « Voici la photo du jardin : » et le vide.

CAUSE : les deux filets ne connaissaient que les blocs ```ui ÉMIS dans
l'historique, or la vision n'écrivait la référence qu'en texte, entre accents
graves.

CE QUE CE BANC PROUVE, les fonctions du module livré EXÉCUTÉES :
  · une clé connue du fil (historique, photo jointe) ou présente au DÉPÔT est
    reconnue ; une clé inventée ne l'est pas ;
  · « montre moi la photo » avec la vraie clé n'est plus un fantôme ;
  · le vocabulaire de la retouche connaît « intègre », « insère », « implante » ;
  · la vision montre la photo EN BLOC (Symbiose seulement — la retouche est
    son offre ; chez Duret le contrôle est sauté, et dit pourquoi).
"""
import ast
import pathlib
import re
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ L'IMAGE DU FIL — {BACKEND.parent}\n")

# ── LE DÉPÔT DOUBLÉ : il connaît UNE image ────────────────────────────────
CLE_AU_DEPOT = "4f3614bf531f0b1ec4b71121"
CLE_INVENTEE = "dd566702accb8815844deb3b"
CLE_HISTORIQUE = "ab12cd34ef56ab12cd34ef56"
mod_visuels = types.ModuleType("visuels")
mod_depot = types.ModuleType("visuels.depot")
mod_depot._chemin = lambda cle: ("/depot/" + cle) if cle == CLE_AU_DEPOT else None
sys.modules["visuels"] = mod_visuels
sys.modules["visuels.depot"] = mod_depot

# ── LES FONCTIONS DU MODULE LIVRÉ ─────────────────────────────────────────
source = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
arbre = ast.parse(source)
voulu = {"_reference_bloc", "fichiers_du_fil", "cles_images_du_fil", "_image_connue",
         "_montre_un_fichier_du_fil", "_CLE_IMAGE_RE", "_BLOC_UI_RE", "_TYPES_LIVRABLE",
         "_blocs_de", "_re_images"}
gardes = []
for n in arbre.body:
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in voulu:
        gardes.append(n)
    elif isinstance(n, (ast.Assign, ast.AnnAssign)):
        cibles = n.targets if isinstance(n, ast.Assign) else [n.target]
        if any(isinstance(c, ast.Name) and c.id in voulu for c in cibles):
            gardes.append(n)
    elif isinstance(n, ast.Import):
        # `import re as _re_images` et consorts : on garde les alias de `re`
        for a in n.names:
            if a.name == "re":
                gardes.append(ast.Import(names=[a]))
espace = {"re": re, "_re": re, "logger": types.SimpleNamespace(info=lambda *a, **k: None,
                                                                 warning=lambda *a, **k: None),
          "Any": object, "Optional": object, "AgentState": dict}
try:
    exec(compile(ast.fix_missing_locations(ast.Module(body=gardes, type_ignores=[])), "agent1", "exec"), espace)
except Exception as e:  # noqa: BLE001
    print("  ✗ extraction des fonctions impossible :", e)
    sys.exit(1)
manquants = {"_image_connue", "_montre_un_fichier_du_fil", "cles_images_du_fil"} - set(espace)
verifier("les fonctions du filet existent dans le module livré", not manquants, str(manquants))
if manquants:
    sys.exit(1)

image_connue = espace["_image_connue"]
montre = espace["_montre_un_fichier_du_fil"]


def _msg(contenu):
    return types.SimpleNamespace(content=contenu)


# ── 1. UNE CLÉ CONNUE EST RECONNUE, UNE CLÉ INVENTÉE NON ─────────────────
etat_vide = {"messages": [], "tool_results": []}
verifier("une clé présente au DÉPÔT est reconnue, même absente de l'historique",
         image_connue(CLE_AU_DEPOT, etat_vide) is True)
verifier("une clé inventée par le modèle n'est PAS reconnue",
         image_connue(CLE_INVENTEE, etat_vide) is False)
verifier("une clé vide non plus", image_connue("", etat_vide) is False)

etat_hist = {"messages": [_msg('```ui\n{"type": "visuel", "images": [{"cle": "' + CLE_HISTORIQUE + '"}]}\n```')],
             "tool_results": []}
verifier("une clé émise en bloc dans l'historique est reconnue",
         image_connue(CLE_HISTORIQUE, etat_hist) is True)
etat_jointe = {"messages": [], "tool_results": [], "attachment_visuel_cle": "0011223344556677889900aa"}
verifier("la photo jointe À L'INSTANT est reconnue",
         image_connue("0011223344556677889900aa", etat_jointe) is True)

# ── 2. « MONTRE MOI LA PHOTO » N'EST PLUS UN FANTÔME ─────────────────────
reponse_vraie = ('Voici la photo du jardin :\n\n```ui\n{"type":"visuel","titre":"Jardin existant",'
                 '"images":[{"cle":"' + CLE_AU_DEPOT + '"}]}\n```\n\nQue souhaitez-vous en faire ?')
reponse_fausse = reponse_vraie.replace(CLE_AU_DEPOT, CLE_INVENTEE)
verifier("la réponse qui remontre une photo RÉELLE compte comme un fichier du fil",
         montre(reponse_vraie, etat_vide) is True)
verifier("la même réponse avec une clé inventée reste un fantôme",
         montre(reponse_fausse, etat_vide) is False)

# ── 3. LE FILET D'AFFICHAGE : le bloc réel survit, l'inventé s'efface ─────
verifier("_livrables_a_l_ecran exempte l'image connue de l'effacement",
         'if type_ == "visuel" and _image_connue(ref, state):' in source)
verifier("le forceur n'est plus déclenché par un visuel remontré depuis le fil",
         'or (demande_un_visuel(state.get("query") or "") and "?" not in visible\n'
         '                 and not _montre_un_fichier_du_fil(visible, state))' in source)

# ── 4. « INTÈGRE UNE PISCINE » EST UNE RETOUCHE ──────────────────────────
routeur = (BACKEND / "agents" / "router.py").read_text(encoding="utf-8")
debut = routeur.find("_SUITE_ATTENDUE = (")
# Le tuple se ferme sur une ligne à lui seul ; une parenthèse dans un
# commentaire (« (31/08) ») ne doit pas fermer la lecture avant la fin.
bloc = routeur[debut:routeur.find("\n)", debut)]
for mot in ("intègr", "integr", "insèr", "implant", "incrust", "pose ", "place "):
    verifier(f"le vocabulaire de la retouche connaît « {mot.strip()} »", f'"{mot}"' in bloc)

# ── 5. LA VISION MONTRE LA PHOTO EN BLOC (offre visuelle : Symbiose) ─────
agent2 = (BACKEND / "agents" / "agent2.py").read_text(encoding="utf-8")
if "attachment_visuel_cle" in agent2 and "Photo enregistrée sous la référence" in agent2:
    verifier("la vision émet un bloc `visuel` pour la photo reçue (lisible par tous les filets)",
             '\\"type\\": \\"visuel\\", \\"titre\\": \\"Photo de départ\\"' in agent2)
    verifier("le bloc précède la note en texte (le texte seul était invisible des filets)",
             agent2.find('Photo de départ') < agent2.find("Photo enregistrée sous la référence"))
else:
    print("  · (pas d'offre visuelle dans ce projet : la vision ne dépose pas de photo, contrôle sans objet)")

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
