"""
cots_core.py - the plain-Python side of Gusset's COTS library (no Fusion imports;
tested in tests/test_cots_core.py).

THE LIBRARY (compatible with FRC Team 5000's FRC-COTS add-in)
    Fusion project  FRC_COTS
        Motors/                  <- top folder = category (what Team 5000's tool shows)
            REV/                 <- second folder = vendor (Gusset adds this level)
                REV-21-1650 NEO Brushless Motor V1.1      <- "<vendor part #> <name>"
        Bearings/
            WCP/ ...

Each part file's DESCRIPTION (visible in the Data Panel, readable without
opening the file) holds its details in a simple format:

    Gusset COTS
    Name: NEO Brushless Motor V1.1
    Vendor: REV
    Part #: REV-21-1650
    Category: Motors
    Price: 48.00
    Link: https://www.revrobotics.com/rev-21-1650/
    Added by: [student] on 2026-11-20

The same details are written INSIDE the part file as Gusset attributes
(cots=true, cots_vendor, cots_pn, cots_price, cots_url), so Name Parts never
renumbers library parts and Export BOM fills Vendor / Vendor Part # / Link /
Unit Price automatically.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

LIBRARY_PROJECT = "FRC_COTS"
DESCRIPTION_HEADER = "Gusset COTS"

DEFAULT_CATEGORIES = ["Motors", "Bearings", "Gears", "Wheels", "Electronics", "Bearing Blocks", "Pulleys",
                      "Sprockets", "Planetary Gearboxes", "Sensors", "Swerve Modules"]


@dataclass(frozen=True)
class Vendor:
    name: str                       # also the vendor folder name
    pattern: str = ""               # regex a correct part number matches ("" = anything goes)
    example: str = ""
    link: str = ""                  # search link with {pn}
    hint: str = ""


DEFAULT_VENDORS: List[Vendor] = [
    Vendor("WCP", r"^WCP-\d{4}$", "WCP-0123", "https://wcproducts.com/search?q={pn}"),
    Vendor("REV", r"^REV-\d{2}-\d{4}$", "REV-21-1650", "https://www.revrobotics.com/search.php?search_query={pn}"),
    Vendor("AndyMark", r"^am-\d{4}[a-z]?(_[A-Za-z0-9]+)?$", "am-4255", "https://www.andymark.com/search?q={pn}"),
    Vendor("SDS", "", "am-5248", "https://www.andymark.com/search?q={pn}",
           "SDS parts sold by AndyMark use AndyMark numbers (am-####) - use the number on the store page."),
    Vendor("TTB", r"^TTB-[A-Za-z0-9][A-Za-z0-9.\-]*$", "TTB-0060", "https://www.thethriftybot.com/search?q={pn}",
           "Most are TTB-#### ; kits can be longer, e.g. TTB-S-02-v1.1."),
]

# Characters Fusion (and the operating systems it syncs to) don't allow in file names.
_BAD = re.compile(r'[\\/:*?"<>|]')


def vendor_by_name(name: str, vendors: Sequence[Vendor] = DEFAULT_VENDORS) -> Optional[Vendor]:
    for v in vendors:
        if v.name.lower() == (name or "").strip().lower():
            return v
    return None


def safe_name(text: str) -> str:
    """Inch marks become 'in'; characters Fusion won't take become '-'."""
    text = (text or "").replace('"', "in")
    text = _BAD.sub("-", text)
    return re.sub(r"\s+", " ", text).strip()


def part_file_name(vendor_pn: str, name: str) -> str:
    """'REV-21-1650 NEO Brushless Motor V1.1' - part number first, so it sorts and is easy to search."""
    pn, nm = safe_name(vendor_pn), safe_name(name)
    if pn and nm.lower().startswith(pn.lower()):
        return nm
    return f"{pn} {nm}".strip()


# ---------------------------------------------------------------------------
# Part details
# ---------------------------------------------------------------------------
@dataclass
class CotsInfo:
    name: str = ""
    vendor: str = ""
    vendor_pn: str = ""
    category: str = ""
    price: str = ""                 # dollars, as typed ("48.00"); "" = unknown
    url: str = ""
    notes: str = ""
    added_by: str = ""
    added_on: str = ""
    different_part: bool = field(default=False, compare=False)   # a mentor said: not a duplicate of a look-alike

    def price_value(self) -> Optional[float]:
        try:
            return float(self.price.replace("$", "").replace(",", "").strip()) if self.price.strip() else None
        except ValueError:
            return None


_FIELDS = [("Name", "name"), ("Vendor", "vendor"), ("Part #", "vendor_pn"), ("Category", "category"),
           ("Price", "price"), ("Link", "url"), ("Notes", "notes"), ("Added by", "added_by"),
           ("Added on", "added_on"), ("Different part", "different_part")]


def to_description(info: CotsInfo) -> str:
    lines = [DESCRIPTION_HEADER]
    for label, attr in _FIELDS:
        raw = getattr(info, attr)
        if isinstance(raw, bool):
            raw = "yes" if raw else ""          # 'Different part: yes' (a mentor said it isn't a duplicate)
        value = str(raw or "").replace("\n", " ").strip()
        if value:
            lines.append(f"{label}: {value}")
    return "\n".join(lines)


def parse_description(text: str) -> Optional[CotsInfo]:
    """CotsInfo from a file description written by to_description (None if it isn't one)."""
    if not text or DESCRIPTION_HEADER.lower() not in text.lower():
        return None
    info = CotsInfo()
    by_label = {label.lower(): attr for label, attr in _FIELDS}
    for line in text.splitlines():
        if ":" not in line:
            continue
        label, value = line.split(":", 1)
        attr = by_label.get(label.strip().lower())
        if attr == "different_part":
            info.different_part = value.strip().lower() in ("yes", "y", "true", "1", "x")
        elif attr:
            setattr(info, attr, value.strip())
    return info


def guess_from_file_name(file_name: str, vendors: Sequence[Vendor] = DEFAULT_VENDORS) -> CotsInfo:
    """
    For parts added WITHOUT Gusset (e.g. a Team 5000-style library): split
    '<part #> <name>' when the first word looks like a known vendor's number.
    """
    first, _, rest = (file_name or "").strip().partition(" ")
    for v in vendors:
        if v.pattern and re.match(v.pattern, first):
            return CotsInfo(name=rest or file_name, vendor=v.name, vendor_pn=first)
    return CotsInfo(name=file_name)


# ---------------------------------------------------------------------------
# Checking what a student typed (the Add to Library tool)
# ---------------------------------------------------------------------------
@dataclass
class Check:
    errors: List[str] = field(default_factory=list)     # block saving
    warnings: List[str] = field(default_factory=list)   # allowed, but shown

    @property
    def ok(self) -> bool:
        return not self.errors


# Words that don't tell two parts apart (vendor names are added per call).
_NOISE = {"the", "a", "an", "and", "with", "for", "of", "x", "by", "powered", "kit", "pack", "inch", "in",
          "mm", "bore", "frc", "new", "v1", "v2"}
# Words that always make a different product when only one name has them
# ('36t Steel Spur Gear' vs '36t Pocketed Steel Spur Gear' are both real WCP parts).
VARIANT_WORDS = {"pocketed", "motionx", "steel", "aluminum", "plastic", "nylon", "rounded", "thunderhex",
                 "splinexs", "splinexl", "key", "keyed", "falcon", "round", "left", "right", "hand", "flipped",
                 "thin", "double", "single", "hub", "solo", "spline"}
_UNITS = re.compile(r'(\d+(?:\.\d+)?)\s*(?:"|in\b|inch\b|-in\b)')


def name_key(name: str, vendors: Sequence[Vendor] = DEFAULT_VENDORS) -> Tuple[frozenset, frozenset]:
    """
    (words, numbers) that identify a part regardless of who sells it:
    'WCP Kraken X60 Powered by TalonFX' -> ({kraken, talonfx}, {x60}).
    Numbers (anything with a digit: 24t, x60, 1.125, 20dp) must ALL match for two
    parts to be called the same - a 24t and a 36t pulley never are.
    """
    text = _UNITS.sub(lambda m: f" {m.group(1)}in ", (name or "").lower())
    text = text.replace("tooth", "t").replace("teeth", "t")
    text = re.sub(r"(\d+)\s+t\b", r"\1t", text)
    vendor_words = {v.name.lower() for v in vendors} | {"andymark", "am", "rev", "robotics", "wcp", "westcoast",
                                                         "ctre", "sds", "ttb", "thrifty", "thriftybot"}
    words, numbers = set(), set()
    for w in re.split(r"[^a-z0-9.]+", text):
        w = w.strip(".")
        if not w or w in vendor_words:
            continue
        if any(ch.isdigit() for ch in w):
            numbers.add(w)
        elif w not in _NOISE and len(w) > 1:
            words.add(w)
    return frozenset(words), frozenset(numbers)


def same_part(a: str, b: str, vendors: Sequence[Vendor] = DEFAULT_VENDORS) -> bool:
    """
    True when two names very likely describe the same product. The numbers of one
    name must all be in the other (so '24t pulley' = '24t 5mm pulley', but never a
    36t one), and the words must mostly match - or one name is the other plus extras.
    """
    (wa, na), (wb, nb) = name_key(a, vendors), name_key(b, vendors)
    if not (wa and wb) or not (na <= nb or nb <= na):
        return False
    if (wa ^ wb) & VARIANT_WORDS:
        return False                                  # e.g. pocketed vs solid, MotionX vs plain, steel vs aluminum
    if na != nb:
        # the name with the extra numbers must also hold all of the other's words
        # ('NEO Vortex' vs 'NEO 550': each has something the other lacks -> different)
        (big_w, _), (small_w, _) = ((wa, na), (wb, nb)) if nb <= na else ((wb, nb), (wa, na))
        if not small_w <= big_w:
            return False
    shared = len(wa & wb)
    if shared == 0:
        return False
    small_words, small_nums = (wa, na) if len(wa) <= len(wb) else (wb, nb)
    contained = shared == len(small_words) and bool(small_nums)
    return shared / len(wa | wb) >= 0.75 or contained


def similar_items(info: CotsInfo, existing: Iterable["CatalogItem"],
                  vendors: Sequence[Vendor] = DEFAULT_VENDORS) -> List["CatalogItem"]:
    """Library parts that look like the same product as `info` (any vendor)."""
    pn = info.vendor_pn.strip().lower()
    return [item for item in existing
            if item.info.vendor_pn.strip().lower() != pn and same_part(info.name, item.title, vendors)]


def check_info(info: CotsInfo, existing: Iterable["CatalogItem"] = (),
               vendors: Sequence[Vendor] = DEFAULT_VENDORS,
               categories: Sequence[str] = DEFAULT_CATEGORIES, different_part: bool = False) -> Check:
    """
    Errors stop the save; warnings are advice. Messages are written for students.
    different_part=True is the student ticking "It's a different part" after a
    possible-duplicate error.
    """
    c = Check()
    existing = list(existing)
    if not info.name.strip():
        c.errors.append("Give the part a name (what the vendor calls it, e.g. 'NEO Brushless Motor V1.1').")
    elif len(info.name) > 80:
        c.warnings.append("That name is long - keep it to what fits on a label.")
    if not info.vendor.strip():
        c.errors.append("Pick the vendor.")
    if not info.vendor_pn.strip():
        c.errors.append("Type the vendor's part number (SKU) - it's on the product page.")
    elif " " in info.vendor_pn.strip():
        c.errors.append("Part numbers don't have spaces - copy just the SKU.")
    if not info.category.strip():
        c.errors.append("Pick a category.")
    elif info.category not in categories:
        c.warnings.append(f"'{info.category}' isn't one of the usual categories - it will get its own folder.")
    v = vendor_by_name(info.vendor, vendors)
    if v and v.pattern and info.vendor_pn.strip() and not re.match(v.pattern, info.vendor_pn.strip()):
        c.warnings.append(f"{v.name} part numbers usually look like {v.example} - double-check '{info.vendor_pn}'.")
    if v and v.hint:
        c.warnings.append(v.hint)
    if info.price.strip() and info.price_value() is None:
        c.errors.append("Price should be a number of dollars, e.g. 48.00 (or leave it empty).")
    if info.url.strip() and not re.match(r"^https?://", info.url.strip()):
        c.errors.append("The link should start with http:// or https:// (copy it from the browser).")
    if not info.url.strip():
        c.warnings.append("Add the product page link so others can re-order it.")
    pn = info.vendor_pn.strip().lower()
    for item in existing:
        if pn and item.info.vendor_pn.strip().lower() == pn:
            who = "" if item.vendor.lower() == info.vendor.strip().lower() else f" under {item.vendor}"
            c.errors.append(f"{info.vendor_pn} is already in the library{who} as '{item.file_name}' "
                            f"({item.category}). Use that one, or ask a mentor to update it.")
            break
    if info.name.strip():
        for item in similar_items(info, existing, vendors)[:3]:
            where = f"'{item.title}' from {item.vendor or 'another vendor'} ({item.info.vendor_pn or item.file_name})"
            if different_part:
                c.warnings.append(f"Looks a lot like {where} - saving anyway because you said it's different.")
            else:
                c.errors.append(f"This looks like {where}, which is already in the library. Use that one - "
                                "or, if it really is a different part, tick 'It's a different part'.")
    return c


def find_duplicates(items: Sequence["CatalogItem"],
                    vendors: Sequence[Vendor] = DEFAULT_VENDORS) -> List[Tuple["CatalogItem", "CatalogItem"]]:
    """Pairs of library parts that share a part # or look like the same product (for a library check)."""
    pairs = []
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            same_pn = a.info.vendor_pn and a.info.vendor_pn.lower() == b.info.vendor_pn.lower()
            marked_different = a.info.different_part or b.info.different_part    # 'It's a different part'
            if same_pn or (not marked_different and same_part(a.title, b.title, vendors)):
                pairs.append((a, b))
    return pairs


# ---------------------------------------------------------------------------
# The catalog (what the browser shows)
# ---------------------------------------------------------------------------
@dataclass
class CatalogItem:
    file_id: str
    file_name: str
    category: str                   # top folder
    vendor: str                     # second folder ("" if the part sits right in the category)
    info: CotsInfo = field(default_factory=CotsInfo)
    version: int = 0
    thumb: str = ""                 # thumbnail file name in the cache ("" = not fetched yet)

    @property
    def title(self) -> str:
        return self.info.name or self.file_name

    def to_json(self) -> dict:
        d = asdict(self)
        d["title"] = self.title
        return d


def make_item(file_id: str, file_name: str, folders: Sequence[str], description: str, version: int = 0,
              vendors: Sequence[Vendor] = DEFAULT_VENDORS) -> CatalogItem:
    """One catalog entry from a file found at FRC_COTS/<folders...>/<file_name>."""
    category = folders[0] if folders else "Uncategorized"
    vendor = folders[1] if len(folders) > 1 else ""
    info = parse_description(description) or guess_from_file_name(file_name, vendors)
    info.category = info.category or category
    info.vendor = info.vendor or vendor
    return CatalogItem(file_id, file_name, category, vendor or info.vendor, info, version)


def _words(text: str) -> List[str]:
    return [w for w in re.split(r"[^a-z0-9.#]+", (text or "").lower()) if w]


def search(items: Sequence[CatalogItem], query: str = "", category: str = "", vendor: str = "",
           favorites: Iterable[str] = (), favorites_only: bool = False) -> List[CatalogItem]:
    """
    Every word typed must appear somewhere (name, part #, vendor, category, notes).
    Best matches first: exact part number, then name starts, then whole words.
    """
    favs = set(favorites)
    words = _words(query)
    scored: List[Tuple[float, str, CatalogItem]] = []
    for item in items:
        if category and item.category != category:
            continue
        if vendor and item.vendor != vendor:
            continue
        if favorites_only and item.file_id not in favs:
            continue
        hay_name = item.title.lower()
        hay = " ".join([hay_name, item.info.vendor_pn.lower(), item.vendor.lower(), item.category.lower(),
                        item.info.notes.lower(), item.file_name.lower()])
        if any(w not in hay for w in words):
            continue
        score = 0.0
        q = query.strip().lower()
        if q and q == item.info.vendor_pn.lower():
            score += 100
        if q and hay_name.startswith(q):
            score += 20
        hay_words = set(_words(hay))
        score += sum(3 for w in words if w in hay_words)
        if item.file_id in favs:
            score += 5
        scored.append((-score, hay_name, item))
    scored.sort(key=lambda s: (s[0], s[1]))
    return [s[2] for s in scored]


def catalog_to_json(items: Sequence[CatalogItem], scanned_at: float) -> str:
    return json.dumps({"scanned_at": scanned_at, "items": [i.to_json() for i in items]})


def catalog_from_json(text: str) -> Tuple[List[CatalogItem], float]:
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return [], 0.0
    items = []
    for d in data.get("items", []):
        try:
            info = CotsInfo(**{k: d["info"].get(k, "") for k in CotsInfo.__dataclass_fields__})
            items.append(CatalogItem(d["file_id"], d["file_name"], d["category"], d["vendor"], info,
                                     int(d.get("version", 0)), d.get("thumb", "")))
        except (KeyError, TypeError, AttributeError):
            continue
    return items, float(data.get("scanned_at", 0.0))


def thumb_file_name(file_id: str) -> str:
    """A safe file name for a part's thumbnail (file ids contain ':' and '.')."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", file_id)[-80:] + ".png"


def folder_counts(items: Sequence[CatalogItem]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for i in items:
        counts[i.category] = counts.get(i.category, 0) + 1
    return counts


def attrs_for(info: CotsInfo) -> Dict[str, str]:
    """Gusset attributes written INSIDE a library part (read by Name Parts / BOM / Design Review)."""
    out = {"cots": "true", "cots_name": info.name, "cots_vendor": info.vendor, "cots_pn": info.vendor_pn,
           "cots_category": info.category}
    if info.price_value() is not None:
        out["cots_price"] = f"{info.price_value():.2f}"
    if info.url:
        out["cots_url"] = info.url
    return out


def vendor_link(info: CotsInfo, vendors: Sequence[Vendor] = DEFAULT_VENDORS) -> str:
    """The product link if we have it, else the vendor's search link for the part number."""
    if info.url:
        return info.url
    v = vendor_by_name(info.vendor, vendors)
    return v.link.replace("{pn}", info.vendor_pn) if v and v.link and info.vendor_pn else ""


# ---------------------------------------------------------------------------
# Batch import: a parts list (CSV) + a folder of STEP files
# ---------------------------------------------------------------------------
PARTS_LIST_COLUMNS = ["Category", "Vendor", "Part #", "Name", "Price", "Link", "Notes", "Different part"]
STEP_EXTENSIONS = (".step", ".stp")

READY, NO_STEP, IN_LIBRARY, NEEDS_LOOK, NO_PN, TWO_FILES = (
    "ready", "no STEP file yet", "already in the library", "needs a look", "needs a part #", "more than one STEP file")


def parse_parts_list(text: str) -> Tuple[List[CotsInfo], List[str]]:
    """
    Rows of the parts list -> CotsInfo. Columns are matched by header name (any
    order, extra columns ignored), so the list can be edited in Excel / Sheets.
    """
    problems: List[str] = []
    reader = csv.DictReader(io.StringIO((text or "").lstrip("\ufeff")))
    headers = {h.strip().lower(): h for h in (reader.fieldnames or [])}
    missing = [c for c in ("Category", "Vendor", "Part #", "Name") if c.lower() not in headers]
    if missing:
        return [], [f"The parts list needs these columns: {', '.join(missing)}"]
    infos = []
    for n, row in enumerate(reader, start=2):
        def col(name):
            key = headers.get(name.lower())
            return (row.get(key) or "").strip() if key else ""
        if not any(col(c) for c in PARTS_LIST_COLUMNS):
            continue                                   # blank line
        infos.append(CotsInfo(name=col("Name"), vendor=col("Vendor"), vendor_pn=col("Part #"),
                              category=col("Category"), price=col("Price").replace("$", ""), url=col("Link"),
                              notes=col("Notes"),
                              different_part=col("Different part").lower() in ("yes", "y", "true", "x", "1")))
        if not col("Name"):
            problems.append(f"Row {n} has no name")
    return infos, problems


def parts_list_csv(infos: Sequence[CotsInfo]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(PARTS_LIST_COLUMNS)
    for i in infos:
        writer.writerow([i.category, i.vendor, i.vendor_pn, i.name, i.price, i.url, i.notes,
                         "yes" if i.different_part else ""])
    return out.getvalue()


def step_files_for(vendor_pn: str, file_names: Iterable[str]) -> List[str]:
    """
    STEP files whose name contains the part number as a whole 'word':
    'am-2986 FR8ZZ Hex Bearing.STEP' and 'REV-21-1652.step' match; 'WCP-07330.step'
    doesn't match WCP-0733. Case and _ / space / - differences are ignored.
    """
    if not vendor_pn.strip():
        return []
    norm = lambda t: re.sub(r"[\s_]+", "-", t.lower())
    pn = re.escape(norm(vendor_pn.strip()))
    pattern = re.compile(rf"(^|[^a-z0-9]){pn}($|[^a-z0-9])")
    return [f for f in file_names
            if f.lower().endswith(STEP_EXTENSIONS) and pattern.search(norm(f.rsplit(".", 1)[0]))]


_REPEAT = re.compile(r"^(?P<base>.+?) \((?P<n>\d+)\)(?P<ext>\.[A-Za-z0-9]+)$")


def drop_repeat_downloads(sizes: Dict[str, int]) -> List[str]:
    """
    File names with browser repeat-download copies removed: 'WCP-1434 (1).step'
    goes when 'WCP-1434.step' is there with the same size (a real second version,
    with a different size, is kept so the importer can ask).
    """
    keep = []
    for name in sorted(sizes):
        m = _REPEAT.match(name)
        if m:
            original = m.group("base") + m.group("ext")
            if original in sizes and sizes[original] == sizes[name]:
                continue
        keep.append(name)
    return keep


@dataclass
class ImportRow:
    info: CotsInfo
    status: str
    step: str = ""                                    # file name in the folder
    message: str = ""
    file_id: str = ""                                 # set once the part is saved to the library


def plan_import(infos: Sequence[CotsInfo], file_names: Sequence[str], existing: Sequence[CatalogItem] = (),
                vendors: Sequence[Vendor] = DEFAULT_VENDORS,
                categories: Sequence[str] = DEFAULT_CATEGORIES) -> List[ImportRow]:
    """What a batch import would do with each row - nothing is saved here."""
    rows: List[ImportRow] = []
    library = list(existing)
    for info in infos:
        if not info.vendor_pn:
            rows.append(ImportRow(info, NO_PN, message="Copy the SKU from the product page into the parts list."))
            continue
        check = check_info(info, library, vendors, categories, different_part=info.different_part)
        if any("already in the library" in e and info.vendor_pn in e for e in check.errors):
            rows.append(ImportRow(info, IN_LIBRARY))
            continue
        files = step_files_for(info.vendor_pn, file_names)
        if not files:
            rows.append(ImportRow(info, NO_STEP))
            continue
        if len(files) > 1:
            rows.append(ImportRow(info, TWO_FILES, message="Keep only the version your team uses: " +
                                  ", ".join(files)))
            continue
        if not check.ok:
            rows.append(ImportRow(info, NEEDS_LOOK, files[0], check.errors[0]))
            continue
        rows.append(ImportRow(info, READY, files[0]))
        library.append(CatalogItem("planned:" + info.vendor_pn, part_file_name(info.vendor_pn, info.name),
                                   info.category, info.vendor, info))      # catch duplicates within the list
    return rows


def unmatched_steps(rows: Sequence[ImportRow], file_names: Sequence[str]) -> List[str]:
    """STEP files in the folder that no parts-list row claimed (add them one at a time)."""
    used = {r.step for r in rows if r.step}
    claimed = set()
    for r in rows:
        claimed.update(step_files_for(r.info.vendor_pn, file_names))
    return [f for f in file_names if f.lower().endswith(STEP_EXTENSIONS) and f not in used and f not in claimed]


def import_summary(rows: Sequence[ImportRow], extra_files: Sequence[str] = ()) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1
    if extra_files:
        counts["STEP files not in the list"] = len(extra_files)
    return counts
