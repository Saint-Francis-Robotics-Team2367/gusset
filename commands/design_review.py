"""
Design Review - automatic checks + a mentor checklist + sign-off, for the open assembly.

  1. Open the assembly being reviewed, click GUSSET > Design Review.
  2. Read the automatic checks. Each one says why it matters and how to fix it.
     (Tick "Check for overlapping parts" for the slower interference check.)
  3. The mentor ticks the checklist items that are true, picks a decision and
     adds notes (use initials for students).
  4. Press Sign Off: the review is saved in the assembly (save it afterwards)
     and a PDF report is written.

The checklist is editable in gusset_config.json ("review_checklist").
"""

from __future__ import annotations

import datetime
import os
import subprocess
import sys
import time
from typing import Dict, List, Optional, Tuple

import adsk.core
import adsk.fusion

from .. import config
from ..lib import bom_core as bc
from ..lib import design_tree as dt
from ..lib import fusion_helpers as fh
from ..lib import log as gslog
from ..lib import naming_core as nc
from ..lib import review_core as rc
from ..lib import settings
from ..lib import tip_box

CMD_ID = "Gusset_DesignReview"
CMD_NAME = "Design Review"
CMD_TOOLTIP = "Automatic design checks + mentor checklist and sign-off, with a PDF report."
ICON_DIR = os.path.join(config.ADDIN_DIR, "resources", "design_review")
HANDLER_GROUP = "design_review_dialog"

_log = gslog.get_logger("design_review")

ID_INTRO, ID_AUTO, ID_OVERLAP, ID_TABLE = "dr_intro", "dr_auto", "dr_overlap", "dr_table"
ID_REVIEWER, ID_DECISION, ID_NOTES, ID_HISTORY = "dr_reviewer", "dr_decision", "dr_notes", "dr_history"

_state: Dict[str, object] = {}


def start() -> None:
    fh.add_button(CMD_ID, CMD_NAME, CMD_TOOLTIP, ICON_DIR, _on_created, config.PANEL_REVIEW_ID, config.PANEL_REVIEW_NAME)


def stop() -> None:
    fh.remove_button(CMD_ID, config.PANEL_REVIEW_ID)


def _out_of_date(doc) -> List[str]:
    names = []
    try:
        refs = doc.documentReferences
        for i in range(refs.count):
            ref = refs.item(i)
            if ref.isOutOfDate:
                names.append(ref.dataFile.name)
    except Exception as exc:
        _log.warning("Couldn't check links (%s)", exc)
    return names


def _interference(design) -> List[Tuple[str, str]]:
    """Pairs of overlapping parts (top-level occurrences and loose bodies)."""
    started = time.time()
    root = design.rootComponent
    entities = adsk.core.ObjectCollection.create()
    for i in range(root.occurrences.count):
        entities.add(root.occurrences.item(i))
    for i in range(root.bRepBodies.count):
        entities.add(root.bRepBodies.item(i))
    if entities.count < 2:
        return []
    interference_input = design.createInterferenceInput(entities)
    interference_input.areCoincidentFacesIncluded = False
    results = design.analyzeInterference(interference_input)

    def label(entity) -> str:
        body = adsk.fusion.BRepBody.cast(entity)
        occ = body.assemblyContext if body else adsk.fusion.Occurrence.cast(entity)
        name = occ.component.name if occ else (body.name if body else "?")
        return nc.strip_fusion_suffixes(name)

    pairs = sorted({tuple(sorted((label(r.entityOne), label(r.entityTwo)))) for r in results})
    _log.info("Interference: %d pair(s) in %.1fs", len(pairs), time.time() - started)
    return [p for p in pairs if p[0] != p[1]]


def _on_created(args: adsk.core.CommandCreatedEventArgs) -> None:
    _log.info("Design Review opened")
    cmd = args.command
    app, ui = fh.app_ui()
    design = fh.active_design()
    if not design:
        ui.messageBox("Open the assembly you're reviewing, then try again.", "Gusset")
        return
    cfg = settings.load_config(config.ADDIN_DIR)
    ctx = dt.TreeContext(cfg)
    root = dt.root_node(design, ctx)
    dt.fill_bom_info(root, ctx, cfg)
    bom = bc.build_bom(root, cfg, fab_log=dt.read_fab_logs(root, ctx))
    out_of_date = _out_of_date(app.activeDocument)
    checklist = settings.read_review_checklist(config.ADDIN_DIR)
    title = nc.strip_fusion_suffixes(root.name)
    history = rc.parse_records(dt.read_text_attr(design.rootComponent, rc.REVIEW_ATTR))
    _state.clear()
    _state.update(cfg=cfg, root=root, bom=bom, design=design, out_of_date=out_of_date, title=title,
                  checklist=checklist, interference=None, history=history, boxes={})
    _state["results"] = rc.auto_checks(root, cfg, bom, out_of_date, None, _library())

    try:
        cmd.setDialogInitialSize(760, 760)
    except Exception:
        pass
    cmd.okButtonText = "Sign Off"
    inputs = cmd.commandInputs
    tip_box.attach(cmd, CMD_ID)              # 'How to use this' + hover tips (0.13)
    inputs.addTextBoxCommandInput(
        ID_INTRO, "",
        f"Reviewing <b>{fh.safe_text(title)}</b>. Fix what you can from the checks, then a mentor ticks the "
        "checklist and signs off. Hover any checklist item for why it matters.", 2, True)
    inputs.addTextBoxCommandInput(ID_AUTO, "Automatic checks", "", 14, True)
    inputs.addBoolValueInput(ID_OVERLAP, "Check for overlapping parts (slower)", True, "", False)

    table = inputs.addTableCommandInput(ID_TABLE, "Mentor checklist", 2, "1:14")
    table.maximumVisibleRows = 12
    table.minimumVisibleRows = 6
    last = history[-1] if history else None
    for row, (item, why) in enumerate(checklist):
        box = table.commandInputs.addBoolValueInput(f"dr_cb_{row}", "", True, "", bool(last and last.checklist.get(item)))
        box.tooltip = why
        text = table.commandInputs.addTextBoxCommandInput(f"dr_tx_{row}", "", "", 1, True)
        text.text = item
        text.tooltip = why
        table.addCommandInput(box, row, 0)
        table.addCommandInput(text, row, 1)
        _state["boxes"][item] = box  # type: ignore[index]

    reviewer = inputs.addStringValueInput(ID_REVIEWER, "Reviewed by (mentor)", last.reviewer if last else "")
    reviewer.tooltip = "Mentor's name or initials"
    decision = inputs.addDropDownCommandInput(ID_DECISION, "Decision", adsk.core.DropDownStyles.TextListDropDownStyle)
    for i, d in enumerate(rc.DECISIONS):
        decision.listItems.add(d, i == 0)
    notes = inputs.addTextBoxCommandInput(ID_NOTES, "Notes", "", 4, False)
    notes.tooltip = "What to fix before the next review. Please use initials, not students' full names."
    hist_text = "No earlier reviews of this assembly." if not history else "<br>".join(
        f"{fh.safe_text(r.date)}: <b>{fh.safe_text(r.decision)}</b> ({fh.safe_text(r.reviewer or '-')})"
        for r in history[-4:])
    inputs.addTextBoxCommandInput(ID_HISTORY, "Earlier reviews", hist_text, 3, True)

    for event, base, func, label in (
        (cmd.inputChanged, adsk.core.InputChangedEventHandler, _on_input_changed, "input changed"),
        (cmd.validateInputs, adsk.core.ValidateInputsEventHandler, _on_validate, "validate"),
        (cmd.execute, adsk.core.CommandEventHandler, _on_execute, "Sign Off"),
        (cmd.destroy, adsk.core.CommandEventHandler, _on_destroy, "close"),
    ):
        event.add(fh.make_handler(base, func, f"Design Review: {label}", HANDLER_GROUP))
    _show_results(inputs)


def _library():
    """The COTS panel's catalog (cached - no cloud calls), for the 'from the COTS Library' check."""
    try:
        from . import cots_browser
        return cots_browser.catalog()
    except Exception as exc:
        _log.debug("No COTS catalog for the review: %s", exc)
        return []


def _show_results(inputs) -> None:
    results: List[rc.CheckResult] = _state["results"]  # type: ignore[assignment]
    lines = []
    for r in results:
        # Plain-word badges: Fusion's text boxes don't reliably draw emoji or HTML codes.
        lines.append(f"<b>[{r.status}]</b> <b>{fh.safe_text(r.title)}</b> — {fh.safe_text(r.summary)}")
        if r.status in (rc.FAIL, rc.WARN) or (r.status == rc.INFO and not r.items):
            lines.append(f"\u00a0\u00a0\u00a0\u00a0<i>Why:</i> {fh.safe_text(r.why)} <i>Fix:</i> {fh.safe_text(r.fix)}")
            if r.items:
                shown = ", ".join(r.items[:6]) + (f" (+{len(r.items) - 6} more)" if len(r.items) > 6 else "")
                lines.append(f"\u00a0\u00a0\u00a0\u00a0{fh.safe_text(shown)}")
    adsk.core.TextBoxCommandInput.cast(inputs.itemById(ID_AUTO)).formattedText = "<br>".join(lines)


def _on_input_changed(args: adsk.core.InputChangedEventArgs) -> None:
    if args.input.id != ID_OVERLAP:
        return
    if adsk.core.BoolValueCommandInput.cast(args.input).value and _state.get("interference") is None:
        box = adsk.core.TextBoxCommandInput.cast(fh.all_inputs(args).itemById(ID_AUTO))
        box.formattedText = "Checking for overlapping parts... (this can take a minute on a big robot)"
        adsk.doEvents()
        try:
            _state["interference"] = _interference(_state["design"])
        except Exception as exc:
            _log.warning("Interference check failed (%s)", exc)
            _state["interference"] = None
    interference = _state["interference"] if adsk.core.BoolValueCommandInput.cast(args.input).value else None
    _state["results"] = rc.auto_checks(_state["root"], _state["cfg"], _state["bom"],  # type: ignore[arg-type]
                                       _state["out_of_date"], interference, _library())  # type: ignore[arg-type]
    _show_results(fh.all_inputs(args))


def _on_validate(args: adsk.core.ValidateInputsEventArgs) -> None:
    args.areInputsValid = bool(adsk.core.StringValueCommandInput.cast(fh.all_inputs(args).itemById(ID_REVIEWER)).value.strip())


def _on_execute(args: adsk.core.CommandEventArgs) -> None:
    _, ui = fh.app_ui()
    inputs = args.command.commandInputs
    checklist: List[Tuple[str, str]] = _state["checklist"]  # type: ignore[assignment]
    answers = {item: adsk.core.BoolValueCommandInput.cast(box).value
               for item, box in _state["boxes"].items()}  # type: ignore[union-attr]
    record = rc.new_record(
        assembly=str(_state["title"]),
        reviewer=adsk.core.StringValueCommandInput.cast(inputs.itemById(ID_REVIEWER)).value,
        decision=adsk.core.DropDownCommandInput.cast(inputs.itemById(ID_DECISION)).selectedItem.name,
        notes=adsk.core.TextBoxCommandInput.cast(inputs.itemById(ID_NOTES)).text,
        results=_state["results"], checklist=answers, version=config.VERSION)  # type: ignore[arg-type]

    root_comp = _state["design"].rootComponent  # type: ignore[union-attr]
    dt.write_attr(root_comp, rc.REVIEW_ATTR, rc.add_record(dt.read_text_attr(root_comp, rc.REVIEW_ATTR), record))

    folder = settings.load_state(config.ADDIN_DIR).get("review_folder", "")
    if not folder or not os.path.isdir(folder):
        folder = os.path.join(os.path.expanduser("~"), "Documents")
    name = nc.sanitize(f"{record.assembly} design review {record.date}") + ".pdf"
    path = os.path.join(folder, name)
    try:
        rc.render_report(path, record, _state["results"], checklist)  # type: ignore[arg-type]
        settings.save_state(config.ADDIN_DIR, review_folder=folder)
        _open(path)
        where = f"Report: {path}"
    except Exception as exc:
        _log.exception("Report failed")
        where = f"The review was saved, but the PDF report failed: {exc}"
    unchecked = sum(1 for v in answers.values() if not v)
    ui.messageBox(f"Signed off: {record.decision}\n\n{where}\n\n"
                  + (f"{unchecked} checklist item(s) not ticked.\n\n" if unchecked else "")
                  + "Save the assembly to keep the review record with it.", "Gusset - Design Review")


def _open(path: str) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
    except Exception as exc:
        _log.warning("Couldn't open %s (%s)", path, exc)


def _on_destroy(args: adsk.core.CommandEventArgs) -> None:
    _state.clear()
    fh.release_handlers(HANDLER_GROUP)
