#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Compteur de derive entre les deux depots jumeaux (Symbiose / Duret & Sols).

But : transformer « on ne sait plus a quel point les deux depots ont diverge »
en un nombre reproductible, et etablir fichier par fichier ce qui doit converger
et ce qui doit legitimement differer.

Le moteur est en Python, et les deux entrees (derive.sh, derive.ps1) l'appellent.
C'est deliberement UNE seule implementation : deux implementations paralleles
(sh + PowerShell) finiraient par rendre deux chiffres differents, et un compteur
qui varie ne mesure rien. Python est deja une dependance dure du projet (le
backend est en FastAPI), donc cela n'ajoute rien a installer.

Ce script est en LECTURE SEULE. Il n'ecrit dans aucun des deux depots.

Classement de chaque fichier commun aux deux depots :

  IDENTIQUE  les deux contenus sont egaux une fois les fins de ligne
             neutralisees (CRLF -> LF, et une seule fin de ligne finale).
             C'etait le bruit qui rendait tout diff illisible : un fichier
             annoncait 917 lignes changees quand 4 l'etaient.

  MARQUE     les deux contenus deviennent egaux une fois appliquee la table de
             marque (derive.marque.txt) : nom d'entreprise, domaine, couleurs,
             identifiants de stockage, vocabulaire metier. Ces fichiers sont
             mutualisables tels quels, la marque n'ayant qu'a sortir dans une
             configuration par client.

  REELLE     il reste une difference apres neutralisation ET apres marque.
             C'est de la derive au sens strict : soit un correctif applique
             d'un seul cote, soit une divergence voulue - et dans ce second cas
             elle doit figurer dans derive.declaration.txt.

Code de sortie : 0 si toute divergence reelle est declaree, 1 sinon. De quoi le
brancher un jour en verification automatique.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
from pathlib import Path

# --------------------------------------------------------------------------
# Perimetres compares.
#
# Volontairement explicites plutot que « tout le depot » : les arbres
# d'installation (node_modules, .venv, .next) et les artefacts (__pycache__,
# builds) ne sont pas du code source, et les inclure ferait varier le compteur
# selon l'etat des machines. Un perimetre qui depend de qui a lance `npm i`
# ne mesure rien non plus.
# --------------------------------------------------------------------------
PERIMETRES = [
    {
        "nom": "backend",
        # (chemin, recursif)
        "racines": [("backend", True)],
        "extensions": [".py"],
    },
    {
        "nom": "frontend",
        "racines": [("frontend", True)],
        "extensions": [".ts", ".tsx", ".css", ".js", ".mjs", ".cjs", ".json"],
    },
    {
        "nom": "deploiement",
        # Ce que l'on installe autour du code : compose, reverse-proxy,
        # scripts de mise en route, notes d'exploitation. C'est la que la
        # derive se voit le plus tard - un depot se deploie encore, l'autre
        # non - donc autant la compter des maintenant.
        #
        # `scripts/` en fait partie, et cela inclut ce compteur lui-meme. Ce
        # n'est pas une curiosite : `derive.marque.txt` et
        # `derive.declaration.txt` doivent rester identiques dans les deux
        # depots, sinon les deux cotes ne mesurent plus la meme chose. Le
        # compteur surveille donc sa propre configuration.
        "racines": [(".", False), ("nginx", True), ("caddy", True), ("scripts", True)],
        "extensions": [".yml", ".yaml", ".sh", ".ps1", ".conf", ".md", ".py", ".txt"],
    },
]

# Repertoires jamais parcourus, quel que soit le perimetre.
DOSSIERS_EXCLUS = {
    "node_modules", ".next", ".venv", "venv", "__pycache__", ".git",
    "dist", "build", ".turbo", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "coverage", ".vercel", "out", "site-packages", ".idea", ".vscode",
}

# Fichiers jamais compares : ils ne decrivent pas le produit, ils decrivent
# l'etat local d'une machine ou d'un secret.
FICHIERS_EXCLUS = {
    ".env", ".env.local", "prod.env", "CREDENTIALS.env",
}

# Sous-arbres produits par une execution, pas ecrits a la main. Les comparer
# reviendrait a mesurer qui a lance quoi en dernier, pas la derive du code.
CHEMINS_EXCLUS = (
    "frontend/e2e/resultats/",
)

SEPARATEUR_MARQUE = "=>"


# --------------------------------------------------------------------------
# Lecture des fichiers de configuration versionnes
# --------------------------------------------------------------------------

def lire_table_marque(chemin: Path) -> list[tuple[str, re.Pattern, str]]:
    """
    Lit derive.marque.txt.

    Format, une regle par ligne :   <expression reguliere> => <jeton>
    Les sections [nom] regroupent les regles par categorie, ce qui permet au
    rapport de dire QUELLE facette de la marque explique un fichier.

    Chaque regle est appliquee aux DEUX cotes. La symetrie est donc structurelle :
    il n'y a pas de « cote Symbiose » et de « cote Duret » dans la table, juste
    des motifs qui se replient tous sur le meme jeton neutre. Un depot tiers
    s'ajouterait sans toucher au moteur.
    """
    regles: list[tuple[str, re.Pattern, str]] = []
    section = "divers"
    for numero, ligne in enumerate(chemin.read_text(encoding="utf-8").splitlines(), 1):
        nue = ligne.strip()
        if not nue or nue.startswith("#"):
            continue
        if nue.startswith("[") and nue.endswith("]"):
            section = nue[1:-1].strip()
            continue
        if SEPARATEUR_MARQUE not in nue:
            raise SystemExit(
                f"{chemin}:{numero} : regle sans « {SEPARATEUR_MARQUE} » -> {nue!r}"
            )
        motif, jeton = nue.rsplit(SEPARATEUR_MARQUE, 1)
        motif, jeton = motif.strip(), jeton.strip()
        try:
            compile_ = re.compile(motif)
        except re.error as err:
            raise SystemExit(f"{chemin}:{numero} : expression illisible ({err})")
        regles.append((section, compile_, jeton))
    return regles


def lire_declaration(chemin: Path) -> list[tuple[str, str, str]]:
    """
    Lit derive.declaration.txt : la liste des divergences LEGITIMES.

    Format, une entree par ligne :   <chemin ou motif>   # <raison>
    Les sections [nom] servent uniquement a la lecture humaine.

    Un motif accepte `*` (ne traverse pas les `/`) et `**` (traverse).
    """
    entrees: list[tuple[str, str, str]] = []
    section = "divers"
    for numero, ligne in enumerate(chemin.read_text(encoding="utf-8").splitlines(), 1):
        nue = ligne.strip()
        if not nue or nue.startswith("#"):
            continue
        if nue.startswith("[") and nue.endswith("]"):
            section = nue[1:-1].strip()
            continue
        motif, _, raison = nue.partition("#")
        motif = motif.strip().replace("\\", "/")
        raison = raison.strip()
        if not motif:
            raise SystemExit(f"{chemin}:{numero} : entree sans chemin")
        entrees.append((section, motif, raison))
    return entrees


def motif_vers_regex(motif: str) -> re.Pattern:
    """
    Traduit un motif de declaration en expression reguliere.

    `**` traverse les separateurs, `*` s'arrete au `/`, `?` vaut un caractere.
    Un motif qui se termine par `/` couvre tout le sous-arbre.
    """
    if motif.endswith("/"):
        motif += "**"
    sortie, i = [], 0
    while i < len(motif):
        c = motif[i]
        if c == "*":
            if motif[i:i + 2] == "**":
                sortie.append(".*")
                i += 2
                continue
            sortie.append("[^/]*")
        elif c == "?":
            sortie.append("[^/]")
        else:
            sortie.append(re.escape(c))
        i += 1
    return re.compile("^" + "".join(sortie) + "$")


# --------------------------------------------------------------------------
# Parcours et normalisation
# --------------------------------------------------------------------------

def lister(depot: Path, perimetre: dict) -> set[str]:
    """Chemins relatifs au depot, en `/`, pour un perimetre donne."""
    racine_depot = depot.resolve()
    extensions = set(perimetre["extensions"])
    trouves: set[str] = set()

    for sous_chemin, recursif in perimetre["racines"]:
        base = (racine_depot / sous_chemin).resolve()
        if not base.is_dir():
            continue
        for dossier, sous_dossiers, fichiers in os.walk(base):
            if recursif:
                sous_dossiers[:] = sorted(
                    d for d in sous_dossiers
                    if d not in DOSSIERS_EXCLUS and not d.startswith(".")
                )
            else:
                sous_dossiers[:] = []
            for nom in fichiers:
                if nom in FICHIERS_EXCLUS or Path(nom).suffix not in extensions:
                    continue
                relatif = (Path(dossier) / nom).resolve().relative_to(racine_depot).as_posix()
                if relatif.startswith(CHEMINS_EXCLUS):
                    continue
                trouves.add(relatif)
    return trouves


def neutraliser_fins_de_ligne(brut: bytes) -> str:
    """
    Le seul bruit qu'on efface avant de parler de difference.

    CRLF et CR isoles deviennent LF, et la fin de fichier est ramenee a
    exactement une fin de ligne. Rien d'autre n'est touche : une espace en fin
    de ligne ou une indentation changee restent des differences reelles.
    `surrogateescape` garantit qu'un octet non-UTF-8 ne fausse pas la
    comparaison au lieu de faire echouer la lecture.
    """
    texte = brut.replace(b"\r\n", b"\n").replace(b"\r", b"\n").decode(
        "utf-8", errors="surrogateescape"
    )
    return texte.rstrip("\n") + "\n" if texte else ""


def nombre_de_lignes_divergentes(a: str, b: str) -> int:
    """
    Taille de la divergence, une fois le bruit ote : le nombre de lignes qui
    changent vraiment. C'est le chiffre qui permet de trier le travail - trois
    lignes se recollent en une passe, deux cents demandent une decision.
    """
    total = 0
    for etiquette, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, a.splitlines(), b.splitlines(), autojunk=False).get_opcodes():
        if etiquette != "equal":
            total += max(i2 - i1, j2 - j1)
    return total


def neutraliser_marque(texte: str, regles) -> tuple[str, set[str]]:
    """Applique la table de marque et retourne le texte neutre + les categories touchees."""
    categories: set[str] = set()
    for section, motif, jeton in regles:
        texte, nombre = motif.subn(jeton, texte)
        if nombre:
            categories.add(section)
    return texte, categories


# --------------------------------------------------------------------------
# Mesure
# --------------------------------------------------------------------------

def mesurer(ici: Path, autre: Path, regles, declaration, detail: bool = False) -> dict:
    declaration_regex = [(s, m, r, motif_vers_regex(m)) for s, m, r in declaration]
    motifs_utilises: set[str] = set()

    def declare(chemin: str) -> str | None:
        for _section, motif, raison, regex in declaration_regex:
            if regex.match(chemin):
                motifs_utilises.add(motif)
                return raison or "(sans raison notee)"
        return None

    resultat = {"perimetres": [], "reelles_a_traiter": [], "orphelins_a_traiter": []}
    total = {"communs": 0, "identiques": 0, "marque": 0, "reelles": 0,
             "reelles_declarees": 0, "orphelins": 0, "orphelins_declares": 0}

    for perimetre in PERIMETRES:
        gauche, droite = lister(ici, perimetre), lister(autre, perimetre)
        communs = sorted(gauche & droite)
        orphelins = sorted((gauche | droite) - (gauche & droite))

        compte = {"nom": perimetre["nom"], "communs": len(communs), "identiques": 0,
                  "marque": 0, "reelles": 0, "reelles_declarees": 0,
                  "orphelins": len(orphelins), "orphelins_declares": 0}

        for chemin in communs:
            a = neutraliser_fins_de_ligne((ici / chemin).read_bytes())
            b = neutraliser_fins_de_ligne((autre / chemin).read_bytes())
            if a == b:
                compte["identiques"] += 1
                continue
            a_neutre, cat_a = neutraliser_marque(a, regles)
            b_neutre, cat_b = neutraliser_marque(b, regles)
            if a_neutre == b_neutre:
                compte["marque"] += 1
                continue
            compte["reelles"] += 1
            raison = declare(chemin)
            if raison is not None:
                compte["reelles_declarees"] += 1
            else:
                entree = {
                    "perimetre": perimetre["nom"],
                    "chemin": chemin,
                    "categories_marque": sorted(cat_a | cat_b),
                    "lignes_divergentes": nombre_de_lignes_divergentes(a_neutre, b_neutre),
                }
                if detail:
                    # Le diff est celui des textes NEUTRALISES : c'est tout
                    # l'interet du compteur. Le fichier qui annoncait 917 lignes
                    # changees n'en montre plus que les 4 qui comptent.
                    entree["diff"] = list(difflib.unified_diff(
                        a_neutre.splitlines(), b_neutre.splitlines(),
                        fromfile=f"ici/{chemin}", tofile=f"autre/{chemin}",
                        lineterm="", n=1,
                    ))
                resultat["reelles_a_traiter"].append(entree)

        for chemin in orphelins:
            raison = declare(chemin)
            if raison is not None:
                compte["orphelins_declares"] += 1
            else:
                resultat["orphelins_a_traiter"].append({
                    "perimetre": perimetre["nom"],
                    "chemin": chemin,
                    "present": "ici" if chemin in gauche else "autre",
                })

        resultat["perimetres"].append(compte)
        for cle in total:
            total[cle] += compte[cle]

    resultat["total"] = total
    resultat["declaration_obsolete"] = sorted(
        m for _s, m, _r in declaration if m not in motifs_utilises
    )
    return resultat


# --------------------------------------------------------------------------
# Rapport
# --------------------------------------------------------------------------

def rapporter(resultat: dict, ici: Path, autre: Path) -> None:
    """
    Rapport court et STABLE : aucune date, aucune duree, aucun ordre de parcours
    du systeme de fichiers. Deux lancements successifs doivent rendre des octets
    identiques, sans quoi le chiffre ne vaut rien.
    """
    print("DERIVE ENTRE LES DEUX DEPOTS JUMEAUX")
    print(f"  ici   : {ici}")
    print(f"  autre : {autre}")
    print()

    entete = f"{'perimetre':<12}{'communs':>9}{'identiques':>12}{'marque':>8}{'reelles':>9}{'declarees':>11}{'A TRAITER':>11}"
    print(entete)
    print("-" * len(entete))

    def ligne(nom, c):
        print(f"{nom:<12}{c['communs']:>9}{c['identiques']:>12}{c['marque']:>8}"
              f"{c['reelles']:>9}{c['reelles_declarees']:>11}"
              f"{c['reelles'] - c['reelles_declarees']:>11}")

    for compte in resultat["perimetres"]:
        ligne(compte["nom"], compte)
    print("-" * len(entete))
    ligne("TOTAL", resultat["total"])
    print()

    total = resultat["total"]
    orphelins_a_traiter = total["orphelins"] - total["orphelins_declares"]
    print(f"Fichiers presents d'un seul cote : {total['orphelins']} "
          f"(dont {total['orphelins_declares']} declares) -> {orphelins_a_traiter} a traiter")
    print()

    reelles = resultat["reelles_a_traiter"]
    print(f"DIVERGENCES REELLES NON DECLAREES : {len(reelles)}")
    print("  (« lignes » = apres neutralisation des fins de ligne ET de la marque)")
    for item in reelles:
        indice = (f"   marque aussi : {', '.join(item['categories_marque'])}"
                  if item["categories_marque"] else "")
        print(f"  {item['lignes_divergentes']:>4} lignes  {item['chemin']}{indice}")
        for ligne in item.get("diff", []):
            print(f"        {ligne}")
    if not reelles:
        print("  (aucune)")
    print()

    orphelins = resultat["orphelins_a_traiter"]
    if orphelins:
        print(f"FICHIERS D'UN SEUL COTE, NON DECLARES : {len(orphelins)}")
        for item in orphelins:
            cote = "ici seulement" if item["present"] == "ici" else "autre seulement"
            print(f"  {item['chemin']}  ({cote})")
        print()

    if resultat["declaration_obsolete"]:
        print("DECLARATIONS SANS OBJET (le fichier vise n'existe plus) :")
        for motif in resultat["declaration_obsolete"]:
            print(f"  {motif}")
        print("  -> a retirer de derive.declaration.txt (n'echoue pas le compteur)")
        print()


def main() -> int:
    # Le rapport contient des accents et des guillemets francais. Sans cela, une
    # console Windows en codepage 850 les remplace par des « ? » - et deux
    # lancements sur deux terminaux differents ne rendraient plus les memes
    # octets, ce qui suffirait a faire douter du compteur.
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    ici_defaut = Path(__file__).resolve().parent.parent

    analyseur = argparse.ArgumentParser(
        description="Compteur de derive entre les deux depots jumeaux.")
    analyseur.add_argument("--ici", default=str(ici_defaut),
                           help="racine du depot courant (defaut : le depot qui contient ce script)")
    analyseur.add_argument("--autre", default=os.environ.get("DERIVE_AUTRE"),
                           help="racine du depot jumeau (ou variable DERIVE_AUTRE, ou scripts/derive.jumeau.local)")
    analyseur.add_argument("--marque", default=None, help="table de marque")
    analyseur.add_argument("--declaration", default=None, help="declaration des divergences legitimes")
    analyseur.add_argument("--json", action="store_true", help="sortie machine, pour une verification automatique")
    analyseur.add_argument("--detail", action="store_true",
                           help="montre, pour chaque divergence reelle, le diff APRES neutralisation")
    args = analyseur.parse_args()

    ici = Path(args.ici).resolve()

    autre_brut = args.autre
    if not autre_brut:
        local = ici / "scripts" / "derive.jumeau.local"
        if local.is_file():
            autre_brut = local.read_text(encoding="utf-8").strip()
    if not autre_brut:
        print("Depot jumeau inconnu. Donnez-le par --autre <chemin>, par la variable\n"
              "DERIVE_AUTRE, ou en posant le chemin dans scripts/derive.jumeau.local\n"
              "(fichier propre a la machine, non versionne).", file=sys.stderr)
        return 2
    autre = Path(autre_brut).resolve()

    for nom, chemin in (("ici", ici), ("autre", autre)):
        if not chemin.is_dir():
            print(f"Depot « {nom} » introuvable : {chemin}", file=sys.stderr)
            return 2
    if ici == autre:
        print("Les deux chemins designent le meme depot.", file=sys.stderr)
        return 2

    dossier = Path(__file__).resolve().parent
    fichier_marque = Path(args.marque) if args.marque else dossier / "derive.marque.txt"
    fichier_declaration = Path(args.declaration) if args.declaration else dossier / "derive.declaration.txt"
    for chemin in (fichier_marque, fichier_declaration):
        if not chemin.is_file():
            print(f"Fichier de configuration manquant : {chemin}", file=sys.stderr)
            return 2

    resultat = mesurer(ici, autre,
                       lire_table_marque(fichier_marque),
                       lire_declaration(fichier_declaration),
                       detail=args.detail)

    total = resultat["total"]
    a_traiter = (total["reelles"] - total["reelles_declarees"]) + \
                (total["orphelins"] - total["orphelins_declares"])

    if args.json:
        resultat["a_traiter"] = a_traiter
        print(json.dumps(resultat, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        rapporter(resultat, ici, autre)

    return 1 if a_traiter else 0


if __name__ == "__main__":
    sys.exit(main())
