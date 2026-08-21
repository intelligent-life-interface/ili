/* index.js — dynamische Projekt-Übersicht (index-new.html).
 *
 * Lädt EIN Aggregat von GET /api/dashboard (via window.API aus api.js) und
 * rendert clientseitig — ersetzt die statisch generierte index.html
 * (generate_dashboard.py) inkl. deren N+1 /board?id=…-Requests.
 *
 * Features: Gruppierung (Kategorie / Status / Alphabetisch), Suche,
 *           Zoom ± (localStorage), Klick → project.html?id=…
 */
(function () {
    'use strict';

    var TAG = '[IndexNew]';

    // ── State ────────────────────────────────────────────────────
    var data = null;                  // /api/dashboard-Payload
    var groupMode = localStorage.getItem('idx_group') || 'category';
    // Eisenhower-Modus: pro Kategorie ("Thema") eine eigene Prioritäts-Matrix.
    // Persistiert zentral im Manifest-Feld `eisenhower` (q1..q4 | ""), darum
    // synchron mit Isehauer. Hier nur Darstellung + Setzen via PATCH.
    var eisOn = localStorage.getItem('idx_eisenhower') === '1';
    var showArchived = false;   // 🗄-Toggle: Archiv-Ansicht (zeigt NUR archivierte zum Aufräumen)
    // Arrange-Modus: Drag-and-Drop Reihenfolge der Projektkacheln (nur Kategorie-Ansicht)
    var arrangeMode = localStorage.getItem('idx_arrange') === '1';
    var customOrder = (function() {
        try { return JSON.parse(localStorage.getItem('idx_order') || '{}'); } catch(e) { return {}; }
    })();
    var EIS_ZONES = [
        { key: 'q1', title: '🔴 Dringend & wichtig',         hint: 'sofort' },
        { key: 'q2', title: '🟡 Dringend oder wichtig',      hint: 'bald' },
        { key: 'q3', title: '🟢 Unwichtig & nicht dringend', hint: 'kann warten' },
        { key: 'q4', title: '⚫ Nicht umsetzen',             hint: 'zum Vergessen' },
        { key: '',   title: '📥 Noch nicht einsortiert',     hint: 'hierher ziehen →' }
    ];
    // Schnell-Knöpfe pro Karte (Touch-/Klick-Alternative zu Drag&Drop)
    var EIS_QUICK = [
        { key: 'q1', emoji: '🔴', title: 'Dringend & wichtig' },
        { key: 'q2', emoji: '🟡', title: 'Dringend oder wichtig' },
        { key: 'q3', emoji: '🟢', title: 'Unwichtig & nicht dringend' },
        { key: 'q4', emoji: '⚫', title: 'Nicht umsetzen' },
        { key: '',   emoji: '📥', title: 'Zurück in „nicht einsortiert"' }
    ];
    // Listenansicht (📋 Liste): flache Liste, gruppiert nach Gruppe (Kategorie),
    // sortiert innerhalb der Gruppe nach Eisenhower-Prio (q1→q4→ohne) dann Name.
    // Drei Dropdown-Filter (Gruppe, Auto-Entwicklung-Status, Projekt-Status), persistiert
    // im localStorage. Auto-Status und Projekt-Status sind zwei verschiedene Dinge:
    // ersterer ist abgeleitet (hat der Bot noch Karten?), letzterer ist das
    // Lebenszyklus-Feld `status` — siehe CLAUDE.md.
    var listFilterCat = localStorage.getItem('idx_list_cat') || '';
    var listFilterAuto = localStorage.getItem('idx_list_auto') || '';
    var listFilterStatus = localStorage.getItem('idx_list_status') || '';
    var EIS_RANK = { q1: 0, q2: 1, q3: 2, q4: 3, '': 4 };
    function eisRank(p) { var k = p.eisenhower || ''; return EIS_RANK.hasOwnProperty(k) ? EIS_RANK[k] : 4; }
    var EIS_EMOJI = { q1: '🔴', q2: '🟡', q3: '🟢', q4: '⚫', '': '📥' };
    var EIS_TITLE = {
        q1: 'Dringend & wichtig', q2: 'Dringend oder wichtig',
        q3: 'Unwichtig & nicht dringend', q4: 'Nicht umsetzen', '': 'Nicht einsortiert'
    };
    var AUTO_OPT_LABEL = { aus: 'Aus', an: 'Läuft', erledigt: 'Erledigt', entscheidung: 'Entscheidung nötig' };

    var ZOOM_STEPS = [200, 240, 280, 320, 380];   // --card-min-width px
    var DEFAULT_STEP = 2;                          // 280px = 100%
    var zoomStep = parseInt(localStorage.getItem('idx_zoom'), 10);
    if (isNaN(zoomStep) || zoomStep < 0 || zoomStep >= ZOOM_STEPS.length) zoomStep = DEFAULT_STEP;

    // Server-Tag-Suche (GET /search-by-tag): findet Treffer im VOLLEN Index — auch
    // container-Projekte, die kein Board haben und darum gar nicht im /api/dashboard-
    // Payload stecken. tagHits = letzte Server-Antwort, tagQuery = wofür sie galt.
    var tagHits = [];
    var tagQuery = '';
    var tagTimer = null;

    // Boards mit offener Entscheidungskarte (GET /api/automat/decisions) — Grundlage
    // für den Status „Entscheidung nötig" des Auto-Weiterentwicklungs-Schalters.
    // Map board-slug -> true; wird in init() nach dem Dashboard-Load befüllt.
    var autoDecisions = {};

    // ── Helpers ──────────────────────────────────────────────────
    const escHtml = window.escHtml;

    // i18n-Lookup mit Fallback — Woerterbuch aus html/i18n/de.js (window.I18N).
    // Fehlt der Key oder ist die Datei nicht geladen, gilt der Fallback-Text,
    // die Seite rendert also auch ohne ui.intranet unveraendert weiter.
    function t(key, fallback) {
        var w = window.I18N;
        return (w && w[key]) || fallback;
    }

    function catInfo(catId) {
        var c = (data && data.categories && data.categories[catId]) || null;
        return {
            label: c ? c.label : (catId || 'Ohne Kategorie'),
            color: c ? c.color : null,
            emoji: c ? c.emoji : '📁'
        };
    }

    function showError(msg) {
        var el = document.getElementById('error-banner');
        el.textContent = msg;
        el.style.display = 'block';
        console.error(TAG, 'Fehler:', msg);
    }

    // ── Zoom ─────────────────────────────────────────────────────
    function applyZoom() {
        var px = ZOOM_STEPS[zoomStep];
        document.documentElement.style.setProperty('--card-min-width', px + 'px');
        var pct = Math.round(px / ZOOM_STEPS[DEFAULT_STEP] * 100);
        document.getElementById('zoom-label').textContent = pct + '%';
        localStorage.setItem('idx_zoom', String(zoomStep));
        console.debug(TAG, 'Zoom:', px + 'px (' + pct + '%)');
    }

    function changeZoom(delta) {
        var next = zoomStep + delta;
        if (next < 0 || next >= ZOOM_STEPS.length) return;
        zoomStep = next;
        applyZoom();
    }

    // ── Custom-Order Helpers (Arrange-Modus) ─────────────────────
    function applyStoredOrder(catId, items) {
        var stored = customOrder[catId] || [];
        var sort = function(a, b) { return (a.name || a.id).localeCompare(b.name || b.id, 'de'); };
        if (!stored.length) return items.slice().sort(sort);
        var byId = {};
        items.forEach(function(p) { byId[p.id] = p; });
        var ordered = [];
        stored.forEach(function(id) { if (byId[id]) { ordered.push(byId[id]); delete byId[id]; } });
        var remaining = Object.keys(byId).map(function(k) { return byId[k]; }).sort(sort);
        return ordered.concat(remaining);
    }

    function saveCustomOrder(catId, ids) {
        customOrder[catId] = ids;
        try { localStorage.setItem('idx_order', JSON.stringify(customOrder)); } catch(e) {}
        console.log(TAG, 'Reihenfolge gespeichert für "' + catId + '":', ids.length, 'Einträge');
    }

    function initArrangeGrid(grid, catId) {
        var dragging = null;
        Array.from(grid.querySelectorAll('.project-card[data-id]')).forEach(function(card) {
            card.draggable = true;
            card.addEventListener('dragstart', function(e) {
                dragging = card;
                e.dataTransfer.effectAllowed = 'move';
                e.dataTransfer.setData('text/plain', card.dataset.id);
                requestAnimationFrame(function() { if (dragging === card) card.classList.add('dragging'); });
            });
            card.addEventListener('dragend', function() {
                dragging = null;
                card.classList.remove('dragging');
                grid.querySelectorAll('.drop-before,.drop-after').forEach(function(el) {
                    el.classList.remove('drop-before', 'drop-after');
                });
            });
            card.addEventListener('dragover', function(e) {
                if (!dragging || card === dragging) return;
                e.preventDefault();
                e.dataTransfer.dropEffect = 'move';
                grid.querySelectorAll('.drop-before,.drop-after').forEach(function(el) {
                    el.classList.remove('drop-before', 'drop-after');
                });
                var rect = card.getBoundingClientRect();
                card.classList.add(e.clientX < rect.left + rect.width / 2 ? 'drop-before' : 'drop-after');
            });
            card.addEventListener('dragleave', function(e) {
                if (!card.contains(e.relatedTarget)) {
                    card.classList.remove('drop-before', 'drop-after');
                }
            });
            card.addEventListener('drop', function(e) {
                if (!dragging || card === dragging) return;
                e.preventDefault();
                var fromId = dragging.dataset.id;
                var insertBefore = card.classList.contains('drop-before');
                card.classList.remove('drop-before', 'drop-after');
                var allCards = Array.from(grid.querySelectorAll('.project-card[data-id]'));
                var ids = allCards.map(function(c) { return c.dataset.id; });
                var fromIdx = ids.indexOf(fromId);
                if (fromIdx < 0) return;
                ids.splice(fromIdx, 1);
                var toIdx = ids.indexOf(card.dataset.id);
                if (toIdx < 0) return;
                ids.splice(insertBefore ? toIdx : toIdx + 1, 0, fromId);
                console.log(TAG, 'DnD drop: neue Reihenfolge für "' + catId + '":', ids);
                saveCustomOrder(catId, ids);
                applyFilter();
            });
        });
        grid.classList.add('arrange-active');
        console.log(TAG, 'Arrange-Grid init:', catId, grid.querySelectorAll('.project-card[data-id]').length, 'Karten');
    }

    function refreshArrangeUI() {
        var arrBtn = document.getElementById('arrange-toggle');
        var rstBtn = document.getElementById('arrange-reset');
        if (!arrBtn) return;
        var active = arrangeMode && groupMode === 'category' && !eisOn && !showArchived;
        arrBtn.classList.toggle('active', active);
        if (rstBtn) {
            var hasOrder = Object.keys(customOrder).some(function(k) { return (customOrder[k] || []).length > 0; });
            rstBtn.style.display = (active && hasOrder) ? '' : 'none';
        }
    }

    // ── Kachel ───────────────────────────────────────────────────
    function renderCard(p) {
        var cat = catInfo(p.category);
        var color = cat.color || p.color || '#4a90d9';
        var icon = cat.emoji || p.icon || '📁';

        var card = document.createElement('div');
        card.className = 'project-card';
        card.style.setProperty('--cat-color', color);
        card.title = p.name || p.id;
        card.dataset.id = p.id;
        if (p.cover_photo) {
            card.classList.add('has-photo');
            card.style.backgroundImage = 'url(\'' + p.cover_photo + '\')';
        }

        var c = p.counts || { backlog: 0, in_progress: 0, done: 0 };
        var badges =
            '<span><span class="badge-num badge-backlog">' + c.backlog + '</span> Backlog</span>' +
            '<span>·</span>' +
            '<span><span class="badge-num badge-in_progress">' + c.in_progress + '</span> In Arbeit</span>' +
            '<span>·</span>' +
            '<span><span class="badge-num badge-done">' + c.done + '</span> Erledigt</span>';
        if (p.sub_count > 0) {
            badges += '<span class="badge-sub">📂 ' + p.sub_count + '</span>';
        }
        if (p.att_count > 0) {
            // Klickbarer Zugang direkt zu den Anhängen (öffnet das Anhänge-Modal im Projekt)
            badges += '<span class="badge-att" data-att="1" title="Anhänge öffnen">📎 ' + p.att_count + '</span>';
        }

        // Aktionen (Archivieren/Entarchivieren + Löschen) — stopPropagation im Handler, damit
        // ein Klick darauf NICHT das Projekt öffnet.
        var actions =
            (p.archived
                ? '<button class="card-act" data-act="unarchive" title="Aus Archiv zurückholen">♻️</button>'
                : '<button class="card-act" data-act="archive" title="Archivieren (aus Übersicht ausblenden)">🗄</button>') +
            '<button class="card-act card-act-del" data-act="delete" title="Projekt löschen">🗑</button>';

        // Prioritaet (Manifest-Feld `eisenhower`) auch ausserhalb des Priorisieren-Modus
        // sichtbar — nur wenn gesetzt, sonst waeren fast alle Kacheln mit 📥 zugepflastert.
        var eisKey = p.eisenhower || '';
        var prioBadge = eisKey
            ? '<span class="card-prio" title="Priorität: ' + escHtml(EIS_TITLE[eisKey] || '') + '">' + EIS_EMOJI[eisKey] + '</span>'
            : '';

        card.innerHTML =
            '<div class="card-actions">' + actions + '</div>' +
            '<div class="card-title">' + prioBadge + escHtml(icon) + ' ' + escHtml(p.name || p.id) + '</div>' +
            (p.description ? '<div class="card-desc">' + escHtml(p.description) + '</div>' : '') +
            // Worklog: jüngste Aktivität (Commits/Claude-Sessions), via project_describer aus worklog.md
            (p.last_activity ? '<div class="card-activity">🕒 ' + escHtml(p.last_activity) + '</div>' : '') +
            '<div class="card-badges">' + badges + '</div>';

        card.addEventListener('click', function (e) {
            // Aktions-Knopf? → Archivieren/Löschen, Projekt NICHT öffnen.
            var act = e.target.closest('.card-act');
            if (act) {
                e.stopPropagation();
                var a = act.getAttribute('data-act');
                if (a === 'archive') archiveProject(p.id, true);
                else if (a === 'unarchive') archiveProject(p.id, false);
                else if (a === 'delete') deleteProject(p);
                return;
            }
            // Klick auf das 📎-Badge → Projekt mit geöffnetem Anhänge-Modal
            var att = e.target.closest('.badge-att');
            var url = '/project.html?id=' + encodeURIComponent(p.id) + (att ? '&att=1' : '');
            console.log(TAG, 'Öffne Projekt:', p.id, att ? '(Anhänge)' : '');
            window.location.href = url;
        });
        return card;
    }

    // ── Archivieren / Löschen ────────────────────────────────────
    // Archivieren = Manifest-Feld `archived` (optimistisch + PATCH-Rollback), reversibel.
    function archiveProject(id, flag) {
        var p = (data.projects || []).find(function (x) { return x.id === id; });
        if (!p) return;
        p.archived = flag;            // optimistisch sofort ausblenden/zeigen
        applyFilter();
        console.log(TAG, 'Archiv:', id, '→', flag);
        window.API.patchBoard(id, { archived: flag }).catch(function (err) {
            console.error(TAG, 'Archiv-PATCH fehlgeschlagen, Rollback:', err);
            p.archived = !flag; applyFilter();
            alert('Archivieren fehlgeschlagen: ' + err);
        });
    }

    // Löschen — 2 Bestätigungen: (1) überhaupt löschen, (2) auch Ordner/Dateien (purge)?
    function deleteProject(p) {
        var name = p.name || p.id;
        // Ordner-Löschung (purge) nur für Ideen/Foto-Boards anbieten — echte Projekte
        // (oft Quellcode/Repos in ~/Projekte) werden nur aus dem Dashboard entfernt.
        var isIdea = p.type === 'idea' || /^foto[-_]/.test(p.id || '');
        if (!confirm('Projekt „' + name + '" löschen?\n\nDas Board verschwindet aus dem Dashboard.')) return;
        var purge = false;
        if (isIdea) {
            purge = confirm('Auch den Projektordner mit allen Dateien/Fotos endgültig löschen?\n\n' +
                'OK = komplett löschen (unwiderruflich)\n' +
                'Abbrechen = nur aus Dashboard entfernen, Dateien als Backup behalten');
        }
        console.log(TAG, 'Löschen:', p.id, 'isIdea=', isIdea, 'purge=', purge);
        window.API.deleteBoard(p.id, purge).then(function (res) {
            console.log(TAG, 'Gelöscht:', p.id, res);
            data.projects = (data.projects || []).filter(function (x) { return x.id !== p.id; });
            applyFilter();
        }).catch(function (err) {
            console.error(TAG, 'Löschen fehlgeschlagen:', err);
            alert('Löschen fehlgeschlagen: ' + err);
        });
    }

    // ── Eisenhower-Priorisierung ─────────────────────────────────
    // Setzt das zentrale Manifest-Feld `eisenhower` (optimistic + PATCH-Rollback).
    function setEisenhower(id, key) {
        var p = (data.projects || []).find(function (x) { return x.id === id; });
        if (!p) return;
        if ((p.eisenhower || '') === (key || '')) return;
        var prev = p.eisenhower || '';
        p.eisenhower = key;          // optimistisch sofort umsortieren
        applyFilter();
        console.log(TAG, 'Eisenhower:', id, (prev || '∅'), '→', (key || '∅'));
        window.API.patchBoard(id, { eisenhower: key }).catch(function (err) {
            p.eisenhower = prev;     // Rollback bei Fehler
            applyFilter();
            showError('Priorität konnte nicht gespeichert werden: ' + err.message);
        });
    }

    // ── Automatische Weiterentwicklung (auto-Flag, 4 Status) ─────
    // In der Priorisierungs-Ansicht pro Kachel bedienbar. Nur „aus" ↔ „an" sind
    // per Klick umschaltbar (steuern das Manifest-Feld `auto` = Freigabe für den
    // Kanban-Automaten). „erledigt" und „entscheidung" sind ABGELEITET und werden
    // nicht direkt gesetzt:
    //   aus          — auto=false: Automat rührt das Projekt nicht an
    //   an           — auto=true, es gibt offene Karten, keine offene Entscheidung
    //   erledigt     — auto=true, keine offenen Karten mehr (p.automat_open === 0)
    //   entscheidung — auto=true, offene Entscheidungskarte → Automat wartet auf Antwort
    // Basis ist `automat_open` (Backlog+In Arbeit OHNE Meta-Karten, s.
    // dashboard_service._count_automat_open) und NICHT die angezeigten `counts` — sonst
    // stünde ein leergearbeitetes Projekt weiter auf „an", nur weil die
    // CLAUDE.md-Beschreibungskarte im Backlog liegt.
    var AUTO_STATE = {
        aus:          { emoji: '⚪', label: 'Auto-Weiterentwicklung: aus',                 cls: 'auto-aus' },
        an:           { emoji: '🤖', label: 'Auto-Weiterentwicklung: an — läuft',          cls: 'auto-an' },
        erledigt:     { emoji: '✅', label: 'Auto-Weiterentwicklung: abgeschlossen — keine Karten mehr', cls: 'auto-erledigt' },
        entscheidung: { emoji: '🙋', label: 'Entscheidung nötig — Automat wartet auf dich', cls: 'auto-entscheidung' }
    };

    function autoStateKey(p) {
        if (!p.auto) return 'aus';
        if (autoDecisions[p.id]) return 'entscheidung';
        var c = p.counts || {};
        var offen = (p.automat_open !== undefined && p.automat_open !== null)
            ? p.automat_open
            : (c.backlog || 0) + (c.in_progress || 0);   // Fallback: alte Payload ohne Feld
        if (offen === 0) return 'erledigt';
        return 'an';
    }

    // Auto-Flag setzen (optimistic + PATCH-Rollback), Klick toggelt nur aus↔an.
    function setAuto(id, next) {
        var p = (data.projects || []).find(function (x) { return x.id === id; });
        if (!p) return;
        var prev = !!p.auto;
        if (prev === !!next) return;
        p.auto = !!next;             // optimistisch sofort umschalten
        applyFilter();
        console.log(TAG, 'Auto-Weiterentwicklung:', id, prev, '→', !!next);
        window.API.patchBoard(id, { auto: !!next }).catch(function (err) {
            p.auto = prev;           // Rollback bei Fehler
            applyFilter();
            showError('Auto-Weiterentwicklung konnte nicht gespeichert werden: ' + err.message);
        });
    }

    // Projekt-Kachel im Eisenhower-Modus: draggable + Schnell-Knöpfe (Touch).
    function renderEisCard(p) {
        var card = renderCard(p);
        card.classList.add('eis-card');
        card.draggable = true;
        card.dataset.id = p.id;
        card.addEventListener('dragstart', function (e) {
            e.dataTransfer.setData('text/plain', p.id);
            e.dataTransfer.effectAllowed = 'move';
            card.classList.add('dragging');
        });
        card.addEventListener('dragend', function () { card.classList.remove('dragging'); });

        var bar = document.createElement('div');
        bar.className = 'eis-quickbar';
        EIS_QUICK.forEach(function (q) {
            var b = document.createElement('button');
            b.type = 'button';
            b.className = 'eis-qbtn' + ((p.eisenhower || '') === q.key ? ' active' : '');
            b.textContent = q.emoji;
            b.title = q.title;
            b.addEventListener('click', function (e) {
                e.stopPropagation();   // nicht ins Projekt navigieren
                setEisenhower(p.id, q.key);
            });
            bar.appendChild(b);
        });

        // Auto-Weiterentwicklungs-Schalter (4 Status) — rechts abgesetzt.
        // Klick toggelt nur aus↔an; erledigt/entscheidung sind abgeleitet.
        var stKey = autoStateKey(p);
        var st = AUTO_STATE[stKey];
        var ab = document.createElement('button');
        ab.type = 'button';
        ab.className = 'eis-autobtn ' + st.cls;
        ab.textContent = st.emoji;
        ab.title = st.label + '  ·  Klick: ' + (p.auto ? 'ausschalten' : 'einschalten');
        ab.addEventListener('click', function (e) {
            e.stopPropagation();     // nicht ins Projekt navigieren
            setAuto(p.id, !p.auto);
        });
        bar.appendChild(ab);

        card.appendChild(bar);
        return card;
    }

    // Pro Kategorie ("Thema") ein eigenes Board mit den Zonen aus EIS_ZONES.
    function renderEisenhower(projects, area) {
        var byName = function (a, b) { return (a.name || a.id).localeCompare(b.name || b.id, 'de'); };
        var buckets = {};
        projects.forEach(function (p) {
            var k = p.category || '_none';
            (buckets[k] = buckets[k] || []).push(p);
        });
        // Reihenfolge: erst bekannte Kategorien (wie data.categories), Rest alphabetisch
        var order = [];
        Object.keys(data.categories || {}).forEach(function (c) { if (buckets[c]) order.push(c); });
        Object.keys(buckets).sort().forEach(function (c) { if (order.indexOf(c) === -1) order.push(c); });

        order.forEach(function (catId) {
            var items = buckets[catId].slice().sort(byName);
            var ci = catInfo(catId);
            var section = document.createElement('section');
            section.className = 'group-section';

            var h = document.createElement('h2');
            h.className = 'group-heading';
            var label = (catId === '_none') ? '📁 Ohne Kategorie' : (ci.emoji + ' ' + ci.label);
            h.innerHTML = escHtml(label) + ' <span class="group-count">' + items.length + '</span>';
            section.appendChild(h);

            var board = document.createElement('div');
            board.className = 'eis-board';
            EIS_ZONES.forEach(function (z) {
                var zone = document.createElement('div');
                zone.className = 'eis-zone eis-' + (z.key || 'none');
                zone.dataset.key = z.key;
                var inZone = items.filter(function (p) { return (p.eisenhower || '') === z.key; });
                zone.innerHTML =
                    '<div class="eis-zone-head">' + escHtml(z.title) +
                    ' <span class="eis-zone-count">' + inZone.length + '</span>' +
                    '<span class="eis-zone-hint">' + escHtml(z.hint) + '</span></div>';
                var body = document.createElement('div');
                body.className = 'eis-zone-body';
                inZone.forEach(function (p) { body.appendChild(renderEisCard(p)); });
                zone.appendChild(body);

                zone.addEventListener('dragover', function (e) { e.preventDefault(); zone.classList.add('drop-hover'); });
                zone.addEventListener('dragleave', function () { zone.classList.remove('drop-hover'); });
                zone.addEventListener('drop', function (e) {
                    e.preventDefault();
                    zone.classList.remove('drop-hover');
                    var id = e.dataTransfer.getData('text/plain');
                    if (id) setEisenhower(id, z.key);
                });
                board.appendChild(zone);
            });
            section.appendChild(board);
            area.appendChild(section);
        });
        console.log(TAG, 'Eisenhower-Render:', projects.length, 'Projekte in', order.length, 'Themen');
    }

    // ── Listenansicht (📋 Liste) ─────────────────────────────────
    // Eine Zeile pro Projekt statt Kachel: kompakt, zeigt Prio + Auto-Status direkt,
    // sortiert innerhalb jeder Gruppe (Kategorie) nach Eisenhower-Prio dann Name.
    function renderListRow(p) {
        var cat = catInfo(p.category);
        var color = cat.color || p.color || '#4a90d9';
        var icon = cat.emoji || p.icon || '📁';
        var eisKey = p.eisenhower || '';
        var c = p.counts || { backlog: 0, in_progress: 0, done: 0 };
        var stKey = autoStateKey(p);
        var st = AUTO_STATE[stKey];
        // Projekt-Status (Lebenszyklus, Manifest-Feld `status` — orthogonal zum
        // Auto-Entwicklungs-Status rechts!). Kommt aus data.statuses (constants.STATUSES),
        // gleiche Darstellung wie das Badge im Projekt-Kopf (project-head.js).
        var ps = (data.statuses || {})[p.status];
        // Automat überspringt pausierte/archivierte Boards still, auch wenn auto=true
        // (s. kanban-automat/automat_lib.py PAUSED_STATUSES) — Warnung, damit der User
        // merkt, dass hier trotz eingeschaltetem Bot nichts passiert.
        var statusBlocksAuto = !!p.auto && ['pausiert', 'archiviert'].includes(p.status);

        var row = document.createElement('div');
        row.className = 'list-row';
        row.style.setProperty('--cat-color', color);
        row.dataset.id = p.id;
        row.title = p.name || p.id;

        row.innerHTML =
            '<span class="list-prio" title="' + escHtml(EIS_TITLE[eisKey] || '') + '">' + EIS_EMOJI[eisKey] + '</span>' +
            '<span class="list-cat-chip" style="background:' + color + '22;color:' + color + '" title="' + escHtml(cat.label) + '">' + escHtml(icon) + '</span>' +
            '<span class="list-name">' + escHtml(p.name || p.id) + '</span>' +
            (ps
                ? '<span class="list-status" style="background:' + ps.color + '22;border:1px solid ' + ps.color +
                  ';color:' + ps.color + '" title="Projekt-Status: ' + escHtml(ps.label) + '">' +
                  ps.emoji + ' ' + escHtml(ps.label) + '</span>'
                : '<span class="list-status list-status-none" title="Projekt-Status: nicht gesetzt">–</span>') +
            (statusBlocksAuto
                ? '<span class="list-status-warn" title="Auto-Entwicklung ist an, aber Status \'' +
                  escHtml(ps ? ps.label : p.status) + '\' stoppt den Automaten still. Status zurücksetzen oder Auto ausschalten.">⚠️</span>'
                : '') +
            '<span class="list-counts">' +
                '<span class="badge-num badge-backlog" title="Backlog">' + c.backlog + '</span>' +
                '<span class="badge-num badge-in_progress" title="In Arbeit">' + c.in_progress + '</span>' +
                '<span class="badge-num badge-done" title="Erledigt">' + c.done + '</span>' +
            '</span>' +
            '<button type="button" class="eis-autobtn list-autobtn ' + st.cls + '" ' +
                'title="' + escHtml(st.label) + '  ·  Klick: ' + (p.auto ? 'ausschalten' : 'einschalten') + '">' + st.emoji + '</button>';

        row.querySelector('.list-autobtn').addEventListener('click', function (e) {
            e.stopPropagation();
            setAuto(p.id, !p.auto);
        });
        row.addEventListener('click', function () {
            console.log(TAG, 'Öffne Projekt (Liste):', p.id);
            window.location.href = '/project.html?id=' + encodeURIComponent(p.id);
        });
        return row;
    }

    // Gruppiert wie die Kategorie-Ansicht, aber Zeilen statt Kacheln + Sortierung nach Prio.
    function renderListMode(projects, area) {
        var buckets = {};
        projects.forEach(function (p) {
            var k = p.category || '_none';
            (buckets[k] = buckets[k] || []).push(p);
        });
        var order = [];
        Object.keys(data.categories || {}).forEach(function (c) { if (buckets[c]) order.push(c); });
        Object.keys(buckets).sort().forEach(function (c) { if (order.indexOf(c) === -1) order.push(c); });

        var sortFn = function (a, b) {
            var r = eisRank(a) - eisRank(b);
            if (r !== 0) return r;
            return (a.name || a.id).localeCompare(b.name || b.id, 'de');
        };

        order.forEach(function (catId) {
            var items = buckets[catId].slice().sort(sortFn);
            var ci = catInfo(catId);
            var section = document.createElement('section');
            section.className = 'group-section';
            var h = document.createElement('h2');
            h.className = 'group-heading';
            var label = (catId === '_none') ? '📁 Ohne Kategorie' : (ci.emoji + ' ' + ci.label);
            h.innerHTML = escHtml(label) + ' <span class="group-count">' + items.length + '</span>';
            section.appendChild(h);
            var list = document.createElement('div');
            list.className = 'list-table';
            items.forEach(function (p) { list.appendChild(renderListRow(p)); });
            section.appendChild(list);
            area.appendChild(section);
        });
        console.log(TAG, 'Liste-Render:', projects.length, 'Projekte in', order.length, 'Gruppen',
            '(Filter: Gruppe=' + (listFilterCat || 'alle') + ', Auto=' + (listFilterAuto || 'alle') +
            ', Projekt-Status=' + (listFilterStatus || 'alle') + ')');
    }

    function populateListFilters() {
        var catSel = document.getElementById('list-filter-cat');
        var autoSel = document.getElementById('list-filter-auto');
        var statSel = document.getElementById('list-filter-status');
        if (!catSel || !autoSel || !data) return;

        var usedCats = {};
        (data.projects || []).forEach(function (p) { usedCats[p.category || '_none'] = true; });
        var opts = '<option value="">📂 Alle Gruppen</option>';
        Object.keys(data.categories || {}).forEach(function (c) {
            if (!usedCats[c]) return;
            var ci = catInfo(c);
            opts += '<option value="' + c + '"' + (listFilterCat === c ? ' selected' : '') + '>' +
                escHtml(ci.emoji + ' ' + ci.label) + '</option>';
        });
        if (usedCats._none) {
            opts += '<option value="_none"' + (listFilterCat === '_none' ? ' selected' : '') + '>📁 Ohne Kategorie</option>';
        }
        catSel.innerHTML = opts;

        var autoOpts = '<option value="">🤖 Alle Status</option>';
        Object.keys(AUTO_STATE).forEach(function (k) {
            autoOpts += '<option value="' + k + '"' + (listFilterAuto === k ? ' selected' : '') + '>' +
                AUTO_STATE[k].emoji + ' ' + escHtml(AUTO_OPT_LABEL[k] || k) + '</option>';
        });
        autoSel.innerHTML = autoOpts;

        // Projekt-Status (Lebenszyklus, data.statuses = constants.STATUSES). Reihenfolge
        // kommt aus dem Backend (fachlich, nicht alphabetisch). Nur tatsächlich vergebene
        // Status stehen zur Wahl — ein Filter, der garantiert 0 Treffer liefert, hilft nicht.
        if (statSel) {
            var used = {};
            (data.projects || []).forEach(function (p) { used[p.status || '_none'] = true; });
            var statOpts = '<option value="">🏷 Alle Projekt-Status</option>';
            Object.keys(data.statuses || {}).forEach(function (k) {
                if (!used[k]) return;
                var s = data.statuses[k];
                statOpts += '<option value="' + k + '"' + (listFilterStatus === k ? ' selected' : '') + '>' +
                    s.emoji + ' ' + escHtml(s.label) + '</option>';
            });
            if (used._none) {
                statOpts += '<option value="_none"' + (listFilterStatus === '_none' ? ' selected' : '') +
                    '>– Ohne Status</option>';
            }
            statSel.innerHTML = statOpts;
        }
    }

    function refreshListFiltersUI() {
        var show = (groupMode === 'list' && !eisOn);
        ['list-filter-cat', 'list-filter-auto', 'list-filter-status'].forEach(function (id) {
            var el = document.getElementById(id);
            if (el) el.style.display = show ? '' : 'none';
        });
    }

    // ── Gruppierung ──────────────────────────────────────────────
    function statusOf(p) {
        var c = p.counts || {};
        if ((c.in_progress || 0) > 0) return 'in_progress';
        if ((c.backlog || 0) > 0) return 'backlog';
        if ((c.done || 0) > 0) return 'done';
        return 'empty';
    }

    function buildGroups(projects) {
        var byName = function (a, b) { return (a.name || a.id).localeCompare(b.name || b.id, 'de'); };

        if (groupMode === 'alpha') {
            return [{ title: '🔤 Alle Projekte (A–Z)', items: projects.slice().sort(byName) }];
        }

        if (groupMode === 'status') {
            var order = [
                { key: 'in_progress', title: '🔶 In Arbeit' },
                { key: 'backlog',     title: '🔵 Backlog' },
                { key: 'done',        title: '✅ Erledigt' },
                { key: 'empty',       title: '⚪ Leer' }
            ];
            return order.map(function (g) {
                return { title: g.title, items: projects.filter(function (p) { return statusOf(p) === g.key; }).sort(byName) };
            }).filter(function (g) { return g.items.length > 0; });
        }

        // default: Kategorie — Reihenfolge aus data.categories, Unbekanntes hinten
        var buckets = {};
        projects.forEach(function (p) {
            var k = p.category || '_none';
            (buckets[k] = buckets[k] || []).push(p);
        });
        var groups = [];
        Object.keys(data.categories || {}).forEach(function (catId) {
            if (buckets[catId]) {
                var ci = catInfo(catId);
                var items = arrangeMode ? applyStoredOrder(catId, buckets[catId]) : buckets[catId].slice().sort(byName);
                groups.push({ title: ci.emoji + ' ' + ci.label, catId: catId, items: items });
                delete buckets[catId];
            }
        });
        Object.keys(buckets).sort().forEach(function (k) {
            var items = arrangeMode ? applyStoredOrder(k, buckets[k]) : buckets[k].slice().sort(byName);
            groups.push({ title: '📁 ' + (k === '_none' ? 'Ohne Kategorie' : k), catId: k, items: items });
        });
        return groups;
    }

    // ── Render ───────────────────────────────────────────────────
    function applyFilter() {
        if (!data) return;
        // Führendes '#' entfernen: Tags sind ohne '#' gespeichert (#mqtt → mqtt).
        var search = (document.getElementById('project-search').value || '')
            .toLowerCase().trim().replace(/^#+\s*/, '');
        var projects = data.projects.filter(function (p) {
            // Ausgeblendet = NUR archiviert. 🗄-Toggle zeigt genau diese (zum
            // Aufräumen/Reaktivieren).
            // Bis 06.08.26 galt zusätzlich `p.status === 'pausiert'` als ausgeblendet —
            // pausierte Projekte waren also nur hinter dem 🗄-Knopf zu finden. Anforderung:
            // pausierte Projekte sollen in der Dashboard-Liste auch sichtbar sein.
            // Sie sind jetzt normal sichtbar und am ⏸️-Badge (.list-status) erkennbar;
            // genau dieses fehlende Erkennungsmerkmal war der ursprüngliche Grund fürs
            // Verstecken. Archiviert bleibt ausgeblendet (bewusstes „weg aus der Übersicht").
            var hidden = !!p.archived;
            if (showArchived) { if (!hidden) return false; }
            else if (hidden) { return false; }
            if (!search) return true;
            var tags = Array.isArray(p.tags) ? p.tags.join(' ') : '';
            var hay = ((p.name || '') + ' ' + (p.id || '') + ' ' + (p.description || '') + ' ' + tags)
                .toLowerCase();
            // Wort-Split (UND): jedes Suchwort muss irgendwo vorkommen — Reihenfolge
            // egal. Loest u.a. "github status" ↔ "github-status": der ganze String
            // mit Leerzeichen war nie Substring der Bindestrich-Schreibweise, ein
            // einzelner indexOf() lieferte 0 Treffer trotz passendem Projekt.
            return search.split(/\s+/).every(function (w) {
                return !w || hay.indexOf(w) !== -1;
            });
        });

        // Listenansicht: zusätzliche Gruppe-/Auto-Status-Filter (nur in diesem Modus sichtbar)
        if (groupMode === 'list' && !eisOn) {
            projects = projects.filter(function (p) {
                if (listFilterCat && (p.category || '_none') !== listFilterCat) return false;
                if (listFilterAuto && autoStateKey(p) !== listFilterAuto) return false;
                if (listFilterStatus && (p.status || '_none') !== listFilterStatus) return false;
                return true;
            });
        }
        refreshListFiltersUI();

        var area = document.getElementById('projects-area');
        area.innerHTML = '';

        // Server-Tag-Treffer, die NICHT als Board-Kachel im Payload sind (z.B. container-
        // Projekte ohne Board). Nur wenn die Server-Antwort zur aktuellen Eingabe passt.
        var known = {};
        data.projects.forEach(function (p) { known[p.id] = true; });
        var extraHits = (search && tagQuery === search)
            ? tagHits.filter(function (h) { return !known[h.id]; })
            : [];

        document.getElementById('count-label').textContent =
            projects.length + ' / ' + data.projects.length + ' Projekte' +
            (extraHits.length ? ' (+' + extraHits.length + ' im Index)' : '');

        // Persistenter KI-Suche-Knopf: nicht nur bei 0 Treffern anbieten, sondern
        // sobald ein Suchbegriff steht — Titel/Tag-Suche kann auch bei Treffern
        // am eigentlich Gesuchten vorbeigehen (Beispiel: Suche nach "Dokumentation"
        // liefert ein Ergebnis, aber nicht das gesuchte).
        var persistBtn = document.getElementById('ki-search-persist-btn');
        if (persistBtn) {
            persistBtn.style.display = search ? '' : 'none';
            persistBtn.onclick = function () { runKiSearch(search); };
        }

        if (projects.length === 0 && extraHits.length === 0) {
            // KI-Suche-Knopf nur anbieten, wenn tatsaechlich gesucht wurde — bei
            // leerem Feld ist "nichts gefunden" kein sinnvoller KI-Fall.
            var kiBtn = search
                ? '<div class="empty-ki">' +
                    '<button type="button" id="idx-btn-ki-search" class="empty-ki-btn">' +
                    escHtml(t('idx.kisuche.btn', '🤖 KI-Suche in Projekten')) + '</button>' +
                    '<div class="empty-ki-hint">' +
                    escHtml(t('idx.kisuche.hint', 'Textsuche erfolglos? Lass die KI passende Projekte finden.')) +
                    '</div></div>'
                : '';
            area.innerHTML = '<div class="empty-state"><div class="empty-icon">🔍</div>' +
                escHtml(t('idx.leer', 'Kein Projekt gefunden')) +
                (search ? ' für "<strong>' + escHtml(search) + '</strong>"' : '') + '.' +
                kiBtn + '</div>';
            if (search) {
                var b = document.getElementById('idx-btn-ki-search');
                if (b) b.addEventListener('click', function () { runKiSearch(search); });
            }
            return;
        }

        if (eisOn) {
            // Eisenhower-Modus: immer nach Kategorie ("Thema"), je eine Matrix
            if (projects.length) renderEisenhower(projects, area);
        } else if (groupMode === 'list') {
            if (projects.length) renderListMode(projects, area);
        } else {
            var groups = buildGroups(projects);
            groups.forEach(function (g) {
                var section = document.createElement('section');
                section.className = 'group-section';
                var h = document.createElement('h2');
                h.className = 'group-heading';
                h.innerHTML = escHtml(g.title) + ' <span class="group-count">' + g.items.length + '</span>';
                var grid = document.createElement('div');
                grid.className = 'projects-grid';
                g.items.forEach(function (p) { grid.appendChild(renderCard(p)); });
                section.appendChild(h);
                section.appendChild(grid);
                area.appendChild(section);
                // Arrange-Modus: DnD nur in Kategorie-Ansicht, nicht im Archiv
                if (arrangeMode && groupMode === 'category' && !showArchived && g.catId) {
                    initArrangeGrid(grid, g.catId);
                }
            });
        }
        refreshArrangeUI();

        if (extraHits.length) appendTagHits(area, extraHits, search);

        console.log(TAG, 'Render:', projects.length, 'Projekte, mode=' + groupMode +
            ', search="' + search + '", Tag-only-Treffer=' + extraHits.length);
    }

    // Eigene Sektion für Tag-Treffer aus dem Index, die KEIN Board haben (kein
    // /api/dashboard-Eintrag). Schlanke, klickbare Kachel: führt ins Projekt-Terminal
    // (projterm löst den Code-Ordner auch ohne Board auf).
    function appendTagHits(area, hits, search) {
        var section = document.createElement('section');
        section.className = 'group-section';
        var h = document.createElement('h2');
        h.className = 'group-heading';
        h.innerHTML = '🔎 Weitere Treffer im Index <span class="group-count">' + hits.length + '</span>' +
            '<span class="group-subnote"> — Projekte ohne eigenes Board</span>';
        var grid = document.createElement('div');
        grid.className = 'projects-grid';
        hits.forEach(function (hit) { grid.appendChild(renderTagHitCard(hit, search)); });
        section.appendChild(h);
        section.appendChild(grid);
        area.appendChild(section);
    }

    function renderTagHitCard(hit, search) {
        var card = document.createElement('div');
        card.className = 'project-card tag-hit-card';
        card.title = hit.id;
        var via = (hit.match_in || []);
        var viaBadge = via.map(function (m) {
            return '<span class="tag-hit-via tag-hit-via-' + m + '">' +
                (m === 'name' ? 'Name' : 'Tag') + '</span>';
        }).join('');
        var s = (search || '').toLowerCase();
        var tagsHtml = (hit.tags || []).map(function (t) {
            var hot = t.toLowerCase().indexOf(s) !== -1;
            return '<span class="tag-chip' + (hot ? ' tag-chip-hot' : '') + '">' + escHtml(t) + '</span>';
        }).join('');
        card.innerHTML =
            '<div class="card-title">🔎 ' + escHtml(hit.id) + ' ' + viaBadge + '</div>' +
            (tagsHtml ? '<div class="tag-hit-tags">' + tagsHtml + '</div>' : '') +
            (hit.path ? '<div class="card-activity">📁 ' + escHtml(hit.path) + '</div>' : '');
        card.addEventListener('click', function () {
            console.log(TAG, 'Öffne Tag-Treffer (kein Board):', hit.id);
            window.location.href = '/project.html?id=' + encodeURIComponent(hit.id);
        });
        return card;
    }

    // ── KI-Suche (Fallback) ──────────────────────────────────────
    // Nur aus dem Empty-State heraus (Text- + Tag-Suche haben nichts gefunden).
    // Schickt Query + kompakte Projektliste an das lokale Ollama (POST
    // /api/projects/ki-search) und rendert die semantisch passenden Projekte.
    var kiSearchBusy = false;

    function runKiSearch(query) {
        if (kiSearchBusy) return;
        kiSearchBusy = true;
        var area = document.getElementById('projects-area');
        area.innerHTML = '<div class="empty-state"><div class="empty-icon">🤖</div>' +
            escHtml(t('idx.kisuche.laeuft', '🤖 KI durchsucht deine Projekte …')) + '</div>';

        // Kompakte Records — nur, was das Modell zum Einordnen braucht.
        var payload = {
            query: query,
            projects: (data.projects || []).map(function (p) {
                return {
                    id: p.id,
                    name: p.name || p.id,
                    tags: Array.isArray(p.tags) ? p.tags : [],
                    desc: (p.description || '').slice(0, 160)
                };
            })
        };
        console.log(TAG, 'KI-Suche startet für "' + query + '" (' + payload.projects.length + ' Projekte)');

        window.API.post('/api/projects/ki-search', payload).then(function (res) {
            kiSearchBusy = false;
            // Nur anwenden, wenn das Suchfeld noch dieselbe Anfrage zeigt.
            var cur = (document.getElementById('project-search').value || '')
                .toLowerCase().trim().replace(/^#+\s*/, '');
            if (cur && cur !== query) {
                console.log(TAG, 'KI-Suche verworfen (Suchfeld geändert)');
                return;
            }
            renderKiResults(query, res || {});
        }).catch(function (err) {
            kiSearchBusy = false;
            console.error(TAG, 'KI-Suche fehlgeschlagen:', err.message);
            var a = document.getElementById('projects-area');
            a.innerHTML = '<div class="empty-state"><div class="empty-icon">⚠️</div>' +
                escHtml(t('idx.kisuche.fehler', 'KI-Suche fehlgeschlagen')) +
                ': ' + escHtml(err.message) + '</div>';
        });
    }

    function renderKiResults(query, res) {
        var area = document.getElementById('projects-area');
        area.innerHTML = '';
        var matches = (res && res.matches) || [];
        console.log(TAG, 'KI-Suche: ' + matches.length + ' Treffer, Modell=' + (res.model || '?'));

        if (!matches.length) {
            area.innerHTML = '<div class="empty-state"><div class="empty-icon">🤖</div>' +
                escHtml(t('idx.kisuche.keine', 'Auch die KI hat kein passendes Projekt gefunden.')) +
                (res.note ? ' <span class="empty-ki-note">(' + escHtml(res.note) + ')</span>' : '') +
                '</div>';
            return;
        }

        var byId = {};
        (data.projects || []).forEach(function (p) { byId[p.id] = p; });

        var section = document.createElement('section');
        section.className = 'group-section';
        var h = document.createElement('h2');
        h.className = 'group-heading';
        h.innerHTML = escHtml(t('idx.kisuche.titel', '🤖 KI-Vorschläge')) +
            ' <span class="group-count">' + matches.length + '</span>' +
            '<span class="group-subnote"> — für „' + escHtml(query) + '"' +
            (res.model ? ' · ' + escHtml(res.model) : '') + '</span>';
        var grid = document.createElement('div');
        grid.className = 'projects-grid';

        matches.forEach(function (m) {
            var p = byId[m.id];
            var card;
            if (p) {
                card = renderCard(p);        // volle Projektkachel wiederverwenden
            } else {
                // Sollte durch die Server-Validierung nie passieren — defensiv.
                card = document.createElement('div');
                card.className = 'project-card';
                card.innerHTML = '<div class="card-title">📁 ' + escHtml(m.name || m.id) + '</div>';
                card.addEventListener('click', function () {
                    window.location.href = '/project.html?id=' + encodeURIComponent(m.id);
                });
            }
            if (m.reason) {
                var r = document.createElement('div');
                r.className = 'card-ki-reason';
                r.textContent = '💡 ' + m.reason;
                card.appendChild(r);
            }
            grid.appendChild(card);
        });

        section.appendChild(h);
        section.appendChild(grid);
        area.appendChild(section);
    }

    // Server-Tag-Suche debounced anstossen; race-safe (nur die jüngste Antwort gilt).
    function runTagSearch(q) {
        // '#'-Präfix wegnormalisieren, gleich wie applyFilter — sonst passt
        // tagQuery !== search und die "+X im Index"-Sektion erscheint nicht.
        q = (q || '').toLowerCase().trim().replace(/^#+\s*/, '');
        if (q.length < 2) { tagHits = []; tagQuery = ''; applyFilter(); return; }
        window.API.searchByTag(q).then(function (res) {
            // Nur anwenden, wenn das Suchfeld noch denselben Wert hat (sonst veraltet).
            var cur = (document.getElementById('project-search').value || '')
                .toLowerCase().trim().replace(/^#+\s*/, '');
            if (cur !== q) return;
            tagHits = (res && res.results) || [];
            tagQuery = q;
            console.log(TAG, 'Tag-Suche "' + q + '": ' + tagHits.length + ' Index-Treffer');
            applyFilter();
        }).catch(function (e) {
            console.debug(TAG, 'Tag-Suche fehlgeschlagen:', e.message);
        });
    }

    function onSearchInput() {
        applyFilter();                       // Client-Filter sofort (kein Lag)
        clearTimeout(tagTimer);
        tagTimer = setTimeout(function () {
            runTagSearch(document.getElementById('project-search').value);
        }, 250);                             // Server-Suche debounced
    }

    function updateSubtitle() {
        var s = data.stats || {};
        var stand = data.generated_at ? ' · Stand ' + new Date(data.generated_at).toLocaleTimeString('de-CH') : '';
        document.getElementById('page-subtitle').textContent =
            (s.projects_total || 0) + ' Projekte · ' + (s.cards_total || 0) + ' Karten · ' +
            (s.containers_running || 0) + ' Container laufen' + stand;
        // Fusszone (nur auf index.html vorhanden) spiegelt die Kernzahlen
        var foot = document.getElementById('footer-count');
        if (foot) foot.textContent =
            (s.projects_total || 0) + ' Projekte · ' + (s.cards_total || 0) + ' Karten' + stand;
    }

    // ── Init ─────────────────────────────────────────────────────
    async function init() {
        console.log(TAG, 'init() — lade /api/dashboard …');
        applyZoom();

        // Gruppier-Buttons
        document.querySelectorAll('.group-btn').forEach(function (btn) {
            if (btn.dataset.group === groupMode) btn.classList.add('active');
            else btn.classList.remove('active');
            btn.addEventListener('click', function () {
                if (!btn.dataset.group) return;   // Toggles (🎯/🤖/🗄) haben kein data-group → eigener Handler
                groupMode = btn.dataset.group;
                localStorage.setItem('idx_group', groupMode);
                document.querySelectorAll('.group-btn[data-group]').forEach(function (b) { b.classList.toggle('active', b === btn); });
                console.log(TAG, 'Gruppierung:', groupMode);
                applyFilter();
            });
        });

        // Eisenhower-Toggle
        var eisBtn = document.getElementById('eisenhower-toggle');
        if (eisBtn) {
            eisBtn.classList.toggle('active', eisOn);
            eisBtn.addEventListener('click', function () {
                eisOn = !eisOn;
                localStorage.setItem('idx_eisenhower', eisOn ? '1' : '0');
                eisBtn.classList.toggle('active', eisOn);
                document.body.classList.toggle('eis-mode', eisOn);
                console.log(TAG, 'Eisenhower-Modus:', eisOn);
                applyFilter();
            });
            document.body.classList.toggle('eis-mode', eisOn);
        }

        // Archiv-Toggle: zeigt NUR archivierte Projekte (zum Aufräumen/Entarchivieren)
        var arcBtn = document.getElementById('archive-toggle');
        if (arcBtn) {
            arcBtn.addEventListener('click', function () {
                showArchived = !showArchived;
                arcBtn.classList.toggle('active', showArchived);
                console.log(TAG, 'Archiv-Ansicht:', showArchived);
                applyFilter();
            });
        }

        // KI-Prio: ordnet noch NICHT einsortierte Projekte (leeres `eisenhower`) per Ollama
        // in die Quadranten q1..q4. Vom User gesetzte Quadranten bleiben unangetastet.
        var kiBtn = document.getElementById('ki-prio-btn');
        if (kiBtn) {
            kiBtn.addEventListener('click', async function () {
                if (!data || !data.projects) return;
                var empty = data.projects.filter(function (p) { return !(p.eisenhower || ''); });
                if (!empty.length) {
                    showError('Alle Projekte sind bereits einsortiert — KI hat nichts zu tun.');
                    return;
                }
                var items = empty.map(function (p) {
                    return { id: p.id, name: p.name || p.id, category: p.category || '',
                             desc: (p.description || '').slice(0, 160) };
                });
                kiBtn.disabled = true;
                var label = kiBtn.textContent;
                kiBtn.textContent = '🤖 …';
                console.log(TAG, 'KI-Prio: ' + items.length + ' Projekte ohne Quadrant → Ollama');
                try {
                    var res = await window.API.post('/eisenhower-suggest', { items: items, ai: true });
                    var sugg = (res && res.suggestions) || [];
                    var patches = [];
                    sugg.forEach(function (s) {
                        if (['q1', 'q2', 'q3', 'q4'].indexOf(s.quadrant) < 0) return;
                        var p = data.projects.find(function (x) { return x.id === s.id; });
                        if (!p || (p.eisenhower || '')) return;   // nie überschreiben
                        p.eisenhower = s.quadrant;                 // optimistisch
                        patches.push(window.API.patchBoard(p.id, { eisenhower: s.quadrant }));
                    });
                    await Promise.allSettled(patches);
                    console.log(TAG, 'KI-Prio: ' + patches.length + ' Projekte eingestuft (ai=' + (res && res.ai) + ')');
                    if (!patches.length) showError('KI lieferte keine Einstufung (Ollama erreichbar?).');
                    // In den Priorisieren-Modus schalten, damit man das Ergebnis sieht
                    if (!eisOn) {
                        eisOn = true;
                        localStorage.setItem('idx_eisenhower', '1');
                        var et = document.getElementById('eisenhower-toggle');
                        if (et) et.classList.add('active');
                        document.body.classList.add('eis-mode');
                    }
                    applyFilter();
                } catch (e) {
                    console.error(TAG, 'KI-Prio fehlgeschlagen:', e);
                    showError('KI-Prio fehlgeschlagen: ' + e.message);
                } finally {
                    kiBtn.disabled = false;
                    kiBtn.textContent = label;
                }
            });
        }

        document.getElementById('project-search').addEventListener('input', onSearchInput);
        document.getElementById('zoom-in').addEventListener('click', function () { changeZoom(+1); });
        document.getElementById('zoom-out').addEventListener('click', function () { changeZoom(-1); });

        // Listenansicht: Gruppe-/Auto-Status-Filter
        var listCatSel = document.getElementById('list-filter-cat');
        var listAutoSel = document.getElementById('list-filter-auto');
        if (listCatSel) {
            listCatSel.addEventListener('change', function () {
                listFilterCat = listCatSel.value;
                localStorage.setItem('idx_list_cat', listFilterCat);
                console.log(TAG, 'Liste-Filter Gruppe:', listFilterCat || '(alle)');
                applyFilter();
            });
        }
        if (listAutoSel) {
            listAutoSel.addEventListener('change', function () {
                listFilterAuto = listAutoSel.value;
                localStorage.setItem('idx_list_auto', listFilterAuto);
                console.log(TAG, 'Liste-Filter Auto-Status:', listFilterAuto || '(alle)');
                applyFilter();
            });
        }
        var listStatSel = document.getElementById('list-filter-status');
        if (listStatSel) {
            listStatSel.addEventListener('change', function () {
                listFilterStatus = listStatSel.value;
                localStorage.setItem('idx_list_status', listFilterStatus);
                console.log(TAG, 'Liste-Filter Projekt-Status:', listFilterStatus || '(alle)');
                applyFilter();
            });
        }

        // Arrange-Toggle: Drag-and-Drop Reihenfolge der Projektkacheln
        var arrBtn = document.getElementById('arrange-toggle');
        var rstBtn = document.getElementById('arrange-reset');
        if (arrBtn) {
            arrBtn.addEventListener('click', function() {
                arrangeMode = !arrangeMode;
                localStorage.setItem('idx_arrange', arrangeMode ? '1' : '0');
                // Bei Aktivierung auto-switch zur Kategorie-Ansicht (deaktiviert EIS/Archiv)
                if (arrangeMode && (groupMode !== 'category' || eisOn || showArchived)) {
                    if (eisOn) {
                        eisOn = false;
                        localStorage.setItem('idx_eisenhower', '0');
                        var et = document.getElementById('eisenhower-toggle');
                        if (et) et.classList.remove('active');
                        document.body.classList.remove('eis-mode');
                    }
                    if (showArchived) {
                        showArchived = false;
                        var at = document.getElementById('archive-toggle');
                        if (at) at.classList.remove('active');
                    }
                    if (groupMode !== 'category') {
                        groupMode = 'category';
                        localStorage.setItem('idx_group', 'category');
                        document.querySelectorAll('.group-btn[data-group]').forEach(function(b) {
                            b.classList.toggle('active', b.dataset.group === 'category');
                        });
                    }
                }
                console.log(TAG, 'Arrange-Modus:', arrangeMode);
                applyFilter();
            });
        }
        if (rstBtn) {
            rstBtn.addEventListener('click', function() {
                if (!confirm('Benutzerdefinierte Reihenfolge zurücksetzen?\nAlle Kacheln werden wieder alphabetisch sortiert.')) return;
                customOrder = {};
                try { localStorage.removeItem('idx_order'); } catch(e) {}
                console.log(TAG, 'Reihenfolge zurückgesetzt');
                applyFilter();
            });
        }

        try {
            data = await window.API.get('/api/dashboard');
        } catch (err) {
            showError('Dashboard konnte nicht geladen werden: ' + err.message);
            document.getElementById('projects-area').innerHTML = '';
            return;
        }
        console.log(TAG, 'Daten geladen:', (data.projects || []).length, 'Projekte,',
            (data.containers && data.containers.running || []).length, 'Container, stats=', data.stats);

        // Offene Automat-Entscheidungen board-weise sammeln (für Status „Entscheidung
        // nötig"). Nicht kritisch — bei Fehler bleibt der Schalter bei aus/an/erledigt.
        try {
            var dec = await window.API.get('/api/automat/decisions');
            autoDecisions = {};
            (dec && dec.decisions || []).forEach(function (d) { if (d.board) autoDecisions[d.board] = true; });
            console.log(TAG, 'Offene Automat-Entscheidungen:', Object.keys(autoDecisions).length, 'Board(s)');
        } catch (e) {
            console.debug(TAG, 'Automat-Entscheidungen nicht ladbar (nicht kritisch):', e.message);
        }

        updateSubtitle();
        populateListFilters();
        applyFilter();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
