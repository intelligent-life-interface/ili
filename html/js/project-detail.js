// project-detail.js — Teil von project.js (aufgeteilt 2026-07-24, Kanban arch_6cb5b87e65).
// Detail-Modal, Edit-Modal, Anhaenge, saveCard (schreibt desc+description synchron), Dedup-Check
// Klassik-Script, gemeinsamer globaler Scope mit den uebrigen project-*.js — Ladereihenfolge in project.html beachten.

// URLs aus Karten-Feldern (refs[].url, photo_url) kommen roh aus dem Board-JSON
// (POST /board, Schema extra="allow") — nur http(s)/relative Links durchlassen,
// sonst z.B. javascript:… beim Klick in href/src (Karte opt_xss_esc_0809).
function safeUrl(u) {
    return /^(https?:|\/)/.test(String(u || '')) ? u : '#';
}

function openModal(ci, ki = null) {
    modalState = { ci, ki };
    const card = ki !== null ? board.columns[ci].cards[ki] : null;
    document.getElementById('modal-title').textContent = ki !== null ? 'Karte bearbeiten' : 'Neue Karte';
    document.getElementById('card-input-title').value  = card ? card.title : '';
    document.getElementById('card-input-desc').value   = card ? (card.desc || card.description || '') : '';
    document.getElementById('card-input-input').value  = card ? (card.input || '') : '';
    document.getElementById('card-input-task').value   = card ? (card.task || '') : '';
    document.getElementById('card-input-output').value = card ? (card.output || '') : '';
    document.getElementById('card-input-model').value  = card ? (card.model || '') : '';
    // Schnittstellen-Details aufklappen wenn bereits Daten vorhanden
    const details = document.getElementById('card-interface-details');
    details.open = !!(card && (card.input || card.task || card.output || card.model));

    const picker = document.getElementById('label-picker');
    picker.innerHTML = '';
    LABELS.forEach(lbl => {
        const sw = document.createElement('div');
        sw.className = 'label-swatch' + (lbl.color ? '' : ' none');
        sw.style.background = lbl.color || '#2d3748';
        sw.title = lbl.name;
        sw.dataset.color = lbl.color || '';
        if ((card ? card.label : null) === lbl.color) sw.classList.add('selected');
        sw.onclick = () => {
            picker.querySelectorAll('.label-swatch').forEach(s => s.classList.remove('selected'));
            sw.classList.add('selected');
        };
        picker.appendChild(sw);
    });

    // Anhänge im Bearbeiten-Formular (nur für bereits gespeicherte Karten)
    renderEditAttList();

    document.getElementById('card-modal').classList.add('open');
    setTimeout(() => document.getElementById('card-input-title').focus(), 50);
}

// Anhang-Liste im Bearbeiten-Modal rendern (neue, noch nicht gespeicherte Karte → Hinweis)
function renderEditAttList() {
    const el = document.getElementById('edit-att-list');
    if (!el) return;
    const { ci, ki } = modalState;
    if (ki === null) {
        el.innerHTML = '<div class="att-empty">Karte zuerst speichern — danach Anhänge möglich.</div>';
        return;
    }
    const card = board.columns[ci]?.cards?.[ki];
    el.innerHTML = renderAttList(card?.attachments || [], card?.id || null);
}

// „＋ Datei" im Bearbeiten-Modal: id sicherstellen, dann Datei-Dialog für die Karte
async function addEditCardFiles() {
    const { ci, ki } = modalState;
    if (ki === null) { alert('Bitte die Karte zuerst speichern — danach kannst du Anhänge hinzufügen.'); return; }
    const card = board.columns[ci]?.cards?.[ki];
    if (!card) return;
    if (!card.id) { card.id = genId('c_'); await saveBoard(); }
    pickFiles(card.id);
}

function closeModal() {
    document.getElementById('card-modal').classList.remove('open');
}

// ── Detail-Ansicht (read-only, dynamisch) ──────────────────────────────────
let detailState = { ci: null, ki: null };

function openDetail(ci, ki) {
    const card = board.columns[ci]?.cards?.[ki];
    if (!card) return;
    detailState = { ci, ki };

    const sections = [];

    // Badges: Priorität, Aufwand, Modell
    const badges = [];
    if (card.priority && PRIO_STYLE[card.priority]) {
        const p = PRIO_STYLE[card.priority];
        badges.push(`<span class="dbadge" style="background:${p.bg};color:${p.fg}">⚡ Priorität: ${p.txt}</span>`);
    }
    if (card.effort && PRIO_STYLE[card.effort]) {
        badges.push(`<span class="dbadge" style="background:#2d3748;color:#a0aec0">⏱ Aufwand: ${PRIO_STYLE[card.effort].txt}</span>`);
    }
    if (card.model) badges.push(`<span class="dbadge" style="background:#3d2a60;color:#b794f4">🤖 ${escHtml(card.model)}</span>`);
    if (badges.length) sections.push(`<div class="detail-badges">${badges.join('')}</div>`);

    // Foto
    if (card.photo_url) {
        const photoUrl = escHtml(safeUrl(card.photo_url));
        sections.push(`<a href="${photoUrl}" target="_blank" class="detail-photo-wrap"><img class="detail-photo" src="${photoUrl}" alt="Foto"></a>`);
    }

    // Beschreibung — `desc` (UI-Karten) oder `description` (Sync/KI-Karten), als Markdown gerendert
    const detailBody = card.desc || card.description;
    if (detailBody) {
        console.log(`[Project] openDetail "${card.title}": Beschreibung aus ${card.desc ? 'desc' : 'description'} (${detailBody.length} Zeichen)`);
        sections.push(`<div class="detail-sec"><div class="detail-h">📝 Beschreibung</div><div class="detail-text">${renderMd(detailBody)}</div></div>`);
    }

    // Schnittstellen (Input / Task / Output / Modell)
    const iface = [];
    if (card.input)  iface.push(`<div class="iface-row"><span class="iface-k">📥 Input</span><span class="iface-v">${escHtml(card.input)}</span></div>`);
    if (card.task)   iface.push(`<div class="iface-row"><span class="iface-k">⚙️ Aufgabe</span><span class="iface-v">${escHtml(card.task)}</span></div>`);
    if (card.output) iface.push(`<div class="iface-row"><span class="iface-k">📤 Output</span><span class="iface-v">${escHtml(card.output)}</span></div>`);
    if (iface.length) sections.push(`<div class="detail-sec"><div class="detail-h">🔌 Schnittstellen</div>${iface.join('')}</div>`);

    // Querverweise
    if (card.refs && card.refs.length) {
        const refs = card.refs.map(ref => {
            const href = escHtml(safeUrl(ref.url || ('/project.html?id=' + encodeURIComponent(ref.board_id))));
            const lbl = escHtml(ref.label || ref.board_id);
            const tt = escHtml(ref.card_title ? `→ ${ref.card_title} (${ref.board_id})` : ref.board_id);
            return `<a class="dref" href="${href}" title="${tt}">🔗 ${lbl}</a>`;
        }).join('');
        sections.push(`<div class="detail-sec"><div class="detail-h">🔗 Verknüpfungen</div><div class="detail-refs">${refs}</div></div>`);
    }

    // Anhänge (Karten-Ebene) — immer anzeigen, inkl. Upload-Knopf
    const attList = card.attachments || [];
    sections.push(
        `<div class="detail-sec"><div class="detail-h">📎 Anhänge` +
        `<button class="btn att-add-btn" onclick="addCardFiles()" title="Datei an diese Karte anhängen (→ OneDrive)">＋ Datei</button></div>` +
        `<div class="att-list" id="detail-att-list">${renderAttList(attList, card.id || null)}</div></div>`);

    if (!sections.length) {
        sections.push(`<div class="detail-empty">Keine weiteren Details — über ✏️ Bearbeiten ergänzen.</div>`);
    }

    document.getElementById('detail-title').textContent = card.title || '(ohne Titel)';
    document.getElementById('detail-body').innerHTML = sections.join('');
    document.getElementById('detail-modal').classList.add('open');
}

function closeDetail() {
    document.getElementById('detail-modal').classList.remove('open');
}

function editFromDetail() {
    const { ci, ki } = detailState;
    closeDetail();
    if (ci !== null && ki !== null) openModal(ci, ki);
}

function deleteFromDetail() {
    const { ci, ki } = detailState;
    if (ci === null || ki === null) return;
    closeDetail();
    deleteCard(ci, ki);
}

// ══════════════════════════════════════════════════════════════
// DATEI-ANHÄNGE (Board/Karte → lokal + OneDrive via /api/attachments)
// ══════════════════════════════════════════════════════════════
let attUploadTarget = null;   // cardId (String) für Karten-Anhang, null = Projekt-Anhang
let attPollTimer = null;

// Stabile ID erzeugen (crypto.randomUUID gibt's nur im secure context → Fallback fürs HTTP-Intranet)
function genId(prefix) {
    if (window.crypto && crypto.randomUUID) { try { return prefix + crypto.randomUUID().slice(0, 8); } catch (e) {} }
    return prefix + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

function fmtSize(n) {
    if (n >= 1048576) return (n / 1048576).toFixed(1) + ' MB';
    if (n >= 1024)    return Math.round(n / 1024) + ' KB';
    return (n || 0) + ' B';
}

function attStatusBadge(s) {
    if (s === 'synced')    return '<span class="att-status att-synced" title="In OneDrive synchronisiert">☁︎ OneDrive</span>';
    if (s === 'failed')    return '<span class="att-status att-failed" title="OneDrive-Sync fehlgeschlagen — Datei liegt lokal vor">⚠️ nur lokal</span>';
    return '<span class="att-status att-uploading" title="Wird zu OneDrive hochgeladen…">⏳ lädt…</span>';
}

function renderAttList(list, cardId) {
    if (!list || !list.length) return '<div class="att-empty">Noch keine Anhänge.</div>';
    const cidArg = cardId ? `'${cardId}'` : 'null';
    return list.map(a => {
        if (a.type === 'link') {
            return `<div class="att-row">` +
                `<a class="att-name" href="${escHtml(a.url)}" target="_blank" rel="noopener" title="Link öffnen">🔗 ${escHtml(a.filename || a.url)}</a>` +
                `<span class="att-status" title="Automatisch aus dem Chat erkannt">💬 Chat</span>` +
                `<button class="att-del" title="Link löschen" onclick="deleteAtt('${a.id}', ${cidArg})">🗑</button>` +
            `</div>`;
        }
        const dl = a.download_url + '?board_id=' + encodeURIComponent(BOARD_ID) +
                   (cardId ? '&card_id=' + encodeURIComponent(cardId) : '');
        return `<div class="att-row">` +
            `<a class="att-name" href="${escHtml(dl)}" target="_blank" title="Herunterladen">📄 ${escHtml(a.filename)}</a>` +
            `<span class="att-size">${fmtSize(a.size)}</span>` +
            attStatusBadge(a.status) +
            `<button class="att-del" title="Anhang löschen" onclick="deleteAtt('${a.id}', ${cidArg})">🗑</button>` +
        `</div>`;
    }).join('');
}

// ── Datei-Auswahl auslösen ───────────────────────────────────
function pickFiles(cardId) {
    attUploadTarget = cardId || null;
    const inp = document.getElementById('att-file-input');
    inp.value = '';
    inp.click();
}

// „＋ Datei" im Detail-Modal: sicherstellen, dass die Karte eine id hat (sonst
// findet das Backend sie nicht), dann Datei-Dialog für genau diese Karte öffnen.
async function addCardFiles() {
    const { ci, ki } = detailState;
    const card = board.columns[ci]?.cards?.[ki];
    if (!card) return;
    if (!card.id) {
        card.id = genId('c_');
        console.log('[Project] Karte ohne id → neue id vergeben:', card.id);
        await saveBoard();   // id persistieren, damit der Upload sie referenzieren kann
    }
    pickFiles(card.id);
}

async function handleAttFiles() {
    const inp = document.getElementById('att-file-input');
    const files = Array.from(inp.files || []);
    if (!files.length) return;
    const cardId = attUploadTarget;
    setSaveStatus('⬆️ Lade ' + files.length + ' Datei(en) hoch…', '');
    for (const f of files) {
        if (f.size > 100 * 1024 * 1024) { alert(`"${f.name}" ist grösser als 100 MB und wird übersprungen.`); continue; }
        try {
            const fd = new FormData();
            fd.append('file', f);
            fd.append('board_id', BOARD_ID);
            if (cardId) fd.append('card_id', cardId);
            const res = await fetch('/api/attachments', { method: 'POST', body: fd });
            if (!res.ok) {
                let msg = 'HTTP ' + res.status;
                try { const j = await res.json(); msg = j.detail || j.error || msg; } catch (e) {}
                throw new Error(msg);
            }
            console.log('[Project] Anhang hochgeladen:', f.name, '→ card=' + (cardId || '-'));
        } catch (e) {
            console.error('[Project] Upload-Fehler:', e);
            alert(`Upload von "${f.name}" fehlgeschlagen: ${e.message}`);
        }
    }
    inp.value = '';
    await loadBoard(true);     // rev + attachments aktualisieren (Server hat geschrieben)
    refreshAttViews();
    setSaveStatus('✅ Hochgeladen', 'ok');
    setTimeout(() => setSaveStatus('', ''), 2000);
    startAttPoll();            // OneDrive-Sync-Status nachführen
}

async function deleteAtt(attId, cardId) {
    if (!confirm('Diesen Anhang löschen (lokal und in OneDrive)?')) return;
    try {
        const url = '/api/attachments/' + encodeURIComponent(attId) +
                    '?board_id=' + encodeURIComponent(BOARD_ID) +
                    (cardId ? '&card_id=' + encodeURIComponent(cardId) : '');
        const res = await fetch(url, { method: 'DELETE' });
        if (!res.ok) throw new Error('HTTP ' + res.status);
    } catch (e) {
        console.error('[Project] Löschfehler:', e);
        alert('Löschen fehlgeschlagen: ' + e.message);
        return;
    }
    await loadBoard(true);
    refreshAttViews();
}

// Sync-Status nachführen: Board still nachladen bis kein Anhang mehr 'uploading' ist.
function startAttPoll() {
    clearTimeout(attPollTimer);
    let tries = 0;
    const anyUploading = () =>
        (board.attachments || []).some(a => a.status === 'uploading') ||
        (board.columns || []).some(c => (c.cards || []).some(cd => (cd.attachments || []).some(a => a.status === 'uploading')));
    const tick = async () => {
        tries++;
        await loadBoard(true);
        refreshAttViews();
        if (anyUploading() && tries < 20) attPollTimer = setTimeout(tick, 2500);
    };
    attPollTimer = setTimeout(tick, 2500);
}

// Offene Anhang-Ansichten neu rendern (Projekt-Modal und/oder Karten-Detail).
function refreshAttViews() {
    updateAttProjCount();
    const attModal = document.getElementById('att-modal');
    if (attModal && attModal.classList.contains('open')) {
        document.getElementById('att-modal-list').innerHTML = renderAttList(board.attachments || [], null);
    }
    const detail = document.getElementById('detail-modal');
    if (detail && detail.classList.contains('open') && detailState.ci !== null && detailState.ki !== null) {
        const card = board.columns[detailState.ci]?.cards?.[detailState.ki];
        const el = document.getElementById('detail-att-list');
        if (card && el) el.innerHTML = renderAttList(card.attachments || [], card.id || null);
    }
    const editModal = document.getElementById('card-modal');
    if (editModal && editModal.classList.contains('open')) {
        renderEditAttList();
    }
    render();   // Karten-Indikatoren (📎N) aktualisieren
}

function updateAttProjCount() {
    const el = document.getElementById('att-proj-count');
    if (!el) return;
    const n = (board.attachments || []).length;
    el.textContent = n ? '(' + n + ')' : '';
}

function openAttModal() {
    document.getElementById('att-modal-list').innerHTML = renderAttList(board.attachments || [], null);
    document.getElementById('att-modal').classList.add('open');
}
function closeAttModal() {
    document.getElementById('att-modal').classList.remove('open');
}

// Dedup-Steuerung: _dedupSkip überspringt den Check (Nutzer hat "trotzdem anlegen" gewählt),
// _pendingNew hält die noch nicht angelegte neue Karte während der Warnung.
let _dedupSkip = false;
let _pendingNew = null;

async function saveCard() {
    const rawTitle = document.getElementById('card-input-title').value.trim();
    if (!rawTitle) { document.getElementById('card-input-title').focus(); return; }
    // Sicherheits-Kürzen falls KI nicht aufgerufen wurde und langer Text im Titel steht
    const title = rawTitle.length > 120 ? rawTitle.substring(0, 117) + '…' : rawTitle;
    if (!title) { document.getElementById('card-input-title').focus(); return; }
    const desc   = document.getElementById('card-input-desc').value.trim();
    const input  = document.getElementById('card-input-input').value.trim();
    const task   = document.getElementById('card-input-task').value.trim();
    const output = document.getElementById('card-input-output').value.trim();
    const model  = document.getElementById('card-input-model').value || null;
    const selected = document.querySelector('#label-picker .label-swatch.selected');
    const label = selected ? (selected.dataset.color || null) : null;

    const { ci, ki } = modalState;
    const existing = ki !== null ? board.columns[ci].cards[ki] : null;
    // Bestehende Felder erhalten (id, priority, effort, refs, status, photo_url …),
    // nur die im Formular editierbaren überschreiben.
    // desc + description synchron halten: Backends/Mobile lesen teils nur eines der Felder
    const card = { ...(existing || {}), title, desc: desc || '', description: desc || '', label };
    card.input  = input  || undefined;
    card.task   = task   || undefined;
    card.output = output || undefined;
    card.model  = model  || undefined;

    if (ki !== null) {
        board.columns[ci].cards[ki] = card;
        console.log(`[Project] Karte bearbeitet: Col${ci}[${ki}]`);
        closeModal();
        render();
        autoSave();
        return;
    }

    // NEUE Karte: vor dem Anlegen auf Duplikate prüfen (überspringbar via _dedupSkip).
    if (!_dedupSkip) {
        const dups = await checkDuplicates(card.title, card.desc);
        if (dups.length) {
            console.log(`[Project] Dedup: ${dups.length} mögliche(s) Duplikat(e) für "${card.title}"`);
            _pendingNew = { card, ci };
            showDedupWarning(dups);
            return;   // card-modal bleibt offen; Nutzer entscheidet im Warn-Dialog
        }
    }
    _dedupSkip = false;
    commitNewCard(card, ci);
}

// Neue Karte tatsächlich ins Board übernehmen.
function commitNewCard(card, ci) {
    board.columns[ci].cards.push(card);
    console.log(`[Project] Karte hinzugefügt: Col${ci}[${board.columns[ci].cards.length - 1}]`);
    closeModal();
    render();
    autoSave();
}

// Dedup-Check gegen den Server (POST /dedup-check). Fehler blockieren das Anlegen NIE.
async function checkDuplicates(title, desc) {
    try {
        const res = await API.post('/dedup-check', { board_id: BOARD_ID, title, desc: desc || '' });
        return (res && res.duplicates) || [];
    } catch (e) {
        console.warn('[Project] Dedup-Check nicht möglich (ignoriert):', e.message);
        return [];
    }
}

// Warn-Dialog mit den gefundenen Duplikaten + Verknüpfen/Trotzdem/Abbrechen.
function showDedupWarning(dups) {
    closeDedupWarning();
    const items = dups.map(d => {
        const t = escHtml(d.title);
        const col = escHtml(d.column || '');
        const why = escHtml(d.reason || '');
        return `<div class="dedup-item">
            <div class="dedup-it-head"><span class="dedup-it-title">${t}</span>
                <span class="dedup-it-col">${col}</span></div>
            ${why ? `<div class="dedup-it-why">${why}</div>` : ''}
            <button class="btn dedup-link-btn"
                onclick="linkToExisting('${encodeURIComponent(d.id)}', '${encodeURIComponent(d.title)}')">
                🔗 Mit dieser Karte verknüpfen</button>
        </div>`;
    }).join('');
    const el = document.createElement('div');
    el.id = 'dedup-modal';
    el.className = 'dedup-overlay';
    el.innerHTML = `<div class="dedup-box">
        <div class="dedup-head">⚠️ Ähnliche Karte${dups.length > 1 ? 'n' : ''} gefunden</div>
        <div class="dedup-sub">Diese offene${dups.length > 1 ? 'n' : ''} Karte${dups.length > 1 ? 'n scheinen' : ' scheint'} dasselbe Anliegen zu beschreiben:</div>
        <div class="dedup-list">${items}</div>
        <div class="dedup-actions">
            <button class="btn" onclick="proceedNewAnyway()">Trotzdem neu anlegen</button>
            <button class="btn btn-primary" onclick="closeDedupWarning()">Abbrechen</button>
        </div></div>`;
    document.body.appendChild(el);
}

function closeDedupWarning() {
    const el = document.getElementById('dedup-modal');
    if (el) el.remove();
}

// "Trotzdem neu anlegen": Check einmalig überspringen und die Karte committen.
function proceedNewAnyway() {
    closeDedupWarning();
    if (!_pendingNew) return;
    const { card, ci } = _pendingNew;
    _pendingNew = null;
    commitNewCard(card, ci);
}

// Neue Karte NICHT anlegen, sondern bidirektional mit der bestehenden Karte verknüpfen.
function linkToExisting(existingIdEnc, existingTitleEnc) {
    const existingId = decodeURIComponent(existingIdEnc);
    const existingTitle = decodeURIComponent(existingTitleEnc);
    closeDedupWarning();
    if (!_pendingNew) return;
    const { card } = _pendingNew;
    _pendingNew = null;

    // Die bestehende Karte im Board finden (über die id).
    let target = null;
    for (const col of board.columns) {
        for (const c of (col.cards || [])) { if (c.id === existingId) { target = c; break; } }
        if (target) break;
    }
    if (!target) { console.warn('[Project] Ziel-Karte nicht gefunden:', existingId); alert('Karte nicht gefunden.'); return; }

    // Statt einer Dublette: einen Querverweis auf der BESTEHENDEN Karte ergänzen.
    // Trägt den (verworfenen) neuen Titel als Hinweis bei, damit der Wunsch nicht verloren geht.
    target.refs = target.refs || [];
    const lbl = card.title.length > 40 ? card.title.slice(0, 39) + '…' : card.title;
    if (!target.refs.some(r => r.note === card.title && r.board_id === BOARD_ID)) {
        target.refs.push({ board_id: BOARD_ID, card_id: target.id, card_title: target.title,
                           label: 'Auch gewünscht: ' + lbl, note: card.title });
    }
    console.log(`[Project] Neue Karte mit bestehender "${existingTitle}" verknüpft statt doppelt angelegt.`);
    closeModal();
    render();
    autoSave();
}

// ══════════════════════════════════════════════════════════════
// MODELL-LISTE LADEN
// ══════════════════════════════════════════════════════════════
