"""
Export BOM - writes the open assembly's Bill of Materials to an Excel file
that imports straight into monday.com.

How it works for the student:
  1. Open an assembly and click GUSSET > Export BOM.
  2. Set the Process (X-Carve, 3D Print, Lathe, ...) for each made part.
     Choices are saved ON the part, so next time they're already filled in.
  3. Pick a folder and press Export.

The Excel file has two tabs:
  BOM (monday) - one row per part, TOTAL quantity. monday imports only the
                 first tab, so this one is first.
  Indented     - mirrors the assembly tree, for build instructions.

Saving processes: parts modeled in the open file are tagged right away;
linked part files get a new saved version ("Gusset: part info") just after
the dialog closes (Fusion can't save files during a command).
"""

from __future__ import annotations

import datetime
import os
import subprocess
import sys
from typing import Dict, List, Optional

import adsk.core
import adsk.fusion

from .. import config
from ..lib import bom_core as bc
from ..lib import design_tree as dt
from ..lib import file_jobs as fj
from ..lib import file_runner as fr
from ..lib import fusion_helpers as fh
from ..lib import log as gslog
from ..lib import naming_core as nc
from ..lib import settings
from ..lib import xlsx_writer as xw
from ..lib import tip_box

CMD_ID = "Gusset_ExportBom"
CMD_NAME = "Export BOM"
CMD_TOOLTIP = ("Export a Bill of Materials (Excel, ready for monday.com) with total quantities, "
               "process, material, mass and vendor info.")
ICON_DIR = os.path.join(config.ADDIN_DIR, "resources", "export_bom")
HANDLER_GROUP = "export_bom_dialog"
AFTER_EVENT_ID = "Gusset_ExportBom_SaveProcesses"

_log = gslog.get_logger("export_bom")

ID_INTRO, ID_FOLDER, ID_PICK, ID_FILE = "gb_intro", "gb_folder", "gb_pick", "gb_file"
ID_BULK, ID_OPEN, ID_TABLE, ID_SUMMARY = "gb_bulk", "gb_open", "gb_table", "gb_summary"
BULK_NONE = "(choose a process)"

_state: Dict[str, object] = {}
_pending: Dict[str, object] = {}
_after_event = None


# ---------------------------------------------------------------------------
# Add-in lifecycle
# ---------------------------------------------------------------------------
def start() -> None:
    global _after_event
    app, _ = fh.app_ui()
    try:
        app.unregisterCustomEvent(AFTER_EVENT_ID)
    except Exception:
        pass
    _after_event = app.registerCustomEvent(AFTER_EVENT_ID)
    _after_event.add(fh.make_handler(adsk.core.CustomEventHandler, _on_after_dialog,
                                     "Export BOM: save processes to linked files"))
    fh.add_button(CMD_ID, CMD_NAME, CMD_TOOLTIP, ICON_DIR, _on_created,
                  config.PANEL_BOM_ID, config.PANEL_BOM_NAME)


def stop() -> None:
    global _after_event
    fh.remove_button(CMD_ID, config.PANEL_BOM_ID)
    try:
        app, _ = fh.app_ui()
        app.unregisterCustomEvent(AFTER_EVENT_ID)
    except Exception:
        pass
    _after_event = None


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------
def _default_folder() -> str:
    remembered = settings.load_state(config.ADDIN_DIR).get("bom_folder", "")
    if remembered and os.path.isdir(remembered):
        return remembered
    documents = os.path.join(os.path.expanduser("~"), "Documents")
    return documents if os.path.isdir(documents) else os.path.expanduser("~")


def _default_file_name(title: str) -> str:
    stamp = datetime.date.today().isoformat()
    return nc.sanitize(f"{title} BOM {stamp}") + ".xlsx"


def _on_created(args: adsk.core.CommandCreatedEventArgs) -> None:
    _log.info("Export BOM opened")
    cmd = args.command
    app, ui = fh.app_ui()
    design = fh.active_design()
    if not design:
        ui.messageBox("Open a Fusion design first, then try Export BOM again.", "Gusset")
        return

    cfg = settings.load_config(config.ADDIN_DIR)
    processes = settings.read_processes(config.ADDIN_DIR)

    # Read the design once. Material/mass come from Fusion's physical properties.
    ctx = dt.TreeContext(cfg)
    root = dt.root_node(design, ctx)
    dt.fill_bom_info(root, ctx, cfg)
    fab_log = dt.read_fab_logs(root, ctx)       # parts already exported -> "Ready to Cut"
    title = nc.strip_fusion_suffixes(root.name)

    _state.clear()
    _state.update(cfg=cfg, design=design, doc=app.activeDocument, ctx=ctx, root=root,
                  processes=processes, chosen={}, row_keys={}, cells={}, busy=False, title=title, generation=0,
                  fab_log=fab_log)

    try:
        cmd.setDialogInitialSize(820, 680)
        cmd.setDialogMinimumSize(600, 460)
    except Exception:
        pass
    cmd.okButtonText = "Export"

    inputs = cmd.commandInputs
    tip_box.attach(cmd, CMD_ID)              # 'How to use this' + hover tips (0.13)
    inputs.addTextBoxCommandInput(
        ID_INTRO, "",
        f"BOM for <b>{fh.safe_text(title)}</b>. Set the <b>Process</b> for each made part "
        "(saved on the part for next time), then press <b>Export</b>.", 2, True)

    folder_box = inputs.addTextBoxCommandInput(ID_FOLDER, "Folder", fh.safe_text(_default_folder()), 1, True)
    folder_box.tooltip = "Where the Excel file is saved"
    _state["folder"] = _default_folder()
    inputs.addBoolValueInput(ID_PICK, "", False, "", False).text = "Choose folder..."
    inputs.addStringValueInput(ID_FILE, "File name", _default_file_name(title))
    inputs.addBoolValueInput(ID_OPEN, "Open when done", True, "", True)

    bulk = inputs.addDropDownCommandInput(ID_BULK, "Set all TBD parts to",
                                          adsk.core.DropDownStyles.TextListDropDownStyle)
    bulk.listItems.add(BULK_NONE, True)
    for choice in processes:
        if choice != bc.PROCESS_TBD:
            bulk.listItems.add(choice, False)

    table = inputs.addTableCommandInput(ID_TABLE, "Made parts", 6, "5:6:1:3:4:3")
    table.maximumVisibleRows = 16
    table.minimumVisibleRows = 6
    try:
        table.tablePresentationStyle = adsk.core.TablePresentationStyles.itemBorderTablePresentationStyle
    except Exception:
        pass
    inputs.addTextBoxCommandInput(ID_SUMMARY, "", "", 4, True)

    for event, base, func, label in (
        (cmd.inputChanged, adsk.core.InputChangedEventHandler, _on_input_changed, "input changed"),
        (cmd.validateInputs, adsk.core.ValidateInputsEventHandler, _on_validate, "validate"),
        (cmd.execute, adsk.core.CommandEventHandler, _on_execute, "Export"),
        (cmd.destroy, adsk.core.CommandEventHandler, _on_destroy, "close"),
    ):
        event.add(fh.make_handler(base, func, f"Export BOM: {label}", HANDLER_GROUP))

    _fill_table(inputs)
    _update_summary(inputs)


def _bom() -> bc.Bom:
    return bc.build_bom(_state["root"], _state["cfg"], processes=_state["chosen"],  # type: ignore[arg-type]
                        title=_state["title"], fab_log=_state.get("fab_log"))  # type: ignore[arg-type]


def _fill_table(inputs) -> None:
    table = adsk.core.TableCommandInput.cast(inputs.itemById(ID_TABLE))
    processes: List[str] = _state["processes"]  # type: ignore[assignment]
    bom = _bom()
    made = [r for r in bom.flat if r.type == bc.TYPE_MADE]
    _state["busy"] = True
    try:
        table.clear()
        # Fresh ids on every rebuild so they never collide with deleted inputs.
        gen = int(_state["generation"]) + 1  # type: ignore[arg-type]
        _state["generation"] = gen
        _state["row_keys"], _state["cells"] = {}, {}
        cells_in = table.commandInputs
        for col, title in enumerate(("Part #", "Description", "Qty", "Process", "Material / Mass", "Status")):
            header = cells_in.addTextBoxCommandInput(f"bh_{gen}_{col}", "", f"<b>{title}</b>", 1, True)
            table.addCommandInput(header, 0, col)
        for row, r in enumerate(made, start=1):
            pn = cells_in.addTextBoxCommandInput(f"bpn_{gen}_{row}", "", "", 1, True)
            pn.text = r.part_number or "(no number)"
            pn.tooltip = r.notes or r.name
            desc = cells_in.addTextBoxCommandInput(f"bds_{gen}_{row}", "", "", 1, True)
            desc.text = r.description
            qty = cells_in.addTextBoxCommandInput(f"bqt_{gen}_{row}", "", "", 1, True)
            qty.text = str(r.qty)
            proc = cells_in.addDropDownCommandInput(f"bpr_{gen}_{row}", "", adsk.core.DropDownStyles.TextListDropDownStyle)
            choices = processes if r.process in processes else processes + [r.process]
            for choice in choices:
                proc.listItems.add(choice, choice == r.process)
            info = cells_in.addTextBoxCommandInput(f"bmt_{gen}_{row}", "", "", 1, True)
            mass = f"{r.mass_lb:.3f} lb" if r.mass_lb is not None else "mass ?"
            info.text = f"{r.material or 'no material'} · {mass}"
            status = cells_in.addTextBoxCommandInput(f"bst_{gen}_{row}", "", "", 1, True)
            status.text = r.status            # "Ready to Cut" / "Ready to Print" once Fab Export made its file
            entry = (_state.get("fab_log") or {}).get(r.part_number)  # type: ignore[union-attr]
            status.tooltip = (f"Exported {entry.get('date', '')}: {entry.get('file', '')}" if entry
                              else "Not exported yet (Fab Export or Export Face sets this)")
            for col, cell in enumerate((pn, desc, qty, proc, info, status)):
                table.addCommandInput(cell, row, col)
            _state["row_keys"][f"bpr_{gen}_{row}"] = r.key  # type: ignore[index]
            _state["cells"][r.key] = proc  # type: ignore[index]
        _log.debug("BOM table: %d made parts", len(made))
    finally:
        _state["busy"] = False


def _update_summary(inputs) -> None:
    bom = _bom()
    _state["bom"] = bom
    counts = bom.counts()
    linked_changes = sum(1 for k in _state["chosen"] if _owner_of(k))  # type: ignore[union-attr]
    lines = [
        f"<b>{counts.get(bc.TYPE_MADE, 0)}</b> made parts · <b>{counts.get(bc.TYPE_COTS, 0)}</b> COTS "
        f"· {counts.get(bc.TYPE_ASSEMBLY, 0)} assemblies · parts mass about "
        f"<b>{bom.parts_mass_lb():.1f} lb</b>",
    ]
    ready = sum(1 for r in bom.flat if r.status in ("Ready to Cut", "Ready to Print"))
    if ready:
        lines.append(f"{ready} part(s) already exported: their Build Status starts as <b>Ready to Cut / Ready to Print</b>.")
    for warning in bom.warnings:
        lines.append("⚠ " + fh.safe_text(warning))
    if linked_changes:
        lines.append(f"\U0001F517 Saving processes will add a new version to {linked_changes} linked part file(s).")
    box = adsk.core.TextBoxCommandInput.cast(inputs.itemById(ID_SUMMARY))
    box.formattedText = "<br>".join(lines)


def _owner_of(key: str) -> str:
    node = _state["ctx"].memo.get(key)  # type: ignore[union-attr]
    return node.owner_file if node else ""


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
def _on_input_changed(args: adsk.core.InputChangedEventArgs) -> None:
    if _state.get("busy"):
        return
    changed, inputs = args.input, fh.all_inputs(args)
    cid = changed.id
    _log.debug("Input changed: %s", cid)

    if cid == ID_PICK:
        _pick_folder(inputs)
    elif cid.startswith("bpr_"):
        key = _state["row_keys"].get(cid)  # type: ignore[union-attr]
        item = adsk.core.DropDownCommandInput.cast(changed).selectedItem
        if key and item:
            _set_process(key, item.name)
            _update_summary(inputs)
    elif cid == ID_BULK:
        dropdown = adsk.core.DropDownCommandInput.cast(changed)
        choice = dropdown.selectedItem.name if dropdown.selectedItem else BULK_NONE
        if choice == BULK_NONE:
            return
        changed_rows = 0
        for row in _state["bom"].flat:  # type: ignore[union-attr]
            if row.type == bc.TYPE_MADE and row.process == bc.PROCESS_TBD:
                _set_process(row.key, choice)
                changed_rows += 1
        _log.info("Set %d TBD part(s) to %s", changed_rows, choice)
        _state["busy"] = True
        try:
            dropdown.listItems.item(0).isSelected = True
        finally:
            _state["busy"] = False
        _fill_table(inputs)
        _update_summary(inputs)


def _set_process(key: str, process: str) -> None:
    node = _state["ctx"].memo.get(key)  # type: ignore[union-attr]
    saved = (node.process or bc.PROCESS_TBD) if node else bc.PROCESS_TBD
    chosen: Dict[str, str] = _state["chosen"]  # type: ignore[assignment]
    if process == saved:
        chosen.pop(key, None)
    else:
        chosen[key] = process
    _log.debug("Process for %s -> %s (%d changes pending)", key, process, len(chosen))


def _pick_folder(inputs) -> None:
    _, ui = fh.app_ui()
    dialog = ui.createFolderDialog()
    dialog.title = "Where should the BOM be saved?"
    dialog.initialDirectory = _state.get("folder") or _default_folder()
    if dialog.showDialog() == adsk.core.DialogResults.DialogOK:
        _state["folder"] = dialog.folder
        box = adsk.core.TextBoxCommandInput.cast(inputs.itemById(ID_FOLDER))
        box.formattedText = fh.safe_text(dialog.folder)
        _log.info("BOM folder: %s", dialog.folder)


def _on_validate(args: adsk.core.ValidateInputsEventArgs) -> None:
    name = adsk.core.StringValueCommandInput.cast(fh.all_inputs(args).itemById(ID_FILE)).value.strip()
    args.areInputsValid = bool(name) and bool(_state.get("folder"))


def _on_execute(args: adsk.core.CommandEventArgs) -> None:
    _, ui = fh.app_ui()
    inputs = args.command.commandInputs
    folder = str(_state.get("folder") or _default_folder())
    name = nc.sanitize(adsk.core.StringValueCommandInput.cast(inputs.itemById(ID_FILE)).value.strip())
    if not name.lower().endswith(".xlsx"):
        name += ".xlsx"
    path = os.path.join(folder, name)
    open_after = adsk.core.BoolValueCommandInput.cast(inputs.itemById(ID_OPEN)).value

    bom = _bom()
    try:
        xw.write_xlsx(path, [
            xw.Sheet("BOM (monday)", bc.flat_table(bom), [w for _c, w in bc.FLAT_COLUMNS]),
            xw.Sheet("Indented", bc.indented_table(bom), [w for _c, w in bc.INDENTED_COLUMNS]),
            # COTS to order, by vendor, with store links and subtotals (0.12)
            xw.Sheet("Shopping list", bc.shopping_table(bom, xw.Link, xw.Bold),
                     [w for _c, w in bc.SHOPPING_COLUMNS], autofilter=False),
        ])
    except PermissionError:
        ui.messageBox(f"Couldn't write:\n{path}\n\nIs the file open in Excel? Close it and export again.",
                      "Gusset - Export BOM")
        return
    settings.save_state(config.ADDIN_DIR, bom_folder=folder)

    # Save process choices onto the parts.
    chosen: Dict[str, str] = dict(_state["chosen"])  # type: ignore[arg-type]
    job_plan = fj.build_attr_jobs(_state["root"], {k: {"process": v} for k, v in chosen.items()})  # type: ignore[arg-type]
    report = fr.RunReport()
    fr.apply_local_edits(job_plan.local_edits, _state["ctx"].components, report)  # type: ignore[union-attr]

    message = _export_message(path, bom, report, include_tags=not job_plan.jobs)
    if job_plan.jobs:
        _pending.clear()
        _pending.update(job_plan=job_plan, files=dict(_state["ctx"].files), doc=_state["doc"],  # type: ignore[union-attr]
                        report=report, message=message, path=path if open_after else "")
        app, _ = fh.app_ui()
        app.fireCustomEvent(AFTER_EVENT_ID, "")
        return
    ui.messageBox(message, "Gusset - Export BOM")
    if open_after:
        _open_file(path)


def _export_message(path: str, bom: bc.Bom, report: fr.RunReport, include_tags: bool = True) -> str:
    counts = bom.counts()
    lines = [
        f"Saved: {path}",
        f"{len(bom.flat)} rows ({counts.get(bc.TYPE_MADE, 0)} made, {counts.get(bc.TYPE_COTS, 0)} COTS, "
        f"{counts.get(bc.TYPE_ASSEMBLY, 0)} assemblies). Parts mass about {bom.parts_mass_lb():.1f} lb.",
    ]
    if include_tags and report.tagged:
        lines.append(f"Saved the process on {report.tagged} part(s).")
    if bom.warnings:
        lines.append("Heads up:\n  " + "\n  ".join(bom.warnings))
    lines.append(
        "To bring it into monday.com:\n"
        "  New board: Start from > Import data > Excel, pick 'Name' as the item name.\n"
        "  Updating a board: New item (arrow) > Import items. Under duplicates choose\n"
        "  'Update' matched on Part #, and set Build Status to 'Don't import' so\n"
        "  students' progress in monday isn't overwritten.")
    return "\n\n".join(lines)


def _on_after_dialog(args) -> None:
    if not _pending:
        return
    try:
        job_plan: fj.JobPlan = _pending["job_plan"]  # type: ignore[assignment]
        report = fr.run_file_jobs(job_plan, _pending["files"], _pending["doc"], note=fr.SAVE_NOTE_TAGS)  # type: ignore[arg-type]
        first: fr.RunReport = _pending["report"]  # type: ignore[assignment]
        message = str(_pending["message"])
        tagged = first.tagged + report.tagged
        problems = first.failures + report.failures + report.skipped
        extra = f"Saved the process on {tagged} part(s)"
        if report.files_saved:
            extra += f", including {len(report.files_saved)} linked file(s) (new version: '{fr.SAVE_NOTE_TAGS}')"
        extra += "."
        if problems:
            extra += "\n\nCouldn't save the process for:\n  " + "\n  ".join(problems[:10])
        _, ui = fh.app_ui()
        ui.messageBox(message + "\n\n" + extra, "Gusset - Export BOM")
        if _pending.get("path"):
            _open_file(str(_pending["path"]))
    finally:
        _pending.clear()


def _open_file(path: str) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        _log.info("Opened %s", path)
    except Exception as exc:
        _log.warning("Couldn't open %s (%s)", path, exc)


def _on_destroy(args: adsk.core.CommandEventArgs) -> None:
    _log.info("Export BOM closed")
    _state.clear()
    fh.release_handlers(HANDLER_GROUP)
