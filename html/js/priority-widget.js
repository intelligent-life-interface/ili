// Schwebendes Priority Widget-Widget (Eisenhower-Wochenplaner, eigener Container Port 3005).
// Stil: REITER/DRAWER — ein vertikaler Reiter "🐸 Wochenplaner" am rechten Rand; Klick fährt
// einen Drawer über die volle Höhe ein. position:fixed → läuft beim Scrollen mit. ⛶ vergrössert
// auf die ganze Seite (Esc verkleinert). Offen/Vollbild-Zustand wird in localStorage gemerkt.
//
// Priority Widget wird cross-origin via Caddy-Subdomain im iframe eingebettet (setzt kein
// X-Frame-Options/CSP). Erreichbar nur im Heimnetz via Split-DNS.
//
// Einbinden: <script src="/js/priority-widget-widget.js?v=..." defer></script>
// Muster bewusst wie nav.js: eine self-contained Datei, injiziert eigenes CSS + DOM.
(function () {
    'use strict';

    var ISE_URL = (typeof window.DASHBOARD_CONFIG !== 'undefined' && window.DASHBOARD_CONFIG.priority_widget_url)
        ? window.DASHBOARD_CONFIG.priority_widget_url
        : (window.location.protocol + '//' + window.location.hostname + ':3005/');

    function load(key, def) {
        try { var v = localStorage.getItem(key); return v === null ? def : v; }
        catch (e) { return def; }
    }
    function save(key, val) { try { localStorage.setItem(key, val); } catch (e) {} }

    var state = {
        open: load('ise_open', '0') === '1',   // Drawer ausgefahren?
        full: load('ise_full', '0') === '1'     // Vollbild?
    };
    console.log('[pp-widget] Init-Zustand:', JSON.stringify(state));

    var CSS = `
    #pp-w, #pp-w * { box-sizing: border-box; }
    #pp-w {
        --pp-bg:#0b0d13; --pp-border:#2a2d3e; --pp-fg:#e2e8f0; --pp-accent:#4a9eff;
        position: fixed; z-index: 2600;
        font: 500 .85rem system-ui, -apple-system, sans-serif;
    }
    /* Reiter am rechten Rand */
    .pp-tab {
        position: fixed; right: 0; top: 50%; transform: translateY(-50%);
        z-index: 2600; cursor: pointer;
        writing-mode: vertical-rl; text-orientation: mixed;
        background: var(--pp-accent); color:#fff; border:0;
        padding:.75rem .35rem; border-radius: 10px 0 0 10px; font-weight:700;
        box-shadow: -4px 0 16px rgba(0,0,0,.4); letter-spacing:.03em;
        transition: right .25s ease;
    }
    .pp-tab:hover { filter: brightness(1.08); }

    /* Drawer-Panel */
    .pp-panel {
        position: fixed; top: 0; right: 0; bottom: 0; height: 100vh;
        width: 420px; max-width: 92vw;
        display: flex; flex-direction: column;
        background: var(--pp-bg); border-left: 1px solid var(--pp-border);
        box-shadow: -12px 0 40px rgba(0,0,0,.55);
        transform: translateX(100%); transition: transform .25s ease;
    }
    #pp-w.is-open .pp-panel { transform: translateX(0); }
    #pp-w.is-open .pp-tab   { right: 420px; }
    @media (max-width:480px){ #pp-w.is-open .pp-tab { right: 92vw; } }

    .pp-head {
        display: flex; align-items: center; gap:.4rem;
        padding: .35rem .5rem; background:#11141d;
        border-bottom: 1px solid var(--pp-border); flex: 0 0 auto;
    }
    .pp-title { color: var(--pp-fg); font-weight:700; white-space:nowrap;
                 overflow:hidden; text-overflow:ellipsis; flex:1 1 auto; }
    .pp-btn {
        background:#1a1d27; color:#8892a4; border:1px solid var(--pp-border);
        border-radius:7px; cursor:pointer; padding:.25rem .45rem; font-size:.9rem;
        line-height:1; transition:background .12s,color .12s;
    }
    .pp-btn:hover { color: var(--pp-fg); background:#222634; }
    .pp-body { flex:1 1 auto; min-height:0; position:relative; }
    #pp-frame { position:absolute; inset:0; width:100%; height:100%; border:0; background:#0b0d13; }

    /* Vollbild */
    #pp-w.is-full .pp-panel {
        width:100% !important; max-width:none !important; border-left:0;
        transform:none !important; z-index:3000;
    }
    #pp-w.is-full .pp-tab { display:none; }
    `;

    function el(tag, cls, html) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        if (html != null) e.innerHTML = html;
        return e;
    }

    function build() {
        var style = el('style'); style.textContent = CSS; document.head.appendChild(style);

        var root = el('div'); root.id = 'pp-w';

        var tab = el('button', 'pp-tab', '🐸 Wochenplaner');
        tab.title = 'Wochenplaner öffnen/schliessen';

        var panel = el('div', 'pp-panel');
        var head  = el('div', 'pp-head');
        var title = el('div', 'pp-title', '🐸 Wochenplaner');
        var full  = el('button', 'pp-btn', '⛶'); full.title = 'Vergrössern / verkleinern';
        var min   = el('button', 'pp-btn', '–'); min.title = 'Einklappen';
        head.appendChild(title); head.appendChild(full); head.appendChild(min);

        var body  = el('div', 'pp-body');
        var frame = el('iframe'); frame.id = 'pp-frame';
        frame.src = ISE_URL; frame.title = 'Priority Widget – Eisenhower-Wochenplaner';
        frame.setAttribute('allow', 'clipboard-write');
        body.appendChild(frame);

        panel.appendChild(head); panel.appendChild(body);
        root.appendChild(tab); root.appendChild(panel);
        document.body.appendChild(root);

        function apply() {
            root.className = (state.open ? 'is-open' : '') + (state.full ? ' is-full' : '');
        }
        function openDrawer(v) {
            state.open = v; save('ise_open', v ? '1' : '0');
            if (!v) { state.full = false; save('ise_full', '0'); }
            apply(); console.log('[pp-widget] open=', v);
        }

        tab.addEventListener('click', function () { openDrawer(!state.open); });
        min.addEventListener('click', function () { openDrawer(false); });
        full.addEventListener('click', function () {
            state.full = !state.full; save('ise_full', state.full ? '1' : '0');
            if (state.full) { state.open = true; save('ise_open', '1'); }
            apply(); console.log('[pp-widget] full=', state.full);
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && state.full) {
                state.full = false; save('ise_full', '0'); apply();
            }
        });

        apply();
        console.log('[pp-widget] bereit (Drawer)');
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', build);
    } else { build(); }
})();
