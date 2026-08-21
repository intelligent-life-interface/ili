# ili — Arbeitsweise: Kanban als Gedächtnis für KI-gestützte Entwicklung

> **Tags:** methodik, kanban, board, projekte, entscheidungen, owner, adoption, vorlage

## Was ist das System?

ili ist ein **Kanban-Board als Projektgedächtnis**: Jedes Projekt ist ein Board, jede Aufgabe eine Karte. Der Kern ist nicht die grafische Oberfläche, sondern die **Struktur selbst** — Boards, Karten, Spalten, Metadaten — als Schnittstelle zwischen dir und deiner KI.

Du brauchst kein IT-Background. Die KI nutzt die Karten wie ein Notizbuch: Sie liest die aktuelle Aufgabe, den Kontext und bisherige Entscheidungen, entwickelt eigenständig und dokumentiert Fortschritt und Befunde direkt im Board. So vergisst das System nichts — nicht der Manager, nicht die KI, nicht du.

---

## Die drei Adoptionswege

**Das System ist eine Vorlage, kein Korsett.** Drei Wege stehen offen:

### Weg A: Grundlagen unverändert übernehmen

Du installierst ili, startest die Einrichtungs-Tour (im Willkommen-Board), aktivierst deine KI (Claude API, Ollama) und arbeitest mit der vorgegebenen Struktur weiter:
- **Projekt = Board** (`Mein erstes Projekt` → `proj-meines-erstes-projekt`)
- **Spalten:** Backlog → Laufend → Überprüfen → Erledigt
- **Unterprojekte:** Das Menü zeigt eine Hierarchie (Mutterprojekt + Kinder)
- **Entscheidungskarten:** Bei wichtigen Fragen legt die KI eine 🟡 ENTSCHEIDUNG an, ihr beantwortet per Knopf, die KI setzt um
- **owner-Trennung:** Karten tragen `owner: KI` oder `owner: Ich` → die KI bearbeitet nur ihre eigenen, fragt bei Unsicherheit

Das ist **niedrigschwellig**: Keine Anpassungen nötig, Standardkonventionen gelten sofort.

### Weg B: Eigene Struktur bauen

Du spielst die Grundlagen-Tour, ignorierst sie aber danach komplett und entwirfst eine **eigene Struktur** — andere Spalten-Namen, andere Feldnamen, eigene Konvention für Prioritäten, Owner, Fälligkeit. Die KI lernt deine Regeln aus der README oder aus den bestehenden Karten.

Das ist **maximal flexibel**: Kanban-Struktur bleibt (was eine Karte, Spalte, Feld ist), der Inhalt ist dein Design.

### Weg C: Hybrid — Grundlagen + eigene Erweiterungen

Die Vorlagen-Spalten bleiben (`Backlog`, `Laufend`, `Überprüfen`, `Erledigt`), aber du ergänzt eigene Spalten (z.B. `⏸ Parked`, `🐛 Bugs`, `🎯 Sprintgoal`), eigene Feldtypen (z.B. `deadline`, `team`, `external_dependency`) oder eigene Labels (z.B. `blocked`, `urgent`, `technical-debt`).

Das ist **praktisch am häufigsten**: Du behältst bewährte Struktur, passt sie aber für deine Zwecke an.

---

## Kern-Konzepte

### Projekt = Board

Ein Projekt ist ein Kanban-Board im JSON-Format (`boards/<id>.json`). Der Pfad ist gleichzeitig dein Ordner im Terminal (`~/Projekte/<id>/`). Die KI öffnet das Projekt-Terminal, arbeitet dort, die IDE lädt Dateien aus diesem Ordner.

Ein frisches ili enthält zwei Seed-Boards:
- **📋 Willkommen** — eine Übersicht der Methodik in sieben Karten
- **💡 Ideen** — vier vorgefertigte Ideen-Karten, die du oder die KI konkretisieren

### Unterprojekte / Hierarchie

Boards haben optional `parent_ids` (Liste von übergeordneten Projekt-IDs). Das Frontend rendert:
- **Mutterprojekt** oben (`Projekt: Mein System`)
- **Unterprojekte** darunter (`├─ Komponente A`, `├─ Komponente B`, `└─ Komponente C`)

Navigieren funktioniert bidirektional: vom Kind zum Mutter (Breadcrumb-Knopf), von der Mutter zu den Kindern (Menü). `Board ID` bleibt eindeutig; ein Kind kann mehrere Eltern haben (mehrere Projekte teilen eine Aufgabe).

### Karten und Spalten

Eine Karte hat:
- **Titel** — eine Zeile, prägnant (`Datenbank-Migration`, `API-Fehler #42 beheben`)
- **Beschreibung** — der Kontext (was, warum, bisherige Versuche, Fehler-Stack)
- **Spalte** — `Backlog`, `Laufend`, `Überprüfen`, `Erledigt` (oder deine eigenen)
- **Felder** (optional): `priority`, `effort`, `owner`, `deadline`, `tags`, `labels`
- **Status-Marker** — `updated`, `created`, `completed_at` (automatisch)
- **Anhänge** — Dateien, Bilder, externe Links
- **Kommentar** — KI-Notizen zum Fortschritt (Änderungen zur Karte)

### Entscheidungskarten (🟡 ENTSCHEIDUNG)

Eine Entscheidungskarte hat das Label `Entscheidung` und folgt diesem Format:

```
Titel: 🟡 ENTSCHEIDUNG: <Frage kurz>

Beschreibung:
Längere Erklärung der Frage, Kontext, was auf dem Spiel steht.

Optionen:
- **Option A:** Kurze Erklärung, Vor- / Nachteile
- **Option B:** Alternative
- **Option C:** Dritte Möglichkeit
```

Das Frontend rendert Knöpfe (A / B / C), du wählst eine. Die KI schreibt deine Antwort in die Karten-Beschreibung (`Manager entschied: Option B wegen …`). Beim nächsten Tick liest die KI die Antwort und setzt sie um.

**Wichtig:** Entscheidungskarten sind der einzige Ort, wo die KI auf deine Steuerung wartet. Alles andere entwickelt die KI eigenständig (in der `owner: KI`-Spalte).

### owner — Trennung zwischen KI und dir

Jede Karte trägt ein Feld `owner`:
- **`owner: KI`** — die KI bearbeitet diese Karte (liest die Aufgabe, entwickelt, notiert Fortschritt)
- **`owner: Ich`** — du bearbeitest die Karte (KI hält sich raus, liest aber mit, um Kontext zu verstehen)
- **`owner: Gemeinsam`** (optional) — beide arbeiten alternierend dran

Sinn: **Kontextverlust vermeiden.** Wenn du eine `owner: KI`-Karte startest, antwortet die KI auf eine Frage _deinerseits_ — nicht weil sie freiwillig genau diese Aufgabe nehmen würde.

Beispiel:
- `owner: KI, Titel: Fehler in Datenbank-Migration debuggen` → die KI beginnt zu lesen, zu testen, dokumentiert den Bug
- `owner: Ich, Titel: SSH-Zugang ins Produktiv-System einrichten` → die KI liest die Situation (dein Kontext), schlägt Optionen vor, dich setzt um; sie dokumentiert deinen Fortschritt

### Self-contained als Langzeitgedächtnis

Jede Karte trägt alle Infos in sich:
- Titel + Beschreibung = Problem-Statement
- Kommentar-Historie = bisherige Versuche + Befunde
- Anhänge = Error-Logs, Screenshots, Code-Snippets, Ressourcen-Links
- `parent_card_id` (optional) = Bezug zu anderen Karten / Epics

Du kannst jede Karte **sechs Monate später** öffnen und weisst sofort, was los ist. Die KI lernt das Board beim Durchscrollen; keine versteckte Dokumentation nötig.

---

## Konventionen der Vorlage

Diese Grundlagen gelten ab Installation (Weg A), sind aber nicht erzwungen:

| Element | Konvention | Sinn |
|---|---|---|
| **Spalten** | Backlog → Laufend → Überprüfen → Erledigt | klarer Workflow, KI sieht Status sofort |
| **Karten-Titel** | Aktiv (Verb): „Fehler beheben", nicht „Fehler" | unmissverständlich, was zu tun ist |
| **Beschreibung** | Was, warum, bisherige Versuche, Fehler | Kontext für die KI (entscheidend!) |
| **owner** | `KI` / `Ich` / `Gemeinsam` | Rollen klar, keine doppelte Arbeit |
| **priority** | `high` / `medium` / `low` oder farbig | Reihenfolge für die KI festlegen |
| **effort** | `niedrig` / `mittel` / `hoch` | realistische Zeitplanung |
| **Entscheidung** | Label `Entscheidung` + Format Optionen: A\|B\|C | Frontend rendert Knöpfe, Manager delegiert |
| **Unterprojekte** | via `parent_ids: ["parent-id"]` im Board | Hierarchie im Menü sichtbar |
| **Anhänge** | Datei-Upload oder externe URL → Karte | alles an einer Stelle, keine Suche |
| **Archivieren** | Spalte `Erledigt` = archiviert (nicht gelöscht) | Gedächtnis bleibt, suchen möglich |

---

## board_templates.json — Vorlagen für neue Projekte

Das Paket enthält eine Datei `board_templates.json` mit zwei vorgefertigten Boards (Willkommen + Ideen) und Beispiel-Spalten-Definitionen:

```json
{
  "templates": [
    {
      "id": "proj-willkommen",
      "name": "Willkommen",
      "description": "Deine Einführung in die ili-Methodik",
      "columns": ["Backlog", "Laufend", "Überprüfen", "Erledigt"],
      "cards": [
        {
          "title": "🎯 Deine erste Aufgabe",
          "description": "...",
          "owner": "KI"
        }
      ]
    }
  ]
}
```

Du kannst diese Datei **editieren**, bevor du ein frisches ili startest. So kannst du:
- Eigene Spalten-Namen eintragen
- Seed-Karten anpassen
- Konventionen (Labels, Feldnamen) definieren

---

## Praktischer Start

### 1. Installation & Willkommen-Board

Nach der Installation (`docker compose up -d`) siehst du zwei Projekte:
- **📋 Willkommen** — Tour durch die Methodik (7 Karten)
- **💡 Ideen** — vier konkrete Ideen-Vorschläge

Lies die Willkommen-Karten. Sie erklären:
- Was Projekte sind
- Wie Unterprojekte funktionieren
- Format der Entscheidungskarten
- Beispiele für owner-Trennung

### 2. Erstes eigenes Projekt

Klick `➕ Neues Projekt` → Name + Beschreibung → Board entsteht mit:
- 4 leeren Spalten (Backlog, Laufend, Überprüfen, Erledigt)
- Manifest (Metadaten: ID, Name, parent_ids, Ersteller)
- Terminal-Session (falls ttyd aktiviert)

### 3. KI anbinden

In den **Einrichtungs-Boards** (5 Unterprojekte des 🔧 Konfiguration-Boards):
- **🌐 Domain & Aussenzugang** — wie erreichbar?
- **🤖 KI-Anbindung** — Claude API, Ollama oder beides?
- **🗄 Daten & Datenbank** — wo sollen Boards gespeichert werden?
- **♻ Betrieb** — wie Sicherung, Updates?
- **🐙 Code & Beiträge** — GitHub-Integration, Fork, Token?

Jedes dieser Unterprojekte hat Entscheidungskarten mit echten Optionen. Du beantwortest sie einmal, die KI setzt um.

### 4. Deine Konvention definieren

Entweder:
- **Weg A:** Grundlagen behalten, fertig
- **Weg B oder C:** Eigene Spalten/Felder ins frische Projekt, KI einmal briefen (README oder erste Entscheidungskarte)

Die KI lernt aus bestehenden Karten. Je konsistenter du die erste Stunde bist, desto besser versteht die KI deine Struktur danach.

---

## Was die KI kann, was nicht

### ✅ Die KI macht eigenständig (owner: KI)

- Aufgaben von deinem Board lesen und bearbeiten
- Entscheidungskarten vorbereiten (Frage + Optionen formulieren)
- Fortschritt notieren (Kommentare zur Karte)
- Fehler/Blocker als neue Karten vorschlagen
- Code/Doku nach deiner Struktur schreiben
- Unterprojekte aus Aufgaben-Ideen anlegen

### ❓ Die KI fragt oder delegiert (wenn unklar)

- Bei Entscheidungen wartet die KI auf deine Antwort
- Wenn mehrere Optionen sinnvoll sind → Entscheidungskarte anlegen
- Wenn externe Abhängigkeiten fehlen (Hardware, Login, API-Key) → Karte als „blockiert" parken

### ❌ Die KI macht nicht

- **Nicht in den Browser öffnen** — sie hat keinen Desktop
- **Nicht im Home-Verzeichnis arbeiten** — das ist privat
- **Nicht im Internet surfen** — außer als explizite Aufgabe
- **Nicht deine Secrets ausgeben** — `config.env` bleibt privat
- **Nicht ungefragt ins Terminal pushen** → fragt vorher

---

## Weiterführende Ressourcen

- **Willkommen-Board** — Einführung in 7 Karten
- **Ideen-Board** — konkrete Projektideen-Vorlage
- **Einrichtungs-Projekt** (🔧 Konfiguration) — 5 Entscheidungs-Unterprojekte
- **API-Doku** (`API.md`) — Karten, Boards, Felder, Operationen
- **Terminal-Kurzanleitung** (`TERMINAL.md`) — Projekt-Terminal per Browser
- **Privatsphäre** (`SECURITY.md`) — was bleibt lokal, was nicht

---

## Beispiel: Eine Aufgabe von Anfang bis Ende

**Szenario:** Du willst einen Fehler in deiner App beheben.

1. **Karte anlegen** (im Backlog)
   - Titel: `Fehler #42: Login-Button funktioniert nicht auf Mobile`
   - Beschreibung: Error-Log, Browser (Safari iOS), Schritte zum Reproduzieren
   - `owner: KI`, `priority: high`, `effort: medium`

2. **KI sieht die Karte**
   - Öffnet dein Projekt-Terminal
   - Cloned den Code-Repo oder öffnet bestehende Dateien
   - Beginnt zu debuggen (Console lesen, HTML prüfen, JavaScript testen)
   - Notiert Befunde: `Kommentar: CSS media-query greift nicht, @media (max-width: 600px) fehlt`

3. **Du prüfst den Fortschritt**
   - Liest die Karten-Kommentare
   - Bestätigst die Diagnose oder fragst nach
   - Falls unklar: KI legt Entscheidungskarte an (`Beheben via CSS oder via JS-Logic?`)
   - Du antwortest per Knopf

4. **KI setzt um**
   - Editet die CSS, committed, pushed (mit deinem Token)
   - Verschiebt die Karte in `Überprüfen`
   - Hinterlässt Link zu PR oder Commit

5. **Du testest & schließt ab**
   - Prüfst die Änderung manuell oder automatisiert
   - Verschiebt Karte in `Erledigt`
   - Board-Gedächtnis bleibt: nächster Fehler, gleiche Stelle → kein Nachfragen nötig

---

## Lizenzen & Community

ili wird als **Open Source veröffentlicht**, drei Adoptionswege sind alle erlaubt:
- Nutze die Vorlage unverändert
- Verzweige sie für deine Bedürfnisse
- Teile Verbesserungen zurück via GitHub (Issues, Pull Requests)

Alle Ideen-Karten sind als GitHub-Issues geöffnet, damit Entwickler weltweit auf gleiche Aufgaben hinarbeiten statt zu duplizieren.

---

**Viel Erfolg! 🚀**
