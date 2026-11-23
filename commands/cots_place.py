"""
Place COTS Part - runs right after a part is inserted from the COTS panel.

  1. "Put it on": click a round edge, a round (cylindrical) face, a flat face,
     a sketch/construction point or a joint origin in your design.
  2. Optional "Part's mounting spot": click a round edge / face / joint origin
     ON THE NEW PART (e.g. a motor's face). Otherwise Gusset uses the part's
     first joint origin, or its origin.
  3. Flip / Angle / Offset to adjust; the part moves live (rigid joint).
  OK keeps the joint. Cancel leaves the part where it was inserted (the origin).

Only one dialog: not a toolbar button (cots_browser starts it).
"""

from __future__ import annotations

from typing import Dict, Optional

import adsk.core
import adsk.fusion

from ..lib import fusion_helpers as fh
from ..lib import log as gslog
from ..lib import tip_box

CMD_ID = "Gusset_CotsPlace"
CMD_NAME = "Place COTS Part"
HANDLER_GROUP = "cots_place"
ID_TARGET, ID_PART, ID_FLIP, ID_ANGLE, ID_OFFSET, ID_INFO = (
    "cp_target", "cp_part", "cp_flip", "cp_angle", "cp_offset", "cp_info")

_log = gslog.get_logger("cots_place")
_state: Dict[str, object] = {}


def start() -> None:
    _, ui = fh.app_ui()
    old = ui.commandDefinitions.itemById(CMD_ID)
    if old:
        old.deleteMe()
    cmd_def = ui.commandDefinitions.addButtonDefinition(CMD_ID, CMD_NAME, "Attach the new COTS part", "")
    cmd_def.commandCreated.add(fh.make_handler(adsk.core.CommandCreatedEventHandler, _on_created,
                                               "Place COTS: open"))


def stop() -> None:
    _, ui = fh.app_ui()
    try:
        cmd_def = ui.commandDefinitions.itemById(CMD_ID)
        if cmd_def:
            cmd_def.deleteMe()
    except Exception:
        pass


def start_placing(occurrence, design) -> None:
    """Called by the COTS panel right after inserting."""
    occ = occurrence
    if design.activeOccurrence:                       # inserted into a sub-assembly -> work from the top
        occ = occurrence.createForAssemblyContext(design.activeOccurrence)
    _state.clear()
    _state["occ"] = occ
    try:
        occurrence.isGrounded = False
    except Exception:
        pass
    _, ui = fh.app_ui()
    ui.commandDefinitions.itemById(CMD_ID).execute()


def _on_created(args: adsk.core.CommandCreatedEventArgs) -> None:
    cmd = args.command
    occ = _state.get("occ")
    inputs = cmd.commandInputs
    tip_box.attach(cmd, CMD_ID)              # 'How to use this' + hover tips (0.13)
    if occ is None:
        inputs.addTextBoxCommandInput(ID_INFO, "", "Insert a part from the COTS Library panel first.", 2, True)
        return
    cmd.okButtonText = "Attach"
    inputs.addTextBoxCommandInput(ID_INFO, "", f"<b>{fh.safe_text(occ.component.name)}</b> - click where it goes.",
                                  2, True)
    target = inputs.addSelectionInput(ID_TARGET, "Put it on", "Round edge, round or flat face, point or joint origin")
    for f in ("CircularEdges", "CylindricalFaces", "PlanarFaces", "SketchPoints", "ConstructionPoints",
              "JointOrigins", "Vertices"):
        target.addSelectionFilter(f)
    target.setSelectionLimits(1, 1)
    part = inputs.addSelectionInput(ID_PART, "Part's mounting spot", "Optional: a round edge/face on the new part")
    for f in ("CircularEdges", "CylindricalFaces", "PlanarFaces", "JointOrigins"):
        part.addSelectionFilter(f)
    part.setSelectionLimits(0, 1)
    inputs.addBoolValueInput(ID_FLIP, "Flip", True, "", False)
    inputs.addValueInput(ID_ANGLE, "Angle", "deg", adsk.core.ValueInput.createByString("0 deg"))
    inputs.addValueInput(ID_OFFSET, "Offset", "in", adsk.core.ValueInput.createByString("0 in"))
    for event, base, func, label in (
        (cmd.preSelect, adsk.core.SelectionEventHandler, _on_pre_select, "pre-select"),
        (cmd.executePreview, adsk.core.CommandEventHandler, _on_preview, "preview"),
        (cmd.execute, adsk.core.CommandEventHandler, _on_execute, "OK"),
        (cmd.destroy, adsk.core.CommandEventHandler, _on_destroy, "close"),
    ):
        event.add(fh.make_handler(base, func, f"Place COTS: {label}", HANDLER_GROUP))


def _on_new_part(entity) -> bool:
    """True if entity belongs to the part being placed (or a component inside it)."""
    occ = _state.get("occ")
    ctx = getattr(entity, "assemblyContext", None)
    while ctx is not None:
        if ctx.fullPathName == occ.fullPathName:
            return True
        ctx = ctx.assemblyContext
    return False


def _on_pre_select(args: adsk.core.SelectionEventArgs) -> None:
    on_part = _on_new_part(args.selection.entity)
    if args.activeInput.id == ID_TARGET and on_part:
        args.isSelectable = False                      # can't attach the part to itself
    elif args.activeInput.id == ID_PART and not on_part:
        args.isSelectable = False


def _geometry(entity):
    """JointGeometry (or a JointOrigin) for anything the student can click."""
    if isinstance(entity, adsk.fusion.JointOrigin):
        return entity
    if isinstance(entity, adsk.fusion.BRepEdge):
        return adsk.fusion.JointGeometry.createByCurve(entity, adsk.fusion.JointKeyPointTypes.CenterKeyPoint)
    if isinstance(entity, adsk.fusion.BRepFace):
        if isinstance(entity.geometry, adsk.core.Plane):
            return adsk.fusion.JointGeometry.createByPlanarFace(entity, None,
                                                                adsk.fusion.JointKeyPointTypes.CenterKeyPoint)
        return adsk.fusion.JointGeometry.createByNonPlanarFace(entity, adsk.fusion.JointKeyPointTypes.MiddleKeyPoint)
    return adsk.fusion.JointGeometry.createByPoint(entity)


def _part_geometry(inputs):
    sel = inputs.itemById(ID_PART)
    if sel.selectionCount:
        return _geometry(sel.selection(0).entity)
    occ = _state["occ"]
    comp = occ.component
    if comp.jointOrigins.count:
        return comp.jointOrigins.item(0).createForAssemblyContext(occ)
    return adsk.fusion.JointGeometry.createByPoint(comp.originConstructionPoint.createForAssemblyContext(occ))


def _make_joint(inputs) -> Optional[object]:
    target = inputs.itemById(ID_TARGET)
    if target.selectionCount == 0:
        return None
    design = fh.active_design()
    joints = design.rootComponent.joints
    joint_input = joints.createInput(_part_geometry(inputs), _geometry(target.selection(0).entity))
    joint_input.setAsRigidJointMotion()
    joint_input.isFlipped = adsk.core.BoolValueCommandInput.cast(inputs.itemById(ID_FLIP)).value
    joint_input.angle = adsk.core.ValueInput.createByReal(
        adsk.core.ValueCommandInput.cast(inputs.itemById(ID_ANGLE)).value)
    joint_input.offset = adsk.core.ValueInput.createByReal(
        adsk.core.ValueCommandInput.cast(inputs.itemById(ID_OFFSET)).value)
    joint = joints.add(joint_input)
    joint.name = f"COTS {_state['occ'].component.name}"[:60]
    return joint


def _on_preview(args: adsk.core.CommandEventArgs) -> None:
    try:
        if _make_joint(fh.all_inputs(args)):
            args.isValidResult = True                  # keep the preview as the result
    except Exception as exc:
        _log.debug("Joint preview failed: %s", exc)


def _on_execute(args: adsk.core.CommandEventArgs) -> None:
    joint = _make_joint(fh.all_inputs(args))
    if joint:
        _log.info("Attached %s (rigid joint)", _state["occ"].name)


def _on_destroy(args: adsk.core.CommandEventArgs) -> None:
    _state.clear()
    fh.release_handlers(HANDLER_GROUP)
