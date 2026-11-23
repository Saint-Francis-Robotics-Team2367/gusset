"""Tests for part-file names, matching and grouping."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from lib import frc_parts_core as pc  # noqa: E402
from lib import part_files_core as pf  # noqa: E402


class NameTests(unittest.TestCase):
    def test_folder(self):
        self.assertEqual(pf.parts_folder_name("Intake Assembly "), "Intake Assembly Parts")

    def test_safe_names(self):
        self.assertEqual(pf.safe_file_name('Tube 2x1 x 24.000"'), "Tube 2x1 x 24.000in")
        self.assertEqual(pf.safe_file_name("a/b:c*d?  e"), "a-b-c-d- e")

    def test_part_names(self):
        self.assertEqual(pf.shaft_file_name(pc.plan_shaft(4.0, 0.25, 0.25, "Plain ends")), "Shaft 0.5in hex x 4.500in")
        self.assertEqual(pf.shaft_file_name(pc.plan_shaft(4.0, 0.5, 0.5, "Plain ends", "Both ends", grooves_in=[0.39, 4.61])),
                         "Shaft 0.5in hex x 5.000in round ends 0.5x0.375 grooves 0.39-4.61")
        self.assertNotEqual(pf.shaft_file_name(pc.plan_shaft(4.0, 0.5, 0.5, "Plain ends", "Start only")),
                            pf.shaft_file_name(pc.plan_shaft(4.0, 0.5, 0.5, "Plain ends", "End only")))
        self.assertEqual(pf.shaft_file_name(pc.plan_shaft(4.0, 0.25, 0.25, "Tapped ends (#10-32)")),
                         "Shaft 0.5in hex x 4.500in tapped")
        self.assertEqual(pf.spacer_file_name(pc.plan_spacer(0.5, '0.75"')), "Spacer 0.75in OD x 0.490in")
        self.assertEqual(pf.spacer_file_name(pc.plan_spacer(0.5, '0.75"'), "PLA"), "Spacer 0.75in OD x 0.490in PLA")
        self.assertEqual(pf.spacer_file_name(pc.plan_spacer(0.5, '0.75"', clearance_in=0.004)),
                         "Spacer 0.75in OD x 0.490in bore 0.504")
        tube = pc.plan_tube("2x1", '1/16" wall', 24, True)
        self.assertEqual(pf.tube_file_name(tube), "Tube 2x1 1-16 wall x 24.000in")
        holes = pc.plan_tube("2x1", '1/8" wall', 24, True, '#10 close (0.196")', 2)
        self.assertEqual(pf.tube_file_name(holes), "Tube 2x1 1-8 wall x 24.000in holes 0.196 x2 rows")

    def test_matching(self):
        self.assertTrue(pf.matches("Shaft 0.5in hex x 4.500in", "shaft 0.5in hex x 4.500in"))
        self.assertTrue(pf.matches("27-INT-104 Shaft 0.5in hex x 4.500in", "Shaft 0.5in hex x 4.500in"))
        self.assertFalse(pf.matches("Shaft 0.5in hex x 4.500in tapped", "Shaft 0.5in hex x 4.500in"))
        self.assertFalse(pf.matches("Shaft 0.5in hex x 14.500in", "Shaft 0.5in hex x 4.500in"))

    def test_grouping(self):
        p = pf.Placement((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1))
        reqs = [pf.PartRequest("spacer", "Spacer A", None, placements=[p]),
                pf.PartRequest("spacer", "spacer a", None, placements=[p]),
                pf.PartRequest("shaft", "Shaft B", None, placements=[p])]
        grouped = pf.group_requests(reqs)
        self.assertEqual([g.file_name for g in grouped], ["Spacer A", "Shaft B"])
        self.assertEqual(len(grouped[0].placements), 2)


if __name__ == "__main__":
    unittest.main()
