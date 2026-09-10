/**
 * bug-report-button.js — "report a bug" button, visible on every page.
 *
 * Uses the deep-link path (GET /api/github/deeplink), which needs NO GitHub
 * login: the backend builds a pre-filled issue URL and the browser opens it in
 * a new tab. The user then decides whether to submit — nothing is sent behind
 * their back.
 *
 * Deliberately independent of the device-flow login in github-report.js: that
 * one needs the GitHub App to exist (ILI_GITHUB_APP_CLIENT_ID), this one works
 * in every installation from day one.
 */
(function () {
    'use strict';

    var TAG = '[bug-report-button]';
    var log = function () {
        try { console.debug.apply(console, [TAG].concat([].slice.call(arguments))); } catch (e) {}
    };

    /** Translate via the shared i18n helper, with a German fallback. */
    function t(key, fallback) {
        try {
            if (typeof window.t === 'function') return window.t(key, fallback);
        } catch (e) {}
        return fallback;
    }

    var CSS = [
        '#ili-bug-btn{position:fixed;right:1.25rem;bottom:1.25rem;z-index:900;',
        '  display:flex;align-items:center;gap:.4rem;padding:.55rem .85rem;',
        '  border:none;border-radius:2rem;cursor:pointer;font:inherit;font-size:.85rem;',
        '  background:#2b4c7e;color:#fff;box-shadow:0 2px 10px rgba(0,0,0,.25);',
        '  opacity:.75;transition:opacity .15s,transform .15s}',
        '#ili-bug-btn:hover{opacity:1;transform:translateY(-1px)}',
        '#ili-bug-btn[disabled]{cursor:progress;opacity:.5}',
        '@media(max-width:640px){#ili-bug-btn span.ili-bug-label{display:none}}'
    ].join('');

    /**
     * Collect a bit of context for the issue body. Only technical facts about
     * the page itself — the backend sanitizer strips the rest before it ever
     * reaches GitHub.
     */
    function context() {
        var lines = [
            'Seite: ' + location.pathname + (location.search || ''),
            'Browser: ' + navigator.userAgent
        ];
        try {
            var v = document.getElementById('footer-version');
            if (v && v.textContent) lines.push('Version: ' + v.textContent.trim());
        } catch (e) {}
        return lines.join('\n');
    }

    function openIssue(btn) {
        btn.disabled = true;
        var title = t('bug.prefillTitle', 'Fehler in ili: ');
        var body = t('bug.prefillBody', 'Was ist passiert?\n\n\nWas hättest du erwartet?\n\n\n---\n')
            + context();

        var url = '/api/github/deeplink?title=' + encodeURIComponent(title)
                + '&body=' + encodeURIComponent(body);

        fetch(url)
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (d && d.url) {
                    log('deeplink erhalten, öffne neuen Tab');
                    window.open(d.url, '_blank', 'noopener');
                } else {
                    log('kein deeplink in der Antwort', d);
                    alert(t('bug.failed', 'Der Melde-Link konnte nicht erzeugt werden.'));
                }
            })
            .catch(function (e) {
                log('deeplink fehlgeschlagen:', e && e.message);
                alert(t('bug.failed', 'Der Melde-Link konnte nicht erzeugt werden.'));
            })
            .then(function () { btn.disabled = false; });
    }

    function init() {
        if (document.getElementById('ili-bug-btn')) return;

        var style = document.createElement('style');
        style.textContent = CSS;
        document.head.appendChild(style);

        var btn = document.createElement('button');
        btn.id = 'ili-bug-btn';
        btn.type = 'button';
        btn.title = t('bug.title', 'Einen Fehler melden (öffnet GitHub in einem neuen Tab)');
        btn.innerHTML = '🐛<span class="ili-bug-label">'
            + t('bug.button', 'Fehler melden') + '</span>';
        btn.addEventListener('click', function () { openIssue(btn); });
        document.body.appendChild(btn);
        log('Knopf eingehängt');
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
