"""github_deeplink_service.py — build a pre-filled "new issue" URL (no login needed).

The user opens the link in their browser, is logged into GitHub with their own
account, sees exactly what will be posted and submits it themselves. Nothing
leaves the instance automatically on this path.

GitHub *issue forms* (.github/ISSUE_TEMPLATE/*.yml) ignore the generic ``body``
query parameter — prefill only works through query parameters named after the
form's field ``id``s. So each template gets an explicit field mapping here:

    bug.yml   → title, version, component, steps, logs
    idea.yml  → title, description

Interface
---------
build_issue_url(title, body, template="bug.yml", component="") -> str
"""
import logging
from urllib.parse import urlencode

from constants import GITHUB_ISSUES_REPO
from app.services.report_sanitizer import sanitize
from app.services.version_service import version_info

log = logging.getLogger("dashboard.services.github_deeplink")

# Browsers and GitHub cope with ~8 kB URLs; keep a safety margin.
_MAX_BODY_CHARS = 5000
_MAX_TITLE_CHARS = 120
_TEMPLATES = {"bug.yml", "idea.yml"}


def build_issue_url(title: str, body: str, template: str = "bug.yml", component: str = "") -> str:
    """Return https://github.com/<repo>/issues/new?template=…&<field-ids> with sanitized values."""
    if template not in _TEMPLATES:
        log.warning("unknown template %r — falling back to bug.yml", template)
        template = "bug.yml"
    clean_title, t_stats = sanitize((title or "").strip()[:_MAX_TITLE_CHARS])
    clean_body, b_stats = sanitize((body or "").strip())
    clean_comp, _ = sanitize((component or "").strip()[:200])
    if len(clean_body) > _MAX_BODY_CHARS:
        clean_body = clean_body[:_MAX_BODY_CHARS] + "\n\n… (truncated for URL length)"
    vi = version_info()
    params = {"template": template, "title": clean_title or ("Bug report" if template == "bug.yml" else "Idea")}
    if template == "bug.yml":
        params["version"] = f"{vi.get('version')} ({vi.get('channel')})"
        if clean_comp:
            params["component"] = clean_comp
        params["steps"] = clean_body
    else:  # idea.yml
        params["description"] = clean_body
    url = f"https://github.com/{GITHUB_ISSUES_REPO}/issues/new?{urlencode(params)}"
    log.debug("deeplink built: template=%s %d chars, sanitized title=%s body=%s",
              template, len(url), t_stats, b_stats)
    return url
