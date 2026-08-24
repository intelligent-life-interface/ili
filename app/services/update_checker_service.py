"""GitHub-based update checker for ili.

Checks for new releases on GitHub (Toa1984/ili-public), compares with
current version, and caches the result. Respects ILI_UPDATE_CHANNEL (stable/beta)
and ILI_UPDATE_CHECK environment variables.

Stable channel: uses releases/latest (never includes prereleases)
Beta channel: uses first release (may be prerelease)
ILI_UPDATE_CHECK=off disables checking (privacy)
"""
import logging
import os
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Optional

import httpx

from app.services.version_service import read_version

log = logging.getLogger("dashboard.services.update_checker")

_GITHUB_REPO = "Toa1984/ili-public"
_GITHUB_RELEASES_API = f"https://api.github.com/repos/{_GITHUB_REPO}/releases"
_CACHE_DURATION = timedelta(hours=1)
_HTTP_TIMEOUT = 10

# Global cache state: (timestamp, result) to avoid repeated API calls
_cache_state: Optional[tuple[datetime, dict]] = None


def _is_cache_valid() -> bool:
    """Check if cached result is still fresh."""
    global _cache_state
    if _cache_state is None:
        return False
    timestamp, _ = _cache_state
    return datetime.utcnow() - timestamp < _CACHE_DURATION


def _get_check_enabled() -> bool:
    """Check if update checking is enabled (default: yes; set ILI_UPDATE_CHECK=off to disable)."""
    check = (os.environ.get("ILI_UPDATE_CHECK") or "").strip().lower()
    return check != "off"


def _get_channel() -> str:
    """Get update channel: stable or beta (default: stable)."""
    channel = (os.environ.get("ILI_UPDATE_CHANNEL") or "stable").strip().lower()
    if channel not in ("stable", "beta"):
        log.warning("ILI_UPDATE_CHANNEL=%r unknown — falling back to 'stable'", channel)
        channel = "stable"
    return channel


def _fetch_stable_release() -> Optional[dict]:
    """Fetch latest stable release (never prerelease)."""
    try:
        log.debug("Fetching latest stable release from %s", _GITHUB_RELEASES_API)
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            resp = client.get(f"{_GITHUB_RELEASES_API}/latest")
            resp.raise_for_status()
        data = resp.json()
        if data.get("prerelease"):
            log.info("Latest release is prerelease — not suitable for stable channel")
            return None
        return data
    except httpx.HTTPError as e:
        log.warning("Failed to fetch latest release: %s", e)
        return None


def _fetch_beta_release() -> Optional[dict]:
    """Fetch first release (may be prerelease) for beta channel."""
    try:
        log.debug("Fetching releases list from %s (first entry for beta)", _GITHUB_RELEASES_API)
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            resp = client.get(_GITHUB_RELEASES_API, params={"per_page": 1})
            resp.raise_for_status()
        data = resp.json()
        if not data:
            log.info("No releases found")
            return None
        return data[0]
    except httpx.HTTPError as e:
        log.warning("Failed to fetch releases list: %s", e)
        return None


def _compare_versions(current: str, available: str) -> bool:
    """Return True if available version is newer.

    Simple semver comparison (strip beta/prerelease suffixes for comparison).
    Handles both '1.2.3' and '1.2.3-beta.1' format.
    """
    def normalize(v: str) -> tuple:
        # Extract major.minor.patch
        base = v.split("-")[0] if "-" in v else v
        try:
            return tuple(int(x) for x in base.split(".")[:3])
        except (ValueError, IndexError):
            return (0, 0, 0)

    return normalize(available) > normalize(current)


def _build_update_status(
    check_enabled: bool,
    current_version: str,
    channel: str,
    available_release: Optional[dict],
) -> dict:
    """Build the update status response."""
    if not check_enabled:
        return {
            "check_enabled": False,
            "current_version": current_version,
            "channel": channel,
            "update_available": False,
            "available_version": None,
            "available_url": None,
            "checked_at": datetime.utcnow().isoformat() + "Z",
        }

    if available_release is None:
        return {
            "check_enabled": True,
            "current_version": current_version,
            "channel": channel,
            "update_available": False,
            "available_version": None,
            "available_url": None,
            "checked_at": datetime.utcnow().isoformat() + "Z",
            "error": "Could not fetch release info from GitHub",
        }

    tag_name = available_release.get("tag_name", "").lstrip("v")
    is_prerelease = available_release.get("prerelease", False)
    html_url = available_release.get("html_url", "")
    update_available = _compare_versions(current_version, tag_name)

    return {
        "check_enabled": True,
        "current_version": current_version,
        "channel": channel,
        "available_version": tag_name,
        "available_url": html_url,
        "update_available": update_available,
        "is_prerelease": is_prerelease,
        "checked_at": datetime.utcnow().isoformat() + "Z",
    }


def get_update_status() -> dict:
    """Get current update status. Cached for up to 1 hour."""
    global _cache_state

    # Return cached result if valid
    if _is_cache_valid():
        _, cached_result = _cache_state
        log.debug("Returning cached update status")
        return cached_result

    # Fetch fresh status
    check_enabled = _get_check_enabled()
    current_version = read_version()
    channel = _get_channel()

    available_release = None
    if check_enabled:
        if channel == "stable":
            available_release = _fetch_stable_release()
        else:  # beta
            available_release = _fetch_beta_release()

    result = _build_update_status(check_enabled, current_version, channel, available_release)

    # Cache it
    _cache_state = (datetime.utcnow(), result)
    log.debug("Update status: current=%s, available=%s, update_available=%s",
              current_version, result.get("available_version"), result.get("update_available"))

    return result


def refresh_update_status() -> dict:
    """Force refresh of update status (bypasses cache)."""
    global _cache_state
    _cache_state = None
    return get_update_status()
