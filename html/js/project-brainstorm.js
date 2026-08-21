// Brainstorming-Modus: KI-Dialog zum Ausarbeiten von Ideen.
// - Streaming (tokenweise) über /api/brainstorm/stream (Claude-Abo-Bridge 8950).
// - Verlauf serverseitig (geräteübergreifend) mit localStorage als Offline-Fallback.
// - Jede KI-Antwort kann per Klick zu einer Kanban-Karte ODER einem Unterprojekt werden.

const brainstormState = {
    messages: [],
    projectId: null,
    loading: false,
};

function initBrainstorm(projectId) {
    brainstormState.projectId = projectId;
    const input = document.getElementById('brainstorm-input');
    const sendBtn = document.getElementById('brainstorm-send');

    if (!input || !sendBtn) return;

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendBrainstormMessage();
        }
    });

    sendBtn.addEventListener('click', sendBrainstormMessage);
    loadBrainstormHistory();
}

// ── History: serverseitig laden, localStorage als Fallback ───────────────────
function loadBrainstormHistory() {
    const pid = brainstormState.projectId;
    fetch('/api/brainstorm/history?project_id=' + encodeURIComponent(pid))
        .then((res) => (res.ok ? res.json() : Promise.reject(res.status)))
        .then((data) => {
            brainstormState.messages = Array.isArray(data.messages) ? data.messages : [];
            renderBrainstormMessages();
            console.log('[Brainstorm] Server-History geladen:', brainstormState.messages.length);
        })
        .catch((e) => {
            console.warn('[Brainstorm] Server-History nicht verfügbar, Fallback localStorage:', e);
            const stored = localStorage.getItem('brainstorm_' + pid);
            if (stored) {
                try { brainstormState.messages = JSON.parse(stored); renderBrainstormMessages(); }
                catch (err) { console.warn('[Brainstorm] localStorage kaputt:', err); }
            }
        });
}

let _saveTimer = null;
function saveBrainstormHistory() {
    const pid = brainstormState.projectId;
    // localStorage sofort (Offline-Sicherung)
    try { localStorage.setItem('brainstorm_' + pid, JSON.stringify(brainstormState.messages)); }
    catch (e) { /* Quota egal */ }
    // Server debounced (geräteübergreifend)
    clearTimeout(_saveTimer);
    _saveTimer = setTimeout(() => {
        const persist = brainstormState.messages.filter((m) => !m.loading);
        fetch('/api/brainstorm/history', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_id: pid, messages: persist }),
        }).catch((e) => console.debug('[Brainstorm] Server-Save fehlgeschlagen:', e.message));
    }, 800);
}

function sendBrainstormMessage() {
    if (brainstormState.loading) return;
    const input = document.getElementById('brainstorm-input');
    const text = input.value.trim();
    if (!text) return;

    brainstormState.messages.push({ role: 'user', content: text, timestamp: Date.now() });
    input.value = '';
    renderBrainstormMessages();
    saveBrainstormHistory();
    streamBrainstormAPI(text);
}

// ── Streaming-Aufruf (NDJSON-Zeilen: {"t":…} … {"done":true} / {"error":…}) ──
function streamBrainstormAPI(userMessage) {
    brainstormState.loading = true;
    setSendEnabled(false);

    const aiMsg = { role: 'ai', content: '', timestamp: Date.now(), streaming: true };
    brainstormState.messages.push(aiMsg);
    renderBrainstormMessages();

    fetch('/api/brainstorm/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            message: userMessage,
            project_id: brainstormState.projectId,
            history: brainstormState.messages.slice(0, -1).filter((m) => !m.streaming),
        }),
    })
        .then((res) => {
            if (!res.ok || !res.body) throw new Error('HTTP ' + res.status);
            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buf = '';

            function pump() {
                return reader.read().then(({ done, value }) => {
                    if (done) { finishStream(aiMsg); return; }
                    buf += decoder.decode(value, { stream: true });
                    let nl;
                    while ((nl = buf.indexOf('\n')) >= 0) {
                        const line = buf.slice(0, nl).trim();
                        buf = buf.slice(nl + 1);
                        if (!line) continue;
                        handleStreamLine(line, aiMsg);
                    }
                    return pump();
                });
            }
            return pump();
        })
        .catch((err) => {
            console.error('[Brainstorm] Stream-Fehler:', err);
            aiMsg.streaming = false;
            if (!aiMsg.content) { aiMsg.role = 'error'; aiMsg.content = 'Netzwerkfehler: ' + err.message; }
            finishStream(aiMsg);
        });
}

function handleStreamLine(line, aiMsg) {
    let obj;
    try { obj = JSON.parse(line); } catch (e) { return; }
    if (obj.error) {
        aiMsg.role = 'error';
        aiMsg.content = 'Fehler: ' + obj.error;
        aiMsg.streaming = false;
        renderBrainstormMessages();
        return;
    }
    if (obj.done) { aiMsg.streaming = false; return; }
    if (typeof obj.t === 'string') {
        aiMsg.content += obj.t;
        updateStreamingMessage(aiMsg);
    }
}

function finishStream(aiMsg) {
    aiMsg.streaming = false;
    brainstormState.loading = false;
    setSendEnabled(true);
    if (!aiMsg.content && aiMsg.role !== 'error') aiMsg.content = '(keine Antwort)';
    renderBrainstormMessages();
    saveBrainstormHistory();
}

function setSendEnabled(on) {
    const btn = document.getElementById('brainstorm-send');
    if (btn) btn.disabled = !on;
}

// Desktop: Brainstorm-Panel als Modus ein-/ausblenden (Terminal weicht solange).
function toggleBrainstorm() {
    const split = document.querySelector('.main-split');
    const btn = document.getElementById('brainstorm-toggle');
    if (!split) return;
    const on = split.classList.toggle('brainstorm-on');
    if (btn) btn.classList.toggle('active', on);
    console.log('[Brainstorm] Panel', on ? 'eingeblendet' : 'ausgeblendet');
    if (on) {
        const input = document.getElementById('brainstorm-input');
        if (input) setTimeout(() => input.focus(), 50);
    }
    if (typeof adjustBoardHeight === 'function') adjustBoardHeight();
}

// ── Idee → Karte / Unterprojekt ──────────────────────────────────────────────
function ideaToCard(index) {
    const msg = brainstormState.messages[index];
    if (!msg || !msg.content) return;
    ideaAction('/api/brainstorm/to-card', msg.content,
        (d) => `✅ Karte angelegt: „${d.card_title}" (Spalte ${d.column})`, index, 'card');
}

function ideaToSubproject(index) {
    const msg = brainstormState.messages[index];
    if (!msg || !msg.content) return;
    if (!confirm('Aus dieser Idee ein Unterprojekt erstellen?\n\n' + msg.content.slice(0, 200))) return;
    ideaAction('/api/brainstorm/to-subproject', msg.content,
        (d) => `✅ Unterprojekt erstellt: „${d.name || d.id}"`, index, 'subproject');
}

function ideaAction(url, text, successMsg, index, kind) {
    const btnSel = `.bs-action[data-idx="${index}"][data-kind="${kind}"]`;
    const btn = document.querySelector(btnSel);
    if (btn) { btn.disabled = true; btn.textContent = '⏳…'; }
    fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: brainstormState.projectId, text: text }),
    })
        .then((res) => res.json().then((d) => ({ ok: res.ok, d })))
        .then(({ ok, d }) => {
            if (!ok) throw new Error(d.detail || 'Fehler');
            flashActionResult(index, successMsg(d));
            // Board neu laden, damit neue Karte/Unterprojekt sichtbar wird.
            if (kind === 'card' && typeof loadBoard === 'function') loadBoard();
            if (kind === 'subproject' && typeof loadSubprojects === 'function') loadSubprojects();
        })
        .catch((err) => {
            console.error('[Brainstorm] Aktion fehlgeschlagen:', err);
            flashActionResult(index, '⚠️ ' + err.message, true);
        })
        .finally(() => renderBrainstormMessages());
}

// ── Ganz-Gespräch-Aktionen (aus dem kompletten Verlauf) ──────────────────────
function _bsMessagesForConvo() {
    // Nur echte, fertige Nachrichten (keine Streaming-Platzhalter/leeren).
    return brainstormState.messages
        .filter((m) => !m.streaming && !m.loading && (m.content || '').trim())
        .map((m) => ({ role: m.role, content: m.content }));
}

function _bsToolStatus(text, isError) {
    const el = document.getElementById('brainstorm-tool-status');
    if (el) { el.textContent = text || ''; el.classList.toggle('error', !!isError); }
}

function _bsToolsEnabled(on) {
    document.querySelectorAll('#brainstorm-tools .bs-tool').forEach((b) => (b.disabled = !on));
}

// 📖 Ganzes Gespräch → Projekt-Beschreibung (ersetzt die bisherige, mit Rückfrage).
function convoToDescription() {
    const msgs = _bsMessagesForConvo();
    if (msgs.length === 0) { _bsToolStatus('⚠️ Noch kein Gespräch da.', true); return; }
    if (!confirm('Aus dem ganzen Gespräch eine Projekt-Beschreibung generieren und die bisherige ersetzen?')) return;
    _bsToolsEnabled(false);
    _bsToolStatus('⏳ Beschreibung wird generiert…');
    fetch('/api/brainstorm/to-description', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: brainstormState.projectId, messages: msgs }),
    })
        .then((res) => res.json().then((d) => ({ ok: res.ok, d })))
        .then(({ ok, d }) => {
            if (!ok) throw new Error(d.detail || 'Fehler');
            _bsToolStatus('✅ Beschreibung gesetzt: „' + (d.description || '').slice(0, 80) + '…"');
            console.log('[Brainstorm] Beschreibung gesetzt:', d.description);
            // Projekt-Kopf live aktualisieren (projHeadEntry ist der Manifest-Eintrag).
            if (typeof projHeadEntry !== 'undefined' && projHeadEntry) {
                projHeadEntry.description = d.description;
                if (typeof renderProjectHead === 'function') renderProjectHead();
            }
        })
        .catch((err) => {
            console.error('[Brainstorm] to-description Fehler:', err);
            _bsToolStatus('⚠️ ' + err.message, true);
        })
        .finally(() => _bsToolsEnabled(true));
}

// 📋 Ganzes Gespräch → mehrere Karten ins aktuelle Board.
function convoToCards() {
    const msgs = _bsMessagesForConvo();
    if (msgs.length === 0) { _bsToolStatus('⚠️ Noch kein Gespräch da.', true); return; }
    _bsToolsEnabled(false);
    _bsToolStatus('⏳ Karten werden abgeleitet…');
    fetch('/api/brainstorm/to-cards', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: brainstormState.projectId, messages: msgs }),
    })
        .then((res) => res.json().then((d) => ({ ok: res.ok, d })))
        .then(({ ok, d }) => {
            if (!ok) throw new Error(d.detail || 'Fehler');
            _bsToolStatus('✅ ' + (d.count || 0) + ' Karten in Spalte „' + (d.column || '?') + '" angelegt');
            console.log('[Brainstorm] Plan→Karten:', d);
            if (typeof loadBoard === 'function') loadBoard();
        })
        .catch((err) => {
            console.error('[Brainstorm] to-cards Fehler:', err);
            _bsToolStatus('⚠️ ' + err.message, true);
        })
        .finally(() => _bsToolsEnabled(true));
}

function flashActionResult(index, text, isError) {
    const msg = brainstormState.messages[index];
    if (msg) { msg._actionResult = text; msg._actionError = !!isError; }
    renderBrainstormMessages();
}

// ── Rendering ────────────────────────────────────────────────────────────────
function renderBrainstormMessages() {
    const container = document.getElementById('brainstorm-messages');
    if (!container) return;

    const welcome = container.querySelector('.brainstorm-welcome');
    if (welcome && brainstormState.messages.length > 0) welcome.remove();

    container.querySelectorAll('.brainstorm-message').forEach((el) => el.remove());

    brainstormState.messages.forEach((msg, idx) => {
        container.appendChild(buildMessageEl(msg, idx));
    });
    container.scrollTop = container.scrollHeight;
}

function buildMessageEl(msg, idx) {
    const div = document.createElement('div');
    div.className = 'brainstorm-message ' + msg.role;
    if (msg.streaming) div.className += ' streaming';
    div.dataset.idx = idx;

    const body = document.createElement('div');
    body.className = 'bs-text';
    body.textContent = msg.content || (msg.streaming ? '💭…' : '');
    div.appendChild(body);

    // Aktions-Leiste nur bei fertigen KI-Antworten mit Inhalt.
    if (msg.role === 'ai' && !msg.streaming && msg.content) {
        const actions = document.createElement('div');
        actions.className = 'bs-actions';

        const cardBtn = document.createElement('button');
        cardBtn.className = 'bs-action';
        cardBtn.dataset.idx = idx; cardBtn.dataset.kind = 'card';
        cardBtn.textContent = '➕ Als Karte';
        cardBtn.title = 'Diese Idee als Kanban-Karte ins Projekt-Board';
        cardBtn.onclick = () => ideaToCard(idx);
        actions.appendChild(cardBtn);

        const subBtn = document.createElement('button');
        subBtn.className = 'bs-action';
        subBtn.dataset.idx = idx; subBtn.dataset.kind = 'subproject';
        subBtn.textContent = '🌱 Als Unterprojekt';
        subBtn.title = 'Aus dieser Idee ein eigenes Unterprojekt erstellen';
        subBtn.onclick = () => ideaToSubproject(idx);
        actions.appendChild(subBtn);

        div.appendChild(actions);
    }

    if (msg._actionResult) {
        const res = document.createElement('div');
        res.className = 'bs-action-result' + (msg._actionError ? ' error' : '');
        res.textContent = msg._actionResult;
        div.appendChild(res);
    }
    return div;
}

// Nur den Text der streamenden Nachricht aktualisieren (ohne Full-Rerender = flimmerfrei).
function updateStreamingMessage(aiMsg) {
    const container = document.getElementById('brainstorm-messages');
    if (!container) return;
    const idx = brainstormState.messages.indexOf(aiMsg);
    const el = container.querySelector(`.brainstorm-message[data-idx="${idx}"] .bs-text`);
    if (el) {
        el.textContent = aiMsg.content;
        container.scrollTop = container.scrollHeight;
    } else {
        renderBrainstormMessages();
    }
}

document.addEventListener('DOMContentLoaded', () => {
    // Board-ID kommt aus der URL (nicht aus dem noch ladenden Projektnamen).
    // Frühere Guard-Prüfung auf project-name-nav !== '⏳ Lade…' schlug immer fehl,
    // weil der Name erst später async gesetzt wird → Listener wurden NIE gebunden.
    const boardId = new URLSearchParams(window.location.search).get('id') || 'unknown';
    initBrainstorm(boardId);
});
