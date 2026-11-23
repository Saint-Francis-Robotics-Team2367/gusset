"""
cots_match.py - finds the right FRC_COTS library part for other Gusset tools
(no Fusion imports; tested in tests/test_cots_match.py).

    pulley_for(items, 36, "HTD 5mm belt", width="9mm", bore='1/2" hex')
        -> Match(best item, other choices, why) - Belt & Chain places it
    shaft_bearings(items)        -> hex-bore bearings for Shaft & Spacer's dropdown
    hand_modeled(components, items) -> parts that look like COTS but weren't
                                       inserted from the library (Design Review)

Everything reads the names/tags the COTS panel already has (cots_family).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence, Tuple

from . import cots_core as cc
from . import cots_family as cf

# Belt & Chain's drive names -> the pitch tag on library parts, and where to look.
DRIVE_PITCH = {"HTD 5mm belt": ("HTD 5mm", "Pulleys"), "#25 chain": ("#25 chain", "Sprockets"),
               "#35 chain": ("#35 chain", "Sprockets")}
HEX_BORES = ('1/2" hex', '1/2" rounded hex')
ANY = "Any"


@dataclass
class Match:
    best: Optional[cc.CatalogItem]
    others: List[cc.CatalogItem] = field(default_factory=list)
    why: str = ""                     # one line for the dialog ("Using WCP-0703 ..." / "No 13t pulley ...")


def _tags(item: cc.CatalogItem) -> dict:
    return cf.tags_for(item.title, item.info.notes)


def _teeth(item: cc.CatalogItem) -> Optional[int]:
    return cf.variant_of(item.title)[1].get("teeth")


def drive_parts(items: Sequence[cc.CatalogItem], drive: str) -> List[cc.CatalogItem]:
    """Every library pulley (or sprocket) for this belt/chain."""
    pitch, category = DRIVE_PITCH.get(drive, ("", ""))
    return [i for i in items if pitch and _tags(i)["pitch"] == pitch and
            (i.category.lower() == category.lower() or category == "Pulleys" and i.category.lower() == "pulleys")]


def drive_choices(items: Sequence[cc.CatalogItem], drive: str) -> Tuple[List[str], List[str]]:
    """(widths, bores) the library has for this drive - for the dialog's dropdowns ('Any' first)."""
    parts = drive_parts(items, drive)
    widths = sorted({_tags(i)["width"] for i in parts if _tags(i)["width"]}, key=lambda w: float(w[:-2]))
    bores = sorted({_tags(i)["bore"] for i in parts if _tags(i)["bore"]},
                   key=lambda b: (b not in HEX_BORES, HEX_BORES.index(b) if b in HEX_BORES else 0, b))
    return [ANY] + widths, [ANY] + bores


def pulley_for(items: Sequence[cc.CatalogItem], teeth: int, drive: str, width: str = ANY, bore: str = ANY,
               usage: Optional[dict] = None) -> Match:
    """
    The library pulley/sprocket with this many teeth. Width and bore narrow it down;
    when several still fit, 1/2" hex bore, then the one used most, then the narrowest.
    """
    usage = usage or {}
    pitch, category = DRIVE_PITCH.get(drive, ("", ""))
    kind = "sprocket" if category == "Sprockets" else "pulley"
    same = [i for i in drive_parts(items, drive) if _teeth(i) == teeth]
    if not same:
        have = sorted({t for t in (_teeth(i) for i in drive_parts(items, drive)) if t})
        hint = f" The library has {', '.join(f'{t}t' for t in have)}." if have else \
            f" The library has no {pitch} {kind}s yet - add one with + Add."
        return Match(None, [], f"No {teeth}t {pitch} {kind} in the library.{hint}")
    fits = [i for i in same if (width == ANY or _tags(i)["width"] == width) and (bore == ANY or _tags(i)["bore"] == bore)]
    if not fits:
        options = "; ".join(sorted({f"{_tags(i)['width'] or '?'} {_tags(i)['bore'] or ''}".strip() for i in same}))
        return Match(None, same, f"No {teeth}t {kind} with that width/bore - the library has: {options}.")

    def rank(i: cc.CatalogItem):
        t = _tags(i)
        width_mm = float(t["width"][:-2]) if t["width"] else 99.0
        return (t["bore"] not in HEX_BORES, -int((usage.get(i.file_id) or [0])[0]), width_mm, i.title)

    fits.sort(key=rank)
    best = fits[0]
    return Match(best, fits[1:], f"{teeth}t: {best.info.vendor_pn or best.vendor} {best.title}")


_HALF_INCH_ID = re.compile(r'(?i)\b(1/2|0?\.5)\s*(in\.?|")\s*(hex\s*)?(id|bore)\b|\bR8(ZZ|-2RS)?\b')


def bearing_bore(item: cc.CatalogItem) -> str:
    """'hex' (goes on the 1/2\" hex), 'round' (a 1/2\" round bore - for turned-round shaft ends) or ''."""
    if _tags(item)["bore"] in HEX_BORES:
        return "hex"
    return "round" if _HALF_INCH_ID.search(item.title) else ""


def shaft_bearings(items: Sequence[cc.CatalogItem]) -> List[cc.CatalogItem]:
    """Library bearings for a 1/2\" shaft: hex-bore first (flanged first), then round-bore ones."""
    found = [i for i in items if i.category.lower() == "bearings" and bearing_bore(i)]
    return sorted(found, key=lambda i: (bearing_bore(i) != "hex", "flange" not in i.title.lower(), i.title))


def bearing_label(item: cc.CatalogItem) -> str:
    kind = {"hex": "hex bore", "round": "round bore"}.get(bearing_bore(item), "")
    return f"{item.info.vendor_pn} {item.title}".strip()[:80] + (f" [{kind}]" if kind else "")


# ---------------------------------------------------------------------------
# Design Review: COTS parts modeled by hand
# ---------------------------------------------------------------------------
# Words that say "this is something you buy" when a part isn't from the library.
# 'bearing block', 'pulley guard', 'encoder mount'... are parts teams make, so those don't count.
_MADE_AFTER = r"(?!\s*(?:block|plate|mount|holder|retainer|cap|support|spacer|guard|cover|bracket|tensioner)s?\b)"
COTS_WORDS = re.compile(r"(?i)\b(neo|kraken|falcon|vortex|spark\s*max|spark\s*flex|talon\s*fx|cancoder|pigeon|"
                        r"bearings?|pulleys?|sprockets?|gearbox|maxplanetary|ultraplanetary|versaplanetary|"
                        r"swerve\s*module|encoder|roborio)\b" + _MADE_AFTER)
_TEAM_PN = re.compile(r"^\d{2}-[A-Z]{2,5}-\d{3}\b")          # '26-DRV-012 ...' = a team-made part
_PN = re.compile(r"(?i)\b(WCP-\d{4}|REV-\d{2}-\d{4}|am-\d{4}[a-z]?|TTB-\w+)\b")


@dataclass
class HandModeled:
    name: str                        # the component as students named it
    reason: str
    library: Optional[cc.CatalogItem] = None    # the part to use instead, when we can tell

    def line(self) -> str:
        use = (f" - use '{self.library.file_name}' from the COTS Library" if self.library
               else " - insert it from the COTS Library (or add it with + Add)")
        return f"{self.name}: {self.reason}{use}"


def hand_modeled(components: Iterable[Tuple[str, bool]], items: Sequence[cc.CatalogItem],
                 vendors: Sequence[cc.Vendor] = cc.DEFAULT_VENDORS) -> List[HandModeled]:
    """
    components = (name, came_from_library) for every distinct component in the
    assembly. A part NOT from the library is flagged when its name has a vendor part
    number, matches a library part, or names something teams buy (NEO, bearing...).
    """
    by_pn = {i.info.vendor_pn.lower(): i for i in items if i.info.vendor_pn}
    out: List[HandModeled] = []
    seen = set()
    for name, from_library in components:
        clean = re.sub(r"\s*\(\d+\)$|:\d+$", "", name or "").strip()
        if from_library or not clean or clean.lower() in seen or _TEAM_PN.match(clean):
            continue
        seen.add(clean.lower())
        pn = _PN.search(clean)
        if pn:
            lib = by_pn.get(pn.group(1).lower())
            out.append(HandModeled(clean, f"has the vendor part # {pn.group(1)} but isn't the library part", lib))
            continue
        lib = next((i for i in items if cc.same_part(clean, i.title, vendors)), None)
        if lib is not None:
            out.append(HandModeled(clean, "looks like a part that's in the library", lib))
        elif COTS_WORDS.search(clean):
            out.append(HandModeled(clean, f"sounds like a bought part ('{COTS_WORDS.search(clean).group(1)}')"))
    return out
