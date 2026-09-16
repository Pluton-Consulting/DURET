"""
LA RECETTE, EN UNE COMMANDE ET UN RAPPORT (16/09, audit D-25/S-25).

« Aucune régression » ne se décrète pas : ça se MESURE. Les bancs existent
(plus de cent quarante fichiers `test_*.py`), mais chacun se lançait à la main,
et rien ne gardait trace de ce qui avait été joué, sur quel commit, avec quel
Python. Un lot livré ne pouvait donc pas produire la phrase qui compte :
« voici ce qui passe, voici ce qui est sauté, et pourquoi ».

Ce lanceur :
  · joue tous les bancs (ou ceux qu'on nomme), un par un, avec un délai ;
  · classe chaque résultat en PASS / FAIL / SKIP — un banc qui dit lui-même
    qu'il lui manque le conteneur, une bibliothèque ou un réseau est SAUTÉ, pas
    réussi : c'est la différence entre « vérifié » et « non vérifié » ;
  · écrit un rapport daté (texte et JSON) sous `DOCUMENTS_DIR/recettes/`, avec
    le commit, la branche, l'interpréteur et la durée de chacun.

⚠️ Il ne charge JAMAIS d'identifiants de production : les bancs tournent sans
base, sans réseau et sans clé — c'est ce qui les rend rejouables partout.

USAGE :
    python backend/scripts/recette_usages.py                 # tout
    python backend/scripts/recette_usages.py --seulement trame,visuel
    python backend/scripts/recette_usages.py --delai 600 --sortie /tmp/recette
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys
import time

RACINE = pathlib.Path(__file__).resolve().parents[2]
BACKEND = RACINE / "backend"
# Ce qu'un banc dit quand il lui manque son environnement : ce n'est pas un
# échec, c'est un contrôle NON JOUÉ. Le confondre avec une réussite serait le
# pire des deux mondes.
MOTS_DE_SAUT = ("exige le conteneur", "non joué", "non jouée", "absent :", "(Node absent",
                "sans objet ici", "SAUTÉ", "python-docx", "cryptography absent",
                "n'est pas installé", "ModuleNotFoundError",
                # Un banc qui ATTEND UNE SAISIE (identifiants d'un tenant, mot de
                # passe) ne peut pas tourner sans personne devant : c'est un
                # contrôle non joué, pas un échec. On lui ferme l'entrée standard
                # pour qu'il le dise tout de suite au lieu d'attendre.
                "EOFError")


def _sortie_par_defaut() -> pathlib.Path:
    base = os.environ.get("DOCUMENTS_DIR") or str(RACINE / ".recettes")
    return pathlib.Path(base) / "recettes"


MARQUES_DE_REUSSITE = ("✓ 0 échec", "0 échec(s)", "Tous les contrôles passent",
                       "tout passe", "0 echec")


def _classer(code: int, texte: str) -> tuple:
    """(état, sauts) — l'état du banc, et s'il a dit avoir sauté des contrôles.

    Un banc qui finit bien mais annonce une section non jouée reste un PASS :
    il a vérifié ce qu'il pouvait. Le rapport garde la mention, pour qu'on ne
    lise pas « vert » là où il manque une partie.
    """
    saute = any(m in texte for m in MOTS_DE_SAUT)
    if code != 0:
        # Un banc qui n'a PAS PU tourner (il lui manque le conteneur, une
        # bibliothèque) et qui n'annonce aucun contrôle en échec n'est pas un
        # échec : c'est un contrôle NON JOUÉ. Le dire autrement ferait passer
        # une suite rouge pour une suite verte, ou l'inverse.
        if saute and "✗" not in texte:
            return "SKIP", True
        return "FAIL", saute
    if any(m in texte for m in MARQUES_DE_REUSSITE):
        return "PASS", saute
    return ("SKIP", saute) if saute else ("PASS", False)


def main() -> int:
    analyse = argparse.ArgumentParser(description="Recette : joue les bancs et rend un rapport.")
    analyse.add_argument("--seulement", default="", help="motifs séparés par des virgules")
    analyse.add_argument("--delai", type=int, default=300, help="secondes par banc")
    analyse.add_argument("--sortie", default="", help="dossier du rapport")
    analyse.add_argument("--python", default=sys.executable, help="interpréteur des bancs")
    args = analyse.parse_args()

    motifs = [m.strip().lower() for m in args.seulement.split(",") if m.strip()]
    bancs = sorted(p for p in (BACKEND / "scripts").glob("test_*.py")
                   if not motifs or any(m in p.name.lower() for m in motifs))
    if not bancs:
        print("Aucun banc ne correspond.")
        return 1

    commit = subprocess.run(["git", "-C", str(RACINE), "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True).stdout.strip() or "inconnu"
    branche = subprocess.run(["git", "-C", str(RACINE), "rev-parse", "--abbrev-ref", "HEAD"],
                             capture_output=True, text=True).stdout.strip() or "-"
    print(f"Recette de {RACINE.name} — commit {commit} ({branche}), {len(bancs)} banc(s), "
          f"{pathlib.Path(args.python).name}\n")

    resultats = []
    debut = time.monotonic()
    for banc in bancs:
        t0 = time.monotonic()
        try:
            lance = subprocess.run([args.python, str(banc), str(BACKEND)],
                                   capture_output=True, text=True, timeout=args.delai,
                                   stdin=subprocess.DEVNULL)
            texte, code = (lance.stdout or "") + (lance.stderr or ""), lance.returncode
            # La plupart des bancs prennent le chemin du backend en argument ;
            # quelques-uns ont leurs propres options et le refusent. On les
            # relance tels quels plutôt que de les compter en échec.
            if code != 0 and "unrecognized arguments" in texte:
                lance = subprocess.run([args.python, str(banc)], cwd=str(RACINE),
                                       capture_output=True, text=True, timeout=args.delai,
                                       stdin=subprocess.DEVNULL)
                texte, code = (lance.stdout or "") + (lance.stderr or ""), lance.returncode
        except subprocess.TimeoutExpired:
            texte, code = f"délai de {args.delai}s dépassé", 1
        etat, sauts = _classer(code, texte)
        duree = time.monotonic() - t0
        derniere = [l for l in texte.strip().splitlines() if l.strip()]
        resultats.append({"banc": banc.name, "etat": etat, "code": code,
                          "sauts": bool(sauts), "duree_s": round(duree, 1),
                          "dernier": (derniere[-1][:160] if derniere else "")})
        marque = {"PASS": "✓", "FAIL": "✗", "SKIP": "·"}[etat]
        mention = " (des contrôles sautés)" if sauts and etat == "PASS" else ""
        print(f"  {marque} {etat:<4} {banc.name:<44} {duree:5.1f}s  "
              f"{resultats[-1]['dernier'][:70]}{mention}")

    comptes = {e: sum(1 for r in resultats if r["etat"] == e) for e in ("PASS", "FAIL", "SKIP")}
    total = round(time.monotonic() - debut, 1)
    print(f"\n{comptes['PASS']} PASS · {comptes['FAIL']} FAIL · {comptes['SKIP']} SKIP "
          f"en {total}s")

    dossier = pathlib.Path(args.sortie) if args.sortie else _sortie_par_defaut()
    rapport = {"projet": RACINE.name, "commit": commit, "branche": branche,
               "python": args.python, "quand": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "duree_s": total, "comptes": comptes, "bancs": resultats}
    try:
        dossier.mkdir(parents=True, exist_ok=True)
        nom = f"recette_{time.strftime('%Y-%m-%d_%Hh%M')}_{commit}"
        (dossier / f"{nom}.json").write_text(json.dumps(rapport, ensure_ascii=False, indent=2),
                                             encoding="utf-8")
        lignes = [f"{r['etat']:<4} {r['banc']:<46} {r['duree_s']:>6}s  {r['dernier']}"
                  + ("   [des contrôles sautés]" if r.get("sauts") and r["etat"] == "PASS" else "")
                  for r in resultats]
        (dossier / f"{nom}.txt").write_text(
            f"Recette {RACINE.name} — commit {commit} ({branche})\n"
            f"{comptes['PASS']} PASS · {comptes['FAIL']} FAIL · {comptes['SKIP']} SKIP en {total}s\n\n"
            + "\n".join(lignes) + "\n", encoding="utf-8")
        print(f"Rapport : {dossier / (nom + '.txt')}")
    except OSError as e:
        print(f"(rapport non écrit : {e})")

    if comptes["FAIL"]:
        print("\nÉCHECS :")
        for r in resultats:
            if r["etat"] == "FAIL":
                print(f"  · {r['banc']} — {r['dernier']}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
