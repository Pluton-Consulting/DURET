"""
Factory : construit un modèle LLM **natif browser-use** (PAS LangChain) à partir
de la config. browser-use a ses propres classes ChatOpenAI/ChatDeepSeek/ChatGroq/
ChatOpenRouter homonymes mais distinctes de LangChain.

Le modèle doit être fiable en function-calling (deepseek-chat, llama-4-maverick,
LongCat…). Un llama-3.1-8b ne convient pas pour du multi-étapes.

LA VITESSE COMPTE AUTANT QUE LA QUALITÉ, DEPUIS QUE LE CHAT PEUT LANCER UNE
NAVIGATION. Le geste `naviguer` se déroule DANS un tour de conversation :
quelqu'un attend devant l'écran. Chaque étape est un appel au modèle, et une
navigation ordinaire en demande dix à quinze.

LongCat mène la navigation correctement — c'est lui qui servait l'onglet — mais
il répond en une minute par appel (61,8 s mesuré) : quinze étapes feraient un
quart d'heure, et le tour de conversation est coupé bien avant. Un modèle Groq
70B rend la même décision en une à trois secondes, ce qui ramène la même
navigation sous la minute.

Le compromis est assumé : le quota journalier de Groq est limité là où LongCat
n'en a pas. Le jour où il s'épuise, la tâche échoue avec un message clair, et
`BROWSER_LLM_PROVIDER=longcat` la rétablit — plus lente, mais sans plafond.
"""
import logging
import os
import urllib.request

import wconfig

logger = logging.getLogger("browser-worker.llm")

# ── LE FOURNISSEUR CONFIGURÉ PEUT ÊTRE MORT, ET ÇA SE VOIT TROP TARD ────────
#
# Relevé en production le 30/08 : BROWSER_LLM_PROVIDER pointait un compte Groq
# révoqué (403 dès la liste des modèles). La clé étant PRÉSENTE, la fabrique
# construisait le client sans broncher — et chaque étape de navigation brûlait
# son délai sur un 403, cinq étapes en trois minutes, tour coupé. L'utilisateur
# lisait « le site est sans doute trop long à parcourir » : faux, c'était la
# clé.
#
# La vivacité se SONDE donc à la construction — un GET /models d'une seconde,
# le même geste qui a permis le diagnostic — et un fournisseur mort cède sa
# place au premier VIVANT de l'ordre de repli. LongCat d'abord (le modèle de
# la maison, sans plafond de quota), Gemini ensuite (rapide, function-calling
# propre), puis les autres. Le repli est journalisé : une clé morte doit se
# lire dans les logs, pas se déduire d'une navigation qui rampe.

_SONDES = {
    "deepseek":   ("DEEPSEEK_API_KEY",   "https://api.deepseek.com/models"),
    "groq":       ("GROQ_API_KEY",       "https://api.groq.com/openai/v1/models"),
    "openrouter": ("OPENROUTER_API_KEY", "https://openrouter.ai/api/v1/models"),
    "longcat":    ("LONGCAT_API_KEY",    "https://api.longcat.chat/openai/v1/models"),
    "google":     ("GOOGLE_API_KEY",
                   "https://generativelanguage.googleapis.com/v1beta/openai/models"),
}
_MODELES_DEFAUT = {
    "deepseek": "deepseek-chat",
    "groq": "llama-3.3-70b-versatile",
    "openrouter": "deepseek/deepseek-v4-flash",
    "longcat": "LongCat-2.0",
    "google": "gemini-flash-latest",
}
_ORDRE_REPLI = ("longcat", "google", "deepseek", "openrouter", "groq")


def _vivant(provider: str) -> bool:
    """Le fournisseur répond-il avec CETTE clé ? Une seconde, pas plus."""
    env, url = _SONDES.get(provider, (None, None))
    if not env or not os.environ.get(env):
        return False
    try:
        req = urllib.request.Request(
            url, headers={"Authorization": "Bearer " + os.environ[env]})
        with urllib.request.urlopen(req, timeout=6) as r:
            return 200 <= r.status < 300
    except Exception as e:  # noqa: BLE001 — mort ou injoignable : même verdict
        logger.warning("Fournisseur navigateur %s écarté : %s", provider, str(e)[:120])
        return False


def _resoudre() -> tuple[str, str]:
    """Le couple (fournisseur, modèle) réellement utilisable."""
    configure = wconfig.LLM_PROVIDER
    if configure == "openai" or _vivant(configure):
        return configure, wconfig.LLM_MODEL
    for p in _ORDRE_REPLI:
        if p != configure and _vivant(p):
            logger.warning("BROWSER_LLM_PROVIDER=%s injoignable — repli sur %s",
                           configure, p)
            return p, _MODELES_DEFAUT[p]
    # Personne ne répond : on garde la configuration, et l'échec dira la clé.
    return configure, wconfig.LLM_MODEL


def build_llm():
    provider, model = _resoudre()

    if provider == "google":
        # Point d'entrée OpenAI-compatible de Google : function-calling propre,
        # réponses en quelques secondes — le même chemin que la vision du backend.
        from browser_use import ChatOpenAI
        return ChatOpenAI(
            model=model,
            api_key=_require("GOOGLE_API_KEY"),
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )

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
