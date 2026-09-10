"""
Banc « L'ACCORD HUMAIN AVANT CHAQUE ACTION » (08/09 soir).

Règle de Noa : « sur toutes les actions — lecture du drive, modifier un
document, créer un document, rechercher sur Internet, etc. — il y a une
validation humaine à chaque fois. Vraiment à chaque fois. »

CE QUE CE BANC PROUVE (modules EXÉCUTÉS, câblage lu) : le réglage promeut
toute lecture en effet externe dans le CHAT et laisse les tâches planifiées
tranquilles ; la carte d'accord dit de quoi il s'agit ; après l'accord, le
résultat du geste revient au modèle sous la forme exacte de la boucle
d'actions et le tour ROUVRE (drapeaux à neuf, résultats acquis conservés,
horloge remise) ; un échec revient comme un résultat en erreur ; le routeur
renvoie l'assistant ; l'état, le prompt, l'écran et le chat sont câblés.
Tombe sur la version d'avant.
"""
import ast
import asyncio
import pathlib
import sys
import time
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
FRONTEND = BACKEND.parent / "frontend"
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def fonctions(chemin, noms, espace):
    src = chemin.read_text(encoding="utf-8")
    arbre = ast.parse(src)
    morceaux = [ast.get_source_segment(src, n) for n in arbre.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in noms]
    manquantes = [n for n in noms if not any(m.startswith(("def " + n, "async def " + n)) for m in morceaux)]
    if manquantes:
        return manquantes
    exec(compile("from __future__ import annotations\n" + "\n\n".join(morceaux), str(chemin), "exec"), espace)
    return []


print(f"\n═══ L'ACCORD HUMAIN AVANT CHAQUE ACTION — {BACKEND.parent}\n")

# ── 1. Le réglage et la promotion ──
print("— le réglage")
cfg = types.ModuleType("config")
cfg.settings = types.SimpleNamespace(validation_totale="active")
sys.modules["config"] = cfg
reglages = types.ModuleType("llm.reglages")
VALEUR = {"validation_totale": None}
reglages.valeur = lambda nom: VALEUR.get(nom)
sys.modules["llm"] = types.ModuleType("llm")
sys.modules["llm.reglages"] = reglages
src = BACKEND / "security" / "validation_totale.py"
verifier("le module `security/validation_totale.py` existe", src.exists())
if not src.exists():
    sys.exit(1)
vt = types.ModuleType("vt_double")
exec(compile(src.read_text(encoding="utf-8"), str(src), "exec"), vt.__dict__)
verifier("sans surcharge en base, le défaut du config fait foi (ici doublé à « active »)", vt.active() is True)
cfg.settings.validation_totale = "desactivee"
verifier("…et « desactivee » dans le config coupe le régime", vt.active() is False)
cfg.settings.validation_totale = "active"
VALEUR["validation_totale"] = "desactivee"
verifier("« desactivee » en base coupe le réglage", vt.active() is False)
VALEUR["validation_totale"] = "active"
verifier("dans le chat, une LECTURE est promue en effet externe", vt.effet_effectif("lecture", "chat") == "externe"
         and vt.effet_effectif("ecriture_interne", "resume") == "externe" and vt.effet_effectif("lecture", None) == "externe")
verifier("une tâche planifiée ou un webhook gardent l'effet déclaré",
         vt.effet_effectif("lecture", "schedule") == "lecture" and vt.effet_effectif("lecture", "webhook") == "lecture")
verifier("un effet externe reste externe, réglage ou pas", vt.effet_effectif("externe", "schedule") == "externe")
VALEUR["validation_totale"] = "desactivee"
verifier("réglage coupé : la lecture redevient immédiate", vt.effet_effectif("lecture", "chat") == "lecture")
verifier("…et le prompt ne reçoit rien", vt.consigne() == "")
VALEUR["validation_totale"] = "active"
verifier("la carte dit de quoi il s'agit (« Accord demandé avant chaque action » / « effet externe »)",
         vt.raison_d_accord("lire_mails", "lecture").startswith("Accord demandé avant chaque action : lire_mails")
         and vt.raison_d_accord("envoyer_email", "externe").startswith("Action à effet externe"))
verifier("le prompt dit : une action à la fois, une phrase qui dit pourquoi, ne redemande jamais",
         "UNE action à la fois" in vt.consigne() and "ne redemande" in vt.consigne())
cfgs = (BACKEND / "config.py").read_text(encoding="utf-8")
# LE DÉFAUT EST LE MÊME DES DEUX CÔTÉS DEPUIS LE 10/09. Il a divergé deux
# jours (« active » chez Duret, à la demande de Noa) ; il revient dessus après
# l'avoir vécu : « remets la même fréquence de validation humaine que
# Symbiose ». Le régime commun est donc l'ancien — accord sur les seuls effets
# externes —, et le mécanisme reste là, à un clic.
attendu = "desactivee"
verifier(f"config : le défaut de CE client est « {attendu} », et le catalogue des réglages le connaît",
         f'validation_totale: str = "{attendu}"' in cfgs
         and '"validation_totale",' in (BACKEND / "llm" / "reglages.py").read_text(encoding="utf-8"))

# ── 2. La reprise du tour après l'accord ──
print("— la reprise après l'accord")
anon = types.ModuleType("security.anonymizer")
anon.anonymizer = types.SimpleNamespace(anonymize_chunks=lambda textes, carte: (list(textes), dict(carte or {})))
sys.modules["security"] = types.ModuleType("security")
sys.modules["security.anonymizer"] = anon
esp1 = {"AgentState": dict, "asyncio": asyncio}
manque = fonctions(BACKEND / "agents" / "agent1.py", ["resultat_de_geste"], esp1)
verifier("`resultat_de_geste` existe dans agent1 (le masquage partagé)", not manque, manque)
ag1 = types.ModuleType("agents.agent1")
ag1.PLAFOND_RESULTAT, ag1.PLAFOND_RESULTAT_GENEREUX, ag1.RESULTATS_GENEREUX = 4000, 12000, frozenset({"lire_mails"})
ag1.resultat_de_geste = esp1.get("resultat_de_geste")
sys.modules["agents"] = types.ModuleType("agents")
sys.modules["agents.agent1"] = ag1
ex = types.ModuleType("skills.executor")
ex.expert_du_skill = lambda s: "agent2" if s == "nas_photos" else None
sys.modules["skills"] = types.ModuleType("skills")
sys.modules["skills.executor"] = ex
esp2 = {"AgentState": dict}
manque = fonctions(BACKEND / "agents" / "router.py", ["_reprise_du_tour", "_reouverture_du_tour", "route_apres_execution"], esp2)
verifier("`_reprise_du_tour` et `route_apres_execution` existent dans router.py", not manque, manque)
if not manque and not echecs[-1:] == ["`_reprise_du_tour` et `route_apres_execution` existent dans router.py"]:
    etat = {"tool_results": [{"skill": "ou_chercher", "ok": True}], "tool_iterations": 2, "entity_map": {"[PER_1]": "x"},
            "tools_finished": True, "redaction_forcee": True, "reprise_apres_accord": True, "tour_debut": time.time() - 500}
    action = {"skill": "lire_mails", "args": {"depuis": "7j"}}
    resultat = {"output": {"boite": "a@b", "nombre": 3, "bloc_ui": {"type": "table", "rows": [["x"]]}, "bloc_garanti": True}}
    s = asyncio.run(esp2["_reprise_du_tour"](etat, action, "empreinte-ok", resultat, None))
    verifier("le résultat du geste approuvé entre dans `tool_results` APRÈS ceux déjà acquis",
             len(s["tool_results"]) == 2 and s["tool_results"][0]["skill"] == "ou_chercher"
             and s["tool_results"][1]["skill"] == "lire_mails" and s["tool_results"][1]["ok"] is True)
    entree = s["tool_results"][1]
    verifier("…sous la forme exacte de la boucle (empreinte, args pour l'écran, résultat masqué, bloc garanti à part)",
             entree["payload_hash"] == "empreinte-ok" and entree["args"] == {"depuis": "7j"}
             and '"nombre": 3' in entree["resultat_masque"] and '"type": "table"' in (entree["bloc_garanti_masque"] or ""))
    verifier("le tour rouvre : drapeaux à neuf, itérations conservées, horloge remise, plus rien en attente",
             s["tools_finished"] is False and s["redaction_forcee"] is False and s["tool_iterations"] == 2
             and abs(s["tour_debut"] - time.time()) < 5 and s["pending_action"] is None
             and s["requires_validation"] is False and s["llm_response"] is None and s["final_response"] is None)
    verifier("la carte du fil est rendue (les jetons restent cohérents)", s["entity_map"] == {"[PER_1]": "x"})
    s2 = asyncio.run(esp2["_reprise_du_tour"](etat, {"skill": "nas_photos", "args": {}}, "e", None, "dossier introuvable"))
    verifier("un échec revient au modèle comme un résultat en erreur, sans lever",
             s2["tool_results"][-1]["ok"] is False and s2["tool_results"][-1]["resultat_masque"].startswith("ERREUR : dossier introuvable"))
    verifier("l'attribution d'expert suit le geste", s2.get("target_agent") == "agent2" and "target_agent" not in s)
    verifier("le routeur renvoie l'assistant après un geste approuvé sous ce régime, la fin sinon",
             esp2["route_apres_execution"]({"reprise_apres_accord": True}) == "agent1"
             and esp2["route_apres_execution"]({"plan_valide": ["a"]}) == "agent1"
             and esp2["route_apres_execution"]({}) == "fin")

# ── 3. Le câblage ──
print("— le câblage")
a1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("la boucle d'actions décide l'accord sur l'effet EFFECTIF (promu dans le chat)",
         'effet = _vt.effet_effectif(effet_declare, state.get("trigger_kind"))' in a1)
verifier("l'armement porte la raison lisible et le drapeau de reprise",
         '"validation_reason": _vt.raison_d_accord(action["skill"], effet_declare)' in a1
         and '"reprise_apres_accord": _vt.effet_effectif("lecture"' in a1)
verifier("la boucle d'actions et la reprise partagent le même masquage (`resultat_de_geste`)",
         a1.count("resultat_de_geste(") >= 2)
verifier("le prompt reçoit la consigne quand le réglage est actif",
         "from security.validation_totale import consigne as _consigne_accord" in a1)
r = (BACKEND / "agents" / "router.py").read_text(encoding="utf-8")
verifier("après l'accord, la reprise passe AVANT le rédacteur, et le plan garde sa branche",
         'if state.get("reprise_apres_accord") and action["skill"] != "proposer_plan":' in r
         and r.find("return await _reprise_du_tour(") < r.find("message = await _reponse_apres_action("))
verifier("l'état porte le drapeau, le runtime le remet à zéro à chaque tour",
         "reprise_apres_accord: Optional[bool]" in (BACKEND / "agents" / "state.py").read_text(encoding="utf-8")
         and '"reprise_apres_accord": False,' in (BACKEND / "agents" / "runtime.py").read_text(encoding="utf-8"))
tab = (FRONTEND / "components" / "settings" / "ClesApiTab.tsx").read_text(encoding="utf-8")
verifier("Paramètres → Clés API : la carte « Accord avant chaque action », un clic",
         "function ReglageValidationTotale(" in tab and "<ReglageValidationTotale" in tab
         and 'cle: "validation_totale"' in tab)
cw = (FRONTEND / "components" / "chat" / "ChatWindow.tsx").read_text(encoding="utf-8")
verifier("le chat enchaîne les accords : une nouvelle carte après la reprise garde le fil suspendu",
         'res.status === "pending_validation" && res.validation_id && String(res.validation_id) !== id' in cw
         and "bulleAccord(suivant)" in cw)

print(f"\n{'═' * 72}")
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs)); sys.exit(1)
print("✓ 0 échec")
