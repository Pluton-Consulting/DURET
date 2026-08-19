"""
Agent 2 — Appels d'offres / Chiffrage / Analyse de plans (BTP — Duret & Sols)
Rôle : analyse de plans et documents techniques (CCTP, DPGF, plans), extraction
structurée (revêtements, surfaces, plinthes, contraintes), recherche de dossiers
similaires, préparation d'une base de pré-chiffrage — TOUJOURS validée par Benoît.

Pipeline : preprocess → vision → extraction → [browser?] → similar_projects → prechiffrage

Sécurité / RGPD :
- Les fichiers sont ré-encodés via Pillow → suppression des métadonnées EXIF/GPS.
- Le pré-chiffrage n'est JAMAIS validé par l'IA : il est rendu comme une estimation
  indicative, marquée comme telle, à valider par un humain avant tout usage. Aucune
  porte d'accord devant la LECTURE (voir prechiffrage_node).
"""
import base64
import io
import json
import logging
import re

from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END
from agents.state import AgentState
from llm.router import get_llm, get_vision_llm, LLMTier

logger = logging.getLogger("duret.agent2")

VISION_PROMPT = (
    "Tu es l'assistant études & chiffrage de Duret & Sols (travaux de sols et revêtements, BTP). "
    "Analyse ce plan ou document technique pour préparer un métré et un chiffrage. Décris de façon "
    "factuelle et structurée : nature des locaux/zones, revêtements de sol indiqués (carrelage, "
    "résine, béton, sol souple, parquet…), surfaces et cotes LISIBLES, linéaires (plinthes, joints, "
    "seuils), niveaux, contraintes techniques (accès, réservations, existant à déposer, chape). "
    "Repère les informations utiles au métré (surfaces en m², longueurs de plinthes en ml, quantités). "
    "Ne devine JAMAIS une mesure non lisible : dis « non lisible ». Réponds en français, structuré. "
    "Typographie : n'utilise JAMAIS de tiret cadratin ni de tiret demi-cadratin ; emploie plutôt une virgule, un deux-points, une parenthèse ou un point."
)

# Taille max d'image envoyée au modèle vision (coût / limites API).
_MAX_IMG_WIDTH = 1568


# ── Nœuds ────────────────────────────────────────────────────────────

async def preprocess_attachment_node(state: AgentState) -> dict:
    """Prétraitement : PDF→image (1re page), et suppression EXIF/GPS des photos (Pillow)."""
    b64 = state.get("attachment_b64")
    mime = (state.get("attachment_mime") or "").lower()
    if not b64:
        return {}

    try:
        raw = base64.b64decode(b64)
    except Exception:
        return {"error": "attachment_base64_invalide"}

    # PDF → rendre la première page en image (PyMuPDF, import optionnel).
    if "pdf" in mime:
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(stream=raw, filetype="pdf")
            page = doc.load_page(0)
            pix = page.get_pixmap(dpi=150)
            raw = pix.tobytes("png")
            mime = "image/png"
        except ImportError:
            return {"error": "pdf_non_supporte_installer_pymupdf",
                    "llm_response": "Analyse PDF indisponible (dépendance PyMuPDF absente)."}
        except Exception as e:
            return {"error": f"pdf_illisible_{type(e).__name__}"}

    # Image → ré-encodage Pillow (retire EXIF/GPS) + downscale.
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        if img.width > _MAX_IMG_WIDTH:
            ratio = _MAX_IMG_WIDTH / img.width
            img = img.resize((_MAX_IMG_WIDTH, int(img.height * ratio)))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=80)  # nouvel encodage = sans métadonnées EXIF
        return {
            "attachment_b64": base64.b64encode(out.getvalue()).decode(),
            "attachment_mime": "image/jpeg",
        }
    except Exception as e:
        return {"error": f"image_illisible_{type(e).__name__}"}


async def vision_node(state: AgentState, config=None) -> dict:
    """Analyse visuelle multimodale. Dégradation propre si aucun modèle vision configuré."""
    b64 = state.get("attachment_b64")
    if not b64:
        return {"vision_analysis": None}

    llm, label = get_vision_llm()
    if llm is None:
        return {
            "vision_analysis": None,
            "llm_response": ("Analyse visuelle indisponible : aucun modèle vision configuré. "
                             "Ajoutez une clé Anthropic ou activez un modèle Groq multimodal."),
            "error": "vision_unavailable",
        }

    mime = state.get("attachment_mime") or "image/jpeg"
    demande = state.get("query") or "Décris ce document pour préparer un chiffrage de travaux de sols."
    message = HumanMessage(content=[
        {"type": "text", "text": f"{VISION_PROMPT}\n\nDemande de l'utilisateur : {demande}"},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
    ])
    try:
        response = await llm.ainvoke([message], config=config)
        usage = getattr(response, "usage_metadata", None) or {}
        return {
            "vision_analysis": response.content,
            "llm_response": response.content,
            "model_used": label,
            "tokens_in": usage.get("input_tokens", 0),
            "tokens_out": usage.get("output_tokens", 0),
        }
    except Exception as e:
        logger.warning("Appel vision échoué (%s) : %s", label, e)
        return {
            "vision_analysis": None,
            "llm_response": f"L'analyse visuelle a échoué ({type(e).__name__}). Réessayez ou joignez une image plus nette.",
            "error": "vision_failed",
        }


async def extraction_node(state: AgentState) -> dict:
    """Extraction structurée (JSON) à partir de l'analyse visuelle. Ne jamais inventer."""
    analysis = state.get("vision_analysis")
    if not analysis:
        return {"extracted_data": None}

    llm = get_llm(LLMTier.STANDARD)
    schema = ('{"locaux_zones": [], "revetements_sol": [], "surfaces_m2": {}, '
              '"lineaires_plinthes_ml": {}, "contraintes": [], '
              '"quantites_a_verifier": [], "incertitudes": []}')
    messages = [
        SystemMessage(content=(
            "Tu extrais des données structurées d'une analyse de plan technique BTP "
            "(travaux de sols et revêtements), en vue d'un métré et d'un chiffrage. "
            "Réponds UNIQUEMENT par un objet JSON valide, sans texte autour. "
            "Ne jamais inventer : mets null, [] ou \"non lisible\" pour toute donnée absente.")),
        HumanMessage(content=f"Analyse :\n{analysis}\n\nProduis ce JSON : {schema}"),
    ]
    try:
        response = await llm.ainvoke(messages)
        text = response.content or ""
        match = re.search(r"\{.*\}", text, re.DOTALL)
        data = json.loads(match.group(0)) if match else None
        return {"extracted_data": data}
    except Exception as e:
        logger.warning("Extraction structurée échouée : %s", e)
        return {"extracted_data": None}


async def browser_node(state: AgentState) -> dict:
    """Enrichit le pré-chiffrage avec des prix matériaux actuels (dernier recours)."""
    from browser.tools import web_search

    result = await web_search(
        query=state.get("query", ""),
        user_id=state.get("user_id", ""),
        agent_id="agent2",
        max_results=3,
    )
    existing = list(state.get("raw_chunks") or [])
    if result["success"]:
        existing.append(
            "[SOURCE WEB : prix / données externes, à mentionner et à valider]\n" + result["content"]
        )
    return {
        "raw_chunks": existing,
        "browser_used": True,
        "browser_sources": result.get("sources", []),
        "browser_content": result.get("content"),
        "browser_was_filtered": result.get("was_filtered", False),
    }


async def similar_projects_node(state: AgentState) -> dict:
    """Recherche chantiers/devis similaires via RAG vectoriel."""
    from vectorstore.rag import retrieve_as_context

    contexts = await retrieve_as_context(
        query=state.get("query", "") or (state.get("vision_analysis") or "")[:400],
        user_role=state.get("user_role", "bureau_etudes"),
        source_types=["chantier", "devis", "appel_offre", "cctp", "dpgf"],
        top_k=5,
    )
    existing = list(state.get("raw_chunks") or [])
    existing.extend(contexts)
    return {"raw_chunks": existing}


async def prechiffrage_node(state: AgentState) -> dict:
    """Assemble une synthèse + prépare le pré-chiffrage — TOUJOURS validé par un humain."""
    analysis = state.get("vision_analysis")
    extracted = state.get("extracted_data")

    parts = []
    if analysis:
        parts.append(analysis)
    if extracted:
        parts.append("Éléments extraits (à valider) :\n"
                     + json.dumps(extracted, ensure_ascii=False, indent=2))
    summary = "\n\n".join(parts) if parts else (
        state.get("llm_response") or "Aucune analyse disponible pour ce document."
    )

    # L'ANALYSE SE LIT, ELLE NE S'APPROUVE PAS.
    #
    # Ce nœud posait `requires_validation=True` sur TOUT ce qu'il rendait — y
    # compris une simple lecture de plan. L'écran affichait alors « une action
    # attend votre accord », et la personne ne voyait rien de l'analyse avant
    # d'avoir cliqué ; or approuver ne déclenchait rien : aucun chemin ne
    # consomme une validation « prechiffrage ». C'était un accord demandé pour
    # le droit de LIRE — relevé au banc de recette (socle commun).
    #
    # L'agent « ne doit pas valider seul un chiffrage ; il prépare les
    # éléments, la décision finale reste humaine ». Ce qui est garanti ici :
    # rien n'est engagé, rien n'est envoyé, rien n'est créé — l'agent n'en a
    # pas le moyen — et le texte le DIT. Le jour où une approbation aura un
    # effet (créer le devis dans l'outil métier), la porte se posera devant
    # CET effet, pas devant la lecture.
    summary += ("\n\n_Pré-chiffrage indicatif : estimations préparées par l'IA, à "
                "vérifier et valider par un humain avant tout usage commercial. "
                "Rien n'a été envoyé ni engagé._")

    return {
        "final_response": summary,
        "requires_validation": False,
        "validation_reason": None,
        "validation_payload": None,
    }


# ── Edges conditionnels ───────────────────────────────────────────────

def should_use_browser(state: AgentState) -> str:
    """Browser = dernier recours : uniquement si le RAG interne est vide."""
    from config import settings

    if state.get("browser_used"):
        return "similar_projects"
    if not settings.browser_enabled:
        return "similar_projects"
    no_internal = len(state.get("raw_chunks") or []) == 0
    return "browser" if no_internal else "similar_projects"


# ── Graph ─────────────────────────────────────────────────────────────

def build_agent2_graph():
    graph = StateGraph(AgentState)

    graph.add_node("preprocess", preprocess_attachment_node)
    graph.add_node("vision", vision_node)
    graph.add_node("extraction", extraction_node)
    graph.add_node("browser", browser_node)
    graph.add_node("similar_projects", similar_projects_node)
    graph.add_node("prechiffrage", prechiffrage_node)

    graph.set_entry_point("preprocess")
    graph.add_edge("preprocess", "vision")
    graph.add_edge("vision", "extraction")
    graph.add_conditional_edges(
        "extraction",
        should_use_browser,
        {"browser": "browser", "similar_projects": "similar_projects"},
    )
    graph.add_edge("browser", "similar_projects")
    graph.add_edge("similar_projects", "prechiffrage")
    graph.add_edge("prechiffrage", END)

    return graph.compile()


agent2_graph = build_agent2_graph()
