"""
Banc « LES SESSIONS ET LES CONNEXIONS GOOGLE » — audit du 15/09, fiche D-19.

CE QUI ÉTAIT FAUX :
  · le jeton de rafraîchissement d'un compte Google — une clé PERMANENTE vers
    le Drive et la boîte de la personne — était écrit en clair dans
    `connexions_google.refresh_token` ;
  · l'état OAuth était signé et daté, mais REJOUABLE dix minutes durant : un
    retour Google capturé pouvait être renvoyé ;
  · rien ne bornait les demandes de lien de connexion ni les essais de
    vérification : mille demandes faisaient mille mails partis de notre domaine ;
  · un compte relié valait pour TOUT : lire le Drive, écrire un brouillon
    Gmail, ouvrir l'agenda — alors que Google ne rend que les droits consentis ;
  · le lien de connexion s'imprimait dans les journaux dès que `DEBUG` était
    vrai, y compris sur un serveur.

CE BANC PROUVE (modules EXÉCUTÉS, base et Google doublés) :
  1. le coffre chiffre, déchiffre, sépare les usages, lit le clair d'avant et
     dit quand une clé a changé ;
  2. un état OAuth ne sert qu'une fois, et un jeton d'un autre usage est refusé ;
  3. les capacités suivent les droits RENDUS, et un droit manquant se dit ;
  4. les essais ratés sont comptés par origine, une entrée réussie efface, et
     la réponse ne change pas quand la borne mord ;
  5. `enregistrer` écrit un jeton CHIFFRÉ, `rafraichir` le relit et met au
     coffre les lignes d'avant, sans les couper ;
  6. le lien de connexion ne s'imprime qu'en développement.

Usage : python backend/scripts/test_connexions_google.py [backend]
"""
import asyncio
import importlib.util
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
# Les tickets OAuth utilisent le vrai SQLite, isolé pour ce banc.
import os, tempfile, atexit
sys.path.insert(0, str(BACKEND.resolve()))
_repertoire_tickets = tempfile.TemporaryDirectory(prefix="banc-oauth-")
atexit.register(_repertoire_tickets.cleanup)
os.environ["DOCUMENTS_DIR"] = _repertoire_tickets.name

echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {str(detail)[:300]}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def poser(nom, **attrs):
    mod = types.ModuleType(nom)
    mod.__dict__.update(attrs)
    mod.__path__ = []
    sys.modules[nom] = mod
    if "." in nom:
        parent, feuille = nom.rsplit(".", 1)
        if parent not in sys.modules:
            poser(parent)
        setattr(sys.modules[parent], feuille, mod)
    return mod


def charger(nom, chemin):
    spec = importlib.util.spec_from_file_location(nom, BACKEND / chemin)
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    if "." in nom:
        parent, feuille = nom.rsplit(".", 1)
        if parent not in sys.modules:
            poser(parent)
        setattr(sys.modules[parent], feuille, module)
    spec.loader.exec_module(module)
    return module


print(f"\n═══ SESSIONS ET CONNEXIONS GOOGLE — {BACKEND.parent}\n")

REGLAGES = types.SimpleNamespace(jetons_chiffrement_cle="", jwt_secret_key="secret-de-session",
                                 app_url="https://exemple-sols.fr", debug=True,
                                 environment="production")
poser("config", settings=REGLAGES)
coffre = charger("security.coffre", "security/coffre.py")
sys.modules["security"].__path__ = [str(BACKEND / "security")]

print("1. Le coffre : chiffrer ce qui ouvre une porte ailleurs")
if not coffre.disponible():
    print("  (SAUTÉ : la bibliothèque `cryptography` n'est pas installée ici — "
          "elle vient avec pyjwt[crypto] dans l'image)")
else:
    chiffre = coffre.chiffrer("1//jeton-de-rafraichissement", "google-refresh")
    verifier("un jeton chiffré ne ressemble pas au clair, et se reconnaît",
             chiffre != "1//jeton-de-rafraichissement" and coffre.chiffre(chiffre), chiffre)
    verifier("il se relit tel quel",
             coffre.dechiffrer(chiffre, "google-refresh") == "1//jeton-de-rafraichissement")
    verifier("un autre USAGE ne le déchiffre pas (un coffre par porte)",
             coffre.dechiffrer(chiffre, "autre-usage") is None)
    verifier("une valeur en clair d'avant le coffre se lit telle quelle",
             coffre.dechiffrer("1//ancien-jeton", "google-refresh") == "1//ancien-jeton")
    verifier("… et l'on sait qu'elle doit être réécrite",
             coffre.a_rechiffrer("1//ancien-jeton") and not coffre.a_rechiffrer(chiffre))
    verifier("chiffrer deux fois ne double pas l'enveloppe",
             coffre.chiffrer(chiffre, "google-refresh") == chiffre)
    REGLAGES.jetons_chiffrement_cle = "une-cle-dediee-tout-a-fait-neuve"
    avec_cle = coffre.chiffrer("1//jeton", "google-refresh")
    verifier("la clé dédiée prime, et l'ancienne dérivation reste LISIBLE "
             "(rotation sans perte)",
             coffre.dechiffrer(avec_cle, "google-refresh") == "1//jeton"
             and coffre.dechiffrer(chiffre, "google-refresh") == "1//jeton-de-rafraichissement")
    REGLAGES.jetons_chiffrement_cle = "cle-changee"
    REGLAGES.jwt_secret_key = "autre-secret"
    verifier("une clé perdue rend « illisible », jamais une chaîne inutilisable",
             coffre.dechiffrer(avec_cle, "google-refresh") is None)
    REGLAGES.jetons_chiffrement_cle = ""
    REGLAGES.jwt_secret_key = "secret-de-session"

print("2. L'état OAuth ne sert qu'une fois")
JETONS = {}


def _creer(charge, expires_delta=None):
    jeton = f"jeton-{len(JETONS)}"
    JETONS[jeton] = dict(charge)
    return jeton


poser("auth.jwt_handler", create_access_token=_creer,
      decode_access_token=lambda j: JETONS.get(j) or (_ for _ in ()).throw(ValueError("signature")))
poser("httpx")
poser("database.connection", get_db=lambda: None, schema_incomplet=lambda e: False)
poser("llm.cles", valeur=lambda cle, *a, **k: {
    "google_oauth_client_id": "client-de-recette.apps.googleusercontent.com",
    "google_oauth_client_secret": "secret-de-recette",
}.get(cle))
google = charger("mail.google_perso", "mail/google_perso.py")

google._CACHE = {}
google._SCOPES_PAR_EMAIL = {}
lien = google.lien_autorisation("personne-1", compte="paysage@exemple-sols.fr")
etat = lien.split("state=")[1].split("&")[0]
verifier("le lien porte un état, et l'état porte l'identité et son usage",
         JETONS[etat]["sub"] == "personne-1" and JETONS[etat]["usage"] == google.USAGE_STATE)
verifier("l'état s'ouvre une fois", google.verifier_state(etat) == "personne-1")
rejeu = None
try:
    google.verifier_state(etat)
except ValueError as e:
    rejeu = str(e)
verifier("… et le REJEU est refusé, en le disant", rejeu and "déjà utilisé" in rejeu, rejeu)
autre = _creer({"sub": "personne-1", "usage": "session"})
refus = None
try:
    google.verifier_state(autre)
except ValueError as e:
    refus = str(e)
verifier("un jeton d'un AUTRE usage ne vaut pas un état OAuth", refus == "state OAuth invalide", refus)
ancien = _creer({"sub": "personne-2", "usage": google.USAGE_STATE})
verifier("un état émis avant ce correctif (sans marque) reste accepté le temps "
         "que les liens en vol s'éteignent", google.verifier_state(ancien) == "personne-2")

print("3. Les capacités suivent les droits RENDUS par Google")
google._CACHE = {"lecture@exemple-sols.fr": "j1", "complet@exemple-sols.fr": "j2"}
google._SCOPES_PAR_EMAIL = {
    "lecture@exemple-sols.fr": ["https://www.googleapis.com/auth/drive.readonly"],
    "complet@exemple-sols.fr": ["https://www.googleapis.com/auth/drive",
                                   "https://www.googleapis.com/auth/gmail.compose"],
}
verifier("lire le Drive ne donne pas le droit d'y écrire",
         google.peut("lecture@exemple-sols.fr", "drive_lecture")
         and not google.peut("lecture@exemple-sols.fr", "drive_ecriture"))
verifier("… ni celui de poser un brouillon Gmail",
         not google.peut("lecture@exemple-sols.fr", "gmail_brouillon"))
verifier("le compte complet peut écrire sur le Drive et poser un brouillon",
         google.peut("complet@exemple-sols.fr", "drive_ecriture")
         and google.peut("complet@exemple-sols.fr", "gmail_brouillon"))
verifier("un compte NON relié n'a aucune capacité (fail-closed), et ce n'est pas "
         "la même chose qu'un droit manquant",
         google.capacites("inconnu@exemple-sols.fr") is None
         and not google.peut("inconnu@exemple-sols.fr", "drive_lecture"))
message = google.refus_de_capacite("lecture@exemple-sols.fr", "drive_ecriture")
verifier("le refus dit QUOI FAIRE, pas seulement que c'est refusé",
         "Reliez-le à nouveau" in message and "Mon compte Google" in message, message)
verifier("un compte inconnu reçoit l'autre message",
         "n'est pas relié" in google.refus_de_capacite("inconnu@x.fr", "drive_lecture"))

print("4. Les essais ratés, comptés par origine")
tentatives = charger("security.tentatives", "security/tentatives.py")
verifier("l'origine vient de X-Forwarded-For quand nginx la pose",
         tentatives.origine_de("203.0.113.9, 10.0.0.1", "10.0.0.1") == "203.0.113.9")
verifier("… sinon de la connexion", tentatives.origine_de("", "198.51.100.4") == "198.51.100.4")
for _ in range(tentatives.ESSAIS_MAX - 1):
    tentatives.noter_echec("203.0.113.9")
verifier("sous la borne, on laisse passer", not tentatives.saturee("203.0.113.9"))
tentatives.noter_echec("203.0.113.9")
verifier("à la borne, l'origine est saturée", tentatives.saturee("203.0.113.9"))
verifier("une AUTRE origine n'est pas touchée (on ne ferme pas la porte de tout le monde)",
         not tentatives.saturee("198.51.100.4"))
tentatives.oublier("203.0.113.9")
verifier("une entrée réussie efface les essais", not tentatives.saturee("203.0.113.9"))

print("5. Ce qui est écrit en base est chiffré, ce qui était clair y passe")
REGLAGES.jetons_chiffrement_cle = "cle-du-coffre-de-recette"
ECRITS = []
LIGNES = [{"user_id": "personne-1", "email": "Ancien@exemple-sols.fr",
           "refresh_token": "1//en-clair-d-avant", "scopes": "https://www.googleapis.com/auth/drive"}]


class _Conn:
    async def execute(self, sql, *args):
        ECRITS.append((sql, args))
        if "INSERT INTO connexions_google" in sql:
            LIGNES.append({"user_id": args[0], "email": args[1],
                           "refresh_token": args[2], "scopes": args[3]})
        if "UPDATE connexions_google SET refresh_token" in sql:
            for l in LIGNES:
                if l["user_id"] == args[0]:
                    l["refresh_token"] = args[1]
        return "OK"

    async def fetch(self, sql, *args):
        return list(LIGNES)

    async def fetchrow(self, sql, *args):
        return LIGNES[0] if LIGNES else None


class _Db:
    async def __aenter__(self):
        return _Conn()

    async def __aexit__(self, *a):
        return False


sys.modules["database.connection"].get_db = lambda: _Db()
if coffre.disponible():
    asyncio.run(google.enregistrer("personne-9", "Neuf@exemple-sols.fr", "1//tout-neuf",
                                   "https://www.googleapis.com/auth/drive"))
    ecrit = [a for s, a in ECRITS if "INSERT INTO connexions_google" in s][0]
    verifier("le jeton écrit en base est CHIFFRÉ, jamais le clair",
             coffre.chiffre(ecrit[2]) and "1//tout-neuf" not in str(ecrit[2]), ecrit[2])
    verifier("l'adresse est normalisée en passant", ecrit[1] == "neuf@exemple-sols.fr")
    verifier("le cache, lui, porte le jeton utilisable",
             google._CACHE.get("neuf@exemple-sols.fr") == "1//tout-neuf",
             list(google._CACHE))
    verifier("la ligne EN CLAIR d'avant reste lisible (aucun compte coupé au déploiement)",
             google._CACHE.get("ancien@exemple-sols.fr") == "1//en-clair-d-avant")
    verifier("… et elle a été mise au coffre au passage",
             coffre.chiffre(LIGNES[0]["refresh_token"]), LIGNES[0]["refresh_token"])
    REGLAGES.jetons_chiffrement_cle = "une-cle-tout-a-fait-differente"
    REGLAGES.jwt_secret_key = "et-un-autre-secret"
    asyncio.run(google.rafraichir(force=True))
    verifier("clé changée : la connexion illisible est ÉCARTÉE, pas devinée",
             "neuf@exemple-sols.fr" not in google._CACHE, list(google._CACHE))
    verifier("… et la ligne reste en base (l'écran dira « reliez à nouveau »)",
             any(l["user_id"] == "personne-9" for l in LIGNES))
    REGLAGES.jetons_chiffrement_cle = "cle-du-coffre-de-recette"
    REGLAGES.jwt_secret_key = "secret-de-session"

print("6. Le lien de connexion ne s'imprime pas sur un serveur")
source = (BACKEND / "routers" / "auth.py").read_text(encoding="utf-8")
verifier("l'impression du lien dépend de l'ENVIRONNEMENT, pas du seul drapeau debug",
         'environnement in ("development", "dev", "local", "test")' in source
         and source.index("environnement =") < source.index("MAGIC LINK (dev)"))
verifier("la demande de lien est bornée par origine",
         "tentatives.saturee(origine)" in source
         and ("tentatives.origine_de" in source or "_origine(request)" in source))
verifier("la borne ne change pas la réponse (elle n'apprend rien à qui insiste)",
         source.count('return {"ok": True}') >= 2)
verifier("la vérification compte ses échecs et oublie après une entrée réussie",
         "tentatives.noter_echec(origine)" in source and "tentatives.oublier(origine)" in source)
verifier("un refus de vérification dit toujours la même chose",
         source.count('detail="Lien invalide"') >= 2)

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s)")
    sys.exit(1)
print("✓ 0 échec")
