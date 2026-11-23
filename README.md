# Gusset

**FRC design tools for Autodesk Fusion, built by our team for our team.**

Gusset adds a **GUSSET** tab to Fusion's Design workspace with the tools we use every build season: hex shafts with bearings and snap-ring grooves, box tube frames, belt and chain center distances, a picture library of COTS parts, part numbers, a BOM with a shopping list, cut files for the router and laser, a robot weight tracker, and design reviews.

Every dialog teaches itself. Open any tool and read the **How to use this** box at the top, and hover over any box for a tip.

> Works on **Mac and Windows**. It works alongside [FRC Tools](https://github.com/4698RaiderRobotics/FRCTools).

---

## Install (students, about 2 minutes)

1. Go to this repo's **[Releases](../../releases/latest)** page and download **`Gusset-<version>.zip`**.
2. Unzip it, then double-click the installer:
   - **Mac:** `Install Gusset (Mac).command`. If macOS says it can't be opened, right-click it, choose **Open**, then **Open** again.
   - **Windows:** `Install Gusset (Windows).bat`. If Windows says it protected your PC, click **More info**, then **Run anyway**.
3. Open (or restart) Fusion. The **GUSSET** tab appears in the Design workspace.

Nothing shows up? In Fusion, go to **Utilities > Add-Ins > Scripts and Add-Ins**, find **Gusset**, and press **Run**. Tick **Run on Startup** while you're there.

## Updates

You only install once. When a mentor publishes a new version, Gusset asks **"Update now?"** the next time Fusion starts. Press **Update now** and it installs in a few seconds. Your settings stay. You can check any time in **GUSSET > Settings**, which also shows your version number.

## What's in the GUSSET tab

| | Tool | What it does |
|---|---|---|
| **Parts** | Shaft & Spacer | 1/2" hex shafts between two holes: extensions, tapped or turned-round ends, snap-ring grooves, and library bearings in the holes. Also spacers that fill the gap between two faces. |
| | Tube | Box tube (1x1, 2x1) from sketch lines, with the 0.5" hole pattern. |
| | Belt & Chain | Center distances for real HTD belts and #25/#35 chain, drawn into a sketch, with the library pulleys put in for you. |
| | Bearing Pocket | Bearing holes sized for your machines (press, snug, slip, 3D print). |
| **Features** | Hole Pattern | #10 / 1/4" holes on the FRC 0.5" grid. |
| | Quick Rib + Lighten | Ribs between the load points, then pocket the plate for weight. |
| **COTS** | COTS Library | A picture panel of the team's **FRC_COTS** Fusion project. Click a part to insert it. Gears and pulleys come one tile per family, so you pick the size. |
| | Add to Library | Add a vendor part (STEP file) with the right name, folder, price and link. |
| | Library Check | Finds duplicates, missing prices, links and pictures, and badly named files, each with a **Fix** button. |
| **Names & BOM** | Name Parts / Check Names | Team part numbers like `27-DRV-012` on every part, with a preview first. |
| | Export BOM | An Excel BOM (ready for monday.com) with a **Shopping list** tab grouped by vendor. |
| **Fabrication** | Fab Export / Export Face / Export Part | Cut files sorted by machine: SVG/DXF, 3MF prints, PDF lathe sheets. |
| **Review** | Robot Weight | A side panel with the robot's weight against the limit while you design, plus the heaviest parts. |
| | Design Review | Automatic checks, then a mentor checklist and sign-off. |
| | Settings | Your version, updates, this computer's options, and the team's settings. |

The full details of every tool and setting are in **[docs/REFERENCE.md](docs/REFERENCE.md)**.

## Learning Gusset

1. **Inside Fusion:** every dialog has a **How to use this** box with numbered steps and a **Why it matters** note. Hover over any box for what it does and an example value.
2. **The reference:** [docs/REFERENCE.md](docs/REFERENCE.md) explains every tool and setting in detail.
3. **Ask a teammate who's used it.** Then add the answer to the tips so nobody has to ask again (see [Contributing](CONTRIBUTING.md)).

## Something went wrong?

When Gusset hits an error, it opens a window with a one-line explanation and a **What to try** box.

1. Try what it suggests first.
2. Still stuck? Press **Report problem** in that window, or open a new **[Issue](../../issues/new/choose)** here (any free GitHub account works). Say what you clicked, what you expected, and paste the technical details from the error window.
3. **Use initials, not full names.** Gusset already removes your computer's user name from error details.

## Help build Gusset

Gusset is built by students, for students. The easiest way to help is to **[open an Issue](../../issues/new/choose)**: bugs, confusing tips and new ideas are all welcome. Want to change the code yourself? Read **[CONTRIBUTING.md](CONTRIBUTING.md)**. A mentor reviews every change before it reaches the team's laptops.

## For mentors

Publishing releases, team settings (subsystems, weight limits, bearing fits), and repo setup are covered in **[docs/MENTOR_SETUP.md](docs/MENTOR_SETUP.md)**.

## License

Gusset is free software under the **[GNU General Public License v3.0](LICENSE)**: you can use, study, change and share it. Anything you share that's built on it must stay open under the same license.

COTS part models (WCP, REV, AndyMark, and other vendors) are **not** in this repo. They live in the team's FRC_COTS Fusion project, and each one belongs to its vendor.
