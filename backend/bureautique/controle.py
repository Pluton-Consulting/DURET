"""Contrôle local d'un DOCX : structure XML, contenu prévu et ressources.

Les nombres d'éléments ne dépendent pas de leur sérialisation. Les textes
attendus sont capturés après les substitutions et avant la sauvegarde ; ils
ne remplacent pas la recette de l'algorithme ni une comparaison visuelle.
"""
from __future__ import annotations
import hashlib
import io
import re
import zipfile
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def textes_xml(octets: bytes) -> list:
    """Texte et séparateurs Word, sans dépendre des préfixes XML."""
    return [(el.tag, el.text or "", tuple(sorted(el.attrib.items())))
            for el in ET.fromstring(octets).iter()
            if el.tag in {W + t for t in ("t", "instrText", "tab", "br", "cr")}]


def _structure(el):
    return (el.tag, tuple(sorted(el.attrib.items())), el.text or "",
            tuple(_structure(enfant) for enfant in el))


def mesurer_docx(octets: bytes) -> dict:
    mesures = {"lisible": False}
    try:
        with zipfile.ZipFile(io.BytesIO(octets)) as z:
            if z.testzip() is not None:
                return mesures
            noms = z.namelist()
            parties = [n for n in noms if re.fullmatch(r"word/(document|header\d*|footer\d*)\.xml", n)]
            racines = [ET.fromstring(z.read(n)) for n in parties]
            def compter(*tags):
                return sum(el.tag in {W + t for t in tags} for r in racines for el in r.iter())
            mesures.update({
                "medias": sum(n.startswith("word/media/") for n in noms),
                "entetes": sum(bool(re.fullmatch(r"word/header\d*\.xml", n)) for n in noms),
                "pieds": sum(bool(re.fullmatch(r"word/footer\d*\.xml", n)) for n in noms),
                "dessins": compter("drawing", "pict"), "tableaux": compter("tbl"),
                "paragraphes": compter("p"), "sections": compter("sectPr"),
                "relations": sum(len(ET.fromstring(z.read(n))) for n in noms
                                 if n.startswith("word/_rels/") and n.endswith(".rels")),
                "styles": sum(el.tag == W + "style" for el in ET.fromstring(z.read("word/styles.xml")).iter())
                          if "word/styles.xml" in noms else 0,
            })
        import docx
        docx.Document(io.BytesIO(octets))
        mesures["lisible"] = True
    except Exception:
        mesures["lisible"] = False
    return mesures


_LIBELLES = {"medias": "image(s)", "entetes": "en-tête(s)", "pieds": "pied(s) de page",
             "dessins": "dessin(s)", "tableaux": "tableau(x)", "paragraphes": "paragraphe(s)",
             "relations": "relation(s) interne(s)", "styles": "style(s)", "sections": "section(s)"}


def comparer_docx(avant: bytes, apres: bytes, *, textes_attendus: dict | None = None) -> dict:
    m_avant, m_apres = mesurer_docx(avant), mesurer_docx(apres)
    problemes = []
    if not m_avant.get("lisible") or not m_apres.get("lisible"):
        problemes.append("l'original ou le fichier produit ne se rouvre pas")
    else:
        for cle, libelle in _LIBELLES.items():
            if m_avant.get(cle) != m_apres.get(cle):
                problemes.append(f"{libelle} : {m_avant.get(cle)} dans l'original, {m_apres.get(cle)} dans le résultat")
        try:
            with zipfile.ZipFile(io.BytesIO(avant)) as za, zipfile.ZipFile(io.BytesIO(apres)) as zb:
                for nom in za.namelist():
                    if not nom.startswith("word/"):
                        continue
                    if nom not in zb.namelist():
                        problemes.append(f"partie supprimée : {nom}")
                        continue
                    a, b = za.read(nom), zb.read(nom)
                    if nom.startswith("word/media/"):
                        if hashlib.sha256(a).digest() != hashlib.sha256(b).digest():
                            problemes.append(f"média modifié : {nom}")
                    elif nom.endswith(".rels"):
                        relations = lambda data: sorted(tuple(sorted(e.attrib.items())) for e in ET.fromstring(data))
                        if relations(a) != relations(b):
                            problemes.append(f"cibles de relations modifiées : {nom}")
                    elif nom.endswith(".xml"):
                        ra, rb = ET.fromstring(a), ET.fromstring(b)
                        attendus = (textes_attendus or {}).get(nom, textes_xml(a))
                        if textes_xml(b) != attendus:
                            problemes.append(f"contenu différent des substitutions prévues : {nom}")
                        invariants = {W + t for t in ("sectPr", "pPr", "rPr", "tblPr", "tcPr", "style")}
                        if [_structure(e) for e in ra.iter() if e.tag in invariants] != [
                                _structure(e) for e in rb.iter() if e.tag in invariants]:
                            problemes.append(f"styles, marges ou propriétés modifiés : {nom}")
        except Exception:
            problemes.append("comparaison des ressources impossible")
    return {"ok": not problemes, "problemes": problemes, "avant": m_avant, "apres": m_apres}
