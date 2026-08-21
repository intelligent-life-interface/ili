# Project Creation: Foto → Tags

**ID:** `project_creation/vision_tags`
**Modul:** `project_creator.py:245`
**Output:** Kommagetrennte Tag-Liste
**Stabilität:** Hoch (über Claude Vision, nicht über Text)
**Cache-Phase:** 2

## System Prompt

```
Antworte NUR mit kommaseparierten Schlagwörtern. Keine Sätze, keine Nummern.
```

## User Prompt

```
Was siehst du auf diesem Foto? Gib 5-8 deutsche Schlagwörter zurück, kommagetrennt, kleingeschrieben:
```

Optional: Kontext-Hinweis (`Kontext: {note}`)

## Eigenschaften

- **Länge:** Jeweils 1 Zeile (System), 2 Zeilen (User)
- **Output:** Kommagetrennte Liste (z.B. `heimkino, mediapipe, bildschirm`)
- **Parsing:** `_parse_tag_list(response)` → lowercase Tags, dedupliziert, 2-30 Zeichen
- **Ziel:** Foto-Kontext erfassen (nicht die KI-Vision der Projektidee, nur Objekt-Tags)
- **Anti-Muster:** Keine Sätze, keine Nummern, keine Erklärungen

## Codesystematik

- Input: Photo bytes (JPEG/PNG)
- Bridge: `_claude_abo_vision()` (POST `/vision`)
- Output-Parsing: Split by comma, strip whitespace, lowercase, filter 2-30 chars
- Fallback: Empty list wenn Bridge nicht erreichbar

## Changelog

- **2026-08-03:** Initial dokumentiert
- **Notiz:** Vision lädt über Claude-Abo (teuer), wird kombiniert mit Text-Tags
