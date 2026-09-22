"""
LA TRANSCRIPTION DE LA VOIX — dans l'application, et SANS JETON D'IA si possible.

LA DEMANDE (03/09, Noa) : « le micro peut fonctionner, il faut que le
transcripteur soit intégré à l'app » — puis : « il n'y a pas une solution pour
retranscrire sans token IA ? ». Si.

⚠️ DEPUIS LE 15/09, GROQ PASSE DEVANT (Noa : « ça transcrit mal dès qu'on ne
parle pas lentement comme un robot »). Deux causes : Whisper `base` est trop
petit pour le français parlé vite, et le découpage toutes les deux secondes
coupait les mots — la parole rapide n'a pas de silence où couper. Groq sert
Whisper large-v3-turbo (le plus gros Whisper) avec une offre GRATUITE, sans
modèle sur le serveur (règle du 15/09). Ordre : GROQ (dès que la clé Groq est
posée dans Paramètres) → Whisper local → Google. Voir la section GROQ plus bas.

AVANT LE 15/09, DEUX MOTEURS, DANS CET ORDRE :

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


# ── GROQ : Whisper large-v3-turbo, offre gratuite (15/09) ────────────────
# DEUX PASSES. Pendant la dictée, le texte s'écrit par fenêtres d'une vingtaine
# de secondes (au plus un appel toutes les INTERVALLE_GROQ_S par dictée : l'offre
# gratuite compte les requêtes par minute et les secondes d'audio par heure, et
# chaque requête est facturée dix secondes au minimum). À l'ARRÊT, tout
# l'enregistrement est retranscrit d'un bloc et remplace le brouillon : le
# texte final n'a plus aucune coupure, c'est lui que la personne envoie.
GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MODELE = "whisper-large-v3-turbo"
MAX_OCTETS_GROQ = 25 * 1024 * 1024      # plafond d'un fichier sur l'offre gratuite
INTERVALLE_GROQ_S = 5.0                 # un appel au plus toutes les 5 s pendant la dictée
FENETRE_GROQ_S = 20.0                   # au-delà, la fenêtre est figée et la suivante commence
RECOUVREMENT_GROQ_S = 1.5
# {cle: {"stable_s", "stable", "provisoire", "prochain", "quand"}}
_GROQ: dict[str, dict] = {}


def _cle_groq() -> str:
    from llm.cles import valeur
    return (valeur("groq_api_key") or "").strip()


def _amorce(precedent: str = "") -> str:
    """Ce que Whisper lit AVANT l'audio : le nom de la maison (il l'écrit alors
    juste) et la fin du texte déjà dicté (il garde le fil et la ponctuation).
    Whisper n'en lit que ~220 jetons : on reste court."""
    try:
        from emails.marque import MARQUE
        nom = str(MARQUE.get("nom") or "")
    except Exception:  # noqa: BLE001
        nom = ""
    debut = f"Dictée pour {nom}." if nom else "Dictée en français."
    return (debut + " " + (precedent or "")[-300:]).strip()


def _pcm16(octets: bytes) -> tuple[bytes, float]:
    """L'audio en PCM 16 bits, 16 kHz mono, et sa durée — pour découper la fin
    d'une dictée qui grandit. Un enregistrement en cours d'écriture peut finir
    au milieu d'un paquet : on garde ce qui a été décodé."""
    import av
    pcm = bytearray()
    try:
        conteneur = av.open(io.BytesIO(octets))
        reechantillon = av.AudioResampler(format="s16", layout="mono", rate=HZ)
        try:
            for trame in conteneur.decode(audio=0):
                trame.pts = None
                for t in reechantillon.resample(trame):
                    pcm.extend(t.to_ndarray().tobytes())
            for t in reechantillon.resample(None):
                pcm.extend(t.to_ndarray().tobytes())
        except Exception:  # noqa: BLE001 — la fin d'un flux en cours n'est pas une panne
            pass
    except Exception as e:  # noqa: BLE001
        raise TranscriptionIndisponible(f"L'enregistrement n'a pas pu être lu ({type(e).__name__}).")
    return bytes(pcm), len(pcm) / (2 * HZ)


def _wav(pcm: bytes) -> bytes:
    import wave
    tampon = io.BytesIO()
    with wave.open(tampon, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(HZ)
        w.writeframes(pcm)
    return tampon.getvalue()


class _Limite(TranscriptionIndisponible):
    """429 : l'offre gratuite est à son plafond pour un moment."""
    def __init__(self, message: str, attente_s: float):
        super().__init__(message)
        self.attente_s = attente_s


async def _appel_groq(fichier: bytes, nom: str, mime: str, amorce: str) -> str:
    cle = _cle_groq()
    if not cle:
        raise TranscriptionIndisponible("Aucune clé Groq : Paramètres > Clés API.")
    if len(fichier) > MAX_OCTETS_GROQ:
        raise TranscriptionIndisponible("L'enregistrement dépasse 25 Mo, trop long pour une dictée.")
    donnees = {"model": GROQ_MODELE, "language": "fr", "temperature": "0",
               "response_format": "json"}
    if amorce:
        donnees["prompt"] = amorce
    async with httpx.AsyncClient(timeout=DELAI_S) as client:
        rep = None
        for pause_s in (0, 2, 5):
            if pause_s:
                await asyncio.sleep(pause_s)
            try:
                rep = await client.post(GROQ_URL, headers={"Authorization": f"Bearer {cle}"},
                                        data=donnees, files={"file": (nom, fichier, mime)})
            except httpx.HTTPError as e:
                logger.info("Groq injoignable (%s)", type(e).__name__)
                rep = None
                continue
            if rep.status_code in (500, 502, 503, 504):
                rep = None
                continue
            break
    if rep is None:
        raise TranscriptionIndisponible("Le service de transcription Groq ne répond pas.")
    if rep.status_code == 429:
        try:
            attente = float((getattr(rep, "headers", None) or {}).get("retry-after") or 20)
        except (TypeError, ValueError):
            attente = 20.0
        raise _Limite("Le quota gratuit de transcription est atteint pour quelques instants.", attente)
    if rep.status_code in (401, 403):
        raise TranscriptionIndisponible("La clé Groq est refusée : vérifiez-la dans Paramètres > Clés API.")
    if rep.status_code >= 400:
        logger.warning("Transcription Groq refusée : HTTP %s — %s", rep.status_code, rep.text[:200])
        raise TranscriptionIndisponible(f"Transcription refusée par Groq (HTTP {rep.status_code}).")
    try:
        return _nettoyer(str(rep.json().get("text") or ""))
    except ValueError:
        raise TranscriptionIndisponible("Réponse de Groq illisible.")


def _extension(mime: str) -> str:
    base = _mime_propre(mime)
    return {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/mpeg": "mp3",
            "audio/wav": "wav", "audio/x-wav": "wav", "audio/flac": "flac"}.get(base, "webm")


async def _groq_complet(octets: bytes, mime: str) -> str:
    """Tout l'enregistrement d'un bloc, tel que le navigateur l'a produit."""
    return await _appel_groq(octets, f"dictee.{_extension(mime)}", _mime_propre(mime), _amorce())


async def _groq_provisoire(cle: str, octets: bytes, mime: str) -> str:
    """Le brouillon pendant la dictée : seule la fenêtre en cours est relue."""
    maintenant = time.monotonic()
    for k in [k for k, v in _GROQ.items() if maintenant - v["quand"] > CACHE_TTL_S]:
        _GROQ.pop(k, None)
    e = _GROQ.setdefault(cle, {"stable_s": 0.0, "stable": "", "provisoire": "",
                               "prochain": 0.0, "quand": maintenant})
    e["quand"] = maintenant
    deja = _recoller(e["stable"], e["provisoire"]) if e["provisoire"] else e["stable"]
    if maintenant < e["prochain"]:
        return deja
    e["prochain"] = maintenant + INTERVALLE_GROQ_S
    pcm, duree = await asyncio.to_thread(_pcm16, octets)
    depuis = max(0.0, e["stable_s"] - RECOUVREMENT_GROQ_S) if e["stable_s"] else 0.0
    morceau = pcm[int(depuis * HZ) * 2:]
    if len(morceau) < HZ * 2:                     # moins d'une seconde : rien à relire
        return deja
    try:
        texte = await _appel_groq(_wav(morceau), "fenetre.wav", "audio/wav", _amorce(e["stable"]))
    except _Limite as limite:
        e["prochain"] = time.monotonic() + limite.attente_s
        return deja
    if duree - e["stable_s"] >= FENETRE_GROQ_S:
        e["stable"], e["stable_s"], e["provisoire"] = _recoller(e["stable"], texte), duree, ""
        return e["stable"]
    e["provisoire"] = texte
    return _recoller(e["stable"], texte) if e["stable"] else texte


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
    # La clé Groq peut vivre en base : on relit les clés avant de décider, sinon
    # le modèle local se chargerait pour rien (500 Mo de mémoire).
    try:
        from llm.cles import rafraichir
        await rafraichir(force=True)
    except Exception:  # noqa: BLE001
        pass
    if moteur_choisi() != "local":
        return
    try:
        await asyncio.to_thread(_modele_local)
    except Exception as e:  # noqa: BLE001
        logger.warning("Whisper local non préchargé (%s) : il se chargera à la première dictée", e)


# ── LE FLUX : le navigateur n'envoie que le NOUVEAU son ─────────────────
# « Le voir s'écrire en direct » (04/09, Noa). Envoyer tout l'enregistrement
# toutes les six secondes ne permettait ni d'aller plus vite (le poids double
# à chaque envoi) ni d'écrire au fil de la parole. Désormais le navigateur
# envoie toutes les deux secondes les morceaux qu'il vient d'enregistrer, le
# serveur les AJOUTE au tampon de la dictée et ne transcrit que la fin (le
# cache incrémental fait le reste). Le premier morceau porte l'en-tête webm :
# le tampon entier reste décodable. Un tampon par (personne, dictée), oublié
# à la fin ou au bout de dix minutes.
_TAMPONS: dict[str, dict] = {}

# UNE DICTÉE A UNE FIN, MÊME SI LE NAVIGATEUR L'OUBLIE (22/09, Duret). Un onglet
# a gardé le micro ouvert plus de douze minutes, sans que personne le voie, et
# chaque envoi faisait transcrire le son de la pièce. Le navigateur s'arrête à
# dix minutes ; le serveur, une minute plus tard, n'accepte plus rien de cette
# dictée (et ne rappelle plus aucun moteur) — c'est ce qui arrête aussi les
# onglets restés ouverts sur une version plus ancienne de l'écran.
DUREE_MAX_DICTEE_S = 11 * 60


class MorceauManquant(Exception):
    """Le serveur n'a pas reçu tout le son d'avant : le navigateur renvoie depuis `recus`."""

    def __init__(self, recus: int):
        super().__init__(f"Il manque du son à partir de l'octet {recus}.")
        self.recus = recus


class DicteeTerminee(Exception):
    """La dictée a dépassé sa borne : plus rien n'est transcrit pour elle."""


def _tampon(cle: str) -> dict:
    maintenant = time.monotonic()
    for k in [k for k, v in _TAMPONS.items() if maintenant - v["quand"] > CACHE_TTL_S]:
        _TAMPONS.pop(k, None)
    return _TAMPONS.setdefault(cle, {"octets": bytearray(), "quand": maintenant, "cree": maintenant})


def _ajouter(cle: str, t: dict, morceau: bytes, debut: int | None) -> None:
    """Ajoute le son neuf au tampon, sans trou ni doublon.

    LE PREMIER MORCEAU PORTE L'EN-TÊTE DU FICHIER (22/09, Duret). Un envoi perdu
    en route (deux abandonnés à 15 h 29 le 22/09) laissait au serveur une suite
    de son sans son début : Groq, Whisper et Google l'ont tous refusée, et le
    navigateur, qui comptait le morceau comme parti, ne le renvoyait jamais.
    Désormais chaque envoi dit où il commence (`debut`, en octets depuis le
    début de la dictée) : ce que le serveur a déjà est ignoré, ce qui lui manque
    est réclamé (`MorceauManquant`) — le navigateur renvoie depuis là. Sans
    `debut` (un écran d'avant ce correctif), on ajoute comme avant.
    """
    if t.get("terminee"):
        # Tant que l'onglet envoie, la marque reste : oubliée, elle laisserait
        # repartir une « nouvelle » dictée sur la suite du même son.
        t["quand"] = time.monotonic()
        raise DicteeTerminee(t["terminee"])
    recus = len(t["octets"])
    if debut is not None:
        if debut > recus:
            raise MorceauManquant(recus)
        morceau = morceau[recus - debut:]
    if morceau:
        t["octets"].extend(morceau)
    t["quand"] = time.monotonic()
    if len(t["octets"]) > MAX_OCTETS or t["quand"] - t.get("cree", t["quand"]) > DUREE_MAX_DICTEE_S:
        t["terminee"] = ("Cette dictée a dépassé dix minutes : elle est arrêtée. "
                         "Réappuyez sur le micro pour en commencer une autre.")
        # Le son est oublié tout de suite ; la marque reste, pour refuser la suite.
        t["octets"] = bytearray()
        _CACHE.pop(cle, None)
        _GROQ.pop(cle, None)
        logger.warning("Dictée arrêtée par le serveur : plus de dix minutes ou plus de 12 Mo")
        raise DicteeTerminee(t["terminee"])


async def transcrire_flux(cle: str, morceau: bytes, mime: str = "audio/webm",
                          definitif: bool = False, debut: int | None = None) -> str:
    """Ajoute un morceau au tampon de cette dictée et rend le texte ENTIER.

    `definitif` : le dernier morceau — le tampon et le cache sont oubliés après.
    `debut` : où ce morceau commence dans la dictée, en octets (voir `_ajouter`).
    Lève `MorceauManquant` (le tampon est GARDÉ, même au dernier morceau : le
    navigateur renvoie ce qui manque) ou `DicteeTerminee`.
    """
    t = _tampon(cle)
    _ajouter(cle, t, morceau, debut)
    octets = bytes(t["octets"])
    try:
        if moteur_choisi() == "groq":
            if not definitif:
                try:
                    return await _groq_provisoire(cle, octets, mime)
                except TranscriptionIndisponible as e:
                    logger.info("Brouillon Groq indisponible (%s)", e)
                    return (_GROQ.get(cle) or {}).get("stable", "")
            brouillon = _GROQ.get(cle) or {}
            try:
                return await _groq_complet(octets, mime)
            except _Limite as limite:
                # La passe finale compte : on attend un peu si le quota le permet.
                if limite.attente_s <= 8:
                    await asyncio.sleep(limite.attente_s)
                    try:
                        return await _groq_complet(octets, mime)
                    except TranscriptionIndisponible:
                        pass
            except TranscriptionIndisponible as e:
                logger.warning("Passe finale Groq en échec (%s)", e)
            texte = (_recoller(brouillon.get("stable", ""), brouillon.get("provisoire", ""))
                     if brouillon.get("provisoire") else brouillon.get("stable", ""))
            if texte:
                return texte
            return await transcrire(octets, mime, cle_cache="", sans_groq=True)
        return await transcrire(octets, mime, cle_cache=cle)
    finally:
        if definitif:
            _TAMPONS.pop(cle, None)
            _CACHE.pop(cle, None)
            _GROQ.pop(cle, None)


# ── L'ENTRÉE ─────────────────────────────────────────────────────────────
def moteur_choisi() -> str:
    """« groq » dès que sa clé est posée, sinon « local » si Whisper est là,
    sinon « google ». `TRANSCRIPTION_MOTEUR` force un moteur (groq, local, google) ;
    « auto » (défaut) suit cet ordre."""
    voulu = (getattr(settings, "transcription_moteur", "auto") or "auto").strip().lower()
    if voulu == "google":
        return "google"
    if voulu in ("auto", "groq") and _cle_groq():
        return "groq"
    if voulu in ("auto", "local", "groq") and moteur_local_disponible():
        return "local"
    return "google"


async def transcrire(octets: bytes, mime: str = "audio/webm", cle_cache: str = "",
                     sans_groq: bool = False) -> str:
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
    moteur = moteur_choisi()
    if moteur == "groq" and not sans_groq:
        try:
            return await _groq_complet(octets, mime)
        except TranscriptionIndisponible as e:
            logger.warning("Groq en échec (%s) : moteur suivant", e)
        moteur = "local" if moteur_local_disponible() else "google"
    if moteur == "groq":
        moteur = "local" if moteur_local_disponible() else "google"
    if moteur == "local":
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
