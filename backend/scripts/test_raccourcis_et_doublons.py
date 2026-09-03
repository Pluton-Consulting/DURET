"""
Banc des raccourcis et des doublons — trois demandes de Noa du 31/08 au soir.

« Des fois il met deux composants visuels différents mais pour le même
contenu » → `_dedoublonner_blocs` (le contenu fait la signature, pas la forme).
« Un petit menu au-dessus de la saisie avec les process qu'on fait souvent »
→ raccourcis de l'InputBar (préremplissent, n'envoient pas). « Les réponses
proposées dans des cartes horizontales, validées en une fois » → bloc
`reponses_mail` (le bouton écrit dans le chat ; chaque envoi repasse par la
validation). Et la voie rapide du routeur ne s'applique qu'à une SUITE :
un premier message, même court, passe par le juge.
"""
import ast
import pathlib
import re
import sys

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
FRONTEND = BACKEND.parent / "frontend"
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ RACCOURCIS ET DOUBLONS — {BACKEND.parent}\n")
print("1. Le dédoublonnage des blocs (agents/agent1.py)")
agent1_src = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
espace: dict = {"_re_livrables": re, "_BLOC_UI_RE": re.compile(r"```ui\s*(\{.*?\})\s*```", re.S)}
try:
    arbre = ast.parse(agent1_src)
    for noeud in arbre.body:
        if isinstance(noeud, ast.FunctionDef) and noeud.name in ("_signature_bloc", "_dedoublonner_blocs", "_plat_nom"):
            exec(compile(ast.Module([noeud], []), "agent1", "exec"), espace)  # noqa: S102
    dedup = espace["_dedoublonner_blocs"]

    def ui(d):
        import json
        return "```ui\n" + json.dumps(d, ensure_ascii=False) + "\n```"

    email = {"type": "email", "subject": "Devis terrasse", "from": "client@ext.fr", "date": "2026-08-31"}
    meme_email = {"type": "email", "from": "client@ext.fr", "date": "2026-08-31", "subject": "Devis terrasse", "preview": "Bonjour…"}
    t = dedup("Voici :\n\n" + ui(email) + "\n\n" + ui(meme_email))
    verifier("deux cartes `email` du même message → une seule (l'ordre des clés est indifférent)", t.count("```ui") == 1 and "Voici :" in t)
    table = {"type": "table", "columns": ["Client", "CA"], "rows": [["Pereire", "12 000"], ["Moulleau", "8 500"]]}
    kv = {"type": "keyvalue", "rows": [["Pereire", "12 000"], ["Moulleau", "8 500"], ["Client", "CA"]]}
    verifier("un `table` et un `keyvalue` qui portent les MÊMES valeurs → un seul (le contenu fait la signature)",
             dedup(ui(table) + "\n\n" + ui(kv)).count("```ui") == 1)
    autre = {"type": "table", "columns": ["Client", "CA"], "rows": [["Pereire", "12 000"], ["Cap Ferret", "3 000"]]}
    verifier("deux contenus différents restent deux blocs", dedup(ui(table) + "\n\n" + ui(autre)).count("```ui") == 2)
    fichier = {"type": "fichier", "url": "/api/documents/abc", "nom": "clients.xlsx", "titre": "clients"}
    doc = {"type": "doc", "name": "Clients.XLSX"}
    verifier("une vignette `doc` du même fichier que la carte `fichier` disparaît",
             dedup(ui(fichier) + "\n\n" + ui(doc)).count("```ui") == 1)
    qr = {"type": "quick_replies", "options": ["Oui", "Non"]}
    # 01/09 : ce contrôle s'est RETOURNÉ. Depuis que les suggestions sont
    # posées mécaniquement (agents/suggestions.py), deux rangées de pastilles
    # pouvaient se retrouver dans le même message — une du modèle, une du
    # filet. Une rangée reste hors du dédoublonnage par CONTENU (elle ne doit
    # jamais effacer un tableau qui répète ses mots), mais un message n'en
    # porte qu'UNE : la première.
    verifier("deux rangées de pastilles : la première seule survit",
             dedup(ui(qr) + "\n\n" + ui(qr)).count("```ui") == 1)
    _tab = {"type": "table", "colonnes": ["Oui"], "lignes": [["Non"]]}
    verifier("une rangée de pastilles n'efface pas un tableau qui partage ses mots",
             dedup(ui(qr) + "\n\n" + ui(_tab)).count("```ui") == 2)
    verifier("un bloc illisible est gardé tel quel", "```ui" in dedup("```ui\n{cassé\n```"))
    verifier("un texte sans bloc ressort intact", dedup("Bonjour, rien à signaler.") == "Bonjour, rien à signaler.")
except Exception as e:  # noqa: BLE001
    verifier("le dédoublonnage s'exécute", False, repr(e))
verifier("il est appliqué au rendu final (rehydrate), après le filet des livrables",
         "_dedoublonner_blocs(text)" in agent1_src
         and agent1_src.index("_livrables_a_l_ecran(text, state)") < agent1_src.index("_dedoublonner_blocs(text)"))

print("\n2. La voie rapide ne s'applique qu'à une SUITE")
routeur = agent1_src[agent1_src.index("async def routeur_node("):agent1_src.index("async def recherche_node(")]
verifier("un premier message, même court, passe par le juge (la voie rapide exige un historique)",
         'state.get("messages")' in routeur and "question_meta(" in routeur)

print("\n3. Le composant reponses_mail et le canal d'envoi")
rendu = (FRONTEND / "components" / "chat" / "MessageRenderer.tsx").read_text(encoding="utf-8")
verifier("bloc `reponses_mail` enregistré (champ requis : reponses)", 'reponses_mail: ["reponses"]' in rendu)
verifier("le composant reçoit onAction (le même canal que les suggestions)",
         re.search(r'case "reponses_mail":.*?onAction=\{onAction\}', rendu, re.S) is not None)
composant = (FRONTEND / "components" / "blocks" / "business" / "ReponsesMail.tsx").read_text(encoding="utf-8")
verifier("cartes en pages (une, deux ou trois), case par carte, un bouton groupé",
         # 03/09 : le rail horizontal a cédé la place à des pages avec deux flèches
         # (relevé de Noa : « trop petit et pas pratique »). Voir test_cartes_mail_pages.
         "sym-rm-pages" in composant and 'aria-label="Cartes suivantes"' in composant
         and 'type="checkbox"' in composant and "réponse(s) cochée(s)" in composant)
verifier("chaque carte montre la SYNTHÈSE du mail reçu (le contexte de la réponse)",
         "synthese" in composant and "sym-rm-contexte" in composant)
verifier("le contrat du bloc et check_mails portent le champ synthese",
         '"synthese":"..."' in (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
         and "synthese" in (BACKEND / "skills" / "routines.py").read_text(encoding="utf-8"))
verifier("chaque réponse est ÉDITABLE : la version corrigée est celle qui part",
         "<textarea" in composant and "corriger(" in composant and "textes[i].trim()" in composant
         and "modifiée" in composant)
verifier("tout cocher / tout décocher existe", "Tout décocher" in composant)
verifier("le bouton n'envoie RIEN lui-même : il écrit dans le chat, la validation reste",
         "onAction(" in composant and "validation" in composant)
prompt_ok = '"type":"reponses_mail"' in agent1_src and "reponses_mail" in agent1_src.split("COMPOSANTS VISUELS")[1][:6000]
verifier("le modèle connaît le bloc (liste des composants du prompt)", prompt_ok)
routines = (BACKEND / "skills" / "routines.py").read_text(encoding="utf-8")
verifier("check_mails demande de rassembler les propositions dans UN bloc reponses_mail",
         "reponses_mail" in routines and "n’envoie rien" in routines)

chemin = (FRONTEND / "components" / "chat" / "ReasoningPath.tsx").read_text(encoding="utf-8")
verifier("la colonne « En ce moment » : une ligne par étape, le détail suit l'étape ACTIVE, plus de titre redondant",
         'stateOf(i) === "active" && (' in chemin and "sym-path-title" not in chemin)

print("\n4. Les raccourcis de la barre de saisie")
barre = (FRONTEND / "components" / "chat" / "InputBar.tsx").read_text(encoding="utf-8")
raccourcis = (FRONTEND / "lib" / "raccourcis.ts").read_text(encoding="utf-8")
verifier("la liste des raccourcis est une donnée par client (lib/raccourcis.ts), importée par la barre",
         "const RACCOURCIS" not in barre and 'from "@/lib/raccourcis"' in barre
         and "export const RACCOURCIS" in raccourcis and "7 derniers jours" in raccourcis)
verifier("clients et chiffre d'affaires ont quitté le menu (31/08)",
         "liste complète des clients" not in raccourcis and "chiffre d’affaires" not in raccourcis
         and "chiffre d'affaires" not in raccourcis)
verifier("le bouton déroule le menu au-dessus de la saisie", "setRaccourcisOuverts" in barre and "ZapIcon" in barre)
theme = (FRONTEND / "app" / "theme.css").read_text(encoding="utf-8")
verifier("les boutons de la barre sont centrés sur l'axe du champ (theme.css)",
         ".sym-barre-saisie button { align-self: center; }" in theme)
verifier("chaque raccourci a un libellé et un prompt non vides",
         raccourcis.count("libelle:") >= 2 and raccourcis.count("prompt:") == raccourcis.count("libelle:"))
verifier("un raccourci PRÉREMPLIT la saisie, il n'envoie pas",
         re.search(r"setTexte\(r\.prompt\)", barre) is not None and "onSend(r.prompt" not in barre)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
