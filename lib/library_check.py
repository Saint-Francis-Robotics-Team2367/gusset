"""
library_check.py - the COTS Library Check (no Fusion imports; tested in
tests/test_library_check.py).

check(items, ...) looks over the catalog the COTS panel already has and returns a
Problem for everything that would trip a student up later:

    kind          level   what it means                               fix (button)
    duplicate     fix     two files are the same part                 review   - move the extra to _Review
    temp_id       fix     the panel only has an upload's temporary id relink   - look it up again
    missing       fix     the file is gone from the cloud (full check) rescan  - read the library again
    no_picture    fix     Fusion has no thumbnail for it              resave   - open, fit, save a version
    name          fix     file name isn't '<part #> <name>'           rename
    folder        fix     sits in another vendor/category's folder    move
    part_number   fix     part # missing or not the vendor's format   details
    wrong_link    fix     link isn't on the vendor's store            details  (link suggested)
    no_link       info    no store link                               details  (link suggested)
    no_price      info    no price                                    details
    bad_price     fix     price isn't a number                        details
    old_price     tip     price was entered over a year ago           details
    category      tip     folder isn't one of the team's categories   (none - just a heads-up)

Levels: "fix" problems count in the COTS panel's badge; "info" (missing details)
is shown as its own count; "tip" is only shown in the check window.
Every message is written for students: what's wrong, then what the button does.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import asdict, dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence
from urllib.parse import urlparse

from . import cots_core as cc

FIX, INFO, TIP = "fix", "info", "tip"
REVIEW_FOLDER = "_Review"

# Sections of the check window, in order.
GROUPS = [
    ("duplicate", "Duplicates"),
    ("broken", "Broken links to files"),
    ("picture", "Missing pictures"),
    ("naming", "Names and folders"),
    ("details", "Part numbers and store links"),
    ("price", "Prices"),
    ("tips", "Tips"),
]
_GROUP_OF = {"duplicate": "duplicate", "temp_id": "broken", "missing": "broken", "no_picture": "picture",
             "name": "naming", "folder": "naming", "part_number": "details", "wrong_link": "details",
             "no_link": "details", "no_price": "price", "bad_price": "price", "old_price": "price",
             "category": "tips"}

# Stores each vendor sells from (anything else is flagged as the wrong link).
VENDOR_DOMAINS: Dict[str, List[str]] = {
    "wcp": ["wcproducts.com"],
    "rev": ["revrobotics.com"],
    "andymark": ["andymark.com"],
    "sds": ["swervedrivespecialties.com", "andymark.com"],
    "ttb": ["thethriftybot.com"],
}


@dataclass
class Problem:
    kind: str
    level: str
    file_id: str
    title: str                       # the part, as students know it
    message: str                     # one sentence: what's wrong
    fix: str = ""                    # action name for the Fix button ("" = no button)
    fix_label: str = ""
    other_id: str = ""               # duplicates: the file we keep
    suggest: Dict[str, str] = field(default_factory=dict)   # e.g. {"name": "...", "url": "..."}

    @property
    def key(self) -> str:
        """Stable id - used to remember 'ignore this one'."""
        return f"{self.kind}:{self.file_id}"

    @property
    def group(self) -> str:
        return _GROUP_OF.get(self.kind, "tips")

    def to_json(self) -> dict:
        d = asdict(self)
        d.update(key=self.key, group=self.group)
        return d


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def store_domains(vendor: str, vendors: Sequence[cc.Vendor] = cc.DEFAULT_VENDORS) -> List[str]:
    """Hosts a vendor's store links may be on (from the table above, else the vendor's search link)."""
    known = VENDOR_DOMAINS.get((vendor or "").strip().lower())
    if known:
        return known
    v = cc.vendor_by_name(vendor, vendors)
    host = urlparse(v.link).hostname if v and v.link else ""
    return [host[4:] if host.startswith("www.") else host] if host else []


def link_ok(url: str, vendor: str, vendors: Sequence[cc.Vendor] = cc.DEFAULT_VENDORS) -> bool:
    """True when the link is a web address on the vendor's own store (unknown vendors: any web address)."""
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    domains = store_domains(vendor, vendors)
    host = parsed.hostname.lower()
    return not domains or any(host == d or host.endswith("." + d) for d in domains)


def suggested_link(info: cc.CotsInfo, vendors: Sequence[cc.Vendor] = cc.DEFAULT_VENDORS) -> str:
    """The vendor's search page for this part number (good enough to find the product in one click)."""
    v = cc.vendor_by_name(info.vendor, vendors)
    if v and v.link and info.vendor_pn.strip():
        return v.link.replace("{pn}", info.vendor_pn.strip())
    return ""


def completeness(item: cc.CatalogItem) -> int:
    """How much we know about a part - when two files are the same part, keep the fuller one."""
    i = item.info
    score = sum(bool(x) for x in (i.vendor_pn, i.price, i.url, i.notes, item.thumb))
    score += 2 if item.file_id.startswith("urn:") else 0
    score += 1 if item.file_name == cc.part_file_name(i.vendor_pn, i.name) else 0
    return score


def _age_days(added_on: str, today: _dt.date) -> Optional[int]:
    try:
        return (today - _dt.date.fromisoformat((added_on or "").strip()[:10])).days
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------
def check(items: Sequence[cc.CatalogItem],
          vendors: Sequence[cc.Vendor] = cc.DEFAULT_VENDORS,
          categories: Sequence[str] = cc.DEFAULT_CATEGORIES,
          no_thumbnail: Iterable[str] = (),
          missing: Iterable[str] = (),
          ignored: Iterable[str] = (),
          today: Optional[_dt.date] = None) -> List[Problem]:
    """
    Every problem in the library. no_thumbnail = ids Fusion said have no picture;
    missing = ids the full check couldn't find in the cloud; ignored = Problem.keys
    someone pressed Ignore on.
    """
    today = today or _dt.date.today()
    no_thumbnail, missing, ignored = set(no_thumbnail), set(missing), set(ignored)
    cats = {c.lower() for c in categories}
    out: List[Problem] = []

    # --- duplicates: keep the more complete file, move the other one
    moved = set()
    for a, b in cc.find_duplicates(list(items), vendors):
        keep, extra = (a, b) if completeness(a) >= completeness(b) else (b, a)
        if extra.file_id in moved:
            continue
        moved.add(extra.file_id)
        same_pn = a.info.vendor_pn and a.info.vendor_pn.lower() == b.info.vendor_pn.lower()
        why = "has the same part number as" if same_pn else "looks like the same part as"
        out.append(Problem("duplicate", FIX, extra.file_id, extra.title,
                           f"{why.capitalize()} '{keep.file_name}' ({keep.category}/{keep.vendor}).",
                           "review", f"Move to {REVIEW_FOLDER}", other_id=keep.file_id))

    for item in items:
        info, title = item.info, item.title

        # --- broken ids
        if item.file_id in missing:
            out.append(Problem("missing", FIX, item.file_id, title,
                               "Fusion can't find this file anymore - it was probably deleted or moved.",
                               "rescan", "Read the library again"))
            continue
        if not item.file_id.startswith("urn:"):
            out.append(Problem("temp_id", FIX, item.file_id, title,
                               "The panel only has a temporary id from when this part was uploading, "
                               "so inserting it can fail with 'invalid id'.", "relink", "Look it up again"))

        # --- picture
        if item.file_id in no_thumbnail:
            out.append(Problem("no_picture", FIX, item.file_id, title,
                               "Fusion never made a picture for this part, so its tile is blank.",
                               "resave", "Make a picture"))

        # --- names and folders
        expected = cc.part_file_name(info.vendor_pn, info.name) if info.vendor_pn and info.name else ""
        if expected and item.file_name != expected:
            out.append(Problem("name", FIX, item.file_id, title,
                               f"The file is called '{item.file_name}'. Library files are named "
                               f"'<part #> <name>', so it should be '{expected}'.",
                               "rename", "Rename it", suggest={"name": expected}))
        folder_vendor = item.vendor
        if (info.vendor and folder_vendor and info.vendor.lower() != folder_vendor.lower()) or \
                (info.category and item.category and info.category.lower() != item.category.lower()):
            out.append(Problem("folder", FIX, item.file_id, title,
                               f"It's saved in {item.category}/{folder_vendor}, but its details say "
                               f"{info.category}/{info.vendor}.", "move",
                               f"Move to {info.category}/{info.vendor}",
                               suggest={"category": info.category, "vendor": info.vendor}))
        if item.category and item.category.lower() not in cats and item.category != "Uncategorized":
            out.append(Problem("category", TIP, item.file_id, title,
                               f"'{item.category}' isn't one of the team's categories, so it won't line up "
                               "with the category menu. Add it in Settings, or move the part.", ""))

        # --- part number
        v = cc.vendor_by_name(info.vendor, vendors)
        pn = info.vendor_pn.strip()
        if not pn:
            out.append(Problem("part_number", FIX, item.file_id, title,
                               "It has no part number, so the BOM can't say what to order.",
                               "details", "Add part #"))
        elif v and v.pattern and not re.match(v.pattern, pn):
            out.append(Problem("part_number", FIX, item.file_id, title,
                               f"'{pn}' doesn't look like a {v.name} part number (like {v.example}).",
                               "details", "Fix part #"))

        # --- link
        link = suggested_link(info, vendors)
        if not info.url.strip():
            out.append(Problem("no_link", INFO, item.file_id, title, "It has no store link.",
                               "details", "Add link", suggest={"url": link} if link else {}))
        elif not link_ok(info.url, info.vendor, vendors):
            out.append(Problem("wrong_link", FIX, item.file_id, title,
                               f"The store link isn't on {info.vendor or 'the vendor'}'s website: {info.url}",
                               "details", "Fix link", suggest={"url": link} if link else {}))

        # --- price
        if not info.price.strip():
            out.append(Problem("no_price", INFO, item.file_id, title,
                               "It has no price, so the BOM total leaves it out.", "details", "Add price"))
        elif info.price_value() is None or info.price_value() <= 0:
            out.append(Problem("bad_price", FIX, item.file_id, title,
                               f"The price '{info.price}' isn't a dollar amount.", "details", "Fix price"))
        else:
            age = _age_days(info.added_on, today)
            if age is not None and age > 365:
                out.append(Problem("old_price", TIP, item.file_id, title,
                                   f"The price was entered {age // 30} months ago - it may have changed.",
                                   "details", "Update price"))

    return [p for p in out if p.key not in ignored]


def summary(problems: Sequence[Problem]) -> Dict[str, int]:
    """{'fix': 3, 'info': 101, 'tip': 0, 'no_price': 101} - for the panel's badge."""
    s = {FIX: 0, INFO: 0, TIP: 0}
    for p in problems:
        s[p.level] = s.get(p.level, 0) + 1
        s[p.kind] = s.get(p.kind, 0) + 1
    return s


def badge_text(s: Dict[str, int]) -> str:
    """'3 to fix' / '101 missing prices' / '' (nothing to show)."""
    if s.get(FIX):
        return f"{s[FIX]} to fix"
    if s.get("no_price"):
        return f"{s['no_price']} missing price{'s' if s['no_price'] != 1 else ''}"
    if s.get(INFO):
        return f"{s[INFO]} missing detail{'s' if s[INFO] != 1 else ''}"
    return ""


def apply_details(info: cc.CotsInfo, changes: Dict[str, str]) -> cc.CotsInfo:
    """A copy of info with the fields a student typed in the check window (price, url, vendor_pn)."""
    new = cc.CotsInfo(**{k: getattr(info, k) for k in info.__dataclass_fields__})
    for key in ("price", "url", "vendor_pn", "notes"):
        if key in changes and changes[key] is not None:
            value = str(changes[key]).strip()
            if key == "price":
                value = value.replace("$", "").replace(",", "").strip()
            setattr(new, key, value)
    if "price" in changes:
        new.added_on = _dt.date.today().isoformat()     # the price is as of today
    return new


def check_details(info: cc.CotsInfo, vendors: Sequence[cc.Vendor] = cc.DEFAULT_VENDORS) -> List[str]:
    """Problems with what was typed (shown next to the boxes; nothing is saved while there are any)."""
    errs = []
    if info.price and (info.price_value() is None or info.price_value() <= 0):
        errs.append("Type the price as a number, like 12.99.")
    if info.url and not link_ok(info.url, info.vendor, vendors):
        errs.append(f"The link should be a page on {info.vendor}'s website (starting with https://).")
    v = cc.vendor_by_name(info.vendor, vendors)
    if info.vendor_pn and v and v.pattern and not re.match(v.pattern, info.vendor_pn):
        errs.append(f"{v.name} part numbers look like {v.example}.")
    if not info.vendor_pn:
        errs.append("The part number can't be empty.")
    return errs


# ---------------------------------------------------------------------------
# Vendor revisions
# ---------------------------------------------------------------------------
def revision_note(info: cc.CotsInfo, step_name: str, today: Optional[_dt.date] = None) -> str:
    """What goes in the new version's notes: 'Updated from WCP-0712.step on 2026-11-22'."""
    today = today or _dt.date.today()
    note = f"Updated from {step_name} on {today.isoformat()}"
    old = re.sub(r"\s*\|?\s*Updated from .*? on \d{4}-\d{2}-\d{2}", "", info.notes or "").strip(" |")
    return f"{old} | {note}" if old else note
