/* leichen-cards.js — Kanban-Karten aus einem Leichen-Projekt einem Zielprojekt zuordnen.
 *
 * Nutzt window.API (api.js) + window.escHtml (esc.js), beide von leichen.html vor
 * diesem Script geladen. Liest/schreibt `allProjects` aus leichen.html (gleicher
 * globaler Skript-Scope der Seite) fürs Nachschlagen des Quellprojekt-Titels und
 * zum Ausschliessen bereits inaktiver Projekte aus der Ziel-Auswahl.
 */
const escHtml = window.escHtml;

let cardMoveSourceId = null;

async function openCardMoveModal(sourceId) {
  console.log('[leichen-cards] Öffne Karten-Auswahl für', sourceId);
  cardMoveSourceId = sourceId;

  const source = (typeof allProjects !== 'undefined' ? allProjects : []).find(p => p.id === sourceId);
  document.getElementById('card-move-title').textContent =
    `Karten aus „${source ? source.title : sourceId}" verschieben`;

  const listEl = document.getElementById('card-move-list');
  const targetEl = document.getElementById('card-move-target');
  listEl.innerHTML = 'Lädt…';
  targetEl.innerHTML = '';

  try {
    const [board, boardsResp] = await Promise.all([
      API.get('/kanban-api?board=' + encodeURIComponent(sourceId)),
      API.fetchBoards({ all: true }),
    ]);

    let html = '';
    for (const col of (board.columns || [])) {
      const cards = (col.cards || []).filter(c =>
        c.id !== 'claudemd-description' && !c.archived_at && !c.rejected);
      if (!cards.length) continue;
      html += `<div class="card-move-col-title">${escHtml(col.title || col.id)}</div>`;
      for (const c of cards) {
        html += `<label class="card-move-item">
          <input type="checkbox" value="${escHtml(c.id)}">
          ${escHtml(c.title || '(ohne Titel)')}
        </label>`;
      }
    }
    listEl.innerHTML = html || '<div class="card-move-empty">Keine offenen Karten in diesem Board.</div>';

    const inactiveIds = new Set((typeof allProjects !== 'undefined' ? allProjects : []).map(p => p.id));
    const targets = (boardsResp.boards || [])
      .filter(b => b.id !== sourceId && !b.archived && !inactiveIds.has(b.id))
      .sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id, 'de'));
    targetEl.innerHTML = targets.length
      ? targets.map(b => `<option value="${escHtml(b.id)}">${escHtml(b.name || b.id)}</option>`).join('')
      : '';
    if (!targets.length) {
      targetEl.innerHTML = '<option value="">— keine aktiven Zielprojekte gefunden —</option>';
    }

    document.getElementById('card-move-overlay').classList.add('open');
  } catch (e) {
    console.error('[leichen-cards] Laden fehlgeschlagen:', e);
    alert('Fehler beim Laden der Karten: ' + e.message);
  }
}

function closeCardMoveModal() {
  document.getElementById('card-move-overlay').classList.remove('open');
  cardMoveSourceId = null;
}

async function confirmCardMove() {
  const checked = Array.from(document.querySelectorAll('#card-move-list input[type=checkbox]:checked'))
    .map(cb => cb.value);
  const targetId = document.getElementById('card-move-target').value;

  if (!checked.length) { alert('Bitte mindestens eine Karte auswählen.'); return; }
  if (!targetId) { alert('Bitte ein Zielprojekt wählen.'); return; }

  console.log('[leichen-cards] Verschiebe', checked.length, 'Karte(n) von', cardMoveSourceId, 'nach', targetId);
  try {
    const result = await API.moveCards(cardMoveSourceId, checked, targetId);
    console.log('[leichen-cards] Ergebnis:', result);
    closeCardMoveModal();
    if (typeof loadProjects === 'function') loadProjects();
    const info = result.created_subboard
      ? `${result.moved.length} Karte(n) als neues Unterprojekt "${result.created_subboard}" übernommen.`
      : `${result.moved.length} Karte(n) verschoben.`;
    alert(info);
  } catch (e) {
    console.error('[leichen-cards] Verschieben fehlgeschlagen:', e);
    alert('Fehler beim Verschieben: ' + e.message);
  }
}
