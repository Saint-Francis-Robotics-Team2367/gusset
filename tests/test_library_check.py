"""Library Check (0.11)."""

import datetime as dt
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from lib import cots_core as cc  # noqa: E402
from lib import library_check as lc  # noqa: E402

TODAY = dt.date(2026, 11, 22)
REAL = "/mnt/user-data/uploads/FRC Plugins/Gusset/cache/cots_catalog.json"


def item(fid="urn:1", pn="WCP-0712", name='42t Aluminum Spur Gear (20 DP, 1/2" Hex Bore)', vendor="WCP",
         cat="Gears", price="12.99", url="https://wcproducts.com/products/x", file_name=None, folder_vendor=None,
         folder_cat=None, thumb="t.png", added="2026-11-20", different=False):
    info = cc.CotsInfo(name=name, vendor=vendor, vendor_pn=pn, category=cat, price=price, url=url,
                       added_on=added, different_part=different)
    return cc.CatalogItem(fid, file_name or cc.part_file_name(pn, name), folder_cat or cat,
                          folder_vendor or vendor, info, 1, thumb)


def kinds(problems):
    return sorted(p.kind for p in problems)


class CheckTests(unittest.TestCase):
    def test_clean_part(self):
        self.assertEqual(lc.check([item()], today=TODAY), [])

    def test_missing_details(self):
        p = lc.check([item(price="", url="")], today=TODAY)
        self.assertEqual(kinds(p), ["no_link", "no_price"])
        link = next(x for x in p if x.kind == "no_link")
        self.assertEqual(link.suggest["url"], "https://wcproducts.com/search?q=WCP-0712")
        self.assertTrue(all(x.level == lc.INFO for x in p))

    def test_bad_values(self):
        p = lc.check([item(price="call", url="https://amazon.com/x", pn="0712")], today=TODAY)
        self.assertEqual(kinds(p), ["bad_price", "part_number", "wrong_link"])
        p = lc.check([item(file_name="gear 42")], today=TODAY)
        self.assertEqual((kinds(p), p[0].suggest["name"]), (["name"], 'WCP-0712 42t Aluminum Spur Gear (20 DP, 1-2in Hex Bore)'))

    def test_sds_on_andymark_is_fine(self):
        self.assertEqual(lc.check([item(vendor="SDS", pn="am-5248", name="MK5n Module",
                                       url="https://www.andymark.com/products/mk5n")], today=TODAY), [])

    def test_duplicates_keep_fuller_file(self):
        full = item("urn:a")
        thin = item("urn:b", price="", url="", thumb="")
        p = [x for x in lc.check([thin, full], today=TODAY) if x.kind == "duplicate"]
        self.assertEqual(len(p), 1)
        self.assertEqual((p[0].file_id, p[0].other_id, p[0].fix), ("urn:b", "urn:a", "review"))

    def test_marked_different_isnt_duplicate(self):
        a = item("urn:a", pn="am-2986", vendor="AndyMark", name="1/2 in. Hex Flanged Bearing",
                 url="https://www.andymark.com/x")
        b = item("urn:b", pn="REV-21-1915", vendor="REV", name="1/2 in. Hex Flanged Bearing",
                 url="https://www.revrobotics.com/x", different=True)
        self.assertEqual([x for x in lc.check([a, b], today=TODAY) if x.kind == "duplicate"], [])

    def test_folder_and_ids(self):
        p = lc.check([item("C:/temp/_x.f3d", folder_vendor="REV")], no_thumbnail=["C:/temp/_x.f3d"], today=TODAY)
        self.assertEqual(kinds(p), ["folder", "no_picture", "temp_id"])
        self.assertEqual(kinds(lc.check([item()], missing=["urn:1"], today=TODAY)), ["missing"])

    def test_old_price_and_ignore(self):
        p = lc.check([item(added="2025-01-05")], today=TODAY)
        self.assertEqual(kinds(p), ["old_price"])
        self.assertEqual(lc.check([item(added="2025-01-05")], ignored=[p[0].key], today=TODAY), [])

    def test_badge(self):
        s = lc.summary(lc.check([item(price=""), item("urn:2", pn="WCP-0713", name="NEO Motor", price="", file_name="oops")],
                                today=TODAY))
        self.assertEqual(lc.badge_text(s), "1 to fix")
        s = lc.summary(lc.check([item(price="")], today=TODAY))
        self.assertEqual(lc.badge_text(s), "1 missing price")
        self.assertEqual(lc.badge_text(lc.summary([])), "")

    def test_json(self):
        d = lc.check([item(price="")], today=TODAY)[0].to_json()
        self.assertEqual((d["group"], d["key"]), ("price", "no_price:urn:1"))
        json.dumps(d)

    @unittest.skipUnless(os.path.exists(REAL), "real catalog not staged")
    def test_real_library(self):
        items, _ = cc.catalog_from_json(open(REAL).read())
        s = lc.summary(lc.check(items, today=TODAY))
        self.assertEqual(s[lc.FIX], 0)               # the library is clean apart from prices
        self.assertGreater(s["no_price"], 90)


class DetailTests(unittest.TestCase):
    def test_apply_and_check(self):
        info = item(price="").info
        new = lc.apply_details(info, {"price": "$1,204.50"})
        self.assertEqual((new.price, info.price), ("1204.50", ""))
        self.assertEqual(lc.check_details(new), [])
        self.assertEqual(len(lc.check_details(lc.apply_details(info, {"price": "abc", "url": "ftp://x",
                                                                      "vendor_pn": "12"}))), 3)

    def test_description_round_trip_keeps_different_part(self):
        info = item(different=True).info
        back = cc.parse_description(cc.to_description(info))
        self.assertTrue(back.different_part)
        self.assertFalse(cc.parse_description(cc.to_description(item().info)).different_part)

    def test_revision_note(self):
        info = item().info
        info.notes = "MotionX insert | Updated from old.step on 2026-01-01"
        self.assertEqual(lc.revision_note(info, "WCP-0712.step", TODAY),
                         "MotionX insert | Updated from WCP-0712.step on 2026-11-22")


if __name__ == "__main__":
    unittest.main()
