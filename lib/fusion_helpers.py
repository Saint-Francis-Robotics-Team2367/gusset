"""
fusion_helpers.py - shared Fusion plumbing: event handlers, error reporting,
and the GUSSET toolbar tab. Every tool uses these so they behave the same.
"""

from __future__ import annotations

import os
import time
import traceback
from typing import Callable, Dict, List

import adsk.core
import adsk.fusion

from .. import config
from . import log as pclog

_log = pclog.get_logger("fusion")

# Fusion only keeps a WEAK reference to event handlers. If Python forgets a
# handler it silently stops firing, so we keep them here, grouped by owner.
_handlers: Dict[str, List[object]] = {}

WORKSPACE_ID = "FusionSolidEnvironment"  # the Design workspace


def app_ui():
    app = adsk.core.Application.get()
    return app, app.userInterface


def active_design():
    """The open Design, or None (e.g. if a drawing is active)."""
    app, _ = app_ui()
    return adsk.fusion.Design.cast(app.activeProduct)


def fire_until_handled(event_id: str, still_waiting, label: str, tries: int = 90) -> bool:
    """
    Fire a custom event, and keep re-firing it once a second (from a background
    thread) until still_waiting() is False. Returns the first fire's result, for
    the log only.

    Why: inside a command dialog, Fusion's fireCustomEvent often answers False but
    delivers the event anyway a moment later (seen in 0.12 placing bearings and in
    0.13 Add to Library). Trusting that False threw the waiting job away. Never
    trust it - keep the job, and make the handler safe to run more than once.
    """
    import threading
    app = adsk.core.Application.get()
    first = app.fireCustomEvent(event_id, "")
    _log.info("%s: start signal sent (Fusion said %s)", label, first)

    def nudge():
        for _ in range(tries):
            time.sleep(1.0)
            try:
                if not still_waiting():
                    return
                app.fireCustomEvent(event_id, "")
            except Exception:
                return
        _log.warning("%s: still waiting after %ds - giving up", label, tries)

    threading.Thread(target=nudge, daemon=True, name=f"nudge {event_id}").start()
    return bool(first)


def fusion_is_idle() -> str:
    """'' when no command dialog is open; otherwise why not (for the log)."""
    try:
        active = app_ui()[1].activeCommand
    except Exception:
        return ""
    return "" if not active or active == "SelectCommand" else f"{active} is still open"


def run_command(cmd_id: str) -> bool:
    """Open another Gusset (or Fusion) command by id; False if it isn't there."""
    _, ui = app_ui()
    cmd_def = ui.commandDefinitions.itemById(cmd_id)
    if cmd_def is None:
        _log.debug("No command %s", cmd_id)
        return False
    cmd_def.execute()
    return True


def safe(getter, default=None):
    """getter() or default if Fusion raises (stale objects, properties some entities don't have)."""
    try:
        return getter()
    except Exception:
        return default


def safe_text(text: str) -> str:
    """
    Make text safe for Fusion's formattedText. Fusion understands simple tags
    like <b> but NOT HTML codes like &nbsp; or &#9656; (they show up as raw
    text, seen on macOS). So: no html.escape, and no entities. Angle brackets
    in names are swapped for look-alikes so they can't be read as tags.
    """
    return str(text or "").replace("<", "\u2039").replace(">", "\u203a")


def report_error(context: str, show_dialog: bool = True) -> None:
    """
    Log the current exception in full, then show the student Gusset's error window:
    one plain sentence about what went wrong and what to try, with the traceback
    folded away under "Technical details" (see lib/error_core.py for the wording).
    context = "Tool: what it was doing", e.g. "COTS Library: inserting a part".
    """
    import sys
    details = traceback.format_exc()
    _log.error("%s failed:\n%s", context, details)
    if not show_dialog:
        return
    try:
        from . import dialogs, error_core
        exc = sys.exc_info()[1]
        dialogs.show_error(error_core.explain(context, exc, details))
    except Exception as exc:                          # last resort: a short message, still no code dump
        _log.error("Couldn't show the error window: %s", exc)
        try:
            _, ui = app_ui()
            ui.messageBox(f"Gusset couldn't finish: {context}.\n\nTry again. If it keeps happening, "
                          f"send a mentor the log:\n{pclog.log_file_path()}", "Gusset")
        except Exception:
            pass


def all_inputs(args):
    """
    ALL of a dialog's inputs, from any event's args.

    Careful: in an inputChanged event Fusion's `args.inputs` is only the
    collection the changed input lives in - so for a checkbox inside a group,
    inputs outside the group are invisible (itemById returns None). That broke
    Fab Export's machine checkboxes. The command's own commandInputs finds
    everything, groups included.
    """
    try:
        cmd = adsk.core.Command.cast(args.firingEvent.sender)
        if cmd:
            return cmd.commandInputs
    except Exception:
        pass
    try:
        return args.input.parentCommand.commandInputs
    except Exception:
        return args.inputs


def make_handler(base_class, callback: Callable, label: str, group: str = "global"):
    """
    Wrap a plain Python function as a Fusion event handler.

        cmd.execute.add(make_handler(adsk.core.CommandEventHandler, on_execute, "Name Parts: OK"))

    Any exception inside the callback is logged and shown, instead of
    disappearing silently (Fusion swallows handler errors otherwise).
    """

    class _Handler(base_class):
        def __init__(self):
            super().__init__()

        def notify(self, args):
            _log.debug("event -> %s", label)
            try:
                callback(args)
            except Exception:
                report_error(label)

    handler = _Handler()
    _handlers.setdefault(group, []).append(handler)
    return handler


def release_handlers(group: str) -> None:
    """Forget handlers for a dialog that has closed."""
    count = len(_handlers.pop(group, []))
    _log.debug("Released %d handler(s) in group %r", count, group)


def release_all_handlers() -> None:
    _handlers.clear()


# ---------------------------------------------------------------------------
# Toolbar: one GUSSET tab in the Design workspace, one panel per area
# ---------------------------------------------------------------------------
def get_panel(panel_id: str, panel_name: str):
    _, ui = app_ui()
    workspace = ui.workspaces.itemById(WORKSPACE_ID)
    tab = workspace.toolbarTabs.itemById(config.TAB_ID)
    if not tab:
        _log.debug("Creating toolbar tab %s", config.TAB_ID)
        tab = workspace.toolbarTabs.add(config.TAB_ID, config.TAB_NAME)
    panel = tab.toolbarPanels.itemById(panel_id)
    if not panel:
        _log.debug("Creating toolbar panel %s", panel_id)
        panel = tab.toolbarPanels.add(panel_id, panel_name)
    return panel


def add_button(cmd_id: str, name: str, tooltip: str, icon_folder: str,
               on_created: Callable, panel_id: str, panel_name: str, promote: bool = True):
    """Create (or recreate) a toolbar button that opens a command."""
    _, ui = app_ui()
    old = ui.commandDefinitions.itemById(cmd_id)
    if old:
        old.deleteMe()  # left over from a crash or a reload

    if not os.path.isdir(icon_folder):
        _log.warning("Icon folder missing for %s: %s", cmd_id, icon_folder)
        icon_folder = ""

    cmd_def = ui.commandDefinitions.addButtonDefinition(cmd_id, name, tooltip, icon_folder)
    cmd_def.commandCreated.add(
        make_handler(adsk.core.CommandCreatedEventHandler, on_created, f"{name}: open")
    )
    panel = get_panel(panel_id, panel_name)
    control = panel.controls.itemById(cmd_id) or panel.controls.addCommand(cmd_def)
    control.isPromoted = promote
    control.isPromotedByDefault = promote
    _log.info("Added button: %s", name)
    return cmd_def


def remove_button(cmd_id: str, panel_id: str) -> None:
    _, ui = app_ui()
    try:
        workspace = ui.workspaces.itemById(WORKSPACE_ID)
        tab = workspace.toolbarTabs.itemById(config.TAB_ID) if workspace else None
        panel = tab.toolbarPanels.itemById(panel_id) if tab else None
        control = panel.controls.itemById(cmd_id) if panel else None
        if control:
            control.deleteMe()
        cmd_def = ui.commandDefinitions.itemById(cmd_id)
        if cmd_def:
            cmd_def.deleteMe()
        _log.debug("Removed button %s", cmd_id)
    except Exception:
        report_error(f"removing button {cmd_id}", show_dialog=False)


def cleanup_toolbar() -> None:
    """Delete our panels and tab once they're empty."""
    _, ui = app_ui()
    try:
        workspace = ui.workspaces.itemById(WORKSPACE_ID)
        tab = workspace.toolbarTabs.itemById(config.TAB_ID) if workspace else None
        if not tab:
            return
        for i in reversed(range(tab.toolbarPanels.count)):
            panel = tab.toolbarPanels.item(i)
            if panel.controls.count == 0:
                panel.deleteMe()
        if tab.toolbarPanels.count == 0:
            tab.deleteMe()
        _log.debug("Toolbar cleaned up")
    except Exception:
        report_error("cleaning up the toolbar", show_dialog=False)
