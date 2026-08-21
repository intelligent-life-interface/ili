/* api.js — zentraler API-Client für alle Dashboard-Seiten.
 *
 * Plain JS (kein Modul) — wird via <script src="/js/api.js"> geladen und
 * exponiert window.API. Alle Pfade sind RELATIV (laufen über nginx Port 80
 * → FastAPI-Backend), keine hartcodierten Ports mehr.
 *
 * Kern:    apiGet / apiPost / apiPatch / apiDelete  (JSON, Debug-Logs)
 * Domäne:  fetchBoards, fetchBoard, saveBoard, patchBoard, deleteBoard,
 *          createBoard, fetchCategories, fetchAiConfig, scanLogs,
 *          analyseBugStream, kiExplainStream (text/plain-Streams,
 *          [DONE]/[FEHLER]-Protokoll)
 */
(function () {
  'use strict';

  // ---- Kern: fetch-Wrapper mit Debug-Logs + Fehler aus error-Body --------

  async function request(method, path, body) {
    var t0 = performance.now();
    var opts = { method: method, headers: {} };
    if (body !== undefined && body !== null) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    var res;
    try {
      res = await fetch(path, opts);
    } catch (e) {
      console.debug('[api]', method, path, Math.round(performance.now() - t0) + 'ms', 'NETZWERK-FEHLER:', e.message);
      throw e;
    }
    var ms = Math.round(performance.now() - t0);
    console.debug('[api]', method, path, ms + 'ms', 'HTTP', res.status);

    if (!res.ok) {
      var msg = 'HTTP ' + res.status;
      var errData = null;
      try {
        errData = await res.json();
        if (errData && errData.error) msg = errData.error;
        else if (errData && errData.detail) msg = typeof errData.detail === 'string' ? errData.detail : JSON.stringify(errData.detail);
      } catch (e) { /* kein JSON-Body — Status-Meldung behalten */ }
      console.debug('[api]', method, path, 'Fehler:', msg);
      var err = new Error(msg);
      err.status = res.status;     // z.B. 409 = Stale-Tab (F4)
      err.body = errData;          // z.B. {error, server_rev}
      throw err;
    }

    if (res.status === 204) return null;
    var text = await res.text();
    if (!text) return null;
    try { return JSON.parse(text); }
    catch (e) {
      console.debug('[api]', method, path, 'Antwort ist kein JSON (' + text.length + ' Zeichen)');
      return text;
    }
  }

  function apiGet(path)          { return request('GET', path); }
  function apiPost(path, body)   { return request('POST', path, body); }
  function apiPatch(path, body)  { return request('PATCH', path, body); }
  function apiDelete(path)       { return request('DELETE', path); }

  // ---- Domänen-Funktionen -------------------------------------------------

  // opts: {all:true} → ?all=1, {parent:'<id>'} → ?parent=<id>
  function fetchBoards(opts) {
    opts = opts || {};
    var qs = [];
    if (opts.all) qs.push('all=1');
    if (opts.parent) qs.push('parent=' + encodeURIComponent(opts.parent));
    return apiGet('/boards' + (qs.length ? '?' + qs.join('&') : ''));
  }

  function fetchBoard(id) {
    return apiGet('/board?id=' + encodeURIComponent(id));
  }

  function saveBoard(id, data) {
    return apiPost('/board?id=' + encodeURIComponent(id), data);
  }

  function patchBoard(id, data) {
    return apiPatch('/boards/' + encodeURIComponent(id), data);
  }

  function deleteBoard(id, purge) {
    // purge=true → Backend löscht zusätzlich den Projektordner ~/Projekte/<id>
    return apiDelete('/boards/' + encodeURIComponent(id) + (purge ? '?purge=1' : ''));
  }

  function createBoard(payload) {
    return apiPost('/boards', payload);
  }

  // cardIds: string[], targetBoardId: string. Eine Karte -> landet direkt im
  // Ziel-Board. Mehrere -> Backend legt ein neues Sub-Board unter dem Ziel an.
  function moveCards(sourceBoardId, cardIds, targetBoardId) {
    return apiPost('/boards/' + encodeURIComponent(sourceBoardId) + '/move-cards',
      { card_ids: cardIds, target_board_id: targetBoardId });
  }

  function fetchCategories() {
    return apiGet('/categories');
  }

  function fetchAiConfig() {
    return apiGet('/api/ai-config');
  }

  function scanLogs(sinceHours) {
    return apiGet('/scan-logs?since=' + encodeURIComponent(sinceHours));
  }

  // GET /search-by-tag?q= — durchsucht ALLE Projekte (Index, inkl. container-
  // Projekte ohne Board) nach Name UND Tags. Liefert {query,count,results:[{id,
  // path,tags,matched,match_in}]}. Ergänzt die clientseitige Kachel-Filterung
  // um Treffer, die gar nicht im /api/dashboard-Payload stecken.
  function searchByTag(q) {
    return apiGet('/search-by-tag?q=' + encodeURIComponent(q));
  }

  // POST /analyse-bug — liest den text/plain-Stream chunk-weise.
  // onToken(text) wird pro Chunk gerufen (ohne die Marker selbst).
  // Resolved bei "[DONE]", rejected bei "[FEHLER] <msg>" oder HTTP-Fehler.
  async function analyseBugStream(payload, onToken) {
    var t0 = performance.now();
    var res = await fetch('/analyse-bug', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    console.debug('[api]', 'POST', '/analyse-bug', Math.round(performance.now() - t0) + 'ms (Header)', 'HTTP', res.status);
    if (!res.ok) {
      var msg = 'HTTP ' + res.status;
      try {
        var errData = await res.json();
        if (errData && errData.error) msg = errData.error;
      } catch (e) { /* kein JSON */ }
      throw new Error(msg);
    }

    var reader = res.body.getReader();
    var decoder = new TextDecoder();
    var chunks = 0;

    while (true) {
      var r = await reader.read();
      if (r.done) break;
      var chunk = decoder.decode(r.value, { stream: true });
      chunks++;

      if (chunk.includes('[FEHLER]')) {
        var errMsg = chunk.replace(/[\s\S]*\[FEHLER\]\s*/, '');
        console.debug('[api] /analyse-bug Stream-Fehler nach', chunks, 'Chunks:', errMsg);
        throw new Error(errMsg || 'Analyse fehlgeschlagen');
      }
      if (chunk.includes('[DONE]')) {
        var rest = chunk.replace(/\n?\[DONE\][\s\S]*/, '');
        if (rest && onToken) onToken(rest);
        console.debug('[api] /analyse-bug Stream fertig:', chunks, 'Chunks,', Math.round(performance.now() - t0) + 'ms gesamt');
        return;
      }
      if (onToken) onToken(chunk);
    }
    // Stream endete ohne [DONE] — trotzdem sauber auflösen, Inhalt ist da.
    console.debug('[api] /analyse-bug Stream beendet ohne [DONE]-Marker (', chunks, 'Chunks )');
  }

  // POST /ki-explain-stream — gleiches Protokoll wie analyseBugStream:
  // text/plain-Stream, onToken(text) pro Chunk, resolved bei "[DONE]",
  // rejected bei "[FEHLER] <msg>" oder HTTP-Fehler.
  async function kiExplainStream(payload, onToken) {
    var t0 = performance.now();
    var res = await fetch('/ki-explain-stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    console.debug('[api]', 'POST', '/ki-explain-stream', Math.round(performance.now() - t0) + 'ms (Header)', 'HTTP', res.status);
    if (!res.ok) {
      var msg = 'HTTP ' + res.status;
      try {
        var errData = await res.json();
        if (errData && errData.error) msg = errData.error;
      } catch (e) { /* kein JSON */ }
      throw new Error(msg);
    }

    var reader = res.body.getReader();
    var decoder = new TextDecoder();
    var chunks = 0;

    while (true) {
      var r = await reader.read();
      if (r.done) break;
      var chunk = decoder.decode(r.value, { stream: true });
      chunks++;

      if (chunk.includes('[FEHLER]')) {
        var errMsg = chunk.replace(/[\s\S]*\[FEHLER\]\s*/, '');
        console.debug('[api] /ki-explain-stream Stream-Fehler nach', chunks, 'Chunks:', errMsg);
        throw new Error(errMsg || 'Erklärung fehlgeschlagen');
      }
      if (chunk.includes('[DONE]')) {
        var rest = chunk.replace(/\n?\[DONE\][\s\S]*/, '');
        if (rest && onToken) onToken(rest);
        console.debug('[api] /ki-explain-stream Stream fertig:', chunks, 'Chunks,', Math.round(performance.now() - t0) + 'ms gesamt');
        return;
      }
      if (onToken) onToken(chunk);
    }
    // Stream endete ohne [DONE] — trotzdem sauber auflösen, Inhalt ist da.
    console.debug('[api] /ki-explain-stream Stream beendet ohne [DONE]-Marker (', chunks, 'Chunks )');
  }

  // ---- Export -------------------------------------------------------------

  window.API = {
    get: apiGet,
    post: apiPost,
    patch: apiPatch,
    delete: apiDelete,
    fetchBoards: fetchBoards,
    fetchBoard: fetchBoard,
    saveBoard: saveBoard,
    patchBoard: patchBoard,
    deleteBoard: deleteBoard,
    createBoard: createBoard,
    moveCards: moveCards,
    fetchCategories: fetchCategories,
    fetchAiConfig: fetchAiConfig,
    scanLogs: scanLogs,
    searchByTag: searchByTag,
    analyseBugStream: analyseBugStream,
    kiExplainStream: kiExplainStream,
  };
  console.debug('[api] API-Client geladen (window.API)');
})();
