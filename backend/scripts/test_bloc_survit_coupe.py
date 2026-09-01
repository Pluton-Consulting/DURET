"""
Banc « le bloc garanti survit à la coupe du résultat » — 01/09, audit avant déploiement.

DÉFAUT TROUVÉ. Le résultat d'un skill est tranché avant de repartir vers le
modèle (PLAFOND_RESULTAT = 4 000, ou 12 000 pour les skills « généreux »), et
`_blocs_garantis` relisait le bloc d'écran DANS ce JSON tronqué. Mesuré : une
page de recherche Drive (40 résultats) pèse ~12 000 caractères, une page de
publipostage (40 cartes) ~14 000. Le JSON était donc coupé en plein milieu,
`json.loads` échouait, et l'écran n'affichait RIEN — alors que le skill avait
réussi et que sa consigne interdit au modèle de recopier le contenu.

Ce banc prouve : le bloc est mis DE CÔTÉ avant la coupe et masqué à part
(`bloc_garanti_masque`), `_blocs_garantis` le lit en priorité, les résultats
ne portent plus les données en double, et les nouveaux skills ont droit au
plafond généreux.
"""
import ast
import importlib.util
import json
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
        elif isinstance(n, ast.Import) and any(
                (a.asname or a.name) in noms for a in n.names):
            gardes.append(n)
    exec(compile(ast.Module(body=gardes, type_ignores=[]), str(chemin), "exec"), espace)
    manquants = [x for x in noms if x not in espace]
    assert not manquants, f"absent du module livré : {manquants}"
    return espace


print(f"\n═══ LE BLOC GARANTI SURVIT À LA COUPE — {BACKEND.resolve().parent}\n")

# ── 1. Les tailles RÉELLES, sur les vrais modules ────────────────────────
spec = importlib.util.spec_from_file_location("aff_coupe", BACKEND / "skills" / "affichage.py")
aff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aff)

agent1_src = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
PLAF = int(re.search(r"PLAFOND_RESULTAT = (\d+)", agent1_src).group(1))
PLAF_G = int(re.search(r"PLAFOND_RESULTAT_GENEREUX = (\d+)", agent1_src).group(1))

# Une page pleine de recherche : 40 trouvailles aux chemins réalistes.
recherche = aff.garantir_recherche(
    {"motif": "durand", "nombre": 95, "page": 1, "pages": 3,
     "resultats": [{"nom": f"33 LACANAU DE MIOS - DURAND dossier {i}",
                    "chemin": f"Symbiose Paysage/2-PROJETS/Contrats d'entretien/PISCINE/dossier {i}",
                    "dossier": i % 2 == 0} for i in range(40)]}, "durand")
taille_r = len(json.dumps(recherche, ensure_ascii=False, default=str))
verifier(f"recherche (40 résultats) : le résultat tient dans le plafond généreux ({taille_r} car.)",
         taille_r <= PLAF_G, f"{taille_r} > {PLAF_G}")
verifier("le résultat ne porte plus les résultats EN DOUBLE (rows suffit)",
         "resultats" not in recherche)

apercu = aff.garantir_apercu(
    {"total_dossiers": 80, "total_fichiers": 300,
     "detail": [{"dossier": f"racine{j}", "dossiers": 40, "fichiers": 150,
                 "octets_total": 3355443, "types_de_fichiers": {"pdf": 90, "dwg": 60},
                 "noms_des_dossiers": [f"33 COMMUNE - CLIENT NOM {i}" for i in range(40)]}
                for j in range(2)]}, "le Drive")
taille_a = len(json.dumps(apercu, ensure_ascii=False, default=str))
verifier(f"aperçu (2 racines × 40 dossiers) : sous le plafond généreux ({taille_a} car.)",
         taille_a <= PLAF_G, f"{taille_a} > {PLAF_G}")
verifier("l'aperçu ne porte plus le détail EN DOUBLE",
         "detail" not in apercu and "emplacements" not in apercu)

publi = None
chemin_publi = BACKEND / "mail" / "publipostage.py"
if chemin_publi.exists():
    spec2 = importlib.util.spec_from_file_location("publi_coupe", chemin_publi)
    pub = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(pub)
    cartes = pub.construire_cartes(
        "Relance {nom}", "Bonjour {nom},\n\nnous revenons vers vous au sujet de votre "
        "projet d'aménagement. Restons à votre disposition.\n\nCordialement,",
        [{"email": f"client{i}@exemple.fr", "nom": f"Client Numéro {i}"} for i in range(100)])
    publi = {"nombre": 100, "page": 1, "pages": 3,
             "bloc_ui": {"type": "reponses_mail", "titre": "Envois préparés",
                         "reponses": cartes["cartes"]},
             "bloc_garanti": True}
    taille_p = len(json.dumps(publi, ensure_ascii=False, default=str))
    # Le publipostage DÉPASSE volontairement : c'est justement pourquoi le bloc
    # doit voyager hors de la coupe. On vérifie que la mécanique le sauve.
    verifier(f"publipostage (40 cartes) : mesuré à {taille_p} car. — dépasse bien le plafond simple",
             taille_p > PLAF)

# ── 2. La mécanique : le bloc est mis de côté AVANT la coupe ─────────────
verifier("tools_node extrait le bloc garanti avant de couper",
         re.search(r"bloc_garanti = \(sortie\.get\(\"bloc_ui\"\)\s*\n\s*if isinstance\(sortie, dict\)"
                   r" and sortie\.get\(\"bloc_garanti\"\)", agent1_src))
verifier("il est masqué DANS LE MÊME appel (une seule carte de jetons)",
         re.search(r"anonymizer\.anonymize_chunks,\s*\n\s*\[contenu, _json\.dumps\(bloc_garanti",
                   agent1_src))
verifier("il est rangé à part dans le résultat (`bloc_garanti_masque`)",
         '"bloc_garanti_masque"' in agent1_src)
verifier("un échec de skill ne laisse pas un bloc d'un appel précédent",
         re.search(r"contenu, ok, bloc_garanti = f\"ERREUR", agent1_src))
verifier("les nouveaux skills ont droit au plafond généreux",
         all(s in agent1_src.split("RESULTATS_GENEREUX")[1][:400]
             for s in ('"drive_chercher"', '"nas_chercher"', '"drive_apercu"',
                       '"nas_apercu"', '"preparer_envois"')))

# ── 3. `_blocs_garantis` lit la voie sûre, MÊME si le résultat est coupé ─
espace = {"_tracer_filet": lambda *a, **k: None, "AgentState": dict}
extraire(BACKEND / "agents" / "agent1.py",
         {"_blocs_garantis", "_blocs_de", "_designe_le_meme", "_plat_nom",
          "_signature_bloc", "_re_livrables", "_BLOC_UI_RE"}, espace)
garantir = espace["_blocs_garantis"]

bloc = recherche["bloc_ui"]
resultat_coupe = json.dumps({"bloc_garanti": True, "bloc_ui": bloc},
                            ensure_ascii=False)[:PLAF]      # tronqué, illisible
etat = {"tool_results": [{"skill": "drive_chercher", "ok": True,
                          "resultat_masque": resultat_coupe,
                          "bloc_garanti_masque": json.dumps(bloc, ensure_ascii=False)}]}
sortie = garantir("Voici ce que j'ai trouvé.", etat)
verifier("résultat TRONQUÉ mais bloc rangé à part → le tableau s'affiche quand même",
         '"type": "table"' in sortie and "DURAND dossier 39" in sortie)

etat_sans = {"tool_results": [{"skill": "drive_chercher", "ok": True,
                               "resultat_masque": resultat_coupe}]}
verifier("sans la voie sûre, le résultat tronqué ne rend RIEN (le défaut d'origine)",
         garantir("Voici.", etat_sans) == "Voici.")

# ── 4. La charpente n'est plus prise pour du contenu ─────────────────────
etat_t = {"tool_results": [{"skill": "drive_chercher", "ok": True,
                            "resultat_masque": "{}",
                            "bloc_garanti_masque": json.dumps(
                                {"type": "table", "titre": "Recherche — durand",
                                 "columns": ["Nom", "Type", "Emplacement"],
                                 "rows": [["Dossier DURAND", "Dossier", "Clients/DURAND"],
                                          ["devis durand.pdf", "Fichier", "Clients/DURAND"]]},
                                ensure_ascii=False)}]}
legitime = json.dumps({"type": "table", "titre": "Pièces du dossier",
                       "columns": ["Nom", "Type", "Taille"],
                       "rows": [["Devis Durand 2025.pdf", "Fichier", "3 Mo"]]},
                      ensure_ascii=False)
s = garantir("Deux tableaux :\n\n```ui\n" + legitime + "\n```", etat_t)
verifier("un tableau LÉGITIME et différent n'est plus effacé par la charpente commune",
         "Pièces du dossier" in s and s.count("```ui") == 2)
copie = json.dumps({"type": "table", "columns": ["Nom", "Type", "Emplacement"],
                    "rows": [["Dossier DURAND", "Dossier", "Clients/DURAND"]]},
                   ensure_ascii=False)
s2 = garantir("Voici :\n\n```ui\n" + copie + "\n```", etat_t)
verifier("une vraie COPIE partielle du bloc garanti s'efface toujours",
         s2.count("```ui") == 1 and "devis durand.pdf" in s2)

# ── 5. Les titres atteignent enfin l'écran ───────────────────────────────
FRONT = BACKEND.resolve().parent / "frontend"
st = (FRONT / "components" / "blocks" / "tables" / "SimpleTable.tsx").read_text(encoding="utf-8")
verifier("SimpleTable reçoit ET affiche `titre` (« Recherche — durand »)",
         "titre?: string" in st and "{titre}" in st)
rend = (FRONT / "components" / "chat" / "MessageRenderer.tsx").read_text(encoding="utf-8")
verifier("le renderer passe `titre` à ReponsesMail",
         "<ReponsesMail titre={p.titre}" in rend)
rm = (FRONT / "components" / "blocks" / "business" / "ReponsesMail.tsx").read_text(encoding="utf-8")
verifier("ReponsesMail accepte et affiche `titre`",
         "titre?: string" in rm and "{titre}" in rm)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
