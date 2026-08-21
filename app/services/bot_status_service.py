"""Bot-Status-Service — Überblick über alle Claude-Code-Sessions in tmux.

Liest rein den sichtbaren Pane-Text (`tmux capture-pane`) und klassifiziert je
Session: wartet auf Antwort / arbeitet / leer-bereit. Keine API, kein State.

dashboard-api läuft als User-Prozess (systemd --user) → hat Zugriff auf den
tmux-Socket unter $XDG_RUNTIME_DIR. Schlägt `tmux` fehl (kein Server) → leere Liste.

Schnittstelle:
    list_sessions() -> {"sessions": [ {name, kind, slug, state, tokens, context,
                                       link, title} ], "summary": {...}, "ts": iso}
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
from datetime import datetime

from app.services.ttl_cache import TTLCache

log = logging.getLogger("dashboard.bot_status")

# opt_polling_ttl_caches_0815: list_sessions() macht `tmux ls` + PRO Session ein
# `tmux capture-pane` — /bot-status wird von fragen.html + bots.html je alle 10s
# gepollt (mehrere offene Tabs teilen sich sonst nichts). Kurzer TTL-Cache mit
# Single-Flight (Muster app/api/fragen.py) dämpft das, ohne die Daten spürbar
# altbacken wirken zu lassen (Zustand ändert sich nicht im Sekundentakt).
_list_cache = TTLCache(ttl_seconds=8.0)

# Spinner-/Aktiv-Marker, die Claude Code beim Arbeiten zeigt (Wortliste bewusst breit).
# Die \w*…-Bindung verlangt die Ellipsis des laufenden Spinners und schliesst
# fertige "… for Xs"-Meldungen (z.B. "Crunched for 9s") sicher aus.
_ACTIVE_RE = re.compile(
    r"\([0-9]+m?[0-9]*s ·"            # "(31s · …)" Lauf-Timer
    r"|esc to interrupt"
    r"|⎿\s+(Running|Waiting)…"
    r"|(Cogitat|Burrow|Cascad|Newspaper|Thinking|Working|Pondering|Crunch|"
    r"Forging|Simmer|Brew|Percolat|Ruminat|Hatch|Spelunk|Synthesi|Distill)\w*…",
)
# Claude-Code-Prompt sichtbar (= interaktiv, kein reiner Shell-Prompt)
_PROMPT_RE = re.compile(r"⏵⏵ auto mode|^❯", re.M)
# AskUserQuestion-Dialog / Session-Resume-Auswahl: eigener Footer ersetzt die
# normale Statuszeile inkl. Token-Zahl → tokens bleibt 0, _PROMPT_RE greift bei
# eingerücktem "❯" (Resume-Dialog) gar nicht erst. Ohne diesen Marker landet die
# Session fälschlich bei "leer" statt "wartet" und verschwindet aus "Offene Fragen".
_WAITING_DIALOG_RE = re.compile(r"Enter to select|Enter to confirm")
# Zeilen, die nie als Kontext taugen (Deko/Status/Tipps)
_NOISE_RE = re.compile(
    r"^\s*$|^[─-]+$|INSERT|auto mode|tokens$|^\s*--\s*$|Try \"|/btw|shift\+tab|"
    r"Resume this session|claude --resume|Press up to edit|^❯\s*$|↳",
)
_TOKENS_RE = re.compile(r"([0-9]+)\s+tokens")


def _run(args: list[str], timeout: int = 5) -> str:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except Exception as e:  # tmux fehlt / kein Server / Timeout
        log.debug("tmux-Aufruf fehlgeschlagen %s: %s", args, e)
        return ""


def _link_for(name: str) -> tuple[str, str, str]:
    """(kind, slug, link) für eine Session bestimmen."""
    if name.startswith("proj-"):
        slug = name[len("proj-"):]
        # project.html?id=<slug> öffnet das Board MIT eingebettetem Terminal (gleiche Session)
        return "Projekt", slug, f"/project.html?id={slug}"
    m = re.fullmatch(r"term(\d+)", name)
    if m:
        _dom = os.environ.get("DASHBOARD_DOMAIN", "yourdomain.example")
        return "Web-Terminal", name, f"https://terminal{m.group(1)}.intranet.{_dom}"
    return "Sonstige", name, ""


def _classify(pane: str) -> tuple[str, int]:
    """(state, tokens) aus dem Pane-Text."""
    tok_matches = _TOKENS_RE.findall(pane)
    tokens = int(tok_matches[-1]) if tok_matches else 0
    if _ACTIVE_RE.search(pane):
        return "arbeitet", tokens
    if _WAITING_DIALOG_RE.search(pane):
        return "wartet", tokens
    if _PROMPT_RE.search(pane):
        # 0 Tokens + Prompt = frische, noch nicht beauftragte Session
        return ("leer" if tokens == 0 else "wartet"), tokens
    return "shell", tokens


def _context(pane: str, n: int = 6) -> str:
    """Letzte n sinnvolle Inhaltszeilen (für wartende Sessions = die offene Frage)."""
    lines = [ln.rstrip() for ln in pane.splitlines() if not _NOISE_RE.search(ln)]
    tail = lines[-n:]
    return "\n".join(tail).strip()


def list_sessions() -> dict:
    """Wie _list_sessions_uncached(), aber gecacht für 8 Sekunden
    (Single-Flight, Double-Checked Locking via TTLCache)."""
    return _list_cache.get(_list_sessions_uncached)


def _list_sessions_uncached() -> dict:
    names_raw = _run(["tmux", "ls", "-F", "#{session_name}"])
    names = sorted(n for n in names_raw.splitlines() if n.strip())
    out: list[dict] = []
    summary = {"wartet": 0, "arbeitet": 0, "leer": 0, "shell": 0}
    for name in names:
        pane = _run(["tmux", "capture-pane", "-pt", name])
        state, tokens = _classify(pane)
        kind, slug, link = _link_for(name)
        ctx = _context(pane) if state in ("wartet", "arbeitet") else ""
        # Titel = lesbarer Name (proj-foo → foo, sonst Sessionname)
        title = slug if kind == "Projekt" else name
        summary[state] = summary.get(state, 0) + 1
        out.append({
            "name": name, "kind": kind, "slug": slug, "state": state,
            "tokens": tokens, "context": ctx, "link": link, "title": title,
        })
    # Sortierung: wartende zuerst, dann arbeitende, dann Rest
    order = {"wartet": 0, "arbeitet": 1, "shell": 2, "leer": 3}
    out.sort(key=lambda s: (order.get(s["state"], 9), s["name"]))
    return {"sessions": out, "summary": summary, "ts": datetime.now().isoformat(timespec="seconds")}


# ── Terminal-Heilung (vom „↻ Neu laden"-Knopf im Projekt-Terminal aufgerufen) ──
# Zwei Probleme in einem Rutsch:
#   1) Mosaik/Geistertext: hängen mehrere ttyd-Clients unterschiedlicher Grösse an
#      derselben tmux-Session, zeichnet tmux für die kleinste -> kaputtes Bild.
#      Fix: alle Clients der Session lösen; danach reattacht das frisch geladene iframe
#      als EINZIGER Client in der richtigen Grösse.
#   2) Tote bash: claude ist gecrasht/beendet (z.B. Auto-Update mit Exit 0) und der
#      Pane hängt in einer nackten Login-Shell. Fix: `claude --continue` einschicken
#      -> die letzte Konversation des Projektordners läuft weiter (kein Kontextverlust).

_SAFE_SLUG_RE = re.compile(r"^[A-Za-z0-9._-]+$")  # nur unverdächtige Sessionnamen


def _session_names() -> set[str]:
    return {n for n in _run(["tmux", "ls", "-F", "#{session_name}"]).splitlines() if n.strip()}


def _claude_alive(name: str) -> bool:
    """True, wenn unter der Pane-Shell ein laufender claude/node-Prozess hängt.

    `pane_current_command` ist unzuverlässig (zeigt oft `bash`, obwohl claude als
    Vordergrund-Kind läuft) -> echten Prozessbaum prüfen.
    """
    pid = _run(["tmux", "list-panes", "-t", name, "-F", "#{pane_pid}"]).splitlines()
    pid = pid[0].strip() if pid else ""
    if not pid:
        return False
    for kid in _run(["pgrep", "-P", pid]).split():
        comm = _run(["ps", "-o", "comm=", "-p", kid]).strip()
        if comm in ("claude", "node"):
            return True
    return False


# ── Antwort in eine Session tippen (fragen.html: direkt antworten ohne Terminal) ──
# Sicherheit: nur existierende tmux-Sessions (exakter Name aus `tmux ls`), Keys nur
# aus Whitelist, Text längenbegrenzt. Alles via Arg-Liste an tmux → keine Shell-Injection.

_ALLOWED_KEYS = {"Enter", "Escape", "Up", "Down", "Tab"} | {str(i) for i in range(1, 10)}
_MAX_ANSWER_LEN = 2000


def send_answer(name: str, text: str = "", key: str = "") -> dict:
    """Antwort/Taste in eine tmux-Session schicken.

    text → literal eintippen + Enter (normale Prompt-Antwort).
    key  → einzelne Taste aus Whitelist (Menü-Auswahl 1-9, Enter, Escape, Up/Down/Tab).
    Returns {ok, name, sent, mode} bzw. {ok: False, reason}.
    """
    import time
    name, text, key = (name or "").strip(), (text or "").rstrip("\n"), (key or "").strip()
    if name not in _session_names():
        log.warning("send_answer: unbekannte Session %r", name)
        return {"ok": False, "reason": "unknown-session", "name": name}
    if key:
        if key not in _ALLOWED_KEYS:
            log.warning("send_answer: Taste %r nicht erlaubt (Session %s)", key, name)
            return {"ok": False, "reason": "key-not-allowed", "name": name}
        _run(["tmux", "send-keys", "-t", name, key])
        log.info("send_answer: Taste %s -> %s", key, name)
        return {"ok": True, "name": name, "sent": key, "mode": "key"}
    if not text.strip():
        return {"ok": False, "reason": "empty", "name": name}
    if len(text) > _MAX_ANSWER_LEN:
        log.warning("send_answer: Text zu lang (%d) für %s", len(text), name)
        return {"ok": False, "reason": "too-long", "name": name}
    _run(["tmux", "send-keys", "-t", name, "-l", "--", text])
    time.sleep(0.3)  # Claude-Code-TUI braucht einen Moment, sonst schluckt Enter Text
    _run(["tmux", "send-keys", "-t", name, "Enter"])
    log.info("send_answer: %d Zeichen + Enter -> %s", len(text), name)
    return {"ok": True, "name": name, "sent": text[:120], "mode": "text"}


def heal_session(slug: str) -> dict:
    """Projekt-Terminal `proj-<slug>` heilen: Mosaik lösen + tote claude-Session fortsetzen.

    Returns {ok, name, existed, detached, restarted_claude, actions[]}.
    Idempotent & defensiv: existiert die Session nicht, passiert nichts (das iframe
    legt sie beim Attach selbst via Wrapper an).
    """
    slug = (slug or "").strip()
    if not _SAFE_SLUG_RE.match(slug):
        return {"ok": False, "reason": "bad-slug", "name": f"proj-{slug}"}
    name = f"proj-{slug}"
    actions: list[str] = []
    if name not in _session_names():
        log.info("heal_session: %s existiert nicht (iframe legt sie beim Attach an)", name)
        return {"ok": True, "name": name, "existed": False,
                "detached": False, "restarted_claude": False, "actions": actions}

    # 1) Mosaik-Fix: alle Clients dieser Session lösen
    _run(["tmux", "detach-client", "-s", name])
    actions.append("detach-clients")

    # 2) claude tot? -> Konversation fortsetzen
    restarted = False
    if not _claude_alive(name):
        _run(["tmux", "send-keys", "-t", name, "C-c"])
        _run(["tmux", "send-keys", "-t", name, "clear && claude --continue", "Enter"])
        actions.append("restart-claude")
        restarted = True
        log.info("heal_session: %s war tot -> claude --continue gestartet", name)
    else:
        log.info("heal_session: %s claude läuft -> nur Clients gelöst (Mosaik-Fix)", name)

    return {"ok": True, "name": name, "existed": True,
            "detached": True, "restarted_claude": restarted, "actions": actions}
