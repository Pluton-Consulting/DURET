"""
Banc « LE BROUILLON VA DANS LA BOÎTE, SE RETOUCHE, ET NE S'AFFICHE QU'UNE FOIS » —
deux conversations du 11/09 (Symbiose).

Relevé de Noa : « il y a un gros problème avec les mails ». Ce qu'on y lit :
  1. « je ne le trouve pas dans les brouillons de ma boîte mail » : aucun
     geste ne savait poser un brouillon dans la messagerie — `redaction_email`
     écrit dans la conversation, rien d'autre ;
  2. l'assistant a pourtant AFFIRMÉ « le brouillon a bien été créé dans votre
     boîte mail […] enregistré comme brouillon », puis s'est démenti au tour
     suivant ;
  3. « une version un peu moins brute », « tu as enlevé trop de choses, le
     mail d'avant était mieux construit » : chaque retouche repartait du seul
     `contexte`, sans la version précédente — une réécriture ;
  4. chaque version s'affichait DEUX fois : une carte `email` recopiée par le
     modèle (signée d'un nom que la consigne interdit), puis le même texte en
     prose ; et « Joins le devis » en suggestion sous un refus poli.

CE QUE CE BANC PROUVE (sans réseau, sans modèle, sans base) :
  · `mail/expedition.py` EXÉCUTÉ contre un Graph doublé : le brouillon est créé
    dans la boîte (POST messages), en RÉPONSE au message d'origine quand on le
    connaît (createReply + objet), pièces téléversées ; un 403 nomme
    Mail.ReadWrite ; le dossier IMAP se reconnaît à son attribut \\Drafts ;
  · `mail/brouillons.py` : le dernier brouillon par personne ET par fil ;
  · `rediger_email` EXÉCUTÉ : carte `reponses_mail` garantie, « dans la
    conversation seulement » dit au modèle, brouillon retenu ; une retouche
    part de la version précédente et le dit au rédacteur ; sans version connue,
    un refus clair ;
  · `deposer_brouillon` EXÉCUTÉ : sans corps, le dernier brouillon du fil ; la
    `ref` du mail d'origine devient la réponse ; signature apposée ;
  · `pretend_brouillon_depose` sur les phrases EXACTES du 11/09 ;
  · la prose et la carte `email` recopiées sous la carte du skill s'effacent,
    la phrase de présentation reste ;
  · le câblage : catalogue, effet, fil donné par le serveur, suggestion, filet,
    bouton « Mettre dans mes brouillons ».
Tombe sur la version d'avant (geste absent).

Usage : python backend/scripts/test_brouillon_boite.py [backend]
"""
import ast
import asyncio
import importlib.util
import json
import pathlib
import sys
import types

racine = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
sys.path.insert(0, str(racine))
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {str(detail)[:300]}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def extraire(chemin, noms, espace):
    arbre = ast.parse(pathlib.Path(chemin).read_text(encoding="utf-8"))
    gardes = [n for n in arbre.body
              if (isinstance(n, ast.ImportFrom) and n.module == "__future__")
              or (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in noms)
              or (isinstance(n, ast.Assign) and any(isinstance(c, ast.Name) and c.id in noms
                                                    for c in n.targets))]
    exec(compile(ast.Module(body=gardes, type_ignores=[]), str(chemin), "exec"), espace)
    return [x for x in noms if x not in espace]


def module(nom, **attrs):
    m = types.ModuleType(nom)
    m.__dict__.update(attrs)
    sys.modules[nom] = m
    return m


CORPS_V1 = ("Bonjour François,\n\nMerci pour votre proposition d'accompagnement. Après réflexion, "
            "nous ne donnerons pas suite pour le moment. Nous vous contacterons si le besoin se "
            "présente.\n\nBonne continuation,")
CORPS_V2 = ("Bonjour François,\n\nMerci pour votre proposition d'accompagnement et pour le temps que "
            "vous y avez consacré.\n\nAprès mûre réflexion, nous préférons ne pas y donner suite pour "
            "le moment. Nous conservons vos coordonnées et n'hésiterons pas à vous recontacter si un "
            "besoin se présentait.\n\nBien cordialement,")

# ── 1. L'expédition : le brouillon dans la boîte ────────────────────────────
print("1. mail/expedition.py — le dépôt réel")
APPELS = []


class _Rep:
    def __init__(self, code, donnees=None, texte=""):
        self.status_code, self._d, self.text = code, donnees or {}, texte

    def json(self):
        return self._d


class _Client:
    statut = 201

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None, **k):
        APPELS.append(("POST", url, json))
        if _Client.statut == 403:
            return _Rep(403, texte="Access denied")
        if url.endswith("createUploadSession"):
            return _Rep(200, {"uploadUrl": "https://televersement"})
        return _Rep(201, {"id": "BROUILLON-1", "webLink": "https://outlook/brouillon"})

    async def patch(self, url, json=None, headers=None, **k):
        APPELS.append(("PATCH", url, json))
        return _Rep(200, {})

    async def put(self, url, content=None, headers=None, **k):
        APPELS.append(("PUT", url, len(content or b"")))
        return _Rep(201, {})


module("httpx", AsyncClient=_Client)
module("mail.collecte", fournisseur=lambda: "outlook")
module("ingestion")
module("ingestion.connectors")


async def _jeton():
    return "JETON"
module("ingestion.connectors.outlook", _jeton=_jeton)
spec = importlib.util.spec_from_file_location("mail.expedition", racine / "mail" / "expedition.py")
exp = importlib.util.module_from_spec(spec)
sys.modules["mail.expedition"] = exp
spec.loader.exec_module(exp)

if not hasattr(exp, "deposer_brouillon"):
    verifier("mail/expedition.py sait déposer un brouillon", False, "deposer_brouillon absent")
else:
    m = exp._message_graph_brouillon("", "RE: Proposition", CORPS_V2)
    verifier("un brouillon sans destinataire reste valable (on complète dans Outlook)",
             "toRecipients" not in m and m["subject"] == "RE: Proposition")
    r = asyncio.run(exp.deposer_brouillon("direction@exemple-paysage.fr", "francois@exemple.fr",
                                          "RE: Proposition", CORPS_V2,
                                          pieces=[{"nom": "devis.pdf", "octets": b"%PDF" * 10,
                                                   "mime": "application/pdf"}]))
    verifier("le brouillon est CRÉÉ dans la boîte (POST …/messages), rien n'est envoyé",
             APPELS[0][0] == "POST" and APPELS[0][1].endswith("/users/direction@exemple-paysage.fr/messages")
             and not any(u.endswith("/send") for _, u, _ in APPELS), APPELS)
    verifier("les pièces sont téléversées sur le brouillon",
             any(u.endswith("createUploadSession") for _, u, _ in APPELS))
    verifier("le résultat dit : déposé, pas envoyé, dans les Brouillons, avec le lien",
             r.get("depose") and r.get("envoye") is False and r.get("dossier") == "Brouillons"
             and r.get("lien"), r)
    APPELS.clear()
    asyncio.run(exp.deposer_brouillon("direction@exemple-paysage.fr", "", "RE: Proposition",
                                      CORPS_V2, en_reponse_a="AAMkIdOrigine"))
    verifier("en réponse : createReply sur le message d'origine, texte en commentaire",
             APPELS[0][1].endswith("/messages/AAMkIdOrigine/createReply")
             and APPELS[0][2] == {"comment": CORPS_V2}, APPELS[:1])
    verifier("… puis l'objet est reposé sur le brouillon (PATCH)",
             any(v == "PATCH" and d == {"subject": "RE: Proposition"} for v, _, d in APPELS), APPELS)
    _Client.statut = 403
    try:
        asyncio.run(exp.deposer_brouillon("d@exemple.fr", "", "o", "c"))
        verifier("un 403 nomme l'autorisation Mail.ReadWrite", False, "aucune erreur")
    except RuntimeError as e:
        verifier("un 403 nomme l'autorisation Mail.ReadWrite", "Mail.ReadWrite" in str(e), e)
    _Client.statut = 201
    listes = [b'(\\HasNoChildren) "/" "INBOX"',
              b'(\\HasNoChildren \\Drafts) "/" "[Gmail]/Brouillons"',
              b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Messages envoy&AOk-s"']
    verifier("IMAP : le dossier des brouillons se reconnaît à \\Drafts (Gmail en français)",
             exp._dossier_brouillons_imap(listes) == "[Gmail]/Brouillons")
    verifier("IMAP : sans attribut, un nom courant", exp._dossier_brouillons_imap([b'() "/" "Drafts"']) == "Drafts")

# ── 2. Le dernier brouillon de la conversation ──────────────────────────────
print("2. mail/brouillons.py")
spec = importlib.util.spec_from_file_location("mail.brouillons", racine / "mail" / "brouillons.py")
br = importlib.util.module_from_spec(spec)
sys.modules["mail.brouillons"] = br
spec.loader.exec_module(br)
br.retenir("u1", "fil-A", {"objet": "RE: x", "corps": CORPS_V1, "boite": "b@x.fr"})
verifier("retenu pour cette personne et ce fil", (br.dernier("u1", "fil-A") or {}).get("corps") == CORPS_V1)
verifier("pas pour un autre fil, ni une autre personne",
         br.dernier("u1", "fil-B") is None and br.dernier("u2", "fil-A") is None)
br.retenir("u1", "fil-A", {"objet": "RE: x", "corps": CORPS_V2})
verifier("la version suivante remplace la précédente", br.dernier("u1", "fil-A")["corps"] == CORPS_V2)

# ── 3. rediger_email ────────────────────────────────────────────────────────
print("3. redaction_email exécuté")
PROMPTS = []


class MailSkillError(Exception):
    def __init__(self, detail):
        self.detail = detail
        super().__init__(detail)


async def _boite_a_lire(data, user):
    return "direction@exemple-paysage.fr"


async def verifier_acces(user, cible, envoi=False):
    return cible


async def consigne_style(boite):
    return ""


async def _protege(t):
    return t, {}


REPONSE_MODELE = {"objet": "RE: Proposition d'accompagnement", "corps": CORPS_V2, "ton": "cordial"}


async def _appeler(prompt, tier="standard"):
    PROMPTS.append(prompt)
    return json.dumps(REPONSE_MODELE, ensure_ascii=False)


esp = {"MailSkillError": MailSkillError, "_boite_a_lire": _boite_a_lire,
       "verifier_acces": verifier_acces, "consigne_style": consigne_style,
       "_protege": _protege, "_appeler": _appeler, "_rehydrater": lambda v, c: v,
       "json": json, "re": __import__("re")}
manque = extraire(racine / "mail" / "skills.py",
                  {"rediger_email", "TYPES_MAIL", "_CONSIGNE_COMMUNE", "_json_de", "deposer_brouillon"}, esp)
verifier("les gestes existent", not manque, manque)
user = types.SimpleNamespace(id="u-dir", email="direction@exemple-paysage.fr", role="direction")
if not manque:
    br._DERNIERS.clear()
    r1 = asyncio.run(esp["rediger_email"]({"type_mail": "refus", "_fil": "fil-11-09",
                                           "destinataire": "francois@exemple.fr", "ref": "a1b2c3d4e5f6a7b8",
                                           "contexte": "ne pas donner suite, poliment"}, user))
    carte = (r1.get("bloc_ui") or {})
    verifier("la carte du brouillon est garantie (reponses_mail, modifiable)",
             r1.get("bloc_garanti") and carte.get("type") == "reponses_mail"
             and carte["reponses"][0]["reponse"] == CORPS_V2 and carte["reponses"][0]["ref"] == "a1b2c3d4e5f6a7b8", carte)
    verifier("le résultat dit que le brouillon n'est PAS dans la boîte",
             "PAS dans la boîte" in r1.get("ou_est_il", "") and "deposer_brouillon" in r1["a_faire"])
    verifier("la consigne interdit de réécrire le texte ou d'ajouter un signataire",
             "n'écris NI bloc email NI le texte" in r1["a_faire"] and "signataire" in r1["a_faire"])
    verifier("le brouillon est retenu pour la conversation",
             (br.dernier("u-dir", "fil-11-09") or {}).get("corps") == CORPS_V2)
    REPONSE_MODELE = {"objet": "RE: Proposition d'accompagnement", "corps": CORPS_V2 + "\n\nPS", "ton": "cordial"}
    esp["_appeler"] = _appeler
    PROMPTS.clear()
    r2 = asyncio.run(esp["rediger_email"]({"type_mail": "refus", "_fil": "fil-11-09", "retoucher": True,
                                           "contexte": "une version un peu moins brute"}, user))
    verifier("une retouche part de la VERSION PRÉCÉDENTE, envoyée au rédacteur",
             PROMPTS and "VERSION PRÉCÉDENTE" in PROMPTS[0] and "consacré" in PROMPTS[0]
             and "RETOUCHE, PAS UNE RÉÉCRITURE" in PROMPTS[0], PROMPTS[0][-600:] if PROMPTS else "")
    verifier("… avec la demande comme MODIFICATIONS, et le destinataire et la ref gardés",
             "MODIFICATIONS DEMANDÉES" in PROMPTS[0] and r2["bloc_ui"]["reponses"][0]["ref"] == "a1b2c3d4e5f6a7b8"
             and r2["bloc_ui"]["reponses"][0]["de"] == "francois@exemple.fr")
    try:
        asyncio.run(esp["rediger_email"]({"type_mail": "refus", "_fil": "fil-vide", "retoucher": True,
                                          "contexte": "plus court"}, user))
        verifier("retoucher sans version connue : un refus clair", False, "aucun refus")
    except MailSkillError as e:
        verifier("retoucher sans version connue : un refus clair", "version précédente" in str(e.detail), e.detail)

    print("4. deposer_brouillon exécuté")
    DEPOTS = []

    async def _faux_depot(boite, destinataire, objet, corps, cc=None, pieces=None, html="", en_reponse_a=None):
        DEPOTS.append({"boite": boite, "destinataire": destinataire, "objet": objet, "corps": corps,
                       "en_reponse_a": en_reponse_a})
        return {"depose": True, "envoye": False, "boite": boite, "dossier": "Brouillons"}

    exp.deposer_brouillon = _faux_depot

    async def _apposer(boite, corps, pieces, demandee=None):
        return corps + "\n--\nSignature de la boîte", "", pieces

    module("mail.signature", apposer=_apposer)
    module("mail.lecture", _resoudre=lambda ref, boite: "AAMkIdOrigine" if ref == "a1b2c3d4e5f6a7b8" else None)
    r = asyncio.run(esp["deposer_brouillon"]({"_fil": "fil-11-09"}, user))
    verifier("sans corps : le DERNIER brouillon de la conversation est déposé, tel quel",
             DEPOTS and DEPOTS[0]["corps"].startswith(CORPS_V2) and DEPOTS[0]["objet"].startswith("RE:"), DEPOTS)
    verifier("la signature de la boîte est apposée", DEPOTS and DEPOTS[0]["corps"].endswith("Signature de la boîte"))
    verifier("la ref du mail d'origine devient une vraie réponse", DEPOTS and DEPOTS[0]["en_reponse_a"] == "AAMkIdOrigine")
    verifier("le compte rendu dit : dans les Brouillons, rien n'a été envoyé",
             "Brouillons" in r["message_final"] and "Rien n'a été envoyé" in r["message_final"], r)
    try:
        asyncio.run(esp["deposer_brouillon"]({"_fil": "fil-inconnu"}, user))
        verifier("rien à déposer : un refus clair", False, "déposé quand même")
    except MailSkillError as e:
        verifier("rien à déposer : un refus clair", "Aucun brouillon" in str(e.detail), e.detail)

# ── 5. L'affirmation fausse ─────────────────────────────────────────────────
print("5. « le brouillon est dans votre boîte » sans dépôt")
spec = importlib.util.spec_from_file_location("agents.annonce", racine / "agents" / "annonce.py")
ann = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ann)
f = getattr(ann, "pretend_brouillon_depose", None)
if f is None:
    verifier("agents/annonce.py porte pretend_brouillon_depose", False)
else:
    for t in ("Oui, le brouillon a bien été créé dans votre boîte mail via `redaction_email` (type \"relance_impaye\"). "
              "Il est enregistré comme brouillon dans la boîte contact@exemple-paysage.fr, non envoyé.",
              "Vous pouvez le retrouver dans vos brouillons, le compléter avec la référence."):
        verifier(f"affirmé → détecté : « {t[:50]}… »", f(t))
    for t in ("Le brouillon n'a pas été enregistré dans votre boîte mail : il est uniquement dans cette conversation.",
              "Je ne peux pas déposer le brouillon dans votre boîte mail parce que `redaction_email` rédige le texte.",
              "Souhaitez-vous que je le crée comme brouillon dans votre boîte mail ?",
              "Pour le retrouver dans vos brouillons, je peux le créer avec redaction_email.",
              "Ce brouillon est prêt à être relu et envoyé."):
        verifier(f"nié, proposé ou sans lieu → ignoré : « {t[:50]}… »", not f(t))

# ── 6. La recopie sous la carte ─────────────────────────────────────────────
print("6. La carte et la prose recopiées s'effacent")
esp6 = {}
manque6 = extraire(racine / "agents" / "agent1.py",
                   {"_aplati_texte", "_sans_recopie_du_brouillon", "_apercu_du_brouillon"}, esp6)
verifier("agent1 porte les deux filets", not manque6, manque6)
if not manque6:
    texte = ("Voici une version plus travaillée et plus chaleureuse :\n\n" + CORPS_V2
             + "\nBenjamin Durou\n\nCe ton est plus posé : il laisse la porte ouverte.")
    net = esp6["_sans_recopie_du_brouillon"](texte, [CORPS_V2])
    verifier("le texte du brouillon recopié et le signataire ajouté s'effacent",
             "mûre réflexion" not in net and "Benjamin Durou" not in net, net)
    verifier("la phrase qui présente et celle qui commente restent",
             net.startswith("Voici une version") and net.endswith("porte ouverte."), net)
    verifier("un texte sans rapport ne bouge pas",
             esp6["_sans_recopie_du_brouillon"]("Bonjour,\n\nVoici le point.", [CORPS_V2]) == "Bonjour,\n\nVoici le point.")
    carte_copie = {"type": "email", "from": "direction@exemple-paysage.fr",
                   "preview": "Bonjour François, merci pour votre proposition et le temps que vous y avez consacré."}
    carte_recue = {"type": "email", "from": "francois@exemple.fr",
                   "preview": "Bonjour, je reviens vers vous au sujet de notre plan d'action marketing."}
    verifier("la carte `email` qui recopie le brouillon (expédiée par la boîte même) s'efface",
             esp6["_apercu_du_brouillon"](carte_copie, [CORPS_V2], ["direction@exemple-paysage.fr"]))
    verifier("la carte d'un mail REÇU reste",
             not esp6["_apercu_du_brouillon"](carte_recue, [CORPS_V2], ["direction@exemple-paysage.fr"]))

# ── 7. Le câblage ───────────────────────────────────────────────────────────
print("7. Le câblage")
skills_src = (racine / "mail" / "skills.py").read_text(encoding="utf-8")
agent1 = (racine / "agents" / "agent1.py").read_text(encoding="utf-8")
protocole = (racine / "skills" / "protocol.py").read_text(encoding="utf-8")
verifier("deposer_brouillon : enregistré, effet interne (rien ne sort)",
         '"deposer_brouillon": deposer_brouillon' in skills_src and '"deposer_brouillon": "ecriture_interne"' in skills_src)
verifier("le catalogue porte deposer_brouillon et la retouche", '"deposer_brouillon": (' in protocole
         and '"retoucher", "version_precedente", "ref"' in protocole)
verifier("le serveur donne la conversation aux gestes du brouillon",
         '"redaction_email",' in agent1.split("SKILLS_QUI_CONNAISSENT_LE_FIL = ")[1][:200]
         and "deposer_brouillon" in agent1.split("SKILLS_QUI_CONNAISSENT_LE_FIL = ")[1][:200])
verifier("le filet de la livraison fantôme connaît le brouillon prétendu",
         "pretend_brouillon_depose(visible)" in agent1)
verifier("les suggestions ne proposent plus « Joins le devis » sous un brouillon",
         "Mets-le dans mes brouillons" in (racine / "agents" / "suggestions_metier.py").read_text(encoding="utf-8"))
verifier("le journal a son libellé", "deposer_brouillon" in (racine / "agents" / "journal.py").read_text(encoding="utf-8"))
carte_src = (racine.parent / "frontend/components/blocks/business/ReponsesMail.tsx").read_text(encoding="utf-8")
verifier("la carte a son bouton « Mettre dans mes brouillons »",
         "Mettre dans mes brouillons" in carte_src and "dans les brouillons de ma boîte mail" in carte_src)

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s)")
    sys.exit(1)
print("✓ 0 échec")
