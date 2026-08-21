// ---------------------------------------------------------------------------
// Terminal-Watchdog — Auto-Reconnect für ttyd-iframes (2026-07-18)
//
// Problem: ttyd 1.7.4 hat zwar Client-Reconnect, aber die Kette stirbt endgültig,
// wenn (a) der WS mit Close-Code 1000 zugeht oder (b) beim Reconnect der
// Token-Fetch fehlschlägt (typisch: Gerät wacht auf, Netz steht noch nicht).
// Dann bleibt für immer "Connection Closed" / "Reconnecting..." stehen und man
// musste die Seite von Hand neu laden.
//
// Lösung: Der Watchdog beobachtet die same-origin iframes, erkennt das
// festgefahrene ttyd-Overlay und lädt NUR das betroffene iframe neu — tmux
// reattacht die Session nahtlos (kein Verlust).
//
// EINE Pflege-Datei für alle Flächen (wie terminal-shortcuts.js):
//   - caddy terminals.html  (cross-origin <script>, T1–4)
//   - dashboard project.js  (#proj-terminal)
//   - dashboard m/m.js      (#m-term)
// Nutzung: window.TermWatchdog.watch(iframeEl, "label")
// Kein Restart nötig (html-Mount live), nur Browser-Hardreload.
// ---------------------------------------------------------------------------
"use strict";
window.TermWatchdog = (function () {
  const LOG = (...a) => console.log("[term-watchdog]", ...a);

  const CHECK_EVERY_MS   = 3000;   // Poll-Takt (nur bei sichtbarem Tab)
  const STUCK_GRACE_MS   = 12000;  // so lange darf ttyd selbst "Reconnecting..." zeigen
  const RELOAD_COOLDOWN  = 10000;  // max. 1 Reload pro iframe in diesem Fenster
  const NOTERM_GRACE_MS  = 30000;  // Fehlerseite/502 statt Terminal: so lange warten, dann neu versuchen

  // iframeEl -> { label, stuckSince, lastReload }
  const frames = new Map();

  // Zustand eines iframes anhand des ttyd-Overlays bestimmen.
  // Das ttyd-OverlayAddon hängt einen klassenlosen <div> in .xterm; persistente
  // Overlays ("Connection Closed", "Reconnecting...") bleiben mit opacity 0.75
  // stehen, getimte (Resize "80x24", "Reconnected") verschwinden wieder.
  function frameState(el) {
    let doc;
    try { doc = el.contentWindow && el.contentWindow.document; }
    catch (e) { return "blocked"; }              // cross-origin/Fehlerseite
    if (!doc || !doc.body) return "blank";
    const xterm = doc.querySelector(".xterm");
    if (!xterm) return "noterm";                 // about:blank / noch am Laden
    for (const div of xterm.querySelectorAll(":scope > div:not([class])")) {
      if (div.style.opacity === "0") continue;
      const txt = (div.textContent || "").trim();
      if (txt === "Connection Closed") return "closed";
      if (txt === "Reconnecting...")   return "reconnecting";
    }
    return "ok";
  }

  function maybeReload(el, st, why) {
    const now = Date.now();
    if (navigator.onLine === false) { LOG(st.label + ": offline — warte mit Reload"); return; }
    if (now - st.lastReload < RELOAD_COOLDOWN) return;
    st.lastReload = now;
    st.stuckSince = 0;
    LOG(st.label + ": Verbindung tot (" + why + ") — lade iframe neu");
    try { el.contentWindow.location.reload(); }
    catch (e) { LOG(st.label + ": reload() blockiert (" + e.message + ") — setze src neu"); el.src = el.src; }
  }

  function checkAll(trigger) {
    if (document.hidden) return;                 // im Hintergrund nichts tun
    frames.forEach((st, el) => {
      if (!el.isConnected) { frames.delete(el); return; }
      const s = frameState(el);
      if (s === "closed") {
        maybeReload(el, st, "Connection Closed, Trigger: " + trigger);
      } else if (s === "reconnecting") {
        if (!st.stuckSince) { st.stuckSince = Date.now(); LOG(st.label + ": ttyd versucht Reconnect — beobachte"); }
        else if (Date.now() - st.stuckSince > STUCK_GRACE_MS) {
          maybeReload(el, st, "Reconnecting haengt >" + (STUCK_GRACE_MS / 1000) + "s");
        }
      } else if ((s === "noterm" || s === "blocked") && el.src && el.src !== "about:blank") {
        // Fehlerseite/502 statt Terminal (z.B. Reload während Dienst kurz weg war):
        // nach längerer Schonfrist erneut versuchen, bis das Terminal wieder da ist.
        if (!st.stuckSince) st.stuckSince = Date.now();
        else if (Date.now() - st.stuckSince > NOTERM_GRACE_MS) {
          maybeReload(el, st, "kein Terminal geladen (" + s + ") >" + (NOTERM_GRACE_MS / 1000) + "s");
        }
      } else {
        if (st.stuckSince) LOG(st.label + ": wieder verbunden");
        st.stuckSince = 0;
      }
    });
  }

  // Poll + gezielte Checks bei den typischen "Gerät ist zurück"-Momenten.
  setInterval(() => checkAll("interval"), CHECK_EVERY_MS);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) setTimeout(() => checkAll("visible"), 800);
  });
  window.addEventListener("online", () => setTimeout(() => checkAll("online"), 800));
  window.addEventListener("focus",  () => setTimeout(() => checkAll("focus"), 800));

  return {
    watch(el, label) {
      if (!el) { LOG("watch(): iframe fehlt (" + label + ")"); return; }
      if (frames.has(el)) return;
      frames.set(el, { label: label || el.id || "iframe", stuckSince: 0, lastReload: 0 });
      LOG("beobachte", label || el.id);
    },
    // Zustand eines iframes für Aufrufer (Tastatur prüft vor dem Senden, ob die
    // Verbindung tot ist — triggerDataEvent "klappt" sonst still in einen toten Socket).
    state: frameState,
    // Sofort-Check anstossen (z.B. beim Tippen auf toter Verbindung), statt auf
    // den nächsten Poll-Takt zu warten.
    kick() { checkAll("kick"); },
  };
})();
