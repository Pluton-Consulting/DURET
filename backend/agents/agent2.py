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
from llm.router import get_llm, LLMTier

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

# COMBIEN DE PAGES D'UN PDF PARTENT À LA VISION.
#
# Une seule, jusqu'ici : `load_page(0)`. Or un dossier de plans, c'est un plan
# de masse, des coupes, des façades, parfois un descriptif — et l'assistant
# n'en voyait que la première feuille tout en répondant comme s'il avait tout
# lu. Rien ne signalait le reste : ni l'utilisateur ni le modèle ne pouvaient
# le savoir.
#
# Cinq est un compromis assumé : chaque page est une image de plus dans la
# requête, donc un coût et une latence de plus, et les modèles de vision se
# dégradent quand on les noie. Au-delà, on prend les cinq premières et ON LE
# DIT — une troncature annoncée est une information ; silencieuse, c'est une
# erreur.
MAX_PAGES_PDF = 5


# ── Nœuds ────────────────────────────────────────────────────────────

async def preprocess_attachment_node(state: AgentState) -> dict:
    """Prétraitement : PDF → images (jusqu'à MAX_PAGES_PDF pages), et
    suppression EXIF/GPS des photos (Pillow)."""
    b64 = state.get("attachment_b64")
    mime = (state.get("attachment_mime") or "").lower()
    if not b64:
        return {}

    try:
        raw = base64.b64decode(b64)
    except Exception:
        return {"error": "attachment_base64_invalide"}

    # PDF → rendre ses pages en images (PyMuPDF, import optionnel).
    pages_brutes, pages_totales = [], 0
    if "pdf" in mime:
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(stream=raw, filetype="pdf")
            pages_totales = doc.page_count
            for numero in range(min(pages_totales, MAX_PAGES_PDF)):
                pix = doc.load_page(numero).get_pixmap(dpi=150)
                pages_brutes.append(pix.tobytes("png"))
            if not pages_brutes:
                return {"error": "pdf_sans_page"}
            raw = pages_brutes[0]
            mime = "image/png"
        except ImportError:
            return {"error": "pdf_non_supporte_installer_pymupdf",
                    "llm_response": "Analyse PDF indisponible (dépendance PyMuPDF absente)."}
        except Exception as e:
            return {"error": f"pdf_illisible_{type(e).__name__}"}

    # Image → ré-encodage Pillow (retire EXIF/GPS) + downscale.
    def _nettoyer(donnees: bytes) -> bytes:
        from PIL import Image
        img = Image.open(io.BytesIO(donnees)).convert("RGB")
        if img.width > _MAX_IMG_WIDTH:
            ratio = _MAX_IMG_WIDTH / img.width
            img = img.resize((_MAX_IMG_WIDTH, int(img.height * ratio)))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=80)  # nouvel encodage = sans métadonnées EXIF
        return out.getvalue()

    try:
        octets = _nettoyer(raw)
        # Les pages SUIVANTES du PDF, nettoyées et redimensionnées comme la
        # première. Une page illisible n'interrompt pas l'analyse des autres :
        # mieux vaut quatre pages sur cinq qu'un échec entier.
        pages = [octets]
        for suivante in pages_brutes[1:]:
            try:
                pages.append(_nettoyer(suivante))
            except Exception as e:  # noqa: BLE001
                logger.info("Page de PDF illisible, ignorée : %s", e)
        return {
            "attachment_b64": base64.b64encode(octets).decode(),
            "attachment_mime": "image/jpeg",
            # Toutes les pages retenues, la première comprise : c'est ce que la
            # vision recevra. Une seule page ⇒ liste d'un élément, aucun cas
            # particulier plus loin.
            "attachment_pages": [base64.b64encode(p).decode() for p in pages],
            "pages_totales": pages_totales or None,
            "pages_ignorees": (max(0, pages_totales - len(pages))
                               if pages_totales else 0) or None,
        }
    except Exception as e:
        return {"error": f"image_illisible_{type(e).__name__}"}


async def vision_node(state: AgentState, config=None) -> dict:
    """Analyse visuelle multimodale. Dégradation propre si aucun modèle vision configuré."""
    b64 = state.get("attachment_b64")
    if not b64:
        return {"vision_analysis": None}

    from llm.router import get_vision_candidates
    candidats = get_vision_candidates()
    if not candidats:
        return {
            "vision_analysis": None,
            "llm_response": ("Analyse visuelle indisponible : aucun modèle vision configuré. "
                             "Ajoutez une clé Google, Anthropic ou un modèle Groq multimodal."),
            "error": "vision_unavailable",
        }

    mime = state.get("attachment_mime") or "image/jpeg"
    demande = state.get("query") or "Décris ce document pour préparer un chiffrage de travaux de sols."

    # TOUTES LES PAGES RETENUES, pas seulement la première. Un dossier de plans
    # tient rarement sur une feuille, et l'assistant répondait sur la seule
    # page 1 comme s'il avait tout vu. On dit au modèle combien il en reçoit et
    # combien ont été laissées de côté : sans cela, il conclurait de la
    # dernière page qu'il a fait le tour du dossier.
    pages = state.get("attachment_pages") or [b64]
    total = state.get("pages_totales") or 0
    ignorees = state.get("pages_ignorees") or 0
    entete = f"{VISION_PROMPT}\n\nDemande de l'utilisateur : {demande}"
    if len(pages) > 1:
        entete += (f"\n\nCe document comporte {total or len(pages)} page(s) ; "
                   f"les {len(pages)} premières te sont montrées, dans l'ordre. "
                   "Analyse-les ENSEMBLE : un plan de masse, ses coupes et ses "
                   "façades décrivent le même projet. Dis à quelle page se "
                   "trouve chaque élément que tu relèves.")
    if ignorees:
        entete += (f"\n\nATTENTION : {ignorees} page(s) n'ont PAS été analysées. "
                   "Signale-le dans ta réponse, et ne conclus rien sur ce que tu "
                   "n'as pas vu.")
    message = HumanMessage(content=[{"type": "text", "text": entete}] + [
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{page}"}}
        for page in pages
    ])
    # LES CANDIDATS SE SUCCÈDENT, comme dans la cascade texte. Un seul essai
    # laissait l'agent aveugle dès que le premier modèle répondait 404 — relevé
    # au banc de recette (« L'analyse visuelle a échoué (NotFoundError) »).
    derniere = None
    for llm, label in candidats:
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
        except Exception as e:  # noqa: BLE001 — on passe au suivant
            derniere = e
            logger.warning("Appel vision échoué (%s) : %s — candidat suivant", label, e)
    return {
        "vision_analysis": None,
        "llm_response": (f"L'analyse visuelle a échoué ({type(derniere).__name__}). "
                         "Réessayez ou joignez une image plus nette."),
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

    # LE TRAVAIL DE RECHERCHE ÉTAIT FAIT, PUIS JETÉ.
    #
    # `similar_projects_node` interroge la mémoire pour trouver les chantiers et
    # devis qui ressemblent à ce plan, et `browser_node` va chercher des prix
    # publics quand la mémoire est vide. Tous deux remplissent `raw_chunks` — que
    # ce nœud-ci, le seul qui écrive la réponse, ne lisait pas. Deux appels
    # payés, deux résultats perdus, et une trame de pré-chiffrage sans le seul
    # élément qui lui donnait de la valeur : « on a déjà fait ça, voilà où ».
    #
    # Les extraits sont bornés et RECOPIÉS TELS QUELS : rien n'est résumé ici,
    # aucun modèle ne repasse derrière ce nœud. Ce qui vient du web porte déjà sa
    # marque depuis `browser_node` ([SOURCE WEB]), elle est conservée.
    comparables = [c for c in (state.get("raw_chunks") or []) if str(c).strip()][:5]
    if comparables:
        parts.append(
            "Chantiers et devis comparables trouvés dans la mémoire de "
            "l'entreprise (à recouper, ce ne sont pas des références de prix) :\n"
            + "\n\n".join(f"- {str(c).strip()[:600]}" for c in comparables))

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
