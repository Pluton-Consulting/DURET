"""
Routeur LLM — cascade multi-fournisseurs avec retry, backoff et fallback.

Stratégie (par palier, chaque candidat essayé puis rétrogradation au suivant) :
  LIGHT    — actions simples / backend : 100 % gratuit
             Groq free → OpenRouter free (Nemotron) → OpenRouter free (Qwen) → Ollama
  STANDARD — défaut : qualité d'abord, gratuit en secours
             LongCat 2.0 → DeepSeek → Groq 70B → OpenRouter free → Groq 8B → Ollama
  COMPLEX  — dur / vision :
             LongCat 2.0 → DeepSeek → (Anthropic vision) → Groq 70B → OpenRouter free → Ollama

Fournisseurs : openrouter (OpenAI-compatible : LongCat, DeepSeek, free), groq, anthropic, ollama.
Un candidat dont la clé fournisseur est absente est ignoré silencieusement, ce qui rend
la configuration progressive : avec seulement GROQ_API_KEY, tout tourne sur Groq/Ollama ;
dès qu'OPENROUTER_API_KEY est fournie, LongCat/DeepSeek/free s'activent en tête de cascade.
"""
import asyncio
import logging
from enum import Enum
from typing import Any, Optional

from config import settings
from optim.tokens import tier_max_tokens

logger = logging.getLogger("duret.llm")


class LLMTier(Enum):
    LIGHT = "light"        # actions simples / backend — gratuit
    STANDARD = "standard"  # défaut — LongCat/DeepSeek puis gratuit
    COMPLEX = "complex"    # dur / vision


# ── Disponibilité & construction des fournisseurs ────────────────────────

# Fournisseurs OpenAI-compatibles (base_url + clé configurables) : direct ou via passerelle.
_OPENAI_COMPAT = ("openrouter", "deepseek", "longcat")


def _provider_available(provider: str) -> bool:
    if provider in _OPENAI_COMPAT:
        return bool(getattr(settings, f"{provider}_api_key"))
    if provider == "groq":
        return bool(settings.groq_api_key)
    if provider == "anthropic":
        return bool(settings.anthropic_api_key) and settings.anthropic_api_key != "placeholder"
    if provider == "ollama":
        return True
    return False


def _build_model(provider: str, model: Optional[str], max_tokens: int = 4096):
    """Construit l'instance LangChain (sans résilience) pour un couple (fournisseur, modèle)."""
    if provider in _OPENAI_COMPAT:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            api_key=getattr(settings, f"{provider}_api_key"),
            base_url=getattr(settings, f"{provider}_base_url"),
            temperature=0.1,
            max_tokens=max_tokens,
            default_headers={"HTTP-Referer": "https://pluton.local", "X-Title": "Duret & Sols"},
        )
    if provider == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(model=model, api_key=settings.groq_api_key, temperature=0.1, max_tokens=max_tokens)
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model, api_key=settings.anthropic_api_key, temperature=0.1, max_tokens=max_tokens)
    if provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(base_url=settings.ollama_base_url, model=settings.ollama_model_light, temperature=0.1)
    raise ValueError(f"Fournisseur LLM inconnu : {provider}")


def _tier_chain(tier: LLMTier) -> list[tuple[str, Optional[str]]]:
    """Cascade de candidats (fournisseur, modèle) pour un palier, filtrée selon les clés dispo."""
    s = settings
    if tier == LLMTier.LIGHT:
        chain = [
            ("groq", s.model_groq_light),
            ("openrouter", s.model_or_free_a),
            ("openrouter", s.model_or_free_b),
            ("ollama", None),
        ]
    elif tier == LLMTier.STANDARD:
        chain = [
            ("longcat", s.model_longcat),        # LongCat 2.0 — QUALITÉ/raisonnement (principal)
            ("groq", s.model_groq_large),        # Groq 70B — repli RAPIDE si LongCat indispo/quota
            ("openrouter", s.model_primary),
            ("deepseek", s.model_deepseek),
            ("groq", s.model_groq_light),
            ("openrouter", s.model_or_free_a),
            ("ollama", None),
        ]
    else:  # COMPLEX
        chain = [
            ("longcat", s.model_longcat),        # LongCat 2.0 — principal (raisonnement)
            ("groq", s.model_groq_large),        # repli rapide
            ("deepseek", s.model_deepseek),
            ("anthropic", s.model_anthropic_vision),
            ("openrouter", s.model_or_free_b),
            ("ollama", None),
        ]
    filtered = [(p, m) for (p, m) in chain if _provider_available(p)]
    return filtered if settings.llm_fallback_enabled else filtered[:1]


# Erreurs pour lesquelles il est inutile de retenter le MÊME modèle → passer au suivant.
_HARD_FAIL_MARKERS = ("429", "rate limit", "rate_limit", "quota", "insufficient", "401", "403",
                      "invalid api key", "authentication", "not found", "no endpoints")


def _is_hard_fail(err: Exception) -> bool:
    msg = str(err).lower()
    return any(k in msg for k in _HARD_FAIL_MARKERS)


class ResilientLLM:
    """LLM résilient : parcourt la cascade du palier, retry+backoff par candidat, fallback au suivant."""

    def __init__(self, tier: LLMTier):
        self.tier = tier
        self.last_model_used: Optional[str] = None

    async def ainvoke(self, messages: Any, **kwargs) -> Any:
        chain = _tier_chain(self.tier)
        if not chain:
            raise RuntimeError(
                "Aucun fournisseur LLM configuré — renseignez au moins GROQ_API_KEY "
                "ou OPENROUTER_API_KEY dans le .env."
            )

        last_error: Optional[Exception] = None
        for idx, (provider, model) in enumerate(chain):
            try:
                llm = _build_model(provider, model, tier_max_tokens(self.tier.value))
            except Exception as e:  # dépendance/clé manquante à l'instanciation
                last_error = e
                logger.warning("LLM %s indisponible : %s", provider, e)
                continue

            label = f"{provider}:{model or settings.ollama_model_light}"
            for attempt in range(settings.llm_max_retries):
                try:
                    result = await llm.ainvoke(messages, **kwargs)
                    self.last_model_used = label
                    if idx > 0:
                        logger.warning("LLM fallback → %s (palier %s)", label, self.tier.value)
                    return result
                except Exception as e:
                    last_error = e
                    if _is_hard_fail(e):
                        logger.warning("LLM %s indispo (quota/auth) : %s — candidat suivant", label, e)
                        break  # inutile de retenter ce modèle, passer au suivant
                    delay = settings.llm_retry_base_delay * (2 ** attempt)
                    logger.warning(
                        "LLM %s tentative %d/%d échouée : %s — retry dans %.1fs",
                        label, attempt + 1, settings.llm_max_retries, e, delay,
                    )
                    if attempt < settings.llm_max_retries - 1:
                        await asyncio.sleep(delay)

        raise RuntimeError(f"Tous les modèles LLM ont échoué (dernier : {last_error})") from last_error

    def invoke(self, messages: Any, **kwargs) -> Any:
        """Version synchrone — best-effort sur le premier candidat disponible."""
        chain = _tier_chain(self.tier)
        if not chain:
            raise RuntimeError("Aucun fournisseur LLM configuré")
        provider, model = chain[0]
        llm = _build_model(provider, model)
        result = llm.invoke(messages, **kwargs)
        self.last_model_used = f"{provider}:{model or settings.ollama_model_light}"
        return result


def get_llm(tier: LLMTier) -> ResilientLLM:
    """Retourne un LLM résilient (cascade multi-fournisseurs) pour le palier demandé."""
    return ResilientLLM(tier)


def get_vision_llm() -> tuple[Any, Optional[str]]:
    """Retourne (llm, label) d'un modèle capable de VISION, ou (None, None).

    Préférence : Anthropic (si clé) > Groq multimodal (llama-4). Ces modèles acceptent
    un message multimodal (content = [{type:'text'}, {type:'image_url', image_url:{url:'data:...'}}]).
    Modèle direct (pas la cascade) : la vision nécessite un modèle spécifique.
    """
    s = settings
    if not getattr(s, "vision_enabled", True):
        return None, None
    for provider, model in (("anthropic", s.model_anthropic_vision), ("groq", s.model_groq_vision)):
        if _provider_available(provider):
            try:
                return _build_model(provider, model), f"{provider}:{model}"
            except Exception as e:
                logger.warning("Modèle vision %s indisponible : %s", provider, e)
    return None, None


def classify_request_tier(query: str, has_attachment: bool = False) -> LLMTier:
    """
    Classe la requête dans le bon palier.
    Bias volontaire vers LIGHT (gratuit) pour un max d'actions simples/backend.
    """
    if has_attachment:
        return LLMTier.COMPLEX

    q = query.lower().strip()
    words = len(query.split())
    greetings = ("bonjour", "salut", "hello", "coucou", "bonsoir", "hey", "merci", "ça va", "ca va")
    # Salutation / politesse très courte → petit modèle rapide (suffisant).
    if words <= 4 and any(g in q for g in greetings):
        return LLMTier.LIGHT
    # Tout le reste, questions métier incluses → modèle STANDARD (Groq 70B, rapide ET fiable :
    # le 8B hallucinait des chiffres/balises sur les questions).
    return LLMTier.STANDARD
