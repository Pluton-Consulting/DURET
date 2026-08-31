"""
Banc de la session expirée — « Erreur : Token invalide » ne se dit plus ainsi.

POURQUOI. Le 31/08 au soir, Noa : « il vient de me dire Erreur ; Token invalide ».
Le JWT du backend vit 8 h (`jwt_expire_hours`) ; l'onglet du chat, lui, garde la
session NextAuth en mémoire et continue d'envoyer le vieux jeton. PyJWT lève
`ExpiredSignatureError`, que `auth/dependencies.py` repliait avec toutes les
autres erreurs en « Token invalide » — un mot de tuyauterie, sans dire quoi
faire, et le chat l'affichait tel quel sans renvoyer à la connexion.

CE QUE CE BANC PROUVE, sans serveur : le backend distingue l'expiration (et le
dit en français, sans « Token »), le chat traite le 401 en renvoyant à /login,
et le ticket WebSocket dit la même chose.
"""
import pathlib
import re
import sys

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
FRONTEND = BACKEND.parent / "frontend"
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ SESSION EXPIRÉE — {BACKEND.parent}\n")
dep = (BACKEND / "auth" / "dependencies.py").read_text(encoding="utf-8")
verifier("l'expiration est attrapée AVANT l'erreur générique",
         dep.find("except ExpiredSignatureError") != -1 and dep.find("except ExpiredSignatureError") < dep.find("except PyJWTError"))
verifier("elle se dit en français et dit quoi faire", "Session expirée : reconnectez-vous." in dep)
verifier("plus aucun « Token invalide » à l'écran", "Token invalide" not in dep)
verifier("un jeton forgé ou sans sujet reste refusé", dep.count("Session invalide : reconnectez-vous.") == 2)

chat = (FRONTEND / "components" / "chat" / "ChatWindow.tsx").read_text(encoding="utf-8")
verifier("le chat traite le 401 : message humain + retour à la connexion",
         re.search(r"err\?\.status === 401.*?session expirée.*?window\.location\.assign\(\"/login\"\)", chat, re.S) is not None)
ws = (FRONTEND / "lib" / "ws.ts").read_text(encoding="utf-8")
verifier("le ticket WebSocket refusé en 401 porte le même message et son statut",
         "ticketRes.status === 401" in ws and "session expirée" in ws and "e.status = ticketRes.status" in ws)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
