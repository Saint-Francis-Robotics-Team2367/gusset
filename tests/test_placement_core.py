"""Auto-placing round library parts (pulleys on Belt & Chain centers, bearings in holes)."""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from lib import placement_core as pl  # noqa: E402


def close(a, b, tol=1e-6):
    return all(abs(x - y) < tol for x, y in zip(a, b))


class AxisTests(unittest.TestCase):
    def test_disc_and_rod(self):
        self.assertEqual(pl.axis_index([5.0, 5.0, 9.8]), 2)        # pulley: big moment about its axis
        self.assertEqual(pl.axis_index([0.4, 3.0, 3.02]), 0)       # long part: small moment about its axis
        self.assertIsNone(pl.axis_index([3.0, 3.0, 3.0]))          # a ball - can't tell
        self.assertIsNone(pl.axis_index([1.0, 2.0, 4.0]))          # lumpy - can't tell
        self.assertIsNone(pl.axis_index([0, 0, 0]))


class SeatTests(unittest.TestCase):
    # a flanged bearing along its axis: body 0..0.8 cm, flange 0.8..1.0 (mass leans to the flange)
    FACES = [(0.0, -1), (0.8, -1), (1.0, +1)]

    def test_center(self):
        s = pl.seat_along_axis(pl.CENTER, 0.0, 1.5, 0.7)
        self.assertAlmostEqual(s.position, 0.05)
        self.assertFalse(s.flip)

    def test_flange_high(self):
        s = pl.seat_along_axis(pl.FLANGE_OUT, 0.0, 1.0, 0.56, self.FACES)
        self.assertAlmostEqual(s.position, 0.8 - 0.56)
        self.assertFalse(s.flip)

    def test_flange_low_flips(self):
        faces = [(0.0, -1), (0.2, +1), (1.0, +1)]
        s = pl.seat_along_axis(pl.FLANGE_OUT, 0.0, 1.0, 0.44, faces)
        self.assertAlmostEqual(s.position, 0.2 - 0.44)
        self.assertTrue(s.flip)

    def test_no_flange(self):
        s = pl.seat_along_axis(pl.FLANGE_OUT, 0.0, 1.0, 0.5, [(0.0, -1), (1.0, 1)])
        self.assertAlmostEqual(s.position, 0.5)
        self.assertIn("no flange", s.note)


class MatrixTests(unittest.TestCase):
    def test_pulley_onto_sketch_point(self):
        # vendor model: axis along +Y, center of mass at (1, 2, 3); target: point (10, 0, 0), axis +Z
        seat = pl.Seat(0.0, False)
        m = pl.placement_matrix((1, 2, 3), (0, 1, 0), (1, 0, 0), seat, (10, 0, 0), (0, 0, 1))
        self.assertTrue(close(pl.apply(m, (1, 2, 3)), (10, 0, 0)))
        self.assertTrue(close(pl.rotate_dir(m, (0, 1, 0)), (0, 0, 1)))
        # it's a rotation (no stretching): columns are unit length and the determinant is +1
        r = [[m[0], m[1], m[2]], [m[4], m[5], m[6]], [m[8], m[9], m[10]]]
        det = (r[0][0] * (r[1][1] * r[2][2] - r[1][2] * r[2][1]) - r[0][1] * (r[1][0] * r[2][2] - r[1][2] * r[2][0])
               + r[0][2] * (r[1][0] * r[2][1] - r[1][1] * r[2][0]))
        self.assertAlmostEqual(det, 1.0)

    def test_bearing_flange_outward(self):
        # flange at the part's low end (flip): the low end must end up pointing outward (+X)
        seat = pl.seat_along_axis(pl.FLANGE_OUT, 0.0, 1.0, 0.44, [(0.0, -1), (0.2, 1), (1.0, 1)])
        m = pl.placement_matrix((0, 0, 0.44), (0, 0, 1), (1, 0, 0), seat, (5, 5, 5), (1, 0, 0))
        self.assertTrue(close(pl.apply(m, (0, 0, 0.2)), (5, 5, 5)))       # flange underside on the plate face
        self.assertTrue(close(pl.apply(m, (0, 0, 0.0)), (5.2, 5, 5)))     # flange end sticks out
        self.assertTrue(close(pl.apply(m, (0, 0, 1.0)), (4.2, 5, 5)))     # body goes into the hole

    def test_hole_fits(self):
        self.assertTrue(pl.hole_fits(1.125 * 2.54, 1.125 * 2.54))
        self.assertTrue(pl.hole_fits(1.128 * 2.54, 1.125 * 2.54))
        self.assertFalse(pl.hole_fits(0.875 * 2.54, 1.125 * 2.54))


if __name__ == "__main__":
    unittest.main()


class FlangeTests(unittest.TestCase):
    """0.12.1 fix: find the flange from the round faces, not the mass."""
    # FR8ZZ-ish, cm along the axis 0..0.8: body OD r=1.43 from 0..0.8, flange r=1.59 from 0.64..0.8, hex bore inside
    CYL = [(1.43, 0.0, 0.64), (1.59, 0.64, 0.8), (0.9, 0.0, 0.8)]

    def test_flange_high(self):
        self.assertEqual(pl.flange_from_cylinders(self.CYL, 0.0, 0.8), (1, 0.64))
        s = pl.seat_along_axis(pl.FLANGE_OUT, 0.0, 0.8, 0.30, cylinders=self.CYL)   # mass leans the WRONG way
        self.assertAlmostEqual(s.position, 0.34)
        self.assertFalse(s.flip)

    def test_flange_low_flips(self):
        cyl = [(1.43, 0.16, 0.8), (1.59, 0.0, 0.16)]
        self.assertEqual(pl.flange_from_cylinders(cyl, 0.0, 0.8), (-1, 0.16))
        s = pl.seat_along_axis(pl.FLANGE_OUT, 0.0, 0.8, 0.6, cylinders=cyl)
        self.assertTrue(s.flip)
        self.assertAlmostEqual(s.position, 0.16 - 0.6)

    def test_plain_bearing(self):
        cyl = [(1.43, 0.0, 0.79), (0.64, 0.0, 0.79)]
        self.assertEqual(pl.flange_from_cylinders(cyl, 0.0, 0.79), (0, 0.0))
        s = pl.seat_along_axis(pl.FLANGE_OUT, 0.0, 0.79, 0.4, cylinders=cyl)
        self.assertAlmostEqual(s.position, 0.39)
        self.assertIn("no flange", s.note)


class HexRecognitionTests(unittest.TestCase):
    """0.12.3: Spacer recognizes a hex shaft with no Gusset tag."""

    def hex_planes(self, center, flats=1.27, rotate_deg=0.0, z_extra=()):
        out = []
        for k in range(6):
            a = math.radians(rotate_deg + 60 * k)
            n = (math.cos(a), math.sin(a), 0.0)
            out.append((pl.add(center, pl.scale(n, flats / 2)), n))
        return out + list(z_extra)

    def test_finds_axis(self):
        planes = self.hex_planes((3.0, -2.0, 0.0), rotate_deg=15,
                                 z_extra=[((3.0, -2.0, 0.0), (0, 0, -1)), ((3.0, -2.0, 12.0), (0, 0, 1))])
        point, axis, flat = pl.hex_axis_from_planes(planes, 1.27, (0.0, 0.0, 5.0))
        self.assertTrue(close(point, (3.0, -2.0, 5.0)))
        self.assertTrue(close(axis, (0, 0, 1)) or close(axis, (0, 0, -1)))
        self.assertAlmostEqual(abs(pl.dot(flat, (math.cos(math.radians(15)), math.sin(math.radians(15)), 0))), 1.0)

    def test_wrong_size_or_shape(self):
        self.assertIsNone(pl.hex_axis_from_planes(self.hex_planes((0, 0, 0), flats=1.9), 1.27, (0, 0, 0)))
        box = [((0.635, 0, 0), (1, 0, 0)), ((-0.635, 0, 0), (-1, 0, 0)), ((0, 0.635, 0), (0, 1, 0)),
               ((0, -0.635, 0), (0, -1, 0))]
        self.assertIsNone(pl.hex_axis_from_planes(box, 1.27, (0, 0, 0)))     # a square isn't a hex
