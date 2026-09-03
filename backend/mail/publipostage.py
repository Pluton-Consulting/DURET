"""
Publipostage — UNE carte de mail par destinataire, en quantité illimitée.

Demande de Noa du 01/09 : « si on lui dit d'envoyer un mail à 100 clients, il
met 100 cartes … il doit être capable de faire des quantités illimitées ».
Faire ÉCRIRE cent cartes par le modèle est impossible (plafond de sortie) et
inutile : la personnalisation d'un gabarit est une MÉCANIQUE. Le modèle écrit
UN gabarit à variables, la liste des destinataires vient des gestes de
données, et ce module fabrique les cartes — par pages de 40, comme tout ce
qui est grand (règle « une recherche ne se bloque jamais »).

Deux niveaux de sur-mesure :
  * le GABARIT à variables — {nom}, {email}, ou n'importe quelle clé portée
    par le destinataire — personnalise chaque carte sans appel de modèle ;
  * un destinataire peut porter son PROPRE corps (`reponse` ou `message`) :
    le modèle écrit alors chaque mail à la main, la mécanique ne fait que
    les ranger en cartes.

RIEN NE PART D'ICI : les cartes s'affichent (bloc `reponses_mail`, éditables,
cochables), et chaque envoi repasse par `envoyer_email` et sa validation
humaine — l'effet externe reste la seule porte de sortie.
"""
from __future__ import annotations

import re

PAR_PAGE = 40
# Une variable absente ne se devine pas : la règle des fiches vaut pour les
# mails — « [À COMPLÉTER] » se voit et se corrige, une valeur plausible part.
MANQUANT = "[À COMPLÉTER]"
_VARIABLE = re.compile(r"\{([a-zA-Z_àâäéèêëîïôöùûüç][\w àâäéèêëîïôöùûüç-]{0,40})\}")


_ADRESSE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def _plat(cle) -> str:
    """« Prénom », « Nom ? », « E-mail » → prenom, nom, email : la clé telle
    qu'un gabarit l'écrit. Les en-têtes d'un export portent des accents, des
    espaces et de la ponctuation que personne ne recopie dans `{prenom}`."""
    import unicodedata
    s = unicodedata.normalize("NFKD", str(cle or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _substituer(gabarit: str, dest: dict) -> str:
    def _valeur(m):
        cle = _plat(m.group(1))
        for k, v in dest.items():
            if _plat(k) == cle and v not in (None, ""):
                return str(v)
        return MANQUANT
    return _VARIABLE.sub(_valeur, str(gabarit or ""))


def _adresse_dans(d: dict) -> str:
    """L'adresse d'une ligne de tableau, où qu'elle soit.

    D'abord les clés qui la NOMMENT (email, mail, e-mail, adresse, courriel…),
    puis, à défaut, N'IMPORTE QUELLE valeur qui a la forme d'une adresse. Le
    fichier du 03/09 portait l'adresse en colonne « Colonne AG » pour la
    moitié des lignes : sans ce repli, ces clients-là restaient sans mail.
    """
    for k, v in d.items():
        if _plat(k) in ("email", "mail", "adresse", "de", "courriel", "adressemail",
                        "adresseemail", "mel") and v:
            trouve = _ADRESSE.search(str(v))
            if trouve:
                return trouve.group(0)
    for v in d.values():
        if isinstance(v, str):
            trouve = _ADRESSE.search(v)
            if trouve:
                return trouve.group(0)
    return ""


def _normaliser(destinataires) -> list[dict]:
    """Accepte une liste de dicts (y compris des lignes brutes d'un tableau
    joint, via `@tableau`), d'adresses nues, ou un mélange."""
    sortie: list[dict] = []
    for d in destinataires or []:
        if isinstance(d, dict):
            entree = dict(d)
            entree["email"] = _adresse_dans(d)
            sortie.append(entree)
        elif isinstance(d, str) and d.strip():
            sortie.append({"email": d.strip()})
    return sortie


def construire_cartes(sujet: str, gabarit: str, destinataires,
                      page: int = 1, par_page: int = PAR_PAGE) -> dict:
    """Les cartes de la page demandée, plus les comptes pour enchaîner.

    Pure : aucune E/S, aucun appel réseau — c'est ce qui la rend testable et
    ce qui garantit qu'aucun envoi ne peut partir d'ici.
    """
    tous = _normaliser(destinataires)
    nombre = len(tous)
    page = max(1, int(page or 1))
    par_page = max(1, min(int(par_page or PAR_PAGE), PAR_PAGE))
    pages = max(1, -(-nombre // par_page))
    debut = (page - 1) * par_page

    cartes = []
    sans_adresse = 0
    for dest in tous[debut:debut + par_page]:
        if not dest.get("email"):
            sans_adresse += 1
            continue
        # Le corps SUR MESURE du destinataire prime sur le gabarit : c'est la
        # voie « chaque mail écrit à la main », rangée par la même mécanique.
        corps = str(dest.get("reponse") or dest.get("message") or "").strip() \
            or _substituer(gabarit, dest)
        cartes.append({
            "de": dest["email"],
            "objet": _substituer(sujet, dest),
            "synthese": ("Mail préparé pour "
                         + str(dest.get("nom") or dest.get("client")
                               or dest["email"])),
            "reponse": corps,
        })

    sortie: dict = {"nombre": nombre, "page": page, "pages": pages,
                    "cartes": cartes}
    if sans_adresse:
        sortie["sans_adresse"] = sans_adresse
    if page < pages:
        sortie["pour_continuer"] = (
            f"{nombre} destinataire(s) au total : rappelle preparer_envois avec "
            f"les MÊMES paramètres et page={page + 1} pour les suivants — "
            "enchaîne jusqu'à couvrir tout le monde.")
    return sortie
