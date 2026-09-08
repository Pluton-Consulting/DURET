"""
Skill `courrier_entrant` — les NOUVEAUX mails depuis la dernière fois, ouverts
en entier avec leurs pièces jointes récupérées et déposées, prêts pour le
point : réponses proposées à ceux qui en appellent une, et POURQUOI les
autres n'en appellent pas.

Demande de Noa du 08/09 : « une lecture des mails intuitive, simple, avec des
comptes rendus sous forme de cartes, où ça lit tous les mails, ça propose des
réponses uniquement à ceux qui nécessitent des réponses, ça explique pourquoi
certains ne nécessitent pas de réponse ; les pièces jointes récupérées,
stockées ; chaque mail lu dès réception → une tâche en attente de validation
qui dit ce qui a été fait ; des centaines de mails et de pièces, même si ça
prend 30 minutes ».

CE QUI MANQUAIT. `check_mails` lit une PÉRIODE (« les 7 derniers jours ») ;
lancé toutes les dix minutes par une tâche planifiée, il relisait les mêmes
messages à chaque réveil — chaque exécution tourne sur un fil neuf, sans
mémoire de la précédente. Ici un REPÈRE persistant par personne et par boîte
(table `courrier_suivi`, migration 038) : chaque appel ne rend que ce qui est
arrivé depuis, ouvre chaque message en entier (`lire_mail`, pièces jointes
déposées par `mail/pieces.py`, donc téléchargeables et lues), et avance le
repère. Une tâche « toutes les 10 minutes : courrier entrant » traite donc
CHAQUE mail une fois, dès son arrivée ; ses propositions d'envoi attendent
l'accord (tableau de bord → À valider, et le compte rendu revient dans la
conversation qui a créé la tâche).

Les cartes de réponses restent au modèle (contrat `reponses_mail`, comme
`check_mails`) : c'est lui qui juge ce qui appelle une réponse. Ce que le
skill impose : un message SANS réponse proposée doit avoir sa raison dite.
Rien ne part d'ici. Une lecture bornée par appel (30 messages, 3 de front),
le reste attend l'appel suivant — dit.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from database.connection import get_db
from skills.registre import Declaration

logger = logging.getLogger("symbiose.skills.courrier")

MESSAGES_PAR_APPEL = 30
DE_FRONT = 3
EXTRAIT = 700
PREMIERE_FOIS_JOURS = 1        # sans repère, on part de la veille
BLOCS_MAX = 24                 # cartes de pièces jointes affichées par appel


def _blocs_de(bloc) -> list:
    if isinstance(bloc, list):
        return [b for b in bloc if isinstance(b, dict)]
    return [bloc] if isinstance(bloc, dict) else []


def _date_de(m: dict):
    brut = str(m.get("date") or m.get("date_iso") or "").strip()
    if not brut:
        return None
    try:
        d = datetime.fromisoformat(brut.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


async def _repere(user, boite: str):
    async with get_db() as conn:
        ligne = await conn.fetchrow(
            "SELECT dernier_vu, dernieres_refs FROM courrier_suivi WHERE user_id = $1::uuid AND boite = $2",
            str(user.id), boite)
    if not ligne:
        return None, set()
    refs = ligne["dernieres_refs"]
    if isinstance(refs, str):
        try:
            refs = json.loads(refs)
        except Exception:  # noqa: BLE001
            refs = []
    return ligne["dernier_vu"], set(refs or [])


async def _avancer_repere(user, boite: str, dernier_vu, refs: set) -> None:
    async with get_db() as conn:
        await conn.execute(
            """INSERT INTO courrier_suivi (user_id, boite, dernier_vu, dernieres_refs)
               VALUES ($1::uuid, $2, $3, $4::jsonb)
               ON CONFLICT (user_id, boite) DO UPDATE
                   SET dernier_vu = EXCLUDED.dernier_vu, dernieres_refs = EXCLUDED.dernieres_refs,
                       updated_at = NOW()""",
            str(user.id), boite, dernier_vu, json.dumps(sorted(refs)[-200:]))


async def courrier_entrant(data: dict, user) -> dict:
    from mail.skills import SKILLS_NATIFS
    lire_mails = SKILLS_NATIFS["lire_mails"]
    lire_mail = SKILLS_NATIFS["lire_mail"]

    boite_demandee = str(data.get("mailbox") or data.get("boite") or "").strip() or None
    avec_pieces = str(data.get("pieces", "true")).strip().lower() not in ("false", "0", "non")
    cle_boite = boite_demandee or "@moi"
    dernier_vu, refs_vues = await _repere(user, cle_boite)
    depuis = (dernier_vu.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
              if dernier_vu else f"{PREMIERE_FOIS_JOURS}j")

    args = {"depuis": depuis, "limite": MESSAGES_PAR_APPEL}
    if boite_demandee:
        args["mailbox"] = boite_demandee
    liste = await lire_mails(args, user)
    boite = str(liste.get("boite") or liste.get("mailbox") or cle_boite)
    messages = [m for m in (liste.get("messages") or []) if m.get("ref") and m["ref"] not in refs_vues]
    # Le repère avance à la date du message le plus récent VU, jamais à
    # « maintenant » : un message arrivé pendant la lecture n'est pas perdu.
    plus_recent = dernier_vu
    for m in messages:
        d = _date_de(m)
        if d and (plus_recent is None or d > plus_recent):
            plus_recent = d

    sem = asyncio.Semaphore(DE_FRONT)

    async def _ouvrir(m: dict) -> dict:
        async with sem:
            try:
                fiche = await lire_mail({"ref": m["ref"], "pieces": avec_pieces}, user)
            except Exception as e:  # noqa: BLE001 — un message illisible n'arrête pas les autres
                return {**m, "corps": "", "pieces": [], "blocs": [], "erreur": str(e)[:120]}
        corps = str(fiche.get("corps") or fiche.get("texte") or m.get("apercu") or "")
        pieces = fiche.get("pieces_jointes") or []
        noms = [str(p.get("nom") or p) for p in pieces if p] if isinstance(pieces, list) else []
        return {**m, "corps": corps, "pieces": noms, "blocs": _blocs_de(fiche.get("bloc_ui")),
                "liens": fiche.get("liens") or []}

    ouverts = await asyncio.gather(*[_ouvrir(m) for m in messages])
    if plus_recent or messages:
        await _avancer_repere(user, cle_boite, plus_recent or datetime.now(timezone.utc),
                              refs_vues | {m["ref"] for m in messages})

    releve = []
    blocs: list = []
    for o in ouverts:
        releve.append({
            "ref": o.get("ref"), "de": o.get("de"), "objet": o.get("objet"), "date": o.get("date"),
            "extrait": (o.get("corps") or "")[:EXTRAIT],
            "corps_tronque": len(o.get("corps") or "") > EXTRAIT,
            "pieces_jointes": o.get("pieces") or [],
            "liens": (o.get("liens") or [])[:5],
            "automatique": bool(o.get("expediteur_automatique") or o.get("automatique")),
            "interne": bool(o.get("expediteur_interne") or o.get("interne")),
            "non_lu": not bool(o.get("lu", True)),
            **({"erreur": o["erreur"]} if o.get("erreur") else {}),
        })
        for b in o.get("blocs") or []:
            if b.get("type") in ("fichier", "visuel") and len(blocs) < BLOCS_MAX:
                blocs.append(b)
    nb_pieces = sum(len(r["pieces_jointes"]) for r in releve)
    total = liste.get("total_periode")
    reste = (int(total) - len(liste.get("messages") or [])) if total else 0
    if releve:
        blocs.insert(0, {"type": "table", "titre": f"Courrier entrant — {len(releve)} nouveau(x) message(s)",
                         "columns": ["De", "Objet", "Reçu le", "Pièces"],
                         "rows": [[str(r["de"] or ""), str(r["objet"] or "")[:90], str(r["date"] or "")[:16].replace("T", " "),
                                   ", ".join(r["pieces_jointes"])[:80]] for r in releve]})
    sortie = {
        "boite": boite, "depuis": depuis, "nombre": len(releve), "pieces_jointes": nb_pieces,
        "messages": releve,
        "reste": max(reste, 0),
        "message_final": (f"{len(releve)} nouveau(x) message(s) depuis "
                          + (f"le {dernier_vu.astimezone(timezone.utc):%d/%m à %H:%M} (UTC)" if dernier_vu else "hier")
                          + (f", {nb_pieces} pièce(s) jointe(s) récupérée(s)" if nb_pieces else "")
                          + (f" ; {max(reste, 0)} de plus attendent l'appel suivant" if reste > 0 else "") + "."),
    }
    if blocs:
        sortie["bloc_ui"] = blocs
        sortie["bloc_garanti"] = True
    if not releve:
        sortie["a_faire"] = ("Aucun nouveau message : dis-le en une phrase, rien d'autre.")
        return sortie
    sortie["a_faire"] = (
        "Le tableau des messages et les cartes des pièces jointes sont DÉJÀ affichés : ne les "
        "recopie pas. Fais le point en UN message. Pour CHAQUE message : l'expéditeur, l'objet, "
        "une phrase tirée de l'extrait. Propose une réponse UNIQUEMENT à ceux qui en appellent "
        "une (question, demande, devis, relance, rendez-vous) — toutes dans UN SEUL bloc ```ui "
        "reponses_mail (ref, de, objet, synthese, reponse). Pour chaque message SANS réponse "
        "proposée, dis en quelques mots POURQUOI (automatique, information, copie, remerciement, "
        "déjà traité…) : la personne doit voir que rien n'a été oublié. Un `extrait` tronqué : "
        "ouvre le message avec `lire_mail` avant de répondre. N'envoie rien : chaque envoi "
        "repasse par `envoyer_email` et son accord."
        + (" Des messages attendent l'appel suivant : rappelle `courrier_entrant` après ce point."
           if reste > 0 else ""))
    return sortie


SKILLS = {
    "courrier_entrant": Declaration(
        fonction=courrier_entrant,
        description=(
            "LES NOUVEAUX MAILS depuis la dernière fois (repère mémorisé par boîte), chacun "
            "OUVERT en entier avec ses pièces jointes récupérées, déposées et affichées. Rend "
            "le tableau des messages, les extraits, les pièces ; puis propose une réponse "
            "seulement à ceux qui en appellent une et dit pourquoi les autres n'en appellent "
            "pas. `mailbox` (défaut : la boîte de la personne), `pieces: false` pour ne pas "
            "lire les pièces. C'est le geste d'une tâche planifiée « toutes les 10 minutes : "
            "courrier entrant » — chaque mail est traité UNE fois, dès son arrivée. Pour une "
            "PÉRIODE (« mes mails de la semaine »), c'est `check_mails`."),
        requis=[], optionnels=["mailbox", "pieces"], effet="lecture",
        libelle="je lis le courrier entrant"),
}
