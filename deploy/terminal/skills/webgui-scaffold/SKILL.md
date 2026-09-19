---
name: webgui-scaffold
description: Erzeugt WebGUI-Boilerplate im Home-Stack-Stil für ein Container-Projekt — index.html mit Gradient-Header/Tabs/Status-Footer, angebunden ans zentrale UI-Kit (ui.intranet.<DOMAIN>), plus leeres style.css/app.js für Projekteigenes und StaticFiles-Anbindung in main.py. Nutze bei "WebGUI", "Frontend", "Oberfläche", "GUI für Container", "Navbar/Tabs". Mit --full wird vorher container-scaffold für das komplette Projekt aufgerufen.
---

# webgui-scaffold — WebGUI-Boilerplate im Home-Stack-Stil

Legt `app/static/{index.html,style.css,app.js}` an und verdrahtet `main.py` mit
`StaticFiles`.

## Stil kommt aus dem zentralen UI-Kit

Die GUI lädt `https://ui.intranet.<DOMAIN>/v1/ui-kit.{css,js}` — Layout,
Farben, Tabs, Karten, Buttons, Tabellen, Formulare, Dark-Mode, Theme-Toggle
und Status-Dot stecken dort. Quelle: `~/Projekte/ui-verbesserungen/ui-kit/`,
Styleguide mit allen Klassen: <https://ui.intranet.<DOMAIN>/>.

Das erzeugte `style.css`/`app.js` ist bewusst fast leer und nur für
Projekteigenes da. **Nichts aus dem Kit hierher kopieren** — sonst hat man
wieder 20 eingefrorene Kopien. Fehlt eine Komponente, gehört sie ins Kit.

⚠️ Das Kit ist **nur im LAN** erreichbar. Eine GUI, die über
`home.<DOMAIN>` von aussen laufen soll, kopiert `ui-kit.css`/`ui-kit.js`
nach `app/static/` und passt die beiden Pfade in `index.html` an.

## Wann einsetzen
- Neues oder bestehendes Container-Projekt braucht eine Web-Oberfläche
- Zusammen mit `container-scaffold` (`--full`) für „Projekt komplett mit GUI"

**Nicht einsetzen:** für bestehende GUIs (überschreibt nie, bricht ab wenn
`static/index.html` existiert) oder React/SPA-Projekte.

## Nutzung

```bash
# GUI in bestehendes Projekt (z.B. frisch per container-scaffold erstellt):
~/.claude/skills/webgui-scaffold/webgui.sh <name> \
  --title "Mein Tool" --desc "Was es tut" \
  --tabs "Übersicht,Daten,Einstellungen"

# Alles in einem Schritt (container-scaffold + GUI):
~/.claude/skills/webgui-scaffold/webgui.sh <name> --full \
  --port 8827 --tags "tag1, tag2" --title "Mein Tool" --desc "Was es tut" \
  --tabs "Übersicht,Daten"

# Abweichender App-Ordner:
~/.claude/skills/webgui-scaffold/webgui.sh <name> --dir ~/Projekte/<name>/app
```

## main.py-Verhalten (sicher)
- fehlt → wird aus Template erstellt (FastAPI + StaticFiles + `/api/status` + `/health`)
- unverändertes container-scaffold-Gerüst → ersetzt, Backup `main.py.bak-webgui`
- eigener Code → bleibt unangetastet, Skript druckt den Einbau-Snippet

## Danach
- Bauen/Starten: `podman build -t <name> ~/containers/<name> && systemctl --user restart container-<name>.service`
- Frontend-Ausbau (Formulare, Tabellen, Charts) via `ollama-code` generieren
- Sichtprüfung per Browser/Playwright-Screenshot — nie nur curl
