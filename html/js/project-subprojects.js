// project-subprojects.js — Teil von project.js (aufgeteilt 2026-07-24, Kanban arch_6cb5b87e65).
// Unterprojekte, Board-Picker, Tab-Umschaltung, Rollup
// Klassik-Script, gemeinsamer globaler Scope mit den uebrigen project-*.js — Ladereihenfolge in project.html beachten.
async function loadSubprojects() {
    console.log('[Project] loadSubprojects() parent=' + BOARD_ID);
    try {
        const data = await API.get('/boards?parent=' + encodeURIComponent(BOARD_ID) + '&t=' + Date.now());
        subprojectsData = Array.isArray(data) ? data : (data.boards || []);
        console.log('[Project] Unterprojekte geladen:', subprojectsData.length);
        renderSubprojects();
        renderViewTabs();   // farbige Unterprojekt-Tabs oben aktualisieren (laden parallel zum Board)
    } catch(e) {
        console.error('[Project] Unterprojekte Ladefehler:', e);
        subprojectsData = [];
        renderSubprojects();
    }
}

function renderSubprojects() {
    const listEl = document.getElementById('subprojects-list');
    const labelEl = document.getElementById('subprojects-label');
    listEl.innerHTML = '';

    // Teil 4d: Ein-/Ausklappen (State in localStorage)
    const ckey = 'subprojects_collapsed_' + BOARD_ID;
    const collapsed = localStorage.getItem(ckey) === '1';
    const caret = subprojectsData.length > 0 ? (collapsed ? '▶ ' : '▼ ') : '';
    labelEl.textContent = caret + '📂 Unterprojekte' + (subprojectsData.length > 0 ? ' (' + subprojectsData.length + ')' : '');
    labelEl.style.cursor = subprojectsData.length > 0 ? 'pointer' : 'default';
    labelEl.onclick = () => {
        localStorage.setItem(ckey, localStorage.getItem(ckey) === '1' ? '0' : '1');
        renderSubprojects();
    };
    listEl.style.display = collapsed ? 'none' : '';

    subprojectsData.forEach((sub, idx) => {
        const item = document.createElement('div');
        item.className = 'sub-item';
        item.title = sub.name;

        // Teil 4a: Unterprojekte per Drag&Drop umsortieren -> child_order am Parent
        item.draggable = true;
        item.addEventListener('dragstart', e => {
            dragSubIdx = idx; e.dataTransfer.effectAllowed = 'move'; item.classList.add('sub-dragging');
        });
        item.addEventListener('dragend', () => {
            dragSubIdx = null;
            document.querySelectorAll('.sub-dragging,.sub-drop').forEach(el => el.classList.remove('sub-dragging', 'sub-drop'));
        });
        item.addEventListener('dragover', e => { if (dragSubIdx !== null) { e.preventDefault(); item.classList.add('sub-drop'); } });
        item.addEventListener('dragleave', () => item.classList.remove('sub-drop'));
        item.addEventListener('drop', e => {
            if (dragSubIdx === null) return;
            e.preventDefault(); item.classList.remove('sub-drop');
            let to = idx, from = dragSubIdx;
            if (from === to) return;
            const [moved] = subprojectsData.splice(from, 1);
            if (from < to) to--;
            subprojectsData.splice(to, 0, moved);
            dragSubIdx = null;
            renderSubprojects();
            persistChildOrder();
        });

        const iconEl = document.createElement('div');
        iconEl.className = 'sub-item-icon';
        iconEl.style.background = sub.color || '#2d3748';
        iconEl.textContent = sub.icon || '📋';
        item.appendChild(iconEl);

        const nameEl = document.createElement('div');
        nameEl.className = 'sub-item-name';
        if (sub.seq_id) {
            const badge = document.createElement('span');
            badge.className = 'seq-badge';
            badge.textContent = '#' + String(sub.seq_id).padStart(3, '0');
            nameEl.appendChild(badge);
        }
        nameEl.appendChild(document.createTextNode(sub.name));
        item.appendChild(nameEl);

        const actEl = document.createElement('div');
        actEl.className = 'sub-item-actions';

        const openBtn = document.createElement('button');
        openBtn.className = 'sub-btn';
        openBtn.title = 'Öffnen';
        openBtn.textContent = '↗';
        openBtn.onclick = e => { e.stopPropagation(); window.location.href = '/project.html?id=' + sub.id; };

        // 🔗 Direktlink ins Unterprojekt: lädt dessen Links erst beim Klick (spart N Requests),
        // öffnet Web-App, sonst Code-Ordner, sonst CLAUDE.md.
        const linkBtn = document.createElement('button');
        linkBtn.className = 'sub-btn';
        linkBtn.title = 'Unterprojekt öffnen (Web-App / Dateien)';
        linkBtn.textContent = '🔗';
        linkBtn.onclick = async e => {
            e.stopPropagation();
            try {
                const d = await API.get('/api/project-links?id=' + encodeURIComponent(sub.id));
                const l = (d && d.links) || {};
                const target = l.webapp || l.filebrowser || l.claudemd || l.github;
                if (target) window.open(target, '_blank', 'noopener');
                else alert('Kein Direktlink für „' + sub.name + '" gefunden.');
            } catch(err) {
                console.warn('[Project] Sub-Link Fehler:', err);
                alert('Link konnte nicht geladen werden: ' + err.message);
            }
        };

        // 🗂 Datenordner des Unterprojekts: lädt dessen Links erst beim Klick (wie der 🔗-Knopf),
        // öffnet den data/-Ordner im Filebrowser — oder meldet, wenn das Sub keinen data/ hat.
        const dataBtn = document.createElement('button');
        dataBtn.className = 'sub-btn';
        dataBtn.title = 'Datenordner (data/) des Unterprojekts öffnen';
        dataBtn.textContent = '🗂';
        dataBtn.onclick = async e => {
            e.stopPropagation();
            try {
                const d = await API.get('/api/project-links?id=' + encodeURIComponent(sub.id));
                const target = d && d.links && d.links.datadir;
                if (target) window.open(target, '_blank', 'noopener');
                else alert('„' + sub.name + '" hat keinen Datenordner (data/).');
            } catch(err) {
                console.warn('[Project] Sub-Daten-Link Fehler:', err);
                alert('Datenordner konnte nicht geladen werden: ' + err.message);
            }
        };

        const moveBtn = document.createElement('button');
        moveBtn.className = 'sub-btn';
        moveBtn.title = 'Zu anderem Projekt verschieben';
        moveBtn.textContent = '⤷';
        moveBtn.onclick = e => { e.stopPropagation(); openBoardPicker('move', sub.id, sub.name); };

        const attachBtn = document.createElement('button');
        attachBtn.className = 'sub-btn';
        attachBtn.title = 'An weiteres Projekt anheften';
        attachBtn.textContent = '＋';
        attachBtn.onclick = e => { e.stopPropagation(); openBoardPicker('attach', sub.id, sub.name); };

        actEl.appendChild(openBtn);
        actEl.appendChild(linkBtn);
        actEl.appendChild(dataBtn);
        actEl.appendChild(moveBtn);
        actEl.appendChild(attachBtn);
        item.appendChild(actEl);

        item.onclick = () => { window.location.href = '/project.html?id=' + sub.id; };
        listEl.appendChild(item);
    });
}

async function createSubprojectText() {
    const name = prompt('Name des Unterprojekts:', '');
    if (!name || !name.trim()) return;
    const id = 'sub_' + Date.now();
    console.log('[Project] createSubprojectText(): name=' + name + ' parent_ids=[' + BOARD_ID + ']');
    try {
        await API.createBoard({ id, name: name.trim(), parent_ids: [BOARD_ID] });
        console.log('[Project] Unterprojekt angelegt:', name);
        await loadSubprojects();
    } catch(e) {
        console.error('[Project] Fehler beim Anlegen des Unterprojekts:', e);
        alert('Fehler: ' + e.message);
    }
}

function _compressSubPhoto(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = ev => {
            const img = new Image();
            img.onload = () => {
                const MAX = 1200;
                let w = img.width, h = img.height;
                if (w > MAX || h > MAX) {
                    if (w > h) { h = Math.round(h * MAX / w); w = MAX; }
                    else       { w = Math.round(w * MAX / h); h = MAX; }
                }
                const canvas = document.createElement('canvas');
                canvas.width = w; canvas.height = h;
                canvas.getContext('2d').drawImage(img, 0, 0, w, h);
                resolve(canvas.toDataURL('image/jpeg', 0.82));
            };
            img.onerror = reject;
            img.src = ev.target.result;
        };
        reader.onerror = reject;
        reader.readAsDataURL(file);
    });
}

async function createSubprojectFromPhoto(file) {
    if (!file) return;
    console.log('[Project] createSubprojectFromPhoto():', file.name, file.size, 'parent_id=' + BOARD_ID);
    const overlay = document.getElementById('sub-photo-overlay');
    overlay.classList.add('active');
    try {
        const dataUrl = await _compressSubPhoto(file);
        console.log('[Project] Foto komprimiert, sende an /project-from-photo');
        const data = await API.post('/project-from-photo', { photo: dataUrl, parent_id: BOARD_ID });
        console.log('[Project] Foto-Unterprojekt erstellt:', data.board_id, data.title);
        overlay.classList.remove('active');
        await loadSubprojects();
    } catch(e) {
        console.error('[Project] Fehler bei Foto-Unterprojekt:', e);
        overlay.classList.remove('active');
        alert('Fehler: ' + e.message);
    }
}

// ── Board Picker (verschieben / anheften) ─────────────────────
async function openBoardPicker(mode, subId, subName) {
    pickerState = { mode, subId, subName };
    console.log('[Project] openBoardPicker() mode=' + mode + ' subId=' + subId);

    try {
        const data = await API.get('/boards?all=1&t=' + Date.now());
        allBoardsCache = Array.isArray(data) ? data : (data.boards || []);
        console.log('[Project] Alle Boards geladen:', allBoardsCache.length);
    } catch(e) {
        console.error('[Project] Fehler beim Laden aller Boards:', e);
        allBoardsCache = [];
    }

    const modal = document.getElementById('board-picker-modal');
    const titleEl = document.getElementById('picker-modal-title');
    const listEl = document.getElementById('picker-board-list');

    titleEl.textContent = mode === 'move'
        ? `"${subName}" verschieben zu…`
        : `"${subName}" anheften an…`;

    // Aktuelle Parents des Unterprojekts
    const subEntry = allBoardsCache.find(b => b.id === subId);
    const currentParents = [];
    if (subEntry) {
        const ids = subEntry.parent_ids;
        if (Array.isArray(ids)) currentParents.push(...ids);
        else if (subEntry.parent_id) currentParents.push(subEntry.parent_id);
    }
    console.log('[Project] Board-Picker currentParents:', currentParents);

    // Boards filtern: nicht das Unterprojekt selbst
    let boards = allBoardsCache.filter(b => b.id !== subId);
    if (mode === 'attach') {
        // Bereits zugewiesene Parents ausblenden
        boards = boards.filter(b => !currentParents.includes(b.id));
    }

    listEl.innerHTML = '';
    if (boards.length === 0) {
        listEl.innerHTML = '<div class="board-picker-empty">Keine anderen Projekte verfügbar</div>';
    } else {
        boards.forEach(b => {
            const item = document.createElement('div');
            item.className = 'board-picker-item';
            item.dataset.boardId = b.id;
            item.innerHTML = `<span>${b.icon || '📋'}</span><span>${b.name}</span>`;
            item.onclick = () => {
                listEl.querySelectorAll('.board-picker-item').forEach(i => i.classList.remove('selected'));
                item.classList.add('selected');
            };
            listEl.appendChild(item);
        });
    }

    modal.classList.add('open');
}

async function confirmBoardPicker() {
    const listEl = document.getElementById('picker-board-list');
    const selected = listEl.querySelector('.board-picker-item.selected');
    if (!selected) { alert('Bitte ein Projekt auswählen.'); return; }

    const targetId = selected.dataset.boardId;
    const { mode, subId } = pickerState;
    console.log('[Project] confirmBoardPicker() mode=' + mode + ' subId=' + subId + ' target=' + targetId);

    try {
        const body = mode === 'move'
            ? { parent_ids: [targetId] }
            : { add_parent: targetId };

        await API.patchBoard(subId, body);
        console.log('[Project] Board-Picker Aktion OK:', mode, subId, '→', targetId);
        closeBoardPicker();
        await loadSubprojects();
    } catch(e) {
        console.error('[Project] Board-Picker Fehler:', e);
        alert('Fehler: ' + e.message);
    }
}

function closeBoardPicker() {
    document.getElementById('board-picker-modal').classList.remove('open');
    pickerState = { mode: null, subId: null, subName: '' };
}

// ══════════════════════════════════════════════════════════════
// MOBILE TAB-SWITCHING
// ══════════════════════════════════════════════════════════════
function switchTab(tab) {
    const boardPanel = document.querySelector('.board-panel');
    const brainstormPanel = document.querySelector('.brainstorm-panel');
    const chatPanel  = document.querySelector('.chat-panel');
    const subPanel   = document.querySelector('.subprojects-panel');
    const tabBoard   = document.getElementById('tab-board');
    const tabBrainstorm = document.getElementById('tab-brainstorm');
    const tabChat    = document.getElementById('tab-chat');

    // Debug-Logs für Mobile-Fehlersuche
    console.log('[Mobile] switchTab("' + tab + '") aufgerufen');
    console.log('[Mobile] Elemente vorhanden:', {
        boardPanel: !!boardPanel,
        brainstormPanel: !!brainstormPanel,
        chatPanel: !!chatPanel,
        subPanel: !!subPanel,
        tabBoard: !!tabBoard,
        tabBrainstorm: !!tabBrainstorm,
        tabChat: !!tabChat
    });

    // Null-Check: Elemente müssen existieren
    if (!boardPanel || !brainstormPanel || !chatPanel || !tabBoard || !tabBrainstorm || !tabChat) {
        console.error('[Mobile] switchTab: Ein oder mehrere Elemente fehlen!', {
            boardPanel, brainstormPanel, chatPanel, tabBoard, tabBrainstorm, tabChat
        });
        return;
    }

    // Alle Panels verstecken
    boardPanel.classList.add('tab-hidden');
    brainstormPanel.classList.add('tab-hidden');
    chatPanel.classList.add('tab-hidden');
    if (subPanel) subPanel.classList.add('tab-hidden');

    // Alle Tabs deaktivieren
    tabBoard.classList.remove('active');
    tabBrainstorm.classList.remove('active');
    tabChat.classList.remove('active');

    if (tab === 'board') {
        boardPanel.classList.remove('tab-hidden');
        if (subPanel) subPanel.classList.remove('tab-hidden');
        tabBoard.classList.add('active');
        console.log('[Mobile] ✓ Tab gewechselt → Kanban (boardPanel.tab-hidden entfernt)');
    } else if (tab === 'brainstorm') {
        brainstormPanel.classList.remove('tab-hidden');
        tabBrainstorm.classList.add('active');
        console.log('[Mobile] ✓ Tab gewechselt → Brainstorming');
    } else if (tab === 'chat') {
        chatPanel.classList.remove('tab-hidden');
        tabChat.classList.add('active');
        console.log('[Mobile] ✓ Tab gewechselt → Terminal');
    } else {
        console.warn('[Mobile] switchTab: Unbekannter Tab-Name "' + tab + '"');
    }
}

// ══════════════════════════════════════════════════════════════
// ROLLUP — Alle Karten aus Sub-Boards aggregiert
// ══════════════════════════════════════════════════════════════
let rollupData   = null;
let rollupFilter = 'all';
let rollupOpen   = false;

async function loadRollup() {
    try {
        rollupData = await API.get('/board-rollup?id=' + encodeURIComponent(BOARD_ID) + '&t=' + Date.now());
        const total = (rollupData.cards || []).length;
        document.getElementById('rollup-count').textContent = total ? `(${total})` : '';
        console.log('[Project] Rollup geladen:', total, 'Karten aus', (rollupData.boards||[]).length, 'Boards');
        if (rollupOpen) renderRollup();
        renderProjectHead();   // F1.4: Rollup-Zahl im Kopf aktualisieren
    } catch(e) {
        console.warn('[Project] Rollup Fehler:', e.message);
    }
}

function toggleRollup() {
    rollupOpen = !rollupOpen;
    const panel = document.getElementById('rollup-panel');
    const icon  = document.getElementById('rollup-toggle-icon');
    if (rollupOpen) {
        panel.classList.remove('collapsed');
        icon.textContent = '▼ einklappen';
        if (!rollupData) loadRollup();
        else renderRollup();
    } else {
        panel.classList.add('collapsed');
        icon.textContent = '▶ ausklappen';
    }
}

function renderRollup() {
    if (!rollupData) return;
    const cards   = rollupData.cards   || [];
    const columns = rollupData.columns || [];

    // Filter-Buttons — createElement statt String-Interpolation: col.title/col.id
    // kommen aus fremden Board-JSONs (POST /board, extra="allow") und dürfen nicht
    // ungeprüft in innerHTML/Inline-onclick landen (XSS, Karte opt_xss_esc_0809).
    const filtersEl = document.getElementById('rollup-filters');
    filtersEl.innerHTML = '';
    const allCount = cards.length;
    const btnAll = document.createElement('button');
    btnAll.className = 'rollup-filter-btn' + (rollupFilter === 'all' ? ' active' : '');
    btnAll.textContent = `Alle (${allCount})`;
    btnAll.addEventListener('click', () => setRollupFilter('all'));
    filtersEl.appendChild(btnAll);
    columns.forEach(col => {
        const n = cards.filter(c => c._col_id === col.id).length;
        if (!n) return;
        const btn = document.createElement('button');
        btn.className = 'rollup-filter-btn' + (rollupFilter === col.id ? ' active' : '');
        btn.textContent = `${col.title} (${n})`;
        btn.addEventListener('click', () => setRollupFilter(col.id));
        filtersEl.appendChild(btn);
    });

    // Karten rendern
    const bodyEl = document.getElementById('rollup-body');
    bodyEl.innerHTML = '';
    const filtered = rollupFilter === 'all' ? cards : cards.filter(c => c._col_id === rollupFilter);

    if (!filtered.length) {
        const empty = document.createElement('div');
        empty.className = 'rollup-empty';
        empty.textContent = 'Keine Karten gefunden.';
        bodyEl.appendChild(empty);
        return;
    }

    // Nach Status gruppiert
    const grouped = {};
    filtered.forEach(c => {
        const key = c._col_title || c._col_id || '?';
        if (!grouped[key]) grouped[key] = [];
        grouped[key].push(c);
    });

    Object.entries(grouped).forEach(([colTitle, grpCards]) => {
        const header = document.createElement('div');
        header.style.cssText = 'font-size:0.65rem;color:#4a5568;text-transform:uppercase;letter-spacing:.06em;padding:0.3rem 0 0.1rem';
        header.textContent = colTitle;
        bodyEl.appendChild(header);

        grpCards.forEach(c => {
            const row = document.createElement('div');
            row.className = 'rollup-card';
            row.addEventListener('click', () => { window.location = '/project.html?id=' + encodeURIComponent(c._board_id); });

            // el.style.background ist DOM-Property-Zuweisung, kein Attribut-String — sicher
            // gegen Ausbruch, anders als früher style="background:${c.label}" in innerHTML.
            if (c.label && c.label.startsWith('#')) {
                const lbl = document.createElement('span');
                lbl.className = 'rollup-card-label';
                lbl.style.background = c.label;
                row.appendChild(lbl);
            }

            const title = document.createElement('span');
            title.className = 'rollup-card-title';
            title.textContent = c.title || '?';
            row.appendChild(title);

            const bname = document.createElement('span');
            bname.className = 'rollup-card-board';
            bname.textContent = c._board_name || '';
            row.appendChild(bname);

            bodyEl.appendChild(row);
        });
    });
}

function setRollupFilter(colId) {
    rollupFilter = colId;
    renderRollup();
}

// ══════════════════════════════════════════════════════════════
// PROJEKT-KOPF (F1.4) — Beschreibung, Kategorie, Eisenhower, Stats
// ══════════════════════════════════════════════════════════════
const QUADRANT_META = {
    Q1: { label: 'Q1 · wichtig + dringend', color: '#e5534b' },
    Q2: { label: 'Q2 · wichtig',            color: '#3fb950' },
    Q3: { label: 'Q3 · dringend',           color: '#d29922' },
    Q4: { label: 'Q4 · weder noch',         color: '#6e7681' },
};
let projHeadEntry = null;        // Manifest-Eintrag (aus loadParentBreadcrumb)
let projHeadCategories = null;   // {key: {label, color, emoji}} aus GET /categories
let projHeadStatuses = null;     // {key: {label, color, emoji}} aus GET /statuses
let projHeadIse = null;          // Result von GET /api/priority_widget/item
let projHeadEditorOpen = false;  // Guard: kein Re-Render solange der Editor offen ist
let projHeadColorTimer = null;   // Debounce für <input type=color>

