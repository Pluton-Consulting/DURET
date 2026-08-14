"""
Outil « documents » — produire un fichier téléchargeable en un seul appel.

L'atelier en trois temps (`creer_document`, `ajouter_document`,
`terminer_document`) existe pour une raison valable : un rapport de deux cents
pages ne tient pas dans une réponse de modèle, et il faut pouvoir le remplir en
plusieurs fois. Mais il fait payer TROIS allers-retours au document d'une page,
qui est le cas courant — mesuré : 132 secondes pour un PDF portant un seul
nombre, dont 86 d'attente du modèle.

`produire` réunit les trois gestes. L'atelier reste disponible, pour ce qu'il
justifie vraiment : les documents trop gros pour une seule réponse.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("duret.outils.documents")

# Au-delà, c'est un gros document : l'atelier en plusieurs versements est le bon
# outil, et cette limite le dit au lieu de tronquer en silence.
MAX_BLOCS_EN_UNE_FOIS = 400


async def produire(titre: str, blocs: list, proprietaire: str,
                   format: str = "pdf", entete: str = "", pied: str = "",
                   numeroter: bool = True) -> dict:
    """Crée, remplit et finalise un document. Rend le lien de téléchargement.

    Le contenu est DÉCRIT, jamais programmé : une liste de blocs du vocabulaire
    (titre, paragraphe, liste, tableau, saut_page, feuille). C'est le même
    vocabulaire que `ajouter_document` — on ne compose que l'enchaînement, pas
    le format.
    """
    from bureautique.atelier import ouvrir, ajouter, terminer, abandonner
    from bureautique.modele import normaliser_entete

    if not isinstance(blocs, list) or not blocs:
        raise ValueError(
            "`blocs` doit être une liste non vide décrivant le contenu. "
            'Exemple : [{"bloc":"paragraphe","texte":"18","taille":"tres_grand",'
            '"gras":true,"couleur":"rouge","centre":true}]')
    if len(blocs) > MAX_BLOCS_EN_UNE_FOIS:
        raise ValueError(
            f"{len(blocs)} blocs d'un coup, au-delà de {MAX_BLOCS_EN_UNE_FOIS}. "
            "Pour un document de cette taille, ouvre-le avec `creer_document` "
            "et verse le contenu en plusieurs fois.")

    en_tete = normaliser_entete({"titre": titre, "format": format,
                                 "entete": entete, "pied": pied,
                                 "numeroter": numeroter})
    jeton = ouvrir(en_tete, proprietaire)

    # UN PRODUIRE QUI ÉCHOUE NE LAISSE PAS DE FANTÔME. `ouvrir` a déjà créé la
    # fiche : lever sans nettoyer laissait un document ouvert par échec — et au
    # cinquième, le quota fermait LE PLUS ANCIEN, c'est-à-dire le vrai document
    # en cours de rédaction ; « ajouter_document » répondait alors « document
    # inconnu ». Depuis que les documents ouverts sont montrés au modèle d'un
    # tour à l'autre, un fantôme serait en plus une fausse piste offerte.
    try:
        retenus = ajouter(jeton, blocs, proprietaire)
        if not retenus:
            # `terminer` refuserait un document vide ; le dire ici est plus
            # utile, on sait encore POURQUOI il est vide. Et on MONTRE ce qui
            # est arrivé : « type inconnu » tout court renvoyait le modèle
            # deviner, à une minute l'aller-retour — avec la forme reçue sous
            # les yeux, il se corrige en UN coup.
            premier = blocs[0] if blocs else None
            recu = (f"type={premier.get('bloc') or premier.get('type')!r}, "
                    f"champs={sorted(premier.keys())}"
                    if isinstance(premier, dict) else repr(premier)[:120])
            raise ValueError(
                "Aucun bloc n'a été retenu : type de bloc inconnu ou contenu "
                f"vide. Premier élément reçu : {recu}. Vocabulaire accepté : "
                "titre, paragraphe (champ `texte`), liste (items[]), tableau "
                "(entetes[], lignes[[]]), saut_page, feuille.")
        fiche = terminer(jeton, proprietaire)
    except BaseException:
        abandonner(jeton, proprietaire)
        raise
    ignores = len(blocs) - retenus
    logger.info("Document %s produit en un appel : %s, %d éléments",
                jeton[:8], en_tete["format"], retenus)
    return {
        "pret": True, "document_id": jeton, "titre": en_tete["titre"],
        "format": en_tete["format"], "elements": retenus,
        "ignores": ignores, "octets": fiche["octets"],
        "url": f"/api/documents/{jeton}",
        # Le début RÉEL du fichier, pour l'aperçu dans le chat.
        "extrait": fiche.get("extrait") or "",
        "note": ("Le fichier est prêt. Annonce-le avec DEUX blocs ```ui : un "
                 "`doc_apercu` portant `titre`, `format` et `extrait` (recopie "
                 "l'extrait fourni TEL QUEL), puis un `fichier` portant `url`, "
                 "`nom`, `format` et `octets`. "
                 + (f"{ignores} bloc(s) écarté(s) : type inconnu ou vide."
                    if ignores else "")),
    }
