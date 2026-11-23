"""
lathe_sheet.py - builds a one-page "lathe sheet" PDF for a turned part
(spacers, standoffs, shafts). Plain Python, unit tested.

Fusion's API can't reliably create a drawing from scratch, so Gusset makes its
own sheet from the part's geometry. The Fusion side (lib/fab_geometry.py)
measures the part along its turning axis and hands us:
    outer cylinders  -> outside diameters (OD steps)
    inner cylinders  -> bores
    flat faces parallel to the axis -> hex stock (across-flats size)
All lengths in MILLIMETERS, measured along the axis.

The sheet shows: stock to cut (round or hex, with a little extra length),
overall length, a side view with diameters, and tables of steps and bores.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .flat_export import MM_PER_IN, thickness_label
from .pdf_writer import PdfPage, text_width, write_pdf

log = logging.getLogger("gusset.lathe")

TOL_MM = 0.05                       # features closer than this are "the same"
STOCK_STEP_IN = 0.125               # round stock comes in 1/8" steps
STOCK_LENGTH_EXTRA_IN = 0.25        # extra length for facing + parting off


@dataclass
class RawCylinder:
    radius_mm: float
    z0: float
    z1: float
    outer: bool                     # True = outside surface, False = bore


@dataclass
class RawFlat:
    distance_mm: float              # distance from the axis to a flat face (hex: half the across-flats)
    z0: float
    z1: float


@dataclass
class Step:
    diameter_mm: float
    z0: float
    z1: float
    kind: str = "round"             # "round" | "hex"

    @property
    def length(self) -> float:
        return self.z1 - self.z0


@dataclass
class LatheProfile:
    name: str
    part_number: str = ""
    description: str = ""
    material: str = ""
    qty: int = 1
    length_mm: float = 0.0
    steps: List[Step] = field(default_factory=list)       # outside, left to right
    bores: List[Step] = field(default_factory=list)
    stock: str = ""
    stock_length_mm: float = 0.0
    warnings: List[str] = field(default_factory=list)


def _merge(spans: List[Step]) -> List[Step]:
    """Join touching/overlapping spans that have the same diameter."""
    out: List[Step] = []
    for s in sorted(spans, key=lambda s: (round(s.diameter_mm, 2), s.z0)):
        last = out[-1] if out else None
        if last and abs(last.diameter_mm - s.diameter_mm) < TOL_MM and last.kind == s.kind and s.z0 <= last.z1 + TOL_MM:
            last.z1 = max(last.z1, s.z1)
        else:
            out.append(Step(s.diameter_mm, s.z0, s.z1, s.kind))
    return sorted(out, key=lambda s: (s.z0, -s.diameter_mm))


def _in(mm: float) -> float:
    return mm / MM_PER_IN


def fmt_len(mm: float, units: str = "in") -> str:
    return f"{mm:.2f} mm" if units == "mm" else f'{_in(mm):.3f}"'


def round_stock_for(od_mm: float) -> float:
    """
    Stock to buy. If the finished diameter already IS a standard 1/16" size
    (a 1/2" standoff), use that stock as-is. Otherwise the smallest 1/8"
    size that leaves at least 0.02" to clean up.
    """
    inches = _in(od_mm)
    sixteenths = round(inches * 16)
    if sixteenths and abs(inches - sixteenths / 16) <= 0.003:
        return sixteenths / 16 * MM_PER_IN
    need = inches + 0.02
    steps = int(need / STOCK_STEP_IN + 0.999999)
    return steps * STOCK_STEP_IN * MM_PER_IN


def analyze(name: str, length_mm: float, cylinders: List[RawCylinder], flats: List[RawFlat],
            part_number: str = "", description: str = "", material: str = "", qty: int = 1) -> LatheProfile:
    """Turn raw measurements into steps, bores and a stock callout."""
    prof = LatheProfile(name=name, part_number=part_number, description=description,
                        material=material, qty=qty, length_mm=length_mm)
    if length_mm <= 0:
        prof.warnings.append("couldn't measure the part's length")

    outer = [Step(2 * c.radius_mm, max(0.0, c.z0), min(length_mm, c.z1)) for c in cylinders if c.outer]
    inner = [Step(2 * c.radius_mm, max(0.0, c.z0), min(length_mm, c.z1)) for c in cylinders if not c.outer]

    hex_af = None
    if len(flats) >= 6:
        distances = sorted(f.distance_mm for f in flats)
        mid = distances[len(distances) // 2]
        same = [f for f in flats if abs(f.distance_mm - mid) < TOL_MM * 4]
        if len(same) >= 6:
            hex_af = 2 * mid
            z0, z1 = min(f.z0 for f in same), max(f.z1 for f in same)
            outer.append(Step(hex_af, z0, z1, "hex"))
    elif flats:
        prof.warnings.append(f"{len(flats)} flat face(s) along the part (keyway or D-flat?) - mill or file after turning")

    prof.steps = _merge(outer)
    prof.bores = _merge(inner)

    if hex_af:
        prof.stock = f"{_hex_label(hex_af)} hex"
    elif prof.steps:
        biggest = max(s.diameter_mm for s in prof.steps)
        prof.stock = f"{_hex_label(round_stock_for(biggest))} round"
    else:
        prof.stock = "unknown"
        prof.warnings.append("no turned outside diameter found - is this really a lathe part?")
    prof.stock_length_mm = length_mm + STOCK_LENGTH_EXTRA_IN * MM_PER_IN
    log.info("Lathe %s: L=%.2fmm, %d steps, %d bores, stock %s", name, length_mm, len(prof.steps), len(prof.bores), prof.stock)
    return prof


def _hex_label(size_mm: float) -> str:
    """6.35 -> 1/4"   12.7 -> 1/2"   9.0 -> 0.354\""""
    label = thickness_label(size_mm)          # "1/2 in", "1-1/4 in" or "0.354 in"
    return label.replace(" in", '"')


def _bore_where(b: Step, length_mm: float) -> str:
    at_left, at_right = b.z0 <= TOL_MM * 2, b.z1 >= length_mm - TOL_MM * 2
    if at_left and at_right:
        return "through"
    if at_left:
        return "from left end"
    if at_right:
        return "from right end"
    return f"starts {fmt_len(b.z0)} from left"


# ---------------------------------------------------------------------------
# Features: what a machinist needs to read off the sheet
# ---------------------------------------------------------------------------
GROOVE_MAX_WIDTH_MM = 0.25 * MM_PER_IN    # narrower than this and smaller than both neighbors = groove


@dataclass
class Feature:
    number: int
    kind: str                # "round" | "hex" | "groove"
    step: Step

    @property
    def label(self) -> str:
        return {"hex": "Hex (across flats)", "groove": "Groove", "round": "Round"}[self.kind]


def features(prof: LatheProfile) -> List[Feature]:
    """Outside steps, left to right, with grooves picked out."""
    out: List[Feature] = []
    steps = prof.steps
    for i, s in enumerate(steps):
        kind = s.kind
        if kind == "round" and s.length <= GROOVE_MAX_WIDTH_MM:
            left = steps[i - 1].diameter_mm if i > 0 else None
            right = steps[i + 1].diameter_mm if i + 1 < len(steps) else None
            neighbors = [d for d in (left, right) if d is not None]
            if len(neighbors) == 2 and all(s.diameter_mm < d - TOL_MM for d in neighbors):
                kind = "groove"
        out.append(Feature(i + 1, kind, s))
    return out


def nearest_end(z0: float, z1: float, length: float, units: str = "in") -> str:
    """'0.062" from left end' - whichever end is closer to the feature."""
    from_left, from_right = z0, length - z1
    if from_left <= from_right:
        return f"{fmt_len(from_left, units)} from left end"
    return f"{fmt_len(from_right, units)} from right end"


def turned_sections(prof: LatheProfile, units: str = "in") -> List[str]:
    """
    When the part is made from hex (or bigger round) stock, the ends usually get
    turned down. Describe each turned end as one instruction, e.g.
    'Left end: turn to Ø0.500 for 0.414" (includes 1 groove)'.
    """
    feats = features(prof)
    if not feats:
        return []
    # The "body" is the hex if there is one (round ends on hex stock are turned even
    # when they match the across-flats size), otherwise the biggest diameter.
    hexes = [f for f in feats if f.kind == "hex"]
    if hexes:
        main = hexes
    else:
        biggest = max(f.step.diameter_mm for f in feats)
        main = [f for f in feats if abs(f.step.diameter_mm - biggest) < TOL_MM]
    if not main:
        return []
    first_main, last_main = main[0].number, main[-1].number
    lines = []
    for side, group in (("Left end", [f for f in feats if f.number < first_main]),
                        ("Right end", [f for f in feats if f.number > last_main])):
        if not group:
            continue
        start, end = min(f.step.z0 for f in group), max(f.step.z1 for f in group)
        diameters = sorted({round(f.step.diameter_mm, 3) for f in group if f.kind != "groove"}, reverse=True)
        grooves = sum(1 for f in group if f.kind == "groove")
        dia_text = " / ".join(f"Ø{fmt_len(d, units)}" for d in diameters) or "-"
        extra = f" (includes {grooves} groove{'s' if grooves != 1 else ''})" if grooves else ""
        lines.append(f"{side}: turn to {dia_text} for {fmt_len(end - start, units)}{extra}")
    return lines


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
def render(prof: LatheProfile, path: str, units: str = "in") -> str:
    page = PdfPage(792, 612)     # US Letter, landscape
    m = 36
    W = 792 - 2 * m
    feats = features(prof)

    # --- Title block
    page.text(m, 578, "LATHE SHEET", size=10, bold=True, gray=0.4)
    page.text(m, 556, f"{prof.part_number or '(no part number)'}  {prof.description or prof.name}", size=18, bold=True)
    info = [
        ("Stock", f"{prof.stock}, cut to {fmt_len(prof.stock_length_mm, units)}"),
        ("Finished length", fmt_len(prof.length_mm, units)),
        ("Material", prof.material or "not set in Fusion"),
        ("Quantity", str(prof.qty)),
    ]
    x = m
    for label, value in info:
        page.text(x, 536, label.upper(), size=7, bold=True, gray=0.45)
        page.text(x, 524, value, size=10)
        x += max(140, text_width(value, 10) + 28)
    turned = turned_sections(prof, units)
    y_t = 508
    for line in turned:
        page.text(m, y_t, line, size=10, bold=True)
        y_t -= 13
    page.line(m, y_t + 5, 792 - m, y_t + 5, width=0.8)

    # --- Side view, scaled to fit
    view_top = y_t - 18
    max_d = max([s.diameter_mm for s in prof.steps] + [b.diameter_mm for b in prof.bores] + [1.0])
    length = max(prof.length_mm, 1.0)
    box_h = 120
    scale = min((W - 80) / length, box_h / max_d)
    ox = m + (W - length * scale) / 2
    cy = view_top - box_h / 2 - 10
    X = lambda z: ox + z * scale  # noqa: E731

    page.line(ox - 18, cy, ox + length * scale + 18, cy, width=0.4, gray=0.5, dash=[12, 3, 2, 3])   # centerline
    for f in feats:
        s = f.step
        h = s.diameter_mm * scale / 2
        page.rect(X(s.z0), cy - h, s.length * scale, 2 * h, width=1.4 if f.kind != "hex" else 1.8)
        if f.kind == "hex":
            page.line(X(s.z0), cy + h * 0.5, X(s.z1), cy + h * 0.5, width=0.6)
            page.line(X(s.z0), cy - h * 0.5, X(s.z1), cy - h * 0.5, width=0.6)
    for b in prof.bores:
        h = b.diameter_mm * scale / 2
        page.polyline([(X(b.z0), cy - h), (X(b.z1), cy - h), (X(b.z1), cy + h), (X(b.z0), cy + h)],
                      width=0.8, gray=0.3, dash=[4, 2], close=True)

    # Labels above: feature number on every step; grooves get a full callout.
    top = cy + max_d * scale / 2
    callout_y = top + 10
    for f in feats:
        s = f.step
        mid = (X(s.z0) + X(s.z1)) / 2
        h = s.diameter_mm * scale / 2
        page.text(mid, cy + h + 4, str(f.number), size=7.5, bold=True, align="center", gray=0.35)
        if f.kind == "groove":
            text = (f"GROOVE Ø{fmt_len(s.diameter_mm, units)} x {fmt_len(s.length, units)} wide, "
                    f"{nearest_end(s.z0, s.z1, prof.length_mm, units)}")
            page.line(mid, cy + h + 12, mid, callout_y + 2, width=0.5, gray=0.3)
            # Keep the callout on the page: slide it right/left near the ends.
            half = text_width(text, 8) / 2
            tx = min(max(mid, m + half), 792 - m - half)
            page.text(tx, callout_y + 5, text, size=8, bold=True, align="center")
            callout_y += 12

    # Baseline dimensions below: left end to every shoulder / groove edge.
    boundaries = sorted({round(z, 4) for f in feats for z in (f.step.z0, f.step.z1)} - {0.0})
    bottom = cy - max_d * scale / 2
    dim_y = bottom - 14
    page.line(X(0), bottom - 4, X(0), dim_y - 12 * len(boundaries) - 2, width=0.5, gray=0.3)
    for z in boundaries:
        page.line(X(z), bottom - 4, X(z), dim_y - 2, width=0.4, gray=0.55)
        page.line(X(0), dim_y, X(z), dim_y, width=0.6)
        page.polyline([(X(z) - 4, dim_y + 2), (X(z), dim_y), (X(z) - 4, dim_y - 2)], width=0.6)
        page.text(X(z) + 3, dim_y - 3, fmt_len(z, units), size=7.5)
        dim_y -= 12
    page.text(X(0) - 4, bottom - 14, "0", size=7.5, align="right")

    # --- Feature table (every step: where it starts and ends, from BOTH ends)
    y = dim_y - 14
    rows = [["#", "Feature", "Diameter", "Starts (from left)", "Ends (from left)", "Length", "Nearest end"]]
    for f in feats:
        s = f.step
        rows.append([str(f.number), f.label, fmt_len(s.diameter_mm, units), fmt_len(s.z0, units),
                     fmt_len(s.z1, units), fmt_len(s.length, units), nearest_end(s.z0, s.z1, prof.length_mm, units)])
    if len(rows) == 1:
        rows.append(["-", "no outside diameter found", "", "", "", "", ""])
    page.text(m, y + 5, "OUTSIDE, LEFT TO RIGHT", size=7.5, bold=True, gray=0.45)
    y_end = page.table(m, y, rows, [18, 92, 58, 82, 76, 52, 120], size=8, row_h=13)

    rows = [["#", "Bore", "Depth", "Where"]]
    for i, b in enumerate(prof.bores, start=1):
        rows.append([str(i), "Ø" + fmt_len(b.diameter_mm, units), fmt_len(b.length, units),
                     _bore_where(b, prof.length_mm)])
    if len(rows) == 1:
        rows.append(["-", "no bores", "", ""])
    bx = m + 518
    page.text(bx, y + 5, "BORES", size=7.5, bold=True, gray=0.45)
    page.table(bx, y, rows, [16, 50, 46, 108], size=8, row_h=13)

    note_y = min(y_end - 16, 62)
    for w in prof.warnings[:3]:
        page.text(m, note_y, "! " + w, size=8.5, bold=True)
        note_y -= 11
    page.text(m, 30, f"Made by Gusset from the Fusion model on {datetime.date.today().isoformat()}. "
                     "All lengths from the LEFT end unless noted. Chamfers, threads and small fillets aren't shown.",
              size=7, gray=0.45)
    return write_pdf(path, [page], title=f"{prof.part_number} {prof.description} lathe sheet")
