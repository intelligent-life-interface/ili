#!/usr/bin/env python3
"""Claude-CLI-Bridge — HTTP-Proxy für Container, der die lokal eingeloggte
Claude-Code-Subscription (OAuth) nutzt statt eines API-Keys.

Endpoint:
  POST /chat
    body: {"system": str, "messages": [{role, content}], "model": str, "max_tokens"?,
           "temperature"?, "loop_run_id"?: str}
    response: {"text": str, "model": str, "tokens": {"input", "output", "cache_read",
               "cache_write", "cost_usd", "model"}}
  POST /vision
    body: {"system"?: str, "prompt": str, "images": [{"base64": str, "media_type"?: str}],
           "model"?: str, "loop_run_id"?: str}
    response: {"text": str, "model": str, "tokens": {...}}
    → Bild-Analyse übers Abo. Das Bild wird als base64-CONTENT-BLOCK via
      --input-format stream-json an `claude` gereicht (Modell-Input, KEIN Tool,
      KEIN Dateizugriff). Tool-Sperre bleibt identisch zu /chat.
  GET  /health
    response: {"ok": true, "claude_version": "..."}

Authentifizierung: keine (nur an localhost binden!). Wird per systemd-user als User
als derselbe Benutzer gestartet, damit `claude` die OAuth-Session aus ~/.claude/ findet.

Aufruf-Konstrukt:
  claude -p "<gerenderter prompt>" --system-prompt "..." --output-format json --model X
  --no-session-persistence  (kein Session-Save)

Token-Statistik: `--output-format json` liefert im abschliessenden `result`-Event echte
Usage-Zahlen (inkl. Cache-Tokens) + Kosten. Schickt ein Aufrufer ein `loop_run_id` mit,
meldet die Bridge sie selbst an ~/bin/loop_logger.py — EIN Schreibpfad statt Parsing in
jedem Aufrufer. Das ist keine Doppelzählung: `--no-session-persistence` erzeugt kein
Transkript, deshalb kann cost_db_sync._join_loop_runs() diese Läufe nicht anreichern.
Beide Flags müssen zusammen bleiben — ohne das Flag zählte der Join zusätzlich mit.
"""
import http.server
import importlib.util
import json
import logging
import os
import shutil
import socketserver
import subprocess
from pathlib import Path
from typing import Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("claude_cli_bridge")

LISTEN_HOST = os.getenv("BRIDGE_HOST", "127.0.0.1")  # localhost nur (Sicherheit)
LISTEN_PORT = int(os.getenv("BRIDGE_PORT", "8950"))
# BRIDGE_KEEP_API_KEY=1 (ili release): let `claude -p` use ANTHROPIC_API_KEY when the
# installation has no subscription login. The home stack strips it to force the Abo.
KEEP_API_KEY = os.getenv("BRIDGE_KEEP_API_KEY", "0") == "1"


def _claude_env() -> dict:
    if KEEP_API_KEY:
        return dict(os.environ)
    return {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}

CLAUDE_BIN  = os.getenv("CLAUDE_BIN", os.path.expanduser("~/.local/bin/claude"))
TIMEOUT_S   = int(os.getenv("BRIDGE_TIMEOUT", "180"))
BRIDGE_TOKEN = os.getenv("BRIDGE_TOKEN", "")  # Shared-Secret für LAN-Konsumenten


# ── SICHERHEIT: reine Inferenz, KEINE Agent-Tools (gilt für /chat UND /vision) ──
# Diese Bridge verarbeitet UNTRUSTED Input. Ohne diese Flags erbt `claude` die
# breite Allowlist aus ~/.claude/settings.json (Bash, sudo) → Prompt-Injection =
# RCE/Datenleck. Bei /vision ist das Bild ein base64-CONTENT-BLOCK (Modell-Input),
# NICHT ein Tool — es braucht KEIN Read-Tool und KEINEN Dateizugriff. Darum bleibt
# die Sperre vollständig: Claude kann über die Bridge weder Code ändern noch Dateien
# lesen, egal wie (Text oder Bild) übertragen wird.
SECURITY_FLAGS = [
    "--permission-mode", "dontAsk",
    "--allowedTools", "",
    # --disallowedTools entfernt: --allowedTools "" sperrt bereits alle Tools.
    # Explizite deny-Liste mit veralteten Namen (MultiEdit, SlashCommand) verursachte
    # in neueren CLI-Versionen "matches no known tool" → exit 1.
    "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
]


LOOP_LOGGER_PATH = Path(os.getenv(
    "LOOP_LOGGER_PATH", os.path.expanduser("~/bin/loop_logger.py")))
_loop_logger = None


def _get_loop_logger():
    """Load loop_logger.py from ~/bin on first use (stdlib-only, no package import).
    Same importlib pattern as the dashboard's usage_service.py."""
    global _loop_logger
    if _loop_logger is None:
        spec = importlib.util.spec_from_file_location("loop_logger", LOOP_LOGGER_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _loop_logger = mod
    return _loop_logger


def _result_event(raw: str) -> dict:
    """Extract the final `result` event from a `claude -p --output-format json` run.

    The CLI returns a LIST of events (rate_limit_event, system, assistant, result);
    older/other builds may return the result object directly. Returns {} when the
    output is unparsable — callers fall back to the raw text."""
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    if isinstance(data, dict):
        return data if data.get("type") in (None, "result") else {}
    if isinstance(data, list):
        for o in reversed(data):
            if isinstance(o, dict) and o.get("type") == "result":
                return o
    return {}


def _usage_of(event: dict, fallback_model: str) -> dict:
    """Normalise the CLI's usage block into the flat shape the HTTP clients see."""
    u = event.get("usage") or {}
    model = fallback_model
    mu = event.get("modelUsage") or {}
    if mu:
        model = next(iter(mu))          # exactly one entry per single-turn call
    return {
        "input": int(u.get("input_tokens") or 0),
        "output": int(u.get("output_tokens") or 0),
        "cache_read": int(u.get("cache_read_input_tokens") or 0),
        "cache_write": int(u.get("cache_creation_input_tokens") or 0),
        "cost_usd": float(event.get("total_cost_usd") or 0.0),
        "model": model,
    }


def _report_usage(loop_run_id: str | None, usage: dict | None) -> None:
    """Attach this call's usage to a loop run. Best-effort by design: statistics
    must never break the answer the caller is waiting for."""
    if not loop_run_id or not usage:
        return
    try:
        _get_loop_logger().record_usage(
            loop_run_id,
            model=usage.get("model"),
            input_tokens=usage.get("input"),
            output_tokens=usage.get("output"),
            cache_read_tokens=usage.get("cache_read"),
            cache_write_tokens=usage.get("cache_write"),
            cost_usd=usage.get("cost_usd"),
        )
        log.info(f"[usage] run_id={loop_run_id} in={usage.get('input')} "
                 f"out={usage.get('output')} cache_r={usage.get('cache_read')} "
                 f"cost=${usage.get('cost_usd')}")
    except Exception as e:
        log.warning(f"[usage] Meldung an loop_logger fehlgeschlagen (run_id={loop_run_id}): {e}")


def _render_messages(messages: list) -> str:
    """Konvertiert Multi-Turn-Verlauf in einen einzelnen Prompt-String."""
    if len(messages) == 1 and messages[0].get("role") == "user":
        return messages[0].get("content", "")
    lines = ["=== Bisheriger Verlauf ===\n"]
    for m in messages[:-1]:
        role = m.get("role", "user")
        label = "Assistent" if role == "assistant" else ("System" if role == "system" else "Nutzer")
        lines.append(f"[{label}]: {m.get('content', '')}\n")
    last = messages[-1]
    lines.append(f"\n=== Aktuelle Nachricht ({last.get('role','user')}) ===\n{last.get('content','')}")
    return "\n".join(lines)


def _call_claude(system: str, messages: list, model: str) -> Tuple[str, dict]:
    prompt = _render_messages(messages)
    cmd = [
        CLAUDE_BIN, "-p", prompt,
        "--output-format", "json",
        "--no-session-persistence",
        "--model", model,
        *SECURITY_FLAGS,
    ]
    if system:
        cmd += ["--system-prompt", system]
    log.info(f"[claude] model={model} prompt_chars={len(prompt)} sys_chars={len(system or '')}")
    env = _claude_env()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S,
                       env=env)
    if r.returncode != 0:
        out_msg = (r.stdout or "").strip()[:300]
        err_msg = (r.stderr or "").strip()[:300]
        raise RuntimeError(f"claude exit {r.returncode}: out={out_msg!r} err={err_msg!r}")
    raw = (r.stdout or "").strip()
    ev = _result_event(raw)
    if not ev:
        # Under --output-format json the raw stdout is the CLI's event envelope, never
        # the answer — handing it back would feed metadata to the fence-robust parsers
        # downstream (they'd happily pull a {...} out of it). Fail loudly instead.
        log.error(f"[claude] kein result-Event im JSON-Output (chars={len(raw)}): {raw[:300]!r}")
        raise RuntimeError("claude lieferte kein result-Event (unerwartetes Ausgabeformat)")
    text = (ev.get("result") or "").strip()
    usage = _usage_of(ev, model)
    log.info(f"[claude] ok, out_chars={len(text)} in={usage['input']} out={usage['output']} "
             f"cache_r={usage['cache_read']} cost=${usage['cost_usd']}")
    return text, usage


def _stream_claude(system: str, messages: list, model: str, usage_sink: dict | None = None):
    """Streamt die Antwort TOKEN-WEISE als Generator von Text-Chunks.

    Nutzt `--output-format stream-json --include-partial-messages --verbose`:
    Claude emittiert NDJSON-Events; die Text-Deltas stecken in
    type=stream_event → event.type=content_block_delta → delta.type=text_delta.
    Security-Flags identisch zu /chat (reine Inferenz, KEINE Tools).

    `usage_sink` (optional): dict, in das die Zahlen des abschliessenden
    `result`-Events geschrieben werden — ein Generator kann keinen zweiten
    Rückgabewert liefern, den der Aufrufer nach dem Streamen noch sieht."""
    import threading
    prompt = _render_messages(messages)
    cmd = [
        CLAUDE_BIN, "-p", prompt,
        "--output-format", "stream-json",
        "--include-partial-messages", "--verbose",
        "--no-session-persistence",
        "--model", model,
        *SECURITY_FLAGS,
    ]
    if system:
        cmd += ["--system-prompt", system]
    log.info(f"[stream] model={model} prompt_chars={len(prompt)} sys_chars={len(system or '')}")
    env = _claude_env()
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, env=env)
    killer = threading.Timer(TIMEOUT_S, p.kill)   # Watchdog gegen Hänger
    killer.start()

    # stderr in eigenem Thread lesen, um Deadlock durch Buffer-Überlauf zu verhindern
    stderr_lines = []
    def _read_stderr():
        for line in (p.stderr or []):
            stderr_lines.append(line.rstrip('\n'))
    stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
    stderr_thread.start()

    n = 0
    try:
        for line in p.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get("type") == "stream_event":
                ev = o.get("event", {})
                if ev.get("type") == "content_block_delta":
                    d = ev.get("delta", {})
                    if d.get("type") == "text_delta" and d.get("text"):
                        n += len(d["text"])
                        yield d["text"]
            elif o.get("type") == "result" and usage_sink is not None:
                # Closing event carries the real token counts — previously discarded.
                usage_sink.update(_usage_of(o, model))
        p.wait()
        stderr_thread.join(timeout=1)  # Warte auf stderr-Thread
        if p.returncode not in (0, None):
            err_msg = " ".join(stderr_lines).strip()[:300] if stderr_lines else ""
            raise RuntimeError(f"claude exit {p.returncode}: err={err_msg!r}")
        log.info(f"[stream] ok, out_chars={n}")
    finally:
        killer.cancel()
        if p.poll() is None:
            p.kill()


def _call_claude_vision(system: str, prompt: str, images: list, model: str) -> Tuple[str, dict]:
    """Bild-Analyse übers Abo: Bilder als base64-Content-Blocks via stream-json.
    Tools bleiben gesperrt (SECURITY_FLAGS) — das Bild ist Modell-Input, kein Tool."""
    content = []
    for i, im in enumerate(images):
        b64 = im.get("base64") or im.get("data")
        if not b64:
            continue
        mt = im.get("media_type") or im.get("mediaType") or "image/jpeg"
        if len(images) > 1:
            content.append({"type": "text", "text": f"=== FOTO / SEITE {i+1} von {len(images)} ==="})
        content.append({"type": "image", "source": {"type": "base64", "media_type": mt, "data": b64}})
    content.append({"type": "text", "text": prompt})
    msg = {"type": "user", "message": {"role": "user", "content": content}}

    cmd = [
        CLAUDE_BIN, "-p",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--no-session-persistence",
        "--model", model,
        *SECURITY_FLAGS,
    ]
    if system:
        cmd += ["--system-prompt", system]
    log.info(f"[vision] model={model} bilder={len(images)} prompt_chars={len(prompt)}")
    env = _claude_env()
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, env=env)
    out, err = p.communicate(input=json.dumps(msg) + "\n", timeout=TIMEOUT_S)
    if p.returncode != 0:
        out_msg = (out or "").strip()[:300]
        err_msg = (err or "").strip()[:300]
        raise RuntimeError(f"claude vision exit {p.returncode}: out={out_msg!r} err={err_msg!r}")
    # stream-json: letzte 'result'-Zeile bzw. assistant-Text einsammeln
    text = ""
    usage = {}
    for line in (out or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        if o.get("type") == "result":
            if o.get("result"):
                text = o["result"]
            usage = _usage_of(o, model)
        elif o.get("type") == "assistant" and not text:
            for c in o.get("message", {}).get("content", []):
                if c.get("type") == "text":
                    text += c["text"]
    log.info(f"[vision] ok, out_chars={len(text)} in={usage.get('input', 0)} "
             f"out={usage.get('output', 0)} cost=${usage.get('cost_usd', 0)}")
    return text.strip(), usage


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        log.info("%s - %s", self.client_address[0], fmt % args)

    def _check_auth(self) -> bool:
        """Prüfe X-Bridge-Token Header. Fehlt er: nur warnen (Übergangsphase).
        Falsch: 401. Richtig: OK."""
        token = self.headers.get("X-Bridge-Token", "").strip()
        if not token:
            if BRIDGE_TOKEN:
                log.warning(f"[auth] {self.client_address[0]} schickt keinen X-Bridge-Token (noch in Übergangsphase)")
            else:
                log.debug(f"[auth] {self.client_address[0]} ohne X-Bridge-Token (kein BRIDGE_TOKEN konfiguriert)")
            return True  # Noch erlauben, aber gewarnt
        if not BRIDGE_TOKEN:
            log.error("[auth] BRIDGE_TOKEN nicht in Umgebung — ohne das Token kann Auth nicht geprüft werden")
            return False
        if token != BRIDGE_TOKEN:
            log.warning(f"[auth] {self.client_address[0]} schickt falsches Token")
            self._json(401, {"error": "invalid token"})
            return False
        return True

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            v = "?"
            try:
                rv = subprocess.run([CLAUDE_BIN, "--version"], capture_output=True, text=True, timeout=5)
                v = rv.stdout.strip().split()[0]
            except Exception:
                pass
            return self._json(200, {"ok": True, "claude_version": v, "bin": CLAUDE_BIN})
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path not in ("/chat", "/vision", "/stream"):
            return self._json(404, {"error": "not found"})
        if not self._check_auth():
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as e:
            return self._json(400, {"error": f"invalid json: {e}"})

        model = payload.get("model", "claude-sonnet-4-6")
        system = payload.get("system", "") or ""
        # Optional: caller runs inside a systemd loop (loop-run.sh exports LOOP_RUN_ID)
        # and wants this call's tokens attached to that run. Absent for browser/bot clients.
        loop_run_id = payload.get("loop_run_id") or None

        # ── /stream: Text-Inferenz, TOKEN-WEISE gestreamt (NDJSON) ──
        # Jede Zeile: {"t": "<chunk>"} ; Abschluss: {"done": true} ; Fehler: {"error": "..."}
        if self.path == "/stream":
            messages = payload.get("messages") or []
            if not messages:
                return self._json(400, {"error": "messages required"})
            self.close_connection = True   # kein keep-alive — wir streamen bis EOF
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            stream_usage: dict = {}
            try:
                for chunk in _stream_claude(system, messages, model, usage_sink=stream_usage):
                    self.wfile.write((json.dumps({"t": chunk}, ensure_ascii=False) + "\n").encode("utf-8"))
                    self.wfile.flush()
                _report_usage(loop_run_id, stream_usage)
                done = {"done": True, "model": model}
                if stream_usage:
                    done["tokens"] = stream_usage
                self.wfile.write((json.dumps(done) + "\n").encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                log.info("[stream] Client getrennt")
            except Exception as e:
                log.error(f"stream error: {e}")
                try:
                    self.wfile.write((json.dumps({"error": str(e)}) + "\n").encode("utf-8"))
                    self.wfile.flush()
                except Exception:
                    pass
            return

        # ── /vision: Bild-Analyse übers Abo ──
        if self.path == "/vision":
            images = payload.get("images") or []
            prompt = payload.get("prompt", "") or ""
            if not images:
                return self._json(400, {"error": "images required"})
            if not prompt:
                return self._json(400, {"error": "prompt required"})
            try:
                text, usage = _call_claude_vision(system, prompt, images, model)
                _report_usage(loop_run_id, usage)
                return self._json(200, {"text": text, "model": model, "tokens": usage})
            except subprocess.TimeoutExpired:
                return self._json(504, {"error": f"claude vision timeout > {TIMEOUT_S}s"})
            except Exception as e:
                log.error(f"vision error: {e}")
                return self._json(500, {"error": str(e)})

        # ── /chat: reine Text-Inferenz ──
        messages = payload.get("messages") or []
        if not messages:
            return self._json(400, {"error": "messages required"})
        try:
            text, tokens = _call_claude(system, messages, model)
            _report_usage(loop_run_id, tokens)
            return self._json(200, {"text": text, "model": model, "tokens": tokens})
        except subprocess.TimeoutExpired:
            return self._json(504, {"error": f"claude timeout > {TIMEOUT_S}s"})
        except Exception as e:
            log.error(f"chat error: {e}")
            return self._json(500, {"error": str(e)})


class ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    if not shutil.which(CLAUDE_BIN) and not os.path.exists(CLAUDE_BIN):
        log.error(f"claude binary nicht gefunden: {CLAUDE_BIN}")
        raise SystemExit(2)
    srv = ThreadingServer((LISTEN_HOST, LISTEN_PORT), Handler)
    log.info(f"claude_cli_bridge listening on {LISTEN_HOST}:{LISTEN_PORT}  (bin={CLAUDE_BIN})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
