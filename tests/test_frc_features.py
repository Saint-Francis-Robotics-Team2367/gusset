"""Tests for hole sizes, the 0.5" hole grid and bearing pockets."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from lib import frc_features as ff  # noqa: E402


class HoleTests(unittest.TestCase):
    def test_sizes_match_drill_chart(self):
        self.assertEqual(ff.hole_size("#10", "Clearance").diameter_in, 0.2010)
        self.assertEqual(ff.hole_size("#10", "Close").diameter_in, 0.1960)
        self.assertEqual(ff.hole_size("#10", "Tap").diameter_in, 0.1590)
        self.assertEqual(ff.hole_size('1/4"', "Clearance").diameter_in, 0.2660)
        self.assertEqual(ff.hole_size('1/4"', "Close").diameter_in, 0.2570)
        self.assertEqual(ff.hole_size('1/4"', "Tap").diameter_in, 0.2010)
        self.assertIn("#21", ff.hole_size("#10", "Tap").label)
        with self.assertRaises(ValueError):
            ff.hole_size("#8", "Tap")

    def test_row_on_2x1_tube_face(self):
        holes = ff.grid_positions(10.0, 1.0, 0.201)
        xs = [x for x, _ in holes]
        self.assertEqual(xs[0], 0.25)
        self.assertEqual(xs[-1], 9.75)
        self.assertEqual(len(holes), 20)
        self.assertTrue(all(y == 0.5 for _, y in holes))
        self.assertTrue(all(abs((b - a) - 0.5) < 1e-9 for a, b in zip(xs, xs[1:])))

    def test_full_grid_on_2in_face(self):
        holes = ff.grid_positions(3.0, 2.0, 0.201, layout=ff.LAYOUT_GRID)
        ys = sorted({y for _, y in holes})
        self.assertEqual(ys, [0.5, 1.0, 1.5])
        self.assertEqual(len(holes), 6 * 3)

    def test_centered_start(self):
        holes = ff.grid_positions(3.3, 1.0, 0.201, start=ff.START_CENTER)
        xs = [x for x, _ in holes]
        self.assertAlmostEqual(sum(xs) / len(xs), 1.65)
        self.assertIn(1.65, [round(x, 6) for x in xs])

    def test_no_room(self):
        self.assertEqual(ff.grid_positions(0.2, 1.0, 0.266), [])
        self.assertEqual(ff.grid_positions(5.0, 0.25, 0.266), [])


class BearingTests(unittest.TestCase):
    def fr8(self):
        return ff.DEFAULT_BEARINGS[0]

    def test_through_press_fit(self):
        p = ff.plan_pocket(self.fr8(), "Press", ff.POCKET_THROUGH, 0.25)
        self.assertAlmostEqual(p.pocket_d_in, 1.1245)
        self.assertIsNone(p.pocket_depth_in)
        self.assertTrue(any("thinner" in n for n in p.notes))       # 1/4" plate, 5/16" bearing

    def test_print_fit(self):
        self.assertAlmostEqual(ff.plan_pocket(self.fr8(), "3D print", ff.POCKET_THROUGH, 0.5).pocket_d_in, 1.133)

    def test_blind_pocket(self):
        r8 = ff.DEFAULT_BEARINGS[2]
        p = ff.plan_pocket(r8, "Snug", ff.POCKET_BLIND, 0.5)
        self.assertAlmostEqual(p.pocket_depth_in, 0.3125)
        self.assertAlmostEqual(p.shaft_d_in, 0.5625)
        self.assertEqual(p.notes, [])
        flanged = ff.plan_pocket(self.fr8(), "Snug", ff.POCKET_BLIND, 0.5)
        self.assertAlmostEqual(flanged.pocket_depth_in, 0.3125 - 0.062)   # flange sits on top

    def test_warnings(self):
        r8 = ff.DEFAULT_BEARINGS[2]
        self.assertTrue(ff.plan_pocket(r8, "Snug", ff.POCKET_THROUGH, 0.5).notes)      # no flange
        thin = ff.plan_pocket(r8, "Snug", ff.POCKET_BLIND, 0.25)                         # too thin: refuse
        self.assertIn("straight through", thin.blocked)
        fr8_in_quarter = ff.plan_pocket(self.fr8(), "Press", ff.POCKET_BLIND, 0.25)       # a real team case
        self.assertTrue(fr8_in_quarter.blocked)
        self.assertEqual(ff.plan_pocket(r8, "Snug", ff.POCKET_BLIND, 0.5).blocked, "")

    def test_settings_round_trip(self):
        b = ff.bearing_from_dict(ff.bearing_to_dict(self.fr8()))
        self.assertEqual(b, self.fr8())
        self.assertIsNone(ff.bearing_from_dict({"name": "broken"}))


if __name__ == "__main__":
    unittest.main()
