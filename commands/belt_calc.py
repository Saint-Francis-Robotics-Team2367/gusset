"""
Belt & Chain - center-to-center distances for HTD 5mm belts and #25 / #35 chain
(Gusset's take on Origin Cube's FRC Functions + Belt & Chain Gen).

  1. GUSSET > Belt & Chain. Pick the belt/chain and both tooth counts.
  2. Either:
       "I have a distance"  - type where you'd like the pulleys; Gusset lists the
                              real belts (any tooth count) or chains (even links)
                              just shorter and just longer, with their exact centers.
       "I have a belt/chain" - type its teeth/links; Gusset gives the exact center.
  3. Optional: click a sketch point (pulley 1's center) and a direction (a line
     or another point) and press OK. Gusset draws pulley 2's center at exactly
     the right distance, both pitch circles and the belt's straight runs
     (construction lines), with a dimension on the center distance.

Many teams add a few thousandths to belt centers so belts aren't over-tight:
put that in "Add to center".
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
from ..lib import parts_builder as pb
from ..lib import cots_match as cm
from ..lib import placement_core as pl
from ..lib import settings
from ..lib import tip_box
from . import cots_autoplace, cots_browser

CMD_ID = "Gusset_BeltCalc"
CMD_NAME = "Belt & Chain"
CMD_TOOLTIP = "Exact center distances for HTD 5mm belts and #25/#35 chain - and draw them into a sketch."
ICON_DIR = os.path.join(config.ADDIN_DIR, "resources", "belt")
HANDLER_GROUP = "belt_dialog"
STATE_KEY = "belt"

_log = gslog.get_logger("belt")

MODE_DISTANCE, MODE_COUNT = "I have a distance - find belts/chains", "I have a belt/chain - find the distance"
(ID_DRIVE, ID_T1, ID_T2, ID_MODE, ID_TARGET, ID_COUNT, ID_EXTRA, ID_PICK, ID_P1, ID_DIR, ID_RESULT) = (
    "bc_drive", "bc_t1", "bc_t2", "bc_mode", "bc_target", "bc_count", "bc_extra", "bc_pick", "bc_p1", "bc_dir",
    "bc_result")
ID_LIB, ID_WIDTH, ID_BORE, ID_LIBINFO = "bc_lib", "bc_width", "bc_bore", "bc_libinfo"   # library pulleys (0.12)

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


def _int(inputs, input_id) -> int:
    return adsk.core.IntegerSpinnerCommandInput.cast(inputs.itemById(input_id)).value


def _inches(inputs, input_id) -> float:
    return adsk.core.ValueCommandInput.cast(inputs.itemById(input_id)).value / fb.IN_TO_CM


def _on_created(args: adsk.core.CommandCreatedEventArgs) -> None:
    _log.info("Belt & Chain opened")
    cmd = args.command
    _state.clear()
    saved = settings.load_state(config.ADDIN_DIR).get(STATE_KEY)
    last = saved if isinstance(saved, dict) else {}
    inputs = cmd.commandInputs
    tip_box.attach(cmd, CMD_ID)              # 'How to use this' + hover tips (0.13)
    _dropdown(inputs, ID_DRIVE, "Belt / chain", list(pc.DRIVES), str(last.get("drive", "HTD 5mm belt")))
    inputs.addIntegerSpinnerCommandInput(ID_T1, "Pulley 1 teeth", 8, 120, 1, int(last.get("t1", 18)))
    inputs.addIntegerSpinnerCommandInput(ID_T2, "Pulley 2 teeth", 8, 120, 1, int(last.get("t2", 36)))
    _dropdown(inputs, ID_MODE, "I know", [MODE_DISTANCE, MODE_COUNT], str(last.get("mode", MODE_DISTANCE)))
    inputs.addValueInput(ID_TARGET, "Target center", "in", adsk.core.ValueInput.createByString(
        f"{float(last.get('target', 6.0))} in"))
    inputs.addIntegerSpinnerCommandInput(ID_COUNT, "Belt teeth / links", 10, 1000, 1, int(last.get("count", 90)))
    inputs.addValueInput(ID_EXTRA, "Add to center", "in", adsk.core.ValueInput.createByString(
        f"{float(last.get('extra', 0.0))} in")).tooltip = "Your team's usual extra (e.g. 0.003\") so belts aren't tight"
    inputs.addDropDownCommandInput(ID_PICK, "Draw this one", adsk.core.DropDownStyles.TextListDropDownStyle)
    p1 = inputs.addSelectionInput(ID_P1, "Pulley 1 center", "Optional: click a sketch point to draw from")
    p1.addSelectionFilter("SketchPoints")
    p1.setSelectionLimits(0, 1)
    d = inputs.addSelectionInput(ID_DIR, "Toward", "Click a sketch line or point in the direction of pulley 2")
    for f in ("SketchLines", "SketchPoints"):
        d.addSelectionFilter(f)
    d.setSelectionLimits(0, 1)
    # Library pulleys: after drawing, Gusset inserts the matching FRC_COTS pulley on each center.
    lib = inputs.addBoolValueInput(ID_LIB, "Insert library pulleys", True, "", bool(last.get("library", True)))
    lib.tooltip = "After drawing, put the matching pulley (or sprocket) from the COTS Library on each center"
    widths, bores = cm.drive_choices(cots_browser.catalog(), _choice(inputs, ID_DRIVE))
    _dropdown(inputs, ID_WIDTH, "Pulley width", widths, str(last.get("width", cm.ANY)))
    _dropdown(inputs, ID_BORE, "Pulley bore", bores, str(last.get("bore", cm.ANY)))
    inputs.addTextBoxCommandInput(ID_LIBINFO, "", "", 3, True)
    inputs.addTextBoxCommandInput(ID_RESULT, "", "", 10, True)
    _refresh(inputs)
    for event, base, func, label in (
        (cmd.inputChanged, adsk.core.InputChangedEventHandler, _on_input_changed, "input changed"),
        (cmd.executePreview, adsk.core.CommandEventHandler, _on_preview, "preview"),
        (cmd.execute, adsk.core.CommandEventHandler, _on_execute, "OK"),
        (cmd.destroy, adsk.core.CommandEventHandler, _on_destroy, "close"),
    ):
        event.add(fh.make_handler(base, func, f"Belt & Chain: {label}", HANDLER_GROUP))


def _options(inputs) -> List[pc.DriveOption]:
    drive = pc.DRIVES[_choice(inputs, ID_DRIVE)]
    t1, t2, extra = _int(inputs, ID_T1), _int(inputs, ID_T2), _inches(inputs, ID_EXTRA)
    if _choice(inputs, ID_MODE) == MODE_COUNT:
        count = _int(inputs, ID_COUNT)
        c = pc.center_for(drive, t1, t2, count)
        return [] if c != c else [pc.DriveOption(count, c + extra, 0.0)]
    return pc.options_near(drive, t1, t2, _inches(inputs, ID_TARGET), extra)


def _refresh(inputs) -> None:
    mode_count = _choice(inputs, ID_MODE) == MODE_COUNT
    inputs.itemById(ID_TARGET).isVisible = not mode_count
    inputs.itemById(ID_COUNT).isVisible = mode_count
    drive = pc.DRIVES[_choice(inputs, ID_DRIVE)]
    t1, t2 = _int(inputs, ID_T1), _int(inputs, ID_T2)
    unit = "T belt" if drive.kind == "belt" else " links"
    lines = [f"Pitch diameters: {pc.pitch_diameter(drive, t1):.4f}\" and {pc.pitch_diameter(drive, t2):.4f}\" - "
             f"ratio {pc.ratio(t1, t2):.3f}:1"]
    try:
        opts = _options(inputs)
    except Exception as exc:
        _log.debug("Belt options failed: %s", exc)
        opts = []
    pick = adsk.core.DropDownCommandInput.cast(inputs.itemById(ID_PICK))
    old = pick.selectedItem.name if pick.selectedItem else ""
    pick.listItems.clear()
    if not opts:
        lines.append("<b>Too short</b> to wrap both - use more teeth/links or a longer distance.")
    for o in opts:
        label = f"{o.count}{unit}: {o.center_in:.4f}\""
        if not mode_count:
            label += f" ({o.delta_in:+.3f}\")"
        pick.listItems.add(label, False)
    if pick.listItems.count:
        names = [pick.listItems.item(i).name for i in range(pick.listItems.count)]
        # default: keep the last pick, else the option closest to the target
        idx = names.index(old) if old in names else min(range(len(opts)), key=lambda i: abs(opts[i].delta_in))
        pick.listItems.item(idx).isSelected = True
    if opts and not mode_count:
        lines.append("<b>Closest real ones</b> (center, and how far from your target):")
        lines += [f"• {o.count}{unit} → {o.center_in:.4f}\" ({o.delta_in:+.3f}\")" for o in opts]
    elif opts:
        lines.append(f"<b>Center distance: {opts[0].center_in:.4f}\"</b>")
    if drive.kind == "chain":
        lines.append("Chain needs an even number of links (no half-link), so only even counts are listed.")
    lines.append("To draw it: click pulley 1's center (a sketch point) and a direction, then OK.")
    _state["opts"] = opts
    adsk.core.TextBoxCommandInput.cast(inputs.itemById(ID_RESULT)).formattedText = "<br>".join(lines)
    _refresh_library(inputs)


def _matches(inputs) -> List[cm.Match]:
    drive, items = _choice(inputs, ID_DRIVE), cots_browser.catalog()
    width, bore = _choice(inputs, ID_WIDTH) or cm.ANY, _choice(inputs, ID_BORE) or cm.ANY
    usage = cots_browser.usage()
    return [cm.pulley_for(items, t, drive, width, bore, usage) for t in (_int(inputs, ID_T1), _int(inputs, ID_T2))]


def _refresh_library(inputs) -> None:
    on = adsk.core.BoolValueCommandInput.cast(inputs.itemById(ID_LIB)).value
    for i in (ID_WIDTH, ID_BORE, ID_LIBINFO):
        inputs.itemById(i).isVisible = on
    if not on:
        return
    try:
        lines = []
        for n, match in enumerate(_matches(inputs), 1):
            mark = "&#10003;" if match.best else "&#9888;"
            lines.append(f"{mark} Pulley {n}: {fh.safe_text(match.why)}")
        if not cots_browser.catalog():
            lines = ["Open the COTS panel once so Gusset knows what's in the library."]
    except Exception as exc:
        _log.debug("Library pulley lookup failed: %s", exc)
        lines = ["Couldn't look in the library - see the Gusset log."]
    adsk.core.TextBoxCommandInput.cast(inputs.itemById(ID_LIBINFO)).formattedText = "<br>".join(lines)


def _rebuild_library_choices(inputs) -> None:
    """A new belt/chain has its own widths and bores."""
    widths, bores = cm.drive_choices(cots_browser.catalog(), _choice(inputs, ID_DRIVE))
    for input_id, values in ((ID_WIDTH, widths), (ID_BORE, bores)):
        dd = adsk.core.DropDownCommandInput.cast(inputs.itemById(input_id))
        old = dd.selectedItem.name if dd.selectedItem else cm.ANY
        dd.listItems.clear()
        for v in values:
            dd.listItems.add(v, v == (old if old in values else cm.ANY))


def _on_input_changed(args: adsk.core.InputChangedEventArgs) -> None:
    inputs = fh.all_inputs(args)
    if args.input.id == ID_DRIVE:
        _rebuild_library_choices(inputs)
    if args.input.id in (ID_LIB, ID_WIDTH, ID_BORE):
        _refresh_library(inputs)
    elif args.input.id != ID_PICK:
        _refresh(inputs)


def _draw(inputs, place: bool = False) -> bool:
    """
    Draw the picked option into the sketch, if a center + direction were picked.
    place=True (OK, not the preview): also queue the library pulleys for each center.
    """
    p1_sel = adsk.core.SelectionCommandInput.cast(inputs.itemById(ID_P1))
    dir_sel = adsk.core.SelectionCommandInput.cast(inputs.itemById(ID_DIR))
    if p1_sel.selectionCount != 1:
        return False
    if dir_sel.selectionCount != 1:
        raise fb.FeatureError("Click a line or point in the direction of pulley 2 too.")
    point = adsk.fusion.SketchPoint.cast(p1_sel.selection(0).entity)
    sketch, _occ = fb.editable_sketch(point.parentSketch)
    p1 = pb.sketch_point_2d(sketch, point)
    target = dir_sel.selection(0).entity
    line = adsk.fusion.SketchLine.cast(target)
    if line:
        a = pb.sketch_point_2d(sketch, line.startSketchPoint)
        b = pb.sketch_point_2d(sketch, line.endSketchPoint)
        far = b if math.dist(b, p1) >= math.dist(a, p1) else a
        near = a if far is b else b
        # A line through pulley 1 points away from it; any other line just gives a direction.
        direction = (far[0] - near[0], far[1] - near[1]) if min(math.dist(a, p1), math.dist(b, p1)) > 1e-6 else \
            (far[0] - p1[0], far[1] - p1[1])
    else:
        q = pb.sketch_point_2d(sketch, adsk.fusion.SketchPoint.cast(target))
        direction = (q[0] - p1[0], q[1] - p1[1])
    opts = _state.get("opts") or []
    pick = adsk.core.DropDownCommandInput.cast(inputs.itemById(ID_PICK)).selectedItem
    if not opts or pick is None:
        raise fb.FeatureError("There's nothing to draw - fix the numbers first.")
    option = opts[pick.index]  # type: ignore[index]
    drive = pc.DRIVES[_choice(inputs, ID_DRIVE)]
    t1, t2 = _int(inputs, ID_T1), _int(inputs, ID_T2)
    unit = "T belt" if drive.kind == "belt" else " links"
    centers = pb.draw_drive(sketch, p1, direction, option.center_in, pc.pitch_diameter(drive, t1),
                            pc.pitch_diameter(drive, t2), f"{drive.name} {t1}T-{t2}T {option.count}{unit}")
    if place and adsk.core.BoolValueCommandInput.cast(inputs.itemById(ID_LIB)).value:
        _queue_pulleys(inputs, sketch, _occ, centers)
    _log.info("Drew %s %dT-%dT, %d%s, C=%.4f in sketch %s", drive.name, t1, t2, option.count, unit,
              option.center_in, sketch.name)
    return True


def _to_top(occ, point=None, vector=None):
    """Sketch-component coordinates -> the top assembly's (through the occurrence it was picked in)."""
    if occ is not None:
        m = occ.transform2
        if point is not None:
            point.transformBy(m)
        if vector is not None:
            vector.transformBy(m)
    return point if point is not None else vector


def _queue_pulleys(inputs, sketch, occ, centers) -> None:
    """Each center with a library match gets its pulley, centered on the sketch's plane, axis square to it."""
    normal = sketch.xDirection.crossProduct(sketch.yDirection)
    normal.normalize()
    normal = _to_top(occ, vector=normal)
    requests, missing = [], []
    for n, (match, center) in enumerate(zip(_matches(inputs), centers), 1):
        if match.best is None:
            missing.append(f"Pulley {n}: {match.why}")
            continue
        point = _to_top(occ, point=center.worldGeometry.copy())
        requests.append(cots_autoplace.request(match.best, point, normal, pl.CENTER, anchor=occ,
                                               label=f"Pulley {n} ({match.best.info.vendor_pn})"))
    _log.info("Belt & Chain: %d library pulley(s) to place, %d not in the library", len(requests), len(missing))
    cots_autoplace.queue(requests, "Belt & Chain")
    if missing:
        fh.app_ui()[1].messageBox("Drew the belt. These pulleys aren't in the library, so only their circles "
                                  "were drawn:\n\n- " + "\n- ".join(missing), "Gusset - Belt & Chain")


def _on_preview(args: adsk.core.CommandEventArgs) -> None:
    try:
        inputs = args.command.commandInputs
        if _draw(inputs):
            # A kept preview means Fusion skips OK - but OK is where library pulleys are queued,
            # so only keep it when there are none to add.
            args.isValidResult = not adsk.core.BoolValueCommandInput.cast(inputs.itemById(ID_LIB)).value
    except fb.FeatureError as exc:
        _log.debug("Belt draw preview: %s", exc)
    except Exception:
        fh.report_error("Belt & Chain preview", show_dialog=False)


def _save(inputs) -> None:
    try:
        settings.save_state(config.ADDIN_DIR, **{STATE_KEY: {
            "drive": _choice(inputs, ID_DRIVE), "t1": _int(inputs, ID_T1), "t2": _int(inputs, ID_T2),
            "mode": _choice(inputs, ID_MODE), "target": _inches(inputs, ID_TARGET), "count": _int(inputs, ID_COUNT),
            "extra": _inches(inputs, ID_EXTRA),
            "library": adsk.core.BoolValueCommandInput.cast(inputs.itemById(ID_LIB)).value,
            "width": _choice(inputs, ID_WIDTH), "bore": _choice(inputs, ID_BORE)}})
    except Exception as exc:
        _log.debug("Couldn't remember Belt & Chain choices: %s", exc)


def _on_execute(args: adsk.core.CommandEventArgs) -> None:
    _, ui = fh.app_ui()
    try:
        _draw(args.command.commandInputs, place=True)
    except fb.FeatureError as exc:
        ui.messageBox(str(exc), "Gusset - Belt & Chain")
        args.executeFailed = True


def _on_destroy(args: adsk.core.CommandEventArgs) -> None:
    _save(args.command.commandInputs)      # remember even after Cancel - most uses are just the numbers
    _state.clear()
    fh.release_handlers(HANDLER_GROUP)
