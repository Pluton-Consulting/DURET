"""
LA TRANSCRIPTION DE LA VOIX — dans l'application, pas dans le navigateur.

LA DEMANDE (03/09, Noa) : « le micro peut fonctionner, il faut que le
transcripteur soit intégré à l'app ». Une première version s'en remettait à
la reconnaissance vocale du NAVIGATEUR (`SpeechRecognition`) : gratuite, sans
clé — et absente sur la moitié des postes (Firefox, Chromium sans les services
Google, certains Chrome d'entreprise). Le bouton affichait « ce navigateur ne
sait pas transcrire la voix » sur un poste dont le micro marchait très bien.

CE QUI CHANGE DE CAMP. Le navigateur ne fait plus qu'ENREGISTRER (MediaRecorder,
que tous savent faire) ; c'est ce module qui transcrit, avec le modèle Google
que l'application paie déjà pour la vision et les images — même clé, même
compte, même écran de réglage. Rien de nouveau à configurer chez le client.

CE QUE LE MODÈLE REÇOIT : l'audio en clair (inlineData), et une consigne de
transcription FIDÈLE — pas de résumé, pas de reformulation, la ponctuation
posée à l'oreille. Ce qui en sort est le texte de la personne, tel qu'elle
l'a dit ; l'assistant n'y touche pas, c'est elle qui l'envoie.

Ce module ne connaît ni le chat, ni les skills : il rend du texte. Socle
commun aux deux projets.
"""
from __future__ import annotations

import asyncio
import base64
import logging

import httpx

from config import settings

logger = logging.getLogger("duret.voix.transcription")

BASE = "https://generativelanguage.googleapis.com/v1beta/models"
# Une dictée, pas une réunion : douze mégaoctets font largement dix minutes
# d'opus. Au-delà, le compte rendu de réunion prend une TRANSCRIPTION écrite.
MAX_OCTETS = 12 * 1024 * 1024
DELAI_S = 90

CONSIGNE = (
    "Transcris FIDÈLEMENT ce qui est dit dans cet enregistrement, en français. "
    "Rends UNIQUEMENT le texte prononcé, avec la ponctuation qu'on entend "
    "(phrases, virgules) : pas de résumé, pas de reformulation, pas de titre, "
    "pas de commentaire, pas de guillemets autour. Les nombres s'écrivent en "
    "chiffres, les noms propres comme on les entend. Si rien n'est dit, rends "
    "une chaîne vide."
)


class TranscriptionIndisponible(RuntimeError):
    """Clé absente, service refusé, enregistrement illisible. Jamais la clé dans le message."""


def _cle() -> str:
    from llm.cles import valeur
    cle = (valeur("google_api_key") or "").strip()
    if not cle:
        raise TranscriptionIndisponible(
            "La transcription de la voix demande la clé Google (Paramètres > Clés "
            "API) : elle n'est pas configurée sur ce serveur.")
    return cle


def _modeles() -> list[str]:
    """Le modèle audio, puis le secours de la vision : les deux lisent l'audio."""
    principal = getattr(settings, "model_google_audio", "") or getattr(settings, "model_google_vision", "")
    secours = getattr(settings, "model_google_vision_secours", "")
    return [m for i, m in enumerate((principal, secours)) if m and m not in (principal, secours)[:i]]


def _mime_propre(mime: str) -> str:
    """« audio/webm;codecs=opus » → « audio/webm » : l'API veut le type nu."""
    base = (mime or "audio/webm").split(";")[0].strip().lower()
    return base if base.startswith("audio/") else "audio/webm"


async def transcrire(octets: bytes, mime: str = "audio/webm") -> str:
    """Le texte dit dans l'enregistrement. Lève `TranscriptionIndisponible`, jamais la clé."""
    if not octets:
        return ""
    if len(octets) > MAX_OCTETS:
        raise TranscriptionIndisponible(
            "L'enregistrement est trop long pour une dictée (plus de dix minutes). "
            "Pour une réunion, collez sa transcription écrite.")
    cle = _cle()
    corps = {
        "contents": [{"parts": [
            {"text": CONSIGNE},
            {"inlineData": {"mimeType": _mime_propre(mime),
                            "data": base64.b64encode(octets).decode("ascii")}},
        ]}],
        # Une transcription n'invente pas : température au plancher.
        "generationConfig": {"temperature": 0.0},
    }
    derniere = "aucun modèle essayé"
    async with httpx.AsyncClient(timeout=DELAI_S) as client:
        for modele in _modeles():
            rep = None
            # Comme pour les visuels : un 5xx est une surcharge passagère, on
            # réessaie deux fois avant de passer au modèle suivant.
            for pause_s in (0, 3, 8):
                if pause_s:
                    await asyncio.sleep(pause_s)
                try:
                    rep = await client.post(f"{BASE}/{modele}:generateContent",
                                            params={"key": cle}, json=corps)
                except httpx.HTTPError as e:
                    derniere = f"{modele} injoignable ({type(e).__name__})"
                    rep = None
                    continue
                if rep.status_code in (500, 502, 503, 504):
                    derniere = f"{modele} : HTTP {rep.status_code}, surcharge passagère"
                    rep = None
                    continue
                break
            if rep is None:
                continue
            if rep.status_code == 429:
                raise TranscriptionIndisponible(
                    "Le quota Google est épuisé pour le moment : la voix ne peut pas "
                    "être transcrite. Réessayez dans quelques minutes.")
            if rep.status_code == 404:
                derniere = f"{modele} inconnu de cette clé"
                continue
            if rep.status_code >= 400:
                derniere = f"{modele} : HTTP {rep.status_code}"
                logger.warning("Transcription refusée par %s : HTTP %s — %s",
                               modele, rep.status_code, rep.text[:200])
                continue
            try:
                donnees = rep.json()
                parts = donnees["candidates"][0]["content"]["parts"]
                texte = "".join(str(p.get("text") or "") for p in parts if isinstance(p, dict))
            except (KeyError, IndexError, TypeError, ValueError):
                derniere = f"{modele} : réponse illisible"
                continue
            return _nettoyer(texte)
    raise TranscriptionIndisponible(
        f"La transcription n'a pas abouti ({derniere}). Réessayez ; si cela "
        "persiste, prévenez votre administrateur.")


def _nettoyer(texte: str) -> str:
    """Le texte nu : un modèle met parfois des guillemets ou une clôture autour."""
    t = (texte or "").strip()
    if t.startswith("```"):
        t = t.strip("`").strip()
    if len(t) >= 2 and t[0] in "\"«" and t[-1] in "\"»":
        t = t[1:-1].strip()
    return t
