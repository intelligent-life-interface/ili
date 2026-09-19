/* __NAME__ – projekteigene Frontend-Logik.
 *
 * Tabs, Theme-Umschaltung und der Status-Dot im Footer laufen automatisch
 * über das zentrale UI-Kit (ui-kit.js). Hier steht nur, was dieses Projekt
 * zusätzlich macht.
 *
 * Verfügbare Helfer (Details: https://ui.intranet.<DOMAIN>/ → Tab "JS-Helfer"):
 *   UI.api(pfad, options)   GET/beliebig, wirft mit Statuscode + Servertext
 *   UI.post(pfad, objekt)   JSON-POST
 *   UI.toast(text, "ok"|"err")
 *   UI.el(id)               document.getElementById
 *   UI.esc(text)            escapen vor innerHTML
 *   UI.dbg(...)             Debug-Log mit [__NAME__]-Präfix
 */
"use strict";

document.addEventListener("DOMContentLoaded", function () {
    UI.dbg("__NAME__ Frontend startet");

    /* Beispiel: Daten laden, sobald ein Tab geöffnet wird
    document.addEventListener("ui:tab", async function (ev) {
        if (ev.detail.tab !== "daten") return;
        try {
            const daten = await UI.api("/api/daten");
            UI.dbg("Daten geladen:", daten.length);
        } catch (e) {
            UI.toast(e.message, "err");
        }
    });
    */
});
