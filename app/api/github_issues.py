"""github_issues.py — HTTP surface for the GitHub feedback channel.

Routes (all under /api/github):
  GET    /auth/status          {logged_in, login, expires_at, client_id_set}
  POST   /auth/start           start device flow → {user_code, verification_uri, device_code, interval}
  POST   /auth/poll            {device_code} → {status: pending|slow_down|ok|expired|denied|error}
  DELETE /auth                 forget the stored token
  POST   /report               {kind, text, component?, title?} → create issue / comment
  POST   /report/preview       same body → {title, body, sanitized}  (nothing is sent)
  GET    /deeplink?title&body  → {url}  pre-filled issue form, no login needed
  GET    /reports              last 20 audit-log entries (what this instance sent)

The token never leaves the server: status() omits it, logs only print counts.
"""
import logging

from fastapi import APIRouter, HTTPException

from app.services import github_auth_service as auth
from app.services import github_issue_service as issues
from app.services.github_deeplink_service import build_issue_url

log = logging.getLogger("dashboard.api.github_issues")
router = APIRouter(prefix="/api/github", tags=["github"])

_KINDS = {"frontend", "manual"}   # "backend" is produced server-side only


@router.get("/auth/status")
def auth_status():
    return auth.status()


@router.post("/auth/start")
def auth_start():
    try:
        return auth.start()
    except RuntimeError as e:
        log.warning("device flow start failed: %s", e)
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/auth/poll")
def auth_poll(body: dict):
    return auth.poll((body.get("device_code") or "").strip())


@router.delete("/auth")
def auth_logout():
    auth.logout()
    return {"ok": True}


def _validated(body: dict) -> tuple[str, str, str, str]:
    kind = (body.get("kind") or "").strip()
    if kind not in _KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {sorted(_KINDS)}")
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text missing")
    return kind, text[:8000], (body.get("component") or "").strip()[:200], (body.get("title") or "").strip()[:120]


@router.post("/report/preview")
def report_preview(body: dict):
    kind, text, component, title = _validated(body)
    return issues.preview(kind, text, component, title)


@router.post("/report")
def report(body: dict):
    kind, text, component, title = _validated(body)
    log.debug("report request kind=%s component=%s len=%d", kind, component, len(text))
    result = issues.report(kind, text, component, title=title)
    if result["status"] == "not_logged_in":
        raise HTTPException(status_code=401, detail="not logged in to GitHub")
    if result["status"] == "throttled":
        raise HTTPException(status_code=429, detail="daily report limit reached")
    if result["status"] == "error":
        raise HTTPException(status_code=502, detail=result.get("error", "GitHub error"))
    return result


@router.get("/deeplink")
def deeplink(title: str = "", body: str = "", template: str = "bug.yml", component: str = ""):
    return {"url": build_issue_url(title, body, template=template, component=component)}


@router.get("/reports")
def reports():
    return {"reports": issues.recent(20)}
