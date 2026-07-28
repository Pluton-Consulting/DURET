"""
Lecture des fichiers déposés à l'import : CSV, Excel, Word, PDF, texte.

Deux familles de résultats, parce qu'elles ne s'ingèrent pas pareil :

  * TABULAIRE (csv, xlsx, xls) -> une LIGNE = un document. Un export de milliers
    de lignes ingéré en un seul bloc serait découpé arbitrairement et la recherche
    remonterait des morceaux sans rapport ; ligne par ligne, chaque chantier /
    devis / client devient un document retrouvable, avec un identifiant stable.

  * DOCUMENT (pdf, docx, txt, md) -> un FICHIER = un document, découpé ensuite
    par le pipeline d'ingestion.

Toutes les fonctions sont synchrones et bornées (nb de lignes, nb de pages) :
les appeler via asyncio.to_thread pour ne pas bloquer la boucle d'événements.
"""
from __future__ import annotations

import csv
import io
import logging
from typing import Optional

logger = logging.getLogger("duret.ingestion.parsers")

# Bornes anti-fichier piégé / anti-saturation mémoire.
MAX_LIGNES = 20000
MAX_PAGES_PDF = 300
MAX_COLONNES = 200

ENCODAGES = ("utf-8-sig", "utf-8", "cp1252", "latin-1")

EXT_TABULAIRE = (".csv", ".xlsx", ".xls", ".xlsm")
EXT_DOCUMENT = (".pdf", ".docx", ".txt", ".md")


class FichierNonSupporte(Exception):
    """Extension inconnue ou dépendance de lecture absente."""


def famille(nom: str) -> Optional[str]:
    """'tabulaire', 'document', ou None si l'extension n'est pas gérée."""
    n = (nom or "").lower()
    if n.endswith(EXT_TABULAIRE):
        return "tabulaire"
    if n.endswith(EXT_DOCUMENT):
        return "document"
    return None


def _decoder(brut: bytes) -> str:
    """Décode en essayant les encodages usuels (Excel FR écrit en cp1252)."""
    for enc in ENCODAGES:
        try:
            return brut.decode(enc)
        except UnicodeDecodeError:
            continue
    return brut.decode("utf-8", errors="replace")


def lire_csv(brut: bytes) -> tuple[list[str], list[dict]]:
    texte = _decoder(brut)
    echantillon = texte[:8192]
    try:
        sep = csv.Sniffer().sniff(echantillon, delimiters=";,\t|").delimiter
    except csv.Error:
        sep = ";" if echantillon.count(";") > echantillon.count(",") else ","

    lecteur = csv.DictReader(texte.splitlines(), delimiter=sep)
    entetes = [(c or "").strip() for c in (lecteur.fieldnames or [])][:MAX_COLONNES]
    lignes = []
    for i, l in enumerate(lecteur):
        if i >= MAX_LIGNES:
            logger.warning("CSV tronqué à %d lignes", MAX_LIGNES)
            break
        if any((v or "").strip() for v in l.values()):
            lignes.append({(k or "").strip(): (v or "").strip() for k, v in l.items() if k})
    return entetes, lignes


def lire_excel(brut: bytes) -> tuple[list[str], list[dict]]:
    try:
        from openpyxl import load_workbook
    except ImportError as e:
        raise FichierNonSupporte("Lecture Excel indisponible (openpyxl absent)") from e

    wb = load_workbook(io.BytesIO(brut), read_only=True, data_only=True)
    ws = wb.active                      # 1re feuille — la plus courante pour un export
    iterateur = ws.iter_rows(values_only=True)

    entetes: list[str] = []
    for ligne in iterateur:             # 1re ligne non vide = en-têtes
        if ligne and any(c is not None and str(c).strip() for c in ligne):
            entetes = [str(c).strip() if c is not None else "" for c in ligne][:MAX_COLONNES]
            break

    lignes = []
    for i, ligne in enumerate(iterateur):
        if i >= MAX_LIGNES:
            logger.warning("Excel tronqué à %d lignes", MAX_LIGNES)
            break
        if not ligne or not any(c is not None and str(c).strip() for c in ligne):
            continue
        d = {}
        for entete, valeur in zip(entetes, ligne):
            if entete and valeur is not None and str(valeur).strip():
                d[entete] = str(valeur).strip()
        if d:
            lignes.append(d)
    wb.close()
    return [e for e in entetes if e], lignes


def lire_pdf(brut: bytes) -> str:
    try:
        import pdfplumber
    except ImportError as e:
        raise FichierNonSupporte("Lecture PDF indisponible (pdfplumber absent)") from e
    morceaux = []
    with pdfplumber.open(io.BytesIO(brut)) as pdf:
        for i, page in enumerate(pdf.pages):
            if i >= MAX_PAGES_PDF:
                logger.warning("PDF tronqué à %d pages", MAX_PAGES_PDF)
                break
            morceaux.append(page.extract_text() or "")
    return "\n\n".join(morceaux).strip()


def lire_docx(brut: bytes) -> str:
    try:
        import docx  # python-docx
    except ImportError as e:
        raise FichierNonSupporte("Lecture Word indisponible (python-docx absent)") from e
    d = docx.Document(io.BytesIO(brut))
    morceaux = [p.text for p in d.paragraphs if p.text and p.text.strip()]
    # Les tableaux Word portent souvent l'essentiel (métrés, postes, quantités).
    for table in d.tables:
        for row in table.rows:
            cellules = [c.text.strip() for c in row.cells if c.text and c.text.strip()]
            if cellules:
                morceaux.append(" | ".join(cellules))
    return "\n".join(morceaux).strip()


def ligne_en_texte(ligne: dict) -> str:
    """« Colonne : valeur » — lisible par le modèle, et les libellés participent
    eux-mêmes à la recherche sémantique."""
    return "\n".join(f"{k} : {v}" for k, v in ligne.items() if str(v).strip())


def analyser(nom: str, brut: bytes) -> dict:
    """Lit le fichier et retourne sa structure, sans rien écrire.

    Retour : {kind, columns, rows, text, documents_estimes}
    """
    fam = famille(nom)
    if fam is None:
        raise FichierNonSupporte(
            f"Format non géré : {nom}. Formats acceptés : "
            "CSV, Excel (.xlsx/.xls), Word (.docx), PDF, texte (.txt/.md)."
        )

    n = nom.lower()
    if fam == "tabulaire":
        entetes, lignes = lire_csv(brut) if n.endswith(".csv") else lire_excel(brut)
        if not lignes:
            raise FichierNonSupporte("Fichier tabulaire vide ou illisible (aucune ligne de données).")
        return {"kind": "tabulaire", "columns": entetes, "rows": lignes,
                "text": None, "documents_estimes": len(lignes)}

    if n.endswith(".pdf"):
        texte = lire_pdf(brut)
    elif n.endswith(".docx"):
        texte = lire_docx(brut)
    else:
        texte = _decoder(brut).strip()

    if not texte:
        raise FichierNonSupporte(
            "Aucun texte extractible. S'il s'agit d'un PDF scanné (image), "
            "il faut d'abord le passer par une reconnaissance de caractères."
        )
    return {"kind": "document", "columns": [], "rows": [],
            "text": texte, "documents_estimes": 1}
