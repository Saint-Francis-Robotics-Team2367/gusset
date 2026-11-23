"""Tests for the COTS library's formats, checks and search."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from lib import cots_core as cc  # noqa: E402


def neo():
    return cc.CotsInfo(name="NEO Brushless Motor V1.1", vendor="REV", vendor_pn="REV-21-1650", category="Motors",
                       price="48.00", url="https://www.revrobotics.com/rev-21-1650/", added_by="[STUDENT]")


class FormatTests(unittest.TestCase):
    def test_file_name(self):
        self.assertEqual(cc.part_file_name("REV-21-1650", "NEO Brushless Motor V1.1"),
                         "REV-21-1650 NEO Brushless Motor V1.1")
        self.assertEqual(cc.part_file_name("am-4255", 'am-4255 6" HiGrip Wheel'), "am-4255 6in HiGrip Wheel")
        self.assertEqual(cc.part_file_name("TTB-0060", "Cam / Tensioner"), "TTB-0060 Cam - Tensioner")

    def test_description_round_trip(self):
        text = cc.to_description(neo())
        self.assertTrue(text.startswith("Gusset COTS"))
        self.assertIn("Part #: REV-21-1650", text)
        back = cc.parse_description(text)
        self.assertEqual(back, neo())
        self.assertIsNone(cc.parse_description("Made by someone"))

    def test_guess_from_team_5000_style_name(self):
        g = cc.guess_from_file_name("WCP-0123 Thunderhex Bearing")
        self.assertEqual((g.vendor, g.vendor_pn, g.name), ("WCP", "WCP-0123", "Thunderhex Bearing"))
        self.assertEqual(cc.guess_from_file_name("Kraken X60").vendor, "")

    def test_attrs_and_links(self):
        a = cc.attrs_for(neo())
        self.assertEqual(a["cots"], "true")
        self.assertEqual(a["cots_price"], "48.00")
        info = cc.CotsInfo(name="x", vendor="WCP", vendor_pn="WCP-0123")
        self.assertEqual(cc.vendor_link(info), "https://wcproducts.com/search?q=WCP-0123")
        self.assertEqual(cc.vendor_link(neo()), neo().url)
        self.assertNotIn("cots_price", cc.attrs_for(info))


class CheckTests(unittest.TestCase):
    def test_good_part(self):
        c = cc.check_info(neo())
        self.assertTrue(c.ok, c.errors)
        self.assertEqual(c.warnings, [])

    def test_errors_and_warnings(self):
        c = cc.check_info(cc.CotsInfo())
        self.assertGreaterEqual(len(c.errors), 4)
        bad = neo()
        bad.vendor_pn, bad.price, bad.url = "REV 21 1650", "about 50", "www.rev.com"
        c = cc.check_info(bad)
        self.assertTrue(any("spaces" in e for e in c.errors))
        self.assertTrue(any("number of dollars" in e for e in c.errors))
        self.assertTrue(any("http" in e for e in c.errors))
        odd = neo()
        odd.vendor_pn = "21-1650"
        self.assertTrue(any("REV-21-1650" in w for w in cc.check_info(odd).warnings))
        ttb = cc.CotsInfo(name="Swerve top plate", vendor="TTB", vendor_pn="TTB-S-02-v1.1", category="Wheels",
                          url="https://x.y")
        self.assertFalse(any("usually look like" in w for w in cc.check_info(ttb).warnings))

    def test_duplicates_blocked(self):
        existing = [cc.CatalogItem("id1", "REV-21-1650 NEO", "Motors", "REV", neo())]
        c = cc.check_info(neo(), existing)
        self.assertFalse(c.ok)
        self.assertIn("already in the library", c.errors[0])


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.items = [
            cc.make_item("a", "REV-21-1650 NEO Brushless Motor V1.1", ["Motors", "REV"], cc.to_description(neo())),
            cc.make_item("b", "WCP-0123 Thunderhex Bearing", ["Bearings", "WCP"], ""),
            cc.make_item("c", "am-4255 6in HiGrip Wheel", ["Wheels", "AndyMark"], ""),
            cc.make_item("d", "Kraken X60", ["Motors"], ""),
        ]

    def test_make_item(self):
        self.assertEqual(self.items[0].title, "NEO Brushless Motor V1.1")
        self.assertEqual(self.items[1].info.vendor_pn, "WCP-0123")
        self.assertEqual(self.items[3].vendor, "")
        self.assertEqual(self.items[3].category, "Motors")

    def test_search(self):
        motors = [i.file_id for i in cc.search(self.items, "motor")]
        self.assertEqual(motors[0], "a")                       # 'Motor' in the name beats the category
        self.assertIn("d", motors)                             # the Kraken is in the Motors category
        self.assertEqual({i.file_id for i in cc.search(self.items, category="Motors")}, {"a", "d"})
        self.assertEqual(cc.search(self.items, "REV-21-1650")[0].file_id, "a")
        self.assertEqual([i.file_id for i in cc.search(self.items, "wcp bearing")], ["b"])
        self.assertEqual(cc.search(self.items, "nothing like this"), [])
        favs = cc.search(self.items, favorites=["c"], favorites_only=True)
        self.assertEqual([i.file_id for i in favs], ["c"])
        self.assertEqual({i.file_id for i in cc.search(self.items, vendor="REV")}, {"a"})

    def test_json_round_trip(self):
        text = cc.catalog_to_json(self.items, 123.0)
        back, stamp = cc.catalog_from_json(text)
        self.assertEqual(stamp, 123.0)
        self.assertEqual([b.file_id for b in back], ["a", "b", "c", "d"])
        self.assertEqual(back[0].info, self.items[0].info)
        self.assertEqual(cc.catalog_from_json("not json"), ([], 0.0))

    def test_thumb_names_are_safe(self):
        name = cc.thumb_file_name("urn:adsk.wipprod:dm.lineage:AQoaJ1TISyu3M_dCt4tBqg")
        self.assertTrue(name.endswith(".png"))
        self.assertNotIn(":", name)


if __name__ == "__main__":
    unittest.main()


class DuplicateTests(unittest.TestCase):
    """The same product shouldn't end up in the library twice under different vendors."""

    def lib(self):
        return [
            cc.make_item("k60", "WCP-0940 Kraken X60 Powered by TalonFX", ["Motors", "WCP"], ""),
            cc.make_item("p24", "am-4625 24 Tooth Hex Bore HTD Pulley", ["Pulleys", "AndyMark"], ""),
            cc.make_item("brg", "am-2986 1-2in Hex 1.125in OD Flanged Bearing", ["Bearings", "AndyMark"], ""),
        ]

    def test_same_part(self):
        self.assertTrue(cc.same_part("WCP Kraken X60 Powered by TalonFX", "Kraken X60"))
        self.assertFalse(cc.same_part("Kraken X60", "Kraken X44"))
        self.assertFalse(cc.same_part("24t HTD Pulley 1/2in hex", "36t HTD Pulley 1/2in hex"))
        self.assertTrue(cc.same_part("24 Tooth HTD Pulley", "24t HTD 5mm pulley"))
        self.assertFalse(cc.same_part("NEO Vortex", "NEO 550"))
        self.assertFalse(cc.same_part("Through Bore Encoder", "Color Sensor V3"))
        self.assertFalse(cc.same_part("SPARK MAX Motor Controller", "SPARK Flex Motor Controller"))
        # WCP sells all of these as separate products
        self.assertFalse(cc.same_part('36t Steel Spur Gear (20 DP, 1/2" Hex Bore)',
                                      '36t Pocketed Steel Spur Gear (20 DP, 1/2" Hex Bore)'))
        self.assertFalse(cc.same_part('52t Pocketed Steel Spur Gear (20 DP, 1/2" Hex Bore)',
                                      '52t Pocketed Steel Spur Gear with MotionX (20 DP, 1/2" Hex Bore)'))
        self.assertFalse(cc.same_part('18t x 9mm Wide Aluminum Pulley (HTD 5mm, 8mm SplineXS Bore)',
                                      '18t x 9mm Wide Aluminum Pulley (HTD 5mm, 8mm Key Bore)'))
        self.assertTrue(cc.same_part('36t Steel Spur Gear (20 DP, 1/2" Hex Bore)', 'WCP 36t Steel Spur Gear'))

    def test_other_vendor_blocked_until_ticked(self):
        k = cc.CotsInfo(name="Kraken X60", vendor="TTB", vendor_pn="TTB-9999", category="Motors", url="https://x.y")
        c = cc.check_info(k, self.lib())
        self.assertFalse(c.ok)
        self.assertIn("Kraken X60 Powered by TalonFX", c.errors[0])
        c = cc.check_info(k, self.lib(), different_part=True)
        self.assertTrue(c.ok, c.errors)
        self.assertTrue(any("saving anyway" in w for w in c.warnings))

    def test_same_number_other_vendor(self):
        # SDS parts are sold by AndyMark; CTRE sells Krakens under WCP's number
        dup = cc.CotsInfo(name="Kraken X60 motor", vendor="REV", vendor_pn="WCP-0940", category="Motors")
        c = cc.check_info(dup, self.lib(), different_part=True)
        self.assertTrue(any("under WCP" in e for e in c.errors))   # same part # can't be overridden

    def test_different_sizes_are_fine(self):
        p36 = cc.CotsInfo(name="36 Tooth Hex Bore HTD Pulley", vendor="AndyMark", vendor_pn="am-4626",
                          category="Pulleys", url="https://x.y")
        self.assertTrue(cc.check_info(p36, self.lib()).ok)

    def test_library_audit(self):
        items = self.lib() + [cc.make_item("k2", "Kraken X60", ["Motors", "TTB"], "")]
        pairs = cc.find_duplicates(items)
        self.assertEqual([(a.file_id, b.file_id) for a, b in pairs], [("k60", "k2")])


class BatchImportTests(unittest.TestCase):
    STARTER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "resources", "cots_starter_parts.csv")

    def starter(self):
        with open(self.STARTER, encoding="utf-8") as handle:
            return cc.parse_parts_list(handle.read())

    def test_starter_list_is_clean(self):
        infos, problems = self.starter()
        self.assertEqual(problems, [])
        self.assertEqual(len(infos), 45)
        pns = [i.vendor_pn for i in infos if i.vendor_pn]
        self.assertEqual(len(pns), len(set(pns)), "duplicate part numbers in the starter list")
        items = [cc.CatalogItem(i.vendor_pn, cc.part_file_name(i.vendor_pn, i.name), i.category, i.vendor, i)
                 for i in infos]
        pairs = [(a.info.vendor_pn, b.info.vendor_pn) for a, b in cc.find_duplicates(items)]
        self.assertEqual(pairs, [])       # the one look-alike (am-2986 / REV-21-1915) is marked "Different part"
        self.assertTrue(next(i for i in infos if i.vendor_pn == "REV-21-1915").different_part)
        for i in infos:
            self.assertIn(i.category, cc.DEFAULT_CATEGORIES)
            if i.vendor_pn:
                c = cc.check_info(i)
                self.assertTrue(c.ok, (i.vendor_pn, c.errors))

    def test_step_matching(self):
        files = ["am-2986 FR8ZZ Hex Bearing.STEP", "REV-21-1652.step", "WCP-07330.step", "wcp_0733 gear.stp",
                 "notes.txt", "am-4756 MK4i L2 Kraken.STEP", "am-4756 MK4i L3 Kraken.STEP"]
        self.assertEqual(cc.step_files_for("am-2986", files), ["am-2986 FR8ZZ Hex Bearing.STEP"])
        self.assertEqual(cc.step_files_for("WCP-0733", files), ["wcp_0733 gear.stp"])
        self.assertEqual(cc.step_files_for("REV-21-165", files), [])
        self.assertEqual(len(cc.step_files_for("am-4756", files)), 2)

    def test_plan(self):
        infos, _ = self.starter()
        kraken60 = cc.CotsInfo(name="Kraken X60 Powered by TalonFX", vendor="WCP", vendor_pn="WCP-0940",
                               category="Motors")
        lib = [cc.CatalogItem("k", "WCP-0940 Kraken X60 Powered by TalonFX", "Motors", "WCP", kraken60)]
        files = ["WCP-0941 Kraken X44.step", "am-2986.STEP", "am-4756 a.STEP", "am-4756 b.STEP", "random part.step"]
        extra = infos + [kraken60, cc.CotsInfo(name="Kraken X60", vendor="TTB", vendor_pn="TTB-9", category="Motors")]
        rows = cc.plan_import(extra, files + ["TTB-9.step"], lib)
        by_pn = {r.info.vendor_pn: r for r in rows}
        self.assertEqual(by_pn["WCP-0941"].status, cc.READY)
        self.assertEqual(by_pn["am-2986"].status, cc.READY)
        self.assertEqual(by_pn["am-4756"].status, cc.TWO_FILES)
        self.assertEqual(by_pn["REV-21-1652"].status, cc.NO_STEP)
        self.assertEqual(by_pn[""].status, cc.NO_PN)
        self.assertEqual(by_pn["WCP-0940"].status, cc.IN_LIBRARY)
        self.assertEqual(by_pn["TTB-9"].status, cc.NEEDS_LOOK)          # look-alike of the Kraken X60
        self.assertEqual(cc.unmatched_steps(rows, files), ["random part.step"])
        self.assertEqual(cc.import_summary(rows)[cc.READY], 2)

    def test_csv_round_trip_and_bad_headers(self):
        infos, _ = self.starter()
        back, problems = cc.parse_parts_list(cc.parts_list_csv(infos))
        self.assertEqual(back, infos)
        self.assertTrue(cc.parse_parts_list("Name,Price\nx,1")[1])


class RepeatDownloadTests(unittest.TestCase):
    def test_drop_repeats(self):
        sizes = {"WCP-1434.step": 100, "WCP-1434 (1).step": 100, "am-4756 (1).STEP": 50, "am-4756.STEP": 70,
                 "x (2).step": 5}
        self.assertEqual(cc.drop_repeat_downloads(sizes),
                         ["WCP-1434.step", "am-4756 (1).STEP", "am-4756.STEP", "x (2).step"])
