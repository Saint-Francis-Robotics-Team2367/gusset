"""
fab_core.py - plans a fabrication export: which made part goes where, in what
format, with what file name. Plain Python, unit tested.

Process -> output (from the team's lab):
    X-Carve  (Easel)          -> SVG (or DXF) in  X-Carve/<material> <thickness>/
    Laser    (LightBurn)      -> SVG (or DXF) in  Laser/<material> <thickness>/
    3D Print (Bambu / Orca)   -> 3MF          in  3D Print/
    Lathe                     -> PDF sheet    in  Lathe/
    Mill                      -> skipped (programmed in Fusion CAM)
    Hand Tools / Outsourced / TBD -> skipped, listed in the cut list

Every export is logged as {part number: {date, process, file}} so the next BOM
can show "Ready to Cut" / "Ready to Print" for that part.
"""

from __future__ import annotations

import datetime
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from . import bom_core as bc
from . import naming_core as nc
from .flat_export import thickness_label

log = logging.getLogger("gusset.fab")

PROC_XCARVE, PROC_LASER, PROC_PRINT, PROC_LATHE, PROC_MILL = "X-Carve", "Laser", "3D Print", "Lathe", "Mill"
FLAT_PROCESSES = (PROC_XCARVE, PROC_LASER)

OUT_FLAT, OUT_PRINT, OUT_LATHE, OUT_SKIP = "flat", "print", "lathe", "skip"
EXPORT_PROCESSES = [PROC_XCARVE, PROC_LASER, PROC_PRINT, PROC_LATHE]   # the machines Fab Export makes files for

STATUS_READY_CUT = "Ready to Cut"
STATUS_READY_PRINT = "Ready to Print"

LOG_ATTR = "fab_log"        # Gusset attribute on an assembly's root component


@dataclass
class FabOptions:
    xcarve_format: str = "svg"
    laser_format: str = "svg"
    units: str = "in"
    only_new: bool = False
    # Which machines to export for (None = all). E.g. {"Lathe"} at the lathe.
    processes: Optional[Set[str]] = None
    # Parts the student unticked in the table (component keys).
    excluded: Set[str] = field(default_factory=set)


@dataclass
class FabItem:
    key: str
    part_number: str
    description: str
    qty: int
    process: str
    material: str
    output: str                      # flat | print | lathe | skip
    fmt: str = ""                    # svg | dxf | 3mf | pdf
    folder: str = ""                 # relative folder inside the export folder
    file_name: str = ""
    thickness_mm: Optional[float] = None
    status: str = ""                 # "" = will export; otherwise why it's skipped
    warnings: List[str] = field(default_factory=list)

    @property
    def rel_path(self) -> str:
        return f"{self.folder}/{self.file_name}" if self.folder else self.file_name

    @property
    def will_export(self) -> bool:
        return self.output != OUT_SKIP and not self.status


def base_name(part_number: str, description: str, qty: int) -> str:
    """'27-DRV-104 omni mounting plate - qty 2' (safe for every OS)."""
    head = " ".join(t for t in (part_number, description) if t) or "unnamed part"
    return nc.sanitize(f"{head} - qty {qty}")


def stock_folder(material: str, thickness_mm: Optional[float], units: str = "in") -> str:
    """'Aluminum 6061 1-4 in' -> folder per sheet of stock. ('/' isn't allowed in folder names.)"""
    mat = (material or "No material set").replace("Mixed (", "Mixed ").rstrip(")")
    return nc.sanitize(f"{mat} {thickness_label(thickness_mm, units)}")


def plan(rows: List[bc.BomRow], options: FabOptions, fab_log: Optional[Dict[str, dict]] = None) -> List[FabItem]:
    """One FabItem per MADE part in the BOM (flat rows: one per unique part, total qty)."""
    fab_log = fab_log or {}
    items: List[FabItem] = []
    for r in rows:
        if r.type != bc.TYPE_MADE:
            continue
        item = FabItem(key=r.key, part_number=r.part_number, description=r.description, qty=r.qty,
                       process=r.process, material=r.material, output=OUT_SKIP)
        if r.process in FLAT_PROCESSES:
            item.output = OUT_FLAT
            item.fmt = (options.xcarve_format if r.process == PROC_XCARVE else options.laser_format).lower()
            item.folder = r.process          # stock subfolder is added once thickness is known
        elif r.process == PROC_PRINT:
            item.output, item.fmt, item.folder = OUT_PRINT, "3mf", PROC_PRINT
        elif r.process == PROC_LATHE:
            item.output, item.fmt, item.folder = OUT_LATHE, "pdf", PROC_LATHE
        elif r.process == PROC_MILL:
            item.status = "Mill: programmed in Fusion CAM"
        elif r.process in (bc.PROCESS_TBD, ""):
            item.status = "no process yet - set it in Export BOM"
        else:
            item.status = f"{r.process}: nothing to export"
        if item.output != OUT_SKIP:
            if not r.part_number:
                item.warnings.append("no part number - run Name Parts")
            suffix = " (in)" if item.fmt == "dxf" and options.units == "in" else " (mm)" if item.fmt == "dxf" else ""
            item.file_name = base_name(r.part_number, r.description, r.qty) + suffix + "." + item.fmt
            if options.processes is not None and r.process not in options.processes:
                item.status = f"{r.process} not ticked"
            elif r.key in options.excluded:
                item.status = "unticked in the list"
            elif options.only_new and r.part_number and r.part_number in fab_log:
                item.status = f"already exported {fab_log[r.part_number].get('date', '')}".strip()
        items.append(item)
    log.info("Fab plan: %d made parts, %d to export", len(items), sum(1 for i in items if i.will_export))
    return items


def set_thickness(item: FabItem, thickness_mm: Optional[float], options: FabOptions) -> None:
    """Flat parts: put the file in a folder for its sheet of stock."""
    item.thickness_mm = thickness_mm
    if item.output == OUT_FLAT:
        item.folder = f"{item.process}/{stock_folder(item.material, thickness_mm, options.units)}"


# ---------------------------------------------------------------------------
# Export log (feeds the BOM's Build Status)
# ---------------------------------------------------------------------------
def parse_log(text: str) -> Dict[str, dict]:
    if not text:
        return {}
    try:
        data = json.loads(text)
        return {str(k): v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}
    except ValueError:
        log.warning("Ignoring an unreadable fab log")
        return {}


def merge_logs(*logs: Dict[str, dict]) -> Dict[str, dict]:
    """Combine logs from several assemblies; the newest entry per part wins."""
    merged: Dict[str, dict] = {}
    for one in logs:
        for pn, entry in one.items():
            if pn not in merged or str(entry.get("date", "")) >= str(merged[pn].get("date", "")):
                merged[pn] = entry
    return merged


def record(fab_log: Dict[str, dict], items: List[FabItem], when: Optional[str] = None) -> Dict[str, dict]:
    """Add exported items to a log (copy). Parts without a number can't be tracked."""
    out = dict(fab_log)
    stamp = when or datetime.date.today().isoformat()
    for item in items:
        if item.part_number:
            out[item.part_number] = {"date": stamp, "process": item.process, "file": item.rel_path}
    return out


def ready_status(process: str) -> str:
    return STATUS_READY_PRINT if process == PROC_PRINT else STATUS_READY_CUT


def cut_list_rows(items: List[FabItem]) -> List[List[object]]:
    rows: List[List[object]] = [["Part #", "Description", "Qty", "Process", "Material", "Thickness", "File", "Notes"]]
    order = {PROC_XCARVE: 0, PROC_LASER: 1, PROC_PRINT: 2, PROC_LATHE: 3}
    for i in sorted(items, key=lambda i: (order.get(i.process, 9), i.folder, i.part_number)):
        notes = "; ".join([i.status] + i.warnings) if i.status else "; ".join(i.warnings)
        rows.append([i.part_number, i.description, i.qty, i.process, i.material,
                     thickness_label(i.thickness_mm) if i.output == OUT_FLAT else "",
                     i.rel_path if i.will_export else "", notes])
    return rows


def selectable(item: FabItem) -> bool:
    """Can the student tick/untick this row? (It has a file to make, apart from being unticked.)"""
    return item.output != OUT_SKIP and (not item.status or item.status == "unticked in the list")


def default_output_for(process: str) -> str:
    """Export Part: which file to suggest for a part's process."""
    return {PROC_XCARVE: OUT_FLAT, PROC_LASER: OUT_FLAT, PROC_PRINT: OUT_PRINT, PROC_LATHE: OUT_LATHE}.get(process, OUT_PRINT)
