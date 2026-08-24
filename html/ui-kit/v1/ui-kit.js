/* ============================================================================
 * Home-Stack UI-Kit v1 — geteilte Frontend-Helfer
 * Ausgeliefert unter: /ui-kit/v1/ui-kit.js (alt) / /ui-kit/v1/ui-kit.js (neu, relativ)
 * Quelle:             ~/Projekte/ui-verbesserungen/ui-kit/v1/ui-kit.js
 *
 * Loest die Logik ab, die bisher in jeder app.js dupliziert war: Tabs,
 * fetch-Helfer, Status-Dot, Theme-Toggle. Debug-Logs sind bewusst drin
 * (CLAUDE.md-Vorgabe) und lassen sich pro Seite abschalten.
 *
 * Einbinden:  <script src="/ui-kit/v1/ui-kit.js" defer></script>
 * Auto-Init laeuft bei DOMContentLoaded; abschalten via <body data-ui-autoinit="off">
 * ========================================================================== */
"use strict";

window.UI = (function () {
    var APP = document.documentElement.dataset.uiApp || document.title || "app";
    var DEBUG = document.documentElement.dataset.uiDebug !== "off";
    /* document.currentScript ist nur waehrend der synchronen Script-Ausfuehrung
       gueltig — im DOMContentLoaded-Handler (loadAddonModules) ist es bereits
       wieder null. Deshalb hier sofort sichern, nicht erst im Handler lesen. */
    var OWN_SCRIPT_SRC = document.currentScript ? document.currentScript.src : "";

    function dbg() {
        if (!DEBUG) return;
        var args = Array.prototype.slice.call(arguments);
        console.log.apply(console, ["[" + APP + "]"].concat(args));
    }

    function err() {
        var args = Array.prototype.slice.call(arguments);
        console.error.apply(console, ["[" + APP + "]"].concat(args));
    }

    /* ---------- API-Helfer ------------------------------------------------ */
    /* Wirft bei HTTP-Fehlern mit Statuscode + Server-Text, damit der Aufrufer
       eine brauchbare Meldung anzeigen kann statt "undefined". */
    async function api(path, options) {
        dbg("API-Aufruf:", path, options || "");
        var resp;
        try {
            resp = await fetch(path, options);
        } catch (e) {
            err("Netzwerkfehler bei", path, e);
            throw new Error("Netzwerkfehler bei " + path + ": " + e.message);
        }
        dbg("API-Antwort:", path, resp.status);
        if (!resp.ok) {
            var text = "";
            try { text = await resp.text(); } catch (e) { /* Body evtl. leer */ }
            throw new Error("HTTP " + resp.status + " bei " + path + ": " + text);
        }
        if (resp.status === 204) return null;
        var ctype = resp.headers.get("content-type") || "";
        return ctype.indexOf("json") >= 0 ? resp.json() : resp.text();
    }

    function post(path, body) {
        return api(path, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body)
        });
    }

    /* ---------- Tabs ------------------------------------------------------ */
    /* Erwartet .tab-btn[data-tab="x"] und #tab-x.tab-panel.
       Merkt den aktiven Tab pro Seite im localStorage. */
    function initTabs(opts) {
        opts = opts || {};
        var buttons = document.querySelectorAll(".tab-btn");
        if (!buttons.length) return;
        var key = "ui:tab:" + (opts.key || location.pathname);

        function activate(name, remember) {
            var panel = document.getElementById("tab-" + name);
            if (!panel) { dbg("Tab-Panel fehlt:", name); return false; }
            document.querySelectorAll(".tab-btn").forEach(function (b) {
                b.classList.toggle("active", b.dataset.tab === name);
                b.setAttribute("aria-selected", b.dataset.tab === name ? "true" : "false");
            });
            document.querySelectorAll(".tab-panel").forEach(function (p) {
                p.classList.toggle("active", p === panel);
            });
            if (remember !== false) {
                try { localStorage.setItem(key, name); } catch (e) { /* Privatmodus */ }
            }
            dbg("Tab aktiv:", name);
            document.dispatchEvent(new CustomEvent("ui:tab", { detail: { tab: name } }));
            return true;
        }

        buttons.forEach(function (btn) {
            btn.setAttribute("role", "tab");
            btn.addEventListener("click", function () { activate(btn.dataset.tab); });
        });

        var saved = null;
        try { saved = localStorage.getItem(key); } catch (e) { /* egal */ }
        if (!saved || !activate(saved, false)) {
            activate(buttons[0].dataset.tab, false);
        }
        return { activate: activate };
    }

    /* ---------- Status-Dot im Footer -------------------------------------- */
    /* Zeigt #status-dot / #status-text an; pollt optional weiter. */
    async function status(url, intervalMs) {
        url = url || "/api/status";
        var dot = document.getElementById("status-dot");
        var text = document.getElementById("status-text");
        if (!dot && !text) return;

        async function ping() {
            try {
                var data = await api(url);
                if (dot) dot.className = "dot ok";
                if (text) text.textContent = ((data && (data.service || data.name)) || "Backend") + " ok";
            } catch (e) {
                if (dot) dot.className = "dot err";
                if (text) text.textContent = "Backend nicht erreichbar";
                err("Status-Fehler:", e.message);
            }
        }

        await ping();
        if (intervalMs) setInterval(ping, intervalMs);
    }

    /* ---------- Theme ----------------------------------------------------- */
    /* Ohne gespeicherte Wahl entscheidet prefers-color-scheme (siehe CSS). */
    function applyTheme(mode) {
        if (mode === "light" || mode === "dark") {
            document.documentElement.dataset.theme = mode;
        } else {
            delete document.documentElement.dataset.theme;
        }
        dbg("Theme:", mode || "auto");
    }

    function initTheme() {
        var saved = null;
        try { saved = localStorage.getItem("ui:theme"); } catch (e) { /* egal */ }
        applyTheme(saved);

        document.querySelectorAll("[data-ui-theme-toggle]").forEach(function (btn) {
            btn.addEventListener("click", function () { toggleTheme(); });
        });
        return saved || "auto";
    }

    function toggleTheme() {
        var cur = document.documentElement.dataset.theme;
        var dark = cur ? cur === "dark"
                       : window.matchMedia("(prefers-color-scheme: dark)").matches;
        var next = dark ? "light" : "dark";
        applyTheme(next);
        try { localStorage.setItem("ui:theme", next); } catch (e) { /* egal */ }
        return next;
    }

    /* ---------- Toast ----------------------------------------------------- */
    function toast(msg, kind, ms) {
        var host = document.querySelector(".toast-host");
        if (!host) {
            host = document.createElement("div");
            host.className = "toast-host";
            document.body.appendChild(host);
        }
        var el = document.createElement("div");
        el.className = "toast" + (kind ? " " + kind : "");
        el.textContent = msg;
        el.setAttribute("role", kind === "err" ? "alert" : "status");
        host.appendChild(el);
        dbg("Toast:", kind || "info", msg);
        setTimeout(function () { el.remove(); }, ms || 4000);
        return el;
    }

    /* ---------- Kleinkram ------------------------------------------------- */
    function el(id) { return document.getElementById(id); }

    /* Escaped Text fuer innerHTML-Zusammenbau — nie ungeprueft interpolieren. */
    function esc(s) {
        return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
        });
    }

    /* ---------- Zusatz-Module laden ---------------------------------------- */
    /* Lädt error-buffer.js und report-button.js asynchron nach.
       Falls die scheitern, läuft die Seite trotzdem — diese Module sind optional. */
    function loadAddonModules() {
        try {
            var scriptSrc = OWN_SCRIPT_SRC || "/ui-kit/v1/ui-kit.js";
            var basePath = scriptSrc.substring(0, scriptSrc.lastIndexOf("/"));
            var modules = ["error-buffer.js", "report-button.js", "report-picker.js", "report-send.js"];
            modules.forEach(function (mod) {
                var script = document.createElement("script");
                script.src = basePath + "/" + mod;
                script.async = true;
                document.head.appendChild(script);
            });
        } catch (e) {
            err("Addon-Module konnten nicht geladen werden:", e.message);
        }
    }

    /* ---------- Auto-Init ------------------------------------------------- */
    document.addEventListener("DOMContentLoaded", function () {
        if (document.body.dataset.uiAutoinit === "off") {
            dbg("Auto-Init aus");
            return;
        }
        dbg("UI-Kit v1 startet");
        loadAddonModules();
        initTheme();
        initTabs();
        if (document.getElementById("status-dot")) status();
    });

    return {
        version: "1.0.0",
        dbg: dbg, err: err,
        api: api, post: post,
        initTabs: initTabs, status: status,
        initTheme: initTheme, toggleTheme: toggleTheme, applyTheme: applyTheme,
        toast: toast, el: el, esc: esc,
        loadAddonModules: loadAddonModules
    };
})();
