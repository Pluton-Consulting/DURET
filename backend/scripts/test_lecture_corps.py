"""
Banc du corps des mails — « l'assistant lit le message, pas son aperçu ».

POURQUOI. Le 31/08, Noa : « il n'arrive pas à lire les corps de mails complets,
il lit que les aperçus, qui sont donc coupés ». Deux causes qui s'additionnaient :
la lecture Outlook ne demandait à Graph que `bodyPreview` (plafonné à ~255
caractères par Microsoft, le corps n'était JAMAIS lu), et le résultat d'un skill
est tranché à 4 000 caractères avant d'atteindre le modèle — dix extraits de 800
n'y tenaient pas, la liste arrivait coupée au milieu. Et aucun geste n'ouvrait
UN message en entier.

CE QUE CE BANC PROUVE, sans réseau ni base : les fonctions PURES de
`mail/lecture.py` (texte lisible, budget d'extrait partagé, références courtes,
choix d'un candidat), les paramètres Graph (le corps est demandé, en texte), le
geste `lire_message` sur un fournisseur doublé (corps entier, coupure DITE,
retrouvé par sa ref ou par son objet), et le câblage jusqu'au modèle : skill
`lire_mail` déclaré, effet lecture, catalogue, journal, résultats généreux,
`check_mails` qui porte la ref. Sur la version d'avant, il tombe.
"""
import asyncio
import logging
import pathlib
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def lire(rel: str) -> str:
    try:
        return (BACKEND / rel).read_text(encoding="utf-8")
    except OSError:
        return ""


src = lire("mail/lecture.py")
print(f"\n═══ LE CORPS DES MAILS — {BACKEND.parent}\n")

# ── Extraction du code livré : tout sauf les deux imports du projet ──────────
espace = {"Optional": Optional, "datetime": datetime, "timedelta": timedelta,
          "timezone": timezone, "__name__": "banc_lecture"}
try:
    tete = src[: src.index("def _domaine_entreprise(")]
    tete = re.sub(r"^from config import settings\n|^from mail\.collecte import fournisseur\n",
                  "", tete, flags=re.M)
    exec(tete, espace)  # noqa: S102 — code du dépôt
    exec(src[src.index("def _kql_echapper("): src.index("async def _lire_outlook(")], espace)  # noqa: S102
    exec(src[src.index("async def lire_message("):], espace)  # noqa: S102
    extrait_ok = True
except (ValueError, NameError, SyntaxError) as e:
    extrait_ok = False
    verifier("le code de lecture porte les nouvelles fonctions", False, repr(e))

if extrait_ok:
    _texte_lisible = espace["_texte_lisible"]
    _apercu = espace["_apercu"]
    _budget_apercu = espace["_budget_apercu"]
    _memoriser, _resoudre, _choisir = espace["_memoriser"], espace["_resoudre"], espace["_choisir"]
    _params_outlook, _corps_outlook = espace["_params_outlook"], espace["_corps_outlook"]
    _fiche_outlook = espace["_fiche_outlook"]
    MAX_APERCU, MAX_CORPS = espace["MAX_APERCU"], espace["MAX_CORPS"]
    ENTETE = espace["ENTETE_MESSAGE"]
    espace["_qualifier"] = lambda a: {"adresse": a, "interne": False, "automatique": False}

    print("1. Le texte d'un corps, lisible")
    html = ("<html><head><style>p{color:red}</style></head><body><p>Bonjour,</p>"
            "<p>Le devis&nbsp;n°12 est <b>accept&eacute;</b>.</p><!-- x --><div>Cordialement</div>"
            "</body></html>")
    t = _texte_lisible(html)
    verifier("balises, style et commentaires retirés", "<" not in t and "color" not in t and "x" not in t.split("Cordialement")[0][-5:])
    verifier("entités décodées (&nbsp;, &eacute;)", "devis n°12 est accepté." in t, t)
    verifier("les paragraphes restent des lignes", t.split("\n\n")[0] == "Bonjour," and t.endswith("Cordialement"), t)
    brut = "Bonjour,\r\n\r\nvoir <contact@x.fr>\r\n\r\n\r\n\r\nMerci"
    verifier("un texte brut citant <adresse> n'est pas pris pour du HTML", "<contact@x.fr>" in _texte_lisible(brut))
    verifier("CRLF normalisés, lignes vides repliées à une", _texte_lisible(brut).count("\n\n\n") == 0)
    verifier("un HTML explicite l'emporte sur l'apparence", _texte_lisible("a<br>b", html=True) == "a\nb")

    print("\n2. L'extrait d'une liste : un budget PARTAGÉ")
    long_ = "mot " * 1000
    verifier("un extrait seul vaut 800", len(_apercu(long_)) == MAX_APERCU == 800)
    verifier("la longueur se donne", len(_apercu(long_, 160)) == 160)
    b1, b10, b25 = _budget_apercu(1), _budget_apercu(10), _budget_apercu(25)
    verifier("1 message : l'extrait entier", b1 == MAX_APERCU)
    verifier("10 messages : encore au moins 500 caractères", 500 <= b10 < MAX_APERCU, str(b10))
    verifier("25 messages : le plancher de 160", b25 == 160, str(b25))
    verifier("décroissant avec le nombre", b1 >= b10 >= b25)
    verifier("25 fiches tiennent sous les 12 000 du résultat généreux", 25 * (b25 + ENTETE) + 1200 <= 12000)

    print("\n3. Graph : le CORPS est demandé, en texte")
    for regime, p in (("sans recherche", _params_outlook(25, None)),
                      ("avec recherche", _params_outlook(25, None, "terrasse"))):
        sel = str(p.get("$select", "")).split(",")
        verifier(f"{regime} : $select porte body (pas seulement bodyPreview)", "body" in sel, p.get("$select"))
        verifier(f"{regime} : $select porte id et hasAttachments", "id" in sel and "hasAttachments" in sel)
    verifier("Prefer body-content-type=text sur la liste",
             re.search(r"async def _lire_outlook.*?\"Prefer\": PREFER_OUTLOOK_TEXTE", src, re.S) is not None)
    verifier("Prefer body-content-type=text à l'ouverture",
             re.search(r"async def _ouvrir_outlook.*?\"Prefer\": PREFER_OUTLOOK_TEXTE", src, re.S) is not None)
    verifier("la valeur de Prefer est celle de Graph", espace["PREFER_OUTLOOK_TEXTE"] == 'outlook.body-content-type="text"')

    print("\n4. Le corps d'un message Graph")
    m = {"id": "AAMk" + "x" * 140, "subject": "Devis", "bodyPreview": "Bonjour, je souhaite",
         "body": {"contentType": "html", "content": "<p>Bonjour, je souhaite un devis pour " + "une terrasse " * 200 + "</p>"},
         "hasAttachments": True, "from": {"emailAddress": {"address": "client@ext.fr"}}}
    c = _corps_outlook(m)
    verifier("body l'emporte sur bodyPreview (le corps entier, pas 255 caractères)", len(c) > 2000 and "<p>" not in c)
    verifier("sans body, repli sur bodyPreview", _corps_outlook({"bodyPreview": "abc"}) == "abc")
    verifier("un body texte n'est pas « dé-HTMLisé »", _corps_outlook({"body": {"contentType": "text", "content": "a <b> c"}}) == "a <b> c")
    f = _fiche_outlook(m, "boite@x.fr", 160)
    verifier("la fiche d'une liste : extrait à la longueur du budget", len(f["apercu"]) == 160)
    verifier("la fiche porte une ref courte (16 hexa), pas l'identifiant Graph", re.fullmatch(r"[0-9a-f]{16}", f["ref"]) is not None)
    verifier("la fiche dit s'il y a des pièces jointes", f["pieces_jointes"] is True)

    print("\n5. Les références courtes, liées à la boîte")
    ident = "AAMk" + "y" * 150
    ref = _memoriser(ident, "Nathalie@X.fr")
    verifier("la ref se résout pour SA boîte (casse indifférente)", _resoudre(ref, "nathalie@x.fr") == ident)
    verifier("la ref ne s'ouvre PAS dans une autre boîte", _resoudre(ref, "eric@x.fr") is None)
    verifier("un identifiant brut recopié passe tel quel", _resoudre(ident, "eric@x.fr") == ident)
    verifier("une ref inconnue et courte → rien (on cherchera par objet)", _resoudre("0123456789abcdef", "x@x.fr") is None)
    verifier("ref vide → rien", _resoudre("", "x@x.fr") is None and _resoudre(None, "x") is None)

    print("\n6. Retrouver par l'objet")
    cands = [{"ref": "a", "objet": "Newsletter", "de": "info@a.fr"},
             {"ref": "b", "objet": "RE: devis terrasse", "de": "client@ext.fr"},
             {"ref": "c", "objet": "Devis terrasse", "de": "autre@ext.fr"}]
    verifier("« devis terrasse » retrouve le message malgré le RE:", _choisir(cands, "devis terrasse", None)["ref"] in ("b", "c"))
    verifier("l'expéditeur départage", _choisir(cands, "devis terrasse", "autre@ext.fr")["ref"] == "c")
    verifier("sans candidat → None", _choisir([], "x", None) is None)
    verifier("sans correspondance → le premier (la recherche du fournisseur a déjà trié)", _choisir(cands, "zzz", None)["ref"] == "a")

    print("\n7. lire_message sur un fournisseur doublé")
    appels = []

    async def _ouvrir(boite, identifiant):
        appels.append(("ouvrir", boite, identifiant))
        return {"ref": "r", "objet": "Devis terrasse", "de": "client@ext.fr", "a": "", "date": "",
                "date_iso": "", "lu": False, "apercu": "x", "pieces_jointes": [{"nom": "plan.pdf"}],
                "corps": "Bonjour. " + "Ligne du message. " * 800}

    async def _lister(boite, dossier, limite, depuis, recherche=None, avant=None):
        appels.append(("lister", dossier, limite, recherche))
        ref_ = _memoriser("ID-TROUVE-" + "z" * 30, boite)
        return [{"ref": ref_, "objet": "RE: Devis terrasse", "de": "client@ext.fr"}], None

    espace.update({"fournisseur": lambda: "outlook", "_ouvrir_outlook": _ouvrir,
                   "_lire_outlook": _lister, "logger": logging.getLogger("banc")})
    lire_message = espace["lire_message"]
    ref = _memoriser("ID-CONNU-" + "w" * 30, "nath@x.fr")
    r = asyncio.run(lire_message("nath@x.fr", ref=ref))
    verifier("par sa ref : ouverture directe, sans recherche", appels and appels[-1][0] == "ouvrir" and appels[-1][2].startswith("ID-CONNU"))
    verifier("le corps est rendu jusqu'à MAX_CORPS", len(r["corps"]) == MAX_CORPS)
    verifier("la coupure est DITE (corps_tronque, longueur, a_faire)", r["corps_tronque"] is True and r["longueur"] > MAX_CORPS and "n'ont pas été lus" in r["a_faire"])
    verifier("les pièces jointes sont nommées", r["pieces_jointes"][0]["nom"] == "plan.pdf")
    verifier("l'aperçu disparaît de la fiche ouverte (le corps le remplace)", "apercu" not in r)
    appels.clear()
    r = asyncio.run(lire_message("nath@x.fr", ref="inconnue", objet="devis terrasse", dossier="envoyes"))
    verifier("ref inconnue + objet : une recherche dans le bon dossier, puis l'ouverture",
             [a[0] for a in appels] == ["lister", "ouvrir"] and appels[0][1] == "sentitems" and appels[0][3] == "devis terrasse")
    verifier("le message ouvert est celui que la recherche a trouvé", appels[1][2].startswith("ID-TROUVE"))
    try:
        asyncio.run(lire_message("nath@x.fr"))
        verifier("sans ref ni objet : refus explicite", False)
    except ValueError as e:
        verifier("sans ref ni objet : refus explicite", "référence" in str(e))

    async def _rien(*a, **k):
        return [], None
    espace["_lire_outlook"] = _rien
    try:
        asyncio.run(lire_message("nath@x.fr", objet="introuvable"))
        verifier("aucun candidat : LookupError, pas une ouverture à l'aveugle", False)
    except LookupError:
        verifier("aucun candidat : LookupError, pas une ouverture à l'aveugle", True)

    print("\n8. La liste dit que l'extrait n'est pas le message")
    verifier("`pour_lire_en_entier` dans le résultat de lire_boite", '"pour_lire_en_entier"' in src and "`lire_mail` avec sa `ref`" in src)

print("\n9. Le câblage jusqu'au modèle")
skills = lire("mail/skills.py")
verifier("skill `lire_mail` déclaré", 'SKILLS_NATIFS["lire_mail"] = lire_mail' in skills)
verifier("effet LECTURE déclaré (fail-closed sinon)", re.search(r'"lire_mail":\s*"lecture"', skills) is not None)
verifier("le skill résout la boîte et vérifie l'accès comme lire_mails",
         re.search(r"async def lire_mail\(.*?_boite_a_lire\(data, user\).*?verifier_acces\(user, cible\)", skills, re.S) is not None)
protocole = lire("skills/protocol.py")
verifier("catalogue : `lire_mail` avec ref / objet / de", re.search(r'"lire_mail": \(.*?\["ref", "objet", "de", "dossier", "mailbox"\]', protocole, re.S) is not None)
verifier("catalogue : lire_mails dit que l'aperçu est un EXTRAIT", "EXTRAIT, pas le message" in protocole)
agent1 = lire("agents/agent1.py")
m = re.search(r"RESULTATS_GENEREUX = \{([^}]*)\}", agent1)
genereux = set(re.findall(r'"(\w+)"', m.group(1))) if m else set()
verifier("résultats généreux : lire_mails, lire_mail, check_mails (sinon coupés à 4 000)",
         {"lire_mails", "lire_mail", "check_mails"} <= genereux, str(sorted(genereux)))
verifier("le prompt d'agent1 nomme `lire_mail` pour OUVRIR un message", "`lire_mail` pour OUVRIR" in agent1)
verifier("journal : « j'ouvre le message »", '"lire_mail": "j\'ouvre le message"' in lire("agents/journal.py"))
routines = lire("skills/routines.py")
verifier("check_mails porte la ref de chaque message", '"ref": _champ(m, "ref")' in routines)
verifier("check_mails dit d'ouvrir le message si l'extrait ne suffit pas", "ouvre le message" in routines and "`lire_mail`" in routines)
verifier("check_mails demande SON budget d'extrait (240 à 25 messages, 800 dès 10) et ne coupe plus à 400",
         '"apercu": apercu' in routines and "[:800]," in routines and "[:400]," not in routines
         and max(160, min(800, (10500 - 25 * 180) // 25)) == 240 and max(160, min(800, (10500 - 10 * 180) // 10)) == 800)
verifier("lire_mails transmet `apercu` et lire_boite l'applique (borné 160–800)",
         'apercu=data.get("apercu")' in skills and "def _longueur_apercu(" in src and "apercu=apercu)" in src)
verifier("tableau de bord : lire_mail compte comme un mail relevé", lire("routers/tableau.py").count("'lire_mail'") == 2)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
