"""Every Gusset file must at least compile (catches mistakes the linter misses, like a misplaced 'global')."""

import glob
import os
import py_compile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


class CompileTests(unittest.TestCase):
    def test_all_files_compile(self):
        files = [f for f in glob.glob(os.path.join(ROOT, "**", "*.py"), recursive=True) if "__pycache__" not in f]
        self.assertGreater(len(files), 50)
        for f in files:
            with self.subTest(file=os.path.relpath(f, ROOT)):
                py_compile.compile(f, doraise=True)
