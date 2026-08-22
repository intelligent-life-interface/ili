// project-claude-login.js — Claude-Anmeldungs-Helfer für Projekt-Terminal
//
// Funktionalität:
// 1. Prüft (a) ob das Terminal-Profil überhaupt läuft, (b) ob Claude angemeldet ist
// 2. Zeigt ein Login-Panel an, wenn das Terminal läuft, Claude aber nicht angemeldet ist
//
// Geladen in project.html nach dem Terminal-Modul (project-terminal-fit.js, das
// window.PTTerm für den Daten-Kanal ins Terminal exportiert).

(function() {
  'use strict';

  const CLAUDE_LOGIN_CHECK_INTERVAL = 5000; // 5 Sekunden zwischen Checks

  let checkInterval = null;
  let lastCheckTime = 0;
  let isCheckingNow = false;
  let boardId = '';
  let terminalEnabled = null; // null = noch nicht geprüft

  // Public API
  window.ClaudeLoginHelper = {
    init: initClaudeLoginHelper,
    setBoardId: setBoardId,
    checkLogin: checkClaudeLogin,
    stop: stopChecking,
    showLoginPanel: () => window.ClaudeLoginPanel?.show?.(),
    hideLoginPanel: () => window.ClaudeLoginPanel?.hide?.()
  };

  function setBoardId(id) {
    boardId = (id || '').trim();
    console.log('[ClaudeLoginHelper] Board-ID gesetzt:', boardId);
  }

  async function initClaudeLoginHelper() {
    console.log('[ClaudeLoginHelper] Initialisierung…');

    await checkClaudeLogin();

    // Wiederholte Checks (z.B. nach Terminal-Neustart oder erfolgtem Login)
    checkInterval = setInterval(() => {
      checkClaudeLogin().catch(e => console.error('[ClaudeLoginHelper] Check-Fehler:', e));
    }, CLAUDE_LOGIN_CHECK_INTERVAL);

    console.log('[ClaudeLoginHelper] Aktiviert. Checks alle', CLAUDE_LOGIN_CHECK_INTERVAL / 1000, 'Sek.');
  }

  // /projterm/state existiert unabhängig vom Terminal-Profil (der stub-503 hat KEINEN
  // Body, ein laufendes Terminal antwortet 200 mit {"generated": bool}). Ohne dieses
  // Gate würde das Panel „tote Knöpfe" für ein Terminal zeigen, das es gar nicht gibt.
  async function isTerminalEnabled() {
    if (terminalEnabled !== null) return terminalEnabled;
    try {
      const r = await fetch('/projterm/state', { cache: 'no-store' });
      terminalEnabled = r.ok;
    } catch (e) {
      terminalEnabled = false;
    }
    console.log('[ClaudeLoginHelper] Terminal-Profil aktiv:', terminalEnabled);
    return terminalEnabled;
  }

  async function checkClaudeLogin() {
    const now = Date.now();
    if (isCheckingNow || (now - lastCheckTime < 1000)) {
      return;
    }

    if (!boardId) {
      console.debug('[ClaudeLoginHelper] Keine Board-ID gesetzt, prüfe nicht');
      return;
    }

    isCheckingNow = true;
    lastCheckTime = now;

    try {
      if (!(await isTerminalEnabled())) {
        window.ClaudeLoginPanel?.hide?.();
        return;
      }

      const response = await fetch('/api/claude-status', {
        method: 'GET',
        cache: 'no-store'
      });

      if (!response.ok) {
        console.debug('[ClaudeLoginHelper] Status-Endpunkt antwortet nicht ok:', response.status);
        return;
      }

      const data = await response.json();
      const isLoggedIn = data.logged_in === true;

      console.log('[ClaudeLoginHelper] Claude-Status:', isLoggedIn ? 'angemeldet' : 'nicht angemeldet', '(' + data.source + ')');

      if (!isLoggedIn && window.ClaudeLoginPanel) {
        showLoginPrompt();
      } else if (isLoggedIn && window.ClaudeLoginPanel) {
        window.ClaudeLoginPanel.hide?.();
      }
    } catch (error) {
      console.debug('[ClaudeLoginHelper] Status-Check fehlgeschlagen:', error.message);
    } finally {
      isCheckingNow = false;
    }
  }

  function showLoginPrompt() {
    if (!window.ClaudeLoginPanel) {
      console.warn('[ClaudeLoginHelper] ClaudeLoginPanel nicht geladen');
      return;
    }
    if (window.ClaudeLoginPanel.isVisible?.()) {
      console.debug('[ClaudeLoginHelper] Login-Panel bereits sichtbar');
      return;
    }
    console.log('[ClaudeLoginHelper] Claude nicht angemeldet, zeige Login-Panel');
    window.ClaudeLoginPanel.show?.();
  }

  function stopChecking() {
    if (checkInterval) {
      clearInterval(checkInterval);
      checkInterval = null;
      console.log('[ClaudeLoginHelper] Überprüfungen gestoppt');
    }
  }

  function autoInit() {
    if (typeof window.BOARD_ID === 'string') {
      setBoardId(window.BOARD_ID);
    }
    initClaudeLoginHelper();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      setTimeout(autoInit, 500);
    });
  } else {
    setTimeout(autoInit, 500);
  }
})();
