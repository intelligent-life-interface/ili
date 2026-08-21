# KI-Prompt-Audit — Dashboard

> Erstellt 2026-06-24 (Projekt „Kanban-KI-Optimierung", Karte 1).
> Methode: 3 parallele Lese-Agenten (Claude-Calls / Ollama-Calls / Kontext-Ballast).
> Preise Opus-Ref: Cache-Read $1,50/M · Cache-Write $18,75/M · Output $75/M.

## Kernbefund in einem Satz
Der mit Abstand grösste API-Token-Treiber ist **`chat_service.py` → das komplette Board-JSON (`indent=2`, alle internen Felder) im System-Prompt jedes Chat-Calls** (~9–13k Tokens/Call). Fast alle anderen KI-Tasks laufen bereits über **Ollama (gratis, lokal)** oder die **Abo-CLI-Bridge (Port 8950, kein API-Guthaben)**.

---

## A) Anthropic/Claude-Aufrufe (echte API-Tokens nur bei #1 & #4)

| # | Stelle | Modell | Zweck | Prompt-Inhalt | Grösse | cache_control |
|---|---|---|---|---|---|---|
| 1 | `app/services/chat_service.py:_build_system_context` | Sonnet 4.6 (API direkt) | Kanban-Chat-Assistent | **GANZES Board als json.dumps(indent=2)** + Boardliste + 10 History-Msgs | **>5k (9–13k)** | **ja** |
| 2 | `project_creator.py:generate_idea_cards` | Sonnet 4.6 (Abo-Bridge) | Ideenkarten brainstormen | Name+Desc+Tags + Format-Instruktion | <1k | nein (Bridge) |
| 3 | `project_creator.py:_generate_claude_md` | Sonnet 4.6 (Abo-Bridge) | CLAUDE.md generieren | Name+Desc+Tags | <1k | nein |
| 4 | `project_creator.py:_vision_title` (Fallback) | Haiku 4.5 (API direkt) | Projekttitel aus Foto | 1 Bild (base64) + 1 Satz | 1–5k (Bild) | nein |
| 5 | `auto_categorize.py:_ask_claude` | Haiku 4.5 (Abo-Bridge) | Projekte kategorisieren | alle „missing" Projekte als `id\|name\|tags` | 1–5k (skaliert) | nein |

**Wichtig:** 4 von 5 laufen über die **Abo-Bridge (8950)** = kein API-Guthaben, aber auch **kein Prompt-Caching möglich**. Echte API-Tokens nur bei #1 (Chat) und #4 (Vision-Fallback).

## B) Ollama-Aufrufe (lokal, gratis — entlasten Claude bereits)

| Stelle | Modell | Zweck | Bündelung | Grösse |
|---|---|---|---|---|
| `kanban_tagger.py:ollama_generate_tags` | gemma3:12b | Tags pro Karte | **N Calls (1/Karte!)** | <1k |
| `prio_suggester.py:_ai_rank` | gemma3:12b | Prio-Ranking | gebündelt | <1k |
| `prio_suggester.py:suggest_eisenhower` | gemma3:12b | Eisenhower-Quadrant | gebündelt | 1–5k |
| `related_finder.py:_ai_reasons` | gemma3:12b | verwandte Projekte | gebündelt (max 8, Jaccard-Vorfilter) | <1k |
| `dedup_finder.py:_ai_confirm` | gemma3:12b | Duplikat-Check | gebündelt | <1k |
| `kanban_ki_sortierer.py:_ollama_classify_batch` | gemma3:12b | Sortieren 10 Kat. | gebündelt (30/Batch) | mittel |
| `ki_explain_worker.py:_ollama_explain/_critiques` | **mistral (hart!)** | Erklären + Gegenargumente | **2 Calls/Karte** | mittel |
| `app/services/stream_service.py:ki_explain_stream` | gemma3:12b | Live-Erklärung | 1/Anfrage | mittel |
| `app/services/stream_service.py:analyse_bug_stream` | qwen2.5-coder | Bug-Analyse | 1/Anfrage | mittel |
| `app/services/ki_service.py:critique` | qwen2.5-coder | Gegenargumente | 1/Anfrage | <1k |

## C) Top-Token-Fresser (Kontext-Ballast, anbieterunabhängig)

| # | Stelle | Was mitgeschickt wird | Grösse | Trim-Vorschlag |
|---|---|---|---|---|
| 1 | `chat_service.py:50` `_build_system_context` | volles Board-JSON, alle Felder, `desc`+`description` doppelt | **9–13k/Call** | nur `{col: [{title,desc,status}]}`; `separators=(',',':')`; Done/Archiv weglassen → **~70 % weniger** |
| 2 | `ki_project_advisor.py:84` `_build_portfolio_context` | lädt manifest **+ jedes Board** von Platte, 1 Zeile/Board | 1–1,5k + voller Disk-Read | nur parent/sibling-Boards; Counts aus manifest statt alle Boards laden |
| 3 | `chat_service.py:32` Board-Liste | `id=name` für ≤25 Boards | ~200 | nur bei Board-Erstellung mitschicken |
| 4 | `kanban_tools.py` KANBAN_TOOLS | 8 Tool-Schemas | ~1k/Tool-Call | in gecachten System-Block (aktiver Chat sendet aktuell keine Tools) |
| 5 | `project_describer.py:222`, `kanban_tagger.py:70` | CLAUDE.md-Auszug / Kartentext | gekappt (1500/400) | bereits gut, läuft über Ollama |

**cache_control:** nur in `chat_helpers.py:42,55` (System-Block + letzte Msg ephemeral). Greift für #1, **aber Cache bricht** weil das Board-JSON sich bei jeder Änderung ändert → Finding C#1 trimmen verbessert Input-Tokens **und** Cache-Trefferquote.

---

## Konsequenzen für die übrigen Karten
- **Kontext-Trimmer (Karte 2):** = Finding C#1. **Grösster Hebel**, zuerst angehen.
- **Ollama-Routing (Karte 3):** weitgehend **schon erfüllt** — fast alles läuft auf Ollama. Rest-To-do: `ki_explain_worker` nutzt hartkodiert `mistral` statt `ai_config`.
- **System-Prompt-Caching (Karte 4):** Mechanik **existiert** (chat_helpers); Nutzen steigt erst mit stabilem, getrimmtem Prefix (Karte 2 zuerst).
- **Batch-Modus (Karte 8):** konkreter Treffer = `kanban_tagger` (1 Call/Karte → bündeln) + `ki_explain_worker` (2 Calls/Karte → 1 Call).
- **Token-Counter (Karte 6):** `cost_service.py` existiert bereits als Ansatzpunkt.

---

## Umsetzungs-Log

### Karte 2 „Kontext-Trimmer" — erledigt 2026-06-24
**Fix:** Neue Funktion `_slim_board()` in `app/services/chat_service.py` ersetzt `json.dumps(board, indent=2)` im Chat-System-Prompt. Serialisiert pro Spalte nur `[id] Titel :: desc`; Erledigt/Archiv-Spalten ohne `desc`; interne Felder (label/effort/priority/refs/category/abschluss/…) und die `desc`/`description`-Dublette fallen weg.

**Messung (reale Boards, alt = json.dumps indent=2):**
| Board | alt | slim | Ersparnis |
|---|---|---|---|
| dashboard (148 Karten) | ~9 700 Tok | ~2 640 Tok | **−73 %** |
| dev-log | ~8 900 | ~300 | −97 % |
| ideen | ~8 800 | ~3 300 | −62 % |
| immobilienverwaltung (desc-lastig) | ~13 000 | ~10 100 | −23 % |

Alle Karten-IDs bleiben erhalten (Tool-Use unverändert), `desc` offener Karten voll erhalten → kein Qualitätsverlust. Service `dashboard-api.service` neugestartet, live.

**Audit-Korrektur:** Die ursprünglich als Konsumenten genannten Ollama-Pfade (dedup_finder, related_finder, kanban_ki_sortierer, prio_suggester) waren **bereits schlank** (Jaccard-Vorfilter, nur Titel/Tags) — kein `slim_card` nötig. Der Trim war nur bei `chat_service.py` (echte API-Tokens) erforderlich.

### Karte 8 „Batch-Modus" — erledigt 2026-06-24
**Fix:** `kanban_tagger.py` machte **1 Ollama-Call pro Karte** (+0,8 s Pause je Karte). Neu: `ollama_generate_tags_batch()` taggt bis `BATCH_SIZE=10` Karten in **einem** Call via Ollama-**JSON-Modus** (`format:json`, robustes Parsen). `process_board()` sammelt taggbare Karten, schickt sie gebündelt, mit **Einzel-Fallback** pro Karte ohne Batch-Ergebnis. Gemeinsamer `_clean_tags()`-Helper (DRY). Toter `process_card`-Pfad entfernt.

**Effekt (Ollama = lokal/gratis, daher kein API-$, aber):**
- fixe ~80-Token-Instruktion wird **1× statt N×** geschickt (bei 10 Karten: −90 % Instruktions-Overhead);
- **1 Pause/Batch statt 1/Karte** → bei 10 Karten ~7 s schneller;
- weniger HTTP-Roundtrips/lokale Last.

**Live-Test:** 3 Karten in 1 Call (16 s), 3/3 valides JSON mit sinnvollen Tags. Konfigurierbar via `TAGGER_BATCH`. Greift beim nächsten Tagger-Lauf (kein Daemon-Neustart nötig).
