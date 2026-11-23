# Gusset reference

A Fusion add-in suite for FRC teams. It works alongside [FRC Tools](https://github.com/4698RaiderRobotics/FRCTools) and adds a **GUSSET** tab to the Design workspace.

This is the full reference for every tool and setting. New to Gusset? Start with the [README](../README.md).

## Tools

| Button | What it does |
|---|---|
| **Name Parts** | Gives every team-made part in the open assembly file a part number, **including linked part files**, with a preview table you can edit before anything changes. |
| **Check Names** | Read-only report of default names, missing or duplicate numbers, and last season's numbers. Also saves a CSV in `logs/`. |
| **Export BOM** | Writes an Excel BOM ready for monday.com: total quantities through repeated sub-assemblies, process, material, mass, vendor info, and a Build Status column. A **Shopping list** tab groups bought parts by vendor with store links, prices and subtotals. |
| **Export Face** | Click one flat face, save its outline (with holes) as SVG or DXF for Easel or LightBurn. |
| **Export Part** | Click one part and save its shop file: lathe sheet (PDF), 3D print (3MF) or plate outline (SVG/DXF), suggested from its Process. |
| **Fab Export** | Exports every made part by its Process: SVG/DXF sorted into folders by material and thickness, 3MF for the printers, PDF lathe sheets, plus a cut list. |
| **Hole Pattern** | Bolt holes on the FRC 0.5" grid on any flat face: #10 or 1/4", clearance / close / tap, one row or a full grid, one wall or through. Live preview. |
| **Bearing Pocket** | Correctly sized bearing holes or pockets at the points you pick: bearing, fit (press / snug / slip / 3D print), through or pocket + shaft hole. Live preview. |
| **Quick Rib** | Draws rib lines on a plate automatically - every hole and bearing tied to its neighbours and to the edge in triangles - as a sketch you can edit. |
| **Lighten** | Pockets a plate in one step: outside wall, ring around every hole, ribs (Quick Rib, your own sketch, or none), corners rounded for your cutter, through or set depth. Shows the weight saved. |
| **Tube** | Turns sketch lines into 1x1 / 2x1 box tube (1/16", 0.100" or 1/8" wall), standing or flat, centered/on top/below the sketch, with an optional 0.5" hole pattern. Lists the cut lengths. |
| **Shaft & Spacer** | 1/2" hex shaft between two points (extensions, plain or tapped #10-32 ends, hex rotation), and hex-bore spacers that fill the gap between two faces on a shaft. Optionally **turns the ends round** (0.500" journals for round-bore bearings), cuts **snap-ring grooves** just outside each plate, and drops a **COTS Library bearing** in each end hole, flange outside or inside the plates. A reference note shows the groove and round-end numbers for students to type. |
| **Belt & Chain** | Exact center distances for HTD 5mm belts and #25/#35 chain: the real belts/chains nearest your target distance, or the distance for a belt you have. Draws pulley 2's center, pitch circles and belt runs into a sketch with a dimension, then **inserts the matching COTS Library pulleys** on both centers (choose width and bore, or turn it off). |
| **COTS Library** | A picture panel of the team's **FRC_COTS** Fusion project: search, categories, vendor chips, favorites. Click a part to insert it (linked), then click the edge or face it goes on. |
| **Add to Library** | Students add vendor parts (a STEP file or a component in the design) with the right name, folder and details every time - checked live, duplicates blocked. |
| **Library Check** | Finds duplicates, broken file links, missing pictures, misnamed or misfiled parts, and missing prices, links and part numbers in FRC_COTS, each with a Fix button. Also updates a part when the vendor posts a new STEP. |
| **Robot Weight** | A side panel with the robot's weight against the limit while you design: robot + bumpers, by subsystem, heaviest parts, and parts with no material set. Refreshes on save. |
| **Design Review** | Automatic checks (including bought parts that were modeled by hand instead of inserted from the COTS Library) (each explains why and how to fix), a mentor checklist, sign-off saved in the assembly, and a PDF report. |
| **Settings** | The version and updates, this computer's options, and the team's settings (read-only for students; mentors edit and publish them). |

## Part number scheme: `YY-SUB-NNN`

```
27-ELV-100  Elevator                 <- assembly owns the 100 block
27-ELV-101  Gusset Plate             <- parts inside it: 101-199
27-ELV-102  Belt Tensioner
27-ELV-200  Carriage                 <- sub-assembly gets the next block
27-ELV-201  Roller Axle
27-MSC-101  Standoff                 <- team part shared with another subsystem
WCP-0123    Flanged Bearing          <- COTS keeps its vendor number
```

- **YY**: season year (`auto` = next season from September on).
- **SUB**: subsystem code from settings (FRM, DRV, INT, IDX, SHT, ELV, ARM, CLB, ELC, BMP, MSC by default).
- **NNN**: assemblies end in `00`, parts are numbered inside their assembly's block. That allows up to 9 assemblies and 99 parts each, per subsystem.
- Each component gets **Name** = `27-ELV-101 Gusset Plate`, **Part Number** = `27-ELV-101`, **Description** = `Gusset Plate`.
- A component used several times (like 4 swerve modules) gets **one** number.
- **Shared parts:** a team part file that's also linked into another subsystem's assembly gets a number in the shared block (`MSC` by default, `shared_subsystem` in settings). Tick **Shared** in the preview to force it.
- **Already-numbered sub-assemblies keep their subsystem:** a gearbox numbered `27-GRB-100` on its own stays GRB (with its parts) when it's later used inside the DRV chassis. New parts added inside it get GRB numbers.
- **Linked files:** the file itself is renamed (`27-DRV-104 Output Shaft`) and its Part Number is set inside it.

**COTS (bought) parts** keep their vendor numbers. Gusset guesses COTS from vendor prefixes (WCP-, am-, REV-, 217-, TTB, McMaster numbers), and words like *bearing*, *bolt*, *Kraken*. Students can override any guess with the checkbox, and that choice is saved inside the design.

Every dialog has a **How to use this** box (steps + why it matters) and a hover tip on every input, so students can learn each tool on their own.

## Install

1. Download `Gusset-<version>.zip` from the team's GitHub releases and unzip it.
2. Double-click **Install Gusset (Mac).command** or **Install Gusset (Windows).bat**.
   - Mac: if macOS says it can't be opened, right-click it > **Open** > **Open**.
   - Windows: if it says "Windows protected your PC", click **More info** > **Run anyway**.
3. Open Fusion. The **GUSSET** tab appears by itself.

The installer copies Gusset into Fusion's own add-ins folder (Mac: `~/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns/Gusset`, Windows: `%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\Gusset`), so no Scripts and Add-Ins steps are needed. It's safe to run again. An older copy in `FRC Plugins` is retired: its settings and picture cache move over and the folder is renamed "Gusset (old copy - safe to delete)". If both copies ever load, the installed one wins and the old one stays off.

## Updates

Gusset updates itself from the public GitHub repo in `config.py` (`UPDATE_REPO`):

- When Fusion starts (at most every 6 hours), Gusset reads `release/latest.json` and `team_settings.json` from the repo in the background. Raw files don't count against GitHub's API limit, so a whole classroom can check at once.
- If there's a newer version it asks: **Update now / Later / Skip this version**. Update downloads the zip, checks its sha256, backs up the current version to `cache/previous/`, installs over itself (never touching `gusset_config.json`, `gusset_state.json`, logs or cache), and asks you to restart Fusion.
- **Settings > This computer > Undo last update** puts the previous version back.

**Publishing a release (mentors):**
1. Bump `VERSION` in `config.py` and `version` in `Gusset.manifest`, and add a `## <version>` section with `- ` lines to `CHANGELOG.md` (they show as "What's new").
2. Run `python tools/make_release.py`. It builds `dist/Gusset-<version>.zip` and writes `release/latest.json`.
3. On GitHub, create a release named `v<version>` and attach the zip.
4. Commit `release/latest.json` to `main`. Laptops offer the update at their next check.

## Settings

**GUSSET > Naming > Settings** opens the Settings window: the version, update status (**Check for updates**, **Update now**), and three tabs:

- **This computer:** check for updates at startup, detailed logs, the log folder, Undo last update.
- **Team:** season year, subsystem codes, shared code, name format, processes, cut-file formats, bearing fits and Lighten defaults. These come from `team_settings.json` on GitHub, so every laptop matches, and they're read-only for students.
- **Advanced:** bearing sizes, Lighten cutters, the review checklist, COTS settings and name patterns, as JSON.

Settings are layered (later wins): built-in defaults < `gusset_config.json` (this computer) < `team_settings.json` (GitHub) < `team_settings_draft.json` (a mentor's unpublished edits on this computer). Each laptop's own switches always come from `gusset_config.json`.

**Changing team settings (mentors):** Team > **Edit team settings** > change > **Save on this computer** (checked first, used on this laptop right away) > **Publish to GitHub**. Gusset copies the settings and opens `team_settings.json` on GitHub; select all, paste, **Commit changes**. When this laptop next sees the published copy match, the draft clears itself. Bearing Pocket's bearing library saves a draft the same way.

## Errors

When something goes wrong, Gusset shows one plain sentence about what happened and what to try, with the full traceback folded under **Technical details**. Buttons: **Copy details**, **Open log folder** and **Report problem**, which opens a pre-filled GitHub issue (user names in paths are replaced by `<user>`). If that window can't open, a short message box appears instead, never a code dump. The wording lives in `lib/error_core.py`.

## Using Name Parts

1. Open the subsystem's assembly file and click **GUSSET > Name Parts**. It numbers the **whole open file**, walking into linked sub-assemblies too. (To number only one sub-assembly, select it in the dialog.)
2. Check the subsystem code. Gusset guesses it from the file name.
3. Read the preview. Type descriptions for rows marked **NEEDS DESCRIPTION**, tick **COTS** or **Shared** where needed, and hover a status to see why. Rows with a link icon are separate files.
4. Press **Rename**. It works in two steps:
   - **Parts modeled in this file** change right away. One **Undo** reverts them.
   - **Linked part files** are then opened in the background, given their part number, saved as a new version ("Gusset: part numbers"), and renamed. Undo can't reach these; use the file's **Version History** in the Data Panel instead. A linked file that's open with unsaved changes is skipped.
5. Save the assembly when you're happy.

Leave **Keep good existing numbers** ticked so numbers already on drawings and cut parts don't change.

**Speed notes:** Fusion takes about 0.5 s to read each part's Part Number, so Gusset only reads it when needed and leaves a small tag on parts it has numbered so later runs are fast. The first Name Parts of a session also scans every file name in the Fusion project (so numbers never repeat across files); that scan is remembered for 15 minutes. Set `"scan_project": false` in settings to skip it.

### Name Parts speed

- **Quick rename (file names only)** - ticked by default, remembered. Linked part files are just *renamed* (about 1 s each) instead of opened, updated and saved (about 8 s each). Gusset reads a linked part's number from the start of its file name, so Gusset's BOM, checks and Fab Export are right either way; Fusion's own BOM/drawing tables show the old Part Number until that file is opened and saved. Files whose COTS/Shared box you changed (or that contain other parts to rename) are still opened. Untick to update every Part Number too.
- **Check numbers in** - *This season's folder* (default; the top-level folder under the project that holds this file - about 2 s) or *The whole project* (pick this if each season has its own Fusion project). Results are remembered for an hour. Team default: `"number_scan_scope": "season folder"` or `"project"` in `gusset_config.json`.

## Using Export BOM

1. Open an assembly and click **GUSSET > Export BOM**. (Run **Name Parts** first, so every part has a number monday can match on.)
2. Set the **Process** for each made part (X-Carve, 3D Print, Lathe, Mill, Hand Tools, Outsourced, TBD). **Set all TBD parts to** fills in the rest in one go. Choices are saved on the part, so next time they're filled in. Edit the list with `"processes"` in settings.
3. Pick a folder and press **Export**.

The Excel file has two tabs:

| Tab | What's in it |
|---|---|
| **BOM (monday)** | One row per part with the **total** quantity (2 gearboxes x 4 standoffs = 8). Columns: Name, Part #, Description, Qty, Type (Made / COTS / Assembly), Process, Build Status, Subsystem, Material, Mass Each (lb), Total Mass (lb), Vendor, Vendor Part #, Link, Unit Price, Used In, Notes. |
| **Indented** | The assembly tree with quantity per parent, for build instructions. |

COTS parts get vendor, vendor part number, and a search link for AndyMark, WCP, REV, VEX, The Thrifty Bot, and McMaster-Carr. Their insides (like a wheel's tread) are left out. Mass uses Fusion's physical material, so set materials for accurate robot weight.

### Importing into monday.com

monday imports only the **first** tab, which is why the monday tab comes first.

- **First time:** create a board from the file (Import data > Excel). Choose **Name** as the item name. Status-style columns (Type, Process, Build Status) import as Status columns.
- **After design changes:** on the existing board, use the arrow next to **New item > Import items**. Under duplicate behavior choose **Update**, matched on **Part #**, and set **Build Status** (and Unit Price, if students fill it in monday) to **don't import**, so progress tracked in monday isn't overwritten.

Saving a process on a linked part file adds a new version to that file ("Gusset: part info"), just like Name Parts.

## Fabrication export

Each part's **Process** (set in Export BOM) decides what Fab Export makes:

| Process | File | Folder | Opens in |
|---|---|---|---|
| X-Carve | SVG (or DXF) | `X-Carve/<material> <thickness>/` | Easel |
| Laser | SVG (or DXF) | `Laser/<material> <thickness>/` | LightBurn |
| 3D Print | 3MF | `3D Print/` | Bambu Studio, OrcaSlicer |
| Lathe | PDF lathe sheet | `Lathe/` | print it |
| Mill | skipped | - | programmed in Fusion CAM |
| Hand Tools, Outsourced, TBD | skipped | - | listed in the cut list |

**Pick what to export:** tick only the machines you need (e.g. just **Lathe** when you're at the lathe; Gusset remembers your choice on that laptop), and untick individual parts in the list (**Tick all / Untick all** buttons help). For a single part, **Export Part** is quicker.

File names carry the part number, description and total quantity: `27-DRV-104 omni mounting plate - qty 2.svg`. A `Cut list.xlsx` lands in the export folder. **Only parts not exported yet** skips anything already exported.

**Flat parts (SVG/DXF):**
- Gusset reads the plate's geometry directly; nothing in the design changes.
- Each outline and hole is ONE closed shape, so Easel can cut it.
- **SVG** files carry real units (`width="3.3125in"`), so Easel and LightBurn import them at the right size. That's why SVG is the default.
- **DXF** files don't reliably carry units (LightBurn uses its own Units setting on import), so the unit is in the file name: `(in).dxf`. Arcs stay true arcs.
- Through-holes are black. Pockets (cuts that don't go all the way through) are blue, on their own layer with the depth in the name, so you can set their depth in Easel or put them on their own layer in LightBurn.
- Parts with chamfers, fillets along the edge or countersinks get a warning: the file is the outline only.

**Lathe sheets** show the stock to cut (hex or round, with 1/4" extra for facing and parting), finished length, a side view, every outside diameter step (including snap-ring grooves) and every bore. If the finished diameter is already a stock size (a 1/2" standoff), the sheet says to use that stock as-is. Chamfers, threads and small fillets aren't shown.

**Build Status:** exports are logged on the open assembly (save it to keep the log). The next Export BOM shows those parts as **Ready to Cut** (X-Carve, laser, lathe) or **Ready to Print**.

**Settings:** `fab_units` (`in` or `mm`), `xcarve_format` and `laser_format` (`svg` or `dxf`). Add **Laser** to your `processes` list if your settings file predates it.

### Parts linked two or more levels deep

Fusion doesn't show an add-in's saved tags (like a part's Process) for parts linked 2+ levels deep, for example a standoff file linked into a gearbox file that's linked into the chassis. Gusset works around this by keeping a copy of those tags on the assemblies it saves. If a deep part shows **TBD** even though you set its process before, set it once more from the assembly you're in; from then on it sticks.

## Feature tools

All of these tools show a **live preview** and add a normal, named sketch + cut to the part's timeline ("Gusset holes 10-32 clearance (20)"), so students can edit or delete it like any feature. They work on parts modeled in the open file; for a part that lives in its own (linked) file, open that file first (Gusset says so).

**Hole Pattern** sizes (from a standard inch drill chart):

| Screw | Clearance | Close | Tap |
|---|---|---|---|
| #10 (10-32) | #7, 0.2010" | #9, 0.1960" | #21, 0.1590" |
| 1/4" (1/4-20) | H, 0.2660" | F, 0.2570" | #7, 0.2010" |

Layout: one row down the middle of the face's long direction, or a full 0.5" grid. Start: first hole 0.25" from the end (so the grid lands on 0.5" multiples) or centered. Depth: through this wall only (measured from the part) or through everything.

**Bearing Pocket:** pick the plate face, then one or more centers (sketch points, vertices, or an existing round edge). The hole size is the bearing OD plus the fit allowance:

| Fit | Allowance | Use |
|---|---|---|
| Press | -0.0005" | tap in with a mallet (metal plates) |
| Snug | 0 | pushes in by hand |
| Slip | +0.002" | drops in, held by the flange |
| 3D print | +0.008" | printed holes come out small |

Fits depend on your machines: cut a test plate with one hole of each and tune `bearing_fits` in settings. Bearings (FR8ZZ, FR8ZZ-size 1/2" hex, R8ZZ, FR6ZZ, R6ZZ, shielded sizes) are in `bearings`; add your own. "Pocket + shaft hole" makes a bearing-deep pocket (minus the flange) and a bore + 1/16" shaft hole.

**Bearing Pocket into a sketch:** set **Output** to *Draw circles in a sketch* and click your layout sketch (or any line in it) instead of a face. Gusset adds the bearing circle - and the shaft circle for a pocket - at each center, sized with the fit, and cuts nothing. Handy when you lay out a plate before extruding it.

### Quick Rib and Lighten (plate pocketing)

Same idea as the Onshape lightening scripts FRC teams use (2471's Part Lighten, Robot Lighten / Quick Rib in Alex's FeatureScripts): you say where the load paths are, the tool does the offsets, pockets and corner rounds.

```
plate outline --offset in by WALL ------+
every hole    --ring HOLE RING wide ----+--> what's left between them = pockets
every rib     --strip RIB wide ---------+    (inside corners rounded for the cutter)
```

1. **Quick Rib** (optional): click the plate face. It ribs the plate the way designers do it by hand:
   - **rows**: holes in a line on close spacing (like a 0.5" row) get one rib through them
   - **arcs**: a bolt circle around a bearing gets one curved rib through its holes (a full ring if it fits)
   - **spokes**: each bearing gets ribs out to the edge, to its neighbours, or T-ing onto an existing rib
   - **triangles** fill what's left (skipping lines that would cross, run alongside another rib, hug the edge or make slivers)
   - **support check**: every hole must end up held from two sides (two ribs at least 90 degrees apart), or by the wall plus one rib; missing ribs are added and the dialog warns if one can't be.
   You get a normal sketch, *Gusset ribs* (lines, arcs and circles) - delete or add curves as you like.
2. **Lighten**: click the plate face and pick the ribs: *Quick Rib (automatic)*, *Ribs from my sketch* (lines, arcs, splines and circles count; construction and projected lines don't), or *No ribs*.
3. Pick the **cutter** - it sets the inside-corner radius (tool radius + 0.005"; the laser still gets R0.0625" so corners don't crack) - and **Through** or **Pocket (set depth)** (must leave at least 0.03" of floor).
4. Widths: **Wall** (default 0.25"), **Rib** (0.1875"), **Hole ring** (0.15"), **Smallest pocket** (0.5" - narrower spots stay solid). Your last values are remembered.

5. **Keep a pocket solid**: tick *Click pockets to keep solid* and click inside any pocket on the plate (click again to cut it after all; *Cut all pockets again* clears them).

Curved ribs are drawn as true arcs (and splines as one smooth band), so curved pocket edges come out smooth. Holes closer to the wall than the smallest pocket get a tab joining their ring to the wall, so a too-thin gap can't link two pockets together.

Everything goes in one timeline group, *Gusset lighten*: a hidden sketch, the pocket cut and the corner fillet. Changed the plate? Delete the group and run Lighten again. If Fusion can't round every corner at once, Gusset redoes it pocket by pocket and skips (and reports) only the pockets whose corners are too tight.

Team defaults in `gusset_config.json`:

```json
"lighten_defaults": {"wall_in": 0.25, "rib_in": 0.1875, "boss_in": 0.15, "min_pocket_in": 0.5, "max_span_in": 4.0},
"lighten_cutters": [
  {"name": "1/8\" end mill (X-Carve)", "diameter_in": 0.125},
  {"name": "Laser", "diameter_in": 0, "corner_radius_in": 0.0625}
]
```

Every cut checks that the part actually lost material.

### Parts: Tube, Shaft & Spacer, Belt & Chain

**Create as** (Tube and Shaft & Spacer):

- **Linked part files** - the default in an assembly. Each part is saved as its own file in a **"[Assembly Name] Parts"** folder next to the assembly (made if missing) and inserted as a linked component right where the preview showed it. Identical parts share one file (four identical spacers = one file inserted four times), and a matching file already in the folder is reused. Part files are editable: a sketch + extrude driven by a **Length** user parameter (spacers also **OD**, tapped shafts **TapDepth**; a tube's hole pattern follows Length) - change it in *Modify > Change Parameters* and every assembly using it updates. The assembly has to be saved once first; saving each new file takes ~10 s while it uploads. File names describe the part (`Shaft 0.5in hex x 4.500in tapped`, `Spacer 0.75in OD x 0.490in`, `Tube 2x1 1-16 wall x 24.000in`) - run Naming afterwards for part numbers (a numbered file is still recognised for reuse).
- Spacers have a **material** dropdown (PLA default, PETG, Aluminum 6061). Fusion's library has no PLA/PETG, so Gusset adds them to the design with real densities (1240 / 1270 kg/m3) - BOM masses come out right. The material is part of a spacer's file name, so a PLA and an aluminum spacer never share a file.
- **Bodies in this file** - the default in a part file: one timeline item per run ("Gusset tubes (4)", "Gusset shaft", "Gusset spacer"), bodies named for the BOM and cut list.

- **Tube**: one sketch line = one tube along its centerline. *Start end / Far end +/-* lengthen or shorten each end. Holes: the 0.5" pattern starts 0.25" from the start end, through both walls, 1-3 rows on a 2" face.
- **Shaft**: click the start and end (round edges such as both plates' bearing holes, sketch points or vertices), add length past each end. The shaft remembers its axis and hex rotation.
- **Spacer**: click the Gusset shaft, then the two faces it fills between. The hex bore lines up with the shaft, gets +0.010" clearance (3D printing) and the spacer is 0.005" short at each end - both adjustable.
- **Belt & Chain**: pick HTD 5mm / #25 / #35 and the tooth counts. Pulleys use pitch diameter T x p / pi, sprockets p / sin(180/T); belt centers are solved from the exact open-belt length, chain from the ANSI formula with even links only. *Add to center* adds your team's usual extra. To draw: click pulley 1's center (sketch point) and a direction, pick the belt in *Draw this one*, OK. (Testing in Fusion showed a cut can silently miss when it starts in empty space, like a shaft hole above a pocket.) If a direction misses, Gusset undoes it and tries another.

## COTS Library

The library is one shared Fusion project, **FRC_COTS** (laid out like Team 5000's FRC-COTS, so either tool can read it):

```
FRC_COTS/
  Motors/            <- category (top folder)
    REV/             <- vendor (made when the first part arrives)
      REV-21-1650 NEO Brushless Motor V1.1      <- "<vendor part #> <name>"
  Bearings/  Gears/  Wheels/  Electronics/  Bearing Blocks/  Pulleys/
  Sprockets/  Planetary Gearboxes/  Sensors/  Swerve Modules/
```

**Browsing** - GUSSET > COTS > **COTS Library** docks a panel on the right. Type to search (name, part #, vendor, notes - every word must match; an exact part # comes first), pick a category, tap a vendor chip, star favorites. The panel opens instantly from a cache on this laptop; press the round arrow to re-read the project (about half a second per folder - Fusion asks the cloud for each one). Parts added with Gusset appear right away.

**Inserting** - click a tile. Fusion can only *link* a part from the same project, so the first time a part is used in a robot project Gusset copies it into a **COTS/&lt;Category&gt;** folder of that project and links the copy; after that the copy is reused (about 2 s). An unsaved design gets an embedded copy instead. Then **Place COTS Part** opens: click a round edge (a bearing hole), a round or flat face, a point or a joint origin. Optionally click the part's own mounting spot (otherwise its first joint origin, or its origin). Flip / Angle / Offset adjust it live; OK makes a rigid joint. Cancel leaves the part at the origin.

**Adding parts (students)** - GUSSET > COTS > **Add to Library** (or **+ Add** in the panel):

1. *Add from*: a STEP file from the vendor's site, or a component already in the design.
2. Name, Vendor, Part # (SKU), Category - plus Price, Product link, Notes and **initials** (initials only, never full names). Picking a file named like `am-4255.step` or `REV-21-1650 NEO.step` fills in the vendor and part #.
3. The box at the bottom checks as you type: red must be fixed, yellow is advice (e.g. "REV part numbers usually look like REV-21-1650"). A part # already in the library is blocked.
4. OK - the file is saved to `FRC_COTS/<Category>/<Vendor>/<Part #> <Name>` (about 8 s).

**No duplicates** - a part # already in the library is blocked (whatever vendor it's under - CTRE sells Krakens with WCP's number, SDS parts use AndyMark's). A part whose *name* matches one already in the library from any vendor is blocked too, with the look-alike named; every number in the names must match (24t vs 36t, Kraken X60 vs X44 are different). If it really is a different part, tick **It's a different part** (only shown when there's a look-alike).

**Adding many parts at once (batch)** - *Add from: A folder of STEP files (parts list)*:

1. Students open each product page in the parts list and save its STEP file into one folder. The file name just has to contain the part # (vendors' own downloads already do, e.g. `am-2986 FR8ZZ Hex Bearing.STEP`; otherwise rename it `WCP-0941.step`).
2. Choose the folder. Gusset uses a `.csv` parts list in that folder if there is one, otherwise its built-in starter list (`resources/cots_starter_parts.csv`, 45 current parts). Columns: Category, Vendor, Part #, Name, Price, Link, Notes, Different part.
3. The preview counts what's ready, already in the library, missing a STEP file, has two STEP files (keep the version your team uses - e.g. one MK4i ratio), needs a part #, or needs a look (a look-alike). STEP files no row claims are listed so they can be added one at a time.
4. OK adds the ready parts one by one with a progress bar you can cancel; one bad STEP file doesn't stop the rest. `Gusset import report.csv` is written into the folder. Uploads finish in the background (a 112-part batch took 19 minutes, most of it waiting that's now gone) - press Refresh in the panel afterwards.

Repeat browser downloads (`WCP-1434 (1).step`, same size as `WCP-1434.step`) are ignored.

Running it again later is safe: parts already in the library are skipped.

**Part designs** - Fusion's *Part* designs can only hold one component, so the panel says so instead of inserting; open an assembly.

Part-number formats Gusset knows: WCP `WCP-0123`, REV `REV-21-1650`, AndyMark `am-4255` (also `am-4755a`), TTB `TTB-0060` (kits can be longer, e.g. `TTB-S-02-v1.1`). SDS parts are sold by AndyMark, so they use AndyMark numbers.

**What a library part carries** - the details go in the file's description (visible in the Data Panel) and are stamped inside the part (`cots`, `cots_vendor`, `cots_pn`, `cots_price`, `cots_url`). So Name Parts never renumbers it, and Export BOM fills Vendor, Vendor Part #, Link and **Unit Price**.

**Settings** - an optional `"cots"` section in `gusset_config.json`:

```json
"cots": {
  "project": "FRC_COTS",
  "categories": ["Motors", "Bearings", "Gears", "Wheels", "Electronics", "Bearing Blocks",
                 "Pulleys", "Sprockets", "Planetary Gearboxes", "Sensors"],
  "vendors": [{"name": "WCP", "pattern": "^WCP-\\d{4}$", "example": "WCP-0123",
               "link": "https://wcproducts.com/search?q={pn}"}]
}
```

Share the FRC_COTS project with the team (Fusion: project > Members) so everyone sees the same parts.


### Library Check

**COTS > Library Check** (or the badge in the top corner of the COTS panel) lists everything that needs attention in FRC_COTS:

| Section | What it catches | Fix button |
|---|---|---|
| Duplicates | Same part number, or the same product from two vendors | Moves the less complete file to `FRC_COTS/_Review` (never deletes it). **Not the same part** remembers they're different |
| Broken links to files | Parts the panel only knows by a temporary upload id, or that were deleted | Looks them up again / reads the library again |
| Missing pictures | Parts Fusion never made a thumbnail for | Saves a version so Fusion makes one |
| Names and folders | Files not named `<part #> <name>`, or saved in the wrong vendor/category folder | Renames / moves (the file keeps its id, so robots keep working) |
| Part numbers and store links | Missing or wrongly formatted part numbers, links that aren't on the vendor's store | Type it in the window. A search link is suggested |
| Prices | Missing or unreadable prices (older than a year shows as a tip) | Type prices into the boxes, then press **Save typed** |

Saving details writes a **new version** of the library part: the details are saved inside the part (what the BOM reads) and in the version description (what the panel reads).

**Vendor revisions:** at the bottom of the window, find the part and press **Pick new STEP...**. Gusset replaces the model in a new version of the library part. If the open robot has its own copy (`COTS/<Category>/...`), it offers to update that copy too, so Fusion marks the robot's linked part out of date (right-click it in the Browser and choose **Get Latest**). Joints to the part may need to be picked again.

The ✕ on a problem hides it on that laptop only.

## Design Review

1. Open the assembly being reviewed, click **Review > Design Review**.
2. Automatic checks, worst first, each with **why it matters** and **how to fix it**: part numbers, duplicates, this season's numbers, real materials (not default Steel), a process for every made part, orderable COTS, up-to-date links, empty components, and (optional, slower) overlapping parts.
3. A mentor ticks the checklist (hover an item for why it matters), picks a decision, and adds notes. Please use initials for students.
4. **Sign Off** saves the review in the assembly (save it afterwards) and writes a PDF report to Documents. Earlier reviews show at the bottom of the dialog.

Edit the checklist with `review_checklist` in settings: a list of `["item", "why it matters"]` pairs.

## Logs and troubleshooting

- Live log: **Utilities > Text Commands** (look for `[Gusset]` lines).
- Log file: `Gusset/logs/gusset.log` (1 MB, keeps 3 old copies).
- Any error shows a dialog with the full traceback and the log path.
- Set `DEBUG = False` in `config.py` for quieter logs in releases.

## For developers

```
Gusset/
  Gusset.py, Gusset.manifest, config.py   add-in entry point and constants
  commands/        one module per button (start/stop + event handlers)
  lib/
    naming_core.py   ALL naming logic, plain Python, no Fusion imports
    settings.py      reads gusset_config.json (plain Python)
    design_tree.py   Fusion occurrence tree -> CompNode objects, project scan
    file_jobs.py     plan -> edits grouped by file, deepest file first (plain Python)
    file_runner.py   applies edits; opens, saves and renames linked files
    bom_core.py      BOM rows: totals, indented tree, vendor info (plain Python)
    xlsx_writer.py   writes .xlsx with only the standard library (Fusion has no openpyxl)
    flat_export.py   2D outlines -> SVG / DXF (plain Python)
    lathe_sheet.py   turned-part analysis -> PDF lathe sheet (plain Python)
    pdf_writer.py    tiny PDF writer (standard library only)
    fab_core.py      fab export planning, file names, export log (plain Python)
    fab_geometry.py  reads faces/bodies from Fusion for fab export, 3MF export
    frc_features.py  hole sizes, 0.5" grid, bearings and fits (plain Python)
    feature_builder.py sketch + self-checking cut on a face (Fusion)
    lighten_core.py  Quick Rib triangulation, pocket classification, checks (plain Python)
    lighten_builder.py reads plates/rib sketches, draws, cuts and rounds pockets (Fusion)
    frc_parts_core.py tube/shaft/spacer sizes, belt & chain math (plain Python)
    parts_builder.py builds tubes, shafts, spacers as exact solids; draws belts (Fusion)
    review_core.py   design review checks, records, PDF report (plain Python)
    fusion_helpers.py handlers, error dialogs, toolbar
    log.py           logging to Text Commands, file and stdout
  resources/       toolbar icons (regenerate with tools/make_icons.py)
  tests/           unit tests for the plain-Python parts
```

Run the tests without Fusion:

```
cd Gusset
python -m unittest discover -s tests -v
```

Rule of thumb: logic goes in `lib/` as plain Python with tests; `commands/` only reads Fusion, calls the logic, and shows results. Adding a tool means a new module in `commands/` that is listed in `commands/__init__.py`.

Known limits: numbers are checked against file names in the current Fusion project only. Files in another project, or read-only library files, can't be renamed (they're reported, not changed).

## Roadmap

- [x] Naming + part numbers
- [x] BOM export (Excel, ready for monday.com)
- [x] Fabrication export: SVG/DXF, 3MF, lathe sheets, cut list (uses each part's Process)
- [x] FRC feature tools: Hole Pattern, Bearing Pocket
- [x] Plate pocketing: Quick Rib, Lighten
- [x] Parts: Tube, Shaft & Spacer, Belt & Chain
- [ ] Weight and center of gravity
- [ ] Chain and reduction calculators
- [x] Design review checklist
- [ ] Mechanism generators
