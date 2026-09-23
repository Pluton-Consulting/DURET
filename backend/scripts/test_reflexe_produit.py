"""
Banc « LES PRODUITS SE VÉRIFIENT À LA SOURCE » (23/09, Duret).

Demande de Noa : que la recherche web soit un RÉFLEXE pour les produits, les
fiches techniques et les sites fournisseurs, et que l'assistant soit force de
proposition — sans rien dégrader : le web reste interdit aux données internes.

CE QUE CE BANC PROUVE (modules LIVRÉS, web doublé) :
  * `fiche_produit` vise le site du fabricant quand la marque est connue, lit la
    fiche, relève UPEC / feu / épaisseur / acoustique / avis technique avec leur
    source, affiche le tableau ; sans résultat, le dit sans rien inventer ;
  * la garde du web automatique laisse passer « la fiche technique du fournisseur
    Weber » et garde au-dedans « les factures du fournisseur Weber » ;
  * le relecteur relit une caractéristique affirmée même sans geste, et sa
    consigne exige la source (règle 7) ;
  * la consigne du modèle porte le réflexe, le geste est rangé dans la famille web.
"""
import ast
import asyncio
import importlib.util
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ LES PRODUITS SE VÉRIFIENT À LA SOURCE — {BACKEND.parent}\n")

reg = types.ModuleType("skills.registre")
reg.Declaration = lambda **k: types.SimpleNamespace(**k)
sys.modules["skills"] = types.ModuleType("skills")
sys.modules["skills.registre"] = reg
RECHERCHES, OUVERTURES = [], []
FICHE = ("Source : https://www.gerflor.fr/docs/taralay-impression-compact.pdf\nTitre : Fiche technique\n\n"
         "Taralay Impression Compact Acoustic 43 Classement UPEC : U4 P3 E2/3 C2 Réaction au feu Bfl-s1 "
         "Classement d'usage 34-43 Épaisseur totale 3,45 mm Épaisseur de couche d'usure 0,70 mm "
         "Efficacité acoustique ΔLw = 19 dB Poids total 2,9 kg/m² Avis Technique 12/19-1789_V1")
REVENDEUR = "Source : https://www.revendeur-sols.fr/taralay\nTitre : Taralay pas cher\n\nPrix bas, livraison 48 h."


async def web_search(query, user_id, agent_id, max_results=3, context=None):
    RECHERCHES.append(query)
    if query.startswith("site:gerflor.fr"):
        return {"success": True, "content": FICHE,
                "sources": ["https://www.gerflor.fr/docs/taralay-impression-compact.pdf"]}
    if "inconnu" in query:
        return {"success": False, "content": "", "sources": []}
    return {"success": True, "content": REVENDEUR, "sources": ["https://www.revendeur-sols.fr/taralay"]}


async def fetch_url(url, user_id, agent_id, reason="", capture=True):
    OUVERTURES.append(url)
    return {"success": True, "content": FICHE, "url": url}


tools = types.ModuleType("browser.tools")
tools.web_search, tools.fetch_url = web_search, fetch_url
sys.modules["browser"] = types.ModuleType("browser")
sys.modules["browser.tools"] = tools
spec = importlib.util.spec_from_file_location("skills.produits", BACKEND / "skills" / "produits.py")
pr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pr)
user = types.SimpleNamespace(id="u1", role="direction")

print("— Le geste fiche_produit")
verifier("marque reconnue dans le nom", pr.fabricant("Gerflor Taralay Impression") == ("gerflor", "gerflor.fr"))
verifier("« interface » ne se reconnaît pas dans « interfaces »", pr.fabricant("les interfaces") is None)
verifier("recherche la plus ciblée d'abord : le site du fabricant",
         pr.requetes("Taralay Impression", "Gerflor")[0].startswith("site:gerflor.fr"))
releve = {c["caracteristique"]: c["valeur"] for c in pr.relever(FICHE, "x")}
for nom, attendu in (("Classement UPEC", "U4 P3 E2/3 C2"), ("Classement au feu", "Bfl-s1"),
                     ("Classement d'usage (EN ISO 10874)", "34-43"), ("Épaisseur totale", "3,45 mm"),
                     ("Épaisseur de couche d'usure", "0,70 mm"), ("Efficacité acoustique (ΔLw)", "19 dB"),
                     ("Poids", "2,9 kg/m²"), ("Avis technique / DTA", "12/19-1789_V1")):
    verifier(f"relevé : {nom} = {attendu}", releve.get(nom) == attendu, releve.get(nom))
verifier("un texte sans fiche ne produit aucune valeur inventée", pr.relever(REVENDEUR, "x") == [])


async def scenario():
    r = await pr.fiche_produit({"produit": "Taralay Impression Compact Acoustic 43", "marque": "Gerflor"}, user)
    verifier("une seule recherche quand la fiche du fabricant est trouvée", len(RECHERCHES) == 1, RECHERCHES)
    verifier("la source principale est la fiche PDF du fabricant",
             str(r.get("source_principale", "")).endswith("taralay-impression-compact.pdf"), r.get("source_principale"))
    verifier("tableau garanti avec la source de chaque valeur",
             r.get("bloc_garanti") and all(row[2].startswith("https://www.gerflor.fr") for row in r["bloc_ui"]["rows"]))
    verifier("la consigne pousse aux alternatives vérifiées", "alternatives" in r.get("a_faire", ""))
    RECHERCHES.clear()
    r = await pr.fiche_produit({"produit": "produit inconnu"}, user)
    verifier("rien trouvé : dit, sans valeur, et propose d'autres voies",
             r.get("trouve") is False and "N'invente aucune" in r.get("a_faire", ""))
    r = await pr.fiche_produit({"url": "https://www.gerflor.fr/docs/fiche.pdf"}, user)
    verifier("une adresse donnée s'ouvre directement",
             OUVERTURES == ["https://www.gerflor.fr/docs/fiche.pdf"] and bool(r.get("caracteristiques")))
    r = await pr.fiche_produit({}, user)
    verifier("sans produit ni adresse : erreur claire", "erreur" in r)

asyncio.run(scenario())

print("\n— La garde du web automatique")
source = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
espace = {"AgentState": dict}
for noeud in ast.parse(source).body:
    if (isinstance(noeud, ast.Assign) and getattr(noeud.targets[0], "id", "") in
            ("_MOTS_INTERNES", "_MOTS_EXTERNES", "_POSSESSIFS", "_CARACTERISTIQUES_PUBLIQUES")) or (
            isinstance(noeud, ast.FunctionDef) and noeud.name == "should_use_browser"):
        exec(compile(ast.Module(body=[noeud], type_ignores=[]), "agent1", "exec"), espace)
sys.modules["config"] = types.SimpleNamespace(settings=types.SimpleNamespace(browser_enabled=True))
decider = espace["should_use_browser"]
for demande, attendu in (("la fiche technique du fournisseur Weber pour le mortier colle", "browser"),
                         ("quel est le classement UPEC du Taralay Impression ?", "browser"),
                         ("les factures du fournisseur Weber de septembre", "llm"),
                         ("l'épaisseur de chape prévue sur le chantier Mérignac", "llm"),
                         ("la fiche technique du devis Dupont", "llm")):
    verifier(f"« {demande[:48]} » → {attendu}", decider({"query": demande}) == attendu)

print("\n— Le relecteur")
spec = importlib.util.spec_from_file_location("verificateur", BACKEND / "agents" / "verificateur.py")
ve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ve)
verifier("« classé U4 P3 E2/3 C2 et Bfl-s1 » sans geste : relu",
         ve.a_verifier("Ce revêtement est classé U4 P3 E2/3 C2 et Bfl-s1.", False, False, False))
verifier("« efficacité de 19 dB » sans geste : relu", ve.a_verifier("Son efficacité est de 19 dB.", False, False, False))
verifier("« Bonjour, que puis-je faire ? » : pas relu", not ve.a_verifier("Bonjour, que puis-je faire ?", False, False, False))
texte_consigne = ve.consigne("d", "", "", "r", [])
verifier("la consigne exige la source d'une caractéristique (règle 7)",
         "fiche_produit" in texte_consigne and "CARACTÉRISTIQUE DE PRODUIT" in texte_consigne)

print("\n— Consigne et catalogue")
verifier("la consigne du modèle porte le réflexe",
         "LES PRODUITS SE VÉRIFIENT À LA SOURCE" in source and "FORCE DE PROPOSITION" in source)
verifier("fiche_produit rangé dans la famille web",
         '"naviguer", "fiche_produit"' in (BACKEND / "skills" / "familles.py").read_text(encoding="utf-8"))
verifier("résultat généreux (une fiche dépasse 4 000 caractères)", '"fiche_produit", "texte_de_loi", "jurisprudence"}' in source)
sug = (BACKEND / "agents" / "suggestions_metier.py").read_text(encoding="utf-8")
verifier("après la lecture d'un document : vérifier les fiches proposé",
         "Vérifie les fiches techniques des produits cités" in sug)

print(f"\n{'✅ tout passe' if not echecs else f'❌ {len(echecs)} échec(s)'}\n")
sys.exit(1 if echecs else 0)
