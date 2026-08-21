# Prompt-Bibliothek Changelog

Alle Änderungen an KI-Prompts im Dashboard (chronologisch, neuste zuerst).

## 2026-08-03

**Initial Dokumentation**
- Brainstorm-Prompts dokumentiert:
  - `system_prompt.md` — Kreativ-Partner-Rolle
  - `card_from_idea.md` — Idee → Kanban-Karte
  - `description_from_convo.md` — Gespräch → Projekt-Beschreibung
  - `cards_from_plan.md` — Gesprächs-Plan → mehrere Karten
- Project-Creation-Prompts dokumentiert:
  - `correct_name.md` — Name-Korrektur (Anti-Fantasie)
  - `vision_tags.md` — Foto → Tags
  - `text_tags.md` — Text → Tags
- Bug-Analysis dokumentiert:
  - `bug_triage.md` — Log → Klassifizierung + Fix

**Status:** Keine funktionalen Änderungen, nur Dokumentation bestehender Prompts.

---

## Zukünftige Versionen

### Phase 1: Prompt-Caching aktivieren
- System-Prompts (Brainstorm, Bug-Triage) werden mit `cache_control: {type: ephemeral}` markiert
- Bridge-Upgrade erforderlich (8950 muss System-Prompt-Arrays unterstützen)
- Erwartete Einsparung: 90% Input-Tokens bei Cache-Hits (5min-Fenster)

### Phase 2: Konsolidierung
- Duplizierte Patterns identifizieren (z.B. JSON-Output Instruktionen)
- Shared Snippets in `constants.md` auslagern
- Ollama-Prompts (Batch-Tagging, Klassifizierung) hinzufügen

### Phase 3: A/B-Testing
- Experimentelle Prompt-Varianten (z.B. kürzere vs. detaillierte Anweisungen)
- Token-Messung vor/nach (via `token-report.sh`)
- Versionierung: `v1`, `v1.1`, `v2` im Dateinamen

---

## Notizen für Prompt-Editoren

1. **Vor Änderung:** CHANGELOG.md updaten (Datum + Was ändert sich)
2. **Temperatur:** Konsistent über ähnliche Prompts (0.0=deterministisch, 0.3=normal, 0.5+=kreativ)
3. **JSON-Outputs:** Exact Feldnamen dokumentieren, Fallback-Values testen
4. **Länge:** Maximal 15 Zeilen; längere → mehrere Prompts splitten
5. **After Deploy:** `token-report.sh | grep <kategorie>` — Kosten-Baseline messen
