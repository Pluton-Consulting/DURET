"""
Skills mail NATIFS — exécutés dans le backend, pas dans le bac à sable.

Pourquoi natifs : ces compétences ont besoin du LLM, de la base documentaire et
surtout de l'IDENTITÉ de l'appelant pour vérifier ses droits sur la boîte. Un
code isolé en bac à sable n'a accès à rien de tout cela.

Invariants respectés par TOUTES les fonctions ci-dessous :
  * `verifier_acces` est appelé AVANT tout traitement. Rédiger « au nom de »
    exige le droit d'envoi sur la boîte.
  * Rien n'est JAMAIS envoyé : ces skills produisent des BROUILLONS. L'envoi
    reste une action humaine.
  * Le contenu passe par l'anonymiseur avant d'atteindre le modèle, et la
    réponse est réhydratée ensuite (même contrat que le chat).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

from fastapi import HTTPException, status

from mail.authorization import verifier_acces, normaliser
from mail.style import consigne_style

logger = logging.getLogger("duret.mail.skills")

# Types de messages proposés. Chaque entrée = (libellé, consigne spécifique).
TYPES_MAIL = {
    "reponse": (
        "Réponse à un message reçu",
        "Réponds point par point au message reçu, sans rien laisser sans réponse."),
    "relance_devis": (
        "Relance d'un devis sans réponse",
        "Relance courtoise sur un devis resté sans réponse. Ne mets aucune pression, "
        "propose d'échanger et de lever les éventuelles questions."),
    "relance_impaye": (
        "Relance d'une facture impayée",
        "Relance ferme mais courtoise sur une facture échue. Rappelle la référence et "
        "l'échéance, propose un contact en cas de difficulté. Aucune menace juridique "
        "sauf si elle est explicitement demandée."),
    "envoi_devis": (
        "Envoi d'un devis",
        "Accompagne l'envoi d'un devis : rappelle brièvement le besoin, annonce la pièce "
        "jointe, indique la durée de validité et propose un échange."),
    "reclamation": (
        "Réponse à une réclamation",
        "Réponds à un mécontentement : accuse réception, reconnais le désagrément sans "
        "reconnaître de responsabilité juridique, annonce la démarche et un délai."),
    "information_chantier": (
        "Information sur un chantier",
        "Informe le client de l'avancement ou d'un aléa de chantier : faits, impact sur "
        "le planning, prochaine étape."),
    "confirmation_rdv": (
        "Confirmation de rendez-vous",
        "Confirme un rendez-vous : date, heure, lieu, participants, objet, et ce que le "
        "client doit éventuellement préparer."),
    "demande_information": (
        "Demande d'informations",
        "Demande les éléments manquants, sous forme de liste courte et précise."),
    "remerciement": (
        "Remerciement / fin de chantier",
        "Remercie à l'issue d'un chantier ou d'une commande, propose de rester disponible."),
    "refus": (
        "Refus poli",
        "Décline une demande avec tact : motif, absence d'ambiguïté, ouverture si possible."),
    "interne": (
        "Message interne à l'équipe",
        "Message interne : ton direct, pas de formule commerciale, va à l'essentiel."),
}

_CONSIGNE_COMMUNE = (
    "Tu rédiges un BROUILLON de message professionnel en français, destiné à être relu "
    "puis envoyé par un humain.\n"
    "Règles absolues :\n"
    "- N'INVENTE aucun chiffre, prix, date, délai ni engagement. Si une information manque, "
    "écris [À COMPLÉTER] et signale-la dans elements_a_verifier.\n"
    "- Certaines valeurs peuvent apparaître masquées ([PER_1], [MONTANT_2]...) : conserve-les "
    "telles quelles, ne crée jamais de balise toi-même.\n"
    "- N'utilise JAMAIS de tiret cadratin ni demi-cadratin ; emploie une virgule, un "
    "deux-points, une parenthèse ou un tiret simple.\n"
    "- Tu ne peux pas envoyer de message : tu produis uniquement un brouillon."
)


class MailSkillError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


def _json_de(texte: str) -> dict:
    """Extrait le premier objet JSON d'une réponse LLM. Lève si introuvable."""
    trouve = re.search(r"\{.*\}", str(texte), re.S)
    if not trouve:
        raise MailSkillError("Le modèle n'a pas renvoyé de résultat exploitable.")
    try:
        return json.loads(trouve.group(0))
    except json.JSONDecodeError as e:
        raise MailSkillError(f"Résultat du modèle illisible : {e}")


async def _appeler(prompt: str, tier: str = "standard") -> str:
    from llm.router import get_llm, LLMTier
    from langchain_core.messages import HumanMessage
    reponse = await get_llm(LLMTier(tier)).ainvoke([HumanMessage(content=prompt)])
    return str(reponse.content)


async def _protege(texte: str) -> tuple[str, dict]:
    """Anonymise avant envoi au modèle (même contrat RGPD que le chat)."""
    import asyncio
    from security.anonymizer import anonymizer
    return await asyncio.to_thread(anonymizer.anonymize, texte or "")


def _rehydrater(valeur, carte: dict):
    """Réinjecte les vraies valeurs dans la sortie (chaînes et listes de chaînes)."""
    from security.anonymizer import anonymizer
    if isinstance(valeur, str):
        return anonymizer.rehydrate(valeur, carte)
    if isinstance(valeur, list):
        return [_rehydrater(v, carte) for v in valeur]
    if isinstance(valeur, dict):
        return {k: _rehydrater(v, carte) for k, v in valeur.items()}
    return valeur


# ── Skills ───────────────────────────────────────────────────────────

async def triage_email_entrant(data: dict, user) -> dict:
    """Classe et priorise un message reçu. Ne déclenche aucune action."""
    boite = await verifier_acces(user, data.get("mailbox"))
    objet = (data.get("objet") or "").strip()
    corps = (data.get("corps") or "").strip()
    if not objet and not corps:
        raise MailSkillError("Fournissez au moins l'objet ou le corps du message.")

    masque, carte = await _protege(f"Objet : {objet}\n\n{corps}")
    prompt = (
        "Analyse ce message reçu par une entreprise du paysage et classe-le.\n"
        "Réponds UNIQUEMENT par un objet JSON :\n"
        '{"categorie":"devis|sav|administratif|commercial|interne|indesirable|autre",'
        '"priorite":"haute|moyenne|basse",'
        '"client_detecte":"<nom ou vide>",'
        '"resume":"<une phrase>",'
        '"action_suggeree":"<que faire, une phrase>",'
        '"delai_conseille":"<ex. sous 24h, cette semaine>"}\n\n'
        f"{masque}"
    )
    resultat = _json_de(await _appeler(prompt, "light"))
    resultat = _rehydrater(resultat, carte)
    resultat["mailbox"] = boite
    return resultat


async def rediger_email(data: dict, user) -> dict:
    """Rédige un BROUILLON, dans le style de l'expéditeur, pour un type donné."""
    # `envoi=True` : rédiger AU NOM d'une boîte exige le droit d'écriture dessus.
    boite = await verifier_acces(user, data.get("mailbox"), envoi=True)

    type_mail = (data.get("type_mail") or "reponse").strip()
    if type_mail not in TYPES_MAIL:
        raise MailSkillError(
            f"Type de message inconnu : {type_mail}. "
            f"Types disponibles : {', '.join(TYPES_MAIL)}.")

    contexte = (data.get("contexte") or "").strip()
    message_recu = (data.get("message_recu") or "").strip()
    destinataire = (data.get("destinataire") or "").strip()
    if not contexte and not message_recu:
        raise MailSkillError(
            "Fournissez au moins `contexte` (ce que vous voulez dire) ou "
            "`message_recu` (le message auquel répondre).")

    libelle, consigne = TYPES_MAIL[type_mail]
    brut = "\n\n".join(p for p in [
        f"Destinataire : {destinataire}" if destinataire else "",
        f"Message reçu :\n{message_recu}" if message_recu else "",
        f"Éléments à intégrer :\n{contexte}" if contexte else "",
    ] if p)
    masque, carte = await _protege(brut)

    style = await consigne_style(boite)
    prompt = "\n\n".join(p for p in [
        _CONSIGNE_COMMUNE,
        f"TYPE DE MESSAGE : {libelle}.\n{consigne}",
        style,
        f"ÉLÉMENTS FOURNIS :\n{masque}",
        'Réponds UNIQUEMENT par un objet JSON :\n'
        '{"objet":"<objet du mail>","corps":"<corps complet, sauts de ligne compris>",'
        '"ton":"<formel|cordial|direct>",'
        '"elements_a_verifier":["<ce qui doit être vérifié ou complété avant envoi>"]}',
    ] if p)

    resultat = _json_de(await _appeler(prompt, "standard"))
    resultat = _rehydrater(resultat, carte)

    if not resultat.get("corps"):
        raise MailSkillError("Le modèle n'a pas produit de corps de message.")

    # Garde-fou explicite : le consommateur ne doit jamais confondre avec un envoi.
    resultat.update({
        "mailbox": boite,
        "type_mail": type_mail,
        "statut": "brouillon",
        "envoye": False,
        "avertissement": "Brouillon à relire. Aucun message n'a été envoyé.",
    })
    if "[À COMPLÉTER]" in resultat.get("corps", ""):
        resultat.setdefault("elements_a_verifier", []).append(
            "Le brouillon contient des mentions [À COMPLÉTER] à renseigner.")
    return resultat


async def resumer_fil(data: dict, user) -> dict:
    """Résume un échange de plusieurs messages et en extrait les engagements."""
    boite = await verifier_acces(user, data.get("mailbox"))
    fil = (data.get("fil") or "").strip()
    if not fil:
        raise MailSkillError("Fournissez `fil` : les messages de l'échange.")

    masque, carte = await _protege(fil)
    prompt = (
        "Résume cet échange de mails pour quelqu'un qui le découvre.\n"
        "Réponds UNIQUEMENT par un objet JSON :\n"
        '{"resume":"<5 lignes maximum>",'
        '"demandes_client":["..."],'
        '"engagements_pris":["<ce que NOUS avons promis>"],'
        '"points_en_attente":["..."],'
        '"prochaine_action":"<une phrase>"}\n\n'
        f"{masque}"
    )
    resultat = _rehydrater(_json_de(await _appeler(prompt, "standard")), carte)
    resultat["mailbox"] = boite
    return resultat


async def profil_style(data: dict, user) -> dict:
    """(Re)calcule le profil de style à partir des messages DÉJÀ ingérés."""
    boite = await verifier_acces(user, data.get("mailbox") or getattr(user, "email", None))
    from mail.style import construire_profil
    return await construire_profil(boite, force=bool(data.get("force")))


async def apprendre_style(data: dict, user) -> dict:
    """Va CHERCHER les derniers messages envoyés de la boîte, puis apprend le style.

    Parcours libre-service : chacun se connecte avec son compte et lance
    l'apprentissage pour SA boîte. Sans `mailbox`, on prend celle de la personne
    connectée — le cas courant. Une boîte déléguée est acceptée si l'accès est
    reconnu ; aucune permission d'administration n'est requise, c'est
    `verifier_acces` qui borne le périmètre.
    """
    boite = await verifier_acces(user, data.get("mailbox") or getattr(user, "email", None))

    from mail.collecte import collecter_envoyes
    from mail.style import construire_profil

    try:
        collecte = await collecter_envoyes(boite, maximum=data.get("nombre"))
    except NotImplementedError as e:
        raise MailSkillError(str(e))
    except Exception as e:  # noqa: BLE001
        logger.warning("Collecte des envois de %s échouée : %s", boite, e)
        raise MailSkillError(
            f"Impossible de lire les messages envoyés de {boite}. "
            "Vérifiez que la messagerie est bien connectée.")

    # force=True : on vient d'ajouter des messages, le profil doit être refait.
    profil = await construire_profil(boite, force=True)

    if not profil.get("profil"):
        raise MailSkillError(
            f"Pas encore assez de messages envoyés depuis {boite} pour apprendre un style "
            f"({profil.get('echantillons', 0)} trouvé(s)). "
            f"Motif : {profil.get('raison', 'inconnu')}.")

    return {
        "mailbox": boite,
        "messages_collectes": collecte.get("envoyes", 0),
        "messages_analyses": profil.get("echantillons", 0),
        "profil": profil.get("profil"),
        "message": f"Style appris pour {boite}. Les prochains brouillons rédigés "
                   f"au nom de cette boîte reprendront cette façon d'écrire.",
    }


# Registre consommé par l'exécuteur de skills.
SKILLS_NATIFS = {
    "triage_email_entrant": triage_email_entrant,
    "redaction_email": rediger_email,
    "resume_fil_email": resumer_fil,
    "profil_style_email": profil_style,
    "apprendre_style_email": apprendre_style,
}


def _skill_creer_tache():
    """Import différé : tasks/ dépend de la base, mail/skills.py est importé tôt."""
    from tasks.skills import creer_tache_agent
    return creer_tache_agent


async def creer_tache_agent(data: dict, user) -> dict:
    return await _skill_creer_tache()(data, user)


SKILLS_NATIFS["creer_tache_agent"] = creer_tache_agent


async def rechercher_documents(data: dict, user) -> dict:
    from skills.documents import rechercher_documents as _chercher
    return await _chercher(data, user)


SKILLS_NATIFS["rechercher_documents"] = rechercher_documents


async def lire_mails(data: dict, user) -> dict:
    """Lit les derniers messages d'une boîte, EN DIRECT.

    Le contrôle de droits passe par `verifier_acces`, comme tous les skills mail :
    sa boîte, celles qui lui sont déléguées, toutes si administrateur — et
    l'accès administrateur est journalisé. Sans boîte précisée, c'est la sienne.

    `envoi=False` : consulter n'est pas écrire au nom de quelqu'un. Une
    délégation en lecture seule suffit donc à lire, pas à rédiger.
    """
    from mail.lecture import lire_boite

    boite = await verifier_acces(user, data.get("mailbox") or getattr(user, "email", None))
    try:
        limite = int(data.get("limite") or 10)
    except (TypeError, ValueError):
        limite = 10

    try:
        return await lire_boite(boite, data.get("dossier") or "recus", limite)
    except NotImplementedError as e:
        raise MailSkillError(str(e))
    except Exception as e:  # noqa: BLE001 - une messagerie injoignable n'est pas une panne du chat
        logger.warning("Lecture de %s impossible : %s", boite, e)
        raise MailSkillError(
            f"La boîte {boite} n'a pas pu être consultée ({e}). "
            "Vérifiez la configuration de la messagerie.")


SKILLS_NATIFS["lire_mails"] = lire_mails


async def lancer_enrichissement(data: dict, user) -> dict:
    from learning.skills import lancer_enrichissement as _lancer
    return await _lancer(data, user)


async def statut_enrichissement(data: dict, user) -> dict:
    from learning.skills import statut_enrichissement as _statut
    return await _statut(data, user)


SKILLS_NATIFS["lancer_enrichissement"] = lancer_enrichissement
SKILLS_NATIFS["statut_enrichissement"] = statut_enrichissement

# EFFET de chaque skill — classification qui décide si une validation humaine est
# exigée. Déclarée DANS LE CODE, jamais déduite du nom ni fournie par le modèle :
#   lecture          : ne modifie rien ;
#   ecriture_interne : écrit dans nos propres données (brouillon, profil de style) ;
#   externe          : produit un effet hors du système (envoi de mail, écriture sur
#                      un NAS, action chez un tiers) -> validation humaine OBLIGATOIRE.
# Tout skill non listé est traité comme `externe` par l'exécuteur : un oubli de
# déclaration verrouille, il n'ouvre pas.
EFFETS_NATIFS = {
    "triage_email_entrant": "lecture",
    "resume_fil_email": "lecture",
    "redaction_email": "ecriture_interne",      # brouillon : n'envoie jamais
    "profil_style_email": "ecriture_interne",
    "apprendre_style_email": "ecriture_interne",
    # Créer une tâche n'a aucun effet hors du système : quand elle s'exécutera,
    # elle repassera par tous les contrôles, validation humaine comprise.
    "creer_tache_agent": "ecriture_interne",
    # Recherche dans la mémoire d'entreprise : ne modifie rien, et reste bornée
    # aux droits de l'appelant (cloisonnement des boîtes mail compris).
    "rechercher_documents": "lecture",
    # Lire une boîte ne modifie rien et reste borné par `verifier_acces`.
    "lire_mails": "lecture",
    # Campagne d'enrichissement : elle n'écrit QUE dans nos propres données
    # (mémoire, profils de style, brouillons de skills) et ne sort rien du
    # système. Le vrai garde-fou n'est pas l'effet mais la PERMISSION, vérifiée
    # dans le skill sur l'identité rechargée : lire toutes les boîtes est
    # réservé à l'administration système.
    "lancer_enrichissement": "ecriture_interne",
    "statut_enrichissement": "lecture",
}
