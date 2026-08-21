"""WhatsApp-Whitelist — Nummern-Verwaltung, Normalisierung, Profil-Anreicherung.

Standalone-Service: keine KI-Abhängigkeit, rein Datei-basiert.
Nutzt: WA_WHITELIST_FILE, WA_PROFILES_FILE (unter WA_FREIGABE_DIR).
"""
import json
import logging

from constants import WA_FREIGABE_DIR, WA_PROFILES_FILE, WA_WHITELIST_FILE
from app.storage.locking import _lock_of, file_lock
from app.storage.atomic_write import write_json_atomic

log = logging.getLogger("dashboard.services.wa_whitelist")


def _wa_read_whitelist() -> list:
    if not WA_WHITELIST_FILE.exists():
        return []
    try:
        return json.loads(WA_WHITELIST_FILE.read_text()).get("numbers", [])
    except Exception:
        return []


def _wa_write_whitelist(numbers: list) -> None:
    WA_FREIGABE_DIR.mkdir(parents=True, exist_ok=True)
    with file_lock(_lock_of(WA_WHITELIST_FILE)):
        write_json_atomic(WA_WHITELIST_FILE, {"numbers": numbers})
    log.info("Whitelist gespeichert: %d Nummern", len(numbers))


def _wa_read_profiles() -> dict:
    if not WA_PROFILES_FILE.exists():
        return {}
    try:
        return json.loads(WA_PROFILES_FILE.read_text())
    except Exception:
        return {}


def _wa_normalize(number) -> str:
    """Nummern-Normalisierung wie im Legacy: strip, führendes +, Leerzeichen weg."""
    return str(number or "").strip().lstrip("+").replace(" ", "")


def wa_whitelist_get() -> dict:
    """Whitelist + bekannte Profile, angereichert mit Namen."""
    numbers = _wa_read_whitelist()
    profiles = _wa_read_profiles()
    enriched = []
    for num in numbers:
        p = profiles.get(num, {})
        enriched.append({"number": num, "name": p.get("name", ""), "lang": p.get("lang", "")})
    # Bekannte Kontakte die noch nicht in der Whitelist sind
    known = []
    for num, p in profiles.items():
        if num not in numbers:
            known.append({"number": num, "name": p.get("name", ""), "lang": p.get("lang", "")})
    mode = "offen" if not numbers else "eingeschraenkt"
    log.debug("Whitelist GET: %d whitelisted, %d bekannte, Modus=%s", len(enriched), len(known), mode)
    return {"mode": mode, "whitelist": enriched, "known": known}


def wa_whitelist_add(number: str, name: str) -> dict:
    """Nummer hinzufügen; optional Namen ins Profil schreiben."""
    numbers = _wa_read_whitelist()
    if number in numbers:
        return {"status": "exists"}
    numbers.append(number)
    _wa_write_whitelist(numbers)
    if name:
        with file_lock(_lock_of(WA_PROFILES_FILE)):
            profiles = _wa_read_profiles()
            if number not in profiles:
                profiles[number] = {"name": name}
                write_json_atomic(WA_PROFILES_FILE, profiles)
    log.info("Whitelist: +%s (%s)", number, name or "?")
    return {"status": "ok", "number": number}


def wa_whitelist_remove(number: str) -> dict:
    """Nummer entfernen.

    Raises:
        LookupError: Nummer nicht in der Whitelist (HTTP 404).
    """
    numbers = _wa_read_whitelist()
    if number not in numbers:
        raise LookupError("Nicht in Whitelist")
    numbers.remove(number)
    _wa_write_whitelist(numbers)
    log.info("Whitelist: -%s", number)
    return {"status": "ok", "number": number, "remaining": len(numbers)}
