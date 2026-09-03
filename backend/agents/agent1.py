"""
Agent 1 — Administratif / Suivi de chantiers (BTP — Duret & Sols)
Pipeline : RAG pgvector → anonymisation NER → [browser?] → LLM → réhydratation → validation check
Zéro PII vers l'API LLM : la requête ET les documents sont masqués avant l'appel,
puis les vraies valeurs sont réinjectées dans la réponse (entity_map).
"""
import logging

from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END
from agents.state import AgentState
from llm.router import get_llm, LLMTier

logger = logging.getLogger("duret.agents.agent1")

_JOURS_FR = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
_MOIS_FR = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
            "septembre", "octobre", "novembre", "décembre")


def _maintenant() -> str:
    """« lundi 31 août 2026, 21:40 » — heure de Paris, en français.

    LA DATE N'ÉTAIT NULLE PART (31/08). Le modèle ne sait pas quel jour on est :
    « cette semaine » un lundi devenait « depuis aujourd'hui », et il datait ses
    réponses au hasard. Elle va dans le message (qui change à chaque tour), pas
    dans le préfixe système, pour ne pas casser le cache de prompt.
    """
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo
    t = _dt.now(ZoneInfo("Europe/Paris"))
    jour = "1er" if t.day == 1 else str(t.day)
    return f"{_JOURS_FR[t.weekday()]} {jour} {_MOIS_FR[t.month - 1]} {t.year}, {t:%H:%M}"


SYSTEM_PROMPT = """Tu es l'assistant IA interne de Duret & Sols, entreprise de travaux de sols et de revêtements (BTP).
Tu assistes l'équipe administrative et le suivi de chantiers dans leur travail quotidien : gestion administrative, comptabilité, réponses aux mails, factures et situations, suivi du temps passé sur les chantiers, commandes, planning, fournisseurs, règlements, réserves, contentieux et dossiers juridiques, support commercial sur les dossiers existants.
Tu disposes d'une mémoire d'entreprise : fichiers importés (clients, devis, factures, fournisseurs), documents (appels d'offres, CCTP, CCAP, DPGF, plans, DOE, commandes, situations, documents fournisseurs, dossiers juridiques, réserves, dossiers chantier), mails.

OÙ EST CHAQUE DONNÉE. Quatre sources, quatre gestes. Choisis le bon AVANT de répondre :
1. CLIENTS, DEVIS, FACTURES, CHIFFRES (combien, liste, total, chiffre d'affaires, tout ce qu'on sait d'un client) : ce sont des FICHIERS IMPORTÉS, lus de façon EXACTE par `liste_clients`, `liste_fournisseurs`, `fiche_client` et `interroger_donnees`. Jamais la recherche documentaire pour cela (elle approxime et ne sait pas compter), jamais le web (il ne connaît pas les clients de l'entreprise).
2. DOCUMENTS (contrats, comptes rendus, plans, pièces d'un dossier, courrier archivé) : `rechercher_documents` retrouve un texte par ressemblance. Pour parcourir ou ouvrir les fichiers eux-mêmes : les gestes du serveur de fichiers (`nas_arborescence`, `nas_lister`, `nas_ouvrir`, `nas_lire`, `nas_lire_lot`, `nas_chercher`, `nas_apercu`).
3. MAILS : `boites_mail` pour LISTER les boîtes et adresses mail accessibles ; `check_mails` pour faire le point (résumés, réponses à proposer, avec le COMPTE de la période) ; `lire_mails` pour consulter une boîte ou compter ; `lire_mail` pour OUVRIR un message en entier (une liste ne rend qu'un extrait de chaque message — pour répondre, résumer ou citer un mail, ouvre-le d'abord ; `pieces: true` récupère et LIT ses pièces jointes) ; `lire_piece_jointe` pour UNE pièce jointe (PDF, image, plan DWG/DXF : téléchargeable, aperçu, contenu lu) ; `redaction_email` pour écrire ; `preparer_envois` pour un MÊME mail à PLUSIEURS destinataires (10, 100, sans limite : une carte par destinataire, gabarit à variables {nom} {email} ou corps sur mesure par destinataire, pages de 40 à enchaîner — rien ne part sans validation). Ces gestes lisent les messages RÉELS, en direct : la recherche documentaire ne voit que ce qui a été ingéré. Le détail est borné à 25 messages, le total ne l'est pas : pour « combien », cite le total. Pour analyser tout le courrier de l'entreprise (process, activités), la seule voie est `lancer_enrichissement`.
4. LE WEB (`chercher_web`, `ouvrir_page`, `naviguer`) : UNIQUEMENT pour une information PUBLIQUE qui n'existe pas dans l'entreprise (prix public, norme, réglementation, coordonnées d'un fournisseur, contenu d'un site), ou quand on te le demande. Ne réponds jamais que tu n'as pas accès à internet : c'est faux. Mais ne l'utilise JAMAIS pour les clients, devis, factures, chantiers ou mails : il ne peut rendre que du bruit. Ce qui en vient est EXTERNE : cite les adresses, ne le présente jamais comme une donnée interne.
La mémoire n'est PAS consultée d'avance : rien ne se passe si tu n'émets pas l'action. Pour une salutation, un remerciement ou une conversation courante, réponds simplement, SANS action et SANS parler de la mémoire d'entreprise. Dès qu'on te demande de FABRIQUER un fichier ou de TOUCHER à un système (créer un document, lire ou déposer un fichier, lire des mails, produire un visuel), il FAUT émettre les actions : aucune rédaction directe ne produit un document téléchargeable.

AUCUNE ACTION NE COUVRE LA DEMANDE ? Ne réponds pas « je ne sais pas faire » ni « je n'ai pas de commande pour » : la plupart de ces demandes se composent de gestes que tu as déjà — relis le catalogue, compose-les. ESSAIE D'ABORD : exécute la voie la plus directe et montre le résultat ; ne demande une précision QUE si, sans elle, le résultat serait FAUX (le destinataire d'un envoi, le montant d'une facture) — jamais « que préférez-vous ? » entre deux voies que tu peux toutes les deux prendre, jamais « voulez-vous que je… ? » pour un geste de lecture : fais-le. UNE SEULE SALVE DE QUESTIONS, JAMAIS DEUX : si tu dois demander une précision, pose TOUT ce qui te manque en UN message, puis agis avec ce qu'on te répond. Ne reviens pas demander autre chose au tour suivant — ce qui manque encore, tu le cherches (une adresse est dans l'annuaire, une période se déduit de la date du jour, un client se retrouve par son nom) ou tu prends l'hypothèse la plus raisonnable EN LA DISANT. Zéro question vaut mieux qu'une, et une vaut infiniment mieux que deux. Si la marche à suivre a demandé plusieurs gestes et qu'elle a marché, propose de la retenir avec `enregistrer_procedure` pour les fois suivantes. Ne retiens jamais une marche à suivre que tu n'as pas vérifiée, et n'annonce jamais une étape qu'aucune de tes actions ne sait faire.

LE TRAVAIL LONG S'ANNONCE AVANT DE COMMENCER. Quand une demande tient en PLUSIEURS gestes distincts (analyser un document PUIS retrouver un client PUIS produire un fichier PUIS rédiger un mail), n'attaque pas : appelle `proposer_plan` avec les étapes, en français, dans l'ordre. La personne approuve, et tu exécutes alors TOUT d'un coup, sans redemander d'accord, pour rendre UNE SEULE réponse à la fin. Pour un travail qui tient en un seul geste, ne planifie rien : fais-le. Ne l'utilise jamais pour une question, une salutation ou une rédaction simple.

CE QUE LES FICHIERS NE CONTIENNENT PAS. Les jeux importés portent ce qui a été FACTURÉ : ni les achats, ni les heures passées, ni la sous-traitance. On peut donc calculer un CHIFFRE D'AFFAIRES, jamais une MARGE ni une RENTABILITÉ. Si on te demande le client « le plus rentable », le poste « qui rapporte le plus », ou toute question de marge : donne le classement par chiffre d'affaires, et dis EXPLICITEMENT que la rentabilité demanderait les coûts, absents de nos données. Ne présente jamais un chiffre d'affaires comme une rentabilité : celui qui lit « rentable » comprend « marge », et repartirait avec un chiffre faux.

CE QUE TU NE PROMETS JAMAIS. Ne dis jamais que tu vas ENVOYER, TRANSMETTRE, EXPÉDIER ou ADRESSER quoi que ce soit à un client ou à un tiers : tout ce qui sort de l'entreprise passe par l'accord explicite de la personne, et c'est elle qui déclenche l'envoi. Dis « je prépare le message, vous validerez l'envoi », jamais « je l'enverrai une fois que vous m'aurez confirmé ». La promesse est fausse et elle engage l'entreprise : celui qui la lit croit que le mail partira tout seul.

LA VÉRITÉ. N'invente JAMAIS de donnée : ni montant, ni nom, ni date, ni nombre, ni référence. Tout chiffre que tu avances vient d'un résultat d'action ou de ce que l'utilisateur vient de dire ; cite-le tel quel, sans le recalculer ni l'arrondir. Sois utile pour : retrouver un dossier par chantier, faire le point sur des commandes / réserves / échéances, préparer un brouillon de réponse à un mail, suivre un dossier juridique ou un règlement fournisseur. Les décisions engageantes (envoi d'un mail, facturation, action juridique) restent validées par un humain.
LE CLASSEMENT PORTE LES NOMS. AVANT de répondre qu'une information sur un client, un chantier ou un fournisseur est introuvable, cherche son NOM dans le classement des fichiers avec `nas_chercher` : les dossiers de l'entreprise portent les noms des clients, à toutes les profondeurs. Montre ce qui est trouvé (dossiers, fichiers, chemins), puis PROPOSE d'aller plus loin : ouvrir un fichier trouvé, explorer un dossier trouvé, chercher dans le contenu des documents — c'est l'utilisateur qui décide de pousser.
Une recherche qui ne rend rien signifie « rien ne correspond à CES termes », jamais « il n'y a rien » : dis ce que tu as cherché, et propose des termes plus concrets. Affirmer que la mémoire ne contient aucun mail ou aucun document est une affirmation sur l'état du système, que seul un inventaire explicite autorise. Un nom de jeu de données qui n'existe pas n'est pas un jeu vide.
UN ÉCHANTILLON N'EST PAS UN INVENTAIRE : quelques messages d'une boîte ne disent rien des activités, des process ni de l'histoire de l'entreprise. Ne généralise jamais de dix mails vers une description de la société.
QUI EST DE L'ENTREPRISE : une adresse n'est un collègue que si elle appartient au domaine de l'entreprise. Les résultats de lecture de mails portent `expediteur_interne` : quand il vaut false, la personne est EXTERNE (client, fournisseur, prestataire) et tu ne dois jamais la présenter comme appartenant à l'entreprise. `expediteur_automatique` signale un envoi sans auteur humain (bulletin, notification) : n'en tire aucune conclusion sur les gens ni sur les métiers.
QUI TE PARLE EST CONNU DU SERVEUR : `mes_droits` rend le nom et l'adresse e-mail de la personne connectée, et `@moi` vaut cette adresse partout où un skill l'accepte (colonnes `ajouts` de `liste_clients` comme de `liste_fournisseurs`). Ne demande JAMAIS à quelqu'un sa propre adresse ou son propre nom, et ne réponds jamais que tu ne les connais pas : c'est faux. Plus largement, avant d'écrire « je ne sais pas » ou de poser une question, vérifie qu'aucune de tes actions ne détient déjà l'information.
DONNÉE MANQUANTE : quand on te demande de remplir une fiche, un tableau, un récapitulatif ou un modèle et qu'une information ne figure nulle part, écris exactement [À COMPLÉTER] à sa place. Ne l'omets pas en silence, ne la devine pas, ne la remplace pas par une valeur plausible. Cette règle vaut pour chaque champ pris séparément : une fiche à moitié renseignée est utile, une fiche à moitié inventée est dangereuse.
Certaines valeurs peuvent apparaître masquées sous forme de balises [PER_1], [MONTANT_2], etc. Conserve-les telles quelles et ne CRÉE jamais toi-même de balise entre crochets. Une balise reste une VRAIE valeur, simplement masquée : passée telle quelle en paramètre d'une action, le serveur la remplace par la valeur réelle. Ne dis jamais qu'une balise « n'est pas une vraie donnée » et ne redemande jamais l'information qu'elle porte : la personne l'a déjà donnée.

TOUT SIGNIFIE TOUT. Quand la demande porte sur l'ENSEMBLE (« tous mes clients », « tous les mails », « toute la base ») : les COMPTES et TOTAUX rendus par les gestes portent déjà sur tout — cite-les. Quand un résultat dit « tronqué », « page x sur y » ou rend `pour_continuer`, ENCHAÎNE les pages jusqu'à couvrir la demande, ou produis le FICHIER complet quand le geste le propose (`liste_clients`/`liste_fournisseurs` avec fichier: true). Ne conclus JAMAIS à partir d'un échantillon présenté comme le tout : si tu t'arrêtes avant la fin, dis exactement ce qui est couvert et comment obtenir le reste.
UN CHIFFRE SE LIT, IL NE S'ESTIME JAMAIS. Tout nombre que tu donnes (compte de mails, de dossiers, montant) se recopie À L'UNITÉ depuis un résultat d'action de CE tour : jamais « environ », « à peu près », « une soixantaine » quand un geste rend le compte exact. Un chiffre cité plus tôt dans la conversation est PÉRIMÉ (la boîte, la base, les dossiers ont changé depuis) : pour redonner un compte, refais le geste qui le rend et cite le résultat du tour, pas ton souvenir.
UNE DEMANDE RÉPÉTÉE SE REFAIT. Quand on te redemande un travail déjà fait (« fais le point sur les mails » alors que le point a été fait tout à l'heure) : REFAIS les gestes et livre le résultat À JOUR. Ne réponds JAMAIS « cela a déjà été fait », ne renvoie jamais vers une réponse précédente et ne la ressers pas de mémoire : elle date de son moment, la personne veut l'état ACTUEL. Seule une question qui porte sur le passé lui-même (« as-tu envoyé le mail ? ») se répond par ce qui a été fait.
PLUSIEURS DEMANDES DANS UN MESSAGE (« affiche le mail complet et dis-moi combien j'en ai reçu ») : traite-les TOUTES, chacune avec son geste, avant de rédiger ; la réponse répond à chacune, dans l'ordre, et dit celle que tu n'as pas pu faire.
UNE QUESTION COURTE SANS OBJET (« es-tu sûr ? », « vraiment ? », « et alors ? ») porte sur TA DERNIÈRE réponse, jamais sur un échange plus ancien : vérifie-la (refais le geste s'il le faut) et réponds sur elle. La date du jour t'est donnée à chaque message : une période (« cette semaine », « les 7 derniers jours ») se demande en DURÉE (« 7j »), jamais en date que tu calcules.

LA FORME. Réponds toujours en français. Sois précis, professionnel et concis. Réponds, puis arrête-toi : ne recopie pas la demande, ne répète pas une information déjà donnée.
Un message qui commence par « non » suivi d'une demande (« non, affiche les 28 ») REFUSE ta proposition précédente et FORMULE la demande à exécuter : exécute-la, ne réponds pas « d'accord, je ne le fais pas ».
Salutation : commence par « Bonjour » UNIQUEMENT si le message de l'utilisateur est lui-même une salutation (bonjour, salut, bonsoir...) ; sinon réponds DIRECTEMENT, sans formule d'accueil, et sans jamais répéter une salutation déjà faite dans la conversation. Ne dis JAMAIS « je suis Duret & Sols » ni « je m'appelle Duret & Sols » (c'est le nom de l'entreprise, pas ton identité) et ne te présente pas.
Typographie : n'utilise JAMAIS de tiret cadratin ni de tiret demi-cadratin ; emploie plutôt une virgule, un deux-points, une parenthèse ou un point."""


# Nombre maximal d'actions exécutées dans un même tour. Chaque action coûte un
# aller-retour LLM supplémentaire : au-delà, le modèle tourne en rond plus qu'il
# n'avance, et la facture grimpe pour rien.
#
# RELEVÉ DE 3 À 8. Trois suffisaient tant qu'une demande se traduisait par une
# recherche puis une réponse. Produire un document en demande TROIS à lui seul
# (créer, remplir, terminer) : la moindre consultation préalable faisait dépasser
# le budget, et le tour se terminait sur « je vais le faire » sans que rien ne
# soit fait — observé sur « compte les dossiers puis fais-en un PDF ».
#
# Le garde-fou contre les boucles ne repose de toute façon pas sur ce chiffre :
# une action REJOUÉE à l'identique est reconnue par son empreinte et resservie
# sans être exécutée. Ce qui est borné ici, c'est le travail qui AVANCE.
# CE N'EST PLUS UN BUDGET, C'EST UN GARDE-FOU D'EMBALLEMENT.
#
# À 8, le chiffre bornait des tâches légitimes : lire cinq cahiers des charges,
# les analyser, puis produire deux documents demande bien davantage, et
# l'utilisateur recevait « le nombre d'actions autorisées est atteint » sur une
# demande parfaitement raisonnable.
#
# Or ce compteur n'a jamais mesuré le coût : il mesurait « est-ce que ça mène
# quelque part », et mal. Le vrai signal d'un tour qui tourne en rond est
# l'ENLISEMENT, pas le nombre d'actions — c'est lui qui est mesuré plus bas.
# Ce plafond-ci ne sert plus qu'à empêcher une boucle folle de durer des heures.
# 40 → 120 (01/09, règle de Noa : une recherche ne doit JAMAIS être bloquée en
# quantité — enchaîner cinquante pages de mails ou de documents est un travail
# qui avance, pas une boucle).
MAX_ACTIONS_PAR_TOUR = 120
# Un même skill rappelé sans fin avec des paramètres qui changent un peu à
# chaque fois — le 31/08 : DIX-SEPT `interroger_donnees` en neuf minutes pour
# « dégager 10 missions types » de 1 398 titres de devis, ce que ce skill ne
# sait pas faire. La garde « à l'identique » ne voyait rien (empreintes
# différentes) et le plafond global de 40 laissait faire. Au-delà de ce
# nombre, la boucle sort sur une note et le modèle rédige avec ce qu'il a.
# Les gestes qui CONSTRUISENT un document par morceaux sont exemptés : un
# rapport de douze sections, c'est douze `ajouter_document` légitimes.
MAX_APPELS_MEME_SKILL = 10
SKILLS_SANS_PLAFOND = frozenset({"ajouter_document"})

# LA PAGINATION N'EST PAS DE L'ACHARNEMENT (01/09, règle de Noa : une recherche
# ne se bloque jamais en quantité). « Les 60 suivants », « page 4 », « avant » :
# le même skill rappelé avec la SEULE pagination qui change est un travail qui
# AVANCE — le compter dans MAX_APPELS_MEME_SKILL coupait « lis TOUS les mails »
# à la dixième page, exactement le comportement que TOUT SIGNIFIE TOUT exige.
# Les vraies variations (filtres, motifs qui changent à chaque essai — les
# 17 `interroger_donnees` du 31/08) comptent toujours.
_CLES_PAGINATION = frozenset({"page", "avant", "lettre"})


def _est_une_page_de_plus(avant: dict, courant: dict) -> bool:
    """Deux appels du même skill qui ne diffèrent QUE par la pagination."""
    avant, courant = avant or {}, courant or {}
    if avant == courant:
        return False
    cles = set(avant) | set(courant)
    if not any(avant.get(k) != courant.get(k) for k in cles & _CLES_PAGINATION):
        return False
    return all(avant.get(k) == courant.get(k) for k in cles - _CLES_PAGINATION)

# LE FILET CONTRE L'ERRANCE — PAS CONTRE L'EXPLORATION.
#
# À 3, ce compteur a tué un tour qui était en train de se corriger : chaque
# refus du Drive renvoie la liste des dossiers réellement présents, et le tour
# du matin, parti de la MÊME erreur, s'était rattrapé à l'essai suivant et
# avait tout livré. Trois échecs DISTINCTS, c'est souvent un modèle qui lit
# les indications et resserre — pas un modèle perdu.
#
# La vraie obstination — redemander À L'IDENTIQUE une action qui a échoué —
# a déjà sa sortie immédiate dans le bloc de rejeu, avec la raison d'origine.
# Ce compteur-ci n'est que le filet DERRIÈRE ce garde : six tentatives
# différentes qui échouent toutes d'affilée, c'est une errance qui n'écoute
# plus les indications, et chaque essai coûte un appel.
MAX_ECHECS_CONSECUTIFS = 6

# À PARTIR D'OÙ UN TOUR EST « LONG », DONC OÙ UN LIVRABLE SE PRÉSENTE.
#
# En deçà, une demande simple — « fais-moi une note de deux pages » — tient en
# quelques actions et n'a aucune raison d'être coupée en deux. Au-delà,
# l'attente devient assez longue pour qu'un résultat déjà prêt mérite d'être
# montré tout de suite plutôt que d'attendre la fin d'un travail qui continue.
#
# Dix : le premier document du tour relevé en production était terminé à la
# dixième action, et le reste a duré vingt minutes de plus.
POINT_ETAPE_ACTIONS = 10


# Les versements dans un document en cours sont exemptés du budget ci-dessus
# (ils avancent par construction), mais pas sans borne : le document accepte
# 20 000 éléments, donc un modèle qui en verserait UN par appel obtiendrait
# 20 000 allers-retours — pas une boucle infinie, un tour qui dure des heures.
# 40 versements couvrent 16 000 blocs au rythme normal (400 par appel), soit
# bien au-delà de tout document réel.
MAX_VERSEMENTS_PAR_TOUR = 40

# LE SCHÉMA D'UNE ARBORESCENCE NE TIENT PAS DANS 4000 CARACTÈRES. Le résultat
# de chaque action est plafonné avant de repartir vers le modèle — et c'est ce
# plafond, pas l'outil, qui tronquait l'arbre : le modèle relançait alors
# l'exploration « car le résultat précédent était tronqué », mot pour mot, et
# le budget d'actions y passait. Ces skills-là, dont la sortie EST le contenu
# demandé, ont droit à un plafond large ; les autres gardent le plafond serré,
# un résultat d'action ordinaire n'ayant rien à faire au-delà.
# (Le nom varie selon le projet — drive_ ou nas_ — la règle est la même.)
# Corrections d'un bloc d'action mal formé ou COUPÉ, par tour. Deux essais :
# une sortie tronquée par le plafond se répète volontiers une fois avant que le
# modèle réduise vraiment le volume. Au-delà, on n'insiste pas.
MAX_REPARATIONS_PAR_TOUR = 2
# DEUX FORÇAGES PAR TOUR, PAS UN. Relevé le 22/08 : le modèle annonce « je
# prépare le visuel » (forcé → preparer_visuel réussit), puis annonce « je
# lance le tirage » — et le forceur, déjà consommé, ne pouvait plus rien. La
# boucle se fermait, la dernière passe annonçait encore, fin du tour sans
# image. Un enchaînement de deux gestes est la norme, pas l'exception
# (préparer puis essayer, lire puis résumer). Au-delà de deux, on rédige avec
# ce qu'on a.
MAX_FORCAGES_PAR_TOUR = 2

# Les skills mail y sont depuis le 31/08 : dix extraits de 800 caractères ne
# tenaient pas dans 4 000, le JSON de la liste était tranché au milieu — le
# modèle ne voyait que les premiers messages, coupés. Et un message OUVERT
# (`lire_mail`, corps jusqu'à 10 000 caractères) doit passer entier.
# Puis la recherche documentaire (jusqu'à 20 documents par page, extraits
# fenêtrés) et les enregistrements filtrés (25 par page) : une page qui ne
# passe pas entière est une page qu'on redemande.
# Les écritures acceptées du jeton « le message de l'utilisateur, en entier ».
# Plusieurs, parce qu'un modèle qui a compris l'idée n'écrit pas toujours le
# mot exact — et qu'un jeton non reconnu partirait tel quel dans le skill.
JETONS_MESSAGE = {"@message", "@transcription", "@texte", "@demande",
                  "@ma_demande", "@message_utilisateur"}
# Et le jeton « toutes les lignes du tableau joint » (03/09) : un modèle qui
# devait recopier 95 clients dans son bloc ```action en a recopié 30.
JETONS_TABLEAU = {"@tableau", "@lignes", "@fichier_joint", "@excel", "@tableau_joint"}


def _est_jeton_message(valeur) -> bool:
    """La valeur est-elle le jeton « mets ici le message de l'utilisateur » ?"""
    return isinstance(valeur, str) and valeur.strip().lower() in JETONS_MESSAGE


def _est_jeton_tableau(valeur) -> bool:
    return isinstance(valeur, str) and valeur.strip().lower() in JETONS_TABLEAU


RESULTATS_GENEREUX = {"drive_chercher", "nas_chercher", "drive_apercu",
                      "nas_apercu", "preparer_envois",
                      "drive_arborescence", "nas_arborescence",
                      "lire_mails", "lire_mail", "check_mails",
                      "rechercher_documents", "interroger_donnees",
                      # Un compte rendu concis pese quand meme quelques milliers
                      # de caracteres : coupe a 4 000, le modele n'en verrait que
                      # le debut et enchainerait sur une reunion qu'il a lue a
                      # moitie. Le bloc, lui, est deja hors de la coupe.
                      "compte_rendu_reunion"}
PLAFOND_RESULTAT = 4000
PLAFOND_RESULTAT_GENEREUX = 12000


# ANNONCE SANS ACTE. Le modèle écrit « je crée le PDF », « je commence par
# compter », et n'émet AUCUN bloc d'action. Le tour se terminait sur cette
# phrase : l'utilisateur lit une promesse, redemande, et obtient la même
# promesse. Observé sur plusieurs tours d'affilée.
#
# On ne peut pas l'empêcher d'écrire cela ; on peut refuser que ce soit la FIN
# du tour. Une seule relance, avec une consigne explicite — au-delà on
# insisterait sur un modèle qui ne veut pas, et la note de sortie explique alors
# honnêtement pourquoi rien n'a été fait.
from agents.annonce import (est_une_annonce, cloture_attendue, promesse_sans_suite,
                            options_proposees, reclame_un_prealable,
                            pretend_avoir_livre, demande_une_production,
                            propose_au_lieu_d_agir, renvoie_au_deja_fait,
                            demande_sur_le_passe, demande_un_visuel,
                            deuxieme_salve_de_questions)


# ── Nœuds ────────────────────────────────────────────────────────────

def _derniere_reponse_assistant(state) -> str:
    """La dernière chose que l'assistant a dite dans ce fil, avant ce tour.

    Sert à voir une RÉPÉTITION : certains défauts ne se lisent pas dans une
    réponse isolée, seulement dans son rapport à la précédente. Poser des
    questions est légitime ; en poser deux tours de suite sans avoir rien fait
    entre les deux ne l'est pas.
    """
    for m in reversed(state.get("messages") or []):
        if getattr(m, "type", "") != "ai" and m.__class__.__name__ != "AIMessage":
            continue
        contenu = getattr(m, "content", "")
        return contenu if isinstance(contenu, str) else str(contenu)
    return ""


async def rag_node(state: AgentState) -> dict:
    """Prépare le contexte immédiat du tour. NE FAIT PLUS de recherche.

    La recherche documentaire est devenue un OUTIL (`rechercher_documents`) que
    le modèle appelle s'il en a besoin. Auparavant elle tournait avant chaque
    appel, quoi qu'on dise : un « bonjour » déclenchait une recherche
    vectorielle, une passe d'anonymisation sur les résultats, puis un préambule
    « aucun document trouvé » qui poussait le modèle à répondre à côté.

    Reste ici ce qui n'a pas à être décidé : une pièce jointe envoyée à l'instant
    fait évidemment partie du contexte.
    """
    texte_joint = state.get("attachment_text")
    if not texte_joint:
        return {"raw_chunks": []}
    nom = state.get("attachment_name") or "document"
    return {"raw_chunks": [f"[FICHIER JOINT PAR L'UTILISATEUR : {nom}]\n{texte_joint}"]}


async def anonymize_node(state: AgentState) -> dict:
    """Masque la requête ET les chunks avant tout envoi LLM (entity_map partagé)."""
    from security.anonymizer import anonymizer

    import asyncio
    query = state.get("query", "")
    chunks = list(state.get("raw_chunks") or [])
    # entity_map PERSISTANTE sur le fil : on repart de celle des tours précédents pour
    # qu'une même valeur garde le MÊME placeholder d'un tour à l'autre. Sans ça, la
    # numérotation redémarrant à 1 à chaque tour, [PER_1] désignerait une personne
    # différente dans l'historique et dans la question courante — le modèle fusionnerait
    # les deux et la réhydratation réinjecterait la mauvaise valeur.
    # Désamorce les balises que l'utilisateur aurait saisies lui-même : la map étant
    # cumulative, « donne-moi [PER_1] » lui ferait sinon restituer la valeur réelle
    # attachée à ce jeton par un tour antérieur ou par un document.
    query = anonymizer.neutralize_placeholders(query)
    previous_map = state.get("entity_map") or {}
    # NER spaCy = CPU-bound synchrone : on le sort de la boucle événementielle (sinon il
    # fige le streaming WS et bloque les autres requêtes pendant toute l'étape).
    # L'ÉTAPE EST SUPPRIMÉE quand l'anonymisation est coupée (défaut depuis le
    # 31/08, demande de Noa) : ni passe spaCy dans un thread, ni regex — la
    # question et les extraits passent tels quels, la carte du fil ne bouge
    # pas. Le nœud reste dans le graphe pour que la réhydratation et les
    # anciennes balises continuent de fonctionner ; il ne coûte plus rien.
    if anonymizer.desactivee():
        return {"anonymized_query": query, "anonymized_chunks": chunks,
                "entity_map": dict(previous_map)}
    masked, entity_map = await asyncio.to_thread(
        anonymizer.anonymize_chunks, [query] + chunks, previous_map
    )

    return {
        "anonymized_query": masked[0] if masked else query,
        "anonymized_chunks": masked[1:] if len(masked) > 1 else [],
        "entity_map": entity_map,
    }


def _echange_precedent(state: AgentState) -> str:
    """Le dernier tour, court, pour que le routeur ne juge pas à l'aveugle.

    Quatre cents caractères par message suffisent à reconnaître une suite de
    conversation : on paie quelques dizaines de jetons sur le palier LIGHT,
    jamais davantage.
    """
    recents = [m for m in (state.get("messages") or [])
               if getattr(m, "type", None) in ("human", "ai")][-2:]
    lignes = []
    for m in recents:
        qui = "Utilisateur" if getattr(m, "type", None) == "human" else "Assistant"
        texte = " ".join(str(getattr(m, "content", "") or "").split())
        if texte:
            lignes.append(qui + " : " + texte[:400])
    if not lignes:
        return ""
    saut = chr(10)
    return "Échange précédent :" + saut + saut.join(lignes) + saut + saut


async def routeur_node(state: AgentState) -> dict:
    """Décide de la suite : répondre directement, ou consulter la mémoire.

    C'est une IA qui tranche, pas une liste de mots-clés — mais elle tranche en
    UN appel très court, sur le palier le plus léger, avant toute rédaction.

    Pourquoi pas laisser le modèle rédacteur décider via un bloc d'action : sur
    les modèles modestes de la cascade, un « salut » déclenchait des recherches
    en boucle jusqu'au garde-fou, pour un résultat lent et vide. Séparer la
    DÉCISION de la RÉDACTION rend le chemin court quand il doit l'être.
    """
    from llm.router import get_llm, LLMTier as _T
    from langchain_core.messages import HumanMessage as _H
    import json as _json
    import re as _re

    question = state.get("anonymized_query") or state.get("query", "")

    # Une pièce jointe vient d'arriver : le contexte est déjà là, rien à chercher.
    if state.get("attachment_text"):
        # Le contexte est déjà là, mais analyser un document EST un travail de fond.
        return {"besoin_memoire": False, "llm_tier": "complex"}

    # UNE POLITESSE N'A PAS BESOIN D'UNE IA POUR ÊTRE RECONNUE.
    #
    # Ce nœud coûte un aller-retour complet vers le modèle AVANT que la moindre
    # rédaction ne commence. Sur une vraie question, il est rentable : il évite
    # une recherche vectorielle inutile et choisit le palier. Sur « merci »,
    # « ok » ou « oui », il fait attendre plusieurs secondes pour trancher ce
    # qu'une comparaison de chaînes tranche à coup sûr — et ce sont justement
    # les échanges où l'attente se remarque le plus, parce qu'on attend une
    # réponse de trois mots.
    #
    # LA LISTE EST VOLONTAIREMENT COURTE ET FERMÉE : uniquement des messages qui
    # ne peuvent RIEN vouloir dire d'autre, et seulement quand ils sont seuls.
    # « merci de me sortir le devis Dupont » ne correspond pas — il y a autre
    # chose derrière le mot. Au moindre doute, on paie l'appel : se tromper ici
    # coûte une recherche manquée, ce qui est bien pire que deux secondes.
    _nu = _re.sub(r"[\s!.,;:?…]+", " ", question.lower()).strip()
    _COURTOISIES = {
        "bonjour", "bonsoir", "salut", "coucou", "hello", "hey", "re",
        "merci", "merci beaucoup", "merci bien", "mille mercis", "nickel",
        "parfait", "super", "top", "genial", "génial", "ok", "okay", "d'accord",
        "daccord", "ca marche", "ça marche", "tres bien", "très bien", "bien",
        "oui", "non", "yes", "no", "au revoir", "bonne journee", "bonne journée",
        "bonne soiree", "bonne soirée", "a bientot", "à bientôt", "bye",
    }
    if _nu in _COURTOISIES:
        logger.info("Routage court-circuité (courtoisie) : « %s »", _nu[:40])
        return {"besoin_memoire": False, "llm_tier": "standard"}

    # LA VOIE RAPIDE (31/08). Une suite courte et sans objet propre — « oui »,
    # « 1 », « es-tu sûr ? » — n'a besoin ni de recherche mémoire (la fenêtre
    # récente la couvre, et le rappel vectoriel est déjà coupé pour elle) ni
    # d'un juge : cet appel LLM « très court » coûtait une minute entière quand
    # la cascade tournait sur un modèle lent, à CHAQUE message.
    from agents.memoire_conversation import question_meta
    # …et seulement pour une SUITE : un premier message, même court
    # (« liste les clients »), passe par le juge — la voie rapide ne
    # décide RIEN du fond, elle évite un appel qui ne servait à rien.
    if question_meta(str(state.get("query") or "")) and (state.get("messages") or []):
        logger.debug("Routage : voie rapide (suite courte), aucun appel LLM")
        return {"besoin_memoire": False, "requete_memoire": "", "llm_tier": "standard"}

    invite = (
        "Tu orientes une demande adressée à l'assistant interne d'une entreprise.\n"
        "Dis UNIQUEMENT s'il faut consulter la mémoire d'entreprise (chantiers, devis, "
        "factures, commandes, dossiers, mails, documents internes) pour répondre.\n"
        "- Salutation, remerciement, question générale, demande de rédaction ou de "
        "reformulation, suite directe de la conversation : AUCUNE recherche.\n"
        "- Question portant sur un dossier, un client, un montant ou un document "
        "de l'entreprise : recherche NÉCESSAIRE.\n"
        "- Demande de CONSULTER une boîte mail (lire, voir, relever ses messages) : "
        "AUCUNE recherche. Les messages se lisent en direct dans la boîte, pas dans "
        "la mémoire.\n"
        "Dis AUSSI quel effort la demande réclame :\n"
        '- "simple" : salutation, question factuelle, rédaction courte, suite de '
        "conversation. La grande majorité des cas.\n"
        '- "analyse" : il faut comparer, synthétiser, recouper plusieurs sources, '
        "expliquer un raisonnement, tirer des conclusions d'un ensemble de données.\n"
        'Réponds par un objet JSON seul : {"memoire": true|false, "requete": '
        '"<mots-clés de recherche si true, sinon vide>", "effort": "simple|analyse"}\n\n'
        # LE ROUTEUR JUGEAIT À L'AVEUGLE. Sa grille ci-dessus contient la
        # catégorie « suite directe de la conversation » — impossible à
        # reconnaître sans savoir ce qui précède. Sur un « 1 » ou un « oui »,
        # il tranchait au hasard ; et s'il concluait à une recherche,
        # `recherche_node` interrogeait la mémoire avec « 1 » pour requête et
        # injectait des extraits sans rapport en tête du message. L'ambiguïté
        # du message court était aggravée au lieu d'être levée.
        + _echange_precedent(state)
        + f"Demande : {question}"
    )

    try:
        reponse = await get_llm(_T.LIGHT).ainvoke([_H(content=invite)])
        trouve = _re.search(r"\{.*\}", str(reponse.content), _re.S)
        decision = _json.loads(trouve.group(0)) if trouve else {}
        besoin = bool(decision.get("memoire"))
        requete = str(decision.get("requete") or "").strip() or question
        # « analyse » fait basculer la rédaction sur le palier COMPLEX, donc sur
        # le modèle de raisonnement. Le défaut reste « simple » : on ne paie le
        # modèle cher que lorsqu'une IA a jugé qu'il le fallait.
        effort = ("complex"
                  if str(decision.get("effort") or "").strip().lower().startswith("analyse")
                  else "standard")
    except Exception as e:  # noqa: BLE001
        # En cas d'échec, on CHERCHE : répondre « je n'ai rien » alors que la
        # mémoire contient la réponse est bien pire qu'une recherche inutile.
        logger.info("Routage indisponible (%s) — recherche par défaut", e)
        besoin, requete, effort = True, question, "standard"

    logger.debug("Routage : mémoire=%s, effort=%s", besoin, effort)
    return {"besoin_memoire": besoin, "requete_memoire": requete, "llm_tier": effort}


async def recherche_node(state: AgentState) -> dict:
    """Exécute la recherche décidée par le routeur, et masque les résultats."""
    import asyncio
    from security.anonymizer import anonymizer
    from vectorstore.rag import retrieve_as_context
    from mail.authorization import boites_par_id

    # Cloisonnement : uniquement les boîtes mail auxquelles cette personne a
    # droit. Sans droits déterminables, aucun mail (fail-closed).
    try:
        boites = await boites_par_id(state.get("user_id"))
    except Exception:  # noqa: BLE001
        boites = []

    trouves = await retrieve_as_context(
        query=state.get("requete_memoire") or state.get("query", ""),
        user_role=state.get("user_role", "terrain"),
        top_k=5,
        mailboxes=boites,
    )
    # On CONSERVE ce qui est déjà là (une pièce jointe masquée en amont) : ce
    # canal est en « dernière valeur », un retour brut l'effacerait.
    deja = list(state.get("anonymized_chunks") or [])
    if not trouves:
        return {"anonymized_chunks": deja}

    # D'OÙ VIENT CE QUE L'ASSISTANT VA DIRE.
    #
    # Chaque extrait porte sa provenance en tête, sous la forme « [nom] »
    # (vectorstore/rag.py:201). Elle servait au modèle et à lui seul : l'écran
    # n'en voyait rien. Or quand l'assistant annonce un montant ou une
    # référence, la première question est « tu as vu ça où ». Sans réponse,
    # il faut le croire sur parole.
    #
    # Le nom de fichier ne divulgue rien : la recherche a DÉJÀ filtré sur le
    # niveau d'accès de la personne (`user_role` plus haut), donc elle avait
    # de toute façon le droit d'ouvrir ces documents. Et cela ne coûte aucun
    # jeton : on n'ajoute rien au prompt, on transmet ce qu'on avait déjà.
    sources: list[str] = []
    for extrait in trouves:
        texte = str(extrait or "")
        if texte.startswith("["):
            nom = texte[1:texte.find("]")] if "]" in texte else ""
            nom = nom.strip()
            if nom and nom not in sources:
                sources.append(nom)

    # Les documents partent vers le modèle : ils doivent être masqués, avec la
    # carte cumulative du fil pour que les jetons restent cohérents.
    masques, carte = await asyncio.to_thread(
        anonymizer.anonymize_chunks, list(trouves), state.get("entity_map") or {})
    return {"anonymized_chunks": deja + masques, "entity_map": carte,
            "sources_memoire": sources}


async def browser_node(state: AgentState) -> dict:
    """Recherche web via DuckDuckGo dans sandbox Daytona — dernier recours si RAG vide."""
    from browser.tools import web_search
    result = await web_search(
        query=state.get("query", ""),
        user_id=state.get("user_id", ""),
        agent_id="agent1",
        max_results=3,
    )
    existing = list(state.get("raw_chunks") or [])
    if result["success"]:
        existing.append(
            "[SOURCE WEB : information externe, à mentionner et valider]\n" + result["content"]
        )
    return {
        "raw_chunks": existing,
        "browser_used": True,
        "browser_sources": result.get("sources", []),
        "browser_content": result.get("content"),
        "browser_was_filtered": result.get("was_filtered", False),
    }


async def llm_node(state: AgentState, config=None) -> dict:
    """Appel LLM (résilient) sur requête/contexte masqués. Le tracing Langfuse est
    propagé depuis le tour complet via `config` (arbre de trace unique)."""
    # Fail-closed RGPD : si l'anonymiseur NER est HS, on NE contacte PAS de LLM
    # externe (noms/adresses/organisations partiraient en clair). On refuse.
    from security.anonymizer import anonymizer
    from config import settings as _settings
    if _settings.block_external_llm_without_ner and not anonymizer.spacy_available:
        return {
            "llm_response": ("Service momentanément indisponible : la protection des données "
                             "(anonymisation) n'est pas opérationnelle, la requête n'a pas été "
                             "envoyée à un modèle externe. Contactez l'administrateur."),
            "model_used": None,
            "error": "ner_unavailable",
        }

    import hashlib
    from optim.tokens import trim_chunks, response_cache
    from skills.protocol import (instruction_actions, rafraichir_catalogue,
                                 BLOC_ACTION_RE, BLOC_NATIF_RE)

    # Le registre de skills en base est rechargé périodiquement (cache interne).
    # Sans cela, le modèle ne connaîtrait que les six skills natifs, alors que
    # l'onglet Skills en montre bien davantage : interrogé sur ce qu'il sait
    # faire, il en oubliait la plus grande partie.
    await rafraichir_catalogue()

    tier = state.get("llm_tier", "standard")
    llm = get_llm(LLMTier(tier))

    chunks = state.get("anonymized_chunks")
    if chunks is None:
        chunks = state.get("raw_chunks") or []
    chunks = trim_chunks(chunks)   # borne le nombre de chunks + le volume de contexte
    context_text = "\n\n---\n\n".join(str(c) for c in chunks) if chunks else ""

    query = state.get("anonymized_query") or state.get("query", "")

    # Historique de conversation (déjà ANONYMISÉ : on ne stocke que du texte masqué),
    # borné en nombre de messages ET en caractères, recalé sur une frontière de paire.
    # MÉMOIRE DE CONVERSATION À TROIS ÉTAGES (agents/memoire_conversation.py) :
    # la fenêtre récente verbatim (large, messages longs taillés), le résumé
    # glissant de ce qui en est sorti, et le rappel vectoriel des échanges
    # anciens proches de la question. `compact_messages` ne donnait que la
    # première, et petite : huit messages, quatre mille caractères.
    from agents.memoire_conversation import (fenetre_recente, fondre_dans_le_resume,
                                             rappeler_echanges, bloc_memoire)
    _tous = state.get("messages") or []
    history, _anciens = fenetre_recente(_tous)
    maj_memoire: dict = {}
    bloc_memoire_txt = ""
    if _anciens:
        _nb = len([m for m in _tous if getattr(m, "type", None) != "system"])
        _premier_rang_fenetre = (_nb - len(history)) // 2 + 1
        # EN PARALLÈLE (31/08) : le résumé glissant est un appel LLM léger, le
        # rappel vectoriel un embedding — indépendants, ils s'additionnaient en
        # série sur le chemin critique du tour.
        import asyncio as _aio_mem
        maj_memoire, _rappels = await _aio_mem.gather(
            fondre_dans_le_resume(state, _tous, _anciens),
            rappeler_echanges(str(state.get("thread_id") or ""), query,
                              _premier_rang_fenetre))
        _resume = maj_memoire.get("resume_conversation") or state.get("resume_conversation")
        bloc_memoire_txt = bloc_memoire(_resume, _rappels)
    # L'AMNÉSIE DOIT SE VOIR DANS LES JOURNAUX.
    #
    # Quand le modèle répond « je ne comprends pas » à un « oui » ou à un « 1 »,
    # rien ne permettait de distinguer un historique ABSENT d'un modèle qui n'a
    # pas su faire le lien. Ces deux causes appellent des correctifs opposés,
    # et on ne peut pas les départager après coup : la trace ne conservait pas
    # la taille de la fenêtre réellement envoyée. Une ligne suffit.
    _brut = len([m for m in (state.get("messages") or [])
                 if getattr(m, "type", None) != "system"])
    if _brut and not history:
        logger.warning("Historique VIDE alors que le fil porte %d messages", _brut)
    else:
        logger.info("Historique : %d messages sur %d, %d caractères",
                    len(history), _brut,
                    sum(len(str(getattr(m, "content", "") or "")) for m in history))

    # Cache exact (palier|requête|contexte anonymisés). La clé DOIT inclure le fil et
    # l'historique : sinon, reposer une question déjà posée renverrait la réponse figée
    # du 1er tour (la mémoire semblerait perdue par intermittence), et deux utilisateurs
    # posant la même question partageraient une réponse conditionnée par la conversation
    # de l'autre. Le thread_id isole par conversation, donc par utilisateur.
    history_sig = hashlib.sha256(
        "\n".join(str(getattr(m, "content", "") or "") for m in history).encode("utf-8")
    ).hexdigest()[:16] if history else ""
    if bloc_memoire_txt:
        history_sig += "|" + hashlib.sha256(bloc_memoire_txt.encode("utf-8")).hexdigest()[:8]
    cache_scope = f"{state.get('thread_id', '')}|{history_sig}"

    # Le cache est COURT-CIRCUITÉ dès qu'une action a été exécutée : la réponse
    # dépend alors d'un effet de bord (contenu d'une boîte, brouillon produit),
    # elle n'est pas rejouable à l'identique.
    en_boucle_outils = bool(state.get("tool_results"))
    if not en_boucle_outils:
        cached = response_cache.get(tier, query, context_text, cache_scope)
        if cached is not None:
            return {"llm_response": cached, "model_used": "cache", "tokens_in": 0, "tokens_out": 0,
                    **maj_memoire}

    # Résultats des actions déjà exécutées ce tour : c'est ce qui permet au modèle
    # de rédiger sa réponse finale à partir de ce que l'outil a réellement produit.
    resultats_outils = state.get("tool_results") or []
    bloc_resultats = ""
    if resultats_outils:
        import json as _json_out
        # CE MESSAGE DISAIT « appuie-toi dessus POUR RÉPONDRE ». À chaque retour
        # de résultat, on invitait donc le modèle à conclure — y compris au
        # milieu d'un travail à peine commencé. Combiné au protocole qui parlait
        # de « ta réponse finale » après UNE action, il n'avait aucune raison de
        # continuer : les deux textes lui disaient de s'arrêter.
        # Le plafond du bloc suit celui des résultats : tronquer ICI à 6000 un
        # schéma que `tools_node` a laissé passer à 12000 reviendrait à
        # déplacer la coupure, pas à la supprimer.
        plafond_bloc = (16000 if any((r.get("skill") or "") in RESULTATS_GENEREUX
                                     for r in resultats_outils) else 6000)
        # `args` ne PART PAS vers le modèle. Il accompagne le résultat pour que
        # l'écran puisse dire sur quoi portait l'action, mais le modèle, lui, a
        # déjà écrit ces arguments : les lui renvoyer serait les payer deux fois,
        # à chaque passage de la boucle. Ce filtre est ce qui rend le « sur quoi »
        # affiché réellement gratuit.
        pour_le_modele = [{c: v for c, v in r.items() if c != "args"}
                          for r in resultats_outils]
        # ON GARDE LES RÉSULTATS LES PLUS RÉCENTS, PAS LES PREMIERS.
        #
        # Tronquer la sérialisation entière par la fin coupait le bout le plus
        # récent : le modèle relisait ses premières actions et perdait celle
        # qu'il venait d'obtenir. Tant que le budget d'actions valait 8, la
        # coupure était rare ; à 40 elle devient la règle — et perdre le dernier
        # résultat est précisément ce qui fait relancer la même action.
        #
        # On empile donc depuis la fin, le plus ancien tombant en premier. Le
        # dernier résultat est gardé même s'il dépasse à lui seul le plafond :
        # mieux vaut un résultat coupé que pas de résultat du tout.
        gardes, taille = [], 0
        for _r in reversed(pour_le_modele):
            _bloc = _json_out.dumps(_r, ensure_ascii=False, default=str)
            if gardes and taille + len(_bloc) > plafond_bloc:
                break
            gardes.append(_r)
            taille += len(_bloc)
        gardes.reverse()

        # L'OUBLI SE DIT. Sans cette phrase, le modèle voit trois résultats là
        # où il en a obtenu douze, et croit devoir relancer les neuf manquants.
        omis = len(pour_le_modele) - len(gardes)
        entete = ("Résultats des actions déjà exécutées pour cette demande (ne les "
                  "relance pas à l'identique)")
        if omis > 0:
            entete += (f" — les {omis} plus anciens ne sont plus détaillés ici, "
                       "mais ils ont bien abouti : ne les refais pas")
        bloc_resultats = (
            entete + " :\n"
            "Résultats des actions déjà exécutées pour cette demande (ne les "
            "relance pas à l'identique) :\n"
            + _json_out.dumps(pour_le_modele, ensure_ascii=False,
                              default=str)[:plafond_bloc]
            + "\n\n")
        # LE TRAVAIL RESTÉ OUVERT SE DIT, il ne se devine pas. `cloture_attendue`
        # lit dans les RÉSULTATS — pas dans la prose — qu'un document a été
        # ouvert sans être fermé. Le lui rappeler ici est le seul rappel qui
        # arrive au bon moment : juste avant qu'il choisisse entre agir et
        # conclure.
        manque = cloture_attendue(resultats_outils)
        if manque:
            # LE CHEMIN QUI DÉPOSE SE DIT ICI. Ne nommer que `terminer_document`
            # poussait vers la fermeture seule : une fois fermée, plus rien
            # n'attendait, et le document demandé « dans /Drive » restait sur
            # le disque de l'assistant. Les deux sorties sont annoncées, avec
            # celle qui répond à une demande de dépôt en premier.
            bloc_resultats += (
                f"ATTENTION : le travail n'est PAS terminé. Il reste au minimum "
                f"`{manque}` à exécuter, et le contenu demandé à verser avant. "
                "Si un DÉPÔT sur le serveur a été demandé (« dans /Drive », "
                "« sur le NAS »), la bonne action de clôture est "
                "`nas_deposer_document` : elle finalise ET dépose en un geste, "
                "et remplace `terminer_document`. "
                "N'écris pas ta réponse finale maintenant : émets l'action suivante.\n\n")

    # UN DOCUMENT RESTÉ OUVERT D'UN TOUR PRÉCÉDENT SE DIT AUSSI.
    # `cloture_attendue` ne lit que les résultats de CE tour : « je continue à
    # verser le contenu dans le document déjà ouvert » — ouvert au tour d'avant
    # — partait donc sans identifiant ni rappel, et le tour s'est terminé sur
    # la promesse. L'atelier, lui, s'en souvient : on lui demande.
    #
    # ET LES TERMINÉS AUSSI. Relevé en production : « test 2 » venait d'être
    # finalisé (38 Ko), et au tour suivant le modèle a répondu « ce document
    # n'existe pas », est parti le chercher sur le serveur, puis a proposé de
    # déposer un document VIDE à sa place. Un document fini sortait de la seule
    # liste que le modèle voyait — le plus important devenait invisible.
    try:
        import asyncio as _aio
        from bureautique.atelier import ouverts as _docs_ouverts
        from bureautique.atelier import termines as _docs_termines
        _uid = str(state.get("user_id") or "")
        en_cours = await _aio.to_thread(_docs_ouverts, _uid)
        finis = (await _aio.to_thread(_docs_termines, _uid))[:5]
    except Exception:  # noqa: BLE001 - un aperçu manquant ne casse pas le tour
        en_cours, finis = [], []
    if en_cours or finis:
        import json as _json_docs
        etat_docs = "ÉTAT DE TES DOCUMENTS (fait autorité, ne le devine jamais) :\n"
        if en_cours:
            etat_docs += (
                "- OUVERTS, non terminés (aucun fichier n'existe encore) :\n"
                + _json_docs.dumps(en_cours, ensure_ascii=False)
                + "\n  Ce sont TES documents pour les demandes en cours : "
                  "continue-les avec `ajouter_document` puis "
                  "`terminer_document`, en recopiant CE `document_id` caractère "
                  "pour caractère et SANS réécrire ce qui est déjà versé (le "
                  "compte d'éléments fait foi). N'en rouvre pas un du même "
                  "titre. Ne les jette JAMAIS de ta propre initiative, même si "
                  "la demande dit « nouveau » : un document déjà ouvert sous ce "
                  "titre EST le document demandé.\n")
        if finis:
            etat_docs += (
                "- TERMINÉS, fichier PRÊT et téléchargeable, mais PAS déposé "
                "sur le serveur :\n"
                + _json_docs.dumps(finis, ensure_ascii=False)
                + "\n  Ces documents ne se trouvent PAS en cherchant sur le "
                  "serveur : ils vivent ici, avec leur `document_id`. Titre, "
                  "taille, éléments et pages_estimees ci-dessus répondent "
                  "directement aux questions dessus.\n")
        bloc_resultats += etat_docs + "\n"

    # Aucun préambule sur l'absence de documents : c'est le modèle qui décide
    # s'il lui en faut, en appelant l'outil de recherche. Lui annoncer d'office
    # « aucun document » l'amenait à en parler même pour un simple bonjour.
    human_content = f"Date et heure actuelles : {_maintenant()} (Europe/Paris).\nQuestion : {query}"
    if context_text:
        human_content = f"Documents disponibles :\n{context_text}\n\n{human_content}"
    # Résultats d'un tour précédent dont la rédaction avait échoué : on les
    # remet sous les yeux du modèle UNE fois, au tour qui suit, pour que
    # « présente le résultat » ou « continue » puissent être tenus.
    en_attente = state.get("resultats_en_attente") or []
    if en_attente and not resultats_outils:
        import json as _json_att
        bloc_attente = (
            "RÉSULTATS DU TOUR PRÉCÉDENT, obtenus mais JAMAIS RESTITUÉS à l'utilisateur "
            "(la rédaction avait échoué). Si la demande s'y rapporte — « présente le "
            "résultat », « montre », « continue », ou la même question — restitue-les "
            "MAINTENANT, complètement, sans relancer les actions :" + chr(10)
            + _json_att.dumps(en_attente, ensure_ascii=False, default=str)[:8000] + chr(10) * 2)
        bloc_resultats = bloc_attente + bloc_resultats
    human_content = bloc_memoire_txt + bloc_resultats + human_content

    # Composants visuels : l'instruction est TOUJOURS présente.
    # Elle était auparavant conditionnée à des mots-clés (« devis », « tableau »…) pour
    # économiser ~340 tokens. Mauvais calcul, à deux titres :
    #   1. l'heuristique ratait l'essentiel des demandes — « lis les derniers mails »
    #      ne contient aucun mot-clé, donc le modèle ignorait jusqu'à l'existence des
    #      composants, et répondait en texte brut ;
    #   2. un préfixe système qui change d'un tour à l'autre DÉTRUIT le cache de prompt,
    #      dont l'entrée est facturée jusqu'à ~100× moins cher qu'un appel non caché.
    #      Un préfixe stable coûte donc moins que l'alternance qu'il évitait.
    system_prompt = SYSTEM_PROMPT + """

COMPOSANTS VISUELS. Dès que tu présentes des DONNÉES concrètes (mail, devis, facture, document, liste, tableau, indicateur, avancement, suggestions d'actions...), intercale un composant : insère au milieu de ta réponse un bloc balisé ```ui contenant un objet JSON, et rédige le texte normalement autour. Un composant vaut mieux qu'un paragraphe pour tout ce qui est structuré. Règle absolue : n'invente jamais de valeurs ; remplis TOUS les champs requis, sinon reste en texte simple (un composant incomplet ne s'affiche pas). Types :
- {"type":"email","subject":"...","from":"...","date":"...","preview":"..."}
- {"type":"quote","id":"...","client":"...","status":"draft|sent|accepted","total":"...","lines":[{"label":"...","qty":"...","price":"..."}]} devis RÉSUMÉ, quand tu le cites. Pour MONTRER un devis complet, même type, forme longue : ajoute "emetteur","reference","date","objet","adresse":["...","..."],"suivi_par","totals":{"ht":"...","tva":"...","taux":"20 %","ttc":"..."},"footer":"...","mentions":["..."] et écris les lignes ainsi : [{"section":"LOT 1 — TERRASSEMENTS"},{"n":1,"description":"...","unite":"m²","qte":"250","pu":"3,40 €","montant":"850,00 €"}]. TOUT le devis tient dans CE SEUL bloc — en-tête, lots, lignes, totaux, conditions. N'écris jamais un devis en tableau markdown ni en morceaux séparés.
- {"type":"invoice","number":"...","client":"...","amount":"...","issued":"...","due":"...","status":"paid|pending|late"}
- {"type":"doc","name":"...","kind":"PDF|XLSX|DOCX","meta":"..."}
- {"type":"doc_apercu","titre":"...","format":"docx|pdf|xlsx","extrait":"..."} pour l'aperçu d'un document QU'ON A LU et qui n'est pas téléchargeable. Un document que TU viens de produire ou de déposer s'annonce par un bloc `fichier` et par lui seul : sa carte montre déjà le document. Ici : `extrait` reprend TEL QUEL le champ `extrait` (document produit) ou le début du `contenu`/`texte` rendu par la lecture. Jamais un résumé réécrit : l'aperçu montre le VRAI contenu.
- {"type":"site","url":"...","titre":"...","apercu":"..."} pour MONTRER une page web que tu viens de lire : `ouvrir_page` te donne `apercu` (une clé) et `titre` — recopie-les tels quels, l'écran affiche la capture de la page avec son lien.
- {"type":"contact","name":"...","role":"...","phone":"...","email":"..."}
- {"type":"project","name":"...","client":"...","progress":62,"status":"..."}
- {"type":"table","columns":["...","..."],"rows":[["...","..."]]}
- {"type":"keyvalue","rows":[["Clé","Valeur"]]}
- {"type":"list","items":["...","..."]}
- {"type":"callout","tone":"info|success|warning|error","title":"...","text":"..."}
- {"type":"bars","data":[{"label":"...","value":10}]} barres verticales, pour COMPARER quelques valeurs.
- {"type":"hbars","data":[{"label":"...","value":10}],"unit":"€"} barres horizontales : le meme classement quand les libelles sont longs (noms de fournisseurs, de chantiers). `unit` s'affiche apres chaque valeur.
- {"type":"donut","segments":[{"label":"...","value":45}]} anneau, pour une REPARTITION dont le total fait un tout (postes d'un budget, part de chaque corps d'etat). N'indique JAMAIS de couleur : elles viennent de la charte du client.
- {"type":"line","values":[12,19,15,27]} courbe, pour une EVOLUTION dans le temps. Les valeurs sont dans l'ordre chronologique.
- {"type":"gauge","value":68,"label":"..."} jauge de 0 a 100, pour un TAUX unique (marge, avancement, taux de remplissage).
- {"type":"progress","items":[{"label":"...","pct":72}]} plusieurs avancements compares, en pourcentage.
- {"type":"status_table","columns":["...","...","Statut"],"rows":[{"cells":["...","..."],"status":"ok|wait|late"}]} tableau dont la derniere colonne est une PASTILLE d'etat. `cells` ne contient PAS le statut, il est rendu a partir de `status`. Prefere-le au tableau simple des qu'une ligne a un etat (livree, en attente, en retard).
- {"type":"stat","label":"...","value":"...","hint":"..."}
- {"type":"badge","tone":"primary|success|warning|error|neutral","text":"..."}
- {"type":"quick_replies","options":["Proposition 1","Proposition 2"]}
- {"type":"reponses_mail","reponses":[{"ref":"...","de":"...","objet":"...","synthese":"...","reponse":"..."}]} LES RÉPONSES PROPOSÉES à plusieurs mails, en cartes cochables avec un envoi groupé : une entrée par message qui appelle une réponse, `ref` recopiée telle que la lecture l'a rendue, `synthese` = une ou deux phrases sur ce que le mail REÇU demande (tirées du message, jamais inventées — c'est le contexte qui permet de juger la réponse), `reponse` prête à partir. C'est une PROPOSITION : rien ne part sans l'accord habituel. Ne double pas ce bloc avec des cartes `email`.
- {"type":"plan","titre":"...","etapes":[{"titre":"...","etat":"fait|en_cours|a_faire","resultats":["ce que l’étape a donné"]}]} pour une demande à plusieurs livrables : annonce le plan dès ta PREMIÈRE réponse, puis redonne-le à jour chaque fois que tu rends compte. Sous une étape franchie, écris ce qu’elle a DONNÉ — constats, chiffres, décisions — jamais « fait », et jamais « fait » sur une étape que tu n’as pas menée.

DOCUMENTS. Un cahier des charges, un rapport, un compte rendu, une note, un mémoire technique, une procédure, un courrier ne s’écrivent NI en bloc ```ui NI en markdown : ils se PRODUISENT en fichier Word, format par défaut sauf demande contraire. « Montre-le-moi dans le chat » veut dire : produis-le et laisse son bloc `fichier` en afficher l’aperçu.
- QUEL GESTE : `produire_document` finalise en une fois et plafonne vers 2-3 pages — réserve-le à une note ou un courrier. Pour un document long : `creer_document`, un `ajouter_document` par grande partie, puis `terminer_document`.
- NE LE REFAIS PAS : avant `creer_document`, relis les résultats de ce tour ; si un `terminer_document` y figure pour ce document, il est FINI — tu as son `url` et son `titre`, sers-t’en. S’il te paraît incomplet, dis ce qui manque plutôt que de le recréer.
- NE RESSERS PAS UN VIEUX LIEN : une adresse /api/documents/... émise lors d’un tour PRÉCÉDENT est périmée et donne une carte qui ne s’ouvre pas. Seul un document produit dans CE tour-ci s’annonce.
- SUR LE MÊME MODÈLE : quand on te demande de suivre des documents existants, tu viens de les lire — reprends leur structure (titres, ordre, numérotation), leurs formulations types, leurs mentions d’en-tête et de pied. C’est la ressemblance qu’on attend, pas un meilleur plan.

LE WEB, QUAND IL FAUT. `chercher_web`, `ouvrir_page` et `naviguer` existent : ne réponds jamais que tu ne peux pas accéder à internet. Mais ils servent à l'information PUBLIQUE (prix public, norme, fournisseur, contenu d'un site) ou à ce que l'utilisateur te demande d'aller voir, jamais aux données de l'entreprise (voir OÙ EST CHAQUE DONNÉE). Si une page ne rend rien d'exploitable — site qui n'affiche rien sans JavaScript, bannière de cookies, information à plusieurs clics —, PASSE À `naviguer` : il voit la page et clique comme le ferait un humain. Il est lent, garde-le pour ces cas-là.

SUGGESTIONS. Termine par `quick_replies` (2 ou 3 options) quand TU vois une suite précise que l’écran ne devinerait pas — « Chiffre la variante en pierre naturelle », « Relance le devis de mars ». Sinon n’en écris pas : une suite générique est ajoutée toute seule. Jamais une question dans une pastille.

SCHEMAS. Pour un enchainement d'etapes, une arborescence, un organigramme ou un circuit de validation, ecris un bloc ```mermaid (PAS ```ui, ce n'est pas un composant : c'est un dessin). Le schema se dessine aux couleurs du client, tu n'as donc aucune couleur ni aucun style a indiquer, seulement la structure. Exemple :
```mermaid
flowchart LR
  A[Demande recue] --> B{Devis existant ?}
  B -- oui --> C[Mise a jour]
  B -- non --> D[Redaction]
  C --> E[Validation]
  D --> E
```
Reserve-le a ce qu'un dessin explique mieux qu'une phrase. Une simple liste d'etapes se rend avec `list`, une repartition avec `donut` : un schema pour trois puces est plus lourd a lire que les puces.
Exemple, pour présenter des mails : une carte PAR message.
Voici les messages trouvés :
```ui
{"type":"email","subject":"CONTACT architecte","from":"lb@lbbl-architectes.fr","date":"23/07/2026","preview":"Demande d'intervention sur un projet a Sainte-Eulalie..."}
```""" + instruction_actions(state.get("user_role"))

    # CONSIGNES APPRISES, injectees a CHAQUE tour et non cherchees. Une regle de
    # comportement (« chez nous "le serveur" designe le NAS ») doit etre presente
    # AVANT que le modele choisisse son action : rangee en memoire, elle serait
    # retrouvee par ressemblance, donc parfois — et une regle qui vaut une fois
    # sur deux est pire qu'une regle absente.
    from learning.consignes import texte_injecte
    system_prompt += await texte_injecte(state.get("user_id"), state.get("user_role"))
    # LE PORTRAIT DE LA PERSONNE, juste après ses consignes — et l'ordre n'est
    # pas neutre : une consigne est un ORDRE qu'elle a donné, le portrait n'est
    # qu'une OBSERVATION. Si les deux se contredisent, c'est l'ordre qui doit
    # avoir été lu en premier et qui prime. Vide tant qu'aucune passe de nuit
    # n'a tourné, ou si la personne a refusé d'être observée.
    from learning.profil_utilisateur import texte_injecte as portrait
    system_prompt += await portrait(state.get("user_id"))
    # Les références d'images du fil, pour que « retouche celle-là » soit une
    # action possible sans fouille de l'historique (voir cles_images_du_fil).
    system_prompt += _consigne_images(state)
    # Le plan approuvé prime sur tout le reste : c'est le contrat du tour.
    system_prompt += _consigne_plan(state)

    # Il y avait ici un rappel « ATTENTION, tu as annoncé sans exécuter »,
    # ajouté quand `relance_annonce` était levé. RETIRÉ, pour deux raisons.
    # D'abord il ne servait à rien : les traces montrent le rappel bien présent
    # dans le prompt, et le modèle annonçant quand même. Ensuite il est devenu
    # inatteignable — le drapeau n'est plus levé que par `forcer_action_node`,
    # qui va vers `tools` ou termine le tour, jamais vers une nouvelle passe de
    # ce nœud. Un garde-fou qui ne s'exécute pas rassure sans protéger : c'est
    # déjà ce qui avait rendu la première détection d'annonce si difficile à
    # débusquer. La reprise se fait maintenant dans un appel dédié.

    # Drapeau de la seconde passe de rédaction, posé plus bas et renvoyé avec
    # la réponse : c'est lui qui borne la reprise à UNE fois. Il est COLLANT
    # dans le tour : posé par `rediger_node` ou par une passe précédente, il
    # ne retombe pas — sinon ce nœud, qui le RÉÉCRIT à chaque passage,
    # l'effaçait et la reprise n'était plus bornée. `runtime` le remet à
    # zéro au début de chaque tour.
    redaction_a_reprendre = bool(state.get("redaction_forcee"))

    # Dernière passe imposée : la boucle d'actions est close, il ne reste qu'à
    # rédiger. Sans cette consigne, le modèle peut redemander une action, dont
    # le bloc serait retiré à l'affichage — donc une réponse vide.
    if state.get("tools_finished"):
        system_prompt += ("\n\nLa phase d'actions est TERMINÉE pour ce tour : n'émets plus "
                          "aucun bloc ```action. Rédige maintenant ta réponse finale à "
                          "partir des résultats ci-dessus.")
        # SECONDE PASSE : la première a rendu une PROMESSE au lieu du contenu.
        # On ne répète pas la même consigne, on NOMME le défaut — répéter à
        # l'identique obtient à l'identique.
        _precedente = state.get("llm_response") or ""
        # La note d'un point d'étape explique déjà la situation : y ajouter
        # « ta réponse ne contenait aucun texte » serait faux et déroutant.
        if not _texte_visible(_precedente) and not state.get("note_sortie"):
            # RIEN QU'UN BLOC D'ACTION, DONC RIEN. La phase d'actions est close :
            # en émettre un de plus ne l'exécutera pas, il sera simplement
            # retiré avant l'affichage et la réponse sera vide. C'est ce qui a
            # coûté trente et une minutes de travail abouti en production.
            redaction_a_reprendre = True
            system_prompt += (
                "\n⚠ Ta réponse précédente ne contenait AUCUN texte : seulement un "
                "bloc d'action. La phase d'actions est TERMINÉE pour ce tour — un "
                "bloc de plus ne sera pas exécuté, il sera retiré, et l'utilisateur "
                "verra une réponse vide. Écris maintenant une VRAIE réponse en "
                "français : ce que tu as fait, ce que tu as trouvé, et les documents "
                "produits avec leur bloc `fichier`. Aucun bloc d'action.")
        elif est_une_annonce(_precedente) or promesse_sans_suite(_precedente):
            redaction_a_reprendre = True
            system_prompt += (
                "\n⚠ Ta réponse précédente ANNONÇAIT le travail au lieu de le livrer "
                "(« je vais… », « voici ce que je lance… »). L'utilisateur ne voit QUE "
                "cette phrase, et rien d'autre : pour lui, tu n'as rien produit. "
                "Écris MAINTENANT le contenu lui-même, en entier, dans ta réponse. "
                "N'annonce rien, ne décris pas ce que tu vas faire.")
        elif _reponses_mail_manquantes(state, _precedente):
            # LA MOITIÉ D'UNE DEMANDE N'EST PAS UNE RÉPONSE (01/09) : la
            # synthèse est arrivée, les propositions de réponse jamais.
            redaction_a_reprendre = True
            system_prompt += (
                "\n⚠ La demande réclamait AUSSI une PROPOSITION DE RÉPONSE pour "
                "chaque message qui en appelle une : ta réponse précédente n'en "
                "portait aucune. Reprends ta synthèse telle quelle et ajoute à la "
                "fin UN bloc ```ui reponses_mail — une carte par message qui "
                "appelle une réponse (ref, de, objet, synthese, reponse), aucune "
                "pour les messages automatiques. N'envoie rien : chaque envoi "
                "repassera par sa validation.")
        # La raison d'une sortie sans résultat est expliquée par le modèle, dans
        # ses mots : l'utilisateur mérite une phrase, pas un code d'erreur.
        note = state.get("note_sortie")
        if note:
            system_prompt += (
                f"\nContexte : {note} Explique-le simplement à l'utilisateur, en une "
                "phrase, et propose une suite utile. Ne recopie pas cette note telle "
                "quelle et n'affiche aucune parenthèse technique.")

    # [système] + [historique masqué] + [tour courant] : c'est ce qui donne la mémoire.
    messages = [SystemMessage(content=system_prompt)] + list(history) + [
        HumanMessage(content=human_content)
    ]
    response = await llm.ainvoke(messages, config=config)

    # Ne JAMAIS mettre en cache une réponse qui demande une action : son contenu
    # utile n'est pas la réponse mais l'action, et la resservir sauterait
    # l'exécution. Idem après une action : le résultat n'est pas rejouable.
    _sortie = str(response.content or "")
    if (not en_boucle_outils and not BLOC_ACTION_RE.search(_sortie)
            and not BLOC_NATIF_RE.search(_sortie)):
        response_cache.set(tier, query, context_text, response.content, cache_scope)

    usage = getattr(response, "usage_metadata", None) or {}
    return {
        **maj_memoire,
        "redaction_forcee": redaction_a_reprendre,
        "llm_response": response.content,
        "tokens_in": usage.get("input_tokens", 0),
        "tokens_out": usage.get("output_tokens", 0),
        "model_used": llm.last_model_used,
        # L'historique n'est PLUS émis ici mais dans `rehydrate_node` : avec la
        # boucle d'outils, ce nœud s'exécute plusieurs fois par tour et ajouterait
        # autant de paires — les réponses intermédiaires (blocs action) pollueraient
        # la mémoire de conversation.
        # Jetons réellement PRÉSENTS dans ce qui a été envoyé au modèle ce tour-ci.
        # La réhydratation sera restreinte à cet ensemble : la map étant cumulative,
        # réhydrater aveuglément permettrait au modèle de ressortir un [PER_n] d'un
        # tour sans rapport et d'y réinjecter une vraie valeur (donnée fausse dans un
        # contexte faux — exactement la classe de bug qu'on répare ici).
        "turn_placeholders": sorted(
            anonymizer.find_placeholders(human_content).union(
                *[anonymizer.find_placeholders(str(getattr(m, "content", "") or ""))
                  for m in history] or [set()]
            )
        ),
    }


async def tools_node(state: AgentState, config=None) -> dict:
    """Exécute UNE action demandée par le modèle, puis lui rend la main.

    Un seul outil par passage : la boucle repasse par `llm` entre chaque action.
    Cela borne le raisonnement, rend chaque étape visible dans le streaming, et
    évite qu'un effet de bord ne soit produit avant une éventuelle suspension.

    Les actions à effet EXTERNE ne sont jamais exécutées ici : elles arment le
    `human_gate` du graphe parent, qui suspend le tour jusqu'à décision humaine.
    """
    import asyncio
    import json as _json

    from security.anonymizer import anonymizer
    from skills.protocol import extraire_action
    from skills.executor import execute_skill, hash_payload, SkillError, effet_du_skill, expert_du_skill
    from tasks.identity import charger_executant

    # Le rôle est transmis pour que la vue qui VALIDE soit exactement celle
    # qui a été ANNONCÉE au modèle. Un écart entre les deux se lirait comme
    # une fuite : un skill hors périmètre deviendrait appelable.
    action, texte, erreur = extraire_action(
        state.get("llm_response") or "", state.get("user_role"))
    iteration = (state.get("tool_iterations") or 0) + 1
    resultats = list(state.get("tool_results") or [])

    def _sortir(note: str | None = None) -> dict:
        """Termine la boucle, en garantissant qu'une VRAIE réponse sera rédigée.

        Le contrat de la boucle est : le modèle demande une action, puis rédige
        au vu de son résultat. Si l'on sort sans qu'aucun résultat ne lui soit
        jamais revenu, son dernier texte est par construction une parole
        d'AVANT l'action — « Je vais d'abord chercher... » — et non une réponse.
        Observé en production : des tours entiers réduits à cette annonce, ou à
        la note du garde-fou toute seule.

        On force donc une dernière passe de rédaction, en lui transmettant la
        raison de la sortie pour qu'il l'explique lui-même plutôt que de coller
        une note technique à l'utilisateur. La passe est bornée : `tools_finished`
        étant posé, `route_apres_llm` ira en réhydratation quoi qu'il produise.
        """
        corps = (texte or "").strip()
        # UNE NOTE NE S’AFFICHE JAMAIS TELLE QUELLE. La branche qui gardait le
        # corps COLLAIT la note dessous, verbatim — et l’utilisateur a lu
        # « les dernières actions tentées ont toutes échoué ; inutile
        # d’insister sur la même voie. » sous une annonce d’exploration.
        # C’est exactement ce que la docstring ci-dessus promettait d’éviter,
        # mais la promesse ne couvrait qu’une branche sur deux. Dès qu’il y a
        # une note, la rédaction est forcée : le modèle explique, dans ses
        # mots, avec les erreurs sous les yeux.
        if note or not resultats or not corps:
            if note:
                logger.info("Sortie de boucle sans aboutissement (%s) — rédaction forcée", note)
            return {"tool_results": resultats, "llm_response": "",
                    "tools_finished": True,
                    "tool_iterations": iteration, "note_sortie": note}
        # `tool_results` EST RENVOYÉ, toujours. Aux points de sortie
        # d'origine la liste valait déjà celle de l'état, si bien que
        # l'omission ne se voyait pas ; appelée APRÈS l'exécution d'une
        # action, elle aurait effacé son résultat — et le modèle, ne le
        # voyant plus, aurait refait le geste. C’est le double devis
        # relevé en production.
        return {"tool_results": resultats, "llm_response": corps,
                "tools_finished": True, "tool_iterations": iteration}

    if erreur:
        # Bloc mal formé : on renvoie l'erreur au modèle pour qu'il se corrige,
        # mais un nombre BORNÉ de fois — sinon deux modèles têtus boucleraient
        # à l'infini.
        #
        # DEUX PLUTÔT QU'UNE. Relevé en production le 14/08 : deux sorties
        # coupées d'affilée sur le même tour (le modèle a réessayé aussi long).
        # La première armait la reprise, la seconde terminait le tour — après
        # dix minutes de rédaction, sans rien avoir versé. Corriger un volume
        # demande parfois deux essais ; chacun coûte un appel, et le plafond
        # reste franc.
        reparations = int(state.get("tool_repair_used") or 0)
        if reparations >= MAX_REPARATIONS_PAR_TOUR:
            return _sortir("le modèle n'a pas réussi à produire une action "
                           "exploitable, même après correction.")
        resultats.append({"skill": None, "ok": False,
                          "resultat_masque": f"ERREUR : {erreur}."})
        return {"tool_results": resultats, "tool_iterations": iteration,
                "tool_repair_used": reparations + 1}

    if action is None:
        return _sortir()

    if iteration > MAX_ACTIONS_PAR_TOUR:
        # Formulé comme une RAISON, pas comme un texte à afficher : c'est le
        # modèle qui la met en mots pour l'utilisateur.
        #
        # Le mot RECHERCHES était faux : le budget porte sur les ACTIONS, quelles
        # qu'elles soient. Sur une demande de document, l'utilisateur lisait
        # « le nombre de recherches autorisées est atteint » alors qu'aucune
        # recherche n'avait eu lieu — un message qui égare au lieu d'expliquer.
        return _sortir("le nombre d'actions autorisées pour ce tour est atteint "
                       "sans que la demande ait abouti.")

    # Les paramètres arrivent masqués (le modèle ne voit que du texte anonymisé).
    # On les réhydrate avec TOUTE la carte du fil, pas la seule fenêtre du tour.
    # La borne `turn_placeholders` protège l'AFFICHAGE (ne pas montrer une entité
    # d'un autre contexte) ; un paramètre d'action ne s'affiche pas, il s'exécute
    # — et tout jeton de la carte a été réellement émis dans CE fil, un jeton
    # inventé n'y figure pas et reste tel quel. Relevé le 29/08 : l'adresse tapée
    # par l'utilisateur devenait un jeton mort dès que la fenêtre glissait, et
    # l'assistant la redemandait en boucle.
    carte = dict(state.get("entity_map") or {})
    args = {k: (anonymizer.rehydrate(v, carte) if isinstance(v, str) else v)
            for k, v in action["args"].items()}

    # UN TEXTE LONG NE SE RECOPIE PAS DANS UNE ACTION (03/09).
    #
    # Une transcription de réunion fait 40 000 à 60 000 caractères. Demander au
    # modèle de la réécrire dans son bloc ```action, c'est la lui faire payer
    # deux fois — et surtout la voir RACCOURCIE : un modèle qui doit recopier
    # un mur de texte en garde le début et la fin. Le compte rendu porterait
    # alors sur la moitié de la réunion sans que rien ne le dise.
    #
    # Le modèle écrit donc le jeton `@message`, et c'est le serveur qui met à
    # sa place le message de l'utilisateur — il l'a en entier, lui. Même esprit
    # que `@moi` pour l'adresse de la session : ce que le serveur sait, on ne
    # le fait pas transiter par le modèle.
    #
    # AVANT l'empreinte, jamais après : ce qui est haché doit être ce qui
    # s'exécute, sinon la garantie « ce qui est validé est ce qui part » tombe.
    args = {k: ((state.get("query") or "") if _est_jeton_message(v) else v)
            for k, v in args.items()}
    # MÊME LOGIQUE POUR UN TABLEAU JOINT : les lignes du fichier (ou du dernier
    # fichier tabulaire de la conversation) remplacent le jeton. Sans tableau
    # connu, le jeton reste tel quel et le skill dira ce qui manque.
    tableau = state.get("dernier_tableau") or {}
    if isinstance(tableau, dict) and tableau.get("lignes"):
        args = {k: (list(tableau["lignes"]) if _est_jeton_tableau(v) else v)
                for k, v in args.items()}

    empreinte = hash_payload(action["skill"], args)
    # Une page de plus ne compte pas : enchaîner les pages est le comportement
    # DEMANDÉ (TOUT SIGNIFIE TOUT), pas une boucle.
    memes = sum(1 for r in resultats
                if r.get("skill") == action["skill"]
                and not _est_une_page_de_plus(r.get("args"), action.get("args")))
    if memes >= MAX_APPELS_MEME_SKILL and action["skill"] not in SKILLS_SANS_PLAFOND:
        return _sortir(f"l'action « {action['skill']} » a déjà été appelée {memes} fois "
                       "ce tour sans que la demande aboutisse : elle ne donnera pas "
                       "davantage, il faut répondre avec ce qui a été obtenu.")
    deja = [r for r in resultats if r.get("payload_hash") == empreinte]
    if deja:
        # UNE ACTION QUI A ÉCHOUÉ NE RÉUSSIRA PAS EN LA REDEMANDANT TELLE QUELLE.
        #
        # Relevé sur les deux projets, le même jour : « il y a combien de
        # fichiers dans le dossier ? » → l'outil refuse (aucun périmètre
        # configuré) → le modèle redemande à l'identique → le garde-fou
        # s'arme, et l'utilisateur reçoit « l'action a été redemandée à
        # l'identique sans que la demande avance ». Une note technique sur la
        # MÉCANIQUE, à la place de la seule chose qui l'intéressait : POURQUOI
        # ça n'a pas marché.
        #
        # On sort donc dès la première répétition quand l'original a échoué, et
        # on remonte SA raison. Le modèle la met en mots ; l'utilisateur
        # apprend qu'il manque une configuration, au lieu de croire que
        # l'assistant tourne en rond.
        if not deja[0].get("ok"):
            raison = str(deja[0].get("resultat_masque") or "").strip()
            return _sortir(f"l'action « {action['skill']} » a échoué et redonnerait "
                           f"le même résultat : {raison[:400]}")
        # DEUXIÈME REDEMANDE IDENTIQUE : le tour n'avance plus. Insister ne peut
        # rien produire de neuf — la réponse serait la même — et chaque passe
        # coûte un appel de modèle. On arrête et on dit pourquoi.
        if len(deja) >= 2:
            return _sortir(f"l'action « {action['skill']} » a été redemandée à "
                           "l'identique sans que la demande avance.")
        # Le modèle redemande la même action : on ressert son RÉSULTAT plutôt que
        # de la rejouer. Il contenait auparavant « (déjà exécuté ce tour) » et
        # rien d'autre — or c'est justement là que se trouvait l'identifiant du
        # document dont le modèle avait besoin. On lui reprenait l'information au
        # moment précis où il la redemandait.
        resultats.append({**deja[0], "resultat_masque":
                          "(déjà exécuté à ce tour, son résultat est inchangé)\n"
                          + str(deja[0].get("resultat_masque") or "")})
        return {"tool_results": resultats, "tool_iterations": iteration}

    # L'EFFET SE DEMANDE À L'AUTORITÉ, il ne se lit pas dans une table.
    #
    # Ce nœud interrogeait `EFFETS_NATIFS` en direct. Quand les skills du NAS et
    # de la bibliothèque d'outils sont passés au registre, ils ont quitté cette
    # table — et `.get(nom, "externe")` les a donc TOUS classés en effet externe.
    # Résultat : lister un dossier demandait une validation humaine, et la
    # bibliothèque entière devenait inutilisable. Rien ne le signalait : le
    # défaut de sécurité est verrouillant, donc silencieux.
    #
    # `effet_du_skill` est le seul endroit qui connaît les deux sources (table
    # du socle, puis registre du projet) et garde le même défaut fail-closed.
    # UN PLAN VALIDÉ NE SE REPLANIFIE PAS. Sans ce garde, le modèle pouvait
    # reproposer un plan à chaque reprise : une deuxième carte d'accord pour le
    # travail qu'on venait justement d'autoriser, et un aller-retour de plus à
    # chaque clic. On refuse mécaniquement, et on le dit dans les termes du
    # travail en cours plutôt que par un refus sec.
    if action["skill"] == "proposer_plan" and state.get("plan_valide"):
        resultats.append({
            "skill": action["skill"], "ok": False, "payload_hash": empreinte,
            "resultat_masque": ("Le plan est DÉJÀ validé par l'utilisateur : "
                                + " ; ".join(state.get("plan_valide") or [])
                                + ". N'en propose pas un autre, exécute celui-là."),
        })
        return {"tool_results": resultats, "tool_iterations": iteration}

    effet = effet_du_skill(action["skill"])
    if effet == "externe":
        # JAMAIS exécuté ici. On arme la validation humaine du graphe parent.
        armement = {
            "llm_response": texte or f"Action « {action['skill']} » en attente de validation.",
            "pending_action": {"skill": action["skill"], "args": args,
                               "effet": effet, "payload_hash": empreinte},
            "requires_validation": True,
            "validation_reason": f"Action à effet externe : {action['skill']}",
            "validation_payload": {"skill": action["skill"], "args": args,
                                   "payload_hash": empreinte},
            "tools_finished": True, "tool_iterations": iteration,
        }
        # L'ATTRIBUTION D'ÉCRAN SUIT LE TRAVAIL, PAS LE GRAPHE. Un tirage de
        # visuel s'exécute ici, dans agent1 — mais c'est un travail de
        # conception : la demande d'accord, le tableau de bord et l'historique
        # doivent le porter au crédit de l'expert que le skill déclare. Posé
        # dès l'ARMEMENT, pour que la carte d'accord nomme le bon expert.
        exp = expert_du_skill(action["skill"])
        if exp:
            armement["target_agent"] = exp
        apercu = _apercu_avant_accord(action["skill"], args, texte)
        if apercu:
            armement["llm_response"] = apercu
        return armement

    # Identité RECHARGÉE au moment d'agir : un compte désactivé entre-temps ne
    # doit plus rien pouvoir faire, même si le tour a commencé avant.
    utilisateur = await charger_executant(state.get("user_id"))
    if utilisateur is None:
        return _sortir("ce compte n'est plus actif, aucune action n'a pu être exécutée.")

    try:
        # UNE PHOTO JOINTE NE SE RÉINVENTE PAS (01/09). « Simulation
        # avant/après, garde tout le reste à l'identique » sur une photo du
        # fil → le modèle appelait l'ESSAI depuis un brief TEXTE : le moteur
        # d'images n'a jamais VU la photo, et rend une AUTRE maison qui
        # ressemble. Quand le fil porte une image et que la demande dit de la
        # garder, l'essai et le tirage depuis un texte sont REFUSÉS : le refus
        # nomme la voie (modifier_visuel, avec la clé de l'image), et le
        # modèle se corrige au tour de boucle suivant.
        if (action["skill"] in ("tester_visuel", "generer_visuel")
                and not (args.get("image") or args.get("cle_image"))):
            from agents.annonce import demande_de_garder_la_photo
            cles = cles_images_du_fil(state)
            if cles and demande_de_garder_la_photo(state.get("query") or ""):
                raise SkillError(
                    "cette demande RETOUCHE une photo du fil (« à l'identique », "
                    "avant/après) : un essai depuis un brief texte réinventerait "
                    "une AUTRE maison. Appelle `modifier_visuel` avec "
                    f'image="{cles[-1]}" et la liste des changements demandés.')
        brut = await execute_skill(
            action["skill"], args, user=utilisateur,
            trigger={"type": state.get("trigger_kind") or "chat",
                     "id": state.get("thread_id")},
        )
        sortie = brut.get("output")
        # LE BLOC GARANTI NE PASSE PAS PAR LA COUPE (01/09). Le résultat est
        # tranché pour le modèle ; or un tableau de 40 lignes ou 40 cartes de
        # publipostage pèse 12 000 à 14 000 caractères et tombe au milieu de ce
        # JSON. `_blocs_garantis` ne sait alors plus le relire, et l'écran
        # n'affiche RIEN — sans la moindre erreur, alors que le skill a réussi
        # et que sa consigne interdit au modèle de recopier le contenu. On met
        # donc le bloc DE CÔTÉ avant de couper, et on le masque à part.
        bloc_garanti = (sortie.get("bloc_ui")
                        if isinstance(sortie, dict) and sortie.get("bloc_garanti")
                        else None)
        plafond = (PLAFOND_RESULTAT_GENEREUX
                   if action["skill"] in RESULTATS_GENEREUX else PLAFOND_RESULTAT)
        contenu = _json.dumps(sortie, ensure_ascii=False, default=str)[:plafond]
        ok = True
    except SkillError as e:
        contenu, ok, bloc_garanti = f"ERREUR : {e}", False, None
    except Exception as e:  # noqa: BLE001 - inclut le 403 de verifier_acces
        contenu, ok, bloc_garanti = f"ERREUR : {getattr(e, 'detail', None) or e}", False, None

    # Le résultat repart vers le modèle : il doit être masqué, avec la carte
    # cumulative du fil pour que les jetons restent cohérents.
    # Le bloc garanti est masqué DANS LE MÊME APPEL : une carte de jetons
    # séparée ferait diverger [PER_1] du texte et du bloc.
    masques, carte_maj = await asyncio.to_thread(
        anonymizer.anonymize_chunks,
        [contenu, _json.dumps(bloc_garanti, ensure_ascii=False, default=str)
         if bloc_garanti else ""],
        state.get("entity_map") or {})
    # `args` accompagne le resultat POUR L'ECRAN, pas pour le modele : c'est ce
    # qui permet au journal d'activite de dire « je regarde le dossier :
    # Chantiers/2026 » au lieu de « je regarde le dossier ». Seuls des reperes
    # de LOCALISATION en sont extraits (journal._detail), jamais du contenu, et
    # ce champ n'est pas reinjecte dans le prompt : il ne coute aucun jeton.
    resultats.append({"skill": action["skill"], "ok": ok, "payload_hash": empreinte,
                      "args": action.get("args") or {},
                      "resultat_masque": masques[0],
                      # Hors de la coupe : c'est lui qui garantit l'affichage.
                      "bloc_garanti_masque": (masques[1] or None) if len(masques) > 1 else None})
    # UNE ACTION A ABOUTI : le drapeau de relance retombe, pour que le modele
    # puisse etre repris s'il cale de nouveau plus loin.
    #
    # Une seule relance par TOUR ne suffisait pas : produire un document en
    # demande trois d'affilee (creer, remplir, terminer), et le modele annonce
    # entre chacune. Il repartait apres la premiere relance, puis s'arretait a la
    # suivante — « je vais ajouter le nombre de dossiers dans le document cree ».
    #
    # SEULEMENT SI ELLE A ABOUTI. Le code le rearmait aussi apres un ECHEC,
    # contrairement a ce que cette explication promettait : une action qui rate
    # en boucle redonnait donc un forcage a chaque tour, sans que rien n'avance.
    # C'est exactement la boucle que ce commentaire disait impossible.
    # UN VERSEMENT QUI A RÉELLEMENT ÉCRIT NE CONSOMME PAS LE BUDGET.
    #
    # Le budget existe contre les tours qui TOURNENT EN ROND. Remplir un
    # document long, lui, avance à chaque appel — et le catalogue demande
    # explicitement de le remplir en plusieurs fois. Les deux règles se
    # contredisaient : « raconte une histoire de dix pages » ouvrait le
    # document, versait quelques sections, puis se faisait couper par le
    # garde-fou, avec en prime un message parlant de « recherches ».
    #
    # Le rejeu n'est pas ouvert pour autant : on n'exempte que les versements
    # qui ont retenu au moins un bloc, et le document a sa propre borne
    # (20 000 éléments), après quoi l'ajout échoue et le budget reprend ses
    # droits.
    versements = int(state.get("versements") or 0)
    a_verse = False
    if ok and action["skill"] in ("ajouter_document",) and versements < MAX_VERSEMENTS_PAR_TOUR:
        try:
            a_verse = int((brut.get("output") or {}).get("ajoutes") or 0) > 0
        except (AttributeError, TypeError, ValueError):
            a_verse = False

    # LE JALON QUI FERME NE CONSOMME PAS LE BUDGET. Relevé en production :
    # « créer un docx de 10 pages » s'est terminé sur « le nombre d'actions
    # autorisées est atteint » — le budget de 8 se faisait manger par la
    # fermeture, en plus des recherches. Un `terminer_document` qui RÉUSSIT ne
    # peut pas boucler : il ferme le document, et le rouvrir passe par
    # `creer_document`, qui reste compté (cf. S11 : le forceur qui rouvre un
    # document à chaque passe).
    #
    # `abandonner_document` A ÉTÉ RETIRÉ DE CETTE EXEMPTION. Je l'y avais mis
    # en raisonnant « il consomme un document ouvert, donc il ne peut pas
    # boucler » — c'était faux, et la production l'a montré le jour même :
    # abandonner LIBÈRE une place, créer la reprend, et le cycle
    # abandon → création → remplissage → abandon tourne sans jamais croiser de
    # plafond. Huit minutes, deux fois le travail détruit. Un geste qui DÉFAIT
    # n'est jamais un geste qui avance.
    jalon = ok and action["skill"] == "terminer_document"

    avance = a_verse or jalon

    # POINT D'ÉTAPE : UN LIVRABLE PRÊT SE MONTRE, IL NE S'EMPILE PAS.
    #
    # Relevé en production : trente et une minutes, vingt-neuf actions, trois
    # documents — et rien à l'écran avant la toute fin. Le premier document
    # était pourtant terminé dès la dixième action, donc disponible vingt
    # minutes plus tôt. Pire, faute de le présenter, le modèle a REFAIT le même
    # devis plus loin dans le tour : deux fichiers identiques, huit actions
    # perdues.
    #
    # Un document qui vient d'être fermé, après un tour déjà long, est un
    # RÉSULTAT. On clôt donc la phase d'actions pour le présenter, avec
    # l'avancement du plan et une proposition de suite. Le travail n'est pas
    # interrompu : il reprend au tour suivant, en sachant ce qui est déjà fait.
    #
    # Le seuil ne porte QUE sur les tours déjà longs : produire un document
    # court en trois actions reste un seul tour, comme avant.
    if jalon and iteration >= POINT_ETAPE_ACTIONS:
        logger.info("Point d'étape : document terminé à l'action %d, on présente", iteration)
        # `llm_response` VIDÉ À DESSEIN : sans cela la note serait recopiée
        # telle quelle sous le texte du modèle, et l'utilisateur lirait une
        # consigne interne. Vidé, le routeur redemande une rédaction, et le
        # modèle met la note dans ses mots — avec le document sous les yeux.
        return {"tool_results": resultats, "llm_response": "",
                "tools_finished": True, "tool_iterations": iteration,
                "note_sortie": "un premier livrable est prêt. Présente-le "
                               "maintenant avec son bloc `fichier`, dis où en "
                               "est le plan, et propose de poursuivre."}

    # L'ENLISEMENT, MESURÉ SUR CE QUI VIENT DE SE PASSER.
    #
    # C'est ce contrôle qui autorise le plafond haut posé en tête de fichier.
    # Tant que les actions aboutissent, le tour continue : lire quinze fichiers
    # avant de rédiger est un travail légitime, pas une boucle. Dès que trois
    # échouent d'affilée, le chemin est fermé et une tentative de plus ne
    # l'ouvrira pas.
    #
    # On regarde la FIN de la liste, pas son total : un tour qui a réussi dix
    # actions puis en rate deux travaille encore. Le rejeu à l'identique est
    # déjà écarté en amont (l'empreinte le resert sans l'exécuter), donc ces
    # échecs-ci sont bien des tentatives distinctes qui échouent.
    if not ok:
        recents = [r for r in resultats if r.get("skill")][-MAX_ECHECS_CONSECUTIFS:]
        if (len(recents) == MAX_ECHECS_CONSECUTIFS
                and not any(r.get("ok") for r in recents)):
            logger.info("Enlisement : %d actions consécutives en échec, tour arrêté",
                        MAX_ECHECS_CONSECUTIFS)
            # Formulé comme une RAISON : c'est le modèle qui la met en mots, et
            # il a les résultats d'échec sous les yeux pour dire lequel a bloqué.
            return _sortir("les dernières actions ont toutes échoué. Explique "
                           "ce qui a bloqué — les messages d'erreur le disent — "
                           "présente ce que tu as déjà trouvé, et propose une "
                           "autre voie.")

    maj = {"tool_results": resultats,
           "tool_iterations": (state.get("tool_iterations") or 0) if avance else iteration,
           "versements": versements + 1 if a_verse else versements,
           "entity_map": carte_maj}
    if ok:
        maj["relance_annonce"] = False
        # MÊME ATTRIBUTION QU'À L'ARMEMENT : un skill qui déclare son expert
        # crédite le tour à cet expert (préparer/essayer un visuel = travail de
        # conception, même exécuté dans agent1). Seulement s'il a ABOUTI : un
        # échec n'est pas un travail rendu.
        exp = expert_du_skill(action["skill"])
        if exp:
            maj["target_agent"] = exp
    return maj




_CLES_TECHNIQUES = frozenset({
    "cles", "cle", "clé", "clés", "document_id", "bloc_ui", "payload_hash", "hash",
    "ids", "jeton", "token", "source_id", "fichier_id", "thread_id", "tache_id",
    "validation_id", "empreinte", "a_faire", "a_savoir", "note",
})
# Un identifiant : long, sans espace, avec au moins un chiffre — une clé de
# dépôt (sha tronqué), un jeton de document, un UUID. Un mot français ne
# ressemble jamais à ça ; un numéro de devis (« DV0001410 ») fait 9 caractères
# et passe.
_IDENTIFIANT_RE = __import__("re").compile(r"(?<![\w/])(?=[\w-]*\d)[A-Za-z0-9_-]{16,}(?![\w/])")


def _sans_identifiants(texte: str) -> str:
    """Le résultat d'un skill, DÉBARRASSÉ de ce qui n'est pas pour l'utilisateur.

    Relevé par Noa le 31/08 sur un tour réussi : « les résultats indiquent les
    clés ["e527f1b03524955df936f7ff"], la source "bc4191bbe1154b53f191d130" »,
    et « avec l'identifiant xz-U9coZQtoswQYDsniBnM9pr1BfwJMA » dans la prose.
    Le rédacteur recevait le résultat BRUT du skill : le modèle recopiait
    docilement les clés de dépôt, drapeaux internes et consignes qui lui
    étaient destinées. Deux passes : les CLÉS techniques d'un JSON sont
    retirées (récursivement), puis toute valeur qui a la forme d'un
    identifiant disparaît — que le résultat soit du JSON ou du texte.
    Les blocs d'écran, eux, gardent leurs clés : ils sont ajoutés
    mécaniquement sous la prose, pas écrits par le modèle.
    """
    import json as _json

    def _nettoyer(v):
        if isinstance(v, dict):
            return {k: _nettoyer(x) for k, x in v.items()
                    if str(k).lower() not in _CLES_TECHNIQUES}
        if isinstance(v, list):
            return [_nettoyer(x) for x in v]
        if isinstance(v, str):
            return _IDENTIFIANT_RE.sub("", v).strip()
        return v

    brut = (texte or "").strip()
    if brut[:1] in ("{", "["):
        try:
            return _json.dumps(_nettoyer(_json.loads(brut)), ensure_ascii=False)
        except (ValueError, TypeError):
            pass
    return _IDENTIFIANT_RE.sub("", brut)


def _essentiel(texte: str, budget: int = 8000) -> str:
    """Le résultat d'un skill RÉDUIT à ce qui répond à la demande, dans un budget.

    Le 31/08, « analyse mes mails pour trouver des demandes de travaux » a fini
    en : « La recherche "travaux" a donné 19 message(s) trouvé(s) … 7 expéditeurs
    internes et 3 automatiques ». Le rédacteur ne recevait que les 800 PREMIERS
    caractères de chaque résultat — l'en-tête (comptes, expéditeurs) — et jamais
    les messages eux-mêmes, coupés derrière. Il a donc rédigé ce qu'il voyait :
    des statistiques d'appels.

    Ici, les listes d'objets sont COMPACTÉES plutôt que coupées : chaque champ
    texte est borné, chaque liste aussi, pour qu'un lot de 25 mails tienne dans
    le budget AVEC son contenu (objet, expéditeur, date, extrait). Puis le
    filtre des identifiants, puis le budget global.
    """
    import json as _json

    def _compacter(v, profondeur=0):
        if isinstance(v, dict):
            return {k: _compacter(x, profondeur + 1) for k, x in v.items()}
        if isinstance(v, list):
            return [_compacter(x, profondeur + 1) for x in v[:25]]
        if isinstance(v, str) and profondeur >= 2:
            return v[:150]
        return v

    brut = (texte or "").strip()
    if brut[:1] in ("{", "["):
        try:
            brut = _json.dumps(_compacter(_json.loads(brut)), ensure_ascii=False)
        except (ValueError, TypeError):
            pass
    propre = _sans_identifiants(brut)
    return propre[:budget] + (" […tronqué]" if len(propre) > budget else "")


async def _rediger_par_le_modele(demande: str, resultats, cause: str = "") -> str:
    """Fait ÉCRIRE la réponse par le MODÈLE à partir des résultats des skills.

    RÈGLE DE NOA DU 30/08, posée après l'avoir vue échouer en production :
    l'assistant ne parle JAMAIS avec des phrases écrites dans le code — même
    en secours, même après validation. Un texte préécrit qui dit « c'est
    prêt » au-dessus d'un tour qui a échoué est pire qu'un silence : il
    maquille. Les mécaniques gardent DEUX territoires : les blocs d'écran
    (aperçus, fichiers — des composants, pas des phrases) et le routage
    (forceur). Toute prose vient d'ici.

    Contexte volontairement RÉDUIT (comme le forceur) : la demande, les
    résultats MASQUÉS, une consigne au passé composé — pas l'historique du
    fil, qui est précisément ce qui apprend au modèle à mentir. Rend "" si
    aucun fournisseur ne répond : l'appelant affiche alors les blocs seuls,
    sans texte — jamais une phrase de remplacement.
    """
    from llm.router import get_llm, LLMTier as _T
    from langchain_core.messages import HumanMessage as _H

    lignes = []
    # Le budget total (≈ 14 000 caractères) se partage entre les résultats : un
    # seul lot de 25 mails a toute la place, cinq résultats en ont chacun moins.
    dicts = [r for r in (resultats or []) if isinstance(r, dict)]
    budget = max(1500, min(8000, 14000 // max(1, len(dicts))))
    for r in dicts:
        brut = _essentiel(str(r.get("resultat_masque") or ""), budget)
        lignes.append(f"- {r.get('skill') or '?'} : "
                      f"{'réussie' if r.get('ok') else 'EN ÉCHEC'}\n  {brut}")

    if lignes:
        consigne = (
            "Tu rédiges la réponse FINALE d'un assistant d'entreprise, en "
            "français. Les actions ci-dessous ont DÉJÀ été exécutées : écris au "
            "passé composé ce qui a été fait et ce que montrent les résultats — "
            "chiffres, comptes et noms recopiés EXACTEMENT des résultats, "
            "balises [XXX_n] recopiées telles quelles. N'annonce rien, ne "
            "promets rien, n'invente ni fichier ni référence, ne propose pas la "
            "suite. Si une action a ÉCHOUÉ, dis-le simplement avec sa raison. "
            "N'écris AUCUN bloc de code ni ```ui : les aperçus et fichiers sont "
            "ajoutés automatiquement sous ton texte. Ne cite JAMAIS d'identifiant "
            "technique (clé, jeton, hash, document_id), de drapeau interne "
            "(genere, essai, ok) ni de nom de skill : parle du résultat, pas de la "
            "tuyauterie. Réponds à la DEMANDE avec le CONTENU des résultats — objets, "
            "expéditeurs, extraits, montants, noms — jamais avec une statistique des "
            "appels ni un compte rendu de ce que tu as consulté : si la demande "
            "cherchait quelque chose, dis ce qui a été trouvé, et dis franchement si "
            "rien n'y répond. 2 à 8 phrases ou une liste courte, sans salutation.")
        corps = (f"Demande de l'utilisateur :\n{demande}\n\n"
                 "Actions exécutées à ce tour, et leurs résultats :\n"
                 + "\n".join(lignes))
    else:
        # Rien n'a abouti et rien n'a été rédigé : le modèle le DIT, dans ses
        # mots — pas une excuse préécrite qui accuse la demande.
        consigne = (
            "Tu rédiges la réponse d'un assistant d'entreprise, en français. "
            "Ce tour-ci, la demande n'a pas pu être traitée : aucune action n'a "
            "abouti et aucune réponse n'a pu être formulée. Dis-le honnêtement "
            "en une ou deux phrases, sans accuser l'utilisateur ni t'excuser "
            "platement, et sans promettre quoi que ce soit.")
        corps = f"Demande de l'utilisateur :\n{demande}"

    try:
        reponse = await get_llm(_T.STANDARD).ainvoke(
            [_H(content=consigne + "\n\n" + corps)])
        texte = _texte_visible(str(getattr(reponse, "content", "") or ""))
        # Un modèle qui répond ici par une promesse ou une question n'a pas
        # fait le travail : on préfère les blocs seuls à une rechute.
        if texte and not est_une_annonce(texte) and not promesse_sans_suite(texte):
            return texte
    except Exception as e:  # noqa: BLE001 — le secours ne casse jamais un tour
        logger.info("Rédaction de secours par le modèle indisponible (%s) : %s",
                    cause or "?", str(e)[:120])
    return ""


def _tracer_filet(state, filet: str, cause: str, **details) -> None:
    """Trace un FILET MÉCANIQUE dans l'audit — visible en Console développeur.

    Demande de Noa du 30/08 : quand une réponse a une origine mécanique, c'est
    presque toujours parce que le MODÈLE a échoué (promesse, prétention,
    invention) — et l'écran, lui, peut avoir l'air d'un succès. La console doit
    donc dire exactement QUAND un filet a tiré et POURQUOI : l'événement est
    enregistré `success=False`, parce que c'est bien un échec du modèle que le
    filet a rattrapé, même si l'utilisateur a fini par voir quelque chose.

    Fire-and-forget : la trace ne ralentit jamais un tour et ne le casse
    jamais. Et, règle de l'audit : JAMAIS le contenu des messages — seulement
    le nom du mécanisme, sa cause, et des références techniques.
    """
    try:
        import asyncio as _aio
        from security.audit import log_action
        meta = {"filet": filet, "cause": cause}
        meta.update({k: str(v)[:200] for k, v in details.items() if v is not None})
        _aio.get_running_loop().create_task(log_action(
            action="filet_mecanique",
            user_id=str(state.get("user_id") or "") or None,
            agent_id="agent1",
            success=False,
            error_message=f"Filet « {filet} » : {cause}",
            metadata=meta,
            trigger_type="chat",
            trigger_id=str(state.get("thread_id") or "") or None,
        ))
    except Exception:  # noqa: BLE001 — la trace ne casse jamais un tour
        pass


def _rendu_de_secours(resultats) -> str:
    """Ce qu'on affiche quand le modèle n'a pas rédigé : la sortie du skill lui-même.

    LE CONSTAT QUI IMPOSE CE FILET. Traces du 22/08, 21:42 à 21:50 : le skill
    réussit (28 mails lus, un visuel préparé), et le modèle répond « Je vais
    lire les 25 mails… », « Je prépare le visuel… » — une annonce, deux fois
    de suite malgré la consigne qui nomme le défaut. L'utilisateur ne voit
    rien de ce qui a été fait. Pire : l'annonce entre dans l'historique comme
    une réponse acceptée, et le tour suivant l'imite — chaque échec enseigne le
    suivant. Le docstring du forceur l'avait prédit ; les traces le confirment.

    On cesse donc de dépendre du modèle pour MONTRER. Depuis le 30/08 (règle
    de Noa : aucune phrase préécrite dans le chat), cette fonction ne rend
    plus QUE les BLOCS d'écran du dernier skill réussi — tableaux, cartes
    mail, planches — sans une ligne de prose : le `message_final` et les
    comptes du skill servent d'ENTRÉE à `_rediger_par_le_modele`, qui écrit
    le texte, et n'atteignent plus jamais l'écran tels quels. C'est ce
    couple (prose du modèle + blocs mécaniques) qui va dans l'historique.
    """
    import json as _j
    for r in reversed(list(resultats or [])):
        if not r.get("ok"):
            continue
        brut = str(r.get("resultat_masque") or "")
        # La déduplication préfixe « (déjà exécuté à ce tour…)\n{…} » : on lit
        # à partir du premier objet JSON.
        i = brut.find("{")
        if i < 0:
            continue
        try:
            d = _j.loads(brut[i:])
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        parties = []
        blocs = _blocs_de(d.get("bloc_ui"))
        for bloc in blocs:
            parties.append("```ui\n" + _j.dumps(bloc, ensure_ascii=False) + "\n```")
        messages = d.get("messages")
        if isinstance(messages, list) and messages and not blocs:
            for m in messages[:25]:
                if not isinstance(m, dict):
                    continue
                carte = {"type": "email",
                         "subject": str(m.get("objet") or m.get("subject") or "(sans objet)")[:140],
                         "from": str(m.get("de") or m.get("from") or "")[:120],
                         "date": str(m.get("date") or "")[:19],
                         "preview": str(m.get("apercu") or m.get("extrait") or m.get("preview") or "")[:220]}
                parties.append("```ui\n" + _j.dumps(carte, ensure_ascii=False) + "\n```")
        if parties:
            return "\n\n".join(parties)
    return ""


# ════════════════════════════════════════════════════════════════════════════
#  UN LIVRABLE PRODUIT NE RESTE JAMAIS INVISIBLE
#
#  LE CONSTAT. Traces du 23/08, 13:05 : « fais-moi un Excel avec une colonne de
#  tous les noms clients ». Le forceur appelle `liste_clients {fichier: true}`,
#  le fichier est PRODUIT (477 lignes, 19 Ko, son bloc `fichier` prêt à
#  l'emploi) — puis le modèle enchaîne deux actions sans rapport et termine par
#  « Pour créer ce fichier Excel, j'ai besoin de votre adresse email ». Le
#  fichier existait depuis deux minutes ; l'utilisateur ne l'a jamais vu. Deux
#  tours plus tard, il en fabrique même une carte de son cru
#  (`{"type":"doc","name":"Liste des clients"}`) : une vignette sans URL, que
#  l'écran ne peut ni prévisualiser ni télécharger.
#
#  Le filet existant (`_rendu_de_secours`) ne pouvait rien ici : il ne se
#  déclenche que sur une réponse VIDE ou sur une promesse, et une question
#  posée à l'utilisateur n'en est pas une — à juste titre, elle appelle une
#  réponse et doit rester.
#
#  D'où un filet distinct, et MÉCANIQUE : ce que le tour a réellement produit
#  s'affiche, que le modèle ait pensé à le recopier ou non ; et ce qu'il
#  invente à la place d'un fichier réel s'efface. Aucune consigne de plus au
#  modèle : le dépôt a déjà payé pour apprendre qu'une règle de plus ne tient
#  pas quand le prompt en porte trente autres.
# ════════════════════════════════════════════════════════════════════════════

import re as _re_livrables

# Un bloc d'écran écrit par le modèle : ```ui { … }
_BLOC_UI_RE = _re_livrables.compile(r"```ui\s*(\{.*?\})\s*```", _re_livrables.S)

# Ce qui compte comme LIVRABLE : un objet produit, qui porte sa propre
# référence (une URL de document, les clés d'une planche d'images). Une carte
# `doc`, une table ou un `callout` décrivent quelque chose ; ils ne le portent
# pas, et ne sont donc jamais restitués d'office.
_TYPES_LIVRABLE = ("fichier", "visuel")


def _blocs_de(bloc_ui) -> list[dict]:
    """Les blocs d'écran d'un résultat : UN dict, ou une LISTE (31/08 — un mail
    à trois pièces jointes rend trois cartes). Tout ce qui n'a pas de `type`
    est ignoré."""
    blocs = bloc_ui if isinstance(bloc_ui, list) else [bloc_ui]
    return [b for b in blocs if isinstance(b, dict) and b.get("type")]


def _reference_bloc(bloc) -> str:
    """Ce qui identifie un livrable : l'URL du document, ou la clé de sa première image."""
    if not isinstance(bloc, dict):
        return ""
    url = str(bloc.get("url") or "").strip()
    if url:
        return url
    images = bloc.get("images")
    if isinstance(images, list):
        for img in images:
            cle = str((img or {}).get("cle") or "").strip() if isinstance(img, dict) else ""
            if cle:
                return cle
    return ""


def _blocs_livrables(resultats) -> list[dict]:
    """Les blocs d'écran des livrables produits par les skills de CE tour."""
    import json as _j
    blocs: list[dict] = []
    for r in resultats or []:
        if not isinstance(r, dict) or not r.get("ok"):
            continue
        brut = str(r.get("resultat_masque") or "")
        i = brut.find("{")
        if i < 0:
            continue
        try:
            d = _j.loads(brut[i:])
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        for bloc in _blocs_de(d.get("bloc_ui")):
            if (bloc.get("type") in _TYPES_LIVRABLE and _reference_bloc(bloc)
                    and not any(_reference_bloc(b) == _reference_bloc(bloc) for b in blocs)):
                blocs.append(bloc)
    return blocs


def fichiers_du_fil(state: AgentState) -> list[dict]:
    """Les fichiers déjà produits dans CETTE conversation, le plus récent en dernier.

    Lus dans l'historique, comme les images (`cles_images_du_fil`) : aucun champ
    d'état à ajouter, rien à remettre à zéro, et cela survit au redémarrage.
    C'est ce qui permet de répondre « montre-moi la liste » au tour suivant avec
    le VRAI fichier plutôt qu'avec une vignette inventée.
    """
    import json as _j
    vus: list[dict] = []
    for m in (state.get("messages") or []):
        contenu = getattr(m, "content", "")
        if not isinstance(contenu, str):
            contenu = str(contenu)
        for brut in _BLOC_UI_RE.findall(contenu):
            try:
                bloc = _j.loads(brut)
            except ValueError:
                continue
            if not isinstance(bloc, dict) or bloc.get("type") not in _TYPES_LIVRABLE:
                continue
            ref = _reference_bloc(bloc)
            if not ref:
                continue
            vus = [b for b in vus if _reference_bloc(b) != ref]
            vus.append(bloc)
    return vus[-4:]

def _signature_bloc(bloc: dict) -> str:
    """Ce qui fait qu'un bloc d'écran EST le même qu'un autre, sous une autre forme.

    Relevé par Noa le 31/08 : « des fois il met deux composants visuels
    différents mais pour le même contenu ». Un `table` et un `keyvalue` qui
    portent les mêmes valeurs, deux cartes `email` du même message, une carte
    `doc` à côté du vrai `fichier` : mêmes données, deux affichages. La
    signature se calcule sur le CONTENU (les feuilles du JSON, triées), pas sur
    la forme — et sur l'identité quand le type en a une (URL, clé d'image,
    objet + expéditeur).
    """
    import json as _j
    t = str(bloc.get("type") or "")
    if t in ("fichier", "doc", "doc_apercu"):
        # Le NOM identifie (comme `_meme_livrable`) : une vignette `doc` n'a
        # jamais l'URL du vrai fichier, elle a son nom.
        ident = str(bloc.get("nom") or bloc.get("name") or bloc.get("titre") or bloc.get("url") or "")
        return "fichier|" + _plat_nom(ident)
    if t == "visuel":
        images = bloc.get("images") or []
        premiere = images[0] if images and isinstance(images[0], dict) else {}
        return "visuel|" + str(premiere.get("cle") or premiere.get("url") or "")
    if t == "email":
        return "email|" + " ".join(str(bloc.get(c) or "").strip().lower()
                                   for c in ("subject", "from", "date"))
    if t == "site":
        return "site|" + str(bloc.get("url") or "")
    feuilles: list = []

    def _cueillir(v):
        if isinstance(v, dict):
            for x in v.values():
                _cueillir(x)
        elif isinstance(v, list):
            for x in v:
                _cueillir(x)
        elif v not in (None, ""):
            feuilles.append(str(v).strip().lower())

    _cueillir({k: v for k, v in bloc.items() if k != "type"})
    if len(feuilles) >= 3:
        return "contenu|" + "|".join(sorted(set(feuilles)))
    return "brut|" + _j.dumps(bloc, ensure_ascii=False, sort_keys=True)


def _dedoublonner_blocs(texte: str) -> str:
    """Un même contenu ne s'affiche qu'UNE fois par message, quel que soit son habit.

    Passe mécanique, posée après `_livrables_a_l_ecran` (qui gère les
    livrables face au FIL) : ici on dédoublonne À L'INTÉRIEUR du message. Le
    premier bloc gagne, les suivants de même signature disparaissent. Un bloc
    illisible est gardé tel quel (le rendu sait déjà l'écarter), et les
    `quick_replies` ne comptent pas : des suggestions ne sont pas un contenu.
    """
    import json as _j
    if not texte or "```ui" not in texte:
        return texte
    vus: set = set()

    def _garder(m):
        try:
            bloc = _j.loads(m.group(1))
        except ValueError:
            return m.group(0)
        if not isinstance(bloc, dict):
            return m.group(0)
        # Les suggestions ne comptent pas comme un CONTENU dupliqué — elles ne
        # doivent jamais faire disparaître un tableau qui répète leurs mots.
        # Mais un message ne porte qu'UNE rangée de pastilles : la première.
        if str(bloc.get("type")) == "quick_replies":
            if "quick_replies" in vus:
                return ""
            vus.add("quick_replies")
            return m.group(0)
        sig = _signature_bloc(bloc)
        if sig in vus:
            return ""
        vus.add(sig)
        return m.group(0)

    resultat = _BLOC_UI_RE.sub(_garder, texte)
    return _re_livrables.sub(r"\n{3,}", "\n\n", resultat).strip()



def _plat_nom(valeur) -> str:
    """Un nom réduit à ses lettres et chiffres, sans accent : « Liste des clients » -> « listedesclients »."""
    import unicodedata
    texte = unicodedata.normalize("NFD", str(valeur or "")).encode("ascii", "ignore").decode()
    texte = _re_livrables.sub(r"\.(xlsx|xls|docx|doc|pdf|csv|pptx)$", "", texte.lower())
    return _re_livrables.sub(r"[^a-z0-9]+", "", texte)


def _designe_le_meme(carte: dict, reels: list[dict]) -> bool:
    """La carte inventée par le modèle parle-t-elle d'un fichier qu'on a vraiment ?

    Volontairement STRICT : une carte `doc` est aussi la façon normale de citer
    un document trouvé par la recherche documentaire. On ne retire que celle
    qui désigne, par son nom, un livrable qu'on tient sous la main — et qu'on
    va donc remplacer par le vrai bloc, avec son aperçu et son téléchargement.
    """
    nom = _plat_nom(carte.get("name") or carte.get("nom") or carte.get("titre"))
    if len(nom) < 5:
        return False
    for bloc in reels:
        for candidat in (bloc.get("titre"), bloc.get("nom"), bloc.get("name")):
            autre = _plat_nom(candidat)
            if len(autre) >= 5 and (nom in autre or autre in nom):
                return True
    return False


def _meme_livrable(a: dict, b: dict) -> bool:
    """Deux blocs désignent-ils le MÊME livrable, sous deux références ?

    Le jeton d'un document est tiré au hasard à chaque production : le même
    Excel refait dans le tour (autres colonnes, seconde passe du forceur) porte
    une autre URL. Aux yeux de la personne c'est pourtant le même fichier, et
    l'afficher deux fois est un doublon — vu en production le 29/08.
    """
    nom_a = _plat_nom(a.get("titre") or a.get("nom") or a.get("name"))
    nom_b = _plat_nom(b.get("titre") or b.get("nom") or b.get("name"))
    return len(nom_a) >= 5 and len(nom_b) >= 5 and (nom_a in nom_b or nom_b in nom_a)


def _livrables_a_l_ecran(texte: str, state: AgentState) -> str:
    """Le texte final, débarrassé des faux fichiers et des doublons, complété des vrais."""
    import json as _j
    produits = _blocs_livrables(state.get("tool_results") or [])
    # Le même livrable produit deux fois dans le tour : seule la DERNIÈRE
    # version compte (cf. _meme_livrable) — les références plus anciennes
    # sortent aussi de `references`, donc du texte, via _trier.
    derniers: list[dict] = []
    for bloc in produits:
        derniers = [b for b in derniers if not _meme_livrable(b, bloc)]
        derniers.append(bloc)
    produits = derniers
    # Et une version ANTÉRIEURE du même livrable, produite à un tour passé,
    # ne légitime plus son affichage : recopiée par le modèle, elle céderait
    # la place à celle de ce tour-ci.
    du_fil = [b for b in fichiers_du_fil(state)
              if not any(_meme_livrable(b, p) and _reference_bloc(b) != _reference_bloc(p)
                         for p in produits)]
    connus = produits + [b for b in du_fil
                         if not any(_reference_bloc(x) == _reference_bloc(b) for x in produits)]
    if not connus:
        return texte
    references = {_reference_bloc(b) for b in connus}
    inventes: list[dict] = []   # les blocs effacés, GARDÉS pour juger le repli
    affiches: set[str] = set()  # les livrables GARDÉS dans le texte, par référence

    def _trier(m):
        try:
            bloc = _j.loads(m.group(1))
        except ValueError:
            return m.group(0)
        if not isinstance(bloc, dict):
            return m.group(0)
        type_ = bloc.get("type")
        if type_ in _TYPES_LIVRABLE:
            ref = _reference_bloc(bloc)
            # Un livrable dont la référence n'existe pas : le modèle l'a écrit
            # de mémoire (URL morte, image absente) ou c'est une version
            # périmée de ce que le tour vient de refaire. On l'efface.
            if ref not in references:
                # Sauf une IMAGE que le fil connaît ou que le dépôt tient : le
                # modèle la remontre, il ne l'invente pas (03/09, « montre moi
                # la photo » effacé à l'écran).
                if type_ == "visuel" and _image_connue(ref, state):
                    if ref in affiches:
                        return ""
                    affiches.add(ref)
                    return m.group(0)
                inventes.append(bloc)
                return ""
            # Le MÊME fichier écrit deux fois par le modèle : un seul aperçu.
            if ref in affiches:
                return ""
            affiches.add(ref)
            return m.group(0)
        # Une vignette qui parle d'un fichier qu'on tient vraiment : on la
        # remplace plus bas par le bloc réel, téléchargeable et prévisualisable.
        if type_ == "doc" and not bloc.get("url") and _designe_le_meme(bloc, connus):
            inventes.append(bloc)
            return ""
        return m.group(0)

    texte = _BLOC_UI_RE.sub(_trier, texte).strip()

    # Ce que le tour a produit s'affiche toujours ; si le modèle a inventé une
    # carte à la place d'un fichier du fil, on restitue ce fichier-là — MAIS
    # SEULEMENT si l'invention le DÉSIGNE. Relevé en production le 30/08,
    # 13:34 : « fais un word avec les infos de l'entreprise » — aucun skill
    # n'a tourné (routage à terre), le modèle a prétendu l'avoir fait avec un
    # bloc inventé, et le repli, écrit pour « remontre-moi cette liste », a
    # restitué le DERNIER fichier du fil : l'Excel des fournisseurs, sans
    # aucun rapport. Corroborer une invention avec le mauvais fichier est
    # pire que ne rien montrer.
    a_montrer = list(produits)
    if inventes and not a_montrer and du_fil:
        correspondants = [b for b in du_fil
                          if any(_meme_livrable(b, inv) for inv in inventes)]
        if correspondants:
            a_montrer = [correspondants[-1]]
        else:
            # L'invention ne désigne RIEN qu'on tienne : le fichier annoncé
            # n'existe pas, le bloc s'efface, et RIEN ne le remplace. Une
            # première version ajoutait ici une phrase toute faite
            # (« redemandez-le en un message… ») : règle de Noa, AUCUN message
            # déterministe ni mécanique de question-réponse dans le chat — et
            # cette phrase a créé exactement la boucle qu'elle prétendait
            # éviter. La vraie réponse au tour qui prétend sans produire est
            # en AMONT : la livraison fantôme part au forceur
            # (route_apres_llm), qui fait produire pour de vrai. Ici, on ne
            # fait que refuser de corroborer — et on le journalise.
            noms_inventes = [str(i.get("nom") or i.get("name") or i.get("titre") or "?")[:60]
                             for i in inventes]
            logger.info("Livrable inventé sans équivalent réel, effacé : %s", noms_inventes)
            _tracer_filet(state, "invention_effacee", "reference_inexistante",
                          blocs=noms_inventes)
    for bloc in a_montrer:
        ref = _reference_bloc(bloc)
        # `affiches` et non une sous-chaîne : un modèle qui échappe les barres
        # obliques (`\/api\/documents\/…`, JSON valide) rendait l'URL introuvable
        # dans le texte brut, et le même fichier s'affichait DEUX fois.
        if ref and (ref in affiches or ref in texte):
            continue
        logger.info("Livrable restitué à l'écran : %s", ref)
        _tracer_filet(state, "livrable_restitue", "absent_de_la_redaction",
                      reference=ref)
        affiches.add(ref)
        texte = (texte + "\n\n```ui\n" + _j.dumps(bloc, ensure_ascii=False) + "\n```").strip()
    return texte


def _blocs_garantis(texte: str, state: AgentState) -> str:
    """Les blocs qu'un skill GARANTIT à l'écran, que le modèle les recopie ou non.

    Pendant de `_livrables_a_l_ecran` pour les blocs SANS référence (l'arbre
    des dossiers, l'aperçu compté d'un dossier). Relevé le 01/09 : le modèle
    devait recopier le `schema` de l'arborescence ; il a inventé à la place
    une carte de document quasi vide (« TXT — Arborescence du Drive »), et
    l'utilisateur n'a rien eu à lire. Un résultat qui porte `bloc_garanti`
    voit donc ses blocs AJOUTÉS au texte s'ils n'y sont pas déjà (même
    signature), et la carte de document inventée qui les désigne est effacée.
    Trois gestes légitimes d'un garde-fou (règle de Noa) : effacer, restituer
    la sortie d'un skill, forcer — jamais une phrase écrite en dur.
    """
    import json as _j
    garantis: list[dict] = []
    for r in state.get("tool_results") or []:
        if not isinstance(r, dict) or not r.get("ok"):
            continue
        # LA VOIE SÛRE D'ABORD : le bloc mis de côté avant la coupe.
        direct = r.get("bloc_garanti_masque")
        if direct:
            try:
                garantis.extend(_blocs_de(_j.loads(direct)))
                continue
            except ValueError:
                pass                      # on retombe sur la lecture du résultat
        brut = str(r.get("resultat_masque") or "")
        i = brut.find("{")
        if i < 0:
            continue
        try:
            d = _j.loads(brut[i:])
        except ValueError:
            continue
        if not isinstance(d, dict) or not d.get("bloc_garanti"):
            continue
        garantis.extend(_blocs_de(d.get("bloc_ui")))
    if not garantis:
        return texte
    signatures_garanties = {_signature_bloc(g) for g in garantis}

    # UNE COPIE PARTIELLE N'EST PAS UNE PRÉSENCE (01/09, relevé en prod le
    # soir même du déploiement : la recherche Drive « parfaitement répondue »
    # affichait le composant EN DOUBLE). Le modèle avait reconstruit SA
    # version du tableau depuis les données du résultat — quelques lignes de
    # moins, un champ reformulé — et la comparaison par signature EXACTE ne
    # la reconnaissait pas : le bloc mécanique s'ajoutait à côté de la copie.
    # On reconnaît donc la copie au RECOUVREMENT de contenu (même type, même
    # titre, ou 60 % des feuilles en commun) : la copie dégradée s'efface, le
    # bloc mécanique complet la remplace. Une copie EXACTE reste en place —
    # elle est déjà le bon bloc, au bon endroit.
    def _feuilles(bloc) -> set:
        feuilles: set = set()

        def _cueillir(v):
            if isinstance(v, dict):
                for x in v.values():
                    _cueillir(x)
            elif isinstance(v, list):
                for x in v:
                    _cueillir(x)
            elif v not in (None, ""):
                feuilles.add(str(v).strip().lower())

        # STRUCTURE ≠ CONTENU (01/09). `columns` et `titre` sont la CHARPENTE :
        # deux tableaux sans rapport partagent « Nom » et « Type » sans parler de
        # la même chose, et le seuil se calcule sur le plus PETIT des deux — un
        # tableau légitime de trois lignes s'effaçait alors, sans être remplacé.
        _cueillir({k: v for k, v in bloc.items()
                   if k not in ("type", "titre", "sous_titre", "columns", "colonnes")})
        return feuilles

    def _copie_du_garanti(bloc: dict) -> bool:
        for g in garantis:
            if bloc.get("type") != g.get("type"):
                continue
            if bloc.get("titre") and bloc.get("titre") == g.get("titre"):
                return True
            fa, fg = _feuilles(bloc), _feuilles(g)
            if fa and fg and len(fa & fg) >= max(3, int(0.6 * min(len(fa), len(fg)))):
                return True
        return False

    def _retirer(m):
        try:
            bloc = _j.loads(m.group(1))
        except ValueError:
            return m.group(0)
        if not isinstance(bloc, dict):
            return m.group(0)
        # Une carte de document SANS url qui désigne un bloc garanti est la
        # signature exacte du défaut relevé : le vrai contenu la remplace.
        if (bloc.get("type") in ("doc", "doc_apercu")
                and not bloc.get("url") and _designe_le_meme(bloc, garantis)):
            _tracer_filet(state, "invention_effacee", "carte_au_lieu_du_bloc_garanti",
                          bloc=str(bloc.get("titre") or bloc.get("name")
                                   or bloc.get("nom") or "")[:60])
            return ""
        # La copie dégradée d'un bloc garanti s'efface (le complet arrive) ;
        # la copie exacte, elle, reste : c'est déjà le bon bloc.
        if (_signature_bloc(bloc) not in signatures_garanties
                and _copie_du_garanti(bloc)):
            _tracer_filet(state, "invention_effacee", "copie_partielle_du_bloc_garanti",
                          type=str(bloc.get("type") or ""))
            return ""
        return m.group(0)

    texte = _BLOC_UI_RE.sub(_retirer, texte).strip()
    presentes: set[str] = set()
    for brut in _BLOC_UI_RE.findall(texte):
        try:
            bloc = _j.loads(brut)
        except ValueError:
            continue
        if isinstance(bloc, dict):
            presentes.add(_signature_bloc(bloc))
    for bloc in garantis:
        if _signature_bloc(bloc) in presentes:
            continue
        # La signature s'ajoute à la volée : deux résultats garantis IDENTIQUES
        # dans le même tour (le skill rappelé tel quel) n'affichent qu'un bloc.
        presentes.add(_signature_bloc(bloc))
        _tracer_filet(state, "livrable_restitue", "bloc_garanti_absent",
                      type=str(bloc.get("type") or ""))
        texte = (texte + "\n\n```ui\n" + _j.dumps(bloc, ensure_ascii=False) + "\n```").strip()
    return texte


def _image_connue(cle: str, state) -> bool:
    """Cette clé d'image désigne-t-elle une image RÉELLE de la conversation ?

    LE CAS DU 03/09 (export Langfuse, 13:47). Photo jointe au tour précédent,
    analysée par la vision ; « montre moi la photo » → le modèle écrit le bloc
    `visuel` avec la BONNE clé — celle que la vision lui avait donnée. Deux
    filets l'ont pris pour une invention : la livraison fantôme (forceur), puis
    l'effacement du bloc. À l'écran : « Voici la photo du jardin : » et rien
    dessous. Pourquoi : les deux filets ne connaissaient que les blocs ```ui
    ÉMIS dans l'historique, or la vision n'écrivait la référence qu'en texte.

    Deux sources, dans cet ordre : les clés du fil (`cles_images_du_fil`, qui
    lit l'historique ET la photo jointe à l'instant), puis le DÉPÔT lui-même —
    une image qui existe sur le disque n'est pas inventée, quoi qu'en dise
    l'historique. C'est l'arbitre de dernier ressort, et il ne coûte qu'un
    `stat`.
    """
    if not cle:
        return False
    if cle in cles_images_du_fil(state):
        return True
    try:
        from visuels import depot
        return depot._chemin(str(cle)) is not None
    except Exception:  # noqa: BLE001 — pas de dépôt (Duret sans visuels) : rien de plus à savoir
        return False


def _montre_un_fichier_du_fil(texte: str, state) -> bool:
    """La réponse remontre-t-elle un VRAI fichier de la conversation ?

    Sert à distinguer la remontrance honnête (« remontre-moi la liste » → le
    bloc réel du fil, avec sa vraie référence) de la livraison fantôme : une
    prétention accompagnée d'un fichier du fil est légitime, la même phrase
    sans rien derrière ne l'est pas.
    """
    import json as _j
    refs = {_reference_bloc(b) for b in fichiers_du_fil(state)} - {""}
    for brut in _BLOC_UI_RE.findall(texte or ""):
        try:
            bloc = _j.loads(brut)
        except ValueError:
            continue
        if not isinstance(bloc, dict):
            continue
        ref = _reference_bloc(bloc)
        if ref and ref in refs:
            return True
        # Une photo du fil, remontrée : légitime au même titre qu'un fichier.
        if bloc.get("type") == "visuel" and _image_connue(ref, state):
            return True
    return False


def _redaction_dement_le_livrable(texte: str, resultats) -> bool:
    """La rédaction réclame un préalable à un travail que le tour vient de LIVRER ?

    LE CAS DU 30/08, sur le code pourtant corrigé du 29 : « excel des
    fournisseurs avec mon mail », dans une VIEILLE conversation (66 messages)
    pleine des réponses ratées d'avant le correctif. Le skill tourne, l'Excel
    sort avec la bonne adresse — et la rédaction finale recopie mot pour mot
    une vieille réponse de l'historique : « j'ai besoin de votre adresse email
    professionnelle exacte… Une fois communiqué, je créerai un fichier Excel. »
    Le filet des livrables affichait bien le fichier, mais SOUS ce texte qui le
    dément — l'utilisateur lit une contradiction, et la question périmée entre
    à nouveau dans l'historique, prête à être imitée au tour suivant.

    Trois conditions, TOUTES nécessaires — c'est ce qui rend le filet sûr :
      1. le texte réclame un préalable (`reclame_un_prealable`, motifs étroits) ;
      2. un livrable RÉEL a été produit à ce tour (`_blocs_livrables`) ;
      3. la rédaction ne montre PAS ce livrable (sinon le modèle a fait son
         travail, et sa prose — même imparfaite — accompagne le fichier).
    Alors la sortie du skill remplace la rédaction (rendu de secours) : c'est
    elle qui va à l'écran ET dans l'historique, et l'historique guérit au lieu
    de s'empoisonner.
    """
    import json as _j
    if not reclame_un_prealable(texte):
        return False
    produits = _blocs_livrables(resultats)
    if not produits:
        return False
    montres = set()
    for brut in _BLOC_UI_RE.findall(texte or ""):
        try:
            bloc = _j.loads(brut)
        except ValueError:
            continue
        if isinstance(bloc, dict):
            montres.add(_reference_bloc(bloc))
    return not any(_reference_bloc(p) in montres for p in produits)


async def rehydrate_node(state: AgentState) -> dict:
    """Réinjecte les vraies entités dans la réponse via entity_map."""
    from security.anonymizer import anonymizer

    from langchain_core.messages import AIMessage
    from skills.protocol import (BLOC_ACTION_RE, BLOC_ACTION_TRONQUE_RE,
                                 BLOC_NATIF_RE, BALISAGE_OUTIL_RE)

    text = state.get("llm_response", "") or ""
    # Filet : si une demande d'action survit jusqu'ici (sortie de boucle, limite
    # atteinte), elle ne doit pas s'afficher — c'est de la mécanique interne.
    # Les passes couvrent le bloc demandé, le bloc COUPÉ par le plafond de
    # sortie, la syntaxe native d'un modèle de la cascade, puis tout balisage
    # résiduel quel qu'en soit l'émetteur.
    # Un bloc ouvert et jamais refermé échappait aux filtres : relevé en
    # production, 8 000 caractères de JSON affichés à l'utilisateur. Les quatre
    # passes vivent dans `_texte_visible`, partagé avec le routeur.
    text = _texte_visible(text)
    # LE FILET. Une promesse ou du vide à la fin d'un tour où un skill a
    # réussi : on montre la sortie du skill (voir _rendu_de_secours). C'est
    # aussi ce texte-là qui entrera dans l'historique — jamais la promesse.
    if not text or est_une_annonce(text) or promesse_sans_suite(text):
        besoin = "redaction_absente_ou_promesse"
    elif _redaction_dement_le_livrable(text, state.get("tool_results") or []):
        # LE DÉMENTI DU TRAVAIL FAIT : la rédaction réclame un préalable
        # (« j'ai besoin de votre adresse ») alors que le livrable est produit
        # et absent du texte. La question est périmée — souvent recopiée de
        # l'historique.
        besoin = "la_redaction_dement_le_livrable"
    if besoin:
        # RÈGLE DE NOA DU 30/08 : la prose de remplacement vient du MODÈLE
        # (`_rediger_par_le_modele`, contexte réduit, résultats masqués) — la
        # mécanique n'apporte que les BLOCS d'écran. Si aucun fournisseur ne
        # répond, les blocs s'affichent seuls : jamais une phrase préécrite.
        resultats = state.get("tool_results") or []
        prose = await _rediger_par_le_modele(
            state.get("anonymized_query") or state.get("query", ""),
            resultats, besoin)
        blocs = _rendu_de_secours(resultats)
        if prose or blocs:
            logger.info("Rendu de secours (%s) : prose du modèle %s, blocs %s",
                        besoin, "oui" if prose else "non", "oui" if blocs else "non")
            _tracer_filet(state, "rendu_de_secours", besoin,
                          prose_modele=bool(prose), blocs=bool(blocs))
            text = (prose + ("\n\n" + blocs if blocs else "")).strip()
    # LE SECOND FILET, indépendant du premier : celui-ci ne juge pas la
    # rédaction, il vérifie que ce qui a été PRODUIT est bien à l'écran. Posé
    # AVANT la réhydratation, donc le bloc entre aussi dans l'historique du fil
    # — c'est ainsi que le tour suivant retrouve le vrai fichier (URL et nom,
    # aucune donnée personnelle) au lieu d'en réinventer une vignette.
    text = _livrables_a_l_ecran(text, state)
    # Les blocs GARANTIS par les skills (arborescence, aperçu d'un dossier)
    # s'affichent aussi, recopiés par le modèle ou non — et la carte de
    # document inventée à leur place s'efface (01/09).
    text = _blocs_garantis(text, state)
    # Et un même CONTENU ne s'affiche qu'une fois par message (31/08 : « deux
    # composants visuels différents pour le même contenu »).
    text = _dedoublonner_blocs(text)
    resultats_en_attente = None
    if not text:
        # DERNIER FILET, ET IL NE DOIT PAS ACCUSER L'UTILISATEUR.
        #
        # « Pouvez-vous la reformuler ? » suppose que la demande était mauvaise.
        # Relevé en production alors que 29 actions avaient toutes abouti et que
        # trois documents étaient terminés : la demande était parfaite, c'est la
        # rédaction finale qui a manqué. On distingue donc les deux cas, et on
        # dit ce qui EXISTE — un document produit se retrouve dans l'historique
        # du fil, encore faut-il savoir qu'il est là.
        faits = [r for r in (state.get("tool_results") or []) if r.get("ok")]
        demande = state.get("anonymized_query") or state.get("query", "")
        if faits:
            # RÈGLE DE NOA DU 30/08 : plus de phrase préécrite ici non plus —
            # le MODÈLE écrit le compte rendu depuis les résultats masqués ;
            # à défaut, les blocs des skills s'affichent seuls.
            text = (await _rediger_par_le_modele(
                        demande, faits, "aucune_redaction_malgre_actions_reussies")
                    or _rendu_de_secours(faits))
            _tracer_filet(state, "compte_rendu_indisponible",
                          "aucune_redaction_malgre_actions_reussies",
                          actions_reussies=len(faits), prose_modele=bool(text))
            # LA PROMESSE DOIT ÊTRE TENABLE : les résultats d'outils ne vivent
            # que le temps d'un tour — relevé en production, une liste de
            # clients demandée, trois documents sans rapport rendus au tour
            # suivant. On porte donc ces résultats (masqués, taillés) au tour
            # suivant.
            resultats_en_attente = [
                {"skill": r.get("skill"), "args": r.get("args") or {},
                 "resultat_masque": str(r.get("resultat_masque") or "")[:6000]}
                for r in faits[-4:]]
        else:
            # Rien n'a abouti, rien n'a été rédigé : l'aveu vient du modèle,
            # dans ses mots — pas d'une excuse préécrite qui accuse la demande.
            text = await _rediger_par_le_modele(demande, [], "aucune_reponse")
            _tracer_filet(state, "aveu_d_echec", "aucune_action_aucune_redaction",
                          prose_modele=bool(text))

    entity_map = state.get("entity_map") or {}
    # Restreint aux jetons envoyés ce tour-ci (cf. turn_placeholders dans llm_node).
    allowed = state.get("turn_placeholders")
    if allowed is not None:
        allowed = set(allowed)
        entity_map = {k: v for k, v in entity_map.items() if k in allowed}

    final = anonymizer.rehydrate(text, entity_map)

    # UN JETON ORPHELIN NE SORT JAMAIS À L'ÉCRAN. Relevé au banc de recette :
    # « TOTAL HT [MONTANT_1] » affiché tel quel. Les montants ne sont pas
    # masqués sur ce déploiement (`anonymize_amounts` à faux), donc ce jeton
    # n'a JAMAIS eu d'entrée dans la carte : il vient d'un CONTENU LU — un
    # document qui le portait déjà en toutes lettres — que le modèle a recopié.
    # La réhydratation ne peut rien pour lui. Mais son sens, lui, est clair :
    # la donnée manque. Le brief dit quoi écrire dans ce cas (§5) : « [À
    # COMPLÉTER] », jamais un balisage technique. On rend donc au lecteur la
    # seule chose vraie — il manque une valeur ici — sans lui montrer la
    # tuyauterie.
    orphelins = anonymizer.find_placeholders(final)
    if orphelins:
        logger.warning("Réhydratation : %d jeton(s) sans valeur neutralisé(s) : %s",
                       len(orphelins), " ".join(sorted(orphelins)[:6]))
        for jeton in orphelins:
            final = final.replace(jeton, "[À COMPLÉTER]")

    sortie = {"final_response": final}
    # Porté au tour suivant seulement si ce tour a échoué à rédiger ; sinon on
    # efface ce qu'un tour précédent aurait laissé (il a été consommé ou n'a
    # plus d'objet).
    sortie["resultats_en_attente"] = resultats_en_attente

    # DES OPTIONS EN PROSE DEVIENNENT DES BOUTONS.
    #
    # Relevé en production : l'assistant termine par « Souhaitez-vous que je
    # commence par : 1. … 2. … 3. … ? », l'utilisateur répond « 1 », et le tour
    # suivant reçoit un message d'un caractère qui ne veut rien dire hors
    # contexte. Réponse obtenue : « Je ne comprends pas bien ce que signifie
    # ce « 1 » ».
    #
    # ON NE CORRIGE PAS ÇA PAR UNE CONSIGNE DE PLUS. Le dépôt a déjà payé deux
    # fois pour apprendre qu'une règle répétée au modèle ne tient pas quand le
    # prompt en porte trente autres. Ici la correction est mécanique : un
    # bouton renvoie le LIBELLÉ ENTIER comme message utilisateur, et il n'y a
    # plus aucune anaphore à résoudre. Le défaut devient impossible, au lieu de
    # devenir moins probable.
    #
    # On COMPLÈTE la réponse, on ne la réécrit pas : la prose du modèle reste
    # intacte, les boutons s'ajoutent dessous. Et rien n'est ajouté à
    # l'historique (`sortie["messages"]` plus bas) : il ne porte que du texte
    # masqué, et ces libellés sont déjà réhydratés.
    import json as _json_ui
    _options = options_proposees(sortie["final_response"])
    if _options:
        logger.info("Options en prose converties en suggestions : %d", len(_options))
        bloc = _json_ui.dumps({"type": "quick_replies", "options": _options},
                              ensure_ascii=False)
        sortie["final_response"] += "\n\n```ui\n" + bloc + "\n```"
    else:
        # ET S'IL N'EN A PAS ÉCRIT, ON EN POSE (01/09). Une question à choix du
        # modèle reste préférable — ses libellés collent au tour ; à défaut, la
        # table mécanique propose la suite qui correspond à ce qui vient de se
        # passer. Elle se tait quand une validation attend ou quand le message
        # porte déjà un bloc interactif : voir `suggestions_du_tour`. Posé ICI,
        # donc APRÈS la réhydratation et AVANT `sortie["messages"]`, qui est
        # construit à partir de `text` (masqué) : les pastilles n'entrent pas
        # dans l'historique du modèle, et ne peuvent porter aucun jeton.
        from agents.suggestions import poser as _poser_suites
        from agents.suggestions import suggestions_du_tour
        _suites = suggestions_du_tour(
            sortie["final_response"], state.get("tool_results") or [],
            expert=str(state.get("target_agent") or ""),
            pending=bool(state.get("pending_action")
                         or state.get("requires_validation")))
        if _suites:
            sortie["final_response"] = _poser_suites(sortie["final_response"], _suites)

    # UN TOUR SANS EFFET NE S'ÉCRIT PAS DANS L'HISTORIQUE.
    #
    # Le modèle relit ses propres tours. Quand une annonce sans acte y est
    # rangée, elle devient un EXEMPLE : au tour suivant il la recopie, et
    # l'exemple se duplique. Relevé dans les traces, l'historique envoyé au
    # modèle contenait quatre tours d'assistant d'affilée qui n'étaient que
    # « je vais compter les dossiers, puis créer le PDF » — après quoi aucune
    # consigne système ne pesait plus rien face à quatre démonstrations du
    # contraire.
    #
    # On ne coupe que le cas AVÉRÉ : la reprise a déjà eu lieu ce tour-ci
    # (`relance_annonce`), aucune action n'a abouti, et le texte est encore une
    # promesse. Le tour n'a alors rien produit — l'oublier ne perd rien et
    # évite d'enseigner le geste. La question posée à l'utilisateur est
    # épargnée : elle, appelle une réponse et doit rester dans le fil.
    resultats = state.get("tool_results") or []
    rien_fait = not any(r.get("ok") for r in resultats)
    if state.get("relance_annonce") and rien_fait and "?" not in text \
            and est_une_annonce(text):
        logger.info("Tour sans effet — annonce ni affichée ni enregistrée")
        # ET LA PROMESSE NE S'AFFICHE PAS NON PLUS. Laisser « je vais créer le
        # PDF » en réponse d'un tour qui n'a rien fait rend l'échec indiscernable
        # d'un affichage manquant : on ne sait plus si l'assistant travaille
        # encore, s'il s'est arrêté, ou si l'écran ne suit pas. Une phrase nette
        # vaut mieux qu'une promesse : le tour est fini, et rien n'a été produit.
        sortie["final_response"] = (
            "Je n'ai pas réussi à exécuter l'action : rien n'a été fait. "
            "Reformulez la demande, ou découpez-la en une seule étape à la fois.")
        # Trois portes qui marchent, plutôt qu'un cul-de-sac : on ne commente
        # pas l'échec, on rouvre. (La phrase ci-dessus, elle, est un message
        # déterministe antérieur à la règle du 30/08 — signalé à Noa, non traité
        # ici : le corriger est une décision, pas un correctif.)
        from agents.suggestions import poser as _poser_suites
        from agents.suggestions import suites_d_echec
        sortie["final_response"] = _poser_suites(sortie["final_response"],
                                                 suites_d_echec())
        return sortie

    # L'historique est émis ICI, et non dans `llm_node` : ce nœud s'exécute
    # exactement une fois par tour, quel que soit le nombre d'actions. On n'y
    # stocke QUE du texte masqué : aucune PII ne dort dans le checkpoint ni ne
    # repart vers le LLM.
    question_masquee = state.get("anonymized_query") or state.get("query", "")
    sortie["messages"] = [
        HumanMessage(content=question_masquee),
        AIMessage(content=text),
    ]

    # TROISIÈME ÉTAGE DE LA MÉMOIRE : l'échange clos est vectorisé pour être
    # rappelé plus tard, quand une question s'y rapportera alors qu'il sera
    # sorti de la fenêtre récente. Texte MASQUÉ, comme l'historique. Ne lève
    # jamais ; un service d'embeddings absent coûte un rappel, pas un tour.
    # En ARRIÈRE-PLAN : l'écran n'attend pas la vectorisation pour recevoir la
    # réponse. La référence est gardée (`_TACHES_MEMOIRE`) : asyncio ne
    # ramasse pas une tâche référencée.
    from agents.memoire_conversation import memoriser_echange_en_fond
    _nb = len([m for m in (state.get("messages") or []) if getattr(m, "type", None) != "system"])
    memoriser_echange_en_fond(str(state.get("thread_id") or ""), state.get("user_id"),
                              _nb // 2 + 1, question_masquee, text)
    return sortie


async def validation_check_node(state: AgentState) -> dict:
    """Détecte si la réponse nécessite une validation humaine (devis, envoi client...)."""
    """Détecte si la réponse nécessite une validation humaine.

    PRÉSERVE le drapeau posé en amont : `tools_node` le lève quand une action à
    effet externe attend une décision. L'écraser à False annulerait la demande de
    validation juste avant le `human_gate`, et l'action s'exécuterait sans accord.
    """
    # TODO (cas d'usage métier) : heuristique supplémentaire sur final_response.
    return {"requires_validation": bool(state.get("requires_validation"))}


# ── Edges conditionnels ───────────────────────────────────────────────

def route_apres_routeur(state: AgentState) -> str:
    """Décision du routeur : rédaction directe, ou consultation de la mémoire."""
    return "recherche" if state.get("besoin_memoire") else "llm"


# LE REPLI WEB AUTOMATIQUE NE SE DÉCLENCHE QUE SUR DEMANDE EXPLICITE.
#
# Première version (21/08) : une liste de mots INTERNES (client, devis…) qui
# gardaient la question au-dedans. Elle a tenu pour « la liste des clients » et
# laissé passer « les mails de la semaine » : « mail » n'y figurait pas, la
# recherche documentaire n'a rien rendu, et le tour est parti chercher la météo
# sur des sites qui n'avaient rien à voir. Une liste noire ne couvre que les
# échecs déjà vus.
#
# On inverse donc la charge : le web automatique exige que la demande nomme une
# information PUBLIQUE (prix, norme, réglementation, actualité, météo…) ou le
# web lui-même. Tout le reste reste au-dedans — et le modèle garde
# `chercher_web` au catalogue pour les cas qu'aucune liste ne prévoit. Les mots
# internes sont conservés comme VETO : « prix du devis Dupont » contient
# « prix », mais c'est un devis, il ne part pas.
_MOTS_INTERNES = (
    "client", "devis", "facture", "impaye", "impayé", "chiffre d'affaires",
    "chantier", "fournisseur", "salarie", "salarié", "collaborateur", "equipe",
    "équipe", "planning", "commande", "marge", "prospect", "contact", "mail",
    "courrier", "boite", "boîte", "dossier", "document", "drive", "nas",
    "notre", "nos ", "mes ", "mon ", "ma ",
)
_MOTS_EXTERNES = (
    "sur internet", "sur le web", "en ligne", "sur le site", "site web", "site de",
    "cherche sur", "regarde sur", "google", "prix public", "prix du marché", "prix moyen",
    "tarif public", "combien coûte", "combien coute", "norme", "dtu", "réglement",
    "reglement", "législation", "legislation", "décret", "decret", "arrêté", "arrete",
    "actualité", "actualite", "météo", "meteo", "horaires d'ouverture", "adresse de",
    "qu'est-ce que", "qu'est ce que", "définition", "definition", "wikipedia",
)


def should_use_browser(state: AgentState) -> str:
    """Après une recherche infructueuse, tenter le web — seulement si on le demande."""
    from config import settings
    if state.get("browser_used") or not settings.browser_enabled:
        return "llm"
    trouve = (state.get("anonymized_chunks") or []) or (state.get("raw_chunks") or [])
    if trouve:
        return "llm"
    demande = (state.get("query") or "").lower()
    if any(mot in demande for mot in _MOTS_INTERNES):
        return "llm"          # veto : une donnée de l'entreprise ne sort pas
    if any(mot in demande for mot in _MOTS_EXTERNES):
        return "browser"      # demande explicite d'information publique
    return "llm"              # dans le doute, on reste au-dedans


def should_validate(state: AgentState) -> str:
    return "wait_for_human" if state.get("requires_validation") else END


# ── Graph ─────────────────────────────────────────────────────────────

import re as _re_images
_CLE_IMAGE_RE = _re_images.compile(r'"cle"\s*:\s*"([0-9a-f]{16,64})"')


def cles_images_du_fil(state: AgentState) -> list[str]:
    """Les références des images de CETTE conversation, la plus récente en dernier.

    Lues dans l'historique (les blocs ```ui `visuel` que l'assistant a émis) et
    dans les résultats du tour : aucun champ d'état à ajouter, rien à remettre
    à zéro, et cela survit au redémarrage comme l'historique lui-même.

    POURQUOI. Relevé le 22/08 : « change les montants gris de la maison en
    rouge vif », juste après un essai de visuel. Le modèle a ANNONCÉ la retouche
    sans l'émettre ; le forceur, qui part d'un contexte neuf, n'avait aucune
    référence d'image sous la main et a répondu RIEN. Le tour s'est terminé sur
    « Je n'ai pas réussi à exécuter l'action » — alors que la clé était là, dans
    le message précédent. Une référence qu'il faut aller déterrer dans
    l'historique n'est pas une référence disponible.
    """
    vues: list[str] = []
    for m in (state.get("messages") or []):
        contenu = getattr(m, "content", "")
        for cle in _CLE_IMAGE_RE.findall(contenu if isinstance(contenu, str) else str(contenu)):
            if cle not in vues:
                vues.append(cle)
    for r in (state.get("tool_results") or []):
        for cle in _CLE_IMAGE_RE.findall(str(r.get("resultat_masque") or "")):
            if cle not in vues:
                vues.append(cle)
    # LA PHOTO DE CE TOUR-CI, quand l'expert vision vient de rendre la main.
    # Elle a été rangée au dépôt à l'arrivée, mais elle n'est encore NI dans
    # l'historique (le tour n'est pas fini) NI dans un résultat d'action (la
    # vision n'en appelle aucune). Sans cette ligne, « ajoute une terrasse à
    # cette photo » n'a aucune image de départ au moment même où l'utilisateur
    # la montre, et la retouche repartirait d'une génération neuve, donc d'un
    # autre jardin. La plus récente est en dernier : c'est bien elle.
    cle_jointe = state.get("attachment_visuel_cle")
    if cle_jointe and cle_jointe not in vues:
        vues.append(cle_jointe)
    return vues[-6:]


def _apercu_avant_accord(skill: str, args: dict, texte: str) -> str:
    """CE QUE L'ON APPROUVE DOIT SE VOIR, pas seulement se lire en creux.

    Le brouillon présenté à l'humain est le TEXTE du modèle. Pour une action
    ordinaire (envoyer un devis rédigé plus haut), il décrit ce qui va partir et
    cela suffit. Pour deux d'entre elles, non :

      · un PLAN — ce qu'il faut lire EST le plan, et le skill n'étant pas encore
        exécuté, son bloc n'existe pas ;
      · une RETOUCHE d'image — on approuve une dépense sur une photo précise, et
        rien ne montrait LAQUELLE. « Approuver ? » sans image, c'est un clic à
        l'aveugle, et un clic à l'aveugle finit par être donné sans lire.

    Les blocs sont construits MÉCANIQUEMENT à partir des arguments dont
    l'empreinte est vérifiée : aucun modèle ne repasse entre l'affichage et
    l'exécution, donc ce qui est montré est exactement ce qui sera fait.

    Ne lève jamais : un aperçu manquant laisse le brouillon tel quel, et la
    porte fonctionne comme avant.
    """
    import json as _json
    try:
        if skill == "proposer_plan":
            from skills.plan import bloc_du_plan
            return ((texte or "Voici comment je compte procéder.").rstrip()
                    + "\n\n```ui\n" + _json.dumps(bloc_du_plan(args),
                                                  ensure_ascii=False) + "\n```")
        if skill == "envoyer_email":
            # Un MESSAGE QUI PART — troisième cas où le texte du modèle ne
            # suffit pas : on approuve un envoi, il faut lire ce qui partira.
            # Construit depuis les arguments vérifiés par empreinte : ce qui
            # est montré est exactement ce qui sera envoyé.
            cc = args.get("cc") or []
            if isinstance(cc, str):
                cc = [cc]
            lignes = [f"À : {args.get('destinataire', '')}"]
            if args.get("mailbox"):
                lignes.insert(0, f"De : {args['mailbox']}")
            if cc:
                lignes.append("Copie : " + ", ".join(str(c) for c in cc[:10]))
            lignes.append(f"Objet : {args.get('objet', '')}")
            # LES PIÈCES SE VOIENT AVANT L'ACCORD (01/09). Un envoi qu'on
            # approuve emporte des FICHIERS hors de l'entreprise : « Approuver »
            # sans la liste de ce qui part est le même clic à l'aveugle que la
            # retouche d'image sans sa photo, juste en dessous. On se contente
            # de lignes de texte : un bloc ```ui `fichier` construit ici
            # risquerait d'être effacé par `_livrables_a_l_ecran`, dont la
            # référence n'existe pas encore au moment de l'armement.
            jointes = (args.get("pieces") or args.get("pieces_jointes")
                       or args.get("fichiers") or args.get("attachments") or [])
            if isinstance(jointes, (str, dict)):
                jointes = [jointes]
            if jointes:
                lignes.append("Pièces jointes : " + ", ".join(
                    str(p.get("nom") or p.get("ref") or p) if isinstance(p, dict)
                    else str(p) for p in jointes[:10]))
            corps = str(args.get("corps") or "")
            if len(corps) > 1500:
                corps = corps[:1500] + "…"
            return ((texte or "Voici le message prêt à partir.").rstrip()
                    + "\n\nCe qui sera envoyé, tel quel :\n\n"
                    + "\n".join(lignes) + "\n\n" + corps)
        if skill == "modifier_visuel" and args.get("image"):
            changements = args.get("changements") or args.get("modifications") or ""
            if isinstance(changements, (list, tuple)):
                changements = "; ".join(str(c) for c in changements)
            bloc = {"type": "visuel", "titre": "Image de départ",
                    "images": [{"cle": str(args["image"]),
                                "legende": "La photo qui sera retouchée"}]}
            return ((texte or "Voici la retouche que je vais produire.").rstrip()
                    + (f"\n\nCe qui change : {str(changements)[:300]}."
                       if changements else "")
                    + "\n\nLe reste de la scène est conservé à l'identique."
                    + "\n\n```ui\n" + _json.dumps(bloc, ensure_ascii=False) + "\n```")
    except Exception as e:  # noqa: BLE001 — un aperçu manquant n'empêche rien
        logger.info("Aperçu avant accord non construit (%s) : %s", skill, e)
    return ""


def _consigne_plan(state: AgentState) -> str:
    """Le plan que l'utilisateur vient d'approuver, remis sous les yeux du modèle.

    Sans cette consigne, la reprise après accord repartirait sur la demande
    d'origine sans savoir qu'un plan a été discuté et accepté : le modèle
    reproposerait le même plan, et la personne cliquerait deux fois pour un
    seul travail. Elle dit aussi les deux choses que l'accord a changées : il
    n'y a plus rien à redemander, et il n'y aura qu'une réponse.
    """
    etapes = state.get("plan_valide") or []
    if not etapes:
        return ""
    return ("\n\nPLAN APPROUVÉ PAR L'UTILISATEUR, à exécuter MAINTENANT :\n"
            + "\n".join(f"{i}. {e}" for i, e in enumerate(etapes, start=1))
            + "\nCes étapes sont accordées : ne redemande AUCUN accord pour elles, "
            "n'en propose pas d'autres, et n'appelle plus `proposer_plan`. Enchaîne "
            "les actions jusqu'au bout, puis rends UNE SEULE réponse contenant tout "
            "ce qui a été produit. Si une étape échoue, dis-le dans cette réponse et "
            "poursuis les suivantes.")


def _consigne_images(state: AgentState) -> str:
    cles = cles_images_du_fil(state)
    if not cles:
        return ""
    return ("\n\nIMAGES DE CETTE CONVERSATION (références, la plus récente en dernier) : "
            + ", ".join(cles) + ". Pour en RETOUCHER une (changer un détail, une couleur, "
            "ajouter ou retirer un élément en gardant tout le reste identique), appelle "
            "`modifier_visuel` avec `image` = cette référence recopiée telle quelle et "
            "`changements` en anglais simple. Sans autre précision, « cette image » "
            "désigne la dernière.")


async def forcer_action_node(state: AgentState, config=None) -> dict:
    """Le modèle a annoncé une action sans l'émettre : on la lui FAIT produire.

    POURQUOI UN APPEL À PART, ET NON UNE CONSIGNE DE PLUS. La version précédente
    se contentait de rendre la main au modèle avec un « ATTENTION, tu as annoncé
    sans exécuter » ajouté au prompt système. Les traces montrent que cette
    consigne ÉTAIT bien présente et qu'il a annoncé quand même : dans le même
    contexte se trouvaient quatre de ses propres tours ne contenant qu'une
    promesse. Une phrase d'instruction ne pèse rien contre quatre démonstrations
    du contraire, et durcir encore la formulation ne ferait que répéter l'échec.

    On change donc de levier. Cet appel-ci part d'un contexte NEUF : ni
    historique, ni documents, ni personnalité — le catalogue des actions, la
    demande, ce qui a déjà été fait, et l'intention annoncée. Sa seule sortie
    admise est un bloc ```action. Le modèle n'a plus à choisir entre parler et
    agir : parler n'est plus une réponse possible.

    Le bloc obtenu repart dans `llm_response` et le tour continue par `tools` :
    l'exécution reste au SEUL endroit qui contrôle les droits, classe l'effet et
    déduplique. Ce nœud choisit, il n'exécute pas.
    """
    import json as _json
    from skills.protocol import (instruction_actions, extraire_action,
                                 rafraichir_catalogue)

    role = state.get("user_role")
    await rafraichir_catalogue()

    consigne = (
        "Tu es le sélecteur d'actions d'un assistant interne. Ta SEULE sortie "
        "admise est un bloc ```action. N'écris ni phrase, ni explication, ni "
        "commentaire : tout texte hors du bloc est jeté sans être lu."
        + instruction_actions(role) +
        "\n\nLes identifiants (document_id, chemins, références) se RECOPIENT "
        "depuis les résultats fournis, caractère pour caractère. N'en invente "
        "jamais un qui ressemble : il serait rejeté."
        "\n\nLa demande n'a presque jamais d'action du MÊME NOM : choisis "
        "celle dont le RÉSULTAT contient l'information demandée, même si son "
        "nom n'y ressemble pas — une action de lecture s'essaie sans coût. "
        "Si, et seulement si, aucune action de la liste ne peut faire "
        "avancer la demande, réponds le seul mot RIEN, sans bloc."
    )

    # LE RÉSULTAT, PAS SEULEMENT LE VERDICT. La première version ne listait que
    # « creer_document : réussie » — sans le `document_id` qu'elle avait rendu.
    # Le modèle, à qui l'on demandait l'action suivante, ne pouvait donc pas la
    # former : il a inventé un identifiant plausible, l'ajout a été refusé, et il
    # a rouvert un document en boucle. Un sélecteur d'actions à qui l'on cache ce
    # que les actions ont produit ne peut pas enchaîner.
    lignes = []
    for r in (state.get("tool_results") or []):
        brut = str(r.get("resultat_masque") or "")
        # Tronqué : ce nœud a besoin des identifiants (en tête des résultats),
        # pas du contenu entier — le modèle principal, lui, l'a déjà.
        extrait = _essentiel(brut, 2500)
        lignes.append(f"- {r.get('skill') or '?'} : "
                      f"{'réussie' if r.get('ok') else 'EN ÉCHEC'}\n"
                      f"  résultat : {extrait}")
    faits = "\n".join(lignes) or "- aucune"

    demande = (
        "Demande de l'utilisateur :\n"
        f"{state.get('anonymized_query') or state.get('query', '')}\n\n"
        f"Actions déjà exécutées à ce tour :\n{faits}\n\n"
        "L'assistant vient d'écrire cette intention SANS l'exécuter :\n"
        f"« {(state.get('llm_response') or '').strip()[:400]} »\n\n"
        "Produis le bloc ```action de la PROCHAINE action à exécuter."
    ) + _consigne_images(state) + _consigne_plan(state)

    # Quand un travail est resté OUVERT, on ne laisse pas deviner : dire quelle
    # fermeture manque évite qu'un document déjà rempli soit rouvert une fois de
    # plus — c'est exactement la boucle qu'on a observée.
    manquante = cloture_attendue(state.get("tool_results"))
    if manquante:
        demande += (
            f"\n\nATTENTION : un document est OUVERT et n'a pas été fermé. Tant "
            f"que `{manquante}` n'a pas été appelé, AUCUN fichier n'existe, il "
            f"n'y a donc rien à télécharger ni à déposer. C'est l'action "
            f"attendue, avec le `document_id` déjà rendu. N'en ouvre pas un "
            f"nouveau : le travail déjà versé serait perdu.")

    # Un document ouvert lors d'un TOUR PRÉCÉDENT n'apparaît pas dans les
    # résultats de ce tour : l'atelier est le seul à s'en souvenir. Sans
    # l'identifiant sous les yeux, ce sélecteur en inventerait un plausible —
    # c'est la boucle documentée plus haut, jouée depuis un autre point d'entrée.
    try:
        import asyncio as _aio
        from bureautique.atelier import ouverts as _docs_ouverts
        from bureautique.atelier import termines as _docs_termines
        _uid = str(state.get("user_id") or "")
        en_cours = await _aio.to_thread(_docs_ouverts, _uid)
        finis = (await _aio.to_thread(_docs_termines, _uid))[:5]
    except Exception:  # noqa: BLE001
        en_cours, finis = [], []
    if en_cours:
        demande += (
            "\n\nDocument(s) encore OUVERTS de tours précédents :\n"
            + _json.dumps(en_cours, ensure_ascii=False)
            + "\nSi l'intention annoncée est de CONTINUER ce document, l'action "
              "attendue est `ajouter_document` (puis `terminer_document`) avec "
              "ce `document_id`, recopié caractère pour caractère.")
    if finis:
        demande += (
            "\n\nDocument(s) TERMINÉS (fichier prêt, pas déposé) :\n"
            + _json.dumps(finis, ensure_ascii=False)
            + "\nSi l'intention est de DÉPOSER ou de montrer un de ces "
              "documents, utilise SON `document_id`, pas celui d'un document "
              "vide.")

    llm = get_llm(LLMTier(state.get("llm_tier", "standard")))
    try:
        reponse = await llm.ainvoke(
            [SystemMessage(content=consigne), HumanMessage(content=demande)],
            config=config)
        texte = str(reponse.content or "")
    except Exception as e:  # noqa: BLE001 - un forçage raté n'est pas une panne
        logger.warning("Forçage d'action impossible : %s", e)
        return {"relance_annonce": True, "forcages": (state.get("forcages") or 0) + 1}

    action, _, erreur = extraire_action(texte, role)
    if action is None:
        # Le drapeau reste levé : le tour est reconnu sans effet, la promesse ne
        # sera ni affichée comme une réponse ni rangée dans l'historique.
        logger.info("Forçage sans résultat (%s)", erreur or "aucun bloc produit")
        return {"relance_annonce": True, "forcages": (state.get("forcages") or 0) + 1}

    logger.info("Action forcée : %s", action.get("skill"))
    return {"relance_annonce": True, "forcages": (state.get("forcages") or 0) + 1,
            "llm_response": "```action\n"
                            + _json.dumps(action, ensure_ascii=False) + "\n```"}


def _reponses_mail_manquantes(state: AgentState, texte: str) -> bool:
    """La demande voulait des PROPOSITIONS DE RÉPONSE aux mails, la rédaction
    n'en porte pas — alors que les mails ont bien été lus.

    Relevé le 01/09 : « fais le point sur tous mes mails … et propose une
    réponse pour chacun » → la synthèse seule. La moitié d'une demande n'est
    pas une réponse : la rédaction est reprise UNE fois (bornée par
    `redaction_forcee`), avec le manque nommé.
    """
    from agents.annonce import demande_des_reponses_mail
    if not demande_des_reponses_mail(state.get("query") or ""):
        return False
    if "reponses_mail" in (texte or ""):
        return False
    return any(isinstance(r, dict) and r.get("ok")
               and r.get("skill") in ("check_mails", "lire_mails", "lire_mail")
               for r in state.get("tool_results") or [])


async def rediger_node(state: AgentState, config=None) -> dict:
    """Les résultats sont là, le modèle a promis au lieu d'écrire : on ferme la
    boucle d'actions et on lui redonne la main pour RÉDIGER.

    Pas de logique ici : c'est `llm_node` qui, voyant `tools_finished` et une
    annonce en réponse précédente, ajoute la consigne qui nomme le défaut. Ce
    nœud ne fait que poser le drapeau — mais un routeur ne peut pas écrire
    l'état, d'où son existence.

    Il pose AUSSI `redaction_forcee` : c'est ce drapeau que `route_apres_llm`
    lit pour ne redemander la rédaction qu'UNE fois. Le laisser à `llm_node`
    seul avait un trou : quand la boucle d'actions sort sur une note, la
    consigne « ta réponse était vide » n'est pas ajoutée (la note explique
    déjà) et le drapeau n'était pas posé non plus — d'où une seconde
    redemande, vers une arête inexistante (KeyError « llm », 31/08)."""
    return {"tools_finished": True, "redaction_forcee": True}


def route_apres_forcage(state: AgentState) -> str:
    """L'action a-t-elle pu être produite ?"""
    from skills.protocol import BLOC_ACTION_RE
    if BLOC_ACTION_RE.search(state.get("llm_response") or ""):
        return "tools"
    # Rien n'a pu être produit : inutile de refaire tourner le modèle, il vient
    # de refuser deux fois. On termine le tour, et l'utilisateur l'apprend.
    return "rehydrate"


def _texte_visible(texte: str) -> str:
    """Ce qui resterait à l'écran une fois la mécanique interne retirée.

    Les blocs d'action ne s'affichent jamais : `rehydrate_node` les retire.
    Un texte qui n'est QUE cela vaut donc zéro pour l'utilisateur, même s'il
    fait deux mille caractères. Cette fonction sert aux deux endroits qui ont
    besoin de la même vérité — le routeur, pour décider s'il faut redemander
    la rédaction, et la réhydratation, pour son dernier filet.
    """
    from skills.protocol import (BLOC_ACTION_RE, BLOC_ACTION_TRONQUE_RE,
                                 BLOC_NATIF_RE, BALISAGE_OUTIL_RE)
    if not isinstance(texte, str):
        return ""
    for motif in (BLOC_ACTION_RE, BLOC_ACTION_TRONQUE_RE, BLOC_NATIF_RE,
                  BALISAGE_OUTIL_RE):
        texte = motif.sub("", texte)
    return texte.strip()


def route_apres_llm(state: AgentState) -> str:
    """Le modèle a-t-il demandé une action ?"""
    from skills.protocol import BLOC_ACTION_RE, BLOC_NATIF_RE
    texte = state.get("llm_response") or ""

    if state.get("tools_finished"):
        # UNE PROMESSE N'EST PAS UNE RÉPONSE, MÊME EN DERNIÈRE PASSE.
        #
        # Ce chemin sortait DIRECTEMENT vers la rédaction, sans regarder ce que
        # le modèle venait d'écrire. Le contrôle « annonce sans acte », plus
        # bas, était donc court-circuité pour le seul cas où il compte le plus :
        # la dernière passe, celle qui doit livrer.
        #
        # Relevé en production : après une arborescence Drive récupérée AVEC
        # SUCCÈS, la réponse affichée était « Je parcours le drive pour trouver
        # des devis. Voici ce que je lance : ». Le travail avait été fait, et
        # l'utilisateur n'en a rien vu. Le garde-fou de `rehydrate_node` ne
        # pouvait pas rattraper ce cas : il exige que RIEN n'ait abouti, or ici
        # une action avait réussi.
        #
        # On redemande donc la rédaction UNE fois, avec une consigne qui nomme
        # le défaut. La reprise est bornée par `redaction_forcee` : un modèle
        # qui annonce en boucle ne doit pas faire tourner le tour sans fin.
        # DEUX SIGNAUX, dont un indépendant du vocabulaire : la liste de verbes
        # ne reconnaissait PAS « Voici ce que je lance : », qui est pourtant le
        # cas relevé en production.
        # TROISIÈME SIGNAL, ET LE PLUS COÛTEUX : RIEN DU TOUT.
        #
        # Le modèle peut rendre une dernière passe qui ne contient QU'un bloc
        # d'action. Ces blocs sont retirés avant affichage — c'est de la
        # mécanique interne — et il ne reste alors rien : `rehydrate_node`
        # tombait sur son dernier filet et servait « Je n'ai pas réussi à
        # formuler de réponse pour cette demande. Pouvez-vous la reformuler ? ».
        #
        # Relevé en production, et c'est le pire cas observé jusqu'ici : 29
        # actions, TOUTES réussies, trois documents terminés, trente et une
        # minutes de travail — et l'utilisateur reçoit une excuse, sans un seul
        # lien. Une phrase qui, en plus, l'accuse d'avoir mal formulé.
        #
        # Un texte vide n'est pas une réponse : on redemande la rédaction, au
        # même titre qu'une promesse.
        if not state.get("redaction_forcee") and (est_une_annonce(texte)
                                                  or promesse_sans_suite(texte)
                                                  or not _texte_visible(texte)
                                                  or _reponses_mail_manquantes(state, texte)):
            logger.info("Dernière passe sans réponse utilisable : rédaction redemandée")
            # « rediger », PAS « llm ». La table des arêtes de ce routeur ne
            # connaît que tools / forcer / rediger / rehydrate : renvoyer « llm »
            # faisait lever un KeyError par LangGraph, le tour mourait et l'écran
            # affichait « Une erreur est survenue ». Relevé le 31/08 sur trois
            # tours (« Non, cherche seulement dans les devis », 280 s ; « fias »,
            # 545 s ; « Détaille par mois sur 2025 »). Le cas exact : la boucle
            # d'actions sort sur une NOTE, la rédaction forcée rend encore une
            # annonce, et `redaction_forcee` n'avait pas été posé (la note en
            # dispensait). `rediger` pose maintenant le drapeau lui-même : une
            # reprise, jamais une boucle.
            return "rediger"
        return "rehydrate"

    # Deux syntaxes : le bloc demandé, et celle que certains modèles de la
    # cascade émettent d'eux-mêmes. Ignorer la seconde la laissait s'afficher.
    demande = BLOC_ACTION_RE.search(texte) or BLOC_NATIF_RE.search(texte)
    if demande:
        return "tools"
    # ANNONCE SANS ACTE. « Je crée le PDF » sans bloc d'action : le tour se
    # terminait ici, sur une promesse présentée comme une réponse.
    #
    # La détection doit vivre ICI et nulle part ailleurs : sans bloc d'action,
    # `tools` n'est JAMAIS appelé, donc un contrôle placé là-bas ne s'exécute
    # pas — il en avait tout l'air, et c'est ce qui l'a rendu difficile à voir.
    # LA LIVRAISON FANTÔME. Relevée le 30/08, trois tours de suite : « fais un
    # word avec toutes les infos de l'entreprise » → aucun skill appelé, et
    # une réponse AU PASSÉ (« voici le document », « il est téléchargeable »)
    # — au pire avec un VRAI fichier du fil collé en guise de preuve, l'Excel
    # de la veille déguisé en Word. `est_une_annonce` couvre le futur ; le
    # passé ne l'était pas, et le forceur — l'outil exact de ce défaut, qui
    # repart d'un contexte NEUF, immunisé contre un historique rempli de
    # fausses réussites que le modèle imite — ne se déclenchait jamais.
    #
    # Deux signaux, tous deux soumis à « RIEN n'a été produit ce tour » :
    #   · la demande réclamait la CRÉATION d'un fichier et il n'existe pas —
    #     sauf question de clarification (elle attend une réponse) ;
    #   · la réponse PRÉTEND livrer — sauf si elle remontre honnêtement un
    #     fichier réel du fil (« remontre-moi la liste » reste légitime).
    visible = _texte_visible(texte)
    fantome = (
        not _blocs_livrables(state.get("tool_results") or [])
        and not state.get("pending_action")
        # Un VISUEL demandé sans image produite est un fantôme au même titre
        # qu'un fichier (01/09 : la retouche « décrite » au passé, sans skill
        # ni carte de validation — le modèle imitait le tour précédent).
        and (((demande_une_production(state.get("query") or "")) and "?" not in visible)
             # Un visuel demandé et REMONTRÉ depuis le fil (« montre moi la
             # photo » → le bloc avec la vraie clé) n'est pas un fantôme :
             # 03/09, le forceur relançait, puis répondait « la photo est
             # affichée ci-dessus » au-dessus de rien.
             or (demande_un_visuel(state.get("query") or "") and "?" not in visible
                 and not _montre_un_fichier_du_fil(visible, state))
             or (pretend_avoir_livre(visible)
                 and not _montre_un_fichier_du_fil(visible, state))))
    if fantome:
        logger.info("Livraison fantôme : la réponse prétend livrer sans production — forçage")
        _tracer_filet(state, "livraison_fantome", "pretention_sans_production",
                      forcages_deja=state.get("forcages") or 0)
    # PROPOSER AU LIEU D'AGIR (31/08). « Je n'ai pas de commande pour… que
    # préférez-vous ? » sans qu'aucun geste ait tourné : la réponse repart au
    # forceur, qui cherche le geste dans un contexte neuf. Après une action,
    # une question de suite est légitime : le prédicat ne s'applique qu'à un
    # tour sans acte.
    sans_agir = (
        propose_au_lieu_d_agir(visible)
        and not any(r.get("ok") for r in (state.get("tool_results") or []))
        and not state.get("pending_action"))
    if sans_agir and not fantome:
        logger.info("Proposition sans acte : la réponse offre de faire au lieu de faire — forçage")
        _tracer_filet(state, "forcage", "proposition_sans_acte",
                      forcages_deja=state.get("forcages") or 0)
    # LE RENVOI AU DÉJÀ-FAIT (01/09). « Fais le point sur les mails » → « cela
    # a déjà été fait tout à l'heure » sans qu'aucun geste ait tourné : une
    # demande répétée se REFAIT — la boîte a changé depuis, et une réponse de
    # mémoire est à la fois périmée et approximative (« environ 70 mails » pour
    # 66 exacts). La réponse repart au forceur, dont le contexte NEUF n'est pas
    # contaminé par la première exécution. Une vraie question sur le passé
    # (« as-tu envoyé le mail ? ») garde sa réponse : c'est la demande qui
    # décide, pas la formulation du modèle.
    deja_fait = (
        renvoie_au_deja_fait(visible)
        and not any(r.get("ok") for r in (state.get("tool_results") or []))
        and not state.get("pending_action")
        and not demande_sur_le_passe(state.get("query") or ""))
    if deja_fait and not fantome and not sans_agir:
        logger.info("Renvoi au déjà-fait : la réponse repousse la demande vers le passé — forçage")
        _tracer_filet(state, "forcage", "renvoi_au_deja_fait",
                      forcages_deja=state.get("forcages") or 0)

    # DEUX SALVES DE QUESTIONS D'AFFILÉE (02/09). Règle de Noa : « au maximum
    # UN message avec une ou des questions complémentaires avant d'agir ; s'il
    # peut y en avoir zéro ou trouver la réponse tout seul, qu'il le fasse ».
    #
    # Une question de clarification est légitime — les filets précédents la
    # laissent passer, et c'est voulu. Ce qui ne l'est pas, c'est la SECONDE :
    # deux tours entiers dépensés sans qu'aucun travail n'avance. Le défaut ne
    # se voit pas dans la réponse seule, seulement dans son rapport à la
    # précédente ; d'où la comparaison avec le dernier message de l'assistant.
    deux_salves = (
        deuxieme_salve_de_questions(visible, _derniere_reponse_assistant(state))
        and not any(r.get("ok") for r in (state.get("tool_results") or []))
        and not state.get("pending_action"))
    if deux_salves and not fantome and not sans_agir and not deja_fait:
        logger.info("Deuxième salve de questions sans acte : la demande n'avance "
                    "pas — forçage")
        _tracer_filet(state, "forcage", "deuxieme_salve_de_questions",
                      forcages_deja=state.get("forcages") or 0)

    if (est_une_annonce(texte) or promesse_sans_suite(texte) or not visible
            or fantome or sans_agir or deja_fait or deux_salves):
        # L'ORDRE COMPTE, ET IL A ÉTÉ FAUX UNE SOIRÉE. Première version : une
        # annonce après un résultat réussi allait droit à la rédaction. Or
        # l'annonce porte souvent sur l'étape SUIVANTE (« je lance le tirage »
        # après avoir préparé le brief) : fermer la boucle à ce moment-là tue
        # le travail en cours. On FORCE donc d'abord — le forceur voit les
        # résultats acquis et choisit la suite — jusqu'à deux fois ; on ne
        # rédige que quand forcer n'est plus permis, et seulement s'il y a
        # quelque chose à rédiger. Une réponse VIDE après un résultat compte
        # comme une promesse : elle n'a rien montré non plus.
        if visible and (state.get("forcages") or 0) < MAX_FORCAGES_PAR_TOUR:
            if not fantome and not sans_agir and not deja_fait:
                _tracer_filet(state, "forcage", "annonce_ou_promesse_sans_acte",
                              forcages_deja=state.get("forcages") or 0)
            return "forcer"
        if any(r.get("ok") for r in (state.get("tool_results") or [])):
            return "rediger"

    # TRAVAIL RESTÉ OUVERT. Le signal qui ne dépend pas des mots : un document
    # ouvert et jamais fermé n'a produit aucun fichier, quoi qu'en dise la
    # réponse. La détection par formulation, elle, énumère des verbes et en
    # oublie toujours un — « je crée » était couvert, « j'y ajoute » non, et le
    # tour s'est arrêté sur la promesse.
    #
    # Pas de boucle possible : la fermeture aboutie retire l'attente, et le
    # budget d'actions du tour borne le reste.
    if cloture_attendue(state.get("tool_results")):
        return "forcer"
    # LA MOITIÉ D'UNE DEMANDE N'EST PAS UNE RÉPONSE (01/09). « Fais le point
    # ET propose une réponse pour chacun » : la synthèse arrive, les cartes de
    # réponse jamais. La rédaction est reprise UNE fois (rediger →
    # redaction_forcee), avec la consigne qui nomme le manque — jamais de
    # contenu écrit en dur.
    if not state.get("redaction_forcee") and _reponses_mail_manquantes(state, visible):
        logger.info("La demande voulait des réponses aux mails : rédaction reprise")
        _tracer_filet(state, "forcage", "reponses_mail_manquantes",
                      forcages_deja=state.get("forcages") or 0)
        return "rediger"
    return "rehydrate"


def route_apres_tools(state: AgentState) -> str:
    """Après une action : rendre la main au modèle, ou terminer le tour.

    On termine dès qu'une action externe attend une validation : le graphe parent
    prend le relais avec `human_gate`.
    """
    if state.get("pending_action"):
        return "rehydrate"
    if state.get("tools_finished"):
        # Boucle terminée mais rien de rédigé : une dernière passe de rédaction,
        # bornée (`tools_finished` étant posé, `route_apres_llm` ira en
        # réhydratation quoi que produise le modèle).
        return "rehydrate" if (state.get("llm_response") or "").strip() else "llm"
    return "llm"


def build_agent1_graph():
    graph = StateGraph(AgentState)
    graph.add_node("rag", rag_node)
    graph.add_node("anonymize", anonymize_node)
    graph.add_node("browser", browser_node)
    graph.add_node("routeur", routeur_node)
    graph.add_node("recherche", recherche_node)
    graph.add_node("llm", llm_node)
    graph.add_node("tools", tools_node)
    graph.add_node("rehydrate", rehydrate_node)
    graph.add_node("validation_check", validation_check_node)

    graph.set_entry_point("rag")
    graph.add_edge("rag", "anonymize")
    # Protection des données -> le routeur (IA) décide -> recherche SI nécessaire.
    graph.add_edge("anonymize", "routeur")
    graph.add_conditional_edges("routeur", route_apres_routeur,
                                {"recherche": "recherche", "llm": "llm"})
    # Le navigateur n'est tenté qu'APRÈS une recherche interne infructueuse.
    graph.add_conditional_edges("recherche", should_use_browser,
                                {"browser": "browser", "llm": "llm"})
    graph.add_edge("browser", "llm")
    # Boucle d'outils : llm -> tools -> llm -> ... jusqu'à ce que le modèle réponde
    # sans demander d'action (ou que le garde-fou l'arrête).
    # Annonce sans acte : on ne redemande pas au modèle de bien vouloir agir (il
    # a déjà refusé une fois, consigne en main) — on lui fait produire l'action
    # dans un appel dédié, puis on l'exécute.
    graph.add_node("forcer", forcer_action_node)
    graph.add_node("rediger", rediger_node)
    graph.add_conditional_edges("llm", route_apres_llm,
                                {"tools": "tools", "forcer": "forcer",
                                 "rediger": "rediger", "rehydrate": "rehydrate"})
    graph.add_edge("rediger", "llm")
    graph.add_conditional_edges("forcer", route_apres_forcage,
                                {"tools": "tools", "rehydrate": "rehydrate"})
    graph.add_conditional_edges("tools", route_apres_tools,
                                {"llm": "llm", "rehydrate": "rehydrate"})
    graph.add_edge("rehydrate", "validation_check")
    graph.add_conditional_edges("validation_check", should_validate)

    return graph.compile()


agent1_graph = build_agent1_graph()
