#!/usr/bin/env python3
"""CLI für Konfigabfragen: tägliches Limit, Wochenbudget, Reserve-Konzept."""
import json
import sys
import logging
import argparse

import config

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")


def main():
    parser = argparse.ArgumentParser(
        description="Abfrage des Token-Budget-Systems (ai_config.json)"
    )
    parser.add_argument(
        "--daily-limit",
        action="store_true",
        help="Tägliches Token-Limit (aus Wochenbudget / Divisionen)"
    )
    parser.add_argument(
        "--week-tokens",
        action="store_true",
        help="Wochenbudget (budget_week_tokens)"
    )
    parser.add_argument(
        "--divisions",
        action="store_true",
        help="Anzahl der Wochenteilungen (budget_week_divisions)"
    )
    parser.add_argument(
        "--reserve-concept",
        action="store_true",
        help="Kurzerklärung der Reserve-Logik"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Alle Werte + Erklärungen (default wenn kein Flag gesetzt)"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Ausgabe als JSON statt formatiertem Text"
    )

    args = parser.parse_args()

    # Wenn kein Flag, default zu --all
    if not any([args.daily_limit, args.week_tokens, args.divisions, args.reserve_concept]):
        args.all = True

    cfg = config.get_config()

    if args.json:
        # JSON-Ausgabe
        out = {}
        if args.all or args.daily_limit:
            out["daily_limit_tokens"] = cfg["budget_daily_max_tokens"]
        if args.all or args.week_tokens:
            out["week_tokens"] = cfg["budget_week_tokens"]
        if args.all or args.divisions:
            out["week_divisions"] = cfg["budget_week_divisions"]
        if args.all or args.reserve_concept:
            div = cfg["budget_week_divisions"]
            out["reserve_concept"] = (
                f"Bei {div} Wochenteilungen und normalem Verbrauch an 7 Tagen "
                f"bleibt ca. {cfg['budget_reserve_days']} Tag Reserve"
            )
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        # Formatierte Text-Ausgabe
        if args.all or args.daily_limit:
            print(f"Tägliches Limit: {cfg['budget_daily_max_tokens']:,} Token")
        if args.all or args.week_tokens:
            print(f"Wochenbudget: {cfg['budget_week_tokens']:,} Token")
        if args.all or args.divisions:
            print(f"Wochenteilungen: {cfg['budget_week_divisions']}")
        if args.all or args.reserve_concept:
            div = cfg["budget_week_divisions"]
            reserve = cfg["budget_reserve_days"]
            print(
                f"\nReserve-Konzept: "
                f"Woche/{div} = Tageslimit. "
                f"Bei {7} Tagen Normalverbrauch bleibt ca. {reserve} Tag für Manager-Projekte."
            )


if __name__ == "__main__":
    main()
