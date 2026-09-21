// ssh-settings.js — "🔐 SSH-Zugang" section of ai-settings.html.
// Variante A (Manager decision 2026-09-20): read-only GUI with status checks and
// client-side command generation. No writable mount; public key stays in browser.
// Talks to /api/ssh/status for status checks only (port/sshd running).
//
// All visible text comes from language files (ssh.* keys) via window.t().
(function () {
    'use strict';
    const log = (...a) => console.debug('[ssh-settings]', ...a);
    const $ = (id) => document.getElementById(id);
    const T = (key, vars) => {
        let s = (typeof window.t === 'function') ? window.t(key, key) : key;
        if (vars) Object.keys(vars).forEach((k) => { s = s.split('{' + k + '}').join(vars[k] == null ? '' : String(vars[k])); });
        return s;
    };
    const say = (msg, isErr) => (typeof window.toast === 'function') ? window.toast(msg, !!isErr) : log(msg);

    // Status: state comes from the api (probe of terminal:22 in the compose network).
    // ssh_port / ssh_bind are the CONFIGURED host port/bind — the api cannot probe those.
    function renderStatus(st) {
        const dot = $('ssh-dot');
        const text = $('ssh-status-text');
        const meta = $('ssh-meta');
        const port = st.ssh_port || 2222;
        const bind = st.ssh_bind || '127.0.0.1';

        dot.className = 'docker-dot';
        let line;
        switch (st.state) {
            case 'ok':
                dot.classList.add('ok');
                line = T('ssh.status.ok', { port, bind });
                break;
            case 'sshd_down':
                dot.classList.add('fail');
                line = T('ssh.status.sshd_down');
                break;
            case 'no_terminal':
                dot.classList.add('fail');
                line = T('ssh.status.no_terminal');
                break;
            default:
                line = T('ssh.status.unknown');
        }

        text.removeAttribute('data-i18n');  // live text — don't reset to i18n fallback
        text.textContent = line;

        const bits = [T('ssh.meta.port', { port }), T('ssh.meta.bind', { bind })];
        if (st.lan_exposed) bits.push(T('ssh.meta.lan'));
        if (st.overlay_in_env === true) bits.push(T('ssh.meta.overlay_yes'));
        else if (st.overlay_in_env === false) bits.push(T('ssh.meta.overlay_no'));
        meta.textContent = bits.join(' · ');
        log('status rendered', st);
    }

    async function loadStatus() {
        try {
            const r = await fetch('/api/ssh/status');
            if (!r.ok) throw new Error('HTTP ' + r.status);
            const st = await r.json();
            renderStatus(st);
        } catch (e) {
            log('status load failed', e);
            $('ssh-status-text').removeAttribute('data-i18n');
            $('ssh-status-text').textContent = T('ssh.status.fail', { error: e.message });
            $('ssh-dot').className = 'docker-dot fail';
        }
    }

    // Client-side command generation: never sends the key to the API.
    // Returns '' when the input is not (yet) a usable public key; `quiet` suppresses
    // the error toast so live typing in the textarea does not spam.
    function generateCommand(quiet) {
        const pubkey = $('ssh-pubkey-input').value.trim();
        const fail = (key) => { if (!quiet) say(T(key), true); log('command rejected:', key); return ''; };

        if (!pubkey) return fail('ssh.error.no_key');
        if (pubkey.includes('PRIVATE KEY') || pubkey.startsWith('-----BEGIN')) return fail('ssh.error.private_key');
        if (/[\r\n]/.test(pubkey)) return fail('ssh.error.multiline');

        const keyTypes = ['ssh-rsa', 'ssh-ed25519', 'ecdsa-sha2-nistp256', 'ecdsa-sha2-nistp384', 'ecdsa-sha2-nistp521', 'sk-ssh-ed25519@openssh.com', 'sk-ecdsa-sha2-nistp256@openssh.com'];
        if (!keyTypes.some((t) => pubkey.startsWith(t + ' '))) return fail('ssh.error.invalid_format');

        // The key ends up inside single quotes on the operator's shell. A quote or a
        // control character would break out of them, so refuse instead of escaping
        // (escaping differs between sh and PowerShell).
        if (/['\u0000-\u001f\u007f]/.test(pubkey)) return fail('ssh.error.bad_chars');

        const bindArg = $('ssh-bind-select').value === 'lan' ? ' --bind lan' : '';
        return `docker run --rm -v "$PWD":/out ghcr.io/toa1984/ili ssh-setup${bindArg} '${pubkey}'`;
    }

    function updateCommand() {
        const cmd = generateCommand(true);
        const term = $('ssh-command-term');
        term.textContent = cmd || T('ssh.command.empty');
    }

    function copyCommand() {
        const cmd = generateCommand(false);
        if (!cmd) return;

        navigator.clipboard.writeText(cmd).then(() => {
            say(T('ssh.copied'));
        }).catch(e => {
            log('copy failed', e);
            say(T('ssh.copy_failed', { error: e.message }), true);
        });
    }

    // Init
    async function init() {
        loadStatus();

        // Event listeners
        const keyInput = $('ssh-pubkey-input');
        const bindSelect = $('ssh-bind-select');
        const copyBtn = $('ssh-copy-btn');
        const refreshBtn = $('ssh-btn-refresh');

        if (keyInput) keyInput.addEventListener('input', updateCommand);
        if (bindSelect) bindSelect.addEventListener('change', updateCommand);
        if (copyBtn) copyBtn.addEventListener('click', copyCommand);
        if (refreshBtn) refreshBtn.addEventListener('click', () => { loadStatus(); say(T('ssh.status.refreshed')); });

        // Initial command display (empty)
        updateCommand();

        // Refresh status every 30s
        setInterval(loadStatus, 30000);
    }

    window.addEventListener('load', init);
})();
