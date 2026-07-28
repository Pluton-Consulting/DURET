"""
Protocole d'appel d'outil — bloc ```action textuel.

POURQUOI PAS le function-calling natif (`bind_tools`) : la cascade LLM du projet
mélange LongCat, Groq 70B/8B, des modèles gratuits d'OpenRouter, DeepSeek et
Ollama. Le support du function-calling y est inégal, invérifié sur le modèle
PRINCIPAL, et surtout il échoue SILENCIEUSEMENT sur certains points d'accès (ils
acceptent le paramètre `tools` puis répondent en prose) — un mode de panne que la
cascade ne peut pas détecter pour rétrograder.

Le protocole retenu est celui qui FONCTIONNE DÉJÀ en production dans ce projet :
le modèle émet un bloc balisé contenant du JSON, exactement comme les blocs
```ui des composants visuels. Il marche sur les 7 candidats, survit à une
rétrogradation en milieu de cascade (l'historique reste du texte pur), et
dégrade proprement : pas de bloc = réponse en prose, bloc invalide = une seule
tentative de réparation.

Le modèle ne choisit QUE parmi ce catalogue. Un nom inconnu est refusé ici, bien
avant d'atteindre l'exécuteur.
"""
from __future__ import annotations

import json
import re
from typing import Optional

# Un bloc ```action ... ``` n'importe où dans la réponse.
BLOC_ACTION_RE = re.compile(r"```action\s*(.*?)```", re.S)

# Catalogue exposé au modèle : nom -> (description, requis[], optionnels[]).
# Volontairement PETIT au départ : uniquement des skills natifs, dont les effets
# sont déclarés dans le code. Les skills générés (bac à sable) n'y figurent pas.
CATALOGUE_AGENT1: dict[str, tuple[str, list[str], list[str]]] = {
    "triage_email_entrant": (
        "Classe et priorise un message reçu (catégorie, urgence, action suggérée)",
        ["mailbox"], ["objet", "corps"]),
    "redaction_email": (
        "Rédige un BROUILLON de message (11 types : reponse, relance_devis, "
        "relance_impaye, envoi_devis, reclamation, information_chantier, "
        "confirmation_rdv, demande_information, remerciement, refus, interne). "
        "N'envoie jamais.",
        ["mailbox", "type_mail"], ["contexte", "message_recu", "destinataire"]),
    "resume_fil_email": (
        "Résume un échange de mails et en extrait les engagements",
        ["mailbox", "fil"], []),
    "apprendre_style_email": (
        "Apprend le style d'écriture d'une boîte à partir de ses messages envoyés",
        [], ["mailbox"]),
    "creer_tache_agent": (
        "Enregistre une tâche que l'assistant exécutera plus tard, éventuellement de "
        "façon répétée. recurrence : interval (avec interval_minutes, minimum 5), "
        "daily ou weekly (avec heure « 07:30 », et jours [1..7] pour weekly). "
        "Sans recurrence, la tâche ne part que sur demande.",
        ["titre", "consigne"],
        ["recurrence", "interval_minutes", "heure", "jours"]),
}


def instruction_actions() -> str:
    """Bloc à ajouter au prompt système. Constant : le préfixe reste stable, donc
    le cache de prompt du fournisseur continue de s'appliquer."""
    lignes = []
    for nom, (desc, requis, optionnels) in CATALOGUE_AGENT1.items():
        params = ", ".join([f"{p}*" for p in requis] + list(optionnels)) or "aucun"
        lignes.append(f'- {nom} : {desc}. Paramètres ({params}) — * = obligatoire.')
    return (
        "\n\nACTIONS. Tu peux EXÉCUTER une action, et pas seulement répondre. Pour cela, "
        "termine ta réponse par un bloc balisé ```action contenant "
        '{"skill":"<nom>","args":{...}} puis ARRÊTE-toi : le résultat te sera fourni et '
        "tu pourras alors rédiger ta réponse finale.\n"
        "Règles : UNE seule action par réponse ; uniquement un skill de la liste ; "
        "si aucune action n'est nécessaire, réponds normalement SANS bloc. "
        "Les balises masquées ([PER_1], [MONTANT_2]...) sont acceptées dans les paramètres. "
        "Quand une boîte mail est demandée et que l'utilisateur n'en précise pas, "
        "omets le paramètre : la sienne sera utilisée.\n"
        "Skills disponibles :\n" + "\n".join(lignes) +
        '\nExemple :\n```action\n{"skill":"redaction_email","args":'
        '{"mailbox":"contact@exemple.fr","type_mail":"relance_devis",'
        '"contexte":"devis DEV-17 envoyé il y a 3 semaines, sans réponse"}}\n```'
    )


def extraire_action(texte: str) -> tuple[Optional[dict], str, Optional[str]]:
    """Extrait l'action d'une réponse LLM.

    Retourne `(action, texte_sans_bloc, erreur)` :
      * `action` = {"skill", "args"} si le bloc est valide ;
      * `texte_sans_bloc` = la réponse débarrassée du bloc, toujours exploitable ;
      * `erreur` = message destiné au modèle pour qu'il se corrige, sinon None.

    Ne lève jamais : un bloc mal formé est une erreur de rédaction du modèle, pas
    une panne du service.
    """
    trouve = BLOC_ACTION_RE.search(texte or "")
    if not trouve:
        return None, (texte or ""), None

    reste = ((texte[:trouve.start()] + texte[trouve.end():]) or "").strip()

    try:
        data = json.loads(trouve.group(1).strip())
    except json.JSONDecodeError as e:
        return None, reste, f"bloc action illisible ({e}) — réécris un JSON valide"

    if not isinstance(data, dict):
        return None, reste, "le bloc action doit contenir un objet JSON"

    skill = data.get("skill")
    if skill not in CATALOGUE_AGENT1:
        return None, reste, (f"skill inconnu : {skill}. "
                             f"Choisis parmi : {', '.join(CATALOGUE_AGENT1)}")

    args = data.get("args")
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return None, reste, "« args » doit être un objet JSON"

    requis = CATALOGUE_AGENT1[skill][1]
    manquants = [p for p in requis if not str(args.get(p) or "").strip()]
    if manquants:
        return None, reste, (f"paramètres obligatoires manquants pour {skill} : "
                             f"{', '.join(manquants)}")

    return {"skill": skill, "args": args}, reste, None
