"""
LE CONTRÔLE D'UN LIVRABLE AVANT QU'IL SORTE (16/09, audit D-02/S-02).

Un document repris d'un original ne doit rien perdre de ce qu'on n'a pas
demandé de changer. « Le logo est toujours là » ne se déduit pas du code qui a
appelé `save()` : il se MESURE sur le fichier produit, rouvert. On compare donc
l'original et le résultat sur ce qui casse en pratique :

  · le fichier se rouvre (zip sain, document lisible par python-docx) ;
  · autant d'images (`word/media`), de dessins, de relations, de sections,
    d'en-têtes et de pieds, de styles, de tableaux ;
  · aucun texte n'a disparu hors des remplacements (le nombre de paragraphes
    reste le même).

Ce contrôle est STRUCTUREL et local : il ne prétend pas juger le rendu visuel
(une comparaison d'images PDF avant/après reste une option pour les modèles
importants). Il ne lève jamais : il rend {ok, problemes, mesures}.
"""
from __future__ import annotations

import io
import re
import zipfile

_DESSINS = re.compile(rb"<w:(?:drawing|pict)\b")
_STYLES = re.compile(rb"<w:style\b")
_TABLEAUX = re.compile(rb"<w:tbl>")
_PARAGRAPHES = re.compile(rb"<w:p[ >]")
_RELATIONS = re.compile(rb"<Relationship\b")


def mesurer_docx(octets: bytes) -> dict:
    """Ce qui caractérise la structure d'un .docx, compté."""
    mesures = {"lisible": False}
    try:
        with zipfile.ZipFile(io.BytesIO(octets)) as z:
            if z.testzip() is not None:
                return mesures
            noms = z.namelist()
            parties = [n for n in noms if re.fullmatch(r"word/(document|header\d*|footer\d*)\.xml", n)]
            contenu = {n: z.read(n) for n in parties}
            mesures.update({
                "medias": sum(1 for n in noms if n.startswith("word/media/")),
                "entetes": sum(1 for n in noms if re.fullmatch(r"word/header\d*\.xml", n)),
                "pieds": sum(1 for n in noms if re.fullmatch(r"word/footer\d*\.xml", n)),
                "dessins": sum(len(_DESSINS.findall(x)) for x in contenu.values()),
                "tableaux": sum(len(_TABLEAUX.findall(x)) for x in contenu.values()),
                "paragraphes": sum(len(_PARAGRAPHES.findall(x)) for x in contenu.values()),
                "relations": sum(len(_RELATIONS.findall(z.read(n)))
                                 for n in noms if n.startswith("word/_rels/") and n.endswith(".rels")),
                "styles": len(_STYLES.findall(z.read("word/styles.xml"))) if "word/styles.xml" in noms else 0,
                "sections": len(re.findall(rb"<w:sectPr\b", contenu.get("word/document.xml", b""))),
            })
        import docx
        docx.Document(io.BytesIO(octets))
        mesures["lisible"] = True
    except Exception:  # noqa: BLE001 — un fichier illisible est une MESURE, pas une panne
        mesures["lisible"] = False
    return mesures


_LIBELLES = {"medias": "image(s)", "entetes": "en-tête(s)", "pieds": "pied(s) de page",
             "dessins": "dessin(s)", "tableaux": "tableau(x)", "paragraphes": "paragraphe(s)",
             "relations": "relation(s) interne(s)", "styles": "style(s)", "sections": "section(s)"}


def comparer_docx(avant: bytes, apres: bytes) -> dict:
    """L'original et le résultat ont-ils la même structure ?"""
    m_avant, m_apres = mesurer_docx(avant), mesurer_docx(apres)
    problemes = []
    if not m_apres.get("lisible"):
        problemes.append("le fichier produit ne se rouvre pas")
    else:
        for cle, libelle in _LIBELLES.items():
            a, b = m_avant.get(cle), m_apres.get(cle)
            if a is not None and b is not None and a != b:
                problemes.append(f"{libelle} : {a} dans l'original, {b} dans le résultat")
    return {"ok": not problemes, "problemes": problemes, "avant": m_avant, "apres": m_apres}
