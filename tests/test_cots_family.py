"""Family tiles, tags and recently/most used for the COTS panel."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from lib import cots_family as cf  # noqa: E402

H = '1/2" Hex Bore'


def part(fid, title, vendor="WCP", category="Gears"):
    d = cf.describe(title, vendor, category)
    d.update(file_id=fid, title=title)
    return d


class VariantTests(unittest.TestCase):
    def test_gear(self):
        self.assertEqual(cf.variant_of(f"18t Aluminum Spur Gear (20 DP, {H})"),
                         (f"Aluminum Spur Gear (20 DP, {H})", {"teeth": 18}))

    def test_pulley_teeth_and_width(self):
        self.assertEqual(cf.variant_of(f"15t x 9mm Wide Aluminum Pulley (HTD 5mm, {H})"),
                         (f"Aluminum Pulley (HTD 5mm, {H})", {"teeth": 15, "width_mm": 9}))
        # AndyMark wording
        fam, v = cf.variant_of("24 Tooth 0.5 in. Hex Bore 5 mm HTD 9 mm Wide Aluminum Pulley")
        self.assertEqual(v, {"teeth": 24, "width_mm": 9})
        self.assertNotIn("24", fam)

    def test_not_sized(self):
        self.assertEqual(cf.variant_of("Kraken X60 Powered by TalonFX")[1], {})
        self.assertEqual(cf.describe("NEO 2.0 Brushless Motor", "REV", "Motors")["family"], "")

    def test_families_dont_mix(self):
        parts = [part("a", f"18t Aluminum Spur Gear (20 DP, {H})"), part("b", f"20t Aluminum Spur Gear (20 DP, {H})"),
                 part("c", f"36t Steel Spur Gear (20 DP, {H})"), part("d", f"38t Steel Spur Gear (20 DP, {H})"),
                 part("e", f"52t Pocketed Steel Spur Gear (20 DP, {H})"),
                 part("f", f"52t Pocketed Steel Spur Gear with MotionX (20 DP, {H})"),
                 part("g", f"18t Aluminum Spur Gear (20 DP, {H})", vendor="REV"),
                 part("h", "50 Tooth 20 DP 0.5 in. Hex Bore Steel Gear", vendor="AndyMark")]
        fams = cf.build_families(parts)
        self.assertEqual(sorted(len(v) for v in fams.values()), [2, 2])           # aluminum + steel only
        alu = next(v for v in fams.values() if "aluminum" in v[0]["family"])
        self.assertEqual([p["file_id"] for p in alu], ["a", "b"])              # not REV's
        self.assertEqual(cf.family_range(alu), "18-20t")

    def test_pulley_range_and_label(self):
        parts = [part(str(t) + str(w), f"{t}t x {w}mm Wide Aluminum Pulley (HTD 5mm, {H})", category="Pulleys")
                 for t in (15, 36) for w in (9, 15)]
        fam = list(cf.build_families(parts).values())[0]
        self.assertEqual(cf.family_range(fam), "15-36t, 2 widths")
        self.assertEqual(fam[0]["variant_label"], "15t x 9mm")


class TagTests(unittest.TestCase):
    def test_tags(self):
        t = cf.tags_for(f"15t x 9mm Wide Aluminum Pulley (HTD 5mm, {H})")
        self.assertEqual((t["bore"], t["pitch"], t["width"], t["material"]), ('1/2" hex', "HTD 5mm", "9mm", "Aluminum"))
        self.assertEqual(cf.tags_for('14t Steel Spur Gear (20 DP, 1/2" Rounded Hex Bore)')["bore"], '1/2" rounded hex')
        self.assertEqual(cf.tags_for("18t x 9mm Wide Aluminum Pulley (HTD 5mm, 8mm SplineXS Bore)")["bore"],
                         "SplineXS (Kraken)")
        self.assertEqual(cf.tags_for("1/2 in. Hex ID 1.125 in. OD Shielded Flanged Bearing")["bore"], '1/2" hex')
        self.assertEqual(cf.tags_for('1/2" Hex Bore Aluminum Single Hub Sprocket (18t, #25 Chain)')["pitch"],
                         "#25 chain")
        self.assertEqual(cf.tags_for(f"66t Pocketed Steel Spur Gear with MotionX (20 DP, {H})")["style"], "MotionX")
        self.assertEqual(cf.tags_for("NEO 2.0 Brushless Motor"), {"bore": "", "pitch": "", "width": "",
                                                                  "material": "", "style": ""})


class UsageTests(unittest.TestCase):
    def test_recent_and_most(self):
        u = {}
        for fid, t in (("a", 1), ("b", 2), ("a", 3), ("c", 4)):
            u = cf.record_use(u, fid, t)
        self.assertEqual(u["a"], [2, 3.0])
        self.assertEqual(cf.recent(u), ["c", "a", "b"])
        self.assertEqual(cf.most_used(u)[0], "a")
        trimmed = cf.record_use({str(i): [1, i] for i in range(10)}, "new", 99, keep=5)
        self.assertEqual(len(trimmed), 5)
        self.assertIn("new", trimmed)

    def test_default_size(self):
        members = [{"file_id": "s"}, {"file_id": "m"}, {"file_id": "l"}]
        self.assertEqual(cf.pick_default(members), "s")
        self.assertEqual(cf.pick_default(members, {"l": [5, 1], "m": [2, 9]}), "l")


if __name__ == "__main__":
    unittest.main()
