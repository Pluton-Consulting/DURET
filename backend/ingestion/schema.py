"""
Restructurer avant de ranger : ramener les colonnes d'un export au vocabulaire
commun de son type.

LE PROBLÈME. Chaque logiciel nomme ses colonnes à sa façon — « Nom client »,
« client_nom », « CLIENT », « Raison sociale ». Rangées telles quelles, ces
colonnes restent quatre champs différents : filtrer sur le client obligerait à
connaître les entêtes de chaque fichier importé, et un total « par client »
calculé sur deux exports différents serait faux sans que rien ne le signale.

CE QUI EST FAIT ICI. Un seul appel PAR FICHIER (pas par ligne) demande au modèle
d'associer les colonnes source à un vocabulaire — quand c'est utile, et
seulement alors.

LE VOCABULAIRE EST DÉCOUVERT, PAS DÉCRÉTÉ. Une liste fermée écrite à l'avance ne
peut pas tenir : les exports varient de sujet et de format, et tout ce qui n'y
figurerait pas serait simplement perdu. On fournit donc des AMORCES — les noms
courants d'un type — puis, surtout, le vocabulaire DÉJÀ EMPLOYÉ par les imports
précédents du même type. Le modèle réutilise ce qui existe, et n'invente un nom
que si rien ne convient. La cohérence vient de l'usage accumulé, pas d'un
règlement.

Une colonne trop particulière pour se ranger n'est PAS forcée : elle reste
disponible sous son entête d'origine. Associer à tort est pire que ne pas
associer — un mauvais rangement se paie sur toutes les requêtes suivantes.

CE QUI N'EST PAS FAIT, ET POURQUOI. Les valeurs ne sont ni converties ni typées.
Interpréter « 1 250,00 » ou « 03/04/2025 » suppose un format ; se tromper de
séparateur décimal ou d'ordre jour/mois fausserait des montants et des dates
sans que ça se voie. Seuls les NOMS sont normalisés.

LES COLONNES D'ORIGINE SONT CONSERVÉES INTACTES à côté (`data`). Une association
ratée prive d'un filtre commode, elle ne perd aucune donnée et se refait sans
réimporter le fichier.
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger("duret.ingestion.schema")

# AMORCES, et non liste fermée : les noms courants d'un type, proposés au modèle
# pour qu'un premier import ne parte pas de rien. Elles ne limitent RIEN — un
# export d'un sujet imprévu créera ses propres champs, qui serviront d'amorces
# aux suivants.
AMORCES: dict[str, dict[str, str]] = {
    "client": {
        "reference": "code ou identifiant du client",
        "nom": "nom ou raison sociale",
        "email": "adresse e-mail", "telephone": "téléphone",
        "ville": "ville", "code_postal": "code postal",
        "siret": "SIRET ou numéro d'identification",
    },
    "prospect": {
        "reference": "code ou identifiant",
        "nom": "nom ou raison sociale",
        "statut": "état dans le suivi commercial (à relancer, en cours, perdu…)",
        "origine": "d'où vient le contact",
        "date": "date de contact ou de dernière relance",
        "montant_ht": "montant estimé hors taxes",
        "responsable": "personne qui suit l'affaire",
        "ville": "ville",
    },
    "devis": {
        "reference": "numéro du devis", "client": "client concerné",
        "date": "date d'émission", "montant_ht": "montant hors taxes",
        "statut": "état (envoyé, signé, refusé…)",
        "responsable": "personne qui l'a établi",
    },
    "commande": {
        "reference": "numéro de commande", "fournisseur": "fournisseur",
        "date": "date de commande", "montant_ht": "montant hors taxes",
        "statut": "état (envoyée, reçue, soldée…)",
        "chantier": "chantier ou affaire rattachée",
    },
    "facture": {
        "reference": "numéro de facture", "client": "client concerné",
        "date": "date d'émission", "echeance": "date d'échéance",
        "montant_ht": "montant hors taxes",
        "statut": "état (émise, payée, impayée…)",
    },
    "fournisseur": {
        "reference": "code fournisseur", "nom": "nom ou raison sociale",
        "categorie": "nature de la fourniture ou du service",
        "email": "adresse e-mail", "telephone": "téléphone", "ville": "ville",
    },
    "chantier": {
        "reference": "code du chantier", "nom": "libellé du chantier",
        "client": "client concerné", "ville": "ville",
        "date": "date de démarrage", "statut": "état d'avancement",
        "responsable": "conducteur de travaux ou responsable",
    },
    "planning": {
        "reference": "identifiant de la tâche ou de l'affaire",
        "nom": "libellé", "date": "date",
        "responsable": "personne concernée", "statut": "état",
    },
}

# Un nom de champ est contrôlé par sa FORME, pas par son appartenance à une
# liste. C'est ce qui laisse passer un sujet imprévu tout en gardant des clés
# saines : minuscules, sans espace ni ponctuation, bornées.
_NOM_CHAMP_RE = re.compile(r"^[a-z][a-z0-9_]{1,29}$")

# Garde-fou contre la dérive : un type qui accumulerait des dizaines de champs
# légèrement différents (`ville`, `ville_client`, `ville_chantier`…) redeviendrait
# aussi impraticable que pas de vocabulaire du tout.
MAX_CHAMPS_PAR_TYPE = 40


def amorces_de(source_type: str) -> dict[str, str]:
    """Noms courants du type. Point de départ, jamais une limite."""
    return AMORCES.get((source_type or "").strip(), {})


async def vocabulaire(source_type: str) -> dict[str, str]:
    """Amorces + champs DÉJÀ employés par les imports précédents de ce type.

    C'est ce qui rend la normalisation cohérente sans être rigide : le premier
    import d'un sujet inédit fixe ses noms, les suivants s'y alignent. Ne lève
    jamais — sans base, on retombe sur les seules amorces.
    """
    connus = dict(amorces_de(source_type))
    if not source_type:
        return connus
    try:
        from database.connection import get_db
        async with get_db() as conn:
            lignes = await conn.fetch(
                "SELECT DISTINCT d.key AS cle FROM document_metadata m, "
                "       jsonb_each_text(m.champs) AS d "
                "WHERE m.source_type = $1 LIMIT $2",
                source_type, MAX_CHAMPS_PAR_TYPE)
        for l in lignes:
            connus.setdefault(l["cle"], "déjà utilisé pour ce type")
    except Exception as e:  # noqa: BLE001
        logger.info("Vocabulaire existant illisible (%s) : %s", source_type, e)
    return connus


def valider(source_type: str, brut: dict, colonnes: list[str]) -> dict[str, str]:
    """Ne garde que les associations plausibles : colonne réelle -> nom sain.

    On ne vérifie PAS l'appartenance à une liste : les fichiers importés varient
    de sujet et de format, et refuser tout nom non prévu reviendrait à ne rien
    normaliser dès qu'on sort du cas connu. Ce qui est contrôlé, c'est que la
    colonne existe vraiment dans le fichier et que le nom de champ a une forme
    sûre — ces noms deviennent des clés JSONB, toujours passées en paramètre,
    jamais concaténées dans du SQL.
    """
    if not isinstance(brut, dict):
        return {}
    presentes = {str(c) for c in (colonnes or [])}
    retenu: dict[str, str] = {}
    for colonne, champ in brut.items():
        col, ch = str(colonne or "").strip(), str(champ or "").strip().lower()
        if col not in presentes or not _NOM_CHAMP_RE.match(ch):
            continue
        # Un champ ne peut venir que d'UNE colonne : deux sources pour « nom »
        # rendraient le filtrage dépendant de l'ordre de lecture.
        if ch in retenu.values():
            continue
        retenu[col] = ch
        if len(retenu) >= MAX_CHAMPS_PAR_TYPE:
            break
    return retenu


async def correspondance(source_type: str, colonnes: list[str], echantillon: str) -> dict[str, str]:
    """Associe les colonnes du fichier à un vocabulaire. Ne lève jamais.

    Un seul appel pour tout le fichier : l'association dépend des ENTÊTES, pas
    du contenu de chaque ligne. Appeler par ligne coûterait des milliers de fois
    plus pour le même résultat.
    """
    if not colonnes:
        return {}

    connus = await vocabulaire(source_type)

    # UNIQUEMENT SI NÉCESSAIRE. Quand les entêtes portent déjà les noms du
    # vocabulaire, il n'y a rien à traduire : l'appel coûterait sans rien
    # apporter, et une réponse malheureuse ne pourrait que dégrader.
    deja = {c for c in colonnes if str(c).strip().lower() in connus}
    if len(deja) == len(colonnes):
        logger.info("Association %s : entêtes déjà normalisées, appel évité", source_type)
        return {str(c): str(c).strip().lower() for c in colonnes}

    liste = ("\n".join(f"- {c} : {d}" for c, d in connus.items())
             if connus else "(aucun pour l'instant : ce type est nouveau)")
    invite = (
        "Tu ranges les colonnes d'un fichier importé, pour qu'on puisse plus tard "
        "l'interroger avec les mêmes mots que les autres fichiers du même genre.\n"
        f"Type du fichier : « {source_type} »\n"
        f"Colonnes du fichier : {', '.join(str(c) for c in colonnes)}\n"
        f"Extrait (anonymisé) :\n{(echantillon or '')[:800]}\n\n"
        f"Noms DÉJÀ utilisés pour ce type :\n{liste}\n\n"
        "Règles :\n"
        "- Réutilise un nom de la liste dès qu'il convient : c'est ce qui rend "
        "deux exports différents interrogeables ensemble.\n"
        "- Si aucun ne convient, propose un nom neuf, court, en minuscules sans "
        "accent ni espace (ex. surface_m2, date_reception).\n"
        "- Laisse de côté une colonne trop particulière pour se ranger : mieux "
        "vaut ne pas associer qu'associer à tort.\n"
        "- Un même nom ne peut désigner qu'une seule colonne.\n"
        'Réponds UNIQUEMENT par un objet JSON {"colonne du fichier": "nom"}.'
    )

    try:
        from langchain_core.messages import HumanMessage
        from llm.router import get_llm, LLMTier
        reponse = await get_llm(LLMTier.LIGHT).ainvoke([HumanMessage(content=invite)])
        texte = str(reponse.content)
        trouve = re.search(r"\{.*\}", texte, re.S)
        propose = json.loads(trouve.group(0)) if trouve else {}
    except Exception as e:  # noqa: BLE001 - sans association, l'import reste valide
        logger.info("Association des colonnes indisponible (%s) : %s", source_type, e)
        return {}

    retenu = valider(source_type, propose, colonnes)
    logger.info("Association %s : %d colonne(s) sur %d", source_type, len(retenu), len(colonnes))
    return retenu
