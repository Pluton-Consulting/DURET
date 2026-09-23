"""
LA FICHE D'UN PRODUIT, LUE À LA SOURCE (23/09, Duret).

Demande de Noa : « pour Duret, ça doit être un réflexe pour l'IA d'aller confirmer
ses informations, les enrichir ou trouver sur le web ce qu'elle ne trouve pas
ailleurs — notamment tout ce qui concerne les produits, les fiches techniques, les
sites fournisseurs ; elle doit être une grosse force de proposition là-dessus ».

Mesuré sur 21 jours de production (445 demandes) : 14 recherches web, presque
toutes des tests où la personne DISAIT d'aller sur le web. « Quel prix au m² pour
du PVC acoustique ? », la lecture d'un CCTP, le rapprochement d'achats Würth : aucune
vérification, aucune source. Le métier de Duret vit pourtant de fiches produits —
classement UPEC, classement au feu, épaisseur, efficacité acoustique, avis technique.

CE QUE FAIT CE GESTE (sans modèle) : une recherche orientée vers le site du FABRICANT
quand la marque est connue, et vers la fiche technique (souvent un PDF, que le
conteneur navigateur sait lire) ; puis les caractéristiques qui comptent sur un
chantier de sols sont RELEVÉES dans le texte lu, chacune avec l'adresse où elle a
été lue. Le tableau s'affiche ; le texte lu reste disponible pour le reste. Un
relevé mécanique ne remplace pas la lecture : ce qui n'est pas relevé n'est pas
absent de la fiche — le modèle lit `contenu`.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

logger = logging.getLogger("duret.skills.produits")

# Les fabricants que Duret pose, et leur site : une recherche « site:gerflor.fr … »
# tombe sur la fiche du fabricant au lieu d'un revendeur ou d'un comparateur.
FABRICANTS = {
    "gerflor": "gerflor.fr", "tarkett": "tarkett.fr", "forbo": "forbo.com", "polyflor": "polyflor.com",
    "amtico": "amtico.com", "interface": "interface.com", "balsan": "balsan.com", "desso": "tarkett.fr",
    "weber": "fr.weber", "sika": "fra.sika.com", "mapei": "mapei.com", "bostik": "bostik.com",
    "parexlanko": "parexlanko.fr", "uzin": "uzin.fr", "cegecol": "cegecol.com",
    "kerakoll": "kerakoll.com", "ardex": "ardex.fr", "marazzi": "marazzi.fr", "porcelanosa": "porcelanosa.com",
    "novoceram": "novoceram.fr", "saloni": "saloni.com", "florim": "florim.com", "cerabati": "cerabati.com",
    "schluter": "schluter.fr", "profilpas": "profilpas.com", "dural": "dural.com",
    "quick-step": "quick-step.fr", "quickstep": "quick-step.fr", "berry alloc": "berryalloc.com",
    "egger": "egger.com", "wurth": "wurth.fr", "würth": "wurth.fr",
}

# Ce qui compte sur un chantier de sols. Chaque motif rend la valeur telle qu'écrite.
_CARACTERISTIQUES = (
    ("Classement UPEC", re.compile(r"\bU\s?\d(?:\s?s)?\s?P\s?\d(?:\s?s)?\s?E\s?\d(?:\s?/\s?\d)?\s?C\s?\d\b")),
    ("Classement au feu", re.compile(r"\b(?:A1|A2|B|C|D|E)fl\s?[-–]?\s?s\s?[12]\b")),
    ("Classement d'usage (EN ISO 10874)",
     re.compile(r"(?:classement|classe)(?: d.usage)?[^.\n]{0,40}?\b((?:2[1-3]|3[1-4]|4[1-3])(?:\s?[-/]\s?(?:2[1-3]|3[1-4]|4[1-3]))*)\b", re.I)),
    ("Épaisseur totale", re.compile(r"[ée]paisseur(?: totale)?[^\d\n]{0,40}(\d+(?:[.,]\d+)?\s?mm)", re.I)),
    ("Épaisseur de couche d'usure", re.compile(r"couche d.usure[^\d\n]{0,40}(\d+(?:[.,]\d+)?\s?mm)", re.I)),
    ("Efficacité acoustique (ΔLw)",
     re.compile(r"(?:ΔL\s?w|Delta\s?Lw|efficacit[ée] acoustique|isolation aux bruits de choc)[^\d\n]{0,30}(\d{1,2}\s?dB)", re.I)),
    ("Poids", re.compile(r"poids[^\d\n]{0,30}(\d+(?:[.,]\d+)?\s?k?g\s?/\s?m[²2])", re.I)),
    ("Glissance", re.compile(r"\b(R\s?(?:9|10|11|12|13))\b(?![\d,.])")),
    ("Avis technique / DTA",
     re.compile(r"(?:Avis Technique|DTA|ATec|Document Technique d.Application)[^\d\n]{0,25}(\d{1,2}(?:\.\d)?\s?/\s?\d{2}\s?-\s?\d{3,5}(?:_V\d)?)", re.I)),
)
MAX_CONTENU = 9000


def fabricant(texte: str) -> tuple[str, str] | None:
    """(marque, site) reconnus dans le nom du produit ou la marque donnée."""
    bas = (texte or "").lower()
    for marque, site in FABRICANTS.items():
        if re.search(rf"(?<![a-z]){re.escape(marque)}(?![a-z])", bas):
            return marque, site
    return None


def requetes(produit: str, marque: str = "") -> list[str]:
    """Les recherches à mener, la plus ciblée d'abord."""
    nom = " ".join(f"{marque} {produit}".split()).strip()
    connu = fabricant(nom)
    sortie = []
    if connu:
        sortie.append(f"site:{connu[1]} {produit} fiche technique")
    sortie.append(f"{nom} fiche technique pdf")
    return sortie


def relever(texte: str, source: str) -> list[dict]:
    """Les caractéristiques trouvées dans un texte, chacune avec sa source. PURE."""
    trouve = []
    t = " ".join(str(texte or "").split())
    for nom, motif in _CARACTERISTIQUES:
        m = motif.search(t)
        if m:
            valeur = (m.group(1) if m.groups() else m.group(0)).strip()
            trouve.append({"caracteristique": nom, "valeur": valeur, "source": source})
    return trouve


def _pages(contenu: str) -> list[tuple[str, str]]:
    """Le texte combiné d'une recherche → [(adresse, texte)]."""
    morceaux = []
    for bloc in re.split(r"\n\n---\n\n", contenu or ""):
        m = re.match(r"Source : (\S+)", bloc)
        if m:
            morceaux.append((m.group(1), bloc))
    return morceaux


def _rang(url: str, site: str | None) -> tuple:
    """Le site du fabricant d'abord, un PDF avant une page."""
    hote = urlparse(url).netloc.lower()
    return (0 if site and hote.endswith(site) else 1,
            0 if url.lower().split("?")[0].endswith(".pdf") else 1)


async def fiche_produit(data: dict, user) -> dict:
    from browser.tools import fetch_url, web_search

    produit = str(data.get("produit") or data.get("nom") or data.get("reference") or "").strip()
    marque = str(data.get("marque") or data.get("fabricant") or "").strip()
    url = str(data.get("url") or "").strip()
    if not produit and not url:
        return {"erreur": "Donne le produit (nom commercial, référence) dans `produit`, et la marque si tu la connais."}
    connu = fabricant(f"{marque} {produit}")
    site = connu[1] if connu else None
    uid = str(getattr(user, "id", "") or "")

    pages: list[tuple[str, str]] = []
    sources: list[str] = []
    if url:
        r = await fetch_url(url=url, user_id=uid, agent_id="agent1", reason="fiche produit", capture=False)
        if r.get("success"):
            pages.append((url, str(r.get("content") or "")))
            sources.append(url)
    else:
        for q in requetes(produit, marque):
            r = await web_search(query=q, user_id=uid, agent_id="agent1", max_results=4)
            for adresse in r.get("sources") or []:
                if adresse and adresse not in sources:
                    sources.append(adresse)
            deja = {x[0] for x in pages}
            pages += [p for p in _pages(str(r.get("content") or "")) if p[0] not in deja]
            # La fiche du fabricant suffit : on ne va chercher ailleurs que si elle manque.
            if any(_rang(a, site)[0] == 0 for a, _ in pages):
                break
    if not pages:
        return {"produit": produit, "trouve": False, "sources": sources,
                "a_faire": ("Aucune fiche lisible trouvée. Dis-le, puis essaie `chercher_web` avec d'autres "
                            "termes (référence exacte, gamme) ou `naviguer` sur le site du fabricant"
                            + (f" ({site})" if site else "") + ". N'invente aucune caractéristique.")}
    pages.sort(key=lambda p: _rang(p[0], site))
    releve, vues = [], set()
    for adresse, texte in pages:
        for c in relever(texte, adresse):
            if c["caracteristique"] not in vues:
                vues.add(c["caracteristique"])
                releve.append(c)
    sortie = {
        "produit": " ".join(f"{marque} {produit}".split()) or url,
        "fabricant": site, "trouve": True,
        "source_principale": pages[0][0],
        "caracteristiques": releve,
        "contenu": "\n\n---\n\n".join(t for _, t in pages)[:MAX_CONTENU],
        "sources": sources[:8],
        "a_savoir": ("Information EXTERNE, lue chez le fabricant ou sur le web : cite l'adresse de chaque "
                     "valeur. Le tableau est un RELEVÉ automatique : une caractéristique absente du "
                     "tableau n'est pas absente de la fiche — lis `contenu`."),
        "a_faire": ("Réponds avec les caractéristiques utiles à la demande, chacune avec sa source. "
                    "Confronte-les à ce qu'exige le document de la maison s'il y en a un (CCTP, DPGF, devis) "
                    "et dis ce qui est conforme ou non. Sois force de proposition : un produit « ou "
                    "équivalent », une référence introuvable, un classement insuffisant appellent une "
                    "ou deux alternatives — cherche-les (`fiche_produit` sur l'alternative) plutôt que "
                    "de les citer de mémoire."),
    }
    if releve:
        sortie["bloc_ui"] = {"type": "table", "titre": f"Fiche produit — {sortie['produit']}"[:120],
                             "columns": ["Caractéristique", "Valeur relevée", "Source"],
                             "rows": [[c["caracteristique"], c["valeur"], c["source"]] for c in releve]}
        sortie["bloc_garanti"] = True
    return sortie


from skills.registre import Declaration  # noqa: E402

SKILLS = {
    "fiche_produit": Declaration(
        fonction=fiche_produit,
        description=(
            "LA FICHE TECHNIQUE D'UN PRODUIT, lue chez le FABRICANT (site officiel, fiche PDF) : "
            "classement UPEC, classement au feu, classement d'usage, épaisseur, couche d'usure, "
            "efficacité acoustique, poids, glissance, avis technique — chaque valeur avec "
            "l'adresse où elle a été lue. À utiliser DE TOI-MÊME dès qu'un produit, une marque ou "
            "une référence est cité (CCTP, DPGF, devis ou facture fournisseur, question) et qu'une "
            "caractéristique compte : vérifier la conformité au CCTP, comparer des « équivalents », "
            "compléter un mémoire technique, répondre à une question de caractéristique. `produit` : "
            "le nom commercial ou la référence ; `marque` si connue ; `url` si tu as déjà l'adresse "
            "de la fiche. JAMAIS pour les données internes (clients, devis, chantiers)."),
        optionnels=["produit", "marque", "url", "cherche"],
        effet="lecture",
        libelle="je lis la fiche du fabricant"),
}
