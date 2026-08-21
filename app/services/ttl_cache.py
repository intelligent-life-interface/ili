"""Generischer TTL-Cache mit Single-Flight Double-Checked Locking.

Zentrale Implementierung des Musters, das über 11 Module verstreut war:
TTL-Cache + Condition Variable (statt nur Lock) für echtes Single-Flight:
nur der erste Request nach TTL-Ablauf rechnet neu; parallele Requests warten
auf sein Ergebnis, statt selbst zu berechnen.

Verwendung:
    cache = TTLCache(ttl_seconds=60.0)
    result = cache.get(compute_fn)  # compute_fn wird ggf. aufgerufen

Bei mehreren parallelen Requests nach TTL-Ablauf:
- Der erste durchläuft compute_fn und speichert das Ergebnis
- Die anderen warten unter der Condition Variable, bis das Ergebnis da ist

Unterstützt auch None-Werte (können gültig sein):
    cache = TTLCache(ttl_seconds=60.0, allow_none=True)
    result = cache.get(compute_fn)  # compute_fn kann None zurückgeben
    cache.invalidate()  # Fortzwingern einer Neuberechnung
"""
import logging
import threading
import time
from typing import Callable, Generic, TypeVar, Optional

log = logging.getLogger("dashboard.services.ttl_cache")

T = TypeVar('T')


class TTLCache(Generic[T]):
    """Thread-safe TTL cache mit Single-Flight via Condition Variable.

    Schützt teure Operationen vor Cache-Stampede: nur der erste Request
    nach TTL-Ablauf rechnet neu; parallele Requests warten auf sein Ergebnis
    statt selbst zu berechnen.
    """

    def __init__(self, ttl_seconds: float, allow_none: bool = False):
        """
        Args:
            ttl_seconds: Cache-Gültigkeit in Sekunden
            allow_none: Wenn True, werden auch None-Werte gecacht
                       (useful für fehlertolerante Fallbacks)
        """
        self.ttl = ttl_seconds
        self.allow_none = allow_none
        self._cond = threading.Condition(threading.Lock())
        self._computing: bool = False  # Flag: gerade eine Berechnung unterwegs?
        self._data: Optional[T] = None
        self._ts: float = 0.0
        self._valid: bool = False  # True = es wurde ≥1x gecacht (auch None)

    def get(self, compute_fn: Callable[[], Optional[T]]) -> Optional[T]:
        """Cached value abrufen oder neu berechnen + cachen.

        Bei mehreren parallelen Requests nach TTL-Ablauf:
        - Nur einer berechnet wirklich (compute_fn wird 1x aufgerufen)
        - Die anderen warten auf das Ergebnis

        Args:
            compute_fn: Callable, das den (potenziell teuren) Wert berechnet

        Returns:
            Gecachtes oder neu berechnetes Ergebnis (kann None sein wenn allow_none=True)
        """
        now = time.time()

        # Check 1: ohne Lock (fast path für Cache-Hits)
        if self._valid and (now - self._ts) < self.ttl:
            if self._data is not None or self.allow_none:
                return self._data

        with self._cond:
            # Warte, falls gerade eine Berechnung läuft
            while self._computing:
                self._cond.wait()

            # Double-Check: ist der Cache jetzt gültig?
            now = time.time()
            if self._valid and (now - self._ts) < self.ttl:
                if self._data is not None or self.allow_none:
                    return self._data

            # Ich werde berechnen — Signalisiere anderen Threads, dass Berechnung läuft
            self._computing = True

        # Berechnung OHNE Lock (für lange Operationen)
        try:
            result = compute_fn()
        except Exception as e:
            log.error("TTL-Cache compute_fn fehlgeschlagen: %s", e, exc_info=True)
            with self._cond:
                self._computing = False
                self._cond.notify_all()
            raise
        else:
            # Nur bei Erfolg als gültig markieren — sonst bliebe eine
            # fehlgeschlagene Neuberechnung fälschlich für die volle TTL
            # als "gültig" markiert und liefert stille, veraltete Daten.
            now = time.time()
            with self._cond:
                self._data = result
                self._computing = False
                self._ts = now
                self._valid = True
                self._cond.notify_all()

        return self._data

    def invalidate(self):
        """Cache sofort invalidieren (erzwingt Neuberechnung beim nächsten get())."""
        with self._cond:
            self._valid = False
            self._data = None
            self._ts = 0.0

    def is_valid(self) -> bool:
        """Ist der Cache noch gültig (nicht abgelaufen)?"""
        now = time.time()
        return self._valid and (now - self._ts) < self.ttl
