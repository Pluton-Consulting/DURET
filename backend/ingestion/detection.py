"""
Détection automatique de la nature d'un fichier importé.

Le modèle reçoit UNIQUEMENT la structure (noms de colonnes + un échantillon
ANONYMISÉ) et propose : un type de source, la colonne identifiante, un résumé
en français. Rien n'est écrit : la proposition est soumise à l'utilisateur, qui
la corrige et la valide (l'IA propose, l'humain décide).

Dégradation propre : sans LLM disponible, on retombe sur une heuristique par
mots-clés. L'import reste donc toujours possible.
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger("duret.ingestion.detection")

# Types de source connus du RAG (cf. ingestion/pipeline.py et le prompt d'agent1).
#
# Un type par FICHIER : c'est LUI qui scinde réellement la mémoire. Deux natures
# rangées sous le même type ne se séparent plus jamais ensuite, ni au filtrage,
# ni au comptage — et il faudrait tout réimporter pour les démêler. On distingue
# donc ce qui répond à des questions différentes : un prospect ne se compte pas
# avec un client signé, un bon de commande ne s'additionne pas avec un catalogue
# fournisseur.
TYPES = {
    "chantier": "chantiers, suivi de travaux, avancement",
    "devis": "devis, propositions commerciales, chiffrages",
    "commande": "bons de commande, achats, approvisionnements, commandes fournisseurs",
    "facture": "factures, situations de travaux, règlements, impayés",
    "client": "fiches et listes de CLIENTS (affaires déjà signées)",
    "prospect": "suivi commercial : PROSPECTS, opportunités, relances, pipeline",
    "fournisseur": "fournisseurs, sous-traitants, catalogues, tarifs",
    "planning": "plannings, calendriers, temps passé",
    "document": "document libre (compte rendu, CCTP, courrier, note)",
}

_INDICES = {
    "chantier": ("chantier", "travaux", "avancement", "site", "ouvrage"),
    "devis": ("devis", "proposition", "chiffrage", "dpgf", "estimation"),
    "facture": ("facture", "situation", "reglement", "règlement", "echeance", "échéance", "acompte"),
    "client": ("client", "prospect", "contact", "societe", "société", "raison sociale"),
    "fournisseur": ("fournisseur", "commande", "catalogue", "tarif", "achat", "appro"),
    "planning": ("planning", "calendrier", "semaine", "heures", "pointage", "date debut", "date début"),
}


def _heuristique(nom_fichier: str, colonnes: list[str], texte: str = "") -> dict:
    """Repli sans LLM : score par mots-clés sur le nom, les colonnes et le texte."""
    base = f"{nom_fichier} {' '.join(colonnes)} {texte[:2000]}".lower()
    scores = {t: sum(base.count(i) for i in indices) for t, indices in _INDICES.items()}
    meilleur = max(scores, key=scores.get)
    if scores[meilleur] == 0:
        meilleur = "document"
    return {
        "source_type": meilleur,
        "confiance": "faible",
        "resume": "Détection par mots-clés (modèle indisponible). Vérifiez le type avant de valider.",
        "id_col": _colonne_id_probable(colonnes),
    }


def _colonne_id_probable(colonnes: list[str]) -> str | None:
    """Colonne la plus plausible comme identifiant stable."""
    if not colonnes:
        return None
    prioritaires = ("code", "reference", "référence", "ref", "numero", "numéro", "n°", "id")
    for mot in prioritaires:
        for c in colonnes:
            if mot in c.lower():
                return c
    return colonnes[0]


async def detecter(nom_fichier: str, structure: dict) -> dict:
    """Propose type / colonne identifiante / résumé. Ne lève jamais."""
    colonnes = structure.get("columns") or []
    tabulaire = structure.get("kind") == "tabulaire"

    # Échantillon ANONYMISÉ : la détection ne doit pas exfiltrer de PII.
    try:
        from security.anonymizer import anonymizer
        if tabulaire:
            from ingestion.parsers import ligne_en_texte
            brut = "\n---\n".join(ligne_en_texte(l) for l in (structure.get("rows") or [])[:3])
        else:
            brut = (structure.get("text") or "")[:1500]
        echantillon, _ = anonymizer.anonymize(brut)
    except Exception:
        echantillon = ""

    liste = "\n".join(f"- {t} : {d}" for t, d in TYPES.items())
    prompt = (
        f"Tu analyses un fichier importé dans la mémoire d'une entreprise de travaux "
        f"de sols et de revêtements (BTP).\n"
        f"Nom du fichier : {nom_fichier}\n"
        + (f"Colonnes : {', '.join(colonnes)}\n" if colonnes else "")
        + f"Extrait (anonymisé) :\n{echantillon[:1200]}\n\n"
        f"Types possibles :\n{liste}\n\n"
        "Choisis le type le PLUS PRÉCIS qui convienne. `document` est un dernier "
        "recours, pas un choix par défaut : un fichier de prospects n'est pas un "
        "fichier clients, un bon de commande n'est pas un catalogue fournisseur.\n"
        "Réponds UNIQUEMENT par un objet JSON, sans texte autour :\n"
        '{"source_type":"<un type de la liste>",'
        '"confiance":"haute|moyenne|faible",'
        '"resume":"<une phrase en français décrivant ce que contient ce fichier>"'
        + (',"id_col":"<nom exact de la colonne identifiant chaque ligne>"' if tabulaire else "")
        + "}"
    )

    try:
        from llm.router import get_llm, LLMTier
        from langchain_core.messages import HumanMessage

        reponse = await get_llm(LLMTier.LIGHT).ainvoke([HumanMessage(content=prompt)])
        trouve = re.search(r"\{.*\}", str(reponse.content), re.S)
        if not trouve:
            raise ValueError("réponse sans JSON")
        data = json.loads(trouve.group(0))

        source_type = data.get("source_type")
        if source_type not in TYPES:
            source_type = _heuristique(nom_fichier, colonnes, echantillon)["source_type"]

        id_col = data.get("id_col")
        if tabulaire and id_col not in colonnes:      # le modèle a pu inventer un nom
            id_col = _colonne_id_probable(colonnes)

        # RESTRUCTURER, une fois le type connu. Second appel, et non une seule
        # invite plus grosse : associer des colonnes exige de savoir à QUEL
        # vocabulaire les rattacher, donc le type doit être tranché avant. Un
        # seul appel devrait deviner les deux à la fois, et une erreur de type
        # entraînerait des associations fausses.
        mapping = {}
        if tabulaire:
            from ingestion.schema import correspondance
            mapping = await correspondance(source_type, colonnes, echantillon)

        return {
            "source_type": source_type,
            "confiance": data.get("confiance") if data.get("confiance") in ("haute", "moyenne", "faible") else "moyenne",
            "resume": str(data.get("resume") or "")[:300],
            "id_col": id_col if tabulaire else None,
            "mapping": mapping,
        }
    except Exception as e:  # noqa: BLE001 - la détection ne doit jamais bloquer l'import
        logger.info("Détection LLM indisponible (%s) — repli heuristique", e)
        repli = _heuristique(nom_fichier, colonnes, echantillon)
        if not tabulaire:
            repli["id_col"] = None
        # Meme forme que la reponse nominale : sans cette cle, l'ecran d'import
        # lirait `undefined` la ou il attend une association.
        repli.setdefault("mapping", {})
        return repli
