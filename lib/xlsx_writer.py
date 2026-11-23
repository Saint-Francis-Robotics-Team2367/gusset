"""
xlsx_writer.py - writes a simple .xlsx file using ONLY the Python standard library.

Why: Fusion's built-in Python has no openpyxl/pandas, and asking every FRC team
to install packages into Fusion is a support nightmare. An .xlsx file is just a
zip of a few XML files, so we write those directly.

Supports what the BOM needs: several sheets, a bold frozen header row, column
widths, an autofilter, numbers stored as numbers, text, and blank cells.

    write_xlsx("bom.xlsx", [
        Sheet("BOM", rows=[["Name", "Qty"], ["Plate", 2]], widths=[30, 6]),
    ])
"""

from __future__ import annotations

import datetime
import logging
import math
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from typing import List, Optional, Sequence
from xml.sax.saxutils import escape

log = logging.getLogger("gusset.xlsx")

_ILLEGAL_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_BAD_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")
MAX_CELL_TEXT = 32767   # Excel's limit per cell


@dataclass
class Sheet:
    name: str
    rows: List[Sequence[object]] = field(default_factory=list)
    widths: Optional[List[float]] = None
    freeze_header: bool = True
    autofilter: bool = True


@dataclass
class Link:
    """A clickable cell: Excel's HYPERLINK formula, with the text cached so it shows before recalculating."""
    url: str
    text: str = ""


@dataclass
class Bold:
    """A bold cell (subtotal rows) - no fill, unlike the header row."""
    value: object


def _formula_text(text: str) -> str:
    return _ILLEGAL_XML.sub("", str(text)).replace('"', '""')


def _col_letter(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA"""
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _clean_sheet_name(name: str, used: set) -> str:
    base = _BAD_SHEET_CHARS.sub("-", name or "Sheet").strip("'")[:31] or "Sheet"
    candidate, n = base, 2
    while candidate.lower() in used:
        suffix = f" ({n})"
        candidate = base[: 31 - len(suffix)] + suffix
        n += 1
    used.add(candidate.lower())
    return candidate


def _cell_xml(ref: str, value: object, header: bool) -> str:
    style = ' s="1"' if header else ""
    if isinstance(value, Bold):
        value, style = value.value, ' s="2"'
    if isinstance(value, Link):
        if not value.url.startswith(("http://", "https://")):
            value = value.text or value.url                   # not a web link - plain text
        else:
            text = (value.text or value.url)[:250]
            formula = f'HYPERLINK("{_formula_text(value.url)[:250]}","{_formula_text(text)}")'
            return f'<c r="{ref}" t="str"{style}><f>{escape(formula)}</f><v>{escape(_ILLEGAL_XML.sub("", text))}</v></c>'
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return f'<c r="{ref}" t="b"{style}><v>{int(value)}</v></c>'
    if isinstance(value, (int, float)) and not (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
        return f'<c r="{ref}"{style}><v>{value}</v></c>'
    text = _ILLEGAL_XML.sub("", str(value))[:MAX_CELL_TEXT]
    space = ' xml:space="preserve"' if text != text.strip() else ""
    return f'<c r="{ref}" t="inlineStr"{style}><is><t{space}>{escape(text)}</t></is></c>'


def _sheet_xml(sheet: Sheet) -> str:
    rows = sheet.rows or [[]]
    ncols = max((len(r) for r in rows), default=1) or 1
    parts = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">']
    if sheet.freeze_header and len(rows) > 1:
        parts.append('<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
                     'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>')
    if sheet.widths:
        parts.append("<cols>")
        for i, width in enumerate(sheet.widths, start=1):
            parts.append(f'<col min="{i}" max="{i}" width="{float(width):.1f}" customWidth="1"/>')
        parts.append("</cols>")
    parts.append("<sheetData>")
    for r_index, row in enumerate(rows, start=1):
        cells = "".join(_cell_xml(f"{_col_letter(c)}{r_index}", v, r_index == 1) for c, v in enumerate(row))
        parts.append(f'<row r="{r_index}">{cells}</row>')
    parts.append("</sheetData>")
    if sheet.autofilter and len(rows) > 1:
        parts.append(f'<autoFilter ref="A1:{_col_letter(ncols - 1)}{len(rows)}"/>')
    parts.append("</worksheet>")
    return "".join(parts)


_STYLES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
           '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
           '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
           '<fills count="3"><fill><patternFill patternType="none"/></fill>'
           '<fill><patternFill patternType="gray125"/></fill>'
           '<fill><patternFill patternType="solid"><fgColor rgb="FFE7E6E6"/><bgColor indexed="64"/></patternFill></fill></fills>'
           '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
           '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
           '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
           '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
           '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
           '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
           '</styleSheet>')


def write_xlsx(path: str, sheets: List[Sheet], creator: str = "Gusset") -> str:
    """Write the workbook. Writes to a temp file first, so a crash never leaves half a file."""
    if not sheets:
        raise ValueError("need at least one sheet")
    used: set = set()
    names = [_clean_sheet_name(s.name, used) for s in sheets]
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
                      'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                      for i in range(1, len(sheets) + 1))
            + "</Types>"),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            "</Relationships>"),
        "docProps/core.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f"<dc:creator>{escape(creator)}</dc:creator>"
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
            "</cp:coreProperties>"),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
            + "".join(f'<sheet name="{escape(n, {chr(34): "&quot;"})}" sheetId="{i}" r:id="rId{i}"/>'
                      for i, n in enumerate(names, start=1))
            + "</sheets></workbook>"),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                      f'Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1))
            + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            "</Relationships>"),
        "xl/styles.xml": _STYLES,
    }
    for i, sheet in enumerate(sheets, start=1):
        files[f"xl/worksheets/sheet{i}.xml"] = _sheet_xml(sheet)

    folder = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".xlsx", dir=folder)
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, content in files.items():
                zf.writestr(name, content.encode("utf-8"))
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    log.info("Wrote %s (%s)", path, ", ".join(f"{n}: {len(s.rows) - 1} rows" for n, s in zip(names, sheets)))
    return path
