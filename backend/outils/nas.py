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

# « Parcours tout le serveur et fais-moi le schéma » est une demande légitime,
# et elle doit aboutir en UN appel. Les anciennes bornes (3 niveaux, 40
# dossiers) la faisaient échouer : l'arbre revenait tronqué, le modèle
# relançait avec d'autres paramètres, et le budget d'actions du tour y passait.
#
# Le serveur n'a pas d'équivalent du balayage global du Drive : chaque dossier
# coûte UNE requête. La vitesse vient donc du PARALLÉLISME — six listages de
# front dans la même session DSM — et le garde-fou est un budget de TEMPS en
# plus du plafond de dossiers : l'arbre rendu est celui qu'on a pu lire dans le
# délai, et il le dit.
MAX_PROFONDEUR = 20
MAX_DOSSIERS_ARBRE = 400
MAX_SCHEMA_CARACTERES = 9000
# 90 → 300 (01/09, règle de Noa : une recherche ne se bloque jamais en temps).
# À 90 s, un serveur chargé rendait un arbre partiel sur des demandes légitimes.
DELAI_ARBRE_S = 300
_LISTAGES_DE_FRONT = 6
MAX_LOT = 5


async def _enfants_dossiers(client, base, sid, chemin: str) -> list[dict]:
    from nas.acces import _lister_ouvert
    brut = await _lister_ouvert(client, base, sid, chemin)
    return [e for e in (brut.get("entrees") or []) if e.get("dossier")]


async def _resoudre(client, base, sid, chemin: str) -> str:
    """Un NOM (« Drive », « Compta/2026 ») vers son chemin réel sur le serveur.

    RELEVÉ EN PRODUCTION : « il y a combien de fichiers dans le dossier
    Drive ? » → le modèle demande « /Drive » → « ce dossier N'EXISTE PAS sur le
    NAS » — deux tours de suite, car le partage réel est /home/Drive. L'humain
    nomme le dossier qu'il a en tête, jamais son chemin de montage : exiger le
    chemin exact faisait échouer la formulation la plus naturelle. Le Drive de
    Symbiose a sa résolution par nom depuis le même constat ; le serveur de
    Duret ne l'avait pas.

    Résolution segment par segment, SOUS LES RACINES OUVERTES uniquement : le
    confinement ne bouge pas d'un pouce, on cherche seulement où vit le nom.
    Une racine illisible (partage mal configuré) est ignorée sans bloquer les
    autres. Quand ça échoue, le refus LISTE ce qui existe : c'est la différence
    entre une erreur et une piste.
    """
    from nas.acces import dossiers_autorises, normaliser, NasRefuse

    vise = normaliser(chemin)
    # Le chemin tel quel se liste ? C'est un vrai chemin, on ne cherche pas.
    try:
        await _enfants_dossiers(client, base, sid, vise)
        return vise
    except NasRefuse:
        raise                    # hors périmètre : la résolution ne contourne pas
    except Exception:  # noqa: BLE001 - inexistant : on cherche par nom
        pass

    segments = [s for s in vise.split("/") if s]
    if not segments:
        raise NasRefuse("Donne le nom ou le chemin du dossier.")
    racines = dossiers_autorises()

    # Premier segment : le nom d'une racine elle-même (« home »), sinon un
    # enfant direct d'une des racines lisibles — exact avant « contient ».
    #
    # L'ALIAS DE RACINE NE VAUT QUE SI ELLE SE LISTE. C'est le piège exact de
    # la production : « /Drive » était CONFIGURÉ comme racine mais n'existait
    # pas sur le NAS — le nom « Drive » retombait donc sur la racine fantôme,
    # et la résolution rendait le chemin même qui venait d'échouer, pendant que
    # le vrai /home/Drive attendait deux niveaux plus loin.
    courant = None
    for r in racines:
        if r.rsplit("/", 1)[-1].lower() == segments[0].lower():
            try:
                await _enfants_dossiers(client, base, sid, r)
                courant = r
                break
            except Exception:  # noqa: BLE001 - racine fantôme : on cherche ailleurs
                continue
    disponibles: list[str] = []
    if courant is None:
        for r in racines:
            try:
                enfants = await _enfants_dossiers(client, base, sid, r)
            except Exception:  # noqa: BLE001 - une racine fantôme ne bloque pas
                continue
            disponibles += [e.get("nom") or "" for e in enfants]
            exacts = [e for e in enfants
                      if (e.get("nom") or "").lower() == segments[0].lower()]
            contient = [e for e in enfants
                        if segments[0].lower() in (e.get("nom") or "").lower()]
            choisi = exacts or contient
            if choisi:
                courant = choisi[0]["chemin"]
                break
    if courant is None:
        raise NasRefuse(
            f"Aucun dossier « {segments[0]} » sous les racines ouvertes "
            f"({', '.join(racines)}). Dossiers présents : "
            f"{', '.join(sorted(set(d for d in disponibles if d))[:25])}. "
            "Reprends le nom EXACT dans cette liste.")

    # Segments suivants : contraints à leur parent — c'est le sens d'un chemin.
    for segment in segments[1:]:
        try:
            enfants = await _enfants_dossiers(client, base, sid, courant)
        except NasRefuse:
            raise
        except Exception as e:  # noqa: BLE001 - un niveau illisible se DIT
            raise NasRefuse(
                f"« {courant} » n'a pas pu être lu pendant la résolution : "
                f"{str(e)[:120]}")
        exacts = [e for e in enfants
                  if (e.get("nom") or "").lower() == segment.lower()]
        contient = [e for e in enfants
                    if segment.lower() in (e.get("nom") or "").lower()]
        choisi = exacts or contient
        if not choisi:
            noms = ", ".join(sorted((e.get("nom") or "") for e in enfants)[:25])
            raise NasRefuse(
                f"Aucun dossier « {segment} » dans {courant}. Dossiers "
                f"présents : {noms}. Reprends le nom EXACT dans cette liste.")
        courant = choisi[0]["chemin"]
    return courant


async def apercu(chemin: Optional[str] = None) -> dict:
    """Ce que contient un dossier, compté et classé — sans lister tout le détail.

    Répond en UN appel à « combien de dossiers dans /home/Drive », « qu'est-ce
    qu'il y a là-dedans », « c'est gros ? ». Avec les gestes élémentaires il
    fallait lister puis faire compter le modèle, qui se trompait d'autant plus
    que la liste était longue — compter n'est pas ce qu'un modèle fait de mieux.
    """
    from nas.acces import connexion, _lister_ouvert, dossiers_autorises, NasRefuse

    if not chemin:
        # AUCUN DOSSIER OUVERT n'est un refus, pas un serveur vide. Répondre
        # « 0 dossier et 0 fichier » se lisait comme « le serveur est vide »,
        # et le modèle le répétait à l'utilisateur.
        racines_ouvertes = dossiers_autorises()
        if not racines_ouvertes:
            raise NasRefuse(
                "Aucun dossier du serveur n'est ouvert à l'assistant. Un "
                "administrateur doit renseigner les partages à ouvrir. Ce n'est "
                "PAS un serveur vide : dis-le tel quel.")

    illisibles = []
    async with connexion() as (client, base, sid):
        if chemin:
            # Le chemin arrive presque toujours sous forme de NOM : c'est ce
            # qu'un humain dit, et donc ce que le modèle répète.
            chemin = await _resoudre(client, base, sid, chemin)
            racines = [await _lister_ouvert(client, base, sid, chemin)]
        else:
            # Sans chemin : l'inventaire des racines ouvertes, chacune résumée.
            # Une racine illisible ne doit pas effacer les autres — c'était le
            # cas, la première exception annulant tout l'aperçu.
            racines = []
            for d in racines_ouvertes:
                try:
                    racines.append(await _lister_ouvert(client, base, sid, d))
                except Exception as e:  # noqa: BLE001
                    illisibles.append({"chemin": d, "raison": str(e)[:120]})

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
            # LA TRONCATURE SE DÉDUIT, elle ne se croit pas sur parole. On
            # comparait le seul drapeau `tronque` : absent, il valait False, et
            # un dossier de 4 321 entrées était annoncé « 200, comptés et non
            # estimés ». Le total rendu par le serveur tranche mieux qu'un
            # drapeau qu'on peut oublier de poser.
            "tronque": bool(r.get("tronque")) or int(r.get("total") or 0) > len(entrees),
            # Ce que le SERVEUR annonce, quand il en dit plus que ce qu'il a
            # rendu : c'est la seule façon de savoir qu'on ne compte qu'une page.
            "total_reel": r.get("total"),
        })

    total_dossiers = sum(r["dossiers"] for r in resume)
    total_fichiers = sum(r["fichiers"] for r in resume)

    # UN COMPTE TRONQUÉ N'EST PAS UN COMPTE. Le listage s'arrête à 200 entrées ;
    # annoncer « 200 fichiers, comptés et non estimés » sur un dossier qui en
    # contient 4 321 est un mensonge, et c'est celui que le modèle répète. On le
    # dit, avec le total réel que le serveur nous a donné.
    tronques = [r for r in resume if r["tronque"]]
    if tronques:
        reels = ", ".join(f"{t['chemin']} ({t.get('total_reel')} entrées)"
                          for t in tronques if t.get("total_reel"))
        note = (f"Compte PARTIEL : {total_dossiers} dossier(s) et "
                f"{total_fichiers} fichier(s) sur la première page seulement. "
                f"Le serveur en annonce davantage : {reels}. "
                "Ne présente PAS ces nombres comme le total : descends dans un "
                "sous-dossier pour compter précisément.")
    else:
        note = (f"{total_dossiers} dossier(s) et {total_fichiers} fichier(s). "
                "Les nombres ci-dessus sont comptés, pas estimés : "
                "reprends-les tels quels.")

    if illisibles:
        note += (f" {len(illisibles)} dossier(s) n'ont pas pu être lus : "
                 + ", ".join(i["chemin"] for i in illisibles) + ".")

    return {"emplacements": resume, "illisibles": illisibles,
            "total_dossiers": total_dossiers, "total_fichiers": total_fichiers,
            "complet": not tronques and not illisibles,
            "note": note}


def _rendre_schema(racines: list[dict], profondeur_max: int) -> tuple[str, int]:
    """L'arbre en texte, prêt à afficher — et la profondeur réellement rendue.

    UN SCHÉMA, PAS UN JSON. Le résultat repart vers le modèle avec un plafond
    de caractères : un arbre en JSON verbeux se faisait couper au milieu, et le
    modèle relançait l'exploration « car le résultat précédent était tronqué »
    — c'est mot pour mot ce qu'il a répondu. Le texte indenté porte la même
    information pour un cinquième du poids, et se recopie tel quel dans une
    réponse.

    Si même le texte déborde, on RÉDUIT LA PROFONDEUR D'AFFICHAGE, jamais la
    vérité : les niveaux repliés sont comptés et annoncés, pas perdus.
    """
    def _ligne(n: dict) -> str:
        bouts = []
        if n.get("sous_dossiers_total"):
            bouts.append(f"{n['sous_dossiers_total']} dossiers")
        if n.get("fichiers"):
            bouts.append(f"{n['fichiers']} fichiers")
        if n.get("erreur"):
            bouts.append(n["erreur"])
        if n.get("tronque"):
            bouts.append("liste partielle")
        return (n.get("nom") or "?") + (f"  ({', '.join(bouts)})" if bouts else "")

    def _rendre(noeuds: list[dict], prefixe: str, niveau: int,
                limite: int, lignes: list[str]) -> int:
        """Rend un niveau ; renvoie le nombre de dossiers REPLIÉS (non montrés)."""
        replies = 0
        for i, n in enumerate(noeuds):
            dernier = i == len(noeuds) - 1
            lignes.append(prefixe + ("└─ " if dernier else "├─ ") + _ligne(n))
            enfants = n.get("enfants") or []
            if not enfants:
                continue
            if niveau + 1 >= limite:
                replies += n.get("sous_dossiers_total") or len(enfants)
                continue
            suite = prefixe + ("   " if dernier else "│  ")
            replies += _rendre(enfants, suite, niveau + 1, limite, lignes)
        return replies

    for limite in range(profondeur_max, 0, -1):
        lignes: list[str] = []
        replies = 0
        for r in racines:
            lignes.append(_ligne(r))
            replies += _rendre(r.get("enfants") or [], "", 1, limite, lignes)
        schema = "\n".join(lignes)
        if len(schema) <= MAX_SCHEMA_CARACTERES or limite == 1:
            if replies:
                schema += (f"\n… détail limité à {limite} niveau(x) : "
                           f"{replies} sous-dossier(s) repliés, comptés ci-dessus.")
            return schema, limite
    return "", 0


async def arborescence(chemin: Optional[str] = None, profondeur: int = 0) -> dict:
    """L'arbre — COMPLET si on ne précise rien — en UN appel.

    « Parcours tout le serveur et fais-moi le schéma » doit aboutir ICI, en
    une action. L'ancienne version exigeait un dossier de départ et s'arrêtait
    à trois niveaux et quarante dossiers : le modèle relançait avec d'autres
    paramètres jusqu'à épuiser son budget d'actions, sans jamais rendre le
    schéma.

    La descente se fait PAR NIVEAUX, six listages de front dans la même
    session DSM : c'est le parallélisme qui rend l'arbre complet abordable,
    chaque dossier coûtant une requête au serveur. Les plafonds — dossiers ET
    temps — rendent un arbre PARTIEL et le disent, jamais un arbre faux.

    Le résultat porte `schema` : l'arbre en texte. La couche skill le
    transforme en bloc d'écran mécanique (`skills/affichage.py`).
    """
    import asyncio
    import time as _t

    from nas.acces import connexion, _lister_ouvert, dossiers_autorises, NasRefuse

    debut = _t.monotonic()
    profondeur = min(int(profondeur), MAX_PROFONDEUR) if profondeur else MAX_PROFONDEUR
    profondeur = max(1, profondeur)

    if not chemin:
        chemins_racines = dossiers_autorises()
        if not chemins_racines:
            raise NasRefuse(
                "Aucun dossier du serveur n'est ouvert à l'assistant. Un "
                "administrateur doit renseigner les partages à ouvrir. Ce n'est "
                "PAS un serveur vide : dis-le tel quel.")

    partiel = False
    porte = asyncio.Semaphore(_LISTAGES_DE_FRONT)

    async with connexion() as (client, base, sid):
        if chemin:
            # Un NOM suffit : « Drive » se résout en /home/Drive.
            chemins_racines = [await _resoudre(client, base, sid, chemin)]
        racines = [{"nom": c, "chemin": c, "enfants": [], "fichiers": 0,
                    "octets": 0} for c in chemins_racines]
        par_chemin = {r["chemin"]: r for r in racines}
        total = len(racines)

        async def _lire(c: str):
            async with porte:
                try:
                    return c, await _lister_ouvert(client, base, sid, c)
                except Exception as e:  # noqa: BLE001 - trié par l'appelant
                    return c, e

        niveau_courant = [r["chemin"] for r in racines]
        for _niveau in range(profondeur):
            if not niveau_courant:
                break
            if total >= MAX_DOSSIERS_ARBRE or _t.monotonic() - debut > DELAI_ARBRE_S:
                partiel = True
                break
            resultats = await asyncio.gather(*[_lire(c) for c in niveau_courant])
            prochain: list[str] = []
            for c, brut in resultats:
                noeud = par_chemin[c]
                if isinstance(brut, NasRefuse):
                    # UN REFUS DE PÉRIMÈTRE N'EST PAS UN ARBRE VIDE. Sur la
                    # racine explicitement demandée, il remonte tel quel ;
                    # ailleurs il se lit dans le schéma, jamais comme « vide ».
                    if chemin and noeud in racines:
                        raise brut
                    noeud["erreur"] = "accès refusé (hors du périmètre autorisé)"
                    continue
                if isinstance(brut, Exception):
                    if chemin and noeud in racines:
                        raise brut
                    noeud["erreur"] = str(brut)[:120]
                    continue
                entrees = brut.get("entrees") or []
                dossiers = [e for e in entrees if e.get("dossier")]
                fichiers = [e for e in entrees if not e.get("dossier")]
                noeud["fichiers"] = len(fichiers)
                noeud["octets"] = sum(int(e.get("octets") or 0) for e in fichiers)
                noeud["tronque"] = (bool(brut.get("tronque"))
                                    or int(brut.get("total") or 0) > len(entrees))
                noeud["sous_dossiers_total"] = len(dossiers)
                for sd in sorted(dossiers,
                                 key=lambda d: (d.get("nom") or "").lower()):
                    enfant = {"nom": sd.get("nom"), "chemin": sd.get("chemin"),
                              "enfants": [], "fichiers": 0, "octets": 0}
                    noeud["enfants"].append(enfant)
                    par_chemin[sd["chemin"]] = enfant
                    prochain.append(sd["chemin"])
                    total += 1
            niveau_courant = prochain
        if niveau_courant:
            partiel = True

    schema, rendu = _rendre_schema(racines, profondeur)
    comptes_partiels = any(n.get("tronque") for n in par_chemin.values())
    sortie = {
        "schema": schema,
        "dossiers_total": total,
        "fichiers_total": sum(n.get("fichiers") or 0 for n in par_chemin.values()),
        "profondeur_affichee": rendu,
        "complet": not partiel and not comptes_partiels,
        "duree_s": round(_t.monotonic() - debut, 1),
    }
    if sortie["complet"]:
        sortie["note"] = (
            "ARBORESCENCE COMPLÈTE : tous les dossiers y sont, comptes exacts. "
            "Elle est déjà affichée à l'écran. Ne relance PAS "
            "l'exploration, il n'y a rien de plus à trouver.")
    else:
        morceaux = []
        if partiel:
            morceaux.append(
                f"plafond atteint ({MAX_DOSSIERS_ARBRE} dossiers ou "
                f"{DELAI_ARBRE_S} s) : des branches restent fermées")
        if comptes_partiels:
            morceaux.append("certains dossiers dépassent la page lue, leurs "
                            "comptes sont partiels")
        sortie["note"] = ("Arborescence rendue, mais " + " ; ".join(morceaux)
                          + ". Dis-le tel quel : ne présente pas ces nombres "
                            "comme exhaustifs.")
    return sortie


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
                # Le chemin EXISTE mais n'a pas pu être lu (trop volumineux,
                # format non pris en charge) : le message le dit. Relancer une
                # recherche DSM ne trouverait que ce même fichier, pour échouer
                # pareil — deux appels lents pour rien.
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


def _nom_avec_extension(nom: Optional[str], entete: dict) -> str:
    """Le nom du fichier déposé PORTE toujours son vrai format.

    RELEVÉ EN PRODUCTION : « appelle-le test 2 » → le modèle a transmis
    `nom="test 2"`, et le code l'utilisait tel quel. Le fichier est arrivé sur
    le serveur sans extension : un .docx parfaitement valide (ZIP correct,
    word/document.xml présent, 3 160 mots) que Windows ne savait pas ouvrir.
    Toute la chaîne avait fonctionné, et le résultat était inutilisable pour
    une raison qui n'a rien à voir avec son contenu.

    La même trace montre le modèle écrire tantôt « test 2 », tantôt
    « test 2.docx » : l'extension ne peut pas dépendre de son humeur. C'est au
    code de la garantir, puisque lui seul sait dans quel format le fichier a
    réellement été rendu.

    Une extension MENTEUSE est corrigée, pas conservée : un fichier nommé
    « rapport.pdf » qui contient un .docx ne s'ouvrira pas davantage. Un point
    qui ne désigne aucun format connu (« note.v2 ») n'est pas touché — ce n'est
    pas une extension, c'est une partie du nom.
    """
    from bureautique.modele import FORMATS

    fmt = (entete.get("format") or "docx").lower()
    final = (nom or "").strip() or f"{entete.get('titre') or 'document'}.{fmt}"
    racine, point, ext = final.rpartition(".")
    if point and ext.lower() == fmt:
        return final                      # déjà correcte
    if point and racine and ext.lower() in FORMATS:
        return f"{racine}.{fmt}"          # extension fausse : rectifiée
    return f"{final}.{fmt}"               # absente : ajoutée


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
    from nas.acces import connexion, deposer

    # UN PROPRIÉTAIRE VIDE N'EST PAS UN PROPRIÉTAIRE. `fiche()` compare
    # `proprietaire == f["proprietaire"]` : une chaîne vide ne correspondrait à
    # rien aujourd'hui, mais rien ne le garantit — et un document appartient à
    # quelqu'un, ou l'opération n'a pas lieu. On refuse ici, où c'est explicite.
    if not (proprietaire or "").strip():
        raise PermissionError(
            "Impossible de déposer un document sans compte identifié.")

    fiche = terminer(document_id, proprietaire)      # lève si inconnu ou vide
    chemin = chemin_fichier(document_id, proprietaire)
    if not chemin:
        raise FileNotFoundError("Le document a été finalisé mais son fichier est "
                                "introuvable. Recommence-le.")

    entete = fiche["entete"]
    final = _nom_avec_extension(nom, entete)
    with open(chemin, "rb") as f:
        contenu = f.read()

    # « Dépose-le dans Drive » doit suffire : le dossier se résout par NOM,
    # comme partout ailleurs — c'est au moment du dépôt que l'exigence du
    # chemin exact coûtait le plus cher, après tout le travail de rédaction.
    async with connexion() as (client, base, sid):
        dossier = await _resoudre(client, base, sid, dossier)

    depot = await deposer(dossier, final, contenu)
    # UN DÉPÔT RATÉ DOIT ÊTRE UN ÉCHEC, pas un dictionnaire optimiste.
    #
    # `deposer()` ne lève pas : elle rend `{"depose": False, "message": ...}`
    # quand le NAS refuse — dossier interdit, nom déjà pris, quota. On rendait
    # malgré tout « Document finalisé ET déposé sur le serveur », et comme
    # l'exécuteur ne voit qu'un dictionnaire, il concluait au succès. L'écran
    # affichait « action exécutée après validation », le modèle annonçait le
    # dépôt, et le fichier n'était nulle part.
    #
    # C'est exactement la panne déjà corrigée sur `ajouter_document` : une
    # fonction qui rend un compte rendu de succès sur un échec ment à tout ce
    # qui la lit ensuite, y compris à l'utilisateur.
    if not depot.get("depose"):
        raise RuntimeError(
            f"Le dépôt sur le serveur a ÉCHOUÉ : "
            f"{depot.get('message') or 'raison inconnue'}. Le document est bien "
            f"produit et reste téléchargeable, mais il n'est PAS sur le serveur. "
            f"Dis-le clairement.")
    return {"document_id": document_id, "titre": entete["titre"],
            "format": entete["format"], "octets": fiche["octets"],
            "elements": fiche["elements"], **depot,
            # Le début RÉEL du fichier déposé, pour l'aperçu dans le chat.
            "extrait": fiche.get("extrait") or "",
            "note": ("Document finalisé ET déposé sur le serveur. Montre-le "
                     "avec un bloc ```ui `doc_apercu` portant `titre`, "
                     "`format` et `extrait` (recopié TEL QUEL).")}


# ═══════════════════════════════════════════════════════════════════════════
#  LES PHOTOS D'UN CHANTIER, MONTRÉES DANS LE CHAT
# ═══════════════════════════════════════════════════════════════════════════
#
# « Montre-moi les photos de ce chantier » ne trouvait aucun geste : la
# recherche documentaire rend du texte, et `nas_ouvrir` refuse les formats non
# textuels. Or le nécessaire était déjà là, à un maillon près — le dépôt
# (`visuels/depot.py`) range n'importe quels octets sous une clé et les sert
# par `/api/visuels/{clé}` avec le jeton de session, et le bloc d'écran
# `visuel` sait afficher une planche téléchargeable. Il manquait le geste qui
# va CHERCHER les images et les dépose. C'est celui-ci.
#
# CE QU'IL NE FAIT PAS : sortir des dossiers autorisés (`dossiers_autorises`
# borne la recherche, comme pour tous les gestes du NAS), ni ramener autre
# chose que des images, ni télécharger un fichier énorme.

MAX_PHOTOS = 12
MAX_OCTETS_PHOTO = 12 * 1024 * 1024
_EXTENSIONS_IMAGE = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".gif")


async def photos(dossier: Optional[str] = None, motif: Optional[str] = None,
                 limite: int = 6) -> dict:
    """Les photos d'un dossier du NAS, rangées au dépôt et prêtes à l'écran."""
    from nas.acces import connexion, _chercher_ouvert, NasRefuse
    from ingestion.connectors import synology as c
    from visuels.depot import deposer_octets

    limite = max(1, min(int(limite or 6), MAX_PHOTOS))
    # Sans motif, on cherche les extensions d'image une à une : la recherche
    # DSM travaille sur un masque de nom, elle ne connaît pas les types.
    motifs = [motif] if motif else list(_EXTENSIONS_IMAGE)

    trouves, vus = [], set()
    async with connexion() as (client, base, sid):
        for m in motifs:
            if len(trouves) >= limite * 2:
                break
            try:
                res = await _chercher_ouvert(client, base, sid, m, dossier)
            except NasRefuse:
                raise
            except Exception as e:  # noqa: BLE001 — une racine muette n'annule pas le reste
                logger.warning("NAS : recherche de photos « %s » échouée : %s", m, e)
                continue
            for f in res.get("resultats") or []:
                chemin = f.get("chemin")
                if (not chemin or f.get("dossier") or chemin in vus
                        or not chemin.lower().endswith(_EXTENSIONS_IMAGE)):
                    continue
                vus.add(chemin)
                trouves.append(f)

        if not trouves:
            ou = f"« {dossier} »" if dossier else "les dossiers ouverts"
            return {
                "photos": [], "nombre": 0,
                "message": (f"Aucune image dans {ou}"
                            + (f" dont le nom contienne « {motif} »" if motif else "")
                            + ". Ce n'est pas une preuve qu'il n'y en a pas : elles "
                              "peuvent être ailleurs, ou hors du périmètre autorisé."),
            }

        images, trop_gros = [], 0
        for f in trouves:
            if len(images) >= limite:
                break
            try:
                octets = await c._telecharger(client, base, sid, f["chemin"])
                if not octets:
                    continue
                if len(octets) > MAX_OCTETS_PHOTO:
                    trop_gros += 1
                    continue
                cle = deposer_octets(octets, "image/jpeg")
                if cle:
                    images.append({"cle": cle, "legende": f.get("nom") or "photo",
                                   "chemin": f["chemin"]})
            except Exception as e:  # noqa: BLE001
                logger.info("NAS : photo « %s » non récupérée : %s", f.get("nom"), e)

    if not images:
        return {"photos": [], "nombre": 0,
                "message": ("Des images existent mais aucune n'a pu être "
                            "récupérée (format, taille ou droits).")}

    return {
        "photos": images,
        "nombre": len(images),
        "disponibles": len(trouves),
        "trop_volumineuses": trop_gros or None,
        "bloc_ui": {"type": "visuel",
                    "titre": (dossier or motif or "Photos du serveur")[:80],
                    "images": [{"cle": i["cle"], "legende": i["legende"]}
                               for i in images]},
    }
