# Mentor setup and releases

Everything a mentor does that students don't: create the repo once, publish releases, and manage team settings.

---

## First time: create the repo (about 10 minutes)

1. **Create the repo on GitHub.** Make it **Public** (laptops read updates from it without signing in), named e.g. `gusset`, with **no** README, license or .gitignore (this folder already has them).
2. **Put this folder in it.** From inside the `Gusset` folder:
   ```
   git init -b main
   git add .
   git commit -m "Gusset 0.13.2"
   git remote add origin https://github.com/Saint-Francis-Robotics-Team2367/gusset.git
   git push -u origin main
   ```
3. **Point Gusset at the repo.** Use the real owner/name:
   ```
   python tools/set_repo.py Saint-Francis-Robotics-Team2367/gusset
   git add config.py release/latest.json
   git commit -m "Point updates at Saint-Francis-Robotics-Team2367/gusset"
   git push
   ```
   This also builds `dist/Gusset-0.13.2.zip`, with the right download link inside.
4. **Publish the first release** (see *Publishing a release* below, steps 3-4).
5. **Protect `main`:** the **Protect main** ruleset (Settings > Rules > Rulesets) requires a pull request with a Code Owner's approval (`.github/CODEOWNERS`), the three **Tests** checks, resolved conversations, and blocks deletions and force pushes. Repository admins can merge their own pull requests (bypass: pull requests only). To rebuild it, import `docs/Protect main ruleset.json` from **New ruleset > Import a ruleset**.
6. **Students report problems with Issues:** the repo is public, so anyone with a free GitHub account can open an Issue - no collaborator access needed. Students who later change code can fork the repo and open a pull request from their fork (or be added as collaborators with **Write**).

Then install on every laptop once, from the release zip. After that, updates come by themselves.

## Publishing a release

Do this when `main` has changes you want on everyone's laptop.

1. **Bump the version** in **both** `config.py` (`VERSION = "0.13.3"`) and `Gusset.manifest` (`"version"`). The builder refuses if they don't match.
2. **CHANGELOG.md:** rename `## Unreleased` to `## 0.13.3 - short title`, and add a fresh empty `## Unreleased` above it. Each `- ` line shows in the students' "What's new" update window, so write it for them.
3. **Build:**
   ```
   python -m pytest tests          # must pass
   python tools/make_release.py    # -> dist/Gusset-0.13.3.zip + release/latest.json
   ```
4. **On GitHub:** go to **Releases > Draft a new release**. Use the tag **`v0.13.3`** (exactly `v` + the version), paste the CHANGELOG lines as the description, attach **`dist/Gusset-0.13.3.zip`**, and press **Publish**.
5. **Commit `release/latest.json`** (plus the version bump) to `main`, through a pull request if `main` is protected. **This commit is what makes laptops offer the update**, so do it *after* the release zip is uploaded.

Each laptop checks when Fusion starts, at most every 6 hours, and asks before installing. If a release goes wrong, any laptop can undo it in **Settings > Advanced > Undo last update**.

## Team settings

`team_settings.json` holds settings every laptop shares: subsystem codes, the season year, bearings and fits, weight limits, Design Review's checklist, and so on.

- **Easiest:** in Fusion, open **GUSSET > Settings > Team**, press **Edit team settings (mentors)**, change things, then press **Publish**. That copies the JSON and opens GitHub's editor for `team_settings.json`. Paste and commit.
- Laptops pick up new team settings at their next update check (no release needed).
- **Every Kickoff:** update **Robot weight** limits from the new game manual, and the **season year** if it's set by hand.

## Branches and reviews

- Students work on branches and open pull requests. GitHub runs the tests on Mac, Windows and Linux.
- Before approving, **pull the branch and try it in Fusion**: `git fetch`, then `git checkout their-branch`, then Stop/Run your dev copy. The automatic tests can't open Fusion.
- Check new dialog inputs have tips (the tests enforce it), and that no full student names appear anywhere.

## Your own laptop

If you cloned the repo to work on Gusset, your copy is a git folder, so it never auto-updates. Use `git pull`. Students' installed copies update normally.
