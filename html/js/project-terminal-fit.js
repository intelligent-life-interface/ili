// project-terminal-fit.js — Teil von project.js (aufgeteilt 2026-07-24, Kanban arch_6cb5b87e65).
// Zwei self-contained IIFEs: OSC-52-Copy-Overlay + Mobile-Viewport-Fit
// Klassik-Script, gemeinsamer globaler Scope mit den uebrigen project-*.js — Ladereihenfolge in project.html beachten.
(function () {
  'use strict';
  const PTLOG = (...a) => console.log('[PT-Kbd]', ...a);
  const KEYMAP = {
    'Escape': { keyCode:27, code:'Escape' }, 'Tab': { keyCode:9, code:'Tab' },
    'Enter': { keyCode:13, code:'Enter' }, 'Backspace': { keyCode:8, code:'Backspace' },
    'ArrowLeft': { keyCode:37, code:'ArrowLeft' }, 'ArrowUp': { keyCode:38, code:'ArrowUp' },
    'ArrowDown': { keyCode:40, code:'ArrowDown' }, 'ArrowRight': { keyCode:39, code:'ArrowRight' },
    'Home': { keyCode:36, code:'Home' }, 'End': { keyCode:35, code:'End' },
    'PageUp': { keyCode:33, code:'PageUp' }, 'PageDown': { keyCode:34, code:'PageDown' },
  };
  const stick = { ctrl:false, alt:false };
  let shiftOn = false;

  function ptTextarea() {
    const f = document.getElementById('proj-terminal');
    if (!f) return null;
    let doc;
    try { doc = f.contentDocument || f.contentWindow.document; }
    catch (e) { PTLOG('iframe-Doc blockiert:', e.message); return null; }
    if (!doc) return null;
    const ta = doc.querySelector('textarea.xterm-helper-textarea')
            || doc.querySelector('.xterm-helper-textarea') || doc.querySelector('textarea');
    if (!ta) { PTLOG('xterm-Textarea nicht gefunden'); return null; }
    if (!ta.dataset.hardened) {
      ta.setAttribute('autocorrect', 'off'); ta.setAttribute('autocapitalize', 'none');
      ta.setAttribute('autocomplete', 'off'); ta.setAttribute('spellcheck', 'false');
      // Touch: native iOS-Tastatur am Terminal unterdrücken — getippt wird über die
      // Eingabe-Zeile (#pt-input). Die native Tastatur brächte hier ohnehin nichts
      // (Events erreichen das xterm nicht) und würde nur stören.
      if (('ontouchstart' in window) || matchMedia('(pointer: coarse)').matches) ta.setAttribute('inputmode', 'none');
      ta.dataset.hardened = '1';
    }
    return ta;
  }

  // Terminal-Objekt (ttyd exponiert window.term, same-origin).
  function ptTerm() {
    const f = document.getElementById('proj-terminal');
    try { return (f && f.contentWindow && f.contentWindow.term) || null; } catch (e) { return null; }
  }
  // Rohdaten an die PTY senden — der EINZIGE zuverlässige Weg. Synthetische
  // KeyboardEvents erreichen dieses xterm/ttyd NICHT (verifiziert 2026-07-18);
  // triggerDataEvent(data,true) = als hätte der Nutzer getippt → ttyd-WebSocket
  // → tmux/Shell.
  function ptSendData(data) {
    // Tote Verbindung? window.term existiert dann noch und triggerDataEvent "klappt"
    // still in den toten Socket — darum vorher Watchdog-Zustand prüfen, Feedback
    // zeigen und den Reconnect sofort anstossen.
    const f = document.getElementById('proj-terminal');
    const wd = window.TermWatchdog;
    if (wd && f) {
      const s = wd.state(f);
      if (s === 'closed' || s === 'reconnecting') {
        PTLOG('Tastendruck verworfen — Verbindung tot (' + s + ')');
        ptFlashNoConn(); wd.kick(); return false;
      }
    }
    const t = ptTerm();
    if (!t) { PTLOG('Terminal noch nicht bereit (kein window.term)'); ptFlashNoConn(); return false; }
    try { t._core.coreService.triggerDataEvent(data, true); return true; }
    catch (e) { PTLOG('triggerDataEvent fehlgeschlagen:', e); return false; }
  }

  // Öffentlich fürs Login-Panel (html/claude-login-panel.html): derselbe verifizierte
  // Daten-Kanal wie die Eingabe-Zeile — kein zweiter, ungetesteter Weg (z.B. term.paste)
  // für denselben Zweck.
  window.PTTerm = { send: ptSendData, term: ptTerm };

  // Kurzer Hinweis-Banner: Tastendruck ging ins Leere, Verbindung wird wiederhergestellt.
  let ptNoConnT;
  function ptFlashNoConn() {
    let el = document.getElementById('pt-noconn');
    if (!el) {
      el = document.createElement('div');
      el.id = 'pt-noconn';
      el.textContent = '⚠️ Keine Terminal-Verbindung — stelle wieder her…';
      el.style.cssText = 'position:fixed;top:8px;left:50%;transform:translateX(-50%);' +
        'background:#b91c1c;color:#fff;padding:6px 14px;border-radius:8px;font:600 13px sans-serif;' +
        'z-index:9999;transition:opacity .3s;pointer-events:none;';
      document.body.appendChild(el);
    }
    el.style.opacity = '1';
    clearTimeout(ptNoConnT);
    ptNoConnT = setTimeout(() => { el.style.opacity = '0'; }, 1800);
  }
  // Tasten-Spezifikation {key?,ch?,ctrl?,alt?} → Byte-Sequenz fürs Terminal.
  function ptKeyToBytes(spec) {
    const ctrl = !!spec.ctrl || stick.ctrl, alt = !!spec.alt || stick.alt;
    const wrapAlt = s => alt ? '\x1b' + s : s;
    if (spec.ch != null) {
      const c = spec.ch;
      if (ctrl && c.length === 1) {
        const cc = c.toUpperCase().charCodeAt(0);
        if (cc >= 64 && cc <= 95) return wrapAlt(String.fromCharCode(cc & 0x1f));
      }
      return wrapAlt(c);
    }
    const t = ptTerm();
    const appCK = !!(t && t.modes && t.modes.applicationCursorKeys);
    const NAMED = {
      Enter: '\r', Tab: '\t', ShiftTab: '\x1b[Z', Escape: '\x1b', Backspace: '\x7f',
      ArrowUp: appCK ? '\x1bOA' : '\x1b[A', ArrowDown: appCK ? '\x1bOB' : '\x1b[B',
      ArrowRight: appCK ? '\x1bOC' : '\x1b[C', ArrowLeft: appCK ? '\x1bOD' : '\x1b[D',
      Home: '\x1b[H', End: '\x1b[F', PageUp: '\x1b[5~', PageDown: '\x1b[6~',
    };
    if (NAMED[spec.key] != null) {
      // Modifier-aware (2026-07-19): benannte Tasten (Tab/Enter/Pfeile…) ignorierten
      // bisher stick.ctrl/stick.alt → Ctrl+Tab & Co. waren am Touch nicht möglich.
      // Ohne aktiven Modifier bleibt die unveränderte Sequenz (kein Verhaltenswechsel).
      // ShiftTab hat sein eigenes Byte (\x1b[Z) und bleibt davon unberührt.
      if ((!ctrl && !alt) || spec.key === 'ShiftTab') return NAMED[spec.key];
      const mod = 1 + (alt ? 2 : 0) + (ctrl ? 4 : 0);   // xterm-Modifier-Code (Shift=1,Alt=2,Ctrl=4)
      const CSI_LETTER = { ArrowUp:'A', ArrowDown:'B', ArrowRight:'C', ArrowLeft:'D', Home:'H', End:'F' };
      if (CSI_LETTER[spec.key]) return '\x1b[1;' + mod + CSI_LETTER[spec.key];   // \x1b[1;5A = Ctrl+↑
      if (spec.key === 'PageUp')   return '\x1b[5;' + mod + '~';
      if (spec.key === 'PageDown') return '\x1b[6;' + mod + '~';
      const CSIU = { Tab:9, Enter:13, Escape:27, Backspace:127 };                 // CSI-u (fixterms): \x1b[9;5u = Ctrl+Tab
      if (CSIU[spec.key] != null) return '\x1b[' + CSIU[spec.key] + ';' + mod + 'u';
      return NAMED[spec.key];
    }
    const k = spec.key;
    if (k && k.length === 1) {
      if (ctrl) { const cc = k.toUpperCase().charCodeAt(0); if (cc >= 64 && cc <= 95) return wrapAlt(String.fromCharCode(cc & 0x1f)); }
      return wrapAlt(k);
    }
    return '';
  }
  function ptPress(spec) {
    const bytes = ptKeyToBytes(spec);
    if (bytes === '') { PTLOG('keine Bytes für', spec); ptClearSticky(); return; }
    if (ptSendData(bytes)) PTLOG('gesendet:', JSON.stringify(bytes));
    ptClearSticky();
  }
  function ptClearSticky() {
    if (!stick.ctrl && !stick.alt) return;
    stick.ctrl = false; stick.alt = false;
    document.querySelectorAll('#pt-keys .mod.on').forEach(b => b.classList.remove('on'));
  }
  function ptToggleMod(which, btn) { stick[which] = !stick[which]; btn.classList.toggle('on', stick[which]); }

  // ── Farbmodus ── global für onclick ──
  // Schaltet die SECHS eingebauten Farbmodi von Claude Code durch (dark, light,
  // *-daltonized, *-ansi) und schreibt den gewählten per POST /api/claude-theme in
  // ~/.claude/settings.json. Claude liest das Theme beim START — die Umstellung gilt
  // also ab der nächsten Session, laufende behalten ihre Farben (so abgesprochen
  // 07.08.2026; Alternative wäre ein Session-Neustart und damit Kontextverlust).
  // Zusätzlich wird das iframe hell/dunkel gefiltert, damit das Fenster sofort zum
  // gewählten Modus passt — das ist reine Darstellung, kein Reconnect.
  let PT_THEMES = [
    { key: 'dark',             icon: '🌙', label: 'Dunkel' },
    { key: 'light',            icon: '☀️', label: 'Hell' },
    { key: 'dark-daltonized',  icon: '🌘', label: 'Dunkel, farbfehlsichtigkeits-freundlich' },
    { key: 'light-daltonized', icon: '🌗', label: 'Hell, farbfehlsichtigkeits-freundlich' },
    { key: 'dark-ansi',        icon: '🖤', label: 'Dunkel, nur ANSI-Farben' },
    { key: 'light-ansi',       icon: '🤍', label: 'Hell, nur ANSI-Farben' }
  ];
  let PT_THEME_CUR = null;

  function ptThemeMeta(key) { return PT_THEMES.find(t => t.key === key) || PT_THEMES[0]; }

  /** Knopf beschriften + iframe-Filter passend zu hell/dunkel setzen. */
  function ptApplyTheme(key, note) {
    const meta = ptThemeMeta(key);
    PT_THEME_CUR = meta.key;
    const frame = document.getElementById('proj-terminal');
    const btn = document.getElementById('term-theme-btn');
    if (frame) {
      frame.classList.toggle('pt-light', meta.key.startsWith('light'));
      frame.classList.remove('pt-contrast');   // alter 3er-Zyklus, gibt es nicht mehr
    }
    if (btn) {
      btn.textContent = meta.icon;
      btn.title = 'Farbmodus: ' + meta.label + (note ? ' — ' + note : '')
                + '\nTippen für den nächsten von ' + PT_THEMES.length
                + '. Gilt ab der nächsten Claude-Session.';
    }
    PTLOG('Farbmodus:', meta.key);
  }

  window.ptCycleTheme = async function () {
    const idx = PT_THEMES.findIndex(t => t.key === PT_THEME_CUR);
    const next = PT_THEMES[(idx + 1) % PT_THEMES.length];
    ptApplyTheme(next.key, 'wird gespeichert …');        // sofort sichtbar
    try {
      const r = await fetch('/api/claude-theme', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ theme: next.key })
      });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const d = await r.json();
      PTLOG('Farbmodus gespeichert:', d.theme, d.written);
      ptApplyTheme(next.key, 'gespeichert');
    } catch (e) {
      console.error('[pt] Farbmodus konnte nicht gespeichert werden:', e);
      ptApplyTheme(PT_THEME_CUR, 'NICHT gespeichert: ' + e.message);
    }
  };

  // Startzustand aus dem Backend holen (nicht localStorage — die Wahrheit steht in
  // settings.json und kann auch ausserhalb des Dashboards geändert worden sein).
  (function () {
    fetch('/api/claude-theme', { cache: 'no-store' })
      .then(r => r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status)))
      .then(d => {
        if (Array.isArray(d.themes) && d.themes.length) PT_THEMES = d.themes;
        ptApplyTheme(d.theme || 'dark');
      })
      .catch(e => { console.warn('[pt] Farbmodus nicht ladbar, nehme Dunkel:', e); ptApplyTheme('dark'); });
  })();

  // ── Touch-Modus (tmux-Maus dieser Session) ── global für onclick ──
  // Prefix (Ctrl-b = \x02) + Kommandotaste über den Daten-Kanal an tmux.
  function ptSendTmuxKey(ch) { ptSendData('\x02'); setTimeout(() => ptSendData(ch), 40); }
  window.ptToggleTouch = function () {
    const key = 'pt-term-touch-' + (typeof BOARD_ID !== 'undefined' ? BOARD_ID : '_');
    let on = false; try { on = localStorage.getItem(key) === '1'; } catch (e) {}
    ptSendTmuxKey('T');
    on = !on;
    try { localStorage.setItem(key, on ? '1' : '0'); } catch (e) {}
    const btn = document.getElementById('term-touch-btn');
    if (btn) btn.classList.toggle('on', on);   // Zustand nur noch via .on-Klasse (blau), Label bleibt 📱
    PTLOG('Touch-Modus =', on ? 'an (tmux-Maus aus)' : 'aus (tmux-Maus an)');
  };

  // ── Bildschirm-Tastatur (volle QWERTZ) ── global für onclick ──
  window.ptToggleKbd = function () {
    const kbd = document.getElementById('pt-kbd'), keys = document.getElementById('pt-keys');
    const btn = document.getElementById('term-kbd-btn');
    const show = !kbd.classList.contains('show');
    kbd.classList.toggle('show', show);
    keys.classList.toggle('show', show);        // Sonderleiste zusammen mit QWERTZ
    if (btn) btn.classList.toggle('on', show);
    try { localStorage.setItem('pt-term-kbd', show ? '1' : '0'); } catch (e) {}
    PTLOG('Bildschirm-Tastatur:', show ? 'an' : 'aus');
    if (typeof _nudgeTerminalResize === 'function') _nudgeTerminalResize();
    if (typeof adjustBoardHeight === 'function') adjustBoardHeight();
    if (show) setTimeout(() => { const ta = ptTextarea(); if (ta) ta.focus(); }, 50);
  };

  function ptApplyShift() {
    document.querySelectorAll('#pt-kbd .ltr').forEach(b => {
      const base = b.dataset.ch.toLowerCase(); b.textContent = shiftOn ? base.toUpperCase() : base;
    });
    document.getElementById('pt-shiftbtn').classList.toggle('on', shiftOn);
  }
  function ptApplyMore(open) {
    document.getElementById('pt-keys').classList.toggle('collapsed', !open);
    document.getElementById('pt-morebtn').innerHTML = open ? '&#9650;' : '&#9776;';
  }

  function ptInitKeyboard() {
    const keys = document.getElementById('pt-keys'), kbd = document.getElementById('pt-kbd');
    if (!keys || !kbd || keys.dataset.wired) return;
    keys.dataset.wired = '1';

    // Sonder-Tastenleiste
    keys.addEventListener('pointerdown', e => {
      const b = e.target.closest('button'); if (!b) return;
      e.preventDefault();
      if (b.id === 'pt-morebtn') {
        const open = keys.classList.contains('collapsed');
        try { localStorage.setItem('pt-term-more', open ? '1' : '0'); } catch (err) {}
        ptApplyMore(open); return;
      }
      if (b.dataset.mod) { ptToggleMod(b.dataset.mod, b); return; }
      ptPress({ key:b.dataset.key, ch:b.dataset.ch, ctrl:b.dataset.ctrl === '1', alt:b.dataset.alt === '1' });
    });

    // Volle QWERTZ
    document.getElementById('pt-shiftbtn').addEventListener('pointerdown', e => { e.preventDefault(); shiftOn = !shiftOn; ptApplyShift(); });
    document.getElementById('pt-symbtn').addEventListener('pointerdown', e => {
      e.preventDefault();
      const sym = !document.querySelector('#pt-kbd .lay-sym').classList.contains('show');
      document.querySelector('#pt-kbd .lay-sym').classList.toggle('show', sym);
      document.querySelector('#pt-kbd .lay-abc').classList.toggle('show', !sym);
      e.target.textContent = sym ? 'abc' : '#+='; e.target.classList.toggle('on', sym);
    });
    kbd.addEventListener('pointerdown', e => {
      const b = e.target.closest('button'); if (!b) return;
      if (b.id === 'pt-shiftbtn' || b.id === 'pt-symbtn') return;
      e.preventDefault();
      if (b.dataset.key) { ptPress({ key:b.dataset.key }); return; }
      let ch = b.dataset.ch; if (ch == null) return;
      if (b.classList.contains('ltr') && shiftOn) ch = ch.toUpperCase();
      ptPress({ ch });
      if (b.classList.contains('ltr') && shiftOn) { shiftOn = false; ptApplyShift(); }
    });

    // ── Eingabe-Zeile: native iPhone-Tastatur → Text bei Enter/„Senden" ins Terminal ──
    const inp = document.getElementById('pt-input');
    const sendInput = () => {
      if (!inp) return;
      let v = inp.value;
      const cr = document.getElementById('pt-input-cr');
      if (cr && cr.checked) v += '\r';
      if (v && ptSendData(v)) PTLOG('Eingabe gesendet:', JSON.stringify(v));
      inp.value = '';
      inp.focus();   // Tastatur offen halten für die nächste Zeile
    };
    if (inp) inp.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); sendInput(); } });
    const sendBtn = document.getElementById('pt-input-send');
    if (sendBtn) sendBtn.addEventListener('click', e => { e.preventDefault(); sendInput(); });

    // ── Modell-Dropdown: "/model <name>" in die LAUFENDE Terminal-Session senden ──
    // Nutzt denselben Daten-Kanal wie die Eingabe-Zeile (ptSendData → triggerDataEvent).
    // Nur wirksam, wenn claude im Vordergrund läuft; sonst landet es als Shell-Eingabe.
    const ptModelSel = document.getElementById('pt-model-select');
    if (ptModelSel) ptModelSel.addEventListener('change', () => {
      const m = ptModelSel.value;
      ptModelSel.selectedIndex = 0;                 // Dropdown zurück aufs Label
      if (!m) return;
      if (ptSendData('/model ' + m + '\r')) PTLOG('Modellwechsel gesendet:', m);
    });

    // Auf Touch-Geräten Eingabe-Zeile + Sonderleiste standardmässig zeigen; Desktop: aus.
    const isTouch = ('ontouchstart' in window) || matchMedia('(pointer: coarse)').matches;
    let moreOpen = false, kbdOpen = false;
    try { moreOpen = localStorage.getItem('pt-term-more') === '1'; kbdOpen = localStorage.getItem('pt-term-kbd') === '1'; } catch (e) {}
    ptApplyMore(moreOpen);
    if (isTouch) { const il = document.getElementById('pt-inputline'); if (il) il.classList.add('show'); }
    if (isTouch || kbdOpen) keys.classList.add('show');
    if (kbdOpen) { kbd.classList.add('show'); const kb = document.getElementById('term-kbd-btn'); if (kb) kb.classList.add('on'); }
    // Touch-Knopf-Optik aus gemerktem Zustand
    try {
      const on = localStorage.getItem('pt-term-touch-' + (typeof BOARD_ID !== 'undefined' ? BOARD_ID : '_')) === '1';
      const tb = document.getElementById('term-touch-btn');
      if (on && tb) { tb.classList.add('on'); tb.textContent = '📱 Touch AN'; }
    } catch (e) {}
    PTLOG('Tastatur verdrahtet (Touch-Gerät:', isTouch, ')');
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ptInitKeyboard);
  else ptInitKeyboard();
})();

// ══════════════════════════════════════════════════════════════
// PROJEKT-TERMINAL — iPhone-Tastatur-Fit (visualViewport, 2026-07-18)
// Kommt die NATIVE iOS-Tastatur hoch, schrumpft nur window.visualViewport
// (nicht innerHeight/100vh) → das Terminal-Panel verschwände hinter der
// Tastatur. Wir pinnen .chat-panel dann exakt auf den sichtbaren Ausschnitt
// (top=offsetTop, height=vv.height) → Terminal + Eingabezeile bleiben sichtbar
// ("Bild wird nach oben geschoben"). Analog zu m/ (fitViewport). Zusätzlich:
// ist die EIGENE ⌨-Tastatur offen, unterdrücken wir die native (inputmode=none),
// damit nicht beide gleichzeitig erscheinen.
// ══════════════════════════════════════════════════════════════
(function () {
  'use strict';
  const VVLOG = (...a) => console.log('[PT-VV]', ...a);

  function ptTermTa() {
    const f = document.getElementById('proj-terminal');
    if (!f) return null;
    try { const d = f.contentDocument || f.contentWindow.document;
          return d && (d.querySelector('.xterm-helper-textarea') || d.querySelector('textarea')); }
    catch (e) { return null; }
  }
  function ptNudgeFrame() {
    const f = document.getElementById('proj-terminal');
    try { f && f.contentWindow.dispatchEvent(new Event('resize')); } catch (e) {}
  }

  // Nur wenn: kleiner Screen + Terminal-Tab aktiv + nicht Vollbild/maximiert.
  function ptMobileTermActive() {
    if (!window.matchMedia('(max-width: 768px)').matches) return false;
    const p = document.querySelector('.chat-panel');
    return !!p && !p.classList.contains('tab-hidden')
              && !p.classList.contains('terminal-maximized')
              && !document.fullscreenElement;
  }
  function ptClearPin(p) {
    if (!p || !p.style.position) return;
    p.style.position = ''; p.style.left = ''; p.style.right = '';
    p.style.top = ''; p.style.height = ''; p.style.zIndex = '';
    ptNudgeFrame();
  }
  function ptFitViewport() {
    const p = document.querySelector('.chat-panel');
    const vv = window.visualViewport;
    if (!p || !vv || !ptMobileTermActive()) { ptClearPin(p); return; }
    // Tastatur belegt spürbar Platz? (Schwelle 120px gegen Adressleisten-Jitter)
    const kbdUp = (window.innerHeight - vv.height) > 120;
    if (!kbdUp) { ptClearPin(p); return; }
    p.style.position = 'fixed';
    p.style.left = '0'; p.style.right = '0';
    p.style.top = Math.round(vv.offsetTop) + 'px';
    p.style.height = Math.round(vv.height) + 'px';
    p.style.zIndex = '40';
    ptNudgeFrame();
    VVLOG('Tastatur oben → Panel gepinnt: top=' + Math.round(vv.offsetTop) + ' h=' + Math.round(vv.height));
  }

  // Native iOS-Tastatur unterdrücken, solange die eigene QWERTZ (#pt-kbd) offen ist.
  function ptSyncNativeKbd() {
    const ta = ptTermTa();
    if (!ta) return;
    // Touch: native Tastatur am Terminal IMMER unterdrücken (getippt wird über
    // die Eingabe-Zeile). Desktop: nichts unterdrücken.
    const touch = ('ontouchstart' in window) || window.matchMedia('(pointer: coarse)').matches;
    if (touch) ta.setAttribute('inputmode', 'none');
    else ta.removeAttribute('inputmode');
  }

  // ptToggleKbd erweitern (native Tastatur mit-synchronisieren).
  const _origToggleKbd = window.ptToggleKbd;
  if (typeof _origToggleKbd === 'function') {
    window.ptToggleKbd = function () { _origToggleKbd.apply(this, arguments); setTimeout(ptSyncNativeKbd, 30); };
  }
  // switchTab erweitern (beim Wechsel auf/aus Terminal-Tab neu einpassen).
  const _origSwitchTab = window.switchTab;
  if (typeof _origSwitchTab === 'function') {
    window.switchTab = function () { _origSwitchTab.apply(this, arguments); setTimeout(ptFitViewport, 60); };
  }

  if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', ptFitViewport);
    window.visualViewport.addEventListener('scroll', ptFitViewport);
    VVLOG('visualViewport-Handler aktiv');
  }
  // Beim Fokus ins Terminal (native Tastatur kommt evtl. verzögert) nachfassen.
  document.addEventListener('focusin', e => {
    if (e.target && (e.target.id === 'proj-terminal' || e.target.id === 'pt-input')) setTimeout(ptFitViewport, 250);
  });
})();
