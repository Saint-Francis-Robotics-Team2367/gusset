"""
Fab Export - exports every made part in the open assembly, ready for the shop.

    X-Carve  -> SVG/DXF in  X-Carve/<material> <thickness>/   (Easel)
    Laser    -> SVG/DXF in  Laser/<material> <thickness>/     (LightBurn)
    3D Print -> 3MF     in  3D Print/                          (Bambu Studio / OrcaSlicer)
    Lathe    -> PDF lathe sheet in Lathe/
    Mill     -> skipped (Fusion CAM)
plus "Cut list.xlsx" in the export folder.

Each part's Process comes from Export BOM. File names carry the part number,
description and total quantity: "27-DRV-104 omni mounting plate - qty 2.svg".
Exported parts are logged on the open assembly so the next BOM shows them as
"Ready to Cut" / "Ready to Print". Nothing else in the design changes.
"""

from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import time
from typing import Dict, List, Optional

import adsk.core
import adsk.fusion

from .. import config
from ..lib import bom_core as bc
from ..lib import design_tree as dt
from ..lib import fab_core as fc
from ..lib import fab_geometry as fg
from ..lib import flat_export as fe
from ..lib import fusion_helpers as fh
from ..lib import lathe_sheet as ls
from ..lib import log as gslog
from ..lib import naming_core as nc
from ..lib import settings
from ..lib import xlsx_writer as xw
from ..lib import tip_box

CMD_ID = "Gusset_FabExport"
CMD_NAME = "Fab Export"
CMD_TOOLTIP = ("Export every made part at once: SVG/DXF for the X-Carve and laser (sorted by stock), "
               "3MF for the printers, PDF lathe sheets, plus a cut list.")
ICON_DIR = os.path.join(config.ADDIN_DIR, "resources", "fab_export")
HANDLER_GROUP = "fab_export_dialog"

_log = gslog.get_logger("fab_export")

ID_INTRO, ID_FOLDER, ID_PICK, ID_SUB = "fx_intro", "fx_folder", "fx_pick", "fx_sub"
ID_XFMT, ID_LFMT, ID_NEW, ID_OPEN = "fx_xfmt", "fx_lfmt", "fx_new", "fx_open"
ID_TABLE, ID_SUMMARY = "fx_table", "fx_summary"
ID_ALL, ID_NONE = "fx_all", "fx_none"
MACHINE_IDS = {proc: "fx_m_" + proc.lower().replace(" ", "").replace("-", "") for proc in fc.EXPORT_PROCESSES}

_state: Dict[str, object] = {}


def start() -> None:
    fh.add_button(CMD_ID, CMD_NAME, CMD_TOOLTIP, ICON_DIR, _on_created, config.PANEL_FAB_ID, config.PANEL_FAB_NAME)


def stop() -> None:
    fh.remove_button(CMD_ID, config.PANEL_FAB_ID)


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------
def _default_folder() -> str:
    remembered = settings.load_state(config.ADDIN_DIR).get("fab_folder", "")
    if remembered and os.path.isdir(remembered):
        return remembered
    documents = os.path.join(os.path.expanduser("~"), "Documents")
    return documents if os.path.isdir(documents) else os.path.expanduser("~")


def _on_created(args: adsk.core.CommandCreatedEventArgs) -> None:
    _log.info("Fab Export opened")
    cmd = args.command
    app, ui = fh.app_ui()
    design = fh.active_design()
    if not design:
        ui.messageBox("Open a Fusion design first, then try Fab Export again.", "Gusset")
        return

    started = time.time()
    cfg = settings.load_config(config.ADDIN_DIR)
    ctx = dt.TreeContext(cfg)
    root = dt.root_node(design, ctx)
    dt.fill_bom_info(root, ctx, cfg)
    fab_log = dt.read_fab_logs(root, ctx)
    bom = bc.build_bom(root, cfg, fab_log=fab_log)
    title = nc.strip_fusion_suffixes(root.name)
    _state.clear()
    _state.update(cfg=cfg, design=design, ctx=ctx, root=root, bom=bom, fab_log=fab_log, title=title,
                  folder=_default_folder(), thickness={}, geo_warnings={}, generation=0, busy=False,
                  units=settings.read_choice(config.ADDIN_DIR, "fab_units", ["in", "mm"], "in"))
    _measure_flat_parts()
    _log.info("Fab Export ready in %.1fs", time.time() - started)

    try:
        cmd.setDialogInitialSize(860, 680)
        cmd.setDialogMinimumSize(620, 460)
    except Exception:
        pass
    cmd.okButtonText = "Export"

    inputs = cmd.commandInputs
    tip_box.attach(cmd, CMD_ID)              # 'How to use this' + hover tips (0.13)
    inputs.addTextBoxCommandInput(
        ID_INTRO, "",
        f"Exports the made parts of <b>{fh.safe_text(title)}</b> using each part's <b>Process</b> "
        "(set it in Export BOM). Mill parts are skipped (Fusion CAM).", 2, True)
    inputs.addTextBoxCommandInput(ID_FOLDER, "Folder", fh.safe_text(str(_state["folder"])), 1, True)
    inputs.addBoolValueInput(ID_PICK, "", False, "", False).text = "Choose folder..."
    inputs.addStringValueInput(ID_SUB, "New folder name",
                               nc.sanitize(f"{title} fab {datetime.date.today().isoformat()}"))
    xfmt = inputs.addDropDownCommandInput(ID_XFMT, "X-Carve files", adsk.core.DropDownStyles.TextListDropDownStyle)
    lfmt = inputs.addDropDownCommandInput(ID_LFMT, "Laser files", adsk.core.DropDownStyles.TextListDropDownStyle)
    for dropdown, key in ((xfmt, "xcarve_format"), (lfmt, "laser_format")):
        current = settings.read_choice(config.ADDIN_DIR, key, ["svg", "dxf"], "svg")
        dropdown.listItems.add("SVG", current == "svg")
        dropdown.listItems.add("DXF", current == "dxf")
    # Which machines: e.g. untick everything but Lathe when you're standing at the lathe.
    remembered = settings.load_state(config.ADDIN_DIR).get("fab_machines")
    ticked = set(remembered) if isinstance(remembered, list) else set(fc.EXPORT_PROCESSES)
    machines = inputs.addGroupCommandInput("fx_machines", "Machines to export for")
    for proc in fc.EXPORT_PROCESSES:
        box = machines.children.addBoolValueInput(MACHINE_IDS[proc], proc, True, "", proc in ticked)
        box.tooltip = {"X-Carve": "SVG/DXF outlines for Easel", "Laser": "SVG/DXF outlines for LightBurn",
                       "3D Print": "3MF files for Bambu Studio / OrcaSlicer", "Lathe": "PDF lathe sheets"}[proc]
    inputs.addBoolValueInput(ID_NEW, "Only parts not exported yet", True, "", False)
    inputs.addBoolValueInput(ID_OPEN, "Open the folder when done", True, "", True)

    table = inputs.addTableCommandInput(ID_TABLE, "Parts", 6, "1:4:5:1:2:6")
    table.maximumVisibleRows = 16
    table.minimumVisibleRows = 6
    try:
        table.tablePresentationStyle = adsk.core.TablePresentationStyles.itemBorderTablePresentationStyle
    except Exception:
        pass
    inputs.addBoolValueInput(ID_ALL, "", False, "", False).text = "Tick all parts"
    inputs.addBoolValueInput(ID_NONE, "", False, "", False).text = "Untick all parts"
    inputs.addTextBoxCommandInput(ID_SUMMARY, "", "", 3, True)
    _state["excluded"] = set()

    for event, base, func, label in (
        (cmd.inputChanged, adsk.core.InputChangedEventHandler, _on_input_changed, "input changed"),
        (cmd.validateInputs, adsk.core.ValidateInputsEventHandler, _on_validate, "validate"),
        (cmd.execute, adsk.core.CommandEventHandler, _on_execute, "Export"),
        (cmd.destroy, adsk.core.CommandEventHandler, _on_destroy, "close"),
    ):
        event.add(fh.make_handler(base, func, f"Fab Export: {label}", HANDLER_GROUP))
    _replan(inputs)


def _measure_flat_parts() -> None:
    """Read thickness of every X-Carve / laser part once (fast: ~0.05 s each)."""
    bom: bc.Bom = _state["bom"]  # type: ignore[assignment]
    ctx: dt.TreeContext = _state["ctx"]  # type: ignore[assignment]
    for row in bom.flat:
        if row.type != bc.TYPE_MADE or row.process not in fc.FLAT_PROCESSES:
            continue
        comp = ctx.components.get(row.key)
        body, _w = fg.main_body(comp) if comp is not None else (None, [])
        try:
            prof = fg.flat_profile(body, row.description) if body is not None else None
            _state["thickness"][row.key] = prof.thickness_mm if prof else None  # type: ignore[index]
            _state["geo_warnings"][row.key] = prof.warnings if prof else ["no solid body"]  # type: ignore[index]
        except Exception as exc:
            _state["thickness"][row.key] = None  # type: ignore[index]
            _state["geo_warnings"][row.key] = [str(exc)]  # type: ignore[index]


def _options(inputs) -> fc.FabOptions:
    def fmt(input_id: str) -> str:
        item = adsk.core.DropDownCommandInput.cast(inputs.itemById(input_id)).selectedItem
        return item.name.lower() if item else "svg"
    processes = {proc for proc, input_id in MACHINE_IDS.items()
                 if adsk.core.BoolValueCommandInput.cast(inputs.itemById(input_id)).value}
    return fc.FabOptions(xcarve_format=fmt(ID_XFMT), laser_format=fmt(ID_LFMT), units=str(_state["units"]),
                         only_new=adsk.core.BoolValueCommandInput.cast(inputs.itemById(ID_NEW)).value,
                         processes=processes, excluded=set(_state.get("excluded", set())))  # type: ignore[arg-type]


def _replan(inputs) -> None:
    options = _options(inputs)
    bom: bc.Bom = _state["bom"]  # type: ignore[assignment]
    items = fc.plan(bom.flat, options, _state["fab_log"])  # type: ignore[arg-type]
    for item in items:
        if item.output == fc.OUT_FLAT:
            fc.set_thickness(item, _state["thickness"].get(item.key), options)  # type: ignore[union-attr]
            item.warnings += _state["geo_warnings"].get(item.key, [])  # type: ignore[union-attr]
    _state["items"], _state["options"] = items, options
    _fill_table(inputs, items)
    _update_summary(inputs, items)


def _fill_table(inputs, items: List[fc.FabItem]) -> None:
    table = adsk.core.TableCommandInput.cast(inputs.itemById(ID_TABLE))
    _state["busy"] = True
    try:
        table.clear()
        gen = int(_state["generation"]) + 1  # type: ignore[arg-type]
        _state["generation"] = gen
        cells = table.commandInputs
        for col, title in enumerate(("", "Part #", "Description", "Qty", "Process", "Goes to")):
            table.addCommandInput(cells.addTextBoxCommandInput(f"fh_{gen}_{col}", "", f"<b>{title}</b>", 1, True), 0, col)
        order = {fc.OUT_FLAT: 0, fc.OUT_PRINT: 1, fc.OUT_LATHE: 2, fc.OUT_SKIP: 3}
        _state["row_keys"] = {}
        for row, item in enumerate(sorted(items, key=lambda i: (order[i.output], bool(i.status), i.rel_path)), start=1):
            where = item.rel_path if item.will_export else f"skipped: {item.status}"
            if item.will_export and item.warnings:
                where = "\u26a0 " + where
            box = cells.addBoolValueInput(f"fx_pick_{gen}_{row}", "", True, "", item.will_export)
            box.isEnabled = fc.selectable(item)
            box.tooltip = "Tick to export this part" if box.isEnabled else (item.status or "nothing to export")
            table.addCommandInput(box, row, 0)
            _state["row_keys"][box.id] = item.key  # type: ignore[index]
            values = (item.part_number or "(no number)", item.description, str(item.qty), item.process or "-", where)
            for col, value in enumerate(values, start=1):
                cell = cells.addTextBoxCommandInput(f"fc_{gen}_{row}_{col}", "", "", 1, True)
                cell.text = value
                if col == 5:
                    cell.tooltip = "; ".join(item.warnings) or where
                table.addCommandInput(cell, row, col)
    finally:
        _state["busy"] = False


def _update_summary(inputs, items: List[fc.FabItem]) -> None:
    counts: Dict[str, int] = {}
    for item in items:
        if item.will_export:
            counts[item.process] = counts.get(item.process, 0) + 1
    exporting = sum(counts.values())
    skipped = len(items) - exporting
    parts = [f"<b>{exporting}</b> file(s) to export"] + [f"{n} {p}" for p, n in counts.items()]
    lines = [" · ".join(parts)]
    tbd = sum(1 for i in items if "no process" in i.status)
    if tbd:
        lines.append(f"⚠ {tbd} part(s) have no process yet - set them in Export BOM first.")
    if skipped:
        lines.append(f"{skipped} part(s) skipped (hover the table for reasons).")
    adsk.core.TextBoxCommandInput.cast(inputs.itemById(ID_SUMMARY)).formattedText = "<br>".join(lines)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
def _on_input_changed(args: adsk.core.InputChangedEventArgs) -> None:
    if _state.get("busy"):
        return
    cid = args.input.id
    _log.debug("Input changed: %s", cid)
    if cid == ID_PICK:
        _, ui = fh.app_ui()
        dialog = ui.createFolderDialog()
        dialog.title = "Where should the fab files go?"
        dialog.initialDirectory = str(_state.get("folder") or _default_folder())
        if dialog.showDialog() == adsk.core.DialogResults.DialogOK:
            _state["folder"] = dialog.folder
            adsk.core.TextBoxCommandInput.cast(fh.all_inputs(args).itemById(ID_FOLDER)).formattedText = fh.safe_text(dialog.folder)
    elif cid in (ID_XFMT, ID_LFMT, ID_NEW) or cid in MACHINE_IDS.values():
        _replan(fh.all_inputs(args))
    elif cid.startswith("fx_pick_"):
        key = _state.get("row_keys", {}).get(cid)  # type: ignore[union-attr]
        if key:
            excluded = _state["excluded"]  # type: ignore[assignment]
            if adsk.core.BoolValueCommandInput.cast(args.input).value:
                excluded.discard(key)  # type: ignore[union-attr]
            else:
                excluded.add(key)  # type: ignore[union-attr]
            _replan(fh.all_inputs(args))
    elif cid in (ID_ALL, ID_NONE):
        items: List[fc.FabItem] = _state.get("items", [])  # type: ignore[assignment]
        _state["excluded"] = set() if cid == ID_ALL else {i.key for i in items if fc.selectable(i)}
        _replan(fh.all_inputs(args))


def _on_validate(args: adsk.core.ValidateInputsEventArgs) -> None:
    items: List[fc.FabItem] = _state.get("items", [])  # type: ignore[assignment]
    sub = adsk.core.StringValueCommandInput.cast(fh.all_inputs(args).itemById(ID_SUB)).value.strip()
    args.areInputsValid = bool(sub) and any(i.will_export for i in items)


def _on_execute(args: adsk.core.CommandEventArgs) -> None:
    _, ui = fh.app_ui()
    inputs = args.command.commandInputs
    items: List[fc.FabItem] = _state["items"]  # type: ignore[assignment]
    options: fc.FabOptions = _state["options"]  # type: ignore[assignment]
    ctx: dt.TreeContext = _state["ctx"]  # type: ignore[assignment]
    design = _state["design"]
    sub = nc.sanitize(adsk.core.StringValueCommandInput.cast(inputs.itemById(ID_SUB)).value.strip())
    out_dir = os.path.join(str(_state["folder"]), sub)
    os.makedirs(out_dir, exist_ok=True)
    _log.info("Exporting to %s", out_dir)

    todo = [i for i in items if i.will_export]
    done: List[fc.FabItem] = []
    failures: List[str] = []
    progress = ui.progressBar
    try:
        progress.show("Gusset: exporting part %v of %m", 0, max(len(todo), 1), False)
    except Exception:
        progress = None
    started = time.time()
    for n, item in enumerate(todo, start=1):
        if progress:
            progress.progressValue = n - 1
        adsk.doEvents()
        try:
            _export_one(item, ctx, design, out_dir, options)
            done.append(item)
        except Exception as exc:
            _log.exception("Export of %s failed", item.part_number or item.description)
            failures.append(f"{item.part_number or item.description}: {exc}")
            item.status = f"FAILED: {exc}"
    if progress:
        progress.hide()

    try:
        xw.write_xlsx(os.path.join(out_dir, "Cut list.xlsx"), [
            xw.Sheet("Cut list", fc.cut_list_rows(items), [14, 30, 6, 10, 20, 12, 60, 50])])
    except Exception as exc:
        failures.append(f"Cut list: {exc}")

    root = design.rootComponent
    if done:
        log = fc.record(fc.parse_log(dt.read_text_attr(root, fc.LOG_ATTR)), done)
        dt.write_attr(root, fc.LOG_ATTR, json.dumps(log))
    settings.save_state(config.ADDIN_DIR, fab_folder=str(_state["folder"]),
                        fab_machines=sorted(options.processes or fc.EXPORT_PROCESSES))
    _log.info("Fab Export: %d exported, %d failed (%.1fs)", len(done), len(failures), time.time() - started)

    by_process: Dict[str, int] = {}
    for item in done:
        by_process[item.process] = by_process.get(item.process, 0) + 1
    lines = [f"Exported {len(done)} file(s) to:\n{out_dir}",
             "  " + ", ".join(f"{n} {p}" for p, n in by_process.items()) if by_process else "",
             "A Cut list.xlsx is in the folder too."]
    warned = [i for i in done if i.warnings]
    if warned:
        lines.append("Check these in Easel/LightBurn/the slicer:\n  " + "\n  ".join(
            f"{i.part_number or i.description}: {i.warnings[0]}" for i in warned[:8]))
    if failures:
        lines.append(f"{len(failures)} problem(s):\n  " + "\n  ".join(failures[:8]))
    if done:
        lines.append("Exported parts will show as Ready to Cut / Ready to Print in the next Export BOM "
                     "(save the assembly to keep this).")
    ui.messageBox("\n\n".join(l for l in lines if l), "Gusset - Fab Export")
    if adsk.core.BoolValueCommandInput.cast(inputs.itemById(ID_OPEN)).value:
        _open_folder(out_dir)


def _export_one(item: fc.FabItem, ctx: dt.TreeContext, design, out_dir: str, options: fc.FabOptions) -> None:
    comp = ctx.components.get(item.key)
    if comp is None:
        raise RuntimeError("couldn't find the part in the design")
    body, warnings = fg.main_body(comp)
    if body is None:
        raise RuntimeError("no solid body")
    item.warnings += [w for w in warnings if w not in item.warnings]
    folder = os.path.join(out_dir, *item.folder.split("/"))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, item.file_name)
    _log.debug("Exporting %s -> %s", item.part_number, path)
    if item.output == fc.OUT_FLAT:
        prof = fg.flat_profile(body, f"{item.part_number} {item.description}".strip())
        fe.write_profile(path, prof, item.fmt, options.units)
    elif item.output == fc.OUT_PRINT:
        fg.export_3mf(design, body, path)
    elif item.output == fc.OUT_LATHE:
        prof = fg.lathe_profile(body, item.description, part_number=item.part_number,
                                description=item.description, material=item.material, qty=item.qty)
        item.warnings += prof.warnings
        ls.render(prof, path, options.units)


def _open_folder(path: str) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as exc:
        _log.warning("Couldn't open %s (%s)", path, exc)


def _on_destroy(args: adsk.core.CommandEventArgs) -> None:
    _log.info("Fab Export closed")
    _state.clear()
    fh.release_handlers(HANDLER_GROUP)
