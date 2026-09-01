"""
LA SIGNATURE de mail : la retenir telle qu'elle est, la revoir, l'apposer.

POURQUOI ELLE N'EST PAS DANS LE PROFIL DE STYLE. `mail/style.py` distille une
DESCRIPTION du style (« décris SON STYLE en 5 à 8 points ») et la réinjecte
dans un prompt : c'est exactement ce qu'il faut pour un ton, et exactement ce
qu'il ne faut pas pour une signature. Une signature ne se décrit pas, elle se
REPRODUIT — nom, fonction, téléphone, mentions légales, logo. La faire passer
par un modèle, c'est garantir qu'un jour un chiffre de téléphone changera.

D'OÙ ELLE VIENT. Du bas des messages ENVOYÉS de la boîte, en HTML : c'est là
que vit le bloc, et là que vivent ses images (`cid:`). Elle ne pouvait donc pas
être apprise avant que les pièces EN LIGNE soient récupérées (même chantier,
01/09) — c'est la même lacune qui rendait la signature invisible en lecture et
introuvable en écriture.

OÙ VIVENT LES OCTETS DU LOGO. Aux deux endroits, et il faut les deux : dans la
BASE (colonne `images`, en base64) parce qu'une signature doit survivre à un
volume Docker recréé ; et dans le dépôt des visuels au moment de l'apposer,
parce que c'est de là que l'écran sait l'afficher. Le dépôt est adressé par le
contenu (`sha256[:24]`) : redéposer la même image rend la même clé.

Module PUR pour ses deux fonctions de découpe (`separer`, `en_texte`) : le banc
les exerce sans base ni réseau.
"""
from __future__ import annotations

import base64
import html as _html
import logging
import re
import time

logger = logging.getLogger("duret.mail.signature")

MAX_SIGNATURE_HTML = 20_000
MAX_IMAGE_SIGNATURE = 512 * 1024        # un logo, pas une photo
MAX_IMAGES = 4
# Assez d'envois pour qu'une RÉCURRENCE se voie, assez peu pour ne pas payer
# huit ouvertures de message à chaque apprentissage.
MAX_ECHANTILLONS = 8
_CACHE: dict = {}                       # boîte -> (instant, signature | None)
_DUREE_CACHE_S = 120

# Les clients BALISENT leur signature : autant s'en servir plutôt que de
# deviner. Du plus fiable au plus faible.
_BALISES = (
    re.compile(r'<div[^>]*class="[^"]*gmail_signature[^"]*"', re.I),
    re.compile(r'<div[^>]*id="[Ss]ignature"', re.I),
    re.compile(r'<div[^>]*id="ms-outlook-mobile-signature"', re.I),
    re.compile(r'<table[^>]*class="[^"]*signature[^"]*"', re.I),
)
# Le séparateur normalisé (RFC 3676) : deux tirets, une espace, une fin de ligne.
_SEPARATEUR = re.compile(r"(?:<br\s*/?>|<p[^>]*>|\n)\s*--\s*(?:<br\s*/?>|</p>|\n)", re.I)
# Le repli, jamais certain : un bloc qui porte une formule de politesse ET un
# moyen de contact.
_POLITESSE = re.compile(r"cordialement|bien à vous|sincèrement|salutations", re.I)
_CONTACT = re.compile(r"(?:\+33|0)[\s.\-]?\d(?:[\s.\-]?\d{2}){4}"
                      r"|www\.|https?://|@[\w.\-]+\.\w{2,}", re.I)

_RE_BALISE = re.compile(r"<[^>]+>")
_RE_BR = re.compile(r"<br\s*/?>|</p>|</div>|</tr>", re.I)


def en_texte(html_: str) -> str:
    """Le HTML rendu lisible : les sauts de ligne gardés, les balises retirées.

    Sert de REPLI quand le message part en texte brut. Une signature affichée
    en `<table>` devient alors une suite de lignes, ce qui est très en dessous
    de l'original — mais lisible, et c'est ce qui compte.
    """
    texte = _RE_BR.sub("\n", html_ or "")
    texte = _RE_BALISE.sub("", texte)
    texte = _html.unescape(texte)
    lignes = [l.strip() for l in texte.splitlines()]
    return "\n".join(l for l in lignes if l)[:4000]


def separer(html_: str) -> tuple:
    """(corps sans signature, signature) — fonction PURE, exercée au banc.

    Rien de reconnu → `("", "")`, et on le DIT : on n'invente pas une coupure.
    Deviner une signature au jugé reviendrait à couper le dernier paragraphe
    d'un message, c'est-à-dire à perdre du contenu pour en gagner un.
    """
    html_ = html_ or ""
    if not html_.strip():
        return "", ""
    for balise in _BALISES:
        m = balise.search(html_)
        if m:
            return html_[:m.start()], html_[m.start():][:MAX_SIGNATURE_HTML]
    m = None
    for m in _SEPARATEUR.finditer(html_):
        pass                              # le DERNIER séparateur, pas le premier
    if m:
        return html_[:m.start()], html_[m.end():][:MAX_SIGNATURE_HTML]
    # Repli : le dernier bloc qui porte politesse ET contact.
    morceaux = re.split(r"(?i)(?:<br\s*/?>\s*){2,}|</p>\s*<p[^>]*>", html_)
    if len(morceaux) >= 2:
        queue = morceaux[-1]
        if _POLITESSE.search(queue) and _CONTACT.search(queue):
            coupe = html_.rfind(queue)
            return html_[:coupe], queue[:MAX_SIGNATURE_HTML]
    return "", ""


def _images_du_html(html_: str, pieces: list) -> list:
    """Les images que la signature référence, réduites à ce qui sert.

    Une pièce EN LIGNE dont le `content_id` est cité par le HTML fait partie de
    la signature ; les autres non. Sans ce tri, un logo de pied de page devenu
    pièce jointe partirait à chaque envoi.
    """
    from mail.pieces import cids_du_html
    cites = set(cids_du_html(html_))
    gardees = []
    for p in pieces or []:
        cid = (p.get("content_id") or "").strip()
        octets = p.get("octets") or b""
        if not cid or cid not in cites or not octets:
            continue
        if len(octets) > MAX_IMAGE_SIGNATURE:
            logger.info("Image de signature ignorée (%d o) : %s", len(octets), cid)
            continue
        gardees.append({"content_id": cid, "nom": p.get("nom") or "logo",
                        "mime": p.get("mime") or p.get("type") or "image/png",
                        "octets_b64": base64.b64encode(octets).decode("ascii")})
        if len(gardees) >= MAX_IMAGES:
            break
    return gardees


async def enregistree(boite: str):
    """La signature en vigueur pour cette boîte, ou None.

    Cache mémoire court, façon `llm/cles.py` : une signature est relue à chaque
    envoi, et une requête par envoi pour une donnée qui change deux fois par an
    serait du gaspillage.
    """
    boite = (boite or "").strip().lower()
    if not boite:
        return None
    fige = _CACHE.get(boite)
    if fige and time.time() - fige[0] < _DUREE_CACHE_S:
        return fige[1]
    try:
        from database.connection import get_db
        async with get_db() as conn:
            ligne = await conn.fetchrow(
                "SELECT html, texte, images, source, derniere_maj "
                "FROM mail_signatures WHERE mailbox = $1 AND active", boite)
    except Exception as e:  # noqa: BLE001 — une signature absente n'arrête rien
        logger.info("Signature non lue pour %s : %s", boite, e)
        return None
    signature = None
    if ligne:
        import json
        images = ligne["images"]
        if isinstance(images, str):     # asyncpg rend le JSONB en CHAÎNE (22/08)
            images = json.loads(images or "[]")
        signature = {"html": ligne["html"] or "", "texte": ligne["texte"] or "",
                     "images": images or [], "source": ligne["source"],
                     "derniere_maj": ligne["derniere_maj"]}
    _CACHE[boite] = (time.time(), signature)
    return signature


async def oublier_cache(boite: str = "") -> None:
    """Vide le cache — après un apprentissage, sinon l'ancienne tient 2 min."""
    if boite:
        _CACHE.pop((boite or "").strip().lower(), None)
    else:
        _CACHE.clear()


async def enregistrer(boite: str, html_: str, texte: str, images: list,
                      source: str, user_id=None) -> None:
    """Range la signature de cette boîte. Écrase la précédente : il n'y en a
    qu'une en vigueur, et garder l'historique d'une signature n'apprend rien."""
    import json

    from database.connection import get_db
    async with get_db() as conn:
        await conn.execute(
            """INSERT INTO mail_signatures
                   (mailbox, html, texte, images, source, active,
                    derniere_maj, updated_by)
               VALUES ($1, $2, $3, $4::jsonb, $5, true, NOW(), $6)
               ON CONFLICT (mailbox) DO UPDATE SET
                   html = EXCLUDED.html, texte = EXCLUDED.texte,
                   images = EXCLUDED.images, source = EXCLUDED.source,
                   active = true, derniere_maj = NOW(),
                   updated_by = EXCLUDED.updated_by""",
            (boite or "").strip().lower(), html_[:MAX_SIGNATURE_HTML], texte[:4000],
            json.dumps(images or [], ensure_ascii=False), source[:300], user_id)
    await oublier_cache(boite)


async def apprendre(boite: str, user, ref: str = "") -> dict:
    """Cherche la signature dans les messages ENVOYÉS de la boîte, et la range.

    LA RÉCURRENCE FAIT FOI : la signature est le bloc qui revient À L'IDENTIQUE
    d'un message à l'autre. Un pied de page occasionnel, une phrase de
    circonstance ne reviennent pas — c'est le seul critère qui les distingue
    sans jamais demander son avis à un modèle.
    """
    from mail.lecture import lire_boite, lire_message

    if ref:
        messages = [await lire_message(boite, ref=ref, dossier="envoyes",
                                       pieces=True, inline=True)]
    else:
        # Les derniers ENVOYÉS : c'est là que vit la signature, et nulle part
        # ailleurs. On les OUVRE un par un — une liste ne rend qu'un extrait,
        # jamais le HTML, donc jamais les `cid:`.
        liste = await lire_boite(boite, dossier="envoyes", limite=MAX_ECHANTILLONS)
        messages = []
        for m in (liste.get("messages") or [])[:MAX_ECHANTILLONS]:
            try:
                messages.append(await lire_message(
                    boite, ref=m.get("ref"), dossier="envoyes",
                    pieces=True, inline=True))
            except Exception as e:  # noqa: BLE001 — un message illisible n'arrête rien
                logger.info("Message envoyé non ouvert (%s)", e)
    candidats: dict = {}
    for m in messages or []:
        corps_html = (m or {}).get("corps_html") or ""
        _, signature = separer(corps_html)
        if not signature.strip():
            continue
        cle = re.sub(r"\s+", " ", _RE_BALISE.sub("", signature)).strip()[:800]
        if not cle:
            continue
        entree = candidats.setdefault(cle, {"n": 0, "html": signature,
                                            "pieces": [], "source": ""})
        entree["n"] += 1
        entree["pieces"] = entree["pieces"] or (m.get("pieces_jointes") or [])
        entree["source"] = entree["source"] or (
            f"message « {(m.get('objet') or 'sans objet')[:60]} » "
            f"du {(m.get('date') or '')[:10]}")

    if not candidats:
        return {"trouvee": False,
                "message": "Aucune signature reconnaissable dans les derniers "
                           "messages envoyés de cette boîte."}

    # La plus récurrente ; à égalité, la plus longue (une signature complète
    # bat une signature de téléphone).
    cle, retenue = max(candidats.items(), key=lambda kv: (kv[1]["n"], len(kv[0])))
    images = _images_du_html(retenue["html"], retenue["pieces"])
    texte = en_texte(retenue["html"])
    await enregistrer(boite, retenue["html"], texte, images,
                      retenue["source"], getattr(user, "id", None))
    logger.info("Signature apprise pour %s (%d occurrence(s), %d image(s))",
                boite, retenue["n"], len(images))
    return {"trouvee": True, "boite": boite, "texte": texte,
            "images": len(images), "occurrences": retenue["n"],
            "source": retenue["source"]}


def _cles_deposees(images: list) -> list:
    """Dépose les images de la signature et rend leurs clés d'affichage."""
    from visuels.depot import deposer_octets
    cles = []
    for i in images or []:
        try:
            octets = base64.b64decode(i.get("octets_b64") or "")
        except Exception:  # noqa: BLE001
            continue
        cle = deposer_octets(octets, i.get("mime") or "image/png")
        if cle:
            cles.append({"cle": cle, "legende": i.get("nom") or "signature"})
    return cles


async def apposer(boite: str, corps: str, pieces: list, demandee=None) -> tuple:
    """(corps, html, pièces) — le corps DÉFINITIF, signature comprise.

    Appelée par `envoyer_email` APRÈS tous les refus mécaniques (jeton
    orphelin, [À COMPLÉTER]) : la signature n'est pas du contenu à valider,
    c'est l'en-tête de la maison. `demandee=False` la retire explicitement
    (« envoie-le sans signature »).

    S'il y a des images, le corps passe en HTML : le texte de l'assistant est
    ÉCHAPPÉ et enveloppé en paragraphes, la signature collée dessous, et chaque
    image devient une pièce EN LIGNE portant le `content_id` que le HTML cite.
    Sans image, on se contente du texte — un HTML inutile ne fait qu'ajouter
    des façons de mal s'afficher.
    """
    pieces = list(pieces or [])
    if demandee is False or str(demandee).lower() in ("false", "non", "0"):
        return corps, "", pieces
    signature = await enregistree(boite)
    if not signature or not (signature.get("html") or signature.get("texte")):
        return corps, "", pieces

    images = signature.get("images") or []
    if not images:
        # Pas d'image : le texte suffit, et il reste lisible partout.
        return (corps.rstrip() + "\n\n" + (signature.get("texte") or "")).strip(), \
            "", pieces

    paragraphes = "".join(
        f"<p>{_html.escape(bloc).replace(chr(10), '<br>')}</p>"
        for bloc in re.split(r"\n{2,}", corps.strip()) if bloc.strip())
    html_ = f"<html><body>{paragraphes}{signature['html']}</body></html>"
    for i in images:
        try:
            octets = base64.b64decode(i.get("octets_b64") or "")
        except Exception:  # noqa: BLE001
            continue
        if not octets:
            continue
        pieces.append({"nom": i.get("nom") or "logo",
                       "mime": i.get("mime") or "image/png",
                       "octets": octets, "inline": True,
                       "content_id": i.get("content_id")})
    return corps, html_, pieces
