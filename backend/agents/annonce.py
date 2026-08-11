"""
Reconnaître un tour qui PROMET au lieu de faire.

Le modèle écrit « je crée le PDF », « j'y ajoute le nombre de dossiers, puis je
finalise et dépose le fichier », et n'émet aucun bloc d'action. Le tour se
terminait alors sur cette phrase : l'utilisateur lit une promesse, redemande, et
obtient la même promesse.

DEUX SIGNAUX, ET LE SECOND EST LE SOLIDE.

  1. La FORMULATION — une liste de tournures. Elle rend service, mais elle est
     perdante par nature : elle énumère des verbes, et il en manque toujours un.
     « je crée » était couvert, « j'y ajoute » ne l'était pas, et le tour s'est
     arrêté sur la promesse. Élargir la liste repousse l'échec sans le supprimer.

  2. LE TRAVAIL RESTÉ OUVERT — ce que les actions ont réellement fait. Un
     document ouvert et jamais fermé est un travail inachevé, quels que soient
     les mots employés pour en parler. Ce signal ne dépend d'aucun vocabulaire :
     il se lit dans les résultats, pas dans la prose.

Module à part parce que ces motifs se testent seuls, sans monter tout le graphe
— et un détecteur qui n'est jamais éprouvé sur de vraies phrases finit toujours
par attraper autre chose que ce qu'on croit.
"""
from __future__ import annotations

import re

# Ce qui compte : le FUTUR PROCHE à la première personne. Une phrase au passé
# (« j'ai listé ») décrit un acte accompli et ne doit pas déclencher de reprise,
# sinon on rejouerait indéfiniment un travail déjà fait.
ANNONCE_SANS_ACTE = re.compile(
    r"\b(?:"
    # Futur proche, explicite.
    r"je (?:vais|commence|m['’]y mets|me mets|procède|prépare|entame)"
    # Présent de narration : « je crée le PDF ». Sans bloc d'action, c'est une
    # promesse — s'il l'avait fait, il en donnerait le RÉSULTAT, au passé
    # (« j'ai listé », « il y a 18 dossiers »). L'adverbe n'est pas exigé : la
    # phrase de production la plus courante n'en portait aucun.
    r"|je (?:crée|créé|liste|cherche|lis|rédige|génère|compte|regarde|récupère"
    r"|finalise|termine|dépose|ajoute|complète|remplis|enregistre|envoie|ouvre)\b"
    # Élision, avec ou sans pronom intercalé : « j'ajoute », « j'y ajoute ».
    # C'est cette forme qui manquait, sur la phrase même qui a fait échouer le
    # tour : « J'y ajoute le nombre de dossiers (18)... puis je finalise ».
    r"|j['’](?:y |l['’])?(?:ajoute|envoie|ouvre|enregistre|extrais|inscris)"
    r"|c['’]est parti"
    r"|je le fais"
    r"|maintenant[^.!?]{0,25}\bje\b"
    r")",
    re.IGNORECASE,
)

# CE QUI RESTE OUVERT tant qu'une autre action ne l'a pas fermé.
#
# Un document s'ouvre, se remplit, puis se ferme : sans la fermeture il n'existe
# aucun fichier, donc rien à télécharger ni à déposer. Un tour qui s'arrête
# entre les deux n'a rien produit, même s'il l'annonce.
#
# On n'y met QUE des enchaînements réellement obligatoires. `preparer_visuel`
# n'appelle pas `generer_visuel` : la séparation est voulue, on règle le brief
# gratuitement avant de payer le tirage. Le forcer reviendrait à facturer une
# génération que personne n'a demandée.
CLOTURES = {
    "creer_document": "terminer_document",
    "ajouter_document": "terminer_document",
}


def est_une_annonce(texte: str) -> bool:
    """Le texte promet-il une action au lieu de la faire ?"""
    return bool(ANNONCE_SANS_ACTE.search(texte or ""))


def cloture_attendue(resultats) -> str | None:
    """L'action de fermeture qui manque, si un travail est resté ouvert.

    Rend `None` quand il n'y a rien en suspens. Les actions en ÉCHEC sont
    ignorées : un `creer_document` qui a échoué n'a rien ouvert, et attendre sa
    fermeture ferait tourner le tour sur un document qui n'existe pas.
    """
    attendue = None
    for r in resultats or []:
        if not isinstance(r, dict) or not r.get("ok"):
            continue
        skill = r.get("skill") or ""
        if skill in CLOTURES:
            attendue = CLOTURES[skill]
        elif skill == attendue:
            attendue = None
    return attendue
