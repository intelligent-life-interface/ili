---
name: container-architektur
description: Regeln für Container-Images, rootless-Podman-Units und Compose im Home-Stack — Basis-Image-Wahl (Debian-slim, vollqualifiziert, kein EOL), Layer-Reihenfolge und Build-Cache, was ins Runtime-Image gehört, Healthcheck auf echten API-Pfad (bei Podman per --health-cmd in der Unit), --memory/--cpus-Limits, Trivy-Scan, Testversion zuerst. Enthält container-check.sh (OK/WARN/FAIL wie architektur-review). Nutze bei allem, was Containerfile/Dockerfile, Image-Grösse, Multi-Stage, Alpine vs. Debian, Layer/Cache, HEALTHCHECK, Ressourcen-Limits, podman run-Flags in einer systemd-Unit, docker-compose-Services, CVE/Trivy oder „Container optimieren/verkleinern/aufräumen" betrifft — BEVOR du ein Containerfile oder eine Unit schreibst oder änderst. NICHT fürs Anlegen eines neuen Projekts (container-scaffold, wendet diese Regeln an) und NICHT für den Code im Container (backend-architektur).
---

# container-architektur — Regeln für Image, Unit und Compose

Diese Regeln sagen, **wie ein Container gebaut und betrieben wird**. Jede Regel ist mit
einer Messung oder einem Vorfall belegt (Belege am Ende). Abgrenzung:
`container-scaffold` = neues Projekt anlegen (nutzt diese Regeln) ·
`architektur-review` = Projekt im Stack einordnen · `backend-architektur` = Code im
Container · `security-konventionen` = Secrets, Exposure, GitHub.

## 0. Zuerst prüfen, dann ändern

```bash
~/.claude/skills/container-architektur/container-check.sh <name>          # ~/containers/<name>
~/.claude/skills/container-architektur/container-check.sh <Containerfile> --context <dir>
~/.claude/skills/container-architektur/container-check.sh --all [--json]  # ganzer Bestand
```

FAIL = nachweislich kaputt (Container startet nicht oder Unit läuft nicht) · WARN = kostet
Cache, Grösse oder Robustheit · INFO = Hinweis. Ein FAIL wird vor jedem Deploy behoben.

## 1. Basis-Image (verbindlich)

- **Debian-slim als Standard** (`python:3.12-slim`, `node:22-*-slim`). Alpine nur, wenn
  kein Entrypoint-Skript `bash` braucht und keine musl-empfindlichen Binaries drin sind.
  Beleg: Alpine-Variante des ili-Terminals startete nicht (`env: can't execute 'bash'`),
  Ersparnis wäre nur ~20 % Image gewesen.
- **Vollqualifiziert und getaggt:** `docker.io/library/python:3.12-slim`. Kurzname und
  `latest` sind Podman-Stolperfallen (Suchregistry, unreproduzierbare Builds).
- **Kein EOL-Release pinnen.** Trivy meldet dann „OS no longer supported" und zeigt
  fälschlich 0 CVEs (Blindfleck, Vorfall `alpine:3.20`).
- Unfixed CVEs in Debian-Basispaketen sind Status quo aller Debian-Images, **kein Grund
  für einen Basis-Wechsel**. Massstab ist `trivy --ignore-unfixed`.

## 2. Layer-Reihenfolge und Build-Cache (verbindlich)

Stabil zuerst, volatil zuletzt — jeder geänderte Layer baut alle folgenden neu:

1. `FROM`, `ARG` für Versionen
2. System-Pakete: `apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends … && rm -rf /var/lib/apt/lists/*` in **einem** RUN
3. Abhängigkeiten: `COPY requirements.txt` → `pip install --no-cache-dir` (bzw. `package*.json` → `npm ci`), **vor** dem App-Code
4. App-Code: `COPY --chmod=755 skript.sh /usr/local/bin/…` (kein separater `RUN chmod`-Layer)
5. Metadaten zuletzt: `LABEL`, `ENV`, `EXPOSE`, `HEALTHCHECK`, `ENTRYPOINT`

- Versionen als `ARG` **direkt vor** dem Layer, den sie betreffen
  (`ARG CLAUDE_CODE_VERSION=latest` → `--build-arg` baut nur diesen Layer neu).
- Multi-Stage nur bei echten Build-Werkzeugen (Compiler, node_modules-Build). Für ein
  Python-slim-Image bringt es nichts. Beim Kopieren aus dem Builder brechen Symlinks
  (`COPY --from` dereferenziert) — Symlinks danach mit `ln -sf` neu setzen.
- Was die Einsparung wirklich bringt: nur Pull-Zeit und Platz. **Laufzeit-RAM hängt am
  Prozess, nicht am Image** (655-MB-Image, 30 MB idle).

## 3. Inhalt des Runtime-Images

- Vor dem Entfernen von „Debug-Tools" die Skripte greppen: `procps`, `less`, `curl`
  wurden aus dem ili-Terminal entfernt, obwohl `pgrep`/`ps` und der HEALTHCHECK sie
  brauchten. Ersparnis 3–10 MB, Schaden: Healthcheck dauerhaft rot.
- Werkzeug des Healthchecks muss im Image sein (`curl` in `python:*-slim` fehlt → Python-Skript nehmen).
- **Kein Claude Code im App-Image.** Entscheid 09.09.2026: zentraler Läufer ist der
  Host-Claude (`delegate`-MCP + Container-Manager `test-deploy`), sonst Versionsdrift
  und ~300 MB Node pro Image.
- `apt-get upgrade -y` im Build ist erwünscht (patcht Basis-CVEs, die ein reines
  `install` nicht anfasst; Alpine: `apk upgrade --no-cache`).

## 4. Healthcheck (verbindlich)

- Immer auf einen **echten API-Pfad** mit Backend-Logik (`/health`, der etwas prüft),
  nie auf die Startseite: ein vorgeschaltetes nginx liefert 200, während das Backend tot
  ist (Vorfall ili-testbox).
- **Podman baut OCI-Format → `HEALTHCHECK` im Containerfile wird ignoriert** (Build-Warnung
  „HEALTHCHECK is not supported for OCI image format"). Darum in der systemd-Unit:
  `--health-cmd "python3 /app/healthcheck.py" --health-interval=30s --health-retries=3
  --health-start-period=10s`. Belegt: rootless unter systemd meldet nach ~16 s `healthy`.
- Das `HEALTHCHECK` im Containerfile trotzdem setzen — es gilt für Docker- und
  Compose-Nutzer (ili-Release). In Compose: `healthcheck:` pro Service.

## 5. Ressourcen-Limits (verbindlich in jeder Unit)

`--memory` **und** `--cpus` in `podman run` (Compose: `mem_limit`, `cpus`). Richtwerte:

| Dienst-Typ | memory | cpus | Beleg |
|---|---|---|---|
| FastAPI-Kleinstdienst (SQLite/DuckDB) | 512m | 1.0 | scaffold-Default, idle < 100 MB |
| Claude-Code-Terminal | 1g | 1.0 | ~100–130 MB je offenem Board, 112 MB → OOM |
| Playwright/Browser, ML | 2g–4g | 2 | Erfahrungswert pulse-begleiter 2g |

Limit so wählen, dass der Normalbetrieb doppelt Platz hat; das Limit schützt den Host vor
Ausreissern, es ist kein Sparziel. OOM-Kills erkennt man an `memory.events: oom_kill`.

## 6. systemd-Unit (rootless Podman)

- **Kein `User=`** — sonst `216/GROUP` (Muster: `container-scaffold`).
- `Type=notify` + `--sdnotify=conmon`, `--replace`, `--cidfile`, `Restart=on-failure`.
- Netz **explizit** (`--network=monitoring`), sonst Fallback auf slirp4netns/pasta und
  Container sehen sich nicht (Vorfall grafana).
- Eigenes Image als `localhost/<name>:latest`; Fremd-Images vollqualifiziert.
- Nach Unit-Edits `systemctl --user daemon-reload`.

## 7. Sicherheit vor Release

`~/.local/bin/trivy image --scanners vuln --ignore-unfixed --severity CRITICAL,HIGH <image>`.
Fixbare CRITICAL/HIGH werden behoben (meist `apt-get upgrade`/`apk upgrade` oder
Basis-Tag-Bump); npm-Bundled-Deps hängen am npm-Release. Im ili-Release-Workflow ist
das Gate bereits verdrahtet (`release.yml`, nach dem Push).

## 8. Betrieb

- **Testversion zuerst:** Container-Manager `test-deploy` (`<name>-test`, Ports +10000,
  Daten read-only), erst nach Prüfung `test-promote`. Nie Prod direkt neu bauen.
- Verschachtelte Container (Sandbox, Testbox) nach Host-Neustart **neu erstellen**, vorher
  `podman system renumber` (siehe `~/containers/ili-testbox/CLAUDE.md`).
- Test-Images und -Container nach Messungen entfernen (`podman rmi`), keine Leichen.

## 9. Bestand optimieren (alte Container)

`container-check.sh --all` liefert den Bericht; Stand 09.09.2026: 86 Units, davon 2 mit
`--memory`, 1 mit `--cpus`, 0 mit `--health-cmd`; 7 von 59 Containerfiles mit
`HEALTHCHECK`. Abarbeitung: FAIL → eigene Karte je Container, WARN-Klassen gebündelt als
Karte für den Automaten, immer über Testversion zuerst. Bericht:
`~/Projekte/docker-container-optimieren/CHECK-REPORT-<datum>.md`.
