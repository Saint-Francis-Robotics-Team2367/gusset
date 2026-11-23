"""
Settings - GUSSET > Naming > Settings opens Gusset's settings window (a Fusion
palette, resources/settings_panel/index.html):

    top        Gusset version, update status, Check for updates / Update now
    This computer   personal switches (update checks, detailed logs), log folder,
                    Undo last update
    Team       the team's settings, read-only for students. A mentor clicks
               "Edit team settings", changes them, saves them ON THIS LAPTOP
               (a draft, used right away here), then Publish: Gusset copies the
               settings and opens team_settings.json on GitHub to paste them in.
               Every laptop picks them up at its next update check.
    Advanced   the less-common team settings as JSON (bearings, patterns, cutters...)
"""

from __future__ import annotations

import json
import os
import webbrowser

import adsk.core

from .. import config
from ..lib import dialogs
from ..lib import fusion_helpers as fh
from ..lib import log as pclog
from ..lib import settings
from ..lib import update_core as uc
from ..lib import updater

CMD_ID = "Gusset_Settings"
CMD_NAME = "Settings"
CMD_TOOLTIP = "Gusset's version, updates and the team's settings."
ICON_DIR = os.path.join(config.ADDIN_DIR, "resources", "settings")
PALETTE_ID = "Gusset_SettingsPanel"
HTML_PATH = os.path.join(config.ADDIN_DIR, "resources", "settings_panel", "index.html")
HANDLER_GROUP = "settings_cmd"
PALETTE_GROUP = "settings_panel"

_log = pclog.get_logger("settings_cmd")


def start() -> None:
    fh.add_button(CMD_ID, CMD_NAME, CMD_TOOLTIP, ICON_DIR, _on_created,
                  config.PANEL_NAMING_ID, config.PANEL_NAMING_NAME, promote=False)


def stop() -> None:
    try:
        pal = fh.app_ui()[1].palettes.itemById(PALETTE_ID)
        if pal:
            pal.deleteMe()
    except Exception:
        pass
    fh.release_handlers(PALETTE_GROUP)
    fh.remove_button(CMD_ID, config.PANEL_NAMING_ID)


def _on_created(args: adsk.core.CommandCreatedEventArgs) -> None:
    try:
        args.command.isAutoExecute = True            # no dialog - just open the window
    except Exception:
        pass
    args.command.execute.add(fh.make_handler(adsk.core.CommandEventHandler, lambda a: _show(),
                                             "Settings: open window", HANDLER_GROUP))


# ---------------------------------------------------------------------------
def _palette():
    return fh.app_ui()[1].palettes.itemById(PALETTE_ID)


def _send(action: str, payload) -> None:
    pal = _palette()
    if pal:
        pal.sendInfoToHTML(action, json.dumps(payload))


def _show() -> None:
    _, ui = fh.app_ui()
    pal = _palette()
    if pal is None:
        pal = ui.palettes.add(PALETTE_ID, f"Gusset {config.VERSION} Settings", HTML_PATH.replace("\\", "/"),
                              True, True, True, 620, 700, True)
        pal.dockingState = adsk.core.PaletteDockingStates.PaletteDockStateFloating
        pal.incomingFromHTML.add(fh.make_handler(adsk.core.HTMLEventHandler, _on_html, "Settings window",
                                                 PALETTE_GROUP))
        _log.info("Settings window opened")
    else:
        pal.isVisible = True
        _send("state", _state())


def _state() -> dict:
    """Everything the window shows."""
    merged = settings.read_settings(config.ADDIN_DIR)
    layers = settings.team_layers(config.ADDIN_DIR)
    status = updater.status()
    latest = status.get("latest") or {}
    team = settings.effective_team_settings(config.ADDIN_DIR)
    team.setdefault("lighten_defaults", settings.read_lighten_defaults(config.ADDIN_DIR))   # show the built-ins
    return {
        "version": config.VERSION,
        "install_dir": config.ADDIN_DIR,
        "log_file": pclog.log_file_path(),
        "update": {**status, "newer": bool(latest and uc.is_newer(latest.get("version", ""), config.VERSION))},
        "personal": {k: merged.get(k) for k in settings.PERSONAL_KEYS},
        "team": team,
        "team_source": "draft" if layers["draft"] else ("github" if layers["team"] else "this computer"),
        "has_draft": bool(layers["draft"]),
        "edit_url": (f"https://github.com/{config.UPDATE_REPO}/edit/{config.UPDATE_BRANCH}/team_settings.json"
                     if uc.repo_is_set(config.UPDATE_REPO) else ""),
        "repo_url": f"https://github.com/{config.UPDATE_REPO}" if uc.repo_is_set(config.UPDATE_REPO) else "",
    }


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
    _log.debug("settings window -> %s", action)

    if action == "ready":
        _send("state", _state())
    elif action == "checkUpdates":
        def done(result):
            _send("checkResult", {"ok": result.get("ok", False), "error": result.get("error", ""),
                                  "newer": result.get("newer", False), "release": result.get("release") or {},
                                  "team_changed": result.get("team_changed", False)})
            _send("state", _state())
        if not updater.check(manual=True, on_done=done):
            _send("state", _state())
    elif action == "installUpdate":
        latest = updater.status().get("latest") or {}
        if latest:
            dialogs.show_update(latest)
    elif action == "savePersonal":
        values = {k: bool(v) for k, v in data.items() if k in settings.PERSONAL_KEYS}
        settings.update_settings(config.ADDIN_DIR, **values)
        _send("saved", {"what": "personal", "note": "Saved. Detailed logs change the next time Fusion starts."
                        if "debug_logs" in values else "Saved."})
    elif action == "saveTeam":
        team = data.get("team")
        problems = settings.validate_team(team)
        if problems:
            _send("teamProblems", {"problems": problems})
            return
        settings.save_team_draft(config.ADDIN_DIR, team)
        _send("saved", {"what": "team", "note": "Saved on this computer. Click Publish so every laptop gets it."})
        _send("state", _state())
    elif action == "discardDraft":
        settings.discard_team_draft(config.ADDIN_DIR)
        _send("state", _state())
    elif action == "publish":
        url = _state()["edit_url"]
        if url:
            webbrowser.open(url)
    elif action == "openUrl":
        url = str(data.get("url", ""))
        if url.startswith("https://github.com/"):
            webbrowser.open(url)
    elif action == "openLog":
        dialogs.open_folder(os.path.dirname(pclog.log_file_path()))
    elif action == "undoUpdate":
        _, ui = fh.app_ui()
        try:
            version = updater.undo_last_update()
            ui.messageBox(f"Gusset {version} is back. Quit Fusion and open it again to use it.", "Gusset")
        except ValueError as exc:
            ui.messageBox(f"Nothing to undo: {exc}.", "Gusset")
        _send("state", _state())
