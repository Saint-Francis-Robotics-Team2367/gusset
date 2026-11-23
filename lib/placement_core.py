"""
placement_core.py - the math for dropping a round library part (pulley, gear,
bearing) onto a spot without the student clicking anything on the part
(no Fusion imports; tested in tests/test_placement_core.py).

Vendor STEP files point their parts every which way, so Gusset works the part's
axis out from its mass: a round part spins the same about two directions and
differently about its axis, so the axis is the principal direction whose moment
of inertia stands apart from the other two.

    axis_index(moments)                    which principal axis is the spin axis
    seat_along_axis(...)                   where on that axis meets the target, and
                                           which way it should face (flange outward)
    placement_matrix(part_frame, target)   the 4x4 transform for Occurrence.transform2

Vectors are (x, y, z) tuples in cm (Fusion's internal units).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

Vec = Tuple[float, float, float]
CENTER, FLANGE_OUT, FACE_OUT = "center", "flange_out", "face_out"


def dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def scale(a: Vec, k: float) -> Vec:
    return (a[0] * k, a[1] * k, a[2] * k)


def add(a: Vec, b: Vec) -> Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def unit(a: Vec) -> Vec:
    n = math.sqrt(dot(a, a))
    if n < 1e-12:
        raise ValueError("zero-length direction")
    return scale(a, 1.0 / n)


def any_perpendicular(a: Vec) -> Vec:
    a = unit(a)
    helper = (1.0, 0.0, 0.0) if abs(a[0]) < 0.9 else (0.0, 1.0, 0.0)
    return unit(cross(a, helper))


def axis_index(moments: Sequence[float], tolerance: float = 0.08) -> Optional[int]:
    """
    0, 1 or 2: the principal axis that stands apart (the spin axis of a round part),
    or None when the part isn't round enough to tell (all three alike, or all
    different by more than `tolerance` - a motor with a big gearbox on one side).
    """
    m = [abs(float(x)) for x in moments]
    if len(m) != 3 or max(m) <= 0:
        return None
    best, best_gap = None, 0.0
    for i in range(3):
        j, k = [n for n in range(3) if n != i]
        pair = abs(m[j] - m[k]) / max(m[j], m[k], 1e-12)     # the other two should match
        gap = min(abs(m[i] - m[j]), abs(m[i] - m[k])) / max(m)  # and this one should differ
        if pair <= tolerance and gap > best_gap:
            best, best_gap = i, gap
    return best if best_gap > tolerance else None


@dataclass
class Seat:
    position: float       # where along the part's axis (cm, measured from its center of mass) meets the target
    flip: bool            # True = turn the part around (its axis points the other way)
    note: str = ""


def seat_along_axis(mode: str, low: float, high: float, com: float,
                    faces: Sequence[Tuple[float, int]] = (),
                    cylinders: Sequence[Tuple[float, float, float]] = ()) -> Seat:
    """
    Positions are along the part's axis, all measured the same way.
      low/high  the part's ends; com  its center of mass
      faces     (position, +1/-1) for every flat face square to the axis, with which
                way its outside points
    CENTER      the middle of the part sits on the target (pulleys on a sketch).
    FLANGE_OUT  a bearing: flange on the outside, the flange's underside on the target
                (the plate's outer face). The flange end is the end the mass leans
                toward. No flange -> the outer end face is flush with the target.
    Result: Seat(position from com, flip) where flip means the flange is at the low end.
    """
    if high - low < 1e-9:
        return Seat(0.0, False, "the part has no length along its axis")
    if mode == CENTER:
        return Seat((low + high) / 2.0 - com, False)
    side, under = flange_from_cylinders(cylinders, low, high)
    if side:                                         # measured from the round faces (the reliable way)
        return Seat(under - com, side < 0, f"flange found at the {'high' if side > 0 else 'low'} end")
    if cylinders:
        return Seat(high - com, False, "no flange found - lined up flush with the outside face")
    middle = (low + high) / 2.0
    lean = com - middle
    span = high - low
    flange_high = lean >= 0
    if abs(lean) < 0.02 * span:                     # balanced: no flange to speak of
        end = high
        return Seat(end - com, False, "no flange found - lined up flush with the outside face")
    if flange_high:
        # underside of the flange: the inward-facing (-1) flat face nearest the high end, but not the low end
        under = [p for p, n in faces if n < 0 and p > low + 0.05 * span]
        pos = max(under) if under else high
        return Seat(pos - com, False, "" if under else "flange underside not found - used the flange end")
    under = [p for p, n in faces if n > 0 and p < high - 0.05 * span]
    pos = min(under) if under else low
    return Seat(pos - com, True, "" if under else "flange underside not found - used the flange end")


def flange_from_cylinders(cylinders: Sequence[Tuple[float, float, float]], low: float, high: float
                          ) -> Tuple[int, float]:
    """
    Which end the flange is on, from the part's round faces: (+1 high end / -1 low end
    / 0 no flange, position of the flange's underside along the axis).
    cylinders = (radius, from, to) for each round face around the axis.
    The flange is the biggest round face when it's short and sits at one end and is
    clearly bigger than the body (0.12.1: guessing from the mass got it backwards).
    """
    span = high - low
    usable = [c for c in cylinders if c[2] - c[1] > 1e-6]
    if span <= 1e-9 or len(usable) < 2:
        return 0, 0.0
    biggest = max(usable, key=lambda c: c[0])
    body = max((c for c in usable if c is not biggest and c[2] - c[1] > 0.3 * span), key=lambda c: c[0],
               default=None)
    if body is None or biggest[0] < body[0] * 1.03 or biggest[2] - biggest[1] > 0.6 * span:
        return 0, 0.0
    tol = 0.05 * span
    if abs(biggest[2] - high) <= tol:
        return 1, biggest[1]
    if abs(biggest[1] - low) <= tol:
        return -1, biggest[2]
    return 0, 0.0


def placement_matrix(part_center: Vec, part_axis: Vec, part_ref: Vec, seat: Seat,
                     target_point: Vec, target_axis: Vec, target_ref: Optional[Vec] = None) -> List[float]:
    """
    Row-major 4x4 (16 numbers, Matrix3D.setWithArray order) that moves a part so the
    spot `seat.position` along its axis (from part_center) lands on target_point, with
    its axis along target_axis (turned around if seat.flip), and part_ref (any
    direction square to the axis) along target_ref (or any square direction).
    """
    a_p = unit(part_axis)
    r_p = unit(sub(part_ref, scale(a_p, dot(part_ref, a_p))))
    b_p = cross(a_p, r_p)
    a_t = unit(target_axis)
    if seat.flip:
        a_t = scale(a_t, -1.0)
    ref = target_ref if target_ref is not None else any_perpendicular(a_t)
    r_t = unit(sub(ref, scale(a_t, dot(ref, a_t))))
    b_t = cross(a_t, r_t)
    # Rotation R takes the part frame (r_p, b_p, a_p) onto (r_t, b_t, a_t): R = T * P^T
    P = (r_p, b_p, a_p)
    T = (r_t, b_t, a_t)
    R = [[sum(T[k][i] * P[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    anchor = add(part_center, scale(a_p, seat.position))           # the part's spot that meets the target
    moved = tuple(sum(R[i][j] * anchor[j] for j in range(3)) for i in range(3))
    t = sub(target_point, moved)                                      # type: ignore[arg-type]
    return [R[0][0], R[0][1], R[0][2], t[0],
            R[1][0], R[1][1], R[1][2], t[1],
            R[2][0], R[2][1], R[2][2], t[2],
            0.0, 0.0, 0.0, 1.0]


def apply(matrix: Sequence[float], p: Vec) -> Vec:
    m = matrix
    return (m[0] * p[0] + m[1] * p[1] + m[2] * p[2] + m[3],
            m[4] * p[0] + m[5] * p[1] + m[6] * p[2] + m[7],
            m[8] * p[0] + m[9] * p[1] + m[10] * p[2] + m[11])


def rotate_dir(matrix: Sequence[float], d: Vec) -> Vec:
    m = matrix
    return (m[0] * d[0] + m[1] * d[1] + m[2] * d[2],
            m[4] * d[0] + m[5] * d[1] + m[6] * d[2],
            m[8] * d[0] + m[9] * d[1] + m[10] * d[2])


def hole_fits(hole_diameter_cm: float, bearing_od_cm: float, tolerance_cm: float = 0.13) -> bool:
    """Does a bearing (by its OD) go in this hole? (~0.05\" either way covers press/slip fits and 3D prints)"""
    return abs(hole_diameter_cm - bearing_od_cm) <= tolerance_cm


def hex_axis_from_planes(planes: Sequence[Tuple[Vec, Vec]], flats_cm: float, near: Vec,
                         tolerance_cm: float = 0.02) -> Optional[Tuple[Vec, Vec, Vec]]:
    """
    Recognize a hex shaft from its flat faces (0.12.3 - shafts with no Gusset tag).
    planes = (point on face, outward normal) for every flat face of the body.
    A hex has three pairs of opposite faces `flats_cm` apart whose normals are 60
    degrees apart. Returns (point on the axis nearest `near`, axis, a flat's normal)
    or None when the body isn't a hex of that size.
    """
    pairs = []          # (normal, mid-plane offset along that normal)
    for i, (p1, n1) in enumerate(planes):
        for p2, n2 in planes[i + 1:]:
            if dot(unit(n1), unit(n2)) > -0.999:
                continue                                  # not opposite faces
            n = unit(n1)
            gap = dot(sub(p1, p2), n)
            if abs(abs(gap) - flats_cm) <= tolerance_cm:
                mid = (dot(p1, n) + dot(p2, n)) / 2.0
                if not any(abs(abs(dot(n, q)) - 1.0) < 1e-3 for q, _m in pairs):
                    pairs.append((n, mid))
    for a in range(len(pairs)):
        for b in range(a + 1, len(pairs)):
            na, ma = pairs[a]
            nb, mb = pairs[b]
            if abs(abs(dot(na, nb)) - 0.5) > 0.02:        # hex flats are 60 (or 120) degrees apart
                continue
            axis = unit(cross(na, nb))
            # the axis line: on both mid-planes. Solve for the point nearest `near`.
            # point = near + s*na' + t*nb' restricted to the plane square to the axis
            ra, rb = ma - dot(near, na), mb - dot(near, nb)
            d = dot(na, nb)
            det = 1.0 - d * d
            s_ = (ra - rb * d) / det
            t_ = (rb - ra * d) / det
            point = add(near, add(scale(na, s_), scale(nb, t_)))
            return point, axis, na
    return None
