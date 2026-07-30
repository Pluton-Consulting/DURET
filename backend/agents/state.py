from typing import TypedDict, Optional, List, Annotated
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """État partagé entre tous les nœuds du graph LangGraph"""

    # Identité de la requête
    thread_id: str
    user_id: str
    user_role: str
    session_id: str

    # Requête entrante
    query: str
    has_attachment: bool
    attachment_type: Optional[str]  # 'pdf', 'image', 'sketchup'
    attachment_b64: Optional[str]   # contenu encodé base64 (image nettoyée / page PDF rendue)
    attachment_mime: Optional[str]  # 'image/jpeg', 'application/pdf', ...
    attachment_name: Optional[str]     # nom du fichier joint (traçabilité, invite)
    attachment_text: Optional[str]     # texte extrait d'un fichier non-image (Excel, Word, PDF, CSV…)
    vision_analysis: Optional[str]  # description brute produite par le modèle vision (Agent 2)
    extracted_data: Optional[dict]  # extraction structurée (postes, surfaces, contraintes)

    # Routage
    target_agent: Optional[str]     # 'agent1', 'agent2', 'agent3', 'multi'
    llm_tier: Optional[str]         # 'light', 'standard', 'complex'
    skill_name: Optional[str]       # Nom du skill utilisé si applicable

    # Traitement RAG
    raw_chunks: Optional[List[str]]
    anonymized_chunks: Optional[List[str]]
    anonymized_query: Optional[str]  # requête masquée (PII retirée) envoyée au LLM
    entity_map: Optional[dict]      # Correspondances pour réhydratation (CUMULATIF sur le fil)
    turn_placeholders: Optional[List[str]]  # jetons envoyés au LLM ce tour-ci (borne la réhydratation)

    # Boucle d'appel d'outils. AUCUN reducer d'accumulation ici : `dispatch_agentN`
    # renvoie l'ÉTAT COMPLET du sous-graphe comme update du nœud parent, si bien
    # qu'un reducer additif dupliquerait toute la liste à chaque tour. On accumule
    # donc à la main dans le nœud, et le canal reste en « dernière valeur ».
    tool_results: Optional[List[dict]]   # résultats MASQUÉS des actions du tour
    tool_iterations: int                 # garde anti-boucle
    tool_repair_used: bool               # une seule tentative de réparation d'un bloc invalide
    tools_finished: bool                 # force la sortie de boucle
    note_sortie: Optional[str]           # pourquoi la boucle s'est arrêtée sans aboutir
    pending_action: Optional[dict]       # action externe en attente de validation humaine
    besoin_memoire: Optional[bool]       # décision du routeur : consulter la mémoire ?
    requete_memoire: Optional[str]       # termes de recherche choisis par le routeur
    trigger_kind: Optional[str]          # 'chat' | 'schedule' | 'webhook'

    # Réponse LLM
    llm_response: Optional[str]
    final_response: Optional[str]   # Après réhydratation

    # Human-in-the-loop
    requires_validation: bool
    validation_id: Optional[str]      # UUID de la ligne validations (pause/reprise)
    validation_reason: Optional[str]
    validation_payload: Optional[dict]  # brouillon préparé, présenté à l'humain
    validated_by: Optional[str]
    validation_status: Optional[str]  # 'pending', 'approved', 'rejected'

    # Résilience LLM
    retry_count: int                  # tentatives d'appel LLM sur ce tour
    model_used: Optional[str]         # modèle réellement utilisé (après fallback)

    # Agent 3 — Skill learning
    out_of_scope: bool
    skill_generated: Optional[str]   # Code Python généré
    skill_test_result: Optional[dict]
    skill_confidence: Optional[float]

    # Browser agent — Playwright via Daytona sandbox
    browser_needed: bool
    browser_used: bool
    browser_sources: Optional[List[str]]
    browser_content: Optional[str]
    browser_was_filtered: bool

    # Métadonnées
    tokens_in: int
    tokens_out: int
    cost_eur: float
    duration_ms: Optional[int]
    error: Optional[str]

    # Messages (historique de la conversation)
    messages: Annotated[list, add_messages]
