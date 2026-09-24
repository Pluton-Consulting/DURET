"""
Banc « LES MAILS SE LISTENT TOUS, ET SE CLASSENT » (24/09, Duret).

Règle de Noa : « qu'il y en ait un ou mille, la quantité ne doit même pas être une
question ». Conversation de Damien (23/09) : « affiche mes mails non lus » → 4 non lus
parmi les 25 derniers, alors que la boîte en comptait 36 ; « trie-les, classe-les » →
rien, aucun geste ne savait écrire dans la boîte.

CE QUE CE BANC PROUVE (modules EXÉCUTÉS contre un serveur IMAP doublé) : le filtre
« non lus » part au serveur (UNSEEN, `isRead eq false`, `is:unread`) ; le listage IMAP
rend une page de 50 et un curseur ; `deplacer` crée le dossier manquant et déplace par
MOVE, ou par COPY + Deleted + EXPUNGE sans MOVE, sans qu'un identifiant périmé arrête
les autres ; `classer_mails` lit les trois formes que le modèle écrit, déplace par
dossier et rend un tableau garanti ; l'aperçu d'accord montre le tableau mail → dossier ;
`lire_mails` inventorie sans période dès qu'on demande les non lus ; le geste est
dans la famille « mails ».
"""
import ast
import asyncio
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
sys.path.insert(0, str(BACKEND))
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ LES MAILS SE LISTENT TOUS, ET SE CLASSENT — {BACKEND}\n")

# ── Doublures : config, et le peu de mail.lecture que imap._fiche importe ─────
sys.modules["config"] = types.SimpleNamespace(settings=types.SimpleNamespace(
    mail_imap_user="boite@exemple-sols.fr", mail_imap_password="x", mail_imap_host="imap.exemple",
    mail_imap_dossier_envoyes="[Gmail]/Sent Mail", mail_smtp_host="smtp.exemple"))
lecture_doublee = types.ModuleType("mail.lecture")
lecture_doublee._apercu = lambda texte, n: str(texte or "")[:n]
lecture_doublee._memoriser = lambda ident, boite: "ref-" + ident.replace("|", "-")
lecture_doublee._qualifier = lambda exp: {"interne": False, "automatique": False}
lecture_doublee._texte_lisible = lambda t: t
lecture_doublee.MAX_APERCU = 10000
sys.modules["mail.lecture"] = lecture_doublee
from mail import imap  # noqa: E402

print("— Le filtre « non lus » part au serveur")
crit, _ = imap._criteres(None, None, None, non_lus=True)
verifier("IMAP : UNSEEN dans les critères", crit == "UNSEEN", crit)
crit, _ = imap._criteres(None, None, None)
verifier("IMAP : sans le filtre, ALL", crit == "ALL", crit)
src_lecture = (BACKEND / "mail" / "lecture.py").read_text(encoding="utf-8")
arbre = ast.parse(src_lecture)
espace = {"re": __import__("re"), "Optional": __import__("typing").Optional, "datetime": __import__("datetime").datetime}
for n in arbre.body:
    if (isinstance(n, ast.FunctionDef) and n.name in ("_params_outlook", "_requete_gmail", "_kql_echapper")) or \
       (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "SELECT_OUTLOOK"):
        exec(compile(ast.Module(body=[n], type_ignores=[]), "lecture", "exec"), espace)
p = espace["_params_outlook"](25, None, None, None, non_lus=True)
verifier("Outlook : `isRead eq false` dans le filtre", "isRead eq false" in p.get("$filter", ""), p)
p = espace["_params_outlook"](25, None, "devis", None, non_lus=True)
verifier("Outlook avec recherche : `isread:false` en KQL", "isread:false" in p.get("$search", ""), p)
verifier("Gmail : `is:unread`", "is:unread" in (espace["_requete_gmail"](None, None, None, non_lus=True) or ""))


# ── Un serveur IMAP doublé ───────────────────────────────────────────────────
class Client:
    def __init__(self, avec_move=True, dossiers=("INBOX", "[Gmail]/Sent Mail", "AFF 072-23")):
        self.capabilities = ("IMAP4rev1", "MOVE") if avec_move else ("IMAP4rev1",)
        self.dossiers = list(dossiers)
        self.messages = {"INBOX": {str(i): ("" if i % 3 else "\\Seen") for i in range(1, 121)}}
        self.journal = []
        self.selectionne = None

    def list(self):
        return "OK", [f'(\\HasNoChildren) "/" "{d}"'.encode() for d in self.dossiers]

    def create(self, nom):
        self.dossiers.append(nom.strip('"')); self.journal.append(("create", nom)); return "OK", [b""]

    def select(self, nom, readonly=False):
        self.selectionne = nom.strip('"'); return ("OK", [b"120"]) if self.selectionne in self.dossiers else ("NO", [b""])

    def response(self, code):
        return code, [b"777"]

    def uid(self, cmd, *args):
        cmd = cmd.upper()
        if cmd == "SEARCH":
            crit = " ".join(str(a) for a in args if a)
            boite = self.messages.get(self.selectionne, {})
            uids = [u for u, f in boite.items() if "UNSEEN" not in crit or "\\Seen" not in f]
            return "OK", [" ".join(uids).encode()]
        if cmd == "FETCH":
            uids = args[0].decode().split(",")
            sortie = []
            for u in uids:
                brut = (f"From: a@b.fr\r\nSubject: Objet {u}\r\nDate: Tue, 23 Sep 2026 10:00:00 +0000\r\n"
                        f"\r\nCorps {u}\r\n").encode()
                sortie.append((f"{u} (UID {u} FLAGS ({self.messages['INBOX'].get(u, '')}) RFC822.SIZE {len(brut)} BODY[]<0> {{{len(brut)}}}".encode(), brut))
                sortie.append(b")")
            return "OK", sortie
        if cmd in ("MOVE", "COPY"):
            uid, cible = args[0], args[1].strip('"')
            if uid not in self.messages.get(self.selectionne, {}):
                return "NO", [b"inconnu"]
            self.journal.append((cmd, uid, cible))
            self.messages.setdefault(cible, {})[uid] = self.messages[self.selectionne][uid]
            if cmd == "MOVE":
                del self.messages[self.selectionne][uid]
            return "OK", [b""]
        if cmd == "STORE":
            self.journal.append(("STORE", args[0], args[2])); return "OK", [b""]
        raise AssertionError(cmd)

    def expunge(self):
        self.journal.append(("expunge",)); return "OK", [b""]

    def logout(self):
        return "BYE", [b""]


print("\n— Le listage : une page de 50 et un curseur, les non lus seulement")
client = Client()
imap._connexion = lambda boite=None: client
fiches, total = imap.lister("boite@exemple-sols.fr", "INBOX", 50, non_lus=True)
verifier("UNSEEN côté serveur : 80 non lus sur 120", total == 80, total)
verifier("50 par page, du plus récent au plus ancien", len(fiches) == 50 and fiches[0]["objet"] == "Objet 119", len(fiches))
verifier("un curseur pour la suite", str(fiches[-1].get("curseur_suivant", "")).startswith("imap:777:"))
verifier("aucune fiche lue dans une page de non lus", all(not f["lu"] for f in fiches))

print("\n— Déplacer : MOVE, création du dossier, échec isolé")
client = Client()
imap._connexion = lambda boite=None: client
bilan = imap.deplacer("boite@exemple-sols.fr", ["INBOX|3", "INBOX|6", "INBOX|9999"], "AFF 084-24 BILLI")
verifier("le dossier manquant est créé", bilan["dossier_cree"] and ("create", '"AFF 084-24 BILLI"') in client.journal)
verifier("deux messages déplacés par MOVE", sorted(bilan["deplaces"]) == ["INBOX|3", "INBOX|6"]
         and ("MOVE", "3", "AFF 084-24 BILLI") in client.journal)
verifier("l'identifiant périmé échoue SEUL, avec sa raison", len(bilan["echecs"]) == 1 and bilan["echecs"][0][0] == "INBOX|9999")
verifier("les messages ont quitté la réception", "3" not in client.messages["INBOX"] and "3" in client.messages["AFF 084-24 BILLI"])
client = Client(avec_move=False)
imap._connexion = lambda boite=None: client
bilan = imap.deplacer("boite@exemple-sols.fr", ["INBOX|3"], "AFF 072-23")
verifier("sans MOVE : COPY + Deleted + EXPUNGE, dossier existant non recréé",
         bilan["deplaces"] == ["INBOX|3"] and not bilan["dossier_cree"]
         and ("COPY", "3", "AFF 072-23") in client.journal and ("STORE", "3", r"(\Deleted)") in client.journal
         and ("expunge",) in client.journal)
try:
    imap.deplacer("boite@exemple-sols.fr", ["INBOX|4"], "Nouveau", creer=False)
    verifier("`creer=False` : un dossier absent est refusé", False, "aucune erreur")
except RuntimeError as e:
    verifier("`creer=False` : un dossier absent est refusé", "introuvable" in str(e))


async def _coro(v):
    return v


print("\n— Le geste classer_mails")
sys.modules["mail.authorization"] = types.SimpleNamespace(verifier_acces=lambda u, b, envoi=False: _coro(b or "boite@exemple-sols.fr"))
lecture_doublee.fournisseur = lambda: "imap"
lecture_doublee._resoudre = lambda ref, boite: {"ref-a": "INBOX|3", "ref-b": "INBOX|6", "ref-c": "INBOX|30"}.get(ref)
sys.modules["mail.skills"] = types.SimpleNamespace(_boite_a_lire=lambda d, u: _coro(d.get("mailbox") or "boite@exemple-sols.fr"))
from skills import classement_mails as cm  # noqa: E402

c = cm.lire_affectations({"classement": [{"ref": "ref-a", "dossier": "AFF 072-23", "objet": "Situation n°3"},
                                         {"reference": "ref-b", "affaire": "AFF 084-24 BILLI"}, {"ref": "", "dossier": "x"}]})
verifier("liste de dictionnaires, alias compris, ligne vide écartée",
         [(x["ref"], x["dossier"]) for x in c] == [("ref-a", "AFF 072-23"), ("ref-b", "AFF 084-24 BILLI")])
c = cm.lire_affectations({"mails": {"AFF 072-23": ["ref-a", "ref-c"], "Divers": "ref-b"}})
verifier("dictionnaire dossier → refs", len(c) == 3 and (c[2]["ref"], c[2]["dossier"]) == ("ref-b", "Divers"))
c = cm.lire_affectations({"classement": [["ref-a", "AFF 072-23"]]})
verifier("liste de paires", bool(c) and c[0]["dossier"] == "AFF 072-23")
bloc = cm.bloc_du_classement({"classement": [{"ref": "ref-a", "dossier": "AFF 072-23", "objet": "Situation n°3"},
                                             {"ref": "ref-b", "dossier": "AFF 084-24 BILLI"}]})
verifier("l'aperçu d'accord : un tableau mail → dossier, l'objet quand il est donné",
         bloc["type"] == "table" and bloc["rows"] == [["Situation n°3", "AFF 072-23"], ["ref-b", "AFF 084-24 BILLI"]]
         and "2 dossier(s)" in bloc["titre"])
client = Client()
imap._connexion = lambda boite=None: client
utilisateur = types.SimpleNamespace(id="u1", role="direction", email="d@exemple-sols.fr")
r = asyncio.run(cm.classer_mails({"classement": [
    {"ref": "ref-a", "dossier": "AFF 072-23", "objet": "Situation n°3"},
    {"ref": "ref-b", "dossier": "AFF 084-24 BILLI", "objet": "PV réception"},
    {"ref": "ref-c", "dossier": "AFF 084-24 BILLI"},
    {"ref": "ref-inconnue", "dossier": "Divers"}]}, utilisateur))
verifier("trois mails rangés dans deux dossiers, un créé", r["deplaces"] == 3 and r["dossiers_crees"] == ["AFF 084-24 BILLI"], r)
verifier("la référence inconnue est un échec DIT, pas une panne", r["echecs"] == 1
         and any("inconnue" in ligne[2] for ligne in r["bloc_ui"][0]["rows"]))
verifier("tableau garanti + phrase pour la personne", r.get("bloc_garanti") and r["bloc_ui"][0]["type"] == "table"
         and "3 mail(s) rangé(s)" in r["message_final"])
try:
    asyncio.run(cm.classer_mails({"classement": []}, utilisateur))
    verifier("sans classement : refus qui explique la forme attendue", False)
except Exception as e:  # noqa: BLE001
    verifier("sans classement : refus qui explique la forme attendue", "ref" in str(e) and "dossier" in str(e))
lecture_doublee.fournisseur = lambda: "outlook"
try:
    asyncio.run(cm.classer_mails({"classement": [{"ref": "ref-a", "dossier": "X"}]}, utilisateur))
    verifier("hors IMAP : refus dit, rien de déplacé", False)
except Exception as e:  # noqa: BLE001
    verifier("hors IMAP : refus dit, rien de déplacé", "IMAP" in str(e))

print("\n— Un mail qu'on ne sait pas ranger se dit, il n'est pas déplacé")
c = cm.lire_affectations({"classement": [{"ref": "ref-a", "dossier": "AFF 072-23"},
                                         {"ref": "ref-b", "a_trancher": True, "raison": "aucun chantier nommé"},
                                         {"ref": "ref-c", "dossier": "?"}]})
verifier("`a_trancher` ou un dossier « ? » gardent le mail dans la liste, sans dossier",
         [(x["ref"], x["dossier"], x["a_trancher"]) for x in c] == [("ref-a", "AFF 072-23", False), ("ref-b", "", True), ("ref-c", "", True)])
bloc = cm.bloc_du_classement({"classement": [{"ref": "ref-a", "dossier": "AFF 072-23", "objet": "Situation"},
                                             {"ref": "ref-b", "a_trancher": True, "raison": "aucun chantier nommé", "objet": "Pub"}]})
verifier("l'aperçu d'accord montre « À TRANCHER — raison »", bloc["rows"][1] == ["Pub", "À TRANCHER — aucun chantier nommé"]
         and "1 à trancher" in bloc["titre"])
lecture_doublee.fournisseur = lambda: "imap"
client = Client()
imap._connexion = lambda boite=None: client
r = asyncio.run(cm.classer_mails({"classement": [{"ref": "ref-a", "dossier": "AFF 072-23", "objet": "Situation"},
                                                 {"ref": "ref-b", "a_trancher": True, "raison": "aucun chantier nommé", "objet": "Pub"}]}, utilisateur))
verifier("le mail à trancher n'est pas déplacé, il est dit dans le résultat",
         r["deplaces"] == 1 and r["a_trancher"] == 1 and "1 laissé(s) à trancher" in r["message_final"]
         and "6" in client.messages["INBOX"] and any("À TRANCHER" in l[2] for l in r["bloc_ui"][0]["rows"]))
verifier("lire_mails : une période sans nombre demandé = inventaire complet",
         "bool(_periode and not data.get(\"limite\") and not recherche and not avant)" in (BACKEND / "mail" / "skills.py").read_text(encoding="utf-8"))

print("\n— Un « onglet » Gmail par IMAP : la catégorie se pose en copiant, le mail reste en réception")
lecture_doublee.fournisseur = lambda: "imap"
lecture_doublee._controler_identifiant = lambda ident, autorises: None
client = Client()
imap._connexion = lambda boite=None: client
imap.boite_unique = lambda: "boite@exemple-sols.fr"
from skills import gestion_mail as gm  # noqa: E402
r = gm._imap_modifier("INBOX|3", {"ajouter_categories": ["_Nathalie"]}, None)
verifier("catégorie posée = COPY dans le dossier du même nom, créé s'il manque",
         r.get("categories_ajoutees") == ["_Nathalie"] and ("COPY", "3", "_Nathalie") in client.journal
         and ("create", '"_Nathalie"') in client.journal and ("expunge",) not in client.journal)
verifier("le mail reste dans la réception", "3" in client.messages["INBOX"] and "3" in client.messages["_Nathalie"])
try:
    gm._imap_modifier("INBOX|3", {"retirer_categories": ["_Nathalie"]}, None)
    verifier("retirer une catégorie par IMAP : refus dit", False)
except ValueError as e:
    verifier("retirer une catégorie par IMAP : refus dit", "Retirer" in str(e))
client = Client()
imap._connexion = lambda boite=None: client
bilan = imap.deplacer("boite@exemple-sols.fr", ["INBOX|6"], "_Eric", copier=True)
verifier("classer_mails garder_en_reception : copie sans expunge", bilan["deplaces"] == ["INBOX|6"]
         and "6" in client.messages["INBOX"] and ("expunge",) not in client.journal)

print("\n— Le socle autour du geste")
src_skills = (BACKEND / "mail" / "skills.py").read_text(encoding="utf-8")
verifier("lire_mails : `non_lus` compris, inventaire sans période dès qu'on les demande",
         'data.get("non_lus")' in src_skills and "exhaustif = exhaustif or non_lus" in src_skills
         and "(depuis or non_lus)" in src_skills)
verifier("lire_mails : jusqu'à 1 000 messages par pages de 50",
         "MAX_INVENTAIRE_MAILS = 1000" in src_skills and "PAGE_INVENTAIRE = 50" in src_skills)
verifier("lire_boite transmet `non_lus` aux trois messageries", src_lecture.count("non_lus=non_lus") >= 3)
verifier("famille « mails » : le geste y est", '"classer_mails"' in (BACKEND / "skills" / "familles.py").read_text(encoding="utf-8"))
verifier("agent1 : l'aperçu d'accord montre le classement",
         'skill == "classer_mails"' in (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8"))
verifier("effet externe : rien ne bouge sans accord", cm.SKILLS["classer_mails"].effet == "externe")

print(f"\n{'✅ tout passe' if not echecs else f'❌ {len(echecs)} échec(s)'}\n")
sys.exit(1 if echecs else 0)
