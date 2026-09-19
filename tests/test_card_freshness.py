"""Karteileichen-Filter (Kanban-Auftrag 18.09.2026): html/js/card-freshness.js enthält die
reine Filterlogik ("ist eine Karte eine Leiche?") ohne DOM-Zugriff, damit sie ohne Browser
geprüft werden kann. Hier per `node` aufgerufen, gleicher Stil wie test_terminal_test_scripts.py
(bash -n/shellcheck via subprocess statt eines eigenen JS-Testframeworks — keins vorhanden).
"""
import json
import os
import shutil
import subprocess

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
MODULE_PATH = os.path.join(ROOT, "html", "js", "card-freshness.js")

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node nicht installiert")


def run_node(js_snippet: str) -> str:
    result = subprocess.run(
        ["node", "-e", js_snippet],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_module_is_valid_syntax():
    result = subprocess.run(["node", "--check", MODULE_PATH], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_card_without_any_timestamp_is_not_a_zombie():
    # Seed-Karten aus der Zeit vor diesem Feature haben weder created_at noch
    # updated_at -- sie gelten als unbekannt, nicht als Leiche (Auftragsvorgabe).
    out = run_node(f"""
        const {{ isZombieCard }} = require({json.dumps(MODULE_PATH)});
        console.log(isZombieCard({{}}, 60, Date.now()));
    """)
    assert out == "false"


def test_recently_touched_card_is_not_a_zombie():
    out = run_node(f"""
        const {{ isZombieCard }} = require({json.dumps(MODULE_PATH)});
        const now = Date.now();
        const recent = new Date(now - 5 * 86400000).toISOString();
        console.log(isZombieCard({{ updated_at: recent }}, 60, now));
    """)
    assert out == "false"


def test_stale_card_is_a_zombie_at_default_threshold():
    out = run_node(f"""
        const {{ isZombieCard }} = require({json.dumps(MODULE_PATH)});
        const now = Date.now();
        const old = new Date(now - 90 * 86400000).toISOString();
        console.log(isZombieCard({{ updated_at: old }}, 60, now));
    """)
    assert out == "true"


def test_updated_at_wins_over_older_created_at():
    out = run_node(f"""
        const {{ isZombieCard }} = require({json.dumps(MODULE_PATH)});
        const now = Date.now();
        const oldCreated = new Date(now - 200 * 86400000).toISOString();
        const recentUpdated = new Date(now - 1 * 86400000).toISOString();
        console.log(isZombieCard({{ created_at: oldCreated, updated_at: recentUpdated }}, 60, now));
    """)
    assert out == "false"


def test_threshold_is_configurable():
    out = run_node(f"""
        const {{ isZombieCard }} = require({json.dumps(MODULE_PATH)});
        const now = Date.now();
        const days45 = new Date(now - 45 * 86400000).toISOString();
        console.log([
            isZombieCard({{ updated_at: days45 }}, 30, now),
            isZombieCard({{ updated_at: days45 }}, 90, now),
        ].join(','));
    """)
    assert out == "true,false"
