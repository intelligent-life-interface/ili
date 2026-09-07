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

    function copyHowto() {
        const txt = $('docker-howto').textContent || '';
        if (!navigator.clipboard) return say(T('docker.copy.fail'), true);
        navigator.clipboard.writeText(txt).then(() => say(T('docker.copied'))).catch((e) => say(T('docker.copy.fail') + ': ' + e.message, true));
    }

    function init() {
        if (!$('docker-mode')) return;  // section not on this page
        $('docker-mode').addEventListener('change', syncRows);
        $('docker-btn-test').addEventListener('click', test);
        $('docker-btn-save').addEventListener('click', save);
        $('docker-copy').addEventListener('click', copyHowto);
        syncRows();
        load();
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
