"""Updater, error messages and layered settings."""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from lib import error_core as ec  # noqa: E402
from lib import settings as st  # noqa: E402
from lib import update_core as uc  # noqa: E402

GOOD = {"version": "0.9.4", "zip": "https://github.com/x/gusset/releases/download/v0.9.4/Gusset-0.9.4.zip",
        "sha256": "a" * 64, "released": "2026-11-21", "notes": ["Settings window", "Friendly errors"]}


class VersionTests(unittest.TestCase):
    def test_compare(self):
        self.assertTrue(uc.is_newer("0.10.0", "0.9.9"))
        self.assertTrue(uc.is_newer("v0.9.4", "0.9.3"))
        self.assertFalse(uc.is_newer("0.9.3", "0.9.3"))
        self.assertFalse(uc.is_newer("0.9.2", "0.9.3"))
        self.assertFalse(uc.is_newer("junk", "0.9.3"))
        self.assertEqual(uc.parse_version("1.2"), (1, 2, 0))

    def test_parse_latest(self):
        r = uc.parse_latest(json.dumps(GOOD))
        self.assertEqual((r.version, r.notes[0]), ("0.9.4", "Settings window"))
        for bad in ({**GOOD, "version": "soon"}, {**GOOD, "zip": "http://x"}, {**GOOD, "sha256": "abc"}):
            with self.assertRaises(ValueError):
                uc.parse_latest(json.dumps(bad))
        with self.assertRaises(ValueError):
            uc.parse_latest("not json")

    def test_urls_and_timing(self):
        self.assertEqual(uc.latest_url("team/gusset"),
                         "https://raw.githubusercontent.com/team/gusset/main/release/latest.json")
        self.assertFalse(uc.repo_is_set("OWNER/gusset"))
        self.assertFalse(uc.repo_is_set(""))
        self.assertTrue(uc.repo_is_set("frc1234/gusset"))
        self.assertTrue(uc.due_for_check(0, 100))
        self.assertFalse(uc.due_for_check(1000, 1000 + 3600))

    def test_zip_layout(self):
        names = ["Gusset/Gusset.py", "Gusset/Gusset.manifest", "Gusset/config.py", "Gusset/lib/a.py",
                 "Gusset/logs/gusset.log", "Gusset/gusset_config.json", "Gusset/lib/__pycache__/a.pyc",
                 "__MACOSX/Gusset/._Gusset.py", "Install Gusset (Mac).command", "Gusset/team_settings.json",
                 "Gusset/resources/"]
        root = uc.find_package_root(names)
        self.assertEqual(root, "Gusset/")
        self.assertEqual(uc.files_to_install(names, root),
                         ["Gusset.manifest", "Gusset.py", "config.py", "lib/a.py", "team_settings.json"])
        with self.assertRaises(ValueError):
            uc.files_to_install(["Gusset/../evil.py"], "Gusset/")
        self.assertIsNone(uc.find_package_root(["readme.txt"]))
        self.assertEqual(uc.read_zip_version('DEBUG = True\nVERSION = "0.9.4"\n'), "0.9.4")


class ErrorTests(unittest.TestCase):
    def test_titles(self):
        self.assertEqual(ec.title_for("COTS Library: inserting a part"), "Gusset couldn't finish inserting a part")
        self.assertEqual(ec.title_for(""), "Gusset ran into a problem")

    def test_explain(self):
        r = ec.explain("COTS Library: inserting a part", RuntimeError("3 : invalid id"), "Traceback ...")
        self.assertIn("couldn't find that file", r.summary)
        self.assertEqual(r.tool, "COTS Library")
        r = ec.explain("Fab Export: saving files", PermissionError("[Errno 13] Permission denied"), "")
        self.assertIn("wasn't allowed", r.summary)
        r = ec.explain("Tube: making tubes", ValueError("weird"), "")
        self.assertIn("unexpected", r.summary)

    def test_privacy_scrub(self):
        text = 'File "/Users/jdoe/FRC Plugins/Gusset/x.py" and C:\\Users\\jdoe\\AppData\\x'
        out = ec.scrub(text, home="/Users/someoneelse")
        self.assertNotIn("jdoe", out)
        self.assertEqual(ec.scrub("/Users/me/a", home="/Users/me"), "~/a")

    def test_issue_url(self):
        r = ec.explain("Tube: making tubes", ValueError("x"), "trace " * 2000)
        url = ec.issue_url("team/gusset", r, "0.9.4")
        self.assertTrue(url.startswith("https://github.com/team/gusset/issues/new?"))
        self.assertLessEqual(len(url), 6000)


class LayeredSettingsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        st._cache.clear()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def write(self, name, data):
        with open(os.path.join(self.dir, name), "w") as h:
            json.dump(data, h)

    def test_team_wins_personal_stays(self):
        self.write("gusset_config.json", {"season_year": "26", "check_updates": False, "fab_units": "mm"})
        self.write("team_settings.json", {"season_year": "27", "check_updates": True})
        s = st.read_settings(self.dir)
        self.assertEqual(s["season_year"], "27")          # team beats the laptop
        self.assertEqual(s["fab_units"], "mm")             # not set by the team -> laptop value
        self.assertFalse(s["check_updates"])               # personal: team can't change it
        self.assertEqual(st.load_config(self.dir).season_year, "27")

    def test_draft_then_publish(self):
        self.write("team_settings.json", {"season_year": "27"})
        st.save_team_draft(self.dir, {"season_year": "28"})
        st._cache.clear()
        self.assertEqual(st.read_settings(self.dir)["season_year"], "28")
        # GitHub now has the mentor's change -> the draft clears itself
        draft = st.team_layers(self.dir)["draft"]
        self.assertTrue(st.write_team_settings(self.dir, json.dumps(draft)))
        self.assertFalse(os.path.exists(os.path.join(self.dir, st.DRAFT_FILENAME)))

    def test_discard_and_bad_files(self):
        self.write("team_settings.json", {"season_year": "27"})
        st.save_team_draft(self.dir, {"season_year": "29"})
        self.assertTrue(st.discard_team_draft(self.dir))
        st._cache.clear()
        self.assertEqual(st.read_settings(self.dir)["season_year"], "27")
        with open(os.path.join(self.dir, "team_settings.json"), "w") as h:
            h.write("{oops")
        st._cache.clear()
        self.assertEqual(st.read_settings(self.dir)["season_year"], "auto")   # typo -> ignored, not a crash


if __name__ == "__main__":
    unittest.main()


class ValidateTeamTests(unittest.TestCase):
    def test_defaults_are_valid(self):
        self.assertEqual(st.validate_team({k: v for k, v in st.DEFAULT_SETTINGS.items() if not k.startswith("_")}), [])

    def test_problems(self):
        bad = dict(st.DEFAULT_SETTINGS, season_year="2027", subsystems={"elv": "Elevator"}, name_format="{desc}",
                   fab_units="ft", bearing_fits={"Press": "tight"}, cots_patterns=["(unclosed"])
        problems = " | ".join(st.validate_team(bad))
        for words in ("Season year", "'elv'", "{pn}", "fab_units", "'Press'", "valid pattern"):
            self.assertIn(words, problems)
