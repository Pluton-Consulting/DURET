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
from mail.authorization import verifier_acces, normaliser, boite_par_defaut
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
    "- N'ÉCRIS PAS de signature (nom, fonction, téléphone, mentions légales) : celle de "
    "la boîte est apposée mécaniquement à l'envoi. En écrire une produirait un message "
    "signé deux fois, dont une fois de mémoire.\n"
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

async def _boite_du_triage(data: dict, user) -> Optional[str]:
    """La boîte à créditer pour un message qu'on CLASSE, jamais qu'on lit.

    Le cas courant n'est pas la lecture d'une boîte : c'est un mail COLLÉ dans
    le chat (« voici ce que je viens de recevoir, classe-le »). Personne ne
    nomme d'adresse dans cette phrase, et il n'y a aucune raison de le faire.
    Or le contrôle de droits était appelé directement sur `data["mailbox"]` :
    absente, il refusait « Aucune boîte mail précisée » et le classement
    n'avait pas lieu. Le modèle en était réduit à inventer une adresse ou à
    réclamer la sienne à l'utilisateur — les deux ont été observés.

    On reprend donc le repli déjà en place pour la rédaction : la boîte de la
    personne connectée. Et si elle n'en a aucune, on classe QUAND MÊME, sans
    boîte : le texte vient de l'utilisateur, aucune messagerie n'est ouverte,
    il n'y a rien à cloisonner. Le contrôle reste entier dès qu'une boîte est
    NOMMÉE : nommer celle d'un collègue est refusé comme avant.
    """
    try:
        return await verifier_acces(user, await _boite_a_lire(data, user))
    except HTTPException:
        if normaliser(data.get("mailbox")):
            raise                      # une boîte a été nommée : le refus est un vrai refus
        return None


async def triage_email_entrant(data: dict, user) -> dict:
    """Classe et priorise un message reçu. Ne déclenche aucune action."""
    boite = await _boite_du_triage(data, user)
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
    ref_recu = str(data.get("ref") or "").strip()

    # LA RETOUCHE PART DE LA VERSION PRÉCÉDENTE (15/09). Le 11/09, « une
    # version un peu moins brute » puis « tu as enlevé trop de choses, le mail
    # d'avant était mieux construit » : chaque retouche était une réécriture
    # depuis le seul `contexte`. La version précédente vient du modèle
    # (`version_precedente`) ou, à défaut, du dernier brouillon retenu pour
    # cette conversation (`mail/brouillons.py`).
    from mail import brouillons
    fil = data.get("_fil")
    precedent = (data.get("version_precedente") or "").strip()
    retouche = bool(precedent) or str(data.get("retoucher") or "").lower() in ("true", "1", "oui", "yes")
    if retouche and not precedent:
        garde = brouillons.dernier(getattr(user, "id", ""), fil) or {}
        precedent = garde.get("corps") or ""
        destinataire = destinataire or garde.get("destinataire") or ""
        ref_recu = ref_recu or garde.get("ref") or ""
    if retouche and not precedent:
        raise MailSkillError(
            "Aucune version précédente de ce message n'est connue dans cette "
            "conversation : passe son texte dans `version_precedente`, ou rédige-le "
            "à nouveau avec `contexte`.")
    if not contexte and not message_recu and not precedent:
        raise MailSkillError(
            "Fournissez au moins `contexte` (ce que vous voulez dire) ou "
            "`message_recu` (le message auquel répondre).")

    libelle, consigne = TYPES_MAIL[type_mail]
    brut = "\n\n".join(p for p in [
        f"Destinataire : {destinataire}" if destinataire else "",
        f"Message reçu :\n{message_recu}" if message_recu else "",
        (f"VERSION PRÉCÉDENTE DU BROUILLON (validée jusqu'ici par la personne) :\n{precedent}"
         if precedent else ""),
        (f"MODIFICATIONS DEMANDÉES :\n{contexte}" if precedent and contexte
         else f"Éléments à intégrer :\n{contexte}" if contexte else ""),
    ] if p)
    masque, carte = await _protege(brut)

    style = await consigne_style(boite)
    prompt = "\n\n".join(p for p in [
        _CONSIGNE_COMMUNE,
        f"TYPE DE MESSAGE : {libelle}.\n{consigne}",
        style,
        ("C'EST UNE RETOUCHE, PAS UNE RÉÉCRITURE : pars de la version précédente et "
         "n'y change QUE ce que les modifications demandent. Garde sa structure, ses "
         "informations et ses formulations partout ailleurs ; n'enlève rien qu'on "
         "n'ait pas demandé d'enlever." if precedent else ""),
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
        "retouche": retouche or None,
        # OÙ EST LE BROUILLON (15/09). Le 11/09 : « le brouillon a bien été créé
        # dans votre boîte mail, enregistré comme brouillon » — faux, et démenti
        # au tour suivant. Le résultat le dit en toutes lettres.
        "ou_est_il": ("dans cette conversation SEULEMENT — il n'est PAS dans la boîte "
                      "mail. Pour l'y poser : `deposer_brouillon`."),
        "avertissement": "Brouillon à relire. Aucun message n'a été envoyé.",
    })
    if "[À COMPLÉTER]" in resultat.get("corps", ""):
        resultat.setdefault("elements_a_verifier", []).append(
            "Le brouillon contient des mentions [À COMPLÉTER] à renseigner.")
    brouillons.retenir(getattr(user, "id", ""), fil, {
        "objet": resultat.get("objet"), "corps": resultat.get("corps"),
        "destinataire": destinataire, "ref": ref_recu, "boite": boite})
    # LA CARTE EST MÉCANIQUE (15/09). Le 11/09, chaque version s'affichait DEUX
    # fois : une carte `email` recopiée par le modèle (avec un nom de signataire
    # que la consigne interdit), puis le même texte en prose. La carte vient du
    # skill : modifiable, et ses boutons demandent l'envoi (avec accord) ou le
    # dépôt dans les brouillons de la boîte.
    resultat["bloc_garanti"] = True
    resultat["bloc_ui"] = {"type": "reponses_mail", "titre": "Brouillon — modifiable", "boite": boite,
                           "reponses": [{"ref": ref_recu or None, "de": destinataire or None,
                                         "objet": resultat.get("objet") or "",
                                         "reponse": resultat.get("corps") or ""}]}
    resultat["a_faire"] = (
        "La carte du brouillon s'affiche AUTOMATIQUEMENT (modifiable, avec « Envoyer » et "
        "« Mettre dans mes brouillons ») : n'écris NI bloc email NI le texte du message, "
        "et n'ajoute aucun nom de signataire. Dis en une ou deux phrases ce que ce "
        "brouillon dit" + (" et ce qui a changé par rapport à la version précédente"
                           if retouche else "") + ". Il est dans la CONVERSATION seulement : "
        "ne dis jamais qu'il est dans la boîte mail. Pour l'y mettre, `deposer_brouillon`.")
    return resultat


async def deposer_brouillon(data: dict, user) -> dict:
    """POSE un brouillon dans le dossier Brouillons de la boîte. N'envoie rien.

    Relevé du 11/09 : « je ne le trouve pas dans les brouillons de ma boîte
    mail » — aucun geste ne savait l'y mettre, et l'assistant a prétendu
    l'avoir fait. Ici le message est réellement créé dans la messagerie, avec la
    signature de la boîte, en réponse au message d'origine quand on le connaît.
    Rien ne sort de l'entreprise : effet `ecriture_interne`.
    """
    from mail import brouillons
    from mail.expedition import deposer_brouillon as _deposer, porte_un_jeton

    garde = brouillons.dernier(getattr(user, "id", ""), data.get("_fil")) or {}
    corps = (data.get("corps") or data.get("message") or "").strip() or garde.get("corps") or ""
    objet = (data.get("objet") or "").strip() or garde.get("objet") or ""
    destinataire = (data.get("destinataire") or "").strip() or garde.get("destinataire") or ""
    ref_recu = str(data.get("ref") or "").strip() or garde.get("ref") or ""
    if not corps:
        raise MailSkillError(
            "Aucun brouillon à déposer : rédige-le d'abord (`redaction_email`) ou donne "
            "son `corps` complet.")
    cible = data.get("mailbox") or garde.get("boite")
    boite = await verifier_acces(user, await _boite_a_lire({**data, "mailbox": cible} if cible else data, user),
                                 envoi=True)
    for champ, valeur in (("destinataire", destinataire), ("objet", objet), ("corps", corps)):
        if porte_un_jeton(valeur):
            raise MailSkillError(
                f"Le champ `{champ}` contient une balise de masquage jamais résolue : "
                "réécris-le avec les vraies valeurs.")

    brut_pieces = (data.get("pieces") or data.get("pieces_jointes") or data.get("fichiers"))
    pieces = []
    if brut_pieces:
        from mail.attaches import resoudre
        pieces, refusees = await resoudre(brut_pieces, user, boite)
        if refusees:
            raise MailSkillError(
                "Ces pièces n'ont pas pu être jointes, aucun brouillon n'a été déposé : "
                + " ; ".join(f"« {r['nom']} » ({r['raison']})" for r in refusees) + ".")

    from mail.instantanes import verifier as verifier_pieces_figees
    verifier_pieces_figees(data, pieces)

    from mail.signature import apposer
    corps_signe, html, pieces_signees = await apposer(boite, corps, pieces, demandee=data.get("signature"))
    signee = bool(html) or corps_signe != corps or len(pieces_signees) != len(pieces)
    pieces = pieces_signees
    if _signature_exigee(data.get("signature")) and not signee:
        raise MailSkillError(
            "Aucune signature utilisable n'est enregistrée pour cette boîte : aucun brouillon "
            "n'a été déposé. Apprends-la d'abord (`apprendre_signature`), puis redemande.")
    en_reponse_a = None
    if ref_recu:
        from mail.lecture import _resoudre
        en_reponse_a = _resoudre(ref_recu, boite)
    try:
        resultat = await _deposer(boite, destinataire, objet, corps_signe, cc=data.get("cc"),
                                  pieces=pieces, html=html, en_reponse_a=en_reponse_a)
    except RuntimeError as e:
        raise MailSkillError(str(e))
    resultat["en_reponse"] = bool(en_reponse_a) or None
    resultat["signature"] = "apposée" if signee else "AUCUNE — aucune signature enregistrée pour la boîte"
    resultat["message_final"] = (
        f"Le brouillon « {objet or 'sans objet'} » est dans le dossier Brouillons de {boite}"
        + (f", adressé à {destinataire}" if destinataire else "")
        + (", en réponse au message d'origine" if en_reponse_a else "")
        + ". Rien n'a été envoyé.")
    resultat["a_faire"] = ("Dis en une phrase que le brouillon est dans les Brouillons de la "
                           "boîte, non envoyé. N'affirme rien d'autre.")
    return resultat


async def envoyer_email(data: dict, user) -> dict:
    """ENVOIE réellement un message. Effet EXTERNE : n'arrive ici qu'après accord.

    Le pendant de `rediger_email`, qui s'arrête au brouillon et le dit. Ici le
    message PART : c'est pourquoi le skill est déclaré `externe` — l'accord
    humain porte sur le destinataire, l'objet et le corps exacts, vérifiés par
    empreinte, et `_apercu_avant_accord` les montre avant le clic.

    Mêmes règles que le reste du courrier : sans `mailbox`, la boîte de la
    personne connectée ; nommer la boîte d'un collègue exige le droit d'ÉCRIRE
    dessus (`verifier_acces(envoi=True)`).
    """
    from mail.expedition import envoyer_message, porte_un_jeton

    cible = await _boite_a_lire(data, user)
    boite = await verifier_acces(user, cible, envoi=True)

    destinataire = (data.get("destinataire") or "").strip()
    objet = (data.get("objet") or "").strip()
    corps = (data.get("corps") or data.get("message") or "").strip()
    # Les alias, comme partout ailleurs : refuser l'action pour un NOM de
    # paramètre est le piège déjà payé avec `url` (`ouvrir_page`, 30/08).
    brut_pieces = (data.get("pieces") or data.get("pieces_jointes")
                   or data.get("fichiers") or data.get("attachments")
                   or data.get("piece") or data.get("fichier"))
    if not destinataire or "@" not in destinataire:
        raise MailSkillError(
            "Il faut `destinataire` : l'adresse exacte de la personne. Si elle "
            "n'a pas été donnée, demande-la — n'en invente jamais une.")
    if not objet or not corps:
        raise MailSkillError(
            "Il faut `objet` et le `corps` COMPLET du message : ce qui est "
            "validé est ce qui part, rien n'est complété après l'accord.")

    # Un jeton d'anonymisation resté orphelin n'a rien à faire dans un message
    # qui SORT de l'entreprise — et « [À COMPLÉTER] » est l'aveu d'un brouillon
    # inachevé : dans les deux cas on refuse, en disant quoi reprendre.
    for champ, valeur in (("destinataire", destinataire), ("objet", objet),
                          ("corps", corps)):
        if porte_un_jeton(valeur):
            raise MailSkillError(
                f"Le champ `{champ}` contient une balise de masquage jamais "
                "résolue : réécris-le avec les vraies valeurs avant l'envoi.")
    if "[À COMPLÉTER]" in corps:
        raise MailSkillError(
            "Le corps contient encore des mentions [À COMPLÉTER] : complète le "
            "brouillon avant de demander l'envoi.")

    from mail.attaches import resoudre
    pieces, refusees = await resoudre(brut_pieces, user, boite)
    from mail.instantanes import verifier as verifier_pieces_figees
    verifier_pieces_figees(data, pieces)
    # UNE PIÈCE QUI NE PEUT PAS PARTIR ARRÊTE L'ENVOI. Le compte rendu d'un
    # envoi incomplet est un mensonge par omission : le destinataire lit
    # « veuillez trouver ci-joint » et ne trouve rien. On refuse en nommant la
    # pièce ET la cause — c'est réparable au tour suivant.
    if refusees:
        raise MailSkillError(
            "Ces pièces n'ont pas pu être jointes, rien n'a été envoyé : "
            + " ; ".join(f"« {r['nom']} » ({r['raison']})" for r in refusees)
            + ".")
    # Le NOM d'une pièce sort de l'entreprise comme le corps du message : la
    # règle du jeton orphelin vaut pour lui aussi (« Devis [PER_1].pdf »).
    for p in pieces:
        if porte_un_jeton(p["nom"]):
            raise MailSkillError(
                f"Le nom de pièce « {p['nom']} » contient une balise de "
                "masquage : renomme-la avant l'envoi.")

    # La signature de la boîte, apposée sur le corps DÉFINITIF. Ce n'est pas du
    # contenu à valider : c'est l'en-tête de la maison, reproduit à l'octet.
    from mail.signature import apposer
    avant = (corps, len(pieces))
    corps, html, pieces = await apposer(boite, corps, pieces,
                                        demandee=data.get("signature"))
    signee = bool(html) or (corps, len(pieces)) != avant
    # « RENVOIE-LE AVEC LA SIGNATURE » (15/09) : aucune signature n'était
    # enregistrée, le message est reparti sans, et personne ne l'a su. Une
    # signature DEMANDÉE qui n'existe pas arrête l'envoi, en le disant.
    if _signature_exigee(data.get("signature")) and not signee:
        raise MailSkillError(
            "Aucune signature utilisable n'est enregistrée pour cette boîte : RIEN n'a été "
            "envoyé. Apprends-la d'abord (`apprendre_signature`, depuis un message ENVOYÉ), "
            "puis redemande l'envoi.")
    try:
        resultat = await envoyer_message(boite, destinataire, objet, corps,
                                         cc=data.get("cc"), pieces=pieces,
                                         html=html)
    except RuntimeError as e:
        raise MailSkillError(str(e))
    jointes = [{"nom": p["nom"], "octets": len(p["octets"])}
               for p in pieces if not p.get("inline")]
    resultat["pieces_jointes"] = jointes
    resultat["signature"] = "apposée" if signee else "AUCUNE — le message est parti sans signature"
    resultat["message_final"] = (
        f"Message envoyé à {destinataire} depuis {boite} (objet : « {objet} »)"
        + (", avec " + ", ".join(p["nom"] for p in jointes) + " en pièce jointe"
           if jointes else "")
        + ("" if signee else ", sans signature (aucune n'est enregistrée pour la boîte)") + ".")
    return resultat


def _signature_exigee(valeur) -> bool:
    """`signature: true` explicite — pas l'absence du paramètre."""
    return valeur is True or str(valeur).strip().lower() in ("true", "oui", "1", "yes")


async def resumer_fil(data: dict, user) -> dict:
    """Résume un échange de plusieurs messages et en extrait les engagements."""
    # Même raison qu'au triage : le fil est COLLÉ dans le chat, il ne se lit pas
    # dans une boîte. Exiger une adresse ici bloquait un geste qui n'ouvre rien.
    boite = await _boite_du_triage(data, user)
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
    boite = await verifier_acces(user, data.get("mailbox") or await boite_par_defaut(user))
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
    boite = await verifier_acces(user, data.get("mailbox") or await boite_par_defaut(user))

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
async def apprendre_signature(data: dict, user) -> dict:
    """Va CHERCHER la signature dans les messages ENVOYÉS de la boîte.

    Même parcours libre-service qu'`apprendre_style_email` : sans `mailbox`,
    la boîte de la personne connectée, et c'est `verifier_acces` qui borne le
    périmètre. `ref` apprend depuis UN message précis, quand les derniers
    envois ne sont pas représentatifs.

    Ce qui est appris n'est PAS une description : c'est le bloc HTML tel quel,
    ses images comprises. Le modèle ne le rédige jamais — il ne fait que le
    voir. C'est aussi pourquoi le résultat porte un bloc GARANTI : on veut que
    la personne LISE ce qui partira désormais sous ses messages.
    """
    boite = await verifier_acces(user, data.get("mailbox")
                                 or await boite_par_defaut(user))
    from mail.signature import apprendre
    resultat = await apprendre(boite, user, ref=str(data.get("ref") or ""))
    if not resultat.get("trouvee"):
        # UN ÉCHEC, PAS UN COMPTE RENDU (15/09). Rendu comme un résultat
        # ordinaire, « rien trouvé » passait pour une réussite, et le modèle a
        # répondu « la signature a bien été apprise ».
        raise MailSkillError(
            (resultat.get("message") or "Aucune signature reconnue.")
            + " Ne dis pas qu'une signature a été apprise. Pour apprendre depuis UN "
            "message précis, prends sa `ref` dans `lire_mails` avec `dossier: envoyes` "
            "(un message REÇU ne porte pas la signature de la boîte).")
    return await _fiche_signature(boite, appris=True, occurrences=resultat)


async def ma_signature(data: dict, user) -> dict:
    """Remontre la signature en vigueur pour une boîte."""
    boite = await verifier_acces(user, data.get("mailbox")
                                 or await boite_par_defaut(user))
    # MONTRER, C'EST D'ABORD AVOIR (15/09). « Affiche ma signature » sans
    # signature enregistrée rendait « aucune » et une proposition d'aller la
    # chercher : un tour de plus, et une minute de forçage. Aller la chercher
    # dans les envoyés est une LECTURE ; elle se fait.
    from mail.signature import enregistree, signature_vide
    if signature_vide(await enregistree(boite)):
        return await apprendre_signature(data, user)
    return await _fiche_signature(boite, appris=False)


async def _fiche_signature(boite: str, appris: bool, occurrences=None) -> dict:
    """La signature telle qu'on la MONTRE — un bloc mécanique, jamais rédigé.

    Le logo est redéposé pour être servi par `/api/visuels/{clé}` : le dépôt
    est adressé par le contenu, redéposer la même image ne crée pas de doublon.
    """
    from mail.signature import _cles_deposees, enregistree, signature_vide
    signature = await enregistree(boite)
    if signature_vide(signature):
        return {"boite": boite, "signature": None,
                "message": "Aucune signature enregistrée pour cette boîte.",
                "a_faire": ("Dis qu'il n'y en a pas, et propose "
                            "`apprendre_signature` pour aller la chercher "
                            "dans les messages envoyés.")}
    cles = _cles_deposees(signature.get("images") or [])
    # LA CARTE NE S'AFFICHAIT PAS (15/09) : `keyvalue` exige `rows`, et le type
    # `text` n'existe pas à l'écran. La personne n'a jamais VU la signature
    # enregistrée — ni celle de la cliente, prise à la place de la sienne.
    from mail.signature import adresses_etrangeres
    etrangeres = adresses_etrangeres(signature.get("texte") or "", boite)
    blocs = [{"type": "keyvalue", "titre": f"Signature de {boite}",
              "rows": [["Apprise le", str(signature.get("derniere_maj") or "")[:10]],
                       ["Source", signature.get("source") or "—"],
                       ["Images", str(len(cles))]]}]
    if (signature.get("texte") or "").strip():
        blocs.append({"type": "callout", "tone": "warning" if etrangeres else "info",
                      "title": ("Texte de la signature — porte l'adresse d'un tiers, elle ne sera PAS apposée"
                                if etrangeres else "Texte de la signature"),
                      "text": signature.get("texte")})
    if cles:
        blocs.append({"type": "visuel", "titre": "Images de la signature",
                      "images": cles})
    return {
        "boite": boite,
        "signature": {"texte": signature.get("texte") or "",
                      "images": len(cles),
                      "source": signature.get("source"),
                      "celle_d_un_tiers": etrangeres or None},
        "apprise": bool(appris),
        "occurrences": (occurrences or {}).get("occurrences"),
        "bloc_ui": blocs,
        # Le bloc est MÉCANIQUE : il s'affiche que le modèle le recopie ou non.
        "bloc_garanti": True,
        "message_final": (
            f"Signature de {boite} " + ("apprise" if appris else "en vigueur")
            + (f", avec {len(cles)} image(s)." if cles else ".")),
        "a_faire": ("La signature est affichée automatiquement sous ta réponse : "
                    "n'écris aucun bloc ```ui pour elle. Dis en une phrase ce "
                    "qu'elle contient, et qu'elle sera apposée à chaque envoi "
                    "(`signature: false` la retire pour un message)."),
    }


async def supprimer_signature(data: dict, user) -> dict:
    """RETIRE la signature en vigueur d'une boîte (elle n'est plus apposée).

    15/09 : « oublie la signature de Sandrine » — aucun geste ne savait retirer
    une signature mal apprise, qui serait partie sous chaque message. La ligne
    est DÉSACTIVÉE, pas effacée (réparable en base), et le geste passe par la
    règle de l'entreprise : rien ne se supprime sans le mot « supprime ».
    """
    boite = await verifier_acces(user, data.get("mailbox") or await boite_par_defaut(user),
                                 envoi=True)
    from database.connection import get_db
    from mail.signature import oublier_cache
    async with get_db() as conn:
        n = await conn.fetchval(
            """WITH maj AS (UPDATE mail_signatures SET active = false, derniere_maj = NOW()
                            WHERE mailbox = $1 AND active RETURNING 1)
               SELECT COUNT(*) FROM maj""", boite)
    await oublier_cache(boite)
    if not n:
        raise MailSkillError(f"Aucune signature n'était en vigueur pour {boite}.")
    return {"boite": boite, "retiree": True,
            "message_final": f"La signature de {boite} est retirée : elle ne sera plus apposée.",
            "a_faire": "Dis en une phrase que la signature est retirée, et propose d'apprendre la bonne."}


SKILLS_NATIFS = {
    "triage_email_entrant": triage_email_entrant,
    "redaction_email": rediger_email,
    "envoyer_email": envoyer_email,
    "deposer_brouillon": deposer_brouillon,
    "resume_fil_email": resumer_fil,
    "profil_style_email": profil_style,
    "apprendre_style_email": apprendre_style,
    "apprendre_signature": apprendre_signature,
    "ma_signature": ma_signature,
    "supprimer_signature": supprimer_signature,
}


def _skill_creer_tache():
    """Import différé : tasks/ dépend de la base, mail/skills.py est importé tôt."""
    from tasks.skills import creer_tache_agent
    return creer_tache_agent


async def creer_tache_agent(data: dict, user) -> dict:
    return await _skill_creer_tache()(data, user)


SKILLS_NATIFS["creer_tache_agent"] = creer_tache_agent


# CRÉER SANS POUVOIR DÉFAIRE N'EST PAS UNE FONCTIONNALITÉ, C'EST UN PIÈGE
# (01/09, demande de Noa). Une tâche créée par erreur en « toutes les 5
# minutes » se réveillait indéfiniment : il n'existait aucune voie pour
# l'arrêter, ni écran ni chat. Mêmes imports différés que ci-dessus.
async def mes_taches(data: dict, user) -> dict:
    from tasks.skills import mes_taches as _f
    return await _f(data, user)


async def supprimer_tache(data: dict, user) -> dict:
    from tasks.skills import supprimer_tache as _f
    return await _f(data, user)


async def suspendre_tache(data: dict, user) -> dict:
    from tasks.skills import suspendre_tache as _f
    return await _f(data, user)


SKILLS_NATIFS["mes_taches"] = mes_taches
SKILLS_NATIFS["supprimer_tache"] = supprimer_tache
SKILLS_NATIFS["suspendre_tache"] = suspendre_tache


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
    # LE NOMMAGE SUIT LE RÔLE, PAS LE DÉFAUT DE LECTURE (01/09). Depuis que
    # `boites_par_id` ne rend plus le jeton « toutes les boîtes » (le défaut de
    # chacun est SA boîte), ce test ne pouvait plus être vrai : le super_admin
    # ne voyait plus AUCUNE autre adresse, donc ne pouvait plus en NOMMER une —
    # et la règle « s'ils la demandent, ils y ont accès » devenait inapplicable.
    # On teste donc le rôle : qui peut demander une boîte doit pouvoir la nommer.
    from mail.authorization import acces_total
    # LES BOÎTES PRIVÉES DE LA DIRECTION (23/09) : nommées à la direction et au
    # super_admin seulement ; pour tout autre rôle, elles n'existent pas.
    try:
        from mail import boites_privees
        privees = boites_privees.adresses_pour(getattr(user, "role", None))
        cachees = {b["adresse"] for b in boites_privees.boites()} - set(privees)
    except Exception:  # noqa: BLE001
        privees, cachees = [], set()
    if autorisees == ["*"] or acces_total(getattr(user, "role", None)):
        return sorted(set(connues) - cachees | set(privees))
    permis = {normaliser(b) for b in autorisees}
    return [b for b in connues if b in permis and b not in cachees]


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
        # « ma boîte perso », « pro » : le LIBELLÉ d'une boîte privée de la
        # direction (23/09). Résolu pour la direction et le super_admin
        # seulement — pour les autres, la suite refuse comme d'habitude.
        try:
            from mail import boites_privees
            privee = boites_privees.resoudre_libelle(demandee, getattr(user, "role", None))
        except Exception:  # noqa: BLE001
            privee = None
        if privee:
            return privee
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

    # Rien de demandé. LE SUPER_ADMIN LIT LA BOÎTE D'UN DIRIGEANT (03/09) : son
    # adresse à lui n'est pas dans la messagerie de l'entreprise, et la règle
    # du 01/09 (« sa boîte, pour tout le monde ») le laissait sans rien à lire.
    # Depuis le 07/09, la direction hors domaine est dans le même cas : c'est
    # `boite_par_defaut` qui tranche, une fois, pour les deux.
    from mail.authorization import boite_par_defaut, domaines_messagerie, est_du_domaine
    role = (getattr(user, "role", "") or "").strip().lower()
    if role in ("super_admin", "direction"):
        defaut = await boite_par_defaut(user)
        if defaut:
            return defaut

    # Sinon : la boîte de la personne connectée, si c'en est une. LES DOMAINES
    # SONT PLUSIEURS (07/09) : un tenant a son domaine public, son
    # `onmicrosoft.com` et ses alias, et la comparaison à un seul suffixe
    # refusait des adresses parfaitement légitimes.
    propre = normaliser(getattr(user, "email", None))
    if propre and est_du_domaine(propre):
        return propre

    # Son compte applicatif est hors du domaine de messagerie — cas courant
    # d'un administrateur qui se connecte avec une adresse personnelle. Il n'a
    # donc pas de boîte propre à lire : on prend la boîte de l'entreprise si
    # elle est connue, plutôt que d'échouer sur une adresse qui n'existe pas
    # dans le tenant.
    # UNE BOÎTE QUE PERSONNE N'A NOMMÉE NE S'OUVRE PAS (01/09). `boites_visibles`
    # rend TOUTES les boîtes connues à un super_admin ou à la direction : en
    # prendre la première reviendrait à lire — et, via `envoyer_email`, à ÉCRIRE —
    # au nom d'un collègue que personne n'a désigné, la carte de validation ne
    # montrant même pas l'expéditeur quand `mailbox` est absent. Une boîte
    # DÉLÉGUÉE, elle, a été nommée une fois par un humain : c'est le seul repli
    # légitime, et seulement s'il n'y en a qu'une (sinon on ne devine pas).
    from mail.authorization import boites_par_id
    deleguees = [x for x in await boites_par_id(str(getattr(user, "id", "") or ""))
                 if x and x != "*" and x != propre]
    if len(deleguees) == 1:
        return deleguees[0]
    # LE REFUS DIT QUOI FAIRE. Il nommait le domaine attendu et s'arrêtait là :
    # la personne ne pouvait pas savoir si le tort venait de son compte, du
    # réglage, ou d'une délégation manquante.
    domaines = ", ".join(sorted(domaines_messagerie())) or "aucun configuré"
    visibles = await boites_visibles(user)
    raise MailSkillError(
        f"Aucune boîte à lire : l'adresse de votre compte ({propre or 'sans adresse'}) "
        f"n'est pas dans la messagerie de l'entreprise (domaines reconnus : {domaines}). "
        + (f"Boîtes accessibles, à nommer explicitement : {', '.join(visibles[:10])}."
           if visibles else
           "Aucune boîte ne vous est déléguée : un administrateur peut en déléguer une "
           "depuis Paramètres → Utilisateurs, ou ajouter votre domaine à MS_DOMAIN."))


# LE TABLEAU DE TOUS LES MAILS SE FABRIQUE, IL NE SE RECOPIE PAS (17/09, Symbiose ; porté chez Duret le 18/09).
#
# « Liste tous les mails des 7 derniers jours : date, expéditeur, objet, résumé,
# catégorie » — 98 mails lus, VINGT lignes à l'écran (« faute de place »), puis « mets
# ça dans un Excel » : QUATRE lignes dans le classeur. Un modèle ne recopie pas 98
# lignes : son budget de sortie n'y suffit pas, et au tour suivant les mails ne sont
# plus sous ses yeux. Même leçon que la liste des clients (23/08) et le publipostage
# (04/09) : ce qui est long se fabrique DANS le skill. Le résumé et la catégorie de
# chaque mail sont demandés au modèle par LOTS ; le tableau complet et l'Excel sont
# assemblés mécaniquement, ligne pour ligne.
# CE QUI VIENT D'ÊTRE LU N'EST PAS RELU (17/09, 16:02). « Ajoute les trois priorités en premier
# dans l'Excel et surligne-les en orange » : le tour a RELU toute la boîte et RECLASSÉ les 98
# mails — quarante secondes, cinq appels au modèle, et des catégories qui pouvaient CHANGER par
# rapport au tableau que la personne venait de lire. Les résultats d'un geste ne survivent pas
# au tour : c'est donc le skill qui se souvient, trente minutes, par personne, boîte et période.
DUREE_INVENTAIRE_S = 1800
_INVENTAIRES: dict = {}


def _cle_inventaire(user, boite: str, dossier: str, depuis, non_lus: bool = False) -> tuple:
    # LA PÉRIODE PAR SON JOUR DE DÉBUT, PAS PAR SON ÉCRITURE (22/09, Duret, prompts 5 et 6) :
    # « 7j », « semaine », « les 7 derniers jours » désignent la même liste ; rangée sous le
    # texte exact, elle n'était retrouvée que par qui l'écrivait à l'identique.
    periode = " ".join(str(depuis or "").lower().split())
    try:
        from mail.lecture import depuis_quand
        debut = depuis_quand(depuis)
        if debut is not None:
            periode = debut.date().isoformat()
    except Exception:  # noqa: BLE001 — une période illisible garde son texte
        pass
    return (str(getattr(user, "id", "") or ""), str(boite or "").lower(),
            "envoyes" if str(dossier or "").lower().startswith("env") else "recus", periode,
            "non_lus" if non_lus else "")


def _inventaire_retenu(cle: tuple):
    import time
    garde = _INVENTAIRES.get(cle)
    if garde and time.time() - garde["a"] < DUREE_INVENTAIRE_S:
        return garde
    _INVENTAIRES.pop(cle, None)
    return None


def _retenir_inventaire(cle: tuple, inventaire: dict, categories) -> None:
    import copy, time
    if len(_INVENTAIRES) >= 20:
        _INVENTAIRES.pop(min(_INVENTAIRES, key=lambda k: _INVENTAIRES[k]["a"]), None)
    _INVENTAIRES[cle] = {"a": time.time(), "inventaire": copy.deepcopy(inventaire),
                         "categories": tuple(categories or ())}


def _sans_accents(texte: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", str(texte or "").lower())
                   if not unicodedata.combining(c))


def _lettres(texte: str) -> str:
    """Lettres et chiffres seulement : « APA - PV pour signature » retrouve
    « …achèvement (APA) - PV pour signature » (18/09 : la parenthèse cassait la
    correspondance, la 3ᵉ priorité restait sans rang alors que le modèle l'annonçait)."""
    return "".join(c for c in _sans_accents(texte) if c.isalnum())


def _mettre_en_tete(messages: list[dict], priorites) -> int:
    """Place en tête, dans l'ordre demandé, les mails désignés — par un fragment de leur OBJET
    (ou de l'expéditeur), ou par leur RANG dans la liste (1 = premier). Rend le nombre trouvé."""
    if isinstance(priorites, (str, int)):
        priorites = [priorites]
    tete, pris = [], set()
    for p in list(priorites or [])[:20]:
        trouve = None
        if isinstance(p, int) or (isinstance(p, str) and p.strip().isdigit()):
            i = int(p) - 1
            trouve = i if 0 <= i < len(messages) and i not in pris else None
        else:
            voulu = _lettres(re.sub(r"^\s*((re|tr|fw|fwd)\s*:\s*)+", "", str(p), flags=re.I))
            if len(voulu) >= 3:
                trouve = next((i for i, m in enumerate(messages) if i not in pris and (
                    voulu in _lettres(m.get("objet")) or voulu in _lettres(m.get("de")))), None)
        if trouve is not None:
            pris.add(trouve)
            tete.append(trouve)
    for rang, i in enumerate(tete, 1):
        messages[i]["priorite"] = rang
    messages[:] = [messages[i] for i in tete] + [m for i, m in enumerate(messages) if i not in pris]
    return len(tete)


CATEGORIES_MAILS = ("demande de devis", "question chantier", "fournisseur", "administratif", "sans suite")
LOT_CLASSEMENT = 20


def _categories_voulues(brut) -> list[str]:
    """Les catégories demandées (liste ou texte séparé par des virgules), sinon celles de la maison."""
    if isinstance(brut, str):
        brut = [c for c in re.split(r"[,;/\n]", brut)]
    voulues = [str(c).strip().lower()[:40] for c in (brut or []) if str(c).strip()]
    return list(dict.fromkeys(voulues))[:12] or list(CATEGORIES_MAILS)


def _lire_classement(brut: str, taille: int, categories: list[str]) -> dict:
    """{rang: (résumé, catégorie)} lu dans la réponse du modèle. Tolérant, jamais inventif :
    une catégorie hors liste est écartée, un rang hors du lot aussi."""
    import json as _j
    m = re.search(r"\[.*\]", brut or "", re.S)
    try:
        lignes = _j.loads(m.group(0)) if m else []
    except ValueError:
        return {}
    sortie = {}
    for l in lignes if isinstance(lignes, list) else []:
        if not isinstance(l, dict):
            continue
        try:
            n = int(l.get("n"))
        except (TypeError, ValueError):
            continue
        if not 1 <= n <= taille:
            continue
        cat = str(l.get("categorie") or "").strip().lower()
        sortie[n] = (" ".join(str(l.get("resume") or "").split())[:180],
                     cat if cat in categories else "")
    return sortie


async def _classer_les_mails(messages: list[dict], categories: list[str]) -> int:
    """Pose `resume` et `categorie` sur chaque fiche, par lots. Rend le nombre de fiches classées."""
    import asyncio
    verrou = asyncio.Semaphore(3)

    async def _un_lot(lot: list[dict]) -> int:
        lignes = "\n".join(
            f"{i}. De : {str(m.get('de') or '')[:80]} | Objet : {str(m.get('objet') or '')[:140]} | "
            f"Extrait : {' '.join(str(m.get('apercu') or '').split())[:220]}"
            for i, m in enumerate(lot, 1))
        consigne = (
            "Voici des mails reçus par une entreprise. Pour CHACUN, écris un résumé d'UNE phrase "
            "(ce que l'expéditeur veut ou annonce, tiré de l'objet et de l'extrait, rien d'inventé) "
            "et choisis UNE catégorie dans cette liste exacte : " + " | ".join(categories) + ". "
            "Une lettre d'information, une publicité ou une notification automatique : « sans suite » "
            "si cette catégorie existe. Réponds par un tableau JSON seul, un objet par mail, dans "
            "l'ordre : [{\"n\": 1, \"resume\": \"…\", \"categorie\": \"…\"}].\n\n" + lignes)
        async with verrou:
            try:
                masque, carte = await _protege(consigne)
                lu = _lire_classement(_rehydrater(await _appeler(masque, "standard"), carte),
                                      len(lot), categories)
            except Exception as e:  # noqa: BLE001 — un lot muet laisse ses lignes « à classer »
                logger.warning("Classement d'un lot de mails impossible : %s", e)
                lu = {}
        for i, m in enumerate(lot, 1):
            m["resume"], m["categorie"] = lu.get(i, ("", ""))
        return sum(1 for i in range(1, len(lot) + 1) if lu.get(i, ("", ""))[1])

    lots = [messages[i:i + LOT_CLASSEMENT] for i in range(0, len(messages), LOT_CLASSEMENT)]
    return sum(await asyncio.gather(*[_un_lot(l) for l in lots]))


def _comptes_par_expediteur(messages: list[dict], limite: int = 20) -> list[dict]:
    """« Qui m'a écrit le plus ce mois-ci ? » (18/09, Q44 réel : 13 minutes — une lecture
    CLASSÉE de 400 mails, une relecture forcée, puis une réécriture). Un compte se calcule,
    il ne se demande pas au modèle : les expéditeurs les plus fréquents, avec l'adresse
    et jusqu'à trois objets récents chacun, sur les messages LUS (le résultat dit combien)."""
    par: dict = {}
    for m in messages:
        adresse = str(m.get("de") or "").strip()
        cle = adresse.lower()
        if not cle:
            continue
        entree = par.setdefault(cle, {"expediteur": _expediteur_lisible(m), "nombre": 0, "objets": []})
        entree["nombre"] += 1
        objet = str(m.get("objet") or "").strip()[:90]
        if objet and len(entree["objets"]) < 3 and objet not in entree["objets"]:
            entree["objets"].append(objet)
    return sorted(par.values(), key=lambda e: -e["nombre"])[:limite]


def _jour_lisible(m: dict) -> str:
    """« 18/09/2026 10:32 ». La voie IMAP (Duret) rend `date` au format RFC 2822
    (« Fri, 18 Sep 2026 08:32:14 +0000 ») : lu tel quel, il donnait « Se/18/Fri, 2026 »
    dans le tableau (18/09). L'ISO d'abord ; sinon la date se PARSE, jamais se tranche."""
    brut = str(m.get("date") or "")
    iso = str(m.get("date_iso") or "")
    if len(brut) >= 10 and brut[4] == "-" and brut[7] == "-":
        return f"{brut[8:10]}/{brut[5:7]}/{brut[:4]}" + (f" {brut[11:16]}" if len(brut) >= 16 else "")
    if brut:
        try:
            from email.utils import parsedate_to_datetime
            from zoneinfo import ZoneInfo
            d = parsedate_to_datetime(brut)
            return (d.astimezone(ZoneInfo("Europe/Paris")) if d.tzinfo else d).strftime("%d/%m/%Y %H:%M")
        except (TypeError, ValueError, IndexError):
            pass
    if len(iso) >= 10:
        return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}"
    return brut[:16]


def _expediteur_lisible(m: dict) -> str:
    """« Prénom Nom (adresse) » quand la messagerie donne le nom affiché, l'adresse seule sinon.
    Un nom qui n'est que l'adresse recopiée (envois automatiques) n'ajoute rien."""
    adresse = str(m.get("de") or "").strip()
    nom = str(m.get("de_nom") or "").strip()
    if not nom or "@" in nom or nom.lower() == adresse.lower():
        return adresse[:80]
    return f"{nom} ({adresse})"[:110] if adresse else nom[:80]


async def _livrer_inventaire(inventaire: dict, user, *, classer: bool, fichier: bool, categories=None,
                             priorites=None, surlignage=None, cle=None, deja_classe: bool = False) -> dict:
    """Le tableau COMPLET à l'écran, et l'Excel si on le demande — assemblés ligne pour ligne."""
    import asyncio
    messages = inventaire.get("messages") or []
    voulues = _categories_voulues(categories)
    # Un classement DÉJÀ fait est repris tel quel : la personne a lu ces catégories-là.
    if deja_classe and not categories:
        classer, classes = True, sum(1 for m in messages if m.get("categorie"))
    else:
        classes = await _classer_les_mails(messages, voulues) if classer and messages else 0
    if cle is not None:
        _retenir_inventaire(cle, {**inventaire, "messages": messages}, voulues if classer else ())
    en_tete = _mettre_en_tete(messages, priorites) if priorites else 0
    entetes = ((["Priorité"] if en_tete else []) + ["Date", "Expéditeur", "Objet"]
               + (["Résumé", "Catégorie"] if classer else ["Extrait"]))

    def _ligne(m: dict) -> list:
        base = (([m.get("priorite") or ""] if en_tete else [])
                + [_jour_lisible(m), _expediteur_lisible(m), str(m.get("objet") or "")[:160]])
        if classer:
            return base + [m.get("resume") or "", m.get("categorie") or "à classer"]
        return base + [" ".join(str(m.get("apercu") or "").split())[:200]]
    lignes = [_ligne(m) for m in messages]
    periode = str(inventaire.get("periode_depuis") or "")[:10]
    titre = (f"Mails reçus depuis le {periode[8:10]}/{periode[5:7]}/{periode[:4]}" if len(periode) == 10
             else "Mails non lus" if inventaire.get("non_lus") else "Mails de la période")
    blocs = [{"type": "table", "titre": f"{titre} ({len(lignes)})", "columns": entetes, "rows": lignes}]
    par_categorie = []
    if classer:
        compte_cat = {}
        for m in messages:
            compte_cat[m.get("categorie") or "à classer"] = compte_cat.get(m.get("categorie") or "à classer", 0) + 1
        par_categorie = sorted(compte_cat.items(), key=lambda kv: -kv[1])
    url = None
    if fichier and lignes:
        from bureautique.atelier import ouvrir, ajouter, terminer
        proprio = str(getattr(user, "id", "") or "")
        entete = {"titre": titre, "format": "xlsx"}
        elements = [{"type": "feuille", "nom": "Mails", "entetes": entetes, "lignes": lignes,
                     "surlignees": list(range(en_tete)), "surlignage": str(surlignage or "orange")}]
        if par_categorie:
            elements.append({"type": "feuille", "nom": "Par catégorie", "entetes": ["Catégorie", "Nombre"],
                             "lignes": [[c, n] for c, n in par_categorie]})

        def _produire():
            jeton = ouvrir(entete, proprio)
            ajouter(jeton, elements, proprio)
            return jeton, terminer(jeton, proprio)
        try:
            jeton, fiche = await asyncio.to_thread(_produire)
            url = f"/api/documents/{jeton}"
            blocs.insert(0, {"type": "fichier", "url": url, "nom": "mails.xlsx", "titre": titre,
                             "format": "xlsx", "octets": fiche.get("octets")})
        except Exception as e:  # noqa: BLE001 — le tableau reste, et l'échec se dit
            logger.warning("Excel des mails impossible : %s", e)
    complet = not inventaire.get("tronque")
    phrase = (f"{inventaire.get('total_periode') or len(lignes)} mail(s) sur la période, "
              f"{len(lignes)} listé(s)" + (" — tous." if complet else " ; la suite se lit par `curseur`."))
    if priorites and en_tete < len(priorites if isinstance(priorites, list) else [priorites]):
        inventaire = {**inventaire, "priorites_introuvables": (
            f"{en_tete} priorité(s) retrouvée(s) sur {len(priorites) if isinstance(priorites, list) else 1} : "
            "désigne chaque mail par un fragment EXACT de son objet.")}
    return {**inventaire, "classes": classes if classer else None, "priorites_en_tete": en_tete or None,
            "par_categorie": dict(par_categorie) or None, "par_expediteur": _comptes_par_expediteur(messages), "fichier": url,
            "fichier_non_produit": bool(fichier and lignes and not url) or None,
            "message_final": phrase, "bloc_garanti": True, "bloc_ui": blocs,
            "a_faire": ("Le tableau COMPLET (" + str(len(lignes)) + " lignes)"
                        + (" et le fichier Excel" if url else "")
                        + " S'AFFICHENT AUTOMATIQUEMENT : ne recopie AUCUNE ligne, n'écris aucun "
                        "tableau toi-même. Donne le total, la répartition par catégorie si elle existe, "
                        "puis ce qu'on t'a demandé EN PLUS (les mails à traiter en priorité, avec la "
                        "raison) en t'appuyant sur `messages`. Ne rappelle pas ce geste."
                        + (" Le fichier n'a PAS pu être produit : dis-le." if fichier and lignes and not url else ""))}


# L'inventaire d'une période : jusqu'à 250 messages en un geste (comme `check_mails`),
# avec un extrait court — le compte et la liste priment, `lire_mail` ouvre le détail.
# LA QUANTITÉ N'EST PAS UNE QUESTION (24/09, Noa) : un ou mille, la liste se fait.
# Mille messages à 110 caractères d'extrait tiennent dans un résultat d'inventaire
# (plafond 190 000) ; au-delà, la suite se lit par `curseur`, et c'est DIT.
MAX_INVENTAIRE_MAILS = 1000
PAGE_INVENTAIRE = 50
# Au-delà de ce rang, l'extrait se resserre : quatre cents messages doivent tenir dans UN résultat
# (18/09 : « mes mails des 30 derniers jours » = 294 messages, la lecture s'arrêtait à 250).
RANG_EXTRAIT_COURT = 250
APERCU_INVENTAIRE_COURT = 110
APERCU_INVENTAIRE = 200


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
    # Quand une PÉRIODE est demandée (« les mails de la semaine »), le détail va
    # au maximum : relevé le 22/08, 28 messages sur la période, 10 rendus par
    # défaut, et le modèle qui promet « une limite plus élevée » sans pouvoir.
    _periode = data.get("depuis") or data.get("periode") or data.get("jours")
    # Les alias : le modèle écrit « mots », « contient » ou « mots_cles » aussi
    # souvent que « recherche » — refuser l'action pour un nom de paramètre
    # est le piège déjà payé avec `url` (ouvrir_page, 30/08).
    recherche = (data.get("recherche") or data.get("mots") or data.get("mots_cles")
                 or data.get("contient") or data.get("query"))
    # « un mail dont l'OBJET est / contient … » : chercher dans l'objet SEUL (17/09). Sans cela
    # « maxime » rendait 5 279 messages — tous ceux dont le corps dit « Salut Maxime ».
    _dans_objet = data.get("objet") or data.get("sujet") or data.get("objet_contient")
    if _dans_objet and not recherche:
        recherche = "objet: " + str(_dans_objet)
    avant = data.get("avant") or data.get("avant_le") or data.get("jusqu_a")
    # Une recherche ordinaire répond avec une page pour rester rapide. La
    # pagination complète est réservée à une demande explicite d'inventaire.
    exhaustif = bool(data.get("exhaustif") or data.get("tous") or data.get("toutes")
                     or data.get("pour_tous"))
    # LES NON LUS (24/09) : « affiche mes mails non lus » = TOUS les non lus, filtrés par le
    # serveur (UNSEEN), pas les non lus parmi les 25 derniers. C'est une liste : exhaustive.
    non_lus = bool(data.get("non_lus") or data.get("non_lu") or data.get("unread")
                   or str(data.get("lus") or "").strip().lower() in ("false", "non", "0"))
    # LE DÉFAUT, C'EST LES NON LUS DE LA RÉCEPTION, TOUS (24/09, Noa : « il n'a fait que
    # 10 mails ; par défaut il fait tous ceux qui ne sont pas lus encore »). Un appel nu —
    # ni période, ni recherche, ni nombre, ni curseur, ni autre dossier — ne rend plus
    # « les 10 derniers » : il rend chaque message non lu de la boîte de réception. Un
    # nombre demandé (`limite`) ou une période gardent leur sens.
    appel_nu = not any(data.get(k) for k in ("depuis", "periode", "jours", "limite", "avant", "avant_le",
                                              "jusqu_a", "curseur", "recherche", "mots", "mots_cles",
                                              "contient", "query", "objet", "sujet", "objet_contient"))
    if appel_nu and not non_lus and str(data.get("dossier") or "recus").lower().startswith(("recus", "reçus", "inbox")):
        non_lus = True
    exhaustif = exhaustif or non_lus
    # Un Excel ou un classement de « tous les mails » EST un inventaire complet.
    veut_fichier = bool(data.get("fichier") or data.get("excel"))
    veut_classement = bool(data.get("classer") or data.get("categories"))
    exhaustif = exhaustif or veut_fichier or veut_classement
    try:
        limite = int(data.get("limite") or (25 if (_periode or recherche or avant or non_lus) else 10))
    except (TypeError, ValueError):
        limite = 25 if (_periode or recherche or avant or non_lus) else 10
    if exhaustif:
        limite = max(limite, PAGE_INVENTAIRE)
    depuis = data.get("depuis") or data.get("periode") or data.get("jours")
    options = {"classer": veut_classement, "fichier": veut_fichier, "categories": data.get("categories"),
               "priorites": data.get("priorites") or data.get("priorités") or data.get("en_tete"),
               "surlignage": data.get("surlignage") or data.get("couleur")}
    cle_inv = _cle_inventaire(user, boite, data.get("dossier") or "recus", depuis, non_lus=non_lus)
    # Un inventaire se retient 30 min, avec ou sans période — « classe-les » au tour suivant
    # ne relit pas la boîte (24/09 : la garde `not depuis` excluait les non lus).
    retenu = (None if (data.get("rafraichir") or recherche or avant or data.get("curseur")
                       or not (depuis or non_lus))
              else _inventaire_retenu(cle_inv))
    if retenu and exhaustif:
        import copy, time as _t
        inventaire = copy.deepcopy(retenu["inventaire"])
        minutes = max(0, int((_t.time() - retenu["a"]) // 60))
        inventaire["repris"] = (f"Liste reprise de la lecture faite il y a {minutes} min (aucune relecture) ; "
                                "`rafraichir: true` pour relire la boîte.")
        deja_classe = any(m.get("categorie") or m.get("resume") for m in inventaire.get("messages") or [])
        return await _livrer_inventaire(inventaire, user, cle=cle_inv, deja_classe=deja_classe, **options)
    from mail.authorization import dossiers_autorises
    from mail.lecture import DossierInterdit
    try:
        autorises = await dossiers_autorises(user)
        premier = await lire_boite(boite, data.get("dossier") or "recus", limite, depuis=depuis,
                                   recherche=recherche, avant=avant,
                                   # `apercu` : la longueur d'extrait voulue par un
                                   # appelant qui connaît son budget (check_mails).
                                   apercu=data.get("apercu") or (APERCU_INVENTAIRE if exhaustif else None),
                                   curseur=data.get("curseur"), non_lus=non_lus,
                                   # Les dossiers ouverts à CE profil (11/09).
                                   autorises=autorises)
        # UN INVENTAIRE EST UN TRAVAIL DE SKILL, PAS UNE BOUCLE DE MODÈLE (17/09, Symbiose ;
        # 18/09 chez Duret : « mets-moi dans un Excel tous les mails de la semaine » = sept
        # `check_mails` enchaînés par le modèle, puis 171 lignes recopiées DEUX fois à la main).
        # `exhaustif` sur une PÉRIODE parcourt ici toutes les pages, par curseur.
        # Un inventaire vaut pour une PÉRIODE ou pour les NON LUS (24/09) : sans l'un ni
        # l'autre, « tous les mails » serait la boîte entière (83 620 chez Duret).
        if not (exhaustif and (depuis or non_lus) and not recherche and not avant and not data.get("curseur")):
            return premier
        messages = list(premier.get("messages") or [])
        suivant, vus = premier.get("curseur_suivant"), set()
        while suivant and suivant not in vus and len(messages) < MAX_INVENTAIRE_MAILS:
            vus.add(suivant)
            page = await lire_boite(boite, data.get("dossier") or "recus",
                                    min(PAGE_INVENTAIRE, MAX_INVENTAIRE_MAILS - len(messages)), depuis=depuis,
                                    apercu=(APERCU_INVENTAIRE if len(messages) < RANG_EXTRAIT_COURT
                                            else APERCU_INVENTAIRE_COURT),
                                    curseur=suivant, autorises=autorises, non_lus=non_lus)
            messages.extend(page.get("messages") or [])
            suivant = page.get("curseur_suivant")
        total = premier.get("total_periode")
        complet = not suivant and (total is None or len(messages) >= int(total))
        inventaire = {**premier, "messages": messages, "nombre": len(messages), "non_lus": non_lus or None,
                "tronque": not complet, "curseur_suivant": suivant, "inventaire": True,
                "pour_continuer": (None if complet else
                                   f"Rappelle lire_mails avec les mêmes filtres et curseur={suivant}."),
                "compte": (f"{total if total is not None else len(messages)} message(s) "
                           + ("non lu(s)" if non_lus else "sur la période") + " ; "
                           f"{len(messages)} détaillé(s) ci-dessous"
                           + (", c'est-à-dire TOUS." if complet else " — le reste suit par `curseur`.")),
                # Les comptes PAR EXPÉDITEUR sont calculés ici : « qui m'écrit le plus » ne demande
                # ni classement ni relecture — et un résultat partiel (plafond) dit sur combien.
                "par_expediteur": _comptes_par_expediteur(messages),
                "a_faire": (("La liste porte TOUS les messages demandés : traite-les TOUS, sans "
                             "« etc. » ni échantillon. " if complet else
                             f"Les {len(messages)} plus récents sur {total} sont lus (plafond) : réponds sur ceux-là en le disant, "
                             "NE relis PAS avec `rafraichir`. ")
                            + "`par_expediteur` porte les comptes par expéditeur, déjà calculés : ne recompte pas. Ne rappelle pas ce geste.")}
        # LE TABLEAU S'AFFICHE TOUJOURS (24/09, Noa : « qu'il affiche bien les mails »). Sans
        # classement ni fichier, l'inventaire revenait NU : le modèle devait recopier 135
        # lignes, il en montrait vingt. Le tableau complet est garanti à l'écran, mécaniquement.
        return await _livrer_inventaire(inventaire, user, cle=cle_inv, **options)
    except DossierInterdit as e:
        raise MailSkillError(str(e))
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


async def lire_mail(data: dict, user) -> dict:
    """OUVRE UN message en entier : corps complet, pièces jointes nommées.

    Relevé par Noa le 31/08 : « il lit que les aperçus, qui sont donc coupés ».
    Une liste ne rend qu'un EXTRAIT par message (et Graph plafonne son aperçu
    à 255 caractères) ; jusqu'ici aucun geste n'allait chercher le reste. Même
    contrôle de droits que `lire_mails` : sa boîte, celles qui lui sont
    déléguées, toutes si administrateur. Rien n'est modifié — le message
    n'est pas marqué lu.
    """
    from mail.lecture import lire_message

    cible = await _boite_a_lire(data, user)
    boite = await verifier_acces(user, cible)      # le contrôle reste ICI
    # Les alias, comme pour `lire_mails` : refuser l'action pour un nom de
    # paramètre est le piège déjà payé avec `url`.
    ref = (data.get("ref") or data.get("reference") or data.get("id")
           or data.get("message_id") or data.get("identifiant"))
    objet = data.get("objet") or data.get("subject") or data.get("sujet") or data.get("titre")
    de = data.get("de") or data.get("expediteur") or data.get("from")
    rang = data.get("rang") or data.get("numero") or (1 if data.get("dernier") else None)
    # `pieces` : récupérer, déposer et LIRE les pièces jointes (31/08).
    brut_pieces = data.get("pieces") or data.get("pieces_jointes") or data.get("attachments")
    pieces = str(brut_pieces).strip().lower() in ("true", "1", "oui", "toutes", "all", "yes")
    # `inline` : AUSSI les images affichées DANS le corps (logo, signature en
    # image, capture collée). Séparé de `pieces` à dessein : sans ce partage,
    # chaque logo de pied de page paierait un appel de vision, à chaque mail.
    brut_inline = data.get("inline") or data.get("images") or data.get("dans_le_corps")
    inline = str(brut_inline).strip().lower() in ("true", "1", "oui", "toutes", "all", "yes")
    from mail.authorization import dossiers_autorises
    from mail.lecture import DossierInterdit
    try:
        return await lire_message(boite, ref=ref, objet=objet, de=de,
                                  dossier=data.get("dossier") or "recus", rang=rang,
                                  pieces=pieces, proprietaire=str(user.id),
                                  inline=inline, autorises=await dossiers_autorises(user))
    except DossierInterdit as e:
        raise MailSkillError(str(e))
    except NotImplementedError as e:
        raise MailSkillError(str(e))
    except (LookupError, ValueError) as e:
        raise MailSkillError(str(e))
    except Exception as e:  # noqa: BLE001 - une messagerie injoignable n'est pas une panne du chat
        logger.warning("Ouverture d'un message de %s impossible : %s", boite, e)
        detail = str(e)
        if "404" in detail:
            raise MailSkillError(
                f"Ce message n'existe plus dans la boîte {boite}, ou sa référence est périmée : "
                "relancez la lecture de la boîte pour en obtenir une fraîche.")
        raise MailSkillError(
            f"Le message n'a pas pu être ouvert dans la boîte {boite} ({detail}).")


SKILLS_NATIFS["lire_mail"] = lire_mail


async def lire_piece_jointe(data: dict, user) -> dict:
    """UNE pièce jointe : récupérée chez le fournisseur, déposée (téléchargeable,
    aperçu) et LUE — PDF, Word, Excel, image par OCR puis vision, DWG par sa
    vignette, DXF par ses textes (`mail/pieces.py`). Mêmes droits que la lecture."""
    from mail.lecture import lire_piece

    cible = await _boite_a_lire(data, user)
    boite = await verifier_acces(user, cible)
    ref = data.get("ref") or data.get("reference") or data.get("id") or data.get("piece")
    nom = data.get("nom") or data.get("fichier") or data.get("name")
    mail = data.get("mail") or data.get("message") or data.get("ref_message")
    dans_archive = (data.get("dans_archive") or data.get("fichier_archive") or data.get("membre")
                    or data.get("dans_le_zip"))
    from mail.authorization import dossiers_autorises
    from mail.lecture import DossierInterdit
    try:
        return await lire_piece(boite, ref=ref, nom=nom, mail=mail, proprietaire=str(user.id),
                                autorises=await dossiers_autorises(user), dans_archive=dans_archive,
                                page=data.get("page") or data.get("suite"))
    except DossierInterdit as e:
        raise MailSkillError(str(e))
    except NotImplementedError as e:
        raise MailSkillError(str(e))
    except (LookupError, ValueError) as e:
        raise MailSkillError(str(e))
    except Exception as e:  # noqa: BLE001
        logger.warning("Pièce jointe de %s non lue : %s", boite, e)
        raise MailSkillError(f"La pièce jointe n'a pas pu être récupérée ({e}).")


SKILLS_NATIFS["lire_piece_jointe"] = lire_piece_jointe


async def boites_mail(data: dict, user) -> dict:
    """LA LISTE des boîtes mail accessibles à la personne connectée.

    Relevé le 31/08 : « liste toutes les adresses mail que tu as » → « je n'ai
    pas de commande pour ça ». `mes_droits` disait « toutes les boîtes du
    domaine » sans les nommer, et le cloisonnement (`boites_visibles`) ne
    connaît que les boîtes configurées ou déjà lues. Un administrateur, lui,
    a le droit de voir TOUT le domaine : Graph sait le lister
    (`boites_du_domaine`, permission User.Read.All — sinon liste vide, et on
    le dit). Lecture pure, filtrée par les droits : un profil terrain ne
    voit toujours que les siennes.
    """
    from mail.collecte import fournisseur

    visibles = await boites_visibles(user)
    try:
        from mail.authorization import boites_par_id
        autorisees = await boites_par_id(str(getattr(user, "id", "") or ""))
    except Exception:  # noqa: BLE001 - dans le doute, ne rien élargir
        autorisees = []
    decouvertes: list[str] = []
    annuaire = ""
    # Même raison que dans `boites_visibles` : ce skill EST la demande explicite
    # (« liste les adresses mail »), il suit donc le rôle et non le défaut de
    # lecture, sans quoi l'annuaire du domaine n'était plus jamais consulté.
    from mail.authorization import acces_total as _acces_total
    if autorisees == ["*"] or _acces_total(getattr(user, "role", None)):
        try:
            if fournisseur() == "outlook":
                from ingestion.connectors.outlook import boites_du_domaine
                decouvertes = [normaliser(b) for b in await boites_du_domaine()]
                annuaire = ("annuaire Microsoft 365 du domaine" if decouvertes else
                            "l'annuaire du domaine n'a pas pu être lu (permission User.Read.All "
                            "absente ?) : seules les boîtes configurées ou déjà lues sont listées")
            # LA VOIE GMAIL N'AVAIT JAMAIS ÉTÉ BRANCHÉE (01/09) : ce projet lit
            # dans Google Workspace, et `boites_du_domaine` existe bien dans
            # `ingestion/connectors/gmail.py` — mais seule la branche Outlook
            # était écrite (le skill vient du socle, posé le 31/08 côté jumeau).
            # « Liste toutes les adresses mail » ne rendait donc ici que les
            # boîtes déjà configurées, jamais l'annuaire du domaine.
            elif fournisseur() == "gmail":
                from ingestion.connectors.gmail import boites_du_domaine
                decouvertes = [normaliser(b) for b in await boites_du_domaine()]
                annuaire = ("annuaire Google Workspace du domaine" if decouvertes else
                            "l'annuaire du domaine n'a pas pu être lu (délégation annuaire "
                            "absente ?) : seules les boîtes configurées ou déjà lues sont listées")
        except Exception as e:  # noqa: BLE001 - l'annuaire est un complément
            logger.info("Annuaire des boîtes indisponible : %s", e)
            annuaire = "annuaire du domaine indisponible : boîtes configurées ou déjà lues seulement"
    toutes = sorted({b for b in (visibles + decouvertes) if b})
    propre = normaliser(str(getattr(user, "email", "") or ""))
    return {
        "nombre": len(toutes),
        "boites": toutes,
        "la_votre": propre if propre in toutes else None,
        "source": annuaire or ("boîtes configurées et déjà lues, filtrées par vos droits"),
        "bloc_ui": ({"type": "list", "items": toutes} if toutes else None),
        "message": (f"{len(toutes)} boîte(s) mail accessible(s)." if toutes else
                    "Aucune boîte mail n'est accessible à ce compte."),
        "a_faire": ("Cite-les TOUTES, telles quelles (la liste s'affiche aussi sous ta réponse). "
                    "Aucune autre adresse n'est connue : n'en invente pas, ne propose pas "
                    "d'aller les chercher ailleurs."),
    }


SKILLS_NATIFS["boites_mail"] = boites_mail


async def dossiers_mail(data: dict, user) -> dict:
    """LES DOSSIERS que ce profil peut lire dans la boîte de l'entreprise (11/09).

    La boîte de réception toujours ; les autres selon ce que l'administrateur a
    ouvert (Paramètres → Utilisateurs). Le modèle s'en sert pour passer le bon
    `dossier` à `lire_mails` au lieu de deviner un nom — et pour dire, sans
    essayer, qu'un dossier n'est pas ouvert.
    """
    import asyncio
    from mail.authorization import boite_unique, dossiers_autorises
    if not boite_unique():
        return {"dossiers": [{"nom": "recus", "libelle": "Boîte de réception"},
                             {"nom": "envoyes", "libelle": "Messages envoyés"}],
                "restreint": False,
                "a_faire": "Passe le `nom` en `dossier` de `lire_mails`."}
    from mail import imap
    autorises = await dossiers_autorises(user)
    try:
        proposables = await asyncio.to_thread(imap.dossiers_proposables)
    except Exception as e:  # noqa: BLE001
        raise MailSkillError(f"Les dossiers de la boîte n'ont pas pu être lus ({str(e)[:120]}).")
    lisibles = [{"nom": "recus", "libelle": "Boîte de réception"}] + [
        d for d in proposables if imap.dossier_permis(d["nom"], autorises)]
    return {"dossiers": lisibles, "restreint": autorises is not None,
            "a_faire": ("Passe le `nom` exact en `dossier` de `lire_mails` (ou de `lire_mail`). "
                        + ("Ce profil ne lit QUE ces dossiers : pour un autre, dis qu'il n'est pas "
                           "ouvert et qu'un administrateur peut l'ouvrir dans Paramètres → "
                           "Utilisateurs — n'essaie pas." if autorises is not None else ""))}


SKILLS_NATIFS["dossiers_mail"] = dossiers_mail


async def preparer_envois(data: dict, user) -> dict:
    """UNE carte de mail par destinataire — gabarit à variables, sans limite.

    Demande de Noa du 01/09 : « un mail à 100 clients → 100 cartes ». Les
    cartes se FABRIQUENT (mail/publipostage.py), le modèle n'écrit que le
    gabarit — ou un corps sur mesure par destinataire. Rien ne part d'ici :
    chaque envoi repasse par `envoyer_email` et sa validation.
    """
    from mail.publipostage import MANQUANT, construire_cartes, variables_de

    sujet = str(data.get("sujet") or data.get("objet") or "").strip()
    gabarit = str(data.get("gabarit") or data.get("corps")
                  or data.get("message") or "").strip()
    destinataires = data.get("destinataires") or data.get("clients") or []
    if isinstance(destinataires, str):
        destinataires = [d.strip() for d in destinataires.split(",") if d.strip()]
    if not sujet:
        raise MailSkillError("Donne le `sujet` du mail (les variables {nom}… y sont permises).")
    if isinstance(destinataires, str) and destinataires.strip().lower().startswith("@"):
        raise MailSkillError("Aucun tableau n'est joint à cette conversation : joignez le "
                             "fichier (Excel, CSV) puis redemandez, ou donnez la liste.")
    if not destinataires:
        raise MailSkillError("Donne `destinataires` : `\"@tableau\"` (toutes les lignes du "
                             "fichier joint), une liste d'adresses, ou d'objets {email, nom, …}. "
                             "Avec un fichier joint, écris TOUJOURS `\"@tableau\"` : recopier "
                             "les lignes à la main n'en produit jamais la totalité.")
    if not gabarit and not any(isinstance(d, dict)
                               and (d.get("reponse") or d.get("message"))
                               for d in destinataires):
        raise MailSkillError("Donne le `gabarit` du corps (variables {nom}, {email}…), "
                             "ou un corps par destinataire (clé `reponse`).")

    r = construire_cartes(sujet, gabarit, destinataires, page=data.get("page") or 1)
    cartes = r.pop("cartes")

    # LA PERSONNALISATION PAR L'HISTORIQUE (04/09). Export de 18:48 : « adapte
    # les 95 mails : lis l'historique de chaque client et personnalise » — le
    # modèle a produit un plan, puis un Excel, puis des recherches Drive, et
    # jamais les mails : 95 lectures de boîte en chaîne, c'est un TRAVAIL DE
    # SKILL, pas une boucle de modèle. Ici : pour chaque carte, les derniers
    # échanges avec l'adresse (reçus et envoyés), puis un rédacteur qui adapte
    # le gabarit à ce qu'ils révèlent — sans rien inventer. Trois de front.
    if str(data.get("personnaliser") or "").strip().lower() in ("1", "true", "oui", "vrai", "historique"):
        cartes = await _personnaliser_cartes(cartes, user, data.get("mailbox"),
                                             str(data.get("consigne") or "").strip())
        r["personnalisees"] = sum(1 for c in cartes if c.get("personnalisee"))
    # Les VARIABLES disponibles et les trous, dits au modèle : sans cela il
    # devinait les noms de colonnes et rappelait le skill à chaque échec.
    r["variables"] = variables_de(destinataires)
    r["cartes_avec_manque"] = sum(1 for c in cartes if MANQUANT in (c.get("reponse") or "")
                                  or MANQUANT in (c.get("objet") or ""))
    if not cartes:
        return {**r, "message_final": "Aucune carte : aucun destinataire de cette "
                                      "page ne porte d'adresse.",
                "a_faire": "Dis-le, et vérifie les adresses des destinataires."}
    r["bloc_ui"] = {"type": "reponses_mail", "titre": f"Envois préparés — {sujet}",
                    "reponses": cartes}
    r["bloc_garanti"] = True
    # LA COMPLÉTION SE DIT. Le serveur a remis les lignes que le bloc d'action
    # avait laissées derrière lui : la personne doit savoir pourquoi elle voit
    # 95 cartes après en avoir vu 30, et le modèle doit cesser de croire que le
    # tableau n'en contenait que 30.
    complete = data.get("_tableau_complete") or {}
    if complete.get("total"):
        r["complete_du_tableau"] = complete
        r["message_final"] = (
            f"Le tableau joint porte {complete['total']} lignes ; l'action n'en "
            f"recopiait que {complete['recopiees']}. Les {complete['total']} ont "
            "été traitées. ")
    else:
        r["message_final"] = ""
    r["message_final"] += (f"{r['nombre']} destinataire(s), {len(cartes)} carte(s) "
                          "préparée(s)"
                          + (f" (page {r['page']} sur {r['pages']})" if r["pages"] > 1 else "")
                          + ". Rien ne part sans votre validation.")
    r["a_faire"] = ("Les cartes sont DÉJÀ affichées (éditables, cochables) : ne les "
                    "recopie pas, et NE RAPPELLE PAS ce skill dans ce tour — un rappel "
                    "REMPLACE les cartes, il ne les améliore pas. "
                    + (f"{r['personnalisees']} carte(s) ont été adaptées à l'historique des "
                       "échanges (les autres n'avaient aucun échange : gabarit tel quel). "
                       if r.get("personnalisees") is not None else "")
                    + (f"{r['cartes_avec_manque']} carte(s) portent « {MANQUANT} » : le tableau "
                       "n'a pas cette valeur pour cette personne (une société sans prénom, "
                       "par exemple). C'est NORMAL et c'est voulu — la personne corrige "
                       "la carte à l'écran. N'essaie pas d'autres noms de variables. "
                       if r["cartes_avec_manque"] else "")
                    + (f"Variables reconnues pour ces destinataires : "
                       f"{', '.join('{' + v + '}' for v in r['variables'])}. "
                       if r.get("variables") else "")
                    + ("ENCHAÎNE avec la page suivante jusqu'à couvrir tous les "
                       "destinataires. " if r["pages"] > 1 else "")
                    + "Rien ne part d'ici : chaque envoi repassera par "
                      "`envoyer_email` et sa validation. Dis en une phrase combien de "
                      "cartes sont prêtes, puis laisse la main.")
    return r


async def _personnaliser_cartes(cartes: list[dict], user, mailbox, consigne: str) -> list[dict]:
    """Chaque carte relue à la lumière des échanges passés avec son destinataire."""
    import asyncio
    from mail.lecture import lire_boite
    from mail.publipostage import CONSIGNE_PERSONNALISATION, historique_en_texte
    try:
        boite = await verifier_acces(user, mailbox or await boite_par_defaut(user))
    except Exception as e:  # noqa: BLE001 - sans boîte lisible, les cartes restent celles du gabarit
        logger.info("Personnalisation sans boîte : %s", e)
        return cartes
    verrou = asyncio.Semaphore(3)
    # Un profil de la boîte partagée sans les messages envoyés ne les lit pas
    # non plus par ce détour (11/09).
    from mail.authorization import dossiers_autorises
    autorises = await dossiers_autorises(user)
    dossiers = ("recus", "envoyes") if (autorises is None or "envoyes" in
                                         {a.lower() for a in autorises}) else ("recus",)

    async def _une(carte: dict) -> dict:
        adresse = str(carte.get("de") or "").strip()
        if not adresse or not carte.get("reponse"):
            return carte
        async with verrou:
            messages: list[dict] = []
            for dossier in dossiers:
                try:
                    lu = await lire_boite(boite, dossier, limite=4, recherche=adresse)
                    for m in (lu or {}).get("messages") or []:
                        if isinstance(m, dict):
                            messages.append({**m, "dossier": dossier})
                except Exception as e:  # noqa: BLE001 - une boîte muette ne bloque pas la carte
                    logger.info("Historique introuvable pour %s (%s) : %s", adresse, dossier, e)
            historique = historique_en_texte(messages)
            if not historique:
                return {**carte, "synthese": "Aucun échange trouvé : gabarit tel quel.",
                        "personnalisee": False}
            qui = " ".join(str(carte.get(k) or "") for k in ("prenom", "nom")).strip() or adresse
            masque, carte_pii = await _protege(
                CONSIGNE_PERSONNALISATION.format(
                    consigne=(f"CONSIGNE DE L'UTILISATEUR : {consigne}\n" if consigne else ""),
                    qui=qui, historique=historique, gabarit=carte["reponse"]))
            try:
                corps = _rehydrater(await _appeler(masque, "standard"), carte_pii).strip()
            except Exception as e:  # noqa: BLE001 - le rédacteur muet laisse le gabarit
                logger.info("Rédaction personnalisée impossible pour %s : %s", adresse, e)
                return carte
            if not corps or len(corps) < 40:
                return carte
            return {**carte, "reponse": corps, "personnalisee": True,
                    "synthese": "Échanges relus : " + historique.split("\n")[0][:160]}

    return list(await asyncio.gather(*[_une(c) for c in cartes]))


SKILLS_NATIFS["preparer_envois"] = preparer_envois

# ── L'AGENDA (04/09) ──────────────────────────────────────────────────────
# Trois gestes seulement : lire une période, chercher un créneau, poser un
# rendez-vous. Le CALCUL des créneaux vit dans `mail/agenda.py`, pas ici et
# surtout pas dans le modèle : à qui l'on donne quinze rendez-vous et qu'on
# laisse en déduire les trous, il en oublie un.

def _periode(data: dict) -> tuple:
    """La fenêtre demandée : `depuis`/`jusqu_a` en mots (« demain », « 7j ») ou
    en dates. Sans rien : d'aujourd'hui à sept jours."""
    from datetime import datetime, timedelta, timezone
    from mail.lecture import depuis_quand
    maintenant = datetime.now(timezone.utc)
    debut = depuis_quand(data.get("depuis")) if data.get("depuis") else None
    # Une période d'AGENDA regarde DEVANT : `depuis_quand` rend une date passée
    # (« 7j » = il y a sept jours), ce qui est juste pour des mails et faux ici.
    # On ne garde donc une date passée que si elle est explicitement demandée
    # comme telle (un mot de passé), sinon on part de maintenant.
    if debut and debut < maintenant - timedelta(days=1) and not data.get("passe"):
        debut = maintenant
    debut = debut or maintenant
    jours = data.get("jours")
    try:
        jours = int(jours) if jours is not None else None
    except (TypeError, ValueError):
        jours = None
    fin = depuis_quand(data.get("jusqu_a")) if data.get("jusqu_a") else None
    if fin and fin < debut:
        fin = None
    if not fin:
        from mail.agenda import MAX_JOURS
        fin = debut + timedelta(days=max(1, min(jours or 7, MAX_JOURS)))
    return debut, fin


def _quand(iso: str) -> str:
    """« jeudi 8 sept. 09:00 » — une date d'agenda se lit, elle ne se décode pas."""
    from mail.agenda import _analyser
    d = _analyser(iso)
    if not d:
        return iso or ""
    local = d.astimezone()
    jours = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
    mois = ("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août",
            "sept.", "oct.", "nov.", "déc.")
    return (f"{jours[local.weekday()]} {local.day} {mois[local.month - 1]} "
            f"{local.strftime('%H:%M')}")


async def mon_agenda(data: dict, user) -> dict:
    """Les rendez-vous d'une boîte sur une période."""
    from mail.agenda import AgendaIndisponible, lire
    boite = await verifier_acces(user, data.get("mailbox") or await boite_par_defaut(user))
    debut, fin = _periode(data)
    try:
        evenements = await lire(boite, debut, fin)
    except AgendaIndisponible as e:
        raise MailSkillError(str(e))
    except Exception as e:  # noqa: BLE001
        logger.warning("Agenda de %s illisible : %s", boite, e)
        raise MailSkillError(f"L'agenda de {boite} n'a pas pu être lu. Réessayez.")

    lignes = [[_quand(e["debut"]), e["titre"], e.get("lieu") or "—",
               str(len(e.get("participants") or [])) if e.get("participants") else "—"]
              for e in evenements]
    periode = f"du {debut.astimezone().strftime('%d/%m')} au {fin.astimezone().strftime('%d/%m')}"
    return {
        "boite": boite, "periode": periode, "nombre": len(evenements),
        "evenements": evenements,
        "bloc_ui": {"type": "table", "titre": f"Agenda {periode}",
                    "columns": ["Quand", "Rendez-vous", "Lieu", "Invités"], "rows": lignes},
        "bloc_garanti": True,
        "message_final": (f"{len(evenements)} rendez-vous {periode} sur {boite}."
                          if evenements else f"Aucun rendez-vous {periode} sur {boite}."),
        "a_faire": ("Le tableau est DÉJÀ affiché : ne le recopie pas. Dis en une phrase ce "
                    "que la période contient (la journée la plus chargée, un trou notable). "
                    "Pour proposer une date, appelle `creneaux_agenda` — ne déduis JAMAIS "
                    "les disponibilités toi-même à partir de cette liste."),
    }


SKILLS_NATIFS["mon_agenda"] = mon_agenda


async def creneaux_agenda(data: dict, user) -> dict:
    """Les créneaux libres d'au moins N minutes, dans les heures ouvrées."""
    from mail.agenda import (AgendaIndisponible, creneaux_libres, heures_ouvrees,
                             jours_ouvres, occupations)
    boite = await verifier_acces(user, data.get("mailbox") or await boite_par_defaut(user))
    debut, fin = _periode(data)
    try:
        duree = int(data.get("duree") or 60)
    except (TypeError, ValueError):
        duree = 60
    duree = max(15, min(duree, 8 * 60))
    try:
        prises = await occupations(boite, debut, fin)
    except AgendaIndisponible as e:
        raise MailSkillError(str(e))
    except Exception as e:  # noqa: BLE001
        logger.warning("Agenda de %s illisible : %s", boite, e)
        raise MailSkillError(f"L'agenda de {boite} n'a pas pu être lu. Réessayez.")

    libres = creneaux_libres(prises, debut, fin, duree)
    h_debut, h_fin, p_debut, p_fin = heures_ouvrees()
    lignes = [[_quand(d.isoformat()), f"{(f - d).seconds // 60} min disponibles"]
              for d, f in libres]
    return {
        "boite": boite, "duree_demandee": duree, "nombre": len(libres),
        "creneaux": [{"debut": d.isoformat(), "fin": f.isoformat()} for d, f in libres],
        "heures_ouvrees": f"{h_debut}h–{p_debut}h et {p_fin}h–{h_fin}h",
        "jours_ouvres": sorted(jours_ouvres()),
        "bloc_ui": {"type": "table", "titre": f"Créneaux libres — {duree} min",
                    "columns": ["Début", "Disponible"], "rows": lignes},
        "bloc_garanti": True,
        "message_final": (f"{len(libres)} créneau(x) d'au moins {duree} min sur {boite}."
                          if libres else
                          f"Aucun créneau de {duree} min sur cette période."),
        "a_faire": ("Les créneaux sont DÉJÀ affichés et CALCULÉS : ne les recopie pas, n'en "
                    "invente aucun, n'en déduis pas d'autres. Propose-en deux ou trois en "
                    "une phrase. Pour poser le rendez-vous, `creer_rendez_vous` — il "
                    "demandera l'accord avant d'écrire dans l'agenda."),
    }


SKILLS_NATIFS["creneaux_agenda"] = creneaux_agenda


async def creer_rendez_vous(data: dict, user) -> dict:
    """Pose un rendez-vous dans l'agenda. EFFET EXTERNE : il invite de vraies gens."""
    from datetime import timedelta
    from mail.agenda import AgendaIndisponible, _analyser, creer
    from mail.publipostage import MANQUANT
    boite = await verifier_acces(user, data.get("mailbox") or await boite_par_defaut(user),
                                 envoi=True)
    titre = str(data.get("titre") or data.get("objet") or "").strip()
    if not titre:
        raise MailSkillError("Donne le `titre` du rendez-vous.")
    debut = _analyser(str(data.get("debut") or ""))
    if not debut:
        raise MailSkillError(
            "Donne `debut` au format ISO (2026-09-08T09:00:00). N'invente pas une heure : "
            "propose d'abord des créneaux avec `creneaux_agenda`.")
    fin = _analyser(str(data.get("fin") or ""))
    if not fin:
        try:
            duree = int(data.get("duree") or 60)
        except (TypeError, ValueError):
            duree = 60
        fin = debut + timedelta(minutes=max(15, min(duree, 8 * 60)))

    participants = data.get("participants") or data.get("invites") or []
    if isinstance(participants, str):
        participants = [p.strip() for p in participants.replace(";", ",").split(",") if p.strip()]
    participants = [p for p in participants if "@" in p]
    # UNE ADRESSE INVENTÉE N'INVITE PERSONNE, elle invite QUELQU'UN D'AUTRE.
    # Même règle que l'envoi de mail : le modèle ne compose pas une adresse.
    for a in participants:
        if MANQUANT in a or "[" in a:
            raise MailSkillError(f"L'adresse « {a} » n'est pas une vraie adresse. "
                                 "Demande-la, ou retire cet invité.")

    try:
        evenement = await creer(boite, titre, debut, fin, participants,
                                str(data.get("lieu") or ""), str(data.get("note") or ""))
    except AgendaIndisponible as e:
        raise MailSkillError(str(e))
    except Exception as e:  # noqa: BLE001
        logger.warning("Rendez-vous non créé sur %s : %s", boite, e)
        raise MailSkillError("Le rendez-vous n'a pas pu être créé. Réessayez.")

    quand = _quand(evenement.get("debut") or debut.isoformat())
    rows = [["Quand", quand], ["Rendez-vous", evenement.get("titre") or titre]]
    if evenement.get("lieu"):
        rows.append(["Lieu", evenement["lieu"]])
    if participants:
        rows.append(["Invités", ", ".join(participants)])
    rows.append(["Agenda", boite])
    return {
        "cree": True, "boite": boite, "evenement": evenement,
        "bloc_ui": {"type": "keyvalue", "titre": "Rendez-vous créé", "rows": rows},
        "bloc_garanti": True,
        "message_final": f"Rendez-vous « {titre} » créé le {quand} sur {boite}.",
        "a_faire": ("Le rendez-vous est posé et la fiche est DÉJÀ affichée : ne la recopie "
                    "pas. Confirme en une phrase. Les invités ont reçu l'invitation."),
    }


SKILLS_NATIFS["creer_rendez_vous"] = creer_rendez_vous



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
    # ENVOYER sort de l'entreprise : validation humaine obligatoire, l'accord
    # porte sur le destinataire, l'objet et le corps exacts (payload_hash).
    "envoyer_email": "externe",
    # DÉPOSER UN BROUILLON écrit dans la messagerie de l'entreprise, rien n'en
    # sort : la personne relit et envoie elle-même depuis Outlook (15/09).
    "deposer_brouillon": "ecriture_interne",
    "profil_style_email": "ecriture_interne",
    "apprendre_style_email": "ecriture_interne",
    # Apprendre une signature ÉCRIT dans l'application (une table), rien n'en
    # sort ; la relire ne fait que lire.
    "apprendre_signature": "ecriture_interne",
    "ma_signature": "lecture",
    # Retirer une signature écrit DANS l'application ; la règle « supprime »
    # s'applique par le nom du geste (skills/suppression.py).
    "supprimer_signature": "ecriture_interne",
    # Créer une tâche n'a aucun effet hors du système : quand elle s'exécutera,
    # elle repassera par tous les contrôles, validation humaine comprise.
    "creer_tache_agent": "ecriture_interne",
    # Lister ne fait que lire. Suspendre et supprimer écrivent DANS
    # l'application et n'ont aucun effet au dehors : la règle du projet réserve
    # l'accord humain aux effets qui SORTENT. Le garde-fou est ailleurs, et il
    # vaut mieux qu'une confirmation — on ne devine jamais quelle tâche est
    # visée : une désignation ambiguë ne supprime rien et redemande.
    "mes_taches": "lecture",
    "supprimer_tache": "ecriture_interne",
    "suspendre_tache": "ecriture_interne",
    # Recherche dans la mémoire d'entreprise : ne modifie rien, et reste bornée
    # aux droits de l'appelant (cloisonnement des boîtes mail compris).
    "rechercher_documents": "lecture",
    # Lire une boîte ne modifie rien et reste borné par `verifier_acces`.
    "lire_mails": "lecture",
    # Ouvrir un message ne le marque pas lu : lecture pure, même contrôle.
    "lire_mail": "lecture",
    # Récupérer une pièce jointe ne modifie rien chez le fournisseur ; elle est
    # déposée pour la personne connectée seulement.
    "lire_piece_jointe": "lecture",
    # Lister les boîtes accessibles : lecture de la configuration et de l'annuaire.
    "boites_mail": "lecture",
    # Lister les dossiers lisibles de la boîte partagée (11/09) : lecture pure.
    "dossiers_mail": "lecture",
    "preparer_envois": "lecture",
    # L'AGENDA (04/09). Lire une période et calculer des créneaux ne touchent à
    # rien. CRÉER un rendez-vous, si : il s'inscrit dans l'agenda d'une boîte et
    # ENVOIE une invitation à de vraies personnes — c'est un effet externe au
    # même titre qu'un mail, il attend donc l'accord humain.
    "mon_agenda": "lecture",
    "creneaux_agenda": "lecture",
    "creer_rendez_vous": "externe",
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
