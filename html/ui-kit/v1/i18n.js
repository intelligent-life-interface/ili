/* ============================================================================
 * ili UI-Kit v1 — i18n helper (tool language from language files)
 * Served at: /ui-kit/v1/i18n.js
 *
 * GUI texts are not hard-wired into the HTML/JS but pulled from a language file.
 * German is the default; another language is just another dictionary file.
 *
 * Include order matters (defer runs in document order):
 *   <script src="/i18n/de.js" defer></script>      <- sets window.I18N
 *   <script src="/ui-kit/v1/i18n.js" defer></script>
 *
 * Dictionary = flat object, dotted keys:
 *   window.I18N = { "nav.fragen": "Offene Fragen", ... };
 *
 * Fail-safe by design: t() always takes a fallback and returns it when the
 * dictionary or the key is missing, so a page never depends on this file.
 * ========================================================================== */
"use strict";

window.I18n = (function () {
    var DEBUG = document.documentElement.dataset.uiDebug !== "off";
    var missing = [];   // Schluessel ohne Eintrag — am Ende EINMAL gesammelt loggen

    function dict() { return window.I18N || {}; }

    /** Text zum Schluessel; fehlt er, kommt der Fallback (nie undefined). */
    function t(key, fallback) {
        var d = dict();
        if (Object.prototype.hasOwnProperty.call(d, key)) return d[key];
        if (missing.indexOf(key) === -1) missing.push(key);
        return fallback !== undefined ? fallback : key;
    }

    /**
     * Ersetzt Texte im DOM anhand von Attributen:
     *   data-i18n="key"        -> textContent
     *   data-i18n-title="key"  -> title-Attribut
     *   data-i18n-aria="key"   -> aria-label
     * Der im HTML stehende Text ist gleichzeitig der Fallback — die Seite bleibt
     * also auch ohne Woerterbuch vollstaendig lesbar.
     */
    function apply(root) {
        var scope = root || document;
        var n = 0;
        scope.querySelectorAll("[data-i18n]").forEach(function (el) {
            el.textContent = t(el.dataset.i18n, el.textContent); n++;
        });
        scope.querySelectorAll("[data-i18n-title]").forEach(function (el) {
            el.title = t(el.dataset.i18nTitle, el.title); n++;
        });
        scope.querySelectorAll("[data-i18n-aria]").forEach(function (el) {
            el.setAttribute("aria-label", t(el.dataset.i18nAria, el.getAttribute("aria-label") || "")); n++;
        });
        if (DEBUG) console.log("[i18n] " + n + " Texte gesetzt, Woerterbuch-Eintraege: " + Object.keys(dict()).length);
        if (missing.length) console.warn("[i18n] Schluessel ohne Eintrag (Fallback benutzt):", missing.slice(0, 20));
        return n;
    }

    /** Titel der Seite aus dem Woerterbuch, falls <title data-i18n="..."> gesetzt ist. */
    function applyTitle() {
        var el = document.querySelector("title[data-i18n]");
        if (el) document.title = t(el.dataset.i18n, document.title);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () { applyTitle(); apply(); });
    } else {
        applyTitle(); apply();
    }

    return { t: t, apply: apply, dict: dict };
})();

/* Kurzform fuer den Alltag — nur setzen, wenn nichts anderes t() belegt. */
if (!window.t) window.t = window.I18n.t;
