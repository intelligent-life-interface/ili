/* ============================================================================
 * github-report.js — forward uncaught frontend errors to the GitHub feedback
 * channel, ONLY when the user opted in (user_settings.github_auto_report) and
 * is logged in (server checks both again; 401 means "not logged in").
 *
 * What is sent: error message + stack (URL query strings stripped client-side,
 * full sanitizing happens server-side in report_sanitizer.py) and the page
 * path. Never DOM contents, never board data.
 *
 * Rate limit: at most one report per minute per page, and each distinct
 * message only once per page load. Never throws — a failure here must not
 * produce a second error.
 *
 * Load with `defer` after /i18n/de.js; independent of error-buffer.js (uses
 * addEventListener instead of overriding window.onerror).
 * ========================================================================== */
"use strict";

(function () {
    var MIN_INTERVAL_MS = 60 * 1000;
    var lastSent = 0;
    var seen = {};
    var enabled = null;   // null = unknown yet
    var log = function () { try { console.debug.apply(console, ["[github-report]"].concat([].slice.call(arguments))); } catch (e) {} };

    function stripQuery(s) {
        return String(s || "").replace(/(https?:\/\/[^\s?#"']+)\?[^\s"']*/g, "$1?<query>");
    }

    function checkEnabled(cb) {
        if (enabled !== null) return cb(enabled);
        fetch("/api/user-settings").then(function (r) { return r.json(); }).then(function (s) {
            enabled = !!(s && s.github_auto_report);
            log("auto report enabled=" + enabled);
            cb(enabled);
        }).catch(function () { enabled = false; cb(false); });
    }

    function send(message, stack) {
        var now = Date.now();
        var key = String(message).slice(0, 200);
        if (seen[key]) { log("duplicate on this page, skip"); return; }
        if (now - lastSent < MIN_INTERVAL_MS) { log("rate limited, skip"); return; }
        seen[key] = true;
        lastSent = now;
        var text = stripQuery(message) + (stack ? "\n\n" + stripQuery(stack) : "");
        fetch("/api/github/report", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ kind: "frontend", text: text.slice(0, 6000), component: location.pathname }),
        }).then(function (r) {
            if (r.status === 401) { enabled = false; log("not logged in — disabling for this page"); return; }
            if (r.status === 429) { log("daily limit reached"); return; }
            return r.json().then(function (d) { log("sent → " + (d && d.status) + " " + (d && d.url || "")); });
        }).catch(function (e) { log("send failed: " + e.message); });
    }

    function handle(message, stack) {
        try {
            if (!message) return;
            checkEnabled(function (on) { if (on) send(message, stack); });
        } catch (e) { /* never throw from an error handler */ }
    }

    window.addEventListener("error", function (ev) {
        var err = ev && ev.error;
        handle(ev && ev.message, err && err.stack);
    });
    window.addEventListener("unhandledrejection", function (ev) {
        var r = ev && ev.reason;
        handle(r && (r.message || String(r)), r && r.stack);
    });
    log("installed on " + location.pathname);

    /* Allow the settings panel to flip the flag without a reload. */
    window.__githubReportSetEnabled = function (on) { enabled = !!on; log("enabled set to " + enabled); };
})();
