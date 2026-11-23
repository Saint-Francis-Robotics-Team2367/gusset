"""Tests for fab export planning and the export log."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from lib import bom_core as bc  # noqa: E402
from lib import fab_core as fc  # noqa: E402
import test_bom_core as tb  # noqa: E402

CFG, asm, part = tb.CFG, tb.asm, tb.part


def bot():
    rows = []
    for key, pn, desc, proc, mat in [
        ("plate", "27-DRV-104", "omni mounting plate", "X-Carve", "Aluminum 6061"),
        ("acrylic", "27-ELC-101", "battery cover", "Laser", "Acrylic"),
        ("guide", "27-INT-102", "note guide", "3D Print", "PLA"),
        ("shaft", "27-GRB-104", "Output Shaft", "Lathe", "Steel 4140"),
        ("block", "27-ARM-103", "bearing block", "Mill", "Aluminum 6061"),
        ("bend", "27-FRM-105", "bent bracket", "Outsourced", "Aluminum"),
        ("new", "", "omni shaft", "TBD", ""),
    ]:
        p = part(key, f"{pn} {desc}".strip(), pn=pn or desc)
        p.material = mat
        rows.append(p)
    root = asm("root", "27-DRV-100 Robot", rows + [rows[0]], pn="27-DRV-100")
    return root, {r.key: r.process for r in []}


class FabPlanTests(unittest.TestCase):
    def setUp(self):
        root, _ = bot()
        procs = {"plate": "X-Carve", "acrylic": "Laser", "guide": "3D Print", "shaft": "Lathe",
                 "block": "Mill", "bend": "Outsourced"}
        self.bom = bc.build_bom(root, CFG, processes=procs)
        self.items = {i.key: i for i in fc.plan(self.bom.flat, fc.FabOptions())}

    def test_outputs_per_process(self):
        it = self.items
        self.assertEqual((it["plate"].output, it["plate"].fmt), (fc.OUT_FLAT, "svg"))
        self.assertEqual((it["acrylic"].output, it["acrylic"].fmt), (fc.OUT_FLAT, "svg"))
        self.assertEqual((it["guide"].output, it["guide"].fmt, it["guide"].folder), (fc.OUT_PRINT, "3mf", "3D Print"))
        self.assertEqual((it["shaft"].output, it["shaft"].fmt), (fc.OUT_LATHE, "pdf"))
        self.assertIn("Fusion CAM", it["block"].status)
        self.assertFalse(it["bend"].will_export)
        self.assertIn("set it in Export BOM", it["new"].status)

    def test_names_and_stock_folders(self):
        plate = self.items["plate"]
        self.assertEqual(plate.file_name, "27-DRV-104 omni mounting plate - qty 2.svg")
        fc.set_thickness(plate, 6.35, fc.FabOptions())
        self.assertEqual(plate.folder, "X-Carve/Aluminum 6061 1-4 in")
        self.assertEqual(plate.rel_path, "X-Carve/Aluminum 6061 1-4 in/27-DRV-104 omni mounting plate - qty 2.svg")

    def test_dxf_names_carry_units(self):
        items = {i.key: i for i in fc.plan(self.bom.flat, fc.FabOptions(xcarve_format="dxf"))}
        self.assertTrue(items["plate"].file_name.endswith(" (in).dxf"))

    def test_only_new_and_log(self):
        log = fc.record({}, [self.items["plate"]], when="2026-11-04")
        self.assertEqual(log["27-DRV-104"]["process"], "X-Carve")
        items = {i.key: i for i in fc.plan(self.bom.flat, fc.FabOptions(only_new=True), log)}
        self.assertIn("already exported 2026-11-04", items["plate"].status)
        self.assertTrue(items["shaft"].will_export)

    def test_log_round_trip_and_merge(self):
        import json
        a = {"27-A-101": {"date": "2026-11-01"}}
        b = {"27-A-101": {"date": "2026-11-04"}, "27-A-102": {"date": "2026-11-02"}}
        merged = fc.merge_logs(a, b)
        self.assertEqual(merged["27-A-101"]["date"], "2026-11-04")
        self.assertEqual(fc.parse_log(json.dumps(merged)), merged)
        self.assertEqual(fc.parse_log("not json"), {})

    def test_bom_status_from_log(self):
        root, _ = bot()
        procs = {"plate": "X-Carve", "guide": "3D Print"}
        log = {"27-DRV-104": {"date": "2026-11-04"}, "27-INT-102": {"date": "2026-11-04"}}
        flat = {r.key: r for r in bc.build_bom(root, CFG, processes=procs, fab_log=log).flat}
        self.assertEqual(flat["plate"].status, "Ready to Cut")
        self.assertEqual(flat["guide"].status, "Ready to Print")
        self.assertEqual(flat["shaft"].status, "Designed")

    def test_only_some_machines(self):
        items = {i.key: i for i in fc.plan(self.bom.flat, fc.FabOptions(processes={"Lathe"}))}
        self.assertTrue(items["shaft"].will_export)
        self.assertFalse(items["plate"].will_export)
        self.assertEqual(items["plate"].status, "X-Carve not ticked")
        self.assertFalse(items["guide"].will_export)
        self.assertIn("Fusion CAM", items["block"].status)      # Mill keeps its own reason

    def test_one_part_only(self):
        keys = {"plate", "acrylic", "guide"}
        items = {i.key: i for i in fc.plan(self.bom.flat, fc.FabOptions(processes={"Lathe", "3D Print"}, excluded=keys))}
        self.assertEqual([k for k, i in items.items() if i.will_export], ["shaft"])
        self.assertEqual(items["guide"].status, "unticked in the list")
        self.assertTrue(fc.selectable(items["guide"]))            # can be ticked back on
        self.assertFalse(fc.selectable(items["plate"]))           # its machine isn't ticked
        self.assertFalse(fc.selectable(items["block"]))

    def test_default_output(self):
        self.assertEqual(fc.default_output_for("Lathe"), fc.OUT_LATHE)
        self.assertEqual(fc.default_output_for("Laser"), fc.OUT_FLAT)
        self.assertEqual(fc.default_output_for("3D Print"), fc.OUT_PRINT)

    def test_cut_list(self):
        rows = fc.cut_list_rows(list(self.items.values()))
        self.assertEqual(rows[0][0], "Part #")
        self.assertEqual(rows[1][3], "X-Carve")       # sorted by process
        self.assertEqual(len(rows), len(self.items) + 1)


if __name__ == "__main__":
    unittest.main()
