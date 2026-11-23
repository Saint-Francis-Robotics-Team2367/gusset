"""
feature_builder.py - shared Fusion plumbing for the Hole Pattern and Bearing
Pocket tools: find where a face can be edited, draw circles on it, and cut them.

Every cut is a normal Fusion sketch + extrude in the part's timeline, named
"Gusset ...", so students can see it, edit the sketch, or delete it later.
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

import adsk.core
import adsk.fusion

from . import log as gslog

_log = gslog.get_logger("feature_builder")

IN_TO_CM = 2.54


class FeatureError(Exception):
    """A problem the student can fix (shown in the dialog, not as a crash)."""


def _safe(getter, default=None):
    try:
        value = getter()
        return default if value is None else value
    except Exception:
        return default


def editable_face(face):
    """
    The face as it exists inside its own component (Fusion edits geometry there),
    plus that component and the occurrence it was picked through (or None).
    Refuses parts that live in another (linked) file.
    """
    occ = face.assemblyContext
    current = occ
    while current is not None:
        if _safe(lambda c=current: c.isReferencedComponent, False):
            name = current.component.name
            raise FeatureError(f"'{name}' lives in its own file. Open it (right-click > Open) and add the "
                               "feature there - then every assembly that uses it gets the change.")
        current = _safe(lambda c=current: c.assemblyContext)
    native = face.nativeObject if occ is not None else face
    native = adsk.fusion.BRepFace.cast(native) or face
    comp = native.body.parentComponent
    if _safe(lambda: native.geometry.surfaceType) != adsk.core.SurfaceTypes.PlaneSurfaceType:
        raise FeatureError("Pick a flat face.")
    return native, comp, occ


def editable_sketch(sketch):
    """
    The sketch as it exists in its own component, plus the occurrence it was
    picked through (or None). Refuses sketches that live in another (linked) file.
    """
    occ = _safe(lambda: sketch.assemblyContext)
    current = occ
    while current is not None:
        if _safe(lambda c=current: c.isReferencedComponent, False):
            raise FeatureError(f"'{current.component.name}' lives in its own file. Open it (right-click > Open) "
                               "and add the circles there.")
        current = _safe(lambda c=current: c.assemblyContext)
    native = sketch.nativeObject if occ is not None else sketch
    return adsk.fusion.Sketch.cast(native) or sketch, occ


def to_component_space(point, occ):
    """A point picked in the assembly -> the component's own coordinates."""
    if occ is None:
        return point
    matrix = occ.transform2.copy()
    matrix.invert()
    p = point.copy()
    p.transformBy(matrix)
    return p


def new_sketch(comp, native_face, name: str):
    sketch = comp.sketches.addWithoutEdges(native_face)
    sketch.name = name
    return sketch


def face_bounds_in_sketch(sketch, native_face) -> Tuple[float, float, float, float]:
    """Bounding box (cm) of the face's outer edges, in the sketch's 2D space."""
    xs, ys = [], []
    for i in range(native_face.loops.count):
        loop = native_face.loops.item(i)
        if not loop.isOuter:
            continue
        for k in range(loop.edges.count):
            ev = loop.edges.item(k).evaluator
            ok, p0, p1 = ev.getParameterExtents()
            ok, pts = ev.getStrokes(p0, p1, 0.005)
            for p in (pts if ok else []):
                q = sketch.modelToSketchSpace(p)
                xs.append(q.x)
                ys.append(q.y)
    if not xs:
        raise FeatureError("Couldn't read the face's edges.")
    return min(xs), min(ys), max(xs), max(ys)


def inside_face(sketch, native_face, x_cm: float, y_cm: float, radius_cm: float, margin_cm: float = 0.0) -> bool:
    """True if a circle at (x, y) sketch coords sits completely on the face."""
    evaluator = native_face.evaluator
    r = radius_cm + margin_cm
    for angle in [i * math.pi / 4 for i in range(8)] + [None]:
        px = x_cm + (r * math.cos(angle) if angle is not None else 0.0)
        py = y_cm + (r * math.sin(angle) if angle is not None else 0.0)
        model = sketch.sketchToModelSpace(adsk.core.Point3D.create(px, py, 0))
        ok, param = evaluator.getParameterAtPoint(model)
        if not ok or not evaluator.isParameterOnFace(param):
            return False
    return True


def wall_thickness_cm(native_face) -> Optional[float]:
    """
    Distance to the nearest parallel face facing the other way: the wall of a
    box tube, or the plate's thickness. None if there isn't one.
    """
    ok, n = native_face.evaluator.getNormalAtPoint(native_face.pointOnFace)
    if not ok:
        return None
    origin = native_face.pointOnFace
    best = None
    body = native_face.body
    for i in range(body.faces.count):
        f = body.faces.item(i)
        if f == native_face or _safe(lambda f=f: f.geometry.surfaceType) != adsk.core.SurfaceTypes.PlaneSurfaceType:
            continue
        ok, m = f.evaluator.getNormalAtPoint(f.pointOnFace)
        if not ok or m.dotProduct(n) > -0.9999:
            continue                                  # not parallel and facing the other way
        d = -origin.vectorTo(f.pointOnFace).dotProduct(n)   # depth below the picked face
        if d > 1e-4 and (best is None or d < best):
            best = d
    return best


def add_circle(sketch, x_cm: float, y_cm: float, diameter_in: float):
    return sketch.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(x_cm, y_cm, 0), diameter_in * IN_TO_CM / 2)


def cut(comp, profiles: Sequence, body, depth_cm: Optional[float], name: str):
    """
    Extrude-cut the profiles INTO the part. depth_cm=None cuts through all.
    The sketch's direction depends on the face, so if the first direction
    doesn't hit the part we try the other one.
    """
    collection = adsk.core.ObjectCollection.create()
    for p in profiles:
        collection.add(p)
    if collection.count == 0:
        raise FeatureError("Nothing to cut.")
    extrudes = comp.features.extrudeFeatures
    last_error = None

    def extent():
        return (adsk.fusion.ThroughAllExtentDefinition.create() if depth_cm is None else
                adsk.fusion.DistanceExtentDefinition.create(adsk.core.ValueInput.createByReal(depth_cm)))

    # Strategies in order. Testing in a real Fusion document showed a cut can go
    # the wrong way WITHOUT an error (it just removes nothing), so after each try
    # we check that the part actually lost material, and undo it if not.
    strategies = [("into the part", adsk.fusion.ExtentDirections.NegativeExtentDirection),
                  ("other direction", adsk.fusion.ExtentDirections.PositiveExtentDirection)]
    if depth_cm is None:
        strategies.append(("both directions", None))
    for label, direction in strategies:
        volume_before = _safe(lambda: body.volume, 0.0)
        feature = None
        try:
            feature_input = extrudes.createInput(collection, adsk.fusion.FeatureOperations.CutFeatureOperation)
            if direction is None:
                feature_input.setTwoSidesExtent(extent(), extent())
            else:
                feature_input.setOneSideExtent(extent(), direction)
            feature_input.participantBodies = [body]
            feature = extrudes.add(feature_input)
        except Exception as exc:
            last_error = exc
            _log.debug("Cut %r (%s) failed: %s", name, label, exc)
            continue
        removed = volume_before - _safe(lambda: body.volume, volume_before)
        if removed > 1e-9:
            feature.name = name
            _log.debug("Cut %r (%d profile(s), %s, depth %s): removed %.4f cm3", name, collection.count, label,
                       "through" if depth_cm is None else f"{depth_cm / IN_TO_CM:.4f} in", removed)
            return feature
        _log.debug("Cut %r (%s) removed nothing; undoing it and trying another way", name, label)
        try:
            feature.deleteMe()
        except Exception:
            pass
        last_error = "the cut didn't reach the part"
    raise FeatureError(f"Fusion couldn't cut into the part ({last_error}).")


def profile_center(profile) -> Tuple[float, float, float]:
    """(x, y, area) of a sketch profile, in sketch space."""
    props = profile.areaProperties(adsk.fusion.CalculationAccuracy.LowCalculationAccuracy)
    return props.centroid.x, props.centroid.y, props.area
