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
    # Le modele a annonce sans agir : on lui fait produire l'action dans un
    # appel dedie. Le dire evite que l'ecran paraisse fige pendant cette passe.
    "forcer": "je passe à l'exécution",
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
    # Les skills propres au projet (NAS, bibliotheque d'outils) portent leur
    # libelle dans leur DECLARATION (`skills/*.py`, dictionnaire SKILLS) : cette
    # table ne garde que le socle commun. `_acte()` interroge le registre.
    "retenir": "j'enregistre la consigne",
    "oublier": "je retire la consigne",
    "consignes_retenues": "je relis les consignes",
    "lancer_enrichissement": "je lance l'analyse du courrier",
    "statut_enrichissement": "je regarde où en est l'analyse",
    # Les libelles des visuels appartenaient a l'AUTRE projet (Symbiose) : un
    # skill que ce backend n'a jamais eu n'a pas a etre traduit ici.
}

MAX_DETAIL = 80
# Le libellé COMPLET est borné lui aussi : un nom de skill venu du registre en
# base peut être long, et la ligne d'activité tient sur une seule ligne d'écran.
MAX_LIBELLE = 140


def _detail(args: dict) -> str:
    """Le « sur quoi » de l'action : un chemin, un dossier.

    On ne prend QUE des repères de LOCALISATION, jamais du contenu. La règle
    n'était pas tenue : `motif` est une requête de recherche et `titre` un
    texte libre dicté par l'utilisateur — tous deux passaient en clair sur un
    écran qui promet de n'afficher aucun contenu. Un journal d'activité ne doit
    pas devenir une seconde voie de lecture, échappant au cloisonnement.
    """
    if not isinstance(args, dict):
        return ""
    for cle in ("chemin", "dossier", "source_type", "mailbox"):
        valeur = args.get(cle)
        if valeur and isinstance(valeur, str):
            return valeur.strip()[:MAX_DETAIL]
    return ""


def _acte(nom: str) -> str | None:
    """Le libellé d'un skill : la table du socle, puis le REGISTRE.

    Les skills propres au projet portent leur libellé dans leur déclaration,
    à côté de leur fonction : déposer un module suffit, cette table n'a plus à
    en connaître.
    """
    if nom in ACTES:
        return ACTES[nom]
    try:
        from skills.registre import libelle as libelle_declare
        return libelle_declare(nom)
    except Exception:   # noqa: BLE001 - le journal ne casse jamais un tour
        return None


def libelle(node: str, update: dict | None = None) -> str:
    """Phrase à afficher pour ce nœud, ou chaîne vide s'il n'y a rien à dire."""
    update = update if isinstance(update, dict) else {}

    # Une action vient d'être exécutée : c'est la seule chose intéressante à
    # dire, bien plus que « rédaction en cours ».
    resultats = update.get("tool_results")
    if node == "tools" and isinstance(resultats, list) and resultats:
        # Le dernier résultat n'est pas forcément un dictionnaire : un état mal
        # formé suffisait à faire lever `AttributeError` ICI, c'est-à-dire dans
        # le code qui décrit le travail — le tour entier tombait parce que
        # l'écran n'arrivait pas à en parler.
        dernier = resultats[-1]
        dernier = dernier if isinstance(dernier, dict) else {}
        nom = dernier.get("skill") or ""
        texte = _acte(nom) or (f"j'exécute {nom}" if nom else "j'exécute une action")
        if dernier.get("ok") is False:
            texte += ", sans succès"
        return texte[:MAX_LIBELLE]

    if node == "tools" and update.get("pending_action"):
        action = update["pending_action"]
        action = action if isinstance(action, dict) else {}
        nom = action.get("skill") or ""
        return f"{_acte(nom) or nom} (en attente de votre validation)".strip()[:MAX_LIBELLE]

    return LIBELLES.get(node, "")


def libelle_action(skill: str, args: dict | None = None) -> str:
    """Phrase pour une action sur le point d'être exécutée."""
    texte = _acte(skill) or f"j'exécute {skill}"
    detail = _detail(args or {})
    return (f"{texte} : {detail}" if detail else texte)[:MAX_LIBELLE]
