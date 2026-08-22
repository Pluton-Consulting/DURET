"""
Banc du rendu de secours — la sortie d'un skill atteint l'écran sans le modèle.

La fonction est extraite du module livré (agent1.py importe un graphe entier
au chargement : on ne prend que ce qu'on teste). Les résultats rejoués sont
ceux des traces du 22/08 : une liste de clients, un point sur les mails, une
lecture de boîte, un visuel, un refus honnête, et le préfixe de déduplication.
"""
import sys, ast, pathlib, json
BACKEND = sys.argv[1] if len(sys.argv) > 1 else "backend"
src = (pathlib.Path(BACKEND) / "agents" / "agent1.py").read_text(encoding="utf-8")
arbre = ast.parse(src)
espace = {}
for n in arbre.body:
    if isinstance(n, ast.FunctionDef) and n.name == "_rendu_de_secours":
        exec(compile(ast.Module(body=[n], type_ignores=[]), "agent1", "exec"), espace)
assert "_rendu_de_secours" in espace, "fonction absente du module livré"
secours = espace["_rendu_de_secours"]
echecs = []
def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond: echecs.append(nom)
def res(skill, d, ok=True, prefixe=""):
    return {"skill": skill, "ok": ok, "resultat_masque": prefixe + json.dumps(d, ensure_ascii=False)}

print(f"\n═══ RENDU DE SECOURS — {BACKEND}\n")
r = secours([res("liste_clients", {"trouve": True, "message_final": "478 clients en base, les 60 premiers affichés.",
                                   "bloc_ui": {"type": "table", "columns": ["Client"], "rows": [["ACIEN"]]}})])
verifier("liste_clients → phrase + bloc table", r.startswith("478 clients") and '"type": "table"' in r, r[:120])
r = secours([res("check_mails", {"nombre": 2, "message_final": "28 message(s) reçu(s) depuis le 15/08/2026, dont voici les 2 plus récents.",
                                 "messages": [{"de": "a@b.fr", "objet": "Re: devis", "date": "2026-08-22T09:12:00Z", "extrait": "Bonjour"},
                                              {"de": "c@d.fr", "objet": "Catalogue", "date": "2026-08-21", "extrait": "Promo"}]})])
verifier("check_mails → compte + une carte email par message", r.count('"type": "email"') == 2 and r.startswith("28 message"), r[:160])
r = secours([res("lire_mails", {"compte": "La boîte contient 24865 message(s) ; voici les 10 plus récents.", "messages": [{"objet": "x", "de": "y", "date": "", "apercu": "z"}]})])
verifier("lire_mails → le compte puis les cartes", r.startswith("La boîte contient") and '"type": "email"' in r, r[:120])
r = secours([res("tester_visuel", {"genere": True, "message_final": "Voici l'essai de visuel.", "bloc_ui": {"type": "visuel", "images": [{"cle": "79800c896bd4e138b125d2d0"}]}})])
verifier("tester_visuel → le bloc visuel", '"type": "visuel"' in r and "79800c896bd4e138b125d2d0" in r, r[:120])
r = secours([res("fiche_client", {"trouve": False, "message": "Aucun enregistrement ne mentionne « Fantôme »."})])
verifier("un refus honnête est rendu tel quel", r.startswith("Aucun enregistrement"), r)
r = secours([res("liste_clients", {"trouve": True, "message_final": "3 clients en base, tous affichés.", "bloc_ui": {"type": "table", "columns": ["C"], "rows": [["a"]]}},
                 prefixe="(déjà exécuté à ce tour, son résultat est inchangé)\n")])
verifier("le préfixe de déduplication n'empêche pas la lecture", r.startswith("3 clients"), r[:80])
r = secours([res("rechercher_documents", {"requete": "x", "resultats": [], "nombre": 0}), res("liste_clients", {"trouve": True, "message_final": "OK", "bloc_ui": {"type": "table", "columns": [], "rows": []}})])
verifier("le DERNIER skill réussi gagne", r.startswith("OK"), r[:60])
r = secours([res("liste_clients", {"trouve": True}, ok=False)])
verifier("un échec ne rend rien", r == "", r)
r = secours([res("preparer_visuel", {"pret": True, "brief": "…", "note": "…"})])
verifier("un résultat sans rien à montrer ne rend rien (pas de bruit)", r == "", r)
print(f"\n═══ {len(echecs)} échec(s)" + (f" : {', '.join(echecs)}" if echecs else " — tout passe"))
sys.exit(1 if echecs else 0)
