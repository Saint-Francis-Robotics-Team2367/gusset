"""
part_files_core.py - names and grouping for parts Gusset saves as their own files
(no Fusion imports; tested in tests/test_part_files_core.py).

The team's layout:

    <folder>/
        Intake Assembly                 <- the assembly
        Intake Assembly Parts/          <- every part the assembly links to
            Shaft 0.5in hex x 4.500in
            Spacer 0.75in OD x 0.490in

A part's FILE NAME says everything about its shape, so two identical spacers
map to the same name - Gusset then saves one file and inserts it twice, and a
matching file already in the Parts folder is simply reused.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Sequence

from . import frc_parts_core as pc

PARTS_SUFFIX = " Parts"
# Characters Fusion (and the operating systems it syncs to) don't allow in file names.
_BAD = re.compile(r'[\\/:*?"<>|]')


def parts_folder_name(assembly_name: str) -> str:
    return f"{assembly_name.strip()}{PARTS_SUFFIX}"


def safe_file_name(name: str) -> str:
    """Inch marks become 'in'; other characters Fusion won't take are dropped."""
    name = name.replace('"', "in")
    name = _BAD.sub("-", name)
    return re.sub(r"\s+", " ", name).strip()


def _num(x: float) -> str:
    return f"{x:.3f}in"


def shaft_file_name(plan: pc.ShaftPlan) -> str:
    """Every feature is in the name, so only truly identical shafts share a file."""
    name = f"Shaft 0.5in hex x {_num(plan.length_in)}" + (" tapped" if plan.tapped else "")
    if plan.round_start or plan.round_end:
        where = "ends" if plan.round_start and plan.round_end else ("start" if plan.round_start else "end")
        name += f" round {where} {plan.round_d_in:g}x{plan.round_len_in:g}"
    if plan.grooves_in:
        name += " grooves " + "-".join(f"{g:.3f}".rstrip("0").rstrip(".") for g in plan.grooves_in)
    return safe_file_name(name)


def spacer_file_name(plan: pc.SpacerPlan, material: str = "") -> str:
    """Material is part of the name: a PLA and an aluminum spacer of the same size are different parts."""
    name = f"Spacer {plan.od_in:g}in OD x {_num(plan.length_in)}"
    if material:
        name += f" {material}"
    default_bore = pc.HEX_FLATS_IN + pc.DEFAULT_SPACER_CLEARANCE_IN
    if abs(plan.bore_flats_in - default_bore) > 1e-6:
        name += f" bore {plan.bore_flats_in:.3f}"
    return safe_file_name(name)


WALL_TAGS = {0.0625: "1-16 wall", 0.100: "0.100 wall", 0.125: "1-8 wall"}


def tube_file_name(plan: pc.TubePlan) -> str:
    wall = WALL_TAGS.get(round(plan.wall_in, 4), f"{plan.wall_in:.3f} wall")
    name = f"Tube {plan.size} {wall} x {_num(plan.length_in)}"
    if plan.hole_d_in:
        rows = max(len(plan.rows_up_faces), len(plan.rows_side_faces))
        name += f" holes {plan.hole_d_in:.3f}" + (f" x{rows} rows" if rows > 1 else "")
    return safe_file_name(name)


def matches(existing: str, wanted: str) -> bool:
    """
    Is this existing file the part we want? Exact name, or the same name with a
    part number in front (after the Naming tool numbers it: '27-INT-104 Shaft ...').
    """
    e, w = existing.strip().lower(), wanted.strip().lower()
    return e == w or e.endswith(" " + w)


@dataclass
class Placement:
    """Where one copy goes: an origin and the part's X/Y/Z axes, in the target component (cm)."""
    origin: tuple
    x: tuple
    y: tuple
    z: tuple


@dataclass
class PartRequest:
    kind: str                         # "shaft", "spacer" or "tube"
    file_name: str
    plan: object                      # the pc.*Plan the part is built from
    extras: Dict[str, object] = field(default_factory=dict)
    placements: List[Placement] = field(default_factory=list)


def group_requests(requests: Sequence[PartRequest]) -> List[PartRequest]:
    """Identical parts (same file name) become one request with several placements."""
    merged: Dict[str, PartRequest] = {}
    order: List[str] = []
    for r in requests:
        key = r.file_name.lower()
        if key in merged:
            merged[key].placements.extend(r.placements)
        else:
            merged[key] = PartRequest(r.kind, r.file_name, r.plan, dict(r.extras), list(r.placements))
            order.append(key)
    return [merged[k] for k in order]
