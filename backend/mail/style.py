"""
Profil de style rédactionnel, appris progressivement par boîte mail.

Principe : plutôt que de réentraîner un modèle, on DISTILLE le style d'une
personne à partir de ses messages ENVOYÉS (formules d'ouverture et de clôture,
tutoiement ou vouvoiement, longueur, niveau de formalisme, signature), puis on
réinjecte cette description au moment de rédiger. Le profil s'affine au fil des
synchronisations : plus il y a de messages, plus il est fidèle.

Deux niveaux réinjectés dans le prompt :
  1. le PROFIL distillé (quelques lignes, coût en tokens négligeable) ;
  2. deux ou trois EXTRAITS réels récents, qui valent mieux qu'une description
     pour reproduire un ton.

Confidentialité : les messages sont déjà anonymisés à l'ingestion. Le profil ne
décrit qu'une manière d'écrire, jamais un contenu ni un interlocuteur.
"""
from __future__ import annotations

import logging
from typing import Optional

from database.connection import get_db
from mail.authorization import normaliser

logger = logging.getLogger("duret.mail.style")

# Convention d'identifiant à l'ingestion : "email_sent:<boite>:<id_message>".
# Elle permet de retrouver les messages d'une personne sans colonne dédiée.
PREFIXE_ENVOYE = "email_sent"

def _reglages() -> tuple[int, int]:
    """(minimum, maximum) d'échantillons — réglables sans toucher au code."""
    try:
        from config import settings
        return (int(getattr(settings, "mail_style_min_samples", 3)),
                int(getattr(settings, "mail_style_samples", 50)))
    except Exception:
        return 3, 50


MIN_ECHANTILLONS, MAX_ECHANTILLONS = _reglages()


def source_id(mailbox: str, message_id: str) -> str:
    """Identifiant d'ingestion d'un message envoyé (stable -> resynchro idempotente)."""
    return f"{PREFIXE_ENVOYE}:{normaliser(mailbox)}:{message_id}"


async def messages_envoyes(mailbox: str, limite: int = MAX_ECHANTILLONS) -> list[str]:
    """Derniers messages envoyés par cette boîte (contenus déjà anonymisés)."""
    boite = normaliser(mailbox)
    async with get_db() as conn:
        rows = await conn.fetch(
            """SELECT content FROM documents
               WHERE source_type = $1 AND source_id LIKE $2
               ORDER BY created_at DESC
               LIMIT $3""",
            PREFIXE_ENVOYE, f"{PREFIXE_ENVOYE}:{boite}:%", limite,
        )
    return [r["content"] for r in rows if r["content"]]


async def profil_enregistre(mailbox: str) -> Optional[dict]:
    boite = normaliser(mailbox)
    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT profil, echantillons, derniere_maj FROM mail_style_profiles WHERE mailbox = $1",
            boite,
        )
    return dict(row) if row else None


async def construire_profil(mailbox: str, force: bool = False) -> dict:
    """(Re)calcule le profil de style d'une boîte à partir de ses envois.

    Ne lève jamais : sans messages ou sans LLM, on renvoie un profil vide et la
    rédaction se fera simplement sans personnalisation.
    """
    boite = normaliser(mailbox)
    echantillons = await messages_envoyes(boite)

    if len(echantillons) < MIN_ECHANTILLONS:
        return {"mailbox": boite, "profil": "", "echantillons": len(echantillons),
                "raison": f"pas assez de messages envoyés ({len(echantillons)}/{MIN_ECHANTILLONS})"}

    existant = await profil_enregistre(boite)
    if existant and not force and existant["echantillons"] >= len(echantillons):
        return {"mailbox": boite, **existant, "raison": "profil déjà à jour"}

    # Budget de contexte plutôt qu'un nombre fixe de messages : on analyse le plus
    # de messages possible sans dépasser la fenêtre des petits modèles (le palier
    # LIGHT tourne parfois sur un 8k). Mieux vaut 30 messages courts que 12 longs.
    BUDGET = 16000
    morceaux, utilises, total = [], 0, 0
    for message in echantillons:
        extrait = message[:800]
        if total + len(extrait) > BUDGET and morceaux:
            break
        morceaux.append(extrait)
        total += len(extrait)
        utilises += 1
    extraits = "\n\n---\n\n".join(morceaux)
    prompt = (
        "Voici des messages écrits par une même personne (contenus anonymisés).\n"
        "Décris SON STYLE d'écriture en 5 à 8 points courts, en français, pour qu'un "
        "assistant puisse rédiger à sa manière.\n"
        "Couvre : formule d'ouverture, formule de clôture, vouvoiement ou tutoiement, "
        "longueur habituelle, niveau de formalisme, tics de langage, structure "
        "(paragraphes ou listes), signature.\n"
        "Ne décris AUCUN contenu, AUCUN client, AUCUN chiffre : uniquement la manière d'écrire.\n\n"
        f"{extraits}"
    )

    try:
        from llm.router import get_llm, LLMTier
        from langchain_core.messages import HumanMessage
        reponse = await get_llm(LLMTier.LIGHT).ainvoke([HumanMessage(content=prompt)])
        texte = str(reponse.content).strip()[:2000]
    except Exception as e:  # noqa: BLE001 - l'absence de profil ne doit rien bloquer
        logger.warning("Profil de style indisponible pour %s : %s", boite, e)
        return {"mailbox": boite, "profil": "", "echantillons": len(echantillons),
                "raison": "modèle indisponible"}

    # On enregistre le nombre RÉELLEMENT analysé, pas le nombre récupéré : c'est
    # lui qui dit à quel point le profil est représentatif.
    echantillons = echantillons[:utilises]

    async with get_db() as conn:
        await conn.execute(
            """INSERT INTO mail_style_profiles (mailbox, profil, echantillons, derniere_maj)
               VALUES ($1, $2, $3, NOW())
               ON CONFLICT (mailbox) DO UPDATE
                   SET profil = EXCLUDED.profil,
                       echantillons = EXCLUDED.echantillons,
                       derniere_maj = NOW()""",
            boite, texte, len(echantillons),
        )
    logger.info("Profil de style mis à jour pour %s (%d messages)", boite, len(echantillons))
    return {"mailbox": boite, "profil": texte, "echantillons": len(echantillons)}


async def consigne_style(mailbox: str) -> str:
    """Bloc à insérer dans le prompt de rédaction. Vide si rien n'est connu."""
    boite = normaliser(mailbox)
    enregistre = await profil_enregistre(boite)
    profil = (enregistre or {}).get("profil") or ""

    exemples = await messages_envoyes(boite, limite=3)
    if not profil and not exemples:
        return ""

    morceaux = ["STYLE DE L'EXPÉDITEUR : reproduis-le fidèlement."]
    if profil:
        morceaux.append(profil)
    if exemples:
        morceaux.append("Exemples de ses messages :\n" +
                        "\n\n---\n\n".join(e[:600] for e in exemples))
    return "\n\n".join(morceaux)
