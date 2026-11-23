"""Tests for Quick Rib (rib placement) and Lighten (which regions become pockets)."""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from lib import lighten_core as lc  # noqa: E402


def circle(cx, cy, r, n=48):
    return [(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)) for k in range(n)]


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def gearbox_plate():
    """6 x 4 plate: two bearing holes and four #10 corner holes."""
    holes = [lc.Hole(circle(cx, cy, r), (cx, cy), r) for cx, cy, r in
             [(1.5, 2.0, 0.5625), (4.5, 2.0, 0.5625),
              (0.5, 0.5, 0.1), (5.5, 0.5, 0.1), (0.5, 3.5, 0.1), (5.5, 3.5, 0.1)]]
    outer = rect(0, 0, 6, 4)
    return lc.Plate(outer, holes, list(outer))


class GeometryTests(unittest.TestCase):
    def test_inside_and_distances(self):
        sq = rect(0, 0, 2, 2)
        self.assertTrue(lc.inside((1, 1), sq))
        self.assertFalse(lc.inside((3, 1), sq))
        self.assertAlmostEqual(lc.dist_to_poly((1, 0.25), sq), 0.25)
        self.assertAlmostEqual(lc.area(sq), 4)
        self.assertAlmostEqual(lc.perimeter(sq), 8)

    def test_inradius_estimate(self):
        c = circle(0, 0, 1, 400)
        self.assertAlmostEqual(lc.inradius_estimate(lc.area(c), lc.perimeter(c)), 1.0, places=3)
        tri = [(0, 0), (3, 0), (0, 4)]   # 3-4-5 triangle, inradius 1
        self.assertAlmostEqual(lc.inradius_estimate(lc.area(tri), lc.perimeter(tri)), 1.0)

    def test_interior_point_of_concave_shapes(self):
        # A thin "C": its centroid is in the empty middle.
        c_shape = [(0, 0), (4, 0), (4, 0.5), (0.5, 0.5), (0.5, 3.5), (4, 3.5), (4, 4), (0, 4)]
        p = lc.interior_point(c_shape)
        self.assertIsNotNone(p)
        self.assertTrue(lc.inside(p, c_shape))
        # A ring: the middle is the hole.
        ring_p = lc.interior_point(circle(0, 0, 2), [circle(0, 0, 1.5)])
        self.assertTrue(1.5 < math.hypot(*ring_p) < 2.0)

    def test_chain_loop_flips_pieces(self):
        pieces = [[(0, 0), (1, 0)], [(1, 1), (1, 0)], [(1, 1), (0, 1)], [(0, 0), (0, 1)]]
        loop = lc.chain_loop(pieces)
        self.assertEqual(len(loop), 4)
        self.assertAlmostEqual(lc.area(loop), 1.0)
        # First piece backwards relative to the second.
        loop2 = lc.chain_loop([[(1, 0), (0, 0)], [(1, 0), (1, 1)], [(1, 1), (0, 1)], [(0, 1), (0, 0)]])
        self.assertEqual(len(loop2), 4)
        self.assertAlmostEqual(lc.area(loop2), 1.0)
        self.assertAlmostEqual(lc.perimeter(loop2), 4.0)
        self.assertEqual(lc.chain_loop([]), [])

    def test_delaunay_square_and_grid(self):
        self.assertEqual(len(lc.delaunay(rect(0, 0, 1, 1))), 2)
        grid = [(x, y) for x in range(4) for y in range(3)]
        tris = lc.delaunay(grid)
        self.assertEqual(len(tris), 2 * 3 * 2)     # (4-1)*(3-1) squares, 2 triangles each
        self.assertEqual(lc.delaunay([(0, 0), (1, 1)]), [])


class ParamTests(unittest.TestCase):
    def test_cutters(self):
        xcarve = lc.cutter_from_dict(lc.DEFAULT_CUTTERS[0])
        self.assertAlmostEqual(xcarve.corner_in, 0.0675)
        laser = lc.cutter_from_dict(lc.DEFAULT_CUTTERS[-1])
        self.assertAlmostEqual(laser.corner_in, 0.0625)
        self.assertIsNone(lc.cutter_from_dict({"name": "", "diameter_in": 0.1}))
        self.assertIsNone(lc.cutter_from_dict({"name": "x", "diameter_in": "abc"}))

    def test_check_params(self):
        ok = lc.LightenParams()
        self.assertEqual(lc.check_params(ok, 0.25), [])
        deep = lc.LightenParams(depth_in=0.24)
        self.assertTrue(any("floor" in p for p in lc.check_params(deep, 0.25)))
        self.assertEqual(lc.check_params(lc.LightenParams(depth_in=0.1), 0.25), [])
        tiny = lc.LightenParams(min_pocket_in=0.1, corner_in=0.13)
        self.assertTrue(any("cutter won't fit" in p for p in lc.check_params(tiny, None)))
        self.assertTrue(lc.check_params(lc.LightenParams(rib_in=0.01), None))


class ClassifyTests(unittest.TestCase):
    def setUp(self):
        self.plate = gearbox_plate()
        self.params = lc.LightenParams()

    def test_zones(self):
        c = lambda p, ribs=(): lc.classify(p, self.plate, ribs, self.params)  # noqa: E731
        self.assertEqual(c((-1, 1)), lc.KEEP_OUTSIDE)
        self.assertEqual(c((3, 0.1)), lc.KEEP_WALL)
        self.assertEqual(c((1.5, 2.0)), lc.KEEP_HOLE)
        self.assertEqual(c((1.5, 2.0 + 0.5625 + 0.1)), lc.KEEP_BOSS)
        self.assertEqual(c((3, 2)), lc.POCKET)
        rib = lc.Rib((1.5, 2.0), (4.5, 2.0))
        self.assertEqual(c((3, 2.05), [rib]), lc.KEEP_RIB)
        self.assertEqual(c((3, 2.5), [rib]), lc.POCKET)
        ring = lc.Rib(center=(3, 2), radius=1.0)
        self.assertEqual(c((3, 3), [ring]), lc.KEEP_RIB)
        self.assertEqual(c((3, 2.5), [ring]), lc.POCKET)

    def test_pocket_size(self):
        self.assertTrue(lc.pocket_too_small(lc.area(rect(0, 0, 0.3, 0.3)), 1.2, self.params))
        self.assertFalse(lc.pocket_too_small(1.0, 4.0, self.params))

    def test_rib_strip(self):
        strip = lc.rib_strip(lc.Rib((0, 0), (2, 0)), 0.2)
        self.assertEqual(len(strip), 4)
        self.assertAlmostEqual(lc.area(strip), 0.4)
        self.assertEqual(lc.rib_strip(lc.Rib((1, 1), (1, 1)), 0.2), [])
        self.assertEqual(len(lc.polyline_ribs([(0, 0), (1, 0), (1, 1)], closed=True)), 3)


class QuickRibTests(unittest.TestCase):
    def test_gearbox_plate_ribs(self):
        plate = gearbox_plate()
        params = lc.LightenParams()
        ribs = lc.quick_ribs(plate, params)
        self.assertGreater(len(ribs), 5)
        for rib in ribs:
            # Every rib stays on the plate.
            for s in (0.25, 0.5, 0.75):
                q = (rib.a[0] + (rib.b[0] - rib.a[0]) * s, rib.a[1] + (rib.b[1] - rib.a[1]) * s)
                self.assertTrue(lc.inside(q, plate.outer) or lc.dist_to_poly(q, plate.outer) < 1e-3)
            # No rib runs along the outside edge.
            mid = ((rib.a[0] + rib.b[0]) / 2, (rib.a[1] + rib.b[1]) / 2)
            self.assertGreater(lc.dist_to_poly(mid, plate.outer), params.wall_in)
        # The two bearings are tied together.
        self.assertTrue(any({r.a, r.b} == {(1.5, 2.0), (4.5, 2.0)} for r in ribs))
        # Every hole has at least one rib.
        for h in plate.holes:
            self.assertTrue(any(lc.dist(h.center, r.a) < 1e-6 or lc.dist(h.center, r.b) < 1e-6 for r in ribs),
                            f"hole at {h.center} has no rib")

    def test_no_floating_holes_on_long_arm(self):
        holes = [lc.Hole(circle(x, y, 0.1), (x, y), 0.1) for x in (0.5, 13.5) for y in (0.75, 2.25)]
        holes.append(lc.Hole(circle(7, 1.5, 0.5625), (7, 1.5), 0.5625))
        outer = rect(0, 0, 14, 3)
        ribs = lc.quick_ribs(lc.Plate(outer, holes, outer), lc.LightenParams())
        for h in holes:
            self.assertTrue(any(lc.dist(h.center, r.a) < 1e-6 or lc.dist(h.center, r.b) < 1e-6 for r in ribs),
                            f"hole at {h.center} is floating")

    def test_close_holes_merge(self):
        holes = [lc.Hole(circle(x, 1, 0.1), (x, 1), 0.1) for x in (2.0, 2.4)]
        plate = lc.Plate(rect(0, 0, 6, 2), holes, rect(0, 0, 6, 2))
        nodes = lc._cluster_holes(plate, 0.15)
        self.assertEqual(len(nodes), 1)
        self.assertAlmostEqual(nodes[0].p[0], 2.2)
        # 0.5in spacing: rings just touch, so the holes stay separate (a row, not a blob)
        spaced = [lc.Hole(circle(x, 1, 0.1), (x, 1), 0.1) for x in (2.0, 2.5)]
        self.assertEqual(len(lc._cluster_holes(lc.Plate(rect(0, 0, 6, 2), spaced, []), 0.15)), 2)

    def test_ribs_avoid_cutouts_and_concave_edges(self):
        # L-shaped plate with a square cutout: no rib may cross the notch or the cutout.
        outer = [(0, 0), (8, 0), (8, 3), (3, 3), (3, 8), (0, 8)]
        cut = rect(4.5, 0.75, 6.5, 2.25)
        holes = [lc.Hole(cut), lc.Hole(circle(1.5, 1.5, 0.3), (1.5, 1.5), 0.3),
                 lc.Hole(circle(1.5, 6.5, 0.1), (1.5, 6.5), 0.1), lc.Hole(circle(7.25, 1.5, 0.1), (7.25, 1.5), 0.1)]
        plate = lc.Plate(outer, holes, outer)
        ribs = lc.quick_ribs(plate, lc.LightenParams())
        self.assertTrue(ribs)
        for rib in ribs:
            for k in range(1, 10):
                s = k / 10
                q = (rib.a[0] + (rib.b[0] - rib.a[0]) * s, rib.a[1] + (rib.b[1] - rib.a[1]) * s)
                self.assertFalse(4 < q[0] < 7.9 and 3.1 < q[1] < 7.9, f"rib {rib} crosses the notch")
                self.assertFalse(lc.inside(q, cut) and lc.dist_to_poly(q, cut) > 1e-3, f"rib {rib} crosses the cutout")

    def test_no_holes_still_ribs_a_big_plate(self):
        outer = rect(0, 0, 12, 4)
        self.assertTrue(lc.quick_ribs(lc.Plate(outer, [], outer), lc.LightenParams()))

    def test_addisons_plate(self):
        """The real test plate: bolt-circle arc, row rib, and every hole held from two sides."""
        import json
        import time
        data = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "test_plate.json")))
        outer = lc.chain_loop([[tuple(p) for p in seg] for seg in data["outer"]])
        corners = [tuple(seg[0]) for seg in data["outer"]]
        holes = [lc.Hole(circle(x, y, r, 32), (x, y), r) for x, y, r in data["holes"]]
        plate = lc.Plate(outer, holes, corners)
        params = lc.LightenParams()
        t0 = time.time()
        ribs = lc.quick_ribs(plate, params)
        self.assertLess(time.time() - t0, 3.0, "Quick Rib is too slow for a live preview")
        kinds = [r.kind for r in ribs]
        self.assertEqual(kinds.count("row"), 1)
        self.assertEqual(kinds.count("arc"), 1)
        arc = next(r for r in ribs if r.kind == "arc")
        self.assertAlmostEqual(arc.radius, 1.0, places=2)
        self.assertFalse(arc.is_full_circle)            # a full ring would run through the big bearing
        self.assertGreaterEqual(kinds.count("spoke"), 2)
        self.assertEqual(lc.unsupported_holes(plate, ribs, params), [])

    def test_every_hole_supported_on_test_plates(self):
        params = lc.LightenParams()
        holes = [lc.Hole(circle(x, y, 0.1), (x, y), 0.1) for x in (0.5, 13.5) for y in (0.75, 2.25)]
        holes.append(lc.Hole(circle(7, 1.5, 0.5625), (7, 1.5), 0.5625))
        arm = lc.Plate(rect(0, 0, 14, 3), holes, rect(0, 0, 14, 3))
        for plate in (gearbox_plate(), arm):
            ribs = lc.quick_ribs(plate, params)
            self.assertEqual(lc.unsupported_holes(plate, ribs, params), [])

    def test_row_detection(self):
        holes = [lc.Hole(circle(x, 1, 0.1), (x, 1), 0.1) for x in (1, 1.5, 2, 2.5, 3)]
        outer = rect(0, 0, 4, 4)
        ribs = lc.quick_ribs(lc.Plate(outer, holes, outer), lc.LightenParams())
        rows = [r for r in ribs if r.kind == "row"]
        self.assertEqual(len(rows), 1)
        self.assertEqual({rows[0].a, rows[0].b}, {(1, 1), (3, 1)})

    def test_full_bolt_circle_ring(self):
        bolt = [lc.Hole(circle(3 + 1.1 * math.cos(k * math.pi / 3), 3 + 1.1 * math.sin(k * math.pi / 3), 0.1),
                        (3 + 1.1 * math.cos(k * math.pi / 3), 3 + 1.1 * math.sin(k * math.pi / 3)), 0.1) for k in range(6)]
        holes = [lc.Hole(circle(3, 3, 0.5625), (3, 3), 0.5625)] + bolt
        outer = rect(0, 0, 6, 6)
        ribs = lc.quick_ribs(lc.Plate(outer, holes, outer), lc.LightenParams())
        arcs = [r for r in ribs if r.kind == "arc"]
        self.assertEqual(len(arcs), 1)
        self.assertTrue(arcs[0].is_full_circle)

    def test_arc_through_three_points(self):
        ccw = lc.arc_through((1, 0), (0, 1), (-1, 0))
        self.assertAlmostEqual(ccw.radius, 1.0)
        self.assertAlmostEqual(ccw.sweep, math.pi)
        self.assertAlmostEqual(ccw.start, 0.0)
        cw = lc.arc_through((-1, 0), (0, 1), (1, 0))        # same arc drawn the other way
        self.assertAlmostEqual(cw.sweep, math.pi)
        self.assertAlmostEqual(cw.start, 0.0)
        low = lc.arc_through((1, 0), (0, -1), (-1, 0))      # bottom half
        self.assertAlmostEqual(low.start, math.pi)
        self.assertIsNone(lc.arc_through((0, 0), (1, 1), (2, 2)))

    def test_offset_strip_is_one_smooth_band(self):
        pts = [(math.cos(k * math.pi / 20), math.sin(k * math.pi / 20)) for k in range(11)]   # quarter circle
        band = lc.offset_strip(pts, 0.2)
        self.assertEqual(len(band), 22)
        # Every outline point sits ~0.1 from the centerline - no notches or spikes.
        for q in band:
            self.assertAlmostEqual(abs(math.hypot(*q) - 1.0), 0.1, delta=0.002)
        self.assertAlmostEqual(lc.area(band), 0.2 * math.pi / 2, delta=0.003)

    def test_arc_rib_distance(self):
        arc = lc.arc_rib((0, 0), 1.0, 0.0, math.pi / 2)
        self.assertAlmostEqual(lc.rib_distance((0.0, 1.2), arc), 0.2)
        self.assertAlmostEqual(lc.rib_distance((-1.0, 0.0), arc), math.hypot(1, 1))   # past the end: to the end point
        self.assertAlmostEqual(arc.b[1], 1.0)
        p = lc.LightenParams()
        plate = lc.Plate(rect(-3, -3, 3, 3), [], rect(-3, -3, 3, 3))
        self.assertEqual(lc.classify((0.7071, 0.7071), plate, [arc], p), lc.KEEP_RIB)
        self.assertEqual(lc.classify((-0.7071, -0.7071), plate, [arc], p), lc.POCKET)

    def test_edge_tabs_close_thin_channels(self):
        params = lc.LightenParams()
        holes = [lc.Hole(circle(x, 0.75, 0.098), (x, 0.75), 0.098) for x in (1.0, 1.5, 2.0)]   # a row near the edge
        holes.append(lc.Hole(circle(2.0, 2.5, 0.098), (2.0, 2.5), 0.098))                      # far from any edge
        plate = lc.Plate(rect(0, 0, 4, 4), holes, rect(0, 0, 4, 4))
        tabs = lc.edge_tabs(plate, params)
        self.assertEqual(len(tabs), 3)
        for tab in tabs:
            self.assertAlmostEqual(tab.b[1], 0.0)                     # straight down to the wall
            self.assertAlmostEqual(tab.width, 2 * (0.098 + 0.15))
        # The 0.25in gap under the row would be a pocket channel; with the tabs it's material.
        self.assertEqual(lc.classify((1.0, 0.38), plate, [], params), lc.POCKET)
        self.assertEqual(lc.classify((1.0, 0.38), plate, tabs, params), lc.KEEP_RIB)

    def test_summary(self):
        lines = lc.summary(6, 2, 1, 0.25, 1.0)
        self.assertIn("25%", lines[0])
        self.assertEqual(len(lines), 3)


if __name__ == "__main__":
    unittest.main()
