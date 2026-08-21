#!/usr/bin/env python3
"""
project_creator.py — Projekt- und Ideen-Erstellung mit Ollama-Integration.

Öffentliche Schnittstellen
--------------------------
search_projects_by_tag(query) -> list[dict]
    Alle ~/Projekte/ nach Tag durchsuchen.
    Rückgabe: [{"id": str, "path": str, "tags": list[str], "matched": list[str]}]

_vision_title(photo_bytes, note="") -> str
    Projekttitel aus JPEG-Bytes via Claude-Abo (Bridge 8950, /vision — „Bildersuche").
    Gibt leeren String zurück wenn die Bridge nicht erreichbar ist.

_vision_tags(photo_bytes, note="") -> list[str]
    5–8 deutsche Schlagwörter aus Foto via Claude-Abo (Bridge /vision).

_text_tags(title, description) -> list[str]
    5–8 deutsche Schlagwörter aus Text via Claude-Abo (Live-Projekterstellung, board_service.py).

_ollama_tags(title, description) -> list[str]
    5–8 deutsche Schlagwörter aus Text via Ollama (nächtlicher Batch-Tagger, project_tagger.py —
    226+ Projekte/Nacht, dafür Claude-Abo-Budget zu teuer, siehe kanban-ki-optimierung 02.08.26).

_correct_project_name(text) -> tuple[str, bool]
    Schreibfehler korrigieren + Projektnamen ableiten via Claude-Abo (ohne Theme-Ausschmückung).
    Rückgabe: (korrigierter_name, sinnvoll). sinnvoll=False → Eingabe zu unklar.

_create_project_folder(name, board_id, description, photo_bytes, photo_filename,
                       tags, is_idea) -> Path
    ~/Projekte/<board_id>/ mit CLAUDE.md, TAGS.md, Foto-Unterordner anlegen.

_slugify(text) -> str
    Text → lowercase, Bindestriche, Umlaute ersetzt, max 40 Zeichen.

pin_tag(project_path, tag, name=None) -> None
    Tag dauerhaft zu TAGS.md hinzufügen — übersteht automatisches Re-Tagging
    (project_tagger.py, stündlich), im Unterschied zu normal generierten Tags.

Interne Helfer (nicht für Wiederverwendung):
    _claude_abo_text, _claude_abo_vision, _ollama_text, _parse_tag_list,
    _generate_claude_md, _save_tags_md, _read_tags_md, _read_auto_tags_md,
    _read_pinned_tags, _write_tags_md_raw, _unique_board_id
"""

import json
import logging
import re
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

from constants import (OLLAMA_URL, PROJEKTE_BASE, CONTAINERS_BASE,
                       BOARDS_DIR, PRIORITY_COLORS)
from config_handler import _load_ai_config
from app.services import claude_client

log = logging.getLogger("trigger-server")


# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    """Text → kleingeschrieben, Bindestriche, max 40 Zeichen."""
    text = text.lower().strip()
    text = text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text[:40].strip("-")


def _unique_board_id(slug: str) -> str:
    """Gibt eine eindeutige Board-ID zurück (fügt -2, -3 etc. hinzu falls nötig)."""
    from app.storage.board_repository import BoardRepository
    board_repo = BoardRepository()
    candidate = slug
    counter = 2
    while board_repo.exists(candidate) or (PROJEKTE_BASE / candidate).exists():
        candidate = f"{slug}-{counter}"
        counter += 1
    return candidate


# ── Ollama Helpers ────────────────────────────────────────────────────────────

def _ollama_text(prompt: str, num_predict: int = 120, temperature: float = 0.2, timeout: int = 120,
                 model: str = "mistral:latest") -> str:
    """Ollama /api/generate (Default mistral:latest, via model= überschreibbar) → Antwort-String.

    Args:
        prompt:      Vollständiger Prompt-Text.
        num_predict: Max. Tokens (Standard 120; für CLAUDE.md ~350 verwenden).
        temperature: Kreativität 0.0–1.0 (Standard 0.2 = präzise).
        timeout:     HTTP-Timeout in Sekunden (Standard 120; für lange Texte 180).
        model:       Ollama-Modell (Standard mistral:latest; z.B. gemma3:12b für strukturierte
                     JSON-Ausgaben, die mistral nicht zuverlässig liefert).
    Returns:
        Generierter Text (stripped). Leerer String bei Fehler.
    """
    payload = {
        "model":   model,
        "prompt":  prompt,
        "stream":  False,
        "options": {"temperature": temperature, "num_predict": num_predict},
    }
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode())
    return body.get("response", "").strip()


def _claude_abo_text(system: str, prompt: str, model: str | None = None,
                     max_tokens: int = 800, temperature: float = 0.3,
                     timeout: int = 120) -> str:
    """Claude-Abo via lokaler CLI-Bridge (Port 8950) → Antwort-String.

    Nutzt die eingeloggte Claude-CLI-Session (= Abo, KEIN API-Guthaben). Modell aus
    ai_config['project_ideas_model'] wenn nicht explizit übergeben.

    Args:
        system:      System-Prompt (Rolle/Format).
        prompt:      User-Prompt.
        model:       Claude-Modell-ID; None → aus ai_config.
        max_tokens:  Antwort-Limit.
        temperature: Kreativität (Sonnet ignoriert es teils, schadet aber nicht).
        timeout:     HTTP-Timeout in Sekunden (CLI-Aufruf dauert ~5–20s).
    Returns:
        Generierter Text (stripped). Leerer String bei Fehler (Aufrufer fällt zurück).
    """
    if not model:
        model = _load_ai_config().get("project_ideas_model", "claude-sonnet-5")
    return claude_client.chat(system, prompt, model, max_tokens=max_tokens,
                              temperature=temperature, timeout=timeout)


def _claude_abo_vision(photo_bytes: bytes, system: str, prompt: str,
                       model: str | None = None, media_type: str = "image/jpeg",
                       timeout: int = 120) -> str:
    """Foto-Analyse („Bildersuche") übers Claude-Abo via CLI-Bridge (Port 8950, /vision).

    Ersetzt die frühere lokale Ollama-Vision (minicpm-v). Nutzt die eingeloggte
    Claude-CLI-Session (= Abo, KEIN API-Guthaben). Das Bild geht als base64-Content-Block
    an Claude (reine Inferenz, keine Agent-Tools — Bridge-Sicherheitssperre).

    Args:
        photo_bytes: JPEG/PNG als Bytes (wird base64-kodiert).
        system:      System-Instruktion (Rolle/Format).
        prompt:      Nutzer-Frage zum Bild (z.B. "Gib einen Projekttitel:").
        model:       Claude-Modell-ID; None → ai_config['project_vision_model'].
        media_type:  MIME-Typ des Bildes (Standard image/jpeg).
        timeout:     HTTP-Timeout in Sekunden.
    Returns:
        Antwort-Text (stripped). Leerer String bei Fehler (Aufrufer degradiert sauber).
    """
    if not model:
        model = _load_ai_config().get("project_vision_model", "claude-sonnet-4-6")
    return claude_client.vision(photo_bytes, system, prompt, model,
                                media_type=media_type, timeout=timeout)


# ── Öffentliche Funktionen ────────────────────────────────────────────────────

def _vision_title(photo_bytes: bytes, note: str = "") -> str:
    """Deutschen Projekttitel aus Foto generieren (3–5 Wörter) — via Claude-Abo (Bridge /vision).

    „Bildersuche" läuft jetzt komplett über das Claude-Abo (kein lokales Ollama mehr).
    Bei Fehler (Bridge nicht erreichbar) → leerer String, Aufrufer degradiert sauber.

    Args:
        photo_bytes: Foto als JPEG/PNG Bytes.
        note:        Optionaler Kontext-Hinweis (z.B. Nutzer-Notiz zum Foto).
    Returns:
        Projekttitel-String. Leerer String bei Fehler.
    """
    prompt = "Gib einen deutschen Projekttitel für dieses Foto (3-5 Wörter, kein Punkt, keine Anführungszeichen):"
    if note:
        prompt += f" Kontext: {note}"
    try:
        title = _claude_abo_vision(
            photo_bytes,
            "Antworte NUR mit dem Titel. Kein erklärender Text.",
            prompt, timeout=90)
        if title:
            # Claude liefert gelegentlich Anführungszeichen/Punkt mit → säubern
            title = title.splitlines()[0].strip().strip('"').strip("'").rstrip(".").strip()
            log.info(f"Vision-Titel (Claude-Abo): {title!r}")
            return title
    except Exception as e:
        log.warning(f"Claude Vision-Titel fehlgeschlagen: {e}")
    return ""


def _vision_tags(photo_bytes: bytes, note: str = "") -> list[str]:
    """5–8 deutsche Schlagwörter aus Foto — via Claude-Abo (Bridge /vision).

    „Bildersuche" über das Claude-Abo (kein lokales Ollama mehr).

    Args:
        photo_bytes: Foto als JPEG/PNG Bytes.
        note:        Optionaler Kontext-Hinweis.
    Returns:
        Liste mit 0–8 lowercase Tags (dedupliziert, 2–30 Zeichen je Tag).
        Leere Liste bei Fehler (Bridge nicht erreichbar).
    """
    prompt = "Was siehst du auf diesem Foto? Gib 5-8 deutsche Schlagwörter zurück, kommagetrennt, kleingeschrieben:"
    if note:
        prompt += f" Kontext: {note}"
    try:
        response = _claude_abo_vision(
            photo_bytes,
            "Antworte NUR mit kommaseparierten Schlagwörtern. Keine Sätze, keine Nummern.",
            prompt, timeout=90)
        tags = _parse_tag_list(response)
        log.info(f"Vision-Tags (Claude-Abo): {tags}")
        return tags
    except Exception as e:
        log.warning(f"Claude Vision-Tags fehlgeschlagen: {e}")
    return []


def _text_tags(title: str, description: str, parent_context: str = "",
               model: str | None = None) -> list[str]:
    """5–8 Schlagwörter aus Projektname + Beschreibung via Claude-Abo (Bridge 8950).

    Deckt bewusst ZWEI Dimensionen ab, damit die Tag-Suche Projekte nicht nur über ihr
    Thema, sondern auch über die **eingesetzte Technik** findet (z.B. "welche Projekte nutzen
    mediapipe / fastapi / mqtt / three.js"):
      1. Thema/Zweck des Projekts (worum geht es?)
      2. verwendete Technologien, Bausteine & Komponenten — auch wenn sie nur GENUTZT und
         nicht selbst gebaut werden (avatar, mediapipe, three.js, tts, fastapi, sqlite, …).

    Args:
        title:       Projektname (bereits korrigiert).
        description: Freitext/Quelltext (wird auf 1200 Zeichen gekürzt — die Technik steht
                     oft erst weiter unten in der CLAUDE.md).
        parent_context: Bei Unterprojekten die Kurzbeschreibung des Mutterprojekts —
                     hilft, mehrdeutige Titel im richtigen Thema zu verschlagworten.
        model:       Claude-Modell-ID; None → ai_config['project_ideas_model']. Der
                     Batch-Tagger (jobs/project_tagger.py) übergibt Haiku (Massen-Job).
    Returns:
        Liste mit 0–8 lowercase Tags. Leere Liste wenn die Bridge nicht erreichbar ist.
    """
    try:
        system = (
            "Du vergibst 5-8 Schlagwörter für ein Projekt: kommagetrennt, kleingeschrieben, "
            "keine Erklärung, kein Fliesstext. Decke ab: (1) Thema/Zweck und (2) die im Text "
            "GENANNTEN verwendeten Technologien/Bausteine — auch solche, die nur genutzt und "
            "nicht selbst gebaut werden. Eigennamen/Technik dürfen englisch bleiben, sonst deutsch. "
            "WICHTIG: Verwende AUSSCHLIESSLICH Begriffe, die tatsächlich aus Titel oder Beschreibung "
            "hervorgehen. Erfinde KEINE Technologien. Steht im Text keine konkrete Technik, gib nur "
            "Themen-Schlagwörter zurück."
        )
        parent_line = ""
        if parent_context:
            parent_line = f"Mutterprojekt (Thema-Kontext): {parent_context[:300]}\n"
            log.debug(f"Text-Tags mit Eltern-Kontext ({len(parent_context)} Zeichen)")
        prompt = f"Titel: {title}\n{parent_line}Beschreibung: {description[:1200]}\nTags:"
        response = _claude_abo_text(system, prompt, model=model, max_tokens=120,
                                    temperature=0.2, timeout=90)
        tags = _parse_tag_list(response)
        log.info(f"Text-Tags (Claude-Abo): {tags}")
        return tags
    except Exception as e:
        log.warning(f"Claude Text-Tags fehlgeschlagen: {e}")
    return []


def _ollama_tags(title: str, description: str, parent_context: str = "") -> list[str]:
    """5–8 Schlagwörter aus Projektname + Beschreibung via Ollama (Batch-Tagger, viele Projekte/Nacht).

    Bewusst EIN einfacher Auftrag statt der mehrteiligen Anti-Fantasie-Regeln aus `_text_tags`
    (Claude-Abo) — kleine lokale Modelle folgen einer kurzen, klaren Anweisung zuverlässiger als
    mehreren verschachtelten Constraints. Modell gemma3:12b (liefert strukturierte Kurzantworten
    zuverlässiger als mistral:latest).

    Args:
        title:       Projektname.
        description: Freitext/Quelltext (auf 1200 Zeichen gekürzt).
        parent_context: Bei Unterprojekten die Kurzbeschreibung des Mutterprojekts.
    Returns:
        Liste mit 0–8 lowercase Tags. Leere Liste bei Fehler (Ollama nicht erreichbar o.ä.).
    """
    try:
        parent_line = f"Mutterprojekt: {parent_context[:300]}\n" if parent_context else ""
        prompt = (
            f"Titel: {title}\n{parent_line}Beschreibung: {description[:1200]}\n\n"
            "Gib 5 bis 8 Schlagwörter zu Thema und Technik dieses Projekts aus. "
            "Nur Wörter, die oben im Text stehen. "
            "Format: durch Komma getrennt, klein geschrieben, keine Erklärung.\n"
            "Schlagwörter:"
        )
        response = _ollama_text(prompt, num_predict=120, temperature=0.2, timeout=60, model="gemma3:12b")
        tags = _parse_tag_list(response)
        log.info(f"Text-Tags (Ollama): {tags}")
        return tags
    except Exception as e:
        log.warning(f"Ollama Text-Tags fehlgeschlagen: {e}")
    return []


def _parse_tag_list(raw: str) -> list[str]:
    """Komma- oder zeilengetrennte Ollama-Antwort → bereinigte Tag-Liste.

    Normalisiert: lowercase, Sonderzeichen entfernt, Leerzeichen → Bindestriche.
    Filtert Tags < 2 oder > 30 Zeichen. Dedupliziert. Max. 8 Tags.
    """
    tags = []
    for part in raw.replace("\n", ",").split(","):
        tag = part.strip().strip("•-–·").strip().lower()
        tag = re.sub(r"[^\w\s\-äöüß]", "", tag).strip()
        tag = re.sub(r"\s+", "-", tag)
        if 2 <= len(tag) <= 30:
            tags.append(tag)
    return list(dict.fromkeys(tags))[:8]  # dedupliziert, max 8


def _correct_project_name(text: str, parent_context: str = "") -> tuple[str, bool]:
    """
    Schreibfehler korrigieren + kurzen Projektnamen ableiten — via Claude-Abo (Bridge 8950).
    Gibt (korrigierter_name, sinnvoll) zurück.
    sinnvoll=False wenn die Eingabe zu kurz/unklar ist.

    WICHTIG (Anti-Fantasie): NUR Tippfehler korrigieren und knapp benennen — das Thema NICHT
    umdeuten oder ausschmücken. Mehrdeutiges bleibt mehrdeutig (z.B. "Latein" → "Latein",
    nicht "Lateinische Kartenprojektion"). Insbesondere darf ein Ein-Wort-Name NICHT um
    erfundene Attribute verlängert werden (Vorfall 07.07.2026: "Geschichte" wurde wegen
    "2-4 Wörter"-Vorgabe zu "Schweizer Geschichte" aufgefüllt und das ganze Projekt kippte
    thematisch).

    Args:
        parent_context: Kurzbeschreibung des Mutterprojekts bei Unterprojekten — dient NUR
                        dem Verständnis mehrdeutiger Eingaben, wird nie in den Namen übernommen.
    """
    if len(text.strip()) < 3:
        return text, False
    system = (
        "Du korrigierst Schreibfehler in einer kurzen Projekt-Eingabe und gibst einen knappen "
        "Projektnamen (1-4 Wörter, Deutsch) zurück. Antworte NUR mit dem Namen, ohne Erklärung "
        "oder Anführungszeichen. Ist die Eingabe bereits ein brauchbarer Name, gib sie "
        "UNVERÄNDERT zurück. Deute das Thema NICHT um und füge KEINE zusätzlichen Wörter oder "
        "Attribute hinzu — auch nicht, um den Namen 'runder' zu machen; ein einzelnes Wort ist "
        "als Name erlaubt. Ergibt die Eingabe keinen erkennbaren Sinn, antworte genau mit: UNKLAR"
    )
    user = f"Eingabe: {text}"
    if parent_context:
        user += (
            f"\nKontext (Unterprojekt von): {parent_context}\n"
            "Der Kontext dient nur dem Verständnis — übernimm daraus NICHTS in den Namen."
        )
        log.debug(f"Namenskorrektur mit Eltern-Kontext ({len(parent_context)} Zeichen)")
    try:
        raw = _claude_abo_text(system, user, max_tokens=30, temperature=0.0, timeout=60)
        name = raw.split("\n")[0].strip().strip('"').strip("'").strip()
        if not name or name.upper() == "UNKLAR" or len(name) > 80:
            log.info(f"Claude-Abo: Eingabe '{text}' unklar")
            return text, False
        # Deterministische Anti-Fantasie-Guard: Die "Korrektur" darf keine Wörter HINZUFÜGEN
        # (nur Tippfehler beheben). LLMs neigen dazu, generische Ein-Wort-Namen trotz Verbot
        # auszuschmücken ("Geschichte" → "Spielgeschichte"/"Schweizer Geschichte") — in dem
        # Fall gewinnt die User-Eingabe.
        if len(name.split()) > len(text.strip().split()):
            log.info(f"Namenskorrektur verworfen (Wörter hinzugefügt): {text!r} → {name!r} "
                     f"— behalte User-Eingabe")
            return text.strip(), True
        log.info(f"Korrigierter Projektname (Claude-Abo): {name!r}")
        return name, True
    except Exception as e:
        log.warning(f"Claude-Abo Namenskorrektur fehlgeschlagen: {e}")
    return text, True  # Im Fehlerfall Eingabe durchlassen


def _strip_md_fences(content: str) -> str:
    """Entfernt umschliessende ```-Code-Fences aus LLM-Antworten."""
    if content.startswith("```"):
        content = "\n".join(content.split("\n")[1:]).rsplit("```", 1)[0].strip()
    return content


def _generate_claude_md(name: str, description: str, tags: list[str], is_idea: bool = False,
                        parent_context: str = "") -> str:
    """Generiert CLAUDE.md-Inhalt — Claude-Abo (Bridge 8950), Ollama als Fallback.

    Reihenfolge: 1) Claude-Abo (bessere Qualität, kein API-Guthaben), 2) Ollama,
    3) Minimal-Template. Schlägt nie fehl (Aufrufer bekommt immer gültiges Markdown).

    Args:
        parent_context: Bei Unterprojekten die Kurzbeschreibung des Mutterprojekts —
                        das Thema MUSS dann zum Mutterprojekt passen (mehrdeutige Namen
                        werden in dessen Kontext interpretiert, nicht frei ausgedeutet).
    """
    typ = "Schnell-Idee" if is_idea else "Projekt"
    system = ("Du schreibst eine knappe, sachliche CLAUDE.md für ein Projekt. "
              "Antworte NUR mit Markdown, ohne Code-Fences, max. 200 Wörter. Sprache: Deutsch. "
              "STIL: Steig direkt mit der Sache ein, keine Füllsätze wie 'Dieses Projekt dient dazu...' "
              "oder 'In diesem Projekt geht es um...'. Übernimm konkrete Begriffe aus der Eingabe "
              "wörtlich (Technik, Orte, Zahlen, Eigennamen) statt sie zu verallgemeinern — "
              "z.B. 'nutzt InfluxDB' statt 'nutzt eine Datenbank'.\n"
              "WICHTIG (Anti-Fantasie): Erfinde KEINE Inhalte, die nicht aus Name, Beschreibung "
              "oder Mutterprojekt-Kontext hervorgehen — 'konkret' heisst vorhandene Fakten wörtlich "
              "übernehmen, nicht neue Details erzeugen. Ist die Eingabe dünn oder mehrdeutig, "
              "schreibe knapp und liste das Offene als Klärungspunkte unter 'Nächste Schritte', "
              "statt ein detailliertes Projekt zu erdichten.")
    parent_block = ""
    if parent_context:
        parent_block = (
            f"Mutterprojekt (das Unterprojekt gehört thematisch DAZU): {parent_context}\n"
            "Das Thema der CLAUDE.md MUSS zum Mutterprojekt passen — interpretiere den "
            "Projektnamen in dessen Kontext.\n"
        )
        log.debug(f"CLAUDE.md-Generierung mit Eltern-Kontext ({len(parent_context)} Zeichen)")
    user = (
        f"Projektname: {name}\n"
        f"Beschreibung: {description}\n"
        f"Tags: {', '.join(tags)}\n"
        f"{parent_block}\n"
        f"Erstelle die CLAUDE.md für dieses {typ} mit den Abschnitten:\n"
        f"# {name}\n## Übersicht (1-2 Sätze, was das Projekt konkret ist — Fakten aus der "
        f"Beschreibung wörtlich übernehmen)\n"
        f"## Ziel (konkretes Ergebnis, aus der Beschreibung abgeleitet)\n"
        f"## Nächste Schritte (3-5 Stichpunkte, die sich aus der Beschreibung ergeben — "
        f"keine generischen Standardschritte)"
    )
    # 1) Claude-Abo
    try:
        content = _strip_md_fences(_claude_abo_text(system, user, max_tokens=600, timeout=120))
        if content:
            log.info(f"CLAUDE.md via Claude-Abo für '{name}' ({len(content)} Zeichen)")
            return content
    except Exception as e:
        log.warning(f"CLAUDE.md via Claude-Abo fehlgeschlagen, Fallback Ollama: {e}")
    # 2) Ollama-Fallback
    try:
        prompt = (
            f"Erstelle eine kurze CLAUDE.md für ein {typ} namens '{name}'.\n"
            f"Beschreibung: {description}\nTags: {', '.join(tags)}\n"
            f"{parent_block}"
            f"Nutze konkrete Begriffe aus der Beschreibung wörtlich, erfinde keine Inhalte, "
            f"die nicht aus den Angaben hervorgehen.\n"
            f"Format: Markdown, max 200 Wörter. Abschnitte: # {name}, ## Übersicht, ## Ziel, ## Nächste Schritte"
        )
        content = _strip_md_fences(_ollama_text(prompt, num_predict=350, temperature=0.3, timeout=180))
        if content:
            log.info(f"CLAUDE.md via Ollama (Fallback) für '{name}' ({len(content)} Zeichen)")
            return content
    except Exception as e:
        log.warning(f"CLAUDE.md-Generierung fehlgeschlagen: {e}")
    return f"# {name}\n\n{description}\n"


def generate_idea_cards(name: str, description: str, tags: list[str],
                        parent_context: str = "") -> list[dict]:
    """Brainstormt 5–8 konkrete Ideen-/Aufgabenkarten via Claude-Abo (Bridge 8950).

    Jede Idee bekommt Priorität (hoch/mittel/niedrig) + Aufwand (hoch/mittel/niedrig)
    als strukturierte Felder; `label` = Prioritäts-Farbe (Chip). Best-effort:
    bei Fehler/kaputtem JSON → leere Liste (Board-Erstellung schlägt nie fehl).

    Args:
        parent_context: Bei Unterprojekten die Kurzbeschreibung des Mutterprojekts —
                        Aufgaben müssen dann thematisch dazu passen.
    Returns:
        Liste von Karten-Dicts: {id, title, desc, label, priority, effort}.
    """
    system = (
        "Du bist ein erfahrener Projektplaner. Du brainstormst konkrete, umsetzbare "
        "Aufgaben/Ideen für ein neues Projekt. Jede Idee ist EIN konkreter Arbeitsschritt "
        "oder Feature, kein vages Schlagwort. Sprache: Deutsch.\n"
        "WICHTIG (Anti-Fantasie): Stütze dich NUR auf Name, Beschreibung, Tags und ggf. das "
        "Mutterprojekt. Ist die Eingabe dünn oder mehrdeutig, gib lieber nur 3-4 vorsichtige "
        "Aufgaben nah am Wortlaut zurück (z.B. Thema präzisieren, Material sammeln), statt ein "
        "erfundenes Detail-Projekt auszubreiten.\n"
        "Antworte AUSSCHLIESSLICH mit einem JSON-Array, kein Fliesstext, keine Code-Fences:\n"
        '[{"title":"kurzer Titel (max 8 Wörter)","desc":"1 Satz, was zu tun ist",'
        '"priority":"hoch|mittel|niedrig","effort":"hoch|mittel|niedrig"}, ...]\n'
        "Gib 3 bis 8 Ideen zurück. priority = Wichtigkeit, effort = geschätzter Aufwand."
    )
    parent_block = ""
    if parent_context:
        parent_block = (
            f"Mutterprojekt (Aufgaben MÜSSEN thematisch dazu passen): {parent_context}\n"
        )
        log.debug(f"Ideen-Brainstorm mit Eltern-Kontext ({len(parent_context)} Zeichen)")
    user = (
        f"Projektname: {name}\n"
        f"Beschreibung: {description}\n"
        f"Tags: {', '.join(tags)}\n"
        f"{parent_block}\n"
        "Generiere konkrete erste Aufgaben/Ideen für dieses Projekt."
    )
    try:
        raw = _strip_md_fences(_claude_abo_text(system, user, max_tokens=1200, timeout=150))
        start, end = raw.find("["), raw.rfind("]")
        if start < 0 or end < 0:
            log.warning(f"Ideen-Brainstorm: kein JSON-Array in Antwort ({raw[:120]!r})")
            return []
        items = json.loads(raw[start:end + 1])
    except Exception as e:
        log.warning(f"Ideen-Brainstorm fehlgeschlagen (keine Karten): {e}")
        return []

    cards: list[dict] = []
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            continue
        title = (it.get("title") or "").strip()
        if not title:
            continue
        prio = (it.get("priority") or "mittel").strip().lower()
        if prio not in PRIORITY_COLORS:
            prio = "mittel"
        effort = (it.get("effort") or "mittel").strip().lower()
        if effort not in ("hoch", "mittel", "niedrig"):
            effort = "mittel"
        cards.append({
            "id":       f"idea_{uuid.uuid4().hex[:10]}",
            "title":    title[:120],
            "desc":     (it.get("desc") or "").strip(),
            "label":    PRIORITY_COLORS[prio],   # Farb-Chip = Priorität
            "priority": prio,
            "effort":   effort,
        })
    log.info(f"Ideen-Brainstorm: {len(cards)} Karten via Claude-Abo für '{name}'")
    return cards


# Platzhalter in TAGS.md, wenn (noch) keine echten Tags generiert wurden (z.B. dünne
# Quelle / Ollama nicht erreichbar). KEIN echter Tag — wird beim Lesen herausgefiltert,
# und der Tagger wertet eine solche TAGS.md NICHT als "frisch" → nächster Lauf versucht erneut.
TAGS_PLACEHOLDER = "_(noch keine Tags)_"


def _write_tags_md_raw(project_path: Path, name: str, auto_tags: list[str],
                       pinned_tags: list[str], source: str,
                       individual_terms: list[str] | None = None,
                       src_hash: str | None = None) -> None:
    """Schreibt TAGS.md mit Schlagwörter- + optionalen Gepinnte-Tags-/Individuelle-Begriffe-
    Abschnitten. Interner Format-Writer, gemeinsam genutzt von _save_tags_md, pin_tag und
    set_individual_terms.

    `src_hash`: Fingerabdruck der Quelle (CLAUDE.md bzw. Karten-Titel), aus dem die Tags
    erzeugt wurden — Idempotenz-Marker von project_tagger (`_tags_fresh`). None = einen
    bereits vorhandenen Hash aus der Datei übernehmen; so löschen pin_tag und
    set_individual_terms ihn nicht versehentlich (sonst würde der nächste Tagger-Lauf das
    Projekt unnötig neu durch Ollama schicken)."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    if src_hash is None:
        src_hash = _read_tags_src_hash(project_path)
    lines = [
        f"# Tags – {name}",
        "",
        "## Schlagwörter",
        ", ".join(auto_tags) if auto_tags else TAGS_PLACEHOLDER,
    ]
    if pinned_tags:
        lines += ["", "## Gepinnte Tags", ", ".join(pinned_tags)]
    if individual_terms:
        lines += ["", "## Individuelle Begriffe", ", ".join(individual_terms)]
    lines += [
        "",
        "## Generiert",
        f"- Datum: {date_str}",
        f"- Quelle: {source}",
    ]
    if src_hash:
        lines.append(f"- Quell-Hash: {src_hash}")
    tags_path = project_path / "TAGS.md"
    tags_path.write_text("\n".join(lines) + "\n")
    log.info(f"TAGS.md gespeichert: {tags_path} — {auto_tags}" +
             (f" (+gepinnt: {pinned_tags})" if pinned_tags else "") +
             (f" (+individuell: {individual_terms})" if individual_terms else ""))


def _read_tags_src_hash(project_path: Path) -> str:
    """Liest den Quell-Fingerabdruck aus TAGS.md ("- Quell-Hash: <hex>", Abschnitt
    "## Generiert"). Leer, wenn die Datei fehlt oder noch aus der Zeit vor der
    hash-basierten Idempotenz stammt."""
    tags_file = project_path / "TAGS.md"
    if not tags_file.exists():
        return ""
    try:
        m = re.search(r"^-\s*Quell-Hash:\s*([0-9a-f]+)\s*$",
                      tags_file.read_text(errors="ignore"), re.MULTILINE)
    except Exception:
        return ""
    return m.group(1) if m else ""


def _save_tags_md(project_path: Path, name: str, tags: list[str], source: str = "ollama",
                  src_hash: str | None = None) -> None:
    """Schreibt TAGS.md in den Projektordner. Ein bereits vorhandener "## Gepinnte Tags"- oder
    "## Individuelle Begriffe"-Abschnitt (siehe pin_tag / set_individual_terms) bleibt beim
    Überschreiben erhalten — sonst würde jeder automatische Re-Tag-Lauf (project-meta.timer,
    stündlich) manuell gepinnte bzw. per Wortscanner ermittelte Tags mit auslöschen, da die KI
    bei jedem Lauf neu entscheidet, welche ~7 Tags am relevantesten sind (nicht deterministisch
    — ein einzelner erwähnter Begriff kann durchfallen)."""
    pinned = _read_pinned_tags(project_path)
    individual = _read_individual_terms(project_path)
    _write_tags_md_raw(project_path, name, tags, pinned, source, individual, src_hash)


def _read_auto_tags_md(project_path: Path) -> list[str]:
    """Liest NUR die automatisch generierten Tags (Abschnitt "## Schlagwörter"), OHNE
    gepinnte Tags. Der Platzhalter TAGS_PLACEHOLDER zählt NICHT als Tag."""
    tags_file = project_path / "TAGS.md"
    if not tags_file.exists():
        return []
    raw = tags_file.read_text()
    if "## Schlagwörter" not in raw:
        return []
    section = raw.split("## Schlagwörter", 1)[1].split("##")[0].strip()
    return [t.strip() for t in section.split(",")
            if t.strip() and t.strip() != TAGS_PLACEHOLDER]


def _read_pinned_tags(project_path: Path) -> list[str]:
    """Liest manuell gepinnte Tags (Abschnitt "## Gepinnte Tags", siehe pin_tag) —
    diese übersteht der automatische Tagger unverändert, im Unterschied zu
    "## Schlagwörter" (wird bei jedem Lauf komplett neu generiert)."""
    tags_file = project_path / "TAGS.md"
    if not tags_file.exists():
        return []
    raw = tags_file.read_text()
    if "## Gepinnte Tags" not in raw:
        return []
    section = raw.split("## Gepinnte Tags", 1)[1].split("##")[0].strip()
    return [t.strip() for t in section.split(",") if t.strip()]


def _read_individual_terms(project_path: Path) -> list[str]:
    """Liest die vom Wortscanner (siehe jobs/noun_scanner.py) ermittelten individuellen
    Begriffe (Abschnitt "## Individuelle Begriffe") — Nomen, die projektweit selten
    vorkommen und das Projekt dadurch von anderen unterscheiden. Übersteht wie
    "## Gepinnte Tags" das automatische Re-Tagging unverändert."""
    tags_file = project_path / "TAGS.md"
    if not tags_file.exists():
        return []
    raw = tags_file.read_text()
    if "## Individuelle Begriffe" not in raw:
        return []
    section = raw.split("## Individuelle Begriffe", 1)[1].split("##")[0].strip()
    return [t.strip() for t in section.split(",") if t.strip()]


def _read_tags_md(project_path: Path) -> list[str]:
    """Liest die effektiven Tags aus TAGS.md fürs Index/Suche: automatische
    "## Schlagwörter" + manuell "## Gepinnte Tags" (siehe _read_pinned_tags) +
    "## Individuelle Begriffe" (siehe _read_individual_terms), dedupliziert
    (case-insensitiv, erste Schreibweise gewinnt)."""
    auto = _read_auto_tags_md(project_path)
    pinned = _read_pinned_tags(project_path)
    individual = _read_individual_terms(project_path)
    seen, merged = set(), []
    for t in auto + pinned + individual:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            merged.append(t)
    return merged


def pin_tag(project_path: Path, tag: str, name: str | None = None) -> None:
    """Fügt einen Tag dauerhaft zu TAGS.md hinzu — übersteht automatisches Re-Tagging.

    Für Fälle wie "advisor" bei dashboard: project_tagger.py generiert die "##
    Schlagwörter" bei JEDEM Lauf (stündlich, project-meta.timer) komplett neu via
    KI — ein einzelner im CLAUDE.md erwähnter Begriff kann dabei durchfallen, weil
    die KI nicht deterministisch die ~7 salientesten Themen wählt. Gepinnte Tags
    stehen in einem separaten Abschnitt, den _save_tags_md nie überschreibt.
    """
    pinned = _read_pinned_tags(project_path)
    if tag in pinned:
        log.info(f"pin_tag: '{tag}' bereits gepinnt in {project_path}/TAGS.md")
        return
    pinned.append(tag)
    auto = _read_auto_tags_md(project_path)
    individual = _read_individual_terms(project_path)
    display_name = name or project_path.name
    _write_tags_md_raw(project_path, display_name, auto, pinned, source="manuell (pin_tag)",
                       individual_terms=individual)


def set_individual_terms(project_path: Path, name: str, terms: list[str]) -> None:
    """Schreibt die vom Wortscanner (jobs/noun_scanner.py) ermittelten individuellen Begriffe
    in TAGS.md — überschreibt NUR diesen Abschnitt, "## Schlagwörter" und "## Gepinnte Tags"
    bleiben unangetastet erhalten (analog zu pin_tag)."""
    auto = _read_auto_tags_md(project_path)
    pinned = _read_pinned_tags(project_path)
    _write_tags_md_raw(project_path, name, auto, pinned, source="wortscanner",
                       individual_terms=terms)


def _create_project_folder(
    name: str,
    board_id: str,
    description: str = "",
    photo_bytes: bytes = b"",
    photo_filename: str = "",
    tags: list[str] = None,
    is_idea: bool = False,
    fast: bool = False,
    parent_context: str = "",
) -> Path:
    """Legt die Projektverzeichnis-Struktur unter ~/Projekte/<board_id>/ an.

    Erstellt:
        CLAUDE.md       — via Ollama generiert (Übersicht, Ziel, Nächste Schritte)
        TAGS.md         — Schlagwörter (Quelle: ollama-vision oder ollama-text)
        .idea           — Marker-Datei, nur wenn is_idea=True
        fotos/<name>    — Foto-Kopie, nur wenn photo_bytes übergeben

    Args:
        name:           Angezeigter Projektname (z.B. "Smarte Küchenbeleuchtung").
        board_id:       Slugifizierte Board-ID = Ordner-Name (z.B. "smarte-kuechenbeleuchtung").
        description:    Optionale Freitext-Beschreibung.
        photo_bytes:    Foto als JPEG/PNG Bytes (leer = kein Foto).
        photo_filename: Dateiname für das gespeicherte Foto (z.B. "foto.jpg").
        tags:           Vorgefertigte Tag-Liste; wenn None → leere Liste.
        is_idea:        True = Schnell-Idee (legt .idea-Marker an).
        parent_context: Kurzbeschreibung des Mutterprojekts (Unterprojekte) — fliesst in
                        die CLAUDE.md-Generierung ein, damit das Thema dazu passt.
    Returns:
        Path-Objekt des angelegten Projektordners.
    Side effects:
        Schreibt Dateien in ~/Projekte/<board_id>/. Erstellt Ordner falls nötig.
    """
    tags = tags or []
    project_path = PROJEKTE_BASE / board_id
    project_path.mkdir(parents=True, exist_ok=True)
    log.info(f"Projektordner angelegt: {project_path}")

    # CLAUDE.md — fast=True: simples Template ohne Ollama (sonst ~20s Latenz)
    if fast:
        claude_md = (
            f"# {name}\n\n## Ziel\n- {description or 'TBD'}\n\n"
            f"## Status\n- Neu angelegt\n\n## Nächste Schritte\n- TBD\n"
        )
    else:
        claude_md = _generate_claude_md(name, description, tags, is_idea,
                                        parent_context=parent_context)
    (project_path / "CLAUDE.md").write_text(claude_md)
    log.debug(f"CLAUDE.md geschrieben (fast={fast})")

    # TAGS.md
    source = "ollama-vision" if photo_bytes else "ollama-text"
    _save_tags_md(project_path, name, tags, source)

    # .idea Marker
    if is_idea:
        (project_path / ".idea").write_text(
            f"Schnell-Idee erstellt: {datetime.now().isoformat()}\n"
        )
        log.info(".idea Marker gesetzt")

    # Foto in fotos/-Unterordner
    if photo_bytes and photo_filename:
        fotos_dir = project_path / "fotos"
        fotos_dir.mkdir(exist_ok=True)
        foto_path = fotos_dir / photo_filename
        foto_path.write_bytes(photo_bytes)
        log.info(f"Foto gespeichert: {foto_path} ({len(photo_bytes):,} Bytes)")

    # Projekt-Terminal vorab anlegen: leere tmux-Session "proj-<board_id>" (ohne Claude).
    # So ist das Terminal sofort da; Claude startet lazy beim ersten Öffnen (tmux-project.sh).
    _ensure_project_session(board_id, project_path)

    return project_path


def _ensure_project_session(board_id: str, project_path: Path) -> None:
    """Legt die persistente tmux-Session ``proj-<board_id>`` leer vorab an (OHNE Claude).

    Damit existiert das Projekt-Terminal sofort bei der Erstellung; Claude wird erst beim
    ersten Öffnen gestartet (``tmux-project.sh`` erkennt die leere Session und schickt die
    Claude-Schleife per ``send-keys`` rein). Spart RAM gegenüber sofort laufenden Claude-
    Instanzen pro Projekt.

    Idempotent + defensiv: existiert die Session schon, passiert nichts; fehlt der tmux-
    Server oder schlägt der Aufruf fehl, wird nur geloggt — die Projekt-Erstellung bricht
    NIE daran ab. dashboard-api läuft als User-Prozess und hat den tmux-Socket; CLI-/
    Background-Aufrufe ohne tmux degradieren sauber.
    """
    import re
    import shutil
    import subprocess

    if not re.fullmatch(r"[A-Za-z0-9._-]+", board_id or ""):
        log.warning("ensure_session: ungültiger Slug %r — übersprungen", board_id)
        return
    if not shutil.which("tmux"):
        log.info("ensure_session: kein tmux verfügbar — Session-Vorabanlage übersprungen")
        return
    session = f"proj-{board_id}"
    try:
        if subprocess.run(["tmux", "has-session", "-t", session],
                          capture_output=True, timeout=5).returncode == 0:
            log.info("ensure_session: %s existiert bereits — nichts zu tun", session)
            return
        subprocess.run(["tmux", "new-session", "-d", "-s", session, "-c", str(project_path)],
                       capture_output=True, timeout=5, check=True)
        log.info("ensure_session: leere tmux-Session %s angelegt (cwd=%s)", session, project_path)
    except Exception as e:
        log.warning("ensure_session: Anlegen von %s fehlgeschlagen (ignoriert): %s", session, e)


def search_projects_by_tag(query: str) -> list[dict]:
    """Alle bekannten Projekte nach Schlagwort durchsuchen (Index-basiert, schnell).

    Liest boards/tags-index.json (geschrieben von project_tagger.py, eine Quelle
    der Wahrheit für alle getaggten Projekte). Matcht case-insensitiv als Teilstring
    gegen Tags UND Ordner-/Anzeigenamen.

    Fallback auf TAGS.md-Direktscan wenn der Index fehlt oder nicht lesbar ist.

    Args:
        query: Suchbegriff (z.B. "avatar", "beleuchtung" oder "mqtt").
    Returns:
        Liste der Treffer, alphabetisch nach Projekt-ID sortiert:
        [{"id": str,          # Ordner-Name (Index-Schlüssel)
          "path": str,        # Absoluter Pfad zum Projektordner
          "tags": list,       # Alle Tags des Projekts (aus Index)
          "matched": list,    # Nur die Tags die den query enthalten (ggf. leer)
          "match_in": list    # Wo es traf: "name" und/oder "tag"
         }, ...]
    """
    # Führendes '#' tolerieren: User tippt oft Hashtag-Syntax (#mqtt), Tags im
    # Index sind aber ohne '#' gespeichert → sonst 0 Treffer.
    query_lower = query.lower().strip().lstrip("#").strip()
    if not query_lower:
        return []

    tags_index_path = BOARDS_DIR / "tags-index.json"
    if not tags_index_path.exists():
        log.warning("search_projects_by_tag: tags-index.json fehlt — Fallback auf TAGS.md-Scan")
        return _search_by_tags_md_scan(query_lower)

    try:
        idx = json.loads(tags_index_path.read_text())
    except Exception as exc:
        log.error("search_projects_by_tag: tags-index.json nicht lesbar (%s) — Fallback", exc)
        return _search_by_tags_md_scan(query_lower)

    projects = idx.get("projects", {})
    log.debug("search_projects_by_tag: Index geladen (%d Projekte, Stand %s)",
              len(projects), idx.get("updated", "?"))

    results = []
    for folder_id, proj in projects.items():
        tags = proj.get("tags", [])
        display_name = proj.get("name", folder_id)

        matching = [t for t in tags if query_lower in t.lower()]
        name_match = (query_lower in folder_id.lower() or
                      query_lower in display_name.lower())
        if not matching and not name_match:
            continue

        # Pfad bestimmen: ~/Projekte/ hat Vorrang (wie project_tagger._all_projects)
        path = None
        for base in (PROJEKTE_BASE, CONTAINERS_BASE):
            candidate = base / folder_id
            if candidate.exists():
                path = str(candidate)
                break
        if path is None:
            log.debug("search_projects_by_tag: '%s' im Index, Ordner nicht gefunden", folder_id)
            continue

        match_in = (["name"] if name_match else []) + (["tag"] if matching else [])
        results.append({
            "id":       folder_id,
            "path":     path,
            "tags":     tags,
            "matched":  matching,
            "match_in": match_in,
        })

    results.sort(key=lambda r: r["id"])
    log.info("Tag-Suche '%s': %d Treffer aus tags-index.json (Stand %s)",
             query_lower, len(results), idx.get("updated", "?"))
    return results


def _search_by_tags_md_scan(query_lower: str) -> list[dict]:
    """Fallback: TAGS.md in ~/Projekte/ und ~/containers/ direkt lesen (langsam)."""
    results = []
    seen: set[str] = set()
    for base in (PROJEKTE_BASE, CONTAINERS_BASE):
        if not base.exists():
            continue
        for project_dir in sorted(base.iterdir()):
            name = project_dir.name
            if not project_dir.is_dir() or name.startswith(".") or "__pycache__" in name:
                continue
            if name in seen:
                continue
            tags = _read_tags_md(project_dir)
            matching = [t for t in tags if query_lower in t.lower()]
            name_match = query_lower in name.lower()
            if not matching and not name_match:
                continue
            seen.add(name)
            match_in = (["name"] if name_match else []) + (["tag"] if matching else [])
            results.append({
                "id":       name,
                "path":     str(project_dir),
                "tags":     tags,
                "matched":  matching,
                "match_in": match_in,
            })
    results.sort(key=lambda r: r["id"])
    log.info("Tag-Suche '%s' (Fallback/TAGS.md-Scan): %d Treffer", query_lower, len(results))
    return results
