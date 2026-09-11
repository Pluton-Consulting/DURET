"""
Enrichissement DOCUMENTAIRE — distiller les documents ingérés en connaissances.

POURQUOI. La campagne d'enrichissement historique (`enrichissement.py`) ne lit
que le COURRIER : les milliers de documents du socle documentaire (Drive d'un
côté, NAS de l'autre) alimentaient la recherche mais jamais le savoir distillé.
Relevé le 30/08 : « fais un Word avec tout ce que tu sais sur l'entreprise »
rendait quatre pages maigres, bâties sur le seul inventaire tiré des mails.

CE QUE FAIT CETTE CAMPAGNE. Elle relit les documents DÉJÀ INGÉRÉS (la table
`documents` — lecture seule par construction : rien n'est retéléchargé, rien
n'est modifié à la source), les regroupe par NIVEAU DE CONFIDENTIALITÉ, et
fait distiller chaque groupe par le modèle, comme la campagne mail. Les
connaissances héritent du niveau de leur groupe.

LE NIVEAU EST CELUI DES ACCÈS RÉELS, pas d'un réglage global. Demande de Noa :
une information tirée d'un fichier que seule la direction peut ouvrir ne doit
pas ressortir à tout le monde. Le module client `learning/acces_docs.py`
interroge les PARTAGES du socle documentaire (qui a accès à ce fichier, par
adresse e-mail) et les traduit en niveau de l'échelle maison
(`security/acces.py`). Quand il ne sait pas répondre — fichier disparu,
partage illisible, socle sans ACL — le niveau STOCKÉ à l'ingestion fait foi,
et en dernier recours le plus restrictif : une erreur ne doit jamais OUVRIR
un accès.

Même discipline que la campagne mail : anonymisation avant l'appel (elle
respecte l'interrupteur des Paramètres), modèle principal exigé par défaut,
état consultable, aucune écriture hors de notre propre mémoire.

ELLE OUVRE LE STOCKAGE AVANT DE LE LIRE (11/09). Relevé de Noa chez Duret :
« enrichir le NAS ne marche pas, alors qu'il devrait ouvrir tous les fichiers
du NAS pour apprendre de tout et faire des skills en auto ». La campagne ne
relisait que ce qu'une synchronisation PASSÉE avait laissé en base — et celle
du NAS partait d'une racine fantôme, donc rien : « aucun document ingéré ».
Désormais, trois temps, comme la campagne des mails :
  1. COLLECTE    la synchronisation du stockage de CE client
                 (`classement.source.CONNECTEUR`) ouvre chaque fichier lisible
                 et le range en mémoire — par la même porte que le bouton, donc
                 la carte du connecteur montre l'avancement ;
  2. ANALYSE     tout le corpus, par lots à la mesure de la fenêtre — plus de
                 plafond à trente appels par niveau (règle du 01/09 : jamais
                 bloqué en quantité ; le seul garde est l'emballement) ;
  3. ÉCRITURE    connaissances et manières de faire au niveau du fichier, et
                 les tâches qui reviennent en BROUILLONS de skills, désactivés
                 jusqu'à relecture dans l'onglet Skills — du code écrit par un
                 modèle ne s'exécute jamais sans qu'un humain l'ait lu.
"""
from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger("duret.learning.enrichissement_docs")

# Ce que la campagne relit : les documents du socle documentaire, quel que
# soit le connecteur qui les a apportés. Les mails ont leur propre campagne.
SOURCES_DOCUMENTS = ("drive", "nas", "document")

# Un document démesuré n'apporte pas plus de savoir distillé que son début —
# et il faut bien borner ce qu'un seul fichier peut coûter en fenêtre.
MAX_CARS_PAR_DOCUMENT = 12000

# LE SEUL GARDE : l'emballement. Deux mille appels d'analyse, c'est un stockage
# de plusieurs dizaines de milliers de documents — au-delà, quelque chose
# tourne en rond, et la campagne le DIT au lieu de continuer à payer.
MAX_APPELS_CAMPAGNE = 2000

INVITE_DOCS = """Tu relis un LOT DE DOCUMENTS internes de l'entreprise (contrats,
devis, comptes rendus, procédures, pièces de dossier). Ton but n'est pas de les
résumer, mais d'en tirer ce qui resservira PLUS TARD, sur d'autres dossiers.

Retiens :
- "connaissances" : un fait durable sur l'entreprise (un tarif, un fournisseur
  habituel, une règle interne, une contrainte technique, un équipement, une
  offre, un partenaire, une garantie pratiquée).
- "procedures" : une manière de faire qui revient (comment un devis est
  structuré, comment un chantier est réceptionné, dans quel ordre les pièces
  d'un dossier sont montées).
- "competences" : une tâche AUTOMATISABLE que ces documents montrent revenir
  souvent, c'est-à-dire un calcul ou une transformation déterministe (un métré,
  un total de lots, une conversion d'unités, un contrôle de pièces
  obligatoires). N'en propose que si c'est vraiment reproductible.

IGNORE : ce qui ne vaut que pour un dossier précis (un montant isolé, une date
de rendez-vous), les mentions légales génériques, les documents sans contenu
métier. Il est normal qu'un lot ne donne rien.
N'INVENTE RIEN. Les balises masquées ([PER_1], [MONTANT_2]...) restent telles quelles.

Réponds par un objet JSON seul :
{{"connaissances": [{{"titre": "...", "contenu": "..."}}],
  "procedures":    [{{"titre": "...", "contenu": "..."}}],
  "competences":   [{{"nom": "nom_en_snake_case", "description": "...", "entrees": "..."}}]}}

DOCUMENTS (chacun précédé de son nom de fichier) :
{corpus}"""

_ETAT: dict = {"en_cours": False, "phase": "jamais lancée", "lance_par": None,
               "debut": None, "fin": None, "stockage": None, "collecte": None,
               "documents": 0, "groupes": {}, "appels_prevus": 0,
               "appels_analyse": 0, "connaissances": 0, "procedures": 0,
               "deja_connues": 0, "skills": [], "modele": None, "echecs": []}


def etat() -> dict:
    sortie = dict(_ETAT)
    sortie["echecs"] = list(_ETAT["echecs"])[-12:]
    sortie["groupes"] = dict(_ETAT["groupes"])
    sortie["skills"] = list(_ETAT["skills"])
    if sortie.get("stockage") is None:
        sortie["stockage"] = _stockage()[1]
    return sortie


def _stockage() -> tuple:
    """(connecteur, nom lisible) du stockage de CE client — ou (None, …) si le
    module client ne le déclare pas (la collecte est alors sautée, et dite)."""
    try:
        from classement import source
        return (getattr(source, "CONNECTEUR", None),
                getattr(source, "NOM_STOCKAGE", None) or "stockage documentaire")
    except Exception:  # noqa: BLE001 — sans module client, on relit ce qui est en base
        return None, "stockage documentaire"


def _resume_collecte(r: dict) -> str:
    """Une ligne lisible du bilan de synchronisation (clés propres à chaque
    connecteur : on ne présume que des compteurs)."""
    res = (r or {}).get("resultat") or {}
    morceaux = [f"{v} {k.replace('_', ' ')}" for k, v in res.items()
                if isinstance(v, (int, float)) and not isinstance(v, bool) and v]
    texte = " · ".join(morceaux) or "aucun compteur"
    if res.get("racines_introuvables"):
        texte += f" · dossier(s) introuvable(s) sur le serveur : {res['racines_introuvables']}"
    return texte


def _lots(textes: list[str], budget: int) -> list[list[str]]:
    """Regroupe des textes en lots tenant dans la fenêtre — coupe au BUDGET."""
    lots: list[list[str]] = []
    courant: list[str] = []
    taille = 0
    for t in textes:
        if courant and taille + len(t) > budget:
            lots.append(courant)
            courant, taille = [], 0
        courant.append(t)
        taille += len(t)
    if courant:
        lots.append(courant)
    return lots


async def _documents_assembles(sources: tuple) -> list[dict]:
    """Les documents ingérés, rassemblés depuis leurs morceaux (chunks)."""
    from database.connection import get_db

    async with get_db() as conn:
        lignes = await conn.fetch(
            """SELECT source_id, source_type, source_filename, access_level,
                      content, chunk_index
               FROM documents WHERE source_type = ANY($1::text[])
               ORDER BY source_id, chunk_index""",
            list(sources))
    docs: dict[str, dict] = {}
    for l in lignes:
        cle = str(l["source_id"])
        d = docs.setdefault(cle, {"source_id": cle, "source_type": l["source_type"],
                                  "nom": l["source_filename"] or cle,
                                  "acces_stocke": l["access_level"] or "all",
                                  "morceaux": []})
        if sum(len(m) for m in d["morceaux"]) < MAX_CARS_PAR_DOCUMENT:
            d["morceaux"].append(l["content"] or "")
    sortie = []
    for d in docs.values():
        d["texte"] = "\n".join(d.pop("morceaux"))[:MAX_CARS_PAR_DOCUMENT]
        if d["texte"].strip():
            sortie.append(d)
    return sortie


async def _classer(docs: list[dict]) -> dict[str, list[dict]]:
    """Chaque document rejoint son niveau de confidentialité RÉEL.

    `acces_docs.niveau_reel` (module client) lit les partages du socle
    documentaire ; à défaut, le niveau stocké à l'ingestion. Un niveau hors
    échelle retombe sur le plus restrictif : une faute ne doit jamais ouvrir.
    """
    from security.acces import NIVEAUX

    try:
        from learning import acces_docs
    except ImportError:
        acces_docs = None

    groupes: dict[str, list[dict]] = {}
    for d in docs:
        niveau = None
        if acces_docs is not None:
            try:
                niveau = await acces_docs.niveau_reel(d["source_id"], d["source_type"])
            except Exception as e:  # noqa: BLE001 — un partage illisible n'arrête pas la campagne
                logger.info("Accès de « %s » illisible : %s", d["nom"], str(e)[:120])
        niveau = niveau or d["acces_stocke"]
        if niveau not in NIVEAUX:
            niveau = "direction_only"
        groupes.setdefault(niveau, []).append(d)
    return groupes


async def _lire_lot_docs(niveau: str, textes: list[str],
                         exiger_principal: bool) -> tuple[dict, dict, str]:
    """Fait distiller un lot au modèle. Renvoie (propositions, carte, modèle)."""
    from langchain_core.messages import HumanMessage
    from llm.router import get_llm, LLMTier
    from security.anonymizer import anonymizer
    from config import settings

    from learning.debrief import _extraire_json, _nettoyer
    from learning.enrichissement import modele_de_confiance, ModeleDegrade

    # Même fail-closed que la campagne mail — et même levée quand
    # l'anonymisation a été COUPÉE volontairement par le réglage.
    if (settings.block_external_llm_without_ner and not anonymizer.spacy_available
            and not anonymizer.desactivee()):
        raise RuntimeError("Anonymisation indisponible : campagne interrompue.")

    masques, carte = await asyncio.to_thread(anonymizer.anonymize_chunks, textes, {})
    corpus = "\n\n=====\n\n".join(masques)

    llm = get_llm(LLMTier.STANDARD)
    reponse = await llm.ainvoke([HumanMessage(
        content=INVITE_DOCS.format(corpus=corpus))])

    modele = getattr(llm, "last_model_used", "") or "?"
    if exiger_principal and not modele_de_confiance(modele):
        raise ModeleDegrade(
            f"aucun modèle de confiance n'a répondu (obtenu : {modele}). "
            "Campagne interrompue : ce qu'elle écrit reste en mémoire.")

    return _nettoyer(_extraire_json(str(reponse.content))), carte, modele


async def _collecter(connecteur: str, nom: str, lance_par: str, lance_par_id) -> None:
    """Temps 1 : ouvrir chaque fichier du stockage. Une panne n'arrête pas la
    campagne — ce qui est déjà en mémoire se relit quand même — mais elle se
    DIT, en tête de l'écran : c'est la première chose à savoir."""
    _ETAT["phase"] = f"ouverture des fichiers · {nom} (voir la carte du connecteur ci-dessous)"
    try:
        from routers.ingestion import synchroniser_et_attendre
        r = await synchroniser_et_attendre(connecteur, lance_par_id, lance_par)
    except Exception as e:  # noqa: BLE001
        r = {"etat": "echec", "erreur": str(e)[:300], "resultat": None}
    _ETAT["collecte"] = {"etat": r.get("etat"), "erreur": r.get("erreur"),
                         "resume": _resume_collecte(r)}
    if r.get("etat") not in ("terminee", "partielle"):
        _ETAT["echecs"].append(
            f"ouverture du {nom} : {r.get('erreur') or r.get('etat') or 'échec'}"
            " — la campagne relit ce qui était déjà en mémoire")
    logger.info("Enrichissement documents : collecte %s → %s", connecteur, _ETAT["collecte"])


async def executer(lance_par: str, max_lots_par_niveau: int = 0,
                   exiger_modele_principal: bool = True,
                   sources: tuple = SOURCES_DOCUMENTS,
                   collecter: bool = True, lance_par_id=None) -> dict:
    """La campagne documentaire complète, en tâche de fond.

    `max_lots_par_niveau` : 0 = TOUT le corpus (le défaut) ; un nombre borne
    les appels d'analyse par niveau d'accès (essai sur un échantillon).
    """
    from learning.debrief import enregistrer
    from learning.enrichissement import (BUDGET_CARACTERES_PAR_APPEL,
                                         PAUSE_ENTRE_LOTS_S, _creer_skills)

    if _ETAT["en_cours"]:
        return etat()
    connecteur, nom_stockage = _stockage()
    _ETAT.update({"en_cours": True, "phase": "démarrage",
                  "lance_par": lance_par, "debut": time.time(), "fin": None,
                  "stockage": nom_stockage, "collecte": None,
                  "documents": 0, "groupes": {}, "appels_prevus": 0,
                  "appels_analyse": 0, "connaissances": 0, "procedures": 0,
                  "deja_connues": 0, "skills": [], "modele": None, "echecs": []})
    # LES TÂCHES DE FOND ONT LEUR PROPRE BUDGET (01/09), comme la campagne des
    # mails : sans lui, la distillation prendrait tous les créneaux du
    # fournisseur et gèlerait le chat pendant des heures.
    try:
        from config import settings
        from llm.concurrence import porter
        porter("fond:enrichissement", int(getattr(settings, "llm_simultanes_fond", 2) or 2))
    except Exception:  # noqa: BLE001 — une porte absente n'empêche pas la campagne
        pass
    try:
        # ── 1. Ouvrir le stockage ────────────────────────────────────────
        if collecter and connecteur:
            await _collecter(connecteur, nom_stockage, lance_par, lance_par_id)

        _ETAT["phase"] = "assemblage des documents"
        docs = await _documents_assembles(sources)
        _ETAT["documents"] = len(docs)
        if not docs:
            _ETAT["phase"] = (f"terminée : aucun document lisible en mémoire — le {nom_stockage} "
                              "n'a rien rendu (voir la carte du connecteur ci-dessous)")
            return etat()

        _ETAT["phase"] = "classement par niveau d'accès"
        groupes = await _classer(docs)
        _ETAT["groupes"] = {n: len(ds) for n, ds in groupes.items()}
        logger.info("Enrichissement documents : %d document(s), niveaux %s",
                    len(docs), _ETAT["groupes"])

        # ── 2. Analyser TOUT le corpus ───────────────────────────────────
        plan = []
        for niveau, ds in groupes.items():
            textes = [f"[{d['nom']}]\n{d['texte']}" for d in ds]
            lots = _lots(textes, BUDGET_CARACTERES_PAR_APPEL)
            if max_lots_par_niveau and max_lots_par_niveau > 0:
                lots = lots[:max_lots_par_niveau]
            plan.extend((niveau, lot) for lot in lots)
        if len(plan) > MAX_APPELS_CAMPAGNE:
            _ETAT["echecs"].append(
                f"{len(plan)} appels d'analyse nécessaires : la campagne s'arrête à "
                f"{MAX_APPELS_CAMPAGNE} (garde contre l'emballement) — relancer pour la suite")
            plan = plan[:MAX_APPELS_CAMPAGNE]
        _ETAT["appels_prevus"] = len(plan)

        from learning.enrichissement import avec_reprise
        for i, (niveau, lot) in enumerate(plan):
            _ETAT["phase"] = f"analyse · {i + 1}/{len(plan)} · niveau {niveau}"
            # Même patience que la campagne des mails : une cascade à terre
            # deux minutes ne jette pas des heures de distillation.
            try:
                propositions, carte, modele = await avec_reprise(
                    lambda: _lire_lot_docs(niveau, lot, exiger_modele_principal),
                    f"niveau {niveau} lot {i + 1}",
                    sur_attente=lambda t: _ETAT.__setitem__("phase", t))
            except RuntimeError:
                raise
            except Exception as e:  # noqa: BLE001
                _ETAT["echecs"].append(f"{niveau} lot {i + 1} : {e}")
                continue
            _ETAT["appels_analyse"] += 1
            _ETAT["modele"] = modele

            # ── 3. Écrire : connaissances, manières de faire, brouillons ──
            bilan = await enregistrer(propositions, carte,
                                      prefixe_source=f"documents:{niveau}",
                                      acces_force=niveau, sans_doublon=True)
            _ETAT["connaissances"] += len(propositions.get("connaissances") or [])
            _ETAT["procedures"] += len(propositions.get("procedures") or [])
            _ETAT["deja_connues"] += int(bilan.get("deja_connus") or 0)
            _ETAT["echecs"].extend(bilan["echecs"])
            # Un skill tiré d'un fichier réservé à la direction n'est ouvert
            # qu'à la direction : il hérite du niveau de son groupe.
            skills = await _creer_skills(propositions.get("competences") or [],
                                         exiger_principal=exiger_modele_principal,
                                         acces=niveau)
            _ETAT["skills"].extend(s for s in skills if s not in _ETAT["skills"])
            await asyncio.sleep(PAUSE_ENTRE_LOTS_S)

        _ETAT["phase"] = "terminée"
        return etat()
    except Exception as e:  # noqa: BLE001
        logger.warning("Campagne documentaire interrompue : %s", e)
        _ETAT["phase"] = f"interrompue : {e}"
        _ETAT["echecs"].append(str(e)[:200])
        return etat()
    finally:
        _ETAT["en_cours"] = False
        _ETAT["fin"] = time.time()
