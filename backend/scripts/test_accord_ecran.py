"""
Banc « L'ACCORD ET SON RÉSULTAT À L'ÉCRAN » — trois relevés de Noa du 07/09 :

  1. « dès que le bouton est validé dans le chat, il doit y avoir marqué
     "résultat en cours…" pour combler le délai d'affichage de la réponse » ;
  2. « quand il lance la modification d'une image, il affiche en grand l'image
     de départ et, en petit dessous, encore l'image de départ et le rendu final
     à droite — il devrait afficher en grand l'image finale et en dessous
     l'avant / après » ;
  3. « il ne doit pas afficher le texte de modification anglais ».

CE QUE CE BANC PROUVE (sans navigateur, sans base, sans modèle) :
  · la bulle d'accord du fil est ATTACHÉE à sa validation (`accord:<id>`) et
    passe à « Résultat en cours… » dès le clic, sur tous les chemins qui la
    posent (WebSocket, repli POST, tour détaché, rechargement) ; la réponse la
    remplit ; un échec la remet en attente ;
  · `_apercu_avant_accord` (EXÉCUTÉ) ne recopie plus le brief anglais ;
  · après l'exécution, le brouillon (photo de départ en grand) ne survit pas
    au résultat quand le skill rend un bloc `visuel` ; le rédacteur ne reçoit
    plus `changements` ; `resultat` existe sur tous les chemins ;
  · la planche sait montrer une image PRINCIPALE en grand, la paire légendée
    en dessous, sans télécharger deux fois le rendu ; le renderer la transmet.

La construction du bloc (`principale` = le rendu) est éprouvée par
`test_demo.py` chez Symbiose, qui exécute `modifier_visuel` : cette offre
n'existe pas chez Duret, le banc ne l'exige donc pas ici.

Tombe sur la version d'avant.
"""
import ast
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
FRONTEND = BACKEND.parent / "frontend"
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ L'ACCORD ET SON RÉSULTAT À L'ÉCRAN — {BACKEND.parent}\n")

# ══════════════════════════════════════════════════════════════════════════
# 1. « RÉSULTAT EN COURS… » DÈS LE CLIC
# ══════════════════════════════════════════════════════════════════════════
print("── 1. Le clic sur « Approuver »")
chatwin = (FRONTEND / "components" / "chat" / "ChatWindow.tsx").read_text(encoding="utf-8")

verifier("la bulle d'accord est attachée à sa validation (`accord:<id>`)",
         "const cleAccord = (id?: string | null) => (id ? `accord:${id}` : null)" in chatwin
         and "const bulleAccord = (validationId?: string | null) =>" in chatwin)
verifier("tous les chemins qui posaient la bulle générique passent par `bulleAccord`",
         'pushAssistant("⏳ Une action attend votre accord' not in chatwin
         and chatwin.count("bulleAccord(") >= 4)
verifier("dès le clic, la bulle dit « Résultat en cours… » (tâche liée OU bulle du fil)",
         'const TEXTE_RESULTAT_EN_COURS = "Résultat en cours…"' in chatwin
         and "if (liee) majBulle(liee.id, TEXTE_RESULTAT_EN_COURS)" in chatwin
         and "majBulle(cle, TEXTE_RESULTAT_EN_COURS)" in chatwin)
verifier("…seulement si l'accord est DONNÉ (un refus n'attend aucun résultat)",
         "if (accorde) {\n      if (liee) majBulle(liee.id, TEXTE_RESULTAT_EN_COURS)" in chatwin)
verifier("la réponse remplit la bulle du fil quand aucune tâche n'est liée",
         "else if (tachesSuiviesRef.current.has(cle)) poserReponse(cle, texte)" in chatwin)
verifier("un échec de la décision remet la bulle en attente d'accord",
         "else if (tachesSuiviesRef.current.has(cle)) majBulle(cle, TEXTE_ATTENTE_ACCORD)" in chatwin)
verifier("une décision déjà prise (409) ferme la bulle au lieu de la laisser battre",
         'poserReponse(cle, "Cette action a déjà été tranchée.")' in chatwin)
verifier("la tâche liée est cherchée AVANT la requête (elle sert au clic ET à la réponse)",
         chatwin.index("const liee = tachesFile.find((t) => t.validationId === id)")
         < chatwin.index("`/api/validations/${id}/resolve`"))

# ══════════════════════════════════════════════════════════════════════════
# 2. LA CARTE D'ACCORD NE RECOPIE PLUS LE BRIEF ANGLAIS
# ══════════════════════════════════════════════════════════════════════════
print("\n── 2. La carte d'accord")
src_a1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
arbre = ast.parse(src_a1)
espace = {"logger": types.SimpleNamespace(info=lambda *a, **k: None)}
for n in arbre.body:
    if isinstance(n, ast.FunctionDef) and n.name == "_apercu_avant_accord":
        exec(compile(ast.Module([n], []), "agent1.py", "exec"), espace)
apercu = espace["_apercu_avant_accord"]
CLE = "bf08dcefbd22f64bc286e066"
carte = apercu("modifier_visuel", {"image": CLE, "changements": "remove the two olive trees "
                                   "in front of the house, keep everything else identical"},
               "Je retire les deux oliviers devant la façade.")
verifier("la carte montre la photo qui sera retouchée", CLE in carte and '"type": "visuel"' in carte)
verifier("le texte du modèle (en français) reste en tête", carte.startswith("Je retire les deux oliviers"))
verifier("le brief ANGLAIS du moteur d'images n'y est plus",
         "olive trees" not in carte and "Ce qui change" not in carte)
verifier("ce qui ne change pas est toujours dit", "conservé à l'identique" in carte)

# ══════════════════════════════════════════════════════════════════════════
# 3. APRÈS L'EXÉCUTION : le résultat remplace le brouillon
# ══════════════════════════════════════════════════════════════════════════
print("\n── 3. Après l'exécution")
src_r = (BACKEND / "agents" / "router.py").read_text(encoding="utf-8")
verifier("`resultat` existe sur tous les chemins (plus de NameError avalé sur un échec)",
         "resultat = None\n    try:\n        resultat = await execute_skill(" in src_r)
verifier("quand le skill rend un bloc `visuel`, le brouillon (photo de départ) ne survit pas",
         'b.get("type") == "visuel" for b in _blocs_de_resultat(_sortie_skill.get("bloc_ui"))' in src_r
         and 'precedent = ""' in src_r
         and '"final_response": (precedent + f"\\n\\n{message}").strip()' in src_r)
verifier("les autres actions gardent leur brouillon (un mail parti reste lisible)",
         'precedent = (state.get("final_response") or "").rstrip()' in src_r)
verifier("le rédacteur ne reçoit plus le brief anglais ni les clés de dépôt",
         '"changements", "source", "cles"' in src_r)

# ══════════════════════════════════════════════════════════════════════════
# 4. LA PLANCHE : le rendu en grand, l'avant / après en dessous
# ══════════════════════════════════════════════════════════════════════════
print("\n── 4. La planche")
planche = (FRONTEND / "components" / "blocks" / "business" / "VisuelPaysager.tsx").read_text(encoding="utf-8")
renderer = (FRONTEND / "components" / "chat" / "MessageRenderer.tsx").read_text(encoding="utf-8")
verifier("la planche accepte une image PRINCIPALE", "principale?: string" in planche
         and "const grande = principale ? liste.find((i) => i.cle === principale) : undefined" in planche)
verifier("elle se montre en grand, AVANT la paire", 'data-testid="visuel-principal"' in planche
         and planche.index('data-testid="visuel-principal"') < planche.index("gridTemplateColumns: liste.length > 1"))
verifier("la paire garde ses légendes (Avant / Après) sous chaque image",
         "{grande && img.legende && (" in planche)
verifier("« Tout télécharger » ne sort pas le rendu deux fois",
         "enregistrer={!grande || img.cle !== principale}" in planche
         and "if (etat === \"pret\" && blob.current && enregistrer) surBlob(index, telecharger)" in planche)
verifier("sans image principale, rien ne change (essai, tirage simple)",
         "{grande && (" in planche)
verifier("le renderer transmet `principale` au bloc", "principale={p.principale}" in renderer)

# ══════════════════════════════════════════════════════════════════════════
print(f"\n{'═' * 72}")
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs))
    sys.exit(1)
print("✓ 0 échec")
