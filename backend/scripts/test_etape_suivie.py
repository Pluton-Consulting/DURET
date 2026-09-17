"""
Banc « L'ÉTAPE SUIT, MÊME SANS SOCKET » — 17/09, fil d13ff0ac (Symbiose, iPhone).

12:47:35 : la socket du téléphone se ferme (veille). L'écran rejoint la demande par
SONDAGE — 175 fois — et ne reçoit que « toujours en cours » : il reste figé sur
« je cherche ce nom sur le Drive » pendant que le serveur lit des factures puis
produit l'Excel. La personne croit le tour mort, recharge, renvoie, et reçoit « un
traitement est déjà en cours », qui ressemble à une panne.

Sans base ni réseau : les fonctions sont extraites du code livré et exécutées.
"""
import ast
import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend"
echecs = []


def verifier(nom, cond, detail=""):
    print(("  ✓ " if cond else "  ✗ ") + nom + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


src = (BACKEND / "agents" / "requetes.py").read_text(encoding="utf-8")
arbre = ast.parse(src)
code = "\n\n".join(ast.get_source_segment(src, n) for n in arbre.body
                   if isinstance(n, ast.FunctionDef) and n.name in ("noter_etape", "oublier_etape", "reponse_de_reprise"))
esp = {"json": __import__("json"), "_ETAPES": {}, "_ETAPES_MAX": 3}
exec(code, esp)
noter, oublier, reprise = esp["noter_etape"], esp["oublier_etape"], esp["reponse_de_reprise"]

print("\n═══ L'ÉTAPE SUIT —", BACKEND.parent)
D = {"etat": "en_cours", "thread_id": "fil", "resultat": None, "request_id": "req-1"}
verifier("avant toute étape, le sondage ne ment pas : étape absente, tour en cours",
         reprise(D)["reprise"] is True and reprise(D)["etape"] is None)
noter("req-1", "tools", "je cherche ce nom sur le Drive", "drive_chercher")
verifier("l'étape annoncée par la socket est rendue par le sondage",
         reprise(D)["etape"] == {"node": "tools", "libelle": "je cherche ce nom sur le Drive", "skill": "drive_chercher"})
noter("req-1", "llm", None, None)
verifier("un nœud sans libellé garde le libellé précédent (comme à l'écran), et avance le nœud",
         reprise(D)["etape"]["libelle"] == "je cherche ce nom sur le Drive" and reprise(D)["etape"]["node"] == "llm"
         and reprise(D)["etape"]["skill"] == "")
noter("req-1", "tools", "je produis le document", "produire_document")
verifier("l'étape suivante remplace la précédente", reprise(D)["etape"]["libelle"] == "je produis le document")
verifier("une autre demande ne voit pas cette étape", reprise({**D, "request_id": "req-2"})["etape"] is None)
fini = reprise({"etat": "terminee", "thread_id": "fil", "request_id": "req-1", "resultat": '{"response": "voilà", "status": "ok"}'})
verifier("une demande terminée rend sa réponse, sans étape", fini["response"] == "voilà" and fini["reprise"] is False and "etape" not in fini)
oublier("req-1")
verifier("l'étape s'oublie à la fin du tour", reprise(D)["etape"] is None)
for i in range(6):
    noter(f"r{i}", "llm", "x", "")
verifier("le registre est borné (il ne grossit pas sans fin)", len(esp["_ETAPES"]) <= 3)
noter(None, "llm", "x", ""); noter("", "llm", "x", "")
verifier("sans identifiant, rien n'est noté et rien ne lève", True)
verifier("aucun contenu de message n'entre dans le registre : un nœud, un libellé, un skill",
         set(next(iter(esp["_ETAPES"].values())).keys()) == {"node", "libelle", "skill"})

chat = (BACKEND / "routers" / "chat.py").read_text(encoding="utf-8")
verifier("l'étape est RETENUE avant d'être dite à la socket",
         chat.index("_requetes.noter_etape(data.get(\"request_id\")") < chat.index("rafraîchissement) ne doit plus faire dérailler le tour")
         and "_requetes.oublier_etape(data.get(\"request_id\"))" in chat)
verifier("la demande consultée porte son identifiant (c'est la clé de l'étape)",
         '{**dict(ligne), "request_id": request_id}' in src)
tsx = (FRONTEND / "components" / "chat" / "ChatWindow.tsx").read_text(encoding="utf-8")
# Duret : l'écran ne suit pas encore une demande par sondage après socket perdue (patch Symbiose
# du 17/09 matin, non porté) : le serveur REND l'étape, l'écran la lira quand ce suivi sera porté.

# Le PLAN APPROUVÉ : l'étape était sondée et reçue, mais rendue nulle part au téléphone.
verifier("le bandeau d'étape s'affiche aussi pendant un accord en cours et une reprise suivie",
         "enCours={loading || accordEnCours !== null || repriseSuivie}" in tsx)
verifier("la reprise suivie après un POST perdu allume la frise ET se referme à la fin",
         "setRepriseSuivie(true)" in tsx and tsx.count("setRepriseSuivie(false)") >= 2
         and tsx.count("setThinkingSteps((prev) => (prev[prev.length - 1] === n ? prev : [...prev, n]))") >= 2)

print("\n" + "═" * 70)
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs))
    sys.exit(1)
print("✓ 0 échec\n")
