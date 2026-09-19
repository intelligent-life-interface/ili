---
name: frontend-architektur
description: Wie Frontend-Code im Home-Stack sauber strukturiert wird (nicht womit man startet — das macht webgui-scaffold). Trennung Struktur/Logik/Style, zentrales UI-Kit statt Kopien, i18n über Sprachdateien statt hartkodierter Texte, stabile Element-IDs, Fetch-/State-Muster, und Verifikation im echten Browser statt curl. Enthält frontend-check.sh (OK/WARN/FAIL wie architektur-review: UI-Kit eingebunden, Inline-CSS, hartkodierte deutsche Texte statt Sprachdatei, stabile IDs). Nutze bei allem, was HTML/JS/CSS, WebGUI, Oberfläche, Frontend, index.html/app.js/style.css, Buttons/Formulare, Dark-Mode/Theme, Mehrsprachigkeit oder „das Frontend ist unsauber/aufräumen" betrifft — BEVOR du GUI-Code schreibst oder änderst.
---

# frontend-architektur — sauberer Frontend-Aufbau

Diese Regeln sagen, **wie** Frontend-Code strukturiert wird. Das **Gerüst**
(Boilerplate, Header/Tabs/Footer) liefert der Skill `webgui-scaffold`, die
**Styles/Komponenten** das zentrale UI-Kit. Hier steht die Sauberkeits-Ebene —
sie ersetzt die beiden nicht, sondern ergänzt sie.

## 0. Prüfen statt nur lesen

```bash
~/.claude/skills/frontend-architektur/frontend-check.sh <projektpfad>
~/.claude/skills/frontend-architektur/frontend-check.sh --all [--json]
```

Ausgabe: OK/WARN/FAIL wie architektur-review — UI-Kit eingebunden (/ui-kit/v1/ oder volle
Intranet-URL), Inline-CSS statt Kit-Komponente, Sprachdatei vorhanden, hartkodierte
deutsche Texte (Heuristik), auffällige/instabile IDs. `--json` für den Kanban-Automat.

## 1. Drei-Schichten-Trennung (verbindlich)

Pro GUI **drei** Verantwortlichkeiten, drei Dateien:

| Datei | enthält | enthält NICHT |
|---|---|---|
| `index.html` | Struktur/Markup, semantische Elemente, stabile IDs | Logik, Inline-`<script>`-Wildwuchs, hartkodierte Texte |
| `app.js` | Verhalten: Fetch, State, Event-Handler | CSS-Strings, Style-Manipulation die ins CSS gehört |
| `style.css` | **nur Projekteigenes** | Kopien von UI-Kit-Regeln |

- **Kein Inline-JS/CSS** ausser winzigen Ausnahmen. Logik gehört in `app.js`,
  Aussehen ins CSS/UI-Kit.
- **Business-Logik gehört nicht ins Frontend** — das Frontend rendert und ruft
  API-Endpoints; Rechnen/Entscheiden macht das Backend.

## 2. UI-Kit statt Kopien (verbindlich)

- Stil + Basis-Logik immer aus dem zentralen Kit laden:
  ```html
  <link rel="stylesheet" href="/ui-kit/v1/ui-kit.css">
  <script src="/ui-kit/v1/ui-kit.js" defer></script>
  ```
- **Relative Pfade nur bei GUIs mit Caddy-VHost** (Snippet `ui-kit-proxy`). Ohne
  VHost: volle URL `https://ui.intranet.<DOMAIN>/v1/…` oder lokale Kopie.
- **Fehlt eine Komponente, kommt sie INS Kit** — nie ins projekteigene `style.css`
  kopieren. Sonst driften N Kopien auseinander. Quelle:
  `~/Projekte/ui-verbesserungen/ui-kit/`, Styleguide: <https://ui.intranet.<DOMAIN>/>.
- Dark-Mode/Theme kommt aus dem Kit, nicht pro Projekt neu erfunden.

## 3. Mehrsprachigkeit / Texte (verbindlich)

- **Keine hartkodierten UI-Texte** in HTML/JS. Texte in Sprachdateien (`de.json`),
  **Deutsch ist Default**; eine weitere Sprache ist dann nur eine weitere Datei.
- **Element-IDs stabil und sprachunabhängig** halten (Logik/i18n hängen an IDs,
  nicht an sichtbaren Beschriftungen). Beschriftung ändern ≠ ID ändern.

## 4. Fetch- / State-Muster

- API-Aufrufe gebündelt (eine kleine `api()`-Hilfe statt verstreuter `fetch()`),
  mit Fehler-/Timeout-Behandlung und sichtbarem Fehlerzustand für den Nutzer.
- State an einer Stelle halten, nicht im DOM „verstecken". DOM = Darstellung des
  States, nicht die Quelle der Wahrheit.
- Ladezustände und Leerzustände explizit rendern (kein stummes leeres Panel).

## 5. Erzeugen & Prüfen

- **Frontend-Code darf via Ollama generiert werden** (gratis, lokal) — Ergebnis
  aber immer prüfen. Skill `ollama-code`.
- **Verifikation IMMER im echten Browser**, nie mit `curl`. Ein 200er von `curl`
  sagt nichts über gerendertes Layout, JS-Fehler in der Konsole oder Theme. Nutze
  einen Browser (z.B. Playwright-venv, `full_page=True` für Screenshots).
- Intranet-URL zum Testen verwenden, nicht `localhost` (Caddy-VHost spiegelt die
  reale Umgebung inkl. UI-Kit-Proxy).

## Verweise (nicht duplizieren)

- Gerüst neu aufsetzen → `webgui-scaffold` (bindet UI-Kit-Pfade automatisch ein)
- Diagramme/Charts → Skill `dataviz`
- Systemeinordnung/Exposure der GUI → `architektur-review`
- Backend hinter der GUI → Skill `backend-architektur`
