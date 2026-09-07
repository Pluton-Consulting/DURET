"""
Banc « LE TABLEAU EN ENTIER, ET UNE BOÎTE À LIRE » — relevés du 07/09.

LES DEUX DEMANDES (Noa, en lisant le journal des échanges du 3 septembre) :
  1. « pourquoi sur un excel de plus de 60 lignes (contenant des mails) il a agi
     que sur 30 lignes ? il doit être capable d'agir sur la totalité de l'excel
     en 1 seul coup » ;
  2. « pourquoi il n'a pas réussi à lire les mails ? le mail du compte qui a
     demandé est bien en @symbiose-paysage.fr ».

CE QUE LES TRACES MONTRAIENT :
  · 03/09 08:57 et 10:33 — l'invite disait « Tableau : 95 lignes », donc le
    SERVEUR avait tout lu. C'est le bloc d'action du modèle qui portait une
    liste de destinataires recopiée À LA MAIN, arrêtée à 30. Interrogé, il a
    répondu que « 30 correspond exactement au nombre de clients du tableau » :
    il ne voyait que sa propre liste ;
  · 03/09 15:18 et 15:24 — « votre compte n'appartient pas au domaine de
    messagerie ». Ces deux tours-là tournaient sur le compte SUPER-ADMIN (le
    compte développeur, hors messagerie de l'entreprise), pas sur celui de la
    direction : `MS_DOMAIN` valait bien `symbiose-paysage.fr`, et le compte
    direction avait lu SA boîte sans difficulté à 10:30 le même jour. La
    bascule du super_admin vers la boîte d'un dirigeant existait déjà
    (03/09, `2d490df`) — elle n'était pas déployée. Restaient deux fragilités
    voisines, corrigées ici : un seul domaine accepté (un tenant en a
    plusieurs), et une direction hors domaine laissée sans boîte.

CE QUE CE BANC PROUVE (sans base, sans réseau) :
  · une liste recopiée qui est le DÉBUT du tableau est complétée, avant
    l'empreinte, et la complétion est DITE ;
  · une vraie sélection n'est jamais touchée, et une demande qui borne
    elle-même le travail (« les 10 premiers ») est respectée ;
  · plusieurs domaines de messagerie sont reconnus, l'ancienne valeur à un
    seul domaine continue de marcher, et aucun domaine configuré n'exclut
    personne ;
  · la direction dont l'adresse est hors messagerie reçoit la boîte d'un
    dirigeant au lieu d'un refus, et les autres rôles ne bougent pas.

CE QU'IL NE PROUVE PAS : aucun appel réel à Graph ni à Gmail, aucune vraie base.
"""
import asyncio
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def _poser(nom, **attrs):
    mod = types.ModuleType(nom)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[nom] = mod
    return mod


print(f"\n═══ LE TABLEAU EN ENTIER, ET UNE BOÎTE À LIRE — {BACKEND.parent}\n")

# ══════════════════════════════════════════════════════════════════════════
# 1. LE TABLEAU EN ENTIER
# ══════════════════════════════════════════════════════════════════════════
print("── 1. Un classeur de 95 lignes donne 95 envois")

agent1_src = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
debut = agent1_src.index("_RE_SOUS_ENSEMBLE = ")
fin = agent1_src.index("def _est_jeton_tableau")
espace = {"__name__": "tableau_entier"}
exec(compile(agent1_src[debut:fin], "agent1.py", "exec"), espace)
completer = espace["_completer_depuis_tableau"]
est_debut = espace["_est_le_debut_du_tableau"]
cle_de = espace["_cle_de_ligne"]

# Le classeur du 03/09 : 95 clients, colonne « E-mail ».
LIGNES = [{"Civilité": "Mme" if i % 2 else "M.", "Nom ?": f"CLIENT{i:02d}",
           "Prénom": f"Prénom{i}", "E-mail": f"client{i:02d}@exemple.fr"}
          for i in range(95)]

verifier("une ligne se reconnaît par son adresse",
         cle_de(LIGNES[3]) == "client03@exemple.fr")
verifier("une adresse nue se reconnaît aussi",
         cle_de("Client03@Exemple.fr ") == "client03@exemple.fr")

verifier("30 lignes recopiées dans l'ordre, c'est le DÉBUT du tableau",
         est_debut(LIGNES[:30], LIGNES) is True)
verifier("une sélection dispersée n'est PAS un début",
         est_debut([LIGNES[2], LIGNES[40], LIGNES[80]], LIGNES) is False)
verifier("une liste aussi longue que le tableau n'est pas une troncature",
         est_debut(list(LIGNES), LIGNES) is False)

# ── le cas exact de la trace du 03/09 ────────────────────────────────────
args = {"sujet": "Votre entretien 2027", "gabarit": "Bonjour {prenom},",
        "destinataires": LIGNES[:30]}
sortis = completer(args, LIGNES, "écris un mail pour ces clients")
verifier("LE CAS DU 03/09 : 30 recopiés sur 95 → les 95 sont traités",
         len(sortis["destinataires"]) == 95)
verifier("la complétion est enregistrée pour être DITE",
         sortis["_tableau_complete"] == {"recopiees": 30, "total": 95,
                                         "champ": "destinataires"})
verifier("les autres paramètres ne bougent pas",
         sortis["sujet"] == "Votre entretien 2027" and sortis["gabarit"] == "Bonjour {prenom},")

# ── ce qu'il ne faut SURTOUT pas compléter ───────────────────────────────
choisis = [LIGNES[5], LIGNES[60], LIGNES[91]]
verifier("une vraie sélection reste intacte",
         completer({"destinataires": choisis}, LIGNES, "écris à ces trois-là"
                   )["destinataires"] == choisis)
verifier("« les 10 premiers clients » est respecté à la lettre",
         len(completer({"destinataires": LIGNES[:10]}, LIGNES,
                       "prépare un mail pour les 10 premiers clients"
                       )["destinataires"]) == 10)
verifier("« seulement quelques-uns pour tester » est respecté",
         len(completer({"destinataires": LIGNES[:3]}, LIGNES,
                       "envoie seulement à quelques-uns pour tester"
                       )["destinataires"]) == 3)
verifier("sans tableau joint, rien n'est touché",
         completer({"destinataires": LIGNES[:5]}, [], "un mail à chacun"
                   )["destinataires"] == LIGNES[:5])
verifier("une liste déjà complète n'est pas marquée comme complétée",
         "_tableau_complete" not in completer({"destinataires": list(LIGNES)}, LIGNES,
                                              "un mail à chacun"))
verifier("aucune liste n'est jamais RACCOURCIE",
         len(completer({"destinataires": LIGNES[:30]}, LIGNES[:10],
                       "un mail à chacun")["destinataires"]) == 30)

# ── la substitution a lieu AVANT l'empreinte ─────────────────────────────
verifier("la complétion est posée avant `hash_payload` (ce qui est haché s'exécute)",
         agent1_src.index("_completer_depuis_tableau(args") < agent1_src.index("empreinte = hash_payload"))

# ── ce que le skill en dit ───────────────────────────────────────────────
skills_src = (BACKEND / "mail" / "skills.py").read_text(encoding="utf-8")
verifier("le skill DIT que la liste a été complétée",
         'complete = data.get("_tableau_complete")' in skills_src
         and "l'action n'en " in skills_src)
verifier("le catalogue ordonne d'écrire `@tableau` avec un fichier joint",
         "recopier " in skills_src and "n'en produit jamais la totalité" in skills_src)

# ══════════════════════════════════════════════════════════════════════════
# 2. UNE BOÎTE À LIRE
# ══════════════════════════════════════════════════════════════════════════
print("\n── 2. « Aucune boîte à lire » ne doit plus arriver à un dirigeant")

REGLAGES = types.SimpleNamespace(ms_domain=None, gmail_domain=None)
DIRIGEANT = {"email": "eric@symbiose-paysage.fr"}


class _Connexion:
    async def fetchrow(self, *a, **k):
        return DIRIGEANT


class _Base:
    async def __aenter__(self):
        return _Connexion()

    async def __aexit__(self, *a):
        return False


_poser("fastapi", HTTPException=type("HTTPException", (Exception,), {
    "__init__": lambda self, status_code=None, detail=None: Exception.__init__(self, detail)}),
    status=types.SimpleNamespace(HTTP_403_FORBIDDEN=403))
_poser("database")
_poser("database.connection", get_db=lambda: _Base())
_poser("config", settings=REGLAGES)

src = BACKEND / "mail" / "authorization.py"
authz = types.ModuleType("authz_double")
authz.__dict__["__file__"] = str(src)
exec(compile(src.read_text(encoding="utf-8"), str(src), "exec"), authz.__dict__)


def compte(email, role):
    return types.SimpleNamespace(email=email, role=role, id="u-1")


# ── les domaines ─────────────────────────────────────────────────────────
REGLAGES.ms_domain = "symbiose-paysage.fr"
verifier("l'ancienne valeur à UN domaine marche telle quelle",
         authz.domaines_messagerie() == frozenset({"symbiose-paysage.fr"})
         and authz.est_du_domaine("noa@symbiose-paysage.fr"))

REGLAGES.ms_domain = "symbiose-paysage.fr, symbiosepaysage.onmicrosoft.com"
verifier("PLUSIEURS domaines sont reconnus (le public ET l'onmicrosoft)",
         authz.est_du_domaine("noa@symbiose-paysage.fr")
         and authz.est_du_domaine("noa@symbiosepaysage.onmicrosoft.com"))
verifier("une adresse d'un autre domaine reste dehors",
         not authz.est_du_domaine("benitez.noapro@gmail.com"))
verifier("la casse et les espaces ne décident de rien",
         authz.est_du_domaine("  Noa@Symbiose-Paysage.FR  "))

REGLAGES.ms_domain = "@symbiose-paysage.fr;autre.fr"
verifier("les séparateurs et l'arobase de trop sont tolérés",
         authz.domaines_messagerie() == frozenset({"symbiose-paysage.fr", "autre.fr"}))

REGLAGES.ms_domain, REGLAGES.gmail_domain = None, None
verifier("aucun domaine configuré n'exclut PERSONNE",
         authz.est_du_domaine("qui.que.ce.soit@ailleurs.fr"))
verifier("une valeur qui n'est pas une adresse n'est jamais du domaine",
         not authz.est_du_domaine("") and not authz.est_du_domaine("pas-une-adresse"))

# ── la boîte par défaut ──────────────────────────────────────────────────
REGLAGES.ms_domain = "symbiose-paysage.fr"

verifier("un compte du domaine lit SA boîte, quel que soit son rôle",
         asyncio.run(authz.boite_par_defaut(compte("noa@symbiose-paysage.fr", "direction")))
         == "noa@symbiose-paysage.fr")
verifier("une direction hors domaine reçoit la boîte d'un dirigeant (nouveau, 07/09)",
         asyncio.run(authz.boite_par_defaut(compte("benitez.noapro@gmail.com", "direction")))
         == "eric@symbiose-paysage.fr")
verifier("LE CAS DES DEUX REFUS DU 03/09 : le super_admin lit la boîte d'un dirigeant",
         asyncio.run(authz.boite_par_defaut(compte("dev@pluton-consulting.fr", "super_admin")))
         == "eric@symbiose-paysage.fr")
verifier("un rôle métier hors domaine ne reçoit PAS la boîte d'un dirigeant",
         asyncio.run(authz.boite_par_defaut(compte("perso@gmail.com", "collaborateur")))
         == "perso@gmail.com")

DIRIGEANT = None
verifier("sans dirigeant en base, on retombe sur sa propre adresse",
         asyncio.run(authz.boite_par_defaut(compte("benitez.noapro@gmail.com", "direction")))
         == "benitez.noapro@gmail.com")
DIRIGEANT = {"email": "eric@symbiose-paysage.fr"}

# ── ce que le refus dit, quand il arrive encore ──────────────────────────
verifier("le refus NOMME les domaines reconnus et le geste à faire",
         "domaines reconnus" in skills_src
         and "Paramètres → Utilisateurs" in skills_src
         and "n'appartient pas au domaine de messagerie" not in skills_src)
verifier("le choix de la boîte passe par `boite_par_defaut` pour les DEUX rôles",
         'role in ("super_admin", "direction")' in skills_src)
verifier("le suffixe d'un domaine unique ne décide plus de rien",
         'propre.endswith("@" + domaine)' not in skills_src)

lecture_src = (BACKEND / "mail" / "lecture.py").read_text(encoding="utf-8")
verifier("un collègue est reconnu sur TOUS les domaines du tenant",
         "est_du_domaine(adresse)" in lecture_src
         and 'adresse.endswith("@" + domaine)' not in lecture_src)

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs))
    sys.exit(1)
print("✓ 0 échec")
