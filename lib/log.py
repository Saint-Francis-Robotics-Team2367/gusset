"""
log.py - one logging setup for the whole add-in.

Every message goes to three places:
  1. Fusion's TEXT COMMANDS window (Utilities > Text Commands, or Ctrl/Cmd+Alt+C)
  2. logs/gusset.log next to the add-in (rotates at 1 MB, keeps 3 old files)
  3. stdout, which shows up in the VS Code debug console while debugging

Usage in any module:
    from ..lib import log as pclog
    _log = pclog.get_logger("my_tool")
    _log.info("Renamed %d parts", count)
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Optional

LOGGER_NAME = "gusset"
_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
_log_file: Optional[str] = None


class _FusionConsoleHandler(logging.Handler):
    """Sends log lines to Fusion's Text Commands window. Never raises."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            import adsk.core  # only available inside Fusion

            if record.levelno >= logging.ERROR:
                level = adsk.core.LogLevels.ErrorLogLevel
            elif record.levelno >= logging.WARNING:
                level = adsk.core.LogLevels.WarningLogLevel
            else:
                level = adsk.core.LogLevels.InfoLogLevel
            adsk.core.Application.get().log(self.format(record), level, adsk.core.LogTypes.ConsoleLogType)
        except Exception:
            pass  # logging must never crash Fusion


def setup(log_dir: str, debug: bool = False) -> str:
    """Configure logging. Safe to call again (e.g. when the add-in reloads)."""
    global _log_file
    logger = logging.getLogger(LOGGER_NAME)
    shutdown()  # remove handlers from a previous run so lines aren't doubled

    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.propagate = False
    formatter = logging.Formatter(_FORMAT, datefmt="%H:%M:%S")

    try:
        os.makedirs(log_dir, exist_ok=True)
        _log_file = os.path.join(log_dir, "gusset.log")
        file_handler = RotatingFileHandler(_log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError as exc:
        _log_file = None
        print(f"[Gusset] Could not open log file in {log_dir}: {exc}")

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    logger.addHandler(stream)

    fusion = _FusionConsoleHandler()
    fusion.setFormatter(logging.Formatter("[Gusset] %(levelname)s %(message)s"))
    logger.addHandler(fusion)

    logger.info("Logging started (debug=%s) -> %s", debug, _log_file or "no file")
    return _log_file or ""


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{name}")


def log_file_path() -> str:
    return _log_file or "(log file unavailable)"


def shutdown() -> None:
    """Close handlers so Windows releases the log file when the add-in stops."""
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        try:
            handler.close()
        finally:
            logger.removeHandler(handler)
