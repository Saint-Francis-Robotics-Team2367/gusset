"""
update_core.py - the plain-Python side of Gusset's updater (no Fusion imports;
tested in tests/test_update_core.py).

HOW UPDATES ARE PUBLISHED (public GitHub repo, see config.UPDATE_REPO)
    release/latest.json      on the main branch - a tiny file every laptop checks:
        {
          "version": "0.9.4",
          "zip": "https://github.com/<owner>/<repo>/releases/download/v0.9.4/Gusset-0.9.4.zip",
          "sha256": "<64 hex characters of the zip>",
          "released": "2026-11-21",
          "notes": ["COTS panel: family tiles", "Fixed ..."]
        }
    team_settings.json       on the main branch - the team's settings (season year,
                             subsystem codes, processes...). Every laptop uses these.
    Gusset-0.9.4.zip         a GitHub release asset: Gusset/ + the installers.

Reading raw.githubusercontent.com and release downloads doesn't count against
GitHub's 60-requests-an-hour API limit, so a whole classroom on one school
network can check at once.

HOW AN UPDATE IS APPLIED (lib/updater.py does the file work)
    1. download the zip, check its sha256 matches latest.json
    2. find the Gusset/ folder inside, check it's really Gusset at that version
    3. back up the current code to cache/previous/ (Settings > Undo last update)
    4. copy the new code over the install, never touching PRESERVE
    5. ask the student to restart Fusion
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Tuple

# Never overwritten or backed up by an update: this laptop's own files.
PRESERVE_FILES = {"gusset_config.json", "gusset_state.json", "team_settings_draft.json"}
PRESERVE_DIRS = {"logs", "cache", ".git", "__pycache__"}
CHECK_EVERY_HOURS = 6
_VERSION = re.compile(r"^\s*v?(\d+)\.(\d+)(?:\.(\d+))?\s*$")


def parse_version(text: str) -> Optional[Tuple[int, int, int]]:
    """'0.9.4' / 'v0.10' -> (0, 9, 4) / (0, 10, 0); None if it isn't a version."""
    m = _VERSION.match(str(text or ""))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)


def is_newer(candidate: str, current: str) -> bool:
    """True if candidate is a later version than current (0.10.0 > 0.9.9)."""
    a, b = parse_version(candidate), parse_version(current)
    return bool(a and b and a > b)


@dataclass
class Release:
    version: str
    zip_url: str
    sha256: str
    released: str = ""
    notes: List[str] = field(default_factory=list)


def parse_latest(text: str) -> Release:
    """latest.json -> Release. Raises ValueError with a plain-English reason."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        raise ValueError("latest.json isn't valid JSON")
    if not isinstance(data, dict):
        raise ValueError("latest.json should hold one { ... } object")
    version = str(data.get("version", "")).strip()
    if not parse_version(version):
        raise ValueError(f"latest.json has no usable version ({version!r})")
    zip_url = str(data.get("zip", "")).strip()
    if not zip_url.startswith("https://"):
        raise ValueError("latest.json's zip link must start with https://")
    sha = str(data.get("sha256", "")).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ValueError("latest.json's sha256 should be 64 hex characters")
    notes = data.get("notes", [])
    if isinstance(notes, str):
        notes = [notes]
    notes = [str(n).strip() for n in notes if str(n).strip()] if isinstance(notes, list) else []
    return Release(version, zip_url, sha, str(data.get("released", "")).strip(), notes)


def raw_url(repo: str, branch: str, path: str) -> str:
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"


def latest_url(repo: str, branch: str = "main") -> str:
    return raw_url(repo, branch, "release/latest.json")


def team_settings_url(repo: str, branch: str = "main") -> str:
    return raw_url(repo, branch, "team_settings.json")


def repo_is_set(repo: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+", repo or "")) and "OWNER" not in repo


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def due_for_check(last_check: float, now: float, hours: float = CHECK_EVERY_HOURS) -> bool:
    """Never checked -> due. Otherwise once every `hours` (or if the clock went backwards)."""
    if not last_check or now < last_check:
        return True
    return now - last_check >= hours * 3600


def find_package_root(names: Iterable[str]) -> Optional[str]:
    """
    Where Gusset lives inside a release zip: the folder holding Gusset.py and
    Gusset.manifest ('Gusset/' normally; '' if they're at the top).
    """
    names = [n.replace("\\", "/") for n in names]
    candidates = []
    for n in names:
        if n.endswith("Gusset.py"):
            root = n[: -len("Gusset.py")]
            if root + "Gusset.manifest" in names and "__MACOSX" not in root:
                candidates.append(root)
    return min(candidates, key=len) if candidates else None


def files_to_install(names: Iterable[str], root: str) -> List[str]:
    """Relative paths under root to copy, skipping PRESERVE and junk."""
    out = []
    for n in names:
        n = n.replace("\\", "/")
        if not n.startswith(root) or n.endswith("/"):
            continue
        rel = n[len(root):]
        parts = rel.split("/")
        if not rel or parts[0] in PRESERVE_DIRS or rel in PRESERVE_FILES:
            continue
        if any(p in ("__pycache__", "__MACOSX") or p.startswith("._") or p == ".DS_Store" for p in parts):
            continue
        if ".." in parts:
            raise ValueError(f"unsafe path in the update zip: {n}")
        out.append(rel)
    return sorted(out)


def read_zip_version(config_text: str) -> Optional[str]:
    """VERSION = "x.y.z" from a config.py inside the zip."""
    m = re.search(r'^VERSION\s*=\s*["\']([^"\']+)["\']', config_text or "", re.M)
    return m.group(1) if m else None


def summary_line(release: Release, current: str) -> str:
    return f"Gusset {release.version} is ready (you have {current})."
