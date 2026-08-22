"""
Routeur LLM — cascade multi-fournisseurs avec retry, backoff et fallback.

Trois paliers, trois compromis assumés entre coût et intelligence :
  LIGHT    — gros volume, faible enjeu (orientation, classification, résumé court)
             DeepSeek Flash → Groq 8B → OpenRouter free → Ollama
  STANDARD — rédaction courante : la LATENCE d'abord
             DeepSeek Flash → passerelle → Groq 70B → LongCat → free → Ollama
  COMPLEX  — analyse, synthèse, jugement : le raisonnement fait la qualité
             DeepSeek V4 Pro → passerelle → Anthropic → Groq 70B → LongCat → free

Le palier n'est pas choisi au hasard : le nœud d'orientation tranche, en un
appel LIGHT, si la demande relève d'une rédaction courante ou d'un vrai travail
d'analyse. Le modèle cher ne sert donc qu'aux tours qui le justifient — c'est ce
qui rend son coût acceptable.

Chaque modèle est joignable EN DIRECT ou via OpenRouter. La passerelle suit
immédiatement l'API directe dans la cascade : si l'une tombe, l'autre prend le
relais sans changer de modèle, donc sans changer de qualité.

Fournisseurs : openrouter (OpenAI-compatible : LongCat, DeepSeek, free), groq, anthropic, ollama.
Un candidat dont la clé fournisseur est absente est ignoré silencieusement, ce qui rend
la configuration progressive : avec seulement GROQ_API_KEY, tout tourne sur Groq/Ollama ;
dès qu'OPENROUTER_API_KEY est fournie, LongCat/DeepSeek/free s'activent en tête de cascade.
"""
import asyncio
import time
import logging
from enum import Enum
from typing import Any, Optional

from config import settings
from optim.tokens import tier_max_tokens

logger = logging.getLogger("duret.llm")


class LLMTier(Enum):
    LIGHT = "light"        # actions simples / backend — gratuit
    STANDARD = "standard"  # défaut — LongCat/DeepSeek puis gratuit
    COMPLEX = "complex"    # dur / vision


# ── Disponibilité & construction des fournisseurs ────────────────────────

# Fournisseurs OpenAI-compatibles (base_url + clé configurables) : direct ou via passerelle.
_OPENAI_COMPAT = ("openrouter", "deepseek", "longcat", "google")


def _cle(provider: str) -> Optional[str]:
    """Clé effective d'un fournisseur : Paramètres d'abord, `.env` ensuite.

    Passe par `llm.cles` plutôt que par `settings` directement, pour qu'une clé
    saisie dans l'interface prenne effet sans redéploiement.
    """
    from llm.cles import valeur
    return valeur(f"{provider}_api_key")


def _provider_available(provider: str) -> bool:
    if provider in _OPENAI_COMPAT or provider == "groq":
        return bool(_cle(provider))
    if provider == "anthropic":
        c = _cle("anthropic")
        return bool(c) and c != "placeholder"
    if provider == "ollama":
        return True
    return False


def tier_timeout(tier: str) -> int:
    """Secondes accordées à UN candidat avant de passer au suivant."""
    return {
        "light": settings.llm_timeout_light,
        "standard": settings.llm_timeout_standard,
        "complex": settings.llm_timeout_complex,
    }.get(tier, settings.llm_timeout_standard)


def _build_model(provider: str, model: Optional[str], max_tokens: int = 4096,
                 delai: int = 75):
    """Construit l'instance LangChain (sans résilience) pour un couple (fournisseur, modèle).

    DEUX RÉGLAGES QUI MANQUAIENT, ET QUI COÛTAIENT DES MINUTES.

    `timeout` : sans lui, le SDK OpenAI attend 600 SECONDES. Un fournisseur
    qui rame ne rendait donc jamais la main, et la cascade — écrite pour
    survivre exactement à ça — restait spectatrice.

    `max_retries=0` : le SDK retente DEUX FOIS de lui-même, en plus de nos
    propres tentatives. Les deux mécanismes se multipliaient : trois essais à
    nous, trois à lui, chacun plafonné à dix minutes. La résilience se décide
    ICI, à un seul étage, sinon personne ne sait plus combien de temps un appel
    peut durer.
    """
    if provider in _OPENAI_COMPAT:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            api_key=_cle(provider),
            base_url=getattr(settings, f"{provider}_base_url"),
            temperature=0.1,
            max_tokens=max_tokens,
            timeout=delai,
            max_retries=0,
            default_headers={"HTTP-Referer": "https://pluton.local", "X-Title": "Symbiose Paysage"},
        )
    if provider == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(model=model, api_key=_cle("groq"), temperature=0.1,
                        max_tokens=max_tokens, timeout=delai, max_retries=0)
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model, api_key=_cle("anthropic"), temperature=0.1,
                             max_tokens=max_tokens, timeout=delai, max_retries=0)
    if provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(base_url=settings.ollama_base_url, model=settings.ollama_model_light, temperature=0.1)
    raise ValueError(f"Fournisseur LLM inconnu : {provider}")


def _tete(tier: LLMTier) -> list[tuple[str, Optional[str]]]:
    """Les candidats mis EN TÊTE par `LLM_TETE`, pour ce palier.

    Sert à essayer un modèle sur des tours réels sans toucher au code : la
    cascade habituelle reste derrière, donc un essai qui échoue retombe sur le
    comportement connu au lieu de casser l'application.

    Un réglage mal écrit est IGNORÉ, pas fatal : une variable d'environnement
    approximative ne doit pas empêcher l'assistant de répondre. Elle est
    journalisée pour que la faute de frappe se voie.
    """
    # Paramètres d'abord, `.env` ensuite. Ce réglage sert à essayer un modèle
    # sur des tours réels : il doit se poser et se retirer depuis l'interface,
    # pas par une session SSH et une recréation de conteneur sur CHAQUE serveur.
    from llm.reglages import valeur as reglage
    brut = (reglage("llm_tete") or "").strip()
    if not brut:
        return []
    sortie: list[tuple[str, Optional[str]]] = []
    for morceau in brut.split(","):
        morceau = morceau.strip()
        if not morceau:
            continue
        vise = None
        if "=" in morceau:
            palier, _, morceau = morceau.partition("=")
            vise = palier.strip().lower()
            morceau = morceau.strip()
        # Sans palier nommé : les deux paliers qui RÉDIGENT. LIGHT ne sert qu'à
        # orienter en un mot, y mettre un gros modèle serait payer pour rien.
        if vise is None:
            if tier not in (LLMTier.STANDARD, LLMTier.COMPLEX):
                continue
        elif vise != tier.value:
            continue
        fournisseur, _, modele = morceau.partition(":")
        fournisseur, modele = fournisseur.strip().lower(), modele.strip()
        if not fournisseur or not modele:
            logger.warning("LLM_TETE ignoré (forme attendue « fournisseur:modele ») : %r",
                           morceau)
            continue
        if fournisseur not in _OPENAI_COMPAT and fournisseur not in ("groq", "anthropic"):
            logger.warning("LLM_TETE ignoré (fournisseur inconnu) : %r", fournisseur)
            continue
        sortie.append((fournisseur, modele))
    if sortie:
        logger.info("LLM_TETE actif sur %s : %s", tier.value,
                    ", ".join(f"{p}:{m}" for p, m in sortie))
    return sortie


def _tier_chain(tier: LLMTier) -> list[tuple[str, Optional[str]]]:
    """Cascade de candidats (fournisseur, modèle) pour un palier, filtrée selon les clés dispo."""
    s = settings
    if tier == LLMTier.LIGHT:
        # Volume élevé, enjeu faible : orientation, classification, résumés
        # courts. On paie le moins possible, et on privilégie la latence.
        # GROQ EN TÊTE, ET C'EST LA MESURE QUI TRANCHE. « DeepSeek Flash, rapide »
        # était une hypothèse : la trace du 17/08 lui donne 25 à 38 secondes
        # pour SOIXANTE jetons de sortie. Groq rend la même chose en une à trois
        # secondes — son matériel est fait pour ça. Sur ce palier, qui ne produit
        # qu'une décision de routage, seule la latence compte : personne ne lit
        # jamais ce que le modèle y écrit.
        # J'AVAIS MIS GROQ EN TÊTE ICI, ET C'ÉTAIT FAUX. La mesure disait bien
        # que Groq répond en une à trois secondes là où DeepSeek en prend
        # vingt-cinq — mais elle portait sur le modèle 70B. Le petit modèle de
        # ce palier, `llama-3.1-8b-instant`, rend un 404 sur cette clé : chaque
        # appel de routage partait donc chercher une adresse inexistante avant
        # de retomber sur DeepSeek. J'avais rendu le chemin court PLUS LONG.
        #
        # DeepSeek reprend la tête tant que le petit modèle Groq n'est pas
        # rétabli. Groq reste juste derrière : le jour où la clé y donne accès,
        # il repasse devant sans rien changer d'autre — et depuis que le 404
        # est reconnu comme définitif, l'essai ne coûte plus qu'un aller-retour.
        chain = [
            ("deepseek", s.model_deepseek_flash),          # tête tant que le petit Groq est indisponible
            ("groq", s.model_groq_light),                  # le plus rapide quand la clé y donne accès
            ("openrouter", s.model_or_deepseek_flash),     # même modèle via la passerelle
            ("openrouter", s.model_or_free_a),
            ("openrouter", s.model_or_free_b),
            ("ollama", None),
        ]
    elif tier == LLMTier.STANDARD:
        # Rédaction courante : la LATENCE passe devant. LongCat était en tête,
        # et l'export Langfuse du 14/08 (projet jumeau, même cascade) a donné la
        # mesure : 61,8 s de MOYENNE par appel (37 appels), des pointes à 190 s.
        # Or un tour n'est pas un appel : produire un document long en enchaîne
        # quinze — un quart d'heure de rédaction pure, qui crevait le plafond
        # des tâches de fond, et l'utilisateur lisait « délai dépassé » après
        # avoir tout attendu.
        #
        # DeepSeek Flash écrit un français propre en quelques secondes ; Groq
        # 70B répond encore plus vite. LongCat n'apporte son surcroît de style
        # qu'au prix de la minute par appel : il devient le SECOURS, plus le
        # principal. La qualité d'un assistant qui répond est supérieure à
        # celle d'un assistant qui rédige mieux mais n'aboutit pas.
        # LE MÊME RENVERSEMENT, POUR LA MÊME RAISON. Le commentaire ci-dessus
        # promettait « DeepSeek Flash écrit un français propre en quelques
        # secondes » : mesuré, c'est 25 à 38 secondes par appel aux heures
        # pleines. Or un tour n'est pas un appel — celui du 17/08 en a enchaîné
        # sept, et le modèle a coûté 145 secondes sur les 307 du tour.
        #
        # Groq 70B écrit un français tout aussi correct, en une à trois
        # secondes. DeepSeek reste juste derrière : il prend le relais si Groq
        # sature, et son délai est désormais borné, ce qui n'était pas le cas.
        chain = [
            ("groq", s.model_groq_large),
            ("deepseek", s.model_deepseek_flash),
            ("openrouter", s.model_or_deepseek_flash),
            ("longcat", s.model_longcat),
            ("openrouter", s.model_primary),               # LongCat via la passerelle
            ("openrouter", s.model_or_free_a),
            ("ollama", None),
        ]
    else:  # COMPLEX
        # Analyse, synthèse, jugement : ce sont les tours où le raisonnement
        # décide de la qualité. DeepSeek Pro EN TÊTE, avant LongCat — c'est le
        # seul endroit où l'on accepte de payer davantage, et il ne représente
        # qu'une fraction des tours grâce à l'orientation.
        #
        # Groq passe DEVANT LongCat dans les replis, pour la même raison de
        # latence qu'au palier STANDARD : un secours à 60-190 s l'appel
        # transforme la panne du principal en gel de l'application.
        chain = [
            ("deepseek", s.model_deepseek),                # V4 Pro — raisonnement
            ("openrouter", s.model_or_deepseek_pro),
            ("anthropic", s.model_anthropic_vision),
            ("groq", s.model_groq_large),
            ("longcat", s.model_longcat),
            ("openrouter", s.model_or_free_b),
            ("ollama", None),
        ]
    chain = _tete(tier) + chain
    filtered = [(p, m) for (p, m) in chain if _provider_available(p)]
    # Un même couple peut arriver deux fois quand la tête reprend un candidat
    # déjà présent : le doublon ferait retenter le modèle qu'on vient d'écarter.
    vus, uniques = set(), []
    for c in filtered:
        if c not in vus:
            vus.add(c)
            uniques.append(c)
    return uniques if settings.llm_fallback_enabled else uniques[:1]


# Erreurs pour lesquelles il est inutile de retenter le MÊME modèle → passer au suivant.
#
# « 404 » ET « model_not_found » MANQUAIENT, et l'oubli coûtait cher. Groq écrit
# `model_not_found` avec des soulignés, quand la liste ne portait que « not
# found » avec un espace : l'erreur n'était donc pas reconnue comme définitive.
#
# Relevé en production : `llama-3.1-8b-instant` indisponible pour cette clé, et
# CHAQUE appel du palier léger le retentait deux fois, avec 0,5 s puis 1 s
# d'attente, avant de passer au suivant. Une seconde et demie perdue par tour,
# sur une adresse qui n'existera jamais — un modèle absent ne réapparaît pas
# parce qu'on redemande poliment.
_HARD_FAIL_MARKERS = ("429", "rate limit", "rate_limit", "quota", "insufficient", "401", "403",
                      "404", "model_not_found", "does not exist", "decommissioned",
                      "invalid api key", "authentication", "not found", "no endpoints")


def _is_hard_fail(err: Exception) -> bool:
    msg = str(err).lower()
    return any(k in msg for k in _HARD_FAIL_MARKERS)


def _contenu_vide(result: Any) -> bool:
    """Le modèle a-t-il rendu un texte vide ? (liste de blocs ou chaîne.)"""
    contenu = getattr(result, "content", result)
    if isinstance(contenu, list):
        contenu = "".join(
            (b.get("text", "") if isinstance(b, dict) else str(b)) for b in contenu)
    return not str(contenu or "").strip()



# ════════════════════════════════════════════════════════════════════════════
#  LE DISJONCTEUR — un candidat mort ne se retente pas à chaque appel.
#
#  Relevé dans les traces Langfuse du 21/08 : sur 38 appels LLM d'une seule
#  session, 33 ont échoué. DeepSeek rendait 401 « User not found » (clé morte),
#  Groq 404 sur ses deux modèles (retirés du compte), OpenRouter 401, Ollama
#  injoignable. Chaque appel repartait pourtant du haut de la cascade et
#  refaisait les quatre mêmes échecs avant d'atteindre le seul fournisseur
#  vivant — le plus lent de tous. Un tour qui enchaîne quinze appels payait donc
#  soixante allers-retours pour rien, et finissait en « une erreur est survenue ».
#
#  Le correctif n'est pas de mieux ordonner la cascade : c'est de RETENIR
#  l'échec. Un candidat qui répond « clé invalide » ou « modèle inconnu » est
#  écarté pour un temps, et la cascade commence directement au premier candidat
#  qui a une chance de répondre.
#
#  DEUX DURÉES, parce que les deux pannes n'ont pas la même nature :
#    · authentification / modèle inconnu -> 30 min. C'est un problème de
#      configuration : il ne se répare pas tout seul dans la minute.
#    · quota (429) -> 5 min. Là, l'attente EST le remède.
#
#  On ne bannit jamais définitivement : la quarantaine EXPIRE, et le candidat
#  est retenté une fois. Une clé rechargée redevient donc utilisable sans
#  redémarrer quoi que ce soit — comme pour les clés (`llm/cles.py`).
# ════════════════════════════════════════════════════════════════════════════
QUARANTAINE_AUTH_S = 1800.0
QUARANTAINE_QUOTA_S = 300.0

_QUARANTAINE: dict = {}


def _motif_quarantaine(err: Exception) -> Optional[tuple]:
    """La panne justifie-t-elle d'écarter ce candidat, et pour combien de temps ?

    Un timeout ou une coupure réseau n'entrent PAS ici : ils sont ponctuels, et
    écarter un bon fournisseur pour une seconde de réseau coûterait plus cher
    que de le retenter.
    """
    msg = str(err).lower()
    if "429" in msg or "rate limit" in msg or "rate_limit" in msg or "quota" in msg:
        return QUARANTAINE_QUOTA_S, "quota épuisé"
    if "401" in msg or "403" in msg or "invalid api key" in msg or "authentication" in msg \
       or "user not found" in msg:
        return QUARANTAINE_AUTH_S, "clé refusée"
    if "404" in msg or "model_not_found" in msg or "does not exist" in msg \
       or "decommissioned" in msg or "no endpoints" in msg:
        return QUARANTAINE_AUTH_S, "modèle inconnu de cette clé"
    # UN HÔTE QUI REFUSE LA CONNEXION, CE N'EST PAS UN TIMEOUT. Ollama est
    # toujours « disponible » pour la cascade (repli hors ligne, sans clé), mais
    # sur ces serveurs il ne tourne pas : chaque appel LLM payait deux
    # tentatives vers un port fermé — visible dans CHAQUE trace du 22/08,
    # « mistral:7b · All connection attempts failed » ×2. Un refus de connexion
    # ne se répare pas dans la seconde : cinq minutes d'écart, comme un quota.
    # Un timeout, lui, reste hors quarantaine : c'est un réseau lent, pas un
    # service absent.
    if "connection attempts failed" in msg or "connection refused" in msg \
       or "connecterror" in msg or "nodename nor servname" in msg \
       or "name or service not known" in msg or "failed to establish" in msg:
        return QUARANTAINE_QUOTA_S, "injoignable"
    return None


def _ecarter(provider: str, model, err: Exception) -> None:
    motif = _motif_quarantaine(err)
    if not motif:
        return
    duree, raison = motif
    _QUARANTAINE[(provider, model)] = (time.monotonic() + duree, raison)
    logger.warning("LLM %s:%s écarté %d min — %s", provider, model, int(duree // 60), raison)


def _ecarte(provider: str, model) -> Optional[str]:
    """La raison pour laquelle ce candidat est écarté, ou None s'il est utilisable."""
    fin, raison = _QUARANTAINE.get((provider, model), (0.0, ""))
    return raison if time.monotonic() < fin else None


def _filtrer_quarantaine(chain: list) -> list:
    """Retire les candidats écartés — mais JAMAIS tous.

    Si la quarantaine vidait la cascade, on n'aurait plus aucun chemin et le
    tour tomberait alors qu'un des candidats est peut-être revenu entre-temps.
    Tout écarter revient donc à n'écarter personne : on retente tout.
    """
    vivants = [(p, m) for p, m in chain if not _ecarte(p, m)]
    return vivants or chain


def sante_cascade() -> list[dict]:
    """Ce que l'écran Paramètres montre : qui répond, qui est écarté et pourquoi."""
    maintenant = time.monotonic()
    etat = []
    for tier in LLMTier:
        for provider, model in _tier_chain(tier):
            fin, raison = _QUARANTAINE.get((provider, model), (0.0, ""))
            ecarte = maintenant < fin
            etat.append({
                "palier": tier.value,
                "fournisseur": provider,
                "modele": model or "",
                "ecarte": ecarte,
                "raison": raison if ecarte else "",
                "reprise_dans_s": int(fin - maintenant) if ecarte else 0,
            })
    return etat


class ResilientLLM:
    """LLM résilient : parcourt la cascade du palier, retry+backoff par candidat, fallback au suivant."""

    def __init__(self, tier: LLMTier):
        self.tier = tier
        self.last_model_used: Optional[str] = None

    async def ainvoke(self, messages: Any, **kwargs) -> Any:
        chain = _filtrer_quarantaine(_tier_chain(self.tier))
        if not chain:
            raise RuntimeError(
                "Aucun fournisseur LLM configuré : renseignez au moins GROQ_API_KEY "
                "ou OPENROUTER_API_KEY dans le .env."
            )

        last_error: Optional[Exception] = None
        for idx, (provider, model) in enumerate(chain):
            try:
                llm = _build_model(provider, model,
                                   tier_max_tokens(self.tier.value),
                                   tier_timeout(self.tier.value))
            except Exception as e:  # dépendance/clé manquante à l'instanciation
                last_error = e
                logger.warning("LLM %s indisponible : %s", provider, e)
                continue

            label = f"{provider}:{model or settings.ollama_model_light}"
            # UNE RÉPONSE VIDE N'EST PAS UNE RÉPONSE. Un modèle RAISONNANT
            # (DeepSeek V4 Pro en tête du palier) dépense son budget de sortie
            # à réfléchir ; sur un gros contexte — une liste de vingt-cinq
            # mails, l'analyse d'un plan — il atteint le plafond AVANT d'avoir
            # écrit un mot, et rend un `content` vide avec finish_reason
            # « length ». Le routeur prenait ce vide pour un succès, l'agent
            # n'avait rien à afficher, et l'écran disait « je n'ai pas réussi à
            # en rédiger le compte rendu ». Relevé trois fois au banc de
            # recette, toujours après un gros résultat d'outil. On relance donc
            # UNE fois le même modèle avec un budget doublé (la réflexion déjà
            # faite ne se rejoue pas à l'identique, mais le plafond ne la coupe
            # plus), puis on passe au candidat suivant : mieux vaut un modèle
            # moins fin qui écrit qu'un modèle fin qui se tait.
            budget_double = False
            # La relance « budget doublé » s'AJOUTE aux tentatives ordinaires :
            # avec une seule tentative configurée, elle aurait lieu quand même.
            tentatives = settings.llm_max_retries
            attempt = -1
            while (attempt := attempt + 1) < tentatives:
                try:
                    result = await llm.ainvoke(messages, **kwargs)
                    if _contenu_vide(result):
                        if not budget_double:
                            budget_double = True
                            tentatives += 1
                            plafond = min(tier_max_tokens(self.tier.value) * 2, 16384)
                            logger.warning("LLM %s : réponse VIDE (plafond de sortie atteint ?) — "
                                           "relance avec %d jetons", label, plafond)
                            llm = _build_model(provider, model, plafond,
                                               tier_timeout(self.tier.value))
                            continue
                        logger.warning("LLM %s : réponse vide deux fois — candidat suivant", label)
                        last_error = RuntimeError(f"réponse vide de {label}")
                        break
                    self.last_model_used = label
                    if idx > 0:
                        logger.warning("LLM fallback → %s (palier %s)", label, self.tier.value)
                    return result
                except Exception as e:
                    last_error = e
                    if _is_hard_fail(e):
                        logger.warning("LLM %s indispo (quota/auth) : %s — candidat suivant", label, e)
                        # Et on le RETIENT : sans cela, l'appel suivant referait
                        # exactement le même échec, quinze fois par tour.
                        _ecarter(provider, model, e)
                        break  # inutile de retenter ce modèle, passer au suivant
                    delay = settings.llm_retry_base_delay * (2 ** attempt)
                    logger.warning(
                        "LLM %s tentative %d/%d échouée : %s — retry dans %.1fs",
                        label, attempt + 1, tentatives, e, delay,
                    )
                    if attempt < tentatives - 1:
                        await asyncio.sleep(delay)

        raise RuntimeError(f"Tous les modèles LLM ont échoué (dernier : {last_error})") from last_error

    def invoke(self, messages: Any, **kwargs) -> Any:
        """Version synchrone — best-effort sur le premier candidat disponible."""
        chain = _tier_chain(self.tier)
        if not chain:
            raise RuntimeError("Aucun fournisseur LLM configuré")
        provider, model = chain[0]
        llm = _build_model(provider, model)
        result = llm.invoke(messages, **kwargs)
        self.last_model_used = f"{provider}:{model or settings.ollama_model_light}"
        return result


def get_llm(tier: LLMTier) -> ResilientLLM:
    """Retourne un LLM résilient (cascade multi-fournisseurs) pour le palier demandé."""
    return ResilientLLM(tier)


def get_vision_llm() -> tuple[Any, Optional[str]]:
    """Retourne (llm, label) d'un modèle capable de VISION, ou (None, None).

    Préférence : Anthropic (si clé) > Groq multimodal (llama-4). Ces modèles acceptent
    un message multimodal (content = [{type:'text'}, {type:'image_url', image_url:{url:'data:...'}}]).
    Modèle direct (pas la cascade) : la vision nécessite un modèle spécifique.
    """
    s = settings
    if not getattr(s, "vision_enabled", True):
        return None, None
    candidats = get_vision_candidates()
    return candidats[0] if candidats else (None, None)


def get_vision_candidates() -> list[tuple[Any, str]]:
    """TOUS les modèles de vision constructibles, dans l'ordre de préférence.

    Un seul candidat ne suffisait pas : `get_vision_llm` rendait le premier
    fournisseur qui AVAIT UNE CLÉ, et si son modèle répondait 404 — relevé au
    banc de recette, Groq multimodal retiré : « L'analyse visuelle a échoué
    (NotFoundError) » — l'agent 2 n'avait plus d'yeux, alors qu'une clé Google
    capable de voir dormait dans la configuration. L'appelant essaie donc les
    candidats l'un après l'autre, comme la cascade texte.

    Ordre : Anthropic (meilleure lecture de plans), Google Gemini (rapide,
    gratuit, toujours un modèle courant), Groq multimodal (si encore servi).
    """
    s = settings
    if not getattr(s, "vision_enabled", True):
        return []
    sortie: list[tuple[Any, str]] = []
    for provider, model in (("anthropic", s.model_anthropic_vision),
                            ("google", s.model_google_vision),
                            ("google", s.model_google_vision_secours),
                            ("groq", s.model_groq_vision)):
        if not _provider_available(provider):
            continue
        try:
            sortie.append((_build_model(provider, model), f"{provider}:{model}"))
        except Exception as e:  # noqa: BLE001
            logger.warning("Modèle vision %s non constructible : %s", provider, e)
    return sortie


def classify_request_tier(query: str, has_attachment: bool = False) -> LLMTier:
    """
    Classe la requête dans le bon palier.
    Bias volontaire vers LIGHT (gratuit) pour un max d'actions simples/backend.
    """
    if has_attachment:
        return LLMTier.COMPLEX

    q = query.lower().strip()
    words = len(query.split())
    greetings = ("bonjour", "salut", "hello", "coucou", "bonsoir", "hey", "merci", "ça va", "ca va")
    # Salutation / politesse très courte → petit modèle rapide (suffisant).
    if words <= 4 and any(g in q for g in greetings):
        return LLMTier.LIGHT
    # Tout le reste, questions métier incluses → modèle STANDARD (Groq 70B, rapide ET fiable :
    # le 8B hallucinait des chiffres/balises sur les questions).
    return LLMTier.STANDARD
