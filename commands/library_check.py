"""
Library Check - GUSSET > COTS > Library Check (also the badge on the COTS panel).

Opens a window (resources/library_check/index.html) listing everything wrong with
the FRC_COTS library, grouped (Duplicates, Broken links, Missing pictures, Names
and folders, Part numbers and links, Prices, Tips), each with a Fix button:

    review    move a duplicate to FRC_COTS/_Review (never deletes)
    relink    look a temporary upload id up again
    rescan    read the library again
    resave    save a version so Fusion makes a picture
    rename    '<part #> <name>'
    move      to <Category>/<Vendor>
    details   price / link / part # typed right in the window -> new version of the part

Also from this window: "Update from a new STEP" (vendor revisions). It saves a new
version of the library part and offers to update the open robot's own copy
(COTS/<Category>/...), so Fusion marks the linked parts out of date.

Every Fusion call happens here, on Fusion's main thread (HTML events are). Checks
themselves are in lib/library_check.py (tested).
"""

from __future__ import annotations

import json
import os
import time
import webbrowser
from typing import Dict, List

import adsk.core

from .. import config
from ..lib import cots_core as cc
from ..lib import cots_library as cl
from ..lib import feature_builder as fb
from ..lib import fusion_helpers as fh
from ..lib import library_check as lc
from ..lib import log as pclog
from ..lib import settings
from . import cots_browser as cb

CMD_ID = "Gusset_LibraryCheck"
CMD_NAME = "Library Check"
CMD_TOOLTIP = "Find duplicates, missing pictures, prices and links, and badly named files in the COTS library."
ICON_DIR = os.path.join(config.ADDIN_DIR, "resources", "library_check")
PALETTE_ID = "Gusset_LibraryCheckPanel"
HTML_PATH = os.path.join(config.ADDIN_DIR, "resources", "library_check", "index.html")
PALETTE_GROUP = "library_check_panel"
TITLE = "Gusset - Library Check"
BULK_KINDS = {"rename", "move", "relink", "resave"}      # safe to "Fix all" in one go

_log = pclog.get_logger("library_check")


# ---------------------------------------------------------------------------
# What the check sees
# ---------------------------------------------------------------------------
def ignored() -> List[str]:
    value = settings.load_state(config.ADDIN_DIR).get("library_check_ignored")
    return [str(v) for v in value] if isinstance(value, list) else []


def problems(missing=()) -> List[lc.Problem]:
    lib = cb.library_settings()
    return lc.check(cb.catalog(), lib["vendors"], lib["categories"], cb.no_thumbnail_ids(), missing, ignored())


def quick_summary() -> Dict[str, object]:
    """For the COTS panel's badge - no cloud calls."""
    try:
        s = lc.summary(problems())
        return {"text": lc.badge_text(s), "fix": s.get(lc.FIX, 0), "info": s.get(lc.INFO, 0)}
    except Exception:
        _log.exception("Quick library check failed")
        return {"text": "", "fix": 0, "info": 0}


# ---------------------------------------------------------------------------
# Window
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


def _status(text: str, busy: bool = False) -> None:
    _send("status", {"text": text, "busy": busy})
    adsk.doEvents()                                   # let the window repaint during long fixes


def _state(note: str = "") -> dict:
    found = problems()
    lib = cb.library_settings()
    return {
        "problems": [p.to_json() for p in found],
        "groups": [{"id": g, "name": n} for g, n in lc.GROUPS],
        "summary": lc.summary(found),
        "parts": [{"file_id": i.file_id, "title": i.title, "pn": i.info.vendor_pn, "vendor": i.vendor,
                   "category": i.category, "price": i.info.price, "url": i.info.url}
                  for i in cb.catalog()],
        "vendors": [v.name for v in lib["vendors"]],
        "count": len(cb.catalog()),
        "ignored": len(ignored()),
        "note": note,
        "theme": settings.load_state(config.ADDIN_DIR).get("cots_theme", "dark"),
    }


def show() -> None:
    _, ui = fh.app_ui()
    pal = _palette()
    if pal is None:
        pal = ui.palettes.add(PALETTE_ID, "Gusset Library Check", HTML_PATH.replace("\\", "/"),
                              True, True, True, 560, 720, True)
        pal.dockingState = adsk.core.PaletteDockingStates.PaletteDockStateFloating
        pal.incomingFromHTML.add(fh.make_handler(adsk.core.HTMLEventHandler, _on_html, "Library Check window",
                                                 PALETTE_GROUP))
        _log.info("Library Check window opened (%d parts in the catalog)", len(cb.catalog()))
    else:
        pal.isVisible = True
        _send("state", _state())


def _on_html(args) -> None:
    html = adsk.core.HTMLEventArgs.cast(args)
    html.returnData = "OK"
    action = html.action
    if action == "response":
        return
    try:
        data = json.loads(html.data or "{}")
    except ValueError:
        data = {}
    _log.debug("check window -> %s %s", action, {k: v for k, v in data.items() if k != "items"})
    try:
        if action == "ready":
            _send("state", _state())
        elif action == "recheck":
            _full_check()
        elif action == "fix":
            note = _fix_one(str(data.get("kind", "")), str(data.get("fix", "")), str(data.get("file_id", "")),
                            data.get("values") or {}, str(data.get("other_id", "")))
            _after_change(note)
        elif action == "fixAll":
            _fix_all(str(data.get("fix", "")))
        elif action == "saveDetails":
            _save_many(data.get("items") or [])
        elif action == "ignore":
            keys = [k for k in ignored() if k != data.get("key")] + [str(data.get("key"))]
            settings.save_state(config.ADDIN_DIR, library_check_ignored=keys)
            _send("state", _state("Hidden on this laptop."))
        elif action == "unignore":
            settings.save_state(config.ADDIN_DIR, library_check_ignored=[])
            _send("state", _state("Showing everything again."))
        elif action == "revision":
            _revision(str(data.get("file_id", "")))
        elif action == "openPart":
            _open_part(str(data.get("file_id", "")))
        elif action == "openLink":
            url = str(data.get("url", ""))
            if url.startswith("http"):
                webbrowser.open(url)
    except fb.FeatureError as exc:
        _log.info("Library Check: %s", exc)
        _send("state", _state())
        _send("result", {"ok": False, "text": str(exc)})
    except Exception:
        fh.report_error(f"Library Check ({action})")
        _send("state", _state())
        _send("result", {"ok": False, "text": "That didn't work - the details are in the error window."})


def _after_change(note: str) -> None:
    cb.save_and_refresh_panel()
    _send("state", _state())
    _send("result", {"ok": True, "text": note})


# ---------------------------------------------------------------------------
# Full check (reads the cloud again)
# ---------------------------------------------------------------------------
def _full_check() -> None:
    _status("Reading the library again (about a second per folder)...", True)
    before = {i.file_id for i in cb.catalog()}
    started = time.time()
    if not cb.rescan():
        _status("")
        _send("result", {"ok": False, "text": "There's no FRC_COTS project yet - open the COTS panel to make one."})
        return
    after = {i.file_id for i in cb.catalog()}
    gone = len(before - after)
    cb.ask_for_pictures()
    found = problems()
    note = f"Checked {len(after)} parts in {time.time() - started:.0f}s"
    if gone:
        note += f" - {gone} part(s) were deleted or moved since last time and are gone from the panel"
    _log.info("Full library check: %s; %s", note, lc.summary(found))
    cb.save_and_refresh_panel()
    _send("state", _state(note + "."))
    _status("")


# ---------------------------------------------------------------------------
# Fixes
# ---------------------------------------------------------------------------
def _item(file_id: str) -> cc.CatalogItem:
    item = next((i for i in cb.catalog() if i.file_id == file_id), None)
    if item is None:
        raise fb.FeatureError("That part isn't in the panel anymore - press Re-check.")
    return item


def _data_file(item: cc.CatalogItem):
    return cl._must_find(item.file_id, cb.library_project(), item.category, item.vendor, item.file_name)


def _fix_one(kind: str, fix: str, file_id: str, values: dict, other_id: str = "") -> str:
    if fix == "rescan":
        _full_check()
        return "Read the library again."
    item = _item(file_id)
    _status(f"{item.title}...", True)
    project = cb.library_project()
    if project is None:
        raise fb.FeatureError("Can't find the FRC_COTS project.")

    if fix == "relink":
        data_file = cl.resolve(item.file_id, project, item.category, item.vendor, item.file_name)
        real = getattr(data_file, "id", "") if data_file is not None else ""
        if not cl.is_cloud_id(real):
            raise fb.FeatureError("Still uploading - wait a minute, then press Re-check.")
        cb.update_item(item.file_id, file_id=real)
        return f"Found {item.title} again."

    data_file = _data_file(item)
    if fix == "review":
        note = cl.move_to_review(data_file, project, lc.REVIEW_FOLDER)
        cb.remove_item(item.file_id)
        return note
    if fix == "rename":
        new_name = str(values.get("name") or cc.part_file_name(item.info.vendor_pn, item.info.name))
        note = cl.rename_file(data_file, new_name)
        cb.update_item(item.file_id, file_name=new_name)
        return note
    if fix == "move":
        note = cl.move_to(data_file, project, item.info)
        cb.update_item(item.file_id, category=item.info.category, vendor=item.info.vendor)
        return note
    if fix == "resave":
        cl.save_version(data_file, item.info, why="New picture")
        cb.forget_picture(item.file_id)
        return "Saved a new version - the picture shows up in a minute or two."
    if fix == "details":
        return _save_details(item, data_file, values)
    if fix == "notSame":                                    # duplicates: "they're different parts"
        new = lc.apply_details(item.info, {})
        new.different_part = True
        cl.save_version(data_file, new, why="Marked different part")
        cb.update_item(item.file_id, info=new)
        return "Marked as a different part - it won't be flagged again."
    raise fb.FeatureError(f"Gusset doesn't know how to fix '{fix}' yet.")


def _save_details(item: cc.CatalogItem, data_file, values: dict) -> str:
    new = lc.apply_details(item.info, values)
    errs = lc.check_details(new, cb.library_settings()["vendors"])
    if errs:
        raise fb.FeatureError(" ".join(errs))
    pn_changed = new.vendor_pn != item.info.vendor_pn
    file_id = cl.save_version(data_file, new, why="Details")
    took = cl.description_took(file_id or item.file_id, new)
    cb.update_item(item.file_id, info=new)
    if pn_changed:
        new_name = cc.part_file_name(new.vendor_pn, new.name)
        cl.rename_file(data_file, new_name)
        cb.update_item(item.file_id, file_name=new_name)
    if not took:
        # The part itself (what the BOM reads) has the new details either way.
        _log.warning("Details for %s are inside the part, but the file description didn't change - "
                     "other laptops' panels may show the old values until this is fixed", item.file_name)
    return f"Saved {item.title}."


def _save_many(rows: List[dict]) -> None:
    """Prices / links typed into several rows, then 'Save all' (each is a new version: a few seconds each)."""
    rows = [r for r in rows if isinstance(r, dict) and r.get("file_id")]
    done, failed = 0, []
    started = time.time()
    for n, row in enumerate(rows, 1):
        try:
            item = _item(str(row["file_id"]))
            _status(f"Saving {n} of {len(rows)}: {item.title}", True)
            _save_details(item, _data_file(item), row.get("values") or {})
            done += 1
        except fb.FeatureError as exc:
            failed.append(f"{row.get('title', '?')}: {exc}")
        except Exception as exc:
            _log.exception("Saving details for %s failed", row.get("file_id"))
            failed.append(f"{row.get('title', '?')}: {exc}")
    _log.info("Saved details for %d part(s) in %.0fs (%d failed)", done, time.time() - started, len(failed))
    text = f"Saved {done} part(s)." + (f" {len(failed)} didn't save: " + "; ".join(failed[:3]) if failed else "")
    cb.save_and_refresh_panel()
    _send("state", _state())
    _send("result", {"ok": not failed, "text": text})
    _status("")


def _fix_all(fix: str) -> None:
    if fix not in BULK_KINDS:
        raise fb.FeatureError("That kind of fix has to be done one at a time.")
    todo = [p for p in problems() if p.fix == fix]
    done, failed = 0, []
    for n, p in enumerate(todo, 1):
        _status(f"Fixing {n} of {len(todo)}: {p.title}", True)
        try:
            _fix_one(p.kind, p.fix, p.file_id, p.suggest)
            done += 1
        except fb.FeatureError as exc:
            failed.append(f"{p.title}: {exc}")
    _status("")
    cb.save_and_refresh_panel()
    _send("state", _state())
    _send("result", {"ok": not failed, "text": f"Fixed {done}." + (f" {len(failed)} need a look: "
                                                                   + "; ".join(failed[:3]) if failed else "")})


# ---------------------------------------------------------------------------
# Vendor revisions
# ---------------------------------------------------------------------------
def _pick_step(title: str) -> str:
    _, ui = fh.app_ui()
    dlg = ui.createFileDialog()
    dlg.title = title
    dlg.filter = "STEP files (*.step;*.stp);;All files (*.*)"
    dlg.isMultiSelectEnabled = False
    downloads = os.path.join(os.path.expanduser("~"), "Downloads")
    if os.path.isdir(downloads):
        dlg.initialDirectory = downloads
    return dlg.filename if dlg.showOpen() == adsk.core.DialogResults.DialogOK else ""


def _revision(file_id: str) -> None:
    _, ui = fh.app_ui()
    item = _item(file_id)
    step = _pick_step(f"New STEP for {item.file_name}")
    if not step:
        return
    robot_doc = fh.app_ui()[0].activeDocument          # remember the robot before library files open
    data_file = _data_file(item)
    copy = cl.robot_copy(data_file, item.category)
    answer = ui.messageBox(
        f"Replace the model of\n    {item.file_name}\nwith\n    {os.path.basename(step)}?\n\n"
        "Gusset saves a NEW VERSION of the library part (the old one stays in Fusion's version history). "
        "Joints to this part in robots may need to be picked again.",
        TITLE, adsk.core.MessageBoxButtonTypes.YesNoButtonType)
    if answer != adsk.core.DialogResults.DialogYes:
        return
    info = lc.apply_details(item.info, {"notes": lc.revision_note(item.info, os.path.basename(step))})
    _status(f"Importing {os.path.basename(step)} into {item.title}...", True)
    cl.save_version(data_file, info, step, why="Vendor revision")
    cb.update_item(item.file_id, info=info)
    cb.forget_picture(item.file_id)
    lines = [f"Updated {item.file_name} in the library."]
    if copy is not None:
        if ui.messageBox(f"This robot has its own copy of the part (COTS/{item.category}/{copy.name}).\n\n"
                         "Update that copy too?", TITLE,
                         adsk.core.MessageBoxButtonTypes.YesNoButtonType) == adsk.core.DialogResults.DialogYes:
            _status("Updating this robot's copy...", True)
            cl.save_version(copy, info, step, why="Vendor revision (robot copy)")
            lines.append("Updated this robot's copy - Fusion now shows the part as out of date: right-click it "
                         "in the Browser and choose Get Latest.")
        else:
            lines.append("This robot still uses the old model.")
    try:
        if robot_doc is not None and robot_doc.isValid:
            robot_doc.activate()
    except Exception:
        pass
    _status("")
    _after_change(" ".join(lines))


def _open_part(file_id: str) -> None:
    item = _item(file_id)
    fh.app_ui()[0].documents.open(_data_file(item), True)


# ---------------------------------------------------------------------------
# Toolbar
# ---------------------------------------------------------------------------
def start() -> None:
    fh.add_button(CMD_ID, CMD_NAME, CMD_TOOLTIP, ICON_DIR, _on_created, config.PANEL_COTS_ID,
                  config.PANEL_COTS_NAME, promote=False)


def stop() -> None:
    try:
        pal = _palette()
        if pal:
            pal.deleteMe()
    except Exception:
        pass
    fh.release_handlers(PALETTE_GROUP)
    fh.remove_button(CMD_ID, config.PANEL_COTS_ID)


def _on_created(args: adsk.core.CommandCreatedEventArgs) -> None:
    try:
        args.command.isAutoExecute = True
    except Exception:
        pass
    args.command.execute.add(fh.make_handler(adsk.core.CommandEventHandler, lambda a: show(),
                                             "Library Check: open window", "library_check_cmd"))
