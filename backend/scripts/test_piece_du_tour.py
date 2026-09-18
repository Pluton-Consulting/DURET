"""
LA PIÈCE JOINTE À CE MESSAGE EST CELLE QU'ON LIT (18/09, banc de tests Duret, Q69).

Fil de test : un CCTP, un DPGF et des questions-réponses joints (Q65), un tableau
de surfaces (Q66), une photo (Q67), dix photos (Q68). Puis « Lis ce document » +
le PDF des questions-réponses. Réponse : le résumé du CCTP d'un tour précédent et
de l'analyse des dix photos — jamais le PDF joint. Deux causes :

  1. `vision_analysis` n'était pas remise à zéro à chaque tour : l'analyse des dix
     photos restait dans l'état, et `rag_node` l'ENREGISTRAIT dans le dossier du
     fil sous le nom du PDF (« Analyse visuelle — Questions réponses.pdf ») ;
  2. dans un fil qui porte déjà des sources, la pièce du message n'était qu'un
     aperçu parmi vingt, sans rien qui la distingue.

Ce banc exécute `rag_node` (extrait du module livré) contre un dossier doublé.
"""
import ast
import asyncio
import sys
import types
from pathlib import Path

ICI = Path(__file__).resolve()
BACKEND = ICI.parents[1]
ECHECS = []


def verifier(nom, cond, detail=""):
    print(("  ✓ " if cond else "  ✗ ") + nom + ("" if cond else f"  → {detail}"))
    if not cond:
        ECHECS.append(nom)


print("═══ LA PIÈCE DE CE MESSAGE — " + str(BACKEND))

# ── 1. La remise à zéro par tour ─────────────────────────────────────────
src_rt = (BACKEND / "agents" / "runtime.py").read_text(encoding="utf-8")
arbre = ast.parse(src_rt)
init = next(n for n in ast.walk(arbre) if isinstance(n, ast.FunctionDef) and n.name == "_initial_state")
cles_nulles = set()
for n in ast.walk(init):
    if isinstance(n, ast.Dict):
        for k, v in zip(n.keys, n.values):
            if isinstance(k, ast.Constant) and isinstance(v, ast.Constant) and v.value is None:
                cles_nulles.add(k.value)
verifier("l'analyse visuelle est remise à zéro à chaque tour", "vision_analysis" in cles_nulles,
         sorted(cles_nulles)[:10])

# ── 2. rag_node, extrait du module livré ─────────────────────────────────
src = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
mod = ast.parse(src)
voulus = {"_noms_joints_du_tour", "_source_du_tour", "rag_node"}
morceaux = []
for n in mod.body:
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in voulus:
        morceaux.append(ast.get_source_segment(src, n))
    if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_MARQUE_PIECE" for t in n.targets):
        morceaux.append(ast.get_source_segment(src, n))
verifier("les fonctions sont dans le module livré", len(morceaux) == 4, len(morceaux))


class _Dossier:
    """Un dossier de fil en mémoire, de la forme du vrai (`ressources.dossiers`)."""

    def __init__(self, sources):
        self.sources = list(sources)
        self.enregistres = []

    def manifeste(self, uid, fil):
        return [{"id": s["id"], "nom": s["nom"]} for s in self.sources]

    def lire(self, uid, fil, ident):
        s = next(x for x in self.sources if x["id"] == ident)
        return {"texte": s["texte"]}

    def enregistrer(self, uid, fil, nom, texte, *a):
        self.enregistres.append(nom)
        self.sources.append({"id": f"s{len(self.sources) + 1}", "nom": nom, "texte": texte})

    def joindre_texte(self, uid, fil, texte, nom):
        self.enregistrer(uid, fil, nom, texte)


FIL = [
    {"id": "s1", "nom": "CCTP Lot 11.pdf", "texte": "CCTP lot 11 revêtements Saint Aigulin"},
    {"id": "s2", "nom": "DPGF Lot 11.pdf", "texte": "DPGF parquets La Teste"},
    {"id": "s3", "nom": "Questions réponses.pdf", "texte": "Questions réponses Domofrance Pessac 111 logements"},
    {"id": "s4", "nom": "Tableau Surfaces Utiles.pdf", "texte": "tableau des surfaces"},
    {"id": "s5", "nom": "Analyse visuelle — onze-IMG_1046.JPG", "texte": "dix photos d'escalier"},
]
dossier = _Dossier(FIL)
paquet = types.ModuleType("ressources")
paquet.dossiers = dossier
sys.modules["ressources"] = paquet
sys.modules["ressources.dossiers"] = dossier
espace = {"AgentState": dict, "__name__": "agent1_extrait"}
exec("import re as _re_pieces\n" + "\n\n".join(morceaux), espace)

# LE CAS DE PROD, tel que le routeur du chat le transmet : un PDF joint SEUL n'a pas
# d'`attachment_name` (il ne désigne que le premier fichier VISUEL) — seul le texte
# joint, marqué à son nom, dit quelle pièce vient d'arriver.
src_chat = (BACKEND / "routers" / "chat.py").read_text(encoding="utf-8")
verifier("le routeur marque TOUT texte joint à son nom, même seul",
         "textes.append(f\"=== Fichier joint : {piece['nom']} ===\\n{texte}\")" in src_chat
         and "if len(pieces) > 1 else texte" not in src_chat)
verifier("…et `attachment_name` reste celui du premier fichier visuel (d'où la marque)",
         'tete = visuels[0] if visuels else {}' in src_chat and 'attachment_name=tete.get("nom")' in src_chat)
etat = {"user_id": "u", "thread_id": "f", "query": "Lis ce document",
        "attachment_text": "=== Fichier joint : Questions réponses.pdf ===\nQuestions réponses Domofrance Pessac 111 logements",
        "attachment_name": None, "has_attachment": True,
        "vision_analysis": None}
r = asyncio.run(espace["rag_node"](etat))
chunks = r.get("raw_chunks") or []
verifier("la pièce de CE message est annoncée en tête",
         chunks and chunks[0].startswith("[PIÈCE(S) JOINTE(S) À CE MESSAGE") and "Questions réponses.pdf" in chunks[0],
         chunks[:1])
verifier("son aperçu est marqué et passe avant les autres",
         len(chunks) > 1 and "Questions réponses.pdf — JOINTE À CE MESSAGE" in chunks[1], chunks[1:2])
verifier("les autres sources restent, sans la marque",
         any("CCTP Lot 11.pdf — APERÇU" in c for c in chunks)
         and not any("CCTP Lot 11.pdf — JOINTE" in c for c in chunks))
verifier("aucune analyse visuelle n'est enregistrée sous le nom du PDF",
         not any(n.startswith("Analyse visuelle — Questions") for n in dossier.enregistres), dossier.enregistres)

# Plusieurs fichiers dans un message : les marques du texte joint font foi.
etat2 = {"user_id": "u", "thread_id": "f", "query": "compare ces pièces",
         "attachment_text": "=== Fichier joint : CCTP Lot 11.pdf ===\nx\n\n=== Fichier joint : DPGF Lot 11.pdf ===\ny",
         "attachment_name": "CCTP Lot 11.pdf", "has_attachment": True}
r2 = asyncio.run(espace["rag_node"](etat2))
tete = (r2.get("raw_chunks") or [""])[0]
verifier("deux fichiers joints : les deux sont nommés comme pièces du message",
         "CCTP Lot 11.pdf" in tete and "DPGF Lot 11.pdf" in tete and "Questions réponses" not in tete, tete)

# Une photo analysée par la vision : sa lecture dérivée compte comme pièce du tour.
verifier("« Analyse visuelle — photo.jpg » appartient à la pièce photo.jpg",
         espace["_source_du_tour"]("Analyse visuelle — photo.jpg", ["photo.jpg"])
         and espace["_source_du_tour"]("plan.pdf — lecture visuelle page 2", ["plan.pdf"])
         and not espace["_source_du_tour"]("photo.jpg.old", ["photo.jpg"]))

# Sans pièce jointe : aucun en-tête, les aperçus comme avant.
etat3 = {"user_id": "u", "thread_id": "f", "query": "et le planning ?", "attachment_text": None,
         "attachment_name": None, "has_attachment": False}
r3 = asyncio.run(espace["rag_node"](etat3))
verifier("sans pièce jointe, aucune marque ni en-tête",
         not any("JOINTE" in c for c in (r3.get("raw_chunks") or [])))

print("\n" + ("✓ 0 échec" if not ECHECS else f"✗ {len(ECHECS)} échec(s)"))
sys.exit(1 if ECHECS else 0)
