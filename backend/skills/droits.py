"""
Skill natif : dire à quelqu'un ce à quoi il a droit.

Relevé en recette (§15) : « Un collaborateur terrain peut-il consulter les
marges ? » → « Je n'ai pas d'information concernant les droits d'accès ». Et
« Quels sont mes droits ? » → « Je n'ai pas accès à ces informations ».

L'application APPLIQUE pourtant ce cloisonnement à chaque requête. Elle savait
l'imposer sans savoir l'expliquer, ce qui est le pire des deux mondes : un
utilisateur à qui l'on refuse une donnée sans pouvoir lui dire pourquoi conclut
à une panne, et un dirigeant ne peut pas vérifier que la gouvernance qu'il a
demandée est réellement en place.

La réponse est LUE dans la configuration d'accès, jamais rédigée dans le prompt :
un texte décrivant les droits divergerait du code au premier rôle ajouté, et
c'est exactement le genre d'écart qui se lit comme une fuite.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("duret.skills.droits")

# Ce que chaque niveau protège, en français. Le niveau vient du code ;
# seule sa TRADUCTION vit ici.
SENS_NIVEAUX = {
    "all": "informations de travail ouvertes à toute l'entreprise",
    "commercial_plus": "suivi commercial : devis, prospects, relances",
    "bureau_etudes_plus": "études et conception : plans, métrés, chiffrages",
    "direction_only": "données stratégiques : marges, indicateurs financiers, "
                      "statistiques globales, connaissances tirées des mails",
    "admin_only": "configuration de l'infrastructure et gestion des utilisateurs",
}


async def mes_droits(data: dict, user) -> dict:
    """Rôle, niveaux visibles, boîtes accessibles — et ce qui reste fermé."""
    from security.acces import ROLE_ACCESS_LEVELS, NIVEAUX, niveaux_visibles

    role = (getattr(user, "role", "") or "").strip()
    vus = niveaux_visibles(role)
    fermes = [n for n in NIVEAUX if n not in vus]

    boites: list[str] = []
    try:
        from mail.authorization import boites_par_id
        boites = await boites_par_id(str(getattr(user, "id", "") or ""))
    except Exception as e:  # noqa: BLE001 - un rôle reste descriptible sans les boîtes
        logger.info("Boîtes indisponibles pour la description des droits : %s", e)

    # Décrire un droit, ce n'est pas l'exercer : le super_admin et la direction
    # PEUVENT accéder à une autre boîte en la nommant, `mes_droits` doit le dire
    # même si leur défaut de lecture est désormais leur seule boîte (01/09).
    from mail.authorization import acces_total
    toutes = boites == ["*"] or acces_total(role)
    connu = role in ROLE_ACCESS_LEVELS

    return {
        # QUI PARLE. Le serveur le sait — c'est la session. Sans cette ligne,
        # « une colonne avec MON mail » devenait une question posée à
        # l'utilisateur, et le tour se terminait sans rien produire (relevé le
        # 23/08). On ne demande pas à quelqu'un ce qu'on a déjà sous la main.
        "identite": {
            "nom": str(getattr(user, "name", "") or "").strip(),
            "email": str(getattr(user, "email", "") or "").strip(),
        },
        "role": role or "(inconnu)",
        "role_reconnu": connu,
        "acces_autorises": [{"niveau": n, "contenu": SENS_NIVEAUX.get(n, n)}
                            for n in NIVEAUX if n in vus],
        "acces_refuses": [{"niveau": n, "contenu": SENS_NIVEAUX.get(n, n)}
                          for n in fermes],
        "mails": ("toutes les boîtes du domaine" if toutes
                  else (boites or "aucune boîte accessible")),
        "regles": [
            "Le cloisonnement s'applique à CHAQUE recherche : ce qui est fermé "
            "n'apparaît pas dans les résultats, il n'est pas seulement masqué.",
            "Les mails sont cloisonnés par PERSONNE (boîte propre + délégations), "
            "pas par rôle : deux collègues de même rôle ne voient pas le courrier "
            "l'un de l'autre.",
            "Les documents et connaissances sont cloisonnés par RÔLE : deux "
            "personnes du même rôle voient la même chose.",
            "Un rôle non reconnu reçoit le niveau le plus bas : une faute de "
            "frappe ne peut pas ouvrir un accès.",
        ],
        "note": ("Ce sont les droits RÉELLEMENT appliqués, lus dans la configuration. "
                 "Réponds à partir d'eux, n'invente aucune autre règle. Pour parler "
                 "d'un AUTRE rôle que celui-ci, appuie-toi sur `acces_refuses` et sur "
                 "les règles ci-dessus."),
        "grille_par_role": {r: sorted(n) for r, n in ROLE_ACCESS_LEVELS.items()},
    }
