"""Tests for the design review checks, records and PDF report."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from lib import bom_core as bc  # noqa: E402
from lib import naming_core as nc  # noqa: E402
from lib import review_core as rc  # noqa: E402
import test_naming_core as tn  # noqa: E402

CFG, asm, linked, part = tn.CFG, tn.asm, tn.linked, tn.part


def robot():
    good = part("good", "27-DRV-101 Plate", pn="27-DRV-101")
    good.material, good.process = "Aluminum 6061", "X-Carve"
    steel = part("steel", "27-DRV-102 Rail", pn="27-DRV-102")
    steel.material, steel.process = "Steel", "Mill"
    unnamed = part("unnamed", "Component7")
    dup = part("dup", "27-DRV-101 Other", pn="27-DRV-101")
    dup.material = "PLA"
    mystery = linked("mys", "Spacer thing")
    mystery.cots_flag = True
    return asm("root", "27-DRV-100 Chassis", [good, steel, unnamed, dup, mystery], pn="27-DRV-100")


class ReviewTests(unittest.TestCase):
    def setUp(self):
        root = robot()
        bom = bc.build_bom(root, CFG)
        self.results = {r.check_id: r for r in rc.auto_checks(root, CFG, bom, out_of_date=["27-GRB-100 Gearbox"])}

    def test_statuses(self):
        r = self.results
        self.assertEqual(r["names"].status, rc.FAIL)
        self.assertIn("Component7", r["names"].items)
        self.assertEqual(r["duplicates"].status, rc.FAIL)
        self.assertEqual(r["material"].status, rc.WARN)
        self.assertIn("27-DRV-102 Rail", r["material"].items)
        self.assertEqual(r["process"].status, rc.WARN)
        self.assertEqual(r["vendor"].status, rc.WARN)
        self.assertEqual(r["links"].items, ["27-GRB-100 Gearbox"])
        self.assertEqual(r["overlap"].status, rc.INFO)      # not run

    def test_every_check_explains_itself(self):
        for r in self.results.values():
            self.assertTrue(r.why and r.fix, r.check_id)

    def test_failures_sort_first(self):
        root = robot()
        ordered = rc.auto_checks(root, CFG, bc.build_bom(root, CFG), interference=[("A", "B")])
        self.assertEqual(ordered[0].status, rc.FAIL)
        self.assertEqual(ordered[-1].status, rc.PASS)

    def test_clean_design_passes(self):
        p = part("p", "27-DRV-101 Plate", pn="27-DRV-101")
        p.material, p.process = "Aluminum 6061", "X-Carve"
        root = asm("root", "27-DRV-100 Chassis", [p], pn="27-DRV-100")
        results = rc.auto_checks(root, CFG, bc.build_bom(root, CFG), interference=[])
        self.assertTrue(all(r.status == rc.PASS for r in results), [(r.check_id, r.status) for r in results])

    def test_records_round_trip_and_cap(self):
        rec = rc.new_record("27-DRV-100 Chassis", "Mentor A", rc.DECISIONS[0], "Looks good",
                            list(self.results.values()), {rc.DEFAULT_CHECKLIST[0][0]: True}, "0.5.0", "2026-11-04")
        text = rc.add_record("", rec)
        back = rc.parse_records(text)
        self.assertEqual(back[0].reviewer, "Mentor A")
        self.assertEqual(back[0].auto["Every part has a team part number"], rc.FAIL)
        for _ in range(60):
            text = rc.add_record(text, rec)
        self.assertEqual(len(rc.parse_records(text)), 50)
        self.assertEqual(rc.parse_records("nonsense"), [])

    def test_pdf_report(self):
        rec = rc.new_record("27-DRV-100 Chassis", "Mentor A", rc.DECISIONS[2], "Fix the rail material. " * 20,
                            list(self.results.values()), {t: i % 2 == 0 for i, (t, _h) in enumerate(rc.DEFAULT_CHECKLIST)},
                            "0.5.0")
        path = rc.render_report(os.path.join(tempfile.mkdtemp(), "r.pdf"), rec, list(self.results.values()),
                                rc.DEFAULT_CHECKLIST)
        data = open(path, "rb").read()
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertIn(b"MENTOR CHECKLIST", data)


if __name__ == "__main__":
    unittest.main()


class LibraryCheckTests(unittest.TestCase):
    """0.12: bought parts modeled by hand instead of inserted from FRC_COTS."""

    def test_flags_hand_modeled_not_library_or_insides(self):
        from lib import cots_core as cc
        lib_neo = cc.CatalogItem("n", "REV-21-1653 NEO 2.0 Brushless Motor", "Motors", "REV",
                                 cc.CotsInfo(name="NEO 2.0 Brushless Motor", vendor="REV", vendor_pn="REV-21-1653"))
        from_library = linked("lib", "REV-21-1653 NEO 2.0 Brushless Motor")
        from_library.cots_flag = True
        from_library.cots_info = {"cots_pn": "REV-21-1653", "cots_vendor": "REV"}
        from_library.children = [part("inside", "Bearing")]           # the motor's own insides: not ours
        hand_neo = part("hand", "NEO 2.0 Brushless Motor")
        block = part("blk", "27-DRV-110 Bearing Block", pn="27-DRV-110")
        hand_bearing = part("hb", "Flanged bearing")
        root = asm("root", "27-DRV-100 Chassis", [from_library, hand_neo, block, hand_bearing], pn="27-DRV-100")
        res = {r.check_id: r for r in rc.auto_checks(root, CFG, bc.build_bom(root, CFG), library_items=[lib_neo])}
        lib = res["library"]
        self.assertEqual(lib.status, rc.WARN)                        # a warning - doesn't block sign-off
        self.assertEqual(len(lib.items), 2, lib.items)
        self.assertTrue(any(i.startswith("NEO 2.0 Brushless Motor:") and "REV-21-1653" in i for i in lib.items))
        self.assertTrue(any(i.startswith("Flanged bearing:") for i in lib.items))

    def test_passes_without_bought_parts(self):
        root = robot()
        res = {r.check_id: r for r in rc.auto_checks(root, CFG, bc.build_bom(root, CFG))}
        self.assertEqual(res["library"].status, rc.PASS)
