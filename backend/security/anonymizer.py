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
import unicodedata
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
# GARDE-FOU ANTI FAUX-POSITIFS NER.
#
# Mesuré sur fr_core_news_md/sm 3.7.0 : les modèles étiquettent massivement en
# PER/LOC/ORG le vocabulaire calendaire et métier CAPITALISÉ —
#   « Mars » -> LOC, « kEUR » -> PER, « CA » -> ORG,
#   « Jan 42 kEUR » -> PER (le nombre est avalé dans le span !).
# Masquer ces spans détruit l'association libellé <-> valeur : le LLM reçoit
# « [LOC_1] 35 » au lieu de « Mars 35 », ne peut plus lire la série, et la
# réhydratation produit des phrases absurdes (« la valeur pour Mars n'est pas
# précisée »). Ce vocabulaire n'est PAS une donnée personnelle : on le laisse
# en clair. Règle de sûreté : un SEUL mot inconnu dans le span suffit à
# conserver le masquage (« Avril » passe, « Avril Dupont » reste masqué).
_NON_PII_WORDS = frozenset({
    # Mois — formes longues et abrégées.
    "janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet",
    "aout", "septembre", "octobre", "novembre", "decembre",
    "jan", "janv", "fev", "fevr", "avr", "jui", "juil",
    "sep", "sept", "oct", "nov", "dec",
    # Jours.
    "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche",
    # Périodes.
    "jour", "jours", "semaine", "semaines", "mois", "trimestre", "semestre",
    "annee", "annees", "exercice", "t1", "t2", "t3", "t4", "s1", "s2",
    # Unités et devises.
    "eur", "euro", "euros", "keur", "keuros", "meur", "usd",
    "ht", "ttc", "tva", "kg", "tonne", "tonnes", "ml", "km", "cm", "mm", "m2", "m3",
    "unite", "unites", "heure", "heures", "qte",
    # Vocabulaire métier NON nominatif. Règle d'or : ne JAMAIS y mettre un mot
    # qui peut être un patronyme (« Boulanger », « Charpentier », « Mercier »,
    # « Meunier », « Fournier »... sont des noms de famille courants).
    "ca", "chiffre", "affaires", "total", "sous", "montant", "montants",
    "quantite", "quantites", "prix", "tarif", "devis", "facture", "factures",
    "situation", "situations", "commande", "commandes", "chantier",
    "chantiers", "lot", "lots", "acompte", "solde", "reserve", "reserves",
    "planning", "graphique", "tableau", "budget", "marge", "poste", "postes",
    # Connecteurs happés dans les spans multi-mots (« chantier de Mars »).
    "de", "du", "des", "le", "la", "les", "l", "et", "en", "au", "aux", "a",
})

# Séquences purement alphabétiques (accents inclus, chiffres et « _ » exclus).
_RE_WORDS = re.compile(r"[^\W\d_]+", re.UNICODE)

# Placeholder déjà posé par une passe précédente : ne jamais le re-masquer.
_RE_PLACEHOLDER = re.compile(r"\[[A-Z]+_\d+\]")


def _normalize_word(word: str) -> str:
    """Minuscule + suppression des accents (« Février » -> « fevrier »)."""
    decomposed = unicodedata.normalize("NFD", word.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _shrink_to_letters(value: str, start: int, end: int) -> tuple[str, int, int]:
    """
    Rétrécit un span spaCy aux bornes de sa partie alphabétique.

    spaCy agrège très souvent le nombre voisin d'un nom propre (« Dupont 42 »
    étiqueté PER d'un seul tenant, mesuré). Masquer le span entier effacerait
    la VALEUR en plus du nom : le LLM perdrait la donnée chiffrée. On ne masque
    donc que la portion porteuse de lettres.

    Ne réduit JAMAIS la couverture d'un patronyme : on ne rogne que sur un
    séparateur (espace/ponctuation). Couper au milieu d'un token collé
    ré-exposerait une portion sensible — « FR76 » (préfixe IBAN) reste entier.
    """
    left, right = 0, len(value)
    while left < right and not value[left].isalpha():
        left += 1
    while right > left and not value[right - 1].isalpha():
        right -= 1
    if left >= right:  # span sans aucune lettre -> laissé aux regex métier
        return value, start, end
    if left > 0 and value[left - 1].isalnum():
        left = 0
    if right < len(value) and value[right].isalnum():
        right = len(value)
    if left == 0 and right == len(value):
        return value, start, end
    return value[left:right], start + left, start + right


def _is_non_pii_span(value: str) -> bool:
    """
    True si le span ne peut pas porter de donnée personnelle.

    Deux cas :
      * aucun caractère alphabétique (chiffres seuls) — la détection est alors
        assurée par les regex métier (IBAN/SIRET/SIREN/TEL/MONTANT) exécutées
        juste après, donc aucune fuite ;
      * TOUS les mots du span appartiennent au vocabulaire non-PII.
    """
    words = _RE_WORDS.findall(value)
    if not words:
        return True
    return all(_normalize_word(w) in _NON_PII_WORDS for w in words)


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

# SIRET : 14 chiffres collés, ou groupés 3-3-3-5 (forme imprimée classique).
_RE_SIRET = re.compile(
    r"(?<!\d)(?:\d{14}|\d{3} \d{3} \d{3} \d{5})(?!\d)",
)

# SIREN : 9 chiffres COLLÉS, ou groupés 3-3-3 UNIQUEMENT s'ils sont annoncés par
# le mot-clé. L'ancienne forme « \b\d{3}[ ]?\d{3}[ ]?\d{3}\b » masquait n'importe
# quelle suite de trois nombres à 3 chiffres : « Lot 250 300 450 » -> « Lot
# [SIREN_1] », ce qui détruisait les tableaux de quantités des DPGF/métrés
# (mesuré). Un SIREN reste masqué sous sa forme compacte ou explicitement nommée.
_RE_SIREN = re.compile(
    r"(?<!\d)\d{9}(?!\d)"
    r"|(?:(?<=SIREN )|(?<=SIREN: )|(?<=SIREN : ))\d{3} ?\d{3} ?\d{3}(?!\d)",
    re.IGNORECASE,
)

# E-mail.
_RE_EMAIL = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
)

# Téléphone FR : format national (0X suivi de 9 chiffres, séparateurs
# espace/point/tiret tolérés) ou international (+33 / 0033).
# Le lookahead d'unité évite de masquer une série de mesures (« 05 12 30 45 60 mm »
# relevés d'un chantier) comme s'il s'agissait d'un numéro de téléphone.
_RE_TEL = re.compile(
    r"(?<![\w])(?:(?:\+33|0033)[ .\-]?[1-9]|0[1-9])(?:[ .\-]?\d{2}){4}"
    r"(?![\w])(?!\s*(?:mm|cm|m2|m3|ml|kg|km|t|u)\b)",
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

# Regex appliquées AVANT spaCy. IBAN et EMAIL sont strictement délimités (aucun
# faux positif possible) et doivent passer en premier : spaCy consommait
# « IBAN FR76 » comme une entité PER, ce qui empêchait ensuite _RE_IBAN de
# matcher — le reste du numéro partait EN CLAIR vers le LLM (fuite mesurée).
_REGEX_PRE: list[tuple[str, re.Pattern]] = [
    ("IBAN", _RE_IBAN),
    ("EMAIL", _RE_EMAIL),
]

# Regex appliquées APRÈS spaCy (patterns numériques : le NER doit voir le texte
# encore lisible pour délimiter correctement les noms propres).
_REGEX_POST: list[tuple[str, re.Pattern]] = [
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
    def _build_index(entity_map: dict) -> dict:
        """Index inverse valeur -> placeholder (évite un balayage par entité).

        Sans lui, la recherche est linéaire sur la map ; avec une map PERSISTÉE
        sur tout un fil de conversation, le coût deviendrait quadratique.
        """
        return {original: placeholder for placeholder, original in entity_map.items()}

    def _placeholder_for(
        self,
        value: str,
        type_prefix: str,
        entity_map: dict,
        counters: dict,
        index: Optional[dict] = None,
    ) -> str:
        """
        Retourne le placeholder à utiliser pour `value`.

        Réutilise le placeholder existant si la valeur a déjà été rencontrée
        (cohérence intra-`entity_map`, y compris entre plusieurs tours de
        conversation quand la map est partagée), sinon en crée un nouveau
        numéroté et met à jour `entity_map`, l'index inverse et les compteurs.
        """
        if index is None:
            index = self._build_index(entity_map)
        existing = index.get(value)
        if existing is not None:
            return existing

        counters[type_prefix] = counters.get(type_prefix, 0) + 1
        placeholder = f"[{type_prefix}_{counters[type_prefix]}]"
        entity_map[placeholder] = value
        index[value] = placeholder
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
    def _apply_regex(self, text: str, entity_map: dict, counters: dict,
                     pipeline: list, index: Optional[dict] = None) -> str:
        """
        Applique successivement les regex métier de `pipeline` sur `text`.

        Les entités déjà masquées (placeholders) sont ignorées par les regex
        car elles ne correspondent à aucun des patterns (chiffres, @, €...).
        Retourne le texte partiellement masqué.
        """
        for type_prefix, pattern in pipeline:

            def _replace(match: re.Match) -> str:
                value = match.group(0)
                return self._placeholder_for(value, type_prefix, entity_map, counters, index)

            text = pattern.sub(_replace, text)
        return text

    def _apply_spacy(self, text: str, entity_map: dict, counters: dict,
                     index: Optional[dict] = None) -> str:
        """
        Applique la reconnaissance d'entités nommées spaCy sur `text`.

        Ne traite que les labels PER, LOC, ORG. Trois garde-fous :
          * les spans chevauchant un placeholder déjà posé sont ignorés ;
          * chaque span est recadré sur sa partie alphabétique (spaCy avale le
            nombre voisin : « Dupont 42 » -> PER masquerait aussi la valeur) ;
          * le vocabulaire non-PII (mois, unités, métier) est laissé en clair.

        Les placeholders sont ATTRIBUÉS dans l'ordre de LECTURE puis appliqués
        de droite à gauche. L'ancienne version numérotait dans l'ordre inverse
        du texte : le premier nom cité recevait le plus grand numéro, si bien
        qu'un LLM supposant « [PER_1] = première personne citée » inversait
        systématiquement les données (comportement mesuré). No-op sans spaCy.
        """
        if not self.spacy_available or self._nlp is None:
            return text

        try:
            doc = self._nlp(text)
        except Exception:  # noqa: BLE001 - jamais planter sur une analyse
            return text

        # Zones déjà masquées : un span spaCy qui les recouvre ne doit pas être
        # re-remplacé (sinon double masquage et réhydratation cassée).
        masked_zones = [(m.start(), m.end()) for m in _RE_PLACEHOLDER.finditer(text)]

        spans = [
            (ent.start_char, ent.end_char, ent.text, ent.label_)
            for ent in doc.ents
            if ent.label_ in _SPACY_LABEL_TO_TYPE
        ]
        spans.sort(key=lambda s: s[0])  # ordre de lecture

        prepared: list[tuple[int, int, str]] = []
        for start, end, value, label in spans:
            if any(start < z_end and end > z_start for z_start, z_end in masked_zones):
                continue
            value, start, end = _shrink_to_letters(value, start, end)
            if _is_non_pii_span(value):
                continue
            placeholder = self._placeholder_for(
                value, _SPACY_LABEL_TO_TYPE[label], entity_map, counters, index
            )
            prepared.append((start, end, placeholder))

        # Remplacement de droite à gauche : préserve la validité des offsets.
        for start, end, placeholder in reversed(prepared):
            text = text[:start] + placeholder + text[end:]

        return text

    # ------------------------------------------------------------------
    # API publique.
    # ------------------------------------------------------------------
    def _mask_one(self, text: str, entity_map: dict, counters: dict, index: dict) -> str:
        """Pipeline complet sur un texte : regex strictes -> spaCy -> regex numériques."""
        masked = self._apply_regex(text, entity_map, counters, _REGEX_PRE, index)
        masked = self._apply_spacy(masked, entity_map, counters, index)
        return self._apply_regex(masked, entity_map, counters, _REGEX_POST, index)

    def anonymize(self, text: str, entity_map: Optional[dict] = None) -> tuple[str, dict]:
        """
        Anonymise `text` et retourne `(texte_masqué, entity_map)`.

        Pipeline : IBAN/e-mail (délimités, avant que spaCy ne les morde) PUIS
        entités spaCy PUIS regex numériques. Le `entity_map` retourné mappe
        chaque placeholder vers sa valeur originale et permet la réhydratation
        via `rehydrate`.

        `entity_map` en entrée (optionnel) permet de POURSUIVRE une numérotation
        existante : une même valeur conserve alors le même placeholder d'un
        appel à l'autre (indispensable pour un fil de conversation).

        Ne lève jamais d'exception : en cas d'entrée invalide (None, non-str)
        ou d'indisponibilité de spaCy, retourne au minimum le texte tel quel.
        """
        entity_map = dict(entity_map) if entity_map else {}
        if not text or not isinstance(text, str):
            return (text if isinstance(text, str) else "", entity_map)

        counters = self._sync_counters(entity_map)
        index = self._build_index(entity_map)
        return self._mask_one(text, entity_map, counters, index), entity_map

    def anonymize_chunks(self, chunks: list[str],
                         entity_map: Optional[dict] = None) -> tuple[list[str], dict]:
        """
        Anonymise une liste de textes en PARTAGEANT un même `entity_map`.

        Garantit qu'une même valeur reçoit le même placeholder à travers tous
        les chunks (numérotation continue, sans collision). Si `entity_map` est
        fourni, la numérotation REPREND à partir de lui : `[PER_1]` désigne
        alors la même personne sur toute la conversation, et la réhydratation
        reste exacte sur les tours antérieurs. Retourne la liste des textes
        masqués et l'`entity_map` global (entrée + nouvelles entités).
        """
        entity_map = dict(entity_map) if entity_map else {}
        counters = self._sync_counters(entity_map)
        index = self._build_index(entity_map)
        masked_chunks: list[str] = []

        for chunk in chunks:
            if not chunk or not isinstance(chunk, str):
                masked_chunks.append(chunk if isinstance(chunk, str) else "")
                continue
            masked_chunks.append(self._mask_one(chunk, entity_map, counters, index))

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
