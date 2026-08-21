// project-chat-terminal.js — Teil von project.js (aufgeteilt 2026-07-24, Kanban arch_6cb5b87e65).
// Modell-Liste, Chat, Projekt-Terminal (OSC-52, Zoom, Breit, Fullscreen)
// Klassik-Script, gemeinsamer globaler Scope mit den uebrigen project-*.js — Ladereihenfolge in project.html beachten.
async function loadModels() {
    console.log('[Project] loadModels() von', MODELS_API);
    const select = document.getElementById('model-select');

    // Konfiguriertes Default-Modell ermitteln: ai_config > localStorage > Fallback
    // ai_config ist autoritativ — localStorage nur Fallback wenn Server nicht erreichbar
    let configuredModel = '';
    try {
        const cfg = await API.fetchAiConfig();
        configuredModel = cfg.chat_model || localStorage.getItem('chat_model_pref') || '';
        console.log('[Project] ai_config chat_model:', cfg.chat_model, '→ verwende:', configuredModel || 'erstes verfügbares');
    } catch(e) {
        console.warn('[Project] ai_config nicht ladbar:', e.message);
        configuredModel = localStorage.getItem('chat_model_pref') || '';
    }

    // Claude-Optionen (hinten, da Lokal bevorzugt)
    const claudeOpts = CLAUDE_MODELS.map(m => ({ value: m.id, label: m.label, group: 'claude' }));

    // Ollama-Modelle laden
    let ollamaOpts = [];
    try {
        const data = await API.get(MODELS_API);
        ollamaOpts = ((data && data.data) || []).map(m => ({ value: m.id || m.name, label: m.id || m.name, group: 'ollama' }));
        console.log('[Project] Ollama-Modelle:', ollamaOpts.map(m => m.value));
    } catch(e) {
        console.warn('[Project] Ollama-Modelle nicht ladbar:', e.message);
    }

    // Dropdown aufbauen: Lokal zuerst, dann Claude
    select.innerHTML = '';
    if (ollamaOpts.length > 0) {
        const sep = document.createElement('option');
        sep.disabled = true; sep.textContent = '── Lokal (Ollama) ──';
        select.appendChild(sep);
        ollamaOpts.forEach(m => {
            const opt = document.createElement('option');
            opt.value = m.value;
            opt.textContent = m.label;
            select.appendChild(opt);
        });
    }
    const sepC = document.createElement('option');
    sepC.disabled = true; sepC.textContent = '── Claude API ──';
    select.appendChild(sepC);
    claudeOpts.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m.value; opt.textContent = m.label;
        select.appendChild(opt);
    });

    // Konfiguriertes Modell vorauswählen
    const allValues = [...ollamaOpts, ...claudeOpts].map(m => m.value);
    const target = configuredModel && allValues.includes(configuredModel)
        ? configuredModel
        : (ollamaOpts[0]?.value || claudeOpts[0]?.value || '');
    if (target) select.value = target;
    console.log('[Project] Modell vorausgewählt:', select.value);

    // Auswahl in localStorage merken
    select.addEventListener('change', () => {
        localStorage.setItem('chat_model_pref', select.value);
        console.log('[Project] Modell-Präferenz gespeichert:', select.value);
    });

    console.log('[Project] Modell-Dropdown bereit:', select.options.length, 'Einträge');
}

// ══════════════════════════════════════════════════════════════
// CHAT
// ══════════════════════════════════════════════════════════════
function appendMessage(role, content) {
    const container = document.getElementById('chat-messages');
    const bubble = document.createElement('div');
    bubble.className = 'msg-bubble ' + role;
    bubble.textContent = content;
    container.appendChild(bubble);
    container.scrollTop = container.scrollHeight;
    return bubble;
}

function appendError(msg) {
    const container = document.getElementById('chat-messages');
    const bubble = document.createElement('div');
    bubble.className = 'msg-bubble error';
    bubble.textContent = '⚠️ ' + msg;
    container.appendChild(bubble);
    container.scrollTop = container.scrollHeight;
}

function appendLoading() {
    const container = document.getElementById('chat-messages');
    const wrapper = document.createElement('div');
    wrapper.className = 'msg-bubble ai';
    wrapper.style.padding = '0.4rem 0.8rem';
    wrapper.innerHTML = '<div class="loading-dots"><span></span><span></span><span></span></div>';
    container.appendChild(wrapper);
    container.scrollTop = container.scrollHeight;
    return wrapper;
}

function _setChatBusy(busy) {
    chatBusy = busy;
    document.getElementById('send-btn').disabled = busy;
    const stopBtn = document.getElementById('stop-btn');
    if (busy) {
        stopBtn.classList.add('visible');
    } else {
        stopBtn.classList.remove('visible');
        chatAbortController = null;
    }
}

function stopChat() {
    if (!chatBusy || !chatAbortController) return;
    console.log('[Project] stopChat() — Anfrage abbrechen');
    chatAbortController.abort();
}

async function sendMessage() {
    if (chatBusy) {
        console.log('[Project] Chat beschäftigt, ignoriere Send');
        return;
    }
    const input = document.getElementById('chat-input');
    const text = input.value.trim();
    if (!text) return;

    const model = document.getElementById('model-select').value;
    if (!model) {
        appendError('Kein Modell ausgewählt.');
        return;
    }

    console.log('[Project] sendMessage() Modell=' + model + ' Text="' + text.substring(0, 80) + '"');

    input.value = '';
    input.style.height = '';
    _setChatBusy(true);

    // User-Nachricht anzeigen und speichern
    appendMessage('user', text);
    chatHistory.push({ role: 'user', content: text });

    // Loading-Indikator
    const loadingEl = appendLoading();

    chatAbortController = new AbortController();

    try {
        const payload = {
            model: model,
            board_id: BOARD_ID,
            messages: chatHistory
        };
        console.log('[Project] POST', CHAT_API, 'payload:', JSON.stringify(payload).substring(0, 200));

        const resp = await fetch(CHAT_API, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
            signal: chatAbortController.signal
        });

        if (!resp.ok) {
            const errText = await resp.text().catch(() => '');
            throw new Error(`HTTP ${resp.status}: ${errText.substring(0, 120)}`);
        }

        const data = await resp.json();
        console.log('[Project] Chat-Antwort erhalten:', JSON.stringify(data).substring(0, 200));

        // Antwort extrahieren (verschiedene API-Formate)
        let aiReply = '';
        if (data && data.message && data.message.content) {
            aiReply = data.message.content;
        } else if (data && data.choices && data.choices[0]) {
            aiReply = data.choices[0].message?.content || data.choices[0].text || '';
        } else if (data && typeof data.response === 'string') {
            aiReply = data.response;
        } else if (data && typeof data.content === 'string') {
            aiReply = data.content;
        } else {
            aiReply = JSON.stringify(data);
        }

        loadingEl.remove();
        appendMessage('ai', aiReply);
        chatHistory.push({ role: 'assistant', content: aiReply });
        console.log('[Project] AI-Antwort gespeichert, History-Länge:', chatHistory.length);

        // Board nach KI-Antwort neu laden (KI könnte Änderungen vorgenommen haben)
        console.log('[Project] Lade Board nach AI-Antwort neu');
        await reloadBoard();

    } catch(e) {
        loadingEl.remove();
        if (e.name === 'AbortError') {
            console.log('[Project] Anfrage vom User abgebrochen');
            // Letzte User-Nachricht aus History entfernen (keine Antwort erhalten)
            if (chatHistory.length > 0 && chatHistory[chatHistory.length - 1].role === 'user') {
                chatHistory.pop();
            }
            const stopMsg = document.createElement('div');
            stopMsg.className = 'msg-bubble ai';
            stopMsg.style.cssText = 'opacity:0.5;font-style:italic;font-size:0.78rem;';
            stopMsg.textContent = '⏹ Abgebrochen';
            document.getElementById('chat-messages').appendChild(stopMsg);
            document.getElementById('chat-messages').scrollTop = 9999;
        } else {
            console.error('[Project] Chat-Fehler:', e);
            appendError('Chat nicht erreichbar: ' + e.message);
        }
    } finally {
        _setChatBusy(false);
        input.focus();
    }
}

function clearChat() {
    if (chatHistory.length > 0 && !confirm('Chat-Verlauf löschen?')) return;
    chatHistory = [];
    document.getElementById('chat-messages').innerHTML = '';
    console.log('[Project] Chat-Verlauf gelöscht');
}

// ══════════════════════════════════════════════════════════════
// KEYBOARD SHORTCUTS
// ══════════════════════════════════════════════════════════════
document.addEventListener('keydown', e => {
    // Modal schliessen
    if (e.key === 'Escape') { closeModal(); closeDetail(); closeAttModal(); }
    // Modal speichern mit Enter (nicht in Textarea)
    if (e.key === 'Enter' && document.getElementById('card-modal').classList.contains('open')) {
        if (e.target.tagName !== 'TEXTAREA') saveCard();
    }
});

// ══════════════════════════════════════════════════════════════
// PROJEKT-TERMINAL (ersetzt den früheren KI-Chat)
// Bettet das pro-Projekt-Terminal (ttyd + tmux + Claude Code) als same-origin
// iframe ein: /projterm/?arg=<board-id>. Der Wrapper ~/bin/tmux-project.sh startet
// daraus eine eigene tmux-Session im Projektordner und ruft Claude Code auf.
// ══════════════════════════════════════════════════════════════
function terminalUrl() {
    return '/projterm/?arg=' + encodeURIComponent(BOARD_ID);
}

function initTerminal() {
    const frame = document.getElementById('proj-terminal');
    if (!frame) { console.warn('[Terminal] iframe #proj-terminal fehlt'); return; }
    applyTerminalWidth();          // gemerkten Breit-Zustand wiederherstellen
    applyTerminalZoom();           // gemerkten Schrift-Zoom wiederherstellen
    const url = terminalUrl();
    console.log('[Terminal] lade', url, 'für Board', BOARD_ID);
    frame.addEventListener('load', () => _hookTerminalOsc52(frame));  // feuert auch nach ↻ Neu laden
    frame.src = url;
    _hookTerminalOsc52(frame);
    // Auto-Reconnect: erkennt totes ttyd ("Connection Closed") und lädt nur das
    // iframe neu — tmux reattacht. Logik zentral in /terminal-watchdog.js.
    if (window.TermWatchdog) window.TermWatchdog.watch(frame, 'projterm');
    else console.warn('[Terminal] terminal-watchdog.js nicht geladen — kein Auto-Reconnect');
}

// ── OSC-52-Clipboard-Bridge (Copy-Fix 2026-07-06, wie caddy/html/terminals.html) ──
// tmux (set-clipboard on, ~/.tmux.conf) meldet jede Kopie (Maus-Selektion
// loslassen, copy-mode y) als OSC-52-Sequenz. ttyd 1.7.4/xterm.js wertet die
// nicht aus — wir registrieren am xterm-Objekt des same-origin iframes
// (ttyd exponiert window.term) einen Handler, der den Text ins Browser-
// Clipboard schreibt. Ohne User-Geste (Safari) fällt er auf ein Overlay
// mit "Kopieren"-Knopf zurück.
function _osc52Decode(data) {
    const i = data.indexOf(';');
    const b64 = i >= 0 ? data.slice(i + 1) : data;
    if (!b64 || b64 === '?') return null;      // "?" = Clipboard-Abfrage der App
    try {
        const bin = atob(b64);
        return new TextDecoder().decode(Uint8Array.from(bin, c => c.charCodeAt(0)));
    } catch (e) { console.warn('[Terminal] OSC52 base64-Fehler:', e); return null; }
}

function _osc52Write(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(
            () => console.log('[Terminal] OSC52:', text.length, 'Zeichen ins Clipboard kopiert'),
            err => { console.warn('[Terminal] OSC52 writeText abgelehnt:', err); _osc52Overlay(text); });
    } else { _osc52Overlay(text); }
}

function _osc52Overlay(text) {
    let ov = document.getElementById('copyov');
    if (!ov) {
        ov = document.createElement('div');
        ov.id = 'copyov';
        ov.style.cssText = 'position:fixed;left:8px;right:8px;bottom:8px;z-index:9999;' +
            'background:#1c2128;border:1px solid #444c56;border-radius:8px;padding:8px;' +
            'display:flex;gap:8px;align-items:stretch;box-shadow:0 4px 16px rgba(0,0,0,.5)';
        ov.innerHTML =
            '<textarea id="copyov-ta" readonly style="flex:1;height:52px;background:#0d1117;' +
              'color:#e6edf3;border:1px solid #30363d;border-radius:6px;padding:6px;' +
              'font:12px monospace;resize:none"></textarea>' +
            '<button id="copyov-copy" style="background:#238636;color:#fff;border:0;' +
              'border-radius:6px;padding:0 14px;font-size:14px;cursor:pointer">Kopieren</button>' +
            '<button id="copyov-close" style="background:#30363d;color:#e6edf3;border:0;' +
              'border-radius:6px;padding:0 12px;font-size:14px;cursor:pointer">✕</button>';
        document.body.appendChild(ov);
        ov.querySelector('#copyov-close').addEventListener('click', () => ov.remove());
        ov.querySelector('#copyov-copy').addEventListener('click', () => {
            const ta = ov.querySelector('#copyov-ta');
            ta.focus(); ta.select();
            const done = () => { console.log('[Terminal] OSC52: via Overlay kopiert'); ov.remove(); };
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(ta.value).then(done, () => { document.execCommand('copy'); done(); });
            } else { document.execCommand('copy'); done(); }
        });
    }
    ov.querySelector('#copyov-ta').value = text;
}

function _hookTerminalOsc52(frame) {
    // window.term entsteht erst nach dem load-Event; nach Reload ist es ein
    // NEUES Objekt -> Merker sitzt am term selbst, mehrere Versuche nötig.
    [300, 800, 2000, 4000].forEach(ms => setTimeout(() => {
        try {
            const t = frame.contentWindow && frame.contentWindow.term;
            if (!t || t.__osc52hooked) return;
            t.__osc52hooked = true;
            t.parser.registerOscHandler(52, data => {
                const txt = _osc52Decode(data);
                if (txt) _osc52Write(txt);
                return true;
            });
            console.log('[Terminal] OSC52-Handler registriert');
        } catch (e) { console.warn('[Terminal] OSC52-Hook fehlgeschlagen:', e); }
    }, ms));
}

// Breit-Modus umschalten: Panel wächst von 400px auf ~55% (CSS-Klasse .terminal-wide),
// damit die Claude-Code-TUI mehr Spalten bekommt. Zustand in localStorage gemerkt.
// Nach dem Resize bekommt das same-origin iframe einen 'resize'-Stups, damit ttyd
// (xterm fit-addon) die Spaltenzahl sofort neu berechnet — sonst erst beim nächsten
// Fenster-Resize / ↻ Neu laden.
function toggleTerminalWidth() {
    const panel = document.querySelector('.chat-panel');
    if (!panel) return;
    const wide = !panel.classList.contains('terminal-wide');
    panel.classList.toggle('terminal-wide', wide);
    try { localStorage.setItem('term_wide', wide ? '1' : '0'); } catch (e) {}
    _setWideBtn(wide);
    console.log('[Terminal] Breit-Modus =', wide);
    _nudgeTerminalResize();
}

// Gemerkten Zustand beim Laden anwenden (ohne den iframe anzufassen).
function applyTerminalWidth() {
    const panel = document.querySelector('.chat-panel');
    if (!panel) return;
    // Standard = BREIT (2026-06-18). Nur ein explizit gespeicherter Wert ('0'/'1')
    // sticht den Default → wer bewusst auf Schmal schaltet, behält das; frische
    // Browser ohne gespeicherte Wahl starten breit.
    let wide = true;
    try {
        const v = localStorage.getItem('term_wide');
        if (v !== null) wide = (v === '1');
    } catch (e) {}
    panel.classList.toggle('terminal-wide', wide);
    _setWideBtn(wide);
}

function _setWideBtn(wide) {
    const btn = document.getElementById('term-wide-btn');
    if (btn) btn.textContent = wide ? '⇥⇤' : '↔';   // symbol-kurz (weniger Text): ⇥⇤ = schmaler, ↔ = breiter
}

// ── Terminal-Zoom (Schrift kleiner = mehr Spalten/Zeilen) ──────────────────
// Trick „Fenster grösser tun" ohne ttyd-Internas: die CSS-Variable --term-zoom
// auf .chat-panel bläst das iframe auf 100%/zoom auf und skaliert es per
// transform:scale(zoom) optisch zurück. Resultat: ttyds fit-addon misst mehr
// Pixel -> mehr Spalten/Zeilen, die Schrift wirkt kleiner. Wert pro Browser
// gemerkt (localStorage). Grenzen 0.6..1.0 in 0.1-Schritten (1.0 = Original).
const _TERM_ZOOM_MIN = 0.6, _TERM_ZOOM_MAX = 1.0, _TERM_ZOOM_STEP = 0.1;

const _TERM_ZOOM_DEFAULT = 0.8;   // Standard 80% (2026-06-18) — mehr Spalten/Zeilen ab Werk

function _termZoom() {
    let z = parseFloat(localStorage.getItem('term_zoom'));
    if (!Number.isFinite(z)) z = _TERM_ZOOM_DEFAULT;   // nichts gespeichert -> Default
    return Math.min(_TERM_ZOOM_MAX, Math.max(_TERM_ZOOM_MIN, z));
}

// delta -1 = kleiner (rauszoomen), +1 = grösser. Schreibt die CSS-Variable,
// merkt den Wert und stupst ttyd zum Neuvermessen an.
function setTerminalZoom(delta) {
    let z = _termZoom() + delta * _TERM_ZOOM_STEP;
    z = Math.round(z * 10) / 10;                       // saubere 0.1-Schritte
    z = Math.min(_TERM_ZOOM_MAX, Math.max(_TERM_ZOOM_MIN, z));
    try { localStorage.setItem('term_zoom', String(z)); } catch (e) {}
    applyTerminalZoom();
    console.log('[Terminal] Zoom =', z, '(' + Math.round(z * 100) + '%)');
}

// Gemerkten Zoom anwenden (Variable setzen + Buttons-Status + Resize-Stups).
function applyTerminalZoom() {
    const panel = document.querySelector('.chat-panel');
    if (!panel) return;
    const z = _termZoom();
    panel.style.setProperty('--term-zoom', String(z));
    const out = document.getElementById('term-zoom-out');
    const inb = document.getElementById('term-zoom-in');
    if (out) out.disabled = (z <= _TERM_ZOOM_MIN + 1e-9);   // unten angeschlagen
    if (inb) inb.disabled = (z >= _TERM_ZOOM_MAX - 1e-9);   // bei Original
    _nudgeTerminalResize();
}

// ttyd lauscht im iframe auf 'resize' (xterm fit-addon). Eine CSS-Breitenänderung
// feuert das nicht immer zuverlässig -> nach der Layout-Änderung explizit anstossen
// (same-origin, daher Zugriff aufs contentWindow erlaubt; in try/catch gekapselt).
function _nudgeTerminalResize() {
    const frame = document.getElementById('proj-terminal');
    if (!frame) return;
    setTimeout(() => {
        try { frame.contentWindow?.dispatchEvent(new Event('resize')); }
        catch (e) { console.debug('[Terminal] resize-Stups nicht möglich:', e); }
    }, 80);
}

// Terminal neu laden (Button ↻). Heilt ERST die tmux-Session serverseitig, DANN
// reattacht das iframe frisch. /projterm-heal (a) löst alle ttyd-Clients der Session
// -> behebt Mosaik/Geistertext (kein Doppel-Client mehr), (b) startet bei toter bash
// `claude --continue` -> die letzte Konversation läuft weiter. Erst nach der Antwort
// das iframe neu setzen, damit es als EINZIGER Client in richtiger Grösse reattacht.
async function reloadTerminal() {
    const frame = document.getElementById('proj-terminal');
    if (!frame) return;
    const btn = document.getElementById('term-reload-btn');
    if (btn) { btn.disabled = true; btn.dataset.t = btn.textContent; btn.textContent = '… heile'; }
    try {
        const r = await fetch('/projterm-heal?board=' + encodeURIComponent(BOARD_ID), { method: 'POST' });
        const j = await r.json().catch(() => ({}));
        console.log('[Terminal] heal-Ergebnis:', j);
    } catch (e) {
        console.warn('[Terminal] heal fehlgeschlagen (lade trotzdem neu):', e);
    }
    // claude --continue braucht einen Moment zum Hochfahren, bevor wir reattachen
    setTimeout(() => {
        frame.src = terminalUrl() + '&_=' + Date.now();
        if (btn) { btn.disabled = false; btn.textContent = btn.dataset.t || '↻ Neu laden'; }
        console.log('[Terminal] neu geladen (Mosaik + tote Session geheilt)');
    }, 700);
}

// Vollbild umschalten (ganzer Bildschirm <-> normal). Nutzt die Fullscreen-API
// (ganzer Monitor); fällt auf eine CSS-Klasse zurück (füllt den Browser-Tab), wenn
// die API fehlt/abgelehnt wird. Esc beendet (Browser bei echtem FS, sonst Listener).
function toggleTerminalFullscreen() {
    const panel = document.querySelector('.chat-panel');
    if (!panel) return;
    const isMax = document.fullscreenElement === panel || panel.classList.contains('terminal-maximized');
    if (isMax) {
        if (document.fullscreenElement) { document.exitFullscreen?.(); }
        else { panel.classList.remove('terminal-maximized'); _setFsBtn(false); }
        ptSetHeaderTouchUi(panel);
    } else if (panel.requestFullscreen) {
        panel.requestFullscreen().catch(() => { panel.classList.add('terminal-maximized'); _setFsBtn(true); });
        panel.classList.add('pt-touch-ui', 'header-collapsed');
    } else {
        panel.classList.add('terminal-maximized'); _setFsBtn(true);
        panel.classList.add('pt-touch-ui', 'header-collapsed');
    }
    console.log('[Terminal] Vollbild umschalten, war max=' + isMax);
}

// ══ Einklappbarer Terminal-Header (2026-08-09) ═══════════════════════════
// Grund: Header (Icons + Modell-Zeile + Label) frass am iPhone ~1/3 des
// Bildschirms. Auf Touch-Geräten UND im Vollbild startet er eingeklappt;
// #pt-header-handle (dünner Griff über dem Terminal) klappt ihn per Tap
// oder Wisch auf/zu. Desktop ohne Vollbild bleibt unverändert (Griff bleibt
// per CSS unsichtbar ohne .pt-touch-ui).
function ptIsTouchUi() {
    return !(window.matchMedia('(pointer: fine)').matches && !('ontouchstart' in window));
}

// Nach echtem Fullscreen-Exit (Browser-Esc) den Touch-UI-Status neu bewerten:
// auf Touch-Geräten bleibt eingeklappt (Default), am Desktop wieder normal.
function ptSetHeaderTouchUi(panel) {
    const isMax = document.fullscreenElement === panel || panel.classList.contains('terminal-maximized');
    if (isMax || ptIsTouchUi()) {
        panel.classList.add('pt-touch-ui');
    } else {
        panel.classList.remove('pt-touch-ui', 'header-collapsed');
    }
}

function ptInitHeaderHandle() {
    const panel = document.querySelector('.chat-panel');
    const handle = document.getElementById('pt-header-handle');
    if (!panel || !handle) return;

    if (ptIsTouchUi()) { panel.classList.add('pt-touch-ui', 'header-collapsed'); }

    handle.addEventListener('click', () => panel.classList.toggle('header-collapsed'));

    let startY = null;
    handle.addEventListener('touchstart', e => { startY = e.touches[0].clientY; }, { passive: true });
    handle.addEventListener('touchmove', e => {
        if (startY == null) return;
        const dy = e.touches[0].clientY - startY;
        if (dy > 24) { panel.classList.remove('header-collapsed'); startY = null; }
        else if (dy < -24) { panel.classList.add('header-collapsed'); startY = null; }
    }, { passive: true });
    handle.addEventListener('touchend', () => { startY = null; });

    console.log('[Terminal] Header-Handle initialisiert, touchUi=' + ptIsTouchUi());
}
document.addEventListener('DOMContentLoaded', ptInitHeaderHandle);

function _setFsBtn(isMax) {
    const btn = document.getElementById('term-fs-btn');
    if (btn) btn.textContent = isMax ? '⤡' : '⛶';   // symbol-kurz: ⤡ = verkleinern, ⛶ = Vollbild
}

// Button-Text mit echtem Fullscreen-Status synchronisieren (z.B. Esc des Browsers).
document.addEventListener('fullscreenchange', () => {
    const panel = document.querySelector('.chat-panel');
    _setFsBtn(!!panel && document.fullscreenElement === panel);
    if (panel) ptSetHeaderTouchUi(panel);
});
// Esc im CSS-Fallback (kein echtes FS) -> verkleinern.
document.addEventListener('keydown', e => {
    if (e.key !== 'Escape' || document.fullscreenElement) return;
    const panel = document.querySelector('.chat-panel');
    if (panel && panel.classList.contains('terminal-maximized')) {
        panel.classList.remove('terminal-maximized');
        _setFsBtn(false);
        ptSetHeaderTouchUi(panel);
    }
});

// ══════════════════════════════════════════════════════════════
// UNTERPROJEKTE
// ══════════════════════════════════════════════════════════════
let subprojectsData = [];
let pickerState = { mode: null, subId: null, subName: '' };
let allBoardsCache = [];

