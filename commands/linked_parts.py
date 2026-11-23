"""
linked_parts - the after-dialog step shared by Tube and Shaft & Spacer.

Fusion can't save files while a command is running, so when a student presses
OK with "Create as: Linked part files", the command only works out WHAT to make
and WHERE it goes (PartRequests), then fires this custom event. Right after the
dialog closes, this makes/reuses the part files in the "[Assembly] Parts" folder
and inserts them (lib/part_files.py), then shows a summary.

Not a button - it only registers the event (start/stop like the other tools).
"""

from __future__ import annotations

from typing import Dict, List, Optional

import adsk.core

from ..lib import feature_builder as fb
from ..lib import fusion_helpers as fh
from ..lib import log as gslog
from ..lib import part_files as pfl
from ..lib import part_files_core as pf

EVENT_ID = "Gusset_LinkedParts_Make"
LINKED = "Linked part files (in the Parts folder)"
BODIES = "Bodies in this file"

_log = gslog.get_logger("linked_parts")
_event = None
_pending: List[dict] = []
busy = False            # True while part files are being made - cots_autoplace waits for this


def start() -> None:
    global _event
    app, _ = fh.app_ui()
    try:
        app.unregisterCustomEvent(EVENT_ID)     # left over from a reload
    except Exception:
        pass
    _event = app.registerCustomEvent(EVENT_ID)
    _event.add(fh.make_handler(adsk.core.CustomEventHandler, _on_event, "Linked parts: make files"))


def stop() -> None:
    global _event
    try:
        app, _ = fh.app_ui()
        app.unregisterCustomEvent(EVENT_ID)
    except Exception:
        pass
    _event = None
    _pending.clear()


def assembly_label(doc) -> str:
    """'Linked part files in "<name> Parts"' for the dropdown, or a hint to save first."""
    data_file = getattr(doc, "dataFile", None) if doc else None
    if data_file is None:
        return "save this file first"
    return f'"{pf.parts_folder_name(data_file.name)}"'


def check_ready(doc) -> None:
    if doc is None or doc.dataFile is None:
        raise fb.FeatureError("Save this assembly first - Gusset puts the new part files in a "
                              "'[Assembly] Parts' folder next to it. (Or pick 'Bodies in this file'.)")


def queue(doc, comp, requests: List[pf.PartRequest], label: str, materials: Optional[Dict[str, str]] = None) -> None:
    """Hand work to the after-dialog step (call from a command's execute handler)."""
    if not requests:
        return
    _pending.append({"doc": doc, "comp": comp, "requests": requests, "label": label, "materials": materials or {}})
    _log.info("%s: queued %d part(s) for the after-dialog step", label, len(requests))
    # Fusion may say 'refused' from inside a dialog and deliver it anyway - keep nudging until it runs.
    fh.fire_until_handled(EVENT_ID, lambda: bool(_pending), f"{label} part files")


def _on_event(args) -> None:
    if not _pending:
        _log.debug("Linked-parts event with nothing pending")
        return
    global busy
    if busy or fh.fusion_is_idle():          # already running, or the dialog hasn't closed yet: wait
        return
    _, ui = fh.app_ui()
    jobs = list(_pending)
    _pending.clear()
    busy = True
    try:
        _run_jobs(jobs, ui)
    finally:
        busy = False


def _run_jobs(jobs, ui) -> None:
    for job in jobs:
        try:
            report = pfl.run_requests(job["doc"], job["comp"], job["requests"], materials=job["materials"])
            _log.info("%s: %s", job["label"], report.text().replace("\n", " | "))
            ui.messageBox(report.text(), f"Gusset - {job['label']}")
        except fb.FeatureError as exc:
            ui.messageBox(str(exc), f"Gusset - {job['label']}")
        except Exception:
            fh.report_error(f"{job['label']}: making part files")
