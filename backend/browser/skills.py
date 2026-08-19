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
    sortie = {
        "url": url,
        "trouve": bool(r.get("success")),
        "contenu": r.get("content"),
        "a_savoir": ("Information EXTERNE, lue sur le web. Cite l'adresse dans ta "
                     "réponse et ne la présente jamais comme une donnée interne."),
    }
    # L'APERÇU SE MONTRE. Quand le conteneur a capturé la page, le modèle
    # reçoit la clé et le titre, et la consigne d'insérer le composant `site`
    # — c'est lui qui affiche l'image, le titre et le lien à l'écran.
    if r.get("apercu"):
        sortie["apercu"] = r["apercu"]
        sortie["titre"] = r.get("title")
        sortie["a_savoir"] += (
            " Montre la page : insère un bloc ```ui {\"type\":\"site\",\"url\":\"" + url
            + "\",\"titre\":\"" + str(r.get("title") or url).replace('"', "'")[:120]
            + "\",\"apercu\":\"" + str(r["apercu"]) + "\"} — l'écran y affiche la capture.")
    return sortie

async def naviguer(data: dict, user) -> dict:
    """LE NAVIGATEUR LIBRE : il regarde, il clique, il suit les liens.

    C'EST LA DÉMARCHE DE L'ONGLET, ramenée dans le chat. Les deux gestes
    ci-dessus suivent un parcours ÉCRIT D'AVANCE : ouvrir, extraire, rendre.
    Rapides et vérifiables, mais aveugles — ils ne franchissent pas une
    bannière de cookies, ne déplient pas un menu, ne suivent pas « voir plus ».

    Celui-ci confie la conduite au modèle : il voit la page, décide du prochain
    clic, recommence. C'est ce que faisait l'onglet, et ce qui marchait.

    IL RESTE EN LECTURE. Le mode écriture — remplir un formulaire, se connecter
    — dépend de `BROWSER_READONLY` côté déploiement, et le conteneur refuse la
    demande si le déploiement dit non. Le modèle ne peut pas s'en affranchir
    depuis ici : il n'a aucun paramètre pour ça.

    IL EST LENT, ET C'EST ASSUMÉ. Chaque étape est un aller-retour vers le
    modèle. Compter une à trois minutes, contre quelques secondes pour les deux
    gestes rapides. À réserver aux pages qui ne se laissent pas lire d'un coup.
    """
    import asyncio
    import json

    from browser_agent import client as agent_navigateur
    from database.connection import get_db

    tache = str(data.get("tache") or data.get("consigne") or "").strip()
    if not tache:
        return {"erreur": "Dis ce que le navigateur doit aller faire."}

    domaines = data.get("domaines") or []
    if isinstance(domaines, str):
        domaines = [d.strip() for d in domaines.split(",") if d.strip()]

    # La ligne AVANT le lancement, et l'identifiant vient de la base : le
    # conteneur rend compte de son avancement en écrivant dessus, et il ne
    # peut pas le faire sur une ligne qui n'existe pas encore.
    async with get_db() as conn:
        job = await conn.fetchval(
            "INSERT INTO browser_tasks (user_id, status, task_prompt, allowed_domains) "
            "VALUES ($1, 'pending', $2, $3) RETURNING id",
            getattr(user, "id", None), tache, domaines)

    try:
        await agent_navigateur.start_task_sur(
            str(job), tache, domaines, str(getattr(user, "id", "")),
            readonly=True, max_steps=14)
    except agent_navigateur.NavigateurCoupe as e:
        async with get_db() as conn:
            await conn.execute(
                "UPDATE browser_tasks SET status='failed', error=$2, updated_at=NOW() "
                "WHERE id=$1", job, "navigateur arrêté")
        return {"erreur": str(e)}

    # ON ATTEND, MAIS PAS INDÉFINIMENT. Le tour de conversation est synchrone :
    # rendre la main sans résultat obligerait à redemander, sans savoir quand.
    # Trois minutes couvrent une navigation ordinaire.
    fin = asyncio.get_event_loop().time() + 180
    etat = None
    while asyncio.get_event_loop().time() < fin:
        await asyncio.sleep(3)
        async with get_db() as conn:
            etat = await conn.fetchrow(
                "SELECT status, result, error, steps FROM browser_tasks WHERE id=$1", job)
        if etat and etat["status"] in ("completed", "failed", "cancelled"):
            break
    else:
        # DÉPASSÉ : on COUPE au lieu de laisser courir. Une session abandonnée
        # garde un Chromium en vie, et la mémoire est la ressource rare ici.
        try:
            await agent_navigateur.cancel_task(str(job))
        except Exception:  # noqa: BLE001 — l'abandon ne doit pas masquer le dépassement
            logger.info("Abandon de navigation non confirmé (job %s)", job)
        # LE NOMBRE D'ÉTAPES FRANCHIES EST LE DIAGNOSTIC. Zéro étape en trois
        # minutes ne dit pas « site lent » : ça dit que l'agent n'a jamais
        # démarré — Chromium étranglé, ou modèle à quota épuisé.
        etapes = int(etat["steps"] or 0) if etat else 0
        return {"tache": tache, "trouve": False,
                "erreur": (("la navigation a dépassé trois minutes et a été "
                            "arrêtée après %d étape(s) ; le site est sans doute "
                            "long à parcourir" % etapes) if etapes
                           else ("la navigation a été arrêtée après trois minutes "
                                 "sans avoir pu franchir la moindre étape : le "
                                 "navigateur ou son modèle n'a pas démarré, ce "
                                 "n'est pas la faute du site"))}

    if not etat or etat["status"] != "completed":
        return {"tache": tache, "trouve": False,
                "erreur": (etat["error"] if etat else None) or "la navigation n'a pas abouti"}

    # asyncpg rend le JSONB en texte : sans ce décodage, le modèle reçoit une
    # chaîne d'accolades au lieu du résumé.
    brut = etat["result"]
    if isinstance(brut, str):
        try:
            brut = json.loads(brut)
        except Exception:  # noqa: BLE001
            brut = {}
    brut = brut or {}

    # Le journal d'étapes n'a pas sa place dans le contexte du modèle : ce qui
    # compte, c'est CE QU'IL A VU et OÙ. On garde les adresses, pas les clics.
    vues, deja = [], set()
    for e in brut.get("step_log") or []:
        u = e.get("url")
        if u and u not in deja:
            deja.add(u)
            vues.append(u)

    return {
        "tache": tache,
        "trouve": bool(brut.get("summary")),
        "contenu": brut.get("summary"),
        "pages_vues": vues[:15],
        "etapes": etat["steps"],
        "a_savoir": ("Information EXTERNE, vue sur le web. Cite les adresses et ne "
                     "la présente jamais comme une donnée interne."),
    }
