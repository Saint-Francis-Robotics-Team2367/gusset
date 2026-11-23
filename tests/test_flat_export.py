"""Tests for SVG/DXF flat export. Run: python -m unittest discover -s tests -v"""

import math
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from lib import flat_export as fe  # noqa: E402

IN = 25.4


def plate():
    """A 4in x 2in plate with rounded right end (radius 1in), a 0.5in hole,
    a slot made of arcs, and a 0.125in-deep pocket."""
    outer = fe.Loop([
        ("line", (0, 0), (3 * IN, 0)),
        ("arc", (3 * IN, 0), (4 * IN, 1 * IN), (3 * IN, 2 * IN)),        # CCW half circle
        ("line", (3 * IN, 2 * IN), (0, 2 * IN)),
        ("line", (0, 2 * IN), (0, 0)),
    ], fe.KIND_OUTER)
    hole = fe.Loop([("circle", (1 * IN, 1 * IN), 0.25 * IN)], fe.KIND_HOLE)
    pocket = fe.Loop([("poly", [(2 * IN, 0.5 * IN), (2.5 * IN, 0.5 * IN), (2.5 * IN, 1.5 * IN),
                                (2 * IN, 1.5 * IN), (2 * IN, 0.5 * IN)])], fe.KIND_POCKET, 0.125 * IN)
    return fe.FlatProfile("27-DRV-104 omni mounting plate", [outer, hole, pocket], thickness_mm=0.25 * IN)


class GeometryTests(unittest.TestCase):
    def test_arc_from_3pts(self):
        (c, r, a0, a1, ccw) = fe.arc_from_3pts((1, 0), (0, 1), (-1, 0))
        self.assertAlmostEqual(c[0], 0)
        self.assertAlmostEqual(c[1], 0)
        self.assertAlmostEqual(r, 1)
        self.assertAlmostEqual(a0, 0)
        self.assertAlmostEqual(a1, 180)
        self.assertTrue(ccw)
        self.assertFalse(fe.arc_from_3pts((1, 0), (0, -1), (-1, 0))[4])   # through the bottom = CW
        self.assertIsNone(fe.arc_from_3pts((0, 0), (1, 1), (2, 2)))        # straight line

    def test_bounds_include_arc_bulge(self):
        x0, y0, x1, y1 = fe.bounds(plate())
        self.assertAlmostEqual(x1, 4 * IN, places=3)
        self.assertAlmostEqual(y1, 2 * IN, places=3)

    def test_normalized_moves_to_origin(self):
        p = plate()
        moved = fe.FlatProfile("x", [fe.Loop([fe._shift(s, 100, -50) for s in p.loops[0].segs])])
        x0, y0, _x1, _y1 = fe.bounds(fe.normalized(moved))
        self.assertAlmostEqual(x0, 0, places=6)
        self.assertAlmostEqual(y0, 0, places=6)

    def test_thickness_labels(self):
        self.assertEqual(fe.thickness_label(6.35), "1/4 in")
        self.assertEqual(fe.thickness_label(3.175), "1/8 in")
        self.assertEqual(fe.thickness_label(25.4), "1 in")
        self.assertEqual(fe.thickness_label(1.5 * IN), "1-1/2 in")
        self.assertEqual(fe.thickness_label(3.0), "0.118 in")
        self.assertEqual(fe.thickness_label(6.35, "mm"), "6.35 mm")
        self.assertEqual(fe.thickness_label(None), "unknown thickness")


class SvgTests(unittest.TestCase):
    def test_real_units_and_viewbox(self):
        root = ET.fromstring(fe.to_svg(plate(), "in"))
        self.assertEqual(root.get("width"), "4in")
        self.assertEqual(root.get("height"), "2in")
        self.assertEqual(root.get("viewBox"), "0 0 4 2")
        mm = ET.fromstring(fe.to_svg(plate(), "mm"))
        self.assertEqual(mm.get("width"), "101.6mm")

    def test_layers_and_shapes(self):
        svg = fe.to_svg(plate(), "in")
        root = ET.fromstring(svg)
        ns = "{http://www.w3.org/2000/svg}"
        groups = {g.get("id"): g for g in root.iter(ns + "g")}
        self.assertEqual(set(groups), {"cut", "pockets"})
        self.assertEqual(groups["pockets"].get("stroke"), fe.POCKET_COLOR)
        self.assertEqual(len(list(groups["cut"].iter(ns + "circle"))), 1)
        circle = next(groups["cut"].iter(ns + "circle"))
        self.assertEqual((circle.get("cx"), circle.get("cy"), circle.get("r")), ("1", "1", "0.25"))  # y flipped: 2-1
        path = next(groups["cut"].iter(ns + "path")).get("d")
        self.assertIn("A1,1 0 0 0 3,0", path)   # half circle: from (3,2) svg-down to (3,0), math-CCW -> sweep 0
        self.assertTrue(path.rstrip().endswith("Z"))
        self.assertIn("1/4 in", svg)              # stock noted in the header comment


class DxfTests(unittest.TestCase):
    def pairs(self, text):
        rows = text.strip().split("\n")
        return list(zip(rows[0::2], rows[1::2]))

    def test_entities_and_units(self):
        text = fe.to_dxf(plate(), "in")
        pairs = self.pairs(text)
        kinds = [v for c, v in pairs if c.strip() == "0"]
        self.assertEqual(kinds.count("CIRCLE"), 1)
        self.assertEqual(kinds.count("POLYLINE"), 2)        # outline + pocket, each ONE closed shape
        self.assertEqual(kinds.count("SEQEND"), 2)
        self.assertNotIn("LINE", kinds)
        self.assertTrue(text.rstrip().endswith("EOF"))
        self.assertIn("POCKET_0_125in", text)
        # The half-circle end is a bulge of tan(180/4) = 1 (CCW) on one vertex.
        bulges = [float(v) for c, v in pairs if c.strip() == "42"]
        self.assertEqual(len(bulges), 1)
        self.assertAlmostEqual(bulges[0], 1.0, places=6)

    def test_chain_fixes_order_and_direction(self):
        scrambled = [("line", (0, 0), (10, 0)), ("line", (10, 10), (0, 10)),
                     ("line", (10, 10), (10, 0)),          # backwards
                     ("line", (0, 0), (0, 10))]            # backwards
        chains = fe.chain(scrambled)
        self.assertEqual(len(chains), 1)
        self.assertTrue(fe.is_closed(chains[0]))
        for a, b in zip(chains[0], chains[0][1:]):
            self.assertEqual(fe._ends(a)[1], fe._ends(b)[0])

    def test_svg_is_one_closed_path_per_loop(self):
        svg = fe.to_svg(plate(), "in")
        cut = svg.split('<g id="cut"')[1].split("</g>")[0]
        self.assertEqual(cut.count("<path"), 1)
        self.assertEqual(cut.count(" Z"), 1)
        self.assertEqual(cut.count("M"), 1)

    def test_dxf_reads_in_cad_library(self):
        try:
            import ezdxf
        except ImportError:
            self.skipTest("ezdxf not installed")
        from ezdxf import bbox
        folder = tempfile.mkdtemp()
        path = fe.write_profile(os.path.join(folder, "p.dxf"), plate(), "dxf")
        doc = ezdxf.readfile(path)
        self.assertEqual(len(doc.audit().errors), 0)
        ext = bbox.extents(doc.modelspace())
        self.assertAlmostEqual(ext.extmax.x, 4.0, places=3)     # the bulge arc reaches x = 4in
        self.assertAlmostEqual(ext.extmax.y, 2.0, places=3)

    def test_mm_units(self):
        text = fe.to_dxf(plate(), "mm")
        self.assertIn("$INSUNITS\n70\n4", text)
        self.assertIn("\n76.2\n", text)   # arc starts at 3in = 76.2mm

    def test_write_files(self):
        folder = tempfile.mkdtemp()
        for fmt in ("svg", "dxf"):
            path = fe.write_profile(os.path.join(folder, f"p.{fmt}"), plate(), fmt)
            self.assertGreater(os.path.getsize(path), 200)


if __name__ == "__main__":
    unittest.main()
