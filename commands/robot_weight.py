"""
Robot Weight - GUSSET > Review > Robot Weight (0.13).

A side panel (resources/robot_weight/index.html) that shows, while students
design: robot weight vs the limit, robot + bumpers, a breakdown by subsystem, the
heaviest parts, and made parts still on Fusion's default material (their weight is
a guess). Click a part to find it in the design.

Numbers come from the same BOM rows Export BOM writes (lib/weight_core.py), so the
panel and the spreadsheet agree. Refreshes when you press Refresh and (optionally)
every time the design is saved. Limits are team settings (weight_limits).
"""

from __future__ import annotations

import json
import os
import time
import adsk.core
import adsk.fusion

from .. import config
from ..lib import bom_core as bc
from ..lib import design_tree as dt
from ..lib import fusion_helpers as fh
from ..lib import log as gslog
from ..lib import naming_core as nc
from ..lib import settings
from ..lib import weight_core as wc

CMD_ID = "Gusset_RobotWeight"
CMD_NAME = "Robot Weight"
CMD_TOOLTIP = "See the robot's weight against the limit while you design - by subsystem, heaviest parts first."
ICON_DIR = os.path.join(config.ADDIN_DIR, "resources", "robot_weight")
PALETTE_ID = "Gusset_RobotWeightPanel"
HTML_PATH = os.path.join(config.ADDIN_DIR, "resources", "robot_weight", "index.html")
GROUP = "robot_weight"
EVENT_ID = "Gusset_RobotWeightRefresh"
QUICK_BUDGET_S = 30.0          # seconds Fusion may spend weighing parts on a normal refresh
FULL_BUDGET_S = 600.0          # "Weigh every part"

_log = gslog.get_logger("robot_weight")
_state = {"busy": False, "last": None, "event": None}


# ---------------------------------------------------------------------------
# Panel plumbing
# ---------------------------------------------------------------------------
def _palette():
    return fh.app_ui()[1].palettes.itemById(PALETTE_ID)


def _send(action: str, payload) -> None:
    pal = _palette()
    if pal:
        try:
            pal.sendInfoToHTML(action, json.dumps(payload))
        except Exception as exc:
            _log.debug("sendInfoToHTML(%s) failed: %s", action, exc)


def _prefs() -> dict:
    st = settings.load_state(config.ADDIN_DIR)
    return {"auto": bool(st.get("weight_auto_refresh", True)),
            "ignored": [str(k) for k in (st.get("weight_really_default") or [])]}


def show() -> None:
    _, ui = fh.app_ui()
    pal = _palette()
    if pal is None:
        pal = ui.palettes.add(PALETTE_ID, "Gusset Robot Weight", HTML_PATH.replace("\\", "/"),
                              True, True, True, 340, 640, True)
        try:
            pal.dockingState = adsk.core.PaletteDockingStates.PaletteDockStateRight
        except Exception:
            pal.dockingState = adsk.core.PaletteDockingStates.PaletteDockStateFloating
        pal.incomingFromHTML.add(fh.make_handler(adsk.core.HTMLEventHandler, _on_html, "Robot Weight panel", GROUP))
        _log.info("Robot Weight panel opened")
    else:
        pal.isVisible = True
        refresh()


def _on_html(args) -> None:
    html = adsk.core.HTMLEventArgs.cast(args)
    html.returnData = "OK"
    if html.action == "response":
        return
    try:
        data = json.loads(html.data or "{}")
    except ValueError:
        data = {}
    try:
        if html.action == "ready":
            _send("prefs", _prefs())
            refresh()
        elif html.action == "refresh":
            refresh(full=bool(data.get("full")))
        elif html.action == "find":
            _find(str(data.get("key", "")), str(data.get("name", "")))
        elif html.action == "reallyDefault":            # "it really is steel" - stop flagging it
            st = _prefs()
            keys = sorted(set(st["ignored"]) | {str(data.get("key", ""))})
            settings.save_state(config.ADDIN_DIR, weight_really_default=keys)
            refresh()
        elif html.action == "auto":
            settings.save_state(config.ADDIN_DIR, weight_auto_refresh=bool(data.get("on")))
            _send("prefs", _prefs())
        elif html.action == "settings":
            fh.run_command("Gusset_Settings")
    except Exception:
        fh.report_error(f"Robot Weight ({html.action})")


# ---------------------------------------------------------------------------
# Weighing
# ---------------------------------------------------------------------------
def refresh(full: bool = False) -> None:
    if _state["busy"]:
        return
    design = fh.active_design()
    if design is None:
        _send("empty", {"text": "Open a robot design to see its weight."})
        return
    _state["busy"] = True
    started = time.time()
    try:
        _send("status", {"text": "Weighing every part (this can take a few minutes)..." if full
                         else "Weighing parts...", "busy": True})
        adsk.doEvents()
        cfg = settings.load_config(config.ADDIN_DIR)
        ctx = dt.TreeContext(cfg)
        root = dt.root_node(design, ctx)
        stats = dt.fill_bom_info(root, ctx, cfg, budget=FULL_BUDGET_S if full else QUICK_BUDGET_S)
        bom = bc.build_bom(root, cfg, title=nc.strip_fusion_suffixes(root.name))
        ws = settings.read_weight_settings(config.ADDIN_DIR)
        rep = wc.report(bom, ws["limits"], ws["exclude"], ws["default_materials"],
                        subsystem_names=dict(getattr(cfg, "subsystems", {}) or {}),
                        ignored_materials=_prefs()["ignored"])
        payload = rep.to_json()
        payload.update(design=nc.strip_fusion_suffixes(root.name), seconds=round(time.time() - started, 1),
                       when=time.strftime("%H:%M"))
        _state["last"] = payload
        _send("weight", payload)
        _log.info("Robot weight %s: %s (%d measured, %d not yet, %.1fs; %s)", payload["design"], rep.headline(),
                  rep.measured, len(rep.unmeasured), time.time() - started, stats)
    except Exception:
        _log.exception("Weighing failed")
        _send("status", {"text": "Couldn't weigh this design - see the Gusset log.", "busy": False})
    finally:
        _state["busy"] = False


def _find(key: str, name: str) -> None:
    """Select the first copy of a part and zoom to it, so students can fix its material."""
    app, ui = fh.app_ui()
    design = fh.active_design()
    comp = dt.find_component(design, key, name) if design else None
    occs = design.rootComponent.allOccurrencesByComponent(comp) if comp else None
    if not occs or occs.count == 0:
        _send("status", {"text": f"Couldn't find {name} - press Refresh.", "busy": False})
        return
    ui.activeSelections.clear()
    ui.activeSelections.add(occs.item(0))
    fh.safe(lambda: app.activeViewport.fit())
    _send("status", {"text": f"Selected {name}. Right-click it > Physical Material to set what it's made of.",
                     "busy": False})


# ---------------------------------------------------------------------------
# Refresh after a save (custom event: don't weigh inside Fusion's save handler)
# ---------------------------------------------------------------------------
def _on_saved(args) -> None:
    pal = _palette()
    if pal and pal.isVisible and _prefs()["auto"]:
        fh.app_ui()[0].fireCustomEvent(EVENT_ID, "")


def start() -> None:
    app, _ = fh.app_ui()
    fh.add_button(CMD_ID, CMD_NAME, CMD_TOOLTIP, ICON_DIR, _on_created, config.PANEL_REVIEW_ID,
                  config.PANEL_REVIEW_NAME, promote=False)
    try:
        app.unregisterCustomEvent(EVENT_ID)
    except Exception:
        pass
    _state["event"] = app.registerCustomEvent(EVENT_ID)
    _state["event"].add(fh.make_handler(adsk.core.CustomEventHandler, lambda a: refresh(), "Robot Weight: refresh",
                                        GROUP))
    app.documentSaved.add(fh.make_handler(adsk.core.DocumentEventHandler, _on_saved, "Robot Weight: saved", GROUP))


def stop() -> None:
    try:
        pal = _palette()
        if pal:
            pal.deleteMe()
    except Exception:
        pass
    try:
        fh.app_ui()[0].unregisterCustomEvent(EVENT_ID)
    except Exception:
        pass
    fh.release_handlers(GROUP)
    fh.remove_button(CMD_ID, config.PANEL_REVIEW_ID)


def _on_created(args: adsk.core.CommandCreatedEventArgs) -> None:
    try:
        args.command.isAutoExecute = True
    except Exception:
        pass
    args.command.execute.add(fh.make_handler(adsk.core.CommandEventHandler, lambda a: show(),
                                             "Robot Weight: open", "robot_weight_cmd"))
