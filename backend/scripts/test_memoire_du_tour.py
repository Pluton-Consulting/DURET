"""
Banc « LE MODÈLE SAIT CE QU'IL A DÉJÀ FAIT » — export Langfuse du 14/09, fil
c9f5a00d (Symbiose, compte direction).

Relevé de Noa : « il y a très souvent ce bug là » — 3 min 21 et deux gestes en
échec pour « tu peux l'enregistrer mais tu devras remplacer studio par
symbiose paysage » ; et, le même après-midi, « et voici le devis » : trente et
une minutes, 159 `ajouter_document`, 911 blocs, jamais terminé.

LES DEUX CAUSES QUE CE BANC ENFERME :
  1. À chaque passe de la boucle d'actions, le modèle repart d'un prompt NEUF.
     Ses blocs d'action précédents n'y sont pas, et les résultats lui
     arrivaient SANS leurs arguments. Il lisait « 6 élément(s) ajouté(s) » —
     jamais quoi. Chaque passe ressemblait à la première : il reversait
     l'en-tête du devis (153 variantes distinctes sur 159 appels), rejouait
     `reproduire_document` avec la même table. → `agents/memoire_gestes.py` :
     un journal, une ligne par geste, dans le prompt de la boucle ET du
     sélecteur d'actions.
  2. `tour_debut` n'était pas déclaré dans l'AgentState : LangGraph le jetait,
     et le temps imparti (huit minutes) n'a jamais tourné. (Banc à part :
     `test_etat_declare.py`.)
  Et le filet de la dernière chance, côté document : un versement dont
  l'essentiel est DÉJÀ dans le document est refusé, avec la structure du
  document sous les yeux (`bureautique/atelier.py::deja_presents`).

CE QUE CE BANC PROUVE (sans base, sans réseau, sans modèle) :
  · le journal EXÉCUTÉ sur les gestes du tour de 13:05 : chaque ligne dit ce
    qui a été versé (« titre «Devis N° DV0001451» »), l'issue et les comptes ;
    ni empreinte ni arguments bruts ne partent ; un long tour se replie ;
  · l'atelier RÉEL (dossier temporaire) : le deuxième versement du devis, à la
    ponctuation près, est refusé ; la section suivante passe ; un titre de
    section répété (« Aménagement Paysager ») passe ;
  · `ajouter_document` EXÉCUTÉ : le refus est un ÉCHEC qui porte la structure
    du document et dit quoi faire ; un succès rend `plan_du_document` ;
  · le contrat du code : `llm_node` et `forcer_action_node` passent par le
    journal ; `route_apres_llm` n'envoie plus au forceur une réponse qui a
    réellement ouvert un fichier.
Tombe sur la version d'avant (module absent, versement accepté).

Usage : python backend/scripts/test_memoire_du_tour.py [backend]
"""
import asyncio
import importlib
import json
import os
import pathlib
import sys
import tempfile
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
sys.path.insert(0, str(BACKEND))
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {str(detail)[:400]}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


# ── 1. Le journal des gestes ────────────────────────────────────────────────
print("1. Le journal des gestes du tour")
try:
    mg = importlib.import_module("agents.memoire_gestes")
except Exception as e:  # noqa: BLE001
    mg = None
    verifier("agents/memoire_gestes.py existe", False, e)

ENTETE_DEVIS = [
    {"bloc": "titre", "texte": "Devis N° DV0001451", "niveau": 2},
    {"bloc": "paragraphe", "texte": "Client : M. CAMP Nicolas — 20 avenue du Pinsan, 33370 ARTIGUES-PRÈS-BORDEAUX"},
    {"bloc": "paragraphe", "texte": "Suivi par : RADUSZYNSKI Julien — Date : 14/09/2026"},
    {"bloc": "paragraphe", "texte": "Aménagement de votre coin de paradis.", "gras": True},
    {"bloc": "tableau", "entetes": ["N°", "Description", "Montant HT"],
     "lignes": [["1", "Arrachage des plantes mortes", "1 990,00"], ["2", "Accès béton armé", "1 035,00"]]},
]
DOC = "XTW4ynmm5eDSzNU7N5ncdKYvKvZoxEfW"
gestes = [
    {"skill": "creer_document", "ok": True, "payload_hash": "c18d" * 16,
     "args": {"titre": "Dossier de conception paysagère - M. CAMP Nicolas", "format": "docx"},
     "resultat_masque": json.dumps({"document_id": DOC, "format": "docx"})},
    {"skill": "ajouter_document", "ok": True, "payload_hash": "b859" * 16,
     "args": {"document_id": DOC, "elements": ENTETE_DEVIS},
     "resultat_masque": json.dumps({"document_id": DOC, "ajoutes": 5, "total": 15, "ignores": 0})},
    {"skill": "reproduire_document", "ok": True, "payload_hash": "fc1b" * 16,
     "args": {"fichier": "fItbeyH6BAp4jbu88WYdhj1av8OcuvBK", "remplacements": {"STUDIO": "Symbiose Paysage"}},
     "resultat_masque": json.dumps({"remplacements": 0, "fichier": "Modèle (repris).docx"})},
    {"skill": "enregistrer_trame", "ok": False, "payload_hash": "8d39" * 16,
     "args": {"nom": "Dossier de conception paysagère", "fichier": "Lavèze.pdf"},
     "resultat_masque": "ERREUR : Je ne retrouve pas « Lavèze.pdf » : il pèse trop lourd."},
]
if mg:
    journal = mg.journal_des_gestes(gestes)
    lignes = [l for l in journal.splitlines() if l[:2].rstrip(".").isdigit()]
    verifier("une ligne numérotée par geste", len(lignes) == 4, journal)
    verifier("la ligne du versement dit CE QUI a été versé",
             "Devis N° DV0001451" in lignes[1] and "titre" in lignes[1] and "; +3]" in lignes[1], lignes[1])
    verifier("la ligne du versement dit l'issue et les comptes",
             "ok (ajoutes=5" in lignes[1], lignes[1])
    verifier("la table de remplacement essayée est dans le journal",
             "STUDIO" in lignes[2] and "Symbiose Paysage" in lignes[2] and "remplacements=0" in lignes[2], lignes[2])
    verifier("un échec dit sa raison", "ÉCHEC" in lignes[3] and "trop lourd" in lignes[3], lignes[3])
    verifier("aucune empreinte ne part au modèle", "c18d" * 4 not in journal)
    verifier("le journal dit de ne pas refaire", "Ne refais pas" in journal)
    verifier("chaque ligne reste courte", all(len(l) <= mg.MAX_LIGNE + 8 for l in lignes),
             max(len(l) for l in lignes))
    entree = mg.pour_le_modele(gestes[1])
    verifier("l'entrée détaillée ne porte ni args ni empreinte",
             "args" not in entree and "payload_hash" not in entree and "resultat_masque" in entree)
    rejeu = dict(gestes[2], resultat_masque="(déjà exécuté à ce tour, son résultat est inchangé)\n{}")
    verifier("un rejeu se dit comme tel", "rejeu" in mg.resume_geste(rejeu), mg.resume_geste(rejeu))
    long_tour = [gestes[0]] + [dict(gestes[1]) for _ in range(160)]
    jl = mg.journal_des_gestes(long_tour)
    verifier("un tour de 161 gestes se replie en tête, sans perdre le compte",
             "ajouter_document ×" in jl and jl.count("\n") <= mg.MAX_LIGNES_JOURNAL + 6, jl[:300])

# ── 2. L'atelier refuse de reverser ce qui y est ────────────────────────────
print("2. L'atelier refuse un versement déjà présent")
tmp = tempfile.mkdtemp(prefix="atelier-")
os.environ["DOCUMENTS_DIR"] = tmp
for m in [m for m in sys.modules if m.startswith("bureautique")]:
    del sys.modules[m]
atelier = importlib.import_module("bureautique.atelier")
atelier.DOSSIER = tmp
jeton = atelier.ouvrir({"titre": "Dossier CAMP", "format": "docx"}, "u1")
verifier("premier versement du devis accepté", atelier.ajouter(jeton, ENTETE_DEVIS, "u1") == 5)
variante = [
    {"bloc": "titre", "texte": "Devis N° DV0001451 — Aménagement de votre coin de paradis", "niveau": 2},
    {"bloc": "paragraphe", "texte": "Client : M. CAMP Nicolas, 20 avenue du Pinsan, 33370 ARTIGUÈS-PRÈS-BORDEAUX"},
    {"bloc": "paragraphe", "texte": "Suivi par : RADUSZYNSKI Julien (Tél.) — Date : 14/09/2026"},
    {"bloc": "paragraphe", "texte": "Aménagement de votre coin de paradis."},
]
leve = None
try:
    atelier.ajouter(jeton, variante, "u1")
except Exception as e:  # noqa: BLE001
    leve = e
verifier("le même devis reversé (ponctuation et accent différents) est REFUSÉ",
         leve is not None and type(leve).__name__ == "DejaPresent", repr(leve))
verifier("rien n'a été écrit par le versement refusé",
         (atelier.fiche(jeton, "u1") or {}).get("elements") == 5)
suite = [{"bloc": "titre", "texte": "Palette végétale", "niveau": 1},
         {"bloc": "paragraphe", "texte": "Washingtonia robusta, cordyline australis, gaura, romarin pointe du Raz."},
         {"bloc": "paragraphe", "texte": "Des sujets graphiques, adaptés au climat doux et aux embruns."}]
verifier("la section suivante est acceptée", atelier.ajouter(jeton, suite, "u1") == 3)
sections = [{"bloc": "titre", "texte": "Aménagement Paysager", "niveau": 1},
            {"bloc": "paragraphe", "texte": "Plan de masse annoté : terrasses, piscine, végétation et accès."}]
atelier.ajouter(jeton, sections, "u1")
sections2 = [{"bloc": "titre", "texte": "Aménagement Paysager", "niveau": 1},
             {"bloc": "paragraphe", "texte": "Visuels 3D : piscine et espace repas, entrée, parement pierre."}]
verifier("un titre de section qui revient (légitime) ne bloque pas la section suivante",
         atelier.ajouter(jeton, sections2, "u1") == 2)
verifier("le plan du document rend les titres dans l'ordre",
         atelier.plan(jeton)[:2] == ["Devis N° DV0001451", "Palette végétale"], atelier.plan(jeton))

# ── 3. Le skill dit ce qui est déjà là ──────────────────────────────────────
print("3. `ajouter_document` exécuté")
images = types.ModuleType("bureautique.images")


async def _preparer(jeton_, proprio, elements, entete, user):
    return elements, entete, []
images.preparer = _preparer
images.note_refus = lambda refus: ""
sys.modules["bureautique.images"] = images
for m in ("skills.bureau",):
    sys.modules.pop(m, None)
bureau = importlib.import_module("skills.bureau")
erreurs = importlib.import_module("skills.erreurs")
user = types.SimpleNamespace(id="u1", email="direction@exemple-paysage.fr", role="direction")
try:
    asyncio.run(bureau.ajouter_document({"document_id": jeton, "elements": variante}, user))
    verifier("le rejeu est un ÉCHEC du skill", False, "aucune exception")
except erreurs.SkillError as e:
    msg = str(e)
    verifier("le rejeu est un ÉCHEC du skill", True)
    verifier("l'échec dit que RIEN n'a été versé et cite ce qui y est",
             "RIEN N'A ÉTÉ VERSÉ" in msg and "Devis N° DV0001451" in msg, msg)
    verifier("l'échec donne la structure et la suite (terminer_document)",
             "Palette végétale" in msg and "terminer_document" in msg, msg)
ok = asyncio.run(bureau.ajouter_document(
    {"document_id": jeton, "elements": [{"bloc": "titre", "texte": "Matériaux"},
                                         {"bloc": "paragraphe", "texte": "Tasseaux, volige, grès cérame et pierre naturelle."}]}, user))
verifier("un versement neuf rend le plan du document",
         ok.get("ajoutes") == 2 and "Matériaux" in (ok.get("plan_du_document") or []), ok)

# ── 4. Le contrat du graphe ─────────────────────────────────────────────────
print("4. Le graphe se sert du journal")
src = (BACKEND / "agents/agent1.py").read_text(encoding="utf-8")
llm = src[src.index("async def llm_node"):src.index("def _consigne_plan") if "def _consigne_plan" in src else None]
verifier("llm_node place le journal des gestes dans le prompt",
         "journal_des_gestes(resultats_outils)" in src and "journal_gestes\n            + entete" in src)
f = src[src.index("async def forcer_action_node"):]
f = f[:f.index("\nasync def ", 10)] if "\nasync def " in f[10:] else f
verifier("le sélecteur d'actions voit le geste, pas seulement « réussie »", "resume_geste(r)" in f)
verifier("le temps imparti se compte en gestes faits, pas en `iteration` (qu'un versement ne fait pas avancer)",
         'if debut and len(resultats) >= 3 and (time.time() - float(debut)) > TOUR_DUREE_MAX_S' in src)
r = src[src.index("def route_apres_llm"):]
verifier("un fichier réellement ouvert ce tour n'est pas une livraison fantôme",
         "SKILLS_LECTURE_FICHIER" in r[:r.index("if fantome:")])

print()
if echecs:
    print(f"ÉCHEC : {len(echecs)} contrôle(s)")
    sys.exit(1)
print("Tous les contrôles passent.")
