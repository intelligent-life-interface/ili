# Integration: Prompts aus Bibliothek laden

Schritt-für-Schritt Anleitung, wie Prompts aus der Bibliothek geladen werden (statt inline).

## Kurzanleitung

**Alte Weise (verstreut):**
```python
# brainstorm_service.py
SYSTEM_PROMPT = "Du bist ein kreativer..."  # Inline, schwer zu versionieren
```

**Neue Weise (zentral):**
```python
from prompts.loader import load_brainstorm_system
SYSTEM_PROMPT = load_brainstorm_system()  # Aus Bibliothek
```

## Schritt 1: Prompt dokumentieren

Datei anlegen: `prompts/brainstorm/system_prompt.md`

```markdown
# Brainstorm System Prompt

**ID:** `brainstorm/system_prompt`
...

## Text

```
Du bist ein kreativer...
```

## Changelog
- **2026-08-03:** Initial
```

**Wichtig:** Der `## Text`-Block muss mit ` ```-Fences` ummantelt sein!

## Schritt 2: In Code referenzieren

```python
from prompts.loader import load_prompt

# Variante A: Allgemein
system = load_prompt("brainstorm/system_prompt")

# Variante B: Shortcut (für häufige Prompts)
from prompts.loader import load_brainstorm_system
system = load_brainstorm_system()
```

## Schritt 3: Testen

```bash
cd ~/containers/dashboard
python3 -c "from prompts.loader import load_brainstorm_system; print(load_brainstorm_system())"
```

Sollte den Prompt-Text ausgeben.

## Schritt 4: Deploy

```bash
systemctl --user restart dashboard-api.service
```

Kein spezieller Reload nötig — die Prompts werden beim Service-Start einmal geladen und gecacht.

## Fallback-Handling

Der `loader.py` hat **zwei Sicherheits-Ebenen:**

1. **Datei nicht gefunden oder Parse-Fehler:** → Fallback aus `_FALLBACKS` nutzen
2. **Fallback auch nicht vorhanden:** → leerer String zurückgeben (+ Log-Warnung)

So bricht die App nie wegen fehlender Prompts. Die Logs zeigen aber sofort, wenn etwas schiefgeht.

## Versionierung

Prompts ändern → **CHANGELOG.md updaten**:

```markdown
## 2026-08-10

**Brainstorm System Prompt gekürzt**
- Emoji-Regel entschärft (vorher "sparsam", jetzt "wenn nötig")
- `brainstorm/system_prompt.md` angepasst

**Impact:** Marginal; User merken es nicht.
```

## Testing vor Prod-Rollout

1. **Lokal ändern:** `prompts/brainstorm/system_prompt.md` editieren
2. **Python-Test:** `python3 -c "from prompts.loader import load_brainstorm_system; ..."`
3. **Integration-Test:** Brainstorm im Test-Board öffnen, ein paar Turns machen
4. **Kosten-Check:** `token-report.sh --days 1 | grep brainstorm`
5. **Commit & Push** (wenn alles ok)

## Cache-Prewarming (optional)

Bei vielen Prompts kannst du sie beim App-Start alle preloaden:

```python
# brainstorm_service.py, am Ende der Initialisierung
from prompts import loader
_ = loader.load_brainstorm_system()
_ = loader.load_brainstorm_card()
# ... weitere Prompts
log.info(f"[init] Prompts gecacht: {len(loader._PROMPT_CACHE)} Einträge")
```

So sind alle Prompts im Memory sofort verfügbar (schneller als beim ersten Request).
