"""
Export Face - click one flat face of a part, save its outline as SVG or DXF.
Quick one-offs for the X-Carve (Easel) or the laser (LightBurn).

  1. GUSSET > Export Face, click a flat face (the side you'd see from above).
  2. Pick SVG or DXF. The dialog shows the part's size and stock thickness.
  3. Press Save and choose where. Holes come along; nothing in the design changes.

The export is logged on the open assembly, so the next Export BOM shows the
part as "Ready to Cut".
"""

from __future__ import annotations

import datetime
import json
import os
from typing import Dict, Optional

import adsk.core
import adsk.fusion

from .. import config
from ..lib import fab_core as fc
from ..lib import fab_geometry as fg
from ..lib import flat_export as fe
from ..lib import fusion_helpers as fh
from ..lib import log as gslog
from ..lib import naming_core as nc
from ..lib import design_tree as dt
from ..lib import settings
from ..lib import tip_box

CMD_ID = "Gusset_ExportFace"
CMD_NAME = "Export Face"
CMD_TOOLTIP = "Click a flat face and save its outline (with holes) as SVG or DXF for Easel or LightBurn."
ICON_DIR = os.path.join(config.ADDIN_DIR, "resources", "export_face")
HANDLER_GROUP = "export_face_dialog"

_log = gslog.get_logger("export_face")

ID_FACE, ID_FORMAT, ID_UNITS, ID_LOG, ID_INFO = "ef_face", "ef_format", "ef_units", "ef_log", "ef_info"
_state: Dict[str, object] = {}


def start() -> None:
    fh.add_button(CMD_ID, CMD_NAME, CMD_TOOLTIP, ICON_DIR, _on_created, config.PANEL_FAB_ID, config.PANEL_FAB_NAME)


def stop() -> None:
    fh.remove_button(CMD_ID, config.PANEL_FAB_ID)


def _on_created(args: adsk.core.CommandCreatedEventArgs) -> None:
    _log.info("Export Face opened")
    cmd = args.command
    _, ui = fh.app_ui()
    if not fh.active_design():
        ui.messageBox("Open a Fusion design first, then try Export Face again.", "Gusset")
        return
    _state.clear()
    _state["cfg"] = settings.load_config(config.ADDIN_DIR)
    cmd.okButtonText = "Save..."

    inputs = cmd.commandInputs
    tip_box.attach(cmd, CMD_ID)              # 'How to use this' + hover tips (0.13)
    select = inputs.addSelectionInput(ID_FACE, "Face", "Click a flat face of the part")
    select.addSelectionFilter("PlanarFaces")
    select.setSelectionLimits(1, 1)

    fmt = inputs.addDropDownCommandInput(ID_FORMAT, "Format", adsk.core.DropDownStyles.TextListDropDownStyle)
    default_fmt = settings.read_choice(config.ADDIN_DIR, "xcarve_format", ["svg", "dxf"], "svg")
    fmt.listItems.add("SVG (Easel, LightBurn)", default_fmt == "svg")
    fmt.listItems.add("DXF", default_fmt == "dxf")
    units = inputs.addDropDownCommandInput(ID_UNITS, "Units", adsk.core.DropDownStyles.TextListDropDownStyle)
    default_units = settings.read_choice(config.ADDIN_DIR, "fab_units", ["in", "mm"], "in")
    units.listItems.add("in", default_units == "in")
    units.listItems.add("mm", default_units == "mm")
    inputs.addBoolValueInput(ID_LOG, "Mark as exported (BOM: Ready to Cut)", True, "", True)
    inputs.addTextBoxCommandInput(ID_INFO, "", "Click a flat face.", 3, True)

    for event, base, func, label in (
        (cmd.inputChanged, adsk.core.InputChangedEventHandler, _on_input_changed, "input changed"),
        (cmd.execute, adsk.core.CommandEventHandler, _on_execute, "Save"),
        (cmd.destroy, adsk.core.CommandEventHandler, _on_destroy, "close"),
    ):
        event.add(fh.make_handler(base, func, f"Export Face: {label}", HANDLER_GROUP))


def _selected_face(inputs):
    select = adsk.core.SelectionCommandInput.cast(inputs.itemById(ID_FACE))
    if not select or select.selectionCount != 1:
        return None
    return adsk.fusion.BRepFace.cast(select.selection(0).entity)


def _owner(face):
    """(component, part number, description) of the part that owns a face."""
    occ = face.assemblyContext
    comp = occ.component if occ else face.body.parentComponent
    cfg: nc.NamingConfig = _state["cfg"]  # type: ignore[assignment]
    tagged = dt.read_text_attr(comp, "pn")
    parsed = nc.existing_number(tagged, comp.name)
    pn = nc.format_part_number(*parsed) if parsed else ""
    desc = nc.clean_description(comp.name, cfg) or nc.strip_fusion_suffixes(comp.name)
    return comp, pn, desc


def _on_input_changed(args: adsk.core.InputChangedEventArgs) -> None:
    inputs = fh.all_inputs(args)
    if args.input.id != ID_FACE:
        return
    face = _selected_face(inputs)
    box = adsk.core.TextBoxCommandInput.cast(inputs.itemById(ID_INFO))
    if not face:
        box.formattedText = "Click a flat face."
        _state.pop("profile", None)
        return
    comp, pn, desc = _owner(face)
    try:
        prof = fg.face_profile(face, desc)
    except Exception as exc:
        box.formattedText = f"<b>Can't export this face:</b> {fh.safe_text(str(exc))}"
        _state.pop("profile", None)
        return
    _state.update(profile=prof, pn=pn, desc=desc, comp=comp)
    x0, y0, x1, y1 = fe.bounds(prof)
    holes = sum(1 for lp in prof.loops if lp.kind == fe.KIND_HOLE)
    lines = [
        f"<b>{fh.safe_text(pn or '(no part number)')}</b> {fh.safe_text(desc)}",
        f"{(x1 - x0) / 25.4:.3f} x {(y1 - y0) / 25.4:.3f} in · {holes} hole(s) · "
        f"stock {fe.thickness_label(prof.thickness_mm)}",
    ]
    lines += ["⚠ " + fh.safe_text(w) for w in prof.warnings[:2]]
    box.formattedText = "<br>".join(lines)
    _log.info("Face picked on %r: %.1f x %.1f mm, %d holes", desc, x1 - x0, y1 - y0, holes)


def _on_execute(args: adsk.core.CommandEventArgs) -> None:
    _, ui = fh.app_ui()
    inputs = args.command.commandInputs
    prof: Optional[fe.FlatProfile] = _state.get("profile")  # type: ignore[assignment]
    if prof is None:
        ui.messageBox("Pick a flat face first.", "Gusset - Export Face")
        return
    fmt = "dxf" if adsk.core.DropDownCommandInput.cast(inputs.itemById(ID_FORMAT)).selectedItem.name.startswith("DXF") else "svg"
    units = adsk.core.DropDownCommandInput.cast(inputs.itemById(ID_UNITS)).selectedItem.name
    pn, desc = str(_state.get("pn", "")), str(_state.get("desc", ""))

    dialog = ui.createFileDialog()
    dialog.title = "Save the outline"
    dialog.filter = "SVG files (*.svg)" if fmt == "svg" else "DXF files (*.dxf)"
    folder = settings.load_state(config.ADDIN_DIR).get("fab_folder", "")
    if folder and os.path.isdir(folder):
        dialog.initialDirectory = folder
    suffix = f" ({units})" if fmt == "dxf" else ""
    dialog.initialFilename = nc.sanitize(" ".join(t for t in (pn, desc) if t) or "part") + suffix + "." + fmt
    if dialog.showSave() != adsk.core.DialogResults.DialogOK:
        _log.info("Save cancelled")
        return
    path = dialog.filename
    if not path.lower().endswith("." + fmt):
        path += "." + fmt

    fe.write_profile(path, prof, fmt, units)
    settings.save_state(config.ADDIN_DIR, fab_folder=os.path.dirname(path))

    logged = ""
    if adsk.core.BoolValueCommandInput.cast(inputs.itemById(ID_LOG)).value and pn:
        design = fh.active_design()
        root = design.rootComponent
        log = fc.parse_log(dt.read_text_attr(root, fc.LOG_ATTR))
        log[pn] = {"date": datetime.date.today().isoformat(), "process": "Export Face",
                   "file": os.path.basename(path)}
        dt.write_attr(root, fc.LOG_ATTR, json.dumps(log))
        logged = "\n\nLogged as exported: the next Export BOM shows it as Ready to Cut (save the assembly to keep this)."
    elif not pn:
        logged = "\n\nThis part has no part number, so it can't be tracked in the BOM. Run Name Parts first."

    warn = ("\n\nHeads up:\n  " + "\n  ".join(prof.warnings)) if prof.warnings else ""
    ui.messageBox(f"Saved:\n{path}\n\nStock: {fe.thickness_label(prof.thickness_mm, units)}{warn}{logged}",
                  "Gusset - Export Face")


def _on_destroy(args: adsk.core.CommandEventArgs) -> None:
    _state.clear()
    fh.release_handlers(HANDLER_GROUP)
