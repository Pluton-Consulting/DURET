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


async def creer_document(data: dict, user) -> dict:
    """Ouvre un document. Ne produit encore aucun fichier."""
    from bureautique.atelier import ouvrir
    from bureautique.modele import normaliser_entete, BLOCS, FORMATS

    proprio = _proprietaire(user)
    if not proprio:
        return {"message": "Impossible d'ouvrir un document sans compte identifié."}

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
        return {"message": "`elements` doit être une liste de blocs."}

    try:
        retenus = ajouter(jeton, elements[:MAX_PAR_APPEL], _proprietaire(user))
    except KeyError:
        return {"message": "Document inconnu, expiré, ou ouvert par quelqu'un d'autre. "
                           "Rouvre-en un avec `creer_document`."}
    except ValueError as e:
        return {"message": str(e)}

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
        return {"message": "Document inconnu, expiré, ou ouvert par quelqu'un d'autre."}
    except ValueError as e:
        return {"message": str(e)}
    except Exception as e:  # noqa: BLE001 - un rendu raté ne doit pas casser le chat
        logger.warning("Rendu du document %s impossible : %s", jeton[:8], e)
        return {"message": f"Le document n'a pas pu être produit ({e})."}

    entete = f["entete"]
    return {
        "pret": True,
        "document_id": jeton,
        "titre": entete["titre"],
        "format": entete["format"],
        "elements": f["elements"],
        "octets": f["octets"],
        "url": f"/api/documents/{jeton}",
        "note": ("Le fichier est prêt. Annonce-le avec un bloc ```ui de type "
                 "`fichier` portant `url`, `nom`, `format` et `octets`, pour que "
                 "la personne puisse le télécharger d'un clic. Le lien vaut 24 h "
                 "et n'est utilisable que par elle."),
    }
