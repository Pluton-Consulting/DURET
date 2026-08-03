"""
Skills au format Markdown — import et export.

Un skill vit dans la base, mais s'écrit et se relit bien plus facilement dans un
fichier : on le versionne, on le passe à un collègue, on l'édite dans son
éditeur, on le rejoue sur une autre instance.

Le format retenu tient en trois parties :

    ---
    name: analyse_cctp
    description: Analyse un CCTP et en extrait les postes
    agent: agent2
    category: appel_offres
    effect: lecture
    ---

    ## Rôle

    (le prompt_template : ce que le skill doit faire, en français)

    ## Code

    ```python
    def run(data: dict) -> dict:
        ...
    ```

RÈGLE DE SÉCURITÉ, non négociable : un skill importé arrive TOUJOURS en
`draft` et désactivé, quel que soit le statut écrit dans le fichier. Le code
importé sera exécuté un jour ; il doit passer par une relecture humaine. Un
fichier qui pourrait se déclarer « stable » ferait de cet import une porte
d'entrée pour du code arbitraire.
"""
from __future__ import annotations

import re

# Champs de l'en-tête que l'on accepte de lire. `status` et `enabled` en sont
# volontairement absents : ils ne se décrètent pas depuis un fichier.
CHAMPS_ENTETE = ("name", "description", "agent", "category", "effect")
EFFETS_VALIDES = ("lecture", "ecriture_interne", "externe")
AGENTS_VALIDES = ("agent1", "agent2", "agent3")

_RE_NOM = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
_RE_ENTETE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
_RE_CODE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.S)


class MarkdownInvalide(ValueError):
    """Le fichier ne décrit pas un skill exploitable."""


def vers_markdown(skill: dict) -> str:
    """Sérialise un skill de la base en Markdown."""
    entete = [f"name: {skill.get('name', '')}"]
    for champ in ("description", "agent", "category", "effect"):
        valeur = (skill.get(champ) or "").strip() if skill.get(champ) else ""
        if valeur:
            # Une description multiligne casserait l'en-tête : on l'aplatit.
            entete.append(f"{champ}: {' '.join(valeur.splitlines())}")

    # Le statut est EXPORTÉ pour information, en commentaire : il documente
    # l'état d'origine sans pouvoir être réimporté tel quel.
    statut = skill.get("status") or "draft"
    role = (skill.get("prompt_template") or "").strip()
    code = (skill.get("code") or "").strip()

    parties = ["---", "\n".join(entete), "---", "",
               f"<!-- statut a l'export : {statut} (un import repart toujours en brouillon) -->",
               "", "## Rôle", "",
               role or "_(aucune consigne enregistrée)_", "", "## Code", ""]
    if code:
        parties += ["```python", code, "```"]
    else:
        # Un skill natif n'a pas de code en base : il est implémenté dans
        # l'application. Le dire explicitement évite de croire à une perte.
        parties += ["_(skill natif : la logique est implémentée dans le backend, "
                    "il n'y a pas de code en base)_"]
    return "\n".join(parties) + "\n"


def _lire_entete(texte: str) -> tuple[dict, str]:
    trouve = _RE_ENTETE.search(texte)
    if not trouve:
        raise MarkdownInvalide(
            "En-tête absent : le fichier doit commencer par un bloc « --- » "
            "contenant au moins « name: ».")
    entete = {}
    for ligne in trouve.group(1).splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or ":" not in ligne:
            continue
        cle, _, valeur = ligne.partition(":")
        cle = cle.strip().lower()
        if cle in CHAMPS_ENTETE:
            entete[cle] = valeur.strip()
    return entete, texte[trouve.end():]


def _lire_section(corps: str, titre: str) -> str:
    """Contenu d'une section « ## titre », jusqu'au prochain titre de même niveau."""
    motif = re.compile(rf"^##\s+{re.escape(titre)}\s*$(.*?)(?=^##\s|\Z)",
                       re.S | re.M | re.I)
    trouve = motif.search(corps)
    return trouve.group(1).strip() if trouve else ""


def depuis_markdown(texte: str) -> dict:
    """Analyse un fichier Markdown et renvoie un skill prêt à insérer.

    Ne renvoie NI statut NI activation : l'appelant impose « draft » et
    désactivé. Lève `MarkdownInvalide` si le fichier n'est pas exploitable.
    """
    entete, corps = _lire_entete(texte or "")

    nom = (entete.get("name") or "").strip().lower().replace(" ", "_")
    if not _RE_NOM.match(nom):
        raise MarkdownInvalide(
            f"Nom invalide : « {entete.get('name', '')} ». Attendu : minuscules, "
            "chiffres et tirets bas, 3 à 64 caractères, commençant par une lettre.")

    role = _lire_section(corps, "Rôle") or _lire_section(corps, "Role")
    section_code = _lire_section(corps, "Code")
    trouve = _RE_CODE.search(section_code) or _RE_CODE.search(corps)
    code = trouve.group(1).strip() if trouve else ""

    if not code and not role:
        raise MarkdownInvalide(
            "Ni consigne ni code : le fichier doit contenir une section « ## Rôle » "
            "ou une section « ## Code » avec un bloc python.")
    if code and "def run(" not in code:
        raise MarkdownInvalide(
            "Le code doit exposer une fonction « def run(data: dict) -> dict ».")

    agent = entete.get("agent", "").strip() or None
    if agent and agent not in AGENTS_VALIDES:
        raise MarkdownInvalide(
            f"Agent inconnu : « {agent} ». Attendu : {', '.join(AGENTS_VALIDES)}.")

    # Effet FAIL-CLOSED : un effet absent ou fantaisiste devient « externe »,
    # donc soumis à validation humaine à chaque exécution.
    effet = entete.get("effect", "").strip()
    if effet not in EFFETS_VALIDES:
        effet = "externe"

    return {
        "name": nom,
        "description": (entete.get("description") or "").strip()[:500],
        "agent": agent,
        "category": (entete.get("category") or "").strip()[:50] or None,
        "effect": effet,
        "prompt_template": role,
        "code": code,
    }
