"""
All Gusset tools. To add a new tool: make a module with start() and stop(),
then add it to COMMANDS below. Future modules:
calculators, review_checklist, generators.
"""

from ..lib import fusion_helpers as fh
from ..lib import log as pclog
from . import (bearing_pocket, check_names, design_review, export_bom, export_face, export_part, fab_export,
               hole_pattern, lighten, name_parts, open_settings, quick_rib, tube_gen, shaft_spacer, belt_calc, linked_parts,
               cots_browser, cots_place, cots_add, library_check, cots_autoplace, robot_weight)

COMMANDS = [linked_parts, name_parts, check_names, open_settings, export_bom, export_face, export_part, fab_export,
            hole_pattern, bearing_pocket, quick_rib, lighten, tube_gen, shaft_spacer, belt_calc,
            cots_browser, cots_place, cots_add, library_check, cots_autoplace, robot_weight, design_review]

_log = pclog.get_logger("commands")


def start() -> None:
    for module in COMMANDS:
        try:
            module.start()
        except Exception:
            # One broken tool shouldn't stop the others from loading.
            fh.report_error(f"starting {module.__name__}")


def stop() -> None:
    for module in reversed(COMMANDS):
        try:
            module.stop()
        except Exception:
            fh.report_error(f"stopping {module.__name__}", show_dialog=False)
    fh.cleanup_toolbar()
    _log.info("All tools stopped")
