"""
lighten_builder.py - the Fusion side of Quick Rib and Lighten.

The math (where ribs go, which regions become pockets) lives in lighten_core.py
and is unit-tested. This file only talks to Fusion:

  read_plate()       face loops      -> lighten_core.Plate (inches, sketch 2D)
  read_sketch_ribs() student sketch  -> list of Rib
  draw_rib_lines()   Quick Rib       -> plain sketch lines the student can edit
  lighten()          the whole job: draw wall/boss/rib curves in one sketch,
                     pick the pocket regions, cut them, round the corners.

Everything Gusset makes is normal timeline features named "Gusset ...", grouped
into one timeline group, so students can edit the sketch or delete the group.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import adsk.core
import adsk.fusion

from . import feature_builder as fb
from . import lighten_core as lc
from . import log as gslog

_log = gslog.get_logger("lighten_builder")

CM = fb.IN_TO_CM
KG_TO_LB = 2.20462
STROKE_TOL_CM = 0.005


def _safe(getter, default=None):
    try:
        value = getter()
        return default if value is None else value
    except Exception:
        return default


def _to_in(p) -> lc.Pt:
    return (p.x / CM, p.y / CM)


def _pt(x_in: float, y_in: float):
    return adsk.core.Point3D.create(x_in * CM, y_in * CM, 0)


def _strokes(curve_evaluator) -> list:
    ok, p0, p1 = curve_evaluator.getParameterExtents()
    if not ok:
        return []
    ok, pts = curve_evaluator.getStrokes(p0, p1, STROKE_TOL_CM)
    return list(pts) if ok else []


# ---------------------------------------------------------------------------
# Reading the plate
# ---------------------------------------------------------------------------
@dataclass
class PlateInfo:
    plate: lc.Plate
    outer_edges: list = field(default_factory=list)        # BRepEdges of the outside loop
    odd_holes: List[Tuple[int, list]] = field(default_factory=list)  # (hole index, BRepEdges) non-round cutouts
    thickness_in: Optional[float] = None


def read_plate(sketch, native_face) -> PlateInfo:
    """The face's outline and holes, in the sketch's 2D space, in inches."""
    outer: lc.Poly = []
    corners: List[lc.Pt] = []
    outer_edges: list = []
    holes: List[lc.Hole] = []
    odd: List[Tuple[int, list]] = []
    for i in range(native_face.loops.count):
        loop = native_face.loops.item(i)
        pieces = []
        loop_corners: List[lc.Pt] = []
        edges = []
        for k in range(loop.coEdges.count):
            edge = loop.coEdges.item(k).edge
            edges.append(edge)
            pts = [_to_in(sketch.modelToSketchSpace(p)) for p in _strokes(edge.evaluator)]
            if len(pts) >= 2:
                pieces.append(pts)
                loop_corners.append(pts[0])
                if not adsk.core.Line3D.cast(edge.geometry):
                    loop_corners.append(pts[len(pts) // 2])   # arcs: their middle is a good landing spot too
        poly = lc.chain_loop(pieces)
        if len(poly) < 3:
            _log.debug("Skipping a loop with %d points", len(poly))
            continue
        if loop.isOuter:
            outer, corners, outer_edges = poly, loop_corners, edges
            continue
        circle = adsk.core.Circle3D.cast(edges[0].geometry) if len(edges) == 1 else None
        if circle:
            c = sketch.modelToSketchSpace(circle.center)
            holes.append(lc.Hole(poly, (c.x / CM, c.y / CM), circle.radius / CM))
        else:
            odd.append((len(holes), edges))
            holes.append(lc.Hole(poly))
    if not outer:
        raise fb.FeatureError("Couldn't read the outline of that face.")
    thk = fb.wall_thickness_cm(native_face)
    info = PlateInfo(lc.Plate(outer, holes, corners), outer_edges, odd, thk / CM if thk else None)
    _log.debug("Plate: %d outline points, %d corners, %d holes (%d odd-shaped), thickness %s",
               len(outer), len(corners), len(holes), len(odd), info.thickness_in)
    return info


def selected_sketch(entity):
    """A sketch from whatever was clicked: the sketch itself, or one of its curves/points."""
    sketch = adsk.fusion.Sketch.cast(entity)
    if sketch:
        return sketch
    for kind in (adsk.fusion.SketchCurve, adsk.fusion.SketchPoint):
        thing = kind.cast(entity)
        if thing:
            return thing.parentSketch
    return None


def read_sketch_ribs(rib_sketch, plate_sketch, comp) -> Tuple[List[lc.Rib], int, List[List[lc.Pt]]]:
    """
    Rib centerlines from a student's sketch. Lines, circles and arcs are read
    exactly (arcs stay true arcs - that's what keeps curved pocket edges smooth);
    splines and other curves come back as a point list, drawn as one smooth band.
    Construction lines and projected (reference) curves are ignored, like Robot
    Lighten. Returns (ribs, how many curves were used, curvy centerlines).
    """
    native = rib_sketch.nativeObject if _safe(lambda: rib_sketch.assemblyContext) else rib_sketch
    if native.parentComponent != comp:
        raise fb.FeatureError(f"The rib sketch '{native.name}' is in a different component than the plate. "
                              "Make the rib sketch inside the plate's component (Quick Rib does this for you).")

    def to_plate(p) -> lc.Pt:
        return _to_in(plate_sketch.modelToSketchSpace(native.sketchToModelSpace(p)))

    ribs: List[lc.Rib] = []
    curvy: List[List[lc.Pt]] = []
    used = 0
    curves = native.sketchCurves
    for i in range(curves.count):
        curve = curves.item(i)
        if _safe(lambda: curve.isConstruction, False) or _safe(lambda: curve.isReference, False):
            continue
        line = adsk.fusion.SketchLine.cast(curve)
        circle = adsk.fusion.SketchCircle.cast(curve)
        arc = adsk.fusion.SketchArc.cast(curve)
        if line:
            ribs.append(lc.Rib(to_plate(line.startSketchPoint.geometry), to_plate(line.endSketchPoint.geometry)))
        elif circle:
            ribs.append(lc.Rib(center=to_plate(circle.centerSketchPoint.geometry), radius=circle.radius / CM))
        elif arc:
            ev = arc.geometry.evaluator
            ok, t0, t1 = ev.getParameterExtents()
            ok, mid = ev.getPointAtParameter((t0 + t1) / 2)
            rib = lc.arc_through(to_plate(arc.startSketchPoint.geometry), to_plate(mid),
                                 to_plate(arc.endSketchPoint.geometry))
            if rib is not None:
                ribs.append(rib)
        else:
            pts = [to_plate(p) for p in _strokes(curve.geometry.evaluator)]
            if len(pts) >= 2:
                curvy.append(pts)
                ribs.extend(lc.Rib(r.a, r.b, kind="curve") for r in lc.polyline_ribs(pts))
        used += 1
    _log.debug("Rib sketch '%s': %d curves -> %d ribs (%d curvy)", native.name, used, len(ribs), len(curvy))
    return ribs, used, curvy


# ---------------------------------------------------------------------------
# Quick Rib output
# ---------------------------------------------------------------------------
def _arc(sketch, center: lc.Pt, radius_in: float, start: float, sweep: float):
    start_pt = lc.arc_point(center, radius_in, start)
    return sketch.sketchCurves.sketchArcs.addByCenterStartSweep(_pt(*center), _pt(*start_pt), sweep)


def draw_rib_lines(sketch, ribs: Sequence[lc.Rib]) -> int:
    """Quick Rib's result as ordinary sketch curves: lines, circles and arcs."""
    for rib in ribs:
        if rib.center is None:
            sketch.sketchCurves.sketchLines.addByTwoPoints(_pt(*rib.a), _pt(*rib.b))
        elif rib.is_full_circle:
            sketch.sketchCurves.sketchCircles.addByCenterRadius(_pt(*rib.center), rib.radius * CM)
        else:
            _arc(sketch, rib.center, rib.radius, rib.start, rib.sweep)
    return len(ribs)


# ---------------------------------------------------------------------------
# Lighten
# ---------------------------------------------------------------------------
@dataclass
class LightenResult:
    pockets: int = 0
    too_small: int = 0
    too_tight: int = 0
    kept: int = 0
    regions: list = field(default_factory=list)     # (outer, inners, kept?) for every pocket candidate
    before_lb: Optional[float] = None
    removed_lb: Optional[float] = None
    corners_rounded: bool = True

    def lines(self) -> List[str]:
        out = lc.summary(self.pockets, self.too_small, self.too_tight, self.removed_lb, self.before_lb)
        if self.kept:
            out.append(f"{self.kept} pocket(s) kept solid (you clicked them) - click again to cut")
        if not self.corners_rounded:
            out.append("⚠ Fusion couldn't round the inside corners - check them before cutting")
        return out


def _offset(sketch, edges, direction_point, distance_cm: float, what: str):
    """Project face edges into the sketch and offset them (toward direction_point)."""
    curves = adsk.core.ObjectCollection.create()
    for edge in edges:
        projected = sketch.project(edge)
        for k in range(projected.count):
            curves.add(projected.item(k))
    try:
        result = sketch.offset(curves, direction_point, distance_cm)
        if result is None or result.count == 0:
            raise RuntimeError("no curves came back")
        return result
    except Exception as exc:
        _log.debug("Offset of the %s failed: %s", what, exc)
        raise fb.FeatureError(f"Fusion couldn't offset the {what} (it may be too small or oddly shaped for that "
                              "width). Try a smaller width.")


def _profile_shape(profile):
    """(a point inside it, area in², perimeter in, outer outline, inner outlines) for one sketch region."""
    outer: lc.Poly = []
    inners: List[lc.Poly] = []
    for i in range(profile.profileLoops.count):
        loop = profile.profileLoops.item(i)
        pieces = []
        for k in range(loop.profileCurves.count):
            pts = [_to_in(p) for p in _strokes(loop.profileCurves.item(k).geometry.evaluator)]
            if pts:
                pieces.append(pts)
        poly = lc.chain_loop(pieces)
        if loop.isOuter:
            outer = poly
        elif poly:
            inners.append(poly)
    props = profile.areaProperties(adsk.fusion.CalculationAccuracy.LowCalculationAccuracy)
    return lc.interior_point(outer, inners), props.area / (CM * CM), props.perimeter / CM, outer, inners


def _vertical_edges(feature, normal) -> adsk.core.ObjectCollection:
    """The up-and-down edges where a cut's side walls meet: those are the inside corners."""
    edges = adsk.core.ObjectCollection.create()
    seen = set()
    faces = feature.sideFaces
    for i in range(faces.count):
        for k in range(faces.item(i).edges.count):
            edge = faces.item(i).edges.item(k)
            key = _safe(lambda: edge.tempId)
            if key in seen:
                continue
            seen.add(key)
            line = adsk.core.Line3D.cast(edge.geometry)
            if not line:
                continue
            v = line.startPoint.vectorTo(line.endPoint)
            if v.length < 1e-6:
                continue
            v.normalize()
            if abs(v.dotProduct(normal)) < 0.999:
                continue
            # Skip smooth (tangent) joins - there's no corner there to round.
            mid = adsk.core.Point3D.create((line.startPoint.x + line.endPoint.x) / 2,
                                           (line.startPoint.y + line.endPoint.y) / 2,
                                           (line.startPoint.z + line.endPoint.z) / 2)
            normals = []
            for f in range(edge.faces.count):
                ok, n = edge.faces.item(f).evaluator.getNormalAtPoint(mid)
                if ok:
                    normals.append(n)
            if len(normals) == 2 and abs(normals[0].dotProduct(normals[1])) > 0.9995:
                continue
            edges.add(edge)
    return edges


def _fillet(comp, edges, radius_cm: float, name: str):
    """Round the edges. Returns the feature, or None if Fusion couldn't do it."""
    if edges.count == 0:
        return None
    fillets = comp.features.filletFeatures
    feature = None
    try:
        fi = fillets.createInput()
        value = adsk.core.ValueInput.createByReal(radius_cm)
        try:
            fi.edgeSetInputs.addConstantRadiusEdgeSet(edges, value, False)
        except AttributeError:          # older Fusion API
            fi.addConstantRadiusEdgeSet(edges, value, False)
        feature = fillets.add(fi)
        if _safe(lambda: feature.healthState) == adsk.fusion.FeatureHealthStates.ErrorFeatureHealthState:
            raise RuntimeError(_safe(lambda: feature.errorOrWarningMessage, "error"))
        feature.name = name
        return feature
    except Exception as exc:
        _log.debug("Fillet %r (%d edges) failed: %s", name, edges.count, exc)
        if feature is not None:
            try:
                feature.deleteMe()
            except Exception:
                pass
        return None


def _mass_lb(body) -> Optional[float]:
    mass = _safe(lambda: body.physicalProperties.mass)
    return mass * KG_TO_LB if mass else None


def lighten(comp, native_face, sketch, info: PlateInfo, ribs: Sequence[lc.Rib], params: lc.LightenParams,
            name: str = "Gusset lighten", curvy: Sequence[Sequence[lc.Pt]] = (),
            keep_points: Sequence[lc.Pt] = ()) -> LightenResult:
    """
    Draw, pick and cut the pockets, in `sketch` (an empty sketch on the face -
    the same one read_plate() read the plate in, so the coordinates match).
    Raises FeatureError for problems a student can fix; the caller deletes the
    sketch then.
    """
    problems = lc.check_params(params, info.thickness_in)
    if problems:
        raise fb.FeatureError(" ".join(problems))
    body = native_face.body
    result = LightenResult(before_lb=_mass_lb(body))
    ribs = list(ribs) + lc.edge_tabs(info.plate, params)      # join near-edge holes to the wall
    normal = native_face.geometry.normal      # the plate's up direction (only its axis matters)
    plate = info.plate
    timeline_start = _safe(lambda: sketch.timelineObject.index)
    inside_pt = sketch.modelToSketchSpace(native_face.pointOnFace)
    inside_pt.z = 0

    # 1. The outside wall, and a ring around every hole.
    _offset(sketch, info.outer_edges, inside_pt, params.wall_in * CM, "plate's outline")
    for _idx, edges in info.odd_holes:
        _offset(sketch, edges, inside_pt, params.boss_in * CM, "edge of a cutout")
    circles = sketch.sketchCurves.sketchCircles
    for hole in plate.holes:
        if hole.center is not None:
            circles.addByCenterRadius(_pt(*hole.center), (hole.radius + params.boss_in) * CM)

    # 2. Every rib as a strip (deferred compute: much faster with lots of lines).
    #    Straight ribs: a rectangle. Circles: two circles. Arcs: two TRUE arcs plus
    #    end caps. Splines: one smooth band. (Lots of little rectangles along a
    #    curve leave a notch at every joint - that was the jagged-edge bug.)
    lines = sketch.sketchCurves.sketchLines
    half = params.rib_in / 2

    def polygon(poly):
        for k in range(len(poly)):
            lines.addByTwoPoints(_pt(*poly[k]), _pt(*poly[(k + 1) % len(poly)]))

    sketch.isComputeDeferred = True
    try:
        for rib in ribs:
            if rib.kind == "curve":
                continue                      # drawn below as one band per curve
            if rib.center is None:
                polygon(lc.rib_strip(rib, params.rib_in))
            elif rib.is_full_circle:
                circles.addByCenterRadius(_pt(*rib.center), (rib.radius + half) * CM)
                if rib.radius > half:
                    circles.addByCenterRadius(_pt(*rib.center), (rib.radius - half) * CM)
            else:
                outer_r, inner_r = rib.radius + half, max(rib.radius - half, 0.0)
                _arc(sketch, rib.center, outer_r, rib.start, rib.sweep)
                if inner_r > 1e-4:
                    _arc(sketch, rib.center, inner_r, rib.start, rib.sweep)
                for ang in (rib.start, rib.start + rib.sweep):     # square end caps
                    lines.addByTwoPoints(_pt(*lc.arc_point(rib.center, inner_r, ang)),
                                         _pt(*lc.arc_point(rib.center, outer_r, ang)))
        for pts in curvy:
            band = lc.offset_strip(pts, params.rib_in)
            if band:
                polygon(band)
    finally:
        sketch.isComputeDeferred = False

    # 3. Which regions are pockets?
    pockets = []
    for i in range(sketch.profiles.count):
        profile = sketch.profiles.item(i)
        try:
            point, region_area, region_perim, outer_poly, inner_polys = _profile_shape(profile)
        except Exception as exc:
            _log.debug("Couldn't read region %d: %s", i, exc)
            continue
        if point is None or lc.classify(point, plate, ribs, params) != lc.POCKET:
            continue
        if keep_points and any(lc.in_region(k, outer_poly, inner_polys) for k in keep_points):
            result.kept += 1                  # the student clicked this one: leave it solid
            result.regions.append((outer_poly, inner_polys, True))
            continue
        if lc.pocket_too_small(region_area, region_perim, params):
            result.too_small += 1
            continue
        pockets.append(profile)
        result.regions.append((outer_poly, inner_polys, False))
    _log.debug("Sketch has %d regions: %d pockets, %d too small", sketch.profiles.count, len(pockets),
               result.too_small)
    if not pockets:
        raise fb.FeatureError("No room for pockets with these widths. Try thinner walls/ribs, a smaller "
                              "'smallest pocket', or fewer ribs.")

    # 4. Cut them all at once and round the corners. If the rounding fails, redo
    #    pocket by pocket and skip only the ones whose corners are too tight.
    depth_cm = params.depth_in * CM if params.depth_in else None
    radius_cm = params.corner_in * CM
    last_feature = None
    cut = fb.cut(comp, pockets, body, depth_cm, f"{name} pockets")
    fillet = _fillet(comp, _vertical_edges(cut, normal), radius_cm, f"{name} corners")
    if fillet is not None:
        result.pockets, last_feature = len(pockets), fillet
    else:
        _log.info("Rounding all corners at once failed; trying pocket by pocket")
        cut.deleteMe()
        for n, profile in enumerate(pockets, start=1):
            try:
                one = fb.cut(comp, [profile], body, depth_cm, f"{name} pocket {n}")
            except fb.FeatureError as exc:
                _log.debug("Pocket %d didn't cut: %s", n, exc)
                result.too_tight += 1
                continue
            edges = _vertical_edges(one, normal)
            rounded = _fillet(comp, edges, radius_cm, f"{name} pocket {n} corners")
            if rounded is None and edges.count:
                one.deleteMe()
                result.too_tight += 1
                continue
            result.pockets += 1
            last_feature = rounded or one
        if result.pockets == 0:
            raise fb.FeatureError("Fusion couldn't round the pocket corners to the cutter radius. Try wider "
                                  "pockets (thinner ribs, fewer ribs) or a smaller cutter.")

    sketch.isVisible = False
    after = _mass_lb(body)
    if result.before_lb is not None and after is not None:
        result.removed_lb = result.before_lb - after
    _group_timeline(comp, timeline_start, last_feature, name)
    _log.info("Lighten: %d pockets (%d too small, %d too tight), removed %s lb", result.pockets,
              result.too_small, result.too_tight,
              f"{result.removed_lb:.3f}" if result.removed_lb is not None else "?")
    return result


def _group_timeline(comp, start_index, last_feature, name: str) -> None:
    """Tuck the sketch + cuts + fillets into one timeline group."""
    try:
        end_index = last_feature.timelineObject.index
        timeline = comp.parentDesign.timeline
        if start_index is None or end_index <= start_index:
            return
        group = timeline.timelineGroups.add(start_index, end_index)
        group.name = name
    except Exception as exc:
        _log.debug("Couldn't group the timeline (%s) - not a problem", exc)
