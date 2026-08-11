"""
Reconnaître une ANNONCE sans acte.

Le modèle écrit « je crée le PDF », « je commence par compter », et n'émet aucun
bloc d'action. Le tour se terminait alors sur cette phrase : l'utilisateur lit
une promesse, redemande, et obtient la même promesse. Observé sur plusieurs
tours d'affilée, sur une demande pourtant simple.

On ne peut pas empêcher le modèle d'écrire cela. On peut refuser que ce soit la
FIN du tour : détecter l'annonce, et lui rendre la main une fois avec une
consigne explicite.

Module à part parce que ce motif se teste seul, sans monter tout le graphe — et
un motif de détection qui n'est jamais éprouvé sur de vraies phrases finit
toujours par attraper autre chose que ce qu'on croit.
"""
from __future__ import annotations

import re

# Ce qui compte : le FUTUR PROCHE à la première personne. Une phrase au passé
# (« j'ai listé ») décrit un acte accompli et ne doit pas déclencher de relance,
# sinon on rejouerait indéfiniment un travail déjà fait.
ANNONCE_SANS_ACTE = re.compile(
    r"\b(?:"
    # Futur proche, explicite.
    r"je (?:vais|commence|m['’]y mets|me mets|procède|prépare|entame)"
    # Présent de narration : « je crée le PDF ». Sans bloc d'action, c'est une
    # promesse — s'il l'avait fait, il en donnerait le RÉSULTAT, au passé
    # (« j'ai listé », « il y a 18 dossiers »). L'adverbe n'est pas exigé : la
    # phrase de production la plus courante n'en portait aucun.
    r"|je (?:crée|créé|liste|cherche|lis|rédige|génère|compte|regarde|récupère)\b"
    r"|c['’]est parti"
    r"|je le fais"
    r"|maintenant[^.!?]{0,25}\bje\b"
    r")",
    re.IGNORECASE,
)


def est_une_annonce(texte: str) -> bool:
    """Le texte promet-il une action au lieu de la faire ?"""
    return bool(ANNONCE_SANS_ACTE.search(texte or ""))
