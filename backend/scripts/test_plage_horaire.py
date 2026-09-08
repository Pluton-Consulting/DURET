"""
Banc « LA PLAGE HORAIRE SE LIT À L'HEURE DE L'ENTREPRISE » (08/09).

Relevé de Noa (Symbiose) : « une employée a essayé de se connecter dans les
heures bloquées, ça n'a pas marché ; là elle essaie dans les bonnes heures,
c'est toujours bloqué ». Les deux gardes (`routers/chat.py::_check_schedule`,
`agents/router.py::check_schedule_node`) comparaient la plage à
`datetime.now()` — l'heure du CONTENEUR, en UTC (aucun fuseau dans Docker).
À 8 h 12 à Paris, le serveur lisait 6 h 12 : refus, et le message disait
« Accès refusé à 6h12 » à quelqu'un dont la pendule marquait 8 h 12. Et à
l'écran, ce 403 passait pour un fil périmé : fil oublié, rejoué, second refus.

CE QUE CE BANC PROUVE : `security/horaires.py` (EXÉCUTÉ) décide à l'heure
locale, quel que soit le fuseau de la machine ; les deux gardes passent par
lui et plus par `datetime.now()` ; le refus dit l'heure locale ; l'écran
affiche le refus de plage au lieu de rejouer. Tombe sur la version d'avant.
"""
import pathlib
import sys
import types
from datetime import datetime, timezone

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
FRONTEND = BACKEND.parent / "frontend"
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ LA PLAGE HORAIRE À L'HEURE DE L'ENTREPRISE — {BACKEND.parent}\n")

chemin = BACKEND / "security" / "horaires.py"
verifier("security/horaires.py existe (la seule horloge de la plage)", chemin.exists())
if chemin.exists():
    sys.modules["config"] = types.ModuleType("config")
    sys.modules["config"].settings = types.SimpleNamespace(fuseau_horaire="Europe/Paris")
    mod = types.ModuleType("security.horaires")
    exec(compile(chemin.read_text(encoding="utf-8"), str(chemin), "exec"), mod.__dict__)

    # Le cas exact : 06:12 UTC un 8 septembre = 08:12 à Paris (UTC+2).
    ok, local = mod.dans_la_plage(8, 18, datetime(2026, 9, 8, 6, 12, tzinfo=timezone.utc))
    verifier("06:12 UTC le 8 septembre = 08:12 à Paris → DANS la plage 8h–18h", ok and local.hour == 8 and local.minute == 12, (ok, local))
    ok, local = mod.dans_la_plage(8, 18, datetime(2026, 9, 8, 16, 30, tzinfo=timezone.utc))
    verifier("16:30 UTC = 18:30 à Paris → HORS plage (avant, le soir restait ouvert jusqu'à 20 h)", not ok and local.hour == 18)
    ok, local = mod.dans_la_plage(8, 18, datetime(2026, 9, 8, 6, 12))
    verifier("un instant NAÏF (ce que rend datetime.now() dans le conteneur) est pris pour de l'UTC", ok and local.hour == 8)
    ok, local = mod.dans_la_plage(8, 18, datetime(2026, 1, 8, 7, 30, tzinfo=timezone.utc))
    verifier("en hiver (UTC+1), 07:30 UTC = 08:30 à Paris → dans la plage", ok and local.hour == 8)
    verifier("le refus dit l'heure LOCALE et la plage, et commence par « Accès refusé »",
             mod.message_refus(local, 8, 18).startswith("Accès refusé à 8h30") and "8h00–18h00" in mod.message_refus(local, 8, 18))

    sys.modules["config"].settings = types.SimpleNamespace(fuseau_horaire="Pacific/Noumea")
    ok, local = mod.dans_la_plage(8, 18, datetime(2026, 9, 8, 6, 12, tzinfo=timezone.utc))
    verifier("le fuseau est un RÉGLAGE (Nouméa, UTC+11 : 06:12 UTC = 17:12 → dans la plage)", ok and local.hour == 17)
    sys.modules["config"].settings = types.SimpleNamespace(fuseau_horaire="Europe/Nulle-Part")
    ok, local = mod.dans_la_plage(8, 18, datetime(2026, 9, 8, 6, 12, tzinfo=timezone.utc))
    verifier("un fuseau inconnu retombe sur Paris, jamais sur UTC", ok and local.hour == 8)
    del sys.modules["config"]
    ok, local = mod.dans_la_plage(8, 18, datetime(2026, 9, 8, 6, 12, tzinfo=timezone.utc))
    verifier("sans config du tout (script, banc) : Paris", ok and local.hour == 8)

chat = (BACKEND / "routers" / "chat.py").read_text(encoding="utf-8")
routeur = (BACKEND / "agents" / "router.py").read_text(encoding="utf-8")
garde = chat[chat.find("async def _check_schedule"):chat.find("async def _check_quota")]
noeud = routeur[routeur.find("async def check_schedule_node"):routeur.find("async def dispatch_agent1")]
verifier("`_check_schedule` (routers/chat.py) décide par `dans_la_plage`, plus par datetime.now()",
         "dans_la_plage(start_hour, end_hour)" in garde and "datetime.datetime.now()" not in garde)
verifier("le nœud `check_schedule` (agents/router.py) aussi",
         "dans_la_plage(start_hour, end_hour)" in noeud and "datetime.datetime.now()" not in noeud)
verifier("les deux refus passent par `message_refus` (heure locale dite)",
         "message_refus(local, start_hour, end_hour)" in garde and "message_refus(local, start_hour, end_hour)" in noeud)
config = (BACKEND / "config.py").read_text(encoding="utf-8")
verifier("le réglage `fuseau_horaire` existe, défaut Europe/Paris", 'fuseau_horaire: str = "Europe/Paris"' in config)

ecran = (FRONTEND / "components" / "chat" / "ChatWindow.tsx").read_text(encoding="utf-8")
i = ecran.find("if (e?.status !== 403) throw e")
verifier("à l'écran, un 403 « Accès refusé » est AFFICHÉ, pas pris pour un fil périmé à rejouer",
         i > 0 and "refus" in ecran[i:i + 400] and ecran.find("forgetThread()", i) > ecran.find("throw e", i + 10))

print(f"\n{'═' * 72}")
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs))
    sys.exit(1)
print("✓ 0 échec")
