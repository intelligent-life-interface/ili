"""github_auth_service.py — GitHub App device-flow login for an ili instance.

Why device flow with a *GitHub App*: the instance only needs the public
client_id — no client secret, no shared PAT. The user confirms a short code on
github.com with their own account; the resulting user token carries just the
App's permissions (Issues: read/write on the target repo). An OAuth App would
need the classic ``public_repo`` scope (write to *all* of the user's public
repos) — exactly what we refuse to ask people for.

Token storage: GITHUB_AUTH_FILE (data/github/github_auth.json, mode 0600).
Deliberately NOT user_settings.json — that file is exportable from the UI.

Interface
---------
start()                 -> dict   # {user_code, verification_uri, device_code, interval, expires_in}
poll(device_code)       -> dict   # {status: "pending"|"slow_down"|"ok"|"expired"|"denied"|"error", ...}
status()                -> dict   # {logged_in, login, expires_at, client_id_set}
get_token()             -> str|None   # valid access token, refreshed if needed
logout()                -> None
"""
import json
import logging
import os
import time

import httpx

from constants import GITHUB_APP_CLIENT_ID, GITHUB_AUTH_FILE
from app.storage.atomic_write import write_json_atomic

log = logging.getLogger("dashboard.services.github_auth")

_DEVICE_CODE_URL = "https://github.com/login/device/code"
_TOKEN_URL = "https://github.com/login/oauth/access_token"
_USER_URL = "https://api.github.com/user"
_TIMEOUT = 15.0
_HEADERS = {"Accept": "application/json", "User-Agent": "ili-dashboard"}


# ---------------------------------------------------------------- storage --

def _load() -> dict:
    if not GITHUB_AUTH_FILE.exists():
        return {}
    try:
        return json.loads(GITHUB_AUTH_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        log.error("github_auth.json unreadable: %s", exc)
        return {}


def _save(data: dict) -> None:
    write_json_atomic(GITHUB_AUTH_FILE, data)
    try:
        os.chmod(GITHUB_AUTH_FILE, 0o600)
    except OSError as exc:
        log.warning("chmod 0600 on %s failed: %s", GITHUB_AUTH_FILE, exc)
    log.debug("github_auth.json written (login=%s, expires_at=%s)",
              data.get("login"), data.get("expires_at"))


def _store_token_response(tok: dict) -> dict:
    """Normalise an access_token response into our stored record."""
    now = int(time.time())
    record = {
        "access_token": tok.get("access_token", ""),
        "refresh_token": tok.get("refresh_token", ""),
        "token_type": tok.get("token_type", "bearer"),
        # GitHub App user tokens expire after 8h when expiry is enabled; a
        # missing expires_in means the App has expiry disabled → no refresh.
        "expires_at": now + int(tok["expires_in"]) if tok.get("expires_in") else None,
        "refresh_expires_at": now + int(tok["refresh_token_expires_in"]) if tok.get("refresh_token_expires_in") else None,
        "login": "",
        "obtained_at": now,
    }
    record["login"] = _fetch_login(record["access_token"])
    _save(record)
    return record


def _fetch_login(token: str) -> str:
    try:
        r = httpx.get(_USER_URL, headers={**_HEADERS, "Authorization": f"Bearer {token}"}, timeout=_TIMEOUT)
        if r.status_code == 200:
            return r.json().get("login", "")
        log.warning("GET /user returned %s", r.status_code)
    except Exception as exc:
        log.warning("GET /user failed: %s", exc)
    return ""


# ------------------------------------------------------------ device flow --

def start() -> dict:
    """Step 1: ask GitHub for a device + user code. Raises RuntimeError on failure."""
    if not GITHUB_APP_CLIENT_ID:
        raise RuntimeError("ILI_GITHUB_APP_CLIENT_ID is not configured")
    r = httpx.post(_DEVICE_CODE_URL, data={"client_id": GITHUB_APP_CLIENT_ID},
                   headers=_HEADERS, timeout=_TIMEOUT)
    log.debug("device/code → %s", r.status_code)
    if r.status_code != 200:
        raise RuntimeError(f"GitHub device/code failed: HTTP {r.status_code}")
    d = r.json()
    if "device_code" not in d:
        raise RuntimeError(f"GitHub device/code error: {d.get('error', 'unknown')}")
    log.info("device flow started (user_code=%s, expires_in=%ss)", d.get("user_code"), d.get("expires_in"))
    return {
        "device_code": d["device_code"],
        "user_code": d["user_code"],
        "verification_uri": d.get("verification_uri", "https://github.com/login/device"),
        "interval": int(d.get("interval", 5)),
        "expires_in": int(d.get("expires_in", 900)),
    }


def poll(device_code: str) -> dict:
    """Step 2: exchange the device code. Call at most every `interval` seconds."""
    if not device_code:
        return {"status": "error", "error": "device_code missing"}
    r = httpx.post(_TOKEN_URL, data={
        "client_id": GITHUB_APP_CLIENT_ID,
        "device_code": device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    }, headers=_HEADERS, timeout=_TIMEOUT)
    d = r.json() if r.content else {}
    err = d.get("error")
    log.debug("device poll → %s error=%s", r.status_code, err)
    if d.get("access_token"):
        rec = _store_token_response(d)
        log.info("device flow completed, logged in as %s", rec["login"] or "?")
        return {"status": "ok", "login": rec["login"]}
    mapping = {
        "authorization_pending": "pending",
        "slow_down": "slow_down",
        "expired_token": "expired",
        "access_denied": "denied",
    }
    return {"status": mapping.get(err, "error"), "error": err or f"HTTP {r.status_code}"}


# ---------------------------------------------------------------- tokens --

def _refresh(rec: dict) -> dict | None:
    if not rec.get("refresh_token"):
        return None
    r = httpx.post(_TOKEN_URL, data={
        "client_id": GITHUB_APP_CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": rec["refresh_token"],
    }, headers=_HEADERS, timeout=_TIMEOUT)
    d = r.json() if r.content else {}
    if d.get("access_token"):
        log.info("GitHub token refreshed")
        return _store_token_response(d)
    log.warning("token refresh failed: %s", d.get("error") or r.status_code)
    return None


def get_token() -> str | None:
    """Valid access token or None (not logged in / expired without refresh)."""
    rec = _load()
    if not rec.get("access_token"):
        return None
    exp = rec.get("expires_at")
    if exp and time.time() > exp - 60:
        log.debug("access token expired (expires_at=%s) — refreshing", exp)
        rec = _refresh(rec)
        if not rec:
            return None
    return rec.get("access_token") or None


def status() -> dict:
    """Public view — never includes the token itself."""
    rec = _load()
    logged_in = bool(rec.get("access_token"))
    exp = rec.get("expires_at")
    if logged_in and exp and time.time() > exp - 60 and not rec.get("refresh_token"):
        logged_in = False
    return {
        "logged_in": logged_in,
        "login": rec.get("login", "") if logged_in else "",
        "expires_at": exp,
        "client_id_set": bool(GITHUB_APP_CLIENT_ID),
    }


def logout() -> None:
    if GITHUB_AUTH_FILE.exists():
        GITHUB_AUTH_FILE.unlink()
        log.info("GitHub login removed (%s deleted)", GITHUB_AUTH_FILE)
