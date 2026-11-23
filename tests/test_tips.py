"""0.13: every input in every Gusset dialog has a student tip (and no tip points at nothing)."""

import glob
import os
import re
import sys
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from lib import tips  # noqa: E402


def dialogs():
    """{CMD_ID: set of input ids} read from the command files (the ids are string constants)."""
    out = {}
    for f in sorted(glob.glob(os.path.join(ROOT, "commands", "*.py"))):
        src = open(f).read()
        if "tip_box.attach(" not in src:
            continue
        cmd_id = re.search(r'^CMD_ID\s*=\s*"([^"]+)"', src, re.M).group(1)
        # each dialog's input ids share one 2-letter prefix (ss_, bc_...): the most common one
        from collections import Counter
        prefix = Counter(re.findall(r'"([a-z]{2})_[a-z0-9_]+"', src)).most_common(1)[0][0]
        ids = set(re.findall(r'"(' + prefix + r'_[a-z0-9_]+)"', src))
        out[cmd_id] = {i for i in ids if not i.endswith("_")}          # 'bp_bn_' etc. are row prefixes
    return out


class TipTests(unittest.TestCase):
    def test_every_dialog_has_how_to(self):
        found = dialogs()
        self.assertEqual(len(found), 16, sorted(found))
        for cmd_id in found:
            self.assertIn(cmd_id, tips.TIPS, cmd_id)
            self.assertGreaterEqual(len(tips.TIPS[cmd_id]["how"]), 2, cmd_id)
            self.assertTrue(tips.TIPS[cmd_id]["why"], cmd_id)
            self.assertIn("Why it matters", tips.how_to_html(cmd_id))

    def test_every_input_has_a_tip(self):
        gaps = {cmd: tips.missing(cmd, sorted(ids)) for cmd, ids in dialogs().items()}
        self.assertEqual({c: g for c, g in gaps.items() if g}, {})

    def test_no_stale_tips(self):
        found = dialogs()
        stale = {cmd: sorted(set(t["inputs"]) - found.get(cmd, set())) for cmd, t in tips.TIPS.items()}
        self.assertEqual({c: s for c, s in stale.items() if s}, {})

    def test_tips_are_short_plain_text(self):
        for cmd, t in tips.TIPS.items():
            for iid, (tip, desc) in t["inputs"].items():
                self.assertLessEqual(len(tip), 40, f"{cmd}/{iid}: hover tip too long")
                self.assertNotIn("<", tip + desc, f"{cmd}/{iid}: hover tips can't show HTML")
                self.assertLessEqual(len(desc), 200, f"{cmd}/{iid}")

    def test_display_boxes_need_no_tip(self):
        self.assertFalse(tips.needs_tip("ss_info"))
        self.assertFalse(tips.needs_tip("bp_bn_3"))
        self.assertTrue(tips.needs_tip("ss_round"))
        self.assertEqual(tips.tip_for("nope", "x"), ("", ""))
