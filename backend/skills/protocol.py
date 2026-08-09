"""
Protocole d'appel d'outil — bloc ```action textuel.

POURQUOI PAS le function-calling natif (`bind_tools`) : la cascade LLM du projet
mélange LongCat, Groq 70B/8B, des modèles gratuits d'OpenRouter, DeepSeek et
Ollama. Le support du function-calling y est inégal, invérifié sur le modèle
PRINCIPAL, et surtout il échoue SILENCIEUSEMENT sur certains points d'accès (ils
acceptent le paramètre `tools` puis répondent en prose) — un mode de panne que la
cascade ne peut pas détecter pour rétrograder.

Le protocole retenu est celui qui FONCTIONNE DÉJÀ en production dans ce projet :
le modèle émet un bloc balisé contenant du JSON, exactement comme les blocs
```ui des composants visuels. Il marche sur les 7 candidats, survit à une
rétrogradation en milieu de cascade (l'historique reste du texte pur), et
dégrade proprement : pas de bloc = réponse en prose, bloc invalide = une seule
tentative de réparation.

Le modèle ne choisit QUE parmi ce catalogue. Un nom inconnu est refusé ici, bien
avant d'atteindre l'exécuteur.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

logger = logging.getLogger("duret.skills.protocol")

# Un bloc ```action ... ``` n'importe où dans la réponse.
BLOC_ACTION_RE = re.compile(r"```action\s*(.*?)```", re.S)

# Syntaxes d'appel d'outil NATIVES des modèles de la cascade. Observé en
# production : LongCat émet parfois son propre balisage au lieu du bloc demandé,
# et il partait tel quel à l'écran — l'utilisateur recevait du XML. On le
# reconnaît donc comme une action valide (l'intention du modèle est juste, seule
# la forme diffère), et ce qui n'est pas interprétable est au moins retiré de
# l'affichage.
#
#   <longcat_tool_call>rechercher_documents
#   <longcat_arg_key>requete</longcat_arg_key>
#   <longcat_arg_value>chantier 2031</longcat_arg_value>
#   </longcat_tool_call>
BLOC_NATIF_RE = re.compile(
    r"<longcat_tool_call>\s*(.*?)</longcat_tool_call>", re.S)
_ARG_NATIF_RE = re.compile(
    r"<longcat_arg_key>\s*(.*?)\s*</longcat_arg_key>\s*"
    r"<longcat_arg_value>\s*(.*?)\s*</longcat_arg_value>", re.S)

# Tout balisage d'outil résiduel, quel qu'en soit le modèle : il ne doit JAMAIS
# rester visible. Filet de sécurité appliqué juste avant l'affichage.
BALISAGE_OUTIL_RE = re.compile(
    r"<\/?(?:longcat_tool_call|longcat_arg_key|longcat_arg_value|tool_call|"
    r"function_call|tool_use|invoke|antml:[a-z_]+)[^>]*>", re.I)


# Autre forme rencontrée : le modèle rend un objet JSON nu, sans balise, dans la
# convention OpenAI (`name`/`arguments`) ou dans la nôtre (`skill`/`args`). Sans
# reconnaissance, l'utilisateur reçoit du JSON en guise de réponse.
_DEBUT_JSON_NU_RE = re.compile(
    r"\{\s*\"(?:skill|name|tool|function)\"\s*:\s*\"[a-z_]+\"")


def _objet_equilibre(texte: str, debut: int) -> str | None:
    """Extrait l'objet JSON commençant à `debut`, accolades équilibrées.

    Une expression régulière ne convient pas : `.*?\\}` s'arrête à la première
    accolade fermante, qui est celle des arguments IMBRIQUÉS, et rend un JSON
    tronqué. On compte donc les accolades, en ignorant celles des chaînes.
    """
    niveau, dans_chaine, echappe = 0, False, False
    for i in range(debut, len(texte)):
        c = texte[i]
        if echappe:
            echappe = False
            continue
        if c == "\\":
            echappe = True
        elif c == '"':
            dans_chaine = not dans_chaine
        elif not dans_chaine:
            if c == "{":
                niveau += 1
            elif c == "}":
                niveau -= 1
                if niveau == 0:
                    return texte[debut:i + 1]
    return None


def _action_json_nu(texte: str, role: str | None = None):
    """Reconnaît un appel d'outil rendu en JSON nu, sans aucune balise."""
    for amorce in _DEBUT_JSON_NU_RE.finditer(texte or ""):
        brut = _objet_equilibre(texte, amorce.start())
        if not brut:
            continue
        try:
            data = json.loads(brut)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        nom = data.get("skill") or data.get("name") or data.get("tool") or data.get("function")
        if nom not in catalogue(role):
            continue
        args = data.get("args") or data.get("arguments") or data.get("parameters") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                continue
        if not isinstance(args, dict):
            continue
        if [p for p in catalogue(role)[nom][1] if not str(args.get(p) or "").strip()]:
            continue
        fin = amorce.start() + len(brut)
        reste = (texte[:amorce.start()] + texte[fin:]).strip()
        return {"skill": nom, "args": args}, reste, None
    return None, texte, None


def _action_native(texte: str, role: str | None = None):
    """Convertit un appel natif en `{skill, args}`, ou None si illisible."""
    trouve = BLOC_NATIF_RE.search(texte or "")
    if not trouve:
        return _action_json_nu(texte or "", role)

    reste = ((texte[:trouve.start()] + texte[trouve.end():]) or "").strip()
    corps = trouve.group(1)
    nom = corps.splitlines()[0].strip() if corps.strip() else ""
    if nom not in catalogue(role):
        return None, reste, None

    args = {}
    for cle, valeur in _ARG_NATIF_RE.findall(corps):
        valeur = valeur.strip()
        # Une valeur peut être du JSON (liste de types, objet) ou du texte brut.
        if valeur[:1] in "[{":
            try:
                valeur = json.loads(valeur)
            except json.JSONDecodeError:
                pass
        args[cle.strip()] = valeur

    manquants = [p for p in catalogue(role)[nom][1]
                 if not str(args.get(p) or "").strip()]
    if manquants:
        return None, reste, None
    return {"skill": nom, "args": args}, reste, None

# Catalogue exposé au modèle : nom -> (description, requis[], optionnels[]).
# Volontairement PETIT au départ : uniquement des skills natifs, dont les effets
# sont déclarés dans le code. Les skills générés (bac à sable) n'y figurent pas.
CATALOGUE_AGENT1: dict[str, tuple[str, list[str], list[str]]] = {
    "rechercher_documents": (
        "Cherche dans la mémoire d'entreprise (devis, chantiers, clients, mails, "
        "documents importés). À appeler dès qu'une question porte sur des données "
        "internes. Peut être relancé avec d'autres termes si la première recherche "
        "ne donne rien",
        ["requete"], ["types"]),
    "connaissances_acquises": (
        "LISTE ce que l'assistant a APPRIS de l'entreprise (connaissances et manières "
        "de faire retenues par les campagnes d'enrichissement). À utiliser dès qu'on "
        "demande « que sais-tu de nous », « qu'as-tu appris », « quelles connaissances "
        "as-tu ». C'est un INVENTAIRE, pas une recherche : il rend ce qui existe, sans "
        "seuil de pertinence. sujet : mot-clé optionnel pour filtrer",
        [], ["sujet"]),
    "mes_droits": (
        "Explique les DROITS D'ACCES : ce que la personne connectee peut consulter, "
        "ce qui lui est ferme, quelles boites mail elle peut lire, et comment le "
        "cloisonnement fonctionne pour les AUTRES roles. A utiliser des qu'on demande "
        "« quels sont mes droits », « qui a acces a quoi », « un terrain peut-il voir "
        "les marges ». Les droits sont LUS dans la configuration reelle",
        [], []),
    "interroger_donnees": (
        "COMPTE et FILTRE de facon EXACTE dans les donnees importees (fichiers CSV/Excel "
        "d'un logiciel metier). OBLIGATOIRE des qu'on demande un nombre, un total, une "
        "liste par critere : la recherche semantique approxime et ne sait pas compter. "
        "Sans argument : les jeux de donnees disponibles. Avec source_type seul : ses "
        "colonnes et leurs valeurs reelles. Avec filtres (objet {colonne: valeur}) : le "
        "compte exact. Verifie TOUJOURS les valeurs reelles avant de filtrer",
        [], ["source_type", "filtres"]),
    "lire_mails": (
        "LIT les derniers messages d'UNE boîte, en direct. Pour consulter, relever, "
        "faire le point sur le courrier récent. C'est un ÉCHANTILLON de 25 messages "
        "au plus : n'en tire jamais de conclusion sur l'entreprise entière, ses "
        "activités ou ses process. Pour cela, c'est `lancer_enrichissement`. "
        "dossier : recus (défaut) ou envoyes ; limite : 1 à 25. Sans mailbox, la "
        "boîte de la personne connectée",
        [], ["mailbox", "dossier", "limite"]),
    "triage_email_entrant": (
        "Classe et priorise un message reçu (catégorie, urgence, action suggérée)",
        ["mailbox"], ["objet", "corps"]),
    "redaction_email": (
        "Rédige un BROUILLON de message (11 types : reponse, relance_devis, "
        "relance_impaye, envoi_devis, reclamation, information_chantier, "
        "confirmation_rdv, demande_information, remerciement, refus, interne). "
        "N'envoie jamais.",
        ["mailbox", "type_mail"], ["contexte", "message_recu", "destinataire"]),
    "resume_fil_email": (
        "Résume un échange de mails et en extrait les engagements",
        ["mailbox", "fil"], []),
    "apprendre_style_email": (
        "Apprend le style d'écriture d'une boîte à partir de ses messages envoyés",
        [], ["mailbox"]),
    "lancer_enrichissement": (
        "ADMINISTRATION UNIQUEMENT. LA seule action capable d'analyser TOUT le "
        "courrier de l'entreprise : elle relit toutes les boîtes par lots, construit "
        "un profil d'écriture par personne, et en tire des connaissances, des "
        "manières de faire et des brouillons de skills. C'est elle qu'il faut "
        "lancer dès qu'on demande d'analyser les mails de l'entreprise, d'en tirer "
        "des process, des activités ou des compétences. Elle dure plusieurs heures "
        "et travaille en tâche de fond : annonce-la, ne prétends pas avoir déjà le "
        "résultat. Ne la propose jamais de toi-même sans demande explicite",
        [], ["collecter", "max_lots_par_boite", "acces_skills"]),
    "statut_enrichissement": (
        "Avancement de la campagne d'enrichissement en cours (administration)",
        [], []),
    "creer_tache_agent": (
        "Enregistre une tâche que l'assistant exécutera plus tard, éventuellement de "
        "façon répétée. recurrence : interval (avec interval_minutes, minimum 5), "
        "daily ou weekly (avec heure « 07:30 », et jours [1..7] pour weekly). "
        "Sans recurrence, la tâche ne part que sur demande.",
        ["titre", "consigne"],
        ["recurrence", "interval_minutes", "heure", "jours"]),
}


# ── Skills du catalogue en base ──────────────────────────────────────
#
# Le catalogue ci-dessus est celui des skills NATIFS. Le registre `skills` en
# base en contient bien d'autres (analyse de CCTP, suivi de réserves, rapproche-
# ment de factures...), visibles dans l'onglet Skills. Le chat les ignorait :
# interrogé sur ce qu'il savait faire, il n'en citait que six, et refusait donc
# des demandes qu'il aurait pu traiter.
#
# On les charge périodiquement dans ce registre. Les natifs restent PRIORITAIRES
# (leur signature est déclarée dans le code, pas devinée) ; un skill en base ne
# peut pas en masquer un.
# nom -> (description, requis[], optionnels[], niveau d'accès)
_EXTERNES: dict[str, tuple[str, list[str], list[str], str]] = {}
_EXTERNES_EXPIRE: float = 0.0
DUREE_CACHE_CATALOGUE_S = 300


def _niveaux_visibles(role: str | None) -> set[str]:
    """Niveaux d'accès qu'un rôle peut voir. Même échelle que les documents."""
    from security.acces import niveaux_visibles
    return niveaux_visibles(role)


def catalogue(role: str | None = None) -> dict[str, tuple[str, list[str], list[str]]]:
    """Skills visibles par ce rôle : natifs d'abord, puis le registre en base.

    Sans `role`, seuls les skills ouverts à tous sont rendus. C'est volontaire :
    un appelant qui oublie de transmettre le rôle obtient la vue la PLUS
    restreinte, jamais la plus large.

    Les NATIFS ne sont pas filtrés : leur portée est déjà bornée par leur propre
    contrôle de droits, au moment d'agir (une boîte mail, une permission). Les
    masquer priverait un utilisateur légitime de la recherche documentaire.
    """
    visibles = _niveaux_visibles(role)
    externes = {nom: valeur[:3] for nom, valeur in _EXTERNES.items()
                if valeur[3] in visibles}
    return {**externes, **CATALOGUE_AGENT1}




async def rafraichir_catalogue(force: bool = False) -> int:
    """Recharge les skills exécutables du registre. Ne lève jamais.

    Seuls les skills VALIDÉS et activés sont exposés : un brouillon ne doit pas
    apparaître au modèle comme une capacité disponible. Leur effet reste
    déterminé par `effet_du_skill`, qui échoue en « externe » — donc validation
    humaine — tant qu'il n'est pas explicitement déclaré.
    """
    global _EXTERNES, _EXTERNES_EXPIRE
    import time

    if not force and time.monotonic() < _EXTERNES_EXPIRE:
        return len(_EXTERNES)
    _EXTERNES_EXPIRE = time.monotonic() + DUREE_CACHE_CATALOGUE_S

    try:
        from database.connection import get_db
        async with get_db() as conn:
            lignes = await conn.fetch(
                "SELECT name, description, COALESCE(access_level, 'all') AS access_level "
                "FROM skills "
                "WHERE status IN ('validated', 'stable') AND COALESCE(enabled, true) "
                "  AND (agent IS NULL OR agent = 'agent1') "
                "ORDER BY name")
    except Exception as e:  # noqa: BLE001 - un registre injoignable n'empêche pas de répondre
        logger.info("Registre de skills indisponible (%s) — seuls les natifs sont exposés", e)
        return len(_EXTERNES)

    # La table ne décrit pas les paramètres attendus : on n'en invente aucun.
    # C'est l'exécuteur qui validera au moment de l'appel.
    _EXTERNES = {r["name"]: ((r["description"] or "skill interne").strip()[:160], [], [],
                             r["access_level"])
                 for r in lignes if r["name"] not in CATALOGUE_AGENT1}
    logger.debug("Catalogue de skills : %d natifs + %d en base",
                 len(CATALOGUE_AGENT1), len(_EXTERNES))
    return len(_EXTERNES)


def instruction_actions(role: str | None = None) -> str:
    """Bloc à ajouter au prompt système. Constant : le préfixe reste stable, donc
    le cache de prompt du fournisseur continue de s'appliquer."""
    lignes = []
    for nom, (desc, requis, optionnels) in catalogue(role).items():
        params = ", ".join([f"{p}*" for p in requis] + list(optionnels)) or "aucun"
        lignes.append(f'- {nom} : {desc}. Paramètres ({params}) — * = obligatoire.')
    return (
        "\n\nACTIONS. Tu peux EXÉCUTER une action, et pas seulement répondre. Pour cela, "
        "termine ta réponse par un bloc balisé ```action contenant "
        '{"skill":"<nom>","args":{...}} puis ARRÊTE-toi : le résultat te sera fourni et '
        "tu pourras alors rédiger ta réponse finale.\n"
        "Règles : UNE seule action par réponse ; uniquement un skill de la liste ; "
        "si aucune action n'est nécessaire, réponds normalement SANS bloc. "
        "Les balises masquées ([PER_1], [MONTANT_2]...) sont acceptées dans les paramètres. "
        "Quand une boîte mail est demandée et que l'utilisateur n'en précise pas, "
        "omets le paramètre : la sienne sera utilisée.\n"
        "PARLER D'UNE ACTION N'EST PAS L'EXÉCUTER. Si l'on te demande ce que tu sais "
        "faire, quelles actions tu as, à quoi sert l'une d'elles ou ce qu'elle "
        "contient, réponds AVEC DES MOTS et n'émets AUCUN bloc : décrire un outil "
        "ne consiste pas à s'en servir.\n"
        "N'invente jamais les paramètres d'une action. S'il te manque une information "
        "indispensable (le destinataire, la référence d'un devis, le contexte), "
        "DEMANDE-LA au lieu de lancer l'action avec une valeur plausible.\n"
        "Skills disponibles :\n" + "\n".join(lignes) +
        # L'exemple porte volontairement sur l'action SANS EFFET (une recherche) :
        # des modèles modestes recopient l'exemple mot pour mot et l'exécutent tel
        # quel. Observé en production avec l'ancien exemple : un brouillon de mail
        # a réellement été produit pour « contact@exemple.fr » et un « devis DEV-17 »
        # qui n'existent pas, puis présenté à l'utilisateur comme un vrai résultat.
        # Si celui-ci est recopié, il ne fait qu'une recherche : sans conséquence.
        '\nExemple de FORME (ne reprends jamais ces valeurs, elles sont fictives) :'
        '\n```action\n{"skill":"rechercher_documents",'
        '"args":{"requete":"<ce que tu cherches>"}}\n```'
    )


def extraire_action(texte: str, role: str | None = None) -> tuple[Optional[dict], str, Optional[str]]:
    """Extrait l'action d'une réponse LLM.

    Retourne `(action, texte_sans_bloc, erreur)` :
      * `action` = {"skill", "args"} si le bloc est valide ;
      * `texte_sans_bloc` = la réponse débarrassée du bloc, toujours exploitable ;
      * `erreur` = message destiné au modèle pour qu'il se corrige, sinon None.

    Ne lève jamais : un bloc mal formé est une erreur de rédaction du modèle, pas
    une panne du service.
    """
    trouve = BLOC_ACTION_RE.search(texte or "")
    if not trouve:
        # Pas de bloc balisé : le modèle a-t-il utilisé sa syntaxe native ?
        return _action_native(texte or "", role)

    reste = ((texte[:trouve.start()] + texte[trouve.end():]) or "").strip()

    try:
        data = json.loads(trouve.group(1).strip())
    except json.JSONDecodeError as e:
        return None, reste, f"bloc action illisible ({e}) — réécris un JSON valide"

    if not isinstance(data, dict):
        return None, reste, "le bloc action doit contenir un objet JSON"

    skill = data.get("skill")
    if skill not in catalogue(role):
        return None, reste, (f"skill inconnu : {skill}. "
                             f"Choisis parmi : {', '.join(catalogue(role))}")

    args = data.get("args")
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return None, reste, "« args » doit être un objet JSON"

    requis = catalogue(role)[skill][1]
    manquants = [p for p in requis if not str(args.get(p) or "").strip()]
    if manquants:
        return None, reste, (f"paramètres obligatoires manquants pour {skill} : "
                             f"{', '.join(manquants)}")

    return {"skill": skill, "args": args}, reste, None
