"""
Skills au format Markdown — import et export.

Un skill vit dans la base, mais s'écrit et se relit bien plus facilement dans un
fichier : on le versionne, on le passe à un collègue, on l'édite dans son
éditeur, on le rejoue sur une autre instance.

AUCUNE STRUCTURE N'EST IMPOSÉE À L'IMPORT. Un fichier écrit à la main, exporté
d'un autre outil ou tiré de simples notes entre tel quel : ce qui n'est pas
déclaré est déduit du document (le titre donne le nom, le premier paragraphe la
description, le tout la consigne). Le format ci-dessous est celui de l'EXPORT,
et la façon la plus précise de décrire un skill — pas un passage obligé.

Le format d'export tient en trois parties :

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
import unicodedata

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


def _slug(texte: str) -> str:
    """Transforme un titre libre en nom de skill valide.

    « Analyse d'un CCTP (v2) » -> « analyse_d_un_cctp_v2 »
    """
    sans_accent = "".join(
        c for c in unicodedata.normalize("NFKD", texte or "")
        if not unicodedata.combining(c))
    brut = re.sub(r"[^a-z0-9]+", "_", sans_accent.lower()).strip("_")
    brut = re.sub(r"_+", "_", brut)
    if brut and not brut[0].isalpha():
        brut = "skill_" + brut
    return brut[:64]


def _lire_entete(texte: str) -> tuple[dict, str]:
    """En-tête si présent, sinon dictionnaire vide et texte inchangé.

    L'en-tête n'est PAS obligatoire : un fichier écrit à la main, ou produit
    ailleurs, doit pouvoir être importé tel quel. Ce qui manque est déduit du
    document lui-même.
    """
    trouve = _RE_ENTETE.search(texte)
    if not trouve:
        return {}, texte
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


def _titre_h1(corps: str) -> str:
    trouve = re.search(r"^#\s+(.+)$", corps, re.M)
    return trouve.group(1).strip() if trouve else ""


def _premier_paragraphe(corps: str) -> str:
    """Première vraie phrase du document : titres, listes et code exclus."""
    for bloc in re.split(r"\n\s*\n", re.sub(r"```.*?```", "", corps, flags=re.S)):
        ligne = bloc.strip()
        if not ligne or ligne.startswith(("#", "-", "*", ">", "|", "```")):
            continue
        return " ".join(ligne.split())
    return ""


def depuis_markdown(texte: str, nom_fichier: str | None = None) -> dict:
    """Analyse un Markdown QUELCONQUE et renvoie un skill prêt à insérer.

    Aucune structure n'est imposée : un fichier écrit à la main, exporté d'un
    autre outil ou pris dans des notes doit pouvoir entrer tel quel. Ce qui
    n'est pas déclaré est DÉDUIT, dans cet ordre :

      nom          en-tête `name:`, sinon titre de niveau 1, sinon nom du fichier
      description  en-tête `description:`, sinon premier paragraphe
      consigne     section « ## Rôle » si elle existe, sinon TOUT le document
      code         bloc ```python exposant `def run(...)`, sinon aucun

    Un skill sans code reste parfaitement utile : sa consigne documente une
    manière de faire. Il ne devient exécutable que si quelqu'un lui écrit un
    `run()` et le valide.

    Ne renvoie NI statut NI activation : l'appelant impose « draft » et
    désactivé. Ne lève que si RIEN d'exploitable ne peut être tiré du fichier.
    """
    entete, corps = _lire_entete(texte or "")

    # ── Nom : déclaré, sinon titre, sinon nom de fichier ──────────────
    declare = (entete.get("name") or "").strip()
    nom = _slug(declare) if declare else ""
    if not nom:
        nom = _slug(_titre_h1(corps))
    if not nom and nom_fichier:
        nom = _slug(re.sub(r"\.mdx?$", "", nom_fichier, flags=re.I))
    if not _RE_NOM.match(nom or ""):
        raise MarkdownInvalide(
            "Impossible de nommer ce skill : ajoutez « name: » dans un en-tête, "
            "un titre « # Mon skill », ou donnez au fichier un nom explicite.")

    # ── Consigne : la section dédiée, sinon le document entier ────────
    role = (_lire_section(corps, "Rôle") or _lire_section(corps, "Role")
            or corps.strip())

    # ── Code : seulement s'il expose bien un point d'entrée ───────────
    section_code = _lire_section(corps, "Code")
    if section_code:
        # Section « ## Code » explicite : on est exigeant, l'intention est claire.
        trouve = _RE_CODE.search(section_code)
        code = trouve.group(1).strip() if trouve else ""
        if code and "def run(" not in code:
            raise MarkdownInvalide(
                "La section « ## Code » doit exposer « def run(data: dict) -> dict ».")
    else:
        # Document libre : un bloc python n'est adopté comme code que s'il
        # ressemble vraiment à un skill. Sinon c'est un exemple dans la prose,
        # et le rejeter reviendrait à refuser le fichier pour rien.
        code = next((b.strip() for b in _RE_CODE.findall(corps) if "def run(" in b), "")

    if not role.strip() and not code:
        raise MarkdownInvalide("Fichier vide : ni texte ni code exploitable.")

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
        "description": ((entete.get("description") or "").strip()
                        or _premier_paragraphe(corps))[:500],
        "agent": agent,
        "category": (entete.get("category") or "").strip()[:50] or None,
        "effect": effet,
        "prompt_template": role,
        "code": code,
    }
