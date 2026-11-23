"""Tests for the BOM builder. Run: python -m unittest discover -s tests -v"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from lib import bom_core as bc  # noqa: E402
from lib import naming_core as nc  # noqa: E402
import test_naming_core as tn  # noqa: E402  (module import so its tests aren't run twice)

CFG, asm, linked, part = tn.CFG, tn.asm, tn.linked, tn.part


def minibot():
    """Minibot chassis with TWO copies of a numbered gearbox (like the team's)."""
    so = linked("so", "27-GRB-102 Standoff", pn="27-GRB-102")
    so.material, so.mass_kg, so.process = "Aluminum 6061", 0.01, "Lathe"
    plate = part("mmp", "27-GRB-101 motor mounting plate", pn="27-GRB-101")
    plate.material, plate.mass_kg = "Aluminum 6061", 0.2
    wheel = linked("wh", "am-0940b 6 in HiGrip Wheel", pn="am-0940b 6 HiGrip",
                   children=[part("rim", "6 wheel Rev 4"), part("tread", "tread")])
    gb = linked("gb", "27-GRB-100 Gearbox Assembly (1)", pn="27-GRB-100",
                children=[plate, so, so, so, so, linked("cim", "am-0255 2.5inch CIM Motor (1)"),
                          linked("bolt", "Hexagon Socket Head Cap Screw ANSI B18.3 - 10-24"),
                          linked("bolt", "Hexagon Socket Head Cap Screw ANSI B18.3 - 10-24")])
    rail = part("rail", "27-DRV-101 side frame rails", pn="27-DRV-101")
    rail.mass_kg = 1.0
    root = asm("root", "27-DRV-100 MINIBOTS Chassis assembly", [
        rail, rail, gb, gb, wheel, wheel, wheel, wheel,
        part("new", "omni shaft"),
        nc.CompNode(key="empty", name="Component9"),
    ], pn="27-DRV-100")
    return root


class BomTests(unittest.TestCase):
    def setUp(self):
        self.bom = bc.build_bom(minibot(), CFG, processes={"rail": "X-Carve"})
        self.flat = {r.key: r for r in self.bom.flat}

    def test_totals_multiply_through_repeated_gearboxes(self):
        self.assertEqual(self.flat["root"].qty, 1)
        self.assertEqual(self.flat["gb"].qty, 2)
        self.assertEqual(self.flat["so"].qty, 8)        # 4 per gearbox x 2
        self.assertEqual(self.flat["bolt"].qty, 4)
        self.assertEqual(self.flat["cim"].qty, 2)
        self.assertEqual(self.flat["rail"].qty, 2)
        self.assertEqual(self.flat["wh"].qty, 4)

    def test_cots_insides_and_empty_components_left_out(self):
        self.assertNotIn("rim", self.flat)
        self.assertNotIn("empty", self.flat)

    def test_types_process_status(self):
        self.assertEqual(self.flat["gb"].type, bc.TYPE_ASSEMBLY)
        self.assertEqual(self.flat["so"].process, "Lathe")          # saved on the part
        self.assertEqual(self.flat["rail"].process, "X-Carve")      # chosen in the dialog
        self.assertEqual(self.flat["new"].process, bc.PROCESS_TBD)
        self.assertEqual(self.flat["cim"].process, bc.PROCESS_COTS)
        self.assertEqual(self.flat["cim"].status, "To Order")
        self.assertEqual(self.flat["rail"].status, "Designed")

    def test_vendor_info(self):
        cim = self.flat["cim"]
        self.assertEqual((cim.vendor, cim.vendor_pn), ("AndyMark", "am-0255"))
        self.assertIn("am-0255", cim.link)
        self.assertEqual(self.flat["bolt"].vendor, "Hardware")
        mc = bc.vendor_info("91251A537 Socket Head Screw", "")
        self.assertEqual((mc.vendor, mc.link), ("McMaster-Carr", "https://www.mcmaster.com/91251A537"))
        self.assertEqual(bc.vendor_info("WCP-0903", "WCP-0903 Rev1").vendor_pn, "WCP-0903")

    def test_mass_and_subsystem(self):
        self.assertAlmostEqual(self.flat["so"].total_mass_lb, round(0.01 * bc.KG_TO_LB, 3) * 8, places=2)
        self.assertIsNone(self.flat["gb"].total_mass_lb)            # assemblies don't double count
        self.assertEqual(self.flat["so"].subsystem, "GRB")
        self.assertEqual(self.flat["rail"].subsystem, "DRV")
        self.assertEqual(self.flat["cim"].subsystem, "DRV")

    def test_notes_and_warnings(self):
        self.assertIn("no team part number", self.flat["new"].notes)
        self.assertTrue(any("Name Parts" in w for w in self.bom.warnings))

    def test_default_steel_is_flagged(self):
        root = asm("root", "Bot", [part("a", "27-DRV-101 Plate", pn="27-DRV-101"), part("b", "27-DRV-102 Rail", pn="27-DRV-102")])
        root.children[0].material = "Steel"
        root.children[1].material = "Aluminum 6061"
        bom = bc.build_bom(root, CFG)
        flat = {r.key: r for r in bom.flat}
        self.assertIn("default", flat["a"].notes)
        self.assertNotIn("default", flat["b"].notes)
        self.assertTrue(any("Steel" in w for w in bom.warnings))

    def test_used_in(self):
        self.assertEqual(self.flat["so"].used_in, "27-GRB-100 Gearbox Assembly")

    def test_indented_view(self):
        rows = [(r.level, r.key, r.qty) for r in self.bom.indented]
        self.assertEqual(rows[0], (0, "root", 1))
        self.assertIn((1, "gb", 2), rows)
        self.assertIn((2, "so", 4), rows)
        self.assertIn((1, "wh", 4), rows)
        self.assertNotIn("rim", [k for _, k, _ in rows])

    def test_tables(self):
        flat = bc.flat_table(self.bom)
        self.assertEqual(flat[0][:4], ["Name", "Part #", "Description", "Qty"])
        self.assertEqual(len(flat), len(self.bom.flat) + 1)
        so_row = next(r for r in flat if r[1] == "27-GRB-102")
        self.assertEqual(so_row[0], "27-GRB-102 Standoff")
        self.assertEqual(so_row[3], 8)
        ind = bc.indented_table(self.bom)
        self.assertTrue(ind[2][1].startswith("    "))


if __name__ == "__main__":
    unittest.main()


class CotsLibraryBomTests(unittest.TestCase):
    """Parts from the COTS Library carry their own vendor details into the BOM."""

    def test_library_details_win(self):
        neo = linked("neo", "REV-21-1650 NEO Brushless Motor V1.1", pn="REV-21-1650")
        neo.cots_flag = True
        neo.cots_info = {"cots_vendor": "REV", "cots_pn": "REV-21-1650", "cots_name": "NEO Brushless Motor V1.1",
                         "cots_price": "48.00", "cots_url": "https://www.revrobotics.com/rev-21-1650/"}
        root = asm("root", "27-DRV-100 Drive", [neo, neo], pn="27-DRV-100")
        row = {r.key: r for r in bc.build_bom(root, CFG).flat}["neo"]
        self.assertEqual((row.type, row.qty, row.vendor, row.vendor_pn), (bc.TYPE_COTS, 2, "REV", "REV-21-1650"))
        self.assertEqual(row.unit_price, 48.0)
        self.assertEqual(row.link, "https://www.revrobotics.com/rev-21-1650/")
        self.assertEqual(row.description, "NEO Brushless Motor V1.1")
        table = bc.flat_table(bc.build_bom(root, CFG))
        price_col = table[0].index("Unit Price")
        self.assertIn(48.0, [r[price_col] for r in table[1:]])
