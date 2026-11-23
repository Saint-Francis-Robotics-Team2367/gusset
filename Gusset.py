"""
Gusset - FRC tools for Autodesk Fusion.
Fusion calls run() when the add-in starts and stop() when it stops.

Start-up order:
  1. logging (detail level = the "Detailed logs" switch in Settings)
  2. a check that no OTHER copy of Gusset is already running (see _claim_instance)
  3. the toolbar buttons
  4. a background update check (if due) - never slows Fusion down
"""

import os
import sys
import traceback
import types

import adsk.core

from . import commands, config
from .lib import fusion_helpers as fh
from .lib import log as pclog

_log = pclog.get_logger("main")
_INSTANCE_KEY = "gusset_running_instance"
_started = False


def _in_fusion_addins_folder(path: str) -> bool:
    """True for Fusion's own add-ins folder (where the installer puts Gusset)."""
    return "/api/addins/" in (path.replace("\\", "/").lower() + "/")


def _claim_instance() -> bool:
    """
    Only one Gusset may run (two copies would fight over the same buttons). That
    happens after the installer moves an older 'FRC Plugins' copy into Fusion's
    add-ins folder while Fusion still remembers the old one. Rule: the add-ins
    folder copy wins; an old copy stands aside.
    """
    other = sys.modules.get(_INSTANCE_KEY)
    if other is not None and getattr(other, "folder", None) != config.ADDIN_DIR:
        # (runs before logging starts - logging is shared, so print() is used here)
        if _in_fusion_addins_folder(config.ADDIN_DIR) and not _in_fusion_addins_folder(other.folder):
            print(f"[Gusset] Stopping the older copy in {other.folder} - the installed copy takes over")
            try:
                other.stop()
            except Exception as exc:
                print(f"[Gusset] Couldn't stop the older copy: {exc}")
        else:
            print(f"[Gusset] Another copy is already running from {other.folder} - "
                  f"this copy ({config.ADDIN_DIR}) stays off")
            return False
    marker = types.ModuleType(_INSTANCE_KEY)
    marker.folder = config.ADDIN_DIR
    marker.stop = lambda: stop({})
    sys.modules[_INSTANCE_KEY] = marker
    return True


def run(context):
    global _started
    try:
        if not _claim_instance():                     # before logging: a second copy must not take the log over
            return
        from .lib import settings
        debug = bool(settings.read_settings(config.ADDIN_DIR).get("debug_logs", config.DEBUG))
        pclog.setup(os.path.join(config.ADDIN_DIR, "logs"), debug=debug)
        _log.info("Gusset %s starting from %s", config.VERSION, config.ADDIN_DIR)
        commands.start()
        _started = True
        _log.info("Gusset ready - look for the GUSSET tab in the Design workspace")
        from .lib import updater
        updater.start()
        updater.startup_check()
    except Exception:
        _fatal("starting")


def stop(context):
    global _started
    if not _started:
        return
    try:
        _log.info("Gusset stopping")
        from .lib import dialogs, updater
        updater.stop()
        dialogs.stop()
        commands.stop()
        fh.release_all_handlers()
        marker = sys.modules.get(_INSTANCE_KEY)
        if marker is not None and getattr(marker, "folder", None) == config.ADDIN_DIR:
            del sys.modules[_INSTANCE_KEY]
        _started = False
    except Exception:
        _fatal("stopping")
    finally:
        pclog.shutdown()


def _fatal(doing: str) -> None:
    """Gusset itself failed. Log everything; show one short, readable message."""
    details = traceback.format_exc()
    try:
        _log.error("Gusset failed while %s:\n%s", doing, details)
    except Exception:
        pass
    try:
        adsk.core.Application.get().userInterface.messageBox(
            f"Gusset {config.VERSION} couldn't finish {doing}, so some GUSSET buttons may be missing.\n\n"
            "Quit Fusion and open it again. If it happens again, send a mentor the log file:\n"
            f"{os.path.join(config.ADDIN_DIR, 'logs', 'gusset.log')}", "Gusset")
    except Exception:
        print(details)
