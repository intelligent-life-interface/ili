// project-core.js — Teil von project.js (aufgeteilt 2026-07-24, Kanban arch_6cb5b87e65).
// State, Board laden/speichern/autosave, Projekt-Links/Dateien, Auto/Modell/Testfirst-Toggles, Breadcrumbs, verwandte Projekte, Cleanup
// Klassik-Script, gemeinsamer globaler Scope mit den uebrigen project-*.js — Ladereihenfolge in project.html beachten.
// project.js — extrahiert aus project.html (FastAPI-Migration, Aufgabe B Schritt 2).
// Nutzt window.API aus /js/api.js — api.js muss VOR dieser Datei geladen werden.

// ── Block 1 (war Zeile 176–1850 in project.html) ──
// ── URL-Parameter ──────────────────────────────────────────────
const params = new URLSearchParams(window.location.search);
const BOARD_ID = params.get('id') || 'default';
const BOARD_API = '/board?id=' + encodeURIComponent(BOARD_ID);
const CHAT_API  = '/chat';
const MODELS_API = '/api/models';

const CLAUDE_MODELS = [
    { id: 'claude-sonnet-4-6', label: 'Claude Sonnet 4.6 ✦' },
    { id: 'claude-opus-4-7',   label: 'Claude Opus 4.7' },
    { id: 'claude-haiku-4-5-20251001', label: 'Claude Haiku 4.5' },
];
const FALLBACK_MODELS = ['mistral:latest', 'llama3.2:latest'];

console.log('[Project] Board-ID:', BOARD_ID);

const LABELS = [
    { color: null,      name: 'Kein Label' },
    { color: '#fc8181', name: 'Dringend' },
    { color: '#f6ad55', name: 'Wichtig' },
    { color: '#68d391', name: 'Fertig' },
    { color: '#4a90d9', name: 'Info' },
    { color: '#b794f4', name: 'Idee' },
    { color: '#76e4f7', name: 'Frage' },
];

// ── Board State ────────────────────────────────────────────────
let board = { id: BOARD_ID, title: BOARD_ID, columns: [] };
let dragCard = null;
let dragSrcCol = null;
let dragSrcIdx = null;
let placeholder = null;
let dragColIdx = null;       // Spalten-Drag&Drop (Teil 4a)
let dragSubIdx = null;       // Unterprojekt-Drag&Drop (Teil 4a)
const CLAUDE_MD_CARD_ID = 'claudemd-description';   // Beschreibungskarte (F1.3: aus dem Board extrahiert, lebt im Projekt-Kopf)
let claudeCard = null;             // F1.3: extrahierte Beschreibungskarte (wird beim Speichern re-injiziert)
let claudeCardColId = 'backlog';   // F1.3: Quell-Spalte der Beschreibungskarte (Re-Injektion an gleicher Stelle)

// ── Chat State ─────────────────────────────────────────────────
let chatHistory = [];   // [{role: 'user'|'assistant', content: string}]
let chatBusy = false;
let chatAbortController = null;

// ══════════════════════════════════════════════════════════════
// BOARD LADEN / SPEICHERN
// ══════════════════════════════════════════════════════════════
async function loadBoard(silent = false) {
    console.log('[Project] loadBoard() id=' + BOARD_ID + ' silent=' + silent);
    console.log('[Project] isMobile:', window.innerWidth <= 768 ? 'ja' : 'nein (Desktop)');
    try {
        console.log('[Project] Rufe API auf: ' + BOARD_API);
        board = await API.get(BOARD_API + '&t=' + Date.now());
        console.log('[Project] ✓ Board erfolgreich geladen:', board.columns ? board.columns.length : 0, 'Spalten, Titel:', board.title);
        console.log('[Project] Board-Daten:', JSON.stringify({
            id: board.id,
            title: board.title,
            columns: (board.columns || []).map(c => ({ id: c.id, title: c.title, cards: (c.cards || []).length }))
        }));

        // F1.3: Beschreibungskarte aus dem Board ziehen — lebt im Projekt-Kopf, nicht im Kanban
        extractClaudeCard();

        // Projekt-Name in Nav setzen. Der verlässliche Name lebt im Manifest
        // (entry.name), NICHT im Board-JSON — nur ~27/232 Boards haben ein
        // board.title. Darum hier nur setzen, wenn das Board-JSON ausnahmsweise
        // einen eigenen Titel trägt; sonst bleibt „⏳ Lade…" stehen, bis
        // loadParentBreadcrumb() gleich darauf den Manifest-Namen + den
        // „Unterprojekt – Mutterprojekt"-Tab-Titel setzt (verhindert das kurze
        // Aufblitzen der rohen sub_-ID).
        const nameEl = document.getElementById('project-name-nav');
        if (board.title) {
            nameEl.textContent = board.title;
            document.title = '📋 ' + board.title + ' · Home Server';
        }

        render();
        renderAutoBtn();   // Status hängt an den Kartenzahlen -> nach jedem Board-Laden neu
        // Deep-Link ?card=<id> (Ziel der Master-Links auf Spiegel-Karten)
        if (typeof focusCardFromUrl === 'function') focusCardFromUrl();
        renderProjectHead();   // F1.4: Stats/Beschreibung im Kopf aktualisieren
        updateAttProjCount();  // 📎-Zähler im Anhänge-Button
        if (!silent) setSaveStatus('', '');

        // Parent-Breadcrumb nachladen (nicht-blockierend)
        loadParentBreadcrumb().catch(e => console.warn('[Project] Breadcrumb Fehler:', e));

        // Direktlinks ins (Unter-)Projekt nachladen (nicht-blockierend)
        loadProjectLinks().catch(e => console.warn('[Project] Projekt-Links Fehler:', e));

        // Offene Entscheidungen nachladen -> Antwort-Knöpfe auf den Karten
        // (nicht-blockierend; rendert selbst neu, sobald die Optionen da sind)
        if (typeof loadDecisions === 'function')
            loadDecisions().catch(e => console.warn('[Project] Entscheidungen Fehler:', e));
    } catch(e) {
        console.error('[Project] Ladefehler:', e);
        document.getElementById('board').innerHTML =
            `<div style="color:#fc8181;padding:2rem">⚠️ Board nicht erreichbar: ${e.message}<br><small style="color:#4a5568">API-Endpunkt /board verfügbar?</small></div>`;
    }
}

// ── Direktlinks ins (Unter-)Projekt (Web-App / Dateien / GitHub / CLAUDE.md) ──
// Quelle: GET /api/project-links?id=<board>. work_dir = der Ordner, in dem auch die
// Terminal-tmux-Session läuft → der Link zeigt aufs tatsächlich bearbeitete Projekt.
const PROJECT_LINK_DEFS = [
    { key: 'webapp',      icon: '🌐', label: 'Web-App',   title: 'Laufende Web-App öffnen' },
    { key: 'services',    icon: '🖥', label: 'Service',   title: 'Eintrag in der Service-Übersicht' },
    { key: 'filebrowser', icon: '📁', label: 'Dateien',   title: 'Code-Ordner im Filebrowser öffnen' },
    { key: 'datadir',     icon: '🗂', label: 'Daten',     title: 'Datenordner (data/) im Filebrowser öffnen' },
    { key: 'github',      icon: '🐙', label: 'GitHub',    title: 'GitHub-Repo öffnen' },
    { key: 'claudemd',    icon: '📄', label: 'CLAUDE.md', title: 'Projekt-Doku (CLAUDE.md) öffnen' },
];

async function loadProjectLinks() {
    const el = document.getElementById('project-links');
    if (!el) return;
    console.log('[Project] loadProjectLinks() id=' + BOARD_ID);
    const data = await API.get('/api/project-links?id=' + encodeURIComponent(BOARD_ID));
    renderProjectLinks(data);
}

function renderProjectLinks(data) {
    const el = document.getElementById('project-links');
    if (!el) return;
    const links = (data && data.links) || {};
    const chips = PROJECT_LINK_DEFS
        .filter(d => links[d.key])
        .map(d => `<a class="proj-link" href="${escHtml(links[d.key])}" target="_blank" rel="noopener" title="${d.title}">${d.icon} ${d.label}</a>`);
    // Aus den Terminal-Protokollen gesammelte Links (LINKS.md, Projekt 'projekt-artefakte')
    const alinks = (data && data.artefakt_links) || [];
    const filesBtn = data.work_dir
        ? `<span class="proj-link proj-files-btn" id="proj-files-btn" title="Dateien des Projektordners direkt anzeigen">🗂 Datei-Liste ▾</span><div class="proj-files-drop" id="proj-files-drop" hidden></div>`
        : '';
    // Klick öffnet die gerenderte LINKS.md direkt (md.html); nur ein Longpress zeigt
    // stattdessen das Dropdown mit der Roh-Liste (analog Datei-Liste, Links anklickbar).
    const linksMdHref = `/md.html?id=${encodeURIComponent(BOARD_ID)}&file=LINKS.md`;
    const linksBtn = alinks.length
        ? `<a class="proj-link proj-files-btn" id="proj-links-btn" href="${escHtml(linksMdHref)}" target="_blank" rel="noopener" title="Klick: LINKS.md öffnen · Lang drücken: Liste als Dropdown">🔗 Links (${alinks.length}) ▾</a><div class="proj-files-drop" id="proj-links-drop" hidden></div>`
        : '';
    if (!chips.length && !linksBtn && !filesBtn) { el.innerHTML = ''; return; }
    const wd = data.work_dir ? `<span class="proj-link-dir" title="Arbeitsordner der Terminal-Session">📂 ${escHtml(data.work_dir)}</span>` : '';
    el.innerHTML = chips.join('') + filesBtn + linksBtn + wd;
    const btn = document.getElementById('proj-files-btn');
    if (btn) btn.addEventListener('click', toggleProjectFiles);
    const lbtn = document.getElementById('proj-links-btn');
    if (lbtn) {
        const LONG_PRESS_MS = 500;
        let holdTimer = null;
        let longPress = false;
        const openDrop = () => {
            longPress = true;
            const drop = document.getElementById('proj-links-drop');
            if (!drop) return;
            if (!drop.dataset.filled) {
                drop.innerHTML = alinks.map(u =>
                    `<a class="proj-files-item" href="${escHtml(u)}" target="_blank" rel="noopener" title="${escHtml(u)}">🔗 ${escHtml(u)}</a>`
                ).join('');
                drop.dataset.filled = '1';
            }
            drop.hidden = !drop.hidden;
        };
        const startHold = () => { longPress = false; clearTimeout(holdTimer); holdTimer = setTimeout(openDrop, LONG_PRESS_MS); };
        const cancelHold = () => clearTimeout(holdTimer);
        lbtn.addEventListener('mousedown', startHold);
        lbtn.addEventListener('touchstart', startHold, { passive: true });
        lbtn.addEventListener('mouseup', cancelHold);
        lbtn.addEventListener('mouseleave', cancelHold);
        lbtn.addEventListener('touchend', cancelHold);
        lbtn.addEventListener('touchmove', cancelHold);
        lbtn.addEventListener('contextmenu', e => e.preventDefault());
        // Normalklick soll ganz normal zur LINKS.md navigieren — nur nach ausgelöstem
        // Longpress wird die Default-Navigation unterdrückt (Dropdown steht schon offen).
        lbtn.addEventListener('click', e => { if (longPress) { e.preventDefault(); longPress = false; } });
    }
}

// 🗂 Datei-Liste: Dropdown mit den Dateien des Arbeitsordners (GET /api/project-files).
// Ordner/Dateien → Filebrowser; .md → gerenderte Ansicht (md.html, Links anklickbar).
// Als absolutes Overlay, damit adjustBoardHeight() nicht beeinflusst wird.
let projFilesLoaded = false;

async function toggleProjectFiles() {
    const drop = document.getElementById('proj-files-drop');
    if (!drop) return;
    if (!drop.hidden) { drop.hidden = true; return; }
    drop.hidden = false;
    if (projFilesLoaded) return;
    drop.innerHTML = '<div class="proj-files-empty">lädt…</div>';
    try {
        const data = await API.get('/api/project-files?id=' + encodeURIComponent(BOARD_ID));
        console.log('[Project] project-files:', (data.files || []).length, 'Einträge');
        renderProjectFiles(data);
        projFilesLoaded = true;
    } catch (e) {
        console.warn('[Project] project-files Fehler:', e);
        drop.innerHTML = '<div class="proj-files-empty">Fehler beim Laden der Dateiliste</div>';
    }
}

function fmtSize(n) {
    if (n >= 1048576) return (n / 1048576).toFixed(1) + ' MB';
    if (n >= 1024) return Math.round(n / 1024) + ' KB';
    return n + ' B';
}

function renderProjectFiles(data) {
    const drop = document.getElementById('proj-files-drop');
    if (!drop) return;
    const files = data.files || [];
    if (!files.length) { drop.innerHTML = '<div class="proj-files-empty">keine Dateien gefunden</div>'; return; }
    drop.innerHTML = files.map(f => {
        const icon = f.is_dir ? '📁' : (f.viewable ? '📖' : '📄');
        const href = f.viewable
            ? `/md.html?id=${encodeURIComponent(BOARD_ID)}&file=${encodeURIComponent(f.name)}`
            : (f.filebrowser || '#');
        const size = f.is_dir ? '' : `<span class="proj-file-size">${fmtSize(f.size)}</span>`;
        const title = f.viewable ? 'Gerenderte Ansicht öffnen (Links anklickbar)' : 'Im Filebrowser öffnen';
        return `<a class="proj-file-row" href="${escHtml(href)}" target="_blank" rel="noopener" title="${title}">${icon} <span class="proj-file-name">${escHtml(f.name)}</span>${size}</a>`;
    }).join('');
}

// 🤖 Auto-Entwicklung: Manifest-Flag `auto` togglen (Kanban-Automat ~/containers/kanban-automat).
// Freigegebene Boards arbeitet der stündliche Watchdog autonom mit headless Claude ab.
//
// Der Button zeigt denselben 4-Status wie die Kachel in der Projektliste (index.js
// AUTO_STATE/autoStateKey) — Vorgabe 06.08.26: „der Button hier im Projekt soll synchron
// mit der Liste sein." Vorher stand hier stur AN/aus, man sah also nie, ob der Automat
// noch etwas zu tun hat. Nur `aus` ↔ `an` sind klickbar (Feld `auto`); `abgeschlossen`
// und `Entscheidung nötig` sind ABGELEITET und werden nie gespeichert — das Freigabe-Flag
// gehört dem Projektinhaber allein („Aus ist, wenn ich sie auf aus schalte").
const AUTO_STATE = {
    aus:          { emoji: '⚪', text: 'aus',           cls: null,
                    title: 'Projekt für den Kanban-Automaten freigeben (autonome Abarbeitung offener Karten). Klick = freigeben.' },
    an:           { emoji: '🤖', text: 'AN',            cls: 'auto-on',
                    title: 'Aktiv: Der Automat arbeitet offene Karten dieses Projekts autonom ab. Klick = sperren.' },
    erledigt:     { emoji: '✅', text: 'abgeschlossen', cls: 'auto-done',
                    title: 'Der Automat ist durch: keine Karten mehr in Backlog/In Arbeit. Die Freigabe bleibt an — Klick = sperren.' },
    entscheidung: { emoji: '🙋', text: 'Entscheidung nötig', cls: 'auto-decide',
                    title: 'Der Automat wartet auf deine Antwort zu einer Entscheidungskarte. Klick = sperren.' }
};

// Board-Status, bei denen der Automat NIE arbeitet (siehe kanban-automat/automat_lib.py
// PAUSED_STATUSES) — unabhängig vom `auto`-Flag. Auto=an + einer dieser Status ist ein
// stiller Widerspruch: der User denkt der Automat läuft, tut er aber nicht. Darum Warnung.
const PAUSED_PROJECT_STATUSES = ['pausiert', 'archiviert'];

// Kartenzählung identisch zum Backend (`dashboard_service._count_automat_open`, Basis des
// Status in der Projektliste): Karten in `backlog`/`in_progress`/`gemeldet` ohne Meta-Karten.
// Die CLAUDE.md-Beschreibungskarte ist hier ohnehin schon raus — extractClaudeCard() löst sie
// beim Laden aus den Spalten (sie lebt im Projekt-Kopf, nicht im Kanban) — darum wird sie
// bewusst NICHT zurückgezählt. Beide Ansichten kommen so auf dieselbe Zahl.
// Gemeldete Karten zählen auch als "zu bearbeiten", damit der Auto-Button nicht fälschlicherweise
// "erledigt" anzeigt, wenn Bugs/Features in der Spalte "gemeldet" vorhanden sind (Bug 2026-08-17).
function autoOpenCards() {
    let n = 0;
    (board.columns || []).forEach(col => {
        if (col.id === 'backlog' || col.id === 'in_progress' || col.id === 'gemeldet') n += (col.cards || []).length;
    });
    return n;
}

function autoStateKey() {
    if (!(projHeadEntry && projHeadEntry.auto)) return 'aus';
    // DECISIONS_BY_CARD (project-decisions.js) hält die offenen Entscheidungen DIESES Boards
    if (typeof DECISIONS_BY_CARD === 'object' && Object.keys(DECISIONS_BY_CARD || {}).length)
        return 'entscheidung';
    return autoOpenCards() === 0 ? 'erledigt' : 'an';
}

function renderAutoBtn() {
    const btn = document.getElementById('auto-dev-btn');
    if (!btn) return;
    const key = autoStateKey();
    const st = AUTO_STATE[key];
    const statusBlocks = key !== 'aus' && PAUSED_PROJECT_STATUSES.includes(projHeadEntry?.status);
    btn.textContent = st.emoji + ' Auto-Entwicklung: ' + st.text + (statusBlocks ? ' ⚠️' : '');
    ['auto-on', 'auto-done', 'auto-decide'].forEach(c => btn.classList.toggle(c, st.cls === c));
    btn.classList.toggle('auto-status-warn', statusBlocks);
    btn.title = statusBlocks
        ? `Achtung: Projekt-Status ist "${projHeadEntry.status}" — der Automat überspringt dieses Board deshalb still, obwohl Auto-Entwicklung an ist. Status auf „aktiv" setzen, wenn weitergearbeitet werden soll, sonst passiert nichts.`
        : st.title;
    console.log('[Auto] Status', BOARD_ID, '=', key, '(offene Karten:', autoOpenCards() + ')',
        statusBlocks ? '— WARNUNG: Status "' + projHeadEntry.status + '" blockiert den Automaten' : '');
}

async function toggleAuto() {
    if (!projHeadEntry) { console.warn('[Auto] kein Manifest-Eintrag geladen'); return; }
    const next = !projHeadEntry.auto;
    const btn = document.getElementById('auto-dev-btn');
    if (btn) btn.disabled = true;
    try {
        await API.patchBoard(BOARD_ID, { auto: next });
        projHeadEntry.auto = next;               // optimistisch übernehmen
        renderAutoBtn();
        console.log('[Auto] Board', BOARD_ID, 'auto =', next);
    } catch (e) {
        console.error('[Auto] Umschalten fehlgeschlagen:', e);
        alert('Konnte Auto-Entwicklung nicht umschalten: ' + e);
    } finally {
        if (btn) btn.disabled = false;
    }
}

// 📦 Batch-Vorschläge: Manifest-Flag `automat_batch` togglen (Kanban-Automat batch.py).
// Freigegebene Boards bekommen für offene Karten über die Message Batches API günstige
// Text-Vorschläge (parallel zum Abo, kein Datei-Editieren). Wirkt nur zusätzlich zum
// globalen Schalter batch_enabled=1 + Kostenlimit der Projektgruppe (batch_budget.json).
function renderBatchBtn() {
    const btn = document.getElementById('auto-batch-btn');
    if (!btn) return;
    const on = !!(projHeadEntry && projHeadEntry.automat_batch);
    btn.textContent = '📦 API batch mode: ' + (on ? 'AN' : 'aus');
    btn.classList.toggle('batch-on', on);
    btn.title = on
        ? 'Aktiv: Der Kanban-Automat holt für offene Karten dieses Projekts günstige Vorschläge über die Message Batches API (parallel zum Abo). Betrifft NUR den Automaten. Wirkt nur, wenn global batch_enabled=1 ist und die Projektgruppe ein Kostenlimit hat. Klick = aus.'
        : 'API batch mode einschalten (nur für den Kanban-Automaten): günstige Karten-Vorschläge über die Message Batches API (parallel zum Abo, kein Datei-Editieren). Braucht zusätzlich global batch_enabled=1 + Kostenlimit der Projektgruppe. Klick = ein.';
}

async function toggleBatch() {
    if (!projHeadEntry) { console.warn('[Batch] kein Manifest-Eintrag geladen'); return; }
    const next = !projHeadEntry.automat_batch;
    const btn = document.getElementById('auto-batch-btn');
    if (btn) btn.disabled = true;
    try {
        await API.patchBoard(BOARD_ID, { automat_batch: next });
        projHeadEntry.automat_batch = next;      // optimistisch übernehmen
        renderBatchBtn();
        console.log('[Batch] Board', BOARD_ID, 'automat_batch =', next);
    } catch (e) {
        console.error('[Batch] Umschalten fehlgeschlagen:', e);
        alert('Konnte Batch-Vorschläge nicht umschalten: ' + e);
    } finally {
        if (btn) btn.disabled = false;
    }
}

// 🧪 Testversion zuerst: Manifest-Flag `test_first` (Tri-State).
// true/false = eigener Wert; nicht gesetzt = erbt via parent_ids vom Mutterprojekt.
// Ausgewertet vom Kanban-Automaten (Worker-Prompt) + Container-Manager :8810 (test-deploy).
// Nutzt die bestehende allBoardsCache (Deklaration im UNTERPROJEKTE-Block) mit —
// loadParentBreadcrumb befüllt sie beim Laden aus /boards?all=1.

// Effektiven test_first-Wert auflösen: eigener Wert gewinnt, sonst parent_ids-Kette
// hochlaufen (BFS, zyklussicher). Liefert {value, source} — source = Board-ID des Erbgebers.
function resolveTestFirst(entry, boards) {
    if (typeof entry.test_first === 'boolean') return { value: entry.test_first, source: entry.id };
    const byId = Object.fromEntries(boards.map(b => [b.id, b]));
    const seen = new Set([entry.id]);
    let queue = (entry.parent_ids || (entry.parent_id ? [entry.parent_id] : [])).slice();
    while (queue.length) {
        const next = [];
        for (const pid of queue) {
            if (seen.has(pid)) continue;
            seen.add(pid);
            const p = byId[pid];
            if (!p) continue;
            if (typeof p.test_first === 'boolean') return { value: p.test_first, source: pid };
            next.push(...(p.parent_ids || (p.parent_id ? [p.parent_id] : [])));
        }
        queue = next;
    }
    return { value: false, source: null };   // nirgends gesetzt = aus
}

function renderTestFirstBtn() {
    const btn = document.getElementById('test-first-btn');
    if (!btn || !projHeadEntry) return;
    const own = typeof projHeadEntry.test_first === 'boolean';
    const eff = resolveTestFirst(projHeadEntry, allBoardsCache);
    if (own) {
        btn.textContent = '🧪 Testversion: ' + (eff.value ? 'AN' : 'AUS');
    } else if (eff.source) {
        btn.textContent = `🧪 Testversion: ${eff.value ? 'AN' : 'AUS'} (geerbt von ${eff.source})`;
    } else {
        btn.textContent = '🧪 Testversion: aus (erbt)';
    }
    btn.classList.toggle('test-on', own && eff.value);
    btn.classList.toggle('test-inherited', !own && eff.value);
    console.log('[TestFirst] Board', BOARD_ID, 'eigen =', own ? projHeadEntry.test_first : '(erbt)',
                '→ effektiv =', eff.value, 'Quelle =', eff.source);
}

// Klick-Zyklus: erbt → true → false → erbt (null löscht das Flag im Manifest)
async function toggleTestFirst() {
    if (!projHeadEntry) { console.warn('[TestFirst] kein Manifest-Eintrag geladen'); return; }
    const cur = projHeadEntry.test_first;
    const next = (typeof cur !== 'boolean') ? true : (cur ? false : null);
    const btn = document.getElementById('test-first-btn');
    if (btn) btn.disabled = true;
    try {
        await API.patchBoard(BOARD_ID, { test_first: next });
        if (next === null) delete projHeadEntry.test_first;   // optimistisch übernehmen
        else projHeadEntry.test_first = next;
        renderTestFirstBtn();
        console.log('[TestFirst] Board', BOARD_ID, 'test_first =', next);
    } catch (e) {
        console.error('[TestFirst] Umschalten fehlgeschlagen:', e);
        alert('Konnte Testversion-Einstellung nicht umschalten: ' + e);
    } finally {
        if (btn) btn.disabled = false;
    }
}

// 🧠 Soll-Modell des Kanban-Automaten (Manifest-Feld `model`, leer = Standard Sonnet 5).
// Der Automat entwickelt bei Parallelbetrieb eine Stufe TIEFER und lässt das hier
// gewählte Modell anschliessend prüfen (~/containers/kanban-automat/models.py + review.py).
function renderModelPick() {
    const sel = document.getElementById('model-select');
    if (!sel || !projHeadEntry) return;
    sel.value = projHeadEntry.model || '';
    console.log('[Modell] Board', BOARD_ID, 'model =', projHeadEntry.model || '(Standard)');
}

async function setBoardModel(value) {
    if (!projHeadEntry) { console.warn('[Modell] kein Manifest-Eintrag geladen'); return; }
    const sel = document.getElementById('model-select');
    const prev = projHeadEntry.model || '';
    if (sel) sel.disabled = true;
    try {
        await API.patchBoard(BOARD_ID, { model: value || null });   // null = Feld entfernen
        if (value) projHeadEntry.model = value; else delete projHeadEntry.model;
        console.log('[Modell] Board', BOARD_ID, 'model =', value || '(Standard)');
    } catch (e) {
        console.error('[Modell] Setzen fehlgeschlagen:', e);
        alert('Konnte das Modell nicht setzen: ' + e);
        if (sel) sel.value = prev;
    } finally {
        if (sel) sel.disabled = false;
    }
}

async function loadParentBreadcrumb() {
    const data = await API.get('/boards?all=1&t=' + Date.now());
    const allBoards = Array.isArray(data) ? data : (data.boards || []);
    allBoardsCache = allBoards;      // 🧪 für test_first-Vererbung merken

    // Eigenen Manifest-Eintrag finden
    const entry = allBoards.find(b => b.id === BOARD_ID);
    if (!entry) return;

    // F1.4: Manifest-Eintrag für den Projekt-Kopf merken
    projHeadEntry = entry;
    renderProjectHead();
    renderAutoBtn();   // 🤖 Auto-Entwicklung-Toggle anhand entry.auto darstellen
    renderBatchBtn();  // 📦 Batch-Vorschläge-Toggle anhand entry.automat_batch
    renderTestFirstBtn();   // 🧪 Testversion-zuerst-Toggle (inkl. Vererbung)
    renderModelPick();      // 🧠 Soll-Modell des Automaten für dieses Projekt

    // Projekt-Name autoritativ aus dem Manifest (Board-JSON hat meist kein
    // title → sonst stünde die rohe sub_-ID da). Fallbacks der Vollständigkeit
    // halber. seq_id-Badge davor.
    const projName = entry.name || board.title || BOARD_ID;
    const nameEl = document.getElementById('project-name-nav');
    if (nameEl) {
        if (entry.seq_id) {
            const seqStr = '#' + String(entry.seq_id).padStart(3, '0');
            nameEl.innerHTML = `<span class="seq-badge">${seqStr}</span>${escHtml(projName)}`;
            console.log('[Project] seq_id:', seqStr);
        } else {
            nameEl.textContent = projName;
        }
    }

    // parent_ids ermitteln
    let parentIds = [];
    if (Array.isArray(entry.parent_ids)) parentIds = entry.parent_ids;
    else if (entry.parent_id) parentIds = [entry.parent_id];

    // Tab-Titel: „Unterprojekt – Mutterprojekt" (bei Top-Level nur der
    // Projektname). Gilt für ALLE Projekte, nicht nur dieses. Mehrere Eltern
    // werden mit „ / " verbunden.
    const parentNames = parentIds
        .map(pid => { const p = allBoards.find(b => b.id === pid); return p ? p.name : null; })
        .filter(Boolean);
    document.title = '📋 ' + projName
        + (parentNames.length ? ' – ' + parentNames.join(' / ') : '')
        + ' · Home Server';
    console.log('[Project] Tab-Titel:', document.title);

    renderNavCrumbs(allBoards, parentIds);
}

// Navigations-Leiste unter der Projekt-Zeile: links der Weg nach oben
// (Projekt-Übersicht + Mutterprojekt(e)), rechts (kleiner) die Geschwister-
// Unterprojekte — alle Boards, die denselben Parent haben, ausser sich selbst.
// Nutzt die bereits geladenen allBoards (aus /boards?all=1), damit dafür kein
// zusätzlicher Request nötig ist.
//
// Die Leiste wird IMMER angezeigt: bei Top-Level-Projekten steht links nur
// „🏠 Projekte". Vorher war sie bei den 134 Boards ohne Parent komplett
// ausgeblendet, was wie eine kaputte Navigation aussah.
function renderNavCrumbs(allBoards, parentIds) {
    const wrap = document.getElementById('project-nav-crumbs');
    if (!wrap) return;
    wrap.innerHTML = '';

    const left = document.createElement('div');
    left.className = 'crumbs-left';
    left.appendChild(makeCrumbBtn({ id: '', name: 'Projekte', icon: '📁' }, 'crumb-home-btn', '', '/'));

    // Eltern auflösen; zeigt eine parent_id auf ein gelöschtes Board, wird der
    // Link trotzdem gebaut (mit roher ID + Warn-Hinweis) statt die ganze Leiste
    // zu verstecken — sonst verschwindet die Navigation bei kaputten Verweisen.
    parentIds.forEach(pid => {
        const p = allBoards.find(b => b.id === pid);
        if (p) {
            left.appendChild(makeCrumbBtn(p, 'crumb-parent-btn', '⬅ '));
        } else {
            console.warn('[Project] Elternprojekt nicht im Manifest:', pid);
            const btn = makeCrumbBtn({ id: pid, name: pid, icon: '⚠️' }, 'crumb-parent-btn crumb-broken', '⬅ ');
            btn.title = 'Mutterprojekt „' + pid + '" existiert nicht mehr';
            left.appendChild(btn);
        }
    });
    console.log('[Project] Elternprojekte:', parentIds.length ? parentIds : '(Top-Level)');

    const parentIdSet = new Set(parentIds);
    const siblings = allBoards.filter(b => {
        if (b.id === BOARD_ID) return false;
        const bParents = Array.isArray(b.parent_ids) ? b.parent_ids : (b.parent_id ? [b.parent_id] : []);
        return bParents.some(pid => parentIdSet.has(pid));
    });
    console.log('[Project] Geschwisterprojekte:', siblings.length);

    const right = document.createElement('div');
    right.className = 'crumbs-right';
    siblings.forEach(s => right.appendChild(makeCrumbBtn(s, 'crumb-sibling-btn')));

    wrap.appendChild(left);
    wrap.appendChild(right);
    wrap.style.display = 'flex';
}

function makeCrumbBtn(b, extraClass, prefix, hrefOverride) {
    const a = document.createElement('a');
    a.className = 'crumb-btn ' + extraClass;
    a.href = hrefOverride || ('/project.html?id=' + encodeURIComponent(b.id));
    a.title = b.name;
    a.textContent = (prefix || '') + (b.icon || '📋') + ' ' + b.name;
    return a;
}

// F1.3: ALLE claudemd-Karten aus dem Board entfernen, die erste behalten (Kopf-Datenquelle).
// Quell-Spalte merken, damit saveBoard() die Karte an gleicher Stelle re-injiziert.
function extractClaudeCard() {
    claudeCard = null;
    (board.columns || []).forEach(col => {
        const hits = (col.cards || []).filter(c => c.id === CLAUDE_MD_CARD_ID);
        if (hits.length && !claudeCard) {
            claudeCard = hits[0];
            claudeCardColId = col.id;
        }
        if (hits.length) col.cards = col.cards.filter(c => c.id !== CLAUDE_MD_CARD_ID);
    });
    console.log('[Project] extractClaudeCard: ' + (claudeCard ? 'gefunden in Spalte ' + claudeCardColId : 'keine Beschreibungskarte'));
}

// F1.3: Payload = Kopie des Boards mit re-injizierter claudemd-Karte (Quell-Spalte,
// Fallback: erste Nicht-navigation-Spalte). board selbst bleibt OHNE die Karte.
function buildSavePayload() {
    const payload = JSON.parse(JSON.stringify(board));   // Kopie inkl. rev (F4)
    if (claudeCard) {
        let col = (payload.columns || []).find(c => c.id === claudeCardColId);
        if (!col) col = (payload.columns || []).find(c => c.id !== 'navigation');
        if (col) {
            (col.cards = col.cards || []).unshift(claudeCard);
            console.log('[Project] buildSavePayload: claudemd-Karte re-injiziert in Spalte ' + col.id);
        } else {
            console.warn('[Project] buildSavePayload: keine Spalte für claudemd-Karte gefunden!');
        }
    }
    return payload;
}

async function saveBoard() {
    console.log('[Project] saveBoard() id=' + BOARD_ID + ' rev=' + (board.rev ?? '–'));
    setSaveStatus('⏳ Speichern…', '');
    try {
        const result = await API.saveBoard(BOARD_ID, buildSavePayload());
        if (result && typeof result.rev === 'number') board.rev = result.rev;  // F4
        setSaveStatus('✅ Gespeichert', 'ok');
        console.log('[Project] Board gespeichert (rev ' + board.rev + ')');
        setTimeout(() => setSaveStatus('', ''), 2500);
    } catch(e) {
        console.error('[Project] Speicherfehler:', e);
        if (e.status === 409) {
            // F4: dieser Tab ist veraltet — NICHT überschreiben, Nutzer entscheidet
            setSaveStatus('⚠️ Board wurde inzwischen geändert — neu laden!', 'err');
            if (confirm('Dieses Board wurde inzwischen woanders geändert.\n\nSeite neu laden? (Deine letzte Änderung in diesem Tab geht verloren)')) {
                location.reload();
            }
            return;
        }
        setSaveStatus('❌ ' + e.message, 'err');
    }
}

function setSaveStatus(text, cls) {
    const el = document.getElementById('save-status');
    el.textContent = text;
    el.className = cls;
}

async function reloadBoard() {
    console.log('[Project] reloadBoard() nach KI-Antwort');
    await loadBoard(true);
    await loadSubprojects();
    rollupData = null;
    await loadRollup();
    setSaveStatus('↻ Board aktualisiert', 'ok');
    setTimeout(() => setSaveStatus('', ''), 2000);
}

// Auto-Save mit 500ms Debounce
let autoSaveTimer = null;
function autoSave() {
    clearTimeout(autoSaveTimer);
    autoSaveTimer = setTimeout(() => {
        console.log('[Project] autoSave ausgelöst');
        saveBoard();
    }, 500);
}

// ══════════════════════════════════════════════════════════════
// ORDNEN (Teil 4) + VERWANDTE PROJEKTE (Teil 3)
// ══════════════════════════════════════════════════════════════

// Teil 4b: Karten je Spalte nach Label, dann erstem KI-Tag/Titel sortieren.
function _cardSortKey(card) {
    const label = card.label || '';
    const body = card.description || card.desc || '';
    const m = body.match(/🏷️ KI-Tags:\s*([^\n·]+)/);
    const firstTag = m ? m[1].split(',')[0].trim().toLowerCase() : '';
    return (label ? '0' + label : '1') + '|' + (firstTag || (card.title || '').toLowerCase());
}
function autoSortCards() {
    (board.columns || []).forEach(col => {
        if (col.id === 'navigation') return;
        const cards = (col.cards || []).slice();
        cards.sort((a, b) => _cardSortKey(a).localeCompare(_cardSortKey(b), 'de'));
        col.cards = cards;
    });
    console.log('[Project] Karten auto-sortiert');
    render();
    autoSave();
}

// Teil 4a: Unterprojekt-Reihenfolge persistieren (child_order am Parent-Manifest)
async function persistChildOrder() {
    const order = subprojectsData.map(s => s.id);
    try {
        await API.patchBoard(BOARD_ID, { child_order: order });
        console.log('[Project] child_order gespeichert:', order);
    } catch (e) {
        console.error('[Project] child_order PATCH fehlgeschlagen:', e);
    }
}

// Teil 3: verwandte Projekte über Tags (nur Tags+Namen an die KI)
async function findRelated() {
    const statusEl = document.getElementById('related-status');
    const panel = document.getElementById('related-panel');
    statusEl.textContent = '⏳ Suche…';
    panel.style.display = 'block';
    panel.innerHTML = '';
    try {
        const data = await API.get('/find-related?project=' + encodeURIComponent(BOARD_ID) + '&n=8');
        statusEl.textContent = '';
        if (!data.related || data.related.length === 0) {
            panel.innerHTML = '<div class="related-empty">' + (data.note || 'Keine verwandten Projekte gefunden.') + '</div>';
            return;
        }
        const rows = data.related.map(r => {
            const tags = (r.shared_tags || []).map(t => '<span class="related-tag">' + escHtmlRel(t) + '</span>').join('');
            return '<a class="related-item" href="/project.html?id=' + encodeURIComponent(r.id) + '">' +
                   '<div class="related-head"><span class="related-name">' + escHtmlRel(r.name || r.id) + '</span>' +
                   '<span class="related-score">' + Math.round((r.score || 0) * 100) + '%</span></div>' +
                   '<div class="related-reason">' + escHtmlRel(r.reason || '') + '</div>' +
                   '<div class="related-tags">' + tags + '</div></a>';
        }).join('');
        panel.innerHTML = '<div class="related-title">🔗 Verwandte Projekte (' + data.count + ')</div>' + rows;
    } catch (e) {
        statusEl.textContent = '❌ ' + e.message;
        console.error('[Project] findRelated Fehler:', e);
    }
}
const escHtmlRel = window.escHtml;

// 🧹 Aufräumen — löst den zeitgesteuerten Aufräumer (kanban-split) für DIESES Board aus.
// Zweistufig: erst Vorschau (Trockenlauf, schreibt nichts), dann auf Bestätigung anwenden
// (legt Unterprojekte an + verschiebt Karten; das Backend macht vorher ein Backup).
async function cleanupBoard(btn) {
    if (btn) { btn.disabled = true; btn.dataset._t = btn.textContent; btn.textContent = '🧹 Prüfe… (~30s)'; }
    const restore = () => { if (btn) { btn.disabled = false; btn.textContent = btn.dataset._t || '🧹 Aufräumen'; } };
    try {
        // Schritt 1: Vorschau (apply=false → schreibt nichts)
        const preview = await API.post('/cleanup-board', { board_id: BOARD_ID, apply: false });
        const out = (preview && preview.output || '').trim() || '(keine Ausgabe)';
        if (!preview || preview.nothing_to_do) {
            alert('🧹 Aufräumer — Vorschau:\n\n' + out +
                  '\n\nNichts zu tun: Das Board ist nicht gross/gemischt genug, um es sinnvoll in Unterprojekte aufzuteilen.');
            return;
        }
        // Schritt 2: bestätigen, dann wirklich ausführen
        if (!confirm('🧹 Aufräumer — so würde aufgeteilt:\n\n' + out +
                     '\n\nJetzt wirklich ausführen? Es werden Unterprojekte angelegt und Karten verschoben (ein Backup wird vorher erstellt).')) {
            return;
        }
        if (btn) btn.textContent = '🧹 Räume auf…';
        const res = await API.post('/cleanup-board', { board_id: BOARD_ID, apply: true });
        alert('✅ Aufräumer fertig:\n\n' + ((res && res.output || '').trim() || '(keine Ausgabe)'));
        await loadBoard(true);          // Karten wurden verschoben → Board neu laden
        await loadSubprojects();        // neue Unterprojekte anzeigen
    } catch (e) {
        alert('❌ Aufräumer fehlgeschlagen: ' + (e.message || e));
        console.error('[Project] cleanupBoard Fehler:', e);
    } finally {
        restore();
    }
}

// ══════════════════════════════════════════════════════════════
// AUTO-RELOAD (Feature: automatisches Neuladen von Kanban + Beschreibung)
// ══════════════════════════════════════════════════════════════

let autoReloadInterval = null;
let autoReloadEnabled = false;
const AUTO_RELOAD_INTERVAL_MS = 60000;  // 60 Sekunden

function startAutoReload() {
    if (autoReloadEnabled) return;
    autoReloadEnabled = true;
    console.log('[Project] Auto-Reload gestartet (' + AUTO_RELOAD_INTERVAL_MS + 'ms)');
    updateAutoReloadButton();

    autoReloadInterval = setInterval(async () => {
        try {
            console.log('[Project] Auto-Reload: Kanban + Beschreibung werden neu geladen');
            await loadBoard(true);
            await loadProjectHead();
        } catch (e) {
            console.warn('[Project] Auto-Reload Fehler:', e.message);
        }
    }, AUTO_RELOAD_INTERVAL_MS);
}

function stopAutoReload() {
    if (!autoReloadEnabled) return;
    autoReloadEnabled = false;
    console.log('[Project] Auto-Reload gestoppt');
    if (autoReloadInterval) {
        clearInterval(autoReloadInterval);
        autoReloadInterval = null;
    }
    updateAutoReloadButton();
}

function toggleAutoReload() {
    if (autoReloadEnabled) {
        stopAutoReload();
    } else {
        startAutoReload();
    }
}

function updateAutoReloadButton() {
    const btn = document.querySelector('[data-auto-reload]') || document.getElementById('auto-reload-btn');
    if (btn) {
        if (autoReloadEnabled) {
            btn.classList.add('active');
            btn.textContent = '🔄 Auto-Reload: AN';
        } else {
            btn.classList.remove('active');
            btn.textContent = '🔄 Auto-Reload: AUS';
        }
    }
}

// ══════════════════════════════════════════════════════════════
// RENDER
// ══════════════════════════════════════════════════════════════
