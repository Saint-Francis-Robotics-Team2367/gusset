"""
lighten_core.py - the geometry behind Quick Rib and Lighten (no Fusion imports,
so it's unit-tested in tests/test_lighten_core.py).

How lightening works in Gusset (same idea as FRC's Onshape "Lighten" scripts):

    plate outline ──offset in by WALL──┐
    every hole    ──ring of BOSS───────┤  -> what's left between them are POCKETS
    every rib     ──strip RIB wide─────┘     (corners rounded to the cutter radius)

Quick Rib decides WHERE the ribs go: it connects the holes to each other and to
the plate's edge in triangles (a truss), because triangles carry load well and
each hole keeps material running to its neighbours.

Everything here is in INCHES. Points are (x, y) tuples.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

Pt = Tuple[float, float]
Poly = List[Pt]

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
# Cutters: the corner radius is what the tool can actually cut (radius + a hair),
# and the laser still gets rounded corners because sharp inside corners crack.
DEFAULT_CUTTERS: List[Dict[str, object]] = [
    {"name": '1/8" end mill (X-Carve)', "diameter_in": 0.125},
    {"name": '1/4" end mill', "diameter_in": 0.25},
    {"name": '3/16" end mill', "diameter_in": 0.1875},
    {"name": "Laser", "diameter_in": 0.0, "corner_radius_in": 0.0625},
]
CORNER_CLEARANCE_IN = 0.005     # corner radius = tool radius + this, so the tool never has to stop dead
MIN_CORNER_IN = 0.03

DEFAULTS = {
    "wall_in": 0.25,          # material left around the outside of the plate
    "rib_in": 0.1875,         # width of each rib
    "boss_in": 0.15,          # ring of material left around every hole
    "min_pocket_in": 0.5,     # pockets narrower than this are left solid
    "max_span_in": 4.0,       # Quick Rib: a rib reaches the edge at least this often
    "depth_in": 0.0,          # 0 = through; otherwise pocket depth
}
MIN_FLOOR_IN = 0.03           # a blind pocket must leave at least this much floor


@dataclass
class Cutter:
    name: str
    diameter_in: float
    corner_radius_in: Optional[float] = None

    @property
    def corner_in(self) -> float:
        if self.corner_radius_in:
            return max(float(self.corner_radius_in), MIN_CORNER_IN)
        return max(self.diameter_in / 2 + CORNER_CLEARANCE_IN, MIN_CORNER_IN)


def cutter_from_dict(d: Dict[str, object]) -> Optional[Cutter]:
    try:
        name = str(d.get("name", "")).strip()
        dia = float(d.get("diameter_in", 0.0))  # type: ignore[arg-type]
        corner = d.get("corner_radius_in")
        corner_f = float(corner) if corner not in (None, "") else None  # type: ignore[arg-type]
    except (TypeError, ValueError, AttributeError):
        return None
    if not name or dia < 0 or dia > 2 or (corner_f is not None and corner_f < 0):
        return None
    return Cutter(name, dia, corner_f)


@dataclass
class LightenParams:
    wall_in: float = DEFAULTS["wall_in"]
    rib_in: float = DEFAULTS["rib_in"]
    boss_in: float = DEFAULTS["boss_in"]
    corner_in: float = 0.0675
    min_pocket_in: float = DEFAULTS["min_pocket_in"]
    depth_in: Optional[float] = None   # None = through


def check_params(p: LightenParams, plate_thk_in: Optional[float]) -> List[str]:
    """Problems that stop the cut (empty list = OK). Written for students."""
    problems: List[str] = []
    if p.wall_in < 0.05:
        problems.append('The outside wall must be at least 0.05" wide.')
    if p.rib_in < 0.05:
        problems.append('Ribs must be at least 0.05" wide.')
    if p.boss_in < 0.03:
        problems.append('Leave at least 0.03" of material around holes.')
    if p.min_pocket_in < 2 * p.corner_in:
        problems.append(f'"Smallest pocket" ({p.min_pocket_in:.3f}") must be at least twice the corner radius '
                        f'({2 * p.corner_in:.3f}") or the cutter won\'t fit in it.')
    if p.depth_in is not None:
        if p.depth_in <= 0:
            problems.append("Pocket depth must be more than 0 (or pick Through).")
        elif plate_thk_in is not None and p.depth_in > plate_thk_in - MIN_FLOOR_IN:
            problems.append(f'A {p.depth_in:.3f}" pocket in a {plate_thk_in:.3f}" plate leaves less than '
                            f'{MIN_FLOOR_IN}" of floor. Make it shallower, or pick Through.')
    return problems


# ---------------------------------------------------------------------------
# Plate description (filled in from Fusion by the command)
# ---------------------------------------------------------------------------
@dataclass
class Hole:
    poly: Poly                          # outline (closed, last point != first)
    center: Optional[Pt] = None         # set for round holes
    radius: float = 0.0


@dataclass
class Plate:
    outer: Poly
    holes: List[Hole] = field(default_factory=list)
    corners: List[Pt] = field(default_factory=list)   # outline corners + arc midpoints (for Quick Rib)


TAU = 2 * math.pi


@dataclass
class Rib:
    """
    A rib centerline: a straight line a->b, a full circle (center + radius), or
    an arc (center + radius + start angle + sweep, radians, counter-clockwise).
    `kind` says which Quick Rib rule made it (row, arc, spoke, support, fill) -
    handy for logs and tests.
    """
    a: Pt = (0.0, 0.0)
    b: Pt = (0.0, 0.0)
    center: Optional[Pt] = None
    radius: float = 0.0
    start: float = 0.0
    sweep: float = TAU
    kind: str = ""
    width: Optional[float] = None     # None = the normal rib width

    @property
    def is_circle(self) -> bool:
        """Round (full circle or arc) rather than straight."""
        return self.center is not None

    @property
    def is_full_circle(self) -> bool:
        return self.center is not None and self.sweep >= TAU - 1e-9


def arc_point(center: Pt, radius: float, angle: float) -> Pt:
    return (center[0] + radius * math.cos(angle), center[1] + radius * math.sin(angle))


def arc_rib(center: Pt, radius: float, start: float, sweep: float, kind: str = "") -> Rib:
    rib = Rib(center=center, radius=radius, start=start % TAU, sweep=min(sweep, TAU), kind=kind)
    if not rib.is_full_circle:
        rib.a, rib.b = arc_point(center, radius, rib.start), arc_point(center, radius, rib.start + rib.sweep)
    return rib


def rib_distance(p: Pt, rib: Rib) -> float:
    """Distance from a point to a rib's centerline."""
    if rib.center is None:
        return dist_to_segment(p, rib.a, rib.b)
    d = dist(p, rib.center)
    if rib.is_full_circle:
        return abs(d - rib.radius)
    rel = (math.atan2(p[1] - rib.center[1], p[0] - rib.center[0]) - rib.start) % TAU
    if rel <= rib.sweep:
        return abs(d - rib.radius)
    return min(dist(p, rib.a), dist(p, rib.b))


def arc_through(p0: Pt, pm: Pt, p1: Pt, kind: str = "") -> Optional[Rib]:
    """The arc from p0 through pm to p1 (any direction), as a counter-clockwise arc rib."""
    ax, ay = p0
    bx, by = pm
    cx, cy = p1
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return None          # the three points are in a line
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    c = (ux, uy)
    a0 = math.atan2(ay - uy, ax - ux)
    am = math.atan2(by - uy, bx - ux)
    a1 = math.atan2(cy - uy, cx - ux)
    s1, sm = (a1 - a0) % TAU, (am - a0) % TAU
    if sm <= s1:
        return arc_rib(c, dist(c, p0), a0, s1, kind)
    return arc_rib(c, dist(c, p0), a1, TAU - s1, kind)


def offset_strip(points: Sequence[Pt], width: float) -> Poly:
    """
    One closed outline around a curvy rib's centerline (a spline, say): the left
    side going forward, then the right side coming back, with mitered joints.
    Drawing this instead of one rectangle per piece is what keeps the pocket
    edge smooth - separate rectangles leave a notch at every joint.
    """
    pts = [p for i, p in enumerate(points) if i == 0 or dist(p, points[i - 1]) > 1e-6]
    if len(pts) < 2:
        return []
    half = width / 2

    def normal(i: int) -> Pt:
        a, b = pts[i], pts[i + 1]
        L = dist(a, b)
        return (-(b[1] - a[1]) / L, (b[0] - a[0]) / L)

    left: List[Pt] = []
    right: List[Pt] = []
    n_seg = len(pts) - 1
    for i, p in enumerate(pts):
        if i == 0:
            nx, ny = normal(0)
            scale = 1.0
        elif i == n_seg:
            nx, ny = normal(n_seg - 1)
            scale = 1.0
        else:
            n0, n1 = normal(i - 1), normal(i)
            mx, my = n0[0] + n1[0], n0[1] + n1[1]
            ml = math.hypot(mx, my)
            if ml < 1e-9:
                nx, ny, scale = n1[0], n1[1], 1.0
            else:
                nx, ny = mx / ml, my / ml
                cos_half = nx * n1[0] + ny * n1[1]
                scale = min(1.0 / max(cos_half, 1e-6), 3.0)    # miter, capped for sharp kinks
        left.append((p[0] + nx * half * scale, p[1] + ny * half * scale))
        right.append((p[0] - nx * half * scale, p[1] - ny * half * scale))
    return left + right[::-1]


def rib_points(rib: Rib, n: int = 32) -> List[Pt]:
    """Points along a rib (for crossing checks and drawing previews)."""
    if rib.center is None:
        return [rib.a, rib.b]
    return [arc_point(rib.center, rib.radius, rib.start + rib.sweep * k / n) for k in range(n + 1)]


# ---------------------------------------------------------------------------
# Small geometry helpers
# ---------------------------------------------------------------------------
def dist(a: Pt, b: Pt) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def dist_to_segment(p: Pt, a: Pt, b: Pt) -> float:
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    L2 = dx * dx + dy * dy
    if L2 <= 1e-18:
        return dist(p, a)
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def dist_to_poly(p: Pt, poly: Sequence[Pt]) -> float:
    n = len(poly)
    return min(dist_to_segment(p, poly[i], poly[(i + 1) % n]) for i in range(n)) if n else float("inf")


def inside(p: Pt, poly: Sequence[Pt]) -> bool:
    """Even-odd point-in-polygon."""
    x, y = p
    result = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            x_cross = xi + (y - yi) * (xj - xi) / (yj - yi)
            if x < x_cross:
                result = not result
        j = i
    return result


def area(poly: Sequence[Pt]) -> float:
    s = 0.0
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return abs(s) / 2


def perimeter(poly: Sequence[Pt]) -> float:
    n = len(poly)
    return sum(dist(poly[i], poly[(i + 1) % n]) for i in range(n))


def hole_gap(p: Pt, hole) -> float:
    """Signed distance from p to a hole's edge: negative inside the hole. Round holes are exact and fast."""
    if hole.center is not None:
        return dist(p, hole.center) - hole.radius
    d = dist_to_poly(p, hole.poly)
    return -d if inside(p, hole.poly) else d


def in_region(p: Pt, outer: Sequence[Pt], inners: Sequence[Sequence[Pt]]) -> bool:
    return inside(p, outer) and not any(inside(p, h) for h in inners)


def interior_point(outer: Sequence[Pt], inners: Sequence[Sequence[Pt]] = ()) -> Optional[Pt]:
    """
    A point well inside a region (outer loop minus inner loops), as far from its
    edges as we can cheaply find. We scan across the region and keep the middle
    of the inside stretch with the most clearance (the centroid is a candidate
    too). Points sitting ON an edge never count, so a ring's hole can't fool it.
    """
    if len(outer) < 3:
        return None
    loops = [outer, *inners]

    def clearance(p: Pt) -> float:
        if not in_region(p, outer, inners):
            return -1.0
        return min(dist_to_poly(p, loop) for loop in loops)

    cx = sum(p[0] for p in outer) / len(outer)
    cy = sum(p[1] for p in outer) / len(outer)
    best_p, best_c = (cx, cy), clearance((cx, cy))
    ys = [p[1] for p in outer]
    lo, hi = min(ys), max(ys)
    for k in range(1, 40):
        y = lo + (hi - lo) * (k + 0.37) / 40.37     # odd offset: avoid scanning exactly through vertices
        xs: List[float] = []
        for loop in loops:
            n = len(loop)
            for i in range(n):
                (x0, y0), (x1, y1) = loop[i], loop[(i + 1) % n]
                if (y0 > y) != (y1 > y):
                    xs.append(x0 + (y - y0) * (x1 - x0) / (y1 - y0))
        xs.sort()
        for i in range(len(xs) - 1):
            if xs[i + 1] - xs[i] > 1e-9:
                mid = ((xs[i] + xs[i + 1]) / 2, y)
                c = clearance(mid)
                if c > best_c:
                    best_p, best_c = mid, c
    return best_p if best_c > 1e-9 else None


def chain_loop(pieces: Sequence[Sequence[Pt]], tol: float = 1e-3) -> Poly:
    """
    Join curve pieces (each a list of points, in any direction) into one closed
    outline. Fusion hands a profile's curves over in order, but each curve may
    point either way, so we flip pieces as needed to make them meet end to end.
    """
    pieces = [list(p) for p in pieces if len(p) >= 2]
    if not pieces:
        return []
    out = list(pieces[0])
    rest = pieces[1:]
    if rest:
        # Point the first piece toward its nearest neighbour.
        near_start = min(min(dist(out[0], q[0]), dist(out[0], q[-1])) for q in rest)
        near_end = min(min(dist(out[-1], q[0]), dist(out[-1], q[-1])) for q in rest)
        if near_start < near_end:
            out.reverse()
    while rest:
        tail = out[-1]
        best_i, best_flip, best_d = 0, False, float("inf")
        for i, piece in enumerate(rest):
            for flip, end in ((False, piece[0]), (True, piece[-1])):
                d = dist(tail, end)
                if d < best_d:
                    best_i, best_flip, best_d = i, flip, d
        piece = rest.pop(best_i)
        if best_flip:
            piece.reverse()
        out.extend(piece[1:] if dist(out[-1], piece[0]) <= tol else piece)
    if len(out) > 1 and dist(out[0], out[-1]) <= tol:
        out.pop()
    return out


def inradius_estimate(region_area: float, region_perimeter: float) -> float:
    """2*Area/Perimeter: exact for circles and triangles, close enough for pockets."""
    return 2 * region_area / region_perimeter if region_perimeter > 0 else 0.0


# ---------------------------------------------------------------------------
# Lighten: which sketch regions become pockets?
# ---------------------------------------------------------------------------
KEEP_OUTSIDE, KEEP_WALL, KEEP_HOLE, KEEP_BOSS, KEEP_RIB, POCKET = (
    "outside", "wall", "hole", "boss", "rib", "pocket")


def classify(p: Pt, plate: Plate, ribs: Sequence[Rib], params: LightenParams, tol: float = 1e-4) -> str:
    """What a point on the plate is: part of a pocket, or material we keep (and why)."""
    if not inside(p, plate.outer):
        return KEEP_OUTSIDE
    if dist_to_poly(p, plate.outer) < params.wall_in - tol:
        return KEEP_WALL
    for hole in plate.holes:
        gap = hole_gap(p, hole)
        if gap < 0:
            return KEEP_HOLE
        if gap < params.boss_in - tol:
            return KEEP_BOSS
    for rib in ribs:
        if rib_distance(p, rib) < (rib.width or params.rib_in) / 2 - tol:
            return KEEP_RIB
    return POCKET


def edge_tabs(plate: Plate, params: LightenParams) -> List[Rib]:
    """
    Holes close to the outside wall get a tab joining their ring to the wall.
    Without it, the thin gap between ring and wall (too narrow to cut) links the
    pockets on either side into one snaking region - keep one solid and you'd
    keep them all, and the cutter can't follow the gap anyway.
    """
    tabs = []
    for hole in plate.holes:
        if hole.center is None:
            continue
        ring = hole.radius + params.boss_in
        gap = dist_to_poly(hole.center, plate.outer) - ring - params.wall_in
        if 0 < gap < params.min_pocket_in:
            n = len(plate.outer)
            best = min(((dist_to_segment(hole.center, plate.outer[i], plate.outer[(i + 1) % n]), i) for i in range(n)))
            a, b = plate.outer[best[1]], plate.outer[(best[1] + 1) % n]
            ex, ey = b[0] - a[0], b[1] - a[1]
            L2 = ex * ex + ey * ey
            t = 0.0 if L2 < 1e-18 else max(0.0, min(1.0, ((hole.center[0] - a[0]) * ex + (hole.center[1] - a[1]) * ey) / L2))
            foot = (a[0] + t * ex, a[1] + t * ey)
            tabs.append(Rib(hole.center, foot, kind="tab", width=2 * ring))
    return tabs


def pocket_too_small(region_area: float, region_perimeter: float, params: LightenParams) -> bool:
    return inradius_estimate(region_area, region_perimeter) < max(params.min_pocket_in / 2, params.corner_in * 1.2)


def rib_strip(rib: Rib, width: float) -> Poly:
    """Rectangle around a straight rib's centerline (the sketch lines Lighten draws)."""
    width = rib.width or width
    (ax, ay), (bx, by) = rib.a, rib.b
    L = math.hypot(bx - ax, by - ay)
    if L < 1e-9:
        return []
    nx, ny = -(by - ay) / L * width / 2, (bx - ax) / L * width / 2
    return [(ax + nx, ay + ny), (bx + nx, by + ny), (bx - nx, by - ny), (ax - nx, ay - ny)]


def polyline_ribs(points: Sequence[Pt], closed: bool = False) -> List[Rib]:
    """Arcs/splines from a student's sketch, as short straight ribs."""
    pts = list(points) + ([points[0]] if closed and points else [])
    return [Rib(pts[i], pts[i + 1]) for i in range(len(pts) - 1) if dist(pts[i], pts[i + 1]) > 1e-6]


# ---------------------------------------------------------------------------
# Quick Rib
# ---------------------------------------------------------------------------
# Rules, in order (the way FRC designers rib a plate by hand):
#   1. ROWS     holes in a straight line on close spacing get one rib through them
#   2. ARCS     holes evenly spaced around a bearing (a bolt circle) get a curved rib
#   3. SPOKES   every bearing gets ribs out to the edge / its neighbours
#   4. FILL     leftover space gets triangle ribs (a Delaunay triangulation)
#   5. SUPPORT  every hole must end up held from two sides - two ribs at least
#               90 degrees apart - or, if its ring already touches the outside
#               wall, by one more rib. Missing ribs are added here.
BEARING_MIN_DIA_IN = 0.6       # a round hole this big or bigger is treated as a bearing
ROW_MAX_GAP_IN = 1.05          # holes this close (or closer) in a line make a row
ROW_LINE_TOL_IN = 0.02
BOLT_CIRCLE_TOL_IN = 0.03      # bolt holes must sit this close to the same radius
BOLT_CIRCLE_REACH_IN = 2.0     # ...and within this far outside the bearing
SUPPORT_ANGLE = math.pi / 2    # "two sides" = two ribs at least this far apart
SPOKE_SPREAD = math.radians(60)


@dataclass
class Node:
    p: Pt
    kind: str              # "hole" or "edge"
    owner: int = -1        # hole index (hole nodes / hole-edge nodes); -1 = plate outline
    members: Tuple[int, ...] = ()   # hole indexes merged into this node
    bearing: bool = False


def _cluster_holes(plate: Plate, boss: float) -> List[Node]:
    """
    Round holes whose rings touch become one node (e.g. two screws 0.5" apart).
    A node containing a bearing sits at the bearing's center.
    """
    round_ids = [i for i, h in enumerate(plate.holes) if h.center is not None]
    parent = {i: i for i in round_ids}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for x in range(len(round_ids)):
        for y in range(x + 1, len(round_ids)):
            i, j = round_ids[x], round_ids[y]
            hi, hj = plate.holes[i], plate.holes[j]
            # Rings must really overlap: holes on FRC's 0.5in spacing just touch, and stay separate.
            if dist(hi.center, hj.center) < hi.radius + hj.radius + 2 * boss - 0.01:  # type: ignore[arg-type]
                parent[find(i)] = find(j)
    groups: Dict[int, List[int]] = {}
    for i in round_ids:
        groups.setdefault(find(i), []).append(i)
    nodes = []
    for members in groups.values():
        members.sort()
        biggest = max(members, key=lambda j: plate.holes[j].radius)
        is_bearing = 2 * plate.holes[biggest].radius >= BEARING_MIN_DIA_IN
        if is_bearing:
            c = plate.holes[biggest].center
        else:
            c = (sum(plate.holes[j].center[0] for j in members) / len(members),  # type: ignore[index]
                 sum(plate.holes[j].center[1] for j in members) / len(members))  # type: ignore[index]
        nodes.append(Node(c, "hole", biggest, tuple(members), is_bearing))  # type: ignore[arg-type]
    return nodes


def _edge_nodes(loop: Sequence[Pt], corners: Sequence[Pt], max_span: float, owner: int) -> List[Node]:
    """Points along an outline where ribs may land: corners, plus extra ones on long sides."""
    pts = list(corners) if corners else list(loop)
    out: List[Pt] = []
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        out.append(a)
        L = dist(a, b)
        pieces = int(math.ceil(L / max_span)) if max_span > 0 else 1
        for k in range(1, pieces):
            t = k / pieces
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return [Node(p, "edge", owner) for p in out]


def _merge_close(nodes: List[Node], gap: float) -> List[Node]:
    kept: List[Node] = []
    for node in nodes:
        if all(dist(node.p, k.p) >= gap for k in kept):
            kept.append(node)
    return kept


def delaunay(points: Sequence[Pt]) -> List[Tuple[int, int, int]]:
    """Bowyer-Watson triangulation. Returns triangles as index triples."""
    n = len(points)
    if n < 3:
        return []
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    span = max(maxx - minx, maxy - miny, 1e-6) * 20
    midx, midy = (minx + maxx) / 2, (miny + maxy) / 2
    pts = list(points) + [(midx - span, midy - span), (midx + span, midy - span), (midx, midy + span)]
    tris: List[Tuple[int, int, int]] = [(n, n + 1, n + 2)]

    def circum(t):
        (ax, ay), (bx, by), (cx, cy) = pts[t[0]], pts[t[1]], pts[t[2]]
        d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
        if abs(d) < 1e-14:
            return (0.0, 0.0, float("inf"))
        ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
        uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
        return (ux, uy, (ux - ax) ** 2 + (uy - ay) ** 2)

    cache = {tris[0]: circum(tris[0])}
    for i in range(n):
        px, py = pts[i]
        bad = [t for t in tris if (px - cache[t][0]) ** 2 + (py - cache[t][1]) ** 2 < cache[t][2] * (1 - 1e-9)]
        edges: Dict[Tuple[int, int], int] = {}
        for t in bad:
            for e in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                key = (min(e), max(e))
                edges[key] = edges.get(key, 0) + 1
        bad_set = set(bad)
        tris = [t for t in tris if t not in bad_set]
        for (a, b), count in edges.items():
            if count == 1:
                t = (a, b, i)
                tris.append(t)
                cache[t] = circum(t)
    return [t for t in tris if max(t) < n]


def _segments_cross(a: Pt, b: Pt, c: Pt, d: Pt, tol: float = 1e-6) -> bool:
    """True if segments ab and cd cross somewhere other than a shared end."""
    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    if min(dist(a, c), dist(a, d), dist(b, c), dist(b, d)) < 1e-6:
        return False
    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    return (o1 > tol and o2 < -tol or o1 < -tol and o2 > tol) and (o3 > tol and o4 < -tol or o3 < -tol and o4 > tol)


def _ray_hit_poly(p: Pt, u: Pt, poly: Sequence[Pt]) -> Optional[float]:
    best = None
    n = len(poly)
    for i in range(n):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
        ex, ey = x1 - x0, y1 - y0
        den = u[0] * ey - u[1] * ex
        if abs(den) < 1e-12:
            continue
        t = ((x0 - p[0]) * ey - (y0 - p[1]) * ex) / den
        s = ((x0 - p[0]) * u[1] - (y0 - p[1]) * u[0]) / den
        if t > 1e-6 and -1e-9 <= s <= 1 + 1e-9 and (best is None or t < best):
            best = t
    return best


def _ray_hit_circle(p: Pt, u: Pt, c: Pt, r: float) -> Optional[float]:
    fx, fy = p[0] - c[0], p[1] - c[1]
    b = fx * u[0] + fy * u[1]
    disc = b * b - (fx * fx + fy * fy - r * r)
    if disc < 0:
        return None
    for t in (-b - math.sqrt(disc), -b + math.sqrt(disc)):
        if t > 1e-6:
            return t
    return None


def _angle_gap_ok(dirs: Sequence[float]) -> bool:
    """Two of these directions are at least SUPPORT_ANGLE apart."""
    for i in range(len(dirs)):
        for j in range(i + 1, len(dirs)):
            diff = abs((dirs[i] - dirs[j] + math.pi) % TAU - math.pi)
            if diff >= SUPPORT_ANGLE - 1e-6:
                return True
    return False


def _ray_hit_rib(p: Pt, u: Pt, rib: Rib) -> Optional[float]:
    """Distance along a ray to a rib's centerline (straight or arc)."""
    if rib.center is None:
        ex, ey = rib.b[0] - rib.a[0], rib.b[1] - rib.a[1]
        den = u[0] * ey - u[1] * ex
        if abs(den) < 1e-12:
            return None
        t = ((rib.a[0] - p[0]) * ey - (rib.a[1] - p[1]) * ex) / den
        s = ((rib.a[0] - p[0]) * u[1] - (rib.a[1] - p[1]) * u[0]) / den
        return t if t > 1e-6 and 0.0 <= s <= 1.0 else None
    fx, fy = p[0] - rib.center[0], p[1] - rib.center[1]
    b = fx * u[0] + fy * u[1]
    disc = b * b - (fx * fx + fy * fy - rib.radius ** 2)
    if disc < 0:
        return None
    for t in sorted((-b - math.sqrt(disc), -b + math.sqrt(disc))):
        if t > 1e-6:
            q = (p[0] + u[0] * t, p[1] + u[1] * t)
            if rib_distance(q, rib) < 1e-6:
                return t
    return None


class _QuickRib:
    """Holds the plate, nodes and ribs while the rules run."""

    def __init__(self, plate: Plate, params: LightenParams, max_span: float):
        self.plate, self.params, self.max_span = plate, params, max_span
        self.hug = params.wall_in + params.rib_in / 2 + 0.75 * params.min_pocket_in
        self.min_free = max(params.min_pocket_in, 2 * params.rib_in)
        self.groups = _cluster_holes(plate, params.boss_in)
        self.group_of = {m: gi for gi, g in enumerate(self.groups) for m in g.members}
        self.ribs: List[Rib] = []
        self._scores: Dict[tuple, Optional[Tuple[float, float]]] = {}

    # --- checks -------------------------------------------------------------
    def score(self, a: Pt, b: Pt, allowed: set) -> Optional[Tuple[float, float]]:
        """None if a straight rib a->b can't exist; else (free length, share hugging the edge)."""
        key = (a, b, frozenset(allowed))
        if key not in self._scores:
            self._scores[key] = self._score(a, b, allowed)
        return self._scores[key]

    def _score(self, a: Pt, b: Pt, allowed: set) -> Optional[Tuple[float, float]]:
        plate, params = self.plate, self.params
        L = dist(a, b)
        if L < params.wall_in + params.rib_in:
            return None
        # A rib that lands on the edge must meet it at a decent angle; sliding in at a
        # shallow angle leaves a long thin sliver between it and the wall.
        square_ends = []
        u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
        for e in (a, b):
            if dist_to_poly(e, plate.outer) < 1e-3:
                n = len(plate.outer)
                k = min(range(n), key=lambda i: dist_to_segment(e, plate.outer[i], plate.outer[(i + 1) % n]))
                p0, p1 = plate.outer[k], plate.outer[(k + 1) % n]
                el = dist(p0, p1)
                if el > 1e-9:
                    cos_a = abs(u[0] * (p1[0] - p0[0]) / el + u[1] * (p1[1] - p0[1]) / el)
                    if cos_a > math.cos(math.radians(35)):
                        return None
                square_ends.append(e)
        free_d: List[float] = []
        for k in range(40):
            s = (k + 0.5) / 40
            q = (a[0] + (b[0] - a[0]) * s, a[1] + (b[1] - a[1]) * s)
            if not inside(q, plate.outer) and dist_to_poly(q, plate.outer) > 1e-4:
                return None   # leaves the plate (concave outline)
            for h_id, hole in enumerate(plate.holes):
                if h_id not in allowed and hole_gap(q, hole) < -1e-4:
                    return None   # crosses another hole or cutout
            if classify(q, plate, (), params) == POCKET:
                d_edge = dist_to_poly(q, plate.outer)
                if any(dist(q, e) < self.hug for e in square_ends):
                    d_edge = float("inf")     # the stretch where a rib meets the edge square-on is fine
                free_d.append(d_edge)
        free_len = len(free_d) / 40 * L
        hugging = sum(1 for d in free_d if d < self.hug) / len(free_d) if free_d else 1.0
        return free_len, hugging

    def crosses_existing(self, a: Pt, b: Pt) -> bool:
        # Ignore the very ends: a rib starting at a bolt hole touches the arc running
        # through that hole, and that's a joint, not a crossing.
        L = dist(a, b)
        if L < 1e-9:
            return False
        trim = min(0.25, 0.2 * L)
        u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
        a, b = (a[0] + u[0] * trim, a[1] + u[1] * trim), (b[0] - u[0] * trim, b[1] - u[1] * trim)
        for rib in self.ribs:
            pts = rib_points(rib)
            for i in range(len(pts) - 1):
                if _segments_cross(a, b, pts[i], pts[i + 1]):
                    return True
        return False

    def too_close_to_existing(self, a: Pt, b: Pt) -> bool:
        """
        A rib running alongside another one (nearly parallel, close by) would only
        leave a sliver between them. Ribs meeting at a real angle are fine.
        """
        gap = self.params.rib_in + self.params.min_pocket_in * 1.6
        L = dist(a, b)
        if L < 1e-9:
            return False
        u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
        for s in (0.3, 0.5, 0.7):
            q = (a[0] + (b[0] - a[0]) * s, a[1] + (b[1] - a[1]) * s)
            for r in self.ribs:
                if rib_distance(q, r) >= gap:
                    continue
                if r.center is None:
                    rl = dist(r.a, r.b)
                    v = ((r.b[0] - r.a[0]) / rl, (r.b[1] - r.a[1]) / rl) if rl > 1e-9 else u
                else:
                    th = math.atan2(q[1] - r.center[1], q[0] - r.center[0])
                    v = (-math.sin(th), math.cos(th))
                if abs(u[0] * v[0] + u[1] * v[1]) > math.cos(math.radians(30)):
                    return True
        return False

    def makes_sliver(self, a: Pt, b: Pt) -> bool:
        """Two straight ribs meeting at (nearly) the same point at a sharp angle leave a sliver."""
        L = dist(a, b)
        if L < 1e-9:
            return False
        near = self.params.rib_in + self.params.min_pocket_in
        for here, there in ((a, b), (b, a)):
            u = ((there[0] - here[0]) / L, (there[1] - here[1]) / L)
            for r in self.ribs:
                if r.center is not None:
                    continue
                for e, o in ((r.a, r.b), (r.b, r.a)):
                    if dist(e, here) < near:
                        rl = dist(e, o)
                        if rl < 1e-9:
                            continue
                        v = ((o[0] - e[0]) / rl, (o[1] - e[1]) / rl)
                        if u[0] * v[0] + u[1] * v[1] > math.cos(math.radians(25)):
                            return True
        return False

    def members_near(self, p: Pt) -> set:
        """Hole indexes of the node at point p (a rib end)."""
        for g in self.groups:
            if dist(g.p, p) < 1e-6:
                return set(g.members)
        return set()

    def add(self, rib: Rib) -> None:
        self.ribs.append(rib)

    # --- support bookkeeping -------------------------------------------------
    def directions(self, gi: int) -> List[float]:
        """Directions (radians) of ribs leaving node gi."""
        g = self.groups[gi]
        holes = [self.plate.holes[m] for m in g.members]
        dirs: List[float] = []
        for rib in self.ribs:
            if rib.center is None:
                (ax, ay), (bx, by) = rib.a, rib.b
                L = dist(rib.a, rib.b)
                if L < 1e-9:
                    continue
                ang = math.atan2(by - ay, bx - ax)
                if dist(rib.a, g.p) < 1e-6:
                    dirs.append(ang)
                elif dist(rib.b, g.p) < 1e-6:
                    dirs.append(ang + math.pi)
                else:
                    for h in holes:
                        if dist_to_segment(h.center, rib.a, rib.b) < h.radius:  # type: ignore[arg-type]
                            # passes through: count only the sides it actually continues to
                            t = ((h.center[0] - ax) * (bx - ax) + (h.center[1] - ay) * (by - ay)) / (L * L)  # type: ignore[index]
                            if t * L > h.radius:
                                dirs.append(ang + math.pi)
                            if (1 - t) * L > h.radius:
                                dirs.append(ang)
                            break
            else:
                for h in holes:
                    if rib_distance(h.center, rib) >= h.radius:  # type: ignore[arg-type]
                        continue
                    theta = math.atan2(h.center[1] - rib.center[1], h.center[0] - rib.center[0])  # type: ignore[index]
                    fwd, back = theta + math.pi / 2, theta - math.pi / 2     # tangents, counter-clockwise first
                    if rib.is_full_circle:
                        dirs += [fwd, back]
                    else:
                        rel = (theta - rib.start) % TAU
                        slack = h.radius / max(rib.radius, 1e-9)
                        if rel < rib.sweep - slack:
                            dirs.append(fwd)
                        if rel > slack:
                            dirs.append(back)
                    break
        return dirs

    def touches_wall(self, gi: int) -> bool:
        for m in self.groups[gi].members:
            h = self.plate.holes[m]
            # Within half a rib of the wall counts (FRC's usual 0.5"-from-the-edge holes).
            if dist_to_poly(h.center, self.plate.outer) - h.radius - self.params.boss_in <= \
                    self.params.wall_in + self.params.rib_in / 2 + 1e-6:  # type: ignore[arg-type]
                return True
        return False

    def supported(self, gi: int) -> bool:
        dirs = self.directions(gi)
        if self.touches_wall(gi) and dirs:
            return True
        return _angle_gap_ok(dirs)

    # --- rule 1: rows ---------------------------------------------------------
    def rows(self) -> None:
        small = [gi for gi, g in enumerate(self.groups) if not g.bearing]
        used: set = set()
        found: List[List[int]] = []
        for x in range(len(small)):
            for y in range(x + 1, len(small)):
                i, j = small[x], small[y]
                a, b = self.groups[i].p, self.groups[j].p
                L = dist(a, b)
                if L > ROW_MAX_GAP_IN or L < 1e-9:
                    continue
                u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
                line = [(((self.groups[k].p[0] - a[0]) * u[0] + (self.groups[k].p[1] - a[1]) * u[1]), k) for k in small
                        if abs((self.groups[k].p[0] - a[0]) * u[1] - (self.groups[k].p[1] - a[1]) * u[0]) < ROW_LINE_TOL_IN]
                line.sort()
                run = [line[0]]
                runs = []
                for item in line[1:]:
                    if item[0] - run[-1][0] <= ROW_MAX_GAP_IN:
                        run.append(item)
                    else:
                        runs.append(run)
                        run = [item]
                runs.append(run)
                for r in runs:
                    ids = [k for _, k in r]
                    if len(ids) >= 3 and i in ids and j in ids:
                        found.append(ids)
        for ids in sorted(found, key=len, reverse=True):
            if any(k in used for k in ids):
                continue
            a, b = self.groups[ids[0]].p, self.groups[ids[-1]].p
            allowed = set(m for k in ids for m in self.groups[k].members)
            if self.score(a, b, allowed) is None:
                continue
            self.add(Rib(a, b, kind="row"))
            used.update(ids)

    # --- rule 2: bolt circles --------------------------------------------------
    def bolt_circles(self) -> None:
        holes = self.plate.holes
        for bi, bh in enumerate(holes):
            if bh.center is None or 2 * bh.radius < BEARING_MIN_DIA_IN:
                continue
            near = []
            for hi, h in enumerate(holes):
                if hi == bi or h.center is None or 2 * h.radius >= BEARING_MIN_DIA_IN:
                    continue
                d = dist(h.center, bh.center)
                if bh.radius + h.radius < d <= bh.radius + BOLT_CIRCLE_REACH_IN:
                    near.append((d, hi))
            near.sort()
            clusters: List[List[Tuple[float, int]]] = []
            for item in near:
                if clusters and item[0] - clusters[-1][0][0] <= BOLT_CIRCLE_TOL_IN:
                    clusters[-1].append(item)
                else:
                    clusters.append([item])
            for cl in clusters:
                if len(cl) < 3:
                    continue
                radius = sum(d for d, _ in cl) / len(cl)
                angles = sorted(math.atan2(holes[hi].center[1] - bh.center[1], holes[hi].center[0] - bh.center[0])  # type: ignore[index]
                                for _, hi in cl)
                gaps = [((angles[(k + 1) % len(angles)] - angles[k]) % TAU or TAU) for k in range(len(angles))]
                widest = max(range(len(gaps)), key=lambda k: gaps[k])
                start = angles[(widest + 1) % len(angles)]
                options = []
                if gaps[widest] < 1.5 * sorted(gaps)[len(gaps) // 2]:      # evenly spaced all the way round
                    options.append(arc_rib(bh.center, radius, 0.0, TAU, "arc"))  # type: ignore[arg-type]
                options.append(arc_rib(bh.center, radius, start, TAU - gaps[widest], "arc"))  # type: ignore[arg-type]
                allowed = {hi for _, hi in cl} | {bi}
                for rib in options:          # full ring if it fits, otherwise the arc through the holes
                    if self._arc_ok(rib, allowed):
                        self.add(rib)
                        break

    def _arc_ok(self, rib: Rib, allowed: set) -> bool:
        for q in rib_points(rib, 64):
            if not inside(q, self.plate.outer) or dist_to_poly(q, self.plate.outer) < self.params.wall_in * 0.5:
                return False
            for h_id, hole in enumerate(self.plate.holes):
                if h_id not in allowed and hole_gap(q, hole) < self.params.rib_in / 2:
                    return False
        return True

    # --- rule 3: spokes ---------------------------------------------------------
    def cast(self, gi: int, ang: float, max_edge: float) -> Optional[Tuple[Pt, set]]:
        """
        Follow a ray from node gi. It stops at the first thing it meets: another
        hole (rib ends at that hole's center), an existing rib (a T onto it,
        snapped to a hole if one is right there), or the plate edge (only if
        that's within max_edge). Returns (end point, allowed hole ids) or None.
        """
        g = self.groups[gi]
        u = (math.cos(ang), math.sin(ang))
        best_t = _ray_hit_poly(g.p, u, self.plate.outer)
        if best_t is None:
            return None
        end: Optional[Pt] = None
        allowed = set(g.members)
        for oi, other in enumerate(self.groups):
            if oi == gi:
                continue
            for m in other.members:
                h = self.plate.holes[m]
                t = _ray_hit_circle(g.p, u, h.center, h.radius)  # type: ignore[arg-type]
                if t is not None and t < best_t:
                    best_t, end, allowed = t, other.p, set(g.members) | set(other.members)
        for rib in self.ribs:
            if g.p in (rib.a, rib.b):
                continue
            t = _ray_hit_rib(g.p, u, rib)
            if t is not None and t < best_t:
                q = (g.p[0] + u[0] * t, g.p[1] + u[1] * t)
                snap = [(dist(q, o.p), o) for o in self.groups
                        if dist(q, o.p) < self.plate.holes[o.owner].radius + self.params.boss_in + self.params.rib_in]
                if snap:
                    o = min(snap, key=lambda x: x[0])[1]
                    best_t, end, allowed = t, o.p, set(g.members) | set(o.members)
                else:
                    best_t, end, allowed = t, q, set(g.members)
        if end is None:
            if best_t > max_edge:
                return None
            end = (g.p[0] + u[0] * best_t, g.p[1] + u[1] * best_t)
        return end, allowed

    def spokes(self) -> None:
        for gi, g in enumerate(self.groups):
            if not g.bearing:
                continue
            candidates = []
            for k in range(16):
                ang = k * math.pi / 8
                hit = self.cast(gi, ang, 0.75 * self.max_span)
                if hit is None:
                    continue
                end, allowed = hit
                sc = self.score(g.p, end, allowed)
                if sc is None or sc[0] < self.min_free or sc[1] > 0.5:
                    continue
                candidates.append((dist(g.p, end), ang, end))
            taken = [d for d in self.directions(gi)]
            for _L, ang, end in sorted(candidates):
                if all(abs((ang - t + math.pi) % TAU - math.pi) >= SPOKE_SPREAD - 1e-6 for t in taken):
                    if self.crosses_existing(g.p, end) or self.makes_sliver(g.p, end):
                        continue
                    self.add(Rib(g.p, end, kind="spoke"))
                    taken.append(ang)

    # --- rule 4: triangles ------------------------------------------------------
    def fill(self) -> None:
        plate, params = self.plate, self.params
        edge = _edge_nodes(plate.outer, plate.corners, self.max_span, -1)
        for i, hole in enumerate(plate.holes):
            if hole.center is None:
                edge += _edge_nodes(hole.poly, [], self.max_span, i)
        edge = [e for e in _merge_close(edge, max(2 * params.wall_in, 0.5))
                if all(dist(e.p, h.p) > params.wall_in + params.boss_in for h in self.groups)]
        nodes = self.groups + edge
        if len(nodes) < 3:
            return
        owner_loop = {-1: plate.outer, **{i: h.poly for i, h in enumerate(plate.holes)}}
        cands = []
        seen = set()
        for t in delaunay([n.p for n in nodes]):
            for i, j in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                key = (min(i, j), max(i, j))
                if key in seen:
                    continue
                seen.add(key)
                a, b = nodes[i], nodes[j]
                if a.kind == "edge" and b.kind == "edge":
                    mid = ((a.p[0] + b.p[0]) / 2, (a.p[1] + b.p[1]) / 2)
                    if a.owner == b.owner and dist_to_poly(mid, owner_loop[a.owner]) < self.hug:
                        continue      # runs along the outline - the wall is already there
                cands.append((dist(a.p, b.p), a, b))
        for _L, a, b in sorted(cands, key=lambda c: c[0]):
            allowed = set(a.members) | set(b.members)
            sc = self.score(a.p, b.p, allowed)
            if sc is None or sc[0] < self.min_free or sc[1] > 0.5:
                continue
            if self.crosses_existing(a.p, b.p) or self.too_close_to_existing(a.p, b.p) or \
                    self.makes_sliver(a.p, b.p):
                continue
            self.add(Rib(a.p, b.p, kind="fill"))

    # --- rule 5: every hole held from two sides ---------------------------------
    def support(self) -> None:
        for gi in range(len(self.groups)):
            for _attempt in range(3):
                if self.supported(gi):
                    break
                rib = self._best_support(gi)
                if rib is None:
                    break
                self.add(rib)

    def _best_support(self, gi: int) -> Optional[Rib]:
        g = self.groups[gi]
        have = self.directions(gi)
        wall = self.touches_wall(gi)
        targets: List[Tuple[Pt, set]] = [(o.p, set(o.members)) for oi, o in enumerate(self.groups) if oi != gi]
        for k in range(24):
            ang = k * math.pi / 12
            u = (math.cos(ang), math.sin(ang))
            t = _ray_hit_poly(g.p, u, self.plate.outer)
            if t is not None:
                targets.append(((g.p[0] + u[0] * t, g.p[1] + u[1] * t), set()))
        best: Optional[Tuple[Tuple[int, float], Rib]] = None
        for end, members in targets:
            sc = self.score(g.p, end, set(g.members) | members)
            if sc is None or sc[0] < self.params.rib_in:
                continue
            ang = math.atan2(end[1] - g.p[1], end[0] - g.p[0])
            dirs = have + [ang]
            fixes = (wall and bool(dirs)) or _angle_gap_ok(dirs)
            if not fixes and have:
                # Doesn't finish the job: only worth it if it spreads the directions out.
                spread = min(abs((ang - d + math.pi) % TAU - math.pi) for d in have)
                if spread < SUPPORT_ANGLE / 2:
                    continue
            cost = dist(g.p, end) * (1 + 2 * sc[1]) * (1.5 if self.crosses_existing(g.p, end) else 1.0) * \
                (2.0 if self.makes_sliver(g.p, end) else 1.0)
            key = (0 if fixes else 1, cost)
            if best is None or key < best[0]:
                best = (key, Rib(g.p, end, kind="support"))
        return best[1] if best else None

    def run(self) -> List[Rib]:
        self.rows()
        self.bolt_circles()
        self.spokes()
        self.fill()
        self.support()
        return self.ribs


def quick_ribs(plate: Plate, params: LightenParams, max_span_in: float = DEFAULTS["max_span_in"]) -> List[Rib]:
    """
    Rib centerlines for a plate: rows, bolt-circle arcs, bearing spokes, triangle
    fill, then extra ribs until every hole is held from two sides (see the rules
    above). Straight ribs end at hole centers or on the plate's edge.
    """
    if len(plate.outer) < 3:
        return []
    return _QuickRib(plate, params, max_span_in).run()


def unsupported_holes(plate: Plate, ribs: Sequence[Rib], params: LightenParams) -> List[Pt]:
    """Centers of hole groups NOT held from two sides by these ribs (for the dialog's warning)."""
    q = _QuickRib(plate, params, DEFAULTS["max_span_in"])
    q.ribs = list(ribs)
    return [g.p for gi, g in enumerate(q.groups) if not q.supported(gi)]


# ---------------------------------------------------------------------------
# Plain-language summary for the dialog
# ---------------------------------------------------------------------------
def summary(pockets: int, too_small: int, too_tight: int, removed_lb: Optional[float],
            before_lb: Optional[float]) -> List[str]:
    lines = [f"<b>{pockets}</b> pocket(s)"]
    if removed_lb is not None and before_lb:
        lines[0] += f" - saves <b>{removed_lb:.3f} lb</b> ({100 * removed_lb / before_lb:.0f}% of the plate)"
    if too_small:
        lines.append(f"{too_small} spot(s) left solid: smaller than the smallest pocket setting")
    if too_tight:
        lines.append(f"{too_tight} pocket(s) skipped: corners too tight for the cutter")
    return lines
