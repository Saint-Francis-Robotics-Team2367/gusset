"""
make_release.py - builds a Gusset release (run from the Gusset folder):

    python tools/make_release.py

makes, in dist/:
    Gusset-<version>.zip    Gusset/ + both installers + READ ME FIRST.txt
                            (never this computer's gusset_config.json, state, logs or cache)
and updates release/latest.json (version, zip link, sha256, notes from CHANGELOG.md).

To publish (GitHub, public repo in config.UPDATE_REPO):
    1. Make a GitHub release named v<version> and attach dist/Gusset-<version>.zip
    2. Commit release/latest.json (and team_settings.json if it changed) to main
Every laptop offers the update at its next check (Fusion start, at most every 6 h).
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lib import update_core as uc  # noqa: E402

SKIP_DIRS = {"logs", "cache", "__pycache__", ".git", "dist", ".pytest_cache", "installer", ".github", "docs", "tests"}
SKIP_FILES = {"gusset_config.json", "gusset_state.json", "team_settings_draft.json", ".DS_Store"}
README = """Gusset {version} - how to install

  Mac:      double-click "Install Gusset (Mac).command"
            (if macOS says it can't be opened: right-click it > Open > Open)
  Windows:  double-click "Install Gusset (Windows).bat"
            (if Windows says it protected your PC: More info > Run anyway)

Then open Fusion: the GUSSET tab appears by itself.
After this, Gusset updates itself - it asks when a new version is ready.
"""


def read_config():
    text = open(os.path.join(ROOT, "config.py"), encoding="utf-8").read()
    version = uc.read_zip_version(text)
    repo = re.search(r'^UPDATE_REPO\s*=\s*"([^"]*)"', text, re.M).group(1)
    return version, repo


def notes_for(version: str):
    path = os.path.join(ROOT, "CHANGELOG.md")
    if not os.path.exists(path):
        return []
    text = open(path, encoding="utf-8").read()
    m = re.search(rf"^##\s*{re.escape(version)}\b.*?$(.*?)(?=^##\s|\Z)", text, re.M | re.S)
    if not m:
        return []
    return [line.strip()[2:].strip() for line in m.group(1).splitlines() if line.strip().startswith("- ")]


def build() -> str:
    version, repo = read_config()
    manifest = json.load(open(os.path.join(ROOT, "Gusset.manifest"), encoding="utf-8"))
    if manifest.get("version") != version:
        raise SystemExit(f"Gusset.manifest says {manifest.get('version')} but config.py says {version} - fix one")
    os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
    out = os.path.join(ROOT, "dist", f"Gusset-{version}.zip")
    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(ROOT):
            rel_dir = os.path.relpath(dirpath, ROOT)
            if rel_dir != "." and rel_dir.split(os.sep)[0] in SKIP_DIRS:
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for f in sorted(filenames):
                if f in SKIP_FILES or f.endswith((".pyc", ".tmp")):
                    continue
                rel = os.path.normpath(os.path.join(rel_dir, f)).replace(os.sep, "/")
                zf.write(os.path.join(dirpath, f), "Gusset/" + rel)
                count += 1
        for name in os.listdir(os.path.join(ROOT, "installer")):
            info = zipfile.ZipInfo(name, date_time=datetime.datetime.now().timetuple()[:6])
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if name.endswith(".command") else 0o644) << 16   # Mac: keep it runnable
            data = open(os.path.join(ROOT, "installer", name), "rb").read()
            if name.endswith(".bat"):
                data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")            # Windows line endings
            zf.writestr(info, data)
        zf.writestr("READ ME FIRST.txt", README.format(version=version).replace("\n", "\r\n"))
    data = open(out, "rb").read()
    latest = {"version": version,
              "zip": f"https://github.com/{repo}/releases/download/v{version}/Gusset-{version}.zip",
              "sha256": uc.sha256_of(data), "released": datetime.date.today().isoformat(),
              "notes": notes_for(version)}
    uc.parse_latest(json.dumps(latest))                 # same checks the laptops make
    os.makedirs(os.path.join(ROOT, "release"), exist_ok=True)
    with open(os.path.join(ROOT, "release", "latest.json"), "w", encoding="utf-8") as handle:
        json.dump(latest, handle, indent=2)
    print(f"Built {out}: {count} files, {len(data) / 1024:.0f} KB, sha256 {latest['sha256'][:12]}...")
    print(f"Wrote release/latest.json ({len(latest['notes'])} notes)")
    if not uc.repo_is_set(repo):
        print("NOTE: config.UPDATE_REPO is still a placeholder - set it before publishing.")
    return out


if __name__ == "__main__":
    build()
