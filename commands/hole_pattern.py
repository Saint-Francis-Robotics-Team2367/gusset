"""
Hole Pattern - puts bolt holes on FRC's 0.5" grid on a flat face (box tube or plate).

  1. GUSSET > Hole Pattern, click the flat face (e.g. the 1" side of a 2x1 tube).
  2. Pick the screw (#10 or 1/4") and the fit (Clearance, Close or Tap).
  3. Pick the layout: one row down the middle, or a full 0.5" grid.
  4. Watch the preview, then press OK.

The holes are a normal sketch + cut in the part's timeline ("Gusset holes ..."),
so you can edit or delete them like any other feature.
"""

from __future__ import annotations

import os
from typing import Dict, Optional

import adsk.core
import adsk.fusion

from .. import config
from ..lib import feature_builder as fb
from ..lib import frc_features as ff
from ..lib import fusion_helpers as fh
from ..lib import log as gslog
from ..lib import tip_box

CMD_ID = "Gusset_HolePattern"
CMD_NAME = "Hole Pattern"
CMD_TOOLTIP = ('Bolt holes on the FRC 0.5" grid: pick a face, #10 or 1/4", clearance / close / tap. '
               "Shows a preview before cutting.")
ICON_DIR = os.path.join(config.ADDIN_DIR, "resources", "hole_pattern")
HANDLER_GROUP = "hole_pattern_dialog"

_log = gslog.get_logger("hole_pattern")

ID_FACE, ID_SCREW, ID_FIT, ID_LAYOUT, ID_START, ID_DEPTH, ID_INFO, ID_HELP = (
    "hp_face", "hp_screw", "hp_fit", "hp_layout", "hp_start", "hp_depth", "hp_info", "hp_help")

LAYOUTS = {"One row down the middle": ff.LAYOUT_ROW, 'Full 0.5" grid': ff.LAYOUT_GRID}
STARTS = {'First hole 0.25" from the end': ff.START_END, "Centered on the face": ff.START_CENTER}
DEPTHS = {"Through this wall only": "wall", "Through everything": "all"}

HELP = (
    "<b>Which fit?</b> Clearance: the bolt slides through (most joints). Close: snug, for lining parts up. "
    "Tap: the hole gets threaded so a bolt screws into it.<br>"
    "<b>Which depth?</b> On a box tube, 'this wall only' drills one side; 'everything' goes through both walls "
    "(for a bolt all the way through the tube).<br>"
    "<b>Why 0.5\"?</b> It's the standard FRC spacing, so your tube lines up with COTS gussets and brackets."
)

_state: Dict[str, object] = {}


def start() -> None:
    fh.add_button(CMD_ID, CMD_NAME, CMD_TOOLTIP, ICON_DIR, _on_created,
                  config.PANEL_FEATURES_ID, config.PANEL_FEATURES_NAME)


def stop() -> None:
    fh.remove_button(CMD_ID, config.PANEL_FEATURES_ID)


def _dropdown(inputs, input_id: str, label: str, choices, selected: str):
    dd = inputs.addDropDownCommandInput(input_id, label, adsk.core.DropDownStyles.TextListDropDownStyle)
    for choice in choices:
        dd.listItems.add(choice, choice == selected)
    return dd


def _choice(inputs, input_id: str) -> str:
    item = adsk.core.DropDownCommandInput.cast(inputs.itemById(input_id)).selectedItem
    return item.name if item else ""


def _on_created(args: adsk.core.CommandCreatedEventArgs) -> None:
    _log.info("Hole Pattern opened")
    cmd = args.command
    _, ui = fh.app_ui()
    if not fh.active_design():
        ui.messageBox("Open a Fusion design first, then try Hole Pattern again.", "Gusset")
        return
    _state.clear()
    inputs = cmd.commandInputs
    tip_box.attach(cmd, CMD_ID)              # 'How to use this' + hover tips (0.13)
    face = inputs.addSelectionInput(ID_FACE, "Face", "Click the flat face to drill")
    face.addSelectionFilter("PlanarFaces")
    face.setSelectionLimits(1, 1)
    _dropdown(inputs, ID_SCREW, "Screw", ["#10", '1/4"'], "#10")
    _dropdown(inputs, ID_FIT, "Fit", ff.FITS, "Clearance")
    _dropdown(inputs, ID_LAYOUT, "Layout", list(LAYOUTS), "One row down the middle")
    _dropdown(inputs, ID_START, "Start", list(STARTS), 'First hole 0.25" from the end')
    _dropdown(inputs, ID_DEPTH, "Depth", list(DEPTHS), "Through this wall only")
    inputs.addTextBoxCommandInput(ID_INFO, "", "Click a flat face to see the holes.", 3, True)
    inputs.addTextBoxCommandInput(ID_HELP, "", HELP, 6, True)

    for event, base, func, label in (
        (cmd.inputChanged, adsk.core.InputChangedEventHandler, _on_input_changed, "input changed"),
        (cmd.executePreview, adsk.core.CommandEventHandler, _on_preview, "preview"),
        (cmd.validateInputs, adsk.core.ValidateInputsEventHandler, _on_validate, "validate"),
        (cmd.execute, adsk.core.CommandEventHandler, _on_execute, "OK"),
        (cmd.destroy, adsk.core.CommandEventHandler, _on_destroy, "close"),
    ):
        event.add(fh.make_handler(base, func, f"Hole Pattern: {label}", HANDLER_GROUP))


def _on_input_changed(args: adsk.core.InputChangedEventArgs) -> None:
    _describe(fh.all_inputs(args))


def _describe(inputs) -> None:
    size = ff.hole_size(_choice(inputs, ID_SCREW), _choice(inputs, ID_FIT))
    box = adsk.core.TextBoxCommandInput.cast(inputs.itemById(ID_INFO))
    count = _state.get("count")
    lines = [f"<b>{fh.safe_text(size.label)}</b> — {ff.FIT_HELP[size.fit]}."]
    if _state.get("error"):
        lines.append(f"⚠ {fh.safe_text(str(_state['error']))}")
    elif count is not None:
        lines.append(f"<b>{count}</b> hole(s) on a 0.5\" grid" + (f", wall {_state['wall']}" if _state.get("wall") else ""))
    box.formattedText = "<br>".join(lines)


def _selected_face(inputs):
    select = adsk.core.SelectionCommandInput.cast(inputs.itemById(ID_FACE))
    return adsk.fusion.BRepFace.cast(select.selection(0).entity) if select.selectionCount == 1 else None


def _build(inputs) -> int:
    """Make the sketch + cut. Used for the preview AND for OK. Returns the hole count."""
    face = _selected_face(inputs)
    if face is None:
        raise fb.FeatureError("Click a flat face.")
    size = ff.hole_size(_choice(inputs, ID_SCREW), _choice(inputs, ID_FIT))
    native, comp, _occ = fb.editable_face(face)
    sketch = fb.new_sketch(comp, native, f"Gusset holes {size.thread} {size.fit.lower()}")
    x0, y0, x1, y1 = fb.face_bounds_in_sketch(sketch, native)
    w_in, h_in = (x1 - x0) / fb.IN_TO_CM, (y1 - y0) / fb.IN_TO_CM
    along_x = w_in >= h_in
    length, width = (w_in, h_in) if along_x else (h_in, w_in)
    spots = ff.grid_positions(length, width, size.diameter_in, LAYOUTS[_choice(inputs, ID_LAYOUT)],
                              STARTS[_choice(inputs, ID_START)])
    radius_cm = size.diameter_in * fb.IN_TO_CM / 2
    placed = 0
    for a, b in spots:
        x = x0 + (a if along_x else b) * fb.IN_TO_CM
        y = y0 + (b if along_x else a) * fb.IN_TO_CM
        if fb.inside_face(sketch, native, x, y, radius_cm, ff.EDGE_MARGIN_IN * fb.IN_TO_CM):
            fb.add_circle(sketch, x, y, size.diameter_in)
            placed += 1
    if placed == 0:
        sketch.deleteMe()
        raise fb.FeatureError("No room for holes on this face with that screw size.")
    depth = None
    if DEPTHS[_choice(inputs, ID_DEPTH)] == "wall":
        depth = fb.wall_thickness_cm(native)
        _state["wall"] = f'{depth / fb.IN_TO_CM:.3f}"' if depth else "not found - drilling through everything"
    else:
        _state["wall"] = None
    profiles = [sketch.profiles.item(i) for i in range(sketch.profiles.count)]
    fb.cut(comp, profiles, native.body, depth, f"Gusset holes {size.thread} {size.fit.lower()} ({placed})")
    _log.info("Hole pattern: %d x %s on a %.3f x %.3f in face", placed, size.label, length, width)
    return placed


def _on_preview(args: adsk.core.CommandEventArgs) -> None:
    inputs = args.command.commandInputs
    _state.pop("error", None)
    try:
        _state["count"] = _build(inputs)
        args.isValidResult = True          # the preview IS the result, so OK is instant
    except fb.FeatureError as exc:
        _state["error"], _state["count"] = str(exc), None
    _describe(inputs)


def _on_validate(args: adsk.core.ValidateInputsEventArgs) -> None:
    args.areInputsValid = _selected_face(fh.all_inputs(args)) is not None


def _on_execute(args: adsk.core.CommandEventArgs) -> None:
    # Only runs if the preview didn't already produce the result.
    _, ui = fh.app_ui()
    try:
        count = _build(args.command.commandInputs)
        _log.info("Hole Pattern done: %d holes", count)
    except fb.FeatureError as exc:
        ui.messageBox(str(exc), "Gusset - Hole Pattern")
        args.executeFailed = True


def _on_destroy(args: adsk.core.CommandEventArgs) -> None:
    _state.clear()
    fh.release_handlers(HANDLER_GROUP)
