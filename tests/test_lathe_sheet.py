"""Tests for lathe sheet analysis and the tiny PDF writer."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from lib import lathe_sheet as ls  # noqa: E402
from lib import pdf_writer as pw  # noqa: E402

IN = 25.4


def output_shaft():
    """1/2" hex shaft, 4" long, with a 0.375" round journal on the last 0.5"
    and a #10 tapped hole (0.159" drill) 0.5" deep in the left end."""
    flats = [ls.RawFlat(0.25 * IN, 0, 3.5 * IN) for _ in range(6)]
    cyl = [ls.RawCylinder(0.1875 * IN, 3.5 * IN, 4 * IN, True),
           ls.RawCylinder(0.0795 * IN, 0, 0.5 * IN, False)]
    return ls.analyze("output shaft", 4 * IN, cyl, flats, "27-GRB-104", "Output Shaft", "Steel 4140", 2)


def standoff():
    """0.5" OD spacer, 1.25" long, 0.257" through bore, made in two touching halves."""
    cyl = [ls.RawCylinder(0.25 * IN, 0, 0.6 * IN, True), ls.RawCylinder(0.25 * IN, 0.6 * IN, 1.25 * IN, True),
           ls.RawCylinder(0.1285 * IN, 0, 1.25 * IN, False)]
    return ls.analyze("standoff", 1.25 * IN, cyl, [], "27-GRB-102", "Standoff", "Aluminum 6061", 8)


class LatheTests(unittest.TestCase):
    def test_hex_shaft(self):
        p = output_shaft()
        self.assertEqual(p.stock, '1/2" hex')
        self.assertEqual([s.kind for s in p.steps], ["hex", "round"])
        self.assertAlmostEqual(p.steps[1].diameter_mm, 0.375 * IN)
        self.assertEqual(len(p.bores), 1)
        self.assertEqual(ls._bore_where(p.bores[0], p.length_mm), "from left end")
        self.assertAlmostEqual(p.stock_length_mm, 4.25 * IN)

    def test_round_spacer_merges_halves_and_picks_stock(self):
        p = standoff()
        self.assertEqual(len(p.steps), 1)
        self.assertAlmostEqual(p.steps[0].length, 1.25 * IN)
        self.assertEqual(p.stock, '1/2" round')       # finished OD is a stock size: use it as-is
        self.assertEqual(ls.analyze("x", 10, [ls.RawCylinder(0.23 * IN, 0, 10, True)], []).stock, '1/2" round')
        self.assertEqual(ls._bore_where(p.bores[0], p.length_mm), "through")

    def test_not_a_lathe_part(self):
        p = ls.analyze("bracket", 50, [], [])
        self.assertEqual(p.stock, "unknown")
        self.assertTrue(p.warnings)

    def test_keyway_flag(self):
        p = ls.analyze("shaft", 100, [ls.RawCylinder(6, 0, 100, True)], [ls.RawFlat(5, 10, 40)])
        self.assertTrue(any("keyway" in w for w in p.warnings))

    def test_render_pdf(self):
        folder = tempfile.mkdtemp()
        for prof in (output_shaft(), standoff()):
            path = ls.render(prof, os.path.join(folder, prof.name + ".pdf"))
            with open(path, "rb") as handle:
                data = handle.read()
            self.assertTrue(data.startswith(b"%PDF-1.4"))
            self.assertTrue(data.rstrip().endswith(b"%%EOF"))
            self.assertIn(b"LATHE SHEET", data)


def omni_shaft():
    """The REAL omni shaft from the team's minibot: 1/2" hex body, 0.500" turned ends with snap-ring grooves."""
    cyl = [ls.RawCylinder(0.25 * IN, 0, 0.062 * IN, True), ls.RawCylinder(0.234 * IN, 0.062 * IN, 0.102 * IN, True),
           ls.RawCylinder(0.25 * IN, 0.102 * IN, 0.414 * IN, True), ls.RawCylinder(0.25 * IN, 3.289 * IN, 3.601 * IN, True),
           ls.RawCylinder(0.234 * IN, 3.601 * IN, 3.641 * IN, True), ls.RawCylinder(0.25 * IN, 3.641 * IN, 3.705 * IN, True)]
    flats = [ls.RawFlat(0.25 * IN, 0.414 * IN, 3.289 * IN) for _ in range(6)]
    return ls.analyze("omni shaft", 3.705 * IN, cyl, flats, "27-DRV-105", "omni shaft", "Steel 4140", 1)


class DimensionTests(unittest.TestCase):
    def test_grooves_found_with_distance_from_nearest_end(self):
        p = omni_shaft()
        feats = ls.features(p)
        self.assertEqual([f.kind for f in feats], ["round", "groove", "round", "hex", "round", "groove", "round"])
        g1, g2 = feats[1], feats[5]
        self.assertEqual(ls.nearest_end(g1.step.z0, g1.step.z1, p.length_mm), '0.062" from left end')
        self.assertEqual(ls.nearest_end(g2.step.z0, g2.step.z1, p.length_mm), '0.064" from right end')
        self.assertAlmostEqual(g1.step.length / IN, 0.040, places=3)

    def test_turned_sections(self):
        lines = ls.turned_sections(omni_shaft())
        self.assertEqual(lines[0], 'Left end: turn to \u00d80.500" for 0.414" (includes 1 groove)')
        self.assertTrue(lines[1].startswith("Right end: turn to \u00d80.500\" for 0.416\""))
        self.assertEqual(ls.turned_sections(standoff()), [])        # plain round spacer: nothing turned down

    def test_wide_narrow_section_is_not_a_groove(self):
        cyl = [ls.RawCylinder(0.5 * IN, 0, 1 * IN, True), ls.RawCylinder(0.3 * IN, 1 * IN, 2 * IN, True),
               ls.RawCylinder(0.5 * IN, 2 * IN, 3 * IN, True)]
        kinds = [f.kind for f in ls.features(ls.analyze("x", 3 * IN, cyl, []))]
        self.assertEqual(kinds, ["round", "round", "round"])

    def test_sheet_has_every_dimension(self):
        path = ls.render(omni_shaft(), os.path.join(tempfile.mkdtemp(), "omni.pdf"))
        data = open(path, "rb").read()
        for text in (b"GROOVE", b"0.062", b"0.102", b"0.414", b"3.289", b"3.601", b"3.641", b"3.705",
                     b"Left end: turn to", b"from right end"):
            self.assertIn(text, data, text)


class PdfWriterTests(unittest.TestCase):
    def test_escape(self):
        self.assertEqual(pw._esc("a(b)\\c"), "a\\(b\\)\\\\c")
        self.assertEqual(pw._esc("Ø0.5"), "Ø0.5")       # Ø is Latin-1, kept
        self.assertEqual(pw._esc("\U0001F517"), "?")              # emoji isn't

    def test_xref_offsets_are_correct(self):
        folder = tempfile.mkdtemp()
        page = pw.PdfPage()
        page.text(36, 500, "hello")
        path = pw.write_pdf(os.path.join(folder, "x.pdf"), [page])
        data = open(path, "rb").read()
        xref_at = int(data.rsplit(b"startxref\n", 1)[1].split(b"\n")[0])
        self.assertTrue(data[xref_at:].startswith(b"xref"))
        entries = data[xref_at:].split(b"\n")[3:]
        first_obj_offset = int(entries[0][:10])
        self.assertTrue(data[first_obj_offset:].startswith(b"1 0 obj"))


if __name__ == "__main__":
    unittest.main()
