"""
LE TABLEAU DE BORD D'UN PATRON DE PME — pas d'un développeur.

Ce que la direction veut savoir en ouvrant l'outil : ce qu'il lui a fait
gagner, ce que chaque expert a fait pour l'entreprise, ce qui attend une
décision, ce qui est planifié, ce qui s'est passé récemment. Pas le nombre de
requêtes HTTP, pas les jetons, pas les latences — ça, c'est la page Pilotage,
et elle s'adresse à qui administre.

DEUX PÉRIMÈTRES, tranchés par le rôle. Qui a le droit de voir le tableau de
bord global (direction, administration) voit l'entreprise ; les autres voient
LEUR activité — leurs conversations, leurs tâches, leurs documents. Le brief
(§15) le demande : « accès uniquement aux dossiers les concernant ». C'est le
serveur qui filtre, jamais l'écran.

LE ROI EST UNE ESTIMATION, ET IL LE DIT. Le brief (§13) pose l'hypothèse :
temps récupéré valorisé 65 €/h. On compte ce que les experts ont FAIT — des
conversations menées, des documents produits, des mails traités, des plans
analysés — et on y applique un temps économisé par geste, réglable. Les
hypothèses sont rendues avec le chiffre, pour que personne ne lise une
estimation comme une mesure.

CHAQUE BLOC SE DÉFEND SEUL. Une table absente, une colonne manquante sur un
déploiement plus ancien : le bloc rend zéro ou vide, et le reste de la page
s'affiche. Un tableau de bord qui tombe entièrement parce qu'une de ses neuf
cartes n'a pas pu lire sa donnée n'aide personne.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from auth.dependencies import get_current_user
from config import settings
from database.connection import get_db
from database.models import User
from security.rbac import has_permission

logger = logging.getLogger("duret.routers.tableau")
router = APIRouter()


def _val(d: Any, cle: str, defaut: Any = 0) -> Any:
    try:
        v = d[cle]
    except (KeyError, TypeError):
        return defaut
    if v is None:
        return defaut
    if type(v).__name__ == "Decimal":
        return float(v)
    return v


def _ligne(r) -> dict:
    d = dict(r)
    for k, v in list(d.items()):
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif type(v).__name__ == "Decimal":
            d[k] = float(v)
        elif type(v).__name__ == "UUID":
            d[k] = str(v)
    return d


async def _sur(conn, sql: str, *args, defaut: Any = None):
    """Une requête qui ne fait jamais tomber la page."""
    try:
        return await conn.fetch(sql, *args)
    except Exception as e:  # noqa: BLE001
        logger.info("Bloc du tableau de bord indisponible (%s) : %s", type(e).__name__, sql[:60])
        return defaut if defaut is not None else []


async def _une(conn, sql: str, *args):
    lignes = await _sur(conn, sql, *args)
    return lignes[0] if lignes else None


@router.get("/tableau")
async def tableau(current_user: User = Depends(get_current_user)):
    global_ = has_permission(current_user.role, "view_dashboard_global")
    voir_couts = has_permission(current_user.role, "view_costs_global")
    uid = current_user.id
    # Le filtre de périmètre est le MÊME fragment partout : $1 = user_id,
    # $2 = vrai si global. Un collaborateur ne voit que ce qui porte son nom.
    perim = "($2::boolean OR {col} = $1::uuid)"
    # LE PLANCHER DES INDICATEURS. Réglage `kpi_depuis` : une remise à zéro qui
    # ne supprime rien. Les lignes restent en base — on cesse simplement de les
    # compter. Réversible en effaçant le champ, ce qu'aucun DELETE ne permet.
    # Il ne s'applique QU'À l'activité : l'inventaire (« mémoire d'entreprise »)
    # décrit ce que l'outil connaît aujourd'hui, et le remettre à zéro
    # ferait mentir l'écran sur des documents qui existent bel et bien.
    from llm.reglages import plancher_sql
    plancher = plancher_sql("created_at")
    plancher_a = plancher_sql("a.created_at")
    plancher_date = plancher_sql("date")
    plancher_t = plancher_sql("t.created_at")

    async with get_db() as conn:
        # ── Ce que les experts ont fait ce mois-ci (30 jours glissants) ──
        faits = await _une(conn, f"""
            SELECT
              COUNT(*) FILTER (WHERE action = 'chat_request' AND COALESCE(agent_id,'agent1') = 'agent1') AS conversations_a1,
              COUNT(*) FILTER (WHERE action = 'chat_request' AND agent_id = 'agent2')                     AS analyses_a2,
              COUNT(*) FILTER (WHERE action = 'chat_request' AND agent_id = 'agent3')                     AS sollicitations_a3,
              COUNT(*) FILTER (WHERE action = 'skill_executed'
                                 AND metadata->>'skill' IN ('terminer_document','produire_document'))     AS documents,
              COUNT(*) FILTER (WHERE action = 'skill_executed'
                                 AND metadata->>'skill' IN ('lire_mails','lire_mail','triage_email_entrant',
                                                            'resume_fil_email','redaction_email'))        AS mails,
              COUNT(*) FILTER (WHERE action = 'skill_executed'
                                 AND metadata->>'skill' IN ('chercher_web','ouvrir_page','naviguer'))     AS web,
              COUNT(*) FILTER (WHERE action = 'skill_executed'
                                 AND metadata->>'skill' IN ('rechercher_documents','interroger_donnees')) AS recherches,
              COUNT(*) FILTER (WHERE action IN ('browser_task_completed'))                                AS navigations,
              COUNT(*) FILTER (WHERE success = false)                                                     AS echecs
            FROM audit_log
            WHERE created_at >= NOW() - INTERVAL '30 days' AND {perim.format(col='user_id')}{plancher}
        """, uid, global_)

        # Activité par jour (14 jours) : des barres, pas des courbes de dev.
        par_jour = await _sur(conn, f"""
            SELECT date_trunc('day', created_at)::date AS jour,
                   COUNT(*) FILTER (WHERE action = 'chat_request') AS conversations,
                   COUNT(*) FILTER (WHERE action = 'skill_executed') AS actions
            FROM audit_log
            WHERE created_at >= NOW() - INTERVAL '14 days' AND {perim.format(col='user_id')}{plancher}
            GROUP BY 1 ORDER BY 1
        """, uid, global_)

        # La MATIÈRE du ROI, par jour sur 60 jours : les mêmes gestes que
        # `faits`, datés. Les 30 derniers dessinent la courbe ; les 30 d'avant
        # donnent la variation « ce mois ». Une seule requête, convertie en
        # minutes puis en euros côté Python, avec les mêmes hypothèses.
        roi_jours = await _sur(conn, f"""
            SELECT date_trunc('day', created_at)::date AS jour,
                   COUNT(*) FILTER (WHERE action = 'chat_request' AND COALESCE(agent_id,'agent1') <> 'agent2') AS conversations,
                   COUNT(*) FILTER (WHERE action = 'chat_request' AND agent_id = 'agent2')                      AS analyses,
                   COUNT(*) FILTER (WHERE action = 'skill_executed'
                                      AND metadata->>'skill' IN ('terminer_document','produire_document'))      AS documents,
                   COUNT(*) FILTER (WHERE action = 'skill_executed'
                                      AND metadata->>'skill' IN ('lire_mails','lire_mail','triage_email_entrant',
                                                                 'resume_fil_email','redaction_email'))         AS mails,
                   COUNT(*) FILTER (WHERE action = 'skill_executed'
                                      AND metadata->>'skill' IN ('rechercher_documents','interroger_donnees',
                                                                 'chercher_web','ouvrir_page','naviguer'))      AS recherches
            FROM audit_log
            WHERE created_at >= NOW() - INTERVAL '60 days' AND {perim.format(col='user_id')}{plancher}
            GROUP BY 1 ORDER BY 1
        """, uid, global_)

        # ── À valider : accords en attente + compétences à valider ──
        accords = await _sur(conn, f"""
            SELECT v.id, v.agent, v.reason, v.created_at, v.thread_id,
                   LEFT(COALESCE(v.draft, ''), 220) AS apercu,
                   COALESCE(u.name, u.email) AS demandeur
            FROM validations v LEFT JOIN users u ON u.id = v.user_id
            WHERE v.status = 'pending' AND {perim.format(col='v.user_id')}
            ORDER BY v.created_at DESC LIMIT 12
        """, uid, global_)
        competences_a_valider = await _sur(conn, """
            SELECT name, description, status, created_at
            FROM skills
            WHERE status IN ('draft','testing') AND created_by <> 'system'
              AND COALESCE(code,'') NOT LIKE '%Squelette g_n_rique%'
            ORDER BY created_at DESC LIMIT 8
        """) if global_ else []

        # ── Tâches (arrière-plan) ──
        taches = await _sur(conn, f"""
            SELECT t.id, LEFT(t.query, 160) AS demande, t.status, t.progress, t.created_at, t.updated_at,
                   COALESCE(u.name, u.email) AS par
            FROM taches_differees t LEFT JOIN users u ON u.id = t.user_id
            WHERE {perim.format(col='t.user_id')}{plancher_t}
            ORDER BY t.updated_at DESC LIMIT 10
        """, uid, global_)
        synthese = await _une(conn, f"""
            SELECT COUNT(*) FILTER (WHERE status IN ('terminee','termine','done'))              AS terminees,
                   COUNT(*) FILTER (WHERE status IN ('en_cours','attente_validation','pending')) AS en_attente,
                   COUNT(*) FILTER (WHERE status IN ('echec','erreur','failed','interrompue'))   AS echouees,
                   COUNT(*)                                                                       AS total
            FROM taches_differees
            WHERE created_at >= NOW() - INTERVAL '30 days' AND {perim.format(col='user_id')}{plancher}
        """, uid, global_)

        # ── Actions planifiées (réveils automatiques) ──
        planifiees = await _sur(conn, f"""
            SELECT id, agent, title, schedule_kind, interval_minutes, time_of_day, days_of_week,
                   next_run_at, enabled
            FROM agent_tasks
            WHERE enabled AND {perim.format(col='user_id')}
            ORDER BY next_run_at NULLS LAST LIMIT 8
        """, uid, global_)

        # ── Mémoire d'entreprise : ce que l'outil connaît ──
        memoire = await _une(conn, """
            SELECT (SELECT COUNT(*) FROM documents)                                              AS documents,
                   (SELECT COUNT(*) FROM document_metadata WHERE source_type = 'devis')          AS devis,
                   (SELECT COUNT(*) FROM document_metadata WHERE source_type IN ('client','clients')) AS clients,
                   (SELECT COUNT(*) FROM document_metadata WHERE source_type IN ('fournisseur','fournisseurs')) AS fournisseurs,
                   (SELECT COUNT(*) FROM consignes)                                              AS consignes,
                   (SELECT COUNT(*) FROM skills WHERE status IN ('validated','stable') AND COALESCE(enabled,true)
                       AND COALESCE(code,'') NOT LIKE '%Squelette g_n_rique%')                  AS competences
        """)
        synchros = await _sur(conn, """
            SELECT DISTINCT ON (source) source, statut, etape, traites, total, demarre_a, termine_a
            FROM synchronisations ORDER BY source, demarre_a DESC
        """)

        # ── Activité récente, en mots ──
        activite = await _sur(conn, f"""
            SELECT a.created_at, a.action, a.agent_id, a.success, a.metadata->>'skill' AS skill,
                   COALESCE(u.name, u.email) AS qui
            FROM audit_log a LEFT JOIN users u ON u.id = a.user_id
            WHERE a.action IN ('chat_request','skill_executed','tache_differee_lancee',
                               'browser_task_completed','skill_created','skill_validated')
              AND {perim.format(col='a.user_id')}{plancher_a}
            ORDER BY a.created_at DESC LIMIT 14
        """, uid, global_)

        # ── Coût IA du mois (pour l'écart ROI), si le rôle y a droit ──
        cout = await _une(conn, f"""
            SELECT COALESCE(SUM(cost_eur), 0) AS cout
            FROM api_usage_daily
            WHERE date >= CURRENT_DATE - INTERVAL '30 days'{plancher_date}
        """) if voir_couts else None

    # ── Le ROI : un calcul lisible, des hypothèses visibles ──
    taux = float(getattr(settings, "roi_taux_horaire", 65.0))
    mn_q = float(getattr(settings, "roi_minutes_question", 10.0))
    mn_doc = float(getattr(settings, "roi_minutes_document", 45.0))
    mn_mail = float(getattr(settings, "roi_minutes_mail", 4.0))
    mn_ana = float(getattr(settings, "roi_minutes_analyse", 30.0))
    mn_rech = float(getattr(settings, "roi_minutes_recherche", 6.0))
    conv = int(_val(faits, "conversations_a1")) + int(_val(faits, "sollicitations_a3"))
    docs = int(_val(faits, "documents"))
    mails = int(_val(faits, "mails"))
    analyses = int(_val(faits, "analyses_a2"))
    recherches = int(_val(faits, "recherches")) + int(_val(faits, "web")) + int(_val(faits, "navigations"))
    minutes = conv * mn_q + docs * mn_doc + mails * mn_mail + analyses * mn_ana + recherches * mn_rech
    heures = round(minutes / 60.0, 1)
    euros = round(heures * taux, 0)

    jours_actifs = [_ligne(j) for j in par_jour]

    experts = [
        {
            "cle": "agent1",
            "actif": True,
            "kpis": [
                {"libelle": "conversations", "valeur": int(_val(faits, "conversations_a1"))},
                {"libelle": "documents produits", "valeur": docs},
                {"libelle": "mails traités", "valeur": mails},
            ],
            "en_attente": sum(1 for a in accords if (a["agent"] or "agent1") == "agent1"),
        },
        {
            "cle": "agent2",
            "actif": True,
            "kpis": [
                {"libelle": "plans & photos analysés", "valeur": analyses},
                {"libelle": "pré-chiffrages", "valeur": sum(1 for a in accords if a["reason"] == "chiffrage")},
                {"libelle": "recherches web", "valeur": int(_val(faits, "web")) + int(_val(faits, "navigations"))},
            ],
            "en_attente": sum(1 for a in accords if a["agent"] == "agent2"),
        },
        {
            "cle": "agent3",
            "actif": True,
            "kpis": [
                {"libelle": "compétences actives", "valeur": int(_val(memoire, "competences"))},
                {"libelle": "consignes retenues", "valeur": int(_val(memoire, "consignes"))},
                {"libelle": "à valider", "valeur": len(competences_a_valider)},
            ],
            "en_attente": len(competences_a_valider),
        },
    ]

    # La courbe et la variation, avec les mêmes hypothèses que le total.
    import datetime as _dt
    def _euros_du_jour(l) -> float:
        mn = (int(_val(l, "conversations")) * mn_q + int(_val(l, "documents")) * mn_doc
              + int(_val(l, "mails")) * mn_mail + int(_val(l, "analyses")) * mn_ana
              + int(_val(l, "recherches")) * mn_rech)
        return round(mn / 60.0 * taux, 2)
    aujourdhui = _dt.date.today()
    par_date = {l["jour"]: _euros_du_jour(l) for l in roi_jours}
    serie = [{"jour": (aujourdhui - _dt.timedelta(days=29 - i)).isoformat(),
              "euros": par_date.get(aujourdhui - _dt.timedelta(days=29 - i), 0.0)}
             for i in range(30)]
    avant = sum(v for j, v in par_date.items()
                if aujourdhui - _dt.timedelta(days=60) <= j < aujourdhui - _dt.timedelta(days=30))
    # Un mois de référence quasi vide rend des pourcentages absurdes (-100 %,
    # +4 000 %) : sous dix euros de base, on n'affiche pas de variation.
    if avant >= 10:
        variation_pct = round((euros - avant) / avant * 100)
    else:
        variation_pct = None

    # LE ROI EST UNE AFFAIRE DE DIRECTION (§15 : les collaborateurs n'ont pas
    # accès aux indicateurs financiers). Pour les autres rôles, le bloc n'est
    # pas rendu du tout : l'écran ne dessine pas une carte qu'on ne lui donne
    # pas — c'est le serveur qui tranche, jamais un `if` d'affichage.
    bloc_roi = None
    if global_:
        bloc_roi = {
            "euros": euros, "heures": heures, "periode": "30 derniers jours",
            "hypotheses": {
                "taux_horaire": taux, "minutes_par_conversation": mn_q,
                "minutes_par_document": mn_doc, "minutes_par_mail": mn_mail,
                "minutes_par_analyse": mn_ana, "minutes_par_recherche": mn_rech,
            },
            "detail": {"conversations": conv, "documents": docs, "mails": mails,
                       "analyses": analyses, "recherches": recherches},
            "cout_ia_eur": round(float(_val(cout, "cout")), 2) if cout is not None else None,
            "serie": serie,
            "variation_pct": variation_pct,
        }

    return {
        "perimetre": "global" if global_ else "personnel",
        "roi": bloc_roi,
        "experts": experts,
        "a_valider": {
            "accords": [_ligne(a) for a in accords],
            "competences": [_ligne(c) for c in competences_a_valider],
        },
        "synthese": {
            "terminees": int(_val(synthese, "terminees")),
            "en_attente": int(_val(synthese, "en_attente")),
            "echouees": int(_val(synthese, "echouees")),
            "total": int(_val(synthese, "total")),
            "par_jour": jours_actifs,
        },
        "planifiees": [_ligne(p) for p in planifiees],
        "taches": [_ligne(t) for t in taches],
        "memoire": {
            "documents": int(_val(memoire, "documents")),
            "devis": int(_val(memoire, "devis")),
            "clients": int(_val(memoire, "clients")),
            "fournisseurs": int(_val(memoire, "fournisseurs")),
            "synchronisations": [_ligne(s) for s in synchros],
        },
        "activite": [_ligne(a) for a in activite],
    }


@router.get("/tableau/historique/{agent}")
async def historique_expert(agent: str, current_user: User = Depends(get_current_user)):
    """Les conversations et tâches passées d'UN expert, pour la personne connectée.

    C'est ce que le bouton « Historique » d'une carte d'expert ouvre, et ce
    qu'un clic pré-inscrit dans le chat comme contexte. Toujours PERSONNEL :
    une conversation appartient à qui l'a menée, même pour la direction — le
    brief (§15) réserve à chacun « l'historique de ses propres échanges ».
    """
    if agent not in ("agent1", "agent2", "agent3"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expert inconnu")
    async with get_db() as conn:
        fils = await _sur(conn, """
            SELECT t.langgraph_thread_id AS thread_id, t.title, t.updated_at,
                   (SELECT LEFT(m.content, 240) FROM messages m
                     WHERE m.thread_id = t.id AND m.role = 'assistant'
                     ORDER BY m.created_at DESC LIMIT 1) AS derniere_reponse,
                   (SELECT COUNT(*) FROM messages m WHERE m.thread_id = t.id) AS nb_messages
            FROM threads t
            WHERE t.user_id = $1::uuid AND t.agent_type = $2
              AND t.langgraph_thread_id IS NOT NULL AND t.langgraph_thread_id NOT LIKE 'file:%'
            ORDER BY t.updated_at DESC LIMIT 25
        """, current_user.id, agent)
        taches = await _sur(conn, """
            SELECT id, LEFT(query, 200) AS demande, status, LEFT(COALESCE(response, ''), 240) AS reponse,
                   updated_at
            FROM taches_differees
            WHERE user_id = $1::uuid
            ORDER BY updated_at DESC LIMIT 15
        """, current_user.id) if agent == "agent1" else []
    return {"agent": agent,
            "conversations": [_ligne(f) for f in fils],
            "taches": [_ligne(t) for t in taches]}
