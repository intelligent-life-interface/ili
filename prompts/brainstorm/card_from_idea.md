# Brainstorm: Idee → Kanban-Karte

**ID:** `brainstorm/card_from_idea`
**Modul:** `app/services/brainstorm_service.py:194`
**Output:** JSON-Objekt
**Stabilität:** Sehr hoch (fix)
**Cache-Phase:** 1 (sofort)

## Text

```
Du wandelst eine Brainstorming-Notiz in EINE konkrete Kanban-Karte um. Antworte AUSSCHLIESSLICH mit einem JSON-Objekt, kein Fliesstext, keine Code-Fences:

{"title":"kurzer Titel (max 8 Wörter)","desc":"1-2 Sätze, was zu tun ist","priority":"hoch|mittel|niedrig"}

Bleib nah am Wortlaut der Notiz, erfinde keine neuen Details. Sprache: Deutsch.
```

## Eigenschaften

- **Länge:** 5 Zeilen
- **Format:** JSON-Objekt (NICHT Array)
- **Felder:**
  - `title`: max 8 Wörter, wird als `💡 {title}` auf der Karte angezeigt
  - `desc`: 1-2 Sätze (geht ins `description`-Feld)
  - `priority`: `hoch|mittel|niedrig` → Label-Farbe (rot/orange/grün)
- **Ziel:** Eine Brainstorm-Aussage zur konkreten Task verdichten
- **Fallback:** Ohne KI = erste Zeile als Titel, ganzer Text als Beschreibung, Prio=mittel

## Codesystematik

- Input: `text` (Brainstorm-Notiz)
- Output-Parsing: JSON zwischen `{` und `}` (robust gegen Markdown-Noise)
- Validierung: Prio muss in `PRIORITY_COLORS` sein, sonst mittel

## Changelog

- **2026-08-03:** Initial dokumentiert (keine Änderung)
