"""
frc_features.py - the numbers behind Gusset's Hole Pattern and Bearing Pocket
tools. Plain Python, unit tested. All sizes in INCHES (FRC's native unit).

Hole sizes come from a standard inch drill chart (UPenn MEAM lab):
    thread    tap (75%)        close clearance   free clearance
    10-32     #21  0.1590"     #9  0.1960"        #7  0.2010"
    1/4-20    #7   0.2010"     F   0.2570"        H   0.2660"
  - Clearance (free): the bolt slides through easily. Best for most joints.
  - Close: a snug fit, less wiggle; good for locating parts.
  - Tap: the hole is threaded afterwards, so a bolt screws straight into it.

Bearings: a starter table using SHIELDED (ZZ) sizes. Vendors differ slightly
(one lists the FR8 flange as 1.225", another 1.250"), so the table can be
edited in gusset_config.json. Only the OD and width matter for the pocket.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("gusset.features")

GRID_PITCH_IN = 0.5          # FRC's standard hole spacing (box tube, plates)
FIRST_FROM_END_IN = 0.25     # first hole 1/4" from the end, so the grid lands on 0.5" multiples
EDGE_MARGIN_IN = 0.04        # minimum material between a hole and the face edge


@dataclass(frozen=True)
class HoleSize:
    screw: str
    thread: str
    fit: str
    diameter_in: float
    drill: str

    @property
    def label(self) -> str:
        return f'{self.thread} {self.fit.lower()}: {self.drill} drill ({self.diameter_in:.4f}")'


# screw -> fit -> (diameter, drill name)
HOLE_TABLE: Dict[str, Dict[str, Tuple[float, str]]] = {
    "#10": {"Clearance": (0.2010, "#7"), "Close": (0.1960, "#9"), "Tap": (0.1590, "#21")},
    '1/4"': {"Clearance": (0.2660, "H"), "Close": (0.2570, "F"), "Tap": (0.2010, "#7")},
}
THREADS = {"#10": "10-32", '1/4"': "1/4-20"}
FITS = ["Clearance", "Close", "Tap"]
FIT_HELP = {
    "Clearance": "bolt slides through easily (most joints)",
    "Close": "snug fit with less wiggle (locating parts)",
    "Tap": "you'll thread this hole so a bolt screws into it",
}


def hole_size(screw: str, fit: str) -> HoleSize:
    if screw not in HOLE_TABLE or fit not in HOLE_TABLE[screw]:
        raise ValueError(f"unknown screw/fit {screw!r}/{fit!r}")
    diameter, drill = HOLE_TABLE[screw][fit]
    return HoleSize(screw, THREADS[screw], fit, diameter, drill)


# ---------------------------------------------------------------------------
# Hole grid
# ---------------------------------------------------------------------------
LAYOUT_ROW = "row"           # one row down the middle of the long direction
LAYOUT_GRID = "grid"         # fill the face on a 0.5" grid
START_END = "end"            # first hole 0.25" from the end
START_CENTER = "center"      # grid centered on the face


def _axis_positions(length: float, hole_d: float, start: str, pitch: float, first: float) -> List[float]:
    lo, hi = hole_d / 2 + EDGE_MARGIN_IN, length - hole_d / 2 - EDGE_MARGIN_IN
    if hi < lo - 1e-9:
        return []
    if start == START_CENTER:
        mid = length / 2
        k = math.floor((mid - lo) / pitch + 1e-9)
        positions = [mid + i * pitch for i in range(-k, k + 1)]
    else:
        positions = [first + i * pitch for i in range(int((length - first) / pitch) + 2)]
    return [p for p in positions if lo - 1e-9 <= p <= hi + 1e-9]


def grid_positions(length_in: float, width_in: float, hole_d_in: float, layout: str = LAYOUT_ROW,
                   start: str = START_END, pitch: float = GRID_PITCH_IN,
                   first_from_end: float = FIRST_FROM_END_IN) -> List[Tuple[float, float]]:
    """
    Hole centers on a rectangle `length` (long direction, x) by `width` (y),
    measured from its lower-left corner, in inches.
      row  -> one row centered across the width
      grid -> rows every `pitch` across the width too (centered)
    """
    xs = _axis_positions(length_in, hole_d_in, start, pitch, first_from_end)
    if layout == LAYOUT_GRID:
        ys = _axis_positions(width_in, hole_d_in, START_CENTER, pitch, first_from_end)
    else:
        ys = [width_in / 2] if width_in >= hole_d_in + 2 * EDGE_MARGIN_IN else []
    holes = [(x, y) for y in ys for x in xs]
    log.debug("Grid %.3fx%.3f in, d=%.4f, %s/%s -> %d holes", length_in, width_in, hole_d_in, layout, start, len(holes))
    return holes


# ---------------------------------------------------------------------------
# Bearings
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Bearing:
    name: str
    bore_in: float
    od_in: float
    width_in: float
    flange_od_in: float = 0.0
    flange_thk_in: float = 0.0

    @property
    def flanged(self) -> bool:
        return self.flange_od_in > self.od_in


DEFAULT_BEARINGS: List[Bearing] = [
    Bearing('FR8ZZ flanged, 1/2" round bore', 0.500, 1.125, 0.3125, 1.225, 0.062),
    Bearing('FR8ZZ-size flanged, 1/2" hex bore (am-2986)', 0.500, 1.125, 0.3125, 1.225, 0.062),
    Bearing('R8ZZ (no flange), 1/2" round bore', 0.500, 1.125, 0.3125),
    Bearing('FR6ZZ flanged, 3/8" round bore', 0.375, 0.875, 0.281, 0.969, 0.062),
    Bearing('R6ZZ (no flange), 3/8" round bore', 0.375, 0.875, 0.281),
]

# fit name -> (change to the bearing OD in inches, explanation)
DEFAULT_FITS: Dict[str, Tuple[float, str]] = {
    "Press": (-0.0005, "tight: tap the bearing in with a mallet (metal plates)"),
    "Snug": (0.0, "exact size: pushes in by hand, stays put"),
    "Slip": (0.002, "loose: drops in, held by the flange or a retainer"),
    "3D print": (0.008, "extra room because printed holes come out small"),
}

POCKET_THROUGH = "through"   # hole all the way through at the bearing OD (flange rests on the plate)
POCKET_BLIND = "blind"       # bearing-width-deep pocket + a smaller through hole for the shaft
SHAFT_CLEARANCE_IN = 0.0625  # shaft hole = bearing bore + 1/16" (clears hex corners, too)


def bearing_from_dict(d: dict) -> Optional[Bearing]:
    try:
        return Bearing(str(d["name"]), float(d["bore_in"]), float(d["od_in"]), float(d["width_in"]),
                       float(d.get("flange_od_in", 0) or 0), float(d.get("flange_thk_in", 0) or 0))
    except (KeyError, TypeError, ValueError) as exc:
        log.warning("Skipping a bearing in settings (%s): %r", exc, d)
        return None


def bearing_to_dict(b: Bearing) -> dict:
    return {"name": b.name, "bore_in": b.bore_in, "od_in": b.od_in, "width_in": b.width_in,
            "flange_od_in": b.flange_od_in, "flange_thk_in": b.flange_thk_in}


@dataclass
class PocketPlan:
    pocket_d_in: float
    pocket_depth_in: Optional[float]     # None = through
    shaft_d_in: Optional[float]          # only for blind pockets
    notes: List[str]
    blocked: str = ""                    # set = this can't work; explain why instead of cutting


def plan_pocket(bearing: Bearing, fit: str, kind: str, plate_thk_in: Optional[float],
                fits: Optional[Dict[str, Tuple[float, str]]] = None) -> PocketPlan:
    fits = fits or DEFAULT_FITS
    allowance = fits.get(fit, (0.0, ""))[0]
    pocket_d = round(bearing.od_in + allowance, 4)
    notes: List[str] = []
    if kind == POCKET_THROUGH:
        if not bearing.flanged:
            notes.append("this bearing has no flange, so a through hole won't stop it - use a pocket or a retainer")
        if plate_thk_in is not None and plate_thk_in < bearing.width_in - 0.01:
            notes.append(f'plate ({plate_thk_in:.3f}") is thinner than the bearing ({bearing.width_in:.3f}") - '
                         "it will stick out the far side")
        return PocketPlan(pocket_d, None, None, notes)
    depth = bearing.width_in - (bearing.flange_thk_in if bearing.flanged else 0.0)
    shaft = round(bearing.bore_in + SHAFT_CLEARANCE_IN, 4)
    blocked = ""
    if plate_thk_in is not None and depth >= plate_thk_in - 0.03:
        # Seen in real testing: an FR8ZZ pocket (0.2505") in a 1/4" plate cut straight through,
        # leaving nothing for the shaft hole. Refuse and explain instead.
        blocked = (f'The pocket would be {depth:.3f}" deep but the plate is only {plate_thk_in:.3f}" thick, so it would '
                   f'cut straight through. Use "Through hole" instead (the flange holds the bearing), '
                   f'or a plate at least {depth + 0.06:.3f}" thick.')
    return PocketPlan(pocket_d, round(depth, 4), shaft, notes, blocked)
