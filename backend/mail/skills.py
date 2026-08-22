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

from config import settings
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
    "- N'utilise JAMAIS de tiret cadratin ni de tiret demi-cadratin ; emploie plutôt "
    "une virgule, un deux-points, une parenthèse ou un point.\n"
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
        "Analyse ce message reçu par une entreprise de travaux de sols et de "
        "revêtements (BTP) et classe-le.\n"
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
    # Sans boîte précisée, on prend celle de la personne — même règle qu'à la
    # lecture. Auparavant l'appel echouait et AUCUN brouillon n'etait produit :
    # l'assistant reclamait l'adresse au lieu de rediger, alors que le cahier
    # des charges demande un brouillon troue de [A COMPLETER]. Le controle de
    # droits reste entier : `envoi=True` exige toujours l'ecriture sur la boite
    # finalement retenue.
    cible = await _boite_a_lire(data, user)
    boite = await verifier_acces(user, cible, envoi=True)

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


# Une adresse, une vraie. Sert à écarter les GABARITS qu'un modèle glisse à la
# place d'une valeur : « [mailbox_de_l_entreprise] », « <votre_email> ». Observé
# en production : un tel gabarit partait jusqu'à Microsoft Graph, qui répondait
# 404 — message incompréhensible pour l'utilisateur, alors que la vraie cause
# était un paramètre inventé.
_ADRESSE_RE = re.compile(r"^[^@\s<>\[\]]+@[^@\s<>\[\]]+\.[a-z]{2,}$", re.I)


async def boites_visibles(user) -> list[str]:
    """Boîtes qu'on a le droit de NOMMER à cette personne.

    Relevé en recette : en répondant sur les mails, l'assistant énumérait toutes
    les adresses du domaine. Aucune donnée n'était exposée — la lecture reste
    contrôlée — mais la LISTE partait à l'écran. Chez un profil terrain, cela
    revient à publier l'annuaire des boîtes de l'entreprise, ce que le
    cloisonnement du cahier des charges exclut.

    On filtre donc ce qui est MONTRÉ, en plus de ce qui est lu.
    """
    connues = await boites_connues()
    try:
        from mail.authorization import boites_par_id
        autorisees = await boites_par_id(str(getattr(user, "id", "") or ""))
    except Exception as e:  # noqa: BLE001 - dans le doute, ne rien nommer
        logger.info("Boîtes autorisées illisibles : %s", e)
        return []
    if autorisees == ["*"]:
        return connues
    permis = {normaliser(b) for b in autorisees}
    return [b for b in connues if b in permis]


def resoudre_boite(demandee: str, visibles: list[str]) -> Optional[str]:
    """« contact » → « contact@duret-sols.fr », si c'est sans ambiguïté.

    Personne n'écrit une adresse entière dans une phrase. Refuser un nom partiel
    que le système sait pourtant résoudre est la même erreur que refuser un
    pluriel sur un jeu de données : on fait dépendre la réponse d'une forme
    d'écriture plutôt que d'une intention.

    Une seule correspondance est retenue. Deux boîtes commençant pareil
    (`contact@` et `contacts@`) laissent la question ouverte : deviner
    donnerait la bonne réponse pour la mauvaise boîte.
    """
    cible = (demandee or "").strip().lower()
    if not cible:
        return None
    exact = [b for b in visibles if b.split("@")[0].lower() == cible]
    if len(exact) == 1:
        return exact[0]
    debut = [b for b in visibles if b.lower().startswith(cible)]
    return debut[0] if len(debut) == 1 else None


async def boites_connues() -> list[str]:
    """Boîtes que le système sait nommer : configurées, ou déjà en mémoire.

    Vue NON filtrée, réservée aux usages internes (résolution, diagnostic).
    Pour tout ce qui peut atteindre un utilisateur, passer par
    `boites_visibles`, qui applique le cloisonnement.
    """
    trouvees: list[str] = []
    for source in (getattr(settings, "ms_mailbox", None),
                   getattr(settings, "ms_extra_mailboxes", None),
                   getattr(settings, "gmail_extra_mailboxes", None)):
        for adresse in (source or "").split(","):
            adresse = normaliser(adresse)
            if _ADRESSE_RE.match(adresse) and adresse not in trouvees:
                trouvees.append(adresse)
    try:
        from database.connection import get_db
        async with get_db() as conn:
            lignes = await conn.fetch(
                "SELECT DISTINCT split_part(source_id, ':', 2) AS boite FROM documents "
                "WHERE source_type IN ('email', 'email_sent')")
        for l in lignes:
            adresse = normaliser(l["boite"])
            if _ADRESSE_RE.match(adresse) and adresse not in trouvees:
                trouvees.append(adresse)
    except Exception as e:  # noqa: BLE001 - une base indisponible n'empêche pas de lire
        logger.info("Inventaire des boîtes indisponible : %s", e)
    return sorted(trouvees)


async def _boite_a_lire(data: dict, user) -> str:
    """Détermine QUELLE boîte lire, avant tout contrôle de droits."""
    demandee = normaliser(data.get("mailbox"))

    if demandee and not _ADRESSE_RE.match(demandee):
        # Un nom partiel se résout avant de refuser : « contact » désigne sans
        # ambiguïté contact@<domaine> quand c'est la seule qui commence ainsi.
        visibles = await boites_visibles(user)
        resolue = resoudre_boite(demandee, visibles)
        if resolue:
            logger.info("Boîte « %s » résolue en %s", demandee, resolue)
            return resolue
        raise MailSkillError(
            f"« {demandee} » n'est pas une adresse mail et ne correspond à "
            "aucune boîte accessible. N'invente jamais ce paramètre : soit tu "
            "donnes une adresse réelle, soit tu l'omets. "
            + (f"Boîtes accessibles : {', '.join(visibles)}." if visibles else
               "Aucune boîte ne vous est accessible."))
    if demandee:
        return demandee

    # Rien de demandé : la boîte de la personne connectée, si c'en est une.
    propre = normaliser(getattr(user, "email", None))
    domaine = normaliser(getattr(settings, "ms_domain", None)
                         or getattr(settings, "gmail_domain", None))
    if propre and (not domaine or propre.endswith("@" + domaine)):
        return propre

    # Son compte applicatif est hors du domaine de messagerie — cas courant
    # d'un administrateur qui se connecte avec une adresse personnelle. Il n'a
    # donc pas de boîte propre à lire : on prend la boîte de l'entreprise si
    # elle est connue, plutôt que d'échouer sur une adresse qui n'existe pas
    # dans le tenant.
    visibles = await boites_visibles(user)
    if visibles:
        return visibles[0]
    raise MailSkillError(
        "Aucune boîte à lire : votre compte "
        f"({propre or 'sans adresse'}) n'appartient pas au domaine de messagerie"
        + (f" {domaine}" if domaine else "")
        + ", et aucune boîte d'entreprise n'est configurée. Précisez l'adresse "
          "à consulter.")


async def lire_mails(data: dict, user) -> dict:
    """Lit les derniers messages d'une boîte, EN DIRECT.

    Le contrôle de droits passe par `verifier_acces`, comme tous les skills mail :
    sa boîte, celles qui lui sont déléguées, toutes si administrateur — et
    l'accès administrateur est journalisé.

    `envoi=False` : consulter n'est pas écrire au nom de quelqu'un. Une
    délégation en lecture seule suffit donc à lire, pas à rédiger.
    """
    from mail.lecture import lire_boite

    cible = await _boite_a_lire(data, user)
    boite = await verifier_acces(user, cible)      # le contrôle reste ICI
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
        detail = str(e)
        # Un 404 du fournisseur ne veut pas dire « erreur » pour l'utilisateur :
        # il veut dire « cette boîte n'existe pas là où je cherche ».
        if "404" in detail:
            visibles = await boites_visibles(user)
            raise MailSkillError(
                f"La boîte {boite} n'existe pas dans la messagerie de l'entreprise. "
                + (f"Boîtes accessibles : {', '.join(visibles)}." if visibles else
                   "Aucune boîte ne vous est accessible."))
        raise MailSkillError(
            f"La boîte {boite} n'a pas pu être consultée ({detail}). "
            "Vérifiez la configuration de la messagerie.")


SKILLS_NATIFS["lire_mails"] = lire_mails


async def connaissances_acquises(data: dict, user) -> dict:
    from skills.connaissances import connaissances_acquises as _acquis
    return await _acquis(data, user)


SKILLS_NATIFS["connaissances_acquises"] = connaissances_acquises


async def interroger_donnees(data: dict, user) -> dict:
    from skills.donnees import interroger_donnees as _donnees
    return await _donnees(data, user)


SKILLS_NATIFS["interroger_donnees"] = interroger_donnees


async def mes_droits(data: dict, user) -> dict:
    from skills.droits import mes_droits as _droits
    return await _droits(data, user)


SKILLS_NATIFS["mes_droits"] = mes_droits


async def creer_document(data: dict, user) -> dict:
    from skills.bureau import creer_document as _c
    return await _c(data, user)


async def ajouter_document(data: dict, user) -> dict:
    from skills.bureau import ajouter_document as _a
    return await _a(data, user)


async def terminer_document(data: dict, user) -> dict:
    from skills.bureau import terminer_document as _t
    return await _t(data, user)


async def abandonner_document(data: dict, user) -> dict:
    from skills.bureau import abandonner_document as _ab
    return await _ab(data, user)


SKILLS_NATIFS["creer_document"] = creer_document
SKILLS_NATIFS["ajouter_document"] = ajouter_document
SKILLS_NATIFS["terminer_document"] = terminer_document
SKILLS_NATIFS["abandonner_document"] = abandonner_document


def _ou_echouer(resultat: dict) -> dict:
    """Un `{"ok": False}` est un ÉCHEC, pas un compte rendu.

    L'exécuteur ne regarde pas DANS le dictionnaire : tout ce qui n'est pas une
    exception est un succès. Une fonction qui rend son échec sous forme de
    données ment donc à tout ce qui la lit ensuite — l'écran affiche « action
    exécutée », et le modèle annonce une consigne enregistrée qui ne l'est pas.
    Même panne que le dépôt sur le serveur, même correctif.
    """
    if isinstance(resultat, dict) and resultat.get("ok") is False:
        from skills.executor import SkillError
        raise SkillError(str(resultat.get("message")
                             or "L'opération n'a pas abouti."))
    return resultat


async def retenir(data: dict, user) -> dict:
    from learning.consignes import ajouter
    return _ou_echouer(await ajouter(
        data.get("consigne") or data.get("texte") or "", user,
        pour_tous=bool(data.get("pour_tous")),
        access_level=(data.get("acces") or "all")))


async def consignes_retenues(data: dict, user) -> dict:
    from learning.consignes import lister
    liste = await lister(user)
    return {"nombre": len(liste), "consignes": liste,
            "message": ("Aucune consigne enregistree." if not liste else
                        f"{len(liste)} consigne(s) active(s).")}


async def oublier(data: dict, user) -> dict:
    from learning.consignes import retirer
    return _ou_echouer(await retirer(
        data.get("consigne") or data.get("reference") or "", user))


SKILLS_NATIFS["retenir"] = retenir
SKILLS_NATIFS["consignes_retenues"] = consignes_retenues
SKILLS_NATIFS["oublier"] = oublier


# Les skills du NAS et de la bibliothèque d'outils ne passent plus par ici :
# chaque module de `skills/` les déclare dans son dictionnaire `SKILLS`
# (fonction, description, effet, libellé — tout au même endroit), et
# l'exécuteur les trouve via `skills/registre.py`. Ce fichier appartient au
# socle commun des projets : ce qui change d'un client à l'autre n'y a plus
# sa place.


async def lancer_enrichissement(data: dict, user) -> dict:
    from learning.skills import lancer_enrichissement as _lancer
    return await _lancer(data, user)


async def statut_enrichissement(data: dict, user) -> dict:
    from learning.skills import statut_enrichissement as _statut
    return await _statut(data, user)


SKILLS_NATIFS["lancer_enrichissement"] = lancer_enrichissement
SKILLS_NATIFS["statut_enrichissement"] = statut_enrichissement


# L'INGESTION DES DOCUMENTS, pendant documentaire de l'enrichissement du
# courrier. Elle manquait, et son absence se lisait mal : demandé d'enrichir la
# mémoire à partir des documents, l'assistant renvoyait vers la campagne de
# mails puis expliquait qu'elle ne lit pas les fichiers. Il disait vrai, et
# n'avait aucun geste pour la suite.
async def lancer_ingestion_documents(data: dict, user) -> dict:
    from ingestion.skills import lancer_ingestion_documents as _lancer
    return await _lancer(data, user)


async def statut_ingestion_documents(data: dict, user) -> dict:
    from ingestion.skills import statut_ingestion_documents as _statut
    return await _statut(data, user)


# LA NAVIGATION, ENFIN CHOISIE PAR L'ASSISTANT. Elle n'etait qu'un nœud du
# graphe, declenche automatiquement apres une recherche infructueuse : le modele
# n'avait aucun geste a proposer, et repondait — a juste titre — qu'il ne
# pouvait pas aller sur le web. Ces deux-la LISENT, et rien d'autre.
async def chercher_web(data: dict, user) -> dict:
    from browser.skills import chercher_web as _chercher
    return await _chercher(data, user)


async def ouvrir_page(data: dict, user) -> dict:
    from browser.skills import ouvrir_page as _ouvrir
    return await _ouvrir(data, user)


SKILLS_NATIFS["chercher_web"] = chercher_web
async def naviguer(data: dict, user) -> dict:
    from browser.skills import naviguer as _naviguer
    return await _naviguer(data, user)


SKILLS_NATIFS["ouvrir_page"] = ouvrir_page
SKILLS_NATIFS["naviguer"] = naviguer

SKILLS_NATIFS["lancer_ingestion_documents"] = lancer_ingestion_documents
SKILLS_NATIFS["statut_ingestion_documents"] = statut_ingestion_documents

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
    # Inventaire de ce qui a été appris : lecture pure, filtrée par rôle.
    "connaissances_acquises": "lecture",
    # Compte et filtre sur les donnees importees : lecture, filtree par role.
    "interroger_donnees": "lecture",
    # Description des droits de l'appelant : lecture de sa propre configuration.
    "mes_droits": "lecture",
    # Produire un fichier telechargeable : rien ne sort de l'entreprise et
    # rien n'est envoye, donc ecriture interne et non effet externe.
    "creer_document": "ecriture_interne",
    "ajouter_document": "ecriture_interne",
    "terminer_document": "ecriture_interne",
    # Jeter un brouillon jamais produit : rien ne sort, rien ne s'envoie.
    "abandonner_document": "ecriture_interne",
    # Apprendre une consigne modifie le comportement de l'assistant, pas le
    # monde exterieur : ecriture interne. Le droit d'ecrire POUR TOUS est
    # verifie dans le skill lui-meme.
    "retenir": "ecriture_interne",
    "oublier": "ecriture_interne",
    "consignes_retenues": "lecture",
    # NAS et bibliothèque d'outils : leurs effets vivent dans leurs
    # DÉCLARATIONS (skills/nas.py, skills/outils.py), à côté de leurs
    # fonctions. `effet_du_skill` interroge le registre après cette table, avec
    # le même défaut fail-closed : non déclaré = externe = verrouillé.
    # Campagne d'enrichissement : elle n'écrit QUE dans nos propres données
    # (mémoire, profils de style, brouillons de skills) et ne sort rien du
    # système. Le vrai garde-fou n'est pas l'effet mais la PERMISSION, vérifiée
    # dans le skill sur l'identité rechargée : lire toutes les boîtes est
    # réservé à l'administration système.
    "lancer_enrichissement": "ecriture_interne",
    "statut_enrichissement": "lecture",
    # Même raisonnement pour l'ingestion des documents : elle n'écrit que
    # dans notre propre mémoire et ne sort rien du système. Le garde-fou
    # n'est pas l'effet mais la PERMISSION, vérifiée dans le skill sur
    # l'identité rechargée.
    # Lecture pure : ils ouvrent des pages et rendent du texte. Rien n'est
    # ecrit, rien ne sort du systeme. Le garde-fou n'est pas l'effet mais le
    # CONTENEUR — seul lui parle a l'internet — et l'interrupteur qui le coupe.
    "chercher_web": "lecture",
    "ouvrir_page": "lecture",
    # Le navigateur LIBRE reste en lecture : le mode ecriture depend du
    # deploiement (`BROWSER_READONLY`), et le conteneur refuse la demande
    # si le deploiement dit non. Le modele n'a aucun parametre pour s'en
    # affranchir depuis le chat.
    "naviguer": "lecture",
    "lancer_ingestion_documents": "ecriture_interne",
    "statut_ingestion_documents": "lecture",
}
