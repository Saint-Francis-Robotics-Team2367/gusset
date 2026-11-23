"""
flat_export.py - turns a flat part's outline into SVG or DXF files for the
X-Carve (Easel) and the laser (LightBurn). Plain Python, unit tested.

The Fusion side (lib/fab_geometry.py) reads a planar face and hands us
2D loops in MILLIMETERS, made of these segments:
    ("line",   (x0, y0), (x1, y1))
    ("arc",    (x0, y0), (xm, ym), (x1, y1))     # start, a point in the middle, end
    ("circle", (cx, cy), r)
    ("poly",   [(x, y), ...])                     # anything else (splines...)

Units: SVG files carry real units (width="4.5in" + matching viewBox), which is
what makes Easel and LightBurn import them at the right size. DXF files don't
reliably carry units (LightBurn uses its own Units setting on import), so DXFs
are written in one unit and the unit goes in the file name: "... (in).dxf".

Colors (LightBurn turns each color into a layer; Easel ignores them):
    black  = cut through (outline and holes)
    blue   = pocket (doesn't go all the way through; depth is in the layer name)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from fractions import Fraction
from typing import List, Optional, Sequence, Tuple

log = logging.getLogger("gusset.flat")

Point = Tuple[float, float]
MM_PER_IN = 25.4

CUT_COLOR = "#000000"
POCKET_COLOR = "#0000FF"

KIND_OUTER = "outer"
KIND_HOLE = "hole"
KIND_POCKET = "pocket"


@dataclass
class Loop:
    segs: List[tuple]
    kind: str = KIND_OUTER
    depth_mm: Optional[float] = None     # pockets only


@dataclass
class FlatProfile:
    name: str
    loops: List[Loop] = field(default_factory=list)
    thickness_mm: Optional[float] = None
    warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------
def arc_from_3pts(p0: Point, pm: Point, p1: Point) -> Optional[Tuple[Point, float, float, float, bool]]:
    """
    Circle through three points. Returns (center, radius, start_deg, end_deg, ccw)
    where start/end are the angles of p0/p1 and ccw says which way the arc
    runs from p0 through pm to p1. None if the points are (nearly) in a line.
    """
    (x1, y1), (x2, y2), (x3, y3) = p0, pm, p1
    d = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    if abs(d) < 1e-12:
        return None
    s1, s2, s3 = x1 * x1 + y1 * y1, x2 * x2 + y2 * y2, x3 * x3 + y3 * y3
    cx = (s1 * (y2 - y3) + s2 * (y3 - y1) + s3 * (y1 - y2)) / d
    cy = (s1 * (x3 - x2) + s2 * (x1 - x3) + s3 * (x2 - x1)) / d
    r = math.hypot(x1 - cx, y1 - cy)
    a0 = math.degrees(math.atan2(y1 - cy, x1 - cx)) % 360
    am = math.degrees(math.atan2(y2 - cy, x2 - cx)) % 360
    a1 = math.degrees(math.atan2(y3 - cy, x3 - cx)) % 360
    # The arc is CCW if the middle point is reached going CCW from start before the end.
    ccw = ((am - a0) % 360) < ((a1 - a0) % 360)
    return (cx, cy), r, a0, a1, ccw


def _seg_points(seg: tuple) -> List[Point]:
    kind = seg[0]
    if kind == "line":
        return [seg[1], seg[2]]
    if kind == "arc":
        info = arc_from_3pts(seg[1], seg[2], seg[3])
        if info is None:
            return [seg[1], seg[3]]
        (cx, cy), r, a0, a1, ccw = info
        sweep = ((a1 - a0) % 360) if ccw else -((a0 - a1) % 360)
        steps = max(4, int(abs(sweep) / 10))
        return [(cx + r * math.cos(math.radians(a0 + sweep * i / steps)),
                 cy + r * math.sin(math.radians(a0 + sweep * i / steps))) for i in range(steps + 1)]
    if kind == "circle":
        (cx, cy), r = seg[1], seg[2]
        return [(cx + r * math.cos(t), cy + r * math.sin(t)) for t in (0, math.pi / 2, math.pi, 1.5 * math.pi)]
    if kind == "poly":
        return list(seg[1])
    raise ValueError(f"unknown segment type {kind!r}")


def _arc_extremes(seg: tuple) -> Tuple[List[float], List[float]]:
    """Exact x/y extremes of an arc: its two ends plus any of the 0/90/180/270
    degree points the arc passes through (sampling would miss the true edge)."""
    info = arc_from_3pts(seg[1], seg[2], seg[3])
    pts = [seg[1], seg[3]]
    if info is not None:
        (cx, cy), r, a0, a1, ccw = info
        start, sweep = (a0, (a1 - a0) % 360) if ccw else (a1, (a0 - a1) % 360)
        for axis in (0, 90, 180, 270):
            if (axis - start) % 360 <= sweep + 1e-9:
                pts.append((cx + r * math.cos(math.radians(axis)), cy + r * math.sin(math.radians(axis))))
    return [p[0] for p in pts], [p[1] for p in pts]


def _ends(seg: tuple) -> Tuple[Point, Point]:
    kind = seg[0]
    if kind == "line":
        return seg[1], seg[2]
    if kind == "arc":
        return seg[1], seg[3]
    if kind == "poly":
        return seg[1][0], seg[1][-1]
    raise ValueError("circles have no ends")


def _reverse(seg: tuple) -> tuple:
    kind = seg[0]
    if kind == "line":
        return ("line", seg[2], seg[1])
    if kind == "arc":
        return ("arc", seg[3], seg[2], seg[1])
    return ("poly", list(reversed(seg[1])))


def _close(a: Point, b: Point, tol: float) -> bool:
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def chain(segs: List[tuple], tol: float = 0.01) -> List[List[tuple]]:
    """
    Fusion hands us a loop's edges in no particular order or direction. CAM
    programs (Easel especially) want ONE closed shape per loop, so put the edges
    end-to-start. Returns a list of chains (normally one per loop); circles are
    their own chain. tol is in mm.
    """
    chains: List[List[tuple]] = []
    rest = []
    for seg in segs:
        if seg[0] == "circle":
            chains.append([seg])
        elif seg[0] == "poly" and len(seg[1]) < 2:
            continue
        else:
            rest.append(seg)
    while rest:
        current = [rest.pop(0)]
        grew = True
        while rest and grew:
            grew = False
            tail = _ends(current[-1])[1]
            head = _ends(current[0])[0]
            for i, seg in enumerate(rest):
                a, b = _ends(seg)
                if _close(a, tail, tol):
                    current.append(rest.pop(i))
                elif _close(b, tail, tol):
                    current.append(_reverse(rest.pop(i)))
                elif _close(b, head, tol):
                    current.insert(0, rest.pop(i))
                elif _close(a, head, tol):
                    current.insert(0, _reverse(rest.pop(i)))
                else:
                    continue
                grew = True
                break
        chains.append(current)
    return chains


def is_closed(chain_segs: List[tuple], tol: float = 0.01) -> bool:
    if len(chain_segs) == 1 and chain_segs[0][0] == "circle":
        return True
    return _close(_ends(chain_segs[0])[0], _ends(chain_segs[-1])[1], tol)


def bounds(profile: FlatProfile) -> Tuple[float, float, float, float]:
    xs, ys = [], []
    for loop in profile.loops:
        for seg in loop.segs:
            if seg[0] == "arc":
                xs_a, ys_a = _arc_extremes(seg)
                xs += xs_a
                ys += ys_a
                continue
            if seg[0] == "circle":
                (cx, cy), r = seg[1], seg[2]
                xs += [cx - r, cx + r]
                ys += [cy - r, cy + r]
            else:
                for x, y in _seg_points(seg):
                    xs.append(x)
                    ys.append(y)
    if not xs:
        return 0.0, 0.0, 0.0, 0.0
    return min(xs), min(ys), max(xs), max(ys)


def _shift(seg: tuple, dx: float, dy: float) -> tuple:
    move = lambda p: (p[0] + dx, p[1] + dy)  # noqa: E731
    kind = seg[0]
    if kind == "line":
        return ("line", move(seg[1]), move(seg[2]))
    if kind == "arc":
        return ("arc", move(seg[1]), move(seg[2]), move(seg[3]))
    if kind == "circle":
        return ("circle", move(seg[1]), seg[2])
    return ("poly", [move(p) for p in seg[1]])


def normalized(profile: FlatProfile, margin_mm: float = 0.0) -> FlatProfile:
    """Move the part so its lower-left corner sits at (margin, margin)."""
    x0, y0, _x1, _y1 = bounds(profile)
    dx, dy = margin_mm - x0, margin_mm - y0
    return FlatProfile(
        name=profile.name, thickness_mm=profile.thickness_mm, warnings=list(profile.warnings),
        loops=[Loop([_shift(s, dx, dy) for s in loop.segs], loop.kind, loop.depth_mm) for loop in profile.loops],
    )


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------
def thickness_label(thickness_mm: Optional[float], units: str = "in") -> str:
    """6.35 -> '1/4 in'; 3.0 -> '0.118 in' (no clean fraction); units='mm' -> '6.35 mm'."""
    if thickness_mm is None or thickness_mm <= 0:
        return "unknown thickness"
    if units == "mm":
        return f"{thickness_mm:.2f}".rstrip("0").rstrip(".") + " mm"
    inches = thickness_mm / MM_PER_IN
    frac = Fraction(inches).limit_denominator(64)
    if abs(float(frac) - inches) < 0.002 and frac.denominator in (1, 2, 4, 8, 16, 32, 64):
        whole, rem = divmod(frac.numerator, frac.denominator)
        if rem == 0:
            return f"{whole} in"
        text = f"{rem}/{frac.denominator}"
        return f"{whole}-{text} in" if whole else f"{text} in"
    return f"{inches:.3f} in"


def depth_label(depth_mm: float, units: str = "in") -> str:
    return f"{depth_mm:.2f}mm" if units == "mm" else f"{depth_mm / MM_PER_IN:.3f}in"


# ---------------------------------------------------------------------------
# SVG
# ---------------------------------------------------------------------------
def _fmt(v: float) -> str:
    text = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def to_svg(profile: FlatProfile, units: str = "in", margin_mm: float = 0.0) -> str:
    """
    SVG with real-world units. The viewBox uses the same unit as width/height,
    so 1 user unit = 1 inch (or mm). SVG's y axis points DOWN, so y is flipped.
    """
    scale = 1 / MM_PER_IN if units == "in" else 1.0
    prof = normalized(profile, margin_mm)
    _x0, _y0, x1, y1 = bounds(prof)
    width, height = (x1 + margin_mm) * scale, (y1 + margin_mm) * scale
    flip = lambda p: (p[0] * scale, height - p[1] * scale)  # noqa: E731

    groups = {KIND_OUTER: [], KIND_HOLE: [], KIND_POCKET: []}
    for loop in prof.loops:
        for segs in chain(loop.segs):
            if segs[0][0] == "circle":
                (cx, cy), r = flip(segs[0][1]), segs[0][2] * scale
                groups.setdefault(loop.kind, []).append(f'<circle cx="{_fmt(cx)}" cy="{_fmt(cy)}" r="{_fmt(r)}"/>')
                continue
            start = flip(_ends(segs[0])[0])
            parts: List[str] = [f"M{_fmt(start[0])},{_fmt(start[1])}"]
            for seg in segs:
                kind = seg[0]
                if kind == "line":
                    b = flip(seg[2])
                    parts.append(f"L{_fmt(b[0])},{_fmt(b[1])}")
                elif kind == "arc":
                    info = arc_from_3pts(seg[1], seg[2], seg[3])
                    b = flip(seg[3])
                    if info is None:
                        parts.append(f"L{_fmt(b[0])},{_fmt(b[1])}")
                        continue
                    (_c, r, a0, a1, ccw) = info
                    sweep_deg = ((a1 - a0) % 360) if ccw else ((a0 - a1) % 360)
                    large = 1 if sweep_deg > 180 else 0
                    # y is flipped, so math-CCW becomes SVG clockwise (sweep-flag 0).
                    sweep_flag = 0 if ccw else 1
                    rs = _fmt(r * scale)
                    parts.append(f"A{rs},{rs} 0 {large} {sweep_flag} {_fmt(b[0])},{_fmt(b[1])}")
                else:
                    parts.append(" ".join(f"L{_fmt(x)},{_fmt(y)}" for x, y in (flip(p) for p in seg[1][1:])))
            if is_closed(segs):
                parts.append("Z")
            else:
                prof.warnings.append("an outline isn't closed - check it in Easel/LightBurn")
            groups.setdefault(loop.kind, []).append(f'<path d="{" ".join(parts)}"/>')

    u = "in" if units == "in" else "mm"
    out = [
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
        f"<!-- {profile.name} | made by Gusset | units: {u}"
        + (f" | stock {thickness_label(profile.thickness_mm, units)}" if profile.thickness_mm else "") + " -->",
        f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="{_fmt(width)}{u}" height="{_fmt(height)}{u}" '
        f'viewBox="0 0 {_fmt(width)} {_fmt(height)}">',
        f'<g id="cut" fill="none" stroke="{CUT_COLOR}" stroke-width="{_fmt(0.01 if u == "in" else 0.25)}">',
        *groups[KIND_OUTER], *groups[KIND_HOLE], "</g>",
    ]
    if groups[KIND_POCKET]:
        out += [f'<g id="pockets" fill="none" stroke="{POCKET_COLOR}" stroke-width="{_fmt(0.01 if u == "in" else 0.25)}">',
                *groups[KIND_POCKET], "</g>"]
    out.append("</svg>")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# DXF (R12 / AC1009: the version every CAM and laser program reads)
# ---------------------------------------------------------------------------
def _dxf_layer(loop: Loop, units: str) -> str:
    if loop.kind == KIND_POCKET and loop.depth_mm:
        return f"POCKET_{depth_label(loop.depth_mm, units)}".replace(".", "_")
    return "CUT"


def to_dxf(profile: FlatProfile, units: str = "in", margin_mm: float = 0.0) -> str:
    scale = 1 / MM_PER_IN if units == "in" else 1.0
    prof = normalized(profile, margin_mm)
    lines: List[str] = []

    def add(*pairs: object) -> None:
        for p in pairs:
            lines.append(str(p))

    # Header: $INSUNITS isn't part of R12, but many readers honor it, so include it.
    add(0, "SECTION", 2, "HEADER",
        9, "$ACADVER", 1, "AC1009",
        9, "$INSUNITS", 70, 1 if units == "in" else 4,
        9, "$MEASUREMENT", 70, 0 if units == "in" else 1,
        0, "ENDSEC")
    layers = sorted({_dxf_layer(loop, units) for loop in prof.loops} | {"CUT"})
    add(0, "SECTION", 2, "TABLES", 0, "TABLE", 2, "LAYER", 70, len(layers))
    for layer in layers:
        color = 5 if layer.startswith("POCKET") else 7   # 5 = blue, 7 = black/white
        add(0, "LAYER", 2, layer, 70, 0, 62, color, 6, "CONTINUOUS")
    add(0, "ENDTAB", 0, "ENDSEC")

    add(0, "SECTION", 2, "ENTITIES")
    for loop in prof.loops:
        layer = _dxf_layer(loop, units)
        for segs in chain(loop.segs):
            if segs[0][0] == "circle":
                (cx, cy), r = segs[0][1], segs[0][2]
                add(0, "CIRCLE", 8, layer, 10, _fmt(cx * scale), 20, _fmt(cy * scale), 30, 0, 40, _fmt(r * scale))
                continue
            # One POLYLINE per shape: each vertex carries a "bulge" (tan of a quarter of
            # the arc's sweep; + for counter-clockwise) for the arc that starts there.
            vertices: List[Tuple[float, float, float]] = []
            for seg in segs:
                kind = seg[0]
                if kind == "arc":
                    info = arc_from_3pts(seg[1], seg[2], seg[3])
                    bulge = 0.0
                    if info is not None:
                        (_c, _r, a0, a1, ccw) = info
                        sweep = ((a1 - a0) % 360) if ccw else -((a0 - a1) % 360)
                        bulge = math.tan(math.radians(sweep) / 4)
                    vertices.append((seg[1][0], seg[1][1], bulge))
                elif kind == "line":
                    vertices.append((seg[1][0], seg[1][1], 0.0))
                else:
                    vertices += [(x, y, 0.0) for x, y in seg[1][:-1]]
            closed = is_closed(segs)
            if not closed:
                end = _ends(segs[-1])[1]
                vertices.append((end[0], end[1], 0.0))
            add(0, "POLYLINE", 8, layer, 66, 1, 10, 0, 20, 0, 30, 0, 70, 1 if closed else 0)
            for x, y, bulge in vertices:
                add(0, "VERTEX", 8, layer, 10, _fmt(x * scale), 20, _fmt(y * scale), 30, 0)
                if abs(bulge) > 1e-12:
                    add(42, f"{bulge:.8f}")
            add(0, "SEQEND", 8, layer)
    add(0, "ENDSEC", 0, "EOF")
    return "\n".join(lines) + "\n"


def write_profile(path: str, profile: FlatProfile, fmt: str, units: str = "in") -> str:
    """Write SVG or DXF. Returns the path."""
    text = to_svg(profile, units) if fmt.lower() == "svg" else to_dxf(profile, units)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    x0, y0, x1, y1 = bounds(profile)
    log.info("Wrote %s (%.1f x %.1f mm, %d loops)", path, x1 - x0, y1 - y0, len(profile.loops))
    return path
