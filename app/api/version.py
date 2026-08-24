"""API router for version and update information.

Routes:
  GET /api/version — current version, commit, build date, channel
  GET /api/update-status — available update, channel, checked timestamp
"""
import logging
from fastapi import APIRouter
from app.services.version_service import version_info
from app.services.update_checker_service import get_update_status

log = logging.getLogger("dashboard.api.version")
router = APIRouter(tags=["version"])


@router.get("/api/version")
def get_version():
    """Current ili version, commit, build date, and update channel.

    Response: {"version": "0.1.0", "commit": "abc123", "build_date": "2026-08-23T12:34:56", "channel": "stable"}
    """
    return version_info()


@router.get("/api/update-status")
def get_updates():
    """Check for available updates.

    Response:
    {
      "check_enabled": true,
      "current_version": "0.1.0",
      "channel": "stable",
      "available_version": "0.1.1",
      "available_url": "https://github.com/Toa1984/ili-public/releases/tag/v0.1.1",
      "update_available": true,
      "is_prerelease": false,
      "checked_at": "2026-08-23T12:34:56Z"
    }

    If check_enabled is false (ILI_UPDATE_CHECK=off), returns current version but
    no available version (respects user privacy preference).
    """
    return get_update_status()
