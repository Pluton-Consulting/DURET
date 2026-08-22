"""
Banc du protocole natif — l'appel d'outil tel que LongCat l'écrit VRAIMENT.

Relevé le 22/08 : « <longcat_tool_call>lire_mails} … <longcat_arg_key>args
</longcat_arg_key><longcat_arg_value>{"depuis":"7j","limite":25}</longcat_arg_value> »
— une accolade collée au nom, et tous les paramètres sous une seule clé
« args ». Le bloc était jeté, le tour se fermait sur « Je vais lire les
mails ». Ce banc rejoue ces formes sur le parseur livré, avec un catalogue
doublé (pas de base).
"""
import sys, types, pathlib, importlib.util

BACKEND = sys.argv[1] if len(sys.argv) > 1 else "backend"
sys.path.insert(0, BACKEND)
# protocol.py importe le registre paresseusement ; on lui donne un catalogue fixe.
spec = importlib.util.spec_from_file_location("skills.protocol", pathlib.Path(BACKEND)/"skills"/"protocol.py")
protocol = importlib.util.module_from_spec(spec)
sys.modules["skills.protocol"] = protocol
paquet = types.ModuleType("skills"); paquet.protocol = protocol; sys.modules.setdefault("skills", paquet)
spec.loader.exec_module(protocol)
protocol.catalogue = lambda role=None: {
    "lire_mails": ("…", [], ["mailbox", "dossier", "limite", "depuis"]),
    "fiche_client": ("…", ["nom"], []),
    "modifier_visuel": ("…", ["image", "changements"], ["titre"]),
}

echecs = []
def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond: echecs.append(nom)

print(f"\n═══ PROTOCOLE NATIF — {BACKEND}\n")
CAS_22_08 = ('Je consulte les mails de la semaine.<longcat_tool_call>lire_mails}\n'
             '<longcat_arg_key>args</longcat_arg_key>\n'
             '<longcat_arg_value>{"depuis": "7j", "limite": 25}</longcat_arg_value>\n'
             '</longcat_tool_call>\n')
action, reste, erreur = protocol.extraire_action(CAS_22_08, None)
verifier("la forme exacte du 22/08 est comprise", action is not None, erreur)
verifier("le nom est nettoyé de son accolade", action and action["skill"] == "lire_mails", action)
verifier("les paramètres sous « args » sont dépliés",
         action and action["args"] == {"depuis": "7j", "limite": 25}, action and action["args"])
verifier("le texte autour est conservé", "Je consulte" in reste, reste)

propre = ('<longcat_tool_call>fiche_client\n<longcat_arg_key>nom</longcat_arg_key>'
          '<longcat_arg_value>SCI Les Tilleuls</longcat_arg_value></longcat_tool_call>')
a, _, e = protocol.extraire_action(propre, None)
verifier("la forme propre marche toujours", a == {"skill": "fiche_client", "args": {"nom": "SCI Les Tilleuls"}}, (a, e))

inconnu = '<longcat_tool_call>envoyer_fusee\n<longcat_arg_key>x</longcat_arg_key><longcat_arg_value>1</longcat_arg_value></longcat_tool_call>'
a, _, e = protocol.extraire_action(inconnu, None)
verifier("un nom inconnu rend une ERREUR (réparation), pas un silence", a is None and e and "n'existe pas" in e, e)

manque = '<longcat_tool_call>modifier_visuel\n<longcat_arg_key>image</longcat_arg_key><longcat_arg_value>79800c896bd4e138b125d2d0</longcat_arg_value></longcat_tool_call>'
a, _, e = protocol.extraire_action(manque, None)
verifier("un paramètre obligatoire manquant rend une ERREUR nommant le paramètre",
         a is None and e and "changements" in e, e)

bloc = '```action\n{"skill":"lire_mails","args":{"depuis":"7j"}}\n```'
a, _, e = protocol.extraire_action(bloc, None)
verifier("le bloc ```action ordinaire est inchangé", a == {"skill": "lire_mails", "args": {"depuis": "7j"}}, (a, e))

print(f"\n═══ {len(echecs)} échec(s)" + (f" : {', '.join(echecs)}" if echecs else " — tout passe"))
sys.exit(1 if echecs else 0)
