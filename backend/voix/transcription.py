"""
LA TRANSCRIPTION DE LA VOIX — dans l'application, et SANS JETON D'IA si possible.

LA DEMANDE (03/09, Noa) : « le micro peut fonctionner, il faut que le
transcripteur soit intégré à l'app » — puis : « il n'y a pas une solution pour
retranscrire sans token IA ? ». Si.

DEUX MOTEURS, DANS CET ORDRE :

  1. WHISPER LOCAL (`faster-whisper`, open source, sur le CPU du conteneur).
     Aucun appel externe, aucun jeton, le son ne quitte pas le serveur. Le
     modèle `base` en français (03/09 : `small` était « beaucoup trop lent »
     sur le VPS — `base` va trois fois plus vite, en glouton, pour une dictée
     qu'on relit de toute façon) : ~150 Mo téléchargés au build de l'image
     (ou au premier usage, dans le volume des documents), préchargé au
     démarrage du backend. `WHISPER_MODELE=small` si la machine suit. C'est le
     moteur PAR DÉFAUT.

  2. GOOGLE (le modèle déjà payé pour la vision et les images) — le SECOURS,
     quand Whisper n'est pas installé, ou sur réglage `TRANSCRIPTION_MOTEUR=google`.

LE TEXTE S'ÉCRIT AU FUR ET À MESURE, et cela coûte quelque chose en local :
le navigateur envoie toutes les six secondes L'ENREGISTREMENT DEPUIS LE DÉBUT
(un mot coupé à la frontière de deux morceaux ne doit pas disparaître). Chez
Google, retranscrire tout à chaque fois ne gêne pas ; sur un CPU, une dictée
de deux minutes retranscrirait deux minutes toutes les six secondes et
prendrait du retard. D'où le CACHE INCRÉMENTAL : par personne, on retient
l'empreinte de ce qui a déjà été entendu, sa durée et son texte ; quand le
nouvel enregistrement COMMENCE par l'ancien (c'est le cas, les morceaux
s'ajoutent), on ne transcrit que la fin, avec une seconde de recouvrement et
le texte précédent en amorce. Le client, lui, ne sait rien de tout cela : il
envoie tout, il reçoit tout.

CE QUE LE MODÈLE REÇOIT : l'audio en clair et une consigne de transcription
FIDÈLE. Ce qui en sort est le texte de la personne, tel qu'elle l'a dit ;
l'assistant n'y touche pas, c'est elle qui l'envoie.

Module SOCLE, commun aux deux projets.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import logging
import os
import threading
import time

import httpx

from config import settings

logger = logging.getLogger("duret.voix.transcription")

BASE = "https://generativelanguage.googleapis.com/v1beta/models"
# Une dictée, pas une réunion : douze mégaoctets font largement dix minutes
# d'opus. Au-delà, le compte rendu de réunion prend une TRANSCRIPTION écrite.
MAX_OCTETS = 12 * 1024 * 1024
DELAI_S = 90
# Whisper décode tout en 16 kHz mono.
HZ = 16000
# Le recouvrement relu avant la partie neuve : une seconde, pour ne pas couper
# un mot en deux à la frontière du dernier envoi.
RECOUVREMENT_S = 1.0
# Un cache par personne, oublié au bout de dix minutes sans nouvelle : la
# durée maximale d'une dictée.
CACHE_TTL_S = 600

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


# ── LE MOTEUR LOCAL ───────────────────────────────────────────────────────
_MODELE = None
_MODELE_VERROU = threading.Lock()
_LOCAL_INDISPONIBLE: str | None = None    # la raison, une fois pour toutes


def _dossier_modeles() -> str:
    """Là où le modèle vit : le volume des documents, qui survit au redéploiement."""
    return os.path.join(os.environ.get("DOCUMENTS_DIR", "/tmp/symbiose-documents"), "modeles")


def moteur_local_disponible() -> bool:
    """`faster-whisper` est-il installé ? Sans lui, Google prend le relais."""
    global _LOCAL_INDISPONIBLE
    if _LOCAL_INDISPONIBLE is not None:
        return False
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception as e:  # noqa: BLE001
        _LOCAL_INDISPONIBLE = f"faster-whisper absent ({type(e).__name__})"
        return False


def _modele_local():
    """Le modèle Whisper, chargé une fois pour toutes (plusieurs secondes)."""
    global _MODELE
    if _MODELE is not None:
        return _MODELE
    with _MODELE_VERROU:
        if _MODELE is None:
            from faster_whisper import WhisperModel
            nom = getattr(settings, "whisper_modele", "base") or "base"
            debut = time.monotonic()
            # TOUS les cœurs : la transcription est le seul travail CPU lourd
            # du conteneur, et une dictée attend qu'il soit fini.
            _MODELE = WhisperModel(nom, device="cpu", compute_type="int8",
                                   cpu_threads=max(2, os.cpu_count() or 2),
                                   download_root=_dossier_modeles())
            logger.info("Whisper local « %s » chargé en %.1f s", nom, time.monotonic() - debut)
    return _MODELE


def _decoder(octets: bytes):
    """L'audio en échantillons 16 kHz mono, quel que soit le conteneur (webm, mp4, ogg)."""
    from faster_whisper.audio import decode_audio
    return decode_audio(io.BytesIO(octets), sampling_rate=HZ)


def _transcrire_echantillons(audio, amorce: str = "") -> str:
    modele = _modele_local()
    # `beam_size=1` (glouton) : deux fois plus rapide qu'un faisceau de 2, pour
    # une dictée qu'on relit de toute façon. Relevé de Noa (03/09) : « ça
    # fonctionne bien mais c'est beaucoup trop lent ».
    segments, _info = modele.transcribe(
        audio, language="fr", beam_size=1, vad_filter=True,
        initial_prompt=(amorce[-200:] or None),
        condition_on_previous_text=False)
    return " ".join(s.text.strip() for s in segments if getattr(s, "text", "").strip()).strip()


# ── LE CACHE INCRÉMENTAL, par personne ───────────────────────────────────
# {cle: {"empreinte": sha256 des `longueur` premiers octets, "longueur": int,
#        "secondes": float déjà transcrites, "texte": str, "quand": float}}
_CACHE: dict[str, dict] = {}


def _lire_cache(cle: str, octets: bytes) -> dict | None:
    entree = _CACHE.get(cle)
    if not entree:
        return None
    if time.monotonic() - entree["quand"] > CACHE_TTL_S:
        _CACHE.pop(cle, None)
        return None
    n = entree["longueur"]
    if len(octets) < n or hashlib.sha256(octets[:n]).hexdigest() != entree["empreinte"]:
        return None                        # une autre dictée : on repart de zéro
    return entree


def _ecrire_cache(cle: str, octets: bytes, secondes: float, texte: str) -> None:
    _CACHE[cle] = {"empreinte": hashlib.sha256(octets).hexdigest(), "longueur": len(octets),
                   "secondes": secondes, "texte": texte, "quand": time.monotonic()}


def _transcrire_local(octets: bytes, cle_cache: str) -> str:
    audio = _decoder(octets)
    duree = len(audio) / HZ
    precedent = _lire_cache(cle_cache, octets) if cle_cache else None
    if precedent and precedent["secondes"] > RECOUVREMENT_S:
        depuis = max(0.0, precedent["secondes"] - RECOUVREMENT_S)
        neuf = _transcrire_echantillons(audio[int(depuis * HZ):], amorce=precedent["texte"])
        texte = _recoller(precedent["texte"], neuf)
    else:
        texte = _transcrire_echantillons(audio)
    if cle_cache:
        _ecrire_cache(cle_cache, octets, duree, texte)
    return texte


def _recoller(avant: str, suite: str) -> str:
    """Le texte d'avant plus la suite, sans répéter les mots relus dans le recouvrement.

    Whisper a réentendu la dernière seconde : les deux ou trois derniers mots
    d'`avant` reviennent souvent en tête de `suite`. On retire le plus long
    chevauchement de mots (jusqu'à six) avant de coller.
    """
    a, s = avant.split(), suite.split()
    if not a or not s:
        return (avant + " " + suite).strip()
    for k in range(min(6, len(a), len(s)), 0, -1):
        if [m.lower().strip(".,;:!?") for m in a[-k:]] == [m.lower().strip(".,;:!?") for m in s[:k]]:
            return (" ".join(a) + " " + " ".join(s[k:])).strip()
    return (" ".join(a) + " " + " ".join(s)).strip()


# ── LE SECOURS : GOOGLE ──────────────────────────────────────────────────
def _cle() -> str:
    from llm.cles import valeur
    cle = (valeur("google_api_key") or "").strip()
    if not cle:
        raise TranscriptionIndisponible(
            "La transcription de la voix demande soit Whisper local (faster-whisper "
            "dans l'image), soit la clé Google (Paramètres > Clés API) : aucun des "
            "deux n'est disponible sur ce serveur.")
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


async def _transcrire_google(octets: bytes, mime: str) -> str:
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


async def prechauffer() -> None:
    """Charge le modèle AU DÉMARRAGE, en arrière-plan : la première dictée ne
    doit pas attendre les secondes du chargement — c'est là que « trop lent »
    se ressent le plus. Ne bloque rien, ne lève rien."""
    if moteur_choisi() != "local":
        return
    try:
        await asyncio.to_thread(_modele_local)
    except Exception as e:  # noqa: BLE001
        logger.warning("Whisper local non préchargé (%s) : il se chargera à la première dictée", e)


# ── L'ENTRÉE ─────────────────────────────────────────────────────────────
def moteur_choisi() -> str:
    """« local » si Whisper est là (et non écarté par réglage), sinon « google »."""
    voulu = (getattr(settings, "transcription_moteur", "local") or "local").strip().lower()
    if voulu != "google" and moteur_local_disponible():
        return "local"
    return "google"


async def transcrire(octets: bytes, mime: str = "audio/webm", cle_cache: str = "") -> str:
    """Le texte dit dans l'enregistrement. Lève `TranscriptionIndisponible`, jamais la clé.

    `cle_cache` : qui dicte (l'identifiant de la personne) — c'est ce qui permet
    au moteur local de ne transcrire que la partie neuve d'un enregistrement
    qui grandit. Vide = pas de cache, tout est retranscrit.
    """
    if not octets:
        return ""
    if len(octets) > MAX_OCTETS:
        raise TranscriptionIndisponible(
            "L'enregistrement est trop long pour une dictée (plus de dix minutes). "
            "Pour une réunion, collez sa transcription écrite.")
    if moteur_choisi() == "local":
        try:
            # Le CPU travaille hors de la boucle : un tour de chat ne doit pas
            # attendre qu'une dictée soit transcrite.
            return _nettoyer(await asyncio.to_thread(_transcrire_local, octets, cle_cache))
        except TranscriptionIndisponible:
            raise
        except Exception as e:  # noqa: BLE001
            # Modèle non téléchargeable, audio illisible : on le dit, et on
            # tente le secours — sans clé Google, c'est lui qui expliquera.
            logger.warning("Whisper local en échec (%s) : secours Google", e)
    return await _transcrire_google(octets, mime)
