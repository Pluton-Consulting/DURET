"""
Banc « LA SIGNATURE DE LA BOÎTE, ET PAS CELLE DE LA CLIENTE » — conversation du
15/09, 13:49 → 13:52 (Symbiose, boîte partagée de l'accueil).

Relevé de Noa : « il n'arrive pas à récupérer une signature de mail et il dit
qu'il le fait ; il a été incohérent, il m'a dit avoir récupéré la signature
d'une personne qui m'a envoyé un mail et pas la mienne ». Ce qui s'est passé :
  · « réenvoie-le avec la signature » → aucune signature enregistrée, le mail
    est reparti SANS, et rien ne l'a dit ;
  · « apprends-la » depuis « RE: Relance règlement bon SAP » : c'était la
    RÉPONSE de la cliente. Sa signature Gmail (`gmail_signature`) a été prise,
    et `separer` a gardé tout ce qui suivait — la citation du message de
    l'accueil comprise. « La signature a bien été apprise » ;
  · la vraie signature de la boîte est une IMAGE sous « Cordialement » : aucune
    règle ne la voyait, et les OCTETS des images n'étaient jamais téléchargés
    (« Images : 0 », depuis toujours) ;
  · la carte de la signature ne s'affichait pas (`keyvalue` sans `rows`, type
    `text` inconnu) : personne ne l'a VUE.

CE QUE CE BANC PROUVE (sans réseau ni base) :
  · `separer` EXÉCUTÉ : la citation est coupée avant de chercher ; la réponse
    Gmail de la cliente rend SA signature, que `adresses_etrangeres` désigne ;
    l'envoi de l'accueil (Outlook, texte + Cordialement + image, puis citation
    portant une `gmail_signature`) rend l'IMAGE, pas la signature citée ;
  · `apprendre` EXÉCUTÉ contre une messagerie doublée : un message REÇU
    n'enregistre rien ; un message envoyé enregistre la signature en image AVEC
    ses octets téléchargés ;
  · `apposer` : une signature enregistrée qui porte l'adresse d'un tiers ne
    part pas ;
  · les gestes : `apprendre_signature` en échec est un ÉCHEC ; la carte est
    lisible (rows, callout) ; `envoyer_email` avec `signature: true` et aucune
    signature n'envoie RIEN ; `supprimer_signature` passe par la règle
    « supprime ».
Tombe sur la version d'avant.

Usage : python backend/scripts/test_signature_boite.py [backend]
"""
import ast
import asyncio
import base64
import importlib.util
import pathlib
import re
import sys
import types

racine = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
sys.path.insert(0, str(racine))
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {str(detail)[:300]}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def module(nom, **attrs):
    m = types.ModuleType(nom)
    m.__dict__.update(attrs)
    sys.modules[nom] = m
    return m


BOITE = "contact@exemple-paysage.fr"
LOGO = b"\x89PNG\r\n\x1a\n" + b"logo" * 50
RECU_CLIENTE = (
    '<div dir="ltr">Bonjour, c\'est réglé.</div><br>'
    '<div class="gmail_signature"><div>RSE - FORMATION - RETAIL - ESS - ISR</div>'
    '<div>+ 33 (0) 6.16.12.95.09</div><div>cliente.exemple@gmail.com</div></div><br>'
    '<div class="gmail_quote"><div class="gmail_attr">Le mar. 15 sept. 2026 à 12:24, '
    'Accueil &lt;contact@exemple-paysage.fr&gt; a écrit :</div><blockquote>Bonjour,<br>'
    'Sauf erreur de notre part, le bon SAP est en attente.<br>Cordialement,<br>'
    '<img src="cid:image001.png@01DC12AB"></blockquote></div>')
ENVOI_ACCUEIL = (
    '<div>Bonjour,</div><div>Merci pour votre retour, nous restons disponibles.</div>'
    '<div>Cordialement,</div><div><img src="cid:image001.png@01DC12AB" width="320"></div>'
    '<hr style="display:inline-block;width:98%" tabindex="-1">'
    '<div id="divRplyFwdMsg"><b>De :</b> Cliente &lt;cliente.exemple@gmail.com&gt;<br>'
    '<b>Envoyé :</b> mardi 15 septembre 2026</div>'
    '<div class="gmail_signature">RSE - FORMATION<br>cliente.exemple@gmail.com</div>')

# ── 1. separer ──────────────────────────────────────────────────────────────
print("1. La découpe")
spec = importlib.util.spec_from_file_location("mail.signature", racine / "mail" / "signature.py")
sig = importlib.util.module_from_spec(spec)
sys.modules["mail.signature"] = sig
spec.loader.exec_module(sig)
if not hasattr(sig, "sans_citation"):
    verifier("mail/signature.py coupe la citation", False, "sans_citation absent")
else:
    _, s_recu = sig.separer(RECU_CLIENTE)
    verifier("la réponse Gmail de la cliente : SA signature, sans la citation",
             "RSE - FORMATION" in s_recu and "Sauf erreur" not in s_recu and "a écrit" not in s_recu, s_recu)
    verifier("… et elle porte une adresse d'un tiers",
             sig.adresses_etrangeres(sig.en_texte(s_recu), BOITE) == ["cliente.exemple@gmail.com"])
    _, s_envoi = sig.separer(ENVOI_ACCUEIL)
    verifier("l'envoi de l'accueil : la signature en IMAGE, pas celle citée plus bas",
             "cid:image001" in s_envoi and "RSE" not in s_envoi and "Cordialement" not in s_envoi, s_envoi)
    _, s_outlook = sig.separer('<p>Bonjour</p><div id="Signature">Marie Dupont<br>Directrice</div>'
                               '<div id="divRplyFwdMsg"><b>De :</b> x</div><div id="Signature">Autre</div>')
    verifier("deux signatures Outlook : la nôtre, au-dessus de la citation", "Marie Dupont" in s_outlook
             and "Autre" not in s_outlook, s_outlook)
    verifier("une adresse de la boîte ne rend pas la signature étrangère",
             sig.adresses_etrangeres("Accueil\ncontact@exemple-paysage.fr", BOITE) == [])

# ── 2. apprendre ────────────────────────────────────────────────────────────
print("2. apprendre, contre une messagerie doublée")
ENREGISTRE = []
MESSAGES = {
    "ref-recu": {"objet": "RE: Relance règlement bon SAP", "de": "cliente.exemple@gmail.com",
                 "date": "2026-09-15", "corps_html": RECU_CLIENTE, "pieces_jointes": []},
    "ref-envoi": {"objet": "RE: Relance règlement bon SAP", "de": BOITE, "date": "2026-09-15",
                  "corps_html": ENVOI_ACCUEIL,
                  "pieces_jointes": [{"nom": "image001.png", "type": "image/png", "inline": True,
                                      "content_id": "image001.png@01DC12AB", "ref": "p-logo"}]},
}


async def _lire_message(boite, ref=None, dossier="recus", pieces=False, inline=False, **k):
    return dict(MESSAGES[ref], pieces_jointes=[dict(p) for p in MESSAGES[ref]["pieces_jointes"]])


async def _lire_boite(boite, dossier="recus", limite=8):
    return {"messages": [{"ref": "ref-envoi"}]}


async def _telecharger(boite, info):
    return LOGO


module("mail.lecture", lire_message=_lire_message, lire_boite=_lire_boite,
       piece_connue=lambda ref, boite: {"id": "a", "message": "m"} if ref == "p-logo" else None,
       telecharger_piece=_telecharger)
module("mail.pieces", cids_du_html=lambda h: [c.strip("<>") for c in re.findall(
    r"""src\s*=\s*["']?\s*cid:([^"'>\s]+)""", h or "", re.I)])


async def _enregistrer(boite, html_, texte, images, source, user_id=None):
    ENREGISTRE.append({"html": html_, "texte": texte, "images": images, "source": source})
sig.enregistrer = _enregistrer
user = types.SimpleNamespace(id="u-accueil", email=BOITE, role="administratif")
if hasattr(sig, "sans_citation"):
    r = asyncio.run(sig.apprendre(BOITE, user, ref="ref-recu"))
    verifier("un message REÇU n'enregistre AUCUNE signature", not r.get("trouvee") and not ENREGISTRE, (r, ENREGISTRE))
    verifier("… et le dit (rien n'a été enregistré)", "Rien n'a été enregistré" in r.get("message", ""), r)
    r = asyncio.run(sig.apprendre(BOITE, user))
    verifier("les derniers ENVOYÉS : la signature en image est apprise",
             r.get("trouvee") and ENREGISTRE and "cid:image001" in ENREGISTRE[-1]["html"], (r, ENREGISTRE))
    verifier("… AVEC les octets de son image (plus « Images : 0 »)",
             ENREGISTRE and len(ENREGISTRE[-1]["images"]) == 1
             and base64.b64decode(ENREGISTRE[-1]["images"][0]["octets_b64"]) == LOGO, ENREGISTRE[-1:])

    # 15/09, Duret : IMAP rend l'en-tête entier. « Revêtements Duret Sols
    # <revetementsduret@gmail.com> » n'était jamais égal à l'adresse : les huit
    # envoyés de la boîte étaient écartés.
    if hasattr(sig, "meme_expediteur"):
        GMAIL = "revetementsduret@gmail.com"
        verifier("l'en-tête « Nom <adresse> » se lit par son adresse",
                 sig.meme_expediteur("Revêtements Duret Sols <revetementsduret@gmail.com>", GMAIL))
        verifier("sur une boîte Gmail, un AUTRE compte Gmail n'est pas la boîte",
                 not sig.meme_expediteur("Cliente <cliente.exemple@gmail.com>", GMAIL))
        verifier("sur un domaine d'entreprise, un collègue du domaine l'est",
                 sig.meme_expediteur("Marie <marie@exemple-paysage.fr>", BOITE))
        verifier("sur une boîte Gmail, l'adresse Gmail d'un tiers dans la signature est étrangère",
                 sig.adresses_etrangeres("Duret\nrevetementsduret@gmail.com\ncliente.exemple@gmail.com", GMAIL)
                 == ["cliente.exemple@gmail.com"])
        MESSAGES["ref-envoi"]["de"] = "Accueil <" + BOITE + ">"
        ENREGISTRE.clear()
        r = asyncio.run(sig.apprendre(BOITE, user))
        verifier("un envoyé dont l'expéditeur porte un nom est appris", r.get("trouvee") and ENREGISTRE, r)
        MESSAGES["ref-envoi"]["de"] = BOITE
    else:
        verifier("signature.py porte `meme_expediteur`", False, "absent")

# ── 2 bis. Les images INTÉGRÉES et HÉBERGÉES (15/09) ─────────────────────────
print("2 bis. Une signature en image intégrée (data:) ou hébergée (https:)")
if hasattr(sig, "images_integrees"):
    import base64 as _b64
    PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    html_data = ('<p>Bonjour,</p><p>Voici le devis.</p><p>Cordialement,</p>'
                 f'<p><img src="data:image/png;base64,{_b64.b64encode(PNG).decode()}" width="200"></p>')
    _, s_data = sig.separer(html_data)
    verifier("une signature QU'IMAGE intégrée (data:) est reconnue", "data:image/png" in s_data, s_data[:120])
    html2, pieces2 = asyncio.run(sig.images_integrees(s_data))
    verifier("l'image intégrée devient une image cid: de la signature, octets compris",
             "cid:signature-1@assistant" in html2 and pieces2 and pieces2[0]["octets"] == PNG, (html2[:160], pieces2[:1]))
    verifier("une adresse interne n'est jamais chargée", not sig.adresse_publique("http://localhost/logo.png")
             and not sig.adresse_publique("http://10.0.0.5/logo.png") and not sig.adresse_publique("http://127.0.0.1/x.png"))

    class _Rep:
        def __init__(self, contenu, mime):
            self.content, self.status_code, self.headers = contenu, 200, {"content-type": mime}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return _Rep(PNG, "image/png")

    ancien_httpx, ancienne_adresse = sys.modules.get("httpx"), sig.adresse_publique
    sys.modules["httpx"], sig.adresse_publique = types.SimpleNamespace(AsyncClient=_Client), (lambda url: True)
    try:
        html3, pieces3 = asyncio.run(sig.images_integrees(
            '<p>Cordialement,</p><img src="https://www.exemple-paysage.fr/logo.png">'))
    finally:
        sig.adresse_publique = ancienne_adresse
        if ancien_httpx is None:
            sys.modules.pop("httpx", None)
        else:
            sys.modules["httpx"] = ancien_httpx
    verifier("une image hébergée (https:) est téléchargée et devient une image cid:",
             "cid:signature-1@assistant" in html3 and pieces3 and pieces3[0]["mime"] == "image/png", (html3, pieces3[:1]))
    MESSAGES["ref-data"] = {"objet": "Devis", "de": BOITE, "date": "2026-09-15",
                            "corps_html": html_data, "pieces_jointes": []}
    ancienne_boite = _lire_boite

    async def _lire_boite_data(boite, dossier="recus", limite=8):
        return {"messages": [{"ref": "ref-data"}]}
    module("mail.lecture", lire_message=_lire_message, lire_boite=_lire_boite_data,
           piece_connue=lambda ref, boite: None, telecharger_piece=_telecharger)
    ENREGISTRE.clear()
    r = asyncio.run(sig.apprendre(BOITE, user))
    verifier("« apprends la signature » : une signature en image intégrée est apprise AVEC son image",
             r.get("trouvee") and ENREGISTRE and len(ENREGISTRE[-1]["images"]) == 1
             and "cid:signature-1@assistant" in ENREGISTRE[-1]["html"], (r, ENREGISTRE[-1:]))
    module("mail.lecture", lire_message=_lire_message, lire_boite=ancienne_boite,
           piece_connue=lambda ref, boite: {"id": "a", "message": "m"} if ref == "p-logo" else None,
           telecharger_piece=_telecharger)
else:
    verifier("signature.py sait reprendre les images intégrées et hébergées", False, "absent")
lecture_src = (pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend") / "mail" / "lecture.py").read_text(encoding="utf-8")
verifier("Outlook : l'identifiant de TOUTE image est relu, et une pièce que le corps affiche est une image du corps",
         'str(x.get("type") or "").lower().startswith("image/")' in lecture_src and 'p["inline"] = True' in lecture_src)

# ── 3. apposer ──────────────────────────────────────────────────────────────
print("3. Une signature d'un tiers ne part pas")


async def _enregistree_tiers(boite):
    return {"html": "<div>RSE</div>", "texte": "RSE - FORMATION\ncliente.exemple@gmail.com", "images": []}
sig.enregistree = _enregistree_tiers
corps, html_, pieces = asyncio.run(sig.apposer(BOITE, "Bonjour,\n\nCordialement,", []))
verifier("la signature enregistrée d'un tiers n'est PAS apposée", corps == "Bonjour,\n\nCordialement," and not html_)

# ── 4. Les gestes ───────────────────────────────────────────────────────────
print("4. Les gestes")


def extraire(chemin, noms, espace):
    arbre = ast.parse(pathlib.Path(chemin).read_text(encoding="utf-8"))
    gardes = [n for n in arbre.body
              if (isinstance(n, ast.ImportFrom) and n.module == "__future__")
              or (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in noms)]
    exec(compile(ast.Module(body=gardes, type_ignores=[]), str(chemin), "exec"), espace)
    return [x for x in noms if x not in espace]


class MailSkillError(Exception):
    def __init__(self, detail):
        self.detail = detail
        super().__init__(detail)


async def _verifier_acces(user, cible, envoi=False):
    return cible or BOITE


async def _boite_par_defaut(user):
    return BOITE

esp = {"MailSkillError": MailSkillError, "verifier_acces": _verifier_acces,
       "boite_par_defaut": _boite_par_defaut}
manque = extraire(racine / "mail" / "skills.py",
                  {"apprendre_signature", "_fiche_signature", "envoyer_email", "_signature_exigee",
                   "supprimer_signature"}, esp)
verifier("les gestes existent (dont supprimer_signature)", not manque, manque)
if not manque:
    async def _apprendre_rien(boite, user, ref=""):
        return {"trouvee": False, "message": "Aucune signature de la boîte n'a été trouvée."}
    sig.apprendre = _apprendre_rien
    try:
        asyncio.run(esp["apprendre_signature"]({"ref": "ref-recu"}, user))
        verifier("apprendre_signature sans résultat est un ÉCHEC", False, "rendu comme une réussite")
    except MailSkillError as e:
        verifier("apprendre_signature sans résultat est un ÉCHEC",
                 "Ne dis pas qu'une signature a été apprise" in str(e.detail), e.detail)

    module("visuels")
    module("visuels.depot", deposer_octets=lambda o, m: "c" * 24)
    sig.enregistree = _enregistree_tiers
    fiche = asyncio.run(esp["_fiche_signature"](BOITE, appris=False))
    kv = [b for b in fiche["bloc_ui"] if b["type"] == "keyvalue"]
    co = [b for b in fiche["bloc_ui"] if b["type"] == "callout"]
    verifier("la carte s'affiche : keyvalue avec `rows`, texte dans un callout",
             kv and kv[0].get("rows") and co and co[0].get("text")
             and all(b["type"] in ("keyvalue", "callout", "visuel") for b in fiche["bloc_ui"]), fiche["bloc_ui"])
    verifier("… et une signature d'un tiers est signalée comme non apposée",
             co and co[0]["tone"] == "warning" and fiche["signature"]["celle_d_un_tiers"])

    async def _aucune(boite):
        return None
    sig.enregistree = _aucune
    ENVOIS = []

    async def _envoyer(*a, **k):
        ENVOIS.append(a)
        return {"envoye": True}

    async def _resoudre(brut, user, boite, plafond=None):
        return [], []
    module("mail.attaches", resoudre=_resoudre)
    exp = module("mail.expedition", envoyer_message=_envoyer, porte_un_jeton=lambda t: False)

    async def _boite_a_lire(data, user):
        return BOITE
    esp["_boite_a_lire"] = _boite_a_lire
    try:
        asyncio.run(esp["envoyer_email"]({"destinataire": "cliente@exemple.fr", "objet": "RE: x",
                                          "corps": "Bonjour", "signature": True}, user))
        verifier("« avec la signature » et aucune signature : RIEN ne part", False, "envoyé")
    except MailSkillError as e:
        verifier("« avec la signature » et aucune signature : RIEN ne part",
                 not ENVOIS and "RIEN n'a été envoyé" in str(e.detail), e.detail)
    r = asyncio.run(esp["envoyer_email"]({"destinataire": "cliente@exemple.fr", "objet": "RE: x",
                                          "corps": "Bonjour"}, user))
    verifier("sans demande explicite, le compte rendu dit que le message est parti SANS signature",
             ENVOIS and r["signature"].startswith("AUCUNE") and "sans signature" in r["message_final"], r)

# ── 5. La lecture Outlook des pièces (15/09, export Langfuse de 14:28) ──────
print("5. Outlook : les pièces d'un message et la signature en image")
# Le vrai message envoyé de l'accueil : `<div id="Signature">`, « Cordialement »,
# puis une image en ligne de 1 445 544 octets.
HTML_ACCUEIL = (
    '<html><body dir="ltr"><div class="elementToProof">Bonjour,</div><div class="elementToProof">'
    'Pouvez-vous me confirmer qu\'elles ne passeront pas en Traite fin octobre ?</div>'
    '<div id="Signature" class="elementToProof"><div class="elementToProof"><br></div>'
    '<p class="elementToProof" style="margin:0cm"><span style="color:black">Cordialement,</span></p>'
    '<p class="elementToProof" style="margin:0cm"><span style="color:black">&nbsp;</span></p>'
    '<p class="elementToProof" style="margin:0cm"><span style="color:black"><img width="626" height="254" '
    'size="1445544" data-outlook-trace="F:1|T:1" src="cid:13b895d9-e9b7-4232-a311-6c95b978e50c" '
    'style="width:626px; height:254px"></span></p><p class="elementToProof">&nbsp;</p></div></body></html>')
GROS_LOGO = b"\x89PNG" + b"x" * 1_445_540
GRAPH = []


class _RepG:
    def __init__(self, code, donnees):
        self.status_code, self._d = code, donnees

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _ClientG:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None, headers=None):
        GRAPH.append((url, dict(params or {})))
        select = (params or {}).get("$select", "")
        if url.endswith("/attachments"):
            if "contentId" in select:     # ce que Graph fait : propriété inconnue du type de base
                return _RepG(400, {"error": {"message": "Could not find a property named 'contentId' "
                                                        "on type 'microsoft.graph.attachment'."}})
            return _RepG(200, {"value": [{"id": "ATT1", "name": "image.png", "size": 1445544,
                                          "contentType": "image/png", "isInline": True}]})
        if "/attachments/ATT1" in url:
            return _RepG(200, {"id": "ATT1", "contentId": "13b895d9-e9b7-4232-a311-6c95b978e50c",
                               "contentBytes": base64.b64encode(GROS_LOGO).decode()})
        if select == "body":
            return _RepG(200, {"body": {"contentType": "html", "content": HTML_ACCUEIL}})
        return _RepG(200, {"id": "MSG1", "subject": "Point règlement facture", "hasAttachments": True,
                           "from": {"emailAddress": {"address": BOITE}}, "body": {"content": "Bonjour"}})


module("httpx", AsyncClient=_ClientG)
module("ingestion")
module("ingestion.connectors")


async def _jeton_g():
    return "J"
module("ingestion.connectors.outlook", _jeton=_jeton_g)
esp_l = {"logger": types.SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None),
         "PREFER_OUTLOOK_TEXTE": "outlook.body-content-type=\"text\"", "SELECT_OUTLOOK": "id,subject",
         "MAX_APERCU": 400, "_fiche_outlook": lambda m, b, n: {"objet": m.get("subject"), "de": BOITE},
         "_corps_outlook": lambda m: "Bonjour"}
manque_l = extraire(racine / "mail" / "lecture.py", {"_ouvrir_outlook"}, esp_l)
src_lec = (racine / "mail" / "lecture.py").read_text(encoding="utf-8")
exec(compile("\n".join(l for l in src_lec.splitlines() if l.startswith("MAX_INLINE_RELUS")), "lecture", "exec"), esp_l)
if manque_l:
    verifier("mail/lecture.py porte _ouvrir_outlook", False, manque_l)
else:
    fiche = asyncio.run(esp_l["_ouvrir_outlook"](BOITE, "MSG1"))
    verifier("la liste des pièces ne demande plus `contentId` au type de base (Graph refusait)",
             all("contentId" not in p.get("$select", "") for u, p in GRAPH if u.endswith("/attachments")), GRAPH)
    verifier("l'image en ligne est LISTÉE, avec son identifiant de contenu relu",
             fiche["pieces_jointes"] and fiche["pieces_jointes"][0]["content_id"] == "13b895d9-e9b7-4232-a311-6c95b978e50c",
             fiche["pieces_jointes"])
    _, s_acc = sig.separer(HTML_ACCUEIL)
    verifier("le vrai HTML de l'accueil : la signature Outlook, image comprise", "cid:13b895d9" in s_acc, s_acc[:200])
    images = sig._images_du_html(s_acc, [{"content_id": "13B895D9-E9B7-4232-A311-6C95B978E50C", "nom": "image.png",
                                           "mime": "image/png", "octets": GROS_LOGO}])
    verifier("une image de signature de 1,4 Mo est gardée (le plafond était 512 Ko)", len(images) == 1)
    verifier("pas de « Cordialement, » en double à l'envoi",
             sig.sans_politesse_en_double("Bonjour,\n\nMerci.\n\nCordialement,\n", "Cordialement,\n")
             == "Bonjour,\n\nMerci.")
    verifier("une signature sans politesse ne retire rien du corps",
             sig.sans_politesse_en_double("Bonjour,\n\nCordialement,", "Marie Dupont\nDirectrice")
             == "Bonjour,\n\nCordialement,")

# ── 6. Une signature VIDE (15/09, Symbiose, 15:40 → 15:42) ─────────────────
print("6. Une signature vide ne s'apprend pas, ne se montre pas, ne part pas")
# Export du 15/09 : « apprise » avec texte vide et 0 image ; au tour suivant,
# « affiche la signature » → une fiche au texte et au téléphone INVENTÉS.
spec6 = importlib.util.spec_from_file_location("mail.signature", racine / "mail" / "signature.py")
sig6 = importlib.util.module_from_spec(spec6)
sys.modules["mail.signature"] = sig6
spec6.loader.exec_module(sig6)
if not hasattr(sig6, "signature_vide"):
    verifier("signature.py porte `signature_vide`", False, "absent")
else:
    verifier("absente ou sans texte ni image : vide ; texte ou image : non",
             sig6.signature_vide(None)
             and sig6.signature_vide({"html": '<div><img src="cid:x"></div>', "texte": "", "images": []})
             and not sig6.signature_vide({"texte": "Marie Dupont", "images": []})
             and not sig6.signature_vide({"texte": "", "images": [{"cid": "x"}]}))
    ENR6 = []

    async def _enr6(*a, **k):
        ENR6.append(a)
    sig6.enregistrer = _enr6
    MESSAGES["ref-envoi"]["pieces_jointes"] = []     # l'image n'a pas été lue
    module("mail.lecture", lire_message=_lire_message, lire_boite=_lire_boite,
           piece_connue=lambda ref, boite: None, telecharger_piece=_telecharger)
    r = asyncio.run(sig6.apprendre(BOITE, user))
    verifier("une signature QU'IMAGE dont l'image n'est pas récupérée n'est PAS enregistrée",
             not r.get("trouvee") and not ENR6, (r, ENR6))
    verifier("… et l'échec dit ce qui manque", "aucune de ses images" in r.get("message", ""), r)

    async def _vide(boite):
        return {"html": '<div><img src="cid:x"></div>', "texte": "", "images": []}
    sig6.enregistree = _vide
    corps6, html6, _ = asyncio.run(sig6.apposer(BOITE, "Bonjour", []))
    verifier("une signature vide déjà en base ne part pas sous le message", corps6 == "Bonjour" and html6 == "",
             (corps6, html6))

    esp6 = {"MailSkillError": MailSkillError, "verifier_acces": _verifier_acces,
            "boite_par_defaut": _boite_par_defaut}
    manque6 = extraire(racine / "mail" / "skills.py",
                       {"ma_signature", "apprendre_signature", "_fiche_signature"}, esp6)
    verifier("ma_signature existe", not manque6, manque6)
    if not manque6:
        ETAT6 = {"sig": {"html": "", "texte": "", "images": []}}
        APPRIS6 = []

        async def _lue(boite):
            return ETAT6["sig"]

        async def _apprend(boite, user, ref=""):
            APPRIS6.append(boite)
            ETAT6["sig"] = {"html": "<div>Marie Dupont</div>", "texte": "Marie Dupont", "images": [],
                            "source": "message « x »", "derniere_maj": "2026-09-15"}
            return {"trouvee": True, "occurrences": 2}
        sig6.enregistree, sig6.apprendre = _lue, _apprend
        fiche6 = asyncio.run(esp6["ma_signature"]({}, user))
        verifier("« affiche ma signature » sans signature utilisable va la chercher dans les envoyés",
                 APPRIS6 == [BOITE] and fiche6.get("apprise") and fiche6["signature"]["texte"] == "Marie Dupont",
                 fiche6)
        APPRIS6.clear()
        fiche6 = asyncio.run(esp6["ma_signature"]({}, user))
        verifier("… et une signature en vigueur se montre sans réapprendre", not APPRIS6 and not fiche6.get("apprise"))
    sys.modules["mail.signature"] = sig

src_sup = (racine / "skills" / "suppression.py").read_text(encoding="utf-8")
espace_sup = {"re": re}
exec(compile(src_sup, "suppression", "exec"), espace_sup)
verifier("supprimer_signature exige le mot « supprime »",
         espace_sup["est_une_suppression"]("supprimer_signature")
         and not espace_sup["autorise_la_suppression"]("oublie la signature de la cliente"))
proto = (racine / "skills" / "protocol.py").read_text(encoding="utf-8")
verifier("le catalogue dit qu'un message REÇU ne porte pas notre signature, et l'échec",
         "un message RECU" in proto and "AUCUNE signature n'a ete apprise" in proto)
verifier("le catalogue d'envoi dit `signature: true`", "`signature: true` quand la personne DEMANDE" in proto)

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s)")
    sys.exit(1)
print("✓ 0 échec")
