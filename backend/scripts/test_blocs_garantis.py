"""
Banc « blocs garantis » — l'arborescence et l'aperçu s'affichent en mécanique.

Relevé par Noa le 01/09 sur la prod Symbiose : « liste les dossiers du Drive »
→ une carte de document inventée (« TXT — Arborescence du Drive ») sans rien à
lire ; « montre-moi 33 LA TESTE DE BUCH » → un tableau d'aperçu aux lignes
inventées (« Autres dossiers éventuels… (voir arborescence) »). Le catalogue
demandait au modèle de RECOPIER le `schema` : il ne le fait pas.

Ce banc prouve : `skills/affichage.py` construit les blocs mécaniques (arbre,
fiche + noms) dans les deux formes (Drive et NAS), la coupe d'un schéma trop
long se fait à la ligne et se dit, `_blocs_garantis` (agent1) restitue les
blocs absents de la rédaction et efface la carte inventée qui les désigne, les
catalogues ne demandent plus de recopier, et le frontend rend le type `arbre`
avec une largeur de bloc UNIFIÉE (`--bloc-largeur`) — plus de composants en
escalier.
"""
import ast
import importlib.util
import json
import pathlib
import re
import sys

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
FRONTEND = (BACKEND.resolve().parent / "frontend")
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def extraire(chemin, noms, espace):
    """Exécute, du module livré, les seules définitions demandées."""
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


print(f"\n═══ BLOCS GARANTIS — {BACKEND.resolve().parent}\n")

# ── 1. skills/affichage.py : les constructeurs mécaniques ────────────────
spec = importlib.util.spec_from_file_location("affichage_banc", BACKEND / "skills" / "affichage.py")
verifier("le module skills/affichage.py existe", spec is not None and (BACKEND / "skills" / "affichage.py").exists())
aff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aff)

r = aff.garantir_arborescence(
    {"schema": "Drive\n├─ 33 LA TESTE DE BUCH\n│  └─ Davy SAINT LAURENT",
     "dossiers_total": 12, "fichiers_total": 340, "complet": True}, "du Drive")
bloc = r.get("bloc_ui") or {}
verifier("arborescence → bloc `arbre` mécanique, titré, avec le schéma",
         bloc.get("type") == "arbre" and "Arborescence du Drive" in str(bloc.get("titre"))
         and "33 LA TESTE DE BUCH" in str(bloc.get("schema")))
verifier("le résultat porte `bloc_garanti` et un message_final chiffré",
         r.get("bloc_garanti") is True and "12 dossiers" in str(r.get("message_final")))
verifier("le `schema` ne vit plus qu'au bloc (pas en double dans le résultat)",
         "schema" not in r)
verifier("a_faire : déjà affichée, jamais un document",
         "DÉJÀ affichée" in str(r.get("a_faire")) and "document" in str(r.get("a_faire")))

long = "\n".join(f"├─ dossier {i}" for i in range(1200))
r2 = aff.garantir_arborescence({"schema": long, "dossiers_total": 1200, "complet": True}, "du Drive")
schema2 = str((r2.get("bloc_ui") or {}).get("schema"))
verifier("un schéma trop long est coupé À LA LIGNE, sous le plafond",
         len(schema2) <= aff.MAX_SCHEMA_BLOC and schema2.endswith(tuple(f"dossier {i}" for i in range(1200))))
verifier("la coupe est DITE (sous-titre + a_faire)",
         "affichage coupé" in str((r2.get("bloc_ui") or {}).get("sous_titre"))
         and "coupé" in str(r2.get("a_faire")))
r3 = aff.garantir_arborescence({"note": "rien"}, "du Drive")
verifier("sans schéma, rien n'est garanti", "bloc_garanti" not in r3 and "bloc_ui" not in r3)

# La forme Drive (detail/dossier) et la forme NAS (emplacements/chemin).
apercu_drive = aff.garantir_apercu(
    {"total_dossiers": 2, "total_fichiers": 31,
     "detail": [{"dossier": "id1", "dossiers": 2, "fichiers": 31, "octets_total": 3355443,
                 "types_de_fichiers": {"pdf": 20, "dwg": 5},
                 "noms_des_dossiers": ["33 LA TESTE DE BUCH - Davy SAINT LAURENT"]}]},
    "« 33 LA TESTE DE BUCH »")
blocs = apercu_drive.get("bloc_ui") or []
kv = blocs[0] if blocs else {}
verifier("aperçu (forme Drive) → fiche keyvalue + liste des sous-dossiers",
         len(blocs) == 2 and kv.get("type") == "keyvalue" and blocs[1].get("type") == "list"
         and "33 LA TESTE DE BUCH - Davy SAINT LAURENT" in blocs[1].get("items", []))
lignes = {k: v for k, v in (kv.get("rows") or [])}
verifier("la fiche porte les comptes EXACTS, la taille lisible et les types",
         lignes.get("Sous-dossiers") == "2" and lignes.get("Fichiers") == "31"
         and "Mo" in str(lignes.get("Taille")) and "pdf ×20" in str(lignes.get("Types de fichiers")))
verifier("le keyvalue porte un titre (pour reconnaître la carte inventée qui le désigne)",
         "33 LA TESTE DE BUCH" in str(kv.get("titre")))
apercu_nas = aff.garantir_apercu(
    {"total_dossiers": 3, "total_fichiers": 10,
     "emplacements": [{"chemin": "/home/Drive", "dossiers": 3, "fichiers": 10,
                       "octets_total": 0, "types_de_fichiers": {"xlsx": 4},
                       "noms_des_dossiers": ["CHANTIERS", "DEVIS"]}]}, "le serveur")
verifier("aperçu (forme NAS) → mêmes blocs mécaniques",
         apercu_nas.get("bloc_garanti") is True
         and "CHANTIERS" in (apercu_nas["bloc_ui"][1].get("items") or []))
verifier("octets_lisibles : 512 → « 512 o », 2048 → « 2,0 Ko »",
         aff.octets_lisibles(512) == "512 o" and aff.octets_lisibles(2048) == "2,0 Ko")

# ── 2. agent1 : le garde-fou restitue et efface ─────────────────────────
espace = {"_tracer_filet": lambda *a, **k: None, "AgentState": dict}
extraire(BACKEND / "agents" / "agent1.py",
         {"_blocs_garantis", "_blocs_de", "_designe_le_meme", "_plat_nom",
          "_signature_bloc", "_re_livrables", "_BLOC_UI_RE"}, espace)
garantir = espace["_blocs_garantis"]
arbre_bloc = {"type": "arbre", "titre": "Arborescence du Drive", "schema": "Drive\n├─ A\n├─ B"}
resultat_skill = json.dumps({"bloc_garanti": True, "bloc_ui": arbre_bloc}, ensure_ascii=False)
etat = {"tool_results": [{"skill": "drive_arborescence", "ok": True,
                          "resultat_masque": resultat_skill}]}

invente = json.dumps({"type": "doc_apercu", "titre": "Arborescence du Drive",
                      "format": "txt", "extrait": "Structure complète des dossiers"},
                     ensure_ascii=False)
sortie = garantir("Voici l'arborescence complète du Drive.\n\n```ui\n" + invente + "\n```", etat)
verifier("la carte de document inventée est EFFACÉE", "doc_apercu" not in sortie)
verifier("le bloc `arbre` mécanique est RESTITUÉ à l'écran",
         '"type": "arbre"' in sortie and "├─ A" in sortie)
deja = "Voici.\n\n```ui\n" + json.dumps(arbre_bloc, ensure_ascii=False) + "\n```"
verifier("un bloc déjà recopié par le modèle n'est pas doublé",
         garantir(deja, etat).count("```ui") == 1)
verifier("sans `bloc_garanti`, le texte ne bouge pas",
         garantir("Réponse simple.", {"tool_results": [{"ok": True, "resultat_masque": "{}"}]})
         == "Réponse simple.")
deux = json.dumps({"bloc_garanti": True, "bloc_ui": [
    {"type": "keyvalue", "titre": "Aperçu — « X »", "rows": [["Sous-dossiers", "2"]]},
    {"type": "list", "items": ["A", "B"]}]}, ensure_ascii=False)
sortie2 = garantir("Voici l'aperçu.", {"tool_results": [{"ok": True, "resultat_masque": deux}]})
verifier("PLUSIEURS blocs garantis s'affichent tous", sortie2.count("```ui") == 2)

# LE DOUBLON DE PROD (01/09 au soir) : la recherche Drive répond bien, mais le
# modèle RECONSTRUIT sa propre version du tableau depuis les données (lignes en
# moins, champ reformulé) — signature différente, et le bloc mécanique
# s'ajoutait À CÔTÉ. La copie dégradée doit s'effacer, la complète rester SEULE.
table = {"type": "table", "titre": "Recherche — durand",
         "columns": ["Nom", "Type", "Emplacement"],
         "rows": [["Dossier DURAND", "Dossier", "Clients/DURAND"],
                  ["devis durand.pdf", "Fichier", "Clients/DURAND"],
                  ["facture durand.pdf", "Fichier", "Clients/DURAND/2026"]]}
etat_t = {"tool_results": [{"ok": True, "resultat_masque": json.dumps(
    {"bloc_garanti": True, "bloc_ui": table}, ensure_ascii=False)}]}
copie_partielle = json.dumps({"type": "table",
                              "columns": ["Nom", "Type", "Emplacement"],
                              "rows": table["rows"][:2]}, ensure_ascii=False)
s = garantir("Voici les résultats :\n\n```ui\n" + copie_partielle + "\n```", etat_t)
verifier("la copie PARTIELLE du modèle s'efface : UN seul composant, le complet",
         s.count("```ui") == 1 and "facture durand.pdf" in s)
s2 = garantir("Voici :\n\n```ui\n" + json.dumps(table, ensure_ascii=False) + "\n```", etat_t)
verifier("la copie EXACTE reste en place, sans doublon", s2.count("```ui") == 1)
autre = json.dumps({"type": "table", "columns": ["Mois", "CA"],
                    "rows": [["janvier", "12 000"], ["février", "9 000"]]},
                   ensure_ascii=False)
s3 = garantir("Deux choses :\n\n```ui\n" + autre + "\n```", etat_t)
verifier("un tableau SANS RAPPORT n'est pas pris pour une copie : il reste, plus le garanti",
         s3.count("```ui") == 2 and "janvier" in s3)
double_res = {"tool_results": [etat_t["tool_results"][0], dict(etat_t["tool_results"][0])]}
verifier("le même résultat garanti DEUX fois dans le tour n'affiche qu'un bloc",
         garantir("Voici.", double_res).count("```ui") == 1)

agent1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("le garde-fou est branché entre les livrables et le dédoublonnage",
         re.search(r"_livrables_a_l_ecran\(text, state\).*?_blocs_garantis\(text, state\).*?"
                   r"_dedoublonner_blocs\(text\)", agent1, re.S))

# ── 3. Les skills et catalogues ne demandent plus de recopier ────────────
outils = (BACKEND / "skills" / "outils.py").read_text(encoding="utf-8")
verifier("les skills d'arborescence et d'aperçu passent par skills/affichage.py",
         "garantir_arborescence" in outils and "garantir_apercu" in outils)
verifier("le catalogue dit S'AFFICHE AUTOMATIQUEMENT, plus jamais « recopie-le TEL QUEL »",
         "S'AFFICHE AUTOMATIQUEMENT" in outils and "recopie-le TEL QUEL" not in outils)
module_outils = next(p for p in (BACKEND / "outils" / "drive.py", BACKEND / "outils" / "nas.py")
                     if p.exists())
verifier("la note du collecteur ne demande plus de recopier le schéma",
         "Recopie le `schema` TEL QUEL" not in module_outils.read_text(encoding="utf-8"))

# ── 4. Frontend : le type `arbre` et la largeur unifiée ─────────────────
arbre_tsx = FRONTEND / "components" / "blocks" / "text" / "Arbre.tsx"
verifier("le composant Arbre existe (monospace, défilement, largeur commune)",
         arbre_tsx.exists() and "pre" in arbre_tsx.read_text(encoding="utf-8")
         and "--bloc-largeur" in arbre_tsx.read_text(encoding="utf-8"))
renderer = (FRONTEND / "components" / "chat" / "MessageRenderer.tsx").read_text(encoding="utf-8")
verifier("MessageRenderer rend le type `arbre` et exige son schéma",
         'case "arbre"' in renderer and 'arbre: ["schema"]' in renderer)
verifier("la bibliothèque exporte Arbre",
         'export * from "./text/Arbre"' in (FRONTEND / "components" / "blocks" / "index.ts")
         .read_text(encoding="utf-8"))
verifier("theme.css porte le jeton --bloc-largeur",
         "--bloc-largeur" in (FRONTEND / "app" / "theme.css").read_text(encoding="utf-8"))
motif_durs = re.compile(r"maxWidth: (\d+)(?![%\d])")
restants = []
for f in sorted((FRONTEND / "components" / "blocks").glob("*/*.tsx")):
    restants += [f"{f.name}:{n}" for n in motif_durs.findall(f.read_text(encoding="utf-8"))]
restants += [f"MessageRenderer:{n}" for n in motif_durs.findall(renderer)]
verifier("plus AUCUNE largeur de bloc en dur : tous sur le jeton commun",
         not restants, ", ".join(restants))

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
