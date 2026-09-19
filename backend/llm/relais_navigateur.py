"""
LE NAVIGATEUR PENSE AVEC LES MODÈLES DE L'ASSISTANT (19/09).

La navigation autonome tournait sur OpenRouter, pendant que tout le reste de Duret
tourne sur Ollama Cloud. Le 19/09, le compte OpenRouter était vide (16 $ consommés
sur 16) : plus aucune navigation. Décision de Noa : « utiliser les modèles Ollama
Cloud au maximum ».

Le conteneur navigateur n'a pas la clé Ollama Cloud, et c'est voulu : il ouvre des
pages inconnues, il ne détient aucun secret de l'entreprise, et la clé vit en base
(Paramètres → Clés API). Il appelle donc CE relais, au format OpenAI, avec son
secret de guichet ; le backend pose la clé, choisit le modèle, bride la réflexion
comme partout ailleurs (`reflexion_mesuree`) et rend la réponse.

OLLAMA CLOUD N'IMPOSE PAS LE SCHÉMA JSON (mesuré le 19/09, voie OpenAI comme voie
native : le JSON rendu ne suit pas le schéma demandé, parfois entouré de ```json).
browser-use met le schéma dans sa consigne système (`add_schema_to_system_prompt`)
et lit la réponse STRICTEMENT : une clôture ```json suffisait à faire échouer une
étape. Le relais rend donc le seul objet JSON de la réponse quand un JSON est attendu.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Optional

logger = logging.getLogger("duret.llm.relais_navigateur")

MAX_JETONS = 16384


def modele_du_navigateur() -> str:
    """Le modèle Ollama Cloud du navigateur : le réglage `modele_navigateur`
    (« ollama_cloud:… ») s'il est posé, sinon celui de la configuration."""
    from config import settings
    try:
        from llm.reglages import texte
        brut = (texte("modele_navigateur") or "").strip()
    except Exception:  # noqa: BLE001 — un réglage illisible n'arrête pas la navigation
        brut = ""
    fournisseur, _, modele = brut.partition(":")
    if fournisseur.strip().lower() == "ollama_cloud" and modele.strip():
        return modele.strip()
    return settings.model_ollama_cloud_navigateur


def modele_de_secours(modele: str) -> str:
    """Le modèle rapide de l'assistant (réglage `modele_rapide`, sinon la configuration),
    s'il diffère de celui qui vient d'échouer."""
    from config import settings
    try:
        from llm.reglages import texte
        fournisseur, _, rapide = (texte("modele_rapide") or "").partition(":")
        rapide = rapide.strip() if fournisseur.strip().lower() == "ollama_cloud" else ""
    except Exception:  # noqa: BLE001
        rapide = ""
    rapide = rapide or settings.model_ollama_cloud_rapide
    return rapide if rapide and rapide != modele else ""


def modeles_permis() -> set:
    """Les modèles Ollama Cloud que le navigateur peut demander par leur nom : ceux que
    l'assistant a déjà (configuration et réglages). Tout autre nom → le modèle par défaut."""
    from config import settings
    permis = {settings.model_ollama_cloud_rapide, settings.model_ollama_cloud_puissant,
              settings.model_ollama_cloud_vision, settings.model_ollama_cloud_vision_secours,
              settings.model_ollama_cloud_navigateur}
    try:
        from llm.reglages import texte
        for nom in ("modele_rapide", "modele_puissant", "modele_vision", "modele_navigateur"):
            fournisseur, _, modele = (texte(nom) or "").partition(":")
            if fournisseur.strip().lower() == "ollama_cloud" and modele.strip():
                permis.add(modele.strip())
    except Exception:  # noqa: BLE001
        pass
    return {m for m in permis if m}


def attend_du_json(corps: dict) -> bool:
    """La demande attend-elle un objet JSON ? (`response_format`, ou le schéma que
    browser-use pose dans sa consigne système)."""
    if corps.get("response_format"):
        return True
    for m in corps.get("messages") or []:
        if not isinstance(m, dict) or m.get("role") != "system":
            continue
        contenu = m.get("content")
        texte = contenu if isinstance(contenu, str) else json.dumps(contenu, ensure_ascii=False)
        if "<json_schema>" in texte:
            return True
    return False


def json_propre(texte: Optional[str]) -> Optional[str]:
    """Le seul objet JSON d'une réponse (clôtures et phrases autour retirées), ou None."""
    t = str(texte or "").strip()
    if not t:
        return None
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.S)
    if m:
        t = m.group(1).strip()
    try:
        json.loads(t)
        return t
    except Exception:  # noqa: BLE001
        pass
    debut, fin = t.find("{"), t.rfind("}")
    if 0 <= debut < fin:
        bout = t[debut:fin + 1]
        try:
            json.loads(bout)
            return bout
        except Exception:  # noqa: BLE001
            try:
                from json_repair import repair_json
                repare = repair_json(bout)
                if isinstance(json.loads(repare), dict):
                    return repare
            except Exception:  # noqa: BLE001
                return None
    return None


def corps_ollama(corps: dict, modele: str) -> dict:
    """La requête envoyée à Ollama Cloud : messages tels quels, plafond borné,
    réflexion bridée comme pour l'assistant, JSON demandé quand il est attendu."""
    from llm.router import reflexion_mesuree
    try:
        plafond = int(corps.get("max_completion_tokens") or corps.get("max_tokens") or 4096)
    except (TypeError, ValueError):
        plafond = 4096
    envoi: dict[str, Any] = {"model": modele, "messages": corps.get("messages") or [],
                             "max_tokens": max(1, min(plafond, MAX_JETONS)), "stream": False}
    if corps.get("temperature") is not None:
        envoi["temperature"] = corps["temperature"]
    effort = reflexion_mesuree("ollama_cloud", modele, palier="standard")
    if effort:
        envoi["reasoning_effort"] = effort
    if attend_du_json(corps):
        envoi["response_format"] = {"type": "json_object"}
    return envoi


async def _appeler(envoi: dict, cle: str, modele: str) -> dict:
    import httpx
    from fastapi import HTTPException
    from config import settings
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            r = await client.post(settings.ollama_cloud_base_url.rstrip("/") + "/chat/completions",
                                  json=envoi, headers={"Authorization": "Bearer " + cle})
    except httpx.HTTPError as e:
        logger.warning("Relais navigateur : Ollama Cloud injoignable (%s)", type(e).__name__)
        raise HTTPException(status_code=502, detail="Ollama Cloud injoignable.") from e
    if r.status_code >= 400:
        # Le détail du fournisseur ne porte pas la clé ; il dit la cause (quota, modèle inconnu).
        logger.warning("Relais navigateur : %s refuse (%s) %s", modele, r.status_code, r.text[:200])
        raise HTTPException(status_code=r.status_code, detail=r.text[:300])
    return r.json()


async def relayer(corps: dict) -> dict:
    """Un appel du navigateur → Ollama Cloud → la réponse, au format OpenAI."""
    from fastapi import HTTPException
    from llm.router import _cle

    cle = _cle("ollama_cloud")
    if not cle:
        raise HTTPException(status_code=503, detail="Aucune clé Ollama Cloud (Paramètres → Clés API).")
    demande = str(corps.get("model") or "").strip()
    modele = demande if demande in modeles_permis() else modele_du_navigateur()
    envoi = corps_ollama(corps, modele)
    debut = time.monotonic()
    # UNE RÉPONSE VIDE SE REDEMANDE ICI, UNE FOIS (19/09, mesuré sur la navigation Gerflor) :
    # kimi-k3 rend parfois un contenu vide — la réflexion a mangé la sortie. browser-use en
    # faisait un échec d'étape (« Invalid JSON: EOF »), puis une étape de plus ; redemandé
    # au relais, c'est une seconde de plus au lieu d'un tour de boucle.
    for essai in (1, 2):
        try:
            donnees = await _appeler(envoi, cle, modele)
        except HTTPException as e:
            # UN MODÈLE EN PANNE OU SATURÉ CÈDE LA PLACE au modèle rapide de l'assistant
            # (même compte, même clé) : une navigation ne meurt pas sur un 503 passager.
            secours = modele_de_secours(modele)
            if e.status_code not in (429, 500, 502, 503, 504) or not secours:
                raise
            logger.warning("Relais navigateur : %s indisponible (%s), secours %s", modele, e.status_code, secours)
            modele = secours
            envoi = corps_ollama(corps, modele)
            donnees = await _appeler(envoi, cle, modele)
        if "response_format" not in envoi:
            break
        vides = 0
        for choix in donnees.get("choices") or []:
            message = choix.get("message") or {}
            propre = json_propre(message.get("content"))
            if propre is None:
                # Le JSON rangé dans le champ de réflexion vaut réponse.
                propre = json_propre(message.get("reasoning") or message.get("reasoning_content"))
            if propre is not None:
                message["content"] = propre
            elif not str(message.get("content") or "").strip():
                vides += 1
        if not vides:
            break
        logger.info("Relais navigateur : réponse vide de %s (essai %d)", modele, essai)
        # Le second essai part sur le modèle de secours : redemander au même modèle rendait
        # parfois un second vide (mesuré en production le 19/09).
        secours = modele_de_secours(modele)
        if secours:
            modele = secours
            envoi = corps_ollama(corps, modele)
    logger.info("Relais navigateur : %s, %.1f s", modele, time.monotonic() - debut)
    return donnees
