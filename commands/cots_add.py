"""
Add to COTS Library - lets students add vendor parts to FRC_COTS, formatted
correctly every time (GUSSET > COTS > Add to Library, or "+ Add part" in the panel).

  1. Source: a STEP file downloaded from the vendor, OR a component already in
     this design (e.g. a part someone modeled).
  2. Fill in Name / Vendor / Part # / Category (+ Price, Link, Notes, initials).
     The box at the bottom checks it live: red = must fix, yellow = double-check.
     Duplicates (same part #) are blocked.
  3. OK. Right after the dialog closes Gusset makes the library file:
        FRC_COTS/<Category>/<Vendor>/<Part #> <Name>
     with the details in its description AND stamped inside it (so Name Parts
     leaves it alone and the BOM gets vendor, part #, link and price).
"""

from __future__ import annotations

import datetime
import os
import time
from typing import Dict, List

import adsk.core
import adsk.fusion

from .. import config
from ..lib import cots_core as cc
from ..lib import cots_library as cl
from ..lib import feature_builder as fb
from ..lib import fusion_helpers as fh
from ..lib import log as gslog
from ..lib import settings
from ..lib import tip_box
from . import cots_browser

CMD_ID = "Gusset_CotsAdd"
CMD_NAME = "Add to Library"
CMD_TOOLTIP = "Add a vendor part (STEP file or a component) to the team's FRC_COTS library - formatted for you."
ICON_DIR = os.path.join(config.ADDIN_DIR, "resources", "cots_add")
HANDLER_GROUP = "cots_add"
EVENT_ID = "Gusset_CotsAdd_Save"
_saving = False                 # True while library files are being made (the save signal can repeat)

SRC_STEP, SRC_COMP = "A STEP file from the vendor", "A component in this design"
SRC_FOLDER = "A folder of STEP files (parts list)"
STARTER_LIST = os.path.join(config.ADDIN_DIR, "resources", "cots_starter_parts.csv")
REPORT_NAME = "Gusset import report.csv"
BATCH_UPLOAD_WAIT_S = 0      # see cots_library.UPLOAD_WAIT_S
(ID_SRC, ID_BROWSE, ID_FILE, ID_COMP, ID_NAME, ID_VENDOR, ID_PN, ID_CAT, ID_PRICE, ID_URL, ID_NOTES, ID_BY,
 ID_CHECK, ID_DIFF, ID_FOLDER_BTN, ID_FOLDER) = (
    "ca_src", "ca_browse", "ca_file", "ca_comp", "ca_name", "ca_vendor", "ca_pn", "ca_cat", "ca_price", "ca_url",
    "ca_notes", "ca_by", "ca_check", "ca_diff", "ca_folder_btn", "ca_folder")
SINGLE_ONLY = (ID_NAME, ID_VENDOR, ID_PN, ID_CAT, ID_PRICE, ID_URL, ID_NOTES)

_log = gslog.get_logger("cots_add")
_state: Dict[str, object] = {}
_pending: List[dict] = []
_event = None


def start() -> None:
    global _event
    app, _ = fh.app_ui()
    try:
        app.unregisterCustomEvent(EVENT_ID)
    except Exception:
        pass
    _event = app.registerCustomEvent(EVENT_ID)
    _event.add(fh.make_handler(adsk.core.CustomEventHandler, _on_save, "Add to COTS: save"))
    fh.add_button(CMD_ID, CMD_NAME, CMD_TOOLTIP, ICON_DIR, _on_created, config.PANEL_COTS_ID,
                  config.PANEL_COTS_NAME, promote=False)


def stop() -> None:
    try:
        app, _ = fh.app_ui()
        app.unregisterCustomEvent(EVENT_ID)
    except Exception:
        pass
    _pending.clear()
    fh.remove_button(CMD_ID, config.PANEL_COTS_ID)


def _dropdown(inputs, input_id, label, choices, selected):
    dd = inputs.addDropDownCommandInput(input_id, label, adsk.core.DropDownStyles.TextListDropDownStyle)
    pick = selected if selected in choices else choices[0]
    for c in choices:
        dd.listItems.add(c, c == pick)
    return dd


def _text(inputs, input_id) -> str:
    item = inputs.itemById(input_id)
    if isinstance(item, adsk.core.DropDownCommandInput):
        return item.selectedItem.name if item.selectedItem else ""
    return (adsk.core.StringValueCommandInput.cast(item).value or "").strip()


def _set(inputs, input_id, value: str) -> None:
    adsk.core.StringValueCommandInput.cast(inputs.itemById(input_id)).value = value


def _on_created(args: adsk.core.CommandCreatedEventArgs) -> None:
    _log.info("Add to COTS Library opened")
    cmd = args.command
    _state.clear()
    lib = cots_browser.library_settings()
    _state["lib"] = lib
    last = settings.load_state(config.ADDIN_DIR).get("cots_add")
    last = last if isinstance(last, dict) else {}
    inputs = cmd.commandInputs
    tip_box.attach(cmd, CMD_ID)              # 'How to use this' + hover tips (0.13)
    has_design = fh.active_design() is not None
    sources = [SRC_STEP, SRC_COMP, SRC_FOLDER] if has_design else [SRC_STEP, SRC_FOLDER]
    _dropdown(inputs, ID_SRC, "Add from", sources, str(last.get("src", SRC_STEP)))
    inputs.addBoolValueInput(ID_FOLDER_BTN, "STEP folder", False, "", False).text = "Choose folder..."
    folder = inputs.addStringValueInput(ID_FOLDER, " ", "")
    folder.isReadOnly = True
    inputs.addBoolValueInput(ID_BROWSE, "STEP file", False, "", False).text = "Choose file..."
    f = inputs.addStringValueInput(ID_FILE, " ", "")
    f.isReadOnly = True
    comp = inputs.addSelectionInput(ID_COMP, "Component", "Click the part in the canvas or browser")
    comp.addSelectionFilter("Occurrences")
    comp.setSelectionLimits(0, 1)
    inputs.addStringValueInput(ID_NAME, "Name", "").tooltip = "What the vendor calls it, e.g. NEO Brushless Motor V1.1"
    _dropdown(inputs, ID_VENDOR, "Vendor", [v.name for v in lib["vendors"]], str(last.get("vendor", "")))
    inputs.addStringValueInput(ID_PN, "Part # (SKU)", "").tooltip = "Copy it from the product page"
    _dropdown(inputs, ID_CAT, "Category", lib["categories"], str(last.get("category", "")))
    inputs.addStringValueInput(ID_PRICE, "Price ($)", "")
    inputs.addStringValueInput(ID_URL, "Product link", "")
    inputs.addStringValueInput(ID_NOTES, "Notes", "").tooltip = "Optional, e.g. 'use with 1/2in hex'"
    inputs.addStringValueInput(ID_BY, "Your initials", str(last.get("by", ""))).tooltip = \
        "Initials only - no full names"
    diff = inputs.addBoolValueInput(ID_DIFF, "It's a different part", True, "", False)
    diff.tooltip = "Only tick this if the look-alike part in the library really isn't the same product"
    diff.isVisible = False
    inputs.addTextBoxCommandInput(ID_CHECK, "", "", 6, True)
    _show_source(inputs)
    _refresh_check(inputs)
    for event, base, func, label in (
        (cmd.inputChanged, adsk.core.InputChangedEventHandler, _on_input_changed, "input"),
        (cmd.validateInputs, adsk.core.ValidateInputsEventHandler, _on_validate, "validate"),
        (cmd.execute, adsk.core.CommandEventHandler, _on_execute, "OK"),
        (cmd.destroy, adsk.core.CommandEventHandler, _on_destroy, "close"),
    ):
        event.add(fh.make_handler(base, func, f"Add to COTS: {label}", HANDLER_GROUP))


def _show_source(inputs) -> None:
    src = _text(inputs, ID_SRC)
    step, batch = src == SRC_STEP, src == SRC_FOLDER
    inputs.itemById(ID_BROWSE).isVisible = step
    inputs.itemById(ID_FILE).isVisible = step
    inputs.itemById(ID_COMP).isVisible = src == SRC_COMP
    inputs.itemById(ID_FOLDER_BTN).isVisible = batch
    inputs.itemById(ID_FOLDER).isVisible = batch
    for input_id in SINGLE_ONLY:                      # a batch takes these from the parts list
        inputs.itemById(input_id).isVisible = not batch
    if batch:
        inputs.itemById(ID_DIFF).isVisible = False


# --- Batch: a folder of STEP files + a parts list ---------------------------
def _parts_list_for(folder: str):
    """The folder's own .csv parts list if it has one, else Gusset's starter list. -> (path, infos, problems)"""
    own = [f for f in sorted(os.listdir(folder)) if f.lower().endswith(".csv") and f != REPORT_NAME]
    path = os.path.join(folder, own[0]) if own else STARTER_LIST
    with open(path, "r", encoding="utf-8-sig") as handle:
        infos, problems = cc.parse_parts_list(handle.read())
    return path, infos, problems


def _plan_batch(inputs) -> None:
    folder = str(_state.get("folder", ""))
    box = adsk.core.TextBoxCommandInput.cast(inputs.itemById(ID_CHECK))
    _state["ok"], _state["batch"] = False, None
    if not folder:
        box.formattedText = "&#10007; Choose the folder the STEP files were saved in."
        return
    lib = _state["lib"]
    try:
        list_path, infos, problems = _parts_list_for(folder)
        files = cc.drop_repeat_downloads({f: os.path.getsize(os.path.join(folder, f)) for f in os.listdir(folder)
                                          if os.path.isfile(os.path.join(folder, f))})
    except (OSError, ValueError) as exc:
        box.formattedText = f'<span style="color:#d9534f">&#10007; {fh.safe_text(str(exc))}</span>'
        return
    by = _text(inputs, ID_BY)
    for info in infos:
        info.added_by, info.added_on = by, datetime.date.today().isoformat()
        if not info.url:
            info.url = cc.vendor_link(info, lib["vendors"])
    rows = cc.plan_import(infos, files, cots_browser.catalog(), lib["vendors"], lib["categories"])
    extra = cc.unmatched_steps(rows, files)
    _state["batch"] = {"folder": folder, "rows": rows, "list": list_path}
    counts = cc.import_summary(rows, extra)
    ready = [r for r in rows if r.status == cc.READY]
    _state["ok"] = bool(ready)
    lines = [f"Parts list: <b>{fh.safe_text(os.path.basename(list_path))}</b> ({len(infos)} parts)"]
    lines += [f'<span style="color:#d9534f">&#10007; {fh.safe_text(p)}</span>' for p in problems]
    colors = {cc.READY: "#3c9d4e", cc.IN_LIBRARY: "#888888", cc.NO_STEP: "#888888"}
    for status, n in counts.items():
        lines.append(f'<span style="color:{colors.get(status, "#c98a00")}">{n} {fh.safe_text(status)}</span>')
    for r in rows:
        if r.status in (cc.NEEDS_LOOK, cc.TWO_FILES, cc.NO_PN):
            lines.append(f'<span style="color:#c98a00">! {fh.safe_text(r.info.name)}: '
                         f'{fh.safe_text(r.message)}</span>')
    for f in extra[:5]:
        lines.append(f'<span style="color:#c98a00">! {fh.safe_text(f)} isn\'t in the parts list - '
                     'add it on its own.</span>')
    if ready:
        lines.append(f"OK adds the {len(ready)} ready part(s) - about {len(ready) * 8 // 60 + 1} min.")
    box.formattedText = "<br>".join(lines)
    _log.info("Batch plan for %s: %s", folder, counts)


def _info(inputs) -> cc.CotsInfo:
    return cc.CotsInfo(name=_text(inputs, ID_NAME), vendor=_text(inputs, ID_VENDOR), vendor_pn=_text(inputs, ID_PN),
                       category=_text(inputs, ID_CAT), price=_text(inputs, ID_PRICE).replace("$", ""),
                       url=_text(inputs, ID_URL), notes=_text(inputs, ID_NOTES), added_by=_text(inputs, ID_BY),
                       added_on=datetime.date.today().isoformat())


def _source_ok(inputs) -> bool:
    if _text(inputs, ID_SRC) == SRC_STEP:
        return bool(_state.get("step"))
    return inputs.itemById(ID_COMP).selectionCount == 1


def _refresh_check(inputs) -> cc.Check:
    if _text(inputs, ID_SRC) == SRC_FOLDER:
        _plan_batch(inputs)
        return cc.Check() if _state.get("ok") else cc.Check(errors=["nothing ready"])
    lib = _state["lib"]
    info = _info(inputs)
    existing = cots_browser.catalog()
    diff = adsk.core.BoolValueCommandInput.cast(inputs.itemById(ID_DIFF))
    look_alikes = cc.similar_items(info, existing, lib["vendors"]) if info.name else []
    diff.isVisible = bool(look_alikes)              # only offered when there's a possible duplicate
    if not look_alikes:
        diff.value = False
    check = cc.check_info(info, existing, lib["vendors"], lib["categories"], different_part=diff.value)
    if look_alikes:
        _log.info("Possible duplicate of %s (ticked different: %s)", [i.file_name for i in look_alikes], diff.value)
    if not _source_ok(inputs):
        check.errors.insert(0, "Choose the STEP file." if _text(inputs, ID_SRC) == SRC_STEP
                            else "Click the component to add.")
    lines = [f'<span style="color:#d9534f">&#10007; {fh.safe_text(e)}</span>' for e in check.errors]
    lines += [f'<span style="color:#c98a00">! {fh.safe_text(w)}</span>' for w in check.warnings]
    if check.ok:
        info = _info(inputs)
        lines.insert(0, f'<span style="color:#3c9d4e">&#10003; Saves as {fh.safe_text(info.category)}/'
                        f'{fh.safe_text(info.vendor)}/{fh.safe_text(cc.part_file_name(info.vendor_pn, info.name))}'
                        f'</span>')
    adsk.core.TextBoxCommandInput.cast(inputs.itemById(ID_CHECK)).formattedText = "<br>".join(lines)
    _state["ok"] = check.ok
    return check


def _fill_from_guess(inputs, text: str) -> None:
    """Pre-fill empty boxes from a file/component name like 'REV-21-1650 NEO' or 'am-4255.step'."""
    guess = cc.guess_from_file_name(text, _state["lib"]["vendors"])
    if not _text(inputs, ID_NAME):
        _set(inputs, ID_NAME, guess.name if guess.vendor_pn else text)
    if guess.vendor_pn and not _text(inputs, ID_PN):
        _set(inputs, ID_PN, guess.vendor_pn)
        vendor = adsk.core.DropDownCommandInput.cast(inputs.itemById(ID_VENDOR))
        for i in range(vendor.listItems.count):
            if vendor.listItems.item(i).name == guess.vendor:
                vendor.listItems.item(i).isSelected = True


def _on_input_changed(args: adsk.core.InputChangedEventArgs) -> None:
    inputs = fh.all_inputs(args)
    changed = args.input.id
    if changed == ID_SRC:
        _show_source(inputs)
    elif changed == ID_BROWSE:
        _, ui = fh.app_ui()
        dlg = ui.createFileDialog()
        dlg.title = "Choose the vendor's STEP file"
        dlg.filter = "STEP files (*.step;*.stp);;All files (*.*)"
        if dlg.showOpen() == adsk.core.DialogResults.DialogOK:
            _state["step"] = dlg.filename
            _set(inputs, ID_FILE, os.path.basename(dlg.filename))
            _fill_from_guess(inputs, os.path.splitext(os.path.basename(dlg.filename))[0])
            _log.info("STEP file chosen: %s", dlg.filename)
    elif changed == ID_FOLDER_BTN:
        _, ui = fh.app_ui()
        dlg = ui.createFolderDialog()
        dlg.title = "Choose the folder with the vendors' STEP files"
        if dlg.showDialog() == adsk.core.DialogResults.DialogOK:
            _state["folder"] = dlg.folder
            _set(inputs, ID_FOLDER, dlg.folder)
            _log.info("STEP folder chosen: %s", dlg.folder)
    elif changed == ID_COMP:
        sel = inputs.itemById(ID_COMP)
        if sel.selectionCount:
            _fill_from_guess(inputs, sel.selection(0).entity.component.name)
    _refresh_check(inputs)


def _on_validate(args: adsk.core.ValidateInputsEventArgs) -> None:
    args.areInputsValid = bool(_state.get("ok"))


def _on_execute(args: adsk.core.CommandEventArgs) -> None:
    inputs = fh.all_inputs(args)
    if not _refresh_check(inputs).ok:
        return
    if _text(inputs, ID_SRC) == SRC_FOLDER:
        settings.save_state(config.ADDIN_DIR, cots_add={"src": SRC_FOLDER, "by": _text(inputs, ID_BY)})
        _pending.append({"batch": _state["batch"]})
        _start_saving()
        return
    info = _info(inputs)
    job = {"info": info, "step": "", "occ": None}
    if _text(inputs, ID_SRC) == SRC_STEP:
        job["step"] = str(_state.get("step", ""))
    else:
        job["occ"] = inputs.itemById(ID_COMP).selection(0).entity
    settings.save_state(config.ADDIN_DIR, cots_add={"src": _text(inputs, ID_SRC), "vendor": info.vendor,
                                                    "category": info.category, "by": info.added_by})
    _pending.append(job)
    _log.info("Queued %s for the library", cc.part_file_name(info.vendor_pn, info.name))
    _start_saving()


def _start_saving() -> None:
    """
    Saving must happen after the dialog closes, so it's started with a custom event.
    0.13.2: Fusion answers 'refused' from inside the dialog but delivers the event
    anyway - the old code believed it, threw the part away and said to restart.
    Now the job stays queued and the signal is re-sent until it's handled.
    """
    _log.info("%d library job(s) waiting to save", len(_pending))
    fh.fire_until_handled(EVENT_ID, lambda: bool(_pending), "Add to Library")


def _on_destroy(args: adsk.core.CommandEventArgs) -> None:
    _state.clear()
    fh.release_handlers(HANDLER_GROUP)


def _on_save(args) -> None:
    """After the dialog closes: make the library file (saving isn't allowed inside a command)."""
    global _saving
    if not _pending or _saving:
        return
    why = fh.fusion_is_idle() or _other_tool_busy()
    if why:
        _log.debug("Library save waiting: %s", why)
        return                                    # fire_until_handled sends the signal again in a second
    _saving = True
    try:
        _save_jobs()
    finally:
        _saving = False


def _other_tool_busy() -> str:
    from . import linked_parts
    return "part files are being made" if linked_parts.busy else ""


def _save_jobs() -> None:
    _, ui = fh.app_ui()
    jobs = list(_pending)
    _pending.clear()
    lib = cots_browser.library_settings()
    for job in jobs:
        if "batch" in job:
            _run_batch(job["batch"], lib)
            continue
        info: cc.CotsInfo = job["info"]
        try:
            project = cots_browser.library_project(lib)
            if project is None:
                answer = ui.messageBox(f"There's no '{lib['project']}' project yet. Create it now?",
                                       "Gusset - Add to COTS Library",
                                       adsk.core.MessageBoxButtonTypes.YesNoButtonType)
                if answer != adsk.core.DialogResults.DialogYes:
                    return
                project = cl.make_project(lib["project"], lib["categories"], lib["vendors"])
            file_id = cl.add_part(info, project, step_path=job["step"], occurrence=job["occ"])
            name = cc.part_file_name(info.vendor_pn, info.name)
            item = cc.CatalogItem(file_id, name, info.category, info.vendor, info)
            cots_browser.add_to_catalog(item)
            ui.messageBox(f"Added to the library:\n\n{lib['project']} / {info.category} / {info.vendor} / {name}\n\n"
                          "It shows up in the COTS Library panel now (the picture can take a minute).",
                          "Gusset - Add to COTS Library")
        except fb.FeatureError as exc:
            ui.messageBox(str(exc), "Gusset - Add to COTS Library")
        except Exception:
            fh.report_error("Add to COTS Library: saving the part")


def _run_batch(batch: dict, lib: dict) -> None:
    """Add every READY row, one file at a time, with a progress bar you can cancel."""
    _, ui = fh.app_ui()
    project = cots_browser.library_project(lib)
    if project is None:
        project = cl.make_project(lib["project"], lib["categories"], lib["vendors"])
    rows = [r for r in batch["rows"] if r.status == cc.READY]
    progress = ui.createProgressDialog()
    progress.isCancelButtonShown = True
    progress.show("Gusset - adding parts to the library", "Starting...", 0, len(rows), 0)
    added, failed, started = [], [], time.time()
    try:
        for n, row in enumerate(rows):
            if progress.wasCancelled:
                _log.info("Batch import cancelled after %d part(s)", n)
                break
            progress.message = f"{n + 1} of {len(rows)}: {row.info.name}"
            progress.progressValue = n
            adsk.doEvents()
            try:
                # don't wait on each upload - they're all checked together at the end
                file_id = cl.add_part(row.info, project, step_path=os.path.join(batch["folder"], row.step),
                                      upload_wait=BATCH_UPLOAD_WAIT_S)
                cots_browser.add_to_catalog(cc.CatalogItem(file_id, cc.part_file_name(row.info.vendor_pn,
                                                                                      row.info.name),
                                                           row.info.category, row.info.vendor, row.info))
                row.status, row.message, row.file_id = "added", "", file_id
                added.append(row)
            except Exception as exc:                  # one bad STEP file shouldn't stop the rest
                row.status, row.message = "failed", str(exc)
                failed.append(row)
                _log.warning("Batch: %s failed: %s", row.info.vendor_pn, exc)
    finally:
        progress.hide()
    # Uploads finish in the background (Fusion can't report them done while this code runs).
    report = os.path.join(batch["folder"], REPORT_NAME)
    try:
        import csv
        with open(report, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Part #", "Name", "Category", "Vendor", "Result", "STEP file", "Note"])
            for r in batch["rows"]:
                writer.writerow([r.info.vendor_pn, r.info.name, r.info.category, r.info.vendor, r.status,
                                 r.step, r.message])
    except OSError as exc:
        _log.warning("Couldn't write %s: %s", report, exc)
    _log.info("Batch import: %d added, %d failed (%.0fs)", len(added), len(failed), time.time() - started)
    text = f"Added {len(added)} part(s) to {lib['project']} in {(time.time() - started) / 60:.1f} min."
    text += "\nUploads finish in the background - press Refresh in the COTS panel in a minute or two."
    if failed:
        text += "\n\nThese didn't work:\n" + "\n".join(f"- {r.info.name}: {r.message}" for r in failed[:8])
    text += f"\n\nThe full list is in '{REPORT_NAME}' in the STEP folder."
    ui.messageBox(text, "Gusset - Add to COTS Library")
