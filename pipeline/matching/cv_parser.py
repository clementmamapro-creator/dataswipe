"""
cv_parser.py

Extrait le texte brut d'un CV (PDF ou Word) pour ensuite y détecter les
compétences via extract_skills(). Pas d'OCR ici — suppose un CV avec du
texte réellement sélectionnable (pas un scan image), cas très majoritaire
pour des CV générés numériquement (Word, LaTeX, Canva export PDF...).
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("dataswipe.matching.cv_parser")


def parse_cv(file_path: str | Path) -> str:
    """Extrait le texte brut d'un CV. Lève ValueError si le format n'est
    pas supporté, ou si aucun texte n'a pu être extrait (CV scanné en image,
    par exemple — non géré ici, nécessiterait de l'OCR)."""
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        text = _parse_pdf(path)
    elif suffix in (".docx",):
        text = _parse_docx(path)
    elif suffix == ".doc":
        raise ValueError(
            "Format .doc (Word 97-2003) non supporté — merci de convertir en .docx ou .pdf"
        )
    else:
        raise ValueError(f"Format de fichier non supporté : {suffix}")

    if not text or not text.strip():
        raise ValueError(
            "Aucun texte extractible dans ce CV — s'il s'agit d'un scan/image, "
            "l'extraction OCR n'est pas supportée pour l'instant."
        )

    return text


def _parse_pdf(path: Path) -> str:
    import pdfplumber

    chunks = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                chunks.append(page_text)
    return "\n".join(chunks)


def _parse_docx(path: Path) -> str:
    import docx

    document = docx.Document(path)
    paragraphs = [p.text for p in document.paragraphs if p.text]

    # Le texte dans les tableaux (souvent utilisés pour la mise en page
    # de CV) n'est pas capturé par document.paragraphs — on l'ajoute.
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text:
                    paragraphs.append(cell.text)

    return "\n".join(paragraphs)
