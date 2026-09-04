# Publish-Gate Checkliste

**Vor JEDER Veröffentlichung:** Diese Checkliste Punkt für Punkt durchgehen und abhaken. Das Repo darf nur public geschaltet werden, wenn alle Punkte erfüllt sind.

> **Gültig ab:** 24.08.2026  
> **Zuletzt überprüft:** —  
> **Letzte Veröffentlichung:** v0.1.7 (22.08.2026)

## 1. ✅ Privacy-Scanner: 0 Funde

```bash
# Im Release-Container (Werkstatt):
cd ~/Projekte/ili-release/release-container
git add -A && git commit -m "Release: <version> — <beschreibung>"
python3 ~/Projekte/privacy-scanner/scan_repo.py --repo . --config ~/Projekte/privacy-scanner/patterns.conf
```

**Bestätigung:** Scanner meldet `0 Funde` oder nur `.privacyignore`-Einträge.

---

## 2. ✅ Gegenpruefung: alle Dateien inkl. Dokumentation sauber

Die Suchbegriffe (Eigennamen, Klarname, Home-Pfad) stehen bewusst nicht wörtlich in
dieser Checkliste — sonst würde die Gegenprüfung diese Datei selbst als Fund melden.
Kanonische Liste: Variable `GEGEN_PAT` in `~/bin/ili-sync-public.sh`.

```bash
# Führt exakt die GEGEN_PAT-Prüfung aus ili-sync-public.sh manuell aus (ohne Sync):
~/bin/ili-sync-public.sh --dry-run
# → Zeile "Gegenpruefung sauber." = 0 Treffer

git grep -i "priority_widget"
# → Nur das Feature (app/api/priority_widget.py, app/services/, html/js/, README-Beispiel)
# Wenn priority_widget NICHT umbenannt oder entfernt: abbrechen, Entscheidung treffen
```

**Laufzeitdaten & Secrets:**
```bash
git ls-files | grep -E "(html/photos|boards|data|\.privacyignore|config\.env|\.env$)" \
  && echo "⚠️ FEHLER: Laufzeitdaten in der Versionskontrolle" || echo "✓ Sauber"
```

**Zweck:** Sicherstellen, dass der public-Repo saubere Release-Dateien enthält, nicht die Werkstatt-Infrastruktur.

---

## 3. ✅ Geschichte: Commit-Zähler steigt pro Sync um genau 1

**Wichtig — Korrektur 24.08.2026:** `ili-sync-public.sh` setzt das public-Repo NIE zurück
und squasht nicht. Pro Veröffentlichung kommt genau EIN neuer Commit oben drauf; die
Gesamtzahl der Commits im Repo wächst also mit jedem Release (aktuell z.B. 22, nicht 1).
Ein einzelner Commit "pro Release" heisst NICHT "ein Commit im ganzen Repo".

```bash
cd ~/Projekte/ili-release/public
before=$(git log --oneline | wc -l)

# ... ~/bin/ili-sync-public.sh "Release vX.Y.Z: <beschreibung>" laufen lassen ...

after=$(git log --oneline | wc -l)
# → after MUSS genau before+1 sein: ein neuer Commit für DIESES Release,
#   keine Doppel-Pushes, keine fremden Commits dazwischen
git log -1 --format='%H %s'
# → Message muss die erwartete Release-Beschreibung tragen
```

**Falls die Prüfung abweicht:**
- 0 neue Commits: Sync ist fehlgeschlagen (nicht gepusht) — Ursache klären, NICHT weiterschalten
- >1 neuer Commit: Es ist etwas Fremdes ins Repo gekommen (siehe Tor 2: nur der Sync darf schreiben) — Ursache klären
- **NIE** mit `push --force` oder Neuaufbau "reparieren" — das GitHub-Ruleset auf `main` verbietet
  Force-Push und Löschen genau deshalb (siehe CLAUDE.md „Das öffentliche Repo ist gesperrt")
- Stimmt alles: ✓ Weitermachen

---

## 4. ✅ Branches: Keine Arbeitsbranche auf dem Remote

```bash
# Prüfe, dass nur 'main' existiert:
cd ~/Projekte/ili-release/public
git branch -r
# → Sollte nur 'origin/main' zeigen

# Wenn andere Branches vorhanden: löschen oder als stale melden
```

**Zweck:** Ein Fremder-Klon soll KEINE Arbeitsbranches mitbringen, die den Sync-Prozess durcheinander bringen.

---

## 5. ✅ Tags: Keine Tags auf entfernte Objekte

```bash
git tag -l
# Alle Tags sollten auf 'main' oder früher zeigen:
for tag in $(git tag); do
  ref=$(git rev-list -n1 "$tag")
  main_ref=$(git rev-parse main)
  if ! git merge-base --is-ancestor "$ref" "$main_ref"; then
    echo "⚠️ Tag $tag zeigt auf dangling Commit (nicht in main)"
  fi
done
```

**Zweck:** Der public-Repo soll nur Tags enthalten, die im aktuellen Release enthalten sind.

---

## 6. ✅ Packages-Sichtbarkeit: Bewusst gesetzt

**Vor dem Public-Schalten der Repo:**

```bash
# GitHub CLI Check:
gh api repos/Toa1984/ili-public --jq '.private'
# → true (privat)

# Packages auf ghcr.io:
# 1. ghcr.io/toa1984/ili
# 2. ghcr.io/toa1984/ili-web
# 3. ghcr.io/toa1984/ili-terminal
# Alle MÜSSEN privat sein (erben von Repo-Sichtbarkeit oder explizit Paketebene)
```

**Freischaltung (wenn Manager entscheidet):**
1. Repo: Einstellungen → Visibility → Public
2. Packages (jeweils einzeln):
   - ghcr.io/toa1984/ili → Package settings → Public
   - ghcr.io/toa1984/ili-web → Package settings → Public
   - ghcr.io/toa1984/ili-terminal → Package settings → Public

**NIE** via Automation; immer manuell + bewusster Entscheid pro Schalter (6 Total).

---

## 7. ✅ Ausdrückliche Freigabe (schriftlich, mit Datum)

**Form:** Eine Notiz/Commit-Message mit folgenden Informationen:

```
Veröffentlichung: v0.1.X

Freigabe durchgeführt am: YYYY-MM-DD HH:MM UTC
Freigeben durch: [Name/Entity]

Prüfung:
- [ ] Privacy-Scanner: 0 Funde
- [ ] Gegenpruefung (Eigennamen, Pfade, Secrets): sauber
- [ ] Historie: Commit-Zähler genau um 1 gestiegen (before+1)
- [ ] Branches: nur main
- [ ] Tags: alle auf main oder älter
- [ ] Packages: Sichtbarkeit geprüft
- [ ] Code-Review: keine P0/P1-Befunde offen

Nächste Schritte:
- Packages auf public schalten (Manual)
- Repo auf public schalten (Manual)
- QUICKSTART + docs/README überprüfen
```

**Wo:** Commit-Message in der Werkstatt (`release-container`), Notiz auf der Kanban-Karte, oder eine separate `RELEASE-NOTES-vX.Y.Z.md`.

---

## Rundown (Kurzform)

Vor dem Public-Schalten:

```bash
# In der Werkstatt:
cd ~/Projekte/ili-release/release-container
git add -A && git commit -m "Release: v0.1.X — <beschreibung>"

# Privacy-Scan:
python3 ~/Projekte/privacy-scanner/scan_repo.py --repo . --config ~/Projekte/privacy-scanner/patterns.conf

# Gegenpruefung (GEGEN_PAT aus ili-sync-public.sh, siehe Punkt 2 oben):
~/bin/ili-sync-public.sh --dry-run
echo "priority_widget: $(git grep -i priority_widget | wc -l) Treffer (sollte nur Feature sein)"

# Public-Repo VORHER: Commit-Zahl merken
cd ~/Projekte/ili-release/public
before=$(git log --oneline | wc -l)

# Sync nach public:
~/bin/ili-sync-public.sh "Release v0.1.X: <beschreibung>"

# Public-Repo NACHHER prüfen:
after=$(git log --oneline | wc -l)
echo "$after == $((before+1)) ?"  # → MUSS genau +1 sein, nicht 1
git branch -r                      # → MUSS nur origin/main sein

# GitHub Package-Visibility prüfen:
gh api repos/Toa1984/ili-public --jq '.private'  # → true

# (Manager entscheidet) → Packages + Repo public schalten (manuell)
```

---

## Sperrvermerk

**Diese Checkliste ist die Entscheidungsgrundlage.** Sobald alle Punkte grün sind und die ausdrückliche Freigabe vorliegt, darf (und SOLL) der Manager den Repo öffentlich machen. Nicht nachher, sondern dann.

Solange EINE Punkt rot ist oder eine Entscheidung aussteht (z.B. priority_widget: umbenennen oder entfernen): **NICHT VERÖFFENTLICHEN**.
