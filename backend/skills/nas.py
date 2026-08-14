"""
Skills natifs : consulter et alimenter le NAS Synology.

LIRE et AGIR sont séparés, et déclarés différemment :
  * `nas_lister`, `nas_lire`, `nas_chercher` sont en LECTURE ;
  * `nas_deposer` ÉCRIT sur le serveur de l'entreprise. Déclaré à effet EXTERNE,
    il passe donc par la validation humaine avant de partir.

CE QUI N'EST VOLONTAIREMENT PAS OFFERT : supprimer, déplacer, renommer,
écraser. Sur un NAS d'entreprise, ces gestes sont irréversibles et personne ne
s'en aperçoit avant d'avoir besoin du fichier. Les ajouter serait une décision
d'exploitation, pas une commodité technique — elle appartient aux dirigeants,
pas à l'assistant.

DEUX BORNES, ET ELLES NE DISENT PAS LA MÊME CHOSE :
  * le CONFINEMENT borne CE QUI est visible — hors des dossiers autorisés, la
    demande est refusée avant même d'atteindre le NAS ;
  * le contrôle de RÔLE borne QUI peut le voir. Sans lui, tout utilisateur, y
    compris un profil terrain, lirait l'intégralité des dossiers ouverts, alors
    que les mails sont cloisonnés par personne et les documents par rôle.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("duret.skills.nas")


# Causes reelles derriere les exceptions reseau, en clair. Un nom de classe ne
# dit rien a l'utilisateur ; ce qu'il faut verifier, si.
_CAUSES = {
    "ConnectError": "le NAS n'est pas joignable depuis le serveur (adresse, port, "
                    "pare-feu, ou relais QuickConnect indisponible)",
    "ConnectTimeout": "le NAS n'a pas repondu a temps (relais QuickConnect lent, "
                      "ou adresse injoignable)",
    "ReadTimeout": "le NAS a accepte la connexion mais n'a pas repondu a temps",
    "SSLError": "le certificat du NAS a ete refuse (mettre SYNOLOGY_VERIFY_TLS=false)",
    "JSONDecodeError": "la reponse n'est pas du JSON : l'adresse ne pointe pas sur "
                       "l'API DSM (page HTML QuickConnect ?)",
    "NotImplementedError": "Synology n'est pas configure (identifiants manquants)",
}


def _echec(message: str):
    """Un échec doit se signaler comme un échec.

    Ces fonctions rendaient `{"message": "..."}` — un dictionnaire ordinaire,
    donc une RÉUSSITE partout ailleurs : `ok` valait True, l'action s'affichait
    comme aboutie, et la passe suivante lisait « nas_deposer : réussie ». Le
    modèle croyait le fichier posé sur le serveur alors qu'il n'était pas parti,
    et l'annonçait à l'utilisateur.

    Un refus de rôle, un NAS injoignable, un document introuvable : ce sont des
    échecs. Ils doivent porter ce nom, sans quoi rien en amont ne peut réagir.
    """
    from skills.erreurs import SkillError
    raise SkillError(message)


def _detail(quoi: str, e: Exception) -> str:
    """Message exploitable, meme quand l'exception n'en porte aucun.

    Beaucoup d'exceptions reseau ont un str() VIDE : le message se terminait
    alors par « : » et n'apprenait rien, ni a l'utilisateur ni au journal. Le
    TYPE est toujours renseigne, et c'est souvent lui qui designe la cause.
    """
    nom = type(e).__name__
    # exc_info : la trace part au journal, pas a l'ecran. L'utilisateur n'a que
    # faire d'une pile d'appels, l'administrateur en a besoin.
    logger.warning("NAS — %s : %s (%s)", quoi, nom, e or "sans message", exc_info=True)
    cause = _CAUSES.get(nom)
    texte = str(e).strip()
    return (f"{quoi} ({nom})"
            + (f" : {texte}" if texte else "")
            + (f". Probablement : {cause}." if cause else "."))


async def nas_lister(data: dict, user) -> dict:
    """Contenu d'un dossier du NAS."""
    from nas.acces import lister, verifier_role, NasRefuse, dossiers_autorises
    try:
        verifier_role(user)
    except NasRefuse as e:
        _echec(str(e))
    chemin = (data.get("chemin") or "").strip()
    if not chemin:
        racines = dossiers_autorises()
        return {"dossiers_autorises": racines,
                "message": ("Voici les dossiers ouverts. Rappelle `nas_lister` avec "
                            "l'un d'eux." if racines else
                            "Aucun dossier du NAS n'est ouvert à l'assistant. Un "
                            "administrateur doit renseigner SYNOLOGY_FOLDERS avec les "
                            "partages precis a ouvrir (ex. /chantiers,/devis). "
                            "« / » n'est pas accepte : il exposerait tout le serveur, "
                            "dossiers personnels et sauvegardes compris. "
                            "Dis-le tel quel, ne propose pas de nom de dossier au "
                            "hasard : tu ne sais pas lesquels existent.")}
    try:
        return await lister(chemin)
    except NasRefuse as e:
        _echec(str(e))
    except Exception as e:  # noqa: BLE001 - un NAS injoignable n'est pas une panne du chat
        _echec(_detail("Le NAS n'a pas pu être consulté", e))


async def nas_lire(data: dict, user) -> dict:
    """Contenu textuel d'un fichier du NAS."""
    from nas.acces import lire, verifier_role, NasRefuse
    try:
        verifier_role(user)
    except NasRefuse as e:
        _echec(str(e))
    chemin = (data.get("chemin") or "").strip()
    if not chemin:
        _echec("Donne le chemin complet du fichier à lire.")
    try:
        return await lire(chemin)
    except NasRefuse as e:
        _echec(str(e))
    except Exception as e:  # noqa: BLE001
        _echec(_detail("Le fichier n'a pas pu être lu", e))


async def nas_chercher(data: dict, user) -> dict:
    """Recherche un fichier par son nom, dans le périmètre autorisé."""
    from nas.acces import chercher, verifier_role, NasRefuse
    try:
        verifier_role(user)
    except NasRefuse as e:
        _echec(str(e))
    try:
        return await chercher(data.get("motif") or "", data.get("dossier"))
    except NasRefuse as e:
        _echec(str(e))
    except Exception as e:  # noqa: BLE001
        _echec(_detail("La recherche a échoué", e))


async def nas_deposer(data: dict, user) -> dict:
    """Dépose sur le NAS un document produit par l'assistant. ÉCRITURE."""
    from nas.acces import deposer, verifier_role, NasRefuse
    try:
        verifier_role(user)
    except NasRefuse as e:
        _echec(str(e))

    dossier = (data.get("dossier") or "").strip()
    jeton = (data.get("document_id") or "").strip()
    if not dossier or not jeton:
        _echec("Il faut le dossier du NAS et le `document_id` d'un document "
               "déjà terminé (`terminer_document`).")

    # On ne dépose QUE des documents produits ici, et seulement ceux de la
    # personne : téléverser un chemin arbitraire du serveur ferait de ce skill
    # un moyen d'exfiltrer des fichiers internes vers un partage réseau.
    from bureautique.atelier import chemin_fichier, fiche
    proprio = str(getattr(user, "id", "") or "")
    chemin = chemin_fichier(jeton, proprio)
    if not chemin:
        _echec("Document inconnu, pas encore terminé, ou appartenant à "
               "quelqu'un d'autre. Reprends le `document_id` EXACT rendu par "
               "`terminer_document`.")

    f = fiche(jeton, proprio) or {}
    entete = f.get("entete") or {}
    nom = data.get("nom") or f"{entete.get('titre', 'document')}.{entete.get('format', 'docx')}"

    try:
        with open(chemin, "rb") as fichier:
            contenu = fichier.read()
        return await deposer(dossier, nom, contenu)
    except NasRefuse as e:
        _echec(str(e))
    except Exception as e:  # noqa: BLE001
        _echec(_detail("Le dépôt a échoué", e))


# ── Déclarations : tout ce que le système doit savoir, ICI ───────────
# Ces quatre gestes élémentaires restent disponibles pour ce que la
# bibliothèque composée (skills/outils.py) ne couvre pas. Leurs descriptions
# renvoient vers les fonctions composées : ce sont elles, la voie normale.
from skills.registre import Declaration

SKILLS = {
    "nas_lister": Declaration(
        fonction=nas_lister,
        description=("LISTE le detail d'un dossier du serveur. Sans `chemin`, "
                     "les dossiers ouverts a l'assistant. Prefere `nas_apercu` "
                     "pour compter"),
        optionnels=["chemin"],
        effet="lecture",
        libelle="je liste un dossier du serveur"),
    "nas_lire": Declaration(
        fonction=nas_lire,
        description=("LIT un fichier du serveur par son CHEMIN exact. Prefere "
                     "`nas_ouvrir`, qui trouve le chemin tout seul"),
        requis=["chemin"],
        effet="lecture",
        libelle="je lis un fichier du serveur"),
    "nas_chercher": Declaration(
        fonction=nas_chercher,
        description="CHERCHE un fichier par son nom sur le serveur, sans le lire",
        requis=["motif"], optionnels=["dossier"],
        effet="lecture",
        libelle="je cherche un fichier sur le serveur"),
    "nas_deposer": Declaration(
        fonction=nas_deposer,
        description=("DEPOSE sur le serveur un fichier deja produit. Ecrit sur "
                     "le serveur : validation humaine. N'ecrase jamais. Aucune "
                     "suppression ni renommage n'est possible : ne le promets pas"),
        requis=["dossier", "document_id"], optionnels=["nom"],
        # Écrire sur le serveur de l'entreprise sort du périmètre de
        # l'application : effet EXTERNE, validation humaine obligatoire.
        effet="externe",
        libelle="je dépose le fichier sur le serveur"),
}
