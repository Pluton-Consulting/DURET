"""
Interface entre les agents LangGraph et le CONTENEUR NAVIGATEUR.

Chaque outil assainit la requête, délègue au conteneur, journalise dans l'audit.
Le backend n'ouvre lui-même aucune page : tout ce qui vient d'un site inconnu
est manipulé dans le conteneur navigateur, seul contraint pour cela.

Ce module parlait auparavant à un bac à sable Daytona — un service tiers dont
la clé manquait en production, ce qui faisait échouer la recherche web en
silence. Le contrat de retour n'a pas bougé d'un champ.
"""

from typing import Optional
from browser.navigateur import navigateur, BrowserResult
from browser.sandbox_filter import SandboxFilter
from security.audit import log_action

_filter = SandboxFilter()


async def web_search(
    query: str,
    user_id: str,
    agent_id: str,
    max_results: int = 3,
    context: Optional[str] = None,
) -> dict:
    """
    Recherche web via DuckDuckGo, dans le conteneur navigateur.
    La requête est sanitisée avant envoi — aucune PII ne sort.
    """
    clean = _filter.sanitize_query(query)
    if context:
        clean = f"{clean} {_filter.sanitize_query(context)}"[:200]

    result: BrowserResult = await navigateur.run_search(
        query=clean,
        max_results=max_results,
    )

    successful = [r for r in result.results if r.get("content")]
    combined = "\n\n---\n\n".join([
        f"Source : {r['url']}\nTitre : {r.get('title', '')}\n\n{r['content']}"
        for r in successful
    ])

    await log_action(
        action="browser_web_search",
        user_id=user_id,
        agent_id=agent_id,
        success=result.success,
        error_message=result.error,
        duration_ms=result.execution_time_ms,
        metadata={
            "query_sanitized": clean[:100],
            "results_count": len(successful),
            "urls": [r["url"] for r in successful],
            "sandbox_type": result.sandbox_type,
        }
    )

    return {
        "success": result.success,
        "content": combined or result.error or "Aucun résultat.",
        "sources": [r["url"] for r in successful],
        "results_count": len(successful),
        "source_type": "web_external",
    }


async def fetch_url(
    url: str,
    user_id: str,
    agent_id: str,
    reason: str = "",
) -> dict:
    """Ouvre une adresse précise dans le conteneur navigateur."""
    result: BrowserResult = await navigateur.run_fetch(url)

    await log_action(
        action="browser_fetch_url",
        user_id=user_id,
        agent_id=agent_id,
        success=result.success,
        error_message=result.error,
        duration_ms=result.execution_time_ms,
        metadata={
            "url": url[:200],
            "reason": reason[:100],
            "was_filtered": result.was_filtered,
        }
    )

    content = ""
    if result.success and result.results:
        r = result.results[0]
        content = f"Source : {r['url']}\nTitre : {r.get('title','')}\n\n{r.get('content','')}"

    return {
        "success": result.success,
        "content": content or result.error or "Échec de récupération.",
        "url": url,
        "was_filtered": result.was_filtered,
        "source_type": "web_external",
    }


# ── Outils spécialisés métier Symbiose ───────────────────────────────

async def fetch_cadastral_info(commune: str, user_id: str, parcelle: Optional[str] = None) -> dict:
    """Recherche cadastrale — Agent 2 uniquement."""
    query = f"plan cadastral {commune}"
    if parcelle:
        query += f" parcelle {parcelle}"
    return await web_search(
        query=query,
        user_id=user_id,
        agent_id="agent2",
        max_results=2,
        context="site:cadastre.gouv.fr OR site:geoportail.gouv.fr",
    )


async def search_material_price(product: str, user_id: str) -> dict:
    """Recherche prix matériau — Agent 2, pré-chiffrage uniquement."""
    return await web_search(
        query=f"prix {product} professionnel paysagiste HT",
        user_id=user_id,
        agent_id="agent2",
        max_results=3,
    )


async def agent3_research(topic: str, user_id: str) -> dict:
    """Recherche documentaire pour l'Agent 3 lors de la génération d'un skill."""
    return await web_search(
        query=topic,
        user_id=user_id,
        agent_id="agent3",
        max_results=3,
    )
