import json
import datetime
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from auth.dependencies import get_current_user
from database.models import User
from database.connection import get_rls_db, get_db
from security.rbac import has_permission
from config import settings

router = APIRouter()

# LE PLANCHER DES INDICATEURS (réglage `kpi_depuis`).
#
# Une remise à zéro qui ne supprime rien : les lignes restent en base, on cesse
# de les compter. Réversible en effaçant le champ — ce qu'aucun DELETE ne
# permet. Il s'applique aux VOLUMES et aux COÛTS, pas aux listes
# opérationnelles : masquer les échecs des dernières 24 h ou les sessions en
# cours n'aurait aucun sens, ce sont des états présents, pas de l'historique.
def _plancher(colonne: str) -> str:
    from llm.reglages import plancher_sql
    return plancher_sql(colonne)



def _exiger(role: str, feature: str) -> None:
    """Lève une 403 si le rôle ne dispose pas de la permission demandée."""
    if not has_permission(role, feature):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission refusée",
        )


# ============================================================
# STATISTIQUES PERSONNELLES / GLOBALES (existant)
# ============================================================


@router.get("/stats")
async def get_stats(current_user: User = Depends(get_current_user)):
    """Statistiques personnelles de l'utilisateur courant (threads + usage du jour)."""
    async with get_rls_db(str(current_user.id), current_user.role) as conn:
        thread_count = await conn.fetchval(
            f"SELECT COUNT(*) FROM threads WHERE user_id = $1{_plancher('created_at')}",
            current_user.id,
        )
        usage_today = await conn.fetchrow(
            "SELECT request_count, tokens_total, cost_eur FROM api_usage_daily "
            "WHERE user_id = $1 AND date = CURRENT_DATE",
            current_user.id,
        )
    return {
        "threads": thread_count,
        "today": dict(usage_today) if usage_today else {
            "request_count": 0,
            "tokens_total": 0,
            "cost_eur": 0,
        },
        "quota_mensuel": current_user.quota_mensuel,
    }


@router.get("/global")
async def get_global_stats(current_user: User = Depends(get_current_user)):
    """Vue globale par rôle : nombre d'utilisateurs, requêtes et coûts du jour."""
    _exiger(current_user.role, "view_dashboard_global")
    async with get_rls_db(str(current_user.id), current_user.role) as conn:
        rows = await conn.fetch("""
            SELECT u.role,
                   COUNT(DISTINCT u.id) AS user_count,
                   COALESCE(SUM(d.request_count), 0) AS total_requests,
                   COALESCE(SUM(d.cost_eur), 0) AS total_cost
            FROM users u
            LEFT JOIN api_usage_daily d ON d.user_id = u.id AND d.date = CURRENT_DATE
            GROUP BY u.role
            ORDER BY u.role
        """)
    return [dict(row) for row in rows]


@router.get("/activity")
async def get_activity(
    current_user: User = Depends(get_current_user),
    limit: int = 20,
):
    """Journal d'activité récent (audit_log), le plus récent en premier.

    Renvoie l'intégralité des métadonnées techniques (metadata JSONB, message
    d'erreur, modèle, tokens, durée) pour la console développeur — super_admin only.
    """
    _exiger(current_user.role, "view_audit_log")
    async with get_rls_db(str(current_user.id), current_user.role) as conn:
        rows = await conn.fetch(
            "SELECT id, user_id, action, agent_id, model_used, tokens_in, tokens_out, "
            "cost_eur, duration_ms, success, error_message, metadata, created_at "
            "FROM audit_log ORDER BY created_at DESC LIMIT $1",
            limit,
        )
    out = []
    for row in rows:
        d = dict(row)
        # asyncpg renvoie le JSONB en str (aucun codec enregistré) → on désérialise.
        m = d.get("metadata")
        if isinstance(m, str):
            try:
                d["metadata"] = json.loads(m)
            except Exception:
                d["metadata"] = None
        out.append(d)
    return out


# ── LES ÉCHANGES, PERSONNE PAR PERSONNE ──────────────────────────────────
# Demande de Noa (07/09) : « depuis l'espace admin, dans les logs, voir de façon
# simple les questions/réponses posées par chacun des utilisateurs, avec les
# logs de chacun en détail déroulant ».
#
# Tout existait déjà, mais éparpillé : les questions et les réponses dans
# `messages`, le technique dans `audit_log`, et rien qui relie les deux. On ne
# crée donc ni table ni migration — on RAPPROCHE, et le rapprochement se fait
# par le fil (`metadata.trigger_id`, posé depuis le 07/09) avec un repli par
# fenêtre de temps pour tout ce qui a été journalisé avant.

# Un échange n'est pas un objet en base : c'est une question suivie de sa
# réponse. On part donc des messages de l'utilisateur — un par tour — et on va
# chercher la réponse qui suit DANS LE MÊME FIL.
#
# ⚠️ LES DEUX LIGNES PORTENT LA MÊME HEURE. `_persist_messages` les écrit dans
# une seule transaction, et `NOW()` y vaut l'heure de la transaction : trier par
# `created_at` seul ne les départage pas. D'où le `>=` et l'exclusion par `id`.
# ⚠️ LA RÉPONSE EST BORNÉE PAR LA QUESTION SUIVANTE. Sans cette borne, le
# premier tour d'un fil raflait la première réponse et tous les suivants
# ressortaient « aucune réponse enregistrée » — ce qu'on a lu à l'écran sur
# quatre tours qui avaient pourtant répondu. Une réponse appartient au tour
# qu'elle suit, jamais à celui d'après.
_SQL_ECHANGES = """
SELECT m.id, m.content AS question, m.created_at AS quand,
       t.langgraph_thread_id AS fil, t.agent_type,
       u.id AS utilisateur_id, u.email, u.name, u.role AS utilisateur_role,
       r.content AS reponse, r.created_at AS quand_reponse,
       s.created_at AS quand_suivante
FROM messages m
JOIN threads t ON t.id = m.thread_id
JOIN users u ON u.id = t.user_id
LEFT JOIN LATERAL (
    SELECT q.created_at
    FROM messages q
    WHERE q.thread_id = m.thread_id
      AND q.role = 'user'
      AND (q.created_at > m.created_at
           OR (q.created_at = m.created_at AND q.id > m.id))
    ORDER BY q.created_at ASC, q.id ASC
    LIMIT 1
) s ON true
LEFT JOIN LATERAL (
    SELECT a.content, a.created_at
    FROM messages a
    WHERE a.thread_id = m.thread_id
      AND a.role = 'assistant'
      AND a.created_at >= m.created_at
      AND a.id <> m.id
      -- Un tour arrêté sur une CARTE D'ACCORD écrit une réponse VIDE ; la
      -- vraie arrive après « Approuver » (routers/validation.py). La ligne
      -- vide était prise pour LA réponse : « Aucune réponse enregistrée »
      -- sous chaque retouche validée (15/09, fil d4864cdc).
      AND btrim(a.content) <> ''
      AND (s.created_at IS NULL OR a.created_at <= s.created_at)
    ORDER BY a.created_at ASC
    LIMIT 1
) r ON true
WHERE m.role = 'user'
  AND m.created_at > NOW() - ($1::int * INTERVAL '1 day')
  AND ($2::uuid IS NULL OR u.id = $2::uuid)
  AND ($3::text IS NULL OR m.content ILIKE '%' || $3::text || '%'
                        OR COALESCE(r.content, '') ILIKE '%' || $3::text || '%')
  -- LA FIN EST FIXÉE AU LANCEMENT D'UN EXPORT (16/09, audit D-22/S-22) : sans elle,
  -- les messages écrits PENDANT l'export décalent les pages, et une ligne peut
  -- être livrée deux fois ou pas du tout.
  AND ($6::timestamptz IS NULL OR m.created_at <= $6::timestamptz)
  -- PAGINATION PAR CLÉ plutôt que par OFFSET : sur un historique long, OFFSET
  -- relit et jette tout ce qui précède, à chaque page.
  AND ($7::timestamptz IS NULL OR (m.created_at, m.id) > ($7::timestamptz, $8::uuid))
ORDER BY m.created_at DESC, m.id DESC
LIMIT $4 OFFSET $5
"""


def _detail_du_fil(lignes, fil, debut, fin):
    """Les lignes techniques qui appartiennent à CE tour.

    ⚠️ LE FIL NE SUFFIT PAS, ET C'EST LE DÉFAUT QU'ON A VU À L'ÉCRAN. Un fil vit
    des jours et porte des dizaines de tours : filtrer sur lui seul collait les
    quatre-vingts lignes du fil `a9f88326`, du 3 au 7 septembre, sous CHACUN de
    ses tours. Le fil réduit à la bonne conversation, la FENÊTRE DE TEMPS
    désigne le tour — il faut les deux, et dans cet ordre.

    Rend `(lignes, exact)`. `exact` dit si le fil a servi : sur tout ce qui a
    été journalisé avant que les fils ne soient marqués, seule l'heure décide,
    et l'écran l'annonce plutôt que de faire passer un rapprochement approximatif
    pour une certitude.
    """
    dans_la_fenetre = [x for x in lignes if debut <= x["created_at"] <= fin]
    if not fil:
        return dans_la_fenetre, False
    par_fil = [x for x in dans_la_fenetre
               if (x.get("metadata") or {}).get("trigger_id") == fil]
    # Certaines lignes du tour ne portent pas de fil (un skill journalisé
    # ailleurs, une trace antérieure) : on les garde, la fenêtre les a déjà
    # bornées. Ce qui est écarté, c'est ce qui appartient à un AUTRE fil.
    autres = [x for x in dans_la_fenetre
              if not (x.get("metadata") or {}).get("trigger_id")]
    if par_fil:
        return sorted(par_fil + autres, key=lambda x: x["created_at"]), True
    return dans_la_fenetre, False


@router.get("/echanges")
async def get_echanges(
    current_user: User = Depends(get_current_user),
    jours: int = 7,
    limite: int = 40,
    page: int = 1,
    utilisateur: Optional[str] = None,
    q: Optional[str] = None,
):
    """Les questions posées et les réponses rendues, avec leur détail technique.

    SUPER_ADMIN SEUL, et c'est un choix. `view_audit_log` est aussi accordée à
    la direction, mais le journal qu'elle ouvre ne montre que des compteurs :
    ici on rend le CONTENU des conversations de tout le monde. C'est un cran
    au-dessus, du même ordre que lire la boîte mail d'un collègue — et la règle
    du 01/09 dit qu'une chose pareille ne s'ouvre pas par héritage de
    permission. La console développeur, où vit cet écran, est déjà
    super_admin ; élargir à la direction est une décision à prendre, pas un
    effet de bord.
    """
    _exiger_super_admin(current_user)
    jours = max(1, min(int(jours or 7), 365))
    limite = max(1, min(int(limite or 40), 200))
    page = max(1, int(page or 1))
    cible, recherche = _cible_et_recherche(utilisateur, q)
    echanges, gens = await _lire_echanges(jours, cible, recherche, limite, (page - 1) * limite,
                                          avec_gens=True)
    return {
        "echanges": echanges,
        "page": page,
        "limite": limite,
        "jours": jours,
        "utilisateurs": gens,
    }


def _exiger_super_admin(current_user) -> None:
    _exiger(current_user.role, "view_audit_log")
    if (current_user.role or "").strip().lower() != "super_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Réservé au super-administrateur.")


def _cible_et_recherche(utilisateur, q):
    cible = None
    if utilisateur:
        try:
            cible = uuid.UUID(str(utilisateur))
        except (ValueError, AttributeError):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="Identifiant d'utilisateur invalide.")
    return cible, ((q or "").strip() or None)


async def _lire_echanges(jours: int, cible, recherche, limite: int, decalage: int,
                         avec_gens: bool = False, croissant: bool = False,
                         fin=None, apres=None) -> tuple[list, list]:
    """Une page d'échanges, avec leur détail technique rapproché.

    Le technique n'est lu que sur la FENÊTRE DE TEMPS de la page (15/09) : lire
    tout le journal de la période ne tenait plus pour un export depuis le tout
    début — des dizaines de milliers de lignes d'audit pour une page de 500.
    """
    async with get_db() as conn:
        sql = (_SQL_ECHANGES.replace("ORDER BY m.created_at DESC, m.id DESC", "ORDER BY m.created_at ASC, m.id ASC")
               if croissant else _SQL_ECHANGES)
        lignes = await conn.fetch(sql, jours, cible, recherche, limite, decalage,
                                  fin, (apres or (None, None))[0], (apres or (None, None))[1])
        techniques = []
        if lignes:
            bornes = [r["quand"] for r in lignes] + [r["quand_reponse"] for r in lignes if r["quand_reponse"]]
            techniques = await conn.fetch(
                "SELECT id, user_id, action, agent_id, model_used, tokens_in, tokens_out, "
                "cost_eur, duration_ms, success, error_message, metadata, created_at "
                "FROM audit_log "
                "WHERE created_at BETWEEN $1 AND $2 "
                "  AND ($3::uuid IS NULL OR user_id = $3::uuid) "
                "ORDER BY created_at ASC",
                min(bornes) - datetime.timedelta(seconds=2),
                max(bornes) + datetime.timedelta(seconds=30), cible)
        gens = []
        if avec_gens:
            gens = await conn.fetch(
                "SELECT DISTINCT u.id, u.email, u.name, u.role "
                "FROM users u JOIN threads t ON t.user_id = u.id "
                "JOIN messages m ON m.thread_id = t.id "
                "WHERE m.created_at > NOW() - ($1::int * INTERVAL '1 day') "
                "ORDER BY u.name NULLS LAST, u.email",
                jours)
    techs = []
    for row in techniques:
        d = dict(row)
        m = d.get("metadata")
        if isinstance(m, str):
            try:
                d["metadata"] = json.loads(m)
            except Exception:
                d["metadata"] = {}
        d["metadata"] = d.get("metadata") or {}
        techs.append(d)

    # Par personne, triées par heure : chaque échange ne regarde que SA tranche
    # (bisect), au lieu de parcourir tout le journal de la page à chaque fois.
    import bisect
    par_personne: dict = {}
    for x in techs:
        par_personne.setdefault(str(x.get("user_id")), []).append(x)
    heures = {k: [x["created_at"] for x in v] for k, v in par_personne.items()}

    echanges = []
    for row in lignes:
        d = dict(row)
        quand = d["quand"]
        fin = d.get("quand_reponse") or quand
        qui = str(d["utilisateur_id"])
        les_siennes = par_personne.get(qui, [])
        tranche = les_siennes[bisect.bisect_left(heures.get(qui, []), quand - datetime.timedelta(seconds=2)):
                              bisect.bisect_right(heures.get(qui, []), fin + datetime.timedelta(seconds=30))]
        # Une marge : la ligne d'audit est écrite APRÈS la réponse, et la
        # réponse elle-même est persistée avant le journal.
        # LES LIGNES DE CETTE PERSONNE SEULEMENT : depuis que la fenêtre court
        # jusqu'à la réponse d'après l'accord (parfois un quart d'heure), elle
        # attrapait les lignes sans fil d'un autre compte actif au même moment.
        detail, exact = _detail_du_fil(
            tranche,
            d.get("fil"),
            quand - datetime.timedelta(seconds=2),
            fin + datetime.timedelta(seconds=30))
        # LE RÉSUMÉ SE LIT SUR LA LIGNE `chat_request` DU TOUR. Elle ne porte le
        # fil que depuis le 07/09 : sur tout l'historique, la chercher dans les
        # seules lignes du fil ne rendait rien, et l'écran affichait
        # « modèle — · 0 jeton · 0.0000 € » partout. On la cherche donc dans la
        # FENÊTRE, qui, elle, existe depuis toujours.
        principal = next((x for x in detail if x["action"] == "chat_request"), None)
        if principal is None:
            principal = next(
                (x for x in tranche
                 if x["action"] == "chat_request"
                 and quand - datetime.timedelta(seconds=2) <= x["created_at"]
                 <= fin + datetime.timedelta(seconds=30)), None)
        echanges.append({
            "id": str(d["id"]),
            "quand": quand,
            "fil": d.get("fil"),
            # L'EXPERT DU TOUR, PAS CELUI DU FIL. `threads.agent_type` monte
            # vers agent2 au premier tour de conception et n'en redescend
            # jamais (c'est voulu, pour l'historique du fil) : l'afficher ici
            # étiquetait « expert conception » des tours de devis et de mails.
            "expert": (principal or {}).get("agent_id") or d.get("agent_type"),
            "utilisateur": {"id": str(d["utilisateur_id"]), "email": d.get("email"),
                            "nom": d.get("name"), "role": d.get("utilisateur_role")},
            "question": d.get("question") or "",
            "reponse": d.get("reponse") or "",
            "sans_reponse": not d.get("reponse"),
            # Le résumé, celui qu'on lit sans dérouler.
            "modele": (principal or {}).get("model_used"),
            "duree_ms": (principal or {}).get("duration_ms"),
            "cout_eur": float((principal or {}).get("cost_eur") or 0),
            "jetons": int((principal or {}).get("tokens_in") or 0)
                      + int((principal or {}).get("tokens_out") or 0),
            # Un tour arrêté sur l'accord était journalisé « aucune réponse
            # finale » avant c18cd7c ; si la réponse d'après l'accord existe, ce
            # n'était pas un échec.
            "succes": bool((principal or {}).get("success", True)) or bool(
                d.get("reponse") and (principal or {}).get("error_message") == "aucune réponse finale"),
            "erreur": (None if d.get("reponse") and (principal or {}).get("error_message")
                       == "aucune réponse finale" else (principal or {}).get("error_message")),
            "gestes": ((principal or {}).get("metadata") or {}).get("gestes") or [],
            "pieces": ((principal or {}).get("metadata") or {}).get("pieces") or 0,
            # Le détail déroulant : toutes les lignes d'audit du tour.
            "detail": [{"quand": x["created_at"], "action": x["action"],
                        "succes": x["success"], "erreur": x["error_message"],
                        "modele": x["model_used"], "duree_ms": x["duration_ms"],
                        "metadata": x["metadata"]} for x in detail],
            # L'honnêteté du rapprochement : par le fil (exact) ou par l'heure.
            "detail_exact": exact,
        })

    return echanges, [{"id": str(g["id"]), "email": g["email"],
                       "nom": g["name"], "role": g["role"]} for g in gens]


# ── L'EXPORT DEPUIS LE TOUT DÉBUT (15/09) ───────────────────────────────────
# Noa : « qu'on puisse exporter le journal du bas, où il y a les requêtes et
# les réponses, depuis le tout début ». Tout l'historique, par pages de 500
# lues et écrites au fil de l'eau (jamais tout en mémoire), en CSV lisible par
# Excel (point-virgule, BOM UTF-8) ou en JSON complet (détail technique inclus).
EXPORT_PAQUET = 500
EXPORT_TOUT_JOURS = 36500


# ── UNE CELLULE DE TABLEUR N'EST PAS UNE FORMULE (16/09, audit D-22/S-22) ───────
# Une question qui commence par « =2+2 », « +33 6… », « -5 % » ou « @canal » est
# du TEXTE écrit par quelqu'un. Excel et LibreOffice, eux, l'exécutent à
# l'ouverture du CSV : c'est l'injection de formule (OWASP CSV Injection). Les
# guillemets du CSV n'y changent rien — ils protègent le séparateur, pas le
# tableur. On préfixe donc d'une apostrophe, marqueur « ceci est du texte »,
# et l'on retire les caractères de contrôle (tabulation et retour chariot en
# tête déclenchent le même effet), en gardant les retours à la ligne.
# ⚠️ L'export JSON, lui, reste FIDÈLE : c'est le format de référence.
_DEBUTS_DE_FORMULE = ("=", "+", "-", "@")


def _cellule_inerte(valeur):
    """Le texte d'une cellule, inoffensif à l'ouverture. Les nombres passent."""
    if not isinstance(valeur, str) or not valeur:
        return valeur
    texte = valeur.replace("\r\n", "\n").replace("\r", "\n")
    texte = "".join(c for c in texte if c == "\n" or ord(c) >= 32)
    if texte[:1] in _DEBUTS_DE_FORMULE:
        texte = "'" + texte
    return texte


def _ligne_csv(e: dict) -> list:
    gestes = " | ".join(f"{g.get('skill')}:{'ok' if g.get('ok') else 'échec'}"
                        for g in (e.get("gestes") or []) if isinstance(g, dict))
    u = e.get("utilisateur") or {}
    quand = e.get("quand")
    cellules = [quand.isoformat() if hasattr(quand, "isoformat") else str(quand or ""),
                u.get("nom") or "", u.get("email") or "", u.get("role") or "",
                e.get("fil") or "", e.get("expert") or "",
                e.get("question") or "", e.get("reponse") or "", gestes,
                e.get("modele") or "", round((e.get("duree_ms") or 0) / 1000, 1),
                e.get("jetons") or 0, e.get("cout_eur") or 0,
                "oui" if e.get("succes") else "non", e.get("erreur") or ""]
    return [_cellule_inerte(c) for c in cellules]


# ── LE TICKET DE TÉLÉCHARGEMENT (16/09, audit D-22/S-22) ───────────────────────
# L'écran téléchargeait l'export par `fetch` + Blob : tout l'historique passait
# par la mémoire du navigateur avant d'atteindre le disque. On échange donc le
# jeton de session contre un TICKET court, à usage unique, lié à la personne et
# à CE téléchargement ; le navigateur suit l'adresse et écrit au fil de l'eau.
# Jamais le JWT dans une URL : une adresse se retrouve dans l'historique, les
# journaux du serveur et le presse-papier.
_TICKETS_EXPORT: dict[str, dict] = {}
TICKET_EXPORT_TTL_S = 120


def _emettre_ticket(user, format: str, utilisateur, q) -> str:
    import secrets as _secrets
    import time as _time
    maintenant = _time.monotonic()
    for cle in [c for c, t in _TICKETS_EXPORT.items() if t["expire"] < maintenant]:
        _TICKETS_EXPORT.pop(cle, None)
    jeton = _secrets.token_urlsafe(24)
    _TICKETS_EXPORT[jeton] = {"user_id": str(user.id), "role": user.role,
                              "format": format, "utilisateur": utilisateur, "q": q,
                              "expire": maintenant + TICKET_EXPORT_TTL_S}
    return jeton


def _consommer_ticket(jeton: str) -> Optional[dict]:
    import time as _time
    entree = _TICKETS_EXPORT.pop(jeton or "", None)     # usage unique
    if not entree or entree["expire"] < _time.monotonic():
        return None
    return entree


class _TicketExport(BaseModel):
    format: str = "csv"
    utilisateur: Optional[str] = None
    q: Optional[str] = None


@router.post("/echanges/export/ticket")
async def ticket_export(body: _TicketExport, current_user: User = Depends(get_current_user)):
    """Un ticket de téléchargement (2 min, à usage unique) pour CET export."""
    _exiger_super_admin(current_user)
    fmt = "json" if (body.format or "").lower() == "json" else "csv"
    return {"ticket": _emettre_ticket(current_user, fmt, body.utilisateur, body.q),
            "expire_dans_s": TICKET_EXPORT_TTL_S}


@router.get("/echanges/export")
async def exporter_echanges(
    request: Request,
    format: str = "csv",
    utilisateur: Optional[str] = None,
    q: Optional[str] = None,
    ticket: Optional[str] = None,
):
    """Tous les échanges depuis le premier, du plus ancien au plus récent.

    Deux façons d'entrer : le jeton de session (en-tête `Authorization`, pour
    un appel d'API) ou un TICKET court obtenu juste avant (pour que le
    navigateur écrive le fichier directement sur le disque).
    """
    import csv
    import io
    from fastapi.responses import StreamingResponse

    if ticket:
        entree = _consommer_ticket(ticket)
        if entree is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Ticket de téléchargement expiré : relancez l'export.")
        async with get_db() as conn:
            ligne = await conn.fetchrow("SELECT * FROM users WHERE id = $1::uuid AND actif = true",
                                        entree["user_id"])
        if ligne is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Compte introuvable.")
        current_user = User(**dict(ligne))
        format, utilisateur, q = entree["format"], entree["utilisateur"], entree["q"]
    else:
        from auth.dependencies import get_current_user as _lire_jeton
        from fastapi.security import HTTPAuthorizationCredentials
        entete = request.headers.get("authorization") or ""
        if not entete.lower().startswith("bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session requise.")
        current_user = await _lire_jeton(HTTPAuthorizationCredentials(
            scheme="Bearer", credentials=entete.split(" ", 1)[1].strip()))

    # LES DROITS SONT REVÉRIFIÉS ICI, ticket ou pas : un ticket dit QUI demande,
    # jamais ce qu'il a le droit de lire (la permission a pu être retirée entre-temps).
    _exiger_super_admin(current_user)
    cible, recherche = _cible_et_recherche(utilisateur, q)
    fmt = "json" if (format or "").lower() == "json" else "csv"
    maintenant = datetime.datetime.now().strftime("%Y-%m-%d_%Hh%M")
    fin = datetime.datetime.now(datetime.timezone.utc)
    compte = {"lignes": 0}
    manifeste = {"depuis": "le premier échange", "jusqu_a": fin.isoformat(),
                 "personne": utilisateur or "toutes", "recherche": q or "",
                 "format": fmt, "demande_par": str(current_user.id),
                 "cellules_csv_neutralisees": fmt == "csv",
                 "note": ("Le CSV neutralise les cellules qu'un tableur prendrait pour des "
                          "formules (préfixe « ' ») ; le JSON est fidèle.")}

    async def _pages():
        apres = None
        while True:
            echanges, _ = await _lire_echanges(EXPORT_TOUT_JOURS, cible, recherche,
                                               EXPORT_PAQUET, 0, croissant=True,
                                               fin=fin, apres=apres)
            if not echanges:
                return
            yield echanges
            if len(echanges) < EXPORT_PAQUET:
                return
            dernier = echanges[-1]
            apres = (dernier["quand"], dernier["id"])

    def _defaut(v):
        return v.isoformat() if hasattr(v, "isoformat") else str(v)

    async def _flux():
        # Du plus ancien au plus récent, page après page, écrit au fil de l'eau.
        if fmt == "csv":
            yield "\ufeff"
            tampon = io.StringIO()
            w = csv.writer(tampon, delimiter=";")
            w.writerow(["date", "personne", "email", "rôle", "fil", "expert", "question",
                        "réponse", "gestes", "modèle", "durée (s)", "jetons", "coût (€)",
                        "réussi", "erreur"])
            yield tampon.getvalue()
            async for page in _pages():
                tampon = io.StringIO()
                w = csv.writer(tampon, delimiter=";")
                for e in page:
                    w.writerow(_ligne_csv(e))
                    compte["lignes"] += 1
                yield tampon.getvalue()
            tampon = io.StringIO()
            csv.writer(tampon, delimiter=";").writerow(
                ["#manifeste", json.dumps({**manifeste, "lignes": compte["lignes"]},
                                          ensure_ascii=False)])
            yield tampon.getvalue()
        else:
            yield '{"manifeste": ' + json.dumps(manifeste, ensure_ascii=False) + ', "echanges": ['
            premier = True
            async for page in _pages():
                for e in page:
                    yield ("" if premier else ",\n") + json.dumps(e, ensure_ascii=False, default=_defaut)
                    premier = False
                    compte["lignes"] += 1
            yield '], "lignes": ' + str(compte["lignes"]) + "}"

    nom = f"echanges_depuis_le_debut_{maintenant}.{fmt}"
    return StreamingResponse(
        _flux(), media_type="text/csv; charset=utf-8" if fmt == "csv" else "application/json",
        headers={"Content-Disposition": f'attachment; filename="{nom}"'})


@router.get("/token-usage")
async def get_token_usage(current_user: User = Depends(get_current_user), days: int = 7):
    """Consommation de tokens (audit_log) par modèle + totaux + stats du cache d'optimisation."""
    _exiger(current_user.role, "view_costs_global")
    days = max(1, min(days, 90))
    async with get_rls_db(str(current_user.id), current_user.role) as conn:
        by_model = await conn.fetch(
            "SELECT model_used, COUNT(*) AS n, COALESCE(SUM(tokens_in),0) AS tokens_in, "
            "COALESCE(SUM(tokens_out),0) AS tokens_out, COALESCE(SUM(cost_eur),0) AS cost_eur "
            f"FROM audit_log WHERE created_at > NOW() - ($1::int * INTERVAL '1 day'){_plancher('created_at')} "
            "AND model_used IS NOT NULL GROUP BY model_used ORDER BY tokens_in + tokens_out DESC",
            days,
        )
        totals = await conn.fetchrow(
            "SELECT COALESCE(SUM(tokens_in),0) AS tokens_in, COALESCE(SUM(tokens_out),0) AS tokens_out, "
            "COALESCE(SUM(cost_eur),0) AS cost_eur, COUNT(*) AS n FROM audit_log "
            f"WHERE created_at > NOW() - ($1::int * INTERVAL '1 day'){_plancher('created_at')} AND model_used IS NOT NULL",
            days,
        )
    from optim.tokens import response_cache
    return {
        "days": days,
        "totals": dict(totals) if totals else {},
        "by_model": [dict(r) for r in by_model],
        "cache": response_cache.stats(),
    }


# ============================================================
# SUPERVISION TEMPS RÉEL
# ============================================================


@router.get("/live-sessions")
async def get_live_sessions(current_user: User = Depends(get_current_user)):
    """
    Sessions actives récentes : threads dont la dernière activité (updated_at)
    remonte à moins de 30 minutes. Jointure sur `users` pour exposer le nom,
    l'email et le rôle de l'utilisateur derrière chaque session.
    """
    _exiger(current_user.role, "view_dashboard_global")
    async with get_rls_db(str(current_user.id), current_user.role) as conn:
        rows = await conn.fetch("""
            SELECT t.id,
                   t.title,
                   t.agent_type,
                   t.status,
                   t.updated_at,
                   u.id    AS user_id,
                   u.name  AS user_name,
                   u.email AS user_email,
                   u.role  AS user_role
            FROM threads t
            JOIN users u ON u.id = t.user_id
            WHERE t.updated_at > NOW() - INTERVAL '30 minutes'
            ORDER BY t.updated_at DESC
        """)
    return [dict(row) for row in rows]


@router.get("/agents-activity")
async def get_agents_activity(current_user: User = Depends(get_current_user)):
    """
    Activité des agents sur la journée courante, agrégée par `agent_id` depuis
    `audit_log` : nombre de requêtes, succès/échecs, tokens totaux (in + out),
    coût total et durée moyenne d'exécution.
    """
    # ADMINISTRATION SYSTÈME (01/09) : l'onglet « États des agents » a été retiré
    # à la direction, et l'écran Superviseur — seul autre appelant — est déjà
    # réservé au super_admin. Masquer un écran ne ferme pas son API.
    _exiger(current_user.role, "manage_system")
    async with get_rls_db(str(current_user.id), current_user.role) as conn:
        rows = await conn.fetch("""
            SELECT agent_id,
                   COUNT(*)                                   AS request_count,
                   COUNT(*) FILTER (WHERE success)            AS success_count,
                   COUNT(*) FILTER (WHERE NOT success)        AS failure_count,
                   COALESCE(SUM(tokens_in + tokens_out), 0)   AS tokens_total,
                   COALESCE(SUM(cost_eur), 0)                 AS cost_total,
                   COALESCE(ROUND(AVG(duration_ms)), 0)       AS avg_duration_ms
            FROM audit_log
            WHERE created_at::date = CURRENT_DATE
              AND agent_id IS NOT NULL
            GROUP BY agent_id
            ORDER BY agent_id
        """)
    return [dict(row) for row in rows]


# ============================================================
# COÛTS
# ============================================================


@router.get("/costs")
async def get_costs(current_user: User = Depends(get_current_user)):
    """
    Analyse des coûts :
    - `by_day` : coût, requêtes et tokens agrégés par jour sur les 30 derniers jours.
    - `current_month_total` : total du mois en cours.
    - `by_role` : répartition des coûts du mois courant par rôle (JOIN users).
    """
    _exiger(current_user.role, "view_costs_global")
    async with get_rls_db(str(current_user.id), current_user.role) as conn:
        by_day = await conn.fetch(f"""
            SELECT date,
                   COALESCE(SUM(cost_eur), 0)      AS cost_eur,
                   COALESCE(SUM(request_count), 0) AS request_count,
                   COALESCE(SUM(tokens_total), 0)  AS tokens_total
            FROM api_usage_daily
            WHERE date >= CURRENT_DATE - INTERVAL '30 days'{_plancher('date')}
            GROUP BY date
            ORDER BY date
        """)
        current_month_total = await conn.fetchrow(f"""
            SELECT COALESCE(SUM(cost_eur), 0)      AS cost_eur,
                   COALESCE(SUM(request_count), 0) AS request_count,
                   COALESCE(SUM(tokens_total), 0)  AS tokens_total
            FROM api_usage_daily
            WHERE date_trunc('month', date) = date_trunc('month', CURRENT_DATE){_plancher('date')}
        """)
        by_role = await conn.fetch("""
            SELECT u.role,
                   COALESCE(SUM(d.cost_eur), 0)      AS cost_eur,
                   COALESCE(SUM(d.request_count), 0) AS request_count,
                   COALESCE(SUM(d.tokens_total), 0)  AS tokens_total
            FROM users u
            LEFT JOIN api_usage_daily d
                   ON d.user_id = u.id
                  AND date_trunc('month', d.date) = date_trunc('month', CURRENT_DATE)
            GROUP BY u.role
            ORDER BY u.role
        """)
    return {
        "by_day": [dict(row) for row in by_day],
        "current_month_total": dict(current_month_total) if current_month_total else {
            "cost_eur": 0,
            "request_count": 0,
            "tokens_total": 0,
        },
        "by_role": [dict(row) for row in by_role],
    }


# ============================================================
# VALIDATIONS EN ATTENTE
# ============================================================


@router.get("/pending-skills")
async def get_pending_skills(current_user: User = Depends(get_current_user)):
    """
    Skills en attente de validation (status 'draft' ou 'testing'), avec leur
    score de confiance, leur auteur et leur date de création.
    """
    _exiger(current_user.role, "validate_skills")
    async with get_rls_db(str(current_user.id), current_user.role) as conn:
        rows = await conn.fetch("""
            SELECT id,
                   name,
                   description,
                   version,
                   status,
                   confidence_score,
                   usage_count,
                   created_by,
                   created_at
            FROM skills
            WHERE status IN ('draft', 'testing')
            ORDER BY created_at DESC
        """)
    return [dict(row) for row in rows]


@router.get("/pending-validations")
async def get_pending_validations(current_user: User = Depends(get_current_user)):
    """
    Demandes de validation human-in-the-loop en attente (status 'pending').

    Accessible aux rôles disposant de la permission `validate_skills` OU
    `manage_users`. Jointure sur `users` pour identifier le demandeur.
    """
    if not (
        has_permission(current_user.role, "validate_skills")
        or has_permission(current_user.role, "manage_users")
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission refusée",
        )
    async with get_rls_db(str(current_user.id), current_user.role) as conn:
        rows = await conn.fetch("""
            SELECT v.id,
                   v.thread_id,
                   v.agent,
                   v.reason,
                   v.draft,
                   v.created_at,
                   u.name  AS user_name,
                   u.email AS user_email,
                   u.role  AS user_role
            FROM validations v
            LEFT JOIN users u ON u.id = v.user_id
            WHERE v.status = 'pending'
              -- CHACUN SES ACCORDS (14/09) : les siens, et ceux sans propriétaire.
              AND (v.user_id = $1 OR v.user_id IS NULL)
            ORDER BY v.created_at ASC
        """, current_user.id)
    return [dict(row) for row in rows]


# ============================================================
# ALERTES
# ============================================================


@router.get("/alerts")
async def get_alerts(current_user: User = Depends(get_current_user)):
    """
    Liste d'alertes calculées à la volée pour le tableau de bord global.

    Trois familles d'alertes sont évaluées :
    - quotas mensuels proches de la limite (> 80 % de `role_quota_config`) ;
    - échecs LLM récents (audit_log, success = false, dernières 24 h), comptés
      par action ;
    - skills en attente de validation (status 'draft' ou 'testing').

    Chaque alerte : {level: 'info'|'warning'|'error', message, count}.
    """
    _exiger(current_user.role, "view_dashboard_global")

    alerts: list[dict] = []

    async with get_rls_db(str(current_user.id), current_user.role) as conn:
        # 1. Utilisateurs proches de leur quota mensuel (> 80 %)
        quotas_row = await conn.fetchrow("""
            SELECT COUNT(*) AS nb
            FROM (
                SELECT u.id
                FROM users u
                JOIN role_quota_config rq ON rq.role = u.role
                LEFT JOIN api_usage_daily d
                       ON d.user_id = u.id
                      AND date_trunc('month', d.date) = date_trunc('month', CURRENT_DATE)
                WHERE rq.monthly_limit IS NOT NULL
                GROUP BY u.id, rq.monthly_limit
                HAVING COALESCE(SUM(d.request_count), 0) > 0.8 * rq.monthly_limit
            ) AS proches
        """)
        nb_quotas = quotas_row["nb"] if quotas_row else 0
        if nb_quotas > 0:
            alerts.append({
                "level": "warning",
                "message": f"{nb_quotas} utilisateur(s) proche(s) de leur quota mensuel (> 80 %)",
                "count": nb_quotas,
            })

        # 2. Échecs LLM des dernières 24 h, comptés par action
        echecs = await conn.fetch("""
            SELECT action, COUNT(*) AS nb
            FROM audit_log
            WHERE success = false
              AND created_at > NOW() - INTERVAL '24 hours'
            GROUP BY action
            ORDER BY nb DESC
        """)
        for row in echecs:
            alerts.append({
                "level": "error",
                "message": f"{row['nb']} échec(s) LLM sur l'action « {row['action']} » (24 h)",
                "count": row["nb"],
            })

        # 3. Skills en attente de validation
        nb_skills = await conn.fetchval("""
            SELECT COUNT(*) FROM skills WHERE status IN ('draft', 'testing')
        """)
        if nb_skills and nb_skills > 0:
            alerts.append({
                "level": "info",
                "message": f"{nb_skills} skill(s) en attente de validation",
                "count": nb_skills,
            })

    return alerts


# ============================================================
# PILOTAGE (direction) — usages, coûts, journal, par personne
# ============================================================


@router.get("/pilotage")
async def get_pilotage(current_user: User = Depends(get_current_user)):
    """Ce que la page Pilotage montre : des CHIFFRES RÉELS, agrégés en une fois.

    La page affichait « n/d » sur ses indicateurs et « route non implémentée »
    sur les coûts par personne, avec un avertissement disant que les vrais
    chiffres étaient ailleurs. Le brief (§15) en fait pourtant une exigence de
    la Direction : suivi de la consommation par utilisateur, des coûts IA, des
    usages anormaux, journalisation des actions. La donnée existait déjà —
    `api_usage_daily` (par personne et par jour) et `audit_log` (chaque action,
    sa durée, son succès) — elle n'était simplement pas servie.

    Un seul appel, parce que la page se lit d'un coup : indicateurs, série
    quotidienne sur trente jours, répartition par personne sur trente jours,
    erreurs des dernières vingt-quatre heures, dernières actions du journal.
    Le journal est borné et ne porte JAMAIS le contenu des échanges — seulement
    l'action, qui, quand, combien de temps, réussi ou non : c'est ce que
    `log_action` y écrit, rien d'autre.
    """
    _exiger(current_user.role, "view_dashboard_global")
    peut_couts = has_permission(current_user.role, "view_costs_global")
    peut_journal = has_permission(current_user.role, "view_audit_log")

    async with get_db() as conn:
        kpi = await conn.fetchrow(f"""
            SELECT
              (SELECT COALESCE(SUM(request_count), 0) FROM api_usage_daily
                WHERE date >= CURRENT_DATE - INTERVAL '30 days'{_plancher('date')})  AS requetes_30j,
              (SELECT COUNT(*) FROM audit_log
                WHERE success = false AND created_at >= NOW() - INTERVAL '24 hours') AS erreurs_24h,
              (SELECT COALESCE(SUM(cost_eur), 0) FROM api_usage_daily
                WHERE date_trunc('month', date) = date_trunc('month', CURRENT_DATE){_plancher('date')}) AS cout_mois_eur,
              (SELECT COUNT(DISTINCT user_id) FROM api_usage_daily
                WHERE date >= CURRENT_DATE - INTERVAL '30 days'{_plancher('date')})  AS personnes_actives_30j,
              (SELECT COUNT(*) FROM validations WHERE status = 'pending')   AS accords_en_attente,
              (SELECT COUNT(*) FROM skills WHERE status IN ('validated','stable')
                                              AND COALESCE(enabled, true))   AS competences_actives
        """)
        par_jour = await conn.fetch(f"""
            SELECT date,
                   COALESCE(SUM(request_count), 0) AS requetes,
                   COALESCE(SUM(tokens_total), 0)  AS jetons,
                   COALESCE(SUM(cost_eur), 0)      AS cout_eur
            FROM api_usage_daily
            WHERE date >= CURRENT_DATE - INTERVAL '30 days'{_plancher('date')}
            GROUP BY date ORDER BY date
        """)
        par_personne = await conn.fetch(f"""
            SELECT u.id, u.name, u.email, u.role,
                   COALESCE(SUM(d.request_count), 0) AS requetes,
                   COALESCE(SUM(d.tokens_total), 0)  AS jetons,
                   COALESCE(SUM(d.cost_eur), 0)      AS cout_eur,
                   MAX(d.date)                       AS derniere_activite
            FROM users u
            LEFT JOIN api_usage_daily d
                   ON d.user_id = u.id AND d.date >= CURRENT_DATE - INTERVAL '30 days'{_plancher('d.date')}
            -- MÊME RÈGLE QUE list_users (01/09) : la direction ne voit pas les
            -- super_admin, ici non plus. Un filtre posé à un seul endroit est un
            -- rideau, pas un mur — ce tableau rend nom, e-mail et rôle.
            WHERE COALESCE(u.actif, true)
              AND ({'true' if current_user.role == 'super_admin' else "u.role <> 'super_admin'"})
            GROUP BY u.id, u.name, u.email, u.role
            ORDER BY requetes DESC, u.email
        """)
        # LE MÊME FILTRE AUX TROIS ENDROITS (01/09). Il n'était posé que sur le
        # tableau « par personne » — alors que le commentaire juste au-dessus
        # dit lui-même qu'un filtre à un seul endroit est un rideau, pas un
        # mur. Le Journal et les Erreurs rendent AUSSI le nom et l'e-mail :
        # la direction y voyait donc les super_admin qu'on venait de lui
        # masquer ailleurs. Une ligne d'un super_admin est retirée, pas
        # anonymisée : garder la ligne sans le nom dirait encore qu'il existe
        # une activité qu'on ne montre pas.
        filtre_admin = ("" if current_user.role == "super_admin"
                        else " AND (u.role IS NULL OR u.role <> 'super_admin')")
        erreurs = await conn.fetch(f"""
            SELECT a.created_at, a.action, a.agent_id, a.error_message,
                   COALESCE(u.name, u.email) AS qui
            FROM audit_log a LEFT JOIN users u ON u.id = a.user_id
            WHERE a.success = false AND a.created_at >= NOW() - INTERVAL '24 hours'
              {filtre_admin}
            ORDER BY a.created_at DESC LIMIT 50
        """) if peut_journal else []
        journal = await conn.fetch(f"""
            SELECT a.created_at, a.action, a.agent_id, a.model_used, a.duration_ms,
                   a.success, a.tokens_in, a.tokens_out,
                   COALESCE(u.name, u.email) AS qui
            FROM audit_log a LEFT JOIN users u ON u.id = a.user_id
            WHERE true {filtre_admin}
            ORDER BY a.created_at DESC LIMIT 80
        """) if peut_journal else []

    def _ligne(r):
        d = dict(r)
        for k, v in list(d.items()):
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
            elif type(v).__name__ == "Decimal":
                d[k] = float(v)
            elif hasattr(v, "hex") and k == "id":
                d[k] = str(v)
        return d

    personnes = [_ligne(r) for r in par_personne]
    if not peut_couts:
        # Sans le droit de voir les coûts, on voit QUI utilise, pas COMBIEN ça coûte.
        for p in personnes:
            p.pop("cout_eur", None)

    return {
        "kpi": _ligne(kpi) if kpi else {},
        "par_jour": [_ligne(r) for r in par_jour],
        "par_personne": personnes,
        "erreurs_24h": [_ligne(r) for r in erreurs],
        "journal": [_ligne(r) for r in journal],
        "droits": {"couts": peut_couts, "journal": peut_journal},
    }


# ============================================================
# CONSOLE DÉVELOPPEUR (super_admin uniquement)
# ============================================================


@router.get("/system")
async def get_system(current_user: User = Depends(get_current_user)):
    """
    État système temps réel pour la console développeur : fournisseurs LLM
    disponibles, cascade par palier, observabilité, checkpointer, config runtime.
    Réservé au super_admin (permission manage_system). Aucun secret exposé.
    """
    if not has_permission(current_user.role, "manage_system"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Réservé au super admin")

    from llm.router import _provider_available, _tier_chain, LLMTier
    import observability
    from agents import checkpointer as _cp

    providers = {
        p: _provider_available(p)
        for p in ["longcat", "deepseek", "openrouter", "groq", "anthropic", "ollama"]
    }
    chains = {
        t.value: [f"{prov}:{mod or 'default'}" for prov, mod in _tier_chain(t)]
        for t in (LLMTier.LIGHT, LLMTier.STANDARD, LLMTier.COMPLEX)
    }
    checkpointer_type = type(_cp._checkpointer).__name__ if _cp._checkpointer else "non initialisé"

    # Compteurs DB rapides
    async with get_db() as conn:
        counts = await conn.fetchrow(
            """SELECT
                 (SELECT COUNT(*) FROM users WHERE actif) AS users_actifs,
                 (SELECT COUNT(*) FROM threads) AS threads,
                 (SELECT COUNT(*) FROM audit_log) AS audit_events,
                 (SELECT COUNT(*) FROM validations WHERE status='pending') AS validations_pending,
                 (SELECT COUNT(*) FROM skills) AS skills"""
        )

    return {
        "environment": settings.environment,
        "debug": settings.debug,
        "providers": providers,
        "chains": chains,
        "observability": {
            "langfuse_enabled": observability.is_enabled(),
            "host": settings.langfuse_base_url or settings.langfuse_host,
        },
        "checkpointer": checkpointer_type,
        "browser_enabled": settings.browser_enabled,
        "schedule": f"{settings.access_start_hour}h–{settings.access_end_hour}h",
        "db": dict(counts) if counts else {},
    }
