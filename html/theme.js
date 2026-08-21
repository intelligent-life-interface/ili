// theme.js — zentraler Theme-Umschalter für ALLE Dashboard-Seiten.
// Eingebunden via nav.js (dynamisch) bzw. direkt (<script src="/theme.js" defer>)
// auf Seiten ohne Nav (foto, projekt, bots, swipe, /m/).
//
// Drei Zustände, zyklisch per Knopf: Dunkel → Hell → Hochkontrast → Dunkel.
// - Dunkel   = Default (alle Farben haben var(--t-*, <dunkel>)-Fallbacks).
// - Hell     = html[data-theme="light"]    definiert die helle --t-*-Palette.
// - Kontrast = html[data-theme="contrast"] definiert eine Schwarz/Weiss-Palette
//              mit maximalem Kontrast (Barrierefreiheit).
// Jede Palette setzt zusätzlich die Legacy-Variablennamen der Einzelseiten
// (--bg/--surface/… und die /m/-Namen), damit ALLE Seiten mitziehen.
// Wahl wird in localStorage "ds_theme" gespeichert (gilt pro Browser überall).
(function () {
    'use strict';
    const KEY = 'ds_theme';
    const THEMES = ['dark', 'light', 'contrast'];      // Zyklus-Reihenfolge
    const NAME = { dark: 'Dunkel', light: 'Hell', contrast: 'Hochkontrast' };
    const NEXT = { dark: 'Hell', light: 'Hochkontrast', contrast: 'Dunkel' };
    const ICON = { dark: '🌙', light: '☀️', contrast: '◐' };
    const METACOLOR = { dark: null /* = Original */, light: '#eef1f6', contrast: '#000000' };
    const log = (...a) => console.debug('[theme]', ...a);

    const THEME_CSS = `
    html[data-theme="light"] {
      color-scheme: light;
      /* zentrale Theme-Palette (Fallback-Gegenstücke zu den Dunkel-Hexwerten) */
      --t-bg:#eef1f6; --t-surface:#ffffff; --t-surface2:#e7ebf2; --t-raised:#dfe5ee;
      --t-line2:#b9c3d2; --t-text:#1c2431; --t-text2:#39445a; --t-muted:#5b6577;
      /* Legacy-Variablennamen der Einzelseiten (bugs, ai-settings, quick, …) */
      --bg:#eef1f6; --surface:#ffffff; --surface2:#e7ebf2; --border:#d5dce6;
      --text:#1c2431; --muted:#5b6577; --code-bg:#e7ebf2;
      /* Mobile /m/ (m.css) */
      --bg2:#ffffff; --bg3:#e7ebf2; --line:#d5dce6; --txt:#1c2431; --muted2:#7a8598;
    }
    html[data-theme="light"] body { background:#eef1f6; color:#1c2431; }
    /* hardcodierte rgba-Dunkelflächen (m.css topbar/tabbar/overlay, index.css) */
    html[data-theme="light"] .topbar { background:rgba(238,241,246,.96) !important; }
    html[data-theme="light"] .tabbar { background:rgba(238,241,246,.97) !important; }
    html[data-theme="light"] #overlay { background:rgba(238,241,246,.85) !important; }
    html[data-theme="light"] .card-actions { background:rgba(223,229,238,.9) !important; }
    /* Foto-Cover auf Projekt-Kacheln (index.html-Inline-Style): dunkles Overlay
       macht Bilder im Tagmodus fast schwarz — hier auf helle Fläche umgeschaltet. */
    html[data-theme="light"] .project-card.has-photo::before { background:rgba(238,241,246,.85) !important; }
    /* Kachel-Badges (Backlog/In Arbeit/Erledigt, index.css): die Pastelltöne sind für
       dunklen Hintergrund gedacht und auf hellem/foto-hinterlegtem Grund kaum lesbar
       (~1.5:1 Kontrast) — hier auf dunklere, kontraststarke Varianten (>4.5:1) umgeschaltet. */
    html[data-theme="light"] .card-badges { color:var(--t-muted, #5b6577) !important; }
    html[data-theme="light"] .badge-backlog { color:#2c5282 !important; }
    html[data-theme="light"] .badge-in_progress { color:#b45309 !important; }
    html[data-theme="light"] .badge-done,
    html[data-theme="light"] .card-activity { color:#276749 !important; }
    /* Nav-Leiste (nav.js) */
    html[data-theme="light"] .ds-nav { background:#ffffff !important; border-bottom-color:#d5dce6 !important; }
    html[data-theme="light"] .ds-nav a { color:#39445a !important; }

    /* ── Hochkontrast: reines Schwarz/Weiss, kräftige weisse Ränder, gelber Akzent ── */
    html[data-theme="contrast"] {
      color-scheme: dark;
      --t-bg:#000000; --t-surface:#000000; --t-surface2:#0a0a0a; --t-raised:#161616;
      --t-line2:#ffffff; --t-text:#ffffff; --t-text2:#ffffff; --t-muted:#e6e6e6;
      --bg:#000000; --surface:#000000; --surface2:#0a0a0a; --border:#ffffff;
      --text:#ffffff; --muted:#e6e6e6; --code-bg:#0a0a0a;
      --bg2:#000000; --bg3:#0a0a0a; --line:#ffffff; --txt:#ffffff; --muted2:#e6e6e6;
      /* Akzent-Familie komplett überschreiben, sonst blieben die blauen
         var()-Fallbacks von index/project.css als Flächen/Text stehen und
         nur die Ränder würden gelb. darstellung.js lässt eine frei gewählte
         Akzentfarbe hier bewusst aus (Barrierefreiheit schlägt Wunschfarbe). */
      --accent:#ffe000; --accent-soft:#ffe000; --accent-deep:#000000;
      --accent-hover:#fff36b; --accent-text:#000000;
    }
    html[data-theme="contrast"] body { background:#000000; color:#ffffff; }
    html[data-theme="contrast"] .topbar { background:#000000 !important; }
    html[data-theme="contrast"] .tabbar { background:#000000 !important; border-top-color:#ffffff !important; }
    html[data-theme="contrast"] #overlay { background:rgba(0,0,0,.92) !important; }
    html[data-theme="contrast"] .card-actions { background:#000000 !important; }
    html[data-theme="contrast"] .ds-nav { background:#000000 !important; border-bottom-color:#ffffff !important; }
    html[data-theme="contrast"] .ds-nav a { color:#ffffff !important; }
    /* Links im Kontrast-Modus knallig, damit sie sich klar abheben */
    html[data-theme="contrast"] a:not(.ds-nav a):not(.ds-theme-btn) { color:#7cc4ff; }

    .ds-theme-btn { cursor:pointer; background:none; border:1px solid transparent; font-size:1.05rem; }
    .ds-theme-float { position:fixed; right:12px; bottom:12px; z-index:9999;
      width:42px; height:42px; border-radius:50%; border:1px solid var(--t-line2,#4a5568);
      background:var(--t-surface,#1a202c); font-size:1.15rem; }
    `;

    function currentTheme() {
        try {
            const t = localStorage.getItem(KEY);
            return THEMES.includes(t) ? t : 'dark';
        } catch (e) { return 'dark'; }
    }

    function apply(t) {
        if (!THEMES.includes(t)) t = 'dark';
        document.documentElement.dataset.theme = t;
        try { localStorage.setItem(KEY, t); } catch (e) { /* Safari private */ }
        const meta = document.querySelector('meta[name="theme-color"]');
        if (meta) {
            if (!meta.dataset.dark) meta.dataset.dark = meta.content;   // Original einmal merken
            meta.content = METACOLOR[t] || meta.dataset.dark;
        }
        document.querySelectorAll('.ds-theme-btn').forEach(b => {
            b.textContent = ICON[t];
            b.title = `Theme: ${NAME[t]} (klicken → ${NEXT[t]})`;
        });
        // darstellung.js hört mit: der Hochkontrast-Akzent (gelb) schlägt eine
        // frei gewählte Akzentfarbe, das muss bei jedem Wechsel neu greifen.
        document.dispatchEvent(new CustomEvent('ds-theme', { detail: t }));
        log('angewendet:', t);
    }

    function cycle() {
        const idx = THEMES.indexOf(currentTheme());
        apply(THEMES[(idx + 1) % THEMES.length]);
    }

    function makeBtn(cls) {
        const b = document.createElement('button');
        // Eindeutige ID pro Bedienelement (Hausregel 07.08.2026) — dieser Knopf war
        // sonst nur als /html/body/nav/button[1] benennbar.
        b.id = 'nav-btn-theme';
        b.className = 'ds-theme-btn ' + (cls || '');
        b.title = (window.I18N && window.I18N['nav.theme.title']) || 'Hell/Dunkel umschalten';
        b.setAttribute('aria-label', 'Theme umschalten (Dunkel/Hell/Hochkontrast)');
        b.onclick = cycle;
        return b;
    }

    function mountButton() {
        if (document.querySelector('.ds-theme-btn')) { apply(currentTheme()); return; }
        const nav = document.querySelector('.ds-nav');            // Desktop-Nav (nav.js)
        const mob = document.querySelector('.topbar-actions');    // Mobile /m/
        if (nav) nav.appendChild(makeBtn('icon-btn'));
        else if (mob) mob.insertBefore(makeBtn('icon-btn'), mob.firstChild);
        else document.body.appendChild(makeBtn('ds-theme-float'));
        apply(currentTheme());
        log('Knopf montiert:', nav ? 'nav' : mob ? 'mobile-topbar' : 'floating');
    }

    // Styles + Theme sofort (verhindert Theme-Blitz), Knopf nach DOM/Nav.
    const st = document.createElement('style');
    st.textContent = THEME_CSS;
    document.head.appendChild(st);
    document.documentElement.dataset.theme = currentTheme();

    function init() {
        // nav.js injiziert die Leiste ebenfalls erst nach DOMContentLoaded → kurz warten
        let tries = 0;
        (function waitNav() {
            if (document.querySelector('.ds-nav') || tries++ > 10) mountButton();
            else setTimeout(waitNav, 100);
        })();
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();

    // toggle() bleibt als Alias (rückwärtskompatibel), zeigt jetzt auf den 3er-Zyklus.
    window.dsTheme = { cycle, toggle: cycle, apply, current: currentTheme };
})();
