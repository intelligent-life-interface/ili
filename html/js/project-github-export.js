/* ============================================================================
 * project-github-export.js — "Als Issue exportieren" from the card detail view.
 *
 * Crowd path: an idea/task card becomes an issue in the ili repo — ONLY on an
 * explicit click, after the user saw (and could edit) the sanitized preview.
 * Card contents never leave the instance any other way.
 *
 * Flow: openGithubExport() → POST /api/github/report/preview (sanitized title
 * + body) → modal with editable fields → "Senden" → POST /api/github/report
 * {kind:"manual"} → issue URL written into the card description.
 * Without GitHub login the modal offers the deep link instead (browser form,
 * user's own account, nothing sent by the instance).
 *
 * Depends on project-core.js (board, BOARD_ID, saveBoard) and
 * project-detail.js (detailState). Texts via window.I18N (gh.* keys).
 * ========================================================================== */
"use strict";

(function () {
    var log = function () { try { console.debug.apply(console, ["[gh-export]"].concat([].slice.call(arguments))); } catch (e) {} };
    var t = function (k, fb) { return (window.I18n && I18n.t) ? I18n.t(k, fb) : ((window.I18N && I18N[k]) || fb); };

    function currentCard() {
        var st = (typeof detailState !== "undefined" && detailState) || {};
        if (st.ci == null || st.ki == null) return null;
        var col = board.columns[st.ci];
        return col && col.cards ? col.cards[st.ki] : null;
    }

    function ensureModal() {
        var m = document.getElementById("gh-export-modal");
        if (m) return m;
        m = document.createElement("div");
        m.className = "modal-overlay";
        m.id = "gh-export-modal";
        m.onclick = function (ev) { if (ev.target === m) closeGithubExport(); };
        m.innerHTML =
            '<div class="modal detail-modal">' +
            '  <div class="detail-head"><h2>' + escHtml(t("gh.export.title", "Karte als GitHub-Issue exportieren")) + '</h2>' +
            '    <button class="detail-close" onclick="closeGithubExport()" title="Schliessen">✕</button></div>' +
            '  <p style="color:#a0aec0;font-size:0.85rem" id="gh-export-note"></p>' +
            '  <label>Titel</label><input id="gh-export-title" maxlength="120" style="width:100%">' +
            '  <label>Text</label><textarea id="gh-export-body" style="width:100%;min-height:180px"></textarea>' +
            '  <div id="gh-export-status" style="font-size:0.85rem;margin-top:0.4rem"></div>' +
            '  <div class="modal-actions">' +
            '    <a class="btn" id="gh-export-deeplink" target="_blank" rel="noopener" style="margin-right:auto"></a>' +
            '    <button class="btn" onclick="closeGithubExport()">Abbrechen</button>' +
            '    <button class="btn primary" id="gh-export-send" onclick="sendGithubExport()"></button>' +
            '  </div></div>';
        document.body.appendChild(m);
        return m;
    }

    window.openGithubExport = function () {
        var card = currentCard();
        if (!card) { log("no card selected"); return; }
        var m = ensureModal();
        var text = (card.title || "") + "\n\n" + (card.desc || card.description || "");
        document.getElementById("gh-export-note").textContent = t("gh.export.note", "");
        document.getElementById("gh-export-send").textContent = t("gh.export.send", "Senden");
        document.getElementById("gh-export-status").textContent = "";
        var dl = document.getElementById("gh-export-deeplink");
        dl.textContent = t("gh.export.deeplink", "Im Browser auf GitHub öffnen");
        dl.style.display = "none";
        log("preview for card " + card.id);
        fetch("/api/github/report/preview", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ kind: "manual", text: text, component: "card", title: card.title || "" }),
        }).then(function (r) { return r.json(); }).then(function (p) {
            document.getElementById("gh-export-title").value = p.title || "";
            document.getElementById("gh-export-body").value = p.body || "";
            log("sanitized:", p.sanitized);
            return fetch("/api/github/auth/status").then(function (r) { return r.json(); });
        }).then(function (st) {
            var send = document.getElementById("gh-export-send");
            if (!st.logged_in) {
                send.disabled = true;
                send.title = t("gh.status.off", "Nicht angemeldet");
                var dl = document.getElementById("gh-export-deeplink");
                dl.style.display = "";
                dl.onclick = function () {
                    var q = "title=" + encodeURIComponent(document.getElementById("gh-export-title").value) +
                            "&body=" + encodeURIComponent(document.getElementById("gh-export-body").value) + "&template=idea.yml";
                    fetch("/api/github/deeplink?" + q).then(function (r) { return r.json(); })
                        .then(function (d) { window.open(d.url, "_blank", "noopener"); });
                    return false;
                };
            } else {
                send.disabled = false;
                send.title = "";
            }
            m.classList.add("open");
        }).catch(function (e) {
            log("preview failed: " + e.message);
            document.getElementById("gh-export-status").textContent = t("gh.export.fail", "Fehler:") + " " + e.message;
            m.classList.add("open");
        });
    };

    window.closeGithubExport = function () {
        var m = document.getElementById("gh-export-modal");
        if (m) m.classList.remove("open");
    };

    window.sendGithubExport = function () {
        var card = currentCard();
        var status = document.getElementById("gh-export-status");
        var send = document.getElementById("gh-export-send");
        send.disabled = true;
        fetch("/api/github/report", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                kind: "manual", component: "card",
                title: document.getElementById("gh-export-title").value,
                text: document.getElementById("gh-export-body").value,
            }),
        }).then(function (r) {
            return r.json().then(function (d) { if (!r.ok) throw new Error(d.error || d.detail || r.status); return d; });
        }).then(function (d) {
            log("issue created: " + d.url);
            status.innerHTML = escHtml(t("gh.export.done", "Issue erstellt:")) + ' <a href="' + escHtml(d.url) + '" target="_blank" rel="noopener">#' + escHtml(String(d.issue_number)) + "</a>";
            if (card && d.url) {
                var appended = (card.desc || card.description || "") + "\n\nGitHub: " + d.url;
                card.desc = appended; card.description = appended;   // both fields, see project_dashboard_desc_feld
                if (typeof saveBoard === "function") saveBoard();
            }
        }).catch(function (e) {
            log("send failed: " + e.message);
            status.textContent = t("gh.export.fail", "Fehler:") + " " + e.message;
            send.disabled = false;
        });
    };
})();
