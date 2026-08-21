# Bug Analysis: Log → Triage + Fix

**ID:** `bug_analysis/bug_triage`
**Modul:** `jobs/bug_fixer.py:176`
**Output:** JSON-Objekt
**Stabilität:** Mittel (Schwellwerte ändern sich)
**Cache-Phase:** 2 (später, wenn Ollama/Claude-Balance stabil)

## System Prompt

```
Du bist ein erfahrener DevOps-/Python-Entwickler und triagierst EINEN Fehler aus den Server-Logs eines rootless-Podman-Homeservers. Entscheide zuerst, ob es eine echte, handlungswürdige Aufgabe ist (relevant=true) oder nur Rauschen/transient/Fremdsystem (relevant=false). relevant=false z.B. bei: vorübergehenden Verbindungsabbrüchen die sich selbst erholen, Health-Checks, Client-Disconnects, leerem KI-Guthaben, Fremd-API-Ausfällen ohne Code-Bezug, reinen Info-/Debug-Zeilen.

Antworte AUSSCHLIESSLICH als JSON-Objekt (kein Markdown, keine Code-Fences):

{"relevant": true|false, "severity": "low|med|high", "ursache": "<eine Zeile, deutsch>", "stelle": "<Datei/Funktion aus dem Traceback, sonst 'unklar'>", "fix": "<2-5 Zeilen minimaler, konkreter Lösungsvorschlag, deutsch>"}
```

## User Prompt

```
Dienst: {service}
Log-Quelle: {source_label}
Zeitstempel: {ts}
Fehler: {headline}

Log-Kontext:
{context}  # Max 1800 Zeichen
```

## Eigenschaften

- **Output:** JSON-Objekt (NICHT Array)
- **Felder:**
  - `relevant`: true/false — echte Aufgabe oder Rauschen?
  - `severity`: `low|med|high` — Priorität
  - `ursache`: Eine Zeile (Deutsch), z.B. "Connexion timeout zu MQTT-Broker"
  - `stelle`: Datei/Funktion oder "unklar"
  - `fix`: 2-5 Zeilen konkreter Lösungsvorschlag (Deutsch)
  - `sicher` (optional): Boolean — nur bei Ollama-Triage (true=Modell sicher, false=unsicher → entscheidungs-Karte)
- **Ziel:** Fehler klassifizieren (relevant/severity) + Fix-Idee vorschlagen
- **Fallback:** Bei Parse-Fehler: `relevant=True, severity=med, sicher=False` (Karte wird angelegt, nicht gefiltert)

## Codesystematik

- **Two-Mode Execution:**
  1. **Ollama (Standard):** `_ollama_classify_and_fix()` — lokal, gratis, täglich Auto-Triage
  2. **Claude-Abo (Manual):** `_classify_and_fix()` — nur auf ENTSCHEIDUNGS-Karten (teuer, bessere Qualität)
- Temperature: 0.1 (deterministisch)
- Max-Tokens: 400 (Ollama), 450 (Claude)
- Timeout: 120s
- Parsing: JSON zwischen `{` und `}` (robust gegen Markdown-Noise)

## Changelog

- **2026-08-03:** Initial dokumentiert
- **History:** 11.07.26 — Ollama wurde Standard (früher nur Claude-Abo)
