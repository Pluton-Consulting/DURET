"""
LES MAILS DÉJÀ VUS DANS LA CONVERSATION (17/09).

Relevé de Noa (Duret) : « pourquoi je suis obligé de rementionner le mail à
chaque fois pour qu'il arrive à le lire ? » Trace : le mail est trouvé à 15:49 ;
à 15:57 « marque-le comme lu » échoue — « Référence IMAP invalide ; relire le
message ». La `ref` d'un message ne vit que dans le RÉSULTAT du geste, et un
résultat de geste n'entre pas dans l'historique du fil : au tour suivant, le
modèle n'a plus que sa prose (« je l'ai trouvé, il est arrivé à 15:31 »), sans
la moindre référence. Il en invente une, ou redemande de quel mail on parle.

Même remède que pour les images du fil (`cles_images_du_fil`) : le serveur
retient ce que la conversation a vu — objet, expéditeur, date, `ref` — et le
remet sous les yeux du modèle à chaque tour. Aucun contenu de message n'est
gardé ici, seulement de quoi le RETROUVER ; le registre est durable, donc cela
survit à un redéploiement.
"""
from __future__ import annotations

import json

MAX_VUS = 30


def _fil():
    try:
        from security.conversation import fil_courant
        return fil_courant.get()
    except Exception:  # noqa: BLE001
        return None


def noter(messages, boite: str) -> None:
    """Retient les messages que ce tour vient de voir. Ne lève jamais."""
    try:
        fil = _fil()
        if not fil or not messages:
            return
        from ressources import registre
        neufs = [{"ref": str(m.get("ref") or ""), "objet": str(m.get("objet") or "")[:120],
                  "de": str(m.get("de") or "")[:80], "date": str(m.get("date_iso") or m.get("date") or "")[:19]}
                 for m in messages if isinstance(m, dict) and m.get("ref")]
        if not neufs:
            return
        ancien = registre.lire("mails_vus", str(fil)) or {}
        deja = json.loads(ancien.get("json") or "[]") if str(ancien.get("boite") or "") == (boite or "").lower() else []
        refs = {x["ref"] for x in neufs}
        # les plus récemment vus EN TÊTE : « ce mail » désigne le premier
        liste = (neufs + [x for x in deja if x.get("ref") not in refs])[:MAX_VUS]
        registre.noter("mails_vus", str(fil), {"boite": (boite or "").lower(), "json": json.dumps(liste, ensure_ascii=False)})
    except Exception:  # noqa: BLE001 — une mémoire de confort ne fait jamais échouer une lecture
        pass


def du_fil(fil) -> tuple[str, list]:
    """(boîte, mails vus dans cette conversation — le plus récemment vu en tête)."""
    try:
        if not fil:
            return "", []
        from ressources import registre
        fiche = registre.lire("mails_vus", str(fil)) or {}
        return str(fiche.get("boite") or ""), list(json.loads(fiche.get("json") or "[]"))
    except Exception:  # noqa: BLE001
        return "", []


def retrouver(fil, boite: str, objet: str | None = None, de: str | None = None):
    """La `ref` du mail que la demande désigne : par son objet ou son expéditeur
    s'ils sont donnés, sinon LE DERNIER VU (« ce mail », « marque-le »)."""
    connue, liste = du_fil(fil)
    if not liste or (boite and connue and connue != boite.lower()):
        return None
    plat = lambda t: " ".join(str(t or "").casefold().split())
    if objet or de:
        for x in liste:
            if (not objet or plat(objet) in plat(x.get("objet"))) and (not de or plat(de) in plat(x.get("de"))):
                return x.get("ref")
        return None
    return liste[0].get("ref")
