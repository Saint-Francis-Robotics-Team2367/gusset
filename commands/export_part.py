"""
Export Part - click ONE part and save its shop file. The 3D twin of Export Face.

  1. GUSSET > Export Part, click the part (anywhere on it).
  2. Gusset reads the part's Process and suggests a file:
        Lathe    -> PDF lathe sheet
        3D Print -> 3MF (Bambu Studio / OrcaSlicer)
        X-Carve / Laser -> SVG or DXF outline of the whole plate (holes + pockets)
     Change it in the "File" dropdown if you want something else.
  3. Press Save and choose where.

Like Fab Export, the export is logged on the open assembly, so the next
Export BOM shows the part as "Ready to Cut" / "Ready to Print".
"""

from __future__ import annotations

import datetime
import json
import os
from typing import Dict, Optional

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
from ..lib import tip_box

CMD_ID = "Gusset_ExportPart"
CMD_NAME = "Export Part"
CMD_TOOLTIP = ("Click one part and save its shop file: lathe sheet (PDF), 3D print (3MF) or plate outline "
               "(SVG/DXF), picked from the part's Process.")
ICON_DIR = os.path.join(config.ADDIN_DIR, "resources", "export_part")
HANDLER_GROUP = "export_part_dialog"

_log = gslog.get_logger("export_part")

ID_PART, ID_KIND, ID_INFO = "xp_part", "xp_kind", "xp_info"

# dropdown label -> (output, format)
KINDS = {
    "Lathe sheet (PDF)": (fc.OUT_LATHE, "pdf"),
    "3D print (3MF)": (fc.OUT_PRINT, "3mf"),
    "Plate outline (SVG)": (fc.OUT_FLAT, "svg"),
    "Plate outline (DXF)": (fc.OUT_FLAT, "dxf"),
}

_state: Dict[str, object] = {}


def start() -> None:
    fh.add_button(CMD_ID, CMD_NAME, CMD_TOOLTIP, ICON_DIR, _on_created, config.PANEL_FAB_ID, config.PANEL_FAB_NAME)


def stop() -> None:
    fh.remove_button(CMD_ID, config.PANEL_FAB_ID)


def _on_created(args: adsk.core.CommandCreatedEventArgs) -> None:
    _log.info("Export Part opened")
    cmd = args.command
    _, ui = fh.app_ui()
    design = fh.active_design()
    if not design:
        ui.messageBox("Open a Fusion design first, then try Export Part again.", "Gusset")
        return
    # Read the assembly once, so we know each part's process (including the tag
    # cache for parts linked deep inside other files), material and total quantity.
    cfg = settings.load_config(config.ADDIN_DIR)
    ctx = dt.TreeContext(cfg)
    root = dt.root_node(design, ctx)
    dt.fill_bom_info(root, ctx, cfg)
    bom = bc.build_bom(root, cfg)
    _state.clear()
    _state.update(cfg=cfg, design=design, ctx=ctx, rows={r.key: r for r in bom.flat}, busy=False,
                  units=settings.read_choice(config.ADDIN_DIR, "fab_units", ["in", "mm"], "in"))
    cmd.okButtonText = "Save..."

    inputs = cmd.commandInputs
    tip_box.attach(cmd, CMD_ID)              # 'How to use this' + hover tips (0.13)
    pick = inputs.addSelectionInput(ID_PART, "Part", "Click the part to export")
    pick.addSelectionFilter("Occurrences")
    pick.addSelectionFilter("SolidBodies")
    pick.setSelectionLimits(1, 1)
    kind = inputs.addDropDownCommandInput(ID_KIND, "File", adsk.core.DropDownStyles.TextListDropDownStyle)
    for i, label in enumerate(KINDS):
        kind.listItems.add(label, i == 0)
    inputs.addTextBoxCommandInput(ID_INFO, "", "Click a part. Gusset suggests a file from its Process.", 4, True)

    for event, base, func, label in (
        (cmd.inputChanged, adsk.core.InputChangedEventHandler, _on_input_changed, "input changed"),
        (cmd.validateInputs, adsk.core.ValidateInputsEventHandler, _on_validate, "validate"),
        (cmd.execute, adsk.core.CommandEventHandler, _on_execute, "Save"),
        (cmd.destroy, adsk.core.CommandEventHandler, _on_destroy, "close"),
    ):
        event.add(fh.make_handler(base, func, f"Export Part: {label}", HANDLER_GROUP))


def _picked_component(inputs):
    select = adsk.core.SelectionCommandInput.cast(inputs.itemById(ID_PART))
    if select.selectionCount != 1:
        return None
    entity = select.selection(0).entity
    occ = adsk.fusion.Occurrence.cast(entity)
    if occ:
        return occ.component
    body = adsk.fusion.BRepBody.cast(entity)
    if body:
        return body.assemblyContext.component if body.assemblyContext else body.parentComponent
    return None


def _set_kind(inputs, label: str) -> None:
    dropdown = adsk.core.DropDownCommandInput.cast(inputs.itemById(ID_KIND))
    _state["busy"] = True
    try:
        for i in range(dropdown.listItems.count):
            item = dropdown.listItems.item(i)
            item.isSelected = item.name == label
    finally:
        _state["busy"] = False


def _on_input_changed(args: adsk.core.InputChangedEventArgs) -> None:
    if _state.get("busy"):
        return
    inputs = fh.all_inputs(args)
    if args.input.id == ID_PART:
        comp = _picked_component(inputs)
        if comp is not None:
            row: Optional[bc.BomRow] = _state["rows"].get(dt.component_key(comp))  # type: ignore[union-attr]
            process = row.process if row else dt.read_text_attr(comp, "process")
            out = fc.default_output_for(process)
            if out == fc.OUT_FLAT:
                fmt = settings.read_choice(config.ADDIN_DIR, "laser_format" if process == fc.PROC_LASER
                                           else "xcarve_format", ["svg", "dxf"], "svg")
                _set_kind(inputs, "Plate outline (DXF)" if fmt == "dxf" else "Plate outline (SVG)")
            else:
                _set_kind(inputs, next(label for label, (o, _f) in KINDS.items() if o == out))
            _state["comp"], _state["row"], _state["process"] = comp, row, process
    _describe(inputs)


def _describe(inputs) -> None:
    box = adsk.core.TextBoxCommandInput.cast(inputs.itemById(ID_INFO))
    comp = _state.get("comp")
    if comp is None:
        box.formattedText = "Click a part. Gusset suggests a file from its Process."
        return
    row: Optional[bc.BomRow] = _state.get("row")  # type: ignore[assignment]
    process = _state.get("process") or bc.PROCESS_TBD
    lines = [f"<b>{fh.safe_text(row.part_number if row and row.part_number else '(no part number)')}</b> "
             f"{fh.safe_text(row.description if row else nc.strip_fusion_suffixes(comp.name))}",  # type: ignore[union-attr]
             f"Process: <b>{fh.safe_text(str(process))}</b>"
             + (f" · qty {row.qty} in this assembly" if row else "")
             + (f" · {fh.safe_text(row.material)}" if row and row.material else "")]
    if row and row.type == bc.TYPE_COTS:
        lines.append("⚠ This looks like a bought (COTS) part. You can still export it.")
    if process in (bc.PROCESS_TBD, ""):
        lines.append("No process set yet, so Gusset guessed. Set it in Export BOM to make this automatic.")
    box.formattedText = "<br>".join(lines)


def _on_validate(args: adsk.core.ValidateInputsEventArgs) -> None:
    args.areInputsValid = _picked_component(fh.all_inputs(args)) is not None


def _on_execute(args: adsk.core.CommandEventArgs) -> None:
    _, ui = fh.app_ui()
    inputs = args.command.commandInputs
    comp = _picked_component(inputs)
    if comp is None:
        return
    label = adsk.core.DropDownCommandInput.cast(inputs.itemById(ID_KIND)).selectedItem.name
    output, fmt = KINDS[label]
    row: Optional[bc.BomRow] = _state.get("row")  # type: ignore[assignment]
    pn = row.part_number if row else ""
    desc = row.description if row else nc.strip_fusion_suffixes(comp.name)
    qty = row.qty if row else 1
    units = str(_state["units"])

    body, warnings = fg.main_body(comp)
    if body is None:
        ui.messageBox("That part has no solid body to export.", "Gusset - Export Part")
        return

    dialog = ui.createFileDialog()
    dialog.title = "Save the part file"
    dialog.filter = {"pdf": "PDF files (*.pdf)", "3mf": "3MF files (*.3mf)",
                     "svg": "SVG files (*.svg)", "dxf": "DXF files (*.dxf)"}[fmt]
    folder = settings.load_state(config.ADDIN_DIR).get("fab_folder", "")
    if folder and os.path.isdir(folder):
        dialog.initialDirectory = folder
    suffix = f" ({units})" if fmt == "dxf" else ""
    dialog.initialFilename = fc.base_name(pn, desc, qty) + suffix + "." + fmt
    if dialog.showSave() != adsk.core.DialogResults.DialogOK:
        _log.info("Save cancelled")
        return
    path = dialog.filename if dialog.filename.lower().endswith("." + fmt) else dialog.filename + "." + fmt

    try:
        if output == fc.OUT_LATHE:
            prof = fg.lathe_profile(body, desc, part_number=pn, description=desc,
                                    material=row.material if row else "", qty=qty)
            warnings += prof.warnings
            ls.render(prof, path, units)
        elif output == fc.OUT_PRINT:
            fg.export_3mf(_state["design"], body, path)
        else:
            prof = fg.flat_profile(body, f"{pn} {desc}".strip())
            warnings += prof.warnings
            fe.write_profile(path, prof, fmt, units)
    except Exception as exc:
        _log.exception("Export Part failed")
        ui.messageBox(f"Couldn't export this part as {label}:\n\n{exc}\n\n"
                      "Tip: lathe sheets need round parts, outlines need flat plates.", "Gusset - Export Part")
        return
    settings.save_state(config.ADDIN_DIR, fab_folder=os.path.dirname(path))

    logged = ""
    if pn:
        process = str(_state.get("process") or {fc.OUT_LATHE: fc.PROC_LATHE, fc.OUT_PRINT: fc.PROC_PRINT}.get(output, fc.PROC_XCARVE))
        root = _state["design"].rootComponent  # type: ignore[union-attr]
        log = fc.parse_log(dt.read_text_attr(root, fc.LOG_ATTR))
        log[pn] = {"date": datetime.date.today().isoformat(), "process": process, "file": os.path.basename(path)}
        dt.write_attr(root, fc.LOG_ATTR, json.dumps(log))
        logged = "\n\nLogged as exported (save the assembly to keep this)."
    warn = ("\n\nCheck:\n  " + "\n  ".join(warnings[:4])) if warnings else ""
    _log.info("Export Part: %s -> %s", pn or desc, path)
    ui.messageBox(f"Saved:\n{path}{warn}{logged}", "Gusset - Export Part")


def _on_destroy(args: adsk.core.CommandEventArgs) -> None:
    _state.clear()
    fh.release_handlers(HANDLER_GROUP)
