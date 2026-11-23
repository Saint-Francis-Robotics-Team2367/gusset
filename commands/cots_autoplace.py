"""
cots_autoplace - puts FRC_COTS library parts in place without the student
clicking on the part (0.12). Used by Belt & Chain (a pulley on each center) and
Shaft & Spacer (a bearing in each end hole).

Like linked_parts: inserting copies files in the cloud, which Fusion doesn't
allow while a command dialog is open, so tools call queue(...) from their OK
handler and the parts go in right after the dialog closes.

For each part:
  1. insert it from the library (cots_library.insert - linked through this
     project's COTS folder, exactly like clicking its tile)
  2. find its spin axis from its mass (lib/placement_core.axis_index), its ends,
     and - for bearings - which end the flange is on
  3. move it so it sits on the spot (pulley: centered on the sketch plane;
     bearing: flange outside, flange underside on the plate's outer face)
  4. pin it with a rigid as-built joint to what it sits on (or ground it)
Every step is logged; a part that can't be placed is left at the origin and
named in the summary.

Not a button - only registers its event (start/stop like the other tools).
"""

from __future__ import annotations

import math
import threading
import time
from typing import List, Optional, Tuple

import adsk.core
import adsk.fusion

from .. import config
from ..lib import cots_library as cl
from ..lib import settings
from ..lib import feature_builder as fb
from ..lib import fusion_helpers as fh
from ..lib import log as gslog
from ..lib import placement_core as pl
from . import cots_browser as cb

EVENT_ID = "Gusset_CotsAutoPlace"
TITLE = "Gusset - Library parts"

_log = gslog.get_logger("cots_autoplace")
_event = None
_pending: List[dict] = []
_running = False
_nudger: Optional[threading.Thread] = None
NUDGE_TRIES = 60


def start() -> None:
    global _event
    app, _ = fh.app_ui()
    try:
        app.unregisterCustomEvent(EVENT_ID)       # left over from a reload
    except Exception:
        pass
    _event = app.registerCustomEvent(EVENT_ID)
    _event.add(fh.make_handler(adsk.core.CustomEventHandler, _on_event, "Library parts: place"))


def stop() -> None:
    global _event
    try:
        fh.app_ui()[0].unregisterCustomEvent(EVENT_ID)
    except Exception:
        pass
    _event = None
    _pending.clear()


def request(item, point, axis, mode: str, anchor=None, label: str = "") -> dict:
    """
    One part to place. point / axis: Point3D / Vector3D (or tuples) in the TOP
    assembly's coordinates (cm). anchor: the occurrence it sits on (None = the top).
    """
    as_tuple = lambda v: (v.x, v.y, v.z) if hasattr(v, "x") else tuple(v)   # noqa: E731
    return {"file_id": item.file_id, "category": item.category, "vendor": item.vendor,
            "file_name": item.file_name, "title": item.title, "point": as_tuple(point),
            "axis": pl.unit(as_tuple(axis)), "mode": mode, "label": label or item.title,
            "anchor": fh.safe(lambda: anchor.entityToken, "") if anchor is not None else ""}


def queue(requests: List[dict], what: str) -> None:
    """
    Hand parts to the after-dialog step. Never places them right here: in 0.12.0
    fireCustomEvent returned False inside a command, the parts were placed while
    the dialog was still open, and Fusion didn't keep their turned positions (both
    bearings faced the same way). Now the event is re-fired from a timer until
    Fusion is idle (no command running, no part files being made).
    """
    if not requests:
        return
    app = fh.app_ui()[0]
    doc = fh.safe(lambda: app.activeDocument)
    _pending.append({"requests": requests, "what": what, "doc": doc, "doc_name": fh.safe(lambda: doc.name, "")})
    ok = app.fireCustomEvent(EVENT_ID, "")
    _log.info("Queued %d library part(s) for %s (event fired: %s)", len(requests), what, ok)
    _start_nudger()


def _start_nudger() -> None:
    """Re-fire the event every second until the queue is empty (fired events can be dropped or come early)."""
    global _nudger
    if _nudger is not None and _nudger.is_alive():
        return

    def nudge():
        app = adsk.core.Application.get()
        for _ in range(NUDGE_TRIES):
            time.sleep(1.0)
            if not _pending:
                return
            try:
                app.fireCustomEvent(EVENT_ID, "")
            except Exception:
                return
        _log.warning("Library parts still waiting after %ds - giving up", NUDGE_TRIES)

    _nudger = threading.Thread(target=nudge, daemon=True)
    _nudger.start()


def _not_ready() -> str:
    """Why we can't place parts right now ('' = go)."""
    from . import linked_parts
    if linked_parts.busy:
        return "part files are being made"
    ui = fh.app_ui()[1]
    active = fh.safe(lambda: ui.activeCommand, "SelectCommand")
    if active and active != "SelectCommand":
        return f"a command is still open ({active})"
    return ""


# ---------------------------------------------------------------------------
def _on_event(_args) -> None:
    global _running
    if not _pending or _running:
        return
    why = _not_ready()
    if why:
        _log.debug("Library parts waiting: %s", why)
        return                                         # the nudger fires again in a second
    _running = True
    try:
        while _pending:
            _run_job(_pending.pop(0))
    finally:
        _running = False


def _run_job(job: dict) -> None:
    app, ui = fh.app_ui()
    doc = job.get("doc")
    if doc is not None and fh.safe(lambda: app.activeDocument.name, "") != job.get("doc_name"):
        _log.info("Switching back to %s to place the library parts", job.get("doc_name"))
        if fh.safe(lambda: doc.activate(), False) is False:
            ui.messageBox(f"{job['what']}: the design '{job.get('doc_name')}' isn't open anymore, so the library "
                          "parts weren't added.", TITLE)
            return
    done, problems = [], []
    started = time.time()
    for req in job["requests"]:
        try:
            note = _place_one(req)
            done.append(f"{req['label']}{' - ' + note if note else ''}")
        except fb.FeatureError as exc:
            problems.append(f"{req['label']}: {exc}")
        except Exception as exc:
            _log.exception("Placing %s failed", req.get("title"))
            problems.append(f"{req['label']}: {exc}")
    _log.info("%s: placed %d, %d problem(s) (%.1fs)", job["what"], len(done), len(problems), time.time() - started)
    if problems:
        ui.messageBox(f"{job['what']}: placed {len(done)} library part(s).\n\nCouldn't place:\n- " +
                      "\n- ".join(problems) + "\n\nInsert those from the COTS panel instead.", TITLE)


def _active():
    design = fh.active_design()
    if design is None:
        raise fb.FeatureError("No design is open.")
    return design


def _to_active_space(design, p, d):
    """Top-assembly point/direction -> the active component's own coordinates."""
    occ = design.activeOccurrence
    point = adsk.core.Point3D.create(*p)
    direction = adsk.core.Vector3D.create(*d)
    if occ is not None:
        m = occ.transform2.copy()
        m.invert()
        point.transformBy(m)
        direction.transformBy(m)
    return (point.x, point.y, point.z), pl.unit((direction.x, direction.y, direction.z))


def _bodies(comp):
    """Every body of a part, as seen from the part's own coordinates (STEP files often nest them)."""
    out = [comp.bRepBodies.item(i) for i in range(comp.bRepBodies.count)]
    occs = comp.allOccurrences
    for i in range(occs.count):
        o = occs.item(i)
        out += [o.bRepBodies.item(k) for k in range(o.bRepBodies.count)]
    return [b for b in out if fh.safe(lambda b=b: b.isSolid, True)]


def part_frame(comp) -> Tuple[pl.Vec, pl.Vec, float, float, float, list]:
    """(center of mass, spin axis, low end, high end, com along axis, flat faces) in the part's coordinates."""
    props = comp.getPhysicalProperties(adsk.fusion.CalculationAccuracy.MediumCalculationAccuracy)
    com = props.centerOfMass
    c = (com.x, com.y, com.z)
    axis = None
    ok, i1, i2, i3 = props.getPrincipalMomentsOfInertia()
    if ok:
        idx = pl.axis_index([i1, i2, i3])
        if idx is not None:
            ok2, xa, ya, za = props.getPrincipalAxes()
            if ok2:
                v = (xa, ya, za)[idx]
                axis = pl.unit((v.x, v.y, v.z))
    bodies = _bodies(comp)
    if axis is None:                                 # not clearly round: use the biggest round face's axis
        best_r = 0.0
        for b in bodies:
            for f in [b.faces.item(i) for i in range(b.faces.count)]:
                cyl = adsk.core.Cylinder.cast(f.geometry)
                if cyl and cyl.radius > best_r:
                    best_r, axis = cyl.radius, pl.unit((cyl.axis.x, cyl.axis.y, cyl.axis.z))
        _log.info("%s isn't clearly round by mass - using its largest round face's axis", comp.name)
    if axis is None:
        raise fb.FeatureError("Gusset couldn't tell which way this part's axis points.")
    lo, hi, faces, cylinders = math.inf, -math.inf, [], []
    for b in bodies:
        for i in range(b.vertices.count):
            g = b.vertices.item(i).geometry
            t = pl.dot((g.x, g.y, g.z), axis)
            lo, hi = min(lo, t), max(hi, t)
        for f in [b.faces.item(i) for i in range(b.faces.count)]:
            cyl = adsk.core.Cylinder.cast(f.geometry)
            if cyl and abs(pl.dot(pl.unit((cyl.axis.x, cyl.axis.y, cyl.axis.z)), axis)) > 0.999:
                ends = []
                for e in [f.edges.item(k) for k in range(f.edges.count)]:
                    circ = adsk.core.Circle3D.cast(e.geometry) or adsk.core.Arc3D.cast(e.geometry)
                    if circ:
                        ends.append(pl.dot((circ.center.x, circ.center.y, circ.center.z), axis))
                if ends:
                    cylinders.append((cyl.radius, min(ends), max(ends)))
                continue
            plane = adsk.core.Plane.cast(f.geometry)
            if not plane:
                continue
            n = (plane.normal.x, plane.normal.y, plane.normal.z)
            if fh.safe(lambda f=f: f.isParamReversed, False):
                n = pl.scale(n, -1.0)
            along = pl.dot(n, axis)
            if abs(abs(along) - 1.0) < 1e-3:
                pos = pl.dot((plane.origin.x, plane.origin.y, plane.origin.z), axis)
                faces.append((pos, 1 if along > 0 else -1))
                lo, hi = min(lo, pos), max(hi, pos)
    if lo == math.inf:
        raise fb.FeatureError("This part has no solid bodies.")
    _log.debug("%s: ends %.3f..%.3f cm, %d flat face(s), round faces (r, from, to): %s", comp.name, lo, hi,
               len(faces), sorted((round(r, 3), round(a, 3), round(b, 3)) for r, a, b in cylinders)[-6:])
    return c, axis, lo, hi, pl.dot(c, axis), faces, cylinders


def _place_one(req: dict) -> str:
    design = _active()
    item = next((i for i in cb.catalog() if i.file_id == req["file_id"]), None)
    occ, linked, data_file = cl.insert(req["file_id"], design.activeComponent, req["category"],
                                       cb.library_project(), req["vendor"], req["file_name"])
    cb.count_use(item.file_id if item else req["file_id"])
    comp = occ.component
    c, axis, lo, hi, com_t, faces, cylinders = part_frame(comp)
    seat = pl.seat_along_axis(req["mode"], lo, hi, com_t, faces, cylinders if req["mode"] != pl.CENTER else ())
    if req["mode"] == pl.FLANGE_OUT:
        _remember_bearing(req["file_id"], lo, hi, cylinders)
    point, target_axis = _to_active_space(design, req["point"], req["axis"])
    if seat.flip:
        target_axis = pl.scale(target_axis, -1.0)
    ref = pl.any_perpendicular(axis)
    from_origin = pl.add(c, pl.scale(axis, seat.position))
    to_x = pl.any_perpendicular(target_axis)
    m = adsk.core.Matrix3D.create()
    P, V = adsk.core.Point3D.create, adsk.core.Vector3D.create
    m.setToAlignCoordinateSystems(P(*from_origin), V(*ref), V(*pl.cross(axis, ref)), V(*axis),
                                  P(*point), V(*to_x), V(*pl.cross(target_axis, to_x)), V(*target_axis))
    for attempt in (1, 2):
        occ.transform2 = m
        if design.designType == adsk.fusion.DesignTypes.ParametricDesignType:
            snaps = design.snapshots
            if fh.safe(lambda: snaps.hasPendingSnapshot, False):
                snaps.add()                               # keep the new position in the timeline
        facing, landed = _check(occ, axis, from_origin, target_axis, point)
        if facing > 0.999 and landed < 0.01:
            break
        _log.warning("%s didn't land right (try %d): axis . target = %.3f, %.3f cm off", req["title"], attempt,
                     facing, landed)
    else:
        raise fb.FeatureError("Fusion didn't keep it where Gusset put it - attach it with Place COTS Part.")
    pinned = _pin(design, occ, req.get("anchor", ""))
    _log.info("Placed %s (%s): part axis %s -> %s, seat %.3f cm%s, %s", req["title"], "linked" if linked else "copy",
              tuple(round(a, 3) for a in axis), tuple(round(a, 3) for a in target_axis), seat.position,
              " (flange end flipped)" if seat.flip else "", pinned + (f"; {seat.note}" if seat.note else ""))
    return seat.note


def _remember_bearing(file_id: str, lo: float, hi: float, cylinders) -> None:
    """Save the bearing's measured width + flange (inches) for Shaft & Spacer's reference note."""
    try:
        side, under = pl.flange_from_cylinders(cylinders, lo, hi)
        flange = (hi - under if side > 0 else under - lo) if side else 0.0
        dims = settings.load_state(config.ADDIN_DIR).get("bearing_dims") or {}
        dims = dims if isinstance(dims, dict) else {}
        dims[file_id] = [round((hi - lo) / 2.54, 4), round(flange / 2.54, 4)]
        settings.save_state(config.ADDIN_DIR, bearing_dims=dims)
    except Exception as exc:
        _log.debug("Couldn't save bearing size: %s", exc)


def _check(occ, axis, origin, target_axis, point) -> Tuple[float, float]:
    """Read the part's position back: (how well its axis lines up, how far its seat is from the target)."""
    m = occ.transform2
    v = adsk.core.Vector3D.create(*axis)
    v.transformBy(m)
    p = adsk.core.Point3D.create(*origin)
    p.transformBy(m)
    return pl.dot(pl.unit((v.x, v.y, v.z)), target_axis), math.dist((p.x, p.y, p.z), point)


def _pin(design, occ, anchor_token: str) -> str:
    """Rigid as-built joint to what it sits on; ground it when it sits on the top assembly."""
    here = occ.createForAssemblyContext(design.activeOccurrence) if design.activeOccurrence else occ
    anchor = None
    if anchor_token:
        found = fh.safe(lambda: design.findEntityByToken(anchor_token), [])
        anchor = found[0] if found else None
    if anchor is not None:
        try:
            joints = design.rootComponent.asBuiltJoints
            inp = joints.createInput(here, anchor, None)
            inp.setAsRigidJointMotion()
            joint = joints.add(inp)
            joint.name = f"COTS {occ.component.name}"[:60]
            return "rigid joint"
        except Exception as exc:
            _log.info("As-built joint didn't work (%s) - grounding the part instead", exc)
    try:
        here.isGrounded = True
        return "grounded"
    except Exception as exc:
        _log.info("Couldn't ground %s: %s", occ.name, exc)
        return "left free"
