"""
Banc de l'ENVOI de mail — le message part exact, ou il ne part pas.

L'envoi réel (`envoyer_email` + `mail/expedition.py`) est né le 30/08 : jusque
là l'assistant savait lire et rédiger, jamais faire partir — il l'a même promis
un jour sans le pouvoir (défaut n°4 du 27/08). Ce banc vérifie, sans base ni
réseau :

  · les CONSTRUCTEURS purs (corps du POST Graph, MIME Gmail) — ce qui part est
    exactement ce qu'on a validé, copies comprises ;
  · les REFUS mécaniques du skill : pas de destinataire, une balise de masquage
    jamais résolue, un [À COMPLÉTER] résiduel — un message abîmé ne part pas ;
  · les DÉCLARATIONS : effet `externe` (validation humaine), catalogue, libellé
    d'écran, et l'aperçu avant accord qui MONTRE le message.
"""
import ast
import asyncio
import base64
import importlib.util
import json
import pathlib
import sys

BACKEND = sys.argv[1] if len(sys.argv) > 1 else "backend"
racine = pathlib.Path(BACKEND)

echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def extraire(chemin, noms, espace):
    """Exécute, du module livré, les seules définitions demandées."""
    arbre = ast.parse(pathlib.Path(chemin).read_text(encoding="utf-8"))
    gardes = []
    for n in arbre.body:
        if isinstance(n, ast.ImportFrom) and n.module == "__future__":
            gardes.append(n)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in noms:
            gardes.append(n)
        elif isinstance(n, ast.Assign) and any(
                isinstance(c, ast.Name) and c.id in noms for c in n.targets):
            gardes.append(n)
    exec(compile(ast.Module(body=gardes, type_ignores=[]), str(chemin), "exec"), espace)
    manquants = [x for x in noms if x not in espace]
    assert not manquants, f"absent du module livré : {manquants}"
    return espace


print(f"\n═══ L'ENVOI DE MAIL — {BACKEND}\n")

# ── 1. expedition : les constructeurs purs ─────────────────────────────────
sys.path.insert(0, str(racine))
spec = importlib.util.spec_from_file_location("mail.expedition",
                                              racine / "mail" / "expedition.py")
exp = importlib.util.module_from_spec(spec)
sys.modules["mail.expedition"] = exp
spec.loader.exec_module(exp)

g = exp._message_graph("client@exemple.fr", "Votre devis n° 42", "Bonjour,\nvoici.",
                       cc="compta@exemple.fr, chef@exemple.fr")
verifier("Graph : le destinataire est dans toRecipients",
         g["message"]["toRecipients"][0]["emailAddress"]["address"] == "client@exemple.fr")
verifier("Graph : les copies en chaîne sont découpées",
         [c["emailAddress"]["address"] for c in g["message"]["ccRecipients"]]
         == ["compta@exemple.fr", "chef@exemple.fr"], json.dumps(g))
verifier("Graph : objet et corps passent tels quels",
         g["message"]["subject"] == "Votre devis n° 42"
         and g["message"]["body"]["content"] == "Bonjour,\nvoici.")
verifier("Graph : le message envoyé se range dans les éléments envoyés",
         g["saveToSentItems"] is True)
verifier("Graph : sans copie, pas de champ ccRecipients",
         "ccRecipients" not in exp._message_graph("a@b.fr", "o", "c")["message"])

brut = base64.urlsafe_b64decode(
    exp._mime_gmail("nathalie@exemple.fr", "client@exemple.fr",
                    "Métrés du chantier Épinay", "Corps du message.",
                    cc=["compta@exemple.fr"]))
verifier("Gmail : le MIME porte destinataire, expéditeur et copie",
         b"To: client@exemple.fr" in brut and b"From: nathalie@exemple.fr" in brut
         and b"Cc: compta@exemple.fr" in brut, brut[:200].decode("ascii", "replace"))
verifier("Gmail : un objet accentué survit à l'encodage", b"=?utf-8?" in brut)
import email as _email  # noqa: E402 — le corps est encodé (base64), on le DÉCODE
_msg = _email.message_from_bytes(brut)
verifier("Gmail : le corps se décode à l'identique",
         _msg.get_payload(decode=True).decode("utf-8") == "Corps du message.",
         str(_msg.get_payload()))

verifier("une balise jamais résolue est reconnue", exp.porte_un_jeton("Bonjour [PER_1],"))
verifier("un texte normal ne l'est pas", not exp.porte_un_jeton("Bonjour Madame Dupont,"))
verifier("[À COMPLÉTER] n'est pas un jeton (il a son propre refus)",
         not exp.porte_un_jeton("solde : [À COMPLÉTER]"))

# ── 2. le skill : ce qui ne part pas ───────────────────────────────────────
print()


class MailSkillError(Exception):
    def __init__(self, detail):
        self.detail = detail
        super().__init__(detail)


async def _boite_a_lire(data, user):
    return getattr(user, "email", "")


async def verifier_acces(user, cible, envoi=False):
    return cible


espace = {"MailSkillError": MailSkillError, "_boite_a_lire": _boite_a_lire,
          "verifier_acces": verifier_acces}
extraire(racine / "mail" / "skills.py", {"envoyer_email"}, espace)
skill = espace["envoyer_email"]


class _Moi:
    email = "nathalie@exemple.fr"


def refuse(data, attendu):
    try:
        asyncio.run(skill(data, _Moi()))
    except MailSkillError as e:
        return attendu in str(e.detail)
    return False


verifier("sans destinataire, refus qui interdit d'inventer",
         refuse({"objet": "o", "corps": "c"}, "invente jamais"))
verifier("un destinataire sans @ est refusé",
         refuse({"destinataire": "le client", "objet": "o", "corps": "c"}, "adresse exacte"))
verifier("sans objet ou sans corps, refus",
         refuse({"destinataire": "a@b.fr", "corps": "c"}, "COMPLET"))
verifier("une balise de masquage dans le corps ne part JAMAIS",
         refuse({"destinataire": "a@b.fr", "objet": "o",
                 "corps": "Bonjour [PER_1], votre devis."}, "balise de masquage"))
verifier("un [À COMPLÉTER] résiduel ne part jamais non plus",
         refuse({"destinataire": "a@b.fr", "objet": "o",
                 "corps": "Le solde est de [À COMPLÉTER] euros."}, "COMPLÉTER"))

# L'envoi qui aboutit : l'expédition est doublée, le compte rendu est vérifié.
appels = []


async def _faux_envoi(boite, destinataire, objet, corps, cc=None,
                      pieces=None, html=""):
    appels.append((boite, destinataire, objet, corps, cc))
    return {"envoye": True, "boite": boite, "destinataire": destinataire, "objet": objet}

_vrai = exp.envoyer_message
exp.envoyer_message = _faux_envoi
try:
    r = asyncio.run(skill({"destinataire": "client@exemple.fr",
                           "objet": "Votre devis", "corps": "Bonjour, voici."}, _Moi()))
finally:
    exp.envoyer_message = _vrai
verifier("l'envoi passe par la boîte de la personne connectée",
         appels and appels[0][0] == _Moi.email, str(appels))
verifier("le compte rendu nomme destinataire, boîte et objet",
         r.get("envoye") is True and "client@exemple.fr" in r["message_final"]
         and _Moi.email in r["message_final"] and "Votre devis" in r["message_final"],
         str(r))

# ── 3. déclarations : effet, catalogue, libellé, aperçu ────────────────────
print()

skills_src = (racine / "mail" / "skills.py").read_text(encoding="utf-8")
verifier("l'effet déclaré est EXTERNE — validation humaine obligatoire",
         '"envoyer_email": "externe"' in skills_src)
verifier("le skill est enregistré dans SKILLS_NATIFS",
         '"envoyer_email": envoyer_email' in skills_src)

protocole = (racine / "skills" / "protocol.py").read_text(encoding="utf-8")
verifier("le catalogue exige destinataire, objet et corps",
         '["destinataire", "objet", "corps"], ["mailbox", "cc"' in protocole)
verifier("le catalogue accepte des pièces jointes et le retrait de signature",
         '"pieces", "signature"]' in protocole)
verifier("le catalogue distingue ENVOYER de rédiger",
         "redaction_email" in protocole.split('"envoyer_email"')[1][:900])

verifier("le journal a son libellé « je … »",
         "j'envoie le message" in (racine / "agents" / "journal.py").read_text(encoding="utf-8"))


class _Journal:
    def info(self, *a, **k):
        pass
    warning = info


espace_a = {"logger": _Journal()}
extraire(racine / "agents" / "agent1.py", {"_apercu_avant_accord"}, espace_a)
apercu = espace_a["_apercu_avant_accord"]("envoyer_email",
                                          {"destinataire": "client@exemple.fr",
                                           "objet": "Votre devis",
                                           "corps": "Bonjour,\nvoici le devis.",
                                           "cc": ["compta@exemple.fr"]},
                                          "J'envoie le devis au client.")
verifier("l'aperçu avant accord montre le message exact — pas de clic à l'aveugle",
         "client@exemple.fr" in apercu and "Votre devis" in apercu
         and "voici le devis." in apercu and "compta@exemple.fr" in apercu, apercu[:300])

print(f"\n═══ {len(echecs)} échec(s)" + (" — tout passe" if not echecs else f" : {echecs}"))
sys.exit(1 if echecs else 0)
