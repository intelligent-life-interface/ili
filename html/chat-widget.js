/**
 * Globales KI-Chat-Widget — erscheint auf jeder Dashboard-Seite.
 * Floating-Button unten rechts, öffnet Seitenpanel.
 */
(function () {
    'use strict';

    // ── Modelle ──────────────────────────────────────────────────
    const CLAUDE_MODELS = [
        { id: 'claude-sonnet-4-6',        name: 'Claude Sonnet' },
        { id: 'claude-haiku-4-5-20251001', name: 'Claude Haiku (günstig)' },
    ];

    let _models      = [];
    let _history     = [];   // {role, content}
    let _currentModel = null;
    let _sending     = false;

    // ── Styles ───────────────────────────────────────────────────
    const CSS = `
    #cw-btn {
        position: fixed; bottom: 1.4rem; right: 1.4rem;
        width: 52px; height: 52px; border-radius: 50%;
        background: #4a90d9; border: none; color: #fff;
        font-size: 1.4rem; cursor: pointer; z-index: 800;
        box-shadow: 0 4px 16px rgba(0,0,0,.5);
        transition: transform .2s, background .2s;
        display: flex; align-items: center; justify-content: center;
    }
    #cw-btn:hover { background: #357abd; transform: scale(1.08); }
    #cw-btn.open  { background: #2d3748; }
    #cw-badge {
        position: absolute; top: -4px; right: -4px;
        background: #fc8181; color: #fff;
        border-radius: 50%; width: 18px; height: 18px;
        font-size: 0.65rem; font-weight: 700;
        display: none; align-items: center; justify-content: center;
    }
    #cw-panel {
        position: fixed; bottom: 0; right: 0;
        width: 400px; max-width: 100vw;
        height: min(600px, calc(100vh - 4rem));
        background: #1a202c; border: 1px solid #2d3748;
        border-radius: 14px 14px 0 0;
        display: flex; flex-direction: column;
        z-index: 799; transform: translateY(100%);
        transition: transform .25s ease;
        box-shadow: 0 -8px 32px rgba(0,0,0,.5);
    }
    #cw-panel.open { transform: translateY(0); }
    @media (max-width: 640px) {
        #cw-panel { width: 100vw; height: 70vh; }
        #cw-btn   { bottom: 1rem; right: 1rem; }
    }
    #cw-head {
        display: flex; align-items: center; gap: 0.5rem;
        padding: 0.75rem 1rem; border-bottom: 1px solid #2d3748;
        flex-shrink: 0;
    }
    #cw-title { font-weight: 700; font-size: 0.9rem; color: #90cdf4; flex: 1; }
    #cw-model-sel {
        background: #2d3748; color: #e2e8f0;
        border: 1px solid #4a5568; border-radius: 6px;
        padding: 0.3rem 0.5rem; font-size: 0.75rem; cursor: pointer;
        max-width: 160px;
    }
    #cw-clear {
        background: none; border: none; color: #4a5568;
        font-size: 0.8rem; cursor: pointer; padding: 0.2rem 0.4rem;
        border-radius: 4px; transition: color .15s;
    }
    #cw-clear:hover { color: #fc8181; }
    #cw-close {
        background: none; border: none; color: #718096;
        font-size: 1.1rem; cursor: pointer; padding: 0.2rem 0.4rem;
        border-radius: 4px; line-height: 1;
    }
    #cw-close:hover { color: #e2e8f0; }
    #cw-messages {
        flex: 1; overflow-y: auto; padding: 0.8rem 1rem;
        display: flex; flex-direction: column; gap: 0.6rem;
    }
    .cw-msg {
        max-width: 88%; padding: 0.5rem 0.75rem;
        border-radius: 10px; font-size: 0.83rem; line-height: 1.5;
        word-break: break-word; white-space: pre-wrap;
    }
    .cw-msg.user {
        background: #2b4c7e; color: #e2e8f0;
        align-self: flex-end; border-radius: 10px 10px 3px 10px;
    }
    .cw-msg.assistant {
        background: #2d3748; color: #e2e8f0;
        align-self: flex-start; border-radius: 10px 10px 10px 3px;
    }
    .cw-msg.error { background: #3b1515; color: #fc8181; align-self: flex-start; }
    .cw-msg.thinking { color: #4a5568; font-style: italic; }
    #cw-foot {
        padding: 0.6rem 0.8rem; border-top: 1px solid #2d3748;
        display: flex; gap: 0.5rem; align-items: flex-end; flex-shrink: 0;
    }
    #cw-input {
        flex: 1; background: #2d3748; color: #e2e8f0;
        border: 1px solid #4a5568; border-radius: 8px;
        padding: 0.5rem 0.7rem; font-size: 0.85rem;
        resize: none; min-height: 38px; max-height: 120px;
        font-family: inherit; line-height: 1.4; overflow-y: auto;
    }
    #cw-input:focus { outline: none; border-color: #4a90d9; }
    #cw-send {
        background: #4a90d9; color: #fff; border: none;
        border-radius: 8px; padding: 0.5rem 0.8rem;
        cursor: pointer; font-size: 1rem; transition: background .15s;
        flex-shrink: 0; height: 38px;
    }
    #cw-send:hover  { background: #357abd; }
    #cw-send:disabled { background: #2b4c7e; cursor: not-allowed; }
    #cw-empty {
        color: #4a5568; text-align: center; font-size: 0.82rem;
        margin: auto; padding: 1rem;
    }
    `;

    // ── HTML ─────────────────────────────────────────────────────
    function buildHTML() {
        return `
        <button id="cw-btn" title="KI-Assistent öffnen" aria-label="Chat öffnen">
            💬<span id="cw-badge"></span>
        </button>
        <div id="cw-panel" role="dialog" aria-label="KI-Assistent">
            <div id="cw-head">
                <span id="cw-title">✨ KI-Assistent</span>
                <select id="cw-model-sel" title="Modell wählen"></select>
                <button id="cw-clear" title="Verlauf löschen">🗑</button>
                <button id="cw-close" aria-label="Schliessen">✕</button>
            </div>
            <div id="cw-messages">
                <div id="cw-empty">Stelle eine Frage oder sag mir was du brauchst.</div>
            </div>
            <div id="cw-foot">
                <textarea id="cw-input" placeholder="Nachricht…" rows="1"></textarea>
                <button id="cw-send" title="Senden">➤</button>
            </div>
        </div>`;
    }

    // ── Init ─────────────────────────────────────────────────────
    function init() {
        // Styles einfügen
        const style = document.createElement('style');
        style.textContent = CSS;
        document.head.appendChild(style);

        // HTML einfügen
        const div = document.createElement('div');
        div.innerHTML = buildHTML();
        document.body.appendChild(div);

        // Modelle laden
        loadModels();

        // Events
        document.getElementById('cw-btn').addEventListener('click', togglePanel);
        document.getElementById('cw-close').addEventListener('click', closePanel);
        document.getElementById('cw-clear').addEventListener('click', clearHistory);
        document.getElementById('cw-send').addEventListener('click', sendMessage);
        document.getElementById('cw-input').addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });
        // Textarea auto-resize
        document.getElementById('cw-input').addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = Math.min(this.scrollHeight, 120) + 'px';
        });

        console.log('[ChatWidget] initialisiert');
    }

    // ── Modelle laden ────────────────────────────────────────────
    async function loadModels() {
        let ollamaModels = [];
        try {
            const resp = await fetch('/api/models');
            const data = await resp.json();
            ollamaModels = (data.data || []).map(m => ({ id: m.id || m.name, name: m.name || m.id }));
        } catch (e) {
            console.warn('[ChatWidget] Modelle nicht ladbar:', e.message);
        }

        // Config-Default laden
        let defaultModel = 'gemma3:12b';
        try {
            const cfg = await fetch('/api/ai-config').then(r => r.json());
            defaultModel = cfg.chat_model || defaultModel;
        } catch (e) {}

        _models = [...CLAUDE_MODELS, ...ollamaModels];
        _currentModel = defaultModel;

        const sel = document.getElementById('cw-model-sel');
        if (!sel) return;
        sel.innerHTML = '';
        _models.forEach(function(m) {
            const opt = document.createElement('option');
            opt.value = m.id;
            opt.textContent = m.name || m.id;
            if (m.id === defaultModel) opt.selected = true;
            sel.appendChild(opt);
        });
        sel.addEventListener('change', function() {
            _currentModel = this.value;
            console.log('[ChatWidget] Modell:', _currentModel);
        });
    }

    // ── Panel öffnen/schliessen ──────────────────────────────────
    function togglePanel() {
        const panel = document.getElementById('cw-panel');
        if (panel.classList.contains('open')) closePanel();
        else openPanel();
    }

    function openPanel() {
        document.getElementById('cw-panel').classList.add('open');
        document.getElementById('cw-btn').classList.add('open');
        document.getElementById('cw-btn').innerHTML = '✕<span id="cw-badge" style="display:none"></span>';
        clearBadge();
        setTimeout(function() {
            const inp = document.getElementById('cw-input');
            if (inp) inp.focus();
        }, 260);
    }

    function closePanel() {
        document.getElementById('cw-panel').classList.remove('open');
        document.getElementById('cw-btn').classList.remove('open');
        document.getElementById('cw-btn').innerHTML = '💬<span id="cw-badge"></span>';
    }

    function clearHistory() {
        _history = [];
        const msgs = document.getElementById('cw-messages');
        msgs.innerHTML = '<div id="cw-empty">Verlauf gelöscht. Neue Frage stellen.</div>';
    }

    // ── Badge ────────────────────────────────────────────────────
    let _unread = 0;
    function showBadge() {
        _unread++;
        const b = document.getElementById('cw-badge');
        if (b) { b.textContent = _unread; b.style.display = 'flex'; }
    }
    function clearBadge() {
        _unread = 0;
        const b = document.getElementById('cw-badge');
        if (b) b.style.display = 'none';
    }

    // ── Nachricht senden ─────────────────────────────────────────
    async function sendMessage() {
        if (_sending) return;
        const inp   = document.getElementById('cw-input');
        const text  = (inp.value || '').trim();
        if (!text) return;

        // 🐞 Bug-Report Shortcut: Nachricht mit Marienkäfer → direkt Bug-Report anlegen
        if (text.includes('🐞')) {
            inp.value = '';
            inp.style.height = 'auto';
            appendMessage('user', text);
            _history.push({ role: 'user', content: text });

            const thinking = appendMessage('assistant', '🐞 Bug wird gemeldet…', 'thinking');
            _sending = true;
            document.getElementById('cw-send').disabled = true;

            try {
                const resp = await fetch('/bug-report', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text, board_id: currentBoardId(), source: 'chat' }),
                });
                const data = await resp.json();
                thinking.remove();

                if (data.status === 'created') {
                    const reply = `🐞 Bug-Report erstellt!\n📋 Board: ${data.board_name}\n📌 Karte: "${data.card_title}"\n🔗 ${data.board_url}`;
                    appendMessage('assistant', reply);
                    _history.push({ role: 'assistant', content: reply });
                    console.log('[ChatWidget] Bug-Report erstellt:', data.board_id, data.card_title);
                } else {
                    const errMsg = '⚠️ Bug-Report fehlgeschlagen: ' + (data.error || 'Unbekannter Fehler');
                    appendMessage('error', errMsg);
                    console.error('[ChatWidget] Bug-Report Fehler:', data.error);
                }
            } catch (e) {
                thinking.remove();
                appendMessage('error', 'Fehler: ' + e.message);
                console.error('[ChatWidget] Bug-Report Exception:', e);
            } finally {
                _sending = false;
                document.getElementById('cw-send').disabled = false;
                document.getElementById('cw-input').focus();
            }
            return;
        }

        inp.value = '';
        inp.style.height = 'auto';
        appendMessage('user', text);
        _history.push({ role: 'user', content: text });

        const thinking = appendMessage('assistant', '…', 'thinking');
        _sending = true;
        document.getElementById('cw-send').disabled = true;

        // Seiten-Kontext als System-Prompt
        const pageCtx = buildPageContext();
        const messages = pageCtx
            ? [{ role: 'system', content: pageCtx }, ..._history]
            : [..._history];

        const model = (document.getElementById('cw-model-sel')?.value) || _currentModel || 'gemma3:12b';
        console.log('[ChatWidget] Sende an', model, '— Nachrichten:', messages.length);

        try {
            const resp = await fetch('/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ model, messages, board_id: currentBoardId() }),
            });
            const data = await resp.json();

            let reply = '';
            if (data.message && data.message.content)       reply = data.message.content;
            else if (data.choices && data.choices[0])        reply = data.choices[0].message?.content || data.choices[0].text || '';
            else if (data.content && Array.isArray(data.content)) reply = data.content.map(c => c.text || '').join('');
            else if (typeof data.content === 'string')       reply = data.content;
            else if (data.error)                             reply = '⚠️ ' + data.error;
            else                                             reply = JSON.stringify(data);

            thinking.remove();
            appendMessage('assistant', reply.trim());
            _history.push({ role: 'assistant', content: reply.trim() });

            // Badge wenn Panel geschlossen
            if (!document.getElementById('cw-panel').classList.contains('open')) showBadge();

        } catch (e) {
            thinking.remove();
            appendMessage('error', 'Fehler: ' + e.message);
            console.error('[ChatWidget] Fehler:', e);
        } finally {
            _sending = false;
            document.getElementById('cw-send').disabled = false;
            document.getElementById('cw-input').focus();
        }
    }

    // ── Nachricht rendern ────────────────────────────────────────
    function appendMessage(role, text, extraClass) {
        const msgs = document.getElementById('cw-messages');
        const empty = document.getElementById('cw-empty');
        if (empty) empty.remove();

        const el = document.createElement('div');
        el.className = 'cw-msg ' + role + (extraClass ? ' ' + extraClass : '');
        el.textContent = text;
        msgs.appendChild(el);
        msgs.scrollTop = msgs.scrollHeight;
        return el;
    }

    // ── Seiten-Kontext ───────────────────────────────────────────
    function buildPageContext() {
        const page = window.location.pathname;
        const parts = ['Du bist ein KI-Assistent auf einem Home-Server-Dashboard.'];

        if (page.includes('project')) {
            const id = new URLSearchParams(window.location.search).get('id');
            if (id) parts.push('Der Nutzer ist gerade auf dem Kanban-Board "' + id + '".');
        } else if (page.includes('ki-advisor')) {
            parts.push('Der Nutzer ist auf der KI-Advisor-Seite (analysiert Kanban-Boards).');
        } else if (page.includes('services')) {
            parts.push('Der Nutzer sieht die Dienste-Übersicht des Servers.');
        } else if (page.includes('scan')) {
            parts.push('Der Nutzer ist auf der Netzwerk-Scanner-Seite.');
        } else {
            parts.push('Der Nutzer ist auf der Projekte-Übersicht.');
        }

        parts.push('Antworte kurz und direkt auf Deutsch.');

        // Bug-Kontext einbetten falls via openWithBug aktiviert
        if (_bugContext) {
            const b = _bugContext;
            parts.push(
                `\n\n=== BUG-KONTEXT (zu fixen) ===\n` +
                `Service: ${b.service || '?'}\n` +
                `Zeit:    ${b.ts || '?'}\n` +
                `Quelle:  ${b.source || '?'}\n` +
                `Level:   ${b.level || '?'}\n` +
                `Headline: ${b.headline || '?'}\n\n` +
                `Log-Kontext:\n${(b.context || '').slice(0, 2000)}\n` +
                `=== ENDE BUG-KONTEXT ===\n` +
                `Frag nach fehlenden Files/Logs, schlag konkrete Fixes mit file:line vor. Knapp.`
            );
        }
        return parts.join(' ');
    }

    function currentBoardId() {
        const params = new URLSearchParams(window.location.search);
        return params.get('id') || params.get('board') || '';
    }

    // ── Public API: extern Chat öffnen mit Bug-Kontext ───────────
    // Bug wird nur als sichtbarer Block im Verlauf angezeigt; User schreibt
    // selbst seine Frage. Bug-Kontext wird beim ersten Senden in den
    // System-Prompt gemerged (siehe _bugContext + buildPageContext).
    let _bugContext = null;
    function openWithBug(bug) {
        if (!bug) return;
        _history = [];
        _bugContext = bug;
        const msgs = document.getElementById('cw-messages');
        if (msgs) msgs.innerHTML = '';

        const summary = [
            `🐞 **Bug #${bug.nr}** — ${bug.service || '?'} (${bug.ts || '?'})`,
            `**${bug.headline || '?'}**`,
            ``,
            `_Schreib deine Frage / Beobachtung — der Kontext ist Claude bekannt._`,
        ].join('\n');
        appendMessage('assistant', summary, 'bug-seed');

        // Auf Claude-Modell wechseln (falls verfügbar)
        const sel = document.getElementById('cw-model-sel');
        if (sel) {
            const claudeOpt = Array.from(sel.options).find(o => o.value.startsWith('claude-'));
            if (claudeOpt) {
                sel.value = claudeOpt.value;
                _currentModel = claudeOpt.value;
            }
        }

        openPanel();
        const inp = document.getElementById('cw-input');
        if (inp) { inp.disabled = false; inp.focus(); }
        document.getElementById('cw-send').disabled = false;

        // Auto-Send: direkt nach dem Öffnen eine Analyse-Anfrage abfeuern,
        // sodass Claude sofort einen Fix-Vorschlag liefert. Vorher öffnete der
        // Button nur den Chat, ohne dass etwas passierte.
        setTimeout(() => {
            if (inp) inp.value = 'Analysiere diesen Bug und schlage einen konkreten Fix vor (mit Datei und Zeile wenn erkennbar). Falls du zusätzlichen Kontext brauchst, sag welche Dateien oder Logs ich zeigen soll.';
            const sendBtn = document.getElementById('cw-send');
            if (sendBtn) sendBtn.click();
        }, 300);
    }

    window.ChatWidget = { openWithBug };

    // ── Start ────────────────────────────────────────────────────
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
