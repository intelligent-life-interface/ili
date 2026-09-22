---
name: architektur-review
description: "Architektur-Review für neue oder bestehende Homeserver-Projekte. Erst review.sh laufen lassen (prüft Haus-Konventionen statisch: CLAUDE.md+Tags, Root-Index, systemd-Unit ohne User=, Ports dokumentiert, Secrets in config.env, Debug-Logs, Dateien <500 Zeilen, Kanban-Board, privates Git, plus container-check.sh sofern installiert). Danach die Urteils-Checkliste unten durchgehen (Datenfluss, DB-Wahl, Exposure, KI-Routing). Nutze bei \"Review\", \"Architektur prüfen\", \"passt das Projekt zum Stack\", vor dem ersten produktiven Deploy eines neuen Containers."
---

# architektur-review — Projekt gegen die Haus-Konventionen prüfen

Zweistufig: **1)** Skript prüft die harten Regeln (deterministisch, gratis),
**2)** Claude beantwortet die Urteils-Fragen unten und fasst beides zu einem
kurzen Review zusammen (Befunde + konkrete Fixes, keine Roman-Reports).

## Schritt 1: Statische Checks

```bash
~/.claude/skills/architektur-review/review.sh ~/containers/<name>
~/.claude/skills/architektur-review/review.sh ~/Projekte/<name> --name <containername>
```

Ausgabe: OK/WARN/FAIL pro Regel. Exit 1 bei FAILs. Ist der Skill
`container-architektur` installiert (`~/.claude/skills/container-architektur/container-check.sh`),
ruft `review.sh` ihn automatisch für das Projekt mit auf und übernimmt dessen
OK/WARN/FAIL-Befunde in die Gesamtzählung — sonst wird der Abschnitt übersprungen.

## Schritt 2: Urteils-Checkliste (macht Claude, kein Skript)

**Daten & Persistenz**
- Passt die DB-Wahl? Konvention: SQLite/DuckDB pro Projekt (EINE Datei), InfluxDB nur für Zeitreihen (Org `home`), nie neue DB-Server ohne Grund.
- Wo liegen die Daten (Volume/Named Volume/Host-Pfad)? Backup-Story vorhanden (rclone-OneDrive / /mnt/daten)?
- Gehen Sensordaten den Standard-Weg (MQTT 1884 → Telegraf → InfluxDB) statt Eigenbau?

**Integration statt Duplikat**
- Nutzt es bestehende Dienste (kalender-service, whisper-api, paperless, Ollama <WINDOWS_PC_IP>:11434 via Proxy :11435) statt eigene Kopien?
- Gibt es einen bestehenden Container, der das fast schon kann? (Root-CLAUDE.md-Tabelle scannen)

**Exposure & Sicherheit**
- Nur LAN nötig? → Port auf 127.0.0.1 oder <SERVER_IP> binden, Caddy `*.intranet.<DOMAIN>`.
  - **Wichtig:** Prüfe, dass Caddy den Dienst reach kann. Der Host hat zwei NICs (eth0 <SERVER_IP_ETH0> DHCP / eth1 <SERVER_IP> static); Podman setzt `host.containers.internal` auf Default-Route (<SERVER_IP_ETH0>). Dienste mit <SERVER_IP>-Bind sind über `host.containers.internal:port` nicht erreichbar. Lösung: Caddyfile nutzt `{$CADDY_INTRANET_IP}` statt `host.containers.internal` (siehe `security-konventionen` §3 und Projekt `security-bug`).
- Internet-Exposure? → ZUERST Cloudflare-Access-Policy klären, dann Tunnel (Regel: Access vor Tunnel).
- Läuft alles rootless? Keine sudo-Abhängigkeiten zur Laufzeit?

**KI-Routing & Kosten**
- Einfache/wiederholte KI-Tasks → Ollama (lokal, gratis, via Logging-Proxy :11435 mit X-Caller); Claude nur wo nötig.
- Psychologie/Personen-Einschätzung → neustes Claude-Modell, nur Hinweise, keine Diagnosen.

**Betrieb**
- Was passiert bei Crash/Reboot? (Restart-Policy, WantedBy=default.target, enable gesetzt?)
- Health-Check-Endpoint vorhanden und von aussen prüfbar?
- Logs: `podman logs` brauchbar? Landen sie im Log-Viewer (8899)?

## Ergebnis-Format

Kurzer Review-Block: 3–6 Befunde nach Priorität (FAILs zuerst), je mit
konkretem Fix-Befehl/Datei. Bei bestehendem Projekt: Befunde als Notiz an die
Bezugskarte im Projekt-Board (`automat_cli.py note`), nicht nur in den Chat —
`automat_cli.py` legt selbst keine neuen Karten an.
