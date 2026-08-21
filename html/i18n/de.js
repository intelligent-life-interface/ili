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
    "leichen.preset.90": "90 Tage"
};
