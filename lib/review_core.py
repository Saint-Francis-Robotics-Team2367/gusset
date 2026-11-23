"""
review_core.py - Gusset's Design Review: automatic checks, a mentor checklist,
sign-off records and a PDF report. Plain Python, unit tested.

Every check explains WHY it matters and HOW to fix it, because many students
reading it are new to CAD.
"""

from __future__ import annotations

import datetime
import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from . import bom_core as bc
from . import cots_match as cmatch
from . import naming_core as nc
from .pdf_writer import PdfPage, text_width, write_pdf

log = logging.getLogger("gusset.review")

PASS, WARN, FAIL, INFO = "PASS", "WARN", "FAIL", "INFO"
STATUS_ORDER = {FAIL: 0, WARN: 1, INFO: 2, PASS: 3}
REVIEW_ATTR = "review_log"

DECISIONS = ["Approved", "Approved with small changes", "Changes needed - review again"]

DEFAULT_CHECKLIST: List[Tuple[str, str]] = [
    ("Every shaft is held by two bearings (or a bearing and a solid support)",
     "One bearing lets a shaft wobble, which wrecks belts, chains and gears."),
    ("Every bolt can be reached with a tool after the robot is built",
     "If you can't get a hex key on it, you can't fix it in the pit."),
    ("Motors and gearboxes can be swapped in about 10 minutes",
     "Between matches you have minutes, not hours."),
    ("Every chain and belt has a way to tension it",
     "They stretch. Without tensioning they skip or fall off."),
    ("Moving mechanisms (arms, elevators) have hard stops",
     "Hard stops protect the robot when code or sensors fail."),
    ("Wires have a planned path and can't be pinched by moving parts",
     "Pinched wires cause the hardest-to-find failures at events."),
    ("Every part fits the machine that makes it (X-Carve bed, printer, lathe)",
     "Find out now, not the night before bag-and-tag."),
    ("Nothing sticks outside the frame perimeter or height limit in the starting position",
     "Check this season's game manual; inspectors measure it."),
    ("No critical load hangs on a single bolt or a thin 3D-printed wall",
     "Impacts find the weakest part first."),
    ("The design was talked through with the drive team",
     "They'll use it every match; their feedback catches real problems."),
]


@dataclass
class CheckResult:
    check_id: str
    title: str
    status: str
    why: str
    fix: str
    items: List[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if self.status == PASS:
            return "OK"
        return f"{len(self.items)} item(s)" if self.items else self.status.lower()


@dataclass
class ReviewRecord:
    date: str
    reviewer: str
    decision: str
    notes: str
    assembly: str
    auto: Dict[str, str]                 # check title -> status
    checklist: Dict[str, bool]           # item -> checked
    version: str = ""


def library_candidates(root: nc.CompNode) -> List[Tuple[str, bool]]:
    """
    (name, came from the COTS Library) for every component - but not the insides of
    bought parts (a motor's STEP has its own 'bearing' components), which aren't the
    team's to fix.
    """
    out: List[Tuple[str, bool]] = []
    seen = set()
    stack = [root]
    while stack:
        n = stack.pop()
        if n.key in seen:
            continue
        seen.add(n.key)
        from_library = bool(n.cots_info.get("cots_pn") or n.cots_info.get("cots_vendor"))
        if n is not root:
            out.append((nc.strip_fusion_suffixes(n.name), from_library))
        if from_library or n.cots_flag:
            continue                          # don't look inside bought parts
        stack.extend(n.children)
    return out


def auto_checks(root: nc.CompNode, cfg: nc.NamingConfig, bom: bc.Bom,
                out_of_date: Sequence[str] = (), interference: Optional[Sequence[Tuple[str, str]]] = None,
                library_items: Sequence[object] = ()) -> List[CheckResult]:
    """
    Run every automatic check. `interference` None = not checked (it's optional and
    slower). library_items = the COTS panel's catalog (for the hand-modeled check).
    """
    seen = set()
    nodes: List[nc.CompNode] = []
    stack = [root]
    while stack:
        n = stack.pop()
        if n.key in seen:
            continue
        seen.add(n.key)
        nodes.append(n)
        stack.extend(n.children)
    issues = nc.check_design(nodes, cfg)

    def names(predicate) -> List[str]:
        return sorted({nc.strip_fusion_suffixes(i.name) for i in issues if predicate(i)})

    made = [r for r in bom.flat if r.type == bc.TYPE_MADE]
    results = [
        CheckResult("names", "Every part has a team part number", PASS,
                    "Part numbers are how parts get cut, ordered and tracked in monday.",
                    "Run GUSSET > Name Parts on this assembly.",
                    names(lambda i: i.severity == "error" and "default name" in i.message
                          or "no team part number" in i.message)),
        CheckResult("duplicates", "No two parts share a part number", PASS,
                    "Two parts with one number means the wrong one gets cut.",
                    "Run Name Parts, or rename one of them.",
                    names(lambda i: "duplicate" in i.message)),
        CheckResult("season", "Part numbers are for this season", PASS,
                    "Old numbers mix last year's robot into this year's BOM.",
                    "Run Name Parts with 'Keep good existing numbers' unticked for those parts.",
                    names(lambda i: "season" in i.message)),
        CheckResult("material", "Made parts have a real material", PASS,
                    "Fusion starts every body as Steel, so weight is wrong until it's set.",
                    "Select the body > Modify > Physical Material, drag on the right material.",
                    sorted(r.name for r in made if r.material in ("", bc.FUSION_DEFAULT_MATERIAL))),
        CheckResult("process", "Every made part has a process", PASS,
                    "The process decides how the part gets made (X-Carve, print, lathe...).",
                    "Open GUSSET > Export BOM and pick a process for each part.",
                    sorted(r.name for r in made if r.process in ("", bc.PROCESS_TBD))),
        CheckResult("vendor", "Bought parts can be ordered", PASS,
                    "If a COTS part doesn't show its vendor part number, nobody knows what to order.",
                    "Use the vendor's file/name (e.g. 'am-0255', 'WCP-0903') or note it in monday.",
                    sorted(r.name for r in bom.flat if r.type == bc.TYPE_COTS and not r.vendor)),
        CheckResult("links", "Linked parts are up to date", PASS,
                    "An out-of-date link shows an old version of a part.",
                    "Click the refresh arrow (Get Latest) in Fusion's top toolbar.",
                    sorted(out_of_date)),
        CheckResult("library", "Bought parts come from the COTS Library", PASS,
                    "Library parts carry the vendor, part #, price and store link into the BOM and shopping "
                    "list, and they're the vendor's exact model.",
                    "Delete the hand-made one and insert the library part from the COTS panel "
                    "(or add it to the library with + Add).",
                    [h.line() for h in cmatch.hand_modeled(library_candidates(root), list(library_items))]),
        CheckResult("empty", "No empty components", PASS,
                    "Empty components clutter the browser and the BOM.",
                    "Delete them, or add the geometry they were meant for.",
                    names(lambda i: "empty component" in i.message)),
    ]
    if interference is None:
        results.append(CheckResult("overlap", "Parts don't overlap", INFO,
                                   "Overlapping parts can't both exist in real life.",
                                   "Tick 'Check for overlapping parts' to run this check (it takes longer)."))
    else:
        results.append(CheckResult("overlap", "Parts don't overlap", PASS,
                                   "Overlapping parts can't both exist in real life.",
                                   "Use Inspect > Interference to see the overlap, then move or resize a part. "
                                   "(A bolt in a tapped hole can show up here; that one's fine.)",
                                   [f"{a}  ↔  {b}" for a, b in interference]))
    severity = {"names": FAIL, "duplicates": FAIL, "overlap": FAIL, "season": WARN, "material": WARN,
                "process": WARN, "vendor": WARN, "links": WARN, "library": WARN, "empty": INFO}
    for r in results:
        if r.items:
            r.status = severity.get(r.check_id, WARN)
    results.sort(key=lambda r: STATUS_ORDER[r.status])
    log.info("Review checks: %s", {r.check_id: r.status for r in results})
    return results


# ---------------------------------------------------------------------------
# Records (saved on the assembly)
# ---------------------------------------------------------------------------
def parse_records(text: str) -> List[ReviewRecord]:
    if not text:
        return []
    try:
        data = json.loads(text)
        return [ReviewRecord(**d) for d in data if isinstance(d, dict)]
    except (ValueError, TypeError) as exc:
        log.warning("Ignoring unreadable review log (%s)", exc)
        return []


def add_record(text: str, record: ReviewRecord) -> str:
    records = parse_records(text) + [record]
    return json.dumps([asdict(r) for r in records[-50:]])     # keep the last 50 reviews


# ---------------------------------------------------------------------------
# PDF report
# ---------------------------------------------------------------------------
def _wrap(text: str, width_pt: float, size: float) -> List[str]:
    words, lines, line = str(text).split(), [], ""
    for w in words:
        trial = f"{line} {w}".strip()
        if text_width(trial, size) > width_pt and line:
            lines.append(line)
            line = w
        else:
            line = trial
    if line:
        lines.append(line)
    return lines or [""]


def render_report(path: str, record: ReviewRecord, results: List[CheckResult],
                  checklist: List[Tuple[str, str]]) -> str:
    pages: List[PdfPage] = []
    m, bottom = 40, 50

    def new_page() -> Tuple[PdfPage, float]:
        page = PdfPage(612, 792)          # US Letter, portrait
        pages.append(page)
        page.text(m, 760, "GUSSET DESIGN REVIEW", size=9, bold=True, gray=0.45)
        page.text(612 - m, 760, f"{record.assembly}  ·  {record.date}", size=9, gray=0.45, align="right")
        return page, 735

    page, y = new_page()
    page.text(m, y, record.assembly, size=18, bold=True)
    y -= 24
    for label, value in (("Date", record.date), ("Reviewed by", record.reviewer or "-"),
                         ("Decision", record.decision), ("Gusset", record.version)):
        page.text(m, y, label.upper(), size=7.5, bold=True, gray=0.45)
        page.text(m + 90, y, value, size=10, bold=label == "Decision")
        y -= 15
    if record.notes:
        page.text(m, y, "NOTES", size=7.5, bold=True, gray=0.45)
        for line in _wrap(record.notes, 612 - 2 * m - 90, 10)[:12]:
            page.text(m + 90, y, line, size=10)
            y -= 13
    y -= 10

    def ensure(space: float):
        nonlocal page, y
        if y - space < bottom:
            page, y = new_page()

    page.text(m, y, "AUTOMATIC CHECKS", size=9, bold=True, gray=0.45)
    y -= 16
    for r in results:
        ensure(30)
        mark = {PASS: "PASS", WARN: "WARN", FAIL: "FAIL", INFO: "INFO"}[r.status]
        page.rect(m, y - 3, 34, 13, width=0.5, fill_gray={PASS: 0.92, WARN: 0.8, FAIL: 0.6, INFO: 0.95}[r.status])
        page.text(m + 17, y, mark, size=7.5, bold=True, align="center")
        page.text(m + 42, y, r.title, size=10, bold=True)
        y -= 13
        if r.status != PASS:
            for line in _wrap(f"Why: {r.why}  Fix: {r.fix}", 612 - 2 * m - 42, 8.5)[:3]:
                ensure(12)
                page.text(m + 42, y, line, size=8.5, gray=0.3)
                y -= 11
            for item in r.items[:12]:
                ensure(12)
                page.text(m + 52, y, "- " + item, size=8.5)
                y -= 11
            if len(r.items) > 12:
                page.text(m + 52, y, f"...and {len(r.items) - 12} more", size=8.5, gray=0.4)
                y -= 11
        y -= 5

    ensure(40)
    y -= 6
    page.text(m, y, "MENTOR CHECKLIST", size=9, bold=True, gray=0.45)
    y -= 16
    for title, _help in checklist:
        ensure(16)
        done = record.checklist.get(title, False)
        page.rect(m, y - 2, 10, 10, width=0.8)
        if done:
            page.line(m + 2, y + 3, m + 4.5, y, width=1.4)
            page.line(m + 4.5, y, m + 9, y + 7, width=1.4)
        for i, line in enumerate(_wrap(title, 612 - 2 * m - 20, 10)):
            page.text(m + 18, y, line, size=10)
            y -= 13
        y -= 2

    for p in pages:
        p.text(m, 30, f"Page {pages.index(p) + 1} of {len(pages)}. Made by Gusset from the Fusion model. "
                      "Automatic checks don't replace a careful look at the design.", size=7.5, gray=0.45)
    return write_pdf(path, pages, title=f"{record.assembly} design review {record.date}")


def new_record(assembly: str, reviewer: str, decision: str, notes: str, results: List[CheckResult],
               checklist: Dict[str, bool], version: str, when: Optional[str] = None) -> ReviewRecord:
    return ReviewRecord(date=when or datetime.date.today().isoformat(), reviewer=reviewer.strip(),
                        decision=decision, notes=notes.strip(), assembly=assembly,
                        auto={r.title: r.status for r in results}, checklist=dict(checklist), version=version)
