# Dashboard — Projekt-Terminal (ttyd/tmux) \& Kanban-Kontext-Hook (Detail-Modul)

> **Tags:** terminal, projterm, ttyd, tmux, tmux-project.sh, projterm_prepare, resolve, vollbild, breit-toggle, zoom, nginx-same-origin, ttyauth, https-pflicht, kanban_context, hook, KANBAN_BOARD
> Ausgelagert aus `~/containers/dashboard/CLAUDE.md` (1:1, unverändert). Kern-Doku + Trigger-Tabelle: `../CLAUDE.md`.

### Projekt-Terminal statt KI-Chat (`project.html`, 2026-06-15)
Das rechte Chat-Panel („🤖 KI-Assistent", Ollama/Claude-API, nur Karten-CRUD) wurde durch
ein **echtes Terminal mit Claude Code** ersetzt — zum Weiterentwickeln/Beauftragen direkt
im Projekt. Pro Board eine eigene tmux-Session im Code-Ordner.
- **Frontend:** `html/project.html` `.chat-panel` → `<iframe id="proj-terminal"
  class="terminal-frame">`; `html/js/project.js` `initTerminal()`/`reloadTerminal()` setzen
  `src='/projterm/?arg='+BOARD_ID`. `loadModels()`-Init + `chat-input`-Listener entfernt;
  alte Chat-Funktionen (`sendMessage`/`clearChat`/`stopChat`/`loadModels`) sind tot (keine
  Aufrufer mehr, nicht entfernt). CSS `.terminal-frame` in `html/css/project.css`.
  - **⛶ Vollbild-Toggle** (`toggleTerminalFullscreen`): echte Fullscreen-API auf `.chat-panel`
    (`:fullscreen`-CSS), Fallback `.terminal-maximized` (position:fixed); Esc verkleinert. Kein
    iframe-Reload → tmux-Session bleibt. **↻ Neu laden** (`reloadTerminal`) setzt iframe-src neu
    gegen falsch dargestellte Schrift/Geistertext (Session bleibt via reattach). Gleicher Reload-
    Button auch in den ttyd-Wrappern `caddy/html/term.html` + `terminals.html`.
  - **↔ Breit-Toggle** (`toggleTerminalWidth`, 2026-06-17): das Panel ist normal fix **400px**
    (→ ttyd meldet nur ~41 Spalten, TUI abgeschnitten). Der Knopf schaltet die CSS-Klasse
    `.terminal-wide` (55%, min 600px, max 1100px) → viele Spalten, Karten bleiben links sichtbar.
    **Standard = BREIT (2026-06-18):** `applyTerminalWidth()` defaultet auf wide; nur ein explizit
    in `localStorage['term_wide']` gespeicherter Wert (`'0'`/`'1'`) sticht den Default → wer bewusst
    auf Schmal schaltet behält das, frische Browser starten breit.
    Nach dem Resize stösst `_nudgeTerminalResize()` ein `resize`-Event im **same-origin** iframe an,
    damit xterm/fit-addon die Spaltenzahl sofort neu rechnet (sonst erst bei Fenster-Resize / ↻).
    Reines Frontend (nginx-Mount, live) → kein Restart, nur Hardreload (Cache-Bust `?v=20260617-termwide`).
  - **A−/A+ Schrift-Zoom** (`setTerminalZoom`/`applyTerminalZoom`, 2026-06-18): macht die Schrift
    kleiner, damit MEHR Spalten/Zeilen reinpassen — orthogonal zum Breit-Toggle (geht auch im
    schmalen 400px-Panel). Trick **ohne ttyd-Internas**: CSS-Variable `--term-zoom` (auf `.chat-panel`,
    **Default 0.8 = 80%**, `_TERM_ZOOM_DEFAULT`; ebenso ist **Breit der Standard**) bläst das iframe via `.terminal-frame { width/height: calc(100%/var(--term-zoom)); transform: scale(var(--term-zoom)) }`
    auf 100%/zoom auf und skaliert es optisch zurück → ttyds fit-addon misst mehr CSS-Pixel = mehr
    Spalten, Schrift wirkt kleiner. Das iframe sitzt dafür in `.terminal-frame-wrap` (flex:1, position:relative,
    overflow:hidden), iframe selbst `position:absolute`. Stufen **0.6–1.0** in 0.1-Schritten, Wert in
    `localStorage['term_zoom']`, A+ disabled bei 1.0 / A− bei 0.6. Nach jeder Änderung `_nudgeTerminalResize()`.
    **Browser-verifiziert** (Playwright/Chromium): zoom 0.8 → iframe-clientWidth 400→500px (+25% Spalten),
    optische Breite unverändert. Reines Frontend (nginx-Mount, live) → nur Hardreload (Cache-Bust `?v=20260618-termzoom`).
- **Kompakte CLAUDE.md beim Start:** `projterm_prepare.py <slug> <cwd>` rendert einen
  marker-abgegrenzten Block `
` (Projekt-Kurzbeschr.
  aus manifest + offene Karten, erledigte/Meta-Karte `claudemd-description` weggelassen,
  token-sparend) idempotent in `<cwd>/CLAUDE.md`. **Ohne Datum** → ändert sich nur bei
  echten Board-Änderungen (verschmutzt git-getrackte CLAUDE.md nicht täglich). Bestehende
  Doku bleibt erhalten (nur Block ersetzt/angehängt).
- **Arbeitsordner = richtige Projekt-CLAUDE.md (`--resolve`, 2026-06-18):** `tmux-project.sh`
  bestimmte den cwd früher stur als `~/containers/<slug>` → sonst `~/Projekte/<slug>`. Das lud
  in zwei Fällen die FALSCHE CLAUDE.md: (a) Board `bohrprofile-3d` (`code_dir=~/containers/bohr3d`)
  öffnete den 739-B-Stub `~/Projekte/bohrprofile-3d` statt der echten 11-KB-Doku — `code_dir`
  wurde ignoriert; (b) `immobilienverwaltung` nahm `~/containers/` (1,7 KB) statt der reicheren
  `~/Projekte/`-Doku (5,3 KB). **Fix:** `projterm_prepare.py` hat jetzt `resolve_work_dir(slug)`
  + CLI-Modus `--resolve <slug>` (druckt den Ordner nach stdout), der **exakt die Logik der
  KI-Kurzbeschreibung** (`project_describer._source_text`) spiegelt: 1. Manifest-`code_dir`
  (falls dort eine CLAUDE.md liegt) — autoritativ; 2. sonst von `~/containers/<slug>` UND
  `~/Projekte/<slug>` der mit der **inhaltsreichsten (längsten) CLAUDE.md**; 3. sonst der
  existierende Ordner (containers vor Projekte); 4. sonst `$HOME`. `tmux-project.sh` ruft
  `python3 $PREP --resolve "$SLUG"` und nutzt das als cwd (altes Schema nur noch als Fallback).
  Neue Projekte sind nicht betroffen (`_ensure_project_session` legt sie korrekt in
  `~/Projekte/<id>` an). **Gotcha:** Der Wrapper **wiederverwendet** bestehende tmux-Sessions
  und wechselt deren cwd NICHT → für Projekte mit schon laufender, falsch platzierter Session
  greift der Fix erst nach `tmux kill-session -t proj-<slug>` (alte Konversation bleibt via
  `claude --resume` im alten Ordner). Reine Host-Script-Änderung (`~/bin/tmux-project.sh` +
  `projterm_prepare.py`) → kein Service-/Container-Restart nötig.
- **nginx same-origin (`/projterm/`):** ttyd läuft als Host-Service `ttyd-project.service`
  (Port 7690, `-b /projterm`, `-a`, `-c` Basic-Auth). Die Locations stehen in
  **`projterm-locations.conf`** — *gitignored* (enthält `TTYD_AUTH_B64` + `TTYD_WS_SECRET`),
  **separat in den Container gemountet** (`container-dashboard.service` zweiter `-v`),
  `nginx.conf` bindet sie via `include /etc/nginx/projterm-locations.conf;` ein.
  - `/projterm/ws`: Cookie `ttyauth` prüfen → Basic-Auth fest Richtung ttyd injizieren
    (Safari sendet im WS-Handshake keine Basic-Auth). `/projterm/`: Browser-Basic-Auth
    durchreichen, bei 200 `Set-Cookie ttyauth`. Beide `^~` (sonst fängt die `\.js$`-regex-
    location die ttyd-Assets als 404 ab).
  - **Neu generieren** (nach config.env-Rotation):
    `SECRET=$(grep ^TTYD_WS_SECRET= ~/config.env|cut -d= -f2-); B64=$(grep ^TTYD_AUTH_B64=
    ~/config.env|cut -d= -f2-)` in die `proxy_set_header Authorization "Basic $B64"` bzw.
    `ttyauth=$SECRET`-Stellen einsetzen, dann `podman restart dashboard`.
- **Sicherheit:** Dashboard hat keinen Login → wer es im LAN erreicht, bekommt via Terminal
  eine Host-Shell. Bewusst akzeptiert (nur intranet/.133, nie online); Basic-Auth liegt vor
  `/projterm/`. Details/Wrapper-Scripts: `~/Projekte/web-terminal/CLAUDE.md`.
- **HTTPS-Pflicht fürs Terminal (Gotcha 2026-06-17):** Das `ttyauth`-WS-Cookie (in
  `projterm-locations.conf`) ist `Secure` → über **http** (z.B. `http://192.0.2.10` oder
  `http://www.dashboard…`) sendet der Browser es NICHT → `/projterm/ws` gibt `403`, das
  Terminal lädt, nimmt aber **keine Eingabe** an (Browser-Konsole: „WebSocket … bad response
  from the server"). Symptom betrifft ALLE Projekte nach einem Reload, nicht ein einzelnes.
  Fix: `nginx.conf` leitet direkte http-Zugriffe per `301` auf `https://dashboard.intranet.yourdomain.example`
  um — Bedingung `if ($http_x_forwarded_proto != "https")`, sonst Redirect-Loop, weil Caddy
  selbst per http auf `:80` proxyt (Caddy setzt den Header). Immer über die **HTTPS-Domain**
  aufrufen, nie über die nackte IP oder `www.`-Subdomain (Wildcard-Cert deckt nur eine Ebene).

### Live-Kanban-Kontext-Hook (`~/.claude/hooks/kanban_context.py`, 2026-06-21)
Der `projterm_prepare.py`-Block in der CLAUDE.md war nur ein **Snapshot beim Terminal-Start** — terminal1-4 bekamen gar keinen, und während des Arbeitens wurde nie aktualisiert (Karte gezogen → CLAUDE.md blieb alt). Neu injiziert ein **UserPromptSubmit-Hook bei JEDEM Prompt** den frischen Stand (stdout → additionalContext), liest das Board live von der Platte.
- **Board-Quelle (Priorität):** (1) Env `$KANBAN_BOARD` — vom Projekt-Terminal-Wrapper `~/bin/tmux-project.sh` gesetzt (`export KANBAN_BOARD=<slug>` vor `exec claude-loop.sh`), greift erst bei NEU gestarteter Session (laufende behält alte Env → `tmux kill-session -t proj-<slug>`). (2) `cwd == $HOME` → **Grundstruktur-Board** `home-stack` (Env `$KANBAN_HOME_BOARD`), damit auch Arbeit an der Basis-Ebene (Container-Stack/Infra/Root-CLAUDE.md) im Home-Terminal nachgeführt wird. (3) Sonst cwd-Basename == Board-Slug. (4) Sonst nichts.
- **DRY/Token:** importiert `render_kanban_block`/`_manifest_entry` aus `projterm_prepare` (gleiche Caps: 12 Karten/Spalte, 400 Zeichen Next-Desc, erledigte/Meta weg). Marker-Kommentare werden für den Kontext weggelassen. JEDER Fehler → exit 0 ohne Ausgabe (Prompt nie blockieren). Debug: `KANBAN_HOOK_DEBUG=1` → stderr.
- **Registrierung:** `~/.claude/settings.json` → `hooks.UserPromptSubmit`. Der statische KANBAN-Block wurde aus `~/CLAUDE.md` entfernt (Hook ist jetzt die einzige Live-Quelle; `projterm_prepare` schreibt den Snapshot-Block beim Öffnen weiterhin in die Projekt-CLAUDE.md, der Hook überschreibt ihn aber bei jedem Prompt mit dem Live-Stand).
