// lang.js — zentraler Sprachumschalter fuer ALLE Dashboard-Seiten.
// Eingebunden via nav.js (dynamisch), analog zu theme.js/darstellung.js.
//
// Sprachdateien: /i18n/<lang>.js (window.I18N = {...}), generiert aus
// ili-sprachen-gpeykj/LOCALES_GLOSSARY.json. de.js ist die statisch im HTML
// verdrahtete Default-Quelle (<script src="/i18n/de.js" defer></script> in
// jeder Seite) — sie wird NIE dynamisch nachgeladen oder ueberschrieben.
//
// Umschalten laedt die Zielsprache, cacht das Woerterbuch in localStorage
// ("ds_lang_dict") und laedt die Seite danach neu: ui-kit/v1/i18n.js
// uebernimmt den Cache dann SYNCHRON, noch bevor nav.js (naechstes
// <script defer>) die Nav baut (siehe Kommentar dort) — ohne den Reload
// bliebe die zur Bauzeit bereits gerenderte Nav in der alten Sprache.
// Wahl wird in localStorage "ds_lang" gespeichert (gilt pro Browser ueberall).
(function () {
    'use strict';
    const KEY = 'ds_lang';
    const DICT_KEY = 'ds_lang_dict';
    const LANGS = [
        ['de', 'Deutsch'],
        ['en', 'English'],
        ['es', 'Español'],
    ];
    const log = (...a) => console.debug('[lang]', ...a);

    function currentLang() {
        try {
            const l = localStorage.getItem(KEY);
            return LANGS.some(([id]) => id === l) ? l : 'de';
        } catch (e) { return 'de'; }
    }

    // Laedt /i18n/<lang>.js (setzt window.I18N komplett neu) und ruft cb() bei
    // Erfolg auf. Fehler -> cb wird NICHT aufgerufen, Seite bleibt unveraendert.
    function loadDict(lang, cb) {
        const s = document.createElement('script');
        s.src = '/i18n/' + lang + '.js?v=' + Date.now();
        s.onload = function () { log('Woerterbuch geladen:', lang); cb(); };
        s.onerror = function () { console.warn('[lang] Sprachdatei nicht ladbar:', lang); };
        document.head.appendChild(s);
    }

    // Nutzerwahl umsetzen: cachen + Seite neu laden, damit die Nav (baut sich
    // aus window.I18N noch VOR lang.js) gleich in der Zielsprache entsteht.
    function setLanguage(lang) {
        if (lang === 'de') {
            try { localStorage.removeItem(KEY); localStorage.removeItem(DICT_KEY); } catch (e) { /* Safari private */ }
            log('zurueck auf Deutsch (statische Quelle)');
            location.reload();
            return;
        }
        loadDict(lang, function () {
            try {
                localStorage.setItem(DICT_KEY, JSON.stringify(window.I18N));
                localStorage.setItem(KEY, lang);
            } catch (e) { console.warn('[lang] localStorage nicht verfuegbar, Wahl gilt nur fuer diese Seite:', e); }
            location.reload();
        });
    }

    // Cache im Hintergrund auffrischen (neue/geaenderte Uebersetzungen seit dem
    // letzten Besuch), OHNE Reload. Bereits gerenderte data-i18n-Elemente werden
    // sofort neu gesetzt; die von nav.js zur Bauzeit eingebrannten Nav-Labels
    // ziehen erst beim naechsten Seitenaufruf nach (Nav ist nicht neu aufbaubar).
    function refreshCache(lang) {
        loadDict(lang, function () {
            try { localStorage.setItem(DICT_KEY, JSON.stringify(window.I18N)); } catch (e) { /* noop */ }
            if (window.I18n) window.I18n.apply();
        });
    }

    function makeSelect() {
        const sel = document.createElement('select');
        sel.id = 'nav-lang-select';
        sel.className = 'ds-lang-select';
        sel.title = (window.I18N && window.I18N['nav.lang.title']) || 'Sprache wechseln';
        sel.setAttribute('aria-label', 'Sprache wechseln');
        LANGS.forEach(([id, label]) => {
            const opt = document.createElement('option');
            opt.value = id;
            opt.textContent = label;
            sel.appendChild(opt);
        });
        sel.value = currentLang();
        sel.onchange = function () { setLanguage(sel.value); };
        return sel;
    }

    const LANG_CSS = `
    .ds-lang-select{background:var(--t-surface2,#1a1d27);color:var(--t-text,#e2e8f0);
        border:1px solid var(--t-raised,#2a2d3e);border-radius:6px;padding:.28rem .4rem;
        font:inherit;font-size:.8rem;cursor:pointer;margin-left:.2rem}
    .ds-lang-select:hover{border-color:#4a5568}
    `;

    function mountSelect() {
        if (document.querySelector('.ds-lang-select')) return;
        const st = document.createElement('style');
        st.textContent = LANG_CSS;
        document.head.appendChild(st);
        const nav = document.querySelector('.ds-nav');           // Desktop-Nav (nav.js)
        const mob = document.querySelector('.topbar-actions');   // Mobile /m/ (falls vorhanden)
        if (nav) nav.appendChild(makeSelect());
        else if (mob) mob.insertBefore(makeSelect(), mob.firstChild);
        else document.body.appendChild(makeSelect());
        log('Umschalter montiert, aktuelle Sprache:', currentLang());
    }

    document.documentElement.lang = currentLang();

    function init() {
        // nav.js injiziert die Leiste ebenfalls erst nach DOMContentLoaded -> kurz warten
        let tries = 0;
        (function waitNav() {
            if (document.querySelector('.ds-nav') || tries++ > 10) mountSelect();
            else setTimeout(waitNav, 100);
        })();
        const lang = currentLang();
        if (lang !== 'de') refreshCache(lang);
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();

    window.dsLang = { setLanguage, current: currentLang };
})();
