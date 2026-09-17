"""
La SOURCE de la carte du classement chez ce client : le serveur de fichiers
Synology (NAS).

Module propre au client (déclaré dans la dérive) : le socle `classement.carte`
ne sait pas d'où viennent les entrées. Ici, elles viennent du CATALOGUE du NAS
(`nas.acces`, balayage de fond depuis le 08/09 midi) : chaque fichier est une
entrée avec sa taille, et le socle en déduit les comptes par dossier.

Le niveau d'accès est celui du NAS tout entier (`SYNOLOGY_ACCESS_LEVEL`) :
c'est le même droit qui ouvre le serveur dans le chat et range ses fichiers
à l'ingestion — la carte ne dit rien de plus que ce que ce droit permet de
lister.
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("symbiose.classement")

NOM_STOCKAGE = "serveur de fichiers (NAS)"
GESTE_LISTER = "nas_lister"
GESTE_CHERCHER = "nas_chercher"
# Le connecteur de synchronisation de ce stockage (clé de
# `routers.ingestion.CONNECTEURS`). La campagne « Enrichir les documents »
# le lance d'abord : elle ouvre chaque fichier de le NAS AVANT d'en tirer le
# savoir, au lieu de ne relire que ce qu'une synchronisation passée aurait
# laissé en mémoire (11/09).
CONNECTEUR = "synology"
ATTENTE_CATALOGUE_S = 900


async def entrees_du_classement() -> tuple[list, bool]:
    """Toutes les entrées (dossiers et fichiers) et si le relevé est complet.

    Le catalogue se construit au démarrage en tâche de fond : on l'attend
    plutôt que de lancer un second balayage du même serveur.
    """
    from nas import acces

    cat = acces.catalogue_pret()
    attendu = 0
    while (cat is None or acces._CATALOGUE.get("en_cours")) and attendu < ATTENTE_CATALOGUE_S:
        await asyncio.sleep(10)
        attendu += 10
        if not acces._CATALOGUE.get("en_cours") and acces._CATALOGUE.get("etat") in ("pret", "partiel"):
            cat = acces._CATALOGUE["entrees"]
            break
    if cat is None:
        cat = (await acces.construire_catalogue()).get("entrees") or []
    entrees = []
    for e in cat:
        if not e.get("chemin"):
            continue
        entrees.append({"chemin": e["chemin"], "dossier": bool(e.get("dossier")),
                        "octets": e.get("octets") or e.get("taille") or 0})
    return entrees, bool(acces._CATALOGUE.get("complet"))


def niveau_de(chemin: str) -> str:
    """Le niveau d'accès du morceau qui décrit ce dossier : celui de SON dossier
    (règles de Paramètres, 13/09), sinon celui du serveur."""
    try:
        from nas.niveaux import niveau
        return niveau(chemin)
    except Exception:  # noqa: BLE001
        from config import settings
        return (getattr(settings, "synology_access_level", None) or "all").strip() or "all"


def signature_droits(role) -> str:
    """Ce qui change la vue d'un rôle : ses niveaux et les règles en vigueur."""
    from nas import niveaux
    from security.acces import niveaux_visibles
    return f"{sorted(niveaux_visibles(role))}|{niveaux.regles()}"


def visible(chemin: str, role) -> bool:
    """Ce rôle voit-il ce dossier ? La carte montrée à une personne ne nomme
    que ce qu'elle a le droit d'ouvrir."""
    from nas.niveaux import visible_pour
    return visible_pour(chemin, role)

# ── L'inventaire (08/09) : lister un dossier, lire un fichier. Le périmètre du
# serveur s'applique en dessous (`verifier`), le rôle est contrôlé ici.

async def fichiers_du_dossier(dossier: str, user) -> tuple[str, list]:
    """(chemin réel, fichiers directs du dossier) — chaque fichier porte `ref`
    (son chemin), `nom`, `octets`."""
    from nas.acces import verifier_role
    from outils import nas

    verifier_role(user)
    r = await nas.lister(dossier)
    entrees = [e for e in (r.get("entrees") or []) if not e.get("dossier")]
    return str(r.get("chemin") or dossier), [
        {"nom": e.get("nom") or "?", "ref": e.get("chemin"), "octets": int(e.get("octets") or 0), "type": ""}
        for e in entrees if e.get("chemin")]


# LES CORPS D'ÉTAT DE LA MAISON (donnée du client). Quand une demande ne nomme
# aucun lot (« fais les métrés du projet X »), le dossier d'un appel d'offres en
# porte dix-sept : on retient ceux dont l'intitulé parle du métier de
# l'entreprise, et on le DIT — plutôt que de charger les dix-sept.
METIERS_DE_LA_MAISON = ("carrelage", "faience", "sols souples", "sol souple", "revetement de sol",
                        "revetements de sols", "chape", "parquet", "moquette", "resine", "linoleum", "pvc")


async def arbre_du_dossier(dossier: str, user, profondeur: int = 6, plafond: int = 2000) -> tuple[str, list, bool]:
    """(chemin réel, fichiers du dossier ET de ses sous-dossiers, coupé ?).

    17/09 : « fais les métrés à partir du dossier souche … » ne lisait QUE les
    pièces jointes au chat — le dossier du serveur n'était jamais ouvert. Le
    nom suffit (même résolution que `nas_lister`), les droits du rôle
    s'appliquent. UNE connexion pour tout l'arbre et un listage COMPLET de
    chaque dossier : le DCE Domofrance porte 250 fichiers sur quatre niveaux,
    dont 90 dans un seul sous-dossier. Chaque fichier garde son sous-dossier et
    sa date : c'est ce qui permet de choisir les pièces utiles et, entre deux
    fichiers du même nom, le plus récent."""
    from nas.acces import _lister_ouvert, connexion, verifier_role
    from outils.nas import _resoudre

    import asyncio

    verifier_role(user)
    fichiers, coupe = [], False
    async with connexion() as (client, base, sid):
        reel = await _resoudre(client, base, sid, dossier)
        # Mesuré sur le serveur : 52 dossiers listés l'un après l'autre = 107 s.
        # Ceux d'un MÊME niveau se listent de front (six à la fois).
        porte = asyncio.Semaphore(6)

        async def un(chemin):
            async with porte:
                try:
                    return await _lister_ouvert(client, base, sid, chemin, tout=True)
                except Exception:  # noqa: BLE001 — un sous-dossier fermé n'arrête pas les autres
                    return None

        niveau, a_voir = 0, [(reel, "")]
        while a_voir:
            contenus = await asyncio.gather(*(un(c) for c, _ in a_voir))
            if not niveau and contenus[0] is None:
                raise ValueError("Le dossier « %s » ne s'ouvre pas sur le serveur." % dossier)
            suivants = []
            for (chemin, relatif), contenu in zip(a_voir, contenus):
                for e in ((contenu or {}).get("entrees") or []):
                    if not e.get("chemin"):
                        continue
                    nom = str(e.get("nom") or "")
                    if e.get("dossier"):
                        if niveau < profondeur and not nom.startswith(("#", "@", ".")):
                            suivants.append((e["chemin"], (relatif + "/" + nom).strip("/")))
                        continue
                    if len(fichiers) >= plafond:
                        coupe = True
                        continue
                    fichiers.append({"nom": nom or "?", "ref": e["chemin"], "octets": int(e.get("octets") or 0),
                                     "dossier": relatif, "modifie": e.get("modifie") or 0})
            niveau, a_voir = niveau + 1, suivants
    return str(reel), fichiers, coupe


async def lire_fichier(ref, user) -> dict:
    """{texte, methode} d'un fichier du serveur — lu PAR TYPE comme une pièce
    jointe (`mail/pieces.lire_sans_deposer`, 09/09) : PDF avec OCR si scanné,
    Word, Excel, DXF, DWG par sa vignette, et les IMAGES décrites par la
    vision (une photo de chantier ne rendait aucun texte : « sans texte
    lisible », l'inventaire ne disait rien). Le binaire vient de
    `nas.octets` (périmètre vérifié) ; rien n'est déposé à l'atelier
    (quarante cartes seraient du bruit). Un refus du serveur lève une raison
    lisible, rendue telle quelle."""
    from mail.pieces import CONSIGNE_FICHIER, lire_sans_deposer
    from outils import nas

    brut, nom, mime = await nas.octets(str(ref))
    return await lire_sans_deposer(nom, mime, brut, consigne_vision=CONSIGNE_FICHIER)
