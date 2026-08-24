"""constants.py — Gemeinsame Konstanten und Konfiguration für alle Module."""
import logging
import os
from pathlib import Path

# Alle Pfade über Umgebungsvariablen konfigurierbar (Defaults für Entwicklung)
_DASH          = Path(os.environ.get("DASHBOARD_DIR", str(Path.home() / "containers/dashboard")))
DASHBOARD_DIR  = _DASH  # öffentlicher Alias für Standalone-Skripte ausserhalb von app/
# ai_config.json muss im Automat-State-Ordner liegen, damit der Automat GI-Entscheidungen sieht
_AUTOMAT_STATE = Path(os.environ.get("AUTOMAT_STATE_DIR", str(Path.home() / "containers/kanban-automat/state")))
AI_CONFIG_FILE = _AUTOMAT_STATE / "ai_config.json"
BOARDS_DIR     = Path(os.environ.get("BOARDS_DIR", str(_DASH / "boards")))
MANIFEST       = BOARDS_DIR / "manifest.json"
PHOTOS_DIR         = _DASH / "html/photos"
TEMPLATES_FILE     = _DASH / "board_templates.json"
KI_ADVISOR_SCRIPT  = _DASH / "jobs" / "ki_project_advisor.py"  # 2026-07-24 nach jobs/ verschoben (opt_pfad_drift_0809)
KI_ADVISOR_STATUS  = _DASH / "ki_advisor_status.json"
KI_ADVISOR_STDERR_LOG = _DASH / "ki_advisor_stderr.log"
KI_FEEDBACK_FILE   = _DASH / "ki_feedback.json"
KI_EXPLAIN_QUEUE   = _DASH / "ki_explain_queue.json"
KI_EXPLAIN_RESULTS    = _DASH / "ki_explain_results.json"
KI_EXPLAIN_OLLAMA_USAGE_FILE = _DASH / "ki_explain_ollama_usage.jsonl"
KI_ADVISOR_OLLAMA_USAGE_FILE = _DASH / "ki_advisor_ollama_usage.jsonl"
KI_GLOBAL_REJECTIONS  = _DASH / "ki_global_rejections.json"
KI_BUG_REPORTS        = _DASH / "ki_bug_reports.json"
CLAUDE_COST_FILE       = _DASH / "claude_cost_log.jsonl"
CLAUDE_COST_CHECKPOINT = _DASH / "claude_cost_checkpoint.json"
CLAUDE_BLOCK_FILE      = _DASH / "claude_daily_block.json"
OLLAMA_USAGE_FILE      = _DASH / "ollama_usage_log.jsonl"
LOG_SOURCES_FILE       = _DASH / "log_sources.json"
SCAN_HTML_FILE         = _DASH / "html/scan.html"
SERVICES_HTML_FILE     = _DASH / "html/services.html"
DASHBOARD_HTML_FILE    = _DASH / "html/index.html"
SESSION_MONITOR_STATE_FILE        = _DASH / "session_monitor_state.json"
SESSION_MONITOR_ALERT_LOG         = _DASH / "session_monitor_alerts.jsonl"
SESSION_MONITOR_OLLAMA_USAGE_FILE = _DASH / "session_monitor_ollama_usage.jsonl"
# Personalisierte Service-Übersicht (Container/URLs/User) — siehe services_config.example.json
# URLs dürfen {ENV_VAR}-Platzhalter enthalten (z.B. für Tokens), werden beim Laden ersetzt.
SERVICES_CONFIG_FILE = Path(os.environ.get("SERVICES_CONFIG_FILE", str(_DASH / "services_config.json")))
USER_SETTINGS_FILE   = _DASH / "user_settings.json"
GITHUB_OWNER = os.environ.get("GITHUB_OWNER", "")
# Claude-Code-Projektordner-Konvention: "/home/x/y" -> "-home-x-y"
CLAUDE_PROJECTS_DIR = Path(os.environ.get(
    "CLAUDE_PROJECTS_DIR",
    str(Path.home() / ".claude/projects" / ("-" + str(Path.home()).strip("/").replace("/", "-"))),
))

_CHF_TO_USD      = 1.12
_DAILY_WARN_CHF  = 5.0
_DAILY_BLOCK_CHF = 10.0
KI_GLOBAL_BOARD_ID = "ki-global-ablehnungen"
KI_LABEL           = "🤖 KI"

PROJEKTE_BASE      = Path(os.environ.get("PROJEKTE_DIR", str(Path.home() / "Projekte")))
CONTAINERS_BASE    = Path(os.environ.get("CONTAINERS_DIR", str(Path.home() / "containers")))

WA_FREIGABE_DIR    = Path(os.environ.get("FREIGABE_DIR", str(Path.home() / "freigabe")))
WA_WHITELIST_FILE  = WA_FREIGABE_DIR / "whitelist.json"
WA_PROFILES_FILE   = WA_FREIGABE_DIR / "user_profiles.json"

# ── Datei-Anhänge (Board/Karte) → lokal + OneDrive via rclone (2026-06-16) ──
# Lokale Arbeitskopie liegt bewusst auf der grossen Platte /mnt/daten (NICHT auf /,
# das ist knapp). OneDrive ist die synchronisierte Ablage im eigenen Ordner.
ATTACH_LOCAL_BASE  = Path(os.environ.get("ATTACH_LOCAL_BASE", "/mnt/daten/Dashboard-Anhaenge"))
ATTACH_MOUNT_GUARD = Path(os.environ.get("ATTACH_MOUNT_GUARD", "/mnt/daten"))  # muss gemountet sein
ATTACH_RCLONE_BIN  = os.environ.get("RCLONE_BIN", str(Path.home() / ".local/bin/rclone"))
ATTACH_RCLONE_REMOTE = os.environ.get("ATTACH_RCLONE_REMOTE", "FHEM:Dashboard-Anhaenge")
ATTACH_MAX_BYTES   = int(os.environ.get("ATTACH_MAX_BYTES", str(100 * 1024 * 1024)))  # 100 MB

OPENWEBUI_URL      = os.environ.get("OPENWEBUI_URL", "http://localhost:3001")
OPENWEBUI_EMAIL    = os.environ.get("OPENWEBUI_EMAIL", "")
OPENWEBUI_PASSWORD = os.environ.get("OPENWEBUI_PASSWORD", "")
# Default :11435 (Ollama-Logging-Proxy), NICHT :11434 — dort lauscht auf diesem Host
# nichts mehr. dashboard-api.service setzt OLLAMA_URL bewusst nicht (config.env-Kommentar
# 16.07.26: eine globale OLLAMA_URL überschreibt die skript-eigenen Proxy-Aufrufernamen
# /c/<skript> und macht das Proxy-Log unbrauchbar) — darum der Fallback hier, nicht dort.
OLLAMA_URL         = os.environ.get("OLLAMA_URL", "http://localhost:11435")
ISEHAUER_URL       = os.environ.get("ISEHAUER_URL", "http://localhost:3005")
ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
# Claude-Abo via lokale CLI-Bridge (claude-cli-bridge.service, Port 8950) — nutzt die
# eingeloggte Claude-CLI-Session = Abo, KEIN API-Guthaben. dashboard-api läuft als
# HOST-Prozess (uvicorn, kein Container) → 127.0.0.1, NICHT host.containers.internal.
CLAUDE_BRIDGE_URL  = os.environ.get("CLAUDE_BRIDGE_URL", "http://127.0.0.1:8950")
# Prioritäts-Farben für Ideen-Karten (label-Chip + Badge): hoch=rot, mittel=orange, niedrig=grün
PRIORITY_COLORS    = {"hoch": "#e5534b", "mittel": "#f5a623", "niedrig": "#3fb950"}
CHAT_HISTORY_FILE  = _DASH / "chat_history.jsonl"

# ── Projekt-Kategorien (zentrale Quelle der Wahrheit) ──────────────────────────
# Eine Kategorie ist ein Manifest-Feld pro Board. color = Hex (Dashboard/Isehauer),
# emoji = Badge. Erweiterbar: einfach Eintrag ergänzen.
CATEGORIES = {
    "hobby":          {"label": "Hobby",          "color": "#f6ad55", "emoji": "🎨"},
    "arbeit":         {"label": "Arbeit",         "color": "#4a90d9", "emoji": "💼"},
    "hausverwaltung": {"label": "Hausverwaltung", "color": "#68d391", "emoji": "🏠"},
    "buero":          {"label": "Büro",           "color": "#b794f4", "emoji": "🗄️"},
    "familie":        {"label": "Familie",        "color": "#fc8181", "emoji": "👨‍👩‍👧"},
    "gesundheit":     {"label": "Gesundheit",     "color": "#38b2ac", "emoji": "🩺"},
    "ideen":          {"label": "Ideen",          "color": "#ecc94b", "emoji": "💡"},
    "technik":        {"label": "Technik",        "color": "#2b6cb0", "emoji": "🖥️"},
    "lernen":         {"label": "Lernen",         "color": "#a3be4c", "emoji": "📚"},
    "finanzen":       {"label": "Finanzen",       "color": "#2f855a", "emoji": "💰"},
    "heimnetzwerk":   {"label": "Heimnetzwerk",   "color": "#667eea", "emoji": "🌐"},
    "ki-projekte":    {"label": "KI-Projekte",    "color": "#d53f8c", "emoji": "🤖"},
    "dashboard-meta": {"label": "Dashboard/Meta", "color": "#718096", "emoji": "🛠️"},
    "infrastruktur":  {"label": "Infrastruktur",  "color": "#319795", "emoji": "⚙️"},
}

# ── Projekt-Status (Lebenszyklus, orthogonal zu category) ─────────────────────
# Manifest-Feld "status" pro Board. Reihenfolge = fachliche Reihenfolge im Lebenszyklus,
# NICHT alphabetisch (Frontend nutzt diese Reihenfolge für Dropdown/Filter).
STATUSES = {
    "entwurf":        {"label": "Entwurf",        "color": "#a0aec0", "emoji": "📝"},
    "in_bearbeitung": {"label": "In Bearbeitung", "color": "#4a90d9", "emoji": "🚧"},
    "blockiert":      {"label": "Blockiert",      "color": "#e5534b", "emoji": "⛔"},
    "pausiert":       {"label": "Pausiert",       "color": "#f5a623", "emoji": "⏸️"},
    "abgeschlossen":  {"label": "Abgeschlossen",  "color": "#3fb950", "emoji": "✅"},
    "archiviert":     {"label": "Archiviert",     "color": "#718096", "emoji": "📦"},
}

# ── Modelle des Kanban-Automaten (Manifest-Feld "model" pro Board) ────────────
# Soll-Modell, mit dem der Automat (~/containers/kanban-automat/) dieses Projekt
# bearbeitet. Laufen mehrere Projekte gleichzeitig, entwickelt der Worker eine Stufe
# TIEFER und das hier gesetzte Modell prüft die Arbeit anschliessend (review.py).
# Reihenfolge = aufsteigende Stärke; Quelle der Wahrheit für die Stufen ist
# kanban-automat/models.py (TIERS) — diese Liste dient nur der PATCH-Validierung.
AUTOMAT_MODELS = {
    "claude-haiku-4-5": {"label": "Haiku 4.5", "hint": "einfache Karten, Doku/Notizen"},
    "claude-sonnet-5":  {"label": "Sonnet 5",  "hint": "Standard für Code-Projekte"},
    "claude-opus-4-8":  {"label": "Opus 4.8",  "hint": "komplexe/heikle Projekte"},
    "claude-fable-5":   {"label": "Fable 5",   "hint": "sehr lange autonome Läufe (teuer)"},
}
AUTOMAT_DEFAULT_MODEL = "claude-sonnet-5"

# Priorisierung pro Board für das Budget-Gate des Kanban-Automaten (priority_gate.py):
# "high" = läuft immer, ignoriert das Tages-Budget; "low" = läuft nur, solange die
# Tages-Tranche noch komfortabel Kopf hat (Headroom, s. priority_gate.LOW_HEADROOM);
# fehlt das Feld, gilt "normal" (läuft, solange /api/budget nicht "verbraucht" meldet).
AUTOMAT_PRIORITIES = {"high", "normal", "low"}
AUTOMAT_DEFAULT_PRIORITY = "normal"

AI_DEV_LOG_FILE    = Path(os.environ.get("AI_DEV_LOG", str(Path.home() / "ai_dev_log.jsonl")))

_AI_CONFIG_DEFAULTS = {
    "chat_model":                  "gemma3:12b",
    "ki_advisor_model":            "gemma3:12b",
    "ki_advisor_panel_models":     ["gemma3:12b", "qwen3:8b"],
    "vision_title_model":          "minicpm-v:latest",   # (Alt-Ollama, nicht mehr im Foto-Flow genutzt)
    "ki_critique_model":           "qwen2.5-coder:latest",
    "ki_explain_model":            "gemma3:12b",
    "session_monitor_model":       "qwen2.5-coder:latest",
    "bug_model":                   "qwen2.5-coder:latest",
    # Projekt-Erstellung: CLAUDE.md + Ideen-Brainstorm + Foto-Analyse (Bildersuche) laufen
    # übers Claude-Abo (Bridge 8950, /chat bzw. /vision) — KEINE lokale Ollama mehr.
    "project_ideas_model":         "claude-haiku-4-5",   # Doku-Task (CLAUDE.md/Ideen) — kein Reasoning nötig, Haiku reicht
    "project_vision_model":        "claude-sonnet-4-6",   # Foto→Titel/Tags via Claude-Abo (/vision)
    "chat_effort":                 "medium",
    "ki_advisor_effort":           "high",
    "ki_critique_effort":          "low",
    "ki_explain_effort":           "medium",
    "session_monitor_effort":      "low",
    "bug_effort":                  "medium",
    # F2 Token-Budget-Manager: Wochenbudget + Tag/Nacht-Fenster (max_pct der Tages-Tranche)
    "budget_week_tokens":          100000000,
    "budget_windows":              [{"from": 10, "to": 22, "max_pct": 50},
                                    {"from": 22, "to": 10, "max_pct": 80}],
    "budget_enforce":              True,
    # Reserve (in virtuellen Tagen) auf die Resttage-Tranche aufgeschlagen, damit die
    # Nacht-Läufe das Wochenbudget nicht bis auf null ausschöpfen (Entscheidung 27.07.26: "Woche
    # durch 8 statt 7 teilen" → ca. 1 Tag Puffer für eigene Projekte übrig).
    "budget_reserve_days":         1,
    # Sonntag-Burndown (08.08.26): am letzten Wochentag entfallen Tranche+Fenster,
    # erlaubt ist bis target_pct des Wochenlimits (Rest = Sicherheitsmarge vor dem
    # Abo-Reset So ~21:00). Details: budget_service.check_allowance.
    "budget_burndown_enabled":     1,
    "budget_burndown_target_pct":  98,
}

HOST = os.environ.get("DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://localhost:8798")
CORS_ORIGIN = "*"

# Keyword → Bug-Board Mapping (priorisiert, erstes Match gewinnt).
# EINZIGE Quelle — config_handler.py re-importiert nur, bug_tracking.py nutzt diese direkt.
_BUG_BOARD_KEYWORDS: list[tuple[list[str], str]] = [
    (["whatsapp", "spracherkennung", "voice kanban", "sprach kanban"], "voice-kanban-bugs"),
    (["homeassistant", "home assistant"], "homeassistant-app-bugs"),
    (["fhem"], "fhem-app-bugs"),
    (["zigbee", "z2m"], "zigbee2mqtt-app-bugs"),
    (["grafana"], "grafana-app-bugs"),
    (["paperless"], "paperless-app-bugs"),
    (["metabase"], "metabase-app-bugs"),
    (["open-webui", "openwebui", "open webui"], "open-webui-app-bugs"),
    (["gesprächsbegleiter", "gespraechsbegleiter"], "gespraechsbegleiter-app-bugs"),
    (["lernspiegel"], "lernspiegel-app-bugs"),
    (["n8n"], "n8n-app-bugs"),
    (["canon scanner", "canon"], "canon-scanner-app-bugs"),
    (["apple health"], "apple-health-app-bugs"),
    (["immo"], "immo-bugs"),
    (["deutsch lernen", "deutschlernen"], "deutsch-lernen-programm-bugs"),
]

_EFFORT_TEMP = {"low": 0.2, "medium": 0.5, "high": 0.8}

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("trigger-server")

# --- GitHub feedback channel (bug reports / card export from ili instances) ---
# Public identifiers only — the instance never holds a shared secret. Users sign
# in with their own GitHub account via the GitHub App device flow; the resulting
# user token lives in GITHUB_DATA_DIR (0600), never in user_settings.json.
GITHUB_ISSUES_REPO       = os.environ.get("ILI_GITHUB_ISSUES_REPO", "Toa1984/ili-public")
GITHUB_APP_CLIENT_ID     = os.environ.get("ILI_GITHUB_APP_CLIENT_ID", "")
GITHUB_DATA_DIR          = _DASH / "data" / "github"
GITHUB_AUTH_FILE         = GITHUB_DATA_DIR / "github_auth.json"
GITHUB_ISSUES_STATE_FILE = GITHUB_DATA_DIR / "github_issues.json"
GITHUB_REPORTS_LOG       = GITHUB_DATA_DIR / "github_reports.log"
GITHUB_REPORTS_PER_DAY   = int(os.environ.get("ILI_GITHUB_REPORTS_PER_DAY", "10"))
