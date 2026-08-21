# Brainstorm: Gesprächs-Plan → mehrere Karten

**ID:** `brainstorm/cards_from_plan`
**Modul:** `app/services/brainstorm_service.py:367`
**Output:** JSON-Array
**Stabilität:** Hoch
**Cache-Phase:** 2

## Text

```
Du leitest aus einem Brainstorming-Gespräch die konkreten, umsetzbaren Aufgaben ab. Antworte AUSSCHLIESSLICH mit einem JSON-Array (kein Fliesstext, keine Code-Fences), je Aufgabe ein Objekt:

[{"title":"kurzer Titel (max 8 Wörter)","desc":"1-2 Sätze, was zu tun ist","priority":"hoch|mittel|niedrig"}]

Nur Aufgaben, die im Gespräch wirklich vorkommen — erfinde keine dazu. Reihenfolge sinnvoll (Voraussetzungen zuerst). Höchstens 8 Aufgaben. Sprache: Deutsch.
```

## Eigenschaften

- **Länge:** 6 Zeilen
- **Format:** JSON-Array (NICHT einzelnes Objekt!)
- **Max Items:** 8 Aufgaben pro Plan
- **Felder je Aufgabe:**
  - `title`: max 8 Wörter
  - `desc`: 1-2 Sätze (was zu tun ist)
  - `priority`: `hoch|mittel|niedrig`
- **Ziel:** Aus einem Brainstorm-Gespräch die konkrete, umsetzbare Aufgabenliste ableiten
- **Fallback:** Ohne KI oder leeres Array → ValueError (Aufrufer zeigt Fehler)

## Codesystematik

- Input: Transkript des Gesprächs (`_transcript()`)
- Output-Parsing: JSON-Array zwischen `[` und `]`
- Validierung:
  - Muss Array sein, nicht leer
  - Title max 120 Zeichen (gekürzt auf Server-Seite)
  - Priority in `PRIORITY_COLORS`
  - Max 8 Items (alles nach Item 8 ignoriert)
- Card-Konstruktion: Jede als `💡 {title}` (wie `card_from_idea`)

## Changelog

- **2026-08-03:** Initial dokumentiert (keine Änderung)
