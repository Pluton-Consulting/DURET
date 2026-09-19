"""
Interface entre les agents LangGraph et le CONTENEUR NAVIGATEUR.

Chaque outil assainit la requête, délègue au conteneur, journalise dans l'audit.
Le backend n'ouvre lui-même aucune page : tout ce qui vient d'un site inconnu
est manipulé dans le conteneur navigateur, seul contraint pour cela.

Ce module parlait auparavant à un bac à sable Daytona — un service tiers dont
la clé manquait en production, ce qui faisait échouer la recherche web en
silence. Le contrat de retour n'a pas bougé d'un champ.
"""

import re
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
        # Par page : l'adresse, son titre et les premiers mots lus — ce qui
        # permet à l'écran de dire CE QUI a été consulté, pas seulement où
        # (09/09 : un tableau d'une adresse nue sous la réponse, « on ne sait
        # pas à quoi ça a servi »).
        "resultats": [{"url": r["url"], "titre": str(r.get("title") or "").strip(),
                       "extrait": _extrait(r.get("content"), requete=query, titre=r.get("title") or "")}
                      for r in successful],
        "results_count": len(successful),
        "source_type": "web_external",
    }


def _plat_web(t) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", str(t or "").casefold())
                   if unicodedata.category(c) != "Mn")


def _extrait(texte, longueur: int = 160, requete: str = "", titre: str = "") -> str:
    """Le passage d'une page qui répond à la recherche, sur une ligne.

    LES PREMIERS MOTS D'UNE PAGE SONT SON DÉCOR (19/09, banc Duret) : « DTU 53.2 » rendait
    dans « Ce qu'on y a lu » le titre recopié, « Aller au contenu », « --> --> --> ». Le
    passage retenu est celui qui porte le plus de mots de la recherche ; sans recherche ni
    passage qui en porte, le début de la page, titre retiré."""
    brut = re.sub(r"-->|<!--", " ", str(texte or ""))
    termes = {m for m in re.findall(r"\w{4,}", _plat_web(requete))} if requete else set()
    choisi = ""
    if termes:
        morceaux = [" ".join(m.split()) for m in re.split(r"(?<=[.!?;:])\s+|\n+", brut)]
        notes = [(sum(1 for t in termes if t in _plat_web(m)), m) for m in morceaux if len(m) >= 25]
        if notes:
            meilleur = max(notes, key=lambda x: x[0])
            if meilleur[0]:
                choisi = meilleur[1]
                if len(choisi) > longueur:
                    # Fenêtre centrée sur le premier terme trouvé, pas le début de la phrase.
                    plat = _plat_web(choisi)
                    pos = min((plat.find(t) for t in termes if t in plat), default=0)
                    debut = max(0, pos - longueur // 3)
                    choisi = ("…" if debut else "") + choisi[debut:debut + longueur].strip()
    if not choisi:
        choisi = " ".join(brut.split())
        t = " ".join(str(titre or "").split())
        if t and choisi.startswith(t):
            choisi = choisi[len(t):].lstrip(" -—|:")
        choisi = re.sub(r"^(?:aller au contenu|passer au contenu|skip to content)\s*", "", choisi, flags=re.I)
    return (choisi[:longueur].rstrip() + "…") if len(choisi) > longueur else choisi


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

    premier = result.results[0] if result.results else {}
    return {
        "success": result.success,
        "content": content or result.error or "Échec de récupération.",
        "url": url,
        "was_filtered": result.was_filtered,
        "source_type": "web_external",
        # La clé d'aperçu et le titre remontent tels quels : c'est le geste
        # `ouvrir_page` qui décide d'en faire un composant à l'écran.
        "apercu": premier.get("apercu"),
        "title": premier.get("title"),
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
