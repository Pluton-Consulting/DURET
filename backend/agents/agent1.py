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
RÈGLE DE RECHERCHE : la mémoire a DÉJÀ été consultée pour toi quand la demande le justifiait. Si des documents te sont fournis, réponds à partir d'eux. Si aucun ne l'est, c'est que la demande n'en nécessitait pas, ou que la mémoire ne contient rien : ne relance l'action `rechercher_documents` que si la réponse dépend manifestement d'une donnée interne qui te manque, avec des termes DIFFÉRENTS. Pour une salutation, un remerciement, une question générale ou une demande de rédaction, réponds directement, SANS aucune action et SANS parler de la mémoire d'entreprise.
Ne liste JAMAIS de contenu imaginaire et ne prétends pas avoir des dossiers que la recherche ne t'a pas rendus.
Réponds toujours en français, de façon précise, professionnelle et concise. Sois utile pour : retrouver un dossier par chantier, faire le point sur des commandes / réserves / échéances, préparer un brouillon de réponse à un mail, suivre un dossier juridique ou un règlement fournisseur.
Certaines valeurs des documents peuvent apparaître masquées sous forme de balises [PER_1], [MONTANT_2], etc. — conserve-les telles quelles. Ne CRÉE jamais toi-même de balise entre crochets.
Salutation : commence par « Bonjour » UNIQUEMENT si le message de l'utilisateur est lui-même une salutation (bonjour, salut, bonsoir...) ; sinon, pour une question de travail, réponds DIRECTEMENT, sans « Bonjour » ni formule d'accueil, et sans jamais répéter une salutation déjà faite dans la conversation. Ne dis JAMAIS « je suis Duret & Sols » ni « je m'appelle Duret & Sols » (c'est le nom de l'entreprise, pas ton identité à énoncer) et ne te présente pas. Pour une question de travail, réponds directement.
N'invente JAMAIS de donnée (montant, nom, date, nombre, référence de dossier). Tout chiffre que tu avances doit provenir d'un document que la recherche t'a rendu, ou de ce que l'utilisateur vient de te dire. Les décisions engageantes (envoi d'un mail, facturation, action juridique) restent validées par un humain.
DONNÉE MANQUANTE : quand on te demande de remplir une fiche, un tableau, un récapitulatif ou un modèle et qu'une information ne figure nulle part, écris exactement [À COMPLÉTER] à sa place. Ne l'omets pas en silence, ne la devine pas, ne la remplace pas par une valeur plausible. Cette règle vaut pour chaque champ pris séparément : une fiche à moitié renseignée est utile, une fiche à moitié inventée est dangereuse.
Typographie : n'utilise JAMAIS de tiret cadratin (—) ni de tiret demi-cadratin (–) ; emploie plutôt une virgule, un deux-points, une parenthèse ou un tiret simple « - »."""


# Nombre maximal d'actions exécutées dans un même tour. Chaque action coûte un
# aller-retour LLM supplémentaire : au-delà, le modèle tourne en rond plus qu'il
# n'avance, et la facture grimpe pour rien.
MAX_ACTIONS_PAR_TOUR = 3


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
    return {"raw_chunks": [f"[FICHIER JOINT PAR L'UTILISATEUR — {nom}]\n{texte_joint}"]}


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
        return {"besoin_memoire": False}

    invite = (
        "Tu orientes une demande adressée à l'assistant interne d'une entreprise.\n"
        "Dis UNIQUEMENT s'il faut consulter la mémoire d'entreprise (chantiers, devis, "
        "factures, commandes, dossiers, mails, documents internes) pour répondre.\n"
        "- Salutation, remerciement, question générale, demande de rédaction ou de "
        "reformulation, suite directe de la conversation : AUCUNE recherche.\n"
        "- Question portant sur un dossier, un client, un montant, un document ou un "
        "mail de l'entreprise : recherche NÉCESSAIRE.\n"
        'Réponds par un objet JSON seul : {"memoire": true|false, "requete": '
        '"<mots-clés de recherche si true, sinon vide>"}\n\n'
        f"Demande : {question}"
    )

    try:
        reponse = await get_llm(_T.LIGHT).ainvoke([_H(content=invite)])
        trouve = _re.search(r"\{.*\}", str(reponse.content), _re.S)
        decision = _json.loads(trouve.group(0)) if trouve else {}
        besoin = bool(decision.get("memoire"))
        requete = str(decision.get("requete") or "").strip() or question
    except Exception as e:  # noqa: BLE001
        # En cas d'échec, on CHERCHE : répondre « je n'ai rien » alors que la
        # mémoire contient la réponse est bien pire qu'une recherche inutile.
        logger.info("Routage indisponible (%s) — recherche par défaut", e)
        besoin, requete = True, question

    logger.debug("Routage : mémoire=%s", besoin)
    return {"besoin_memoire": besoin, "requete_memoire": requete}


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
            "[SOURCE WEB — information externe, à mentionner et valider]\n" + result["content"]
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
    from skills.protocol import instruction_actions, BLOC_ACTION_RE, BLOC_NATIF_RE

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
        bloc_resultats = (
            "Résultats des actions déjà exécutées pour cette demande (ne les relance "
            "pas, appuie-toi dessus pour répondre) :\n"
            + _json_out.dumps(resultats_outils, ensure_ascii=False, default=str)[:6000]
            + "\n\n")

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
- {"type":"contact","name":"...","role":"...","phone":"...","email":"..."}
- {"type":"project","name":"...","client":"...","progress":62,"status":"..."}
- {"type":"table","columns":["...","..."],"rows":[["...","..."]]}
- {"type":"keyvalue","rows":[["Clé","Valeur"]]}
- {"type":"list","items":["...","..."]}
- {"type":"callout","tone":"info|success|warning|error","title":"...","text":"..."}
- {"type":"bars","data":[{"label":"...","value":10}]}
- {"type":"progress","items":[{"label":"...","pct":72}]}
- {"type":"stat","label":"...","value":"...","hint":"..."}
- {"type":"badge","tone":"primary|success|warning|error|neutral","text":"..."}
- {"type":"quick_replies","options":["Proposition 1","Proposition 2"]}
Exemple, pour présenter des mails : une carte PAR message.
Voici les messages trouvés :
```ui
{"type":"email","subject":"CONTACT architecte","from":"lb@lbbl-architectes.fr","date":"23/07/2026","preview":"Demande d'intervention sur un projet a Sainte-Eulalie..."}
```""" + instruction_actions()

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
    from skills.executor import execute_skill, hash_payload, SkillError
    from mail.skills import EFFETS_NATIFS
    from tasks.identity import charger_executant

    action, texte, erreur = extraire_action(state.get("llm_response") or "")
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
        # mais UNE seule fois — sinon deux modèles têtus boucleraient à l'infini.
        if state.get("tool_repair_used"):
            return _sortir()
        resultats.append({"skill": None, "ok": False,
                          "resultat_masque": f"ERREUR : {erreur}."})
        return {"tool_results": resultats, "tool_iterations": iteration,
                "tool_repair_used": True}

    if action is None:
        return _sortir()

    if iteration > MAX_ACTIONS_PAR_TOUR:
        # Formulé comme une RAISON, pas comme un texte à afficher : c'est le
        # modèle qui la met en mots pour l'utilisateur.
        return _sortir("le nombre de recherches autorisées pour ce tour est atteint "
                       "sans avoir abouti.")

    # Les paramètres arrivent masqués (le modèle ne voit que du texte anonymisé).
    # On les réhydrate avec les MÊMES bornes que la réponse finale : uniquement
    # les jetons réellement envoyés ce tour-ci.
    autorises = set(state.get("turn_placeholders") or [])
    carte = {k: v for k, v in (state.get("entity_map") or {}).items() if k in autorises}
    args = {k: (anonymizer.rehydrate(v, carte) if isinstance(v, str) else v)
            for k, v in action["args"].items()}

    empreinte = hash_payload(action["skill"], args)
    for r in resultats:
        if r.get("payload_hash") == empreinte:
            # Le modèle redemande la même action : on resert le résultat plutôt
            # que de la rejouer (une rédaction relancée coûte un appel LLM de plus).
            resultats.append({**r, "resultat_masque": "(déjà exécuté ce tour)"})
            return {"tool_results": resultats, "tool_iterations": iteration}

    effet = EFFETS_NATIFS.get(action["skill"], "externe")
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
        contenu = _json.dumps(brut.get("output"), ensure_ascii=False, default=str)[:4000]
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
    return {"tool_results": resultats, "tool_iterations": iteration,
            "entity_map": carte_maj}


async def rehydrate_node(state: AgentState) -> dict:
    """Réinjecte les vraies entités dans la réponse via entity_map."""
    from security.anonymizer import anonymizer

    from langchain_core.messages import AIMessage
    from skills.protocol import BLOC_ACTION_RE, BLOC_NATIF_RE, BALISAGE_OUTIL_RE

    text = state.get("llm_response", "") or ""
    # Filet : si une demande d'action survit jusqu'ici (sortie de boucle, limite
    # atteinte), elle ne doit pas s'afficher — c'est de la mécanique interne.
    # Les trois passes couvrent le bloc demandé, la syntaxe native d'un modèle de
    # la cascade, puis tout balisage résiduel quel qu'en soit l'émetteur.
    text = BLOC_ACTION_RE.sub("", text)
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

    return {
        "final_response": anonymizer.rehydrate(text, entity_map),
        # L'historique est émis ICI, et non dans `llm_node` : ce nœud s'exécute
        # exactement une fois par tour, quel que soit le nombre d'actions. On n'y
        # stocke QUE du texte masqué : aucune PII ne dort dans le checkpoint ni ne
        # repart vers le LLM.
        "messages": [
            HumanMessage(content=state.get("anonymized_query") or state.get("query", "")),
            AIMessage(content=text),
        ],
    }


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

def route_apres_llm(state: AgentState) -> str:
    """Le modèle a-t-il demandé une action ?"""
    from skills.protocol import BLOC_ACTION_RE, BLOC_NATIF_RE
    if state.get("tools_finished"):
        return "rehydrate"
    texte = state.get("llm_response") or ""
    # Deux syntaxes : le bloc demandé, et celle que certains modèles de la
    # cascade émettent d'eux-mêmes. Ignorer la seconde la laissait s'afficher.
    demande = BLOC_ACTION_RE.search(texte) or BLOC_NATIF_RE.search(texte)
    return "tools" if demande else "rehydrate"


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
    graph.add_conditional_edges("llm", route_apres_llm,
                                {"tools": "tools", "rehydrate": "rehydrate"})
    graph.add_conditional_edges("tools", route_apres_tools,
                                {"llm": "llm", "rehydrate": "rehydrate"})
    graph.add_edge("rehydrate", "validation_check")
    graph.add_conditional_edges("validation_check", should_validate)

    return graph.compile()


agent1_graph = build_agent1_graph()
