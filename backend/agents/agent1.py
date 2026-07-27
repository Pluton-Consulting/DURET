"""
Agent 1 — Administratif / Suivi de chantiers (BTP — Duret & Sols)
Pipeline : RAG pgvector → anonymisation NER → [browser?] → LLM → réhydratation → validation check
Zéro PII vers l'API LLM : la requête ET les documents sont masqués avant l'appel,
puis les vraies valeurs sont réinjectées dans la réponse (entity_map).
"""
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END
from agents.state import AgentState
from llm.router import get_llm, LLMTier

SYSTEM_PROMPT = """Tu es l'assistant IA interne de Duret & Sols, entreprise de travaux de sols et de revêtements (BTP).
Tu assistes l'équipe administrative et le suivi de chantiers dans leur travail quotidien : gestion administrative, comptabilité, réponses aux mails, factures et situations, suivi du temps passé sur les chantiers, commandes, planning, fournisseurs, règlements, réserves, contentieux et dossiers juridiques, support commercial sur les dossiers existants.
Tu peux rechercher dans la mémoire d'entreprise (appels d'offres, CCTP, CCAP, règlements de consultation, DPGF, plans, devis, DOE, commandes, factures, situations, documents fournisseurs, dossiers juridiques, réserves, dossiers chantier). Les documents pertinents te sont fournis ci-dessous sous « Documents internes disponibles ».
IMPORTANT : si aucun document ne t'est fourni, la mémoire n'en contient pas (encore) sur ce sujet — dis-le honnêtement (« je n'ai aucun document là-dessus pour l'instant »), ne liste JAMAIS de contenu imaginaire.
Réponds toujours en français, de façon précise, professionnelle et concise. Sois utile pour : retrouver un dossier par chantier, faire le point sur des commandes / réserves / échéances, préparer un brouillon de réponse à un mail, suivre un dossier juridique ou un règlement fournisseur.
Certaines valeurs des documents peuvent apparaître masquées sous forme de balises [PER_1], [MONTANT_2], etc. — conserve-les telles quelles. Ne CRÉE jamais toi-même de balise entre crochets.
Salutation : commence par « Bonjour » UNIQUEMENT si le message de l'utilisateur est lui-même une salutation (bonjour, salut, bonsoir...) ; sinon, pour une question de travail, réponds DIRECTEMENT, sans « Bonjour » ni formule d'accueil, et sans jamais répéter une salutation déjà faite dans la conversation. Ne dis JAMAIS « je suis Duret & Sols » ni « je m'appelle Duret & Sols » (c'est le nom de l'entreprise, pas ton identité à énoncer) et ne te présente pas. Pour une question de travail, réponds directement.
N'invente JAMAIS de donnée (montant, nom, date, nombre, référence de dossier). Tant qu'aucun document ne t'est fourni, dis franchement que tu n'as pas cette information en mémoire pour l'instant. Les décisions engageantes (envoi d'un mail, facturation, action juridique) restent validées par un humain.
Typographie : n'utilise JAMAIS de tiret cadratin (—) ni de tiret demi-cadratin (–) ; emploie plutôt une virgule, un deux-points, une parenthèse ou un tiret simple « - »."""


# ── Nœuds ────────────────────────────────────────────────────────────

async def rag_node(state: AgentState) -> dict:
    """Récupère les chunks pertinents depuis pgvector (filtrés par rôle)."""
    from vectorstore.rag import retrieve_as_context

    contexts = await retrieve_as_context(
        query=state.get("query", ""),
        user_role=state.get("user_role", "terrain"),
        top_k=5,
    )
    return {"raw_chunks": contexts}


async def anonymize_node(state: AgentState) -> dict:
    """Masque la requête ET les chunks avant tout envoi LLM (entity_map partagé)."""
    from security.anonymizer import anonymizer

    query = state.get("query", "")
    chunks = list(state.get("raw_chunks") or [])
    masked, entity_map = anonymizer.anonymize_chunks([query] + chunks)

    return {
        "anonymized_query": masked[0] if masked else query,
        "anonymized_chunks": masked[1:] if len(masked) > 1 else [],
        "entity_map": entity_map,
    }


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

    from optim.tokens import trim_chunks, response_cache

    tier = state.get("llm_tier", "standard")
    llm = get_llm(LLMTier(tier))

    chunks = state.get("anonymized_chunks")
    if chunks is None:
        chunks = state.get("raw_chunks") or []
    chunks = trim_chunks(chunks)   # borne le nombre de chunks + le volume de contexte
    context_text = "\n\n---\n\n".join(str(c) for c in chunks) if chunks else ""

    query = state.get("anonymized_query") or state.get("query", "")

    # Cache exact (palier|requête|contexte anonymisés) : évite un appel LLM identique récent.
    # Clé et valeur sans PII (la réhydratation se fait ensuite, par requête).
    cached = response_cache.get(tier, query, context_text)
    if cached is not None:
        return {"llm_response": cached, "model_used": "cache", "tokens_in": 0, "tokens_out": 0}

    human_content = f"Question : {query}"
    if context_text:
        human_content = f"Documents internes disponibles :\n{context_text}\n\n{human_content}"
    else:
        human_content = ("(Aucun document interne n'a été trouvé pour cette requête : la mémoire "
                         "d'entreprise est vide ou ne contient rien sur ce sujet. Réponds honnêtement, "
                         "sans inventer de contenu.)\n\n" + human_content)

    # Composants visuels : l'instruction (coûteuse en tokens) n'est ajoutée qu'aux tours
    # « riches » (devis, tableau, indicateur…), détectés par mots-clés sur la requête brute.
    raw_query = (state.get("query") or "").lower()
    ui_keywords = ("devis", "facture", "tableau", "récap", "recap", "compar", "montre",
                   "affiche", "liste", "graph", "planning", "situation", "indicateur",
                   "kpi", "propose", "bouton", "chantier", "statut", "avanc")
    system_prompt = SYSTEM_PROMPT
    if any(k in raw_query for k in ui_keywords):
        system_prompt = SYSTEM_PROMPT + """

COMPOSANTS VISUELS (optionnel). Quand tu as des DONNÉES concrètes à présenter (devis, facture, tableau, indicateur, suggestions d'actions...), tu peux intercaler un composant en insérant, au milieu de ta réponse, un bloc balisé ```ui contenant un objet JSON. Rédige le texte normalement autour du bloc. Règle absolue : n'invente jamais de valeurs ; remplis TOUS les champs requis du composant, sinon réponds en texte simple (un composant aux champs manquants ne s'affiche pas). Types :
- {"type":"quote","id":"...","client":"...","status":"draft|sent|accepted","total":"...","lines":[{"label":"...","qty":"...","price":"..."}]}
- {"type":"invoice","number":"...","client":"...","amount":"...","issued":"...","due":"...","status":"paid|pending|late"}
- {"type":"table","columns":["...","..."],"rows":[["...","..."]]}
- {"type":"callout","tone":"info|success|warning|error","title":"...","text":"..."}
- {"type":"bars","data":[{"label":"...","value":10}]}
- {"type":"stat","label":"...","value":"...","hint":"..."}
- {"type":"quick_replies","options":["Proposition 1","Proposition 2"]}
Exemple :
Voici le devis correspondant :
```ui
{"type":"quote","id":"DEV-2024-017","client":"SCI Dupont","status":"draft","total":"10 380 € HT","lines":[{"label":"Ragréage de sol","qty":"120 m²","price":"3 600 €"},{"label":"Carrelage grès cérame","qty":"120 m²","price":"6 780 €"}]}
```"""

    messages = [SystemMessage(content=system_prompt), HumanMessage(content=human_content)]
    response = await llm.ainvoke(messages, config=config)

    response_cache.set(tier, query, context_text, response.content)

    usage = getattr(response, "usage_metadata", None) or {}
    return {
        "llm_response": response.content,
        "tokens_in": usage.get("input_tokens", 0),
        "tokens_out": usage.get("output_tokens", 0),
        "model_used": llm.last_model_used,
    }


async def rehydrate_node(state: AgentState) -> dict:
    """Réinjecte les vraies entités dans la réponse via entity_map."""
    from security.anonymizer import anonymizer

    text = state.get("llm_response", "") or ""
    entity_map = state.get("entity_map") or {}
    return {"final_response": anonymizer.rehydrate(text, entity_map)}


async def validation_check_node(state: AgentState) -> dict:
    """Détecte si la réponse nécessite une validation humaine (devis, envoi client...)."""
    # TODO (cas d'usage métier) : heuristique sur le contenu de final_response.
    return {"requires_validation": False}


# ── Edges conditionnels ───────────────────────────────────────────────

def should_use_browser(state: AgentState) -> str:
    from config import settings
    if state.get("browser_used"):
        return "llm"
    if not settings.browser_enabled:
        return "llm"
    return "browser" if not (state.get("raw_chunks") or []) else "llm"


def should_validate(state: AgentState) -> str:
    return "wait_for_human" if state.get("requires_validation") else END


# ── Graph ─────────────────────────────────────────────────────────────

def build_agent1_graph():
    graph = StateGraph(AgentState)
    graph.add_node("rag", rag_node)
    graph.add_node("anonymize", anonymize_node)
    graph.add_node("browser", browser_node)
    graph.add_node("llm", llm_node)
    graph.add_node("rehydrate", rehydrate_node)
    graph.add_node("validation_check", validation_check_node)

    graph.set_entry_point("rag")
    graph.add_edge("rag", "anonymize")
    graph.add_conditional_edges("anonymize", should_use_browser, {"browser": "browser", "llm": "llm"})
    graph.add_edge("browser", "llm")
    graph.add_edge("llm", "rehydrate")
    graph.add_edge("rehydrate", "validation_check")
    graph.add_conditional_edges("validation_check", should_validate)

    return graph.compile()


agent1_graph = build_agent1_graph()
