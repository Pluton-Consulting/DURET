"""
LIRE UNE VALEUR ÉCRITE PAR UN HUMAIN, ou par le logiciel de gestion d'un client.

Deux choses s'y lisent : les DATES et les MONTANTS. Elles ont le même problème
et méritaient la même réponse, au même endroit.

POURQUOI CE MODULE EXISTE.

Les fichiers importés ne portent pas des dates : ils portent du TEXTE. Le schéma
d'import ne type rien, à dessein — un export Excel écrit « 03/04/2024 », un
logiciel métier « 2024-04-03T09:12:00 », une saisie à la main « 3 avril 2024 »
ou « 3 avr. 24 », et le même fichier mélange souvent les trois selon la colonne
et selon qui l'a remplie.

Tant qu'on ne savait pas les lire, deux questions parfaitement banales restaient
sans réponse exacte : « sur les douze derniers mois » (on filtrait par MOIS
entier, sur deux formats seulement) et « depuis plus de quinze jours » (rien ne
comparait une date à aujourd'hui). Les deux ont été promises à un client.

CE QUE CE MODULE GARANTIT, ET CE QU'IL REFUSE DE FAIRE.

Il rend une date ET SA PRÉCISION. « 3 avril 2024 » est un jour, « avril 2024 »
est un mois, « 2024 » est une année : ce sont trois informations différentes, et
les confondre est précisément ce qui produit des chiffres faux. Une valeur qu'il
ne sait pas lire rend None — jamais une date par défaut, jamais aujourd'hui.
C'est ce qui permet à l'appelant de DIRE combien de lignes il a dû écarter, au
lieu de les compter en silence dans un total.

L'AMBIGUÏTÉ EST TRANCHÉE UNE FOIS, ET DANS LE BON SENS. « 05/09/2024 » vaut le
5 septembre : ces fichiers viennent d'entreprises françaises. Quand le premier
nombre dépasse 12, il n'y a plus d'ambiguïté du tout ; quand c'est le second, la
date est américaine et on la lit comme telle plutôt que de la jeter.
"""
from __future__ import annotations

import datetime
import logging
import re
import unicodedata

logger = logging.getLogger("pluton.skills.lecture")

# Précisions possibles, de la plus fine à la plus grossière.
JOUR, MOIS, ANNEE = "jour", "mois", "annee"

# Les mois français, entiers ou abrégés, avec ou sans accent ni point. L'ordre
# des alternatives compte : « juillet » avant « juin » ne changerait rien ici
# (on compare des préfixes distincts), mais « mars » doit précéder « mai » pour
# qu'un « mar » ne devienne pas « mai ».
_MOIS = (
    ("janvier", "janv", "jan"), ("fevrier", "fevr", "fev"), ("mars", "mar"),
    ("avril", "avr"), ("mai",), ("juin", "jun"), ("juillet", "juil", "jul"),
    ("aout", "aou"), ("septembre", "sept", "sep"), ("octobre", "octo", "oct"),
    ("novembre", "nov"), ("decembre", "dece", "dec"),
)

# Bornes de plausibilité : un export contient parfois « 0001-01-01 » ou un
# numéro de dossier à quatre chiffres qui ressemble à une année. Une date hors
# de ces bornes est du bruit, pas une date — la lire fausserait les périodes.
ANNEE_MIN, ANNEE_MAX = 1990, 2100


def _plat(texte) -> str:
    """Minuscules, sans accents : la forme qui se compare."""
    s = unicodedata.normalize("NFD", str(texte or ""))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower()


def _mois_depuis_lettres(mot: str):
    """« sept », « septembre », « sept. » → 9. None si ce n'est pas un mois."""
    mot = mot.strip(" .")
    for numero, formes in enumerate(_MOIS, start=1):
        if any(mot == f or (len(mot) >= 3 and f.startswith(mot)) for f in formes):
            return numero
    return None


def _date_sure(annee: int, mois: int, jour: int):
    """Une date réelle, ou None. Ne lève jamais.

    Un « 31/02 » existe dans les fichiers (saisie fautive, export bancal). On
    ne le corrige pas en le décalant au 3 mars — cela inventerait une date que
    personne n'a écrite : on le ramène au dernier jour réel du mois, ce qui
    garde la ligne dans la bonne période sans prétendre à une précision qu'on
    n'a pas.
    """
    if not (ANNEE_MIN <= annee <= ANNEE_MAX) or not (1 <= mois <= 12):
        return None
    jour = max(1, jour)
    for essai in (jour, 31, 30, 29, 28):
        try:
            return datetime.date(annee, mois, min(jour, essai))
        except ValueError:
            continue
    return None


def _annee_complete(brut: str) -> int:
    """« 24 » → 2024, « 99 » → 1999, « 2024 » → 2024."""
    n = int(brut)
    if len(brut) <= 2:
        return n + 2000 if n < 70 else n + 1900
    return n


# ── Les motifs, du plus précis au moins précis ────────────────────────
# Chacun est essayé dans l'ordre : le premier qui correspond gagne. Un motif
# large placé trop tôt avalerait les autres — « 2024 » est contenu dans
# « 03/04/2024 », donc l'année seule vient en dernier, et ancrée.
_ISO = re.compile(r"(?<![0-9])([0-9]{4})[-/.]([0-9]{1,2})[-/.]([0-9]{1,2})(?![0-9])")
_FR = re.compile(r"(?<![0-9])([0-9]{1,2})[-/.]([0-9]{1,2})[-/.]([0-9]{2,4})(?![0-9])")
_JOUR_MOIS_LETTRES = re.compile(
    r"(?<![0-9])([0-9]{1,2})(?:er)?\s+([a-z]{3,10})\.?\s+([0-9]{2,4})(?![0-9])")
_MOIS_LETTRES_ANNEE = re.compile(r"([a-z]{3,10})\.?\s+([0-9]{4})(?![0-9])")
_MOIS_ANNEE = re.compile(r"(?<![0-9])([0-9]{1,2})[-/.]([0-9]{4})(?![0-9])")
# L'ANNÉE SEULE EST ANCRÉE SUR TOUT LE TEXTE, et c'est essentiel. Cherchée au
# fil de la chaîne, elle transformait « DEV-2025-014 » en une date de 2025 : une
# RÉFÉRENCE de devis devenait une date, et une colonne mal choisie remplissait
# une période de lignes qui n'y étaient pas. Une année n'est une date que
# lorsqu'elle est seule.
_ANNEE = re.compile(r"^\s*((?:19|20)[0-9]{2})\s*$")


def lire_date(valeur):
    """Rend `(date, précision)` ou `(None, None)`. Ne lève jamais.

    La précision dit ce qu'on sait VRAIMENT : « jour », « mois » (la date rendue
    est alors le 1er du mois) ou « annee » (le 1er janvier). L'appelant en a
    besoin : compter « avril 2024 » dans une période qui commence le 15 avril
    est un choix, pas une évidence, et ce choix doit être pris en connaissance
    de cause.
    """
    texte = _plat(valeur).strip()
    if not texte:
        return None, None

    m = _ISO.search(texte)
    if m:
        d = _date_sure(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            return d, JOUR

    m = _FR.search(texte)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        annee = _annee_complete(m.group(3))
        # Français par défaut (jour/mois). Si le premier nombre dépasse 12, il
        # ne peut être qu'un jour, ce qui confirme ; si c'est le second, la
        # date est écrite à l'américaine et on la lit ainsi plutôt que de la
        # perdre.
        jour, mois = (a, b) if b <= 12 else (b, a)
        d = _date_sure(annee, mois, jour)
        if d:
            return d, JOUR

    m = _JOUR_MOIS_LETTRES.search(texte)
    if m:
        mois = _mois_depuis_lettres(m.group(2))
        if mois:
            d = _date_sure(_annee_complete(m.group(3)), mois, int(m.group(1)))
            if d:
                return d, JOUR

    m = _MOIS_LETTRES_ANNEE.search(texte)
    if m:
        mois = _mois_depuis_lettres(m.group(1))
        if mois:
            d = _date_sure(int(m.group(2)), mois, 1)
            if d:
                return d, MOIS

    m = _MOIS_ANNEE.search(texte)
    if m and 1 <= int(m.group(1)) <= 12:
        d = _date_sure(int(m.group(2)), int(m.group(1)), 1)
        if d:
            return d, MOIS

    m = _ANNEE.match(texte)
    if m:
        d = _date_sure(int(m.group(1)), 1, 1)
        if d:
            return d, ANNEE

    return None, None


def cle_triable(valeur) -> str:
    """« 12/03/2025 » → « 20250312 ». Chaîne vide si illisible.

    Une date illisible se range en DERNIER, jamais en premier : elle ne doit
    pas se faire passer pour la plus récente quand on demande « le dernier
    devis ».
    """
    d, _ = lire_date(valeur)
    return d.strftime("%Y%m%d") if d else ""


def age_en_jours(valeur, aujourdhui=None):
    """Depuis combien de jours ? None si la date est illisible ou à venir.

    Une date FUTURE rend 0 et non un nombre négatif : un devis daté de demain
    n'attend pas depuis moins que rien, il n'attend pas encore.
    """
    d, _ = lire_date(valeur)
    if not d:
        return None
    ecart = ((aujourdhui or datetime.date.today()) - d).days
    return max(0, ecart)


def fin_de_precision(d, precision):
    """Le DERNIER jour couvert par une date selon ce qu'on en sait.

    « avril 2024 » couvre jusqu'au 30 avril, « 2024 » jusqu'au 31 décembre.
    Sans cela, une ligne datée « avril 2024 » serait exclue d'une période qui
    commence le 15 avril, alors qu'elle y tombe peut-être — et on perdrait des
    lignes en silence, ce qui est le pire des deux erreurs possibles.
    """
    if precision == ANNEE:
        return datetime.date(d.year, 12, 31)
    if precision == MOIS:
        suivant = (datetime.date(d.year + 1, 1, 1) if d.month == 12
                   else datetime.date(d.year, d.month + 1, 1))
        return suivant - datetime.timedelta(days=1)
    return d


def dans_la_periode(valeur, debut, fin=None) -> bool:
    """La date tombe-t-elle dans [debut, fin] ? Une date illisible : non.

    Une date imprécise est retenue dès que sa PLAGE croise la période : c'est
    le seul choix qui ne perd pas de ligne. L'appelant sait combien de lignes
    étaient imprécises, et peut le dire.
    """
    d, precision = lire_date(valeur)
    if not d:
        return False
    fin = fin or datetime.date.today()
    return d <= fin and fin_de_precision(d, precision) >= debut


# ── Comprendre une période dite en français ───────────────────────────
_UNITES = {"j": 1, "jour": 1, "jours": 1, "s": 7, "sem": 7, "semaine": 7,
           "semaines": 7, "m": 30, "mois": 30, "a": 365, "an": 365, "ans": 365,
           "annee": 365, "annees": 365}
_EXPRESSIONS = (
    ("hier", 1), ("cette semaine", 7), ("la semaine", 7), ("semaine derniere", 7),
    ("ce mois", 30), ("le mois dernier", 30), ("mois dernier", 30),
    ("ce trimestre", 91), ("trimestre", 91), ("semestre", 182),
    ("cette annee", 365), ("annee derniere", 365), ("l'an dernier", 365),
    ("an dernier", 365), ("aujourd'hui", 0), ("aujourdhui", 0),
)


def _moins_des_mois(fin, nombre: int):
    """Reculer de N MOIS CALENDAIRES, pas de N fois trente jours.

    « Les 12 derniers mois » veut dire un an, jour pour jour. Compté en tranches
    de trente jours, cela faisait 360 : cinq jours d'historique passaient à la
    trappe sans que personne ne puisse le voir dans le total. Le 31 mars moins
    un mois vaut le 28 (ou 29) février : on ramène au dernier jour réel plutôt
    que de déborder sur mars.
    """
    mois_total = fin.year * 12 + (fin.month - 1) - nombre
    annee, mois = divmod(mois_total, 12)
    mois += 1
    for jour in (fin.day, 30, 29, 28):
        try:
            return datetime.date(annee, mois, min(fin.day, jour))
        except ValueError:
            continue
    return datetime.date(annee, mois, 1)


def debut_de_periode(depuis, aujourdhui=None):
    """Le PREMIER JOUR de la période demandée. None si elle n'est pas lisible.

    Comprend « 12m », « 30j », « 6 mois », « les 15 derniers jours », « cette
    semaine », « l'année dernière », et une date écrite en toutes lettres ou en
    chiffres. Rendre None est un résultat, pas un échec : un paramètre de
    période ignoré EN SILENCE fait porter le total sur tout l'historique tout
    en le présentant comme celui de la période demandée — un chiffre faux avec
    l'aplomb d'un chiffre juste. L'appelant doit refuser, pas deviner.
    """
    fin = aujourdhui or datetime.date.today()
    texte = _plat(depuis).strip()
    if not texte:
        return None

    # Une date écrite : c'est elle, le début.
    d, _ = lire_date(texte)
    if d and re.search(r"[0-9]{4}", texte):
        return d

    def _reculer(nombre, unite):
        if unite in ("m", "mois"):
            return _moins_des_mois(fin, nombre)
        if unite in ("a", "an", "ans", "annee", "annees"):
            return _moins_des_mois(fin, nombre * 12)
        jours = _UNITES.get(unite)
        return fin - datetime.timedelta(days=nombre * jours) if jours else None

    m = re.match(r"^(\d+)\s*([a-z']*)$", texte)
    if m:
        return _reculer(int(m.group(1)), m.group(2) or "j")

    # « 3 derniers mois », « les 15 derniers jours »
    m = re.search(r"(\d+)\s+derni[a-z]*\s+([a-z]+)", texte) or re.search(
        r"(\d+)\s+([a-z]+)", texte)
    if m and (m.group(2) in _UNITES or m.group(2) in ("m", "mois")):
        return _reculer(int(m.group(1)), m.group(2))

    for mot, jours in _EXPRESSIONS:
        if mot in texte:
            if "mois" in mot:
                return _moins_des_mois(fin, 1)
            if "annee" in mot or "an dernier" in mot:
                return _moins_des_mois(fin, 12)
            return fin - datetime.timedelta(days=jours)
    return None


# ═══════════════════════════════════════════════════════════════════════
#  LES MONTANTS — même problème, même réponse
# ═══════════════════════════════════════════════════════════════════════
#
# « 12 450,50 € » se lit 12 par un parseur naïf, et le chiffre d'affaires d'un
# client devient faux sans que rien ne le signale : le genre d'erreur qui ne se
# voit qu'en réunion. Les exports comptables français mélangent espaces
# insécables, virgules décimales et séparateurs de milliers, parfois dans le
# même fichier.
#
# CE PIÈGE-LÀ A DÉJÀ COÛTÉ. « 7.000 » lu 7,0 : en français, un point suivi de
# trois chiffres est un séparateur de milliers, et le total d'une année sortait
# faux de 6 993 €. « 1250.50 » et « 1.5 », eux, restent des décimales.

_NOMBRE = re.compile(r"-?\d[\d\s  .,]*")


def lire_montant(valeur, defaut=0.0) -> float:
    """« 12 450,50 € » → 12450.5. Rend `defaut` sur tout ce qui n'est pas un nombre."""
    m = _NOMBRE.search(str(valeur if valeur is not None else ""))
    if not m:
        return defaut
    brut = m.group(0).strip()
    for espace in (" ", " ", " ", " "):
        brut = brut.replace(espace, "")
    # Le dernier séparateur rencontré est le décimal ; les autres sont des
    # milliers. « 1.234,56 » et « 1,234.56 » se lisent donc tous les deux.
    if "," in brut and "." in brut:
        decimal = "," if brut.rindex(",") > brut.rindex(".") else "."
        millier = "." if decimal == "," else ","
        brut = brut.replace(millier, "").replace(decimal, ".")
    elif "," in brut:
        brut = brut.replace(",", ".")
    elif brut.count(".") > 1:
        brut = brut.replace(".", "")            # plusieurs points : des milliers
    elif re.fullmatch(r"-?[0-9]{1,3}\.[0-9]{3}", brut):
        brut = brut.replace(".", "")            # « 7.000 » : sept mille
    try:
        return float(brut)
    except ValueError:
        return defaut


def est_un_nombre(valeur) -> bool:
    """Y a-t-il un nombre LISIBLE là-dedans ? Sert à dire combien de valeurs
    ont été ignorées, plutôt que de les compter pour zéro dans un total."""
    return bool(_NOMBRE.search(str(valeur if valeur is not None else "")))
