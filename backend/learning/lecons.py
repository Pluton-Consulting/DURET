"""
LES LEÇONS — apprendre d'une correction plutôt qu'écrire une règle de plus.

Demande de Noa (15/09) : « c'est trop déterministe ce que tu as fait, il y a
plein de cas de ce genre qu'on n'a pas traités ; c'est mieux d'entraîner
l'IA ». Réentraîner le modèle (fine-tuning) n'est pas à notre portée sur un
modèle hébergé, et apprend le ton bien plus que le raisonnement. L'équivalent
pratique : se souvenir des ERREURS CORRIGÉES et les remettre sous les yeux du
modèle quand une situation semblable revient.

LE CYCLE, EN TROIS TEMPS, SANS AUCUNE LISTE DE MOTS :
  1. le ROUTEUR (un modèle) dit si la demande CORRIGE l'assistant
     (`correction_signalee`) ;
  2. à la fin de ce tour, le modèle PUISSANT relit l'échange — la réponse
     corrigée, la correction, la nouvelle réponse, les gestes — et en tire UNE
     leçon générale : la situation, l'erreur, la bonne conduite ; ou aucune
     (une préférence de ton, une information nouvelle, ce n'est pas une erreur
     de conduite) ;
  3. aux tours suivants, les leçons dont la situation ressemble à la demande
     sont rappelées dans le prompt, et le RELECTEUR (agents/verificateur.py)
     les connaît aussi. C'est au modèle de juger si elles s'appliquent.

CE QU'UNE LEÇON N'EST PAS. Ce n'est pas une CONSIGNE (learning/consignes.py) :
une consigne est un ordre explicite posé par un humain et injecté à chaque
tour. Une leçon est tirée d'un échange, n'est rappelée que si la situation
ressemble, et peut être retirée d'un clic (Connaissances → Leçons).

GARDE-FOUS. Une leçon ne porte ni nom, ni montant, ni adresse : elle doit
valoir pour la prochaine fois, pas raconter la dernière — une leçon qui porte
une balise de masquage est écartée. Une leçon déjà connue n'est pas dupliquée :
elle gagne une occurrence. Tout échec est silencieux pour le tour : apprendre
ne doit jamais empêcher de répondre.
"""
from __future__ import annotations

import json
import logging
import math
import re
from difflib import SequenceMatcher

logger = logging.getLogger("symbiose.learning.lecons")

MAX_LECONS_RAPPELEES = 4
MAX_CHAMP = 400
SEUIL_DOUBLON = 0.8
_BALISE = re.compile(r"\[[A-Z]+_\d+\]")
_MOT = re.compile(r"[a-zà-öø-ÿ]{4,}", re.I)
_VIDES = {"avec", "dans", "pour", "mais", "plus", "sans", "sont", "tout", "cette", "votre",
          "notre", "nous", "vous", "elle", "leur", "leurs", "fais", "faire", "peux", "moi"}

# Ce qui court en arrière-plan : une référence forte, sinon la tâche peut
# disparaître au ramasse-miettes avant d'avoir fini.
_EN_COURS: set = set()


# ── Extraire ─────────────────────────────────────────────────────────────

def consigne_extraction(question_precedente: str, reponse_corrigee: str, correction: str,
                        nouvelle_reponse: str, gestes: str) -> str:
    return (
        "Tu aides un assistant d'entreprise à APPRENDRE DE SES ERREURS. La personne vient de le "
        "corriger. Lis l'échange et tire-en UNE leçon GÉNÉRALE, réutilisable la prochaine fois "
        "qu'une situation semblable se présente.\n\n"
        "Une leçon décrit une ERREUR DE CONDUITE de l'assistant : il a affirmé ce qu'il n'avait pas "
        "fait, pris une information au mauvais endroit, confondu deux choses, ignoré une partie de la "
        "demande, réécrit au lieu de retoucher… Ce n'est PAS une leçon : une simple préférence de "
        "ton ou de longueur, une information nouvelle que la personne apporte, un changement d'avis.\n"
        "Écris-la SANS nom de personne, d'entreprise, de client, sans montant ni adresse : elle doit "
        "valoir pour d'autres cas.\n\n"
        f"DEMANDE PRÉCÉDENTE :\n{question_precedente[:1500]}\n\n"
        f"RÉPONSE DE L'ASSISTANT QUI A ÉTÉ CORRIGÉE :\n{reponse_corrigee[:2500]}\n\n"
        f"CORRECTION DE LA PERSONNE :\n{correction[:1000]}\n\n"
        f"CE QUE L'ASSISTANT A FAIT ENSUITE :\n{gestes[:1500] or '(aucun geste)'}\n"
        f"{nouvelle_reponse[:1500]}\n\n"
        "Réponds par un objet JSON SEUL, ou {\"lecon\": null} s'il n'y a pas de leçon :\n"
        '{"lecon": {"situation": "<quand cela se présente, en une phrase : « quand on demande de… »>", '
        '"erreur": "<ce que l\'assistant a mal fait, en une phrase>", '
        '"conduite": "<ce qu\'il doit faire à la place, à l\'impératif, une ou deux phrases>", '
        '"gestes": ["<noms des gestes concernés, s\'il y en a>"], "type": "procedure", '
        '"confiance": 0.6, "preuve": "<correction explicite sans nom propre>"}}'
    )


def lire_lecon(brut) -> dict | None:
    """La leçon rendue par le modèle, validée ; None s'il n'y en a pas."""
    texte = brut if isinstance(brut, str) else str(brut or "")
    trouve = re.search(r"\{.*\}", texte, re.S)
    if not trouve:
        return None
    try:
        d = json.loads(trouve.group(0))
    except ValueError:
        return None
    lecon = d.get("lecon") if isinstance(d, dict) else None
    if not isinstance(lecon, dict):
        return None
    situation = " ".join(str(lecon.get("situation") or "").split())[:MAX_CHAMP]
    conduite = " ".join(str(lecon.get("conduite") or "").split())[:MAX_CHAMP]
    erreur = " ".join(str(lecon.get("erreur") or "").split())[:MAX_CHAMP]
    if len(situation) < 15 or len(conduite) < 15:
        return None
    if _BALISE.search(situation + erreur + conduite):
        return None            # une leçon qui porte un nom masqué raconte un cas, pas une règle
    gestes = [str(g)[:60] for g in (lecon.get("gestes") or []) if str(g).strip()][:6]
    type_ = str(lecon.get("type") or "procedure").lower()
    if type_ not in ("preference", "fait", "procedure"):
        type_ = "procedure"
    try:
        confiance = float(lecon.get("confiance", 0.6))
    except (TypeError, ValueError):
        confiance = 0.6
    confiance = min(1.0, max(0.0, confiance)) if math.isfinite(confiance) else 0.6
    return {"situation": situation, "erreur": erreur, "conduite": conduite, "gestes": gestes,
            "type": type_, "confiance": confiance, "preuve": str(lecon.get("preuve") or "")[:800]}


def _echange_du_tour(messages: list) -> dict | None:
    """(question précédente, réponse corrigée, correction, nouvelle réponse) depuis l'historique."""
    def _t(m):
        c = getattr(m, "content", "")
        return c if isinstance(c, str) else str(c)
    suite = [(getattr(m, "type", ""), _t(m)) for m in messages or []
             if getattr(m, "type", "") in ("human", "ai")]
    if len(suite) < 3:
        return None
    # La fin de l'historique : [... humain précédent, IA corrigée, humain (correction), IA nouvelle]
    if suite[-1][0] != "ai":
        suite = suite + [("ai", "")]
    try:
        i_corr = max(i for i, (qui, _) in enumerate(suite[:-1]) if qui == "human")
        i_corrigee = max(i for i, (qui, _) in enumerate(suite[:i_corr]) if qui == "ai")
    except ValueError:
        return None
    precedentes = [t for qui, t in suite[:i_corrigee] if qui == "human"]
    return {"question_precedente": precedentes[-1] if precedentes else "",
            "reponse_corrigee": suite[i_corrigee][1], "correction": suite[i_corr][1],
            "nouvelle_reponse": suite[-1][1]}


async def extraire(state: dict) -> dict | None:
    """La leçon de ce tour, par le modèle puissant ; None s'il n'y en a pas."""
    from agents.memoire_gestes import journal_des_gestes
    from langchain_core.messages import HumanMessage
    from llm.router import LLMTier, get_llm

    echange = _echange_du_tour(state.get("messages") or [])
    if not echange or not echange["reponse_corrigee"].strip():
        return None
    invite = consigne_extraction(echange["question_precedente"], echange["reponse_corrigee"],
                                 echange["correction"], echange["nouvelle_reponse"],
                                 journal_des_gestes(state.get("tool_results") or []))
    reponse = await get_llm(LLMTier.COMPLEX).ainvoke([HumanMessage(content=invite)])
    return lire_lecon(reponse.content)


# ── Ranger ───────────────────────────────────────────────────────────────

def _texte(lecon: dict) -> str:
    return " ".join(str(lecon.get(k) or "") for k in ("situation", "erreur", "conduite")).lower()


def est_un_doublon(neuve: dict, existante: dict) -> bool:
    # « utiliser » et « ne pas utiliser » sont presque identiques à l'œil
    # d'une distance de texte, mais ne renforcent jamais la même règle.
    conduite=lambda l: " ".join(str(l.get('conduite') or '').casefold().split())
    return conduite(neuve)==conduite(existante) and SequenceMatcher(None, _texte(neuve), _texte(existante)).ratio() >= SEUIL_DOUBLON

def conflit_possible(neuve,existante):
    return (not est_un_doublon(neuve,existante)
            and SequenceMatcher(None,str(neuve.get('situation') or '').casefold(),str(existante.get('situation') or '').casefold()).ratio() >= .9)


async def enregistrer(user_id: str, lecon: dict, fil: str = "") -> str:
    """Range la leçon ; une leçon déjà connue gagne une occurrence. Rend « creee » ou « renforcee »."""
    from database.connection import get_db
    async with get_db() as conn:
        existantes = await conn.fetch(
            "SELECT id, situation, erreur, conduite FROM lecons "
            "WHERE actif AND (user_id = $1::uuid OR portee = 'entreprise') "
            "ORDER BY derniere_maj DESC LIMIT 200", user_id)
        for e in existantes:
            if est_un_doublon(lecon, dict(e)):
                await conn.execute(
                    "UPDATE lecons SET occurrences = occurrences + 1, derniere_maj = NOW() WHERE id = $1",
                    e["id"])
                return "renforcee"
        conflit=any(conflit_possible(lecon,dict(e)) for e in existantes)
        # CE QU'ELLE EST, ET CE QU'ELLE VAUT (16/09, audit D-14/S-14) : une tournure
        # de politesse et une règle de facturation ne s'injectent pas pareil, et
        # une leçon tirée d'une correction EXPLICITE vaut mieux qu'une déduction.
        type_lecon = str(lecon.get("type") or "procedure").strip().lower()
        if type_lecon not in ("preference", "fait", "procedure"):
            type_lecon = "procedure"
        try:
            confiance = float(lecon.get("confiance", 0.6))
        except (TypeError, ValueError):
            confiance = 0.6
        if not math.isfinite(confiance):
            confiance = 0.6
        try:
            await conn.execute(
                """INSERT INTO lecons (user_id, situation, erreur, conduite, gestes, source_fil,
                                       type_lecon, confiance, preuve, statut)
                   VALUES ($1::uuid, $2, $3, $4, $5::jsonb, $6, $7, $8, $9, $10)""",
                user_id, lecon["situation"], lecon["erreur"], lecon["conduite"],
                json.dumps(lecon.get("gestes") or [], ensure_ascii=False), (fil or "")[:200],
                type_lecon, max(0.0, min(1.0, confiance)), (lecon.get("preuve") or "")[:800] or None, "brouillon" if conflit else "active")
        except Exception as e:  # noqa: BLE001
            from database.connection import schema_incomplet
            if not schema_incomplet(e):
                raise
            # Sans la migration 048 : on écrit comme avant, rien n'est perdu.
            await conn.execute(
                """INSERT INTO lecons (user_id, situation, erreur, conduite, gestes, source_fil)
                   VALUES ($1::uuid, $2, $3, $4, $5::jsonb, $6)""",
                user_id, lecon["situation"], lecon["erreur"], lecon["conduite"],
                json.dumps(lecon.get("gestes") or [], ensure_ascii=False), (fil or "")[:200])
    return "a_verifier" if conflit else "creee"


# UNE PANNE PASSAGÈRE N'EST PAS UNE RÈGLE MÉTIER (16/09, audit D-14/S-14). Quand le
# tour a échoué parce qu'un fournisseur n'a pas répondu, la « correction » de la
# personne (« recommence ») ne dit rien de la conduite à tenir : en tirer une
# leçon, c'est graver dans la mémoire une panne d'un jour.
_PANNES_PASSAGERES = ("timeout", "timed out", "connection", "connexion", "429",
                      "quota", "502", "503", "504", "indisponible", "effet_inconnu")


def _panne_passagere(state: dict) -> bool:
    texte = " ".join(str(state.get(c) or "") for c in ("error", "derniere_erreur", "note_sortie")).lower()
    for r in state.get("tool_results") or []:
        if r.get("outcome") in ("failed", "denied", "pending") or r.get("effect_status") in ("unknown", "pending"):
            return True
        texte += " " + str(r.get("error") or r.get("warnings") or "").lower()
    return any(mot in texte for mot in _PANNES_PASSAGERES)


async def apprendre_du_tour(state: dict) -> str | None:
    """Tire et range la leçon d'un tour de correction. Ne lève jamais."""
    try:
        if not state.get("correction_signalee") or not state.get("user_id"):
            return None
        if _panne_passagere(state):
            logger.info("Correction après une panne passagère : aucune leçon tirée")
            return None
        lecon = await extraire(state)
        if not lecon:
            logger.info("Correction sans leçon de conduite (préférence ou information nouvelle)")
            return None
        issue = await enregistrer(str(state["user_id"]), lecon, str(state.get("thread_id") or ""))
        logger.info("Leçon %s : %s", issue, lecon["situation"][:120])
        return issue
    except Exception as e:  # noqa: BLE001 — apprendre ne casse jamais un tour
        logger.warning("Leçon non tirée : %s", str(e)[:200])
        return None


def apprendre_en_fond(state: dict) -> None:
    """Lance l'apprentissage sans retenir la réponse."""
    if not state.get("correction_signalee"):
        return
    import asyncio
    try:
        from contextvars import Context
        tache = asyncio.get_running_loop().create_task(apprendre_du_tour(dict(state)), context=Context())
    except RuntimeError:
        return
    _EN_COURS.add(tache)
    tache.add_done_callback(_EN_COURS.discard)


# ── Rappeler ─────────────────────────────────────────────────────────────

def requete_plein_texte(question: str) -> str:
    """Les mots porteurs de la demande, en OU, pour `to_tsquery('french', …)`."""
    mots = []
    for m in _MOT.findall(question or ""):
        m = m.lower()
        if m not in _VIDES and m not in mots:
            mots.append(m)
    return " | ".join(mots[:14])


async def pertinentes(user_id: str, question: str, limite: int = MAX_LECONS_RAPPELEES) -> list[dict]:
    """Les leçons dont la situation ressemble à la demande (les siennes et celles de l'entreprise).

    LES PLUS SÛRES D'ABORD (16/09, audit D-14/S-14) : quand deux leçons se
    contredisent, celle qui vient d'une correction explicite l'emporte sur une
    déduction. Sans la migration 048, la requête d'avant sert : les leçons
    continuent d'être rappelées, dans leur ordre d'alors.
    """
    requete = requete_plein_texte(question)
    if not requete or not user_id:
        return []
    from database.connection import get_db, schema_incomplet
    _CHAMPS = "id, situation, erreur, conduite, type_lecon, confiance"
    _FILTRE = "AND COALESCE(statut, 'active') = 'active'"
    lignes = []
    try:
        async with get_db() as conn:
            for champs, filtre in ((_CHAMPS, _FILTRE), ("id, situation, erreur, conduite", "")):
                try:
                    lignes = await conn.fetch(
                        f"""SELECT {champs},
                                  ts_rank(to_tsvector('french', situation || ' ' || erreur || ' ' || conduite),
                                          to_tsquery('french', $2)) AS rang
                           FROM lecons
                           WHERE actif AND (user_id = $1::uuid OR portee = 'entreprise')
                             {filtre}
                             AND to_tsvector('french', situation || ' ' || erreur || ' ' || conduite)
                                 @@ to_tsquery('french', $2)
                           ORDER BY rang DESC, occurrences DESC, derniere_maj DESC
                           LIMIT $3""", user_id, requete, limite)
                    break
                except Exception as e:  # noqa: BLE001
                    if not schema_incomplet(e):
                        raise
                    lignes = []      # migration 048 absente : on retente sans elle
            propres = [dict(l) for l in lignes]
            propres.sort(key=lambda l: float(l.get("confiance") or 0.6), reverse=True)
            if propres:
                await conn.execute("UPDATE lecons SET rappels = rappels + 1 WHERE id = ANY($1::uuid[])",
                                   [l["id"] for l in propres])
            return propres
    except Exception as e:  # noqa: BLE001
        if not schema_incomplet(e):
            logger.info("Leçons non lues : %s", str(e)[:160])
        return []


def bloc_pour_le_prompt(lecons: list[dict]) -> str:
    """Le rappel tel que le modèle le lit : c'est lui qui juge s'il s'applique."""
    if not lecons:
        return ""
    lignes = [f"- Quand {str(l['situation']).removeprefix('Quand ').removeprefix('quand ')} "
              f"Erreur déjà commise : {l.get('erreur') or '—'} À faire : {l['conduite']}"
              for l in lecons]
    return ("LEÇONS TIRÉES DE CORRECTIONS PASSÉES (applique celles dont la situation correspond "
            "VRAIMENT à la demande ; ignore les autres) :\n" + "\n".join(lignes) + "\n\n")
