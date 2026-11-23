"""
dialogs.py - Gusset's own message window (a small floating Fusion palette):

    show_error(report)    "Gusset couldn't finish inserting a part" + one plain
                          sentence + what to try, with the traceback folded away
                          under "Technical details"
    show_update(release)  "Gusset 0.9.4 is ready" + what's new + Update now / Later / Skip

If the window can't open (or its page doesn't answer within a few seconds),
Gusset falls back to an ordinary Fusion message box with the same short text -
never a wall of code.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import webbrowser
from typing import List, Optional

import adsk.core

from .. import config
from . import error_core as ec
from . import log as gslog
from . import settings

_log = gslog.get_logger("dialogs")
PALETTE_ID = "Gusset_Dialog"
HTML_PATH = os.path.join(config.ADDIN_DIR, "resources", "dialog", "index.html")
FALLBACK_EVENT = "Gusset_DialogFallback"
READY_TIMEOUT_S = 6

_queue: List[tuple] = []         # (action, payload) waiting for the page
_ready = False
_handlers: list = []
_pending_update: dict = {}
_current_error: Optional[ec.ErrorReport] = None
_shown_ids: set = set()


def _ui():
    return adsk.core.Application.get().userInterface


def open_folder(path: str) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as exc:
        _log.warning("Couldn't open %s: %s", path, exc)
        _ui().messageBox(f"The folder is:\n{path}", "Gusset")


# ---------------------------------------------------------------------------
def _palette(create: bool = True):
    global _ready
    ui = _ui()
    pal = ui.palettes.itemById(PALETTE_ID)
    if pal is None and create:
        _ready = False
        pal = ui.palettes.add(PALETTE_ID, "Gusset", HTML_PATH.replace("\\", "/"), False, True, True, 520, 440, True)
        pal.dockingState = adsk.core.PaletteDockingStates.PaletteDockStateFloating

        class _Html(adsk.core.HTMLEventHandler):
            def notify(self, args):
                try:
                    _on_html(adsk.core.HTMLEventArgs.cast(args))
                except Exception as exc:              # never let the error window raise its own error
                    _log.error("Dialog event failed: %s", exc)

        handler = _Html()
        pal.incomingFromHTML.add(handler)
        _handlers.append(handler)
        _log.debug("Dialog window created")
    return pal


def _send(action: str, payload: dict) -> None:
    pal = _palette()
    pal.isVisible = True
    if _ready:
        pal.sendInfoToHTML(action, json.dumps(payload))
    else:
        _queue.append((action, payload))


def _on_html(args) -> None:
    global _ready
    args.returnData = "OK"
    action = args.action
    if action == "response":
        return
    try:
        data = json.loads(args.data or "{}")
    except ValueError:
        data = {}
    pal = _palette(create=False)
    if action == "ready":
        _ready = True
        _shown_ids.add(data.get("id", "page"))
        while _queue and pal:
            a, p = _queue.pop(0)
            pal.sendInfoToHTML(a, json.dumps(p))
    elif action == "shown":
        _shown_ids.add(str(data.get("id", "")))
    elif action == "close":
        if pal:
            pal.isVisible = False
    elif action == "openLog":
        open_folder(os.path.dirname(gslog.log_file_path()))
    elif action == "report" and _current_error is not None:
        webbrowser.open(ec.issue_url(config.UPDATE_REPO, _current_error, config.VERSION))
    elif action == "update":
        _start_install()
    elif action == "later":
        _log.info("Update postponed")
        if pal:
            pal.isVisible = False
    elif action == "skip":
        settings.save_state(config.ADDIN_DIR, skip_version=_pending_update.get("version", ""))
        _log.info("Skipping version %s", _pending_update.get("version"))
        if pal:
            pal.isVisible = False


# ---------------------------------------------------------------------------
# Fallback: if the page never says it's showing, use a plain message box instead
# ---------------------------------------------------------------------------
_fallback_text: dict = {}
_fallback_event = None


def _arm_fallback(msg_id: str, title: str, text: str) -> None:
    global _fallback_event
    app = adsk.core.Application.get()
    if _fallback_event is None:
        try:
            app.unregisterCustomEvent(FALLBACK_EVENT)
        except Exception:
            pass
        _fallback_event = app.registerCustomEvent(FALLBACK_EVENT)

        class _Fallback(adsk.core.CustomEventHandler):
            def notify(self, args):
                mid = adsk.core.CustomEventArgs.cast(args).additionalInfo
                if mid in _shown_ids or mid not in _fallback_text:
                    return
                t, body = _fallback_text.pop(mid)
                _log.warning("Dialog window didn't open - using a message box")
                _ui().messageBox(body, t)

        handler = _Fallback()
        _fallback_event.add(handler)
        _handlers.append(handler)
    _fallback_text[msg_id] = (title, text)
    threading.Timer(READY_TIMEOUT_S, lambda: app.fireCustomEvent(FALLBACK_EVENT, msg_id)).start()


def _message_box(title: str, text: str) -> None:
    try:
        _ui().messageBox(text, title)
    except Exception:
        print(title, text)


# ---------------------------------------------------------------------------
def show_error(report: ec.ErrorReport) -> None:
    global _current_error
    _current_error = report
    msg_id = f"e{id(report)}"
    short = (f"{report.title}.\n\n{report.summary}\n\n{report.hint}\n\n"
             f"Details are in the log:\n{ec.scrub(gslog.log_file_path())}")
    try:
        _send("error", {"id": msg_id, "title": report.title, "summary": report.summary, "hint": report.hint,
                        "details": report.details, "tool": report.tool, "version": config.VERSION,
                        "copy": ec.plain_text(report, config.VERSION),
                        "canReport": bool(config.UPDATE_REPO and "OWNER" not in config.UPDATE_REPO)})
        _arm_fallback(msg_id, "Gusset", short)
    except Exception as exc:
        _log.warning("Couldn't open the error window (%s)", exc)
        _message_box("Gusset", short)


def show_update(release: dict) -> None:
    _pending_update.clear()
    _pending_update.update(release)
    msg_id = f"u{release.get('version')}"
    try:
        _send("update", {"id": msg_id, "version": release["version"], "current": config.VERSION,
                         "notes": release.get("notes", []), "released": release.get("released", "")})
        _arm_fallback(msg_id, "Gusset update", f"Gusset {release['version']} is ready (you have {config.VERSION}).\n\n"
                      "Open GUSSET > Settings and click Update now.")
    except Exception as exc:
        _log.warning("Couldn't open the update window (%s)", exc)


def _start_install() -> None:
    from . import updater
    if not _pending_update:
        return
    _send("installing", {"version": _pending_update["version"]})

    def done(result: dict) -> None:
        if result.get("ok"):
            _send("installed", {"version": result["version"], "seconds": result.get("seconds")})
        else:
            report = ec.explain("Updates: installing the update", None, result.get("error", ""))
            report.summary = f"The update didn't install: {result.get('error', 'unknown problem')}."
            report.hint = "Nothing was changed. Try again later from GUSSET > Settings."
            _send("installFailed", {"summary": report.summary, "hint": report.hint})

    updater.install(dict(_pending_update), done)


def stop() -> None:
    global _fallback_event
    try:
        pal = _ui().palettes.itemById(PALETTE_ID)
        if pal:
            pal.deleteMe()
        if _fallback_event is not None:
            adsk.core.Application.get().unregisterCustomEvent(FALLBACK_EVENT)
            _fallback_event = None
    except Exception:
        pass
    _handlers.clear()
