"""
Unit tests for the naming logic. No Fusion needed:
    cd Gusset
    python -m unittest discover -s tests -v
"""

import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from lib import naming_core as nc  # noqa: E402
from lib import settings  # noqa: E402

CFG = nc.NamingConfig(season_year="27")


def part(key, name, pn="", **kw):
    return nc.CompNode(key=key, name=name, part_number=pn or name, has_bodies=True, **kw)


def asm(key, name, children, pn=""):
    return nc.CompNode(key=key, name=name, part_number=pn or name, children=children)


class HelperTests(unittest.TestCase):
    def test_parse_and_format(self):
        self.assertEqual(nc.parse_part_number("27-ELV-104"), ("27", "ELV", 104))
        self.assertIsNone(nc.parse_part_number("27-ELV-14"))
        self.assertIsNone(nc.parse_part_number("Gusset"))
        self.assertEqual(nc.format_part_number("27", "ELV", 4), "27-ELV-004")

    def test_clean_description(self):
        self.assertEqual(nc.clean_description("27-ELV-104 Gusset Plate", CFG), "Gusset Plate")
        self.assertEqual(nc.clean_description("Gusset v12", CFG), "Gusset")
        self.assertEqual(nc.clean_description("Component7", CFG), "")
        self.assertEqual(nc.clean_description('Plate 1/4" thick', CFG), "Plate 1-4- thick")

    def test_cots_detection(self):
        for name in ("WCP-0123 Spacer", "am-4255", "91251A537", "Kraken X60", "Flanged Bearing"):
            self.assertTrue(nc.looks_like_cots(name, "", CFG), name)
        self.assertFalse(nc.looks_like_cots("Gusset Plate", "", CFG))
        for team_made in ("bearing block", "Bearing Plate", "intake bearing mount", "27-ARM-103 bearing block"):
            self.assertFalse(nc.looks_like_cots(team_made, "", CFG), team_made)
        self.assertTrue(nc.looks_like_cots("FR8ZZ bearing", "", CFG))
        self.assertTrue(nc.looks_like_cots("Bearings", "", CFG))

    def test_guess_subsystem(self):
        self.assertEqual(nc.guess_subsystem("Elevator Assembly", "", CFG), "ELV")
        self.assertEqual(nc.guess_subsystem("27-INT-100 Thing", "", CFG), "INT")
        self.assertIsNone(nc.guess_subsystem("Robot", "", CFG))

    def test_season_year_auto(self):
        self.assertEqual(settings.default_season_year(datetime.date(2026, 11, 2)), "27")
        self.assertEqual(settings.default_season_year(datetime.date(2027, 3, 1)), "27")

    def test_old_bearing_pattern_in_settings_is_upgraded(self):
        old = r"(?i)\b(bearing|bolt|screw|nut|washer|rivet|shaft collar)s?\b"
        cfg = settings.config_from_dict({"cots_patterns": [r"^am-\d", old, r"^MyVendor-"]},
                                        today=datetime.date(2026, 11, 2))
        self.assertIn(r"^MyVendor-", cfg.cots_patterns)
        self.assertNotIn(old, cfg.cots_patterns)
        self.assertFalse(nc.looks_like_cots("bearing block", "", cfg))
        self.assertTrue(nc.looks_like_cots("hex bolt", "", cfg))

    def test_bad_settings_fall_back(self):
        cfg = settings.config_from_dict({"season_year": "2027", "subsystems": {"bad code!": "x"},
                                         "cots_patterns": ["(unclosed"]},
                                        today=datetime.date(2026, 11, 2))
        self.assertEqual(cfg.season_year, "27")
        self.assertEqual(cfg.subsystems, nc.DEFAULT_SUBSYSTEMS)


class PlanTests(unittest.TestCase):
    def elevator(self):
        carriage = asm("car", "Carriage", [part("rl", "Roller"), part("b", "Flanged Bearing")])
        return asm("elv", "Elevator", [
            part("g", "Gusset Plate"),
            part("s", "Component3"),
            carriage,
            part("g", "Gusset Plate"),        # same component used twice
            nc.CompNode(key="e", name="Empty"),
        ])

    def test_hundreds_blocks(self):
        plan = nc.plan_subsystem(self.elevator(), "ELV", CFG)
        self.assertIsNone(plan.fatal)
        pns = {p.key: p.part_number for p in plan.proposals}
        self.assertEqual(pns["elv"], "27-ELV-100")
        self.assertEqual(pns["g"], "27-ELV-101")
        self.assertEqual(pns["s"], "27-ELV-102")
        self.assertEqual(pns["car"], "27-ELV-200")
        self.assertEqual(pns["rl"], "27-ELV-201")
        by = plan.by_key()
        self.assertEqual(by["b"].status, nc.STATUS_COTS)
        self.assertEqual(by["e"].status, nc.STATUS_SKIP)
        self.assertEqual(by["s"].status, nc.STATUS_WARN)   # Component3 needs a description
        self.assertEqual(by["g"].instances, 2)
        self.assertEqual(by["g"].new_name, "27-ELV-101 Gusset Plate")

    def test_keeps_good_numbers_and_avoids_used(self):
        root = asm("elv", "27-ELV-100 Elevator", [
            part("a", "27-ELV-105 Axle"),
            part("b", "Bracket"),
        ], pn="27-ELV-100")
        plan = nc.plan_subsystem(root, "ELV", CFG, used_elsewhere={101})
        by = plan.by_key()
        self.assertEqual(by["a"].part_number, "27-ELV-105")
        self.assertTrue(by["a"].kept)
        self.assertEqual(by["b"].part_number, "27-ELV-102")  # 101 taken elsewhere

    def test_renumber_all(self):
        root = asm("elv", "Elevator", [part("a", "27-ELV-105 Axle")])
        plan = nc.plan_subsystem(root, "ELV", CFG, keep_existing=False)
        self.assertEqual(plan.by_key()["a"].part_number, "27-ELV-101")

    def test_old_season_gets_renumbered(self):
        root = asm("elv", "Elevator", [part("a", "26-ELV-101 Axle")])
        p = nc.plan_subsystem(root, "ELV", CFG).by_key()["a"]
        self.assertEqual(p.part_number, "27-ELV-101")
        self.assertIn("another season", p.message)

    def test_duplicate_existing_numbers(self):
        root = asm("elv", "Elevator", [part("a", "27-ELV-101 A"), part("b", "27-ELV-101 B")])
        by = nc.plan_subsystem(root, "ELV", CFG).by_key()
        self.assertNotEqual(by["a"].part_number, by["b"].part_number)

    def test_assembly_adopts_block_of_its_numbered_parts(self):
        sub = asm("sub", "Sub", [part("a", "27-ELV-104 Axle")])
        root = asm("elv", "Elevator", [sub])
        by = nc.plan_subsystem(root, "ELV", CFG).by_key()
        self.assertEqual(by["sub"].part_number, "27-ELV-100")
        self.assertEqual(by["a"].part_number, "27-ELV-104")   # student's number survives
        self.assertEqual(by["elv"].part_number, "27-ELV-200")

    def test_part_moved_when_its_block_belongs_to_another_assembly(self):
        root = asm("elv", "27-ELV-100 Elevator", [
            asm("sub", "Sub", [part("a", "27-ELV-104 Axle")]),
        ], pn="27-ELV-100")
        by = nc.plan_subsystem(root, "ELV", CFG).by_key()
        self.assertEqual(by["sub"].part_number, "27-ELV-200")
        self.assertEqual(by["a"].part_number, "27-ELV-201")
        self.assertIn("moved", by["a"].message)

    def test_overrides(self):
        root = asm("elv", "Elevator", [part("a", "Component1"), part("b", "Spacer")])
        plan = nc.plan_subsystem(root, "ELV", CFG, overrides={
            "a": {"description": "Belt Tensioner"}, "b": {"cots": True}})
        by = plan.by_key()
        self.assertEqual(by["a"].new_name, "27-ELV-101 Belt Tensioner")
        self.assertEqual(by["b"].status, nc.STATUS_COTS)

    def test_linked_team_part_is_numbered(self):
        shaft = part("x", "output shaft", pn="Output Shaft", is_external=True, file_id="f-shaft", owner_file="f-shaft")
        root = asm("drv", "Drivetrain", [shaft])
        p = nc.plan_subsystem(root, "DRV", CFG).by_key()["x"]
        self.assertEqual(p.new_name, "27-DRV-101 Output Shaft")
        self.assertTrue(p.is_file)

    def test_top_assembly_with_cots_word_is_still_ours(self):
        root = asm("gb", "NEO Gearbox", [part("g", "14T Gear"), part("b", "Flanged Bearing")])
        plan = nc.plan_subsystem(root, "DRV", CFG)
        self.assertIsNone(plan.fatal)
        by = plan.by_key()
        self.assertEqual(by["gb"].part_number, "27-DRV-100")
        self.assertEqual(by["g"].part_number, "27-DRV-101")
        self.assertEqual(by["b"].status, nc.STATUS_COTS)

    def test_multibody_top_explains_components(self):
        plan = nc.plan_subsystem(part("p", "Gearbox"), "DRV", CFG)
        self.assertIn("Create Components from Bodies", plan.fatal)

    def test_fatal_cases(self):
        self.assertIsNotNone(nc.plan_subsystem(part("p", "Plate"), "ELV", CFG).fatal)
        self.assertIsNotNone(nc.plan_subsystem(self.elevator(), "NOPE", CFG).fatal)
        self.assertIsNotNone(nc.plan_subsystem(None, "ELV", CFG).fatal)

    def test_block_full(self):
        root = asm("elv", "Elevator", [part(f"p{i}", f"Plate {i}") for i in range(100)])
        plan = nc.plan_subsystem(root, "ELV", CFG)
        errors = [p for p in plan.proposals if p.status == nc.STATUS_ERROR]
        self.assertEqual(len(errors), 1)
        self.assertIn("full", errors[0].message)

    def test_already_correct_is_ok(self):
        root = asm("elv", "27-ELV-100 Elevator", [part("a", "27-ELV-101 Axle", pn="27-ELV-101")],
                   pn="27-ELV-100")
        plan = nc.plan_subsystem(root, "ELV", CFG)
        self.assertEqual(plan.by_key()["a"].status, nc.STATUS_OK)
        self.assertEqual(plan.changes(), [])


def linked(key, name, pn="", parents=(), children=None):
    """A component that lives in its own Fusion file."""
    node = nc.CompNode(key=key, name=name, part_number=pn or name, has_bodies=not children,
                       is_external=True, file_id=f"f-{key}", file_name=name, owner_file=f"f-{key}",
                       parent_files=list(parents), children=list(children or []))
    return node


class LinkedAndSharedTests(unittest.TestCase):
    def real_gearbox(self):
        """Mirror of 'Gearbox Assembly v2' from the team's 2025 offseason project."""
        root = asm("root", "Gearbox Assembly v2", [
            part("mmp", "motor mounting plate"),
            linked("cim", "am-0255 2.5inch CIM Motor (1)", pn="am-0255 2.5inch CIM Motor"),
            linked("brg", "am-0030 0.5'' id Flanged, Shielded Ball Bearing (FR8ZZ) (1)"),
            linked("w903", "WCP-0903", pn="WCP-0903 Rev1"),
            linked("w720", "WCP-0720", pn="WCP-0720 Rev1"),
            linked("so", "standoff", pn="Standoff", parents=[("f-root", "Gearbox Assembly v2")]),
            linked("so", "standoff", pn="Standoff"),
            part("mp", "mounting plate", pn="Mounting Plate"),
            linked("os", "output shaft", pn="Output Shaft"),
            linked("hb", "am-2986 FR8ZZ Hex Bearing (1)"),
            linked("wh", "am-0940b 6 in HiGrip Wheel", pn="am-0940b 6 HiGrip", children=[
                part("rim", "6 wheel Rev 4"), part("tread", "6 wheel tread II")]),
            linked("hub", "am-2568 500EX Hex Hub"),
            linked("shcs", "Hexagon Socket Head Cap Screw ANSI B18.3 - 10-24 UNC x 9/16 Steel Grade 2 Plain"),
            linked("nut", "Hex Nut ANSI B18.2.2 - #10-32 Steel Grade 2H Plain"),
        ])
        root.file_id = "f-root"
        return root

    def test_real_gearbox(self):
        plan = nc.plan_subsystem(self.real_gearbox(), "DRV", CFG)
        self.assertIsNone(plan.fatal)
        by = plan.by_key()
        self.assertEqual(by["root"].new_name, "27-DRV-100 Gearbox Assembly")
        self.assertEqual(by["mmp"].new_name, "27-DRV-101 motor mounting plate")
        self.assertEqual(by["so"].new_name, "27-DRV-102 Standoff")
        self.assertEqual(by["so"].instances, 2)
        self.assertEqual(by["mp"].new_name, "27-DRV-103 Mounting Plate")
        self.assertEqual(by["os"].new_name, "27-DRV-104 Output Shaft")
        for key in ("cim", "brg", "w903", "w720", "hb", "wh", "hub", "shcs", "nut"):
            self.assertEqual(by[key].status, nc.STATUS_COTS, key)
        self.assertEqual(by["rim"].status, nc.STATUS_SKIP)   # inside the COTS wheel
        self.assertEqual(plan.files_to_save(), {"f-so", "f-os"})

    def test_part_shared_with_another_subsystem_goes_to_msc(self):
        so = linked("so", "standoff", parents=[("f-root", "Gearbox"), ("f-int", "27-INT-100 Intake")])
        root = asm("root", "Gearbox", [part("p", "Plate"), so])
        root.file_id = "f-root"
        by = nc.plan_subsystem(root, "DRV", CFG).by_key()
        self.assertEqual(by["so"].part_number, "27-MSC-101")
        self.assertTrue(by["so"].shared)
        self.assertEqual(by["p"].part_number, "27-DRV-101")

    def test_existing_number_moves_to_msc_when_shared(self):
        so = linked("so", "27-DRV-105 Standoff", parents=[("f-int", "27-INT-100 Intake")])
        root = asm("root", "Gearbox", [so])
        p = nc.plan_subsystem(root, "DRV", CFG, used_elsewhere={"MSC": [101]}).by_key()["so"]
        self.assertEqual(p.part_number, "27-MSC-102")
        self.assertIn("shared", p.message)

    def test_msc_number_is_sticky(self):
        so = linked("so", "27-MSC-104 Standoff", pn="27-MSC-104")
        root = asm("root", "Intake", [so])
        p = nc.plan_subsystem(root, "INT", CFG).by_key()["so"]
        self.assertEqual(p.part_number, "27-MSC-104")
        self.assertEqual(p.status, nc.STATUS_OK)

    def test_same_subsystem_parent_is_not_shared(self):
        so = linked("so", "standoff", parents=[("f-x", "27-DRV-300 Other Gearbox")])
        root = asm("root", "Gearbox", [so])
        self.assertFalse(nc.plan_subsystem(root, "DRV", CFG).by_key()["so"].shared)

    def test_shared_tick_and_shared_assembly_children(self):
        sub = linked("gb", "Gearbox", children=[part("g", "Gear")])
        root = asm("root", "Drivetrain", [sub])
        by = nc.plan_subsystem(root, "DRV", CFG, overrides={"gb": {"shared": True}}).by_key()
        self.assertEqual(by["gb"].part_number, "27-MSC-100")
        self.assertEqual(by["g"].part_number, "27-MSC-101")

    def test_shared_off_in_settings(self):
        cfg = nc.NamingConfig(season_year="27", shared_code="")
        so = linked("so", "standoff", parents=[("f-int", "27-INT-100 Intake")])
        root = asm("root", "Gearbox", [so])
        self.assertEqual(nc.plan_subsystem(root, "DRV", cfg).by_key()["so"].part_number, "27-DRV-101")

    def test_used_numbers_dict(self):
        root = asm("root", "Gearbox", [part("p", "Plate")])
        by = nc.plan_subsystem(root, "DRV", CFG, used_elsewhere={"DRV": [100, 101]}).by_key()
        self.assertEqual(by["root"].part_number, "27-DRV-200")
        self.assertEqual(by["p"].part_number, "27-DRV-201")

    def numbered_gearbox(self, extra_children=()):
        """Gearbox numbered on its own first (a real team test), now a linked file."""
        plate = part("mmp", "27-GRB-101 motor mounting plate", pn="27-GRB-101")
        plate.owner_file = "f-gb"
        children = [plate, linked("so", "27-GRB-102 Standoff", pn="27-GRB-102",
                                  parents=[("f-gb", "27-GRB-100 Gearbox Assembly")]),
                    linked("cim", "am-0255 2.5inch CIM Motor (1)")] + list(extra_children)
        gb = linked("gb", "27-GRB-100 Gearbox Assembly (1)", pn="27-GRB-100", children=children)
        gb.file_name = "27-GRB-100 Gearbox Assembly"
        return gb

    def minibot(self, gearbox):
        root = asm("root", "MINIBOTS Chassis assembly", [
            part("rail", "side frame rails"),
            gearbox,
            gearbox,                                   # two copies of the same file
        ])
        root.file_id, root.file_name = "f-root", "MINIBOTS Chassis assembly"
        return root

    def test_numbered_gearbox_keeps_its_subsystem_inside_chassis(self):
        plan = nc.plan_subsystem(self.minibot(self.numbered_gearbox()), "DRV", CFG,
                                 used_elsewhere={"GRB": []})
        by = plan.by_key()
        self.assertEqual(by["root"].part_number, "27-DRV-100")
        self.assertEqual(by["rail"].part_number, "27-DRV-101")
        self.assertEqual(by["gb"].part_number, "27-GRB-100")
        self.assertEqual(by["gb"].status, nc.STATUS_OK)
        self.assertEqual(by["gb"].instances, 2)
        self.assertIn("keeps its GRB number", by["gb"].message)
        self.assertEqual(by["mmp"].status, nc.STATUS_OK)
        self.assertEqual(by["so"].status, nc.STATUS_OK)
        self.assertEqual(plan.files_to_save(), set())     # gearbox files untouched

    def test_new_part_in_numbered_gearbox_gets_grb_number(self):
        new_shaft = linked("ns", "new shaft", parents=[("f-gb", "27-GRB-100 Gearbox Assembly")])
        plan = nc.plan_subsystem(self.minibot(self.numbered_gearbox([new_shaft])), "DRV", CFG)
        self.assertEqual(plan.by_key()["ns"].new_name, "27-GRB-103 new shaft")

    def test_standalone_gearbox_used_by_two_subsystems_stays_put(self):
        gb = self.numbered_gearbox()
        gb.standalone = True
        gb.parent_files = [("f-int", "27-INT-100 Intake")]
        p = nc.plan_subsystem(self.minibot(gb), "DRV", CFG).by_key()["gb"]
        self.assertEqual(p.part_number, "27-GRB-100")
        self.assertFalse(p.shared)

    def test_foreign_numbered_part_shared_with_another_subsystem_moves_to_msc(self):
        so = linked("so", "27-ELV-104 Standoff", pn="27-ELV-104",
                    parents=[("f-elv", "27-ELV-100 Elevator")])
        root = asm("root", "Intake", [so])
        self.assertEqual(nc.plan_subsystem(root, "INT", CFG).by_key()["so"].sub, "MSC")

    def test_leftover_cots_tick_on_numbered_gearbox_is_ignored(self):
        # A mentor ticked COTS on the gearbox to stop a rename; Rename saved cots=true in its file.
        gb = self.numbered_gearbox()
        gb.cots_flag = True
        plan = nc.plan_subsystem(self.minibot(gb), "DRV", CFG)
        by = plan.by_key()
        self.assertEqual(by["gb"].part_number, "27-GRB-100")
        self.assertEqual(by["gb"].status, nc.STATUS_OK)
        self.assertEqual(by["mmp"].status, nc.STATUS_OK)      # not "inside a COTS part"
        self.assertEqual(plan.files_to_save(), set())

    def test_leftover_cots_tag_on_top_is_not_fatal(self):
        gb = asm("gb", "27-DRV-100 Gearbox Assembly", [part("p", "27-DRV-101 Plate", pn="27-DRV-101")],
                 pn="27-DRV-100")
        gb.cots_flag = True
        plan = nc.plan_subsystem(gb, "DRV", CFG)
        self.assertIsNone(plan.fatal)
        self.assertEqual(plan.by_key()["gb"].status, nc.STATUS_OK)

    def test_cots_tag_still_counts_on_unnumbered_parts(self):
        spacer = part("s", "Spacer")
        spacer.cots_flag = True
        p = nc.plan_subsystem(asm("root", "Gearbox", [spacer, part("q", "Plate")]), "DRV", CFG).by_key()["s"]
        self.assertEqual(p.status, nc.STATUS_COTS)

    def test_last_season_number_is_not_ownership(self):
        gb = linked("gb", "26-GRB-100 Gearbox", pn="26-GRB-100", children=[part("p", "Plate")])
        p = nc.plan_subsystem(asm("root", "Chassis", [gb]), "DRV", CFG).by_key()["gb"]
        self.assertEqual(p.part_number, "27-DRV-200")

    def test_helpers(self):
        self.assertEqual(nc.strip_fusion_suffixes("output shaft (1):2"), "output shaft")
        self.assertEqual(nc.best_description("output shaft", "Output Shaft", CFG), "Output Shaft")
        self.assertEqual(nc.best_description("Shaft", "Something Else", CFG), "Shaft")
        self.assertEqual(nc.subsystem_of_name("27-INT-100 Intake"), "INT")


class CheckTests(unittest.TestCase):
    def test_check_design(self):
        nodes = [
            part("a", "27-ELV-101 Axle", pn="27-ELV-101"),
            part("b", "27-ELV-101 Other", pn="27-ELV-101"),
            part("c", "Component4"),
            part("d", "Bracket"),
            part("e", "26-ELV-102 Old", pn="26-ELV-102"),
            part("f", "Flanged Bearing"),
        ]
        msgs = {(i.key, i.severity) for i in nc.check_design(nodes, CFG)}
        self.assertIn(("b", "error"), msgs)
        self.assertIn(("c", "error"), msgs)
        self.assertIn(("d", "warn"), msgs)
        self.assertIn(("e", "warn"), msgs)
        self.assertNotIn(("a", "error"), msgs)
        self.assertFalse(any(k == "f" for k, _ in msgs))


if __name__ == "__main__":
    unittest.main()
