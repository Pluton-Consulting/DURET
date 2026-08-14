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

# LA CASCADE PRODUIT PARFOIS DU FRANÇAIS SANS ACCENT. « Je cree le document »
# n'était pas reconnu alors que « Je crée le document » l'était : le même
# modèle, selon le fournisseur qui répondait, passait ou non le contrôle.
#
# Les motifs ci-dessous sont donc écrits SANS ACCENT, et le texte est dépouillé
# avant comparaison. Les deux formes tombent ainsi sur la même règle — écrire
# les deux variantes à la main aurait doublé chaque liste, pour n'en oublier une
# qu'au premier ajout.
_ACCENTS = str.maketrans("àâäéèêëîïôöùûüçœ", "aaaeeeeiioouuucœ")


def _sans_accent(texte: str) -> str:
    return texte.translate(_ACCENTS)


# UN PRONOM PEUT S'INTERCALER entre « je » et le verbe. « Je vous prépare ça »
# et « Je vous liste ça dans un tableau » sont des promesses aussi nettes que
# « je prépare » — elles passaient toutes les deux, parce que chaque motif
# collait le verbe à « je ». C'était une faille de FORME, pas de vocabulaire :
# elle laissait passer n'importe quel verbe dès qu'un pronom s'y glissait.
_PRON = r"(?:vous |me |te |nous |y |le |la |les |leur |lui |en |m['’]|l['’])?"

# Futur proche explicite : aucune ambiguïté, c'est une promesse.
#
# La règle « maintenant ... je » a été RETIRÉE : elle attrapait n'importe quel
# « je » à moins de 25 caractères de « maintenant », quel que soit le verbe —
# « Maintenant que j'ai les chiffres, je peux vous répondre : 42 000 € » était
# donc traité comme une promesse, alors que la phrase livre le résultat. Elle
# ne couvrait rien d'unique : « Maintenant, je crée le document » tombe déjà
# sous le verbe de production.
_FUTUR = (rf"je {_PRON}(?:vais|commence|m['’]y mets|me mets|procede|prepare"
          rf"|entame|m['’]occupe)"
          r"|c['’]est parti"
          r"|je le fais")

# VERBES DE PRODUCTION au présent. « je crée le PDF » est une promesse : s'il
# l'avait fait, il en donnerait le RÉSULTAT — « le document est prêt », « j'ai
# créé ». On ne fabrique pas quelque chose « en direct » dans une phrase.
#
# Les verbes de RÉCUPÉRATION et de TRANSFERT ont été ajoutés après mesure sur
# le corpus : « je récupère », « je télécharge », « je lance la recherche »,
# « je consulte la boîte mail » sont exactement les tournures relevées en
# production, et aucune n'était reconnue.
_PRODUCTION = (rf"je {_PRON}(?:cree|redige|genere|produis|finalise|termine"
               r"|depose|ajoute|complete|remplis|enregistre|envoie|ouvre"
               r"|recupere|telecharge|sauvegarde|lance|consulte|calcule"
               r"|liste|poursuis|transmets|extrais|inscris"
               # Les verbes de REPRISE, relevés en production le 14/08 : « Je
               # continue à verser le contenu dans le document déjà ouvert » a
               # terminé le tour tel quel — « je poursuis » était couvert,
               # « je continue » non. C'est exactement la faille de liste que
               # le module documente ; on la rebouche sans se raconter qu'elle
               # ne se rouvrira pas ailleurs.
               r"|continue|reprends|verse|insere)\b"
               # Élision, avec ou sans pronom intercalé : « j'y ajoute ».
               r"|j['’](?:y |l['’])?(?:ajoute|envoie|ouvre|enregistre|extrais"
               r"|inscris|insere)")

# VERBES DE LECTURE au présent : « je compte 18 dossiers », « d'après ce que je
# lis dans le CCTP ». Ce sont les tournures NORMALES d'un résultat d'observation
# — les traiter comme des promesses détruisait de vraies réponses (mesuré : 4
# sur 4). Ils ne comptent donc QUE derrière un marqueur de futur, déjà couvert
# par `_FUTUR` (« je vais compter », « je commence par lire »).
ANNONCE_SANS_ACTE = re.compile(rf"\b(?:{_FUTUR}|{_PRODUCTION})", re.IGNORECASE)

# CE QUI N'EST PAS UNE PROMESSE, quoi qu'en dise le verbe. Deux familles :
#
# LA QUESTION. « Voulez-vous que je crée le document ? » demande un accord ;
# la traiter comme une annonce faisait produire l'action sans jamais montrer la
# question — l'utilisateur voyait le document apparaître à la place de la
# question qu'on lui posait.
#
# LA DEMANDE D'INFORMATION. « Je vais avoir besoin du numéro de chantier »
# porte « je vais », mais n'annonce aucun acte : elle attend une réponse. Sans
# cette exclusion, la phrase était remplacée par « je n'ai pas réussi à
# exécuter l'action » — et la question posée à l'utilisateur disparaissait.
#
# LA PHRASE QUI LIVRE. « Je liste ci-dessous les cinq dernières factures :
# F-2031, F-2032 » emploie le même verbe que « Je vous liste ça dans un
# tableau », et les deux ne demandent pas le même traitement : la première
# porte déjà son résultat. Un marqueur de livraison — ci-dessous, ci-joint,
# voici — dit que le contenu est LÀ, donc qu'il n'y a rien à forcer.
_PAS_UNE_PROMESSE = re.compile(
    r"\?"
    r"|\b(?:voulez-vous|souhaitez-vous|dois-je|puis-je|faut-il|preferez-vous"
    r"|est-ce que|pouvez-vous|pourriez-vous|lequel|laquelle|lesquels)\b"
    r"|j['’]ai besoin|je vais avoir besoin|il me faut|il me manque"
    r"|je vais devoir|precisez|indiquez-moi|de quel"
    r"|\bci-dessous\b|\bci-joint|\bvoici\b|\bvoila\b",
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
    """Le texte promet-il une action au lieu de la faire ?

    Deux conséquences pèsent sur cette réponse, et toutes deux sont lourdes :
    un « oui » fait FABRIQUER une action par le nœud de forçage, et fait
    REMPLACER la réponse à l'écran si rien n'aboutit. Un faux positif ne coûte
    donc pas un appel de trop — il exécute ce que personne n'a demandé, ou
    détruit une réponse juste.

    D'où le refus catégorique sur une question : demander l'autorisation d'agir
    n'est pas agir, et la réponse attendue est celle de l'utilisateur.
    """
    # Un appelant peut passer autre chose qu'une chaîne (état mal formé, valeur
    # d'un modèle). Cette fonction décide d'un routage : elle ne doit jamais
    # être ce qui fait tomber un tour.
    if not isinstance(texte, str):
        texte = str(texte or "")
    nu = _sans_accent(texte)
    if _PAS_UNE_PROMESSE.search(nu):
        return False
    return bool(ANNONCE_SANS_ACTE.search(nu))


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
