"""Prozessübergreifendes File-Locking für boards/ — fcntl.flock auf boards/.lock.

Deckt alle Schreiber ab: FastAPI-Server, alter trigger_server, Timer-Scripts,
Claude-Code-Hooks (alles eigene Prozesse → fcntl statt threading.Lock).

WICHTIG: flock ist NICHT re-entrant über mehrere fds im selben Prozess —
wer den Lock hält, darf load()/save() nur über die _unlocked-Varianten aufrufen
(siehe Repository.update()).
"""
import fcntl
import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger("dashboard.storage.locking")


def _lock_of(path: Path) -> Path:
    """Lock-Pfad für eine Sidecar-JSON (Sibling <name>.lock im selben Ordner).

    Zentrale Quelle statt vier gedrifteter Kopien (ki_service.py,
    ki_global_rejections_service.py, wa_whitelist_service.py, jobs/ki_explain_worker.py):
    dieselbe Datei muss überall auf denselben Lock-Pfad abbilden, sonst überschreiben sich
    zwei Prozesse (z.B. dashboard-api und ein Timer-Worker) gegenseitig (Lost Update).
    """
    return path.with_name(path.name + ".lock")


@contextmanager
def file_lock(lock_file: Path, timeout: float = 10.0):
    """Exklusiver, prozessübergreifender Lock (LOCK_EX).

    Args:
        lock_file: Pfad zur Lock-Datei (wird angelegt falls fehlt).
        timeout:   Sekunden bis TimeoutError.
    Raises:
        TimeoutError: wenn der Lock nicht innerhalb von timeout frei wird.
    """
    with _file_lock_with_type(lock_file, fcntl.LOCK_EX, timeout):
        yield


@contextmanager
def file_lock_shared(lock_file: Path, timeout: float = 10.0):
    """Gemeinsamer, prozessübergreifender Lock (LOCK_SH) — Lesepfade.

    Mehrere Prozesse können LOCK_SH parallel halten (Reads concurrent).
    LOCK_SH blockiert LOCK_EX und umgekehrt — Safe gegen gleichzeitige Writes.

    Args:
        lock_file: Pfad zur Lock-Datei (wird angelegt falls fehlt).
        timeout:   Sekunden bis TimeoutError.
    Raises:
        TimeoutError: wenn der Lock nicht innerhalb von timeout frei wird.
    """
    with _file_lock_with_type(lock_file, fcntl.LOCK_SH, timeout):
        yield


@contextmanager
def _file_lock_with_type(lock_file: Path, lock_type: int, timeout: float = 10.0):
    """Hilfsfunktion für file_lock() / file_lock_shared().

    Args:
        lock_file: Pfad zur Lock-Datei (wird angelegt falls fehlt).
        lock_type: fcntl.LOCK_EX oder fcntl.LOCK_SH.
        timeout:   Sekunden bis TimeoutError.
    """
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_file), os.O_CREAT | os.O_RDWR, 0o644)
    start = time.monotonic()
    last_log = 0.0
    lock_name = "EX" if lock_type == fcntl.LOCK_EX else "SH"
    try:
        while True:
            try:
                fcntl.flock(fd, lock_type | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                waited = time.monotonic() - start
                if waited >= timeout:
                    raise TimeoutError(
                        f"Lock {lock_file} ({lock_name}) nach {waited:.1f}s nicht erhalten (pid={os.getpid()})"
                    )
                if waited - last_log >= 1.0:  # max 1 Debug-Log pro Sekunde
                    log.debug("Warte auf Lock %s (%s, pid=%s, %.1fs)", lock_file, lock_name, os.getpid(), waited)
                    last_log = waited
                time.sleep(0.05)
        waited = time.monotonic() - start
        if waited > 0.1:
            log.debug("Lock %s (%s) erhalten nach %.2fs (pid=%s)", lock_file, lock_name, waited, os.getpid())
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
