"""
cots_library.py - the Fusion side of Gusset's COTS library.

  find_project / make_project   the FRC_COTS cloud project (+ category/vendor folders)
  scan()                        every part in it -> catalog (cached on this laptop)
  ThumbnailFetcher              Fusion's own cloud thumbnails -> PNGs for the browser
  insert()                      put a library part into the open design
  add_part()                    save a new part into the library, correctly formatted
                                (STEP file or a component from the open design)

Formats, checks and search are in cots_core.py (tested).
"""

from __future__ import annotations

import os
import time
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import adsk.core
import adsk.fusion

from . import cots_core as cc
from . import feature_builder as fb
from . import log as gslog

_log = gslog.get_logger("cots_library")
ATTR_GROUP = "Gusset"
SAVE_TIMEOUT_S = 120
# Tested in Fusion (Nov 2026, 116 files): while Gusset's own code is running, Fusion
# never reports an upload as finished - every file reported "still uploading" and had no
# readable description yet, but all 116 were complete with descriptions minutes later.
# So add_part doesn't wait: Fusion finishes uploads in the background after the tab closes.
UPLOAD_WAIT_S = 0
DESCRIPTION_CHECK = False


def _safe(getter, default=None):
    try:
        value = getter()
        return default if value is None else value
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Project and folders
# ---------------------------------------------------------------------------
_project_ids: Dict[str, str] = {}     # project name -> root folder id (finding a project by name is slow)


def find_project(name: str = cc.LIBRARY_PROJECT, remembered_folder_id: str = ""):
    """
    The library project, or None. Every cloud call costs ~0.5 s and looping over
    all of a hub's projects ~4 s, so the root folder id is remembered (pass the
    one saved in gusset_state.json as remembered_folder_id).
    """
    data = adsk.core.Application.get().data
    for folder_id in (_project_ids.get(name.lower()), remembered_folder_id):
        if folder_id:
            folder = _safe(lambda f=folder_id: data.findFolderById(f))
            project = _safe(lambda: folder.parentProject) if folder else None
            if project is not None and _safe(lambda: project.name, "").strip().lower() == name.lower():
                return project
    for p in _safe(lambda: data.dataProjects.asArray(), []):
        if _safe(lambda: p.name, "").strip().lower() == name.lower():
            _project_ids[name.lower()] = p.rootFolder.id
            return p
    return None


def project_folder_id(project) -> str:
    return _safe(lambda: project.rootFolder.id, "")


def make_project(name: str = cc.LIBRARY_PROJECT, categories: Sequence[str] = cc.DEFAULT_CATEGORIES,
                 vendors: Sequence[cc.Vendor] = cc.DEFAULT_VENDORS):
    """
    Create FRC_COTS with a folder per category. Vendor folders are made the first
    time a part needs one (folder_for) - empty folders make every Refresh slower.
    """
    data = adsk.core.Application.get().data
    project = find_project(name) or data.dataProjects.add(name)
    for cat in categories:
        _sub_folder(project.rootFolder, cat)
    _project_ids[name.lower()] = project.rootFolder.id
    _log.info("COTS library project %r ready: %d category folders (vendor folders come with the first part)",
              name, len(categories))
    return project


def _sub_folder(parent, name: str):
    existing = parent.dataFolders.itemByName(name)
    return existing or parent.dataFolders.add(name)


def folder_for(project, info: cc.CotsInfo):
    """FRC_COTS/<Category>/<Vendor> (made if missing)."""
    return _sub_folder(_sub_folder(project.rootFolder, cc.safe_name(info.category)), cc.safe_name(info.vendor))


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------
def scan(project, vendors: Sequence[cc.Vendor] = cc.DEFAULT_VENDORS, time_limit: float = 90.0,
         max_depth: int = 2) -> List[cc.CatalogItem]:
    """
    Every .f3d in the project. Top folder = category, next = vendor (a Team 5000
    layout - parts right in the category folders - works too). Folders deeper than
    max_depth aren't opened: every folder listing is a ~0.5 s cloud call.
    """
    started = time.time()
    items: List[cc.CatalogItem] = []
    stack: List[Tuple[object, List[str]]] = [(project.rootFolder, [])]
    folders = 0
    while stack:
        if time.time() - started > time_limit:
            _log.warning("COTS scan stopped after %.0fs (%d parts so far)", time.time() - started, len(items))
            break
        folder, path = stack.pop()
        folders += 1
        for f in _safe(lambda: folder.dataFiles.asArray(), []):
            if _safe(lambda: f.fileExtension, "") != "f3d":
                continue
            items.append(cc.make_item(f.id, f.name, path, _safe(lambda: f.description, "") or "",
                                      _safe(lambda: f.versionNumber, 0), vendors))
        if len(path) >= max_depth:
            continue
        for sub in _safe(lambda: folder.dataFolders.asArray(), []):
            name = _safe(lambda: sub.name, "")
            if name.lower() in ("icons", "_archive", "_review"):     # _Review = Library Check's set-aside duplicates
                continue
            stack.append((sub, path + [name]))
    _log.info("Scanned COTS library: %d parts in %d folders (%.1fs)", len(items), folders, time.time() - started)
    return items


# ---------------------------------------------------------------------------
# Thumbnails (Fusion makes them in the cloud for every saved design)
# ---------------------------------------------------------------------------
class ThumbnailFetcher:
    """Ask for many thumbnails at once, then poll; each finished one is saved as a PNG."""

    def __init__(self, folder: str, on_ready: Callable[[str, str], None],
                 on_failed: Optional[Callable[[str], None]] = None):
        self.folder = folder
        self.on_ready = on_ready
        self.on_failed = on_failed          # Fusion has no picture for this file (Library Check flags it)
        self.pending: Dict[str, object] = {}       # file id -> DataObjectFuture
        os.makedirs(folder, exist_ok=True)

    def request(self, items: Sequence[cc.CatalogItem], limit: int = 60) -> int:
        data = adsk.core.Application.get().data
        asked = 0
        for item in items:
            if asked >= limit:
                break
            path = os.path.join(self.folder, cc.thumb_file_name(item.file_id))
            if os.path.exists(path) or item.file_id in self.pending:
                continue
            if not is_cloud_id(item.file_id):
                continue                                   # temporary id from an upload - fixed on Refresh
            data_file = _safe(lambda i=item: data.findFileById(i.file_id))
            future = _safe(lambda: data_file.thumbnail) if data_file else None
            if future is not None:
                self.pending[item.file_id] = future
                asked += 1
        if asked:
            _log.debug("Asked Fusion for %d thumbnail(s)", asked)
        return asked

    def poll(self) -> int:
        """Save finished thumbnails; returns how many are still pending."""
        done = []
        for file_id, future in self.pending.items():
            state = _safe(lambda: future.state)
            if state == adsk.core.FutureStates.FinishedFutureState:
                name = cc.thumb_file_name(file_id)
                try:
                    if future.dataObject.saveToFile(os.path.join(self.folder, name)):
                        self.on_ready(file_id, name)
                except Exception as exc:
                    _log.debug("Thumbnail for %s didn't save: %s", file_id, exc)
                done.append(file_id)
            elif state == adsk.core.FutureStates.FailedFutureState:
                _log.debug("Fusion has no thumbnail for %s", file_id)
                if self.on_failed:
                    try:
                        self.on_failed(file_id)
                    except Exception as exc:
                        _log.debug("on_failed(%s) raised %s", file_id, exc)
                done.append(file_id)
        for file_id in done:
            self.pending.pop(file_id, None)
        return len(self.pending)


# ---------------------------------------------------------------------------
# Inserting
# ---------------------------------------------------------------------------
PROJECT_COTS_FOLDER = "COTS"


def _project_copy(data_file, doc, category: str):
    """
    Fusion can only LINK a part from the same project, so the first time a part is
    used in a robot project it's copied to <project>/COTS/<Category>/ and that copy
    is reused afterwards (matched by file name). Returns None when the open design
    isn't saved yet (no project to copy into).
    """
    here = _safe(lambda: doc.dataFile)
    if here is None:
        return None
    project = here.parentProject
    if project.id == data_file.parentProject.id:
        return data_file                                     # already in the same project (e.g. testing)
    folder = _sub_folder(_sub_folder(project.rootFolder, PROJECT_COTS_FOLDER), cc.safe_name(category or "Other"))
    for f in _safe(lambda: folder.dataFiles.asArray(), []):
        if _safe(lambda: f.name, "") == data_file.name:
            _log.info("Reusing this project's copy of %s", data_file.name)
            return f
    copy = data_file.copy(folder)
    if copy is None:
        return None
    waited = time.time()
    while not _safe(lambda: copy.isComplete, True) and time.time() - waited < SAVE_TIMEOUT_S:
        time.sleep(0.25)
    _log.info("Copied %s into %s/%s/%s", data_file.name, project.name, PROJECT_COTS_FOLDER, category)
    return copy


def is_cloud_id(file_id: str) -> bool:
    """
    A real cloud id ('urn:adsk.wipprod:dm.lineage:...'). Tested in Fusion: right after
    saveAs, while the upload is still running, DataFile.id is a temporary local path
    ('.../W.login/F/_name.<uuid>.f3d') that findFileById later rejects ("invalid id").
    """
    return (file_id or "").startswith("urn:")


def find_by_name(project, category: str, vendor: str, file_name: str):
    """Look a library part up by where it lives: FRC_COTS/<category>/<vendor>/<file name>."""
    folder = _safe(lambda: project.rootFolder.dataFolders.itemByName(category)) if project else None
    if folder is not None and vendor:
        folder = _safe(lambda: folder.dataFolders.itemByName(vendor)) or folder
    for f in _safe(lambda: folder.dataFiles.asArray(), []) if folder else []:
        if _safe(lambda: f.name, "") == file_name:
            return f
    return None


def resolve(file_id: str, project=None, category: str = "", vendor: str = "", file_name: str = ""):
    """The DataFile for a catalog entry - by id, or by name if the id is stale or temporary."""
    data = adsk.core.Application.get().data
    if is_cloud_id(file_id):
        try:
            found = data.findFileById(file_id)
            if found is not None:
                return found
        except RuntimeError as exc:
            _log.info("findFileById(%s) failed (%s) - looking the part up by name", file_id[:60], exc)
    if project is not None and file_name:
        found = find_by_name(project, category, vendor, file_name)
        if found is not None:
            _log.info("Found %s by name in %s/%s", file_name, category, vendor)
            return found
    return None


def insert(file_id: str, target_comp, category: str = "", project=None, vendor: str = "", file_name: str = ""):
    """
    Insert a library part at the origin of target_comp. Linked (through this
    project's COTS folder) when possible, otherwise an embedded copy - both are
    flagged COTS inside. Returns (occurrence, linked?, data_file).
    """
    app = adsk.core.Application.get()
    data_file = resolve(file_id, project, category, vendor, file_name)
    if data_file is None:
        raise fb.FeatureError("Gusset couldn't find that part in the library - press Refresh (the round arrow) "
                              "in the COTS panel and try again.")
    matrix = adsk.core.Matrix3D.create()
    try:
        local = _project_copy(data_file, app.activeDocument, category)
        if local is not None:
            occ = target_comp.occurrences.addByInsert(local, matrix, True)
            if occ:
                _log.info("Inserted %s (linked)", data_file.name)
                return occ, True, data_file
    except Exception as exc:
        _log.info("Linked insert of %s didn't work (%s) - inserting a copy instead", data_file.name, exc)
    occ = target_comp.occurrences.addByInsert(data_file, matrix, False)
    if occ is None:
        raise fb.FeatureError(f"Fusion couldn't insert '{data_file.name}'.")
    _log.info("Inserted %s (embedded copy - save the design first to get linked parts)", data_file.name)
    return occ, False, data_file


# ---------------------------------------------------------------------------
# Adding a part to the library
# ---------------------------------------------------------------------------
def write_attrs(comp, info: cc.CotsInfo) -> None:
    for name, value in cc.attrs_for(info).items():
        existing = comp.attributes.itemByName(ATTR_GROUP, name)
        if existing:
            existing.value = value
        else:
            comp.attributes.add(ATTR_GROUP, name, value)


def _new_design():
    app = adsk.core.Application.get()
    try:
        doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType, False)
    except RuntimeError:
        doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType, True)   # no hidden docs yet
    design = adsk.fusion.Design.cast(doc.products.itemByProductType("DesignProductType"))
    try:
        design.fusionUnitsManager.distanceDisplayUnits = adsk.fusion.DistanceUnits.InchDistanceUnits
    except Exception:
        pass
    return doc, design


def _copy_component(design, occurrence) -> int:
    """Copy the bodies of a component from the open design into `design` (in the part's own frame)."""
    tbm = adsk.fusion.TemporaryBRepManager.get()
    to_local = occurrence.transform2.copy()
    to_local.invert()
    bodies = []

    def collect(occ):
        for i in range(occ.bRepBodies.count):
            bodies.append(occ.bRepBodies.item(i))
        for k in range(occ.childOccurrences.count):
            collect(occ.childOccurrences.item(k))

    collect(occurrence)
    if not bodies:
        raise fb.FeatureError("That component has no solid bodies to copy.")
    root = design.rootComponent
    parametric = design.designType == adsk.fusion.DesignTypes.ParametricDesignType
    base = root.features.baseFeatures.add() if parametric else None
    if base:
        base.startEdit()
    try:
        for body in bodies:
            temp = tbm.copy(body)
            tbm.transform(temp, to_local)
            new = root.bRepBodies.add(temp, base) if base else root.bRepBodies.add(temp)
            new.name = body.name
    finally:
        if base:
            base.finishEdit()
    return len(bodies)


def add_part(info: cc.CotsInfo, project, step_path: str = "", occurrence=None,
             upload_wait: float = UPLOAD_WAIT_S) -> str:
    """
    Make the library file: import the STEP (or copy the component), stamp the
    COTS details inside it, save as '<part #> <name>' in FRC_COTS/<Category>/<Vendor>,
    and write the details into the file's description. Returns the new file's id.
    """
    if not step_path and occurrence is None:
        raise fb.FeatureError("Pick a STEP file or a component to add.")
    folder = folder_for(project, info)
    file_name = cc.part_file_name(info.vendor_pn, info.name)
    for f in _safe(lambda: folder.dataFiles.asArray(), []):
        if _safe(lambda: f.name, "").lower() == file_name.lower():
            raise fb.FeatureError(f"'{file_name}' is already in {info.category}/{info.vendor}.")
    app = adsk.core.Application.get()
    started = time.time()
    doc, design = _new_design()
    try:
        root = design.rootComponent
        if step_path:
            if not os.path.isfile(step_path):
                raise fb.FeatureError(f"Can't find the file {step_path}")
            opts = app.importManager.createSTEPImportOptions(step_path)
            if not app.importManager.importToTarget(opts, root):
                raise fb.FeatureError("Fusion couldn't import that STEP file.")
            _log.info("Imported %s", os.path.basename(step_path))
        else:
            n = _copy_component(design, occurrence)
            _log.info("Copied %d body(ies) from %s", n, occurrence.name)
        root.partNumber = info.vendor_pn
        root.description = info.name
        write_attrs(root, info)
        if not doc.saveAs(file_name, folder, cc.to_description(info), ""):
            raise fb.FeatureError(f"Fusion didn't save '{file_name}'.")
        data_file = doc.dataFile
        if upload_wait > 0 and not wait_for_upload(data_file, upload_wait):
            # Not an error: Fusion keeps uploading after the tab closes (big vendor models can take
            # minutes). Batch imports re-check these at the end (still_uploading).
            _log.info("%s is still uploading after %.0fs - Fusion will finish it in the background",
                      file_name, upload_wait)
        if DESCRIPTION_CHECK and cc.parse_description(_safe(lambda: data_file.description, "")) is None:
            # (DataFile.description is read-only, so saveAs is the only chance to write it)
            _log.warning("%s saved without its description - the panel will read the details from the name",
                         file_name)
        _log.info("Added %s to %s/%s/%s (%.1fs)", file_name, project.name, info.category, info.vendor,
                  time.time() - started)
        new_id = _safe(lambda: data_file.id, "")
        if not is_cloud_id(new_id):
            _log.debug("%s has a temporary id while uploading - the panel will find it by name", file_name)
        return new_id
    finally:
        try:
            doc.close(False)
        except Exception:
            pass


def upload_done(file_id: str) -> bool:
    """
    Ask the cloud again. (Tested in Fusion: during a batch import a DataFile we held
    on to kept saying isComplete=False for minutes after the upload had finished.)
    """
    fresh = _safe(lambda: adsk.core.Application.get().data.findFileById(file_id))
    return bool(fresh is not None and _safe(lambda: fresh.isComplete, False))


def wait_for_upload(data_file, seconds: float) -> bool:
    """True once the file is fully uploaded; False if it's still going after `seconds`."""
    started, last_fresh = time.time(), 0.0
    file_id = _safe(lambda: data_file.id, "")
    while time.time() - started < seconds:
        if _safe(lambda: data_file.isComplete, False):
            return True
        if file_id and time.time() - last_fresh > 2.0:
            last_fresh = time.time()
            if upload_done(file_id):
                return True
        adsk.doEvents()
        time.sleep(0.25)
    return False


def cots_info_from_component(comp) -> Optional[cc.CotsInfo]:
    """Library details stamped inside a part (None if it isn't a Gusset library part)."""
    def attr(name):
        a = _safe(lambda: comp.attributes.itemByName(ATTR_GROUP, name))
        return a.value if a else ""
    if not attr("cots_pn") and not attr("cots_vendor"):
        return None
    return cc.CotsInfo(name=attr("cots_name"), vendor=attr("cots_vendor"), vendor_pn=attr("cots_pn"),
                       category=attr("cots_category"), price=attr("cots_price"), url=attr("cots_url"))


# ---------------------------------------------------------------------------
# Library Check fixes (0.11). Each returns a short sentence for the check window and
# raises fb.FeatureError with a student-friendly message when it can't finish.
# ---------------------------------------------------------------------------
def _must_find(file_id: str, project=None, category: str = "", vendor: str = "", file_name: str = ""):
    data_file = resolve(file_id, project, category, vendor, file_name)
    if data_file is None:
        raise fb.FeatureError("Fusion can't find that file anymore - press Re-check to read the library again.")
    return data_file


def rename_file(data_file, new_name: str) -> str:
    old = data_file.name
    if old == new_name:
        return "Already named right."
    for f in _safe(lambda: data_file.parentFolder.dataFiles.asArray(), []):
        if _safe(lambda: f.name, "").lower() == new_name.lower() and f.id != data_file.id:
            raise fb.FeatureError(f"There's already a file called '{new_name}' in that folder - "
                                  "check whether it's a duplicate first.")
    data_file.name = new_name                         # DataFile.name can be set (the file keeps its id)
    _log.info("Renamed '%s' -> '%s'", old, new_name)
    return f"Renamed to '{new_name}'."


def move_file(data_file, folder) -> str:
    """Move a file (same id, so robots that use it keep working)."""
    here = _safe(lambda: data_file.parentFolder.id, "")
    if here and here == _safe(lambda: folder.id, ""):
        return "Already in the right folder."
    for f in _safe(lambda: folder.dataFiles.asArray(), []):
        if _safe(lambda: f.name, "").lower() == data_file.name.lower():
            raise fb.FeatureError(f"There's already a '{data_file.name}' in {folder.name} - "
                                  "it may be a duplicate; check it by hand.")
    if not data_file.move(folder):
        raise fb.FeatureError(f"Fusion didn't move '{data_file.name}'.")
    _log.info("Moved '%s' to %s", data_file.name, _safe(lambda: folder.name, "?"))
    return f"Moved to {folder.name}."


def move_to_review(data_file, project, review_folder: str) -> str:
    """Set a duplicate aside in FRC_COTS/_Review (nothing is deleted; the panel doesn't show that folder)."""
    folder = _sub_folder(project.rootFolder, review_folder)
    move_file(data_file, folder)
    return f"Moved to {review_folder} - delete it there once you're sure."


def move_to(data_file, project, info: cc.CotsInfo) -> str:
    return move_file(data_file, folder_for(project, info))


def _open(data_file):
    """Open a library file visibly (thumbnails are made from what's on screen)."""
    app = adsk.core.Application.get()
    doc = app.documents.open(data_file, True)
    if doc is None:
        raise fb.FeatureError(f"Fusion couldn't open '{data_file.name}'.")
    design = adsk.fusion.Design.cast(doc.products.itemByProductType("DesignProductType"))
    if design is None:
        doc.close(False)
        raise fb.FeatureError(f"'{data_file.name}' isn't a design.")
    return doc, design


def replace_geometry(design, step_path: str) -> int:
    """Throw away the old model and import the vendor's new STEP into the same file."""
    app = adsk.core.Application.get()
    root = design.rootComponent
    if not os.path.isfile(step_path):
        raise fb.FeatureError(f"Can't find the file {step_path}")
    removed = 0
    if design.designType == adsk.fusion.DesignTypes.ParametricDesignType:
        timeline = design.timeline
        removed = timeline.count
        timeline.markerPosition = 0
        timeline.deleteAllAfterMarker()               # the old import and anything built on it
    for occ in [root.occurrences.item(i) for i in range(root.occurrences.count)]:   # direct-modeling files
        _safe(occ.deleteMe)
        removed += 1
    for body in [root.bRepBodies.item(i) for i in range(root.bRepBodies.count)]:
        _safe(body.deleteMe)
        removed += 1
    opts = app.importManager.createSTEPImportOptions(step_path)
    if not app.importManager.importToTarget(opts, root):
        raise fb.FeatureError("Fusion couldn't import that STEP file.")
    _log.info("Replaced the model with %s (%d old item(s) removed)", os.path.basename(step_path), removed)
    return removed


def save_version(data_file, info: cc.CotsInfo, step_path: str = "", why: str = "Library Check") -> str:
    """
    Save a new version of a library part: new details (written inside the part AND as
    the version's description - the file description itself can't be changed after
    the first save), a fresh picture, and optionally a new model from a STEP file.
    Returns the file id (unchanged - robots that use the part see 'out of date').
    """
    started = time.time()
    doc, design = _open(data_file)
    try:
        root = design.rootComponent
        if step_path:
            replace_geometry(design, step_path)
        root.partNumber = info.vendor_pn
        root.description = info.name
        write_attrs(root, info)
        root.attributes.add(ATTR_GROUP, "cots_saved", f"{why} {time.strftime('%Y-%m-%d %H:%M')}")  # marks it changed
        _safe(lambda: adsk.core.Application.get().activeViewport.fit())        # a centred picture
        if not doc.save(cc.to_description(info)):
            raise fb.FeatureError(f"Fusion didn't save '{data_file.name}'.")
        _log.info("Saved a new version of %s (%s, %.1fs)", data_file.name, why, time.time() - started)
    finally:
        try:
            doc.close(False)
        except Exception:
            pass
    return _safe(lambda: data_file.id, "")


def description_took(file_id: str, info: cc.CotsInfo) -> bool:
    """
    Did the new details reach the file's description (what the panel reads)? Logged
    either way - the parts' own details (what the BOM reads) are always written.
    """
    fresh = _safe(lambda: adsk.core.Application.get().data.findFileById(file_id))
    latest = _safe(lambda: fresh.latestVersion) or fresh
    got = cc.parse_description(_safe(lambda: latest.description, "") or "")
    ok = bool(got and got.price == info.price and got.url == info.url and got.vendor_pn == info.vendor_pn)
    _log.info("Description after save %s for %s", "updated" if ok else "NOT updated (yet)", file_id[:60])
    return ok


def robot_copy(library_file, category: str):
    """This robot project's copy of a library part (COTS/<Category>/<same name>), or None."""
    doc = _safe(lambda: adsk.core.Application.get().activeDocument)
    here = _safe(lambda: doc.dataFile) if doc else None
    if here is None:
        return None
    project = here.parentProject
    if project.id == library_file.parentProject.id:
        return None
    cots = _safe(lambda: project.rootFolder.dataFolders.itemByName(PROJECT_COTS_FOLDER))
    folder = _safe(lambda: cots.dataFolders.itemByName(cc.safe_name(category or "Other"))) if cots else None
    for f in _safe(lambda: folder.dataFiles.asArray(), []) if folder else []:
        if _safe(lambda: f.name, "") == library_file.name:
            return f
    return None
