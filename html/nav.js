// Zentrales Nav-Menü für alle Dashboard-Seiten (Port 80).
// Wird per <script src="/nav.js" defer></script> in jede Seite eingebunden.
// Aenderungen an Menue-Eintraegen NUR hier — einmal anpassen, ueberall aktiv.
(function () {
    'use strict';

    // Alle Nav-Ziele sind same-origin. Frueher wurde hier eine Basis-Domain aus
    // location.hostname abgeleitet, um auf Nachbar-Sub-Domains zu verlinken; auf
    // einer Installation ohne Punkt im Hostnamen (localhost) ergab das tote Links.

    // Texte kommen aus der Sprachdatei (/i18n/de.js) ueber den UI-Kit-Helfer.
    // Beides ist optional: fehlt es, greift der hier stehende Fallback-Text —
    // die Nav darf NIE davon abhaengen, dass ui.intranet erreichbar war.
    function t(key, fallback) {
        if (window.I18n && window.I18n.t) return window.I18n.t(key, fallback);
        const d = window.I18N || {};
        return Object.prototype.hasOwnProperty.call(d, key) ? d[key] : fallback;
    }

    // Beschriftung des Overflow-Knopfs. Zwei Zustaende: breit "⋯ Mehr",
    // schmal/Portrait "☰ Menü" (dann steckt das ganze Menue im Panel).
    function MORE_LABEL(narrow) {
        const txt = narrow ? '☰ ' + t('nav.menu', 'Menü') : '⋯ ' + t('nav.more', 'Mehr');
        return txt + ' <span class="ds-nav__caret">▾</span>';
    }

    // `id` = eindeutige, stabile Kennung pro Bedienelement (Konvention
    // <bereich>-<art>-<funktion>), damit man einen Knopf benennen kann, ohne
    // XPath zu zaehlen. `key` = Schluessel in der Sprachdatei, `label` = Fallback.
    const NAV_ITEMS = [
        // Ganz links + mit Zaehler-Badge: offene Fragen sollen sofort auffallen.
        { id: 'nav-link-fragen',   href: '/fragen.html',       icon: '❓', key: 'nav.fragen',   label: 'Offene Fragen', badge: 'fragen' },
        { id: 'nav-link-projekte', href: '/',                  icon: '📁', key: 'nav.projekte', label: 'Projekte' },
        { id: 'nav-link-aufgaben', href: '/project.html?id=meine-aufgaben', icon: '✅', key: 'nav.aufgaben', label: 'Meine Aufgaben' },
        { id: 'nav-link-recent',   href: '/recent.html',       icon: '🕒', key: 'nav.recent',   label: 'Zuletzt aktiv' },
        { id: 'nav-link-created',  href: '/created.html',      icon: '📅', key: 'nav.created',  label: 'Nach Erstelldatum' },
        { id: 'nav-link-leichen',  href: '/leichen.html',      icon: '💀', key: 'nav.leichen',  label: 'Leichen' },
        { id: 'nav-link-github',   href: '/github-status.html', icon: '🐙', key: 'nav.github',  label: 'GitHub-Status' },
        { id: 'nav-link-autodev',  href: '/autodev.html',      icon: '🤖', key: 'nav.autodev',  label: 'Auto-Entwicklung' },
        { id: 'nav-link-quick',    href: '/quick.html',        icon: '⚡', key: 'nav.quick',    label: 'Schnellstart' },
        { id: 'nav-link-bugs',     href: '/bugs.html',         icon: '🐞', key: 'nav.bugs',     label: 'Bugs' },
        { id: 'nav-link-terminal', href: '/projterm/',         icon: '💻', key: 'nav.terminal', label: 'Terminal', external: true },
        { id: 'nav-link-cost',     href: '/cost.html',         icon: '💰', key: 'nav.cost',     label: 'Kosten' },
        { id: 'nav-link-tokenguard', href: '/token-spikes.html', icon: '📈', key: 'nav.tokenguard', label: 'Token-Wächter' },
        { id: 'nav-link-datenbanken', href: '/datenbanken.html', icon: '🗄️', key: 'nav.datenbanken', label: 'Datenbanken' },
        { id: 'nav-link-neuesprojekt', href: '/projekt.html',  icon: '➕', key: 'nav.neuesprojekt', label: 'Neues Projekt' },
        { id: 'nav-link-kiadvisor', href: '/ki-advisor.html',  icon: '🤖', key: 'nav.kiadvisor', label: 'KI-Advisor' },
        { id: 'nav-link-kisettings', href: '/ai-settings.html', icon: '⚙️', key: 'nav.kisettings', label: 'KI-Settings' },
        { id: 'nav-link-whitelist', href: '/whitelist.html',   icon: '🔐', key: 'nav.whitelist', label: 'Whitelist' },
        { id: 'nav-link-swipe',    href: '/swipe.html',        icon: '👆', key: 'nav.swipe',    label: 'Swipe' },
        { id: 'nav-link-flow',     href: '/masterchat-flow.html',   icon: '🔀', key: 'nav.flow',      label: 'Flow' },
        { id: 'nav-link-container', href: '/container-manager.html', icon: '📦', key: 'nav.container', label: 'Container' },
        { id: 'nav-link-wiki',      href: '/wiki.html',        icon: '📚', key: 'nav.wiki',      label: 'Code-Wiki' },
        { id: 'nav-link-ollamaqueue', href: '/ollama-queue.html', icon: '🦙', key: 'nav.ollamaqueue', label: 'Ollama-Queue' },
    ];

    const NAV_CSS = `
    .ds-nav{position:sticky;top:0;z-index:1000;background:#0b0d13;
            border-bottom:1px solid #2a2d3e;display:flex;align-items:center;
            flex-wrap:nowrap;gap:.2rem;padding:.3rem .6rem;
            overflow-x:clip;overflow-y:visible;
            font:500 .82rem system-ui,-apple-system,sans-serif}
    .ds-nav__brand,.ds-nav__a,.ds-nav__more{flex:0 0 auto}
    .ds-nav__brand{font-weight:700;color:#e2e8f0;margin-right:.35rem;
                   white-space:nowrap;text-decoration:none;font-size:.9rem;
                   padding:.3rem .5rem;border-radius:6px;
                   display:inline-flex;align-items:center;gap:.3rem}
    .ds-nav__logo{height:1.15rem;width:1.15rem;display:block}
    .ds-nav__brand:hover{background:#1a1d27}
    .ds-nav__a{color:#8892a4;text-decoration:none;padding:.32rem .5rem;
               border-radius:6px;white-space:nowrap;display:inline-flex;
               align-items:center;gap:.25rem;
               transition:background .12s,color .12s}
    .ds-nav__a:hover{color:var(--t-text,#e2e8f0);background:var(--t-surface2,#1a1d27)}
    .ds-nav__a.is-active{color:#fff;background:var(--accent,#4a9eff)}
    /* Zaehler-Badge (offene Fragen) — nur sichtbar wenn > 0 (Klasse .on) */
    .ds-nav__badge{display:none;min-width:1.15rem;padding:0 .32rem;border-radius:999px;
                   background:#ef4444;color:#fff;font:700 .7rem/1.15rem system-ui,sans-serif;
                   text-align:center}
    .ds-nav__badge.on{display:inline-block}
    .ds-nav__a.has-badge{color:var(--t-text,#e2e8f0)}
    .ds-nav__mobile-toggle{background:var(--t-surface2,#1a1d27);border:1px solid var(--t-raised,#2a2d3e)}
    /* Overflow-Dropdown ("Mehr") */
    .ds-nav__more{position:relative;margin-right:.2rem}
    .ds-nav__morebtn{color:var(--t-muted,#8892a4);background:var(--t-surface2,#1a1d27);border:1px solid var(--t-raised,#2a2d3e);
                     cursor:pointer;padding:.32rem .55rem;border-radius:6px;
                     white-space:nowrap;font:inherit;display:inline-flex;
                     align-items:center;gap:.25rem;transition:background .12s,color .12s}
    .ds-nav__morebtn:hover,.ds-nav__morebtn[aria-expanded="true"]{color:var(--t-text,#e2e8f0);background:var(--t-raised,#242838)}
    .ds-nav__morebtn.has-active{color:#fff;background:var(--accent,#4a9eff);border-color:var(--accent,#4a9eff)}
    .ds-nav__caret{font-size:.7rem;transition:transform .15s}
    .ds-nav__morebtn[aria-expanded="true"] .ds-nav__caret{transform:rotate(180deg)}
    /* position:fixed (nicht absolute!) — entkommt dem overflow-Container der Nav.
       Safari/WebKit clippt ein absolutes Panel im overflow-x:clip-Container weg
       ("oeffnet kurz, verschwindet"). top/left setzt JS (positionPanel). */
    .ds-nav__panel{position:fixed;top:0;left:0;background:var(--t-surface,#0b0d13);
                   border:1px solid var(--t-raised,#2a2d3e);border-radius:8px;padding:.3rem;
                   display:none;flex-direction:column;gap:.1rem;min-width:190px;
                   max-height:75vh;overflow-y:auto;
                   box-shadow:0 10px 28px rgba(0,0,0,.45);z-index:1001}
    .ds-nav__panel.open{display:flex}
    .ds-nav__panel .ds-nav__a{width:100%}
    @media (max-width:600px){
        .ds-nav{padding:.3rem .45rem}
        .ds-nav__brand{font-size:.82rem;padding:.28rem .4rem}
        .ds-nav__a,.ds-nav__morebtn{padding:.3rem .45rem;font-size:.8rem}
    }
    /* Schmal/Portrait (JS setzt .ds-nav--narrow nach gemessener Breite): ALLE Menue-
       punkte in EIN vollbreites, FIXIERTES Panel. position:fixed entkommt dem
       overflow-Container der Nav — das war auf iOS die Bugquelle (absolute-Panel in
       overflow:clip liess sich nicht zuverlaessig oeffnen). */
    .ds-nav--narrow .ds-nav__more{margin-right:0;margin-left:auto}
    .ds-nav--narrow .ds-nav__panel{
        position:fixed; left:0; right:0; top:var(--ds-nav-h,48px);
        min-width:0; width:auto; border-radius:0 0 10px 10px;
        border-top:none; padding:.4rem;
        max-height:calc(100vh - var(--ds-nav-h,48px) - 8px);
    }
    .ds-nav--narrow .ds-nav__panel .ds-nav__a{padding:.6rem .7rem;font-size:.92rem}
    `;

    function currentPath() {
        const p = (window.location.pathname || '/').replace(/\/+$/, '');
        return p === '' ? '/' : p;
    }

    function isActive(href, path) {
        if (href === '/') return path === '/' || path === '/index.html';
        return path === href;
    }

    function buildNav() {
        const path  = currentPath();
        const style = document.createElement('style');
        style.textContent = NAV_CSS;
        document.head.appendChild(style);

        // ili monogram as favicon on every page that loads the nav
        if (!document.querySelector('link[rel~="icon"]')) {
            const fav = document.createElement('link');
            fav.rel  = 'icon';
            fav.type = 'image/png';
            fav.href = '/img/favicon-64.png';
            document.head.appendChild(fav);
        }
        // iOS home-screen icon (Add to Home Screen ignores the favicon)
        if (!document.querySelector('link[rel="apple-touch-icon"]')) {
            const touch = document.createElement('link');
            touch.rel  = 'apple-touch-icon';
            touch.href = '/apple-touch-icon.png';
            document.head.appendChild(touch);
        }

        const nav = document.createElement('nav');
        nav.id = 'ds-nav';
        nav.className = 'ds-nav';
        nav.setAttribute('role', 'navigation');
        nav.setAttribute('aria-label', t('nav.aria', 'Dashboard Navigation'));

        const brand = document.createElement('a');
        brand.id          = 'nav-link-brand';
        brand.className   = 'ds-nav__brand';
        brand.href        = '/';
        brand.title       = t('app.brand.full', 'intelligent life interface');
        // Inline the monogram SVG with fill=currentColor so it follows the
        // brand text color in every theme (nav can be light or dark).
        const brandLogo = document.createElement('span');
        brandLogo.className = 'ds-nav__logo';
        brand.appendChild(brandLogo);
        fetch('/img/ili-logo.svg')
            .then(r => r.ok ? r.text() : Promise.reject(new Error('HTTP ' + r.status)))
            .then(txt => {
                brandLogo.innerHTML = txt
                    .replace(/^[\s\S]*?<svg/, '<svg')
                    .replace(/fill="#[0-9a-fA-F]{3,6}"/g, 'fill="currentColor"');
                const svg = brandLogo.querySelector('svg');
                if (svg) {
                    if (!svg.getAttribute('viewBox')) {
                        svg.setAttribute('viewBox', '0 0 ' + (svg.getAttribute('width') || 1024) + ' ' + (svg.getAttribute('height') || 1024));
                    }
                    svg.removeAttribute('width');
                    svg.removeAttribute('height');
                }
            })
            .catch(e => console.warn('[nav.js] logo load failed', e));
        brand.appendChild(document.createTextNode(t('app.brand', 'ili')));
        nav.appendChild(brand);

        // Manueller Umschalter zur mobilen Ansicht — Auto-Erkennung per User-Agent
        // erkennt nicht jedes Geraet zuverlaessig, daher immer sichtbarer Fallback.
        const mobileToggle = document.createElement('a');
        mobileToggle.id          = 'nav-link-mobil';
        mobileToggle.className   = 'ds-nav__a ds-nav__mobile-toggle';
        mobileToggle.href        = '/m/';
        mobileToggle.title       = t('nav.mobil.title', 'Zur mobilen Ansicht wechseln');
        mobileToggle.textContent = '📱 ' + t('nav.mobil', 'Mobil');
        mobileToggle.addEventListener('click', function () {
            try { localStorage.removeItem('force_desktop'); } catch (e) { console.warn('[nav.js] localStorage nicht verfuegbar', e); }
        });
        nav.appendChild(mobileToggle);

        const itemEls = [];
        const badgeEls = {};   // badge-Name -> <span>, wird per Zaehler-Abfrage gefuellt
        let lastCount = 0;     // letzter Fragen-Zaehler (fuer die Spiegelung auf "Mehr"/"Menü")
        for (const it of NAV_ITEMS) {
            const a = document.createElement('a');
            a.id          = it.id;
            a.className   = 'ds-nav__a' + (isActive(it.href, path) ? ' is-active' : '');
            a.href        = it.href;
            a.textContent = `${it.icon} ${t(it.key, it.label)}`;
            if (it.badge) {
                const b = document.createElement('span');
                b.className = 'ds-nav__badge';
                a.appendChild(b);
                badgeEls[it.badge] = b;
            }
            if (it.external) { a.target = '_blank'; a.rel = 'noopener'; }
            nav.appendChild(a);
            itemEls.push(a);
        }

        // "Mehr"-Dropdown fuer alle Eintraege, die nicht in eine Zeile passen
        const more = document.createElement('div');
        more.id = 'nav-more';
        more.className = 'ds-nav__more';
        const moreBtn = document.createElement('button');
        moreBtn.id = 'nav-btn-more';
        moreBtn.type = 'button';
        moreBtn.className = 'ds-nav__morebtn';
        moreBtn.setAttribute('aria-expanded', 'false');
        moreBtn.setAttribute('aria-label', t('nav.more.aria', 'Weitere Menuepunkte'));
        moreBtn.innerHTML = MORE_LABEL();
        const panel = document.createElement('div');
        panel.id = 'nav-more-panel';
        panel.className = 'ds-nav__panel';
        more.appendChild(moreBtn);
        more.appendChild(panel);
        // "Mehr" links platzieren: direkt nach Brand/Mobil, vor den Menuepunkten
        nav.insertBefore(more, itemEls[0] || null);

        function closePanel() {
            panel.classList.remove('open');
            moreBtn.setAttribute('aria-expanded', 'false');
        }
        moreBtn.addEventListener('click', function (e) {
            e.stopPropagation();
            const open = panel.classList.toggle('open');
            if (open) positionPanel();   // top/left aktuell setzen (Desktop + Portrait)
            moreBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
        });
        document.addEventListener('click', function (e) {
            if (!more.contains(e.target)) closePanel();
        });

        // Overflow-Verteilung: sichtbare Items fuellen eine Zeile, Rest wandert
        // ins Dropdown. Das aktive Item bleibt immer sichtbar. Neu bei jedem Resize.
        const NARROW_BP = 600;   // darunter: Portrait-Modus (vollbreites Menue-Panel)
        let lastW = -1;          // zuletzt vermessene Nav-Breite (Hoehen-Resizes ignorieren)
        // Nav-Hoehe als CSS-Variable — das fixe Portrait-Panel setzt darauf sein top.
        function setNavH() { nav.style.setProperty('--ds-nav-h', nav.offsetHeight + 'px'); }
        // Panel positionieren. Beide Modi nutzen position:fixed (entkommt overflow-Container).
        function positionPanel() {
            setNavH();
            if (nav.classList.contains('ds-nav--narrow')) {
                // Portrait: volle Breite via CSS-Klasse — Inline-Styles wegraeumen, damit
                // .ds-nav--narrow .ds-nav__panel (left:0;right:0;top:var(--ds-nav-h)) greift.
                panel.style.top = ''; panel.style.left = ''; panel.style.right = '';
                return;
            }
            // Desktop: fixiert direkt unter dem "Mehr"-Knopf.
            const nr = nav.getBoundingClientRect();
            const br = moreBtn.getBoundingClientRect();
            panel.style.top   = Math.round(nr.bottom + 5) + 'px';
            panel.style.left  = Math.round(br.left) + 'px';
            panel.style.right = 'auto';
        }
        // Steckt "Offene Fragen" im Dropdown (Portrait: immer), waere die Zahl unsichtbar —
        // darum das Badge auf den "Mehr"/"☰ Menü"-Knopf spiegeln. relayout() setzt dessen
        // innerHTML neu, deshalb IMMER nach relayout aufrufen.
        function syncMoreBadge() {
            const src = badgeEls.fragen;
            if (!src) return;
            let mirror = moreBtn.querySelector('.ds-nav__badge');
            const needed = lastCount > 0 && panel.contains(src.parentElement);
            if (!needed) { if (mirror) mirror.remove(); return; }
            if (!mirror) {
                mirror = document.createElement('span');
                mirror.className = 'ds-nav__badge on';
                moreBtn.appendChild(mirror);
            }
            mirror.textContent = src.textContent;
        }

        function relayout() { relayoutCore(); syncMoreBadge(); }

        function relayoutCore() {
            const wasOpen = panel.classList.contains('open');   // Offen-Zustand merken
            // Ausgangszustand: alle Items zurueck in die Leiste (rechts von "more",
            // das links steht) — appendChild verschiebt auch bereits vorhandene Items
            // ans Ende, so bleibt die Reihenfolge deterministisch.
            for (const el of itemEls) { nav.appendChild(el); }
            panel.innerHTML = '';
            moreBtn.classList.remove('has-active');
            more.style.display = 'none';   // erst ohne "Mehr"-Knopf messen

            // ── Portrait/schmal: ALLE Items ins vollbreite, fixierte Panel ──────────
            // Kein Messen, kein absolute-Dropdown — umgeht den iOS-Panel-Bug.
            if (nav.clientWidth < NARROW_BP) {
                nav.classList.add('ds-nav--narrow');
                more.style.display = '';
                moreBtn.innerHTML = MORE_LABEL(true);
                if (itemEls.some(el => el.classList.contains('is-active'))) {
                    moreBtn.classList.add('has-active');
                }
                for (const el of itemEls) panel.appendChild(el);   // alle, gestapelt
                if (wasOpen) { panel.classList.add('open'); moreBtn.setAttribute('aria-expanded', 'true'); }
                else closePanel();
                positionPanel();   // Inline-Styles raeumen + --ds-nav-h setzen
                lastW = nav.clientWidth;
                return;
            }
            nav.classList.remove('ds-nav--narrow');
            moreBtn.innerHTML = MORE_LABEL();

            const cs   = getComputedStyle(nav);
            const gap  = parseFloat(cs.columnGap || cs.gap) || 4;
            const innerW = nav.clientWidth - (parseFloat(cs.paddingLeft) || 0) - (parseFloat(cs.paddingRight) || 0);
            const fixedW = brand.offsetWidth + mobileToggle.offsetWidth + gap * 2;
            const widths = itemEls.map(el => el.offsetWidth + gap);
            const totalItems = widths.reduce((s, w) => s + w, 0);
            const SAFETY = 4;
            let avail = innerW - fixedW - SAFETY;

            if (totalItems <= avail) { closePanel(); lastW = nav.clientWidth; return; }   // alles passt → kein Dropdown

            // Es gibt Overflow → "Mehr"-Knopf einblenden und dessen Breite reservieren
            more.style.display = '';
            avail -= moreBtn.offsetWidth + gap;

            const activeIdx = itemEls.findIndex(el => el.classList.contains('is-active'));
            let used = 0;
            if (activeIdx >= 0) used += widths[activeIdx];   // aktives Item bleibt garantiert sichtbar

            const overflow = [];
            for (let i = 0; i < itemEls.length; i++) {
                if (i === activeIdx) continue;
                if (used + widths[i] <= avail) { used += widths[i]; }
                else { overflow.push(itemEls[i]); }
            }
            for (const el of overflow) panel.appendChild(el);   // in Original-Reihenfolge

            // Offen-Zustand ueber Resize/Relayout hinweg bewahren — sonst klappt das
            // Menue auf iOS bei jedem Adressleisten-Resize sofort wieder zu.
            if (wasOpen && panel.children.length) {
                panel.classList.add('open');
                moreBtn.setAttribute('aria-expanded', 'true');
                positionPanel();   // fixed-Position unter dem Knopf aktuell halten
            } else {
                closePanel();
            }
            lastW = nav.clientWidth;
        }

        // Vor allen anderen Body-Children einfuegen
        document.body.insertBefore(nav, document.body.firstChild);

        relayout();
        let rt = null;
        function scheduleRelayout() {
            clearTimeout(rt);
            rt = setTimeout(function () {
                // Nur die Hoehe geaendert (z.B. iOS-Adressleiste ein/aus)? Kein Umbau
                // — spart Arbeit und laesst ein offenes "Mehr"-Menue offen.
                if (nav.clientWidth === lastW) return;
                relayout();
            }, 120);
        }
        window.addEventListener('resize', scheduleRelayout);
        if (window.ResizeObserver) { try { new ResizeObserver(scheduleRelayout).observe(nav); } catch (e) { /* noop */ } }
        // Nach Font-Load nochmal messen (Breiten koennen sich aendern)
        if (document.fonts && document.fonts.ready) { document.fonts.ready.then(relayout).catch(() => {}); }

        // ── Zaehler-Badge "Offene Fragen" ────────────────────────────────────────
        // Zahl kommt aus /api/fragen/count (serverseitig 30s gecacht — die Nav laeuft
        // auf JEDER Seite). Fehler bleiben unsichtbar: Badge einfach aus.
        // WICHTIG: nach dem Setzen relayout() direkt aufrufen — die Item-Breite aendert
        // sich, aber die Nav-Breite nicht, und scheduleRelayout() steigt bei gleicher
        // Breite frueh aus.
        function setBadge(el, n) {
            const shown = n > 0;
            lastCount = n;
            el.textContent = shown ? (n > 99 ? '99+' : String(n)) : '';
            el.classList.toggle('on', shown);
            el.parentElement.classList.toggle('has-badge', shown);
            el.parentElement.title = shown
                ? t('nav.fragen.count', '{n} offene Frage(n)').replace('{n}', String(n))
                : t('nav.fragen.title', 'Offene Fragen');
        }
        function refreshBadges() {
            if (!badgeEls.fragen) return;
            fetch('/api/fragen/count', { cache: 'no-store' })
                .then(r => r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status)))
                .then(d => {
                    const n = Number(d && d.count) || 0;
                    console.debug('[nav.js] offene Fragen:', n, d);
                    setBadge(badgeEls.fragen, n);
                    relayout();   // Breite hat sich geaendert -> Overflow neu verteilen
                })
                .catch(e => {
                    console.warn('[nav.js] Fragen-Zaehler nicht ladbar:', e);
                    setBadge(badgeEls.fragen, 0);
                    syncMoreBadge();
                });
        }
        refreshBadges();
        setInterval(refreshBadges, 60000);
        // Beim Zurueckwechseln auf den Tab sofort aktualisieren statt bis zu 60s warten
        document.addEventListener('visibilitychange', function () {
            if (!document.hidden) refreshBadges();
        });

        console.log('[nav.js] Menue eingefuegt (Overflow-Dropdown aktiv) — aktive Seite:', path);
    }

    // Zentraler Theme-Umschalter — auf allen Nav-Seiten automatisch dabei
    if (!document.querySelector('script[src^="/theme.js"]')) {
        const th = document.createElement('script');
        th.src = '/theme.js?v=20260716b';
        document.head.appendChild(th);
    }

    // Darstellungs-Panel (Akzentfarbe, Schriftgroesse) — ebenfalls ueberall
    if (!document.querySelector('script[src^="/js/darstellung.js"]')) {
        const ds = document.createElement('script');
        ds.src = '/js/darstellung.js?v=20260716c';
        document.head.appendChild(ds);
    }
    // Sprachumschalter (de/en/es) — ebenfalls ueberall
    if (!document.querySelector('script[src^="/lang.js"]')) {
        const ln = document.createElement('script');
        ln.src = '/lang.js?v=20260823';
        document.head.appendChild(ln);
    }
    // GitHub-Rückkanal: Frontend-Fehler melden (nur bei Opt-in, prüft selbst) — ebenfalls überall
    if (!document.querySelector('script[src^="/js/github-report.js"]')) {
        const gr = document.createElement('script');
        gr.src = '/js/github-report.js?v=20260822';
        document.head.appendChild(gr);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', buildNav);
    } else {
        buildNav();
    }
})();
