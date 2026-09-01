"""
Banc « le logo dans le mail de connexion » — 01/09 nuit.

Demande de Noa : « dans le contenu du mail de vérification notamment, ajoute le
logo ». L'en-tête ne portait qu'une pastille dessinée en cellules de tableau —
un carré de couleur avec une lettre, choisi parce qu'aucun client de messagerie
ne rend le SVG et qu'une image distante est bloquée par défaut.

LA TROISIÈME VOIE, celle qui marche vraiment : une pièce jointe « inline »,
référencée par `cid:` dans le HTML. L'image voyage AVEC le message, donc rien
n'est bloqué et rien n'a besoin d'être joignable — ce qui compte ici, le site
vivant derrière le VPN.

CE QUE CE BANC EXIGE. Le corps envoyé à Resend porte l'image quand elle existe,
le HTML la référence par le MÊME identifiant, et — le contrôle qui compte —
l'absence du fichier ne casse rien : on retombe sur la pastille, sans cadre vide
ni exception.
"""
import ast
import base64
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def extraire(chemin, noms, espace=None):
    espace = espace if espace is not None else {}
    arbre = ast.parse(pathlib.Path(chemin).read_text(encoding="utf-8"))
    gardes = []
    for n in arbre.body:
        if isinstance(n, ast.ImportFrom) and n.module == "__future__":
            gardes.append(n)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            continue
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in noms:
            gardes.append(n)
        elif isinstance(n, (ast.Assign, ast.AnnAssign)):
            cibles = n.targets if isinstance(n, ast.Assign) else [n.target]
            if any(isinstance(c, ast.Name) and c.id in noms for c in cibles):
                gardes.append(n)
    exec(compile(ast.Module(body=gardes, type_ignores=[]), str(chemin), "exec"), espace)
    manquants = [x for x in noms if x not in espace]
    assert not manquants, f"absent du module livré : {manquants}"
    return espace


print(f"\n═══ LE LOGO DANS LE MAIL — {BACKEND.resolve().parent}\n")

# ── 1. Le corps envoyé à Resend, EXÉCUTÉ ─────────────────────────────────
env = extraire(BACKEND / "emails" / "envoi.py", {"_corps"},
               {"_expediteur": lambda: "Symbiose <a@b.fr>", "base64": base64})
corps = env["_corps"]

nu = corps("qui@x.fr", "Connexion", "<html>bonjour</html>")
verifier("sans image, le corps est celui d'avant — aucune clé parasite",
         set(nu) == {"from", "to", "subject", "html"}, str(sorted(nu)))

OCTETS = b"\x89PNG\r\n\x1a\nfaux"
avec = corps("qui@x.fr", "Connexion", '<img src="cid:logo-marque">',
             [{"content_id": "logo-marque", "nom": "logo.png",
               "mime": "image/png", "octets": OCTETS}])
verifier("avec image, une pièce jointe part", len(avec.get("attachments", [])) == 1)
piece = avec["attachments"][0]
verifier("le contenu est du base64 décodable à l'identique",
         base64.b64decode(piece["content"]) == OCTETS)
verifier("elle porte un content_id — c'est lui qui la met DANS le corps",
         piece["content_id"] == "logo-marque")
verifier("le HTML cite le MÊME identifiant, sans chevrons",
         "cid:" + piece["content_id"] in avec["html"])
verifier("une image sans octets est ignorée, elle ne part pas vide",
         "attachments" not in corps("a@b.fr", "o", "h",
                                    [{"content_id": "x", "octets": b""}]))

# ── 2. Le repli : sans fichier, la pastille — et rien ne casse ───────────
faux_marque = types.ModuleType("emails.marque")
faux_marque.MARQUE = {"logo": "<table>PASTILLE</table>", "nom": "Symbiose Paysage",
                      "fond": "#0F1F0E", "baseline": "#9DB04F",
                      "couleur": "#1D9E75"}
faux_marque.LOGO_CONTENT_ID = "logo-marque"
paquet = types.ModuleType("emails")
paquet.__path__ = []
sys.modules.setdefault("emails", paquet)
sys.modules["emails.marque"] = faux_marque

espace = {"MARQUE": faux_marque.MARQUE, "LOGO_CONTENT_ID": "logo-marque"}
faux_marque.logo_image = lambda: None
espace["logo_image"] = faux_marque.logo_image
extraire(BACKEND / "emails" / "gabarit.py", {"_logo_html"}, espace)
verifier("SANS fichier de logo : la pastille dessinée, jamais un cadre vide",
         espace["_logo_html"]() == "<table>PASTILLE</table>")

espace["logo_image"] = lambda: {"content_id": "logo-marque", "octets": b"x"}
verifier("AVEC fichier : une balise img qui pointe le cid",
         'src="cid:logo-marque"' in espace["_logo_html"]())
verifier("elle porte une hauteur en attribut ET en style "
         "(les vieux clients ignorent l'un ou l'autre)",
         'height="30"' in espace["_logo_html"]()
         and "height:30px" in espace["_logo_html"]())
verifier("la largeur est libre : le logotype est un MOT, pas un carré",
         "width:auto" in espace["_logo_html"]())
verifier("et un texte de remplacement, pour qui n'affiche pas les images",
         'alt="Symbiose Paysage"' in espace["_logo_html"]())

# ── 2 bis. L'EN-TÊTE prend la forme que le logo permet ──────────────────
espace2 = {"MARQUE": faux_marque.MARQUE, "LOGO_CONTENT_ID": "logo-marque",
           "LOGO_PORTE_LE_NOM": True,
           "_BORDURE": "#E5E7EB", "_TEXTE_DOUX": "#6B7280"}
espace2["logo_image"] = lambda: None
extraire(BACKEND / "emails" / "gabarit.py", {"_entete_html", "_logo_html"}, espace2)
sombre = espace2["_entete_html"]()
verifier("SANS logo : le bandeau sombre et le nom écrit, comme avant",
         faux_marque.MARQUE["fond"] in sombre and "Symbiose Paysage</div>" in sombre)

espace2["logo_image"] = lambda: {"content_id": "logo-marque", "octets": b"x"}
clair = espace2["_entete_html"]()
verifier("AVEC logo : fond CLAIR — un logotype vert forêt sur vert foncé "
         "serait illisible",
         "background:#ffffff" in clair and faux_marque.MARQUE["fond"] not in clair)
verifier("et le nom n'est PAS répété : le logotype le contient déjà",
         "Symbiose Paysage</div>" not in clair
         and 'alt="Symbiose Paysage"' in clair)
verifier("la baseline reste, dans une couleur lisible sur clair",
         "Assistant IA interne" in clair and "#6B7280" in clair)

# LE DRAPEAU EST UNE DONNÉE DE MARQUE, et il faut les deux cas : chez le jumeau
# le logo est un SYMBOLE (des carrés), pas un logotype — sans le nom écrit à
# côté, le destinataire ne saurait pas de qui vient le message.
espace2["LOGO_PORTE_LE_NOM"] = False
symbole = espace2["_entete_html"]()
verifier("un logo SYMBOLE fait écrire le nom à côté",
         "Symbiose Paysage</div>" in symbole and 'src="cid:logo-marque"' in symbole)

# ── 2 ter. AUCUN TIRET CADRATIN NE PART DANS LE MAIL ────────────────────
# Demande de Noa. La règle typographique du projet les interdit déjà dans les
# mails rédigés par le modèle ; ceux du gabarit y échappaient, étant en dur.
import ast as _ast  # noqa: E402
_src = (BACKEND / "emails" / "gabarit.py").read_text(encoding="utf-8")
_arbre = _ast.parse(_src)
_docs = set()
for _n in [_arbre] + [x for x in _ast.walk(_arbre)
                      if isinstance(x, (_ast.FunctionDef, _ast.AsyncFunctionDef,
                                        _ast.ClassDef))]:
    if _n.body and isinstance(_n.body[0], _ast.Expr) \
            and isinstance(_n.body[0].value, _ast.Constant):
        _docs.add(_n.body[0].value.lineno)
_fautifs = [(n.lineno, n.value.strip()[:60]) for n in _ast.walk(_arbre)
            if isinstance(n, _ast.Constant) and isinstance(n.value, str)
            and ("—" in n.value or "–" in n.value) and n.lineno not in _docs]
verifier("aucun tiret cadratin dans le texte envoyé", not _fautifs, str(_fautifs[:2]))

# ── 3. `logo_image()` ne lève jamais, fichier ou pas ─────────────────────
marque = extraire(BACKEND / "emails" / "marque.py",
                  {"logo_image", "LOGO_FICHIER", "LOGO_CONTENT_ID"},
                  {"__file__": str(BACKEND / "emails" / "marque.py")})
try:
    lu = marque["logo_image"]()
    ok = lu is None or (isinstance(lu, dict) and lu.get("octets"))
except Exception as e:  # noqa: BLE001
    ok = False
    lu = f"{type(e).__name__}: {e}"
verifier("`logo_image()` rend None ou l'image, sans jamais lever", ok, str(lu))

# ── 4. Le câblage, lu dans le source ─────────────────────────────────────
auth = (BACKEND / "routers" / "auth.py").read_text(encoding="utf-8")
verifier("le mail de connexion emporte le logo",
         "logo_image()" in auth and "images=[logo] if logo else None" in auth)
envoi = (BACKEND / "emails" / "envoi.py").read_text(encoding="utf-8")
verifier("le constructeur du corps est PUR, donc vérifiable sans réseau",
         "def _corps(" in envoi and "async" not in envoi.split("def _corps(")[0][-40:])
outil = BACKEND / "scripts" / "logo_mail.py"
verifier("l'outil de fabrication existe et dit les DEUX façons de poser le fichier",
         outil.exists()
         and "pip install cairosvg" in outil.read_text(encoding="utf-8")
         and "déposer un PNG directement" in outil.read_text(encoding="utf-8"))

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
