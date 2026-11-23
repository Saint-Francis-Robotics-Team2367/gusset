"""
settings.py - Gusset's settings, in three layers (later wins):

    built-in defaults (DEFAULT_SETTINGS below)
    gusset_config.json         this laptop's file (older laptops kept team values here)
    team_settings.json         the TEAM's settings, downloaded from GitHub with each
                               update check - every laptop matches
    team_settings_draft.json   a mentor's unpublished edits (this laptop only)
  + PERSONAL_KEYS always come from gusset_config.json (each student's own choices)

So students can't drift apart: a team value from GitHub beats a local one. A mentor
edits team settings in GUSSET > Settings (mentor mode), which writes the draft, then
publishes it to GitHub; when GitHub's copy matches, the draft is removed.

No Fusion imports here, so this is unit-testable too.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
from typing import Any, Dict, List, Optional

from .bom_core import DEFAULT_PROCESSES, PROCESS_TBD
from .frc_features import DEFAULT_BEARINGS, DEFAULT_FITS, Bearing, bearing_from_dict, bearing_to_dict
from .naming_core import (
    DEFAULT_SHARED_CODE,
    DEFAULT_COTS_PATTERNS,
    DEFAULT_NAME_PATTERNS,
    DEFAULT_SUBSYSTEMS,
    NamingConfig,
)

log = logging.getLogger("gusset.settings")

CONFIG_FILENAME = "gusset_config.json"
TEAM_FILENAME = "team_settings.json"
DRAFT_FILENAME = "team_settings_draft.json"
# Each laptop's own choices - never overridden by team settings.
PERSONAL_KEYS = {"check_updates", "debug_logs"}
PERSONAL_DEFAULTS: Dict[str, Any] = {"check_updates": True, "debug_logs": True}

DEFAULT_SETTINGS: Dict[str, Any] = {
    "_help": [
        "Gusset team settings. Save this file, then reopen any Gusset tool.",
        "season_year: 'auto' picks next season from September on, or set two digits like '27'.",
        "name_format: how component names look. {pn} = part number, {desc} = description.",
        "subsystems: CODE -> name. Codes are 2-4 capital letters or digits.",
        "cots_patterns: regular expressions; a match means 'bought part, don't renumber'.",
        "shared_subsystem: code for team parts used by more than one subsystem ('' turns this off).",
        "scan_project: true = check every file name in the Fusion project so numbers never repeat.",
        "processes: choices in Export BOM's Process column (keep 'TBD' as the 'not decided yet' choice).",
        "fab_units: 'in' or 'mm' for SVG/DXF exports. xcarve_format / laser_format: 'svg' or 'dxf'.",
        "bearings: sizes in inches for Bearing Pocket. bearing_fits: inches added to the bearing OD (negative = tighter).",
        "review_checklist: Design Review's mentor checklist, as [item, why it matters] pairs.",
        "weight_limits: Robot Weight panel limits in pounds (check the game manual each Kickoff). "
        "weight_exclude: words that mark parts not weighed with the robot (bumpers, battery). "
        "weight_default_materials: Fusion's default material - made parts still on it are flagged.",
    ],
    "season_year": "auto",
    "name_format": "{pn} {desc}",
    "shared_subsystem": DEFAULT_SHARED_CODE,
    "scan_project": True,
    "processes": list(DEFAULT_PROCESSES),
    "fab_units": "in",
    "xcarve_format": "svg",
    "laser_format": "svg",
    "bearings": [bearing_to_dict(b) for b in DEFAULT_BEARINGS],
    "bearing_fits": {name: allowance for name, (allowance, _why) in DEFAULT_FITS.items()},
    "subsystems": dict(DEFAULT_SUBSYSTEMS),
    "cots_patterns": list(DEFAULT_COTS_PATTERNS),
    "default_name_patterns": list(DEFAULT_NAME_PATTERNS),
    # Robot Weight panel (0.13). 2026 rules: robot <= 115 lb without bumpers and battery (R103),
    # robot + bumpers <= 135 lb (R408). Check each season's game manual at Kickoff.
    "weight_limits": {"robot_lb": 115, "robot_with_bumpers_lb": 135, "warn_at_percent": 95},
    "weight_exclude": ["bumper", "battery"],
    "weight_default_materials": ["Steel"],
}


# Patterns older Gusset versions wrote into gusset_config.json that have since
# been improved. Only EXACT copies of what Gusset shipped are replaced, so a
# team's own edits are never touched.
_OLD_PATTERN_UPGRADES = {
    r"(?i)\b(bearing|bolt|screw|nut|washer|rivet|shaft collar)s?\b": [
        r"(?i)\bbearings?\b(?!\s*(block|plate|mount|holder|retainer|cap|support|spacer)s?\b)",
        r"(?i)\b(bolt|screw|nut|washer|rivet|shaft collar)s?\b",
    ],
}


def upgrade_cots_patterns(patterns: List[str]) -> List[str]:
    out: List[str] = []
    for pattern in patterns:
        if pattern in _OLD_PATTERN_UPGRADES:
            log.info("Upgrading an old COTS pattern from settings (bearing blocks are team-made)")
            out.extend(_OLD_PATTERN_UPGRADES[pattern])
        else:
            out.append(pattern)
    return out


def default_season_year(today: Optional[datetime.date] = None) -> str:
    """FRC seasons are named for the year of kickoff (January).
    From September on we're designing for next year's robot."""
    today = today or datetime.date.today()
    year = today.year + 1 if today.month >= 9 else today.year
    return f"{year % 100:02d}"


def config_path(addin_dir: str) -> str:
    return os.path.join(addin_dir, CONFIG_FILENAME)


def ensure_config_file(addin_dir: str) -> str:
    """Create the settings file with defaults if it doesn't exist yet."""
    path = config_path(addin_dir)
    if not os.path.exists(path):
        log.info("No settings file yet; writing defaults to %s", path)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(DEFAULT_SETTINGS, handle, indent=2)
    return path


def config_from_dict(data: Dict[str, Any], today: Optional[datetime.date] = None) -> NamingConfig:
    """Build a NamingConfig, falling back to defaults for anything missing or broken."""
    if not isinstance(data, dict):
        log.error("Settings file should contain a JSON object; using defaults")
        data = {}

    season = str(data.get("season_year", "auto")).strip()
    if season.lower() == "auto" or not season:
        season = default_season_year(today)
        log.info("season_year is auto -> %s", season)

    subsystems = data.get("subsystems")
    if not isinstance(subsystems, dict):
        if subsystems is not None:
            log.warning("'subsystems' should be an object like {\"ELV\": \"Elevator\"}; using defaults")
        subsystems = dict(DEFAULT_SUBSYSTEMS)

    def str_list(key: str, fallback):
        value = data.get(key)
        if isinstance(value, list) and all(isinstance(v, str) for v in value):
            return value
        if value is not None:
            log.warning("'%s' should be a list of text; using defaults", key)
        return list(fallback)

    kwargs = dict(
        subsystems=subsystems,
        name_format=str(data.get("name_format") or "{pn} {desc}"),
        cots_patterns=upgrade_cots_patterns(str_list("cots_patterns", DEFAULT_COTS_PATTERNS)),
        default_name_patterns=str_list("default_name_patterns", DEFAULT_NAME_PATTERNS),
        shared_code=str(data.get("shared_subsystem", DEFAULT_SHARED_CODE) or ""),
    )
    try:
        return NamingConfig(season_year=season, **kwargs)
    except ValueError as exc:
        fallback = default_season_year(today)
        log.error("Bad season_year (%s); using %s instead", exc, fallback)
        return NamingConfig(season_year=fallback, **kwargs)


def _load_json(path: str) -> Dict[str, Any]:
    """A settings file as a dict ({} if missing; logs typos plainly)."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return data
        log.error("%s should hold one { ... } object; ignoring it", os.path.basename(path))
    except json.JSONDecodeError as exc:
        log.error("%s has a typo at line %d, column %d (%s); ignoring it until it's fixed.",
                  os.path.basename(path), exc.lineno, exc.colno, exc.msg)
    except OSError as exc:
        log.error("Couldn't read %s (%s)", path, exc)
    return {}


def merge_layers(local: Dict[str, Any], team: Dict[str, Any], draft: Dict[str, Any]) -> Dict[str, Any]:
    """Defaults < local < team < draft, then personal keys from local. Pure, for tests."""
    out: Dict[str, Any] = dict(DEFAULT_SETTINGS)
    out.update(PERSONAL_DEFAULTS)
    for layer in (local, team, draft):
        out.update({k: v for k, v in layer.items() if not k.startswith("_") and k not in PERSONAL_KEYS})
    out.update({k: local[k] for k in PERSONAL_KEYS if k in local})
    return out


_cache: Dict[str, Any] = {}


def read_settings(addin_dir: str) -> Dict[str, Any]:
    """All settings, layered (see the top of this file). Re-read only when a file changes."""
    paths = [ensure_config_file(addin_dir), os.path.join(addin_dir, TEAM_FILENAME),
             os.path.join(addin_dir, DRAFT_FILENAME)]
    stamp = tuple(os.path.getmtime(p) if os.path.exists(p) else 0 for p in paths)
    if _cache.get("key") == (addin_dir, stamp):
        return _cache["value"]
    value = merge_layers(*(_load_json(p) for p in paths))
    _cache.update(key=(addin_dir, stamp), value=value)
    return value


def team_layers(addin_dir: str) -> Dict[str, Dict[str, Any]]:
    """The raw team layers, for the Settings window."""
    return {"team": _load_json(os.path.join(addin_dir, TEAM_FILENAME)),
            "draft": _load_json(os.path.join(addin_dir, DRAFT_FILENAME))}


def team_keys() -> List[str]:
    """Every setting that belongs to the team (everything but personal keys and notes)."""
    return [k for k in DEFAULT_SETTINGS if not k.startswith("_")] + ["lighten_defaults", "lighten_cutters",
                                                                     "review_checklist", "cots",
                                                                     "number_scan_scope"]


def effective_team_settings(addin_dir: str) -> Dict[str, Any]:
    """The team settings this laptop is using right now (what a mentor would publish)."""
    merged = read_settings(addin_dir)
    return {k: merged[k] for k in team_keys() if k in merged}


def save_team_draft(addin_dir: str, values: Dict[str, Any]) -> str:
    """A mentor's (or the bearing library's) team edits: saved on THIS laptop until published."""
    path = os.path.join(addin_dir, DRAFT_FILENAME)
    current = _load_json(path) or effective_team_settings(addin_dir)
    current.update({k: v for k, v in values.items() if k not in PERSONAL_KEYS})
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(current, handle, indent=2, sort_keys=True)
    os.replace(tmp, path)
    log.info("Saved team settings draft on this laptop: %s", ", ".join(sorted(values)))
    return path


def discard_team_draft(addin_dir: str) -> bool:
    path = os.path.join(addin_dir, DRAFT_FILENAME)
    if os.path.exists(path):
        os.replace(path, path + ".discarded")
        log.info("Discarded the team settings draft (kept a copy as %s.discarded)", DRAFT_FILENAME)
        return True
    return False


def same_settings(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    strip = lambda d: {k: v for k, v in d.items() if not k.startswith("_")}
    return json.dumps(strip(a), sort_keys=True) == json.dumps(strip(b), sort_keys=True)


def write_team_settings(addin_dir: str, text: str) -> bool:
    """
    Save team settings downloaded from GitHub. Returns True if they changed. A
    draft that now matches what's published is cleared (the mentor published it).
    """
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("team_settings.json should hold one { ... } object")
    path = os.path.join(addin_dir, TEAM_FILENAME)
    changed = not same_settings(_load_json(path), data)
    if changed:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
        os.replace(tmp, path)
        log.info("Team settings updated from GitHub")
    draft_path = os.path.join(addin_dir, DRAFT_FILENAME)
    draft = _load_json(draft_path)
    published = all(json.dumps(data.get(k), sort_keys=True) == json.dumps(v, sort_keys=True)
                    for k, v in draft.items() if not k.startswith("_"))
    if draft and published:
        os.remove(draft_path)
        log.info("The team settings draft matches GitHub now - draft removed")
    return changed


def read_flag(addin_dir: str, key: str, default: bool) -> bool:
    """Read one true/false setting that isn't part of NamingConfig (e.g. scan_project)."""
    value = read_settings(addin_dir).get(key, default)
    return value if isinstance(value, bool) else default


def read_choice(addin_dir: str, key: str, choices: List[str], default: str) -> str:
    """Read a setting that must be one of `choices` (case-insensitive)."""
    value = read_settings(addin_dir).get(key, default)
    value = str(value).strip().lower()
    if value not in choices:
        log.warning("Setting %s=%r should be one of %s; using %r", key, value, choices, default)
        return default
    return value


def _read_key(addin_dir: str, key: str):
    return read_settings(addin_dir).get(key)


def update_settings(addin_dir: str, **values: Any) -> None:
    """
    Change some keys in gusset_config.json, keeping everything else in it.
    Team keys written here are overridden by team settings - use save_team_draft for those.
    """
    path = ensure_config_file(addin_dir)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"couldn't read the settings file to update it ({exc}); fix or delete it first")
    data.update(values)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
    os.replace(tmp, path)
    log.info("Updated settings: %s", ", ".join(values))


def read_bearings(addin_dir: str) -> List[Bearing]:
    """Bearing table for Bearing Pocket (settings override the built-in list)."""
    value = _read_key(addin_dir, "bearings")
    if isinstance(value, list):
        bearings = [b for b in (bearing_from_dict(d) for d in value if isinstance(d, dict)) if b]
        if bearings:
            return bearings
        log.warning("'bearings' in settings has no usable entries; using the built-in list")
    return list(DEFAULT_BEARINGS)


def read_bearing_fits(addin_dir: str) -> Dict[str, Any]:
    """{fit: (allowance_in, explanation)}. Settings may change the numbers or add fits."""
    fits = dict(DEFAULT_FITS)
    value = _read_key(addin_dir, "bearing_fits")
    if isinstance(value, dict):
        for name, allowance in value.items():
            try:
                fits[str(name)] = (float(allowance), DEFAULT_FITS.get(str(name), (0, "your team's fit"))[1])
            except (TypeError, ValueError):
                log.warning("bearing_fits[%r] should be a number of inches", name)
    return fits


def read_cutters(addin_dir: str):
    """Cutters for Lighten (sets the inside-corner radius). Settings: "lighten_cutters" list."""
    from .lighten_core import DEFAULT_CUTTERS, cutter_from_dict
    value = _read_key(addin_dir, "lighten_cutters")
    if isinstance(value, list):
        cutters = [c for c in (cutter_from_dict(d) for d in value if isinstance(d, dict)) if c]
        if cutters:
            return cutters
        log.warning("'lighten_cutters' in settings has no usable entries; using the built-in list")
    return [c for c in (cutter_from_dict(d) for d in DEFAULT_CUTTERS) if c]


def read_lighten_defaults(addin_dir: str) -> Dict[str, float]:
    """Wall / rib / boss / smallest pocket / rib spacing defaults (inches). Settings: "lighten_defaults"."""
    from .lighten_core import DEFAULTS
    values = dict(DEFAULTS)
    value = _read_key(addin_dir, "lighten_defaults")
    if isinstance(value, dict):
        for key, number in value.items():
            if key in values:
                try:
                    values[key] = float(number)
                except (TypeError, ValueError):
                    log.warning("lighten_defaults[%r] should be a number of inches", key)
    return values


def read_review_checklist(addin_dir: str):
    """[(item, why it matters)] for Design Review. Settings: list of [item, why] or plain strings."""
    from .review_core import DEFAULT_CHECKLIST
    value = _read_key(addin_dir, "review_checklist")
    if not isinstance(value, list):
        return list(DEFAULT_CHECKLIST)
    items = []
    for entry in value:
        if isinstance(entry, str) and entry.strip():
            items.append((entry.strip(), ""))
        elif isinstance(entry, (list, tuple)) and entry and str(entry[0]).strip():
            items.append((str(entry[0]).strip(), str(entry[1]).strip() if len(entry) > 1 else ""))
    return items or list(DEFAULT_CHECKLIST)


def read_processes(addin_dir: str) -> List[str]:
    """Process choices for Export BOM. Always includes TBD (= not decided yet)."""
    value = read_settings(addin_dir).get("processes")
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        if value is not None:
            log.warning("'processes' should be a list of text; using defaults")
        value = list(DEFAULT_PROCESSES)
    choices = [v.strip() for v in value]
    if PROCESS_TBD not in choices:
        choices.append(PROCESS_TBD)
    return choices


# --- Small remembered state (last export folder, ...). Not team settings.
STATE_FILENAME = "gusset_state.json"


def load_state(addin_dir: str) -> Dict[str, Any]:
    try:
        with open(os.path.join(addin_dir, STATE_FILENAME), "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_state(addin_dir: str, **values: Any) -> None:
    data = load_state(addin_dir)
    data.update(values)
    try:
        with open(os.path.join(addin_dir, STATE_FILENAME), "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
    except OSError as exc:
        log.warning("Couldn't save %s (%s)", STATE_FILENAME, exc)


def load_config(addin_dir: str) -> NamingConfig:
    """Read settings (all layers). Never raises: a broken file falls back to defaults."""
    return config_from_dict(read_settings(addin_dir))


# --- Checking team settings before a mentor saves them (Settings window) -----
def _is_positive(value) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def read_weight_settings(addin_dir: str) -> Dict[str, Any]:
    """Limits, exclude words and default materials for the Robot Weight panel (never raises)."""
    try:
        data = read_settings(addin_dir)
    except Exception:
        data = {}
    pick = lambda k: data.get(k) if data.get(k) not in (None, "", [], {}) else DEFAULT_SETTINGS[k]  # noqa: E731
    return {"limits": pick("weight_limits"), "exclude": pick("weight_exclude"),
            "default_materials": pick("weight_default_materials")}


def validate_team(data: Dict[str, Any]) -> List[str]:
    """Plain-English problems with a set of team settings ([] = fine to save)."""
    import re
    problems: List[str] = []
    if not isinstance(data, dict):
        return ["Team settings must be one { ... } object."]
    season = str(data.get("season_year", "auto")).strip().lower()
    if season != "auto" and not re.fullmatch(r"\d{2}", season):
        problems.append("Season year must be 'auto' or two digits, like 27.")
    subs = data.get("subsystems", {})
    if not isinstance(subs, dict) or not subs:
        problems.append("Add at least one subsystem code.")
    else:
        for code, name in subs.items():
            if not re.fullmatch(r"[A-Z0-9]{2,4}", str(code)):
                problems.append(f"Subsystem code '{code}' should be 2-4 capital letters or digits.")
            if not str(name).strip():
                problems.append(f"Subsystem {code} needs a name.")
    shared = str(data.get("shared_subsystem", "") or "")
    if shared and isinstance(subs, dict) and shared not in subs:
        problems.append(f"Shared code '{shared}' isn't one of the subsystem codes.")
    fmt = str(data.get("name_format", "{pn} {desc}"))
    if "{pn}" not in fmt:
        problems.append("Name format must include {pn} (the part number).")
    procs = data.get("processes", [])
    if not isinstance(procs, list) or not all(isinstance(p, str) and p.strip() for p in procs):
        problems.append("Processes must be a list of names.")
    limits = data.get("weight_limits", {})
    if limits and (not isinstance(limits, dict) or any(not _is_positive(v) for v in limits.values())):
        problems.append("Weight limits must be positive numbers (pounds; warn_at_percent like 95).")
    for key in ("weight_exclude", "weight_default_materials"):
        if key in data and not (isinstance(data[key], list) and all(isinstance(w, str) for w in data[key])):
            problems.append(f"{key} must be a list of words.")
    for key, allowed in (("fab_units", ("in", "mm")), ("xcarve_format", ("svg", "dxf")),
                         ("laser_format", ("svg", "dxf")), ("number_scan_scope", ("season folder", "project"))):
        if key in data and str(data[key]).lower() not in allowed:
            problems.append(f"{key} must be one of: {', '.join(allowed)}.")
    for key in ("bearing_fits", "lighten_defaults"):
        value = data.get(key)
        if value is not None:
            if not isinstance(value, dict):
                problems.append(f"{key} must be a list of name: number.")
            else:
                for name, number in value.items():
                    try:
                        float(number)
                    except (TypeError, ValueError):
                        problems.append(f"{key} '{name}' must be a number (inches).")
    for key in ("cots_patterns", "default_name_patterns"):
        for pattern in data.get(key, []) or []:
            try:
                re.compile(pattern)
            except re.error as exc:
                problems.append(f"{key}: '{pattern}' isn't a valid pattern ({exc}).")
    return problems
