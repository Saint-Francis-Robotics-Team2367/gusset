"""
COTS Library - the picture panel (GUSSET > COTS > COTS Library).

A docked panel (Fusion "palette" = a small web page) listing every part in the
FRC_COTS project: search, category list, vendor chips, favorites and a tile per
part with Fusion's own thumbnail. Click a tile -> the part is inserted into the
active component and "Place COTS Part" starts, so the student clicks the edge
or face it goes on.

Talking to the page:
    page -> Python   adsk.fusionSendData(action, json)   -> _on_html()
    Python -> page   palette.sendInfoToHTML(action, json) -> fusionJavaScriptHandler.handle()

The catalog is cached in cache/cots_catalog.json (opening the panel is
instant); Refresh rescans the cloud project. Thumbnails are fetched in the
background and cached as PNGs in cache/cots_thumbs/.
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time
import webbrowser
from typing import List, Optional

import adsk.core
import adsk.fusion

from .. import config
from ..lib import cots_core as cc
from ..lib import cots_family as cf
from ..lib import cots_library as cl
from ..lib import feature_builder as fb
from ..lib import fusion_helpers as fh
from ..lib import log as gslog
from ..lib import settings

CMD_ID = "Gusset_CotsBrowser"
CMD_NAME = "COTS Library"
CMD_TOOLTIP = "Browse the team's FRC_COTS library and drop parts into your design."
ICON_DIR = os.path.join(config.ADDIN_DIR, "resources", "cots")
PALETTE_ID = "Gusset_CotsPalette"
HTML_PATH = os.path.join(config.ADDIN_DIR, "resources", "cots_palette", "index.html")
CACHE_DIR = os.path.join(config.ADDIN_DIR, "cache")
CATALOG_PATH = os.path.join(CACHE_DIR, "cots_catalog.json")
THUMB_DIR = os.path.join(CACHE_DIR, "cots_thumbs")
THUMB_EVENT = "Gusset_CotsThumbs"
STALE_HOURS = 24 * 7      # full rescans are slow (~1 s per folder), so only weekly by themselves
HANDLER_GROUP = "cots_palette"

_log = gslog.get_logger("cots_browser")
_catalog: List[cc.CatalogItem] = []
_scanned_at = 0.0
_fetcher: Optional[cl.ThumbnailFetcher] = None
_poll_thread: Optional[threading.Thread] = None
_stop_polling = threading.Event()
_thumb_event = None
_state_ready: dict = {}


# ---------------------------------------------------------------------------
# Library settings (Settings button -> gusset_config.json "cots" section)
# ---------------------------------------------------------------------------
def library_settings() -> dict:
    raw = settings._read_key(config.ADDIN_DIR, "cots")
    raw = raw if isinstance(raw, dict) else {}
    vendors = cc.DEFAULT_VENDORS
    if isinstance(raw.get("vendors"), list):
        try:
            vendors = [cc.Vendor(str(v["name"]), str(v.get("pattern", "")), str(v.get("example", "")),
                                 str(v.get("link", "")), str(v.get("hint", ""))) for v in raw["vendors"]]
        except (KeyError, TypeError):
            _log.warning("cots.vendors in gusset_config.json isn't valid - using the built-in vendors")
    cats = raw.get("categories")
    cats = [str(c) for c in cats] if isinstance(cats, list) and cats else list(cc.DEFAULT_CATEGORIES)
    return {"project": str(raw.get("project") or cc.LIBRARY_PROJECT), "categories": cats, "vendors": vendors}


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------
def catalog() -> List[cc.CatalogItem]:
    global _catalog, _scanned_at
    if not _catalog and os.path.exists(CATALOG_PATH):
        with open(CATALOG_PATH, "r", encoding="utf-8") as handle:
            _catalog, _scanned_at = cc.catalog_from_json(handle.read())
        _log.info("Loaded %d cached COTS part(s)", len(_catalog))
    return _catalog


def _save_catalog() -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(CATALOG_PATH, "w", encoding="utf-8") as handle:
        handle.write(cc.catalog_to_json(_catalog, _scanned_at))


def library_project(lib: Optional[dict] = None):
    """The library project (remembering its folder id so the next lookup is instant)."""
    lib = lib or library_settings()
    project = cl.find_project(lib["project"], str(settings.load_state(config.ADDIN_DIR).get("cots_folder_id", "")))
    if project is not None:
        folder_id = cl.project_folder_id(project)
        if folder_id and settings.load_state(config.ADDIN_DIR).get("cots_folder_id") != folder_id:
            settings.save_state(config.ADDIN_DIR, cots_folder_id=folder_id)
    return project


def rescan() -> bool:
    """Scan the cloud project. False if the project doesn't exist yet."""
    global _catalog, _scanned_at
    lib = library_settings()
    project = library_project(lib)
    if project is None:
        _log.info("No %s project yet", lib["project"])
        return False
    items = cl.scan(project, lib["vendors"])
    for item in items:
        if os.path.exists(os.path.join(THUMB_DIR, cc.thumb_file_name(item.file_id))):
            item.thumb = cc.thumb_file_name(item.file_id)
    _catalog, _scanned_at = items, time.time()
    _save_catalog()
    return True


def no_thumbnail_ids() -> List[str]:
    """Parts Fusion said have no picture (Library Check offers to make one)."""
    value = settings.load_state(config.ADDIN_DIR).get("cots_no_thumb")
    return [str(v) for v in value] if isinstance(value, list) else []


def _thumb_failed(file_id: str) -> None:
    ids = no_thumbnail_ids()
    if file_id not in ids:
        settings.save_state(config.ADDIN_DIR, cots_no_thumb=ids + [file_id])
        _log.info("No picture in Fusion for %s", file_id[:60])


def forget_picture(file_id: str) -> None:
    """After a new version: drop the cached picture and the 'no picture' mark so it's fetched again."""
    settings.save_state(config.ADDIN_DIR, cots_no_thumb=[i for i in no_thumbnail_ids() if i != file_id])
    path = os.path.join(THUMB_DIR, cc.thumb_file_name(file_id))
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError as exc:
        _log.debug("Couldn't remove old thumbnail %s: %s", path, exc)
    for item in catalog():
        if item.file_id == file_id:
            item.thumb = ""
            _start_thumbs([item])


def update_item(file_id: str, **changes) -> None:
    """Library Check changed a part (renamed, moved, new details, real id) - keep the panel in step."""
    for item in catalog():
        if item.file_id == file_id:
            for key, value in changes.items():
                setattr(item, key, value)
            _log.debug("Catalog: %s updated %s", file_id[:60], sorted(changes))
            return


def remove_item(file_id: str) -> None:
    catalog()
    _catalog[:] = [i for i in _catalog if i.file_id != file_id]


def save_and_refresh_panel() -> None:
    _save_catalog()
    _send_catalog()


def ask_for_pictures() -> None:
    _start_thumbs(catalog())


def add_to_catalog(item: cc.CatalogItem) -> None:
    """Called by Add to COTS Library after saving a part (no full rescan needed)."""
    catalog()
    _catalog[:] = [i for i in _catalog if i.file_id != item.file_id] + [item]
    _save_catalog()
    _send_catalog()
    _start_thumbs([item])


# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
def _palette():
    _, ui = fh.app_ui()
    return ui.palettes.itemById(PALETTE_ID)


def _send(action: str, payload) -> None:
    pal = _palette()
    if pal:
        try:
            pal.sendInfoToHTML(action, json.dumps(payload))
        except Exception as exc:
            _log.debug("sendInfoToHTML(%s) failed: %s", action, exc)


def _favorites() -> List[str]:
    favs = settings.load_state(config.ADDIN_DIR).get("cots_favorites")
    return [str(f) for f in favs] if isinstance(favs, list) else []


def _send_catalog(status: str = "") -> None:
    lib = library_settings()
    has_project = bool(catalog()) or library_project(lib) is not None
    items = []
    for i in catalog():
        d = i.to_json()
        d.update(cf.describe(i.title, i.vendor, i.category, i.info.notes))   # family, size, tags
        items.append(d)
    _send("catalog", {
        "items": items,
        "usage": _usage(),
        "health": _health(),
        "tagLabels": cf.TAG_LABELS,
        "favorites": _favorites(),
        "categories": lib["categories"],
        "vendors": [v.name for v in lib["vendors"]],
        "project": lib["project"],
        "hasProject": has_project,
        "scannedAt": _scanned_at,
        "status": status,
        "theme": settings.load_state(config.ADDIN_DIR).get("cots_theme", "dark"),
    })


def _health() -> dict:
    """The Library Check badge: {'text': '3 to fix', 'fix': 3, 'info': 101} (no cloud calls)."""
    from . import library_check                  # (imports this module - so not at the top)
    return library_check.quick_summary()


def usage() -> dict:
    return _usage()


def _usage() -> dict:
    """{file_id: [times inserted, last inserted]} on this computer (recently / most used)."""
    usage = settings.load_state(config.ADDIN_DIR).get("cots_usage")
    return usage if isinstance(usage, dict) else {}


def count_use(file_id: str) -> None:
    """Other tools that insert library parts (Belt & Chain, Shaft & Spacer) count toward Recently used too."""
    _count_use(file_id)


def _count_use(file_id: str) -> None:
    usage = cf.record_use(_usage(), file_id, time.time())
    settings.save_state(config.ADDIN_DIR, cots_usage=usage)
    _send("usage", {"usage": usage})


def _send_thumb(file_id: str, name: str) -> None:
    path = os.path.join(THUMB_DIR, name)
    try:
        with open(path, "rb") as handle:
            data = base64.b64encode(handle.read()).decode("ascii")
        _send("thumb", {"file_id": file_id, "src": "data:image/png;base64," + data})
    except OSError:
        pass


def _show() -> None:
    _, ui = fh.app_ui()
    pal = _palette()
    if pal is None:
        _state_ready.clear()
        url = HTML_PATH.replace("\\", "/")             # a plain path, like Autodesk's add-in template
        pal = ui.palettes.add(PALETTE_ID, "Gusset COTS Library", url, True, True, True, 380, 640, True)
        pal.dockingState = adsk.core.PaletteDockingStates.PaletteDockStateRight
        pal.incomingFromHTML.add(fh.make_handler(adsk.core.HTMLEventHandler, _on_html, "COTS panel", HANDLER_GROUP))
        pal.closed.add(fh.make_handler(adsk.core.UserInterfaceGeneralEventHandler, lambda a: None,
                                       "COTS panel closed", HANDLER_GROUP))
        _log.info("COTS panel created (%s)", url)
    else:
        pal.isVisible = True
        _send_catalog()


def _on_html(args) -> None:
    html_args = adsk.core.HTMLEventArgs.cast(args)
    action = html_args.action
    try:
        data = json.loads(html_args.data or "{}")
    except ValueError:
        data = {}
    html_args.returnData = "OK"
    if action == "response":
        return                     # Fusion's automatic reply to our own sendInfoToHTML - nothing to do
    _log.debug("panel -> %s %s", action, data if action != "ready" else "")
    if action == "ready":
        _send_catalog()
        if _state_ready.get("done"):
            return                                   # the page re-asks until it hears back - no rescans
        _state_ready["done"] = True
        stale = time.time() - _scanned_at > STALE_HOURS * 3600
        temporary = [i for i in catalog() if not cl.is_cloud_id(i.file_id)]
        if temporary:
            _log.info("%d part(s) still have temporary upload ids - re-reading the library", len(temporary))
        if not catalog() or stale or temporary:
            _do_refresh()
        else:
            _send_cached_thumbs()
            _start_thumbs(catalog())
    elif action == "refresh":
        _do_refresh()
    elif action == "insert":
        _insert(str(data.get("file_id", "")))
    elif action == "favorite":
        favs = [f for f in _favorites() if f != data.get("file_id")]
        if data.get("on"):
            favs.append(str(data.get("file_id")))
        settings.save_state(config.ADDIN_DIR, cots_favorites=favs)
    elif action == "theme":
        settings.save_state(config.ADDIN_DIR, cots_theme=str(data.get("theme", "dark")))
    elif action == "add":
        _run_command("Gusset_CotsAdd")
    elif action == "check":
        _run_command("Gusset_LibraryCheck")
    elif action == "createProject":
        _create_project()
    elif action == "openLink":
        url = str(data.get("url", ""))
        if url.startswith("http"):
            webbrowser.open(url)


def _do_refresh() -> None:
    _send("status", {"text": "Reading the library (about a second per folder)..."})
    try:
        started = time.time()
        found = rescan()
        _send_catalog("" if found else "no project")
        _send("status", {"text": f"{len(_catalog)} parts ({time.time() - started:.1f}s)" if found else ""})
        _send_cached_thumbs()
        _start_thumbs(_catalog)
    except Exception:
        fh.report_error("COTS Library: reading the library", show_dialog=False)
        _send("status", {"text": "Couldn't read the library - see the Gusset log."})


def _create_project() -> None:
    _, ui = fh.app_ui()
    lib = library_settings()
    answer = ui.messageBox(
        f"Create a new Fusion project called '{lib['project']}' with a folder for each category "
        f"({len(lib['categories'])})? Vendor folders are added as parts come in.\n\n"
        "Share the project with your team afterwards so everyone sees the same parts.",
        "Gusset - COTS Library", adsk.core.MessageBoxButtonTypes.YesNoButtonType)
    if answer != adsk.core.DialogResults.DialogYes:
        return
    _send("status", {"text": "Creating the project..."})
    cl.make_project(lib["project"], lib["categories"], lib["vendors"])
    _do_refresh()


def _run_command(cmd_id: str) -> None:
    _, ui = fh.app_ui()
    cmd_def = ui.commandDefinitions.itemById(cmd_id)
    if cmd_def:
        cmd_def.execute()


def _insert(file_id: str) -> None:
    _, ui = fh.app_ui()
    design = fh.active_design()
    if design is None:
        ui.messageBox("Open a design first.", "Gusset - COTS Library")
        return
    intent = getattr(adsk.fusion, "DesignIntentTypes", None)
    if intent is not None and getattr(design, "designIntent", None) == intent.PartDesignIntentType:
        # Fusion's Part designs hold exactly one component, so nothing can be inserted into them
        _log.info("Insert refused: '%s' is a Part design", design.parentDocument.name)
        ui.messageBox("This file is a Part design - Fusion only lets a Part hold one component, so COTS parts "
                      "can't be inserted here.\n\nOpen your assembly (or make a new design and choose "
                      "Assembly) and click the part again.", "Gusset - COTS Library")
        _send("status", {"text": "Open an assembly to insert parts"})
        return
    item = next((i for i in catalog() if i.file_id == file_id), None)
    _send("status", {"text": f"Inserting {item.title if item else 'part'}..."})
    try:
        started = time.time()
        occ, linked, data_file = cl.insert(file_id, design.activeComponent, item.category if item else "",
                                           library_project(), item.vendor if item else "",
                                           item.file_name if item else "")
        real_id = getattr(data_file, "id", "")
        if item is not None and cl.is_cloud_id(real_id) and real_id != item.file_id:
            _log.info("Fixed the saved id for %s", item.file_name)      # e.g. a temporary id from a batch
            item.file_id = real_id
            _save_catalog()
            _send_catalog()
        _count_use(item.file_id if item else file_id)
        _send("status", {"text": f"Inserted {occ.name} ({'linked' if linked else 'copy'}, "
                                 f"{time.time() - started:.1f}s) - click where it goes"})
        from . import cots_place
        cots_place.start_placing(occ, design)
    except fb.FeatureError as exc:
        ui.messageBox(str(exc), "Gusset - COTS Library")
        _send("status", {"text": ""})
    except Exception:
        fh.report_error("COTS Library: inserting a part")
        _send("status", {"text": ""})


# ---------------------------------------------------------------------------
# Thumbnails: ask Fusion, then poll from a small thread that pokes the main thread
# ---------------------------------------------------------------------------
def _send_cached_thumbs() -> None:
    for item in catalog():
        name = cc.thumb_file_name(item.file_id)
        if os.path.exists(os.path.join(THUMB_DIR, name)):
            _send_thumb(item.file_id, name)


def _thumb_ready(file_id: str, name: str) -> None:
    for item in _catalog:
        if item.file_id == file_id:
            item.thumb = name
    _send_thumb(file_id, name)


def _start_thumbs(items: List[cc.CatalogItem]) -> None:
    global _fetcher, _poll_thread
    if _fetcher is None:
        _fetcher = cl.ThumbnailFetcher(THUMB_DIR, _thumb_ready, _thumb_failed)
    if not _fetcher.request(items):
        return
    if _poll_thread is None or not _poll_thread.is_alive():
        _stop_polling.clear()
        _poll_thread = threading.Thread(target=_poll_loop, daemon=True)
        _poll_thread.start()


def _poll_loop() -> None:
    app = adsk.core.Application.get()
    deadline = time.time() + 300
    while not _stop_polling.is_set() and time.time() < deadline:
        time.sleep(0.5)
        app.fireCustomEvent(THUMB_EVENT, "")


def _on_thumb_poll(args) -> None:
    if _fetcher is None:
        return
    left = _fetcher.poll()
    if left == 0:
        _stop_polling.set()
        _save_catalog()
    elif len(_fetcher.pending) < 10:
        _fetcher.request(catalog())        # keep a few in flight until all are cached


# ---------------------------------------------------------------------------
# Toolbar
# ---------------------------------------------------------------------------
def start() -> None:
    global _thumb_event
    app, _ = fh.app_ui()
    try:
        app.unregisterCustomEvent(THUMB_EVENT)
    except Exception:
        pass
    _thumb_event = app.registerCustomEvent(THUMB_EVENT)
    _thumb_event.add(fh.make_handler(adsk.core.CustomEventHandler, _on_thumb_poll, "COTS thumbnails"))
    fh.add_button(CMD_ID, CMD_NAME, CMD_TOOLTIP, ICON_DIR, _on_created, config.PANEL_COTS_ID,
                  config.PANEL_COTS_NAME)


def stop() -> None:
    _stop_polling.set()
    try:
        app, _ = fh.app_ui()
        app.unregisterCustomEvent(THUMB_EVENT)
        pal = _palette()
        if pal:
            pal.deleteMe()
    except Exception:
        pass
    fh.release_handlers(HANDLER_GROUP)
    fh.remove_button(CMD_ID, config.PANEL_COTS_ID)


def _on_created(args: adsk.core.CommandCreatedEventArgs) -> None:
    try:
        args.command.isAutoExecute = True          # no dialog - just open the panel
    except Exception:
        pass
    args.command.execute.add(fh.make_handler(adsk.core.CommandEventHandler, lambda a: _show(), "COTS: show panel",
                                             "cots_button"))
