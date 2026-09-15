"""
Banc « UN LIVRABLE DURABLE, UNE SOURCE RETROUVABLE » — audit du 15/09, D-04 et D-07.

CE QUI ÉTAIT FAUX :
  · l'atelier écrivait la fiche JSON et le contenu JSONL séparément, sans
    verrou : deux versements simultanés ou une coupure entre les deux
    laissaient un compteur qui ment (« 12 éléments » pour 8 écrits) ;
  · la purge balayait les FICHIERS à l'ancienneté : elle pouvait emporter les
    images d'un rendu encore cité, ou le contenu d'un document ouvert ;
  · au cinquième document ouvert, le quota fermait « le plus ancien » — parfois
    le seul qui portait du travail ;
  · une retouche créait un document SANS PARENT : plus moyen de dire quelle
    révision un brouillon de mail avait jointe ;
  · les références des messages et des pièces jointes vivaient dans la mémoire
    du processus : après un redémarrage, un accord en attente ne retrouvait
    plus sa pièce.

CE BANC PROUVE, avec un vrai dossier temporaire et des modules EXÉCUTÉS :
  1. écriture atomique, verrou, compteur réconcilié sur le contenu réel ;
  2. lignée : document_id stable, révision, parent, fil, manifeste ;
  3. purge par groupe : un brouillon rempli et les images d'un rendu restent ;
  4. quota : on refuse en nommant les documents, on ne détruit pas ;
  5. le registre des ressources survit à un « redémarrage » (module rechargé).

Usage : python backend/scripts/test_versions_documents.py [backend]
"""
import importlib
import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import threading
import time
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
sys.path.insert(0, str(BACKEND))
os.environ["DOCUMENTS_DIR"] = tempfile.mkdtemp(prefix="banc-versions-")
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {str(detail)[:300]}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def charger(nom, chemin):
    spec = importlib.util.spec_from_file_location(nom, BACKEND / chemin)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nom] = mod
    if "." in nom:
        parent, feuille = nom.rsplit(".", 1)
        if parent not in sys.modules:
            paquet = types.ModuleType(parent)
            paquet.__path__ = []
            sys.modules[parent] = paquet
        setattr(sys.modules[parent], feuille, mod)
    spec.loader.exec_module(mod)
    return mod


print(f"\n═══ LIVRABLES DURABLES, SOURCES RETROUVABLES — {BACKEND.parent}\n")

atelier = charger("bureautique.atelier", "bureautique/atelier.py")
# Le vocabulaire des blocs et le rendu : seuls comptent ici le versement et la
# fiche, pas la mise en page (elle a son banc, `test_charte_document`).
sys.modules["bureautique.modele"] = types.SimpleNamespace(
    normaliser_element=lambda e: e if isinstance(e, dict) else None, MAX_ELEMENTS=500)


def _rendre(entete, elements_, sortie):
    with open(sortie, "w", encoding="utf-8") as f:
        f.write("RENDU " + json.dumps(entete, ensure_ascii=False) + "\n")
        for e in elements_:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


sys.modules["bureautique.rendu"] = types.SimpleNamespace(rendre=_rendre)
MOI = "compte-a"

print("1. Le compteur ne ment plus : verrou, écriture atomique, réconciliation")
jeton = atelier.ouvrir({"titre": "Devis Martin", "format": "docx"}, MOI, fil="fil-1")
atelier.ajouter(jeton, [{"bloc": "titre", "texte": "Devis"}], MOI)


def _verser(n):
    atelier.ajouter(jeton, [{"bloc": "paragraphe", "texte": f"ligne {n}"}], MOI, refuser_repetition=False)


# Un fil qui lève ne doit pas passer inaperçu : sinon la course se cacherait.
INCIDENTS = []
threading.excepthook = lambda args: INCIDENTS.append(args.exc_value)
fils = [threading.Thread(target=_verser, args=(i,)) for i in range(12)]
for t in fils:
    t.start()
for t in fils:
    t.join()
verifier("aucun versement simultané ne lève (le fichier temporaire est propre à son écrivain)",
         not INCIDENTS, INCIDENTS[:2])
fiche = atelier.fiche(jeton, MOI)
verifier("douze versements simultanés : le compteur vaut ce que le contenu porte",
         fiche["elements"] == 13 == sum(1 for _ in atelier.elements(jeton)), fiche["elements"])
# Une coupure entre le contenu et la fiche : le compteur reste en retard, et se rattrape.
fiche["elements"] = 3
atelier._ecrire_fiche(jeton, fiche)
verifier("un compteur laissé en retard par une coupure est réconcilié à la lecture",
         atelier.fiche(jeton, MOI)["elements"] == 13)
verifier("la fiche s'écrit atomiquement (aucun fichier temporaire ne traîne)",
         not [n for n in os.listdir(atelier.DOSSIER) if n.endswith(".tmp")])

print("2. La lignée : document, révision, parent, fil, manifeste")
verifier("un document ouvert porte son identifiant stable, sa révision et son fil",
         fiche["document_id"] == jeton and fiche["revision"] == jeton
         and fiche["parent_revision"] is None and fiche["fil"] == "fil-1")
finie = atelier.terminer(jeton, MOI)
verifier("un rendu terminé porte son EMPREINTE (il ne changera plus sous cet identifiant)",
         len(finie.get("empreinte") or "") == 32 and finie["manifeste"]["empreinte"] == finie["empreinte"])
verifier("son manifeste dit d'où il vient et ce qu'il contient",
         finie["manifeste"]["fil"] == "fil-1" and finie["manifeste"]["blocs"] == 13
         and finie["manifeste"]["format"] == "docx" and finie["manifeste"]["titre"] == "Devis Martin")
suivante = atelier.nouvelle_revision(jeton, MOI)
atelier.ajouter(suivante, [{"bloc": "paragraphe", "texte": "prix corrigé"}], MOI)
atelier.terminer(suivante, MOI)
lignee = atelier.revisions(MOI, jeton)
verifier("une retouche est une RÉVISION du même document, pas un document sans parent",
         [r["revision"] for r in lignee] == [jeton, suivante]
         and lignee[1]["parent_revision"] == jeton, lignee)
verifier("l'ancienne révision reste téléchargeable (rien n'est supprimé)",
         atelier.chemin_fichier(jeton, MOI) and atelier.chemin_fichier(suivante, MOI))
dernier = atelier.dernier_livrable_du_fil(MOI, "fil-1")
verifier("le dernier livrable DU FIL est la dernière révision, pas le dernier fichier de la personne",
         dernier and dernier["document_id"] == suivante, dernier)
autre_fil = atelier.ouvrir({"titre": "Rapport", "format": "docx"}, MOI, fil="fil-2")
atelier.ajouter(autre_fil, [{"bloc": "titre", "texte": "Rapport"}], MOI)
atelier.ranger_image(autre_fil, MOI, b"\x89PNG une image du rapport", "png")
atelier.terminer(autre_fil, MOI)
verifier("un document d'une AUTRE conversation n'est jamais désigné",
         atelier.dernier_livrable_du_fil(MOI, "fil-1")["document_id"] == suivante
         and atelier.dernier_livrable_du_fil(MOI, "fil-2")["document_id"] == autre_fil)
verifier("sans fil connu, on ne désigne rien plutôt que n'importe quoi",
         atelier.dernier_livrable_du_fil(MOI, None) is None)

print("3. La purge : par groupe, jamais un brouillon rempli ni les images d'un rendu")
brouillon = atelier.ouvrir({"titre": "Brouillon en cours", "format": "docx"}, MOI, fil="fil-3")
atelier.ajouter(brouillon, [{"bloc": "paragraphe", "texte": "du travail versé"}], MOI)
vide = atelier.ouvrir({"titre": "Ouvert par erreur", "format": "docx"}, MOI)
vieux = time.time() - 3 * 24 * 3600
for j in (brouillon, vide):
    f = atelier._lire_fiche(j)
    f["ouvert"] = vieux
    atelier._ecrire_fiche(j, f)
f = atelier._lire_fiche(autre_fil)
f["termine"] = vieux
atelier._ecrire_fiche(f["document_id"], f)
atelier.purger()
verifier("un brouillon REMPLI de trois jours survit (sept jours avant de partir)",
         atelier.fiche(brouillon, MOI) is not None)
verifier("un document ouvert et VIDE de trois jours part", atelier.fiche(vide, MOI) is None)
verifier("un rendu périmé part ENTIER : fiche, contenu, rendu et images ensemble",
         atelier.fiche(autre_fil, MOI) is None
         and not [n for n in os.listdir(atelier.DOSSIER) if n.startswith(autre_fil)])
verifier("le document encore vivant garde tous ses fichiers",
         {n.split(".")[-1] for n in os.listdir(atelier.DOSSIER) if n.startswith(suivante)} >= {"json", "jsonl"})

print("4. Le quota ne détruit plus le travail")
ouverts_ = [atelier.ouvrir({"titre": f"Doc {i}", "format": "docx"}, MOI) for i in range(3)]
for j in ouverts_:
    atelier.ajouter(j, [{"bloc": "paragraphe", "texte": f"contenu {j[:4]}"}], MOI)
dernier_ouvert = atelier.ouvrir({"titre": "Encore un", "format": "docx"}, MOI)
verifier("cinq documents ouverts dont un vide : c'est le VIDE qui est fermé",
         dernier_ouvert and atelier.fiche(brouillon, MOI) is not None)
atelier.ajouter(dernier_ouvert, [{"bloc": "paragraphe", "texte": "du travail ici aussi"}], MOI)
try:
    atelier.ouvrir({"titre": "Un de trop", "format": "docx"}, MOI)
    verifier("quand tous portent du travail, on REFUSE au lieu d'effacer", False)
except atelier.TropDeDocuments as e:
    verifier("quand tous portent du travail, on REFUSE au lieu d'effacer, en les nommant",
             "Brouillon en cours" in str(e) and "terminer_document" in str(e), str(e)[:200])

print("5. Une source se retrouve après un redémarrage")
registre = charger("ressources.registre", "ressources/registre.py")
registre.noter("piece", "abc123", {"boite": "accueil@exemple-sols.fr", "message": "AAMk…",
                                   "nom": "devis.pdf", "octets": b"jamais"})
registre.noter("message", "def456", {"boite": "accueil@exemple-sols.fr", "identifiant": "AAMk…"})
verifier("le registre ne retient JAMAIS le contenu, seulement de quoi rouvrir",
         "octets" not in (registre.lire("piece", "abc123") or {}))
# « Redémarrage » : on relit le fichier du volume, la mémoire vidée.
registre.recharger()
verifier("après un redémarrage, la pièce et le message sont toujours là",
         (registre.lire("piece", "abc123") or {}).get("nom") == "devis.pdf"
         and (registre.lire("message", "def456") or {}).get("identifiant") == "AAMk…")
verifier("le fichier du registre est écrit atomiquement",
         not [n for n in os.listdir(os.environ["DOCUMENTS_DIR"]) if n.startswith("ressources.json.")])
lecture_src = (BACKEND / "mail" / "lecture.py").read_text(encoding="utf-8")
verifier("la messagerie écrit ses références dans le registre, et les y relit",
         'registre.noter("message"' in lecture_src and 'registre.noter("piece"' in lecture_src
         and 'registre.lire("piece", ref)' in lecture_src and 'registre.lire("message", ref)' in lecture_src)
verifier("le cache mémoire reste devant (il accélère, il ne décide plus seul)",
         "_REFS[ref] = (str(fiche[\"boite\"])" in lecture_src and "_PIECES[ref] = info" in lecture_src)

print("6. Le document de référence du travail (D-01)")
trames_src = (BACKEND / "skills" / "trames.py").read_text(encoding="utf-8")
# Les fonctions pures de mémoire du travail, exécutées contre le vrai registre.
import ast as _ast

arbre_trames = _ast.parse(trames_src)
voulus = {"TYPE_TRAVAIL", "_cle_travail", "_registre", "travail_en_cours", "noter_travail"}
morceaux = [n for n in arbre_trames.body
            if (isinstance(n, _ast.FunctionDef) and n.name in voulus)
            or (isinstance(n, _ast.Assign) and any(getattr(t, "id", "") in voulus for t in n.targets))]
espace = {"__name__": "trames_double"}
exec(compile(_ast.Module(body=morceaux, type_ignores=[]), "trames", "exec"), espace)
QUI = types.SimpleNamespace(id="compte-a")
espace["noter_travail"](QUI, "fil-9", source_ref="/home/Drive/AFF/devis type.docx",
                        nom="devis type.docx", type="docx", empreinte="abc",
                        raison="référence donnée dans le tour")
verifier("la référence choisie est retenue POUR CE TRAVAIL (personne + conversation)",
         espace["travail_en_cours"](QUI, "fil-9")["nom"] == "devis type.docx"
         and espace["travail_en_cours"](QUI, "fil-8") == {})
registre.recharger()
verifier("elle survit à un redémarrage : la conversation reprend où elle en était",
         espace["travail_en_cours"](QUI, "fil-9")["source_ref"].endswith("devis type.docx"))
verifier("le geste reprend la référence du travail quand le tour n'en donne pas",
         "if not reference and travail.get(\"source_ref\")" in trames_src
         and "repris_du_travail = True" in trames_src)
verifier("des remplacements déjà donnés ne sont pas redemandés",
         "travail.get(\"remplacements\")" in trames_src and "remplacements_repris" in trames_src
         and "Les changements demandés plus tôt" in trames_src)
verifier("un original qui a changé depuis le choix est SIGNALÉ, jamais substitué en silence",
         "a changé depuis le choix initial" in trames_src)
verifier("la raison du choix est conservée avec la référence",
         'raison=("référence donnée dans le tour"' in trames_src)
agent1_src = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("le serveur donne la conversation aux gestes de documents et de trames",
         all(g in agent1_src.split("SKILLS_QUI_CONNAISSENT_LE_FIL")[1].split("})")[0]
             for g in ("creer_document", "produire_document", "reproduire_document", "utiliser_trame")))

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s)")
    sys.exit(1)
print("✓ 0 échec")
