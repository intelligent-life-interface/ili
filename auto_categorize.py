#!/usr/bin/env python3
"""auto_categorize.py — einmalige/erneuerbare Vorkategorisierung aller Top-Level-Projekte.

Ein gebündelter Ollama-Call (token-sparend, nur Namen+Tags — nicht den Inhalt) ordnet jedes
Projekt GENAU einer der 5 Kategorien zu (constants.CATEGORIES). Ergebnis via PATCH /boards/<id>
{category} -> Manifest -> Dashboard-Kachel (Daemon). Der User korrigiert
einzelne per Schnellknopf.

Nur Projekte OHNE Kategorie werden angefasst (idempotent; --force überschreibt alle).
Aufruf:  python3 auto_categorize.py [--force]
"""
import os
import sys
import json
import argparse
import urllib.request
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from constants import CATEGORIES, BOARDS_DIR
from app.storage.manifest_repository import ManifestRepository
from project_creator import _ollama_text

DASHBOARD_URL = os.getenv("DASHBOARD_URL", "http://localhost:8798")  # FastAPI seit 2026-06-10
TAGS_INDEX = BOARDS_DIR / "tags-index.json"
VALID = set(CATEGORIES.keys())

# grobe Heuristik als Fallback (wenn Ollama nichts/Unsinn liefert)
_HEURISTIC = [
    ("gesundheit",     ("health", "gesund", "ekg", "herz", "heart", "kardia", "rücken", "ruecken",
                        "reha", "ergotherap", "therap", "adhs", "puls", "blutdruck", "wellness")),
    ("lernen",         ("lern", "matur", "schul", "schüler", "bildung", "vokabel", "sprachen",
                        "vorlesen", "nachhilfe", "studium", "forvo", "biologie", "chemie")),
    ("finanzen",       ("steuer", "finanz", "rechnung", "kassenbon", "budget", "konto", "zahlung")),
    # KI/AI-Software (Modelle, Sprachverarbeitung, Ollama/Claude-Anbindung) — NICHT Technik.
    ("ki-projekte",    ("ollama", "ki-", "claude", "llm", "huggingface", "whisper", "tts",
                        "sprachmodell", "neurofeedback", "prompt", "chatbot")),
    # Dashboard/Kanban-System selbst (Boards, Karten, project-index) — eigene Kategorie.
    ("dashboard-meta", ("dashboard", "kanban")),
    # Server-/Container-Software & generelle Homeserver-Infra (kein Hardware-Projekt!) — NICHT Technik.
    ("infrastruktur",  ("server", "container", "infra", "docker", "podman", "n8n", "grafana",
                        "influx", "automation", "rpa", "webui", "workflow", "log", "bug", "scanner",
                        "paperless", "wiki", "webapp", "routing", "vpn", "netzwerk", "wlan", "modbus",
                        "mqtt", "zigbee", "signal", "whatsapp", "bot", "cloudbeaver", "backup", "nas",
                        "homeassistant", "home-assistant", "git-auto")),
    # Technik = NUR Hardware-Projekte (kein KI/Dashboard/reine Software, s. CLAUDE.md-Vorgabe 09.07.2026).
    ("technik",        ("raspberry", "arduino", "esp32", "esp8266", "beamer", "kamera", "rtl-sdr",
                        "rtl_433", "sdr", "npu", "cockpit", "joystick", "hotas", "saitek", "thrustmaster",
                        "oszilloskop", "bioamp", "löten", "loeten", "platine", "3d-druck", "notebook",
                        "nokia", "metallsucher")),
    ("hausverwaltung", ("immobil", "wohnung", "haus", "miet", "fassade", "sanierung", "garten",
                        "heizung", "abnahme")),
    ("familie",        ("familie", "stammbaum", "kind")),
    ("hobby",          ("velo", "foto", "astro", "musik", "stimme", "saiten", "kristall", "mineral",
                        "biene", "spiel", "freizeit", "kunst")),
]


def _load_tags():
    try:
        return json.load(open(TAGS_INDEX)).get("projects", {})
    except Exception:
        return {}


def _heuristic(name, tags):
    blob = (name + " " + " ".join(tags)).lower()
    for cat, keys in _HEURISTIC:
        if any(k in blob for k in keys):
            return cat
    return "hobby"


def _heuristic_or_none(name, tags, desc=""):
    """Wie _heuristic, aber OHNE 'hobby'-Fallback (None wenn nichts matcht) — so kann der
    Aufrufer entscheiden, ob er stattdessen Ollama fragt oder 'ideen' nimmt."""
    blob = (name + " " + " ".join(tags) + " " + desc).lower()
    for cat, keys in _HEURISTIC:
        if any(k in blob for k in keys):
            return cat
    return None


def categorize_one(name, tags=None, desc="", use_ai=False):
    """Beste Kategorie für EIN neu erstelltes Projekt/Idee (Erstellungs-Hotpath).

    Reihenfolge: (1) Heuristik (gratis/instant, Schlagworte aus Name+Tags+Beschreibung).
    (2) Nur wenn nichts matcht UND use_ai → EIN kleiner Claude-Abo-Call (Ollama-Fallback).
    (3) Fallback 'ideen'
    (= unkategorisiert/frisch). Gibt NUR die Kategorie zurück; setzt bewusst KEINE Priorität
    (eisenhower bleibt leer → neue Projekte erscheinen als 📥 'noch nicht einsortiert').

    Args:
        name:   Projektname.
        tags:   Liste Tags (optional).
        desc:   Beschreibung (optional, fliesst in die Heuristik ein).
        use_ai: True → bei Heuristik-Fehlschlag Claude-Abo befragen (nur wo Latenz egal ist,
                z.B. async Foto-Analyse; im schnellen create_board-Pfad False lassen).
    Returns:
        Kategorie-Key aus constants.CATEGORIES (immer gültig).
    """
    tags = tags or []
    cat = _heuristic_or_none(name, tags, desc)
    if cat:
        return cat
    if use_ai:
        try:
            # Claude-Abo zuerst (User-Präferenz 27.06.2026), Ollama nur als Fallback.
            mapping = _ask_claude([("_new", name, tags)]) or _ask_ollama([("_new", name, tags)])
            c = (mapping or {}).get("_new")
            if c in VALID:
                return c
        except Exception:
            pass
    return "ideen"


def _ask_ollama(projects):
    """projects: [(id, name, tags)] -> {id: category}. Ein Call, JSON-Antwort.

    Modell aus ai_config['categorize_ollama_model'] (Default gemma3:12b — hält das JSON-Format
    zuverlässig ein, anders als mistral). Seit 27.06.2026 nur noch FALLBACK hinter Claude (s. _ask_ai).
    """
    from project_creator import _load_ai_config
    model = _load_ai_config().get("categorize_ollama_model", "gemma3:12b")
    lines = []
    for pid, name, tags in projects:
        lines.append(f"- {pid} | {name} | Tags: {', '.join(tags) or '-'}")
    cat_list = ", ".join(f"{k} ({v['label']})" for k, v in CATEGORIES.items())
    prompt = (
        "Ordne jedes Projekt GENAU einer dieser Kategorien zu (nur den Key verwenden):\n"
        f"{cat_list}\n\n"
        "Projekte:\n" + "\n".join(lines) +
        '\n\nAntworte AUSSCHLIESSLICH als JSON-Objekt {"projekt-id": "kategorie-key", ...}. Kein Text drumherum.'
    )
    raw = _ollama_text(prompt, num_predict=1800, temperature=0.1, timeout=240, model=model)
    s, e = raw.find("{"), raw.rfind("}")
    if s == -1 or e <= s:
        return {}
    try:
        obj = json.loads(raw[s:e + 1])
    except Exception:
        return {}
    return {k: v for k, v in obj.items() if v in VALID}


def _ask_claude(projects, model=None):
    """Wie _ask_ollama, aber via Claude-Abo (CLI-Bridge Port 8950, KEIN API-Guthaben).

    Deutlich treffsicherer als das lokale mistral (das das JSON-Format nicht einhält).
    Modell aus ai_config['categorize_model'] (Default Haiku — schnell + genug für Klassifikation).
    Gibt {} bei Fehler zurück → Aufrufer fällt auf Ollama/Heuristik zurück.
    """
    from project_creator import _claude_abo_text, _load_ai_config
    if not model:
        model = _load_ai_config().get("categorize_model", "claude-haiku-4-5-20251001")
    cat_list = ", ".join(f"{k} ({v['label']})" for k, v in CATEGORIES.items())
    lines = [f"- {pid} | {name} | Tags: {', '.join(tags) or '-'}" for pid, name, tags in projects]
    system = (
        "Du kategorisierst Projekte für ein Kanban-Board. Antworte AUSSCHLIESSLICH mit einem "
        'JSON-Objekt {"projekt-id": "kategorie-key", ...} — NUR die vorgegebenen Kategorie-Keys, '
        "kein Fliesstext, kein Markdown, keine erfundenen Kategorien."
    )
    prompt = (
        "Ordne jedes Projekt GENAU einer dieser Kategorien zu (nur den Key links der Klammer):\n"
        f"{cat_list}\n\nProjekte:\n" + "\n".join(lines)
    )
    try:
        raw = _claude_abo_text(system, prompt, model=model, temperature=0.0,
                               max_tokens=60 + len(projects) * 24, timeout=180)
    except Exception:
        return {}
    s, e = raw.find("{"), raw.rfind("}")
    if s == -1 or e <= s:
        return {}
    try:
        obj = json.loads(raw[s:e + 1])
    except Exception:
        return {}
    return {k: v for k, v in obj.items() if v in VALID}


def _ask_ai(projects):
    """KI-Zuordnung Claude-first (User-Präferenz 27.06.2026): Claude-Abo (Bridge 8950) zuerst,
    nur bei Lücken Ollama (gemma3:12b) nachfüllen. Heuristik bleibt der finale Fallback
    (im Aufrufer via `_heuristic`)."""
    mapping = _ask_claude(projects)
    missing = [p for p in projects if p[0] not in mapping]
    if missing:
        mapping.update(_ask_ollama(missing))
    return mapping


def _patch(board_id, category):
    req = urllib.request.Request(
        f"{DASHBOARD_URL}/boards/{urllib.parse.quote(board_id)}",
        data=json.dumps({"category": category}).encode(),
        method="PATCH", headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read()
        return True
    except Exception as e:
        print(f"  PATCH {board_id} fehlgeschlagen: {e}")
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="auch bereits kategorisierte überschreiben")
    args = ap.parse_args()

    manifest = ManifestRepository().load()
    tags_idx = _load_tags()

    def parents(b):
        ids = b.get("parent_ids")
        if ids is not None:
            return ids if isinstance(ids, list) else [ids]
        return [b["parent_id"]] if b.get("parent_id") else []

    targets = []
    for b in manifest.get("boards", []):
        bid = b.get("id")
        if not bid or parents(b):                      # nur Top-Level-Projekte
            continue
        if b.get("category") and not args.force:
            continue
        name = b.get("name") or bid
        tags = (tags_idx.get(bid) or {}).get("tags", [])
        targets.append((bid, name, tags))

    if not targets:
        print("Nichts zu kategorisieren (alle haben schon eine Kategorie; --force erzwingt).")
        return

    print(f"Kategorisiere {len(targets)} Projekte via Claude-Abo (Ollama-Fallback) …")
    mapping = _ask_ai(targets)
    print(f"KI lieferte {len(mapping)} Zuordnungen.")

    done = {}
    for bid, name, tags in targets:
        cat = mapping.get(bid) or _heuristic(name, tags)
        if _patch(bid, cat):
            done[bid] = cat
            print(f"  {bid:30s} -> {cat}")
    # Verteilung
    from collections import Counter
    print("Verteilung:", dict(Counter(done.values())))
    print(json.dumps({"categorized": len(done)}))


if __name__ == "__main__":
    main()
