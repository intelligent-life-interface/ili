#!/usr/bin/env python3
"""
Kanban KI-Sortierer — Thin Wrapper.

Die Logik liegt jetzt im Paket kanban_ki_sortierer/ (1 Funktion = 1 Datei):
  config.py         — Konstanten + Logging
  classifier.py     — _col_status, _ollama_classify_batch
  board_io.py       — Board-/Manifest-I/O
  splitter.py       — _create_split_board, _remove_split_cards
  analyser.py       — analyse_board, _get_main_boards
  analyse_updater.py — _update_analyse_board, _fill_analyse_cards
  main.py           — CLI / argparse

Usage (unverändert):
  python3 kanban_ki_sortierer.py               # alle Boards analysieren
  python3 kanban_ki_sortierer.py --board xyz   # nur ein Board
  python3 kanban_ki_sortierer.py --dry-run     # nur analysieren, nicht schreiben
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kanban_ki_sortierer.main import main

if __name__ == "__main__":
    main()
