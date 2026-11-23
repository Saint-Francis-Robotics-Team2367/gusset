"""
Guard against calling dialog methods Fusion doesn't have (v0.8.0 shipped with
addAngleValueInput, which doesn't exist). Scans every command module for
`inputs.addXxx(` and checks the name against Fusion's CommandInputs API.
"""

import os
import re
import unittest

# adsk.core.CommandInputs methods (Fusion API reference).
FUSION_ADD_METHODS = {
    "addBoolValueInput", "addButtonRowCommandInput", "addDirectionCommandInput", "addDistanceValueCommandInput",
    "addDropDownCommandInput", "addFloatSliderCommandInput", "addFloatSliderListCommandInput",
    "addFloatSpinnerCommandInput", "addGroupCommandInput", "addImageCommandInput", "addIntegerSliderCommandInput",
    "addIntegerSliderListCommandInput", "addIntegerSpinnerCommandInput", "addRadioButtonGroupCommandInput",
    "addSelectionInput", "addSliderCommandInput", "addStringValueInput", "addTabCommandInput",
    "addTableCommandInput", "addTextBoxCommandInput", "addValueInput", "addAngleValueCommandInput",
    "addBrowserCommandInput", "addTriadCommandInput",
}

# Selection filter names from Fusion's SelectionCommandInput.addSelectionFilter docs.
FUSION_FILTERS = {
    "Bodies", "SolidBodies", "SurfaceBodies", "MeshBodies", "Faces", "SolidFaces", "SurfaceFaces", "PlanarFaces",
    "CylindricalFaces", "ConicalFaces", "SphericalFaces", "ToroidalFaces", "SplineFaces", "Edges", "LinearEdges",
    "CircularEdges", "EllipticalEdges", "TangentEdges", "NonTangentEdges", "SplineEdges", "Vertices",
    "RootComponents", "Occurrences", "Sketches", "SketchCurves", "SketchLines", "SketchCircles", "SketchPoints",
    "ConstructionPoints", "ConstructionLines", "ConstructionPlanes", "Features", "Canvases", "Decals",
    "JointOrigins", "Joints", "SketchConstraints", "Profiles", "Texts",
}

COMMANDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "commands")


class DialogApiTests(unittest.TestCase):
    def test_only_real_input_methods(self):
        bad = []
        for name in sorted(os.listdir(COMMANDS_DIR)):
            if not name.endswith(".py"):
                continue
            text = open(os.path.join(COMMANDS_DIR, name), encoding="utf-8").read()
            for method in re.findall(r"(?:inputs|children|commandInputs)\.(add\w+)\(", text):
                if method not in FUSION_ADD_METHODS:
                    bad.append(f"{name}: {method}")
        self.assertEqual(bad, [], "dialog methods Fusion doesn't have")

    def test_only_real_selection_filters(self):
        bad = []
        for name in sorted(os.listdir(COMMANDS_DIR)):
            if name.endswith(".py"):
                text = open(os.path.join(COMMANDS_DIR, name), encoding="utf-8").read()
                found = re.findall(r'addSelectionFilter\("(\w+)"\)', text)
                for loop in re.findall(r'for \w+ in \(([^)]*)\):\s*\n\s*\w+\.addSelectionFilter', text):
                    found += re.findall(r'"(\w+)"', loop)
                bad += [f"{name}: {f}" for f in found if f not in FUSION_FILTERS]
        self.assertEqual(bad, [], "selection filters Fusion doesn't have")


class EventSafetyTests(unittest.TestCase):
    def test_no_args_inputs(self):
        """args.inputs only sees the changed input's group - use fh.all_inputs(args)."""
        bad = [n for n in os.listdir(COMMANDS_DIR) if n.endswith(".py") and
               "args.inputs" in open(os.path.join(COMMANDS_DIR, n), encoding="utf-8").read()]
        self.assertEqual(bad, [])

    def test_no_doevents_while_naming(self):
        """doEvents mid-dialog let other events wipe Name Parts' state."""
        lib_dir = os.path.join(COMMANDS_DIR, "..", "lib")
        for path in (os.path.join(COMMANDS_DIR, "name_parts.py"), os.path.join(lib_dir, "design_tree.py")):
            code = "\n".join(line.split("#")[0] for line in open(path, encoding="utf-8"))
            code = re.sub(r'"""[\s\S]*?"""', "", code)
            self.assertNotIn("doEvents()", code, path)

    def test_components_never_dict_keys(self):
        """Fusion Components are unhashable - grouping by them crashed Tube."""
        bad = []
        for n in os.listdir(COMMANDS_DIR):
            if n.endswith(".py"):
                text = open(os.path.join(COMMANDS_DIR, n), encoding="utf-8").read()
                if re.search(r"setdefault\(\s*(comp|component|sketch\.parentComponent)\b", text):
                    bad.append(n)
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
