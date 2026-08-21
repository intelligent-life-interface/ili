# Brainstorm: Gespräch → Projekt-Beschreibung

**ID:** `brainstorm/description_from_convo`
**Modul:** `app/services/brainstorm_service.py:317`
**Output:** Plain Text (2-4 Sätze)
**Stabilität:** Hoch
**Cache-Phase:** 2 (wenn Brainstorm-Stabilität erwiesen)

## Text

```
Du fasst ein Brainstorming-Gespräch zu EINER prägnanten Projekt-Beschreibung zusammen. Schreibe 2-4 Sätze in ganzen Sätzen (kein Stichwort-Fliess, keine Aufzählung, keine Anrede, kein Titel): Worum geht das Projekt, was ist das Ziel, ggf. der geplante Weg. Bleib nah am Gesagten, erfinde nichts dazu. Nur der Beschreibungstext, sonst nichts. Sprache: Deutsch.
```

## Eigenschaften

- **Länge:** 5 Zeilen
- **Format:** Plain Text (kein JSON, kein Markdown)
- **Output-Länge:** 2-4 Sätze (~150–300 Zeichen)
- **Ziel:** Ganzes Brainstorm-Gespräch zu einer prägnanten Projekt-Beschreibung verdichten
- **Anti-Muster:** Keine Aufzählung, keine Stichwörter, kein Titel/Intro

## Codesystematik

- Input: Transkript des Gesprächs (Format: `Du: …\nKI: …`)
- Output-Verarbeitung: Text 1:1 übernehmen (kein Parsing nötig)
- Speicherung: In `manifest.json` → `description`-Feld (ersetzt bisherige)

## Changelog

- **2026-08-03:** Initial dokumentiert (keine Änderung)
