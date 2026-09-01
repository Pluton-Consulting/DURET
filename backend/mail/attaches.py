"""
De ce que le modèle NOMME aux OCTETS qui partiront dans le message.

POURQUOI UN MODULE À PART. Une pièce jointe n'est jamais un chemin de fichier :
un skill qui accepterait un chemin serait un moyen d'exfiltration — on lui
demanderait `/app/backend/secrets/…` et il l'enverrait. Le modèle ne désigne
donc QUE ce qu'un geste lui a déjà rendu, sous une des quatre formes que le
code produit déjà :

  · le jeton d'un document de l'atelier (32 caractères base64url) — tout
    document PRODUIT, et toute pièce jointe déjà déposée ;
  · la clé d'une image du dépôt (24 hexadécimaux) — photos du NAS,
    images de mails, vignettes DWG ;
  · la `ref` d'une pièce d'un mail ouvert (16 hexadécimaux) ;
  · le NOM ou le CHEMIN d'un fichier du NAS.

Chaque forme porte SA PROPRE vérification de droits, appliquée par la fonction
qui la résout : composer deux gestes ne compose pas les droits (leçon de
`drive.deposer_document`). Un jeton d'atelier n'ouvre que les documents de la
personne connectée ; une `ref` de pièce est liée à SA boîte ; un chemin du NAS
passe par `verifier()`, donc par le périmètre autorisé.

UNE PIÈCE QU'ON NE PEUT PAS JOINDRE EST REFUSÉE AVEC SA RAISON — jamais
ignorée. Un message qui part sans son devis pendant que le corps annonce
« veuillez trouver ci-joint » est un mensonge par omission ; c'est pire qu'un
message qui ne part pas, parce que personne ne le voit.

Les fonctions de reconnaissance sont PURES : le banc les exerce sans réseau.
"""
from __future__ import annotations

import logging
import mimetypes
import re

logger = logging.getLogger("duret.mail.attaches")

# Les trois formes reconnaissables MÉCANIQUEMENT. Elles ne se recouvrent pas :
# 24 hexa ≠ 16 hexa, et un jeton base64url de 32 caractères contient presque
# toujours autre chose que [0-9a-f]. L'ordre d'essai lève l'ambiguïté restante
# (une clé de dépôt est essayée avant un jeton d'atelier).
RE_VISUEL = re.compile(r"^(?:/api/visuels/)?([0-9a-f]{24})$", re.I)
RE_PIECE = re.compile(r"^(?:piece:)?([0-9a-f]{16})$", re.I)
RE_DOCUMENT = re.compile(r"^(?:/api/documents/)?([A-Za-z0-9_-]{20,64})$")

MAX_PIECE = 20 * 1024 * 1024        # une pièce
MAX_TOTAL = 22 * 1024 * 1024        # le message entier, marge sous les 25 Mo
MAX_NOMBRE = 10


def _mime_du_nom(nom: str) -> str:
    """Le type MIME d'après l'extension, sans jamais lever."""
    devine, _ = mimetypes.guess_type(nom or "")
    return devine or "application/octet-stream"


def _designations(brut) -> list:
    """Ce que le modèle a écrit, ramené à une liste d'entrées exploitables.

    Il écrit tantôt une chaîne, tantôt une liste, tantôt un dict `{ref, nom}`
    (un `nom` explicite permet de renommer : « envoie-le sous Devis-Dupont.pdf »).
    Refuser l'action pour un nom de paramètre est le piège déjà payé avec `url`
    (`ouvrir_page`, 30/08) : on accepte les trois.
    """
    if not brut:
        return []
    if isinstance(brut, (str, dict)):
        brut = [brut]
    entrees = []
    for e in brut:
        if isinstance(e, dict):
            ref = (e.get("ref") or e.get("reference") or e.get("cle")
                   or e.get("jeton") or e.get("url") or e.get("fichier")
                   or e.get("nom") or "")
            entrees.append({"ref": str(ref).strip(),
                            "nom": str(e.get("nom") or "").strip()})
        elif str(e or "").strip():
            entrees.append({"ref": str(e).strip(), "nom": ""})
    return entrees


async def _du_depot(cle: str) -> tuple:
    """(octets, nom, mime) d'une image du dépôt des visuels, ou (None, …)."""
    from visuels import depot
    lu = depot.lire(cle)
    if not lu:
        return None, "", ""
    octets, mime = lu
    ext = (mime or "image/png").rpartition("/")[2] or "png"
    return octets, f"{cle}.{ext}", mime


async def _de_l_atelier(jeton: str, proprietaire: str) -> tuple:
    """(octets, nom, mime) d'un document produit ou reçu, ou (None, …).

    `chemin_fichier` vérifie la propriété : un jeton deviné par quelqu'un
    d'autre est indistinct d'un jeton absent.
    """
    import asyncio

    from bureautique import atelier
    f = atelier.fiche(jeton, proprietaire)
    chemin = atelier.chemin_fichier(jeton, proprietaire)
    if not f or not chemin:
        return None, "", ""
    entete = f.get("entete") or {}
    nom = f"{entete.get('titre') or 'document'}.{entete.get('format') or 'bin'}"
    octets = await asyncio.to_thread(lambda: open(chemin, "rb").read())
    return octets, nom, _mime_du_nom(nom)


async def _d_un_mail(ref: str, boite: str) -> tuple:
    """(octets, nom, mime) d'une pièce jointe d'un message ouvert."""
    from mail.lecture import piece_connue, telecharger_piece
    info = piece_connue(ref, boite)
    if not info:
        return None, "", ""
    octets = await telecharger_piece(boite, info)
    nom = info.get("nom") or "piece-jointe"
    return octets, nom, info.get("type") or _mime_du_nom(nom)


async def _du_nas(nom: str, user) -> tuple:
    """(octets, nom réel, mime) d'un fichier du NAS, dans le périmètre.

    Le périmètre est appliqué DANS `nas.acces.verifier()`, à chaque descente :
    composer deux gestes ne doit ouvrir aucun droit que ni l'un ni l'autre
    n'accordait.
    """
    from outils.nas import octets
    return await octets(nom)


async def resoudre(brut, user, boite: str) -> tuple:
    """(pièces prêtes, refusées). Ne lève JAMAIS.

    Une pièce prête est `{nom, mime, octets}` — exactement ce qu'attendent les
    constructeurs de `mail/expedition.py`. Une refusée est `{nom, raison}`, et
    la raison est écrite pour la personne : ce qu'elle peut faire au tour
    suivant, pas ce qui a planté.
    """
    entrees = _designations(brut)
    if not entrees:
        return [], []
    pretes, refusees = [], []
    proprietaire = str(getattr(user, "id", "") or "")
    total = 0

    for entree in entrees[:MAX_NOMBRE + 5]:
        ref, renom = entree["ref"], entree["nom"]
        etiquette = renom or ref
        if len(pretes) >= MAX_NOMBRE:
            refusees.append({"nom": etiquette,
                             "raison": f"plus de {MAX_NOMBRE} pièces dans un "
                                       "seul message"})
            continue

        octets = nom = mime = None
        try:
            m = RE_VISUEL.match(ref)
            if m:
                octets, nom, mime = await _du_depot(m.group(1).lower())
            if octets is None:
                m = RE_PIECE.match(ref)
                if m:
                    octets, nom, mime = await _d_un_mail(m.group(1).lower(), boite)
            if octets is None:
                m = RE_DOCUMENT.match(ref)
                if m:
                    octets, nom, mime = await _de_l_atelier(m.group(1), proprietaire)
            if octets is None:
                # Dernier recours : un NOM ou un CHEMIN du NAS. Volontairement
                # en dernier — une référence technique doit gagner sur un nom,
                # sinon « ab…24hexa » partirait chercher un fichier nommé ainsi.
                octets, nom, mime = await _du_nas(ref, user)
        except Exception as e:  # noqa: BLE001 — un refus est une donnée, pas un plantage
            logger.info("Pièce « %s » non résolue : %s", etiquette[:60], e)
            refusees.append({"nom": etiquette, "raison": str(e)[:200]})
            continue

        if not octets:
            refusees.append({
                "nom": etiquette,
                "raison": "introuvable — un document produit ne vit que 24 h ; "
                          "reproduis-le, ou ouvre d'abord la pièce à joindre"})
            continue
        if len(octets) > MAX_PIECE:
            refusees.append({
                "nom": renom or nom,
                "raison": f"{len(octets) // (1024 * 1024)} Mo : au-delà de "
                          f"{MAX_PIECE // (1024 * 1024)} Mo un mail ne passe "
                          "pas — dépose le fichier sur le NAS et envoie le chemin"})
            continue
        total += len(octets)
        if total > MAX_TOTAL:
            refusees.append({
                "nom": renom or nom,
                "raison": f"le message dépasserait {MAX_TOTAL // (1024 * 1024)} Mo "
                          "au total — envoie les pièces en deux messages"})
            continue
        final = renom or nom
        pretes.append({"nom": final, "mime": mime or _mime_du_nom(final),
                       "octets": octets})

    logger.info("Pièces résolues : %d prêtes, %d refusées (%d o)",
                len(pretes), len(refusees), total)
    return pretes, refusees
