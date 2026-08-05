"""
Campagne d'enrichissement — l'assistant apprend du corpus de mails.

Ce que l'administrateur demande en une phrase (« lis toutes les boîtes et
enrichis-toi ») se décompose en quatre phases, exécutées en tâche de fond :

  1. COLLECTE   synchronisation des boîtes (reçus + envoyés) vers la mémoire.
                Déjà en place : ce sont les connecteurs Gmail / Outlook.
  2. STYLE      un profil d'écriture par boîte, à partir des messages envoyés.
                Déjà en place : `mail.style`.
  3. LECTURE    l'assistant relit le corpus, boîte par boîte, et propose ce
                qu'il en retient : faits durables, manières de faire,
                automatisations récurrentes.
  4. ÉCRITURE   les connaissances entrent en mémoire, les compétences deviennent
                des brouillons de skills, désactivés.

POURQUOI UNE TÂCHE DE FOND. Sur un corpus réel — dix boîtes, plusieurs centaines
de messages — l'opération dure des heures : la vectorisation est bornée par le
quota d'embeddings, et chaque lot lu coûte un appel de modèle. Un tour de chat ou
une requête HTTP expirerait bien avant la fin.

CLOISONNEMENT. Les messages restent rangés par boîte (`email:<boite>:<id>`), donc
la recherche continue de ne rendre à chacun que ce à quoi il a droit. Mais ce que
l'assistant DÉDUIT de plusieurs boîtes n'appartient plus à aucune : ce n'est plus
cloisonnable. Ces connaissances sont donc écrites au niveau d'accès le plus
restrictif, et un administrateur les rouvre s'il le juge utile. L'inverse — tout
exposer puis restreindre après coup — aurait déjà fait la fuite.
"""
from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger("duret.learning.enrichissement")

# Messages relus par lot. Assez pour qu'une régularité apparaisse, assez peu
# pour tenir dans une fenêtre de contexte sans être tronqué.
TAILLE_LOT = 25
MAX_LOTS_PAR_BOITE = 8
MAX_CARACTERES_PAR_MESSAGE = 1200

# Respiration entre deux lots : la cascade gratuite limite le débit, et une
# campagne qui la sature ferait échouer les conversations en cours.
PAUSE_ENTRE_LOTS_S = 3.0

# Les déductions inter-boîtes ne sont plus rattachables à une personne.
ACCES_DEDUCTIONS = "direction_only"

# État de la campagne en cours. Une seule à la fois : deux campagnes
# simultanées se disputeraient le quota d'embeddings pour rien.
_ETAT: dict = {"en_cours": False}


def etat() -> dict:
    return dict(_ETAT)


def _reinitialiser(lance_par: str, boites: list[str]) -> None:
    _ETAT.clear()
    _ETAT.update({
        "en_cours": True, "phase": "démarrage", "lance_par": lance_par,
        "debut": time.time(), "boites": boites, "boite_courante": None,
        "lots_lus": 0, "connaissances": 0, "procedures": 0, "skills": [],
        "echecs": [], "fin": None,
    })


INVITE_CORPUS = """Tu relis un LOT DE MESSAGES issus de la boîte professionnelle {boite}.
Ton but n'est pas de résumer ces messages, mais d'en tirer ce qui resservira PLUS TARD,
sur d'autres dossiers.

Retiens :
- "connaissances" : un fait durable sur l'entreprise ou son fonctionnement (un tarif, une
  règle, un fournisseur habituel, une contrainte technique, une préférence client récurrente).
- "procedures" : une manière de faire qui revient (comment on annonce un retard, comment on
  relance un impayé, dans quel ordre on présente un devis).
- "competences" : une tâche AUTOMATISABLE qui revient souvent, c'est-à-dire un calcul ou une
  transformation déterministe. N'en propose que si c'est vraiment reproductible.

IGNORE : ce qui ne vaut que pour un message précis, les salutations, les confirmations de
rendez-vous, les échanges sans contenu métier. Il est normal qu'un lot ne donne rien.
N'INVENTE RIEN. Les balises masquées ([PER_1], [MONTANT_2]...) restent telles quelles.

Réponds par un objet JSON seul :
{{"connaissances": [{{"titre": "...", "contenu": "..."}}],
  "procedures":    [{{"titre": "...", "contenu": "..."}}],
  "competences":   [{{"nom": "nom_en_snake_case", "description": "...", "entrees": "..."}}]}}

MESSAGES :
{corpus}"""


async def _boites_du_corpus() -> list[str]:
    """Boîtes réellement présentes en mémoire, déduites des identifiants.

    On part de ce qui est INGÉRÉ plutôt que de la liste des comptes : une boîte
    sans message ne donnerait rien, et une boîte partagée ingérée mais sans
    compte applicatif serait sinon oubliée.
    """
    from database.connection import get_db
    async with get_db() as conn:
        lignes = await conn.fetch(
            "SELECT DISTINCT split_part(source_id, ':', 2) AS boite "
            "FROM documents WHERE source_type IN ('email', 'email_sent') "
            "  AND source_id LIKE '%:%:%' ORDER BY 1")
    return [l["boite"] for l in lignes if l["boite"] and "@" in l["boite"]]


async def _messages(boite: str, decalage: int, limite: int) -> list[str]:
    from database.connection import get_db
    async with get_db() as conn:
        lignes = await conn.fetch(
            "SELECT content FROM documents "
            "WHERE source_type IN ('email', 'email_sent') "
            "  AND split_part(source_id, ':', 2) = $1 "
            "ORDER BY created_at DESC OFFSET $2 LIMIT $3",
            boite, decalage, limite)
    return [(l["content"] or "")[:MAX_CARACTERES_PAR_MESSAGE] for l in lignes if l["content"]]


async def _lire_lot(boite: str, messages: list[str]) -> tuple[dict, dict]:
    """Fait relire un lot au modèle. Renvoie (propositions, carte d'entités)."""
    from langchain_core.messages import HumanMessage
    from llm.router import get_llm, LLMTier
    from security.anonymizer import anonymizer
    from config import settings

    from learning.debrief import _extraire_json, _nettoyer

    # Fail-closed RGPD, comme partout ailleurs : sans anonymiseur, le corpus de
    # l'entreprise ne part pas vers un modèle externe.
    if settings.block_external_llm_without_ner and not anonymizer.spacy_available:
        raise RuntimeError("Anonymisation indisponible : campagne interrompue.")

    masques, carte = await asyncio.to_thread(anonymizer.anonymize_chunks, messages, {})
    corpus = "\n\n———\n\n".join(masques)

    llm = get_llm(LLMTier.STANDARD)
    reponse = await llm.ainvoke([HumanMessage(
        content=INVITE_CORPUS.format(boite=boite, corpus=corpus))])
    return _nettoyer(_extraire_json(str(reponse.content))), carte


async def _creer_skills(competences: list[dict]) -> list[str]:
    """Crée les compétences retenues en BROUILLON désactivé."""
    from database.connection import get_db
    from learning.debrief import generer_code_skill

    crees = []
    for item in competences:
        try:
            code = await generer_code_skill(item)
            if not code:
                continue
            async with get_db() as conn:
                await conn.execute(
                    """INSERT INTO skills (name, description, code, prompt_template,
                                           status, created_by, enabled)
                       VALUES ($1, $2, $3, $4, 'draft', 'enrichissement', false)
                       ON CONFLICT (name) DO NOTHING""",
                    item["nom"], item["description"], code, item.get("entrees") or "")
            crees.append(item["nom"])
        except Exception as e:  # noqa: BLE001
            logger.warning("Skill %s non créé : %s", item.get("nom"), e)
    return crees


async def executer(lance_par: str, collecter: bool = True,
                   max_lots_par_boite: int = MAX_LOTS_PAR_BOITE) -> dict:
    """Déroule la campagne. Longue : à lancer en tâche de fond."""
    from learning.debrief import enregistrer

    boites = await _boites_du_corpus()
    _reinitialiser(lance_par, boites)

    try:
        # ── 1. Collecte ────────────────────────────────────────────────
        if collecter:
            _ETAT["phase"] = "collecte des boîtes"
            for nom_connecteur in ("gmail", "outlook"):
                try:
                    module = __import__(f"ingestion.connectors.{nom_connecteur}",
                                        fromlist=["sync"])
                    resultat = await module.sync()
                    logger.info("Collecte %s : %s", nom_connecteur, resultat)
                except NotImplementedError:
                    continue          # connecteur non configuré : ce n'est pas une panne
                except Exception as e:  # noqa: BLE001
                    _ETAT["echecs"].append(f"collecte {nom_connecteur} : {e}")
            # Le corpus a pu s'élargir : on redécouvre les boîtes.
            boites = await _boites_du_corpus()
            _ETAT["boites"] = boites

        if not boites:
            _ETAT["phase"] = "aucune boîte en mémoire"
            return etat()

        # ── 2 et 3. Style, puis lecture du corpus, boîte par boîte ─────
        for boite in boites:
            _ETAT["boite_courante"] = boite

            _ETAT["phase"] = f"style d'écriture · {boite}"
            try:
                from mail.style import construire_profil
                await construire_profil(boite, force=True)
            except Exception as e:  # noqa: BLE001 - un profil raté n'arrête pas la campagne
                _ETAT["echecs"].append(f"style {boite} : {e}")

            _ETAT["phase"] = f"lecture du corpus · {boite}"
            for lot in range(max_lots_par_boite):
                messages = await _messages(boite, lot * TAILLE_LOT, TAILLE_LOT)
                if not messages:
                    break
                try:
                    propositions, carte = await _lire_lot(boite, messages)
                except RuntimeError:
                    raise                     # anonymiseur HS : on arrête tout
                except Exception as e:  # noqa: BLE001
                    _ETAT["echecs"].append(f"lecture {boite} lot {lot + 1} : {e}")
                    continue

                _ETAT["lots_lus"] += 1

                # ── 4. Écriture ───────────────────────────────────────
                bilan = await enregistrer(propositions, carte,
                                          prefixe_source=f"mails:{boite}",
                                          acces_force=ACCES_DEDUCTIONS)
                _ETAT["connaissances"] += len(propositions.get("connaissances") or [])
                _ETAT["procedures"] += len(propositions.get("procedures") or [])
                _ETAT["echecs"].extend(bilan["echecs"])

                skills = await _creer_skills(propositions.get("competences") or [])
                _ETAT["skills"].extend(s for s in skills if s not in _ETAT["skills"])

                await asyncio.sleep(PAUSE_ENTRE_LOTS_S)

        _ETAT["phase"] = "terminée"
        return etat()

    except Exception as e:  # noqa: BLE001
        logger.warning("Campagne d'enrichissement interrompue : %s", e)
        _ETAT["phase"] = f"interrompue : {e}"
        _ETAT["echecs"].append(str(e)[:200])
        return etat()
    finally:
        _ETAT["en_cours"] = False
        _ETAT["boite_courante"] = None
        _ETAT["fin"] = time.time()
