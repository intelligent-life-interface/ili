---
name: planen
description: "Planungs-Phase für eine neue Idee oder ein neues Feature im Homeserver-Stack — BEVOR Code entsteht. Klärt: gehört das überhaupt in ein neues Projekt oder in ein bestehendes, welches Kanban-Board, Zerlegung in self-contained Karten, test_first, KI-Routing (Ollama vs Claude), Modellstufe. Nutze bei \"neue Idee\", \"planen\", \"wie gehen wir das an\", \"sollen wir dafür ein Projekt\", \"in Karten zerlegen\", vor container-scaffold. NICHT für die Architektur-Prüfung eines fertigen Projekts — dafür architektur-review."
---

# planen — von der Idee zur Kartenliste

Reihenfolge: **Duplikat-Check → Verortung → Zerlegung → Flags → Routing**.
Erst danach `container-scaffold` bzw. Code. Am Ende `architektur-review`.

## 1. Duplikat-Check (immer zuerst)

Die häufigste vermeidbare Arbeit ist ein Projekt, das es fast schon gibt.

```bash
# Was existiert schon zum Thema? (SQLite-Index, billiger als Volltextsuche)
python3 ~/Projekte/kanban-ki-optimierung/claudemd_db.py --suche "<stichwort>"
grep -i "<stichwort>" ~/.claude/skills/homeserver-projekte/projects.tsv
```

Treffer → **erweitern statt neu bauen**. Kein Treffer → weiter.

## 2. Verortung: eigenes Projekt oder Unterprojekt?

| Situation | Entscheidung |
|---|---|
| Eigener Dienst, eigener Port, eigener Lebenszyklus | eigenes Projekt + eigenes Board |
| Ergänzt ein bestehendes Projekt fachlich | Karten ins bestehende Board, kein neues Projekt |
| Thematisch verwandt, aber eigener Arbeitsstrom | Unterprojekt (`parent_ids`) — erbt Kontext und `test_first` |

**Projektstruktur bleibt flach.** Keine tiefen Hierarchien; lieber ein Unterprojekt
mehr als drei Ebenen. Bei Unterprojekten reicht der Elternkontext automatisch in
alle KI-Schritte durch — der Name wird im Thema der Mutter interpretiert.

## 3. Zerlegung in Karten

Jede Karte **self-contained**: Titel + `description`, die für sich allein verständlich
ist. Das Board ist das Langzeitgedächtnis — nach `/clear` ist die Karte alles, was bleibt.

- Eine Karte = ein abschliessbares Ergebnis, nicht ein Arbeitsschritt.
- Abhängigkeiten in die Beschreibung schreiben, nicht in die Reihenfolge hoffen.
- Karten, die eine Entscheidung vom Menschen brauchen, **als Entscheidungskarte** formulieren
  (Frage + klare Optionen A/B/C) — nicht als offene Aufgabe.
- Der Automat gruppiert später selbst bis zu 4 zusammengehörige Karten pro Session;
  du musst nicht künstlich bündeln.

Beide Beschreibungsfelder setzen (`desc` **und** `description`) — die GUI liest je
nach Ansicht ein anderes.

## 4. Flags beim Board-Anlegen

| Flag | Wann setzen |
|---|---|
| `test_first` | Projekt betrifft einen laufenden Container/Service → neue Version läuft zuerst als Testversion (Port +10000). Erbt an Unterprojekte. |
| `auto` | Der Kanban-Automat darf das Board eigenständig abarbeiten |
| `model` | Soll-Modellstufe je Board — schwierige Projekte höher, Routine tiefer |
| `status` | `entwurf` … `archiviert`; `pausiert` ⇒ Automat stumm + aus der Übersicht |
| `owner` | 👤 Mensch oder 🤖 KI pro Karte |

## 5. KI-Routing festlegen

Vor dem Bauen entscheiden, **wer welchen Teil rechnet** — das ist der grösste Kostenhebel:

- **Ollama zuerst** (gratis, `<WINDOWS_PC_IP>:11434` via Proxy `:11435`): Klassifizieren, Tagging,
  Kurzbeschreibungen, Boilerplate, Code-Suche (`ollama-locate`), isolierte Funktionen
  (`ollama-code`), Frontend-Entwürfe.
- **Claude-Abo** (`claude -p` / Bridge `:8950`): mehrstufige Arbeit mit Tools,
  Bugfixes mit unklarem Kontext, Multi-File-Änderungen.
- **Anthropic-API mit Guthaben**: nur wenn es einen Grund gibt, den das Abo nicht abdeckt.
  Die Batch-API ist **kein Sparhebel gegenüber dem Abo** — sie kostet 50 % des API-Preises,
  das Abo kostet kein Guthaben. Batch lohnt nur für grosse Mengen unabhängiger
  One-Shot-Prompts ohne Tool-Nutzung, für die Ollama nicht reicht.

Faustregel: Was ein 9B-Modell zuverlässig kann, gehört nicht zu Claude.

## 6. Experiment vor Produktion

Neue Technik erst lokal ausprobieren, nicht direkt im laufenden Stack. Ausnahme:
das Dashboard selbst darf live weiterentwickelt werden.

## 7. Abschluss der Planung

- Board angelegt, Karten drin, Flags gesetzt
- Sub-`CLAUDE.md` mit `> **Tags:**`-Zeile angelegt
- Zeile in `~/.claude/skills/homeserver-projekte/projects.tsv` + `build_index.py`
- Danach: `container-scaffold` (Gerüst) → bauen → `architektur-review` (Prüfung)

Doku entsteht **mit** dem Schritt, nicht danach.
