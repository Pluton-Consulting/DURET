"""
Outil « serveur de fichiers » — les cas d'usage réunis, un appel chacun.

Chaque fonction ouvre UNE session DSM et enchaîne tout ce qu'il faut dedans.
C'est là que se joue la vitesse : mesuré, une seule liste de dossier prend six
secondes, dont l'essentiel en résolution d'adresse et connexion. Enchaîner
« cherche puis lis » avec les gestes élémentaires payait ce prix deux fois, plus
un aller-retour de modèle entre les deux — soit une quinzaine de secondes pour
un fichier dont la lecture prend moins d'une seconde.

Le confinement reste entier : toutes ces fonctions passent par `verifier()`, qui
refuse tout chemin hors des dossiers ouverts. Composer des gestes ne compose pas
des droits.
"""
from __future__ import annotations

import logging
import posixpath
from typing import Optional

logger = logging.getLogger("duret.outils.nas")

MAX_PROFONDEUR = 3
MAX_DOSSIERS_PARCOURUS = 40
MAX_LOT = 5


async def apercu(chemin: Optional[str] = None) -> dict:
    """Ce que contient un dossier, compté et classé — sans lister tout le détail.

    Répond en UN appel à « combien de dossiers dans /home/Drive », « qu'est-ce
    qu'il y a là-dedans », « c'est gros ? ». Avec les gestes élémentaires il
    fallait lister puis faire compter le modèle, qui se trompait d'autant plus
    que la liste était longue — compter n'est pas ce qu'un modèle fait de mieux.
    """
    from nas.acces import connexion, _lister_ouvert, dossiers_autorises

    async with connexion() as (client, base, sid):
        if chemin:
            brut = await _lister_ouvert(client, base, sid, chemin)
            racines = [brut]
        else:
            # Sans chemin : l'inventaire des racines ouvertes, chacune résumée.
            racines = [await _lister_ouvert(client, base, sid, d)
                       for d in dossiers_autorises()]

    resume = []
    for r in racines:
        entrees = r.get("entrees") or []
        dossiers = [e for e in entrees if e.get("dossier")]
        fichiers = [e for e in entrees if not e.get("dossier")]
        octets = sum(int(e.get("octets") or 0) for e in fichiers)
        # Les extensions les plus présentes : ça dit la NATURE du dossier
        # (plans, devis, photos) mieux qu'une liste de noms tronquée.
        types: dict[str, int] = {}
        for f in fichiers:
            ext = posixpath.splitext(f.get("nom") or "")[1].lower().lstrip(".")
            if ext:
                types[ext] = types.get(ext, 0) + 1
        resume.append({
            "chemin": r.get("chemin"),
            "dossiers": len(dossiers),
            "fichiers": len(fichiers),
            "octets_total": octets,
            "types_de_fichiers": dict(sorted(types.items(), key=lambda kv: -kv[1])[:8]),
            "noms_des_dossiers": [d.get("nom") for d in dossiers][:40],
            "tronque": bool(r.get("tronque")),
        })

    total_dossiers = sum(r["dossiers"] for r in resume)
    total_fichiers = sum(r["fichiers"] for r in resume)
    return {"emplacements": resume,
            "total_dossiers": total_dossiers, "total_fichiers": total_fichiers,
            "note": (f"{total_dossiers} dossier(s) et {total_fichiers} fichier(s). "
                     "Les nombres ci-dessus sont comptés, pas estimés : "
                     "reprends-les tels quels.")}


async def arborescence(chemin: str, profondeur: int = 2) -> dict:
    """L'arbre d'un dossier sur plusieurs niveaux, en UN appel.

    Descendre de trois niveaux demandait trois listages, donc trois
    allers-retours de modèle et trois connexions. Bornée en profondeur ET en
    nombre de dossiers parcourus : un NAS d'entreprise peut contenir des
    dizaines de milliers de dossiers, et une exploration sans limite ne
    reviendrait jamais.
    """
    from nas.acces import connexion, _lister_ouvert

    profondeur = max(1, min(int(profondeur or 2), MAX_PROFONDEUR))
    vus = 0
    arbre: dict = {"chemin": chemin, "enfants": []}

    async with connexion() as (client, base, sid):
        file_attente = [(chemin, arbre, 0)]
        while file_attente and vus < MAX_DOSSIERS_PARCOURUS:
            courant, noeud, niveau = file_attente.pop(0)
            vus += 1
            try:
                brut = await _lister_ouvert(client, base, sid, courant)
            except Exception as e:  # noqa: BLE001 - un dossier illisible n'arrête pas l'arbre
                noeud["erreur"] = str(e)[:120]
                continue
            for e in brut.get("entrees") or []:
                enfant = {"nom": e.get("nom"), "chemin": e.get("chemin"),
                          "dossier": bool(e.get("dossier")), "octets": e.get("octets")}
                noeud["enfants"].append(enfant)
                if enfant["dossier"] and niveau + 1 < profondeur:
                    enfant["enfants"] = []
                    file_attente.append((enfant["chemin"], enfant, niveau + 1))

    return {"arbre": arbre, "profondeur": profondeur, "dossiers_parcourus": vus,
            "complet": not file_attente,
            "note": ("Arbre partiel : trop de dossiers, précise un sous-dossier."
                     if file_attente else
                     "Reprends le champ `chemin` d'une entrée pour l'ouvrir.")}


async def ouvrir(nom_ou_chemin: str) -> dict:
    """Lit un fichier depuis son NOM, sans en connaître le chemin.

    C'est la fonction qui remplace le plus d'allers-retours : jusqu'ici il
    fallait `nas_chercher` puis `nas_lire`, et c'est exactement là que le chemin
    se perdait — reconstruit à partir du seul nom, il désignait un fichier qui
    n'existe pas. Ici le chemin trouvé est réutilisé tel quel, sans passer par
    le modèle : l'erreur n'est plus possible.

    Un chemin complet est accepté directement : on ne cherche que s'il le faut.
    """
    from nas.acces import connexion, _lire_ouvert, _chercher_ouvert, NasRefuse

    demande = (nom_ou_chemin or "").strip()
    if not demande:
        raise NasRefuse("Donne le nom ou le chemin du fichier à ouvrir.")

    async with connexion() as (client, base, sid):
        # Un chemin s'ouvre directement. On le tente d'abord : c'est le cas le
        # plus fréquent quand la fonction suit un `apercu` ou une `arborescence`.
        if demande.startswith("/"):
            try:
                lu = await _lire_ouvert(client, base, sid, demande)
                if lu.get("type"):
                    return {**lu, "trouve_par": "chemin"}
            except NasRefuse:
                raise            # hors périmètre : ne pas contourner par la recherche
            except Exception:
                pass             # inexistant : on retombe sur la recherche

        motif = posixpath.basename(demande) or demande
        trouve = await _chercher_ouvert(client, base, sid, motif)
        fichiers = [r for r in (trouve.get("resultats") or []) if not r.get("dossier")]
        if not fichiers:
            return {"recherche": motif, "message":
                    "Aucun fichier de ce nom sur le serveur. Vérifie l'orthographe, "
                    "ou donne le dossier où chercher."}
        # Plusieurs correspondances : on lit la première ET on annonce les
        # autres. Rendre une liste sans contenu obligerait à un aller-retour de
        # plus pour choisir, ce que cette fonction existe précisément pour éviter.
        premier = fichiers[0]
        lu = await _lire_ouvert(client, base, sid, premier["chemin"])

    autres = [f["chemin"] for f in fichiers[1:6]]
    return {**lu, "trouve_par": "nom", "recherche": motif,
            "autres_correspondances": autres,
            "note": (f"{len(fichiers)} fichiers portent ce nom ; celui-ci est le "
                     "premier. Les autres sont listés."
                     if autres else "")}


async def lire_lot(motif: str, dossier: Optional[str] = None,
                   limite: int = MAX_LOT) -> dict:
    """Lit plusieurs fichiers d'un coup — « tous les CCTP du chantier 2031 ».

    Sans elle, lire cinq fichiers coûtait dix allers-retours. Bornée à cinq :
    au-delà, le volume de texte dépasse ce qu'un tour de conversation peut
    porter, et la réponse serait tronquée au milieu sans que rien ne le dise.
    """
    from nas.acces import connexion, _lire_ouvert, _chercher_ouvert, NasRefuse

    limite = max(1, min(int(limite or MAX_LOT), MAX_LOT))
    async with connexion() as (client, base, sid):
        trouve = await _chercher_ouvert(client, base, sid, motif, dossier)
        fichiers = [r for r in (trouve.get("resultats") or []) if not r.get("dossier")]
        if not fichiers:
            return {"motif": motif, "nombre": 0,
                    "message": "Aucun fichier ne correspond."}

        lus, echecs = [], []
        for f in fichiers[:limite]:
            try:
                lus.append(await _lire_ouvert(client, base, sid, f["chemin"]))
            except NasRefuse as e:
                echecs.append({"chemin": f["chemin"], "raison": str(e)})
            except Exception as e:  # noqa: BLE001 - un fichier illisible n'annule pas le lot
                echecs.append({"chemin": f["chemin"], "raison": str(e)[:120]})

    return {"motif": motif, "correspondances": len(fichiers), "lus": lus,
            "echecs": echecs,
            "note": (f"{len(fichiers)} fichier(s) trouvé(s), {len(lus)} lu(s)"
                     + (f", {len(echecs)} en échec" if echecs else "")
                     + (f". Limite de {limite} atteinte : précise le motif."
                        if len(fichiers) > limite else "."))}


async def deposer_document(document_id: str, dossier: str, proprietaire: str,
                           nom: Optional[str] = None) -> dict:
    """Finalise un document en cours et le dépose sur le serveur, en un geste.

    Deux actions distinctes jusqu'ici — `terminer_document` puis `nas_deposer` —
    donc deux allers-retours, et l'identifiant du document à reporter entre les
    deux. C'est précisément là que la chaîne cassait : sans l'identifiant sous
    les yeux, le modèle en inventait un, l'ajout était refusé, et il rouvrait un
    document en boucle.

    `proprietaire` vient du skill, qui seul connaît l'utilisateur : un document
    n'appartient qu'à celui qui l'a ouvert, et cette règle ne se contourne pas
    parce qu'on a composé deux gestes.

    EFFET EXTERNE : le dépôt écrit sur le serveur de l'entreprise. Cette
    fonction est donc soumise à validation humaine, comme `nas_deposer`.
    """
    from bureautique.atelier import terminer, chemin_fichier
    from nas.acces import deposer

    fiche = terminer(document_id, proprietaire)      # lève si inconnu ou vide
    chemin = chemin_fichier(document_id, proprietaire)
    if not chemin:
        raise FileNotFoundError("Le document a été finalisé mais son fichier est "
                                "introuvable. Recommence-le.")

    entete = fiche["entete"]
    final = nom or f"{entete['titre']}.{entete['format']}"
    with open(chemin, "rb") as f:
        contenu = f.read()

    depot = await deposer(dossier, final, contenu)
    return {"document_id": document_id, "titre": entete["titre"],
            "format": entete["format"], "octets": fiche["octets"],
            "elements": fiche["elements"], **depot,
            "note": "Document finalisé ET déposé sur le serveur."}
