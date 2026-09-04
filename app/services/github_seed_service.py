"""github_seed_service.py — Create GitHub issues for seed cards.

When a new ili instance is set up, its seed (idea) cards should automatically
create corresponding GitHub issues in Toa1984/ili-public so the crowd can see
what ideas are already available to work on.

Interface
---------
create_issue_for_card(card_id, title, description) -> dict  # returns {status, issue_url?, error?}
"""
import logging
import json
from typing import Optional

import httpx

from constants import GITHUB_ISSUES_REPO
from app.services import github_auth_service as auth

log = logging.getLogger("dashboard.services.github_seed")

_API = "https://api.github.com"
_TIMEOUT = 20.0


def _gh(method: str, path: str, token: str, body: dict) -> httpx.Response:
    """Make authenticated GitHub API request."""
    return httpx.request(method, f"{_API}{path}", json=body, timeout=_TIMEOUT, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ili-seed-cards",
    })


def create_issue_for_card(
    card_id: str,
    title: str,
    description: str = "",
    labels: Optional[list[str]] = None
) -> dict:
    """Create a GitHub issue for a seed card.

    Returns:
        {
            "status": "created" | "skipped" | "error",
            "issue_url": str (if created),
            "issue_number": int (if created),
            "error": str (if failed)
        }

    Args:
        card_id: unique card ID (stored in issue body for deduplication)
        title: issue title
        description: issue body (card description)
        labels: optional labels to add (e.g., ["idea", "seed"])
    """
    token = auth.get_token()
    if not token:
        log.debug("create_issue_for_card: skipped (not logged in)")
        return {"status": "skipped", "error": "no_github_auth"}

    if not title.strip():
        return {"status": "error", "error": "title_required"}

    labels = labels or ["idea", "seed"]

    # Include card_id in body for future deduplication
    body_text = description or ""
    if body_text and not body_text.endswith("\n"):
        body_text += "\n"
    body_text += f"\n<!-- ili seed-card: {card_id} -->"

    payload = {
        "title": title.strip(),
        "body": body_text,
        "labels": labels,
    }

    try:
        resp = _gh("POST", f"/repos/{GITHUB_ISSUES_REPO}/issues", token, payload)
        if resp.status_code in (200, 201):
            data = resp.json()
            issue_url = data.get("html_url", "")
            issue_number = data.get("number")
            log.info(
                "GitHub issue created for card %s: #%s (%s)",
                card_id, issue_number, issue_url
            )
            return {
                "status": "created",
                "issue_url": issue_url,
                "issue_number": issue_number,
            }
        else:
            error_msg = f"HTTP {resp.status_code}"
            try:
                error_data = resp.json()
                if "message" in error_data:
                    error_msg = error_data["message"]
            except Exception:
                pass
            log.error(
                "GitHub issue creation failed for card %s: %s",
                card_id, error_msg
            )
            return {"status": "error", "error": error_msg}
    except Exception as e:
        log.error("GitHub issue creation exception for card %s: %s", card_id, e, exc_info=True)
        return {"status": "error", "error": str(e)}
