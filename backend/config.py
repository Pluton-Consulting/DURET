from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # App
    environment: str = "production"
    debug: bool = False
    allowed_hosts: str = "100.64.0.1"
    # Sécurité transverse
    max_body_mb: int = 10                          # limite de taille du corps HTTP (anti-DoS mémoire)
    block_external_llm_without_ner: bool = True    # refuse l'envoi aux LLM externes si l'anonymiseur NER est HS (RGPD)
    screenshot_ttl_minutes: int = 30               # purge des captures d'écran orphelines dans validations.payload
    screenshot_cleanup_interval_s: int = 300       # fréquence du balayage TTL

    # Database
    database_url: str

    # Auth
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 8

    # ── LLM — stratégie multi-fournisseurs ───────────────────────────────
    # Cascade par palier : chaque candidat est essayé (retry+backoff) puis on
    # rétrograde au suivant. Un candidat dont la clé fournisseur manque est ignoré.
    #   LIGHT    (actions simples / backend) : 100 % gratuit → Groq free, OpenRouter free, Ollama
    #   STANDARD (défaut)                    : LongCat 2.0 → DeepSeek → gratuit
    #   COMPLEX  (dur / vision)              : LongCat 2.0 → DeepSeek → (Anthropic vision) → gratuit

    # LongCat (API directe OpenAI-compatible) — modèle PRINCIPAL
    # Prix remisé ~ $0.30 / 1M in · $1.20 / 1M out (cache input $0.006).
    # ⚠ base_url / nom de modèle à confirmer côté LongCat.
    longcat_api_key: Optional[str] = None
    longcat_base_url: str = "https://api.longcat.chat/openai/v1"
    model_longcat: str = "LongCat-2.0"   # seul modèle supporté sur api.longcat.chat (vérifié)

    # DeepSeek V4 (API directe OpenAI-compatible) — FALLBACK qualité
    # deepseek-v4-pro : 1M contexte · ~ $0.435 / 1M in (cache miss), $0.0036 (cache hit) · $0.87 / 1M out.
    deepseek_api_key: Optional[str] = None
    deepseek_base_url: str = "https://api.deepseek.com"
    # Deux modèles, deux usages. Flash pour tout ce qui est cadencé et bref
    # (orientation, classification, résumé court) ; Pro pour ce qui demande de
    # RAISONNER. Les faire porter par le même palier reviendrait à payer le
    # tarif du second sur le volume du premier.
    model_deepseek_flash: str = "deepseek-v4-flash"
    model_deepseek: str = "deepseek-v4-pro"          # conservé : nom historique

    # Mêmes modèles vus par OpenRouter, quand on préfère une passerelle unique
    # (une seule clé, une seule facture, bascule automatique si l'API directe
    # tombe). ⚠ Vérifier les slugs exacts sur https://openrouter.ai/models
    model_or_deepseek_flash: str = "deepseek/deepseek-v4-flash"
    model_or_deepseek_pro: str = "deepseek/deepseek-v4-pro"

    # OpenRouter — accès alternatif à LongCat + modèles GRATUITS (Nemotron / Qwen)
    # ⚠ Vérifier les slugs exacts sur https://openrouter.ai/models
    openrouter_api_key: Optional[str] = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    model_primary: str = "meituan/longcat-flash-chat"                     # LongCat via OpenRouter
    model_or_free_a: str = "nvidia/llama-3.1-nemotron-70b-instruct:free"  # OpenRouter free — Nemotron
    model_or_free_b: str = "qwen/qwen-2.5-72b-instruct:free"              # OpenRouter free — Qwen

    # Groq (gratuit) — actions simples/backend, rapides
    groq_api_key: Optional[str] = None
    model_groq_light: str = "llama-3.1-8b-instant"      # rapide, gros quota séparé
    model_groq_large: str = "llama-3.3-70b-versatile"   # plus gros, quota journalier limité
    model_groq_vision: str = "meta-llama/llama-4-scout-17b-16e-instruct"  # multimodal (Agent 2)

    # Anthropic (optionnel) — vision agent 2 / palier COMPLEX si clé fournie
    anthropic_api_key: Optional[str] = None
    model_anthropic_vision: str = "claude-sonnet-4-6"

    # UN MODÈLE MIS EN TÊTE, POUR ESSAYER, SANS TOUCHER AU CODE.
    #
    # Comparer deux modèles sur des tours réels est le seul moyen de trancher :
    # une cascade se juge en production, pas sur une fiche technique. Ce
    # réglage préfixe la cascade du palier visé ; le reste demeure derrière,
    # donc un essai raté retombe sur le comportement habituel au lieu de
    # casser l'application.
    #
    # Forme : "<fournisseur>:<modèle>", plusieurs séparés par une virgule,
    # éventuellement préfixés du palier.
    #   LLM_TETE=openrouter:deepseek/deepseek-v4-pro
    #   LLM_TETE=standard=openrouter:deepseek/deepseek-v4-pro
    #   LLM_TETE=standard=openrouter:deepseek/deepseek-v4-pro,complex=deepseek:deepseek-v4-pro
    # Sans palier nommé, la tête s'applique à STANDARD et COMPLEX (les deux
    # paliers qui rédigent) ; LIGHT garde ses modèles rapides, qui ne servent
    # qu'à orienter et dont la qualité de rédaction n'entre pas en jeu.
    llm_tete: str = ""

    # Vision (Agent 2) : ordre de préférence anthropic > groq. Désactivable.
    vision_enabled: bool = True

    # Ollama (local, dernier recours 100 % gratuit)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model_light: str = "mistral:7b"

    # Masquage des MONTANTS avant envoi au LLM. Désactivé par défaut : un montant seul
    # n'identifie personne (les vraies PII — noms, e-mails, téléphones, IBAN, SIRET —
    # restent masquées dans tous les cas), alors que le masquer empêche le modèle de
    # calculer un total, de comparer une série ou de produire un graphique juste : il
    # ne voit que des jetons opaques et les replace au hasard. Mettre à true pour la
    # confidentialité maximale, au prix de l'exploitation des chiffres.
    anonymize_amounts: bool = False

    # ── Optimisation des tokens (réduction coût + latence) ──
    optim_max_rag_chunks: int = 5           # nb max de chunks RAG envoyés au LLM
    optim_max_context_chars: int = 6000     # budget total de contexte (caractères)
    optim_history_keep: int = 8             # messages d'historique conservés (fenêtre) = 4 échanges
    optim_max_history_chars: int = 4000     # budget caractères de l'historique injecté (~1000 tokens)
    optim_cache_enabled: bool = True        # cache exact des réponses (query+contexte identiques)
    optim_cache_ttl_s: int = 900            # durée de vie d'une entrée de cache (s)
    optim_cache_max: int = 500              # nb max d'entrées en cache (LRU)
    optim_max_tokens_light: int = 1024      # plafond sortie palier LIGHT
    optim_max_tokens_standard: int = 3072   # plafond sortie palier STANDARD
    optim_max_tokens_complex: int = 4096    # plafond sortie palier COMPLEX

    # Résilience (retry + backoff + cascade de fallback)
    llm_max_retries: int = 3
    llm_retry_base_delay: float = 0.5      # secondes, doublé à chaque tentative
    llm_fallback_enabled: bool = True

    # ── Embeddings (RAG) — multi-fournisseurs ────────────────────────────
    # Si le fournisseur n'a pas de clé : chunks insérés sans embedding
    # (embedding_jobs en attente), la recherche RAG dégrade sur pg_trgm.
    # gemini (free, 1536 natif → aucune migration) recommandé sur petit VPS.
    embedding_provider: str = "gemini"     # gemini | openai | ollama
    openai_api_key: Optional[str] = None
    google_api_key: Optional[str] = None   # Google AI Studio (Gemini, tier gratuit)
    gemini_embedding_model: str = "gemini-embedding-001"
    embedding_model: str = "text-embedding-3-small"   # si provider=openai
    ollama_embedding_model: str = "bge-m3"            # si provider=ollama (⚠ 1024 dims → migration schéma)
    embedding_dimensions: int = 1536
    # Worker de vectorisation : draine embedding_jobs en tâche de fond (dans le backend).
    embedding_worker_enabled: bool = True
    embedding_worker_interval_s: int = 10
    embedding_worker_batch: int = 32
    # Garde-fous anti-quota (tier gratuit Gemini) :
    embedding_max_chars: int = 8000          # tronque chaque texte (~2000 tokens) avant embedding
    embedding_daily_request_cap: int = 900   # plafond de requêtes/jour (RPD gratuit ~1000)
    embedding_min_interval_s: float = 0.8    # espacement mini entre requêtes (~75 req/min)
    embedding_cooldown_s: int = 1800         # pause auto après un 429 (quota) — 30 min

    # Langfuse — observabilité (cloud ou self-hosted)
    langfuse_secret_key: Optional[str] = None
    langfuse_public_key: Optional[str] = None
    langfuse_host: str = "http://langfuse-server:3000"
    langfuse_base_url: Optional[str] = None   # ex. https://cloud.langfuse.com (prioritaire sur host)
    langfuse_enabled: bool = True

    # Magic Link — Resend
    resend_api_key: str
    resend_from_email: str = "Duret-Sols <Duret-Sols@duret-sols.fr>"
    app_url: str = "http://localhost:3000"

    # Daytona (optionnel) — partagé entre Agent 3 et Browser Agent
    daytona_api_key: Optional[str] = None

    # Browser Agent — Playwright via Daytona sandbox (recherche one-shot, existant)
    browser_enabled: bool = False
    browser_max_results: int = 3
    browser_timeout_ms: int = 15000

    # ── Agent Navigateur agentique (browser-use, conteneur worker dédié) ──
    # Navigation multi-étapes pilotée par LLM : recherche, login, formulaires,
    # extraction. Toute action modifiante passe par la file de validation (HITL).
    browser_agent_enabled: bool = False
    browser_worker_url: str = "http://browser-worker:9000"   # service interne (non exposé)
    browser_llm_provider: str = "openrouter"   # deepseek | groq | openrouter | longcat | openai
    # Free OpenRouter avec tool-calling (MoE 550B, 1M ctx). ⚠ soumis au rate-limit free.
    browser_llm_model: str = "nvidia/nemotron-3-ultra-550b-a55b:free"
    browser_agent_max_steps: int = 40
    browser_approval_timeout_s: int = 1800     # attente max d'une approbation humaine
    browser_use_vision: bool = False           # captures envoyées au LLM (coût + fuite écran) — off par défaut
    browser_readonly: bool = True              # sécurité : interdit la saisie de formulaires (pas d'input_text/send_keys)
    # Allowlist stricte des domaines autorisés (CSV). Vide = aucun site autorisé.
    browser_allowed_domains: str = ""
    # Identifiants par site (jamais exposés au LLM) + sessions connectées persistées.
    site_credentials_file: str = "secrets/site_credentials.json"
    browser_sessions_dir: str = "secrets/sessions"

    # Checkpointer LangGraph — persistance de l'état des conversations
    # true : AsyncPostgresSaver (reprise sur erreur / human-in-the-loop persistés)
    # fallback automatique sur MemorySaver si le setup échoue
    checkpointer_postgres: bool = True

    # ── Ingestion Phase 2 — connecteurs sources externes ─────────────────
    # Récepteur webhook (pont Make.com : Drive/Outlook → notre backend).
    # Secret partagé exigé dans l'en-tête X-Ingestion-Secret. Absent = endpoint désactivé.
    ingestion_webhook_secret: Optional[str] = None

    # Google Drive (voie API directe — alternative à Make). Voir SETUP_CONNECTEURS.md.
    google_credentials_file: str = "secrets/google_credentials.json"  # client OAuth (client_id/secret)
    google_token_file: str = "secrets/google_token.json"              # refresh token (1er consentement)
    # LE MÊME JETON, EN VARIABLE. Sur un serveur, copier un fichier de secret
    # suppose les bons droits sur `secrets/` — souvent root, créé par Docker,
    # d'où un « Permission denied » au scp. Coller ici le contenu de
    # `google_token.json` (une seule ligne) évite tout transfert de fichier.
    # Il porte déjà client_id, client_secret et refresh_token : quand il est
    # renseigné, aucun autre fichier Google n'est nécessaire.
    google_token_json: Optional[str] = None
    google_drive_folder_id: Optional[str] = None                      # dossier à ingérer (None = tout)

    # ── Gmail / Google Workspace (mails de Duret & Sols) ──
    # Compte de service + délégation à l'échelle du domaine : le backend emprunte
    # l'identité de chaque boîte, sans consentement individuel. Scope demandé :
    # gmail.readonly uniquement.
    google_sa_file: str = "secrets/google_service_account.json"
    # LA MÊME CLÉ, EN VARIABLE. Déposer un fichier de secret sur le serveur
    # suppose les bons droits sur `secrets/`, qui appartient à root — créé par
    # Docker — d'où un « Permission denied » au scp. Coller ici le contenu de
    # la clé (une seule ligne) évite tout transfert de fichier. Prioritaire sur
    # `google_sa_file` quand les deux sont renseignés.
    google_sa_json: Optional[str] = None
    gmail_domain: Optional[str] = None          # ex. duret-sols.fr — refuse toute boîte hors domaine
    gmail_extra_mailboxes: Optional[str] = None  # boîtes partagées, séparées par des virgules
    # Découverte des boîtes du domaine via l'Admin SDK (Directory API), au lieu
    # de se limiter aux comptes de l'application. Sans elle, une personne sans
    # compte applicatif a une boîte invisible, y compris pour un administrateur.
    gmail_decouvrir_domaine: bool = True
    # L'API Directory exige d'emprunter l'identité d'un ADMINISTRATEUR du
    # domaine — contrairement à Gmail, où l'on emprunte chaque boîte. Sans ce
    # réglage, la découverte est simplement désactivée : le connecteur retombe
    # sur les comptes de l'application, il n'échoue pas.
    google_admin_subject: Optional[str] = None   # ex. admin@duret-sols.fr
    gmail_max_messages: int = 100               # messages par dossier et par boîte, à chaque synchro
    gmail_access_level: str = "all"             # visibilité des mails ingérés


    mail_provider: str = "auto"        # auto | outlook | gmail

    # Apprentissage du style rédactionnel (mail/style.py)
    mail_style_samples: int = 50        # nb de messages envoyés analysés par boîte
    mail_style_min_samples: int = 3     # en dessous, le profil serait une caricature

    # Outlook / Microsoft 365 (voie API directe — Microsoft Graph, alternative à Make).
    ms_tenant_id: Optional[str] = None
    ms_client_id: Optional[str] = None
    ms_client_secret: Optional[str] = None
    ms_mailbox: Optional[str] = None    # boîte à lire (ex. contact@duret-sols.fr)
    # LE GARDE-FOU DE DOMAINE. Il refuse toute boîte hors du domaine de
    # l'entreprise. Les permissions Microsoft accordées à l'application portent
    # sur TOUT le tenant : ce filtre est ce qui empêche d'ouvrir une boîte qu'on
    # n'a pas à lire, y compris par une simple erreur de saisie.
    #
    # Il est lu par `mail/lecture.py` et `ingestion/connectors/outlook.py`. Non
    # déclaré, il ne rend pas None : il lève une AttributeError au premier accès,
    # loin de la configuration, et l'erreur ne désigne pas sa cause.
    ms_domain: Optional[str] = None     # ex. mon-entreprise.fr

    # Extrabat (API REST partenaire — activation + identifiants API par l'éditeur).
    extrabat_base_url: str = "https://api.extrabat.com/v1"
    extrabat_api_login: Optional[str] = None
    extrabat_api_password: Optional[str] = None
    # Deytime : aucune API — ingestion via export Excel ou via Extrabat (pas de config).

    # ── Synology NAS (API DSM FileStation, lecture seule) ──
    # QuickConnect n'est PAS une API : il ne fait que résoudre une adresse joignable.
    # Préférer TOUJOURS synology_base_url (IP du NAS sur le VPN, ou DDNS) : le relais
    # QuickConnect est lent et limité en débit, il coupe sur un gros volume.
    synology_base_url: Optional[str] = None          # ex. https://100.64.0.3:5001
    synology_quickconnect_id: Optional[str] = None   # repli si aucune adresse directe
    synology_user: Optional[str] = None              # compte de service DÉDIÉ, lecture seule
    synology_password: Optional[str] = None
    synology_otp_code: Optional[str] = None          # 2FA : à éviter (code valable 30 s, non automatisable)
    synology_folders: Optional[str] = None           # dossiers à ingérer, séparés par des virgules
    synology_source_type: str = "nas"                # type de source dans le RAG
    synology_access_level: str = "all"               # 'all', 'direction_only'...
    synology_max_file_mb: int = 25                   # au-delà, fichier ignoré
    synology_max_depth: int = 6                      # profondeur de récursion des sous-dossiers
    synology_verify_tls: bool = False                # les NAS ont souvent un certificat auto-signé

    # Tâches d'agent (planification, webhook)
    agent_tasks_enabled: bool = True

    # Schedule — défaut global (surchargeable par user en DB)
    access_start_hour: int = 8
    access_end_hour: int = 18

    class Config:
        env_file = ".env"
        protected_namespaces = ()  # autorise les champs model_light / model_standard / model_complex


settings = Settings()
