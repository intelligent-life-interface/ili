/* Drossel-Panel für /automat.html — Limits des Kanban-Automaten im Browser einstellen.
 *
 * Backend: GET/PUT /api/automat/limits, POST /api/automat/limits/reset
 * (Router app/api/automat.py → app/services/automat_limits_service.py →
 *  automat_limits.json, die der Automat bei jedem Tick liest).
 *
 * Bewusst keine eigene Grenzwert-Liste hier: min/max/Default/Beschreibung liefert das
 * Backend mit, damit es nur EINE Quelle gibt (limits.py im Automaten).
 */
(function () {
  'use strict';

  const log = (...a) => console.debug('[automat-limits]', ...a);
  const esc = window.escHtml;
  const toast = window.toast || (m => log('toast:', m));

  // Reihenfolge + Klartext-Beschriftung; alles Weitere kommt vom Backend.
  const ORDER = [
    ['max_starts_per_day', 'Starts pro Tag'],
    ['max_parallel', 'Parallel max. (harte Grenze)'],
    ['parallel_day', 'Parallel tagsüber'],
    ['parallel_night', 'Parallel nachts'],
    ['board_cooldown_s', 'Board-Cooldown (Sek.)'],
    ['max_refunds_per_day', 'Refunds pro Tag'],
    ['noop_refund_s', 'No-Op-Grenze (Sek.)'],
    ['worker_timeout_s', 'Worker-Timeout (Sek.)'],
    ['fable_enabled', '🧬 Fable-Optimierung (1=an, 0=aus)'],
    ['fable_max_runs_per_day', '🧬 Fable-Läufe pro Tag max.'],
  ];

  let spec = null;   // Antwort von GET /api/automat/limits

  function fmtSeconds(s) {
    if (s < 60) return `${s} s`;
    if (s < 3600) return `${Math.round(s / 60)} min`;
    const h = s / 3600;
    return `${Number.isInteger(h) ? h : h.toFixed(1)} h`;
  }

  function render() {
    const box = document.getElementById('limits');
    if (!box || !spec) return;
    const L = spec.limits;

    const rows = ORDER.filter(([key]) => L[key]).map(([key, label]) => {
      const it = L[key];
      const isTime = key.endsWith('_s');
      const changed = it.value !== it.default;
      return `
        <div class="lim-row">
          <label for="lim-${key}">
            ${esc(label)}
            ${changed ? `<span class="lim-badge" title="Default: ${it.default}">geändert</span>` : ''}
          </label>
          <div class="lim-input">
            <input type="number" id="lim-${key}" data-key="${key}"
                   value="${it.value}" min="${it.min}" max="${it.max}" step="1">
            <span class="lim-range">${it.min}–${it.max}${isTime ? ` · ${fmtSeconds(it.value)}` : ''}</span>
          </div>
          <div class="lim-desc">${esc(it.description)}</div>
        </div>`;
    }).join('');

    box.innerHTML = `
      <div class="lim-panel">
        <div class="lim-grid">${rows}</div>
        <div class="lim-actions">
          <button id="lim-save" class="lim-btn lim-btn-primary">💾 Speichern</button>
          <button id="lim-reset" class="lim-btn">↺ Auf Defaults zurücksetzen</button>
          <span class="lim-note">Greift beim nächsten Tick (max. 5&nbsp;min). Datei: <code>${esc(spec.file)}</code></span>
        </div>
      </div>`;

    document.getElementById('lim-save').addEventListener('click', save);
    document.getElementById('lim-reset').addEventListener('click', reset);
    // Sekunden-Umrechnung live mitführen
    box.querySelectorAll('input[type=number]').forEach(inp => {
      inp.addEventListener('input', () => {
        const key = inp.dataset.key;
        if (!key.endsWith('_s')) return;
        const rng = inp.parentElement.querySelector('.lim-range');
        const it = L[key];
        rng.textContent = `${it.min}–${it.max} · ${fmtSeconds(Number(inp.value) || 0)}`;
      });
    });
  }

  async function load() {
    const box = document.getElementById('limits');
    try {
      const r = await fetch('/api/automat/limits');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      spec = await r.json();
      log('geladen', spec.limits);
      render();
    } catch (e) {
      log('Laden fehlgeschlagen', e);
      if (box) box.innerHTML = `<div class="empty">Drossel-Werte nicht ladbar (${esc(String(e))}).
        Läuft der Automat unter ~/containers/kanban-automat?</div>`;
    }
  }

  async function save() {
    const body = {};
    document.querySelectorAll('#limits input[type=number]').forEach(inp => {
      const v = Number(inp.value);
      if (Number.isFinite(v)) body[inp.dataset.key] = Math.round(v);
    });
    log('speichern', body);
    try {
      const r = await fetch('/api/automat/limits', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const res = await r.json();
      if (!r.ok) throw new Error(res.detail || `HTTP ${r.status}`);
      const n = Object.keys(res.changed || {}).length;
      toast(n ? `Gespeichert — ${n} Wert(e) geändert` : 'Gespeichert (nichts geändert)');
      log('gespeichert', res);
      await load();
    } catch (e) {
      log('Speichern fehlgeschlagen', e);
      toast('Fehler beim Speichern: ' + e);
    }
  }

  async function reset() {
    if (!confirm('Alle Drossel-Werte auf die Code-Defaults zurücksetzen?')) return;
    try {
      const r = await fetch('/api/automat/limits/reset', { method: 'POST' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      toast('Auf Defaults zurückgesetzt');
      log('zurückgesetzt');
      await load();
    } catch (e) {
      log('Reset fehlgeschlagen', e);
      toast('Fehler beim Zurücksetzen: ' + e);
    }
  }

  document.addEventListener('DOMContentLoaded', load);
  if (document.readyState !== 'loading') load();
})();
