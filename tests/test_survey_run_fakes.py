"""Fakes for tests/test_survey_run*.py (no tests in here): deterministic stand-ins for the core stage
(survey.link.process_tile) and the ranking stage (survey.rank.crossmatch_gaia / rank), shaped exactly like the
contract (docs/survey-contract.md). Worker processes import this module by name, so it must stay importable with
tests/ on sys.path and must not import the real survey core.

Behaviour per tile comes from a JSON spec file named by the SURVEY_FAKE_SPEC environment variable (read on every
call, so a test can change it between runs; spawned workers inherit the variable):

    {"log": "/path/calls.jsonl",           every call appends {"k5", "pid", "t", "event", "tag"}
     "tag": "run2",                        copied into the log lines
     "default_sleep": 0.0, "sleep": {"7": 30},
     "fail": [5],                          ValueError
     "net_fail": {"7": 2},                 ConnectionError for the first 2 attempts of tile 7
     "crash": [9],                         os._exit(3) mid-tile (worker dies)
     "gaia_down": false, "gaia_raise": false}
"""
from __future__ import annotations

import json
import os
import time

import numpy as np

YEARS = [f"year{i}" for i in range(1, 12)] + ["addendum"]
XMATCH_CALLS: list[list[str]] = []
RANK_CALLS: list[int] = []


def spec() -> dict:
    path = os.environ.get("SURVEY_FAKE_SPEC")
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_spec(path, **kw) -> str:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(kw, f)
    return str(path)


def calls(log_path, event: str | None = "start", tag: str | None = None) -> list[dict]:
    if not log_path or not os.path.exists(log_path):
        return []
    out = []
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if (event is None or d["event"] == event) and (tag is None or d.get("tag") == tag):
                out.append(d)
    return out


def _log(s: dict, k5: int, event: str) -> None:
    path = s.get("log")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"k5": int(k5), "pid": os.getpid(), "t": time.time(), "event": event,
                                "tag": s.get("tag")}) + "\n")


def n_movers_of(k5: int) -> int:
    return int(k5) % 4


def fake_tile(k5: int) -> dict:
    """Deterministic TileResult for tile k5, with numpy types, over-long tracks and too many decimals on purpose."""
    k5 = int(k5)
    ra0 = (k5 * 0.0293) % 360.0
    dec0 = ((k5 % 170) - 85) * 1.0
    movers = []
    for i in range(n_movers_of(k5)):
        pmra = np.float64(150.0 + 37.123456 * (i + 1) + k5 % 13)
        pmdec = np.float32(-80.55555 * i)
        ra = ra0 + 0.0123456789 * (i + 1)
        dec = dec0 + 0.00987654321 * (i + 1)
        track = [[2014.1 + 0.25 * j, ra + 1e-6 * j, dec - 1e-6 * j] for j in range(40)]
        movers.append({
            "id": f"{k5}-{i:04d}", "k5": k5, "ra": ra, "dec": dec, "epoch": 2019.123456,
            "pmra": pmra, "pmdec": pmdec, "pm": float(np.hypot(pmra, pmdec)), "pm_err": 4.1234,
            "pm_snr": np.float64(10.0 + (k5 % 97) + 3.33333 * i), "chi2r": 1.23456, "n_visits": np.int64(18 + i),
            "span_yr": 9.87654, "w1": 14.123456, "w2": 13.0, "w1w2": None, "plx": None, "plx_err": None,
            "track": np.array(track), "flags": [],
        })
    return {"k5": k5, "center": [ra0, dec0], "years": YEARS, "n_detections": np.int64(1_000_000 + 1000 * k5),
            "n_good": 800_000 + 800 * k5, "n_visits": 22, "n_visit_sources": 50_000 + k5, "n_tracks": 4_000 + k5,
            "n_movers": len(movers), "seconds": 0.01, "movers": movers}


def process_tile(k5, reader=None, years=YEARS, min_visits=6, min_pm=150.0, min_pm_snr=5.0):
    s = spec()
    key = str(int(k5))
    previous = len([c for c in calls(s.get("log")) if c["k5"] == int(k5)])
    _log(s, k5, "start")
    time.sleep(float(s.get("sleep", {}).get(key, s.get("default_sleep", 0.0))))
    if int(k5) in s.get("crash", []):
        os._exit(3)
    if int(k5) in s.get("fail", []):
        raise ValueError(f"synthetic failure in tile {k5}")
    if int(s.get("net_fail", {}).get(key, 0)) > previous:
        raise ConnectionError("AWS Error SLOW_DOWN during GetObject operation: Please reduce your request rate.")
    result = fake_tile(k5)
    _log(s, k5, "end")
    return result


def process_tile_always_fails(k5, reader=None, **kw):
    raise RuntimeError("core is broken")


def gaia_for(mover_id: str) -> dict:
    i = int(mover_id.split("-")[1])
    if i % 2 == 0:
        return {"checked": True, "match": True, "source_id": 4810594479418041856 + i, "sep_arcsec": 0.41234,
                "pm": 650.04, "g": 12.34567}
    return {"checked": True, "match": False, "source_id": None, "sep_arcsec": None, "pm": None, "g": None}


def crossmatch_gaia(movers, cache_dir, tap_url=None, radius_arcsec=3.0, timeout=60):
    s = spec()
    XMATCH_CALLS.append([m["id"] for m in movers])
    if s.get("gaia_raise"):
        raise RuntimeError("TAP service exploded")
    out = []
    for m in movers:
        m = dict(m)
        if s.get("gaia_down"):
            m["gaia"] = {"checked": False, "match": None, "source_id": None, "sep_arcsec": None, "pm": None,
                         "g": None}
        else:
            m["gaia"] = gaia_for(m["id"])
        out.append(m)
    return out


def classify(m) -> str:
    g = m.get("gaia") or {}
    if not g.get("checked"):
        return "not checked"
    return "known (Gaia)" if g.get("match") else "unexplained"


def score_of(m) -> float:
    base = {"unexplained": 3.0, "known (Gaia)": 0.5, "not checked": 1.0}[classify(m)]
    return base + float(m["pm_snr"]) / 1000.0


def rank(movers, top=1000):
    RANK_CALLS.append(len(movers))
    out = []
    for m in movers:
        m = dict(m)
        m["score"] = np.float64(score_of(m))
        m["class"] = classify(m)
        m["reasons"] = [f"moves {m['pm']:.0f} mas/yr", "no Gaia counterpart" if m["class"] == "unexplained"
                        else "Gaia checked"]
        out.append(m)
    out.sort(key=lambda m: -m["score"])
    out = out[:top]
    for i, m in enumerate(out):
        m["rank"] = i + 1
    return out


def rank_raises(movers, top=1000):
    raise RuntimeError("ranking is broken")
