"""
frc_parts_core.py - the numbers behind Gusset's part generators (no Fusion imports,
unit-tested in tests/test_frc_parts_core.py).

  Tube     1x1 / 2x1 box tube along sketch lines, optional 0.5" hole pattern
  Shaft    1/2" hex shaft between two points, optional tapped ends
  Spacer   hex-bore spacer filling the gap between two faces on a shaft
  Belt     HTD 5mm belts and #25 / #35 chain: center-to-center distances

Everything is in INCHES.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .frc_features import HOLE_TABLE

MM = 1 / 25.4

# ---------------------------------------------------------------------------
# Tube
# ---------------------------------------------------------------------------
TUBE_SIZES: Dict[str, Tuple[float, float]] = {      # name -> (short side, long side)
    "1x1": (1.0, 1.0),
    "2x1": (1.0, 2.0),
}
TUBE_WALLS: Dict[str, float] = {'1/16" wall': 0.0625, '0.100" wall': 0.100, '1/8" wall': 0.125}
HOLE_PITCH_IN = 0.5
FIRST_HOLE_IN = 0.25            # first hole sits this far from the tube's end
HOLE_ROWS = {"1 row (center)": 1, "2 rows (0.5\" apart)": 2, "3 rows (0.5\" apart)": 3}
TUBE_HOLE_CHOICES = ["No holes", '#10 close (0.196")', '#10 clearance (0.201")', '1/4" clearance (0.266")']


def tube_hole_diameter(choice: str) -> Optional[float]:
    return {
        '#10 close (0.196")': HOLE_TABLE["#10"]["Close"][0],
        '#10 clearance (0.201")': HOLE_TABLE["#10"]["Clearance"][0],
        '1/4" clearance (0.266")': HOLE_TABLE['1/4"']["Clearance"][0],
    }.get(choice)


@dataclass
class TubePlan:
    size: str
    wall_in: float
    length_in: float
    across_in: float              # size across the sketch plane (perpendicular to the line)
    up_in: float                  # size along the sketch's normal
    holes_along: List[float] = field(default_factory=list)   # distances from the start
    rows_up_faces: List[float] = field(default_factory=list)       # hole rows on the faces facing "up" (offsets across)
    rows_side_faces: List[float] = field(default_factory=list)     # hole rows on the side faces (offsets up)
    hole_d_in: Optional[float] = None
    problems: List[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return f'Tube {self.size} x {self.length_in:.3f}"'


def hole_rows(face_width: float, rows: int) -> List[float]:
    """Row offsets from a face's center line, 0.5" apart, that fit on the face (with 0.25" to spare)."""
    offsets = [(k - (rows - 1) / 2) * HOLE_PITCH_IN for k in range(rows)]
    return [o for o in offsets if abs(o) <= face_width / 2 - 0.25 + 1e-9] or [0.0]


def along_positions(length: float, hole_d: float) -> List[float]:
    """Hole centers 0.25" from each end region, every 0.5", never closer than one diameter to the end."""
    out = []
    k = 0
    while True:
        x = FIRST_HOLE_IN + k * HOLE_PITCH_IN
        if x > length - max(FIRST_HOLE_IN, hole_d) + 1e-9:
            break
        out.append(round(x, 6))
        k += 1
    return out


def plan_tube(size: str, wall: str, length_in: float, tall: bool, holes: str = "No holes",
              wide_rows: int = 1) -> TubePlan:
    """
    tall=True stands a 2x1 on its 1" edge (2" along the sketch normal); False lays it flat.
    """
    short, long_ = TUBE_SIZES[size]
    across, up = (short, long_) if tall else (long_, short)
    plan = TubePlan(size, TUBE_WALLS[wall], length_in, across, up)
    if length_in < 0.25:
        plan.problems.append(f'A {length_in:.3f}" tube is too short - check the line (and the end extensions).')
    if plan.wall_in * 2 >= min(across, up):
        plan.problems.append("That wall is too thick for this tube.")
    d = tube_hole_diameter(holes)
    if d and not plan.problems:
        plan.hole_d_in = d
        plan.holes_along = along_positions(length_in, d)
        # Faces facing up/down are `across` wide; side faces are `up` tall.
        plan.rows_up_faces = hole_rows(across, wide_rows if across > 1.0 + 1e-9 else 1)
        plan.rows_side_faces = hole_rows(up, wide_rows if up > 1.0 + 1e-9 else 1)
    return plan


# ---------------------------------------------------------------------------
# Hex shaft and spacers
# ---------------------------------------------------------------------------
HEX_FLATS_IN = 0.5
HEX_CORNERS_IN = HEX_FLATS_IN / math.cos(math.radians(30))     # 0.577"
SHAFT_ENDS = ["Plain ends", "Tapped ends (#10-32)"]
TAP_DEPTH_IN = 0.5
SPACER_ODS = ['0.625"', '0.75"', '0.875"', '1.125"']
DEFAULT_SPACER_CLEARANCE_IN = 0.010      # added to the 1/2" hex bore (across flats)
DEFAULT_SPACER_GAP_IN = 0.005            # left at each end so the stack isn't over-tight


# Turned-round journal ends (ride in round-bore bearings like R8ZZ) and snap-ring
# grooves for a standard 1/2" external retaining ring (ANSI B27.7 / 5100-50 size).
ROUND_ENDS = ["No round ends", "Both ends", "Start only", "End only"]
DEFAULT_ROUND_D_IN = 0.500
DEFAULT_ROUND_LEN_IN = 0.375
GROOVES = ["No grooves", "Outside both plates"]
SNAP_RING_GROOVE_D_IN = 0.469
SNAP_RING_GROOVE_W_IN = 0.039
DEFAULT_GROOVE_GAP_IN = 0.070      # plate face -> groove: a bearing flange (~0.062") + a little


@dataclass
class ShaftPlan:
    length_in: float
    start_ext_in: float
    end_ext_in: float
    tapped: bool
    tap_d_in: float = HOLE_TABLE["#10"]["Tap"][0]
    round_start: bool = False
    round_end: bool = False
    round_d_in: float = DEFAULT_ROUND_D_IN
    round_len_in: float = DEFAULT_ROUND_LEN_IN
    grooves_in: List[float] = field(default_factory=list)     # groove centers, from the shaft's start
    groove_d_in: float = SNAP_RING_GROOVE_D_IN
    groove_w_in: float = SNAP_RING_GROOVE_W_IN
    problems: List[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        extras = []
        if self.round_start or self.round_end:
            extras.append("round " + ("ends" if self.round_start and self.round_end else
                                      "start" if self.round_start else "end"))
        if self.grooves_in:
            extras.append(f"{len(self.grooves_in)} groove{'s' if len(self.grooves_in) != 1 else ''}")
        return f'Shaft 1/2" hex x {self.length_in:.3f}"' + (f" ({', '.join(extras)})" if extras else "")

    def ring_cuts(self) -> List[Tuple[float, float, float]]:
        """
        Everything turned off the hex, as (from, to, diameter left) in inches from the
        shaft's start: round journals and snap-ring grooves. Both shaft builders cut
        exactly these, so preview, bodies and linked files always match.
        """
        cuts = []
        L, r = self.length_in, self.round_len_in
        if self.round_start:
            cuts.append((0.0, r, self.round_d_in))
        if self.round_end:
            cuts.append((L - r, L, self.round_d_in))
        for g in self.grooves_in:
            cuts.append((g - self.groove_w_in / 2, g + self.groove_w_in / 2, self.groove_d_in))
        return sorted(cuts)


FLANGE_SIDES = ["Flange outside the plates", "Flange inside the plates"]
BEARING_CLEARANCE_IN = 0.010         # snap ring -> bearing, so the stack isn't over-tight
STANDARD_BEARING_WIDTH_IN = 0.3125   # R8 / FR8 size bearings (1/2" bore x 1.125" OD x 5/16" wide)
STANDARD_FLANGE_IN = 0.0625


@dataclass
class BearingReference:
    """
    What a student needs to work out the numbers they type (0.12.3: shown as a note,
    never filled in for them). Inches.
    """
    groove_gap_in: float          # plate's outside face -> near edge of the snap-ring groove
    depth_in: float               # plate's outside face -> the bearing's inside face (where the shoulder sits)
    why_gap: str
    why_depth: str


def bearing_reference(width_in: float, flange_in: float, plate_in: float, flange_outside: bool) -> BearingReference:
    """
    Where a bearing sits in a plate, measured from the plate's OUTSIDE face:
      flange outside: flange on the outside face, body goes in
      flange inside:  flange on the inside face, body goes out through the hole
      no flange:      flush with the chosen face
    """
    c = BEARING_CLEARANCE_IN
    body = width_in - flange_in
    if flange_in > 0 and flange_outside:
        return BearingReference(flange_in + c, body,
                                f'flange {flange_in:.3f}" + {c:.3f}" clearance',
                                f'bearing {width_in:.3f}" wide - {flange_in:.3f}" flange sticks out')
    if flange_in > 0:
        stick_out = max(0.0, body - plate_in)
        return BearingReference(stick_out + c, plate_in + flange_in,
                                f'bearing pokes {stick_out:.3f}" past the plate + {c:.3f}" clearance',
                                f'plate {plate_in:.3f}" + {flange_in:.3f}" flange on the inside')
    if flange_outside:
        return BearingReference(c, width_in, f'flush with the plate + {c:.3f}" clearance',
                                f'bearing {width_in:.3f}" wide, flush with the outside face')
    stick_out = max(0.0, width_in - plate_in)
    return BearingReference(stick_out + c, plate_in, f'bearing pokes {stick_out:.3f}" past the plate + {c:.3f}" clearance',
                            f'plate {plate_in:.3f}" (bearing flush with the inside face)')


def parse_positions(text: str) -> Tuple[List[float], List[str]]:
    """'1.25, 2.5in 3"' -> ([1.25, 2.5, 3.0], []) - extra groove spots typed in the dialog."""
    values, problems = [], []
    for part in [p for p in (text or "").replace(";", ",").replace(" ", ",").split(",") if p.strip()]:
        raw = part.strip().lower().rstrip('"').replace("in", "").strip()
        try:
            values.append(float(raw))
        except ValueError:
            problems.append(f"'{part.strip()}' isn't a distance - type inches from the shaft's start, like 1.25")
    return values, problems


def plan_shaft(span_in: float, start_ext_in: float, end_ext_in: float, ends: str,
               round_ends: str = ROUND_ENDS[0], round_d_in: float = DEFAULT_ROUND_D_IN,
               round_len_in: float = DEFAULT_ROUND_LEN_IN, grooves_in: Optional[List[float]] = None,
               groove_d_in: float = SNAP_RING_GROOVE_D_IN, groove_w_in: float = SNAP_RING_GROOVE_W_IN) -> ShaftPlan:
    length = span_in + start_ext_in + end_ext_in
    plan = ShaftPlan(length, start_ext_in, end_ext_in, ends == SHAFT_ENDS[1],
                     round_start=round_ends in (ROUND_ENDS[1], ROUND_ENDS[2]),
                     round_end=round_ends in (ROUND_ENDS[1], ROUND_ENDS[3]),
                     round_d_in=round_d_in, round_len_in=round_len_in,
                     grooves_in=sorted(round(g, 4) for g in (grooves_in or [])),
                     groove_d_in=groove_d_in, groove_w_in=groove_w_in)
    if span_in < 1e-4:
        plan.problems.append("The two ends are in the same spot - pick two different points.")
    elif length < 0.25:
        plan.problems.append(f'A {length:.3f}" shaft is too short - check the extensions.')
    if plan.tapped and length < 2 * TAP_DEPTH_IN + 0.1:
        plan.problems.append(f'Too short to tap both ends {TAP_DEPTH_IN}" deep.')
    if plan.round_start or plan.round_end:
        if not 0.2 <= round_d_in < HEX_CORNERS_IN:
            plan.problems.append(f'A round end has to be between 0.2" and {HEX_CORNERS_IN:.3f}" across '
                                 '(the hex\'s corners) - 0.500" fits 1/2" round bearings.')
        if round_len_in <= 0:
            plan.problems.append("Give the round ends a length.")
        elif (plan.round_start + plan.round_end) * round_len_in > length - 0.1:
            plan.problems.append(f'The round ends ({round_len_in:.3f}" each) are longer than the shaft leaves room for.')
        if plan.tapped and round_d_in < plan.tap_d_in + 0.1:
            plan.problems.append("The round ends are too thin to tap.")
    if plan.grooves_in:
        if not 0 < groove_w_in < 0.25 or not 0.2 < groove_d_in < HEX_FLATS_IN:
            plan.problems.append('Snap-ring grooves need a width under 0.25" and a diameter under the hex (0.5").')
        for g in plan.grooves_in:
            if g - groove_w_in / 2 < 0.03 or g + groove_w_in / 2 > length - 0.03:
                plan.problems.append(f'A groove at {g:.3f}" is off the end of the {length:.3f}" shaft - make the '
                                     "shaft longer past the plate (Past start / Past end).")
            for lo, hi, d in [c for c in plan.ring_cuts() if abs(c[2] - groove_d_in) > 1e-9]:
                if lo - groove_w_in < g < hi + groove_w_in and d <= groove_d_in:
                    plan.problems.append(f"The groove at {g:.3f}\" is on a round end that's already thinner.")
        for a, b in zip(plan.grooves_in, plan.grooves_in[1:]):
            if b - a < groove_w_in * 2:
                plan.problems.append(f'Grooves at {a:.3f}" and {b:.3f}" overlap.')
    return plan


@dataclass
class SpacerPlan:
    length_in: float
    od_in: float
    bore_flats_in: float
    problems: List[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return f'Spacer {self.od_in:g}" OD x {self.length_in:.3f}"'


def plan_spacer(gap_between_faces_in: float, od: str, clearance_in: float = DEFAULT_SPACER_CLEARANCE_IN,
                end_gap_in: float = DEFAULT_SPACER_GAP_IN) -> SpacerPlan:
    od_in = float(od.strip('"'))
    plan = SpacerPlan(gap_between_faces_in - 2 * end_gap_in, od_in, HEX_FLATS_IN + clearance_in)
    if plan.length_in < 0.03:
        plan.problems.append(f'The gap is only {gap_between_faces_in:.3f}" - too small for a spacer.')
    corners = plan.bore_flats_in / math.cos(math.radians(30))
    if od_in - corners < 0.08:
        plan.problems.append(f'A {od}" spacer leaves less than 0.04" of wall around the hex - pick a bigger OD.')
    return plan


# ---------------------------------------------------------------------------
# Belts and chain
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Drive:
    name: str
    pitch_in: float
    kind: str        # "belt" or "chain"


DRIVES: Dict[str, Drive] = {
    "HTD 5mm belt": Drive("HTD 5mm belt", 5 * MM, "belt"),
    "#25 chain": Drive("#25 chain", 0.25, "chain"),
    "#35 chain": Drive("#35 chain", 0.375, "chain"),
}


def pitch_diameter(drive: Drive, teeth: int) -> float:
    """Belt pulleys: T*p/pi. Sprockets: p / sin(180deg/T) (the chain pins sit on this circle)."""
    if drive.kind == "belt":
        return teeth * drive.pitch_in / math.pi
    return drive.pitch_in / math.sin(math.pi / teeth)


def belt_length(drive: Drive, t1: int, t2: int, center_in: float) -> float:
    """Open-belt pitch length for two pulleys (exact geometry)."""
    d1, d2 = sorted((pitch_diameter(drive, t1), pitch_diameter(drive, t2)))
    beta = math.asin(min(1.0, (d2 - d1) / (2 * center_in)))
    return 2 * center_in * math.cos(beta) + math.pi * (d1 + d2) / 2 + beta * (d2 - d1)


def chain_center(drive: Drive, t1: int, t2: int, links: int) -> float:
    """ANSI chain center distance from link count (inches)."""
    p, a, b = drive.pitch_in, min(t1, t2), max(t1, t2)
    x = 2 * links - a - b
    under = x * x - (8 / math.pi ** 2) * (b - a) ** 2
    if x <= 0 or under < 0:
        return float("nan")
    return p / 8 * (x + math.sqrt(under))


def chain_links(drive: Drive, t1: int, t2: int, center_in: float) -> float:
    p, a, b = drive.pitch_in, min(t1, t2), max(t1, t2)
    return 2 * center_in / p + (a + b) / 2 + (b - a) ** 2 * p / (4 * math.pi ** 2 * center_in)


def min_center(drive: Drive, t1: int, t2: int) -> float:
    """Pulleys/sprockets touching (pitch circles + a little room)."""
    return (pitch_diameter(drive, t1) + pitch_diameter(drive, t2)) / 2 + 0.1


def center_for(drive: Drive, t1: int, t2: int, count: int) -> float:
    """
    Center distance for a belt with `count` teeth or a chain with `count` links.
    NaN if it can't wrap both (too short).
    """
    if drive.kind == "chain":
        c = chain_center(drive, t1, t2, count)
        return c if c == c and c >= min_center(drive, t1, t2) - 0.1 else float("nan")
    target = count * drive.pitch_in
    lo, hi = min_center(drive, t1, t2) - 0.1, target / 2
    if hi <= lo or belt_length(drive, t1, t2, lo) > target:
        return float("nan")
    for _ in range(80):                      # bisection: belt length grows with center distance
        mid = (lo + hi) / 2
        if belt_length(drive, t1, t2, mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def count_for(drive: Drive, t1: int, t2: int, center_in: float) -> float:
    """Exact (fractional) belt teeth / chain links for a center distance."""
    if drive.kind == "chain":
        return chain_links(drive, t1, t2, center_in)
    return belt_length(drive, t1, t2, center_in) / drive.pitch_in


@dataclass
class DriveOption:
    count: int
    center_in: float
    delta_in: float        # center minus target


def options_near(drive: Drive, t1: int, t2: int, target_in: float, extra_in: float = 0.0,
                 n: int = 3) -> List[DriveOption]:
    """
    Real belts/chains closest to a target center distance: n shorter and n longer.
    Chain must have an even link count (no half-link). `extra_in` is the team's
    usual tweak added to every center (e.g. +0.003" so a belt isn't over-tight).
    """
    exact = count_for(drive, t1, t2, target_in)
    step = 2 if drive.kind == "chain" else 1
    base = int(math.floor(exact))
    if step == 2 and base % 2:
        base -= 1
    counts = [base - step * k for k in range(n - 1, -1, -1)] + [base + step * (k + 1) for k in range(n)]
    out = []
    for c in counts:
        if c <= 0:
            continue
        center = center_for(drive, t1, t2, c)
        if center == center:
            out.append(DriveOption(c, center + extra_in, center + extra_in - target_in))
    return out


def ratio(t1: int, t2: int) -> float:
    return t2 / t1
