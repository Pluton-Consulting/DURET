"""
Ce que l'assistant est en train de faire, en français, pour l'écran.

POURQUOI. La frise d'étapes montre OÙ en est le traitement ; elle ne dit pas
QUOI. « Rédaction » pendant quarante secondes n'apprend rien, et quand rien
n'aboutit on ne sait pas si l'assistant cherche, écrit, ou tourne en rond.

Ici on nomme l'acte : « je lis /home/Drive sur le serveur », « je crée le
document », « j'ai obtenu 18 résultats ». C'est ce qui permet de voir OÙ ça
bloque, sans ouvrir les journaux du serveur.

CE QUI N'Y ENTRE JAMAIS : le contenu. Ni le texte des documents, ni celui des
mails, ni la réponse en cours. Un journal d'activité affiché à l'écran ne doit
pas devenir une seconde voie de lecture, échappant au cloisonnement — un
chemin de fichier et un nombre de résultats suffisent à situer l'avancement.
"""
from __future__ import annotations

# Ce que fait chaque nœud, dit simplement. Sans entrée ici, le nœud reste
# silencieux : mieux vaut ne rien afficher qu'un nom technique.
LIBELLES = {
    "classify": "j'analyse votre demande",
    "check_schedule": "je vérifie vos accès",
    "rag": "je prépare le contexte",
    "anonymize": "je protège les données personnelles",
    "routeur": "je décide de la marche à suivre",
    "recherche": "je cherche dans la mémoire d'entreprise",
    "search_docs": "je cherche dans la mémoire d'entreprise",
    "browser": "je consulte le web",
    "llm": "je réfléchis",
    # Le modele a annonce sans agir : on le reprend. Le dire evite que
    # l'ecran paraisse fige pendant la passe supplementaire.
    "relance": "je reprends l'action",
    "tools": "j'exécute une action",
    "rehydrate": "je finalise la réponse",
    "validation_check": "je vérifie ce qui doit être validé",
    "human_gate": "j'attends votre validation",
    "vision": "j'analyse l'image ou le plan",
    "extraction": "j'extrais les éléments du document",
    "prechiffrage": "je prépare le pré-chiffrage",
    "similar_projects": "je cherche des projets comparables",
}

# Nom d'un skill -> ce qu'il fait, à la première personne. Le nom technique
# (`nas_lister`) ne dit rien à qui regarde l'écran.
ACTES = {
    "rechercher_documents": "je cherche dans les documents",
    "interroger_donnees": "je compte dans les données importées",
    "connaissances_acquises": "je relis ce que j'ai appris",
    "mes_droits": "je vérifie vos droits",
    "lire_mails": "je lis la boîte mail",
    "rediger_email": "je rédige le message",
    "redaction_email": "je rédige le message",
    "resume_fil_email": "je résume le fil de discussion",
    "apprendre_style_email": "j'apprends le style d'écriture",
    "creer_tache_agent": "je programme la tâche",
    "triage_email_entrant": "je classe le message",
    "creer_document": "je prépare le document",
    "ajouter_document": "j'écris dans le document",
    "terminer_document": "je finalise le document",
    "nas_lister": "je liste un dossier du serveur",
    "nas_lire": "je lis un fichier du serveur",
    "nas_chercher": "je cherche un fichier sur le serveur",
    "nas_deposer": "je dépose le fichier sur le serveur",
    "retenir": "j'enregistre la consigne",
    "oublier": "je retire la consigne",
    "consignes_retenues": "je relis les consignes",
    "lancer_enrichissement": "je lance l'analyse du courrier",
    "statut_enrichissement": "je regarde où en est l'analyse",
    "preparer_visuel": "je prépare le brief du visuel",
    "generer_visuel": "je génère le visuel",
}

MAX_DETAIL = 80


def _detail(args: dict) -> str:
    """Le « sur quoi » de l'action : un chemin, un dossier, un titre.

    On ne prend QUE des repères de localisation, jamais du contenu — une requête
    de recherche ou un corps de mail passerait ici en clair, hors de tout
    cloisonnement.
    """
    for cle in ("chemin", "dossier", "source_type", "mailbox", "titre", "motif"):
        valeur = (args or {}).get(cle)
        if valeur and isinstance(valeur, str):
            return valeur.strip()[:MAX_DETAIL]
    return ""


def libelle(node: str, update: dict | None = None) -> str:
    """Phrase à afficher pour ce nœud, ou chaîne vide s'il n'y a rien à dire."""
    update = update if isinstance(update, dict) else {}

    # Une action vient d'être exécutée : c'est la seule chose intéressante à
    # dire, bien plus que « rédaction en cours ».
    resultats = update.get("tool_results")
    if node == "tools" and isinstance(resultats, list) and resultats:
        dernier = resultats[-1] or {}
        nom = dernier.get("skill") or ""
        texte = ACTES.get(nom, f"j'exécute {nom}" if nom else "j'exécute une action")
        if dernier.get("ok") is False:
            texte += " — sans succès"
        return texte

    if node == "tools" and update.get("pending_action"):
        action = update["pending_action"] or {}
        nom = action.get("skill") or ""
        return f"{ACTES.get(nom, nom)} — en attente de votre validation".strip()

    return LIBELLES.get(node, "")


def libelle_action(skill: str, args: dict | None = None) -> str:
    """Phrase pour une action sur le point d'être exécutée."""
    texte = ACTES.get(skill, f"j'exécute {skill}")
    detail = _detail(args or {})
    return f"{texte} : {detail}" if detail else texte
