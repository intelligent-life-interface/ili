# Home Stack Dashboard

[![Release](https://img.shields.io/github/v/release/Toa1984/ili-public?display_name=tag&sort=semver)](https://github.com/Toa1984/ili-public/releases)
[![Release images](https://github.com/Toa1984/ili-public/actions/workflows/release.yml/badge.svg)](https://github.com/Toa1984/ili-public/actions/workflows/release.yml)
[![ghcr.io](https://img.shields.io/badge/ghcr.io-toa1984%2Fili-blue?logo=docker)](https://github.com/Toa1984/ili-public/pkgs/container/ili)
[![Docker Hub](https://img.shields.io/badge/Docker%20Hub-toa1984%2Fili-blue?logo=docker)](https://hub.docker.com/r/toa1984/ili)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-green)](LICENSE)

Ein persönliches Homelab-Dashboard mit Multi-Board Kanban, KI-Chat, Projekt-Management und Homelab-Automatisierung.

**Stack:** Python 3.11 / FastAPI · nginx · JSON-basierte Boards · Anthropic Claude (Abo oder API-Key, Pflicht) · Kanban-Automat (headless Claude-Worker) · Ollama (optional)

> **Hinweis zum Repository:** Dieser Stand wird aus einem privaten Werkstatt-Repo
> erzeugt und als ein Commit je Übernahme veröffentlicht. Direkt hier angelegte
> Branches werden beim nächsten Abgleich überschrieben — Beiträge deshalb bitte
> als Fork und Pull Request, nicht als Branch in diesem Repo.

> **Du willst ili nur installieren?** → **[QUICKSTART.md](QUICKSTART.md)** —
> entweder fertige Images von `ghcr.io/toa1984/ili{,-web,-terminal}` ziehen
> (`docker run --rm --pull always -v "$PWD":/out ghcr.io/toa1984/ili init && docker compose up -d`,
> kein Clone nötig — das Image liefert seine Compose-Dateien selbst) oder
> `git clone` + `docker compose up -d --build`. Dieselben Images gibt es auch auf
> Docker Hub als `toa1984/ili{,-web,-terminal}`. Dieses README beschreibt daneben
> den Aufbau und die Installation aus dem Quelltext. Releases: [docs/RELEASING.md](docs/RELEASING.md).

---

## Features

| Feature | Beschreibung |
|---|---|
| **Multi-Board Kanban** | Boards per JSON, unbegrenzt viele, mit Spalten/Karten/Labels/Anhängen |
| **KI-Chat** | Chat-Interface mit Claude (Abo oder API-Key), optional Ollama lokal; Intent-Klassifikation |
| **KI-Automatisierung** | Auto-Tagger, Karten-Brainstorm, Duplikat-Erkennung, KI-Sortierer |
| **Projekt-Management** | Board ↔ CLAUDE.md Sync, Projekt-Erstellung via Foto/Formular, Terminal-Integration |
| **Log-Scanner** | Fehler aus systemd journal + Datei-Logs → Kanban-Karten |
| **Service-Übersicht** | Alle Dienste mit URLs, Status und Projekt-Links |
| **Web-Adressen** | Automatisch aus Caddy-Config generierte interne/externe URL-Liste |
| **Kosten-Monitor** | Claude-API-Kosten und Ollama-Nutzung verfolgen |
| **Anhänge** | Board-Karten-Anhänge lokal + OneDrive via rclone |
| **Mobile-UI** | Kompaktes `/m/`-Interface für Smartphones |
| **Bot-Status** | Übersicht aller Claude-Code-Sessions in tmux |

---

## Voraussetzungen

- Linux mit systemd (rootless Podman oder Docker)
- Python 3.11+
- nginx (für das Frontend-Serving)
- Claude-Zugang — **Pflicht** (ohne ihn bleibt jedes neu angelegte Projekt eine leere Vorlage; die Projekt-Vorbereitung, der Board-Assistent und der Kanban-Automat laufen über die Claude-Bridge im Terminal-Container). **Eines von beiden genügt:**
  - ein Claude-Abo (Claude Code CLI, Token via `claude setup-token` → `CLAUDE_CODE_OAUTH_TOKEN`), **oder**
  - ein Anthropic API-Key (`ANTHROPIC_API_KEY`)
- Ollama ist **nicht** nötig (optional als lokaler Fallback, `OLLAMA_URL`)

---

## Installation

### 1. Repository klonen

```bash
git clone <repo-url> ~/containers/dashboard
cd ~/containers/dashboard
```

### 2. Python-Abhängigkeiten installieren

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Konfiguration anlegen

```bash
cp scan_config.example.json scan_config.json   # Netzwerk-Scan-Subnetz
cp log_sources.example.json log_sources.json   # Log-Quellen
cp services_config.example.json services_config.json  # Eigene Dienste
cp project_map.example.json project_map.json   # Projekt-Pfad-Mapping
```

Erstelle eine `config.env` mit den benötigten Umgebungsvariablen (Abschnitt [Konfiguration](#konfiguration)).

### 4. nginx-Container starten (Frontend)

**Wichtig:** die produktive `nginx.conf` in diesem Repo erzwingt einen HTTPS-Redirect
und bindet die gitignorete, geheimnishaltige `projterm-locations.conf` ein — auf einer
fremden Maschine ohne vorgelagerten Caddy/TLS-Proxy startet nginx damit gar nicht. Für
eine eigenständige Installation stattdessen **`deploy/nginx-portable.conf`** verwenden
(kein HTTPS-Zwang, kein Secrets-Include):

```bash
# Rootless Podman:
podman run -d --name dashboard \
  -p 80:80 \
  -v $(pwd)/html:/usr/share/nginx/html:ro,Z \
  -v $(pwd)/deploy/nginx-portable.conf:/etc/nginx/conf.d/default.conf:ro,Z \
  docker.io/library/nginx:alpine
```

Für HTTPS empfiehlt sich ein Reverse-Proxy (z.B. Caddy) davor.

**Alternative:** `docker compose -f docker-compose.yml -f docker-compose.terminal.yml up -d`
(bzw. `podman-compose …`) baut und startet Backend + Frontend + Terminal-Container (mit
Claude-Bridge und Kanban-Automat — Standard seit v0.1.7, ohne sie bleiben neue Projekte
leere Vorlagen) aus den mitgelieferten Compose-Dateien — deckt diesen und den nächsten
Schritt in einem Rutsch ab, danach direkt bei Schritt 6 weiter.

### 5. FastAPI-Backend starten

```bash
source venv/bin/activate
source config.env
uvicorn app.main:app --host 0.0.0.0 --port 8798
```

**Als systemd-User-Service:**

```bash
# ~/.config/systemd/user/dashboard-api.service
[Unit]
Description=Dashboard FastAPI Server (Port 8798)
After=network-online.target

[Service]
Type=simple
Restart=on-failure
EnvironmentFile=%h/containers/dashboard/config.env
WorkingDirectory=%h/containers/dashboard
ExecStart=%h/containers/dashboard/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8798
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now dashboard-api.service
```

### 6. Erste Boards anlegen

Das Dashboard erstellt beim ersten Start automatisch ein leeres `boards/`-Verzeichnis. Boards können über das Web-Interface angelegt werden (`/projekt.html`) oder manuell als JSON in `boards/`.

---

## Konfiguration

Alle Einstellungen erfolgen über Umgebungsvariablen. Erstelle `~/containers/dashboard/config.env`:

```env
# Pflicht: Domain für interne URLs (z.B. "yourdomain.example")
DASHBOARD_DOMAIN=yourdomain.example

# Basis-URLs (anpassen wenn Dashboard nicht auf localhost läuft)
DASHBOARD_URL=http://localhost:8798
DASHBOARD_HOST_IP=127.0.0.1       # IP für Auto-Detect-Links im generierten HTML

# KI-Zugang: PFLICHT — eines von beiden genügt (ohne: Projekte bleiben leere Vorlagen)
# a) Claude-Abo (Token aus `claude setup-token`)
CLAUDE_CODE_OAUTH_TOKEN=
# b) Anthropic API-Key
ANTHROPIC_API_KEY=sk-ant-...

# Ollama (optional — lokaler Fallback, nicht nötig)
# OLLAMA_URL=http://localhost:11434

# GitHub-Integration (optional — für automatisches Repo-Anlegen)
GITHUB_OWNER=your-github-username
GH_ADMIN_TOKEN=ghp_...

# Gesprächsbegleiter externer Hostname (optional)
GB_EXTERNAL_HOST=                  # z.B. "yourapp.yourdomain.example"

# Anhänge (optional — für Board-Karten-Dateien)
ATTACH_LOCAL_BASE=/mnt/data/Dashboard-Anhaenge
ATTACH_RCLONE_REMOTE=onedrive:Dashboard-Anhaenge

# Open WebUI-Integration (optional)
OPENWEBUI_URL=http://localhost:3001
OPENWEBUI_EMAIL=
OPENWEBUI_PASSWORD=

# Isehauer-Widget (optional)
ISEHAUER_URL=http://localhost:3005
```

### Netzwerk-Scan-Konfiguration

Bearbeite `scan_config.json` (aus `scan_config.example.json`):

```json
{
    "ranges": ["192.168.1.0/24"],
    "ports": [22, 80, 443, 8080, 8443, ...],
    "timeout_tcp": 0.5,
    "timeout_http": 2.0,
    "threads": 100,
    "exclude_ips": ["192.168.1.0", "192.168.1.255"]
}
```

### Service-Übersicht konfigurieren

Bearbeite `services_config.json` (aus `services_config.example.json`). Jeder Dienst hat URL, Icon, Beschreibung und optionale Token-Platzhalter (`{ENV_VAR}`).

### Web-Adressen aus Caddy generieren (optional)

Wenn Caddy als Reverse-Proxy läuft, generiert `web_adressen_generator.py` automatisch die Service-Liste aus dem Caddyfile:

```bash
DASHBOARD_DOMAIN=yourdomain.example python3 web_adressen_generator.py
```

---

## Verzeichnisstruktur

```
dashboard/
├── app/                  # FastAPI-App (main.py, api/, services/, storage/)
├── html/                 # Frontend (JS, CSS, HTML-Seiten)
│   ├── js/               # JavaScript-Module
│   ├── css/              # Stylesheets
│   ├── m/                # Mobile-Interface
│   └── spiegel/          # Digitalspiegel-Seiten
├── boards/               # Kanban-Boards (JSON, nicht versioniert)
├── docs/                 # Interne Entwicklungsdokumentation
├── requirements.txt      # Python-Abhängigkeiten
├── constants.py          # Zentrale Konfigurationskonstanten
├── nginx.conf            # nginx-Konfiguration
├── scan_config.example.json
├── log_sources.example.json
├── services_config.example.json
└── project_map.example.json
```

---

## API

Die REST-API läuft auf Port 8798. Wichtige Endpunkte:

| Endpunkt | Methode | Beschreibung |
|---|---|---|
| `/boards` | GET | Alle Boards auflisten |
| `/boards/{id}` | GET/PUT | Board lesen/schreiben |
| `/api/chat` | POST | KI-Chat (Claude, optional Ollama) |
| `/api/client-config` | GET | Frontend-Konfiguration (DASHBOARD_DOMAIN etc.) |
| `/scan-logs` | GET | Log-Scanner starten |
| `/health` | GET | Health-Check |

Vollständige API-Dokumentation: `docs/API.md` oder Swagger-UI unter `/docs` (nur im Debug-Modus).

---

## Systemd-Timer für automatische Jobs

```bash
# Nightly: Web-Adressen regenerieren, KI-Tags aktualisieren
# Beispiel-Timer — Zeitpläne im ANLEITUNG_RESTARBEITEN.md
```

---

## Versionierung

- `VERSION` im Repo-Root ist die einzige Quelle (semver, manuell gepflegt); sie
  wird ins Image kopiert und unter `GET /api/version` ausgeliefert
  (`{version, commit, build_date, channel}`).
- Releases sind Git-Tags `vX.Y.Z`; Beta-Stände sind GitHub-Pre-Releases mit Tag
  `vX.Y.Z-beta.N`. `ILI_UPDATE_CHANNEL=stable|beta` in `.env` wählt den Kanal.
- `ILI_COMMIT`/`ILI_BUILD_DATE` werden als Build-Args gesetzt (Update-Skript);
  ein blosses `compose build` lässt sie auf `unknown`.

## Haftungsausschluss

Diese Software wird kostenlos und „as-is" bereitgestellt — siehe [DISCLAIMER.md](DISCLAIMER.md) für die
vollständigen Bedingungen. Wichtigste Punkte:

- **Sie sind verantwortlich** für API-Kosten (Tokenverbrauch), Sicherheit Ihrer Installation
  und Versionsstandigkeit (Updates, Security-Patches).
- **Versionsverantwortung via Git:** Die Fassung des Haftungsausschlusses dokumentiert sich über
  die Git-History. Nutzer können nachvollziehen, welche Fassung mit ihrer Installation mitgeliefert wurde:

  ```bash
  # Prüfen, welche DISCLAIMER.md-Version Sie haben
  git log -1 --oneline DISCLAIMER.md    # letzter Commit dieser Datei
  git show <commit-hash>:DISCLAIMER.md   # genaue Fassung zu einem Commit
  ```

Für weitere Details: [DISCLAIMER.md](DISCLAIMER.md).

## Lizenz

SPDX-License-Identifier: AGPL-3.0-or-later

Copyright (C) 2026 Toa1984

Dieses Projekt steht unter der GNU Affero General Public License v3 (oder später) — voller
Text in [LICENSE](LICENSE). Kurz zusammengefasst: freie Nutzung, Veränderung und
Weiterverteilung, aber jede über ein Netzwerk erreichbare modifizierte Version muss ihren
Quellcode ebenfalls offenlegen (Netzwerk-Copyleft, Art. 13 AGPL).

---

## Beitragen

Contributions sind willkommen. Die Repos sind derzeit **privat** — Zugang gibt es
auf Anfrage als eingeladener Collaborator (Kontakt: Mastodon
[@Toa1984@mastodon.social](https://mastodon.social/@Toa1984)). Danach wie gewohnt:
Issues und Pull Requests via GitHub.

Für Code-Beiträge gilt ein kurzes [CLA](CLA.md), damit neben der AGPL eine
kommerzielle Dual-Lizenz möglich bleibt.
