"""github_issue_service.py — send sanitized bug reports / card exports to GitHub.

Privacy contract (see docs/GITHUB-REPORTING.md):
* Every text passes report_sanitizer.sanitize() — no paths, IPs, hosts,
  e-mails, tokens.
* Auto reports carry only technical data: ili version info, component
  (route/module), exception type, message, traceback frames inside app/.
  Never request bodies, headers, query strings or board/card contents.
* Card contents leave the instance ONLY via an explicit "export as issue"
  click (kind="manual"), after the user saw the sanitized preview.
* Everything that was sent is appended to GITHUB_REPORTS_LOG so the user can
  audit it locally at any time.

De-duplication: error_hash → issue number in GITHUB_ISSUES_STATE_FILE. A
repeat of a known error adds a short comment ("+1, version …") instead of a
new issue. Throttle: GITHUB_REPORTS_PER_DAY new issues/comments per day.

Interface
---------
build_payload(kind, text, component="", exc=None) -> dict
preview(kind, text, component="")                 -> dict   # what *would* be sent
report(kind, text, component="", exc=None, title="", labels=()) -> dict
recent(limit=20)                                   -> list[dict]
"""
import hashlib
import json
import logging
import time
import traceback
from datetime import date, datetime

import httpx

from constants import (GITHUB_ISSUES_REPO, GITHUB_ISSUES_STATE_FILE,
                       GITHUB_REPORTS_LOG, GITHUB_REPORTS_PER_DAY)
from app.services import github_auth_service as auth
from app.services.report_sanitizer import sanitize
from app.services.version_service import version_info
from app.storage.atomic_write import write_json_atomic

log = logging.getLogger("dashboard.services.github_issue")

_API = "https://api.github.com"
_TIMEOUT = 20.0
_MAX_BODY = 6000
_LABELS = {"backend": ["auto-report", "backend"],
           "frontend": ["auto-report", "frontend"],
           "manual": ["from-instance"]}


# ----------------------------------------------------------------- state --

def _load_state() -> dict:
    if not GITHUB_ISSUES_STATE_FILE.exists():
        return {"issues": {}, "day": "", "count": 0}
    try:
        return json.loads(GITHUB_ISSUES_STATE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        log.error("github_issues.json unreadable: %s", exc)
        return {"issues": {}, "day": "", "count": 0}


def _save_state(st: dict) -> None:
    write_json_atomic(GITHUB_ISSUES_STATE_FILE, st)


def _throttle_ok(st: dict) -> bool:
    today = date.today().isoformat()
    if st.get("day") != today:
        st["day"], st["count"] = today, 0
    if st["count"] >= GITHUB_REPORTS_PER_DAY:
        log.warning("GitHub report throttled: %d/%d today", st["count"], GITHUB_REPORTS_PER_DAY)
        return False
    return True


def _audit(entry: dict) -> None:
    """Append what was sent to the local audit log (the user's own record)."""
    try:
        GITHUB_REPORTS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with GITHUB_REPORTS_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        log.error("audit log write failed: %s", exc)


def recent(limit: int = 20) -> list[dict]:
    if not GITHUB_REPORTS_LOG.exists():
        return []
    try:
        lines = GITHUB_REPORTS_LOG.read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        log.error("audit log read failed: %s", exc)
        return []
    out = []
    for line in reversed(lines[-limit:]):
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


# --------------------------------------------------------------- payload --

def _app_frames(exc: BaseException) -> str:
    """Traceback limited to frames inside app/ — file names only, no absolute paths."""
    frames = []
    for fr in traceback.extract_tb(exc.__traceback__):
        if "/app/" in fr.filename or fr.filename.startswith("app/"):
            short = fr.filename.split("/app/")[-1]
            frames.append(f"app/{short}:{fr.lineno} in {fr.name}")
    return "\n".join(frames[-8:])


def build_payload(kind: str, text: str, component: str = "", exc: BaseException | None = None) -> dict:
    """Assemble the technical-only report and sanitize it."""
    vi = version_info()
    exc_type = type(exc).__name__ if exc else ""
    raw_msg = text if text else (str(exc) if exc else "")
    clean_msg, s1 = sanitize(raw_msg)
    clean_comp, s2 = sanitize(component or "")
    frames = _app_frames(exc) if exc else ""
    clean_frames, s3 = sanitize(frames)
    hash_src = "|".join([kind, exc_type, clean_comp, "\n".join(clean_frames.splitlines()[-3:]),
                         clean_msg[:120] if kind != "backend" else ""])
    error_hash = hashlib.sha256(hash_src.encode("utf-8")).hexdigest()[:16]
    stats = {}
    for s in (s1, s2, s3):
        for k, v in s.items():
            stats[k] = stats.get(k, 0) + v
    payload = {
        "kind": kind,
        "error_hash": error_hash,
        "version": vi,
        "component": clean_comp,
        "exception": exc_type,
        "message": clean_msg[:_MAX_BODY],
        "frames": clean_frames,
        "sanitized": stats,
    }
    log.debug("payload built kind=%s hash=%s comp=%s sanitized=%s", kind, error_hash, clean_comp, stats)
    return payload


def _render(payload: dict, title: str = "") -> tuple[str, str]:
    v = payload["version"]
    if not title:
        head = payload["exception"] or payload["message"].splitlines()[0][:80] if payload["message"] else "Report"
        title = f"[{payload['kind']}] {head}"[:120]
    parts = [
        f"**Kind:** {payload['kind']}  ·  **ili version:** {v.get('version')} "
        f"({v.get('channel')}, commit `{v.get('commit') or '?'}`)",
        f"**Component:** `{payload['component'] or '-'}`",
        f"**Error hash:** `{payload['error_hash']}`",
    ]
    if payload["exception"]:
        parts.append(f"**Exception:** `{payload['exception']}`")
    if payload["message"]:
        parts.append("```\n" + payload["message"] + "\n```")
    if payload["frames"]:
        parts.append("**Frames (app/ only):**\n```\n" + payload["frames"] + "\n```")
    parts.append("_Sent automatically by an ili instance — content sanitized "
                 f"({', '.join(f'{k}:{n}' for k, n in payload['sanitized'].items()) or 'nothing removed'})._")
    body = "\n\n".join(parts)
    return title, body[:_MAX_BODY]


def preview(kind: str, text: str, component: str = "", title: str = "") -> dict:
    payload = build_payload(kind, text, component)
    t, b = _render(payload, title)
    return {"title": t, "body": b, "error_hash": payload["error_hash"], "sanitized": payload["sanitized"]}


# ------------------------------------------------------------------ send --

def _gh(method: str, path: str, token: str, body: dict) -> httpx.Response:
    return httpx.request(method, f"{_API}{path}", json=body, timeout=_TIMEOUT, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ili",
    })


def report(kind: str, text: str, component: str = "", exc: BaseException | None = None,
           title: str = "", labels=()) -> dict:
    """Create an issue (or comment on the known one). Returns {status, issue_number?, url?}."""
    token = auth.get_token()
    if not token:
        log.debug("report skipped: not logged in")
        return {"status": "not_logged_in"}
    payload = build_payload(kind, text, component, exc)
    st = _load_state()
    if not _throttle_ok(st):
        _save_state(st)
        return {"status": "throttled"}
    t, b = _render(payload, title)
    known = st["issues"].get(payload["error_hash"]) if kind != "manual" else None
    try:
        if known:
            r = _gh("POST", f"/repos/{GITHUB_ISSUES_REPO}/issues/{known}/comments", token,
                    {"body": f"+1 — seen again on ili {payload['version'].get('version')} "
                             f"({payload['version'].get('channel')}), {datetime.now():%Y-%m-%d}."})
            ok = r.status_code == 201
            result = {"status": "commented" if ok else "error", "issue_number": known,
                      "url": f"https://github.com/{GITHUB_ISSUES_REPO}/issues/{known}"}
        else:
            r = _gh("POST", f"/repos/{GITHUB_ISSUES_REPO}/issues", token,
                    {"title": t, "body": b, "labels": list(labels) or _LABELS.get(kind, [])})
            ok = r.status_code == 201
            if ok:
                d = r.json()
                if kind != "manual":
                    st["issues"][payload["error_hash"]] = d["number"]
                result = {"status": "created", "issue_number": d["number"], "url": d.get("html_url")}
            else:
                result = {"status": "error"}
        if not ok:
            result["error"] = f"HTTP {r.status_code}: {r.text[:200]}"
            log.error("GitHub API failed: %s", result["error"])
        else:
            st["count"] = st.get("count", 0) + 1
    except Exception as e:
        log.error("GitHub report failed: %s", e)
        result = {"status": "error", "error": str(e)[:200]}
    _save_state(st)
    _audit({"ts": int(time.time()), "kind": kind, "hash": payload["error_hash"],
            "status": result["status"], "issue": result.get("issue_number"),
            "title": t, "body": b})
    log.info("GitHub report kind=%s hash=%s → %s", kind, payload["error_hash"], result["status"])
    return result
