"""
Atelier : un document s'ouvre, se remplit en plusieurs fois, puis se ferme.

POURQUOI. Un rapport de deux cents pages ne tient pas dans une réponse de
modèle. Sans cette découpe, la seule façon de produire un gros document serait
de tout demander d'un coup — et la réponse serait tronquée au milieu d'un
tableau, sans que rien ne le signale.

Chaque ajout est écrit sur DISQUE, une ligne JSON par élément. La taille du
document n'est donc jamais bornée par la mémoire d'un processus, et un
enrichissement interrompu laisse ce qui a déjà été écrit.

CLOISONNEMENT. Un document appartient à qui l'a ouvert. Personne d'autre ne peut
y ajouter, le fermer, ni le télécharger — pas même un administrateur : un
brouillon de rapport n'a pas à être lisible par un tiers sous prétexte de rôle.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import time

logger = logging.getLogger("duret.bureautique.atelier")

# Emplacement des documents en cours et rendus. Volume du conteneur : ils
# survivent à un redémarrage, le temps que la personne les télécharge.
DOSSIER = os.environ.get("DOCUMENTS_DIR", "/tmp/symbiose-documents")

# Un document non téléchargé finit par disparaître : ce sont des données
# d'entreprise, elles ne doivent pas s'accumuler indéfiniment sur le disque.
DUREE_VIE_S = 24 * 3600
MAX_OUVERTS_PAR_PERSONNE = 5


def _chemin(jeton: str, suffixe: str) -> str:
    return os.path.join(DOSSIER, f"{jeton}.{suffixe}")


def _lire_fiche(jeton: str) -> dict | None:
    try:
        with open(_chemin(jeton, "json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _ecrire_fiche(jeton: str, fiche: dict) -> None:
    with open(_chemin(jeton, "json"), "w", encoding="utf-8") as f:
        json.dump(fiche, f, ensure_ascii=False)


def purger() -> int:
    """Supprime ce qui a dépassé sa durée de vie. Ne lève jamais."""
    retires = 0
    try:
        limite = time.time() - DUREE_VIE_S
        for nom in os.listdir(DOSSIER):
            chemin = os.path.join(DOSSIER, nom)
            try:
                if os.path.getmtime(chemin) < limite:
                    os.remove(chemin)
                    retires += 1
            except OSError:
                continue
    except OSError:
        pass
    return retires


def ouvrir(entete: dict, proprietaire: str) -> str:
    """Ouvre un document et rend son jeton. Le jeton EST le droit d'accès."""
    os.makedirs(DOSSIER, exist_ok=True)
    purger()

    ouverts = [j for j in _ouverts_de(proprietaire)]
    if len(ouverts) >= MAX_OUVERTS_PAR_PERSONNE:
        # On ferme le plus ancien plutôt que de refuser : un document oublié ne
        # doit pas empêcher d'en commencer un nouveau.
        vieux = min(ouverts, key=lambda j: (_lire_fiche(j) or {}).get("ouvert", 0))
        abandonner(vieux, proprietaire)

    # Jeton imprévisible : il sert de clé de téléchargement, il ne doit pas se
    # deviner à partir d'un autre.
    jeton = secrets.token_urlsafe(24)
    _ecrire_fiche(jeton, {"entete": entete, "proprietaire": proprietaire,
                          "ouvert": time.time(), "elements": 0, "fini": False})
    open(_chemin(jeton, "jsonl"), "w", encoding="utf-8").close()
    logger.info("Document %s ouvert (%s)", jeton[:8], entete.get("format"))
    return jeton


def _ouverts_de(proprietaire: str) -> list[str]:
    try:
        fichiers = os.listdir(DOSSIER)
    except OSError:
        return []
    out = []
    for nom in fichiers:
        if not nom.endswith(".json"):
            continue
        jeton = nom[:-5]
        fiche = _lire_fiche(jeton)
        if fiche and fiche.get("proprietaire") == proprietaire and not fiche.get("fini"):
            out.append(jeton)
    return out


def fiche(jeton: str, proprietaire: str) -> dict | None:
    """Fiche du document SI elle appartient à cette personne, sinon None.

    Le refus est indistinct de l'absence : répondre « ce document existe mais
    n'est pas à vous » confirmerait l'existence d'un jeton à qui le devine.
    """
    f = _lire_fiche(jeton)
    return f if f and f.get("proprietaire") == proprietaire else None


def ajouter(jeton: str, elements: list[dict], proprietaire: str) -> int:
    """Ajoute des éléments. Rend le nombre retenu."""
    from bureautique.modele import normaliser_element, MAX_ELEMENTS

    f = fiche(jeton, proprietaire)
    if f is None:
        raise KeyError("document inconnu")
    if f.get("fini"):
        raise ValueError("document déjà terminé")

    retenus = [e for e in (normaliser_element(x) for x in (elements or [])) if e]
    place = MAX_ELEMENTS - int(f.get("elements") or 0)
    if place <= 0:
        raise ValueError(f"document plein ({MAX_ELEMENTS} éléments)")
    retenus = retenus[:place]

    with open(_chemin(jeton, "jsonl"), "a", encoding="utf-8") as fichier:
        for e in retenus:
            fichier.write(json.dumps(e, ensure_ascii=False) + "\n")

    f["elements"] = int(f.get("elements") or 0) + len(retenus)
    _ecrire_fiche(jeton, f)
    return len(retenus)


def elements(jeton: str):
    """Parcourt les éléments un par un — jamais tout en mémoire."""
    try:
        with open(_chemin(jeton, "jsonl"), encoding="utf-8") as f:
            for ligne in f:
                ligne = ligne.strip()
                if not ligne:
                    continue
                try:
                    yield json.loads(ligne)
                except json.JSONDecodeError:
                    continue        # une ligne abîmée ne perd pas le document
    except OSError:
        return


def terminer(jeton: str, proprietaire: str) -> dict:
    """Rend le fichier et marque le document comme fini."""
    from bureautique.rendu import rendre

    f = fiche(jeton, proprietaire)
    if f is None:
        raise KeyError("document inconnu")
    if not f.get("elements"):
        raise ValueError("document vide : rien à rendre")

    entete = f["entete"]
    extension = entete.get("format", "docx")
    sortie = _chemin(jeton, extension)
    rendre(entete, elements(jeton), sortie)

    f.update({"fini": True, "fichier": os.path.basename(sortie),
              "octets": os.path.getsize(sortie), "termine": time.time()})
    _ecrire_fiche(jeton, f)
    logger.info("Document %s rendu : %s, %d octets, %d éléments",
                jeton[:8], extension, f["octets"], f["elements"])
    return f


def abandonner(jeton: str, proprietaire: str) -> bool:
    """Supprime un document et tout ce qui lui appartient."""
    if fiche(jeton, proprietaire) is None:
        return False
    for suffixe in ("json", "jsonl", "docx", "pdf", "xlsx"):
        try:
            os.remove(_chemin(jeton, suffixe))
        except OSError:
            pass
    return True


def chemin_fichier(jeton: str, proprietaire: str) -> str | None:
    """Chemin du fichier rendu, si le document est fini ET à cette personne."""
    f = fiche(jeton, proprietaire)
    if not f or not f.get("fini"):
        return None
    chemin = _chemin(jeton, f["entete"].get("format", "docx"))
    return chemin if os.path.exists(chemin) else None
