---
name: container-scaffold
description: Setzt ein neues Homeserver-Container-Projekt vollständig auf — Projektordner unter ~/containers/, FastAPI-Gerüst mit Debug-Logging, Containerfile, rootless-Podman-systemd-Unit (ohne User=), Sub-CLAUDE.md mit Tags-Zeile und Kanban-Board. Nutze bei "neues Projekt", "neuer Container", "neuen Service aufsetzen", "scaffold", "Gerüst". Danach Root-CLAUDE.md-Tabellen + Router-Skill ergänzen (Skript gibt fertige Zeilen aus).
---

# container-scaffold — Neues Container-Projekt in einem Schritt

Erstellt ein komplettes Projekt nach dem Home-Stack-Muster (Vorbild `camtimport`):
Ordner, FastAPI-App (Debug-Logging, `/health`), Containerfile, systemd-Unit, `CLAUDE.md` mit Tags, Kanban-Board.

## Wann einsetzen
- User will einen neuen Container/Service/eine neue WebGUI aufsetzen
- Ein bestehendes Projekt braucht einen Nachbar-Service nach gleichem Muster

**Nicht einsetzen:** für reine Skripte ohne Container (→ `~/bin/`), oder wenn das Projekt unter `~/Projekte/` ohne Container leben soll (→ `create_project/main.py`).

## Nutzung

```bash
# Freien Port finden (88xx-Bereich, prüft ss + systemd-Units + Root-CLAUDE.md):
~/.claude/skills/container-scaffold/scaffold.sh --suggest-port

# Projekt anlegen:
~/.claude/skills/container-scaffold/scaffold.sh <name> \
  --port 8827 \
  --desc "Kurzbeschreibung" \
  --tags "tag1, tag2, tag3" \
  [--network monitoring] \        # wenn InfluxDB/MQTT gebraucht wird
  [--volume /srv/<name>] \        # Host-Daten-Mount → /data:Z
  [--no-board] \                  # kein Kanban-Board erstellen
  [--build]                       # direkt bauen + starten + Health-Check
```

Ohne `--port` wählt das Skript selbst einen freien 88xx-Port.
Es überschreibt **nie** — existierender Ordner oder Unit ⇒ Abbruch.

## Was danach noch zu tun ist (macht Claude direkt)

Das Skript druckt am Ende fertig formatierte Zeilen für:
1. Root-`~/CLAUDE.md`: Container-Tabelle **und** Tag-Index-Tabelle ergänzen
2. Router-Skill `~/.claude/skills/homeserver-projekte/SKILL.md` ergänzen
3. Privates GitHub-Repo anlegen (`GH_ADMIN_TOKEN`), Push mit `GH_PUSH_TOKEN`
4. **Caddy-Intranet-URL (IMMER, User-Regel 07/2026):** im `:8443`-Block von `~/containers/caddy/Caddyfile` vor dem Catch-all ergänzen: `@<name> host <name>.intranet.<DOMAIN> <name>.t.<DOMAIN>` + `handle @<name> { reverse_proxy host.containers.internal:<host-port> }`, dann `systemctl --user restart container-caddy.service`. Test: `curl -sk --resolve <name>.intranet.<DOMAIN>:443:<SERVER_IP> https://<name>.intranet.<DOMAIN>/`. Liste in `~/containers/caddy/docs/subdomains-dns.md` nachführen. Split-DNS ist Wildcard — kein DNS-Eintrag nötig.

## Konventionen, die das Skript einhält
- rootless Podman, Image `localhost/<name>:latest`, Container-Port 8000
- systemd-Unit nach camtimport-Muster — **kein `User=`** (sonst `216/GROUP`)
- Tags-Zeile oben in der Sub-CLAUDE.md (für Root-Index + Router)
- Debug-Logging in der FastAPI-App ab Zeile 1 (CLAUDE.md-Vorgabe)
- Kanban-Board via `create_project/kanban_sync.sync_claude_md_to_board` (pfadunabhängig, funktioniert auch für `~/containers/`)
- Feste `--session-id` (uuidgen) + `-n <name>` pro Projekt, dokumentiert in der Sub-CLAUDE.md — Wiedereinstieg immer per `claude --resume <id>` statt neuer Session

## Regeln (seit 09.09.2026)

Containerfile und Unit folgen dem Skill `container-architektur` (vollqualifiziertes
Basis-Image, Deps vor Code, `app/healthcheck.py` + `HEALTHCHECK`, `--memory/--cpus/
--health-cmd` in der Unit). `scaffold.sh` ruft am Ende `container-check.sh <name>` auf;
ein FAIL wird vor dem Deploy behoben.
