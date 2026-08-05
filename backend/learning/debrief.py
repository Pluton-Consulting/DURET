"""
Débriefing d'une conversation — apprentissage déclenché à la main.

L'assistant relit un fil, en extrait ce qui mérite d'être RETENU, et le range
là où ça servira réellement :

  * `connaissance` -> mémoire d'entreprise (base vectorielle). C'est un FAIT
    durable, énoncé pendant l'échange, que le RAG pourra ressortir plus tard.
  * `procedure`    -> mémoire d'entreprise également, mais typée à part : c'est
    une manière de faire (« pour un récap chantier, présenter d'abord ... »).
  * `competence`   -> brouillon de skill dans le catalogue, à valider par un
    humain. Réservé à ce qui est réellement AUTOMATISABLE, c'est-à-dire un
    calcul ou une transformation déterministe.

Deux garde-fous structurels :

1. RGPD. Les messages sont stockés en clair en base (c'est ce que l'humain a
   lu). On les MASQUE donc avant de les envoyer au modèle, exactement comme
   dans le chat, puis on RÉHYDRATE les propositions avant de les écrire en
   mémoire : la mémoire doit contenir les vrais noms, sinon elle est inutile,
   mais le modèle externe, lui, ne voit jamais de PII.

2. Rien n'est écrit sans accord. L'analyse ne fait que PROPOSER et renvoie un
   jeton ; l'écriture n'a lieu qu'au second appel, sur les seules propositions
   cochées. Même patron que l'import de fichiers.
"""
from __future__ import annotations

import json
import logging
import re
import uuid

logger = logging.getLogger("duret.learning.debrief")

# Au-delà, on ne débriefe que la fin du fil : le début d'une longue conversation
# a déjà été résumé par ses propres tours, et le coût grimpe pour peu de valeur.
MAX_MESSAGES = 30
MAX_CARACTERES_PAR_MESSAGE = 1500

# Niveaux d'accès acceptés pour une connaissance retenue (cf. ingestion).
NIVEAUX_ACCES = {"all", "commercial_plus", "bureau_etudes_plus", "direction_only", "admin_only"}

_RE_NOM_SKILL = re.compile(r"^[a-z][a-z0-9_]{2,49}$")


class PasDeConversation(Exception):
    """Aucun fil exploitable pour cet utilisateur."""


async def charger_conversation(user_id: str, role: str,
                               thread_id: str | None = None) -> dict:
    """Charge le dernier fil de CET utilisateur (ou celui demandé).

    Passe par la connexion RLS : un utilisateur ne débriefe que ses propres
    conversations, y compris s'il devine l'identifiant d'un autre fil.
    """
    from database.connection import get_rls_db

    async with get_rls_db(user_id, role) as conn:
        if thread_id:
            try:
                cle = uuid.UUID(str(thread_id))
            except (ValueError, AttributeError):
                raise PasDeConversation("Identifiant de conversation invalide.")
            fil = await conn.fetchrow(
                "SELECT id, title, created_at, updated_at FROM threads "
                "WHERE id = $1 AND user_id = $2::uuid",
                cle, user_id)
        else:
            fil = await conn.fetchrow(
                "SELECT t.id, t.title, t.created_at, t.updated_at FROM threads t "
                "WHERE t.user_id = $1::uuid "
                "  AND EXISTS (SELECT 1 FROM messages m WHERE m.thread_id = t.id) "
                "ORDER BY t.updated_at DESC LIMIT 1",
                user_id)

        if fil is None:
            raise PasDeConversation("Aucune conversation à débriefer pour l'instant.")

        # La question et la réponse d'un même tour sont insérées dans UNE
        # transaction : `created_at` (= NOW()) est identique pour les deux. Sans
        # départage explicite, la réponse pourrait précéder la question et le
        # débrief lirait un dialogue inversé. On force donc user avant assistant.
        lignes = await conn.fetch(
            "SELECT role, content FROM ("
            "  SELECT role, content, created_at FROM messages "
            "  WHERE thread_id = $1 ORDER BY created_at DESC LIMIT $2"
            ") t ORDER BY created_at, "
            "  CASE role WHEN 'system' THEN 0 WHEN 'user' THEN 1 ELSE 2 END",
            fil["id"], MAX_MESSAGES)

    messages = [{"role": r["role"], "content": (r["content"] or "")[:MAX_CARACTERES_PAR_MESSAGE]}
                for r in lignes]
    if not messages:
        raise PasDeConversation("Cette conversation ne contient aucun message.")

    return {
        "thread_id": str(fil["id"]),
        "titre": fil["title"] or "Conversation",
        "date": (fil["updated_at"] or fil["created_at"]).isoformat(),
        "messages": messages,
    }


def _transcription(messages: list[dict]) -> str:
    etiquettes = {"user": "UTILISATEUR", "assistant": "ASSISTANT", "system": "SYSTEME"}
    return "\n\n".join(
        f"{etiquettes.get(m['role'], m['role'].upper())} : {m['content']}" for m in messages)


INVITE = """Tu relis une conversation entre un collaborateur et l'assistant interne de l'entreprise.
Ton rôle : décider ce qui mérite d'être RETENU DURABLEMENT, et rien d'autre.

Retiens uniquement ce qui resservira sur d'AUTRES conversations. Ignore le bavardage, les
salutations, les reformulations, ce que l'assistant a simplement lu dans un document (c'est
déjà en mémoire), et tout ce qui n'est vrai qu'aujourd'hui.

Trois catégories :
- "connaissances" : un FAIT durable sur l'entreprise, énoncé pendant l'échange (un tarif, une
  règle, une préférence client, un fournisseur, une contrainte technique).
- "procedures" : une MANIÈRE DE FAIRE demandée ou corrigée par l'humain (« présente toujours
  ainsi », « pour ce type de demande, commence par... »).
- "competences" : une tâche AUTOMATISABLE, c'est-à-dire un calcul ou une transformation
  déterministe qui reviendra (« calcule le métré à partir des dimensions »). N'en propose que
  si c'est vraiment du calcul reproductible ; sinon, laisse la liste vide.

Il est parfaitement normal de ne rien retenir : dans ce cas, renvoie des listes vides.
N'INVENTE rien. Chaque élément doit s'appuyer sur ce qui est écrit dans la conversation.
Les balises masquées ([PER_1], [MONTANT_2]...) doivent être conservées TELLES QUELLES.

Réponds par un objet JSON seul, sans commentaire :
{"connaissances": [{"titre": "...", "contenu": "...", "acces": "all|commercial_plus|bureau_etudes_plus|direction_only"}],
 "procedures":    [{"titre": "...", "contenu": "..."}],
 "competences":   [{"nom": "nom_en_snake_case", "description": "...", "entrees": "paramètres attendus"}]}

CONVERSATION :
"""


def _extraire_json(brut: str) -> dict:
    trouve = re.search(r"\{.*\}", brut or "", re.S)
    if not trouve:
        return {}
    try:
        data = json.loads(trouve.group(0))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _nettoyer(data: dict) -> dict:
    """Ne garde que des propositions exploitables, et borne leur taille."""
    connaissances, procedures, competences = [], [], []

    for item in (data.get("connaissances") or [])[:10]:
        if not isinstance(item, dict):
            continue
        contenu = str(item.get("contenu") or "").strip()
        if len(contenu) < 15:      # une phrase creuse n'a rien à faire en mémoire
            continue
        acces = str(item.get("acces") or "all").strip()
        connaissances.append({
            "titre": (str(item.get("titre") or "").strip() or contenu[:60])[:120],
            "contenu": contenu[:2000],
            "acces": acces if acces in NIVEAUX_ACCES else "all",
        })

    for item in (data.get("procedures") or [])[:10]:
        if not isinstance(item, dict):
            continue
        contenu = str(item.get("contenu") or "").strip()
        if len(contenu) < 15:
            continue
        procedures.append({
            "titre": (str(item.get("titre") or "").strip() or contenu[:60])[:120],
            "contenu": contenu[:2000],
        })

    for item in (data.get("competences") or [])[:5]:
        if not isinstance(item, dict):
            continue
        nom = str(item.get("nom") or "").strip().lower().replace(" ", "_")
        description = str(item.get("description") or "").strip()
        # Un nom hors convention finirait en skill inexécutable : on l'écarte ici.
        if not _RE_NOM_SKILL.match(nom) or len(description) < 15:
            continue
        competences.append({
            "nom": nom,
            "description": description[:500],
            "entrees": str(item.get("entrees") or "").strip()[:300],
        })

    return {"connaissances": connaissances, "procedures": procedures,
            "competences": competences}


async def analyser(conversation: dict) -> dict:
    """Fait relire la conversation par le modèle. N'ÉCRIT RIEN.

    Retourne `{"propositions": {...}, "entity_map": {...}}` : la carte permet de
    réhydrater les propositions au moment de l'enregistrement.
    """
    import asyncio

    from langchain_core.messages import HumanMessage
    from llm.router import get_llm, LLMTier
    from security.anonymizer import anonymizer
    from config import settings

    # Fail-closed RGPD, comme dans le chat : sans NER opérationnel, la
    # conversation partirait en clair vers un modèle externe.
    if settings.block_external_llm_without_ner and not anonymizer.spacy_available:
        raise RuntimeError("Anonymisation indisponible : analyse refusée.")

    textes = [m["content"] for m in conversation["messages"]]
    masques, carte = await asyncio.to_thread(anonymizer.anonymize_chunks, textes, {})
    masquee = [{"role": m["role"], "content": c}
               for m, c in zip(conversation["messages"], masques)]

    llm = get_llm(LLMTier.STANDARD)
    reponse = await llm.ainvoke([HumanMessage(content=INVITE + _transcription(masquee))])
    propositions = _nettoyer(_extraire_json(str(reponse.content)))

    # Le modèle réellement retenu par la cascade se lit sur CETTE instance :
    # redemander un LLM au routeur pourrait en rendre un autre.
    return {"propositions": propositions, "entity_map": carte,
            "model_used": getattr(llm, "last_model_used", None)}


async def enregistrer(propositions: dict, entity_map: dict, prefixe_source: str,
                      acces_force: str | None = None) -> dict:
    """Écrit en mémoire les connaissances et procédures retenues.

    Partagé par le débrief d'une conversation et par la campagne d'enrichissement
    du corpus de mails : c'est le même geste, avec la même règle de
    réhydratation.

    `acces_force` verrouille le niveau d'accès de tout ce qui est écrit. La
    campagne s'en sert : une connaissance tirée de plusieurs boîtes mail n'est
    plus rattachable à l'une d'elles, donc plus cloisonnable — elle est rangée
    au niveau le plus restrictif plutôt que d'être exposée à tout le monde.
    """
    import time as _time

    from ingestion.pipeline import ingest_document
    from security.anonymizer import anonymizer

    carte = entity_map or {}

    def _vrai(texte: str) -> str:
        # Les propositions viennent d'un modèle nourri au texte MASQUÉ : on remet
        # les vraies valeurs, sinon la mémoire ne contiendrait que des balises.
        return anonymizer.rehydrate(texte or "", carte)

    chunks = memorise = 0
    echecs: list[str] = []
    horodatage = int(_time.time())

    for cle, source_type in (("connaissances", "apprentissage"), ("procedures", "procedure")):
        for i, item in enumerate(propositions.get(cle) or []):
            titre = _vrai(item.get("titre") or "")
            texte = f"{titre}\n\n{_vrai(item.get('contenu') or '')}"
            try:
                chunks += await ingest_document(
                    text=texte, source_type=source_type,
                    source_id=f"{source_type}:{prefixe_source}:{horodatage}:{i}",
                    source_filename=titre[:200],
                    access_level=acces_force or item.get("acces", "all"))
                memorise += 1
            except Exception as e:  # noqa: BLE001 - un élément fautif n'annule pas le reste
                logger.warning("Mémorisation de « %s » échouée : %s", titre[:60], e)
                echecs.append(titre[:80])

    return {"memorise": memorise, "chunks": chunks, "echecs": echecs}


async def generer_code_skill(competence: dict) -> str:
    """Écrit le `run(data)` d'une compétence retenue.

    Appelé SEULEMENT à l'enregistrement, et seulement pour les compétences
    cochées : générer du code que personne ne garde coûte pour rien.
    Le skill est créé en `draft` — donc non exécutable — jusqu'à relecture
    humaine du code dans l'onglet Skills.
    """
    from langchain_core.messages import HumanMessage
    from llm.router import get_llm, LLMTier

    invite = (
        "Écris une fonction Python autonome pour un skill interne.\n"
        "Contraintes STRICTES : une seule fonction `def run(data: dict) -> dict`, "
        "aucun import hors bibliothèque standard, aucun accès réseau, aucun accès "
        "fichier, aucune variable globale. Elle valide ses entrées et lève "
        "ValueError si elles manquent. Réponds par le code seul, sans balise "
        "Markdown et sans explication.\n\n"
        f"Nom : {competence['nom']}\n"
        f"But : {competence['description']}\n"
        f"Entrées attendues : {competence.get('entrees') or 'à déduire du but'}"
    )
    reponse = await get_llm(LLMTier.STANDARD).ainvoke([HumanMessage(content=invite)])
    code = str(reponse.content or "").strip()
    # Le modèle encadre souvent son code : on retire la clôture Markdown.
    code = re.sub(r"^```(?:python)?\s*|\s*```$", "", code).strip()
    return code
