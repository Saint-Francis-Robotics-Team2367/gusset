"""
cots_family.py - groups library parts into families and reads tags out of their
names, for the COTS Library panel (no Fusion imports; tested in
tests/test_cots_family.py).

FAMILIES - parts whose names differ only by tooth count and/or width:
    '18t Aluminum Spur Gear (20 DP, 1/2" Hex Bore)'
    '84t Aluminum Spur Gear (20 DP, 1/2" Hex Bore)'           -> one tile, "pick 18t ... 84t"
    '15t x 9mm Wide Aluminum Pulley (HTD 5mm, 1/2" Hex Bore)'
    '36t x 15mm Wide Aluminum Pulley (HTD 5mm, 1/2" Hex Bore)' -> one tile, teeth + width
  A family needs the same vendor and category and at least two sizes; everything
  else stays its own tile. Pocketed / MotionX / steel / aluminum / bore are part of
  the family name, so those never mix.

TAGS - for the filter menus: bore, pitch, width, material (+ style).
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Tuple

_TEETH = re.compile(r"\b(\d{1,3})\s*(?:t|tooth|teeth)\b", re.I)
_WIDTH = re.compile(r"\b(\d{1,2}(?:\.\d)?)\s*mm\s+wide\b", re.I)


def variant_of(name: str) -> Tuple[str, Dict[str, float]]:
    """
    ('Aluminum Pulley (HTD 5mm, 1/2" Hex Bore)', {'teeth': 15, 'width_mm': 9})
    from '15t x 9mm Wide Aluminum Pulley (HTD 5mm, 1/2" Hex Bore)'.
    No tooth count -> (name, {}) - it isn't a sized part.
    """
    text = name or ""
    variant: Dict[str, float] = {}
    m = _TEETH.search(text)
    if not m:
        return text.strip(), {}
    variant["teeth"] = int(m.group(1))
    text = text[:m.start()] + text[m.end():]
    w = _WIDTH.search(text)
    if w:
        width = float(w.group(1))
        variant["width_mm"] = int(width) if width.is_integer() else width
        text = text[:w.start()] + text[w.end():]
    text = re.sub(r"^\s*(?:x|-|,)\s+", "", text.strip())          # '15t x 9mm Wide ...' leaves 'x'
    text = re.sub(r"\(\s*,\s*", "(", text)
    text = re.sub(r"\s*,\s*\)", ")", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" -,")
    return text, variant


def family_key(vendor: str, category: str, family_name: str) -> str:
    return "|".join([vendor.lower(), category.lower(), re.sub(r"\W+", " ", family_name.lower()).strip()])


def variant_label(variant: Dict[str, float]) -> str:
    parts = []
    if "teeth" in variant:
        parts.append(f"{variant['teeth']}t")
    if "width_mm" in variant:
        parts.append(f"{variant['width_mm']}mm")
    return " x ".join(parts)


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------
_HALF = r'(?:1/2\s*(?:"|in\b|in\.|inch)|1-2\s*in\b|0\.5\s*(?:"|in\b|in\.))'
_BORES: List[Tuple[str, str]] = [
    (_HALF + r"\s*rounded\s*hex|thunderhex", '1/2" rounded hex'),
    (_HALF + r"\s*hex", '1/2" hex'),
    (r'3/8\s*(?:"|in\b)\s*hex|3-8\s*in\s*hex', '3/8" hex'),
    (r"splinexs", "SplineXS (Kraken)"),
    (r"splinexl", "SplineXL"),
    (r"falcon", "Falcon spline"),
    (r"8\s*mm\s*key", "8mm keyed"),
    (r'1\.125\s*(?:"|in\b|in\.)\s*(?:bearing|od)', '1.125" bearing'),
    (r"\b8\s*mm\s*(?:shaft|bore)\b", "8mm round"),
]
_PITCHES: List[Tuple[str, str]] = [
    (r"\b20\s*dp\b", "20 DP"),
    (r"\b32\s*dp\b", "32 DP"),
    (r"htd\s*5\s*mm|5\s*mm\s*htd", "HTD 5mm"),
    (r"gt2\b", "GT2"),
    (r"#\s*25\b", "#25 chain"),
    (r"#\s*35\b", "#35 chain"),
]
_MATERIALS: List[Tuple[str, str]] = [
    (r"\baluminum\b|\baluminium\b", "Aluminum"),
    (r"\bsteel\b", "Steel"),
    (r"\bplastic\b|\bnylon\b|\bdelrin\b|\bpolycarbonate\b", "Plastic"),
]
_STYLES: List[Tuple[str, str]] = [(r"motionx", "MotionX"), (r"\bpocketed\b", "Pocketed")]


def _first(text: str, rules: Sequence[Tuple[str, str]]) -> str:
    for pattern, label in rules:
        if re.search(pattern, text, re.I):
            return label
    return ""


def tags_for(name: str, notes: str = "", category: str = "") -> Dict[str, str]:
    """{'bore': '1/2" hex', 'pitch': '20 DP', 'width': '9mm', 'material': 'Aluminum', 'style': ''} - '' = unknown."""
    text = f"{name} {notes}"
    _, variant = variant_of(name)
    return {
        "bore": _first(text, _BORES),
        "pitch": _first(text, _PITCHES),
        "width": f"{variant['width_mm']}mm" if "width_mm" in variant else "",
        "material": _first(text, _MATERIALS),
        "style": _first(text, _STYLES),
    }


TAG_LABELS = {"bore": "Bore", "pitch": "Pitch", "width": "Width", "material": "Material", "style": "Style"}


def describe(title: str, vendor: str, category: str, notes: str = "") -> dict:
    """Everything the panel needs per part: family key + name, its size, and tags."""
    fam_name, variant = variant_of(title)
    return {"family": family_key(vendor, category, fam_name) if variant else "",
            "family_name": fam_name if variant else "",
            "variant": variant, "variant_label": variant_label(variant),
            "tags": tags_for(title, notes, category)}


def build_families(parts: Sequence[dict]) -> Dict[str, List[dict]]:
    """
    {family key: [parts, smallest first]} for keys shared by 2+ parts. Each part is
    a dict with at least 'family' and 'variant' (what describe() returns, merged in).
    The panel does the same grouping in JavaScript; this is the tested reference.
    """
    groups: Dict[str, List[dict]] = {}
    for p in parts:
        if p.get("family"):
            groups.setdefault(p["family"], []).append(p)
    return {k: sorted(v, key=lambda p: (p["variant"].get("teeth", 0), p["variant"].get("width_mm", 0)))
            for k, v in groups.items() if len(v) >= 2}


# ---------------------------------------------------------------------------
# Usage (recently / most used)
# ---------------------------------------------------------------------------
def record_use(usage: Dict[str, list], file_id: str, now: float, keep: int = 300) -> Dict[str, list]:
    """usage = {file_id: [times used, last used]} - returns a trimmed copy with this insert counted."""
    out = {k: list(v) for k, v in (usage or {}).items() if isinstance(v, (list, tuple)) and len(v) == 2}
    count, _ = out.get(file_id, [0, 0])
    out[file_id] = [int(count) + 1, float(now)]
    if len(out) > keep:                                   # forget the least recently used
        out = dict(sorted(out.items(), key=lambda kv: kv[1][1], reverse=True)[:keep])
    return out


def recent(usage: Dict[str, list], n: int = 8) -> List[str]:
    return [k for k, _ in sorted(usage.items(), key=lambda kv: kv[1][1], reverse=True)[:n]]


def most_used(usage: Dict[str, list], n: int = 12) -> List[str]:
    return [k for k, _ in sorted(usage.items(), key=lambda kv: (kv[1][0], kv[1][1]), reverse=True)[:n]]


def family_range(members: Sequence[dict]) -> str:
    """'18-84t, 2 widths' for a family tile's subtitle."""
    teeth = sorted({m["variant"].get("teeth") for m in members if m["variant"].get("teeth")})
    widths = sorted({m["variant"].get("width_mm") for m in members if m["variant"].get("width_mm")})
    text = f"{teeth[0]}-{teeth[-1]}t" if len(teeth) > 1 else (f"{teeth[0]}t" if teeth else "")
    if len(widths) > 1:
        text += f", {len(widths)} widths"
    return text


def pick_default(members: Sequence[dict], usage: Optional[Dict[str, list]] = None) -> str:
    """The size a family tile shows first: the one used most, else the smallest."""
    usage = usage or {}
    used = [m for m in members if m["file_id"] in usage]
    if used:
        return max(used, key=lambda m: usage[m["file_id"]][0])["file_id"]
    return members[0]["file_id"]
