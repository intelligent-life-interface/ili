// ki-advisor.js — aus ki-advisor.html extrahiert (Phase 5 Modularisierung).
// Benötigt /js/api.js (window.API) — Script-Reihenfolge: api.js VOR ki-advisor.js.
// "ADVISOR_URL" hiess vorher "API" (umbenannt wegen Kollision mit window.API).
const ADVISOR_URL = '/ki-advisor';
let pollInterval = null;
let lastStatus   = null;

// ── Hilfsfunktionen ──────────────────────────────────────────

function fmt(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleString('de-CH', { dateStyle: 'short', timeStyle: 'short' });
}

function duration(start, end) {
    if (!start || !end) return '';
    const s = Math.round((new Date(end) - new Date(start)) / 1000);
    if (s < 60)  return `${s}s`;
    if (s < 3600) return `${Math.floor(s/60)}m ${s%60}s`;
    return `${Math.floor(s/3600)}h ${Math.floor((s%3600)/60)}m`;
}

// ── Ollama Stats ─────────────────────────────────────────────

async function fetchOllamaStats() {
    try {
        const s = await window.API.get('/ollama-stats');
        renderOllama(s);
    } catch(e) {
        renderOllama({ online: false, error: String(e), running_models: [], all_models: [] });
    }
}

function renderOllama(s) {
    const card      = document.getElementById('ollama-card');
    const dot       = document.getElementById('ollama-dot');
    const title     = document.getElementById('ollama-title');
    const sub       = document.getElementById('ollama-sub');
    const modelsWrap= document.getElementById('ollama-models-wrap');
    const modelsList= document.getElementById('ollama-models-list');

    if (!s.online) {
        card.className = 'ollama-card offline';
        dot.className  = 'ollama-dot offline';
        title.textContent = 'KI-Server nicht erreichbar';
        sub.textContent   = s.error || 'Ollama (KI-Server) antwortet nicht';
        modelsWrap.style.display = 'none';
        return;
    }

    const loadedNames = new Set((s.running_models || []).map(m => m.name));
    const isWorking   = loadedNames.size > 0;

    card.className = 'ollama-card online';
    dot.className  = 'ollama-dot ' + (isWorking ? 'working' : 'online');
    title.textContent = 'KI-Server (Ollama)';
    sub.textContent   = isWorking
        ? `Aktiv — ${loadedNames.size} Modell(e) geladen`
        : `Bereit — ${s.model_count || 0} Modelle verfügbar, keines aktiv geladen`;

    modelsWrap.style.display = '';
    modelsList.innerHTML = (s.all_models || []).map(m => {
        const loaded = loadedNames.has(m.name);
        return `<div class="model-row ${loaded ? 'loaded' : ''}">
            <span class="model-name">${m.name}</span>
            <span class="model-size">${m.size}</span>
            <span class="model-badge ${loaded ? 'loaded' : 'idle'}">${loaded ? '⚡ geladen' : 'bereit'}</span>
        </div>`;
    }).join('');
}

// ── Aktivitäts-Log (laienverständlich) ───────────────────────

function renderActivity(s) {
    const section = document.getElementById('activity-section');
    const list    = document.getElementById('activity-list');
    const running = s.running === true;

    const processed = s.processed || [];
    const errors    = s.errors    || {};
    const added     = s.suggestions_added || {};
    const current   = s.current_board;
    const curName   = s.current_board_name || current;

    const items = [];

    // Aktuell laufendes Board
    if (running && current) {
        items.push({
            cls:  'cur',
            icon: '⟳',
            text: `Analysiere gerade: <strong>${curName}</strong>`,
            sub:  'Die KI liest den Code und überlegt sich Verbesserungsvorschläge…',
        });
    }

    // Bereits verarbeitete Boards
    processed.forEach(id => {
        const n = added[id] ?? 0;
        items.push({
            cls:  'ok',
            icon: '✓',
            text: `<strong>${id}</strong> — ${n} neue Vorschläge im Kanban`,
            sub:  n > 0 ? `Öffne das Projekt um die 🤖 KI-Karten im Backlog zu sehen` : 'Keine neuen Vorschläge (evtl. schon alles abgedeckt)',
        });
    });

    // Fehler
    Object.entries(errors).forEach(([id, msg]) => {
        items.push({
            cls:  'err',
            icon: '✗',
            text: `<strong>${id}</strong> — Fehler aufgetreten`,
            sub:  msg.length > 120 ? msg.slice(0, 120) + '…' : msg,
        });
    });

    if (items.length === 0) {
        section.style.display = 'none';
        return;
    }

    section.style.display = '';
    list.innerHTML = items.map(item => `
        <div class="activity-item ${item.cls}">
            <span class="activity-icon">${item.icon}</span>
            <div>
                <div class="activity-text">${item.text}</div>
                <div class="activity-sub">${item.sub}</div>
            </div>
        </div>
    `).join('');
}

// ── Render ───────────────────────────────────────────────────

function render(s) {
    const running = s.running === true;
    const dot     = document.getElementById('status-dot');
    const card    = document.getElementById('status-card');
    const title   = document.getElementById('status-title');
    const sub     = document.getElementById('status-sub');
    const pWrap   = document.getElementById('progress-wrap');
    const pBar    = document.getElementById('progress-bar');
    const pLabel  = document.getElementById('progress-label');
    const btnAll  = document.getElementById('btn-all');
    const lastInfo= document.getElementById('last-run-info');

    // Dot & card border
    dot.className  = 'status-dot ' + (running ? 'running' : (s.errors && Object.keys(s.errors).length ? 'error' : 'idle'));
    card.className = 'status-card ' + (running ? 'running' : 'idle');

    if (running) {
        const n      = s.current_index || 0;
        const tot    = s.total || 1;
        const name   = s.current_board_name || s.current_board || '…';
        const model  = s.current_model ? s.current_model.split(':')[0] : '';
        const round  = s.current_round;
        const rounds = s.total_rounds;

        title.textContent = `Analysiere: ${name}`;
        let subParts = [`Board ${n} von ${tot}`];
        if (model) subParts.push(`Modell: ${model}`);
        if (round && rounds) subParts.push(`Runde ${round}${round === 'Synthese' ? '' : ' von ' + rounds}`);
        subParts.push(`gestartet ${fmt(s.started_at)}`);
        sub.textContent = subParts.join(' · ');

        pWrap.style.display = '';
        pBar.style.width    = `${Math.round((n / tot) * 100)}%`;
        pLabel.textContent  = `${n} / ${tot}`;
        btnAll.disabled = true;
        const btnPanel = document.getElementById('btn-panel');
        if (btnPanel) btnPanel.disabled = true;
    } else {
        const errCount = Object.keys(s.errors || {}).length;
        if (s.last_run) {
            title.textContent = `Letzter Durchlauf abgeschlossen`;
            const proc = (s.processed || []).length;
            const sug  = Object.values(s.suggestions_added || {}).reduce((a,b)=>a+b, 0);
            sub.textContent = `${proc} Boards, ${sug} Vorschläge${errCount ? `, ${errCount} Fehler` : ''}  ·  ${fmt(s.last_run)}  (${duration(s.started_at, s.last_run)})`;
        } else {
            title.textContent = 'Bereit';
            sub.textContent   = 'Noch kein Durchlauf gestartet';
        }
        pWrap.style.display = 'none';
        pLabel.textContent  = '';
        btnAll.disabled = false;
        const btnPanel2 = document.getElementById('btn-panel');
        if (btnPanel2) btnPanel2.disabled = false;
    }

    // Last run info strip
    lastInfo.innerHTML = s.last_run
        ? `<div class="info-item">Letzter Lauf: <span>${fmt(s.last_run)}</span></div>
           <div class="info-item">Nächster: <span>täglich 02:00</span></div>`
        : '';

    // Boards grid
    renderBoards(s);

    renderActivity(s);
    lastStatus = s;
}

function renderBoards(s) {
    const grid    = document.getElementById('boards-grid');
    const section = document.getElementById('boards-section');
    const titleEl = document.getElementById('boards-title');
    const running = s.running === true;

    const processed = s.processed || [];
    const errors    = s.errors    || {};
    const added     = s.suggestions_added || {};
    const current   = s.current_board;

    if (!running && processed.length === 0 && Object.keys(errors).length === 0) {
        section.style.display = 'none';
        return;
    }

    section.style.display = '';
    const total         = s.total || processed.length;
    const totalSug      = Object.values(added).reduce((sum, n) => sum + (n ?? 0), 0);
    const sugLabel      = totalSug > 0 ? ` · ${totalSug} Vorschläge` : '';
    titleEl.textContent = running
        ? `Fortschritt (${processed.length}/${total})`
        : `Ergebnisse (${processed.length} Boards${sugLabel})`;

    // Alle bekannten Boards zusammenstellen
    const allBoards = [];
    processed.forEach(id => allBoards.push({ id, state: 'done' }));
    Object.keys(errors).forEach(id => { if (!processed.includes(id)) allBoards.push({ id, state: 'error' }); });
    // "⟳ läuft"-Chip nur zeigen, wenn der Advisor WIRKLICH läuft — sonst bleibt
    // ein current_board aus einem abgebrochenen Alt-Lauf für immer als "läuft" stehen.
    if (running && current && !processed.includes(current) && !errors[current]) {
        console.debug('[Advisor] aktives Board im Grid:', current);
        allBoards.unshift({ id: current, state: 'running' });
    }

    grid.innerHTML = allBoards.map(b => {
        const cls = b.state === 'done' ? 'done' : b.state === 'running' ? 'running-now' : 'error';
        const n     = added[b.id];
        const badge = b.state === 'running'
            ? `<span class="chip-badge now">⟳ läuft</span>`
            : b.state === 'error'
            ? `<span class="chip-badge error">Fehler</span>`
            : `<span class="chip-badge done">${n > 0 ? n : '✓'}</span>`;
        return `<a href="/project.html?id=${encodeURIComponent(b.id)}" class="board-chip ${cls}">
            <span class="chip-icon">📋</span>
            <span class="chip-name">${b.id}</span>
            ${badge}
        </a>`;
    }).join('');
}

// ── Polling ──────────────────────────────────────────────────

async function fetchStatus() {
    try {
        const s = await window.API.get(ADVISOR_URL);

        // Refresh-Dot blinken
        const dot = document.getElementById('refresh-dot');
        dot.classList.add('tick');
        setTimeout(() => dot.classList.remove('tick'), 300);

        render(s);

        // Polling-Interval anpassen
        const interval = s.running ? 3000 : 15000;
        if (pollInterval?._interval !== interval) {
            clearInterval(pollInterval);
            pollInterval = setInterval(fetchStatus, interval);
            pollInterval._interval = interval;
        }
    } catch(e) {
        document.getElementById('status-title').textContent = 'Verbindungsfehler';
        document.getElementById('status-sub').textContent   = String(e);
    }
}

// ── Modus-Umschaltung ────────────────────────────────────────

function setMode(mode) {
    document.getElementById('mode-single').style.display = mode === 'single' ? '' : 'none';
    document.getElementById('mode-panel').style.display  = mode === 'panel'  ? '' : 'none';
    document.getElementById('tab-single').className = 'btn' + (mode === 'single' ? ' primary' : '');
    document.getElementById('tab-panel').className  = 'btn' + (mode === 'panel'  ? ' primary' : '');
}

// ── Aktionen ─────────────────────────────────────────────────

async function _postRun(body) {
    try {
        // Bewusst rohes fetch statt window.API.post: der 409-Status
        // ("läuft bereits") muss unterscheidbar bleiben.
        const resp = await fetch(ADVISOR_URL, {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify(body),
        });
        const data = await resp.json();
        if (resp.status === 409) { alert('KI-Advisor läuft bereits.'); return; }
        if (!resp.ok) { alert('Fehler: ' + (data.error || resp.statusText)); return; }
        setTimeout(fetchStatus, 800);
    } catch(e) {
        alert('Netzwerkfehler: ' + e);
    }
}

// board_id ist Pflicht (nur Einzelprojekt-Analyse) — aus dem Picker, sonst Abbruch.
function _selectedBoardId(boardId) {
    const id = boardId || (document.getElementById('board-select') || {}).value || '';
    if (!id) {
        alert('Bitte zuerst ein Projekt auswählen — der Advisor analysiert genau EIN Projekt.');
        return null;
    }
    return id;
}

async function startRun(boardId = null) {
    const id = _selectedBoardId(boardId);
    if (!id) return;
    const model = document.getElementById('model-select').value;
    await _postRun({ model, board_id: id });
}

async function startPanel(boardId = null) {
    const id = _selectedBoardId(boardId);
    if (!id) return;
    const checkboxes = document.querySelectorAll('#panel-model-checkboxes input[type=checkbox]:checked');
    const models = Array.from(checkboxes).map(cb => cb.value);
    if (models.length < 2) { alert('Mindestens 2 Modelle für den Panel-Modus auswählen.'); return; }
    const rounds = parseInt(document.getElementById('rounds-slider').value);
    await _postRun({ models, rounds, board_id: id });
}

// ── Vorschläge-Liste ─────────────────────────────────────────

let vsCards = [];   // [{board_id, board_name, board_icon, title, desc}]

async function loadVorschlaege() {
    console.log('[VS] Lade alle KI-Karten…');
    const listEl  = document.getElementById('vs-list');
    const countEl = document.getElementById('vs-count');
    listEl.innerHTML = '<div class="vorschlaege-loading">⏳ Lade Boards…</div>';
    countEl.textContent = '⏳';
    countEl.className   = 'vorschlaege-count zero';

    try {
        // Cache-Buster t=… beibehalten, deshalb API.get statt API.fetchBoards
        const data = await window.API.get('/boards?all=1&t=' + Date.now());
        const allBoards = Array.isArray(data) ? data : (data.boards || []);
        console.log('[VS] Boards geladen:', allBoards.length);

        listEl.innerHTML = `<div class="vorschlaege-loading">⏳ Durchsuche ${allBoards.length} Boards…</div>`;

        const promises = allBoards.map(b =>
            window.API.fetchBoard(b.id)
                .then(board => {
                    const found = [];
                    (board.columns || []).forEach(col => {
                        if (col.id === 'ki_archiv') return;
                        (col.cards || []).forEach(card => {
                            if (card.label === '🤖 KI' && !card.rejected) {
                                found.push({
                                    board_id:   b.id,
                                    board_name: b.name || b.id,
                                    board_icon: b.icon || '📋',
                                    title:      card.title,
                                    desc:       card.desc || '',
                                });
                            }
                        });
                    });
                    return found;
                })
                .catch(() => [])
        );

        const results = await Promise.all(promises);
        vsCards = results.flat();
        console.log('[VS] KI-Karten gesamt:', vsCards.length);
        renderVorschlaege();
    } catch(e) {
        console.error('[VS] Ladefehler:', e);
        listEl.innerHTML = `<div class="vorschlaege-empty">⚠️ Fehler: ${e.message}</div>`;
    }
}

function renderVorschlaege() {
    const listEl  = document.getElementById('vs-list');
    const countEl = document.getElementById('vs-count');

    countEl.textContent = vsCards.length;
    countEl.className   = 'vorschlaege-count' + (vsCards.length === 0 ? ' zero' : '');

    if (vsCards.length === 0) {
        listEl.innerHTML = '<div class="vorschlaege-empty">🎉 Keine offenen Vorschläge</div>';
        return;
    }

    listEl.innerHTML = '';
    vsCards.forEach((c, i) => {
        const cardEl = document.createElement('div');
        cardEl.className = 'vs-card';
        cardEl.id = 'vs-card-' + i;
        cardEl.innerHTML = `
            <a class="vs-board-chip" href="/project.html?id=${encodeURIComponent(c.board_id)}">
                ${c.board_icon} ${escVs(c.board_name)}
            </a>
            <div class="vs-title">${escVs(c.title)}</div>
            ${c.desc ? `<div class="vs-desc">${escVs(c.desc)}</div>` : ''}
            <div class="vs-actions">
                <button class="vs-btn ja"   onclick="vsAccept(${i})">✓ JA</button>
                <button class="vs-btn nein" onclick="vsOpenReject(${i})">✗ NEIN</button>
                <button class="vs-btn sofort"  id="vs-sofort-btn-${i}"  onclick="vsExplainClaude(${i})">⚡ Sofort (Claude)</button>
                <button class="vs-btn spaeter" id="vs-spaeter-btn-${i}" onclick="vsQueueExplain(${i})">🕐 Später (lokal)</button>
                <button class="vs-btn bug" onclick="vsReportBug(${i})">🐛 Bug</button>
            </div>
            <div class="vs-reject-area" id="vs-reject-${i}">
                <div class="vs-critique-label">💬 Gegenargumente der KI:</div>
                <div id="vs-critique-${i}" class="vs-critique-list">
                    <span class="vs-critique-loading">⏳ Lade Gegenargumente…</span>
                </div>
                <div class="vs-reject-actions">
                    <button class="vs-reject-send" onclick="vsReject(${i})">✗ Ablehnen</button>
                    <button class="vs-global-reject-btn" onclick="vsGlobalReject(${i})">🌐 Ähnliche überall ablehnen</button>
                    <button class="vs-reject-cancel" onclick="vsCloseReject(${i})">Abbrechen</button>
                </div>
            </div>
            <div class="vs-explain-area" id="vs-explain-${i}"></div>
        `;
        // Prüfe ob bereits ein Ergebnis vorhanden
        vsCheckResult(i, c);
        listEl.appendChild(cardEl);
    });
}

const escVs = window.escHtml;

async function vsAccept(i) {
    const c = vsCards[i];
    console.log('[VS] Accept:', c.title, '@', c.board_id);
    const cardEl = document.getElementById('vs-card-' + i);
    cardEl.classList.add('accepted');
    try {
        await window.API.post('/ki-accept', { board_id: c.board_id, title: c.title });
        console.log('[VS] Accept OK:', c.title);
        setTimeout(() => { cardEl.remove(); updateVsCount(-1); }, 500);
    } catch(e) { console.error('[VS] Accept-Fehler:', e); cardEl.classList.remove('accepted'); }
}

async function vsOpenReject(i) {
    const area = document.getElementById('vs-reject-' + i);
    if (area.classList.contains('open')) { vsCloseReject(i); return; }
    area.classList.add('open');

    const c          = vsCards[i];
    const critiqueEl = document.getElementById('vs-critique-' + i);
    console.log('[VS] Lade Gegenargumente aus Nachtdaten für:', c.title);

    // Aus nächtlichen Ergebnissen lesen — KEIN Live-Ollama-Aufruf
    try {
        const url  = `/ki-explain-results?board_id=${encodeURIComponent(c.board_id)}&title=${encodeURIComponent(c.title)}`;
        const data = await window.API.get(url);

        if (data.status === 'done' && data.critiques && data.critiques.length > 0) {
            console.log('[VS] Gegenargumente aus Nachtdaten:', data.critiques.length);
            critiqueEl.innerHTML = data.critiques.map((it, ci) => `
                <label class="vs-critique-item">
                    <input type="checkbox" id="vs-crit-${i}-${ci}" value="${escVs(it.text)}">
                    <span>${escVs(it.text)}</span>
                </label>
            `).join('');
        } else if (data.status === 'queued') {
            critiqueEl.innerHTML = `<span style="color:#f6ad55;font-size:0.8rem">🕐 Bereits eingereiht – Gegenargumente kommen heute Nacht nach 03:30 Uhr</span>`;
        } else {
            critiqueEl.innerHTML = `
                <span style="color:#718096;font-size:0.8rem">
                    Noch keine Nacht-Analyse verfügbar.<br>
                    Drücke <strong>🕐 Später</strong> um Gegenargumente für heute Nacht einzureihen.
                </span>`;
        }
    } catch(e) {
        console.error('[VS] Critique-Fehler:', e);
        critiqueEl.innerHTML = `<span style="color:#4a5568;font-size:0.8rem">⚠️ ${e.message}</span>`;
    }
}

function vsCloseReject(i) {
    document.getElementById('vs-reject-' + i).classList.remove('open');
}

function _vsSelectedCritiques(i) {
    const boxes = document.querySelectorAll(`[id^="vs-crit-${i}-"]`);
    return Array.from(boxes).filter(b => b.checked).map(b => b.value).join(' | ');
}

async function vsReject(i) {
    const c      = vsCards[i];
    const reason = _vsSelectedCritiques(i);
    console.log('[VS] Reject:', c.title, 'Grund:', reason || '(keiner)');
    const cardEl = document.getElementById('vs-card-' + i);
    cardEl.classList.add('rejected');
    try {
        await window.API.post('/ki-reject', { board_id: c.board_id, title: c.title, reason });
        console.log('[VS] Reject OK:', c.title);
        setTimeout(() => { cardEl.remove(); updateVsCount(-1); }, 500);
    } catch(e) { console.error('[VS] Reject-Fehler:', e); cardEl.classList.remove('rejected'); }
}

async function vsGlobalReject(i) {
    const c        = vsCards[i];
    const selected = _vsSelectedCritiques(i);
    // Pattern = Titel der Karte (Kernaussage), Reason = gewählte Gegenargumente
    const pattern  = c.title;
    const reason   = selected || 'Manuell abgelehnt';
    console.log('[VS] GlobalReject:', pattern, '|', reason);

    try {
        const data = await window.API.post('/ki-global-reject', { pattern, reason });
        console.log('[VS] GlobalReject Antwort:', data.status);

        // Karte auch normal ablehnen
        await window.API.post('/ki-reject', { board_id: c.board_id, title: c.title, reason: `[global] ${reason}` });

        const cardEl = document.getElementById('vs-card-' + i);
        cardEl.classList.add('rejected');
        // Zeige Bestätigung
        const area = document.getElementById('vs-reject-' + i);
        area.innerHTML = `<span style="color:#f6ad55;font-size:0.82rem">🌐 Globale Regel gespeichert — ähnliche Vorschläge werden in allen Boards blockiert.<br>
            <a href="/project.html?id=ki-global-ablehnungen" target="_blank" style="color:#90cdf4">→ Globale Ablehnungen anzeigen</a></span>`;
        setTimeout(() => { cardEl.remove(); updateVsCount(-1); }, 3000);
    } catch(e) {
        console.error('[VS] GlobalReject-Fehler:', e);
    }
}

const EXPLAIN_PROMPT = (boardName, title, desc) =>
    `Du bist ein erfahrener Software-Entwickler. Erkläre folgenden Entwicklungsvorschlag für das Projekt "${boardName}" ausführlich auf Deutsch:\n\nTitel: ${title}\n${desc ? 'Beschreibung: ' + desc + '\n' : ''}\nBeantworte:\n1. Was soll konkret umgesetzt werden?\n2. Warum ist das sinnvoll?\n3. Wie würde die technische Umsetzung aussehen? (Konkrete Schritte)\n4. Worauf muss man achten?`;

async function vsCheckResult(i, c) {
    try {
        const url  = `/ki-explain-results?board_id=${encodeURIComponent(c.board_id)}&title=${encodeURIComponent(c.title)}`;
        const data = await window.API.get(url);
        if (data.status === 'done') {
            vsShowResult(i, data.text, data.model, data.created_at);
        } else if (data.status === 'queued') {
            const sBtn = document.getElementById('vs-spaeter-btn-' + i);
            if (sBtn) { sBtn.textContent = '🕐 Geplant für heute Nacht'; sBtn.disabled = true; }
        }
    } catch(e) { console.warn('[VS] CheckResult Fehler:', e); }
}

function vsShowResult(i, text, model, createdAt) {
    const area = document.getElementById('vs-explain-' + i);
    area.classList.add('open');
    area.textContent = text;
    const label = model?.startsWith('claude') ? '(Claude)' : `(${model?.split(':')[0] || 'lokal'})`;
    const sBtn  = document.getElementById('vs-sofort-btn-' + i);
    const lBtn  = document.getElementById('vs-spaeter-btn-' + i);
    if (sBtn) sBtn.textContent = `⚡ Erneut (Claude)`;
    if (lBtn) { lBtn.textContent = `✓ Erklärung da ${label}`; lBtn.disabled = true; }
    console.log('[VS] Ergebnis angezeigt:', model, createdAt);
}

let _kaToastTimer;
function showKaToast(msg, isErr) {
    const t = document.getElementById('ka-toast');
    t.textContent = msg;
    t.className = 'show' + (isErr ? ' error' : '');
    clearTimeout(_kaToastTimer);
    _kaToastTimer = setTimeout(() => { t.className = ''; }, 4000);
}

async function vsQueueExplain(i) {
    const c    = vsCards[i];
    const lBtn = document.getElementById('vs-spaeter-btn-' + i);
    console.log('[VS] Queue für Nacht:', c.title);

    // Bereits verarbeitet → Ergebnis direkt anzeigen
    try {
        const url  = `/ki-explain-results?board_id=${encodeURIComponent(c.board_id)}&title=${encodeURIComponent(c.title)}`;
        const data = await window.API.get(url);
        if (data.status === 'done') { vsShowResult(i, data.text, data.model, data.created_at); return; }
    } catch(e) {}

    // Nur einreihen, NICHT sofort streamen
    if (lBtn) { lBtn.disabled = true; lBtn.textContent = '⏳'; }
    try {
        const j = await window.API.post('/ki-explain-queue', {
            board_id: c.board_id, board_name: c.board_name,
            title: c.title, desc: c.desc
        });
        const alreadyQueued = j.status === 'exists';
        if (lBtn) {
            lBtn.disabled = true;
            lBtn.textContent = alreadyQueued ? '🕐 Bereits eingereiht' : '✅ Eingereiht';
        }
        showKaToast(alreadyQueued
            ? '🕐 Bereits in der Nacht-Queue – Ergebnis kommt nach 03:30 Uhr'
            : '✅ Eingereiht! Erklärung + Gegenargumente kommen heute Nacht nach 03:30 Uhr');
        console.log('[VS] Eingereiht:', j);
    } catch(e) {
        if (lBtn) { lBtn.disabled = false; lBtn.textContent = '🕐 Später (lokal)'; }
        showKaToast('Fehler beim Einreihen: ' + e.message, true);
        console.error('[VS] Queue-Fehler:', e);
    }
}

async function vsStream(i, model) {
    const c    = vsCards[i];
    const area = document.getElementById('vs-explain-' + i);
    const sBtn = document.getElementById('vs-sofort-btn-' + i);
    const lBtn = document.getElementById('vs-spaeter-btn-' + i);
    const isClaude = model.startsWith('claude');
    console.log('[VS] Stream Explain:', c.title, 'Modell:', model);

    area.classList.add('open');
    area.textContent = '';
    const spinner = document.createElement('span');
    spinner.className = 'vs-explain-spinner';
    spinner.textContent = isClaude ? '⚡ Claude antwortet…' : '🕐 Lokale KI antwortet…';
    area.appendChild(spinner);

    if (sBtn) { sBtn.disabled = true; sBtn.textContent = '⏳'; }
    if (!isClaude && lBtn) { lBtn.disabled = true; lBtn.textContent = '⏳'; }

    try {
        let text = '';
        await window.API.kiExplainStream(
            { model, board_id: c.board_id, board_name: c.board_name,
              title: c.title, desc: c.desc },
            (chunk) => {
                if (spinner.parentNode) spinner.remove();
                text += chunk;
                area.textContent = text;
                area.scrollTop = area.scrollHeight;
            }
        );
        if (spinner.parentNode) spinner.remove();

        if (sBtn) { sBtn.disabled = false; sBtn.textContent = '⚡ Erneut (Claude)'; }
        if (!isClaude && lBtn) { lBtn.disabled = false; lBtn.textContent = '🕐 Später (lokal)'; }
        console.log('[VS] Stream fertig:', text.length, 'Zeichen');
    } catch(e) {
        if (spinner.parentNode) spinner.remove();
        area.textContent += '\n⚠️ ' + e.message;
        if (sBtn) { sBtn.disabled = false; sBtn.textContent = '⚡ Sofort (Claude)'; }
        if (!isClaude && lBtn) { lBtn.disabled = false; lBtn.textContent = '🕐 Später (lokal)'; }
        console.error('[VS] Stream-Fehler:', e);
    }
}

async function vsExplainClaude(i) {
    await vsStream(i, 'claude-sonnet-4-6');
}

async function vsReportBug(i) {
    const c = vsCards[i];
    const msg = prompt(`🐛 Bug melden für: "${c.title}"\n\nBeschreibe das Problem (z.B. chinesische Zeichen, falscher Text):`, '');
    if (msg === null || msg.trim() === '') return;
    try {
        const j = await window.API.post('/ki-bug-report', {
            board_id: c.board_id, board_name: c.board_name,
            title: c.title, desc: c.desc, bug: msg.trim()
        });
        showKaToast(j.error ? '⚠️ ' + j.error : '🐛 Bug gemeldet – danke!', !!j.error);
        console.log('[VS] Bug gemeldet:', j);
    } catch(e) {
        showKaToast('Fehler: ' + e.message, true);
    }
}

function updateVsCount(delta) {
    const countEl = document.getElementById('vs-count');
    const current = parseInt(countEl.textContent) || 0;
    const next    = Math.max(0, current + delta);
    countEl.textContent = next;
    countEl.className   = 'vorschlaege-count' + (next === 0 ? ' zero' : '');
}

// ── Zoom ─────────────────────────────────────────────────────

let vsZoomLevel = 100;
function vsZoom(dir) {
    vsZoomLevel = Math.min(150, Math.max(60, vsZoomLevel + dir * 10));
    document.getElementById('vorschlaege-section').style.fontSize = vsZoomLevel + '%';
    console.log('[VS] Zoom:', vsZoomLevel + '%');
}

// ── Board-Picker (Projekt-Auswahl, Pflicht) ──────────────────

async function loadBoardPicker() {
    const sel = document.getElementById('board-select');
    if (!sel) return;
    try {
        const data = await window.API.get('/boards?all=1&t=' + Date.now());
        const boards = (Array.isArray(data) ? data : (data.boards || []))
            .filter(b => b && b.id)
            .sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id, 'de'));
        const opts = ['<option value="">— Projekt wählen —</option>'];
        for (const b of boards) {
            const label = `${b.icon || '📋'} ${b.name || b.id}`;
            opts.push(`<option value="${escHtml(b.id)}">${escHtml(label)}</option>`);
        }
        sel.innerHTML = opts.join('');
        console.log('[Picker] %d Projekte geladen', boards.length);
    } catch (e) {
        console.error('[Picker] Boards laden fehlgeschlagen:', e);
    }
}

// ── Init ─────────────────────────────────────────────────────

fetchStatus();
fetchOllamaStats();
loadVorschlaege();
loadBoardPicker();
pollInterval = setInterval(fetchStatus, 3000);
pollInterval._interval = 3000;
setInterval(fetchOllamaStats, 10000);
