"""
Réglages système NON SECRETS — base d'abord, `.env` ensuite.

Jumeau de `llm/cles.py`, pour ce qui n'est pas un secret. Même ordre de
résolution (la base SURCHARGE l'environnement), même cache court, même
discipline de rafraîchissement — et UNE différence assumée : ici la valeur
est LISIBLE. Un réglage qu'on ne peut pas relire est un réglage qu'on ne peut
pas vérifier, et `cles_api` garde son invariant intact (voir migration 026).

Pourquoi ce module existe : `llm_tete` force un modèle en tête de cascade pour
essayer un fournisseur sur des tours réels. C'est le réglage le plus
expérimental du socle, et c'était le plus coûteux à changer — éditer le `.env`
de chaque VPS, puis recréer le conteneur. Deux clients, deux serveurs, deux
sessions SSH pour un essai qu'on veut pouvoir annuler en dix secondes.
"""
from __future__ import annotations

import logging
import time

from config import settings

logger = logging.getLogger("duret.llm.reglages")

# Liste FERMÉE, comme pour les clés : une ligne fantaisiste en base ne doit pas
# pouvoir redéfinir n'importe quel attribut de la configuration.
REGLAGES_CONNUS = (
    "llm_tete",
    # Combien d'appels de modèle partent EN MÊME TEMPS (01/09). L'abonnement du
    # fournisseur en autorise un nombre fixe ; au-delà il met en file puis
    # refuse, et un refus coûte cinq minutes de quarantaine. Se règle à l'écran
    # parce que le plafond change avec l'offre, pas avec le code.
    "llm_simultanes",
    "kpi_depuis",   # AAAA-MM-JJ — les indicateurs ne comptent rien avant cette date
    # L'anonymisation PII se coupe d'un clic (demande de Noa, 30/08 : elle
    # cassait des flux réels — adresse tapée masquée en boucle, balises dans
    # les mails). Valeurs admises : « active » ou « desactivee » — le DÉFAUT
    # est « desactivee » depuis le 31/08 (config.py), sur décision de Noa.
    # La RÉHYDRATATION, elle, reste toujours en service : les jetons déjà
    # posés dans l'historique doivent continuer de se résoudre.
    "anonymisation",
    # DEUX MODÈLES, ET RIEN D'AUTRE (demande de Noa, 31/08 : « deux modèles
    # fiables et rapides, un pour répondre vite, un pour les grosses tâches ;
    # on oublie tous les autres LLM »). « fournisseur:modele » chacun. Dès
    # qu'un des deux est posé, la cascade habituelle n'est plus utilisée :
    # le rapide sert LIGHT et STANDARD, le puissant COMPLEX et les campagnes,
    # chacun secourt l'autre. Les deux vides = cascade automatique.
    "modele_rapide",
    "modele_puissant",
    # LA VISION ET LES EMBEDDINGS SE CHOISISSENT AUSSI (01/09, relevé de Noa :
    # « je vois pas le choix des modèles pour embedding ou image ou OCR »).
    # Ils vivaient dans le `.env`, donc derrière une session SSH et une
    # recréation de conteneur — exactement ce que la migration 026 avait
    # supprimé pour les modèles de texte.
    #
    # L'IMAGE, ELLE, N'EST PAS ICI, et c'est voulu : « la génération d'image,
    # je veux que ça reste Nano Banana Pro avec Google AI ». L'écran la montre,
    # il ne la propose pas.
    "modele_vision",
    "modele_embedding",
)

# Les fournisseurs de TEXTE que le routeur sait construire (llm/router.py).
# Dupliqué ici plutôt qu'importé : reglages.py est lu par le routeur, pas
# l'inverse, et un import croisé au démarrage a déjà coûté une matinée.
# LES EMBEDDINGS N'ONT PAS LES MÊMES FOURNISSEURS QUE LE TEXTE (02/09).
#
# `modele_embedding` était validé contre FOURNISSEURS_TEXTE : l'écran
# acceptait donc « longcat:… » ou « deepseek:… », que le moteur d'embedding
# ne sait pas exécuter — il retombait sur « fournisseur inconnu » et plus
# rien n'était vectorisé, en silence. Le piège le plus vicieux était
# « google » : c'est le nom du fournisseur dans la cascade de texte, mais le
# moteur d'embedding l'appelle « gemini ». Le choix le plus naturel de tous
# cassait donc la vectorisation. Les deux noms sont acceptés ici, et
# `embeddings.py` les ramène au même fournisseur.
FOURNISSEURS_EMBEDDING = ("ollama_cloud", "ollama", "gemini", "google", "openai")

FOURNISSEURS_TEXTE = ("ollama_cloud", "longcat", "deepseek", "openrouter",
                      "google", "groq", "anthropic")

# Un réglage dont la valeur finit DANS du SQL doit être validé à l'écriture ET
# à la lecture. On l'oblige à n'être qu'un instant ISO, ce qui le rend
# inoffensif une fois inséré.
#
# L'HEURE EST ADMISE, ET CE N'EST PAS UN LUXE. Avec une granularité au jour,
# « remets les compteurs à zéro » laissait sur le tableau de bord toute
# l'activité du jour même — 20 évènements en production, ceux des essais de la
# matinée. Or une remise à zéro est un INSTANT, pas une journée : on veut
# repartir de MAINTENANT. Une date nue reste acceptée (le champ de l'écran en
# produit une) et vaut minuit, comme avant.
import re
_FORMAT_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?$")

DUREE_CACHE_S = 30

_CACHE: dict[str, str] = {}
_EXPIRE: float = 0.0


async def rafraichir(force: bool = False) -> None:
    """Recharge les surcharges depuis la base. Ne lève jamais."""
    global _CACHE, _EXPIRE
    if not force and time.monotonic() < _EXPIRE:
        return
    _EXPIRE = time.monotonic() + DUREE_CACHE_S
    try:
        from database.connection import get_db
        async with get_db() as conn:
            lignes = await conn.fetch("SELECT cle, valeur FROM reglages")
    except Exception as e:  # noqa: BLE001 - base indisponible : on garde le .env
        logger.debug("Surcharges de réglages indisponibles (%s)", e)
        return
    _CACHE = {l["cle"]: l["valeur"] for l in lignes
              if l["cle"] in REGLAGES_CONNUS and (l["valeur"] or "").strip()}


def valeur(nom: str) -> str | None:
    """Réglage effectif : surcharge en base si elle existe, sinon `.env`.

    SYNCHRONE à dessein : appelée depuis la construction des cascades, qui ne
    peut pas attendre. Elle lit le cache et RELANCE le rafraîchissement quand
    il est périmé, sans l'attendre.

    Ce second déclenchement n'est pas décoratif : sans lui, le cache ne se
    remplirait qu'à l'ouverture de la page Paramètres, et un réglage
    enregistré serait ignoré après chaque redéploiement. C'est le bug exact
    qu'a connu `llm/cles.py` (commit `fe6e106`), et il a coûté une saga
    entière — on ne le refait pas.
    """
    if time.monotonic() >= _EXPIRE:
        try:
            import asyncio
            asyncio.get_running_loop().create_task(rafraichir())
        except RuntimeError:
            pass  # hors boucle (script) : le repli .env reste le comportement
    if nom in _CACHE:
        return _CACHE[nom]
    return getattr(settings, nom, None)


def texte(nom: str) -> str:
    """La valeur d'un réglage, TOUJOURS en chaîne propre.

    POURQUOI CETTE FONCTION EXISTE (01/09, troisième occurrence du même bug).
    `valeur()` rend ce que porte la configuration, et tous les réglages n'y sont
    pas des chaînes : `llm_simultanes` est un ENTIER. Trois appelants ont écrit
    `(valeur(nom) or "").strip()` — et `8.strip()` lève, ce qui a mis « HTTP
    500 » dans Paramètres trois fois de suite, à trois endroits différents.

    La parade n'est pas de corriger la ligne, c'est de retirer l'occasion : qui
    veut du texte appelle CECI, et n'a plus à savoir de quel type est le
    réglage. Le banc refuse tout `.strip()` posé directement sur `valeur(...)`.
    """
    return str(valeur(nom) or "").strip()


async def enregistrer(nom: str, brut: str | None, user_id: str) -> str:
    """Écrit ou supprime une surcharge. Retourne la valeur effective.

    Une valeur vide SUPPRIME la surcharge plutôt que d'enregistrer une chaîne
    vide : vider le champ doit rendre la main au `.env`, jamais imposer un
    réglage vide — ce n'est jamais l'intention de qui efface.
    """
    # Le refus vient AVANT tout contact avec la base : un nom hors liste ne
    # doit rien ouvrir du tout, pas même une connexion.
    if nom not in REGLAGES_CONNUS:
        raise ValueError(f"Réglage inconnu : {nom}")
    if nom == "kpi_depuis" and (brut or "").strip() and not _FORMAT_INSTANT.match((brut or "").strip()):
        raise ValueError("Date attendue au format AAAA-MM-JJ, éventuellement "
                         "suivie de HH:MM (ex. 2026-08-22 ou 2026-08-22 18:30).")
    if nom == "anonymisation" and (brut or "").strip() \
            and (brut or "").strip().lower() not in ("active", "desactivee"):
        raise ValueError("Valeur attendue : « active » ou « desactivee ».")
    if nom == "llm_simultanes" and (brut or "").strip():
        # ⚠️ NE JAMAIS APPELER CETTE VARIABLE `valeur` : ce module expose une
        # FONCTION `valeur()`, appelée au `return` de cette même fonction. Une
        # assignation locale, même dans une branche jamais prise, rend le nom
        # local À TOUTE LA FONCTION — et le retour levait alors
        # `UnboundLocalError` pour TOUS les réglages, pas seulement celui-ci.
        # C'est ce qui a mis « HTTP 500 » partout dans Paramètres le 01/09.
        nombre = (brut or "").strip()
        if not nombre.isdigit() or not (1 <= int(nombre) <= 64):
            raise ValueError("Nombre attendu entre 1 et 64 (l'abonnement en autorise 10).")
    if nom in ("modele_rapide", "modele_puissant",
               "modele_vision", "modele_embedding") and (brut or "").strip():
        f, _, m = (brut or "").strip().partition(":")
        admis = (FOURNISSEURS_EMBEDDING if nom == "modele_embedding"
                 else FOURNISSEURS_TEXTE)
        if f.strip().lower() not in admis or not m.strip():
            raise ValueError("Forme attendue : « fournisseur:modele », fournisseur parmi "
                             + ", ".join(admis) + ".")
    from database.connection import get_db

    v = (brut or "").strip()
    async with get_db() as conn:
        if not v:
            await conn.execute("DELETE FROM reglages WHERE cle = $1", nom)
        else:
            await conn.execute(
                "INSERT INTO reglages (cle, valeur, updated_by) VALUES ($1, $2, $3::uuid) "
                "ON CONFLICT (cle) DO UPDATE SET valeur = EXCLUDED.valeur, "
                "  updated_at = NOW(), updated_by = EXCLUDED.updated_by",
                nom, v, user_id)
    await rafraichir(force=True)
    return valeur(nom) or ""


async def etat() -> list[dict]:
    """Pour l'interface : la valeur en vigueur, et d'où elle vient."""
    await rafraichir(force=True)
    lignes = []
    for nom in REGLAGES_CONNUS:
        surcharge = _CACHE.get(nom)
        # `str()` AVANT `.strip()` : tous les réglages ne sont pas des chaînes
        # dans la configuration — `llm_simultanes` est un entier, et `8.strip()`
        # faisait tomber l'écran ENTIER des réglages, pas seulement sa ligne.
        depuis_env = str(getattr(settings, nom, None) or "").strip()
        lignes.append({
            "cle": nom,
            "valeur": surcharge or depuis_env or "",
            "origine": "parametres" if surcharge else ("env" if depuis_env else None),
        })
    return lignes


def date_kpi() -> str | None:
    """La date de départ des indicateurs, ou None si l'on compte tout.

    Revalidée ICI, et pas seulement à l'écriture : une ligne posée à la main en
    base ne doit pas pouvoir devenir du SQL. Une valeur mal formée est traitée
    comme absente — un tableau de bord qui compte trop est un désagrément, un
    tableau de bord qui tombe n'aide personne.
    """
    v = texte("kpi_depuis")
    return v if _FORMAT_INSTANT.match(v) else None


def plancher_sql(colonne: str) -> str:
    """Fragment ` AND <colonne> >= DATE '...'`, ou rien du tout.

    Rendu comme littéral et non comme paramètre : les requêtes du tableau de
    bord sont assemblées par f-string avec un périmètre RLS déjà numéroté, et
    y insérer un $N de plus obligerait à renuméroter une douzaine de requêtes
    — c'est-à-dire à risquer un décalage silencieux. Le littéral est sûr parce
    que la valeur ne peut être qu'un AAAA-MM-JJ (`_FORMAT_DATE`, deux fois).
    """
    d = date_kpi()
    # TIMESTAMPTZ et non DATE : une date nue y vaut minuit — le comportement
    # d'avant — tandis qu'un instant complet coupe à la seconde près. Sur une
    # colonne de type DATE (`api_usage_daily.date`), Postgres promeut la date à
    # minuit avant de comparer : la journée en cours sort donc du compte, ce
    # qui est bien l'intention d'une remise à zéro.
    return f" AND {colonne} >= TIMESTAMPTZ '{d}'" if d else ""
