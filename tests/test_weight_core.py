"""Robot Weight panel (0.13)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from lib import bom_core as bc  # noqa: E402
from lib import weight_core as wc  # noqa: E402


def row(key, name, kind, qty, lb, material="6061 Aluminum", sub="DRV", used_in="Drivetrain", pn=""):
    return bc.BomRow(key, name, pn or key, name, kind, qty=qty, mass_lb=lb, material=material, subsystem=sub,
                     used_in=used_in)


def bom():
    return bc.Bom("Robot", flat=[
        row("asm", "Drivetrain", bc.TYPE_ASSEMBLY, 1, 30.0),                        # never counted
        row("neo", "NEO 2.0", bc.TYPE_COTS, 4, 0.94, material="", sub="DRV"),
        row("plate", "Side plate", bc.TYPE_MADE, 2, 1.5),
        row("guess", "Bracket", bc.TYPE_MADE, 6, 0.2, material="Steel", sub="ELV", used_in="Elevator"),
        row("bump", "Bumper frame", bc.TYPE_MADE, 4, 3.0, material="Plywood", sub="BMP", used_in="Bumpers"),
        row("batt", "Battery", bc.TYPE_COTS, 1, 13.0, material="", sub="ELE", used_in="Robot"),
        row("noodle", "Pool noodle", bc.TYPE_COTS, 8, 0.1, material="", sub="BMP", used_in="Red bumper"),
        row("??", "Mystery", bc.TYPE_MADE, 1, None),
    ])


class ReportTests(unittest.TestCase):
    def test_totals(self):
        r = wc.report(bom(), subsystem_names={"DRV": "Drivetrain", "ELV": "Elevator"})
        self.assertAlmostEqual(r.robot_lb, 4 * 0.94 + 2 * 1.5 + 6 * 0.2)
        self.assertAlmostEqual(r.bumpers_lb, 12.8)
        self.assertAlmostEqual(r.battery_lb, 13.0)
        self.assertEqual([n for n, _ in r.by_subsystem], ["Drivetrain", "Elevator"])
        self.assertEqual(r.heaviest[0].key, "neo")
        self.assertEqual([p.key for p in r.no_material], ["guess"])      # COTS on '' isn't flagged
        self.assertEqual((r.measured, r.unmeasured), (6, ["Mystery"]))
        self.assertEqual(r.status, wc.OK)
        self.assertIn("to spare", r.headline())

    def test_status_and_limits(self):
        self.assertEqual(wc.status_of(110, 115, 95), wc.CLOSE)
        self.assertEqual(wc.status_of(115.2, 115, 95), wc.OVER)
        self.assertEqual(wc.status_of(80, 115, 95), wc.OK)
        lim = wc.read_limits({"robot_lb": "120 lb", "robot_with_bumpers_lb": "junk", "warn_at_percent": -3})
        self.assertEqual(lim, {"robot_lb": 120.0, "robot_with_bumpers_lb": 135.0, "warn_at_percent": 95.0})
        r = wc.report(bom(), limits={"robot_lb": 5})
        self.assertEqual(r.status, wc.OVER)
        self.assertIn("OVER", r.headline())

    def test_ignore_really_steel(self):
        self.assertEqual(wc.report(bom(), ignored_materials=["guess"]).no_material, [])

    def test_json(self):
        import json
        d = wc.report(bom()).to_json()
        json.dumps(d)
        self.assertEqual(d["unmeasuredCount"], 1)
        self.assertEqual(d["withBumpers"], round(d["robot"] + d["bumpers"], 2))
