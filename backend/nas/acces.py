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
from contextlib import asynccontextmanager
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


async def _lister_ouvert(client, base, sid, chemin: str) -> dict:
    """Liste un dossier dans une session DÉJÀ ouverte."""
    from ingestion.connectors import synology as c

    vise = verifier(chemin)
    data = await c._appel(client, base, "SYNO.FileStation.List", "list", 2,
                          sid=sid, folder_path=vise, limit=MAX_ENTREES,
                          additional='["size","time"]')

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
    brut = await c._telecharger(client, base, sid, vise)

    if not brut:
        return {"chemin": vise, "message": "Fichier introuvable ou vide sur le NAS."}
    nom = posixpath.basename(vise)
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
                   arret_au_premier: bool = False) -> tuple[list[dict], bool]:
    """Descend l'arborescence et rend les entrées retenues par `correspond`.

    `correspond(entree) -> bool` reçoit un dict `{nom, chemin, dossier, octets}`.
    Rend `(trouvés, complet)` : `complet` est faux dès qu'un plafond a mordu —
    l'appelant doit alors dire que l'absence n'est pas prouvée.
    """
    import time as _t

    debut = _t.monotonic()
    porte = asyncio.Semaphore(BALAYAGE_DE_FRONT)
    trouves: list[dict] = []
    vus: set = set()
    complet = True
    niveau = [r for r in racines if r]
    listes = 0

    async def _un(chemin: str) -> list[dict]:
        garde = _CACHE_LISTAGE.get(chemin)
        if garde and garde[0] > _t.monotonic():
            return garde[1]
        async with porte:
            garde = _CACHE_LISTAGE.get(chemin)      # un autre l'a peut-être lu pendant l'attente
            if garde and garde[0] > _t.monotonic():
                return garde[1]
            try:
                brut = await _lister_ouvert(client, base, sid, chemin)
            except Exception as e:  # noqa: BLE001 — un dossier illisible n'arrête pas le balayage
                logger.info("NAS : dossier ignoré pendant le balayage (%s) : %s",
                            chemin, str(e)[:100])
                return []
            entrees = brut.get("entrees") or []
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
                    suivant.append(chemin)
        niveau = suivant
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
CATALOGUE_DUREE_S = 3600
CATALOGUE_DELAI_S = 900
CATALOGUE_DOSSIERS_MAX = 60000
CATALOGUE_PROFONDEUR = 40
_CATALOGUE: dict = {"etat": "vide", "entrees": [], "construit_le": 0.0,
                    "complet": False, "en_cours": False}


async def construire_catalogue() -> dict:
    """Balaye tout le périmètre et garde le résultat en mémoire. Une seule
    construction à la fois : un second appel pendant la première n'en lance
    pas une autre, il rend l'état."""
    import time as _t

    if _CATALOGUE["en_cours"]:
        return _CATALOGUE
    racines = dossiers_autorises()
    if not racines:
        return _CATALOGUE
    _CATALOGUE["en_cours"] = True
    debut = _t.monotonic()
    try:
        async with connexion() as (client, base, sid):
            entrees, complet = await _balayer(
                client, base, sid, racines, lambda e: True,
                delai_s=CATALOGUE_DELAI_S, dossiers_max=CATALOGUE_DOSSIERS_MAX,
                profondeur=CATALOGUE_PROFONDEUR)
        _CATALOGUE.update({"etat": "pret" if complet else "partiel",
                           "entrees": entrees, "complet": complet,
                           "construit_le": _t.monotonic()})
        logger.info("NAS : catalogue %s — %d entrées en %.0f s",
                    _CATALOGUE["etat"], len(entrees), _t.monotonic() - debut)
    except Exception as e:  # noqa: BLE001 — un NAS injoignable ne casse pas le démarrage
        logger.warning("NAS : catalogue non construit : %s", str(e)[:160])
    finally:
        _CATALOGUE["en_cours"] = False
    return _CATALOGUE


def catalogue_pret() -> Optional[list]:
    """Les entrées du catalogue s'il est utilisable, sinon None — et dans ce
    cas la construction part en tâche de fond si rien ne tourne déjà."""
    import time as _t

    frais = (_CATALOGUE["etat"] in ("pret", "partiel")
             and _t.monotonic() - _CATALOGUE["construit_le"] < CATALOGUE_DUREE_S)
    if frais:
        return _CATALOGUE["entrees"]
    if not _CATALOGUE["en_cours"]:
        try:
            asyncio.get_running_loop().create_task(construire_catalogue())
        except RuntimeError:
            pass
    # Un catalogue PÉRIMÉ vaut mieux qu'aucun le temps de la reconstruction.
    return _CATALOGUE["entrees"] or None


async def demarrer_catalogue() -> None:
    """La tâche de fond : construire, puis reconstruire à chaque heure."""
    while True:
        await construire_catalogue()
        await asyncio.sleep(CATALOGUE_DUREE_S)


def _sans_accent_nas(texte: str) -> str:
    """Comparaison de noms indulgente aux accents et à la casse."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", (texte or "").lower())
                   if unicodedata.category(c) != "Mn")


async def _chercher_ouvert(client, base, sid, motif: str,
                           dossier: Optional[str] = None) -> dict:
    """Cherche par nom dans une session DÉJÀ ouverte."""
    from ingestion.connectors import synology as c

    motif = (motif or "").strip()
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
            return cible in _sans_accent_nas(e.get("nom") or "")

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


async def chercher(motif: str, dossier: Optional[str] = None) -> dict:
    """Recherche par NOM de fichier, dans le périmètre autorisé."""
    async with connexion() as (client, base, sid):
        return await _chercher_ouvert(client, base, sid, motif, dossier)


async def deposer(chemin_dossier: str, nom: str, contenu: bytes) -> dict:
    """Dépose un fichier sur le NAS. ÉCRITURE — passe par la validation.

    Aucun écrasement : `overwrite=false`. Un fichier remplacé sans qu'on l'ait
    demandé est une perte de données irrécupérable côté NAS, et personne ne la
    remarque avant d'en avoir besoin.
    """
    from ingestion.connectors import synology as c

    vise = verifier(chemin_dossier)
    propre = posixpath.basename((nom or "fichier").replace("\\", "/")) or "fichier"

    # La session PARTAGÉE, comme tous les autres gestes : le dépôt payait sa
    # propre résolution d'adresse et son propre login alors qu'une session
    # venait presque toujours d'être ouverte par le geste précédent.
    async with connexion() as (client, base, sid):
        r = await client.post(
            f"{base}/webapi/entry.cgi",
            params={"api": "SYNO.FileStation.Upload", "version": 2,
                    "method": "upload", "_sid": sid},
            data={"path": vise, "create_parents": "false", "overwrite": "false"},
            files={"file": (propre, contenu)}, timeout=180)
        r.raise_for_status()
        data = r.json()

    if not data.get("success"):
        code = (data.get("error") or {}).get("code", 0)
        return {"depose": False,
                "message": c._message(code, "Upload")
                + (" (un fichier de ce nom existe déjà : renomme-le)" if code == 1805 else "")}
    logger.info("Fichier déposé sur le NAS dans %s (%d octets)", vise, len(contenu))
    return {"depose": True, "dossier": vise, "nom": propre, "octets": len(contenu)}
