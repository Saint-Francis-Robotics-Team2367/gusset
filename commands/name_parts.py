"""
Name Parts - gives every made part in a subsystem a team part number.

How it works for the student:
  1. Open the subsystem's assembly file and click GUSSET > Name Parts.
     (It numbers the whole open file. To do just one sub-assembly, select it.)
  2. Pick the subsystem code. Gusset fills a preview table.
  3. Fix descriptions, and tick COTS (bought) or Shared (used by more than
     one subsystem) right in the table.
  4. Press Rename.
       - Components modeled in this file change right away (one Undo reverts).
       - Linked part files are opened in the background, updated, saved as a
         new version, and renamed. That happens just after the dialog closes.

Nothing changes until Rename is pressed.
"""

from __future__ import annotations

import os
from typing import Dict, Optional

import adsk.core
import adsk.fusion

from .. import config
from ..lib import design_tree as dt
from ..lib import file_jobs as fj
from ..lib import file_runner as fr
from ..lib import fusion_helpers as fh
from ..lib import log as gslog
from ..lib import naming_core as nc
from ..lib import settings
from ..lib import tip_box

CMD_ID = "Gusset_NameParts"
CMD_NAME = "Name Parts"
CMD_TOOLTIP = ("Give every team-made part in a subsystem a part number (like 27-ELV-104), "
               "including linked part files. Shows a preview first.")
ICON_DIR = os.path.join(config.ADDIN_DIR, "resources", "name_parts")
HANDLER_GROUP = "name_parts_dialog"
AFTER_EVENT_ID = "Gusset_NameParts_UpdateFiles"

_log = gslog.get_logger("name_parts")

# Input ids
ID_SELECT, ID_SUBSYSTEM, ID_KEEP = "gs_select", "gs_subsystem", "gs_keep"
ID_INTRO, ID_TABLE, ID_SUMMARY = "gs_intro", "gs_table", "gs_summary"
ID_QUICK, ID_SCOPE = "gs_quick", "gs_scope"
SCOPE_FOLDER, SCOPE_PROJECT = "This season's folder", "The whole project"
SCOPE_SETTING = {SCOPE_FOLDER: "season folder", SCOPE_PROJECT: "project"}
STATE_KEY = "name_parts"

STATUS_TEXT = {
    nc.STATUS_OK: "OK",
    nc.STATUS_RENAME: "RENAME",
    nc.STATUS_WARN: "NEEDS DESCRIPTION",
    nc.STATUS_COTS: "COTS (kept)",
    nc.STATUS_SKIP: "skipped",
    nc.STATUS_ERROR: "ERROR",
}

# Everything about the open dialog lives here and is reset each time it opens.
_state: Dict[str, object] = {}
# Work handed from the dialog to the after-dialog file step.
_pending: Dict[str, object] = {}
_after_event = None


# ---------------------------------------------------------------------------
# Add-in lifecycle
# ---------------------------------------------------------------------------
def start() -> None:
    global _after_event
    app, _ = fh.app_ui()
    try:
        app.unregisterCustomEvent(AFTER_EVENT_ID)  # left over from a reload
    except Exception:
        pass
    _after_event = app.registerCustomEvent(AFTER_EVENT_ID)
    _after_event.add(fh.make_handler(adsk.core.CustomEventHandler, _on_after_dialog,
                                     "Name Parts: update linked files"))
    fh.add_button(CMD_ID, CMD_NAME, CMD_TOOLTIP, ICON_DIR, _on_created,
                  config.PANEL_NAMING_ID, config.PANEL_NAMING_NAME)


def stop() -> None:
    global _after_event
    fh.remove_button(CMD_ID, config.PANEL_NAMING_ID)
    try:
        app, _ = fh.app_ui()
        app.unregisterCustomEvent(AFTER_EVENT_ID)
    except Exception:
        pass
    _after_event = None


# ---------------------------------------------------------------------------
# Dialog setup
# ---------------------------------------------------------------------------
def _on_created(args: adsk.core.CommandCreatedEventArgs) -> None:
    _log.info("Name Parts opened")
    cmd = args.command
    app, ui = fh.app_ui()

    design = fh.active_design()
    if not design:
        ui.messageBox("Open a Fusion design first, then try Name Parts again.", "Gusset")
        return

    cfg = settings.load_config(config.ADDIN_DIR)
    _state.clear()
    _state.update(
        cfg=cfg, design=design, doc=app.activeDocument, plan=None, overrides={},
        ctx=None, root=None, project_numbers=None,
        scan_project=settings.read_flag(config.ADDIN_DIR, "scan_project", True),
        row_keys={}, cells={}, generation=0, busy=False,
    )

    try:
        cmd.setDialogInitialSize(820, 660)
        cmd.setDialogMinimumSize(600, 440)
    except Exception:
        pass
    cmd.okButtonText = "Rename"

    file_name = fh.safe_text(design.rootComponent.name)
    inputs = cmd.commandInputs
    tip_box.attach(cmd, CMD_ID)              # 'How to use this' + hover tips (0.13)
    inputs.addTextBoxCommandInput(
        ID_INTRO, "",
        f"Season <b>20{cfg.season_year}</b>. Numbering <b>{file_name}</b> (this whole file). "
        "To number only one sub-assembly, select it below. Nothing changes until you press <b>Rename</b>.",
        2, True,
    )

    select = inputs.addSelectionInput(ID_SELECT, "Only this assembly", "Optional: pick one sub-assembly")
    select.addSelectionFilter("Occurrences")
    select.setSelectionLimits(0, 1)
    select.tooltip = "Leave empty to number the whole open file."

    dropdown = inputs.addDropDownCommandInput(ID_SUBSYSTEM, "Subsystem", adsk.core.DropDownStyles.TextListDropDownStyle)
    guess = nc.guess_subsystem(design.rootComponent.name, design.rootComponent.partNumber, cfg)
    codes = [c for c in cfg.subsystems if c != cfg.shared_code] or list(cfg.subsystems)
    for i, code in enumerate(codes):
        dropdown.listItems.add(f"{code} - {cfg.subsystems[code]}", code == guess or (guess is None and i == 0))

    keep = inputs.addBoolValueInput(ID_KEEP, "Keep good existing numbers", True, "", True)
    keep.tooltip = "Leave parts that already have a correct number alone. Untick to renumber everything."

    remembered = settings.load_state(config.ADDIN_DIR).get(STATE_KEY)
    remembered = remembered if isinstance(remembered, dict) else {}
    quick = inputs.addBoolValueInput(ID_QUICK, "Quick rename (file names only)", True, "",
                                     bool(remembered.get("quick", True)))
    quick.tooltip = ("Linked part files are just RENAMED (about half a second each) instead of opened, updated and "
                     "saved (about 8 seconds each). Gusset reads a linked part's number from its file name, so the "
                     "BOM and checks are right either way - but Fusion's own BOM/drawing tables show the old Part "
                     "Number until that file is opened and saved. Untick to update every Part Number too. "
                     "(Parts whose COTS/Shared box you changed are always opened.)")
    default_scope = settings.read_choice(config.ADDIN_DIR, "number_scan_scope", ["season folder", "project"],
                                         "season folder")
    scope_dd = inputs.addDropDownCommandInput(ID_SCOPE, "Check numbers in", adsk.core.DropDownStyles.TextListDropDownStyle)
    wanted = str(remembered.get("scope", SCOPE_FOLDER if default_scope == "season folder" else SCOPE_PROJECT))
    for choice in (SCOPE_FOLDER, SCOPE_PROJECT):
        scope_dd.listItems.add(choice, choice == wanted)
    scope_dd.tooltip = ("Where Gusset looks for part numbers already used, so it never repeats one. 'This season's "
                        "folder' = the top-level folder (just under the project) this file is in - fast. Pick 'The "
                        "whole project' if each season has its own Fusion project (slower on big projects).")

    table = inputs.addTableCommandInput(ID_TABLE, "Preview", 5, "5:6:1:1:3")
    table.maximumVisibleRows = 16
    table.minimumVisibleRows = 6
    try:
        table.tablePresentationStyle = adsk.core.TablePresentationStyles.itemBorderTablePresentationStyle
    except Exception:
        pass

    inputs.addTextBoxCommandInput(ID_SUMMARY, "", "Reading the design...", 3, True)

    for event, base, func, label in (
        (cmd.inputChanged, adsk.core.InputChangedEventHandler, _on_input_changed, "input changed"),
        (cmd.validateInputs, adsk.core.ValidateInputsEventHandler, _on_validate, "validate"),
        (cmd.execute, adsk.core.CommandEventHandler, _on_execute, "Rename"),
        (cmd.destroy, adsk.core.CommandEventHandler, _on_destroy, "close"),
    ):
        event.add(fh.make_handler(base, func, f"Name Parts: {label}", HANDLER_GROUP))

    # Start with a selected sub-assembly if the student picked one first.
    try:
        if ui.activeSelections.count == 1:
            occ = adsk.fusion.Occurrence.cast(ui.activeSelections.item(0).entity)
            if occ and occ.childOccurrences.count > 0:
                select.addSelection(occ)
                _log.debug("Pre-selected %r", occ.name)
                _guess_subsystem(inputs, occ.component)
    except Exception:
        fh.report_error("using the current selection", show_dialog=False)

    _rebuild(inputs, reset_edits=True)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
def _on_input_changed(args: adsk.core.InputChangedEventArgs) -> None:
    if _state.get("busy"):
        return  # we're changing inputs ourselves; ignore the echo
    changed = args.input
    inputs = fh.all_inputs(args)
    cid = changed.id
    _log.debug("Input changed: %s", cid)

    if cid == ID_SELECT:
        occ = _selected_occurrence(inputs)
        _guess_subsystem(inputs, occ.component if occ else _state["design"].rootComponent)  # type: ignore[union-attr]
        _rebuild(inputs, reset_edits=True)
    elif cid in (ID_SUBSYSTEM, ID_KEEP):
        _rebuild(inputs, reset_edits=False)
    elif cid == ID_SCOPE:
        _state["project_numbers"] = None          # scan the newly picked place
        _rebuild(inputs, reset_edits=False)
    elif cid == ID_QUICK:
        _update_summary(inputs, _state.get("plan"))  # type: ignore[arg-type]
    elif cid.startswith(("desc_", "cots_", "shrd_")):
        key = _key_for_cell(cid)
        if key is None:
            return  # event from an old table we already replaced
        override = _state["overrides"].setdefault(key, {})  # type: ignore[union-attr]
        if cid.startswith("desc_"):
            override["description"] = adsk.core.StringValueCommandInput.cast(changed).value
            _replan(inputs, editing_key=key)
        elif cid.startswith("cots_"):
            override["cots"] = adsk.core.BoolValueCommandInput.cast(changed).value
            _log.info("COTS for %s set to %s", key, override["cots"])
            _replan(inputs)
        else:
            override["shared"] = adsk.core.BoolValueCommandInput.cast(changed).value
            _log.info("Shared for %s set to %s", key, override["shared"])
            _replan(inputs)


def _on_validate(args: adsk.core.ValidateInputsEventArgs) -> None:
    plan: Optional[nc.Plan] = _state.get("plan")  # type: ignore[assignment]
    overrides: Dict[str, Dict[str, object]] = _state.get("overrides", {})  # type: ignore[assignment]
    tag_edits = any("cots" in o for o in overrides.values())
    args.areInputsValid = bool(plan and not plan.fatal and (plan.changes() or tag_edits))


def _on_execute(args: adsk.core.CommandEventArgs) -> None:
    plan: Optional[nc.Plan] = _state.get("plan")  # type: ignore[assignment]
    root: Optional[nc.CompNode] = _state.get("root")  # type: ignore[assignment]
    ctx: Optional[dt.TreeContext] = _state.get("ctx")  # type: ignore[assignment]
    _, ui = fh.app_ui()
    if not plan or plan.fatal or root is None or ctx is None:
        _log.warning("Execute pressed without a usable plan")
        return

    job_plan = fj.build_jobs(plan, root, _state.get("overrides", {}))  # type: ignore[arg-type]
    report = fr.RunReport()
    quick = _quick(args.command.commandInputs)
    _remember_choices(args.command.commandInputs)

    # Phase 1: components in this file (inside the command, so Undo works).
    fr.apply_local_edits(job_plan.local_edits, ctx.components, report)
    label = f"{plan.season_year}-{plan.subsystem}"
    _log.info("Local edits done: %d renamed, %d failed", report.renamed, len(report.failures))

    if not job_plan.needs_after_step:
        ui.messageBox(fr.summary_text(report, label, after_step=False), "Gusset - Name Parts")
        return

    # Phase 2 runs after the dialog closes (Fusion can't save files mid-command).
    _pending.clear()
    _pending.update(job_plan=job_plan, files=dict(ctx.files), doc=_state.get("doc"),
                    report=report, label=label, quick=quick)
    app, _ = fh.app_ui()
    _log.info("Handing %d linked file(s) to the after-dialog step", len(job_plan.jobs))
    app.fireCustomEvent(AFTER_EVENT_ID, "")


def _on_after_dialog(args) -> None:
    """Runs just after Name Parts closes: open, update, save and rename linked files."""
    if not _pending:
        _log.debug("After-dialog event with nothing pending")
        return
    job_plan: fj.JobPlan = _pending["job_plan"]  # type: ignore[assignment]
    first: fr.RunReport = _pending["report"]  # type: ignore[assignment]
    label: str = _pending["label"]  # type: ignore[assignment]
    try:
        report = fr.run_file_jobs(job_plan, _pending["files"], _pending["doc"],  # type: ignore[arg-type]
                                  quick=bool(_pending.get("quick")))
        report.renamed += first.renamed
        report.failures = first.failures + report.failures
        _, ui = fh.app_ui()
        ui.messageBox(fr.summary_text(report, label, after_step=True), "Gusset - Name Parts")
    finally:
        _pending.clear()


def _on_destroy(args: adsk.core.CommandEventArgs) -> None:
    _log.info("Name Parts closed")
    _state.clear()
    fh.release_handlers(HANDLER_GROUP)


# ---------------------------------------------------------------------------
# Planning and the preview table
# ---------------------------------------------------------------------------
def _selected_occurrence(inputs):
    select = adsk.core.SelectionCommandInput.cast(inputs.itemById(ID_SELECT))
    if not select or select.selectionCount != 1:
        return None
    return adsk.fusion.Occurrence.cast(select.selection(0).entity)


def _selected_subsystem(inputs) -> str:
    dropdown = adsk.core.DropDownCommandInput.cast(inputs.itemById(ID_SUBSYSTEM))
    item = dropdown.selectedItem if dropdown else None
    return item.name.split(" - ")[0].strip() if item else ""


def _guess_subsystem(inputs, comp) -> None:
    cfg: nc.NamingConfig = _state["cfg"]  # type: ignore[assignment]
    code = nc.guess_subsystem(comp.name, comp.partNumber, cfg)
    if not code:
        _log.debug("No subsystem guess for %r", comp.name)
        return
    dropdown = adsk.core.DropDownCommandInput.cast(inputs.itemById(ID_SUBSYSTEM))
    _state["busy"] = True
    try:
        for i in range(dropdown.listItems.count):
            item = dropdown.listItems.item(i)
            if item.name.startswith(code + " "):
                item.isSelected = True
                _log.info("Guessed subsystem %s for %r", code, comp.name)
                break
    finally:
        _state["busy"] = False


def _read_tree(inputs):
    """Read the target assembly (whole file, or the selected sub-assembly)."""
    cfg: nc.NamingConfig = _state["cfg"]  # type: ignore[assignment]
    design = _state["design"]
    ctx = dt.TreeContext(cfg)
    occ = _selected_occurrence(inputs)
    if occ:
        root = dt.node_from_occurrence(occ, ctx, dt.owner_of_occurrence(occ, ctx))
        whole = dt.root_node(design, dt.TreeContext(cfg))  # numbers outside the selection
    else:
        root = dt.root_node(design, ctx)
        whole = None
    dt.fill_parent_files([root], ctx, cfg)
    return root, ctx, whole


def _compute_plan(inputs) -> Optional[nc.Plan]:
    cfg: nc.NamingConfig = _state["cfg"]  # type: ignore[assignment]
    subsystem = _selected_subsystem(inputs)
    keep = adsk.core.BoolValueCommandInput.cast(inputs.itemById(ID_KEEP)).value

    if _state.get("root") is None:
        root, ctx, whole = _read_tree(inputs)
        _state.update(root=root, ctx=ctx, whole=whole)
    root: nc.CompNode = _state["root"]  # type: ignore[assignment]
    ctx: dt.TreeContext = _state["ctx"]  # type: ignore[assignment]
    whole = _state.get("whole")

    run_keys = {n.key for n in dt.flatten([root])}
    run_files = {n.file_id for n in dt.flatten([root]) if n.file_id}
    used_local = dt.numbers_in_use([whole], run_keys, cfg.season_year) if whole else {}

    design = _state.get("design")
    if design is None:
        raise RuntimeError("Name Parts lost its design (the dialog was closed mid-way) - open it again.")
    if _state.get("scan_project") and _state.get("project_numbers") is None:
        scope = SCOPE_SETTING.get(_choice_text(inputs, ID_SCOPE), "season folder")
        _set_summary(inputs, f"Checking file names in {'the whole project' if scope == 'project' else 'this season' + chr(39) + 's folder'} "
                             "so numbers never repeat (remembered for an hour)...")
        _state["project_numbers"] = dt.scan_project_numbers(design, cfg.season_year, scope=scope)
    used_project = {}
    for file_id, (sub, num) in (_state.get("project_numbers") or {}).items():  # type: ignore[union-attr]
        if file_id not in run_files:
            used_project.setdefault(sub, set()).add(num)

    used = dt.merge_used(used_local, used_project)
    _log.debug("Numbers used elsewhere: %s", {k: sorted(v) for k, v in used.items()})
    return nc.plan_subsystem(root, subsystem, cfg, used, keep, _state["overrides"])  # type: ignore[arg-type]


def _rebuild(inputs, reset_edits: bool = False) -> None:
    """Selection, subsystem or 'keep' changed: rebuild the whole table."""
    if reset_edits:
        _state["overrides"] = {}  # edits made for a different assembly don't apply
        _state["root"] = None     # re-read the tree for the new target
    plan = _compute_plan(inputs)
    _state["plan"] = plan
    _fill_table(inputs, plan)
    _update_summary(inputs, plan)


def _replan(inputs, editing_key: Optional[str] = None) -> None:
    """A description, COTS or Shared box changed: same rows, so just update the cells."""
    plan = _compute_plan(inputs)
    _state["plan"] = plan
    _refresh_cells(plan, skip_description_for=editing_key)
    _update_summary(inputs, plan)


def _fill_table(inputs, plan: Optional[nc.Plan]) -> None:
    table = adsk.core.TableCommandInput.cast(inputs.itemById(ID_TABLE))
    _state["busy"] = True
    try:
        table.clear()
        # New ids every rebuild so they never collide with deleted inputs.
        gen = int(_state["generation"]) + 1  # type: ignore[arg-type]
        _state["generation"] = gen
        _state["row_keys"], _state["cells"] = {}, {}
        if not plan:
            return

        cells_in = table.commandInputs
        for col, title in enumerate(("Part #", "Description", "COTS", "Shared", "Status")):
            header = cells_in.addTextBoxCommandInput(f"hdr_{gen}_{col}", "", f"<b>{title}</b>", 1, True)
            table.addCommandInput(header, 0, col)

        for row, p in enumerate(plan.proposals, start=1):
            pn = cells_in.addTextBoxCommandInput(f"pn_{gen}_{row}", "", "", 1, True)
            desc = cells_in.addStringValueInput(f"desc_{gen}_{row}", "", "")
            cots = cells_in.addBoolValueInput(f"cots_{gen}_{row}", "", True, "", False)
            shared = cells_in.addBoolValueInput(f"shrd_{gen}_{row}", "", True, "", False)
            status = cells_in.addTextBoxCommandInput(f"st_{gen}_{row}", "", "", 1, True)
            for col, cell in enumerate((pn, desc, cots, shared, status)):
                table.addCommandInput(cell, row, col)
            _state["row_keys"][f"{gen}_{row}"] = p.key  # type: ignore[index]
            _state["cells"][p.key] = {"pn": pn, "desc": desc, "cots": cots, "shared": shared, "status": status}  # type: ignore[index]
        _log.debug("Table built with %d rows (generation %d)", len(plan.proposals), gen)
    finally:
        _state["busy"] = False
    _refresh_cells(plan)


def _refresh_cells(plan: Optional[nc.Plan], skip_description_for: Optional[str] = None) -> None:
    if not plan:
        return
    cfg: nc.NamingConfig = _state["cfg"]  # type: ignore[assignment]
    cells: Dict[str, Dict[str, object]] = _state["cells"]  # type: ignore[assignment]
    _state["busy"] = True
    try:
        for p in plan.proposals:
            c = cells.get(p.key)
            if not c:
                continue
            # Plain characters only: Fusion shows HTML codes like &nbsp; as raw text.
            # Non-breaking spaces (\u00a0) keep the indent from being trimmed.
            indent = ("\u00a0\u00a0" * (p.depth - 1) + "\u2514\u00a0") if p.depth else ""   # "└ "
            marker = "\u25b8\u00a0" if p.kind == nc.KIND_ASSEMBLY else ""                     # "▸ "
            file_mark = "\u00a0\U0001F517" if p.owner_file and p.file_id else ""              # " 🔗" linked file
            shown_pn = p.part_number or ("(vendor)" if p.kind == nc.KIND_COTS else "-")
            c["pn"].text = f"{indent}{marker}{shown_pn}{file_mark}"
            where = "Linked file: renamed and saved as a new version" if p.owner_file else "In this file"
            c["pn"].tooltip = f"Now: {p.old_name}\nWill be: {p.new_name}\n{where}"

            numbered = p.kind in (nc.KIND_ASSEMBLY, nc.KIND_PART)
            if p.key != skip_description_for:
                c["desc"].value = p.description
            c["desc"].isEnabled = numbered
            c["desc"].tooltip = "Type a short description, e.g. 'Gusset Plate'" if numbered else p.old_name

            # The top row is always the team's; skipped rows have nothing to toggle.
            c["cots"].value = p.kind == nc.KIND_COTS
            c["cots"].isEnabled = p.depth > 0 and p.kind != nc.KIND_SKIP
            c["cots"].tooltip = "Tick if this part is bought, not made. It keeps its vendor number."

            c["shared"].value = p.shared
            c["shared"].isEnabled = bool(cfg.shared_code) and p.depth > 0 and numbered
            c["shared"].tooltip = (f"Tick if another subsystem uses this part too. "
                                   f"It gets a {cfg.shared_code} number." if cfg.shared_code
                                   else "Shared parts are turned off in Settings.")

            label = STATUS_TEXT.get(p.status, p.status)
            if p.status == nc.STATUS_RENAME and p.owner_file:
                label = "RENAME FILE"
            c["status"].text = label
            c["status"].tooltip = p.message or label
    finally:
        _state["busy"] = False


def _choice_text(inputs, input_id: str) -> str:
    dd = adsk.core.DropDownCommandInput.cast(inputs.itemById(input_id))
    item = dd.selectedItem if dd else None
    return item.name if item else ""


def _quick(inputs) -> bool:
    box = adsk.core.BoolValueCommandInput.cast(inputs.itemById(ID_QUICK))
    return bool(box.value) if box else False


def _remember_choices(inputs) -> None:
    try:
        settings.save_state(config.ADDIN_DIR, **{STATE_KEY: {"quick": _quick(inputs),
                                                              "scope": _choice_text(inputs, ID_SCOPE)}})
    except Exception as exc:
        _log.debug("Couldn't remember Name Parts choices: %s", exc)


def _set_summary(inputs, text: str) -> None:
    box = adsk.core.TextBoxCommandInput.cast(inputs.itemById(ID_SUMMARY))
    if box:
        box.formattedText = text
    # No adsk.doEvents() here: it let a closing Name Parts dialog's events run in
    # the middle of opening a new one and wipe its state ("KeyError: 'design'").


def _update_summary(inputs, plan: Optional[nc.Plan]) -> None:
    if not plan:
        _set_summary(inputs, "Nothing to show yet.")
        return
    if plan.fatal:
        _set_summary(inputs, f"<b>Can't continue:</b> {fh.safe_text(plan.fatal)}")
        return
    counts = plan.summary()
    files = len(plan.files_to_save())
    parts = [
        f"<b>{len(plan.changes())}</b> to rename",
        f"{counts.get(nc.STATUS_OK, 0)} already OK",
        f"{counts.get(nc.STATUS_COTS, 0)} COTS",
    ]
    shared = sum(1 for p in plan.proposals if p.shared)
    if shared:
        parts.append(f"{shared} shared")
    if counts.get(nc.STATUS_WARN):
        parts.append(f"<b>{counts[nc.STATUS_WARN]}</b> need a description")
    if counts.get(nc.STATUS_ERROR):
        parts.append(f"<b>{counts[nc.STATUS_ERROR]}</b> errors (hover the status for details)")
    text = " \u00b7 ".join(parts)
    if files:
        if _quick(inputs):
            seconds = files * 0.5 + 8 * _opened_estimate()
            text += (f"<br>\U0001F517 <b>{files} linked file(s)</b> will be renamed (quick: about {seconds:.0f} s). "
                     "Undo won't reach those; rename them back in the Data Panel if needed.")
        else:
            text += (f"<br>\U0001F517 <b>{files} linked file(s)</b> will be saved as a new version and renamed "
                     f"(about {files * 8} s). Undo won't reach those; use Version History instead.")
    _set_summary(inputs, text)


def _opened_estimate() -> int:
    """How many linked files quick mode still has to open (COTS/Shared changes)."""
    overrides = _state.get("overrides", {}) or {}
    return sum(1 for o in overrides.values() if "cots" in o or "shared" in o)  # type: ignore[union-attr]


def _key_for_cell(cell_id: str) -> Optional[str]:
    """'desc_3_12' -> component key for row 12 of table generation 3."""
    try:
        _, gen, row = cell_id.split("_", 2)
    except ValueError:
        return None
    if int(gen) != _state.get("generation"):
        return None
    return _state["row_keys"].get(f"{gen}_{row}")  # type: ignore[union-attr]
