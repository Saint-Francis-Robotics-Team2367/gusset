"""
file_runner.py - applies naming edits in Fusion.

apply_local_edits() runs INSIDE the Name Parts command (one Ctrl+Z undoes it).
run_file_jobs() runs AFTER the command closes, because Fusion doesn't allow
opening, saving or closing files during a command. For each linked file it:
    1. opens the file in the background (or uses it if it's already open)
    2. refreshes links to child files that were just changed
    3. sets the part number / description (and names of local components)
    4. saves a new version ("Gusset: part numbers")
    5. closes it, then renames the file itself
Every step is logged; one failing file never stops the others.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import adsk.core
import adsk.fusion

from . import design_tree as dt
from . import log as gslog
from .file_jobs import TAG_CACHE_ATTR, Edit, FileJob, JobPlan, cache_entries, merge_cache

_log = gslog.get_logger("file_runner")

SAVE_NOTE = "Gusset: part numbers"
SAVE_NOTE_TAGS = "Gusset: part info"


@dataclass
class RunReport:
    renamed: int = 0
    tagged: int = 0
    files_saved: List[str] = field(default_factory=list)
    files_renamed: List[str] = field(default_factory=list)
    failures: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)


def _apply_edit(comp, edit: Edit) -> None:
    """Change one component and read it back to make sure it stuck."""
    if edit.renumber:
        _log.debug("  %r -> %r (%s)", edit.old_name, edit.new_name, edit.part_number)
        # The root of a file takes its name from the FILE, so we rename the file later.
        # (Reading partNumber/description is slow in Fusion, so we just set them.)
        if not edit.is_file_root and comp.name != edit.new_name:
            comp.name = edit.new_name
        comp.partNumber = edit.part_number
        if edit.description:
            comp.description = edit.description
        dt.write_attr(comp, "kind", edit.kind)
        dt.write_attr(comp, "pn", edit.part_number)   # fast tag: next run skips the slow partNumber read
        if edit.is_run_top:
            # "Numbered on its own": inside a bigger assembly later, it keeps this number.
            dt.write_attr(comp, "top", "true")
        if edit.cots_tag is None:
            dt.write_attr(comp, "cots", "false")
        if comp.partNumber != edit.part_number or (not edit.is_file_root and comp.name != edit.new_name):
            raise RuntimeError(f"Fusion kept name={comp.name!r}, part number={comp.partNumber!r}")
    if edit.cots_tag is not None:
        dt.write_attr(comp, "cots", edit.cots_tag)
    for name, value in edit.attrs.items():
        _log.debug("  tag %r: %s = %s", edit.old_name, name, value)
        dt.write_attr(comp, name, value)


def apply_local_edits(edits: List[Edit], components: Dict[str, object], report: RunReport) -> None:
    """Edits to components in the open design (inside the command = undoable)."""
    for edit in edits:
        comp = components.get(edit.key)
        if comp is None:
            report.failures.append(f"{edit.old_name}: couldn't find it in the design any more")
            continue
        try:
            _apply_edit(comp, edit)
            if edit.renumber:
                report.renamed += 1
            elif edit.attrs:
                report.tagged += 1
        except Exception as exc:
            _log.error("Could not update %r: %s", edit.old_name, exc)
            report.failures.append(f"{edit.old_name}: {exc}")


def _find_open_document(app, file_id: str):
    for i in range(app.documents.count):
        doc = app.documents.item(i)
        try:
            if doc.dataFile and doc.dataFile.id == file_id:
                return doc
        except Exception:
            continue
    return None


def _write_cache(comp, run_cache: Dict[str, Dict[str, str]], skip_file: str = "") -> None:
    """Keep a copy of linked parts' tags on an assembly (see file_jobs.TAG_CACHE_ATTR)."""
    if not run_cache:
        return
    try:
        old = json.loads(dt.read_text_attr(comp, TAG_CACHE_ATTR) or "{}")
    except ValueError:
        old = {}
    merged = merge_cache(old if isinstance(old, dict) else {}, run_cache, skip_file)
    dt.write_attr(comp, TAG_CACHE_ATTR, json.dumps(merged))
    _log.debug("  tag cache on %r: %d file(s)", getattr(comp, "name", "?"), len(merged))


def _run_one(app, job: FileJob, data_file, report: RunReport, note: str = SAVE_NOTE,
             run_cache: Optional[Dict[str, Dict[str, str]]] = None, quick: bool = False) -> None:
    if quick and not job.edits and job.refresh:
        _log.debug("Quick rename: no need to open %r just to refresh its links", job.label)
        return
    if quick and job.rename_only:
        # Just rename the file - Fusion keeps every link (links follow file ids, not names).
        if data_file.name != job.rename_to:
            _log.info("Quick rename %r -> %r", data_file.name, job.rename_to)
            data_file.name = job.rename_to
            dt.note_file_renamed(job.file_id, job.rename_to)
            report.files_renamed.append(f"{job.label} -> {job.rename_to}")
        report.renamed += sum(1 for e in job.edits if e.renumber)
        return
    doc = _find_open_document(app, job.file_id)
    opened_here = doc is None
    if not opened_here and doc.isModified:
        report.skipped.append(f"{job.label}: it's open with unsaved changes. Save or close it, then run Name Parts again.")
        _log.warning("Skipping %r: open with unsaved changes", job.label)
        return

    needs_open = bool(job.refresh or job.edits)
    if needs_open:
        if opened_here:
            _log.info("Opening %r in the background", job.label)
            doc = app.documents.open(data_file, False)
            if doc is None:
                raise RuntimeError("Fusion couldn't open the file (no access, or it's from a library?)")
        design = adsk.fusion.Design.cast(doc.products.itemByProductType("DesignProductType"))
        if design is None:
            raise RuntimeError("the file isn't a Fusion design")
        try:
            if job.refresh:
                _log.debug("  refreshing links in %r", job.label)
                doc.updateAllReferences()
            for edit in job.edits:
                comp = design.rootComponent if edit.is_file_root else dt.find_component(design, edit.key, edit.old_name)
                if comp is None:
                    raise RuntimeError(f"couldn't find '{edit.old_name}' inside the file")
                _apply_edit(comp, edit)
                if edit.renumber:
                    report.renamed += 1
                elif edit.attrs:
                    report.tagged += 1
            if job.refresh:
                # This assembly contains files we just tagged; keep a visible copy of their tags.
                _write_cache(design.rootComponent, run_cache or {}, skip_file=job.file_id)
            if doc.isModified or job.refresh:
                if not doc.save(note):
                    raise RuntimeError("save failed (is the file read-only, or in another project?)")
                report.files_saved.append(job.label)
                _log.info("Saved new version of %r", job.label)
        finally:
            if opened_here:
                doc.close(False)

    if job.rename_to and data_file.name != job.rename_to:
        _log.info("Renaming file %r -> %r", data_file.name, job.rename_to)
        data_file.name = job.rename_to
        dt.note_file_renamed(job.file_id, job.rename_to)
        report.files_renamed.append(f"{job.label} -> {job.rename_to}")


def run_file_jobs(job_plan: JobPlan, files: Dict[str, object], active_doc, note: str = SAVE_NOTE,
                  quick: bool = False) -> RunReport:
    """
    Process linked files deepest-first, then rename the open file and refresh it.
    quick=True: files whose only change is their number are just renamed (no
    open/save); the rest are opened as usual.
    """
    app = adsk.core.Application.get()
    ui = app.userInterface
    report = RunReport()
    started = time.time()
    total = len(job_plan.jobs)
    _log.info("Updating %d linked file(s)%s...", total,
              f" (quick: {sum(1 for j in job_plan.jobs if j.rename_only)} rename-only)" if quick else "")
    run_cache = cache_entries(job_plan.jobs)

    progress = ui.progressBar
    try:
        progress.show("Gusset: updating file %v of %m", 0, max(total, 1), False)
    except Exception:
        progress = None

    for i, job in enumerate(job_plan.jobs, start=1):
        if progress:
            progress.progressValue = i - 1
        adsk.doEvents()
        data_file = files.get(job.file_id)
        if data_file is None:
            report.failures.append(f"{job.label}: lost track of the file")
            continue
        try:
            _run_one(app, job, data_file, report, note, run_cache, quick)
        except Exception as exc:
            _log.exception("File %r failed", job.label)
            report.failures.append(f"{job.label}: {exc}")

    try:
        if active_doc is not None and app.activeDocument != active_doc:
            active_doc.activate()
        if active_doc is not None:
            if job_plan.active_rename and active_doc.dataFile:
                old = active_doc.dataFile.name
                if old != job_plan.active_rename:
                    active_doc.dataFile.name = job_plan.active_rename
                    dt.note_file_renamed(active_doc.dataFile.id, job_plan.active_rename)
                    report.files_renamed.append(f"{old} -> {job_plan.active_rename}")
                    _log.info("Renamed open file %r -> %r", old, job_plan.active_rename)
            if job_plan.jobs:
                active_doc.updateAllReferences()
                _log.info("Refreshed links in the open design")
                open_design = adsk.fusion.Design.cast(active_doc.products.itemByProductType("DesignProductType"))
                if open_design is not None:
                    _write_cache(open_design.rootComponent, run_cache)
    except Exception as exc:
        _log.exception("Finishing up the open design failed")
        report.failures.append(f"open design: {exc}")
    finally:
        if progress:
            progress.hide()

    _log.info("File updates done in %.1fs: %d saved, %d renamed, %d failed, %d skipped",
              time.time() - started, len(report.files_saved), len(report.files_renamed),
              len(report.failures), len(report.skipped))
    return report


def summary_text(report: RunReport, subsystem_label: str, after_step: bool) -> str:
    lines = [f"Renamed {report.renamed} component(s) in {subsystem_label}."]
    if report.files_saved:
        lines.append(f"Saved a new version of {len(report.files_saved)} linked file(s).")
    if report.files_renamed:
        lines.append("Renamed files:\n  " + "\n  ".join(report.files_renamed[:12]))
        if len(report.files_renamed) > 12:
            lines.append(f"  ...and {len(report.files_renamed) - 12} more (see log)")
    if report.skipped:
        lines.append("Skipped:\n  " + "\n  ".join(report.skipped[:8]))
    if report.failures:
        lines.append(f"{len(report.failures)} problem(s):\n  " + "\n  ".join(report.failures[:10]))
        if len(report.failures) > 10:
            lines.append(f"  ...and {len(report.failures) - 10} more (see log)")
    if after_step:
        lines.append("Changes in this file: press Undo to revert, then Save when you're happy.\n"
                     "Linked files: restore an older version from the Data Panel's version history.")
    else:
        lines.append("Changed your mind? Press Undo once to revert everything.")
    lines.append(f"Log: {gslog.log_file_path()}")
    return "\n\n".join(lines)
