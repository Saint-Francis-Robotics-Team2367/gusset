"""
parts_builder.py - the Fusion side of Gusset's part generators (Tube, Shaft,
Spacer, Belt/Chain sketch).

Parts are built as exact solids with Fusion's TemporaryBRepManager (boxes,
cylinders and booleans - no fiddly sketch orientation), then added to the
component as ONE "base feature" per run so each run is one timeline item named
after what it made. In a direct-modeling design the bodies are added directly.

All the numbers come from frc_parts_core.py (tested); this file only places them.
"""

from __future__ import annotations

import json
import math
from typing import List, Optional, Sequence, Tuple

import adsk.core
import adsk.fusion

from . import feature_builder as fb
from . import frc_parts_core as pc
from . import log as gslog

_log = gslog.get_logger("parts_builder")

CM = fb.IN_TO_CM
ATTR_GROUP = "Gusset"
SHAFT_ATTR = "shaft"


# ---------------------------------------------------------------------------
# Small vector helpers (Fusion Vector3D/Point3D are clumsy for this)
# ---------------------------------------------------------------------------
def V(x, y, z):
    return adsk.core.Vector3D.create(x, y, z)


def vec(p) -> Tuple[float, float, float]:
    return (p.x, p.y, p.z)


def add(a, b, s=1.0):
    return (a[0] + b[0] * s, a[1] + b[1] * s, a[2] + b[2] * s)


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def unit(a):
    n = math.sqrt(dot(a, a))
    if n < 1e-12:
        raise fb.FeatureError("Two points are in the same place.")
    return (a[0] / n, a[1] / n, a[2] / n)


def rotate(v, axis, angle):
    """Rodrigues rotation of v about a unit axis."""
    c, s = math.cos(angle), math.sin(angle)
    k = axis
    kxv = cross(k, v)
    kdv = dot(k, v)
    return tuple(v[i] * c + kxv[i] * s + k[i] * kdv * (1 - c) for i in range(3))


def P3(t):
    return adsk.core.Point3D.create(*t)


def V3(t):
    return adsk.core.Vector3D.create(*t)


def any_perpendicular(u):
    ref = (0.0, 0.0, 1.0) if abs(u[2]) < 0.9 else (1.0, 0.0, 0.0)
    return unit(cross(u, ref))


# ---------------------------------------------------------------------------
# Solids
# ---------------------------------------------------------------------------
def _tbm():
    return adsk.fusion.TemporaryBRepManager.get()


def _box(center, length_dir, width_dir, length, width, height):
    obb = adsk.core.OrientedBoundingBox3D.create(P3(center), V3(length_dir), V3(width_dir), length, width, height)
    return _tbm().createBox(obb)


def _cyl(a, b, radius):
    return _tbm().createCylinderOrCone(P3(a), radius, P3(b), radius)


def _bool(target, tool, kind) -> None:
    if not _tbm().booleanOperation(target, tool, kind):
        raise fb.FeatureError("Fusion couldn't combine the shapes (boolean failed).")


DIFF = adsk.fusion.BooleanTypes.DifferenceBooleanType
UNION = adsk.fusion.BooleanTypes.UnionBooleanType
INTERSECT = adsk.fusion.BooleanTypes.IntersectionBooleanType


def _union_all(tools):
    """One body from many (fewer, bigger booleans are much faster than many small ones)."""
    tools = list(tools)
    if not tools:
        return None
    acc = tools[0]
    for t in tools[1:]:
        _bool(acc, t, UNION)
    return acc


def hex_prism(start, u, ref, length_cm, flats_cm):
    """A hexagonal prism from `start` along u, one pair of flats facing `ref`."""
    center = add(start, u, length_cm / 2)
    big = flats_cm * 2
    prism = None
    for k in range(3):
        w = rotate(ref, u, k * math.pi / 3)
        slab = _box(center, u, w, length_cm, flats_cm, big)
        if prism is None:
            prism = slab
        else:
            _bool(prism, slab, INTERSECT)
    return prism


def tube_frame(p0, p1, normal, plan: pc.TubePlan, start_ext_in: float, align: str):
    """
    Where a tube goes: (start of its centerline, u along it, w across it, n up).
    u x w = n, so (u, w, n) is the part file's (X, Y, Z) when it's a linked part.
    """
    u = unit(sub(p1, p0))
    n = unit(normal)
    w = unit(cross(n, u))
    start = add(p0, u, -start_ext_in * CM)
    up = plan.up_in * CM
    lift = {"center": 0.0, "bottom": up / 2, "top": -up / 2}[align]
    return add(start, n, lift), u, w, n


def tube_body(p0, p1, normal, plan: pc.TubePlan, start_ext_in: float, align: str):
    """A box tube from p0 to p1 (component space, cm). align: center / bottom / top on the sketch plane."""
    axis0, u, w, n = tube_frame(p0, p1, normal, plan, start_ext_in, align)
    L, across, up, t = plan.length_in * CM, plan.across_in * CM, plan.up_in * CM, plan.wall_in * CM
    center = add(axis0, u, L / 2)
    body = _box(center, u, w, L, across, up)
    _bool(body, _box(center, u, w, L + 0.5, across - 2 * t, up - 2 * t), DIFF)
    if plan.hole_d_in:
        r = plan.hole_d_in * CM / 2
        holes = []
        for x in plan.holes_along:
            at = add(axis0, u, x * CM)
            for off in plan.rows_up_faces:                       # through top and bottom
                c = add(at, w, off * CM)
                holes.append(_cyl(add(c, n, -up), add(c, n, up), r))
            for off in plan.rows_side_faces:                     # through both sides
                c = add(at, n, off * CM)
                holes.append(_cyl(add(c, w, -across), add(c, w, across), r))
        tool = _union_all(holes)
        if tool is not None:
            _bool(body, tool, DIFF)
    return body


def shaft_body(a, b, plan: pc.ShaftPlan, ref, rotation_deg: float):
    """1/2" hex shaft from a to b (cm), extended past each end."""
    u = unit(sub(b, a))
    start = add(a, u, -plan.start_ext_in * CM)
    flats_dir = rotate(ref, u, math.radians(rotation_deg))
    L = plan.length_in * CM
    body = hex_prism(start, u, flats_dir, L, pc.HEX_FLATS_IN * CM)
    if plan.tapped:
        r, depth = plan.tap_d_in * CM / 2, pc.TAP_DEPTH_IN * CM
        end = add(start, u, L)
        _bool(body, _cyl(add(start, u, -0.1), add(start, u, depth), r), DIFF)
        _bool(body, _cyl(add(end, u, 0.1), add(end, u, -depth), r), DIFF)
    turn_rings(body, start, u, plan)
    return body, start, u, flats_dir


RING_OUTER_IN = 0.35      # radius of the "tool" that turns the hex down (past its 0.289" corners)


def turn_rings(body, start, u, plan: pc.ShaftPlan) -> None:
    """Round journals and snap-ring grooves: cut a ring (outside the diameter left) from the hex."""
    L = plan.length_in * CM
    for z0, z1, d in plan.ring_cuts():
        a = z0 * CM - (0.02 if z0 <= 1e-9 else 0.0)              # run past the end so no sliver is left
        b = z1 * CM + (0.02 if abs(z1 * CM - L) < 1e-6 else 0.0)
        ring = _cyl(add(start, u, a), add(start, u, b), RING_OUTER_IN * CM)
        _bool(ring, _cyl(add(start, u, a - 0.01), add(start, u, b + 0.01), d * CM / 2), DIFF)
        _bool(body, ring, DIFF)
    if plan.ring_cuts():
        _log.debug("Turned %d section(s) on %s", len(plan.ring_cuts()), plan.name)


def spacer_body(a, u, plan: pc.SpacerPlan, flats_dir, end_gap_in: float):
    start = add(a, u, end_gap_in * CM)
    L = plan.length_in * CM
    body = _cyl(start, add(start, u, L), plan.od_in * CM / 2)
    bore = hex_prism(add(start, u, -0.1), u, flats_dir, L + 0.2, plan.bore_flats_in * CM)
    _bool(body, bore, DIFF)
    return body


# ---------------------------------------------------------------------------
# Putting bodies into the design
# ---------------------------------------------------------------------------
def add_bodies(comp, bodies: Sequence[Tuple[object, str]], feature_name: str, material: Optional[str] = None):
    """Add temporary bodies as one timeline item. Returns the real BRepBodies."""
    design = comp.parentDesign
    parametric = design.designType == adsk.fusion.DesignTypes.ParametricDesignType
    base = None
    made = []
    if parametric:
        base = comp.features.baseFeatures.add()
        base.startEdit()
    try:
        for temp, name in bodies:
            body = comp.bRepBodies.add(temp, base) if base else comp.bRepBodies.add(temp)
            body.name = name
            made.append(body)
    finally:
        if base:
            base.finishEdit()
    if base:
        try:
            base.name = feature_name
        except Exception:
            pass
        # finishEdit can hand back new body objects: re-read them by name/order
        made = [base.bodies.item(i) for i in range(base.bodies.count)] or made
        for body, (_temp, name) in zip(made, bodies):
            try:
                body.name = name
            except Exception:
                pass
    if material:
        mat = find_material(material, design)
        for body in made:
            if mat:
                try:
                    body.material = mat
                except Exception as exc:
                    _log.debug("Couldn't set material on %s: %s", body.name, exc)
    _log.info("%s: added %d body(ies)", feature_name, len(made))
    return made


# 3D-printing plastics Fusion's library doesn't have: made in the design by copying
# a library plastic and setting the right density (kg/m^3), so BOM masses are real.
CUSTOM_MATERIALS = {"PLA": ("ABS Plastic", 1240.0), "PETG": ("ABS Plastic", 1270.0)}


def find_material(name: str, design=None):
    """A Fusion material by name: the library, or (PLA/PETG) a copy made in `design`."""
    app = adsk.core.Application.get()
    if name in CUSTOM_MATERIALS and design is not None:
        existing = design.materials.itemByName(name)
        if existing:
            return existing
        base_name, density = CUSTOM_MATERIALS[name]
        base = find_material(base_name)
        if base is None:
            return None
        try:
            mat = design.materials.addByCopy(base, name)
            prop = adsk.core.FloatProperty.cast(mat.materialProperties.itemByName("Density"))
            if prop:
                prop.value = density
            _log.info("Made material %s (%.0f kg/m3) in this design", name, density)
            return mat
        except Exception as exc:
            _log.debug("Couldn't make material %s: %s", name, exc)
            return None
    for lib_name in ("Fusion Material Library", "Fusion 360 Material Library"):
        lib = app.materialLibraries.itemByName(lib_name)
        if lib:
            mat = lib.materials.itemByName(name)
            if mat:
                return mat
    _log.debug("Material %r not found", name)
    return None


def tag_shaft(body, start, u, flats_dir, length_cm) -> None:
    """Remember the shaft's axis so the Spacer tool can line its hex bore up with it."""
    data = {"start": list(start), "u": list(u), "flats": list(flats_dir), "length": length_cm}
    body.attributes.add(ATTR_GROUP, SHAFT_ATTR, json.dumps(data))


def read_shaft(body) -> Optional[dict]:
    attr = body.attributes.itemByName(ATTR_GROUP, SHAFT_ATTR)
    if not attr:
        return None
    try:
        return json.loads(attr.value)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Belt / chain sketch
# ---------------------------------------------------------------------------
def draw_drive(sketch, p1, direction, center_in: float, d1_in: float, d2_in: float, label: str):
    """
    Second pulley center at exactly center_in from p1 (sketch space, cm) along
    `direction`, pitch circles, the belt's straight runs (all construction), and
    a dimension on the center distance. Returns the two center SketchPoints.
    """
    d = (direction[0], direction[1])
    L = math.hypot(*d)
    if L < 1e-9:
        raise fb.FeatureError("Pick a direction that isn't the same spot as the first center.")
    d = (d[0] / L, d[1] / L)
    e = (-d[1], d[0])
    C = center_in * CM
    p2 = (p1[0] + d[0] * C, p1[1] + d[1] * C)
    r1, r2 = d1_in * CM / 2, d2_in * CM / 2
    curves = sketch.sketchCurves
    pts = sketch.sketchPoints
    a = pts.add(P3((p1[0], p1[1], 0)))
    b = pts.add(P3((p2[0], p2[1], 0)))
    line = curves.sketchLines.addByTwoPoints(a, b)
    line.isConstruction = True
    for p, r in ((a, r1), (b, r2)):
        circle = curves.sketchCircles.addByCenterRadius(p, r)
        circle.isConstruction = True
    sin_b = (r2 - r1) / C
    if abs(sin_b) < 1:
        cos_b = math.sqrt(1 - sin_b * sin_b)
        for side in (1, -1):
            m = (-d[0] * sin_b + e[0] * cos_b * side, -d[1] * sin_b + e[1] * cos_b * side)
            t1 = (p1[0] + r1 * m[0], p1[1] + r1 * m[1], 0)
            t2 = (p2[0] + r2 * m[0], p2[1] + r2 * m[1], 0)
            run = curves.sketchLines.addByTwoPoints(P3(t1), P3(t2))
            run.isConstruction = True
    try:
        mid = P3(((p1[0] + p2[0]) / 2 + e[0] * (r1 + r2 + 0.5), (p1[1] + p2[1]) / 2 + e[1] * (r1 + r2 + 0.5), 0))
        dim = sketch.sketchDimensions.addDistanceDimension(
            a, b, adsk.fusion.DimensionOrientations.AlignedDimensionOrientation, mid)
        dim.parameter.expression = f"{center_in:.4f} in"
        try:
            dim.parameter.comment = label
        except Exception:
            pass
    except Exception as exc:
        _log.debug("Couldn't add the center-distance dimension: %s", exc)
    return a, b


def sketch_point_2d(sketch, entity) -> Optional[Tuple[float, float]]:
    """A picked point/line end, in this sketch's 2D space (cm)."""
    sp = adsk.fusion.SketchPoint.cast(entity)
    if sp:
        if sp.parentSketch == sketch:
            return (sp.geometry.x, sp.geometry.y)
        p = sketch.modelToSketchSpace(sp.worldGeometry)
        return (p.x, p.y)
    return None


def selected_points_text(points: List[Tuple[float, float]]) -> str:
    return ", ".join(f"({x / CM:.3f}, {y / CM:.3f})" for x, y in points)
