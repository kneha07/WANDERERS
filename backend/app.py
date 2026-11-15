"""HTTP API for the live SPHEREx explorer. Run from the repo root: uvicorn backend.app:app --port 8001

WANDERERS server.js (port 8000) proxies /api/frames, /api/resolve, /api/about and /api/live-health to this server.
Every error answer is JSON {"detail": "..."} (docs/blink/api.md).
"""
import logging

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.about import get_about
from backend.spherex import get_frames, resolve

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


@app.get("/api/resolve")
def resolve_name(q: str = Query(min_length=1, max_length=200)):
    """Name or RA/Dec -> position, in a few seconds. The web app calls this first, so a wrong name fails fast and
    the wait text can name the real step (looking up the name, then getting the images)."""
    coord, name, pm = resolve(checked(q))
    return {"query": q, "name": name, "ra": round(float(coord.ra.deg), 6), "dec": round(float(coord.dec.deg), 6),
            "pm": {"pmra": pm[0], "pmdec": pm[1]} if pm else None}


@app.get("/api/about")
def about(
    q: str | None = Query(None, min_length=1, max_length=200),
    ra: float | None = Query(None, ge=0, lt=360),
    dec: float | None = Query(None, ge=-90, le=90),
):
    """'About this star': catalog facts and one history sentence, by name (q) or by position (ra, dec)."""
    if not ((q is not None and ra is None and dec is None) or (q is None and ra is not None and dec is not None)):
        raise HTTPException(400, "Give a name (q) or a position (ra and dec in degrees), not both.")
    return get_about(q=checked(q)) if q is not None else get_about(ra=ra, dec=dec)


@app.get("/api/frames")
def frames(
    q: str = Query(min_length=1, max_length=200),
    fov: float = Query(5, ge=2, le=15),
    per_group: int = Query(12, ge=1, le=30),
    det: str = Query("", pattern="^(D[1-6])?$"),
):
    return get_frames(checked(q), fov, per_group, det)
