"""
LE NIVEAU D'ACCÈS PAR DOSSIER DU NAS (13/09, Duret).

DEMANDE DE NOA : chaque profil a un rôle (direction, commercial, administratif…)
et la mémoire que « Enrichir » tire du NAS doit cacher des informations à
certains. CE QUI EXISTAIT ne le permettait pas : la synchronisation écrivait
TOUS les fichiers au même niveau (`SYNOLOGY_ACCESS_LEVEL`, « all » par
défaut), la campagne d'enrichissement gardait ce niveau, et le chat ouvrait le
serveur entier à qui avait ce niveau. Rien de ce qui venait du NAS n'était
caché à personne.

LA RÈGLE. Dans Paramètres, l'administrateur attribue un niveau à des dossiers.
Un dossier vaut pour TOUT ce qu'il contient ; la règle du chemin LE PLUS LONG
l'emporte (un sous-dossier peut être plus ouvert ou plus fermé que son parent) ;
sans règle, le niveau par défaut du serveur. Le même calcul sert partout :
  * à la synchronisation (le niveau écrit sur chaque document) ;
  * au reclassement des documents déjà importés ;
  * à la carte du classement (noms de dossiers dans le prompt et en base) ;
  * au chat, qui ne liste, ne trouve et n'ouvre que ce que le rôle voit.
Une règle illisible ou un niveau hors échelle se ramènent au plus restrictif :
une faute ne doit jamais ouvrir.

Fonctions pures d'abord (le banc les exécute), accès base ensuite.
"""
from __future__ import annotations

import json
import logging
import unicodedata
from typing import Optional

logger = logging.getLogger("duret.nas.niveaux")

REGLAGE = "nas_niveaux"
MAX_REGLES = 200


def _nu(chemin: str) -> str:
    """Pour comparer deux chemins : casse, accents, forme Unicode et barres
    finales ne font pas deux dossiers (la leçon du 08/09 sur « PIÉCES »)."""
    from nas.acces import normaliser
    c = unicodedata.normalize("NFKD", normaliser(chemin or ""))
    return "".join(ch for ch in c if not unicodedata.combining(ch)).lower()


def _echelle() -> tuple:
    from security.acces import NIVEAUX
    return NIVEAUX


def rang(niveau: Optional[str]) -> int:
    """Rang dans l'échelle (0 = tout le monde). Hors échelle : le plus fermé."""
    echelle = _echelle()
    return echelle.index(niveau) if niveau in echelle else len(echelle) - 1


def lire_regles(brut) -> list[dict]:
    """Le réglage tel qu'il est stocké (JSON) → règles propres, sans doublon.

    Un niveau inconnu devient le plus restrictif plutôt que d'être ignoré :
    ignorer une règle rouvrirait le dossier qu'elle fermait.
    """
    if isinstance(brut, str):
        try:
            brut = json.loads(brut) if brut.strip() else []
        except ValueError:
            logger.warning("Réglage %s illisible : aucune règle appliquée "
                           "(le niveau par défaut vaut partout).", REGLAGE)
            return []
    regles: dict[str, dict] = {}
    for r in brut if isinstance(brut, list) else []:
        if not isinstance(r, dict):
            continue
        chemin = str(r.get("chemin") or "").strip()
        if not chemin or chemin == "/":
            continue
        niveau = str(r.get("niveau") or "").strip()
        if niveau not in _echelle():
            niveau = _echelle()[-1]
        from nas.acces import normaliser
        regles[_nu(chemin)] = {"chemin": normaliser(chemin), "niveau": niveau}
    return sorted(regles.values(), key=lambda r: _nu(r["chemin"]))[:MAX_REGLES]


def niveau_du_chemin(chemin: str, regles: list[dict], defaut: str) -> str:
    """Le niveau d'un fichier ou d'un dossier : la règle du plus long chemin
    qui le contient, sinon le défaut du serveur."""
    vise = _nu(chemin)
    retenue, longueur = None, -1
    for r in regles:
        base = _nu(r["chemin"])
        if (vise == base or vise.startswith(base.rstrip("/") + "/")) and len(base) > longueur:
            retenue, longueur = r["niveau"], len(base)
    niveau = retenue or (defaut or "all")
    return niveau if niveau in _echelle() else _echelle()[-1]


def visible(chemin: str, role: Optional[str], regles: list[dict], defaut: str) -> bool:
    """Ce rôle voit-il ce chemin ? `role` None = le système : tout."""
    if role is None:
        return True
    from security.acces import niveaux_visibles
    return niveau_du_chemin(chemin, regles, defaut) in niveaux_visibles(role)


def niveaux_en_usage(regles: list[dict], defaut: str) -> set[str]:
    """Tous les niveaux qu'un dossier du serveur peut porter."""
    return {defaut or "all"} | {r["niveau"] for r in regles}


# ── La configuration en vigueur ────────────────────────────────────────────
def defaut() -> str:
    from config import settings
    return (getattr(settings, "synology_access_level", None) or "all").strip() or "all"


_MEMO: dict = {"brut": None, "regles": []}


def regles() -> list[dict]:
    """Les règles enregistrées dans Paramètres (cache des réglages, 30 s).

    Relues à chaque chemin (une synchronisation en compte des dizaines de
    milliers) : le JSON n'est analysé qu'au changement du texte stocké.
    """
    try:
        from llm.reglages import valeur
        brut = valeur(REGLAGE) or ""
    except Exception:  # noqa: BLE001 — sans cache, aucune règle : le défaut vaut
        return []
    if brut != _MEMO["brut"]:
        _MEMO.update(brut=brut, regles=lire_regles(brut))
    return _MEMO["regles"]


def niveau(chemin: str) -> str:
    return niveau_du_chemin(chemin, regles(), defaut())


def visible_pour(chemin: str, role: Optional[str]) -> bool:
    return visible(chemin, role, regles(), defaut())


def filtrer(entrees: list, role: Optional[str]) -> list:
    """Retire d'une liste d'entrées (`chemin`) ce que ce rôle ne voit pas."""
    if role is None:
        return list(entrees or [])
    r, d = regles(), defaut()
    return [e for e in entrees or [] if visible(str(e.get("chemin") or ""), role, r, d)]


# ── La base ────────────────────────────────────────────────────────────────
def chemin_de_source(source_id: str, par_empreinte: dict) -> Optional[str]:
    """Le chemin du NAS d'un document importé (`synology:<chemin>`), ou None.

    Un chemin trop long pour la colonne a été rangé par empreinte
    (`synology:#<empreinte>:<fin>`) : on le retrouve dans le catalogue.
    """
    sid = str(source_id or "")
    if not sid.startswith("synology:"):
        return None
    if sid.startswith("synology:#"):
        return par_empreinte.get(sid)
    return sid[len("synology:"):]


async def reclasser_documents() -> dict:
    """Pose sur chaque document déjà importé du NAS le niveau de son dossier.

    Une requête par niveau cible, jamais une par document. Les chemins rangés
    par empreinte ne se retrouvent qu'avec le catalogue : s'il n'est pas prêt,
    ces documents gardent leur niveau et le bilan le dit.
    """
    from config import settings
    from database.connection import get_db
    from ingestion.connectors.synology import _source_id
    from nas.acces import catalogue_pret

    source_type = getattr(settings, "synology_source_type", None) or "nas"
    r, d = regles(), defaut()
    cat = catalogue_pret()
    par_empreinte = {}
    if cat is not None:
        for e in cat:
            if not e.get("dossier") and e.get("chemin"):
                sid = _source_id(e["chemin"])
                if sid.startswith("synology:#"):
                    par_empreinte[sid] = e["chemin"]

    async with get_db() as conn:
        lignes = await conn.fetch(
            "SELECT DISTINCT source_id, access_level FROM documents WHERE source_type = $1",
            source_type)
    cibles: dict[str, list[str]] = {}
    inconnus = 0
    for l in lignes:
        chemin = chemin_de_source(l["source_id"], par_empreinte)
        if chemin is None:
            inconnus += 1
            continue
        n = niveau_du_chemin(chemin, r, d)
        if n != l["access_level"]:
            cibles.setdefault(n, []).append(str(l["source_id"]))
    modifies = 0
    async with get_db() as conn:
        for n, ids in cibles.items():
            statut = await conn.execute(
                "UPDATE documents SET access_level = $1 "
                "WHERE source_type = $2 AND source_id = ANY($3::text[])",
                n, source_type, ids)
            modifies += len(ids)
            logger.info("NAS : %d document(s) passés au niveau %s (%s)", len(ids), n, statut)
    return {"documents": len(lignes), "reclasses": modifies,
            "sans_chemin": inconnus, "catalogue_pret": cat is not None}


async def connaissances_des_documents() -> int:
    """Combien de connaissances et manières de faire la campagne documentaire a
    écrites. Elles portent le niveau du GROUPE de fichiers d'où elles viennent,
    sans lien vers chaque fichier : un reclassement ne peut pas les suivre."""
    from database.connection import get_db
    async with get_db() as conn:
        return int(await conn.fetchval(
            "SELECT COUNT(DISTINCT source_id) FROM documents "
            "WHERE source_type IN ('apprentissage', 'procedure') "
            "AND source_id LIKE '%:documents:%'") or 0)


async def retirer_connaissances_des_documents() -> int:
    """Retire ces connaissances pour qu'une nouvelle campagne les réécrive au
    bon niveau. Geste d'administrateur, sur clic explicite."""
    from database.connection import get_db
    n = await connaissances_des_documents()
    async with get_db() as conn:
        await conn.execute(
            "DELETE FROM documents WHERE source_type IN ('apprentissage', 'procedure') "
            "AND source_id LIKE '%:documents:%'")
    return n
