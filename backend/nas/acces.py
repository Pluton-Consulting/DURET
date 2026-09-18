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

import asyncio
import logging
import posixpath
import re
from contextlib import asynccontextmanager
from typing import Optional

logger = logging.getLogger("duret.nas.acces")

MAX_ENTREES = 200
MAX_OCTETS_LECTURE = 15 * 1024 * 1024
# CE QU'ON ACCEPTE DE TÉLÉCHARGER pour l'afficher dans le chat (aperçu et
# bouton). 08/09, 10:57 : « ouvre le DCE » → l'archive ZIP de 179 Mo est
# partie en téléchargement, quatre minutes, jusqu'à ce que Noa clique
# « Arrêter ». La taille est connue AVANT (le serveur la donne) : au-delà de
# cette borne, on ne télécharge pas, on le dit, et on dit quoi faire.
MAX_OCTETS_TELECHARGEMENT = 40 * 1024 * 1024
MAX_CARACTERES = 40_000


class NasIndisponible(ConnectionError):
    """Le serveur n'a pas répondu (relais QuickConnect en 502, délai) : un aléa, pas un refus.
    18/09 : ce cas levait `NasRefuse` (« fichier absent »), lu comme un retrait de droits,
    et un métré entier se bloquait sur un fichier qu'il avait déjà lu."""


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


def decoder(chemin: str) -> str:
    """Un chemin que le modèle a ENCODÉ à la façon d'une URL redevient lisible.

    08/09, 11:15 : « ouvre le dce de ikos village » → `nas_ouvrir` sur
    `…/AOS - ikos-village-du-r%C3%A9emploi-%C3%A0-bordeaux - DCE.zip`. Le
    modèle avait encodé les accents ; le serveur ne connaît pas ce fichier-là.
    On ne décode que s'il y a bien des séquences %XX : un « % » isolé dans un
    vrai nom reste un « % ».
    """
    import re as _re
    from urllib.parse import unquote
    c = chemin or ""
    return unquote(c) if _re.search(r"%[0-9A-Fa-f]{2}", c) else c


def normaliser(chemin: str) -> str:
    """Chemin absolu POSIX, sans `..` ni segment vide."""
    c = decoder(chemin or "").strip().replace("\\", "/")
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
    from security.acces import niveaux_visibles
    from nas import niveaux

    # PAR DOSSIER DEPUIS LE 13/09 : il suffit qu'UN niveau porté par le serveur
    # (le défaut ou celui d'une règle) soit visible de ce rôle. Le tri fin —
    # quel dossier il voit — se fait à chaque chemin, dans `verifier`.
    if not (niveaux.niveaux_en_usage(niveaux.regles(), niveaux.defaut())
            & niveaux_visibles(getattr(user, "role", ""))):
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
            # LE NIVEAU DU DOSSIER (13/09) : le chemin est dans le périmètre,
            # encore faut-il que la personne pour qui l'on lit y ait droit.
            # Le message ne dit ni le niveau ni ce qu'il y a dedans.
            from security.lecteur import role_lecteur
            from nas import niveaux
            if not niveaux.visible_pour(vise, role_lecteur()):
                raise NasRefuse(f"« {chemin} » est réservé à d'autres profils.")
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
        return base, await c._login(client, base)
    except httpx.HTTPError:
        # Panne de TRANSPORT : l'adresse est en cause, pas les identifiants.
        # Un refus DSM (mot de passe, droits) ne passe pas par ici et ne doit
        # surtout pas invalider une adresse parfaitement bonne.
        #
        # Le cas courant est un tunnel de relais QuickConnect expiré : son port
        # change à chaque allocation, donc l'adresse gardée devient fausse d'un
        # instant à l'autre. On réessaie UNE fois avec une adresse fraîche —
        # sans quoi la première demande échouerait et seule la suivante
        # aboutirait, ce qui se lit comme « ça marche une fois sur deux ».
        c.oublier_adresse()
        logger.info("NAS injoignable à l'adresse retenue : nouvelle résolution")

    base = await c._base_url(client)
    return base, await c._login(client, base)


class _SessionNas:
    """Une session DSM vivante : client HTTP, adresse, jeton, et qui s'en sert."""

    def __init__(self, client, base: str, sid: str, boucle, expire: float):
        self.client = client
        self.base = base
        self.sid = sid
        self.boucle = boucle
        self.expire = expire
        self.usages = 0
        self.perimee = False


# LA SESSION EST GARDÉE, comme le client Drive chez Symbiose — et pour la même
# raison mesurée : six secondes par geste, dont l'essentiel en résolution
# d'adresse et login DSM, payées à CHAQUE action. « Aperçu puis ouvre puis
# dépose » = trois logins pour trois gestes d'une même conversation ; c'est ce
# qui rendait le serveur « beaucoup trop lent » avant d'avoir rien lu.
#
# Durée courte : un jeton DSM vit bien plus longtemps, mais on se reconstruit
# avant tout doute — et une erreur de TRANSPORT pendant l'usage périme la
# session, pour que l'appel suivant reparte d'une résolution fraîche.
_COURANTE: Optional[_SessionNas] = None
_DUREE_SESSION_S = 900


async def _clore(sess: _SessionNas) -> None:
    """Ferme une session sans jamais lever : c'est du ménage, pas un geste."""
    from ingestion.connectors import synology as c
    try:
        await c._logout(sess.client, sess.base, sess.sid)
    except Exception:  # noqa: BLE001
        pass
    try:
        await sess.client.aclose()
    except Exception:  # noqa: BLE001
        pass


@asynccontextmanager
async def connexion():
    """Une session DSM ouverte, PARTAGÉE entre les gestes et entre les tours.

    POURQUOI. Chaque appel ouvrait sa session puis se déconnectait : correct
    pour un geste isolé, ruineux en conversation — mesuré en production, une
    seule liste de dossier prenait six secondes, dont l'essentiel en résolution
    d'adresse et connexion, pas en lecture.

    LA FERMETURE ATTEND LE DERNIER SORTANT. Une session périmée (durée de vie
    écoulée, ou transport en erreur) n'est jamais fermée sous les pieds d'un
    geste qui l'utilise encore : elle est MARQUÉE, les nouveaux venus repartent
    d'une session neuve, et c'est le dernier usage en cours qui la clôt. Sans
    ce comptage, une arborescence longue se faisait couper sa connexion par le
    premier appel arrivé après l'expiration.

    Liée à sa boucle d'événements, comme le sémaphore de la file d'attente :
    un client HTTP appartient à la boucle qui l'a créé, on repart d'une session
    neuve si elle a changé.
    """
    global _COURANTE
    import time

    import httpx
    from config import settings

    boucle = asyncio.get_running_loop()
    sess = _COURANTE
    if not (sess is not None and not sess.perimee and sess.boucle is boucle
            and time.monotonic() < sess.expire):
        if sess is not None:
            sess.perimee = True
            if sess.usages == 0:
                await _clore(sess)
        client = httpx.AsyncClient(verify=settings.synology_verify_tls)
        try:
            base, sid = await _session(client)
        except BaseException:
            await client.aclose()
            raise
        sess = _SessionNas(client, base, sid, boucle,
                           time.monotonic() + _DUREE_SESSION_S)
        _COURANTE = sess

    sess.usages += 1
    try:
        yield sess.client, sess.base, sess.sid
    except httpx.HTTPError:
        # Transport douteux : la session ne ressert pas. L'appel suivant
        # repartira d'une adresse fraîche (cf. `_session` et QuickConnect).
        sess.perimee = True
        raise
    finally:
        sess.usages -= 1
        if sess.perimee and sess.usages == 0:
            await _clore(sess)
            if _COURANTE is sess:
                _COURANTE = None


PAGE_LISTAGE_COMPLET = 1000


async def _lister_ouvert(client, base, sid, chemin: str, tout: bool = False) -> dict:
    """Liste un dossier dans une session DÉJÀ ouverte.

    `tout=True` : TOUTES les entrées, page après page — c'est ce que demande le
    balayage (donc le catalogue, donc l'ingestion). Sans pagination, un
    dossier de plus de 200 entrées n'était vu qu'à moitié, et ce qui dépassait
    n'existait pour personne : ni pour la recherche, ni pour la
    synchronisation (11/09, « enrichir le NAS » qui n'ouvrait pas tout).
    Sans `tout`, le listage montré dans le chat reste borné à `MAX_ENTREES`,
    et le dit (`tronque`).
    """
    from ingestion.connectors import synology as c

    vise = verifier(chemin)
    bruts: list[dict] = []
    total = None
    offset = 0
    while True:
        data = await c._appel(client, base, "SYNO.FileStation.List", "list", 2,
                              sid=sid, folder_path=vise,
                              limit=PAGE_LISTAGE_COMPLET if tout else MAX_ENTREES,
                              offset=offset, additional='["size","time"]')
        page = data.get("files") or []
        total = int(data.get("total") or 0) or None
        # Un serveur qui ignorerait `offset` rendrait la même page à l'infini :
        # on n'ajoute que du NEUF, et une page sans rien de neuf arrête tout.
        deja = {f.get("path") for f in bruts}
        neuves = [f for f in page if f.get("path") not in deja]
        bruts.extend(neuves)
        offset += len(page)
        if not tout or not neuves or total is None or len(bruts) >= total:
            break

    entrees = []
    for f in (bruts if tout else bruts[:MAX_ENTREES]):
        # LES FICHIERS PARASITES D'UN MAC OU DE WINDOWS (15/09, relevé chez
        # Symbiose) : « ._logo.png » (métadonnées macOS de 176 octets) listé
        # devant le vrai logo, pris pour lui, ouvert à sa place. Ni listés, ni
        # catalogués, ni cherchés.
        nom_f = str(f.get("name") or "")
        if nom_f.startswith(("._", "~$")) or nom_f in (".DS_Store", "__MACOSX", "Thumbs.db", "desktop.ini"):
            continue
        add = f.get("additional") or {}
        entrees.append({
            "nom": f.get("name"), "chemin": f.get("path"),
            "dossier": bool(f.get("isdir")),
            "octets": (add.get("size") if not f.get("isdir") else None),
            # La date de modification sert à la synchronisation : un fichier
            # qui n'a pas bougé depuis son ingestion n'est pas retéléchargé.
            # La date vaut aussi pour un DOSSIER (18/09, test réel : « les 5 dossiers les plus
            # récents » → « le listage ne renvoie pas les dates des dossiers »).
            "modifie": (add.get("time") or {}).get("mtime"),
        })
    total = int(total if total is not None else len(bruts))
    total -= len(bruts if tout else bruts[:MAX_ENTREES]) - len(entrees)
    # Ce que la personne n'a pas le droit de voir n'existe pas pour elle : ni
    # dans la liste, ni dans le compte (13/09, niveaux par dossier).
    from security.lecteur import role_lecteur
    from nas import niveaux
    visibles = niveaux.filtrer(entrees, role_lecteur())
    total -= len(entrees) - len(visibles)
    entrees = visibles
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
                 # 07/09 : « ouvre-moi un appel d'offres au hasard » → sept
                 # listages de dossiers, jamais un fichier ouvert, puis une
                 # liste de fichiers INVENTÉE pour un dossier jamais listé. La
                 # note dit désormais le geste qui LIT, et comment choisir.
                 " Un FICHIER (`dossier: false`) se LIT avec `nas_ouvrir` et ce "
                 "`chemin` ; un dossier se descend avec `nas_lister`. Pour « un "
                 "au hasard » : choisis-en UN, descends-le jusqu'à un fichier et "
                 "ouvre-le — ne reliste pas les autres, et n'invente jamais le "
                 "contenu d'un dossier que tu n'as pas listé."
                 + (" Liste tronquée : affine avec un sous-dossier."
                    if total > len(entrees) else "")),
    }


async def lister(chemin: str) -> dict:
    """Contenu d'un dossier : sous-dossiers et fichiers, avec tailles."""
    async with connexion() as (client, base, sid):
        return await _lister_ouvert(client, base, sid, chemin)


async def _taille_ouverte(client, base, sid, chemin: str) -> tuple:
    """(taille, raison). La taille d'un fichier sans le télécharger — 0 si le
    serveur ne la dit pas, et alors la raison quand il en donne une : `getinfo`
    rend un `code` PAR FICHIER (408 : n'existe pas sous ce nom exact)."""
    import json as _json

    from ingestion.connectors import synology as c

    try:
        data = await c._appel(client, base, "SYNO.FileStation.List", "getinfo", 2,
                              sid=sid, path=_json.dumps([chemin]), additional='["size"]')
        for f in (data.get("files") or []):
            if f.get("code"):
                return 0, c._message(int(f["code"]), "SYNO.FileStation.List.getinfo")
            if f.get("isdir"):
                return 0, ""
            return int(((f.get("additional") or {}).get("size")) or 0), ""
    except Exception as e:  # noqa: BLE001 — sans taille, on télécharge comme avant
        logger.info("NAS : taille de %s inconnue (%s)", chemin, str(e)[:80])
    return 0, ""


def _meme_nom(a: str, b: str) -> bool:
    """Deux noms de fichier sont « les mêmes » aux accents, à la casse, à la
    forme Unicode (NFC/NFD : un « é » composé ou décomposé) et aux espaces
    doublés près. C'est la tolérance déjà accordée aux DOSSIERS par la
    résolution ; un FICHIER y avait droit aussi."""
    import re as _re
    na = _re.sub(r"\s+", " ", _sans_accent_nas(a)).strip()
    nb = _re.sub(r"\s+", " ", _sans_accent_nas(b)).strip()
    return bool(na) and na == nb


async def _rattraper_chemin(client, base, sid, chemin: str) -> Optional[str]:
    """Le VRAI chemin d'un fichier dont le chemin donné n'existe pas tel quel.

    08/09, 11:40 : le chemin venait du listage, recopié par le modèle — et le
    serveur répond « n'existe pas ». Un accent recomposé (É/È, forme NFC/NFD),
    un espace en trop : le nom paraît identique et ne l'est pas octet à octet.
    On résout le DOSSIER parent (tolérant, segment par segment), on le liste,
    et on prend l'entrée qui porte le même nom aux accents près. Rend None si
    rien ne correspond — l'appelant dira alors ce que le dossier contient.
    """
    from outils.nas import _resoudre

    parent, nom = posixpath.split(chemin.rstrip("/"))
    if not parent or not nom:
        return None
    try:
        parent_reel = await _resoudre(client, base, sid, parent)
        entrees = (await _lister_ouvert(client, base, sid, parent_reel)).get("entrees") or []
    except Exception as e:  # noqa: BLE001 — un parent introuvable : rien à rattraper
        logger.info("NAS : rattrapage impossible pour %s (%s)", chemin, str(e)[:80])
        return None
    for e in entrees:
        if not e.get("dossier") and _meme_nom(e.get("nom") or "", nom):
            if e.get("chemin") and e["chemin"] != chemin:
                logger.info("NAS : chemin rattrapé %s → %s", chemin, e["chemin"])
            return e.get("chemin")
    return None


async def _voisins(client, base, sid, chemin: str) -> list[str]:
    """Les noms de fichiers du dossier parent (12 au plus), pour un refus utile."""
    try:
        from outils.nas import _resoudre
        parent = posixpath.dirname(chemin.rstrip("/"))
        parent_reel = await _resoudre(client, base, sid, parent)
        entrees = (await _lister_ouvert(client, base, sid, parent_reel)).get("entrees") or []
        return [e.get("nom") or "" for e in entrees if not e.get("dossier")][:12]
    except Exception:  # noqa: BLE001
        return []


def _refus_lecture(chemin: str, raison: str, voisins: list[str]) -> dict:
    """Un refus qui dit la raison du serveur et ce qui existe à côté."""
    nom = posixpath.basename(chemin)
    return {"chemin": chemin,
            "message": (f"« {nom} » n'a pas pu être ouvert : {raison}."
                        + (f" Le dossier contient : {' ; '.join(voisins)}." if voisins else "")),
            "a_faire": ("Ne relance PAS ce chemin : le serveur l'a refusé et redira la même "
                        "chose. " + ("Choisis un nom EXACT dans la liste ci-dessus et rouvre-le "
                                      "avec ce nom, ou demande à la personne lequel elle veut."
                                      if voisins else
                                      "Liste le dossier parent (`nas_lister`) et reprends le `chemin` "
                                      "exact d'une entrée `dossier: false`."))}


async def _lire_ouvert(client, base, sid, chemin: str, proprietaire: str | None = None) -> dict:
    """Lit un fichier dans une session DÉJÀ ouverte.

    Avec `proprietaire`, le fichier est aussi DÉPOSÉ pour la personne (carte
    avec aperçu et téléchargement, `garantir_fichier_lu`) — avant tout
    contrôle de taille : un fichier trop lourd pour être lu dans le chat se
    télécharge quand même (08/09).
    """
    from ingestion.connectors import synology as c
    from ingestion.parsers import analyser, FichierNonSupporte
    from skills.affichage import garantir_fichier_lu

    vise = verifier(chemin)
    nom = posixpath.basename(vise)

    # LA TAILLE D'ABORD, LE TÉLÉCHARGEMENT ENSUITE. Un fichier trop lourd se
    # refuse en une requête de quelques millisecondes, pas après quatre
    # minutes de transfert. Si le serveur ne sait pas répondre, on télécharge
    # comme avant : ne pas savoir n'est pas une raison de refuser.
    taille, raison = await _taille_ouverte(client, base, sid, vise)
    # Certains fichiers du NAS portent littéralement « %C3%A9 » dans leur nom.
    # Le chemin décodé est toujours confiné ci-dessus ; si l'entrée exacte
    # existe, elle prime sur l'interprétation URL. Aucun fichier NAS n'est renommé.
    litteral=posixpath.normpath(str(chemin).strip().replace('\\','/'))
    if litteral.startswith('/') and litteral!=vise and '%' in litteral:
        from security.lecteur import role_lecteur
        from nas import niveaux
        if (any(litteral==r or litteral.startswith(r+'/') for r in dossiers_autorises())
                and niveaux.visible_pour(litteral,role_lecteur())):
            taille_exacte,raison_exacte=await _taille_ouverte(client,base,sid,litteral)
            if taille_exacte>0 and not raison_exacte:
                vise,nom,taille,raison=litteral,posixpath.basename(litteral),taille_exacte,''
    if not taille and raison:
        # LE NOM EXACT N'EXISTE PAS : ON RATTRAPE PAR LE DOSSIER. Si le
        # rattrapage échoue, on dit la raison du serveur ET ce que le dossier
        # contient réellement, pour que personne ne relance dix fois le même
        # chemin (08/09 : « déjà tenté à l'instant… introuvable »).
        rattrape = await _rattraper_chemin(client, base, sid, vise)
        if rattrape and rattrape != vise:
            return await _lire_ouvert(client, base, sid, rattrape, proprietaire)
        if not rattrape:
            return _refus_lecture(vise, raison, await _voisins(client, base, sid, vise))
    if taille and taille > MAX_OCTETS_TELECHARGEMENT:
        extension = nom.rsplit(".", 1)[-1].lower() if "." in nom else ""
        archive = extension in ("zip", "7z", "rar", "tar", "gz")
        return {"chemin": vise, "octets": taille,
                "message": (f"« {nom} » pèse {taille // (1024 * 1024)} Mo : trop lourd pour "
                            "être lu ou affiché dans le chat"
                            + (" — c'est une ARCHIVE, elle contient d'autres fichiers." if archive
                               else ".")),
                "a_faire": (("C'est une archive : ne la rouvre pas. Liste le dossier voisin "
                             "(`nas_lister`) et ouvre un des fichiers qu'il contient, ou dis à la "
                             "personne d'ouvrir l'archive depuis le serveur. ") if archive else
                            "Ne relance pas l'ouverture : dis la taille et propose d'ouvrir un "
                            "autre fichier du même dossier, ou une synchronisation pour l'ingérer.")}

    brut, raison = await c._telecharger_ou_raison(client, base, sid, vise)

    if not brut:
        rattrape = await _rattraper_chemin(client, base, sid, vise)
        if rattrape and rattrape != vise:
            return await _lire_ouvert(client, base, sid, rattrape, proprietaire)
        return _refus_lecture(vise, raison or "le serveur n'a rien rendu",
                              await _voisins(client, base, sid, vise))
    depot = garantir_fichier_lu({}, nom, brut, proprietaire) if proprietaire else {}
    if len(brut) > MAX_OCTETS_LECTURE:
        return {"chemin": vise, "octets": len(brut), **depot,
                "message": (f"Fichier trop volumineux à lire dans le chat "
                            f"({len(brut) // (1024 * 1024)} Mo)"
                            + (" ; il est affiché et téléchargeable." if depot else
                               ". Passe par une synchronisation pour l'ingérer en mémoire."))}

    try:
        structure = analyser(nom, brut)
    except FichierNonSupporte as e:
        return {"chemin": vise, "message": str(e), **depot}

    try:
        from security.conversation import fil_courant
        if proprietaire and fil_courant.get():
            from bureautique.lecture_integrale import lire as lire_integral
            from ressources.dossiers import enregistrer
            integral = await asyncio.to_thread(lire_integral, nom, brut, structure.get("text") or "")
            if integral.strip():
                import hashlib
                source = await asyncio.to_thread(enregistrer, proprietaire, fil_courant.get(), nom, integral, vise, hashlib.sha256(brut).hexdigest())
                depot = {**depot, "source_dossier": source,
                         "pour_continuer": {"skill": "lire_source_dossier", "args": {"source": source, "fragment": 1}},
                         "lecture_integrale_disponible": True}
    except Exception as e:
        depot={**depot,"lecture_integrale_disponible":False,"avertissement_lecture":"Lecture intégrale non enregistrée ("+type(e).__name__+"). Utilise ajouter_source_dossier pour reprendre avant toute synthèse complète."}
    if structure["kind"] == "tabulaire":
        lignes = structure["rows"]
        return {"chemin": vise, "type": "tableau", "colonnes": structure["columns"],
                "lignes_totales": len(lignes), "apercu": lignes[:50],
                "note": f"{len(lignes)} ligne(s) ; 50 premières montrées.", **depot}
    texte = (structure.get("text") or "")[:MAX_CARACTERES]
    return {"chemin": vise, "type": "document", "texte": texte,
            "tronque": len(structure.get("text") or "") > MAX_CARACTERES, **depot}


async def lire(chemin: str, proprietaire: str | None = None) -> dict:
    """Texte d'un fichier du NAS, extrait par le même lecteur que les imports."""
    async with connexion() as (client, base, sid):
        return await _lire_ouvert(client, base, sid, chemin, proprietaire)


# LE BALAYAGE MAISON, ET POURQUOI IL EXISTE.
#
# RELEVÉ EN PRODUCTION LE 08/09 : `SYNO.FileStation.Search` rend ZÉRO sur ce
# NAS, toujours — y compris sur un dossier au chemin exact dont l'arborescence
# compte 132 fichiers, dont 14 PDF dans un sous-dossier nommé « PDF ». La
# requête part, DSM répond « terminé, 0 fichier ». C'est le comportement d'un
# serveur dont l'index de recherche (Universal Search) n'est pas construit sur
# ces partages, et aucun réglage de notre côté n'y change rien.
#
# Or LE LISTAGE, LUI, MARCHE : la même minute, l'arborescence complète du même
# dossier est rendue en 6,5 secondes. On cesse donc de dépendre d'un index
# qu'on ne maîtrise pas : on descend nous-mêmes, par niveaux, plusieurs
# listages de front. C'est plus lent qu'un index — quand il fonctionne — et
# c'est infiniment mieux qu'une recherche qui répond « rien » sur ce qui
# existe : une absence FAUSSE fait conclure au modèle que le document n'est
# pas là, et il l'annonce à l'utilisateur.
#
# Les plafonds sont du TEMPS et du NOMBRE DE DOSSIERS, et un balayage
# incomplet le DIT (règle du 01/09 : jamais bloqué en quantité, mais jamais
# une absence présentée comme prouvée).
# UN BALAYAGE NE RELIT PAS CE QU'IL VIENT DE LIRE. Dans le tour du 08/09, le
# modèle a lancé huit recherches en cinq minutes, sur des variantes du même nom
# (« AIRBORNE », « 2029 AIRBORNE », « pdf »…). Sans mémoire, chacune redescend
# toute l'arborescence : le geste devient juste, et le tour devient
# interminable. Ce cache ne sert QU'AU BALAYAGE : `nas_lister` et
# `nas_arborescence`, les gestes que l'on demande explicitement, listent
# toujours frais — un dossier qu'on vient d'ouvrir doit montrer ce qu'il
# contient MAINTENANT. Cinq minutes est la durée d'une conversation, pas celle
# d'une journée de travail.
CACHE_DUREE_S = 300
CACHE_MAX = 4000
_CACHE_LISTAGE: dict = {}

# CE QU'ON NE DESCEND JAMAIS. « #recycle » est la corbeille de Synology : des
# milliers de dossiers supprimés, que personne ne cherche, et qui mangeaient
# le budget du balayage avant qu'il n'atteigne le classement (08/09, 10:45 :
# « parcours interrompu » sans avoir vu l'appel d'offres). « @eaDir » porte
# les vignettes, « #snapshot » les instantanés. Tout ce qui commence par « # »
# ou « @ » est du serveur, pas de l'entreprise.
DOSSIERS_IGNORES = ("#recycle", "@eaDir", "#snapshot", "@tmp", "@SynoResource", ".SynologyWorkingDirectory")


def _dossier_ignore(nom: str) -> bool:
    n = (nom or "").strip()
    return n in DOSSIERS_IGNORES or n.startswith(("#", "@"))


BALAYAGE_DE_FRONT = 8
BALAYAGE_PROFONDEUR = 8
BALAYAGE_DOSSIERS_MAX = 3000
# 08/09 après-midi, Noa : « il dit "je réfléchis" pendant très très longtemps ».
# Un tour lançait huit recherches, chacune pouvant balayer 45 s. Le balayage
# n'est plus qu'un SECOURS (le catalogue répond en mémoire dès qu'il est
# construit) : il est court, et un parcours coupé le dit.
BALAYAGE_DELAI_S = 15


async def _balayer(client, base, sid, racines: list[str],
                   correspond, delai_s: float = BALAYAGE_DELAI_S,
                   dossiers_max: int = BALAYAGE_DOSSIERS_MAX,
                   profondeur: int = BALAYAGE_PROFONDEUR,
                   arret_au_premier: bool = False,
                   progres: Optional[dict] = None,
                   connu: Optional[dict] = None) -> tuple[list[dict], bool]:
    """Descend l'arborescence et rend les entrées retenues par `correspond`.

    `correspond(entree) -> bool` reçoit un dict `{nom, chemin, dossier, octets}`.
    Rend `(trouvés, complet)` : `complet` est faux dès qu'un plafond a mordu —
    l'appelant doit alors dire que l'absence n'est pas prouvée.

    `progres` (14/09) : un dict tenu à jour au fil du parcours — dossiers lus,
    dossiers repérés, fichiers repérés, niveau, dernier dossier lu. Relevé de
    Noa : « je relève l'arborescence du NAS · depuis 11 min · 0 traité(s) »,
    rien ne disait que le parcours avançait.

    `connu` (18/09) : LE RELEVÉ PRÉCÉDENT, pour un parcours INCRÉMENTAL —
    {"dates": {chemin du dossier: sa date de modification}, "enfants": {chemin:
    [ses entrées]}}. Un dossier dont la date n'a pas bougé depuis le relevé
    précédent n'est pas relu : ses entrées d'alors sont reprises. Mesuré en
    production : 110 000 entrées en 40 minutes et toujours partiel ; d'un
    relevé à l'autre, seuls les dossiers qui ont changé se listent, et la
    couverture grandit jusqu'à être complète. ⚠️ La date d'un DOSSIER ne bouge
    pas quand un fichier est modifié EN PLACE : une synchronisation qui compare
    les dates des fichiers ne doit pas passer par là (`relire_tout`).
    """
    import time as _t

    debut = _t.monotonic()
    porte = asyncio.Semaphore(BALAYAGE_DE_FRONT)
    trouves: list[dict] = []
    vus: set = set()
    complet = True
    niveau = [(r, None) for r in racines if r]
    listes = 0
    dates_connues = (connu or {}).get("dates") or {}
    enfants_connus = (connu or {}).get("enfants") or {}
    if progres is not None:
        progres.update({"debut": debut, "delai_s": delai_s, "dossiers_lus": 0,
                        "dossiers_vus": len(niveau), "fichiers_vus": 0, "niveau": 0,
                        "dernier": "", "reutilises": 0})

    coupe = False

    async def _un(couple) -> list[dict]:
        nonlocal coupe
        chemin, date_courante = couple
        # LE DOSSIER N'A PAS CHANGÉ DEPUIS LE RELEVÉ PRÉCÉDENT : ses entrées d'alors valent, sans
        # listage (la date vient du listage du PARENT, faite à l'instant — pas de l'ancien relevé).
        if (date_courante and chemin in enfants_connus and dates_connues.get(chemin)
                and int(date_courante) == int(dates_connues[chemin])):
            if progres is not None:
                progres["reutilises"] = progres.get("reutilises", 0) + 1
            return enfants_connus[chemin]
        garde = _CACHE_LISTAGE.get(chemin)
        if garde and garde[0] > _t.monotonic():
            return garde[1]
        # LE DÉLAI SE VÉRIFIE ICI AUSSI, pas seulement entre deux niveaux :
        # un niveau de deux mille dossiers dure plus que tout le budget, et le
        # contrôle d'entre-niveaux n'arrivait qu'après (08/09 : « 45 s » de
        # plafond, 93 s mesurées). Passé le délai, on ne lance plus rien.
        if _t.monotonic() - debut > delai_s:
            coupe = True
            return []
        async with porte:
            if _t.monotonic() - debut > delai_s:
                coupe = True
                return []
            garde = _CACHE_LISTAGE.get(chemin)      # un autre l'a peut-être lu pendant l'attente
            if garde and garde[0] > _t.monotonic():
                return garde[1]
            try:
                brut = await _lister_ouvert(client, base, sid, chemin, tout=True)
            except Exception as e:  # noqa: BLE001 — un dossier illisible n'arrête pas le balayage
                logger.info("NAS : dossier ignoré pendant le balayage (%s) : %s",
                            chemin, str(e)[:100])
                return []
            entrees = brut.get("entrees") or []
            if progres is not None:
                progres["dossiers_lus"] = progres.get("dossiers_lus", 0) + 1
                progres["dernier"] = chemin
            if len(_CACHE_LISTAGE) > CACHE_MAX:
                _CACHE_LISTAGE.clear()              # borne grossière : on repart à neuf
            _CACHE_LISTAGE[chemin] = (_t.monotonic() + CACHE_DUREE_S, entrees)
            return entrees

    for _ in range(max(1, int(profondeur))):
        if not niveau:
            break
        if _t.monotonic() - debut > delai_s or listes >= dossiers_max:
            complet = False
            break
        if progres is not None:
            progres["niveau"] = progres.get("niveau", 0) + 1
        paquets = await asyncio.gather(*[_un(c) for c in niveau],
                                       return_exceptions=True)
        listes += len(niveau)
        suivant: list[str] = []
        for paquet in paquets:
            if isinstance(paquet, BaseException):
                continue
            for e in paquet:
                chemin = e.get("chemin")
                if not chemin or chemin in vus or _dossier_ignore(e.get("nom") or ""):
                    continue
                vus.add(chemin)
                if correspond(e):
                    trouves.append(e)
                    if arret_au_premier:
                        return trouves, complet
                if e.get("dossier"):
                    suivant.append((chemin, e.get("modifie")))
                elif progres is not None:
                    progres["fichiers_vus"] = progres.get("fichiers_vus", 0) + 1
        if progres is not None:
            progres["dossiers_vus"] = progres.get("dossiers_vus", 0) + len(suivant)
        niveau = suivant
        if coupe:
            complet = False
            break
    else:
        # La profondeur maximale est atteinte alors qu'il restait des dossiers.
        if niveau:
            complet = False
    return trouves, complet


# ── LE CATALOGUE : l'arborescence entière, en mémoire ─────────────────────
#
# 08/09, 10:45 : même avec le balayage, « 2029 AIRBORNE SONOVISION » (niveau 4
# sous /home) n'a pas été atteint dans le budget d'UNE recherche — le Drive de
# l'entreprise porte des milliers de dossiers, et une recherche ne peut pas
# tous les parcourir à chaque fois. Le jumeau sur Google Drive a réglé la
# même question le 01/09 avec un CATALOGUE (balayage global, filtré chez
# nous). Même réponse ici : l'arborescence se construit UNE fois, en tâche de
# fond dès le démarrage, se rafraîchit toutes les heures, et la recherche
# devient un filtre en mémoire — instantané, complet, et honnête sur son âge.
#
# Tant que le catalogue n'est pas prêt (première minute après un
# redéploiement), la recherche retombe sur le balayage borné, et le DIT.
# UN CATALOGUE COMPLET, ET QUI SURVIT AU REDÉMARRAGE (18/09, banc de tests réel). Mesuré en
# production : « catalogue partiel — 60 341 entrées en 916 s », puis 37 600 : le serveur de
# Duret dépasse le plafond, donc CHAQUE recherche par nom disait « parcours interrompu, une
# absence n'est pas prouvée », pour toujours. Et chaque redéploiement repartait de zéro
# (quinze minutes de balayage de secours). Désormais : le relevé va jusqu'au bout (40 min,
# 250 000 entrées), le résultat est ÉCRIT sur le disque et RELU au démarrage — servi tout de
# suite, marqué de son âge —, et un catalogue complet ne se refait que toutes les six heures.
CATALOGUE_DUREE_S = 3600                # entre deux reconstructions d'un catalogue PARTIEL
CATALOGUE_DUREE_COMPLET_S = 6 * 3600    # …et d'un catalogue COMPLET
CATALOGUE_DELAI_S = 2400
CATALOGUE_DOSSIERS_MAX = 250000
CATALOGUE_PROFONDEUR = 40
CATALOGUE_FICHIER = "nas_catalogue.json"
_CATALOGUE: dict = {"etat": "vide", "entrees": [], "construit_le": 0.0,
                    "complet": False, "en_cours": False, "progression": {}, "age_s": 0.0}


def _chemin_catalogue():
    import os
    from config import settings
    base = str(getattr(settings, "documents_dir", "") or os.environ.get("DOCUMENTS_DIR") or "/tmp/duret-documents")
    # Dans un SOUS-DOSSIER : l'atelier prend tout `.json` posé à la racine de DOCUMENTS_DIR
    # pour la fiche d'un document (piège payé le 17/09 avec des sauvegardes de file).
    return os.path.join(base, "cache", CATALOGUE_FICHIER)


def _ecrire_catalogue(entrees: list, complet: bool) -> None:
    """Le catalogue sur le disque, écrit d'un bloc (fichier temporaire puis renommage)."""
    import json as _json, os, time as _t
    try:
        chemin = _chemin_catalogue()
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        tmp = f"{chemin}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            _json.dump({"construit_le": _t.time(), "complet": bool(complet), "entrees": entrees}, f, ensure_ascii=False)
        os.replace(tmp, chemin)
    except Exception as e:  # noqa: BLE001 — un disque plein ne casse pas la recherche
        logger.warning("NAS : catalogue non écrit sur le disque : %s", str(e)[:120])


def restaurer_catalogue() -> bool:
    """Relit le catalogue écrit par un processus précédent. Vrai s'il a été chargé.
    Il est servi tout de suite (recherche instantanée dès le démarrage) et marqué de son
    âge ; la reconstruction de fond part quand même et le remplacera."""
    import json as _json, os, time as _t
    try:
        chemin = _chemin_catalogue()
        if not os.path.exists(chemin) or _CATALOGUE["entrees"]:
            return False
        with open(chemin, encoding="utf-8") as f:
            data = _json.load(f)
        entrees = data.get("entrees") or []
        if not isinstance(entrees, list) or not entrees:
            return False
        age = max(0.0, _t.time() - float(data.get("construit_le") or 0))
        _CATALOGUE.update({"etat": "restaure", "entrees": entrees, "complet": bool(data.get("complet")),
                           "construit_le": _t.monotonic() - age, "age_s": age})
        logger.info("NAS : catalogue relu depuis le disque — %d entrées, %s, âgé de %.0f min",
                    len(entrees), "complet" if data.get("complet") else "partiel", age / 60)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("NAS : catalogue du disque illisible : %s", str(e)[:120])
        return False


def _releve_precedent() -> Optional[dict]:
    """Le relevé en mémoire sous la forme que `_balayer` sait réutiliser."""
    entrees = _CATALOGUE.get("entrees") or []
    if not entrees:
        return None
    dates, enfants = {}, {}
    for e in entrees:
        chemin = str(e.get("chemin") or "")
        if not chemin:
            continue
        enfants.setdefault(posixpath.dirname(chemin), []).append(e)
        if e.get("dossier") and e.get("modifie"):
            dates[chemin] = e["modifie"]
    return {"dates": dates, "enfants": enfants}


async def construire_catalogue(relire_tout: bool = False) -> dict:
    """Balaye tout le périmètre et garde le résultat en mémoire. Une seule
    construction à la fois : un second appel pendant la première n'en lance
    pas une autre, il rend l'état. `relire_tout` : aucun dossier repris du relevé
    précédent (synchronisation, qui compare les dates des FICHIERS)."""
    import time as _t

    if _CATALOGUE["en_cours"]:
        return _CATALOGUE
    racines = dossiers_autorises()
    if not racines:
        return _CATALOGUE
    _CATALOGUE["en_cours"] = True
    debut = _t.monotonic()
    from security.lecteur import en_systeme
    try:
        # Partagé par tous : construit avec la vue ENTIÈRE, même lancé depuis
        # le geste d'un profil (13/09, niveaux par dossier).
        with en_systeme():
            async with connexion() as (client, base, sid):
                _CATALOGUE["progression"] = {}
                connu = None if relire_tout else _releve_precedent()
                entrees, complet = await _balayer(
                    client, base, sid, racines, lambda e: True,
                    delai_s=CATALOGUE_DELAI_S, dossiers_max=CATALOGUE_DOSSIERS_MAX,
                    profondeur=CATALOGUE_PROFONDEUR,
                    progres=_CATALOGUE["progression"], connu=connu)
                if connu:
                    logger.info("NAS : relevé incrémental — %d dossier(s) repris sans listage",
                                int(_CATALOGUE["progression"].get("reutilises", 0)))
        # Un relevé partiel ne REMPLACE pas un catalogue complet relu du disque : il serait
        # moins bon que ce qu'on a. Il ne s'impose que s'il est complet, ou plus fourni.
        if complet or len(entrees) >= len(_CATALOGUE["entrees"]) or not _CATALOGUE.get("complet"):
            _CATALOGUE.update({"etat": "pret" if complet else "partiel",
                               "entrees": entrees, "complet": complet, "incremental": bool(connu),
                               "construit_le": _t.monotonic(), "age_s": 0.0})
            _ecrire_catalogue(entrees, complet)
        logger.info("NAS : catalogue %s — %d entrées en %.0f s",
                    "pret" if complet else "partiel", len(entrees), _t.monotonic() - debut)
    except Exception as e:  # noqa: BLE001 — un NAS injoignable ne casse pas le démarrage
        logger.warning("NAS : catalogue non construit : %s", str(e)[:160])
    finally:
        _CATALOGUE["en_cours"] = False
    return _CATALOGUE


def catalogue_pret() -> Optional[list]:
    """Les entrées du catalogue s'il est utilisable, sinon None — et dans ce
    cas la construction part en tâche de fond si rien ne tourne déjà."""
    import time as _t

    if _CATALOGUE["etat"] == "vide":
        restaurer_catalogue()
    duree = CATALOGUE_DUREE_COMPLET_S if _CATALOGUE.get("complet") else CATALOGUE_DUREE_S
    frais = (_CATALOGUE["etat"] in ("pret", "partiel", "restaure")
             and _t.monotonic() - _CATALOGUE["construit_le"] < duree)
    if frais:
        return _CATALOGUE["entrees"]
    if not _CATALOGUE["en_cours"]:
        try:
            asyncio.get_running_loop().create_task(construire_catalogue())
        except RuntimeError:
            pass
    # Un catalogue PÉRIMÉ vaut mieux qu'aucun le temps de la reconstruction.
    return _CATALOGUE["entrees"] or None


def decrire_progression(p: Optional[dict] = None) -> str:
    """Le relevé en cours, en une ligne lisible : dossiers lus sur repérés,
    fichiers repérés, profondeur, temps écoulé sur le temps imparti, et le
    dernier dossier lu. Fonction pure (le banc l'exécute)."""
    import time as _t

    p = _CATALOGUE.get("progression") if p is None else p
    # `is None`, pas un test de vérité : l'horloge monotone peut valoir 0 au
    # démarrage du processus (piège déjà payé par le rapporteur d'avancement).
    if not p or p.get("debut") is None:
        return "je relève l'arborescence du NAS · démarrage du parcours"
    ecoule = max(0, int(_t.monotonic() - float(p["debut"])))
    delai = int(p.get("delai_s") or CATALOGUE_DELAI_S)
    nb = lambda n: f"{int(n):,}".replace(",", "\u202f")  # noqa: E731
    dernier = str(p.get("dernier") or "")
    if len(dernier) > 60:
        dernier = "…" + dernier[-59:]
    texte = (f"je relève l'arborescence du NAS · {nb(p.get('dossiers_lus', 0))} dossiers lus "
             f"sur {nb(p.get('dossiers_vus', 0))} repérés · {nb(p.get('fichiers_vus', 0))} fichiers "
             f"repérés · profondeur {p.get('niveau', 0)} · {ecoule // 60} min {ecoule % 60:02d} s "
             f"(arrêt à {delai // 60} min)")
    if p.get("reutilises"):
        texte += f" · {nb(p['reutilises'])} dossiers repris du relevé précédent"
    return texte + (f" · {dernier}" if dernier else "")


async def catalogue_attendu(attente_max_s: float = CATALOGUE_DELAI_S + 60,
                            sur_progres=None, relire_tout: bool = False) -> tuple[list, bool]:
    """(entrées, complet) d'un catalogue FRAIS — attendu s'il se construit,
    construit s'il manque. Pour les traitements de fond (synchronisation) :
    un second balayage du même serveur pendant que le premier tourne ne
    ferait que doubler la charge.

    `sur_progres(texte)` (14/09) est appelé toutes les 5 s pendant le relevé,
    qu'il ait été lancé ici ou par la reconstruction horaire : c'est lui qui
    fait avancer la carte du connecteur pendant cette phase."""
    import time as _t

    async def _dire():
        if sur_progres is None:
            return
        try:
            await sur_progres(decrire_progression())
        except Exception:  # noqa: BLE001 — un compteur ne casse pas un relevé
            pass

    debut = _t.monotonic()
    while _CATALOGUE["en_cours"] and _t.monotonic() - debut < attente_max_s:
        await _dire()
        await asyncio.sleep(5)
    if _CATALOGUE["etat"] == "vide":
        restaurer_catalogue()
    duree = CATALOGUE_DUREE_COMPLET_S if _CATALOGUE.get("complet") else CATALOGUE_DUREE_S
    frais = (_CATALOGUE["etat"] in ("pret", "partiel", "restaure")
             and _t.monotonic() - _CATALOGUE["construit_le"] < duree
             and not (relire_tout and _CATALOGUE.get("age_s", 0) > 0))
    if relire_tout:
        frais = frais and _CATALOGUE["etat"] == "pret" and not _CATALOGUE.get("incremental")
    if not frais and not _CATALOGUE["en_cours"]:
        tache = asyncio.get_running_loop().create_task(construire_catalogue(relire_tout=relire_tout))
        while not tache.done():
            await _dire()
            await asyncio.wait({tache}, timeout=5)
        await tache
    return list(_CATALOGUE["entrees"] or []), bool(_CATALOGUE.get("complet"))


async def demarrer_catalogue() -> None:
    """La tâche de fond : construire, puis reconstruire à chaque heure."""
    import time as _t
    restaurer_catalogue()
    # Un catalogue complet et récent relu du disque : inutile de refaire 40 minutes de listages.
    if _CATALOGUE.get("complet") and _CATALOGUE.get("age_s", 0) < CATALOGUE_DUREE_COMPLET_S:
        await asyncio.sleep(max(60.0, CATALOGUE_DUREE_COMPLET_S - _CATALOGUE.get("age_s", 0)))
    while True:
        await construire_catalogue()
        await asyncio.sleep(CATALOGUE_DUREE_COMPLET_S if _CATALOGUE.get("complet") else CATALOGUE_DUREE_S)


def _sans_accent_nas(texte: str) -> str:
    """Comparaison de noms indulgente aux accents et à la casse."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", (texte or "").lower())
                   if unicodedata.category(c) != "Mn")


def _nom_correspond(nom: str, motif: str) -> bool:
    """Tolérer espaces/tirets/underscores et CCTP17 ↔ CCTP 17, sans deviner."""
    import re
    nom, motif = _sans_accent_nas(nom), _sans_accent_nas(motif).strip()
    if not motif:return False
    if motif in nom:return True
    def mots(t):
        t=re.sub(r'(?<=[a-z])(?=[0-9])|(?<=[0-9])(?=[a-z])',' ',t)
        return re.findall(r'[a-z0-9]+',t)
    termes=mots(motif);disponibles=set(mots(nom))
    return bool(termes) and all(m in disponibles for m in termes)


async def _chercher_ouvert(client, base, sid, motif: str,
                           dossier: Optional[str] = None) -> dict:
    """Cherche par nom dans une session DÉJÀ ouverte."""
    from ingestion.connectors import synology as c

    motif = decoder((motif or "").strip())
    if not motif:
        # Un refus, pas un résultat : rendu comme un dictionnaire ordinaire, il
        # passait pour une recherche réussie et sans correspondance.
        raise NasRefuse("Donne un morceau de nom de fichier à chercher.")

    racines = [verifier(dossier)] if dossier else dossiers_autorises()
    if not racines:
        raise NasRefuse("Aucun dossier NAS n'est ouvert à l'assistant.")

    async def _sur(racine: str) -> list[dict]:
        """Cherche sous UNE racine. Les racines tournent EN PARALLÈLE :
        chercher /home puis /Drive en série doublait l'attente, alors que le
        serveur mène les deux recherches de front sans effort. Et le sondage
        est resserré (0,4 s) : la recherche DSM rend en une à deux secondes,
        attendre une seconde pleine entre deux regards doublait le temps perçu.
        """
        # LE CHEMIN EST UN TABLEAU JSON, comme pour le téléchargement
        # (`_telecharger` passe `["/chemin"]`). Passé nu, DSM refusait la
        # recherche ; l'erreur était avalée plus bas (« une racine en panne
        # n'annule pas les autres ») et TOUTE recherche par nom rendait
        # « aucun fichier » — sur un fichier listé une minute plus tôt (08/09 :
        # « 2029 RC VF.pdf » introuvable par `nas_ouvrir`, ouvert par son
        # chemin). L'ancienne forme reste en second essai.
        import json as _json
        try:
            depart = await c._appel(client, base, "SYNO.FileStation.Search", "start", 2,
                                    sid=sid, folder_path=_json.dumps([racine]),
                                    pattern=f"*{motif}*")
        except Exception:  # noqa: BLE001 — un DSM qui n'accepte que la forme nue
            depart = await c._appel(client, base, "SYNO.FileStation.Search", "start", 2,
                                    sid=sid, folder_path=racine, pattern=f"*{motif}*")
        tache = depart.get("taskid")
        if not tache:
            return []
        res: dict = {}
        # 25 × 0,4 s = 10 s coupaient une recherche encore en cours (01/09,
        # règle de Noa : jamais bloqué en temps) : on laisse au serveur jusqu'à
        # une minute, et un inachèvement se DIT au lieu de passer pour un
        # résultat complet.
        for _ in range(150):         # la recherche DSM est asynchrone
            await asyncio.sleep(0.4)
            res = await c._appel(client, base, "SYNO.FileStation.Search", "list", 2,
                                 sid=sid, taskid=tache, limit=200,
                                 additional='["size"]')
            if res.get("finished"):
                break
        sortie = [{"nom": f.get("name"), "chemin": f.get("path"),
                   "dossier": bool(f.get("isdir")),
                   "inacheve": not res.get("finished") or None}
                  for f in (res.get("files") or [])[:200]]
        await c._appel(client, base, "SYNO.FileStation.Search", "stop", 2,
                       sid=sid, taskid=tache)
        return sortie

    groupes = await asyncio.gather(*[_sur(r) for r in racines],
                                   return_exceptions=True)
    trouves: list[dict] = []
    for g in groupes:
        if isinstance(g, BaseException):
            # Une racine en panne n'annule pas les trouvailles des autres.
            logger.warning("NAS : recherche « %s » en échec sur une racine : %s",
                           motif, g)
            continue
        trouves.extend(g)

    pannes = [g for g in groupes if isinstance(g, BaseException)]
    inacheve = any(t.pop("inacheve", None) for t in trouves)
    methode = "index du serveur"

    # ZÉRO RÉSULTAT DE L'INDEX N'EST PAS UNE ABSENCE : ON VA VOIR NOUS-MÊMES.
    # Sur ce serveur, `SYNO.FileStation.Search` rend toujours zéro (index non
    # construit) — y compris sur un dossier dont on vient de lister 132
    # fichiers. Le balayage par listages, lui, voit ce qui est là. Il prend le
    # relais dès que l'index ne rend RIEN, et aussi quand il est tombé partout.
    if not trouves:
        cible = _sans_accent_nas(motif)

        def _correspond(e):
            return _nom_correspond(e.get("nom") or "",motif)

        cat = catalogue_pret()
        if cat is not None:
            # LE CATALOGUE : instantané et complet. `racines` peut être un
            # dossier précis : on ne rend que ce qui vit dessous.
            balayes = [e for e in cat
                       if any(str(e.get("chemin") or "").startswith(r.rstrip("/") + "/")
                              for r in racines)
                       and _correspond(e)]
            complet = bool(_CATALOGUE.get("complet"))
            methode_repli = "catalogue"
        else:
            balayes, complet = await _balayer(client, base, sid, racines, _correspond)
            methode_repli = "parcours des dossiers"
        if balayes or not pannes:
            trouves = [{"nom": e.get("nom"), "chemin": e.get("chemin"),
                        "dossier": bool(e.get("dossier")),
                        "octets": e.get("octets")} for e in balayes]
            methode = methode_repli
            inacheve = not complet
        elif pannes and len(pannes) == len(groupes):
            raise NasRefuse(
                "La recherche par nom a ÉCHOUÉ sur le serveur "
                f"({str(pannes[0])[:120]}) : ce n'est PAS « aucun résultat ». "
                "Passe par le listage (`nas_lister`) et le `chemin` exact.")

    from security.lecteur import role_lecteur
    from nas import niveaux
    trouves = niveaux.filtrer(trouves, role_lecteur())
    sortie = {"motif": motif, "nombre": len(trouves), "resultats": trouves[:200],
              "dossiers_explores": racines, "methode": methode}
    if inacheve:
        sortie["note"] = ("Parcours INTERROMPU avant d'avoir tout vu (temps ou "
                          "nombre de dossiers) : résultats partiels, une absence "
                          "n'est PAS prouvée — dis-le tel quel, et propose de "
                          "chercher dans un dossier précis.")
    if methode == "parcours des dossiers" and _CATALOGUE.get("etat") == "vide":
        sortie["note"] = ((sortie.get("note") or "") + " Le catalogue du serveur "
                          "se construit encore (redémarrage récent) : dans quelques "
                          "minutes la recherche sera complète et instantanée.").strip()
    return sortie


def plus_recents(dossier: Optional[str], nombre: int = 20) -> dict:
    """Les fichiers modifiés le plus récemment sous un dossier (ou tout le périmètre), d'après le
    CATALOGUE (18/09, test réel : « le fichier modifié le plus récemment sur tout le serveur » →
    « aucune action ne trie par date »). Le catalogue porte la date de chaque fichier ; une
    absence de catalogue se dit, elle ne s'invente pas."""
    from datetime import datetime, timezone
    cat = catalogue_pret()
    if cat is None:
        return {"resultats": [], "nombre": 0, "methode": "aucune",
                "note": "Le catalogue du serveur n'est pas encore construit : ce classement par date n'est pas possible pour l'instant, réessaie dans quelques minutes."}
    racines = [verifier(dossier)] if dossier else dossiers_autorises()
    from security.lecteur import role_lecteur
    from nas import niveaux
    fichiers = [e for e in cat if not e.get("dossier") and e.get("modifie")
                and any(str(e.get("chemin") or "").startswith(r.rstrip("/") + "/") for r in racines)]
    fichiers = niveaux.filtrer(fichiers, role_lecteur())
    fichiers.sort(key=lambda e: int(e.get("modifie") or 0), reverse=True)
    n = max(1, min(int(nombre or 20), 200))
    sortie = []
    for e in fichiers[:n]:
        d = {k: e.get(k) for k in ("nom", "chemin", "octets", "modifie")}
        d["dossier"] = False
        try:
            d["modifie_le"] = datetime.fromtimestamp(int(e["modifie"]), tz=timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M")
        except (TypeError, ValueError, OverflowError, OSError):
            d["modifie_le"] = ""
        sortie.append(d)
    return {"resultats": sortie, "nombre": len(fichiers), "methode": "catalogue",
            "dossiers_explores": racines, "tri": "date de modification décroissante",
            **({"note": "Parcours du serveur encore PARTIEL : un fichier plus récent peut exister dans une branche non relevée."}
               if not _CATALOGUE.get("complet") else {})}


async def chercher(motif: str, dossier: Optional[str] = None) -> dict:
    """Recherche par NOM de fichier, dans le périmètre autorisé."""
    async with connexion() as (client, base, sid):
        return await _chercher_ouvert(client, base, sid, motif, dossier)


_INTERDITS_NOM = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def nom_sur(nom: str, defaut: str = "fichier", longueur: int = 180) -> str:
    """Un nom que le serveur ACCEPTE, sans rien perdre du sens (17/09).

    Le titre d'un mémoire — « … Lots 11 Carrelage/Faïence et 12 Sols souples » —
    devenait « Faïence et 12 Sols souples.docx » : `basename` coupait à la barre
    oblique. Et « : ? * " < > | » valent « nom ou chemin illégal » (418) sur un
    partage lu depuis Windows. Les caractères interdits deviennent un tiret ;
    l'extension est gardée quand le nom est raccourci.
    """
    propre = _INTERDITS_NOM.sub(" - ", str(nom or ""))
    propre = re.sub(r"\s+", " ", propre).strip(" .-")
    if not propre or propre in (".", ".."):
        propre = defaut
    if len(propre) > longueur:
        racine, point, ext = propre.rpartition(".")
        propre = (racine[:longueur - len(ext) - 1].rstrip(" .-") + "." + ext) if point and 0 < len(ext) <= 5 else propre[:longueur].rstrip(" .-")
    return propre


async def _ecrire(envoyer) -> dict:
    """Une ÉCRITURE sur le serveur, rejouée UNE fois si la session est morte.

    Les lectures se réparent seules depuis le 17/09 (`_appel`) ; le dépôt, lui,
    parlait au serveur en direct : une session invalidée par DSM (codes 105, 106,
    107, 119) faisait échouer le dépôt qu'on venait de VALIDER. `envoyer(client,
    base, sid)` rend la réponse JSON de DSM.
    """
    from ingestion.connectors import synology as c

    async with connexion() as (client, base, sid):
        data = await envoyer(client, base, sid)
        code = (data.get("error") or {}).get("code", 0)
        if not data.get("success") and code in c._CODES_SESSION:
            neuf = await c._nouvelle_session(client, base, sid)
            if neuf:
                data = await envoyer(client, base, neuf)
        return data


async def creer_dossier(parent: str, nom: str) -> dict:
    """Crée UN dossier dans un dossier existant du périmètre. ÉCRITURE — validation.

    Rien n'est écrasé ni renommé : si un dossier de ce nom existe déjà (aux accents
    et à la casse près), c'est LUI qui est rendu, et on le dit. Jamais de création
    en cascade (`force_parent=false`) : un chemin mal deviné ne fabrique pas une
    arborescence parallèle sur le serveur de l'entreprise.
    """
    import json as _json
    import unicodedata
    from ingestion.connectors import synology as c

    vise = verifier(parent)
    propre = nom_sur(nom, defaut="")
    if not propre:
        raise NasRefuse("Donne un nom au dossier à créer.")
    if propre[0] in "#@" or propre.startswith("~$"):
        raise NasRefuse("Un nom de dossier ne commence pas par « # », « @ » ou « ~$ » : ce sont des dossiers du système.")

    def _nu(t):
        plat = unicodedata.normalize("NFD", str(t or "")).casefold()
        return " ".join("".join(ch for ch in plat if unicodedata.category(ch) != "Mn").split())

    async with connexion() as (client, base, sid):
        existants = (await _lister_ouvert(client, base, sid, vise, tout=True)).get("entrees") or []
    for e in existants:
        if _nu(e.get("nom")) == _nu(propre):
            if not e.get("dossier"):
                raise NasRefuse(f"Un FICHIER s'appelle déjà « {e.get('nom')} » dans ce dossier : choisis un autre nom.")
            return {"cree": False, "existait": True, "chemin": e.get("chemin"), "nom": e.get("nom"), "parent": vise}

    async def envoyer(client, base, sid):
        r = await client.get(f"{base}/webapi/entry.cgi", timeout=60, params={
            "api": "SYNO.FileStation.CreateFolder", "version": 2, "method": "create", "_sid": sid,
            "folder_path": _json.dumps([vise]), "name": _json.dumps([propre]), "force_parent": "false"})
        r.raise_for_status()
        return r.json()

    data = await _ecrire(envoyer)
    if not data.get("success"):
        code = (data.get("error") or {}).get("code", 0)
        return {"cree": False, "message": c._message(code, "SYNO.FileStation.CreateFolder.create")}
    dossiers = ((data.get("data") or {}).get("folders")) or []
    chemin = (dossiers[0].get("path") if dossiers else None) or posixpath.join(vise, propre)
    # Le catalogue en mémoire ne sera refait que dans l'heure : le dossier neuf y entre
    # tout de suite, sinon « dépose-le dans <ce dossier> » ne le trouverait pas par son nom.
    try:
        if isinstance(_CATALOGUE.get("entrees"), list):
            _CATALOGUE["entrees"].append({"nom": propre, "chemin": chemin, "dossier": True, "octets": None, "modifie": None})
    except Exception:  # noqa: BLE001 — un confort de recherche, jamais un motif d'échec
        pass
    logger.info("Dossier créé sur le NAS : %s", chemin)
    return {"cree": True, "chemin": chemin, "nom": propre, "parent": vise}


async def deposer(chemin_dossier: str, nom: str, contenu: bytes) -> dict:
    """Dépose un fichier sur le NAS. ÉCRITURE — passe par la validation.

    Aucun écrasement : `overwrite=false`. Un fichier remplacé sans qu'on l'ait
    demandé est une perte de données irrécupérable côté NAS, et personne ne la
    remarque avant d'en avoir besoin.
    """
    from ingestion.connectors import synology as c

    vise = verifier(chemin_dossier)
    propre = nom_sur(nom)

    # La session PARTAGÉE, comme tous les autres gestes — et rejouée une fois si
    # DSM l'a invalidée entre-temps (`_ecrire`).
    async def envoyer(client, base, sid):
        r = await client.post(
            f"{base}/webapi/entry.cgi",
            params={"api": "SYNO.FileStation.Upload", "version": 2,
                    "method": "upload", "_sid": sid},
            data={"path": vise, "create_parents": "false", "overwrite": "false"},
            files={"file": (propre, contenu)}, timeout=180)
        r.raise_for_status()
        return r.json()

    data = await _ecrire(envoyer)

    if not data.get("success"):
        code = (data.get("error") or {}).get("code", 0)
        # Le contexte NOMME la famille d'API : « Upload » seul faisait lire un code de
        # FICHIER dans le dictionnaire de l'AUTHENTIFICATION (408 = « mot de passe expiré »
        # au lieu de « ce dossier n'existe pas ») — le piège déjà payé sur les lectures.
        return {"depose": False, "code": code,
                "message": c._message(code, "SYNO.FileStation.Upload.upload")
                + (" — renomme le fichier" if code in (414, 1805) else "")}
    logger.info("Fichier déposé sur le NAS dans %s (%d octets)", vise, len(contenu))
    return {"depose": True, "dossier": vise, "nom": propre, "octets": len(contenu)}
