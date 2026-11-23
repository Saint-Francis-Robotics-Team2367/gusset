"""
fab_geometry.py - reads part geometry from Fusion for fabrication export.

  face_profile(face)     a planar face -> 2D loops (outline + holes) in mm
  flat_profile(body)     a plate -> its outline, through-holes, pockets, thickness
  lathe_profile(body)    a turned part -> diameters, bores, hex flats, length
  export_3mf(body, path) a part -> 3MF for Bambu Studio / OrcaSlicer

Fusion works in CENTIMETERS internally; everything here comes out in mm.
Nothing in the design is changed (no sketches are created), so these are safe
to run anywhere, including on linked parts.
"""

from __future__ import annotations

import math
import time
from typing import Dict, List, Optional, Sequence, Tuple

import adsk.core
import adsk.fusion

from . import flat_export as fe
from . import lathe_sheet as ls
from . import log as gslog

_log = gslog.get_logger("fab_geometry")

CM_TO_MM = 10.0
STROKE_TOL_CM = 0.0025         # 0.025 mm chord tolerance for curves we can't keep exact
PARALLEL_TOL = 1e-4            # |cross| or |dot| below this counts as parallel/perpendicular
LEVEL_TOL_MM = 0.02

Vec = Tuple[float, float, float]


# ---------------------------------------------------------------------------
# Small vector helpers (plain tuples, so they're easy to reason about)
# ---------------------------------------------------------------------------
def _v(p) -> Vec:
    return (p.x, p.y, p.z)


def _sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a: Vec) -> Vec:
    length = math.sqrt(_dot(a, a)) or 1.0
    return (a[0] / length, a[1] / length, a[2] / length)


def _safe(getter, default=None):
    try:
        value = getter()
        return default if value is None else value
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Faces and edges
# ---------------------------------------------------------------------------
def face_normal(face) -> Optional[Vec]:
    """Outward normal of a face (the evaluator accounts for reversed faces)."""
    ok, normal = face.evaluator.getNormalAtPoint(face.pointOnFace)
    return _norm(_v(normal)) if ok else None


def is_planar(face) -> bool:
    return _safe(lambda: face.geometry.surfaceType) == adsk.core.SurfaceTypes.PlaneSurfaceType


class Frame:
    """2D coordinates on a plane: origin + u/v axes, viewed from `normal`."""

    def __init__(self, origin: Vec, normal: Vec, u_hint: Optional[Vec] = None) -> None:
        self.origin, self.normal = origin, _norm(normal)
        u = u_hint or ((1.0, 0.0, 0.0) if abs(self.normal[0]) < 0.9 else (0.0, 1.0, 0.0))
        u = _sub(u, tuple(self.normal[i] * _dot(u, self.normal) for i in range(3)))  # make it lie in the plane
        self.u = _norm(u)
        self.v = _norm(_cross(self.normal, self.u))

    def to2d(self, p: Vec) -> Tuple[float, float]:
        d = _sub(p, self.origin)
        return (_dot(d, self.u) * CM_TO_MM, _dot(d, self.v) * CM_TO_MM)

    def height(self, p: Vec) -> float:
        """Distance (mm) of a point above the plane, along the normal."""
        return _dot(_sub(p, self.origin), self.normal) * CM_TO_MM


def _edge_segment(edge, frame: Frame) -> tuple:
    """One edge -> one flat_export segment, keeping lines/arcs/circles exact."""
    geom = edge.geometry
    ev = edge.evaluator
    ok, p0, p1 = ev.getParameterExtents()
    if adsk.core.Circle3D.cast(geom):
        circle = adsk.core.Circle3D.cast(geom)
        return ("circle", frame.to2d(_v(circle.center)), circle.radius * CM_TO_MM)
    if adsk.core.Line3D.cast(geom):
        _, a = ev.getPointAtParameter(p0)
        _, b = ev.getPointAtParameter(p1)
        return ("line", frame.to2d(_v(a)), frame.to2d(_v(b)))
    if adsk.core.Arc3D.cast(geom):
        _, a = ev.getPointAtParameter(p0)
        _, m = ev.getPointAtParameter((p0 + p1) / 2)
        _, b = ev.getPointAtParameter(p1)
        return ("arc", frame.to2d(_v(a)), frame.to2d(_v(m)), frame.to2d(_v(b)))
    ok, pts = ev.getStrokes(p0, p1, STROKE_TOL_CM)
    return ("poly", [frame.to2d(_v(p)) for p in pts]) if ok else ("poly", [])


def loop_segments(loop, frame: Frame) -> List[tuple]:
    segs = []
    for i in range(loop.edges.count):
        try:
            segs.append(_edge_segment(loop.edges.item(i), frame))
        except Exception as exc:
            _log.warning("Skipped an edge we couldn't read (%s)", exc)
    return segs


def _frame_for_face(face, view_normal: Optional[Vec] = None) -> Frame:
    plane = adsk.core.Plane.cast(face.geometry)
    normal = view_normal or face_normal(face) or _v(plane.normal)
    return Frame(_v(plane.origin), normal, _v(plane.uDirection))


def face_profile(face, name: str = "") -> fe.FlatProfile:
    """Quick export: the clicked face's outline and holes, as seen from outside."""
    if not is_planar(face):
        raise ValueError("That face isn't flat. Pick a flat face of the part.")
    frame = _frame_for_face(face)
    prof = fe.FlatProfile(name=name)
    for i in range(face.loops.count):
        loop = face.loops.item(i)
        kind = fe.KIND_OUTER if loop.isOuter else fe.KIND_HOLE
        prof.loops.append(fe.Loop(loop_segments(loop, frame), kind))
    thickness, _pockets, warnings = _plate_levels(face.body, face, frame)
    prof.thickness_mm = thickness
    prof.warnings += warnings
    _log.info("Face profile %r: %d loops, thickness %s", name, len(prof.loops),
              f"{thickness:.2f} mm" if thickness else "?")
    return prof


# ---------------------------------------------------------------------------
# Plates (X-Carve / laser)
# ---------------------------------------------------------------------------
def _plate_levels(body, main_face, frame: Frame):
    """
    Look at every planar face parallel to `main_face`.
    Returns (thickness_mm, [(face, depth_mm, from_main_side)], warnings).
    """
    warnings: List[str] = []
    parallel = []
    odd_faces = 0
    for i in range(body.faces.count):
        f = body.faces.item(i)
        if is_planar(f):
            n = face_normal(f)
            if n is None:
                continue
            d = _dot(n, frame.normal)
            if abs(abs(d) - 1) < PARALLEL_TOL:
                h = frame.height(_v(f.pointOnFace))
                parallel.append((f, h, d > 0))
            elif abs(d) > PARALLEL_TOL:
                odd_faces += 1            # sloped flat face (chamfer)
        else:
            stype = _safe(lambda f=f: f.geometry.surfaceType)
            if stype == adsk.core.SurfaceTypes.CylinderSurfaceType:
                axis = _norm(_v(adsk.core.Cylinder.cast(f.geometry).axis))
                if abs(abs(_dot(axis, frame.normal)) - 1) > PARALLEL_TOL:
                    odd_faces += 1        # a round edge (fillet) along the plate
            else:
                odd_faces += 1            # cones (countersinks), tori, splines...
    if not parallel:
        return None, [], ["couldn't find the plate's faces"]
    heights = [h for _f, h, _s in parallel]
    # The main face sits at height 0 and its normal points OUT of the part, so
    # the rest of the plate is below it (negative heights).
    thickness = abs(min(heights)) if min(heights) < -LEVEL_TOL_MM else None
    pockets = []
    for f, h, same_dir in parallel:
        if f == main_face or abs(h) < LEVEL_TOL_MM or thickness is None or abs(abs(h) - thickness) < LEVEL_TOL_MM:
            continue
        depth = abs(h) if same_dir else thickness - abs(h)
        pockets.append((f, depth, same_dir))   # same_dir: floor faces the main side -> cut from main side
    if odd_faces:
        warnings.append(f"{odd_faces} face(s) aren't straight up-and-down (chamfers, fillets or countersinks) - "
                        "the file shows the outline only")
    return thickness, pockets, warnings


def _largest_planar_face(body):
    best, best_area = None, -1.0
    for i in range(body.faces.count):
        f = body.faces.item(i)
        if is_planar(f):
            area = _safe(lambda f=f: f.area, 0.0)
            if area > best_area:
                best, best_area = f, area
    return best


def _loop_box(segs: List[tuple]) -> Tuple[float, float, float, float]:
    return fe.bounds(fe.FlatProfile("", [fe.Loop(segs)]))


def _same_box(a, b, tol: float = 0.05) -> bool:
    return all(abs(x - y) < tol for x, y in zip(a, b))


def flat_profile(body, name: str = "") -> fe.FlatProfile:
    """
    Bulk export of a plate. The outline comes from the plate's biggest flat face
    (pockets make the top smaller, so the biggest face is usually the solid back).
    Pockets cut from the OTHER side are what an X-Carve operator sees from the top,
    so the profile is viewed from that side when it has pockets.
    """
    main = _largest_planar_face(body)
    if main is None:
        raise ValueError("no flat face - this doesn't look like a plate")
    frame = _frame_for_face(main)
    thickness, pockets, warnings = _plate_levels(body, main, frame)
    from_back = [p for p in pockets if not p[2]]
    from_main = [p for p in pockets if p[2]]
    if from_back and not from_main:
        # Look at the part from the pocketed side (mirror image of the back).
        frame = Frame(_sub(frame.origin, tuple(frame.normal[i] * (thickness or 0) / CM_TO_MM for i in range(3))),
                      tuple(-c for c in frame.normal), frame.u)
    prof = fe.FlatProfile(name=name, thickness_mm=thickness, warnings=list(warnings))

    pocket_boxes = []
    for f, depth, _side in pockets:
        for i in range(f.loops.count):
            loop = f.loops.item(i)
            if loop.isOuter:
                segs = loop_segments(loop, frame)
                pocket_boxes.append(_loop_box(segs))
                prof.loops.append(fe.Loop(segs, fe.KIND_POCKET, depth))
    for i in range(main.loops.count):
        loop = main.loops.item(i)
        segs = loop_segments(loop, frame)
        if loop.isOuter:
            prof.loops.insert(0, fe.Loop(segs, fe.KIND_OUTER))
        elif any(_same_box(_loop_box(segs), box) for box in pocket_boxes):
            continue        # the opening of a pocket, not a through-hole
        else:
            prof.loops.append(fe.Loop(segs, fe.KIND_HOLE))
    if from_back and from_main:
        prof.warnings.append("pockets on BOTH sides - you'll need to flip the plate")
    _log.info("Flat %r: thickness %s, %d loops (%d pockets)", name,
              f"{thickness:.2f} mm" if thickness else "?", len(prof.loops), len(pockets))
    return prof


# ---------------------------------------------------------------------------
# Lathe parts
# ---------------------------------------------------------------------------
def _face_axial_range(face, axis_origin: Vec, axis: Vec) -> Tuple[float, float]:
    """Min/max position (mm) of a face along the axis, from its edges."""
    values = []
    for i in range(face.edges.count):
        ev = face.edges.item(i).evaluator
        ok, p0, p1 = ev.getParameterExtents()
        ok, pts = ev.getStrokes(p0, p1, STROKE_TOL_CM * 4)
        for p in (pts if ok else []):
            values.append(_dot(_sub(_v(p), axis_origin), axis) * CM_TO_MM)
    return (min(values), max(values)) if values else (0.0, 0.0)


def _pick_axis(body) -> Optional[Tuple[Vec, Vec]]:
    """The turning axis: the cylinder axis with the most surface area."""
    votes: Dict[Tuple[int, int, int], List] = {}
    for i in range(body.faces.count):
        f = body.faces.item(i)
        cyl = adsk.core.Cylinder.cast(_safe(lambda f=f: f.geometry))
        if not cyl or _safe(lambda f=f: f.geometry.surfaceType) != adsk.core.SurfaceTypes.CylinderSurfaceType:
            continue
        axis = _norm(_v(cyl.axis))
        if axis[0] < 0 or (axis[0] == 0 and (axis[1] < 0 or (axis[1] == 0 and axis[2] < 0))):
            axis = tuple(-c for c in axis)
        key = tuple(int(round(c * 1000)) for c in axis)
        votes.setdefault(key, [axis, _v(cyl.origin), 0.0])[2] += _safe(lambda f=f: f.area, 0.0)
    if not votes:
        return None
    axis, origin, _area = max(votes.values(), key=lambda v: v[2])
    return axis, origin


def lathe_profile(body, name: str = "", **info) -> ls.LatheProfile:
    picked = _pick_axis(body)
    if picked is None:
        raise ValueError("no round faces - this doesn't look like a lathe part")
    axis, origin = picked
    cylinders: List[ls.RawCylinder] = []
    flats: List[ls.RawFlat] = []
    all_z: List[float] = []
    for i in range(body.faces.count):
        f = body.faces.item(i)
        stype = _safe(lambda f=f: f.geometry.surfaceType)
        z0, z1 = _face_axial_range(f, origin, axis)
        all_z += [z0, z1]
        if stype == adsk.core.SurfaceTypes.CylinderSurfaceType:
            cyl = adsk.core.Cylinder.cast(f.geometry)
            c_axis = _norm(_v(cyl.axis))
            if abs(abs(_dot(c_axis, axis)) - 1) > PARALLEL_TOL:
                continue                                    # cross hole
            offset = _sub(_v(cyl.origin), origin)
            off_axis = _sub(offset, tuple(axis[k] * _dot(offset, axis) for k in range(3)))
            if math.sqrt(_dot(off_axis, off_axis)) * CM_TO_MM > 0.05:
                continue                                    # not on the axis (e.g. a bolt circle)
            p = _v(f.pointOnFace)
            radial = _sub(_sub(p, origin), tuple(axis[k] * _dot(_sub(p, origin), axis) for k in range(3)))
            n = face_normal(f)
            outer = n is not None and _dot(n, radial) > 0
            cylinders.append(ls.RawCylinder(cyl.radius * CM_TO_MM, z0, z1, outer))
        elif stype == adsk.core.SurfaceTypes.PlaneSurfaceType:
            n = face_normal(f)
            if n is not None and abs(_dot(n, axis)) < PARALLEL_TOL:
                plane_pt = _v(f.pointOnFace)
                distance = abs(_dot(_sub(plane_pt, origin), n)) * CM_TO_MM
                flats.append(ls.RawFlat(distance, z0, z1))
    zmin = min(all_z) if all_z else 0.0
    length = (max(all_z) - zmin) if all_z else 0.0
    for c in cylinders:
        c.z0, c.z1 = c.z0 - zmin, c.z1 - zmin
    for fl in flats:
        fl.z0, fl.z1 = fl.z0 - zmin, fl.z1 - zmin
    return ls.analyze(name, length, cylinders, flats, **info)


# ---------------------------------------------------------------------------
# Bodies and 3D printing
# ---------------------------------------------------------------------------
def main_body(comp) -> Tuple[Optional[object], List[str]]:
    """The component's biggest solid body, plus a warning if there are others."""
    bodies = [comp.bRepBodies.item(i) for i in range(_safe(lambda: comp.bRepBodies.count, 0))]
    solids = [b for b in bodies if _safe(lambda b=b: b.isSolid, True)]
    if not solids:
        return None, ["no solid body"]
    best = max(solids, key=lambda b: _safe(lambda b=b: b.volume, 0.0))
    warnings = [f"{len(solids)} bodies - exported the biggest one"] if len(solids) > 1 else []
    return best, warnings


def export_3mf(design, body, path: str) -> str:
    """3MF for Bambu Studio / OrcaSlicer (both open 3MF directly)."""
    manager = design.exportManager
    options = manager.createC3MFExportOptions(body, path)
    try:
        options.meshRefinement = adsk.fusion.MeshRefinementSettings.MeshRefinementMedium
    except Exception:
        pass
    started = time.time()
    if not manager.execute(options):
        raise RuntimeError("Fusion's 3MF export failed")
    _log.info("Wrote %s (%.1fs)", path, time.time() - started)
    return path
