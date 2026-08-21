"""board_cleanup — löst den zeitgesteuerten Aufräumer (kanban-split) on-demand für EIN Board aus.

Der Aufräumer (`~/bin/kanban-split/main.py`) teilt zu volle Boards in thematische
Unterprojekte auf. Normalerweise läuft er per `kanban-split.timer` (So 04:00, --apply).
Dieses Modul ruft genau dasselbe Script per subprocess für ein einzelnes Board:
  - apply=False: Trockenlauf — zeigt nur den Plan, schreibt nichts (für die Vorschau).
  - apply=True:  führt aus (legt Unterprojekte an, verschiebt Karten, Backup vorher).

dashboard-api läuft als Host-Prozess (systemd --user) → subprocess ist möglich
(der Aufräumer redet seinerseits via HTTP mit der dashboard-api auf 127.0.0.1:8798).
"""
import logging
import os
import subprocess

log = logging.getLogger("dashboard.board_cleanup")

SPLIT_MAIN = os.path.expanduser("~/bin/kanban-split/main.py")
TIMEOUT_S = 300  # Apply mit Ollama-Clustering kann dauern

# Der wöchentliche Timer nutzt SPLIT_THRESHOLD=25. Der manuelle Button (User-Wunsch 2026-06-23)
# darf AUCH kleinere Boards teilen → niedrigerer Default-Schwellwert (8, User-Vorgabe). Das
# technische Minimum wäre 6 (MIN_CLUSTERS_TO_SPLIT(2)*MIN_CLUSTER_CARDS(3)); die übrigen
# Sicherheitsfilter (≥3 Karten/Cluster, ≥2 Cluster, Ausschlusslisten) greifen weiter.
MANUAL_THRESHOLD = 8


def run_cleanup(board_id: str, apply: bool = False, threshold=None) -> dict:
    """Aufräumer für EIN Board ausführen.

    Args:
        board_id: Board-ID (z.B. 'antara-rückentraining').
        apply: False = Trockenlauf/Vorschau, True = wirklich aufteilen.
        threshold: optionaler Karten-Schwellwert. None → MANUAL_THRESHOLD (8), damit der
            manuelle Button auch kleine Boards teilen kann (anders als der Timer mit 25).

    Returns:
        {board_id, applied, ok, returncode, nothing_to_do, output}
    """
    board_id = (board_id or "").strip()
    if not board_id:
        raise ValueError("board_id ist Pflicht")
    if not os.path.exists(SPLIT_MAIN):
        raise FileNotFoundError(f"Aufräumer-Script nicht gefunden: {SPLIT_MAIN}")
    if threshold is None:
        threshold = MANUAL_THRESHOLD

    cmd = ["python3", SPLIT_MAIN, "--board", board_id, "--threshold", str(int(threshold))]
    if apply:
        cmd.append("--apply")

    log.info("Aufräumer für %r (apply=%s, threshold=%s): %s",
             board_id, apply, threshold, " ".join(cmd))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        log.error("Aufräumer-Timeout (%ss) für %r", TIMEOUT_S, board_id)
        return {"board_id": board_id, "applied": apply, "ok": False, "returncode": -1,
                "nothing_to_do": False, "output": "",
                "note": f"Zeitüberschreitung ({TIMEOUT_S}s) — Ollama-Clustering hängt evtl."}

    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    ok = proc.returncode == 0
    # Der Plan/„nichts zu tun" geht via print() nach stdout; Log-INFO nach stderr.
    # stderr nur bei Fehler anhängen, damit die Vorschau sauber bleibt.
    combined = out if ok else (out + ("\n" + err if err else "")).strip()
    if not ok:
        log.warning("Aufräumer rc=%s für %r: %s", proc.returncode, board_id, err[:300])

    nothing = ("Keine zu grossen" in combined) or ("kein sinnvoller Split" in combined)
    return {
        "board_id": board_id,
        "applied": apply,
        "ok": ok,
        "returncode": proc.returncode,
        "nothing_to_do": bool(nothing),
        "output": combined or "(keine Ausgabe)",
    }
