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


async def creer_document(data: dict, user) -> dict:
    """Ouvre un document. Ne produit encore aucun fichier."""
    from bureautique.atelier import ouvrir
    from bureautique.modele import normaliser_entete, BLOCS, FORMATS

    proprio = _proprietaire(user)
    if not proprio:
        _echec("Impossible d'ouvrir un document sans compte identifié.")

    entete = normaliser_entete(data or {})
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
        "url": f"/api/documents/{jeton}",
        # L'extrait est le DÉBUT RÉEL du fichier rendu : c'est lui qui alimente
        # l'aperçu dans le chat. Sans lui, le modèle « montrait » un contenu
        # recomposé de mémoire, qui divergeait du fichier téléchargé.
        "extrait": f.get("extrait") or "",
        "note": ("Le fichier est prêt. Annonce-le avec DEUX blocs ```ui : un "
                 "`doc_apercu` portant `titre`, `format` et `extrait` (recopie "
                 "l'extrait fourni TEL QUEL), puis un `fichier` portant `url`, "
                 "`nom`, `format` et `octets` pour le téléchargement. Le lien "
                 "vaut 24 h et n'est utilisable que par la personne."),
    }
