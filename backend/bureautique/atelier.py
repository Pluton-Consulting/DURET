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

import hashlib
import json
import logging
import os
import secrets
import threading
import time

logger = logging.getLogger("duret.bureautique.atelier")

# Emplacement des documents en cours et rendus. Volume du conteneur : ils
# survivent à un redémarrage, le temps que la personne les télécharge.
DOSSIER = os.environ.get("DOCUMENTS_DIR", "/tmp/duret-documents")

# Valeurs historiques conservées pour compatibilité. La purge est désormais
# activée uniquement par DOCUMENTS_RETENTION_JOURS ; aucun effacement par défaut.
DUREE_VIE_S = 24 * 3600
# UN BROUILLON REMPLI VIT PLUS LONGTEMPS (16/09, audit D-04). La purge
# balayait les fichiers un par un, à l'ancienneté : elle pouvait emporter le
# `.jsonl` d'un document ouvert, ou les images d'un rendu encore cité par un
# brouillon de mail, et laisser une fiche qui promet un fichier disparu. On
# purge désormais par GROUPE (fiche + contenu + rendu + images), et jamais un
# document ouvert qui porte du travail avant ce délai-là.
DUREE_VIE_BROUILLON_S = 7 * 24 * 3600
MAX_OUVERTS_PAR_PERSONNE = 5


class TropDeDocuments(ValueError):
    """Quota atteint, et AUCUN document vide à fermer à la place.

    Avant, on fermait « le plus ancien » — donc parfois le seul document
    REMPLI. Un brouillon qui porte du travail ne s'efface pas tout seul : on
    le dit, et la personne choisit lequel terminer ou abandonner.
    """

    def __init__(self, ouverts_: list):
        self.ouverts = ouverts_
        noms = ", ".join(f"« {d.get('titre') or d['document_id'][:8]} » ({d.get('elements', 0)} élément(s))"
                         for d in ouverts_)
        super().__init__(
            f"{len(ouverts_)} documents sont déjà ouverts et contiennent du travail : {noms}. "
            "Termine-en un (`terminer_document`) ou abandonne-le explicitement avant d'en ouvrir un autre.")


# UN VERROU PAR DOCUMENT (16/09, audit D-04). La fiche JSON et le contenu JSONL
# sont deux écritures : deux versements simultanés pouvaient entrelacer le
# compteur et le contenu. Le verrou tient le couple ; la réconciliation
# (`_reconcilier`) rattrape ce qu'une interruption aurait laissé de travers.
_VERROUS: dict = {}
_VERROU_DES_VERROUS = threading.Lock()


def _verrou(jeton: str):
    from stockage.verrous import verrou_fichier
    return verrou_fichier(DOSSIER, jeton)


def _serialise(fonction):
    from functools import wraps
    @wraps(fonction)
    def execute(jeton, *args, **kwargs):
        with _verrou(jeton):
            from security.conversation import fil_courant
            fil = fil_courant.get()
            f = _lire_fiche(jeton) or {}
            if fonction.__name__ != "fiche" and fil and f.get("fil") and f["fil"] != fil:
                raise ValueError("Ce document appartient à une autre conversation. Crée une copie dans ce fil avant de le modifier.")
            return fonction(jeton, *args, **kwargs)
    return execute


def _chemin(jeton: str, suffixe: str) -> str:
    return os.path.join(DOSSIER, f"{jeton}.{suffixe}")


def _lire_fiche(jeton: str) -> dict | None:
    try:
        with open(_chemin(jeton, "json"), encoding="utf-8") as f:
            fiche = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    # UN JSON ÉTRANGER N'EST PAS UNE FICHE (17/09) : un fichier de sauvegarde posé
    # dans ce dossier (une LISTE) faisait lever `.get` à chaque ouverture de
    # document — un mémoire entièrement rédigé ne pouvait plus être rendu.
    return fiche if isinstance(fiche, dict) else None


def _ecrire_fiche(jeton: str, fiche: dict) -> None:
    """Écriture ATOMIQUE (16/09, audit D-04) : fichier temporaire puis
    remplacement. Une coupure au milieu laissait une fiche tronquée — le
    document devenait introuvable, et son contenu avec lui."""
    chemin = _chemin(jeton, "json")
    # Un temporaire PAR ÉCRIVAIN : deux fils qui écrivent la même fiche
    # partageaient le même nom, et le second renommait un fichier déjà déplacé.
    temporaire = f"{chemin}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(temporaire, "w", encoding="utf-8") as f:
        json.dump(fiche, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporaire, chemin)


def _compter_elements(jeton: str) -> int:
    """Le nombre RÉEL d'éléments écrits, lu dans le contenu."""
    n = 0
    try:
        with open(_chemin(jeton, "jsonl"), encoding="utf-8") as f:
            for ligne in f:
                if ligne.strip():
                    n += 1
    except OSError:
        return 0
    return n


def _reconcilier(jeton: str, fiche_: dict) -> dict:
    """LE CONTENU FAIT FOI (audit D-04). Si un processus s'est arrêté entre
    l'écriture du contenu et celle de la fiche, le compteur ment : on le remet
    sur ce que le fichier porte vraiment, et on le réécrit."""
    if fiche_.get("fini"):
        return fiche_
    reel = _compter_elements(jeton)
    if reel != int(fiche_.get("elements") or 0):
        logger.info("Document %s : compteur réconcilié (%s → %d)", jeton[:8],
                    fiche_.get("elements"), reel)
        fiche_["elements"] = reel
        try:
            _ecrire_fiche(jeton, fiche_)
        except OSError:
            pass
    return fiche_


def _groupe(jeton: str) -> list:
    """Tous les fichiers d'un document : fiche, contenu, rendu, images."""
    fichiers = []
    try:
        for nom in os.listdir(DOSSIER):
            if nom == jeton or nom.startswith(f"{jeton}."):
                fichiers.append(os.path.join(DOSSIER, nom))
    except OSError:
        pass
    return fichiers


def purger() -> int:
    """Rétention explicite, par document, sans toucher aux registres voisins.

    Zéro (défaut) conserve les données. Une rétention positive se configure
    par DOCUMENTS_RETENTION_JOURS. La purge saute les documents utilisés et
    ne tente jamais d'attendre un second verrou pendant une révision.
    """
    from stockage.verrous import verrou_fichier
    import re
    try:
        jours = max(0, int(os.environ.get("DOCUMENTS_RETENTION_JOURS", "0")))
    except ValueError:
        logger.error("DOCUMENTS_RETENTION_JOURS invalide : aucune suppression")
        return 0
    if not jours:
        return 0
    maintenant = time.time()
    duree = jours * 86400
    retires = 0
    try:
        noms = os.listdir(DOSSIER)
    except OSError:
        return 0
    # Une SQLite d'authentification, un registre ou un index n'est PAS un
    # document orphelin. Seules les identités produites par l'atelier comptent.
    jetons = {n.split(".")[0] for n in noms
              if re.fullmatch(r"[A-Za-z0-9_-]{32}(?:\..+)?", n)}
    for jeton in jetons:
        with verrou_fichier(DOSSIER, jeton, bloquant=False) as acquis:
            if not acquis:
                continue
            fiche_ = _lire_fiche(jeton)
            if fiche_:
                # Un travail rempli non terminé ou un document épinglé garde
                # ses octets jusqu'à une action explicite de son propriétaire.
                if fiche_.get("conserver") or (not fiche_.get("fini") and fiche_.get("elements")):
                    continue
                age = maintenant - float(fiche_.get("termine") or fiche_.get("ouvert") or maintenant)
                minimum = max(duree, DUREE_VIE_BROUILLON_S) if fiche_.get("origine") == "piece_validation" else duree
                if age <= minimum:
                    continue
            else:
                groupe = _groupe(jeton)
                try:
                    if not groupe or any(os.path.getmtime(c) >= maintenant - duree for c in groupe):
                        continue
                except FileNotFoundError:
                    continue
            for chemin in _groupe(jeton):
                try:
                    os.remove(chemin)
                    retires += 1
                except OSError:
                    continue
    return retires


def ouvrir(entete: dict, proprietaire: str, fil: str | None = None,
           source_ref: str | None = None, document_id: str | None = None,
           parent_revision: str | None = None) -> str:
    """Ouvre un document et rend son jeton. Le jeton EST le droit d'accès.

    (16/09, audit D-04) La fiche porte désormais sa LIGNÉE : `document_id`
    stable, `revision` (le jeton), `parent_revision`, le fil de travail et la
    référence de la source dont il est repris. Une retouche n'est plus un
    document sans parent : c'est une révision de plus du même document.
    """
    os.makedirs(DOSSIER, exist_ok=True)
    purger()

    from stockage.verrous import verrou_fichier
    from stockage.capacite import verifier as verifier_place
    verifier_place(DOSSIER)
    with verrou_fichier(DOSSIER, "quota:" + str(proprietaire), bloquant=False) as acquis:
        if not acquis:
            raise ValueError("Un document est déjà en préparation pour ce compte ; réessayez dans un instant.")
        ouverts = [j for j in _ouverts_de(proprietaire)]
        if len(ouverts) >= MAX_OUVERTS_PAR_PERSONNE:
            # On ferme le plus ancien plutôt que de refuser : un document oublié ne
            # doit pas empêcher d'en commencer un nouveau.
            #
            # LES VIDES D'ABORD. Relevé en production (projet jumeau) : quatre
            # documents ouverts par des tentatives interrompues, zéro élément
            # chacun — et le cinquième `ouvrir` fermait LE PLUS ANCIEN,
            # c'est-à-dire le seul document REMPLI (21 blocs de rédaction). Le
            # quota détruisait précisément ce qu'il devait protéger. Un document
            # vide ne coûte rien à perdre ; un document rempli coûte tout le
            # travail versé.
            # (16/09, audit D-04) ET SI AUCUN N'EST VIDE, ON NE DÉTRUIT RIEN : on
            # refuse en nommant les documents ouverts. Effacer un brouillon rempli
            # pour faire de la place, c'est perdre le travail qu'on protégeait.
            vides = [j for j in ouverts
                     if not int((_lire_fiche(j) or {}).get("elements") or 0)]
            if not vides:
                raise TropDeDocuments([{"document_id": j,
                                        "titre": ((_lire_fiche(j) or {}).get("entete") or {}).get("titre"),
                                        "elements": int((_lire_fiche(j) or {}).get("elements") or 0)}
                                       for j in ouverts])
            vieux = min(vides, key=lambda j: (_lire_fiche(j) or {}).get("ouvert", 0))
            abandonner(vieux, proprietaire)

        # Jeton imprévisible : il sert de clé de téléchargement, il ne doit pas se
        # deviner à partir d'un autre.
        jeton = secrets.token_urlsafe(24)
        _ecrire_fiche(jeton, {"entete": entete, "proprietaire": proprietaire,
                              "ouvert": time.time(), "elements": 0, "fini": False,
                              # La lignée : le jeton EST l'identifiant de révision ;
                              # `document_id` traverse les révisions.
                              "document_id": document_id or jeton, "revision": jeton,
                              "parent_revision": parent_revision, "fil": fil,
                              "source_ref": source_ref})
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


def ouverts(proprietaire: str, fil: str | None = None) -> list[dict]:
    """Les documents encore ouverts de cette personne, identifiants compris.

    CE QUE LE MODÈLE DOIT SAVOIR D'UN TOUR À L'AUTRE. Relevé en production
    (projet jumeau, même moteur) : « Je continue à verser le contenu dans le
    document déjà ouvert » — et le tour s'est terminé sur cette phrase. Le
    document était bien ouvert, au tour D'AVANT : ce tour-ci ne portait aucun
    résultat d'action, donc ni le rappel de clôture ni le sélecteur d'actions
    ne savaient qu'un travail était en cours, ni sous quel identifiant. Sans
    identifiant à recopier, le modèle ne peut que promettre — ou rouvrir un
    document et perdre le contenu versé.
    """
    sortie = []
    for jeton in _ouverts_de(proprietaire):
        f = _lire_fiche(jeton) or {}
        if fil is not None and (f.get("fil") or "") != fil:
            continue
        entete = f.get("entete") or {}
        sortie.append({"document_id": jeton, "titre": entete.get("titre"),
                       "format": entete.get("format"),
                       "elements": int(f.get("elements") or 0)})
    return sortie


# CE QUI COMPTE COMME PRODUIT. Une fiche sans origine vient de `ouvrir` (le
# modèle a rédigé le document) ; « trame » et « reproduction » sont fabriqués
# à partir d'un modèle, pour la personne. Tout le reste est REÇU (pièce jointe
# d'un mail, « piece_jointe ») ou LU sur le serveur de fichiers (« serveur »,
# 08/09) : rangé à l'atelier pour être téléchargeable et prévisualisable, il
# n'a PAS été rédigé — et le compter parmi les documents produits mène le
# modèle à le présenter comme un livrable. Relevé le 09/09 : un PDF de paie
# (« DSN_082026.pdf ») ouvert la veille sur le Drive pendant un essai était
# rendu « dans le dossier » du client à CHAQUE conversation, avec les vrais
# livrables, parce que la liste des documents terminés le portait.
ORIGINES_PRODUITES = frozenset({"", "trame", "reproduction"})
# Le DÉBUT réel d'un document, glissé dans sa fiche pour que le modèle décrive
# ce qu'il contient au lieu de le deviner d'après le titre.
LONGUEUR_CONTENU = 240


def produit(fiche: dict) -> bool:
    """Ce document a-t-il été RÉDIGÉ ici (et non reçu d'un mail ou lu sur le serveur) ?"""
    return str((fiche or {}).get("origine") or "") in ORIGINES_PRODUITES


def termines(proprietaire: str, fil: str | None = None) -> list[dict]:
    """Les documents FINIS de cette personne — encore téléchargeables.

    PRODUITS seulement (`produit`) : un fichier reçu ou lu ailleurs reste
    téléchargeable par son jeton, mais il ne figure pas dans la liste que le
    modèle lit comme « tes documents ». Chaque entrée porte `contenu`, le
    début réel du document (09/09 : « l'inventaire Excel reprend le détail
    chiffré des fournitures » — faux, c'était la liste des fichiers d'un
    dossier ; le modèle n'avait que le titre pour en parler).

    UN DOCUMENT TERMINÉ NE DOIT PAS DISPARAÎTRE DE LA VUE. Relevé en
    production (projet jumeau) : « test 2 » venait d'être finalisé (38 Ko,
    21 blocs) ; au tour suivant, la liste des documents ne montrant que les
    OUVERTS, le modèle a répondu « ce document n'existe pas », est parti le
    chercher sur le serveur, et a fini par proposer de déposer un document
    VIDE à sa place. Le document le plus important de la conversation était
    le seul que le modèle ne pouvait plus voir.
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
        if (not f or f.get("proprietaire") != proprietaire or not f.get("fini")
                or (fil is not None and (f.get("fil") or "") != fil)):
            continue
        if not produit(f):
            continue          # reçu ou lu sur le serveur : pas produit
        entete = f.get("entete") or {}
        entree = {"document_id": jeton, "titre": entete.get("titre"),
                  "format": entete.get("format"),
                  "elements": int(f.get("elements") or 0),
                  "octets": int(f.get("octets") or 0),
                  "pages_estimees": f.get("pages_estimees"),
                  # Sa PRÉSENTATION (15/09) : refaire le même titre avec un logo,
                  # une couverture ou un style de plus n'est pas « rallonger ».
                  "presentation": {k: str(entete.get(k) or "") for k in
                                   ("entete_image", "pied_image", "image_couverture", "style")}}
        debut = " ".join(str(f.get("extrait") or "").split())
        if debut:
            entree["contenu"] = (debut[:LONGUEUR_CONTENU] + "…") if len(debut) > LONGUEUR_CONTENU else debut
        sortie.append(entree)
    # Les plus récents d'abord : c'est d'eux qu'on parle dans la conversation.
    sortie.sort(key=lambda d: (_lire_fiche(d["document_id"]) or {}).get("termine", 0),
                reverse=True)
    return sortie


@_serialise
def fiche(jeton: str, proprietaire: str) -> dict | None:
    """Fiche du document SI elle appartient à cette personne, sinon None.

    Le refus est indistinct de l'absence : répondre « ce document existe mais
    n'est pas à vous » confirmerait l'existence d'un jeton à qui le devine.
    """
    f = _lire_fiche(jeton)
    if not f or f.get("proprietaire") != proprietaire:
        return None
    return _reconcilier(jeton, f)


# ── Un versement qui répète le document n'est pas un versement ───────────
#
# 14/09, fil c9f5a00d : « et voici le devis » → 159 `ajouter_document` en
# trente et une minutes, 911 blocs, l'en-tête « Devis N° DV0001451 », le client
# et l'objet réécrits à CHAQUE appel avec une ponctuation qui variait. Le
# modèle ne voyait pas ce qu'il avait déjà versé (corrigé dans
# `agents/memoire_gestes.py`), mais le document, lui, le savait : c'est ici que
# la répétition se VOIT, quel que soit le modèle et quoi qu'il se rappelle.
#
# ON REFUSE LE VERSEMENT ENTIER, JAMAIS UN ÉLÉMENT ISOLÉ. Un titre « Aménagement
# paysager » qui revient en tête de chaque section est légitime ; un versement
# dont la plupart des textes sont DÉJÀ dans le document est un rejeu. On ne
# regarde que les textes assez longs pour être distinctifs (25 caractères), et
# « déjà là » veut dire identique à la casse, aux accents et à la ponctuation
# près, ou quasi identique (ratio ≥ 0,9 : « — » au lieu de « , »).
SEUIL_TEXTE_DISTINCTIF = 25
PART_DEJA_PRESENTE = 0.6
RATIO_QUASI_IDENTIQUE = 0.9


class DejaPresent(ValueError):
    """Le versement répète ce que le document contient déjà."""

    def __init__(self, presents: int, distinctifs: int, exemples: list[str]):
        self.presents, self.distinctifs, self.exemples = presents, distinctifs, exemples
        super().__init__(f"{presents} élément(s) sur {distinctifs} déjà présents")


def _aplati(texte: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", str(texte or "")).encode("ascii", "ignore").decode()
    return " ".join("".join(c if c.isalnum() else " " for c in t.lower()).split())


def texte_d_element(e: dict) -> str:
    """Le texte qui rend un élément reconnaissable (titre, paragraphe, liste, tableau)."""
    if not isinstance(e, dict):
        return ""
    if e.get("texte"):
        return str(e["texte"])
    if isinstance(e.get("items"), list):
        return " ".join((f"{x.get('valeur', '')} {x.get('libelle', '')}" if isinstance(x, dict) else str(x))
                        for x in e["items"])
    if isinstance(e.get("lignes"), list):
        return " ".join(" ".join(map(str, l)) if isinstance(l, list) else str(l)
                        for l in e["lignes"])
    return ""


def deja_presents(jeton: str, nouveaux: list[dict]) -> tuple[int, int, list[str]]:
    """(textes déjà dans le document, textes distinctifs du versement, exemples)."""
    from difflib import SequenceMatcher

    candidats = [(_aplati(texte_d_element(e)), texte_d_element(e)) for e in nouveaux]
    candidats = [(a, brut) for a, brut in candidats if len(a) >= SEUIL_TEXTE_DISTINCTIF]
    if not candidats:
        return 0, 0, []
    existants = {_aplati(texte_d_element(e)) for e in elements(jeton)}
    existants.discard("")
    presents, exemples = 0, []
    for aplati, brut in candidats:
        trouve = aplati in existants
        if not trouve:
            for ex in existants:
                m = SequenceMatcher(None, aplati, ex)
                if (m.real_quick_ratio() >= RATIO_QUASI_IDENTIQUE
                        and m.quick_ratio() >= RATIO_QUASI_IDENTIQUE
                        and m.ratio() >= RATIO_QUASI_IDENTIQUE):
                    trouve = True
                    break
        if trouve:
            presents += 1
            if len(exemples) < 3:
                exemples.append(" ".join(brut.split())[:70])
    return presents, len(candidats), exemples


def plan(jeton: str, limite: int = 30) -> list[str]:
    """Les titres du document, dans l'ordre : sa structure, en une liste courte."""
    titres = []
    for e in elements(jeton):
        if isinstance(e, dict) and e.get("bloc") == "titre" and e.get("texte"):
            titres.append(" ".join(str(e["texte"]).split())[:60])
    if len(titres) > limite:
        return titres[: limite // 2] + [f"… {len(titres) - limite} titre(s) …"] + titres[-limite // 2:]
    return titres


@_serialise
def ajouter(jeton: str, elements: list[dict], proprietaire: str,
            refuser_repetition: bool = True) -> int:
    """Ajoute des éléments. Rend le nombre retenu.

    Lève `DejaPresent` quand l'essentiel du versement est déjà dans le document.
    """
    from bureautique.modele import normaliser_element, deplier_feuilles, MAX_ELEMENTS

    f = fiche(jeton, proprietaire)
    if f is None:
        raise KeyError("document inconnu")
    if f.get("fini"):
        raise ValueError("document déjà terminé")

    retenus = [e for e in (normaliser_element(x) for x in deplier_feuilles(elements)) if e]
    if refuser_repetition and int(f.get("elements") or 0) > 0:
        presents, distinctifs, exemples = deja_presents(jeton, retenus)
        if distinctifs and presents >= 2 and presents / distinctifs >= PART_DEJA_PRESENTE:
            raise DejaPresent(presents, distinctifs, exemples)
    place = MAX_ELEMENTS - int(f.get("elements") or 0)
    if place <= 0:
        raise ValueError(f"document plein ({MAX_ELEMENTS} éléments)")
    retenus = retenus[:place]

    # SOUS VERROU, ET LE CONTENU EST POSÉ AVANT LE COMPTEUR (audit D-04) :
    # deux versements simultanés ne s'entrelacent plus, et une coupure entre
    # les deux écritures laisse un compteur en retard — jamais en avance —,
    # que `_reconcilier` remet d'aplomb à la lecture suivante.
    with _verrou(jeton):
        with open(_chemin(jeton, "jsonl"), "a", encoding="utf-8") as fichier:
            for e in retenus:
                fichier.write(json.dumps(e, ensure_ascii=False) + "\n")
            fichier.flush()
            os.fsync(fichier.fileno())
        f = _lire_fiche(jeton) or f
        f["elements"] = _compter_elements(jeton)
        _ecrire_fiche(jeton, f)
    return len(retenus)


@_serialise
def ranger_image(jeton: str, proprietaire: str, octets: bytes, extension: str) -> str:
    """Range les octets d'une image SOUS LE JETON du document (`<jeton>.img<n>.<ext>`)
    et rend ce nom de fichier — la seule forme que le rendu lit. L'image suit
    la durée de vie du document (purge, abandon). Réservé au propriétaire d'un
    document encore ouvert."""
    f = fiche(jeton, proprietaire)
    if f is None:
        raise KeyError("document inconnu")
    if f.get("fini"):
        raise ValueError("document déjà terminé")
    extension = "jpg" if str(extension).lower() in ("jpg", "jpeg") else "png"
    prefixe = f"{jeton}.img"
    try:
        existants = [n for n in os.listdir(DOSSIER) if n.startswith(prefixe)]
    except OSError:
        existants = []
    nom = f"{prefixe}{len(existants) + 1}.{extension}"
    with open(os.path.join(DOSSIER, nom), "wb") as sortie:
        sortie.write(octets)
    logger.info("Image %s rangée pour le document %s (%d octets)", nom.split(".img")[-1], jeton[:8], len(octets))
    return nom


def chemin_image(fichier: str) -> str | None:
    """Le chemin d'une image rangée, si elle existe — un nom nu, jamais un chemin."""
    from bureautique.modele import RE_IMAGE_RANGEE
    fichier = os.path.basename(str(fichier or ""))
    if not RE_IMAGE_RANGEE.match(fichier):
        return None
    chemin = os.path.join(DOSSIER, fichier)
    return chemin if os.path.exists(chemin) else None


@_serialise
def mettre_a_jour_entete(jeton: str, proprietaire: str, entete: dict) -> None:
    """Remplace l'en-tête d'un document ouvert (images d'en-tête/pied rangées)."""
    f = fiche(jeton, proprietaire)
    if f is None:
        raise KeyError("document inconnu")
    if f.get("fini"):
        raise ValueError("document déjà terminé")
    f["entete"] = dict(entete or {})
    _ecrire_fiche(jeton, f)


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
        elif bloc == "image":
            t = f"[image{' : ' + str(e.get('legende')) if e.get('legende') else ''}]"
        elif bloc == "chiffres":
            t = " · ".join(f"{i.get('valeur')} {i.get('libelle') or ''}".strip() for i in (e.get("items") or []))
        elif bloc == "colonnes":
            t = (str(e.get("titre") or "") + " " + t).strip() + " [photo]"
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


@_serialise
def terminer(jeton: str, proprietaire: str) -> dict:
    """Rend le fichier et marque le document comme fini."""
    from bureautique.rendu import rendre

    f = fiche(jeton, proprietaire)
    if f is None:
        raise KeyError("document inconnu")
    if f.get("fini"):
        chemin = chemin_fichier(jeton, proprietaire)
        if not chemin:
            raise ValueError("Le fichier terminé est manquant ; restaurez-le ou créez une nouvelle révision.")
        return f  # Une seconde demande ne réécrit jamais le rendu approuvé.
    if not f.get("elements"):
        raise ValueError("document vide : rien à rendre")

    entete = f["entete"]
    extension = entete.get("format", "docx")
    sortie = _chemin(jeton, extension)
    with _verrou(jeton):
        temporaire = f"{sortie}.{os.getpid()}.tmp"
        try:
            rendre(entete, elements(jeton), temporaire)
            os.replace(temporaire, sortie)
        finally:
            if os.path.exists(temporaire):
                os.remove(temporaire)
        # L'EMPREINTE DU RENDU (16/09, audit D-04) : une révision terminée ne
        # change plus sous le même identifiant. On sait dire, plus tard, si le
        # fichier qu'on tient est bien celui qui a été validé.
        with open(sortie, "rb") as fichier_rendu:
            empreinte = hashlib.sha256(fichier_rendu.read()).hexdigest()[:32]
        f.update({"fini": True, "fichier": os.path.basename(sortie),
                  "octets": os.path.getsize(sortie), "termine": time.time(),
                  "extrait": _extrait(jeton),
                  "pages_estimees": _pages_estimees(jeton, extension),
                  "empreinte": empreinte,
                  "manifeste": manifeste(jeton, f, extension, empreinte)})
        _ecrire_fiche(jeton, f)
    logger.info("Document %s rendu : %s, %d octets, %d éléments",
                jeton[:8], extension, f["octets"], f["elements"])
    return f


@_serialise
def abandonner(jeton: str, proprietaire: str) -> bool:
    """Supprime un document et tout ce qui lui appartient."""
    if fiche(jeton, proprietaire) is None:
        return False
    for suffixe in ("json", "jsonl", "docx", "pdf", "xlsx"):
        try:
            os.remove(_chemin(jeton, suffixe))
        except OSError:
            pass
    # Les images rangées sous ce jeton partent avec lui.
    try:
        for nom in os.listdir(DOSSIER):
            if nom.startswith(f"{jeton}.img"):
                os.remove(os.path.join(DOSSIER, nom))
    except OSError:
        pass
    return True


def deposer_fichier(nom: str, octets: bytes, proprietaire: str, origine: str = "depot", fil: str | None = None) -> str:
    """Range un fichier REÇU (pièce jointe d'un mail) comme un document fini :
    téléchargeable par `/api/documents/{jeton}`, avec aperçu pour PDF / Word /
    Excel, à cette personne seulement. Conservation selon la politique explicite. `origine` = « piece_jointe » le
    tient hors de la liste des documents PRODUITS : il n'a pas été rédigé."""
    os.makedirs(DOSSIER, exist_ok=True)
    purger()
    base, _, ext = (nom or "piece").rpartition(".")
    extension = (ext.lower() if base and 1 <= len(ext) <= 5 else "bin")
    extension = "".join(c for c in extension if c.isalnum()) or "bin"
    from stockage.capacite import verifier as verifier_place
    verifier_place(DOSSIER, len(octets))
    jeton = secrets.token_urlsafe(24)
    with open(_chemin(jeton, extension), "wb") as f:
        f.write(octets)
    _ecrire_fiche(jeton, {"entete": {"titre": base or nom or "piece", "format": extension},
                          "proprietaire": proprietaire, "ouvert": time.time(), "elements": 0,
                          "fini": True, "fichier": f"{jeton}.{extension}", "octets": len(octets),
                          "termine": time.time(), "origine": origine, "fil": fil})
    logger.info("Fichier reçu %s déposé (%s, %d octets)", jeton[:8], extension, len(octets))
    return jeton


def chemin_fichier(jeton: str, proprietaire: str) -> str | None:
    """Chemin du fichier rendu, si le document est fini ET à cette personne."""
    f = fiche(jeton, proprietaire)
    if not f or not f.get("fini"):
        return None
    chemin = _chemin(jeton, f["entete"].get("format", "docx"))
    return chemin if os.path.exists(chemin) else None


# ── LE MANIFESTE D'UN LIVRABLE (16/09, audit D-04) ─────────────────────────
# « Le dernier document de la personne » n'est pas « le dernier livrable de ce
# fil » : l'atelier est par personne, toutes conversations confondues, et un
# tri global rendait le document d'une AUTRE conversation. Chaque rendu porte
# donc ce qu'il faut pour être choisi sciemment : d'où il vient, quelle
# révision il est, ce qu'il contient, ce qui reste à compléter.
def manifeste(jeton: str, fiche_: dict, extension: str, empreinte: str) -> dict:
    """Ce qu'on peut dire d'un livrable sans le rouvrir."""
    images, a_completer, blocs = 0, 0, 0
    for e in elements(jeton):
        if not isinstance(e, dict):
            continue
        blocs += 1
        if e.get("bloc") == "image" or e.get("image"):
            images += 1
        if "[À COMPLÉTER]" in json.dumps(e, ensure_ascii=False):
            a_completer += 1
    entete = fiche_.get("entete") or {}
    for cle in ("entete_image", "pied_image", "image_couverture"):
        if entete.get(cle):
            images += 1
    return {"document_id": fiche_.get("document_id") or jeton,
            "revision": jeton, "parent_revision": fiche_.get("parent_revision"),
            "fil": fiche_.get("fil"), "source_ref": fiche_.get("source_ref"),
            "format": extension, "empreinte": empreinte,
            "titre": entete.get("titre"), "blocs": blocs, "images": images,
            "a_completer": a_completer, "origine": fiche_.get("origine") or "",
            "termine_le": fiche_.get("termine") or time.time()}


@_serialise
def nouvelle_revision(jeton: str, proprietaire: str, entete: dict | None = None) -> str:
    """Ouvre la révision SUIVANTE d'un document (même `document_id`, ce rendu
    pour parent). C'est ce qui fait qu'une retouche reste le même document."""
    precedent = fiche(jeton, proprietaire)
    if precedent is None:
        raise KeyError("document inconnu")
    nouveau = ouvrir(entete or precedent.get("entete") or {}, proprietaire,
                      fil=precedent.get("fil"), source_ref=precedent.get("source_ref"),
                      document_id=precedent.get("document_id") or jeton,
                      parent_revision=jeton)
    correspondances = {}
    try:
        # Copier les médias : la purge de l'ancienne révision ne doit pas
        # casser celle qui vient d'être ouverte.
        for nom in os.listdir(DOSSIER):
            if nom.startswith(f"{jeton}.img"):
                with open(os.path.join(DOSSIER, nom), "rb") as image:
                    correspondances[nom] = ranger_image(nouveau, proprietaire, image.read(), nom.rsplit(".", 1)[-1])
        def remplacer(valeur):
            if isinstance(valeur, dict):
                return {k: remplacer(v) for k, v in valeur.items()}
            if isinstance(valeur, list):
                return [remplacer(v) for v in valeur]
            return correspondances.get(valeur, valeur) if isinstance(valeur, str) else valeur
        mettre_a_jour_entete(nouveau, proprietaire, remplacer(entete or precedent.get("entete") or {}))
        blocs = [remplacer(e) for e in elements(jeton)]
        if blocs:
            ajouter(nouveau, blocs, proprietaire, refuser_repetition=False)
        return nouveau
    except Exception:
        abandonner(nouveau, proprietaire)
        raise


def revisions(proprietaire: str, document_id: str) -> list[dict]:
    """Toutes les révisions connues d'un document, de la plus ancienne à la
    plus récente. Rien n'est supprimé par une nouvelle révision : l'ancienne
    reste téléchargeable, elle n'est simplement plus « la » version."""
    sortie = []
    try:
        noms = os.listdir(DOSSIER)
    except OSError:
        return sortie
    for nom in noms:
        if not nom.endswith(".json"):
            continue
        f = _lire_fiche(nom[:-5])
        if f and f.get("proprietaire") == proprietaire and (f.get("document_id") or "") == document_id:
            sortie.append({"revision": nom[:-5], "parent_revision": f.get("parent_revision"),
                           "fini": bool(f.get("fini")), "termine": f.get("termine"),
                           "empreinte": f.get("empreinte"), "manifeste": f.get("manifeste")})
    sortie.sort(key=lambda d: d.get("termine") or 0)
    return sortie


def dernier_livrable_du_fil(proprietaire: str, fil: str | None) -> dict | None:
    """Le dernier livrable DE CE FIL, choisi sur les manifestes — pas sur un
    tri global des fichiers de la personne (audit D-04). Sans fil connu, rien :
    mieux vaut ne rien désigner que désigner le document d'une autre
    conversation."""
    if not fil:
        return None
    candidats = [d for d in termines(proprietaire)
                 if ((_lire_fiche(d["document_id"]) or {}).get("fil") or "") == str(fil)]
    if not candidats:
        return None
    return max(candidats, key=lambda d: (_lire_fiche(d["document_id"]) or {}).get("termine", 0))
