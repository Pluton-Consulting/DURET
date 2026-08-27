"""
Banc de la RECETTE DU 27/08 — ce que la vision montre, et ce qu'elle laisse.

Deux défauts relevés en direct dans le navigateur, sur la prod de Symbiose,
avec les dix questions du cahier de démonstration :

  * « analyse ce plan » rendait une belle analyse en français PUIS le JSON
    d'extraction recopié tel quel — un pavé d'accolades sur la moitié de
    l'écran. Le dirigeant à qui l'on montre l'outil y voit de la tuyauterie.

  * le tour d'APRÈS, dans le MÊME fil, répondait « je n'ai pas accès à cette
    analyse ». La vision écrivait sa réponse à l'écran et dans la table
    `messages` (le rechargement), mais jamais dans `state["messages"]` — d'où
    la mémoire de conversation tire sa fenêtre récente. Le commentaire du code
    promettait pourtant ce chemin pour retrouver la photo à retoucher : la
    promesse portait sur un mécanisme absent.

Ni base, ni réseau, ni LLM. Les fonctions d'affichage sont extraites du source
par AST (langchain n'est pas installé partout), et le contrat du nœud est
vérifié sur son ARBRE : ce qu'il retourne vraiment, pas ce qu'on en espère.

Les deux jeux d'essai ci-dessous sont les extractions RÉELLEMENT observées en
recette — l'une sans chiffrage (Q6), l'autre avec (Q10).
"""
import sys, ast, json, pathlib

BACKEND = sys.argv[1] if len(sys.argv) > 1 else "backend"
SOURCE = pathlib.Path(BACKEND) / "agents" / "agent2.py"

VERT, ROUGE, GRIS, RAZ = "\x1b[92m", "\x1b[91m", "\x1b[90m", "\x1b[0m"
echecs = 0


def controle(titre: str, ok: bool, detail: str = "") -> None:
    global echecs
    if ok:
        print(f"  {VERT}✓{RAZ} {titre}")
    else:
        echecs += 1
        print(f"  {ROUGE}✗{RAZ} {titre}" + (f"{GRIS} — {detail}{RAZ}" if detail else ""))


# ── Extraction des fonctions d'affichage, sans importer le module ─────
arbre = ast.parse(SOURCE.read_text(encoding="utf-8"))
espace: dict = {"json": json}
VOULUES = {"_bloc", "_libelle", "_valeur_texte", "_blocs_extraction"}
trouvees = set()
for noeud in arbre.body:
    if isinstance(noeud, ast.FunctionDef) and noeud.name in VOULUES:
        exec(compile(ast.Module([noeud], []), str(SOURCE), "exec"), espace)
        trouvees.add(noeud.name)
    if isinstance(noeud, ast.Assign):  # les tuples de clés reconnues
        for c in noeud.targets:
            if isinstance(c, ast.Name) and c.id.startswith("_CLES_"):
                exec(compile(ast.Module([noeud], []), str(SOURCE), "exec"), espace)

manquantes = VOULUES - trouvees
if manquantes:
    print(f"{ROUGE}Fonctions absentes du source : {', '.join(sorted(manquantes))}{RAZ}")
    sys.exit(1)
blocs_extraction = espace["_blocs_extraction"]


# ── Les extractions réellement observées en recette ───────────────────
Q6 = {
    "elements": ["Maison", "Terrasse bois", "Allée gravier", "Piscine", "Pelouse",
                 "Haie persistante"],
    "surfaces_m2": {"terrain_total": 812, "maison": 120, "terrasse_bois": 48,
                    "allee_gravier": 60, "piscine": 32, "pelouse": 280},
    "postes_travaux": ["Terrassement et préparation des sols",
                       "Installation de la piscine (structure, étanchéité, filtration)",
                       "Pose de la terrasse en bois et création de l'allée en gravier"],
    "contraintes": ["Dénivelé : non lisible", "Accès : non lisible"],
    "incertitudes": ["Ce plan est un schéma de principe"],
}
Q10 = {
    "elements": ["Maison", "Terrasse bois", "Piscine"],
    "surfaces_m2": {"surface_totale": 812, "terrasse_bois": 48,
                    "haie_persistante_ml": 45},
    "postes_travaux": [
        {"description": "Entretien et remise en état pelouse", "surface_m2": 280,
         "montant_euros": 840},
        {"description": "Entretien haie persistante", "longueur_ml": 45,
         "montant_euros": 675},
        {"description": "Total estimatif hors taxes", "montant_euros": 2295},
    ],
}


def blocs_de(texte: str) -> list[dict]:
    """Les objets réellement rendus par les balises ```ui du texte."""
    sortie, reste = [], texte
    while "```ui" in reste:
        deb = reste.index("```ui") + len("```ui")
        fin = reste.index("```", deb)
        sortie.append(json.loads(reste[deb:fin].strip()))
        reste = reste[fin + 3:]
    return sortie


print("\n\x1b[1mCE QUE LA VISION MONTRE — l'extraction en composants\x1b[0m\n")

for nom, jeu in (("Q6 — analyse de plan, sans chiffrage", Q6),
                 ("Q10 — interconnexion, avec chiffrage", Q10)):
    print(f"{GRIS}{nom}{RAZ}")
    rendu = blocs_extraction(jeu)
    blocs = blocs_de(rendu)

    # LE CONTRÔLE QUI COMPTE : plus une seule accolade hors d'un bloc balisé.
    hors_blocs = rendu
    for b in blocs:
        hors_blocs = hors_blocs.replace(json.dumps(b, ensure_ascii=False), "")
    controle("aucun JSON brut hors d'un bloc d'écran",
             "{" not in hors_blocs.replace("```ui", "").replace("```", ""),
             repr(hors_blocs[:120]))
    controle("les surfaces sortent en tableau",
             any(b.get("type") == "table" and "Surface" in str(b.get("titre", "")) for b in blocs))
    controle("les clés techniques sont mises en français",
             "terrasse_bois" not in rendu and "Terrasse bois" in rendu,
             "une clé brute reste à l'écran")
    controle("les postes de travaux sont rendus",
             any("oste" in str(b.get("titre", "")) for b in blocs))
    controle("tout bloc porte un type et ses champs requis",
             all(b.get("type") and (b.get("rows") or b.get("items")) for b in blocs))
    print()

# La forme change avec le jeu : une liste de phrases n'est pas un tableau.
controle("des postes en phrases donnent une liste",
         any(b.get("type") == "list" and "oste" in str(b.get("titre", ""))
             for b in blocs_de(blocs_extraction(Q6))))
controle("des postes déjà chiffrés donnent un tableau avec les montants",
         any(b.get("type") == "table" and "oste" in str(b.get("titre", ""))
             and any("2295" in str(c) or "2295 €" in str(c) for l in b["rows"] for c in l)
             for b in blocs_de(blocs_extraction(Q10))))

# Ce qui n'est pas reconnu ne doit pas ressortir en accolades faute de mieux.
inattendu = blocs_extraction({"choses_inconnues": {"a": 1}, "autre": [1, 2]})
controle("une extraction non reconnue n'affiche RIEN plutôt que du JSON",
         inattendu.strip() == "", repr(inattendu[:120]))
controle("une extraction vide ne casse pas", blocs_extraction({}) == ""
         and blocs_extraction(None) == "")

print("\n\x1b[1mCE QUE LA VISION LAISSE — l'analyse entre dans le fil\x1b[0m\n")

# Le contrat du nœud se lit sur son ARBRE : on vérifie ce qu'il RETOURNE.
noeud = next((n for n in ast.walk(arbre)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "prechiffrage_node"), None)
controle("le nœud prechiffrage_node existe", noeud is not None)
if noeud:
    cles = set()
    for r in [n for n in ast.walk(noeud) if isinstance(n, ast.Return)]:
        if isinstance(r.value, ast.Dict):
            cles |= {k.value for k in r.value.keys if isinstance(k, ast.Constant)}
    controle("il rend `messages` — c'est ce que lit la mémoire de conversation",
             "messages" in cles, f"clés rendues : {sorted(cles)}")
    controle("il rend `entity_map` — la carte du fil reste cumulative",
             "entity_map" in cles)
    controle("il rend toujours `final_response`", "final_response" in cles)

    src = ast.get_source_segment(SOURCE.read_text(encoding="utf-8"), noeud) or ""
    controle("le texte archivé est MASQUÉ (aucune PII dans le checkpoint)",
             "anonymizer.anonymize" in src)
    # LA QUESTION EST LE PIÈGE : le graphe de la vision n'a aucun nœud
    # d'anonymisation, donc `anonymized_query` y est toujours vide. Masquer la
    # seule analyse laissait passer « le plan de M. Untel » dans le checkpoint.
    controle("la QUESTION est masquée elle aussi, pas seulement l'analyse",
             "anonymize_chunks" in src and "[question, summary]" in src)
    controle("les deux textes partagent un seul appel (même jeton, même valeur)",
             src.count("to_thread") == 1)
    controle("le masquage sort de la boucle événementielle (spaCy est CPU-bound)",
             "to_thread" in src)
    controle("un masquage indisponible ne perd pas le tour",
             "except" in src and src.count("return") >= 2)
    controle("le JSON brut a bien quitté la réponse",
             "Éléments extraits" not in src and "indent=2" not in src)

print()
if echecs:
    print(f"{ROUGE}{echecs} contrôle(s) en échec.{RAZ}")
    sys.exit(1)
print(f"{VERT}Tous les contrôles passent.{RAZ}")
