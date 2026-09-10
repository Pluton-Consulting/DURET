"""
Banc de L'APPEL D'OUTIL BALISÉ — le routeur et l'exécuteur voient la MÊME chose.

CE QUI S'EST PASSÉ LE 10/09 (Symbiose, prod, compte direction, fil 54906468).
Quatre demandes d'affilée ont reçu pour toute réponse… l'appel d'outil du
modèle, affiché tel quel :

  06:25  « recherches les factures du fournisseur BTF sur l'année 2026 et donne
          moi le CA »                    → « <interroger_donnees>{"source_type":
          "fournisseur"}</interroger_donnees> »
  06:33  « peux tu trouver toutes les factures … et me dire le montant total »
                                         → « <interroger_donnees>{}</interroger_donnees> »
  06:34  la même, « dans notre drive »   → « <action>{"skill":"drive_chercher",
          "args":{"motif":"BTF"}}</action> »
  06:43  « nous avons acheté un fiat doblo au mois de juillet, quel est sa
          puissance ? »                  → « <action>{"skill":"rechercher_documents",
          "args":{"requete":"Fiat Dobló"}}</action> »

LA CAUSE : DEUX DÉTECTEURS POUR UNE MÊME QUESTION. `route_apres_llm` ne
cherchait que le bloc ```action et la syntaxe LongCat ; `tools_node`, lui,
appelle `extraire_action`, qui connaît deux formes de plus. Le routeur étant le
plus ÉTROIT des deux, l'action mourait AVANT l'exécuteur — et comme rien ne
retirait le balisage, il partait à l'écran en guise de réponse.

Les deux modèles de l'assistant (DeepSeek v4 sur Ollama Cloud) dérivent ainsi
sur 4 appels sur 131 ce jour-là : rare, mais chaque dérive coûte un tour
entier, alors que le choix d'outil du modèle était le bon.

Ce banc EXÉCUTE le parseur livré et le routeur livré sur les quatre textes
exacts de production. Ni base, ni réseau. Il sait échouer : joué sur la
version d'avant, il rend 30 contrôles rouges — dont les quatre tours qui
partent en « rehydrate » avec leur balisage intact à l'écran, c'est-à-dire le
symptôme exact vu par le client.

Usage : python backend/scripts/test_appel_outil_balise.py [backend]
"""
import sys, ast, pathlib, types, importlib.util

BACKEND = sys.argv[1] if len(sys.argv) > 1 else "backend"
racine = pathlib.Path(BACKEND)
sys.path.insert(0, BACKEND)

echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


# ── Le module livré, avec un catalogue doublé (pas de base) ───────────────
spec = importlib.util.spec_from_file_location(
    "skills.protocol", racine / "skills" / "protocol.py")
protocol = importlib.util.module_from_spec(spec)
sys.modules["skills.protocol"] = protocol
paquet = types.ModuleType("skills")
paquet.protocol = protocol
sys.modules.setdefault("skills", paquet)
spec.loader.exec_module(protocol)
protocol.catalogue = lambda role=None: {
    "interroger_donnees": ("…", [], ["source_type", "contient", "depuis"]),
    "rechercher_documents": ("…", ["requete"], ["limite", "page"]),
    "drive_chercher": ("…", ["motif"], ["type"]),
    "nas_chercher": ("…", ["motif"], ["dossier"]),
    "lire_mails": ("…", [], ["depuis", "limite"]),
    "chercher_web": ("…", ["requete"], []),
    "modifier_visuel": ("…", ["image", "changements"], []),
}

# LES QUATRE TEXTES DE PRODUCTION, au caractère près (relevés dans l'export
# Langfuse 1789024660417, champ `llm_response` du nœud `llm`).
T_BTF_VIDE = '\n\n<interroger_donnees>\n{}\n</interroger_donnees>'
T_BTF_FOURN = '\n\n<interroger_donnees>\n{"source_type": "fournisseur"}\n</interroger_donnees>'
T_DRIVE = '\n\n<action>\n{"skill":"drive_chercher","args":{"motif":"BTF"}}\n</action>'
T_VEHICULE = ('\n\n<action>\n{"skill":"rechercher_documents",'
              '"args":{"requete":"Fiat Dobló"}}\n</action>')
PRODUCTION = [("BTF sans argument", T_BTF_VIDE, "interroger_donnees", {}),
              ("BTF fournisseur", T_BTF_FOURN, "interroger_donnees",
               {"source_type": "fournisseur"}),
              ("BTF sur le Drive", T_DRIVE, "drive_chercher", {"motif": "BTF"}),
              ("la puissance du Doblo", T_VEHICULE, "rechercher_documents",
               {"requete": "Fiat Dobló"})]

print(f"\n═══ APPEL D'OUTIL BALISÉ — {BACKEND}\n")
print("1. Le parseur lit les quatre formes de production")
for nom, texte, skill, args in PRODUCTION:
    action, reste, erreur = protocol.extraire_action(texte, "direction")
    verifier(f"« {nom} » est comprise", action is not None, erreur)
    verifier(f"« {nom} » nomme le bon geste",
             action and action["skill"] == skill, action)
    verifier(f"« {nom} » porte les bons paramètres",
             action and action["args"] == args, action and action["args"])
    verifier(f"« {nom} » : la balise QUITTE le texte (ouvrante ET fermante)",
             "<" not in reste and ">" not in reste, repr(reste))

print("\n2. Le détecteur est le MÊME pour le routeur et pour l'exécuteur")
# UN BANC DOIT SAVOIR ÉCHOUER, PAS S'INTERROMPRE. Sur la version d'avant le
# détecteur unique n'existe pas : on le dit, on repose l'ancienne règle (les
# deux regex du routeur) et on laisse la suite du banc rendre son verdict.
if not hasattr(protocol, "demande_une_action"):
    verifier("le module livré expose un détecteur unique (`demande_une_action`)", False,
             "absent : le routeur et l'exécuteur ne peuvent pas voir la même chose")
    protocol.demande_une_action = lambda texte, role=None: bool(
        protocol.BLOC_ACTION_RE.search(texte or "")
        or protocol.BLOC_NATIF_RE.search(texte or ""))
for nom, texte, _, _ in PRODUCTION:
    verifier(f"« {nom} » est reconnue comme un appel d'outil",
             protocol.demande_une_action(texte, "direction") is True)
verifier("le bloc ```action reste reconnu",
         protocol.demande_une_action(
             '```action\n{"skill":"lire_mails","args":{"depuis":"7j"}}\n```', "direction"))
verifier("la syntaxe native de LongCat reste reconnue",
         protocol.demande_une_action(
             '<longcat_tool_call>lire_mails\n<longcat_arg_key>depuis</longcat_arg_key>'
             '<longcat_arg_value>7j</longcat_arg_value></longcat_tool_call>', "direction"))

print("\n3. Une vraie réponse n'est JAMAIS prise pour un appel d'outil")
PROSE = [
    "Le Fiat Doblò acheté en juillet développe 95 ch d'après la facture.",
    "Je ne trouve aucune facture BTF dans nos documents. Voulez-vous que je "
    "cherche sur le Drive ?",
    "Le tarif est <de 3 €> la pièce, hors pose.",
    "Voici le comparatif : <avant> 12 m², <après> 18 m².",
    "```ui\n{\"type\": \"table\", \"columns\": [\"Nom\"], \"rows\": [[\"BTF\"]]}\n```",
]
for p in PROSE:
    verifier(f"« {p[:44]}… » reste de la prose",
             protocol.demande_une_action(p, "direction") is False)
    a, reste, e = protocol.extraire_action(p, "direction")
    verifier(f"« {p[:44]}… » n'est pas amputée", reste == p.strip(), repr(reste[:60]))

print("\n4. Une action balisée FAUTIVE se répare, elle ne s'évapore pas")
a, _, e = protocol.extraire_action('<action>{"skill":"envoyer_fusee","args":{}}</action>',
                                   "direction")
verifier("un skill inconnu rend une ERREUR (le modèle se corrige)",
         a is None and e and "n'existe pas" in e, e)
verifier("et l'erreur compte comme une demande d'action",
         protocol.demande_une_action('<action>{"skill":"envoyer_fusee","args":{}}</action>',
                                     "direction") is True)
a, _, e = protocol.extraire_action('<modifier_visuel>{"image":"a1b2c3"}</modifier_visuel>',
                                   "direction")
verifier("un paramètre obligatoire manquant est NOMMÉ",
         a is None and e and "changements" in e, e)
a, _, e = protocol.extraire_action('<lire_mails>{"args":{"depuis":"7j"}}</lire_mails>',
                                   "direction")
verifier("les paramètres repliés sous « args » sont dépliés",
         a == {"skill": "lire_mails", "args": {"depuis": "7j"}}, (a, e))
# LA RÉPARATION LOCALE EXIGE `json_repair`, qui vit dans l'image et pas sur ce
# Mac. On ne la déclare pas verte quand on ne l'a pas jouée : elle se dit « à
# lire », comme le banc de recette le fait pour ce qu'aucune règle ne juge.
try:
    import json_repair  # noqa: F401
except ImportError:
    print("  · « une virgule de trop se répare sur place » — à lire : "
          "json_repair absent de ce poste (présent dans l'image)")
else:
    a, _, e = protocol.extraire_action('<action>\n{"skill":"lire_mails",}\n</action>',
                                       "direction")
    verifier("une virgule de trop se répare sur place",
             a == {"skill": "lire_mails", "args": {}}, (a, e))


# ── Le routeur du graphe, extrait du module livré ─────────────────────────
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


_spec = importlib.util.spec_from_file_location("annonce", racine / "agents" / "annonce.py")
annonce = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(annonce)


class _Journal:
    def info(self, *a, **k):
        pass
    warning = info
    error = info


espace = {
    "AgentState": dict,
    "logger": _Journal(),
    "_tracer_filet": lambda *a, **k: None,
    "_blocs_livrables": lambda resultats: [],
    "_montre_un_fichier_du_fil": lambda visible, state: False,
    "_reponses_mail_manquantes": lambda state, texte: False,
    "_derniere_reponse_assistant": lambda state: "",
    "cles_images_du_fil": lambda state: [],
    "MAX_FORCAGES_PAR_TOUR": 2,
}
for nom in ("est_une_annonce", "promesse_sans_suite", "cloture_attendue",
            "pretend_avoir_livre", "demande_une_production", "propose_au_lieu_d_agir",
            "renvoie_au_deja_fait", "demande_sur_le_passe", "demande_un_visuel",
            "demande_de_montrer", "decrit_un_contenu_lu", "suite_qui_retouche",
            "deuxieme_salve_de_questions"):
    espace[nom] = getattr(annonce, nom)
extraire(racine / "agents" / "agent1.py",
         {"route_apres_llm", "route_apres_forcage", "_texte_visible"}, espace)
route = espace["route_apres_llm"]
route_forcage = espace["route_apres_forcage"]
visible = espace["_texte_visible"]

QUESTIONS = {
    T_BTF_VIDE: "peux tu trouver toutes les factures du fournisseur BTF (bois travaux "
                "forestier)  sur l'année 2026 et me dire le montant total",
    T_BTF_FOURN: "recherches les factures du fournisseur BTF sur l'année 2026 et donne moi le CA",
    T_DRIVE: "peux tu trouver toutes les factures du fournisseur BTF (bois travaux "
             "forestier)  sur l'année 2026, dans notre drive,  et me dire le montant total",
    T_VEHICULE: "nous avons acheté un fiat doblo au mois de juillet, quel est sa puissance ?",
}


def etat(texte, **extra):
    base = {"llm_response": texte, "query": QUESTIONS.get(texte, ""),
            "user_role": "direction", "tool_results": [], "forcages": 0,
            "messages": []}
    base.update(extra)
    return base


print("\n5. LE ROUTEUR — les quatre tours de production atteignent l'exécuteur")
for nom, texte, _, _ in PRODUCTION:
    verifier(f"« {nom} » part au nœud d'exécution", route(etat(texte)) == "tools",
             route(etat(texte)))

print("\n6. Rien d'autre n'a bougé dans le routeur")
verifier("le bloc ```action part toujours à l'exécution",
         route(etat('```action\n{"skill":"lire_mails","args":{"depuis":"7j"}}\n```')) == "tools")
verifier("une vraie réponse va toujours à la réhydratation",
         route(etat("Le Doblò développe 95 ch d'après la facture d'achat.")) == "rehydrate")
verifier("une annonce sans acte part toujours au forceur",
         route(etat("Je vais chercher les factures BTF sur le Drive.")) == "forcer")
verifier("en dernière passe, une action balisée vaut une annonce (rédaction redemandée)",
         route(etat(T_DRIVE, tools_finished=True,
                    tool_results=[{"skill": "drive_chercher", "ok": True}])) == "rediger")
verifier("le FORCEUR aussi reconnaît une action balisée",
         route_forcage(etat(T_VEHICULE)) == "tools")
verifier("le forceur muet termine toujours le tour",
         route_forcage(etat("Je ne peux rien faire de plus.")) == "rehydrate")

print("\n7. Un appel d'outil ne vaut ZÉRO caractère pour la personne")
for nom, texte, _, _ in PRODUCTION:
    verifier(f"« {nom} » ne laisse rien à l'écran", visible(texte) == "", repr(visible(texte)))
verifier("le texte utile autour d'une action est conservé",
         visible("Je regarde dans les documents.\n" + T_VEHICULE)
         == "Je regarde dans les documents.",
         repr(visible("Je regarde dans les documents.\n" + T_VEHICULE)))
verifier("une vraie réponse n'est pas rabotée",
         visible("Le tarif est <de 3 €> la pièce.") == "Le tarif est <de 3 €> la pièce.")

print("\n8. MONTRER N'EST PAS FAIRE, et nettoyer n'est pas mutiler")
#    Trouvés par la revue adverse du 10/09, dans le correctif lui-même.
CITATION = ("Voici comment je m'y prends :\n\n```xml\n"
            "<lire_mails>{\"depuis\":\"7j\"}</lire_mails>\n```\n\nC'est tout.")
a, _, _ = protocol.extraire_action(CITATION, "direction")
verifier("un appel d'outil CITÉ dans un bloc de code n'est pas exécuté", a is None, a)
verifier("et il n'est pas effacé de la réponse (c'est l'explication demandée)",
         "lire_mails" in visible(CITATION), repr(visible(CITATION)[:80]))
HTML = 'Le gabarit ressemble à ceci : <div>{"nom": "Martin"}</div> — à compléter.'
verifier("une balise qui ne nomme aucun skill n'est pas un appel d'outil",
         protocol.demande_une_action(HTML, "direction") is False)
verifier("et elle survit intacte à l'écran", visible(HTML) == HTML, repr(visible(HTML)))
INCONNUE = 'La configuration <reglage>{"a":1}</reglage> reste inchangée.'
verifier("idem pour une balise métier inventée", visible(INCONNUE) == INCONNUE,
         repr(visible(INCONNUE)))

print(f"\n═══ {len(echecs)} échec(s)" + (f" : {', '.join(echecs)}" if echecs else " — tout passe"))
sys.exit(1 if echecs else 0)
