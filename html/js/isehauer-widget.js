// Schwebendes Isehauer-Widget (Eisenhower-Wochenplaner, eigener Container Port 3005).
// Stil: REITER/DRAWER — ein vertikaler Reiter "🐸 Wochenplaner" am rechten Rand; Klick fährt
// einen Drawer über die volle Höhe ein. position:fixed → läuft beim Scrollen mit. ⛶ vergrössert
// auf die ganze Seite (Esc verkleinert). Offen/Vollbild-Zustand wird in localStorage gemerkt.
//
// Isehauer wird cross-origin via Caddy-Subdomain im iframe eingebettet (setzt kein
// X-Frame-Options/CSP). Erreichbar nur im Heimnetz via Split-DNS.
//
// Einbinden: <script src="/js/isehauer-widget.js?v=..." defer></script>
// Muster bewusst wie nav.js: eine self-contained Datei, injiziert eigenes CSS + DOM.
(function () {
    'use strict';

    var ISE_URL = (typeof window.DASHBOARD_CONFIG !== 'undefined' && window.DASHBOARD_CONFIG.isehauer_url)
        ? window.DASHBOARD_CONFIG.isehauer_url
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
    console.log('[ise-widget] Init-Zustand:', JSON.stringify(state));

    var CSS = `
    #ise-w, #ise-w * { box-sizing: border-box; }
    #ise-w {
        --ise-bg:#0b0d13; --ise-border:#2a2d3e; --ise-fg:#e2e8f0; --ise-accent:#4a9eff;
        position: fixed; z-index: 2600;
        font: 500 .85rem system-ui, -apple-system, sans-serif;
    }
    /* Reiter am rechten Rand */
    .ise-tab {
        position: fixed; right: 0; top: 50%; transform: translateY(-50%);
        z-index: 2600; cursor: pointer;
        writing-mode: vertical-rl; text-orientation: mixed;
        background: var(--ise-accent); color:#fff; border:0;
        padding:.75rem .35rem; border-radius: 10px 0 0 10px; font-weight:700;
        box-shadow: -4px 0 16px rgba(0,0,0,.4); letter-spacing:.03em;
        transition: right .25s ease;
    }
    .ise-tab:hover { filter: brightness(1.08); }

    /* Drawer-Panel */
    .ise-panel {
        position: fixed; top: 0; right: 0; bottom: 0; height: 100vh;
        width: 420px; max-width: 92vw;
        display: flex; flex-direction: column;
        background: var(--ise-bg); border-left: 1px solid var(--ise-border);
        box-shadow: -12px 0 40px rgba(0,0,0,.55);
        transform: translateX(100%); transition: transform .25s ease;
    }
    #ise-w.is-open .ise-panel { transform: translateX(0); }
    #ise-w.is-open .ise-tab   { right: 420px; }
    @media (max-width:480px){ #ise-w.is-open .ise-tab { right: 92vw; } }

    .ise-head {
        display: flex; align-items: center; gap:.4rem;
        padding: .35rem .5rem; background:#11141d;
        border-bottom: 1px solid var(--ise-border); flex: 0 0 auto;
    }
    .ise-title { color: var(--ise-fg); font-weight:700; white-space:nowrap;
                 overflow:hidden; text-overflow:ellipsis; flex:1 1 auto; }
    .ise-btn {
        background:#1a1d27; color:#8892a4; border:1px solid var(--ise-border);
        border-radius:7px; cursor:pointer; padding:.25rem .45rem; font-size:.9rem;
        line-height:1; transition:background .12s,color .12s;
    }
    .ise-btn:hover { color: var(--ise-fg); background:#222634; }
    .ise-body { flex:1 1 auto; min-height:0; position:relative; }
    #ise-frame { position:absolute; inset:0; width:100%; height:100%; border:0; background:#0b0d13; }

    /* Vollbild */
    #ise-w.is-full .ise-panel {
        width:100% !important; max-width:none !important; border-left:0;
        transform:none !important; z-index:3000;
    }
    #ise-w.is-full .ise-tab { display:none; }
    `;

    function el(tag, cls, html) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        if (html != null) e.innerHTML = html;
        return e;
    }

    function build() {
        var style = el('style'); style.textContent = CSS; document.head.appendChild(style);

        var root = el('div'); root.id = 'ise-w';

        var tab = el('button', 'ise-tab', '🐸 Wochenplaner');
        tab.title = 'Wochenplaner öffnen/schliessen';

        var panel = el('div', 'ise-panel');
        var head  = el('div', 'ise-head');
        var title = el('div', 'ise-title', '🐸 Wochenplaner');
        var full  = el('button', 'ise-btn', '⛶'); full.title = 'Vergrössern / verkleinern';
        var min   = el('button', 'ise-btn', '–'); min.title = 'Einklappen';
        head.appendChild(title); head.appendChild(full); head.appendChild(min);

        var body  = el('div', 'ise-body');
        var frame = el('iframe'); frame.id = 'ise-frame';
        frame.src = ISE_URL; frame.title = 'Isehauer – Eisenhower-Wochenplaner';
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
            apply(); console.log('[ise-widget] open=', v);
        }

        tab.addEventListener('click', function () { openDrawer(!state.open); });
        min.addEventListener('click', function () { openDrawer(false); });
        full.addEventListener('click', function () {
            state.full = !state.full; save('ise_full', state.full ? '1' : '0');
            if (state.full) { state.open = true; save('ise_open', '1'); }
            apply(); console.log('[ise-widget] full=', state.full);
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && state.full) {
                state.full = false; save('ise_full', '0'); apply();
            }
        });

        apply();
        console.log('[ise-widget] bereit (Drawer)');
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', build);
    } else { build(); }
})();
