"""
Banc « plusieurs composants dans un même bloc ```ui » — 20/09.

RELEVÉ DE NOA, en production : « je lui ai demandé d'afficher tous les mails du
jour, il m'a affiché UN mail et m'a dit combien j'en avais aujourd'hui, alors
qu'il aurait dû afficher des cartes avec l'entièreté des mails ».

Ce n'était pas le modèle : les quatre cartes `email` étaient bien là, justes et
complètes, relues en base. Mais elles tenaient dans UN SEUL bloc balisé, une par
ligne — ce qu'un modèle écrit naturellement quand une demande appelle plusieurs
composants du même type. Personne ne savait relire cette forme :

* à l'écran, `lire()` répare un JSON abîmé en RECULANT : devant quatre objets à
  la suite, elle a tout jeté sauf le premier ;
* côté serveur, `_BLOC_UI_RE` capture tout le contenu du bloc, mais
  `json.loads` refuse quatre objets à la suite — le bloc était donc INVISIBLE
  pour le dédoublonnage, les livrables face au fil, les blocs garantis et les
  images du fil.

Ce banc prouve le défaut (la lecture d'AVANT ne rend qu'un bloc sur quatre),
puis le correctif : `agents/blocs.eclater` ramène la forme écrite par le modèle
à l'invariant du reste du code — un bloc, un objet — sans rien lui interdire et
sans rien perdre. Il vérifie enfin que les trois chemins qui mènent à l'écran
l'appliquent : `rehydrate_node`, la reprise après accord, et l'expert vision.

    python3 backend/scripts/test_blocs_groupes.py [backend]
"""
import importlib.util
import json
import pathlib
import re
import sys

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def charger(chemin, nom):
    spec = importlib.util.spec_from_file_location(nom, chemin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


blocs = charger(BACKEND / "agents" / "blocs.py", "blocs_ui_banc")
objets, eclater = blocs.objets, blocs.eclater

# ON MESURE AVEC LE MOTIF DES FILETS, PAS AVEC UN MOTIF ÉCRIT ICI. Celui qui
# décide si un bloc est lisible vit dans agent1 ; on le relit dans le source
# livré, sans importer le module (qui tire tout le graphe avec lui).
_motif = re.search(r'_BLOC_UI_RE = _re_livrables\.compile\((r"[^"]+"), _re_livrables\.S\)',
                   (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8"))
if not _motif:
    print("  ✗ motif _BLOC_UI_RE introuvable dans agent1.py")
    sys.exit(1)
BLOC_UI_RE = re.compile(eval(_motif.group(1)), re.S)


def lisibles(texte):
    """Ce que les filets du serveur savent relire : un bloc = un objet JSON."""
    lus = []
    for brut in BLOC_UI_RE.findall(texte):
        try:
            lus.append(json.loads(brut))
        except ValueError:
            pass
    return lus


# ── La forme EXACTE de production, contenu neutralisé ────────────────────────
# Quatre cartes `email` dans un seul bloc, puis les pastilles de suites dans le
# leur. Les extraits portent des accolades et des guillemets échappés : c'est
# ce qui casse un découpage naïf.
PROD = (
    "Les 4 mails reçus aujourd'hui, ouverts en entier :\n\n"
    "```ui\n"
    '{"type":"email","subject":"Re: 12 14 Marronniers - attestations de conformité",'
    '"from":"APP <contact@exemple-platrerie.fr>","date":"20/09/2026 20:01",'
    '"preview":"Le bureau de contrôle réclame les justificatifs manquants {étude carbone} ; '
    'il a écrit \\"bloquant pour la vente\\" dans son dernier message."}\n'
    '{"type":"email","subject":"[Action requise] Nouvelle candidature — Chauffeur livreur H/F",'
    '"from":"Recrutement <candidatures@exemple-emploi.fr>","date":"20/09/2026 14:35",'
    '"preview":"Un candidat a postulé à l\'offre publiée. Profil et CV joints."}\n'
    '{"type":"email","subject":"On les enlève... puis elles reviennent 🫆",'
    '"from":"Cleaners <contact@exemple-nettoyage.fr>","date":"20/09/2026 07:05",'
    '"preview":"Publicité : nettoyage de vitres sans traces. Sans lien avec nos chantiers."}\n'
    '{"type":"email","subject":"[Portail] Liste de travail du 19/09/2026",'
    '"from":"notification@exemple-portail.gouv.fr","date":"20/09/2026 06:02",'
    '"preview":"Notifications quotidiennes : dossier de facturation, pour information."}\n'
    "```\n\n"
    "À retenir : seul le mail de APP appelle une action de notre côté.\n\n"
    "```ui\n"
    '{"type":"quick_replies","options":["Réponds à APP","Classe les 4 mails du jour"]}\n'
    "```"
)

print("\n── LE DÉFAUT, TEL QU'IL ÉTAIT ───────────────────────────────────────")
avant = lisibles(PROD)
verifier("la lecture d'AVANT ne rend qu'UN bloc sur les cinq écrits",
         len(avant) == 1 and avant[0]["type"] == "quick_replies",
         f"{len(avant)} bloc(s) : {[b.get('type') for b in avant]}")
verifier("les quatre cartes email étaient donc invisibles des filets ET de l'écran",
         not any(b.get("type") == "email" for b in avant))

print("\n── LE DÉCOUPAGE ─────────────────────────────────────────────────────")
verifier("un objet seul rend un seul morceau",
         objets('{"type":"table","rows":[]}') == ['{"type":"table","rows":[]}'])
verifier("quatre objets à la suite en rendent quatre",
         len(objets('{"a":1}\n{"b":2}\n{"c":3}\n{"d":4}')) == 4)
verifier("une accolade DANS une chaîne ne coupe rien",
         objets('{"t":"un {piège} ici"}{"u":2}') == ['{"t":"un {piège} ici"}', '{"u":2}'])
verifier("un guillemet échappé ne ferme pas la chaîne",
         objets('{"t":"il a dit \\"oui\\" puis"}{"u":2}') ==
         ['{"t":"il a dit \\"oui\\" puis"}', '{"u":2}'])
verifier("les objets imbriqués ne coupent pas au premier accolade fermante",
         objets('{"a":{"b":{"c":1}}}{"d":2}') == ['{"a":{"b":{"c":1}}}', '{"d":2}'])
tronque = objets('{"a":1}\n{"b":"jamais refer')
verifier("un dernier objet tranché net forme bien son propre morceau",
         len(tronque) == 2 and tronque[1].startswith('{"b"'), tronque)

print("\n── LA MISE À PLAT ───────────────────────────────────────────────────")
apres = eclater(PROD)
lus = lisibles(apres)
verifier("les CINQ blocs sont désormais lisibles", len(lus) == 5,
         f"{len(lus)} : {[b.get('type') for b in lus]}")
verifier("les quatre cartes email y sont, dans l'ordre",
         [b["type"] for b in lus] == ["email"] * 4 + ["quick_replies"])
verifier("l'objet du premier mail est intact",
         lus[0]["subject"] == "Re: 12 14 Marronniers - attestations de conformité")
verifier("l'extrait qui portait une accolade et des guillemets est intact",
         "{étude carbone}" in lus[0]["preview"] and '"bloquant pour la vente"' in lus[0]["preview"])
verifier("le texte rédigé autour des blocs n'a pas bougé",
         "Les 4 mails reçus aujourd'hui" in apres and "seul le mail de APP" in apres)

print("\n── CE QU'ON NE CASSE PAS ────────────────────────────────────────────")
seul = "Voici.\n\n```ui\n{\"type\":\"table\",\"columns\":[\"A\"],\"rows\":[[\"1\"]]}\n```"
verifier("un bloc à un seul objet n'est pas touché", eclater(seul) == seul)
verifier("un texte sans bloc n'est pas touché", eclater("Bonjour.") == "Bonjour.")
verifier("un texte vide ne lève pas", eclater("") == "" and eclater(None) is None)
# Un objet SANS `type` n'est pas un composant : c'est du JSON que le modèle
# montre volontairement. On laisse le bloc entier au texte, comme avant.
sans_type = "```ui\n{\"a\":1}\n{\"b\":2}\n```"
verifier("un bloc d'objets sans `type` reste au texte", eclater(sans_type) == sans_type)
# Illisible AU MILIEU : forme inattendue, on ne touche à rien.
casse = "```ui\n{\"type\":\"email\",\"subject\":\"a\"}\n{pas du json}\n{\"type\":\"doc\",\"name\":\"b\"}\n```"
verifier("un morceau illisible au milieu laisse le bloc intact", eclater(casse) == casse)
# Tranché EN FIN : le morceau était déjà perdu (l'écran ne relisait que le
# premier). On garde ce qui tient debout plutôt que de tout perdre.
coupe = ("```ui\n{\"type\":\"email\",\"subject\":\"a\",\"from\":\"x@exemple-sols.fr\"}\n"
         "{\"type\":\"email\",\"subject\":\"b\",\"from\":\"y@exemple-sols.fr\"}\n"
         "{\"type\":\"email\",\"subject\":\"c\",\"fro")
gardes = lisibles(eclater(coupe))
verifier("un bloc tranché en plein vol garde les cartes entières",
         len(gardes) == 2 and [b["subject"] for b in gardes] == ["a", "b"],
         [b.get("subject") for b in gardes])

print("\n── LES CHEMINS QUI MÈNENT À L'ÉCRAN ─────────────────────────────────")
src_agent1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("agent1 prend la mise à plat dans le module partagé",
         "from agents.blocs import eclater as _eclater_blocs_ui" in src_agent1)
pose = src_agent1.find("text = _eclater_blocs_ui(text)")
filet = src_agent1.find("text = _livrables_a_l_ecran(text, state)")
verifier("rehydrate_node met à plat AVANT les filets",
         0 < pose < filet, f"mise à plat {pose}, filet {filet}")
verifier("la reprise après accord la pose aussi",
         "_eclater_blocs_ui" in (BACKEND / "agents" / "router.py").read_text(encoding="utf-8"))
verifier("l'expert vision la pose aussi (son graphe n'a pas de rehydrate)",
         "_eclater_blocs_ui" in (BACKEND / "agents" / "agent2.py").read_text(encoding="utf-8"))

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
