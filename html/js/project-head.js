// project-head.js — Teil von project.js (aufgeteilt 2026-07-24, Kanban arch_6cb5b87e65).
// Projekt-Kopf (Beschreibung/Kategorie/Status/Icon/Priority Widget) + Init-Bootstrap am Ende
// Klassik-Script, gemeinsamer globaler Scope mit den uebrigen project-*.js — Ladereihenfolge in project.html beachten.
// Projekt-Prioritaet = Manifest-Feld `eisenhower` (q1..q4 | ""), identisch mit dem,
// was die Projekt-Uebersicht (index.js) anzeigt und wonach sie sortiert. Labels/Emojis
// bewusst gleich wie dort, damit Uebersicht und Projekt dasselbe sagen.
const PROJ_EIS_META = {
    q1: { emoji: '🔴', short: 'Prio 1', label: 'Dringend & wichtig',         color: '#f85149' },
    q2: { emoji: '🟡', short: 'Prio 2', label: 'Dringend oder wichtig',      color: '#d29922' },
    q3: { emoji: '🟢', short: 'Prio 3', label: 'Unwichtig & nicht dringend', color: '#3fb950' },
    q4: { emoji: '⚫', short: 'Prio 4', label: 'Nicht umsetzen',             color: '#6e7681' }
};

function projHeadIsOpen() { return localStorage.getItem('projhead-open') === '1'; }
function toggleProjHead() {
    localStorage.setItem('projhead-open', projHeadIsOpen() ? '0' : '1');
    renderProjectHead();
}

// Mini-Markdown: IMMER zuerst HTML-escapen (XSS), dann simple Auszeichnung.
function renderMd(md) {
    const esc = escHtmlRel(md || '');
    const lines = esc.split('\n');
    const out = [];
    let inList = false;
    for (const line of lines) {
        let l = line
            .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
            .replace(/`([^`]+)`/g, '<code>$1</code>')
            .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
        const li = l.match(/^\s*[-*]\s+(.*)$/);
        if (li) {
            if (!inList) { out.push('<ul>'); inList = true; }
            out.push('<li>' + li[1] + '</li>');
            continue;
        }
        if (inList) { out.push('</ul>'); inList = false; }
        const h = l.match(/^(#{1,4})\s+(.*)$/);
        if (h) { const lv = Math.min(h[1].length + 2, 6); out.push(`<h${lv}>${h[2]}</h${lv}>`); continue; }
        if (l.trim() === '') { out.push('<div class="md-gap"></div>'); continue; }
        out.push('<p>' + l + '</p>');
    }
    if (inList) out.push('</ul>');
    return out.join('');
}

function _projHeadStats() {
    const count = id => {
        const col = (board?.columns || []).find(c => c.id === id);
        return (col?.cards || []).length;
    };
    const inArbeit = count('inprogress') + count('review');
    // Rollup-Zahl: claudemd-Beschreibungskarten der Sub-Boards nicht mitzählen
    const rollup = rollupData
        ? (rollupData.cards || []).filter(c => c.id !== CLAUDE_MD_CARD_ID).length
        : null;
    return { backlog: count('backlog'), inArbeit, done: count('done'), rollup };
}

function _projHeadGithubUrl() {
    const text = (claudeCard?.description || '') + ' ' + (projHeadEntry?.description || '');
    let m = text.match(/https?:\/\/github\.com\/[\w.\-]+\/[\w.\-]+/);
    if (m) return m[0];
    m = text.match(/\bgithub\.com\/([\w.\-]+\/[\w.\-]+)/i);
    if (m) return 'https://github.com/' + m[1];
    return null;
}

function renderProjectHead() {
    const root = document.getElementById('project-head');
    if (!root) return;
    if (projHeadEditorOpen) { console.log('[Project] renderProjectHead: Editor offen — Re-Render übersprungen'); return; }
    if (!board) return;

    const entry = projHeadEntry || {};
    const cats = projHeadCategories || {};
    const cat = cats[entry.category];
    const statuses = projHeadStatuses || {};
    const stat = statuses[entry.status];
    const item = projHeadIse?.item;
    const stats = _projHeadStats();
    const open = projHeadIsOpen();

    // ── Kollabierte Leiste ──
    const quad = item?.quadrant && QUADRANT_META[item.quadrant];
    const quadBadge = projHeadIse?.available
        ? (quad
            ? `<span class="ph-badge" style="background:${quad.color}">${quad.label}</span>`
            : `<span class="ph-badge ph-badge-inbox">Eingang</span>`)
        : '';
    const catBadge = cat
        ? `<span class="ph-badge" style="background:${cat.color}33;border:1px solid ${cat.color};color:${cat.color}">${cat.emoji} ${escHtmlRel(cat.label)}</span>`
        : '';
    const statusBadge = stat
        ? `<span class="ph-badge" style="background:${stat.color}33;border:1px solid ${stat.color};color:${stat.color}">${stat.emoji} ${escHtmlRel(stat.label)}</span>`
        : '';
    // Automat pausiert/archivierte Projekte immer still (siehe kanban-automat/automat_lib.py
    // PAUSED_STATUSES), egal ob `auto` an ist. Ohne diese Warnung merkt man nicht, warum
    // ein Board mit Auto-Entwicklung=an trotzdem nie bearbeitet wird.
    const autoStatusWarn = (entry.auto && ['pausiert', 'archiviert'].includes(entry.status))
        ? `<span class="ph-badge" style="background:#f6ad5533;border:1px solid #f6ad55;color:#f6ad55"
                 title="Auto-Entwicklung ist an, aber der Automat bearbeitet pausierte/archivierte Projekte nie — er überspringt dieses Board still. Status zurücksetzen oder Auto-Entwicklung ausschalten.">⚠️ Automat inaktiv (Status)</span>`
        : '';
    // Projekt-Prioritaet = Manifest-Feld `eisenhower` (q1..q4) — dasselbe, was die
    // Projekt-Uebersicht anzeigt/sortiert. NICHT zu verwechseln mit der Priority Widget-
    // Wochenplanung unten (eigener Service, eigene Q1..Q4-Logik).
    const eisKey = entry.eisenhower || '';
    const eisMeta = PROJ_EIS_META[eisKey];
    const prioBadge = eisMeta
        ? `<span class="ph-badge" style="background:${eisMeta.color}33;border:1px solid ${eisMeta.color};color:${eisMeta.color}"
                 title="Projekt-Priorität: ${escHtmlRel(eisMeta.label)}">${eisMeta.emoji} ${escHtmlRel(eisMeta.short)}</span>`
        : '';
    const frog = item?.frog_date ? `<span title="Frosch am ${escHtmlRel(item.frog_date)}">🐸</span>` : '';
    const star = item?.pareto ? '<span title="Pareto-Hebel">⭐</span>' : '';
    const statsHtml = `<span class="ph-stats">📥 ${stats.backlog} · 🔧 ${stats.inArbeit} · ✅ ${stats.done}` +
        (stats.rollup !== null ? ` · Σ ${stats.rollup}` : '') + `</span>`;

    let html = `<div class="ph-bar" onclick="toggleProjHead()">
        <span class="ph-toggle">${open ? '▾' : '▸'}</span>
        <span class="ph-icon">${escHtmlRel(entry.icon || '📋')}</span>
        <span class="ph-name">${escHtmlRel(entry.name || board.title || BOARD_ID)}</span>
        ${prioBadge} ${catBadge} ${statusBadge} ${autoStatusWarn} ${quadBadge} ${frog} ${star} ${statsHtml}
    </div>`;

    // ── Offener Bereich ──
    if (open) {
        const subtitle = entry.description
            ? `<div class="ph-subtitle">🤖 ${escHtmlRel(entry.description)}</div>` : '';
        const mdHtml = claudeCard
            ? renderMd(claudeCard.description)
            : '<p class="ph-empty">Keine Beschreibung — mit ✏️ anlegen.</p>';
        const tags = (entry.tags || []).map(t => `<span class="ph-tag">${escHtmlRel(t)}</span>`).join('');
        const dates = (entry.created_at || entry.updated_at)
            ? `<span class="ph-dates">${entry.created_at ? '📅 ' + escHtmlRel(String(entry.created_at).slice(0, 10)) : ''}` +
              `${entry.updated_at ? ' · ✏️ ' + escHtmlRel(String(entry.updated_at).slice(0, 10)) : ''}</span>` : '';
        // Eltern-Links mit Icon + Klartext-Namen (aus allBoardsCache aufgelöst);
        // ist der Parent gelöscht, bleibt die rohe ID mit Warn-Markierung stehen.
        const parents = ((entry.parent_ids || (entry.parent_id ? [entry.parent_id] : []))).map(pid => {
            const p = allBoardsCache.find(b => b.id === pid);
            const label = p ? `${p.icon || '📋'} ${p.name || pid}` : `⚠️ ${pid}`;
            const cls = p ? 'ph-parent' : 'ph-parent ph-parent-broken';
            const ttl = p ? `Zum Mutterprojekt „${p.name || pid}"` : `Mutterprojekt „${pid}" existiert nicht mehr`;
            return `<a class="${cls}" title="${escHtmlRel(ttl)}" href="/project.html?id=${encodeURIComponent(pid)}">↰ ${escHtmlRel(label)}</a>`;
        }).join(' ');
        const gh = _projHeadGithubUrl();
        const ghLink = gh ? `<a class="ph-github" href="${escHtmlRel(gh)}" target="_blank" rel="noopener">🐙 GitHub</a>` : '';

        // Kategorie-Picker aus /categories
        const catOptions = ['<option value="">— Kategorie —</option>'].concat(
            Object.entries(cats).map(([key, c]) =>
                `<option value="${escHtmlRel(key)}" ${key === entry.category ? 'selected' : ''}>${c.emoji} ${escHtmlRel(c.label)}</option>`)
        ).join('');

        // Status-Picker aus /statuses (Lebenszyklus, orthogonal zur Kategorie)
        const statusOptions = ['<option value="">— Status —</option>'].concat(
            Object.entries(statuses).map(([key, s]) =>
                `<option value="${escHtmlRel(key)}" ${key === entry.status ? 'selected' : ''}>${s.emoji} ${escHtmlRel(s.label)}</option>`)
        ).join('');

        // Prioritaets-Picker fuer das Manifest-Feld `eisenhower` — bisher nur per
        // Drag&Drop im Priorisieren-Modus der Uebersicht setzbar, jetzt auch hier.
        const prioOptions = ['<option value="">— Priorität —</option>'].concat(
            Object.entries(PROJ_EIS_META).map(([key, m]) =>
                `<option value="${escHtmlRel(key)}" ${key === eisKey ? 'selected' : ''}>${m.emoji} ${escHtmlRel(m.label)}</option>`)
        ).join('');

        // Priority Widget-Sektion (nur wenn erreichbar)
        let iseHtml = '';
        if (projHeadIse?.available) {
            const qBtn = (q, lbl, title) => {
                const active = item?.quadrant === q;
                const meta = QUADRANT_META[q];
                return `<button class="ph-qbtn ${active ? 'active' : ''}" style="--qc:${meta.color}" title="${title}"
                         onclick="setPriority Widget({quadrant:'${q}'})">${lbl}</button>`;
            };
            iseHtml = `<div class="ph-section ph-pp">
                <span class="ph-section-label">🗓️ Priorität (${escHtmlRel(projHeadIse.week || '')})</span>
                ${qBtn('Q1', 'w+d', 'Q1: wichtig + dringend')}
                ${qBtn('Q2', 'w−', 'Q2: wichtig, nicht dringend')}
                ${qBtn('Q3', '−d', 'Q3: dringend, nicht wichtig')}
                ${qBtn('Q4', '−−', 'Q4: weder noch')}
                <button class="ph-qbtn ${item?.frog_date ? 'active' : ''}" style="--qc:#3fb950" title="Frosch heute (wichtigste Aufgabe des Tages)"
                        onclick="togglePriority WidgetFrog()">🐸</button>
                <button class="ph-qbtn ${item?.pareto ? 'active' : ''}" style="--qc:#d29922" title="Pareto-Hebel (80/20)"
                        onclick="setPriority Widget({pareto:${item?.pareto ? 'false' : 'true'}})">⭐</button>
                <button class="ph-qbtn" style="--qc:#6e7681" title="Zurück in den Eingang (unsortiert)"
                        onclick="setPriority Widget({clear_quadrant:true})">→ Eingang</button>
            </div>`;
        }

        html += `<div class="ph-body" id="ph-body">
            ${subtitle}
            <div class="ph-md" id="ph-md">${mdHtml}</div>
            <div class="ph-md-actions"><button class="ph-btn" onclick="openProjHeadEditor()">✏️ Beschreibung bearbeiten</button></div>
            ${iseHtml}
            <div class="ph-section ph-meta-row">
                <select id="ph-cat-select" onchange="setProjCategory(this.value)">${catOptions}</select>
                <select id="ph-status-select" onchange="setProjStatus(this.value)">${statusOptions}</select>
                <select id="ph-prio-select" title="Projekt-Priorität (wie in der Projekt-Übersicht)"
                        onchange="setProjPrio(this.value)">${prioOptions}</select>
                <input type="color" id="ph-color" value="${escHtmlRel(entry.color || '#4a90e2')}" title="Projektfarbe"
                       oninput="setProjColorDebounced(this.value)">
                <input type="text" id="ph-icon" class="ph-icon-input" value="${escHtmlRel(entry.icon || '')}"
                       placeholder="📋" maxlength="4" title="Icon (Emoji)" onchange="setProjIcon(this.value)">
                ${ghLink} ${parents} ${dates}
            </div>
            ${tags ? `<div class="ph-section ph-tags">${tags}</div>` : ''}
        </div>`;
    }

    root.innerHTML = html;
    adjustBoardHeight();   // Board-Höhe nachführen (Kopf-Leiste/Badges können umbrechen)
}

// Board-Bereich (.main-split) auf eine FESTE Höhe setzen = Viewport minus der
// immer sichtbaren Chrome oben (Header/Nav/View-Tabs + Kopf-LEISTE, NICHT die
// aufgeklappte Beschreibung). Dadurch behält das Board immer seine "zugeklappte"
// Höhe; das Aufklappen der Beschreibung schiebt es nur nach unten und die Seite
// scrollt, statt das Board zu stauchen. Mobile (≤768px) bleibt bei der Tab-Logik.
function adjustBoardHeight() {
    const split = document.querySelector('.main-split');
    if (!split) return;
    if (window.matchMedia('(max-width: 768px)').matches) {
        split.style.height = '';   // Mobile: Media-Query regelt das Layout
        return;
    }
    const h = el => el ? el.getBoundingClientRect().height : 0;
    const phEl = document.getElementById('project-head');
    let phMargin = 0;
    if (phEl) {
        const cs = getComputedStyle(phEl);
        phMargin = (parseFloat(cs.marginTop) || 0) + (parseFloat(cs.marginBottom) || 0);
    }
    // 'nav' matcht die zentrale /nav.js-Leiste (.ds-nav); .proj-bar = schmale
    // Projekt-Zeile (ersetzt den früheren header, 2026-07-07). #project-links
    // fehlte hier bisher -> Seite war um dessen Höhe zu hoch und scrollte.
    // .subprojects-panel liegt (seit b979d41) als Sibling UNTER .main-split (volle
    // Seitenbreite). Seine Höhe muss abgezogen werden, sonst wird die Seite genau um
    // diese Höhe zu hoch und das Terminal (unterstes Element rechts) unten abgeschnitten.
    const chrome = h(document.querySelector('.proj-bar'))
                 + h(document.querySelector('nav'))
                 + h(document.getElementById('view-tabs'))
                 + h(document.getElementById('project-links'))
                 + h(document.querySelector('#project-head .ph-bar'))
                 + h(document.querySelector('.subprojects-panel'))
                 + phMargin;
    const target = Math.max(260, Math.round(window.innerHeight - chrome));
    if (split.style.height !== target + 'px') {
        split.style.height = target + 'px';
        console.log('[Project] adjustBoardHeight: chrome=' + Math.round(chrome) + 'px → board=' + target + 'px');
    }
}

// ── Inline-Editor für die Beschreibung (claudemd-Karte) ──
function openProjHeadEditor() {
    const mdEl = document.getElementById('ph-md');
    if (!mdEl) return;
    projHeadEditorOpen = true;
    const cur = claudeCard?.description || '';
    mdEl.innerHTML = `<textarea id="ph-editor" class="ph-editor"></textarea>
        <div class="ph-md-actions">
            <button class="ph-btn" onclick="saveProjHeadDesc()">💾 Speichern</button>
            <button class="ph-btn" onclick="cancelProjHeadEditor()">✖ Abbrechen</button>
        </div>`;
    const ta = document.getElementById('ph-editor');
    ta.value = cur;
    ta.focus();
    console.log('[Project] Beschreibungs-Editor geöffnet (' + cur.length + ' Zeichen)');
}

function saveProjHeadDesc() {
    const ta = document.getElementById('ph-editor');
    if (!ta) return;
    const text = ta.value;
    if (!claudeCard) {
        claudeCard = { id: CLAUDE_MD_CARD_ID, title: '📋 Beschreibung', description: text };
        claudeCardColId = 'backlog';
        console.log('[Project] Neue Beschreibungskarte angelegt');
    } else {
        claudeCard.description = text;
    }
    projHeadEditorOpen = false;
    renderProjectHead();
    saveBoard();   // re-injiziert die Karte via buildSavePayload → CLAUDE.md-Sync läuft serverseitig
    console.log('[Project] Beschreibung gespeichert (' + text.length + ' Zeichen)');
}

function cancelProjHeadEditor() {
    projHeadEditorOpen = false;
    renderProjectHead();
}

// ── Priority Widget-Aktionen ──
async function loadPriority Widget() {
    try {
        projHeadIse = await API.get('/api/priority_widget/item?project=' + encodeURIComponent(BOARD_ID) + '&t=' + Date.now());
        console.log('[Project] Priority Widget:', JSON.stringify(projHeadIse));
    } catch (e) {
        console.warn('[Project] Priority Widget nicht erreichbar:', e.message);
        projHeadIse = { available: false };
    }
    renderProjectHead();
}

async function setPriority Widget(fields) {
    console.log('[Project] setPriority Widget:', JSON.stringify(fields));
    try {
        const body = Object.assign({ project: BOARD_ID }, fields);
        projHeadIse = await API.patch('/api/priority_widget/item', body);
        setSaveStatus('✅ Priorität gesetzt', 'ok');
        setTimeout(() => setSaveStatus('', ''), 2000);
    } catch (e) {
        console.error('[Project] Priority Widget-Fehler:', e);
        setSaveStatus('❌ Priority Widget: ' + e.message, 'err');
    }
    renderProjectHead();
}

function togglePriority WidgetFrog() {
    const item = projHeadIse?.item;
    if (item?.frog_date) setPriority Widget({ clear_frog: true });
    else setPriority Widget({ frog_date: new Date().toISOString().slice(0, 10) });
}

// ── Manifest-Aktionen (Kategorie / Status / Farbe / Icon) ──
async function setProjCategory(key) {
    console.log('[Project] setProjCategory:', key);
    try {
        const res = await API.patchBoard(BOARD_ID, { category: key });
        if (res?.entry) projHeadEntry = res.entry;   // enthält Auto-Farbe der Kategorie
        renderProjectHead();
    } catch (e) {
        console.error('[Project] Kategorie-Fehler:', e);
        setSaveStatus('❌ ' + e.message, 'err');
    }
}

async function setProjStatus(key) {
    console.log('[Project] setProjStatus:', key);
    try {
        const res = await API.patchBoard(BOARD_ID, { status: key });
        if (res?.entry) projHeadEntry = res.entry;
        renderProjectHead();
    } catch (e) {
        console.error('[Project] Status-Fehler:', e);
        setSaveStatus('❌ ' + e.message, 'err');
    }
}

// Projekt-Prioritaet setzen (Manifest `eisenhower`) — wirkt sofort in der Uebersicht,
// weil die dieselbe Quelle liest. "" = zurueck auf "nicht einsortiert".
async function setProjPrio(key) {
    console.log('[Project] setProjPrio:', BOARD_ID, '→', key || '(leer)');
    try {
        const res = await API.patchBoard(BOARD_ID, { eisenhower: key });
        if (res?.entry) projHeadEntry = res.entry;
        else projHeadEntry = { ...(projHeadEntry || {}), eisenhower: key };
        renderProjectHead();
        setSaveStatus('✅ Priorität gespeichert', 'ok');
        setTimeout(() => setSaveStatus('', ''), 2000);
    } catch (e) {
        console.error('[Project] Prioritaets-Fehler:', e);
        setSaveStatus('❌ ' + e.message, 'err');
    }
}

function setProjColorDebounced(color) {
    clearTimeout(projHeadColorTimer);
    projHeadColorTimer = setTimeout(async () => {
        console.log('[Project] setProjColor:', color);
        try {
            const res = await API.patchBoard(BOARD_ID, { color: color });
            if (res?.entry) projHeadEntry = res.entry;
            // bewusst KEIN sofortiges Re-Render — der Farb-Picker wäre sonst zu (Badge folgt beim nächsten Render)
        } catch (e) {
            console.error('[Project] Farb-Fehler:', e);
        }
    }, 400);
}

async function setProjIcon(icon) {
    console.log('[Project] setProjIcon:', icon);
    try {
        const res = await API.patchBoard(BOARD_ID, { icon: icon });
        if (res?.entry) projHeadEntry = res.entry;
        renderProjectHead();
    } catch (e) {
        console.error('[Project] Icon-Fehler:', e);
    }
}

async function loadProjHeadCategories() {
    try {
        const r = await API.get('/categories');
        projHeadCategories = r.categories || {};
        renderProjectHead();
    } catch (e) {
        console.warn('[Project] Kategorien nicht ladbar:', e.message);
        projHeadCategories = {};
    }
}

async function loadProjHeadStatuses() {
    try {
        const r = await API.get('/statuses');
        projHeadStatuses = r.statuses || {};
        renderProjectHead();
    } catch (e) {
        console.warn('[Project] Status-Werte nicht ladbar:', e.message);
        projHeadStatuses = {};
    }
}

// ══════════════════════════════════════════════════════════════
// INIT
// ══════════════════════════════════════════════════════════════
console.log('[Project] Init, Board-ID=' + BOARD_ID);
// Deep-Link von der Dashboard-Kachel (?att=1) → Anhänge-Modal nach dem Laden öffnen
loadBoard().then(() => { if (params.get('att') === '1') openAttModal(); });
initTerminal();
loadSubprojects();
loadRollup();
loadProjHeadCategories();
loadProjHeadStatuses();
loadPriority Widget();

// Board-Höhe initial setzen + bei Viewport-Änderung nachführen
adjustBoardHeight();
window.addEventListener('resize', adjustBoardHeight);

// ══════════════════════════════════════════════════════════════
// PROJEKT-TERMINAL — Mobile-Tastatur + Touch-Modus (2026-07-17)
// Portiert aus caddy/html/terminals.html. Sendet synthetische KeyboardEvents
// direkt ans xterm-Textarea des #proj-terminal-iframes (same-origin), weil die
// native iOS-Tastatur über dem iframe-xterm oft nicht erscheint. Der Touch-
// Knopf schaltet via Prefix+T die tmux-Maus dieser Session (natives Scrollen/
// Kopieren/Einfügen am Handy). Eigene pt*-Namen → keine Kollision mit dem Rest.
// ══════════════════════════════════════════════════════════════
