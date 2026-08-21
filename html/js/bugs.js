/* bugs.js — Logik des Bug-Viewers (ausgelagert aus bugs.html).
 * Benötigt /js/api.js (window.API) — Reihenfolge im HTML beachten!
 * Alle Requests laufen relativ über nginx (Port 80) → FastAPI-Backend.
 */
let allBugs = [];
let activeLevel  = 'all';   // all | error | warning
let activeSource = 'all';   // all | kanban | log
let activeAge    = 'all';   // all | "3" | "24" | "168" | "720" (Stunden)
let bugModel = 'qwen2.5-coder:latest';

async function loadBugModel() {
  try {
    const cfg = await API.fetchAiConfig();
    bugModel = (cfg && cfg.bug_model) || bugModel;
    console.debug('[bugs] Bug-Modell:', bugModel);
  } catch(e) { console.debug('[bugs] ai-config nicht ladbar, nutze Default:', e.message); }
}
loadBugModel();
// Beim Page-Load direkt scannen — kein Klick mehr nötig
window.addEventListener('DOMContentLoaded', () => { scan(); });

// Lädt offene Bug-Karten vom Kanban-Board (home-stack-bugs) und mappt sie
// in dasselbe Bug-Format wie Log-Scan-Bugs, damit sie zusammen angezeigt werden.
async function loadKanbanBugs() {
  try {
    const data = await API.fetchBoard('home-stack-bugs');
    const openColIds = new Set(['reported', 'triage', 'inprogress']);
    const out = [];
    for (const col of (data.columns || [])) {
      if (!openColIds.has(col.id)) continue;
      for (const card of (col.cards || [])) {
        const title = String(card.title || '').replace(/^🐞\s*/, '').split('\n')[0].trim();
        out.push({
          source: 'kanban',
          card_title: card.title,
          column: col.title,
          column_id: col.id,
          level: 'error',
          service: 'whatsapp-bug',
          ts: (card.desc || '').match(/\d{4}-\d{2}-\d{2} \d{2}:\d{2}/)?.[0] || '',
          headline: title || '(ohne Titel)',
          context: (card.title || '') + '\n\n' + (card.desc || ''),
        });
      }
    }
    console.log(`[bugs] Kanban-Bugs geladen: ${out.length} offene Karten`);
    return out;
  } catch(e) {
    console.warn('[bugs] Kanban-Bugs laden fehlgeschlagen:', e.message);
    return [];
  }
}

// Scan-Bereich ist immer das Maximum (720h = 30d) — die Filterung passiert dann
// client-side via Age-Filter, dadurch kann der User zwischen den Buttons wechseln
// ohne neu zu scannen. Server-Last ist vernachlässigbar (~5-10s scan).
async function scan() {
  const since = 720;
  const main = document.getElementById('main');
  main.innerHTML = '<div class="loading"><span class="spinner"></span>Logs + Kanban werden geladen…</div>';
  document.getElementById('stats').style.display = 'none';
  document.getElementById('filters').style.display = 'none';

  try {
    const [logRes, kanbanBugs] = await Promise.all([
      API.scanLogs(since),
      loadKanbanBugs(),
    ]);

    const logBugs = (logRes.bugs || []).map(b => ({ ...b, source: b.source || 'log' }));
    // Kanban zuerst (höchste Priorität), dann Log-Errors
    let nr = 1;
    allBugs = [...kanbanBugs, ...logBugs].map(b => ({ ...b, nr: nr++ }));

    const kanbanCount = kanbanBugs.length;
    document.getElementById('cnt-error').textContent = (logRes.errors || 0) + kanbanCount;
    document.getElementById('cnt-warn').textContent  = logRes.warnings || 0;
    document.getElementById('cnt-total').textContent = (logRes.total || 0) + kanbanCount;
    document.getElementById('scanned-at').textContent =
      `Gescannt: ${logRes.scanned_at || ''} · ${kanbanCount} Kanban-Bugs`;
    document.getElementById('stats').style.display = 'flex';
    document.getElementById('filters').style.display = 'flex';
    renderBugs();
  } catch(e) {
    main.innerHTML = `<div class="empty" style="color:var(--error)">Fehler: ${e.message}</div>`;
  }
}

// setActive: ersetzt 'active' Klasse innerhalb einer Filter-Group, lässt andere Groups in Ruhe.
function _setActiveInGroup(btn) {
  const group = btn.closest('.filter-group');
  if (!group) return;
  group.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
}
function setLevel(level, btn)   { activeLevel  = level;  _setActiveInGroup(btn); renderBugs(); }
function setSource(source, btn) { activeSource = source; _setActiveInGroup(btn); renderBugs(); }
function setAge(age, btn)       { activeAge    = age;    _setActiveInGroup(btn); renderBugs(); }

// Parst "2026-05-23 00:42:38" / "2026-05-23T00:42:38" / "2026-05-23 00:42" → ms epoch, oder NaN.
function _parseBugTs(ts) {
  if (!ts) return NaN;
  const s = String(ts).replace(' ', 'T');
  const t = Date.parse(s);
  return Number.isFinite(t) ? t : NaN;
}

function renderBugs() {
  const query = (document.getElementById('search-input').value || '').toLowerCase();
  const main  = document.getElementById('main');

  let bugs = allBugs;
  if (activeLevel  !== 'all') bugs = bugs.filter(b => b.level === activeLevel);
  if (activeSource !== 'all') bugs = bugs.filter(b => (b.source || 'log') === activeSource);
  if (activeAge    !== 'all') {
    // activeAge ist jetzt in Stunden (3, 24, 168, 720), nicht mehr in Tagen
    const cutoff = Date.now() - parseInt(activeAge, 10) * 60 * 60 * 1000;
    bugs = bugs.filter(b => {
      const t = _parseBugTs(b.ts);
      // Kein parsebarer Timestamp → bei aktivem Age-Filter AUSBLENDEN.
      // Sonst rauschen alte Karten ohne Datum durch jeden Filter — genau das wollten wir lösen.
      if (Number.isNaN(t)) return false;
      return t >= cutoff;
    });
  }
  if (query) bugs = bugs.filter(b =>
    b.headline.toLowerCase().includes(query) ||
    b.service.toLowerCase().includes(query) ||
    b.context.toLowerCase().includes(query)
  );

  // Sichtbar-Counter live aktualisieren
  const cnt = document.getElementById('visible-count');
  if (cnt) cnt.textContent = `${bugs.length} / ${allBugs.length} sichtbar`;

  // Dedupe: gleiche Bugs gruppieren (Service + Headline ohne Timestamps/IDs).
  // Kanban-Bugs werden NIE dedupliziert (jede Karte ist ein eigener Eintrag).
  const groups = new Map();
  const kanbanBugs = [];
  for (const b of bugs) {
    if (b.source === 'kanban') { kanbanBugs.push(b); continue; }
    const norm = (b.headline || '')
      .replace(/\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\S*/g, '')
      .replace(/\b\d{2}:\d{2}:\d{2}\S*/g, '')
      .replace(/\b[0-9a-f]{8,}\b/gi, '')
      .replace(/\d{3,}/g, '')
      .replace(/\s+/g, ' ').trim().slice(0, 100);
    const key = (b.service || '') + '|' + norm;
    if (groups.has(key)) {
      const g = groups.get(key);
      g.count += 1;
      g.lastTs = b.ts || g.lastTs;
    } else {
      groups.set(key, { ...b, count: 1, lastTs: b.ts });
    }
  }
  // Kanban zuerst (immer oben), dann Log-Bugs nach Häufigkeit
  bugs = [...kanbanBugs, ...Array.from(groups.values()).sort((a, b) => b.count - a.count)];

  if (!bugs.length) {
    main.innerHTML = '<div class="empty">Keine Einträge gefunden.</div>';
    return;
  }

  main.innerHTML = bugs.map(b => {
    const isKanban   = b.source === 'kanban';
    const sourceTag  = isKanban
      ? `<span class="level-badge" style="background:#fc8181;color:#fff;">🐞 Kanban · ${escHtml(b.column || '')}</span>`
      : '';
    const boardLink  = isKanban
      ? `<a href="/project.html?id=home-stack-bugs" target="_blank" class="ollama-btn" style="text-decoration:none;display:inline-block;">📋 Auf Bug-Board öffnen</a>`
      : '';
    return `
    <div class="bug-card level-${b.level}" id="bug-${b.nr}">
      <div class="bug-header" onclick="toggle(${b.nr})">
        <span class="bug-nr">#${b.nr}</span>
        ${sourceTag}
        ${b.count > 1 ? `<span class="level-badge" style="background:#7c3aed;color:#fff;">×${b.count}</span>` : ''}
        <span class="level-badge level-${b.level}">${b.level}</span>
        <span class="bug-service">${escHtml(b.service)}</span>
        <span class="bug-ts">${escHtml(b.ts)}</span>
        <span class="bug-headline">${escHtml(b.headline)}</span>
        <span class="expand-icon">▶</span>
      </div>
      <div class="bug-body">
        <pre>${escHtml(b.context)}</pre>
        <div class="bug-actions">
          <button class="copy-btn" onclick="copyForClaude(${b.nr})">📋 Für Claude kopieren</button>
          <span class="copied-hint" id="hint-${b.nr}">✓ Kopiert!</span>
          <button class="ollama-btn" id="ollama-btn-${b.nr}" onclick="analyseWithOllama(${b.nr})">🤖 Ollama analysieren</button>
          <button class="ollama-btn" onclick="fixWithClaude(${b.nr})" style="background:#7c3aed;border-color:#7c3aed;color:#fff;">💬 Mit Claude fixen</button>
          ${boardLink}
        </div>
        <div class="analyse-area" id="analyse-${b.nr}">
          <div class="analyse-header">
            <span>🤖 <strong>${escHtml(bugModel)}</strong> — Analyse</span>
            <span id="analyse-status-${b.nr}" style="color:var(--muted)"></span>
          </div>
          <div class="analyse-body" id="analyse-body-${b.nr}"></div>
        </div>
      </div>
    </div>
    `;
  }).join('');
}

function toggle(nr) {
  const card = document.getElementById('bug-' + nr);
  card.classList.toggle('open');
}

async function fixWithClaude(nr) {
  const bug = allBugs.find(b => b.nr === nr);
  if (!bug) return;

  // Für Log-Bugs: zusätzlich Kanban-Karte auf home-stack-bugs anlegen,
  // damit der Fix-Vorgang im Bug-Board nachvollziehbar ist. Kanban-Bugs sind
  // bereits dort, also nicht doppelt anlegen.
  if (bug.source !== 'kanban' && !bug._kanbanCreated) {
    try {
      const text = `🐞 ${bug.service}: ${bug.headline}\n\nContext:\n${(bug.context || '').slice(0, 1500)}`;
      const data = await API.post('/bug-report', { text, board_id: 'home-stack-bugs' });
      bug._kanbanCreated = true;
      console.log('[bugs] Kanban-Karte angelegt:', data && data.card_title);
    } catch(e) {
      console.warn('[bugs] /bug-report fehlgeschlagen:', e.message);
    }
  }

  if (!window.ChatWidget || !window.ChatWidget.openWithBug) {
    alert('Chat-Widget noch nicht geladen.'); return;
  }
  window.ChatWidget.openWithBug(bug);
}

function copyForClaude(nr) {
  const bug = allBugs.find(b => b.nr === nr);
  if (!bug) return;
  const text = [
    `=== BUG #${bug.nr}: ${bug.service} (${bug.ts}) ===`,
    `Level:    ${bug.level}`,
    `Quelle:   ${bug.source}`,
    `Fehler:   ${bug.headline}`,
    ``,
    `Kontext:`,
    `---`,
    bug.context,
    `---`,
  ].join('\n');

  navigator.clipboard.writeText(text).then(() => {
    const hint = document.getElementById('hint-' + nr);
    hint.style.display = 'inline';
    setTimeout(() => hint.style.display = 'none', 2000);
  });
}

function renderAnalyseText(el, text, withCursor) {
  const escaped = text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  const paragraphs = escaped.split(/\n\n+/).map(p =>
    `<p>${p.replace(/\n/g, '<br>')}</p>`
  ).join('');
  el.innerHTML = paragraphs + (withCursor ? '<span class="analyse-cursor"></span>' : '');
}

async function analyseWithOllama(nr) {
  const bug = allBugs.find(b => b.nr === nr);
  if (!bug) return;

  const btn      = document.getElementById('ollama-btn-' + nr);
  const area     = document.getElementById('analyse-' + nr);
  const bodyEl   = document.getElementById('analyse-body-' + nr);
  const statusEl = document.getElementById('analyse-status-' + nr);

  btn.disabled = true;
  btn.textContent = '⏳ Analysiere…';
  area.classList.add('show');
  bodyEl.innerHTML = '<span class="analyse-cursor"></span>';
  statusEl.textContent = 'Verbinde mit Ollama…';
  statusEl.style.color = '';

  try {
    let text = '';
    let first = true;
    await API.analyseBugStream({ bug, model: bugModel }, (token) => {
      if (first) { statusEl.textContent = 'Streamt…'; first = false; }
      text += token;
      renderAnalyseText(bodyEl, text, true);
    });

    renderAnalyseText(bodyEl, text.trim(), false);
    statusEl.textContent = 'Fertig ✓';
    btn.textContent = '🔄 Neu analysieren';
  } catch(e) {
    statusEl.textContent = '❌ ' + e.message;
    statusEl.style.color = 'var(--error)';
    btn.textContent = '🤖 Ollama analysieren';
  }
  btn.disabled = false;
}

const escHtml = window.escHtml;
