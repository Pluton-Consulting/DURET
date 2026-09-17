"""
Banc « UN TOUR QUI AVANCE N'EST PAS UNE BOUCLE, UNE LECTURE JUSTE N'EST PAS JETÉE »
— trace Langfuse du 17/09, fil d13ff0ac (Symbiose, super_admin), 27 appels.

Demande : ouvrir les factures BTF de 2026 une par une et en tirer les montants.
Le tour a trouvé les 15 fichiers, ouvert et lu les CINQ factures de 2026 (HT, TVA,
TTC, numéro, date : tout juste) — et la réponse est sortie bancale : montants
recopiés des noms de fichiers, « quatre autres fichiers n'ont pas pu être lus
(déjà listé) ».

LES DEUX CAUSES QUE CE BANC ENFERME :
  1. LA GARDE DU REJEU COUPAIT UN TOUR QUI AVANÇAIT. Le modèle revenait à la même
     recherche (« BTF ») entre deux factures pour savoir ce qu'il restait ; à la
     troisième consultation, « redemandée à l'identique sans que la demande
     avance » — alors que deux factures NEUVES avaient été lues entre chaque.
     La rédaction partait au rédacteur de secours, qui ne voit que des résultats
     compactés. → `_a_avance_depuis` : un geste NEUF et réussi depuis la dernière
     consultation = on ressert le résultat (rien n'est rejoué ni payé) ; sinon la
     coupe reste, et un plafond de retours borne même un tour qui avance.
  2. UNE LECTURE JUSTE ÉTAIT JETÉE. Le modèle de vision principal répond une fois
     sur deux « à plat » ({"total_ht": "133,40 €", …}) au lieu du format
     `observations` : « Relevé visuel structuré incomplet », et le secours
     relisait tout (jusqu'à 74 s par facture). Des valeurs courtes lues sur la
     page SONT un relevé ; une prose longue reste refusée.

Sans base, sans réseau, sans modèle : les fonctions sont extraites du code LIVRÉ
et exécutées sur les sorties EXACTES de la trace.
"""
import ast
import json
import pathlib
import re
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[1]
echecs = []


def verifier(nom, cond, detail=""):
    print(("  ✓ " if cond else "  ✗ ") + nom + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def fonction(source: str, nom: str) -> str:
    arbre = ast.parse(source)
    for n in ast.walk(arbre):
        if isinstance(n, ast.FunctionDef) and n.name == nom:
            return ast.get_source_segment(source, n)
    raise SystemExit(f"{nom} introuvable")


print("\n═══ UN TOUR QUI AVANCE —", BACKEND.parent)

# ── 1. LA GARDE DU REJEU ────────────────────────────────────────────────────
agent1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
esp = {}
exec(fonction(agent1, "_a_avance_depuis"), esp)
avance = esp["_a_avance_depuis"]


def r(h, ok=True):
    return {"skill": "x", "ok": ok, "payload_hash": h}


# Le tour de 10:31 → 10:37, tel que la trace le donne.
tour = [r("cherche"), r("lot"), r("ouvre1"), r("ouvre2"), r("lit1"), r("lit2"),
        r("ouvre3"), r("lit3"), r("cherche"), r("ouvre4"), r("lit4"), r("ouvre5"), r("lit5")]
print("\n── la garde du rejeu")
verifier("le tour exact de prod : revenir à la recherche après deux factures lues, c'est avancer",
         avance(tour, "cherche") is True)
verifier("rien de neuf depuis la dernière consultation : la coupe reste",
         avance([r("cherche"), r("ouvre1"), r("cherche")], "cherche") is False)
verifier("alterner deux appels DÉJÀ faits (A, B, A, B) n'est pas avancer",
         avance([r("A"), r("B"), r("A"), r("B")], "A") is False)
verifier("un geste neuf mais en ÉCHEC n'est pas une avancée",
         avance([r("cherche"), r("cherche"), r("ouvreX", ok=False)], "cherche") is False)
verifier("une empreinte jamais vue ne dit rien (pas d'occurrence, pas d'avancée)",
         avance([r("A")], "jamais") is False)
bloc = agent1[agent1.index("deja = [r for r in resultats if r.get(\"payload_hash\") == empreinte]"):]
bloc = bloc[:bloc.index("resultats.append({**deja[0]")]
verifier("la coupe ne tombe que si le tour n'a PAS avancé",
         "if len(deja) >= 2 and not _a_avance_depuis(resultats, empreinte):" in bloc)
verifier("même un tour qui avance a un plafond de retours, et il est dit",
         "if len(deja) >= MAX_RETOURS_MEME_ACTION:" in bloc
         and re.search(r"^MAX_RETOURS_MEME_ACTION = (\d+)", agent1, re.M) is not None
         and 3 <= int(re.search(r"^MAX_RETOURS_MEME_ACTION = (\d+)", agent1, re.M).group(1)) <= 10)
verifier("une action en ÉCHEC redemandée sort toujours à la première répétition",
         bloc.index('if not deja[0].get("ok"):') < bloc.index("_a_avance_depuis"))
verifier("le rejeu reste RESSERVI, jamais réexécuté",
         "(déjà exécuté à ce tour, son résultat est inchangé)" in agent1)

# ── 2. LE RELEVÉ VISUEL « À PLAT » ──────────────────────────────────────────
plans = (BACKEND / "skills" / "plans_dossier.py").read_text(encoding="utf-8")
esp2 = {"json": json, "re": re}
exec(fonction(plans, "_feuilles_lues"), esp2)
exec(fonction(plans, "verifier"), esp2)
relever = esp2["verifier"]


def accepte(texte):
    try:
        relever(texte)
        return True
    except Exception:  # noqa: BLE001 — un refus est une exception, quelle qu'elle soit
        return False


print("\n── le relevé visuel")
PLAT_1 = '```json\n{\n    "montant_ht": "570,40 €",\n    "numero_facture": "FAC00003549",\n    "date_facture": "31/05/2026"\n}\n```'
PLAT_2 = '```json\n{"numero_facture": "FAC00003406", "date_emission": "17/02/2026", "total_ht": "133,40 €", "tva": "26,68 €", "total_ttc": "160,08 €"}\n```'
IMBRIQUE = json.dumps({"numero_facture": "FAC00003503", "emetteur": {"nom": "SARL BOIENNE DE TRAVAUX FORESTIERS", "telephone": "0557706217"},
                       "lignes": [{"designation": "Broyage", "montant_ht": "3 046,50 €"}]}, ensure_ascii=False)
FORMAT = json.dumps({"observations": [{"element": "Total HT", "lecture": "372,60 €", "nature": "lue"}], "incertitudes": []}, ensure_ascii=False)
verifier("la sortie EXACTE de 10:32:07 (à plat, juste) est un relevé", accepte(PLAT_1))
verifier("la sortie EXACTE de 10:37:05 (à plat, HT/TVA/TTC) est un relevé", accepte(PLAT_2))
verifier("une lecture imbriquée (émetteur, lignes) est un relevé", accepte(IMBRIQUE))
verifier("le format demandé passe comme avant", accepte(FORMAT))
verifier("un livrable RÉDIGÉ à la place du relevé reste refusé (prose longue)",
         not accepte(json.dumps({"memoire": "Notre entreprise s'engage à " + "réaliser les travaux. " * 40}, ensure_ascii=False)))
verifier("un JSON vide reste refusé", not accepte("{}") and not accepte('{"total_ht": ""}'))
verifier("un format `observations` MAL formé reste refusé (la tolérance ne vaut que sans cette clé)",
         not accepte(json.dumps({"observations": "tout va bien", "incertitudes": []}))
         and not accepte(json.dumps({"observations": [{"element": "x", "lecture": "y", "nature": "devinee"}], "incertitudes": []})))
verifier("un relevé au bon format mais vide reste refusé",
         not accepte(json.dumps({"observations": [], "incertitudes": []})))
feuilles = esp2["_feuilles_lues"](json.loads(IMBRIQUE))
verifier("les libellés gardent leur chemin (« emetteur › nom »)",
         ("emetteur › nom", "SARL BOIENNE DE TRAVAUX FORESTIERS") in feuilles and len(feuilles) == 5)

# ── UN TOUR QUI AGIT RAISONNE (17/09) ────────────────────────────────────────
print("\n── le palier d'un tour qui agit")
routeur = agent1[agent1.index("decision = _json.loads(trouve.group(0)) if trouve else {}"):]
routeur = routeur[:routeur.index("async def recherche_node")]
verifier("des outils prévus par le routeur, ou une correction, envoient le tour au palier qui raisonne",
         "if familles or correction:" in routeur and 'effort = "complex"' in routeur.split("if familles or correction:")[1][:60])
verifier("la règle tombe APRÈS la lecture des familles et de la correction, avant le retour",
         routeur.index("familles_valides(brutes)") < routeur.index("if familles or correction:") < routeur.index('"llm_tier": effort'))
verifier("une conversation sans outil (familles vides) garde le modèle rapide — la règle ne s'applique qu'à une liste NON vide",
         "else [] if not brutes else familles_valides(brutes))" in routeur)

print("\n" + "═" * 70)
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs))
    sys.exit(1)
print("✓ 0 échec\n")
