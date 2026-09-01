"""
L'ENVOI RÉEL d'un message — le geste qui manquait au socle mail.

`rediger_email` produit un BROUILLON et le dit (« Aucun message n'a été
envoyé ») ; jusqu'au 30/08, rien dans l'application ne savait FAIRE PARTIR un
message. L'assistant a même promis d'envoyer (défaut n°4 du 27/08, corrigé au
prompt) précisément parce qu'aucun geste ne le permettait. Ce module ferme la
boucle : rédiger reste gratuit et immédiat, ENVOYER est un skill à effet
EXTERNE — l'accord humain porte sur le destinataire, l'objet et le corps
exacts (payload_hash), et c'est exactement cela qui part.

Il parle au MÊME fournisseur que la lecture (`mail.collecte.fournisseur`) :

  * Outlook — Graph `POST /users/{boîte}/sendMail`, avec le jeton applicatif
    du connecteur. L'application doit détenir l'autorisation `Mail.Send`
    (portail Azure, consentement admin) ; sans elle Graph rend 403, et ce
    module le dit dans les mots de la personne qui devra corriger.
  * Gmail — `users().messages().send`, par le connecteur : la connexion
    PERSONNELLE de la boîte d'abord (le consentement de `mail/google_perso`
    porte déjà le scope d'envoi), l'emprunt d'identité ensuite — délégation
    domaine avec le SEUL scope `gmail.send`, à accorder dans la console Admin.

PIÈCES JOINTES ET IMAGES DANS LE CORPS (01/09). Jusqu'à cette date, aucune
pièce ne pouvait partir : `_message_graph` ne portait pas de clé `attachments`,
et `_mime_gmail` fabriquait un `MIMEText`, mono-partie PAR CONSTRUCTION. C'est
ce que l'assistant disait en production, mot pour mot : « Je ne peux pas
joindre directement un fichier à un email via mes actions ». Deux notions
distinctes entrent ici, et les confondre est le grand classique du sujet :
  · une PIÈCE JOINTE se lit dans la liste des pièces du client ;
  · une image EN LIGNE (`inline`) s'affiche DANS le corps, à l'endroit que
    désigne son `cid:` — c'est ainsi qu'une signature reste une signature.
Une image en ligne exige donc un corps HTML : un corps `Text` ne peut porter
aucun `cid:`, et l'image partirait en pièce jointe muette au bas du message.

Les CONSTRUCTEURS de message sont des fonctions pures, séparées de l'appel
réseau : c'est ce qui permet aux bancs (`test_envoi_mail.py`,
`test_pieces_envoi.py`) de vérifier ce qui part — destinataires, copies, objet
accentué, structure MIME — sans jamais rien envoyer.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger("duret.mail.expedition")

# Un jeton d'anonymisation resté orphelin (« [PER_1] », « [EMAIL_2] ») n'est
# pas une valeur : dans un message qui SORT de l'entreprise, il n'a rien à
# faire — même règle que pour un fichier remis à quelqu'un (cf. routines).
# Contrairement au fichier, il n'existe ici aucun repli honnête : on REFUSE,
# et le message d'erreur dit quoi reformuler.
_JETON_ORPHELIN = re.compile(r"\[[A-Z]+_\d+\]")

# Graph plafonne la requête `sendMail` : une pièce posée DANS le JSON doit
# rester petite (Microsoft documente ~3 Mo par pièce, ~4 Mo pour la requête
# entière). Au-delà, le chemin n'est plus un envoi direct mais un BROUILLON
# que l'on remplit par session de téléversement, puis qu'on envoie.
# ⚠️ Ces deux valeurs sont écrites d'après la documentation Microsoft, JAMAIS
# mesurées contre le tenant : si un envoi de 4 Mo échoue, c'est ici qu'on
# baisse le seuil, pas dans le skill.
SEUIL_TELEVERSEMENT = 3 * 1024 * 1024
# Chaque tronçon d'une session Graph doit être un multiple de 320 Kio.
TRONCON = 320 * 1024 * 10                       # 3,2 Mo


def porte_un_jeton(texte: str) -> bool:
    """Le texte contient-il un jeton d'anonymisation jamais réhydraté ?"""
    return bool(_JETON_ORPHELIN.search(str(texte or "")))


def _adresses(cc) -> list[str]:
    """Une liste d'adresses propre, quel que soit ce que le modèle a passé."""
    if not cc:
        return []
    if isinstance(cc, str):
        cc = re.split(r"[;,]", cc)
    return [str(a).strip() for a in cc if str(a).strip()][:10]


def octets_des_pieces(pieces) -> int:
    """Le poids BRUT des pièces, avant l'inflation de 33 % du base64."""
    return sum(len(p.get("octets") or b"") for p in (pieces or []))


def _piece_graph(p: dict) -> dict:
    """UNE pièce au format Graph.

    `contentBytes` est du base64 STANDARD, jamais l'alphabet urlsafe : Graph
    refuse les autres. Et une image en ligne porte `isInline` + `contentId` —
    c'est ce couple, et lui seul, qui la place dans le corps plutôt que dans la
    liste des pièces jointes.
    """
    import base64

    piece = {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": p.get("nom") or "piece-jointe",
        "contentType": p.get("mime") or "application/octet-stream",
        "contentBytes": base64.b64encode(p.get("octets") or b"").decode("ascii"),
    }
    if p.get("inline"):
        piece["isInline"] = True
        piece["contentId"] = p.get("content_id") or p.get("nom") or "image"
    return piece


def _message_graph(destinataire: str, objet: str, corps: str, cc=None,
                   pieces=None, html: str = "") -> dict:
    """Le corps EXACT du POST Graph `sendMail` — pur, donc vérifiable au banc."""
    message = {
        "subject": objet,
        # Le corps passe en HTML dès qu'une image doit s'afficher DEDANS.
        "body": ({"contentType": "HTML", "content": html} if html
                 else {"contentType": "Text", "content": corps}),
        "toRecipients": [{"emailAddress": {"address": destinataire}}],
    }
    copies = _adresses(cc)
    if copies:
        message["ccRecipients"] = [{"emailAddress": {"address": a}} for a in copies]
    if pieces:
        message["attachments"] = [_piece_graph(p) for p in pieces]
    # `saveToSentItems` : le message envoyé doit se retrouver dans « Éléments
    # envoyés », sinon la boîte ment à son propriétaire — et l'apprentissage du
    # style (mail/style.py) ne le verrait jamais.
    return {"message": message, "saveToSentItems": True}


def _mime_gmail(boite: str, destinataire: str, objet: str, corps: str, cc=None,
                pieces=None, html: str = "") -> str:
    """Le message Gmail encodé (base64url), prêt pour `messages().send`.

    Structure : `mixed` porte les pièces jointes ; à l'intérieur, `related`
    porte le corps HTML et les images qu'il désigne par `cid:`. C'est la seule
    imbrication que tous les clients savent lire — une image `related` remontée
    au niveau `mixed` s'affiche en pièce jointe, pas dans le texte.
    """
    import base64
    from email import encoders
    from email.mime.base import MIMEBase
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    jointes = [p for p in (pieces or []) if not p.get("inline")]
    inlines = [p for p in (pieces or []) if p.get("inline")]

    if html:
        contenu = MIMEMultipart("related")
        contenu.attach(MIMEText(html, "html", "utf-8"))
        for p in inlines:
            majeur, _, mineur = (p.get("mime") or "image/png").partition("/")
            image = MIMEBase(majeur, mineur or "octet-stream")
            image.set_payload(p.get("octets") or b"")
            encoders.encode_base64(image)
            # LES CHEVRONS SONT OBLIGATOIRES dans l'en-tête ; le corps HTML,
            # lui, écrit `cid:` SANS chevrons. Les confondre est le grand
            # classique de l'image en ligne qui ne s'affiche pas.
            image.add_header("Content-ID",
                             f"<{p.get('content_id') or p.get('nom') or 'image'}>")
            image.add_header("Content-Disposition", "inline",
                             filename=p.get("nom") or "image")
            contenu.attach(image)
    else:
        contenu = MIMEText(corps, "plain", "utf-8")

    if jointes:
        mime = MIMEMultipart("mixed")
        mime.attach(contenu)
        for p in jointes:
            majeur, _, mineur = (p.get("mime")
                                 or "application/octet-stream").partition("/")
            partie = MIMEBase(majeur, mineur or "octet-stream")
            partie.set_payload(p.get("octets") or b"")
            encoders.encode_base64(partie)
            # `filename=` gère seul l'encodage RFC 2231 d'un nom accentué
            # (« Devis été.pdf ») : une raison de plus de ne jamais fabriquer
            # ces en-têtes à la main.
            partie.add_header("Content-Disposition", "attachment",
                              filename=p.get("nom") or "piece-jointe")
            mime.attach(partie)
    else:
        mime = contenu

    mime["To"] = destinataire
    mime["From"] = boite
    mime["Subject"] = objet
    copies = _adresses(cc)
    if copies:
        mime["Cc"] = ", ".join(copies)
    return base64.urlsafe_b64encode(mime.as_bytes()).decode("ascii")


async def _envoyer_par_brouillon(jeton: str, boite: str, charge: dict,
                                 pieces: list, destinataire: str,
                                 objet: str) -> dict:
    """LE CHEMIN DES PIÈCES LOURDES : brouillon → téléversement → envoi.

    Graph refuse une pièce posée dans le JSON de `sendMail` au-delà de quelques
    mégaoctets. Le contournement documenté est en quatre temps :
      1. POST /users/{boîte}/messages — le brouillon, corps et destinataires
         compris, SANS les pièces (elles n'y tiendraient pas) ;
      2. POST .../messages/{id}/attachments/createUploadSession, une par pièce ;
      3. PUT sur l'`uploadUrl` rendu, par tronçons, `Content-Range` à l'appui ;
      4. POST .../messages/{id}/send.
    `saveToSentItems` n'existe pas sur ce chemin : un brouillon envoyé se range
    tout seul dans les éléments envoyés.

    ⚠️ Ce chemin exige `Mail.ReadWrite` (application) EN PLUS de `Mail.Send`.
    Quand elle manque, on le dit dans les mots de qui devra corriger, au lieu
    de laisser remonter un 403 nu.
    """
    import httpx

    entetes = {"Authorization": f"Bearer {jeton}",
               "Content-Type": "application/json"}
    base = f"https://graph.microsoft.com/v1.0/users/{boite}/messages"
    message = dict(charge.get("message") or {})
    message.pop("attachments", None)

    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.post(base, json=message, headers=entetes)
        if r.status_code == 403:
            raise RuntimeError(
                "Les pièces sont trop lourdes pour un envoi direct, et le "
                "serveur de courrier refuse de créer un brouillon : il faut "
                "accorder l'autorisation « Mail.ReadWrite » (application) dans "
                "le portail Azure, en plus de « Mail.Send ».")
        if r.status_code >= 300:
            raise RuntimeError(
                f"Le brouillon n'a pas pu être créé (HTTP {r.status_code}) : "
                f"{r.text[:300]}")
        identifiant = (r.json() or {}).get("id")
        if not identifiant:
            raise RuntimeError("Le serveur de courrier n'a pas rendu "
                               "d'identifiant de brouillon.")

        for p in pieces or []:
            octets = p.get("octets") or b""
            nom = p.get("nom") or "piece-jointe"
            rs = await client.post(
                f"{base}/{identifiant}/attachments/createUploadSession",
                json={"AttachmentItem": {
                    "attachmentType": "file", "name": nom,
                    "size": len(octets),
                    "contentType": p.get("mime") or "application/octet-stream"}},
                headers=entetes)
            if rs.status_code >= 300:
                raise RuntimeError(
                    f"Le téléversement de « {nom} » a été refusé "
                    f"(HTTP {rs.status_code}) : {rs.text[:200]}")
            url = (rs.json() or {}).get("uploadUrl")
            if not url:
                raise RuntimeError(f"Aucune adresse de téléversement pour « {nom} ».")
            total = len(octets)
            for debut in range(0, total, TRONCON):
                bout = octets[debut:debut + TRONCON]
                fin = debut + len(bout) - 1
                # La session de téléversement s'authentifie par son URL : y
                # rajouter le jeton est une erreur documentée (Graph refuse).
                rp = await client.put(
                    url, content=bout,
                    headers={"Content-Length": str(len(bout)),
                             "Content-Range": f"bytes {debut}-{fin}/{total}"})
                if rp.status_code >= 300:
                    raise RuntimeError(
                        f"Le téléversement de « {nom} » s'est interrompu "
                        f"(HTTP {rp.status_code}).")

        re_ = await client.post(f"{base}/{identifiant}/send", headers=entetes)
        if re_.status_code >= 300:
            raise RuntimeError(
                f"Le message n'a pas pu être envoyé après téléversement "
                f"(HTTP {re_.status_code}) : {re_.text[:300]}")

    return {"envoye": True, "boite": boite, "destinataire": destinataire,
            "objet": objet, "chemin": "brouillon"}


async def envoyer_message(boite: str, destinataire: str, objet: str,
                          corps: str, cc=None, pieces=None,
                          html: str = "") -> dict:
    """Fait réellement partir le message, chez le fournisseur configuré.

    Lève avec un message en français quand l'envoi est impossible : l'appelant
    (le skill `envoyer_email`) le restitue tel quel, et la personne sait quoi
    corriger — jamais un succès optimiste sur un échec (leçon nas_deposer).
    """
    from mail.collecte import fournisseur
    nom = fournisseur()                        # lève si rien n'est configuré

    logger.info("Envoi d'un message depuis %s via %s (%d pièce(s), %d o)",
                boite, nom, len(pieces or []), octets_des_pieces(pieces))
    if nom == "outlook":
        import httpx
        from ingestion.connectors.outlook import _jeton

        jeton = await _jeton()
        charge = _message_graph(destinataire, objet, corps, cc, pieces, html)
        if octets_des_pieces(pieces) > SEUIL_TELEVERSEMENT:
            return await _envoyer_par_brouillon(jeton, boite, charge, pieces,
                                                destinataire, objet)
        url = f"https://graph.microsoft.com/v1.0/users/{boite}/sendMail"
        # 120 s et non 30 : un message avec pièces se téléverse dans la requête.
        async with httpx.AsyncClient(timeout=120) as client:
            reponse = await client.post(
                url, json=charge,
                headers={"Authorization": f"Bearer {jeton}",
                         "Content-Type": "application/json"})
        if reponse.status_code == 202:
            return {"envoye": True, "boite": boite,
                    "destinataire": destinataire, "objet": objet}
        if reponse.status_code == 403:
            raise RuntimeError(
                "Le serveur de courrier refuse l'ENVOI : l'application n'a que "
                "le droit de lecture. Il faut accorder l'autorisation "
                "« Mail.Send » (application) dans le portail Azure, avec le "
                "consentement d'un administrateur.")
        if reponse.status_code == 413:
            raise RuntimeError(
                "Le message est trop lourd pour le serveur de courrier. "
                "Déposez les pièces sur le Drive et envoyez le lien, ou "
                "allégez les fichiers.")
        raise RuntimeError(
            f"L'envoi a été refusé par le serveur de courrier "
            f"(HTTP {reponse.status_code}) : {reponse.text[:300]}")

    # Gmail. Le connecteur est propre au client qui vit dans Google Workspace :
    # sur un projet qui n'en a pas, l'erreur dit la vraie cause au lieu d'un
    # ModuleNotFoundError anonyme au fond d'un journal.
    import asyncio

    def _travail() -> None:
        try:
            from ingestion.connectors.gmail import _service_envoi
        except ImportError as e:
            raise RuntimeError(
                "Ce projet n'a pas de connecteur Gmail : l'envoi n'est pas "
                "configuré pour ce fournisseur de courrier.") from e
        service = _service_envoi(boite)
        service.users().messages().send(
            userId="me",
            body={"raw": _mime_gmail(boite, destinataire, objet, corps, cc,
                                     pieces, html)},
        ).execute()

    try:
        await asyncio.to_thread(_travail)
    except RuntimeError:
        raise
    except Exception as e:  # noqa: BLE001 — l'API Google lève ses propres types
        texte = str(e)
        if "insufficient" in texte.lower() or "403" in texte:
            raise RuntimeError(
                "Le serveur de courrier refuse l'ENVOI : le consentement ne "
                "porte que la lecture. Reliez à nouveau la boîte (Paramètres > "
                "Ma boîte Google) ou accordez le scope gmail.send à la "
                "délégation domaine (console Admin).") from e
        if "too large" in texte.lower() or "413" in texte:
            raise RuntimeError(
                "Le message est trop lourd pour le serveur de courrier. "
                "Déposez les pièces sur le Drive et envoyez le lien, ou "
                "allégez les fichiers.") from e
        raise RuntimeError(f"L'envoi a échoué : {texte[:300]}") from e
    return {"envoye": True, "boite": boite,
            "destinataire": destinataire, "objet": objet}
