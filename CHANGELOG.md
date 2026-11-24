# Gusset changes

Every version of Gusset, newest first. Each "- " line under a version shows in the update window's "What's new", so it's written for students.

**How version numbers work** (`MAJOR.MINOR.PATCH`, like `0.12.3`):
- **PATCH** (`0.12.2` → `0.12.3`): fixes and small touches. Nothing new to learn.
- **MINOR** (`0.12` → `0.13`): new tools or features.
- **MAJOR** (`0.x` → `1.0`): Gusset is still `0.x` while it's being polished. `1.0` will mean "ready to share with other teams".

**Adding to this file:** add your line under **Unreleased** in your pull request. A mentor renames it to the version number when releasing. One line per change: say what changed, for the person using it.

## Unreleased

## 0.13.3 - Gusset logo

- Gusset has a logo! It shows in the Settings window and in Fusion's Scripts and Add-Ins list.

## 0.13.2 - Add to Library fix

- Fixed: Add to Library could say "Gusset couldn't start saving to the library" and save nothing, even after restarting Gusset. It now waits for the dialog to close and saves the part
- Linked part files from Shaft & Spacer and Tube use the same, more reliable start-up step

## 0.13.1 - Ready for GitHub

- Gusset now lives in the team's GitHub repo: see the README to install, and CONTRIBUTING.md to help build it
- A copy of Gusset that's a git folder (for working on Gusset itself) never auto-updates - use git pull

## 0.13.0 - Weight + student tips

- **Robot Weight panel** (Review > Robot Weight): docks on the right and shows, while you design, the robot's weight against the limit (115 lb without bumpers and battery in 2026), plus robot + bumpers. It breaks the weight down by subsystem and lists the heaviest parts
- Robot Weight refreshes when you press Refresh and every time you save. It warns about made parts still on Fusion's default material (their weight is a guess); click one to find it
- Weight limits are a team setting (Settings > Team > Robot weight), so they can change each Kickoff
- **Every dialog teaches itself:** a "How to use this" box at the top with numbered steps and a "Why it matters" note (collapse it once you know it, and it stays collapsed). Every input also has a hover tip with an example

## 0.12.4 - Spacers on linked shafts

- Fixed: making a spacer on a shaft from a linked part file said "That body isn't a Gusset shaft". Linked shaft files are now tagged like the other shafts
- Shafts made before this fix (and any 1/2" hex shaft, even one modeled by hand) are recognized from their shape, so Spacer still lines up its hex bore with them

## 0.12.3 - Flange side + reference note

- **Flange side:** choose "Flange outside the plates" (the default, easier maintenance) or "Flange inside the plates". Bearings without a flange sit flush with that face
- **Reference note:** once both holes are picked, Shaft & Spacer shows the numbers to type yourself: how far past the plate each groove goes, and how long each round end must be to reach the bearing, with the math behind them. Gusset never fills them in for you
- Bearing sizes are measured the first time Gusset places a bearing, so the note gets exact after that (standard R8 sizes until then)

## 0.12.2 - Bearing flange fix

- Fixed: Shaft & Spacer put both bearing flanges on the inside of the plates. Gusset now finds the flange from the bearing's shape (its biggest round face at one end) instead of guessing from its weight, and logs what it found

## 0.12.1 - Shaft upgrades

- **Round ends:** Shaft & Spacer can turn the start, the end, or both ends of the hex down round (0.500" x 0.375" by default) to ride in round-bore bearings like R8ZZ
- **Snap-ring grooves:** grooves for 1/2" external snap rings (0.469" x 0.039") just outside each plate, past the bearing flange. Add more with "Extra grooves at"
- Linked shaft files keep round ends and grooves as editable cuts (RoundDia / RoundLen parameters), and each combination gets its own file
- The **Bearings** menu now lists round-bore bearings too. Gusset only puts round-bore bearings on round ends and hex-bore bearings on hex
- Fixed: bearings from Shaft & Spacer could end up facing the same way, with one flange inside the plate. Library parts are now placed only after the dialog closes, and Gusset checks each part's position afterwards
- Fixed: a linked shaft could be saved but never inserted ("refers to a deleted Object")

## 0.12.0 - Connected tools

- **Belt & Chain puts the pulleys in for you:** after drawing the centers, it inserts the matching COTS Library pulley on each one, centered on the sketch. Pick the width (9 / 15 mm) and bore, or leave them on Any. If a tooth count isn't in the library, Gusset says which sizes it has and just draws the circle
- **Shaft & Spacer adds bearings:** a new **Bearings** menu (None, or any 1/2" hex bearing in the library). It puts one in each end hole with the flange on the outside, and skips holes that are the wrong size
- Parts placed this way are pinned with a rigid joint to what they sit on, and they count toward Recently used
- **Export BOM has a Shopping list tab:** every bought part grouped by vendor, with quantity, part #, a clickable store link, price, line total, and subtotals for each vendor
- **Design Review checks for hand-made COTS:** it warns about parts that look bought (vendor part #, a library look-alike, or names like NEO or bearing) but weren't inserted from the library, and names the library part to use. It doesn't block sign-off

## 0.11.0 - Library health

- **Library Check** (COTS > Library Check, or the badge on the COTS panel) looks over every library part for duplicates, broken file links, missing pictures, misnamed or misfiled parts, part numbers, store links and prices
- Every problem has a **Fix** button. Duplicates go to an _Review folder (nothing is ever deleted), misnamed files are renamed, and misfiled parts are moved
- Type **prices, links and part numbers** right in the check window, then press **Save typed** to save them all at once
- **Vendor posted a new model?** Find the part, pick the new STEP file, and Gusset saves a new version. It can also update this robot's copy so Fusion shows it as out of date
- The COTS panel shows a red **"3 to fix"** badge (or a quiet "missing prices" one) whenever something needs a look
- "Not the same part" is now saved with the part, so look-alike parts are never flagged twice

## 0.10.0 - Browse smarter

- **Family tiles:** gears that only differ by tooth count share one tile (116 parts now show as 27 tiles). Pick the tooth count from the menu, then press **Insert**.
- **Pulley tiles:** pick the teeth *and* the width (9 mm / 15 mm). Widths a size doesn't come in are greyed out.
- **Filters:** Bore, Pitch, Width, Material and Style menus under the vendor chips. Each one only shows up when it can narrow down what's on screen. Press *clear filters* to reset them.
- **Recently used:** a row of your last 8 inserted parts along the top. Click one to insert it again.
- **Recently used / Most used** are also in the category list.
- Search still finds single sizes: typing "48t" or a part number picks that size on its family tile.
- A family tile opens on the size you use most.
- You can star a whole family.

## 0.9.4 - Settings, updates and installers

- New Settings window: version, updates, and the team's settings in one place
- Gusset now updates itself - it asks when a new version is ready
- Team settings come from the team's GitHub, so every laptop matches
- Clearer error messages, with the technical details folded away
- One-click installers for Mac and Windows

## 0.9.3 - COTS insert fix

- COTS Library: fixed inserting parts added by a bulk import ("invalid id")
- The panel re-reads the library by itself when it has parts that were still uploading

## 0.9.2 - Faster bulk imports

- Add to Library no longer waits on each upload during a bulk import, so big imports finish much faster
- Fixes for inserting newly added library parts

## 0.9.1 - Bulk import

- **Add to Library: a folder of STEP files.** Import many parts at once from a folder plus a parts list (CSV); anything that fails goes on an "import later" list
- The duplicate check now looks across vendors

## 0.9.0 - COTS Library

- **COTS Library panel:** a picture panel of the team's FRC_COTS Fusion project. Search, filter by category or vendor, star favorites, and click a tile to insert the part, linked
- **Add to Library:** add a vendor's STEP file with its part number, category, price and store link, filed into the right folder automatically
- **Place COTS Part:** attach an inserted part with a joint, with flip, angle and offset
- Library parts carry their vendor, part #, price and link into the BOM

## 0.8.2 - Linked part fixes

- Fixes for making linked part files from Shaft & Spacer and Tube
- Name Parts checks the project's other files so part numbers don't repeat (with a time limit on big projects)

## 0.8.1 - Linked part files

- Shaft & Spacer and Tube can make each part as its own **linked file** in the assembly's "[Assembly] Parts" folder, so it shows up in the BOM once with its part number
- Fixed Shaft & Spacer and Tube dialogs that sometimes failed to open or preview

## 0.8.0 - Shafts and tube

- **Shaft & Spacer:** 1/2" hex shafts between two points (extensions, plain or tapped ends, hex rotation) and hex-bore spacers that fill the gap between two faces
- **Tube:** 1x1 and 2x1 box tube from sketch lines, with the 0.5" hole pattern

## 0.7.0 - Lightening and belts

- **Quick Rib:** draws ribs between a plate's holes, ready to edit
- **Lighten:** pockets a plate around its ribs, holes and edges, with a live preview
- **Belt & Chain:** exact center distances for real HTD 5mm belts and #25/#35 chain, drawn into a sketch

## 0.6.0 - Export Part

- **Export Part:** shop files for one part - a PDF lathe sheet, a 3MF for printing, or a plate outline

## 0.5.1 - Fixes

- Fixes after 0.5.0

## 0.5.0 - Feature tools and Design Review

- **Hole Pattern:** #10 and 1/4" holes on the FRC 0.5" grid
- **Bearing Pocket:** bearing holes sized for the team's machines (press, snug, slip, 3D print)
- **Design Review:** automatic checks, then a mentor checklist and sign-off

## 0.4.0 - Fabrication export

- **Fab Export:** cut files for every made part, sorted by machine (router, laser, printer, lathe)
- **Export Face:** click a face, get an SVG or DXF to cut
- Exporting a part updates its build status in the BOM

## 0.3.1 - Export BOM

- **Export BOM:** an Excel BOM ready for monday.com, with total quantities through repeated sub-assemblies, process, material, mass, vendor info and build status, plus an indented view
- (There's no 0.3.0 in the logs - it was replaced by 0.3.1 before it was ever run)

## 0.2.2 - Fixes

- Fixes for Name Parts on assemblies with linked parts

## 0.2.1 - Fixes

- Fixes for Name Parts on assemblies with linked parts

## 0.2.0 - Linked parts

- Name Parts works through linked parts and linked sub-assemblies: linked team parts get their file renamed and part number set, all the way down
- Warns about linked parts whose file can't be found (broken links)

## 0.1.0 - First version

- **Name Parts:** team part numbers (`YY-SUB-NNN`, like `27-ELV-104`) on every part, with a preview before anything is renamed
- **Check Names:** lists parts with missing or badly formatted names
- **Settings:** subsystem codes and the season year
- The GUSSET tab in Fusion's Design workspace
