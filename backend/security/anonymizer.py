"""
Module d'ANONYMISATION NER — conformité RGPD, zéro PII vers les API LLM.

Objectif : masquer toute donnée personnelle ou sensible (noms, lieux,
organisations, montants, SIRET/SIREN, e-mails, téléphones, IBAN...) AVANT
tout envoi vers une API LLM externe (OpenAI, Groq, Anthropic...), puis
réinjecter les vraies valeurs dans la réponse renvoyée à l'utilisateur.

Deux niveaux de détection :
  1. spaCy `fr_core_news_md` (optionnel, chargé une seule fois en lazy) pour
     la reconnaissance d'entités nommées : PER, LOC, ORG, MISC.
  2. Regex métier robustes (toujours actives, indépendantes de spaCy) pour
     les patterns structurés : montants €, SIRET, SIREN, e-mails,
     téléphones FR, IBAN FR.

DÉGRADATION PROPRE : si spaCy ou le modèle est absent, le module bascule en
mode « regex-only » sans jamais planter l'application. La propriété
`spacy_available` indique l'état réel du moteur NER.

Autonome : ne dépend que de la stdlib (`re`, `threading`) et de spaCy
(optionnel).
"""
from __future__ import annotations

import re
import threading
from typing import Optional

# ---------------------------------------------------------------------------
# Import optionnel de spaCy — ne jamais planter si absent.
# ---------------------------------------------------------------------------
try:  # pragma: no cover - dépend de l'environnement d'exécution
    import spacy  # type: ignore

    _SPACY_IMPORTED = True
except Exception:  # noqa: BLE001 - import volontairement défensif
    spacy = None  # type: ignore
    _SPACY_IMPORTED = False


# Modèles spaCy français. On charge le premier disponible : `md` (bon compromis
# précision/vitesse pour le NER) → `sm` (le plus léger) → `lg` (précis mais lourd et
# lent, dernier recours). Le regex métier couvre déjà email/tél/IBAN/SIRET/montants.
_SPACY_MODEL_NAMES = ("fr_core_news_md", "fr_core_news_sm", "fr_core_news_lg")

# Correspondance label spaCy -> préfixe de placeholder typé.
# MISC volontairement EXCLU : ce label « divers » (salutations, produits, nationalités,
# événements…) n'est PAS une donnée personnelle et sur-masquait le langage courant
# (« bonjour » → [MISC_1] → le modèle recevait un jeton vide de sens). On ne masque
# que les vraies PII : personnes / lieux / organisations (+ regex montants, email, tel, IBAN).
_SPACY_LABEL_TO_TYPE = {
    "PER": "PER",
    "LOC": "LOC",
    "ORG": "ORG",
}


# ---------------------------------------------------------------------------
# Regex métier (compilées une fois au chargement du module).
# L'ordre d'application compte : on masque d'abord les patterns les plus
# spécifiques (IBAN, SIRET, SIREN) pour éviter qu'un pattern plus large
# (montant, téléphone) ne « mange » une partie d'une entité structurée.
# ---------------------------------------------------------------------------

# IBAN français : FR + 2 chiffres de contrôle + 23 caractères alphanumériques,
# espaces tolérés (souvent groupés par 4).
_RE_IBAN = re.compile(
    r"\bFR\d{2}(?:[ ]?[A-Z0-9]){23}\b",
    re.IGNORECASE,
)

# SIRET : 14 chiffres, espaces tolérés (souvent groupés 3 3 3 5).
_RE_SIRET = re.compile(
    r"\b\d{3}[ ]?\d{3}[ ]?\d{3}[ ]?\d{5}\b",
)

# SIREN : 9 chiffres, espaces tolérés (souvent groupés 3 3 3).
_RE_SIREN = re.compile(
    r"\b\d{3}[ ]?\d{3}[ ]?\d{3}\b",
)

# E-mail.
_RE_EMAIL = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
)

# Téléphone FR : format national (0X suivi de 9 chiffres, séparateurs
# espace/point/tiret tolérés) ou international (+33 / 0033).
_RE_TEL = re.compile(
    r"(?<![\w])(?:(?:\+33|0033)[ .\-]?[1-9]|0[1-9])(?:[ .\-]?\d{2}){4}(?![\w])",
)

# Montant en euros : partie entière avec séparateurs de milliers (espace
# normal, espace insécable ou point), décimales optionnelles (virgule ou
# point), suivie de € / EUR / euro(s).
_RE_MONTANT = re.compile(
    r"\b\d{1,3}(?:[  .]?\d{3})*(?:[.,]\d{1,2})?[  ]?"
    # NB : pas de `\b` final — « € » n'étant pas un caractère de mot, `\b`
    # échouerait dès qu'un montant se termine par « € » (cas le plus fréquent
    # en France). Le lookahead négatif exclut seulement une lettre accolée
    # (évite de tronquer « EUR » dans « EURO ») tout en acceptant « € » suivi
    # d'un espace, d'une ponctuation ou d'une fin de chaîne.
    r"(?:€|EUR|euros?)(?![A-Za-z])",
    re.IGNORECASE,
)

# Ordre d'application des regex : (type, pattern). Le plus spécifique d'abord.
_REGEX_PIPELINE: list[tuple[str, re.Pattern]] = [
    ("IBAN", _RE_IBAN),
    ("EMAIL", _RE_EMAIL),
    ("MONTANT", _RE_MONTANT),
    ("SIRET", _RE_SIRET),
    ("SIREN", _RE_SIREN),
    ("TEL", _RE_TEL),
]


class _Anonymizer:
    """
    Moteur d'anonymisation réversible.

    Chaque valeur détectée est remplacée par un placeholder typé et numéroté
    (`[PER_1]`, `[MONTANT_2]`...). Une même valeur reçoit toujours le même
    placeholder au sein d'un même `entity_map`, garantissant la cohérence.

    Le chargement du modèle spaCy est paresseux (lazy) et protégé par un
    verrou : il n'a lieu qu'au premier appel réel à `anonymize`, une seule
    fois pour toute la durée de vie du processus.
    """

    def __init__(self) -> None:
        # Modèle spaCy chargé (ou None si indisponible / non encore tenté).
        self._nlp = None
        # État : None = pas encore tenté, True/False = résultat du chargement.
        self._spacy_ready: Optional[bool] = None
        # Verrou pour un chargement thread-safe du modèle.
        self._load_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Chargement lazy du modèle spaCy.
    # ------------------------------------------------------------------
    def _ensure_model(self) -> None:
        """
        Charge le modèle spaCy `fr_core_news_md` au premier besoin.

        Idempotent et thread-safe. En cas d'échec (spaCy ou modèle absent),
        bascule silencieusement en mode regex-only : `_spacy_ready` passe à
        False et aucune exception ne remonte.
        """
        if self._spacy_ready is not None:
            return

        with self._load_lock:
            # Double vérification après acquisition du verrou.
            if self._spacy_ready is not None:
                return

            if not _SPACY_IMPORTED or spacy is None:
                self._spacy_ready = False
                return

            # Essaie chaque modèle dans l'ordre de préférence ; garde le premier chargé.
            for model_name in _SPACY_MODEL_NAMES:
                try:
                    self._nlp = spacy.load(
                        model_name,
                        # On ne garde que le NER : plus léger et suffisant.
                        disable=["tagger", "parser", "lemmatizer", "attribute_ruler"],
                    )
                    self._spacy_ready = True
                    return
                except Exception:  # noqa: BLE001 - modèle absent, on tente le suivant
                    continue

            # Aucun modèle disponible -> mode regex-only.
            self._nlp = None
            self._spacy_ready = False

    @property
    def spacy_available(self) -> bool:
        """
        Indique si le moteur NER spaCy est réellement opérationnel.

        Déclenche le chargement lazy si nécessaire. Retourne False dès lors
        que spaCy ou le modèle `fr_core_news_md` est indisponible (mode
        regex-only).
        """
        self._ensure_model()
        return bool(self._spacy_ready)

    # ------------------------------------------------------------------
    # Attribution des placeholders.
    # ------------------------------------------------------------------
    @staticmethod
    def _reverse_lookup(entity_map: dict, value: str) -> Optional[str]:
        """Retourne le placeholder déjà associé à `value`, sinon None."""
        for placeholder, original in entity_map.items():
            if original == value:
                return placeholder
        return None

    def _placeholder_for(
        self,
        value: str,
        type_prefix: str,
        entity_map: dict,
        counters: dict,
    ) -> str:
        """
        Retourne le placeholder à utiliser pour `value`.

        Réutilise le placeholder existant si la valeur a déjà été rencontrée
        (cohérence intra-`entity_map`), sinon en crée un nouveau numéroté et
        met à jour `entity_map` et les compteurs par type.
        """
        existing = self._reverse_lookup(entity_map, value)
        if existing is not None:
            return existing

        counters[type_prefix] = counters.get(type_prefix, 0) + 1
        placeholder = f"[{type_prefix}_{counters[type_prefix]}]"
        entity_map[placeholder] = value
        return placeholder

    def _sync_counters(self, entity_map: dict) -> dict:
        """
        Reconstruit les compteurs par type à partir d'un `entity_map` existant.

        Permet de poursuivre la numérotation sans collision lorsqu'on partage
        un même `entity_map` sur plusieurs textes (cf. `anonymize_chunks`).
        """
        counters: dict = {}
        pattern = re.compile(r"^\[([A-Z]+)_(\d+)\]$")
        for placeholder in entity_map:
            match = pattern.match(placeholder)
            if not match:
                continue
            type_prefix, num = match.group(1), int(match.group(2))
            if num > counters.get(type_prefix, 0):
                counters[type_prefix] = num
        return counters

    # ------------------------------------------------------------------
    # Étapes de masquage.
    # ------------------------------------------------------------------
    def _apply_regex(self, text: str, entity_map: dict, counters: dict) -> str:
        """
        Applique successivement les regex métier sur `text`.

        Les entités déjà masquées (placeholders) sont ignorées par les regex
        car elles ne correspondent à aucun des patterns (chiffres, @, €...).
        Retourne le texte partiellement masqué.
        """
        for type_prefix, pattern in _REGEX_PIPELINE:

            def _replace(match: re.Match) -> str:
                value = match.group(0)
                return self._placeholder_for(value, type_prefix, entity_map, counters)

            text = pattern.sub(_replace, text)
        return text

    def _apply_spacy(self, text: str, entity_map: dict, counters: dict) -> str:
        """
        Applique la reconnaissance d'entités nommées spaCy sur `text`.

        Ne traite que les labels PER, LOC, ORG, MISC. Les remplacements se
        font de droite à gauche (par offsets décroissants) afin de préserver
        la validité des positions pendant la substitution. No-op si spaCy est
        indisponible.
        """
        if not self.spacy_available or self._nlp is None:
            return text

        try:
            doc = self._nlp(text)
        except Exception:  # noqa: BLE001 - jamais planter sur une analyse
            return text

        # On collecte les entités pertinentes, triées par position décroissante.
        spans = [
            (ent.start_char, ent.end_char, ent.text, ent.label_)
            for ent in doc.ents
            if ent.label_ in _SPACY_LABEL_TO_TYPE
        ]
        spans.sort(key=lambda s: s[0], reverse=True)

        for start, end, value, label in spans:
            # On ne remasque pas un fragment déjà transformé en placeholder.
            if value.startswith("[") and value.endswith("]"):
                continue
            type_prefix = _SPACY_LABEL_TO_TYPE[label]
            placeholder = self._placeholder_for(value, type_prefix, entity_map, counters)
            text = text[:start] + placeholder + text[end:]

        return text

    # ------------------------------------------------------------------
    # API publique.
    # ------------------------------------------------------------------
    def anonymize(self, text: str) -> tuple[str, dict]:
        """
        Anonymise `text` et retourne `(texte_masqué, entity_map)`.

        Pipeline : entités spaCy (si disponibles) PUIS regex métier. Le
        `entity_map` retourné mappe chaque placeholder vers sa valeur
        originale et permet la réhydratation ultérieure via `rehydrate`.

        Ne lève jamais d'exception : en cas d'entrée invalide (None, non-str)
        ou d'indisponibilité de spaCy, retourne au minimum le texte tel quel
        avec un `entity_map` vide.
        """
        if not text or not isinstance(text, str):
            return (text if isinstance(text, str) else "", {})

        entity_map: dict = {}
        counters: dict = {}

        # spaCy D'ABORD (noms/lieux/organisations) PUIS regex (email/SIRET/IBAN/tel/
        # montant). Cet ordre est volontaire : il évite que spaCy ne re-tague le
        # contenu interne des placeholders regex (ex. « MONTANT_1 » vu comme un nom),
        # ce qui casserait la réhydratation par double-masquage.
        masked = self._apply_spacy(text, entity_map, counters)
        masked = self._apply_regex(masked, entity_map, counters)
        return masked, entity_map

    def anonymize_chunks(self, chunks: list[str]) -> tuple[list[str], dict]:
        """
        Anonymise une liste de textes en PARTAGEANT un même `entity_map`.

        Garantit qu'une même valeur reçoit le même placeholder à travers tous
        les chunks (numérotation continue, sans collision). Retourne la liste
        des textes masqués et l'`entity_map` global.
        """
        entity_map: dict = {}
        counters: dict = {}
        masked_chunks: list[str] = []

        for chunk in chunks:
            if not chunk or not isinstance(chunk, str):
                masked_chunks.append(chunk if isinstance(chunk, str) else "")
                continue
            masked = self._apply_spacy(chunk, entity_map, counters)
            masked = self._apply_regex(masked, entity_map, counters)
            masked_chunks.append(masked)

        return masked_chunks, entity_map

    def rehydrate(self, text: str, entity_map: dict) -> str:
        """
        Réinjecte les vraies valeurs dans `text` à partir de `entity_map`.

        Remplace chaque placeholder présent dans `entity_map` par sa valeur
        originale. Le remplacement s'effectue du placeholder le PLUS LONG au
        plus court afin d'éviter les collisions de préfixe (ex. `[PER_10]`
        doit être traité avant `[PER_1]`).

        Ne lève jamais d'exception : entrée invalide ou map vide -> texte
        renvoyé inchangé.
        """
        if not text or not isinstance(text, str) or not entity_map:
            return text if isinstance(text, str) else ""

        # Tri des placeholders par longueur décroissante (puis ordre stable),
        # pour que les placeholders englobants soient traités en premier.
        placeholders = sorted(entity_map.keys(), key=len, reverse=True)
        for placeholder in placeholders:
            text = text.replace(placeholder, str(entity_map[placeholder]))
        return text


# Singleton exposé au reste de l'application.
anonymizer = _Anonymizer()
