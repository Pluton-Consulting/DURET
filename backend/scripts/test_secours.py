"""
Banc du rendu de secours — les BLOCS sans prose, et la prose par le MODÈLE.

CONTRAT DU 30/08 (règle de Noa : aucune phrase préécrite dans le chat) :
`_rendu_de_secours` ne rend plus QUE les blocs d'écran du dernier skill réussi
— tableaux, cartes mail, planches — et plus une ligne de prose. Le texte vient
de `_rediger_par_le_modele` : appel modèle à contexte réduit (demande +
résultats masqués + consigne au passé composé), qui rend "" si aucun
fournisseur ne répond ou si le modèle rechute en promesse — les blocs
s'affichent alors seuls, jamais une phrase de remplacement.

Les fonctions sont extraites du module livré ; le LLM est DOUBLÉ (aucun
réseau). Les résultats rejoués sont ceux des traces du 22/08.
"""
import ast
import asyncio
import json
import pathlib
import sys
import types

BACKEND = sys.argv[1] if len(sys.argv) > 1 else "backend"
racine = pathlib.Path(BACKEND)

echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def extraire(noms, espace):
    arbre = ast.parse((racine / "agents" / "agent1.py").read_text(encoding="utf-8"))
    # Fonctions ET constantes de module nommées : le rédacteur s'appuie depuis
    # le 31/08 sur `_sans_identifiants`, qui lit `_CLES_TECHNIQUES` et
    # `_IDENTIFIANT_RE` — des affectations, pas des def.
    def _cibles(n):
        return [t.id for t in getattr(n, "targets", []) if isinstance(t, ast.Name)]
    gardes = [n for n in arbre.body
              if (isinstance(n, ast.ImportFrom) and n.module == "__future__")
              or (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in noms)
              or (isinstance(n, ast.Assign) and any(c in noms for c in _cibles(n)))]
    exec(compile(ast.Module(body=gardes, type_ignores=[]), "agent1", "exec"), espace)
    manquants = [x for x in noms if x not in espace]
    assert not manquants, f"absent du module livré : {manquants}"
    return espace


def res(skill, d, ok=True, prefixe=""):
    return {"skill": skill, "ok": ok, "resultat_masque": prefixe + json.dumps(d, ensure_ascii=False)}


class _Journal:
    def info(self, *a, **k):
        pass
    warning = info


espace = extraire({"_rendu_de_secours"}, {"logger": _Journal()})
secours = espace["_rendu_de_secours"]

print(f"\n═══ RENDU DE SECOURS — {BACKEND}\n")
print("1. Les blocs, et RIEN QUE les blocs (la prose appartient au modèle)")

r = secours([res("liste_clients", {"trouve": True, "message_final": "478 clients en base, les 60 premiers affichés.",
                                   "bloc_ui": {"type": "table", "columns": ["Client"], "rows": [["ACIEN"]]}})])
verifier("liste_clients → le bloc table, sans le message du skill",
         '"type": "table"' in r and "478 clients" not in r, r[:120])
r = secours([res("check_mails", {"nombre": 2, "message_final": "28 message(s) reçu(s) depuis le 15/08/2026.",
                                 "messages": [{"de": "a@b.fr", "objet": "Re: devis", "date": "2026-08-22T09:12:00Z", "extrait": "Bonjour"},
                                              {"de": "c@d.fr", "objet": "Catalogue", "date": "2026-08-21", "extrait": "Promo"}]})])
verifier("check_mails → les cartes email, sans le compte en prose",
         r.count('"type": "email"') == 2 and "28 message" not in r, r[:160])
r = secours([res("tester_visuel", {"genere": True, "message_final": "Voici l'essai de visuel.",
                                   "bloc_ui": {"type": "visuel", "images": [{"cle": "79800c896bd4e138b125d2d0"}]}})])
verifier("tester_visuel → le bloc visuel, sans la phrase",
         '"type": "visuel"' in r and "79800c896bd4e138b125d2d0" in r and "Voici l'essai" not in r, r[:120])
r = secours([res("fiche_client", {"trouve": False, "message": "Aucun enregistrement ne mentionne « Fantôme »."})])
verifier("un refus sans bloc ne rend RIEN — c'est au modèle de le dire", r == "", r)
r = secours([res("liste_clients", {"trouve": True, "bloc_ui": {"type": "table", "columns": ["C"], "rows": [["a"]]}},
                 prefixe="(déjà exécuté à ce tour, son résultat est inchangé)\n")])
verifier("le préfixe de déduplication n'empêche pas la lecture", '"type": "table"' in r, r[:80])
r = secours([res("rechercher_documents", {"requete": "x", "resultats": [], "nombre": 0}),
             res("liste_clients", {"trouve": True, "bloc_ui": {"type": "table", "columns": [], "rows": []}})])
verifier("le DERNIER skill réussi gagne", '"type": "table"' in r, r[:60])
verifier("un échec ne rend rien", secours([res("liste_clients", {"trouve": True}, ok=False)]) == "")
verifier("un résultat sans rien à montrer ne rend rien",
         secours([res("preparer_visuel", {"pret": True, "brief": "…", "note": "…"})]) == "")

aucune_prose = all("message_final" not in secours([res("liste_clients",
                   {"trouve": True, "message_final": phrase,
                    "bloc_ui": {"type": "table", "columns": [], "rows": []}})])
                   .replace('"type": "table"', "") and phrase not in secours([res("liste_clients",
                   {"trouve": True, "message_final": phrase,
                    "bloc_ui": {"type": "table", "columns": [], "rows": []}})])
                   for phrase in ("Le document est prêt.", "Action exécutée."))
verifier("aucune phrase de skill ne traverse, quelle qu'elle soit", aucune_prose)

# ── 2. la prose vient du modèle, avec ses garde-fous ───────────────────────
print("\n2. La prose du modèle (`_rediger_par_le_modele`, LLM doublé)")

appels = []


class _FauxLLM:
    def __init__(self, reponse):
        self._r = reponse

    async def ainvoke(self, messages):
        appels.append(messages[0].content)
        if isinstance(self._r, Exception):
            raise self._r
        return types.SimpleNamespace(content=self._r)


def espace_redaction(reponse):
    faux_llm = types.ModuleType("llm.router")
    faux_llm.get_llm = lambda tier: _FauxLLM(reponse)
    faux_llm.LLMTier = types.SimpleNamespace(STANDARD="standard", LIGHT="light", COMPLEX="complex")
    sys.modules.setdefault("llm", types.ModuleType("llm"))
    sys.modules["llm.router"] = faux_llm
    faux_lc = types.ModuleType("langchain_core.messages")
    faux_lc.HumanMessage = lambda content: types.SimpleNamespace(content=content)
    sys.modules.setdefault("langchain_core", types.ModuleType("langchain_core"))
    sys.modules["langchain_core.messages"] = faux_lc

    import re as _re
    faux_proto = types.ModuleType("skills.protocol")
    for nom in ("BLOC_ACTION_RE", "BLOC_ACTION_TRONQUE_RE", "BLOC_NATIF_RE", "BALISAGE_OUTIL_RE"):
        setattr(faux_proto, nom, _re.compile(r"```action\s*\{.*?\}\s*```", _re.S)
                if nom == "BLOC_ACTION_RE" else _re.compile(r"(?!x)x"))
    sys.modules.setdefault("skills", types.ModuleType("skills"))
    sys.modules["skills.protocol"] = faux_proto

    import importlib.util
    spec = importlib.util.spec_from_file_location("annonce", racine / "agents" / "annonce.py")
    annonce = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(annonce)
    return extraire({"_rediger_par_le_modele", "_texte_visible", "_sans_identifiants",
                     "_CLES_TECHNIQUES", "_IDENTIFIANT_RE"},
                    {"logger": _Journal(), "est_une_annonce": annonce.est_une_annonce,
                     "promesse_sans_suite": annonce.promesse_sans_suite})


RESULTATS = [res("liste_fournisseurs", {"nombre": 90, "message_final": "90 fournisseurs."})]

appels.clear()
e = espace_redaction("Le fichier des 90 fournisseurs a été produit, avec votre adresse en colonne B.")
prose = asyncio.run(e["_rediger_par_le_modele"]("fais un excel des fournisseurs", RESULTATS, "banc"))
verifier("le modèle écrit la prose, elle est rendue telle quelle",
         prose.startswith("Le fichier des 90 fournisseurs"), prose[:120])
verifier("le prompt exige le passé composé et interdit d'annoncer",
         "passé composé" in appels[0] and "N'annonce rien" in appels[0], appels[0][:200])
verifier("le prompt porte la demande et les résultats masqués",
         "fais un excel" in appels[0] and "90 fournisseurs" in appels[0])

e = espace_redaction("Je vais créer le fichier des fournisseurs.")
verifier("une RECHUTE en promesse est refusée — plutôt les blocs seuls",
         asyncio.run(e["_rediger_par_le_modele"]("fais un excel", RESULTATS, "banc")) == "")

e = espace_redaction(RuntimeError("Tous les modèles LLM ont échoué"))
verifier("cascade morte → \"\" , jamais une phrase de remplacement",
         asyncio.run(e["_rediger_par_le_modele"]("fais un excel", RESULTATS, "banc")) == "")

appels.clear()
e = espace_redaction("La demande n'a pas pu être traitée ce tour-ci.")
prose = asyncio.run(e["_rediger_par_le_modele"]("fais un truc", [], "banc"))
verifier("sans résultat, l'aveu d'échec vient aussi du modèle",
         prose.startswith("La demande") and "honnêtement" in appels[-1], appels[-1][:200])

# ── 3. plus une seule phrase préécrite dans les filets livrés ──────────────
print("\n3. Le code livré ne porte plus de prose en dur")
src = (racine / "agents" / "agent1.py").read_text(encoding="utf-8")
# Le guillemet DROIT final distingue un littéral de code d'un commentaire qui
# cite l'ancien défaut pour mémoire (« … ? ». en typographie française).
for fantome in ('J\'ai bien mené les', 'Pouvez-vous la reformuler ?"',
                "n'a pas été réellement produit"):
    verifier(f"« {fantome[:40]} » a quitté agent1.py", fantome not in src)
src_r = (racine / "agents" / "router.py").read_text(encoding="utf-8")
for fantome in ("Action refusée : rien n'a été exécuté",
                "exécutée après validation.\""):
    verifier(f"« {fantome[:40]} » a quitté router.py", fantome not in src_r)
verifier("la reprise post-validation rédige par le modèle",
         "_reponse_apres_action" in src_r and "_rediger_par_le_modele" in src_r)

print(f"\n═══ {len(echecs)} échec(s)" + (f" : {', '.join(echecs)}" if echecs else " — tout passe"))
sys.exit(1 if echecs else 0)
