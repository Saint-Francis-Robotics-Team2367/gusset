# Contributing to Gusset

Thanks for helping! Gusset is built by students, for students. Fixing a typo in a tip helps just as much as a new tool.

**Just want to report a bug or idea?** Open an **[Issue](../../issues/new/choose)** - that's all you need.

**The one rule for code:** never push straight to `main`. Every laptop on the team updates from `main`, so all changes go through a **pull request** that a mentor reviews.

---

## 1. Get set up (once)

You need **Fusion**, **Python 3.12+** (only to run the tests) and **Git** (or GitHub Desktop).

1. **Clone the repo into a folder named exactly `Gusset`.** Fusion needs the folder name to match `Gusset.py`.
   ```
   git clone https://github.com/Saint-Francis-Robotics-Team2367/gusset.git Gusset
   ```
   (Use the real repo address from the green **Code** button.)
2. **Run your copy instead of the installed one.** In Fusion, go to **Utilities > Add-Ins > Scripts and Add-Ins**:
   - Select the installed **Gusset**, press **Stop**, and untick **Run on Startup**.
   - Press the **+** next to *My Add-Ins*, pick your cloned `Gusset` folder, and press **Run**.
   - Only one Gusset runs at a time. If the installed one is running, yours stays off.
3. Your copy never auto-updates, because Gusset sees it's a git folder. Get the newest code with `git pull`.

**Reloading after you change code:** in Scripts and Add-Ins, press **Stop** then **Run** on your copy. Dialog changes show up the next time you open the dialog.

## 2. Make a change

1. Start from fresh `main`, then make a branch named for what you're doing:
   ```
   git checkout main
   git pull
   git checkout -b fix-spacer-bore      # or: tip-lighten-wording, new-sprocket-calc ...
   ```
2. Make your change. Keep it to **one idea per pull request**, so it's easy to review.
3. Test it **in Fusion**, on a test design, never the real robot.
4. Run the automatic tests (they don't need Fusion):
   ```
   python -m pip install pytest
   python -m pytest tests
   ```
   Everything must pass. GitHub runs them again on Mac, Windows and Linux when you open your pull request.
5. Add a line under **## Unreleased** in `CHANGELOG.md`, written for students, e.g. `- Spacer: bore clearance now remembers the last value`.

## 3. Open a pull request

Push your branch (`git push -u origin fix-spacer-bore`), then open a pull request on GitHub. Not a collaborator? Click **Fork** on the repo page first, clone *your fork*, push your branch there, and GitHub will offer to open the pull request back to the team repo. The template asks:
- What changed and why, plus a screenshot if it's something you can see.
- How you tested it in Fusion (Mac, Windows or both).

A mentor will review it, maybe ask for changes, then merge it. It reaches everyone's laptop at the next release.

---

## How Gusset code is written

| Rule | Why |
|---|---|
| **Comment the why, not just the what.** | The next student has to understand it without asking you. |
| **Log as you go:** `_log.info(...)` for what happened, `_log.debug(...)` for details. | When something breaks on a teammate's laptop, the log is how we find out why. |
| **Never crash Fusion.** Catch errors and show a plain-English message (`fb.FeatureError("...")` or `fh.report_error(...)`). | Students should see "Pick two round edges", not a stack trace. |
| **Keep the math out of Fusion code.** Put calculations in a pure `lib/*_core.py` file (no `adsk` imports) with tests in `tests/`. | Tests run in a second without Fusion, so we catch mistakes before anyone opens CAD. |
| **Every dialog input needs a tip** in `lib/tips.py`: a short hover tip plus a longer description. Every dialog also needs a *How to use this* list and a *Why it matters* note. | `tests/test_tips.py` fails if one is missing, because students learn Gusset from these tips. |
| **Don't fill in design numbers for students.** Show reference values in a note, and let students type the real ones. | Typing a measurement is how you learn what the part looks like. |
| **Works on Mac and Windows:** use `os.path.join`, never hard-coded `/` or `\` paths. | Half the team uses each. |

### Student privacy

- **Never commit anyone's full name**, in code, tests, issues or screenshots. Use initials or `[STUDENT NAME]`.
- Never commit `gusset_config.json`, `gusset_state.json`, `logs/` or `cache/`. `.gitignore` already keeps them out, so don't force-add them.
- Crop screenshots so they don't show your name or email.

## Where things live

```
Gusset.py, config.py      start-up and version number
commands/                 one file per button / panel (the Fusion side)
lib/                      shared code - *_core.py files are pure Python with tests
lib/tips.py               every student tip, all in one place
resources/                icons and the HTML panels (COTS Library, Library Check, Robot Weight, Settings)
tests/                    automatic tests (python -m pytest tests)
installer/                the one-click Mac and Windows installers
tools/                    release builder (mentors) and helpers
docs/                     REFERENCE.md (every tool) and MENTOR_SETUP.md
team_settings.json        the team's shared settings - mentors change these
release/latest.json       what laptops check for updates - made by tools/make_release.py
```

## Ideas and bugs without code

No time to code? Open an **[Issue](../../issues/new/choose)**. Bug reports and "this tip confused me" notes are some of the most useful contributions.
