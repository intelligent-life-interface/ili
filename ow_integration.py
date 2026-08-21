"""\now_integration.py — Overwolf-Integration-Funktionen\nAutogeneriert von script_splitter.py\n"""
import json
import logging
import urllib.request
import urllib.error
from constants import OPENWEBUI_URL, OPENWEBUI_EMAIL, OPENWEBUI_PASSWORD

log = logging.getLogger("dashboard.ow_integration")


def _ow_login() -> str:
    """Login zu Open WebUI und JWT-Token zurückgeben. Bei Fehler: leerer String."""
    global _ow_token
    if not OPENWEBUI_EMAIL or not OPENWEBUI_PASSWORD:
        log.warning("OPENWEBUI_EMAIL / OPENWEBUI_PASSWORD nicht gesetzt — kein Login möglich")
        return ""
    url = f"{OPENWEBUI_URL}/api/v1/auths/signin"
    payload = json.dumps({"email": OPENWEBUI_EMAIL, "password": OPENWEBUI_PASSWORD}).encode()
    log.debug(f"OpenWebUI Login POST {url} als {OPENWEBUI_EMAIL}")
    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())
        token = body.get("token", "")
        if token:
            log.info("OpenWebUI Login erfolgreich — Token gecacht")
            _ow_token = token
        else:
            log.error(f"OpenWebUI Login: kein token in Response — body={body}")
        return token
    except Exception as e:
        log.error(f"OpenWebUI Login fehlgeschlagen: {e}")
        return ""




def _ow_chat(payload: dict) -> dict:
    """
    Chat-Request an Open WebUI senden.
    Bei 401: einmal neu einloggen und wiederholen.
    Bei Fehler nach Retry: leeres dict (Caller behandelt das als "keine Antwort").
    """
    global _ow_token

    # Token sicherstellen
    if not _ow_token:
        log.debug("Kein Token vorhanden — Login wird versucht")
        _ow_login()

    url = f"{OPENWEBUI_URL}/api/chat/completions"
    body_bytes = json.dumps(payload).encode()

    def _do_request(token: str) -> tuple[int, bytes]:
        req = urllib.request.Request(
            url,
            data=body_bytes,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    log.debug(f"OpenWebUI Chat POST {url}, model={payload.get('model')}, messages={len(payload.get('messages', []))}")
    status, raw = _do_request(_ow_token)
    log.debug(f"OpenWebUI Chat Response: status={status}, body_len={len(raw)}")

    if status == 401:
        log.warning("OpenWebUI 401 — Token abgelaufen, Login wiederholen...")
        _ow_token = ""
        _ow_login()
        if _ow_token:
            status, raw = _do_request(_ow_token)
            log.debug(f"OpenWebUI Chat Retry Response: status={status}, body_len={len(raw)}")

    if status in (200, 201):
        return json.loads(raw.decode())

    log.error(f"OpenWebUI Chat fehlgeschlagen: status={status}, body={raw[:500]}")
    return {}


