"""
LA NAVIGATION DEVIENT UN GESTE QUE L'ASSISTANT PEUT CHOISIR.

Jusqu'ici, le web n'était pas une action : c'était un nœud du graphe, déclenché
AUTOMATIQUEMENT et seulement après une recherche documentaire infructueuse. Le
modèle n'avait donc rien à proposer, et il le disait — relevé en production,
mot pour mot :

    « Je ne peux pas accéder au site web de Symbiose Paysage ni naviguer sur
      internet. Mes connaissances se limitent à ce qui se trouve dans la
      mémoire d'entreprise. »

Ce n'était pas une hallucination : c'était vrai. Aucune action du catalogue ne
lui permettait d'aller voir une page, alors même que le conteneur navigateur
tournait à côté, prêt à le faire. Un onglet séparé portait cette capacité, ce
qui obligeait à quitter la conversation pour l'utiliser.

Les deux gestes ci-dessous la ramènent dans le chat, là où la demande naît.

CE QU'ILS NE FONT PAS. Ils LISENT, et rien d'autre : pas de formulaire, pas de
connexion, pas de clic. La navigation autonome — celle qui remplit des champs
et se connecte à des sites — reste hors du catalogue : elle a des effets
externes, elle demande un accord humain, et elle n'a pas sa place dans un geste
que le modèle déclenche seul.

L'ISOLEMENT ET L'INTERRUPTEUR VALENT ICI AUSSI. Ces deux gestes passent par
`browser/tools.py`, donc par le conteneur navigateur — le seul contraint pour
ouvrir des pages inconnues — et respectent `browser_enabled`. Couper la
navigation les coupe aussi.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("symbiose.browser.skills")


async def chercher_web(data: dict, user) -> dict:
    """Cherche sur le web et rend le texte des premières pages."""
    from browser.tools import web_search

    requete = str(data.get("requete") or data.get("query") or "").strip()
    if not requete:
        return {"erreur": "Donne les termes à chercher."}

    try:
        nombre = int(data.get("nombre") or 3)
    except (TypeError, ValueError):
        nombre = 3
    # Trois pages suffisent à répondre, et chacune coûte un chargement complet.
    # Au-delà de cinq, le texte cumulé dépasse ce qu'un tour peut porter.
    nombre = max(1, min(nombre, 5))

    r = await web_search(query=requete, user_id=str(getattr(user, "id", "")),
                         agent_id="agent1", max_results=nombre)
    return {
        "requete": requete,
        "trouve": bool(r.get("success")),
        "contenu": r.get("content"),
        "sources": r.get("sources") or [],
        # LE MODÈLE DOIT SAVOIR D'OÙ ÇA VIENT. Une page web n'a pas l'autorité
        # d'un document de l'entreprise : elle se cite, elle ne fait pas foi.
        "a_savoir": ("Information EXTERNE, trouvée sur le web. Cite les adresses "
                     "dans ta réponse et ne la présente jamais comme une donnée "
                     "interne de l'entreprise."),
    }


async def ouvrir_page(data: dict, user) -> dict:
    """Ouvre une adresse précise et en rend le texte."""
    from browser.tools import fetch_url

    url = str(data.get("url") or "").strip()
    if not url:
        return {"erreur": "Donne l'adresse à ouvrir."}
    if not url.startswith(("http://", "https://")):
        # Le modèle écrit souvent « symbiose-paysage.fr » sans protocole ; on le
        # complète plutôt que de refuser pour une raison qu'il ne comprendrait pas.
        url = "https://" + url

    r = await fetch_url(url=url, user_id=str(getattr(user, "id", "")),
                        agent_id="agent1", reason=str(data.get("motif") or ""))
    return {
        "url": url,
        "trouve": bool(r.get("success")),
        "contenu": r.get("content"),
        "a_savoir": ("Information EXTERNE, lue sur le web. Cite l'adresse dans ta "
                     "réponse et ne la présente jamais comme une donnée interne."),
    }
