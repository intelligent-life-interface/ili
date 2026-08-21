#!/usr/bin/env python3
"""related_finder.py — verwandte Projekte finden (Tag-Vorfilter + Ollama über Top-N).

Token-sparend: an die KI gehen NUR Projekt-Namen + Tags, NIE der Projektinhalt.

Ablauf:
  1. Vorfilter (lokal, ohne KI): Jaccard-Ähnlichkeit der Tag-Mengen aus boards/tags-index.json
     (gebaut von project_tagger.py). Top-N Kandidaten mit Score > 0.
  2. KI-Refinement (Ollama, nur Namen+Tags): kurze Begründung je Kandidat, warum Code/Konzepte
     wiederverwendbar sind. Bei fehlendem Ollama -> reine Jaccard-Liste (shared_tags als Begründung).

Öffentliche Schnittstellen:
  score_candidates(source_id, index, top_n) -> list[dict]
  find_related(source_id, top_n=8, use_ai=True) -> dict
"""
import os
import sys
import json
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from constants import BOARDS_DIR
from project_creator import _ollama_text

log = logging.getLogger("trigger-server")

TAGS_INDEX = BOARDS_DIR / "tags-index.json"


def _load_index() -> dict:
    try:
        return json.loads(TAGS_INDEX.read_text())
    except Exception as e:
        log.warning(f"tags-index.json nicht lesbar: {e}")
        return {"projects": {}}


def score_candidates(source_id: str, index: dict, top_n: int = 8) -> list[dict]:
    """Jaccard-Vorfilter: Kandidaten mit gemeinsamen Tags, absteigend nach Score.

    Returns: [{id, name, tags, score, shared_tags}] (max top_n, score>0).
    """
    projects = index.get("projects", {})
    src = projects.get(source_id)
    if not src:
        return []
    a = set(src.get("tags", []))
    if not a:
        return []
    scored = []
    for pid, p in projects.items():
        if pid == source_id:
            continue
        b = set(p.get("tags", []))
        inter = a & b
        if not inter:
            continue
        union = a | b
        scored.append({
            "id": pid,
            "name": p.get("name", pid),
            "tags": sorted(b),
            "score": round(len(inter) / len(union), 3),
            "shared_tags": sorted(inter),
        })
    scored.sort(key=lambda x: (-x["score"], -len(x["shared_tags"]), x["name"].lower()))
    return scored[:top_n]


def _ai_reasons(source: dict, candidates: list[dict]) -> dict:
    """Ollama-Begründungen (NUR Namen+Tags) -> {id: reason}. Robustes JSON-Parsing."""
    lines = [
        f"Quellprojekt: {source.get('name')} (Tags: {', '.join(source.get('tags', []))})",
        "",
        "Kandidaten-Projekte:",
    ]
    for c in candidates:
        lines.append(f"- id={c['id']} | {c['name']} | Tags: {', '.join(c['tags'])}")
    prompt = (
        "Du hilfst, zusammenhängende Software-Projekte zu erkennen, damit Code/Konzepte "
        "wiederverwendet werden können. Gegeben ein Quellprojekt und Kandidaten (nur Namen+Tags).\n\n"
        + "\n".join(lines) +
        "\n\nGib für die 3-5 am stärksten verwandten Kandidaten je einen kurzen deutschen Satz, "
        "WARUM Code/Konzepte wiederverwendbar sind. Antworte AUSSCHLIESSLICH als JSON-Array:\n"
        '[{"id": "<id>", "reason": "<ein Satz>"}]'
    )
    raw = _ollama_text(prompt, num_predict=300, temperature=0.2, timeout=120)
    if not raw:
        return {}
    # JSON-Array aus der Antwort herauslösen (Modelle umranden gern mit Text)
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        arr = json.loads(raw[start:end + 1])
    except Exception:
        return {}
    out = {}
    for item in arr:
        if isinstance(item, dict) and item.get("id") and item.get("reason"):
            out[str(item["id"])] = str(item["reason"]).strip()
    return out


def find_related(source_id: str, top_n: int = 8, use_ai: bool = True) -> dict:
    """Verwandte Projekte: Jaccard-Vorfilter + optionale KI-Begründung.

    Returns: {source, count, related: [{id, name, score, shared_tags, reason}], note?}
    """
    index = _load_index()
    src = index.get("projects", {}).get(source_id)
    cands = score_candidates(source_id, index, top_n)

    if not cands:
        note = "Projekt hat keine Tags — erst taggen lassen." if not (src and src.get("tags")) \
               else "Keine Projekte mit gemeinsamen Tags gefunden."
        return {"source": source_id, "count": 0, "related": [], "note": note}

    reasons = {}
    if use_ai:
        try:
            reasons = _ai_reasons(src, cands)
        except Exception as e:
            log.warning(f"KI-Begründung fehlgeschlagen, nutze Tag-Fallback: {e}")

    related = []
    for c in cands:
        related.append({
            "id": c["id"],
            "name": c["name"],
            "score": c["score"],
            "shared_tags": c["shared_tags"],
            "reason": reasons.get(c["id"]) or ("Gemeinsame Tags: " + ", ".join(c["shared_tags"])),
        })
    return {"source": source_id, "count": len(related), "related": related}
