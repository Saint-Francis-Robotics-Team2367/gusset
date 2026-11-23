"""
Quick Rib - draws rib lines on a plate for you, connecting the holes in triangles.

  1. GUSSET > Quick Rib, click the flat face of the plate.
  2. Watch the preview. Quick Rib works the way designers rib a plate by hand:
       - holes in a row get one rib through them
       - a bolt circle around a bearing gets a curved rib through its holes
       - bearings get spokes out to the edge and to their neighbours
       - leftover space gets triangles
       - then it checks EVERY hole is held from two sides (two ribs at least
         90 degrees apart, or the wall plus one rib) and adds ribs where not.
  3. Press OK. You get a normal sketch called "Gusset ribs" - delete lines you
     don't want, add your own (construction lines are ignored later).
  4. Run Lighten with "Ribs from my sketch" and click that sketch.

Why triangles? A triangle can't fold up, so a plate with a triangle pattern of
ribs stays stiff while losing most of its weight. Every hole keeps a rib to its
neighbours so the load has a path through the plate.
"""

from __future__ import annotations

import os
from typing import Dict

import adsk.core
import adsk.fusion

from .. import config
from ..lib import feature_builder as fb
from ..lib import fusion_helpers as fh
from ..lib import lighten_builder as lb
from ..lib import lighten_core as lc
from ..lib import log as gslog
from ..lib import tip_box
from . import lighten

CMD_ID = "Gusset_QuickRib"
CMD_NAME = "Quick Rib"
CMD_TOOLTIP = ("Draw rib lines on a plate automatically (holes connected in triangles), as a sketch you can "
               "edit. Then use Lighten > Ribs from my sketch.")
ICON_DIR = os.path.join(config.ADDIN_DIR, "resources", "quick_rib")
HANDLER_GROUP = "quick_rib_dialog"

_log = gslog.get_logger("quick_rib")

ID_FACE, ID_WALL, ID_BOSS, ID_SPAN, ID_INFO, ID_HELP = (
    "qr_face", "qr_wall", "qr_boss", "qr_span", "qr_info", "qr_help")

HELP = (
    "<b>What you get:</b> a sketch named 'Gusset ribs' on the plate. It's yours to edit: delete a line, "
    "drag one, or draw more. Then run <b>Lighten</b> and pick <b>Ribs from my sketch</b>.<br>"
    "<b>Edge spacing</b>: on long plates a rib reaches the edge at least this often. Smaller = more ribs.<br>"
    "<b>Wall / hole ring</b>: use the same values you'll use in Lighten, so Quick Rib skips ribs that would "
    "only make slivers."
)

_state: Dict[str, object] = {}


def start() -> None:
    fh.add_button(CMD_ID, CMD_NAME, CMD_TOOLTIP, ICON_DIR, _on_created,
                  config.PANEL_FEATURES_ID, config.PANEL_FEATURES_NAME)


def stop() -> None:
    fh.remove_button(CMD_ID, config.PANEL_FEATURES_ID)


def _on_created(args: adsk.core.CommandCreatedEventArgs) -> None:
    _log.info("Quick Rib opened")
    cmd = args.command
    _, ui = fh.app_ui()
    if not fh.active_design():
        ui.messageBox("Open a Fusion design first, then try Quick Rib again.", "Gusset")
        return
    _state.clear()
    last = lighten.remembered()
    inputs = cmd.commandInputs
    tip_box.attach(cmd, CMD_ID)              # 'How to use this' + hover tips (0.13)
    face = inputs.addSelectionInput(ID_FACE, "Plate face", "Click the flat face of the plate")
    face.addSelectionFilter("PlanarFaces")
    face.setSelectionLimits(1, 1)
    lighten._inches(inputs, ID_WALL, "Wall", last["wall_in"], "Material Lighten will keep around the outside")  # type: ignore[arg-type]
    lighten._inches(inputs, ID_BOSS, "Hole ring", last["boss_in"], "Material Lighten will keep around holes")  # type: ignore[arg-type]
    lighten._inches(inputs, ID_SPAN, "Edge spacing", last["max_span_in"],  # type: ignore[arg-type]
                    "Ribs reach the plate's edge at least this often")
    inputs.addTextBoxCommandInput(ID_INFO, "", "Click the plate face.", 4, True)
    inputs.addTextBoxCommandInput(ID_HELP, "", HELP, 6, True)

    for event, base, func, label in (
        (cmd.inputChanged, adsk.core.InputChangedEventHandler, _on_input_changed, "input changed"),
        (cmd.executePreview, adsk.core.CommandEventHandler, _on_preview, "preview"),
        (cmd.validateInputs, adsk.core.ValidateInputsEventHandler, _on_validate, "validate"),
        (cmd.execute, adsk.core.CommandEventHandler, _on_execute, "OK"),
        (cmd.destroy, adsk.core.CommandEventHandler, _on_destroy, "close"),
    ):
        event.add(fh.make_handler(base, func, f"Quick Rib: {label}", HANDLER_GROUP))


def _describe(inputs) -> None:
    box = adsk.core.TextBoxCommandInput.cast(inputs.itemById(ID_INFO))
    if _state.get("error"):
        box.formattedText = "<b>Can't add ribs:</b> " + fh.safe_text(str(_state["error"]))
    elif _state.get("count") is not None:
        kinds = _state.get("kinds", {})
        parts = [f"{n} {label}" for label, n in (("row", kinds.get("row", 0)), ("bolt-circle arc", kinds.get("arc", 0)),
                                                 ("bearing spoke", kinds.get("spoke", 0)),
                                                 ("triangle", kinds.get("fill", 0)), ("support", kinds.get("support", 0)))
                 if n]
        text = (f"<b>{_state['count']}</b> rib(s) for {_state['holes']} hole(s): {', '.join(parts)}.<br>")
        if _state.get("unsupported"):
            text += (f"⚠ {_state['unsupported']} hole(s) couldn't get ribs from two sides (no room) - check "
                     "them, or add a line yourself.<br>")
        else:
            text += "Every hole is held from two sides (or by the wall + a rib).<br>"
        box.formattedText = text + "Press OK, edit the sketch if you like, then run <b>Lighten</b>."
    else:
        box.formattedText = "Click the plate face."


def _on_input_changed(args: adsk.core.InputChangedEventArgs) -> None:
    _describe(fh.all_inputs(args))


def _build(inputs) -> int:
    sel = adsk.core.SelectionCommandInput.cast(inputs.itemById(ID_FACE))
    if sel.selectionCount != 1:
        raise fb.FeatureError("Click the flat face of the plate.")
    native, comp, _occ = fb.editable_face(adsk.fusion.BRepFace.cast(sel.selection(0).entity))
    params = lc.LightenParams(wall_in=lighten._value_in(inputs, ID_WALL), boss_in=lighten._value_in(inputs, ID_BOSS),
                              rib_in=float(lighten.remembered()["rib_in"]),  # type: ignore[arg-type]
                              min_pocket_in=float(lighten.remembered()["min_pocket_in"]))  # type: ignore[arg-type]
    span = lighten._value_in(inputs, ID_SPAN)
    if span < 0.5:
        raise fb.FeatureError('Edge spacing must be at least 0.5".')
    sketch = fb.new_sketch(comp, native, "Gusset ribs")
    try:
        info = lb.read_plate(sketch, native)
        ribs = lc.quick_ribs(info.plate, params, span)
        if not ribs:
            raise fb.FeatureError("This plate is too small (or too full of holes) for ribs. Try Lighten with "
                                  "'No ribs', or a smaller wall / hole ring.")
        count = lb.draw_rib_lines(sketch, ribs)
        _state["kinds"] = {k: sum(1 for r in ribs if r.kind == k) for k in ("row", "arc", "spoke", "fill", "support")}
        _state["unsupported"] = len(lc.unsupported_holes(info.plate, ribs, params))
    except Exception:
        try:
            if sketch.isValid:
                sketch.deleteMe()
        except Exception:
            pass
        raise
    _state["holes"] = sum(1 for h in info.plate.holes if h.center is not None)
    _log.info("Quick Rib: %d ribs, %d round holes, span %.2f in", count, _state["holes"], span)
    return count


def _on_preview(args: adsk.core.CommandEventArgs) -> None:
    inputs = args.command.commandInputs
    _state.pop("error", None)
    try:
        _state["count"] = _build(inputs)
        args.isValidResult = True
    except fb.FeatureError as exc:
        _state["error"], _state["count"] = str(exc), None
    except Exception:
        fh.report_error("Quick Rib preview", show_dialog=False)
        _state["error"], _state["count"] = "Something went wrong - see the Text Commands window / gusset.log.", None
    _describe(inputs)


def _on_validate(args: adsk.core.ValidateInputsEventArgs) -> None:
    args.areInputsValid = adsk.core.SelectionCommandInput.cast(fh.all_inputs(args).itemById(ID_FACE)).selectionCount == 1


def _save(inputs) -> None:
    try:
        lighten.remember(wall_in=lighten._value_in(inputs, ID_WALL), boss_in=lighten._value_in(inputs, ID_BOSS),
                         max_span_in=lighten._value_in(inputs, ID_SPAN), source=lighten.SRC_SKETCH)
    except Exception as exc:
        _log.debug("Couldn't remember Quick Rib choices: %s", exc)


def _on_execute(args: adsk.core.CommandEventArgs) -> None:
    _, ui = fh.app_ui()
    _save(args.command.commandInputs)
    try:
        _build(args.command.commandInputs)
    except fb.FeatureError as exc:
        ui.messageBox(str(exc), "Gusset - Quick Rib")
        args.executeFailed = True


def _on_destroy(args: adsk.core.CommandEventArgs) -> None:
    try:
        if args.terminationReason == adsk.core.CommandTerminationReason.CompletedTerminationReason:
            _save(args.command.commandInputs)
    except Exception:
        pass
    _state.clear()
    fh.release_handlers(HANDLER_GROUP)
