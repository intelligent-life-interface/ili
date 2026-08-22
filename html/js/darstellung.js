// darstellung.js — Panel "⚙️ Darstellung": Akzentfarbe + Schriftgrösse.
// Self-contained wie theme.js/nav.js; eingebunden via nav.js (dynamisch) bzw.
// direkt auf Nav-losen Seiten. Theme-Umschaltung selbst bleibt in theme.js —
// dieses Panel bietet sie nur zusätzlich als 3 direkte Knöpfe an.
//
// Akzentfarbe: wird als INLINE-Style auf <html> gesetzt, weil fast jede Seite
// ihr eigenes ":root { --accent:#4a9eff }" mitbringt — Inline schlägt jede
// Stylesheet-Regel. index.css/project.css hatten die Blautöne hartcodiert und
// nutzen jetzt var(--accent…, <Originalfarbe>): ohne gewählte Farbe bleibt
// darum alles exakt wie vorher. Aus der Basisfarbe werden --accent-soft (hell)
// und --accent-deep (dunkel) berechnet — die Faktoren reproduzieren die
// Original-Palette (#4a90d9 → #90cdf4 / #2b4c7e).
//
// Schriftgrösse: html-font-size als calc(Basis * --ds-fs); fast alles im
// Dashboard rechnet in rem und zieht damit mit. Bei 100% wird das Attribut
// ENTFERNT, damit die Original-Regeln (z.B. der 18px-Tablet-Boost in m.css)
// unangetastet greifen.
(function () {
    'use strict';
    const K_ACCENT = 'ds_accent';
    const K_FS = 'ds_fontscale';
    const K_WVIS = 'ds_wvis_';                 // Prefix für Widget-Sichtbarkeit
    const K_COLS = 'ds_cols';
    const API_PATH = '/api/user-settings';
    let _syncTimer = null;
    const DEFAULT_ACCENT = '#4a90d9';          // Originalfarbe von index/project.css
    const SCALES = [90, 100, 110, 125];
    const GRID_SEL = '.projects-grid';         // Projekt-Grid der Index-Seite
    // "auto" = Originalverhalten: repeat(auto-fill, minmax(--card-min-width,1fr)),
    // d.h. der Zoom-Regler bestimmt die Breite und damit die Spaltenzahl.
    const COLS = [['auto', 'Auto'], ['1', '1'], ['2', '2'], ['3', '3']];

    // Widgets nur auf der Index-Seite — ID + Label + CSS-Selektor.
    // Kein Eintrag für den Isehauer-Drawer (#ise-w): js/isehauer-widget.js ist
    // zwar noch vorhanden, aber in keiner Seite mehr eingebunden — ein Schalter
    // dafür würde ins Leere greifen. Bei Reaktivierung hier wieder aufnehmen.
    const WIDGETS = [
        { id: 'zoom',        label: '🔍 Zoom',           selector: '.zoom-controls' },
        { id: 'eisenhower',  label: '🎯 Priorisieren',   selector: '#eisenhower-toggle' },
        { id: 'ki_prio',     label: '🤖 KI-Prio',        selector: '#ki-prio-btn' },
        { id: 'ki_settings', label: '⚙️ KI-Settings',    selector: '#btn-ai-settings' },
        { id: 'archiv',      label: '🗄 Archiv',          selector: '#archive-toggle' },
        { id: 'arrange',     label: '🔀 Anordnen',        selector: '#arrange-toggle' },
    ];
    const log = (...a) => console.debug('[darstellung]', ...a);

    /* ── API-Sync ───────────────────────────────────────────────────────── */

    // Aktuellen Zustand aus localStorage zusammenbauen (für PUT).
    function _buildPayload() {
        var widgets = {};
        WIDGETS.forEach(function(w) { widgets[w.id] = isWidgetVisible(w.id); });
        return {
            theme:     (document.documentElement.dataset.theme || 'dark'),
            accent:    storedAccent() || null,
            fontscale: storedScale(),
            cols:      storedCols(),
            widgets:   widgets,
            github_auto_report: storedGhAuto(),
        };
    }

    /* ── GitHub-Rückkanal (Opt-in, Server-Flag gespiegelt in localStorage) ── */
    const K_GH = 'ds-gh-auto';
    function storedGhAuto() { try { return localStorage.getItem(K_GH) === '1'; } catch (e) { return false; } }
    function setGhAuto(on) {
        try { localStorage.setItem(K_GH, on ? '1' : '0'); } catch (e) {}
        if (window.__githubReportSetEnabled) window.__githubReportSetEnabled(on);
    }
    const tr = (k, fb) => (window.I18N && window.I18N[k]) || fb;

    // Debounced PUT — nach jeder Einstellungsänderung aufrufen.
    function _scheduleSave() {
        if (_syncTimer) clearTimeout(_syncTimer);
        _syncTimer = setTimeout(function() {
            _syncTimer = null;
            var payload = _buildPayload();
            fetch(API_PATH, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            }).then(function(r) {
                log('API gespeichert, HTTP', r.status);
            }).catch(function(e) {
                log('API-Sync fehlgeschlagen (offline?):', e.message);
            });
        }, 600);
    }

    // API-Wert laden und anwenden (überschreibt localStorage wenn Werte abweichen).
    function _loadFromApi() {
        fetch(API_PATH).then(function(r) {
            if (!r.ok) { log('API-Load HTTP', r.status); return null; }
            return r.json();
        }).then(function(s) {
            if (!s) return;
            log('API-Stand geladen:', s);

            // Theme (theme.js führt die Hoheit)
            if (s.theme && window.dsTheme && document.documentElement.dataset.theme !== s.theme) {
                window.dsTheme.apply(s.theme);
            }

            // Akzentfarbe
            var apiAccent = s.accent || null;
            if (apiAccent !== (storedAccent() || null)) {
                try {
                    if (apiAccent) localStorage.setItem(K_ACCENT, apiAccent);
                    else localStorage.removeItem(K_ACCENT);
                } catch (e) {}
                applyAccent();
            }

            // Schriftgrösse
            if (s.fontscale && s.fontscale !== storedScale()) {
                try { localStorage.setItem(K_FS, String(s.fontscale)); } catch (e) {}
                applyScale();
            }

            // Spalten
            if (s.cols && s.cols !== storedCols()) {
                try {
                    if (s.cols === 'auto') localStorage.removeItem(K_COLS);
                    else localStorage.setItem(K_COLS, s.cols);
                } catch (e) {}
                applyCols();
            }

            // GitHub-Rückkanal Opt-in
            if (typeof s.github_auto_report === 'boolean' && s.github_auto_report !== storedGhAuto()) {
                setGhAuto(s.github_auto_report);
            }

            // Widget-Sichtbarkeit
            if (s.widgets && typeof s.widgets === 'object') {
                WIDGETS.forEach(function(w) {
                    var vis = s.widgets.hasOwnProperty(w.id) ? !!s.widgets[w.id] : true;
                    if (vis !== isWidgetVisible(w.id)) {
                        try { localStorage.setItem(K_WVIS + w.id, vis ? '1' : '0'); } catch (e) {}
                    }
                });
                applyWidgetVisibility();
            }

            refresh();
        }).catch(function(e) {
            log('API-Load fehlgeschlagen (offline?):', e.message);
        });
    }

    const PRESETS = [
        ['#4a90d9', 'Blau (Standard)'],
        ['#3aa99a', 'Türkis'],
        ['#5aa94a', 'Grün'],
        ['#9f7aea', 'Violett'],
        ['#e0913a', 'Orange'],
        ['#d9556b', 'Rot'],
    ];

    /* ── Farb-Helfer ────────────────────────────────────────────────────── */
    const clamp = (n) => Math.max(0, Math.min(255, Math.round(n)));

    function parseHex(h) {
        if (!/^#[0-9a-f]{6}$/i.test(h || '')) return null;
        return [1, 3, 5].map(i => parseInt(h.substr(i, 2), 16));
    }
    const toHex = (rgb) => '#' + rgb.map(c => clamp(c).toString(16).padStart(2, '0')).join('');
    // Richtung Weiss / Richtung Schwarz — Faktoren aus der Original-Palette abgeleitet.
    const lighten = (rgb, f) => rgb.map(c => c + (255 - c) * f);
    const darken = (rgb, f) => rgb.map(c => c * f);
    // Relative Leuchtdichte + Kontrastverhältnis nach WCAG 2.1. Ein simpler
    // Helligkeits-Schwellwert reicht nicht: Grün wirkt "mittelhell", trägt aber
    // so viel Leuchtdichte, dass weisser Text darauf durchfällt (2.9:1).
    const srgb = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
    const relLum = ([r, g, b]) => 0.2126 * srgb(r) + 0.7152 * srgb(g) + 0.0722 * srgb(b);
    const ratio = (a, b) => (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);

    // Textfarbe für Akzent-Flächen: die mit dem besseren Kontrast gewinnt.
    function bestText(rgb) {
        const L = relLum(rgb);
        return ratio(L, relLum([255, 255, 255])) >= ratio(L, relLum([17, 17, 17]))
            ? '#ffffff' : '#111111';
    }

    /* ── Widget-Sichtbarkeit ────────────────────────────────────────────── */
    function isWidgetVisible(id) {
        try { return localStorage.getItem(K_WVIS + id) !== '0'; }
        catch (e) { return true; }
    }
    function setWidgetVisible(id, visible) {
        try { localStorage.setItem(K_WVIS + id, visible ? '1' : '0'); }
        catch (e) {}
    }

    let _wvisCss = null;
    function applyWidgetVisibility() {
        if (!_wvisCss) {
            _wvisCss = document.createElement('style');
            _wvisCss.id = 'ds-wvis';
            document.head.appendChild(_wvisCss);
        }
        const rules = WIDGETS
            .filter(w => !isWidgetVisible(w.id))
            .map(w => `${w.selector}{display:none!important}`)
            .join('\n');
        _wvisCss.textContent = rules;
        log('Widget-Sichtbarkeit:', rules || '(alle sichtbar)');
    }

    /* ── Zustand lesen ──────────────────────────────────────────────────── */
    function storedAccent() {
        try {
            const c = localStorage.getItem(K_ACCENT);
            return parseHex(c) ? c : null;          // null = Standard, nichts überschreiben
        } catch (e) { return null; }
    }
    function storedScale() {
        try {
            const n = parseInt(localStorage.getItem(K_FS), 10);
            return SCALES.includes(n) ? n : 100;
        } catch (e) { return 100; }
    }
    function storedCols() {
        try {
            const v = localStorage.getItem(K_COLS);
            return COLS.some(([c]) => c === v) ? v : 'auto';
        } catch (e) { return 'auto'; }
    }

    /* ── Anwenden ───────────────────────────────────────────────────────── */
    function applyAccent() {
        const root = document.documentElement;
        const c = storedAccent();
        // Hochkontrast hat einen eigenen, bewusst knalligen Akzent (gelb) —
        // Barrierefreiheit schlägt Wunschfarbe.
        const contrast = root.dataset.theme === 'contrast';
        if (!c || contrast) {
            ['--accent', '--accent-soft', '--accent-deep', '--accent-hover', '--accent-text']
                .forEach(p => root.style.removeProperty(p));
            log('Akzent: Standard', contrast ? '(Hochkontrast aktiv)' : '');
            return;
        }
        const rgb = parseHex(c);
        root.style.setProperty('--accent', c);
        root.style.setProperty('--accent-soft', toHex(lighten(rgb, 0.42)));
        root.style.setProperty('--accent-deep', toHex(darken(rgb, 0.58)));
        root.style.setProperty('--accent-hover', toHex(darken(rgb, 0.80)));
        root.style.setProperty('--accent-text', bestText(rgb));
        log('Akzent angewendet:', c);
    }

    function applyCols() {
        const root = document.documentElement;
        const v = storedCols();
        // "auto" = kein Attribut → Original-Grid + Zoom bleiben unangetastet.
        if (v === 'auto') root.removeAttribute('data-cols');
        else root.setAttribute('data-cols', v);
        log('Spalten:', v);
    }

    function applyScale() {
        const root = document.documentElement;
        const n = storedScale();
        if (n === 100) {
            root.removeAttribute('data-fontscale');
            root.style.removeProperty('--ds-fs');
        } else {
            root.setAttribute('data-fontscale', String(n));
            root.style.setProperty('--ds-fs', String(n / 100));
        }
        log('Schriftgrösse:', n + '%');
    }

    /* ── CSS ────────────────────────────────────────────────────────────── */
    // Basis 16px = Browser-Default. Die Mobil-Seiten (/m/) heben sie ab 600px
    // auf 18px an (m.css) — dort muss die Skalierung auf derselben Basis rechnen,
    // sonst würde der Tablet-Boost beim Skalieren verloren gehen.
    const onMobilePage = location.pathname.startsWith('/m/');
    const CSS = `
    html[data-fontscale] { font-size: calc(16px * var(--ds-fs, 1)); }
    ${onMobilePage ? '@media (min-width:600px){ html[data-fontscale]{ font-size: calc(18px * var(--ds-fs,1)); } }' : ''}

    /* Feste Spaltenzahl (Spezifität 0,2,1 schlägt .projects-grid). Ohne
       data-cols bleibt das Original-Grid (auto-fill + Zoom) unangetastet. */
    html[data-cols="1"] ${GRID_SEL} { grid-template-columns: 1fr; }
    html[data-cols="2"] ${GRID_SEL} { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    html[data-cols="3"] ${GRID_SEL} { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    /* Schmale Screens: index.css erzwingt 1 Spalte — das muss eine feste
       Spaltenwahl schlagen, sonst quetscht man 3 Spalten aufs Handy.
       Gleiche Spezifität, aber später notiert → gewinnt. */
    @media (max-width: 640px) {
      html[data-cols] ${GRID_SEL} { grid-template-columns: 1fr; }
    }

    .ds-set-btn { cursor:pointer; background:none; border:1px solid transparent;
      font-size:1.05rem; line-height:1; }
    .ds-set-float { position:fixed; right:12px; bottom:62px; z-index:9999;
      width:42px; height:42px; border-radius:50%;
      border:1px solid var(--t-line2,#4a5568); background:var(--t-surface,#1a202c); }
    .ds-set-panel { position:fixed; z-index:10000; width:250px; padding:14px;
      border-radius:10px; border:1px solid var(--t-line2,#4a5568);
      background:var(--t-surface,#1a202c); color:var(--t-text,#e2e8f0);
      box-shadow:0 8px 28px rgba(0,0,0,.45); font-size:.82rem;
      font-family:system-ui,sans-serif; }
    .ds-set-panel h4 { margin:0 0 10px; font-size:.82rem; font-weight:600; }
    .ds-set-grp { margin-bottom:14px; }
    .ds-set-grp:last-child { margin-bottom:0; }
    .ds-set-lbl { display:block; margin-bottom:6px; font-size:.72rem;
      color:var(--t-muted,#8892a4); text-transform:uppercase; letter-spacing:.04em; }
    .ds-set-row { display:flex; gap:6px; flex-wrap:wrap; align-items:center; }
    .ds-set-chip { cursor:pointer; padding:4px 9px; border-radius:6px;
      border:1px solid var(--t-line2,#4a5568); background:transparent;
      color:var(--t-text,#e2e8f0); font-size:.75rem; }
    .ds-set-chip.on { border-color:var(--accent,#4a90d9);
      background:var(--accent-deep,#2b4c7e); color:var(--accent-soft,#90cdf4); }
    .ds-set-sw { width:26px; height:26px; border-radius:50%; cursor:pointer;
      border:2px solid transparent; padding:0; }
    .ds-set-sw.on { border-color:var(--t-text,#e2e8f0); }
    .ds-set-pick { width:34px; height:26px; padding:0; cursor:pointer;
      border:1px solid var(--t-line2,#4a5568); border-radius:5px; background:none; }
    .ds-set-note { margin-top:8px; font-size:.68rem; color:var(--t-muted,#8892a4);
      line-height:1.35; }
    .ds-set-reset { margin-top:10px; width:100%; cursor:pointer; padding:5px;
      border-radius:6px; border:1px solid var(--t-line2,#4a5568);
      background:transparent; color:var(--t-muted,#8892a4); font-size:.72rem; }
    .ds-set-reset:hover { color:var(--t-text,#e2e8f0); }
    .ds-set-wrow { display:flex; align-items:center; gap:7px; margin-bottom:5px;
      cursor:pointer; font-size:.75rem; color:var(--t-text,#e2e8f0); }
    .ds-set-wrow input[type=checkbox] { accent-color:var(--accent,#4a90d9);
      width:14px; height:14px; cursor:pointer; flex-shrink:0; }
    `;

    /* ── Panel ──────────────────────────────────────────────────────────── */
    let panel = null;

    function wireGithub(p) {
        const $ = id => p.querySelector('#' + id);
        $('ds-gh-lbl').textContent = tr('gh.section', 'GitHub-Rückkanal');
        $('ds-gh-login').textContent = tr('gh.login', 'Mit GitHub anmelden');
        $('ds-gh-logout').textContent = tr('gh.logout', 'Abmelden');
        $('ds-gh-auto-lbl').textContent = tr('gh.auto', 'Fehler automatisch anonymisiert melden');
        $('ds-gh-auto-note').textContent = tr('gh.auto.note', '');
        $('ds-gh-preview').textContent = tr('gh.preview', 'Vorschau');
        $('ds-gh-reports').textContent = tr('gh.reports', 'Letzte Meldungen');
        const cb = $('ds-gh-auto');
        cb.checked = storedGhAuto();
        let pollTimer = null;

        function refreshStatus() {
            fetch('/api/github/auth/status').then(r => r.json()).then(st => {
                log('github status', st);
                const on = !!st.logged_in;
                $('ds-gh-status').textContent = !st.client_id_set ? tr('gh.status.noclient', 'Nicht konfiguriert')
                    : on ? tr('gh.status.on', 'Angemeldet als') + ' ' + (st.login || '?') : tr('gh.status.off', 'Nicht angemeldet');
                $('ds-gh-login').style.display = on ? 'none' : '';
                $('ds-gh-login').disabled = !st.client_id_set;
                $('ds-gh-logout').style.display = on ? '' : 'none';
                cb.disabled = !on;                      // Häkchen nur mit Login — sonst verspricht es Unmögliches
                if (!on && cb.checked) { cb.checked = false; setGhAuto(false); _scheduleSave(); }
            }).catch(e => { $('ds-gh-status').textContent = 'API: ' + e.message; });
        }

        $('ds-gh-login').onclick = function() {
            $('ds-gh-login').disabled = true;
            fetch('/api/github/auth/start', { method: 'POST' }).then(r => r.json()).then(d => {
                if (!d.device_code) throw new Error(d.error || d.detail || 'start failed');
                const box = $('ds-gh-code');
                box.style.display = '';
                box.innerHTML = tr('gh.code.hint', 'Code eingeben:') + ' <a href="' + escAttr(d.verification_uri) + '" target="_blank" rel="noopener"><b style="font-size:15px;letter-spacing:2px">' + escAttr(d.user_code) + '</b></a><br>' + tr('gh.code.waiting', 'Warte …');
                log('device flow: code ' + d.user_code + ', poll every ' + d.interval + 's');
                let interval = (d.interval || 5) * 1000;
                const tick = () => {
                    fetch('/api/github/auth/poll', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ device_code: d.device_code }) })
                        .then(r => r.json()).then(s => {
                            log('poll →', s.status);
                            if (s.status === 'ok') { box.style.display = 'none'; refreshStatus(); return; }
                            if (s.status === 'slow_down') interval += 5000;
                            if (s.status === 'expired') { box.textContent = tr('gh.code.expired', 'Abgelaufen'); $('ds-gh-login').disabled = false; return; }
                            if (s.status === 'denied') { box.textContent = tr('gh.code.denied', 'Abgelehnt'); $('ds-gh-login').disabled = false; return; }
                            if (s.status === 'error') { box.textContent = 'Fehler: ' + (s.error || '?'); $('ds-gh-login').disabled = false; return; }
                            pollTimer = setTimeout(tick, interval);
                        }).catch(e => { box.textContent = 'Fehler: ' + e.message; $('ds-gh-login').disabled = false; });
                };
                pollTimer = setTimeout(tick, interval);
            }).catch(e => { $('ds-gh-status').textContent = 'Login: ' + e.message; $('ds-gh-login').disabled = false; });
        };
        $('ds-gh-logout').onclick = function() {
            if (pollTimer) clearTimeout(pollTimer);
            fetch('/api/github/auth', { method: 'DELETE' }).then(refreshStatus);
        };
        cb.onchange = function() { setGhAuto(cb.checked); _scheduleSave(); log('github_auto_report →', cb.checked); };
        $('ds-gh-preview').onclick = function() {
            const out = $('ds-gh-out');
            fetch('/api/github/report/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ kind: 'frontend', text: 'TypeError: example at ' + location.href, component: location.pathname }) })
                .then(r => r.json()).then(pv => { out.style.display = ''; out.textContent = pv.title + '\n\n' + pv.body; });
        };
        $('ds-gh-reports').onclick = function() {
            const out = $('ds-gh-out');
            fetch('/api/github/reports').then(r => r.json()).then(d => {
                out.style.display = '';
                out.textContent = (d.reports && d.reports.length) ? d.reports.map(r =>
                    new Date(r.ts * 1000).toLocaleString() + ' · ' + r.kind + ' · ' + r.status + (r.issue ? ' · #' + r.issue : '') + '\n  ' + r.title).join('\n')
                    : tr('gh.reports.none', 'Noch nichts gesendet.');
            });
        };
        refreshStatus();
    }
    function escAttr(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;'); }

    function buildPanel() {
        const p = document.createElement('div');
        p.className = 'ds-set-panel';
        p.innerHTML = `
      <h4>⚙️ Darstellung</h4>
      <div class="ds-set-grp">
        <span class="ds-set-lbl">Theme</span>
        <div class="ds-set-row" id="ds-set-themes"></div>
      </div>
      <div class="ds-set-grp">
        <span class="ds-set-lbl">Akzentfarbe</span>
        <div class="ds-set-row" id="ds-set-colors"></div>
        <div class="ds-set-note" id="ds-set-cnote"></div>
      </div>
      <div class="ds-set-grp">
        <span class="ds-set-lbl">Schriftgrösse</span>
        <div class="ds-set-row" id="ds-set-scales"></div>
      </div>
      <div class="ds-set-grp" id="ds-set-layout-grp" style="display:none">
        <span class="ds-set-lbl">Spalten</span>
        <div class="ds-set-row" id="ds-set-cols"></div>
        <div class="ds-set-note" id="ds-set-lnote"></div>
      </div>
      <div class="ds-set-grp" id="ds-gh-grp" style="border-top:1px solid var(--t-line2,#4a5568);padding-top:10px">
        <span class="ds-set-lbl" id="ds-gh-lbl">GitHub-Rückkanal</span>
        <div class="ds-set-note" id="ds-gh-status"></div>
        <div class="ds-set-row" style="gap:5px;margin-top:4px">
          <button class="ds-set-chip" id="ds-gh-login"></button>
          <button class="ds-set-chip" id="ds-gh-logout" style="display:none"></button>
        </div>
        <div class="ds-set-note" id="ds-gh-code" style="display:none"></div>
        <label class="ds-set-wrow" style="margin-top:6px"><input type="checkbox" id="ds-gh-auto"><span id="ds-gh-auto-lbl"></span></label>
        <div class="ds-set-note" id="ds-gh-auto-note"></div>
        <div class="ds-set-row" style="gap:5px;margin-top:4px">
          <button class="ds-set-chip" id="ds-gh-preview"></button>
          <button class="ds-set-chip" id="ds-gh-reports"></button>
        </div>
        <pre id="ds-gh-out" style="display:none;white-space:pre-wrap;font-size:11px;max-height:160px;overflow:auto;margin-top:4px"></pre>
      </div>
      <button class="ds-set-reset" id="ds-set-reset">↺ Auf Standard zurücksetzen</button>
      <div class="ds-set-grp" style="margin-top:10px;border-top:1px solid var(--t-line2,#4a5568);padding-top:10px">
        <span class="ds-set-lbl">Design-Konfiguration</span>
        <div class="ds-set-row" style="gap:5px">
          <button class="ds-set-chip" id="ds-export-btn" title="Einstellungen als JSON-Datei herunterladen">⬇ Export</button>
          <label class="ds-set-chip" id="ds-import-lbl" title="JSON-Datei importieren" style="cursor:pointer">
            ⬆ Import<input type="file" id="ds-import-file" accept=".json,application/json" style="display:none">
          </label>
        </div>
        <div class="ds-set-note" id="ds-import-status"></div>
      </div>`;
        document.body.appendChild(p);

        // Spalten-Wahl nur zeigen, wo es ein Projekt-Grid gibt (Index-Seite).
        if (document.querySelector(GRID_SEL)) {
            p.querySelector('#ds-set-layout-grp').style.display = '';
            const lRow = p.querySelector('#ds-set-cols');
            COLS.forEach(([v, label]) => {
                const b = document.createElement('button');
                b.className = 'ds-set-chip';
                b.dataset.cols = v;
                b.textContent = label;
                b.onclick = () => setCols(v);
                lRow.appendChild(b);
            });
        }

        // Theme-Knöpfe (delegieren an theme.js)
        const themes = [['dark', '🌙 Dunkel'], ['light', '☀️ Hell'], ['contrast', '◐ Kontrast']];
        const tRow = p.querySelector('#ds-set-themes');
        themes.forEach(([id, label]) => {
            const b = document.createElement('button');
            b.className = 'ds-set-chip';
            b.dataset.theme = id;
            b.textContent = label;
            b.onclick = () => {
                if (window.dsTheme) window.dsTheme.apply(id);
                else log('theme.js fehlt — Theme-Knopf wirkungslos');
                refresh();
                _scheduleSave();
            };
            tRow.appendChild(b);
        });

        // Farb-Swatches + freier Picker
        const cRow = p.querySelector('#ds-set-colors');
        PRESETS.forEach(([hex, title]) => {
            const b = document.createElement('button');
            b.className = 'ds-set-sw';
            b.dataset.color = hex;
            b.style.background = hex;
            b.title = title;
            b.onclick = () => setAccent(hex);
            cRow.appendChild(b);
        });
        const pick = document.createElement('input');
        pick.type = 'color';
        pick.className = 'ds-set-pick';
        pick.id = 'ds-set-pick';
        pick.title = 'Freie Farbe wählen';
        pick.oninput = () => setAccent(pick.value);
        cRow.appendChild(pick);

        // Schriftgrössen
        const sRow = p.querySelector('#ds-set-scales');
        SCALES.forEach(n => {
            const b = document.createElement('button');
            b.className = 'ds-set-chip';
            b.dataset.scale = String(n);
            b.textContent = n + '%';
            b.onclick = () => setScale(n);
            sRow.appendChild(b);
        });

        // Widgets-Abschnitt nur auf der Index-Seite
        const path = location.pathname;
        const onIndex = path === '/' || path === '/index.html' || path === '';
        if (onIndex) {
            const wGrp = document.createElement('div');
            wGrp.className = 'ds-set-grp';
            wGrp.id = 'ds-set-widgets-grp';
            const lbl = document.createElement('span');
            lbl.className = 'ds-set-lbl';
            lbl.textContent = 'Widgets';
            wGrp.appendChild(lbl);
            WIDGETS.forEach(w => {
                const row = document.createElement('label');
                row.className = 'ds-set-wrow';
                const cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.dataset.widget = w.id;
                cb.checked = isWidgetVisible(w.id);
                cb.onchange = () => {
                    setWidgetVisible(w.id, cb.checked);
                    applyWidgetVisibility();
                    _scheduleSave();
                };
                row.appendChild(cb);
                const span = document.createElement('span');
                span.textContent = w.label;
                row.appendChild(span);
                wGrp.appendChild(row);
            });
            const resetBtn = p.querySelector('#ds-set-reset');
            p.insertBefore(wGrp, resetBtn);
        }

        wireGithub(p);

        p.querySelector('#ds-set-reset').onclick = resetAll;

        // Export: GET /api/user-settings → JSON-Download
        p.querySelector('#ds-export-btn').onclick = function() {
            fetch(API_PATH).then(function(r) { return r.json(); }).then(function(s) {
                var blob = new Blob([JSON.stringify(s, null, 2)], { type: 'application/json' });
                var a = document.createElement('a');
                a.href = URL.createObjectURL(blob);
                a.download = 'dashboard-design.json';
                a.click();
                URL.revokeObjectURL(a.href);
                log('Export heruntergeladen');
            }).catch(function(e) {
                var note = p.querySelector('#ds-import-status');
                if (note) { note.textContent = 'Export fehlgeschlagen: ' + e.message; note.style.color = '#fc8181'; }
            });
        };

        // Import: JSON-Datei → PUT /api/user-settings → anwenden
        p.querySelector('#ds-import-file').onchange = function(ev) {
            var file = ev.target.files[0];
            if (!file) return;
            var note = p.querySelector('#ds-import-status');
            var reader = new FileReader();
            reader.onload = function(e) {
                var parsed;
                try { parsed = JSON.parse(e.target.result); }
                catch (err) {
                    if (note) { note.textContent = 'Ungültige JSON-Datei.'; note.style.color = '#fc8181'; }
                    return;
                }
                fetch(API_PATH, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(parsed),
                }).then(function(r) {
                    if (!r.ok) throw new Error('HTTP ' + r.status);
                    return r.json();
                }).then(function(resp) {
                    if (note) { note.textContent = 'Einstellungen importiert ✓'; note.style.color = '#48bb78'; }
                    // Anwenden: wie _loadFromApi
                    _loadFromApi();
                    log('Import angewendet');
                    setTimeout(function() { if (note) note.textContent = ''; }, 3000);
                }).catch(function(err) {
                    if (note) { note.textContent = 'Import fehlgeschlagen: ' + err.message; note.style.color = '#fc8181'; }
                    log('Import-Fehler:', err.message);
                });
            };
            reader.readAsText(file);
            ev.target.value = '';   // erneutes Laden derselben Datei ermöglichen
        };

        p.onclick = (e) => e.stopPropagation();     // Klick im Panel schliesst nicht
        return p;
    }

    function setAccent(hex) {
        try {
            // "Blau" ist die Originalfarbe der Seiten → als Werkszustand behandeln
            // (Override löschen). Sonst bekäme dieselbe Farbe eine abgeleitete
            // Textfarbe und sähe minim anders aus als der Auslieferungszustand.
            if (hex.toLowerCase() === DEFAULT_ACCENT) localStorage.removeItem(K_ACCENT);
            else localStorage.setItem(K_ACCENT, hex);
        } catch (e) { /* Safari private */ }
        applyAccent();
        refresh();
        _scheduleSave();
    }
    function setScale(n) {
        try { localStorage.setItem(K_FS, String(n)); } catch (e) { }
        applyScale();
        refresh();
        _scheduleSave();
    }
    function setCols(v) {
        try {
            if (v === 'auto') localStorage.removeItem(K_COLS);
            else localStorage.setItem(K_COLS, v);
        } catch (e) { }
        applyCols();
        refresh();
        _scheduleSave();
    }
    function resetAll() {
        try {
            localStorage.removeItem(K_ACCENT);
            localStorage.removeItem(K_FS);
            localStorage.removeItem(K_COLS);
            WIDGETS.forEach(w => localStorage.removeItem(K_WVIS + w.id));
        } catch (e) { }
        applyAccent(); applyScale(); applyCols(); applyWidgetVisibility(); refresh();
        _scheduleSave();
        log('auf Standard zurückgesetzt');
    }

    // Panel-Zustand an die gespeicherten Werte angleichen.
    function refresh() {
        if (!panel) return;
        const theme = document.documentElement.dataset.theme || 'dark';
        const acc = storedAccent();
        const scale = storedScale();
        panel.querySelectorAll('[data-theme]').forEach(b =>
            b.classList.toggle('on', b.dataset.theme === theme));
        panel.querySelectorAll('[data-color]').forEach(b =>
            b.classList.toggle('on', b.dataset.color === (acc || DEFAULT_ACCENT)));
        panel.querySelectorAll('[data-scale]').forEach(b =>
            b.classList.toggle('on', b.dataset.scale === String(scale)));
        const pick = panel.querySelector('#ds-set-pick');
        if (pick) pick.value = acc || DEFAULT_ACCENT;
        panel.querySelector('#ds-set-cnote').textContent = theme === 'contrast'
            ? 'Im Hochkontrast-Modus bleibt der Akzent bewusst gelb.'
            : '';
        // Widget-Checkboxen synchronisieren
        panel.querySelectorAll('[data-widget]').forEach(cb => {
            cb.checked = isWidgetVisible(cb.dataset.widget);
        });
        // Spalten-Wahl (nur vorhanden, wo es ein Projekt-Grid gibt)
        const cols = storedCols();
        panel.querySelectorAll('[data-cols]').forEach(b =>
            b.classList.toggle('on', b.dataset.cols === cols));
        const lnote = panel.querySelector('#ds-set-lnote');
        if (lnote) lnote.textContent = cols === 'auto'
            ? 'Auto: der Zoom bestimmt die Kartenbreite.'
            : 'Feste Spalten — der Zoom wirkt hier nicht. Am Handy immer 1 Spalte.';
    }

    function positionPanel(btn) {
        const r = btn.getBoundingClientRect();
        panel.style.right = Math.max(8, window.innerWidth - r.right) + 'px';
        // Knopf in der unteren Bildschirmhälfte (floating) → Panel nach oben aufklappen.
        if (r.top > window.innerHeight / 2) {
            panel.style.bottom = (window.innerHeight - r.top + 8) + 'px';
            panel.style.top = 'auto';
        } else {
            panel.style.top = (r.bottom + 8) + 'px';
            panel.style.bottom = 'auto';
        }
    }

    function toggle(btn) {
        if (!panel) panel = buildPanel();
        const open = panel.style.display === 'block';
        panel.style.display = open ? 'none' : 'block';
        if (!open) { positionPanel(btn); refresh(); }
        log(open ? 'Panel zu' : 'Panel offen');
    }

    /* ── Knopf montieren ────────────────────────────────────────────────── */
    function makeBtn(cls) {
        const b = document.createElement('button');
        // Eindeutige ID pro Bedienelement (Hausregel 07.08.2026) — genau dieser Knopf
        // war nur als /html/body/nav/button[2] benennbar.
        b.id = 'nav-btn-darstellung';
        b.className = 'ds-set-btn ' + (cls || '');
        b.textContent = '⚙️';
        const D = window.I18N || {};
        b.title = D['nav.darstellung.title'] || 'Darstellung: Theme, Akzentfarbe, Schriftgrösse, Widgets';
        b.setAttribute('aria-label', D['nav.darstellung.aria'] || 'Darstellung einstellen');
        b.onclick = (e) => { e.stopPropagation(); toggle(b); };
        return b;
    }

    function mountButton() {
        if (document.querySelector('.ds-set-btn')) return;
        const nav = document.querySelector('.ds-nav');            // Desktop-Nav (nav.js)
        const mob = document.querySelector('.topbar-actions');    // Mobile /m/
        if (nav) nav.appendChild(makeBtn('icon-btn'));
        else if (mob) mob.insertBefore(makeBtn('icon-btn'), mob.firstChild);
        else document.body.appendChild(makeBtn('ds-set-float'));
        log('Knopf montiert:', nav ? 'nav' : mob ? 'mobile-topbar' : 'floating');
    }

    // Styles + Zustand sofort (verhindert Farb-/Grössen-/Widget-Blitz), Knopf nach DOM/Nav.
    const st = document.createElement('style');
    st.textContent = CSS;
    document.head.appendChild(st);
    applyAccent();
    applyScale();
    applyCols();
    applyWidgetVisibility();

    // theme.js meldet Wechsel → Akzent neu bewerten + Einstellungen persistieren.
    document.addEventListener('ds-theme', () => { applyAccent(); refresh(); _scheduleSave(); });

    // API-Stand nach DOM-Load laden (überschreibt localStorage wenn abweichend).
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() { setTimeout(_loadFromApi, 300); });
    } else {
        setTimeout(_loadFromApi, 300);
    }

    document.addEventListener('click', () => { if (panel) panel.style.display = 'none'; });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && panel) panel.style.display = 'none';
    });

    function init() {
        let tries = 0;
        (function waitNav() {
            if (document.querySelector('.ds-nav') || tries++ > 10) mountButton();
            else setTimeout(waitNav, 100);
        })();
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();

    window.dsDarstellung = { setAccent, setScale, setCols, reset: resetAll, open: toggle };
})();
