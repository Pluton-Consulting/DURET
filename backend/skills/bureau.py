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
            return {
                "document_id": d["document_id"],
                "format": d.get("format"),
                "titre": d.get("titre"),
                "deja_ouvert": True,
                "elements": d.get("elements", 0),
                "note": (f"Un document de ce titre est DÉJÀ ouvert, avec "
                         f"{d.get('elements', 0)} élément(s). AUCUN nouveau "
                         "document n'a été créé : continue CELUI-CI avec "
                         "`ajouter_document` (sans réécrire le début), puis "
                         "`terminer_document`. Pour repartir de zéro : "
                         "`abandonner_document` d'abord."),
            }

    jeton = ouvrir(entete, proprio)
    return {
        "document_id": jeton,
        "format": entete["format"],
        "titre": entete["titre"],
        "formats_possibles": list(FORMATS),
        "blocs_possibles": BLOCS,
        "note": ("Document OUVERT, encore vide et sans fichier. Verse le contenu "
                 "avec `ajouter_document` — en plusieurs appels si le document est "
                 "long, il n'y a pas de limite au nombre d'appels — puis appelle "
                 "`terminer_document` pour obtenir le lien de téléchargement."),
    }


async def abandonner_document(data: dict, user) -> dict:
    """Jette un document ouvert : contenu perdu, aucun fichier produit.

    « Supprime les docs 2 et 3 qui sont ouverts » n'avait AUCUNE action pour
    répondre : l'atelier savait abandonner, mais rien ne l'exposait au modèle,
    qui répondait « la suppression n'est pas disponible » pendant que les
    fantômes s'accumulaient jusqu'au quota.
    """
    from bureautique.atelier import abandonner

    jeton = (data.get("document_id") or "").strip()
    if not jeton:
        _echec("Donne le `document_id` du document à abandonner.")
    if not abandonner(jeton, _proprietaire(user)):
        _echec("Document inconnu, expiré, ou ouvert par quelqu'un d'autre. "
               "Reprends un `document_id` de la liste des documents ouverts.")
    return {"abandonne": True, "document_id": jeton,
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
        "note": ("Le fichier est prêt. Annonce-le avec DEUX blocs ```ui : un "
                 "`doc_apercu` portant `titre`, `format`, `pages` (= "
                 "pages_estimees) et `extrait` (recopie l'extrait fourni TEL "
                 "QUEL), puis un `fichier` portant `url`, `nom`, `format` et "
                 "`octets` pour le téléchargement. Le lien vaut 24 h et n'est "
                 "utilisable que par la personne."),
    }
