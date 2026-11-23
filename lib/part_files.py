"""
part_files.py - makes shafts, spacers and tubes as their OWN part files and links
them into the assembly (the team's "[Assembly] Parts" folder layout).

Each part file is a normal, editable design:
  Shaft   sketch (1/2" hex) + extrude by the user parameter "Length";
          tapped ends are cuts "TapDepth" deep.
  Spacer  sketch (circle dimensioned "OD" + hex bore) + extrude by "Length".
  Tube    sketch (outer + inner rectangle) + extrude by "Length"; the 0.5"
          hole pattern is a rectangular pattern whose count follows Length.
Change a parameter (Modify > Change Parameters) and the part updates - in every
assembly that links it.

Fusion can't save files during a command, so the commands hand a list of
PartRequests to run_requests() through a custom event right after OK.
Names/grouping rules live in part_files_core.py (tested).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import List, Optional

import adsk.core
import adsk.fusion

from . import feature_builder as fb
from . import frc_parts_core as pc
from . import log as gslog
from . import part_files_core as pf

_log = gslog.get_logger("part_files")
CM = fb.IN_TO_CM
SAVE_TIMEOUT_S = 90


def _P(x, y, z=0.0):
    return adsk.core.Point3D.create(x, y, z)


def _V(t):
    return adsk.core.Vector3D.create(*t)


def _vi(expr: str):
    return adsk.core.ValueInput.createByString(expr)


# ---------------------------------------------------------------------------
# Folders and files
# ---------------------------------------------------------------------------
def parts_folder(assembly_doc):
    """The '[Assembly] Parts' folder next to the assembly (made if missing)."""
    data_file = assembly_doc.dataFile
    if data_file is None:
        raise fb.FeatureError("Save this assembly first - Gusset puts new parts in a folder next to it.")
    parent = data_file.parentFolder
    name = pf.parts_folder_name(data_file.name)
    folder = parent.dataFolders.itemByName(name)
    if folder is None:
        folder = parent.dataFolders.add(name)
        _log.info("Made folder %r", name)
    return folder


def find_existing(folder, name: str):
    files = folder.dataFiles
    for i in range(files.count):
        f = files.item(i)
        if f.fileExtension == "f3d" and pf.matches(f.name, name):
            return f
    return None


def _wait_until_complete(data_file) -> None:
    """New files keep processing in the cloud after save; inserting too early fails."""
    start = time.time()
    while not data_file.isComplete:
        if time.time() - start > SAVE_TIMEOUT_S:
            raise fb.FeatureError(f"'{data_file.name}' is still uploading after {SAVE_TIMEOUT_S}s - check your "
                                  "connection, then insert it from the Parts folder by hand.")
        adsk.doEvents()
        time.sleep(0.25)


# ---------------------------------------------------------------------------
# Building the part designs (parametric)
# ---------------------------------------------------------------------------
def _new_design():
    app = adsk.core.Application.get()
    try:
        # A hidden document would be nicest, but Fusion doesn't support that yet
        # ("API Function not yet implemented") - so a tab flashes open and closes.
        doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType, False)
    except RuntimeError as exc:
        _log.debug("Hidden document not supported (%s); using a normal tab", exc)
        doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType, True)
    design = adsk.fusion.Design.cast(doc.products.itemByProductType("DesignProductType"))
    design.designType = adsk.fusion.DesignTypes.ParametricDesignType
    try:
        design.fusionUnitsManager.distanceDisplayUnits = adsk.fusion.DistanceUnits.InchDistanceUnits
    except Exception:
        pass
    return doc, design


def _param(design, name: str, inches: float, comment: str):
    design.userParameters.add(name, _vi(f"{inches:.4f} in"), "in", comment)


def _polygon(sketch, pts) -> None:
    lines = sketch.sketchCurves.sketchLines
    first = prev = None
    for i, p in enumerate(pts):
        if i == 0:
            continue
        a = prev.endSketchPoint if prev else _P(*pts[0])
        line = lines.addByTwoPoints(a, _P(*p))
        first = first or line
        prev = line
    lines.addByTwoPoints(prev.endSketchPoint, first.startSketchPoint)


def _hexagon(sketch, flats_cm: float, to_sketch=None) -> None:
    """Hexagon centered on the origin with a pair of flats facing +/-X (model space)."""
    r = flats_cm / (2 * math.cos(math.radians(30)))
    pts = []
    for k in range(6):
        a = math.radians(30 + 60 * k)
        p = _P(r * math.cos(a), r * math.sin(a), 0)
        if to_sketch:
            p = to_sketch(p)
        pts.append((p.x, p.y, 0))
    _polygon(sketch, pts)


def _profile_with_loops(sketch, loops: int):
    for i in range(sketch.profiles.count):
        if sketch.profiles.item(i).profileLoops.count == loops:
            return sketch.profiles.item(i)
    raise fb.FeatureError("Couldn't find the part's sketch profile.")


def _smallest_profile(sketch):
    return min((sketch.profiles.item(i) for i in range(sketch.profiles.count)),
               key=lambda p: p.areaProperties().area)


def _cut(root, profile, body, extent: str, direction=None, through_all=False):
    extrudes = root.features.extrudeFeatures
    inp = extrudes.createInput(profile, adsk.fusion.FeatureOperations.CutFeatureOperation)
    if through_all:
        inp.setTwoSidesExtent(adsk.fusion.ThroughAllExtentDefinition.create(),
                              adsk.fusion.ThroughAllExtentDefinition.create())
    else:
        inp.setOneSideExtent(adsk.fusion.DistanceExtentDefinition.create(_vi(extent)),
                             direction or adsk.fusion.ExtentDirections.PositiveExtentDirection)
    inp.participantBodies = [body]
    return extrudes.add(inp)


def _material(body, name: Optional[str]) -> None:
    if not name:
        return
    from . import parts_builder as pb      # one material lookup for both modes (PLA/PETG included)
    mat = pb.find_material(name, body.parentComponent.parentDesign)
    if mat:
        body.material = mat
    else:
        _log.debug("Material %r not found", name)


def build_shaft(design, plan: pc.ShaftPlan, material: Optional[str]) -> None:
    root = design.rootComponent
    _param(design, "Length", plan.length_in, "Shaft length - change it and the shaft updates")
    sketch = root.sketches.add(root.xYConstructionPlane)
    sketch.name = "Hex 1/2in"
    _hexagon(sketch, pc.HEX_FLATS_IN * CM)
    ext = root.features.extrudeFeatures.addSimple(_profile_with_loops(sketch, 1), _vi("Length"),
                                                  adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    ext.name = "Shaft"
    body = ext.bodies.item(0)
    body.name = "Shaft"
    if plan.tapped:
        _param(design, "TapDepth", pc.TAP_DEPTH_IN, "#10-32 tap drill depth at each end")
        s1 = root.sketches.add(root.xYConstructionPlane)
        s1.name = "Tap start"
        s1.sketchCurves.sketchCircles.addByCenterRadius(_P(0, 0), plan.tap_d_in * CM / 2)
        _cut(root, _smallest_profile(s1), body, "TapDepth").name = "Tap start (#21 drill)"
        planes = root.constructionPlanes
        pin = planes.createInput()
        pin.setByOffset(root.xYConstructionPlane, _vi("Length"))
        end_plane = planes.add(pin)
        end_plane.name = "Shaft end"
        s2 = root.sketches.add(end_plane)
        s2.name = "Tap end"
        s2.sketchCurves.sketchCircles.addByCenterRadius(_P(0, 0), plan.tap_d_in * CM / 2)
        _cut(root, _smallest_profile(s2), body, "TapDepth",
             adsk.fusion.ExtentDirections.NegativeExtentDirection).name = "Tap end (#21 drill)"
    _turn_rings(design, root, body, plan)
    # Tag it like a "Bodies in this file" shaft, in the file's own coordinates (start at the
    # origin, along +Z, flats facing X) - Spacer moves it into the robot through the occurrence.
    from .parts_builder import tag_shaft
    tag_shaft(body, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0), plan.length_in * CM)
    _material(body, material)


def _turn_rings(design, root, body, plan: pc.ShaftPlan) -> None:
    """
    Round journals and snap-ring grooves, as editable cuts: a sketch of a ring
    (outside the hex's corners down to the diameter left) on a plane along the
    shaft, cut its width. The end journal follows the Length parameter.
    """
    from .parts_builder import RING_OUTER_IN
    if plan.round_start or plan.round_end:
        _param(design, "RoundDia", plan.round_d_in, "Turned-round end diameter")
        _param(design, "RoundLen", plan.round_len_in, "Turned-round end length")
    for n, (z0, z1, d) in enumerate(plan.ring_cuts(), start=1):
        is_start = plan.round_start and z0 <= 1e-9 and abs(d - plan.round_d_in) < 1e-9
        is_end = plan.round_end and abs(z1 - plan.length_in) < 1e-6 and abs(d - plan.round_d_in) < 1e-9
        if is_start:
            plane, width, label = root.xYConstructionPlane, "RoundLen", "Round start"
        else:
            pin = root.constructionPlanes.createInput()
            pin.setByOffset(root.xYConstructionPlane, _vi("Length - RoundLen" if is_end else f"{z0:.4f} in"))
            plane = root.constructionPlanes.add(pin)
            plane.name = "Round end" if is_end else f"Groove {n} at {(z0 + z1) / 2:.3f} in"
            width, label = ("RoundLen", "Round end") if is_end else (f"{z1 - z0:.4f} in", plane.name)
        sketch = root.sketches.add(plane)
        sketch.name = label
        circles = sketch.sketchCurves.sketchCircles
        circles.addByCenterRadius(_P(0, 0), RING_OUTER_IN * CM)
        inner = circles.addByCenterRadius(_P(0, 0), d * CM / 2)
        if is_start or is_end:
            try:
                sketch.sketchDimensions.addDiameterDimension(inner, _P(d * CM, d * CM)).parameter.expression = "RoundDia"
            except Exception as exc:
                _log.debug("Couldn't tie the round end to RoundDia: %s", exc)
        _cut(root, _profile_with_loops(sketch, 2), body, width).name = (
            label if (is_start or is_end) else f"Snap-ring groove {(z0 + z1) / 2:.3f} in")
    if plan.ring_cuts():
        _log.info("Turned %d section(s) on %s", len(plan.ring_cuts()), plan.name)


def build_spacer(design, plan: pc.SpacerPlan, material: Optional[str]) -> None:
    root = design.rootComponent
    _param(design, "Length", plan.length_in, "Spacer length")
    _param(design, "OD", plan.od_in, "Spacer outside diameter")
    sketch = root.sketches.add(root.xYConstructionPlane)
    sketch.name = "Spacer"
    circle = sketch.sketchCurves.sketchCircles.addByCenterRadius(sketch.originPoint, plan.od_in * CM / 2)
    try:
        dim = sketch.sketchDimensions.addDiameterDimension(circle, _P(plan.od_in * CM, plan.od_in * CM))
        dim.parameter.expression = "OD"
    except Exception as exc:
        _log.debug("Couldn't tie the OD to a parameter: %s", exc)
    _hexagon(sketch, plan.bore_flats_in * CM)
    ext = root.features.extrudeFeatures.addSimple(_profile_with_loops(sketch, 2), _vi("Length"),
                                                  adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    ext.name = "Spacer"
    ext.bodies.item(0).name = "Spacer"
    _material(ext.bodies.item(0), material)


def build_tube(design, plan: pc.TubePlan, material: Optional[str]) -> None:
    """Tube along +X from the origin, centered on the X axis; 'across' along Y, 'up' along Z."""
    root = design.rootComponent
    _param(design, "Length", plan.length_in, "Tube length - the hole pattern follows it")
    sketch = root.sketches.add(root.yZConstructionPlane)
    sketch.name = f"Tube {plan.size}"
    to_s = sketch.modelToSketchSpace
    A, U, T = plan.across_in * CM / 2, plan.up_in * CM / 2, plan.wall_in * CM
    for a, u in ((A, U), (A - T, U - T)):
        p1, p2 = to_s(_P(0, -a, -u)), to_s(_P(0, a, u))
        sketch.sketchCurves.sketchLines.addTwoPointRectangle(_P(p1.x, p1.y), _P(p2.x, p2.y))
    ext = root.features.extrudeFeatures.addSimple(_profile_with_loops(sketch, 2), _vi("Length"),
                                                  adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    ext.name = "Tube"
    body = ext.bodies.item(0)
    body.name = "Tube"
    if plan.hole_d_in:
        r = plan.hole_d_in * CM / 2
        end_clear = max(pc.FIRST_HOLE_IN, plan.hole_d_in)
        count = f"floor((Length - {end_clear + pc.FIRST_HOLE_IN:.4f} in) / {pc.HOLE_PITCH_IN} in) + 1"
        x0 = pc.FIRST_HOLE_IN * CM
        jobs = ((root.xYConstructionPlane, [(x0, o * CM, 0.0) for o in plan.rows_up_faces], "Holes top+bottom"),
                (root.xZConstructionPlane, [(x0, 0.0, o * CM) for o in plan.rows_side_faces], "Holes sides"))
        for plane, centers, label in jobs:
            s = root.sketches.add(plane)
            s.name = label
            for c in centers:
                q = s.modelToSketchSpace(_P(*c))
                s.sketchCurves.sketchCircles.addByCenterRadius(_P(q.x, q.y), r)
            profiles = adsk.core.ObjectCollection.create()
            for i in range(s.profiles.count):
                profiles.add(s.profiles.item(i))
            extrudes = root.features.extrudeFeatures
            inp = extrudes.createInput(profiles, adsk.fusion.FeatureOperations.CutFeatureOperation)
            # Through ALL in BOTH directions (the sketch sits mid-tube): "symmetric all"
            # only went one way and cut a single wall.
            inp.setTwoSidesExtent(adsk.fusion.ThroughAllExtentDefinition.create(),
                                  adsk.fusion.ThroughAllExtentDefinition.create())
            inp.participantBodies = [body]
            cut = extrudes.add(inp)
            cut.name = label
            things = adsk.core.ObjectCollection.create()
            things.add(cut)
            pats = root.features.rectangularPatternFeatures
            pin = pats.createInput(things, root.xConstructionAxis, _vi(count), _vi(f"{pc.HOLE_PITCH_IN} in"),
                                   adsk.fusion.PatternDistanceType.SpacingPatternDistanceType)
            # Fusion's normal ("adjust") compute: the faster "identical" option fails on
            # through-all hole cuts (PATTERN_FEATURES_NO_PASTE_INT_EDGES).
            pats.add(pin).name = label + " pattern"
    _material(body, material)


BUILDERS = {"shaft": build_shaft, "spacer": build_spacer, "tube": build_tube}


def _close(doc) -> None:
    """
    Close a part tab Gusset opened (it's saved, so nothing is lost). Never raises:
    seen in Fusion (0.12 Shaft test) - after saving, the Document object can already
    be gone ("refers to a deleted Object"), which means the tab is closed. That used
    to stop the shaft from being inserted at all.
    """
    try:
        name = doc.name
    except Exception:
        _log.debug("The part's tab is already closed")
        return
    for attempt in range(3):
        try:
            if doc.close(False):
                return
        except Exception as exc:
            if "deleted" in str(exc).lower():
                _log.debug("%s's tab is already closed", name)
                return
            _log.debug("Close attempt %d failed: %s", attempt + 1, exc)
        adsk.doEvents()
        time.sleep(0.5)
    _log.warning("Couldn't close the tab for %s - close it by hand (it's already saved)", name)


# ---------------------------------------------------------------------------
# The whole after-dialog job
# ---------------------------------------------------------------------------
@dataclass
class LinkReport:
    folder: str = ""
    made: List[str] = field(default_factory=list)
    reused: List[str] = field(default_factory=list)
    copies: int = 0
    failures: List[str] = field(default_factory=list)

    def text(self) -> str:
        lines = []
        if self.made:
            lines.append(f"Saved {len(self.made)} new part file(s) in '{self.folder}':")
            lines += [f"  • {n}" for n in self.made]
        if self.reused:
            lines.append(f"Reused {len(self.reused)} part file(s) already in '{self.folder}':")
            lines += [f"  • {n}" for n in self.reused]
        lines.append(f"Inserted {self.copies} linked component(s) into the assembly.")
        if self.failures:
            lines.append("")
            lines.append("Problems:")
            lines += [f"  • {f}" for f in self.failures]
        lines.append("")
        lines.append("Save the assembly to keep the new components.")
        return "\n".join(lines)


def _matrix(pl: pf.Placement):
    m = adsk.core.Matrix3D.create()
    m.setWithCoordinateSystem(_P(*pl.origin), _V(pl.x), _V(pl.y), _V(pl.z))
    return m


def run_requests(assembly_doc, target_comp, requests: List[pf.PartRequest], material: Optional[str] = None,
                 materials: Optional[dict] = None) -> LinkReport:
    """Make (or reuse) each part file, then insert every placement as a linked occurrence."""
    app = adsk.core.Application.get()
    ui = app.userInterface
    report = LinkReport()
    folder = parts_folder(assembly_doc)
    report.folder = folder.name
    groups = pf.group_requests(requests)
    progress = ui.progressBar
    try:
        progress.show("Gusset: part %v of %m", 0, max(len(groups), 1), False)
    except Exception:
        progress = None
    for n, req in enumerate(groups, start=1):
        if progress:
            progress.progressValue = n - 1
        try:
            data_file = find_existing(folder, req.file_name)
            if data_file is not None:
                report.reused.append(data_file.name)
                _log.info("Reusing %s", data_file.name)
            else:
                doc, design = _new_design()
                try:
                    mat = (materials or {}).get(req.kind, material)
                    BUILDERS[req.kind](design, req.plan, mat)
                    # Files made by a script get a timestamp Part Number ("2026-11-18-12-26-49-698");
                    # use the descriptive name until Name Parts gives it a team number.
                    try:
                        design.rootComponent.partNumber = req.file_name
                        design.rootComponent.description = req.file_name
                    except Exception as exc:
                        _log.debug("Couldn't set the part number on %s: %s", req.file_name, exc)
                    if not doc.saveAs(req.file_name, folder, "Made by Gusset", ""):
                        raise fb.FeatureError(f"Fusion didn't save '{req.file_name}'.")
                    data_file = doc.dataFile
                    _wait_until_complete(data_file)       # Fusion won't close a file mid-upload
                finally:
                    _close(doc)
                report.made.append(req.file_name)
                _log.info("Saved %s in %s", req.file_name, folder.name)
            assembly_doc.activate()
            for pl in req.placements:
                occ = target_comp.occurrences.addByInsert(data_file, _matrix(pl), True)
                if occ is None:
                    raise fb.FeatureError(f"Fusion couldn't insert '{req.file_name}'.")
                report.copies += 1
        except fb.FeatureError as exc:
            report.failures.append(str(exc))
        except Exception as exc:
            _log.exception("Linking %s failed", req.file_name)
            report.failures.append(f"{req.file_name}: {exc}")
    if progress:
        progress.hide()
    try:
        assembly_doc.activate()
    except Exception:
        pass
    return report
