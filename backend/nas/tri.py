"""
CE QUE L'ASSISTANT APPREND DU NAS — le tri AVANT la lecture (15/09, Duret).

DEMANDE DE NOA : « l'enrichir via lecture du NAS c'est bien, mais c'est beaucoup
trop long et ça bouffe le serveur ». La synchronisation ouvrait TOUT ce que le
NAS contient — archives d'affaires terminées, photos de chantier, le même CCTP
type copié dans quarante affaires, PDF scannés passés à l'OCR page à page — et
chaque texte partait ensuite à l'analyse du modèle. Or le coût est à
l'OUVERTURE : faire lire un fichier à l'IA pour juger s'il est utile, c'est
déjà l'avoir payé. On trie donc sur ce qui ne coûte rien à lire : les noms.

TROIS FILTRES, du moins cher au plus cher :
  1. SANS IA — photos (pas de texte à apprendre), doublons (même nom, même
     taille : on n'en lit qu'un, le plus récent), fichiers plus vieux que
     `nas_tri_age_ans` (3 ans par défaut, 0 = aucune limite) ;
  2. L'IA JUGE LES DOSSIERS, pas les fichiers : leur chemin, leurs sous-
     dossiers, quelques noms de fichiers, leur date la plus récente. Par lots,
     du premier degré vers le bas : « apprendre », « à la demande »,
     « ignorer », ou « détailler » (ses sous-dossiers seront jugés à leur tour).
     Quelques dizaines d'appels au lieu de milliers. C'est une PROPOSITION :
     l'administrateur la valide dans Paramètres → Synchronisations ;
  3. LA LECTURE (connecteur `synology`) ne porte plus que sur « apprendre »,
     les affaires récentes d'abord ; un PDF scanné est remis à la NUIT, où
     l'OCR ne gêne personne.

« À la demande » : rien n'est appris d'avance, mais le chat ouvre toujours ce
dossier quand on le lui demande. « Ignorer » ne supprime rien : les documents
déjà importés restent (règle du 08/09, rien ne se supprime sans le mot).

Règles : réglage `nas_tri` = [{"chemin", "decision"}], la règle du chemin le
plus long l'emporte (comme `nas/niveaux.py`) ; sans règle, « apprendre » — le
comportement d'avant, tant qu'aucun tri n'est validé.

Fonctions pures d'abord (le banc les exécute), puis la proposition, asynchrone.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import re
import time
import unicodedata
from typing import Optional

logger = logging.getLogger("duret.nas.tri")

REGLAGE = "nas_tri"
REGLAGE_AGE = "nas_tri_age_ans"
DECISIONS = ("apprendre", "demande", "ignorer")
DECISION_DEFAUT = "apprendre"
MAX_REGLES = 2000

# Ce qui n'a pas de texte à apprendre : une photo de chantier se regarde, elle
# ne se lit pas. L'OCR d'une photo coûtait une minute de processeur pour trois
# mots. Le chat, lui, les montre toujours (`nas_photos`, `nas_ouvrir`).
EXT_SANS_TEXTE = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif", ".heic")

LOT_DOSSIERS = 40
PROFONDEUR_MAX = 4
APPELS_MAX = 80
EXEMPLES_PAR_DOSSIER = 6
FICHIER_PROPOSITION = "nas_tri_proposition.json"
FICHIER_OCR_DIFFERE = "nas_ocr_differe.json"


# ── Les règles ──────────────────────────────────────────────────────────────
def _nu(chemin: str) -> str:
    from nas.acces import normaliser
    c = unicodedata.normalize("NFKD", normaliser(chemin or ""))
    return "".join(ch for ch in c if not unicodedata.combining(ch)).lower().rstrip("/")


def lire_regles(brut) -> list[dict]:
    """Le réglage stocké (JSON) → règles propres. Une décision inconnue est
    ÉCARTÉE (pas ramenée à « ignorer ») : ici une faute ne ferme rien de grave,
    elle rend seulement le comportement par défaut."""
    from nas.acces import normaliser
    if isinstance(brut, str):
        try:
            brut = json.loads(brut) if brut.strip() else []
        except ValueError:
            logger.warning("Réglage %s illisible : aucun tri appliqué.", REGLAGE)
            return []
    regles: dict[str, dict] = {}
    for r in brut if isinstance(brut, list) else []:
        if not isinstance(r, dict):
            continue
        chemin = str(r.get("chemin") or "").strip()
        decision = str(r.get("decision") or "").strip().lower()
        if not chemin or chemin == "/" or decision not in DECISIONS:
            continue
        regles[_nu(chemin)] = {"chemin": normaliser(chemin), "decision": decision}
    return sorted(regles.values(), key=lambda r: _nu(r["chemin"]))[:MAX_REGLES]


def decision_du_chemin(chemin: str, regles: list[dict], defaut: str = DECISION_DEFAUT) -> str:
    """La décision d'un fichier ou d'un dossier : la règle du plus long chemin."""
    vise = _nu(chemin)
    retenue, longueur = None, -1
    for r in regles:
        base = _nu(r["chemin"])
        if (vise == base or vise.startswith(base + "/")) and len(base) > longueur:
            retenue, longueur = r["decision"], len(base)
    return retenue or defaut


# ── Filtre 1 : sans IA ──────────────────────────────────────────────────────
def ecarte_sans_ia(entree: dict, maintenant: float, age_ans: int) -> Optional[str]:
    """« photo » ou « ancien », ou None si le fichier passe. Fonction PURE."""
    nom = str(entree.get("nom") or entree.get("chemin") or "").lower()
    if nom.endswith(EXT_SANS_TEXTE):
        return "photo"
    if age_ans and age_ans > 0:
        try:
            modifie = float(entree.get("modifie") or 0)
        except (TypeError, ValueError):
            modifie = 0
        if modifie > 0 and maintenant - modifie > age_ans * 365.25 * 86400:
            return "ancien"
    return None


def doublons(fichiers: list[dict]) -> set:
    """Les chemins à NE PAS lire parce qu'une copie identique (même nom, même
    taille) est lue ailleurs — on garde la plus récente. Sans taille connue,
    rien n'est tenu pour doublon : deux « CCTP.pdf » ne sont pas le même."""
    groupes: dict[tuple, list[dict]] = {}
    for f in fichiers:
        taille = f.get("octets")
        try:
            taille = int(taille)
        except (TypeError, ValueError):
            continue
        if taille <= 0:
            continue
        nom = str(f.get("nom") or str(f.get("chemin") or "").rsplit("/", 1)[-1]).strip().lower()
        groupes.setdefault((nom, taille), []).append(f)
    ecartes = set()
    for copies in groupes.values():
        if len(copies) < 2:
            continue
        copies.sort(key=lambda f: (float(f.get("modifie") or 0), str(f.get("chemin"))), reverse=True)
        ecartes.update(str(c["chemin"]) for c in copies[1:])
    return ecartes


# ── Filtre 2 : ce que l'IA voit d'un dossier ───────────────────────────────
def resumer_dossiers(entrees: list[dict]) -> dict:
    """chemin → {fichiers (total dessous), sous_dossiers (directs), exemples,
    annee (la plus récente dessous)}. Une seule passe sur le catalogue."""
    dossiers: dict[str, dict] = {}

    def fiche(chemin: str) -> dict:
        return dossiers.setdefault(chemin, {"fichiers": 0, "sous_dossiers": set(), "exemples": [],
                                            "modifie": 0.0})

    for e in entrees:
        chemin = str(e.get("chemin") or "")
        if not chemin or "/" not in chemin.strip("/"):
            continue
        parent = chemin.rsplit("/", 1)[0] or "/"
        if e.get("dossier"):
            fiche(chemin)
            fiche(parent)["sous_dossiers"].add(chemin)
            continue
        d = fiche(parent)
        if len(d["exemples"]) < EXEMPLES_PAR_DOSSIER:
            d["exemples"].append(str(e.get("nom") or chemin.rsplit("/", 1)[-1]))
        try:
            m = float(e.get("modifie") or 0)
        except (TypeError, ValueError):
            m = 0
        # Le compte et la date remontent à TOUS les ancêtres.
        ancetre = parent
        while ancetre and ancetre != "/":
            a = fiche(ancetre)
            a["fichiers"] += 1
            a["modifie"] = max(a["modifie"], m)
            ancetre = ancetre.rsplit("/", 1)[0]
    for d in dossiers.values():
        d["sous_dossiers"] = sorted(d["sous_dossiers"])
        d["annee"] = time.gmtime(d["modifie"]).tm_year if d["modifie"] else None
    return dossiers


def consigne(lot: list[tuple[str, dict]], metier: str = "") -> str:
    """Le prompt d'un lot de dossiers."""
    lignes = []
    for chemin, d in lot:
        lignes.append(json.dumps({
            "chemin": chemin, "fichiers": d["fichiers"], "sous_dossiers": len(d["sous_dossiers"]),
            "noms_de_sous_dossiers": [s.rsplit("/", 1)[-1] for s in d["sous_dossiers"][:8]],
            "exemples_de_fichiers": d["exemples"], "annee_la_plus_recente": d["annee"],
        }, ensure_ascii=False))
    return (
        "Tu tries le serveur de fichiers d'une entreprise " + (metier or "du BTP")
        + " AVANT qu'un assistant n'en apprenne le contenu. Lire un fichier coûte cher : "
        "on ne veut apprendre que ce qui aidera à répondre aux questions de l'équipe "
        "(appels d'offres, CCTP, DCE, mémoires techniques, devis, procédures, modèles, "
        "affaires en cours ou récentes).\n\n"
        "Pour CHAQUE dossier ci-dessous, choisis UNE décision d'après son chemin, ses noms "
        "de sous-dossiers et ses exemples de fichiers :\n"
        "- \"apprendre\" : son contenu est utile à connaître d'avance ;\n"
        "- \"demande\" : utile de temps en temps, mais pas à apprendre d'avance (archives "
        "anciennes, comptabilité, administratif courant) — l'assistant l'ouvrira si on le lui demande ;\n"
        "- \"ignorer\" : rien à apprendre (photos, plans DWG seuls, sauvegardes, corbeille, "
        "doublons, dossiers personnels, logiciels) ;\n"
        "- \"detailler\" : le dossier mélange des choses utiles et inutiles ; ses sous-dossiers "
        "seront jugés un par un (seulement s'il en a).\n"
        "Dans le doute entre apprendre et demande, choisis demande. Ne détaille pas un dossier "
        "sans sous-dossier.\n\n"
        "DOSSIERS (un par ligne, JSON) :\n" + "\n".join(lignes) + "\n\n"
        "Réponds par un objet JSON SEUL : "
        "{\"decisions\": [{\"chemin\": \"<chemin exact>\", \"decision\": \"apprendre|demande|ignorer|detailler\", "
        "\"raison\": \"<quelques mots>\"}]}"
    )


def lire_decisions(brut, lot_chemins: list[str]) -> dict:
    """Le verdict d'un lot → {chemin: (decision, raison)}. Un chemin absent du
    lot est ignoré (le modèle ne crée pas de dossier) ; un dossier que le modèle
    a oublié ne reçoit rien (il gardera le comportement par défaut)."""
    texte = brut if isinstance(brut, str) else str(brut or "")
    trouve = re.search(r"\{.*\}", texte, re.S)
    if not trouve:
        return {}
    try:
        d = json.loads(trouve.group(0))
    except ValueError:
        return {}
    permis = {c: c for c in lot_chemins}
    permis_nus = {_nu(c): c for c in lot_chemins}
    sortie = {}
    for item in (d.get("decisions") if isinstance(d, dict) else None) or []:
        if not isinstance(item, dict):
            continue
        chemin = str(item.get("chemin") or "").strip()
        vrai = permis.get(chemin) or permis_nus.get(_nu(chemin))
        decision = str(item.get("decision") or "").strip().lower().replace("é", "e")
        if decision == "a la demande":
            decision = "demande"
        if not vrai or decision not in DECISIONS + ("detailler",):
            continue
        sortie[vrai] = (decision, str(item.get("raison") or "").strip()[:160])
    return sortie


def estimer(entrees: list[dict], regles: list[dict], age_ans: int, maintenant: float) -> dict:
    """Combien de fichiers seraient lus, laissés à la demande, ignorés, écartés
    sans IA — sur le catalogue, sans rien ouvrir. Sert l'écran."""
    from ingestion.parsers import famille
    fichiers = [e for e in entrees if not e.get("dossier") and e.get("chemin")]
    compte = {"a_lire": 0, "demande": 0, "ignorer": 0, "photo": 0, "ancien": 0,
              "doublon": 0, "format_non_lu": 0}
    en_double = doublons(fichiers)
    for f in fichiers:
        decision = decision_du_chemin(f["chemin"], regles)
        if decision != "apprendre":
            compte[decision] += 1
            continue
        nom = str(f.get("nom") or f["chemin"].rsplit("/", 1)[-1])
        if famille(nom) is None:
            compte["format_non_lu"] += 1
            continue
        raison = ecarte_sans_ia(f, maintenant, age_ans)
        if raison:
            compte[raison] += 1
            continue
        if f["chemin"] in en_double:
            compte["doublon"] += 1
            continue
        compte["a_lire"] += 1
    compte["total"] = len(fichiers)
    return compte


# ── La configuration en vigueur ────────────────────────────────────────────
_MEMO: dict = {"brut": None, "regles": []}


def regles() -> list[dict]:
    try:
        from llm.reglages import texte
        brut = texte(REGLAGE)
    except Exception:  # noqa: BLE001 — sans réglages lisibles, aucun tri
        return []
    if brut != _MEMO["brut"]:
        _MEMO.update(brut=brut, regles=lire_regles(brut))
    return _MEMO["regles"]


def age_ans() -> int:
    try:
        from llm.reglages import texte
        brut = texte(REGLAGE_AGE)
    except Exception:  # noqa: BLE001
        brut = ""
    if not brut:
        from config import settings
        return int(getattr(settings, "nas_tri_age_ans", 3) or 0)
    try:
        return max(0, min(50, int(brut)))
    except ValueError:
        return 3


def fenetre_de_nuit(heure: Optional[int] = None) -> bool:
    """L'OCR des PDF scannés ne tourne que la nuit (heure de Paris)."""
    from config import settings
    if heure is None:
        from datetime import datetime
        try:
            from zoneinfo import ZoneInfo
            heure = datetime.now(ZoneInfo("Europe/Paris")).hour
        except Exception:  # noqa: BLE001
            heure = datetime.now().hour
    debut = int(getattr(settings, "nas_ocr_nuit_debut", 21))
    fin = int(getattr(settings, "nas_ocr_nuit_fin", 6))
    return (heure >= debut or heure < fin) if debut > fin else (debut <= heure < fin)


# ── Les fichiers sur le disque (volume des documents) ──────────────────────
def _fichier(nom: str) -> pathlib.Path:
    return pathlib.Path(os.environ.get("DOCUMENTS_DIR", "/tmp/duret-documents")) / nom


def lire_json(nom: str, defaut):
    try:
        return json.loads(_fichier(nom).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defaut


def ecrire_json(nom: str, contenu) -> None:
    try:
        f = _fichier(nom)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(contenu, ensure_ascii=False), encoding="utf-8")
    except OSError as e:  # noqa: BLE001
        logger.warning("NAS : %s non écrit : %s", nom, e)


# ── La proposition de l'IA ──────────────────────────────────────────────────
_ETAT: dict = {"en_cours": False}


def etat_proposition() -> dict:
    return {**lire_json(FICHIER_PROPOSITION, {}), "en_cours": _ETAT.get("en_cours", False),
            "avancement": _ETAT.get("avancement")}


async def proposer(lance_par: str = "") -> dict:
    """Fait juger l'arborescence du NAS par le modèle, du premier degré vers le
    bas, et range la PROPOSITION (jamais appliquée seule)."""
    if _ETAT.get("en_cours"):
        return etat_proposition()
    _ETAT.update(en_cours=True, avancement="je relève l'arborescence du NAS")
    try:
        return await _proposer(lance_par)
    except Exception as e:  # noqa: BLE001 — une proposition ratée se DIT
        logger.warning("NAS : proposition de tri impossible : %s", e)
        ecrire_json(FICHIER_PROPOSITION, {**lire_json(FICHIER_PROPOSITION, {}),
                                          "erreur": str(e)[:300], "date": time.time()})
        return etat_proposition()
    finally:
        _ETAT.update(en_cours=False, avancement=None)


async def _proposer(lance_par: str) -> dict:
    from langchain_core.messages import HumanMessage
    from llm.router import LLMTier, get_llm
    from nas import acces
    from security.lecteur import en_systeme

    with en_systeme():
        entrees, complet = await acces.catalogue_attendu()
    racines = acces.dossiers_autorises()
    resume = resumer_dossiers(entrees)
    a_juger = sorted({s for r in racines for s in (resume.get(r) or {}).get("sous_dossiers", [])})
    if not a_juger:
        a_juger = sorted(c for c in resume if c.count("/") == 2)
    decisions: dict[str, dict] = {}
    appels = 0
    profondeur = 0
    llm = get_llm(LLMTier.STANDARD)
    while a_juger and profondeur < PROFONDEUR_MAX and appels < APPELS_MAX:
        suivants: list[str] = []
        for i in range(0, len(a_juger), LOT_DOSSIERS):
            if appels >= APPELS_MAX:
                break
            lot = [(c, resume[c]) for c in a_juger[i:i + LOT_DOSSIERS] if c in resume]
            if not lot:
                continue
            _ETAT["avancement"] = (f"je fais juger les dossiers de degré {profondeur + 1} · "
                                   f"{len(decisions)} jugé(s), {appels} appel(s)")
            appels += 1
            try:
                reponse = await llm.ainvoke([HumanMessage(content=consigne(lot))])
                verdict = lire_decisions(reponse.content, [c for c, _ in lot])
            except Exception as e:  # noqa: BLE001 — un lot raté ne décide rien
                logger.info("NAS : lot de tri non jugé (%s)", str(e)[:120])
                verdict = {}
            for chemin, d in lot:
                decision, raison = verdict.get(chemin, (None, ""))
                if decision == "detailler" and d["sous_dossiers"] and profondeur + 1 < PROFONDEUR_MAX:
                    suivants.extend(d["sous_dossiers"])
                    continue
                if decision == "detailler":
                    decision, raison = "apprendre", raison or "à détailler, sans sous-dossier"
                if decision in DECISIONS:
                    decisions[chemin] = {"chemin": chemin, "decision": decision, "raison": raison,
                                         "fichiers": d["fichiers"], "annee": d["annee"],
                                         "degre": profondeur + 1}
        a_juger = sorted(set(suivants))
        profondeur += 1

    # TOUT ce qui a été jugé, dans l'ordre de l'arborescence : l'administrateur
    # relit chaque verdict, même celui qui répète son parent (le retirer
    # l'aurait caché à la relecture).
    propres = [decisions[c] for c in sorted(decisions, key=_nu)]
    proposition = {"date": time.time(), "lance_par": lance_par, "appels": appels,
                   "catalogue_complet": bool(complet), "non_juges": len(a_juger),
                   "dossiers": propres, "erreur": None,
                   "estimation": estimer(entrees, lire_regles(propres), age_ans(), time.time())}
    ecrire_json(FICHIER_PROPOSITION, proposition)
    logger.info("NAS : tri proposé — %d règle(s) en %d appel(s)", len(propres), appels)
    return etat_proposition()


# ── L'OCR remis à la nuit ───────────────────────────────────────────────────
def ocr_differe() -> dict:
    """chemin → date de modification des PDF scannés à passer à l'OCR la nuit."""
    brut = lire_json(FICHIER_OCR_DIFFERE, {})
    return brut if isinstance(brut, dict) else {}


def ecrire_ocr_differe(d: dict) -> None:
    ecrire_json(FICHIER_OCR_DIFFERE, d)


async def boucle_de_nuit() -> None:
    """Chaque quart d'heure : la nuit, s'il reste des scans remis à plus tard
    et qu'aucune synchronisation ne tourne, en lancer une (qui, la nuit, fait
    l'OCR). Une nuit = un lancement au plus."""
    import asyncio
    derniere = None
    await asyncio.sleep(120)
    while True:
        try:
            aujourd_hui = time.strftime("%Y-%m-%d", time.localtime(time.time() - 12 * 3600))
            if fenetre_de_nuit() and ocr_differe() and derniere != aujourd_hui:
                from routers.ingestion import CONNECTEURS, _executer_sync, _ouvrir_sync
                sync_id = await _ouvrir_sync("synology", None, "nuit (OCR des scans)")
                if sync_id is not None:
                    derniere = aujourd_hui
                    logger.info("NAS : passage de nuit — %d scan(s) à lire", len(ocr_differe()))
                    await _executer_sync("synology", CONNECTEURS["synology"][1], None, sync_id)
        except Exception as e:  # noqa: BLE001 — la boucle ne meurt jamais
            logger.warning("NAS : passage de nuit impossible : %s", e)
        await asyncio.sleep(900)


# ── L'INTÉGRATION CONTINUE : un palier toutes les 10 minutes (15/09) ───────
# Noa : « il faudrait qu'il intègre tous les docs qu'il a le temps de faire en
# 10 min, toutes les 10 min ; là je crois qu'il s'arrête si mon PC se met en
# veille ». La synchronisation tourne sur le SERVEUR, mais elle ne partait que
# d'un clic, et un redéploiement l'arrêtait pour de bon. Désormais le serveur
# lance lui-même un palier (lecture bornée dans le temps) à chaque cycle, tant
# qu'il reste à lire. Chaque fichier lu est rangé en base aussitôt : rien
# n'attend la fin d'un palier pour être « intégré ».
REGLAGE_CONTINU = "nas_integration_continue"
_CONTINU = {"prochain": None, "dernier": None, "catalogue_vu": None, "rien_a_lire": False}


def integration_continue_active() -> bool:
    from llm.reglages import valeur
    return (valeur(REGLAGE_CONTINU) or "active").strip().lower() != "desactivee"


def etat_continu() -> dict:
    return {"active": integration_continue_active(),
            "prochain": _CONTINU["prochain"], "dernier": _CONTINU["dernier"],
            "rien_a_lire": _CONTINU["rien_a_lire"]}


async def palier_si_du(maintenant: Optional[float] = None) -> Optional[dict]:
    """Lance UN palier si c'est l'heure, si rien ne tourne et s'il y a à lire.
    Rend le résultat du palier, ou None s'il n'a pas eu lieu."""
    from config import settings
    from nas import acces
    maintenant = maintenant or time.time()
    cycle_s = max(2, int(getattr(settings, "nas_cycle_minutes", 10) or 10)) * 60
    if not integration_continue_active():
        _CONTINU["prochain"] = None
        return None
    if _CONTINU["prochain"] and maintenant < _CONTINU["prochain"]:
        return None
    # RIEN À LIRE LA DERNIÈRE FOIS, ET LE NAS N'A PAS ÉTÉ RELEVÉ DEPUIS : on
    # n'ouvre pas une ligne de synchronisation toutes les dix minutes pour
    # constater la même chose. Le catalogue se rafraîchit toutes les heures.
    construit = acces._CATALOGUE.get("construit_le")
    # La nuit ouvre ce que le jour remettait (scans, fichiers lourds) : un
    # changement de fenêtre relance la lecture même sans nouveau relevé.
    nuit = fenetre_de_nuit()
    if _CONTINU.get("nuit") is not None and _CONTINU.get("nuit") != nuit:
        _CONTINU["rien_a_lire"] = False
    _CONTINU["nuit"] = nuit
    if _CONTINU["rien_a_lire"] and construit == _CONTINU["catalogue_vu"]:
        _CONTINU["prochain"] = maintenant + cycle_s
        return None
    from routers.ingestion import CONNECTEURS, _SYNCS, _executer_sync, _ouvrir_sync
    sync_id = await _ouvrir_sync("synology", None, "palier automatique")
    _CONTINU["prochain"] = maintenant + cycle_s
    if sync_id is None:
        return None                           # une synchro tourne déjà : elle continue
    budget = max(1, int(getattr(settings, "nas_palier_lecture_minutes", 8) or 8)) * 60
    _CONTINU["catalogue_vu"] = construit
    await _executer_sync("synology", CONNECTEURS["synology"][1], None, sync_id, budget_s=budget)
    resultat = (_SYNCS.get("synology") or {}).get("resultat") or {}
    _CONTINU["dernier"] = time.time()
    _CONTINU["rien_a_lire"] = not resultat.get("ouverts") and not resultat.get("reste_a_lire")
    _CONTINU["catalogue_vu"] = acces._CATALOGUE.get("construit_le")
    return resultat


async def boucle_continue() -> None:
    """Chaque minute, regarde s'il est l'heure d'un palier. Ne meurt jamais."""
    import asyncio
    await asyncio.sleep(180)                 # le catalogue du NAS se construit d'abord
    while True:
        try:
            await palier_si_du()
        except Exception as e:  # noqa: BLE001
            logger.warning("NAS : palier automatique impossible : %s", e)
        await asyncio.sleep(60)
