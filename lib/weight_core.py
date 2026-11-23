"""
weight_core.py - the Robot Weight panel's math (no Fusion imports; tested in
tests/test_weight_core.py).

Built from the same BOM rows Export BOM writes, so the panel and the spreadsheet
always agree. FRC weighs the robot WITHOUT bumpers and battery (2026: <= 115 lb,
R103) and robot + bumpers separately (2026: <= 135 lb, R408) - the limits are
team settings ("weight_limits") because each season's game manual can change them.

    report(bom, ...) -> WeightReport
        robot_lb           everything except bumpers and the battery
        bumpers_lb / battery_lb
        by_subsystem       [(name, lb)] heaviest first
        heaviest           the parts that weigh the most in total (qty x each)
        no_material        made parts still on Fusion's default material (weight is a guess)
        unmeasured         parts Fusion hasn't weighed yet (time budget)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import bom_core as bc

DEFAULT_LIMITS = {"robot_lb": 115.0, "robot_with_bumpers_lb": 135.0, "warn_at_percent": 95.0}
DEFAULT_EXCLUDE = ["bumper", "battery"]
DEFAULT_MATERIALS = ["Steel"]          # what Fusion gives a body nobody chose a material for
KG_TO_LB = 2.2046226218
OK, CLOSE, OVER = "ok", "close", "over"


@dataclass
class PartWeight:
    key: str
    name: str
    part_number: str
    qty: int
    each_lb: float
    total_lb: float
    material: str = ""
    subsystem: str = ""


@dataclass
class WeightReport:
    robot_lb: float = 0.0
    bumpers_lb: float = 0.0
    battery_lb: float = 0.0
    limit_lb: float = DEFAULT_LIMITS["robot_lb"]
    limit_with_bumpers_lb: float = DEFAULT_LIMITS["robot_with_bumpers_lb"]
    warn_at_percent: float = DEFAULT_LIMITS["warn_at_percent"]
    by_subsystem: List[Tuple[str, float]] = field(default_factory=list)
    heaviest: List[PartWeight] = field(default_factory=list)
    no_material: List[PartWeight] = field(default_factory=list)
    measured: int = 0
    unmeasured: List[str] = field(default_factory=list)

    @property
    def with_bumpers_lb(self) -> float:
        return self.robot_lb + self.bumpers_lb

    @property
    def left_lb(self) -> float:
        return self.limit_lb - self.robot_lb

    @property
    def status(self) -> str:
        return status_of(self.robot_lb, self.limit_lb, self.warn_at_percent)

    @property
    def bumper_status(self) -> str:
        return status_of(self.with_bumpers_lb, self.limit_with_bumpers_lb, self.warn_at_percent)

    def headline(self) -> str:
        """'98.4 of 115 lb - 16.6 lb to spare' (the panel's big line)."""
        if self.left_lb >= 0:
            return f"{self.robot_lb:.1f} of {self.limit_lb:g} lb - {self.left_lb:.1f} lb to spare"
        return f"{self.robot_lb:.1f} of {self.limit_lb:g} lb - {-self.left_lb:.1f} lb OVER"

    def to_json(self) -> dict:
        part = lambda p: {"key": p.key, "name": p.name, "pn": p.part_number, "qty": p.qty,   # noqa: E731
                          "each": round(p.each_lb, 3), "total": round(p.total_lb, 2), "material": p.material,
                          "subsystem": p.subsystem}
        return {"robot": round(self.robot_lb, 2), "bumpers": round(self.bumpers_lb, 2),
                "battery": round(self.battery_lb, 2), "withBumpers": round(self.with_bumpers_lb, 2),
                "limit": self.limit_lb, "limitWithBumpers": self.limit_with_bumpers_lb,
                "warnAt": self.warn_at_percent, "status": self.status, "bumperStatus": self.bumper_status,
                "headline": self.headline(), "bySubsystem": [[n, round(w, 2)] for n, w in self.by_subsystem],
                "heaviest": [part(p) for p in self.heaviest], "noMaterial": [part(p) for p in self.no_material],
                "measured": self.measured, "unmeasured": self.unmeasured[:50], "unmeasuredCount": len(self.unmeasured)}


def status_of(weight: float, limit: float, warn_at_percent: float) -> str:
    if limit <= 0:
        return OK
    if weight > limit + 1e-9:
        return OVER
    return CLOSE if weight >= limit * warn_at_percent / 100.0 else OK


def read_limits(raw: Optional[dict]) -> Dict[str, float]:
    """Team setting 'weight_limits' -> numbers (bad values fall back to the defaults, never crash)."""
    out = dict(DEFAULT_LIMITS)
    for key, value in (raw or {}).items():
        if key in out:
            try:
                number = float(str(value).replace("lb", "").strip())
                if number > 0:
                    out[key] = number
            except ValueError:
                pass
    return out


def _excluded(row: bc.BomRow, words: Sequence[str]) -> str:
    """'bumper' / 'battery' / '' - from the part's name or the assemblies it's in."""
    text = f"{row.name} {row.description} {row.used_in}".lower()
    for w in words:
        if re.search(r"\b" + re.escape(w.lower()), text):
            return w.lower()
    return ""


def report(bom: bc.Bom, limits: Optional[dict] = None, exclude_words: Sequence[str] = DEFAULT_EXCLUDE,
           default_materials: Sequence[str] = DEFAULT_MATERIALS, subsystem_names: Optional[Dict[str, str]] = None,
           ignored_materials: Iterable[str] = (), top: int = 10) -> WeightReport:
    """The whole panel from the flat BOM (parts only - assemblies would double count)."""
    lim = read_limits(limits)
    rep = WeightReport(limit_lb=lim["robot_lb"], limit_with_bumpers_lb=lim["robot_with_bumpers_lb"],
                       warn_at_percent=lim["warn_at_percent"])
    names = subsystem_names or {}
    defaults = {m.strip().lower() for m in default_materials if m.strip()}
    ignored = set(ignored_materials)
    subs: Dict[str, float] = {}
    parts: List[PartWeight] = []
    for r in bom.flat:
        if r.type == bc.TYPE_ASSEMBLY or r.qty <= 0:
            continue
        if r.mass_lb is None:
            rep.unmeasured.append(r.name)
            continue
        rep.measured += 1
        total = r.mass_lb * r.qty
        sub = names.get(r.subsystem, r.subsystem) or "Other"
        pw = PartWeight(r.key, r.name, r.part_number, r.qty, r.mass_lb, total, r.material, sub)
        kind = _excluded(r, exclude_words)
        if kind == "battery":
            rep.battery_lb += total
            continue
        if kind:                                         # bumpers (or another word the team added)
            rep.bumpers_lb += total
            continue
        rep.robot_lb += total
        subs[sub] = subs.get(sub, 0.0) + total
        parts.append(pw)
        if r.type == bc.TYPE_MADE and r.material.strip().lower() in defaults | {""} and r.key not in ignored:
            rep.no_material.append(pw)
    rep.by_subsystem = sorted(subs.items(), key=lambda kv: -kv[1])
    rep.heaviest = sorted(parts, key=lambda p: -p.total_lb)[:top]
    rep.no_material.sort(key=lambda p: -p.total_lb)
    return rep
