"""
Banc du tour détaché — « aller dans Paramètres ne stoppe plus la demande ».

POURQUOI. Naviguer vers une autre section démonte le composant du chat ; le
démontage fermait la socket, et le serveur lisait cette fermeture comme un
abandon : tour annulé — pendant que le garde-fou anti-blocage du composant
relançait la même demande en double par POST, en aveugle. Le correctif est des
deux côtés : le frontend DÉTACHE un tour en vol (la connexion et ses closures
survivent dans le runtime de la SPA, l'écran se rebranche au retour), et le
serveur laisse un tour orphelin finir sa course — sa réponse est persistée
avant d'être annoncée, elle attend dans l'historique.

Contrôles statiques sur les fichiers livrés (pas de Node sur le poste de
contrôle, pas de navigateur) : ils prouvent que les branchements sont là,
pas que l'écran est beau — ça, c'est le test en conditions réelles de Noa.
"""
import pathlib
import sys

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
FRONTEND = BACKEND.parent / "frontend"

echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ TOUR DÉTACHÉ — {BACKEND.parent}\n")

# ── 1. Serveur : la déconnexion ne tue plus le tour ──────────────────
print("1. Serveur (routers/chat.py)")
chat = (BACKEND / "routers" / "chat.py").read_text(encoding="utf-8")

verifier("_dire existe (envoi tolérant à la socket partie)", "async def _dire(" in chat)

# Le corps de _derouler_tour ne doit plus toucher send_json en direct : chaque
# envoi passe par _dire, sinon une socket fermée fait dérailler le tour.
debut = chat.index("async def _derouler_tour(")
fin = chat.index("@router.websocket", debut)
corps = chat[debut:fin]
verifier("_derouler_tour n'appelle plus send_json en direct",
         "websocket.send_json" not in corps)

verifier("les tours orphelins sont ancrés (_TOURS_DETACHES)",
         "_TOURS_DETACHES" in chat and "add_done_callback(_TOURS_DETACHES.discard)" in chat)
verifier("un seul cancel() reste : celui du bouton stop",
         chat.count("en_cours.cancel()") == 1,
         f"{chat.count('en_cours.cancel()')} occurrence(s)")

# ── 2. Écran : le tour survit à la navigation ────────────────────────
print("\n2. Écran (chat/ChatWindow.tsx + lib/tourDetache.ts)")
module = FRONTEND / "lib" / "tourDetache.ts"
verifier("lib/tourDetache.ts existe", module.exists())
if module.exists():
    td = module.read_text(encoding="utf-8")
    for fn in ("detacherTour", "majTourDetache", "reprendreTour",
               "terminerTourDetache", "abonnerTour"):
        verifier(f"tourDetache exporte {fn}", f"export function {fn}(" in td)

cw = (FRONTEND / "components" / "chat" / "ChatWindow.tsx").read_text(encoding="utf-8")
verifier("ChatWindow importe le module de détachement", '@/lib/tourDetache' in cw)
verifier("le démontage DÉTACHE un tour en vol au lieu de fermer",
         "detacherTour({" in cw)
verifier("l'ancien démontage inconditionnel a disparu",
         "useEffect(() => () => { try { wsRef.current?.close() }" not in cw)
verifier("l'écran remonté re-adopte le tour (adopterTourDetache)",
         "const adopterTourDetache = " in cw and "adopterTourDetache(tid)" in cw)
verifier("les closures publient leur progression quand l'écran est absent",
         cw.count("majTourDetache(") >= 6,
         f"{cw.count('majTourDetache(')} publication(s)")
verifier("la fin d'un tour absent recharge l'historique (source de vérité)",
         "chargerHistorique(tid).catch(() => {})" in cw)

print(f"\n═══ {len(echecs)} échec(s)" + (f" : {', '.join(echecs)}" if echecs else " — tout passe"))
sys.exit(1 if echecs else 0)
