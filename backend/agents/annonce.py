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
          r"|je le fais"
          # « Laissez-moi interroger les factures » (31/08, « le CA mois par mois
          # de 2025 ») : une annonce à l'impératif, sans « je » — la liste ne la
          # voyait pas, le tour s'est terminé sur la promesse.
          r"|(?:laissez|laisse|permettez|permets)[- ]moi")

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
               r"|continue|reprends|verse|insere"
               # Relevés le 22/08, chacun sur un tour qui s'est arrêté là :
               # « Je recherche les informations sur X. », « Je relance la
               # consultation », « Je retente », « Je vais lire les mails »,
               # « Je vais modifier le visuel ». La liste reste perdante par
               # nature (le docstring le dit) ; chaque verbe manquant est
               # un tour perdu, on les ajoute au fur et à mesure.
               r"|recherche|cherche|relance|retente|reessaie|modifie|retouche"
               r"|change|applique|regarde|verifie|analyse|interroge|lis"
               r"|examine|refais|rappelle|mets a jour|consulte a nouveau)\b"
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

# UNE CLÔTURE PEUT ÊTRE SATISFAITE AUTREMENT QUE PAR L'ACTION QU'ON NOMME.
#
# `nas_deposer_document` finalise ET dépose en UN geste : c'est exactement
# l'outil de « crée un docx dans /Drive ». Il ne figurait nulle part ici, avec
# deux conséquences mesurées :
#
#   1. pendant tout le remplissage, le rappel de clôture répétait « il reste
#      `terminer_document` à exécuter » — le modèle était donc poussé vers la
#      fermeture SEULE, et une fois fermée, plus rien n'attendait : le tour se
#      concluait, document jamais déposé. « Il crée, parfois il remplit, mais
#      jamais il ne dépose », mot pour mot ;
#   2. quand le modèle utilisait quand même le geste composé, la clôture
#      restait insatisfaite — on lui réclamait une fermeture déjà faite.
#
# Le dépôt reste une action à effet EXTERNE : il suspend le tour pour la
# validation humaine. Ce n'est pas un contournement de ce garde-fou, c'est la
# reconnaissance qu'il ferme le document au passage.
SATISFAIT_PAR = {
    "terminer_document": {"terminer_document", "nas_deposer_document"},
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


def promesse_sans_suite(texte: str) -> bool:
    """Le texte INTRODUIT quelque chose qui n'est jamais venu.

    Signal volontairement INDÉPENDANT DU VOCABULAIRE, contrairement à
    `est_une_annonce` qui repose sur une liste de verbes français. Une réponse
    finale ne se termine jamais par deux-points : ce signe annonce une suite, et
    s'il est le dernier caractère, la suite manque.

    Relevé en production : « Je parcours le drive pour trouver des devis. Voici
    ce que je lance : », affiché comme réponse finale après une action pourtant
    réussie. Aucun verbe de la liste n'y figurait.

    La borne de longueur évite le faux positif du texte long qui se termine par
    une énumération vide : au-delà de quelques centaines de caractères, le
    modèle a livré quelque chose, même imparfaitement.
    """
    if not isinstance(texte, str):
        return False
    t = texte.strip()
    if not t or len(t) > 400:
        return False
    return t.endswith(":") or t.endswith(" :") or t.endswith("…") or t.endswith("...")


# ── LA QUESTION QUI DÉMENT LE TRAVAIL FAIT ──────────────────────────────────
# Relevé en production le 30/08 : « fais-moi un excel des fournisseurs avec mon
# mail ». Le skill tourne, l'Excel sort avec la bonne adresse — et la rédaction
# finale RECOPIE une vieille réponse de l'historique : « j'ai besoin de votre
# adresse email exacte… Une fois communiqué, je créerai un fichier Excel. » Le
# fichier s'affichait (filet des livrables), mais SOUS un texte qui promettait
# de le créer plus tard et réclamait une information déjà utilisée.
#
# Une question posée à l'utilisateur est légitime en général — `est_une_annonce`
# refuse d'y voir une promesse, à juste titre. Mais une question qui réclame un
# PRÉALABLE (« j'ai besoin de », « quel est votre », « une fois communiqué »)
# ne l'est plus quand le tour vient de LIVRER ce travail : elle dément un fait.
# Ce prédicat ne juge donc JAMAIS seul : l'appelant ne s'en sert que si un
# livrable réel a été produit à ce tour et n'apparaît pas dans la rédaction —
# c'est alors la sortie du skill qui s'affiche (rendu de secours), pas la
# question périmée.
_PREALABLE = re.compile(
    r"j['’]ai besoin d|j['’]aurais besoin d"
    r"|il me (?:faut|manque)"
    r"|je ne (?:peux|pourrai) pas (?:creer|produire|generer|faire|fabriquer"
    r"|etablir|remplir|completer)"
    r"|je ne connais pas votre|je ne dispose pas de votre"
    r"|quel(?:le)? est votre"
    r"|(?:pouvez-vous|veuillez|merci de) (?:me |m['’])?"
    r"(?:communiquer|fournir|donner|transmettre|indiquer|preciser)"
    r"|une fois (?:communique|fourni|recu|transmis|renseigne)",
    re.IGNORECASE)


def reclame_un_prealable(texte: str) -> bool:
    """Le texte réclame-t-il à l'utilisateur un PRÉALABLE au travail ?

    Volontairement étroit : chaque motif exige que la phrase demande quelque
    chose POUR faire, pas qu'elle pose une question quelconque. « Voulez-vous
    que je l'envoie par mail ? » n'en est pas un — c'est une suite proposée.
    """
    if not isinstance(texte, str) or not texte:
        return False
    return bool(_PREALABLE.search(_sans_accent(texte)))


# ── LA LIVRAISON FANTÔME ─────────────────────────────────────────────────────
# Relevé en production le 30/08, trois tours de suite : « fais un word avec
# toutes les infos de l'entreprise » → le modèle répond AU PASSÉ (« voici le
# document », « il est téléchargeable ») sans avoir appelé le moindre skill.
# `est_une_annonce` ne pouvait rien y faire : elle reconnaît le futur (« je
# vais créer »), pas la prétention d'avoir déjà fait. Le forceur — l'outil
# exact de ce défaut, qui repart d'un contexte NEUF, immunisé contre un
# historique plein de fausses réussites — ne se déclenchait donc jamais.
#
# Deux prédicats complémentaires, et NI L'UN NI L'AUTRE ne juge seul :
# l'appelant exige en plus qu'AUCUN livrable n'ait été produit au tour
# (`_blocs_livrables`) — une vraie livraison ne déclenche rien.
#
#   · `pretend_avoir_livre` — le texte AFFIRME qu'un fichier existe. Motifs
#     volontairement stricts (un nom de fichier ou « télécharger » exigé) :
#     « il est disponible mardi » parle d'un rendez-vous, pas d'un document.
#   · `demande_une_production` — la DEMANDE du tour réclame la création d'un
#     fichier. C'est le seul signal qui attrape le pire cas observé : le
#     modèle colle un VRAI fichier du fil (l'Excel de la veille) en le
#     faisant passer pour le Word demandé — bloc réel, prétention réelle,
#     production nulle. Aucun examen de la réponse ne peut le voir ; la
#     demande, si.
# Chaque motif du passé EXIGE un nom de fichier : « voici la liste » est
# aussi la phrase normale d'un tableau à l'écran, « je l'ai fait » peut
# répondre à n'importe quoi — les compter ferait forcer des tours justes.
_NOM_FICHIER = r"(?:documents?|fichiers?|word|excel|pdf|rapports?|docx|xlsx)"
_PRETEND_LIVRE = re.compile(
    rf"voici (?:le|la|votre|ton|un|une) [^.!?\n]{{0,40}}?{_NOM_FICHIER}"
    rf"|{_NOM_FICHIER}\b[^.!?\n]{{0,60}}?(?:est|sont) "
    r"(?:pret|prete|prets|disponible|telechargeable|cree|genere"
    r"|produit|termine|finalise)"
    rf"|{_NOM_FICHIER}\b[^.!?\n]{{0,40}}?(?:a|ont) ete "
    r"(?:cree|genere|produit|finalise|prepare|redige)"
    rf"|j['’]ai (?:cree|genere|produit|prepare|finalise|redige)"
    rf" [^.!?\n]{{0,30}}?{_NOM_FICHIER}"
    r"|vous pouvez (?:le|la|les) telecharger"
    r"|pret[es]* a etre telecharge",
    re.IGNORECASE)

_DEMANDE_PRODUCTION = re.compile(
    r"\b(?:fais|faire|cree|creer|produis|produire|genere|generer|redige"
    r"|rediger|prepare|preparer|etablis|etablir|exporte|exporter)\b"
    r"[^.!?\n]{0,80}?\b(?:word|docx|excel|xlsx|pdf|documents?|fichiers?"
    r"|rapports?|tableur)\b",
    re.IGNORECASE)


def pretend_avoir_livre(texte: str) -> bool:
    """Le texte affirme-t-il qu'un fichier existe ou est téléchargeable ?"""
    if not isinstance(texte, str) or not texte:
        return False
    return bool(_PRETEND_LIVRE.search(_sans_accent(texte)))


def demande_une_production(texte: str) -> bool:
    """La demande réclame-t-elle la CRÉATION d'un fichier ?

    Volontairement bornée aux noms de fichiers : « sors-moi la liste des
    clients » se répond très bien par un tableau à l'écran, et forcer une
    production là-dessus changerait un comportement qui convient.
    """
    if not isinstance(texte, str) or not texte:
        return False
    return bool(_DEMANDE_PRODUCTION.search(_sans_accent(texte)))


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
        elif attendue and skill in SATISFAIT_PAR.get(attendue, {attendue}):
            attendue = None
    return attendue

# Une option proposée en prose : « 1. Dresser l'arborescence », « 2) Lancer… ».
# Bornée à 120 caractères : au-delà ce n'est plus un choix, c'est un paragraphe
# numéroté (un plan, une procédure), et en faire un bouton serait absurde.
_OPTION_NUMEROTEE = re.compile(r"^[ \t]*(\d{1,2})[.)][ \t]+(\S.{2,119})$", re.M)

# Les amorces qui trahissent une VRAIE question à choix, par opposition à une
# énumération d'étapes. Sans ce filtre, un plan en cinq points deviendrait cinq
# boutons — et cliquer « 3. Rédiger le devis » n'aurait aucun sens.
_INVITE_A_CHOISIR = re.compile(
    r"(souhaitez-vous|voulez-vous|préférez-vous|que voulez-vous|"
    r"dites-moi (?:lequel|laquelle|ce que)|par quoi|par où|"
    r"laquelle|lequel de ces|je peux (?:commencer par|vous proposer))",
    re.I)


def options_proposees(texte: str) -> list[str]:
    """Les choix qu'une réponse propose en prose, prêts à devenir des boutons.

    POURQUOI ÇA VAUT UN TRAITEMENT À PART. Relevé en production : l'assistant
    termine par « Souhaitez-vous que je commence par : 1. … 2. … 3. … ? »,
    l'utilisateur répond « 1 », et le tour suivant reçoit un message d'un
    caractère qui ne veut rien dire hors contexte. La réponse a été « Je ne
    comprends pas bien ce que signifie ce « 1 » ».

    Le défaut ne se corrige pas en demandant au modèle de mieux comprendre :
    il se corrige en supprimant l'ambiguïté à la source. Un bouton renvoie le
    LIBELLÉ ENTIER comme message, et il n'y a plus rien à deviner.

    Rendu vide si le texte ne pose pas de choix, s'il en pose moins de deux, ou
    s'il porte déjà des suggestions : on complète une réponse, on ne la corrige
    jamais deux fois.
    """
    if not isinstance(texte, str) or not texte.strip():
        return []
    if "quick_replies" in texte:
        return []
    if not _INVITE_A_CHOISIR.search(texte):
        return []
    vus, options = set(), []
    for _, libelle in _OPTION_NUMEROTEE.findall(texte):
        propre = libelle.strip().rstrip(" ?:;.").strip()
        # Une option qui reprend la numérotation dans son texte, ou qui n'est
        # qu'un fragment, ne fait pas un bouton lisible.
        if len(propre) < 3 or propre.lower() in vus:
            continue
        vus.add(propre.lower())
        options.append(propre)
    return options if 2 <= len(options) <= 4 else []


# ── Proposer au lieu d'agir ─────────────────────────────────────────────────
#
# Relevé par Noa le 31/08 : « liste toutes les adresses mail que tu as » →
# « je n'ai pas de commande pour lister… Pour obtenir cette liste, je peux :
# 1. chercher sur le Drive 2. vous demander les adresses. Que préférez-vous ? »
# Le geste existait. Le modèle a répondu par une QUESTION À CHOIX au lieu
# d'essayer — et « il faut qu'il arrête de demander vingt mille fois ».
#
# Deux signatures, étroites : la réponse dit n'avoir PAS DE COMMANDE / d'outil /
# de moyen pour faire (elle n'a pas cherché), ou elle OFFRE de faire et demande
# de choisir (« voulez-vous que je… ? », « que préférez-vous ? »). Ce n'est pas
# une vraie clarification (« à quelle adresse ? », « quel montant ? ») : celles-là
# demandent une DONNÉE, pas la permission d'agir. Quand aucun geste n'a tourné
# dans le tour, cette réponse repart au forceur (contexte neuf), qui trouve le
# geste ou, à défaut, laisse la question.
_SANS_COMMANDE = re.compile(
    r"je n['’]ai pas (?:de |d['’])(?:commande|outil|fonction|moyen|acc[eè]s direct|action)s? "
    r"(?:pour|qui|permettant|me permettant)|"
    r"je ne dispose (?:pas |d['’]aucun[e]? )(?:de |d['’])?(?:commande|outil|fonction|moyen)|"
    r"(?:aucune?|pas de) (?:commande|outil|fonction|action) (?:ne |n['’])?(?:me )?permet|"
    r"il n['’]existe pas (?:de |d['’])(?:commande|outil|fonction|action)",
    re.I)
_OFFRE_DE_FAIRE = re.compile(
    r"(?:voulez-vous|souhaitez-vous|préférez-vous|preferez-vous|que préférez-vous|que preferez-vous|"
    r"dois-je|puis-je|faut-il que je|je peux (?:vous proposer|commencer par)|je peux ?:)",
    re.I)


def propose_au_lieu_d_agir(texte: str) -> bool:
    """Vrai quand la réponse dit ne pas avoir de commande, ou offre de faire en
    demandant de choisir — au lieu d'essayer. À n'appliquer QUE si aucun geste
    n'a tourné dans le tour : après une action, une question de suite est légitime."""
    if not isinstance(texte, str) or not texte.strip():
        return False
    t = _sans_accent(texte)
    if _SANS_COMMANDE.search(texte) or _SANS_COMMANDE.search(t):
        return True
    if "?" in texte and (_OFFRE_DE_FAIRE.search(texte) or _OFFRE_DE_FAIRE.search(t)):
        # Une offre de faire, pas une demande de donnée : « à quelle adresse ? »
        # ou « quel montant ? » restent des clarifications légitimes.
        # Un interrogatif ouvert — « quelles informations », « combien », « à qui »,
        # « lequel » — demande une DONNÉE : on ne force pas.
        demande_une_donnee = re.search(
            r"\b(?:quel|quelle|quels|quelles|lequel|laquelle|lesquels|lesquelles|combien|"
            r"ou|quand|a qui|a quel|a quelle|pour qui|comment)\b", t, re.I)
        return not demande_une_donnee
    return False
