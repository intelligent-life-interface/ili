// project-board.js — Teil von project.js (aufgeteilt 2026-07-24, Kanban arch_6cb5b87e65).
// Board-/Spalten-/Karten-Rendering, Drag&Drop, KI-Karten-Aktionen, Owner, Titel-Vorschlag
// Klassik-Script, gemeinsamer globaler Scope mit den uebrigen project-*.js — Ladereihenfolge in project.html beachten.
function render() {
    const boardEl = document.getElementById('board');
    boardEl.innerHTML = '';

    // Navigations-Spalte extrahieren und als View-Tabs rendern
    renderViewTabs(board.columns || []);

    (board.columns || []).forEach((col, ci) => {
        // Navigation-Spalte nicht als Kanban-Spalte anzeigen
        if (col.id === 'navigation') return;
        boardEl.appendChild(renderColumn(col, ci));
    });

    const addBtn = document.createElement('button');
    addBtn.className = 'add-column-btn';
    addBtn.textContent = '＋ Neue Spalte';
    addBtn.onclick = addColumn;
    boardEl.appendChild(addBtn);
}

function renderViewTabs(columns) {
    const tabsEl = document.getElementById('view-tabs');
    // Robust: kann auch ohne Argument aufgerufen werden (z.B. nach loadSubprojects),
    // dann das aktuell geladene Board verwenden.
    columns = columns || (board && board.columns) || [];
    const navCol = columns.find(c => c.id === 'navigation');
    const navCards = (navCol && navCol.cards) || [];
    const subs = subprojectsData || [];   // Unterprojekte (parent_id-Kinder), farbig oben

    // Tab-Leiste nur anzeigen, wenn es Unterprojekte ODER navigation-Karten gibt
    if (navCards.length === 0 && subs.length === 0) {
        tabsEl.classList.remove('visible');
        tabsEl.innerHTML = '';
        return;
    }

    tabsEl.classList.add('visible');
    tabsEl.innerHTML = '';

    // "Aktuell"-Tab immer zuerst
    const selfTab = document.createElement('a');
    selfTab.className = 'view-tab active';
    selfTab.href = '/project.html?id=' + encodeURIComponent(BOARD_ID);
    selfTab.textContent = '📋 ' + ((board && board.title) || BOARD_ID);
    tabsEl.appendChild(selfTab);

    // Unterprojekte: farbige Tabs DIREKT nach "Aktuell" → immer ganz oben zuerst.
    // Farbe = Manifest-Farbe des Unterprojekts (sub.color); deutlich abgesetzt vom Eltern-Board.
    subs.forEach(sub => {
        if (!sub || !sub.id || sub.id === BOARD_ID) return;
        const tab = document.createElement('a');
        tab.className = 'view-tab sub-tab';
        tab.href = '/project.html?id=' + encodeURIComponent(sub.id);
        tab.textContent = (sub.icon || '📂') + ' ' + (sub.name || sub.id);
        tab.title = 'Unterprojekt: ' + (sub.name || sub.id);
        const col = sub.color || '#9f7aea';
        tab.style.background = col;
        tab.style.borderColor = col;
        tab.style.color = '#0f1117';   // dunkler Text auf farbigem Grund (gut lesbar)
        tabsEl.appendChild(tab);
    });

    navCards.forEach(card => {
        // Board-ID aus desc extrahieren: "Wechsel zum Board: <id>" oder direkt als id
        let targetId = '';
        const match = (card.desc || '').match(/Wechsel zum Board:\s*(\S+)/);
        if (match) targetId = match[1];
        else if (card.board_id) targetId = card.board_id;

        if (!targetId || targetId === BOARD_ID) return;

        const tab = document.createElement('a');
        tab.className = 'view-tab';
        tab.href = '/project.html?id=' + encodeURIComponent(targetId);
        tab.textContent = card.title || targetId;
        tab.title = targetId;
        tabsEl.appendChild(tab);
    });

    console.log('[Project] View-Tabs gerendert:', tabsEl.children.length, 'Tabs');
}

function renderColumn(col, ci) {
    const colEl = document.createElement('div');
    colEl.className = 'column';
    colEl.dataset.ci = ci;

    // Header
    const header = document.createElement('div');
    header.className = 'col-header';

    // Teil 4a: Drag-Handle zum Umsortieren der Spalte
    const handle = document.createElement('span');
    handle.className = 'col-drag-handle';
    handle.textContent = '⠿';
    handle.title = 'Spalte verschieben';
    handle.draggable = true;
    handle.addEventListener('dragstart', e => {
        dragColIdx = ci;
        e.dataTransfer.effectAllowed = 'move';
        e.stopPropagation();
        colEl.classList.add('col-dragging');
    });
    handle.addEventListener('dragend', () => {
        dragColIdx = null;
        document.querySelectorAll('.col-dragging,.col-drop').forEach(el => el.classList.remove('col-dragging', 'col-drop'));
    });
    header.appendChild(handle);

    // Spalten als Drop-Ziel (nur wenn gerade eine Spalte gezogen wird)
    header.addEventListener('dragover', e => {
        if (dragColIdx === null) return;
        e.preventDefault();
        header.classList.add('col-drop');
    });
    header.addEventListener('dragleave', () => header.classList.remove('col-drop'));
    header.addEventListener('drop', e => {
        if (dragColIdx === null) return;
        e.preventDefault();
        header.classList.remove('col-drop');
        let to = ci, from = dragColIdx;
        if (from === to) return;
        const [moved] = board.columns.splice(from, 1);
        if (from < to) to--;
        board.columns.splice(to, 0, moved);
        dragColIdx = null;
        console.log(`[Project] Spalte ${from} → ${to}`);
        render();
        autoSave();
    });

    const titleInput = document.createElement('input');
    titleInput.className = 'col-title';
    titleInput.value = col.title;
    titleInput.addEventListener('change', () => {
        col.title = titleInput.value.trim() || col.title;
        countEl.textContent = col.cards.length;
        autoSave();
    });

    const countEl = document.createElement('span');
    countEl.className = 'col-count';
    countEl.textContent = (col.cards || []).length;

    const delBtn = document.createElement('button');
    delBtn.className = 'col-del';
    delBtn.title = 'Spalte löschen';
    delBtn.textContent = '✕';
    delBtn.onclick = () => deleteColumn(ci);

    header.appendChild(titleInput);
    header.appendChild(countEl);
    header.appendChild(delBtn);
    colEl.appendChild(header);

    // Cards area
    const cardsEl = document.createElement('div');
    cardsEl.className = 'cards';
    cardsEl.dataset.ci = ci;

    (col.cards || []).forEach((card, ki) => {
        cardsEl.appendChild(renderCard(card, ci, ki));
    });

    // Drop-Zone Events
    cardsEl.addEventListener('dragover', e => {
        if (dragCard === null) return;  // nur Karten-Drags (nicht Spalten/Subprojekte)
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        cardsEl.classList.add('drag-active');
        // Fix 2026-06-10: Platzhalter WIEDERVERWENDEN statt pro Event neu erzeugen —
        // Remove+Neu liess das Layout unter dem Cursor springen (Platzhalter "flackerte",
        // Karte landete an der falschen Stelle). Gezogene Karte (.dragging) ist kein Ziel.
        const targetCard = e.target.closest('.card:not(.drag-placeholder):not(.dragging)');
        if (!placeholder) placeholder = makePlaceholder();
        let refNode = null;  // Knoten VOR dem der Platzhalter stehen soll (null = ans Ende)
        if (targetCard) {
            const rect = targetCard.getBoundingClientRect();
            refNode = (e.clientY < rect.top + rect.height / 2) ? targetCard : targetCard.nextSibling;
        }
        // Nur bewegen wenn sich die Zielposition wirklich ändert → ruhiges Bild
        // Fix 2026-08-17 (drag-drop bug): Vereinfachte Bedingung — prüfe ob Platzhalter bereits
        // an der richtigen Position ist. Verschiebe NUR wenn Position sich ändert.
        const alreadyAtTarget = placeholder.parentElement === cardsEl &&
                               (refNode === null ?
                                   !placeholder.nextSibling :   // Platzhalter sollte am Ende sein
                                   placeholder.nextSibling === refNode);  // Platzhalter sollte vor refNode sein
        if (!alreadyAtTarget) {
            cardsEl.insertBefore(placeholder, refNode);
        }
    });
    cardsEl.addEventListener('dragleave', e => {
        if (!cardsEl.contains(e.relatedTarget)) {
            cardsEl.classList.remove('drag-active');
        }
    });
    cardsEl.addEventListener('drop', e => {
        e.preventDefault();
        cardsEl.classList.remove('drag-active');
        if (dragCard === null) return;
        const targetCi = parseInt(cardsEl.dataset.ci);

        // Fix 2026-06-10: Index OHNE die gezogene Karte zählen (sie steht beim Drop noch
        // an ihrer alten DOM-Position) → entspricht direkt dem Array nach dem splice,
        // die alte ±1-Korrektur entfällt.
        let newIdx = (board.columns[targetCi].cards || []).length - (targetCi === dragSrcCol ? 1 : 0);
        if (placeholder && placeholder.parentElement === cardsEl) {
            const children = Array.from(cardsEl.children);
            const phIdx = children.indexOf(placeholder);
            newIdx = children.filter((n, i) =>
                i < phIdx &&
                !n.classList.contains('drag-placeholder') &&
                !n.classList.contains('dragging')
            ).length;
        }

        const [movedCard] = board.columns[dragSrcCol].cards.splice(dragSrcIdx, 1);
        board.columns[targetCi].cards.splice(newIdx, 0, movedCard);

        if (placeholder) { placeholder.remove(); placeholder = null; }
        render();
        autoSave();
        console.log(`[Project] Karte von Col${dragSrcCol}[${dragSrcIdx}] → Col${targetCi}[${newIdx}]`);
    });

    colEl.appendChild(cardsEl);

    const addBtn = document.createElement('button');
    addBtn.className = 'add-card-btn';
    addBtn.textContent = '＋ Karte hinzufügen';
    addBtn.onclick = () => openModal(ci);
    colEl.appendChild(addBtn);

    return colEl;
}

// Prioritäts-/Aufwand-Stile (geteilt: kompakte Karte + Detail-Modal)
const PRIO_STYLE = {
    hoch:    { bg: '#4a1f1f', fg: '#fc8181', txt: 'Hoch' },
    mittel:  { bg: '#4a3a1f', fg: '#f6ad55', txt: 'Mittel' },
    niedrig: { bg: '#1f4a2a', fg: '#68d391', txt: 'Niedrig' },
};

const escHtml = window.escHtml;

// Besitzer einer Karte setzen (👤 me / 🤖 ki / leer). Gleicher Knopf = Toggle aus.
// Optimistisch + Rollback; Backend spiegelt 'me'-Karten sofort ins Board 'meine-aufgaben'.
async function setCardOwner(ci, ki, owner) {
    const card = board.columns[ci] && board.columns[ci].cards[ki];
    if (!card || !card.id) { console.warn('[Owner] keine Karte/ID'); return; }
    const prev = card.owner || '';
    const next = (prev === owner) ? '' : owner;   // erneuter Klick hebt auf
    card.owner = next || undefined;               // optimistisch
    render();
    console.log('[Owner] Karte', card.id, ':', prev || '(keiner)', '→', next || '(keiner)');
    try {
        await API.post('/card-owner', { board_id: BOARD_ID, card_id: card.id, owner: next });
    } catch (e) {
        card.owner = prev || undefined;           // rollback
        render();
        console.error('[Owner] fehlgeschlagen:', e);
        alert('Besitzer setzen fehlgeschlagen: ' + e);
    }
}

function renderCard(card, ci, ki) {
    const el = document.createElement('div');
    el.className = 'card';
    if (card.id) el.dataset.cardId = card.id;   // Ziel für Deep-Links (?card=<id>)

    el.draggable = true;

    el.addEventListener('dragstart', e => {
        dragCard = card;
        dragSrcCol = ci;
        dragSrcIdx = ki;
        el.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move';
        console.log(`[Project] dragstart Col${ci}[${ki}]: "${card.title}"`);
    });
    el.addEventListener('dragend', () => {
        el.classList.remove('dragging');
        dragCard = null;  // Fix 2026-06-10: sonst reagiert die Drop-Zone auf Spalten-Drags
        if (placeholder) { placeholder.remove(); placeholder = null; }
        document.querySelectorAll('.drag-active').forEach(e => e.classList.remove('drag-active'));
    });

    // Foto + Beschreibung + Schnittstellen + Refs: nur im Detail-Modal (kompakte Kartenfläche)
    const isKiCard = card.label === '🤖 KI';

    if (isKiCard) {
        el.classList.add('ki-card');
        const badge = document.createElement('div');
        badge.className = 'ki-badge';
        badge.textContent = '🤖 KI-Vorschlag';
        el.appendChild(badge);
    } else if (card.label) {
        const lbl = document.createElement('div');
        lbl.className = 'card-label';
        lbl.style.background = card.label;
        el.appendChild(lbl);
    }

    const title = document.createElement('div');
    title.className = 'card-title';
    title.textContent = card.title;
    el.appendChild(title);

    // Kompakte Meta-Zeile: Priorität · Aufwand · Indikatoren für verstecktes Material.
    // Volltext (Beschreibung, Schnittstellen, Refs, Foto) erscheint erst im Detail-Modal.
    const cmChips = [];
    if (card.priority && PRIO_STYLE[card.priority]) {
        const p = PRIO_STYLE[card.priority];
        cmChips.push(`<span class="cmeta" title="Priorität: ${p.txt}" style="background:${p.bg};color:${p.fg}">⚡ ${p.txt}</span>`);
    }
    if (card.effort && PRIO_STYLE[card.effort]) {
        cmChips.push(`<span class="cmeta" title="Aufwand: ${PRIO_STYLE[card.effort].txt}" style="background:#2d3748;color:#a0aec0">⏱ ${PRIO_STYLE[card.effort].txt}</span>`);
    }
    // Besitzer-Chip (👤 Ich / 🤖 KI) — zeigt, wer die Aufgabe erledigt
    if (card.owner === 'me') {
        cmChips.push(`<span class="cmeta" title="Besitzer: Ich (wird ins Board 'Meine Aufgaben' gespiegelt)" style="background:#1a365d;color:#90cdf4">👤 Ich</span>`);
    } else if (card.owner === 'ki') {
        cmChips.push(`<span class="cmeta" title="Besitzer: KI" style="background:#322659;color:#d6bcfa">🤖 KI</span>`);
    }
    const inds = [];
    if (card.desc || card.description) inds.push('📝');   // Sync/KI-Karten nutzen `description`, UI-Karten `desc`
    if (card.photo_url) inds.push('📷');
    if (card.input || card.output || card.model || card.task) inds.push('🔌');
    if (card.refs && card.refs.length) inds.push('🔗' + card.refs.length);
    if (card.attachments && card.attachments.length) inds.push('📎' + card.attachments.length);
    if (inds.length) cmChips.push(`<span class="cmeta cmeta-ind" title="Öffnen für Details">${inds.join(' ')}</span>`);
    if (cmChips.length) {
        const meta = document.createElement('div');
        meta.className = 'card-meta';
        meta.innerHTML = cmChips.join('');
        el.appendChild(meta);
    }

    // Besitzer-Knöpfe (👤 Ich / 🤖 KI) — Toggle; nur für echte Aufgaben-Karten
    // (nicht für KI-Vorschläge oder die angepinnte Beschreibungskarte).
    if (!isKiCard && card.id !== 'claudemd-description') {
        const ownerBtns = document.createElement('div');
        ownerBtns.className = 'card-owner-btns';
        [['me', '👤', 'Ich'], ['ki', '🤖', 'KI']].forEach(([val, emoji, txt]) => {
            const b = document.createElement('button');
            b.className = 'card-btn owner-btn' + (card.owner === val ? ' owner-active' : '');
            b.textContent = emoji;
            b.title = (card.owner === val ? 'Besitzer entfernen' : 'Besitzer: ' + txt);
            b.onclick = e => { e.stopPropagation(); setCardOwner(ci, ki, val); };
            ownerBtns.appendChild(b);
        });
        el.appendChild(ownerBtns);
    }

    // Klick auf die Karte (nicht auf Buttons/Reject-Form/Refs) → Detail-Modal
    el.addEventListener('click', e => {
        if (e.target.closest('.card-btn, .reject-form, .card-ref-badge, .swipe-hint')) return;
        if (el.classList.contains('dragging')) return;
        openDetail(ci, ki);
    });

    // ── Reject-Formular (nur für KI-Karten) ─────────────────
    let rejectForm = null;
    if (isKiCard) {
        rejectForm = document.createElement('div');
        rejectForm.className = 'reject-form';

        const lbl = document.createElement('label');
        lbl.textContent = 'Warum lehnst du diesen Vorschlag ab?';
        rejectForm.appendChild(lbl);

        const textarea = document.createElement('textarea');
        textarea.className = 'reject-input';
        textarea.rows = 2;
        textarea.placeholder = 'z.B. "Schon umgesetzt", "Passt nicht zum Projekt", "Zu aufwändig"…';
        rejectForm.appendChild(textarea);

        const actions = document.createElement('div');
        actions.className = 'reject-actions';

        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'reject-cancel';
        cancelBtn.textContent = 'Abbrechen';
        cancelBtn.onclick = e => { e.stopPropagation(); rejectForm.classList.remove('open'); };

        const sendBtn = document.createElement('button');
        sendBtn.className = 'reject-send';
        sendBtn.textContent = '✗ Ablehnen';
        sendBtn.onclick = e => {
            e.stopPropagation();
            rejectKiCard(card, textarea.value.trim(), el);
        };

        actions.appendChild(cancelBtn);
        actions.appendChild(sendBtn);
        rejectForm.appendChild(actions);
        el.appendChild(rejectForm);
    }

    // Antwort-Knöpfe, wenn die Karte eine offene Automat-Entscheidung ist
    // (project-decisions.js; Optionen kommen aus /api/automat/decisions).
    if (typeof renderDecisionAnswers === 'function') renderDecisionAnswers(card, el);

    // Spiegel-Karte? Link auf die Master-Karte im Quell-Projekt (project-mirror.js)
    if (typeof renderMirrorLink === 'function') renderMirrorLink(card, el);

    const footer = document.createElement('div');
    footer.className = 'card-footer';

    const editBtn = document.createElement('button');
    editBtn.className = 'card-btn';
    editBtn.title = 'Bearbeiten';
    editBtn.textContent = '✏️';
    editBtn.onclick = e => { e.stopPropagation(); openModal(ci, ki); };

    const delBtn = document.createElement('button');
    delBtn.className = 'card-btn del';
    delBtn.title = 'Löschen';
    delBtn.textContent = '🗑';
    delBtn.onclick = e => { e.stopPropagation(); deleteCard(ci, ki); };

    footer.appendChild(editBtn);
    footer.appendChild(delBtn);

    if (isKiCard) {
        const colId = board.columns[ci]?.id;

        if (colId === 'ki_archiv') {
            // Im Archiv: nur Reaktivieren anzeigen
            const reactBtn = document.createElement('button');
            reactBtn.className = 'card-btn';
            reactBtn.title = 'Vorschlag reaktivieren → zurück in Backlog';
            reactBtn.textContent = '↩ Reaktivieren';
            reactBtn.style.color = '#9f7aea';
            reactBtn.onclick = e => { e.stopPropagation(); reactivateKiCard(card, reactBtn); };
            footer.insertBefore(reactBtn, editBtn);
        } else {
            // Im Backlog / anderen Spalten: Annehmen + Ablehnen
            const acceptBtn = document.createElement('button');
            acceptBtn.className = 'card-btn';
            acceptBtn.title = 'Vorschlag annehmen → echte Aufgabe';
            acceptBtn.textContent = '✓ Annehmen';
            acceptBtn.style.color = '#68d391';
            acceptBtn.onclick = e => { e.stopPropagation(); acceptKiCard(card, acceptBtn); };

            const rejectBtn = document.createElement('button');
            rejectBtn.className = 'card-btn reject';
            rejectBtn.title = 'KI-Vorschlag ablehnen';
            rejectBtn.textContent = '✗ Ablehnen';
            rejectBtn.onclick = e => {
                e.stopPropagation();
                rejectForm.classList.toggle('open');
            };
            footer.insertBefore(rejectBtn, editBtn);
            footer.insertBefore(acceptBtn, rejectBtn);
        }
    }

    el.appendChild(footer);

    // Swipe-Gesten für KI-Karten anhängen
    if (isKiCard && board.columns[ci]?.id !== 'ki_archiv') {
        attachKiSwipe(el, card, ci);
    }

    return el;
}

function makePlaceholder() {
    const el = document.createElement('div');
    el.className = 'card drag-placeholder';
    el.style.height = '52px';
    return el;
}

// ══════════════════════════════════════════════════════════════
// SPALTEN / KARTEN OPERATIONS
// ══════════════════════════════════════════════════════════════
function addColumn() {
    const title = prompt('Name der neuen Spalte:', 'Neue Spalte');
    if (!title || !title.trim()) return;
    const id = 'col_' + Date.now();
    board.columns.push({ id, title: title.trim(), cards: [] });
    console.log(`[Project] Spalte hinzugefügt: "${title.trim()}"`);
    render();
    autoSave();
}

function deleteColumn(ci) {
    const col = board.columns[ci];
    const cardCount = (col.cards || []).length;
    if (cardCount > 0 && !confirm(`Spalte "${col.title}" mit ${cardCount} Karte(n) löschen?`)) return;
    board.columns.splice(ci, 1);
    console.log(`[Project] Spalte gelöscht: ${ci}`);
    render();
    autoSave();
}

function deleteCard(ci, ki) {
    const card = board.columns[ci].cards[ki];
    if (!confirm(`Karte "${card.title}" löschen?`)) return;
    board.columns[ci].cards.splice(ki, 1);
    console.log(`[Project] Karte gelöscht: Col${ci}[${ki}]`);
    render();
    autoSave();
}

async function acceptKiCard(card, btn) {
    btn.disabled = true; btn.textContent = '…';
    try {
        const resp = await fetch('/ki-accept', {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({ board_id: BOARD_ID, title: card.title }),
        });
        if (!resp.ok) { alert('Fehler: ' + (await resp.json()).error); btn.disabled=false; btn.textContent='✓ Annehmen'; return; }
        console.log(`[KI-Accept] "${card.title}" angenommen`);
        await reloadBoard();
    } catch(e) { alert('Netzwerkfehler: ' + e); btn.disabled=false; btn.textContent='✓ Annehmen'; }
}

async function reactivateKiCard(card, btn) {
    btn.disabled = true; btn.textContent = '…';
    try {
        const resp = await fetch('/ki-reactivate', {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({ board_id: BOARD_ID, title: card.title }),
        });
        if (!resp.ok) { alert('Fehler: ' + (await resp.json()).error); btn.disabled=false; btn.textContent='↩ Reaktivieren'; return; }
        console.log(`[KI-Reactivate] "${card.title}" reaktiviert`);
        await reloadBoard();
    } catch(e) { alert('Netzwerkfehler: ' + e); btn.disabled=false; btn.textContent='↩ Reaktivieren'; }
}

async function rejectKiCard(card, reason, cardEl) {
    console.log(`[KI-Reject] Ablehne: "${card.title}", Grund: "${reason}"`);

    try {
        const resp = await fetch('/ki-reject', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ board_id: BOARD_ID, title: card.title, reason }),
        });

        if (!resp.ok) {
            const err = await resp.json();
            alert('Fehler beim Ablehnen: ' + (err.error || resp.statusText));
            return;
        }

        const data = await resp.json();
        console.log(`[KI-Reject] OK, board neu laden (moved=${data.moved})`);

        // Board vom Server neu laden (Server hat Karte bereits archiviert)
        await reloadBoard();

    } catch(e) {
        console.error('[KI-Reject] Netzwerkfehler:', e);
        alert('Netzwerkfehler: ' + e);
    }
}

// ══════════════════════════════════════════════════════════════
// SWIPE-GESTEN FÜR KI-KARTEN
// ══════════════════════════════════════════════════════════════

const SWIPE_THRESHOLD = 75; // px bis Aktion ausgelöst wird

/**
 * Hängt Swipe-Gesten (Touch + Mouse) an eine KI-Karte.
 * Rechts → acceptKiCard, Links → rejectKiCard (leer) oder Formular zeigen.
 * Komplexes Drag-Handling: dragstart wird gecancelt wenn horizontaler Swipe erkannt.
 */
function attachKiSwipe(el, card, ci) {
    // Swipe-Hint-Overlays einfügen
    const hintR = document.createElement('span');
    hintR.className = 'swipe-hint right'; hintR.textContent = '✓';
    const hintL = document.createElement('span');
    hintL.className = 'swipe-hint left';  hintL.textContent = '✗';
    el.appendChild(hintR);
    el.appendChild(hintL);

    let startX = 0, startY = 0, dx = 0;
    let active = false;
    let intentLocked = false; // verhindert Drag-Drop wenn horizontaler Swipe

    function onStart(x, y) {
        startX = x; startY = y; dx = 0;
        active = true; intentLocked = false;
        el.classList.add('swiping');
        el.style.transform = '';
        el.style.borderColor = '';
        console.log('[Swipe] start x=' + x);
    }

    function onMove(x, y) {
        if (!active) return;
        dx = x - startX;
        const dy = y - startY;

        // Primär vertikales Scrollen → Swipe abbrechen
        if (!intentLocked && Math.abs(dy) > Math.abs(dx) + 10) {
            onCancel(); return;
        }
        intentLocked = true;

        const rotate = dx * 0.04;
        const ratio = Math.min(Math.abs(dx) / SWIPE_THRESHOLD, 1);

        el.style.transform = `translateX(${dx}px) rotate(${rotate}deg)`;

        if (dx > 15) {
            el.style.borderColor = `rgba(104,211,145,${0.4 + ratio * 0.6})`;
            hintR.style.opacity = ratio;
            hintL.style.opacity = 0;
        } else if (dx < -15) {
            el.style.borderColor = `rgba(252,129,129,${0.4 + ratio * 0.6})`;
            hintL.style.opacity = ratio;
            hintR.style.opacity = 0;
        } else {
            el.style.borderColor = '';
            hintR.style.opacity = 0; hintL.style.opacity = 0;
        }
    }

    function onEnd() {
        if (!active) return;
        active = false;
        el.classList.remove('swiping');
        hintR.style.opacity = 0; hintL.style.opacity = 0;

        if (dx > SWIPE_THRESHOLD) {
            console.log('[Swipe] → Annehmen');
            el.classList.add('swipe-out-right');
            // Fake-Button für acceptKiCard
            const fakeBtn = { disabled: false, textContent: '' };
            setTimeout(() => acceptKiCard(card, fakeBtn), 320);

        } else if (dx < -SWIPE_THRESHOLD) {
            console.log('[Swipe] ← Ablehnen');
            // Reject-Formular öffnen statt sofort ablehnen — Nutzer kann Grund ergänzen
            // oder direkt auf "Ohne Grund ablehnen" klicken
            el.style.transform = ''; el.style.borderColor = '';
            const rejectForm = el.querySelector('.reject-form');
            if (rejectForm) {
                rejectForm.classList.add('open');
                // "Ohne Grund ablehnen"-Button einfügen falls noch nicht da
                if (!rejectForm.querySelector('.quick-reject-btn')) {
                    const quickBtn = document.createElement('button');
                    quickBtn.className = 'reject-send quick-reject-btn';
                    quickBtn.textContent = '✗ Ohne Grund ablehnen';
                    quickBtn.style.cssText = 'background:#2d1515;border-color:#4a5568;color:#718096;margin-right:auto';
                    quickBtn.onclick = e => {
                        e.stopPropagation();
                        el.classList.add('swipe-out-left');
                        setTimeout(() => rejectKiCard(card, '', el), 320);
                    };
                    rejectForm.querySelector('.reject-actions').prepend(quickBtn);
                }
                rejectForm.querySelector('.reject-input').focus();
            }

        } else {
            // Snap zurück
            el.style.transition = 'transform 0.3s ease, border-color 0.2s';
            el.style.transform = ''; el.style.borderColor = '';
            setTimeout(() => el.style.transition = '', 300);
        }
    }

    function onCancel() {
        active = false; dx = 0;
        el.classList.remove('swiping');
        el.style.transform = ''; el.style.borderColor = '';
        hintR.style.opacity = 0; hintL.style.opacity = 0;
    }

    // ── Touch ────────────────────────────────────────────────
    el.addEventListener('touchstart', e => {
        onStart(e.touches[0].clientX, e.touches[0].clientY);
    }, { passive: true });
    el.addEventListener('touchmove', e => {
        onMove(e.touches[0].clientX, e.touches[0].clientY);
    }, { passive: true });
    el.addEventListener('touchend', onEnd);
    el.addEventListener('touchcancel', onCancel);

    // ── Mouse (Desktop) ──────────────────────────────────────
    el.addEventListener('mousedown', e => {
        if (e.button !== 0) return;
        onStart(e.clientX, e.clientY);
        const onMM = e => onMove(e.clientX, e.clientY);
        const onMU = () => { onEnd(); document.removeEventListener('mousemove', onMM); document.removeEventListener('mouseup', onMU); };
        document.addEventListener('mousemove', onMM);
        document.addEventListener('mouseup', onMU);
    });

    // Drag-Drop nur wenn kein horizontaler Swipe erkannt
    el.addEventListener('dragstart', e => {
        if (intentLocked) { e.preventDefault(); onCancel(); }
    });
}

// ══════════════════════════════════════════════════════════════
// AUTO-TITEL
// ══════════════════════════════════════════════════════════════

/** POST /title-suggest: Freitext → Kurztitel + Beschreibung via KI. */
async function suggestTitle() {
    const titleEl = document.getElementById('card-input-title');
    const descEl  = document.getElementById('card-input-desc');
    const btn     = document.getElementById('title-suggest-btn');
    const text    = titleEl.value.trim();

    if (!text) {
        titleEl.focus();
        return;
    }

    const model = document.getElementById('model-select').value || 'mistral:latest';
    console.log(`[suggestTitle] model=${model}, text="${text.substring(0, 60)}…"`);

    btn.disabled = true;
    btn.textContent = '⏳…';

    try {
        const data = await API.post('/title-suggest', { text, model });
        console.log(`[suggestTitle] Ergebnis: title="${data.title}"`);

        titleEl.value = data.title || text;
        titleEl.style.height = '';   // reset textarea height
        // Beschreibung nur befüllen wenn noch leer
        if (!descEl.value.trim()) {
            descEl.value = data.desc || text;
        }
        titleEl.focus();
    } catch(e) {
        console.error('[suggestTitle] Fehler:', e);
        alert('Titel-Generierung fehlgeschlagen: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.textContent = '🤖 Titel generieren';
    }
}

// ══════════════════════════════════════════════════════════════
// MODAL
// ══════════════════════════════════════════════════════════════
let modalState = { ci: null, ki: null };

