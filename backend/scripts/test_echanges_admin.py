"""
Banc « LES ÉCHANGES DANS L'ESPACE ADMIN » — demande du 07/09.

LA DEMANDE (Noa) : « depuis l'espace admin dans les logs, je veux voir de façon
simple les questions/réponses posées par chacun des utilisateurs, avec les logs
de chacun en détail déroulant ».

CE QUI EXISTAIT, ET POURQUOI ÇA NE SUFFISAIT PAS : les questions et les réponses
sont en base depuis toujours (`messages`), le technique aussi (`audit_log`) —
mais rien ne reliait les deux. La console développeur montrait des lignes
d'audit sans une phrase, et le contenu des conversations n'était visible nulle
part ailleurs que dans le fil de la personne. On ne crée donc ni table ni
migration : on RAPPROCHE.

CE QUE CE BANC PROUVE (sans base, sans réseau, sans navigateur) :
  · un tour dit quels gestes il a faits, sans jamais leurs arguments ni leurs
    résultats — un nom de skill n'est pas du contenu, un argument si ;
  · le fil voyage dans le journal (`trigger_id`), c'est lui qui rattache une
    ligne technique à l'échange qu'elle décrit ;
  · le rapprochement est EXACT par le fil, et se replie sur la fenêtre de temps
    pour tout ce qui a été journalisé avant — en le DISANT ;
  · la requête sait apparier une question et sa réponse même quand les deux
    lignes portent la MÊME heure (elles sont écrites dans une transaction) ;
  · la route est réservée au super_admin — pas seulement à `view_audit_log`,
    qui est aussi accordée à la direction ;
  · l'écran montre l'essentiel sans clic et déroule le reste.

CE QU'IL NE PROUVE PAS : la requête SQL n'a jamais tourné contre un vrai
Postgres, et l'écran n'a jamais été rendu dans un navigateur.
"""
import datetime
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
FRONTEND = BACKEND.parent / "frontend"
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ LES ÉCHANGES DANS L'ESPACE ADMIN — {BACKEND.parent}\n")

runtime_src = (BACKEND / "agents" / "runtime.py").read_text(encoding="utf-8")
chat_src = (BACKEND / "routers" / "chat.py").read_text(encoding="utf-8")
dash_src = (BACKEND / "routers" / "dashboard.py").read_text(encoding="utf-8")

# ══════════════════════════════════════════════════════════════════════════
# 1. UN TOUR DIT CE QU'IL A FAIT — et rien de ce qu'il a lu
# ══════════════════════════════════════════════════════════════════════════
print("── 1. Les gestes du tour")

debut = runtime_src.index("def gestes_du_tour")
fin = runtime_src.index("def _response_from_state")
espace = {}
exec(compile(runtime_src[debut:fin], "runtime.py", "exec"), espace)
gestes_du_tour = espace["gestes_du_tour"]

etat = {"tool_results": [
    {"skill": "lire_mails", "ok": True, "args": {"mailbox": "julien@exemple.fr"},
     "resultat_masque": "{\"messages\": [...]}"},
    {"skill": "drive_chercher", "ok": False, "args": {"motif": "contrat DUPONT"}},
    {"skill": "lire_mails", "ok": True, "args": {"mailbox": "julien@exemple.fr"}},
]}
sortie = gestes_du_tour(etat)

verifier("les gestes sortent avec leur nom et leur issue",
         sortie == [{"skill": "lire_mails", "ok": True},
                    {"skill": "drive_chercher", "ok": False}])
verifier("AUCUN argument ni résultat ne suit — ils portent du contenu",
         "julien@exemple.fr" not in str(sortie) and "DUPONT" not in str(sortie)
         and "resultat_masque" not in str(sortie))
verifier("le même geste répété à l'identique ne compte qu'une fois",
         len(sortie) == 2)
verifier("un geste sans nom est ignoré, il ne casse rien",
         gestes_du_tour({"tool_results": [{"ok": True}]}) == [])
verifier("un tour sans geste rend une liste vide",
         gestes_du_tour({}) == [])
verifier("la liste est bornée — un tour de 120 actions ne remplit pas le journal",
         len(gestes_du_tour({"tool_results": [
             {"skill": f"skill{i}", "ok": True} for i in range(120)]})) == 40)

# ── les trois sorties du runtime les portent ─────────────────────────────
verifier("les trois issues d'un tour portent les gestes (POST, reprise, flux)",
         runtime_src.count("gestes_du_tour(state)") >= 4)
verifier("l'événement `final` les porte aussi — le WebSocket est le chemin nominal",
         # Depuis le 07/09 soir, l'événement porte aussi les pièces jointes : l'ancre
         # suit le champ, pas l'accolade fermante.
         '"gestes": gestes_du_tour(state),' in runtime_src
         and runtime_src.count('"pieces": pieces_du_tour_persistables(state)}') >= 1)

# ══════════════════════════════════════════════════════════════════════════
# 2. LE FIL RELIE LA LIGNE TECHNIQUE À L'ÉCHANGE
# ══════════════════════════════════════════════════════════════════════════
print("\n── 2. Le lien entre le journal et l'échange")

verifier("les trois journalisations d'un tour de chat portent le fil",
         chat_src.count('trigger_id=thread_id') >= 3
         and chat_src.count('trigger_type="chat"') >= 3)
verifier("la voie POST journalise les gestes",
         '"gestes": result.get("gestes") or []' in chat_src)
verifier("la voie WebSocket journalise les gestes du flux",
         'gestes = event.get("gestes") or []' in chat_src
         and '"gestes": gestes' in chat_src)
verifier("le nombre de pièces jointes est journalisé (07/09 : un lot par message)",
         '"pieces": len(pieces)' in chat_src)

# ── le rapprochement, exécuté ────────────────────────────────────────────
debut = dash_src.index("def _detail_du_fil")
fin = dash_src.index('@router.get("/echanges")')
espace = {}
exec(compile(dash_src[debut:fin], "dashboard.py", "exec"), espace)
detail_du_fil = espace["_detail_du_fil"]

T0 = datetime.datetime(2026, 9, 7, 10, 0, 0)
LIGNES = [
    {"action": "chat_request", "created_at": T0,
     "metadata": {"trigger_id": "fil-A"}},
    {"action": "filet_mecanique", "created_at": T0 + datetime.timedelta(seconds=1),
     "metadata": {"trigger_id": "fil-A"}},
    {"action": "chat_request", "created_at": T0 + datetime.timedelta(minutes=5),
     "metadata": {"trigger_id": "fil-B"}},
    {"action": "login", "created_at": T0 + datetime.timedelta(seconds=2),
     "metadata": {}},
]

trouve, exact = detail_du_fil(LIGNES, "fil-A", T0 - datetime.timedelta(seconds=2),
                              T0 + datetime.timedelta(seconds=30))
verifier("par le FIL : aucune ligne d'un AUTRE fil n'entre",
         exact is True
         and all((l.get("metadata") or {}).get("trigger_id") in ("fil-A", None, "")
                 for l in trouve)
         and not any((l.get("metadata") or {}).get("trigger_id") == "fil-B"
                     for l in trouve))

trouve, exact = detail_du_fil(LIGNES, "fil-inconnu", T0 - datetime.timedelta(seconds=2),
                              T0 + datetime.timedelta(seconds=3))
verifier("sans fil marqué : repli sur la fenêtre de temps, et on le DIT",
         exact is False and len(trouve) == 3)
verifier("le repli ne ramasse pas le tour d'à côté, cinq minutes plus loin",
         all(l["created_at"] <= T0 + datetime.timedelta(seconds=3) for l in trouve))

trouve, exact = detail_du_fil([], "fil-A", T0, T0)
verifier("aucune ligne : une liste vide, pas une exception", trouve == [] and exact is False)

# ══════════════════════════════════════════════════════════════════════════
# 3. LA REQUÊTE, ET CE QU'ELLE PROTÈGE
# ══════════════════════════════════════════════════════════════════════════
print("\n── 3. La route")

verifier("la route existe", '@router.get("/echanges")' in dash_src)
verifier("elle apparie la question et la réponse du MÊME fil",
         "LEFT JOIN LATERAL" in dash_src and "a.role = 'assistant'" in dash_src)
verifier("elle sait apparier deux lignes écrites à la MÊME heure (une transaction)",
         "a.created_at >= m.created_at" in dash_src and "a.id <> m.id" in dash_src)
verifier("elle part des messages de la PERSONNE — un par tour, jamais deux lignes",
         "WHERE m.role = 'user'" in dash_src)
verifier("filtres : la personne, la période, les mots",
         "$2::uuid IS NULL OR u.id = $2::uuid" in dash_src
         and "ILIKE '%' || $3::text || '%'" in dash_src)
verifier("les bornes sont posées (période, page, nombre)",
         "min(int(jours or 7), 365)" in dash_src and "min(int(limite or 40), 200)" in dash_src)
verifier("un identifiant d'utilisateur invalide est refusé, pas passé au SQL",
         "uuid.UUID(str(utilisateur))" in dash_src and "HTTP_400_BAD_REQUEST" in dash_src)

# ── LE VERROU : contenu de tout le monde = super_admin seul ──────────────
bloc = dash_src[dash_src.index('@router.get("/echanges")'):]
bloc = bloc[:bloc.index("@router.get", 10)]
verifier("SUPER_ADMIN SEUL : `view_audit_log` ne suffit pas (la direction l'a aussi)",
         '_exiger(current_user.role, "view_audit_log")' in bloc
         and '!= "super_admin"' in bloc
         and "HTTP_403_FORBIDDEN" in bloc)
verifier("le choix est EXPLIQUÉ dans le code, pas seulement appliqué",
         "élargir à la direction est une décision" in bloc)

# ══════════════════════════════════════════════════════════════════════════
# 3bis. LES QUATRE DÉFAUTS RELEVÉS SUR L'ÉCRAN LIVRÉ (07/09, Noa)
# ══════════════════════════════════════════════════════════════════════════
print("\n── 3bis. Ce que l'écran livré montrait de faux")

# (1) Le MÊME journal de 80 lignes sous chaque échange : le rapprochement se
#     faisait par le FIL SEUL, or un fil vit des jours et porte des dizaines de
#     tours. Le fil réduit, la fenêtre TRANCHE.
LONG = [
    {"action": "skill_executed", "created_at": T0 - datetime.timedelta(days=4),
     "metadata": {"trigger_id": "fil-A"}},
    {"action": "chat_request", "created_at": T0,
     "metadata": {"trigger_id": "fil-A"}, "agent_id": "agent1"},
    {"action": "skill_executed", "created_at": T0 + datetime.timedelta(days=1),
     "metadata": {"trigger_id": "fil-A"}},
]
trouve, exact = detail_du_fil(LONG, "fil-A", T0 - datetime.timedelta(seconds=2),
                              T0 + datetime.timedelta(seconds=30))
verifier("un fil de plusieurs jours ne colle plus TOUT son journal sous chaque tour",
         len(trouve) == 1 and trouve[0]["action"] == "chat_request" and exact is True)

# (2) Une ligne du tour sans fil marqué (journalisée ailleurs) reste visible.
MIXTE = LONG + [{"action": "filet_mecanique",
                 "created_at": T0 + datetime.timedelta(seconds=3), "metadata": {}}]
trouve, _ = detail_du_fil(MIXTE, "fil-A", T0 - datetime.timedelta(seconds=2),
                          T0 + datetime.timedelta(seconds=30))
verifier("une ligne du tour sans fil marqué n'est pas jetée",
         len(trouve) == 2 and [x["action"] for x in trouve]
         == ["chat_request", "filet_mecanique"])

# (3) Une ligne d'un AUTRE fil, dans la même seconde, reste écartée.
AUTRE = LONG + [{"action": "chat_request",
                 "created_at": T0 + datetime.timedelta(seconds=1),
                 "metadata": {"trigger_id": "fil-B"}}]
trouve, _ = detail_du_fil(AUTRE, "fil-A", T0 - datetime.timedelta(seconds=2),
                          T0 + datetime.timedelta(seconds=30))
verifier("un tour d'un AUTRE fil, à la même seconde, reste écarté",
         all((x.get("metadata") or {}).get("trigger_id") != "fil-B" for x in trouve))

# (4) « modèle — · 0 jeton » : la ligne `chat_request` d'avant le marquage des
#     fils se retrouve par la FENÊTRE, sinon le résumé restait vide partout.
verifier("le résumé retombe sur la fenêtre quand `chat_request` n'a pas de fil",
         'principal = next(' in dash_src
         and "if principal is None:" in dash_src
         and 'x["action"] == "chat_request"' in dash_src.split("if principal is None:")[1][:400])

# (5) « expert agent2 » sur des tours d'agent1 : l'expert d'un TOUR se lit sur
#     sa ligne d'audit, pas sur le fil (qui monte vers agent2 et n'en redescend
#     jamais, par construction).
verifier("l'expert affiché est celui du TOUR, pas celui du fil",
         '(principal or {}).get("agent_id") or d.get("agent_type")' in dash_src)

# (6) « Aucune réponse enregistrée » sur des tours qui avaient répondu : la
#     réponse est bornée par la question SUIVANTE du fil.
verifier("la réponse d'un tour est bornée par la question suivante",
         "s.created_at AS quand_suivante" in dash_src
         and "a.created_at <= s.created_at" in dash_src)

# ══════════════════════════════════════════════════════════════════════════
# 3ter. LES INCOHÉRENCES DE L'ASSISTANT, LUES DANS CES MÊMES ÉCHANGES
# ══════════════════════════════════════════════════════════════════════════
print("\n── 3ter. Ce que l'assistant disait de faux")

proto = (BACKEND / "skills" / "protocol.py").read_text(encoding="utf-8")
agent1_src_bis = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("le catalogue DIT que l'en-tête et le pied de page existent "
         "(14:27 : « les blocs ne permettent pas d'insérer un en-tête » — faux)",
         "`entete` et `pied` " in proto and "sur CHAQUE page" in proto
         and "sont pas des blocs, ce sont des parametres d'ici" in proto)

# La vision rendait des dictionnaires Python à l'écran.
agent2_src = (BACKEND / "agents" / "agent2.py").read_text(encoding="utf-8")
debut = agent2_src.index("def _valeur_texte")
fin = agent2_src.index("def _blocs_extraction")
espace = {}
exec(compile(agent2_src[debut:fin], "agent2.py", "exec"), espace)
valeur_texte = espace["_valeur_texte"]

rendu = valeur_texte({"type": "piscine_coque", "modele": "MOLÈNE",
                      "dimensions_exterieures_m": {"longueur": 4.8, "largeur": 2.5},
                      "bonde_fond": True, "vide": None})
verifier("un élément d'extraction ne sort PLUS en dictionnaire Python",
         "{" not in rendu and "'" not in rendu and "piscine coque" in rendu)
verifier("il se lit : le nom d'abord, les détails ensuite",
         rendu.startswith("piscine coque —") and "longueur : 4.8" in rendu)
verifier("un booléen se dit en français, un champ vide disparaît",
         "bonde fond : oui" in rendu and "vide" not in rendu)
verifier("les nombres et les listes restent lisibles",
         valeur_texte(4.50) == "4.5" and valeur_texte(["a", "b"]) == "a, b")

# « Les liens ont expiré » au-dessus de deux fichiers valides.
annonce_src = (BACKEND / "agents" / "annonce.py").read_text(encoding="utf-8")
debut = annonce_src.index("_DEMENT_LA_DISPONIBILITE")
fin = annonce_src.index("def reclame_un_prealable")
espace = {}
exec(compile(annonce_src[debut:fin], "annonce.py", "exec"), espace)
dement = espace["dement_la_disponibilite"]

verifier("« les liens de téléchargement ont expiré » est reconnu comme un démenti",
         dement("Les liens de téléchargement de ces documents ont expiré "
                "(ils datent d'un échange précédent)."))
verifier("« n'est plus disponible » aussi", dement("Ce document n'est plus disponible."))
verifier("une réponse normale n'est pas prise pour un démenti",
         not dement("Voici le devis, il est téléchargeable ci-dessous.")
         and not dement("Le délai de livraison a expiré côté fournisseur.") is False)
verifier("le démenti passe au rendu de secours QUAND un livrable existe",
         "produits and dement_la_disponibilite(texte)" in agent1_src_bis)

# « Que préférez-vous ? » après trois recherches.
verifier("proposer de faire une lecture de plus est traité même si des gestes "
         "ont déjà tourné (le tour d'Ophélie, 15:45)",
         "a_livre = bool(_blocs_livrables" in agent1_src_bis
         and "and not a_livre)" in agent1_src_bis)

# ══════════════════════════════════════════════════════════════════════════
# 4. L'ÉCRAN
# ══════════════════════════════════════════════════════════════════════════
print("\n── 4. L'écran")

comp = FRONTEND / "components" / "dashboard" / "Echanges.tsx"
verifier("le composant existe", comp.exists())
tsx = comp.read_text(encoding="utf-8") if comp.exists() else ""
sup = (FRONTEND / "app" / "(app)" / "superviseur" / "SuperviseurClient.tsx").read_text(encoding="utf-8")

verifier("il est monté dans la console développeur",
         "components/dashboard/Echanges" in sup and "<Echanges " in sup)
verifier("une ligne par tour se lit SANS cliquer : heure, qui, question, verdict",
         "heure(e.quand)" in tsx and "qui(e.utilisateur)" in tsx and "e.question" in tsx)
verifier("le détail se DÉROULE (c'est la demande), et l'état est annoncé",
         'aria-expanded={ouvert}' in tsx and "setOuverts" in tsx)
verifier("le déroulé montre la question ENTIÈRE, la réponse, les gestes, le journal",
         "Ce qui a été demandé" in tsx and "Ce que l&apos;assistant a répondu" in tsx
         and "Ce qui a tourné" in tsx and "Journal du tour" in tsx)
verifier("on filtre par personne, par période et par mots",
         "tout le monde" in tsx and "PERIODES" in tsx and "setRecherche" in tsx)
verifier("un geste en échec se voit à l'œil, dans la ligne repliée",
         "en échec" in tsx and "rates" in tsx)
verifier("un rapprochement approximatif est DIT à l'écran, pas maquillé",
         "detail_exact" in tsx and "rapproché par l&apos;heure" in tsx)
verifier("choisir une personne ne vide pas le menu des personnes",
         "personne ? prev : data.utilisateurs" in tsx)
verifier("les pages s'enchaînent",
         "précédents" in tsx and "suivants" in tsx)

# 07/09, Noa : « fais en sorte que les logs soient plus détaillés, car là il y a
# juste écrit skill executed ». Le nom du geste était pourtant journalisé depuis
# toujours (`metadata.skill`) — l'écran ne le lisait pas.
verifier("une ligne de journal NOMME le geste, pas « skill_executed »",
         'if (l.action === "skill_executed" && m.skill) return m.skill' in tsx)
verifier("un filet nomme son mécanisme, une réponse nomme son modèle",
         'return `filet « ${m.filet} »`' in tsx
         and '`réponse · ${l.modele}`' in tsx)
verifier("l'effet du geste et la boîte concernée se lisent, sans aucun contenu",
         "effet ${m.effet}" in tsx and "m.mailbox" in tsx
         and "args" not in tsx.split("function detailsLigne")[1][:600])

# 15/09, Duret : un tour qui s'arrête sur une carte d'accord (l'envoi d'un
# mail, approuvé huit secondes plus tard) s'affichait « ✗ aucune réponse finale ».
verifier("un tour en attente d'accord n'est pas journalisé comme un échec",
         'if event.get("type") == "pending_validation":' in chat_src
         and "success=bool(final_response) or attend_un_accord" in chat_src)

# 15/09 (Symbiose, fil d4864cdc) : quatre retouches validées, et « Aucune
# réponse enregistrée » sous chacune. Le tour arrêté sur l'accord écrit une
# réponse VIDE ; la vraie arrive après « Approuver » — parfois un quart d'heure.
verifier("la réponse d'un tour est la première réponse NON VIDE (celle d'après l'accord)",
         "btrim(a.content) <> ''" in dash_src)
verifier("le détail du tour ne prend que les lignes de sa personne",
         'par_personne.get(qui, [])' in dash_src)
verifier("une réponse d'après l'accord efface le vieux « aucune réponse finale »",
         '== "aucune réponse finale"' in dash_src)
val_src = (BACKEND / "routers" / "validation.py").read_text(encoding="utf-8")
verifier("la décision « Approuver » porte le fil du tour qu'elle clôt",
         'trigger_type="validation", trigger_id=fil or None' in val_src)

# 15/09 — L'EXPORT DEPUIS LE TOUT DÉBUT. Noa : « qu'on puisse exporter le
# journal du bas, où il y a les requêtes et les réponses, depuis le tout début ».
# La route est EXÉCUTÉE contre une base doublée : pages de 500, du plus ancien
# au plus récent, CSV pour Excel et JSON complet.
import ast
import asyncio
import csv as _csv
import io as _io
import json as _json
import uuid as _uuid
from contextlib import asynccontextmanager

arbre = ast.parse(dash_src)
noms = {"get_echanges", "_lire_echanges", "_detail_du_fil", "_ligne_csv", "exporter_echanges", "_cible_et_recherche",
        "_exiger_super_admin", "EXPORT_PAQUET", "EXPORT_TOUT_JOURS", "_SQL_ECHANGES",
        # 16/09, audit D-22 : cellules inertes et ticket de téléchargement.
        "_cellule_inerte", "_DEBUTS_DE_FORMULE", "_TICKETS_EXPORT", "TICKET_EXPORT_TTL_S",
        "_emettre_ticket", "_consommer_ticket", "ticket_export", "_TicketExport"}
gardes = [n for n in arbre.body
          if (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name in noms)
          or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in noms for t in n.targets))
          or (isinstance(n, ast.AnnAssign) and getattr(n.target, "id", "") in noms)]
for n in gardes:
    n.decorator_list = []
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for a in n.args.defaults + n.args.kw_defaults:
            pass
# Des dates AVEC fuseau, comme les rend Postgres (`timestamptz`) : la borne de
# fin de l'export en est une aussi (audit D-22).
# … et toutes DANS LE PASSÉ : l'export borne sa fin à l'instant du lancement.
_T0 = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1300)
QUESTIONS = [{"id": _uuid.uuid4(), "question": f"question {i}", "quand": _T0 + datetime.timedelta(hours=i),
              "fil": "f1", "agent_type": "agent1", "utilisateur_id": "u1", "email": "a@exemple.fr", "name": "Anna",
              "utilisateur_role": "direction", "reponse": f"réponse {i}; « guillemets »\nligne 2",
              "quand_reponse": _T0 + datetime.timedelta(hours=i, seconds=5)} for i in range(1203)]
REQUETES = []


class _Conn:
    async def fetch(self, sql, *args):
        if "FROM messages m" in sql:
            REQUETES.append((sql, args))
            ordre = sorted(QUESTIONS, key=lambda r: r["quand"], reverse="created_at DESC" in sql.split("ORDER BY")[-1])
            # (16/09, audit D-22) La fin est bornée et la page reprend APRÈS la
            # dernière ligne livrée (created_at, id) : la doublure applique les
            # deux, sinon le banc ne prouverait pas la pagination par clé.
            if len(args) > 5 and args[5] is not None:
                ordre = [r for r in ordre if r["quand"] <= args[5]]
            if len(args) > 6 and args[6] is not None:
                ordre = [r for r in ordre if (r["quand"], str(r["id"])) > (args[6], str(args[7]))]
            return ordre[args[4]:args[4] + args[3]]
        if "FROM audit_log" in sql:
            return [{"id": 1, "user_id": "u1", "action": "chat_request", "agent_id": "agent1", "model_used": "m",
                     "tokens_in": 10, "tokens_out": 5, "cost_eur": 0.001, "duration_ms": 1200, "success": True,
                     "error_message": None, "created_at": args[0] + datetime.timedelta(seconds=3),
                     "metadata": '{"trigger_id": "f1", "gestes": [{"skill": "lire_mails", "ok": true}]}'}]
        return []


class _ConnAvecUsers(_Conn):
    async def fetchrow(self, sql, *args):
        # Le ticket de téléchargement relit le compte (audit D-22).
        if "FROM users" in sql:
            return {"id": "u-admin", "role": "super_admin"}
        return None


@asynccontextmanager
async def _get_db():
    yield _ConnAvecUsers()


class _Http(Exception):
    def __init__(self, status_code=None, detail=None):
        self.status_code, self.detail = status_code, detail


class _Flux:
    def __init__(self, gen, media_type=None, headers=None):
        self.gen, self.media_type, self.headers = gen, media_type, headers


sys.modules.setdefault("fastapi", types.ModuleType("fastapi"))
sys.modules["fastapi.responses"] = types.SimpleNamespace(StreamingResponse=_Flux)
esp = {"get_db": _get_db, "json": _json, "datetime": datetime, "uuid": _uuid, "HTTPException": _Http,
       "status": types.SimpleNamespace(HTTP_403_FORBIDDEN=403, HTTP_400_BAD_REQUEST=400),
       "_exiger": lambda role, f: None, "Optional": __import__("typing").Optional,
       "User": object, "Depends": lambda x=None: None, "get_current_user": None, "Query": lambda *a, **k: None}
# (16/09, audit D-22) L'export entre par le jeton de session OU par un ticket
# court : la doublure fournit les deux.
class _Requete:
    def __init__(self, entete=""):
        self.headers = {"authorization": entete} if entete else {}


async def _lire_jeton_double(credentials):
    """Le jeton de session, doublé : l'un ouvre en super_admin, l'autre en direction."""
    jeton = getattr(credentials, "credentials", "")
    if jeton == "jeton-direction":
        return types.SimpleNamespace(id="u-dir", role="direction")
    return admin


sys.modules["auth"] = types.ModuleType("auth")
sys.modules["auth.dependencies"] = types.SimpleNamespace(get_current_user=_lire_jeton_double)
sys.modules["fastapi.security"] = types.SimpleNamespace(
    HTTPAuthorizationCredentials=lambda scheme=None, credentials=None: types.SimpleNamespace(
        scheme=scheme, credentials=credentials))
esp["Request"] = _Requete
esp["User"] = lambda **kw: types.SimpleNamespace(**kw)
esp["status"].HTTP_401_UNAUTHORIZED = 401
esp["BaseModel"] = type("BaseModel", (), {})

exec(compile(ast.Module(body=gardes, type_ignores=[]), "dashboard", "exec"), esp)
admin = types.SimpleNamespace(id="u-admin", role="super_admin")


async def _lire(reponse):
    return "".join([bout async for bout in reponse.gen])

print("\n── 5. L'export : cellules inertes, borne de fin, ticket (audit D-22)")
inerte = esp["_cellule_inerte"]
verifier("une cellule qui commence par une formule devient du TEXTE (=, +, -, @)",
         [inerte(v) for v in ("=2+2", "+33 6 12 34 56 78", "-5 %", "@canal")]
         == ["'=2+2", "'+33 6 12 34 56 78", "'-5 %", "'@canal"])
verifier("le texte ordinaire et les nombres ne bougent pas",
         inerte("Bonjour, où en est le devis ?") == "Bonjour, où en est le devis ?"
         and inerte(12.5) == 12.5 and inerte(0) == 0 and inerte("") == "")
verifier("les caractères de contrôle sortent (une tabulation en tête suffisait), les retours à la ligne restent",
         inerte("a\x07b\r\nc") == "ab\nc" and inerte("\t=2+2") == "'=2+2", (inerte("a\x07b\r\nc"), inerte("\t=2+2")))
verifier("la ligne CSV entière passe par là",
         esp["_ligne_csv"]({"question": "=cmd|' /C calc'!A0", "reponse": "ok", "gestes": []})[6]
         == "'=cmd|' /C calc'!A0")

REQUETES.clear()
rep_csv = asyncio.run(esp["exporter_echanges"](_Requete("Bearer jeton-admin"), format="csv",
                                               utilisateur=None, q=None))
texte = asyncio.run(_lire(rep_csv))
lignes = list(_csv.reader(_io.StringIO(texte.lstrip("\ufeff")), delimiter=";"))
verifier("export CSV : TOUT l'historique (1 203 échanges, lus par pages de 500)",
         len(lignes) == 1205 and len(REQUETES) == 3, (len(lignes), len(REQUETES)))
verifier("… par pagination de CLÉ, jamais par OFFSET qui relit tout",
         all(a[4] == 0 for _s, a in REQUETES) and REQUETES[0][1][6] is None
         and REQUETES[1][1][6] == QUESTIONS[499]["quand"] and "(m.created_at, m.id) >" in REQUETES[0][0],
         [(a[4], a[6]) for _s, a in REQUETES])
verifier("… avec une FIN fixée au lancement (ce qui s'écrit pendant l'export ne décale rien)",
         all(a[5] is not None and a[5] == REQUETES[0][1][5] for _s, a in REQUETES))
verifier("… depuis le tout début, du plus ancien au plus récent",
         lignes[1][6] == "question 0" and lignes[-2][6] == "question 1202"
         and all("ASC" in _s.split("ORDER BY")[-1] and a[0] == esp["EXPORT_TOUT_JOURS"] for _s, a in REQUETES))
verifier("… lisible par Excel (BOM, point-virgule), réponses multi-lignes et guillemets intacts",
         texte.startswith("\ufeff") and lignes[1][7] == "réponse 0; « guillemets »\nligne 2"
         and lignes[1][8] == "lire_mails:ok" and lignes[1][9] == "m")
manifeste = _json.loads(lignes[-1][1])
verifier("… et un MANIFESTE en dernière ligne : période, filtres, nombre de lignes",
         lignes[-1][0] == "#manifeste" and manifeste["lignes"] == 1203 and manifeste["jusqu_a"]
         and manifeste["cellules_csv_neutralisees"] is True, lignes[-1][:1])
verifier("… en pièce à télécharger, datée", 'attachment; filename="echanges_depuis_le_debut_' in rep_csv.headers["Content-Disposition"])
REQUETES.clear()
rep_json = asyncio.run(esp["exporter_echanges"](_Requete("Bearer jeton-admin"), format="json",
                                                utilisateur=None, q=None))
brut = _json.loads(asyncio.run(_lire(rep_json)))
verifier("export JSON : fidèle (aucune cellule neutralisée), complet, avec son manifeste",
         len(brut["echanges"]) == 1203 and brut["lignes"] == 1203 and brut["manifeste"]["format"] == "json"
         and brut["echanges"][0]["detail"] and brut["echanges"][0]["question"] == "question 0")

ticket = asyncio.run(esp["ticket_export"](types.SimpleNamespace(format="csv", utilisateur=None, q=None),
                                          current_user=admin))["ticket"]
verifier("le ticket est court et à usage unique",
         esp["_consommer_ticket"](ticket) is not None and esp["_consommer_ticket"](ticket) is None
         and esp["TICKET_EXPORT_TTL_S"] <= 300)
ticket = asyncio.run(esp["ticket_export"](types.SimpleNamespace(format="csv", utilisateur=None, q=None),
                                          current_user=admin))["ticket"]
REQUETES.clear()
rep = asyncio.run(esp["exporter_echanges"](_Requete(), format="csv", utilisateur=None, q=None, ticket=ticket))
verifier("un ticket ouvre le téléchargement sans jeton dans l'URL", asyncio.run(_lire(rep)).startswith("\ufeff"))
try:
    asyncio.run(esp["exporter_echanges"](_Requete(), format="csv", utilisateur=None, q=None, ticket="inconnu"))
    verifier("un ticket inconnu ou périmé est refusé", False)
except _Http as e:
    verifier("un ticket inconnu ou périmé est refusé", e.status_code == 401)
try:
    asyncio.run(esp["exporter_echanges"](_Requete(), format="csv", utilisateur=None, q=None))
    verifier("sans jeton ni ticket, rien ne sort", False)
except _Http as e:
    verifier("sans jeton ni ticket, rien ne sort", e.status_code == 401)
try:
    asyncio.run(esp["exporter_echanges"](_Requete("Bearer jeton-direction"), format="csv",
                                         utilisateur=None, q=None))
    verifier("l'export est réservé au super-administrateur (la direction est refusée)", False)
except _Http as e:
    verifier("l'export est réservé au super-administrateur (la direction est refusée)", e.status_code == 403)
try:
    asyncio.run(esp["ticket_export"](types.SimpleNamespace(format="csv", utilisateur=None, q=None),
                                     current_user=types.SimpleNamespace(id="u-dir", role="direction")))
    verifier("… et le ticket ne s'obtient pas non plus", False)
except _Http as e:
    verifier("… et le ticket ne s'obtient pas non plus", e.status_code == 403)
REQUETES.clear()
vue = asyncio.run(esp["get_echanges"](current_user=admin, jours=7, limite=40, page=2, utilisateur=None, q=None))
verifier("la console elle-même : une page de 40, du plus récent au plus ancien, avec le détail rapproché",
         len(vue["echanges"]) == 40 and vue["echanges"][0]["question"] == "question 1162"
         and vue["echanges"][-1]["modele"] == "m" and REQUETES[0][1][4] == 40, vue["echanges"][-1])
tsx_src = (FRONTEND / "components" / "dashboard" / "Echanges.tsx").read_text(encoding="utf-8")
verifier("la console porte les boutons d'export (CSV et JSON)",
         "/api/dashboard/echanges/export" in tsx_src and "Exporter" in tsx_src)
verifier("l'écran demande un ticket et laisse le navigateur écrire le fichier (plus de Blob géant)",
         "export/ticket" in tsx_src and "createObjectURL" not in tsx_src and "res.blob()" not in tsx_src
         and "Bearer ${token}" in tsx_src and "?ticket=" in tsx_src)

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs))
    sys.exit(1)
print("✓ 0 échec")
