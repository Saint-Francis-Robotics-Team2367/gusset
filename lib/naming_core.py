"""
naming_core.py - the "brain" of the Gusset naming tools.

IMPORTANT: this file has NO Fusion imports on purpose. That means we can run
its unit tests on any computer with plain Python (see tests/), without Fusion
open. The Fusion commands turn the design tree into CompNode objects, ask this
module for a plan, show the plan to the student, and only then apply it.

Part number scheme:  YY-SUB-NNN        example: 27-ELV-104
    YY  = season year (the 2027 season -> "27")
    SUB = subsystem code from the settings file (ELV, DRV, INT, ...)
    NNN = 3-digit number.
          Assemblies own a "hundreds block":
              27-ELV-100  -> an assembly
              27-ELV-101 .. 27-ELV-199 -> the parts directly inside it
              27-ELV-200  -> the next assembly (a sub-assembly, for example)

Shared parts: a team part (or sub-assembly) that is also used by ANOTHER
subsystem gets a number in the shared block instead (default code MSC):
              27-MSC-101  -> a standoff used in both the drivetrain and intake

COTS parts (bought, not made) keep their vendor numbers and are never renumbered.

Linked parts (separate Fusion files, the team's normal workflow) are numbered
just like local components; the Fusion side renames their FILES later.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple, Union

log = logging.getLogger("gusset.naming")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BLOCK = 100          # size of each assembly's number block (100, 200, ... 900)
MAX_NUMBER = 999     # NNN is three digits
MAX_DEPTH = 40       # safety net against runaway recursion in weird designs

KIND_ASSEMBLY = "assembly"   # has sub-components -> gets an XX00 number
KIND_PART = "part"           # has bodies, no sub-components -> gets XX01..XX99
KIND_COTS = "cots"           # bought part -> keeps vendor number
KIND_SKIP = "skip"           # empty component, or something inside a COTS part

STATUS_OK = "ok"             # already named correctly, nothing to do
STATUS_RENAME = "rename"     # will be renamed when the student presses OK
STATUS_WARN = "warn"         # will be numbered, but still needs a description
STATUS_COTS = "cots"         # left alone on purpose
STATUS_SKIP = "skip"         # left alone (empty / inside COTS)
STATUS_ERROR = "error"       # could not be numbered (message explains why)

SEVERITY_ORDER = {"error": 0, "warn": 1, "info": 2}

DEFAULT_SHARED_CODE = "MSC"

DEFAULT_SUBSYSTEMS: Dict[str, str] = {
    "FRM": "Frame",
    "DRV": "Drivetrain",
    "INT": "Intake",
    "IDX": "Indexer",
    "SHT": "Shooter",
    "ELV": "Elevator",
    "ARM": "Arm",
    "CLB": "Climber",
    "ELC": "Electrical",
    "BMP": "Bumpers",
    "MSC": "Misc / Shared",
}

# Names or vendor numbers that usually mean "we bought this".
# Students can always override a guess with the COTS checkbox in the preview.
DEFAULT_COTS_PATTERNS: List[str] = [
    r"^WCP-",                    # West Coast Products
    r"^am-\d",                   # AndyMark
    r"^REV-\d",                  # REV Robotics
    r"^217-\d",                  # VEXpro
    r"^TTB",                     # The Thrifty Bot
    r"^\d{4,5}[A-Z]\d{1,4}\b",   # McMaster-Carr (e.g. 91251A537)
    # "bearing" alone is bought, but a bearing BLOCK/plate/mount is something teams make.
    r"(?i)\bbearings?\b(?!\s*(block|plate|mount|holder|retainer|cap|support|spacer)s?\b)",
    r"(?i)\b(bolt|screw|nut|washer|rivet|shaft collar)s?\b",
    r"(?i)\b(kraken|falcon|neo|vortex|cim|minion)\b",
]

# Fusion's default names. A part with one of these "has no name yet".
DEFAULT_NAME_PATTERNS: List[str] = [
    r"^Component\s*\d*$",
    r"^Body\s*\d*$",
    r"^Part\s*\d*$",
    r"^Assembly\s*\d*$",
    r"^Untitled.*$",
    r"^New Component.*$",
]

_PN_FULL = re.compile(r"^(?P<yy>\d{2})-(?P<sub>[A-Z0-9]{2,4})-(?P<num>\d{3})$")
_PN_AT_START = re.compile(r"^\s*(?P<pn>\d{2}-[A-Z0-9]{2,4}-\d{3})(?=$|[\s:_\-])")
_PN_PREFIX_STRIP = re.compile(r"^\s*\d{2}-[A-Z0-9]{2,4}-\d{3}(?=$|[\s:_\-])[\s:_\-]*")
_VERSION_SUFFIX = re.compile(r"\s+v\d+$")       # " v12" on linked parts
_OCCURRENCE_SUFFIX = re.compile(r":\d+$")       # ":1" on occurrence names
_COPY_SUFFIX = re.compile(r"\s+\(\d+\)$")       # " (1)" Fusion adds to repeated linked names
_BAD_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')  # these break DXF/STL export later
_SUBSYSTEM_CODE = re.compile(r"^[A-Z0-9]{2,4}$")
_SEASON_YEAR = re.compile(r"^\d{2}$")


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
@dataclass
class NamingConfig:
    """Team settings. Built from gusset_config.json by lib/settings.py."""

    season_year: str
    subsystems: Dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SUBSYSTEMS))
    name_format: str = "{pn} {desc}"
    cots_patterns: List[str] = field(default_factory=lambda: list(DEFAULT_COTS_PATTERNS))
    default_name_patterns: List[str] = field(default_factory=lambda: list(DEFAULT_NAME_PATTERNS))
    shared_code: str = DEFAULT_SHARED_CODE

    def __post_init__(self) -> None:
        self.season_year = str(self.season_year).strip()
        if not _SEASON_YEAR.match(self.season_year):
            raise ValueError(f"season_year must be two digits like '27', got {self.season_year!r}")

        clean: Dict[str, str] = {}
        for code, label in (self.subsystems or {}).items():
            code_up = str(code).strip().upper()
            if not _SUBSYSTEM_CODE.match(code_up):
                log.warning("Skipping subsystem code %r: use 2-4 capital letters/digits", code)
                continue
            clean[code_up] = str(label).strip() or code_up
        if not clean:
            log.warning("No valid subsystems in settings; using the built-in list")
            clean = dict(DEFAULT_SUBSYSTEMS)
        self.subsystems = clean

        self.shared_code = str(self.shared_code or "").strip().upper()
        if self.shared_code and self.shared_code not in self.subsystems:
            log.warning("shared_subsystem %r isn't in subsystems; adding it", self.shared_code)
            if _SUBSYSTEM_CODE.match(self.shared_code):
                self.subsystems[self.shared_code] = "Shared"
            else:
                log.warning("shared_subsystem %r isn't a valid code; shared parts turned off", self.shared_code)
                self.shared_code = ""

        if "{pn}" not in self.name_format:
            log.warning("name_format %r has no {pn}; using '{pn} {desc}'", self.name_format)
            self.name_format = "{pn} {desc}"

        self._cots_re = _compile_all(self.cots_patterns, "cots_patterns")
        self._default_re = _compile_all(self.default_name_patterns, "default_name_patterns")
        log.debug("NamingConfig ready: season=%s, %d subsystems, shared=%s, %d COTS patterns",
                  self.season_year, len(self.subsystems), self.shared_code or "off", len(self._cots_re))


def _compile_all(patterns: Iterable[str], label: str) -> List["re.Pattern[str]"]:
    compiled = []
    for pattern in patterns or []:
        try:
            compiled.append(re.compile(pattern))
        except re.error as exc:
            log.warning("Ignoring bad pattern in %s: %r (%s)", label, pattern, exc)
    return compiled


# ---------------------------------------------------------------------------
# Small helpers (all unit tested)
# ---------------------------------------------------------------------------
def format_part_number(season_year: str, subsystem: str, number: int) -> str:
    """format_part_number('27', 'ELV', 104) -> '27-ELV-104'"""
    if not 0 <= int(number) <= MAX_NUMBER:
        raise ValueError(f"part number {number} is outside 000-{MAX_NUMBER}")
    return f"{season_year}-{subsystem}-{int(number):03d}"


def parse_part_number(text: Optional[str]) -> Optional[Tuple[str, str, int]]:
    """'27-ELV-104' -> ('27', 'ELV', 104). Anything else -> None."""
    if not text:
        return None
    match = _PN_FULL.match(text.strip())
    if not match:
        return None
    return match.group("yy"), match.group("sub"), int(match.group("num"))


def part_number_at_start(name: Optional[str]) -> Optional[str]:
    """'27-ELV-104 Gusset' -> '27-ELV-104'. No number at the start -> None."""
    match = _PN_AT_START.match(name or "")
    return match.group("pn") if match else None


def existing_number(part_number_field: str, name: str) -> Optional[Tuple[str, str, int]]:
    """A component's current team number, from its Part Number field or its name."""
    return parse_part_number(part_number_field) or parse_part_number(part_number_at_start(name))


def sanitize(text: str) -> str:
    """Remove characters that break file export, and tidy whitespace."""
    text = _BAD_FILENAME_CHARS.sub("-", text or "")
    return re.sub(r"\s+", " ", text).strip()


def strip_fusion_suffixes(name: str) -> str:
    """'output shaft (1):2' -> 'output shaft'. Removes the bits Fusion adds."""
    text = (name or "").strip()
    text = _OCCURRENCE_SUFFIX.sub("", text)
    text = _COPY_SUFFIX.sub("", text)
    return text.strip()


def is_default_name(name: str, cfg: NamingConfig) -> bool:
    text = (name or "").strip()
    return not text or any(p.match(text) for p in cfg._default_re)


def looks_like_cots(name: str, part_number: str, cfg: NamingConfig) -> bool:
    """Guess "bought part" from the name. Anything already carrying a TEAM part
    number (27-ARM-103 ...) is the team's own, whatever words are in it."""
    if existing_number(part_number, name):
        return False
    for text in (name or "", part_number or ""):
        for pattern in cfg._cots_re:
            if pattern.search(text):
                return True
    return False


def clean_description(name: str, cfg: NamingConfig) -> str:
    """Turn a current name into a description: '27-ELV-104 Gusset v3' -> 'Gusset'."""
    text = strip_fusion_suffixes(name)
    text = _VERSION_SUFFIX.sub("", text)
    text = _PN_PREFIX_STRIP.sub("", text, count=1)
    text = sanitize(text)
    return "" if is_default_name(text, cfg) else text


def best_description(name: str, part_number: str, cfg: NamingConfig) -> str:
    """
    Pick the nicest description. Students often type a tidy Part Number
    ('Output Shaft') while the component keeps a rough name ('output shaft').
    If the two say the same thing, use the tidier Part Number.
    """
    from_name = clean_description(name, cfg)
    if parse_part_number(part_number):
        return from_name
    from_pn = clean_description(part_number, cfg)
    if from_pn and from_name and from_pn.lower() == from_name.lower():
        return from_pn
    return from_name or from_pn


def build_name(part_number: str, description: str, cfg: NamingConfig) -> str:
    """Fill in name_format. Uses replace() so a typo in the format can't crash us."""
    if not description:
        return part_number
    return sanitize(cfg.name_format.replace("{pn}", part_number).replace("{desc}", description))


def guess_subsystem(name: str, part_number: str, cfg: NamingConfig) -> Optional[str]:
    """Best guess at a subsystem code for a top assembly, or None."""
    parsed = existing_number(part_number, name)
    if parsed and parsed[1] in cfg.subsystems:
        return parsed[1]
    lowered = (name or "").lower()
    for code, label in cfg.subsystems.items():
        if re.search(rf"\b{re.escape(code)}\b", name or "", re.IGNORECASE):
            return code
        if label and label.lower() in lowered:
            return code
    return None


def subsystem_of_name(name: str) -> Optional[str]:
    """'27-INT-100 Intake' -> 'INT'. Used to tell which subsystem a parent file belongs to."""
    parsed = parse_part_number(part_number_at_start(name))
    return parsed[1] if parsed else None


# ---------------------------------------------------------------------------
# Data passed in from Fusion, and the plan we hand back
# ---------------------------------------------------------------------------
@dataclass
class CompNode:
    """One Fusion component, flattened into plain Python."""

    key: str                         # stable id used to find the real component again
    name: str
    part_number: str = ""
    description: str = ""
    has_bodies: bool = False
    is_external: bool = False        # lives in its own linked file
    cots_flag: Optional[bool] = None # saved COTS tag on the component, if any
    standalone: bool = False         # Gusset numbered it as the TOP of its own run before
    children: List["CompNode"] = field(default_factory=list)
    # --- BOM info (only filled in by the Export BOM tool)
    material: str = ""
    mass_kg: Optional[float] = None
    process: str = ""                # saved "process" tag (X-Carve, 3D Print, ...)
    cots_info: Dict[str, str] = field(default_factory=dict)  # COTS Library details (cots_vendor, cots_pn, ...)
    # --- file info (filled in by the Fusion side; plain strings so tests are easy)
    file_id: str = ""                # set when this component IS the root of a file
    file_name: str = ""
    owner_file: str = ""             # file where this component is edited ("" = the open design)
    parent_files: List[Tuple[str, str]] = field(default_factory=list)  # (id, name) of files that link this one


@dataclass
class Proposal:
    """What we plan to do with one component. One row of the preview table."""

    key: str
    old_name: str
    old_part_number: str
    kind: str
    depth: int
    parent_key: Optional[str]
    sub: str = ""                    # subsystem code this row is numbered in
    shared: bool = False
    reason: str = ""
    is_external: bool = False
    file_id: str = ""
    file_name: str = ""
    owner_file: str = ""
    instances: int = 1
    number: Optional[int] = None
    kept: bool = False
    part_number: str = ""
    description: str = ""
    new_name: str = ""
    status: str = ""
    messages: List[str] = field(default_factory=list)

    @property
    def message(self) -> str:
        return "; ".join(self.messages)

    @property
    def will_change(self) -> bool:
        return self.status in (STATUS_RENAME, STATUS_WARN) and self.number is not None

    @property
    def is_file(self) -> bool:
        """True when this row is the root of a separate Fusion file (linked part or the open file)."""
        return bool(self.file_id)


@dataclass
class Plan:
    subsystem: str
    season_year: str
    proposals: List[Proposal] = field(default_factory=list)
    fatal: Optional[str] = None      # set when nothing can be done at all

    def summary(self) -> Dict[str, int]:
        return dict(Counter(p.status for p in self.proposals))

    def changes(self) -> List[Proposal]:
        return [p for p in self.proposals if p.will_change]

    def by_key(self) -> Dict[str, Proposal]:
        return {p.key: p for p in self.proposals}

    def files_to_save(self) -> Set[str]:
        """Linked files that will get a new saved version (not undoable with Ctrl+Z)."""
        return {p.owner_file for p in self.changes() if p.owner_file}


@dataclass
class Issue:
    """One problem found by check_design()."""

    key: str
    name: str
    severity: str     # "error" | "warn" | "info"
    message: str


UsedNumbers = Union[Iterable[int], Dict[str, Iterable[int]], None]


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------
def has_season_number(name: str, part_number: str, cfg: NamingConfig) -> bool:
    """True if the component already carries a team number for THIS season."""
    parsed = existing_number(part_number, name)
    return bool(parsed and parsed[0] == cfg.season_year)


def cots_tag_applies(cots_flag: Optional[bool], name: str, part_number: str, cfg: NamingConfig) -> bool:
    """
    Should a saved COTS tag count? A "COTS = true" tag is ignored on anything
    that already has a team number this season: vendor parts never do, so the
    tag must be left over (e.g. a COTS tick used to stop a gearbox being
    renumbered inside a bigger assembly). "COTS = false" tags always count.
    """
    if cots_flag is None:
        return False
    if cots_flag and has_season_number(name, part_number, cfg):
        return False
    return True


def classify(node: CompNode, cfg: NamingConfig, cots_override: Optional[bool] = None,
             is_top: bool = False) -> Tuple[str, str]:
    """Decide what kind of thing a component is. Returns (kind, reason).

    is_top: True for the assembly being numbered. Picking it is a clear
    signal "this is ours", so we never GUESS it's COTS from its name
    (a "NEO Gearbox" is still the team's gearbox). A saved COTS tag still counts.

    Linked files are NOT automatically COTS: most team parts live in their own
    files. Only the vendor-name patterns (or a COTS tick) make something COTS.
    """
    if is_top:
        is_cots, reason = False, ""          # the assembly being numbered is always the team's
    elif cots_override is not None:
        is_cots, reason = bool(cots_override), "set by you in this dialog"
    elif node.cots_flag is not None and cots_tag_applies(node.cots_flag, node.name, node.part_number, cfg):
        is_cots, reason = bool(node.cots_flag), "tagged earlier"
    elif node.cots_flag is not None:
        is_cots, reason = False, ""          # stale COTS tag on a team-numbered part: ignore it
    elif looks_like_cots(node.name, node.part_number, cfg):
        is_cots, reason = True, "name looks like a bought part"
    else:
        is_cots, reason = False, ""
    if is_cots:
        return KIND_COTS, reason
    if node.children:
        return KIND_ASSEMBLY, reason
    if node.has_bodies:
        return KIND_PART, reason
    return KIND_SKIP, "empty component (no bodies or sub-components)"


def detect_shared(node: CompNode, sub: str, run_files: Set[str], cfg: NamingConfig,
                  override: Optional[bool] = None) -> Tuple[bool, str]:
    """
    Is this team part also used by ANOTHER subsystem? Returns (shared, why).
      - a tick in the preview's Shared column always wins
      - something already numbered in the shared block stays shared
      - a file linked into an assembly from a different subsystem is shared
    """
    shared_code = cfg.shared_code
    if not shared_code or sub == shared_code:
        return False, ""
    if override is not None:
        return bool(override), "set by you in this dialog"
    parsed = existing_number(node.part_number, node.name)
    if parsed and parsed[0] == cfg.season_year and parsed[1] == shared_code:
        return True, "already numbered as a shared part"
    for file_id, file_name in node.parent_files:
        if file_id in run_files:
            continue  # a parent inside this same subsystem
        other = subsystem_of_name(file_name)
        if other and other not in (sub, shared_code):
            return True, f"also used in '{file_name}'"
    return False, ""


def owning_subsystem(node: CompNode, sub: str, cfg: NamingConfig) -> Tuple[Optional[str], str]:
    """
    A component already numbered THIS season in a different, known subsystem
    (like a gearbox numbered 27-GRB-100 on its own, now inside the DRV chassis)
    stays in that subsystem. Returns (subsystem, why) or (None, "").
    The shared block isn't an owner here; shared parts are handled by detect_shared.
    """
    parsed = existing_number(node.part_number, node.name)
    if not parsed:
        return None, ""
    p_yy, p_sub, _num = parsed
    # (Codes missing from settings still count: Check Names flags those separately.)
    if p_yy != cfg.season_year or p_sub == sub or p_sub == cfg.shared_code:
        return None, ""
    return p_sub, f"already numbered in {p_sub}, so it keeps its {p_sub} number"


def _normalize_used(used_elsewhere: UsedNumbers, sub: str) -> Dict[str, Dict[int, str]]:
    """Accept either {sub: numbers} or a plain list of numbers for `sub`."""
    used: Dict[str, Dict[int, str]] = {}
    if used_elsewhere is None:
        return used
    if isinstance(used_elsewhere, dict):
        for code, numbers in used_elsewhere.items():
            used.setdefault(str(code).upper(), {}).update({int(n): "(used elsewhere)" for n in numbers})
    else:
        used[sub] = {int(n): "(used elsewhere)" for n in used_elsewhere}
    return used


def _next_free_block(used: Dict[int, str]) -> Optional[int]:
    blocks = range(BLOCK, MAX_NUMBER + 1, BLOCK)
    for start in blocks:                       # prefer a completely empty block
        if all(n not in used for n in range(start, start + BLOCK)):
            return start
    for start in blocks:                       # otherwise any block whose 00 is free
        if start not in used:
            log.warning("No empty blocks left; reusing partly used block %d", start)
            return start
    return None


def _next_free_in_block(block_start: int, used: Dict[int, str]) -> Optional[int]:
    for n in range(block_start + 1, block_start + BLOCK):
        if n not in used:
            return n
    return None


def _next_free_loose(used: Dict[int, str]) -> Optional[int]:
    """A number for a shared part that has no shared parent assembly.
    Skips XX00 numbers and blocks owned by a shared assembly."""
    for n in range(BLOCK + 1, MAX_NUMBER + 1):
        if n % BLOCK == 0:
            continue
        if n not in used and (n - n % BLOCK) not in used:
            return n
    return None


def _walk(node: CompNode, out: List[CompNode], seen: Set[str], depth: int = 0) -> None:
    if node.key in seen or depth > MAX_DEPTH:
        return
    seen.add(node.key)
    out.append(node)
    for child in node.children:
        _walk(child, out, seen, depth + 1)


def plan_subsystem(
    root: Optional[CompNode],
    subsystem: str,
    cfg: NamingConfig,
    used_elsewhere: UsedNumbers = None,
    keep_existing: bool = True,
    overrides: Optional[Dict[str, Dict[str, object]]] = None,
) -> Plan:
    """
    Build a numbering plan for one subsystem assembly. Changes NOTHING in Fusion.

    root           - the assembly being numbered, as a CompNode tree
    subsystem      - code like "ELV"
    used_elsewhere - numbers already used OUTSIDE this assembly, either a list
                     (for `subsystem`) or {"ELV": [...], "MSC": [...]}
    keep_existing  - keep good numbers already in place (recommended)
    overrides      - {key: {"description": str, "cots": bool, "shared": bool}}
                     from the preview table
    """
    overrides = overrides or {}
    sub = (subsystem or "").strip().upper()
    yy = cfg.season_year
    plan = Plan(subsystem=sub, season_year=yy)
    log.info("Planning %s-%s (keep_existing=%s, %d overrides)", yy, sub, keep_existing, len(overrides))

    if root is None:
        plan.fatal = "Open the subsystem's assembly file, or select an assembly."
        return plan
    if sub not in cfg.subsystems:
        plan.fatal = f"Unknown subsystem '{sub}'. Add it to the settings file first."
        return plan

    every: List[CompNode] = []
    _walk(root, every, set())
    run_files = {n.file_id for n in every if n.file_id}

    # --- 1. Walk the tree. Every component gets exactly one row, in tree order.
    index: Dict[str, Proposal] = {}

    def visit(node: CompNode, parent_key: Optional[str], depth: int,
              under_cots: bool, parent_sub: str) -> None:
        if depth > MAX_DEPTH:
            log.warning("Stopped at depth %d under %r (design nested too deep?)", depth, node.name)
            return
        if node.key in index:                  # same component used again
            index[node.key].instances += 1
            return
        override = overrides.get(node.key, {})
        is_top = depth == 0
        if under_cots:
            kind, reason = KIND_SKIP, "inside a COTS part"
        else:
            kind, reason = classify(node, cfg, override.get("cots"), is_top=is_top)  # type: ignore[arg-type]

        shared, shared_why, owned_by = False, "", None
        if kind in (KIND_ASSEMBLY, KIND_PART) and not is_top:
            owned_by, owned_why = owning_subsystem(node, parent_sub, cfg)
            if owned_by and node.standalone and override.get("shared") is None:
                pass      # numbered on its own earlier: keep it, even if used elsewhere
            else:
                shared, shared_why = detect_shared(node, parent_sub, run_files, cfg,
                                                   override.get("shared"))  # type: ignore[arg-type]
                if shared:
                    owned_by = None
        if shared:
            row_sub = cfg.shared_code
        elif owned_by:
            row_sub = owned_by
        else:
            row_sub = parent_sub

        proposal = Proposal(
            key=node.key, old_name=node.name, old_part_number=node.part_number,
            kind=kind, depth=depth, parent_key=parent_key, sub=row_sub, shared=shared,
            reason=reason, is_external=node.is_external, file_id=node.file_id,
            file_name=node.file_name, owner_file=node.owner_file,
        )
        if shared_why:
            proposal.messages.append(f"shared part: {shared_why}")
        elif owned_by:
            proposal.messages.append(owned_why)
        index[node.key] = proposal
        plan.proposals.append(proposal)
        log.debug("%s%-8s %-4s %s%s", "  " * depth, kind, row_sub, node.name, " [file]" if node.file_id else "")
        for child in node.children:
            visit(child, node.key, depth + 1, under_cots or kind == KIND_COTS, row_sub)

    visit(root, None, 0, False, sub)

    top = plan.proposals[0]
    if top.kind == KIND_PART:
        plan.fatal = (f"'{top.old_name}' has bodies but no sub-components, so Gusset sees it "
                      "as one part. If each gear and shaft is a separate body, right-click the "
                      "bodies > 'Create Components from Bodies', then run Name Parts again. "
                      "Otherwise, open or select the assembly that contains this part.")
    elif top.kind == KIND_SKIP:
        plan.fatal = f"'{top.old_name}' is empty, so there is nothing to name."
    if plan.fatal:
        log.warning("Plan stopped: %s", plan.fatal)
        _finish_rows(plan, cfg, overrides)
        return plan

    numbered = [p for p in plan.proposals if p.kind in (KIND_ASSEMBLY, KIND_PART)]
    used_all = _normalize_used(used_elsewhere, sub)

    def used_for(code: str) -> Dict[int, str]:
        return used_all.setdefault(code, {})

    # --- 2. Keep numbers that are already correct (if allowed).
    if keep_existing:
        for p in numbered:
            parsed = existing_number(p.old_part_number, p.old_name)
            if not parsed:
                continue
            p_yy, p_sub, p_num = parsed
            old_pn = format_part_number(p_yy, p_sub, p_num)
            used = used_for(p.sub)
            if (p_yy, p_sub) != (yy, p.sub):
                if p.shared and p_yy == yy:
                    p.messages.append(f"moving {old_pn} into the shared {p.sub} block")
                else:
                    p.messages.append(f"old number {old_pn} is from another season or subsystem")
            elif p.kind == KIND_ASSEMBLY and p_num % BLOCK != 0:
                p.messages.append(f"{old_pn} doesn't end in 00, but this is an assembly")
            elif p.kind == KIND_PART and p_num % BLOCK == 0:
                p.messages.append(f"{old_pn} ends in 00, which is saved for assemblies")
            elif p_num in used:
                p.messages.append(f"{old_pn} is already used by another part")
            else:
                p.number, p.kept = p_num, True
                used[p_num] = p.key
                log.debug("Keeping %s for %r", old_pn, p.old_name)

    # --- 3a. An unnumbered assembly whose kept parts already sit in one block
    #         "adopts" that block, so students' existing part numbers survive.
    for p in numbered:
        if p.kind != KIND_ASSEMBLY or p.number is not None:
            continue
        used = used_for(p.sub)
        child_blocks = Counter(
            c.number - c.number % BLOCK for c in numbered
            if c.parent_key == p.key and c.kind == KIND_PART and c.kept
            and c.number is not None and c.sub == p.sub
        )
        for block, _count in child_blocks.most_common():
            if block not in used:
                p.number = block
                used[block] = p.key
                log.debug("Assembly %r adopts block %d from its parts", p.old_name, block)
                break

    # --- 3b. Give every other assembly without a number its own hundreds block.
    for p in numbered:
        if p.kind != KIND_ASSEMBLY or p.number is not None:
            continue
        used = used_for(p.sub)
        block = _next_free_block(used)
        if block is None:
            p.status = STATUS_ERROR
            p.messages.append(f"out of assembly blocks in {p.sub} (max 9); split into another subsystem code")
            continue
        p.number = block
        used[block] = p.key
        log.debug("Assembly %r -> %s block %d", p.old_name, p.sub, block)

    # --- 4. Number parts: inside their parent's block, or loose in the shared block.
    for p in numbered:
        if p.kind != KIND_PART:
            continue
        used = used_for(p.sub)
        parent = index.get(p.parent_key or "")
        same_space = parent is not None and parent.sub == p.sub

        if not same_space:
            # A shared part inside a normal assembly: any free shared number.
            if p.number is not None:
                continue                           # kept, still valid
            n = _next_free_loose(used)
            if n is None:
                p.status = STATUS_ERROR
                p.messages.append(f"no free numbers left in {p.sub}")
                continue
            p.number = n
            used[n] = p.key
            continue

        if parent.number is None:
            if p.number is not None and p.kept:
                del used[p.number]
            p.number, p.kept = None, False
            p.status = STATUS_ERROR
            p.messages.append("its assembly has no number, so this part can't get one")
            continue
        block = parent.number - parent.number % BLOCK
        if p.number is not None:
            if p.number - p.number % BLOCK == block:
                continue                              # kept, and in the right block
            p.messages.append(f"moved into {format_part_number(yy, p.sub, block)}'s block")
            del used[p.number]
            p.number, p.kept = None, False
        n = _next_free_in_block(block, used)
        if n is None:
            p.status = STATUS_ERROR
            p.messages.append("block is full (99 parts); split this assembly into sub-assemblies")
            continue
        p.number = n
        used[n] = p.key

    _finish_rows(plan, cfg, overrides)
    log.info("Plan for %s-%s: %s; %d linked file(s) to save", yy, sub, plan.summary(), len(plan.files_to_save()))
    return plan


def _finish_rows(plan: Plan, cfg: NamingConfig, overrides: Dict[str, Dict[str, object]]) -> None:
    """Fill in part number, description, new name and status for every row."""
    for p in plan.proposals:
        override = overrides.get(p.key, {})
        if p.kind == KIND_COTS:
            p.status, p.part_number, p.new_name = STATUS_COTS, p.old_part_number, p.old_name
            p.description = clean_description(p.old_name, cfg) or p.old_name
            if p.reason:
                p.messages.append(p.reason)
            continue
        if p.kind == KIND_SKIP:
            p.status, p.part_number, p.new_name = STATUS_SKIP, p.old_part_number, p.old_name
            p.description = p.old_name
            if p.reason:
                p.messages.append(p.reason)
            continue

        if "description" in override:
            p.description = sanitize(str(override["description"]))
        else:
            p.description = best_description(p.old_name, p.old_part_number, cfg)

        if plan.fatal or p.number is None:
            p.status = STATUS_ERROR if not plan.fatal else STATUS_SKIP
            p.part_number, p.new_name = "", p.old_name
            continue

        p.part_number = format_part_number(plan.season_year, p.sub or plan.subsystem, p.number)
        p.new_name = build_name(p.part_number, p.description, cfg)
        if not p.description:
            p.status = STATUS_WARN
            p.messages.append("needs a description - type one in the table")
        elif (p.new_name == strip_fusion_suffixes(p.old_name)
              and p.part_number == p.old_part_number):
            p.status = STATUS_OK
        else:
            p.status = STATUS_RENAME


# ---------------------------------------------------------------------------
# Checking a whole design (used by "Check Names", and later the review checklist)
# ---------------------------------------------------------------------------
def check_design(nodes: Iterable[CompNode], cfg: NamingConfig) -> List[Issue]:
    """Find naming problems in a list of UNIQUE components. Changes nothing."""
    issues: List[Issue] = []
    first_owner: Dict[str, CompNode] = {}
    cots_keys: Set[str] = set()

    node_list = list(nodes)
    # Anything inside a COTS part is the vendor's business, not ours.
    by_key = {n.key: n for n in node_list}
    for n in node_list:
        if n.cots_flag is not None:
            is_cots = bool(n.cots_flag) and cots_tag_applies(n.cots_flag, n.name, n.part_number, cfg)
        else:
            is_cots = looks_like_cots(n.name, n.part_number, cfg)
        if is_cots:
            stack = [n]
            while stack:
                cur = stack.pop()
                if cur.key in cots_keys:
                    continue
                cots_keys.add(cur.key)
                stack.extend(by_key.get(c.key, c) for c in cur.children)

    for n in node_list:
        if n.key in cots_keys:
            continue
        name = strip_fusion_suffixes(n.name)
        if not n.children and not n.has_bodies:
            issues.append(Issue(n.key, name, "info", "empty component - delete it or add geometry"))
            continue
        if is_default_name(name, cfg):
            issues.append(Issue(n.key, name, "error", "still has a default name - run Name Parts"))
            continue

        parsed = existing_number(n.part_number, name)
        if not parsed:
            issues.append(Issue(n.key, name, "warn", "no team part number yet - run Name Parts"))
            continue

        yy, sub, num = parsed
        pn = format_part_number(yy, sub, num)
        owner = first_owner.setdefault(pn, n)
        if owner.key != n.key:
            issues.append(Issue(n.key, name, "error", f"duplicate part number - '{owner.name}' also uses {pn}"))
        if yy != cfg.season_year:
            issues.append(Issue(n.key, name, "warn", f"numbered for the 20{yy} season (now 20{cfg.season_year})"))
        if sub not in cfg.subsystems:
            issues.append(Issue(n.key, name, "warn", f"unknown subsystem code '{sub}'"))
        if n.children and num % BLOCK:
            issues.append(Issue(n.key, name, "warn", "assembly number should end in 00"))
        if not n.children and num % BLOCK == 0:
            issues.append(Issue(n.key, name, "warn", "part number ends in 00 (saved for assemblies)"))
        if part_number_at_start(name) != pn:
            issues.append(Issue(n.key, name, "warn", f"name doesn't start with its part number {pn}"))
        elif not clean_description(name, cfg):
            issues.append(Issue(n.key, name, "warn", "needs a description after the part number"))

    issues.sort(key=lambda i: (SEVERITY_ORDER.get(i.severity, 9), i.name.lower()))
    log.info("check_design found %d issue(s)", len(issues))
    return issues
