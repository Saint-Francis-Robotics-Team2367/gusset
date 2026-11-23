"""Tests for the tube / shaft / spacer / belt-and-chain math."""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from lib import frc_parts_core as pc  # noqa: E402

HTD = pc.DRIVES["HTD 5mm belt"]
C25 = pc.DRIVES["#25 chain"]
C35 = pc.DRIVES["#35 chain"]


class TubeTests(unittest.TestCase):
    def test_orientation(self):
        tall = pc.plan_tube("2x1", '1/16" wall', 24, tall=True)
        self.assertEqual((tall.across_in, tall.up_in), (1.0, 2.0))
        flat = pc.plan_tube("2x1", '1/16" wall', 24, tall=False)
        self.assertEqual((flat.across_in, flat.up_in), (2.0, 1.0))
        self.assertEqual(tall.name, 'Tube 2x1 x 24.000"')
        self.assertEqual(tall.holes_along, [])

    def test_hole_pattern(self):
        plan = pc.plan_tube("1x1", '1/8" wall', 3.0, tall=True, holes='#10 close (0.196")')
        self.assertAlmostEqual(plan.hole_d_in, 0.196)
        self.assertEqual(plan.holes_along, [0.25, 0.75, 1.25, 1.75, 2.25, 2.75])
        self.assertEqual(plan.rows_up_faces, [0.0])
        two = pc.plan_tube("2x1", '1/16" wall', 2.0, tall=False, holes='#10 close (0.196")', wide_rows=2)
        self.assertEqual(two.rows_up_faces, [-0.25, 0.25])      # 2" face: two rows
        self.assertEqual(two.rows_side_faces, [0.0])             # 1" face: always one
        three = pc.plan_tube("2x1", '1/16" wall', 2.0, tall=False, holes='#10 close (0.196")', wide_rows=3)
        self.assertEqual(three.rows_up_faces, [-0.5, 0.0, 0.5])

    def test_problems(self):
        self.assertTrue(pc.plan_tube("1x1", '1/16" wall', 0.1, tall=True).problems)
        self.assertEqual(pc.plan_tube("1x1", '1/16" wall', 6, tall=True).problems, [])


class ShaftSpacerTests(unittest.TestCase):
    def test_shaft(self):
        s = pc.plan_shaft(4.0, 0.25, 0.5, "Tapped ends (#10-32)")
        self.assertAlmostEqual(s.length_in, 4.75)
        self.assertTrue(s.tapped)
        self.assertAlmostEqual(s.tap_d_in, 0.159)
        self.assertEqual(s.name, 'Shaft 1/2" hex x 4.750"')
        self.assertTrue(pc.plan_shaft(0.0, 0, 0, "Plain ends").problems)
        self.assertTrue(pc.plan_shaft(0.8, 0, 0, "Tapped ends (#10-32)").problems)
        self.assertAlmostEqual(pc.HEX_CORNERS_IN, 0.57735, places=4)

    def test_spacer(self):
        sp = pc.plan_spacer(0.5, '0.75"')
        self.assertAlmostEqual(sp.length_in, 0.49)
        self.assertAlmostEqual(sp.bore_flats_in, 0.51)
        self.assertEqual(sp.problems, [])
        self.assertTrue(pc.plan_spacer(0.5, '0.625"').problems)   # 0.625 OD leaves almost no wall
        self.assertTrue(pc.plan_spacer(0.02, '0.75"').problems)


class DriveTests(unittest.TestCase):
    def test_pitch_diameters(self):
        self.assertAlmostEqual(pc.pitch_diameter(HTD, 36), 36 * 5 / math.pi / 25.4)
        # #25 16T sprocket pitch diameter is 1.281"
        self.assertAlmostEqual(pc.pitch_diameter(C25, 16), 1.2815, places=3)

    def test_equal_pulleys_are_simple(self):
        # Same size pulleys: belt = 2C + T*p, so C = (N - T) * p / 2.
        c = pc.center_for(HTD, 18, 18, 70)
        self.assertAlmostEqual(c, (70 - 18) * 5 / 2 / 25.4, places=6)
        # Same for chain: 60 links on 16T/16T = 22 pitches.
        self.assertAlmostEqual(pc.center_for(C25, 16, 16, 60), 22 * 0.25, places=6)

    def test_round_trip(self):
        for drive, t1, t2, count in ((HTD, 18, 36, 90), (C25, 16, 32, 80), (C35, 12, 22, 50)):
            c = pc.center_for(drive, t1, t2, count)
            self.assertAlmostEqual(pc.count_for(drive, t1, t2, c), count, places=3)

    def test_too_short(self):
        self.assertTrue(math.isnan(pc.center_for(HTD, 36, 36, 30)))
        self.assertTrue(math.isnan(pc.center_for(C25, 32, 32, 20)))

    def test_options_near(self):
        opts = pc.options_near(C25, 16, 32, 6.0)
        self.assertEqual(len(opts), 6)
        self.assertTrue(all(o.count % 2 == 0 for o in opts))         # chain: even links only
        self.assertLess(opts[2].center_in, 6.0)
        self.assertGreater(opts[3].center_in, 6.0)
        belts = pc.options_near(HTD, 18, 36, 5.0, extra_in=0.003)
        counts = [o.count for o in belts]
        self.assertEqual(counts, sorted(counts))
        self.assertEqual(counts[1] - counts[0], 1)
        exact = pc.center_for(HTD, 18, 36, counts[0])
        self.assertAlmostEqual(belts[0].center_in, exact + 0.003)


if __name__ == "__main__":
    unittest.main()


class ShaftExtrasTests(unittest.TestCase):
    """0.12.1: turned-round ends and snap-ring grooves."""

    def test_round_ends_and_grooves(self):
        s = pc.plan_shaft(4.0, 0.5, 0.5, "Plain ends", "Both ends", grooves_in=[0.39, 4.61])
        self.assertEqual(s.problems, [])
        self.assertTrue(s.round_start and s.round_end)
        self.assertEqual(s.ring_cuts(), [(0.0, 0.375, 0.5), (0.39 - 0.0195, 0.39 + 0.0195, 0.469),
                                         (4.61 - 0.0195, 4.61 + 0.0195, 0.469), (4.625, 5.0, 0.5)])
        self.assertEqual(s.name, 'Shaft 1/2" hex x 5.000" (round ends, 2 grooves)')

    def test_start_only(self):
        s = pc.plan_shaft(4.0, 0.25, 0.25, "Plain ends", "Start only")
        self.assertEqual((s.round_start, s.round_end), (True, False))
        self.assertEqual(len(s.ring_cuts()), 1)

    def test_problems(self):
        self.assertTrue(pc.plan_shaft(4.0, 0.0, 0.0, "Plain ends", grooves_in=[0.01]).problems)       # off the end
        self.assertTrue(pc.plan_shaft(4.0, 0.0, 0.0, "Plain ends", grooves_in=[1.0, 1.05]).problems)  # overlap
        self.assertTrue(pc.plan_shaft(4.0, 0.0, 0.0, "Plain ends", "Both ends", round_d_in=0.6).problems)
        self.assertTrue(pc.plan_shaft(0.6, 0.0, 0.0, "Plain ends", "Both ends").problems)             # too long
        self.assertEqual(pc.plan_shaft(4.0, 0.5, 0.0, "Plain ends", "Start only", grooves_in=[0.2]).problems, [])

    def test_parse_positions(self):
        self.assertEqual(pc.parse_positions('1.25, 2.5in 3"'), ([1.25, 2.5, 3.0], []))
        self.assertEqual(pc.parse_positions(""), ([], []))
        self.assertEqual(len(pc.parse_positions("1, abc")[1]), 1)


class BearingReferenceTests(unittest.TestCase):
    """0.12.3: the reference note's numbers (students type their own)."""

    def test_flanged_outside(self):
        r = pc.bearing_reference(0.3125, 0.0625, 0.25, True)
        self.assertAlmostEqual(r.groove_gap_in, 0.0725)
        self.assertAlmostEqual(r.depth_in, 0.25)

    def test_flanged_inside(self):
        r = pc.bearing_reference(0.3125, 0.0625, 0.1875, False)
        self.assertAlmostEqual(r.groove_gap_in, 0.0625 + 0.010)     # body pokes 0.0625" past a 3/16" plate
        self.assertAlmostEqual(r.depth_in, 0.25)

    def test_plain(self):
        r = pc.bearing_reference(0.3125, 0.0, 0.25, True)
        self.assertAlmostEqual((r.groove_gap_in, r.depth_in), (0.010, 0.3125))
        r = pc.bearing_reference(0.3125, 0.0, 0.25, False)
        self.assertAlmostEqual(r.groove_gap_in, 0.0725)
        self.assertAlmostEqual(r.depth_in, 0.25)
