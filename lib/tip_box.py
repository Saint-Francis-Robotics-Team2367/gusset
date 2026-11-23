"""
tip_box.py - puts lib/tips.py into Fusion dialogs (0.13).

    tip_box.attach(args.command, CMD_ID)   first thing in a command's created handler

adds a 'How to use this' group at the top (collapsed once a student collapses it -
remembered per command), and when the dialog opens fills in the hover tip of every
input, hides the old help boxes it replaces, and logs any input with no tip.
"""

from __future__ import annotations

import adsk.core

from .. import config
from . import fusion_helpers as fh
from . import log as gslog
from . import settings
from . import tips

_log = gslog.get_logger("tips")


def _ids(inputs, out=None):
    """Every input id in a dialog, inside groups and tabs too (not table cells)."""
    out = [] if out is None else out
    for i in range(inputs.count):
        item = inputs.item(i)
        out.append(item)
        group = adsk.core.GroupCommandInput.cast(item) or adsk.core.TabCommandInput.cast(item)
        if group:
            _ids(group.children, out)
    return out


def _collapsed() -> list:
    value = settings.load_state(config.ADDIN_DIR).get("howto_collapsed")
    return list(value) if isinstance(value, list) else []


def attach(cmd, cmd_id: str) -> None:
    """Call before adding any other input so the box is at the top. Never raises."""
    try:
        html = tips.how_to_html(cmd_id)
        if not html:
            _log.debug("No tips written for %s yet", cmd_id)
            return
        prefix = cmd_id.replace("Gusset_", "").lower()
        group = cmd.commandInputs.addGroupCommandInput(f"{prefix}_howto", "How to use this")
        group.isExpanded = cmd_id not in _collapsed()
        group.children.addTextBoxCommandInput(f"{prefix}_howto_text", "", html, tips.rows_for(cmd_id), True)
        group_id = group.id

        def on_activate(_args):
            _apply(cmd, cmd_id)

        def on_destroy(_args):
            try:
                g = adsk.core.GroupCommandInput.cast(cmd.commandInputs.itemById(group_id))
                if g is None:
                    return
                now = set(_collapsed())
                (now.discard if g.isExpanded else now.add)(cmd_id)
                settings.save_state(config.ADDIN_DIR, howto_collapsed=sorted(now))
            except Exception as exc:
                _log.debug("Couldn't remember the How-to box for %s: %s", cmd_id, exc)
            fh.release_handlers(f"tips_{cmd_id}")

        cmd.activate.add(fh.make_handler(adsk.core.CommandEventHandler, on_activate, f"{cmd_id}: tips",
                                         f"tips_{cmd_id}"))
        cmd.destroy.add(fh.make_handler(adsk.core.CommandEventHandler, on_destroy, f"{cmd_id}: tips done",
                                        f"tips_{cmd_id}"))
    except Exception:
        _log.exception("Couldn't add the How-to box to %s", cmd_id)


def _apply(cmd, cmd_id: str) -> None:
    """Hover tips for every input; hide the old help boxes; log gaps."""
    try:
        items = _ids(cmd.commandInputs)
        without = []
        for item in items:
            iid = item.id
            if iid.endswith("_help") and not iid.endswith("_lib_help"):
                item.isVisible = False                     # replaced by 'How to use this'
                continue
            tip, desc = tips.tip_for(cmd_id, iid)
            if tip:
                item.tooltip = tip
                if desc:
                    item.tooltipDescription = desc
            elif tips.needs_tip(iid):
                without.append(iid)
        if without:
            _log.warning("%s: no tip yet for %s", cmd_id, ", ".join(without))
        else:
            _log.debug("%s: tips on all %d inputs", cmd_id, len(items))
    except Exception:
        _log.exception("Couldn't add tips to %s", cmd_id)
