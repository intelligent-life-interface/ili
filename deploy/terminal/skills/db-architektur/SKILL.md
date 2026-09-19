---
name: db-architektur
description: Regeln für Datenbanken im Home-Stack — Engine-Wahl (SQLite für Dienst-State, DuckDB für Analysen/Aggregationen, InfluxDB für Zeitreihen, Postgres nur bei echtem Multi-User/Netz-Zugriff), Datei-Ablage (grosse/latenz-unkritische DBs auf /mnt/daten, aktive DBs NICHT dorthin), Migrationen, Backups über den zentralen db-snapshots-Mechanismus (CloudBeaver/Metabase lesen NUR Snapshots, nie Produktiv-DBs), read-only-Mount bei Testversion, InfluxDB-host-Tag-Lektion, Metabase nur SQLite (kein DuckDB-Treiber). Enthält db-inventory.sh (OK/WARN/FAIL wie architektur-review). Nutze bei allem, was eine neue Datenbank, SQLite/DuckDB/InfluxDB/Postgres-Wahl, CloudBeaver/Metabase-Anbindung, DB-Backup/Snapshot oder Datenplatte /mnt/daten betrifft — BEVOR du eine neue DB anlegst oder eine bestehende umziehst.
---

# db-architektur — Regeln für Datenbanken im Home-Stack

Diese Regeln sagen, **welche Engine wofür**, **wo eine DB-Datei liegt** und **wie sie
gesichert/eingebunden wird**. Jede Regel ist mit einem Vorfall oder einer Messung belegt
(Belege am Ende). Abgrenzung: `backend-architektur` regelt den Code, der auf eine DB
zugreift (Schichten, Retry) — nicht die Wahl/Ablage der DB selbst; `container-architektur`
regelt den Container drumherum.

## 0. Zuerst prüfen, dann anlegen

```bash
~/.claude/skills/db-architektur/db-inventory.sh <projektname|pfad>
~/.claude/skills/db-architektur/db-inventory.sh --all [--json]
```

FAIL = Datei nachweislich kaputt (0-Byte-DB) · WARN = kein/veraltetes Backup, Engine nicht
bestimmbar · INFO = Hinweis (WAL-Nebendateien, Grösse, Mount-Modus nicht ermittelbar).

## 1. Engine-Wahl (verbindlich)

| Zweck | Engine | Begründung |
|---|---|---|
| Zustand eines einzelnen Diensts (State, Konfiguration, App-Daten) | **SQLite** | Kein eigener Server-Prozess, dateibasiert, WAL-fähig, von CloudBeaver/Metabase direkt lesbar |
| Analysen/Aggregationen, grössere Auswertungen, Import-Pipelines | **DuckDB** | Spaltenorientiert, schnelle Aggregation, kein Server — aber: **kein Metabase-Treiber** (siehe §4) |
| Zeitreihen (Sensoren, Zigbee, Modbus, Shelly) | **InfluxDB** | Bucket-Modell, Retention, Flux-Queries, Grafana-natives Ziel |
| Mehrbenutzer-/Netz-Zugriff mit echter Nebenläufigkeit | **Postgres** | Einziger legitimer Grund für einen DB-Server statt Datei — Beispiel: Paperless-Postgres (einzige Live-Verbindung in CloudBeaver neben den Snapshots) |
| Immobilienverwaltung / Multi-User-Web-App | **SQLite reicht meist**, Postgres nur wenn Nebenläufigkeit real ein Problem wird | SQLite-Writer-Lock ist bei wenigen gleichzeitigen Usern kein echtes Limit |

**Nie** einen DB-Server (Postgres/MySQL) anlegen, nur weil es "professioneller" wirkt —
jeder Server ist ein eigener Container, ein eigenes Backup-Ziel und eine eigene
Angriffsfläche. Ohne echten Multi-User-/Netz-Bedarf bleibt es bei SQLite/DuckDB.

## 2. Datei-Ablage

- Aktive, latenz-empfindliche DBs (InfluxDB, Paperless-Postgres) bleiben auf der
  **Systemplatte** (`~/containers/<name>/data/`) — **nicht** nach `/mnt/daten` auslagern
  (random I/O, Auslagerung war 07.06.2026 bewusst ausgeschlossen).
- Grosse, latenz-unkritische Datenmengen (Modell-Caches, Alt-Logs) gehören auf
  **`/mnt/daten`** (zweite Platte, `ext4`, `nofail` in `/etc/fstab`) — per **rsync + Symlink
  zurück**, damit Service-Units/Pfade unverändert gültig bleiben (Muster: Ollama-Modelle,
  Whisper-Cache). Vor dem Verschieben: Dienst stoppen, rsync, Grösse/Dateizahl verifizieren,
  Original löschen, Symlink setzen, Dienst starten.
- **Symlink+`nofail`-Risiko:** ist `/mnt/daten` beim Boot nicht gemountet, zeigt der
  Symlink ins Leere — bei Boot-Problemen zuerst hier prüfen.

## 3. Migrationen

- Schema-Änderungen an einer SQLite-Datei, die bereits produktiv läuft: **Tabelle neu
  anlegen statt `ALTER COLUMN`** wenn ein Spaltentyp sich ändert (SQLite kann den
  Spaltentyp nicht per `ALTER` ändern) — siehe Metabase-Datumsspalten-Fix
  (`~/bin/token-report-db.py`, 10.07.2026).
- Ist die Quelle **nicht** selbst kontrolliert (Produktiv-DB eines Drittsystems,
  Append-only-Prinzip): Typ-Interpretation **in der lesenden Anwendung** setzen
  (Metabase: `Admin → Data Model → Feld → Cast to a specific data type`), nicht die
  Quelle anfassen.
- Nach jeder Schema-Änderung, die eine Metabase-DB betrifft: `POST
  /api/database/:id/sync_schema` nicht vergessen.

## 4. Backups / Snapshots (verbindlich)

- **CloudBeaver und Metabase lesen ausschliesslich read-only Snapshots, nie
  Produktiv-DBs.** Mechanik: `db-snapshot.timer` (täglich 03:00) →
  `~/containers/db-snapshots/snapshot.sh` kopiert Live-DBs nach
  `~/containers/db-snapshots/<name>/` (Container-Mount `/mnt/snapshots`).
  - SQLite (auch im WAL-Modus): über die Python-`.backup()`-API (konsistent, kein
    Mitten-in-Transaktion-Risiko), Fallback `cp` bei `SQLITE_BUSY`.
  - DuckDB/andere Formate: normales `cp`.
  - Neue DB anlegen → **Zeile in `snapshot.sh` ergänzen**, sonst taucht sie nie im
    Snapshot-Verzeichnis auf (Vorfall: `crowai-usage/usage.db` war gesnapshottet,
    aber der Kommentar dazu war vorgreifend — Registrierung fehlte trotzdem).
  - `db-inventory.sh` warnt, wenn zu einer gefundenen DB kein Snapshot existiert oder
    dieser älter als 30h ist (Timer läuft täglich, 30h = grosszügige Toleranz).
- **SQLite-Snapshots read-only öffnen mit `?open_mode=1`** (`SQLITE_OPEN_READONLY`) —
  ohne das versucht der Treiber ein Journal im Snapshot-Ordner anzulegen →
  `SQLITE_READONLY_DIRECTORY`. DuckDB: `duckdb.read_only=true`.
- `data-sources.json` (CloudBeaver) gehört dem gemappten Container-User — ändern nur via
  `podman stop` → `podman unshare python3 <script>` → `podman start`, sonst überschreibt
  CloudBeaver die Datei beim nächsten Lauf.
- **Nicht aufnehmbar in CloudBeaver/Metabase:** proprietäre Formate ohne SQL-Zugriff
  (zigbee2mqtt `database.db` = NDJSON, `mosquitto.db` = binär, `filebrowser.db` = BoltDB).

## 5. Metabase: nur SQLite (verbindlich)

- Metabase hat **keinen DuckDB-Treiber** (nur den eingebauten SQLite- und einen
  Postgres-Treiber, self-hosted). DuckDB-Quellen (claudemd-db, apple-health,
  duckdb-ui) liegen zwar im Snapshot-Verzeichnis, sind aber **nicht** als Metabase-DB
  einbindbar ohne Community-Treiber-Installation.
- Vor jeder neuen Anbindung prüfen: SQLite/Postgres → direkt über `POST /api/database`
  registrierbar; DuckDB → bleibt CloudBeaver/eigenes Skript vorbehalten.

## 6. Testversion zuerst → read-only-Mount für Daten

- Beim Container-Manager-`test-deploy` werden Daten-Mounts (`data/db/database(s)/media`
  bzw. `*.db|sqlite|duckdb`-Dateien) **nicht kopiert** — die Testversion mountet sie
  `ro` direkt von Prod (Schreibversuch = „Read-only file system"). Override pro Projekt
  über `.test-deploy.conf` (`DATA_DIRS=`), falls die Heuristik danebenliegt.
- Bei `test-promote` bleiben diese Mounts live (nicht Teil des Snapshots/Übernahme) —
  die Testversion wird zur neuen Prod, die Daten waren die ganze Zeit dieselben.

## 7. InfluxDB-`host`-Tag-Lektion

- Der `host`-Tag in InfluxDB (Buckets `mqtt`/`energie`/`dimplex`) ist die
  **Telegraf-Container-ID** und wechselt bei jedem Container-Recreate — ein Sensor
  zersplittert dadurch über viele „Host-Nummern". **Nicht löschen, nicht Telegraf
  umstellen** (kein `omit_hostname`) — stattdessen in jeder Flux-Query direkt nach
  `range()` (bzw. vor jedem `join`) `|> drop(columns: ["host"])` einfügen. `drop` ist
  fehlertolerant (No-op bei Measurements ohne `host`).

## Werkzeuge (nicht neu bauen)

| Zweck | Werkzeug |
|---|---|
| Tägliches Backup/Snapshot | `~/containers/db-snapshots/snapshot.sh` + `db-snapshot.timer` |
| DBs read-only durchsuchen/joinen | CloudBeaver (Port 8978) |
| Dashboards über SQLite/Postgres-Snapshots | Metabase (Port 3003) |
| Diesen Skill prüfen | `db-inventory.sh` (hier im Skill) |
