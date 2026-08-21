# Prompt-Template Bibliothek

Zentrale, kuratierte Sammlung aller KI-Prompts für das Dashboard.

**Ziele:**
- Duplicates identifizieren und konsolidieren
- Prompts versioniert halten (Änderungen trackbar)
- Minimale, fokussierte Inhalte (Token-Sparen)
- Prompt-Caching vorbereiten (siehe `system_prompt_caching_design.md`)

## Struktur

```
prompts/
├── README.md (diese Datei)
├── brainstorm/
│   ├── system_prompt.md        # Rolle-Definition für den Brainstorm-Partner
│   ├── card_from_idea.md       # Idee → Kanban-Karte (JSON-Output)
│   ├── description_from_convo.md # Ganzes Gespräch → Projekt-Beschreibung
│   └── cards_from_plan.md      # Gesprächs-Plan → mehrere Karten (JSON-Array)
├── project_creation/
│   ├── correct_name.md         # Tippfehler-Korrektur (Anti-Fantasie)
│   ├── vision_title.md         # Foto → Projekt-Titel
│   ├── vision_tags.md          # Foto → Tags
│   ├── initial_ideas.md        # Projekt-Brainstorm (Initial-Karten)
│   └── generate_claude_md.md   # CLAUDE.md-Skeleton
├── bug_analysis/
│   └── bug_triage.md           # Log-Fehler → Klassifizierung + Fix-Idee
└── other/
    ├── constants.md            # Shared Patterns (JSON-Format, Sprache)
    └── CHANGELOG.md            # Versions-/Änderungshistorie der Prompts
```

## Prompt-Status & Tracking

| Prompt | Modul | Häufigkeit | Stabilität | Caching-Phase | Notizen |
|--------|-------|-----------|-----------|---|---------|
| **Brainstorm System** | `brainstorm_service.py:35` | Konstant | Sehr hoch | Phase 1 | Anti-Fantasie-Regel, Deutsch |
| **Idea→Card** | `brainstorm_service.py:194` | Je Idee | Sehr hoch | Phase 1 | JSON-Format, kurze Title |
| **Convo→Desc** | `brainstorm_service.py:317` | Pro Projekt (selten) | Hoch | Phase 2 | 2-4 Sätze, kein Bulleting |
| **Convo→Cards** | `brainstorm_service.py:367` | Pro Plan (selten) | Hoch | Phase 2 | JSON-Array max 8 Items |
| **Bug-Triage** | `bug_fixer.py:176` | Täglich (Auto) | Mittel | Phase 2 | Severity + Cause + Fix |
| **Correct Name** | `project_creator.py:~250` | Pro Projekt | Hoch | Phase 2 | TBD: prompt noch auslesen |
| **Vision Title** | `project_creator.py:~280` | Pro Foto | Hoch | Phase 2 | TBD: prompt noch auslesen |
| **Vision Tags** | `project_creator.py:~300` | Pro Foto | Hoch | Phase 2 | TBD: prompt noch auslesen |

## Richtlinien beim Schreiben von Prompts

1. **Sprache:** Deutsch (für Brainstorm/Projekt-Kontext), explizit im Prompt setzen
2. **Länge:** Maximal 15 Zeilen; längere Anweisungen → mehrere Prompts statt eine lange
3. **Struktur:** `<Rolle> + <Aufgabe> + <Format> + <Anti-Muster>`
4. **JSON-Outputs:** Exakt spezifizieren: Feldnamen, erlaubte Werte, Array vs. Objekt
5. **Fallback:** Jeder Prompt braucht einen sauberen Fallback (kein KI-Fehler = Lost-Data)

## Evolving & Feedback Loop

- **Monats-Review:** Prompt-Änderungen im Review dokumentieren → CHANGELOG.md aktualisieren
- **A/B-Test:** Änderungen vor Rollout an Testboard bewerten
- **Token-Messung:** Nach Änderung `token-report.sh | grep <kategorie>` für Kosten-Baseline
- **Duplikate:** Vierteljährlich auf Konsolidierungs-Chancen scannen

## Integration in Code

Statt Prompts inline zu definieren, laden sie aus dieser Bibliothek:

```python
# ALT (verstreut, schwer zu versionieren)
SYSTEM_PROMPT = "Du bist ein kreativer..."

# NEU (zentral, trackbar)
from prompts.loader import load_prompt
SYSTEM_PROMPT = load_prompt("brainstorm/system_prompt")
```

Ein neues Modul `prompts/loader.py` stellt sicher, dass:
- Prompts gecacht werden (nicht auf jeder Initialisierung neu eingelesen)
- Änderungen live greifen (Test: systemd-Unit-Restart)
- Fallback auf Alt-Wert (Fehler bei Laden = Alte Version nutzen)
