"""
Routeur LLM — cascade multi-fournisseurs avec retry, backoff et fallback.

Trois paliers, trois compromis assumés entre coût et intelligence :
  LIGHT    — gros volume, faible enjeu (orientation, classification, résumé court)
             DeepSeek Flash → Groq 8B → OpenRouter free → Ollama
  STANDARD — rédaction courante : la LATENCE d'abord
             DeepSeek Flash → passerelle → Groq 70B → LongCat → free → Ollama
  COMPLEX  — analyse, synthèse, jugement : le raisonnement fait la qualité
             DeepSeek V4 Pro → passerelle → Anthropic → Groq 70B → LongCat → free

Le palier n'est pas choisi au hasard : le nœud d'orientation tranche, en un
appel LIGHT, si la demande relève d'une rédaction courante ou d'un vrai travail
d'analyse. Le modèle cher ne sert donc qu'aux tours qui le justifient — c'est ce
qui rend son coût acceptable.

Chaque modèle est joignable EN DIRECT ou via OpenRouter. La passerelle suit
immédiatement l'API directe dans la cascade : si l'une tombe, l'autre prend le
relais sans changer de modèle, donc sans changer de qualité.

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


def _cle(provider: str) -> Optional[str]:
    """Clé effective d'un fournisseur : Paramètres d'abord, `.env` ensuite.

    Passe par `llm.cles` plutôt que par `settings` directement, pour qu'une clé
    saisie dans l'interface prenne effet sans redéploiement.
    """
    from llm.cles import valeur
    return valeur(f"{provider}_api_key")


def _provider_available(provider: str) -> bool:
    if provider in _OPENAI_COMPAT or provider == "groq":
        return bool(_cle(provider))
    if provider == "anthropic":
        c = _cle("anthropic")
        return bool(c) and c != "placeholder"
    if provider == "ollama":
        return True
    return False


def _build_model(provider: str, model: Optional[str], max_tokens: int = 4096):
    """Construit l'instance LangChain (sans résilience) pour un couple (fournisseur, modèle)."""
    if provider in _OPENAI_COMPAT:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            api_key=_cle(provider),
            base_url=getattr(settings, f"{provider}_base_url"),
            temperature=0.1,
            max_tokens=max_tokens,
            default_headers={"HTTP-Referer": "https://pluton.local", "X-Title": "Duret & Sols"},
        )
    if provider == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(model=model, api_key=_cle("groq"), temperature=0.1, max_tokens=max_tokens)
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model, api_key=_cle("anthropic"), temperature=0.1, max_tokens=max_tokens)
    if provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(base_url=settings.ollama_base_url, model=settings.ollama_model_light, temperature=0.1)
    raise ValueError(f"Fournisseur LLM inconnu : {provider}")


def _tier_chain(tier: LLMTier) -> list[tuple[str, Optional[str]]]:
    """Cascade de candidats (fournisseur, modèle) pour un palier, filtrée selon les clés dispo."""
    s = settings
    if tier == LLMTier.LIGHT:
        # Volume élevé, enjeu faible : orientation, classification, résumés
        # courts. On paie le moins possible, et on privilégie la latence.
        chain = [
            ("deepseek", s.model_deepseek_flash),          # rapide et très bon marché
            ("openrouter", s.model_or_deepseek_flash),     # même modèle via la passerelle
            ("groq", s.model_groq_light),                  # gratuit, très rapide
            ("openrouter", s.model_or_free_a),
            ("openrouter", s.model_or_free_b),
            ("ollama", None),
        ]
    elif tier == LLMTier.STANDARD:
        # Rédaction courante : la LATENCE passe devant. LongCat était en tête,
        # et l'export Langfuse du 14/08 a donné la mesure : 61,8 s de MOYENNE
        # par appel (37 appels), des pointes à 190 s. Or un tour n'est pas un
        # appel : produire un document long en enchaîne quinze — un quart
        # d'heure de rédaction pure, qui crevait le plafond des tâches de fond,
        # et l'utilisateur lisait « délai dépassé » après avoir tout attendu.
        #
        # DeepSeek Flash écrit un français propre en quelques secondes ; Groq
        # 70B répond encore plus vite. LongCat n'apporte son surcroît de style
        # qu'au prix de la minute par appel : il devient le SECOURS, plus le
        # principal. La qualité d'un assistant qui répond est supérieure à
        # celle d'un assistant qui rédige mieux mais n'aboutit pas.
        chain = [
            ("deepseek", s.model_deepseek_flash),
            ("openrouter", s.model_or_deepseek_flash),
            ("groq", s.model_groq_large),
            ("longcat", s.model_longcat),
            ("openrouter", s.model_primary),               # LongCat via la passerelle
            ("openrouter", s.model_or_free_a),
            ("ollama", None),
        ]
    else:  # COMPLEX
        # Analyse, synthèse, jugement : ce sont les tours où le raisonnement
        # décide de la qualité. DeepSeek Pro EN TÊTE, avant LongCat — c'est le
        # seul endroit où l'on accepte de payer davantage, et il ne représente
        # qu'une fraction des tours grâce à l'orientation.
        #
        # Groq passe DEVANT LongCat dans les replis, pour la même raison de
        # latence qu'au palier STANDARD : un secours à 60-190 s l'appel
        # transforme la panne du principal en gel de l'application.
        chain = [
            ("deepseek", s.model_deepseek),                # V4 Pro — raisonnement
            ("openrouter", s.model_or_deepseek_pro),
            ("anthropic", s.model_anthropic_vision),
            ("groq", s.model_groq_large),
            ("longcat", s.model_longcat),
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
