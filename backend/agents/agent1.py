"""
Agent 1 — Administratif / Suivi de chantiers (BTP — Duret & Sols)
Pipeline : RAG pgvector → anonymisation NER → [browser?] → LLM → réhydratation → validation check
Zéro PII vers l'API LLM : la requête ET les documents sont masqués avant l'appel,
puis les vraies valeurs sont réinjectées dans la réponse (entity_map).
"""
import logging

from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END
from agents.state import AgentState
from llm.router import get_llm, LLMTier

logger = logging.getLogger("duret.agents.agent1")

SYSTEM_PROMPT = """Tu es l'assistant IA interne de Duret & Sols, entreprise de travaux de sols et de revêtements (BTP).
Tu assistes l'équipe administrative et le suivi de chantiers dans leur travail quotidien : gestion administrative, comptabilité, réponses aux mails, factures et situations, suivi du temps passé sur les chantiers, commandes, planning, fournisseurs, règlements, réserves, contentieux et dossiers juridiques, support commercial sur les dossiers existants.
Tu disposes d'une mémoire d'entreprise (appels d'offres, CCTP, CCAP, DPGF, plans, devis, DOE, commandes, factures, situations, documents fournisseurs, dossiers juridiques, réserves, dossiers chantier, mails).
RÈGLE DE RECHERCHE : la mémoire a DÉJÀ été consultée pour toi quand la demande le justifiait. Si des documents te sont fournis, réponds à partir d'eux. Si aucun ne l'est, c'est que la demande n'en nécessitait pas, ou que la mémoire ne contient rien : ne relance l'action `rechercher_documents` que si la réponse dépend manifestement d'une donnée interne qui te manque, avec des termes DIFFÉRENTS. Pour une salutation, un remerciement ou une question générale, réponds directement, SANS aucune action et SANS parler de la mémoire d'entreprise. Cette dispense ne concerne QUE la recherche documentaire. Elle ne vaut JAMAIS pour les actions qui PRODUISENT ou qui AGISSENT : creer_document, ajouter_document, terminer_document, la lecture ou le dépôt sur le serveur de fichiers, la lecture de mails, la génération de visuels. Dès qu'on te demande de FABRIQUER un fichier ou de TOUCHER à un système, il FAUT émettre les actions correspondantes : aucune rédaction directe ne produit un document téléchargeable.
Ne liste JAMAIS de contenu imaginaire et ne prétends pas avoir des dossiers que la recherche ne t'a pas rendus.
Réponds toujours en français, de façon précise, professionnelle et concise. Sois utile pour : retrouver un dossier par chantier, faire le point sur des commandes / réserves / échéances, préparer un brouillon de réponse à un mail, suivre un dossier juridique ou un règlement fournisseur.
Certaines valeurs des documents peuvent apparaître masquées sous forme de balises [PER_1], [MONTANT_2], etc. Conserve-les telles quelles. Ne CRÉE jamais toi-même de balise entre crochets.
Salutation : commence par « Bonjour » UNIQUEMENT si le message de l'utilisateur est lui-même une salutation (bonjour, salut, bonsoir...) ; sinon, pour une question de travail, réponds DIRECTEMENT, sans « Bonjour » ni formule d'accueil, et sans jamais répéter une salutation déjà faite dans la conversation. Ne dis JAMAIS « je suis Duret & Sols » ni « je m'appelle Duret & Sols » (c'est le nom de l'entreprise, pas ton identité à énoncer) et ne te présente pas. Pour une question de travail, réponds directement.
N'invente JAMAIS de donnée (montant, nom, date, nombre, référence de dossier). Tout chiffre que tu avances doit provenir d'un document que la recherche t'a rendu, ou de ce que l'utilisateur vient de te dire. Les décisions engageantes (envoi d'un mail, facturation, action juridique) restent validées par un humain.
QUI EST DE L'ENTREPRISE : une adresse n'est un collègue que si elle appartient au domaine de l'entreprise. Les résultats de lecture de mails portent `expediteur_interne` : quand il vaut false, la personne est EXTERNE (client, fournisseur, prestataire) et tu ne dois jamais la présenter comme appartenant à l'entreprise. `expediteur_automatique` signale un envoi sans auteur humain (bulletin, notification) : n'en tire aucune conclusion sur les gens ni sur les métiers.
UN ÉCHANTILLON N'EST PAS UN INVENTAIRE : lire quelques messages d'une boîte ne dit rien des activités, des process ni de l'histoire de l'entreprise. Ne généralise jamais de dix mails reçus vers une description de la société. Si l'on te demande d'analyser LE COURRIER DE L'ENTREPRISE pour en tirer des process, des activités ou des compétences, c'est `lancer_enrichissement` qu'il faut, et rien d'autre.
CONSULTER UNE BOÎTE MAIL : utilise l'action `lire_mails`, qui va chercher les messages RÉELS dans la boîte. La recherche documentaire ne sert pas à cela : elle ne voit que ce qui a été ingéré auparavant. Dès qu'on te demande de lire, voir, relever ou faire le point sur des mails, c'est `lire_mails`.
NE CONCLUS JAMAIS que la mémoire d'entreprise est vide à partir d'une recherche infructueuse. Une recherche qui ne rend rien signifie « rien ne correspond à CES termes », jamais « il n'y a rien ». Dis ce que tu as cherché, dis que tu n'as rien trouvé là-dessus, et propose des termes plus concrets. Affirmer que la mémoire ne contient aucun mail ou aucun document est une affirmation sur l'état du système : tu ne peux la faire que si un inventaire te l'a explicitement indiqué.
DONNÉE MANQUANTE : quand on te demande de remplir une fiche, un tableau, un récapitulatif ou un modèle et qu'une information ne figure nulle part, écris exactement [À COMPLÉTER] à sa place. Ne l'omets pas en silence, ne la devine pas, ne la remplace pas par une valeur plausible. Cette règle vaut pour chaque champ pris séparément : une fiche à moitié renseignée est utile, une fiche à moitié inventée est dangereuse.
Ne recopie jamais la demande de l'utilisateur dans ta réponse, et ne répète pas une information que tu viens de donner : réponds, puis arrête-toi.
Typographie : n'utilise JAMAIS de tiret cadratin ni de tiret demi-cadratin ; emploie plutôt une virgule, un deux-points, une parenthèse ou un point."""


# Nombre maximal d'actions exécutées dans un même tour. Chaque action coûte un
# aller-retour LLM supplémentaire : au-delà, le modèle tourne en rond plus qu'il
# n'avance, et la facture grimpe pour rien.
#
# RELEVÉ DE 3 À 8. Trois suffisaient tant qu'une demande se traduisait par une
# recherche puis une réponse. Produire un document en demande TROIS à lui seul
# (créer, remplir, terminer) : la moindre consultation préalable faisait dépasser
# le budget, et le tour se terminait sur « je vais le faire » sans que rien ne
# soit fait — observé sur « compte les dossiers puis fais-en un PDF ».
#
# Le garde-fou contre les boucles ne repose de toute façon pas sur ce chiffre :
# une action REJOUÉE à l'identique est reconnue par son empreinte et resservie
# sans être exécutée. Ce qui est borné ici, c'est le travail qui AVANCE.
MAX_ACTIONS_PAR_TOUR = 8

# Les versements dans un document en cours sont exemptés du budget ci-dessus
# (ils avancent par construction), mais pas sans borne : le document accepte
# 20 000 éléments, donc un modèle qui en verserait UN par appel obtiendrait
# 20 000 allers-retours — pas une boucle infinie, un tour qui dure des heures.
# 40 versements couvrent 16 000 blocs au rythme normal (400 par appel), soit
# bien au-delà de tout document réel.
MAX_VERSEMENTS_PAR_TOUR = 40

# LE SCHÉMA D'UNE ARBORESCENCE NE TIENT PAS DANS 4000 CARACTÈRES. Le résultat
# de chaque action est plafonné avant de repartir vers le modèle — et c'est ce
# plafond, pas l'outil, qui tronquait l'arbre : le modèle relançait alors
# l'exploration « car le résultat précédent était tronqué », mot pour mot, et
# le budget d'actions y passait. Ces skills-là, dont la sortie EST le contenu
# demandé, ont droit à un plafond large ; les autres gardent le plafond serré,
# un résultat d'action ordinaire n'ayant rien à faire au-delà.
# (Le nom varie selon le projet — drive_ ou nas_ — la règle est la même.)
# Corrections d'un bloc d'action mal formé ou COUPÉ, par tour. Deux essais :
# une sortie tronquée par le plafond se répète volontiers une fois avant que le
# modèle réduise vraiment le volume. Au-delà, on n'insiste pas.
MAX_REPARATIONS_PAR_TOUR = 2

RESULTATS_GENEREUX = {"drive_arborescence", "nas_arborescence"}
PLAFOND_RESULTAT = 4000
PLAFOND_RESULTAT_GENEREUX = 12000


# ANNONCE SANS ACTE. Le modèle écrit « je crée le PDF », « je commence par
# compter », et n'émet AUCUN bloc d'action. Le tour se terminait sur cette
# phrase : l'utilisateur lit une promesse, redemande, et obtient la même
# promesse. Observé sur plusieurs tours d'affilée.
#
# On ne peut pas l'empêcher d'écrire cela ; on peut refuser que ce soit la FIN
# du tour. Une seule relance, avec une consigne explicite — au-delà on
# insisterait sur un modèle qui ne veut pas, et la note de sortie explique alors
# honnêtement pourquoi rien n'a été fait.
from agents.annonce import est_une_annonce, cloture_attendue


# ── Nœuds ────────────────────────────────────────────────────────────

async def rag_node(state: AgentState) -> dict:
    """Prépare le contexte immédiat du tour. NE FAIT PLUS de recherche.

    La recherche documentaire est devenue un OUTIL (`rechercher_documents`) que
    le modèle appelle s'il en a besoin. Auparavant elle tournait avant chaque
    appel, quoi qu'on dise : un « bonjour » déclenchait une recherche
    vectorielle, une passe d'anonymisation sur les résultats, puis un préambule
    « aucun document trouvé » qui poussait le modèle à répondre à côté.

    Reste ici ce qui n'a pas à être décidé : une pièce jointe envoyée à l'instant
    fait évidemment partie du contexte.
    """
    texte_joint = state.get("attachment_text")
    if not texte_joint:
        return {"raw_chunks": []}
    nom = state.get("attachment_name") or "document"
    return {"raw_chunks": [f"[FICHIER JOINT PAR L'UTILISATEUR : {nom}]\n{texte_joint}"]}


async def anonymize_node(state: AgentState) -> dict:
    """Masque la requête ET les chunks avant tout envoi LLM (entity_map partagé)."""
    from security.anonymizer import anonymizer

    import asyncio
    query = state.get("query", "")
    chunks = list(state.get("raw_chunks") or [])
    # entity_map PERSISTANTE sur le fil : on repart de celle des tours précédents pour
    # qu'une même valeur garde le MÊME placeholder d'un tour à l'autre. Sans ça, la
    # numérotation redémarrant à 1 à chaque tour, [PER_1] désignerait une personne
    # différente dans l'historique et dans la question courante — le modèle fusionnerait
    # les deux et la réhydratation réinjecterait la mauvaise valeur.
    # Désamorce les balises que l'utilisateur aurait saisies lui-même : la map étant
    # cumulative, « donne-moi [PER_1] » lui ferait sinon restituer la valeur réelle
    # attachée à ce jeton par un tour antérieur ou par un document.
    query = anonymizer.neutralize_placeholders(query)
    previous_map = state.get("entity_map") or {}
    # NER spaCy = CPU-bound synchrone : on le sort de la boucle événementielle (sinon il
    # fige le streaming WS et bloque les autres requêtes pendant toute l'étape).
    masked, entity_map = await asyncio.to_thread(
        anonymizer.anonymize_chunks, [query] + chunks, previous_map
    )

    return {
        "anonymized_query": masked[0] if masked else query,
        "anonymized_chunks": masked[1:] if len(masked) > 1 else [],
        "entity_map": entity_map,
    }


async def routeur_node(state: AgentState) -> dict:
    """Décide de la suite : répondre directement, ou consulter la mémoire.

    C'est une IA qui tranche, pas une liste de mots-clés — mais elle tranche en
    UN appel très court, sur le palier le plus léger, avant toute rédaction.

    Pourquoi pas laisser le modèle rédacteur décider via un bloc d'action : sur
    les modèles modestes de la cascade, un « salut » déclenchait des recherches
    en boucle jusqu'au garde-fou, pour un résultat lent et vide. Séparer la
    DÉCISION de la RÉDACTION rend le chemin court quand il doit l'être.
    """
    from llm.router import get_llm, LLMTier as _T
    from langchain_core.messages import HumanMessage as _H
    import json as _json
    import re as _re

    question = state.get("anonymized_query") or state.get("query", "")

    # Une pièce jointe vient d'arriver : le contexte est déjà là, rien à chercher.
    if state.get("attachment_text"):
        # Le contexte est déjà là, mais analyser un document EST un travail de fond.
        return {"besoin_memoire": False, "llm_tier": "complex"}

    invite = (
        "Tu orientes une demande adressée à l'assistant interne d'une entreprise.\n"
        "Dis UNIQUEMENT s'il faut consulter la mémoire d'entreprise (chantiers, devis, "
        "factures, commandes, dossiers, mails, documents internes) pour répondre.\n"
        "- Salutation, remerciement, question générale, demande de rédaction ou de "
        "reformulation, suite directe de la conversation : AUCUNE recherche.\n"
        "- Question portant sur un dossier, un client, un montant ou un document "
        "de l'entreprise : recherche NÉCESSAIRE.\n"
        "- Demande de CONSULTER une boîte mail (lire, voir, relever ses messages) : "
        "AUCUNE recherche. Les messages se lisent en direct dans la boîte, pas dans "
        "la mémoire.\n"
        "Dis AUSSI quel effort la demande réclame :\n"
        '- "simple" : salutation, question factuelle, rédaction courte, suite de '
        "conversation. La grande majorité des cas.\n"
        '- "analyse" : il faut comparer, synthétiser, recouper plusieurs sources, '
        "expliquer un raisonnement, tirer des conclusions d'un ensemble de données.\n"
        'Réponds par un objet JSON seul : {"memoire": true|false, "requete": '
        '"<mots-clés de recherche si true, sinon vide>", "effort": "simple|analyse"}\n\n'
        f"Demande : {question}"
    )

    try:
        reponse = await get_llm(_T.LIGHT).ainvoke([_H(content=invite)])
        trouve = _re.search(r"\{.*\}", str(reponse.content), _re.S)
        decision = _json.loads(trouve.group(0)) if trouve else {}
        besoin = bool(decision.get("memoire"))
        requete = str(decision.get("requete") or "").strip() or question
        # « analyse » fait basculer la rédaction sur le palier COMPLEX, donc sur
        # le modèle de raisonnement. Le défaut reste « simple » : on ne paie le
        # modèle cher que lorsqu'une IA a jugé qu'il le fallait.
        effort = ("complex"
                  if str(decision.get("effort") or "").strip().lower().startswith("analyse")
                  else "standard")
    except Exception as e:  # noqa: BLE001
        # En cas d'échec, on CHERCHE : répondre « je n'ai rien » alors que la
        # mémoire contient la réponse est bien pire qu'une recherche inutile.
        logger.info("Routage indisponible (%s) — recherche par défaut", e)
        besoin, requete, effort = True, question, "standard"

    logger.debug("Routage : mémoire=%s, effort=%s", besoin, effort)
    return {"besoin_memoire": besoin, "requete_memoire": requete, "llm_tier": effort}


async def recherche_node(state: AgentState) -> dict:
    """Exécute la recherche décidée par le routeur, et masque les résultats."""
    import asyncio
    from security.anonymizer import anonymizer
    from vectorstore.rag import retrieve_as_context
    from mail.authorization import boites_par_id

    # Cloisonnement : uniquement les boîtes mail auxquelles cette personne a
    # droit. Sans droits déterminables, aucun mail (fail-closed).
    try:
        boites = await boites_par_id(state.get("user_id"))
    except Exception:  # noqa: BLE001
        boites = []

    trouves = await retrieve_as_context(
        query=state.get("requete_memoire") or state.get("query", ""),
        user_role=state.get("user_role", "terrain"),
        top_k=5,
        mailboxes=boites,
    )
    # On CONSERVE ce qui est déjà là (une pièce jointe masquée en amont) : ce
    # canal est en « dernière valeur », un retour brut l'effacerait.
    deja = list(state.get("anonymized_chunks") or [])
    if not trouves:
        return {"anonymized_chunks": deja}

    # Les documents partent vers le modèle : ils doivent être masqués, avec la
    # carte cumulative du fil pour que les jetons restent cohérents.
    masques, carte = await asyncio.to_thread(
        anonymizer.anonymize_chunks, list(trouves), state.get("entity_map") or {})
    return {"anonymized_chunks": deja + masques, "entity_map": carte}


async def browser_node(state: AgentState) -> dict:
    """Recherche web via DuckDuckGo dans sandbox Daytona — dernier recours si RAG vide."""
    from browser.tools import web_search
    result = await web_search(
        query=state.get("query", ""),
        user_id=state.get("user_id", ""),
        agent_id="agent1",
        max_results=3,
    )
    existing = list(state.get("raw_chunks") or [])
    if result["success"]:
        existing.append(
            "[SOURCE WEB : information externe, à mentionner et valider]\n" + result["content"]
        )
    return {
        "raw_chunks": existing,
        "browser_used": True,
        "browser_sources": result.get("sources", []),
        "browser_content": result.get("content"),
        "browser_was_filtered": result.get("was_filtered", False),
    }


async def llm_node(state: AgentState, config=None) -> dict:
    """Appel LLM (résilient) sur requête/contexte masqués. Le tracing Langfuse est
    propagé depuis le tour complet via `config` (arbre de trace unique)."""
    # Fail-closed RGPD : si l'anonymiseur NER est HS, on NE contacte PAS de LLM
    # externe (noms/adresses/organisations partiraient en clair). On refuse.
    from security.anonymizer import anonymizer
    from config import settings as _settings
    if _settings.block_external_llm_without_ner and not anonymizer.spacy_available:
        return {
            "llm_response": ("Service momentanément indisponible : la protection des données "
                             "(anonymisation) n'est pas opérationnelle, la requête n'a pas été "
                             "envoyée à un modèle externe. Contactez l'administrateur."),
            "model_used": None,
            "error": "ner_unavailable",
        }

    import hashlib
    from optim.tokens import trim_chunks, response_cache, compact_messages
    from skills.protocol import (instruction_actions, rafraichir_catalogue,
                                 BLOC_ACTION_RE, BLOC_NATIF_RE)

    # Le registre de skills en base est rechargé périodiquement (cache interne).
    # Sans cela, le modèle ne connaîtrait que les six skills natifs, alors que
    # l'onglet Skills en montre bien davantage : interrogé sur ce qu'il sait
    # faire, il en oubliait la plus grande partie.
    await rafraichir_catalogue()

    tier = state.get("llm_tier", "standard")
    llm = get_llm(LLMTier(tier))

    chunks = state.get("anonymized_chunks")
    if chunks is None:
        chunks = state.get("raw_chunks") or []
    chunks = trim_chunks(chunks)   # borne le nombre de chunks + le volume de contexte
    context_text = "\n\n---\n\n".join(str(c) for c in chunks) if chunks else ""

    query = state.get("anonymized_query") or state.get("query", "")

    # Historique de conversation (déjà ANONYMISÉ : on ne stocke que du texte masqué),
    # borné en nombre de messages ET en caractères, recalé sur une frontière de paire.
    history = compact_messages(state.get("messages") or [])

    # Cache exact (palier|requête|contexte anonymisés). La clé DOIT inclure le fil et
    # l'historique : sinon, reposer une question déjà posée renverrait la réponse figée
    # du 1er tour (la mémoire semblerait perdue par intermittence), et deux utilisateurs
    # posant la même question partageraient une réponse conditionnée par la conversation
    # de l'autre. Le thread_id isole par conversation, donc par utilisateur.
    history_sig = hashlib.sha256(
        "\n".join(str(getattr(m, "content", "") or "") for m in history).encode("utf-8")
    ).hexdigest()[:16] if history else ""
    cache_scope = f"{state.get('thread_id', '')}|{history_sig}"

    # Le cache est COURT-CIRCUITÉ dès qu'une action a été exécutée : la réponse
    # dépend alors d'un effet de bord (contenu d'une boîte, brouillon produit),
    # elle n'est pas rejouable à l'identique.
    en_boucle_outils = bool(state.get("tool_results"))
    if not en_boucle_outils:
        cached = response_cache.get(tier, query, context_text, cache_scope)
        if cached is not None:
            return {"llm_response": cached, "model_used": "cache", "tokens_in": 0, "tokens_out": 0}

    # Résultats des actions déjà exécutées ce tour : c'est ce qui permet au modèle
    # de rédiger sa réponse finale à partir de ce que l'outil a réellement produit.
    resultats_outils = state.get("tool_results") or []
    bloc_resultats = ""
    if resultats_outils:
        import json as _json_out
        # CE MESSAGE DISAIT « appuie-toi dessus POUR RÉPONDRE ». À chaque retour
        # de résultat, on invitait donc le modèle à conclure — y compris au
        # milieu d'un travail à peine commencé. Combiné au protocole qui parlait
        # de « ta réponse finale » après UNE action, il n'avait aucune raison de
        # continuer : les deux textes lui disaient de s'arrêter.
        # Le plafond du bloc suit celui des résultats : tronquer ICI à 6000 un
        # schéma que `tools_node` a laissé passer à 12000 reviendrait à
        # déplacer la coupure, pas à la supprimer.
        plafond_bloc = (16000 if any((r.get("skill") or "") in RESULTATS_GENEREUX
                                     for r in resultats_outils) else 6000)
        bloc_resultats = (
            "Résultats des actions déjà exécutées pour cette demande (ne les "
            "relance pas à l'identique) :\n"
            + _json_out.dumps(resultats_outils, ensure_ascii=False,
                              default=str)[:plafond_bloc]
            + "\n\n")
        # LE TRAVAIL RESTÉ OUVERT SE DIT, il ne se devine pas. `cloture_attendue`
        # lit dans les RÉSULTATS — pas dans la prose — qu'un document a été
        # ouvert sans être fermé. Le lui rappeler ici est le seul rappel qui
        # arrive au bon moment : juste avant qu'il choisisse entre agir et
        # conclure.
        manque = cloture_attendue(resultats_outils)
        if manque:
            # LE CHEMIN QUI DÉPOSE SE DIT ICI. Ne nommer que `terminer_document`
            # poussait vers la fermeture seule : une fois fermée, plus rien
            # n'attendait, et le document demandé « dans /Drive » restait sur
            # le disque de l'assistant. Les deux sorties sont annoncées, avec
            # celle qui répond à une demande de dépôt en premier.
            bloc_resultats += (
                f"ATTENTION : le travail n'est PAS terminé. Il reste au minimum "
                f"`{manque}` à exécuter, et le contenu demandé à verser avant. "
                "Si un DÉPÔT sur le serveur a été demandé (« dans /Drive », "
                "« sur le NAS »), la bonne action de clôture est "
                "`nas_deposer_document` : elle finalise ET dépose en un geste, "
                "et remplace `terminer_document`. "
                "N'écris pas ta réponse finale maintenant : émets l'action suivante.\n\n")

    # UN DOCUMENT RESTÉ OUVERT D'UN TOUR PRÉCÉDENT SE DIT AUSSI.
    # `cloture_attendue` ne lit que les résultats de CE tour : « je continue à
    # verser le contenu dans le document déjà ouvert » — ouvert au tour d'avant
    # — partait donc sans identifiant ni rappel, et le tour s'est terminé sur
    # la promesse. L'atelier, lui, s'en souvient : on lui demande.
    #
    # ET LES TERMINÉS AUSSI. Relevé en production : « test 2 » venait d'être
    # finalisé (38 Ko), et au tour suivant le modèle a répondu « ce document
    # n'existe pas », est parti le chercher sur le serveur, puis a proposé de
    # déposer un document VIDE à sa place. Un document fini sortait de la seule
    # liste que le modèle voyait — le plus important devenait invisible.
    try:
        import asyncio as _aio
        from bureautique.atelier import ouverts as _docs_ouverts
        from bureautique.atelier import termines as _docs_termines
        _uid = str(state.get("user_id") or "")
        en_cours = await _aio.to_thread(_docs_ouverts, _uid)
        finis = (await _aio.to_thread(_docs_termines, _uid))[:5]
    except Exception:  # noqa: BLE001 - un aperçu manquant ne casse pas le tour
        en_cours, finis = [], []
    if en_cours or finis:
        import json as _json_docs
        etat_docs = "ÉTAT DE TES DOCUMENTS (fait autorité, ne le devine jamais) :\n"
        if en_cours:
            etat_docs += (
                "- OUVERTS, non terminés (aucun fichier n'existe encore) :\n"
                + _json_docs.dumps(en_cours, ensure_ascii=False)
                + "\n  Ce sont TES documents pour les demandes en cours : "
                  "continue-les avec `ajouter_document` puis "
                  "`terminer_document`, en recopiant CE `document_id` caractère "
                  "pour caractère et SANS réécrire ce qui est déjà versé (le "
                  "compte d'éléments fait foi). N'en rouvre pas un du même "
                  "titre. Ne les jette JAMAIS de ta propre initiative, même si "
                  "la demande dit « nouveau » : un document déjà ouvert sous ce "
                  "titre EST le document demandé.\n")
        if finis:
            etat_docs += (
                "- TERMINÉS, fichier PRÊT et téléchargeable, mais PAS déposé "
                "sur le serveur :\n"
                + _json_docs.dumps(finis, ensure_ascii=False)
                + "\n  Ces documents ne se trouvent PAS en cherchant sur le "
                  "serveur : ils vivent ici, avec leur `document_id`. Titre, "
                  "taille, éléments et pages_estimees ci-dessus répondent "
                  "directement aux questions dessus.\n")
        bloc_resultats += etat_docs + "\n"

    # Aucun préambule sur l'absence de documents : c'est le modèle qui décide
    # s'il lui en faut, en appelant l'outil de recherche. Lui annoncer d'office
    # « aucun document » l'amenait à en parler même pour un simple bonjour.
    human_content = f"Question : {query}"
    if context_text:
        human_content = f"Documents disponibles :\n{context_text}\n\n{human_content}"
    human_content = bloc_resultats + human_content

    # Composants visuels : l'instruction est TOUJOURS présente.
    # Elle était auparavant conditionnée à des mots-clés (« devis », « tableau »…) pour
    # économiser ~340 tokens. Mauvais calcul, à deux titres :
    #   1. l'heuristique ratait l'essentiel des demandes — « lis les derniers mails »
    #      ne contient aucun mot-clé, donc le modèle ignorait jusqu'à l'existence des
    #      composants, et répondait en texte brut ;
    #   2. un préfixe système qui change d'un tour à l'autre DÉTRUIT le cache de prompt,
    #      dont l'entrée est facturée jusqu'à ~100× moins cher qu'un appel non caché.
    #      Un préfixe stable coûte donc moins que l'alternance qu'il évitait.
    system_prompt = SYSTEM_PROMPT + """

COMPOSANTS VISUELS. Dès que tu présentes des DONNÉES concrètes (mail, devis, facture, document, liste, tableau, indicateur, avancement, suggestions d'actions...), intercale un composant : insère au milieu de ta réponse un bloc balisé ```ui contenant un objet JSON, et rédige le texte normalement autour. Un composant vaut mieux qu'un paragraphe pour tout ce qui est structuré. Règle absolue : n'invente jamais de valeurs ; remplis TOUS les champs requis, sinon reste en texte simple (un composant incomplet ne s'affiche pas). Types :
- {"type":"email","subject":"...","from":"...","date":"...","preview":"..."}
- {"type":"quote","id":"...","client":"...","status":"draft|sent|accepted","total":"...","lines":[{"label":"...","qty":"...","price":"..."}]}
- {"type":"invoice","number":"...","client":"...","amount":"...","issued":"...","due":"...","status":"paid|pending|late"}
- {"type":"doc","name":"...","kind":"PDF|XLSX|DOCX","meta":"..."}
- {"type":"doc_apercu","titre":"...","format":"docx|pdf|xlsx","extrait":"..."} pour l'aperçu d'un document QU'ON A LU et qui n'est pas téléchargeable. Un document que TU viens de produire ou de déposer s'annonce par un bloc `fichier` et par lui seul : sa carte montre déjà le document. Ici : `extrait` reprend TEL QUEL le champ `extrait` (document produit) ou le début du `contenu`/`texte` rendu par la lecture. Jamais un résumé réécrit : l'aperçu montre le VRAI contenu.
- {"type":"contact","name":"...","role":"...","phone":"...","email":"..."}
- {"type":"project","name":"...","client":"...","progress":62,"status":"..."}
- {"type":"table","columns":["...","..."],"rows":[["...","..."]]}
- {"type":"keyvalue","rows":[["Clé","Valeur"]]}
- {"type":"list","items":["...","..."]}
- {"type":"callout","tone":"info|success|warning|error","title":"...","text":"..."}
- {"type":"bars","data":[{"label":"...","value":10}]} barres verticales, pour COMPARER quelques valeurs.
- {"type":"hbars","data":[{"label":"...","value":10}],"unit":"€"} barres horizontales : le meme classement quand les libelles sont longs (noms de fournisseurs, de chantiers). `unit` s'affiche apres chaque valeur.
- {"type":"donut","segments":[{"label":"...","value":45}]} anneau, pour une REPARTITION dont le total fait un tout (postes d'un budget, part de chaque corps d'etat). N'indique JAMAIS de couleur : elles viennent de la charte du client.
- {"type":"line","values":[12,19,15,27]} courbe, pour une EVOLUTION dans le temps. Les valeurs sont dans l'ordre chronologique.
- {"type":"gauge","value":68,"label":"..."} jauge de 0 a 100, pour un TAUX unique (marge, avancement, taux de remplissage).
- {"type":"progress","items":[{"label":"...","pct":72}]} plusieurs avancements compares, en pourcentage.
- {"type":"status_table","columns":["...","...","Statut"],"rows":[{"cells":["...","..."],"status":"ok|wait|late"}]} tableau dont la derniere colonne est une PASTILLE d'etat. `cells` ne contient PAS le statut, il est rendu a partir de `status`. Prefere-le au tableau simple des qu'une ligne a un etat (livree, en attente, en retard).
- {"type":"stat","label":"...","value":"...","hint":"..."}
- {"type":"badge","tone":"primary|success|warning|error|neutral","text":"..."}
- {"type":"quick_replies","options":["Proposition 1","Proposition 2"]}

SCHEMAS. Pour un enchainement d'etapes, une arborescence, un organigramme ou un circuit de validation, ecris un bloc ```mermaid (PAS ```ui, ce n'est pas un composant : c'est un dessin). Le schema se dessine aux couleurs du client, tu n'as donc aucune couleur ni aucun style a indiquer, seulement la structure. Exemple :
```mermaid
flowchart LR
  A[Demande recue] --> B{Devis existant ?}
  B -- oui --> C[Mise a jour]
  B -- non --> D[Redaction]
  C --> E[Validation]
  D --> E
```
Reserve-le a ce qu'un dessin explique mieux qu'une phrase. Une simple liste d'etapes se rend avec `list`, une repartition avec `donut` : un schema pour trois puces est plus lourd a lire que les puces.
Exemple, pour présenter des mails : une carte PAR message.
Voici les messages trouvés :
```ui
{"type":"email","subject":"CONTACT architecte","from":"lb@lbbl-architectes.fr","date":"23/07/2026","preview":"Demande d'intervention sur un projet a Sainte-Eulalie..."}
```""" + instruction_actions(state.get("user_role"))

    # CONSIGNES APPRISES, injectees a CHAQUE tour et non cherchees. Une regle de
    # comportement (« chez nous "le serveur" designe le NAS ») doit etre presente
    # AVANT que le modele choisisse son action : rangee en memoire, elle serait
    # retrouvee par ressemblance, donc parfois — et une regle qui vaut une fois
    # sur deux est pire qu'une regle absente.
    from learning.consignes import texte_injecte
    system_prompt += await texte_injecte(state.get("user_id"), state.get("user_role"))

    # Il y avait ici un rappel « ATTENTION, tu as annoncé sans exécuter »,
    # ajouté quand `relance_annonce` était levé. RETIRÉ, pour deux raisons.
    # D'abord il ne servait à rien : les traces montrent le rappel bien présent
    # dans le prompt, et le modèle annonçant quand même. Ensuite il est devenu
    # inatteignable — le drapeau n'est plus levé que par `forcer_action_node`,
    # qui va vers `tools` ou termine le tour, jamais vers une nouvelle passe de
    # ce nœud. Un garde-fou qui ne s'exécute pas rassure sans protéger : c'est
    # déjà ce qui avait rendu la première détection d'annonce si difficile à
    # débusquer. La reprise se fait maintenant dans un appel dédié.

    # Dernière passe imposée : la boucle d'actions est close, il ne reste qu'à
    # rédiger. Sans cette consigne, le modèle peut redemander une action, dont
    # le bloc serait retiré à l'affichage — donc une réponse vide.
    if state.get("tools_finished"):
        system_prompt += ("\n\nLa phase d'actions est TERMINÉE pour ce tour : n'émets plus "
                          "aucun bloc ```action. Rédige maintenant ta réponse finale à "
                          "partir des résultats ci-dessus.")
        # La raison d'une sortie sans résultat est expliquée par le modèle, dans
        # ses mots : l'utilisateur mérite une phrase, pas un code d'erreur.
        note = state.get("note_sortie")
        if note:
            system_prompt += (
                f"\nContexte : {note} Explique-le simplement à l'utilisateur, en une "
                "phrase, et propose une suite utile. Ne recopie pas cette note telle "
                "quelle et n'affiche aucune parenthèse technique.")

    # [système] + [historique masqué] + [tour courant] : c'est ce qui donne la mémoire.
    messages = [SystemMessage(content=system_prompt)] + list(history) + [
        HumanMessage(content=human_content)
    ]
    response = await llm.ainvoke(messages, config=config)

    # Ne JAMAIS mettre en cache une réponse qui demande une action : son contenu
    # utile n'est pas la réponse mais l'action, et la resservir sauterait
    # l'exécution. Idem après une action : le résultat n'est pas rejouable.
    _sortie = str(response.content or "")
    if (not en_boucle_outils and not BLOC_ACTION_RE.search(_sortie)
            and not BLOC_NATIF_RE.search(_sortie)):
        response_cache.set(tier, query, context_text, response.content, cache_scope)

    usage = getattr(response, "usage_metadata", None) or {}
    return {
        "llm_response": response.content,
        "tokens_in": usage.get("input_tokens", 0),
        "tokens_out": usage.get("output_tokens", 0),
        "model_used": llm.last_model_used,
        # L'historique n'est PLUS émis ici mais dans `rehydrate_node` : avec la
        # boucle d'outils, ce nœud s'exécute plusieurs fois par tour et ajouterait
        # autant de paires — les réponses intermédiaires (blocs action) pollueraient
        # la mémoire de conversation.
        # Jetons réellement PRÉSENTS dans ce qui a été envoyé au modèle ce tour-ci.
        # La réhydratation sera restreinte à cet ensemble : la map étant cumulative,
        # réhydrater aveuglément permettrait au modèle de ressortir un [PER_n] d'un
        # tour sans rapport et d'y réinjecter une vraie valeur (donnée fausse dans un
        # contexte faux — exactement la classe de bug qu'on répare ici).
        "turn_placeholders": sorted(
            anonymizer.find_placeholders(human_content).union(
                *[anonymizer.find_placeholders(str(getattr(m, "content", "") or ""))
                  for m in history] or [set()]
            )
        ),
    }


async def tools_node(state: AgentState, config=None) -> dict:
    """Exécute UNE action demandée par le modèle, puis lui rend la main.

    Un seul outil par passage : la boucle repasse par `llm` entre chaque action.
    Cela borne le raisonnement, rend chaque étape visible dans le streaming, et
    évite qu'un effet de bord ne soit produit avant une éventuelle suspension.

    Les actions à effet EXTERNE ne sont jamais exécutées ici : elles arment le
    `human_gate` du graphe parent, qui suspend le tour jusqu'à décision humaine.
    """
    import asyncio
    import json as _json

    from security.anonymizer import anonymizer
    from skills.protocol import extraire_action
    from skills.executor import execute_skill, hash_payload, SkillError, effet_du_skill
    from tasks.identity import charger_executant

    # Le rôle est transmis pour que la vue qui VALIDE soit exactement celle
    # qui a été ANNONCÉE au modèle. Un écart entre les deux se lirait comme
    # une fuite : un skill hors périmètre deviendrait appelable.
    action, texte, erreur = extraire_action(
        state.get("llm_response") or "", state.get("user_role"))
    iteration = (state.get("tool_iterations") or 0) + 1
    resultats = list(state.get("tool_results") or [])

    def _sortir(note: str | None = None) -> dict:
        """Termine la boucle, en garantissant qu'une VRAIE réponse sera rédigée.

        Le contrat de la boucle est : le modèle demande une action, puis rédige
        au vu de son résultat. Si l'on sort sans qu'aucun résultat ne lui soit
        jamais revenu, son dernier texte est par construction une parole
        d'AVANT l'action — « Je vais d'abord chercher... » — et non une réponse.
        Observé en production : des tours entiers réduits à cette annonce, ou à
        la note du garde-fou toute seule.

        On force donc une dernière passe de rédaction, en lui transmettant la
        raison de la sortie pour qu'il l'explique lui-même plutôt que de coller
        une note technique à l'utilisateur. La passe est bornée : `tools_finished`
        étant posé, `route_apres_llm` ira en réhydratation quoi qu'il produise.
        """
        corps = (texte or "").strip()
        if not resultats or not corps:
            if note:
                logger.info("Sortie de boucle sans aboutissement (%s) — rédaction forcée", note)
            return {"llm_response": "", "tools_finished": True,
                    "tool_iterations": iteration, "note_sortie": note}
        return {"llm_response": corps + (f"\n\n{note}" if note else ""),
                "tools_finished": True, "tool_iterations": iteration}

    if erreur:
        # Bloc mal formé : on renvoie l'erreur au modèle pour qu'il se corrige,
        # mais un nombre BORNÉ de fois — sinon deux modèles têtus boucleraient
        # à l'infini.
        #
        # DEUX PLUTÔT QU'UNE. Relevé en production le 14/08 : deux sorties
        # coupées d'affilée sur le même tour (le modèle a réessayé aussi long).
        # La première armait la reprise, la seconde terminait le tour — après
        # dix minutes de rédaction, sans rien avoir versé. Corriger un volume
        # demande parfois deux essais ; chacun coûte un appel, et le plafond
        # reste franc.
        reparations = int(state.get("tool_repair_used") or 0)
        if reparations >= MAX_REPARATIONS_PAR_TOUR:
            return _sortir("le modèle n'a pas réussi à produire une action "
                           "exploitable, même après correction.")
        resultats.append({"skill": None, "ok": False,
                          "resultat_masque": f"ERREUR : {erreur}."})
        return {"tool_results": resultats, "tool_iterations": iteration,
                "tool_repair_used": reparations + 1}

    if action is None:
        return _sortir()

    if iteration > MAX_ACTIONS_PAR_TOUR:
        # Formulé comme une RAISON, pas comme un texte à afficher : c'est le
        # modèle qui la met en mots pour l'utilisateur.
        #
        # Le mot RECHERCHES était faux : le budget porte sur les ACTIONS, quelles
        # qu'elles soient. Sur une demande de document, l'utilisateur lisait
        # « le nombre de recherches autorisées est atteint » alors qu'aucune
        # recherche n'avait eu lieu — un message qui égare au lieu d'expliquer.
        return _sortir("le nombre d'actions autorisées pour ce tour est atteint "
                       "sans que la demande ait abouti.")

    # Les paramètres arrivent masqués (le modèle ne voit que du texte anonymisé).
    # On les réhydrate avec les MÊMES bornes que la réponse finale : uniquement
    # les jetons réellement envoyés ce tour-ci.
    autorises = set(state.get("turn_placeholders") or [])
    carte = {k: v for k, v in (state.get("entity_map") or {}).items() if k in autorises}
    args = {k: (anonymizer.rehydrate(v, carte) if isinstance(v, str) else v)
            for k, v in action["args"].items()}

    empreinte = hash_payload(action["skill"], args)
    deja = [r for r in resultats if r.get("payload_hash") == empreinte]
    if deja:
        # UNE ACTION QUI A ÉCHOUÉ NE RÉUSSIRA PAS EN LA REDEMANDANT TELLE QUELLE.
        #
        # Relevé sur les deux projets, le même jour : « il y a combien de
        # fichiers dans le dossier ? » → l'outil refuse (aucun périmètre
        # configuré) → le modèle redemande à l'identique → le garde-fou
        # s'arme, et l'utilisateur reçoit « l'action a été redemandée à
        # l'identique sans que la demande avance ». Une note technique sur la
        # MÉCANIQUE, à la place de la seule chose qui l'intéressait : POURQUOI
        # ça n'a pas marché.
        #
        # On sort donc dès la première répétition quand l'original a échoué, et
        # on remonte SA raison. Le modèle la met en mots ; l'utilisateur
        # apprend qu'il manque une configuration, au lieu de croire que
        # l'assistant tourne en rond.
        if not deja[0].get("ok"):
            raison = str(deja[0].get("resultat_masque") or "").strip()
            return _sortir(f"l'action « {action['skill']} » a échoué et redonnerait "
                           f"le même résultat : {raison[:400]}")
        # DEUXIÈME REDEMANDE IDENTIQUE : le tour n'avance plus. Insister ne peut
        # rien produire de neuf — la réponse serait la même — et chaque passe
        # coûte un appel de modèle. On arrête et on dit pourquoi.
        if len(deja) >= 2:
            return _sortir(f"l'action « {action['skill']} » a été redemandée à "
                           "l'identique sans que la demande avance.")
        # Le modèle redemande la même action : on ressert son RÉSULTAT plutôt que
        # de la rejouer. Il contenait auparavant « (déjà exécuté ce tour) » et
        # rien d'autre — or c'est justement là que se trouvait l'identifiant du
        # document dont le modèle avait besoin. On lui reprenait l'information au
        # moment précis où il la redemandait.
        resultats.append({**deja[0], "resultat_masque":
                          "(déjà exécuté à ce tour, son résultat est inchangé)\n"
                          + str(deja[0].get("resultat_masque") or "")})
        return {"tool_results": resultats, "tool_iterations": iteration}

    # L'EFFET SE DEMANDE À L'AUTORITÉ, il ne se lit pas dans une table.
    #
    # Ce nœud interrogeait `EFFETS_NATIFS` en direct. Quand les skills du NAS et
    # de la bibliothèque d'outils sont passés au registre, ils ont quitté cette
    # table — et `.get(nom, "externe")` les a donc TOUS classés en effet externe.
    # Résultat : lister un dossier demandait une validation humaine, et la
    # bibliothèque entière devenait inutilisable. Rien ne le signalait : le
    # défaut de sécurité est verrouillant, donc silencieux.
    #
    # `effet_du_skill` est le seul endroit qui connaît les deux sources (table
    # du socle, puis registre du projet) et garde le même défaut fail-closed.
    effet = effet_du_skill(action["skill"])
    if effet == "externe":
        # JAMAIS exécuté ici. On arme la validation humaine du graphe parent.
        return {
            "llm_response": texte or f"Action « {action['skill']} » en attente de validation.",
            "pending_action": {"skill": action["skill"], "args": args,
                               "effet": effet, "payload_hash": empreinte},
            "requires_validation": True,
            "validation_reason": f"Action à effet externe : {action['skill']}",
            "validation_payload": {"skill": action["skill"], "args": args,
                                   "payload_hash": empreinte},
            "tools_finished": True, "tool_iterations": iteration,
        }

    # Identité RECHARGÉE au moment d'agir : un compte désactivé entre-temps ne
    # doit plus rien pouvoir faire, même si le tour a commencé avant.
    utilisateur = await charger_executant(state.get("user_id"))
    if utilisateur is None:
        return _sortir("ce compte n'est plus actif, aucune action n'a pu être exécutée.")

    try:
        brut = await execute_skill(
            action["skill"], args, user=utilisateur,
            trigger={"type": state.get("trigger_kind") or "chat",
                     "id": state.get("thread_id")},
        )
        plafond = (PLAFOND_RESULTAT_GENEREUX
                   if action["skill"] in RESULTATS_GENEREUX else PLAFOND_RESULTAT)
        contenu = _json.dumps(brut.get("output"), ensure_ascii=False,
                              default=str)[:plafond]
        ok = True
    except SkillError as e:
        contenu, ok = f"ERREUR : {e}", False
    except Exception as e:  # noqa: BLE001 - inclut le 403 de verifier_acces
        contenu, ok = f"ERREUR : {getattr(e, 'detail', None) or e}", False

    # Le résultat repart vers le modèle : il doit être masqué, avec la carte
    # cumulative du fil pour que les jetons restent cohérents.
    masques, carte_maj = await asyncio.to_thread(
        anonymizer.anonymize_chunks, [contenu], state.get("entity_map") or {})
    resultats.append({"skill": action["skill"], "ok": ok, "payload_hash": empreinte,
                      "resultat_masque": masques[0]})
    # UNE ACTION A ABOUTI : le drapeau de relance retombe, pour que le modele
    # puisse etre repris s'il cale de nouveau plus loin.
    #
    # Une seule relance par TOUR ne suffisait pas : produire un document en
    # demande trois d'affilee (creer, remplir, terminer), et le modele annonce
    # entre chacune. Il repartait apres la premiere relance, puis s'arretait a la
    # suivante — « je vais ajouter le nombre de dossiers dans le document cree ».
    #
    # SEULEMENT SI ELLE A ABOUTI. Le code le rearmait aussi apres un ECHEC,
    # contrairement a ce que cette explication promettait : une action qui rate
    # en boucle redonnait donc un forcage a chaque tour, sans que rien n'avance.
    # C'est exactement la boucle que ce commentaire disait impossible.
    # UN VERSEMENT QUI A RÉELLEMENT ÉCRIT NE CONSOMME PAS LE BUDGET.
    #
    # Le budget existe contre les tours qui TOURNENT EN ROND. Remplir un
    # document long, lui, avance à chaque appel — et le catalogue demande
    # explicitement de le remplir en plusieurs fois. Les deux règles se
    # contredisaient : « raconte une histoire de dix pages » ouvrait le
    # document, versait quelques sections, puis se faisait couper par le
    # garde-fou, avec en prime un message parlant de « recherches ».
    #
    # Le rejeu n'est pas ouvert pour autant : on n'exempte que les versements
    # qui ont retenu au moins un bloc, et le document a sa propre borne
    # (20 000 éléments), après quoi l'ajout échoue et le budget reprend ses
    # droits.
    versements = int(state.get("versements") or 0)
    a_verse = False
    if ok and action["skill"] in ("ajouter_document",) and versements < MAX_VERSEMENTS_PAR_TOUR:
        try:
            a_verse = int((brut.get("output") or {}).get("ajoutes") or 0) > 0
        except (AttributeError, TypeError, ValueError):
            a_verse = False

    # LE JALON QUI FERME NE CONSOMME PAS LE BUDGET. Relevé en production :
    # « créer un docx de 10 pages » s'est terminé sur « le nombre d'actions
    # autorisées est atteint » — le budget de 8 se faisait manger par la
    # fermeture, en plus des recherches. Un `terminer_document` qui RÉUSSIT ne
    # peut pas boucler : il ferme le document, et le rouvrir passe par
    # `creer_document`, qui reste compté (cf. S11 : le forceur qui rouvre un
    # document à chaque passe).
    #
    # `abandonner_document` A ÉTÉ RETIRÉ DE CETTE EXEMPTION. Je l'y avais mis
    # en raisonnant « il consomme un document ouvert, donc il ne peut pas
    # boucler » — c'était faux, et la production l'a montré le jour même :
    # abandonner LIBÈRE une place, créer la reprend, et le cycle
    # abandon → création → remplissage → abandon tourne sans jamais croiser de
    # plafond. Huit minutes, deux fois le travail détruit. Un geste qui DÉFAIT
    # n'est jamais un geste qui avance.
    jalon = ok and action["skill"] == "terminer_document"

    avance = a_verse or jalon
    maj = {"tool_results": resultats,
           "tool_iterations": (state.get("tool_iterations") or 0) if avance else iteration,
           "versements": versements + 1 if a_verse else versements,
           "entity_map": carte_maj}
    if ok:
        maj["relance_annonce"] = False
    return maj


async def rehydrate_node(state: AgentState) -> dict:
    """Réinjecte les vraies entités dans la réponse via entity_map."""
    from security.anonymizer import anonymizer

    from langchain_core.messages import AIMessage
    from skills.protocol import (BLOC_ACTION_RE, BLOC_ACTION_TRONQUE_RE,
                                 BLOC_NATIF_RE, BALISAGE_OUTIL_RE)

    text = state.get("llm_response", "") or ""
    # Filet : si une demande d'action survit jusqu'ici (sortie de boucle, limite
    # atteinte), elle ne doit pas s'afficher — c'est de la mécanique interne.
    # Les passes couvrent le bloc demandé, le bloc COUPÉ par le plafond de
    # sortie, la syntaxe native d'un modèle de la cascade, puis tout balisage
    # résiduel quel qu'en soit l'émetteur.
    text = BLOC_ACTION_RE.sub("", text)
    # Un bloc ouvert et jamais refermé échappait aux trois filtres : relevé en
    # production, 8 000 caractères de JSON affichés à l'utilisateur.
    text = BLOC_ACTION_TRONQUE_RE.sub("", text)
    text = BLOC_NATIF_RE.sub("", text)
    text = BALISAGE_OUTIL_RE.sub("", text).strip()
    if not text:
        # Dernier filet : mieux vaut une phrase honnête qu'une bulle vide.
        text = ("Je n'ai pas réussi à formuler de réponse pour cette demande. "
                "Pouvez-vous la reformuler ?")

    entity_map = state.get("entity_map") or {}
    # Restreint aux jetons envoyés ce tour-ci (cf. turn_placeholders dans llm_node).
    allowed = state.get("turn_placeholders")
    if allowed is not None:
        allowed = set(allowed)
        entity_map = {k: v for k, v in entity_map.items() if k in allowed}

    sortie = {"final_response": anonymizer.rehydrate(text, entity_map)}

    # UN TOUR SANS EFFET NE S'ÉCRIT PAS DANS L'HISTORIQUE.
    #
    # Le modèle relit ses propres tours. Quand une annonce sans acte y est
    # rangée, elle devient un EXEMPLE : au tour suivant il la recopie, et
    # l'exemple se duplique. Relevé dans les traces, l'historique envoyé au
    # modèle contenait quatre tours d'assistant d'affilée qui n'étaient que
    # « je vais compter les dossiers, puis créer le PDF » — après quoi aucune
    # consigne système ne pesait plus rien face à quatre démonstrations du
    # contraire.
    #
    # On ne coupe que le cas AVÉRÉ : la reprise a déjà eu lieu ce tour-ci
    # (`relance_annonce`), aucune action n'a abouti, et le texte est encore une
    # promesse. Le tour n'a alors rien produit — l'oublier ne perd rien et
    # évite d'enseigner le geste. La question posée à l'utilisateur est
    # épargnée : elle, appelle une réponse et doit rester dans le fil.
    resultats = state.get("tool_results") or []
    rien_fait = not any(r.get("ok") for r in resultats)
    if state.get("relance_annonce") and rien_fait and "?" not in text \
            and est_une_annonce(text):
        logger.info("Tour sans effet — annonce ni affichée ni enregistrée")
        # ET LA PROMESSE NE S'AFFICHE PAS NON PLUS. Laisser « je vais créer le
        # PDF » en réponse d'un tour qui n'a rien fait rend l'échec indiscernable
        # d'un affichage manquant : on ne sait plus si l'assistant travaille
        # encore, s'il s'est arrêté, ou si l'écran ne suit pas. Une phrase nette
        # vaut mieux qu'une promesse : le tour est fini, et rien n'a été produit.
        sortie["final_response"] = (
            "Je n'ai pas réussi à exécuter l'action : rien n'a été fait. "
            "Reformulez la demande, ou découpez-la en une seule étape à la fois.")
        return sortie

    # L'historique est émis ICI, et non dans `llm_node` : ce nœud s'exécute
    # exactement une fois par tour, quel que soit le nombre d'actions. On n'y
    # stocke QUE du texte masqué : aucune PII ne dort dans le checkpoint ni ne
    # repart vers le LLM.
    sortie["messages"] = [
        HumanMessage(content=state.get("anonymized_query") or state.get("query", "")),
        AIMessage(content=text),
    ]
    return sortie


async def validation_check_node(state: AgentState) -> dict:
    """Détecte si la réponse nécessite une validation humaine (devis, envoi client...)."""
    """Détecte si la réponse nécessite une validation humaine.

    PRÉSERVE le drapeau posé en amont : `tools_node` le lève quand une action à
    effet externe attend une décision. L'écraser à False annulerait la demande de
    validation juste avant le `human_gate`, et l'action s'exécuterait sans accord.
    """
    # TODO (cas d'usage métier) : heuristique supplémentaire sur final_response.
    return {"requires_validation": bool(state.get("requires_validation"))}


# ── Edges conditionnels ───────────────────────────────────────────────

def route_apres_routeur(state: AgentState) -> str:
    """Décision du routeur : rédaction directe, ou consultation de la mémoire."""
    return "recherche" if state.get("besoin_memoire") else "llm"


def should_use_browser(state: AgentState) -> str:
    """Après une recherche infructueuse, tenter le web (si activé)."""
    from config import settings
    if state.get("browser_used") or not settings.browser_enabled:
        return "llm"
    trouve = (state.get("anonymized_chunks") or []) or (state.get("raw_chunks") or [])
    return "llm" if trouve else "browser"


def should_validate(state: AgentState) -> str:
    return "wait_for_human" if state.get("requires_validation") else END


# ── Graph ─────────────────────────────────────────────────────────────

async def forcer_action_node(state: AgentState, config=None) -> dict:
    """Le modèle a annoncé une action sans l'émettre : on la lui FAIT produire.

    POURQUOI UN APPEL À PART, ET NON UNE CONSIGNE DE PLUS. La version précédente
    se contentait de rendre la main au modèle avec un « ATTENTION, tu as annoncé
    sans exécuter » ajouté au prompt système. Les traces montrent que cette
    consigne ÉTAIT bien présente et qu'il a annoncé quand même : dans le même
    contexte se trouvaient quatre de ses propres tours ne contenant qu'une
    promesse. Une phrase d'instruction ne pèse rien contre quatre démonstrations
    du contraire, et durcir encore la formulation ne ferait que répéter l'échec.

    On change donc de levier. Cet appel-ci part d'un contexte NEUF : ni
    historique, ni documents, ni personnalité — le catalogue des actions, la
    demande, ce qui a déjà été fait, et l'intention annoncée. Sa seule sortie
    admise est un bloc ```action. Le modèle n'a plus à choisir entre parler et
    agir : parler n'est plus une réponse possible.

    Le bloc obtenu repart dans `llm_response` et le tour continue par `tools` :
    l'exécution reste au SEUL endroit qui contrôle les droits, classe l'effet et
    déduplique. Ce nœud choisit, il n'exécute pas.
    """
    import json as _json
    from skills.protocol import (instruction_actions, extraire_action,
                                 rafraichir_catalogue)

    role = state.get("user_role")
    await rafraichir_catalogue()

    consigne = (
        "Tu es le sélecteur d'actions d'un assistant interne. Ta SEULE sortie "
        "admise est un bloc ```action. N'écris ni phrase, ni explication, ni "
        "commentaire : tout texte hors du bloc est jeté sans être lu."
        + instruction_actions(role) +
        "\n\nLes identifiants (document_id, chemins, références) se RECOPIENT "
        "depuis les résultats fournis, caractère pour caractère. N'en invente "
        "jamais un qui ressemble : il serait rejeté."
        "\n\nSi, et seulement si, aucune action de la liste ne peut faire "
        "avancer la demande, réponds le seul mot RIEN, sans bloc."
    )

    # LE RÉSULTAT, PAS SEULEMENT LE VERDICT. La première version ne listait que
    # « creer_document : réussie » — sans le `document_id` qu'elle avait rendu.
    # Le modèle, à qui l'on demandait l'action suivante, ne pouvait donc pas la
    # former : il a inventé un identifiant plausible, l'ajout a été refusé, et il
    # a rouvert un document en boucle. Un sélecteur d'actions à qui l'on cache ce
    # que les actions ont produit ne peut pas enchaîner.
    lignes = []
    for r in (state.get("tool_results") or []):
        brut = str(r.get("resultat_masque") or "")
        # Tronqué : ce nœud a besoin des identifiants (en tête des résultats),
        # pas du contenu entier — le modèle principal, lui, l'a déjà.
        extrait = brut[:800] + (" […tronqué]" if len(brut) > 800 else "")
        lignes.append(f"- {r.get('skill') or '?'} : "
                      f"{'réussie' if r.get('ok') else 'EN ÉCHEC'}\n"
                      f"  résultat : {extrait}")
    faits = "\n".join(lignes) or "- aucune"

    demande = (
        "Demande de l'utilisateur :\n"
        f"{state.get('anonymized_query') or state.get('query', '')}\n\n"
        f"Actions déjà exécutées à ce tour :\n{faits}\n\n"
        "L'assistant vient d'écrire cette intention SANS l'exécuter :\n"
        f"« {(state.get('llm_response') or '').strip()[:400]} »\n\n"
        "Produis le bloc ```action de la PROCHAINE action à exécuter."
    )

    # Quand un travail est resté OUVERT, on ne laisse pas deviner : dire quelle
    # fermeture manque évite qu'un document déjà rempli soit rouvert une fois de
    # plus — c'est exactement la boucle qu'on a observée.
    manquante = cloture_attendue(state.get("tool_results"))
    if manquante:
        demande += (
            f"\n\nATTENTION : un document est OUVERT et n'a pas été fermé. Tant "
            f"que `{manquante}` n'a pas été appelé, AUCUN fichier n'existe, il "
            f"n'y a donc rien à télécharger ni à déposer. C'est l'action "
            f"attendue, avec le `document_id` déjà rendu. N'en ouvre pas un "
            f"nouveau : le travail déjà versé serait perdu.")

    # Un document ouvert lors d'un TOUR PRÉCÉDENT n'apparaît pas dans les
    # résultats de ce tour : l'atelier est le seul à s'en souvenir. Sans
    # l'identifiant sous les yeux, ce sélecteur en inventerait un plausible —
    # c'est la boucle documentée plus haut, jouée depuis un autre point d'entrée.
    try:
        import asyncio as _aio
        from bureautique.atelier import ouverts as _docs_ouverts
        from bureautique.atelier import termines as _docs_termines
        _uid = str(state.get("user_id") or "")
        en_cours = await _aio.to_thread(_docs_ouverts, _uid)
        finis = (await _aio.to_thread(_docs_termines, _uid))[:5]
    except Exception:  # noqa: BLE001
        en_cours, finis = [], []
    if en_cours:
        demande += (
            "\n\nDocument(s) encore OUVERTS de tours précédents :\n"
            + _json.dumps(en_cours, ensure_ascii=False)
            + "\nSi l'intention annoncée est de CONTINUER ce document, l'action "
              "attendue est `ajouter_document` (puis `terminer_document`) avec "
              "ce `document_id`, recopié caractère pour caractère.")
    if finis:
        demande += (
            "\n\nDocument(s) TERMINÉS (fichier prêt, pas déposé) :\n"
            + _json.dumps(finis, ensure_ascii=False)
            + "\nSi l'intention est de DÉPOSER ou de montrer un de ces "
              "documents, utilise SON `document_id`, pas celui d'un document "
              "vide.")

    llm = get_llm(LLMTier(state.get("llm_tier", "standard")))
    try:
        reponse = await llm.ainvoke(
            [SystemMessage(content=consigne), HumanMessage(content=demande)],
            config=config)
        texte = str(reponse.content or "")
    except Exception as e:  # noqa: BLE001 - un forçage raté n'est pas une panne
        logger.warning("Forçage d'action impossible : %s", e)
        return {"relance_annonce": True}

    action, _, erreur = extraire_action(texte, role)
    if action is None:
        # Le drapeau reste levé : le tour est reconnu sans effet, la promesse ne
        # sera ni affichée comme une réponse ni rangée dans l'historique.
        logger.info("Forçage sans résultat (%s)", erreur or "aucun bloc produit")
        return {"relance_annonce": True}

    logger.info("Action forcée : %s", action.get("skill"))
    return {"relance_annonce": True,
            "llm_response": "```action\n"
                            + _json.dumps(action, ensure_ascii=False) + "\n```"}


def route_apres_forcage(state: AgentState) -> str:
    """L'action a-t-elle pu être produite ?"""
    from skills.protocol import BLOC_ACTION_RE
    if BLOC_ACTION_RE.search(state.get("llm_response") or ""):
        return "tools"
    # Rien n'a pu être produit : inutile de refaire tourner le modèle, il vient
    # de refuser deux fois. On termine le tour, et l'utilisateur l'apprend.
    return "rehydrate"


def route_apres_llm(state: AgentState) -> str:
    """Le modèle a-t-il demandé une action ?"""
    from skills.protocol import BLOC_ACTION_RE, BLOC_NATIF_RE
    if state.get("tools_finished"):
        return "rehydrate"
    texte = state.get("llm_response") or ""
    # Deux syntaxes : le bloc demandé, et celle que certains modèles de la
    # cascade émettent d'eux-mêmes. Ignorer la seconde la laissait s'afficher.
    demande = BLOC_ACTION_RE.search(texte) or BLOC_NATIF_RE.search(texte)
    if demande:
        return "tools"
    # ANNONCE SANS ACTE. « Je crée le PDF » sans bloc d'action : le tour se
    # terminait ici, sur une promesse présentée comme une réponse.
    #
    # La détection doit vivre ICI et nulle part ailleurs : sans bloc d'action,
    # `tools` n'est JAMAIS appelé, donc un contrôle placé là-bas ne s'exécute
    # pas — il en avait tout l'air, et c'est ce qui l'a rendu difficile à voir.
    if not state.get("relance_annonce") and est_une_annonce(texte):
        return "forcer"

    # TRAVAIL RESTÉ OUVERT. Le signal qui ne dépend pas des mots : un document
    # ouvert et jamais fermé n'a produit aucun fichier, quoi qu'en dise la
    # réponse. La détection par formulation, elle, énumère des verbes et en
    # oublie toujours un — « je crée » était couvert, « j'y ajoute » non, et le
    # tour s'est arrêté sur la promesse.
    #
    # Pas de boucle possible : la fermeture aboutie retire l'attente, et le
    # budget d'actions du tour borne le reste.
    if cloture_attendue(state.get("tool_results")):
        return "forcer"
    return "rehydrate"


def route_apres_tools(state: AgentState) -> str:
    """Après une action : rendre la main au modèle, ou terminer le tour.

    On termine dès qu'une action externe attend une validation : le graphe parent
    prend le relais avec `human_gate`.
    """
    if state.get("pending_action"):
        return "rehydrate"
    if state.get("tools_finished"):
        # Boucle terminée mais rien de rédigé : une dernière passe de rédaction,
        # bornée (`tools_finished` étant posé, `route_apres_llm` ira en
        # réhydratation quoi que produise le modèle).
        return "rehydrate" if (state.get("llm_response") or "").strip() else "llm"
    return "llm"


def build_agent1_graph():
    graph = StateGraph(AgentState)
    graph.add_node("rag", rag_node)
    graph.add_node("anonymize", anonymize_node)
    graph.add_node("browser", browser_node)
    graph.add_node("routeur", routeur_node)
    graph.add_node("recherche", recherche_node)
    graph.add_node("llm", llm_node)
    graph.add_node("tools", tools_node)
    graph.add_node("rehydrate", rehydrate_node)
    graph.add_node("validation_check", validation_check_node)

    graph.set_entry_point("rag")
    graph.add_edge("rag", "anonymize")
    # Protection des données -> le routeur (IA) décide -> recherche SI nécessaire.
    graph.add_edge("anonymize", "routeur")
    graph.add_conditional_edges("routeur", route_apres_routeur,
                                {"recherche": "recherche", "llm": "llm"})
    # Le navigateur n'est tenté qu'APRÈS une recherche interne infructueuse.
    graph.add_conditional_edges("recherche", should_use_browser,
                                {"browser": "browser", "llm": "llm"})
    graph.add_edge("browser", "llm")
    # Boucle d'outils : llm -> tools -> llm -> ... jusqu'à ce que le modèle réponde
    # sans demander d'action (ou que le garde-fou l'arrête).
    # Annonce sans acte : on ne redemande pas au modèle de bien vouloir agir (il
    # a déjà refusé une fois, consigne en main) — on lui fait produire l'action
    # dans un appel dédié, puis on l'exécute.
    graph.add_node("forcer", forcer_action_node)
    graph.add_conditional_edges("llm", route_apres_llm,
                                {"tools": "tools", "forcer": "forcer",
                                 "rehydrate": "rehydrate"})
    graph.add_conditional_edges("forcer", route_apres_forcage,
                                {"tools": "tools", "rehydrate": "rehydrate"})
    graph.add_conditional_edges("tools", route_apres_tools,
                                {"llm": "llm", "rehydrate": "rehydrate"})
    graph.add_edge("rehydrate", "validation_check")
    graph.add_conditional_edges("validation_check", should_validate)

    return graph.compile()


agent1_graph = build_agent1_graph()
