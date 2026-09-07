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
         '"gestes": gestes_du_tour(state)}' in runtime_src)

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
verifier("par le FIL : on prend les lignes du fil, et seulement elles",
         len(trouve) == 2 and exact is True
         and all(l["metadata"]["trigger_id"] == "fil-A" for l in trouve))

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

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs))
    sys.exit(1)
print("✓ 0 échec")
