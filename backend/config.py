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
    # Anonymisation PII : « active » ou « desactivee ». DÉSACTIVÉE PAR DÉFAUT
    # depuis le 31/08/2026, décision de Noa (« fluidifier de A à Z les
    # requêtes ») : le masquage cassait des flux réels — adresse tapée masquée
    # en boucle, balises dans les comptes rendus, mémoire gravée de [PER_n]
    # irrésolubles. Le mécanisme reste entier et se rallume en un clic
    # (Paramètres → Clés API) ou par ANONYMISATION=active ici ; la
    # RÉHYDRATATION des balises déjà posées ne se coupe jamais.
    anonymisation: str = "desactivee"
    screenshot_ttl_minutes: int = 30               # purge des captures d'écran orphelines dans validations.payload
    screenshot_cleanup_interval_s: int = 300       # fréquence du balayage TTL

    # Database
    database_url: str

    # Auth
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    # 24 h (31/08, décision de Noa) : 8 h expiraient en pleine journée dans un onglet
    # resté ouvert. Doit rester ÉGAL à `session.maxAge` de frontend/lib/auth.ts.
    jwt_expire_hours: int = 24
    # LA SESSION D'APPAREIL (03/09, migration 034). Combien de jours un poste
    # déjà connu reste connecté sans repasser par le lien magique.
    # 0 = ILLIMITÉ, tant qu'on ne se déconnecte pas — décision de Noa. Toute
    # autre valeur donne une échéance GLISSANTE, repoussée à chaque usage : un
    # poste dont on se sert ne tombe jamais, un poste oublié finit par tomber.
    session_appareil_jours: int = 0

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

    # Google Gemini, par le point d'entree COMPATIBLE OPENAI : aucune dependance
    # nouvelle, le meme client que LongCat ou DeepSeek. La cle GOOGLE_API_KEY
    # existait deja (embeddings) sans jamais servir a voir. Sert a la VISION de
    # l'agent 2 : le modele Groq multimodal repondait 404 et l'agent n'avait
    # plus d'yeux. `gemini-flash-latest` suit la version courante : Google
    # retire les anciennes aux nouveaux comptes (« no longer available to new
    # users », releve sur gemini-2.5-flash), un nom fige casserait un jour.
    google_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    model_google_vision: str = "gemini-flash-latest"
    # LA VOIX (03/09) : le micro du chat enregistre, ce modèle transcrit. Même
    # clé Google que la vision et les images — rien de plus à configurer.
    model_google_audio: str = "gemini-flash-latest"
    # Second candidat Google, plus leger : au test, le premier a repondu 503
    # « forte demande » pendant que celui-ci lisait le plan en une seconde.
    model_google_vision_secours: str = "gemini-3.1-flash-lite"
    # Gemini en TEXTE (cascade LIGHT/STANDARD/COMPLEX). Ajoute le 30/08, le jour
    # ou TOUTES les autres cles etaient mortes (Groq 403 des la liste des
    # modeles, OpenRouter 401, DeepSeek et Anthropic absentes) : la cle Google,
    # elle, servait deja les visuels, la vision et les embeddings — et la sonde
    # texte repondait en une seconde. Gemini suit le protocole d'action bien
    # mieux que le dernier secours (LongCat) ; le disjoncteur gere 429 et 503.
    model_google_texte: str = "gemini-flash-latest"
    model_google_texte_leger: str = "gemini-flash-lite-latest"

    # Anthropic (optionnel) — vision agent 2 / palier COMPLEX si clé fournie
    anthropic_api_key: Optional[str] = None
    model_anthropic_vision: str = "claude-sonnet-4-6"

    # LA VISION PAR OPENROUTER — préparamétrée pour l'OCR (01/09, demande de
    # Noa : « l'OCR fait encore des erreurs, préparamètre un meilleur modèle,
    # OpenRouter est déjà utilisé »). Gemini 2.5 Pro lit les factures, scans
    # et tableaux bien mieux que tesseract et que le flash de la cascade ; la
    # clé OpenRouter est déjà celle des deux modèles de l'assistant. Entré
    # dans la cascade vision derrière Anthropic : les plans gardent leur
    # meilleur lecteur quand la clé existe, tout le reste monte en qualité.
    model_openrouter_vision: str = "google/gemini-2.5-pro"

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
    # Date de départ des indicateurs (AAAA-MM-JJ). Vide = tout l'historique.
    kpi_depuis: str = ""

    # LE ROI DU TABLEAU DE BORD : une estimation, et l'écran le dit.
    #
    # Ces réglages n'étaient PAS déclarés ici : `routers/tableau.py` retombait
    # sur des valeurs en dur (65 €/h, 10 min par « conversation »), donc
    # impossibles à ajuster sans toucher au code. Ils sont posés le 01/09 avec
    # les valeurs revues chez le jumeau — relevé de Noa : « le ROI monte trop
    # vite, sûrement une surestimation des temps ».
    #
    # Il avait raison, et la cause principale n'était pas la valeur : le
    # compteur compte des TOURS de chat et les appelait « conversations ». Cinq
    # messages pour obtenir un devis créditaient cinquante minutes. Les valeurs
    # ci-dessous répondent à « combien de temps CE geste aurait pris à la
    # main », pas « combien vaut une journée assistée ».
    roi_taux_horaire: float = 45.0         # coût horaire chargé, prudent
    roi_minutes_question: float = 3.0      # UN ÉCHANGE (pas une conversation entière)
    roi_minutes_document: float = 20.0     # un document produit (devis, mémoire)
    roi_minutes_mail: float = 2.0          # un mail trié, résumé ou répondu
    roi_minutes_analyse: float = 15.0      # un plan ou une photo analysés
    roi_minutes_recherche: float = 3.0     # une recherche (mémoire, données, web)

    # Vision (Agent 2) : ordre de préférence anthropic > groq. Désactivable.
    vision_enabled: bool = True

    # Ollama (local, dernier recours 100 % gratuit)
    # ── Ollama Cloud (abonnement) — API compatible OpenAI ────────────────
    # À NE PAS CONFONDRE avec `ollama_*` juste en dessous, qui désigne un
    # Ollama LOCAL sans clé (dernier recours hors ligne). Ici c'est le service
    # HÉBERGÉ : une clé Bearer, une URL publique. Deux fournisseurs distincts
    # dans le routeur (`ollama_cloud` et `ollama`), parce qu'une panne de l'un
    # ne dit rien de l'autre — les confondre reviendrait à lire « le service
    # est en panne » là où le vrai message est « rien ne tourne sur ce poste ».
    ollama_cloud_api_key: Optional[str] = None
    ollama_cloud_base_url: str = "https://ollama.com/v1"
    # Identifiants tels que les sert `GET /v1/models`, SANS le suffixe
    # « :cloud » qu'affiche le site — celui-là est la forme du client en ligne
    # de commande, et rend 404 sur cette API.
    model_ollama_cloud_rapide: str = "deepseek-v4-flash:0731"   # 1M de contexte
    model_ollama_cloud_puissant: str = "deepseek-v4-pro:0813"   # 1M de contexte
    # Vision et OCR : les deux modèles du catalogue qui déclarent lire les
    # images, un très gros lecteur et un très rapide.
    model_ollama_cloud_vision: str = "qwen3.5:397b"
    model_ollama_cloud_vision_secours: str = "glm-5.3-flash"

    # ── Appels de modèle simultanés (llm/concurrence.py) ─────────────────
    # L'abonnement autorise 10 appels de front ; au-delà, le fournisseur met en
    # file puis refuse — et un refus coûte cinq minutes de quarantaine dans le
    # disjoncteur. On garde donc une marge sous son plafond, et l'on attend
    # CHEZ NOUS, où l'attente est bornée et mesurable.
    llm_simultanes: int = 8              # plafond global, tous appels confondus
    llm_simultanes_personne: int = 3     # défaut par personne
    llm_simultanes_fond: int = 2         # budget des tâches de fond et campagnes
    llm_attente_max_s: int = 90          # au-delà, on renonce : jamais d'attente sans fin

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
    # MÉMOIRE DE CONVERSATION À TROIS ÉTAGES (agents/memoire_conversation.py).
    # La fenêtre récente valait 8 messages / 4 000 caractères : une réponse un
    # peu longue effaçait tout, et au-delà de quatre échanges rien ne restait.
    # Elle est quatre fois plus large, chaque message long est TAILLÉ plutôt
    # que jeté, et ce qui en sort est fondu dans un résumé puis rappelé par
    # proximité vectorielle quand la question du moment s'y rapporte.
    optim_history_keep: int = 16            # messages d'historique conservés (fenêtre) = 8 échanges
    optim_max_history_chars: int = 16000    # budget caractères de la fenêtre (~4000 tokens)
    memoire_message_max_chars: int = 1400   # au-delà, un message est taillé (tête + queue)
    memoire_resume_max_chars: int = 1800    # taille du résumé glissant
    memoire_rappels_k: int = 3              # échanges anciens rappelés par proximité
    memoire_rappels_seuil: float = 0.45     # proximité minimale (cosinus) pour être rappelé
    optim_cache_enabled: bool = True        # cache exact des réponses (query+contexte identiques)
    optim_cache_ttl_s: int = 900            # durée de vie d'une entrée de cache (s)
    optim_cache_max: int = 500              # nb max d'entrées en cache (LRU)
    optim_max_tokens_light: int = 1024      # plafond sortie palier LIGHT
    optim_max_tokens_standard: int = 3072   # plafond sortie palier STANDARD
    # 4096 jetons ≈ 3000 mots : un cahier des charges ET un devis demandés dans
    # le même tour n'y tenaient pas, et la réponse se coupait en cours de phrase.
    #
    # Ce plafond est FACTURÉ À L'USAGE RÉEL, pas à sa valeur : le relever ne
    # renchérit aucune réponse courte, il cesse seulement de tronquer les
    # longues. Les appels intermédiaires du tour, qui n'émettent qu'un bloc
    # d'action de quelques lignes, coûtent exactement la même chose qu'avant.
    optim_max_tokens_complex: int = 8192    # plafond sortie palier COMPLEX

    # Résilience (retry + backoff + cascade de fallback)
    # DEUX TENTATIVES, PAS TROIS. La cascade compte six candidats : insister
    # trois fois sur chacun avant de passer au suivant transforme une panne
    # passagère en minutes d'attente. On retente une fois, puis on change de
    # fournisseur — c'est là qu'est la vraie résilience.
    llm_max_retries: int = 2
    llm_retry_base_delay: float = 0.5      # secondes, doublé à chaque tentative

    # LE DÉLAI D'ATTENTE, QUI N'EXISTAIT PAS.
    #
    # Aucun `timeout` n'était passé aux clients : le SDK OpenAI plafonne alors
    # à 600 SECONDES, et retente deux fois de lui-même par-dessus nos propres
    # tentatives. Un fournisseur qui rame ne rendait donc jamais la main, et la
    # cascade — écrite précisément pour ça — ne servait à rien.
    #
    # Mesuré dans la trace du 17/08 : 25 à 38 secondes pour produire SOIXANTE
    # jetons. Ce n'est pas de la génération, c'est de l'attente. Passé ce
    # délai, le candidat suivant fera mieux que le candidat qui traîne.
    #
    # Les valeurs tiennent compte de ce qu'on attend en retour : le palier
    # LIGHT ne rend qu'une décision de routage, les deux autres peuvent avoir
    # un document entier à écrire, et couper une rédaction en cours serait pire
    # que l'attendre.
    llm_timeout_light: int = 20
    # 31/08 : avec deux modèles rapides choisis, un candidat qui pend ne doit
    # pas retenir le tour 75 s avant de céder à l'autre — 45 s suffisent à
    # une rédaction ordinaire, 120 s à une analyse. Revoir à la hausse si un
    # long document sort tronqué (le journal dira « Request timed out »).
    llm_timeout_standard: int = 45
    llm_timeout_complex: int = 120
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
    # Si provider=ollama_cloud. Modèle par DÉFAUT seulement : celui qu'on choisit
    # à l'écran (réglage `modele_embedding`) prime, et sa dimension est MESURÉE
    # avant d'écrire quoi que ce soit — voir `vectorstore/dimension.py`.
    ollama_cloud_embedding_model: str = "embeddinggemma"
    # LA DIMENSION QUE LA BASE ATTEND. Ce n'est pas un réglage de confort : la
    # colonne est déclarée `vector(N)`, et un vecteur d'une autre taille est
    # refusé à l'écriture. Changer de modèle d'embedding impose donc de
    # re-vectoriser tout le corpus, parce que des vecteurs de modèles
    # différents ne se comparent pas — même à dimension égale.
    embedding_dimensions: int = 1536
    # Worker de vectorisation : draine embedding_jobs en tâche de fond (dans le backend).
    embedding_worker_enabled: bool = True
    embedding_worker_interval_s: int = 10
    # 16 et non 32 : à 32 textes par requête, la première rafale après une
    # pause crevait le débit par minute et relançait un 429 (31/08). La
    # cadence s'adapte seule (vectorstore/embeddings.py), le lot reste modeste.
    embedding_worker_batch: int = 16
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
    # LE SECRET DU GUICHET. Le conteneur navigateur n'écrit plus en base : il
    # raconte au backend, qui écrit. Ce secret empêche un tiers du réseau
    # interne d'appeler ce guichet — il ne protège pas d'un conteneur
    # compromis, qui l'a dans son environnement. Le vrai garde-fou est la
    # forme de l'API : huit verbes, aucune requête libre.
    #
    # VIDE PAR DÉFAUT, ET LE GUICHET REFUSE ALORS TOUT. Un oubli de
    # déploiement doit se voir, pas ouvrir une porte.
    browser_worker_secret: str = ""
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

    # ── Connexion Google PERSONNELLE (Paramètres > Ma boîte Google) ──
    # Un client OAuth « application Web » de la console Google Cloud, avec
    # {APP_URL}/api/google/retour en URI de redirection autorisée. ⚠️ L'app
    # doit être « interne » (Workspace) ou publiée en production si externe :
    # restée « en test », Google révoque les refresh tokens au bout de 7 jours.
    google_oauth_client_id: Optional[str] = None
    google_oauth_client_secret: Optional[str] = None

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
        # UN REGLAGE RETIRE DU CODE NE DOIT PAS EMPECHER LE DEMARRAGE.
        # Le `.env` des serveurs vit sa vie : il garde des lignes de reglages
        # qu'on a cesse d'utiliser (Higgsfield, retire le 22/08/2026). Sans
        # cette tolerance, retirer un champ ici ferait tomber le backend au
        # redemarrage chez qui n'a pas nettoye son fichier le meme jour.
        extra = "ignore"
        protected_namespaces = ()  # autorise les champs model_light / model_standard / model_complex


settings = Settings()
