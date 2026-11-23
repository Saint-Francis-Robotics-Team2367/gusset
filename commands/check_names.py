"""
Check Names - a read-only report of naming problems in the whole design.
Great right before a design review or before sending parts to the X-Carve.
Nothing in the design is changed. A CSV copy of the report is saved in logs/.
"""

from __future__ import annotations

import csv
import datetime
import os

import adsk.core

from .. import config
from ..lib import design_tree as dt
from ..lib import fusion_helpers as fh
from ..lib import log as pclog
from ..lib import naming_core as nc
from ..lib import settings
from ..lib import tip_box

CMD_ID = "Gusset_CheckNames"
CMD_NAME = "Check Names"
CMD_TOOLTIP = "List every part with a missing, duplicate or out-of-date part number. Changes nothing."
ICON_DIR = os.path.join(config.ADDIN_DIR, "resources", "check_names")
HANDLER_GROUP = "check_names_dialog"
MAX_ROWS_SHOWN = 200

_log = pclog.get_logger("check_names")


def start() -> None:
    fh.add_button(CMD_ID, CMD_NAME, CMD_TOOLTIP, ICON_DIR, _on_created,
                  config.PANEL_NAMING_ID, config.PANEL_NAMING_NAME)


def stop() -> None:
    fh.remove_button(CMD_ID, config.PANEL_NAMING_ID)


def _on_created(args: adsk.core.CommandCreatedEventArgs) -> None:
    _log.info("Check Names opened")
    cmd = args.command
    _, ui = fh.app_ui()
    design = fh.active_design()
    if not design:
        ui.messageBox("Open a Fusion design first, then try Check Names again.", "Gusset")
        return

    cfg = settings.load_config(config.ADDIN_DIR)
    nodes = dt.flatten([dt.root_node(design, dt.TreeContext(cfg))])
    issues = nc.check_design(nodes, cfg)
    csv_path = _save_csv(issues, design)

    counts = {sev: sum(1 for i in issues if i.severity == sev) for sev in ("error", "warn", "info")}
    _log.info("Checked %d components: %s", len(nodes), counts)
    for issue in issues:
        _log.info("  %-5s %s - %s", issue.severity.upper(), issue.name, issue.message)

    if not issues:
        body = f"<b>All {len(nodes)} components look good!</b> Nice work."
    else:
        lines = [
            f"Checked <b>{len(nodes)}</b> components: "
            f"<b>{counts['error']}</b> errors, <b>{counts['warn']}</b> warnings, {counts['info']} notes.<br>"
        ]
        for issue in issues[:MAX_ROWS_SHOWN]:
            lines.append(f"<b>{issue.severity.upper()}</b>  {fh.safe_text(issue.name)} "
                         f"\u2014 {fh.safe_text(issue.message)}")
        if len(issues) > MAX_ROWS_SHOWN:
            lines.append(f"<i>...and {len(issues) - MAX_ROWS_SHOWN} more in the CSV.</i>")
        if csv_path:
            lines.append(f"<br><i>Full report saved to: {fh.safe_text(csv_path)}</i>")
        body = "<br>".join(lines)

    try:
        cmd.setDialogInitialSize(640, 560)
    except Exception:
        pass
    cmd.okButtonText = "Done"
    tip_box.attach(cmd, CMD_ID)              # 'How to use this' (0.13)
    cmd.commandInputs.addTextBoxCommandInput("pc_report", "", body, 24, True)
    cmd.destroy.add(fh.make_handler(adsk.core.CommandEventHandler,
                                    lambda _a: fh.release_handlers(HANDLER_GROUP),
                                    "Check Names: close", HANDLER_GROUP))


def _save_csv(issues, design) -> str:
    """Write the report to logs/naming_report_<design>_<time>.csv. Returns the path or ''."""
    try:
        safe = nc.sanitize(design.rootComponent.name).replace(" ", "_") or "design"
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        folder = os.path.join(config.ADDIN_DIR, "logs")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"naming_report_{safe}_{stamp}.csv")
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["severity", "component", "problem"])
            for issue in issues:
                writer.writerow([issue.severity, issue.name, issue.message])
        _log.info("Report saved: %s", path)
        return path
    except Exception:
        fh.report_error("saving the CSV report", show_dialog=False)
        return ""
