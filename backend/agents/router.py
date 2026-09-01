"""
Routeur LangGraph principal
Analyse la requête entrante et dispatche vers le bon agent (A1/A2/A3).
Human-in-the-loop : nœud `human_gate` qui suspend le graph via interrupt()
quand une validation humaine est requise — l'état est persisté par le checkpointer,
reprise via runtime.resume_turn().
"""
import datetime
import logging

from langgraph.graph import StateGraph, END
from langgraph.types import interrupt

from agents.state import AgentState
from agents.agent1 import agent1_graph
from agents.agent2 import agent2_graph
from agents.agent3 import agent3_graph
from llm.router import classify_request_tier, LLMTier
from database.connection import get_db
from security.rbac import SCHEDULE_EXEMPT_ROLES
from config import settings
from fastapi import HTTPException

logger = logging.getLogger("duret.router")


async def classify_node(state: AgentState) -> dict:
    """Nœud 1 : classification — quel agent, quel palier LLM."""
    query = state["query"]
    has_attachment = state.get("has_attachment", False)
    tier = classify_request_tier(query, has_attachment)

    # La vision (agent2) ne sert qu'aux IMAGES et aux PDF sans texte (plans, photos,
    # scans). Un Excel, un Word ou un CSV a déjà été converti en texte en amont :
    # l'envoyer à un modèle de vision n'aurait aucun sens. Il part donc chez agent1,
    # son contenu étant injecté dans le contexte comme un document de la mémoire.
    if has_attachment and not state.get("attachment_text"):
        target = "agent2"
        tier = LLMTier.COMPLEX
    else:
        target = "agent1"

    return {"target_agent": target, "llm_tier": tier.value}


async def check_schedule_node(state: AgentState) -> dict:
    """
    Nœud 2 : vérification plage horaire (8h–18h par défaut).
    super_admin / direction exemptés ; bypass_schedule individuel ; plage par user.
    """
    user_role = state.get("user_role", "")
    # Une tâche autonome n'est pas un usage interactif : la plage horaire protège
    # les utilisateurs devant leur écran, pas un traitement de fond. La tâche a été
    # créée par un humain authentifié, et toute action à effet externe reste soumise
    # à validation. La tuer à 7h30 par un 403 n'apporterait aucune sécurité.
    if state.get("trigger_kind") in ("schedule", "webhook"):
        return {}

    if user_role in SCHEDULE_EXEMPT_ROLES:
        return {}

    user_id = state.get("user_id")
    start_hour = settings.access_start_hour
    end_hour = settings.access_end_hour
    bypass = False

    if user_id:
        async with get_db() as conn:
            row = await conn.fetchrow(
                """SELECT bypass_schedule, schedule_start_hour, schedule_end_hour
                   FROM users WHERE id = $1::uuid""",
                user_id,
            )
            gc = await conn.fetchrow("SELECT schedule_start_hour, schedule_end_hour FROM global_config WHERE id = 1")
        if gc:
            start_hour = gc["schedule_start_hour"]
            end_hour = gc["schedule_end_hour"]
        if row:
            bypass = bool(row["bypass_schedule"])
            if row["schedule_start_hour"] is not None:
                start_hour = row["schedule_start_hour"]
            if row["schedule_end_hour"] is not None:
                end_hour = row["schedule_end_hour"]

    if bypass:
        return {}

    now = datetime.datetime.now()
    if not (start_hour <= now.hour < end_hour):
        raise HTTPException(
            status_code=403,
            detail=(
                f"Accès refusé à {now.hour}h{now.minute:02d}. "
                f"Plage autorisée : {start_hour}h00–{end_hour}h00."
            ),
        )
    return {}


async def dispatch_agent1(state: AgentState, config=None) -> dict:
    # config propagé => l'exécution du sous-graphe (et son appel LLM) est tracée
    # dans le MÊME arbre Langfuse que le tour complet.
    return await agent1_graph.ainvoke(state, config)


async def dispatch_agent2(state: AgentState, config=None) -> dict:
    return await agent2_graph.ainvoke(state, config)


async def dispatch_agent3(state: AgentState, config=None) -> dict:
    return await agent3_graph.ainvoke(state, config)


async def human_gate_node(state: AgentState) -> dict:
    """
    Human-in-the-loop : si une validation est requise, suspend le graph.
    `interrupt()` persiste l'état et rend la main ; la reprise fournit la décision
    {"approved": bool, "validated_by": str} via runtime.resume_turn().
    """
    if not state.get("requires_validation"):
        return {}

    decision = interrupt({
        "reason": state.get("validation_reason"),
        "payload": state.get("validation_payload"),
        "agent": state.get("target_agent"),
        "draft": state.get("final_response") or state.get("llm_response"),
    })

    approved = bool(decision.get("approved")) if isinstance(decision, dict) else bool(decision)
    validated_by = decision.get("validated_by") if isinstance(decision, dict) else None
    validation_id = decision.get("validation_id") if isinstance(decision, dict) else None

    return {
        "validation_status": "approved" if approved else "rejected",
        "validated_by": validated_by,
        # Quelle ligne a été résolue : `execute_action_node` la relira par son
        # identifiant, pas par « la dernière approuvée du fil ».
        "validation_id": validation_id,
        "requires_validation": False,
    }


async def execute_action_node(state: AgentState, config=None) -> dict:
    """Exécute une action à effet EXTERNE, après approbation humaine.

    C'est le seul endroit du système où une telle action s'exécute. Trois
    vérifications, toutes indispensables :

      1. la décision doit être « approuvé » ;
      2. l'identité du DEMANDEUR est rechargée fraîche — le valideur approuve une
         action, il ne prête pas ses droits, et un compte désactivé entre-temps ne
         ressuscite pas ;
      3. le hash du payload doit correspondre à celui qui a été présenté à
         l'humain : approuver « envoyer à Dupont » ne peut pas servir à envoyer
         ailleurs, même si l'état a été altéré entre-temps.
    """
    action = state.get("pending_action") or {}
    if state.get("validation_status") != "approved" or not action.get("skill"):
        # Refus : AUCUNE phrase n'est ajoutée (règle de Noa, 30/08 — pas de
        # message préécrit dans le chat). La carte de validation porte déjà
        # l'état « refusée » à l'écran, et le texte du modèle qui proposait
        # l'action reste tel quel.
        return {"pending_action": None,
                "final_response": (state.get("final_response") or "").strip() or None}

    from tasks.identity import charger_executant
    from skills.executor import execute_skill, hash_payload, SkillError, expert_du_skill

    utilisateur = await charger_executant(state.get("user_id"))
    if utilisateur is None:
        return {"pending_action": None,
                "final_response": "Action annulée : le compte du demandeur n'est plus actif."}

    # LA ligne résolue, ciblée par son identifiant quand il a traversé la
    # reprise. Le repli « dernière approuvée du fil » reste pour les reprises
    # anciennes, mais il est fragile : un fil de test porte plusieurs
    # validations, et la plus récente n'est pas forcément celle-ci.
    async with get_db() as conn:
        if state.get("validation_id"):
            approuve = await conn.fetchval(
                """SELECT payload_hash FROM validations
                   WHERE id = $1::uuid AND status = 'approved'""",
                str(state["validation_id"]))
        else:
            approuve = await conn.fetchval(
                """SELECT payload_hash FROM validations
                   WHERE thread_id = $1 AND status = 'approved'
                   ORDER BY resolved_at DESC NULLS LAST LIMIT 1""",
                state.get("thread_id"))

    attendu = hash_payload(action["skill"], action.get("args") or {})
    if not approuve or approuve != attendu:
        logger.warning("Action %s abandonnée : le contenu approuvé ne correspond pas",
                       action.get("skill"))
        return {"pending_action": None,
                "final_response": "Action annulée : le contenu approuvé ne correspond pas "
                                  "à l'action demandée."}

    resultat = None
    try:
        resultat = await execute_skill(
            action["skill"], action.get("args") or {}, user=utilisateur,
            approbation={"payload_hash": approuve,
                         "validated_by": state.get("validated_by")},
            trigger={"type": "resume", "id": state.get("thread_id")},
        )
        message = await _reponse_apres_action(state, action["skill"], resultat)
    except SkillError as e:
        message = await _reponse_apres_echec(state, action["skill"], str(e))
    except Exception as e:  # noqa: BLE001
        logger.warning("Échec de l'action %s : %s", action.get("skill"), e)
        message = await _reponse_apres_echec(
            state, action["skill"], str(getattr(e, "detail", None) or e))

    sortie = {"pending_action": None,
              "final_response": ((state.get("final_response") or "").rstrip()
                                 + f"\n\n{message}").strip()}
    # LA SUITE APRÈS UN ACCORD (01/09). Ce chemin ne passe PAS par
    # `rehydrate_node` : jusqu'ici, un visuel tiré ou un mail parti n'a jamais
    # porté la moindre suggestion — alors que c'est le moment où la suite est
    # la plus évidente (une variante, une relance, un dépôt). Le plan approuvé
    # est exclu d'office : le bloc plus bas remet `final_response` à None.
    try:
        from agents.suggestions import poser as _poser_suites
        from agents.suggestions import suggestions_du_tour
        _suites = suggestions_du_tour(sortie["final_response"],
                                      [{"skill": action["skill"], "ok": True}],
                                      expert=str(state.get("target_agent") or ""))
        if _suites:
            sortie["final_response"] = _poser_suites(sortie["final_response"], _suites)
    except Exception:  # noqa: BLE001 — une suggestion ne casse jamais une reprise
        pass
    # L'ATTRIBUTION D'ÉCRAN SUIT LE TRAVAIL : un skill qui déclare son expert
    # (un tirage de visuel = conception) crédite le tour à cet expert, pour que
    # `agent_used`, le tableau de bord et l'historique du fil disent qui a
    # réellement travaillé — la reprise après validation ne repasse pas par
    # la boucle d'outils, il faut donc le redire ici.
    exp = expert_du_skill(action["skill"])
    if exp:
        sortie["target_agent"] = exp
    # UN PLAN APPROUVÉ N'EST PAS UN TRAVAIL FAIT : c'est un travail AUTORISÉ.
    #
    # Les autres actions à effet externe se terminent ici — le devis est parti,
    # l'image est tirée, il n'y a plus rien à faire. Le plan, lui, ne fait
    # qu'ouvrir la porte : ce que la personne vient d'approuver doit maintenant
    # être exécuté. On repasse donc la main à l'assistant, avec les étapes en
    # consigne, et c'est LUI qui rendra la réponse unique promise.
    if action["skill"] == "proposer_plan" and isinstance(resultat, dict):
        etapes = ((resultat.get("output") or {}) or {}).get("plan") or []
        if etapes:
            sortie["plan_valide"] = list(etapes)
            # La réponse finale sera écrite par l'assistant au bout du plan :
            # celle-ci n'est qu'un accusé, elle ne doit pas rester en travers.
            sortie["final_response"] = None
            sortie["llm_response"] = None
    # LA RÉFÉRENCE DE L'IMAGE VALIDÉE ENTRE DANS L'HISTORIQUE DU MODÈLE.
    # L'historique (`messages`) n'est écrit que par la réhydratation, AVANT la
    # décision humaine : le résultat d'une action validée n'y figurait jamais.
    # Conséquence relevée le 22/08 : après un tirage final validé, « ajoute une
    # maison sur cette image » a retouché l'ESSAI d'avant — la seule clé que le
    # modèle voyait. On n'ajoute à l'historique QUE le bloc `visuel` (des clés,
    # pas de donnée personnelle) : le reste de la sortie d'un skill exécuté
    # n'est pas masqué, et l'historique part au modèle.
    try:
        import json as _json
        from langchain_core.messages import AIMessage
        from agents.agent1 import _blocs_de
        # Un dict, ou une LISTE (un mail à trois pièces jointes rend trois cartes).
        blocs = [b for b in _blocs_de(((resultat or {}).get("output") or {}).get("bloc_ui")
                                     if isinstance((resultat or {}).get("output"), dict) else None)
                 if b.get("type") in ("visuel", "plan", "fichier")]
        bloc = blocs[0] if blocs else None
        # Le PLAN approuvé y entre pour la même raison, et pour une de plus :
        # la réponse de ce tour sera écrite plus loin, par l'assistant. Sans
        # cette ligne, le plan que la personne vient d'approuver disparaîtrait
        # de la conversation au moment même où le travail commence.
        if blocs:
            sortie["messages"] = [AIMessage(
                content=(str(message).strip() + "\n\n" if bloc.get("type") == "plan" else "")
                + "\n\n".join("```ui\n" + _json.dumps(b, ensure_ascii=False) + "\n```" for b in blocs))]
    except Exception:  # noqa: BLE001 - l'historique n'est pas vital
        pass
    return sortie


async def _reponse_apres_action(state: AgentState, skill: str, resultat: dict) -> str:
    """Ce que l'utilisateur LIT après une action validée.

    Deux époques. D'abord le nœud jetait la sortie du skill (« Action exécutée
    après validation ») : un visuel facturé n'atteignait jamais l'écran. Puis
    le `message_final` du skill s'affichait tel quel — une phrase écrite dans
    le code. Règle de Noa du 30/08 : la PROSE vient du MODÈLE, la mécanique
    n'apporte que le BLOC d'écran, qui reste restitué tel quel (c'est lui, la
    preuve de ce qui a été fait — un composant, pas une phrase).

    La sortie d'un skill validé n'est PAS masquée (elle n'est jamais partie au
    modèle) : on la MASQUE donc avec la carte cumulative du fil avant l'appel,
    et la prose revient réhydratée — même aller-retour que le reste du
    système, mêmes garde-fous (un jeton orphelin devient [À COMPLÉTER]).
    Si aucun fournisseur ne répond, le bloc s'affiche seul.
    """
    import json as _json
    from security.anonymizer import anonymizer
    from agents.agent1 import _rediger_par_le_modele

    sortie = (resultat or {}).get("output") or {}
    if not isinstance(sortie, dict):
        sortie = {}
    bloc = sortie.get("bloc_ui")

    prose = ""
    if skill == "proposer_plan":
        # Un plan approuvé rouvre le travail et sa réponse est aussitôt
        # remplacée (final_response remis à None plus haut) : payer un appel
        # modèle pour une prose jetée serait du gâchis — le bloc suffit.
        import json as _json2
        if isinstance(bloc, dict) and bloc.get("type"):
            return "```ui\n" + _json2.dumps(bloc, ensure_ascii=False) + "\n```"
        return ""
    try:
        # Les champs adressés au modèle rédacteur ou à l'écran ne sont pas des
        # faits à raconter : on les écarte avant de masquer.
        donnees = {k: v for k, v in sortie.items()
                   if k not in ("bloc_ui", "a_faire", "note", "a_savoir")}
        brut = _json.dumps(donnees, ensure_ascii=False, default=str)[:1200]
        carte = dict(state.get("entity_map") or {})
        masque, carte = anonymizer.anonymize(brut, carte)
        prose = await _rediger_par_le_modele(
            state.get("anonymized_query") or "",
            [{"skill": skill, "ok": True, "resultat_masque": masque}],
            "action_validee")
        if prose:
            prose = anonymizer.rehydrate(prose, carte)
            for jeton in anonymizer.find_placeholders(prose):
                prose = prose.replace(jeton, "[À COMPLÉTER]")
    except Exception as e:  # noqa: BLE001 — la rédaction ne casse jamais la reprise
        logger.info("Prose post-validation indisponible (%s) : %s", skill, str(e)[:120])
        prose = ""

    message = prose
    from agents.agent1 import _blocs_de
    for _b in _blocs_de(bloc):          # un dict, ou une liste (pièces jointes)
        message = ((message + "\n\n") if message else "") \
            + "```ui\n" + _json.dumps(_b, ensure_ascii=False) + "\n```"
    if not message:
        # MÊME EXCEPTION ASSUMÉE que pour l'échec : une action EXTERNE validée
        # a eu lieu (un mail est parti, un fichier est déposé) — son issue DOIT
        # se lire, même cascade morte. Sans prose et sans bloc, le compte
        # rendu du skill est le dernier témoin ; l'invisible serait un
        # mensonge par omission.
        message = str(sortie.get("message_final") or sortie.get("message") or "").strip()
    return message


async def _reponse_apres_echec(state: AgentState, skill: str, erreur: str) -> str:
    """L'échec d'une action validée, dit par le MODÈLE — avec un repli, lui.

    Seule exception assumée à « aucun texte hors modèle » : si toute la
    cascade est morte, l'erreur BRUTE du skill s'affiche quand même. Un tirage
    facturé qui a échoué, un dépôt refusé, un envoi impossible DOIVENT se
    lire — un échec invisible est pire qu'une phrase imparfaite.
    """
    from security.anonymizer import anonymizer
    from agents.agent1 import _rediger_par_le_modele

    try:
        carte = dict(state.get("entity_map") or {})
        masque, carte = anonymizer.anonymize(str(erreur)[:400], carte)
        prose = await _rediger_par_le_modele(
            state.get("anonymized_query") or "",
            [{"skill": skill, "ok": False, "resultat_masque": masque}],
            "echec_apres_validation")
        if prose:
            prose = anonymizer.rehydrate(prose, carte)
            for jeton in anonymizer.find_placeholders(prose):
                prose = prose.replace(jeton, "[À COMPLÉTER]")
            return prose
    except Exception as e:  # noqa: BLE001
        logger.info("Prose d'échec indisponible (%s) : %s", skill, str(e)[:120])
    return str(erreur)


def route_apres_gate(state: AgentState) -> str:
    """Après la décision humaine : exécuter l'action approuvée, ou terminer."""
    if (state.get("validation_status") == "approved"
            and (state.get("pending_action") or {}).get("skill")):
        return "execute_action"
    return "fin"


def route_apres_execution(state: AgentState) -> str:
    """Après une action validée : le travail est fait, sauf si c'était un plan."""
    return "agent1" if state.get("plan_valide") else "fin"


# ── La main revient à l'assistant après la vision ─────────────────────
#
# UN PLAN ANALYSÉ N'EST PAS UNE DEMANDE SATISFAITE.
#
# Dès qu'une image ou un plan est joint, le tour part à l'expert vision — et
# s'arrêtait là. Or cet agent-ci ne sait que REGARDER : il n'appelle aucune
# action, ne lit aucune fiche client, ne produit aucun document, n'écrit aucun
# mail. « Le client m'envoie ce plan et demande un chiffrage : analyse-le,
# retrouve son historique et prépare-moi le pré-devis et le mail » recevait
# donc une analyse, et rien d'autre. La demande était lue en entier et honorée
# au quart, sans que rien ne le dise.
#
# On rend donc la main : l'analyse devient un élément du contexte, et
# l'assistant reprend la demande d'origine avec ses gestes sous la main. Le
# départ se fait sur ce que la demande RÉCLAME, pas sur ce que l'image
# contient : « c'est quoi cette plante ? » n'a besoin de personne d'autre.
_SUITE_ATTENDUE = (
    "devis", "chiffr", "estim", "budget", "prix", "cout", "coût", "tarif",
    "mail", "message", "courrier", "réponse", "reponse", "répond", "repond",
    "client", "historique", "dossier", "fiche", "document", "rapport", "pdf",
    "docx", "excel", "compte rendu", "prépare", "prepare", "rédige", "redige",
    "produis", "génère", "genere", "fais-moi", "fais moi", "sors-moi",
    # LA RETOUCHE AUSSI (31/08). Le scénario n°1 de Symbiose — « une image + une
    # demande → visualisation de la prestation finale » — s'arrêtait à
    # l'analyse : « ajoute une pergola », « remplace la pelouse par une terrasse »
    # ne contenaient aucun mot de la liste, la vision répondait « dites-moi ce
    # que vous voulez changer », et il fallait un SECOND message pour que
    # l'assistant appelle `modifier_visuel`. Le coût d'une passe de main en trop
    # est une lecture de l'analyse par l'assistant ; le coût d'une passe
    # manquante est une demande honorée à moitié.
    "ajout", "remplac", "modifi", "retouch", "transform", "enlève", "enleve",
    "supprime", "installe", "mets ", "met ", "crée", "cree", "imagine", "simul",
    "visuel", "rendu", "projet", "illustr", "dessine", "variante", "version",
    "à la place", "a la place", "avec un", "avec une", "avec des",
)


async def passer_la_main_node(state: AgentState) -> dict:
    """Prépare le passage de l'expert vision à l'assistant.

    L'analyse est déposée comme un TEXTE JOINT : c'est le canal qu'`agent1`
    consomme déjà pour une pièce jointe lisible (`rag_node`), donc aucun
    chemin nouveau. On retire en revanche l'image elle-même : la vision a fait
    son travail, la repasser ferait repartir un second appel multimodal pour
    rien. Et on efface la réponse de la vision : c'est l'assistant qui rédigera
    la réponse du tour, une seule fois, à la fin.
    """
    analyse = state.get("vision_analysis") or state.get("final_response") or ""
    nom = state.get("attachment_name") or "plan joint"
    return {
        # `target_agent` N'EST PAS TOUCHÉ, ET C'EST VOLONTAIRE. Il ne sert plus
        # au routage à ce stade (on entre dans l'assistant par un edge direct) :
        # il ne sert qu'à dire QUI a travaillé, sur la carte du tour et dans
        # l'historique. Or le plan a bien été lu par l'expert plans & visuels ;
        # rendre le tour à l'assistant effacerait ce travail de son compteur, et
        # l'attribution qu'on venait de réparer le 23/08 repartirait à zéro.
        "attachment_b64": None,
        "attachment_text": (f"ANALYSE DU DOCUMENT JOINT ({nom}), faite par l'expert "
                            f"plans & visuels :\n{analyse}"),
        "final_response": None,
        "llm_response": None,
        # La lecture du plan n'a demandé aucun accord ; ce qui suivra le
        # demandera si un geste l'exige, par le chemin habituel.
        "requires_validation": False,
    }


def route_apres_agent2(state: AgentState) -> str:
    """La vision suffit-elle, ou la demande réclame-t-elle la suite ?"""
    if not (state.get("vision_analysis") or state.get("final_response")):
        return "human_gate"                 # l'analyse a échoué : rien à enchaîner
    if state.get("plan_valide"):
        return "human_gate"                 # on exécute déjà un plan : pas de rebond
    demande = (state.get("query") or "").lower()
    return "agent1" if any(m in demande for m in _SUITE_ATTENDUE) else "human_gate"


def route_to_agent(state: AgentState) -> str:
    """Edge conditionnel principal — out_of_scope force l'Agent 3."""
    if state.get("out_of_scope", False):
        return "agent3"
    target = state.get("target_agent", "agent1")
    return "agent2" if target == "agent2" else "agent1"


async def build_main_graph(checkpointer):
    """Construit le graph principal avec checkpointing (persistance par thread_id)."""
    graph = StateGraph(AgentState)

    graph.add_node("classify", classify_node)
    graph.add_node("check_schedule", check_schedule_node)
    graph.add_node("agent1", dispatch_agent1)
    graph.add_node("agent2", dispatch_agent2)
    graph.add_node("agent3", dispatch_agent3)
    graph.add_node("human_gate", human_gate_node)
    graph.add_node("execute_action", execute_action_node)

    graph.set_entry_point("classify")
    graph.add_edge("classify", "check_schedule")
    graph.add_conditional_edges(
        "check_schedule",
        route_to_agent,
        {"agent1": "agent1", "agent2": "agent2", "agent3": "agent3"},
    )
    graph.add_node("passer_la_main", passer_la_main_node)

    graph.add_edge("agent1", "human_gate")
    # L'expert vision rend la main à l'assistant quand la demande va au-delà de
    # la lecture du document (voir route_apres_agent2).
    graph.add_conditional_edges("agent2", route_apres_agent2,
                                {"agent1": "passer_la_main", "human_gate": "human_gate"})
    graph.add_edge("passer_la_main", "agent1")
    graph.add_edge("agent3", "human_gate")
    # Après la décision humaine : exécuter l'action approuvée, sinon terminer.
    graph.add_conditional_edges("human_gate", route_apres_gate,
                                {"execute_action": "execute_action", "fin": END})
    # Un plan approuvé rouvre le travail : l'assistant exécute ce qui vient
    # d'être autorisé. Toute autre action validée termine le tour.
    graph.add_conditional_edges("execute_action", route_apres_execution,
                                {"agent1": "agent1", "fin": END})

    return graph.compile(checkpointer=checkpointer)
