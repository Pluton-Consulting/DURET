"""
RATTACHER LES VISUELS ANCIENS À LEUR PROPRIÉTAIRE (16/09, audit D-03).

Depuis le 16/09, chaque visuel déposé pendant un geste note son propriétaire
(`visuels/depot.py`, fichier voisin `<clé>.acces`) et la route ne le sert qu'à
lui. Les visuels déposés AVANT n'ont pas de propriétaire connu : ils restent
lisibles par tout compte connecté qui connaît leur clé, pour ne pas vider les
conversations passées de leurs images.

CE SCRIPT ÉTABLIT CE QUI PEUT L'ÊTRE, SANS RIEN DEVINER. Une clé de visuel
apparaît dans les messages qui l'ont montrée (le bloc `visuel` d'une réponse,
les pièces jointes d'une question) ; la personne à qui appartient cette
conversation l'a donc vue, elle en devient propriétaire. Une clé que plus
aucun message ne cite reste « indéterminée » : elle est listée pour une reprise
administrative, et ne se ferme que sur demande explicite (`--fermer-indetermines`
la réserve au super-administrateur — rien n'est supprimé).

USAGE (dans le conteneur, comme les migrations) :
    docker compose exec backend python scripts/rattacher_visuels.py             # constat seul
    docker compose exec backend python scripts/rattacher_visuels.py --ecrire    # note les propriétaires établis
    docker compose exec backend python scripts/rattacher_visuels.py --ecrire --fermer-indetermines
"""
import asyncio
import os
import pathlib
import re
import sys

# Lancé par « python scripts/rattacher_visuels.py », Python met `scripts/`
# dans son chemin, pas la racine du backend (même piège que
# `purger_balises_memoire.py`).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

RE_CLE = re.compile(r"(?<![0-9a-f])[0-9a-f]{24}(?![0-9a-f])")
EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
# Le système (aucune personne) : la politique de lecture des messages ouvre
# toutes les conversations au rôle super_admin.
LECTEUR_SYSTEME = "00000000-0000-0000-0000-000000000000"


def cles_sans_proprietaire(dossier: pathlib.Path) -> set:
    """Les visuels du dépôt qui n'ont aucun propriétaire noté."""
    if not dossier.is_dir():
        return set()
    return {p.stem for p in dossier.iterdir()
            if p.suffix.lower() in EXTENSIONS and p.stem.isalnum()
            and not (dossier / f"{p.stem}.acces").exists()}


def etablir(cles: set, lignes) -> dict:
    """clé → propriétaires, d'après les messages (user_id, texte) qui la citent."""
    trouves: dict = {}
    for user_id, texte in lignes:
        if not user_id or not texte:
            continue
        for cle in set(RE_CLE.findall(texte)) & cles:
            trouves.setdefault(cle, set()).add(str(user_id))
    return trouves


def appliquer(depot, cles: set, etablis: dict, ecrire: bool, fermer: bool) -> dict:
    """Écrit (ou compte seulement) ce qui a été établi."""
    indetermines = sorted(cles - set(etablis))
    if ecrire:
        for cle, personnes in etablis.items():
            for personne in sorted(personnes):
                depot.noter_proprietaire(cle, personne)
        if fermer:
            for cle in indetermines:
                depot.reserver_a_l_administration(cle)
    return {"sans_proprietaire": len(cles), "etablis": len(etablis),
            "indetermines": len(indetermines), "exemples_indetermines": indetermines[:10]}


async def _lignes(conn):
    requete = ("SELECT t.user_id::text AS user_id, m.content || ' ' || COALESCE(m.metadata::text, '') AS texte "
               "FROM messages m JOIN threads t ON t.id = m.thread_id "
               "WHERE m.content ~ '[0-9a-f]{24}' OR m.metadata::text ~ '[0-9a-f]{24}'")
    async for ligne in conn.cursor(requete, prefetch=200):
        yield ligne["user_id"], ligne["texte"]


async def main() -> int:
    ecrire = "--ecrire" in sys.argv
    fermer = "--fermer-indetermines" in sys.argv
    if fermer and not ecrire:
        print("--fermer-indetermines exige --ecrire : rien n'est fait.")
        return 1

    from visuels import depot
    cles = cles_sans_proprietaire(depot.DOSSIER)
    print(f"Dépôt : {depot.DOSSIER} — {len(cles)} visuel(s) sans propriétaire noté.")
    if not cles:
        return 0

    from database.connection import get_rls_db, init_db
    await init_db()
    lignes = []
    async with get_rls_db(LECTEUR_SYSTEME, "super_admin") as conn:
        async for user_id, texte in _lignes(conn):
            lignes.append((user_id, texte))
    bilan = appliquer(depot, cles, etablir(cles, lignes), ecrire, fermer)
    print(f"{bilan['etablis']} visuel(s) dont le propriétaire est établi par les messages, "
          f"{bilan['indetermines']} indéterminé(s).")
    for cle in bilan["exemples_indetermines"]:
        print("  indéterminé :", cle)
    if not ecrire:
        print("\nConstat seul. Relancer avec --ecrire pour noter les propriétaires établis "
              "(les indéterminés restent lisibles ; --fermer-indetermines les réserve au "
              "super-administrateur).")
    elif fermer:
        print("\nPropriétaires notés ; les indéterminés sont réservés au super-administrateur.")
    else:
        print("\nPropriétaires notés ; les indéterminés restent lisibles.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
