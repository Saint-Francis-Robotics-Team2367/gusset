"""Tests for the dependency-free Excel writer. Uses openpyxl to READ the file
back if it's installed (it isn't needed by Gusset itself)."""

import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from lib import xlsx_writer as xw  # noqa: E402

try:
    import openpyxl  # noqa: F401
except ImportError:  # pragma: no cover
    openpyxl = None


class XlsxTests(unittest.TestCase):
    def write(self):
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "test.xlsx")
        xw.write_xlsx(path, [
            xw.Sheet("BOM", [["Name", "Qty", "Mass"], ["Plate <1/4\"> & co", 8, 0.25],
                             ["  padded", None, ""], ["bad\x01char", True, float("nan")]], widths=[30, 6, 8]),
            xw.Sheet("BOM", [["Level"], [0]]),                       # duplicate name gets "(2)"
            xw.Sheet("Bad:/Name*?[x]", [["x"]]),
        ])
        return path

    def test_zip_structure(self):
        with zipfile.ZipFile(self.write()) as zf:
            names = set(zf.namelist())
        for required in ("[Content_Types].xml", "xl/workbook.xml", "xl/styles.xml",
                         "xl/worksheets/sheet1.xml", "xl/worksheets/sheet3.xml"):
            self.assertIn(required, names)

    def test_col_letters(self):
        self.assertEqual([xw._col_letter(i) for i in (0, 25, 26, 51, 52)], ["A", "Z", "AA", "AZ", "BA"])

    @unittest.skipIf(openpyxl is None, "openpyxl not installed")
    def test_reads_back_in_openpyxl(self):
        wb = openpyxl.load_workbook(self.write())
        self.assertEqual(wb.sheetnames, ["BOM", "BOM (2)", "Bad--Name---x-"])
        ws = wb["BOM"]
        self.assertEqual(ws["A2"].value, 'Plate <1/4"> & co')
        self.assertEqual(ws["B2"].value, 8)
        self.assertEqual(ws["C2"].value, 0.25)
        self.assertEqual(ws["A3"].value, "  padded")
        self.assertIsNone(ws["B3"].value)
        self.assertEqual(ws["A4"].value, "badchar")
        self.assertTrue(ws["A1"].font.b)
        self.assertEqual(ws.freeze_panes, "A2")
        self.assertEqual(ws.auto_filter.ref, "A1:C4")
        self.assertAlmostEqual(ws.column_dimensions["A"].width, 30)


if __name__ == "__main__":
    unittest.main()
