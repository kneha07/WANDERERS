"""HTTP API for the live SPHEREx explorer. Run from the repo root: uvicorn backend.app:app --port 8001

WANDERERS server.js (port 8000) proxies /api/frames and /api/live-health to this server.
Every error answer is JSON {"detail": "..."} (docs/blink/api.md).
"""
import logging

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.spherex import get_frames

app = FastAPI(title="SPHEREx blink")
log = logging.getLogger(__name__)


@app.exception_handler(RequestValidationError)
async def bad_params(request: Request, exc: RequestValidationError):
    """Bad query parameters -> HTTP 400 with one readable detail string, like the other errors."""
    detail = "; ".join(f"{e['loc'][-1]}: {e['msg']}" for e in exc.errors())
    return JSONResponse({"detail": detail}, status_code=400)


@app.exception_handler(Exception)
async def server_error(request: Request, exc: Exception):
    """A bug -> HTTP 500 with a JSON detail, never a plain-text page. The traceback goes to the server log."""
    log.error("%s failed", request.url.path, exc_info=exc)
    return JSONResponse({"detail": f"The live server failed ({type(exc).__name__}). Try again; if it fails again,"
                                   " see the server log."}, status_code=500)


def checked(q):
    """The target text, or HTTP 400 when it holds control characters (Sesame would answer 502 after many seconds)."""
    if any(ord(c) < 32 or ord(c) == 127 for c in q):
        raise HTTPException(400, "The target text has a control character. Type a name or RA and Dec.")
    return q


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/frames")
def frames(
    q: str = Query(min_length=1, max_length=200),
    fov: float = Query(5, ge=2, le=15),
    per_group: int = Query(12, ge=1, le=30),
    det: str = Query("", pattern="^(D[1-6])?$"),
):
    return get_frames(checked(q), fov, per_group, det)
