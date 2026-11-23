"""
tips.py - student tips for every Gusset dialog (0.13). No Fusion imports; the
Fusion side is lib/tip_box.py. tests/test_tips.py checks every input in every
dialog has a tip, so a new box can't ship without one.

Written for students who know Fusion basics (sketch, extrude, components) but not
FRC or Gusset. Each dialog has:
    "how":    numbered steps for the 'How to use this' box at the top
    "why":    one or two 'Why it matters' lines - the engineering reason
    "inputs": {input id: (hover tip, longer description)}
Text in "how"/"why" may use <b>bold</b>; hover tips are plain text.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

Tip = Tuple[str, str]

# Read-only text boxes (results, summaries, the old help boxes) don't need hover tips.
DISPLAY_SUFFIXES = ("_info", "_summary", "_result", "_intro", "_help", "_check", "_msg", "_libinfo", "_ref",
                    "_report", "_howto", "_howto_text", "_lib_help", "_history")
# Rows of tables are made one per part (bp_bn_3, fx_m_12...) - the table's own tip covers them.
ROW_PREFIXES = ("bp_bn_", "bp_bv_", "bp_fn_", "bp_fv_", "fx_m_", "fx_pick_")

TIPS: Dict[str, dict] = {
    # ------------------------------------------------------------------ Parts
    "Gusset_ShaftSpacer": {
        "how": ["Pick <b>Make: Shaft</b> (or Spacer).",
                "Click where the shaft <b>starts</b> and <b>ends</b> - the round hole edges in each plate work best.",
                "Set how far it sticks out past each end, then the ends, round ends and grooves you want.",
                "Pick <b>Bearings</b> to drop library bearings in the holes. Read the <b>Reference</b> note, "
                "type the groove and round-end numbers yourself, then press OK."],
        "why": ["Every hex shaft on the robot is a part someone has to cut. Measuring it here first - length, "
                "round ends, snap-ring grooves - means the shaft in CAD is exactly the shaft you make."],
        "inputs": {
            "ss_mode": ("Shaft or spacer", "Shaft: a 1/2\" hex shaft between two points. Spacer: a tube that "
                        "fills the gap between two faces on a shaft."),
            "ss_create": ("Where the new part goes", "Linked part file: its own file in the '[Assembly] Parts' "
                          "folder (best - shows up in the BOM once). Bodies in this file: quick, for sketching ideas."),
            "ss_a": ("Where the shaft starts", "Click a round hole edge, a sketch point or a vertex. Round edges "
                     "also let Gusset place bearings and grooves."),
            "ss_b": ("Where the shaft ends", "Click the matching hole edge in the other plate."),
            "ss_ext_a": ("Shaft past the start", "How far the shaft sticks out past the start point, e.g. 0.25 in "
                         "for a snap ring, more for a pulley or gear."),
            "ss_ext_b": ("Shaft past the end", "How far it sticks out past the end point."),
            "ss_ends": ("Plain or tapped ends", "Tapped (#10-32) lets you bolt a washer to the end to hold "
                        "things on - you drill and tap the shaft ends."),
            "ss_round": ("Turn the ends round", "The end of the hex is turned down round on the lathe so it "
                         "spins in a round-bore bearing (like R8ZZ)."),
            "ss_round_d": ("Round end diameter", "0.500 in fits 1/2\" round-bore bearings. Measure your bearing's "
                           "bore if you're not sure."),
            "ss_round_l": ("Round end length", "From the shaft end to where the hex starts. The step (shoulder) "
                           "should land on the bearing's inner face - see the Reference note."),
            "ss_groove": ("Snap-ring grooves", "Outside both plates: a groove just past each plate so a snap "
                          "ring stops the shaft sliding."),
            "ss_groove_gap": ("Plate face to groove", "From the plate's outside face to the near edge of the "
                              "groove. The Reference note shows the bearing math - type your own value."),
            "ss_groove_d": ("Groove diameter", "0.469 in for a standard 1/2\" external snap ring. Check the "
                            "ring's data sheet for other sizes."),
            "ss_groove_w": ("Groove width", "0.039 in for a standard 1/2\" ring - a little wider than the ring."),
            "ss_groove_x": ("More grooves", "Extra groove spots, in inches from the shaft's start, e.g. 1.25, 2.5."),
            "ss_rot": ("Turn the hex", "Rotates the hex around the shaft so its flats line up with a gear or "
                       "pulley bore."),
            "ss_mat": ("Shaft material", "Sets the material so Robot Weight and the BOM are right."),
            "ss_bearing": ("Library bearings", "Puts this COTS Library bearing in each end hole. Hex-bore "
                           "bearings go on hex ends, round-bore on round ends."),
            "ss_flange": ("Which side the flange goes", "Outside the plates is easier to service. Plain bearings "
                          "sit flush with the face you pick."),
            "ss_axis": ("The shaft", "Click a Gusset shaft (or any 1/2\" hex shaft) or a round edge on its axis."),
            "ss_face1": ("Spacer starts at", "Click the face the spacer touches on one side - e.g. a bearing face."),
            "ss_face2": ("Spacer ends at", "Click the face on the other side - e.g. a gear face."),
            "ss_od": ("Spacer outside diameter", "Bigger spacers are stiffer; match what you have in stock."),
            "ss_spacer_mat": ("Spacer material", "Aluminum for metal spacers, PLA/PETG if you 3D print them."),
            "ss_clear": ("Bore clearance", "Extra room in the hex bore so the spacer slides on. Printed spacers "
                         "need more than machined ones."),
            "ss_gap": ("Gap at each end", "Left at both ends so the stack isn't squeezed tight."),
        },
    },
    "Gusset_Tube": {
        "how": ["Sketch the frame first: one line per tube, along each tube's centerline.",
                "Select the lines, then pick the tube size and wall.",
                "Choose how long each end runs past its line (+) or stops short (-).",
                "Pick holes (the 0.5\" pattern) and press OK."],
        "why": ["Box tube with the standard 0.5\" hole pattern bolts straight to COTS gussets and brackets, so "
                "frames go together without custom brackets."],
        "inputs": {
            "tb_lines": ("Sketch lines", "Each line becomes one tube along its centerline."),
            "tb_create": ("Where the tubes go", "Linked part files show up in the BOM with a cut length."),
            "tb_size": ("Tube size", "2x1 is the usual FRC frame tube; 1x1 for lighter structure."),
            "tb_wall": ("Wall thickness", "1/16\" is light; 1/8\" is stronger and heavier."),
            "tb_stand": ("Which way a 2x1 stands", "Tall (2\" up) is stiffer for bending up and down."),
            "tb_align": ("Line position", "Tube centered on the sketch line, or sitting on top of it."),
            "tb_start": ("Start end +/-", "+ makes the tube longer past the start of the line, - shorter. "
                         "The start is where you began drawing."),
            "tb_end": ("Far end +/-", "+ longer past the far end, - shorter."),
            "tb_holes": ("Hole pattern", "The 0.5\" pattern starts 0.25\" from the start end."),
            "tb_rows": ("Rows on the 2\" face", "1, 2 or 3 rows of holes on the wide side."),
            "tb_material": ("Tube material", "Sets weight for Robot Weight and the BOM."),
        },
    },
    "Gusset_BeltCalc": {
        "how": ["Pick the belt or chain and the two tooth counts.",
                "Choose <b>I know</b>: a target center distance, or the belt you have.",
                "Pick the option you want from the list (real belts/chains only).",
                "Click pulley 1's center and a point it heads toward, then OK - Gusset draws the drive and puts "
                "library pulleys on both centers."],
        "why": ["Belts and chains only come in certain lengths. Picking the center distance from a real belt "
                "means it fits with the right tension - no guessing, no tensioner."],
        "inputs": {
            "bc_drive": ("Belt or chain type", "HTD 5mm belts are the FRC standard; #25 chain for most drives."),
            "bc_t1": ("Pulley 1 teeth", "Tooth count of the first pulley or sprocket."),
            "bc_t2": ("Pulley 2 teeth", "Tooth count of the second one."),
            "bc_mode": ("What you know", "Target center: Gusset finds the nearest real belts. Belt size: Gusset "
                        "finds the center distance for the belt you have."),
            "bc_target": ("Center distance you want", "Pulley center to pulley center."),
            "bc_count": ("Belt teeth / chain links", "Printed on the belt, or count the chain's links."),
            "bc_extra": ("Add to center", "Your team's usual extra (e.g. 0.003\") so belts aren't too tight."),
            "bc_pick": ("Which option to draw", "Closer to your target is better; even links are easier for chain."),
            "bc_p1": ("Pulley 1 center", "Click a sketch point at the first pulley's center."),
            "bc_dir": ("Toward", "Click any point in the direction of pulley 2."),
            "bc_lib": ("Insert library pulleys", "After drawing, puts the matching COTS Library pulley on each "
                       "center, centered on the sketch."),
            "bc_width": ("Pulley width", "9mm or 15mm belt. Wider belts carry more load."),
            "bc_bore": ("Pulley bore", "What it mounts on: 1/2\" hex shaft, a Kraken (SplineXS) motor..."),
        },
    },
    "Gusset_BearingPocket": {
        "how": ["Click the plate face, then the hole centers (sketch points).",
                "Pick the bearing, the fit and through hole or pocket.",
                "Check the preview and press OK."],
        "why": ["A bearing hole a few thousandths too big rattles; too small and it won't go in. The fit "
                "numbers are tuned to your machines, so every hole comes out the same."],
        "inputs": {
            "bp_output": ("What to make", "Cut the holes, or just draw them in a sketch to cut later."),
            "bp_face": ("Plate face", "The flat face the bearing goes into."),
            "bp_sketch": ("Sketch for the holes", "Used when you only draw the holes."),
            "bp_centers": ("Hole centers", "Click sketch points at each bearing's center."),
            "bp_bearing": ("Bearing size", "From the bearing library - add your own below."),
            "bp_fit": ("Fit", "Press: tap in with a mallet. Snug: push in by hand. Slip: drops in. 3D print: "
                       "extra room because printed holes shrink."),
            "bp_kind": ("Through hole or pocket", "Flanged bearings use a through hole; a pocket needs a plate "
                        "thicker than the bearing."),
            "bp_lib": ("Bearing library", "Edit sizes and fits, then press Save. Mentors publish it for the team."),
            "bp_btable": ("Bearing sizes", "Inches: bore, OD, width, flange OD and thickness."),
            "bp_add_b": ("Add a bearing", "Adds a row to fill in."),
            "bp_del_b": ("Remove a bearing", "Removes the selected row."),
            "bp_ftable": ("Fits", "Inches added to the bearing OD for each fit (negative = tighter)."),
            "bp_add_f": ("Add a fit", "Adds a fit row."),
            "bp_del_f": ("Remove a fit", "Removes the selected fit."),
            "bp_save": ("Save the library", "Saves on this computer; mentors can publish it to the team."),
        },
    },
    # ------------------------------------------------------------------ Features
    "Gusset_HolePattern": {
        "how": ["Click the face to drill.", "Pick the screw size, fit, layout and where it starts.",
                "Choose the depth and press OK."],
        "why": ["The 0.5\" pattern matches COTS tube and gussets, so parts bolt together without measuring."],
        "inputs": {
            "hp_face": ("Face to drill", "A flat face of a plate or tube."),
            "hp_screw": ("Screw size", "#10 is the most common FRC bolt."),
            "hp_fit": ("Hole fit", "Clearance: bolt slides through. Close: snug, for lining up. Tap: threaded."),
            "hp_layout": ("Pattern layout", "One row down the middle (most tube), or a full 0.5\" grid."),
            "hp_start": ("Where the pattern starts", "First hole 0.25\" from the end (lines up with COTS parts), "
                         "or centered on the face."),
            "hp_depth": ("How deep", "This wall only, or through everything (both walls of a tube)."),
        },
    },
    "Gusset_Lighten": {
        "how": ["Click the plate face.", "Pick ribs: automatic, or from your own rib sketch (Quick Rib makes one).",
                "Set the wall, rib and hole-ring sizes and the cutter.", "Watch the preview, click any pocket "
                "you want kept solid, then OK."],
        "why": ["Every pound saved is a pound you can spend on mechanisms. Ribs between the load points keep "
                "the plate stiff where it matters."],
        "inputs": {
            "lt_face": ("Plate face", "The face to pocket."),
            "lt_source": ("Where ribs come from", "Automatic, or 'Ribs from my sketch' for full control."),
            "lt_sketch": ("Rib sketch", "Lines between the load points (holes, bearings, bolts)."),
            "lt_cutter": ("Cutter", "The end mill your router uses - sets the smallest inside corner."),
            "lt_depth_mode": ("Pocket depth", "Through, or a pocket that leaves a skin."),
            "lt_depth": ("Depth", "How deep pockets go when not cutting through."),
            "lt_wall": ("Wall", "Material kept around the outside edge."),
            "lt_rib": ("Rib width", "Thicker ribs are stiffer and heavier."),
            "lt_boss": ("Hole ring", "Material kept around every hole and bearing."),
            "lt_min": ("Smallest pocket", "Anything narrower stays solid - tiny pockets save almost nothing."),
            "lt_preview": ("Live preview", "Turn off on big plates if the preview is slow."),
            "lt_pick": ("Keep solid", "Click pockets to leave them solid (for a sensor mount, say)."),
            "lt_clear": ("Clear picks", "Makes every pocket a pocket again."),
        },
    },
    "Gusset_QuickRib": {
        "how": ["Click the plate face.", "Set the wall, hole ring and edge spacing.",
                "Press OK, edit the 'Gusset ribs' sketch if you like, then run Lighten."],
        "why": ["Ribs that run between holes carry the load straight across, so a lightened plate stays strong."],
        "inputs": {
            "qr_face": ("Plate face", "The face to make ribs for."),
            "qr_wall": ("Wall", "Use the same value you'll use in Lighten."),
            "qr_boss": ("Hole ring", "Use the same value you'll use in Lighten."),
            "qr_span": ("Edge spacing", "On long plates a rib reaches the edge at least this often."),
        },
    },
    # ------------------------------------------------------------------ COTS
    "Gusset_CotsAdd": {
        "how": ["Download the part's STEP file from the vendor.", "Pick it here (or a component, or a folder "
                "with a parts list).", "Fill in vendor, part #, category, price and link - copy them from the "
                "product page.", "Check the box at the bottom for warnings, then OK."],
        "why": ["Library parts carry their price and store link into the BOM and shopping list, so ordering "
                "is one click instead of a hunt."],
        "inputs": {
            "ca_src": ("What you're adding", "A STEP file, a component in this design, or a folder of STEP files."),
            "ca_browse": ("Pick a STEP file", "The file you downloaded from the vendor."),
            "ca_file": ("STEP file", "The file being added."),
            "ca_folder_btn": ("Pick a folder", "A folder of STEP files plus a parts list (CSV)."),
            "ca_folder": ("Folder", "The folder being imported."),
            "ca_comp": ("Component", "A part already in this design."),
            "ca_name": ("Part name", "What the vendor calls it, e.g. NEO Brushless Motor V1.1."),
            "ca_vendor": ("Vendor", "Who sells it."),
            "ca_pn": ("Part number", "The vendor's SKU - copy it from the product page."),
            "ca_cat": ("Category", "Which library folder it goes in."),
            "ca_price": ("Price", "In dollars, e.g. 12.99 - used for BOM totals."),
            "ca_url": ("Store link", "The product page, so anyone can reorder it."),
            "ca_notes": ("Notes", "Optional, e.g. 'use with 1/2in hex'."),
            "ca_by": ("Your initials", "So the team knows who added it (initials only)."),
            "ca_diff": ("Not a duplicate", "Tick when the duplicate warning is wrong - it's a different part."),
        },
    },
    "Gusset_CotsPlace": {
        "how": ["Click where the part goes (an edge, face, point or joint origin).",
                "Optional: click the spot on the part that should touch it.",
                "Flip, rotate or offset until the preview looks right, then OK."],
        "why": ["A joint keeps the part where it belongs when the assembly moves, instead of floating."],
        "inputs": {
            "cp_target": ("Put it on", "Where the part attaches in your design."),
            "cp_part": ("Spot on the part", "Optional - which point of the part touches the target."),
            "cp_flip": ("Flip", "Turns the part around to face the other way."),
            "cp_angle": ("Angle", "Spins it around the joint."),
            "cp_offset": ("Offset", "Moves it along the joint, e.g. to sit on a spacer."),
        },
    },
    # ------------------------------------------------------------------ Naming / BOM / Fab
    "Gusset_NameParts": {
        "how": ["Pick the subsystem (and optionally just one assembly).", "Check the Preview list.",
                "Press OK - parts get team part numbers like 27-DRV-012."],
        "why": ["A part number on every file means the BOM, the cut files and the part on the shelf all "
                "match, so nobody machines the wrong version."],
        "inputs": {
            "gs_select": ("Only this assembly", "Leave empty to number the whole open file."),
            "gs_subsystem": ("Subsystem", "The code in the part number, e.g. DRV for drivetrain."),
            "gs_keep": ("Keep good numbers", "Untick to renumber everything."),
            "gs_quick": ("Quick rename", "Linked files are only renamed - much faster on big robots."),
            "gs_scope": ("Where to check numbers", "So the same number is never used twice."),
            "gs_table": ("Preview", "Each part, its new number and description - edit descriptions here."),
        },
    },
    "Gusset_CheckNames": {
        "how": ["Open the design and run Check Names.", "Read the list: errors first, then warnings.",
                "Fix them with Name Parts, then check again."],
        "why": ["Clean names keep the BOM readable and stop two parts sharing a number."],
        "inputs": {},
    },
    "Gusset_ExportBom": {
        "how": ["Pick the folder and file name.", "Set the process for each made part (or set all TBD at once).",
                "Press Export - the Excel file has the BOM, an indented view and a Shopping list."],
        "why": ["The BOM is the build plan: what to cut, what to buy and what's done. The Shopping list "
                "groups everything by vendor so ordering is quick."],
        "inputs": {
            "gb_folder": ("Save folder", "Where the Excel file is saved."),
            "gb_pick": ("Pick folder", "Choose a different folder."),
            "gb_file": ("File name", "Dated automatically."),
            "gb_open": ("Open it", "Opens the Excel file when done."),
            "gb_bulk": ("Set all TBD parts", "Gives every part without a process the same one."),
            "gb_table": ("Made parts", "Pick how each part gets made - it's saved on the part."),
        },
    },
    "Gusset_FabExport": {
        "how": ["Pick the folder and machines.", "Tick the parts to export (new ones are ticked).",
                "Press OK - you get cut files sorted by machine."],
        "why": ["Exporting straight from CAD means the file you cut is the part in the robot - no redrawing, "
                "no wrong version."],
        "inputs": {
            "fx_folder": ("Export folder", "Where cut files go."),
            "fx_pick": ("Pick folder", "Choose a different folder."),
            "fx_sub": ("New folder name", "A dated folder is made for this batch."),
            "fx_xfmt": ("X-Carve file type", "SVG keeps real units for Easel."),
            "fx_lfmt": ("Laser file type", "SVG or DXF, whatever your laser software takes."),
            "fx_machines": ("Machines", "Only parts for these machines are listed."),
            "fx_new": ("Only new parts", "Hides parts already exported."),
            "fx_open": ("Open the folder", "Opens it when done."),
            "fx_table": ("Parts", "Tick the parts to export."),
            "fx_all": ("Select all", "Ticks every part."),
            "fx_none": ("Select none", "Unticks every part."),
        },
    },
    "Gusset_ExportFace": {
        "how": ["Click the face to cut.", "Pick the format and units.", "Press OK and save the file."],
        "why": ["Cutting from the real face means holes and pockets land exactly where CAD has them."],
        "inputs": {
            "ef_face": ("Face to export", "The flat face the router or laser cuts."),
            "ef_format": ("File type", "SVG for Easel/X-Carve, DXF for most others."),
            "ef_units": ("Units", "Match what your cutting software expects."),
            "ef_log": ("Mark as exported", "The BOM then shows this part as Ready to Cut."),
        },
    },
    "Gusset_ExportPart": {
        "how": ["Click the part.", "Pick the shop file: lathe sheet, 3D print or plate outline.",
                "Press OK and save it."],
        "why": ["Each shop machine gets the file it needs straight from CAD - a lathe sheet with the real "
                "dimensions, a 3MF for the printer, an outline for the router."],
        "inputs": {
            "xp_part": ("Part", "The part to make a shop file for."),
            "xp_kind": ("Shop file", "Lathe sheet (PDF) for shafts and spacers, 3D print (3MF) for the printer, "
                        "plate outline for the router or laser."),
        },
    },
    # ------------------------------------------------------------------ Review
    "Gusset_DesignReview": {
        "how": ["Run it on the assembly you want reviewed.", "Fix anything the automatic checks flag.",
                "A mentor works through the checklist, adds notes and a decision, then OK saves the review."],
        "why": ["Catching a problem in CAD costs minutes; catching it after cutting costs material and days."],
        "inputs": {
            "dr_auto": ("Automatic checks", "Names, materials, vendor info, library parts and more."),
            "dr_overlap": ("Overlapping parts", "Slower - checks parts that occupy the same space."),
            "dr_table": ("Mentor checklist", "Tick each item once it's been looked at."),
            "dr_reviewer": ("Reviewer", "Mentor's initials."),
            "dr_decision": ("Decision", "Approved, approved with changes, or needs another review."),
            "dr_notes": ("Notes", "What to fix. Use initials, not students' full names."),
        },
    },
}


def tip_for(cmd_id: str, input_id: str) -> Tuple[str, str]:
    """(hover tip, description) or ('', '') - never raises."""
    return TIPS.get(cmd_id, {}).get("inputs", {}).get(input_id, ("", ""))


def needs_tip(input_id: str) -> bool:
    return not (input_id.endswith(DISPLAY_SUFFIXES) or input_id.startswith(ROW_PREFIXES))


def how_to_html(cmd_id: str) -> str:
    """The 'How to use this' box: numbered steps, then 'Why it matters'."""
    t = TIPS.get(cmd_id)
    if not t:
        return ""
    steps = "".join(f"{n}. {s}<br>" for n, s in enumerate(t.get("how", []), 1))
    why = " ".join(t.get("why", []))
    return steps + (f"<br><b>Why it matters:</b> {why}" if why else "")


def rows_for(cmd_id: str) -> int:
    """Rough height for the text box (Fusion doesn't grow it by itself)."""
    t = TIPS.get(cmd_id, {})
    chars = sum(len(s) for s in t.get("how", [])) + sum(len(s) for s in t.get("why", []))
    return max(4, min(14, len(t.get("how", [])) + 2 + chars // 70))


def missing(cmd_id: str, input_ids: List[str]) -> List[str]:
    """Inputs in a dialog with no tip (logged at runtime, failed in tests)."""
    have = TIPS.get(cmd_id, {}).get("inputs", {})
    return [i for i in input_ids if needs_tip(i) and i not in have]
