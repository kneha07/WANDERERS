#!/usr/bin/env python3
"""WANDERERS Sky Survey runner: sharded, resumable orchestration of the whole-sky mover search.

Pushes NEOWISE HEALPix order-5 tiles through the core stage (`survey.link.process_tile`), writes one
`<out>/tiles/<k5>.json` per finished tile, keeps `<out>/manifest.json`, and every few minutes (and at the end)
rebuilds `<out>/leaderboard.json` and `<out>/summary.json` from all tile files with the ranking stage
(`survey.rank.crossmatch_gaia` + `survey.rank.rank`). Interface: docs/survey-contract.md.

Run from the repo root (PY = the project's Python, e.g. ../wanderers/.venv/bin/python):

    $PY pipeline/survey/run.py --tiles validation --workers 3 --out app/data/survey

Overnight, whole sky, validation tiles first, then the rest in a seeded random order so coverage grows evenly
(stops scheduling after 9 h and finishes cleanly; rerun the same command to resume):

    caffeinate -i nohup $PY pipeline/survey/run.py --tiles all --order validation-first --workers 3 \\
        --max-hours 9 --out app/data/survey > data/cache/survey_nohup.out 2>&1 &
    tail -f data/cache/survey_run.log

End-to-end smoke test without network (fake core and ranking from the test suite, a few seconds):

    PYTHONPATH=tests $PY pipeline/survey/run.py --tiles list:1-6 --workers 2 --no-gaia --publish-every 0 \\
        --out /tmp/survey-smoke --cache /tmp/survey-smoke/cache --log-file /tmp/survey-smoke/run.log \\
        --process-fn test_survey_run_fakes:process_tile --rank-fn test_survey_run_fakes:rank
    $PY -m json.tool /tmp/survey-smoke/summary.json | head -30

Beyond the contract, summary.json also carries (for the web page) `status` ("running" while a run is processing
tiles, published at the start and every --publish-every minutes; "done" once no run is live), `tiles_planned`
(tiles that will be done when the run completes: progress = tiles_done / tiles_planned), `min_pm` (the core's
motion threshold, mas/yr) and `unique_sources` (linked tracks); leaderboard.json's `n_candidates` counts every
ranked mover, while `candidates` holds the top --top (1000).

Robustness rules: tile files are the source of truth for "done" (the manifest is rebuilt from them if needed);
every file is written to a temp file and renamed (never a partial JSON); each tile runs in a worker process that
is replaced after `--maxtasksperchild` tiles (memory goes back to the OS), killed on `--tile-timeout` or when
its RSS passes `--max-worker-gb`, and a crashed worker costs only its own tile. Network errors are retried with
backoff (per year read and per tile); other failures are recorded in the manifest with the error text and
retried on the next run. The run refuses to start with less than `--min-free-disk-gb` free, stops scheduling
when the disk fills or `--max-hours` is reached, and Ctrl-C (finish running tiles; twice = now) or SIGTERM (now)
always writes the manifest. Exit codes: 0 ok, 1 some tiles failed, 2 usage, 3 disk, 4 out dir locked by another
run, 5 setup error (core not importable), 130/143 interrupted.
"""
from __future__ import annotations

import argparse
import copy
import errno
import hashlib
import heapq
import importlib
import inspect
import json
import logging
import math
import multiprocessing as mp
import os
import random
import re
import resource
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from multiprocessing import connection as mpc
from pathlib import Path
from typing import Any, Callable

_HERE = Path(__file__).resolve().parent
PIPELINE = _HERE.parent
ROOT = PIPELINE.parent
if str(PIPELINE) not in sys.path:
    sys.path.insert(0, str(PIPELINE))

log = logging.getLogger("survey.run")

# ---------------------------------------------------------------------------------------------- constants
NSIDE = 32
N_TILES = 12 * NSIDE * NSIDE                                    # 12,288 HEALPix order-5 tiles
ALL_SKY_DEG2 = 4 * math.pi * (180 / math.pi) ** 2               # 41,252.96 deg2
TILE_AREA_DEG2 = ALL_SKY_DEG2 / N_TILES                         # 3.357 deg2
MAX_TRACK_POINTS = 30
MAX_MOVERS_PER_TILE = 5000
TOP_CANDIDATES = 1000
GB = 1024 ** 3
MB = 1024 ** 2

DEFAULT_OUT = ROOT / "app" / "data" / "survey"
DEFAULT_CACHE = ROOT / "data" / "cache" / "survey_gaia"
DEFAULT_LOG = ROOT / "data" / "cache" / "survey_run.log"
DEFAULT_PROCESS = "survey.link:process_tile"
DEFAULT_XMATCH = "survey.rank:crossmatch_gaia"
DEFAULT_RANK = "survey.rank:rank"

# Targets with known motion (contract): their tiles are the validation set.
KNOWN_MOVERS = [
    ("Barnard's Star", 269.452, 4.693),
    ("Kapteyn's Star", 77.960, -45.044),
    ("WISE 0855-0714", 133.786, -7.244),
    ("Luhman 16", 162.308, -53.318),
    ("Wolf 359", 164.103, 7.003),
    ("Lalande 21185", 165.831, 35.949),
    ("Proxima Centauri", 217.429, -62.679),
    ("61 Cygni", 316.748, 38.764),
    ("Epsilon Indi", 330.840, -56.786),
]

ORDERS = ("given", "random", "validation-first")

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_DISK, EXIT_LOCKED, EXIT_SETUP = 0, 1, 2, 3, 4, 5
EXIT_SIGINT, EXIT_SIGTERM = 130, 143

TILE_KEYS = ["k5", "center", "years", "n_detections", "n_good", "n_visits", "n_visit_sources", "n_tracks",
             "n_movers", "seconds", "movers"]
TILE_COUNT_KEYS = ["n_detections", "n_good", "n_visits", "n_visit_sources", "n_tracks"]
MOVER_KEYS = ["id", "k5", "ra", "dec", "epoch", "pmra", "pmdec", "pm", "pm_err", "pm_snr", "chi2r", "n_visits",
              "span_yr", "w1", "w2", "w1w2", "plx", "plx_err", "track", "flags"]
RANK_KEYS = ["gaia", "score", "reasons", "class", "rank"]
GAIA_KEYS = ["checked", "match", "source_id", "sep_arcsec", "pm", "g"]
SUMMARY_KEYS = ["generated", "tiles_done", "tiles_total", "sky_fraction", "sky_deg2", "detections",
                "good_detections", "visit_sources", "tracks", "movers", "unexplained", "runtime_hours",
                "tiles_per_hour", "detections_per_second", "tiles", "validation", "method", "limits"]
# Added for the web page on top of the contract: run state, progress target, motion threshold, linked sources.
SUMMARY_EXTRA_KEYS = ["status", "tiles_planned", "min_pm", "unique_sources"]
STATUSES = ("running", "done")                # running: a run is processing tiles; done: no run is live any more
LEADERBOARD_KEYS = ["generated", "n_candidates", "candidates"]   # n_candidates = all ranked movers, not the top
DEFAULT_MIN_PM = 150.0                        # mas/yr; process_tile's default per the contract

# Decimal places per field: positions 6 (0.004"), epochs 4 (~1 h), proper motions 1 mas/yr, magnitudes 3.
ROUND = {"ra": 6, "dec": 6, "epoch": 4, "pmra": 1, "pmdec": 1, "pm": 1, "pm_err": 2, "pm_snr": 1, "chi2r": 2,
         "span_yr": 2, "w1": 3, "w2": 3, "w1w2": 3, "plx": 2, "plx_err": 2, "score": 3}
GAIA_ROUND = {"sep_arcsec": 3, "pm": 1, "g": 3}

METHOD = (
    "Each processed tile holds every NEOWISE single-exposure detection from 2014 to 2024 (about 20 million per "
    "tile). Detections that fail basic quality cuts (artefact flags, bad frames, moonlight, weak signal) are dropped. "
    "WISE scanned each part of the sky about every six months, so the detections of one source in one scan are "
    "averaged into a single position per visit. Those positions are linked across the ten years into tracks, "
    "including fast movers of up to 12 arcseconds per year, and a straight-line fit gives each track's proper "
    "motion and its uncertainty. Tracks seen in at least 6 visits that move at least {min_pm} mas per year with at "
    "least 5 sigma are kept as movers. Each mover is compared with Gaia DR3 stars moved to the same date with "
    "their own motion, then ranked: movers that Gaia does not explain, that are red in WISE (a sign of a cold "
    "brown dwarf) and that have long, clean tracks come first. The top of the list is for people to investigate."
)

BASE_LIMITS = [
    "Only the tiles listed here have been searched; the rest of the sky has not been processed yet.",
    "Motions slower than {min_pm} mas per year or faster than 12 arcseconds per year are not searched.",
    "A source must be detected in at least 6 of the roughly 20 WISE visits, so very faint or very red objects "
    "near the detection limit can be missed.",
    "'Unexplained' means no Gaia DR3 star with a matching motion lies within 3 arcseconds. That is expected for "
    "cold brown dwarfs too faint for Gaia, but blends, artefacts next to bright stars and tracks cut at tile edges "
    "can look the same.",
    "A track that crosses a tile edge can be split in two or appear in both tiles.",
    "Motions come from a straight-line fit; parallax is fitted only where a value is given, so very nearby "
    "objects can have slightly biased motions.",
    "A candidate is not a discovery: each one needs a human check of the images and other catalogues first.",
]


# ---------------------------------------------------------------------------------------------- small helpers
def utc_iso(t: float | None = None) -> str:
    return datetime.fromtimestamp(time.time() if t is None else t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def human(n: float) -> str:
    n = float(n)
    for unit, div in (("G", 1e9), ("M", 1e6), ("k", 1e3)):
        if abs(n) >= div:
            return f"{n / div:.1f}{unit}"
    return f"{n:.0f}"


def load_callable(spec: str | Callable) -> Callable:
    """'package.module:function' (or a callable, returned as is)."""
    if callable(spec):
        return spec
    if not isinstance(spec, str) or ":" not in spec:
        raise ValueError(f"expected 'module:function', got {spec!r}")
    mod_name, attr = spec.split(":", 1)
    obj = importlib.import_module(mod_name)
    for part in attr.split("."):
        obj = getattr(obj, part)
    if not callable(obj):
        raise TypeError(f"{spec} is not callable")
    return obj


def clean_json(obj: Any) -> Any:
    """Plain JSON types only: numpy scalars/arrays -> Python, tuples -> lists, NaN/inf -> None."""
    if obj is None or isinstance(obj, (bool, str)):
        return obj
    if isinstance(obj, int):
        return int(obj)
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {str(k): clean_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean_json(v) for v in obj]
    if isinstance(obj, Path):
        return str(obj)
    if type(obj).__module__.split(".")[0] == "numpy":
        if hasattr(obj, "tolist"):
            return clean_json(obj.tolist())
    if hasattr(obj, "item"):
        try:
            return clean_json(obj.item())
        except Exception:
            pass
    if hasattr(obj, "tolist"):
        return clean_json(obj.tolist())
    return str(obj)


def _num(x: Any) -> float | None:
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _r(x: Any, nd: int) -> float | None:
    v = _num(x)
    return None if v is None else round(v, nd) + 0.0         # + 0.0 turns -0.0 into 0.0


def _sig(x: Any, digits: int = 7) -> Any:
    """Generic rounding for fields the contract does not name: 7 significant digits."""
    if isinstance(x, bool) or x is None or isinstance(x, str):
        return x
    if isinstance(x, int):
        return x
    v = _num(x)
    return None if v is None else float(f"{v:.{digits}g}")


def _int(x: Any, default: int | None = 0) -> int | None:
    v = _num(x)
    return default if v is None else int(round(v))


def _is_scalar(v: Any) -> bool:
    return v is None or isinstance(v, (bool, int, float, str))


# ---------------------------------------------------------------------------------------------- atomic files
def atomic_write_text(path: Path | str, text: str, fsync: bool = True) -> None:
    """Write to a temp file next to `path`, fsync, then rename over it: readers see the old file or the new one,
    never a partial one, even if the process is killed mid-write or the disk fills."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.tmp-{os.getpid()}-{random.getrandbits(32):08x}"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            if fsync:
                os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def dumps(obj: Any) -> str:
    return json.dumps(clean_json(obj), allow_nan=False, separators=(",", ":"), ensure_ascii=False)


def atomic_write_json(path: Path | str, obj: Any, fsync: bool = True) -> None:
    atomic_write_text(path, dumps(obj), fsync=fsync)          # serialise first: a bad value never leaves a temp


def cleanup_temp_files(directory: Path, older_than_s: float = 60.0) -> int:
    """Remove leftovers of writes interrupted by a crash ('.name.tmp-pid-xxxx')."""
    n = 0
    if not directory.is_dir():
        return 0
    cutoff = time.time() - older_than_s
    for p in directory.glob(".*.tmp-*"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                n += 1
        except OSError:
            pass
    return n


# ---------------------------------------------------------------------------------------------- tiles & selection
def _healpix():
    import astropy.units as u
    from astropy_healpix import healpix_to_lonlat, lonlat_to_healpix
    return u, lonlat_to_healpix, healpix_to_lonlat


def tile_of(ra: float, dec: float) -> int:
    """HEALPix nested order-5 index; survey.tiles.tile_of when it exists, else astropy_healpix directly."""
    try:
        from survey.tiles import tile_of as core_tile_of
    except ImportError:
        core_tile_of = None
    if core_tile_of is not None:
        return int(core_tile_of(ra, dec))
    u, lonlat_to_healpix, _ = _healpix()
    return int(lonlat_to_healpix(float(ra) * u.deg, float(dec) * u.deg, NSIDE, order="nested"))


def tile_center(k5: int) -> list[float]:
    try:
        from survey.tiles import tile_center as core_center
    except ImportError:
        core_center = None
    if core_center is not None:
        ra, dec = core_center(k5)
        return [float(ra), float(dec)]
    _, _, healpix_to_lonlat = _healpix()
    lon, lat = healpix_to_lonlat(int(k5), NSIDE, order="nested")
    return [float(lon.deg), float(lat.deg)]


def validation_tiles() -> list[int]:
    """Tiles holding the known movers, in KNOWN_MOVERS order, without duplicates."""
    out: list[int] = []
    for _, ra, dec in KNOWN_MOVERS:
        k = tile_of(ra, dec)
        if k not in out:
            out.append(k)
    return out


def _check_k5(k: int) -> int:
    if not 0 <= k < N_TILES:
        raise ValueError(f"tile {k} is outside 0..{N_TILES - 1}")
    return k


def parse_tiles_spec(spec: str, seed: int = 1) -> list[int]:
    """validation | random:N | list:1,2,5-9 | all  ->  tile ids (deterministic for a given seed)."""
    spec = (spec or "").strip()
    if spec == "validation":
        return validation_tiles()
    if spec == "all":
        return list(range(N_TILES))
    if spec.startswith("random:"):
        try:
            n = int(spec.split(":", 1)[1])
        except ValueError:
            raise ValueError(f"bad --tiles {spec!r}: random:N needs an integer N") from None
        if not 1 <= n <= N_TILES:
            raise ValueError(f"bad --tiles {spec!r}: N must be 1..{N_TILES}")
        return random.Random(seed).sample(range(N_TILES), n)
    if spec.startswith("list:"):
        body = spec.split(":", 1)[1]
        out: list[int] = []
        seen: set[int] = set()
        for item in body.split(","):
            item = item.strip()
            if not item:
                continue
            m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", item)
            try:
                ks = range(int(m.group(1)), int(m.group(2)) + 1) if m else [int(item)]
            except ValueError:
                raise ValueError(f"bad --tiles {spec!r}: {item!r} is not a tile number") from None
            if m and int(m.group(2)) < int(m.group(1)):
                raise ValueError(f"bad --tiles {spec!r}: empty range {item!r}")
            for k in ks:
                _check_k5(k)
                if k not in seen:
                    seen.add(k)
                    out.append(k)
        if not out:
            raise ValueError(f"bad --tiles {spec!r}: no tiles listed")
        return out
    raise ValueError(f"bad --tiles {spec!r}: use validation, random:N, list:1,2,3 or all")


def order_tiles(selection: list[int], order: str, seed: int = 1, validation: list[int] | None = None) -> list[int]:
    """given: as selected. random: seeded shuffle. validation-first: the validation tiles, then the rest of the
    selection in a seeded random order (so a long run grows sky coverage evenly)."""
    if order == "given":
        return list(selection)
    rng = random.Random(f"order:{seed}")
    if order == "random":
        out = list(selection)
        rng.shuffle(out)
        return out
    if order == "validation-first":
        val = list(validation if validation is not None else validation_tiles())
        vs = set(val)
        rest = [k for k in selection if k not in vs]
        rng.shuffle(rest)
        return val + rest
    raise ValueError(f"unknown order {order!r} (use one of {', '.join(ORDERS)})")


# ---------------------------------------------------------------------------------------------- compaction
def compact_track(track: Any, cap: int = MAX_TRACK_POINTS) -> list[list]:
    pts = clean_json(track) or []
    if not isinstance(pts, list):
        return []
    pts = [p for p in pts if isinstance(p, list) and len(p) >= 3]
    n = len(pts)
    if n > cap:
        idx = sorted({round(i * (n - 1) / (cap - 1)) for i in range(cap)})   # evenly, keeps first and last
        pts = [pts[i] for i in idx]
    return [[_r(p[0], 4), _r(p[1], 6), _r(p[2], 6)] + [_sig(v) for v in p[3:]] for p in pts]


def compact_gaia(g: Any) -> dict:
    if not isinstance(g, dict):
        g = {}
    g = clean_json(g)
    sid = g.get("source_id")
    out = {"checked": bool(g.get("checked", False)),
           "match": None if g.get("match") is None else bool(g.get("match")),
           "source_id": None if sid in (None, "") else str(sid),   # 64-bit ids lose digits as JS numbers
           "sep_arcsec": _r(g.get("sep_arcsec"), 3), "pm": _r(g.get("pm"), 1), "g": _r(g.get("g"), 3)}
    for k, v in g.items():
        if k not in out and _is_scalar(v):
            out[k] = _sig(v)
    return out


def compact_mover(m: dict, k5: int, idx: int = 0) -> dict:
    """Contract Mover with sensible rounding; scalar extra fields are kept, bulky ones dropped."""
    m = clean_json(dict(m))
    mid = m.get("id")
    out: dict[str, Any] = {"id": str(mid) if mid not in (None, "") else f"{int(k5)}-{idx:04d}", "k5": int(k5)}
    for key in ("ra", "dec", "epoch", "pmra", "pmdec", "pm", "pm_err", "pm_snr", "chi2r"):
        out[key] = _r(m.get(key), ROUND[key])
    if out["pm"] is None and out["pmra"] is not None and out["pmdec"] is not None:
        out["pm"] = round(math.hypot(out["pmra"], out["pmdec"]), 1)
    out["n_visits"] = _int(m.get("n_visits"), None)
    out["span_yr"] = _r(m.get("span_yr"), 2)
    out["w1"], out["w2"] = _r(m.get("w1"), 3), _r(m.get("w2"), 3)
    w1w2 = _num(m.get("w1w2"))
    if w1w2 is None and out["w1"] is not None and out["w2"] is not None:
        w1w2 = out["w1"] - out["w2"]
    out["w1w2"] = _r(w1w2, 3)
    out["plx"], out["plx_err"] = _r(m.get("plx"), 2), _r(m.get("plx_err"), 2)
    out["track"] = compact_track(m.get("track"))
    flags = m.get("flags") or []
    out["flags"] = [str(f) for f in flags] if isinstance(flags, list) else [str(flags)]
    if "gaia" in m:
        out["gaia"] = compact_gaia(m["gaia"])
    if "score" in m:
        out["score"] = _r(m["score"], ROUND["score"])
    if "reasons" in m:
        rs = m["reasons"] or []
        out["reasons"] = [str(r) for r in rs] if isinstance(rs, list) else [str(rs)]
    if "class" in m:
        out["class"] = str(m["class"])
    if "rank" in m:
        out["rank"] = _int(m["rank"], None)
    for k, v in m.items():
        if k not in out and _is_scalar(v):
            out[k] = _sig(v)
    return out


def compact_tile(result: Any, k5: int, seconds: float | None = None) -> dict:
    """TileResult as written to tiles/<k5>.json: contract keys first, numbers rounded, tracks capped at 30 points."""
    if not isinstance(result, dict):
        raise TypeError(f"process_tile({k5}) returned {type(result).__name__}, expected dict")
    k5 = int(k5)
    movers_in = result.get("movers") or []
    if not isinstance(movers_in, list):
        movers_in = list(movers_in)
    n_movers = len(movers_in)
    truncated = n_movers > MAX_MOVERS_PER_TILE
    if truncated:                                       # pathological tile: keep the strongest movers only
        movers_in = sorted(movers_in, key=lambda m: -(_num(m.get("pm_snr")) or 0.0))[:MAX_MOVERS_PER_TILE]
    movers = [compact_mover(m, k5, i) for i, m in enumerate(movers_in)]
    center = clean_json(result.get("center"))
    if not (isinstance(center, list) and len(center) >= 2):
        center = tile_center(k5)
    tile: dict[str, Any] = {
        "k5": k5,
        "center": [_r(center[0], 6), _r(center[1], 6)],
        "years": [str(y) for y in (clean_json(result.get("years")) or [])],
    }
    for key in TILE_COUNT_KEYS:
        tile[key] = _int(result.get(key), 0)
    tile["n_movers"] = n_movers
    tile["seconds"] = _r(seconds if seconds is not None else result.get("seconds"), 2)
    tile["movers"] = movers
    for k, v in clean_json({k: v for k, v in result.items() if k not in tile}).items():
        if _is_scalar(v):
            tile[k] = _sig(v)
    if truncated:
        tile["movers_truncated"] = True
    return tile


# ---------------------------------------------------------------------------------------------- tile files & manifest
TILE_NAME = re.compile(r"^(\d+)\.json$")


def scan_tiles(tiles_dir: Path) -> dict[int, Path]:
    out: dict[int, Path] = {}
    if not tiles_dir.is_dir():
        return out
    for p in tiles_dir.iterdir():
        m = TILE_NAME.match(p.name)
        if m and 0 <= int(m.group(1)) < N_TILES:
            out[int(m.group(1))] = p
    return out


def read_tile_file(path: Path) -> dict | None:
    """The tile dict, or None when the file is unreadable or not a TileResult for the k5 in its name."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    m = TILE_NAME.match(Path(path).name)
    if not (isinstance(data, dict) and m and data.get("k5") == int(m.group(1))
            and isinstance(data.get("movers"), list)):
        return None
    return data


def new_manifest() -> dict:
    now = utc_iso()
    return {"version": 1, "created": now, "updated": now, "tiles_total": N_TILES, "done": {}, "failed": {},
            "runs": []}


def load_manifest(out: Path, readonly: bool = False) -> dict:
    """The manifest, or a fresh one. A corrupt manifest is moved aside (never trusted, never fatal)."""
    p = Path(out) / "manifest.json"
    if not p.exists():
        return new_manifest()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("manifest is not an object")
        base = new_manifest()
        for key in ("done", "failed"):
            if not isinstance(data.get(key, {}), dict):
                raise ValueError(f"manifest {key} is not an object")
        if not isinstance(data.get("runs", []), list):
            raise ValueError("manifest runs is not a list")
        base.update(data)
        return base
    except (OSError, ValueError, UnicodeDecodeError) as e:
        if not readonly:
            backup = p.with_name(f"manifest.corrupt-{int(time.time())}.json")
            try:
                os.replace(p, backup)
            except OSError:
                pass
            log.warning("manifest unreadable (%s); moved to %s and rebuilding from tile files", e, backup.name)
        return new_manifest()


def reconcile(manifest: dict, tiles_dir: Path) -> dict:
    """Make manifest['done'] agree with the tile files on disk (the files win). Unreadable tile files are renamed
    to <k5>.json.bad and redone. Returns counts {added, dropped, bad}."""
    files = scan_tiles(tiles_dir)
    done, failed = manifest["done"], manifest["failed"]
    added = dropped = bad = 0
    for key in list(done):
        try:
            k5 = int(key)
        except ValueError:
            k5 = -1
        if k5 not in files:
            del done[key]
            dropped += 1
    for k5, p in files.items():
        key = str(k5)
        entry = done.get(key)
        try:
            size = p.stat().st_size
        except OSError:
            continue
        if entry and entry.get("bytes") == size:
            failed.pop(key, None)
            continue                                    # same size as when we wrote it: trust without parsing
        tile = read_tile_file(p)
        if tile is None:
            try:
                os.replace(p, p.with_name(p.name + ".bad"))
            except OSError:
                pass
            done.pop(key, None)
            bad += 1
            continue
        done[key] = {"seconds": tile.get("seconds"), "n_detections": _int(tile.get("n_detections")),
                     "n_movers": _int(tile.get("n_movers", len(tile["movers"]))), "bytes": size,
                     "finished": utc_iso(p.stat().st_mtime), "run": (entry or {}).get("run")}
        failed.pop(key, None)
        if not entry:
            added += 1
    return {"added": added, "dropped": dropped, "bad": bad}


def acquire_lock(out: Path) -> Path | None:
    """One runner per output directory. A lock left by a dead process is taken over."""
    p = Path(out) / ".run.lock"
    for _ in range(3):
        try:
            fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            try:
                pid = int(p.read_text().split()[0])
            except (OSError, ValueError, IndexError):
                pid = None
            if pid and pid != os.getpid() and _pid_alive(pid):
                return None
            log.warning("removing stale lock %s (pid %s is gone)", p, pid)
            try:
                p.unlink()
            except FileNotFoundError:
                pass
            continue
        with os.fdopen(fd, "w") as f:
            f.write(f"{os.getpid()} {utc_iso()}\n")
        return p
    return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


# ---------------------------------------------------------------------------------------------- machine guards
def disk_free_bytes(path: Path | str) -> int:
    p = Path(path).resolve()
    while not p.exists() and p != p.parent:
        p = p.parent
    return shutil.disk_usage(p).free


def available_memory_bytes() -> int | None:
    """Memory the OS can hand out without swapping (psutil, /proc/meminfo or vm_stat); None if unknown."""
    try:
        import psutil  # type: ignore
        return int(psutil.virtual_memory().available)
    except Exception:
        pass
    try:
        if sys.platform.startswith("linux"):
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
        if sys.platform == "darwin":
            text = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5).stdout
            page = int(re.search(r"page size of (\d+) bytes", text).group(1))
            pages = 0
            for name in ("free", "inactive", "speculative", "purgeable"):
                m = re.search(rf"Pages {name}:\s+(\d+)", text)
                pages += int(m.group(1)) if m else 0
            return pages * page
    except Exception:
        return None
    return None


def total_memory_bytes() -> int | None:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return None


def rss_bytes(pids: list[int]) -> dict[int, int]:
    """Current resident memory per pid (psutil, else one `ps` call)."""
    pids = [int(p) for p in pids if p]
    if not pids:
        return {}
    try:
        import psutil  # type: ignore
        out = {}
        for p in pids:
            try:
                out[p] = int(psutil.Process(p).memory_info().rss)
            except Exception:
                pass
        return out
    except ImportError:
        pass
    try:
        text = subprocess.run(["ps", "-o", "pid=,rss=", "-p", ",".join(map(str, pids))], capture_output=True,
                              text=True, timeout=5).stdout
    except Exception:
        return {}
    return parse_ps_rss(text)


def parse_ps_rss(text: str) -> dict[int, int]:
    out = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            out[int(parts[0])] = int(parts[1]) * 1024          # ps reports KiB
    return out


def peak_rss_bytes() -> int:
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(r if sys.platform == "darwin" else r * 1024)   # bytes on macOS, KiB on Linux


# ---------------------------------------------------------------------------------------------- errors & retries
_NETWORK_HINTS = ("throttl", "slow down", "slowdown", "slow_down", "too many requests", "429", "service unavailable",
                  "service_unavailable", "http status 5", "internal_failure", "request_timeout", "timed out",
                  "timeout was reached", "timeout", "network_connection", "connection reset", "connection refused",
                  "connection aborted", "connection closed", "reset by peer", "broken pipe", "curlcode",
                  "name resolution", "could not resolve", "unreachable", "temporarily", "temporary failure",
                  "eof occurred", "ssl")


def is_network_error(exc: BaseException, _depth: int = 0) -> bool:
    """True for errors worth retrying after a pause: connection problems, timeouts, S3 throttling."""
    if isinstance(exc, FileNotFoundError):
        return False
    if isinstance(exc, OSError) and exc.errno in (errno.ENOENT, errno.ENOSPC, errno.EACCES):
        return False
    if isinstance(exc, (ConnectionError, TimeoutError, socket.timeout, socket.gaierror)):
        return True
    try:
        import urllib.error
        if isinstance(exc, urllib.error.URLError):
            return True
    except ImportError:
        pass
    mod = type(exc).__module__.split(".")[0]
    if isinstance(exc, OSError) or mod in ("pyarrow", "botocore", "urllib3", "requests", "http", "aiohttp"):
        msg = str(exc).lower()
        if any(h in msg for h in _NETWORK_HINTS):
            return True
    cause = exc.__cause__ or exc.__context__
    return bool(cause is not None and _depth < 3 and is_network_error(cause, _depth + 1))


def classify_error(exc: BaseException) -> str:
    if isinstance(exc, MemoryError):
        return "memory"
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return "disk"
    if is_network_error(exc):
        return "network"
    return "error"


def backoff_delay(attempt: int, base: float, cap: float, rng: random.Random | None = None) -> float:
    """base * 2**(attempt-1), capped, with +-25% jitter (attempt counts from 1)."""
    d = min(cap, base * (2 ** max(0, attempt - 1)))
    return d * (0.75 + 0.5 * (rng or random).random())


class RetryingReader:
    """reader(k5, year) for process_tile: retries network errors with exponential backoff, per year, so one
    throttled request does not redo the whole tile. Uses one S3 filesystem per worker (connection reuse,
    SDK-level retries and timeouts) when wrapping survey.tiles.read_tile_year."""

    def __init__(self, base: Callable | None = None, attempts: int = 5, backoff: float = 2.0, max_backoff: float = 60.0,
                 sleep: Callable[[float], None] = time.sleep, make_fs: Callable | None = None):
        self.base = base
        self.attempts = max(1, int(attempts))
        self.backoff, self.max_backoff = backoff, max_backoff
        self.sleep = sleep
        self.make_fs = make_fs
        self.fs = None
        self.retries = 0                                  # retries used (for the progress log)

    def _resolve(self) -> Callable:
        if self.base is None:
            from survey.tiles import read_tile_year
            self.base = read_tile_year
            if self.make_fs is None:
                self.make_fs = make_s3_fs
        if self.fs is None and self.make_fs is not None:
            self.fs = self.make_fs()
            self.make_fs = None
        return self.base

    def __call__(self, k5: int, year: str, **kw):
        base = self._resolve()
        if self.fs is not None and "fs" not in kw:
            kw["fs"] = self.fs
        for attempt in range(1, self.attempts + 1):
            try:
                return base(k5, year, **kw)
            except Exception as e:
                if attempt >= self.attempts or not is_network_error(e):
                    raise
                delay = backoff_delay(attempt, self.backoff, self.max_backoff)
                self.retries += 1
                logging.getLogger("survey.run.worker").warning(
                    "tile %s %s: %s: %s; retry %d/%d in %.1f s", k5, year, type(e).__name__, str(e)[:200],
                    attempt, self.attempts - 1, delay)
                self.sleep(delay)


def make_s3_fs():
    """Anonymous S3 filesystem for the IRSA bucket with timeouts and SDK retries (None if unavailable)."""
    try:
        import pyarrow.fs as pafs
    except ImportError:
        return None
    kw: dict[str, Any] = dict(anonymous=True, region="us-west-2", connect_timeout=20, request_timeout=120)
    try:
        kw["retry_strategy"] = pafs.AwsStandardS3RetryStrategy(max_attempts=5)
        return pafs.S3FileSystem(**kw)
    except Exception:
        kw.pop("retry_strategy", None)
        try:
            return pafs.S3FileSystem(**kw)
        except Exception:
            return None


# ---------------------------------------------------------------------------------------------- worker process
@dataclass
class WorkerConfig:
    tiles_dir: str
    process_fn: Any = DEFAULT_PROCESS               # 'module:function' or a picklable module-level callable
    read_retries: int = 5
    read_backoff: float = 2.0
    log_file: str | None = None
    parent_pid: int = 0
    threads: int = 1


def _setup_worker_logging(wcfg: WorkerConfig) -> None:
    lg = logging.getLogger("survey.run.worker")
    lg.handlers.clear()
    lg.setLevel(logging.INFO)
    lg.propagate = False
    fmt = logging.Formatter(f"%(asctime)s worker {os.getpid()} %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(fmt)
    lg.addHandler(h)
    if wcfg.log_file:
        try:
            fh = logging.FileHandler(wcfg.log_file, encoding="utf-8")
            fh.setFormatter(fmt)
            lg.addHandler(fh)
        except OSError:
            pass


def run_one_tile(k5: int, process_fn: Callable, reader: Callable, tiles_dir: Path) -> dict:
    """process_tile -> compact -> atomic write of tiles/<k5>.json. Returns the small info dict sent to main."""
    t0 = time.monotonic()
    result = process_fn(k5, reader=reader)
    seconds = time.monotonic() - t0
    tile = compact_tile(result, k5, seconds)
    path = Path(tiles_dir) / f"{k5}.json"
    text = dumps(tile)
    atomic_write_text(path, text)
    return {"k5": int(k5), "seconds": round(seconds, 2), "n_detections": tile["n_detections"],
            "n_movers": tile["n_movers"], "bytes": len(text.encode("utf-8")),
            "peak_rss_mb": round(peak_rss_bytes() / MB, 1), "pid": os.getpid()}


def _worker_main(wid: int, conn, wcfg: WorkerConfig) -> None:
    """Worker loop: receive ('tile', k5, attempt) or None (retire); reply ('done', k5, info) or
    ('error', k5, kind, text). Exits when the main process disappears (orphan guard)."""
    try:
        signal.signal(signal.SIGINT, signal.SIG_IGN)       # Ctrl-C is the main process's decision
    except (ValueError, OSError):
        pass
    _setup_worker_logging(wcfg)
    process_fn = None
    reader = RetryingReader(attempts=wcfg.read_retries, backoff=wcfg.read_backoff)
    try:
        conn.send(("ready", os.getpid()))
    except (OSError, EOFError):
        return
    while True:
        try:
            if not conn.poll(2.0):
                if wcfg.parent_pid and os.getppid() != wcfg.parent_pid:
                    return                                    # main process is gone
                continue
            msg = conn.recv()
        except (EOFError, OSError):
            return
        if msg is None:
            return
        _, k5, _attempt = msg
        try:
            if process_fn is None:
                process_fn = load_callable(wcfg.process_fn)
            reader.retries = 0
            info = run_one_tile(k5, process_fn, reader, Path(wcfg.tiles_dir))
            info["read_retries"] = reader.retries
            reply = ("done", k5, info)
        except Exception as e:  # noqa: BLE001 - every failure is reported, the worker survives
            tb = traceback.format_exc(limit=6)
            reply = ("error", k5, classify_error(e), f"{type(e).__name__}: {e}"[:2000], tb[-3000:])
        try:
            conn.send(reply)
        except (OSError, EOFError):
            return


class _Slot:
    def __init__(self, wid: int, proc, conn):
        self.wid, self.proc, self.conn = wid, proc, conn
        self.pid = proc.pid
        self.task: tuple[int, int] | None = None
        self.started = 0.0
        self.n_tasks = 0
        self.rss = 0
        self.peak_rss = 0


class WorkerPool:
    """A process pool with maxtasksperchild that, unlike multiprocessing.Pool, knows which worker runs which tile:
    it can kill one stuck or oversized worker, notices a worker that died (segfault, OOM kill) instead of waiting
    forever, and gives each worker its own pipe, so killing one never corrupts a shared queue."""

    def __init__(self, n: int, wcfg: WorkerConfig, maxtasksperchild: int = 3, ctx=None, clock=time.monotonic):
        self.ctx = ctx or mp.get_context("spawn")
        self.wcfg = wcfg
        self.maxtasks = max(1, int(maxtasksperchild))
        self.clock = clock
        self.retiring: list[tuple[Any, float]] = []
        self.spawned = 0
        self._next_wid = 0
        self.slots: list[_Slot] = [self._spawn() for _ in range(max(1, int(n)))]

    def _spawn(self) -> _Slot:
        parent, child = self.ctx.Pipe(duplex=True)
        wid = self._next_wid
        self._next_wid += 1
        p = self.ctx.Process(target=_worker_main, args=(wid, child, self.wcfg), name=f"survey-worker-{wid}")
        p.start()
        child.close()                                        # so a dead worker reads as EOF here
        self.spawned += 1
        return _Slot(wid, p, parent)

    def idle(self) -> list[_Slot]:
        return [s for s in self.slots if s.task is None]

    def busy(self) -> list[_Slot]:
        return [s for s in self.slots if s.task is not None]

    def assign(self, slot: _Slot, k5: int, attempt: int) -> _Slot:
        for _ in range(2):
            try:
                slot.conn.send(("tile", int(k5), int(attempt)))
                slot.task, slot.started = (int(k5), int(attempt)), self.clock()
                slot.rss = 0
                return slot
            except (OSError, EOFError):                     # died while idle: replace and try again
                slot = self._replace(slot, kill=True)
        raise RuntimeError("could not start a worker process")

    def _replace(self, slot: _Slot, kill: bool = False, respawn: bool = True) -> _Slot | None:
        if kill and slot.proc.is_alive():
            slot.proc.kill()
        slot.proc.join(timeout=5)
        try:
            slot.conn.close()
        except OSError:
            pass
        i = self.slots.index(slot)
        if not respawn:
            self.slots.pop(i)
            return None
        new = self._spawn()
        self.slots[i] = new
        return new

    def kill(self, slot: _Slot, respawn: bool = True) -> None:
        self._replace(slot, kill=True, respawn=respawn)

    def retire(self, slot: _Slot, respawn: bool = True) -> None:
        """Fresh process for the next tiles: memory held by the old one goes back to the OS."""
        try:
            slot.conn.send(None)
        except (OSError, EOFError):
            pass
        self.retiring.append((slot.proc, self.clock()))
        try:
            slot.conn.close()
        except OSError:
            pass
        i = self.slots.index(slot)
        if respawn:
            self.slots[i] = self._spawn()
        else:
            self.slots.pop(i)
        self.reap()

    def reap(self, force_after: float = 30.0) -> None:
        keep = []
        for proc, t in self.retiring:
            proc.join(timeout=0)
            if proc.is_alive():
                if self.clock() - t > force_after:
                    proc.kill()
                    proc.join(timeout=2)
                else:
                    keep.append((proc, t))
        self.retiring = keep

    def poll(self, timeout: float) -> list[tuple]:
        """Wait up to `timeout` s; return events ('done', slot, k5, attempt, info, secs),
        ('error', slot, k5, attempt, kind, text, tb, secs), ('died', slot, k5|None, attempt, exitcode, secs).
        A 'died' slot has already been replaced by a fresh worker."""
        waitables = {}
        for s in self.slots:
            waitables[s.conn] = s
            waitables[s.proc.sentinel] = s
        try:
            ready = mpc.wait(list(waitables), timeout)
        except OSError:
            ready = []
        touched = []
        for r in ready:
            s = waitables[r]
            if s not in touched:
                touched.append(s)
        events = []
        for s in touched:
            if s not in self.slots:
                continue
            dead = False
            while True:
                try:
                    if not s.conn.poll():
                        break
                    msg = s.conn.recv()
                except (EOFError, OSError):
                    dead = True
                    break
                ev = self._message(s, msg)
                if ev:
                    events.append(ev)
            if not dead and not s.proc.is_alive():
                s.proc.join(timeout=1)
                dead = True
            if dead:
                task, secs = s.task, self.clock() - s.started
                s.proc.join(timeout=2)
                code = s.proc.exitcode
                self._replace(s, kill=True)
                events.append(("died", s, task[0] if task else None, task[1] if task else 0, code, secs))
        self.reap()
        return events

    def _message(self, s: _Slot, msg) -> tuple | None:
        kind = msg[0]
        if kind == "ready":
            return None
        task, secs = s.task, self.clock() - s.started
        attempt = task[1] if task else 1
        s.task = None
        s.n_tasks += 1
        if kind == "done":
            return ("done", s, msg[1], attempt, msg[2], secs)
        if kind == "error":
            return ("error", s, msg[1], attempt, msg[2], msg[3], msg[4] if len(msg) > 4 else "", secs)
        return None

    def shutdown(self, graceful: bool = True) -> None:
        for s in list(self.slots):
            if graceful and s.task is None:
                try:
                    s.conn.send(None)
                except (OSError, EOFError):
                    pass
            else:
                s.proc.kill()
        deadline = self.clock() + (10.0 if graceful else 3.0)
        for s in list(self.slots):
            s.proc.join(timeout=max(0.0, deadline - self.clock()))
            if s.proc.is_alive():
                s.proc.kill()
                s.proc.join(timeout=2)
            try:
                s.conn.close()
            except OSError:
                pass
        self.slots = []
        for proc, _ in self.retiring:
            proc.join(timeout=2 if graceful else 0)
            if proc.is_alive():
                proc.kill()
                proc.join(timeout=2)
        self.retiring = []


# ---------------------------------------------------------------------------------------------- publishing
GAIA_UNCHECKED = {"checked": False, "match": None, "source_id": None, "sep_arcsec": None, "pm": None, "g": None}


def _gaia_key(movers: list[dict]) -> str:
    rows = [[m.get("id"), m.get("ra"), m.get("dec"), m.get("epoch"), m.get("pmra"), m.get("pmdec")] for m in movers]
    return hashlib.sha1(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def _gaia_cache_path(cache_dir: Path, k5: int) -> Path:
    return Path(cache_dir) / "run_tiles" / f"{int(k5)}.json"


def gaia_cache_get(cache_dir: Path | None, k5: int, movers: list[dict]) -> list[dict] | None:
    if cache_dir is None:
        return None
    try:
        data = json.loads(_gaia_cache_path(cache_dir, k5).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if data.get("key") != _gaia_key(movers) or len(data.get("gaia", [])) != len(movers):
        return None
    return data["gaia"]


def gaia_cache_put(cache_dir: Path | None, k5: int, movers: list[dict], gaia: list[dict]) -> None:
    if cache_dir is None:
        return
    try:
        atomic_write_json(_gaia_cache_path(cache_dir, k5), {"key": _gaia_key(movers), "gaia": gaia}, fsync=False)
    except OSError as e:
        log.warning("could not cache the Gaia check of tile %s: %s", k5, e)


def crossmatch_tile(xmatch_fn: Callable, movers: list[dict], cache_dir: Path) -> tuple[list[dict], bool]:
    """Gaia dicts for the movers of one tile (in order) and whether every mover was checked."""
    try:
        res = xmatch_fn([dict(m) for m in movers], str(cache_dir) if cache_dir is not None else None)
    except Exception as e:  # noqa: BLE001 - the contract says it should not raise; be safe anyway
        log.warning("Gaia check failed (%s: %s)", type(e).__name__, str(e)[:200])
        return [dict(GAIA_UNCHECKED) for _ in movers], False
    by_id = {}
    for m in res or []:
        if isinstance(m, dict) and "id" in m:
            by_id[str(m["id"])] = m.get("gaia")
    gaia = [compact_gaia(by_id.get(str(m["id"])) or GAIA_UNCHECKED) for m in movers]
    return gaia, all(g["checked"] for g in gaia)


def fallback_rank(movers: list[dict], top: int = TOP_CANDIDATES) -> list[dict]:
    """Used only when survey.rank is missing or fails: orders by motion signal-to-noise."""
    out = []
    for m in movers:
        m = dict(m)
        g = m.get("gaia") or {}
        if not g.get("checked"):
            cls = "not checked"
        elif g.get("match"):
            cls = "known (Gaia)"
        else:
            cls = "unexplained"
        snr = _num(m.get("pm_snr")) or 0.0
        m["score"] = round(math.log10(1 + max(snr, 0.0)), 3)
        m["reasons"] = ["ranking module unavailable: ordered by how clearly the motion is measured"]
        m["class"] = cls
        out.append(m)
    out.sort(key=lambda m: (-m["score"], str(m.get("id"))))
    out = out[:top]
    for i, m in enumerate(out):
        m["rank"] = i + 1
    return out


def _resolve_optional(spec, label: str) -> Callable | None:
    try:
        return load_callable(spec)
    except Exception as e:  # noqa: BLE001
        log.warning("%s unavailable (%s: %s)", label, type(e).__name__, e)
        return None


def load_validation(out: Path) -> dict | None:
    p = Path(out) / "validation.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.warning("validation.json unreadable: %s", e)
        return None
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("summary"), dict):
        return clean_json(data["summary"])
    return {k: clean_json(v) for k, v in data.items() if len(dumps(v)) <= 5000}   # keep summary.json small


def run_totals(runs: list[dict]) -> tuple[float, int, int]:
    secs = sum(_num(r.get("wall_seconds")) or 0.0 for r in runs if isinstance(r, dict))
    tiles = sum(_int(r.get("tiles"), 0) for r in runs if isinstance(r, dict))
    det = sum(_int(r.get("detections"), 0) for r in runs if isinstance(r, dict))
    return secs, tiles, det


def core_min_pm(process_fn: Any = DEFAULT_PROCESS) -> float:
    """The motion threshold the core uses: process_tile's `min_pm` default (the runner never overrides it)."""
    try:
        p = inspect.signature(load_callable(process_fn)).parameters.get("min_pm")
        if p is not None and _num(p.default) is not None:
            return float(p.default)
    except Exception:  # noqa: BLE001 - core not importable: the contract value
        pass
    return DEFAULT_MIN_PM


def run_in_progress(out: Path) -> bool:
    """True when another live process holds the output folder's run lock."""
    try:
        pid = int((Path(out) / ".run.lock").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return False
    return pid != os.getpid() and _pid_alive(pid)


def build_summary(totals: dict, rows: list[list[int]], runs: list[dict], validation: dict | None,
                  extra_limits: list[str], generated: str, status: str = "done", tiles_planned: int | None = None,
                  min_pm: float = DEFAULT_MIN_PM) -> dict:
    """summary.json: the contract keys in contract order, then SUMMARY_EXTRA_KEYS.
    tiles_planned = tiles that will be done when the current (or last) run completes: the tiles already done plus
    the run's selection, so tiles_done / tiles_planned is a progress fraction that ends at 1 (or below, if some
    tiles failed)."""
    tiles_done = len(rows)
    secs, run_tiles, run_det = run_totals(runs)
    hours = secs / 3600.0
    if tiles_planned is None:
        last = runs[-1] if runs and isinstance(runs[-1], dict) else {}
        tiles_planned = _int(last.get("planned"), 0)
    pm_text = f"{min_pm:g}"
    return {
        "generated": generated,
        "tiles_done": tiles_done,
        "tiles_total": N_TILES,
        "sky_fraction": round(tiles_done / N_TILES, 6),
        "sky_deg2": round(tiles_done * TILE_AREA_DEG2, 1),
        "detections": int(totals.get("n_detections", 0)),
        "good_detections": int(totals.get("n_good", 0)),
        "visit_sources": int(totals.get("n_visit_sources", 0)),
        "tracks": int(totals.get("n_tracks", 0)),
        "movers": int(totals.get("movers", 0)),
        "unexplained": int(totals.get("unexplained", 0)),
        "runtime_hours": round(hours, 2),
        "tiles_per_hour": round(run_tiles / hours, 1) if secs > 0 else 0.0,
        "detections_per_second": int(round(run_det / secs)) if secs > 0 else 0,
        "tiles": sorted(rows),
        "validation": validation,
        "method": METHOD.format(min_pm=pm_text),
        "limits": [t.format(min_pm=pm_text) for t in BASE_LIMITS] + list(extra_limits),
        "status": status if status in STATUSES else "done",
        "tiles_planned": max(int(tiles_planned), tiles_done),
        "min_pm": float(min_pm),
        "unique_sources": int(totals.get("n_tracks", 0)),      # every linked track is one distinct source
    }


class PublishAborted(Exception):
    pass


def publish(out: Path | str, *, cache_dir: Path | str | None = DEFAULT_CACHE, use_gaia: bool = True,
            xmatch_fn: Callable | str | None = None, rank_fn: Callable | str | None = None,
            top: int = TOP_CANDIDATES, gaia_budget_s: float | None = None, runs: list[dict] | None = None,
            should_abort: Callable[[], bool] | None = None, clock: Callable[[], float] = time.monotonic,
            gaia_fail_limit: int = 3, status: str | None = None, tiles_planned: int | None = None,
            min_pm: float | None = None) -> dict:
    """Rebuild leaderboard.json and summary.json from every tiles/<k5>.json in `out`.

    Streams the tile files (memory stays bounded by `top`), checks movers against Gaia per tile (answers cached
    under cache_dir/run_tiles; network time limited by gaia_budget_s; after `gaia_fail_limit` failing tiles in a
    row the service is left alone until the next publish), ranks per tile and keeps the global top `top`
    (leaderboard order: score, then pm_snr, then id, like survey.rank.rank). `n_candidates` is the number of
    ranked movers over all tiles. status / tiles_planned / min_pm default to: "running" if a live run holds the
    lock else "done"; the last run's plan; the last run's threshold (else the core's default). Returns the summary."""
    out = Path(out)
    if status is None:
        status = "running" if run_in_progress(out) else "done"
    cache = Path(cache_dir) if cache_dir is not None else None
    rank_callable = _resolve_optional(rank_fn or DEFAULT_RANK, "ranking (survey.rank.rank)") or fallback_rank
    xmatch = _resolve_optional(xmatch_fn or DEFAULT_XMATCH, "Gaia check (survey.rank.crossmatch_gaia)") \
        if use_gaia else None
    if runs is None:
        runs = load_manifest(out, readonly=True).get("runs", [])
    if min_pm is None:
        last = runs[-1] if runs and isinstance(runs[-1], dict) else {}
        min_pm = _num(last.get("min_pm"))
        if min_pm is None:
            min_pm = core_min_pm()
    deadline = None if gaia_budget_s is None else clock() + max(0.0, gaia_budget_s)
    totals = {k: 0 for k in TILE_COUNT_KEYS + ["movers", "unexplained"]}
    rows: list[list[int]] = []
    pool: list[tuple[float, float, str, int, dict]] = []      # (-score, -pm_snr, id, k5, mover): ascending = best
    n_ranked = 0
    seq = 0
    stats = {"tiles_with_movers": 0, "unchecked_tiles": 0, "queries": 0, "fail_streak": 0, "rank_errors": 0}

    def trim(n: int) -> None:
        pool.sort(key=lambda e: e[:3])
        del pool[n:]

    for k5, path in sorted(scan_tiles(out / "tiles").items()):
        if should_abort and should_abort():
            raise PublishAborted()
        tile = read_tile_file(path)
        if tile is None:
            log.warning("skipping unreadable tile file %s", path.name)
            continue
        for key in TILE_COUNT_KEYS:
            totals[key] += _int(tile.get(key), 0)
        movers = [m for m in tile["movers"] if isinstance(m, dict)]
        n_movers = _int(tile.get("n_movers", len(movers)), len(movers))
        totals["movers"] += n_movers
        n_unexplained = 0
        if movers:
            stats["tiles_with_movers"] += 1
            gaia = None
            if xmatch is not None:
                gaia = gaia_cache_get(cache, k5, movers)
                if gaia is None and stats["fail_streak"] < gaia_fail_limit \
                        and (deadline is None or clock() < deadline) and not (should_abort and should_abort()):
                    stats["queries"] += 1
                    gaia, ok = crossmatch_tile(xmatch, movers, cache)
                    if ok:
                        stats["fail_streak"] = 0
                        gaia_cache_put(cache, k5, movers, gaia)
                    else:
                        stats["fail_streak"] += 1
                        if stats["fail_streak"] == gaia_fail_limit:
                            log.warning("Gaia check failing on %d tiles in a row; skipping it until the next publish",
                                        gaia_fail_limit)
            if gaia is None or not all(g.get("checked") for g in gaia):
                stats["unchecked_tiles"] += 1
            for i, m in enumerate(movers):
                m["gaia"] = dict(gaia[i]) if gaia is not None else dict(GAIA_UNCHECKED)
            try:
                ranked = rank_callable([dict(m) for m in movers], top=max(len(movers), 1))
                if not isinstance(ranked, list):
                    raise TypeError(f"rank returned {type(ranked).__name__}")
            except Exception as e:  # noqa: BLE001
                stats["rank_errors"] += 1
                if stats["rank_errors"] == 1:
                    log.error("rank failed on tile %s (%s: %s); using the fallback order", k5, type(e).__name__, e)
                ranked = fallback_rank([dict(m) for m in movers], top=max(len(movers), 1))
            for m in ranked:
                if not isinstance(m, dict):
                    continue
                if m.get("class") == "unexplained":
                    n_unexplained += 1
                score, snr = _num(m.get("score")), _num(m.get("pm_snr"))
                seq += 1
                n_ranked += 1
                pool.append((-score if score is not None else math.inf, -snr if snr is not None else math.inf,
                             str(m.get("id", seq)), k5, m))
            if len(pool) > 2 * top + 256:
                trim(top)
        totals["unexplained"] += n_unexplained
        rows.append([k5, n_movers, n_unexplained])
    trim(top)
    candidates = []
    for i, (_, _, _, k5, m) in enumerate(pool):
        row = compact_mover(m, k5)
        row.setdefault("gaia", dict(GAIA_UNCHECKED))
        row.setdefault("score", None)
        row.setdefault("reasons", [])
        row.setdefault("class", "not checked")
        row["rank"] = i + 1
        candidates.append(row)
    generated = utc_iso()
    extra = []
    if not use_gaia:
        extra.append("The Gaia check was switched off for this build, so no mover can be called 'unexplained' yet.")
    elif stats["unchecked_tiles"]:
        extra.append(f"The Gaia check is still pending for {stats['unchecked_tiles']} of "
                     f"{stats['tiles_with_movers']} tiles with movers (service busy or offline); their movers are "
                     "'not checked'.")
    summary = build_summary(totals, rows, runs, load_validation(out), extra, generated, status=status,
                            tiles_planned=tiles_planned, min_pm=min_pm)
    leaderboard = {"generated": generated, "n_candidates": n_ranked, "candidates": candidates}
    atomic_write_json(out / "leaderboard.json", leaderboard)
    atomic_write_json(out / "summary.json", summary)
    log.info("published (%s) %d of %d planned tiles, %s movers, %d unexplained, top %d of %d ranked "
             "(Gaia queries %d, unchecked tiles %d)", summary["status"], len(rows), summary["tiles_planned"],
             f"{totals['movers']:,}", totals["unexplained"], len(candidates), n_ranked, stats["queries"],
             stats["unchecked_tiles"])
    return summary


def mark_not_running(out: Path) -> None:
    """After an abort (SIGTERM, second Ctrl-C, unexpected error) there is no final publish: flip the last
    summary's status from "running" to "done" so the page shows a partial survey, not a run that is gone as live
    (the manifest's run log keeps why it stopped). Only a kill -9 can leave "running" behind; --rank-only fixes it."""
    p = Path(out) / "summary.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if isinstance(data, dict) and data.get("status") == "running":
        data["status"] = "done"
        try:
            atomic_write_json(p, data)
        except OSError as e:
            log.warning("could not update the status in summary.json: %s", e)


# ---------------------------------------------------------------------------------------------- the runner
@dataclass
class Config:
    tiles: str | None = None
    workers: int = 3
    out: Path = DEFAULT_OUT
    seed: int = 1
    max_hours: float | None = None
    cache: Path = DEFAULT_CACHE
    no_gaia: bool = False
    rank_only: bool = False
    order: str = "given"
    publish_every: float = 10.0          # minutes; 0 = only at the end
    gaia_budget: float = 5.0             # minutes of Gaia network time per periodic publish
    tile_timeout: float = 1800.0         # seconds
    retries: int = 3                     # extra attempts per tile for network errors
    backoff: float = 30.0                # seconds, doubled per attempt
    maxtasksperchild: int = 3
    max_tiles: int | None = None
    min_free_disk_gb: float = 1.0
    max_worker_gb: float = 3.0
    min_free_mem_gb: float = 0.5
    max_consecutive_failures: int = 25
    top: int = TOP_CANDIDATES
    log_file: Path | None = DEFAULT_LOG
    process_fn: Any = DEFAULT_PROCESS
    xmatch_fn: Any = DEFAULT_XMATCH
    rank_fn: Any = DEFAULT_RANK
    read_retries: int = 5
    read_backoff: float = 2.0
    heartbeat: float = 60.0              # seconds between status lines
    rss_check: float = 5.0               # seconds between worker memory checks
    disk_check: float = 30.0
    manifest_every: float = 10.0         # seconds; the manifest is also written at the end and on signals
    verbose: bool = False
    argv: list[str] = field(default_factory=list)


class Runner:
    def __init__(self, cfg: Config, *, disk_free: Callable | None = None, mem_available: Callable | None = None,
                 rss: Callable | None = None, clock: Callable[[], float] = time.monotonic):
        self.cfg = cfg
        self.out = Path(cfg.out)
        self.tiles_dir = self.out / "tiles"
        self.disk_free = disk_free or disk_free_bytes
        self.mem_available = mem_available or available_memory_bytes
        self.rss = rss or rss_bytes
        self.clock = clock
        self.manifest: dict = {}
        self.run_entry: dict | None = None
        self.pool: WorkerPool | None = None
        self.pending: deque = deque()
        self.retry_heap: list = []
        self._seq = 0
        self.stop_scheduling = False
        self.stop_reason: str | None = None
        self.abort = False
        self.signum: int | None = None
        self.processed: list[int] = []
        self.failed_now: dict[int, str] = {}
        self.retried: list[int] = []
        self.fail_streak = 0
        self.n_publishes = 0
        self.statuses: list[str] = []           # status of each successful publish, in order (for tests/logs)
        self.planned: int | None = None
        self.min_pm: float | None = None
        self.publish_errors = 0
        self.pub_thread: threading.Thread | None = None
        self._pub_cancel = threading.Event()
        self.exit_code: int | None = None
        self.t_start = 0.0
        self._last = {"manifest": 0.0, "heartbeat": 0.0, "rss": 0.0, "disk": 0.0, "publish": 0.0, "memwait": -1e9}
        self._mem_cache = (-1e9, None)
        self._dirty = False

    # ---- public
    def run(self) -> int:
        self.exit_code = self._run()
        return self.exit_code

    def _run(self) -> int:
        cfg = self.cfg
        self.tiles_dir.mkdir(parents=True, exist_ok=True)
        if cfg.rank_only:
            log.info("rank-only: rebuilding leaderboard and summary from %s", self.tiles_dir)
            self._publish(final=True, runs=None)
            return EXIT_OK
        free = self.disk_free(self.out)
        if free < cfg.min_free_disk_gb * GB:
            log.error("refusing to start: only %.2f GB free on the output disk (need %.1f GB)", free / GB,
                      cfg.min_free_disk_gb)
            return EXIT_DISK
        try:
            load_callable(cfg.process_fn)                   # fail fast, not once per tile
        except Exception as e:  # noqa: BLE001
            log.error("cannot load the core stage %r: %s: %s", cfg.process_fn, type(e).__name__, e)
            return EXIT_SETUP
        lock = acquire_lock(self.out)
        if lock is None:
            log.error("another run is using %s (see %s); not starting", self.out, self.out / ".run.lock")
            return EXIT_LOCKED
        old_handlers = self._install_signals()
        try:
            return self._run_locked()
        finally:
            self._restore_signals(old_handlers)
            try:
                lock.unlink()
            except OSError:
                pass

    def _run_locked(self) -> int:
        cfg = self.cfg
        n_tmp = cleanup_temp_files(self.tiles_dir) + cleanup_temp_files(self.out)
        self.manifest = load_manifest(self.out)
        rec = reconcile(self.manifest, self.tiles_dir)
        if n_tmp or any(rec.values()):
            log.info("resume check: %d tile files added to the manifest, %d stale entries dropped, %d unreadable "
                     "tile files set aside, %d temp files removed", rec["added"], rec["dropped"], rec["bad"], n_tmp)
        selection = parse_tiles_spec(cfg.tiles, cfg.seed)
        ordered = order_tiles(selection, cfg.order, cfg.seed,
                              validation_tiles() if cfg.order == "validation-first" else None)
        done = {int(k) for k in self.manifest["done"]}
        todo = [k for k in ordered if k not in done]
        if cfg.max_tiles:
            todo = todo[:cfg.max_tiles]
        self.planned = len(done | set(todo))           # done when this run completes (progress target)
        self.min_pm = core_min_pm(cfg.process_fn)
        retrying = sum(1 for k in todo if str(k) in self.manifest["failed"])
        log.info("selected %d tiles (%s, order %s, seed %d): %d already done, %d to process (%d failed before, "
                 "retrying); %d workers, timeout %.0f s, out %s", len(ordered), cfg.tiles, cfg.order, cfg.seed,
                 len(ordered) - len([k for k in ordered if k not in done]), len(todo), retrying, cfg.workers,
                 cfg.tile_timeout, self.out)
        self._warn_machine()
        self.t_start = self.clock()
        for key in self._last:
            if key != "memwait":
                self._last[key] = self.t_start
        self._last["publish"] = self.t_start - cfg.publish_every * 60   # first publish right away: "running"
        runs = self.manifest["runs"]
        self.run_entry = {"run": len(runs) + 1, "started": utc_iso(), "updated": utc_iso(), "ended": None,
                          "stopped": None, "wall_seconds": 0.0, "tiles": 0, "failed": 0, "detections": 0,
                          "workers": cfg.workers, "selection": cfg.tiles, "order": cfg.order, "seed": cfg.seed,
                          "planned": self.planned, "min_pm": self.min_pm, "pid": os.getpid()}
        runs.append(self.run_entry)
        self._write_manifest()
        self.pending = deque((k, 1) for k in todo)
        aborted = False
        try:
            if todo:
                self._loop()
            aborted = self.abort
        except BaseException:
            aborted = True
            self.stop_reason = self.stop_reason or "error"
            raise
        finally:
            if self.pool is not None:
                self.pool.shutdown(graceful=not aborted)
                self.pool = None
            self.run_entry["ended"] = utc_iso()
            self.run_entry["stopped"] = self.stop_reason or "complete"
            self._write_manifest()
            self._pub_cancel.set()                         # periodic publish: stop querying Gaia, finish up
            if self.pub_thread is not None:
                self.pub_thread.join(timeout=120 if not aborted else 5)
            if aborted:
                mark_not_running(self.out)                 # no final publish: don't leave "running" behind
        elapsed = self.clock() - self.t_start
        log.info("run %d %s after %.2f h: %d tiles done, %d failed this run, %d still to do",
                 self.run_entry["run"], self.run_entry["stopped"], elapsed / 3600, len(self.processed),
                 len(self.failed_now), len(self.pending) + len(self.retry_heap))
        if not aborted:
            self._publish(final=True, runs=self._runs_snapshot(), cancel=threading.Event())
        if self.signum == signal.SIGTERM:
            return EXIT_SIGTERM
        if self.signum == signal.SIGINT:
            return EXIT_SIGINT
        if self.stop_reason == "disk":
            return EXIT_DISK
        return EXIT_FAILED if self.failed_now else EXIT_OK

    # ---- main loop
    def _loop(self) -> None:
        cfg = self.cfg
        n_workers = max(1, min(cfg.workers, len(self.pending)))
        threads = max(1, (os.cpu_count() or 1) // n_workers)
        for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
                    "NUMEXPR_NUM_THREADS"):
            os.environ.setdefault(var, str(threads))         # inherited by the spawned workers
        wcfg = WorkerConfig(tiles_dir=str(self.tiles_dir), process_fn=cfg.process_fn, read_retries=cfg.read_retries,
                            read_backoff=cfg.read_backoff, log_file=str(cfg.log_file) if cfg.log_file else None,
                            parent_pid=os.getpid(), threads=threads)
        self.pool = WorkerPool(n_workers, wcfg, cfg.maxtasksperchild, clock=self.clock)
        while True:
            now = self.clock()
            self._check_limits(now)
            if self.abort:
                break
            if not self.stop_scheduling:
                self._schedule(now)
            if not self.pool.busy() and (self.stop_scheduling or (not self.pending and not self.retry_heap)):
                break
            for ev in self.pool.poll(0.25):
                self._handle(ev)
            now = self.clock()
            self._check_workers(now)
            self._periodic(now)

    def _schedule(self, now: float) -> None:
        for slot in self.pool.idle():
            if self.stop_scheduling:
                return
            if self.pool.busy() and not self._memory_ok(now):
                return
            task = self._next_task(now)
            if task is None:
                return
            self.pool.assign(slot, *task)

    def _next_task(self, now: float) -> tuple[int, int] | None:
        if self.retry_heap and self.retry_heap[0][0] <= now:
            _, _, k5, attempt = heapq.heappop(self.retry_heap)
            return k5, attempt
        if self.pending:
            return self.pending.popleft()
        return None

    def _memory_ok(self, now: float) -> bool:
        if self.cfg.min_free_mem_gb <= 0:
            return True
        t, avail = self._mem_cache
        if now - t > 2.0:
            avail = self.mem_available()
            self._mem_cache = (now, avail)
        if avail is None or avail >= self.cfg.min_free_mem_gb * GB:
            return True
        if now - self._last["memwait"] > 60:
            self._last["memwait"] = now
            log.warning("only %.2f GB memory available; waiting for running tiles before starting more", avail / GB)
        return False

    def _stop(self, reason: str, message: str, *args) -> None:
        if not self.stop_scheduling:
            self.stop_scheduling = True
            self.stop_reason = reason
            n = len(self.pool.busy()) if self.pool else 0
            log.warning(message + "; no new tiles, finishing %d running", *args, n)

    def _check_limits(self, now: float) -> None:
        cfg = self.cfg
        if self.signum is not None and not self.stop_scheduling:
            self._stop("interrupted", "interrupted (press Ctrl-C again to stop now)")
        if cfg.max_hours is not None and now - self.t_start >= cfg.max_hours * 3600:
            self._stop("max-hours", "reached --max-hours %.2f", cfg.max_hours)
        if now - self._last["disk"] >= cfg.disk_check:
            self._last["disk"] = now
            self._check_disk()

    def _check_disk(self) -> None:
        try:
            free = self.disk_free(self.out)
        except OSError:
            return
        if free < self.cfg.min_free_disk_gb * GB:
            self._stop("disk", "free disk down to %.2f GB (limit %.1f GB)", free / GB, self.cfg.min_free_disk_gb)

    def _check_workers(self, now: float) -> None:
        cfg = self.cfg
        for s in list(self.pool.busy()):
            if now - s.started > cfg.tile_timeout:
                k5, attempt = s.task
                self.pool.kill(s, respawn=not self.stop_scheduling)
                self._failed(k5, attempt, "timeout", f"timed out after {cfg.tile_timeout:.0f} s; worker killed")
        if now - self._last["rss"] >= cfg.rss_check:
            self._last["rss"] = now
            busy = self.pool.busy()
            sizes = self.rss([s.pid for s in busy]) if busy else {}
            for s in busy:
                b = sizes.get(s.pid)
                if not b:
                    continue
                s.rss, s.peak_rss = b, max(s.peak_rss, b)
                if cfg.max_worker_gb > 0 and b > cfg.max_worker_gb * GB:
                    k5, attempt = s.task
                    self.pool.kill(s, respawn=not self.stop_scheduling)
                    self._failed(k5, attempt, "memory", f"worker used {b / GB:.2f} GB, over the "
                                 f"{cfg.max_worker_gb:.1f} GB limit; killed")

    def _periodic(self, now: float) -> None:
        cfg = self.cfg
        if now - self._last["heartbeat"] >= cfg.heartbeat:
            self._last["heartbeat"] = now
            self._heartbeat(now)
        if self._dirty and now - self._last["manifest"] >= cfg.manifest_every:
            self._write_manifest()
        if cfg.publish_every > 0 and now - self._last["publish"] >= cfg.publish_every * 60 \
                and not (self.pub_thread and self.pub_thread.is_alive()):
            self._last["publish"] = now
            self._write_manifest()
            runs = self._runs_snapshot()
            self.pub_thread = threading.Thread(target=self._publish, name="survey-publish", daemon=True,
                                               kwargs={"final": False, "runs": runs, "cancel": self._pub_cancel})
            self.pub_thread.start()

    # ---- events
    def _handle(self, ev: tuple) -> None:
        kind, slot = ev[0], ev[1]
        if kind == "done":
            _, _, k5, attempt, info, secs = ev
            self._done(k5, attempt, info)
            if slot in self.pool.slots and slot.n_tasks >= self.pool.maxtasks:
                self.pool.retire(slot, respawn=not self.stop_scheduling)
        elif kind == "error":
            _, _, k5, attempt, ekind, text, tb, secs = ev
            if slot in self.pool.slots:                     # a fresh process after any error
                self.pool.retire(slot, respawn=not self.stop_scheduling)
            if ekind == "network" and attempt <= self.cfg.retries and not self.stop_scheduling:
                delay = backoff_delay(attempt, self.cfg.backoff, 30 * 60)
                self._seq += 1
                heapq.heappush(self.retry_heap, (self.clock() + delay, self._seq, k5, attempt + 1))
                self.retried.append(k5)
                log.warning("tile %d: network error (%s); retry %d/%d in %.0f s", k5, text[:200], attempt,
                            self.cfg.retries, delay)
                return
            if tb and self.cfg.verbose:
                log.debug("tile %d traceback:\n%s", k5, tb)
            self._failed(k5, attempt, ekind, text)
            if ekind == "disk":
                self._check_disk()
                self._stop("disk", "tile %d could not be written: disk full", k5)
        elif kind == "died":
            _, _, k5, attempt, code, secs = ev
            if k5 is None:
                log.warning("idle worker %s exited (code %s); replaced", slot.pid, code)
                return
            hint = " (killed by signal 9: probably out of memory)" if code == -9 else ""
            self._failed(k5, attempt, "crash", f"worker process died with exit code {code}{hint}")

    def _done(self, k5: int, attempt: int, info: dict) -> None:
        key = str(k5)
        prev = self.manifest["failed"].pop(key, None)
        self.manifest["done"][key] = {"seconds": info.get("seconds"), "n_detections": _int(info.get("n_detections")),
                                      "n_movers": _int(info.get("n_movers")), "bytes": info.get("bytes"),
                                      "finished": utc_iso(), "run": self.run_entry["run"],
                                      "attempts": attempt + (prev or {}).get("attempts", 0),
                                      "peak_rss_mb": info.get("peak_rss_mb")}
        self.failed_now.pop(k5, None)
        self.processed.append(k5)
        self.fail_streak = 0
        self.run_entry["tiles"] += 1
        self.run_entry["detections"] += _int(info.get("n_detections"))
        self._dirty = True
        elapsed = max(self.clock() - self.t_start, 1e-9)
        n = self.run_entry["tiles"]
        left = len(self.pending) + len(self.retry_heap) + len(self.pool.busy())
        rate = n / elapsed * 3600
        eta = f"{left / rate:.1f} h" if rate > 0 else "?"
        log.info("tile %d done in %.1f s: %s detections, %d movers%s | run: %d done, %d failed, %d left | "
                 "%.1f tiles/h, %s det/s, ETA %s | worker %s peak %.2f GB", k5, info.get("seconds") or 0,
                 human(info.get("n_detections") or 0), info.get("n_movers") or 0,
                 f", {info['read_retries']} read retries" if info.get("read_retries") else "",
                 n, len(self.failed_now), left, rate, human(self.run_entry["detections"] / elapsed), eta,
                 info.get("pid"), (info.get("peak_rss_mb") or 0) / 1024)

    def _failed(self, k5: int, attempt: int, kind: str, text: str) -> None:
        key = str(k5)
        prev = self.manifest["failed"].get(key) or {}
        self.manifest["failed"][key] = {"error": text[:2000], "kind": kind,
                                        "attempts": prev.get("attempts", 0) + attempt, "last": utc_iso(),
                                        "run": self.run_entry["run"]}
        self.failed_now[k5] = text
        self.run_entry["failed"] = len(self.failed_now)
        self.fail_streak += 1
        self._dirty = True
        log.error("tile %d failed (%s): %s", k5, kind, text[:500])
        if self.cfg.max_consecutive_failures and self.fail_streak >= self.cfg.max_consecutive_failures:
            self._stop("too-many-failures", "%d tiles failed in a row; something is wrong", self.fail_streak)

    # ---- outputs
    def _runs_snapshot(self) -> list[dict]:
        if self.run_entry is not None:
            self.run_entry["wall_seconds"] = round(self.clock() - self.t_start, 1)
            self.run_entry["updated"] = utc_iso()
        return copy.deepcopy(self.manifest.get("runs", []))

    def _write_manifest(self) -> None:
        if not self.manifest:
            return
        self._runs_snapshot()
        self.manifest["updated"] = utc_iso()
        try:
            atomic_write_json(self.out / "manifest.json", self.manifest)
            self._dirty = False
        except OSError as e:
            log.error("could not write the manifest: %s", e)
        self._last["manifest"] = self.clock()

    def _publish(self, final: bool, runs: list[dict] | None, cancel: threading.Event | None = None) -> None:
        """final=False: mid-run, status "running", Gaia time capped. final=True after a run: status "done".
        In --rank-only mode (runs=None) status and plan come from the lock and the manifest."""
        cfg = self.cfg
        budget = None if final else cfg.gaia_budget * 60
        cancel = cancel or threading.Event()
        in_run = runs is not None
        try:
            publish(self.out, cache_dir=cfg.cache, use_gaia=not cfg.no_gaia, xmatch_fn=cfg.xmatch_fn,
                    rank_fn=cfg.rank_fn, top=cfg.top, gaia_budget_s=budget, runs=runs,
                    should_abort=lambda: self.abort or cancel.is_set(), clock=self.clock,
                    status=("done" if final else "running") if in_run else None,
                    tiles_planned=self.planned if in_run else None, min_pm=self.min_pm if in_run else None)
            self.n_publishes += 1
            self.statuses.append(("done" if final else "running") if in_run else "rank-only")
        except PublishAborted:
            log.info("publish skipped (stopping)")
        except Exception as e:  # noqa: BLE001 - publishing must never kill the run
            self.publish_errors += 1
            log.exception("publish failed: %s", e)

    def _heartbeat(self, now: float) -> None:
        busy = self.pool.busy() if self.pool else []
        parts = [f"{s.task[0]} {now - s.started:.0f}s {s.rss / GB:.2f}GB" for s in busy]
        try:
            free = self.disk_free(self.out) / GB
        except OSError:
            free = float("nan")
        mem = self._mem_cache[1]
        log.info("status: %d running [%s] | %d queued, %d retrying | %d done this run | disk %.1f GB free%s",
                 len(busy), ", ".join(parts), len(self.pending), len(self.retry_heap), len(self.processed), free,
                 f" | memory {mem / GB:.1f} GB available" if mem else "")

    def _warn_machine(self) -> None:
        cfg = self.cfg
        total = total_memory_bytes()
        if total and cfg.max_worker_gb > 0 and cfg.workers * cfg.max_worker_gb * GB > total:
            log.warning("%d workers x %.1f GB limit is more than the %.1f GB of RAM; tiles may be killed for "
                        "memory or the machine may swap", cfg.workers, cfg.max_worker_gb, total / GB)
        if cfg.workers > (os.cpu_count() or 1):
            log.warning("%d workers on %d CPUs", cfg.workers, os.cpu_count() or 1)

    # ---- signals
    def _install_signals(self) -> dict:
        if threading.current_thread() is not threading.main_thread():
            return {}
        old = {}
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                old[sig] = signal.signal(sig, self._on_signal)
            except (ValueError, OSError):
                pass
        return old

    def _restore_signals(self, old: dict) -> None:
        for sig, h in old.items():
            try:
                signal.signal(sig, h)
            except (ValueError, OSError, TypeError):
                pass

    def _on_signal(self, signum, frame) -> None:
        first = self.signum is None
        self.signum = signum if first or signum == signal.SIGTERM else self.signum
        if signum == signal.SIGTERM or not first:
            self.abort = True
            self.stop_scheduling = True
            self.stop_reason = "signal"


# ---------------------------------------------------------------------------------------------- CLI
def _tiles_arg(s: str) -> str:
    s = s.strip()
    if s == "validation":
        return s
    try:
        parse_tiles_spec(s)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from None
    return s


def _positive_int(s: str) -> int:
    try:
        v = int(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{s!r} is not an integer") from None
    if v < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {v}")
    return v


def _nonneg_int(s: str) -> int:
    try:
        v = int(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{s!r} is not an integer") from None
    if v < 0:
        raise argparse.ArgumentTypeError(f"must be 0 or more, got {v}")
    return v


def _positive_float(s: str) -> float:
    try:
        v = float(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{s!r} is not a number") from None
    if not (v > 0 and math.isfinite(v)):
        raise argparse.ArgumentTypeError(f"must be more than 0, got {s}")
    return v


def _nonneg_float(s: str) -> float:
    try:
        v = float(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{s!r} is not a number") from None
    if not (v >= 0 and math.isfinite(v)):
        raise argparse.ArgumentTypeError(f"must be 0 or more, got {s}")
    return v


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run.py", description="WANDERERS Sky Survey: process NEOWISE tiles, then rank the movers "
        "(sharded and resumable; rerun the same command to continue).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--tiles", type=_tiles_arg, help="validation | random:N | list:1,2,3 (ranges a-b allowed) | all")
    p.add_argument("--workers", type=_positive_int, default=3, help="worker processes")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output directory (tiles/, manifest, leaderboard)")
    p.add_argument("--seed", type=int, default=1, help="seed for random:N and the random orders")
    p.add_argument("--max-hours", type=_positive_float, default=None,
                   help="stop scheduling new tiles after this many hours, then finish cleanly")
    p.add_argument("--cache", type=Path, default=DEFAULT_CACHE, help="Gaia answer cache directory")
    p.add_argument("--no-gaia", action="store_true", help="skip the Gaia check (movers are 'not checked')")
    p.add_argument("--rank-only", action="store_true",
                   help="only rebuild leaderboard.json and summary.json from the existing tile files")
    p.add_argument("--order", choices=ORDERS, default="given",
                   help="given; random (seeded); validation-first (validation tiles, then the rest seeded-random)")
    p.add_argument("--max-tiles", type=_positive_int, default=None, help="process at most this many tiles this run")
    p.add_argument("--publish-every", type=_nonneg_float, default=10.0,
                   help="minutes between leaderboard/summary rebuilds during the run (0 = only at the end)")
    p.add_argument("--gaia-budget", type=_nonneg_float, default=5.0,
                   help="minutes of Gaia queries per periodic rebuild (the final rebuild has no limit)")
    p.add_argument("--tile-timeout", type=_positive_float, default=1800.0, help="seconds before a tile is killed")
    p.add_argument("--retries", type=_nonneg_int, default=3, help="extra attempts per tile after network errors")
    p.add_argument("--backoff", type=_nonneg_float, default=30.0, help="first retry delay in seconds (doubles)")
    p.add_argument("--read-retries", type=_positive_int, default=5, help="attempts per S3 read (per tile-year)")
    p.add_argument("--maxtasksperchild", type=_positive_int, default=3,
                   help="tiles per worker process before it is replaced (frees memory)")
    p.add_argument("--max-worker-gb", type=_nonneg_float, default=3.0,
                   help="kill a worker whose memory passes this (0 = no limit)")
    p.add_argument("--min-free-mem-gb", type=_nonneg_float, default=0.5,
                   help="do not start another tile while less memory than this is available")
    p.add_argument("--min-free-disk-gb", type=_nonneg_float, default=1.0,
                   help="refuse to start, and stop scheduling, below this much free disk")
    p.add_argument("--max-consecutive-failures", type=_nonneg_int, default=25,
                   help="stop scheduling after this many tiles fail in a row (0 = never)")
    p.add_argument("--top", type=_positive_int, default=TOP_CANDIDATES, help="leaderboard length")
    p.add_argument("--log-file", default=str(DEFAULT_LOG), help="log file ('' = none)")
    p.add_argument("--heartbeat", type=_positive_float, default=60.0, help="seconds between status lines")
    p.add_argument("--process-fn", default=DEFAULT_PROCESS, help="core stage as module:function (advanced/testing)")
    p.add_argument("--xmatch-fn", default=DEFAULT_XMATCH, help="Gaia check as module:function (advanced/testing)")
    p.add_argument("--rank-fn", default=DEFAULT_RANK, help="ranking as module:function (advanced/testing)")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging (tracebacks of failed tiles)")
    return p


def config_from_args(ns: argparse.Namespace, argv: list[str] | None = None) -> Config:
    return Config(tiles=ns.tiles, workers=ns.workers, out=Path(ns.out), seed=ns.seed, max_hours=ns.max_hours,
                  cache=Path(ns.cache), no_gaia=ns.no_gaia, rank_only=ns.rank_only, order=ns.order,
                  publish_every=ns.publish_every, gaia_budget=ns.gaia_budget, tile_timeout=ns.tile_timeout,
                  retries=ns.retries, backoff=ns.backoff, maxtasksperchild=ns.maxtasksperchild,
                  max_tiles=ns.max_tiles, min_free_disk_gb=ns.min_free_disk_gb, max_worker_gb=ns.max_worker_gb,
                  min_free_mem_gb=ns.min_free_mem_gb, max_consecutive_failures=ns.max_consecutive_failures,
                  top=ns.top, log_file=Path(ns.log_file) if ns.log_file else None, process_fn=ns.process_fn,
                  xmatch_fn=ns.xmatch_fn, rank_fn=ns.rank_fn, read_retries=ns.read_retries,
                  heartbeat=ns.heartbeat, verbose=ns.verbose, argv=list(argv or []))


def parse_args(argv: list[str] | None = None) -> Config:
    parser = build_parser()
    ns = parser.parse_args(argv)
    if not ns.rank_only and not ns.tiles:
        parser.error("--tiles is required (unless --rank-only)")
    return config_from_args(ns, argv)


_handlers: list[logging.Handler] = []


def setup_logging(log_file: Path | None, verbose: bool = False) -> None:
    for h in _handlers:
        log.removeHandler(h)
        h.close()
    _handlers.clear()
    log.setLevel(logging.DEBUG if verbose else logging.INFO)
    log.propagate = False
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(fmt)
    _handlers.append(h)
    if log_file:
        try:
            Path(log_file).parent.mkdir(parents=True, exist_ok=True)
            fh = logging.FileHandler(log_file, encoding="utf-8")
            fh.setFormatter(fmt)
            _handlers.append(fh)
        except OSError as e:
            print(f"warning: cannot write log file {log_file}: {e}", file=sys.stderr)
    for h in _handlers:
        log.addHandler(h)


def main(argv: list[str] | None = None, **deps) -> int:
    """CLI entry point. `deps` (disk_free, mem_available, rss, clock) are for tests."""
    argv = sys.argv[1:] if argv is None else list(argv)
    cfg = parse_args(argv)
    setup_logging(cfg.log_file, cfg.verbose)
    log.info("survey run: %s", " ".join(argv))
    runner = Runner(cfg, **deps)
    try:
        return runner.run()
    except Exception as e:  # noqa: BLE001 - the manifest is already written; say what happened and exit 1
        log.exception("run stopped by an unexpected error: %s: %s", type(e).__name__, e)
        return EXIT_FAILED


if __name__ == "__main__":
    # Run through the package module so worker processes unpickle `survey.run._worker_main`, not `__main__`.
    sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != _HERE]   # no survey/*.py as top-level
    from survey import run as _run
    sys.exit(_run.main())
