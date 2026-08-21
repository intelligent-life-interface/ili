/* m.js — iPhone-/Mobile-Ansicht. Self-contained (kein api.js nötig).
 * Alle Pfade RELATIV → nginx (Port 8201) proxyt API zu FastAPI 8798.
 * Views: Übersicht (Projekte) · Board-Detail (Karten lesen) · Schnell-Erfassung (Idee/Foto).
 */
(function () {
  'use strict';
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const log = (...a) => console.debug('[m]', ...a);

  // ---- Zustand ----
  let CATS = {};          // category-key → {label,color,emoji}
  let CAT_RANK = {};      // category-key → Index (Reihenfolge wie /categories, für Sortierung „nach Gruppe")
  let PROJECTS = [];      // /api/dashboard projects
  let activeCat = '';     // '' = alle
  let activePrio = '';    // '' = alle | q1..q4 | 'none' = nicht einsortiert
  let activeAuto = '';    // '' = alle | aus|an|erledigt|entscheidung
  let search = '';

  // Eisenhower-Quadranten (gleiches Datenmodell wie Desktop-🎯: Board-Feld `eisenhower`)
  const PRIOS = {
    q1:   { label: '🔴 Dringend & wichtig',   color: '#e05252' },
    q2:   { label: '🟡 Dringend oder wichtig', color: '#d9a520' },
    q3:   { label: '🟢 Unwichtig',             color: '#3f9e57' },
    q4:   { label: '⚫ Nicht umsetzen',        color: '#666'    },
    none: { label: '📥 Ohne Prio',             color: '#4a6b8a' },
  };
  const prioKeyOf = p => (p.eisenhower && PRIOS[p.eisenhower]) ? p.eisenhower : 'none';
  const PRIO_RANK = { q1: 0, q2: 1, q3: 2, q4: 3, none: 4 };
  const catRank = p => {
    const k = p.category || '';
    return CAT_RANK.hasOwnProperty(k) ? CAT_RANK[k] : Object.keys(CATS).length;
  };

  // Automatische Weiterentwicklung (4 Status, gleiches Datenmodell wie Desktop-🎯:
  // Board-Feld `auto` + abgeleitet aus counts/autoDecisions). Read-only hier (Umschalten
  // nur am Desktop im Priorisieren-Modus).
  const AUTO_STATE = {
    aus:          { emoji: '⚪', label: 'Auto-Entwicklung: aus' },
    an:           { emoji: '🤖', label: 'Auto-Entwicklung: läuft' },
    erledigt:     { emoji: '✅', label: 'Auto-Entwicklung: alle Kanban erledigt' },
    entscheidung: { emoji: '🙋', label: 'Entscheidung nötig — wartet auf dich' },
  };
  let autoDecisions = {};   // board-slug -> true (offene Entscheidungskarte)
  function autoStateKey(p) {
    if (!p.auto) return 'aus';
    if (autoDecisions[p.id]) return 'entscheidung';
    const c = p.counts || {};
    if (((c.backlog || 0) + (c.in_progress || 0)) === 0) return 'erledigt';
    return 'an';
  }

  // ---- Netz-Helfer ----
  async function jget(path) {
    try {
      const r = await window.API.get(path);
      log('GET', path, 'OK');
      return r;
    } catch (e) {
      log('GET', path, 'FEHLER:', e.message);
      throw e;
    }
  }
  async function jpost(path, body) {
    try {
      const r = await window.API.post(path, body);
      log('POST', path, 'OK');
      return r;
    } catch (e) {
      log('POST', path, 'FEHLER:', e.message);
      throw e;
    }
  }

  // ---- UI-Helfer ----
  const esc = window.escHtml;
  function overlay(show, txt) { const o = $('#overlay'); if (txt) $('#overlay-text').textContent = txt; o.classList.toggle('hidden', !show); }
  let toastT;
  function toast(msg, kind) {
    const t = $('#toast'); t.textContent = msg; t.className = 'toast' + (kind ? ' ' + kind : '');
    t.classList.remove('hidden'); clearTimeout(toastT);
    toastT = setTimeout(() => t.classList.add('hidden'), 3200);
  }
  const catOf = id => CATS[id] || null;

  // ---- Übersicht ----
  function renderChips() {
    const box = $('#cat-chips');
    const mk = (key, label, color) => {
      const b = document.createElement('button');
      b.className = 'chip' + (activeCat === key ? ' active' : '');
      b.textContent = label;
      if (activeCat === key && color) b.style.background = color;
      b.onclick = () => { activeCat = (activeCat === key ? '' : key); renderChips(); renderProjects(); };
      return b;
    };
    box.innerHTML = '';
    box.appendChild(mk('', 'Alle', null));
    // nur Kategorien anzeigen, die auch vorkommen
    const used = new Set(PROJECTS.map(p => p.category).filter(Boolean));
    Object.keys(CATS).forEach(k => {
      if (!used.has(k)) return;
      const c = CATS[k];
      box.appendChild(mk(k, (c.emoji || '') + ' ' + c.label, c.color));
    });
  }

  function renderPrioChips() {
    const box = $('#prio-chips');
    const counts = {};
    PROJECTS.forEach(p => { const k = prioKeyOf(p); counts[k] = (counts[k] || 0) + 1; });
    log('prio-chips', counts);
    box.innerHTML = '';
    const mk = (key, label, color) => {
      const b = document.createElement('button');
      b.className = 'chip' + (activePrio === key ? ' active' : '');
      b.textContent = label;
      if (activePrio === key && color) b.style.background = color;
      b.onclick = () => { activePrio = (activePrio === key ? '' : key); renderPrioChips(); renderProjects(); };
      return b;
    };
    box.appendChild(mk('', '🎯 Alle', null));
    Object.keys(PRIOS).forEach(k => {
      if (!counts[k]) return;   // nur Quadranten anzeigen, die vorkommen
      box.appendChild(mk(k, PRIOS[k].label + ' (' + counts[k] + ')', PRIOS[k].color));
    });
  }

  // Filter-Chips für den Auto-Entwicklung-Status (analog Prio-Chips)
  function renderAutoChips() {
    const box = $('#auto-chips');
    if (!box) return;
    const counts = {};
    PROJECTS.forEach(p => { const k = autoStateKey(p); counts[k] = (counts[k] || 0) + 1; });
    log('auto-chips', counts);
    box.innerHTML = '';
    const mk = (key, label) => {
      const b = document.createElement('button');
      b.className = 'chip' + (activeAuto === key ? ' active' : '');
      b.textContent = label;
      b.onclick = () => { activeAuto = (activeAuto === key ? '' : key); renderAutoChips(); renderProjects(); };
      return b;
    };
    box.appendChild(mk('', '🤖 Alle'));
    Object.keys(AUTO_STATE).forEach(k => {
      if (!counts[k]) return;   // nur Status anzeigen, die vorkommen
      box.appendChild(mk(k, AUTO_STATE[k].emoji + ' ' + counts[k]));
    });
  }

  function renderProjects() {
    const list = $('#project-list');
    let items = PROJECTS.slice();
    if (activeCat) items = items.filter(p => p.category === activeCat);
    if (activePrio) items = items.filter(p => prioKeyOf(p) === activePrio);
    if (activeAuto) items = items.filter(p => autoStateKey(p) === activeAuto);
    if (search) {
      const q = search.toLowerCase();
      items = items.filter(p => (p.name || p.id || '').toLowerCase().includes(q) ||
        (p.description || '').toLowerCase().includes(q) ||
        (p.tags || []).join(' ').toLowerCase().includes(q));
    }
    // sortiere: nach Gruppe (Kategorie-Reihenfolge wie /categories), dann Prio (Eisenhower q1→q4→ohne), dann Name
    items.sort((a, b) => {
      const cr = catRank(a) - catRank(b);
      if (cr !== 0) return cr;
      const pr = PRIO_RANK[prioKeyOf(a)] - PRIO_RANK[prioKeyOf(b)];
      if (pr !== 0) return pr;
      return (a.name || a.id || '').localeCompare(b.name || b.id || '', 'de');
    });
    $('#overview-empty').classList.toggle('hidden', items.length > 0);
    list.innerHTML = '';
    items.forEach(p => {
      const c = catOf(p.category);
      const cnt = p.counts || {};
      const el = document.createElement('div');
      el.className = 'proj';
      el.style.setProperty('--cat', p.color || (c && c.color) || '#4a90d9');
      const open = cnt.backlog || 0, prog = cnt.in_progress || 0, done = cnt.done || 0;
      const ast = AUTO_STATE[autoStateKey(p)];
      el.innerHTML =
        `<div class="proj-title">${c ? esc(c.emoji) + ' ' : ''}${esc(p.name || p.id)}<span class="chev">›</span></div>` +
        (p.description ? `<div class="proj-desc">${esc(p.description)}</div>` : '') +
        `<div class="proj-meta">` +
          `<span class="badge auto" title="${esc(ast.label)}">${ast.emoji}</span>` +
          (PRIOS[p.eisenhower] ? `<span class="badge prio" style="color:${PRIOS[p.eisenhower].color}">${PRIOS[p.eisenhower].label}</span>` : '') +
          (open ? `<span class="badge open">📥 ${open}</span>` : '') +
          (prog ? `<span class="badge prog">⚙️ ${prog}</span>` : '') +
          (done ? `<span class="badge done">✅ ${done}</span>` : '') +
          (p.sub_count ? `<span class="badge">📂 ${p.sub_count}</span>` : '') +
          (p.att_count ? `<span class="badge">📎 ${p.att_count}</span>` : '') +
        `</div>`;
      el.onclick = () => gotoBoard(p.id);
      list.appendChild(el);
    });
  }

  async function loadOverview() {
    overlay(true, 'Lädt Projekte…');
    try {
      const [cats, dash, dec] = await Promise.all([
        jget('/categories').catch(() => ({ categories: {} })),
        jget('/api/dashboard'),
        jget('/api/automat/decisions').catch(() => ({ decisions: [] })),
      ]);
      CATS = cats.categories || {};
      CAT_RANK = {};
      Object.keys(CATS).forEach((k, i) => { CAT_RANK[k] = i; });
      PROJECTS = dash.projects || [];
      autoDecisions = {};
      (dec.decisions || []).forEach(d => { if (d.board) autoDecisions[d.board] = true; });
      renderChips(); renderPrioChips(); renderAutoChips(); renderProjects();
    } catch (e) {
      toast('Fehler beim Laden: ' + e.message, 'err');
    } finally { overlay(false); }
  }

  // ---- Board-Detail: Kanban-Liste + Terminal ----
  const HIDE_RE = /(navigation|ki_archiv)/i;
  // Erledigt-Spalten (Substring-Match wie das Desktop-Prio-Widget — Boards nutzen
  // mal `done`, mal `col_done`, mal deutsche Titel) → nicht in der Prio-Ansicht
  const DONE_RE = /(erledigt|done|fertig|abgeschlossen|beendet|archiv)/i;
  function prioClass(p) { return p === 'hoch' || p === 'high' ? 'pl-high' : (p === 'niedrig' || p === 'low' ? 'pl-low' : (p ? 'pl-mid' : '')); }
  let curBoard = null;     // {id, name}
  let boardMode = 'list';  // 'list' | 'term'
  let termLoaded = false;

  // ── Hash-Routing (#b=<boardId>) — Browser-Zurück + Neuladen funktionieren ──
  // Karten-Tap setzt nur den Hash; erst hashchange rendert. Reload mit Hash stellt
  // das Board wieder her, die Zurück-Geste landet in der Übersicht statt ausserhalb der App.
  let appNav = false;   // Board per In-App-Navigation erreicht? → Zurück = history.back()
  function gotoBoard(id) {
    const h = '#b=' + encodeURIComponent(id);
    if (location.hash === h) { route(); return; }   // gleicher Hash feuert kein hashchange
    appNav = true;
    location.hash = h;                              // → hashchange → route()
  }
  function goOverview() {
    if (appNav) { history.back(); return; }         // In-App geöffnet → echter Verlauf
    // Direkt-Einstieg/Reload mit #b=…: Hash still entfernen, kein Extra-Verlaufseintrag
    history.replaceState(null, '', location.pathname + location.search);
    route();
  }
  function route() {
    const m = location.hash.match(/^#b=(.+)/);
    log('route', location.hash || '(leer)');
    if (m) {
      const id = decodeURIComponent(m[1]);
      // PROJECTS kennt nur Top-Level — Unterprojekte stehen nur in ALL_BOARDS,
      // sonst stünde beim Sprung ins Unterprojekt die rohe ID im Titel.
      const p = PROJECTS.find(x => x.id === id) || ALL_BOARDS.find(x => x.id === id);
      openBoard(id, (p && (p.name || p.id)) || id);
    } else {
      appNav = false;
      showOverview();
    }
  }

  async function openBoard(id, name) {
    curBoard = { id: id, name: name };
    overlay(true, 'Lädt Board…');
    try {
      const b = await jget('/board?id=' + encodeURIComponent(id));
      $('#view-title').textContent = name;
      // Karten flach einsammeln (sichtbare Spalten) — Grundlage für BEIDE Panels
      const flat = [];
      (b.columns || []).forEach(col => {
        const title = col.title || col.id || '';
        if (HIDE_RE.test(col.id || '') || HIDE_RE.test(title)) return;
        (col.cards || []).forEach(c => {
          if (c.id === 'claudemd-description') return;
          flat.push({ c, col: title, done: DONE_RE.test(col.id || '') || DONE_RE.test(title) });
        });
      });
      renderPrioPanel(flat);
      renderColsPanel(flat);
      log('Board gerendert:', id, flat.length + ' Karten');
      renderBoardCrumbs(id);    // ⬅ Mutterprojekt + Unterprojekte — best-effort
      renderBoardLinks(id);     // Direktlink-Chips (FileBrowser/Web-App/Daten) — best-effort
      setBoardMode('list');     // immer mit der Liste starten
      showView('board');
    } catch (e) {
      toast('Board-Fehler: ' + e.message, 'err');
    } finally { overlay(false); }
  }

  // Eine antippbare Karte bauen — Tap öffnet das Detail-Sheet (volle Beschreibung)
  function mkCard(c, colTitle, showCol) {
    const card = document.createElement('div');
    card.className = 'kcard ' + prioClass(c.priority);
    card.innerHTML =
      `<div class="kcard-title">${esc(c.title || '(ohne Titel)')}</div>` +
      ((c.description || c.desc) ? `<div class="kcard-desc">${esc(c.description || c.desc)}</div>` : '') +
      ((c.priority || c.effort || showCol) ? `<div class="kcard-meta">${showCol ? '📍 ' + esc(colTitle) + ' ' : ''}${c.priority ? '⚡ ' + esc(c.priority) : ''}${c.effort ? ' ⏱ ' + esc(c.effort) : ''}</div>` : '');
    card.onclick = () => openCardSheet(c, colTitle);
    return card;
  }

  // 📋 Spalten-Panel: Kanban nach Spalten gruppiert (wie bisher, jetzt antippbar)
  function renderColsPanel(flat) {
    const wrap = $('#col-groups'); wrap.innerHTML = '';
    const groups = new Map();
    flat.forEach(e => { if (!groups.has(e.col)) groups.set(e.col, []); groups.get(e.col).push(e); });
    let shown = 0;
    groups.forEach((entries, title) => {
      shown += entries.length;
      const grp = document.createElement('div');
      grp.className = 'col-group';
      grp.innerHTML = `<div class="col-title">${esc(title)} (${entries.length})</div>`;
      entries.forEach(e => grp.appendChild(mkCard(e.c, e.col, false)));
      wrap.appendChild(grp);
    });
    if (!shown) wrap.innerHTML = `<p class="empty">Keine offenen Karten.</p>`;
  }

  // 🎯 Prioritäten-Panel: offene Karten nach Priorität gruppiert (wie das
  // Desktop-Prio-Widget); erledigte Spalten bleiben draussen. Karte zeigt 📍 Spalte.
  const PRIO_ORDER = [
    { re: /^(hoch|high|dringend)$/i, label: '🔴 Hoch' },
    { re: /^(mittel|medium|mid)$/i,  label: '🟡 Mittel' },
    { re: /^(niedrig|low)$/i,        label: '🟢 Niedrig' },
    { re: null,                      label: '⚪ Ohne Priorität' },
  ];
  const hasPrio = c => PRIO_ORDER.some(g => g.re && g.re.test(c.priority || ''));
  function renderPrioPanel(flat) {
    const wrap = $('#prio-groups'); wrap.innerHTML = '';
    const open = flat.filter(e => !e.done);
    PRIO_ORDER.forEach(g => {
      const entries = open.filter(e => g.re ? g.re.test(e.c.priority || '') : !hasPrio(e.c));
      if (!entries.length) return;
      const grp = document.createElement('div');
      grp.className = 'col-group';
      grp.innerHTML = `<div class="col-title">${g.label} (${entries.length})</div>`;
      entries.forEach(e => grp.appendChild(mkCard(e.c, e.col, true)));
      wrap.appendChild(grp);
    });
    if (!open.length) wrap.innerHTML = `<p class="empty">Keine offenen Karten.</p>`;
    log('prio-panel', open.length + ' offene Karten');
  }

  // Karten-Detail-Sheet (Tap auf Karte): Titel, Spalte/Prio/Aufwand, volle Beschreibung
  function openCardSheet(c, colTitle) {
    $('#card-title').textContent = c.title || '(ohne Titel)';
    const meta = [];
    if (colTitle) meta.push('📍 ' + colTitle);
    if (c.priority) meta.push('⚡ ' + c.priority);
    if (c.effort) meta.push('⏱ ' + c.effort);
    $('#card-meta').innerHTML = meta.map(m => `<span class="badge2">${esc(m)}</span>`).join('');
    $('#card-desc').textContent = c.description || c.desc || '(keine Beschreibung)';
    openSheet('card');
    log('Karte geöffnet:', c.title);
  }

  // Direktlink-Chips zum Projekt (FileBrowser/Web-App). Quelle: GET /api/project-links?id=
  // Gleiche Logik wie der Desktop-Kopf — im Browser-Terminal sind Pfade nicht klickbar,
  // hier ein Tap zum data/-Ordner (🗂), Code-Ordner (📁) oder der laufenden Web-App.
  const BOARD_LINK_DEFS = [
    { key: 'webapp',      icon: '🌐', label: 'Web-App' },
    { key: 'filebrowser', icon: '📁', label: 'Dateien' },
    { key: 'datadir',     icon: '🗂', label: 'Daten' },
    { key: 'claudemd',    icon: '📄', label: 'Doku' },
    { key: 'github',      icon: '🐙', label: 'GitHub' },
  ];
  // ── Projekt-Hierarchie am Handy ──────────────────────────────────────────
  // /api/dashboard liefert nur Top-Level-Projekte und kein parent_ids, darum
  // einmal pro Sitzung /boards?all=1 nachladen (223 schlanke Manifest-Einträge).
  let ALL_BOARDS = [];
  async function loadAllBoards() {
    if (ALL_BOARDS.length) return ALL_BOARDS;
    try {
      const d = await jget('/boards?all=1');
      ALL_BOARDS = Array.isArray(d) ? d : (d.boards || []);
      log('ALL_BOARDS geladen:', ALL_BOARDS.length);
    } catch (e) {
      log('ALL_BOARDS Fehler:', e.message);
    }
    return ALL_BOARDS;
  }
  function parentsOf(b) {
    if (!b) return [];
    if (Array.isArray(b.parent_ids)) return b.parent_ids;
    return b.parent_id ? [b.parent_id] : [];
  }

  // Chips über dem Board: links ⬅ Mutterprojekt(e), dahinter die eigenen
  // Unterprojekte. Tap navigiert per Hash-Routing (Browser-Zurück bleibt heil).
  async function renderBoardCrumbs(id) {
    const el = $('#board-crumbs');
    if (!el) return;
    el.innerHTML = '';
    const all = await loadAllBoards();
    if (!all.length) return;

    const self = all.find(b => b.id === id);
    // Direkteinstieg per Link: route() kannte den Namen noch nicht (PROJECTS hat
    // nur Top-Level) und schrieb die rohe ID in den Titel — jetzt nachziehen.
    if (self && self.name && $('#view-title').textContent === id) {
      $('#view-title').textContent = self.name;
      if (curBoard && curBoard.id === id) curBoard.name = self.name;
    }
    const mkChip = (bid, label, cls) => {
      const a = document.createElement('button');
      a.className = 'board-crumb ' + (cls || '');
      a.textContent = label;
      a.onclick = () => gotoBoard(bid);
      return a;
    };

    parentsOf(self).forEach(pid => {
      const p = all.find(b => b.id === pid);
      el.appendChild(p
        ? mkChip(pid, '⬅ ' + (p.icon || '📋') + ' ' + (p.name || pid), 'bc-parent')
        : mkChip(pid, '⬅ ⚠️ ' + pid, 'bc-parent bc-broken'));
    });

    const kids = all.filter(b => parentsOf(b).includes(id));
    kids.forEach(k => el.appendChild(mkChip(k.id, (k.icon || '📋') + ' ' + (k.name || k.id), 'bc-child')));
    log('board-crumbs', id, parentsOf(self).length + ' Eltern,', kids.length + ' Unterprojekte');
  }

  async function renderBoardLinks(id) {
    const el = $('#board-links');
    if (!el) return;
    el.innerHTML = '';
    try {
      const data = await jget('/api/project-links?id=' + encodeURIComponent(id));
      const links = (data && data.links) || {};
      const chips = BOARD_LINK_DEFS.filter(d => links[d.key]).map(d =>
        `<a class="board-link" href="${esc(links[d.key])}" target="_blank" rel="noopener">${d.icon} ${d.label}</a>`);
      el.innerHTML = chips.join('');
      log('board-links', id, chips.length + ' Chips');
    } catch (e) {
      log('board-links Fehler:', e.message);  // nie blockieren — Chips sind optional
    }
  }

  // Liste <-> Terminal umschalten. Terminal wird erst beim ersten Mal geladen (spart ttyd-Client).
  function setBoardMode(mode) {
    boardMode = mode;
    $$('#board-seg .seg-btn').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
    $('#board-list').classList.toggle('hidden', mode !== 'list');
    $('#board-term').classList.toggle('hidden', mode !== 'term');
    document.body.classList.toggle('term-active', mode === 'term');  // Vollbild-Stapel + iPhone-Tastatur-Fit
    if (mode === 'term') {
      loadTerminal();
      fitViewport();
      // NICHT fokussieren — Fokus aufs Terminal-Feld würde nur die iOS-Tastatur holen.
      // Eingabe läuft über #m-input / Daten-Kanal. termTextarea() härtet das Feld nur ab.
      setTimeout(() => { termTextarea(); }, 150);
    } else {
      clearViewport();
    }
  }

  function removeAuthHint() { const h = $('#term-auth-hint'); if (h) h.remove(); }

  // /projterm/ verlangt Basic-Auth (401 + WWW-Authenticate). Chrome/Firefox/Safari
  // unterdrücken den nativen Login-Dialog aber, wenn er aus einem <iframe> ausgelöst
  // wird (Anti-Phishing) — auf einem Gerät ohne bereits gecachte Zugangsdaten (v.a.
  // beim ersten Mal auf dem Handy) bleibt das Terminal dadurch für immer schwarz,
  // ohne dass der Nutzer je einen Login sieht. Fix: vorab HTTP-Probe senden (HTTP HEAD
  // triggert nie einen Dialog) und bei 401 einen Link zum Login AUSSERHALB des
  // iframes anbieten (target=_blank) — danach cacht der Browser die Zugangsdaten
  // für den Origin und der iframe funktioniert.
  function showAuthHint() {
    if ($('#term-auth-hint')) return;
    const h = document.createElement('div');
    h.id = 'term-auth-hint'; h.className = 'term-hint';
    h.innerHTML = '🔒 Terminal-Login nötig — der Browser blockiert den Login-Dialog im eingebetteten Fenster.<br>'
      + '<a href="/projterm/" target="_blank" rel="noopener" style="color:var(--accent);font-weight:600">↗ Einmalig hier anmelden</a>, '
      + 'dann zurückkommen und <button id="term-auth-retry" style="background:none;border:1px solid var(--line);'
      + 'color:var(--text);border-radius:8px;padding:.2rem .5rem;font-size:.78rem">↻ erneut versuchen</button>.';
    $('#board-term').insertBefore(h, $('#board-term').firstChild);
    $('#term-auth-retry').addEventListener('click', () => { removeAuthHint(); termLoaded = false; loadTerminal(); });
  }

  async function loadTerminal() {
    const frame = $('#m-term');
    // ttyd-WS-Cookie ist Secure → über http kommt keine Shell. Klartext-Hinweis statt totem Terminal.
    if (location.protocol !== 'https:') {
      if (!$('#term-https-hint')) {
        const h = document.createElement('p');
        h.id = 'term-https-hint'; h.className = 'term-hint';
        h.innerHTML = '⚠️ Das Terminal braucht HTTPS. Bitte über <b>https://' + location.hostname + '/m/</b> öffnen.';
        $('#board-term').insertBefore(h, $('#board-term').firstChild);
      }
      return;
    }
    if (termLoaded && frame.src) return;
    try {
      const probe = await fetch('/projterm/', { method: 'HEAD', cache: 'no-store' });
      if (probe.status === 401) { showAuthHint(); return; }
    } catch (e) {
      log('Terminal-Auth-Check fehlgeschlagen, versuche trotzdem zu laden:', e.message);
    }
    removeAuthHint();
    frame.onload = () => {
      // ttyd (xterm fit-addon) misst die Spaltenzahl bei 'resize' neu — nötig wegen des CSS-Zoom-Tricks.
      // Zugleich das xterm-Textarea entschärfen (autocorrect off), sobald es existiert.
      [120, 400, 900, 1800].forEach(t => setTimeout(() => {
        try { frame.contentWindow.dispatchEvent(new Event('resize')); } catch (_) {}
        termTextarea();
      }, t));
    };
    frame.src = '/projterm/?arg=' + encodeURIComponent(curBoard.id);
    termLoaded = true;
    // Auto-Reconnect: erkennt totes ttyd ("Connection Closed") und lädt nur das
    // iframe neu — tmux reattacht. Logik zentral in /terminal-watchdog.js.
    // (about:blank nach Board-Wechsel ist harmlos: Watchdog ignoriert Frames ohne .xterm)
    if (window.TermWatchdog) window.TermWatchdog.watch(frame, 'm-term');
    else log('terminal-watchdog.js nicht geladen — kein Auto-Reconnect');
    log('Terminal geladen für', curBoard.id);
  }

  // ── Tasten-Injektion ins ttyd-xterm (same-origin iframe) ───────────────
  // Bewährtes Muster aus terminals.html: synthetische KeyboardEvents ans
  // xterm-Helper-Textarea. Sonderkeys → Steuersequenz, Zeichen → direkt.
  const KEYMAP = {
    'Escape':     { keyCode: 27, code: 'Escape' },
    'Tab':        { keyCode: 9,  code: 'Tab' },
    'Enter':      { keyCode: 13, code: 'Enter' },
    'Backspace':  { keyCode: 8,  code: 'Backspace' },
    'ArrowLeft':  { keyCode: 37, code: 'ArrowLeft' },
    'ArrowUp':    { keyCode: 38, code: 'ArrowUp' },
    'ArrowDown':  { keyCode: 40, code: 'ArrowDown' },
    'ArrowRight': { keyCode: 39, code: 'ArrowRight' },
    'Home':       { keyCode: 36, code: 'Home' },
    'End':        { keyCode: 35, code: 'End' },
    'PageUp':     { keyCode: 33, code: 'PageUp' },
    'PageDown':   { keyCode: 34, code: 'PageDown' },
  };
  const stick = { ctrl: false, alt: false };  // Sticky-Modifier: gelten für die NÄCHSTE Taste

  function termTextarea() {
    const f = $('#m-term');
    let doc;
    try { doc = f.contentDocument || f.contentWindow.document; }
    catch (e) { log('iframe-Doc blockiert:', e.message); return null; }
    if (!doc) return null;
    const ta = doc.querySelector('textarea.xterm-helper-textarea') || doc.querySelector('.xterm-helper-textarea') || doc.querySelector('textarea');
    if (ta) hardenTextarea(ta);
    return ta;
  }
  // iOS-Autokorrektur/Gross-Schreib-Automatik abschalten → Zeichen kommen 1:1 an.
  function hardenTextarea(ta) {
    if (ta.dataset.hardened) return;
    ta.setAttribute('autocorrect', 'off');
    ta.setAttribute('autocapitalize', 'none');
    ta.setAttribute('autocomplete', 'off');
    ta.setAttribute('spellcheck', 'false');
    ta.setAttribute('inputmode', 'none');   // native iOS-Tastatur am Terminal AUS — getippt wird über #m-input
    // readonly = iOS zeigt NIE die Tastatur (auch nicht bei Tap/Fokus). Eingabe läuft
    // ausschliesslich über den Daten-Kanal (triggerDataEvent) bzw. #m-input, NICHT über
    // dieses Feld → readonly stört nichts. (2026-07-18: „Tastatur kommt dauernd"-Fix.)
    // KEIN blur-on-focus mehr — würde sich mit Fokus/Reconnect streiten; readonly reicht.
    ta.readOnly = true;
    ta.setAttribute('readonly', 'readonly');
    ta.dataset.hardened = '1';
    log('Textarea entschärft (readonly, inputmode none)');
  }
  // Beibehalten für Aufrufer — Terminal-Feld bleibt hart unterdrückt (readonly/blur).
  function setNativeKbd(suppress) { termTextarea(); }

  // Terminal-Objekt + Rohdaten-Kanal. Der EINZIGE zuverlässige Weg: synthetische
  // KeyboardEvents erreichen dieses xterm/ttyd NICHT (verifiziert 2026-07-18).
  // triggerDataEvent(data,true) = als hätte der Nutzer getippt → ttyd-WS → tmux.
  function mTerm() {
    const f = $('#m-term');
    try { return (f && f.contentWindow && f.contentWindow.term) || null; } catch (e) { return null; }
  }
  function mSendData(data) {
    // Tote Verbindung? window.term existiert dann noch und triggerDataEvent "klappt"
    // still in den toten Socket — darum vorher Watchdog-Zustand prüfen, Feedback
    // zeigen und den Reconnect sofort anstossen.
    const f = $('#m-term');
    const wd = window.TermWatchdog;
    if (wd && f) {
      const s = wd.state(f);
      if (s === 'closed' || s === 'reconnecting') {
        log('Tastendruck verworfen — Verbindung tot (' + s + ')');
        toast('⚠️ Keine Terminal-Verbindung — stelle wieder her…', 'err');
        wd.kick(); return false;
      }
    }
    const t = mTerm();
    if (!t) { toast('Terminal noch nicht bereit', 'err'); return false; }
    try { t._core.coreService.triggerDataEvent(data, true); return true; }
    catch (e) { log('triggerDataEvent Fehler:', e); return false; }
  }
  // Tasten-Spezifikation {key?,ch?,ctrl?,alt?} → Byte-Sequenz fürs Terminal.
  function keyToBytes(spec) {
    const ctrl = !!spec.ctrl || stick.ctrl, alt = !!spec.alt || stick.alt;
    const wrapAlt = s => alt ? '\x1b' + s : s;
    if (spec.ch != null) {
      const c = spec.ch;
      if (ctrl && c.length === 1) { const cc = c.toUpperCase().charCodeAt(0); if (cc >= 64 && cc <= 95) return wrapAlt(String.fromCharCode(cc & 0x1f)); }
      return wrapAlt(c);
    }
    const t = mTerm();
    const appCK = !!(t && t.modes && t.modes.applicationCursorKeys);
    const NAMED = {
      Enter: '\r', Tab: '\t', Escape: '\x1b', Backspace: '\x7f',
      ArrowUp: appCK ? '\x1bOA' : '\x1b[A', ArrowDown: appCK ? '\x1bOB' : '\x1b[B',
      ArrowRight: appCK ? '\x1bOC' : '\x1b[C', ArrowLeft: appCK ? '\x1bOD' : '\x1b[D',
      Home: '\x1b[H', End: '\x1b[F', PageUp: '\x1b[5~', PageDown: '\x1b[6~',
    };
    if (NAMED[spec.key] != null) return NAMED[spec.key];
    const k = spec.key;
    if (k && k.length === 1) {
      if (ctrl) { const cc = k.toUpperCase().charCodeAt(0); if (cc >= 64 && cc <= 95) return wrapAlt(String.fromCharCode(cc & 0x1f)); }
      return wrapAlt(k);
    }
    return '';
  }
  // Eine Taste senden. spec: {key?, ch?, ctrl?, alt?}
  function press(spec) {
    const bytes = keyToBytes(spec);
    if (bytes === '') { clearSticky(); return; }
    if (mSendData(bytes)) log('gesendet:', JSON.stringify(bytes));
    clearSticky();
  }
  function clearSticky() {
    if (!stick.ctrl && !stick.alt) return;
    stick.ctrl = false; stick.alt = false;
    $$('#keys .mod.on').forEach(b => b.classList.remove('on'));
  }
  function toggleMod(which, btn) { stick[which] = !stick[which]; btn.classList.toggle('on', stick[which]); }

  // ── Aufklappbare Reihen (☰) + volle QWERTZ-Tastatur (⌨) ────────────────
  let shiftOn = false;
  function applyShift() {
    $$('#kbd .ltr').forEach(b => { const base = b.dataset.ch.toLowerCase(); b.textContent = shiftOn ? base.toUpperCase() : base; });
    $('#shiftbtn').classList.toggle('on', shiftOn);
  }
  function applyMore(open) {
    $('#keys').classList.toggle('collapsed', !open);
    $('#morebtn').textContent = open ? '▲' : '☰';
  }
  function toggleMore() {
    const open = $('#keys').classList.contains('collapsed');
    try { localStorage.setItem('m-term-more', open ? '1' : '0'); } catch (_) {}
    applyMore(open); fitViewport();
  }
  function toggleKbd() {
    const show = !$('#kbd').classList.contains('show');
    $('#kbd').classList.toggle('show', show);
    $('#kbdbtn').classList.toggle('on', show);
    try { localStorage.setItem('m-term-kbd', show ? '1' : '0'); } catch (_) {}
    setNativeKbd(show);   // Terminal-Feld hart unterdrückt halten (readonly/blur)
    fitViewport();
    // KEIN Fokus aufs Terminal-Feld — die QWERTZ-Tasten senden über den Daten-Kanal.
  }

  // ── Darstellung (Dunkel/Kontrast/Hell) ── reiner CSS-Filter, kein Reconnect ──
  const TERM_THEME_CYCLE = ['dark', 'contrast', 'light'];
  const TERM_THEME_ICON  = { dark: '🌙', contrast: '🔆', light: '☀️' };
  const TERM_THEME_TITLE = { dark: 'Dunkel (Standard) – tippen für mehr Kontrast',
                              contrast: 'Dunkel + Kontrast – tippen für Hell',
                              light: 'Hell – tippen für Dunkel' };
  function applyTermTheme(theme) {
    if (!TERM_THEME_CYCLE.includes(theme)) theme = 'dark';
    const frame = $('#m-term'), btn = $('#term-theme-btn');
    if (frame) { frame.classList.toggle('contrast', theme === 'contrast'); frame.classList.toggle('light', theme === 'light'); }
    if (btn) { btn.textContent = TERM_THEME_ICON[theme]; btn.title = TERM_THEME_TITLE[theme]; }
    log('Darstellung:', theme);
  }
  function cycleTermTheme() {
    let cur = 'dark';
    try { cur = localStorage.getItem('m-term-theme') || 'dark'; } catch (_) {}
    const next = TERM_THEME_CYCLE[(TERM_THEME_CYCLE.indexOf(cur) + 1) % TERM_THEME_CYCLE.length];
    try { localStorage.setItem('m-term-theme', next); } catch (_) {}
    applyTermTheme(next);
  }
  (function () {
    let saved = 'dark';
    try { saved = localStorage.getItem('m-term-theme') || 'dark'; } catch (_) {}
    applyTermTheme(saved);
  })();

  // ── Touch-Modus: tmux-Maus für DIESE Projekt-Session umschalten ─────────
  // "mouse on" fängt am iPhone jede Touch-Geste ab → kein natives Scrollen/
  // Selektieren/Kopieren. Wir senden Prefix (Ctrl-b) + "T" ans xterm; das löst
  // die tmux-Bindung `bind T set mouse` (session-scoped, ~/.tmux.conf) aus.
  // tmux ist die Wahrheit (Zustand überlebt Reload); Knopf-Optik merken wir
  // pro Board in localStorage.
  function sendTmuxKey(ch) {
    // Prefix (Ctrl-b = \x02) + Kommandotaste über den Daten-Kanal an tmux.
    mSendData('\x02');
    setTimeout(() => mSendData(ch), 40);
  }
  function toggleTouch() {
    const key = 'm-term-touch-' + (curBoard ? curBoard.id : '_');
    let on = false; try { on = localStorage.getItem(key) === '1'; } catch (_) {}
    sendTmuxKey('T');
    on = !on;
    try { localStorage.setItem(key, on ? '1' : '0'); } catch (_) {}
    $('#touchbtn').classList.toggle('on', on);
    toast(on ? 'Touch-Modus AN – jetzt nativ scrollen/kopieren' : 'Touch-Modus AUS – Desktop-Maus', 'ok');
    log('Touch-Modus =', on ? 'an (tmux-Maus aus)' : 'aus (tmux-Maus an)');
  }

  // ── iPhone-Tastatur: Ansicht auf den sichtbaren Bereich begrenzen ──────
  // Fährt die iOS-Tastatur hoch, schrumpft visualViewport.height → wir setzen
  // #view-board exakt auf den sichtbaren Ausschnitt (top=offsetTop, height),
  // damit die Eingabezeile + Tastenleisten nicht verdeckt werden.
  let _nudgeT;
  function nudgeTerm() {
    clearTimeout(_nudgeT);
    _nudgeT = setTimeout(() => { const f = $('#m-term'); try { f.contentWindow.dispatchEvent(new Event('resize')); } catch (_) {} }, 60);
  }
  function fitViewport() {
    if (!document.body.classList.contains('term-active')) return;
    const vv = window.visualViewport, vb = $('#view-board');
    if (!vv || !vb) return;
    vb.style.top = vv.offsetTop + 'px';
    vb.style.height = vv.height + 'px';
    nudgeTerm();
  }
  function clearViewport() {
    const vb = $('#view-board'); if (vb) { vb.style.top = ''; vb.style.height = ''; }
  }

  function showOverview() {
    $('#view-title').textContent = 'Projekte';
    // Terminal-Client trennen, wenn man das Projekt verlässt (tmux-Session bleibt)
    const frame = $('#m-term'); if (frame) { frame.src = 'about:blank'; termLoaded = false; }
    document.body.classList.remove('term-active'); clearViewport();  // Vollbild-Terminal verlassen
    curBoard = null;
    showView('overview');
  }
  function showView(v) {
    $('#view-overview').classList.toggle('hidden', v !== 'overview');
    $('#view-board').classList.toggle('hidden', v !== 'board');
    $('.topbar .search').style.display = v === 'overview' ? '' : 'none';
    $('#cat-chips').style.display = v === 'overview' ? '' : 'none';
    $('#prio-chips').style.display = v === 'overview' ? '' : 'none';
    if (v === 'overview') window.scrollTo(0, 0);
  }

  // ---- Schnell-Erfassung ----
  function openSheet(which) { $('#sheet-' + which).classList.remove('hidden'); }
  function closeSheets() { $$('.sheet').forEach(s => s.classList.add('hidden')); }

  async function submitIdea() {
    const name = $('#cap-name').value.trim();
    const desc = $('#cap-desc').value.trim();
    if (!name) { toast('Bitte einen Titel eingeben', 'err'); return; }
    overlay(true, 'Idee wird angelegt…');
    try {
      const data = await jpost('/boards', { name, description: desc });
      closeSheets(); $('#cap-name').value = ''; $('#cap-desc').value = '';
      toast('✅ Idee angelegt', 'ok');
      await loadOverview();
      if (data && data.board_id) gotoBoard(data.board_id);
    } catch (e) { toast('❌ ' + e.message, 'err'); } finally { overlay(false); }
  }

  // Bildkompression (wie foto.html) — spart Upload + Backend-Last
  function compress(file, maxPx, q) {
    return new Promise((resolve, reject) => {
      const img = new Image(), url = URL.createObjectURL(file);
      img.onload = () => {
        let { width: w, height: h } = img;
        if (w > h && w > maxPx) { h = h * maxPx / w; w = maxPx; }
        else if (h > maxPx) { w = w * maxPx / h; h = maxPx; }
        const cv = document.createElement('canvas'); cv.width = w; cv.height = h;
        cv.getContext('2d').drawImage(img, 0, 0, w, h);
        URL.revokeObjectURL(url);
        resolve(cv.toDataURL('image/jpeg', q));
      };
      img.onerror = reject; img.src = url;
    });
  }
  function getGPS() {
    return new Promise((resolve) => {
      if (!navigator.geolocation) return resolve(null);
      navigator.geolocation.getCurrentPosition(
        p => resolve({ lat: p.coords.latitude, lon: p.coords.longitude }),
        () => resolve(null), { timeout: 4000, maximumAge: 60000 });
    });
  }
  async function handlePhoto(input) {
    const file = input.files[0]; if (!file) return; input.value = '';
    overlay(true, 'Foto wird hochgeladen…');
    try {
      const photo = await compress(file, 1200, 0.82);
      const note = $('#photo-note').value.trim();
      const gps = await getGPS();
      const payload = { photo, title: '', note };
      if (gps) Object.assign(payload, gps);
      const data = await jpost('/project-from-photo', payload);
      closeSheets(); $('#photo-note').value = '';
      toast('✅ Idee gespeichert — KI-Analyse läuft', 'ok');
      await loadOverview();
      if (data && data.board_id) setTimeout(() => gotoBoard(data.board_id), 500);
    } catch (e) { toast('❌ ' + e.message, 'err'); } finally { overlay(false); }
  }

  // ---- Tabbar ----
  function onTab(tab) {
    $$('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
    if (tab === 'overview') { goOverview(); }
    else if (tab === 'capture') { openSheet('capture'); }
    else if (tab === 'photo') { openSheet('photo'); }
  }

  // ---- Shortcut-Leiste (fertige Prompts → Terminal) ----
  function renderShortcuts() {
    const box = $('#m-shortcuts');
    if (!box) return;
    const list = Array.isArray(window.TERM_SHORTCUTS) ? window.TERM_SHORTCUTS : [];
    box.innerHTML = '';
    if (!list.length) { box.style.display = 'none'; return; }
    box.style.display = '';
    list.forEach(sc => {
      if (!sc || !sc.text) return;
      const btn = document.createElement('button');
      btn.className = 'sc-btn';
      btn.textContent = sc.label || sc.text;
      btn.title = sc.text;
      btn.addEventListener('pointerdown', e => {
        e.preventDefault();
        const send = sc.send !== false;
        if (send) {
          if (mSendData(sc.text + '\r')) log('Shortcut gesendet:', JSON.stringify(sc.text));
        } else {
          const i = $('#m-input');
          if (i) { i.value = sc.text; i.focus(); }
          else if (mSendData(sc.text)) log('Shortcut eingefügt:', JSON.stringify(sc.text));
        }
      });
      box.appendChild(btn);
    });
    log('Shortcuts gerendert:', list.length);
  }

  // ---- Init ----
  function init() {
    $('#reload-btn').onclick = loadOverview;
    $('#search').addEventListener('input', e => { search = e.target.value.trim(); renderProjects(); });
    // Board-Detail: Zurück + Segment-Umschalter Liste/Terminal
    $('#back-btn').onclick = goOverview;
    $('#board-seg').addEventListener('click', e => { const b = e.target.closest('.seg-btn'); if (b) setBoardMode(b.dataset.mode); });

    // ── Eingabe-Zeile: native iPhone-Tastatur → Text bei Enter/„Senden" ins Terminal ──
    const sendInput = () => {
      const i = $('#m-input'); if (!i) return;
      let v = i.value;
      const cr = $('#m-input-cr');
      if (cr && cr.checked) v += '\r';
      if (v && mSendData(v)) log('Eingabe gesendet:', JSON.stringify(v));
      i.value = '';
      i.focus();   // Tastatur offen halten für die nächste Zeile
    };
    if ($('#m-input')) $('#m-input').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); sendInput(); } });
    if ($('#m-input-send')) $('#m-input-send').addEventListener('click', e => { e.preventDefault(); sendInput(); });

    // ── Shortcut-Leiste: fertige Prompts aus window.TERM_SHORTCUTS (/terminal-shortcuts.js) ──
    renderShortcuts();

    // ── Terminal-Tastaturen (alle pointerdown statt click → Terminal behält Fokus) ──
    // Sonder-Tastenleiste (#keys): Esc/Tab/Ctrl/Alt/Pfeile/Enter + aufklappbare Reihen (☰)
    $('#keys').addEventListener('pointerdown', e => {
      const b = e.target.closest('button'); if (!b) return;
      e.preventDefault();
      if (b.id === 'morebtn') { toggleMore(); return; }
      if (b.dataset.mod)      { toggleMod(b.dataset.mod, b); return; }
      press({ key: b.dataset.key, ch: b.dataset.ch, ctrl: b.dataset.ctrl === '1', alt: b.dataset.alt === '1' });
    });
    // Volle QWERTZ-Tastatur (#kbd)
    $('#kbd').addEventListener('pointerdown', e => {
      const b = e.target.closest('button'); if (!b) return;
      if (b.id === 'shiftbtn' || b.id === 'symbtn') return;  // eigene Handler unten
      e.preventDefault();
      if (b.dataset.key) { press({ key: b.dataset.key }); return; }
      let ch = b.dataset.ch; if (ch == null) return;
      if (b.classList.contains('ltr') && shiftOn) ch = ch.toUpperCase();
      press({ ch });
      if (b.classList.contains('ltr') && shiftOn) { shiftOn = false; applyShift(); }   // Shift gilt für 1 Buchstaben
    });
    // Kopf-Werkzeuge: ⌨ QWERTZ ein/aus, ↻ Terminal neu laden
    $('#kbdbtn').addEventListener('pointerdown', e => { e.preventDefault(); toggleKbd(); });
    $('#touchbtn').addEventListener('pointerdown', e => { e.preventDefault(); toggleTouch(); });
    $('#term-theme-btn').addEventListener('pointerdown', e => { e.preventDefault(); cycleTermTheme(); });
    $('#term-reload').addEventListener('pointerdown', e => {
      e.preventDefault();
      const f = $('#m-term'); try { f.contentWindow.location.reload(); } catch (_) { f.src = f.src; }
      log('Terminal neu geladen');
    });
    // Shift + Symbol-/Buchstaben-Ebene der QWERTZ-Tastatur
    $('#shiftbtn').addEventListener('pointerdown', e => { e.preventDefault(); shiftOn = !shiftOn; applyShift(); });
    $('#symbtn').addEventListener('pointerdown', e => {
      e.preventDefault();
      const sym = !$('#kbd .lay-sym').classList.contains('show');
      $('#kbd .lay-sym').classList.toggle('show', sym);
      $('#kbd .lay-abc').classList.toggle('show', !sym);
      $('#symbtn').textContent = sym ? 'abc' : '#+=';
      $('#symbtn').classList.toggle('on', sym);
    });
    // gespeicherten Aufklapp-/QWERTZ-Zustand wiederherstellen (Default: zugeklappt, QWERTZ aus)
    (function () {
      let more = false, kb = false;
      try { more = localStorage.getItem('m-term-more') === '1'; kb = localStorage.getItem('m-term-kbd') === '1'; } catch (_) {}
      applyMore(more);
      if (kb) { $('#kbd').classList.add('show'); $('#kbdbtn').classList.add('on'); }
    })();
    // iPhone-Tastatur: Ansicht an den sichtbaren Bereich anpassen, wenn sie auf-/zufährt
    if (window.visualViewport) {
      window.visualViewport.addEventListener('resize', fitViewport);
      window.visualViewport.addEventListener('scroll', fitViewport);
    }
    window.addEventListener('resize', fitViewport);
    $$('.tab').forEach(t => t.onclick = () => onTab(t.dataset.tab));
    $$('[data-close]').forEach(b => b.onclick = closeSheets);
    $$('.sheet').forEach(s => s.addEventListener('click', e => { if (e.target === s) closeSheets(); }));
    $('#cap-submit').onclick = submitIdea;
    $('#photo-pick').onclick = () => $('#photo-input').click();
    $('#photo-input').addEventListener('change', e => handlePhoto(e.target));
    // Tab-Reset wenn Sheet zugeht
    new MutationObserver(() => {
      if ($$('.sheet:not(.hidden)').length === 0) {
        $$('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === 'overview'));
      }
    }).observe(document.body, { attributes: true, subtree: true, attributeFilter: ['class'] });
    // Browser-Navigation (Zurück/Vor) rendert über den Hash
    window.addEventListener('hashchange', route);
    // Deep-Link/Reload mit #b=…: erst Projekte laden (Board-Name), dann Board wiederherstellen
    loadOverview().then(() => { if (location.hash) route(); });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
