"""
Tube - turns sketch lines into 1x1 or 2x1 box tube (Gusset's take on Onshape's
Robot Frame / Tube Converter).

  1. Sketch your frame as lines (one line = one tube, along its centerline).
  2. GUSSET > Tube, click the lines (as many as you like).
  3. Pick 1x1 or 2x1, the wall, whether a 2x1 stands up or lies flat, and where
     the tube sits relative to the sketch (centered, on top of it, or below it).
  4. Optional: extend/shorten the ends, add the 0.5" hole pattern.
  5. Watch the preview (the dialog lists every tube's cut length), press OK.

Create as:
  Bodies in this file (default in a part file): all the tubes from one run are
     one timeline item, "Gusset tubes (N)", named like 'Tube 2x1 x 24.000"'.
  Linked part files (default in an assembly): each tube is saved as its own
     editable part file (sketch + extrude by a "Length" parameter; the hole
     pattern follows it) in the "[Assembly] Parts" folder, and inserted as a
     linked component. Identical tubes share one file.
Moved the sketch? Delete the tubes and run Tube again - it only takes a second.
"""

from __future__ import annotations

import math
import os
from typing import Dict, List

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
from ..lib import tip_box
from . import linked_parts

CMD_ID = "Gusset_Tube"
CMD_NAME = "Tube"
CMD_TOOLTIP = ("Turn sketch lines into 1x1 or 2x1 box tube, with an optional 0.5\" hole pattern. One line = one "
               "tube along its centerline.")
ICON_DIR = os.path.join(config.ADDIN_DIR, "resources", "tube")
HANDLER_GROUP = "tube_dialog"
STATE_KEY = "tube"

_log = gslog.get_logger("tube")

(ID_LINES, ID_SIZE, ID_WALL, ID_STAND, ID_ALIGN, ID_START, ID_END, ID_HOLES, ID_ROWS, ID_MATERIAL, ID_INFO,
 ID_HELP, ID_CREATE) = ("tb_lines", "tb_size", "tb_wall", "tb_stand", "tb_align", "tb_start", "tb_end", "tb_holes", "tb_rows",
             "tb_material", "tb_info", "tb_help", "tb_create")

STAND_CHOICES = ['2" side standing up', '2" side lying flat']
ALIGN_CHOICES = {"Centered on the sketch": "center", "Sitting on top of the sketch": "bottom",
                 "Hanging below the sketch": "top"}
MATERIALS = ["Aluminum 6061", "(leave as is)"]

HELP = (
    "<b>One line = one tube</b>, along the tube's centerline. Draw the frame in a sketch first - lines can "
    "touch at corners; extend or shorten the ends below so tubes butt or overlap the way you'll build them.<br>"
    "<b>Ends</b>: + makes the tube longer past that end of the line, - makes it shorter.<br>"
    "<b>Holes</b>: the 0.5\" pattern starts 0.25\" from the start end. On a 2\" face pick 1, 2 or 3 rows.<br>"
    "The 'start' end is where you began drawing the line."
)

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


def _inches(inputs, input_id) -> float:
    return adsk.core.ValueCommandInput.cast(inputs.itemById(input_id)).value / fb.IN_TO_CM


def _on_created(args: adsk.core.CommandCreatedEventArgs) -> None:
    _log.info("Tube opened")
    cmd = args.command
    _, ui = fh.app_ui()
    if not fh.active_design():
        ui.messageBox("Open a Fusion design first, then try Tube again.", "Gusset")
        return
    _state.clear()
    saved = settings.load_state(config.ADDIN_DIR).get(STATE_KEY)
    last = saved if isinstance(saved, dict) else {}
    inputs = cmd.commandInputs
    tip_box.attach(cmd, CMD_ID)              # 'How to use this' + hover tips (0.13)
    lines = inputs.addSelectionInput(ID_LINES, "Lines", "Click the sketch lines to turn into tube")
    lines.addSelectionFilter("SketchLines")
    lines.setSelectionLimits(1, 0)
    design = fh.active_design()
    in_assembly = design.rootComponent.occurrences.count > 0
    create = _dropdown(inputs, ID_CREATE, "Create as", [linked_parts.LINKED, linked_parts.BODIES],
                       linked_parts.LINKED if in_assembly else linked_parts.BODIES)
    create.tooltip = ("Linked part files: each tube saved in " + linked_parts.assembly_label(fh.app_ui()[0].activeDocument)
                      + " and inserted as a component. Bodies: tubes added to this file.")
    _dropdown(inputs, ID_SIZE, "Tube", list(pc.TUBE_SIZES), str(last.get("size", "2x1")))
    _dropdown(inputs, ID_WALL, "Wall", list(pc.TUBE_WALLS), str(last.get("wall", '1/16" wall')))
    _dropdown(inputs, ID_STAND, "2x1 direction", STAND_CHOICES, str(last.get("stand", STAND_CHOICES[0])))
    _dropdown(inputs, ID_ALIGN, "Position", list(ALIGN_CHOICES), str(last.get("align", list(ALIGN_CHOICES)[0])))
    for input_id, label in ((ID_START, "Start end +/-"), (ID_END, "Far end +/-")):
        vi = inputs.addValueInput(input_id, label, "in", adsk.core.ValueInput.createByString("0 in"))
        vi.tooltip = "Make the tube longer (+) or shorter (-) past this end of the line"
    _dropdown(inputs, ID_HOLES, "Holes", pc.TUBE_HOLE_CHOICES, str(last.get("holes", pc.TUBE_HOLE_CHOICES[0])))
    _dropdown(inputs, ID_ROWS, "Rows on 2\" face", list(pc.HOLE_ROWS), str(last.get("rows", list(pc.HOLE_ROWS)[0])))
    _dropdown(inputs, ID_MATERIAL, "Material", MATERIALS, str(last.get("material", MATERIALS[0])))
    inputs.addTextBoxCommandInput(ID_INFO, "", "Click the lines.", 6, True)
    inputs.addTextBoxCommandInput(ID_HELP, "", HELP, 6, True)
    _show_hide(inputs)
    for event, base, func, label in (
        (cmd.inputChanged, adsk.core.InputChangedEventHandler, _on_input_changed, "input changed"),
        (cmd.executePreview, adsk.core.CommandEventHandler, _on_preview, "preview"),
        (cmd.validateInputs, adsk.core.ValidateInputsEventHandler, _on_validate, "validate"),
        (cmd.execute, adsk.core.CommandEventHandler, _on_execute, "OK"),
        (cmd.destroy, adsk.core.CommandEventHandler, _on_destroy, "close"),
    ):
        event.add(fh.make_handler(base, func, f"Tube: {label}", HANDLER_GROUP))


def _show_hide(inputs) -> None:
    is_2x1 = _choice(inputs, ID_SIZE) == "2x1"
    inputs.itemById(ID_STAND).isVisible = is_2x1
    inputs.itemById(ID_ROWS).isVisible = is_2x1 and _choice(inputs, ID_HOLES) != pc.TUBE_HOLE_CHOICES[0]


def _on_input_changed(args: adsk.core.InputChangedEventArgs) -> None:
    _show_hide(fh.all_inputs(args))


def _linked(inputs) -> bool:
    return _choice(inputs, ID_CREATE) == linked_parts.LINKED


def _tubes(inputs):
    """[(component, plan, frame, p0, p1, normal)] for every selected line."""
    sel = adsk.core.SelectionCommandInput.cast(inputs.itemById(ID_LINES))
    if sel.selectionCount < 1:
        raise fb.FeatureError("Click at least one sketch line.")
    size, wall = _choice(inputs, ID_SIZE), _choice(inputs, ID_WALL)
    tall = size != "2x1" or _choice(inputs, ID_STAND) == STAND_CHOICES[0]
    align = ALIGN_CHOICES[_choice(inputs, ID_ALIGN)]
    start_ext, end_ext = _inches(inputs, ID_START), _inches(inputs, ID_END)
    holes = _choice(inputs, ID_HOLES)
    rows = pc.HOLE_ROWS[_choice(inputs, ID_ROWS)]
    out = []
    for i in range(sel.selectionCount):
        line = adsk.fusion.SketchLine.cast(sel.selection(i).entity)
        sketch, _occ = fb.editable_sketch(line.parentSketch)
        native = adsk.fusion.SketchLine.cast(line.nativeObject) if line.assemblyContext else line
        a = pb.vec(sketch.sketchToModelSpace(native.startSketchPoint.geometry))
        b = pb.vec(sketch.sketchToModelSpace(native.endSketchPoint.geometry))
        normal = pb.cross(pb.vec(sketch.xDirection), pb.vec(sketch.yDirection))
        span = math.dist(a, b) / fb.IN_TO_CM
        plan = pc.plan_tube(size, wall, span + start_ext + end_ext, tall, holes, rows)
        if plan.problems:
            raise fb.FeatureError(f"Line {i + 1}: " + " ".join(plan.problems))
        frame = pb.tube_frame(a, b, normal, plan, start_ext, align)
        out.append((sketch.parentComponent, plan, frame, a, b, normal, start_ext, align))
    return out


def _material(inputs):
    material = _choice(inputs, ID_MATERIAL)
    return None if material == MATERIALS[-1] else material


def _group_by_component(items):
    """
    [(component, [things])] keeping order. Fusion Component objects can't be dict
    keys (unhashable), so group by entityToken and compare with ==.
    """
    groups: List[list] = []
    for comp, thing in items:
        for g in groups:
            if g[0] == comp:
                g[1].append(thing)
                break
        else:
            groups.append([comp, [thing]])
    return groups


def _build(inputs) -> List[str]:
    """Preview / bodies mode: tubes as bodies in their sketch's component."""
    items = []
    names: List[str] = []
    for comp, plan, _frame, a, b, normal, start_ext, align in _tubes(inputs):
        body = pb.tube_body(a, b, normal, plan, start_ext, align)
        items.append((comp, (body, plan.name)))
        names.append(plan.name.replace("Tube ", ""))
    for comp, bodies in _group_by_component(items):
        pb.add_bodies(comp, bodies, f"Gusset tubes ({len(bodies)})", _material(inputs))
    return names


def _queue_linked(inputs) -> None:
    doc = fh.app_ui()[0].activeDocument
    linked_parts.check_ready(doc)
    items = []
    for comp, plan, (axis0, u, w, n), *_rest in _tubes(inputs):
        items.append((comp, pf.PartRequest("tube", pf.tube_file_name(plan), plan,
                                           placements=[pf.Placement(axis0, u, w, n)])))
    for comp, reqs in _group_by_component(items):
        linked_parts.queue(doc, comp, reqs, "Tube", {"tube": _material(inputs) or ""})


def _describe(inputs, made: List[str], error: str = "") -> None:
    box = adsk.core.TextBoxCommandInput.cast(inputs.itemById(ID_INFO))
    if error:
        box.formattedText = "<b>Can't make tube yet:</b> " + fh.safe_text(error)
        return
    if not made:
        box.formattedText = "Click the lines."
        return
    total = sum(float(m.split(" x ")[1].rstrip('"')) for m in made)
    counts: Dict[str, int] = {}
    for m in made:
        counts[m] = counts.get(m, 0) + 1
    cut_list = "<br>".join(f"{n} x {fh.safe_text(name)}" for name, n in sorted(counts.items()))
    text = f"<b>{len(made)}</b> tube(s), {total:.2f}\" total:<br>{cut_list}"
    if _linked(inputs):
        unique = len(counts)
        text += (f"<br>OK saves {unique} part file(s) in "
                 f"{fh.safe_text(linked_parts.assembly_label(fh.app_ui()[0].activeDocument))} "
                 f"(reusing matches) and inserts {len(made)} component(s).")
    box.formattedText = text


def _on_preview(args: adsk.core.CommandEventArgs) -> None:
    inputs = args.command.commandInputs
    try:
        made = _build(inputs)
        _describe(inputs, made)
        # Bodies: the preview IS the result. Linked: OK runs execute -> after-dialog file step.
        args.isValidResult = not _linked(inputs)
    except fb.FeatureError as exc:
        _describe(inputs, [], str(exc))
    except Exception:
        fh.report_error("Tube preview", show_dialog=False)
        _describe(inputs, [], "Something went wrong - see the Text Commands window / gusset.log.")


def _on_validate(args: adsk.core.ValidateInputsEventArgs) -> None:
    args.areInputsValid = adsk.core.SelectionCommandInput.cast(fh.all_inputs(args).itemById(ID_LINES)).selectionCount >= 1


def _save(inputs) -> None:
    try:
        settings.save_state(config.ADDIN_DIR, **{STATE_KEY: {
            "size": _choice(inputs, ID_SIZE), "wall": _choice(inputs, ID_WALL), "stand": _choice(inputs, ID_STAND),
            "align": _choice(inputs, ID_ALIGN), "holes": _choice(inputs, ID_HOLES), "rows": _choice(inputs, ID_ROWS),
            "material": _choice(inputs, ID_MATERIAL)}})
    except Exception as exc:
        _log.debug("Couldn't remember Tube choices: %s", exc)


def _on_execute(args: adsk.core.CommandEventArgs) -> None:
    _, ui = fh.app_ui()
    inputs = args.command.commandInputs
    try:
        if _linked(inputs):
            _queue_linked(inputs)
        else:
            _build(inputs)
    except fb.FeatureError as exc:
        ui.messageBox(str(exc), "Gusset - Tube")
        args.executeFailed = True


def _on_destroy(args: adsk.core.CommandEventArgs) -> None:
    try:
        if args.terminationReason == adsk.core.CommandTerminationReason.CompletedTerminationReason:
            _save(args.command.commandInputs)
    except Exception:
        pass
    _state.clear()
    fh.release_handlers(HANDLER_GROUP)
