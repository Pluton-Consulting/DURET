"""
Banc « un journal précis, un OCR qui lit juste » — 01/09.

Deux demandes de Noa le même soir :
  · « les textes de thinking doivent être les plus précis possible et les
    moins génériques possible » — le journal dit désormais la DEMANDE
    (« terrasse bois »), le LIEU (dossier, boîte), l'AVANCEMENT (page 3) et
    le RÉSULTAT (« 12 document(s) ») ; le contenu RAPPORTÉ reste interdit ;
  · « l'OCR fait encore des erreurs, préparamètre un meilleur modèle,
    OpenRouter est déjà utilisé » — Gemini 2.5 Pro via OpenRouter entre dans
    la cascade vision, et la transcription des images passe par la vision
    d'abord (tesseract en ébauche et en secours — voir test_pieces_jointes).
"""
import ast
import pathlib
import re
import sys

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def extraire(chemin, noms, espace):
    arbre = ast.parse(pathlib.Path(chemin).read_text(encoding="utf-8"))
    gardes = []
    for n in arbre.body:
        if isinstance(n, ast.ImportFrom) and n.module == "__future__":
            gardes.append(n)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in noms:
            gardes.append(n)
        elif isinstance(n, ast.Assign) and any(
                isinstance(c, ast.Name) and c.id in noms for c in n.targets):
            gardes.append(n)
    exec(compile(ast.Module(body=gardes, type_ignores=[]), str(chemin), "exec"), espace)
    manquants = [x for x in noms if x not in espace]
    assert not manquants, f"absent du module livré : {manquants}"
    return espace


print(f"\n═══ JOURNAL PRÉCIS ET OCR — {BACKEND.resolve().parent}\n")

# ── 1. Le « sur quoi » : la demande, le lieu, l'avancement ───────────────
espace = extraire(BACKEND / "agents" / "journal.py",
                  {"_detail", "_bilan", "_motif", "_acte", "_budget_actions",
                   "libelle", "ACTES", "LIBELLES", "MAX_DETAIL", "MAX_LIBELLE",
                   "MAX_MOTIF", "_BUDGET_REPLI"}, {})
d = espace["_detail"]
verifier("la DEMANDE s'affiche : motif entre guillemets",
         "« terrasse bois »" in d({"motif": "terrasse bois"}))
verifier("demande + lieu + page, ensemble",
         d({"motif": "terrasse bois", "dossier": "Chantiers", "page": 3})
         == "« terrasse bois », Chantiers, page 3")
verifier("la boîte mail reste un lieu", d({"mailbox": "compta@x.fr"}) == "compta@x.fr")
verifier("la page 1 ne s'affiche pas (elle n'apprend rien)", d({"requete": "devis", "page": 1}) == "« devis »")
verifier("« avant » se dit en français", "messages plus anciens" in d({"avant": "a1f2"}))
verifier("une période se dit", "sur 7j" in d({"depuis": "7j"}))
verifier("vide → vide", d({}) == "" and d(None) == "")

# ── 2. Le « combien » : le résultat compté, jamais son contenu ───────────
b = espace["_bilan"]
verifier("un compte se lit dans le résultat : nombre → résultat(s)",
         b({"resultat_masque": '{"motif": "durand", "nombre": 95, "pages": 3}'}) == "95 résultat(s)")
verifier("total_documents → document(s)",
         b({"resultat_masque": 'préfixe {"total_documents": 12, "documents": []}'}) == "12 document(s)")
verifier("un JSON TRONQUÉ au plafond rend quand même son compte",
         b({"resultat_masque": '{"compte": 66, "messages": [{"de": "x", "ob'}) == "66 message(s)")
verifier("sans compte → rien", b({"resultat_masque": '{"ok": true}'}) == "" and b({}) == "")
lib = espace["libelle"]
ligne = lib("tools", {"tool_results": [
    {"skill": "rechercher_documents", "ok": True,
     "args": {"requete": "drainage terrasse"},
     "resultat_masque": '{"total_documents": 7}'}]})
verifier("la ligne complète : l'acte, la demande, le résultat",
         "je cherche dans les documents" in ligne and "« drainage terrasse »" in ligne
         and "7 document(s)" in ligne)
ligne_ko = lib("tools", {"tool_results": [
    {"skill": "rechercher_documents", "ok": False, "args": {},
     "resultat_masque": "ERREUR : rien"}]})
verifier("un échec dit « sans succès », jamais un bilan", "sans succès" in ligne_ko and "—" not in ligne_ko)

# ── 3. L'OCR préparamétré via OpenRouter ─────────────────────────────────
config = (BACKEND / "config.py").read_text(encoding="utf-8")
verifier("config : model_openrouter_vision préréglé sur Gemini 2.5 Pro",
         re.search(r'model_openrouter_vision: str = "google/gemini-2\.5-pro"', config))
routeur = (BACKEND / "llm" / "router.py").read_text(encoding="utf-8")
m = re.search(r"for provider, model in \(\(\"anthropic\", s\.model_anthropic_vision\),\s*"
              r"\(\"openrouter\", s\.model_openrouter_vision\),\s*"
              r"\(\"google\", s\.model_google_vision\)", routeur)
verifier("cascade vision : OpenRouter derrière Anthropic, devant Google", bool(m))
pieces = (BACKEND / "mail" / "pieces.py").read_text(encoding="utf-8")
verifier("la transcription vision existe, l'ébauche tesseract dans la consigne",
         "CONSIGNE_OCR" in pieces and "{ebauche}" in pieces
         and "transcription par la vision" in pieces)
verifier("tesseract reste le secours quand aucun modèle ne répond",
         "le texte tesseract reste" in pieces)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
