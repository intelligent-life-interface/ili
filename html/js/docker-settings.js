// docker-settings.js — "Docker / project containers" section of ai-settings.html.
//
// Talks to /api/docker/* (app/api/docker_config.py). All visible text comes from the
// language files (docker.* keys) via window.t(); the HTML carries German fallbacks
// only through data-i18n. Nothing here is rendered with innerHTML from server data.
(function () {
    'use strict';
    const log = (...a) => console.debug('[docker-settings]', ...a);
    const $ = (id) => document.getElementById(id);
    const T = (key, vars) => {
        let s = (typeof window.t === 'function') ? window.t(key, key) : key;
        if (vars) Object.keys(vars).forEach((k) => { s = s.split('{' + k + '}').join(vars[k] == null ? '' : String(vars[k])); });
        return s;
    };
    const say = (msg, isErr) => (typeof window.toast === 'function') ? window.toast(msg, !!isErr) : log(msg);

    let lastState = null;

    function formValues() {
        return {
            mode: $('docker-mode').value,
            host: $('docker-host').value.trim(),
            tls_verify: $('docker-tls').checked,
            cert_path: $('docker-cert').value.trim(),
        };
    }

    function fillForm(cfg) {
        $('docker-mode').value = cfg.mode || 'auto';
        $('docker-host').value = cfg.host || '';
        $('docker-tls').checked = !!cfg.tls_verify;
        $('docker-cert').value = cfg.cert_path || '';
        syncRows();
    }

    // Host/TLS/cert only make sense in remote mode.
    function syncRows() {
        const remote = $('docker-mode').value === 'remote';
        ['docker-host-row', 'docker-tls-row', 'docker-cert-row'].forEach((id) => { $(id).hidden = !remote; });
        renderHowto();
    }

    function renderHowto() {
        const mode = $('docker-mode').value;
        const st = lastState || {};
        const [from, to] = st.port_range || [8100, 8119];
        $('docker-howto').textContent = T('docker.howto.' + mode, { ports_from: from, ports_to: to });
        $('docker-warn').hidden = (mode === 'off');
    }

    function renderStatus(st, fromTest) {
        lastState = st;
        const dot = $('docker-dot');
        const text = $('docker-status-text');
        const meta = $('docker-meta');
        dot.className = 'docker-dot';
        let line;
        if (st.mode === 'off') {
            line = T('docker.status.off');
        } else if (st.reachable && st.engine) {
            dot.classList.add('ok');
            line = T('docker.status.ok', {
                engine: st.engine.name, version: st.engine.version,
                os: st.engine.os, arch: st.engine.arch,
                source: T('docker.source.' + (st.probe_source || 'api')),
            });
        } else if (!st.docker_host && st.mode === 'auto') {
            line = T('docker.status.none');
        } else {
            dot.classList.add('fail');
            line = T('docker.status.fail', { error: st.error || '?' });
        }
        text.removeAttribute('data-i18n');  // live text — a later I18n.apply() must not reset it to "loading"
        text.textContent = (fromTest ? T('docker.test.prefix') + ' ' : '') + line;
        const bits = [];
        if (st.docker_host) bits.push('DOCKER_HOST=' + st.docker_host);
        if (st.overlay && st.overlay !== 'none') bits.push(T('docker.overlay.' + st.overlay));
        if (st.projects_host_dir) bits.push('PROJECTS_HOST_DIR=' + st.projects_host_dir);
        if (st.port_range) bits.push(T('docker.ports', { from: st.port_range[0], to: st.port_range[1] }));
        meta.textContent = bits.join(' · ');
        renderHowto();
        log('status', st.mode, st.overlay, st.reachable ? 'reachable' : 'not reachable', 'via', st.probe_source);
    }

    async function load() {
        try {
            const r = await fetch('/api/docker/status');
            if (!r.ok) throw new Error(await r.text());
            const st = await r.json();
            fillForm(st);
            renderStatus(st, false);
        } catch (e) {
            log('load failed', e);
            $('docker-status-text').textContent = T('docker.status.fail', { error: e.message });
            $('docker-dot').className = 'docker-dot fail';
        }
    }

    async function test() {
        const btn = $('docker-btn-test');
        btn.disabled = true;
        $('docker-status-text').textContent = T('docker.status.loading');
        try {
            const r = await fetch('/api/docker/test', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(formValues()),
            });
            const body = await r.json().catch(() => ({}));
            if (!r.ok) throw new Error(T(body.error || body.detail || 'docker.test.fail'));
            renderStatus(body, true);
            say(body.reachable ? T('docker.test.ok') : T('docker.test.fail') + ': ' + (body.error || ''), !body.reachable);
        } catch (e) {
            log('test failed', e);
            say(T('docker.test.fail') + ': ' + e.message, true);
        } finally {
            btn.disabled = false;
        }
    }

    async function save() {
        const btn = $('docker-btn-save');
        btn.disabled = true;
        try {
            const r = await fetch('/api/docker/config', {
                method: 'PUT', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(formValues()),
            });
            const body = await r.json().catch(() => ({}));
            if (!r.ok) throw new Error(T(body.error || body.detail || 'docker.test.fail'));
            fillForm(body.config || {});
            renderStatus(body.state || {}, false);
            say(T('docker.saved'));
        } catch (e) {
            log('save failed', e);
            say(e.message, true);
        } finally {
            btn.disabled = false;
        }
    }

    // ── MCP server for container control ────────────────────────────────────────
    // Talks to /api/docker/mcp/* (app/api/docker_config.py -> claude_cli_bridge.py
    // in the terminal). Setup only makes sense once Docker itself is reachable
    // (lastState.reachable, set by renderStatus above); Remove always stays enabled
    // so the switch can be turned off even when Docker is down.
    function renderMcp(st) {
        const dot = $('docker-mcp-dot');
        const text = $('docker-mcp-status-text');
        const btnSetup = $('docker-mcp-btn-setup');
        const btnRemove = $('docker-mcp-btn-remove');
        dot.className = 'docker-dot';
        let line;
        if (st.error === 'terminal_outdated') {
            line = T('docker.mcp.status.outdated');
        } else if (st.error === 'terminal_unreachable') {
            dot.classList.add('fail');
            line = T('docker.mcp.status.unreachable');
        } else if (st.configured) {
            dot.classList.add('ok');
            line = T('docker.mcp.status.on');
        } else {
            line = T('docker.mcp.status.off');
        }
        text.removeAttribute('data-i18n');
        text.textContent = line;
        const dockerReachable = !!(lastState && lastState.reachable);
        btnSetup.disabled = !dockerReachable || !!st.configured;
        btnSetup.title = dockerReachable ? '' : T('docker.mcp.disabled.unreachable');
        btnRemove.disabled = !st.configured;
        log('mcp status', st);
    }

    async function loadMcp() {
        if (!$('docker-mcp-dot')) return;
        try {
            const r = await fetch('/api/docker/mcp/status');
            const st = await r.json();
            renderMcp(st);
        } catch (e) {
            log('mcp status load failed', e);
            renderMcp({ configured: false, error: 'terminal_unreachable' });
        }
    }

    async function setupMcp() {
        const btn = $('docker-mcp-btn-setup');
        btn.disabled = true;
        try {
            const r = await fetch('/api/docker/mcp/setup', { method: 'POST' });
            const body = await r.json().catch(() => ({}));
            if (!r.ok || !body.ok) throw new Error(T(body.detail || body.error || 'docker.mcp.setup.fail'));
            say(T('docker.mcp.setup.ok'));
            await loadMcp();
        } catch (e) {
            log('mcp setup failed', e);
            say(T('docker.mcp.setup.fail') + ': ' + e.message, true);
            await loadMcp();
        }
    }

    async function removeMcp() {
        const btn = $('docker-mcp-btn-remove');
        btn.disabled = true;
        try {
            const r = await fetch('/api/docker/mcp/remove', { method: 'POST' });
            const body = await r.json().catch(() => ({}));
            if (!r.ok || !body.ok) throw new Error(T(body.detail || body.error || 'docker.mcp.remove.fail'));
            say(T('docker.mcp.remove.ok'));
        } catch (e) {
            log('mcp remove failed', e);
            say(T('docker.mcp.remove.fail') + ': ' + e.message, true);
        } finally {
            await loadMcp();
        }
    }

    function copyHowto() {
        const txt = $('docker-howto').textContent || '';
        if (!navigator.clipboard) return say(T('docker.copy.fail'), true);
        navigator.clipboard.writeText(txt).then(() => say(T('docker.copied'))).catch((e) => say(T('docker.copy.fail') + ': ' + e.message, true));
    }

    // ── Reservierte Ports ─────────────────────────────────────────────────────
    // Ein Container kann einen Port belegen, nicht reservieren. Die Vergabe führt
    // ili (siehe app/services/project_ports_service.py); hier wird sie nur gezeigt
    // und geändert. Keine Server-Daten via innerHTML — alles per textContent.
    async function loadPorts() {
        if (!$('ports-range')) return;
        try {
            const [pr, br] = await Promise.all([
                fetch('/api/docker/ports', { cache: 'no-store' }),
                fetch('/boards', { cache: 'no-store' }).catch(() => null),
            ]);
            if (!pr.ok) throw new Error('HTTP ' + pr.status);
            const st = await pr.json();
            const boards = br && br.ok ? await br.json() : [];
            renderPorts(st, Array.isArray(boards) ? boards : (boards.boards || []));
        } catch (e) {
            log('Portvergabe nicht ladbar:', e.message);
            $('ports-range').textContent = T('ports.fail', { error: e.message });
        }
    }

    function renderPorts(st, boards) {
        $('ports-range').textContent = T('ports.range', {
            from: st.range[0], to: st.range[1], free: st.free_count, total: st.total,
        });
        const tbody = $('ports-tbody');
        tbody.textContent = '';
        const named = {};
        boards.forEach((b) => { if (b && b.id) named[b.id] = b.title || b.name || b.id; });
        st.assignments.forEach((a) => {
            const tr = document.createElement('tr');
            const tdBoard = document.createElement('td');
            tdBoard.textContent = named[a.board] ? named[a.board] + ' (' + a.board + ')' : a.board;
            const tdPort = document.createElement('td');
            tdPort.textContent = String(a.port);
            const tdAct = document.createElement('td');
            const btn = document.createElement('button');
            btn.className = 'btn';
            btn.textContent = T('ports.btn.release');
            btn.addEventListener('click', () => releasePort(a.board));
            tdAct.appendChild(btn);
            tr.append(tdBoard, tdPort, tdAct);
            tbody.appendChild(tr);
        });
        $('ports-table').hidden = st.assignments.length === 0;

        // Auswahl: nur Boards ohne Port, sonst vergäbe man doppelt.
        const sel = $('ports-board');
        const taken = new Set(st.assignments.map((a) => a.board));
        sel.textContent = '';
        boards.filter((b) => b && b.id && !taken.has(b.id)).forEach((b) => {
            const o = document.createElement('option');
            o.value = b.id;
            o.textContent = (b.title || b.name || b.id) + ' (' + b.id + ')';
            sel.appendChild(o);
        });
        const none = sel.options.length === 0;
        sel.disabled = none;
        $('ports-assign').disabled = none || st.free_count === 0;
    }

    async function assignPort() {
        const board = $('ports-board').value;
        if (!board) return;
        try {
            const r = await fetch('/api/docker/ports?board=' + encodeURIComponent(board), { method: 'POST' });
            const body = await r.json();
            if (!r.ok || !body.ok) throw new Error(body.reason || body.detail || ('HTTP ' + r.status));
            say(T('ports.assigned', { board: board, port: body.port }));
            loadPorts();
        } catch (e) {
            say(T('ports.assign.fail', { error: e.message }), true);
        }
    }

    async function releasePort(board) {
        try {
            const r = await fetch('/api/docker/ports?board=' + encodeURIComponent(board), { method: 'DELETE' });
            if (!r.ok) throw new Error('HTTP ' + r.status);
            say(T('ports.released', { board: board }));
            loadPorts();
        } catch (e) {
            say(T('ports.release.fail', { error: e.message }), true);
        }
    }

    async function loadAll() {
        await load();      // fills lastState.reachable first — renderMcp needs it
        await loadMcp();
    }

    function init() {
        if (!$('docker-mode')) return;  // section not on this page
        if ($('ports-assign')) $('ports-assign').addEventListener('click', assignPort);
        loadPorts();
        $('docker-mode').addEventListener('change', syncRows);
        $('docker-btn-test').addEventListener('click', () => test().then(loadMcp));
        $('docker-btn-save').addEventListener('click', () => save().then(loadMcp));
        $('docker-copy').addEventListener('click', copyHowto);
        if ($('docker-mcp-btn-setup')) $('docker-mcp-btn-setup').addEventListener('click', setupMcp);
        if ($('docker-mcp-btn-remove')) $('docker-mcp-btn-remove').addEventListener('click', removeMcp);
        if ($('docker-mcp-btn-refresh')) $('docker-mcp-btn-refresh').addEventListener('click', loadMcp);
        syncRows();
        loadAll();
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
