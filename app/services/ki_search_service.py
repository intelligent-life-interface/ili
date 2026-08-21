"""Semantic project-search fallback via local Ollama — retrieve-then-rerank.

Only invoked from the frontend when BOTH the client word-split filter and the
server tag-index search return nothing — i.e. the user's wording matches no
project text literally (synonyms, related topic, typo). Free (local), no Claude.

WHY retrieve-then-rerank and not "hand the whole catalogue to a chat model"
(the obvious first attempt, benchmarked and rejected 2026-08-07):
  - The ~250-project catalogue is ~13k tokens. gemma2:9b has a HARD 8192-token
    context → the catalogue is silently truncated (prompt_eval_count caps at
    8192) and the model ranks a blind fraction → plausible garbage.
  - gemma3:12b (128k ctx) sees it all but does not fit the 8 GB VRAM of the
    RTX 3070 (49 % CPU spill) → ~90 s, timeouts.
  - qwen3:8b (32k ctx) sees it all but "thinks" → 78-117 s, and STILL ranks 250
    near-identical lines poorly.
  => A small LLM cannot rank 250 items. Embeddings can. So: embed everything
     once (cached), cosine-retrieve the top candidates, then let a small LLM
     rerank+explain only those ~15 lines (tiny prompt, fits gemma2 easily).

House notes baked in:
  - Ollama endpoint: goes through app.services.ollama_client, which reads
    constants.OLLAMA_URL — that itself defaults to the working logging proxy
    :11435 (fixed 2026-08-08, was the dead-on-this-host :11434 before).
  - Embedding cache is keyed by a content hash — the frontend ships the catalogue
    in the POST body anyway, so no index/timer is needed; only changed records
    are re-embedded. First call after a restart pays a few seconds, then instant.
  - bge-m3 occasionally emits a NaN vector for a specific input → Ollama answers
    HTTP 500 ("unsupported value: NaN"). We isolate such records (batch → split →
    skip) so one poison text never sinks the whole search — ollama_client raises
    the distinct OllamaHTTPError for this case (vs. OllamaError for a plain
    network/connection failure), which is exactly the split needed here.
"""
import hashlib
import json
import logging
import math
import os
import threading

from constants import OLLAMA_URL
from app.services import ollama_client

log = logging.getLogger("dashboard.services.ki_search")

EMBED_MODEL = os.environ.get("KI_SEARCH_EMBED_MODEL", "bge-m3")       # multilingual
RERANK_MODEL = os.environ.get("KI_SEARCH_MODEL", "gemma2:9b")        # fits VRAM

# Rerank is OFF by default: the RTX 3070 (8 GB, Windows Ollama) keeps only ONE
# model resident, so a query needs bge-m3 AND the rerank model, forcing two
# model loads per call (~30 s vs. ~0.2 s embedding-only). Embedding-only already
# put the right project in the top-5 for every test query; the cleaner ordering
# + German reasons the reranker adds are not worth a fallback button that spins
# 30 s. Set KI_SEARCH_RERANK=1 to opt in (e.g. once a bigger GPU co-resides both,
# or if embeddings run on a separate host — the MacBook satellite on :152).
RERANK_ENABLED = os.environ.get("KI_SEARCH_RERANK", "").strip().lower() in (
    "1", "true", "yes", "on")
KEEP_ALIVE = os.environ.get("KI_SEARCH_KEEP_ALIVE", "15m")  # keep bge-m3 warm

MAX_PROJECTS = 400      # hard cap on records ever processed
MAX_DESC = 200          # per-project description truncation (chars)
TOP_K = 15              # embedding candidates handed to the reranker
MAX_MATCHES = 8         # results returned to the UI
EMBED_BATCH = 8         # /api/embed batch size (bigger batches 500 sporadically)
RERANK_NUM_CTX = 4096   # ~15 short lines fit easily (gemma2 max is 8192)
RERANK_NUM_PREDICT = 500
TIMEOUT = 60

# Per-process embedding cache: content-hash → vector. Guarded because the route
# is a sync `def` and FastAPI may run several in the threadpool concurrently.
_embed_cache: dict[str, list] = {}
_cache_lock = threading.Lock()


# ── helpers ──────────────────────────────────────────────────────────────
def _compact(projects: list) -> list:
    out = []
    for p in projects[:MAX_PROJECTS]:
        pid = (p.get("id") or "").strip()
        if not pid:
            continue
        tags = p.get("tags") or []
        if not isinstance(tags, list):
            tags = []
        out.append({
            "id": pid,
            "name": (p.get("name") or pid).strip(),
            "tags": [str(t).strip() for t in tags if str(t).strip()],
            "desc": (p.get("desc") or p.get("description") or "").strip()[:MAX_DESC],
        })
    return out


def _content(p: dict) -> str:
    """Text fed to the embedder — name carries most signal, tags + desc refine."""
    return f'{p["name"]}. Tags: {", ".join(p["tags"])}. {p["desc"]}'


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _embed_post(texts: list) -> list:
    """Raw batch embed — raises ollama_client.OllamaHTTPError on a NaN/oversize batch."""
    inputs = [(t or "x")[:400] for t in texts]
    return ollama_client.embed_raw(EMBED_MODEL, inputs, keep_alive=KEEP_ALIVE,
                                   timeout=TIMEOUT)["embeddings"]


def _embed_texts(texts: list) -> list:
    """Return one vector per text, or None where the embedder chokes (NaN).

    Recursive batch → split → skip: a single poison record (bge-m3 NaN → HTTP 500)
    is isolated to a None instead of failing the whole request.
    """
    vecs: list = [None] * len(texts)

    def do_range(lo: int, hi: int) -> None:
        try:
            got = _embed_post(texts[lo:hi])
            for k, i in enumerate(range(lo, hi)):
                vecs[i] = got[k]
        except ollama_client.OllamaHTTPError:
            if hi - lo <= 1:
                log.warning("KI-Suche: Embedding uebersprungen (NaN/500) fuer Text %d", lo)
                return
            mid = (lo + hi) // 2
            do_range(lo, mid)
            do_range(mid, hi)

    for start in range(0, len(texts), EMBED_BATCH):
        do_range(start, min(start + EMBED_BATCH, len(texts)))
    return vecs


def _embed_catalogue(cat: list) -> list:
    """Embed all project records, using and filling the content-hash cache.

    Only records whose content changed since last time are re-embedded.
    """
    contents = [_content(p) for p in cat]
    hashes = [_hash(c) for c in contents]

    with _cache_lock:
        missing = [i for i, h in enumerate(hashes) if h not in _embed_cache]
    if missing:
        log.info("KI-Suche: embedde %d/%d Projekte neu (Rest aus Cache)", len(missing), len(cat))
        fresh = _embed_texts([contents[i] for i in missing])
        with _cache_lock:
            for k, i in enumerate(missing):
                if fresh[k] is not None:
                    _embed_cache[hashes[i]] = fresh[k]

    with _cache_lock:
        return [_embed_cache.get(h) for h in hashes]


def _cosine(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb + 1e-9)


def _build_rerank_prompt(query: str, cands: list) -> str:
    lines = [f'{c["id"]} | {c["name"]} | Tags: {", ".join(c["tags"])} | {c["desc"]}'
             for c in cands]
    return (
        "Ein Nutzer sucht ein Projekt in einem Homeserver-Dashboard. Unten stehen "
        "die per Aehnlichkeitssuche vorausgewaehlten Kandidaten. Waehle davon die "
        "aus, die WIRKLICH zur Suchanfrage passen, nach Relevanz sortiert, und "
        "verwirf die unpassenden.\n\n"
        f'Suchanfrage: "{query}"\n\n'
        "Kandidaten (ID | Name | Tags | Beschreibung):\n"
        f"{chr(10).join(lines)}\n\n"
        f"Gib hoechstens {MAX_MATCHES} zurueck, IDs exakt aus der Liste. Passt gar "
        "nichts, leere Liste. Antworte NUR als JSON:\n"
        '{"matches":[{"id":"<ID>","reason":"<kurze Begruendung auf Deutsch, max 12 Woerter>"}]}'
    )


def _rerank(query: str, cands: list) -> dict:
    """Return {id: reason} for the relevant candidates. {} on any failure."""
    try:
        resp = ollama_client.generate_raw(
            RERANK_MODEL, _build_rerank_prompt(query, cands), format="json",
            options={"temperature": 0.1, "num_ctx": RERANK_NUM_CTX,
                     "num_predict": RERANK_NUM_PREDICT},
            timeout=TIMEOUT,
        )
    except Exception as e:  # noqa: BLE001 — rerank is optional garnish, never fatal
        log.warning("KI-Suche: Rerank fehlgeschlagen (%s) — nutze reine Embedding-Reihung", e)
        return {}
    # prompt_eval_count = truncation canary (must be well under gemma2's 8192)
    log.info("KI-Suche Rerank: prompt_eval_count=%s eval_count=%s",
             resp.get("prompt_eval_count"), resp.get("eval_count"))
    try:
        parsed = json.loads(resp.get("response", "") or "{}")
        out = {}
        for m in (parsed.get("matches") or []):
            if isinstance(m, dict) and (m.get("id") or "").strip():
                out[m["id"].strip()] = (m.get("reason") or "").strip()[:160]
        return out
    except (json.JSONDecodeError, ValueError, AttributeError) as e:
        log.warning("KI-Suche: Rerank-Antwort unlesbar (%s)", e)
        return {}


# ── public API ───────────────────────────────────────────────────────────
def search_projects(query: str, projects: list) -> dict:
    """Return {matches:[{id,name,reason}], model, count, note?}.

    Never raises for a model hiccup — degrades to an empty match list with a note
    so the UI can say "KI hat nichts gefunden" instead of erroring.
    """
    query = (query or "").strip()
    cat = _compact(projects or [])
    model_label = f"{EMBED_MODEL}+{RERANK_MODEL}" if RERANK_ENABLED else EMBED_MODEL
    if not query:
        return {"matches": [], "model": model_label, "note": "leere Suchanfrage"}
    if not cat:
        return {"matches": [], "model": model_label, "note": "keine Projekte uebergeben"}

    log.info("KI-Suche gestartet: query=%r, %d Projekte", query, len(cat))

    # 1) Retrieve: embed catalogue (cached) + query, cosine top-K.
    try:
        vecs = _embed_catalogue(cat)
        qv = _embed_texts([query])[0]
    except ollama_client.OllamaError as e:
        log.error("KI-Suche: Ollama nicht erreichbar (%s): %s", OLLAMA_URL, e)
        return {"matches": [], "model": model_label, "note": f"Ollama nicht erreichbar ({OLLAMA_URL})"}
    except Exception as e:  # noqa: BLE001
        log.error("KI-Suche: unerwarteter Fehler beim Embedden: %s", e, exc_info=True)
        return {"matches": [], "model": model_label, "note": "unerwarteter Fehler"}

    if qv is None:
        return {"matches": [], "model": model_label, "note": "Suchanfrage nicht embeddbar"}

    scored = [(_cosine(qv, v), cat[i]) for i, v in enumerate(vecs) if v is not None]
    scored.sort(key=lambda t: t[0], reverse=True)
    candidates = [p for _, p in scored[:TOP_K]]
    log.info("KI-Suche: %d Kandidaten aus Embedding-Retrieval (Top-Score %.3f)",
             len(candidates), scored[0][0] if scored else 0.0)
    if not candidates:
        return {"matches": [], "model": model_label, "note": "keine embeddbaren Projekte"}

    # 2) Rerank (opt-in only): small LLM over just the top-K → order + reasons.
    #    Off by default because of the one-model-resident VRAM constraint above.
    matches = []
    if RERANK_ENABLED:
        reasons = _rerank(query, candidates)
        by_id = {p["id"]: p for p in candidates}
        for pid, reason in reasons.items():
            if pid in by_id and len(matches) < MAX_MATCHES:
                matches.append({"id": pid, "name": by_id[pid]["name"], "reason": reason})

    # 3) Default path (and rerank-fallback): embedding top-N, ordered by cosine.
    #    No `reason` field — the project card already shows name/tags/description,
    #    and a raw score string reads worse than nothing (frontend: `if m.reason`).
    if not matches:
        for p in candidates[:MAX_MATCHES]:
            matches.append({"id": p["id"], "name": p["name"]})

    log.info("KI-Suche fertig: %d Treffer fuer query=%r (rerank=%s)",
             len(matches), query, RERANK_ENABLED)
    return {"matches": matches, "model": model_label, "count": len(matches)}
