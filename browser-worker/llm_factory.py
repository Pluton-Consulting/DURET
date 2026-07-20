"""
Factory : construit un modèle LLM **natif browser-use** (PAS LangChain) à partir
de la config. browser-use a ses propres classes ChatOpenAI/ChatDeepSeek/ChatGroq/
ChatOpenRouter homonymes mais distinctes de LangChain.

Le modèle doit être fiable en function-calling (deepseek-chat, llama-4-maverick,
LongCat…). Un llama-3.1-8b ne convient pas pour du multi-étapes.
"""
import os

import wconfig


def build_llm():
    provider = wconfig.LLM_PROVIDER
    model = wconfig.LLM_MODEL

    if provider == "deepseek":
        from browser_use import ChatDeepSeek
        return ChatDeepSeek(
            model=model,
            api_key=_require("DEEPSEEK_API_KEY"),
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        )

    if provider == "groq":
        from browser_use import ChatGroq
        return ChatGroq(model=model, api_key=_require("GROQ_API_KEY"))

    if provider == "openrouter":
        from browser_use import ChatOpenRouter
        return ChatOpenRouter(model=model, api_key=_require("OPENROUTER_API_KEY"))

    if provider == "longcat":
        # LongCat 2.0 est un modèle RAISONNANT : il gère mal la sortie structurée forcée
        # (json_schema / response_format) que browser-use utilise par défaut, mais il supporte
        # bien le FUNCTION-CALLING. On désactive donc le forçage et on met le schéma d'action
        # dans le prompt système → browser-use passe par les tool_calls (que LongCat produit).
        from browser_use import ChatOpenAI
        return ChatOpenAI(
            model=model,
            api_key=_require("LONGCAT_API_KEY"),
            base_url=os.environ.get("LONGCAT_BASE_URL", "https://api.longcat.chat/openai"),
            dont_force_structured_output=True,
            add_schema_to_system_prompt=True,
        )

    # openai / générique OpenAI-compatible
    from browser_use import ChatOpenAI
    return ChatOpenAI(
        model=model,
        api_key=_require("OPENAI_API_KEY"),
        base_url=os.environ.get("OPENAI_BASE_URL") or None,
    )


def _require(env_name: str) -> str:
    val = os.environ.get(env_name)
    if not val:
        raise RuntimeError(
            f"{env_name} manquante : l'agent navigateur exige un modèle LLM avec clé "
            f"(provider={wconfig.LLM_PROVIDER}). Configure la clé ou change BROWSER_LLM_PROVIDER."
        )
    return val
