// project-decisions.js — Antwort-Knöpfe direkt auf Entscheidungskarten im Board.
// Bisher liessen sich Entscheidungen nur auf /fragen.html oder /automat.html
// beantworten; wer die Karte im Kanban sah, hatte keine Antwortmöglichkeit.
// Quelle der Optionen ist GET /api/automat/decisions (dort wird geparst), die
// Antwort geht an POST /api/automat/decide (Karte -> Erledigt, Board entsperrt).
// Klassik-Script, gemeinsamer globaler Scope mit den uebrigen project-*.js.

// card_id -> decision object (nur Karten DIESES Boards)
let DECISIONS_BY_CARD = {};

// Choice with these words means "card is noise -> delete" (mirrors _DELETE_HINTS
// in app/api/automat.py). Rendered red + with a confirmation prompt.
const DECISION_DEL_RE = /rauschen|löschen|loeschen|verwerfen/i;

async function loadDecisions() {
    try {
        const data = await API.get('/api/automat/decisions?t=' + Date.now());
        const all = (data && data.decisions) || [];
        const mine = all.filter(d => d.board === BOARD_ID);
        const before = Object.keys(DECISIONS_BY_CARD).sort().join('|');
        DECISIONS_BY_CARD = {};
        mine.forEach(d => { if (d.card_id) DECISIONS_BY_CARD[d.card_id] = d; });
        const after = Object.keys(DECISIONS_BY_CARD).sort().join('|');
        console.log('[Decisions] ' + mine.length + ' offene Entscheidung(en) in ' + BOARD_ID +
                    ' (von ' + all.length + ' gesamt), geändert=' + (before !== after));
        if (before !== after) render();   // Knöpfe nachziehen, sobald die Daten da sind
        // Der 🤖-Button (project-core.js) kennt den Status „Entscheidung nötig" erst,
        // wenn diese Daten da sind — sie kommen nicht-blockierend NACH dem ersten Render.
        if (typeof renderAutoBtn === 'function') renderAutoBtn();
    } catch (e) {
        console.warn('[Decisions] konnten nicht geladen werden:', e);
    }
}

// Wird aus renderCard() (project-board.js) aufgerufen — hängt den Antwort-Block
// an, wenn die Karte eine offene Entscheidung ist.
function renderDecisionAnswers(card, el) {
    const d = (card && card.id) ? DECISIONS_BY_CARD[card.id] : null;
    if (!d) return;
    el.classList.add('decision-card');

    const box = document.createElement('div');
    box.className = 'card-decision';
    box.addEventListener('click', e => e.stopPropagation());   // kein Detail-Modal

    const hint = document.createElement('div');
    hint.className = 'cd-hint';
    hint.textContent = d.options_generic
        ? '🙋 Entscheidung nötig — die Karte nennt keine Optionen, darum Standard-Antworten:'
        : '🙋 Entscheidung nötig — bitte antworten:';
    box.appendChild(hint);

    (d.options || []).forEach(opt => {
        const isDel = DECISION_DEL_RE.test(opt);
        const b = document.createElement('button');
        b.className = 'cd-opt' + (isDel ? ' del' : '');
        b.textContent = (isDel ? '🗑️ ' : '') + opt;
        b.title = opt;
        b.onclick = e => { e.stopPropagation(); answerDecision(d, opt, box); };
        box.appendChild(b);
    });

    const free = document.createElement('div');
    free.className = 'cd-free';
    const input = document.createElement('input');
    input.type = 'text';
    input.placeholder = 'oder eigene Antwort …';
    input.onkeydown = e => {
        e.stopPropagation();
        if (e.key === 'Enter' && input.value.trim()) answerDecision(d, input.value.trim(), box);
    };
    const send = document.createElement('button');
    send.className = 'cd-send';
    send.textContent = 'Antworten';
    send.onclick = e => {
        e.stopPropagation();
        if (input.value.trim()) answerDecision(d, input.value.trim(), box);
    };
    free.appendChild(input);
    free.appendChild(send);
    box.appendChild(free);

    const fb = document.createElement('div');
    fb.className = 'cd-feedback';
    box.appendChild(fb);

    el.appendChild(box);
}

async function answerDecision(d, choice, box) {
    choice = (choice || '').trim();
    if (!choice) return;
    const isDel = DECISION_DEL_RE.test(choice);
    if (isDel && !confirm('Karte als Rauschen löschen?\n\n' + choice)) return;

    const fb = box.querySelector('.cd-feedback');
    box.querySelectorAll('button, input').forEach(x => { x.disabled = true; });
    if (fb) { fb.className = 'cd-feedback'; fb.textContent = '⏳ sende …'; }
    console.log('[Decisions] antworte auf', d.card_id, '→', choice, '(delete=' + isDel + ')');

    try {
        const r = await API.post('/api/automat/decide',
                                 { board: BOARD_ID, card_id: d.card_id, choice: choice });
        console.log('[Decisions] Antwort gespeichert:', r);
        if (fb) {
            fb.className = 'cd-feedback ok';
            fb.textContent = (r && r.deleted ? '🗑️ als Rauschen gelöscht' : '✅ beantwortet')
                           + (r && r.source_answered ? ' · auch im Quell-Board erledigt' : '');
        }
        delete DECISIONS_BY_CARD[d.card_id];
        await loadBoard(true);      // Karte liegt jetzt in „Erledigt"
        loadDecisions();
    } catch (e) {
        console.error('[Decisions] fehlgeschlagen:', e);
        box.querySelectorAll('button, input').forEach(x => { x.disabled = false; });
        if (fb) { fb.className = 'cd-feedback err'; fb.textContent = '⚠️ ' + e; }
    }
}
