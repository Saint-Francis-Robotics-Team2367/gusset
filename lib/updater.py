"""
updater.py - checks GitHub for a new Gusset, downloads it and installs it over
this copy (the plan and the checks are in update_core.py, tested).

Nothing here blocks Fusion: network work runs on a background thread, which
then pokes the main thread with a custom event (the way Fusion wants it).

    check(manual=False)   when Fusion starts (at most every 6 h) or from Settings
    install(release)      after the student says "Update now"
    undo_last_update()    Settings > Undo last update
"""

from __future__ import annotations

import io
import json
import os
import shutil
import ssl
import threading
import time
import urllib.request
import zipfile
from typing import Callable, Dict, Optional

import adsk.core

from .. import config
from . import log as gslog
from . import settings
from . import update_core as uc

_log = gslog.get_logger("updater")
EVENT_ID = "Gusset_UpdaterEvent"
MAX_ZIP_BYTES = 60 * 1024 * 1024
TIMEOUT_S = 15

_event = None
_handlers: list = []
_results: Dict[str, dict] = {}          # job id -> result, picked up on the main thread
_callbacks: Dict[str, Callable] = {}
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Networking (background thread only)
# ---------------------------------------------------------------------------
def _ssl_context() -> ssl.SSLContext:
    """
    Fusion's bundled Python sometimes can't find the computer's certificates (a
    known Mac issue). Try the normal store, then certifi, then the Mac/Linux system
    bundle. Verification is NEVER turned off.
    """
    ctx = ssl.create_default_context()
    if ctx.cert_store_stats().get("x509_ca", 0):
        return ctx
    try:
        import certifi  # type: ignore
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass
    for path in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt", "/private/etc/ssl/cert.pem"):
        if os.path.exists(path):
            return ssl.create_default_context(cafile=path)
    return ctx


def _get(url: str, limit: int = 2 * 1024 * 1024) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"Gusset/{config.VERSION}",
                                               "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S, context=_ssl_context()) as resp:
        data = resp.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"download is bigger than {limit // (1024 * 1024)} MB - refusing it")
    return data


def _run_job(job: str, work: Callable[[], dict], on_done: Callable[[dict], None]) -> None:
    """Run work() on a thread; on_done(result) later runs on Fusion's main thread."""
    with _lock:
        _callbacks[job] = on_done

    def worker():
        try:
            result = work()
        except Exception as exc:                       # reported on the main thread
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        with _lock:
            _results[job] = result
        try:
            adsk.core.Application.get().fireCustomEvent(EVENT_ID, job)
        except Exception as exc:
            _log.warning("Couldn't hand the %s result to Fusion: %s", job, exc)

    threading.Thread(target=worker, daemon=True, name=f"gusset-{job}").start()


def _on_event(args) -> None:
    job = adsk.core.CustomEventArgs.cast(args).additionalInfo
    with _lock:
        result = _results.pop(job, None)
        callback = _callbacks.pop(job, None)
    if result is not None and callback is not None:
        callback(result)


# ---------------------------------------------------------------------------
# Checking
# ---------------------------------------------------------------------------
def is_developer_copy(install_dir: str = "") -> bool:
    """
    A git checkout (someone working ON Gusset). Never update it: installing a release
    would overwrite their uncommitted code. They update with git pull instead.
    """
    return os.path.isdir(os.path.join(install_dir or config.ADDIN_DIR, ".git"))


def status() -> dict:
    """What Settings shows: version, repo, last check, newest version seen."""
    state = settings.load_state(config.ADDIN_DIR)
    return {"version": config.VERSION, "repo": config.UPDATE_REPO, "repo_set": uc.repo_is_set(config.UPDATE_REPO),
            "last_check": state.get("update_last_check", 0), "latest": state.get("update_latest") or {},
            "backup": latest_backup() or "", "install_dir": config.ADDIN_DIR, "developer": is_developer_copy()}


def check(manual: bool = False, on_done: Optional[Callable[[dict], None]] = None) -> bool:
    """
    Look for a new version and fresh team settings. Returns False if it didn't
    even start (no repo yet, or not due). on_done(result) gets
    {"ok", "release"?: dict, "newer": bool, "team_changed": bool, "error"?: str}.
    """
    if not uc.repo_is_set(config.UPDATE_REPO):
        _log.info("Updates aren't set up yet (config.UPDATE_REPO = %r)", config.UPDATE_REPO)
        if on_done:
            on_done({"ok": False, "error": "Updates aren't set up yet - a mentor sets the GitHub repo."})
        return False
    state = settings.load_state(config.ADDIN_DIR)
    if not manual and not uc.due_for_check(state.get("update_last_check", 0), time.time()):
        _log.debug("Update check not due yet")
        return False
    repo, branch = config.UPDATE_REPO, config.UPDATE_BRANCH

    def work() -> dict:
        started = time.time()
        release = uc.parse_latest(_get(uc.latest_url(repo, branch)).decode("utf-8"))
        team_text = ""
        try:
            team_text = _get(uc.team_settings_url(repo, branch)).decode("utf-8")
        except Exception as exc:                        # optional file - updates still work without it
            _log.info("No team settings on GitHub (%s)", exc)
        return {"ok": True, "release": release.__dict__, "team_text": team_text,
                "seconds": round(time.time() - started, 1)}

    def done(result: dict) -> None:
        settings.save_state(config.ADDIN_DIR, update_last_check=time.time())
        if result.get("ok"):
            rel = result["release"]
            result["newer"] = uc.is_newer(rel["version"], config.VERSION)
            settings.save_state(config.ADDIN_DIR, update_latest=rel)
            result["team_changed"] = False
            if result.get("team_text"):
                try:
                    result["team_changed"] = settings.write_team_settings(config.ADDIN_DIR, result["team_text"])
                except Exception as exc:
                    _log.warning("Team settings on GitHub aren't valid JSON (%s) - keeping the old ones", exc)
            _log.info("Update check: newest %s, have %s (%ss)%s", rel["version"], config.VERSION,
                      result.get("seconds"), " - team settings changed" if result["team_changed"] else "")
        else:
            _log.info("Update check failed: %s", result.get("error"))
        if on_done:
            on_done(result)

    _log.info("Checking %s for updates%s", repo, " (asked from Settings)" if manual else "")
    _run_job("check", work, done)
    return True


# ---------------------------------------------------------------------------
# Installing
# ---------------------------------------------------------------------------
def _code_files(folder: str):
    """Relative paths of this install's code (everything but PRESERVE)."""
    for dirpath, dirnames, filenames in os.walk(folder):
        rel_dir = os.path.relpath(dirpath, folder)
        top = rel_dir.split(os.sep)[0]
        if top in uc.PRESERVE_DIRS:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in uc.PRESERVE_DIRS]
        for f in filenames:
            rel = os.path.normpath(os.path.join(rel_dir, f))
            if rel not in uc.PRESERVE_FILES and not f.endswith(".pyc"):
                yield rel


def latest_backup() -> Optional[str]:
    base = os.path.join(config.ADDIN_DIR, "cache", "previous")
    if not os.path.isdir(base):
        return None
    versions = [d for d in os.listdir(base) if uc.parse_version(d)]
    return max(versions, key=uc.parse_version) if versions else None


def apply_zip(data: bytes, release: uc.Release, install_dir: str) -> int:
    """Check, back up and install. Returns the number of files written."""
    if uc.sha256_of(data) != release.sha256:
        raise ValueError("the download doesn't match its checksum (it may be damaged) - nothing was changed")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        root = uc.find_package_root(names)
        if root is None:
            raise ValueError("the download doesn't contain Gusset - nothing was changed")
        inside = uc.read_zip_version(zf.read(root + "config.py").decode("utf-8"))
        if inside != release.version:
            raise ValueError(f"the download says it's {inside}, not {release.version} - nothing was changed")
        files = uc.files_to_install(names, root)
        # 1. back up the code we're about to replace
        backup = os.path.join(install_dir, "cache", "previous", config.VERSION)
        if os.path.isdir(backup):
            shutil.rmtree(backup)
        for rel in _code_files(install_dir):
            dest = os.path.join(backup, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(os.path.join(install_dir, rel), dest)
        _log.info("Backed up %s to %s", config.VERSION, backup)
        # 2. write each new file next to its target, then swap it in
        for rel in files:
            dest = os.path.join(install_dir, *rel.split("/"))
            if rel == settings.TEAM_FILENAME and os.path.exists(dest):
                continue        # the copy from GitHub's last check is newer than the one inside the zip
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            tmp = dest + ".gusset-new"
            with open(tmp, "wb") as handle:
                handle.write(zf.read(root + rel))
            os.replace(tmp, dest)
    _log.info("Installed Gusset %s over %s: %d files", release.version, config.VERSION, len(files))
    return len(files)


def install(release: dict, on_done: Callable[[dict], None]) -> None:
    rel = uc.Release(**release)
    if is_developer_copy():
        _log.warning("Not installing %s over a git checkout - use git pull", rel.version)
        on_done({"ok": False, "error": "This copy of Gusset is a git folder (for working on Gusset) - "
                                      "update it with git pull instead."})
        return

    def work() -> dict:
        started = time.time()
        data = _get(rel.zip_url, MAX_ZIP_BYTES)
        count = apply_zip(data, rel, config.ADDIN_DIR)
        return {"ok": True, "files": count, "version": rel.version, "seconds": round(time.time() - started, 1)}

    def done(result: dict) -> None:
        if result.get("ok"):
            settings.save_state(config.ADDIN_DIR, updated_from=config.VERSION, updated_to=rel.version,
                                skip_version="")
        on_done(result)

    _log.info("Downloading Gusset %s from %s", rel.version, rel.zip_url)
    _run_job("install", work, done)


def undo_last_update() -> str:
    """Put back the code saved before the last update. Returns that version."""
    version = latest_backup()
    if not version:
        raise ValueError("there's no earlier version saved on this computer")
    backup = os.path.join(config.ADDIN_DIR, "cache", "previous", version)
    for rel in _code_files(backup):
        dest = os.path.join(config.ADDIN_DIR, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(os.path.join(backup, rel), dest)
    shutil.rmtree(backup)
    settings.save_state(config.ADDIN_DIR, skip_version=config.VERSION)    # don't offer the same one again
    _log.info("Undid the update: %s is back (restart Fusion)", version)
    return version


# ---------------------------------------------------------------------------
def start() -> None:
    global _event
    app = adsk.core.Application.get()
    try:
        app.unregisterCustomEvent(EVENT_ID)
    except Exception:
        pass
    _event = app.registerCustomEvent(EVENT_ID)

    class _Handler(adsk.core.CustomEventHandler):
        def notify(self, args):
            try:
                _on_event(args)
            except Exception:
                from . import fusion_helpers as fh
                fh.report_error("Updates: finishing the update check")

    handler = _Handler()
    _event.add(handler)
    _handlers.append(handler)


def stop() -> None:
    try:
        adsk.core.Application.get().unregisterCustomEvent(EVENT_ID)
    except Exception:
        pass
    _handlers.clear()


def startup_check() -> None:
    """When Gusset starts: check (if due and switched on) and offer the update."""
    if not settings.read_settings(config.ADDIN_DIR).get("check_updates", True):
        _log.info("Update checks are off on this computer (Settings)")
        return
    if is_developer_copy():
        _log.info("Developer copy (git checkout) - no update offers; use git pull")
        return

    def done(result: dict) -> None:
        if not (result.get("ok") and result.get("newer")):
            return
        rel = result["release"]
        if settings.load_state(config.ADDIN_DIR).get("skip_version") == rel["version"]:
            _log.info("Skipping %s (the student chose Skip this version)", rel["version"])
            return
        from . import dialogs
        dialogs.show_update(rel)

    check(manual=False, on_done=done)


def json_status() -> str:
    return json.dumps(status())
