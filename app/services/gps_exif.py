"""GPS-EXIF-Injektion für Foto-Ideen — restauriert aus Git-History (trigger_server.py.bak).

War nach dem script_splitter-Refactoring verloren (NameError im alten Server,
still verschluckt). piexif ist im venv installiert; ohne piexif → Warning + No-op.
"""
import logging
from pathlib import Path

log = logging.getLogger("dashboard.services.gps")

try:
    import piexif
    _PIEXIF_OK = True
except ImportError:
    _PIEXIF_OK = False
    log.warning("piexif nicht installiert — GPS-EXIF-Injektion deaktiviert")


def _deg_to_dms_rational(deg: float):
    """Dezimalgrad → (Grad, Minuten, Sekunden) als piexif-Rational-Tupel."""
    d = int(abs(deg))
    m_float = (abs(deg) - d) * 60
    m = int(m_float)
    s = round((m_float - m) * 60 * 10000)
    return ((d, 1), (m, 1), (s, 10000))


def inject_gps_exif(photo_path: Path, lat: float, lon: float,
                    alt: float | None = None, direction: float | None = None) -> None:
    """Schreibt GPS-Koordinaten, Höhe und Blickrichtung als EXIF in die JPEG-Datei (in-place)."""
    if not _PIEXIF_OK:
        log.warning("piexif nicht verfügbar — GPS-EXIF wird nicht geschrieben")
        return
    try:
        gps_ifd = {
            piexif.GPSIFD.GPSLatitudeRef: ("N" if lat >= 0 else "S").encode(),
            piexif.GPSIFD.GPSLatitude: _deg_to_dms_rational(lat),
            piexif.GPSIFD.GPSLongitudeRef: ("E" if lon >= 0 else "W").encode(),
            piexif.GPSIFD.GPSLongitude: _deg_to_dms_rational(lon),
        }
        if alt is not None:
            gps_ifd[piexif.GPSIFD.GPSAltitudeRef] = 0 if alt >= 0 else 1
            gps_ifd[piexif.GPSIFD.GPSAltitude] = (int(abs(alt) * 100), 100)
        if direction is not None:
            gps_ifd[piexif.GPSIFD.GPSImgDirectionRef] = b"T"  # True North
            gps_ifd[piexif.GPSIFD.GPSImgDirection] = (int(direction * 100), 100)

        exif_bytes = piexif.dump({"GPS": gps_ifd})
        piexif.insert(exif_bytes, str(photo_path))
        log.info("GPS-EXIF injiziert: lat=%.6f lon=%.6f alt=%s dir=%s°", lat, lon, alt, direction)
    except Exception as e:
        log.error("GPS-EXIF-Injektion fehlgeschlagen: %s", e)
