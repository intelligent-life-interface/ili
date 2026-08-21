# Project Creation: Name-Korrektur (Anti-Fantasie)

**ID:** `project_creation/correct_name`
**Modul:** `project_creator.py:372`
**Output:** Single line (Name oder "UNKLAR")
**Stabilität:** Hoch
**Cache-Phase:** 2

## Text

```
Du korrigierst Schreibfehler in einer kurzen Projekt-Eingabe und gibst einen knappen Projektnamen (1-4 Wörter, Deutsch) zurück. Antworte NUR mit dem Namen, ohne Erklärung oder Anführungszeichen. Ist die Eingabe bereits ein brauchbarer Name, gib sie UNVERÄNDERT zurück. Deute das Thema NICHT um und füge KEINE zusätzlichen Wörter oder Attribute hinzu — auch nicht, um den Namen 'runder' zu machen; ein einzelnes Wort ist als Name erlaubt. Ergibt die Eingabe keinen erkennbaren Sinn, antworte genau mit: UNKLAR
```

## Eigenschaften

- **Länge:** 1 Absatz (~350 Zeichen)
- **Output:** Single line (Name oder literal "UNKLAR")
- **Max Ausgabe:** 80 Zeichen
- **Ziel:** Tippfehler-Korrektur ohne Thema-Umdeuten oder Attribute-Erfindung
- **Anti-Muster:** Nicht "Geschichte" → "Schweizer Geschichte" (Attribute erfunden)
- **Kontext-Handling:** Parent-Context nur für Verständnis mehrdeutiger Eingaben, nie in Namen übernehmen

## Codesystematik

- Input: Projekt-Name (User-Eingabe)
- Optional: Parent-Context (Mutterprojekt-Beschreibung, max 300 Zeichen)
- Output-Parsing: Erste Zeile, Strip Quotes, Check auf "UNKLAR"
- **Anti-Fantasie-Guard (Server-seitig):**
  - Wenn Wort-Anzahl in Output > Wort-Anzahl in Input: User-Input behalten
  - Wenn Output-Länge > 80 Zeichen: UNKLAR behandeln
  - Temperatur: 0.0 (deterministisch)

## Changelog

- **2026-08-03:** Initial dokumentiert
- **Notiz:** Guard gegen Wort-Hinzufügung dokumentiert (Incident 07.07.2026: "Geschichte" → "Schweizer Geschichte")
