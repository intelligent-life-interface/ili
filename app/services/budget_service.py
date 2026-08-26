"""Budget-Service — Claude-Token-Wochenbudget mit Tag/Nacht-Fenstern (F2.1).

Schnittstelle
-------------
usage_week(week=None) -> dict
    {week: '2026-Www', tokens_used: int, by_source: {cli: int, dashboard: int},
     by_day: {ISO-Datum: int}}
    Quellen: cost_service._scan_cli_sessions + _scan_dashboard_log (wiederverwendet,
    NICHT kopiert). ISO-Woche ab Montag.

    `tokens_used` sind **gewichtete** Tokens (_TOKEN_WEIGHTS), keine Roh-Summe:
    * Fund 29.07.26: reines input+output zählte nur ~0,7% des realen Verbrauchs —
      Cache-Read dominiert bei hoher Cache-Hit-Quote; ohne ihn greift kein Budget-Gate,
      das darauf aufbaut (fable_gate.py/priority_gate.py im kanban-automat).
    * Fund 05.08.26: Cache-Read 1:1 mitzählen überzeichnet umgekehrt um ~Faktor 6 —
      gemessen 132% lokal gegen 21% in der Claude-App. Das Abo gewichtet Cache-Read
      nach Preis viel niedriger. Ein einziger intensiver Tag sprengte so das Wochenlimit
      und der Kanban-Automat sperrte sich tagelang lautlos selbst aus (Tages-Tranche 0,
      keine Fehlermeldung). Seither Gewichtung nach Preisverhältnis ⇒ die Skala von
      `week_pct` entspricht wieder der Prozentanzeige der Claude-App.
    * Fund 11.08.26: the InfluxDB integration (below, "Entscheidung D") produced garbage
      despite the `[InfluxDB]` tag in `reason` — `_query_influx_usage()` took the first
      Flux-CSV token that parsed as float, which is almost always the `table` column
      (value "0"), not `_value`. `pct_now` was therefore practically always 0.0, no
      matter what InfluxDB actually reported (real week usage 54% per manual check, display
      0.0%). `pct_start_of_day` was also hardcoded to 0.0 — had pct_now been correct,
      the ENTIRE week's usage would have been wrongly counted as "used today" and the
      day window would have blocked far too aggressively. Fix: both values now come
      from `claude_limits_service.py` (already correct `csv.DictReader` parsing there,
      used by `/api/claude-limits`) instead of the broken parsing logic that used to
      live here. Opus review of that fix (same day) then caught that falling back to
      pct_start_of_day=0.0 whenever no data point exists yet for today would recreate
      the exact same bug in the ~15min after local midnight — see `_query_influx_usage`
      docstring for the actual (stricter) fallback behaviour.

    * 26.08.2026: `claude_limits_service` is OPTIONAL (the release cleanup 97b8371
      dropped the home-stack-only InfluxDB reader, v0.1.11 crash-looped on the hard
      import). Missing module ⇒ source="estimate" only, never an ImportError.

check_allowance(now=None) -> dict
    {allowed: bool, week_pct: float, window_pct: float, day_allowance_tokens: int,
     today_used: int, window: {from, to, max_pct}, reason: str, source: str}
    Logik: rest = week_limit - verbraucht_vor_heute; Tages-Tranche = rest / Resttage
    (inkl. heute + budget_reserve_days virtuelle Puffertage); Fenster aus budget_windows
    (Mitternachts-Überlauf unterstützt); erlaubt solange today_used < Tranche * max_pct/100.
    week_limit<=0 oder budget_enforce=false → immer allowed (reason dokumentiert).

    source = "usage" (echte /usage-Werte aus InfluxDB) oder "estimate" (Schätzung aus Logs).

Config-Keys (ai_config.json via config_handler):
    budget_week_tokens, budget_windows, budget_enforce, budget_reserve_days
    (Reserve, Default 1: Montag wird durch 8 statt 7 geteilt, sodass am Wochenende
    ca. ein Tag Budget übrig bleibt statt komplett von den Nacht-Läufen verbraucht zu werden.)
"""
import logging
from datetime import date, datetime, timezone

from app.services import cost_service  # Scan-Funktionen via Attribut (monkeypatch-bar)
from app.services.ttl_cache import TTLCache
from config_handler import _load_ai_config

log = logging.getLogger("dashboard.services.budget")

# Optional module (26.08.2026, cleanup commit 97b8371 dropped it from the release):
# claude_limits_service reads the home-stack-only InfluxDB bucket `claude_limits`
# (fed by the claude-limit-watcher, which is NOT shipped). Without it every usage
# query falls back to the log-based estimate — the app must never fail to import
# because of it (v0.1.11 crash-looped exactly that way). Kept as a module attribute
# so tests can monkeypatch it and a home-stack can still provide the module.
try:
    from app.services import claude_limits_service
except ImportError:
    claude_limits_service = None
    log.debug("claude_limits_service not available — budget source 'usage' disabled, "
              "using the log-based estimate only")

# Single-Flight-Caches gegen Cache-Stampede (opt_cache_stampede_0806): schützen die
# dünne lokale Memo (Double-Checked Locking). Der eigentliche Datei-Scan liegt seit
# 06.08.26 EINMAL in cost_service.get_all_calls (dort ebenfalls gelockt) — budget
# konsumiert nur noch dessen Ergebnis, statt dieselben Dateien ein zweites Mal zu scannen.
_calls_cache_ttl = TTLCache(ttl_seconds=60.0)

# InfluxDB-Cache für echte /usage-Werte (Entscheidung D: nutze echte Auslastung statt Schätzung).
# Mit allow_none=True, weil auch ein None-Ergebnis (InfluxDB-Fehler) gecacht werden soll,
# um nicht jedes Mal die volle Abfrage zu fahren (Fund 12.08.26, card_286d49dc).
# Note: TTLCache unterstützt nur eine einzige TTL — wir nehmen konservativ die kürzere
# (15s statt 60s für Erfolg), damit eine InfluxDB-Erholung zügig gesehen wird.
_influx_cache_ttl = TTLCache(ttl_seconds=15.0, allow_none=True)
# claude-limit-watcher.timer pollt alle 15min (OnCalendar=*:05/15) — 20min Schwelle
# toleriert einen verpassten Tick, verwirft aber (anders als die alten 60min = 4
# Ticks) deutlich schneller wirklich veraltete Daten. Fund 12.08.26 (card_544ceaa5).
_INFLUX_STALENESS_LIMIT_S = 1200  # 20 min — älter = Fallback auf Schätzung

# Gewichte je Token-Art, normiert auf Input=1.0 (Anthropic-Preisverhältnis, gilt
# modellübergreifend: Output 5x, Cache-Write 1.25x, Cache-Read 0.1x Input-Preis).
# Ergebnis = "Input-Token-Äquivalente" — dieselbe Skala, in der das Abo-Wochenlimit
# zählt. NICHT auf 1.0 zurücksetzen (s. Modul-Docstring, Fund 05.08.26): Cache-Read
# 1:1 zu zählen überzeichnet den Verbrauch um ~Faktor 6 und würgt den Automaten ab.
_TOKEN_WEIGHTS = {
    "input_tokens": 1.0,
    "output_tokens": 5.0,
    "cache_write_tokens": 1.25,
    "cache_read_tokens": 0.1,
}


# Toleranzband gegen falsch erkannte Wochen-Resets (Fund 12.08.26, card_286d49dc,
# s. _query_influx_usage): nur ein deutlicher Abfall (>5 Prozentpunkte) ODER ein
# pct_now nahe 0 gilt als echter Reset — kleinere Schwankungen (Rundung) nicht.
_WEEKLY_RESET_DROP_THRESHOLD_PCT = 5.0
_WEEKLY_RESET_LOW_PCT = 10.0


def _parse_influx_ts(ts: str | None) -> datetime | None:
    """Parses an InfluxDB `_time` string (RFC3339, e.g. "...Z") into an aware datetime."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _query_influx_usage() -> dict | None:
    """Reads pct_now (latest point) + pct_start_of_day (first point of today) for the
    "seven_day" window via claude_limits_service (correct CSV parsing there, see
    Fund 11.08.26 above — no more manual parsing here).

    Falls back to None (caller uses the estimate branch instead) whenever the data
    can't be trusted: no data point yet, the latest point is older than
    _INFLUX_STALENESS_LIMIT_S, or there's no point yet for today — silently assuming
    pct_start_of_day=0.0 in that last case would recreate the exact "whole week counted
    as today" bug from Fund 11.08.26 whenever this runs in the ~15min after local
    midnight (before the watcher's next tick) or after an overnight watcher outage.

    Returns: {pct_now: float, pct_start_of_day: float, last_update_utc: str} or None.
    """
    if claude_limits_service is None:
        log.debug("_query_influx_usage: claude_limits_service not available — "
                  "falling back to estimate")
        return None
    try:
        latest = claude_limits_service.latest_claude_limits()
        seven_day = latest.get("seven_day") or {}
        pct_now = seven_day.get("used_pct")
        if pct_now is None:
            log.debug("_query_influx_usage: no seven_day.used_pct in InfluxDB")
            return None

        latest_ts = _parse_influx_ts(seven_day.get("ts"))
        if latest_ts is None:
            log.debug("_query_influx_usage: latest point has no parseable timestamp")
            return None
        age_s = (datetime.now(timezone.utc) - latest_ts).total_seconds()
        if age_s > _INFLUX_STALENESS_LIMIT_S:
            log.warning("_query_influx_usage: latest point is %.0fs old (limit %ds) — "
                        "falling back to estimate", age_s, _INFLUX_STALENESS_LIMIT_S)
            return None

        pct_start_of_day = claude_limits_service.used_pct_at_start_of_day("seven_day")
        if pct_start_of_day is None:
            log.debug("_query_influx_usage: no data point yet for today — falling back "
                      "to estimate (see docstring, avoids Fund 11.08.26 regression)")
            return None
        drop = pct_start_of_day - pct_now
        if drop > 0:
            if drop > _WEEKLY_RESET_DROP_THRESHOLD_PCT or pct_now < _WEEKLY_RESET_LOW_PCT:
                # Weekly plan reset happened intraday (~Sunday) — pct_start_of_day still
                # reflects the OLD week (near its limit), pct_now the fresh new one.
                # Treat today as starting from 0, not from a stale pre-reset high value.
                log.info("_query_influx_usage: pct_start_of_day (%.1f%%) > pct_now (%.1f%%) — "
                          "weekly reset detected, treating today as starting at 0%%",
                          pct_start_of_day, pct_now)
                pct_start_of_day = 0.0
            else:
                # Fund 12.08.26 (card_286d49dc): jede minimale Abnahme (z.B. Anthropic-
                # Rundung 54.3→54.2) wurde bisher GENAUSO wie ein echter Reset behandelt
                # → pct_start_of_day=0.0 kippte den GESAMTEN Wochenverbrauch in "heute".
                # Unter der Schwelle ist es kein Reset, nur Rauschen: auf pct_now klemmen
                # (today_used bleibt 0, kein künstlicher Reset-Sprung).
                log.debug("_query_influx_usage: pct_start_of_day (%.1f%%) minimal über "
                          "pct_now (%.1f%%, Delta %.1f <= %.1f) — kein Reset, klemme auf pct_now",
                          pct_start_of_day, pct_now, drop, _WEEKLY_RESET_DROP_THRESHOLD_PCT)
                pct_start_of_day = pct_now

        log.info("_query_influx_usage: pct_now=%.1f%% pct_start_of_day=%.1f%% (from InfluxDB)",
                  pct_now, pct_start_of_day)
        return {
            "pct_now": pct_now,
            "pct_start_of_day": pct_start_of_day,
            "last_update_utc": latest_ts.isoformat(),
        }
    except Exception as e:
        # Covers claude_limits_service.ClaudeLimitsError (InfluxDB unreachable /
        # not configured) as well as anything unexpected — both mean "use estimate".
        log.debug("_query_influx_usage: InfluxDB usage unavailable (%s: %s) — "
                  "falling back to estimate", type(e).__name__, e)
        return None


def _get_usage_from_influx_uncached() -> dict | None:
    """Interne Hilfsfunktion für _get_usage_from_influx() — wird vom TTLCache aufgerufen."""
    result = _query_influx_usage()
    if result:
        result["source"] = "usage"
    return result


def _get_usage_from_influx() -> dict | None:
    """Cached InfluxDB-Abfrage. Rückgabe: {pct_now, pct_start_of_day, source: "usage"} oder None.

    Mit TTLCache und allow_none=True, um auch None-Ergebnisse zu cachen (InfluxDB-Ausfall).
    Verhindert, dass JEDER Aufruf die volle, seriell hinter dem Lock hängende Abfrage
    neu auslöst (card_286d49dc). TTL konservativ auf 15s (shorter of 60s success / 15s
    failure) gesetzt, damit eine InfluxDB-Erholung zügig gesehen wird.
    """
    return _influx_cache_ttl.get(_get_usage_from_influx_uncached)


def _weighted_tokens(call: dict) -> int:
    """Gewichtete Token-Summe eines Calls (Input-Äquivalente, s. _TOKEN_WEIGHTS)."""
    return int(sum(call.get(field, 0) * weight
                   for field, weight in _TOKEN_WEIGHTS.items()))


def _all_calls_uncached() -> list:
    """Interne Hilfsfunktion für _all_calls() — wird vom TTLCache aufgerufen."""
    all_calls = cost_service.get_all_calls()
    log.debug("[Budget] %d Calls aus cost_service.get_all_calls übernommen", len(all_calls))
    return all_calls


def _all_calls() -> list:
    """Alle Claude-Calls (CLI + Dashboard), aus dem GEMEINSAMEN Scan von cost_service.

    Dünne 60s-Memo mit Single-Flight via TTLCache; die teure Datei-Arbeit macht
    `cost_service.get_all_calls()` (Single Source of Truth, dort ebenfalls gelockt).
    """
    return _calls_cache_ttl.get(_all_calls_uncached)


def _iso_week_of(d: date) -> str:
    """ISO-Jahr+Woche, z.B. '2026-W24' (Woche beginnt Montag)."""
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def usage_week(week: str | None = None) -> dict:
    """Gewichteter Token-Verbrauch einer ISO-Woche, nach Quelle und Tag."""
    if not week:
        week = _iso_week_of(date.today())

    tokens_used = 0
    by_source = {"cli": 0, "dashboard": 0}
    by_day: dict = {}

    for call in _all_calls():
        ts = call.get("ts", "")
        try:
            d = date.fromisoformat(ts[:10])
        except (ValueError, TypeError):
            continue
        if _iso_week_of(d) != week:
            continue
        tokens = _weighted_tokens(call)
        tokens_used += tokens
        src = "cli" if call.get("source") == "claude-code" else "dashboard"
        by_source[src] += tokens
        day = d.isoformat()
        by_day[day] = by_day.get(day, 0) + tokens

    log.info("[Budget] Woche %s: %d Tokens (cli=%d, dashboard=%d)",
             week, tokens_used, by_source["cli"], by_source["dashboard"])
    return {"week": week, "tokens_used": tokens_used,
            "by_source": by_source, "by_day": dict(sorted(by_day.items()))}


def _find_window(hour: int, windows: list) -> dict:
    """Erstes Fenster das die Stunde abdeckt; from>to = über Mitternacht."""
    for w in windows:
        f, t = int(w.get("from", 0)), int(w.get("to", 24))
        if f < t:
            if f <= hour < t:
                return w
        elif f > t:  # Mitternachts-Überlauf, z.B. 22-10
            if hour >= f or hour < t:
                return w
        else:  # from == to → ganztägig
            return w
    return {"from": 0, "to": 24, "max_pct": 100}


def check_allowance(now: datetime | None = None) -> dict:
    """Prüft ob Claude-Nutzung im aktuellen Budget-Fenster noch erlaubt ist.

    Nutzt echte /usage-Werte aus InfluxDB wenn verfügbar + nicht älter als
    _INFLUX_STALENESS_LIMIT_S (20min); Fallback auf Token-Schätzung wenn
    InfluxDB unerreichbar/veraltet.
    """
    if now is None:
        now = datetime.now()

    cfg = _load_ai_config()
    week_limit = int(cfg.get("budget_week_tokens", 0) or 0)
    windows = cfg.get("budget_windows") or []
    enforce = bool(cfg.get("budget_enforce", True))

    # Versuche echte Werte aus InfluxDB (Entscheidung D)
    source = "estimate"  # Default
    influx_data = _get_usage_from_influx()
    if influx_data:
        # Nutze echte Prozentsätze statt Schätzung
        pct_now = influx_data["pct_now"]
        pct_start_of_day = influx_data["pct_start_of_day"]
        source = influx_data.get("source", "usage")

        # Berechne Token aus Prozentsätzen
        today_used_float = max(0.0, week_limit * (pct_now - pct_start_of_day) / 100.0)
        today_used = int(today_used_float)
        used_before_today = int(week_limit * pct_start_of_day / 100.0)
        week_pct = pct_now
        log.info("[Budget] Quelle=InfluxDB: pct_now=%.1f%% pct_start=%.1f%% → "
                "today_used=%d used_before=%d", pct_now, pct_start_of_day, today_used, used_before_today)
    else:
        # Fallback auf alte Token-Schätzung
        usage = usage_week(_iso_week_of(now.date()))
        today = now.date().isoformat()
        today_used = usage["by_day"].get(today, 0)
        used_before_today = usage["tokens_used"] - today_used
        week_pct = round(usage["tokens_used"] / week_limit * 100, 1) if week_limit > 0 else 0.0
        log.info("[Budget] Quelle=Schätzung (InfluxDB nicht verfügbar): "
                "today_used=%d used_before=%d week_pct=%.1f%%", today_used, used_before_today, week_pct)

    reserve_days = max(int(cfg.get("budget_reserve_days", 1) or 0), 0)
    resttage = 8 - now.isoweekday() + reserve_days  # Mo=7 … So=1 (inkl. heute) + Reserve
    rest = week_limit - used_before_today
    day_allowance = max(rest, 0) / resttage

    w = _find_window(now.hour, windows)
    window = {"from": int(w.get("from", 0)), "to": int(w.get("to", 24)),
              "max_pct": int(w.get("max_pct", 100))}
    limit_today = day_allowance * window["max_pct"] / 100.0

    week_pct = round(week_pct, 1) if week_limit > 0 else 0.0
    if limit_today > 0:
        window_pct = round(today_used / limit_today * 100, 1)
    else:
        window_pct = 0.0 if today_used == 0 else 100.0

    # Sonntag-Burndown (Entscheidung 08.08.26): Am letzten Tag der Budget-Woche sollen die
    # Tages-Tranche UND die Stunden-Fenster nicht mehr bremsen — das Restbudget soll
    # bis zum Abo-Reset (So ~21:00) auf das Zielprozent aufgebraucht werden, statt
    # ungenutzt zu verfallen. Deckel bleibt: target_pct des Wochenlimits (Default 98 %,
    # die letzten 2 % sind die Sicherheitsmarge gegen ein hartes Abo-Aus).
    burndown_on = bool(int(cfg.get("budget_burndown_enabled", 1) or 0))
    burndown_pct = float(cfg.get("budget_burndown_target_pct", 98) or 0)

    # Source-Label für Tracing (InfluxDB vs. Schätzung)
    source_label = "[InfluxDB]" if source == "usage" else "[Schätzung]"

    if week_limit <= 0:
        allowed = True
        reason = f"Kein Wochenlimit gesetzt (budget_week_tokens<=0) {source_label}"
    elif not enforce:
        allowed = True
        reason = f"Budget-Enforcement deaktiviert (budget_enforce=false) {source_label}"
    elif burndown_on and now.isoweekday() == 7:
        target = week_limit * burndown_pct / 100.0
        today_tokens = int(week_limit * week_pct / 100.0)
        allowed = today_tokens < target
        if allowed:
            reason = (f"Sonntag-Burndown: {today_tokens:,} von {int(target):,} "
                      f"Tokens ({burndown_pct:.0f}% Wochenziel) — Tranche/Fenster ausser Kraft {source_label}")
        else:
            reason = (f"Sonntag-Burndown-Ziel erreicht: {today_tokens:,} >= "
                      f"{int(target):,} Tokens ({burndown_pct:.0f}% des Wochenlimits) {source_label}")
    else:
        allowed = today_used < limit_today
        if allowed:
            reason = (f"OK: {today_used:,}/{int(limit_today):,} Tokens "
                      f"im Fenster {window['from']}-{window['to']}h {source_label}")
        else:
            reason = (f"Fenster {window['from']}-{window['to']}h: {today_used:,} von "
                      f"{int(limit_today):,} Tokens verbraucht "
                      f"({window['max_pct']}% der Tages-Tranche {int(day_allowance):,}) {source_label}")

    log.debug("[Budget] allowed=%s week_pct=%.1f window_pct=%.1f tranche=%d "
              "today_used=%d fenster=%d-%d/%d%% source=%s reason=%s",
              allowed, week_pct, window_pct, int(day_allowance),
              today_used, window["from"], window["to"], window["max_pct"], source, reason)

    result = {"allowed": allowed, "week_pct": week_pct, "window_pct": window_pct,
              "day_allowance_tokens": int(day_allowance), "today_used": today_used,
              "window": window, "reason": reason, "source": source, "enforce": enforce}
    return result
