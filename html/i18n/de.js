/* ============================================================================
 * Sprachdatei Deutsch — Tool-Sprache des Dashboards ("ili")
 *
 * Hausregel (Root-CLAUDE.md, 07.08.2026): GUI-Texte kommen aus Sprachdateien,
 * nicht hart aus HTML/JS. Deutsch ist Default; eine weitere Sprache ist nur
 * eine weitere Datei nach demselben Muster (z.B. i18n/en.js).
 *
 * MUSS vor /ui-kit .../v1/i18n.js und vor /nav.js eingebunden werden — defer
 * laeuft in Dokument-Reihenfolge, damit steht das Woerterbuch, wenn die Nav baut.
 * Ein fehlendes Woerterbuch ist kein Fehler: jeder Aufruf hat einen Fallback-Text.
 *
 * Schluessel-Namensraum: <bereich>.<ding> — app / nav / footer / idx / proj.
 * ========================================================================== */
"use strict";

window.I18N = {
    // ── Produktname ─────────────────────────────────────────────────────────
    // 07.08.2026 aus "Dashboard" umbenannt. Technisch heisst alles weiterhin
    // "dashboard" (Ordner, Container, systemd-Units, API-Pfade) — nur die
    // Beschriftung wechselt, plus die zusaetzliche Domain ili.intranet.
    "app.name": "ili",
    "app.brand": "ili",
    "app.brand.full": "intelligent life interface",
    "app.title.index": "ili – Projekte",
    "app.title.project": "📋 Projekt – ili",
    "app.back": "← ili",
    "footer.brand": "Home Server · ili",

    // ── Nav-Leiste ──────────────────────────────────────────────────────────
    "nav.mobil": "Mobil",
    "nav.mobil.title": "Zur mobilen Ansicht wechseln",
    "nav.more": "Mehr",
    "nav.menu": "Menü",
    "nav.more.aria": "Weitere Menuepunkte",
    "nav.aria": "Dashboard Navigation",
    "nav.theme.title": "Hell/Dunkel umschalten",
    "nav.darstellung.title": "Darstellung: Theme, Akzentfarbe, Schriftgrösse, Widgets",
    "nav.darstellung.aria": "Darstellung einstellen",

    "nav.fragen": "Offene Fragen",
    "nav.fragen.title": "Offene Fragen",
    "nav.fragen.count": "{n} offene Frage(n)",
    "nav.projekte": "Projekte",
    "nav.aufgaben": "Meine Aufgaben",
    "nav.recent": "Zuletzt aktiv",
    "nav.created": "Nach Erstelldatum",
    "nav.github": "GitHub-Status",
    "nav.autodev": "Auto-Entwicklung",
    "nav.quick": "Schnellstart",
    "nav.bugs": "Bugs",
    "nav.services": "Services",
    "nav.terminal": "Terminal",
    "nav.webadressen": "Web-Adressen",
    "nav.cost": "Kosten",
    "nav.datenbanken": "Datenbanken",
    "nav.neuesprojekt": "Neues Projekt",
    "nav.kiadvisor": "KI-Advisor",
    "nav.kisettings": "KI-Settings",
    "nav.whitelist": "Whitelist",
    "nav.swipe": "Swipe",
    "nav.flow": "Flow",
    "nav.container": "Container",
    "nav.wiki": "Code-Wiki",
    "nav.ollamaqueue": "Ollama-Queue",

    // ── Projekt-Übersicht (index.html) ──────────────────────────────────────
    // Hier stehen die Emojis MIT im Text, weil sie fester Teil der Beschriftung
    // im HTML sind (data-i18n ersetzt den ganzen textContent).
    "idx.gruppe.kategorie": "📂 Kategorie",
    "idx.gruppe.status": "📊 Status",
    "idx.gruppe.alpha": "🔤 A–Z",
    "idx.gruppe.liste": "📋 Liste",
    "idx.gruppe.liste.title": "Flache Liste, sortiert nach Gruppe und Priorität, mit Auto-Entwicklung-Status",
    "idx.prio": "🎯 Priorisieren",
    "idx.kiprio": "🤖 KI-Prio",
    "idx.archiv": "🗄 Archiv",
    "idx.anordnen": "🔀 Anordnen",
    "idx.kidrawer.zu": "KI-Bereich schliessen",
    "idx.kidrawer.titel": "⚙️ KI-Einstellungen",
    "idx.kidrawer.intro": "Wähle welches KI-Modell für die einzelnen Features verwendet wird. Claude-Modelle kosten API-Tokens, Ollama läuft lokal kostenlos.",
    "idx.kidrawer.cost_warning": "⚠️ Tokenkosten entstehen bei dir: Alle API-Kosten (z.B. für Claude) zahlst du selbst. Es gibt keine automatische Kontrolle — überprüfe regelmässig deine Limits und Rechnungen.",
    "idx.kidrawer.chat.label": "💬 Kanban Chat",
    "idx.kidrawer.chat.desc": "Modell für den Chat auf Projekt-Boards",
    "idx.kidrawer.vision.label": "📸 Foto-Titel",
    "idx.kidrawer.vision.desc": "Erkennt Projekttitel aus Fotos (Vision-fähig)",
    "idx.kidrawer.advisor.label": "🤖 KI-Advisor",
    "idx.kidrawer.advisor.desc": "Einzelmodell-Modus für Board-Analyse",
    "idx.kidrawer.panel.label": "🎭 KI-Advisor Panel",
    "idx.kidrawer.panel.desc": "Mehrere Modelle diskutieren (Ctrl+Klick = Mehrfachauswahl)",
    "idx.kidrawer.modelle": "Verfügbare Modelle",
    "idx.kidrawer.gespeichert": "✓ Gespeichert",
    "idx.kidrawer.fehler": "✗ Fehler",
    "idx.create.btn": "Projekt anlegen",
    "idx.create.laeuft": "Wird angelegt…",
    "idx.create.fehler": "Fehler: {msg}",
    "idx.foto.erstellt": "Projekt erstellt!",
    "idx.foto.fehler": "Foto-Projekt konnte nicht erstellt werden:\n{msg}",
    // Empty-State + KI-Suche (dynamisch in index.js erzeugt)
    "idx.leer": "Kein Projekt gefunden",
    "idx.kisuche.btn": "🤖 KI-Suche in Projekten",
    "idx.kisuche.hint": "Textsuche erfolglos? Lass die KI passende Projekte finden.",
    "idx.kisuche.laeuft": "🤖 KI durchsucht deine Projekte …",
    "idx.kisuche.titel": "🤖 KI-Vorschläge",
    "idx.kisuche.keine": "Auch die KI hat kein passendes Projekt gefunden.",
    "idx.kisuche.fehler": "KI-Suche fehlgeschlagen",

    // ── Bug-Viewer (bugs.html) ──────────────────────────────────────────────
    "bugs.level.all": "Alle",
    "bugs.level.error": "Errors",
    "bugs.level.warning": "Warnings",
    "bugs.source.all": "Alle",
    "bugs.source.kanban": "📋 Kanban",
    "bugs.source.log": "📜 Logs",
    "bugs.source.dblog": "🗄 DB",
    "bugs.age.3": "3 h",
    "bugs.age.24": "heute",
    "bugs.age.168": "7 Tage",
    "bugs.age.720": "30 Tage",
    "bugs.age.all": "alle",

    // ── KI-Nutzung & Kosten (cost.html) ─────────────────────────────────────
    "cost.view.all": "Alle",
    "cost.view.claude": "☁️ Claude",
    "cost.view.ollama": "🤖 Ollama",
    "cost.csv": "⬇ CSV",

    // ── Token-Wächter (token-spikes.html) ───────────────────────────────────
    "nav.tokenguard": "Token-Wächter",
    "tokenguard.title": "📈 Token-Wächter",
    "tokenguard.days": "Zeitraum:",
    "tokenguard.script": "Skript:",
    "tokenguard.allscripts": "Alle Skripte",
    "tokenguard.loading": "⏳ Lade Daten…",
    "tokenguard.empty": "Keine Durchläufe in diesem Zeitraum.",
    "tokenguard.legend.good": "Normal",
    "tokenguard.legend.spike": "Spike (über Schwelle)",
    "tokenguard.legend.threshold": "Schwelle",
    "tokenguard.summary.runs": "Läufe",
    "tokenguard.summary.spikes": "Spikes",
    "tokenguard.summary.max": "Höchster Wert",
    "tokenguard.summary.threshold": "Schwelle",
    "tokenguard.col.ts": "Zeit",
    "tokenguard.col.name": "Skript",
    "tokenguard.col.weighted": "Gewichtete Tokens",
    "tokenguard.col.threshold": "Schwelle",
    "tokenguard.col.status": "Status",

    // ── LAN-Scan (scan.html) ────────────────────────────────────────────────
    "scan.filter.leeren": "✕",
    "scan.speichern": "💾 Speichern",
    "scan.speichernscan": "💾 Speichern & Scan starten",

    // ── Schnellstart (quick.html) ───────────────────────────────────────────
    "quick.abbrechen": "Abbrechen",
    "quick.erstellen": "Erstellen",

    // ── KI-Einstellungen (ai-settings.html) ─────────────────────────────────
    "ai.speichern": "💾 Speichern",
    "ai.zuruecksetzen": "↺ Zurücksetzen",

    // ── Docker / Projekt-Container (ai-settings.html, docker-settings.js) ─────────
    "docker.title": "🐳 Docker / Projekt-Container",
    "docker.subtitle": "So erreicht die KI eine Container-Engine, um Projekt-Container zu bauen und zu starten.",
    "docker.status.loading": "Prüfe Docker-Verbindung…",
    "docker.status.ok": "Erreichbar: {engine} {version} ({os}/{arch}) — geprüft im {source}",
    "docker.status.fail": "Nicht erreichbar: {error}",
    "docker.status.off": "Aus — die KI wird angewiesen, keine Container einzurichten (ein per Overlay gemounteter Socket bleibt technisch erreichbar).",
    "docker.status.none": "Kein Docker konfiguriert — Modus wählen und der Anleitung folgen.",
    "docker.test.prefix": "Test:",
    "docker.source.terminal": "Terminal-Container",
    "docker.source.api": "API-Container (Terminal läuft nicht)",
    "docker.overlay.sandbox": "Sandbox (Docker-in-Docker)",
    "docker.overlay.socket": "Host-Socket",
    "docker.overlay.remote": "Entfernter Host (TCP)",
    "docker.ports": "Projekt-Ports {from}–{to}",
    "docker.mode.label": "Modus",
    "docker.mode.auto": "Wie gestartet (Compose-Overlay: Sandbox oder Host-Socket)",
    "docker.mode.remote": "Entfernter Docker-Host über TCP (ohne Neustart)",
    "docker.mode.off": "Aus — KI soll keine Container einrichten",
    "docker.host.label": "Docker-Host (DOCKER_HOST)",
    "docker.host.hint": "z.B. tcp://host.docker.internal:2375 (Docker Desktop) oder tcp://docker-host:2376 (TLS)",
    "docker.tls.label": "TLS prüfen (DOCKER_TLS_VERIFY=1)",
    "docker.cert.label": "Zertifikat-Ordner (DOCKER_CERT_PATH, im Terminal gemountet)",
    "docker.warn.socket": "⚠️ Host-Socket und ungeschütztes TCP sind faktisch Root auf dem Rechner. Nur auf einem Gerät, das ili gehört — TCP nie ohne TLS ins LAN öffnen. Docker Desktops localhost-TCP ist für jeden Container auf dem Rechner erreichbar, auch für die Projekt-Container der KI, nicht nur für ili.",
    "docker.howto.title": "Anleitung",
    "docker.howto.auto": "Container-Zugriff wird beim Start des Stacks festgelegt (Compose-Overlay). In der .env die COMPOSE_FILE-Zeile ergänzen und den Stack neu starten:\n\nA) Sandbox — Docker-in-Docker, isoliert (empfohlen auf Docker-Hosts):\n   COMPOSE_FILE=docker-compose.yml:docker-compose.terminal.yml:docker-compose.sandbox.yml\n\nB) Host-Socket — Podman-Hosts oder bewusst echte Host-Container (⚠️ = Root):\n   COMPOSE_FILE=docker-compose.yml:docker-compose.terminal.yml:docker-compose.hostdocker.yml\n   DOCKER_SOCKET=/var/run/docker.sock        # Podman rootless: /run/user/<uid>/podman/podman.sock\n   PROJECTS_HOST_DIR=/pfad/zu/ili            # der Ordner, der projects/ enthält\n\nDanach:  docker compose up -d\nFehlen die Overlay-Dateien (Registry-Installation):  docker run --rm -v \"$PWD\":/out ghcr.io/toa1984/ili init\nProjekt-Ports: {ports_from}–{ports_to}",
    "docker.howto.remote": "Der Docker-Host wird zur Laufzeit gesetzt — kein Neustart; gilt für neue Terminal-Sitzungen und Automat-Läufe.\n\nDocker Desktop (Windows/macOS): Settings → General → „Expose daemon on tcp://localhost:2375 without TLS“ aktivieren,\n   dann oben eintragen:  tcp://host.docker.internal:2375\nLinux Docker Engine: /etc/docker/daemon.json → \"hosts\": [\"unix:///var/run/docker.sock\", \"tcp://0.0.0.0:2376\"] NUR mit TLS\n   (docs.docker.com → „Protect the Docker daemon socket“); Zertifikat-Ordner in terminal+automat mounten, oben TLS aktivieren.\nPodman: von hier aus kein TCP-Weg — Host-Socket-Overlay nehmen (Modus „Wie gestartet“, Variante B).\n\nBind-Mounts von Projekt-Containern brauchen HOST-Pfade: PROJECTS_HOST_DIR in der .env setzen.\nProjekt-Ports: {ports_from}–{ports_to}",
    "docker.howto.off": "Nichts zu tun — die KI bekommt keine Docker-Umgebung und keine Container-Anleitung.",
    "docker.btn.test": "🔌 Verbindung testen",
    "docker.btn.save": "💾 Docker-Einstellungen speichern",
    "docker.btn.copy": "📋 Kopieren",
    "docker.saved": "Docker-Einstellungen gespeichert ✓",
    "docker.test.ok": "Verbindung OK ✓",
    "docker.test.fail": "Verbindung fehlgeschlagen",
    "docker.copied": "Anleitung kopiert ✓",
    "docker.copy.fail": "Kopieren fehlgeschlagen",
    "docker.err.mode": "Ungültiger Modus",
    "docker.err.host_required": "Docker-Host fehlt (tcp://host:port)",
    "docker.err.host_format": "Docker-Host muss die Form tcp://host:port haben",
    "docker.err.cert_path": "Zertifikat-Ordner muss ein absoluter Pfad sein",
    "docker.guide.note": "Die KI bekommt die passende Anleitung automatisch (/projects/CLAUDE.md), sobald Docker erreichbar ist.",

    // ── Offene Fragen (fragen.html) ─────────────────────────────────────────
    "fragen.terminal": "Terminal",
    "fragen.terminal.title": "Terminal hier unten ein-/ausklappen",
    "fragen.projekt": "Projekt",
    "fragen.projekt.title": "Projekt-Board in neuem Tab öffnen",

    // ── Leichen (leichen.html) ──────────────────────────────────────────────
    // review: "leichen.default_threshold" (unbenutzt) und "leichen.threshold_desc"
    // (enthielt Platzhalter "N Tage" ohne Interpolationsmechanismus im i18n-Helper,
    // s. leichen.html) entfernt — die Zahl bleibt clientseitig aus
    // INACTIVITY_DEFAULT_DAYS gebaut, nicht übersetzbar.
    "leichen.preset.30": "30 Tage",
    "leichen.preset.60": "60 Tage",
    "leichen.preset.90": "90 Tage",

    // GitHub-Rückkanal (Einstellungen-Panel + Karten-Export) — darstellung.js, project-github-export.js
    "bug.button": "Fehler melden",
    "bug.title": "Einen Fehler melden (öffnet GitHub in einem neuen Tab)",
    "bug.prefillTitle": "Fehler in ili: ",
    "bug.prefillBody": "Was ist passiert?\n\n\nWas hättest du erwartet?\n\n\n---\n",
    "bug.failed": "Der Melde-Link konnte nicht erzeugt werden.",
    "gh.section": "GitHub-Rückkanal",
    "gh.login": "Mit GitHub anmelden",
    "gh.logout": "Abmelden",
    "gh.status.off": "Nicht angemeldet",
    "gh.status.on": "Angemeldet als",
    "gh.status.noclient": "Nicht konfiguriert (ILI_GITHUB_APP_CLIENT_ID fehlt)",
    "gh.code.hint": "Code auf github.com/login/device eingeben:",
    "gh.code.waiting": "Warte auf Bestätigung …",
    "gh.code.expired": "Code abgelaufen — bitte erneut anmelden.",
    "gh.code.denied": "Anmeldung abgelehnt.",
    "gh.auto": "Fehler automatisch anonymisiert melden",
    "gh.auto.note": "Sendet nur technische Daten (Version, Modul, Fehlertyp, bereinigter Fehlertext) an das ili-Projekt auf GitHub. Nie: Karten, Board-Namen, Pfade, IP-Adressen, Namen, E-Mails, Tokens. Jede Meldung wird lokal protokolliert.",
    "gh.preview": "Vorschau: was wird gesendet?",
    "gh.reports": "Letzte Meldungen",
    "gh.reports.none": "Noch nichts gesendet.",
    "gh.export": "Als Issue exportieren",
    "gh.export.title": "Karte als GitHub-Issue exportieren",
    "gh.export.note": "Der Text wurde bereinigt (Pfade, IPs, E-Mails, Tokens entfernt). Prüfe und passe an — erst mit „Senden“ verlässt er diese Instanz.",
    "gh.export.send": "Senden",
    "gh.export.deeplink": "Im Browser auf GitHub öffnen (ohne Anmeldung)",
    "gh.export.done": "Issue erstellt:",
    "gh.export.fail": "Export fehlgeschlagen:",

    // ── Update-Banner (index.html, js/update-banner.js) ─────────────────────
    "update.banner.title": "ili {available} verfügbar",
    "update.banner.installed": "installiert: {version}",
    "update.banner.beta": "🧪 Beta",
    "update.banner.changes": "→ Änderungen",
    "update.banner.howto": "Zum Aktualisieren:",
    "update.banner.close": "Schliessen",
    "update.banner.copy_title": "In Zwischenablage kopieren",
    "update.banner.copy_aria": "Kopieren"
};
