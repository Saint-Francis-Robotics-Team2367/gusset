"""Tests for turning a plan into per-file jobs. Run: python -m unittest discover -s tests -v"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from lib import file_jobs as fj  # noqa: E402
from lib import naming_core as nc  # noqa: E402
import test_naming_core as tn  # noqa: E402  (module import so its tests aren't run twice)

CFG, asm, linked, part = tn.CFG, tn.asm, tn.linked, tn.part


class FileJobTests(unittest.TestCase):
    def test_real_gearbox_jobs(self):
        root = tn.LinkedAndSharedTests().real_gearbox()
        root.file_name = "Gearbox Assembly v2"
        plan = nc.plan_subsystem(root, "DRV", CFG)
        jobs = fj.build_jobs(plan, root)
        self.assertEqual({e.key for e in jobs.local_edits}, {"root", "mmp", "mp"})
        self.assertEqual(jobs.active_rename, "27-DRV-100 Gearbox Assembly")
        by_file = {j.file_id: j for j in jobs.jobs}
        self.assertEqual(set(by_file), {"f-so", "f-os"})
        self.assertEqual(by_file["f-os"].rename_to, "27-DRV-104 Output Shaft")
        self.assertTrue(by_file["f-os"].edits[0].is_file_root)
        root_edit = next(e for e in jobs.local_edits if e.key == "root")
        self.assertTrue(root_edit.is_file_root)

    def test_nested_linked_assembly_order(self):
        # Drivetrain (open file) -> linked Gearbox file -> linked Shaft file + local Plate
        plate = part("plate", "Plate")
        plate.owner_file = "f-gb"
        shaft = linked("shaft", "Shaft")
        gearbox = linked("gb", "Gearbox", children=[shaft, plate])
        root = asm("root", "Drivetrain", [gearbox])
        root.file_id, root.file_name = "f-root", "Drivetrain"
        plan = nc.plan_subsystem(root, "DRV", CFG)
        jobs = fj.build_jobs(plan, root)

        order = [j.file_id for j in jobs.jobs]
        self.assertEqual(order, ["f-shaft", "f-gb"])            # deepest first
        gb = jobs.jobs[1]
        self.assertTrue(gb.refresh)
        self.assertEqual(gb.rename_to, "27-DRV-200 Gearbox")
        self.assertEqual({e.key for e in gb.edits}, {"gb", "plate"})
        self.assertFalse(next(e for e in gb.edits if e.key == "plate").is_file_root)

    def test_parent_file_refreshes_even_without_its_own_edits(self):
        shaft = linked("shaft", "Shaft")
        gearbox = linked("gb", "27-DRV-200 Gearbox", pn="27-DRV-200", children=[shaft])
        root = asm("root", "27-DRV-100 Drivetrain", [gearbox], pn="27-DRV-100")
        plan = nc.plan_subsystem(root, "DRV", CFG)
        jobs = fj.build_jobs(plan, root)
        gb = next(j for j in jobs.jobs if j.file_id == "f-gb")
        self.assertTrue(gb.refresh)
        self.assertEqual(gb.edits, [])
        self.assertIsNone(gb.rename_to)

    def test_cots_tick_creates_tag_only_edit(self):
        root = asm("root", "Gearbox", [part("p", "Spacer"), part("q", "Plate")])
        plan = nc.plan_subsystem(root, "DRV", CFG, overrides={"p": {"cots": True}})
        jobs = fj.build_jobs(plan, root, overrides={"p": {"cots": True}})
        tag = next(e for e in jobs.local_edits if e.key == "p")
        self.assertFalse(tag.renumber)
        self.assertEqual(tag.cots_tag, "true")

    def test_process_tags_go_to_the_right_files(self):
        plate = part("plate", "Plate")
        plate.owner_file = "f-gb"
        shaft = linked("shaft", "Shaft")
        gearbox = linked("gb", "Gearbox", children=[shaft, plate])
        local = part("rail", "Rail")
        root = asm("root", "Chassis", [gearbox, local])
        jobs = fj.build_attr_jobs(root, {"rail": {"process": "X-Carve"}, "shaft": {"process": "Lathe"},
                                         "plate": {"process": "X-Carve"}})
        self.assertEqual([e.key for e in jobs.local_edits], ["rail"])
        self.assertEqual([j.file_id for j in jobs.jobs], ["f-shaft", "f-gb"])
        shaft_edit = jobs.jobs[0].edits[0]
        self.assertTrue(shaft_edit.is_file_root)
        self.assertFalse(shaft_edit.renumber)
        self.assertEqual(shaft_edit.attrs, {"process": "Lathe"})
        self.assertTrue(jobs.jobs[1].refresh)
        self.assertFalse(jobs.jobs[1].edits[0].is_file_root)

    def test_tag_cache_entries_for_nested_parts(self):
        # Minibot -> linked gearbox -> linked standoff (2 levels deep: tags invisible from the top)
        so = linked("so", "27-GRB-102 Standoff", pn="27-GRB-102")
        gearbox = linked("gb", "27-GRB-100 Gearbox", pn="27-GRB-100", children=[so])
        root = asm("root", "27-DRV-100 Chassis", [gearbox], pn="27-DRV-100")
        jobs = fj.build_attr_jobs(root, {"so": {"process": "Lathe"}})
        cache = fj.cache_entries(jobs.jobs)
        self.assertEqual(cache, {"f-so": {"process": "Lathe"}})
        self.assertTrue(next(j for j in jobs.jobs if j.file_id == "f-gb").refresh)   # gearbox keeps a copy

    def test_tag_cache_from_naming(self):
        shaft = linked("shaft", "Shaft")
        root = asm("root", "Gearbox", [shaft])
        root.file_id = "f-root"
        plan = nc.plan_subsystem(root, "DRV", CFG)
        cache = fj.cache_entries(fj.build_jobs(plan, root).jobs)
        self.assertEqual(cache["f-shaft"], {"pn": "27-DRV-101", "cots": "false"})

    def test_merge_cache(self):
        old = {"f-a": {"process": "Mill", "pn": "27-A-101"}, "f-b": {"process": "Lathe"}}
        new = {"f-a": {"process": "X-Carve"}, "f-self": {"process": "Laser"}}
        merged = fj.merge_cache(old, new, skip_file="f-self")
        self.assertEqual(merged["f-a"], {"process": "X-Carve", "pn": "27-A-101"})
        self.assertNotIn("f-self", merged)
        self.assertEqual(old["f-a"]["process"], "Mill")      # original not changed

    def test_nothing_to_do(self):
        root = asm("root", "27-DRV-100 Gearbox", [part("p", "27-DRV-101 Plate", pn="27-DRV-101")], pn="27-DRV-100")
        jobs = fj.build_jobs(nc.plan_subsystem(root, "DRV", CFG), root)
        self.assertFalse(jobs.needs_after_step)
        self.assertEqual(jobs.local_edits, [])


if __name__ == "__main__":
    unittest.main()


class QuickRenameTests(unittest.TestCase):
    """FileJob.rename_only: when Name Parts' quick mode can skip opening a file."""

    def _edit(self, **kw):
        from lib.file_jobs import Edit
        base = dict(key="k", old_name="Plate", new_name="27-GRB-101 Plate", part_number="27-GRB-101",
                    description="", kind="part", is_file_root=True, renumber=True)
        base.update(kw)
        return Edit(**base)

    def test_rename_only_cases(self):
        from lib.file_jobs import FileJob
        plain = FileJob("f1", "Plate", rename_to="27-GRB-101 Plate", edits=[self._edit()])
        self.assertTrue(plain.rename_only)
        cots = FileJob("f2", "Motor", rename_to="x", edits=[self._edit(cots_tag="true")])
        self.assertFalse(cots.rename_only)                       # COTS box changed -> must open
        inner = FileJob("f3", "Gearbox", rename_to="x", edits=[self._edit(), self._edit(is_file_root=False)])
        self.assertFalse(inner.rename_only)                      # a part INSIDE the file is renamed
        tagged = FileJob("f4", "Plate", rename_to="x", edits=[self._edit(attrs={"process": "Laser"})])
        self.assertFalse(tagged.rename_only)
        refresh_only = FileJob("f5", "Robot", refresh=True)
        self.assertFalse(refresh_only.rename_only)
