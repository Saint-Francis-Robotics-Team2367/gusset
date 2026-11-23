"""
error_core.py - turns a Python exception into something a student can read
(no Fusion imports; tested in tests/test_error_core.py).

    explain("COTS Library: inserting a part", exc, traceback_text)
      -> ErrorReport(title="Gusset couldn't finish inserting a part",
                     summary="Fusion couldn't find that file in the cloud ...",
                     hint="Press the round arrow in the COTS panel, then try again.",
                     details=<traceback with this laptop's user name removed>)

The full traceback is still logged and shown under "Technical details" - this
only adds a plain sentence on top.
"""

from __future__ import annotations

import os
import platform
import re
import urllib.parse
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class ErrorReport:
    title: str
    summary: str
    hint: str
    details: str
    tool: str = ""
    error_type: str = ""


# (matches type name or message, plain summary, what to try). First match wins.
_RULES: List[Tuple[str, str, str]] = [
    (r"invalid id|not found in the cloud|findFileById",
     "Fusion couldn't find that file in the cloud - it may have been moved, renamed or is still uploading.",
     "Press the round arrow in the COTS Library panel (or reopen the file), then try again."),
    (r"URLError|timed out|Name or service not known|nodename nor servname|getaddrinfo|ConnectionError|"
     r"Connection (reset|refused)|Network is unreachable",
     "Gusset couldn't reach the internet.",
     "Check the Wi-Fi, then try again. Everything else in Gusset still works offline."),
    (r"CERTIFICATE_VERIFY_FAILED|SSLError|SSL:",
     "This computer refused GitHub's security certificate, so the download stopped.",
     "Tell a mentor - the school network may block it. Nothing was changed."),
    (r"PermissionError|Permission denied|Operation not permitted|Access is denied",
     "Gusset wasn't allowed to save a file in that folder.",
     "Pick a folder in your Documents, or close the file if it's open in another program, then try again."),
    (r"FileNotFoundError|No such file or directory|cannot find the (file|path)",
     "A file Gusset needed wasn't where it expected.",
     "Try again. If it keeps happening, reinstall Gusset with the installer."),
    (r"No space left|disk full",
     "The computer's disk is full.",
     "Free up some space, then try again."),
    (r"read-?only|is not editable|ReadOnly",
     "That design (or part) can't be changed - it's read-only or opened from someone else's file.",
     "Open the part's own file, or save a copy you can edit."),
    (r"is not supported by this design type|Part design|DesignIntent",
     "This file is a Part design, which can only hold one component.",
     "Open an assembly (or make a new design and choose Assembly), then try again."),
    (r"Compute Failed|failed to compute|Geometry|BRep|profile",
     "Fusion couldn't build the shape with those settings.",
     "Try a slightly different size or selection. Undo anything half-made with Ctrl/Cmd+Z."),
    (r"JSONDecodeError|Expecting value|Expecting property name",
     "A Gusset settings file has a typo in it.",
     "Ask a mentor to check the team settings in GUSSET > Settings."),
    (r"MemoryError",
     "The computer ran out of memory.",
     "Save your work, close other programs (and other Fusion tabs), then try again."),
]

_DEFAULT = ("Something unexpected went wrong, so Gusset stopped before finishing.",
            "Try once more. If it happens again, click Report problem or send the log to a mentor.")


def split_context(context: str) -> Tuple[str, str]:
    """'COTS Library: inserting a part' -> ('COTS Library', 'inserting a part')."""
    tool, sep, action = (context or "").partition(":")
    if not sep:
        return "", context.strip()
    return tool.strip(), action.strip()


def title_for(context: str) -> str:
    tool, action = split_context(context)
    if not action:
        return "Gusset ran into a problem"
    action = action[0].lower() + action[1:]
    if action.endswith(" failed"):
        action = action[: -len(" failed")]
    return f"Gusset couldn't finish {action}"


def scrub(text: str, home: Optional[str] = None) -> str:
    """Hide this laptop's user name (student privacy) in paths: /Users/jane/... -> ~/..."""
    home = home if home is not None else os.path.expanduser("~")
    out = text or ""
    if home and len(home) > 3:
        out = out.replace(home, "~").replace(home.replace("\\", "/"), "~")
    out = re.sub(r"(/Users/|/home/)[^/\s'\"]+", r"\1<user>", out)
    out = re.sub(r"([A-Za-z]:\\Users\\)[^\\\s'\"]+", r"\1<user>", out)
    return out


def explain(context: str, exc: Optional[BaseException], details: str, home: Optional[str] = None) -> ErrorReport:
    name = type(exc).__name__ if exc is not None else ""
    message = str(exc) if exc is not None else ""
    haystack = f"{name} {message} {details[-2000:] if details else ''}"
    summary, hint = _DEFAULT
    for pattern, s, h in _RULES:
        if re.search(pattern, haystack, re.I):
            summary, hint = s, h
            break
    tool, _ = split_context(context)
    return ErrorReport(title_for(context), summary, hint, scrub(details, home), tool, name)


def plain_text(report: ErrorReport, version: str) -> str:
    """What 'Copy details' puts on the clipboard."""
    return (f"{report.title}\n{report.summary}\n\nGusset {version} on {platform.system()} {platform.release()}"
            f"\nTool: {report.tool or '-'}\n\n{report.details}")


def issue_url(repo: str, report: ErrorReport, version: str, max_len: int = 6000) -> str:
    """A pre-filled 'new issue' link. The student reads it and presses Submit themselves."""
    body = (f"**What I was doing:** (describe the steps)\n\n**Gusset:** {version}  \n"
            f"**Computer:** {platform.system()} {platform.release()}  \n**Tool:** {report.tool or '-'}\n\n"
            f"**Error:** {report.summary}\n\n```\n{report.details.strip()[-3000:]}\n```")
    query = urllib.parse.urlencode({"title": report.title, "body": body})
    url = f"https://github.com/{repo}/issues/new?{query}"
    return url[:max_len]
