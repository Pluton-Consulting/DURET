"""
Banc « TOUT CE QU'ON FAIT AU CHAT SE FAIT EN FILE » — et les trois relevés du 04/09.

LES DEMANDES (Noa, 04/09) : « Symbiose me dit que les pièces jointes ne peuvent
pas rejoindre la file d'attente ; tout ce qu'on fait en chat classique doit se
faire en file, c'est pareil » ; puis, sur l'export Langfuse : « il a tourné en
boucle sans jamais s'arrêter sur "j'analyse votre demande" » (13 minutes, 27
appels, un Excel que personne n'a demandé), « les grands tableaux sont vraiment
trop grands ».

CE QUE CE BANC PROUVE (contrat, sans navigateur ni base) :
  · la pièce jointe voyage en file : reçue par la route, rangée sur le disque,
    relue à l'exécution, lue par le MÊME lecteur que le chat, et le tableau
    complet (`@tableau`) l'accompagne ;
  · la voie WebSocket du chat transmet le tableau joint (elle ne le faisait
    pas : `@tableau` ne marchait que par le repli POST) ;
  · un tour a un TEMPS IMPARTI, après quoi la rédaction est forcée ;
  · le tableau joint est RAPPELÉ à chaque tour tant qu'il existe ;
  · les tableaux d'écran défilent au-delà d'une hauteur raisonnable.
"""
import pathlib
import sys

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
FRONTEND = BACKEND.parent / "frontend"
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ LA FILE, COMME LE CHAT — {BACKEND.parent}\n")
file_py = (BACKEND / "routers" / "file_attente.py").read_text(encoding="utf-8")
runtime = (BACKEND / "agents" / "runtime.py").read_text(encoding="utf-8")
agent1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
chat_tsx = (FRONTEND / "components" / "chat" / "ChatWindow.tsx").read_text(encoding="utf-8")

# ── 1. LA PIÈCE JOINTE EN FILE ────────────────────────────────────────────
verifier("la route de mise en file accepte une pièce jointe",
         "attachment_b64: Optional[str] = None" in file_py and "attachment_name" in file_py)
verifier("le fichier est rangé sur le DISQUE (volume des documents), pas en base",
         "_ranger_piece(tache_id, body)" in file_py and '/ "file"' in file_py
         and "attachment_b64" not in file_py.split("INSERT INTO taches_differees")[1][:300])
verifier("il est relu à l'exécution et lu par le MÊME lecteur que le chat",
         "_reprendre_piece(tache_id)" in file_py and "from routers.chat import _piece_jointe" in file_py)
verifier("le tour de la file reçoit la pièce ET le tableau complet (@tableau)",
         "has_attachment=bool(piece)" in file_py and "attachment_rows=tableau_joint" in file_py)
verifier("le fichier ne dort pas sur le disque une fois la tâche finie",
         "_oublier_piece(tache_id)" in file_py)
verifier("l'écran n'oppose plus de refus : la pièce part avec la demande",
         "ne peuvent pas rejoindre la file d'attente" not in chat_tsx
         and "lancerEnFile(text, true, piece)" in chat_tsx
         and "attachment_b64: piece.b64" in chat_tsx)
verifier("les replis POST → file gardent la pièce du message d'origine",
         chat_tsx.count("lancerEnFile(text, false, piece)") == 2)

# ── 2. LA VOIE WEBSOCKET TRANSMET LE TABLEAU ──────────────────────────────
verifier("`stream_turn` accepte et transmet `attachment_rows`",
         "attachment_rows: Optional[dict] = None) -> AsyncIterator[dict]:" in runtime
         and runtime.count("attachment_rows=attachment_rows") >= 2)

# ── 3. LE TEMPS IMPARTI D'UN TOUR ─────────────────────────────────────────
verifier("un tour a un temps imparti (8 minutes)", "TOUR_DUREE_MAX_S = 8 * 60" in agent1)
verifier("l'heure de départ est posée à chaque tour", 'etat["tour_debut"] = time.time()' in runtime)
verifier("passé le délai, la boucle sort et la rédaction est forcée, en disant ce qui n'a pas été fait",
         "> TOUR_DUREE_MAX_S" in agent1 and "dire ce qui n'a PAS été fait" in agent1)
verifier("le délai ne mord qu'après quelques actions (une première action lente n'est pas une boucle)",
         "iteration > 3 and" in agent1)

# ── 4. LE TABLEAU JOINT NE S'OUBLIE PAS ───────────────────────────────────
verifier("le tableau joint est rappelé à chaque tour tant qu'il existe",
         "TABLEAU JOINT À CETTE CONVERSATION" in agent1 and 'state.get("dernier_tableau")' in agent1)
verifier("le rappel dit de ne PAS chercher la liste ailleurs (liste_clients rendait 478 clients pour 95)",
         "ne cherche pas cette liste ailleurs" in agent1)

# ── 5. LES TABLEAUX DÉFILENT ─────────────────────────────────────────────
for nom in ("SimpleTable", "StatusTable", "KeyValueTable"):
    src = (FRONTEND / "components" / "blocks" / "tables" / f"{nom}.tsx").read_text(encoding="utf-8")
    verifier(f"{nom} défile au-delà d'une hauteur d'écran raisonnable",
             'maxHeight: "min(70vh, 560px)"' in src and 'overflow: "auto"' in src)
simple = (FRONTEND / "components" / "blocks" / "tables" / "SimpleTable.tsx").read_text(encoding="utf-8")
verifier("l'en-tête du tableau reste visible pendant le défilement",
         'position: "sticky"' in simple)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
