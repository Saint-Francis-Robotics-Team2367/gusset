"""0.12 Connected tools: library matching, shopping list, Excel links."""

import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from lib import bom_core as bc  # noqa: E402
from lib import cots_core as cc  # noqa: E402
from lib import cots_match as m  # noqa: E402
from lib import xlsx_writer as xw  # noqa: E402

H = '1/2" Hex Bore'
REAL = "/mnt/user-data/uploads/FRC Plugins/Gusset/cache/cots_catalog.json"


def item(fid, title, pn, cat="Pulleys", vendor="WCP"):
    return cc.CatalogItem(fid, cc.part_file_name(pn, title), cat, vendor,
                          cc.CotsInfo(name=title, vendor=vendor, vendor_pn=pn, category=cat), 1)


LIB = [item("a", f"18t x 9mm Wide Aluminum Pulley (HTD 5mm, {H})", "WCP-0563"),
       item("b", f"18t x 15mm Wide Aluminum Pulley (HTD 5mm, {H})", "WCP-0991"),
       item("c", "18t x 9mm Wide Aluminum Pulley (HTD 5mm, 8mm SplineXS Bore)", "WCP-1634"),
       item("d", f"36t x 9mm Wide Aluminum Pulley (HTD 5mm, {H})", "WCP-0990"),
       item("e", "1/2 in. Hex ID 1.125 in. OD Shielded Flanged Bearing", "am-2986", "Bearings", "AndyMark"),
       item("f", "1/2 in. ID Shielded Bearing (R8ZZ)", "am-0181", "Bearings", "AndyMark"),
       item("g", "NEO 2.0 Brushless Motor", "REV-21-1653", "Motors", "REV")]


class PulleyTests(unittest.TestCase):
    def test_best_is_hex_and_narrow(self):
        r = m.pulley_for(LIB, 18, "HTD 5mm belt")
        self.assertEqual(r.best.file_id, "a")
        self.assertEqual(sorted(i.file_id for i in r.others), ["b", "c"])

    def test_width_bore_and_usage(self):
        self.assertEqual(m.pulley_for(LIB, 18, "HTD 5mm belt", width="15mm").best.file_id, "b")
        self.assertEqual(m.pulley_for(LIB, 18, "HTD 5mm belt", bore="SplineXS (Kraken)").best.file_id, "c")
        self.assertEqual(m.pulley_for(LIB, 18, "HTD 5mm belt", usage={"b": [4, 1]}).best.file_id, "b")

    def test_missing(self):
        r = m.pulley_for(LIB, 24, "HTD 5mm belt")
        self.assertIsNone(r.best)
        self.assertIn("18t, 36t", r.why)
        self.assertIn("no #25 chain sprockets", m.pulley_for(LIB, 18, "#25 chain").why)
        self.assertIsNone(m.pulley_for(LIB, 36, "HTD 5mm belt", width="15mm").best)

    def test_choices(self):
        widths, bores = m.drive_choices(LIB, "HTD 5mm belt")
        self.assertEqual(widths, ["Any", "9mm", "15mm"])
        self.assertEqual(bores[:2], ["Any", '1/2" hex'])

    def test_bearings(self):
        self.assertEqual([i.file_id for i in m.shaft_bearings(LIB)], ["e", "f"])   # hex first, then round (R8ZZ)
        self.assertEqual([m.bearing_bore(LIB[4]), m.bearing_bore(LIB[5]), m.bearing_bore(LIB[6])], ["hex", "round", ""])
        self.assertTrue(m.bearing_label(LIB[5]).endswith("[round bore]"))

    @unittest.skipUnless(os.path.exists(REAL), "real catalog not staged")
    def test_real_library(self):
        items, _ = cc.catalog_from_json(open(REAL).read())
        self.assertEqual(m.pulley_for(items, 36, "HTD 5mm belt").best.info.vendor_pn, "WCP-0990")
        self.assertEqual(len(m.shaft_bearings(items)), 2)


class HandModeledTests(unittest.TestCase):
    def test_flags(self):
        comps = [("NEO 2.0 Brushless Motor", False), ("NEO 2.0 Brushless Motor", True), ("Bearing Block", False),
                 ("26-DRV-012 Bearing Spacer", False), ("WCP-0563 pulley", False), ("Flanged bearing", False),
                 ("Side Plate", False), ("Pulley guard", False), ("Kraken X60 (2)", False)]
        found = {h.name: h for h in m.hand_modeled(comps, LIB)}
        self.assertEqual(sorted(found), ["Flanged bearing", "Kraken X60", "NEO 2.0 Brushless Motor", "WCP-0563 pulley"])
        self.assertEqual(found["WCP-0563 pulley"].library.file_id, "a")
        self.assertEqual(found["NEO 2.0 Brushless Motor"].library.file_id, "g")
        self.assertIsNone(found["Flanged bearing"].library)
        self.assertIn("COTS Library", found["Kraken X60"].line())


def bom_rows():
    rows = [bc.BomRow("1", "NEO", "REV-21-1653", "NEO 2.0", bc.TYPE_COTS, qty=4, vendor="REV", vendor_pn="REV-21-1653",
                      link="https://www.revrobotics.com/rev-21-1653/", unit_price=90.0),
            bc.BomRow("2", "Pulley", "WCP-0563", "18t pulley", bc.TYPE_COTS, qty=2, vendor="WCP", vendor_pn="WCP-0563"),
            bc.BomRow("3", "Gear", "WCP-0712", "42t gear", bc.TYPE_COTS, qty=1, vendor="WCP", vendor_pn="WCP-0712",
                      unit_price=12.5, link='https://wcproducts.com/x?a=1&b="2"'),
            bc.BomRow("4", "mystery", "mystery", "mystery", bc.TYPE_COTS, qty=1),
            bc.BomRow("5", "Plate", "26-DRV-001", "Plate", bc.TYPE_MADE, qty=2)]
    return bc.Bom("Drive", flat=rows)


class ShoppingTests(unittest.TestCase):
    def test_groups(self):
        groups = bc.shopping_list(bom_rows())
        self.assertEqual([v for v, _ in groups], ["REV", "WCP", bc.NO_VENDOR])
        self.assertEqual([r.vendor_pn for r in groups[1][1]], ["WCP-0563", "WCP-0712"])

    def test_table(self):
        t = bc.shopping_table(bom_rows())
        sub = {row[0]: row for row in t if row and str(row[0]).endswith("subtotal")}
        self.assertEqual(sub["REV subtotal"][6], 360.0)
        self.assertEqual(sub["WCP subtotal"][6], 12.5)
        self.assertIn("1 part(s) with no price", sub["WCP subtotal"][7])
        self.assertEqual(t[-1][:1] + t[-1][6:7], ["Total", 372.5])
        self.assertEqual(bc.shopping_table(bc.Bom("x"))[1][3], "No COTS parts in this assembly.")

    def test_xlsx_links_open(self):
        path = os.path.join(tempfile.mkdtemp(), "bom.xlsx")
        xw.write_xlsx(path, [xw.Sheet("Shopping list", bc.shopping_table(bom_rows(), xw.Link, xw.Bold),
                                      [w for _c, w in bc.SHOPPING_COLUMNS], autofilter=False)])
        with zipfile.ZipFile(path) as z:
            sheet = z.read("xl/worksheets/sheet1.xml").decode()
        self.assertIn('HYPERLINK("https://www.revrobotics.com/rev-21-1653/"', sheet)
        self.assertIn('s="2"', sheet)
        try:
            import openpyxl
        except ImportError:
            return
        ws = openpyxl.load_workbook(path)["Shopping list"]
        cells = [c.value for row in ws.iter_rows() for c in row if c.value is not None]
        self.assertIn('=HYPERLINK("https://wcproducts.com/x?a=1&b=""2""","https://wcproducts.com/x?a=1&b=""2""")', cells)
        self.assertTrue(any(c.font.b for row in ws.iter_rows() for c in row if c.value == "REV subtotal"))


if __name__ == "__main__":
    unittest.main()
