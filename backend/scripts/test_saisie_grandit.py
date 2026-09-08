"""
Banc « LA SAISIE GRANDIT AVEC SES LIGNES » — relevé de Noa, troisième fois (08/09).

Deux correctifs avaient été posés SUR LE CHAMP (03/09) : une mesure JavaScript
bornée à quatre lignes, puis `field-sizing: content` là où le navigateur le
sait. Noa a revu le même défaut : une ligne visible, jamais plus. La cause
n'était pas dans le champ. `PromptInput` (AI Elements) enveloppe ses enfants
dans un `InputGroup` (shadcn) qui porte une hauteur FIXE de 36 px (`h-9`) et
`overflow-hidden`, et ne lève cette hauteur (`has-[>textarea]:h-auto`) que si
le textarea est son enfant DIRECT. Dans notre barre, le champ vit dans la
rangée des boutons (`<div class="flex …">`) : la règle ne s'appliquait jamais,
et le conteneur coupait ce que le champ avait grandi.

CE QUE CE BANC PROUVE (contrat, aucun navigateur ici — il le dit) : le piège
est bien présent dans la bibliothèque livrée, le champ n'est bien PAS un
enfant direct du groupe, et `theme.css` porte la règle qui lève la hauteur du
groupe dès qu'il contient un textarea. Tombe sur la version d'avant.
"""
import pathlib
import re
import sys

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
FRONTEND = BACKEND.parent / "frontend"
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ LA SAISIE GRANDIT — {FRONTEND.parent}\n")

groupe = (FRONTEND / "components" / "ui" / "input-group.tsx").read_text(encoding="utf-8")
prompt = (FRONTEND / "components" / "ai-elements" / "prompt-input.tsx").read_text(encoding="utf-8")
barre = (FRONTEND / "components" / "chat" / "InputBar.tsx").read_text(encoding="utf-8")
theme = (FRONTEND / "app" / "theme.css").read_text(encoding="utf-8")

# ── Le piège, tel qu'il est livré ──
verifier("InputGroup porte une hauteur fixe (h-9) qu'il ne lève que pour un textarea ENFANT DIRECT",
         '"h-9 min-w-0 has-[>textarea]:h-auto"' in groupe)
verifier("PromptInput enveloppe ses enfants dans cet InputGroup, en overflow-hidden",
         '<InputGroup className="overflow-hidden">{children}</InputGroup>' in prompt)

# Le textarea de la barre est-il un enfant direct du groupe ? On lit le JSX :
# entre l'ouverture de <PromptInput …> et <PromptInputTextarea, il y a un <div
# ouvert et non refermé — la rangée des boutons.
debut = barre.find("<PromptInput\n")
champ = barre.find("<PromptInputTextarea", debut)
entre = barre[debut:champ]
ouverts = len(re.findall(r"<div\b", entre)) - len(re.findall(r"</div>", entre))
verifier("dans la barre, le champ vit dans une rangée (<div>) : il n'est PAS l'enfant direct du groupe",
         debut > 0 and champ > debut and ouverts >= 1, f"div ouverts non refermés : {ouverts}")

# ── Le correctif ──
regle = re.search(r'\.sym-barre-saisie \[data-slot="input-group"\]:has\(textarea\)\s*\{([^}]*)\}', theme)
verifier("theme.css lève la hauteur du groupe dès qu'il CONTIENT un textarea (`:has(textarea)`, pas `> textarea`)",
         regle is not None)
verifier("…avec `height: auto`", regle is not None and re.search(r"height\s*:\s*auto", regle.group(1)) is not None)
verifier("le commentaire dit où était le plafond (sur le parent, pas sur le champ)",
         "plafond était sur le parent" in theme)

# ── Ce que les correctifs précédents avaient posé reste en place ──
verifier("le champ garde son plafond de lignes (LIGNES_VISIBLES) et son ascenseur",
         "LIGNES_VISIBLES" in barre and "overflowY" in barre)
verifier("le chemin natif (`field-sizing: content`) est toujours là",
         'CSS.supports?.("field-sizing", "content")' in barre)

print("\n  (aucun navigateur ici : la hauteur RENDUE se juge à l'écran — taper trois lignes,"
      " le champ doit grandir jusqu'à quatre puis défiler)")
print(f"\n{'═' * 72}")
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs))
    sys.exit(1)
print("✓ 0 échec")
