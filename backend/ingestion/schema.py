"""
Restructurer avant de ranger : ramener les colonnes d'un export au vocabulaire
commun de son type.

LE PROBLÈME. Chaque logiciel nomme ses colonnes à sa façon — « Nom client »,
« client_nom », « CLIENT », « Raison sociale ». Rangées telles quelles, ces
colonnes restent quatre champs différents : filtrer sur le client obligerait à
connaître les entêtes de chaque fichier importé, et un total « par client »
calculé sur deux exports différents serait faux sans que rien ne le signale.

CE QUI EST FAIT ICI. Un seul appel PAR FICHIER (pas par ligne) demande au modèle
d'associer chaque colonne source à un champ d'une liste FERMÉE, propre au type
détecté. Le résultat est filtré contre cette liste : un nom de champ inventé est
écarté ici, il n'atteint jamais la base.

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

# Vocabulaire commun, par type. Volontairement COURT : chaque champ doit se
# retrouver dans la plupart des exports du métier, sinon il reste vide et donne
# l'illusion d'une donnée absente alors qu'elle n'a jamais été demandée.
CHAMPS: dict[str, dict[str, str]] = {
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

_NOM_CHAMP_RE = re.compile(r"^[a-z_]{2,20}$")


def champs_de(source_type: str) -> dict[str, str]:
    """Vocabulaire du type, ou vide si le type n'en a pas (document libre)."""
    return CHAMPS.get((source_type or "").strip(), {})


def valider(source_type: str, brut: dict, colonnes: list[str]) -> dict[str, str]:
    """Ne garde que les associations vraies : colonne existante -> champ connu.

    Le modèle propose ; cette fonction dispose. Sans ce filtre, un champ inventé
    s'installerait en base et donnerait des résultats vides à toute requête qui
    s'y fierait — un vide indiscernable d'une donnée réellement absente.
    """
    connus = champs_de(source_type)
    if not connus or not isinstance(brut, dict):
        return {}
    presentes = {str(c) for c in (colonnes or [])}
    retenu: dict[str, str] = {}
    for colonne, champ in brut.items():
        col, ch = str(colonne or "").strip(), str(champ or "").strip().lower()
        if col not in presentes or ch not in connus or not _NOM_CHAMP_RE.match(ch):
            continue
        # Un champ ne peut venir que d'UNE colonne : deux sources pour « nom »
        # rendraient le filtrage dépendant de l'ordre de lecture.
        if ch in retenu.values():
            continue
        retenu[col] = ch
    return retenu


async def correspondance(source_type: str, colonnes: list[str], echantillon: str) -> dict[str, str]:
    """Associe les colonnes du fichier au vocabulaire du type. Ne lève jamais.

    Un seul appel pour tout le fichier : l'association dépend des ENTÊTES, pas
    du contenu de chaque ligne. Appeler par ligne coûterait des milliers de fois
    plus pour le même résultat.
    """
    connus = champs_de(source_type)
    if not connus or not colonnes:
        return {}

    liste = "\n".join(f"- {c} : {d}" for c, d in connus.items())
    invite = (
        "Tu ranges les colonnes d'un fichier importé.\n"
        f"Colonnes du fichier : {', '.join(str(c) for c in colonnes)}\n"
        f"Extrait (anonymisé) :\n{(echantillon or '')[:800]}\n\n"
        f"Champs attendus pour un fichier de type « {source_type} » :\n{liste}\n\n"
        "Associe chaque colonne du fichier à UN champ de la liste, quand la "
        "correspondance est évidente. Laisse de côté les colonnes qui ne "
        "correspondent à rien : mieux vaut ne pas associer qu'associer à tort. "
        "N'invente aucun nom de champ.\n"
        'Réponds UNIQUEMENT par un objet JSON {"colonne du fichier": "champ"}.'
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
