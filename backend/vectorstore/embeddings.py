"""
Génération d'embeddings — multi-fournisseurs (RAG).

Fournisseurs supportés (settings.embedding_provider) :
  - gemini : Google `gemini-embedding-001` via REST, `outputDimensionality=1536`
             (tier gratuit, aucune migration de schéma). RECOMMANDÉ sur petit VPS.
  - openai : `text-embedding-3-small` (1536).
  - ollama : modèle local (ex. bge-m3, 1024 dims → nécessite une migration du schéma).

DÉGRADATION PROPRE : si la clé/le service manque ou échoue, les fonctions
renvoient `None` (ou une liste de `None`) et loggent un warning — elles ne lèvent
JAMAIS. Sans embeddings, la recherche RAG retombe sur pg_trgm.

On ne logge jamais le contenu vectorisé, uniquement des métadonnées.
"""
import asyncio
import datetime
import logging
import time
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger("duret.embeddings")

_warned_no_key = False


def _warn_once(msg: str) -> None:
    global _warned_no_key
    if not _warned_no_key:
        logger.warning(msg)
        _warned_no_key = True


# ── Garde-fou quota Gemini : cadence ADAPTATIVE, plafond/jour, reprise après 429 ──
#
# CE QUI SE PASSAIT (31/08, journaux du VPS Symbiose) : « Gemini 429 — pause
# 1800s » toutes les trente minutes depuis 09:17, et 3 390 morceaux sur 6 401
# SANS vecteur — dont 1 011 des 1 029 du Drive, toutes les factures, tous les
# prospects, la moitié des mails. La recherche documentaire ne les voyait que
# par pg_trgm. Une requête d'UN texte passait pourtant (sondé depuis le
# conteneur) : la clé n'était pas morte, c'était le DÉBIT. Le worker envoyait
# 32 textes par requête toutes les 0,8 s, prenait un 429 dès la première
# rafale, dormait trente minutes, recommençait À L'IDENTIQUE. Deux requêtes
# par heure : la file ne se vidait jamais — et le détail du 429 (retryDelay,
# quotaId) n'était pas lu, donc personne ne pouvait dire pourquoi.
#
# MAINTENANT : le 429 est LU (Google dit combien attendre et quel quota mord,
# et ça se retrouve dans le journal) ; la pause est celle qu'il demande, sinon
# courte et doublée à chaque récidive — jamais trente minutes d'emblée ; et la
# cadence de croisière RALENTIT à chaque 429 puis se détend au fil des succès.
# Le module s'accorde ainsi seul au palier réel de la clé (gratuit ou facturé),
# sans réglage à deviner.
class _GeminiThrottle:
    PAUSE_INITIALE_S = 30.0       # premier 429 sans délai annoncé
    CADENCE_MAX_S = 20.0          # on ne ralentit jamais au-delà (3 requêtes/min)

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._last = 0.0
        self._day: Optional[datetime.date] = None
        self._count = 0
        self._cooldown_until = 0.0
        self._cadence: Optional[float] = None   # None = la cadence du réglage
        self._recidives = 0                     # 429 consécutifs, effacés par un succès
        self._dernier_429 = ""                  # ce que Google a dit la dernière fois

    @property
    def cadence(self) -> float:
        return self._cadence if self._cadence is not None else float(settings.embedding_min_interval_s)

    async def gate(self) -> tuple[bool, str]:
        async with self._lock:
            today = datetime.datetime.utcnow().date()
            if today != self._day:
                self._day, self._count = today, 0
            now = time.monotonic()
            if now < self._cooldown_until:
                return False, "cooldown quota (429)"
            if self._count >= settings.embedding_daily_request_cap:
                return False, "plafond quotidien atteint"
            wait = self.cadence - (now - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()
            self._count += 1
            return True, ""

    @staticmethod
    def lire_429(corps: str) -> tuple[Optional[float], str]:
        """Le délai demandé par Google (`retryDelay`, ex. « 18s ») et le quota
        touché (`quotaId`), lus dans le corps du 429. Rien n'est supposé : un
        corps illisible rend (None, « détail illisible »)."""
        import json
        import re
        try:
            data = json.loads(corps or "")
        except ValueError:
            return None, "détail illisible"
        erreur = data.get("error") if isinstance(data, dict) else None
        if not isinstance(erreur, dict):
            return None, "détail illisible"
        delai: Optional[float] = None
        quotas: list[str] = []
        for d in erreur.get("details") or []:
            if not isinstance(d, dict):
                continue
            rd = d.get("retryDelay")
            if isinstance(rd, str):
                m = re.match(r"(\d+(?:\.\d+)?)s", rd)
                if m:
                    delai = float(m.group(1))
            for v in d.get("violations") or []:
                if isinstance(v, dict) and v.get("quotaId"):
                    quotas.append(str(v["quotaId"]))
        message = str(erreur.get("message") or "")[:120]
        return delai, (", ".join(quotas) or message or "sans détail")

    async def hit_quota(self, corps: str = "") -> tuple[float, str]:
        """Un 429 vient d'arriver : pause (celle de Google, sinon progressive)
        et cadence ralentie. Rend (pause en secondes, diagnostic)."""
        delai, diag = self.lire_429(corps)
        plafond = float(settings.embedding_cooldown_s)
        async with self._lock:
            self._recidives += 1
            if delai is not None:
                pause = min(delai + 2.0, plafond)
            else:
                pause = min(self.PAUSE_INITIALE_S * (2 ** (self._recidives - 1)), plafond)
            self._cooldown_until = time.monotonic() + pause
            self._cadence = min(self.cadence * 2.0, self.CADENCE_MAX_S)
            self._dernier_429 = diag
            return pause, diag

    async def succes(self) -> None:
        """Une requête est passée : les récidives s'effacent et la cadence se
        détend, sans jamais descendre sous celle du réglage."""
        async with self._lock:
            self._recidives = 0
            if self._cadence is not None:
                base = float(settings.embedding_min_interval_s)
                self._cadence = max(base, self._cadence * 0.9)
                if self._cadence <= base:
                    self._cadence = None

    def stats(self) -> dict:
        return {"jour": str(self._day), "requetes_jour": self._count,
                "plafond_jour": settings.embedding_daily_request_cap,
                "cadence_s": round(self.cadence, 2), "recidives_429": self._recidives,
                "dernier_429": self._dernier_429}


_gemini_throttle = _GeminiThrottle()


def embed_stats() -> dict:
    """Stats du garde-fou quota Gemini (supervision)."""
    return _gemini_throttle.stats()


# ── OpenAI ────────────────────────────────────────────────────────────────
_openai_client = None


def _openai():
    global _openai_client
    if _openai_client is not None:
        return _openai_client
    if not settings.openai_api_key:
        return None
    try:
        from openai import AsyncOpenAI
        _openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
        return _openai_client
    except Exception as e:
        logger.warning("Client OpenAI indisponible (%s)", type(e).__name__)
        return None


_CLIENT = None


def _client():
    """Client HTTP PARTAGÉ (31/08) : un client neuf par appel payait la poignée
    de main TLS à chaque embedding — sur le chemin critique de chaque tour
    (rappel de conversation, recherche documentaire)."""
    global _CLIENT
    if _CLIENT is None or _CLIENT.is_closed:
        _CLIENT = httpx.AsyncClient(timeout=60)
    return _CLIENT


async def _embed_openai(texts: list[str], modele: str = "") -> list[Optional[list[float]]]:
    client = _openai()
    if client is None:
        _warn_once("OPENAI_API_KEY absente : embeddings openai désactivés (dégradation pg_trgm).")
        return [None] * len(texts)
    try:
        resp = await client.embeddings.create(
            model=modele or settings.embedding_model, input=texts)
        return [d.embedding for d in resp.data]
    except Exception as e:
        logger.warning("Échec embeddings OpenAI (%s) — mode dégradé", type(e).__name__)
        return [None] * len(texts)


# ── Gemini (Google AI Studio, REST) ───────────────────────────────────────
async def _embed_gemini(texts: list[str], modele: str = "") -> list[Optional[list[float]]]:
    if not settings.google_api_key:
        _warn_once("GOOGLE_API_KEY absente : embeddings gemini désactivés (dégradation pg_trgm).")
        return [None] * len(texts)

    ok, reason = await _gemini_throttle.gate()
    if not ok:
        _warn_once(f"Embeddings Gemini en pause ({reason}) — chunks conservés, reprise auto.")
        return [None] * len(texts)

    model = modele or settings.gemini_embedding_model
    # La dimension que la colonne attend ; sans base lisible, celle de la
    # configuration — un embedding vaut mieux qu'aucun.
    cible = settings.embedding_dimensions
    try:
        from vectorstore.revectorisation import dimension_attendue
        cible = await dimension_attendue()
    except Exception:  # noqa: BLE001 — la configuration reste le repli
        pass
    max_chars = settings.embedding_max_chars
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:batchEmbedContents?key={settings.google_api_key}")
    body = {
        "requests": [
            {
                "model": f"models/{model}",
                "content": {"parts": [{"text": t[:max_chars]}]},
                # LA CIBLE SUIT LA BASE, PAS LA CONFIGURATION (02/09).
                # Gemini est le seul fournisseur qui CHOISIT sa dimension
                # (les autres la subissent) : après une re-vectorisation
                # vers 768, il aurait continué de réclamer les 1536 de
                # `config.py` et chacun de ses vecteurs aurait été refusé
                # par le garde-fou, sans que rien ne relie les deux.
                "outputDimensionality": cible,
            }
            for t in texts
        ]
    }
    try:
        r = await _client().post(url, json=body)
        if r.status_code == 429:
            pause, diag = await _gemini_throttle.hit_quota(r.text)
            logger.warning("Gemini 429 (%s) — pause %.0f s, cadence %.1f s, backlog conservé",
                           diag, pause, _gemini_throttle.cadence)
            return [None] * len(texts)
        r.raise_for_status()
        data = r.json()
        await _gemini_throttle.succes()
        embeddings = data.get("embeddings", [])
        out: list[Optional[list[float]]] = []
        for e in embeddings:
            vals = e.get("values")
            out.append(vals if vals else None)
        # aligne la longueur en cas de réponse partielle
        while len(out) < len(texts):
            out.append(None)
        return out
    except Exception as e:
        logger.warning("Échec embeddings Gemini (%s) — mode dégradé", type(e).__name__)
        return [None] * len(texts)


# ── Ollama (local) ────────────────────────────────────────────────────────
async def _embed_ollama(texts: list[str], modele: str = "") -> list[Optional[list[float]]]:
    out: list[Optional[list[float]]] = []
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            for t in texts:
                r = await client.post(
                    f"{settings.ollama_base_url}/api/embeddings",
                    json={"model": modele or settings.ollama_embedding_model,
                          "prompt": t},
                )
                r.raise_for_status()
                out.append(r.json().get("embedding") or None)
        return out
    except Exception as e:
        logger.warning("Échec embeddings Ollama (%s) — mode dégradé", type(e).__name__)
        return out + [None] * (len(texts) - len(out))


# ── Ollama Cloud (abonnement, API compatible OpenAI) ──────────────────────
#
# CE FOURNISSEUR MANQUAIT (02/09). Le réglage « modèle des embeddings »
# proposait les modèles d'Ollama Cloud, mais `_PROVIDERS` n'en connaissait
# pas le nom : le choix retombait sur « fournisseur inconnu », et plus rien
# n'était vectorisé. Le fournisseur `ollama` existant, lui, vise
# `ollama_base_url` — l'instance LOCALE, absente des serveurs. Les deux
# sont donc bien deux fournisseurs distincts, comme pour le texte (§4.5).
#
# La clé passe par `llm.cles`, jamais par la configuration seule : une clé
# saisie dans Paramètres prime sur le `.env`, et le cache est rafraîchi au
# démarrage (piège du §4.6).
async def _embed_ollama_cloud(texts: list[str], modele: str = "") -> list[Optional[list[float]]]:
    from llm.cles import valeur as _cle_valeur
    cle = _cle_valeur("ollama_cloud_api_key") or ""
    if not cle:
        _warn_once("Clé Ollama Cloud absente : embeddings désactivés "
                   "(la recherche reste servie par la voie lexicale).")
        return [None] * len(texts)
    nom = modele or settings.ollama_cloud_embedding_model
    base = (settings.ollama_cloud_base_url or "").rstrip("/")
    max_chars = settings.embedding_max_chars
    try:
        r = await _client().post(
            f"{base}/embeddings",
            headers={"Authorization": f"Bearer {cle}"},
            json={"model": nom, "input": [t[:max_chars] for t in texts]})
        r.raise_for_status()
        # L'ordre de `data` suit celui de l'entrée, mais le contrat OpenAI
        # porte un `index` : on s'y fie plutôt qu'à la position, sans quoi
        # une réponse réordonnée collerait les vecteurs aux mauvais textes.
        out: list[Optional[list[float]]] = [None] * len(texts)
        for item in (r.json().get("data") or []):
            i = item.get("index")
            if isinstance(i, int) and 0 <= i < len(texts):
                out[i] = item.get("embedding") or None
        return out
    except Exception as e:  # noqa: BLE001 — jamais d'exception vers l'appelant
        logger.warning("Échec embeddings Ollama Cloud (%s) — mode dégradé",
                       type(e).__name__)
        return [None] * len(texts)


_PROVIDERS = {"gemini": _embed_gemini, "openai": _embed_openai,
              "ollama": _embed_ollama, "ollama_cloud": _embed_ollama_cloud,
              # « google » est le nom du fournisseur dans la cascade de texte et
              # dans le catalogue de l'écran ; « gemini » celui du moteur
              # d'embedding. Le même service sous deux noms : sans cet alias, le
              # choix le plus naturel de l'écran coupait la vectorisation.
              "google": _embed_gemini}


# ── API publique ──────────────────────────────────────────────────────────
async def embed_texts(texts: list[str],
                      modele_force: str = "") -> list[Optional[list[float]]]:
    """
    Vectorise un lot de textes. Ordre de sortie = ordre d'entrée. Textes vides →
    None sans appel réseau. Ne lève jamais ; renvoie [None,…] si indisponible.
    """
    if not texts:
        return []
    cleaned = [(t or "").strip() for t in texts]
    to_embed = [(i, t) for i, t in enumerate(cleaned) if t]
    if not to_embed:
        return [None] * len(texts)

    # LE FOURNISSEUR D'EMBEDDINGS SE CHOISIT À L'ÉCRAN (01/09), comme les
    # modèles de texte. Il vivait dans le `.env`, donc derrière une recréation
    # de conteneur.
    #
    # ET UN FOURNISSEUR INCONNU SE DIT. Cette ligne retombait SILENCIEUSEMENT
    # sur Gemini : un nom mal écrit dans la configuration donnait un système
    # qui semble obéir et n'obéit pas — le pire des deux mondes, puisque rien
    # ne le signale.
    # UN MODÈLE PEUT ÊTRE ESSAYÉ SANS ÊTRE CHOISI (02/09). Sans ce paramètre,
    # la seule façon de connaître la dimension d'un modèle était de le POSER en
    # réglage — c'est-à-dire de basculer tout le système dessus pour savoir
    # s'il convenait. On veut l'inverse : mesurer, montrer, puis choisir.
    nom_fournisseur = (settings.embedding_provider or "gemini").strip().lower()
    modele_choisi = ""
    if modele_force and ":" in modele_force:
        f, _, m = modele_force.partition(":")
        if f.strip() and m.strip():
            nom_fournisseur, modele_choisi = f.strip().lower(), m.strip()
    try:
        from llm.reglages import texte as _reglage_texte
        brut = "" if modele_force else _reglage_texte("modele_embedding")
        if brut:
            f, _, m = brut.partition(":")
            if f.strip() and m.strip():
                nom_fournisseur, modele_choisi = f.strip().lower(), m.strip()
    except Exception:  # noqa: BLE001 — un réglage illisible garde la configuration
        pass
    provider = _PROVIDERS.get(nom_fournisseur)
    if provider is None:
        _warn_once(
            f"Fournisseur d'embeddings inconnu : « {nom_fournisseur} ». "
            f"Attendu : {', '.join(sorted(_PROVIDERS))}. Rien n'est vectorisé "
            "tant que ce nom n'est pas corrigé.")
        return [None] * len(texts)

    # Dédup : chaque texte identique n'est vectorisé qu'une fois (économie de quota).
    unique_texts: list[str] = []
    seen: dict[str, int] = {}
    for _, t in to_embed:
        if t not in seen:
            seen[t] = len(unique_texts)
            unique_texts.append(t)
    # LE MODÈLE CHOISI ÉTAIT CALCULÉ PUIS JETÉ (corrigé le 02/09) : seul le
    # FOURNISSEUR était retenu, et chaque fonction reprenait le modèle par
    # défaut de la configuration. Choisir « ollama_cloud:embeddinggemma » à
    # l'écran vectorisait donc avec un autre modèle que celui affiché — et
    # rien ne le disait.
    unique_vectors = await provider(unique_texts, modele_choisi)

    results: list[Optional[list[float]]] = [None] * len(texts)
    for orig_idx, t in to_embed:
        results[orig_idx] = unique_vectors[seen[t]]
    return results


async def embed_query(text: str) -> Optional[list[float]]:
    """Embedding d'une requête unique (None si indisponible / texte vide)."""
    text = (text or "").strip()
    if not text:
        return None
    return (await embed_texts([text]))[0]
