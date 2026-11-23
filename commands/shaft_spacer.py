"""
Shaft & Spacer - 1/2" hex shafts and the spacers that go on them (Gusset's take
on Onshape's Robot Shaft / Robot Spacer).

SHAFT
  1. GUSSET > Shaft & Spacer, Make = Shaft.
  2. Click where the shaft starts and ends: round edges (e.g. the bearing holes
     in both plates), sketch points or vertices.
  3. Add length past each end (for collars, pulleys hanging off the end...).
  4. Plain ends, or tapped #10-32 ends. Rotate the hex if the flats need to line
     up with something. Press OK.

SPACER
  1. Make = Spacer. Click the shaft (a Gusset shaft lines the hex bore up with
     it; or click any round edge on the shaft's axis).
  2. Click the two faces the spacer fills the gap between (e.g. a bearing's face
     and a pulley's face).
  3. Pick the OD. The hex bore gets a little clearance (3D-printed spacers need
     it) and the spacer is a hair short at each end so the stack isn't tight.

CREATE AS
  Linked part files (default): each shaft/spacer is saved as its own editable
  part file in the "[Assembly] Parts" folder next to the assembly and inserted
  as a linked component. Identical parts share one file. (Save the assembly first.)
  Bodies in this file: the parts are added as bodies here instead.
"""

from __future__ import annotations

import math
import re
import os
from typing import Dict, Optional, Tuple

import adsk.core
import adsk.fusion

from .. import config
from ..lib import feature_builder as fb
from ..lib import frc_parts_core as pc
from ..lib import fusion_helpers as fh
from ..lib import log as gslog
from ..lib import part_files_core as pf
from ..lib import parts_builder as pb
from ..lib import settings
from ..lib import cots_match as cm
from ..lib import placement_core as pl
from ..lib import tip_box
from . import cots_autoplace, cots_browser, linked_parts

CMD_ID = "Gusset_ShaftSpacer"
CMD_NAME = "Shaft & Spacer"
CMD_TOOLTIP = "Make a 1/2\" hex shaft between two points, or a hex-bore spacer between two faces on a shaft."
ICON_DIR = os.path.join(config.ADDIN_DIR, "resources", "shaft")
HANDLER_GROUP = "shaft_dialog"
STATE_KEY = "shaft"

_log = gslog.get_logger("shaft")

MODE_SHAFT, MODE_SPACER = "Shaft", "Spacer"
(ID_MODE, ID_A, ID_B, ID_EXT_A, ID_EXT_B, ID_ENDS, ID_ROT, ID_SHAFT_MAT, ID_AXIS, ID_FACE1, ID_FACE2, ID_OD,
 ID_CLEAR, ID_GAP, ID_INFO, ID_CREATE, ID_SPACER_MAT) = ("ss_mode", "ss_a", "ss_b", "ss_ext_a", "ss_ext_b", "ss_ends", "ss_rot", "ss_mat",
                                "ss_axis", "ss_face1", "ss_face2", "ss_od", "ss_clear", "ss_gap", "ss_info",
                                "ss_create", "ss_spacer_mat")
ID_BEARING = "ss_bearing"                       # library bearings in the end holes (0.12)
NO_BEARING = "None"
# Turned-round ends and snap-ring grooves (0.12.1)
(ID_ROUND, ID_ROUND_D, ID_ROUND_L, ID_GROOVE, ID_GROOVE_GAP, ID_GROOVE_D, ID_GROOVE_W, ID_GROOVE_EXTRA) = (
    "ss_round", "ss_round_d", "ss_round_l", "ss_groove", "ss_groove_gap", "ss_groove_d", "ss_groove_w", "ss_groove_x")
ROUND_DETAIL_IDS = (ID_ROUND_D, ID_ROUND_L)
ID_FLANGE, ID_REF = "ss_flange", "ss_ref"         # flange side + the reference note (0.12.3)
GROOVE_DETAIL_IDS = (ID_GROOVE_GAP, ID_GROOVE_D, ID_GROOVE_W)
SHAFT_IDS = (ID_A, ID_B, ID_EXT_A, ID_EXT_B, ID_ENDS, ID_ROT, ID_SHAFT_MAT, ID_BEARING, ID_ROUND, ID_GROOVE,
             ID_GROOVE_EXTRA, ID_FLANGE, ID_REF) + ROUND_DETAIL_IDS + GROOVE_DETAIL_IDS
SPACER_IDS = (ID_AXIS, ID_FACE1, ID_FACE2, ID_OD, ID_CLEAR, ID_GAP, ID_SPACER_MAT)
SHAFT_MATERIALS = ["Steel", "Aluminum 7075", "Aluminum 6061", "(leave as is)"]
SPACER_MATERIALS = ["PLA", "PETG", "Aluminum 6061", "(leave as is)"]

_state: Dict[str, object] = {}


def start() -> None:
    fh.add_button(CMD_ID, CMD_NAME, CMD_TOOLTIP, ICON_DIR, _on_created, config.PANEL_PARTS_ID, config.PANEL_PARTS_NAME)


def stop() -> None:
    fh.remove_button(CMD_ID, config.PANEL_PARTS_ID)


def _dropdown(inputs, input_id, label, choices, selected):
    dd = inputs.addDropDownCommandInput(input_id, label, adsk.core.DropDownStyles.TextListDropDownStyle)
    pick = selected if selected in choices else choices[0]
    for c in choices:
        dd.listItems.add(c, c == pick)
    return dd


def _choice(inputs, input_id) -> str:
    item = adsk.core.DropDownCommandInput.cast(inputs.itemById(input_id)).selectedItem
    return item.name if item else ""


def _value(inputs, input_id) -> float:
    return adsk.core.ValueCommandInput.cast(inputs.itemById(input_id)).value


def _sel(inputs, input_id):
    return adsk.core.SelectionCommandInput.cast(inputs.itemById(input_id))


def _on_created(args: adsk.core.CommandCreatedEventArgs) -> None:
    _log.info("Shaft & Spacer opened")
    cmd = args.command
    _, ui = fh.app_ui()
    if not fh.active_design():
        ui.messageBox("Open a Fusion design first, then try Shaft & Spacer again.", "Gusset")
        return
    _state.clear()
    saved = settings.load_state(config.ADDIN_DIR).get(STATE_KEY)
    last = saved if isinstance(saved, dict) else {}
    inputs = cmd.commandInputs
    tip_box.attach(cmd, CMD_ID)              # 'How to use this' + hover tips (0.13)
    _dropdown(inputs, ID_MODE, "Make", [MODE_SHAFT, MODE_SPACER], str(last.get("mode", MODE_SHAFT)))
    create = _dropdown(inputs, ID_CREATE, "Create as", [linked_parts.LINKED, linked_parts.BODIES],
                       str(last.get("create", linked_parts.LINKED)))
    create.tooltip = ("Linked part files: saved in " + linked_parts.assembly_label(fh.app_ui()[0].activeDocument) +
                      " next to this assembly and inserted as components (identical parts share one file).")
    for input_id, label, prompt in ((ID_A, "Start", "Click where the shaft starts (round edge, sketch point or vertex)"),
                                    (ID_B, "End", "Click where the shaft ends")):
        s = inputs.addSelectionInput(input_id, label, prompt)
        for f in ("CircularEdges", "SketchPoints", "Vertices", "ConstructionPoints"):
            s.addSelectionFilter(f)
        s.setSelectionLimits(0, 1)
    for input_id, label in ((ID_EXT_A, "Past start"), (ID_EXT_B, "Past end")):
        vi = inputs.addValueInput(input_id, label, "in", adsk.core.ValueInput.createByString(
            f"{float(last.get('ext', 0.25))} in"))
        vi.tooltip = "Extra shaft beyond this point (for collars, a pulley on the end...)"
    _dropdown(inputs, ID_ENDS, "Ends", pc.SHAFT_ENDS, str(last.get("ends", pc.SHAFT_ENDS[0])))
    _dropdown(inputs, ID_ROUND, "Round ends", pc.ROUND_ENDS, str(last.get("round", pc.ROUND_ENDS[0]))).tooltip = (
        "Turn the end of the hex down round, to ride in a round-bore bearing (like R8ZZ)")
    for input_id, label, key, default, tip in (
            (ID_ROUND_D, "Round diameter", "round_d", pc.DEFAULT_ROUND_D_IN, '0.500" fits 1/2" round-bore bearings'),
            (ID_ROUND_L, "Round length", "round_l", pc.DEFAULT_ROUND_LEN_IN, "How far in from the end it's turned round")):
        inputs.addValueInput(input_id, label, "in", adsk.core.ValueInput.createByString(
            f"{float(last.get(key, default))} in")).tooltip = tip
    _dropdown(inputs, ID_GROOVE, "Snap-ring grooves", pc.GROOVES, str(last.get("groove", pc.GROOVES[0]))).tooltip = (
        "Grooves for 1/2\" external snap rings, just outside each plate (past the bearing flange)")
    for input_id, label, key, default, tip in (
            (ID_GROOVE_GAP, "Groove past plate", "groove_gap", pc.DEFAULT_GROOVE_GAP_IN,
             "From the plate's outside face to the groove: the bearing flange (~0.062\") plus a little"),
            (ID_GROOVE_D, "Groove diameter", "groove_d", pc.SNAP_RING_GROOVE_D_IN,
             '0.469" for a standard 1/2" external retaining ring'),
            (ID_GROOVE_W, "Groove width", "groove_w", pc.SNAP_RING_GROOVE_W_IN, '0.039" for a standard 1/2" ring')):
        inputs.addValueInput(input_id, label, "in", adsk.core.ValueInput.createByString(
            f"{float(last.get(key, default))} in")).tooltip = tip
    inputs.addStringValueInput(ID_GROOVE_EXTRA, "Extra grooves at", "").tooltip = (
        "More grooves, in inches from the shaft's start (the Start end, including Past start), e.g. 1.25, 2.5")
    # A plain value box in degrees (its .value comes back in radians, like every Fusion angle).
    rot = inputs.addValueInput(ID_ROT, "Rotate hex", "deg", adsk.core.ValueInput.createByString("0 deg"))
    rot.tooltip = "Turn the hex so its flats line up with something (60 degrees = all the way round)"
    _dropdown(inputs, ID_SHAFT_MAT, "Material", SHAFT_MATERIALS, str(last.get("material", SHAFT_MATERIALS[0])))
    bearings = [NO_BEARING] + [cm.bearing_label(i) for i in cm.shaft_bearings(cots_browser.catalog())]
    _dropdown(inputs, ID_BEARING, "Bearings", bearings, str(last.get("bearing", NO_BEARING))).tooltip = (
        "Put this COTS Library bearing in each end hole (round edges only), on the Flange side you pick. "
        "Hex-bore bearings go on hex ends, round-bore bearings (like R8ZZ) on round ends.")
    _dropdown(inputs, ID_FLANGE, "Flange side", pc.FLANGE_SIDES, str(last.get("flange", pc.FLANGE_SIDES[0]))).tooltip = (
        "Outside = flanges on the outer faces of the plates (easier maintenance). Bearings without a flange "
        "sit flush with that face.")
    inputs.addTextBoxCommandInput(ID_REF, "Reference", "", 5, True)
    axis = inputs.addSelectionInput(ID_AXIS, "Shaft", "Click the shaft (or a round edge on its axis)")
    for f in ("SolidBodies", "CircularEdges"):
        axis.addSelectionFilter(f)
    axis.setSelectionLimits(0, 1)
    for input_id, label in ((ID_FACE1, "From face"), (ID_FACE2, "To face")):
        s = inputs.addSelectionInput(input_id, label, "Click a flat face the spacer touches")
        s.addSelectionFilter("PlanarFaces")
        s.setSelectionLimits(0, 1)
    _dropdown(inputs, ID_OD, "Spacer OD", pc.SPACER_ODS, str(last.get("od", '0.75"')))
    _dropdown(inputs, ID_SPACER_MAT, "Spacer material", SPACER_MATERIALS,
              str(last.get("spacer_material", SPACER_MATERIALS[0]))).tooltip = \
        "PLA/PETG are added to the design with real densities, so the BOM mass is right"
    inputs.addValueInput(ID_CLEAR, "Bore clearance", "in", adsk.core.ValueInput.createByString(
        f"{float(last.get('clear', pc.DEFAULT_SPACER_CLEARANCE_IN))} in")).tooltip = \
        "Added to the 1/2\" hex bore. ~0.010\" for 3D-printed spacers, less for machined ones."
    inputs.addValueInput(ID_GAP, "Gap each end", "in", adsk.core.ValueInput.createByString(
        f"{float(last.get('gap', pc.DEFAULT_SPACER_GAP_IN))} in")).tooltip = \
        "Spacer is this much shorter at each end so the stack isn't over-tight"
    inputs.addTextBoxCommandInput(ID_INFO, "", "", 4, True)
    _show_hide(inputs)
    for event, base, func, label in (
        (cmd.inputChanged, adsk.core.InputChangedEventHandler, _on_input_changed, "input changed"),
        (cmd.executePreview, adsk.core.CommandEventHandler, _on_preview, "preview"),
        (cmd.validateInputs, adsk.core.ValidateInputsEventHandler, _on_validate, "validate"),
        (cmd.execute, adsk.core.CommandEventHandler, _on_execute, "OK"),
        (cmd.destroy, adsk.core.CommandEventHandler, _on_destroy, "close"),
    ):
        event.add(fh.make_handler(base, func, f"Shaft & Spacer: {label}", HANDLER_GROUP))


def _shaft_mode(inputs) -> bool:
    return _choice(inputs, ID_MODE) == MODE_SHAFT


def _show_hide(inputs) -> None:
    shaft = _shaft_mode(inputs)
    for i in SHAFT_IDS:
        inputs.itemById(i).isVisible = shaft
    for i in SPACER_IDS:
        inputs.itemById(i).isVisible = not shaft
    if shaft:
        rounds = _choice(inputs, ID_ROUND) != pc.ROUND_ENDS[0]
        for i in ROUND_DETAIL_IDS:
            inputs.itemById(i).isVisible = rounds
        grooves = _choice(inputs, ID_GROOVE) != pc.GROOVES[0]
        for i in GROOVE_DETAIL_IDS:
            inputs.itemById(i).isVisible = grooves
        inputs.itemById(ID_GROOVE_D).isVisible = inputs.itemById(ID_GROOVE_W).isVisible = (
            grooves or bool(adsk.core.StringValueCommandInput.cast(inputs.itemById(ID_GROOVE_EXTRA)).value.strip()))
        inputs.itemById(ID_FLANGE).isVisible = _bearing(inputs) is not None
        note = _reference_note(inputs)
        inputs.itemById(ID_REF).isVisible = bool(note)
        adsk.core.TextBoxCommandInput.cast(inputs.itemById(ID_REF)).formattedText = note
    if not adsk.core.TextBoxCommandInput.cast(inputs.itemById(ID_INFO)).formattedText:
        _say(inputs, "Click where the shaft starts and ends." if shaft else
             "Click the shaft, then the two faces the spacer goes between.")


def _flange_outside(inputs) -> bool:
    return _choice(inputs, ID_FLANGE) != pc.FLANGE_SIDES[1]


def _bearing_dims(item) -> Tuple[float, float, str]:
    """(width, flange thickness, where they came from) in inches - measured when Gusset placed it, else standard."""
    saved = settings.load_state(config.ADDIN_DIR).get("bearing_dims") or {}
    dims = saved.get(item.file_id) if isinstance(saved, dict) else None
    if isinstance(dims, list) and len(dims) == 2:
        return float(dims[0]), float(dims[1]), "measured"
    flange = pc.STANDARD_FLANGE_IN if "flange" in item.title.lower() else 0.0
    return pc.STANDARD_BEARING_WIDTH_IN, flange, "standard size"


def _plate_faces(edge, outward):
    """(outside face point, inside face point) of the plate a round hole edge is in, or None."""
    outer = _hole_seat(edge, outward)[0]
    inner = _hole_seat(edge, pl.scale(outward, -1.0))[0]
    return (outer, inner) if outer is not None and inner is not None else None


def _reference_note(inputs) -> str:
    """
    The two numbers students type themselves - groove past plate, and how long a round
    end must be to reach the bearing - worked out from the picked holes and the bearing.
    Shown only; never typed in for them.
    """
    try:
        a_sel, b_sel = _sel(inputs, ID_A), _sel(inputs, ID_B)
        if a_sel.selectionCount == 0 or b_sel.selectionCount == 0:
            return ""
        item = _bearing(inputs)
        width, flange, source = _bearing_dims(item) if item else (pc.STANDARD_BEARING_WIDTH_IN, 0.0, "standard size")
        name = item.info.vendor_pn if item else "no bearing picked"
        ends = [a_sel.selection(0).entity, b_sel.selection(0).entity]
        world = [_point_of(e)[0] for e in ends]
        ext = [_value(inputs, ID_EXT_A) / fb.IN_TO_CM, _value(inputs, ID_EXT_B) / fb.IN_TO_CM]
        lines = [f"<b>For you to type</b> ({name}: {width:.3f}\" wide, flange {flange:.3f}\", {source})"]
        for n, (here, there) in enumerate(((world[0], world[1]), (world[1], world[0]))):
            label = "Start" if n == 0 else "End"
            edge = adsk.fusion.BRepEdge.cast(ends[n])
            outward = pl.unit(pl.sub(here, there))
            faces = _plate_faces(edge, outward) if edge else None
            if faces is None:
                lines.append(f"{label}: pick a round hole edge to see its numbers.")
                continue
            plate = math.dist(faces[0], faces[1]) / fb.IN_TO_CM
            ref = pc.bearing_reference(width, flange, plate, _flange_outside(inputs))
            # shaft end -> plate's outside face: the extension, plus the plate if the inside face was clicked
            clicked_outer = math.dist(here, faces[0]) < math.dist(here, faces[1])
            end_to_outer = ext[n] + (0.0 if clicked_outer else -plate)
            lines.append(f"{label}: groove past plate &asymp; <b>{ref.groove_gap_in:.3f}\"</b> ({ref.why_gap}); "
                         f"round length to reach the bearing &asymp; <b>{end_to_outer + ref.depth_in:.3f}\"</b> "
                         f"({end_to_outer:.3f}\" to the plate's outside + {ref.depth_in:.3f}\": {ref.why_depth})")
        return "<br>".join(lines)
    except Exception as exc:
        _log.debug("Reference note: %s", exc)
        return ""


def _say(inputs, text: str) -> None:
    adsk.core.TextBoxCommandInput.cast(inputs.itemById(ID_INFO)).formattedText = text


def _on_input_changed(args: adsk.core.InputChangedEventArgs) -> None:
    if args.input.id == ID_MODE:
        _say(fh.all_inputs(args), "")
    _show_hide(fh.all_inputs(args))


def _point_of(entity) -> Tuple[Tuple[float, float, float], Optional[object]]:
    """(assembly-space point, component it belongs to or None) for a picked point/edge/vertex."""
    sp = adsk.fusion.SketchPoint.cast(entity)
    if sp:
        return pb.vec(sp.worldGeometry), sp.parentSketch.parentComponent
    v = adsk.fusion.BRepVertex.cast(entity)
    if v:
        return pb.vec(v.geometry), v.body.parentComponent
    cp = adsk.fusion.ConstructionPoint.cast(entity)
    if cp:
        return pb.vec(cp.geometry), cp.component
    e = adsk.fusion.BRepEdge.cast(entity)
    if e:
        circle = adsk.core.Circle3D.cast(e.geometry) or adsk.core.Arc3D.cast(e.geometry)
        if circle:
            return pb.vec(circle.center), e.body.parentComponent
    raise fb.FeatureError("Pick round edges, sketch points or vertices.")


def _target_component():
    """Shafts and spacers go in the component being edited (the active one)."""
    design = fh.active_design()
    comp = design.activeComponent
    occ = design.activeOccurrence
    if occ is not None and occ.isReferencedComponent:
        raise fb.FeatureError("The active component lives in another file - open that file to add parts to it.")
    return comp, occ


def _to_comp(p, occ):
    return pb.vec(fb.to_component_space(pb.P3(p), occ))


def _linked(inputs) -> bool:
    return _choice(inputs, ID_CREATE) == linked_parts.LINKED


def _shaft_geometry(inputs):
    """Everything about the shaft except building it: (comp, plan, start, u, flats, span)."""
    a_sel, b_sel = _sel(inputs, ID_A), _sel(inputs, ID_B)
    if a_sel.selectionCount != 1 or b_sel.selectionCount != 1:
        raise fb.FeatureError("Click where the shaft starts and where it ends.")
    comp, occ = _target_component()
    ends = [a_sel.selection(0).entity, b_sel.selection(0).entity]
    world = [_point_of(e)[0] for e in ends]
    a, b = _to_comp(world[0], occ), _to_comp(world[1], occ)
    span = math.dist(a, b) / fb.IN_TO_CM
    u = pb.unit(pb.sub(b, a))
    ext_a = _value(inputs, ID_EXT_A) / fb.IN_TO_CM
    start = pb.add(a, u, -ext_a * fb.IN_TO_CM)
    grooves, typed_problems = _groove_spots(inputs, ends, world, start, u, occ)
    plan = pc.plan_shaft(span, ext_a, _value(inputs, ID_EXT_B) / fb.IN_TO_CM, _choice(inputs, ID_ENDS),
                         _choice(inputs, ID_ROUND), _value(inputs, ID_ROUND_D) / fb.IN_TO_CM,
                         _value(inputs, ID_ROUND_L) / fb.IN_TO_CM, grooves,
                         _value(inputs, ID_GROOVE_D) / fb.IN_TO_CM, _value(inputs, ID_GROOVE_W) / fb.IN_TO_CM)
    plan.problems = typed_problems + plan.problems
    if plan.problems:
        raise fb.FeatureError(" ".join(plan.problems))
    flats = pb.rotate(pb.any_perpendicular(u), u, _value(inputs, ID_ROT))
    return comp, plan, a, b, start, u, flats, span


def _groove_spots(inputs, ends, world, start, u, occ):
    """
    Groove centers in inches from the shaft's start: just outside each plate (when
    that end was picked on a round hole edge; otherwise past the picked point) plus
    any typed in 'Extra grooves at'.
    """
    spots, problems = [], []
    if _choice(inputs, ID_GROOVE) != pc.GROOVES[0]:
        past = (_value(inputs, ID_GROOVE_GAP) + _value(inputs, ID_GROOVE_W) / 2) / fb.IN_TO_CM
        for n, (entity, here, there) in enumerate(((ends[0], world[0], world[1]), (ends[1], world[1], world[0]))):
            outward = pl.unit(pl.sub(here, there))
            edge = adsk.fusion.BRepEdge.cast(entity)
            seat = _hole_seat(edge, outward)[0] if edge else None
            face = _to_comp(seat if seat is not None else here, occ)
            along = pl.dot(pl.sub(face, start), u) / fb.IN_TO_CM          # plate face, inches from the start
            spots.append(along - past if n == 0 else along + past)
    extra, problems = pc.parse_positions(adsk.core.StringValueCommandInput.cast(inputs.itemById(ID_GROOVE_EXTRA)).value)
    return spots + extra, problems


def _shaft_material(inputs) -> Optional[str]:
    mat = _choice(inputs, ID_SHAFT_MAT)
    return None if mat == SHAFT_MATERIALS[-1] else mat


def _build_shaft(inputs, make: bool = True) -> str:
    """Preview / 'bodies' mode: add the shaft as a body here."""
    comp, plan, a, b, start, u, flats, span = _shaft_geometry(inputs)
    if make:
        body, start, u, flats = pb.shaft_body(a, b, plan, pb.any_perpendicular(u), math.degrees(_value(inputs, ID_ROT)))
        made = pb.add_bodies(comp, [(body, plan.name)], "Gusset shaft", _shaft_material(inputs))
        pb.tag_shaft(made[0], start, u, flats, plan.length_in * fb.IN_TO_CM)
    ends = " with tapped ends" if plan.tapped else ""
    where = (f"<br>OK saves it as <b>{fh.safe_text(pf.shaft_file_name(plan))}</b> in "
             f"{fh.safe_text(linked_parts.assembly_label(fh.app_ui()[0].activeDocument))}") if _linked(inputs) else ""
    return f"<b>{fh.safe_text(plan.name)}</b>{ends}<br>{span:.3f}\" between your points + extensions.{where}"


def _shaft_request(inputs):
    comp, plan, _a, _b, start, u, flats, _span = _shaft_geometry(inputs)
    y = pb.cross(u, flats)
    req = pf.PartRequest("shaft", pf.shaft_file_name(plan), plan,
                         placements=[pf.Placement(start, flats, y, u)])
    return comp, req


def _axis_from(entity) -> Tuple[tuple, tuple, Optional[tuple]]:
    """(point on axis, axis direction, hex flats direction or None) in assembly space."""
    body = adsk.fusion.BRepBody.cast(entity)
    if body:
        info = pb.read_shaft(body.nativeObject if body.assemblyContext else body)
        if not info:
            # No Gusset tag (linked shafts from 0.12.2 and earlier, or a shaft modeled by hand):
            # recognize the 1/2" hex from its flat faces instead.
            found = _hex_from_shape(body)
            if found:
                return found
            raise fb.FeatureError("Gusset couldn't find a 1/2\" hex on that body - click a round edge on the "
                                  "shaft's axis instead.")
        start, u, flats = tuple(info["start"]), tuple(info["u"]), tuple(info["flats"])
        if body.assemblyContext:
            m = body.assemblyContext.transform2
            p = pb.P3(start)
            p.transformBy(m)
            uv, fv = pb.V3(u), pb.V3(flats)
            uv.transformBy(m)
            fv.transformBy(m)
            return pb.vec(p), pb.vec(uv), pb.vec(fv)
        return start, u, flats
    edge = adsk.fusion.BRepEdge.cast(entity)
    circle = (adsk.core.Circle3D.cast(edge.geometry) or adsk.core.Arc3D.cast(edge.geometry)) if edge else None
    if circle:
        return pb.vec(circle.center), pb.unit(pb.vec(circle.normal)), None
    raise fb.FeatureError("Click a Gusset shaft or a round edge on the shaft's axis.")


def _hex_from_shape(body):
    """(point on axis, axis, a flat's normal) in assembly space for a 1/2" hex body, or None."""
    planes = []
    for face in [body.faces.item(i) for i in range(body.faces.count)]:
        plane = adsk.core.Plane.cast(face.geometry)
        if not plane:
            continue
        n = pb.vec(plane.normal)
        if fh.safe(lambda f=face: f.isParamReversed, False):
            n = pl.scale(n, -1.0)
        planes.append((pb.vec(face.pointOnFace), n))
    box = body.boundingBox
    near = pl.scale(pl.add(pb.vec(box.minPoint), pb.vec(box.maxPoint)), 0.5)
    found = pl.hex_axis_from_planes(planes, pc.HEX_FLATS_IN * fb.IN_TO_CM, near)
    _log.info("Spacer: %s has no Gusset tag - %s", body.name,
              "recognized a 1/2\" hex from its faces" if found else f"no 1/2\" hex in its {len(planes)} flat faces")
    return found


def _plane_hit(face, origin, u) -> float:
    plane = adsk.core.Plane.cast(face.geometry)
    n = pb.vec(plane.normal)
    denom = pb.dot(n, u)
    if abs(denom) < 1e-6:
        raise fb.FeatureError("One of the faces is parallel to the shaft - pick faces the shaft goes through.")
    return pb.dot(n, pb.sub(pb.vec(plane.origin), origin)) / denom


def _spacer_geometry(inputs):
    """(comp, plan, start-of-gap point, u, flats, gap, end_gap, from_shaft) in the target component."""
    axis_sel, f1, f2 = _sel(inputs, ID_AXIS), _sel(inputs, ID_FACE1), _sel(inputs, ID_FACE2)
    if axis_sel.selectionCount != 1 or f1.selectionCount != 1 or f2.selectionCount != 1:
        raise fb.FeatureError("Click the shaft, then the two faces the spacer goes between.")
    origin, u, flats = _axis_from(axis_sel.selection(0).entity)
    t1 = _plane_hit(adsk.fusion.BRepFace.cast(f1.selection(0).entity), origin, u)
    t2 = _plane_hit(adsk.fusion.BRepFace.cast(f2.selection(0).entity), origin, u)
    lo, hi = sorted((t1, t2))
    gap_in = (hi - lo) / fb.IN_TO_CM
    end_gap = _value(inputs, ID_GAP) / fb.IN_TO_CM
    plan = pc.plan_spacer(gap_in, _choice(inputs, ID_OD), _value(inputs, ID_CLEAR) / fb.IN_TO_CM, end_gap)
    if plan.problems:
        raise fb.FeatureError(" ".join(plan.problems))
    comp, occ = _target_component()
    start = _to_comp(pb.add(origin, u, lo), occ)
    if occ is not None:          # directions into the component's space too
        m = occ.transform2.copy()
        m.invert()
        uv = pb.V3(u)
        uv.transformBy(m)
        u = pb.vec(uv)
        if flats:
            fv = pb.V3(flats)
            fv.transformBy(m)
            flats = pb.vec(fv)
    from_shaft = flats is not None
    flats = flats or pb.any_perpendicular(u)
    return comp, plan, start, u, flats, gap_in, end_gap, from_shaft


def _spacer_material(inputs) -> Optional[str]:
    mat = _choice(inputs, ID_SPACER_MAT)
    return None if mat == SPACER_MATERIALS[-1] else mat


def _build_spacer(inputs, make: bool = True) -> str:
    comp, plan, start, u, flats, gap_in, end_gap, from_shaft = _spacer_geometry(inputs)
    if make:
        body = pb.spacer_body(start, u, plan, flats, end_gap)
        pb.add_bodies(comp, [(body, plan.name)], "Gusset spacer", _spacer_material(inputs))
    lined_up = "" if from_shaft else \
        "<br>⚠ Picked an edge, not a Gusset shaft: the hex bore may need rotating to match."
    where = (f"<br>OK saves it as <b>{fh.safe_text(pf.spacer_file_name(plan, _spacer_material(inputs) or ''))}</b> in "
             f"{fh.safe_text(linked_parts.assembly_label(fh.app_ui()[0].activeDocument))} (or reuses a match)") \
        if _linked(inputs) else ""
    return (f"<b>{fh.safe_text(plan.name)}</b> - {gap_in:.3f}\" gap between the faces, bore "
            f"{plan.bore_flats_in:.3f}\" across flats.{lined_up}{where}")


def _spacer_request(inputs):
    comp, plan, start, u, flats, _gap, end_gap, _fs = _spacer_geometry(inputs)
    origin = pb.add(start, u, end_gap * fb.IN_TO_CM)
    req = pf.PartRequest("spacer", pf.spacer_file_name(plan, _spacer_material(inputs) or ""), plan,
                         placements=[pf.Placement(origin, flats, pb.cross(u, flats), u)])
    return comp, req


def _on_preview(args: adsk.core.CommandEventArgs) -> None:
    inputs = args.command.commandInputs
    try:
        msg = _build_shaft(inputs) if _shaft_mode(inputs) else _build_spacer(inputs)
        _say(inputs, msg)
        # Bodies mode: the preview IS the result. Linked mode: OK must run execute,
        # which hands the file work to the after-dialog step.
        # Library bearings are also added after OK, so OK must run for those too.
        args.isValidResult = not _linked(inputs) and not (_shaft_mode(inputs) and _bearing(inputs) is not None)
    except fb.FeatureError as exc:
        _say(inputs, "<b>Not yet:</b> " + fh.safe_text(str(exc)))
    except Exception:
        fh.report_error("Shaft & Spacer preview", show_dialog=False)
        _say(inputs, "Something went wrong - see the Text Commands window / gusset.log.")


def _bearing(inputs):
    """The library bearing picked in the dropdown, or None."""
    label = _choice(inputs, ID_BEARING)
    if not label or label == NO_BEARING:
        return None
    return next((i for i in cm.shaft_bearings(cots_browser.catalog()) if cm.bearing_label(i) == label), None)


def _bearing_od_cm(item) -> Optional[float]:
    """'... 1.125 in. OD ...' -> 2.8575 (None if the name doesn't say)."""
    m = re.search(r'(\d*\.\d+|\d+)\s*(?:in\.?|")\s*OD', item.title, re.I)
    return float(m.group(1)) * fb.IN_TO_CM if m else None


def _hole_seat(edge, outward):
    """
    (point on the plate's OUTER face at the hole's center, hole diameter) for a
    clicked round edge - whichever side of the plate was clicked.
    """
    circle = adsk.core.Circle3D.cast(edge.geometry) or adsk.core.Arc3D.cast(edge.geometry)
    if not circle:
        return None, 0.0
    best = pb.vec(circle.center)
    for face in [edge.faces.item(i) for i in range(edge.faces.count)]:
        if not adsk.core.Cylinder.cast(face.geometry):
            continue
        for e in [face.edges.item(i) for i in range(face.edges.count)]:
            c = adsk.core.Circle3D.cast(e.geometry)
            if c and pl.dot(pb.vec(c.center), outward) > pl.dot(best, outward) + 1e-6:
                best = pb.vec(c.center)
    return best, circle.radius * 2


def _queue_bearings(inputs) -> None:
    """A library bearing in each end hole of the shaft, flange outward, pinned to the plate."""
    item = _bearing(inputs)
    if item is None:
        return
    ends = [_sel(inputs, ID_A).selection(0).entity, _sel(inputs, ID_B).selection(0).entity]
    points = [_point_of(e)[0] for e in ends]
    od = _bearing_od_cm(item)
    plan = _shaft_geometry(inputs)[1]
    bore = cm.bearing_bore(item)
    requests, skipped = [], []
    for n, (edge_entity, here, there) in enumerate(((ends[0], points[0], points[1]), (ends[1], points[1], points[0])), 1):
        name = "start" if n == 1 else "end"
        round_here = plan.round_start if n == 1 else plan.round_end
        if bore == "hex" and round_here:
            skipped.append(f"The {name} is turned round, so a hex-bore bearing won't go on it - pick a round-bore "
                           "bearing (like R8ZZ) for round ends.")
            continue
        if bore == "round" and not round_here:
            skipped.append(f"The {name} is still hex, so a round-bore bearing won't go on it - turn that end round "
                           "or pick a hex-bore bearing.")
            continue
        edge = adsk.fusion.BRepEdge.cast(edge_entity)
        if edge is None:
            skipped.append(f"The shaft's {name} isn't a round hole edge, so no bearing went there.")
            continue
        outward = pl.unit(pl.sub(here, there))
        seat, hole = _hole_seat(edge, outward)
        if seat is None:
            skipped.append(f"The {name} edge isn't round.")
            continue
        if od and not pl.hole_fits(hole, od):
            skipped.append(f"The {name} hole is {hole / fb.IN_TO_CM:.3f}\" across - too far from this bearing's "
                           f"{od / fb.IN_TO_CM:.3f}\" OD, so no bearing went there.")
            continue
        if not _flange_outside(inputs):           # flange on the inside face, pointing in
            outward = pl.scale(outward, -1.0)
            seat = _hole_seat(edge, outward)[0]
        requests.append(cots_autoplace.request(item, seat, outward, pl.FLANGE_OUT,
                                               anchor=fh.safe(lambda e=edge: e.assemblyContext),
                                               label=f"Bearing at the {name} ({item.info.vendor_pn})"))
    _log.info("Shaft & Spacer: %d bearing(s) to place, %d skipped", len(requests), len(skipped))
    cots_autoplace.queue(requests, "Shaft & Spacer")
    if skipped:
        fh.app_ui()[1].messageBox("\n\n".join(skipped), "Gusset - Shaft & Spacer")


def _on_validate(args: adsk.core.ValidateInputsEventArgs) -> None:
    inputs = fh.all_inputs(args)
    ids = (ID_A, ID_B) if _shaft_mode(inputs) else (ID_AXIS, ID_FACE1, ID_FACE2)
    args.areInputsValid = all(_sel(inputs, i).selectionCount == 1 for i in ids)


def _save(inputs) -> None:
    try:
        settings.save_state(config.ADDIN_DIR, **{STATE_KEY: {
            "mode": _choice(inputs, ID_MODE), "ends": _choice(inputs, ID_ENDS), "create": _choice(inputs, ID_CREATE),
            "spacer_material": _choice(inputs, ID_SPACER_MAT),
            "material": _choice(inputs, ID_SHAFT_MAT), "od": _choice(inputs, ID_OD),
            "bearing": _choice(inputs, ID_BEARING), "round": _choice(inputs, ID_ROUND), "flange": _choice(inputs, ID_FLANGE),
            "round_d": _value(inputs, ID_ROUND_D) / fb.IN_TO_CM, "round_l": _value(inputs, ID_ROUND_L) / fb.IN_TO_CM,
            "groove": _choice(inputs, ID_GROOVE), "groove_gap": _value(inputs, ID_GROOVE_GAP) / fb.IN_TO_CM,
            "groove_d": _value(inputs, ID_GROOVE_D) / fb.IN_TO_CM, "groove_w": _value(inputs, ID_GROOVE_W) / fb.IN_TO_CM,
            "ext": _value(inputs, ID_EXT_A) / fb.IN_TO_CM, "clear": _value(inputs, ID_CLEAR) / fb.IN_TO_CM,
            "gap": _value(inputs, ID_GAP) / fb.IN_TO_CM}})
    except Exception as exc:
        _log.debug("Couldn't remember Shaft & Spacer choices: %s", exc)


def _on_execute(args: adsk.core.CommandEventArgs) -> None:
    _, ui = fh.app_ui()
    inputs = args.command.commandInputs
    try:
        if not _linked(inputs):
            _build_shaft(inputs) if _shaft_mode(inputs) else _build_spacer(inputs)
            if _shaft_mode(inputs):
                _queue_bearings(inputs)
            return
        doc = fh.app_ui()[0].activeDocument
        linked_parts.check_ready(doc)
        if _shaft_mode(inputs):
            comp, req = _shaft_request(inputs)
            linked_parts.queue(doc, comp, [req], "Shaft", {"shaft": _shaft_material(inputs) or ""})
            _queue_bearings(inputs)
        else:
            comp, req = _spacer_request(inputs)
            linked_parts.queue(doc, comp, [req], "Spacer", {"spacer": _spacer_material(inputs) or ""})
    except fb.FeatureError as exc:
        ui.messageBox(str(exc), "Gusset - Shaft & Spacer")
        args.executeFailed = True


def _on_destroy(args: adsk.core.CommandEventArgs) -> None:
    try:
        if args.terminationReason == adsk.core.CommandTerminationReason.CompletedTerminationReason:
            _save(args.command.commandInputs)
    except Exception:
        pass
    _state.clear()
    fh.release_handlers(HANDLER_GROUP)
