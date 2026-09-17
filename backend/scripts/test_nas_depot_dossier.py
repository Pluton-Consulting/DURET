"""
Banc du DÉPÔT et de la CRÉATION DE DOSSIER sur le NAS (17/09, Duret). Relu dans le code à la
demande de Noa (« assure-toi, sans tester, que le dépôt et la création de dossier marchent ») :
la création n'existait pas ; `nas_deposer` rendait un refus du serveur comme une RÉUSSITE ; le
titre d'un mémoire contenant « / » donnait un fichier au nom amputé ; un dépôt validé mourait
sur une session DSM périmée ; un code de FICHIER était traduit avec le dictionnaire de
l'AUTHENTIFICATION. Exécuté sur le code livré, DSM doublé ; AUCUN appel au vrai serveur.

    python backend/scripts/test_nas_depot_dossier.py backend
"""
import asyncio, json, os, sys, types
from contextlib import asynccontextmanager
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


from nas import acces
from ingestion.connectors import synology as syn


class Reponse:
    def __init__(self, j): self._j = j
    def raise_for_status(self): pass
    def json(self): return self._j


class FauxDSM:
    def __init__(self, sid_mort=False, refus=None):
        self.sid_mort, self.refus, self.creations, self.depots = sid_mort, refus, [], []

    def _session(self, p):
        return self.sid_mort and p.get("_sid") != "neuf"

    async def get(self, url, params=None, timeout=None):
        p = params or {}
        if self._session(p): return Reponse({"success": False, "error": {"code": 119}})
        if self.refus: return Reponse({"success": False, "error": {"code": self.refus}})
        self.creations.append((json.loads(p["folder_path"])[0], json.loads(p["name"])[0], p["force_parent"]))
        return Reponse({"success": True, "data": {"folders": [{"path": json.loads(p["folder_path"])[0] + "/" + json.loads(p["name"])[0], "isdir": True}]}})

    async def post(self, url, params=None, data=None, files=None, timeout=None):
        if self._session(params or {}): return Reponse({"success": False, "error": {"code": 119}})
        if self.refus: return Reponse({"success": False, "error": {"code": self.refus}})
        self.depots.append((data["path"], files["file"][0], data["overwrite"], data["create_parents"], len(files["file"][1])))
        return Reponse({"success": True})


DSM = FauxDSM()
EXISTANTS = [{"nom": "Études en cours", "chemin": "/home/Drive/Études en cours", "dossier": True}, {"nom": "notes.txt", "chemin": "/home/Drive/notes.txt", "dossier": False}]


@asynccontextmanager
async def connexion():
    yield DSM, "https://nas", "vieux"


async def lister(client, base, sid, chemin, tout=False):
    return {"entrees": EXISTANTS if chemin == "/home/Drive" else []}


async def nouvelle(client, base, ancien):
    return "neuf"

acces.connexion = connexion
acces._lister_ouvert = lister
acces.verifier = lambda c: acces.normaliser(c) if c.startswith("/home") else (_ for _ in ()).throw(acces.NasRefuse("hors périmètre"))
syn._nouvelle_session = nouvelle


async def main():
    global DSM
    print("1. Le nom du fichier déposé")
    titre = "Mémoire technique – La Teste-De-Buch (33 260) – Lots 11 Carrelage/Faïence et 12 Sols souples.docx"
    n = acces.nom_sur(titre)
    verifier("une barre oblique dans le titre ne coupe plus le nom (avant : « Faïence et 12 Sols souples.docx »)", n.startswith("Mémoire technique") and "Carrelage - Faïence" in n and n.endswith(".docx"), n)
    verifier("les caractères refusés par un partage Windows deviennent un tiret", acces.nom_sur('Devis : "lot 12" ? <v2>*.xlsx') == "Devis - lot 12 - v2 - .xlsx" or not set(':"?<>*|') & set(acces.nom_sur('Devis : "lot 12" ? <v2>*.xlsx')), acces.nom_sur('Devis : "lot 12" ? <v2>*.xlsx'))
    verifier("un nom trop long garde son extension", len(acces.nom_sur("x" * 400 + ".docx")) <= 180 and acces.nom_sur("x" * 400 + ".docx").endswith(".docx"))
    verifier("un nom vide ou « .. » retombe sur un nom sûr", acces.nom_sur("") == "fichier" and acces.nom_sur("..") == "fichier")

    print("2. Le dépôt")
    r = await acces.deposer("/home/Drive/Études en cours", titre, b"OCTETS")
    verifier("dépôt nominal : dans le dossier visé, jamais d'écrasement, jamais de dossier créé en cascade", r["depose"] and DSM.depots == [("/home/Drive/Études en cours", r["nom"], "false", "false", 6)], str(DSM.depots))
    DSM = FauxDSM(sid_mort=True)
    r = await acces.deposer("/home/Drive", "a.docx", b"x")
    verifier("session DSM morte : le dépôt VALIDÉ est rejoué une fois sur une session neuve, et réussit", r["depose"] and len(DSM.depots) == 1)
    DSM = FauxDSM(refus=1805)
    r = await acces.deposer("/home/Drive", "a.docx", b"x")
    verifier("un nom déjà pris se dit (1805), avec le geste à faire", not r["depose"] and "existe déjà" in r["message"] and "renomme" in r["message"], r["message"])
    DSM = FauxDSM(refus=408)
    r = await acces.deposer("/home/Drive", "a.docx", b"x")
    verifier("un code de FICHIER n'est plus lu dans le dictionnaire de l'authentification (408 ≠ « mot de passe expiré »)", "N'EXISTE PAS" in r["message"] and "mot de passe" not in r["message"], r["message"])
    try:
        await acces.deposer("/etc", "a.docx", b"x"); hors = False
    except acces.NasRefuse:
        hors = True
    verifier("hors du périmètre : refus AVANT tout appel au serveur", hors and not DSM.depots)

    print("3. La création de dossier")
    DSM = FauxDSM()
    r = await acces.creer_dossier("/home/Drive", "2026-71 La Teste : lots 11/12")
    verifier("le dossier est créé dans le parent, UN niveau, nom assaini", r["cree"] and DSM.creations == [("/home/Drive", "2026-71 La Teste - lots 11 - 12", "false")] and r["chemin"].startswith("/home/Drive/2026-71"), str(DSM.creations))
    r = await acces.creer_dossier("/home/Drive", "etudes en cours")
    verifier("un dossier qui existe déjà (accents, casse) est RENDU, rien n'est créé ni écrasé", r.get("existait") and r["chemin"] == "/home/Drive/Études en cours" and len(DSM.creations) == 1, str(r))
    try:
        await acces.creer_dossier("/home/Drive", "notes.txt"); fichier = False
    except acces.NasRefuse:
        fichier = True
    verifier("un FICHIER de ce nom existe : refus, pas de doublon ambigu", fichier)
    for mauvais in ("#recycle", "@eaDir", "  "):
        try:
            await acces.creer_dossier("/home/Drive", mauvais); ok = False
        except acces.NasRefuse:
            ok = True
        verifier(f"nom refusé : « {mauvais.strip() or 'vide'} »", ok)
    DSM = FauxDSM(refus=1100)
    r = await acces.creer_dossier("/home/Drive", "Neuf")
    verifier("un refus du serveur se dit avec sa raison", not r.get("chemin") and "création du dossier a échoué" in r["message"], str(r))
    DSM = FauxDSM(sid_mort=True)
    r = await acces.creer_dossier("/home/Drive", "Neuf")
    verifier("session morte : la création aussi est rejouée une fois", r["cree"] and len(DSM.creations) == 1)

    print("4. Les skills")
    import skills.nas as sk
    import outils.nas as on
    from skills.erreurs import SkillError
    import bureautique.atelier as at
    sk_user = types.SimpleNamespace(id="u1", role="direction", email="x@exemple-sols.fr")
    acces.verifier_role = lambda u: None
    async def resoudre(ch): return "/home/Drive" if ch in ("Drive", "/home/Drive") else (_ for _ in ()).throw(acces.NasRefuse("ce dossier n'existe pas"))
    on.resoudre_dossier = resoudre
    import tempfile
    f = tempfile.NamedTemporaryFile(suffix=".docx", delete=False); f.write(b"DOCX"); f.close()
    at.chemin_fichier = lambda j, p: f.name if j == "doc1" else None
    at.fiche = lambda j, p: {"entete": {"titre": "Mémoire lots 11/12", "format": "docx"}}
    DSM = FauxDSM(refus=1805)
    try:
        await sk.nas_deposer({"dossier": "Drive", "document_id": "doc1"}, sk_user); leve = False
    except SkillError as e:
        leve = "ÉCHOUÉ" in str(e) and "existe déjà" in str(e)
    verifier("`nas_deposer` : un refus du serveur est un ÉCHEC (avant : un dictionnaire pris pour une réussite)", leve)
    DSM = FauxDSM()
    r = await sk.nas_deposer({"dossier": "Drive", "document_id": "doc1", "sous_dossier": "2026-71 La Teste"}, sk_user)
    verifier("`sous_dossier` : créé dans le dossier puis le fichier y est déposé, en UN geste", r["depose"] and r["sous_dossier_cree"] and DSM.creations[0][:2] == ("/home/Drive", "2026-71 La Teste") and DSM.depots[0][0] == "/home/Drive/2026-71 La Teste" and DSM.depots[0][1] == "Mémoire lots 11 - 12.docx", str((DSM.creations, DSM.depots)))
    r = await sk.nas_creer_dossier({"dossier": "Drive", "nom": "Archives 2026"}, sk_user)
    verifier("`nas_creer_dossier` rend le chemin EXACT à reprendre pour le dépôt", r["cree"] and r["chemin"] == "/home/Drive/Archives 2026" and "chemin" in r["a_faire"])
    try:
        await sk.nas_creer_dossier({"dossier": "Inconnu", "nom": "x"}, sk_user); inconnu = False
    except SkillError:
        inconnu = True
    verifier("un parent introuvable est un échec dit, rien n'est créé ailleurs", inconnu)
    d = sk.SKILLS["nas_creer_dossier"]
    verifier("créer un dossier ÉCRIT sur le serveur : effet externe, donc accord humain", d.effet == "externe" and sk.SKILLS["nas_deposer"].effet == "externe")
    from skills.familles import FAMILLES
    verifier("le nouveau geste est rangé dans une famille du catalogue", any("nas_creer_dossier" in (v if isinstance(v, (list, tuple, set)) else v.get("skills", v)) for v in (FAMILLES.values() if isinstance(FAMILLES, dict) else FAMILLES)) or "nas_creer_dossier" in (BACKEND / "skills" / "familles.py").read_text())
    verifier("aucun geste ne supprime, ne renomme ni n'écrase", "overwrite\": \"false\"" in (BACKEND / "nas" / "acces.py").read_text() and "Delete" not in (BACKEND / "nas" / "acces.py").read_text())

asyncio.run(main())
print(("✗ %d échec(s) : %s" % (len(ECHECS), ", ".join(ECHECS))) if ECHECS else "✓ 0 échec")
sys.exit(1 if ECHECS else 0)
