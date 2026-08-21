# Project Creation: Text → Tags

**ID:** `project_creation/text_tags`
**Modul:** `project_creator.py:281`
**Output:** Kommagetrennte Tag-Liste
**Stabilität:** Hoch (Anti-Fantasie-Regel gut etabliert)
**Cache-Phase:** 2

## System Prompt

```
Du vergibst 5-8 Schlagwörter für ein Projekt: kommagetrennt, kleingeschrieben, keine Erklärung, kein Fliesstext. Decke ab: (1) Thema/Zweck und (2) die im Text GENANNTEN verwendeten Technologien/Bausteine — auch solche, die nur genutzt und nicht selbst gebaut werden. Eigennamen/Technik dürfen englisch bleiben, sonst deutsch. WICHTIG: Verwende AUSSCHLIESSLICH Begriffe, die tatsächlich aus Titel oder Beschreibung hervorgehen. Erfinde KEINE Technologien. Steht im Text keine konkrete Technik, gib nur Themen-Schlagwörter zurück.
```

## User Prompt

```
Titel: {title}
[Mutterprojekt (Thema-Kontext): {parent_context}]  # Optional
Beschreibung: {description}  # Max 1200 Zeichen
Tags:
```

## Eigenschaften

- **Länge:** System ~350 Zeichen, User ~50 Zeichen (+ Daten)
- **Output:** Kommagetrennte Liste
- **Daten-Input:**
  - Titel: 1-80 Zeichen (bereits korrigiert)
  - Beschreibung: Max 1200 Zeichen (gekürzt)
  - Parent-Context: Optional, max 300 Zeichen (nur Kontext, nicht in Tags übernehmen)
- **Tag-Dimensionen:** Thema/Zweck + verwendete Technologien
- **Ziel:** Projekt einerseits über Thema, andererseits über Technik-Stack auffindbar machen

## Codesystematik

- Input: Title, Description, (optional) parent_context
- Temperature: 0.2 (leicht kreativ, aber fokussiert)
- Max-Tokens: 120
- Output-Parsing: `_parse_tag_list()` → lowercase, dedupliziert, 2-30 Zeichen
- Fallback: Empty list wenn Bridge nicht erreichbar
- Used by: Massen-Tagger (`project_tagger.py`), einzelne Projekt-Erstellung

## Changelog

- **2026-08-03:** Initial dokumentiert
- **Notiz:** Parent-Context wird oft bei Unterprojekten genutz (z.B. "Geschichte" unter ADHS-Projekt = richtig kontextualisiert als "historischer Lerninhalt", nicht als "Schweizer Rechtsgeschichte")
