"""Browser-Tor des Release-Loops: keine Konsolenfehler, keine fehlgeschlagenen
Requests — auf der Startseite UND auf einer Projektseite.

Aufruf: ILI_BASE=http://127.0.0.1:8197 python tests/browser_check.py
Braucht Playwright (hier: ~/.venvs/playwright).
"""

import sys
from playwright.sync_api import sync_playwright

import os
BASE = os.environ.get("ILI_BASE", "http://127.0.0.1:8080")
# Eine PROJEKTSEITE gehört dazu: dort laufen die eigentlichen Funktionen.
# Die 0.1.21-Lehre — drei Releases lang sah der Check nur die Startseite.
PAGES = ["/", "/ai-settings.html", "/bugs.html", "/project.html?id=willkommen"]

with sync_playwright() as p:
    browser = p.chromium.launch()
    failures = []
    for path in PAGES:
        page = browser.new_page()
        console, http = [], []
        page.on("console", lambda m: console.append(f"{m.type}: {m.text}") if m.type == "error" else None)
        # 401 on /projterm/ is by design: the terminal iframe asks for basic auth,
        # nginx answers 401 and serves the login page (docs/PROJECT-TERMINAL.md).
        page.on("response", lambda r: http.append(f"{r.status} {r.url}")
                if r.status >= 400 and not (r.status == 401 and "/projterm/" in r.url) else None)
        page.on("pageerror", lambda e: console.append(f"pageerror: {e}"))
        page.goto(BASE + path, wait_until="load", timeout=30000)
        page.wait_for_timeout(3500)
        title = page.title()
        if "project.html" in path:
            # headline feature of 0.1.21: the stale-card filter must be on the page
            stale = page.locator("[class*=karteileich], [id*=stale], [class*=stale], [data-filter*=stale]")
            print(f"    Karteileichen-Filter vorhanden: {stale.count() > 0}")
        badge = page.locator(".ili-version-badge, [class*=version]").first
        badge_text = badge.inner_text() if badge.count() else "(keine Plakette gefunden)"
        print(f"--- {path}  title={title!r}  version-badge={badge_text.strip()[:40]!r}")
        for c in console:
            if "projterm" in c or ("401" in c and "Unauthorized" in c):
                print("    (erwartet)", c[:100]); continue
            print("    KONSOLE:", c[:160]); failures.append(path)
        for h in http: print("    HTTP:", h[:160]); failures.append(path)
        page.close()
    browser.close()
    print("ERGEBNIS:", "FEHLER auf " + ", ".join(sorted(set(failures))) if failures else "0 Konsolenfehler, 0 HTTP-Fehler")
    sys.exit(1 if failures else 0)
