"""
Accès interactif au NAS Synology : lire et agir à la demande.

CE QUI EXISTAIT DÉJÀ. `ingestion/connectors/synology.py` synchronise le NAS en
masse vers la mémoire d'entreprise, en lecture seule. C'est un aspirateur : il
tourne à la demande d'un administrateur et ingère tout.

CE QUE CE MODULE AJOUTE. L'assistant doit pouvoir répondre à « qu'y a-t-il dans
le dossier chantier 2031 » ou « ouvre-moi le CCTP » sans qu'on ait resynchronisé
la veille, et déposer un fichier qu'il vient de produire. On réutilise donc la
résolution d'adresse, l'authentification et les appels DSM déjà écrits et
éprouvés, plutôt que d'en faire une seconde version qui divergerait.

QUICKCONNECT N'EST PAS UNE API. C'est le service de traversée de NAT de
Synology : il RÉSOUT une adresse joignable, rien de plus. L'API réelle est DSM
FileStation. Le relais QuickConnect est lent et coupe sur un gros volume :
l'adresse directe (le NAS sur le VPN Headscale déjà en place) reste la bonne
voie, QuickConnect n'étant qu'un repli.

LE GARDE-FOU CENTRAL : LE CONFINEMENT. Un NAS d'entreprise contient les dossiers
personnels, les sauvegardes, parfois la comptabilité. Sans confinement, une
demande anodine — « liste la racine » — donnerait à l'assistant, et donc à
n'importe quel utilisateur, une vue de tout le disque. Tout chemin est donc
vérifié comme étant SOUS un des dossiers autorisés, après normalisation :
`..`, doubles séparateurs et chemins relatifs sont neutralisés avant
comparaison, sinon `chantiers/../../homes` sortirait du périmètre.

Fail-closed : aucun dossier configuré, aucun accès.
"""
from __future__ import annotations

import logging
import posixpath
from typing import Optional

logger = logging.getLogger("duret.nas.acces")

MAX_ENTREES = 200
MAX_OCTETS_LECTURE = 15 * 1024 * 1024
MAX_CARACTERES = 40_000


class NasRefuse(PermissionError):
    """Chemin hors périmètre, ou NAS non configuré."""


def dossiers_autorises() -> list[str]:
    """Racines ouvertes à l'assistant. Vide = rien n'est accessible.

    « / » est ÉCARTÉ ici comme il l'est dans `verifier`. Les deux fonctions
    doivent appliquer la même règle : quand elles divergeaient, l'assistant
    s'entendait annoncer « le dossier racine vous est accessible » puis se voyait
    refuser ce même dossier au moment de l'ouvrir. Deux règles contradictoires
    sur la même donnée valent moins que pas de règle du tout — celui qui les lit
    conclut que l'outil est cassé, et il a raison.
    """
    from config import settings
    brut = (settings.synology_folders or "").strip()
    racines = [normaliser(d) for d in brut.split(",") if d.strip()]
    if "/" in racines:
        logger.warning("SYNOLOGY_FOLDERS contient « / » : ignoré (exposerait tout "
                       "le NAS). Indiquez les partages précis à ouvrir.")
    return [r for r in racines if r != "/"]


def normaliser(chemin: str) -> str:
    """Chemin absolu POSIX, sans `..` ni segment vide."""
    c = (chemin or "").strip().replace("\\", "/")
    if not c.startswith("/"):
        c = "/" + c
    # `normpath` résout `..` et `.` : c'est LUI qui empêche de remonter.
    return posixpath.normpath(c).rstrip("/") or "/"


def verifier_role(user) -> None:
    """Ce profil a-t-il le droit de consulter le NAS ?

    Le confinement borne CE QUI est visible ; il ne dit rien de QUI peut le
    voir. Sans ce contrôle, tout utilisateur de l'application — y compris un
    profil terrain — lirait l'intégralité des dossiers ouverts, alors que les
    mails sont cloisonnés par personne et les documents par rôle. Le NAS ne peut
    pas être la seule porte sans serrure.

    Le niveau exigé est `synology_access_level`, celui-là même sous lequel la
    synchronisation range les fichiers ingérés : lire un document dans le chat
    et le lire sur le NAS demandent ainsi le même droit, ce qui évite qu'un
    chemin contourne l'autre.
    """
    from config import settings
    from security.acces import niveaux_visibles

    exige = (settings.synology_access_level or "all").strip()
    if exige not in niveaux_visibles(getattr(user, "role", "")):
        raise NasRefuse(
            "Votre profil n'a pas accès au serveur de fichiers de l'entreprise.")


def verifier(chemin: str) -> str:
    """Rend le chemin normalisé s'il est dans le périmètre. Lève sinon.

    Le message ne dit PAS ce qui existe ailleurs : décrire l'arborescence
    interdite à celui qui vient de s'y heurter la lui apprendrait.
    """
    # `dossiers_autorises` a déjà écarté « / » : le refus est donc porté par le
    # cas « aucune racine », et il doit l'expliquer. Un second contrôle sur « / »
    # ici serait inatteignable — du code mort qui laisse croire à une protection
    # supplémentaire alors qu'elle vit ailleurs.
    racines = dossiers_autorises()
    if not racines:
        raise NasRefuse(
            "Aucun dossier NAS n'est ouvert à l'assistant. Un administrateur doit "
            "renseigner SYNOLOGY_FOLDERS avec les partages précis à ouvrir "
            "(ex. /chantiers,/devis). « / » n'est pas accepté : il exposerait tout "
            "le serveur, dossiers personnels et sauvegardes compris.")
    vise = normaliser(chemin)
    for racine in racines:
        if vise == racine or vise.startswith(racine + "/"):
            return vise
    raise NasRefuse(
        f"« {chemin} » est hors du périmètre autorisé. Dossiers ouverts : "
        + ", ".join(racines))


async def _session(client):
    """Adresse + session DSM. Réutilise le connecteur existant.

    Une adresse gardée en cache peut devenir morte : bail DHCP renouvelé, relais
    Synology déplacé. On l'oublie alors, pour que l'appel suivant reparte d'une
    résolution fraîche au lieu de s'obstiner pendant toute la durée du cache.
    """
    import httpx

    from ingestion.connectors import synology as c
    base = await c._base_url(client)
    try:
        sid = await c._login(client, base)
    except httpx.HTTPError:
        # Panne de TRANSPORT : l'adresse est en cause, pas les identifiants.
        # Un refus DSM (mot de passe, droits) ne passe pas par ici et ne doit
        # surtout pas invalider une adresse parfaitement bonne.
        c.oublier_adresse()
        raise
    return base, sid


async def lister(chemin: str) -> dict:
    """Contenu d'un dossier : sous-dossiers et fichiers, avec tailles."""
    import httpx
    from config import settings
    from ingestion.connectors import synology as c

    vise = verifier(chemin)
    async with httpx.AsyncClient(verify=settings.synology_verify_tls) as client:
        base, sid = await _session(client)
        try:
            data = await c._appel(client, base, "SYNO.FileStation.List", "list", 2,
                                  sid=sid, folder_path=vise, limit=MAX_ENTREES,
                                  additional='["size","time"]')
        finally:
            await c._logout(client, base, sid)

    entrees = []
    for f in (data.get("files") or [])[:MAX_ENTREES]:
        add = f.get("additional") or {}
        entrees.append({
            "nom": f.get("name"), "chemin": f.get("path"),
            "dossier": bool(f.get("isdir")),
            "octets": (add.get("size") if not f.get("isdir") else None),
        })
    total = int(data.get("total") or len(entrees))
    return {
        "chemin": vise, "entrees": entrees, "total": total,
        "tronque": total > len(entrees),
        # Le modèle doit REPRENDRE le `chemin` de chaque entrée, pas le
        # reconstruire. Constaté : après avoir listé /home et vu le dossier
        # « Drive », il a demandé « /Drive » — qui n'existe pas — au lieu de
        # « /home/Drive » qu'il avait sous les yeux. Un chemin recompose à
        # partir du seul nom perd son dossier parent.
        "note": (f"{len(entrees)} entrée(s) sur {total}. Pour ouvrir l'une d'elles, "
                 "réutilise EXACTEMENT son champ `chemin` : ne le reconstruis pas à "
                 "partir du nom, tu perdrais le dossier parent."
                 + (" Liste tronquée : affine avec un sous-dossier."
                    if total > len(entrees) else "")),
    }


async def lire(chemin: str) -> dict:
    """Texte d'un fichier du NAS, extrait par le même lecteur que les imports."""
    import httpx
    from config import settings
    from ingestion.connectors import synology as c
    from ingestion.parsers import analyser, FichierNonSupporte

    vise = verifier(chemin)
    async with httpx.AsyncClient(verify=settings.synology_verify_tls) as client:
        base, sid = await _session(client)
        try:
            brut = await c._telecharger(client, base, sid, vise)
        finally:
            await c._logout(client, base, sid)

    if not brut:
        return {"chemin": vise, "message": "Fichier introuvable ou vide sur le NAS."}
    if len(brut) > MAX_OCTETS_LECTURE:
        return {"chemin": vise, "octets": len(brut),
                "message": (f"Fichier trop volumineux à lire dans le chat "
                            f"({len(brut) // (1024 * 1024)} Mo). Passe par une "
                            "synchronisation pour l'ingérer en mémoire.")}

    nom = posixpath.basename(vise)
    try:
        structure = analyser(nom, brut)
    except FichierNonSupporte as e:
        return {"chemin": vise, "message": str(e)}

    if structure["kind"] == "tabulaire":
        lignes = structure["rows"]
        return {"chemin": vise, "type": "tableau", "colonnes": structure["columns"],
                "lignes_totales": len(lignes), "apercu": lignes[:50],
                "note": f"{len(lignes)} ligne(s) ; 50 premières montrées."}
    texte = (structure.get("text") or "")[:MAX_CARACTERES]
    return {"chemin": vise, "type": "document", "texte": texte,
            "tronque": len(structure.get("text") or "") > MAX_CARACTERES}


async def chercher(motif: str, dossier: Optional[str] = None) -> dict:
    """Recherche par NOM de fichier, dans le périmètre autorisé."""
    import httpx
    from config import settings
    from ingestion.connectors import synology as c

    motif = (motif or "").strip()
    if not motif:
        return {"message": "Donne un morceau de nom de fichier à chercher."}

    racines = [verifier(dossier)] if dossier else dossiers_autorises()
    if not racines:
        raise NasRefuse("Aucun dossier NAS n'est ouvert à l'assistant.")

    trouves: list[dict] = []
    async with httpx.AsyncClient(verify=settings.synology_verify_tls) as client:
        base, sid = await _session(client)
        try:
            for racine in racines:
                depart = await c._appel(client, base, "SYNO.FileStation.Search", "start", 2,
                                        sid=sid, folder_path=racine, pattern=f"*{motif}*")
                tache = depart.get("taskid")
                if not tache:
                    continue
                import asyncio
                for _ in range(10):          # la recherche DSM est asynchrone
                    await asyncio.sleep(1.0)
                    res = await c._appel(client, base, "SYNO.FileStation.Search", "list", 2,
                                         sid=sid, taskid=tache, limit=50,
                                         additional='["size"]')
                    if res.get("finished"):
                        break
                for f in (res.get("files") or [])[:50]:
                    trouves.append({"nom": f.get("name"), "chemin": f.get("path"),
                                    "dossier": bool(f.get("isdir"))})
                await c._appel(client, base, "SYNO.FileStation.Search", "stop", 2,
                               sid=sid, taskid=tache)
        finally:
            await c._logout(client, base, sid)

    return {"motif": motif, "nombre": len(trouves), "resultats": trouves[:50],
            "dossiers_explores": racines}


async def deposer(chemin_dossier: str, nom: str, contenu: bytes) -> dict:
    """Dépose un fichier sur le NAS. ÉCRITURE — passe par la validation.

    Aucun écrasement : `overwrite=false`. Un fichier remplacé sans qu'on l'ait
    demandé est une perte de données irrécupérable côté NAS, et personne ne la
    remarque avant d'en avoir besoin.
    """
    import httpx
    from config import settings
    from ingestion.connectors import synology as c

    vise = verifier(chemin_dossier)
    propre = posixpath.basename((nom or "fichier").replace("\\", "/")) or "fichier"

    async with httpx.AsyncClient(verify=settings.synology_verify_tls) as client:
        base, sid = await _session(client)
        try:
            r = await client.post(
                f"{base}/webapi/entry.cgi",
                params={"api": "SYNO.FileStation.Upload", "version": 2,
                        "method": "upload", "_sid": sid},
                data={"path": vise, "create_parents": "false", "overwrite": "false"},
                files={"file": (propre, contenu)}, timeout=180)
            r.raise_for_status()
            data = r.json()
        finally:
            await c._logout(client, base, sid)

    if not data.get("success"):
        code = (data.get("error") or {}).get("code", 0)
        return {"depose": False,
                "message": c._message(code, "Upload")
                + (" (un fichier de ce nom existe déjà : renomme-le)" if code == 1805 else "")}
    logger.info("Fichier déposé sur le NAS dans %s (%d octets)", vise, len(contenu))
    return {"depose": True, "dossier": vise, "nom": propre, "octets": len(contenu)}
