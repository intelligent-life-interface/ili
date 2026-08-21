// Schwebendes Prioritäten-Widget für die Einzel-Projektseite (project.html).
// Gleicher Reiter/Drawer-Look wie das Isehauer-Widget (index.html), ABER kein iframe:
// es lädt die Karten GENAU DIESES Projekts (board_id aus der URL) und ordnet sie
// "selbständig nach Priorität".
//
// Priorität:
//   - gesetzt   → card.priority ∈ {hoch, mittel, niedrig}
//   - fehlt     → lokale Schlagwort-Heuristik (deterministisch, gratis, ändert KEINE
//                 Board-Daten) schätzt eine Priorität; im UI als "geschätzt" markiert.
// Sortierung: Priorität (hoch→mittel→niedrig), innerhalb gleicher Prio die laufenden
//             Spalten (inprogress/review) zuerst.
//
// Ausgeblendet: erledigte Spalte (done / Titel "erledigt"), Sonderspalten navigation/
//               ki_archiv und die Beschreibungskarte claudemd-description.
//
// Einbinden: <script src="/js/project-prio-widget.js?v=..." defer></script>
// Eigene CSS-/DOM-Präfixe (pp-…) → keine Kollision mit dem Isehauer-Widget (ise-…).
(function () {
    'use strict';

    var params  = new URLSearchParams(window.location.search);
    var BOARD_ID = params.get('id') || 'default';

    // Spalten-Erkennung per Substring/Titel — Boards nutzen mal "done", mal "col_done".
    function colIsHidden(id) { return /navigation|ki_archiv/.test(id); }
    function colIsDone(id, title) { return /done/.test(id) || /erledig|fertig|abgeschlossen|done/.test(title); }
    function colRank(id, title) {
        if (/inprogress|in.?progress|bearbeitung|laufend/.test(id + ' ' + title)) return 0;
        if (/review|pr(ü|ue)f/.test(id + ' ' + title)) return 1;
        if (/backlog|offen|todo|ideen/.test(id + ' ' + title)) return 2;
        return 3;
    }
    var PRIO_META = {
        hoch:    { o: 0, dot: '🔴', txt: 'Hoch',    bg: '#4a1f1f', fg: '#fc8181' },
        mittel:  { o: 1, dot: '🟡', txt: 'Mittel',  bg: '#4a3a1f', fg: '#f6ad55' },
        niedrig: { o: 2, dot: '🟢', txt: 'Niedrig', bg: '#1f4a2a', fg: '#68d391' }
    };
    var COL_RANK = { inprogress: 0, review: 1, backlog: 2 };  // laufendes zuerst

    // Heuristik für fehlende Priorität
    var RE_HIGH = /\b(bug|fehler|fix|dringend|wichtig|sofort|kritisch|asap|deadline|frist|crash|down|ausfall|sicherheit|security|blocker)\b/i;
    var RE_LOW  = /\b(idee|sp(ä|ae)ter|evtl|eventuell|vielleicht|nice|optional|irgendwann|kosmetik|refactor|aufr(ä|ae)umen|cleanup|doku)\b/i;

    function load(key, def) {
        try { var v = localStorage.getItem(key); return v === null ? def : v; }
        catch (e) { return def; }
    }
    function save(key, val) { try { localStorage.setItem(key, val); } catch (e) {} }

    var state = {
        open: load('pp_open', '0') === '1',
        full: load('pp_full', '0') === '1'
    };
    console.log('[prio-widget] Init board=' + BOARD_ID + ' state=' + JSON.stringify(state));

    var CSS = `
    #pp-w, #pp-w * { box-sizing: border-box; }
    #pp-w {
        --pp-bg:#0b0d13; --pp-border:#2a2d3e; --pp-fg:#e2e8f0; --pp-accent:#9f7aea;
        position: fixed; z-index: 2500;
        font: 500 .85rem system-ui, -apple-system, sans-serif;
    }
    .pp-tab {
        position: fixed; right: 0; top: 38%; transform: translateY(-50%);
        z-index: 2500; cursor: pointer;
        writing-mode: vertical-rl; text-orientation: mixed;
        background: var(--pp-accent); color:#fff; border:0;
        padding:.75rem .35rem; border-radius: 10px 0 0 10px; font-weight:700;
        box-shadow: -4px 0 16px rgba(0,0,0,.4); letter-spacing:.03em;
        transition: right .25s ease;
    }
    .pp-tab:hover { filter: brightness(1.08); }
    .pp-panel {
        position: fixed; top: 0; right: 0; bottom: 0; height: 100vh;
        width: 380px; max-width: 92vw;
        display: flex; flex-direction: column;
        background: var(--pp-bg); border-left: 1px solid var(--pp-border);
        box-shadow: -12px 0 40px rgba(0,0,0,.55);
        transform: translateX(100%); transition: transform .25s ease;
    }
    #pp-w.is-open .pp-panel { transform: translateX(0); }
    #pp-w.is-open .pp-tab   { right: 380px; }
    @media (max-width:480px){ #pp-w.is-open .pp-tab { right: 92vw; } }

    .pp-head { display:flex; align-items:center; gap:.4rem;
        padding:.35rem .5rem; background:#11141d;
        border-bottom:1px solid var(--pp-border); flex:0 0 auto; }
    .pp-title { color:var(--pp-fg); font-weight:700; white-space:nowrap;
        overflow:hidden; text-overflow:ellipsis; flex:1 1 auto; }
    .pp-btn { background:#1a1d27; color:#8892a4; border:1px solid var(--pp-border);
        border-radius:7px; cursor:pointer; padding:.25rem .45rem; font-size:.9rem;
        line-height:1; transition:background .12s,color .12s; }
    .pp-btn:hover { color:var(--pp-fg); background:#222634; }

    .pp-body { flex:1 1 auto; min-height:0; overflow-y:auto; padding:.5rem .55rem .9rem; }
    .pp-group { margin:.6rem 0 .25rem; color:#cbd5e0; font-weight:700; font-size:.8rem;
        display:flex; align-items:center; gap:.35rem; position:sticky; top:-.5rem;
        background:var(--pp-bg); padding:.25rem 0; }
    .pp-group .pp-count { color:#718096; font-weight:600; }
    .pp-card { background:#141822; border:1px solid var(--pp-border);
        border-left:3px solid #444; border-radius:8px; padding:.4rem .5rem; margin:.3rem 0; }
    .pp-c-title { color:var(--pp-fg); font-weight:600; line-height:1.25; }
    .pp-c-meta { margin-top:.25rem; display:flex; flex-wrap:wrap; gap:.3rem; align-items:center; }
    .pp-chip { font-size:.68rem; padding:.1rem .35rem; border-radius:5px;
        background:#2d3748; color:#a0aec0; white-space:nowrap; }
    .pp-guess { font-size:.66rem; color:#805ad5; font-style:italic; }
    .pp-ki { color:#fff; background:#6b46c1; padding:.05rem .3rem; border-radius:5px; font-style:normal; font-weight:600; }
    .pp-btn.busy { opacity:.6; pointer-events:none; }
    .pp-empty, .pp-error { color:#718096; text-align:center; padding:1.5rem .5rem; }
    .pp-error { color:#fc8181; }

    #pp-w.is-full .pp-panel { width:100% !important; max-width:none !important;
        border-left:0; transform:none !important; z-index:3000; }
    #pp-w.is-full .pp-tab { display:none; }
    `;

    function el(tag, cls, html) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        if (html != null) e.innerHTML = html;
        return e;
    }
    const esc = window.escHtml;

    // Karten des Boards einsammeln (offene), Priorität bestimmen + sortieren
    function collect(board) {
        var out = [];
        (board.columns || []).forEach(function (col) {
            if (!col) return;
            var id = (col.id || '').toLowerCase();
            var t  = (col.title || '').toLowerCase();
            if (colIsHidden(id)) return;
            if (colIsDone(id, t)) return;
            (col.cards || []).forEach(function (c) {
                if (!c || c.id === 'claudemd-description') return;
                var prio = c.priority;
                var guessed = false;
                if (!PRIO_META[prio]) {
                    var txt = (c.title || '') + ' ' + (c.description || c.desc || '');
                    if (RE_HIGH.test(txt))      prio = 'hoch';
                    else if (RE_LOW.test(txt))  prio = 'niedrig';
                    else                        prio = 'mittel';
                    guessed = true;
                }
                out.push({
                    title: c.title || '(ohne Titel)',
                    prio: prio, source: guessed ? 'heuristik' : 'user',
                    col: col.title || col.id,
                    colRank: colRank(id, t),
                    effort: c.effort
                });
            });
        });
        out.sort(function (a, b) {
            var d = PRIO_META[a.prio].o - PRIO_META[b.prio].o;
            if (d) return d;
            return a.colRank - b.colRank;
        });
        console.log('[prio-widget] ' + out.length + ' offene Karten sortiert');
        return out;
    }

    function renderList(body, cards) {
        body.innerHTML = '';
        if (!cards.length) { body.appendChild(el('div', 'pp-empty', 'Keine offenen Karten in diesem Projekt.')); return; }
        ['hoch', 'mittel', 'niedrig'].forEach(function (p) {
            var group = cards.filter(function (c) { return c.prio === p; });
            if (!group.length) return;
            var m = PRIO_META[p];
            body.appendChild(el('div', 'pp-group',
                m.dot + ' ' + m.txt + ' <span class="pp-count">· ' + group.length + '</span>'));
            group.forEach(function (c) {
                var card = el('div', 'pp-card');
                card.style.borderLeftColor = m.fg;
                var meta = '<span class="pp-chip">' + esc(c.col) + '</span>';
                if (c.effort && PRIO_META[c.effort]) meta += '<span class="pp-chip">⏱ ' + PRIO_META[c.effort].txt + '</span>';
                if (c.source === 'ki')             meta += '<span class="pp-guess pp-ki">🤖 KI</span>';
                else if (c.source === 'heuristik') meta += '<span class="pp-guess">≈ geschätzt</span>';
                // source === 'user' (gesetzt) -> kein Badge, bleibt unangetastet
                card.innerHTML = '<div class="pp-c-title">' + esc(c.title) + '</div>'
                               + '<div class="pp-c-meta">' + meta + '</div>';
                body.appendChild(card);
            });
        });
    }

    function build() {
        var style = el('style'); style.textContent = CSS; document.head.appendChild(style);

        var root = el('div'); root.id = 'pp-w';
        var tab  = el('button', 'pp-tab', '🎯 Prioritäten');
        tab.title = 'Karten nach Priorität – öffnen/schliessen';

        var panel = el('div', 'pp-panel');
        var head  = el('div', 'pp-head');
        var title = el('div', 'pp-title', '🎯 Prioritäten');
        var ki    = el('button', 'pp-btn', '🤖 KI'); ki.title = 'Karten ohne Priorität von der KI einstufen (ändert nichts am Board)';
        var ref   = el('button', 'pp-btn', '🔄'); ref.title = 'Neu laden (lokal)';
        var full  = el('button', 'pp-btn', '⛶');  full.title = 'Vergrössern / verkleinern';
        var min   = el('button', 'pp-btn', '–');   min.title = 'Einklappen';
        head.appendChild(title); head.appendChild(ki); head.appendChild(ref); head.appendChild(full); head.appendChild(min);

        var body = el('div', 'pp-body');
        panel.appendChild(head); panel.appendChild(body);
        root.appendChild(tab); root.appendChild(panel);
        document.body.appendChild(root);

        function apply() {
            root.className = (state.open ? 'is-open' : '') + (state.full ? ' is-full' : '');
        }

        var loaded = false;
        function refresh() {
            body.innerHTML = '<div class="pp-empty">Lade Karten…</div>';
            fetch('/board?id=' + encodeURIComponent(BOARD_ID) + '&t=' + Date.now())
                .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
                .then(function (board) { renderList(body, collect(board)); loaded = true; })
                .catch(function (e) {
                    console.error('[prio-widget] Laden fehlgeschlagen:', e);
                    body.innerHTML = '<div class="pp-error">Karten konnten nicht geladen werden:<br>' + esc(e.message) + '</div>';
                });
        }
        // KI-Einstufung: nur Karten OHNE gesetzte Priorität gehen an Ollama; vom User
        // gesetzte Prioritäten bleiben unangetastet (Backend liefert source="user").
        function aiSuggest() {
            ki.classList.add('busy');
            body.innerHTML = '<div class="pp-empty">🤖 KI stuft Karten ein… (nur die ohne Priorität)</div>';
            fetch('/prio-suggest', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ board_id: BOARD_ID, ai: true })
            })
                .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
                .then(function (res) {
                    var cards = (res.cards || []).map(function (c) {
                        return { title: c.title, prio: c.priority, col: c.column,
                                 effort: c.effort, source: c.source };
                    });
                    renderList(body, cards);
                    loaded = true;
                    console.log('[prio-widget] KI-Prio: ' + cards.length + ' Karten, ai=' + res.ai);
                })
                .catch(function (e) {
                    console.error('[prio-widget] KI-Prio fehlgeschlagen:', e);
                    body.innerHTML = '<div class="pp-error">KI-Einstufung fehlgeschlagen:<br>' + esc(e.message) + '</div>';
                })
                .finally(function () { ki.classList.remove('busy'); });
        }

        function openDrawer(v) {
            state.open = v; save('pp_open', v ? '1' : '0');
            if (!v) { state.full = false; save('pp_full', '0'); }
            apply();
            if (v && !loaded) refresh();
            console.log('[prio-widget] open=', v);
        }

        tab.addEventListener('click', function () { openDrawer(!state.open); });
        min.addEventListener('click', function () { openDrawer(false); });
        ref.addEventListener('click', refresh);
        ki.addEventListener('click', aiSuggest);
        full.addEventListener('click', function () {
            state.full = !state.full; save('pp_full', state.full ? '1' : '0');
            if (state.full) { state.open = true; save('pp_open', '1'); }
            apply(); console.log('[prio-widget] full=', state.full);
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && state.full) { state.full = false; save('pp_full', '0'); apply(); }
        });

        apply();
        if (state.open) refresh();
        console.log('[prio-widget] bereit (Drawer, board=' + BOARD_ID + ')');
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', build);
    } else { build(); }
})();
