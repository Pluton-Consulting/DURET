"""
Fusion, groupement et fenêtrage des résultats de recherche — fonctions PURES.

POURQUOI CE MODULE (31/08/2026). Noa : « il a beaucoup de mal avec les longues
requêtes ou les recherches dans la base s'il y a plusieurs milliers de data ;
il doit faire d'énormes recherches aussi bien que des toutes petites ». Ce que
la recherche documentaire faisait jusque-là :
  * SIX morceaux au plus, 6 000 caractères en tout, quelle que soit la
    question — « tous les comptes rendus qui parlent de drainage » rendait six
    extraits, souvent du même document ;
  * la voie vectorielle SEULE, avec un repli lexical tenté uniquement quand
    elle ne rendait RIEN. Or plus de la moitié des morceaux du corpus (3 390
    sur 6 401 le 31/08) n'ont pas d'embedding — quota Gemini — et sont donc
    INVISIBLES à cette voie ; et le repli `content % requête` compare une
    question de trois mots à un morceau de 380 mots : la similarité est nulle
    par construction, le repli ne rendait jamais rien non plus ;
  * chaque extrait était le DÉBUT du morceau, pas l'endroit où les termes
    cherchés apparaissent.

Ici : la FUSION de plusieurs voies (vecteur, plein texte, trigrammes) par rang
réciproque — un morceau trouvé par deux voies remonte ; le GROUPEMENT par
document, pour qu'une grosse recherche rende des documents (avec le nombre de
morceaux qui correspondent dans chacun) et non trente fois le même ; et la
FENÊTRE d'extrait centrée sur les termes de la question. Rien ici ne touche à
la base : tout se teste sans réseau.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional

# Constante du rang réciproque (Cormack et al.) : 60 est la valeur d'usage, elle
# lisse l'écart entre le premier et le dixième sans l'écraser.
RRF_K = 60
EXTRAITS_PAR_DOCUMENT = 2


def _cle(chunk: dict) -> str:
    return str(chunk.get("id") or (chunk.get("source_id"), chunk.get("chunk_index")))


def fusionner(voies: dict[str, Iterable[dict]], k: int = RRF_K) -> list[dict]:
    """Fusion par rang réciproque : {nom_de_voie: résultats classés} → une liste
    unique, du plus sûr au moins sûr. Chaque morceau porte `voies` (celles qui
    l'ont trouvé) et `score`. Un morceau vu par deux voies l'emporte sur un
    morceau premier d'une seule : c'est le principe, et c'est ce qu'on veut."""
    scores: dict[str, float] = {}
    vus: dict[str, dict] = {}
    for nom, liste in voies.items():
        for rang, chunk in enumerate(liste or []):
            cle = _cle(chunk)
            scores[cle] = scores.get(cle, 0.0) + 1.0 / (k + rang + 1)
            if cle not in vus:
                vus[cle] = dict(chunk)
                vus[cle]["voies"] = []
            vus[cle]["voies"].append(nom)
    ordre = sorted(vus, key=lambda c: -scores[c])
    resultat = []
    for cle in ordre:
        chunk = vus[cle]
        chunk["score"] = round(scores[cle], 6)
        resultat.append(chunk)
    return resultat


def grouper_par_document(chunks: list[dict],
                         extraits_par_document: int = EXTRAITS_PAR_DOCUMENT) -> list[dict]:
    """Des morceaux classés → des DOCUMENTS classés (au meilleur morceau), avec
    le nombre de morceaux qui correspondent et les meilleurs extraits de chacun.
    L'ordre d'entrée est l'ordre de pertinence : le premier morceau d'un
    document fixe sa place."""
    documents: dict[tuple, dict] = {}
    for c in chunks:
        cle = (str(c.get("source_type") or ""), str(c.get("source_id") or ""))
        d = documents.get(cle)
        if d is None:
            d = documents[cle] = {
                "source": c.get("source_filename") or c.get("source_id") or "(sans nom)",
                "type": c.get("source_type"),
                "source_id": c.get("source_id"),
                "morceaux_correspondants": 0,
                "morceaux_total": c.get("chunk_total") or 1,
                "voies": [],
                "extraits": [],
            }
        d["morceaux_correspondants"] += 1
        for v in c.get("voies") or []:
            if v not in d["voies"]:
                d["voies"].append(v)
        if len(d["extraits"]) < max(1, extraits_par_document):
            d["extraits"].append({"morceau": int(c.get("chunk_index") or 0) + 1,
                                  "texte": c.get("content") or ""})
    return list(documents.values())


def _plat(texte: str) -> str:
    """Minuscules sans accents : « Drainage » et « drainagé » se retrouvent."""
    return "".join(ch for ch in unicodedata.normalize("NFD", (texte or "").lower())
                   if unicodedata.category(ch) != "Mn")


def termes(requete: str, minimum: int = 4) -> list[str]:
    """Les mots porteurs d'une question — assez longs pour ne pas être « de »
    ou « les », les plus longs d'abord (ils sont les plus discriminants)."""
    mots = re.findall(r"[a-z0-9]+", _plat(requete))
    vus, sortie = set(), []
    for m in sorted(mots, key=len, reverse=True):
        if len(m) >= minimum and m not in vus:
            vus.add(m)
            sortie.append(m)
    return sortie


def fenetre(texte: str, requete: str, longueur: int) -> str:
    """L'extrait d'un morceau, CENTRÉ sur le premier terme de la question qu'on y
    trouve — sinon son début. Coupé aux espaces, avec des points de suspension
    qui disent qu'il y a quelque chose avant ou après."""
    texte = " ".join((texte or "").split())
    longueur = max(40, int(longueur))
    if len(texte) <= longueur:
        return texte
    plat = _plat(texte)
    if len(plat) != len(texte):
        # NFD a changé la longueur (ligature rare) : on cherche sans les accents
        # plutôt que de viser à côté.
        plat = texte.lower()
    position: Optional[int] = None
    for t in termes(requete):
        i = plat.find(t)
        if i >= 0 and (position is None or i < position):
            position = i
    if position is None or position < longueur // 3:
        debut = 0
    else:
        debut = max(0, position - longueur // 3)
        # On recule jusqu'à une espace pour ne pas commencer au milieu d'un mot.
        espace = texte.rfind(" ", 0, debut + 1)
        if espace > 0:
            debut = espace + 1
    fin = min(len(texte), debut + longueur)
    if fin < len(texte):
        espace = texte.rfind(" ", debut, fin)
        if espace > debut + longueur // 2:
            fin = espace
    morceau = texte[debut:fin].strip()
    return ("… " if debut > 0 else "") + morceau + (" …" if fin < len(texte) else "")


def budget_extrait(nombre_extraits: int, budget_total: int = 9000,
                   minimum: int = 250, maximum: int = 1500) -> int:
    """La longueur de chaque extrait pour que la PAGE entière atteigne le
    modèle : longs quand ils sont peu, courts quand ils sont nombreux — même
    principe que les extraits de mails."""
    if nombre_extraits <= 0:
        return maximum
    return max(minimum, min(maximum, budget_total // nombre_extraits))
