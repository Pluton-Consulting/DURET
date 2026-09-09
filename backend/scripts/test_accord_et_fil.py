"""
Banc « L'ACCORD, LE RIEN ET LE FIL » — l'export Langfuse du 09/09 (projet Camp),
lu tour par tour. Quatre défauts, tous rejoués ici avec les TEXTES EXACTS de la
production :

  1. 05:58 et 07:10 — une action armée pour l'accord humain (« Je dépose les
     trois documents… », « Je vais repartir de votre création… » + la photo de
     départ) : le filet des promesses y voyait une annonce sans acte, appelait
     le rédacteur de secours SANS résultat, et l'écran lisait « aucune action
     n'a abouti » au-dessus d'une carte qui attendait un clic ;
  2. 07:05 et 07:10 — deux réponses justes (« Oui, je lis le visuel… », « dès
     que vous me donnez la photo, je m'en occupe ») prises pour des annonces,
     envoyées au forceur, qui a répondu RIEN ; le texte a été jeté et remplacé
     par « le traitement n'a pas abouti » ;
  3. 05:54 et 05:58 — trois messages partis en file d'attente (fil `file:`
     neuf, sans historique) : le modèle a écrit trois vignettes `doc` sans
     adresse — ni aperçu, ni téléchargement — et rien ne les remplaçait ;
  4. 05:34 → 05:43 — le plan approuvé s'est arrêté au premier document (point
     d'étape), les photomontages n'ont jamais été tentés ; et sept recherches
     web ont posé sept tableaux d'adresses sous la réponse.

CE QUE CE BANC PROUVE (sans base, sans réseau, sans modèle) :
  · `rehydrate_node` EXÉCUTÉ : avec une action en attente, le texte du modèle
    et la photo de départ restent, le rédacteur de secours n'est PAS appelé ;
    avec un RIEN du sélecteur, la réponse est gardée telle quelle ; SANS l'un
    ni l'autre, le filet tire encore (contrôle négatif) ;
  · `_livrables_a_l_ecran` EXÉCUTÉ sur la réponse exacte de 05:54, fil vide,
    atelier doublé : les trois vignettes deviennent trois cartes `fichier` ;
  · `_blocs_garantis` EXÉCUTÉ : sept recherches web → un tableau ;
  · les prédicats sur les textes de production ; le point d'étape respecte un
    plan approuvé ; le forceur retient le RIEN ; l'écran attend la fin d'une
    reprise coupée par le mandataire ; nginx laisse « Approuver » durer.
  · Symbiose seulement : l'inventaire lit le Drive par la bonne fonction, et
    le 503 se réessaie cinq fois.

Tombe sur la version d'avant.
"""
import ast
import asyncio
import json
import pathlib
import re
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
RACINE = BACKEND.parent
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
        elif isinstance(n, ast.Import) and any(
                (a.asname or a.name) in noms for a in n.names):
            gardes.append(n)
    exec(compile(ast.Module(body=gardes, type_ignores=[]), str(chemin), "exec"), espace)
    manquants = [x for x in noms if x not in espace]
    assert not manquants, f"absent du module livré : {manquants}"
    return espace


class _Journal:
    def info(self, *a, **k):
        pass
    warning = info
    debug = info


class _Msg:
    def __init__(self, content, type_="ai"):
        self.content = content
        self.type = type_


def bloc_ui(obj):
    return "```ui\n" + json.dumps(obj, ensure_ascii=False) + "\n```"


# ── Les modules que rehydrate_node importe en cours de route, doublés ──────
def _module(nom, **attrs):
    m = types.ModuleType(nom)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[nom] = m
    return m


class _Anonymiseur:
    def rehydrate(self, texte, carte):
        return texte

    def find_placeholders(self, texte):
        return []


_module("security")
_module("security.anonymizer", anonymizer=_Anonymiseur())
_module("skills")
_module("skills.protocol",
        BLOC_ACTION_RE=re.compile(r"```action\s*(\{.*?\})\s*```", re.S),
        BLOC_ACTION_TRONQUE_RE=re.compile(r"```action\s*\{[^`]*$", re.S),
        BLOC_NATIF_RE=re.compile(r"<\|tool_call\|>.*?<\|/tool_call\|>", re.S),
        BALISAGE_OUTIL_RE=re.compile(r"<\|[a-z_/]+\|>"))
_module("agents")
_module("agents.suggestions", poser=lambda texte, suites: texte,
        suggestions_du_tour=lambda *a, **k: [], suites_d_echec=lambda: [])
_module("agents.memoire_conversation", memoriser_echange_en_fond=lambda *a, **k: None)


class _AIMessage(_Msg):
    def __init__(self, content):
        super().__init__(content, "ai")


class _HumanMessage(_Msg):
    def __init__(self, content):
        super().__init__(content, "human")


_module("langchain_core")
_module("langchain_core.messages", AIMessage=_AIMessage, HumanMessage=_HumanMessage)

# L'atelier de la personne : les trois documents finis du 09/09 (le troisième,
# un PDF reçu tel quel, est aussi dans la liste du prompt).
DOCS_FINIS = [
    {"document_id": "m_9wdTIp_PMnKLoYinTifbESqvcma-Pf", "titre": "DSN_082026", "format": "pdf",
     "elements": 0, "octets": 8824, "pages_estimees": None},
    {"document_id": "oapdJPe3_W2Y0YOayDpZkKH2hC2FIds5", "titre": "Inventaire — MR ET MME CAMP",
     "format": "xlsx", "elements": 1, "octets": 5481, "pages_estimees": None},
    {"document_id": "HOn-pT0eHl9w3osDpqk8FKsH_iZGavzm", "titre": "Dossier projet paysager M. et Mme Camp",
     "format": "docx", "elements": 26, "octets": 40435, "pages_estimees": 3},
]
_module("bureautique")
_module("bureautique.atelier", termines=lambda proprietaire: list(DOCS_FINIS))

# ── Les modules livrés ─────────────────────────────────────────────────────
import importlib.util
_spec = importlib.util.spec_from_file_location("annonce", BACKEND / "agents" / "annonce.py")
annonce = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(annonce)

appels_redacteur = []


async def _redacteur_double(demande, resultats, cause=""):
    appels_redacteur.append(cause)
    return "PROSE DE SECOURS (" + cause + ")"


espace = {"logger": _Journal(), "AgentState": dict, "HumanMessage": _HumanMessage,
          "est_une_annonce": annonce.est_une_annonce,
          "promesse_sans_suite": annonce.promesse_sans_suite,
          "decrit_un_contenu_lu": annonce.decrit_un_contenu_lu,
          "reclame_un_prealable": annonce.reclame_un_prealable,
          "dement_la_disponibilite": annonce.dement_la_disponibilite,
          "suite_qui_retouche": annonce.suite_qui_retouche,
          "options_proposees": annonce.options_proposees,
          "_rediger_par_le_modele": _redacteur_double,
          "_rendu_de_secours": lambda resultats: "",
          "_tracer_filet": lambda *a, **k: None}
extraire(BACKEND / "agents" / "agent1.py",
         {"rehydrate_node", "_texte_visible", "_question_deja_au_fil",
          "_re_livrables", "_BLOC_UI_RE", "_TYPES_LIVRABLE", "_reference_bloc",
          "_blocs_livrables", "_blocs_de", "fichiers_du_fil", "_plat_nom", "_designe_le_meme",
          "_meme_livrable", "_livrables_a_l_ecran", "_cartes_de_l_atelier",
          "_redaction_dement_le_livrable", "_signature_bloc", "_dedoublonner_blocs",
          "_blocs_garantis", "cles_images_du_fil", "_CLE_IMAGE_RE", "_re_images",
          "_image_connue"}, espace)
rehydrate = espace["rehydrate_node"]
livrables = espace["_livrables_a_l_ecran"]
blocs_garantis = espace["_blocs_garantis"]

print(f"\n═══ L'ACCORD, LE RIEN ET LE FIL — {RACINE}\n")

# ══════════════════════════════════════════════════════════════════════════
# 1. LES TEXTES DE PRODUCTION FACE AUX PRÉDICATS
# ══════════════════════════════════════════════════════════════════════════
print("── 1. Les textes exacts de la production")
A = ("Oui, je lis le visuel que vous venez d'envoyer. C'est une vue 3D du projet "
     "d'aménagement paysager : espace piscine sur gazon, zone de détente avec bains de "
     "soleil et parasol, plantations en pots, clôture à panneaux et bâtiment à bardage "
     "bois. Je peux m'en servir comme base pour le photomontage sur les photos réelles "
     "du terrain.")
B = ("Très bien, je suis prêt. Dès que vous me donnez la photo de base et votre "
     "création, je m'en occupe : je les analyse et je vous propose l'intégration ou la "
     "retouche demandée. Envoyez-les quand vous voulez.")
PHOTO = bloc_ui({"type": "visuel", "titre": "Image de départ",
                 "images": [{"cle": "d7b5e304cb0453dfd49dc0a1", "legende": "La photo qui sera retouchée"}]})
C = ("Je comprends : le photomontage précédent plaçait la barrière Tokyo sur un angle de "
     "vue où elle n'apparaît pas. Je vais repartir de votre création visuelle (la vue 3D "
     "« vue piscine.jpg ») et la rendre photoréaliste, en conservant exactement l'angle de "
     "vue et l'emplacement des éléments tels que vous les avez conçus.\n\n"
     "Le reste de la scène est conservé à l'identique.\n\n" + PHOTO)
D = "Je dépose les trois documents terminés dans le dossier « MR ET MME CAMP » du Drive."

verifier("« dès que vous me donnez la photo… je m'en occupe » n'est plus une annonce sans acte",
         not annonce.est_une_annonce(B))
verifier("« je vais repartir de votre création » reste une annonce (c'est l'accord qui la légitime)",
         annonce.est_une_annonce(C))
verifier("« je dépose les trois documents » reste une annonce (idem)",
         annonce.est_une_annonce(D))
verifier("une vraie promesse est toujours vue", annonce.est_une_annonce("Je vais lire vos mails."))
verifier("« quand vous voulez » : une question au futur de la personne ne force rien",
         not annonce.est_une_annonce("Je vous prépare le devis quand vous m'aurez donné les métrés."))

# ══════════════════════════════════════════════════════════════════════════
# 2. REHYDRATE_NODE EXÉCUTÉ : L'ACCORD EN ATTENTE ET LE RIEN
# ══════════════════════════════════════════════════════════════════════════
print("\n── 2. rehydrate_node, exécuté sur les tours défaillants")
PENDING = {"skill": "modifier_visuel", "args": {"image": "d7b5e304cb0453dfd49dc0a1"},
           "effet": "externe", "payload_hash": "43b6"}


FIL_AVEC_LA_PHOTO = [_Msg("Photo reçue.\n\n" + bloc_ui(
    {"type": "visuel", "titre": "vue piscine.jpg",
     "images": [{"cle": "d7b5e304cb0453dfd49dc0a1", "legende": "vue piscine.jpg"}]}))]


def etat(texte, **extra):
    # La photo à retoucher est dans le fil (déposée par l'expert vision au tour
    # d'avant) : c'est ce qui légitime le bloc « Image de départ ».
    base = {"llm_response": texte, "tool_results": [], "messages": list(FIL_AVEC_LA_PHOTO),
            "query": "néanmoins ton photo montage est incorrect", "anonymized_query": "",
            "relance_annonce": False, "forcages": 0, "user_id": "89ebd52c", "thread_id": "a9f88326",
            "entity_map": {}, "turn_placeholders": None}
    base.update(extra)
    return base


appels_redacteur.clear()
sortie = asyncio.run(rehydrate(etat(C, pending_action=PENDING, requires_validation=True)))
final = sortie.get("final_response") or ""
verifier("07:10 — une retouche qui attend l'accord garde le texte du modèle",
         "Je vais repartir de votre création" in final, final[:160])
verifier("… et la photo de départ reste à l'écran", "d7b5e304cb0453dfd49dc0a1" in final, final[-200:])
verifier("… sans appeler le rédacteur de secours", not appels_redacteur, str(appels_redacteur))
verifier("… ni « aucune action n'a abouti »", "abouti" not in final and "PROSE DE SECOURS" not in final)

appels_redacteur.clear()
sortie = asyncio.run(rehydrate(etat(D, pending_action={"skill": "drive_deposer", "args": {}},
                                    requires_validation=True,
                                    query="dépose les dans le dossier MR ET MME CAMP")))
final = sortie.get("final_response") or ""
verifier("05:58 — un dépôt qui attend l'accord garde « Je dépose les trois documents… »",
         final.startswith("Je dépose les trois documents") and not appels_redacteur, final[:160])

# Le forceur a répondu RIEN : le texte répondait déjà.
appels_redacteur.clear()
sortie = asyncio.run(rehydrate(etat(A, relance_annonce=True, forcages=1, forcage_refuse=True,
                                    query="es tu capable de lire le visuel que je je t'envoi?")))
final = sortie.get("final_response") or ""
verifier("07:05 — le RIEN du sélecteur garde « Oui, je lis le visuel… »",
         final.startswith("Oui, je lis le visuel") and not appels_redacteur, final[:160])
verifier("… et le tour entre dans l'historique (ce n'est pas un tour sans effet)",
         bool(sortie.get("messages")), str(sortie.get("messages"))[:100])

# CONTRÔLE NÉGATIF : sans accord ni RIEN, une promesse nue est toujours rattrapée.
appels_redacteur.clear()
sortie = asyncio.run(rehydrate(etat("Je vais lire vos mails et je reviens vers vous.",
                                    relance_annonce=True, forcages=1)))
final = sortie.get("final_response") or ""
verifier("contrôle : une promesse sans acte, sans accord ni RIEN, est encore rattrapée",
         "Je vais lire vos mails" not in final, final[:160])

# ══════════════════════════════════════════════════════════════════════════
# 3. LES VIGNETTES `doc` DEVIENNENT LES VRAIES CARTES, MÊME SANS HISTORIQUE
# ══════════════════════════════════════════════════════════════════════════
print("\n── 3. Les trois vignettes de 05:54, sur un fil vide")
REPONSE_0554 = (
    "Oui, tout est terminé. Trois documents sont prêts et téléchargeables :\n\n"
    "```ui\n{\"type\":\"doc\",\"name\":\"Dossier projet paysager M. et Mme Camp\",\"kind\":\"DOCX\",\"meta\":\"3 pages, 26 éléments\"}\n```\n\n"
    "```ui\n{\"type\":\"doc\",\"name\":\"Inventaire — MR ET MME CAMP\",\"kind\":\"XLSX\",\"meta\":\"1 feuille\"}\n```\n\n"
    "```ui\n{\"type\":\"doc\",\"name\":\"DSN_082026\",\"kind\":\"PDF\",\"meta\":\"8,8 Ko\"}\n```\n\n"
    "Le dossier projet paysager (Word, 3 pages) est le livrable principal, l'inventaire "
    "Excel le complète, et le DSN est joint tel quel.")
r = livrables(REPONSE_0554, {"tool_results": [], "messages": [], "user_id": "89ebd52c"})
verifier("plus aucune vignette `doc` sans adresse", '"type": "doc"' not in r and '"type":"doc"' not in r, r[:300])
for d in DOCS_FINIS:
    verifier(f"la carte réelle de « {d['titre']} » est là, avec son adresse et son format",
             f"/api/documents/{d['document_id']}" in r and f"\"format\": \"{d['format']}\"" in r, r[-400:])
verifier("trois cartes `fichier`, une par document (pas seulement la dernière)",
         r.count('"type": "fichier"') == 3, str(r.count('"type": "fichier"')))
verifier("le nom de fichier porte l'extension, comme la carte de terminer_document",
         '"nom": "Dossier projet paysager M. et Mme Camp.docx"' in r)
verifier("la prose du modèle est intacte", r.startswith("Oui, tout est terminé"))

# Une vignette qui ne nomme aucun document tenu reste ce qu'elle était : un
# résultat de recherche documentaire, pas une invention.
autre = "Voici le document trouvé :\n\n" + bloc_ui({"type": "doc", "name": "CCTP lot 3 - plantations.pdf"})
r = livrables(autre, {"tool_results": [], "messages": [], "user_id": "89ebd52c"})
verifier("une vignette sans rapport avec l'atelier n'est pas touchée",
         "CCTP lot 3" in r and "/api/documents/" not in r, r[:200])

# Le fil, quand il existe, prime (version la plus récente du même titre).
FIL = {"type": "fichier", "url": "/api/documents/VERSION-DU-FIL",
       "nom": "Dossier projet paysager M. et Mme Camp.docx",
       "titre": "Dossier projet paysager M. et Mme Camp", "format": "docx", "octets": 40435}
r = livrables("Voici :\n\n" + bloc_ui({"type": "doc", "name": "Dossier projet paysager M. et Mme Camp", "kind": "DOCX"}),
              {"tool_results": [], "messages": [_Msg(bloc_ui(FIL))], "user_id": "89ebd52c"})
verifier("le fil prime sur l'atelier pour un même document", "VERSION-DU-FIL" in r and r.count('"type": "fichier"') == 1, r[-300:])

# Sans atelier (autre personne, dossier vide) : rien n'est inventé.
DOCS_FINIS_SAUVE = list(DOCS_FINIS)
DOCS_FINIS.clear()
r = livrables(REPONSE_0554, {"tool_results": [], "messages": [], "user_id": "inconnu"})
verifier("sans document fini ni fil, le texte est rendu tel quel", r == REPONSE_0554, r[:120])
DOCS_FINIS.extend(DOCS_FINIS_SAUVE)

# ══════════════════════════════════════════════════════════════════════════
# 4. SEPT RECHERCHES WEB, UN TABLEAU
# ══════════════════════════════════════════════════════════════════════════
print("\n── 4. Les tableaux du web")


def res_web(requete, urls):
    return {"skill": "chercher_web", "ok": True,
            "resultat_masque": json.dumps({"requete": requete, "trouve": True, "bloc_garanti": True,
                                           "bloc_ui": {"type": "table", "titre": f"Recherche web — {requete}",
                                                       "columns": ["Adresse consultée"], "rows": [[u] for u in urls]}},
                                          ensure_ascii=False)}


resultats = [res_web("panneau Tokyo", ["https://a.fr/tokyo", "https://b.fr"]),
             res_web("panneau Tokyo dimensions", ["https://a.fr/tokyo", "https://c.fr"]),
             res_web("gazon King Park", ["https://d.fr/king-park"])]
r = blocs_garantis("Voici le dossier.", {"tool_results": resultats, "user_id": "x"})
verifier("trois recherches web donnent UN tableau", r.count('"type": "table"') == 1, r)
verifier("… qui porte l'union des adresses, sans doublon",
         all(u in r for u in ("https://a.fr/tokyo", "https://b.fr", "https://c.fr", "https://d.fr/king-park"))
         and r.count("https://a.fr/tokyo") == 1, r)
r = blocs_garantis("Voici.", {"tool_results": resultats[:1], "user_id": "x"})
verifier("une seule recherche garde son tableau titré par la requête", "Recherche web — panneau Tokyo" in r, r)

# ══════════════════════════════════════════════════════════════════════════
# 5. LE CODE LIVRÉ : plan approuvé, forceur, écran, nginx
# ══════════════════════════════════════════════════════════════════════════
print("\n── 5. Ce que le code livré porte")
agent1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("le point d'étape ne coupe pas un plan approuvé",
         'if jalon and iteration >= POINT_ETAPE_ACTIONS and not state.get("plan_valide"):' in agent1)
verifier("le forceur retient le RIEN explicite (`forcage_refuse`)",
         '"forcage_refuse": refuse' in agent1 and '.upper() == "RIEN"' in agent1)
verifier("le dernier filet (« rien n'a été fait ») épargne l'accord en attente et le RIEN",
         'and not state.get("pending_action") and not state.get("requires_validation") \\' in agent1
         and 'and not state.get("forcage_refuse"):' in agent1)
for nom in ("state.py", "runtime.py", "router.py"):
    src = (BACKEND / "agents" / nom).read_text(encoding="utf-8")
    verifier(f"`forcage_refuse` est déclaré et remis à zéro ({nom})", "forcage_refuse" in src)
inventaire = (BACKEND / "skills" / "inventaire.py").read_text(encoding="utf-8")
verifier("l'inventaire ne montre pas une erreur Python comme raison",
         "incident technique, journalisé" in inventaire)

chatwin = (RACINE / "frontend" / "components" / "chat" / "ChatWindow.tsx").read_text(encoding="utf-8")
verifier("l'écran attend la fin d'une reprise coupée par le mandataire",
         "const attendreFinDeReprise = (id: string, cle: string) =>" in chatwin
         and "attendreFinDeReprise(id, cle)" in chatwin)
verifier("… relit le fil et libère le fil principal à la fin",
         "await chargerHistorique(tid)" in chatwin.split("const attendreFinDeReprise")[1].split("const resoudreAccord")[0]
         and "principalOccupeRef.current = false" in chatwin.split("const attendreFinDeReprise")[1].split("const resoudreAccord")[0])
verifier("… seulement sur un délai ou une coupure (502, 504, 408, réseau), jamais sur un 403/409",
         "e?.status === 502 || e?.status === 504 || e?.status === 408 || !e?.status" in chatwin)
nginx = (RACINE / "nginx" / "nginx.conf").read_text(encoding="utf-8")
i = nginx.find("location /api/validations/")
verifier("nginx laisse « Approuver » durer un tour entier (3600 s)",
         i > 0 and "proxy_read_timeout 3600s;" in nginx[i:i + 800])
verifier("… et ce bloc précède le bloc générique /api/", 0 < i < nginx.find("location /api/ {"))

# ── Symbiose seulement ────────────────────────────────────────────────────
source = BACKEND / "classement" / "source.py"
if source.exists() and "google_drive" in source.read_text(encoding="utf-8"):
    print("\n── 6. Symbiose : l'inventaire lit le Drive, le 503 patiente")
    src = source.read_text(encoding="utf-8")
    verifier("l'inventaire lit le Drive par le binaire et le lecteur par type, plus par `d._download_text`",
             "d._binaire(" in src and "lire_sans_deposer(" in src
             and "to_thread(d._download_text" not in src)
nano = BACKEND / "visuels" / "nano_banana.py"
if nano.exists():
    src = nano.read_text(encoding="utf-8")
    verifier("le 503 se réessaie cinq fois (0, 5, 15, 30, 45 s)", "enumerate((0, 5, 15, 30, 45))" in src)
    verifier("le message du tirage manqué ne nomme aucun skill", "`tester_visuel`" not in src.split("qualite == \"finale\"")[1][:600])

print(f"\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ tout passe'}\n")
sys.exit(1 if echecs else 0)
