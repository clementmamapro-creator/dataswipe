"""
export.py

Génère un fichier Word (.docx) ou PDF à partir d'un texte Markdown simple
(titres #/##/###, listes -, **gras**, *italique*, séparateurs ---) tel que renvoyé
par l'assistant IA : CV adapté, lettre de motivation.

  - Word : python-docx (déjà nécessaire pour lire les CV .docx)
  - PDF  : reportlab (à ajouter à requirements.txt)
"""

from __future__ import annotations

import io
import re

INLINE = re.compile(r"(\*\*[^*\n]+\*\*|\*[^*\n]+\*)")
HEADING = re.compile(r"^(#{1,3})\s+(.*)$")
# Puces : -, *, • mais aussi les symboles que l'IA utilise parfois (▪ ► ➤ ✓ ✔ ▸ – —…) :
# sans cela ils restaient dans le texte et devenaient « ? » dans le PDF.
BULLET = re.compile(r"^\s*[-*•▪▫●○◦■□◆◇►▶➤➢✓✔✅✦★☆‣⁃▸▹–—·]\uFE0F?\s+(.*)$")
NUMBERED = re.compile(r"^\s*\d+[.)]\s+(.*)$")
RULE = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")

INK = (0x11, 0x14, 0x2B)
ACCENT = (0x2F, 0x3B, 0xFF)


def _blocks(markdown: str) -> list[tuple[str, str]]:
    """Découpe en blocs ('h1'|'h2'|'h3'|'bullet'|'num'|'rule'|'p', texte)."""
    out: list[tuple[str, str]] = []
    para: list[str] = []

    def flush() -> None:
        if para:
            out.append(("p", "\n".join(para)))
            para.clear()

    for raw in markdown.replace("\r", "").split("\n"):
        line = raw.rstrip()
        if not line.strip():
            flush()
            continue
        if RULE.match(line):
            flush(); out.append(("rule", "")); continue
        m = HEADING.match(line)
        if m:
            flush(); out.append((f"h{len(m.group(1))}", m.group(2).strip())); continue
        m = BULLET.match(line)
        if m:
            flush(); out.append(("bullet", m.group(1).strip())); continue
        m = NUMBERED.match(line)
        if m:
            flush(); out.append(("num", m.group(1).strip())); continue
        para.append(line.strip())
    flush()
    return out


def _runs(text: str) -> list[tuple[str, bool, bool]]:
    """Découpe un texte en (fragment, gras, italique)."""
    runs = []
    for part in INLINE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            runs.append((part[2:-2], True, False))
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            runs.append((part[1:-1], False, True))
        else:
            runs.append((part, False, False))
    return runs



# ------------------------------------------------------------------ Photo & en-tête
def prepare_photo(data_url: str) -> bytes | None:
    """Photo envoyée par le navigateur (data URL) -> JPEG carré 480 px. None si absente.
    Lève ValueError si le fichier n'est pas une image exploitable."""
    if not data_url:
        return None
    import base64

    from PIL import Image, ImageOps

    try:
        raw = base64.b64decode(data_url.split(",", 1)[-1])
        if len(raw) > 3_000_000:
            raise ValueError("photo trop lourde")
        im = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
    except Exception as e:  # noqa: BLE001
        raise ValueError("Photo illisible : utilisez un fichier JPG ou PNG") from e
    w, h = im.size
    side = min(w, h)
    left, top = (w - side) // 2, ((h - side) // 4 if h > side else 0)   # portrait : cadrage plutôt haut (visage)
    im = im.crop((left, top, left + side, top + side)).resize((480, 480))
    out = io.BytesIO()
    im.save(out, "JPEG", quality=88)
    return out.getvalue()


def _split_header(blocks: list[tuple[str, str]], kind: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Sépare l'en-tête (nom/contacts du CV ; expéditeur/destinataire/date/objet de la lettre) du corps."""
    if kind == "letter":
        idx = next((i for i, (k, _) in enumerate(blocks) if k == "rule"), None)
        if idx is not None and 1 <= idx <= 6 and all(k == "p" for k, _ in blocks[:idx]):
            return blocks[:idx], blocks[idx + 1:]
    elif kind == "cv":
        idx = next((i for i, (k, _) in enumerate(blocks) if k == "h2"), len(blocks))
        if blocks and blocks[0][0] == "h1" and idx <= 6:
            return blocks[:idx], blocks[idx:]
    return [], blocks

# ------------------------------------------------------------------ Word
def to_docx(markdown: str, title: str = "", kind: str = "", photo: bytes | None = None) -> bytes:
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    doc = Document()
    for s in doc.sections:
        s.top_margin = s.bottom_margin = Cm(1.8)
        s.left_margin = s.right_margin = Cm(2.0)
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)
    normal.paragraph_format.space_after = Pt(4)
    normal.paragraph_format.line_spacing = 1.12
    if title:
        doc.core_properties.title = title

    def add_runs(par, text, size=None, color=None, bold_all=False):
        for fragment, bold, italic in _runs(text):
            lines = fragment.split("\n")
            for i, piece in enumerate(lines):
                run = par.add_run(piece)
                run.bold = bold or bold_all
                run.italic = italic
                if size:
                    run.font.size = Pt(size)
                if color:
                    run.font.color.rgb = RGBColor(*color)
                if i < len(lines) - 1:
                    run.add_break(WD_BREAK.LINE)

    def bottom_border(par, color="2F3BFF"):
        p_pr = par._p.get_or_add_pPr()
        borders = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        for k, v in (("w:val", "single"), ("w:sz", "6"), ("w:space", "1"), ("w:color", color)):
            bottom.set(qn(k), v)
        borders.append(bottom)
        p_pr.append(borders)

    blocks = _blocks(markdown)
    head, blocks = _split_header(blocks, kind)

    def put(container, text, size=None, color=None, bold_all=False, align=None, after=4, first=False):
        p = container.paragraphs[0] if first else container.add_paragraph()
        add_runs(p, text, size=size, color=color, bold_all=bold_all)
        p.paragraph_format.space_after = Pt(after)
        if align:
            p.alignment = align
        return p

    if head:
        left = doc
        table = None
        if photo:
            table = doc.add_table(rows=1, cols=2)
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            table.autofit = False
            lc, rc = table.rows[0].cells
            lc.width, rc.width = Cm(13.4), Cm(3.6)
            left = lc
            rp = rc.paragraphs[0]; rp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            rp.add_run().add_picture(io.BytesIO(photo), width=Cm(3.2))
        n_left = 0

        def L(text, **kw):
            nonlocal n_left
            first = table is not None and n_left == 0
            n_left += 1
            return put(left, text, first=first, **kw)

        if kind == "cv":
            for i, (k, text) in enumerate(head):
                if k == "h1":
                    L(text, size=22, color=INK, bold_all=True, after=2)
                elif i == 1:
                    L(text, size=12, color=ACCENT, bold_all=True, after=2)
                else:
                    L(text, size=9.5, color=(0x55, 0x5B, 0x6E), after=2)
            sp = doc.add_paragraph(); sp.paragraph_format.space_after = Pt(0)
        else:   # lettre : expéditeur à gauche (photo à droite), destinataire et date à droite, objet à gauche
            for i, (k, text) in enumerate(head):
                if i == 0:
                    L(text, after=14)
                elif i == len(head) - 1:
                    doc.add_paragraph().paragraph_format.space_after = Pt(0)
                    put(doc, text, after=12)
                else:
                    put(doc, text, align=WD_ALIGN_PARAGRAPH.RIGHT, after=10)

    for kind, text in blocks:
        if kind == "h1":
            p = doc.add_paragraph(); add_runs(p, text, size=20, color=INK, bold_all=True)
            p.paragraph_format.space_after = Pt(2)
        elif kind == "h2":
            p = doc.add_paragraph(); add_runs(p, text, size=12, color=ACCENT, bold_all=True)
            p.paragraph_format.space_before = Pt(10); p.paragraph_format.space_after = Pt(4)
            bottom_border(p)
        elif kind == "h3":
            p = doc.add_paragraph(); add_runs(p, text, size=11, color=INK, bold_all=True)
            p.paragraph_format.space_before = Pt(6); p.paragraph_format.space_after = Pt(2)
        elif kind == "bullet":
            p = doc.add_paragraph(style="List Bullet"); add_runs(p, text)
        elif kind == "num":
            p = doc.add_paragraph(style="List Number"); add_runs(p, text)
        elif kind == "rule":
            continue
        else:
            p = doc.add_paragraph(); add_runs(p, text)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------ PDF
# Emojis et pictogrammes (📍 📞 ✉️ 🔗 🚗 …) : la police PDF standard ne les contient pas.
EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2190-\u21FF\u2300-\u23FF\u2460-\u24FF\u25A0-\u27BF\u2900-\u297F"
                   "\u2B00-\u2BFF\uFE0E\uFE0F\u200D\u20E3]")
REPLACE = {"→": "->", "←": "<-", "…": "...", "≈": "~", "≥": ">=", "≤": "<=", "×": "x", "\u00a0": " ", "\u202f": " ",
           "\u2011": "-", "\u2212": "-", "★": "", "☆": ""}


def _pdf_text(text: str) -> str:
    """Helvetica (police PDF standard) ne gère que le jeu latin-1/cp1252 : les emojis sont
    retirés (un CV professionnel n'en a pas besoin) et les symboles courants remplacés ;
    tout autre caractère non géré est supprimé, jamais affiché comme « ? » ou un carré."""
    for a, b in REPLACE.items():
        text = text.replace(a, b)
    text = EMOJI.sub("", text)
    text = text.encode("cp1252", "ignore").decode("cp1252")
    text = re.sub(r"[ \t]{2,}", " ", text)
    return re.sub(r"(?m)^[ \t]+|[ \t]+$", "", text)


def to_pdf(markdown: str, title: str = "", kind: str = "", photo: bytes | None = None) -> bytes:
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import HRFlowable, Image, ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    ink = colors.Color(*(c / 255 for c in INK))
    accent = colors.Color(*(c / 255 for c in ACCENT))

    base = ParagraphStyle("base", fontName="Helvetica", fontSize=10, leading=14, textColor=ink, alignment=TA_LEFT, spaceAfter=4)
    h1 = ParagraphStyle("h1", parent=base, fontName="Helvetica-Bold", fontSize=19, leading=23, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold", fontSize=11.5, leading=15, textColor=accent, spaceBefore=10, spaceAfter=2)
    h3 = ParagraphStyle("h3", parent=base, fontName="Helvetica-Bold", fontSize=10.5, leading=14, spaceBefore=6, spaceAfter=1)

    def markup(text: str) -> str:
        out = []
        for fragment, bold, italic in _runs(_pdf_text(text)):
            piece = escape(fragment).replace("\n", "<br/>")
            if bold:
                piece = f"<b>{piece}</b>"
            if italic:
                piece = f"<i>{piece}</i>"
            out.append(piece)
        return "".join(out)

    story: list = []
    blocks = _blocks(markdown)
    head, blocks = _split_header(blocks, kind)
    if head:
        grey = ParagraphStyle("grey", parent=base, textColor=colors.Color(.33, .36, .43), fontSize=9, spaceAfter=2)
        sub = ParagraphStyle("sub", parent=base, fontName="Helvetica-Bold", fontSize=11.5, textColor=accent, spaceAfter=2)
        right = ParagraphStyle("right", parent=base, alignment=TA_RIGHT, spaceAfter=10)
        if kind == "cv":
            cells = []
            for i, (k, text) in enumerate(head):
                cells.append(Paragraph(markup(text), h1 if k == "h1" else sub if i == 1 else grey))
        else:
            cells = [Paragraph(markup(head[0][1]), base)]
        if photo:
            img = Image(io.BytesIO(photo), width=3.1 * cm, height=3.1 * cm)
            t = Table([[cells, img]], colWidths=[13.6 * cm, 3.4 * cm])
            t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
            story.append(t)
        else:
            story.extend(cells)
        if kind != "cv":
            story.append(Spacer(1, 10))
            for i, (k, text) in enumerate(head[1:], start=1):
                if i == len(head) - 1:
                    story.append(Spacer(1, 6)); story.append(Paragraph(markup(text), ParagraphStyle("obj", parent=base, spaceAfter=12)))
                else:
                    story.append(Paragraph(markup(text), right))
        else:
            story.append(Spacer(1, 4))
    pending: list = []
    pending_kind = ""

    def flush_list() -> None:
        nonlocal pending, pending_kind
        if pending:
            story.append(ListFlowable(
                [ListItem(Paragraph(markup(t), base), leftIndent=14) for t in pending],
                bulletType="bullet" if pending_kind == "bullet" else "1",
                start="•" if pending_kind == "bullet" else 1, leftIndent=14,
                bulletFontName="Helvetica", bulletFontSize=10, bulletFormat=None if pending_kind == "bullet" else "%s."))
            pending = []

    for kind, text in blocks:
        if kind in ("bullet", "num"):
            if pending and pending_kind != kind:
                flush_list()
            pending_kind = kind; pending.append(text); continue
        flush_list()
        if kind == "h1":
            story.append(Paragraph(markup(text), h1))
        elif kind == "h2":
            story.append(Paragraph(markup(text), h2))
            story.append(HRFlowable(width="100%", thickness=0.8, color=accent, spaceAfter=4))
        elif kind == "h3":
            story.append(Paragraph(markup(text), h3))
        elif kind == "rule":
            story.append(Spacer(1, 4))
        else:
            story.append(Paragraph(markup(text), base))
    flush_list()

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm,
                      bottomMargin=1.8 * cm, title=title or "Document").build(story)
    return buf.getvalue()