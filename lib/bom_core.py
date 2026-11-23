"""
bom_core.py - builds the Bill of Materials from a CompNode tree.
Plain Python (no Fusion imports), so it's unit tested in tests/test_bom_core.py.

Two views of the same robot:
  flat     - one row per unique part with TOTAL quantity for the whole assembly
             (2 gearboxes x 4 standoffs = 8 standoffs). This is the monday.com
             tab: monday imports only the FIRST tab of an Excel file.
  indented - mirrors the assembly tree, quantity per parent. For build docs.

What's in and out:
  - team-made parts and assemblies: listed (with process, material, mass)
  - COTS parts: listed with vendor info, but NOT their insides
    (nobody needs the 2 sub-parts of a HiGrip wheel on an order list)
  - empty components: left out
"""

from __future__ import annotations

import logging
import re
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import naming_core as nc

log = logging.getLogger("gusset.bom")

KG_TO_LB = 2.2046226218
MAX_INDENTED_ROWS = 20000   # safety net for enormous robots

TYPE_ASSEMBLY = "Assembly"
TYPE_MADE = "Made"
TYPE_COTS = "COTS"

PROCESS_TBD = "TBD"

# A new body in Fusion is Steel until someone changes it, so a made part that's
# "Steel" usually means "material never set" (FRC parts are mostly aluminum/plastic).
FUSION_DEFAULT_MATERIAL = "Steel"
PROCESS_COTS = "COTS"

DEFAULT_PROCESSES: List[str] = ["X-Carve", "Laser", "3D Print", "Lathe", "Mill", "Hand Tools", "Outsourced", PROCESS_TBD]

# Starting label for monday's Build Status column (students update it in monday).
DEFAULT_STATUS = {TYPE_MADE: "Designed", TYPE_COTS: "To Order", TYPE_ASSEMBLY: "Not Started"}

# Vendor rules: (vendor name, regex that finds the vendor part number, link template or "").
# Links are SEARCH links, so they keep working when a vendor reorganizes its site.
DEFAULT_VENDORS: List[Tuple[str, str, str]] = [
    ("AndyMark", r"\b(am-\d{4}[a-z]?)\b", "https://www.andymark.com/search?q={pn}"),
    ("WCP", r"\b(WCP-\d{4})\b", "https://wcproducts.com/search?q={pn}"),
    ("REV Robotics", r"\b(REV-\d{2}-\d{4})\b", "https://www.revrobotics.com/search.php?search_query={pn}"),
    ("VEX", r"\b(217-\d{4})\b", "https://www.vexrobotics.com/catalogsearch/result/?q={pn}"),
    ("The Thrifty Bot", r"\b(TTB-?[A-Za-z0-9-]+)\b", "https://www.thethriftybot.com/search?q={pn}"),
    ("McMaster-Carr", r"\b(\d{4,5}[A-Z]\d{1,4})\b", "https://www.mcmaster.com/{pn}"),
    ("Hardware", r"(?i)\b(screw|bolt|nut|washer|rivet)\b", ""),
]


@dataclass
class VendorInfo:
    vendor: str = ""
    vendor_pn: str = ""
    link: str = ""


def vendor_info(name: str, part_number: str, vendors: List[Tuple[str, str, str]] = DEFAULT_VENDORS) -> VendorInfo:
    """Guess vendor, vendor part number and a search link from a COTS name."""
    for text in (part_number or "", name or ""):
        for vendor, pattern, link in vendors:
            try:
                match = re.search(pattern, text)
            except re.error:
                continue
            if not match:
                continue
            pn = match.group(1) if match.groups() else ""
            if vendor == "Hardware":
                return VendorInfo(vendor="Hardware", vendor_pn="", link="")
            return VendorInfo(vendor=vendor, vendor_pn=pn, link=link.replace("{pn}", pn) if link and pn else "")
    return VendorInfo()


@dataclass
class BomRow:
    key: str
    name: str                     # display name (Fusion suffixes removed)
    part_number: str              # team number, or vendor part number for COTS
    description: str
    type: str                     # Assembly | Made | COTS
    qty: int = 0                  # total in the whole assembly (flat) or per parent (indented)
    level: int = 0                # indented view only
    process: str = ""
    material: str = ""
    mass_lb: Optional[float] = None
    vendor: str = ""
    vendor_pn: str = ""
    link: str = ""
    unit_price: Optional[float] = None
    subsystem: str = ""
    used_in: str = ""
    status: str = ""
    notes: str = ""
    owner_file: str = ""          # where a process change must be saved ("" = open design)
    is_file_root: bool = False

    @property
    def total_mass_lb(self) -> Optional[float]:
        if self.mass_lb is None or self.type == TYPE_ASSEMBLY:
            return None
        return round(self.mass_lb * self.qty, 3)


@dataclass
class Bom:
    title: str
    flat: List[BomRow] = field(default_factory=list)
    indented: List[BomRow] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def parts_mass_lb(self) -> float:
        return round(sum(r.total_mass_lb or 0.0 for r in self.flat), 2)

    def counts(self) -> Dict[str, int]:
        return dict(Counter(r.type for r in self.flat))


def _row_type(node: nc.CompNode, cfg: nc.NamingConfig, is_top: bool) -> Optional[str]:
    kind, _reason = nc.classify(node, cfg, None, is_top=is_top)
    if kind == nc.KIND_COTS:
        return TYPE_COTS
    if kind == nc.KIND_ASSEMBLY:
        return TYPE_ASSEMBLY
    if kind == nc.KIND_PART:
        return TYPE_MADE
    return None   # empty component


def _base_row(node: nc.CompNode, row_type: str, cfg: nc.NamingConfig, top_sub: str,
              processes: Dict[str, str]) -> BomRow:
    display = nc.strip_fusion_suffixes(node.name)
    parsed = nc.existing_number(node.part_number, node.name)
    row = BomRow(key=node.key, name=display, part_number="", description="", type=row_type,
                 material=getattr(node, "material", "") or "",
                 mass_lb=(round(node.mass_kg * KG_TO_LB, 3) if getattr(node, "mass_kg", None) is not None else None),
                 owner_file=node.owner_file, is_file_root=bool(node.file_id) and node.file_id == node.owner_file)
    if row_type == TYPE_COTS:
        info = vendor_info(node.name, node.part_number)
        row.part_number = info.vendor_pn or nc.strip_fusion_suffixes(node.part_number or node.name)
        row.description = display
        row.vendor, row.vendor_pn, row.link = info.vendor, info.vendor_pn, info.link
        lib = getattr(node, "cots_info", None) or {}
        if lib:                                   # a COTS Library part: its stamped details win over guessing
            row.vendor = lib.get("cots_vendor") or row.vendor
            row.vendor_pn = lib.get("cots_pn") or row.vendor_pn
            row.part_number = row.vendor_pn or row.part_number
            row.description = lib.get("cots_name") or row.description
            row.link = lib.get("cots_url") or row.link
            try:
                row.unit_price = float(lib["cots_price"]) if lib.get("cots_price") else None
            except ValueError:
                row.unit_price = None
        row.process = PROCESS_COTS
        row.subsystem = top_sub
    else:
        row.part_number = nc.format_part_number(*parsed) if parsed else ""
        row.description = nc.best_description(node.name, node.part_number, cfg) or display
        row.subsystem = parsed[1] if parsed else top_sub
        if row_type == TYPE_MADE:
            row.process = processes.get(node.key) or getattr(node, "process", "") or PROCESS_TBD
        if not parsed:
            row.notes = "no team part number yet - run Name Parts"
        elif parsed[0] != cfg.season_year:
            row.notes = f"numbered for the 20{parsed[0]} season"
    row.status = DEFAULT_STATUS.get(row_type, "")
    return row


def build_bom(root: nc.CompNode, cfg: nc.NamingConfig, top_subsystem: str = "",
              processes: Optional[Dict[str, str]] = None, title: str = "",
              fab_log: Optional[Dict[str, dict]] = None) -> Bom:
    """
    Build both BOM views. `processes` = {component key: process} chosen in the
    dialog; it wins over the process saved on the part. `fab_log` = parts that
    Fab Export / Export Face already exported ({part number: {...}}): those
    start as "Ready to Cut" / "Ready to Print" instead of "Designed".
    """
    processes = processes or {}
    fab_log = fab_log or {}
    top_parsed = nc.existing_number(root.part_number, root.name)
    top_sub = top_subsystem or (top_parsed[1] if top_parsed else "")
    bom = Bom(title=title or nc.strip_fusion_suffixes(root.name))

    # --- 1. Classify every unique component once.
    types: Dict[str, Optional[str]] = {}
    nodes: Dict[str, nc.CompNode] = {}

    def classify_all(node: nc.CompNode, is_top: bool, depth: int) -> None:
        if node.key in types or depth > nc.MAX_DEPTH:
            return
        nodes[node.key] = node
        types[node.key] = _row_type(node, cfg, is_top)
        if types[node.key] == TYPE_COTS:
            return                                   # don't look inside bought parts
        for child in node.children:
            classify_all(child, False, depth + 1)

    classify_all(root, True, 0)

    # --- 2. Total quantities. Each entry in `children` is one placed copy, so
    #        counts multiply naturally through repeated sub-assemblies.
    memo: Dict[str, Counter] = {}

    def totals_under(node: nc.CompNode, depth: int) -> Counter:
        if node.key in memo:
            return memo[node.key]
        counts: Counter = Counter()
        if types.get(node.key) != TYPE_COTS and depth <= nc.MAX_DEPTH:
            for child in node.children:
                if types.get(child.key) is None:
                    continue
                counts[child.key] += 1
                counts.update(totals_under(child, depth + 1))
        memo[node.key] = counts
        return counts

    totals = totals_under(root, 0)
    totals[root.key] = 1

    # Which assemblies directly use each component ("Used In" column).
    used_in: Dict[str, "OrderedDict[str, None]"] = {}
    for parent in nodes.values():
        if types.get(parent.key) == TYPE_COTS:
            continue
        for child in parent.children:
            used_in.setdefault(child.key, OrderedDict())[nc.strip_fusion_suffixes(parent.name)] = None

    # --- 3. Flat view, in tree order (parents before children).
    seen = set()

    def flat_visit(node: nc.CompNode, is_top: bool, depth: int) -> None:
        if node.key in seen or depth > nc.MAX_DEPTH:
            return
        seen.add(node.key)
        row_type = types.get(node.key)
        if row_type is None:
            return
        row = _base_row(node, row_type, cfg, top_sub, processes)
        row.qty = totals.get(node.key, 0)
        if row_type == TYPE_MADE and row.part_number in fab_log:
            row.status = "Ready to Print" if row.process == "3D Print" else "Ready to Cut"
        parents = list(used_in.get(node.key, {}).keys())
        row.used_in = ", ".join(parents[:4]) + (f" (+{len(parents) - 4} more)" if len(parents) > 4 else "")
        bom.flat.append(row)
        if row_type != TYPE_COTS:
            for child in node.children:
                flat_visit(child, False, depth + 1)

    flat_visit(root, True, 0)

    # --- 4. Indented view: quantity per parent, repeated children merged.
    def indent_visit(node: nc.CompNode, qty: int, level: int) -> None:
        if len(bom.indented) >= MAX_INDENTED_ROWS:
            return
        row_type = types.get(node.key)
        if row_type is None:
            return
        row = _base_row(node, row_type, cfg, top_sub, processes)
        row.qty, row.level = qty, level
        bom.indented.append(row)
        if row_type == TYPE_COTS or level > nc.MAX_DEPTH:
            return
        per_parent: "OrderedDict[str, int]" = OrderedDict()
        by_key: Dict[str, nc.CompNode] = {}
        for child in node.children:
            per_parent[child.key] = per_parent.get(child.key, 0) + 1
            by_key[child.key] = child
        for key, count in per_parent.items():
            indent_visit(by_key[key], count, level + 1)

    indent_visit(root, 1, 0)
    if len(bom.indented) >= MAX_INDENTED_ROWS:
        bom.warnings.append(f"Indented tab stopped at {MAX_INDENTED_ROWS} rows")

    missing = sum(1 for r in bom.flat if r.notes.startswith("no team"))
    if missing:
        bom.warnings.append(f"{missing} part(s) have no team part number yet. Run Name Parts first "
                            "so monday can match them on re-import.")
    default_material = [r for r in bom.flat if r.type == TYPE_MADE and r.material == FUSION_DEFAULT_MATERIAL]
    for r in default_material:
        r.notes = "; ".join(n for n in (r.notes, "material is Fusion's default (Steel) - set the real one for accurate mass") if n)
    if default_material:
        bom.warnings.append(f"{len(default_material)} made part(s) still use Steel, Fusion's default material, "
                            "so their mass is probably wrong. Set materials with Modify > Physical Material.")
    tbd = sum(1 for r in bom.flat if r.type == TYPE_MADE and r.process == PROCESS_TBD)
    if tbd:
        bom.warnings.append(f"{tbd} made part(s) have no process yet (TBD)")
    log.info("BOM %r: %d flat rows %s, %d indented rows, parts mass %.2f lb",
             bom.title, len(bom.flat), bom.counts(), len(bom.indented), bom.parts_mass_lb())
    return bom


# ---------------------------------------------------------------------------
# Turning rows into spreadsheet tables
# ---------------------------------------------------------------------------
# The flat tab is shaped for monday.com: "Name" becomes the item name, "Part #"
# is the column to match on when re-importing (Set duplicate behavior > Update).
FLAT_COLUMNS = [
    ("Name", 38), ("Part #", 14), ("Description", 30), ("Qty", 6), ("Type", 10),
    ("Process", 12), ("Build Status", 13), ("Subsystem", 10), ("Material", 20),
    ("Mass Each (lb)", 13), ("Total Mass (lb)", 14), ("Vendor", 14), ("Vendor Part #", 14),
    ("Link", 40), ("Unit Price", 10), ("Used In", 32), ("Notes", 36),
]

INDENTED_COLUMNS = [
    ("Level", 6), ("Name", 44), ("Part #", 14), ("Qty", 6), ("Type", 10), ("Process", 12),
    ("Material", 20), ("Mass Each (lb)", 13), ("Vendor", 14), ("Vendor Part #", 14), ("Notes", 36),
]


def _item_name(row: BomRow) -> str:
    if row.type != TYPE_COTS and row.part_number and not row.name.startswith(row.part_number):
        return f"{row.part_number} {row.description}"
    return row.name


def flat_table(bom: Bom) -> List[List[object]]:
    table: List[List[object]] = [[c for c, _w in FLAT_COLUMNS]]
    for r in bom.flat:
        table.append([
            _item_name(r), r.part_number, r.description, r.qty, r.type, r.process, r.status,
            r.subsystem, r.material, r.mass_lb, r.total_mass_lb, r.vendor, r.vendor_pn,
            r.link, r.unit_price, r.used_in, r.notes,
        ])
    return table


def indented_table(bom: Bom) -> List[List[object]]:
    table: List[List[object]] = [[c for c, _w in INDENTED_COLUMNS]]
    for r in bom.indented:
        table.append([
            r.level, ("    " * r.level) + _item_name(r), r.part_number, r.qty, r.type, r.process,
            r.material, r.mass_lb, r.vendor, r.vendor_pn, r.notes,
        ])
    return table


# ---------------------------------------------------------------------------
# Shopping list (the "Shopping list" tab): COTS parts grouped by vendor
# ---------------------------------------------------------------------------
SHOPPING_COLUMNS = [("Vendor", 14), ("Qty", 6), ("Part #", 16), ("Description", 44), ("Store link", 34),
                    ("Unit Price", 11), ("Line Total", 11), ("Notes", 30)]
NO_VENDOR = "Vendor not known"


def shopping_list(bom: Bom) -> List[Tuple[str, List[BomRow]]]:
    """[(vendor, its COTS rows)] - vendors A-Z, 'Vendor not known' last, rows by part #."""
    groups: Dict[str, List[BomRow]] = {}
    for r in bom.flat:
        if r.type == TYPE_COTS and r.qty > 0:
            groups.setdefault(r.vendor or NO_VENDOR, []).append(r)
    order = sorted(groups, key=lambda v: (v == NO_VENDOR, v.lower()))
    return [(v, sorted(groups[v], key=lambda r: (r.vendor_pn or r.part_number or r.name).lower())) for v in order]


def shopping_table(bom: Bom, link=lambda url, text: url, bold=lambda v: v) -> List[List[object]]:
    """
    Rows for the tab. link/bold wrap cells for the Excel writer (xlsx_writer.Link /
    Bold); left as-is the table is plain values (tests, CSV).
    """
    table: List[List[object]] = [[c for c, _w in SHOPPING_COLUMNS]]
    grand, grand_missing = 0.0, 0
    for vendor, rows in shopping_list(bom):
        subtotal, missing = 0.0, 0
        for r in rows:
            line = round(r.unit_price * r.qty, 2) if r.unit_price is not None else None
            if line is None:
                missing += 1
            else:
                subtotal += line
            note = "no price in the library yet" if r.unit_price is None else ""
            if vendor == NO_VENDOR:
                note = "not from the COTS Library - find the vendor"
            table.append([vendor, r.qty, r.vendor_pn or r.part_number, r.description or r.name,
                          link(r.link, r.link) if r.link else "", r.unit_price, line, note])
        grand += subtotal
        grand_missing += missing
        table.append([bold(f"{vendor} subtotal"), bold(sum(r.qty for r in rows)), "", "", "", "",
                      bold(round(subtotal, 2)),
                      bold(f"+ {missing} part(s) with no price") if missing else ""])
        table.append([])
    if len(table) == 1:
        table.append(["", "", "", "No COTS parts in this assembly.", "", "", "", ""])
    else:
        table.append([bold("Total"), "", "", "", "", "", bold(round(grand, 2)),
                      bold(f"+ {grand_missing} part(s) with no price") if grand_missing else ""])
    return table
