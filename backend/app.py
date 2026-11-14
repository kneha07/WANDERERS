"""HTTP API for the blink tool. Run from the repo root: uvicorn backend.app:app --port 8000"""
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.spherex import get_frames

app = FastAPI(title="SPHEREx blink")


@app.exception_handler(RequestValidationError)
async def bad_params(request: Request, exc: RequestValidationError):
    """Bad query parameters -> HTTP 400 with one readable detail string, like the other errors."""
    detail = "; ".join(f"{e['loc'][-1]}: {e['msg']}" for e in exc.errors())
    return JSONResponse({"detail": detail}, status_code=400)


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
    return get_frames(q, fov, per_group, det)
