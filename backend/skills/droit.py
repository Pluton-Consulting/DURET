"""
Skills `texte_de_loi` et `jurisprudence` — le droit officiel, cité avec sa source.

POURQUOI DEUX GESTES DÉDIÉS. Une entreprise de sols se heurte chaque semaine au
droit : garanties décennale et biennale (Code civil, art. 1792 et suivants),
retards de paiement et pénalités (Code de commerce, Code de la commande
publique), sous-traitance, réserves à la réception, CCAG-Travaux, droit du
travail et conventions collectives du bâtiment. Répondu « de mémoire » par un
modèle, ou recopié du web, un article peut être périmé — et une réponse fausse
sur un délai de garantie coûte cher. Ces deux gestes vont chercher la source
OFFICIELLE (Légifrance pour les textes, Judilibre pour la jurisprudence de la
Cour de cassation et des cours d'appel) et rendent de quoi la CITER : numéro,
date de version, lien.

CE QUE LE RÉSULTAT IMPOSE AU MODÈLE (`a_faire`) : citer l'article ou la décision
avec son lien, dire la date de version, et rappeler que ce n'est pas un conseil
juridique — l'assistant informe, il ne remplace pas un avocat.

TAILLE. Le résultat d'un skill est tronqué vers 4 000 caractères : un article
long (certains font dix pages) est rendu par MORCEAUX coupés à une fin de
phrase, avec `pour_continuer` qui dit comment lire la suite. Une liste de
résultats s'affiche en tableau garanti (le modèle n'a pas à la recopier) et ne
garde pour lui que l'essentiel de chaque ligne.

LE CLIENT HTTP ET LES IDENTIFIANTS vivent dans `outils/piste.py`.
"""
from __future__ import annotations

import html
import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import Optional

from skills.erreurs import SkillError
from skills.registre import Declaration

logger = logging.getLogger("duret.skills.droit")

TAILLE_MORCEAU = 2200     # caractères de texte rendus par appel
MAX_RESULTATS = 10
RESULTATS_DEFAUT = 5
EXTRAIT = 220

AVERTISSEMENT = ("Information juridique tirée de la source officielle, pas un conseil "
                 "juridique : pour un litige ou un engagement, faire valider par un "
                 "avocat ou le conseil juridique de l'entreprise.")

# ── Les codes utiles au BTP, et leurs identifiants Légifrance ────────
# Identifiants LEGITEXT stables (le texte change de version, pas d'identifiant).
# Relevés dans la table officielle reprise par le projet mcp-legifrance ; un
# code absent d'ici reste accessible par la recherche plein texte ou par son
# identifiant LEGITEXT donné tel quel.
CODES: dict[str, tuple[str, str]] = {
    "civil": ("LEGITEXT000006070721", "Code civil"),
    "travail": ("LEGITEXT000006072050", "Code du travail"),
    "construction": ("LEGITEXT000006074096", "Code de la construction et de l'habitation"),
    "commande publique": ("LEGITEXT000037701019", "Code de la commande publique"),
    "commerce": ("LEGITEXT000005634379", "Code de commerce"),
    "assurances": ("LEGITEXT000006073984", "Code des assurances"),
    "urbanisme": ("LEGITEXT000006074075", "Code de l'urbanisme"),
    "environnement": ("LEGITEXT000006074220", "Code de l'environnement"),
    "securite sociale": ("LEGITEXT000006073189", "Code de la sécurité sociale"),
    "consommation": ("LEGITEXT000006069565", "Code de la consommation"),
    "procedure civile": ("LEGITEXT000006070716", "Code de procédure civile"),
    "penal": ("LEGITEXT000006070719", "Code pénal"),
    "general des impots": ("LEGITEXT000006069577", "Code général des impôts"),
    "collectivites territoriales": ("LEGITEXT000006070633",
                                    "Code général des collectivités territoriales"),
}
# Ce qu'une personne (ou le modèle) écrit vraiment pour désigner un code.
ALIAS_CODES = {
    "cch": "construction", "habitation": "construction",
    "construction et habitation": "construction",
    "ccp": "commande publique", "marches publics": "commande publique",
    "cgi": "general des impots", "impots": "general des impots",
    "cgct": "collectivites territoriales", "cpc": "procedure civile",
    "ct": "travail", "cc": "civil", "secu": "securite sociale",
}

# Conventions collectives du bâtiment (fonds KALI) : ce que Duret appliquera
# presque toujours. Donné au modèle pour qu'il n'ait pas à deviner l'IDCC.
IDCC_BTP = {
    "1596": "Ouvriers du bâtiment (entreprises jusqu'à 10 salariés)",
    "1597": "Ouvriers du bâtiment (entreprises de plus de 10 salariés)",
    "2609": "ETAM du bâtiment",
    "3212": "Cadres du bâtiment",
}

SOURCES = {"codes": "CODE_ETAT", "lois": "LODA_ETAT", "conventions": "KALI"}
ALIAS_SOURCES = {
    "code": "codes", "loi": "lois", "decret": "lois", "arrete": "lois",
    "loda": "lois", "textes": "lois", "ccag": "lois", "reglement": "lois",
    "convention": "conventions", "conventions collectives": "conventions",
    "convention collective": "conventions", "kali": "conventions",
}

# ── Les décisions déjà montrées, par personne ─────────────────────────
# UN NUMÉRO RG N'EST PAS UNIQUE (24/09, fil de Damien). « 24/02543 » existe dans
# chaque cour d'appel qui a ouvert un dossier à ce rang cette année-là : le tableau
# montrait la décision RPSO (CA, 2e ch., 29/07/2026, id 6a6ae81a…) ; « ouvre la
# décision 24/02543 » a fait chercher le NUMÉRO sur Judilibre, et le modèle a ouvert
# 678f3830… — une ordonnance d'incompétence d'une AUTRE cour (10/01/2025), même RG,
# sans rapport avec les sols. Le lien du tableau porte bien l'identifiant, mais un
# numéro est ce qu'une personne écrit. Le geste retient donc les décisions qu'il a
# montrées à chaque personne, et un numéro se résout D'ABORD parmi elles ; sinon
# Judilibre est interrogé sur le numéro et seules les décisions qui le PORTENT
# exactement sont retenues — plusieurs = elles sont rendues, le choix se demande,
# il ne se devine pas.
_NUMERO_RE = re.compile(r"^\d{2}[/-]\d{2}[.\d]*\d$")   # RG « 24/02543 », pourvoi « 19-24.001 »
MAX_DECISIONS_VUES = 300
_DECISIONS_VUES: dict[str, dict[str, dict]] = {}


def est_un_numero(v) -> bool:
    return bool(_NUMERO_RE.match(str(v or "").strip()))


def _numero_nu(n) -> str:
    return re.sub(r"[^0-9a-z]", "", str(n or "").lower())


def _cle_personne(user) -> str:
    return str(getattr(user, "id", "") or getattr(user, "email", "") or "")


def retenir_decisions(user, lignes: list[dict]) -> None:
    vues = _DECISIONS_VUES.setdefault(_cle_personne(user), {})
    for l in lignes:
        if l.get("id"):
            vues.pop(l["id"], None)
            vues[l["id"]] = l
    while len(vues) > MAX_DECISIONS_VUES:
        del vues[next(iter(vues))]


def decisions_vues_par_numero(user, numero: str) -> list[dict]:
    nu = _numero_nu(numero)
    return [l for l in _DECISIONS_VUES.get(_cle_personne(user), {}).values()
            if nu and _numero_nu(l.get("numero")) == nu]


JURIDICTIONS = {"cassation": ["cc"], "appel": ["ca"], "toutes": ["cc", "ca"]}
ALIAS_JURIDICTIONS = {
    "cc": "cassation", "cour de cassation": "cassation", "ca": "appel",
    "cours d'appel": "appel", "cour d'appel": "appel", "tout": "toutes",
    "les deux": "toutes", "deux": "toutes",
}
CHAMBRES = {"civ1", "civ2", "civ3", "comm", "soc", "cr", "mi", "pl", "allciv"}
ALIAS_CHAMBRES = {
    "premiere chambre civile": "civ1", "1re chambre civile": "civ1", "civile 1": "civ1",
    "deuxieme chambre civile": "civ2", "2e chambre civile": "civ2", "civile 2": "civ2",
    "troisieme chambre civile": "civ3", "3e chambre civile": "civ3", "civile 3": "civ3",
    "commerciale": "comm", "chambre commerciale": "comm",
    "sociale": "soc", "chambre sociale": "soc",
    "criminelle": "cr", "chambre criminelle": "cr",
    "mixte": "mi", "chambre mixte": "mi", "pleniere": "pl", "assemblee pleniere": "pl",
    "civiles": "allciv", "toutes les chambres civiles": "allciv",
}


# ── Petites lectures ─────────────────────────────────────────────────

def _plat(texte) -> str:
    """Minuscules sans accents ni ponctuation superflue : pour comparer des noms."""
    t = unicodedata.normalize("NFD", str(texte or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[’'`]", " ", t)
    t = re.sub(r"^(le|la|les|du|de la|de l|des|de)\s+", "", t.strip())
    t = re.sub(r"^code\s+(general\s+)?(du|de la|de l|des|de)?\s*", "", t)
    return re.sub(r"\s+", " ", t).strip()


def _choix(brut, table: dict, alias: dict, defaut: str) -> str:
    v = _plat(brut)
    if not v:
        return defaut
    if v in table:
        return v
    # Les clés d'alias passent par la même normalisation que la demande :
    # « cours d'appel » écrit avec une apostrophe doit se retrouver.
    return {_plat(k): a for k, a in alias.items()}.get(v, defaut)


def resoudre_code(brut) -> Optional[tuple[str, str]]:
    """(identifiant LEGITEXT, libellé) d'un code désigné en mots, ou None."""
    s = str(brut or "").strip()
    if not s:
        return None
    if s.upper().startswith("LEGITEXT"):
        # Libellé vide : le titre du texte viendra de la réponse de Légifrance.
        return s.upper(), ""
    cle = _plat(s)
    cle = ALIAS_CODES.get(cle, cle)
    if cle in CODES:
        return CODES[cle]
    # « code de la construction » → « construction » ; « code civil français »
    # → « civil » : le premier code dont le nom court apparaît dans la demande.
    # Du nom le plus long au plus court : « procédure civile » avant « civil ».
    for nom in sorted(CODES, key=len, reverse=True):
        if nom in cle:
            return CODES[nom]
    return None


def texte_propre(brut) -> str:
    """Texte lisible depuis le HTML de Légifrance : balises retirées, paragraphes gardés."""
    t = str(brut or "")
    t = re.sub(r"(?i)<\s*br\s*/?>|</\s*p\s*>|</\s*li\s*>|</\s*div\s*>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t).replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n\n", t)
    return t.strip()


def date_lisible(v) -> str:
    """Date ISO courte depuis ce que rendent les API (millisecondes Unix ou ISO).

    Légifrance rend souvent ses dates en millisecondes ; une fin de version au
    2999-01-01 signifie « sans fin » : on la tait plutôt que de l'afficher.
    """
    if v in (None, "", 0):
        return ""
    try:
        if isinstance(v, (int, float)) or re.fullmatch(r"-?\d{9,}", str(v).strip()):
            d = datetime.fromtimestamp(int(v) / 1000, tz=timezone.utc)
            return "" if d.year >= 2999 else d.strftime("%Y-%m-%d")
    except (ValueError, OverflowError, OSError):
        return ""
    s = str(v).strip()[:10]
    if s.startswith("2999"):
        return ""
    return s if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) else ""


ETATS = {
    "VIGUEUR": "en vigueur", "VIGUEUR_DIFF": "en vigueur différée",
    "VIGUEUR_ETEN": "en vigueur (étendu)", "VIGUEUR_NON_ETEN": "en vigueur (non étendu)",
    "ABROGE": "abrogé", "ABROGE_DIFF": "abrogation différée", "MODIFIE": "modifié",
    "PERIME": "périmé", "ANNULE": "annulé", "TRANSFERE": "transféré",
    "DISJOINT": "disjoint", "SUBSTITUE": "substitué",
}


def etat_lisible(etat) -> str:
    e = str(etat or "").strip().upper()
    return ETATS.get(e, e.lower())


def couper(texte: str, depart: int = 0, taille: int = TAILLE_MORCEAU) -> tuple[str, Optional[int]]:
    """Un morceau lisible à partir de `depart`, coupé à une fin de phrase.

    Rend (morceau, position de la suite) ; la suite vaut None quand tout est lu.
    Couper au milieu d'un mot ou d'un chiffre ferait citer une phrase fausse.
    """
    depart = max(0, min(int(depart or 0), len(texte)))
    reste = texte[depart:]
    if len(reste) <= taille:
        return reste.strip(), None
    fenetre = reste[:taille]
    coupe = max(fenetre.rfind("\n"), fenetre.rfind(". "), fenetre.rfind("; "))
    if coupe < taille // 2:
        coupe = fenetre.rfind(" ")
    if coupe <= 0:
        coupe = taille - 1
    fin = coupe + 1
    # strip des deux côtés : une suite commence après l'espace qui suit le point.
    return reste[:fin].strip(), depart + fin


def _entier(v, defaut: int, mini: int, maxi: int) -> int:
    try:
        return max(mini, min(int(v), maxi))
    except (TypeError, ValueError):
        return defaut


def _variantes_numero(num: str) -> list[str]:
    """Les écritures à essayer pour un numéro d'article.

    « L. 1234-9 », « l1234-9 », « 1234-9 » : Légifrance n'accepte que « L1234-9 ».
    Un numéro nu est essayé tel quel (Code civil : « 1792 ») puis avec les
    préfixes législatif et réglementaires (Code du travail : « L1234-9 »).
    """
    brut = re.sub(r"(?i)^\s*(art\.?|article)\s*", "", str(num or "")).strip()
    brut = re.sub(r"\s+", "", brut).replace(".", "")
    if not brut:
        return []
    m = re.fullmatch(r"(?i)([LRDA])(\*?)(\d.*)", brut)
    if m:
        return [m.group(1).upper() + m.group(2) + m.group(3)]
    return [brut, f"L{brut}", f"R{brut}", f"D{brut}"]


def lien_legifrance(ident: str, code: bool = True) -> str:
    """Le lien public d'un article ou d'un texte, selon la forme de son identifiant."""
    i = str(ident or "").strip()
    base = "https://www.legifrance.gouv.fr"
    if i.startswith("KALIARTI"):
        return f"{base}/conv_coll/article/{i}"
    if i.startswith(("KALICONT", "KALITEXT")):
        return f"{base}/conv_coll/id/{i}"
    if i.startswith("JORFARTI"):
        return f"{base}/jorf/article_jo/{i}"
    if i.startswith("JORFTEXT"):
        return f"{base}/jorf/id/{i}"
    if i.startswith("LEGIARTI"):
        return f"{base}/{'codes' if code else 'loda'}/article_lc/{i}"
    if i.startswith("LEGITEXT"):
        return f"{base}/{'codes/texte_lc' if code else 'loda/id'}/{i}"
    return ""


def lien_decision(ident: str) -> str:
    return f"https://www.courdecassation.fr/decision/{ident}" if ident else ""


def _erreur(e) -> SkillError:
    return SkillError(str(e))


# ── Légifrance ───────────────────────────────────────────────────────

def _article_en_resultat(article: dict, depart: int, code_connu: Optional[str] = None,
                         demande: dict | None = None) -> dict:
    ident = str(article.get("id") or "")
    titres = article.get("textTitles") or []
    titre_texte = ""
    nature = ""
    if titres and isinstance(titres[0], dict):
        titre_texte = str(titres[0].get("titreLong") or titres[0].get("titre") or "")
        nature = str(titres[0].get("nature") or "")
    titre_texte = code_connu or titre_texte
    est_code = bool(code_connu) or nature.upper() == "CODE" or titre_texte.lower().startswith("code")
    texte = texte_propre(article.get("texteHtml") or article.get("texte")
                         or article.get("content") or "")
    morceau, suite = couper(texte, depart)
    debut = date_lisible(article.get("dateDebut"))
    fin = date_lisible(article.get("dateFin"))
    etat = etat_lisible(article.get("etat"))
    num = str(article.get("num") or "").strip()
    res = {
        "source": "Légifrance",
        "texte_source": titre_texte,
        "article": f"Article {num}" if num else "Article",
        "id": ident,
        "etat": etat,
        "version_en_vigueur_depuis": debut,
        "lien": lien_legifrance(ident, code=est_code),
        "texte": morceau,
        "longueur": len(texte),
    }
    if fin:
        res["version_valable_jusqu_au"] = fin
    if article.get("sectionParentTitre"):
        res["section"] = str(article["sectionParentTitre"])[:160]
    if suite is not None:
        res["pour_continuer"] = (
            f"Texte coupé à {suite} caractères sur {len(texte)} : pour lire la suite, "
            f"rappelle `texte_de_loi` avec `id: \"{ident}\"` et `a_partir_de: {suite}`.")
    if etat and etat != "en vigueur":
        res["attention"] = (f"Cette version est « {etat} » : ce n'est pas le droit applicable "
                            "aujourd'hui, dis-le avant de t'en servir.")
    res["a_faire"] = (
        "Réponds en CITANT cet article : son numéro, le texte d'où il vient, la date de la "
        "version (« en vigueur depuis le … ») et le lien Légifrance, en recopiant mot pour "
        "mot les passages que tu t'appropries. Ne complète jamais de mémoire ce que le texte "
        "ne dit pas. Termine par une phrase qui rappelle que c'est une information, pas un "
        "conseil juridique. " + ("Si la question exige la suite du texte, lis-la avant de "
                                 "répondre (voir `pour_continuer`)." if suite is not None else ""))
    res["avertissement"] = AVERTISSEMENT
    return res


def _chercher_article_kali(corps: dict, ident: str) -> Optional[dict]:
    """L'article demandé, au milieu de la convention que rend `kaliArticle`."""
    pile = [corps]
    while pile:
        noeud = pile.pop()
        if not isinstance(noeud, dict):
            continue
        for art in noeud.get("articles") or []:
            if isinstance(art, dict) and str(art.get("id") or "") == ident:
                return art
        pile.extend(s for s in (noeud.get("sections") or []) if isinstance(s, dict))
    return None


async def _lire_par_id(ident: str, depart: int) -> dict:
    from outils import piste
    try:
        if ident.startswith("KALIARTI"):
            corps = await piste.legifrance("/consult/kaliArticle", {"id": ident}) or {}
            art = _chercher_article_kali(corps, ident)
            if not art:
                raise SkillError(f"L'article {ident} n'a pas été retrouvé dans la convention "
                                 "rendue par Légifrance.")
            art = dict(art)
            art.setdefault("textTitles", [{"titre": corps.get("title") or "Convention collective"}])
            return _article_en_resultat(art, depart,
                                        code_connu=str(corps.get("title") or "") or None)
        corps = await piste.legifrance("/consult/getArticle", {"id": ident}) or {}
    except piste.PisteErreur as e:
        raise _erreur(e) from None
    art = corps.get("article") if isinstance(corps, dict) else None
    if not isinstance(art, dict) or not art.get("id"):
        raise SkillError(f"Légifrance ne rend aucun article pour l'identifiant {ident}.")
    return _article_en_resultat(art, depart)


async def _article_d_un_code(code: tuple[str, str], numero: str, depart: int) -> dict:
    from outils import piste
    essais = _variantes_numero(numero)
    if not essais:
        raise SkillError("Donne le numéro de l'article (par exemple « 1792 » ou « L1234-9 »).")
    derniere = None
    for num in essais:
        try:
            corps = await piste.legifrance("/consult/getArticleWithIdAndNum",
                                           {"id": code[0], "num": num}) or {}
        except piste.PisteErreur as e:
            # 404 / 400 : ce numéro n'existe pas sous cette écriture — on essaie
            # la suivante. Toute autre erreur (identifiants, quota) est définitive.
            if e.statut in (400, 404, 500):
                derniere = e
                continue
            raise _erreur(e) from None
        art = corps.get("article") if isinstance(corps, dict) else None
        if isinstance(art, dict) and art.get("id"):
            return _article_en_resultat(art, depart, code_connu=code[1] or None)
    essaye = ", ".join(essais)
    raise SkillError(
        f"Aucun article {essaye} en vigueur dans le {code[1] or code[0]}"
        + (f" ({derniere})" if derniere and derniere.statut not in (400, 404) else "")
        + ". Vérifie le numéro, ou cherche avec `recherche` (mots du sujet) pour "
        "retrouver le bon article.")


def _extrait(valeurs) -> str:
    if isinstance(valeurs, str):
        valeurs = [valeurs]
    brut = " … ".join(texte_propre(v) for v in (valeurs or []) if v)
    brut = " ".join(brut.split())
    return brut[:EXTRAIT] + ("…" if len(brut) > EXTRAIT else "")


def lignes_de_recherche(corps: dict, source: str) -> list[dict]:
    """Les résultats de `/search` à plat : un article trouvé par ligne.

    Un résultat Légifrance est un TEXTE (le Code civil) qui porte des sections
    et, dedans, les ARTICLES qui correspondent (`extracts`). C'est l'article
    qu'on veut citer : on descend jusqu'à lui ; un texte sans article repéré
    reste une ligne à lui seul (une loi, un arrêté comme le CCAG-Travaux).
    """
    lignes: list[dict] = []
    est_code = source == "codes"
    for r in (corps or {}).get("results") or []:
        if not isinstance(r, dict):
            continue
        titres = r.get("titles") or [{}]
        t0 = titres[0] if titres and isinstance(titres[0], dict) else {}
        titre = texte_propre(t0.get("title") or r.get("text") or "")[:160]
        vus = 0
        for s in r.get("sections") or []:
            if not isinstance(s, dict):
                continue
            for x in s.get("extracts") or []:
                if not isinstance(x, dict) or not x.get("id"):
                    continue
                vus += 1
                ident = str(x["id"])
                lignes.append({
                    "texte_source": titre,
                    "article": f"Article {x.get('num')}" if x.get("num") else
                               texte_propre(x.get("title") or "")[:80],
                    "id": ident,
                    "etat": etat_lisible(x.get("legalStatus")),
                    "depuis": date_lisible(x.get("dateDebut") or x.get("dateVersion")),
                    "extrait": _extrait(x.get("values")),
                    "lien": lien_legifrance(ident, code=est_code),
                })
        if not vus:
            ident = str(t0.get("cid") or t0.get("id") or r.get("jorfText") or "")
            lignes.append({
                "texte_source": titre, "article": "", "id": ident,
                "etat": etat_lisible(t0.get("legalStatus") or r.get("etat")),
                "depuis": date_lisible(r.get("dateSignature") or r.get("datePublication")
                                       or r.get("date")),
                "extrait": _extrait((r.get("resumePrincipal") or []) + (r.get("autreResume") or [])),
                "lien": lien_legifrance(ident, code=est_code),
            })
    return lignes


def _corps_recherche(valeur: str, fond: str, champ: str, type_recherche: str,
                     limite: int, page: int, filtres: list[dict]) -> dict:
    recherche = {
        "champs": [{"typeChamp": champ, "operateur": "ET",
                    "criteres": [{"typeRecherche": type_recherche, "valeur": valeur,
                                  "operateur": "ET"}]}],
        "operateur": "ET", "pageSize": limite, "pageNumber": page,
        "sort": "PERTINENCE", "typePagination": "DEFAUT",
    }
    if filtres:
        recherche["filtres"] = filtres
    return {"fond": fond, "recherche": recherche}


async def _recherche_legifrance(valeur: str, source: str, *, code: Optional[tuple[str, str]],
                                idcc: str, limite: int, page: int, par_numero: bool) -> dict:
    from outils import piste
    fond = SOURCES[source]
    filtres: list[dict] = []
    if fond in ("CODE_ETAT", "LODA_ETAT"):
        filtres.append({"facette": "ARTICLE_LEGAL_STATUS", "valeurs": ["VIGUEUR"]})
    if fond == "KALI" and idcc:
        filtres.append({"facette": "IDCC", "valeurs": [idcc]})
    champ = "NUM_ARTICLE" if par_numero else "ALL"
    type_recherche = "EXACTE" if par_numero else "TOUS_LES_MOTS_DANS_UN_CHAMP"
    # Filtrer par code côté API passe par une facette dont les valeurs ne sont
    # pas documentées (erreur 500 sur un nom approché) : on élargit la page et
    # on trie ICI par le titre du texte.
    taille = min(100, limite * 4) if code else limite
    corps_req = _corps_recherche(valeur, fond, champ, type_recherche, taille, page, filtres)
    try:
        corps = await piste.legifrance("/search", corps_req)
    except piste.PisteErreur as e:
        # Une facette refusée (400/500) ne doit pas priver de toute réponse :
        # un second essai sans le filtre d'état, qu'on applique alors nous-mêmes.
        if e.statut in (400, 500) and any(f["facette"] == "ARTICLE_LEGAL_STATUS" for f in filtres):
            reste = [f for f in filtres if f["facette"] != "ARTICLE_LEGAL_STATUS"]
            try:
                corps = await piste.legifrance("/search", _corps_recherche(
                    valeur, fond, champ, type_recherche, taille, page, reste))
            except piste.PisteErreur as e2:
                raise _erreur(e2) from None
        else:
            raise _erreur(e) from None
    lignes = lignes_de_recherche(corps if isinstance(corps, dict) else {}, source)
    # Une version abrogée n'est pas le droit applicable : en queue de liste.
    lignes.sort(key=lambda l: 0 if l["etat"].startswith("en vigueur") or not l["etat"] else 1)
    note = ""
    if code and code[1]:
        cible = _plat(code[1])
        # Égalité d'abord : « civil » est contenu dans « procédure civile ».
        dans = ([l for l in lignes if cible and _plat(l["texte_source"]) == cible]
                or [l for l in lignes if cible and cible in _plat(l["texte_source"])])
        if dans:
            lignes = dans
        elif lignes:
            note = (f"Aucun résultat dans le {code[1]} lui-même : voici ce qui ressort des "
                    "autres textes.")
    lignes = lignes[:limite]
    total = int((corps or {}).get("totalResultNumber") or 0) if isinstance(corps, dict) else 0
    etiquette = {"codes": "codes", "lois": "lois, décrets et arrêtés",
                 "conventions": "conventions collectives"}[source]
    res: dict = {
        "source": "Légifrance", "recherche": valeur, "fonds": etiquette,
        "page": page, "total": total, "resultats": lignes,
    }
    if note:
        res["note"] = note
    if not lignes:
        res["message_final"] = (f"Légifrance ne rend rien pour « {valeur} » dans les "
                                f"{etiquette}.")
        res["a_faire"] = (
            "Aucun résultat : dis ce que tu as cherché, puis retente avec d'autres mots "
            "(le terme juridique : « réception des travaux », « garantie de parfait "
            "achèvement », « pénalités de retard »), ou une autre `source` (codes, lois, "
            "conventions). Ne réponds pas de mémoire en présentant ta réponse comme la loi.")
        return res
    res["bloc_ui"] = {
        "type": "table", "titre": f"Légifrance — {valeur}",
        "columns": ["Texte", "Article", "État", "Extrait", "Lien"],
        "rows": [[l["texte_source"], l["article"], l["etat"], l["extrait"], l["lien"]]
                 for l in lignes],
    }
    res["bloc_garanti"] = True
    res["message_final"] = (f"{len(lignes)} résultat(s) Légifrance affiché(s) pour « {valeur} »"
                            + (f" sur {total}" if total > len(lignes) else "") + ".")
    if total > page * limite:
        res["pour_continuer"] = (f"Page suivante : rappelle `texte_de_loi` avec la même "
                                 f"`recherche` et `page: {page + 1}`.")
    res["a_faire"] = (
        "Les résultats sont DÉJÀ affichés en tableau : ne les recopie pas. Un extrait ne "
        "suffit pas pour répondre sur le fond : OUVRE l'article pertinent avec `texte_de_loi` "
        "et son `id`, puis réponds en citant son numéro, sa date de version et son lien. "
        "Termine en rappelant que c'est une information, pas un conseil juridique.")
    res["avertissement"] = AVERTISSEMENT
    return res


async def texte_de_loi(data: dict, user) -> dict:
    ident = str(data.get("id") or data.get("identifiant") or "").strip()
    article = str(data.get("article") or data.get("numero") or data.get("num") or "").strip()
    recherche = str(data.get("recherche") or data.get("requete") or data.get("question")
                    or data.get("mots") or "").strip()
    depart = _entier(data.get("a_partir_de"), 0, 0, 10_000_000)
    limite = _entier(data.get("limite"), RESULTATS_DEFAUT, 1, MAX_RESULTATS)
    page = _entier(data.get("page"), 1, 1, 1000)
    source = _choix(data.get("source"), SOURCES, ALIAS_SOURCES, "codes")
    idcc = re.sub(r"\D", "", str(data.get("idcc") or ""))
    if idcc:
        source = "conventions"
    code_brut = data.get("code") or data.get("texte")
    code = resoudre_code(code_brut)
    if code_brut and not code and not recherche and not ident:
        connus = ", ".join(v[1] for v in CODES.values())
        raise SkillError(f"Code « {code_brut} » non reconnu. Codes connus : {connus} "
                         "(ou un identifiant LEGITEXT). Sinon, cherche par `recherche`.")

    from outils import piste
    try:
        piste.identifiants()      # clé absente : on le dit AVANT tout appel réseau
    except piste.PisteErreur as e:
        raise _erreur(e) from None

    if ident:
        return await _lire_par_id(ident, depart)
    if article and code:
        return await _article_d_un_code(code, article, depart)
    if article and not recherche:
        # Un numéro sans code : on le cherche dans TOUS les codes plutôt que de
        # demander lequel — la liste dira s'il y en a plusieurs.
        nums = _variantes_numero(article)
        return await _recherche_legifrance(nums[0] if nums else article, source, code=None,
                                           idcc=idcc, limite=limite, page=page,
                                           par_numero=True)
    if not recherche:
        raise SkillError("Dis ce qu'il faut chercher : `recherche` (mots du sujet), ou "
                         "`code` + `article` (ex. code civil, 1792), ou l'`id` d'un article.")
    return await _recherche_legifrance(recherche, source, code=code, idcc=idcc,
                                       limite=limite, page=page, par_numero=False)


# ── Judilibre ────────────────────────────────────────────────────────

def _date_filtre(v, fin: bool = False) -> str:
    s = str(v or "").strip()
    if re.fullmatch(r"\d{4}", s):
        return f"{s}-12-31" if fin else f"{s}-01-01"
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return s[:10] if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", s) else ""


def _libelle(v) -> str:
    """Judilibre rend une clé ou, avec resolve_references, un intitulé : on garde le texte."""
    if isinstance(v, dict):
        return str(v.get("value") or v.get("label") or v.get("key") or "")
    if isinstance(v, list):
        return ", ".join(_libelle(x) for x in v if x)
    return str(v or "")


def _extrait_decision(d: dict) -> str:
    resume = texte_propre(d.get("summary") or "")
    if not resume:
        surl = d.get("highlights") or {}
        morceaux = []
        if isinstance(surl, dict):
            for vals in surl.values():
                morceaux.extend(vals if isinstance(vals, list) else [vals])
        resume = texte_propre(" … ".join(str(m) for m in morceaux[:3]))
    resume = " ".join(resume.split())
    return resume[:260] + ("…" if len(resume) > 260 else "")


def ligne_de_decision(d: dict) -> dict:
    ident = str(d.get("id") or "")
    return {
        "id": ident,
        "date": date_lisible(d.get("decision_date")),
        "juridiction": _libelle(d.get("jurisdiction")),
        "chambre": _libelle(d.get("chamber")),
        "numero": str(d.get("number") or ""),
        "solution": _libelle(d.get("solution")) or str(d.get("solution_alt") or ""),
        "sommaire": _extrait_decision(d),
        "lien": lien_decision(ident),
    }


def _zone(texte: str, zones: dict, nom: str) -> tuple[int, int]:
    segs = (zones or {}).get(nom) or []
    try:
        debut = min(int(s["start"]) for s in segs)
        fin = max(int(s["end"]) for s in segs)
        return max(0, debut), min(len(texte), fin)
    except (ValueError, KeyError, TypeError):
        return -1, -1


async def _lire_decision(ident: str, depart: Optional[int]) -> dict:
    from outils import piste
    try:
        d = await piste.judilibre("/decision", {"id": ident, "resolve_references": "true"})
    except piste.PisteErreur as e:
        raise _erreur(e) from None
    if not isinstance(d, dict) or not d.get("id"):
        raise SkillError(f"Judilibre ne rend aucune décision pour l'identifiant {ident}.")
    texte = str(d.get("text") or "")
    zones = d.get("zones") or {}
    # Sans position demandée, on commence aux MOTIFS : l'en-tête (parties,
    # avocats, rappel de la procédure) mange le budget sans rien dire du droit.
    if depart is None:
        debut_motifs, _ = _zone(texte, zones, "motivations")
        depart = debut_motifs if debut_motifs > 0 else 0
    morceau, suite = couper(texte, depart)
    d0, d1 = _zone(texte, zones, "dispositif")
    dispositif = " ".join(texte[d0:d1].split())[:700] if d0 >= 0 else ""
    res = ligne_de_decision(d)
    res.pop("sommaire", None)
    res.update({
        "source": "Judilibre (Cour de cassation)",
        "sommaire": " ".join(texte_propre(d.get("summary") or "").split())[:700],
        "texte": morceau, "position": depart, "longueur": len(texte),
    })
    if dispositif:
        res["dispositif"] = dispositif
    visas = [str(v.get("title")) for v in (d.get("visa") or []) if isinstance(v, dict) and v.get("title")]
    if visas:
        res["textes_appliques"] = visas[:6]
    if suite is not None:
        res["pour_continuer"] = (
            f"Texte lu de {depart} à {suite} sur {len(texte)} caractères : pour la suite, "
            f"rappelle `jurisprudence` avec `id: \"{ident}\"` et `a_partir_de: {suite}` "
            "(`a_partir_de: 0` pour le début).")
    res["a_faire"] = (
        "Réponds en CITANT la décision : juridiction, chambre, date, numéro de pourvoi, "
        "solution, et le lien. Ne prête à la décision que ce que son texte dit ; une "
        "décision tranche UN litige : dis si elle est publiée au Bulletin (portée) ou "
        "d'espèce si tu le sais, sinon ne l'affirme pas. Si cette décision n'est PAS celle "
        "annoncée plus haut (autre date, autre juridiction, autre affaire), dis-le en clair "
        "au lieu de la présenter comme la même. Termine en rappelant que c'est une "
        "information, pas un conseil juridique.")
    res["avertissement"] = AVERTISSEMENT
    return res


async def _ouvrir_par_numero(numero: str, user, depart: Optional[int]) -> dict:
    """Un numéro (RG « 24/02543 », pourvoi « 19-24.001 ») → LA décision, ou les candidates.

    D'abord parmi les décisions montrées à cette personne (c'est de là que vient le
    numéro qu'elle recopie) ; sinon Judilibre, en ne gardant que les décisions qui
    PORTENT ce numéro — la recherche plein texte rend aussi celles qui le citent."""
    from outils import piste
    candidats = decisions_vues_par_numero(user, numero)
    origine = "déjà montrée(s) dans cette conversation"
    if not candidats:
        params = {"query": numero, "operator": "and", "jurisdiction": ["cc", "ca"],
                  "page_size": MAX_RESULTATS, "page": 0, "resolve_references": "true",
                  "sort": "date", "order": "desc"}
        try:
            corps = await piste.judilibre("/search", params)
        except piste.PisteErreur as e:
            raise _erreur(e) from None
        nu = _numero_nu(numero)
        resultats = (corps if isinstance(corps, dict) else {}).get("results") or []
        candidats = [ligne_de_decision(d) for d in resultats
                     if isinstance(d, dict) and (_numero_nu(d.get("number")) == nu
                                                 or any(_numero_nu(x) == nu for x in (d.get("numbers") or [])))]
        origine = "trouvée(s) sur Judilibre"
    if not candidats:
        raise SkillError(f"Aucune décision ne porte le numéro {numero} sur Judilibre : vérifie le "
                         "numéro, ou ouvre la décision par l'`id` de sa ligne (le lien du tableau).")
    if len(candidats) == 1:
        return await _lire_decision(candidats[0]["id"], depart)
    return {
        "source": "Judilibre (Cour de cassation)", "numero": numero, "total": len(candidats),
        "candidats": candidats,
        "bloc_ui": {"type": "table", "titre": f"Décisions portant le numéro {numero}",
                    "columns": ["Date", "Juridiction", "Chambre", "N°", "Sommaire", "Lien"],
                    "rows": [[l["date"], l["juridiction"], l["chambre"], l["numero"], l["sommaire"], l["lien"]]
                             for l in candidats]},
        "bloc_garanti": True,
        "message_final": (f"{len(candidats)} décisions portent le numéro {numero} ({origine}) : "
                          "un numéro RG n'est unique que dans sa juridiction."),
        "a_faire": ("Plusieurs décisions portent ce numéro (chaque cour numérote ses propres "
                    "dossiers) : NE devine pas. Si l'une d'elles est celle montrée plus haut dans la "
                    "conversation (même date, même juridiction), ouvre-la avec son `id` ; sinon "
                    "demande laquelle par une question à choix (boutons `quick_replies` : date + "
                    "juridiction + chambre), sans en présenter une comme « la bonne »."),
        "avertissement": AVERTISSEMENT,
    }


async def jurisprudence(data: dict, user) -> dict:
    ident = str(data.get("id") or data.get("decision") or "").strip()
    numero = str(data.get("numero") or data.get("rg") or data.get("pourvoi") or data.get("num") or "").strip()
    # Le modèle écrit volontiers `id: "24/02543"` : un numéro n'est pas un identifiant
    # Judilibre (24 hexadécimaux) — c'était un 404 sec, suivi d'une recherche au hasard.
    if ident and est_un_numero(ident):
        numero, ident = ident, ""
    recherche = str(data.get("recherche") or data.get("requete") or data.get("question")
                    or data.get("mots") or "").strip()
    brut_depart = data.get("a_partir_de")
    depart = None if brut_depart in (None, "") else _entier(brut_depart, 0, 0, 10_000_000)
    limite = _entier(data.get("limite"), RESULTATS_DEFAUT, 1, MAX_RESULTATS)
    page = _entier(data.get("page"), 1, 1, 1000)

    from outils import piste
    try:
        piste.identifiants()
    except piste.PisteErreur as e:
        raise _erreur(e) from None

    if ident:
        return await _lire_decision(ident, depart)
    if numero:
        return await _ouvrir_par_numero(numero, user, depart)
    if not recherche:
        raise SkillError("Dis ce qu'il faut chercher (`recherche`), ou donne l'`id` d'une décision "
                         "(ou son `numero`).")

    juridiction = _choix(data.get("juridiction"), JURIDICTIONS, ALIAS_JURIDICTIONS, "cassation")
    params: dict = {
        "query": recherche, "operator": "and",
        "jurisdiction": JURIDICTIONS[juridiction],
        "page_size": limite, "page": page - 1,   # Judilibre compte ses pages depuis 0
        "resolve_references": "true",
    }
    chambre = _choix(data.get("chambre"), {c: c for c in CHAMBRES}, ALIAS_CHAMBRES, "")
    if chambre and juridiction == "cassation":
        params["chamber"] = [chambre]
    debut = _date_filtre(data.get("depuis") or data.get("date_debut"))
    fin = _date_filtre(data.get("jusqu_a") or data.get("date_fin"), fin=True)
    if debut:
        params["date_start"] = debut
    if fin:
        params["date_end"] = fin
    if str(data.get("publiees") or "").strip().lower() in ("1", "true", "oui", "vrai"):
        # b = Bulletin, r = Rapport, l = Lettre de chambre, c = communiqué :
        # les décisions à portée de principe.
        params["publication"] = ["b", "r", "l", "c"]
    tri = _plat(data.get("tri"))
    if tri in ("date", "recent", "recentes", "plus recent", "plus recentes"):
        params["sort"], params["order"] = "date", "desc"
    else:
        params["sort"] = "scorepub"   # pertinence pondérée par la publication

    try:
        corps = await piste.judilibre("/search", params)
    except piste.PisteErreur as e:
        raise _erreur(e) from None
    corps = corps if isinstance(corps, dict) else {}
    lignes = [ligne_de_decision(d) for d in (corps.get("results") or []) if isinstance(d, dict)]
    retenir_decisions(user, lignes)
    total = int(corps.get("total") or 0)
    res: dict = {"source": "Judilibre (Cour de cassation)", "recherche": recherche,
                 "juridiction": {"cassation": "Cour de cassation", "appel": "cours d'appel",
                                 "toutes": "Cour de cassation et cours d'appel"}[juridiction],
                 "page": page, "total": total, "resultats": lignes}
    if chambre:
        res["chambre"] = chambre
    if corps.get("relaxed"):
        res["note"] = ("Judilibre a élargi la recherche faute de résultat exact : "
                       "les décisions peuvent ne porter que sur une partie des mots.")
    if not lignes:
        res["message_final"] = f"Judilibre ne rend aucune décision pour « {recherche} »."
        res["a_faire"] = (
            "Aucune décision : dis ce que tu as cherché et retente avec d'autres mots (les "
            "termes des arrêts : « désordres », « impropriété à la destination », « réception "
            "tacite »), sans filtre de chambre ou de date, ou `juridiction: \"toutes\"`. "
            "N'invente jamais de jurisprudence.")
        return res
    res["bloc_ui"] = {
        "type": "table", "titre": f"Jurisprudence — {recherche}",
        "columns": ["Date", "Juridiction", "Chambre", "N°", "Solution", "Sommaire", "Lien"],
        "rows": [[l["date"], l["juridiction"], l["chambre"], l["numero"], l["solution"],
                  l["sommaire"], l["lien"]] for l in lignes],
    }
    res["bloc_garanti"] = True
    res["message_final"] = (f"{len(lignes)} décision(s) affichée(s) pour « {recherche} »"
                            + (f" sur {total}" if total > len(lignes) else "") + ".")
    if total > page * limite:
        res["pour_continuer"] = (f"Page suivante : rappelle `jurisprudence` avec la même "
                                 f"`recherche` et `page: {page + 1}`.")
    res["a_faire"] = (
        "Les décisions sont DÉJÀ affichées en tableau : ne les recopie pas. Pour t'appuyer "
        "sur une décision, OUVRE-la avec `jurisprudence` et l'`id` de SA ligne (un sommaire "
        "ne suffit pas) — jamais par une nouvelle recherche sur son numéro : un numéro RG "
        "existe dans plusieurs cours, `numero` ne sert que si la personne ne donne que ça. "
        "Puis cite juridiction, date, numéro et lien. Termine en rappelant que c'est une "
        "information, pas un conseil juridique.")
    res["avertissement"] = AVERTISSEMENT
    return res


SKILLS = {
    "texte_de_loi": Declaration(
        fonction=texte_de_loi,
        description=(
            "Le DROIT EN VIGUEUR, lu sur Légifrance (source officielle) : un article de code "
            "ou de loi, avec sa date de version et son lien. À utiliser dès qu'une question "
            "touche au droit : garanties décennale, biennale, parfait achèvement (code civil "
            "1792 et suivants), réception et réserves, sous-traitance, retards et pénalités de "
            "paiement (code de commerce L441-10, code de la commande publique), marchés publics, "
            "CCAG-Travaux (`source: \"lois\"`), droit du travail, conventions collectives du "
            "bâtiment (`source: \"conventions\"`, `idcc` 1596/1597 ouvriers, 2609 ETAM, 3212 "
            "cadres). `code` + `article` (ex. « civil », « 1792 » ; « travail », « L1234-9 ») "
            "pour un article précis ; `recherche` (mots du sujet) sinon ; `id` pour ouvrir un "
            "résultat ; `a_partir_de` pour lire la suite d'un long article ; `page`, `limite`. "
            "Toujours CITER l'article, sa date de version et son lien, et rappeler que ce "
            "n'est pas un conseil juridique. Jamais le droit de mémoire ni par le web quand ce "
            "geste répond."),
        optionnels=["code", "article", "recherche", "id", "source", "idcc",
                    "a_partir_de", "page", "limite"],
        effet="lecture", libelle="je consulte le texte officiel sur Légifrance"),
    "jurisprudence": Declaration(
        fonction=jurisprudence,
        description=(
            "La JURISPRUDENCE officielle (Judilibre : Cour de cassation et cours d'appel) : "
            "comment les juges ont tranché une question — désordres et garantie décennale, "
            "réception tacite, réserves, sous-traitant impayé, pénalités de retard, "
            "licenciement… `recherche` (mots du litige) ; `juridiction` (cassation par défaut, "
            "appel, toutes) ; `chambre` (civ3 = construction, soc = travail, comm = "
            "commercial) ; `depuis` / `jusqu_a` (année ou date) ; `publiees: true` pour les "
            "arrêts de principe ; `tri: date` pour les plus récentes ; `id` pour LIRE une "
            "décision (l'identifiant de SA ligne dans le tableau — commence aux motifs, "
            "`a_partir_de` pour la suite) ; `numero` (RG « 24/02543 », pourvoi « 19-24.001 ») "
            "seulement quand la personne ne donne que le numéro : il est résolu parmi les "
            "décisions déjà montrées, et un numéro porté par plusieurs cours rend les "
            "candidates à faire choisir. Toujours citer juridiction, date, numéro et lien, et "
            "rappeler que ce n'est pas un conseil juridique."),
        optionnels=["recherche", "id", "numero", "juridiction", "chambre", "depuis", "jusqu_a",
                    "publiees", "tri", "a_partir_de", "page", "limite"],
        effet="lecture", libelle="je cherche la jurisprudence sur Judilibre"),
}
