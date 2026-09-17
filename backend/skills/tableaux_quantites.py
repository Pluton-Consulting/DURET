"""
UN TABLEAU CHIFFRÉ SE LIT PAR LE CODE, PAS PAR UN MODÈLE (17/09).

Test réel de Noa (Duret, métrés du DCE Domofrance) : le quantitatif a conclu
« aucune quantité prouvable » alors que le DPGF du lot 11 porte, noir sur
blanc, `Isolant phonique | m2 | 453`. Le classeur avait été donné à un modèle
de langage, passage par passage, avec une règle de citation mot à mot — or un
classeur se lit cellule par cellule (`D90="m2" | E90="453"`), et « 453 m² »
n'y figure nulle part. Les 32 quantités du tableau ont toutes été rejetées.

Un DPGF, un BPU, un DQE sont des TABLEAUX : n°, désignation, unité, quantité.
Le code les lit exactement, instantanément, sans jeton, et chaque ligne garde
sa cellule pour preuve. Décision de Noa : « les Excel sont lus par le code, et
en cas de problème seulement par l'IA ». Le « problème » est défini ici : aucun
en-tête reconnaissable (pas de colonne d'unité ET de quantité) — l'appelant
repasse alors par la lecture habituelle, rien n'est perdu.

Le texte d'entrée est celui de `bureautique/lecture_integrale.py` :
    Feuille DPGF — ligne 90 : B90="3.1.1" | C90="Isolant phonique" | D90="m2" | E90="453"
"""
from __future__ import annotations

import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation

_LIGNE = re.compile(r"^Feuille (?P<feuille>.+?) — ligne (?P<rang>\d+) : (?P<cellules>.*)$")
_CELLULE = re.compile(r'([A-Z]{1,3})(\d+)=("(?:[^"\\]|\\.)*")')

# Ce qui se lit dans une colonne d'unité. « ft » = forfait : une ligne à part
# entière d'un DPGF, qui ne se mesure pas mais se compte.
UNITES = {
    "m2": "m²", "m²": "m²", "m3": "m³", "m³": "m³", "ml": "ml", "m.l": "ml", "m.l.": "ml", "ml.": "ml",
    "m": "m", "u": "u", "un": "u", "unite": "u", "unites": "u", "pce": "u", "piece": "u", "pieces": "u",
    "kg": "kg", "t": "t", "h": "h", "j": "j", "l": "l",
    "ft": "ft", "f": "ft", "fft": "ft", "forfait": "ft", "ens": "ens", "ensemble": "ens", "ps": "ft",
}
_ENTETE_UNITE = {"u", "un", "unite", "unites", "unit"}
_ENTETE_QUANTITE = ("q", "qte", "qt", "quantite", "quantites", "q ent", "qent", "qte ent", "quantite ent",
                    "q entreprise", "qte entreprise", "quantite entreprise", "q moe", "qte moe")
_ENTETE_DESIGNATION = ("designation", "libelle", "ouvrage", "description", "nature", "intitule")
_ENTETE_NUMERO = ("n°", "no", "n", "art", "article", "ref", "reference", "poste", "item", "code")


def _plat(texte) -> str:
    t = unicodedata.normalize("NFD", str(texte or "").casefold())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[\s.]+", " ", t).strip()


def _nombre(valeur):
    """Un nombre de tableau, ou None. « 1 250,5 » et « 453 » passent ; « Ft »,
    une formule sans valeur calculée ou un texte ne passent pas."""
    t = str(valeur if valeur is not None else "").replace("\u00a0", " ").replace("\u202f", " ").strip()
    if not t or "FORMULE SANS VALEUR" in t:
        return None
    t = t.replace(" ", "").replace(",", ".")
    try:
        n = Decimal(t)
    except (InvalidOperation, ValueError):
        return None
    return n if n.is_finite() else None


def _lot(nom: str) -> str:
    m = re.search(r"lot\s*n?°?\s*(\d+)\s*[-–—:]?\s*([^.\n]*)", str(nom or ""), re.I)
    if not m:
        return "Lot non précisé"
    suite = re.sub(r"\s+", " ", m.group(2)).strip(" -–—")
    return f"Lot {m.group(1)}" + (f" — {suite}" if suite else "")


def _lignes(contenu: str):
    for brut in str(contenu or "").splitlines():
        m = _LIGNE.match(brut)
        if not m:
            continue
        cellules = {}
        for colonne, _rang, valeur in _CELLULE.findall(m.group("cellules")):
            try:
                cellules[colonne] = json.loads(valeur)
            except ValueError:
                cellules[colonne] = valeur.strip('"')
        if cellules:
            yield m.group("feuille"), int(m.group("rang")), cellules, brut


def _entete(cellules: dict):
    """(colonne unité, colonne quantité, colonne désignation, colonne n°) ou None."""
    unite = quantite = designation = numero = None
    for colonne, valeur in cellules.items():
        v = _plat(valeur)
        if not v or len(v) > 40:
            continue
        if unite is None and v in _ENTETE_UNITE:
            unite = colonne
        elif quantite is None and (v in _ENTETE_QUANTITE or v.startswith(("quantite", "qte"))):
            quantite = colonne
        elif designation is None and any(v.startswith(d) for d in _ENTETE_DESIGNATION):
            designation = colonne
        elif numero is None and v in _ENTETE_NUMERO:
            numero = colonne
    if unite and quantite:
        return unite, quantite, designation, numero
    return None


def lire(source: dict) -> dict:
    """Les lignes chiffrées d'un classeur, lues par le code.

    Rend {"entete": bool, "lignes": [...], "a_metrer": [...], "feuilles": n}.
    `entete` faux = ce classeur n'a pas la forme d'un tableau de quantités :
    l'appelant le confie à la lecture habituelle (modèle)."""
    contenu = source.get("contenu") or ""
    if not contenu.lstrip().startswith("Feuille "):
        return {"entete": False, "lignes": [], "a_metrer": [], "feuilles": 0}
    lot = _lot(source.get("nom") or "")
    colonnes = {}          # feuille → (unité, quantité, désignation, n°)
    titres = {}            # feuille → (n°, libellé) du dernier intertitre rencontré

    def rubrique(feuille, numero):
        """L'intertitre qui situe un poste — seulement s'il le situe VRAIMENT. DPGF
        réel du lot 12 : « 3.3 Revêtement PVC dans logement » suivait l'intertitre
        « Revêtement de sol des escaliers » (3.2.2) et en héritait à tort."""
        n_titre, libelle = titres.get(feuille) or ("", "")
        if numero and (not n_titre or not numero.startswith(n_titre.rstrip(".") + ".")):
            return ""
        return libelle

    lignes, a_metrer = [], []
    for feuille, rang, cellules, brut in _lignes(contenu):
        if feuille not in colonnes:
            trouve = _entete(cellules)
            if trouve:
                colonnes[feuille] = trouve
            continue
        c_unite, c_quantite, c_designation, c_numero = colonnes[feuille]
        textes = {k: str(v).strip() for k, v in cellules.items() if isinstance(v, str) and str(v).strip()}
        designation = (textes.get(c_designation) if c_designation else None) or max(
            (v for k, v in textes.items() if k not in (c_unite, c_quantite) and _nombre(v) is None),
            key=len, default="")
        designation = re.sub(r"\s+", " ", designation).strip()
        numero = re.sub(r"\s+", " ", str(cellules.get(c_numero) or "")).strip() if c_numero else ""
        unite = UNITES.get(_plat(cellules.get(c_unite)).replace(" ", ""))
        if not designation:
            continue
        if not unite:
            # Une ligne titrée sans unité est un INTERTITRE (« 3.1 Logements ») :
            # elle situe les postes qui suivent.
            if (_nombre(cellules.get(c_quantite)) is None and len(designation) <= 120
                    and not _plat(designation).startswith(("sous total", "sous-total", "total", "montant", "tva", "report"))):
                titres[feuille] = (numero, designation)
            continue
        poste = (numero + " " + designation).strip()
        quantite = _nombre(cellules.get(c_quantite))
        if quantite is None and unite in ("ft", "ens"):
            quantite = None   # un forfait sans « 1 » reste à chiffrer, il ne se devine pas
        if quantite is None:
            a_metrer.append({"lot": lot, "poste": poste, "unite": unite, "local": rubrique(feuille, numero)})
            continue
        if quantite < 0:
            continue
        preuve = f"{source.get('id')}:{feuille}!{c_quantite}{rang}"
        citation = brut.split(" : ", 1)[-1]
        lignes.append({
            "lot": lot, "poste": poste, "niveau": "Ensemble de l'opération",
            "local": rubrique(feuille, numero) or "Total du poste", "unite": unite, "formule": "c1",
            "quantite": format(quantite.normalize() if quantite == quantite.to_integral() else quantite, "f"),
            "operandes": [{"valeur": format(quantite, "f"), "unite": unite, "preuve": preuve, "citation": citation}],
            "affectation": {"preuve": preuve, "citation": citation},
            "lecture": "Tableau chiffré du dossier (lu par le code, cellule citée)", "_tableau": True,
        })
    return {"entete": bool(colonnes), "lignes": lignes, "a_metrer": a_metrer, "feuilles": len(colonnes)}


# ─── LE TABLEAU DES SURFACES D'UN PLAN D'ARCHITECTE ─────────────────────────
#
# 17/09, dossier réel du DCE Domofrance : le plan « 12 SURFACES.pdf » porte, dans
# sa couche texte, la surface de CHAQUE pièce de chaque logement — mais colonne
# par colonne (neuf fois « 001 », neuf fois « T3 », neuf noms de pièces, neuf
# nombres, puis « 67,45 m² »). Aucun nombre n'y touche son unité : la règle de
# citation du relevé par modèle rejetait tout, et une lecture visuelle d'un
# tableau de 230 valeurs se trompe de chiffres. Le code relit les colonnes, et
# garde un bloc SEULEMENT si la somme de ses pièces retombe sur le total écrit
# par l'architecte : l'alignement est alors prouvé, pas supposé.

_SURFACE = re.compile(r"^\d{1,4},\d{2}$")
_TOTAL_M2 = re.compile(r"^(\d{1,3}(?:[   ]\d{3})*|\d+),(\d{2})\s*m[²2]$")
_NUMERO_LOGEMENT = re.compile(r"^[A-Z]?\d{2,4}$")
_TYPE_LOGEMENT = re.compile(r"^(T|F)\d(\s?bis)?$|^studio$", re.I)
_NIVEAUX = {"0": "RDC", "1": "R+1", "2": "R+2", "3": "R+3", "4": "R+4", "5": "R+5"}


def lire_surfaces(source: dict) -> dict:
    """Les surfaces par pièce d'un tableau de surfaces (couche texte d'un plan).

    Rend {"pieces": [...], "blocs": n, "rejetes": n}. Une pièce :
    {logement, type, piece, niveau, surface (Decimal), preuve, citation}."""
    contenu = str(source.get("contenu") or "")
    lignes = [l.strip() for l in contenu.splitlines()]
    pieces, blocs, rejetes = [], 0, 0
    for i, ligne in enumerate(lignes):
        m = _TOTAL_M2.match(ligne)
        if not m:
            continue
        total = _nombre(re.sub(r"\s*m[²2]$", "", ligne))
        # les k nombres qui précèdent le total
        j = i - 1
        valeurs = []
        while j >= 0 and _SURFACE.match(lignes[j]):
            valeurs.insert(0, _nombre(lignes[j])); j -= 1
        k = len(valeurs)
        if not k or total is None or j - k + 1 < 0:
            continue
        noms = lignes[j - k + 1:j + 1]
        if len(noms) != k or any((not n) or _nombre(n) is not None or _TOTAL_M2.match(n) for n in noms):
            rejetes += 1
            continue
        j -= k
        types = lignes[j - k + 1:j + 1] if j - k + 1 >= 0 else []
        if len(types) == k and all(_TYPE_LOGEMENT.match(t) for t in types):
            j -= k
        else:
            types = [""] * k
        numeros = lignes[j - k + 1:j + 1] if j - k + 1 >= 0 else []
        if len(numeros) != k or len(set(numeros)) != 1 or not _NUMERO_LOGEMENT.match(numeros[0]):
            rejetes += 1
            continue
        if abs(sum(valeurs) - total) > Decimal("0.03"):
            rejetes += 1          # colonnes mêlées par le PDF : on ne devine pas
            continue
        blocs += 1
        logement = numeros[0]
        chiffres = re.sub(r"\D", "", logement)
        niveau = _NIVEAUX.get(chiffres[0], "") if len(chiffres) == 3 else ""
        for nom, type_logement, valeur in zip(noms, types, valeurs):
            pieces.append({
                "logement": logement, "type": type_logement, "piece": re.sub(r"\s+", " ", nom),
                "niveau": niveau, "surface": valeur,
                "preuve": f"{source.get('id')}:surfaces!{logement}",
                "citation": (f"Logement {logement}" + (f" ({type_logement})" if type_logement else "") + f" — {nom} : "
                             f"{format(valeur, 'f').replace('.', ',')} ; total du logement écrit sur le plan : "
                             f"{format(total, 'f').replace('.', ',')} m² = somme des {k} pièces (vérifiée)"),
            })
    return {"pieces": pieces, "blocs": blocs, "rejetes": rejetes}


def famille_de_piece(nom: str) -> str:
    """« CHAMBRE 2 », « Chambre » → « CHAMBRE » ; « SdE 1 », « SDE » → « SDE »."""
    t = _plat(nom).upper()
    t = re.sub(r"\b\d+\b", "", t)                 # numéro de la pièce ou du logement
    t = re.sub(r"\s*/\s*", "/", t)
    t = re.sub(r"\s+", " ", t).strip(" .")
    return {"DGT": "DEGAGEMENT", "DEGT": "DEGAGEMENT", "SEJOUR CUISINE": "SEJOUR/CUISINE"}.get(t, t)
