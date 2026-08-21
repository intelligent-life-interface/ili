"""API-Router: Streaming-Endpoints (Welle 7).

POST /analyse-bug, POST /ki-explain-stream — text/plain Token-Stream, Ende "\\n[DONE]".
X-Accel-Buffering: no → nginx puffert nicht (zusätzlich proxy_buffering off in nginx.conf).
"""
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from app.services import stream_service
from app.services.stream_service import ClaudeBlockedError

log = logging.getLogger("dashboard.api.logs")
router = APIRouter(tags=["streaming"])

_STREAM_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


def _streaming_or_403(generator_factory, body: dict):
    try:
        gen = generator_factory(body)
    except ClaudeBlockedError as e:
        return JSONResponse(status_code=403, content={"error": str(e)})
    return StreamingResponse(gen, media_type="text/plain; charset=utf-8", headers=_STREAM_HEADERS)


@router.post("/analyse-bug")
def analyse_bug(body: dict):
    return _streaming_or_403(stream_service.analyse_bug_stream, body)


@router.post("/ki-explain-stream")
def ki_explain_stream(body: dict):
    return _streaming_or_403(stream_service.ki_explain_stream, body)
