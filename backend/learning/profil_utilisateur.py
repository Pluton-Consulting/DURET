"""
LE PROFIL D'UNE PERSONNE — ce qu'elle n'a pas besoin de répéter.

Demande de Noa (01/09) : « fais en sorte que tous les jours à minuit, pour
chaque utilisateur, il relise la conversation complète pour apprendre au max de
l'utilisateur et avoir cette mémoire / contexte propre à chaque utilisateur. Il
doit retenir la façon de parler, mais aussi les détails, la façon de travailler,
les méthodes de travail, les préférences subtiles. »

CE QUE CE MODULE N'EST PAS, et c'est ce qui l'empêche de faire doublon :

  · Ce ne sont pas des CONSIGNES (`learning/consignes.py`, table 021). Une
    consigne est un ORDRE explicite, posé par un humain, retirable un par un —
    « appelle-moi Noa », « pas de tiret cadratin ». Ici rien n'est ordonné :
    c'est OBSERVÉ, et donc toujours faillible.
  · Ce n'est pas le PROFIL DE STYLE des mails (`mail/style.py`) : celui-là
    décrit une BOÎTE et ne sert qu'à rédiger.
  · Ce n'est pas la MÉMOIRE DE CONVERSATION (table 025) : elle rappelle des
    échanges DATÉS, à la demande. Ici on cherche ce qui NE DATE PAS.

TROIS GARDE-FOUS, et ils comptent plus que le mécanisme.

1. RGPD. Les conversations sont en clair en base (c'est ce que l'humain a lu).
   On les MASQUE avant de les envoyer au modèle, et on RÉHYDRATE le profil
   avant de l'écrire : la mémoire doit porter les vrais noms, sinon elle ne
   sert à rien, mais le modèle externe n'en voit jamais aucun. Même patron que
   `learning/debrief.py`.

2. UN PROFIL N'EST PAS UN JOURNAL. Il est PLAFONNÉ et RÉÉCRIT à chaque passe,
   jamais empilé : ce qu'on veut, c'est une page qui se lit d'un coup, pas un
   historique qui gonfle jusqu'à noyer le prompt. Le modèle reçoit l'ancien
   profil ET le nouveau matériau, et rend la version à jour.

3. LE CURSEUR. On ne relit que les conversations TOUCHÉES depuis la dernière
   passe. Relire tout chaque nuit coûterait davantage à chaque jour qui passe
   pour n'apprendre presque rien de neuf — et une conversation déjà lue a déjà
   donné ce qu'elle avait. La première passe, elle, remonte au début.

CE QU'ON NE RETIENT PAS, et c'est explicite dans la consigne au modèle : les
faits ponctuels (« le devis Durand fait 4 200 € »), qui appartiennent à la
mémoire d'entreprise et qui PÉRIMENT. Un profil qui retient des chiffres finit
par les réciter faux.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("duret.learning.profil")

# Un profil se lit d'un coup, sinon il ne sert à rien : il est injecté à CHAQUE
# tour, et ce qui est long se dilue. Deux mille caractères, soit une bonne page.
MAX_PROFIL = 2000
# Le matériau d'une passe. Au-delà, on prend les conversations les plus
# récentes : ce sont elles qui décrivent le mieux la façon de travailler
# d'aujourd'hui.
MAX_MATIERE = 30000
MAX_CONVERSATIONS = 12
# Une passe par nuit et par personne, mais jamais toutes en même temps : le
# plafond d'appels simultanés (llm/concurrence.py) s'applique, et une passe de
# fond ne doit pas prendre les créneaux du chat.
MAX_COMPTES_PAR_PASSE = 50

_CACHE: dict = {}
_DUREE_CACHE_S = 300

CONSIGNE = """Tu observes comment une personne travaille avec son assistant, pour \
que l'assistant n'ait plus besoin de le lui faire répéter.

Voici le portrait actuel (peut être vide) :
---
{profil}
---

Voici de nouveaux échanges entre elle (« Personne ») et l'assistant :
---
{matiere}
---

Rends le portrait MIS À JOUR, en français, {maxi} caractères au maximum.

CE QUE TU RETIENS :
- sa façon de parler : ton, longueur, tutoiement ou vouvoiement, formules ;
- sa façon de travailler : dans quel ordre elle fait les choses, ce qu'elle
  vérifie, ce qu'elle délègue, à quel moment de la journée elle demande quoi ;
- ses préférences, même discrètes : la forme des réponses qu'elle garde, celles
  qu'elle fait refaire, les mots qu'elle corrige, ce qui l'agace ;
- ce qu'elle n'explique jamais parce que c'est évident pour elle : son métier,
  ses interlocuteurs habituels, ses raccourcis de langage.

CE QUE TU NE RETIENS PAS :
- les faits ponctuels : un montant, une date, un nom de dossier. Ils périment,
  et un portrait qui les récite les récitera faux.
- ce qui n'est arrivé qu'une fois : une habitude se répète.
- ce que tu ne fais que supposer. Dans le doute, tu n'écris rien : un portrait
  court et juste vaut mieux qu'un portrait complet et inventé.

Écris des phrases courtes, à la troisième personne. Ne commente pas ta tâche,
ne mets ni titre ni préambule : rends le portrait, et rien d'autre."""


async def enregistre(user_id: str) -> Optional[dict]:
    """Le profil d'une personne, ou None. Cache court : lu à chaque tour."""
    import time

    cle = str(user_id or "")
    if not cle:
        return None
    fige = _CACHE.get(cle)
    if fige and time.monotonic() - fige[0] < _DUREE_CACHE_S:
        return fige[1]
    try:
        from database.connection import get_db
        async with get_db() as conn:
            ligne = await conn.fetchrow(
                "SELECT profil, conversations, messages, derniere_maj, actif "
                "FROM profils_utilisateur WHERE user_id = $1::uuid", cle)
    except Exception as e:  # noqa: BLE001 — un profil absent n'empêche rien
        logger.debug("Profil non lu (%s)", type(e).__name__)
        return None
    profil = dict(ligne) if ligne else None
    _CACHE[cle] = (time.monotonic(), profil)
    return profil


def oublier_cache(user_id: str = "") -> None:
    """Après une passe ou un effacement : sinon l'ancien tient cinq minutes."""
    if user_id:
        _CACHE.pop(str(user_id), None)
    else:
        _CACHE.clear()


async def texte_injecte(user_id: Optional[str]) -> str:
    """Le bloc à coller dans le prompt. Vide quand il n'y a rien à dire.

    Appelé à CHAQUE tour : bon marché, et ne lève jamais. Un portrait illisible
    ne doit pas empêcher de répondre.

    LE CADRE COMPTE AUTANT QUE LE CONTENU : le modèle doit savoir qu'il lit une
    OBSERVATION, pas une consigne. Sans cette précision, un portrait qui dit
    « elle demande souvent le point sur les mails » devient un ordre de faire le
    point sur les mails, et l'assistant répond à côté de la question posée.
    """
    if not user_id:
        return ""
    profil = await enregistre(str(user_id))
    if not profil or not profil.get("actif") or not (profil.get("profil") or "").strip():
        return ""
    return (
        "\n\nCE QUE TU SAIS DE LA PERSONNE QUI TE PARLE (observé au fil des "
        "échanges, jamais demandé par elle). C'est un portrait, pas une "
        "consigne : il t'aide à répondre dans SA forme et à ne pas lui faire "
        "répéter ce qu'elle a déjà dit. Il ne te demande RIEN, et il ne "
        "remplace jamais ce qu'elle écrit maintenant.\n"
        + (profil["profil"] or "").strip()[:MAX_PROFIL])


async def _matiere(user_id: str, depuis) -> tuple:
    """(transcription, nombre de conversations, nombre de messages).

    On lit des CONVERSATIONS ENTIÈRES, pas des messages isolés : une habitude
    se voit dans un enchaînement — ce qu'elle demande, ce qu'elle fait refaire,
    par quoi elle commence — et un message seul n'en dit rien.
    """
    from database.connection import get_db

    async with get_db() as conn:
        fils = await conn.fetch(
            "SELECT id, title FROM threads "
            "WHERE user_id = $1::uuid AND ($2::timestamptz IS NULL OR updated_at > $2) "
            "  AND EXISTS (SELECT 1 FROM messages m WHERE m.thread_id = threads.id) "
            "ORDER BY updated_at DESC LIMIT $3",
            str(user_id), depuis, MAX_CONVERSATIONS)
        if not fils:
            return "", 0, 0
        morceaux, total, nb_messages = [], 0, 0
        for fil in fils:
            lignes = await conn.fetch(
                "SELECT role, content FROM messages WHERE thread_id = $1 "
                "ORDER BY created_at LIMIT 200", fil["id"])
            if not lignes:
                continue
            texte = [f"### {fil['title'] or 'Conversation'}"]
            for m in lignes:
                qui = "Personne" if m["role"] == "user" else "Assistant"
                contenu = (m["content"] or "").strip()
                if not contenu:
                    continue
                # Une réponse très longue n'apprend rien de plus sur la
                # personne que son début : c'est ELLE qu'on observe.
                texte.append(f"{qui} : {contenu[:1200]}")
                nb_messages += 1
            bloc = "\n".join(texte)
            if total + len(bloc) > MAX_MATIERE:
                break
            morceaux.append(bloc)
            total += len(bloc)
    return "\n\n".join(morceaux), len(morceaux), nb_messages


async def construire(user_id: str) -> dict:
    """Relit ce qui est nouveau et met le portrait à jour. Ne lève jamais.

    Rend toujours un état lisible : `{ecrit, raison, conversations, messages}`.
    Une passe qui n'écrit rien doit DIRE pourquoi — sans quoi la carte de
    l'écran afficherait « à jour » sur un profil que personne n'a jamais pu
    construire.
    """
    from datetime import datetime, timezone

    from database.connection import get_db

    user_id = str(user_id)
    try:
        actuel = await enregistre(user_id) or {}
        if actuel and not actuel.get("actif", True):
            return {"ecrit": False, "raison": "profil désactivé par la personne"}

        async with get_db() as conn:
            curseur = await conn.fetchval(
                "SELECT jusqu_a FROM profils_utilisateur WHERE user_id = $1::uuid",
                user_id)
        matiere, nb_fils, nb_messages = await _matiere(user_id, curseur)
        if not matiere.strip():
            return {"ecrit": False, "raison": "aucun échange nouveau",
                    "conversations": 0, "messages": 0}

        # ── RGPD : le modèle ne voit jamais un nom ──────────────────────
        from security.anonymizer import anonymizer
        import asyncio
        try:
            masques, carte = await asyncio.to_thread(
                anonymizer.anonymize_chunks,
                [matiere, (actuel.get("profil") or "")], {})
            matiere_masquee, profil_masque = masques[0], masques[1]
        except Exception as e:  # noqa: BLE001
            # Sans masquage, on n'envoie RIEN : mieux vaut un profil qui ne
            # progresse pas qu'une conversation entière partie en clair.
            logger.warning("Profil non construit (masquage indisponible) : %s", e)
            return {"ecrit": False, "raison": "masquage indisponible"}

        from langchain_core.messages import HumanMessage

        from llm.concurrence import porter
        from llm.router import LLMTier, get_llm
        # Un créneau de FOND : la passe ne prend pas ceux du chat.
        porter(f"fond:profil:{user_id}", 1)
        # Palier COMPLEX : lire une manière de travailler dans dix conversations
        # est un travail de jugement, pas une classification. Le palier rapide
        # rendrait des généralités.
        reponse = await get_llm(LLMTier.COMPLEX).ainvoke([HumanMessage(
            content=CONSIGNE.format(
                profil=profil_masque or "(aucun portrait pour l'instant)",
                matiere=matiere_masquee, maxi=MAX_PROFIL))])
        brut = getattr(reponse, "content", "") or ""
        if not str(brut).strip():
            return {"ecrit": False, "raison": "le modèle n'a rien rendu"}

        # ── Réhydratation : le portrait stocké porte les vrais noms ─────
        propre = anonymizer.rehydrate(brut.strip(), carte)[:MAX_PROFIL]
        # Un jeton resté orphelin n'a rien à faire dans un portrait qu'un
        # humain lira : on le neutralise plutôt que de le montrer.
        import re
        propre = re.sub(r"\[[A-Z]+_\d+\]", "[à compléter]", propre)

        maintenant = datetime.now(timezone.utc)
        async with get_db() as conn:
            await conn.execute(
                """INSERT INTO profils_utilisateur
                       (user_id, profil, conversations, messages, jusqu_a, derniere_maj)
                   VALUES ($1::uuid, $2, $3, $4, $5, NOW())
                   ON CONFLICT (user_id) DO UPDATE SET
                       profil = EXCLUDED.profil,
                       conversations = profils_utilisateur.conversations + EXCLUDED.conversations,
                       messages = profils_utilisateur.messages + EXCLUDED.messages,
                       jusqu_a = EXCLUDED.jusqu_a, derniere_maj = NOW()""",
                user_id, propre, nb_fils, nb_messages, maintenant)
        oublier_cache(user_id)
        logger.info("Profil mis à jour pour %s (%d conversation(s), %d message(s))",
                    user_id[:8], nb_fils, nb_messages)
        return {"ecrit": True, "conversations": nb_fils, "messages": nb_messages,
                "longueur": len(propre)}
    except Exception as e:  # noqa: BLE001 — une passe de fond ne casse jamais rien
        logger.warning("Profil non construit pour %s : %s", user_id[:8], e)
        return {"ecrit": False, "raison": str(e)[:200]}


async def passe_de_nuit() -> dict:
    """Met à jour le portrait de chaque compte actif. Appelée par le planificateur.

    UNE PERSONNE À LA FOIS, à dessein : la porte de concurrence
    (`llm/concurrence.py`) réserve un créneau de fond, et lancer cinquante
    passes en parallèle prendrait tous les créneaux du fournisseur — à minuit
    c'est sans conséquence, à 8 h ça bloquerait le chat si la passe déborde.
    """
    from database.connection import get_db

    try:
        async with get_db() as conn:
            comptes = await conn.fetch(
                "SELECT u.id FROM users u "
                "LEFT JOIN profils_utilisateur p ON p.user_id = u.id "
                "WHERE COALESCE(u.actif, true) AND COALESCE(p.actif, true) "
                "ORDER BY p.derniere_maj NULLS FIRST LIMIT $1",
                MAX_COMPTES_PAR_PASSE)
    except Exception as e:  # noqa: BLE001
        logger.warning("Passe de nuit impossible : %s", e)
        return {"comptes": 0, "ecrits": 0, "raison": str(e)[:200]}

    ecrits, sautes = 0, 0
    for c in comptes:
        resultat = await construire(str(c["id"]))
        if resultat.get("ecrit"):
            ecrits += 1
        else:
            sautes += 1
    logger.info("Passe de nuit : %d compte(s), %d portrait(s) mis à jour, %d sans matière",
                len(comptes), ecrits, sautes)
    return {"comptes": len(comptes), "ecrits": ecrits, "sans_matiere": sautes}


async def effacer(user_id: str) -> bool:
    """Oublie le portrait d'une personne. C'est SA donnée : elle doit pouvoir
    l'effacer, et le prochain passage repartira de zéro."""
    from database.connection import get_db
    async with get_db() as conn:
        fait = await conn.fetchval(
            "DELETE FROM profils_utilisateur WHERE user_id = $1::uuid RETURNING user_id",
            str(user_id))
    oublier_cache(user_id)
    return bool(fait)


async def activer(user_id: str, actif: bool) -> None:
    """Une personne peut refuser d'être observée. Le portrait existant reste,
    mais il ne s'injecte plus et la passe de nuit la saute."""
    from database.connection import get_db
    async with get_db() as conn:
        await conn.execute(
            """INSERT INTO profils_utilisateur (user_id, actif)
               VALUES ($1::uuid, $2)
               ON CONFLICT (user_id) DO UPDATE SET actif = EXCLUDED.actif""",
            str(user_id), actif)
    oublier_cache(user_id)
