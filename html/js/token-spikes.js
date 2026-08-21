/* token-spikes.js — Verlauf der Token-Wächter-Durchläufe (run-ki-dev.sh).
 * Struktur/Logik getrennt von token-spikes.html (frontend-architektur). */
(function () {
    'use strict';

    var allRuns = [];       // rohe Antwort von /api/token-guard/runs
    var thresholdDefault = 2000000;
    var loadSeq = 0;        // Sequenz-Zähler gegen Race Conditions bei schnellem Filterwechsel

    function t(key, fallback) {
        return (window.I18n && window.I18n.t) ? window.I18n.t(key, fallback) : fallback;
    }

    function fmtNum(n) { return (n || 0).toLocaleString('de-CH'); }

    function fmtTs(ts) {
        return (ts || '').replace('T', ' ').slice(0, 19);
    }

    async function load() {
        var days = document.getElementById('filter-days').value;
        console.debug('[TokenGuard] Lade Daten, days=' + days);
        var seq = ++loadSeq; // eigene Anfrage-Nummer: bei schnellem Filterwechsel
                              // koennen mehrere fetch() parallel laufen — nur die
                              // Antwort der zuletzt gestarteten Anfrage darf rendern.
        try {
            var res = await fetch('/api/token-guard/runs?days=' + encodeURIComponent(days));
            if (!res.ok) throw new Error('HTTP ' + res.status);
            var data = await res.json();
            if (seq !== loadSeq) {
                console.debug('[TokenGuard] Veraltete Antwort verworfen, seq=' + seq);
                return;
            }
            allRuns = data.runs || [];
            thresholdDefault = data.threshold_default || thresholdDefault;

            fillNameFilter();
            document.getElementById('last-updated').textContent =
                'Stand: ' + new Date().toLocaleTimeString('de-CH');
            document.getElementById('loading').style.display = 'none';
            document.getElementById('chart-wrap').style.display = '';
            document.getElementById('table-wrap').style.display = '';
            render();
            console.debug('[TokenGuard] Geladen:', allRuns.length, 'Läufe');
        } catch (e) {
            if (seq !== loadSeq) return; // veraltete/abgebrochene Anfrage, nicht mehr relevant
            document.getElementById('loading').textContent = '⚠️ Fehler: ' + e.message;
            console.error('[TokenGuard] Ladefehler:', e);
        }
    }

    function fillNameFilter() {
        var sel = document.getElementById('filter-name');
        var current = sel.value;
        var names = Array.from(new Set(allRuns.map(function (r) { return r.name; }))).sort();
        sel.innerHTML = '<option value="">' + t('tokenguard.allscripts', 'Alle Skripte') + '</option>';
        names.forEach(function (n) {
            var opt = document.createElement('option');
            opt.value = n; opt.textContent = n;
            sel.appendChild(opt);
        });
        if (names.indexOf(current) !== -1) sel.value = current;
    }

    function filtered() {
        var name = document.getElementById('filter-name').value;
        var rows = name ? allRuns.filter(function (r) { return r.name === name; }) : allRuns.slice();
        // Chart liest sich links->rechts als Zeitachse: älteste zuerst.
        rows.sort(function (a, b) { return (a.ts || '').localeCompare(b.ts || ''); });
        return rows;
    }

    function render() {
        var rows = filtered();
        renderSummary(rows);
        renderChart(rows);
        renderTable(rows.slice().reverse()); // Tabelle: neueste zuerst
        document.getElementById('row-count').textContent = rows.length + ' Läufe';
    }

    // Referenz-Schwelle: threshold des neuesten SICHTBAREN Laufs statt des globalen
    // Defaults — sonst kann ein bereits korrekt (anhand seines eigenen r.threshold)
    // als Spike markierter Balken optisch unter der Linie liegen, wenn
    // TOKEN_GUARD_THRESHOLD zwischenzeitlich geändert wurde. rows ist aufsteigend
    // nach ts sortiert (siehe filtered()), also ist der letzte Eintrag der neueste.
    function currentThreshold(rows) {
        return rows.length ? rows[rows.length - 1].threshold : thresholdDefault;
    }

    function renderSummary(rows) {
        var spikes = rows.filter(function (r) { return r.spike; }).length;
        var maxWeighted = rows.reduce(function (m, r) { return Math.max(m, r.weighted); }, 0);
        document.getElementById('tg-summary').innerHTML =
            '<span>' + t('tokenguard.summary.runs', 'Läufe') + ': <b>' + rows.length + '</b></span>' +
            '<span>' + t('tokenguard.summary.spikes', 'Spikes') + ': <b style="color:#d03b3b">' + spikes + '</b></span>' +
            '<span>' + t('tokenguard.summary.max', 'Höchster Wert') + ': <b>' + fmtNum(maxWeighted) + '</b></span>' +
            '<span>' + t('tokenguard.summary.threshold', 'Schwelle') + ': <b>' + fmtNum(currentThreshold(rows)) + '</b></span>';
    }

    // ── SVG-Balkendiagramm ──────────────────────────────────────────────────
    // Mark-Specs (dataviz-Skill): duenne Balken, 4px gerundete Enden, 2px Abstand,
    // Status-Farbe statt kategorial (good/critical, fixe Hex-Werte), Schwelle als
    // gestrichelte Linie, Spike zusaetzlich mit ⚠-Icon markiert (Farbe traegt bei
    // Rot/Gruen NIE allein — CVD-Check des Validators schlug fehl, s. Plan).
    function renderChart(rows) {
        var svg = document.getElementById('tg-svg');
        var tooltip = document.getElementById('tg-tooltip');
        // Vor jedem Neuaufbau des SVG (auch beim 60s-Auto-Refresh) den Tooltip
        // ausblenden — sonst bleibt er sichtbar haengen, wenn die Maus beim Redraw
        // noch ueber einem alten Balken steht und kein mouseleave mehr feuert.
        tooltip.style.display = 'none';
        var W = Math.max(document.querySelector('.tg-chart-scroll').clientWidth - 24, rows.length * 18);
        var H = 220, padTop = 16, padBottom = 28, padLeft = 6, padRight = 6;
        var chartH = H - padTop - padBottom;

        if (!rows.length) {
            svg.setAttribute('width', W);
            svg.setAttribute('height', 60);
            svg.innerHTML = '<text x="10" y="30" class="tg-axis-label">' +
                t('tokenguard.empty', 'Keine Durchläufe in diesem Zeitraum.') + '</text>';
            return;
        }

        var refThreshold = currentThreshold(rows);
        var maxVal = Math.max(
            rows.reduce(function (m, r) { return Math.max(m, r.weighted); }, 0),
            refThreshold
        ) * 1.08;

        var barGap = 2, barW = Math.min(24, Math.max(6, (W - padLeft - padRight) / rows.length - barGap));
        var step = barW + barGap;
        var innerW = rows.length * step;
        svg.setAttribute('width', Math.max(W, innerW + padLeft + padRight));
        svg.setAttribute('height', H);

        function y(v) { return padTop + chartH - (v / maxVal) * chartH; }

        var parts = [];
        var thresholdY = y(refThreshold);
        parts.push('<line x1="' + padLeft + '" y1="' + thresholdY + '" x2="' + (padLeft + innerW) +
            '" y2="' + thresholdY + '" class="tg-threshold-line"></line>');

        rows.forEach(function (r, i) {
            var x = padLeft + i * step;
            var barH = Math.max(2, (r.weighted / maxVal) * chartH);
            var yTop = padTop + chartH - barH;
            var cls = r.spike ? 'tg-bar-critical' : 'tg-bar-good';
            parts.push(
                '<rect class="tg-bar ' + cls + '" x="' + x + '" y="' + yTop + '" width="' + barW +
                '" height="' + barH + '" rx="4" data-idx="' + i + '"></rect>'
            );
            if (r.spike) {
                parts.push('<text class="tg-spike-icon" x="' + (x + barW / 2) + '" y="' + (yTop - 4) +
                    '" text-anchor="middle">⚠️</text>');
            }
        });

        svg.innerHTML = parts.join('');
        svg.querySelectorAll('.tg-bar').forEach(function (el) {
            var r = rows[parseInt(el.dataset.idx, 10)];
            el.addEventListener('mousemove', function (ev) { showTooltip(ev, r); });
            el.addEventListener('mouseleave', hideTooltip);
        });

        function showTooltip(ev, r) {
            var statusText = r.spike
                ? '<span class="tg-tt-spike">⚠️ ' + t('tokenguard.legend.spike', 'Spike (über Schwelle)') + '</span>'
                : '✅ ' + t('tokenguard.legend.good', 'Normal');
            tooltip.innerHTML =
                '<b>' + escHtml(r.name) + '</b><br>' +
                fmtTs(r.ts) + '<br>' +
                t('tokenguard.col.weighted', 'Gewichtete Tokens') + ': ' + fmtNum(r.weighted) + '<br>' +
                t('tokenguard.col.threshold', 'Schwelle') + ': ' + fmtNum(r.threshold) + '<br>' +
                statusText;
            tooltip.style.left = (ev.clientX + 14) + 'px';
            tooltip.style.top = (ev.clientY + 14) + 'px';
            tooltip.style.display = '';
        }
        function hideTooltip() { tooltip.style.display = 'none'; }
    }

    function renderTable(rows) {
        document.getElementById('tg-table-body').innerHTML = rows.map(function (r) {
            var statusCls = r.spike ? 'td-status-critical' : 'td-status-good';
            var statusTxt = r.spike ? '⚠️ Spike' : '✅ ' + t('tokenguard.legend.good', 'Normal');
            return '<tr>' +
                '<td class="td-ts">' + fmtTs(r.ts) + '</td>' +
                '<td>' + escHtml(r.name) + '</td>' +
                '<td class="td-num">' + fmtNum(r.weighted) + '</td>' +
                '<td class="td-num">' + fmtNum(r.threshold) + '</td>' +
                '<td class="' + statusCls + '">' + statusTxt + '</td>' +
                '</tr>';
        }).join('');
    }

    document.getElementById('filter-days').addEventListener('change', load);
    document.getElementById('filter-name').addEventListener('change', render);
    window.addEventListener('resize', function () { render(); });

    load();
    setInterval(load, 60000);
})();
