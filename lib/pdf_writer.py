"""
pdf_writer.py - a tiny PDF writer (standard library only) for one-page sheets:
lines, rectangles, dashed lines and text in Helvetica. Enough for a lathe sheet.

Coordinates are in points (1/72 in) with (0, 0) at the BOTTOM-left, like PDF.

    page = PdfPage(792, 612)            # US Letter, landscape
    page.text(36, 570, "Hello", size=18, bold=True)
    page.line(36, 560, 756, 560)
    write_pdf("out.pdf", [page], title="Lathe sheet")
"""

from __future__ import annotations

import datetime
import logging
import os
import tempfile
from typing import List, Optional, Sequence, Tuple

log = logging.getLogger("gusset.pdf")

PT_PER_IN = 72.0
# Average Helvetica glyph width as a fraction of font size; good enough for centering.
_HELV_AVG = 0.52


def _esc(text: str) -> str:
    """Escape text for a PDF string. Non-Latin-1 characters become '?'."""
    text = str(text).encode("latin-1", "replace").decode("latin-1")
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def text_width(text: str, size: float) -> float:
    return len(str(text)) * size * _HELV_AVG


class PdfPage:
    def __init__(self, width: float = 792, height: float = 612) -> None:
        self.width, self.height = width, height
        self.ops: List[str] = []

    # --- drawing -----------------------------------------------------------
    def _style(self, width: float, gray: float, dash: Optional[Sequence[float]]) -> None:
        self.ops.append(f"{width:.2f} w {gray:.2f} G")
        self.ops.append(f"[{' '.join(f'{d:.1f}' for d in dash)}] 0 d" if dash else "[] 0 d")

    def line(self, x0: float, y0: float, x1: float, y1: float, width: float = 1.0,
             gray: float = 0.0, dash: Optional[Sequence[float]] = None) -> None:
        self._style(width, gray, dash)
        self.ops.append(f"{x0:.2f} {y0:.2f} m {x1:.2f} {y1:.2f} l S")

    def polyline(self, pts: Sequence[Tuple[float, float]], width: float = 1.0, gray: float = 0.0,
                 dash: Optional[Sequence[float]] = None, close: bool = False) -> None:
        if len(pts) < 2:
            return
        self._style(width, gray, dash)
        path = f"{pts[0][0]:.2f} {pts[0][1]:.2f} m " + " ".join(f"{x:.2f} {y:.2f} l" for x, y in pts[1:])
        self.ops.append(path + (" h S" if close else " S"))

    def rect(self, x: float, y: float, w: float, h: float, width: float = 1.0, gray: float = 0.0,
             fill_gray: Optional[float] = None) -> None:
        self._style(width, gray, None)
        if fill_gray is not None:
            self.ops.append(f"{fill_gray:.2f} g {x:.2f} {y:.2f} {w:.2f} {h:.2f} re B 0 g")
        else:
            self.ops.append(f"{x:.2f} {y:.2f} {w:.2f} {h:.2f} re S")

    def text(self, x: float, y: float, text: str, size: float = 10, bold: bool = False,
             align: str = "left", gray: float = 0.0) -> None:
        if align == "center":
            x -= text_width(text, size) / 2
        elif align == "right":
            x -= text_width(text, size)
        font = "F2" if bold else "F1"
        self.ops.append(f"BT {gray:.2f} g /{font} {size:.1f} Tf {x:.2f} {y:.2f} Td ({_esc(text)}) Tj ET 0 g")

    def table(self, x: float, y_top: float, rows: List[Sequence[str]], col_widths: Sequence[float],
              size: float = 9, row_h: float = 15, header: bool = True) -> float:
        """Simple grid table. Returns the y of the bottom edge."""
        y = y_top
        for r, row in enumerate(rows):
            is_header = header and r == 0
            if is_header:
                self.rect(x, y - row_h, sum(col_widths), row_h, width=0.5, fill_gray=0.9)
            cx = x
            for c, cell in enumerate(row):
                self.text(cx + 4, y - row_h + 4.5, str(cell), size=size, bold=is_header)
                cx += col_widths[c]
            self.line(x, y - row_h, x + sum(col_widths), y - row_h, width=0.5, gray=0.6)
            y -= row_h
        self.rect(x, y, sum(col_widths), y_top - y, width=0.6)
        return y

    def content(self) -> bytes:
        return ("\n".join(self.ops) + "\n").encode("latin-1", "replace")


def write_pdf(path: str, pages: List[PdfPage], title: str = "", author: str = "Gusset") -> str:
    """Write the pages to a PDF file (temp file first, then rename)."""
    if not pages:
        raise ValueError("need at least one page")
    objects: List[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    catalog = add(b"")   # filled in below
    pages_id = add(b"")
    font1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    font2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    kids = []
    for page in pages:
        data = page.content()
        stream = add(b"<< /Length %d >>\nstream\n" % len(data) + data + b"endstream")
        kids.append(add((f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {page.width:.0f} {page.height:.0f}] "
                         f"/Resources << /Font << /F1 {font1} 0 R /F2 {font2} 0 R >> >> "
                         f"/Contents {stream} 0 R >>").encode()))
    objects[catalog - 1] = f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode()
    objects[pages_id - 1] = (f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] "
                             f"/Count {len(kids)} >>").encode()
    stamp = datetime.datetime.now().strftime("D:%Y%m%d%H%M%S")
    info = add(f"<< /Title ({_esc(title)}) /Author ({_esc(author)}) /Creator (Gusset) "
               f"/CreationDate ({stamp}) >>".encode("latin-1", "replace"))

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R /Info {info} 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()

    folder = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".pdf", dir=folder)
    with os.fdopen(fd, "wb") as handle:
        handle.write(bytes(out))
    os.replace(tmp, path)
    log.info("Wrote %s (%d page(s))", path, len(pages))
    return path
