"""HTTP contract of backend/app.py: every error is JSON {detail}. Runs the ASGI app directly (no httpx, no network)."""
import asyncio
import json
from urllib.parse import urlencode

from backend import app as api, spherex


def get(path, **params):
    """One GET through the ASGI app. Returns (status, JSON body)."""
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http",
             "path": path, "raw_path": path.encode(), "root_path": "", "query_string": urlencode(params).encode(),
             "headers": [], "client": ("127.0.0.1", 1), "server": ("127.0.0.1", 8001)}
    try:
        asyncio.run(api.app(scope, receive, send))
    except Exception:  # Starlette re-raises an unhandled error after it has sent the 500 answer
        pass
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, json.loads(body)


def test_control_characters_in_the_target_are_a_bad_request_at_once():
    status, body = get("/api/frames", q="Barnard\x00s Star")
    assert status == 400
    assert "control character" in body["detail"]


def test_an_unexpected_error_is_a_json_500_not_plain_text(monkeypatch):
    def bug(*args):
        raise KeyError("frames")
    monkeypatch.setattr(api, "get_frames", bug)
    status, body = get("/api/frames", q="10 20")
    assert status == 500
    assert "KeyError" in body["detail"]


def test_resolve_answers_at_once_for_typed_coordinates():
    assert get("/api/resolve", q="10 20") == (200, {"query": "10 20", "name": None, "ra": 10.0, "dec": 20.0, "pm": None})


def test_resolve_says_plainly_when_no_object_has_the_name(monkeypatch):
    class Nothing:
        ok, status_code, content = True, 200, b"<Sesame><Target><INFO>*** Nothing found ***</INFO></Target></Sesame>"
    monkeypatch.setattr(spherex.requests, "get", lambda url, **kw: Nothing())
    spherex.sesame.cache_clear()
    status, body = get("/api/resolve", q="qwerty12345")
    assert (status, body["detail"][:40]) == (400, "No object called 'qwerty12345' found. Tr")
