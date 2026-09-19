// selftest.js — the "does this installation work?" button on the settings page.
//
// Same source as `ili-selftest` in the terminal: GET /api/selftest
// (app/services/selftest_service.py). Server data is rendered with textContent
// only — never innerHTML.
(function () {
    'use strict';
    const log = (...a) => console.debug('[selftest]', ...a);
    const $ = (id) => document.getElementById(id);
    const T = (key, vars) => {
        let s = (typeof window.t === 'function') ? window.t(key, key) : key;
        if (vars) Object.keys(vars).forEach((k) => { s = s.split('{' + k + '}').join(vars[k] == null ? '' : String(vars[k])); });
        return s;
    };

    function row(check) {
        const tr = document.createElement('tr');
        const mark = document.createElement('td');
        mark.textContent = check.ok ? '✅' : '❌';
        const title = document.createElement('td');
        title.textContent = check.title || check.id;
        const detail = document.createElement('td');
        detail.textContent = check.detail || '';
        if (!check.ok && check.hint) {
            const hint = document.createElement('div');
            hint.className = 'docker-meta';
            hint.textContent = '→ ' + check.hint;
            detail.appendChild(hint);
        }
        tr.append(mark, title, detail);
        return tr;
    }

    async function run() {
        const btn = $('selftest-run');
        btn.disabled = true;
        $('selftest-summary').textContent = T('selftest.running');
        try {
            const r = await fetch('/api/selftest', { cache: 'no-store' });
            if (!r.ok) throw new Error('HTTP ' + r.status);
            const d = await r.json();
            const tbody = $('selftest-tbody');
            tbody.textContent = '';
            (d.checks || []).forEach((c) => tbody.appendChild(row(c)));
            $('selftest-table').hidden = false;
            $('selftest-summary').textContent = d.ok
                ? T('selftest.ok', { count: (d.checks || []).length, ms: d.duration_ms })
                : T('selftest.failed', { failed: (d.failed || []).length, count: (d.checks || []).length, ms: d.duration_ms });
            $('selftest-note').textContent = d.note || '';
            log(d.ok ? 'alles ok' : 'Funde: ' + (d.failed || []).join(', '));
        } catch (e) {
            $('selftest-summary').textContent = T('selftest.fail', { error: e.message });
            log('fehlgeschlagen:', e.message);
        } finally {
            btn.disabled = false;
        }
    }

    function init() {
        if (!$('selftest-run')) return;     // section not on this page
        $('selftest-run').addEventListener('click', run);
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
