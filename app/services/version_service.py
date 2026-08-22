"""Version information of the running ili instance.

Reads the VERSION file shipped in the image plus build metadata passed in via
environment (ILI_COMMIT / ILI_BUILD_DATE, set as build args by ili-update.sh).
Base for the update checker and the footer version display.
"""
import logging
import os
from functools import lru_cache
from pathlib import Path

log = logging.getLogger("dashboard.services.version")

_VERSION_FILE = Path(__file__).resolve().parents[2] / "VERSION"
_FALLBACK = "0.0.0-unknown"


@lru_cache(maxsize=1)
def read_version() -> str:
    """Return the semver string from VERSION (cached; fallback if missing)."""
    try:
        version = _VERSION_FILE.read_text(encoding="utf-8").strip()
        log.debug("VERSION read from %s: %s", _VERSION_FILE, version)
        return version or _FALLBACK
    except OSError as e:
        log.warning("VERSION file not readable (%s): %s — using %s", _VERSION_FILE, e, _FALLBACK)
        return _FALLBACK


def version_info() -> dict:
    """Full version payload for GET /api/version."""
    channel = (os.environ.get("ILI_UPDATE_CHANNEL") or "stable").strip().lower()
    if channel not in ("stable", "beta"):
        log.warning("ILI_UPDATE_CHANNEL=%r unknown — falling back to 'stable'", channel)
        channel = "stable"
    info = {
        "version": read_version(),
        "commit": os.environ.get("ILI_COMMIT") or "unknown",
        "build_date": os.environ.get("ILI_BUILD_DATE") or "unknown",
        "channel": channel,
    }
    log.debug("version_info: %s", info)
    return info
