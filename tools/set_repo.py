"""
set_repo.py - point Gusset's update check at the team's GitHub repo (run once).

    python tools/set_repo.py YOUR-TEAM/gusset

Sets config.UPDATE_REPO, then rebuilds the release (dist/Gusset-<version>.zip and
release/latest.json) so the download link uses the real repo. Commit the changes,
then follow docs/MENTOR_SETUP.md to publish the release.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config.py")


def main(argv) -> int:
    if len(argv) != 2 or not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+", argv[1]) or "OWNER" in argv[1]:
        print("Usage: python tools/set_repo.py OWNER/REPO   (for example: team1234/gusset)")
        return 2
    repo = argv[1]
    text = open(CONFIG, encoding="utf-8").read()
    new, count = re.subn(r'^UPDATE_REPO\s*=\s*"[^"]*"', f'UPDATE_REPO = "{repo}"', text, flags=re.M)
    if count != 1:
        print("Couldn't find UPDATE_REPO in config.py - set it by hand.")
        return 1
    open(CONFIG, "w", encoding="utf-8").write(new)
    print(f"[set_repo] config.UPDATE_REPO = {repo}")
    # The docs say OWNER/gusset until the real repo exists - fill it in there too.
    for doc in ("README.md", "CONTRIBUTING.md", os.path.join("docs", "MENTOR_SETUP.md")):
        path = os.path.join(ROOT, doc)
        if os.path.exists(path):
            body = open(path, encoding="utf-8").read()
            if "OWNER/gusset" in body:
                open(path, "w", encoding="utf-8").write(body.replace("OWNER/gusset", repo))
                print(f"[set_repo] filled in the repo name in {doc}")
    result = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "make_release.py")], cwd=ROOT)
    if result.returncode != 0:
        print("[set_repo] make_release.py failed - see above.")
        return result.returncode
    print("[set_repo] Done. Next: commit, push, then make the GitHub Release (docs/MENTOR_SETUP.md, step 4).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
