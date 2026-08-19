"""
LA MÉMOIRE D'UNE CONVERSATION, À TROIS ÉTAGES.

Ce que le modèle recevait d'une conversation tenait dans UNE FENÊTRE : les huit
derniers messages, quatre mille caractères au plus (`compact_messages`). Une
réponse un peu longue — un devis, une liste de mails — mangeait le budget à
elle seule, et au-delà de quatre échanges tout était oublié. Relevé par
l'utilisateur, mot pour mot : « si j'en parlais sans le réexpliquer dans le
message d'après, l'IA comprenait pas ». C'était une fenêtre, pas une mémoire.

Trois étages, du plus précis au plus lointain, pour un coût borné :

  1. LA FENÊTRE RÉCENTE, verbatim et large. Les derniers échanges, tels quels,
     avec un budget quatre fois plus grand. Un message trop long est TAILLÉ
     (tête et queue gardées, milieu signalé) plutôt que jeté : on perd du
     détail, jamais un échange. C'est l'optimisation de jetons — on ne paie
     pas deux fois une réponse déjà rendue à l'écran, on en garde l'essentiel.

  2. LE RÉSUMÉ GLISSANT de ce qui est sorti de la fenêtre. Quand un échange
     tombe hors de la fenêtre, il est FONDU dans un résumé compact : faits,
     chiffres, noms (masqués), décisions, demandes en suspens. Mis à jour
     seulement à ce moment-là — pas à chaque tour — par le palier léger. Le
     résumé vit dans l'état du fil, donc dans le checkpoint : il survit aux
     redéploiements comme le reste.

  3. LE RAPPEL VECTORIEL des échanges anciens. Chaque échange clos est
     vectorisé (pgvector, déjà en place pour les documents) dans
     `conversation_memoire`. À chaque tour, les trois échanges anciens les plus
     proches de la question du moment sont rappelés, verbatim mais taillés.
     C'est ce qui répond à « tu te souviens du devis dont on a parlé tout à
     l'heure ? » trente échanges plus loin : le résumé en a gardé une ligne,
     le rappel en rend le contenu.

CE QUI NE CHANGE PAS : tout ce qui transite ici est du texte MASQUÉ. Les
messages du fil le sont déjà ; le résumé est écrit à partir d'eux et garde
leurs jetons ; la table porte ce même texte. La carte d'entités du fil étant
cumulative, les jetons anciens se réhydratent comme les autres, dans les
mêmes bornes (ceux réellement envoyés au modèle ce tour-ci).

CE QUI NE LÈVE JAMAIS : chaque étage rend ce qu'il peut. Base injoignable,
embeddings indisponibles, modèle léger en panne — la fenêtre récente, elle,
est toujours là, et un tour ne tombe pas parce que sa mémoire longue a
toussé.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from config import settings

logger = logging.getLogger("duret.memoire_conversation")

# ── Réglages ────────────────────────────────────────────────────────────
# Des défauts dans le code, surchargeables par `settings` quand le réglage
# existe : le module reste utilisable tel quel hors application (tests).
def _reglage(nom: str, defaut: Any) -> Any:
    return getattr(settings, nom, defaut)


def _tailler(texte: str, max_chars: int) -> str:
    """Garde la tête et la queue d'un texte trop long, et le dit."""
    texte = str(texte or "")
    if len(texte) <= max_chars:
        return texte
    tete = int(max_chars * 0.7)
    queue = max_chars - tete
    omis = len(texte) - tete - queue
    return (texte[:tete].rstrip() + f"\n[… {omis} caractères omis — réponse déjà rendue à l'écran …]\n"
            + texte[-queue:].lstrip())


# ── 1. La fenêtre récente ────────────────────────────────────────────────

def fenetre_recente(messages: list) -> tuple[list, int]:
    """Les derniers messages, taillés, recalés sur une paire.

    Rend (fenêtre, nombre de messages ANCIENS laissés dehors). Les messages
    système sont ignorés. La fenêtre commence toujours par un message humain :
    une liste qui s'ouvre sur une réponse est rejetée par certaines API, et
    prive de toute façon le modèle de la question correspondante.
    """
    from langchain_core.messages import AIMessage, HumanMessage

    garder = int(_reglage("optim_history_keep", 16))
    budget = int(_reglage("optim_max_history_chars", 16000))
    par_message = int(_reglage("memoire_message_max_chars", 1400))

    msgs = [m for m in (messages or []) if getattr(m, "type", None) != "system"]
    if not msgs:
        return [], 0

    tail = msgs[-garder:] if garder > 0 else []
    out, used = [], 0
    for m in reversed(tail):
        contenu = _tailler(getattr(m, "content", "") or "", par_message)
        taille = len(contenu)
        if out and used + taille > budget:
            break
        # On reconstruit le message avec le contenu taillé : l'original, lui,
        # reste intact dans le checkpoint.
        cls = HumanMessage if getattr(m, "type", None) == "human" else AIMessage
        out.append(cls(content=contenu))
        used += taille
    out.reverse()
    while out and getattr(out[0], "type", None) != "human":
        out.pop(0)
    # Un échange survit toujours au budget (cf. compact_messages, même leçon).
    if not out and len(tail) >= 2 and getattr(tail[-2], "type", None) == "human":
        out = [HumanMessage(content=_tailler(tail[-2].content, par_message)),
               AIMessage(content=_tailler(tail[-1].content, par_message))]
    anciens = len(msgs) - len(out)
    return out, max(anciens, 0)


# ── 2. Le résumé glissant ────────────────────────────────────────────────

CONSIGNE_RESUME = (
    "Tu tiens la MÉMOIRE d'une conversation entre un collaborateur et un assistant "
    "d'entreprise. On te donne le résumé existant et les échanges qui viennent de "
    "sortir de la fenêtre récente. Écris le NOUVEAU résumé, en français, en "
    "{max_chars} caractères au plus, sous forme de lignes courtes. Garde : les "
    "faits et chiffres donnés (surfaces, montants, dates, références), les noms "
    "de chantiers, clients, documents et fichiers, les décisions prises, les "
    "demandes restées en suspens, les préférences exprimées. Les jetons entre "
    "crochets comme [PER_1] ou [ORG_2] sont des noms masqués : recopie-les tels "
    "quels, ne les invente jamais, ne les traduis jamais. Ne commente pas, "
    "n'ajoute rien qui ne soit pas dans les échanges. Rends uniquement le résumé."
)


async def fondre_dans_le_resume(state: dict, messages: list, anciens: int) -> dict:
    """Fond dans le résumé les messages sortis de la fenêtre depuis la dernière fois.

    Rend les champs d'état à mettre à jour ({} si rien à faire). `anciens` est
    le nombre de messages hors fenêtre ; `resume_couvre` dit combien ont déjà
    été fondus. On ne fond que par PAIRES complètes, et seulement s'il y en a
    au moins une nouvelle : le modèle léger n'est pas appelé à chaque tour.
    """
    deja = int(state.get("resume_couvre") or 0)
    msgs = [m for m in (messages or []) if getattr(m, "type", None) != "system"]
    a_fondre = msgs[deja:anciens]
    if len(a_fondre) < 2:
        return {}
    # Paires complètes seulement : un humain sans sa réponse attendra le tour suivant.
    if len(a_fondre) % 2 == 1:
        a_fondre = a_fondre[:-1]
    if not a_fondre:
        return {}

    max_chars = int(_reglage("memoire_resume_max_chars", 1800))
    ancien = str(state.get("resume_conversation") or "").strip()
    lignes = []
    for m in a_fondre:
        qui = "Collaborateur" if getattr(m, "type", None) == "human" else "Assistant"
        lignes.append(f"{qui} : {_tailler(getattr(m, 'content', '') or '', 1500)}")
    demande = (
        f"Résumé existant :\n{ancien or '(vide)'}\n\n"
        f"Échanges sortis de la fenêtre :\n" + "\n\n".join(lignes)
    )
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from llm.router import LLMTier, get_llm
        llm = get_llm(LLMTier.LIGHT)
        reponse = await llm.ainvoke([
            SystemMessage(content=CONSIGNE_RESUME.format(max_chars=max_chars)),
            HumanMessage(content=demande),
        ])
        neuf = str(getattr(reponse, "content", "") or "").strip()
    except Exception as e:  # noqa: BLE001 — la mémoire longue ne fait pas tomber le tour
        logger.warning("Résumé de conversation non mis à jour (%s)", type(e).__name__)
        return {}
    if not neuf:
        return {}
    # Garde-fou de taille : un modèle bavard ne fait pas gonfler la mémoire.
    if len(neuf) > max_chars * 1.3:
        neuf = neuf[: int(max_chars * 1.3)].rstrip() + " …"
    return {"resume_conversation": neuf, "resume_couvre": deja + len(a_fondre)}


# ── 3. Le rappel vectoriel ───────────────────────────────────────────────

async def memoriser_echange(thread_id: str, user_id: Optional[str], rang: int,
                            question: str, reponse: str) -> None:
    """Vectorise un échange clos et le range dans `conversation_memoire`.

    Texte MASQUÉ uniquement (c'est ce que porte le fil). Ne lève jamais : une
    base ou un service d'embeddings indisponible coûte un rappel de moins, pas
    un tour.
    """
    question = str(question or "").strip()
    reponse = str(reponse or "").strip()
    if not thread_id or not question:
        return
    try:
        from vectorstore.embeddings import embed_query
        from database.connection import get_db
        # La question pèse plus que la réponse dans ce qu'on cherchera plus
        # tard : c'est elle qu'un futur « tu te souviens de … » paraphrase.
        texte = f"{question}\n\n{_tailler(reponse, 1200)}"
        vecteur = await embed_query(texte)
        async with get_db() as conn:
            await conn.execute(
                "INSERT INTO conversation_memoire "
                "(thread_id, user_id, rang, question, reponse, embedding) "
                "VALUES ($1, $2::uuid, $3, $4, $5, $6::vector) "
                "ON CONFLICT (thread_id, rang) DO NOTHING",
                thread_id, user_id or None, rang,
                question[:4000], reponse[:8000],
                ("[" + ",".join(f"{x:.6f}" for x in vecteur) + "]") if vecteur else None)
    except Exception as e:  # noqa: BLE001
        logger.info("Échange non mémorisé (%s)", type(e).__name__)


# Les vectorisations en cours : une tâche asyncio sans référence peut être
# ramassée avant d'avoir fini. On les garde ici le temps qu'elles s'achèvent.
_TACHES_MEMOIRE: set = set()


def memoriser_echange_en_fond(thread_id: str, user_id: Optional[str], rang: int,
                              question: str, reponse: str) -> None:
    """Lance `memoriser_echange` sans attendre. Ne lève jamais."""
    import asyncio
    try:
        tache = asyncio.get_running_loop().create_task(
            memoriser_echange(thread_id, user_id, rang, question, reponse))
    except RuntimeError:  # pas de boucle : on n'insiste pas
        return
    _TACHES_MEMOIRE.add(tache)
    tache.add_done_callback(_TACHES_MEMOIRE.discard)


async def rappeler_echanges(thread_id: str, question: str, avant_rang: int) -> list[dict]:
    """Les échanges anciens du fil les plus proches de la question.

    `avant_rang` : on ne rappelle que ce qui est SORTI de la fenêtre récente
    (rang strictement inférieur), sinon le modèle lirait deux fois la même
    chose. Ne lève jamais ; liste vide si rien ou si indisponible.
    """
    k = int(_reglage("memoire_rappels_k", 3))
    if not thread_id or not question or avant_rang <= 1 or k <= 0:
        return []
    try:
        from vectorstore.embeddings import embed_query
        from database.connection import get_db
        vecteur = await embed_query(question)
        if not vecteur:
            return []
        v = "[" + ",".join(f"{x:.6f}" for x in vecteur) + "]"
        async with get_db() as conn:
            lignes = await conn.fetch(
                "SELECT rang, question, reponse, 1 - (embedding <=> $3::vector) AS score "
                "FROM conversation_memoire "
                "WHERE thread_id = $1 AND rang < $2 AND embedding IS NOT NULL "
                "ORDER BY embedding <=> $3::vector LIMIT $4",
                thread_id, avant_rang, v, k)
        seuil = float(_reglage("memoire_rappels_seuil", 0.45))
        return [dict(l) for l in lignes if float(l["score"] or 0) >= seuil]
    except Exception as e:  # noqa: BLE001
        logger.info("Rappel de conversation indisponible (%s)", type(e).__name__)
        return []


def bloc_memoire(resume: Optional[str], rappels: list[dict]) -> str:
    """Le texte injecté au modèle, ou une chaîne vide s'il n'y a rien à dire."""
    parties = []
    if resume and str(resume).strip():
        parties.append("Résumé de ce qui a été dit plus tôt dans cette conversation :\n"
                       + str(resume).strip())
    if rappels:
        lignes = []
        for r in rappels:
            lignes.append(f"- Échange n°{r.get('rang')} — le collaborateur : "
                          f"{_tailler(r.get('question') or '', 400)}\n  l'assistant : "
                          f"{_tailler(r.get('reponse') or '', 700)}")
        parties.append("Échanges plus anciens de cette conversation, en rapport avec la "
                       "question actuelle :\n" + "\n".join(lignes))
    if not parties:
        return ""
    return ("MÉMOIRE DE LA CONVERSATION (ce que vous avez déjà échangé ; « tout à "
            "l'heure », « ce devis », « le chantier » s'y réfèrent) :\n"
            + "\n\n".join(parties) + "\n\n")
