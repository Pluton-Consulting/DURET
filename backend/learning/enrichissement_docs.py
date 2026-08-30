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

IGNORE : ce qui ne vaut que pour un dossier précis (un montant isolé, une date
de rendez-vous), les mentions légales génériques, les documents sans contenu
métier. Il est normal qu'un lot ne donne rien.
N'INVENTE RIEN. Les balises masquées ([PER_1], [MONTANT_2]...) restent telles quelles.

Réponds par un objet JSON seul :
{{"connaissances": [{{"titre": "...", "contenu": "..."}}],
  "procedures":    [{{"titre": "...", "contenu": "..."}}]}}

DOCUMENTS (chacun précédé de son nom de fichier) :
{corpus}"""

_ETAT: dict = {"en_cours": False, "phase": "jamais lancée", "lance_par": None,
               "debut": None, "fin": None, "documents": 0, "groupes": {},
               "appels_analyse": 0, "connaissances": 0, "procedures": 0,
               "modele": None, "echecs": []}


def etat() -> dict:
    sortie = dict(_ETAT)
    sortie["echecs"] = list(_ETAT["echecs"])[-12:]
    sortie["groupes"] = dict(_ETAT["groupes"])
    return sortie


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


async def executer(lance_par: str, max_lots_par_niveau: int = 20,
                   exiger_modele_principal: bool = True,
                   sources: tuple = SOURCES_DOCUMENTS) -> dict:
    """La campagne documentaire complète, en tâche de fond."""
    from learning.debrief import enregistrer
    from learning.enrichissement import (BUDGET_CARACTERES_PAR_APPEL,
                                         PAUSE_ENTRE_LOTS_S)

    if _ETAT["en_cours"]:
        return etat()
    _ETAT.update({"en_cours": True, "phase": "assemblage des documents",
                  "lance_par": lance_par, "debut": time.time(), "fin": None,
                  "documents": 0, "groupes": {}, "appels_analyse": 0,
                  "connaissances": 0, "procedures": 0, "modele": None,
                  "echecs": []})
    try:
        docs = await _documents_assembles(sources)
        _ETAT["documents"] = len(docs)
        if not docs:
            _ETAT["phase"] = "terminée : aucun document ingéré à relire"
            return etat()

        _ETAT["phase"] = "classement par niveau d'accès"
        groupes = await _classer(docs)
        _ETAT["groupes"] = {n: len(ds) for n, ds in groupes.items()}
        logger.info("Enrichissement documents : %d document(s), niveaux %s",
                    len(docs), _ETAT["groupes"])

        for niveau, ds in groupes.items():
            textes = [f"[{d['nom']}]\n{d['texte']}" for d in ds]
            lots = _lots(textes, BUDGET_CARACTERES_PAR_APPEL)
            for i, lot in enumerate(lots[:max_lots_par_niveau]):
                _ETAT["phase"] = (f"analyse · niveau {niveau} "
                                  f"({i + 1}/{min(len(lots), max_lots_par_niveau)})")
                try:
                    propositions, carte, modele = await _lire_lot_docs(
                        niveau, lot, exiger_modele_principal)
                except RuntimeError:
                    raise
                except Exception as e:  # noqa: BLE001
                    _ETAT["echecs"].append(f"{niveau} lot {i + 1} : {e}")
                    continue
                _ETAT["appels_analyse"] += 1
                _ETAT["modele"] = modele
                bilan = await enregistrer(propositions, carte,
                                          prefixe_source=f"documents:{niveau}",
                                          acces_force=niveau)
                _ETAT["connaissances"] += len(propositions.get("connaissances") or [])
                _ETAT["procedures"] += len(propositions.get("procedures") or [])
                _ETAT["echecs"].extend(bilan["echecs"])
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
