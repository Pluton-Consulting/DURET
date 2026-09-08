"""
LA CARTE DU CLASSEMENT — l'architecture du stockage de l'entreprise, en
mémoire et dans la base vectorisée, pour que l'assistant sache OÙ chercher.

Demande de Noa du 08/09 : « analyser tout le drive pour avoir vraiment un
schéma et enregistrer toute l'architecture sous forme schématique dans la
base de données vectorisée, pour qu'il puisse savoir exactement où chercher ».

CE QUI EXISTAIT, ET POURQUOI ÇA NE SUFFISAIT PAS. L'arborescence se
reconstruisait à CHAQUE demande (Drive : 60 s de balayage pour 10 779
dossiers, mesuré dans l'export du 08/09 ; NAS : un catalogue en mémoire
depuis le 08/09 midi) et ne laissait rien derrière elle : la recherche
documentaire ne connaissait que le CONTENU des fichiers ingérés, jamais le
CLASSEMENT — « où sont rangés les CCTP », « dans quel dossier est le client
Martin » n'avaient de réponse qu'après un nouveau parcours.

CE MODULE EST DU SOCLE : il ne connaît ni le Drive ni le NAS. Il reçoit des
ENTRÉES (un chemin, dossier ou fichier, avec des comptes) d'un module
`classement.source` propre à chaque client, et en fait trois choses :

  1. une CARTE COURTE (les racines et leurs premiers dossiers, ~700 car.),
     glissée dans le prompt système : le modèle connaît la forme du
     classement sans appeler personne ;
  2. des MORCEAUX (un par dossier jusqu'à une profondeur donnée, listant ses
     sous-dossiers avec leurs comptes et les types de fichiers) rangés dans
     la table `documents` sous `source_type = "classement"` : la recherche
     documentaire les retrouve par le texte (plein texte et trigrammes
     marchent SANS embedding — la file des embeddings est souvent en retard),
     et le skill `ou_chercher` les interroge directement en mémoire ;
  3. un rafraîchissement DE FOND (au démarrage, puis toutes les six heures)
     qui ne coûte rien à personne : aucun tour n'attend la carte.

Rien n'est inventé : les comptes sont ceux relevés, et la carte dit quand le
relevé est partiel. Les fonctions de construction sont PURES (le banc les
exécute sur un classement d'essai) ; seul `enregistrer` touche la base.
"""
from __future__ import annotations

import asyncio
import logging
import posixpath
import re
import time
import unicodedata
from typing import Optional

logger = logging.getLogger("symbiose.classement")

SOURCE_TYPE = "classement"
PROFONDEUR_CHUNKS = 3          # en BASE : un morceau par dossier jusqu'à cette profondeur (racine = 0)
PROFONDEUR_MEMOIRE = 40        # en MÉMOIRE : tous les dossiers — « où est le CCTP » vit à la profondeur 6
NOMS_PAR_CHUNK = 80            # sous-dossiers nommés par morceau ; au-delà, un morceau de plus
CHUNKS_MAX = 900               # plafond de morceaux écrits en base (dit quand il mord)
CARTE_COURTE_MAX = 700
CARTE_DUREE_S = 6 * 3600       # rafraîchie toutes les six heures
ATTENTE_DEMARRAGE_S = 25       # on laisse l'application démarrer avant de balayer

ETAT: dict = {"etat": "vide", "courte": "", "chunks": [], "dossiers": 0, "fichiers": 0,
              "complet": False, "en_base": 0, "construit_le": 0.0, "en_cours": False,
              "erreur": ""}


# ── 1. Les fonctions pures ────────────────────────────────────────────────

def _sans_accent(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texte or "")
                   if unicodedata.category(c) != "Mn").lower()


def _propre(chemin: str) -> str:
    return (chemin or "").replace("\\", "/").strip().strip("/")


def _extension(nom: str) -> str:
    base = posixpath.basename(nom or "")
    if "." not in base:
        return "sans extension"
    ext = base.rsplit(".", 1)[-1].lower()
    return ext if 0 < len(ext) <= 6 else "sans extension"


def entrees_vers_arbre(entrees: list) -> dict:
    """Les entrées à plat → un nœud par dossier, avec ce qu'il contient.

    Deux formes d'entrées cohabitent, et c'est voulu :
      · NAS : chaque FICHIER est une entrée (`dossier: False`, `octets`) ; le
        nœud parent compte alors lui-même ses fichiers et leurs types ;
      · Drive : le balayage ne ramène que les DOSSIERS, chacun portant déjà
        ses comptes (`fichiers`, `octets`, `types`).
    Rend {chemin: {"sous": [noms], "fichiers": n, "octets": n, "types": {ext: n}}}.
    """
    noeuds: dict[str, dict] = {}

    def _noeud(chemin: str) -> dict:
        n = noeuds.get(chemin)
        if n is None:
            n = noeuds[chemin] = {"sous": [], "fichiers": 0, "octets": 0, "types": {}}
        return n

    for e in entrees or []:
        chemin = _propre(str(e.get("chemin") or ""))
        if not chemin:
            continue
        parent = posixpath.dirname(chemin)
        if e.get("dossier", True):
            n = _noeud(chemin)
            n["fichiers"] += int(e.get("fichiers") or 0)
            n["octets"] += int(e.get("octets") or 0) if e.get("fichiers") else 0
            for ext, k in (e.get("types") or {}).items():
                n["types"][ext] = n["types"].get(ext, 0) + int(k or 0)
            if parent:
                p = _noeud(parent)
                nom = posixpath.basename(chemin)
                if nom not in p["sous"]:
                    p["sous"].append(nom)
        else:
            p = _noeud(parent) if parent else None
            if p is None:
                continue
            p["fichiers"] += 1
            p["octets"] += int(e.get("octets") or e.get("taille") or 0)
            ext = _extension(chemin)
            p["types"][ext] = p["types"].get(ext, 0) + 1
    # Les dossiers intermédiaires créés par un fichier profond (jamais listés
    # comme tels côté NAS) existent et portent leur enfant, jusqu'à la racine.
    for chemin in list(noeuds):
        cour = chemin
        while True:
            parent = posixpath.dirname(cour)
            if not parent:
                break
            p = _noeud(parent)
            nom = posixpath.basename(cour)
            if nom not in p["sous"]:
                p["sous"].append(nom)
            cour = parent
    for n in noeuds.values():
        n["sous"].sort(key=lambda s: _sans_accent(s))
    return noeuds


def _totaux(noeuds: dict, chemin: str, memo: dict) -> tuple[int, int]:
    """(dossiers, fichiers) dans TOUT le sous-arbre d'un dossier."""
    if chemin in memo:
        return memo[chemin]
    n = noeuds.get(chemin) or {"sous": [], "fichiers": 0}
    d, f = 0, int(n["fichiers"])
    for s in n["sous"]:
        sd, sf = _totaux(noeuds, posixpath.join(chemin, s), memo)
        d += 1 + sd
        f += sf
    memo[chemin] = (d, f)
    return memo[chemin]


def _lisible(octets: int) -> str:
    if octets >= 1024 ** 3:
        return f"{octets / 1024 ** 3:.1f} Go"
    if octets >= 1024 ** 2:
        return f"{octets / 1024 ** 2:.0f} Mo"
    if octets >= 1024:
        return f"{octets / 1024:.0f} Ko"
    return f"{octets} o"


def _types_lisibles(types: dict, n: int = 6) -> str:
    if not types:
        return ""
    tri = sorted(types.items(), key=lambda kv: -kv[1])[:n]
    reste = sum(types.values()) - sum(k for _, k in tri)
    texte = ", ".join(f"{ext} {k}" for ext, k in tri)
    return texte + (f", autres {reste}" if reste > 0 else "")


def racines(noeuds: dict) -> list[str]:
    return sorted([c for c in noeuds if "/" not in c], key=_sans_accent)


def construire_chunks(entrees: list, profondeur: Optional[int] = PROFONDEUR_CHUNKS,
                      noms_par_chunk: int = NOMS_PAR_CHUNK) -> list[dict]:
    """Un morceau de texte par dossier jusqu'à `profondeur`, qui NOMME ses
    sous-dossiers (avec leurs comptes) et dit ce qu'il contient.

    Pourquoi nommer les sous-dossiers dans le morceau du PARENT : c'est ce qui
    fait qu'un dossier client à la profondeur 4 (« 33 LA TESTE - DUPONT »)
    se retrouve par le texte sans qu'on écrive un morceau par client — le
    morceau de « Dossiers Études » le porte. Un dossier de plus de
    `noms_par_chunk` enfants fait plusieurs morceaux (suite 2/3…), jamais une
    liste coupée en silence.
    """
    noeuds = entrees_vers_arbre(entrees)
    memo: dict = {}
    chunks: list[dict] = []
    for chemin in sorted(noeuds, key=lambda c: (c.count("/"), _sans_accent(c))):
        if profondeur is not None and chemin.count("/") > profondeur:
            continue
        n = noeuds[chemin]
        d_tot, f_tot = _totaux(noeuds, chemin, memo)
        lignes_sous = []
        for s in n["sous"]:
            sd, sf = _totaux(noeuds, posixpath.join(chemin, s), memo)
            detail = []
            if sd:
                detail.append(f"{sd} dossier{'s' if sd > 1 else ''}")
            if sf:
                detail.append(f"{sf} fichier{'s' if sf > 1 else ''}")
            lignes_sous.append(s + (f" ({', '.join(detail)})" if detail else ""))
        pages = [lignes_sous[i:i + noms_par_chunk]
                 for i in range(0, len(lignes_sous), noms_par_chunk)] or [[]]
        for idx, page in enumerate(pages):
            entete = [f"CLASSEMENT — {chemin}"
                      + (f" (suite {idx + 1}/{len(pages)})" if len(pages) > 1 else ""),
                      "Emplacement : " + " › ".join(chemin.split("/"))]
            contenu = []
            if n["sous"]:
                contenu.append(f"{len(n['sous'])} sous-dossier{'s' if len(n['sous']) > 1 else ''} directs")
            if d_tot:
                contenu.append(f"{d_tot} dossiers en tout")
            if f_tot:
                contenu.append(f"{f_tot} fichiers en tout")
            if n["fichiers"]:
                contenu.append(f"{n['fichiers']} fichiers à la racine du dossier"
                               + (f" ({_lisible(n['octets'])})" if n["octets"] else ""))
            types = _types_lisibles(n["types"])
            if types:
                contenu.append("types de fichiers : " + types)
            lignes = entete + (["Contenu : " + " ; ".join(contenu)] if contenu else [])
            if page:
                lignes.append("Sous-dossiers : " + " ; ".join(page))
            elif not n["sous"] and not n["fichiers"]:
                lignes.append("Dossier vide au moment du relevé.")
            chunks.append({"chemin": chemin, "nom": posixpath.basename(chemin) or chemin,
                           "texte": "\n".join(lignes), "index": idx, "total": len(pages),
                           "dossiers": d_tot, "fichiers": f_tot, "types": dict(n["types"])})
    return chunks


def carte_courte(entrees: list, max_chars: int = CARTE_COURTE_MAX) -> str:
    """Les racines et leurs premiers dossiers, en une ligne par racine —
    ce que le prompt système porte à chaque tour."""
    noeuds = entrees_vers_arbre(entrees)
    memo: dict = {}
    lignes = []
    for r in racines(noeuds):
        n = noeuds[r]
        # Une racine qui n'a qu'un enfant (« Drive partagé » → « SYMBIOSE PAYSAGE »)
        # se lit par cet enfant : c'est lui qui porte le classement.
        chemin, nom = r, r
        while len(noeuds[chemin]["sous"]) == 1 and not noeuds[chemin]["fichiers"]:
            seul = noeuds[chemin]["sous"][0]
            chemin = posixpath.join(chemin, seul)
            nom = f"{nom}/{seul}"
            n = noeuds[chemin]
        morceaux = []
        for s in n["sous"]:
            sd, sf = _totaux(noeuds, posixpath.join(chemin, s), memo)
            detail = [x for x in ((f"{sd} doss." if sd else ""), (f"{sf} fich." if sf else "")) if x]
            morceaux.append(s + (f" ({', '.join(detail)})" if detail else ""))
        lignes.append(f"{nom} : " + (" ; ".join(morceaux) if morceaux else "(rien)"))
    texte = "\n".join(lignes)
    if len(texte) > max_chars:
        texte = texte[:max_chars].rsplit(" ; ", 1)[0] + " ; …"
    return texte


def chercher_dans_la_carte(chunks: list, sujet: str, limite: int = 12) -> list[dict]:
    """Les dossiers dont le chemin ou le contenu parle du sujet, en mémoire.

    Chaque mot du sujet (3 lettres et plus, sans accent) doit se trouver dans
    le morceau ; un morceau dont le CHEMIN porte le mot passe avant un morceau
    qui ne l'a que dans sa liste de sous-dossiers. Quand un sous-dossier nommé
    dans le morceau correspond, c'est LUI qu'on rend (chemin complet) : c'est
    l'emplacement exact que la personne veut ouvrir.
    """
    mots = [m for m in re.split(r"[^\w]+", _sans_accent(sujet or "")) if len(m) >= 3]
    if not mots:
        return []
    trouves: dict[str, dict] = {}
    for c in chunks or []:
        texte = _sans_accent(c.get("texte") or "")
        if not all(m in texte for m in mots):
            continue
        chemin_nu = _sans_accent(c.get("chemin") or "")
        # D'abord les sous-dossiers nommés qui portent TOUS les mots.
        ligne = ""
        for l in (c.get("texte") or "").splitlines():
            if l.startswith("Sous-dossiers : "):
                ligne = l[len("Sous-dossiers : "):]
        precis = 0
        for item in ligne.split(" ; ") if ligne else []:
            nom = item.rsplit(" (", 1)[0] if item.endswith(")") else item
            if nom and all(m in _sans_accent(nom) for m in mots):
                chemin = posixpath.join(c["chemin"], nom)
                if chemin not in trouves:
                    trouves[chemin] = {"chemin": chemin, "score": 3, "detail": item}
                precis += 1
        if not precis and all(m in chemin_nu for m in mots):
            trouves.setdefault(c["chemin"], {"chemin": c["chemin"], "score": 2,
                                             "detail": f"{c.get('dossiers', 0)} dossiers, {c.get('fichiers', 0)} fichiers"})
        elif not precis:
            trouves.setdefault(c["chemin"], {"chemin": c["chemin"], "score": 1,
                                             "detail": f"{c.get('dossiers', 0)} dossiers, {c.get('fichiers', 0)} fichiers"})
    tri = sorted(trouves.values(), key=lambda t: (-t["score"], t["chemin"].count("/"), _sans_accent(t["chemin"])))
    return tri[:limite]


# ── 2. La base ────────────────────────────────────────────────────────────

async def enregistrer(chunks: list, niveau_de) -> int:
    """Remplace la carte en base par celle-ci. Rend le nombre de morceaux écrits.

    Chaque morceau porte le niveau d'accès de SON dossier (`niveau_de`, fourni
    par le client) : la recherche documentaire filtre déjà par niveau, un
    nom de dossier réservé à la direction ne remonte donc pas ailleurs.
    Aucun embedding n'est calculé ici : le job est mis en file comme pour tout
    document ; le plein texte sert dès l'écriture.
    """
    from database.connection import get_db
    from vectorstore.client import vectorstore

    ecrits = 0
    async with get_db() as conn:
        await conn.execute("DELETE FROM documents WHERE source_type = $1", SOURCE_TYPE)
    for c in chunks[:CHUNKS_MAX]:
        try:
            await vectorstore.insert_document_chunk(
                content=c["texte"], source_type=SOURCE_TYPE,
                source_id=f"classement:{c['chemin']}",
                access_level=niveau_de(c["chemin"]) or "all",
                source_filename=c["nom"], chunk_index=c["index"], chunk_total=c["total"])
            ecrits += 1
        except Exception as e:  # noqa: BLE001 — un morceau refusé n'arrête pas la carte
            logger.info("Carte : morceau non écrit (%s) : %s", c["chemin"], str(e)[:120])
    return ecrits


# ── 3. Le cycle de vie ────────────────────────────────────────────────────

async def rafraichir_carte() -> dict:
    """Relève le classement, construit la carte, la garde en mémoire et en base.
    Une seule construction à la fois ; ne lève jamais."""
    if ETAT["en_cours"]:
        return ETAT
    ETAT["en_cours"] = True
    debut = time.monotonic()
    try:
        from classement.source import entrees_du_classement, niveau_de
        entrees, complet = await entrees_du_classement()
        noeuds = entrees_vers_arbre(entrees)
        # TOUS les dossiers en mémoire (la recherche `ou_chercher` y descend
        # jusqu'au CCTP d'un chantier) ; la base ne reçoit que les premiers
        # niveaux : la recherche documentaire y trouve « dans quelle branche »,
        # le skill donne ensuite le chemin exact.
        chunks = construire_chunks(entrees, profondeur=PROFONDEUR_MEMOIRE)
        memo: dict = {}
        d_tot = sum(1 for c in noeuds if "/" in c)
        f_tot = sum(_totaux(noeuds, r, memo)[1] for r in racines(noeuds))
        ETAT.update({"etat": "pret" if complet else "partiel", "complet": bool(complet),
                     "courte": carte_courte(entrees), "chunks": chunks,
                     "dossiers": d_tot, "fichiers": f_tot,
                     "construit_le": time.monotonic(), "erreur": ""})
        logger.info("Carte du classement %s : %d dossiers, %d fichiers, %d morceaux en %.0f s",
                    ETAT["etat"], d_tot, f_tot, len(chunks), time.monotonic() - debut)
        try:
            en_base = [c for c in chunks if c["chemin"].count("/") <= PROFONDEUR_CHUNKS]
            ETAT["en_base"] = await enregistrer(en_base, niveau_de)
            logger.info("Carte du classement : %d morceaux écrits en base", ETAT["en_base"])
        except Exception as e:  # noqa: BLE001 — sans base, la carte reste en mémoire
            logger.warning("Carte du classement : non écrite en base (%s)", str(e)[:160])
    except Exception as e:  # noqa: BLE001 — un stockage injoignable ne casse rien
        ETAT["erreur"] = str(e)[:200]
        logger.warning("Carte du classement non construite : %s", str(e)[:200])
    finally:
        ETAT["en_cours"] = False
    return ETAT


def carte_prete() -> str:
    """La carte courte si elle existe (même vieille), sinon une chaîne vide."""
    return ETAT["courte"] if ETAT["etat"] in ("pret", "partiel") else ""


def chunks_prets() -> list:
    return ETAT["chunks"] if ETAT["etat"] in ("pret", "partiel") else []


def statut() -> dict:
    """Ce que l'écran et le skill peuvent dire de la carte, sans les morceaux."""
    return {k: v for k, v in ETAT.items() if k != "chunks"} | {"morceaux": len(ETAT["chunks"])}


async def demarrer_carte() -> None:
    """Tâche de fond : une première carte peu après le démarrage, puis une
    toutes les `CARTE_DUREE_S`. Ne lève jamais, ne bloque personne."""
    await asyncio.sleep(ATTENTE_DEMARRAGE_S)
    while True:
        try:
            await rafraichir_carte()
        except Exception as e:  # noqa: BLE001
            logger.warning("Carte du classement : cycle en échec (%s)", str(e)[:160])
        await asyncio.sleep(CARTE_DUREE_S)
