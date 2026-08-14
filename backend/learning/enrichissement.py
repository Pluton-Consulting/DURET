"""
Campagne d'enrichissement — l'assistant apprend du corpus de mails.

Ce que l'administrateur demande en une phrase (« lis toutes les boîtes et
enrichis-toi ») se décompose en quatre phases, exécutées en tâche de fond :

  1. COLLECTE     synchronisation des boîtes vers la mémoire (connecteurs).
  2. EXTRACTION   TOUT le corpus est écrit sur disque, en lecture seule, SANS
                  le moindre appel de modèle.
  3. STYLE        un profil d'écriture par boîte, à partir des envois.
  4. ANALYSE      le corpus est relu par lots dimensionnés à la FENÊTRE du
                  modèle, et non par paquets de vingt-cinq messages.
  5. ÉCRITURE     connaissances et manières de faire en mémoire, compétences en
                  brouillons de skills désactivés.

POURQUOI EXTRAIRE AVANT D'ANALYSER. La campagne appelait le modèle tous les
25 messages : des dizaines d'appels pour lire ce qu'une grande fenêtre avale
d'un coup, chacun payant le prix d'entrée et la latence, pour une vue morcelée
qui empêchait justement de voir les régularités recherchées. L'extraction ne
coûte rien — c'est de la lecture de base — et elle peut échouer sans avoir rien
dépensé. L'analyse, elle, se paie : autant qu'elle travaille sur un corpus déjà
complet. Un corpus de 2 000 messages tient désormais en une dizaine d'appels.

Le corpus extrait contient du courrier d'entreprise : il est passé en lecture
seule, et SUPPRIMÉ en fin de campagne, y compris si elle est interrompue.

POURQUOI UNE TÂCHE DE FOND. Sur un corpus réel, l'opération dure des heures : la
vectorisation est bornée par le quota d'embeddings, et chaque lot analysé coûte
un appel. Un tour de chat ou une requête HTTP expirerait bien avant la fin.

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
import os
import shutil
import tempfile
import time

logger = logging.getLogger("duret.learning.enrichissement")

# Budget de CARACTÈRES par appel, et non un nombre de messages.
#
# La campagne faisait un appel de modèle tous les 25 messages : sur un corpus
# réel, des dizaines d'appels pour lire ce qu'un modèle à grande fenêtre avale
# d'un coup. C'était payer la latence et le prix d'entrée autant de fois que de
# lots, pour une vue morcelée qui empêchait justement de voir les régularités.
#
# 180 000 caractères ≈ 45 000 jetons : large sur une fenêtre de 128 k, confortable
# sur le million de DeepSeek Pro. Un corpus de 2 000 messages tient alors en une
# dizaine d'appels au lieu de quatre-vingts.
BUDGET_CARACTERES_PAR_APPEL = 180_000
MAX_CARACTERES_PAR_MESSAGE = 1200
MAX_MESSAGES_PAR_BOITE = 2000        # garde-fou : une boîte ne monopolise pas la campagne

# Plafond d'appels d'ANALYSE par boîte. Le nom est conservé — il est déjà exposé
# dans le catalogue de skills et dans l'API — mais il ne compte plus des paquets
# de 25 messages : il compte des appels, chacun portant une pleine fenêtre.
# 2 000 messages de 1 200 caractères tiennent en ~14 appels : 20 laisse de la
# marge sans permettre l'emballement.
MAX_LOTS_PAR_BOITE = 20

# Respiration entre deux lots : la cascade gratuite limite le débit, et une
# campagne qui la sature ferait échouer les conversations en cours.
PAUSE_ENTRE_LOTS_S = 3.0

# Les déductions inter-boîtes ne sont plus rattachables à une personne.
ACCES_DEDUCTIONS = "direction_only"

# Fournisseur du modèle PRINCIPAL de la cascade (aujourd'hui LongCat). La
# campagne exige ce modèle et rien d'autre : ce qu'elle produit est écrit
# DURABLEMENT en mémoire et dans le catalogue de skills. Un repli silencieux sur
# un modèle gratuit remplirait la mémoire de déductions médiocres, sans que rien
# n'indique lesquelles — et l'écrit reste, lui.
#
# On lit le fournisseur réellement retenu (`last_model_used`, de la forme
# « fournisseur:modèle ») plutôt qu'un réglage : c'est le seul témoin de ce qui
# a VRAIMENT répondu, la cascade pouvant basculer d'un lot à l'autre.
FOURNISSEUR_PRINCIPAL = "longcat"

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
        "messages_extraits": 0, "corpus": {},
        "appels_analyse": 0, "connaissances": 0, "procedures": 0, "skills": [],
        "modele": None,
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


async def extraire_corpus(boites: list[str], dossier: str) -> dict[str, int]:
    """Écrit TOUT le corpus sur disque, sans le moindre appel de modèle.

    Deux temps volontairement séparés. L'extraction est de la lecture de base :
    elle ne coûte rien, elle est rapide, et elle peut échouer sans avoir rien
    dépensé. L'analyse, elle, se paie — autant qu'elle travaille sur un corpus
    déjà complet plutôt que d'aller le chercher par petits bouts entre deux
    appels.

    Le fichier est passé en LECTURE SEULE une fois écrit : rien, dans la suite
    de la campagne, n'a de raison de le modifier.
    """
    import json
    import os

    from database.connection import get_db

    compte: dict[str, int] = {}
    for boite in boites:
        async with get_db() as conn:
            lignes = await conn.fetch(
                "SELECT source_type, content FROM documents "
                "WHERE source_type IN ('email', 'email_sent') "
                "  AND split_part(source_id, ':', 2) = $1 "
                "ORDER BY created_at DESC LIMIT $2",
                boite, MAX_MESSAGES_PAR_BOITE)

        chemin = os.path.join(dossier, f"{boite.replace('/', '_')}.jsonl")
        n = 0
        with open(chemin, "w", encoding="utf-8") as f:
            for l in lignes:
                contenu = (l["content"] or "").strip()
                if not contenu:
                    continue
                f.write(json.dumps(
                    {"type": l["source_type"],
                     "texte": contenu[:MAX_CARACTERES_PAR_MESSAGE]},
                    ensure_ascii=False) + "\n")
                n += 1
        try:
            os.chmod(chemin, 0o444)      # lecture seule
        except OSError:
            pass                          # système de fichiers qui ne le permet pas
        compte[boite] = n
        logger.info("Corpus extrait : %s -> %d message(s)", boite, n)
    return compte


def _lots_par_budget(chemin: str) -> list[list[str]]:
    """Regroupe les messages d'un fichier en lots tenant dans une fenêtre.

    On coupe sur le BUDGET, pas sur un compte : un lot de 25 messages courts
    gaspille la fenêtre, un lot de 25 messages longs la dépasse. Un message plus
    gros que le budget à lui seul part quand même — tronqué en amont, il ne peut
    pas faire déborder.
    """
    import json

    lots: list[list[str]] = []
    courant: list[str] = []
    taille = 0
    with open(chemin, encoding="utf-8") as f:
        for ligne in f:
            try:
                texte = json.loads(ligne)["texte"]
            except (ValueError, KeyError):
                continue
            if courant and taille + len(texte) > BUDGET_CARACTERES_PAR_APPEL:
                lots.append(courant)
                courant, taille = [], 0
            courant.append(texte)
            taille += len(texte)
    if courant:
        lots.append(courant)
    return lots


class ModeleDegrade(RuntimeError):
    """La cascade a répondu avec autre chose que le modèle principal."""


async def _lire_lot(boite: str, messages: list[str],
                    exiger_principal: bool = True) -> tuple[dict, dict, str]:
    """Fait relire un lot au modèle. Renvoie (propositions, carte, modèle utilisé)."""
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
    corpus = "\n\n=====\n\n".join(masques)

    # Palier STANDARD : sa cascade commence par le modèle principal. On garde la
    # même instance pour lire `last_model_used` — en redemander une au routeur
    # pourrait en rendre une autre.
    llm = get_llm(LLMTier.STANDARD)
    reponse = await llm.ainvoke([HumanMessage(
        content=INVITE_CORPUS.format(boite=boite, corpus=corpus))])

    modele = getattr(llm, "last_model_used", "") or "?"
    if exiger_principal and not modele.startswith(FOURNISSEUR_PRINCIPAL + ":"):
        # On ARRÊTE plutôt que d'écrire au rabais. Une campagne à moitié lue se
        # relance ; une mémoire polluée par des déductions de moindre qualité,
        # mêlées aux bonnes, ne se démêle pas.
        raise ModeleDegrade(
            f"le modèle principal n'a pas répondu (repli sur {modele}). "
            "Campagne interrompue : ce qu'elle écrit reste en mémoire, "
            "il ne doit pas venir d'un modèle de repli.")

    return _nettoyer(_extraire_json(str(reponse.content))), carte, modele


async def _creer_skills(competences: list[dict],
                        exiger_principal: bool = True,
                        acces: str = "all") -> list[str]:
    """Crée les compétences retenues en BROUILLON désactivé.

    Le code est écrit par un modèle : la même exigence qu'à la lecture
    s'applique, sinon on livrerait du code de moindre qualité dans le
    catalogue.
    """
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
                    item["nom"], item["description"], code,
                    item.get("entrees") or "", acces)
            crees.append(item["nom"])
        except Exception as e:  # noqa: BLE001
            logger.warning("Skill %s non créé : %s", item.get("nom"), e)
    return crees


async def executer(lance_par: str, collecter: bool = True,
                   max_lots_par_boite: int = MAX_LOTS_PAR_BOITE,
                   exiger_modele_principal: bool = True,
                   acces_skills: str = "all") -> dict:
    """Déroule la campagne. Longue : à lancer en tâche de fond."""
    from learning.debrief import enregistrer

    boites = await _boites_du_corpus()
    _reinitialiser(lance_par, boites)
    dossier = None

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

        # ── 2. EXTRACTION : tout le corpus sur disque, sans un seul appel ──
        # Séparer l'extraction de l'analyse est ce qui permet d'analyser des
        # LOTS ENTIERS plutôt que d'aller chercher vingt-cinq messages entre
        # deux appels de modèle.
        _ETAT["phase"] = "extraction du corpus"
        dossier = tempfile.mkdtemp(prefix="enrichissement-")
        compte = await extraire_corpus(boites, dossier)
        _ETAT["messages_extraits"] = sum(compte.values())
        _ETAT["corpus"] = compte
        logger.info("Corpus complet extrait dans %s : %d message(s)",
                    dossier, _ETAT["messages_extraits"])

        # ── 3. Style, puis analyse par lots dimensionnés à la fenêtre ──────
        for boite in boites:
            _ETAT["boite_courante"] = boite

            _ETAT["phase"] = f"style d'écriture · {boite}"
            try:
                from mail.style import construire_profil
                await construire_profil(boite, force=True)
            except Exception as e:  # noqa: BLE001 - un profil raté n'arrête pas la campagne
                _ETAT["echecs"].append(f"style {boite} : {e}")

            chemin = os.path.join(dossier, f"{boite.replace('/', '_')}.jsonl")
            if not os.path.exists(chemin):
                continue
            lots = _lots_par_budget(chemin)
            _ETAT["phase"] = f"analyse · {boite} ({len(lots)} appel(s))"
            for lot, messages in enumerate(lots[:max_lots_par_boite]):
                try:
                    propositions, carte, modele = await _lire_lot(
                        boite, messages, exiger_principal=exiger_modele_principal)
                except RuntimeError:
                    raise            # anonymiseur HS ou modèle dégradé : on arrête tout
                except Exception as e:  # noqa: BLE001
                    _ETAT["echecs"].append(f"analyse {boite} lot {lot + 1} : {e}")
                    continue

                _ETAT["appels_analyse"] += 1
                _ETAT["modele"] = modele

                # ── 4. Écriture ───────────────────────────────────────
                bilan = await enregistrer(propositions, carte,
                                          prefixe_source=f"mails:{boite}",
                                          acces_force=ACCES_DEDUCTIONS)
                _ETAT["connaissances"] += len(propositions.get("connaissances") or [])
                _ETAT["procedures"] += len(propositions.get("procedures") or [])
                _ETAT["echecs"].extend(bilan["echecs"])

                skills = await _creer_skills(
                    propositions.get("competences") or [],
                    exiger_principal=exiger_modele_principal,
                    acces=acces_skills)
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
        # Le corpus extrait contient du courrier d'entreprise : il ne doit pas
        # survivre à la campagne, même interrompue.
        if dossier:
            shutil.rmtree(dossier, ignore_errors=True)
            logger.info("Corpus temporaire supprimé : %s", dossier)
        _ETAT["en_cours"] = False
        _ETAT["boite_courante"] = None
        _ETAT["fin"] = time.time()
