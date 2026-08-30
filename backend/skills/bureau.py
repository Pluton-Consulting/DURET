"""
Skills natifs : produire un document téléchargeable.

TROIS GESTES, ET C'EST CE QUI PERMET LES GROS DOCUMENTS :
  `creer_document`   ouvre et décrit l'enveloppe (format, titre, en-tête, pied) ;
  `ajouter_document` verse des éléments, autant de fois qu'il le faut ;
  `terminer_document` rend le fichier et donne le lien.

Un rapport de deux cents pages ne tient pas dans une réponse de modèle. Sans
cette découpe, la seule façon de le produire serait de tout demander d'un coup,
et la réponse serait tronquée au milieu d'un tableau sans que rien ne le
signale. Ici, chaque ajout est écrit sur disque : ce qui est versé est acquis.

Le contenu est DÉCRIT, jamais programmé. Le modèle dit « un tableau avec ces
entêtes et ces lignes » ; le code de rendu est écrit une fois et testé. Faire
écrire du python-docx au modèle demanderait d'exécuter du code produit par lui,
avec les échecs qu'aucune vérification n'anticipe.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("duret.skills.bureau")

MAX_PAR_APPEL = 400


def _proprietaire(user) -> str:
    return str(getattr(user, "id", "") or "")


def _echec(message: str):
    """Un échec doit se signaler comme un échec.

    Ces fonctions rendaient `{"message": "Document inconnu, expiré..."}` — un
    dictionnaire ordinaire, donc une RÉUSSITE aux yeux de tout le reste du
    système : `ok` valait True, le journal d'écran affichait l'action comme
    aboutie, et la passe suivante lisait « ajouter_document : réussie ».

    Relevé en production : le modèle a cru son document rempli, puis a découvert
    dans le texte du résultat qu'il ne l'était pas. Il a alors rouvert un
    document, quatre fois de suite, jusqu'à épuiser le budget d'actions du tour.
    Une heure de tourne-en-rond, née d'un booléen qui disait le contraire du
    message juste à côté.
    """
    from skills.erreurs import SkillError
    raise SkillError(message)


def _meme_titre(a: str, b: str) -> bool:
    """« test 2 » et « Test 2  » désignent le même document."""
    return " ".join((a or "").lower().split()) == " ".join((b or "").lower().split())


async def creer_document(data: dict, user) -> dict:
    """Ouvre un document. Ne produit encore aucun fichier."""
    from bureautique.atelier import ouvrir, ouverts
    from bureautique.modele import normaliser_entete, BLOCS, FORMATS

    proprio = _proprietaire(user)
    if not proprio:
        _echec("Impossible d'ouvrir un document sans compte identifié.")

    entete = normaliser_entete(data or {})

    # UN TITRE DÉJÀ OUVERT NE S'OUVRE PAS UNE DEUXIÈME FOIS. Relevé en
    # production : quatre documents quasi identiques ouverts par des tentatives
    # interrompues (« Méthodes de pose de carrelage » × 2, une variante, plus
    # le vrai) — le modèle s'est mis à les confondre, l'utilisateur à demander
    # lesquels étaient identiques, et le quota a fini par évincer le document
    # rempli. Rouvrir un titre déjà ouvert n'est JAMAIS ce que la conversation
    # voulait : on rend l'existant, avec son compte d'éléments, et la reprise
    # continue au lieu de cloner. Repartir de zéro reste possible : abandonner
    # d'abord, ouvrir ensuite.
    for d in ouverts(proprio):
        if _meme_titre(d.get("titre"), entete["titre"]):
            # CETTE NOTE NE DOIT JAMAIS PROPOSER DE DÉTRUIRE.
            #
            # Elle se terminait par « Pour repartir de zéro :
            # `abandonner_document` d'abord ». Relevé en production le 14/08 :
            # la demande disait « crée un NOUVEAU fichier docx », le modèle a
            # lu « un document existe déjà, on me dit comment repartir de
            # zéro », et il a jeté 22 blocs de rédaction — puis recommencé,
            # deux fois, huit minutes durant.
            #
            # Le document rendu ici EST le fichier demandé : il vient d'être
            # ouvert pour cette demande, ou il l'a été juste avant dans le même
            # tour. Le dire comme une RÉUSSITE ferme la porte à l'interprétation
            # qui détruit. L'abandon reste possible — il faut simplement que
            # l'utilisateur le demande, pas qu'on le suggère.
            nb = d.get("elements", 0)
            return {
                "document_id": d["document_id"],
                "format": d.get("format"),
                "titre": d.get("titre"),
                "deja_ouvert": True,
                "elements": nb,
                "note": (f"C'est BIEN le document demandé : il est déjà ouvert "
                         f"sous ce titre et contient {nb} élément(s), il n'y "
                         "avait donc rien à créer, et c'est normal. Poursuis-le "
                         "avec `ajouter_document` en repartant de la SUITE (ne "
                         "réécris pas ce qui est déjà versé), puis termine-le. "
                         "Ne le jette pas et n'en ouvre pas un autre : ce "
                         "serait perdre le contenu déjà écrit."),
            }

    jeton = ouvrir(entete, proprio)
    return {
        "document_id": jeton,
        "format": entete["format"],
        "titre": entete["titre"],
        "formats_possibles": list(FORMATS),
        "blocs_possibles": BLOCS,
        "note": ("Document OUVERT, encore vide et sans fichier. Verse le contenu "
                 "avec `ajouter_document` (en plusieurs appels si le document est "
                 "long, il n'y a pas de limite au nombre d'appels), puis appelle "
                 "`terminer_document` pour obtenir le lien de téléchargement."),
    }


async def abandonner_document(data: dict, user) -> dict:
    """Jette un document ouvert : contenu perdu, aucun fichier produit.

    « Supprime les docs 2 et 3 qui sont ouverts » n'avait AUCUNE action pour
    répondre : l'atelier savait abandonner, mais rien ne l'exposait au modèle,
    qui répondait « la suppression n'est pas disponible » pendant que les
    fantômes s'accumulaient jusqu'au quota.

    UN DOCUMENT REMPLI NE SE JETTE PAS SUR UN MALENTENDU. Le geste a servi, dès
    sa mise en service, à détruire 22 blocs de rédaction en cours parce que la
    demande contenait le mot « nouveau ». Vider une corbeille est réversible ;
    ceci ne l'est pas — le contenu n'existe nulle part ailleurs. Un document
    VIDE part sans cérémonie (c'est le cas d'usage réel : faire le ménage) ;
    dès qu'il porte du travail, il faut le demander explicitement.
    """
    from bureautique.atelier import abandonner, fiche

    proprio = _proprietaire(user)
    jeton = (data.get("document_id") or "").strip()
    if not jeton:
        _echec("Donne le `document_id` du document à abandonner.")

    f = fiche(jeton, proprio)
    if f is None:
        _echec("Document inconnu, expiré, ou ouvert par quelqu'un d'autre. "
               "Reprends un `document_id` de la liste des documents ouverts.")
    nb = int(f.get("elements") or 0)
    if nb and not data.get("confirme"):
        _echec(
            f"REFUSÉ : ce document contient {nb} élément(s) de contenu déjà "
            "écrit, qui seraient définitivement perdus. Si tu voulais "
            "simplement continuer le travail, appelle `ajouter_document` avec "
            "ce `document_id`. Si la personne a EXPRESSÉMENT demandé de le "
            "jeter, rappelle l'action avec `confirme` à true.")

    if not abandonner(jeton, proprio):
        _echec("Document inconnu, expiré, ou ouvert par quelqu'un d'autre. "
               "Reprends un `document_id` de la liste des documents ouverts.")
    return {"abandonne": True, "document_id": jeton, "elements_perdus": nb,
            "note": "Document jeté : son contenu est perdu, aucun fichier ne sera produit."}


async def ajouter_document(data: dict, user) -> dict:
    """Verse des éléments dans un document ouvert."""
    from bureautique.atelier import ajouter, fiche

    jeton = (data.get("document_id") or "").strip()
    elements = data.get("elements") or data.get("contenu") or []
    if isinstance(elements, dict):
        elements = [elements]
    if not isinstance(elements, list):
        _echec("`elements` doit être une liste de blocs.")

    try:
        retenus = ajouter(jeton, elements[:MAX_PAR_APPEL], _proprietaire(user))
    except KeyError:
        # Le `document_id` reçu ne correspond à aucun document ouvert. Le plus
        # souvent il a été INVENTÉ : les vrais jetons sont imprévisibles, un
        # modèle qui ne l'a pas sous les yeux en fabrique un qui y ressemble.
        _echec("Document inconnu, expiré, ou ouvert par quelqu'un d'autre. "
               "Reprends le `document_id` EXACT rendu par `creer_document`, "
               "ou rouvre un document.")
    except ValueError as e:
        _echec(str(e))

    f = fiche(jeton, _proprietaire(user)) or {}
    ignores = len(elements) - retenus
    return {
        "document_id": jeton,
        "ajoutes": retenus,
        "total": f.get("elements", retenus),
        # Un bloc écarté doit se voir : un trou silencieux se découvre une fois
        # le document envoyé, c'est-à-dire trop tard.
        "ignores": ignores,
        "note": (f"{retenus} élément(s) ajouté(s)."
                 + (f" {ignores} écarté(s) : type de bloc inconnu ou contenu vide."
                    if ignores > 0 else "")
                 + " Continue d'ajouter, ou appelle `terminer_document`."),
    }


async def terminer_document(data: dict, user) -> dict:
    """Rend le fichier et donne le lien de téléchargement."""
    from bureautique.atelier import terminer

    jeton = (data.get("document_id") or "").strip()
    try:
        f = terminer(jeton, _proprietaire(user))
    except KeyError:
        _echec("Document inconnu, expiré, ou ouvert par quelqu'un d'autre. "
               "Reprends le `document_id` EXACT rendu par `creer_document`.")
    except ValueError as e:
        _echec(str(e))
    except Exception as e:  # noqa: BLE001 - un rendu raté ne doit pas casser le chat
        logger.warning("Rendu du document %s impossible : %s", jeton[:8], e)
        _echec(f"Le document n'a pas pu être produit ({e}).")

    entete = f["entete"]
    return {
        "pret": True,
        "document_id": jeton,
        "titre": entete["titre"],
        "format": entete["format"],
        "elements": f["elements"],
        "octets": f["octets"],
        # « Il fait combien de pages ? » est la première question posée sur un
        # document produit — elle restait sans réponse possible.
        "pages_estimees": f.get("pages_estimees"),
        "url": f"/api/documents/{jeton}",
        # L'extrait est le DÉBUT RÉEL du fichier rendu : c'est lui qui alimente
        # l'aperçu dans le chat. Sans lui, le modèle « montrait » un contenu
        # recomposé de mémoire, qui divergeait du fichier téléchargé.
        "extrait": f.get("extrait") or "",
        # LA CARTE FICHIER EST MÉCANIQUE. Relevé le 30/08, la saga du « Word
        # Symbiose » : le document était bien produit (l'atelier l'atteste),
        # mais sa carte dépendait du MODÈLE — la note lui demandait d'écrire le
        # bloc ```ui, et il ne le faisait pas, ou l'inventait avec une URL
        # morte (effacée à juste titre). Résultat : un fichier réel, jamais
        # affiché, sur des tours entiers. Le bloc vit désormais dans la sortie
        # du skill : `_livrables_a_l_ecran` garantit qu'il atteint l'écran et
        # l'historique, que le modèle l'ait recopié ou non.
        "bloc_ui": {"type": "fichier", "url": f"/api/documents/{jeton}",
                    "nom": f"{entete['titre']}.{entete['format']}",
                    "titre": entete["titre"], "format": entete["format"],
                    "octets": f["octets"]},
        "note": ("Le fichier est prêt : sa carte de téléchargement est ajoutée "
                 "AUTOMATIQUEMENT sous ta réponse. N'écris AUCUN bloc ```ui "
                 "pour ce fichier — ni `fichier`, ni `doc_apercu` — et "
                 "n'invente jamais son adresse. Le lien vaut 24 h et n'est "
                 "utilisable que par la personne."),
    }
