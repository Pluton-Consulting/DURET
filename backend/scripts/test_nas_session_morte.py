"""
Banc de la SESSION DU NAS MORTE (17/09, Duret) : DSM répond « session invalide
(SID introuvable) » — le serveur gardait ce SID partagé et refusait TOUS les
téléchargements (« Source distante devenue inaccessible ») jusqu'à l'expiration.
Exécuté sur le connecteur livré, DSM doublé ; sans réseau.

    python backend/scripts/test_nas_session_morte.py backend
"""
import asyncio, os, sys, types
from pathlib import Path

BACKEND = Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
sys.path.insert(0, str(BACKEND))
for k, v in {"DATABASE_URL": "postgresql://x:x@localhost/x", "JWT_SECRET_KEY": "x" * 40, "RESEND_API_KEY": "x",
             "SYNOLOGY_USER": "u", "SYNOLOGY_PASSWORD": "p"}.items():
    os.environ.setdefault(k, v)
ECHECS = []


def verifier(nom, condition, detail=""):
    print(("  ✓ " if condition else "  ✗ ") + nom + (f"  → {detail}" if detail and not condition else ""))
    if not condition:
        ECHECS.append(nom)


from ingestion.connectors import synology as syn


class Reponse:
    def __init__(self, json_=None, contenu=b"", type_="application/json"):
        self._json, self.content, self.headers = json_, contenu, {"content-type": type_}

    def raise_for_status(self):
        pass

    def json(self):
        return self._json


class FauxDSM:
    """Le SID « mort » est refusé (119) ; « neuf » est servi."""
    def __init__(self, login_ok=True):
        self.logins, self.login_ok, self.appels = 0, login_ok, []

    async def get(self, url, params=None, timeout=None):
        p = params or {}
        self.appels.append(p.get("method") or "download")
        if p.get("api") == "SYNO.API.Auth":
            self.logins += 1
            return Reponse({"success": True, "data": {"sid": "neuf"}} if self.login_ok else {"success": False, "error": {"code": 400}})
        sid = p.get("_sid") or ("neuf" if "_sid=neuf" in url else "mort")
        if sid != "neuf":
            return Reponse({"success": False, "error": {"code": 119}})
        if "Download" in url:
            return Reponse(None, b"OCTETS DU MODELE", "application/octet-stream")
        return Reponse({"success": True, "data": {"files": [{"name": "MEMOIRE.docx"}]}})


from nas import acces
partagee = types.SimpleNamespace(sid="mort")
acces._COURANTE = partagee


async def main():
    dsm = FauxDSM()
    octets, raison = await syn._telecharger_ou_raison(dsm, "https://nas", "mort", "/home/Drive/MEMOIRE.docx")
    verifier("un téléchargement refusé pour session morte rouvre la session et REUSSIT", octets == b"OCTETS DU MODELE" and raison == "" and dsm.logins == 1, f"{raison} / {dsm.logins}")
    verifier("la session PARTAGÉE reçoit le nouveau jeton (les appels suivants ne retombent pas dessus)", partagee.sid == "neuf")
    partagee.sid = "mort"; dsm = FauxDSM()
    data = await syn._appel(dsm, "https://nas", "SYNO.FileStation.List", "list", 2, sid="mort", folder_path="/home")
    verifier("un listage aussi se rattrape, une seule fois", data.get("files") and dsm.logins == 1 and dsm.appels.count("list") == 2)
    dsm = FauxDSM(login_ok=False)
    octets, raison = await syn._telecharger_ou_raison(dsm, "https://nas", "mort", "/x.docx")
    verifier("si la réouverture échoue, le refus est DIT avec sa raison, sans boucle", octets is None and "session" in raison and dsm.logins == 1, raison)

asyncio.run(main())
print(("✗ %d échec(s)" % len(ECHECS)) if ECHECS else "✓ 0 échec")
sys.exit(1 if ECHECS else 0)
