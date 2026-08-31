"""
LE NER FRANÇAIS NE DOIT PAS DÉCOUPER DU TEXTE ANGLAIS.

Le modèle spaCy est français ; le socle, lui, brasse de l'anglais en permanence
— briefs de visuels rédigés en anglais par conception, pages web rapportées par
l'agent navigateur, mails et documents fournisseurs. Sur un brief réel, six
jetons sur sept masquaient du vocabulaire ordinaire, et deux d'entre eux
avalaient une clause entière : le modèle relisait un texte amputé de sa scène et
de sa plantation, sans qu'aucune donnée personnelle ne soit en jeu.

Ce banc fige le comportement attendu APRÈS les garde-fous de `_is_non_pii_span` :
un span sans mot capitalisé, ou contenant un deux-points, n'est pas une entité.

    docker compose exec backend sh -c "PYTHONPATH=. python scripts/test_anonymiseur.py"

Sortie : une ligne par cas, et un code de retour non nul si un seul cas tombe.
"""
from __future__ import annotations

import sys

from config import settings
settings.anonymisation = "active"   # le défaut est « désactivée » depuis le 31/08 : ce banc teste le MASQUAGE
from security.anonymizer import anonymizer

# Le brief anglais qui a servi de mesure. Une seule donnée réellement
# identifiante s'y trouve : le lieu.
BRIEF = (
    "Award-winning professional landscape architecture photograph, ultra realistic. "
    "SCENE: modern house on the Bassin d'Arcachon. GARDEN ELEMENTS: modern contemporary "
    "house, sand, pine trees, waterfront. PLANTING: ornamental grasses, lavender shrubs "
    "and two feature olive trees. MATERIALS: natural wood, local stone. STYLE: modern, "
    "contemporary garden design, coherent and lived-in, believable for a real French "
    "property. ATMOSPHERE: luxurious, serene, elegant, gentle atmospheric depth. "
    "SEASON: summer, temperate French climate, botanically coherent species only. "
    "CAMERA: wide angle view, full-frame camera, 28mm lens at f/8, eye-level unless "
    "stated, sharp focus front to back, golden hour balance, high dynamic range, "
    "subtle film-like color grading, photorealistic textures on every material, "
    "physically accurate reflections on water and glass, believable human scale "
    "throughout. Magazine quality, no text, no watermark, no logo, no people in the "
    "foreground, natural colors, no fantasy elements"
)

echecs: list[str] = []


def verifier(intitule: str, condition: bool, detail: str = "") -> None:
    print("  %s  %s%s" % ("OK  " if condition else "ECHEC", intitule,
                          "" if condition else "  -> " + detail))
    if not condition:
        echecs.append(intitule)


print("spaCy actif :", anonymizer.spacy_available)
if not anonymizer.spacy_available:
    print("\nspaCy indisponible : le NER ne tourne pas, ce banc ne prouve rien.")
    print("Installer fr_core_news_md avant de conclure quoi que ce soit.")
    sys.exit(2)


# ---------------------------------------------------------------------------
print("\n1. Le brief anglais ne perd que sa vraie donnée")
# ---------------------------------------------------------------------------
masque, carte = anonymizer.anonymize(BRIEF, {})
# Avant les garde-fous : 7 jetons, dont 6 faux positifs. Après : 2.
verifier("deux jetons au plus", len(carte) <= 2,
         "%d jetons : %s" % (len(carte), carte))
verifier("le lieu est masqué",
         any("Arcachon" in str(v) for v in carte.values()),
         "valeurs = %s" % list(carte.values()))
for expression in ("local stone", "no watermark",
                   "lavender shrubs", "color grading",
                   "GARDEN ELEMENTS", "modern contemporary house"):
    verifier("« %s » reste en clair" % expression, expression in masque)

# LIMITE CONNUE, VOLONTAIREMENT NON CORRIGÉE.
#
# « MATERIALS » — mot anglais isolé, tout en capitales — passe encore pour une
# entité : il porte des majuscules, donc le garde-fou ne s'applique pas. L'en
# exempter demanderait une règle « mot unique tout en capitales = non-PII », et
# cette règle laisserait fuir « DUPONT », « SARL MARTIN », « EDF » — des raisons
# sociales et des patronymes que l'on écrit couramment ainsi dans un devis.
#
# Le dégât résiduel est une étiquette de section masquée dans un brief : le
# modèle lit « [LOC_2]: natural wood, local stone » au lieu de
# « MATERIALS: natural wood, local stone ». Le CONTENU est intact. Sans
# commune mesure avec les clauses entières qui disparaissaient avant.
verifier("limite connue : un mot isolé en capitales reste masqué",
         "MATERIALS" not in masque,
         "si ce cas passe OK, c'est que le comportement a changé — relire la note")


# ---------------------------------------------------------------------------
print("\n2. Les vraies données restent masquées")
# ---------------------------------------------------------------------------
for texte, attendu in (
    ("Le chantier de Jean Dupont à Bordeaux avance bien.", ("Jean Dupont", "Bordeaux")),
    ("Rendez-vous avec Mme Martin sur le Bassin d'Arcachon.", ("Martin", "Arcachon")),
):
    masque_fr, carte_fr = anonymizer.anonymize(texte, {})
    for valeur in attendu:
        verifier("« %s » est masqué" % valeur, valeur not in masque_fr,
                 "masqué = %s" % masque_fr)


# ---------------------------------------------------------------------------
print("\n3. Les regex métier ne sont PAS concernées par les garde-fous")
# ---------------------------------------------------------------------------
# Elles s'exécutent hors du chemin spaCy : un identifiant en minuscules doit
# rester masqué, c'est là qu'est le vrai risque de ré-identification.
for intitule, texte, fragment in (
    ("e-mail",    "ecrire a jean.dupont@exemple.fr stp",        "jean.dupont@exemple.fr"),
    ("telephone", "rappelle au 06 12 34 56 78 demain",          "06 12 34 56 78"),
    ("IBAN",      "virement sur FR7630006000011234567890189",   "FR7630006000011234567890189"),
    ("SIRET",     "siret 80295478500018 pour la facture",       "80295478500018"),
):
    masque_id, _ = anonymizer.anonymize(texte, {})
    verifier("%s masqué même en minuscules" % intitule, fragment not in masque_id,
             "masqué = %s" % masque_id)


# ---------------------------------------------------------------------------
print("\n4. Contrepartie ASSUMÉE du garde-fou « aucun mot capitalisé »")
# ---------------------------------------------------------------------------
# Ce cas est un CHOIX, pas un oubli : on le fige pour qu'un changement futur du
# compromis soit une décision visible, jamais une dérive silencieuse.
masque_min, _ = anonymizer.anonymize("contactez jean dupont pour la suite", {})
verifier("un patronyme tout en minuscules échappe au NER",
         "jean dupont" in masque_min,
         "masqué = %s" % masque_min)


# ---------------------------------------------------------------------------
print("\n5. L'aller-retour reste fidèle")
# ---------------------------------------------------------------------------
masque_ar, carte_ar = anonymizer.anonymize(
    "Devis pour Jean Dupont, chantier du Bassin d'Arcachon.", {})
verifier("la réhydratation rend le texte d'origine",
         anonymizer.rehydrate(masque_ar, carte_ar)
         == "Devis pour Jean Dupont, chantier du Bassin d'Arcachon.",
         anonymizer.rehydrate(masque_ar, carte_ar))
verifier("aucune entrée jeton -> jeton dans la carte",
         not [k for k, v in carte_ar.items()
              if isinstance(v, str) and v.startswith("[") and v.endswith("]")],
         "carte = %s" % carte_ar)


# ---------------------------------------------------------------------------
print()
if echecs:
    print("%d CAS EN ECHEC : %s" % (len(echecs), " | ".join(echecs)))
    sys.exit(1)
print("Tous les cas passent.")
