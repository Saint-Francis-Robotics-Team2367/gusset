"""
Lighten - pockets a plate in one step (Gusset's take on Onshape's Robot Lighten).

  1. GUSSET > Lighten, click the flat face of the plate.
  2. Pick where the ribs come from:
       Quick Rib (automatic) - ribs connect the holes in triangles
       Ribs from my sketch   - every line/arc/circle in your sketch becomes a rib
                               (construction lines are ignored)
       No ribs               - one big pocket inside the outside wall
  3. Pick the cutter (sets how round the inside corners are) and Through or a
     set pocket depth. Adjust the wall, rib and hole-ring widths if you want.
  4. Watch the preview - it shows the weight saved.
  5. Want a pocket left solid (a spot for a sensor, a label, a clamp)? Tick
     "Click pockets to keep solid" and click inside it on the plate. Click it
     again to cut it after all. Then press OK.

Everything lands in one timeline group named "Gusset lighten": a sketch (hidden),
the pocket cut and the corner rounds. Changed the plate? Delete the group and run
Lighten again - that's quicker than fixing old pockets.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional  # noqa: F401 (Optional used in string annotations)

import adsk.core
import adsk.fusion

from .. import config
from ..lib import feature_builder as fb
from ..lib import fusion_helpers as fh
from ..lib import lighten_builder as lb
from ..lib import lighten_core as lc
from ..lib import log as gslog
from ..lib import settings
from ..lib import tip_box

CMD_ID = "Gusset_Lighten"
CMD_NAME = "Lighten"
CMD_TOOLTIP = ("Pocket a plate in one step: outside wall, rings around holes, ribs (automatic or from your "
               "sketch), corners rounded for your cutter. Shows the weight saved.")
ICON_DIR = os.path.join(config.ADDIN_DIR, "resources", "lighten")
HANDLER_GROUP = "lighten_dialog"

_log = gslog.get_logger("lighten")

(ID_FACE, ID_SOURCE, ID_SKETCH, ID_CUTTER, ID_DEPTH_MODE, ID_DEPTH, ID_WALL, ID_RIB, ID_BOSS, ID_MIN,
 ID_PREVIEW, ID_INFO, ID_HELP, ID_PICK, ID_CLEAR) = (
    "lt_face", "lt_source", "lt_sketch", "lt_cutter", "lt_depth_mode", "lt_depth", "lt_wall", "lt_rib",
    "lt_boss", "lt_min", "lt_preview", "lt_info", "lt_help", "lt_pick", "lt_clear")

SRC_QUICK, SRC_SKETCH, SRC_NONE = ("Quick Rib - connect the holes (automatic)", "Ribs from my sketch",
                                   "No ribs - just the outside wall")
DEPTH_THROUGH, DEPTH_POCKET = "Through", "Pocket (set depth)"

HELP = (
    "<b>Wall</b>: material kept around the outside. <b>Rib</b>: width of each rib. "
    "<b>Hole ring</b>: material kept around every hole and bearing. "
    "<b>Smallest pocket</b>: anything narrower stays solid (tiny pockets save almost no weight but take a "
    "long time to cut).<br>"
    "<b>Ribs from my sketch</b>: draw lines between the load points (holes, bearings, bolts) on a sketch in the "
    "same part - or run <b>Quick Rib</b> first and delete the lines you don't want.<br>"
    "<b>Tip:</b> lighten LAST, after design review. Changed the plate? Delete the 'Gusset lighten' group in "
    "the timeline and run Lighten again."
)

STATE_KEY = "lighten"
_state: Dict[str, object] = {}


def start() -> None:
    fh.add_button(CMD_ID, CMD_NAME, CMD_TOOLTIP, ICON_DIR, _on_created,
                  config.PANEL_FEATURES_ID, config.PANEL_FEATURES_NAME)


def stop() -> None:
    fh.remove_button(CMD_ID, config.PANEL_FEATURES_ID)


def remembered() -> Dict[str, object]:
    """Last-used widths (shared with Quick Rib), falling back to the team settings."""
    values: Dict[str, object] = dict(settings.read_lighten_defaults(config.ADDIN_DIR))
    saved = settings.load_state(config.ADDIN_DIR).get(STATE_KEY)
    if isinstance(saved, dict):
        values.update(saved)
    return values


def remember(**values) -> None:
    saved = settings.load_state(config.ADDIN_DIR).get(STATE_KEY)
    merged = dict(saved) if isinstance(saved, dict) else {}
    merged.update(values)
    settings.save_state(config.ADDIN_DIR, **{STATE_KEY: merged})


def _inches(inputs, input_id: str, label: str, value_in: float, tooltip: str):
    vi = inputs.addValueInput(input_id, label, "in", adsk.core.ValueInput.createByString(f"{float(value_in)} in"))
    vi.tooltip = tooltip
    return vi


def _value_in(inputs, input_id: str) -> float:
    return adsk.core.ValueCommandInput.cast(inputs.itemById(input_id)).value / fb.IN_TO_CM


def _choice(inputs, input_id: str) -> str:
    item = adsk.core.DropDownCommandInput.cast(inputs.itemById(input_id)).selectedItem
    return item.name if item else ""


def _dropdown(inputs, input_id: str, label: str, choices: List[str], selected: str):
    dd = inputs.addDropDownCommandInput(input_id, label, adsk.core.DropDownStyles.TextListDropDownStyle)
    pick = selected if selected in choices else (choices[0] if choices else "")
    for choice in choices:
        dd.listItems.add(choice, choice == pick)
    return dd


def _on_created(args: adsk.core.CommandCreatedEventArgs) -> None:
    _log.info("Lighten opened")
    cmd = args.command
    _, ui = fh.app_ui()
    if not fh.active_design():
        ui.messageBox("Open a Fusion design first, then try Lighten again.", "Gusset")
        return
    _state.clear()
    _state["cutters"] = {c.name: c for c in settings.read_cutters(config.ADDIN_DIR)}
    _state["keep"] = []          # clicked spots, (x, y, z) cm in the plate component's space
    _state["cmd"] = cmd
    last = remembered()
    _log.debug("Lighten defaults: %s", last)
    try:
        cmd.setDialogInitialSize(460, 640)
    except Exception:
        pass

    inputs = cmd.commandInputs
    tip_box.attach(cmd, CMD_ID)              # 'How to use this' + hover tips (0.13)
    face = inputs.addSelectionInput(ID_FACE, "Plate face", "Click the flat face of the plate")
    face.addSelectionFilter("PlanarFaces")
    face.setSelectionLimits(1, 1)
    _dropdown(inputs, ID_SOURCE, "Ribs", [SRC_QUICK, SRC_SKETCH, SRC_NONE], str(last.get("source", SRC_QUICK)))
    sketch = inputs.addSelectionInput(ID_SKETCH, "Rib sketch", "Click your rib sketch (or any line in it)")
    for selection_filter in ("Sketches", "SketchCurves"):
        sketch.addSelectionFilter(selection_filter)
    sketch.setSelectionLimits(0, 1)
    _dropdown(inputs, ID_CUTTER, "Cutter", list(_state["cutters"]), str(last.get("cutter", "")))  # type: ignore[arg-type]
    _dropdown(inputs, ID_DEPTH_MODE, "Depth", [DEPTH_THROUGH, DEPTH_POCKET], str(last.get("depth_mode", DEPTH_THROUGH)))
    _inches(inputs, ID_DEPTH, "Pocket depth", float(last.get("pocket_depth_in", 0.1) or 0.1),  # type: ignore[arg-type]
            "How deep each pocket goes (it leaves a floor). Must leave at least 0.03\" of floor.")
    _inches(inputs, ID_WALL, "Wall", last["wall_in"], "Material kept around the outside of the plate")  # type: ignore[arg-type]
    _inches(inputs, ID_RIB, "Rib", last["rib_in"], "Width of every rib")  # type: ignore[arg-type]
    _inches(inputs, ID_BOSS, "Hole ring", last["boss_in"], "Material kept around every hole and bearing")  # type: ignore[arg-type]
    _inches(inputs, ID_MIN, "Smallest pocket", last["min_pocket_in"],  # type: ignore[arg-type]
            "Pockets narrower than this are left solid")
    inputs.addBoolValueInput(ID_PREVIEW, "Live preview", True, "", bool(last.get("preview", True)))
    pick = inputs.addBoolValueInput(ID_PICK, "Click pockets to keep solid", True, "", False)
    pick.tooltip = ("Tick this, then click inside a pocket on the plate to leave it solid. Click it again to cut "
                    "it after all. Untick to go back to picking faces.")
    inputs.addBoolValueInput(ID_CLEAR, "", False, "", False).text = "Cut all pockets again"
    inputs.addTextBoxCommandInput(ID_INFO, "", "Click the plate face.", 4, True)
    inputs.addTextBoxCommandInput(ID_HELP, "", HELP, 7, True)
    _show_hide(inputs)

    for event, base, func, label in (
        (cmd.inputChanged, adsk.core.InputChangedEventHandler, _on_input_changed, "input changed"),
        (cmd.executePreview, adsk.core.CommandEventHandler, _on_preview, "preview"),
        (cmd.validateInputs, adsk.core.ValidateInputsEventHandler, _on_validate, "validate"),
        (cmd.execute, adsk.core.CommandEventHandler, _on_execute, "OK"),
        (cmd.destroy, adsk.core.CommandEventHandler, _on_destroy, "close"),
        (cmd.mouseClick, adsk.core.MouseEventHandler, _on_click, "click"),
    ):
        event.add(fh.make_handler(base, func, f"Lighten: {label}", HANDLER_GROUP))


def _picking(inputs) -> bool:
    return adsk.core.BoolValueCommandInput.cast(inputs.itemById(ID_PICK)).value


def _show_hide(inputs) -> None:
    inputs.itemById(ID_SKETCH).isVisible = _choice(inputs, ID_SOURCE) == SRC_SKETCH
    inputs.itemById(ID_DEPTH).isVisible = _choice(inputs, ID_DEPTH_MODE) == DEPTH_POCKET
    # While picking pockets, clicks must not change the face/sketch selections.
    picking = _picking(inputs)
    for input_id in (ID_FACE, ID_SKETCH):
        inputs.itemById(input_id).isEnabled = not picking
    inputs.itemById(ID_CLEAR).isVisible = bool(_state.get("keep"))


def _params(inputs) -> lc.LightenParams:
    cutter = _state["cutters"].get(_choice(inputs, ID_CUTTER))  # type: ignore[union-attr]
    depth = _value_in(inputs, ID_DEPTH) if _choice(inputs, ID_DEPTH_MODE) == DEPTH_POCKET else None
    return lc.LightenParams(wall_in=_value_in(inputs, ID_WALL), rib_in=_value_in(inputs, ID_RIB),
                            boss_in=_value_in(inputs, ID_BOSS),
                            corner_in=cutter.corner_in if cutter else 0.0675,
                            min_pocket_in=_value_in(inputs, ID_MIN), depth_in=depth)


def _describe(inputs) -> None:
    box = adsk.core.TextBoxCommandInput.cast(inputs.itemById(ID_INFO))
    lines: List[str] = []
    try:
        p = _params(inputs)
        lines.append(f"Inside corners rounded to <b>R{p.corner_in:.4f}\"</b> for the {fh.safe_text(_choice(inputs, ID_CUTTER))}")
    except Exception:
        pass
    if _state.get("thk"):
        lines.append(f"Plate {_state['thk']:.3f}\" thick")
    if _state.get("ribs") is not None:
        lines.append(f"{_state['ribs']} rib(s)")
    if _state.get("result"):
        lines.extend(_state["result"].lines())  # type: ignore[union-attr]
    if _state.get("error"):
        lines.append("<b>Can't lighten yet:</b> " + fh.safe_text(str(_state["error"])))
    if not adsk.core.BoolValueCommandInput.cast(inputs.itemById(ID_PREVIEW)).value and not _state.get("error"):
        lines.append("Live preview is off - press OK to cut.")
    box.formattedText = "<br>".join(lines) or "Click the plate face."


def _on_input_changed(args: adsk.core.InputChangedEventArgs) -> None:
    if args.input.id == ID_CLEAR:
        _state["keep"] = []
        _log.info("Lighten: cleared kept pockets")
    elif args.input.id == ID_FACE:
        _state["keep"] = []          # a different plate: old clicks don't apply
    _show_hide(fh.all_inputs(args))
    _describe(fh.all_inputs(args))


def _click_point(args) -> "Optional[adsk.core.Point3D]":
    """Where a click in the canvas lands on the plate's plane (assembly space), or None."""
    vp, pos = args.viewport, args.viewportPosition
    face_sel = adsk.core.SelectionCommandInput.cast(_state["cmd"].commandInputs.itemById(ID_FACE))  # type: ignore[union-attr]
    if vp is None or pos is None or face_sel.selectionCount != 1:
        return None
    plane = adsk.core.Plane.cast(adsk.fusion.BRepFace.cast(face_sel.selection(0).entity).geometry)
    near = vp.viewToModelSpace(pos)
    cam = vp.camera
    if cam.cameraType == adsk.core.CameraTypes.PerspectiveCameraType:
        ray = cam.eye.vectorTo(near)
    else:
        ray = cam.eye.vectorTo(cam.target)
    n = plane.normal
    denom = ray.dotProduct(n)
    if abs(denom) < 1e-9:
        return None                   # looking edge-on at the plate
    t = near.vectorTo(plane.origin).dotProduct(n) / denom
    ray.scaleBy(t)
    hit = near.copy()
    hit.translateBy(ray)
    return hit


def _to_sketch_in(point_comp) -> "lc.Pt":
    """Component-space point (cm) -> 2D inches in the last preview's lighten sketch."""
    p = point_comp.copy()
    p.transformBy(_state["to_sketch"])  # type: ignore[arg-type]
    return (p.x / fb.IN_TO_CM, p.y / fb.IN_TO_CM)


def _on_click(args: adsk.core.MouseEventArgs) -> None:
    cmd = _state.get("cmd")
    if cmd is None or not _picking(cmd.commandInputs) or "to_sketch" not in _state:  # type: ignore[union-attr]
        return
    hit = _click_point(args)
    if hit is None:
        return
    comp_pt = fb.to_component_space(hit, _state.get("occ"))
    here = _to_sketch_in(comp_pt)
    keep = _state["keep"]  # type: ignore[assignment]
    for outer, inners, was_kept in _state.get("regions", []):  # type: ignore[union-attr]
        if not lc.in_region(here, outer, inners):
            continue
        if was_kept:
            # Clicked a kept pocket: cut it after all (forget every click inside it).
            keep[:] = [k for k in keep  # type: ignore[index]
                       if not lc.in_region(_to_sketch_in(adsk.core.Point3D.create(*k)), outer, inners)]
            _log.info("Lighten: pocket at (%.2f, %.2f) in will be cut", *here)
        else:
            keep.append((comp_pt.x, comp_pt.y, comp_pt.z))  # type: ignore[union-attr]
            _log.info("Lighten: pocket at (%.2f, %.2f) in kept solid", *here)
        _show_hide(cmd.commandInputs)  # type: ignore[union-attr]
        if not cmd.doExecutePreview():  # type: ignore[union-attr]
            _log.debug("doExecutePreview returned False")
        return
    _log.debug("Click at (%.2f, %.2f) in isn't in a pocket", *here)


def _build(inputs) -> lb.LightenResult:
    face_sel = adsk.core.SelectionCommandInput.cast(inputs.itemById(ID_FACE))
    if face_sel.selectionCount != 1:
        raise fb.FeatureError("Click the flat face of the plate.")
    face = adsk.fusion.BRepFace.cast(face_sel.selection(0).entity)
    native, comp, occ = fb.editable_face(face)
    _state["occ"] = occ
    params = _params(inputs)
    source = _choice(inputs, ID_SOURCE)

    sketch = fb.new_sketch(comp, native, "Gusset lighten")
    try:
        info = lb.read_plate(sketch, native)
        _state["thk"] = info.thickness_in
        to_sketch = sketch.transform.copy()     # component space -> this sketch's 2D space
        to_sketch.invert()
        _state["to_sketch"] = to_sketch
        curvy = []
        if source == SRC_QUICK:
            ribs = lc.quick_ribs(info.plate, params, float(remembered().get("max_span_in", 4.0)))  # type: ignore[arg-type]
        elif source == SRC_SKETCH:
            sel = adsk.core.SelectionCommandInput.cast(inputs.itemById(ID_SKETCH))
            rib_sketch = lb.selected_sketch(sel.selection(0).entity) if sel.selectionCount else None
            if rib_sketch is None:
                raise fb.FeatureError("Click your rib sketch (or any line in it).")
            ribs, used, curvy = lb.read_sketch_ribs(rib_sketch, sketch, comp)
            if not used:
                raise fb.FeatureError("That sketch has no rib lines (construction and projected lines are skipped).")
        else:
            ribs = []
        _state["ribs"] = len(ribs)
        keep_in = [_to_sketch_in(adsk.core.Point3D.create(*k)) for k in _state.get("keep", [])]  # type: ignore[union-attr]
        result = lb.lighten(comp, native, sketch, info, ribs, params, curvy=curvy, keep_points=keep_in)
        _state["regions"] = result.regions
        return result
    except Exception:
        # Don't leave a half-made sketch behind (the preview is undone anyway; OK isn't).
        try:
            if sketch.isValid:
                sketch.deleteMe()
        except Exception:
            pass
        raise


def _on_preview(args: adsk.core.CommandEventArgs) -> None:
    inputs = args.command.commandInputs
    for key in ("error", "result"):
        _state.pop(key, None)
    if not adsk.core.BoolValueCommandInput.cast(inputs.itemById(ID_PREVIEW)).value:
        _describe(inputs)
        return
    try:
        _state["result"] = _build(inputs)
        args.isValidResult = True          # the preview IS the result, so OK is instant
    except fb.FeatureError as exc:
        _state["error"] = str(exc)
    except Exception:
        fh.report_error("Lighten preview", show_dialog=False)
        _state["error"] = "Something went wrong - see the Text Commands window / gusset.log."
    _describe(inputs)


def _on_validate(args: adsk.core.ValidateInputsEventArgs) -> None:
    inputs = fh.all_inputs(args)
    ok = adsk.core.SelectionCommandInput.cast(inputs.itemById(ID_FACE)).selectionCount == 1
    if _choice(inputs, ID_SOURCE) == SRC_SKETCH:
        ok = ok and adsk.core.SelectionCommandInput.cast(inputs.itemById(ID_SKETCH)).selectionCount == 1
    try:
        ok = ok and not lc.check_params(_params(inputs), _state.get("thk"))  # type: ignore[arg-type]
    except Exception:
        ok = False
    args.areInputsValid = ok


def _save_choices(inputs) -> None:
    try:
        p = _params(inputs)
        remember(source=_choice(inputs, ID_SOURCE), cutter=_choice(inputs, ID_CUTTER),
                 depth_mode=_choice(inputs, ID_DEPTH_MODE), pocket_depth_in=_value_in(inputs, ID_DEPTH),
                 wall_in=p.wall_in, rib_in=p.rib_in, boss_in=p.boss_in, min_pocket_in=p.min_pocket_in,
                 preview=adsk.core.BoolValueCommandInput.cast(inputs.itemById(ID_PREVIEW)).value)
    except Exception as exc:
        _log.debug("Couldn't remember Lighten choices: %s", exc)


def _on_execute(args: adsk.core.CommandEventArgs) -> None:
    # Only runs if the preview didn't already produce the result (e.g. live preview off).
    _, ui = fh.app_ui()
    inputs = args.command.commandInputs
    _save_choices(inputs)
    try:
        result = _build(inputs)
        _log.info("Lighten done: %s", "; ".join(result.lines()))
    except fb.FeatureError as exc:
        ui.messageBox(str(exc), "Gusset - Lighten")
        args.executeFailed = True


def _on_destroy(args: adsk.core.CommandEventArgs) -> None:
    # A finished preview skips execute, so remember choices here too.
    try:
        if args.terminationReason == adsk.core.CommandTerminationReason.CompletedTerminationReason:
            _save_choices(args.command.commandInputs)
    except Exception:
        pass
    _state.clear()
    fh.release_handlers(HANDLER_GROUP)
