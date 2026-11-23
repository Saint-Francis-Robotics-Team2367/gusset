"""
design_tree.py - turns Fusion's occurrence tree into plain CompNode objects
(which naming_core understands), and writes Gusset tags back onto components.

"Occurrence" vs "component" in Fusion:
  - a COMPONENT is the part definition (name, part number, bodies)
  - an OCCURRENCE is one placed copy of it in an assembly
  Four identical swerve modules = 1 component, 4 occurrences.
  Names and part numbers live on the component, so we key everything by component.

Linked ("external") components live in their own Fusion file. We can READ them
from the open assembly, but to CHANGE them we must open their file. So every
CompNode records:
  file_id    - set when the component is the root of a file (linked part, or the open file)
  owner_file - the file where the component is edited ("" = the open design)
"""

from __future__ import annotations

import time
from typing import Dict, Iterable, List, Optional, Set, Tuple

import adsk.core
import adsk.fusion

from . import log as gslog
from .naming_core import (MAX_DEPTH, CompNode, NamingConfig, cots_tag_applies, existing_number,
                          looks_like_cots, part_number_at_start, parse_part_number)

_log = gslog.get_logger("design_tree")

ATTR_GROUP = "Gusset"   # attribute group saved inside the Fusion design


PN_READ_BUDGET = 10.0   # seconds; see _read_part_number


class TreeContext:
    """Everything collected while reading the tree, needed later to apply changes."""

    def __init__(self, cfg: Optional[NamingConfig] = None) -> None:
        self.cfg = cfg
        self.components: Dict[str, object] = {}   # key -> Fusion Component (read-only if linked)
        self.files: Dict[str, object] = {}        # file id -> Fusion DataFile
        self.memo: Dict[str, CompNode] = {}
        self.tag_cache: Dict[str, Dict[str, str]] = {}   # file id -> tags (see file_jobs.TAG_CACHE_ATTR)
        self.pn_time = 0.0                        # time spent reading Part Numbers
        self.pn_reads = 0
        self.pn_skipped = 0


def _read_part_number(comp, name: str, ctx: TreeContext, cots_flag: Optional[bool], under_cots: bool,
                      file_name: str = "") -> str:
    """
    Reading Component.partNumber costs ~0.5 s EACH in Fusion (measured on a
    real gearbox), so a big robot could take minutes. We only read it when it
    matters:
      - inside a COTS part, or tagged COTS     -> never needed
      - name looks like a vendor part           -> not needed (it's COTS)
      - Gusset numbered it before               -> trust our fast "pn" tag
      - otherwise read it, until a time budget runs out, then fall back to the name
    """
    team_number = part_number_at_start(name)
    # A COTS=true tag only counts if the part has no team number (see cots_tag_applies).
    tagged_cots = cots_flag is True and ctx.cfg is not None and cots_tag_applies(cots_flag, name, "", ctx.cfg)
    if under_cots or tagged_cots:
        return ""
    # A linked part whose FILE name starts with a team number: that's its number.
    # (Name Parts' quick rename only renames the file, so the Part Number inside
    # may still be old - and this skips the slow partNumber read entirely.)
    file_number = part_number_at_start(file_name) if file_name else ""
    if file_number:
        return file_number
    tagged = _safe(lambda: comp.attributes.itemByName(ATTR_GROUP, "pn"), None)
    tagged_pn = str(tagged.value) if tagged else ""
    if tagged_pn and team_number == tagged_pn:
        return tagged_pn
    if ctx.cfg is not None and cots_flag is None and looks_like_cots(name, "", ctx.cfg):
        return ""
    if ctx.pn_time > PN_READ_BUDGET:
        ctx.pn_skipped += 1
        return team_number or ""
    started = time.time()
    value = _safe(lambda: comp.partNumber, "")
    ctx.pn_time += time.time() - started
    ctx.pn_reads += 1
    return value


def component_key(comp) -> str:
    """A stable id for a component, so we can find it again after the preview."""
    for getter in (lambda c: c.id, lambda c: c.entityToken):
        try:
            key = getter(comp)
            if key:
                return str(key)
        except Exception:
            continue
    _log.warning("Component %r has no id; using a temporary key", getattr(comp, "name", "?"))
    return f"tmp-{id(comp)}"


def _safe(getter, default):
    try:
        value = getter()
        return default if value is None else value
    except Exception:
        return default


COTS_INFO_KEYS = ("cots_name", "cots_vendor", "cots_pn", "cots_price", "cots_url", "cots_category")


def read_cots_info(comp) -> Dict[str, str]:
    """Details stamped inside a COTS Library part (empty for everything else)."""
    out: Dict[str, str] = {}
    for key in COTS_INFO_KEYS:
        attr = _safe(lambda k=key: comp.attributes.itemByName(ATTR_GROUP, k), None)
        if attr is not None and attr.value:
            out[key] = attr.value
    return out


def read_cots_flag(comp) -> Optional[bool]:
    attr = _safe(lambda: comp.attributes.itemByName(ATTR_GROUP, "cots"), None)
    if not attr:
        return None
    return str(attr.value).strip().lower() == "true"


def read_flag_attr(comp, name: str) -> bool:
    attr = _safe(lambda: comp.attributes.itemByName(ATTR_GROUP, name), None)
    return bool(attr) and str(attr.value).strip().lower() == "true"


def write_attr(comp, name: str, value: str) -> None:
    """Save a small tag inside the design (attributes.add overwrites existing)."""
    comp.attributes.add(ATTR_GROUP, name, value)


def linked_data_file(occ):
    """
    The DataFile behind a linked occurrence, or None.
    occ.documentReference only works for links made directly in the OPEN file.
    For a link nested inside another linked file (a standoff inside a linked
    gearbox) Fusion raises "Cannot get allDocumentReferences of a non-top-level
    document", so we fall back to the component's own design, which knows its
    file (checked on a real minibot: same file ids either way).
    """
    data_file = _safe(lambda: occ.documentReference.dataFile, None)
    if data_file is None:
        data_file = _safe(lambda: occ.component.parentDesign.parentDocument.dataFile, None)
    return data_file


def owner_of_occurrence(occ, ctx: TreeContext) -> str:
    """Which file a selected occurrence's component is edited in ("" = the open design)."""
    chain = []
    current = occ
    while current is not None:
        chain.append(current)
        current = _safe(lambda c=current: c.assemblyContext, None)
    for item in chain:  # nearest linked ancestor (or itself) owns it
        if _safe(lambda i=item: i.isReferencedComponent, False):
            data_file = linked_data_file(item)
            if data_file:
                ctx.files[data_file.id] = data_file
                return data_file.id
    return ""


def node_from_occurrence(occ, ctx: TreeContext, owner_file: str = "", depth: int = 0,
                         under_cots: bool = False) -> CompNode:
    """Build a CompNode tree under one occurrence (memoized by component)."""
    comp = occ.component
    key = component_key(comp)
    ctx.components.setdefault(key, comp)
    if key in ctx.memo:
        return ctx.memo[key]

    is_external = bool(_safe(lambda: occ.isReferencedComponent, False))
    file_id, file_name = "", ""
    if is_external:
        data_file = linked_data_file(occ)
        if data_file:
            file_id, file_name = data_file.id, _safe(lambda: data_file.name, "")
            ctx.files[file_id] = data_file
            owner_file = file_id          # a linked component is edited in its own file
        else:
            _log.warning("Linked component %r has no file (broken link?)", comp.name)

    name = _safe(lambda: comp.name, "")
    cots_flag = read_cots_flag(comp)
    node = CompNode(
        key=key,
        name=name,
        part_number=_read_part_number(comp, name, ctx, cots_flag, under_cots, file_name),
        has_bodies=(_safe(lambda: comp.bRepBodies.count, 0) + _safe(lambda: comp.meshBodies.count, 0)) > 0,
        is_external=is_external,
        cots_flag=cots_flag,
        cots_info=read_cots_info(comp) if cots_flag else {},
        standalone=read_flag_attr(comp, "top"),
        file_id=file_id,
        file_name=file_name,
        owner_file=owner_file,
    )
    ctx.memo[key] = node  # store before recursing: protects against loops

    if depth >= MAX_DEPTH:
        _log.warning("Design nested deeper than %d levels at %r; stopping there", MAX_DEPTH, node.name)
        return node

    # Walk into linked files too: their parts get numbered with the rest.
    if ctx.cfg is None:
        looks_cots = cots_flag is True
    elif cots_flag is not None:
        looks_cots = bool(cots_flag) and cots_tag_applies(cots_flag, name, node.part_number, ctx.cfg)
    else:
        looks_cots = looks_like_cots(name, "", ctx.cfg)
    children = occ.childOccurrences
    for i in range(children.count):
        node.children.append(node_from_occurrence(children.item(i), ctx, owner_file, depth + 1,
                                                  under_cots or looks_cots))
    return node


def root_node(design, ctx: TreeContext) -> CompNode:
    """The open file's top assembly (the root component) as a CompNode."""
    root = design.rootComponent
    key = component_key(root)
    ctx.components[key] = root
    data_file = _safe(lambda: design.parentDocument.dataFile, None)
    file_id = data_file.id if data_file else ""
    if data_file:
        ctx.files[file_id] = data_file
    started = time.time()
    name = _safe(lambda: root.name, "")
    node = CompNode(
        key=key,
        name=name,
        part_number=_read_part_number(root, name, ctx, None, False),
        has_bodies=_safe(lambda: root.bRepBodies.count, 0) > 0,
        cots_flag=read_cots_flag(root),
        file_id=file_id,
        file_name=_safe(lambda: data_file.name, "") if data_file else "",
        owner_file="",
    )
    ctx.memo[key] = node
    for i in range(root.occurrences.count):
        node.children.append(node_from_occurrence(root.occurrences.item(i), ctx))
    _apply_tag_cache(node, ctx)
    _log.info("Read %r in %.1fs: %d unique components, %d files, %d Part Number reads (%.1fs)%s",
              node.name, time.time() - started, len(ctx.memo), len(ctx.files), ctx.pn_reads, ctx.pn_time,
              f", {ctx.pn_skipped} skipped to save time" if ctx.pn_skipped else "")
    return node


def _apply_tag_cache(root: CompNode, ctx: TreeContext) -> None:
    """
    Fusion hides add-in tags of parts linked 2+ levels deep. Read the copies
    Gusset keeps on assemblies (the open one + linked ones we CAN see) and use
    them for linked parts whose own tags came back empty.
    """
    import json
    from .file_jobs import TAG_CACHE_ATTR, merge_cache
    cache: Dict[str, Dict[str, str]] = {}
    for node in flatten([root]):
        if node is not root and not node.children:
            continue
        comp = ctx.components.get(node.key)
        text = read_text_attr(comp, TAG_CACHE_ATTR) if comp is not None else ""
        if text:
            try:
                cache = merge_cache(cache, json.loads(text))
            except ValueError:
                _log.warning("Ignoring an unreadable tag cache on %r", node.name)
    ctx.tag_cache = cache
    used = 0
    for node in flatten([root]):
        tags = cache.get(node.file_id) if node.is_external and node.file_id else None
        if not tags:
            continue
        if node.cots_flag is None and "cots" in tags:
            node.cots_flag = str(tags["cots"]).lower() == "true"
        if not node.standalone and str(tags.get("top", "")).lower() == "true":
            node.standalone = True
        used += 1
    if cache:
        _log.info("Tag cache: %d file(s) known, used for %d linked part(s)", len(cache), used)


def cached_tag(node: CompNode, ctx: TreeContext, name: str) -> str:
    tags = ctx.tag_cache.get(node.file_id) if node.file_id else None
    return str(tags.get(name, "")) if tags else ""


def fill_parent_files(nodes: Iterable[CompNode], ctx: TreeContext, cfg: NamingConfig) -> None:
    """
    For linked TEAM parts, ask Fusion which other files link them. That's how
    we spot a part shared with another subsystem. Skipped for COTS-looking
    parts to save time (each lookup is a cloud call).
    """
    started, looked_up = time.time(), 0
    for node in flatten(nodes):
        if not node.is_external or not node.file_id or node.parent_files:
            continue
        if node.cots_flag or looks_like_cots(node.name, node.part_number, cfg):
            continue
        data_file = ctx.files.get(node.file_id)
        parents = _safe(lambda: data_file.parentReferences, None) if data_file else None
        if parents is None:
            continue
        for i in range(_safe(lambda: parents.count, 0)):
            parent = parents.item(i)
            node.parent_files.append((_safe(lambda: parent.id, ""), _safe(lambda: parent.name, "")))
        looked_up += 1
        _log.debug("%r is linked by: %s", node.name, [n for _, n in node.parent_files])
    _log.info("Looked up where %d linked file(s) are used (%.1fs)", looked_up, time.time() - started)


MASS_READ_BUDGET = 30.0   # seconds; mass is computed by Fusion and can be slow


def read_text_attr(comp, name: str) -> str:
    attr = _safe(lambda: comp.attributes.itemByName(ATTR_GROUP, name), None)
    return str(attr.value) if attr else ""


def _material_of(comp) -> str:
    """Physical material of the component's bodies ("Mixed" if they differ)."""
    names = []
    bodies = _safe(lambda: comp.bRepBodies, None)
    for i in range(_safe(lambda: bodies.count, 0)):
        body = bodies.item(i)
        name = _safe(lambda b=body: b.material.name, "")
        if name and name not in names:
            names.append(name)
    if not names:
        return _safe(lambda: comp.material.name, "")
    return names[0] if len(names) == 1 else "Mixed (" + ", ".join(names[:3]) + ")"


def _mass_kg(comp) -> Optional[float]:
    """Mass in kg using Fusion's fast (low accuracy) calculation; plenty for a BOM."""
    try:
        props = comp.getPhysicalProperties(adsk.fusion.CalculationAccuracy.LowCalculationAccuracy)
    except Exception:
        props = _safe(lambda: comp.physicalProperties, None)
    mass = _safe(lambda: props.mass, None) if props else None
    return float(mass) if mass is not None else None


def fill_bom_info(root: CompNode, ctx: TreeContext, cfg: NamingConfig,
                  budget: float = MASS_READ_BUDGET) -> Dict[str, int]:
    """
    Add material, mass and saved process to every PART (made or COTS) in the
    tree. Assemblies are skipped (their mass would double count), and so are
    the insides of COTS parts. Mass reads stop after `budget` seconds.
    Returns counts for logging.
    """
    started = time.time()
    stats = {"parts": 0, "mass": 0, "mass_skipped": 0}
    seen: Set[str] = set()

    def visit(node: CompNode, under_cots: bool, depth: int) -> None:
        if node.key in seen or depth > MAX_DEPTH:
            return
        seen.add(node.key)
        comp = ctx.components.get(node.key)
        if node.cots_flag is not None:   # a stale COTS tag on a team-numbered part doesn't count
            tagged = cots_tag_applies(node.cots_flag, node.name, node.part_number, cfg) and bool(node.cots_flag)
        else:
            tagged = looks_like_cots(node.name, node.part_number, cfg)
        is_cots = under_cots or tagged
        if comp is not None and not under_cots:
            node.process = read_text_attr(comp, "process") or cached_tag(node, ctx, "process")
            # Parts get material + mass. A COTS part counts as one piece even when
            # its bodies live in sub-components (like a wheel's hub and tread).
            if (node.has_bodies and not node.children) or (is_cots and (node.has_bodies or node.children)):
                stats["parts"] += 1
                node.material = _material_of(comp)
                if time.time() - started < budget:
                    node.mass_kg = _mass_kg(comp)
                    stats["mass"] += 1
                else:
                    stats["mass_skipped"] += 1
        if is_cots:
            return
        for child in node.children:
            visit(child, under_cots, depth + 1)

    visit(root, False, 0)
    _log.info("BOM info: %d parts, %d masses read, %d skipped to save time (%.1fs)",
              stats["parts"], stats["mass"], stats["mass_skipped"], time.time() - started)
    return stats


def flatten(nodes: Iterable[CompNode]) -> List[CompNode]:
    """Every unique component in the trees, parents before children."""
    out: List[CompNode] = []
    seen: Set[str] = set()

    def visit(node: CompNode, depth: int) -> None:
        if node.key in seen or depth > MAX_DEPTH:
            return
        seen.add(node.key)
        out.append(node)
        for child in node.children:
            visit(child, depth + 1)

    for node in nodes:
        visit(node, 0)
    return out


def numbers_in_use(nodes: Iterable[CompNode], exclude_keys: Set[str], season_year: str) -> Dict[str, Set[int]]:
    """{subsystem: numbers} already taken this season by components outside the selection."""
    used: Dict[str, Set[int]] = {}
    for node in flatten(nodes):
        if node.key in exclude_keys:
            continue
        parsed = existing_number(node.part_number, node.name)
        if parsed and parsed[0] == season_year:
            used.setdefault(parsed[1], set()).add(parsed[2])
    return used


# Project scans are slow (~14 s for 44 files, measured), so results are kept
# for a while and updated with Gusset's own renames. Key: (project id, season).
PROJECT_CACHE_SECONDS = 60 * 60      # Gusset's own renames keep the cache current (note_file_renamed)
_project_cache: Dict[Tuple[str, str], Tuple[float, Dict[str, Tuple[str, int]]]] = {}
_scan_running = False


def note_file_renamed(file_id: str, new_name: str) -> None:
    """Keep cached project scans up to date after Gusset renames a file."""
    parsed = parse_part_number(part_number_at_start(new_name))
    for (_scope, season), (_stamp, data) in _project_cache.items():
        if parsed and parsed[0] == season:
            data[file_id] = (parsed[1], parsed[2])
        else:
            data.pop(file_id, None)


def scan_root_folder(data_file, scope: str = "season folder"):
    """
    Where to look for numbers already used:
      "season folder" (default) - the top-level folder (just under the project)
          that holds this file, e.g. 'FRC Design Library > 2027 Robot'. Much faster
          than the whole project, which can hold years of old robots and seminars.
      "project" - every folder in the project (slow on big projects).
    Returns (folder, label).
    """
    project = _safe(lambda: data_file.parentProject, None)
    folder = _safe(lambda: data_file.parentFolder, None)
    if scope == "project" or folder is None:
        root = _safe(lambda: project.rootFolder, None)
        return root, f"project '{_safe(lambda: project.name, '?')}'"
    while True:
        parent = _safe(lambda f=folder: f.parentFolder, None)
        if parent is None or _safe(lambda: folder.isRoot, False) or _safe(lambda p=parent: p.isRoot, True):
            break
        folder = parent
    return folder, f"folder '{_safe(lambda: folder.name, '?')}'"


def scan_project_numbers(design, season_year: str, max_files: int = 4000, time_limit: float = 20.0,
                         scope: str = "season folder") -> Dict[str, Tuple[str, int]]:
    """
    {file id: (subsystem, number)} for every FILE NAME under the scan folder (see
    scan_root_folder) that starts with a part number for this season. This keeps
    numbers unique across separate part files. (The caller drops files that are
    part of the current run, since those are being renumbered anyway.)

    Speed notes (v0.8.3): this used to walk the WHOLE project and call
    adsk.doEvents() between folders. On a big project that took 25-100 s, and
    doEvents let other Gusset events run mid-scan (a closing dialog cleared the
    new dialog's state -> "KeyError: 'design'"). Now: one season folder, no
    doEvents, one scan at a time, cached for an hour.
    """
    global _scan_running
    used: Dict[str, Tuple[str, int]] = {}
    data_file = _safe(lambda: design.parentDocument.dataFile, None)
    if not data_file:
        _log.info("Design isn't saved yet; skipping the project scan")
        return used
    folder, label = scan_root_folder(data_file, scope)
    if folder is None:
        return used
    cache_key = (f"{_safe(lambda: folder.id, '?')}|{scope}", season_year)
    cached = _project_cache.get(cache_key)
    if cached and time.time() - cached[0] < PROJECT_CACHE_SECONDS:
        _log.info("Using the %s scan from %.0f min ago (%d numbered files)", label,
                  (time.time() - cached[0]) / 60, len(cached[1]))
        return cached[1]
    if _scan_running:
        _log.warning("A number scan is already running; skipping a second one")
        return used
    _scan_running = True
    started, seen_files, seen_folders = time.time(), 0, 0
    try:
        folders = [folder]
        while folders:
            if time.time() - started > time_limit or seen_files >= max_files:
                _log.warning("Number scan of %s stopped early after %d files in %d folders (%.0fs); numbers "
                             "may repeat with files it didn't reach", label, seen_files, seen_folders,
                             time.time() - started)
                break
            current = folders.pop()
            seen_folders += 1
            for item in _safe(lambda: current.dataFiles.asArray(), []):
                seen_files += 1
                parsed = parse_part_number(part_number_at_start(_safe(lambda i=item: i.name, "")))
                if parsed and parsed[0] == season_year:
                    used[_safe(lambda i=item: i.id, f"?{seen_files}")] = (parsed[1], parsed[2])
            subs = _safe(lambda: current.dataFolders.asArray(), None)
            if subs is None:
                sub_folders = _safe(lambda: current.dataFolders, None)
                subs = [sub_folders.item(i) for i in range(_safe(lambda: sub_folders.count, 0))]
            folders.extend(subs)
    finally:
        _scan_running = False
    _log.info("Scanned %s: %d files in %d folders (%.1fs), %d already numbered for 20%s",
              label, seen_files, seen_folders, time.time() - started, len(used), season_year)
    _project_cache[cache_key] = (time.time(), used)
    return used


def merge_used(*sources: Dict[str, Set[int]]) -> Dict[str, Set[int]]:
    merged: Dict[str, Set[int]] = {}
    for source in sources:
        for code, numbers in source.items():
            merged.setdefault(code, set()).update(numbers)
    return merged


def find_component(design, key: str, fallback_name: str):
    """Find a component in a (possibly different) open design by id, then by name."""
    all_comps = design.allComponents
    try:
        comp = all_comps.itemById(key)
        if comp:
            return comp
    except Exception:
        pass
    for i in range(all_comps.count):
        comp = all_comps.item(i)
        if _safe(lambda c=comp: c.id, "") == key:
            return comp
    for i in range(all_comps.count):
        comp = all_comps.item(i)
        if _safe(lambda c=comp: c.name, "") == fallback_name:
            _log.warning("Matched %r by name (id not found)", fallback_name)
            return comp
    return None


def read_fab_logs(root: CompNode, ctx: TreeContext) -> Dict[str, dict]:
    """
    Export logs saved by Fab Export / Export Face on assembly root components
    (the open file and any linked sub-assemblies). {part number: {date, ...}}
    """
    from .fab_core import LOG_ATTR, merge_logs, parse_log
    logs = []
    for node in flatten([root]):
        if node is not root and not node.children:
            continue
        comp = ctx.components.get(node.key)
        text = read_text_attr(comp, LOG_ATTR) if comp is not None else ""
        if text:
            logs.append(parse_log(text))
    merged = merge_logs(*logs)
    _log.debug("Fab logs: %d assemblies, %d parts exported", len(logs), len(merged))
    return merged
