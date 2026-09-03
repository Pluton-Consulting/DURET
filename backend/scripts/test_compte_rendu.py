"""
Banc du COMPTE RENDU DE RÉUNION — une transcription entre, une synthèse sort.

LA DEMANDE (03/09, Noa) : « un skill de compte rendu de réunion / synthèse
concis, qui reprend les points clés », déclenchable par un bouton de questions
rapides où l'on colle la transcription.

CE QUE CE BANC PROUVE, sans réseau ni base : le skill est EXÉCUTÉ de bout en
bout contre un modèle doublé, et ce sont les quatre pièges du sujet qui sont
visés, pas la tuyauterie :

  1. UNE HEURE DE RÉUNION EST LUE EN ENTIER. Le découpage couvre tout le
     texte, les parts se recouvrent (une décision à cheval sur la coupe ne
     disparaît pas), et quand la transcription dépasse ce qu'un tour peut lire,
     ON LE DIT — jamais un compte rendu bâti sur les trois quarts d'une réunion
     avec l'aplomb de qui a tout lu.
  2. RIEN N'EST INVENTÉ. Un responsable non nommé reste VIDE — « à définir »,
     « TBD » et consorts sont ramenés à vide, parce qu'un compte rendu qui
     attribue une tâche à quelqu'un qui ne l'a pas acceptée fait des dégâts.
  3. LA CONCISION EST MÉCANIQUE. Les plafonds coupent APRÈS le modèle : une
     réunion bavarde ne produit pas un compte rendu bavard.
  4. LES NOMS REVIENNENT. Masqués avant le modèle, réhydratés après ; un jeton
     resté orphelin devient un trou visible, jamais une balise technique dans
     un document remis aux participants.

Il TOMBE sur la version d'avant : le module n'existait pas.
"""
import asyncio
import json
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
RACINE = BACKEND.resolve().parent
FRONTEND = RACINE / "frontend"
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ COMPTE RENDU DE RÉUNION — {RACINE}\n")

source = BACKEND / "skills" / "reunion.py"
if not source.exists():
    print("  ✗ backend/skills/reunion.py est absent — le skill n'existe pas.")
    sys.exit(1)


# ── LES DOUBLURES ─────────────────────────────────────────────────────────
class SkillErrorDouble(Exception):
    pass


class DeclarationDouble:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class AnonymiseurDouble:
    """Masque un seul nom, pour que la réhydratation soit VÉRIFIABLE.

    Un anonymiseur qui ne masque rien ferait passer le contrôle sans rien
    prouver : ici « Jean » devient « [PER_1] » à l'aller, et le compte rendu
    doit le retrouver au retour.
    """
    def __init__(self):
        self.appels = 0

    def anonymize_chunks(self, chunks, entity_map=None):
        self.appels += 1
        carte = dict(entity_map or {})
        carte["[PER_1]"] = "Jean"
        return [str(c).replace("Jean", "[PER_1]") for c in chunks], carte

    def rehydrate(self, texte, carte):
        for jeton, valeur in (carte or {}).items():
            texte = texte.replace(jeton, valeur)
        return texte


class ModeleDouble:
    """Rend une réponse préparée par appel, et compte les paliers demandés."""
    def __init__(self):
        self.reponses = []
        self.paliers = []
        self.invites = []

    def pour(self, palier):
        self.paliers.append(palier)
        modele = self

        class Client:
            async def ainvoke(self, messages):
                modele.invites.append(str(getattr(messages[0], "content", "")))
                sortie = (modele.reponses.pop(0) if modele.reponses
                          else '{"resume": "vide"}')
                if isinstance(sortie, Exception):
                    raise sortie
                return types.SimpleNamespace(content=sortie)
        return Client()


MODELE = ModeleDouble()
ANONYMISEUR = AnonymiseurDouble()
ATELIER = {"ouvert": 0, "elements": []}


def _atelier_ouvrir(entete, proprio):
    ATELIER["ouvert"] += 1
    ATELIER["entete"] = entete
    return "jeton-doc"


def _atelier_ajouter(jeton, elements, proprio):
    ATELIER["elements"] = elements
    return len(elements)


def _atelier_terminer(jeton, proprio):
    return {"octets": 4242}


def _poser(nom, **attrs):
    mod = types.ModuleType(nom)
    mod.__dict__.update(attrs)
    sys.modules[nom] = mod
    return mod


_poser("skills")
_poser("skills.erreurs", SkillError=SkillErrorDouble)
_poser("skills.registre", Declaration=DeclarationDouble)
_poser("security")
_poser("security.anonymizer", anonymizer=ANONYMISEUR)
_poser("llm")
_poser("llm.router", LLMTier=lambda p: p, get_llm=MODELE.pour)
_poser("langchain_core")
_poser("langchain_core.messages",
       HumanMessage=lambda content: types.SimpleNamespace(content=content))
_poser("bureautique")
_poser("bureautique.atelier", ouvrir=_atelier_ouvrir, ajouter=_atelier_ajouter,
       terminer=_atelier_terminer)

reunion = types.ModuleType("reunion")
reunion.__dict__["__file__"] = str(source)
exec(compile(source.read_text(encoding="utf-8"), str(source), "exec"), reunion.__dict__)

UTILISATEUR = types.SimpleNamespace(id="user-1", email="patron@exemple.fr")


# ── 1. LE DÉCOUPAGE : tout est lu, et les coupes ne perdent rien ──────────
court = "Bonjour. " * 20
verifier("une transcription courte reste en une seule part",
         reunion.decouper(court) == [court.strip()] or len(reunion.decouper(court)) == 1)

long_texte = "\n".join(f"Ligne {i} : on parle du sujet numéro {i} pendant la réunion."
                       for i in range(1, 1200))
parts = reunion.decouper(long_texte)
verifier("une longue transcription est découpée en plusieurs parts", len(parts) > 1,
         f"{len(parts)} part(s) pour {len(long_texte)} caractères")
verifier("TOUTE la transcription est couverte",
         reunion.couvert(long_texte, parts) >= len(long_texte.strip()),
         f"{reunion.couvert(long_texte, parts)} / {len(long_texte.strip())}")
verifier("les parts se recouvrent (une décision à cheval n'est pas perdue)",
         sum(len(p) for p in parts) > len(long_texte))
verifier("on coupe à une respiration, pas au milieu d'un mot",
         all(p.endswith("\n") or p.endswith(". ") or p.endswith(".")
             or p is parts[-1] for p in parts))

# La borne du nombre de parts : elle EXISTE, et elle se dit (contrôle 2 plus bas).
garde = reunion.MAX_PARTS
reunion.MAX_PARTS = 2
parts_bornees = reunion.decouper(long_texte)
verifier("au-delà de la borne, la lecture s'arrête — et la couverture le montre",
         len(parts_bornees) == 2
         and reunion.couvert(long_texte, parts_bornees) < len(long_texte.strip()))
reunion.MAX_PARTS = garde


# ── 2. LE NETTOYAGE : concision, dédoublonnage, rien d'inventé ────────────
verifier("un même point répété trois fois n'en fait qu'un",
         reunion._lignes(["Le budget est validé.", "le budget est validé",
                          "Le budget est validé !"], 8) == ["Le budget est validé."])
verifier("la liste est bornée (la concision est mécanique)",
         len(reunion._lignes([f"point {i}" for i in range(40)], 8)) == 8)
verifier("un point est une phrase, pas un paragraphe",
         len(reunion._lignes(["x" * 900], 8)[0]) == reunion.MAX_LIGNE)

actions = reunion._actions([
    {"quoi": "Relancer le fournisseur", "qui": "Jean", "quand": "vendredi"},
    {"quoi": "Chiffrer le lot 3", "qui": "à définir", "quand": "TBD"},
    {"quoi": "Relancer le fournisseur", "qui": "Marie", "quand": ""},
    "Envoyer le plan",
], 12)
verifier("un responsable nommé est conservé",
         actions[0] == {"quoi": "Relancer le fournisseur", "qui": "Jean", "quand": "vendredi"})
verifier("« à définir » et « TBD » NE SONT PAS des responsables : le champ reste vide",
         actions[1]["qui"] == "" and actions[1]["quand"] == "", str(actions[1]))
verifier("une action répétée n'est pas comptée deux fois",
         len([a for a in actions if a["quoi"] == "Relancer le fournisseur"]) == 1)
verifier("une action écrite en simple texte est acceptée",
         any(a["quoi"] == "Envoyer le plan" for a in actions))


# ── 3. LE BLOC D'ÉCRAN, construit mécaniquement ──────────────────────────
bloc = reunion.construire_bloc(
    {"resume": "Court résumé.", "decisions": ["On signe"], "points_cles": [],
     "en_suspens": ["Le délai"], "actions": [{"quoi": "Signer", "qui": "", "quand": ""}],
     "participants": ["Jean"]},
    "Réunion du 3", "03/09 · 1 participant")
verifier("le bloc est du type attendu", bloc.get("type") == "compte_rendu")
verifier("une rubrique vide ne fait pas une section vide à l'écran",
         [s["titre"] for s in bloc.get("sections", [])] == ["Décisions", "Points en suspens"])
verifier("les actions voyagent dans le bloc", bloc.get("actions"))


# ── 4. LE SKILL, EXÉCUTÉ ─────────────────────────────────────────────────
TRANSCRIPTION = ("Jean : on démarre la réunion sur le chantier Duval. " * 8
                 + "Marie : le budget de 12 400 € est validé. " * 8)

def _lancer(data, reponses):
    MODELE.reponses = list(reponses)
    MODELE.paliers = []
    MODELE.invites = []
    return asyncio.run(reunion.compte_rendu_reunion(data, UTILISATEUR))


try:
    _lancer({"transcription": "Trop court."}, [])
    verifier("une transcription trop courte est refusée, en disant quoi faire", False)
except SkillErrorDouble as e:
    verifier("une transcription trop courte est refusée, en disant quoi faire",
             "Collez le texte" in str(e))

SYNTHESE = json.dumps({
    "titre": "Chantier Duval",
    "participants": ["[PER_1]", "Marie"],
    "resume": "[PER_1] ouvre la réunion. Le budget de 12 400 € est validé.",
    "points_cles": ["Budget de 12 400 € validé"],
    "decisions": ["Le budget est validé"],
    "actions": [{"quoi": "Commander les matériaux", "qui": "[PER_1]", "quand": "vendredi"},
                {"quoi": "Vérifier le planning", "qui": "à définir", "quand": ""}],
    "en_suspens": ["La date de livraison"],
}, ensure_ascii=False)

def _bloc(sortie, genre):
    """Le bloc d'un type donné — le résultat en porte plusieurs (compte rendu,
    document produit, suites proposées)."""
    blocs = sortie.get("bloc_ui")
    blocs = blocs if isinstance(blocs, list) else [blocs]
    return next((b for b in blocs if isinstance(b, dict) and b.get("type") == genre), None)


sortie = _lancer({"transcription": TRANSCRIPTION}, ['{"points": ["ok"]}', SYNTHESE])
bloc_sortie = _bloc(sortie, "compte_rendu")
verifier("le compte rendu s'affiche par un bloc GARANTI (le modèle ne le recopie pas)",
         sortie.get("bloc_garanti") is True and bloc_sortie is not None)
verifier("LES NOMS SONT REVENUS : masqués à l'aller, réhydratés au retour",
         "Jean" in bloc_sortie.get("resume", "") and "[PER_1]" not in json.dumps(bloc_sortie),
         bloc_sortie.get("resume", ""))
verifier("le masquage a bien eu lieu avant le modèle", ANONYMISEUR.appels >= 1)
verifier("le modèle n'a PAS reçu le nom en clair",
         all("Jean" not in inv for inv in MODELE.invites))
verifier("la synthèse est demandée au palier de jugement, pas au palier rapide",
         MODELE.paliers[-1] == "complex")
verifier("un responsable non tranché reste vide jusque dans le bloc",
         bloc_sortie["actions"][1]["qui"] == "")
verifier("le chiffre dit en réunion est recopié tel quel",
         "12 400 €" in bloc_sortie.get("resume", ""))
verifier("la consigne au modèle lui interdit de recopier le compte rendu",
         "ne le recopie" in sortie.get("a_faire", ""))
verifier("la consigne ORDONNE de proposer l'envoi par mail",
         "PROPOSE L'ENVOI PAR MAIL" in sortie.get("a_faire", ""))
verifier("mais interdit de l'envoyer de soi-même : accord humain d'abord",
         "Ne l'envoie pas de toi-même" in sortie.get("a_faire", "")
         and "envoyer_email" in sortie.get("a_faire", ""))

# ── L'ENVOI EST PROPOSÉ EN BOUTON, pas seulement en prose ────────────────
# Un compte rendu qui reste dans le chat ne sert à personne : sa vie normale
# est de partir aux participants. Le bouton est mécanique — un modèle qui
# oublie de proposer n'empêche pas la proposition d'exister.
blocs_tout = sortie["bloc_ui"] if isinstance(sortie["bloc_ui"], list) else [sortie["bloc_ui"]]
suites = [b for b in blocs_tout if b.get("type") == "quick_replies"]
verifier("une rangée de suites est proposée sous le compte rendu", len(suites) == 1)
verifier("L'ENVOI PAR MAIL EST LA PREMIÈRE SUITE PROPOSÉE",
         suites and suites[0]["options"][0] == "Envoie ce compte rendu par mail",
         str(suites[0]["options"]) if suites else "")
verifier("le Word est proposé tant qu'il n'a pas été produit",
         reunion._suites(False, True)["options"][1] == "Fais-moi le document Word")
verifier("il ne l'est plus une fois le document produit",
         all("Word" not in o for o in reunion._suites(True, True)["options"]))
verifier("les relances ne sont proposées que s'il y a des actions",
         all("relance" not in o for o in reunion._suites(False, False)["options"]))
verifier("l'envoi reste proposé même sans action et sans document",
         reunion._suites(True, False)["options"] == ["Envoie ce compte rendu par mail"])
verifier("le résultat ne porte PAS le compte rendu en double",
         "points_cles" not in sortie and "decisions" not in sortie)
verifier("une phrase d'écran dit ce qui a été produit",
         "Compte rendu" in sortie.get("message_final", ""))

# Le document Word, produit mécaniquement
ATELIER["ouvert"] = 0
sortie_fichier = _lancer({"transcription": TRANSCRIPTION, "fichier": True},
                         ['{"points": ["ok"]}', SYNTHESE])
blocs = sortie_fichier.get("bloc_ui")
verifier("`fichier: true` produit le Word et rend SON bloc en plus",
         isinstance(blocs, list)
         and (_bloc(sortie_fichier, "fichier") or {}).get("format") == "docx")
verifier("le document est écrit par le code, pas dicté au modèle",
         ATELIER["ouvert"] == 1
         and any(e.get("type") == "tableau" for e in ATELIER["elements"]))
verifier("le tableau des actions montre le trou plutôt que de le combler",
         any("à désigner" in str(l) for e in ATELIER["elements"]
             for l in (e.get("lignes") or [])))

# Une transcription plus longue que la part : plusieurs relevés, puis la synthèse
long_transcription = TRANSCRIPTION + "Jean : " + ("on continue de parler. " * 900)
# Une réponse de relevé par part, puis la synthèse : la liste se construit sur
# le découpage réel, sinon le banc casserait au moindre réglage de TAILLE_PART.
n_parts = len(reunion.decouper(long_transcription))
sortie_longue = _lancer({"transcription": long_transcription},
                        ['{"points": ["a"]}'] * n_parts + [SYNTHESE])
verifier("une longue réunion est lue en plusieurs passes, et le nombre est dit",
         sortie_longue.get("parties_lues", 0) > 1
         and f"{sortie_longue['parties_lues']} parties lues" in json.dumps(sortie_longue,
                                                                          ensure_ascii=False))

# Une part perdue ne perd pas le compte rendu
sortie_partielle = _lancer(
    {"transcription": long_transcription},
    [RuntimeError("fournisseur muet")] + ['{"points": ["b"]}'] * (n_parts - 1) + [SYNTHESE])
verifier("une part dont le relevé échoue ne fait pas tomber le compte rendu",
         sortie_partielle.get("bloc_garanti") is True)

# Un jeton orphelin ne part pas dans un document remis à des participants
ORPHELIN = json.dumps({"resume": "Le point de [PER_9] reste ouvert.",
                       "decisions": ["Rien"], "actions": [], "points_cles": [],
                       "en_suspens": [], "participants": []}, ensure_ascii=False)
sortie_orpheline = _lancer({"transcription": TRANSCRIPTION},
                           ['{"points": ["ok"]}', ORPHELIN])
verifier("un jeton resté orphelin devient un trou visible, pas une balise technique",
         "[à compléter]" in _bloc(sortie_orpheline, "compte_rendu")["resume"]
         and "PER_9" not in json.dumps(sortie_orpheline))

# Le modèle qui ne rend rien d'exploitable
try:
    _lancer({"transcription": TRANSCRIPTION}, ['{"points": ["ok"]}', "je ne sais pas faire"])
    verifier("un modèle qui ne rend pas de relevé est signalé, pas maquillé", False)
except SkillErrorDouble as e:
    verifier("un modèle qui ne rend pas de relevé est signalé, pas maquillé",
             "exploitable" in str(e) or "illisible" in str(e))


# ── 5. LA DÉCLARATION ────────────────────────────────────────────────────
decl = reunion.SKILLS.get("compte_rendu_reunion")
verifier("le skill est déclaré une seule fois, dans son module", decl is not None)
if decl:
    verifier("il exige la transcription et rien d'autre", decl.requis == ["transcription"])
    verifier("titre, date, focus et fichier sont optionnels",
             set(decl.optionnels) == {"titre", "date", "focus", "fichier"})
    verifier("effet LECTURE : rien ne sort de l'entreprise, aucun accord à demander",
             decl.effet == "lecture")
    verifier("l'écran dit ce qu'il fait pendant ce temps", decl.libelle == "je fais le compte rendu")
    verifier("le catalogue dit de NE PAS raccourcir la transcription soi-même",
             "NE RECOPIE JAMAIS une longue transcription" in decl.description)
    verifier("il apprend au modèle à écrire `@message` plutôt que recopier la réunion",
             '"@message"' in decl.description)


# ── 5bis. LE JETON `@message` : le serveur met le texte, pas le modèle ────
# C'est le point qui rend le skill utilisable en vrai. Un modèle ne peut pas
# recopier 50 000 caractères dans son bloc ```action : il les raccourcirait, et
# le compte rendu porterait sur la moitié de la réunion.
agent1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("le serveur remplace `@message` par le message de l'utilisateur",
         "_est_jeton_message" in agent1 and 'state.get("query")' in agent1)
verifier("plusieurs écritures du jeton sont acceptées",
         '"@message"' in agent1 and '"@transcription"' in agent1)
verifier("la substitution a lieu AVANT l'empreinte (ce qui est haché est ce qui s'exécute)",
         agent1.find("_est_jeton_message(v)") < agent1.find('empreinte = hash_payload(action["skill"], args)'))

# L'en-tête du raccourci n'est pas de la réunion.
reunion_longue = "Jean : on démarre. " * 40
verifier("la consigne du raccourci est retirée, la transcription est gardée",
         reunion._sans_entete("Fais le compte rendu.\n\nTranscription :\n" + reunion_longue)
         == reunion_longue.strip())
verifier("on ne coupe RIEN quand il ne reste pas de vraie transcription derrière",
         reunion._sans_entete("Transcription : trois mots") == "Transcription : trois mots")


# ── 6. L'ÉCRAN ───────────────────────────────────────────────────────────
rendu = (FRONTEND / "components" / "chat" / "MessageRenderer.tsx").read_text(encoding="utf-8")
verifier("le bloc est enregistré dans le rendu",
         'case "compte_rendu"' in rendu and "CompteRendu" in rendu)
verifier("un compte rendu sans résumé n'est pas affiché",
         'compte_rendu: ["resume"]' in rendu)
composant = FRONTEND / "components" / "blocks" / "business" / "CompteRendu.tsx"
verifier("le composant existe", composant.exists())
if composant.exists():
    texte = composant.read_text(encoding="utf-8")
    verifier("il MONTRE le trou : « à désigner » / « à fixer »",
             "à désigner" in texte and "à fixer" in texte)
    verifier("il tient la largeur commune des blocs", "var(--bloc-largeur)" in texte)
    verifier("le tableau des actions défile seul sur un écran étroit",
             'overflowX: "auto"' in texte)
index = (FRONTEND / "components" / "blocks" / "index.ts").read_text(encoding="utf-8")
verifier("il est exporté par la bibliothèque", "business/CompteRendu" in index)

raccourcis = (FRONTEND / "lib" / "raccourcis.ts").read_text(encoding="utf-8")
verifier("le bouton de questions rapides propose le compte rendu",
         "Compte rendu de réunion" in raccourcis)
verifier("le raccourci laisse la place à la transcription", "Transcription :" in raccourcis)
verifier("il dit de ne rien inventer",
         "N'invente aucun responsable" in raccourcis)

agent1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("le résultat du compte rendu échappe à la coupe à 4 000 caractères",
         '"compte_rendu_reunion"' in agent1)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
