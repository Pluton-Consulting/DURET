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
DOSSIER = os.environ.get("DOCUMENTS_DIR", "/tmp/duret-documents")

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
        #
        # LES VIDES D'ABORD. Relevé en production : quatre documents ouverts
        # par des tentatives interrompues, zéro élément chacun — et le
        # cinquième `ouvrir` fermait LE PLUS ANCIEN, c'est-à-dire le seul
        # document REMPLI (21 blocs de rédaction). Le quota détruisait
        # précisément ce qu'il devait protéger. Un document vide ne coûte rien
        # à perdre ; un document rempli coûte tout le travail versé.
        vides = [j for j in ouverts
                 if not int((_lire_fiche(j) or {}).get("elements") or 0)]
        candidats = vides or ouverts
        vieux = min(candidats, key=lambda j: (_lire_fiche(j) or {}).get("ouvert", 0))
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


def ouverts(proprietaire: str) -> list[dict]:
    """Les documents encore ouverts de cette personne, identifiants compris.

    CE QUE LE MODÈLE DOIT SAVOIR D'UN TOUR À L'AUTRE. Relevé en production :
    « Je continue à verser le contenu dans le document déjà ouvert » — et le
    tour s'est terminé sur cette phrase. Le document était bien ouvert, au tour
    D'AVANT : ce tour-ci ne portait aucun résultat d'action, donc ni le rappel
    de clôture ni le sélecteur d'actions ne savaient qu'un travail était en
    cours, ni sous quel identifiant. Sans identifiant à recopier, le modèle ne
    peut que promettre — ou rouvrir un document et perdre le contenu versé.
    """
    sortie = []
    for jeton in _ouverts_de(proprietaire):
        f = _lire_fiche(jeton) or {}
        entete = f.get("entete") or {}
        sortie.append({"document_id": jeton, "titre": entete.get("titre"),
                       "format": entete.get("format"),
                       "elements": int(f.get("elements") or 0)})
    return sortie


def termines(proprietaire: str) -> list[dict]:
    """Les documents FINIS de cette personne — encore téléchargeables.

    UN DOCUMENT TERMINÉ NE DOIT PAS DISPARAÎTRE DE LA VUE. Relevé en
    production : « test 2 » venait d'être finalisé (38 Ko, 21 blocs) ; au tour
    suivant, la liste des documents ne montrant que les OUVERTS, le modèle a
    répondu « ce document n'existe pas », est parti le chercher sur le serveur
    (où il n'avait jamais été déposé), et a fini par proposer de déposer un
    document VIDE à sa place. Le document le plus important de la conversation
    était le seul que le modèle ne pouvait plus voir.
    """
    sortie = []
    try:
        fichiers = os.listdir(DOSSIER)
    except OSError:
        return sortie
    for nom in fichiers:
        if not nom.endswith(".json"):
            continue
        jeton = nom[:-5]
        f = _lire_fiche(jeton)
        if not f or f.get("proprietaire") != proprietaire or not f.get("fini"):
            continue
        entete = f.get("entete") or {}
        sortie.append({"document_id": jeton, "titre": entete.get("titre"),
                       "format": entete.get("format"),
                       "elements": int(f.get("elements") or 0),
                       "octets": int(f.get("octets") or 0),
                       "pages_estimees": f.get("pages_estimees")})
    # Les plus récents d'abord : c'est d'eux qu'on parle dans la conversation.
    sortie.sort(key=lambda d: (_lire_fiche(d["document_id"]) or {}).get("termine", 0),
                reverse=True)
    return sortie


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


def _extrait(jeton: str, limite: int = 900) -> str:
    """Le DÉBUT RÉEL du document, pour l'aperçu dans le chat.

    C'est ce qui permet de MONTRER ce qui a été produit sans le réinventer :
    un aperçu recomposé de mémoire par le modèle finit toujours par diverger
    du fichier, et c'est le fichier qui fait foi.
    """
    bouts: list[str] = []
    total = 0
    for e in elements(jeton):
        bloc = e.get("bloc")
        t = str(e.get("texte") or "")
        if bloc == "titre" and t:
            t = ("#" * max(1, int(e.get("niveau") or 1))) + " " + t
        elif bloc == "liste":
            t = "\n".join(f"- {i}" for i in (e.get("items") or [])[:6])
        elif bloc in ("tableau", "feuille"):
            t = f"[{bloc} : {len(e.get('lignes') or [])} ligne(s)]"
        elif bloc in ("saut_page", "separateur"):
            continue
        if not t:
            continue
        bouts.append(t)
        total += len(t)
        if total >= limite:
            break
    return "\n\n".join(bouts)[:limite]


def _pages_estimees(jeton: str, extension: str) -> int | None:
    """Combien de pages fera le fichier — une ESTIMATION, jamais un mensonge.

    « Il fait combien de pages ? » est la première question posée sur un
    document produit, et elle restait sans réponse. On l'estime depuis le
    contenu : les sauts de page explicites d'une part, le volume de texte
    d'autre part (~2 800 caractères par page en corps 11), et c'est le plus
    grand des deux qui compte. Un tableur n'a pas de pages : None.
    """
    if extension == "xlsx":
        return None
    caracteres = 0
    sauts = 0
    for e in elements(jeton):
        bloc = e.get("bloc")
        if bloc == "saut_page":
            sauts += 1
        elif bloc == "titre":
            caracteres += len(e.get("texte") or "") + 120   # marges d'un titre
        elif bloc == "paragraphe":
            caracteres += len(e.get("texte") or "") + 40
        elif bloc == "liste":
            caracteres += sum(len(i) + 30 for i in (e.get("items") or []))
        elif bloc in ("tableau", "feuille"):
            caracteres += 90 * (1 + len(e.get("lignes") or []))
    return max(1, 1 + sauts, -(-caracteres // 2800))


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
              "octets": os.path.getsize(sortie), "termine": time.time(),
              "extrait": _extrait(jeton),
              "pages_estimees": _pages_estimees(jeton, extension)})
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
