"""
Bearing Pocket - cuts a correctly sized hole or pocket for a bearing.

  1. GUSSET > Bearing Pocket, click the flat face of the plate.
  2. Click where the bearing goes: a sketch point, a vertex, or an existing
     round hole/edge (its center is used). Pick several to do many at once.
  3. Pick the bearing, the fit (Press / Snug / Slip / 3D print) and the type:
       Through hole  - flanged bearing: the flange rests on the plate
       Pocket        - bearing-width-deep pocket + a smaller hole for the shaft
  4. Watch the preview, then press OK.

Laying out a plate before it's a body? Set "Output" to "Draw circles in a sketch"
and click your layout sketch instead of a face: Gusset adds correctly sized
circles (bearing hole, plus the shaft hole for a pocket) to that sketch and
cuts nothing, so you can extrude it later.

Bought a new bearing, or want to tune a fit after cutting a test plate? Open
the "Bearing library" section at the bottom of this dialog: edit any number,
add or remove bearings and fits, and press "Save library". It's saved to
gusset_config.json, so the whole team's copy can share it.
"""

from __future__ import annotations

import math
import os
from typing import Dict, List, Optional, Tuple

import adsk.core
import adsk.fusion

from .. import config
from ..lib import feature_builder as fb
from ..lib import frc_features as ff
from ..lib import fusion_helpers as fh
from ..lib import log as gslog
from ..lib import settings
from ..lib import tip_box

CMD_ID = "Gusset_BearingPocket"
CMD_NAME = "Bearing Pocket"
CMD_TOOLTIP = ("Cut a bearing hole or pocket at the right size - or just draw the circles into a sketch. "
               "Pick the center(s), the bearing and the fit. Edit or add bearings in the Bearing library.")
ICON_DIR = os.path.join(config.ADDIN_DIR, "resources", "bearing_pocket")
HANDLER_GROUP = "bearing_pocket_dialog"

_log = gslog.get_logger("bearing_pocket")

ID_FACE, ID_CENTERS, ID_BEARING, ID_FIT, ID_KIND, ID_INFO, ID_HELP = (
    "bp_face", "bp_centers", "bp_bearing", "bp_fit", "bp_kind", "bp_info", "bp_help")
ID_OUTPUT, ID_SKETCH = "bp_output", "bp_sketch"
OUT_CUT, OUT_SKETCH = "Cut the part", "Draw circles in a sketch"
ID_LIB, ID_BTABLE, ID_ADD_B, ID_DEL_B, ID_FTABLE, ID_ADD_F, ID_DEL_F, ID_SAVE, ID_LIB_MSG = (
    "bp_lib", "bp_btable", "bp_add_b", "bp_del_b", "bp_ftable", "bp_add_f", "bp_del_f", "bp_save", "bp_lib_msg")

KINDS = {"Through hole (flanged bearing)": ff.POCKET_THROUGH, "Pocket + shaft hole": ff.POCKET_BLIND}
BEARING_COLUMNS = [("Name", None), ("Bore", "bore_in"), ("OD", "od_in"), ("Width", "width_in"),
                   ("Flange OD", "flange_od_in"), ("Flange thk", "flange_thk_in")]

HELP = (
    "<b>Which fit?</b> Press: tap it in with a mallet (metal plates). Snug: pushes in by hand. "
    "Slip: drops in, held by the flange. 3D print: extra room because printed holes shrink.<br>"
    "<b>Tip:</b> fits depend on your machine. Cut a test plate with one hole of each fit, see which "
    "feels right, then tune the numbers in the Bearing library below.<br>"
    "<b>Through or pocket?</b> Flanged bearings usually go in a through hole, so the flange stops them. "
    "A pocket holds a bearing from one side, and needs a plate thicker than the bearing."
)

_state: Dict[str, object] = {}


def start() -> None:
    fh.add_button(CMD_ID, CMD_NAME, CMD_TOOLTIP, ICON_DIR, _on_created,
                  config.PANEL_FEATURES_ID, config.PANEL_FEATURES_NAME)


def stop() -> None:
    fh.remove_button(CMD_ID, config.PANEL_FEATURES_ID)


def _choice(inputs, input_id: str) -> str:
    item = adsk.core.DropDownCommandInput.cast(inputs.itemById(input_id)).selectedItem
    return item.name if item else ""


def _load_library() -> None:
    bearings = settings.read_bearings(config.ADDIN_DIR)
    fits = settings.read_bearing_fits(config.ADDIN_DIR)
    _state.update(bearings={b.name: b for b in bearings}, fits=fits)
    _log.debug("Library: %d bearings, %d fits", len(bearings), len(fits))


def _fill_dropdown(dropdown, names: List[str], keep: str, default: str = "") -> None:
    dropdown.listItems.clear()
    pick = keep if keep in names else (default if default in names else (names[0] if names else ""))
    for name in names:
        dropdown.listItems.add(name, name == pick)


def _on_created(args: adsk.core.CommandCreatedEventArgs) -> None:
    _log.info("Bearing Pocket opened")
    cmd = args.command
    _, ui = fh.app_ui()
    if not fh.active_design():
        ui.messageBox("Open a Fusion design first, then try Bearing Pocket again.", "Gusset")
        return
    _state.clear()
    _state.update(busy=False, row_gen=0)
    _load_library()
    try:
        cmd.setDialogInitialSize(640, 720)
    except Exception:
        pass

    inputs = cmd.commandInputs
    tip_box.attach(cmd, CMD_ID)              # 'How to use this' + hover tips (0.13)
    last_output = str(settings.load_state(config.ADDIN_DIR).get("bearing_output", OUT_CUT))
    output = inputs.addDropDownCommandInput(ID_OUTPUT, "Output", adsk.core.DropDownStyles.TextListDropDownStyle)
    for name in (OUT_CUT, OUT_SKETCH):
        output.listItems.add(name, name == last_output if last_output in (OUT_CUT, OUT_SKETCH) else name == OUT_CUT)
    output.tooltip = "Cut a hole into a plate, or just draw the circles into a sketch (nothing is cut)"
    face = inputs.addSelectionInput(ID_FACE, "Plate face", "Click the flat face of the plate")
    face.addSelectionFilter("PlanarFaces")
    face.setSelectionLimits(0, 1)
    sketch_sel = inputs.addSelectionInput(ID_SKETCH, "Sketch", "Click the sketch to draw in (or any line in it)")
    for selection_filter in ("Sketches", "SketchCurves"):
        sketch_sel.addSelectionFilter(selection_filter)
    sketch_sel.setSelectionLimits(0, 1)
    centers = inputs.addSelectionInput(ID_CENTERS, "Center(s)", "Click sketch points, vertices or round edges")
    for selection_filter in ("SketchPoints", "Vertices", "CircularEdges"):
        centers.addSelectionFilter(selection_filter)
    centers.setSelectionLimits(1, 0)

    dd = inputs.addDropDownCommandInput(ID_BEARING, "Bearing", adsk.core.DropDownStyles.TextListDropDownStyle)
    _fill_dropdown(dd, list(_state["bearings"]), "")  # type: ignore[arg-type]
    fit = inputs.addDropDownCommandInput(ID_FIT, "Fit", adsk.core.DropDownStyles.TextListDropDownStyle)
    _fill_dropdown(fit, list(_state["fits"]), "", "Press")  # type: ignore[arg-type]
    kind = inputs.addDropDownCommandInput(ID_KIND, "Type", adsk.core.DropDownStyles.TextListDropDownStyle)
    for i, name in enumerate(KINDS):
        kind.listItems.add(name, i == 0)
    inputs.addTextBoxCommandInput(ID_INFO, "", "Click the plate face, then the center(s).", 4, True)
    inputs.addTextBoxCommandInput(ID_HELP, "", HELP, 6, True)
    _build_library_group(inputs)
    _show_hide(inputs)

    for event, base, func, label in (
        (cmd.inputChanged, adsk.core.InputChangedEventHandler, _on_input_changed, "input changed"),
        (cmd.executePreview, adsk.core.CommandEventHandler, _on_preview, "preview"),
        (cmd.validateInputs, adsk.core.ValidateInputsEventHandler, _on_validate, "validate"),
        (cmd.execute, adsk.core.CommandEventHandler, _on_execute, "OK"),
        (cmd.destroy, adsk.core.CommandEventHandler, _on_destroy, "close"),
    ):
        event.add(fh.make_handler(base, func, f"Bearing Pocket: {label}", HANDLER_GROUP))


def _sketch_mode(inputs) -> bool:
    return _choice(inputs, ID_OUTPUT) == OUT_SKETCH


def _show_hide(inputs) -> None:
    sketch_mode = _sketch_mode(inputs)
    inputs.itemById(ID_FACE).isVisible = not sketch_mode
    inputs.itemById(ID_SKETCH).isVisible = sketch_mode


# ---------------------------------------------------------------------------
# Bearing library editor (inside this dialog)
# ---------------------------------------------------------------------------
def _spinner(table_inputs, input_id: str, value: float):
    """A plain number box in inches (no unit conversion surprises)."""
    spin = table_inputs.addFloatSpinnerCommandInput(input_id, "", "", 0.0, 20.0, 0.0005, float(value))
    return spin


def _build_library_group(inputs) -> None:
    group = inputs.addGroupCommandInput(ID_LIB, "Bearing library (edit, add, save)")
    group.isExpanded = False
    kids = group.children
    kids.addTextBoxCommandInput(
        "bp_lib_help", "",
        "All sizes in <b>inches</b>. Change a number, add a bearing you just bought, or tune a fit after a "
        "test cut, then press <b>Save library</b>. Flange OD/thk = 0 means no flange.", 2, True)
    btable = kids.addTableCommandInput(ID_BTABLE, "Bearings", 6, "5:2:2:2:2:2")
    btable.maximumVisibleRows = 8
    btable.minimumVisibleRows = 3
    btable.tablePresentationStyle = adsk.core.TablePresentationStyles.itemBorderTablePresentationStyle
    kids.addBoolValueInput(ID_ADD_B, "", False, "", False).text = "Add bearing"
    kids.addBoolValueInput(ID_DEL_B, "", False, "", False).text = "Remove selected bearing"
    ftable = kids.addTableCommandInput(ID_FTABLE, "Fits (inches added to the bearing OD)", 2, "5:2")
    ftable.maximumVisibleRows = 6
    ftable.minimumVisibleRows = 2
    ftable.tablePresentationStyle = adsk.core.TablePresentationStyles.itemBorderTablePresentationStyle
    kids.addBoolValueInput(ID_ADD_F, "", False, "", False).text = "Add fit"
    kids.addBoolValueInput(ID_DEL_F, "", False, "", False).text = "Remove selected fit"
    kids.addBoolValueInput(ID_SAVE, "", False, "", False).text = "Save library"
    kids.addTextBoxCommandInput(ID_LIB_MSG, "", "", 2, True)
    _fill_library_tables(inputs)


def _fill_library_tables(inputs) -> None:
    """(Re)build both tables from the current library in _state."""
    btable = adsk.core.TableCommandInput.cast(inputs.itemById(ID_BTABLE))
    ftable = adsk.core.TableCommandInput.cast(inputs.itemById(ID_FTABLE))
    _state["busy"] = True
    try:
        gen = int(_state["row_gen"]) + 1  # type: ignore[arg-type]
        _state["row_gen"] = gen
        btable.clear()
        t = btable.commandInputs
        for col, (title, _key) in enumerate(BEARING_COLUMNS):
            btable.addCommandInput(t.addTextBoxCommandInput(f"bp_bh_{gen}_{col}", "", f"<b>{title}</b>", 1, True), 0, col)
        for row, b in enumerate(_state["bearings"].values(), start=1):  # type: ignore[union-attr]
            values = ff.bearing_to_dict(b)
            btable.addCommandInput(t.addStringValueInput(f"bp_bn_{gen}_{row}", "", b.name), row, 0)
            for col, (_title, key) in enumerate(BEARING_COLUMNS[1:], start=1):
                btable.addCommandInput(_spinner(t, f"bp_bv_{gen}_{row}_{col}", values[key]), row, col)
        ftable.clear()
        t = ftable.commandInputs
        ftable.addCommandInput(t.addTextBoxCommandInput(f"bp_fh_{gen}_0", "", "<b>Fit</b>", 1, True), 0, 0)
        ftable.addCommandInput(t.addTextBoxCommandInput(f"bp_fh_{gen}_1", "", "<b>+ inches</b>", 1, True), 0, 1)
        for row, (name, (allowance, why)) in enumerate(_state["fits"].items(), start=1):  # type: ignore[union-attr]
            name_in = t.addStringValueInput(f"bp_fn_{gen}_{row}", "", name)
            name_in.tooltip = why
            spin = t.addFloatSpinnerCommandInput(f"bp_fv_{gen}_{row}", "", "", -0.1, 0.1, 0.0005, float(allowance))
            spin.tooltip = "Negative = tighter than the bearing (press fit)"
            ftable.addCommandInput(name_in, row, 0)
            ftable.addCommandInput(spin, row, 1)
    finally:
        _state["busy"] = False


def _read_library_tables(inputs) -> Tuple[List[ff.Bearing], Dict[str, Tuple[float, str]], List[str]]:
    """Read what's typed in the tables. Returns (bearings, fits, problems)."""
    btable = adsk.core.TableCommandInput.cast(inputs.itemById(ID_BTABLE))
    ftable = adsk.core.TableCommandInput.cast(inputs.itemById(ID_FTABLE))
    problems: List[str] = []
    bearings: List[ff.Bearing] = []
    for row in range(1, btable.rowCount):
        name = adsk.core.StringValueCommandInput.cast(btable.getInputAtPosition(row, 0)).value.strip()
        nums = [adsk.core.FloatSpinnerCommandInput.cast(btable.getInputAtPosition(row, c)).value
                for c in range(1, len(BEARING_COLUMNS))]
        if not name:
            problems.append(f"bearing row {row} has no name")
            continue
        bore, od, width, flange_od, flange_thk = nums
        if od <= bore or width <= 0:
            problems.append(f"'{name}': the OD must be bigger than the bore, and the width above 0")
            continue
        if flange_od and flange_od <= od:
            problems.append(f"'{name}': the flange OD must be bigger than the OD (or 0 for no flange)")
            continue
        bearings.append(ff.Bearing(name, bore, od, width, flange_od, flange_thk))
    fits: Dict[str, Tuple[float, str]] = {}
    for row in range(1, ftable.rowCount):
        name = adsk.core.StringValueCommandInput.cast(ftable.getInputAtPosition(row, 0)).value.strip()
        value = adsk.core.FloatSpinnerCommandInput.cast(ftable.getInputAtPosition(row, 1)).value
        if name:
            fits[name] = (value, ff.DEFAULT_FITS.get(name, (0, "your team's fit"))[1])
    if len({b.name for b in bearings}) != len(bearings):
        problems.append("two bearings have the same name")
    if not bearings:
        problems.append("the library needs at least one bearing")
    if not fits:
        problems.append("the library needs at least one fit")
    return bearings, fits, problems


def _library_message(inputs, text: str) -> None:
    adsk.core.TextBoxCommandInput.cast(inputs.itemById(ID_LIB_MSG)).formattedText = text


def _handle_library(inputs, cid: str) -> None:
    bearings, fits, problems = _read_library_tables(inputs)
    if cid == ID_ADD_B:
        name, n = "New bearing", 2
        while name in {b.name for b in bearings}:
            name, n = f"New bearing {n}", n + 1
        bearings.append(ff.Bearing(name, 0.5, 1.125, 0.3125, 0.0, 0.0))
        _library_message(inputs, "Added a row at the bottom. Type the real sizes, then <b>Save library</b>.")
    elif cid == ID_DEL_B:
        table = adsk.core.TableCommandInput.cast(inputs.itemById(ID_BTABLE))
        row = table.selectedRow
        if row >= 1 and row - 1 < len(bearings) and len(bearings) > 1:
            removed = bearings.pop(row - 1)
            _library_message(inputs, f"Removed '{fh.safe_text(removed.name)}'. Press <b>Save library</b> to keep this.")
        else:
            _library_message(inputs, "Click a bearing's row first (and keep at least one bearing).")
    elif cid == ID_ADD_F:
        fits[f"Fit {len(fits) + 1}"] = (0.0, "your team's fit")
        _library_message(inputs, "Added a fit. Name it, set the inches, then <b>Save library</b>.")
    elif cid == ID_DEL_F:
        table = adsk.core.TableCommandInput.cast(inputs.itemById(ID_FTABLE))
        row = table.selectedRow
        names = list(fits)
        if row >= 1 and row - 1 < len(names) and len(names) > 1:
            fits.pop(names[row - 1])
            _library_message(inputs, "Removed that fit. Press <b>Save library</b> to keep this.")
        else:
            _library_message(inputs, "Click a fit's row first (and keep at least one fit).")
    elif cid == ID_SAVE:
        if problems:
            _library_message(inputs, "<b>Not saved:</b> " + fh.safe_text("; ".join(problems)))
            return
        try:
            # Bearings and fits are TEAM settings: saved on this laptop as a draft, which a
            # mentor publishes from GUSSET > Settings so every laptop gets them.
            settings.save_team_draft(config.ADDIN_DIR, {
                "bearings": [ff.bearing_to_dict(b) for b in bearings],
                "bearing_fits": {name: allowance for name, (allowance, _w) in fits.items()}})
            _library_message(inputs, f"<b>Saved</b> {len(bearings)} bearings and {len(fits)} fits on this "
                                     "laptop. A mentor can publish them to the team from GUSSET &gt; Settings.")
            _log.info("Bearing library saved: %d bearings, %d fits", len(bearings), len(fits))
        except Exception as exc:
            _library_message(inputs, f"<b>Couldn't save:</b> {fh.safe_text(str(exc))}")
            return
    # Use the edited library right away (saved or not), and refresh the tables + dropdowns.
    _state["bearings"] = {b.name: b for b in bearings}
    _state["fits"] = fits
    if cid != ID_SAVE:
        _fill_library_tables(inputs)
    _refresh_dropdowns(inputs)


def _refresh_dropdowns(inputs) -> None:
    _state["busy"] = True
    try:
        _fill_dropdown(adsk.core.DropDownCommandInput.cast(inputs.itemById(ID_BEARING)),
                       list(_state["bearings"]), _choice(inputs, ID_BEARING))  # type: ignore[arg-type]
        _fill_dropdown(adsk.core.DropDownCommandInput.cast(inputs.itemById(ID_FIT)),
                       list(_state["fits"]), _choice(inputs, ID_FIT), "Press")  # type: ignore[arg-type]
    finally:
        _state["busy"] = False


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
def _on_input_changed(args: adsk.core.InputChangedEventArgs) -> None:
    if _state.get("busy"):
        return
    cid = args.input.id
    if cid in (ID_ADD_B, ID_DEL_B, ID_ADD_F, ID_DEL_F, ID_SAVE):
        _handle_library(fh.all_inputs(args), cid)
    elif cid.startswith(("bp_bn_", "bp_bv_", "bp_fn_", "bp_fv_")):
        # Typing in the library: use the numbers for the preview right away (not saved yet).
        bearings, fits, problems = _read_library_tables(fh.all_inputs(args))
        if not problems:
            _state["bearings"] = {b.name: b for b in bearings}
            _state["fits"] = fits
            _refresh_dropdowns(fh.all_inputs(args))
            _library_message(fh.all_inputs(args), "Changed (preview uses it). Press <b>Save library</b> to keep it.")
    elif cid == ID_OUTPUT:
        _show_hide(fh.all_inputs(args))
        _state["thk"] = None
    _describe(fh.all_inputs(args))


def _plan(inputs, plate_thk_in: Optional[float]) -> Tuple[ff.Bearing, str, ff.PocketPlan]:
    bearing = _state["bearings"][_choice(inputs, ID_BEARING)]  # type: ignore[index]
    fit = _choice(inputs, ID_FIT)
    plan = ff.plan_pocket(bearing, fit, KINDS[_choice(inputs, ID_KIND)], plate_thk_in, _state["fits"])  # type: ignore[arg-type]
    return bearing, fit, plan


def _describe(inputs) -> None:
    box = adsk.core.TextBoxCommandInput.cast(inputs.itemById(ID_INFO))
    try:
        bearing, fit, plan = _plan(inputs, _state.get("thk"))  # type: ignore[arg-type]
    except Exception:
        return
    allowance, why = _state["fits"].get(fit, (0.0, ""))  # type: ignore[union-attr]
    sign = "+" if allowance >= 0 else "−"
    lines = [f"<b>Hole Ø{plan.pocket_d_in:.4f}\"</b> = bearing OD {bearing.od_in:.4f}\" "
             f"{sign} {abs(allowance):.4f}\" ({fh.safe_text(fit.lower())}: {fh.safe_text(why)})"]
    if plan.pocket_depth_in is not None:
        lines.append(f"Pocket {plan.pocket_depth_in:.4f}\" deep, shaft hole Ø{plan.shaft_d_in:.4f}\" through")
    if _state.get("thk"):
        lines.append(f"Plate {_state['thk']:.3f}\" thick")
    if _state.get("count"):
        what = "circle set(s) drawn in the sketch - nothing is cut" if _sketch_mode(inputs) else "pocket(s)"
        lines.append(f"<b>{_state['count']}</b> {what}")
    for note in _state.get("sketch_notes", []):  # type: ignore[union-attr]
        lines.append("⚠ " + fh.safe_text(note))
    for note in plan.notes:
        lines.append("⚠ " + fh.safe_text(note))
    if _state.get("error"):
        lines.append("<b>Can't cut this:</b> " + fh.safe_text(str(_state["error"])))
    box.formattedText = "<br>".join(lines)


def _center_point(entity):
    """3D point (assembly space) for a picked sketch point, vertex or round edge."""
    point = adsk.fusion.SketchPoint.cast(entity)
    if point:
        return point.worldGeometry
    vertex = adsk.fusion.BRepVertex.cast(entity)
    if vertex:
        return vertex.geometry
    edge = adsk.fusion.BRepEdge.cast(entity)
    if edge:
        geom = edge.geometry
        circle = adsk.core.Circle3D.cast(geom) or adsk.core.Arc3D.cast(geom)
        if circle:
            return circle.center
    raise fb.FeatureError("Pick sketch points, vertices or round edges for the centers.")


def _build_in_sketch(inputs) -> int:
    """Sketch mode: add the circles to the picked sketch. Nothing is cut."""
    sketch_sel = adsk.core.SelectionCommandInput.cast(inputs.itemById(ID_SKETCH))
    centers_sel = adsk.core.SelectionCommandInput.cast(inputs.itemById(ID_CENTERS))
    picked = None
    if sketch_sel.selectionCount == 1:
        entity = sketch_sel.selection(0).entity
        picked = adsk.fusion.Sketch.cast(entity)
        if picked is None:
            curve = adsk.fusion.SketchCurve.cast(entity)
            picked = curve.parentSketch if curve else None
    if picked is None or centers_sel.selectionCount < 1:
        raise fb.FeatureError("Click the sketch to draw in and at least one center.")
    sketch, occ = fb.editable_sketch(picked)
    _state["thk"] = None
    bearing, fit, plan = _plan(inputs, None)  # type: ignore[arg-type]
    notes: List[str] = []
    for i in range(centers_sel.selectionCount):
        world = _center_point(centers_sel.selection(i).entity)
        p = sketch.modelToSketchSpace(fb.to_component_space(world, occ))
        if abs(p.z) > 0.01 and not notes:
            notes.append("a center isn't on the sketch's plane, so its circle was drawn straight below/above it")
        fb.add_circle(sketch, p.x, p.y, plan.pocket_d_in)
        if plan.shaft_d_in:
            fb.add_circle(sketch, p.x, p.y, plan.shaft_d_in)
    _state["sketch_notes"] = notes
    _log.info("Bearing circles in sketch '%s': %d x %s, %s, d=%.4f in", sketch.name, centers_sel.selectionCount,
              bearing.name, fit, plan.pocket_d_in)
    return centers_sel.selectionCount


def _build(inputs) -> int:
    if _sketch_mode(inputs):
        return _build_in_sketch(inputs)
    face_sel = adsk.core.SelectionCommandInput.cast(inputs.itemById(ID_FACE))
    centers_sel = adsk.core.SelectionCommandInput.cast(inputs.itemById(ID_CENTERS))
    if face_sel.selectionCount != 1 or centers_sel.selectionCount < 1:
        raise fb.FeatureError("Click the plate face and at least one center.")
    face = adsk.fusion.BRepFace.cast(face_sel.selection(0).entity)
    native, comp, occ = fb.editable_face(face)
    thk_cm = fb.wall_thickness_cm(native)
    _state["thk"] = thk_cm / fb.IN_TO_CM if thk_cm else None
    bearing, fit, plan = _plan(inputs, _state["thk"])  # type: ignore[arg-type]
    if plan.blocked:
        raise fb.FeatureError(plan.blocked)

    sketch = fb.new_sketch(comp, native, f"Gusset bearing pocket {bearing.name}")
    centers: List[Tuple[float, float]] = []
    for i in range(centers_sel.selectionCount):
        world = _center_point(centers_sel.selection(i).entity)
        local = fb.to_component_space(world, occ)
        p = sketch.modelToSketchSpace(local)
        if not fb.inside_face(sketch, native, p.x, p.y, 0.0):
            sketch.deleteMe()
            raise fb.FeatureError("A center isn't on the picked face. Pick centers on that face.")
        centers.append((p.x, p.y))
        fb.add_circle(sketch, p.x, p.y, plan.pocket_d_in)
        if plan.shaft_d_in:
            fb.add_circle(sketch, p.x, p.y, plan.shaft_d_in)

    profiles = [sketch.profiles.item(i) for i in range(sketch.profiles.count)]
    tag = f"{bearing.name.split(',')[0]} {fit.lower()}"
    if plan.pocket_depth_in is None:
        fb.cut(comp, profiles, native.body, None, f"Gusset bearing hole {tag}")
    else:
        # Every profile (ring + middle) is cut to pocket depth; then the middles go all the way through.
        shaft_area = math.pi * (plan.shaft_d_in * fb.IN_TO_CM / 2) ** 2
        shaft = [p for p in profiles if abs(fb.profile_center(p)[2] - shaft_area) < shaft_area * 0.02]
        fb.cut(comp, profiles, native.body, plan.pocket_depth_in * fb.IN_TO_CM, f"Gusset bearing pocket {tag}")
        fb.cut(comp, shaft, native.body, None, f"Gusset shaft hole {tag}")
    _log.info("Bearing pocket: %d x %s, %s, d=%.4f in", len(centers), bearing.name, fit, plan.pocket_d_in)
    return len(centers)


def _on_preview(args: adsk.core.CommandEventArgs) -> None:
    inputs = args.command.commandInputs
    _state.pop("error", None)
    _state.pop("sketch_notes", None)
    try:
        _state["count"] = _build(inputs)
        args.isValidResult = True
    except fb.FeatureError as exc:
        _state["error"], _state["count"] = str(exc), None
    _describe(inputs)


def _on_validate(args: adsk.core.ValidateInputsEventArgs) -> None:
    inputs = fh.all_inputs(args)
    target = ID_SKETCH if _sketch_mode(inputs) else ID_FACE
    args.areInputsValid = (adsk.core.SelectionCommandInput.cast(inputs.itemById(target)).selectionCount == 1
                           and adsk.core.SelectionCommandInput.cast(inputs.itemById(ID_CENTERS)).selectionCount >= 1
                           and not _state.get("error"))


def _remember_output(inputs) -> None:
    try:
        settings.save_state(config.ADDIN_DIR, bearing_output=_choice(inputs, ID_OUTPUT))
    except Exception as exc:
        _log.debug("Couldn't remember the output choice: %s", exc)


def _on_execute(args: adsk.core.CommandEventArgs) -> None:
    _, ui = fh.app_ui()
    _remember_output(args.command.commandInputs)
    try:
        _build(args.command.commandInputs)
    except fb.FeatureError as exc:
        ui.messageBox(str(exc), "Gusset - Bearing Pocket")
        args.executeFailed = True


def _on_destroy(args: adsk.core.CommandEventArgs) -> None:
    try:
        if args.terminationReason == adsk.core.CommandTerminationReason.CompletedTerminationReason:
            _remember_output(args.command.commandInputs)
    except Exception:
        pass
    _state.clear()
    fh.release_handlers(HANDLER_GROUP)
