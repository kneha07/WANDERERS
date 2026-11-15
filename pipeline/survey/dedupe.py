"""Merge movers that were found twice, in two neighbouring HEALPix tiles (WANDERERS Sky Survey).

The NEOWISE source table puts every detection in the order-5 tile that contains it, and the core
(`survey.link.process_tile`) searches each tile on its own. A source whose detections fall on both sides of a
tile boundary (a mover crossing it, or a slow one sitting on it) can therefore be linked in both tiles, each copy
holding part of its visits. Such movers are usually flagged `tile_edge`. Publishing must count them once.

Two movers from different tiles are the same source when all of these hold:

1. **Their tiles touch** (HEALPix neighbours, corners included). A tile only holds detections inside it, so two
   copies of one source can only come from touching tiles.
2. **Same place:** each is moved with its *own* proper motion to the midpoint of the two epochs, and the two
   positions agree within ``POS_TOL_ARCSEC`` (3") plus ``POS_SIGMA`` (3) times the combined position error there
   (``POS_SIG0_ARCSEC`` at the mover's own epoch, growing with ``pm_err`` x years moved), at most
   ``MAX_POS_TOL_ARCSEC`` (8"). Two WISE sources closer than ~6" are one blob anyway.
3. **Same motion:** the motions, compared as 3D velocity vectors (so the poles need no special case), differ by
   less than the largest of ``PM_FLOOR`` (20 mas/yr: two short halves of one track carry some unmodelled
   parallax), ``PM_SIGMA`` (3) times the combined ``pm_err`` (capped at ``PM_MAX_TOL``, 1000 mas/yr) and
   ``PM_FRAC`` (3 %) of the motion.

The better track is kept: more visits, then higher ``pm_snr``, then the smaller id (so the result does not depend
on file order). The ids of the others go into the kept mover's ``duplicates`` list. Groups are joined
transitively (a mover at a corner can be found in three tiles). Positions are unit vectors throughout, so RA
0/360 needs no special case either.

    python pipeline/survey/dedupe.py app/data/survey/tiles     # how many duplicates the tile files hold
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import warnings
from functools import lru_cache
from pathlib import Path

import numpy as np

POS_TOL_ARCSEC = 3.0
POS_SIGMA = 3.0
POS_SIG0_ARCSEC = 0.15        # position error of a track's fitted mean position (>= 6 visit means of ~0.3")
MAX_POS_TOL_ARCSEC = 8.0
PM_FLOOR = 20.0               # mas/yr
PM_SIGMA = 3.0
PM_MAX_TOL = 1000.0           # mas/yr: cap on the error term, so a sloppy fit cannot match anything
PM_FRAC = 0.03
DEFAULT_PM_ERR = 10.0         # mas/yr, when a mover has no pm_err
NSIDE = 32
MAS_PER_RAD = 180.0 / math.pi * 3.6e6
ARCSEC_PER_RAD = 180.0 / math.pi * 3600.0


# ---------------------------------------------------------------------------------------------- geometry
def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def unit(ra, dec) -> np.ndarray:
    """Unit vectors (..., 3) of RA/Dec in degrees."""
    a, d = np.radians(np.asarray(ra, float)), np.radians(np.asarray(dec, float))
    return np.stack([np.cos(d) * np.cos(a), np.cos(d) * np.sin(a), np.sin(d)], axis=-1)


def velocity(ra, dec, pmra, pmdec) -> np.ndarray:
    """Tangent velocity vectors (..., 3) in mas/yr: pmra (includes cos dec) along east, pmdec along north.
    Works at the poles too: the east/north pair follows the given RA."""
    a, d = np.radians(np.asarray(ra, float)), np.radians(np.asarray(dec, float))
    east = np.stack([-np.sin(a), np.cos(a), np.zeros_like(a)], axis=-1)
    north = np.stack([-np.sin(d) * np.cos(a), -np.sin(d) * np.sin(a), np.cos(d)], axis=-1)
    return east * np.asarray(pmra, float)[..., None] + north * np.asarray(pmdec, float)[..., None]


def radec(v) -> tuple[np.ndarray, np.ndarray]:
    v = np.asarray(v, float)
    v = v / np.linalg.norm(v, axis=-1, keepdims=True)
    ra = np.degrees(np.arctan2(v[..., 1], v[..., 0])) % 360.0
    dec = np.degrees(np.arcsin(np.clip(v[..., 2], -1.0, 1.0)))
    return ra, dec


def moved(p, v, dt_yr) -> np.ndarray:
    """Unit vectors p moved by velocity v (mas/yr) for dt_yr years (straight line on the tangent plane)."""
    q = np.asarray(p, float) + np.asarray(v, float) * (np.asarray(dt_yr, float)[..., None] / MAS_PER_RAD)
    return q / np.linalg.norm(q, axis=-1, keepdims=True)


def propagate(ra, dec, pmra, pmdec, dt_yr):
    """(ra, dec) in degrees after moving dt_yr years with the given motion (mas/yr)."""
    r, d = radec(moved(unit(ra, dec), velocity(ra, dec, pmra, pmdec), dt_yr))
    return (float(r), float(d)) if np.ndim(r) == 0 else (r, d)


def sep_arcsec(p, q) -> np.ndarray:
    """Angle between unit vectors in arcsec (stable for tiny angles)."""
    p, q = np.asarray(p, float), np.asarray(q, float)
    return 2.0 * np.arcsin(np.clip(np.linalg.norm(p - q, axis=-1) / 2.0, 0.0, 1.0)) * ARCSEC_PER_RAD


# ---------------------------------------------------------------------------------------------- tiles
@lru_cache(maxsize=None)
def _hp():
    from astropy_healpix import HEALPix
    return HEALPix(nside=NSIDE, order="nested")


@lru_cache(maxsize=65536)
def neighbours(k5: int) -> frozenset:
    """Tiles touching tile k5 (edges and corners). Empty when astropy_healpix is missing (then the adjacency rule
    is skipped, see find_duplicates)."""
    try:
        with warnings.catch_warnings():        # tiles with only 7 neighbours answer -1 (and astropy warns)
            warnings.simplefilter("ignore", RuntimeWarning)
            nb = np.asarray(_hp().neighbours(int(k5))).ravel()
    except Exception:  # noqa: BLE001 - no astropy_healpix, or a bad tile number
        return frozenset()
    return frozenset(int(x) for x in nb if x >= 0 and x != int(k5))


def touching(a: int, b: int) -> bool:
    return int(b) in neighbours(int(a))


# ---------------------------------------------------------------------------------------------- records
def record(m: dict, k5=None) -> dict | None:
    """The few numbers deduplication needs from a mover (None when its position or motion is missing). A record
    passed in again is returned as it is."""
    if not isinstance(m, dict):
        return None
    if m.get("_record") is True:
        return m
    r = {"_record": True, "id": str(m.get("id")), "k5": m.get("k5", k5)}
    try:
        r["k5"] = int(r["k5"]) if r["k5"] is not None else None
    except (TypeError, ValueError):
        r["k5"] = None
    for k in ("ra", "dec", "epoch", "pmra", "pmdec", "pm", "pm_err", "pm_snr", "n_visits"):
        r[k] = _num(m.get(k))
    if None in (r["ra"], r["dec"], r["epoch"], r["pmra"], r["pmdec"]) or r["id"] in ("", "None"):
        return None
    if r["pm"] is None:
        r["pm"] = math.hypot(r["pmra"], r["pmdec"])
    if r["pm_err"] is None or r["pm_err"] < 0:
        r["pm_err"] = DEFAULT_PM_ERR
    return r


def better_key(r: dict):
    """Sort key, best first: more visits, then higher pm_snr, then the smaller id."""
    nv = r.get("n_visits")
    snr = r.get("pm_snr")
    return (-(nv if nv is not None else -1), -(snr if snr is not None else -math.inf), str(r.get("id")))


def tolerances(a: dict, b: dict) -> tuple[float, float, float]:
    """(midpoint epoch, position tolerance in arcsec, motion tolerance in mas/yr) for a pair of records."""
    t_mid = (a["epoch"] + b["epoch"]) / 2.0
    sig = [math.hypot(POS_SIG0_ARCSEC, r["pm_err"] * abs(t_mid - r["epoch"]) / 1000.0) for r in (a, b)]
    pos_tol = min(MAX_POS_TOL_ARCSEC, POS_TOL_ARCSEC + POS_SIGMA * math.hypot(*sig))
    pm_tol = max(PM_FLOOR, min(PM_MAX_TOL, PM_SIGMA * math.hypot(a["pm_err"], b["pm_err"])),
                 PM_FRAC * (a["pm"] + b["pm"]) / 2.0)
    return t_mid, pos_tol, pm_tol


def compare(a: dict, b: dict) -> dict:
    """Pairwise test on two records (see the module docstring). Returns {same, sep_arcsec, dpm, pos_tol, pm_tol,
    epoch}; `same` ignores tiles (find_duplicates checks those)."""
    t_mid, pos_tol, pm_tol = tolerances(a, b)
    va = velocity(a["ra"], a["dec"], a["pmra"], a["pmdec"])
    vb = velocity(b["ra"], b["dec"], b["pmra"], b["pmdec"])
    pa = moved(unit(a["ra"], a["dec"]), va, t_mid - a["epoch"])
    pb = moved(unit(b["ra"], b["dec"]), vb, t_mid - b["epoch"])
    sep = float(sep_arcsec(pa, pb))
    dpm = float(np.linalg.norm(va - vb))
    return {"same": bool(sep <= pos_tol and dpm <= pm_tol), "sep_arcsec": sep, "dpm": dpm, "pos_tol": pos_tol,
            "pm_tol": pm_tol, "epoch": t_mid}


def same_source(a: dict, b: dict, require_neighbours: bool = True) -> bool:
    """True when movers (or records) a and b, from different tiles, are one source."""
    ra, rb = record(a), record(b)
    if ra is None or rb is None or ra["k5"] is None or rb["k5"] is None or ra["k5"] == rb["k5"]:
        return False
    if require_neighbours and neighbours(ra["k5"]) and not touching(ra["k5"], rb["k5"]):
        return False
    return compare(ra, rb)["same"]


# ---------------------------------------------------------------------------------------------- search
def _candidate_pairs(recs: list[dict]) -> list[tuple[int, int]]:
    """Index pairs (i < j) whose positions, each moved with its own motion to a common reference epoch, lie close
    enough that the pairwise test could accept them. A sweep in z (sin dec) over unit vectors: no RA wrap, no pole
    problem, ~N log N."""
    n = len(recs)
    if n < 2:
        return []
    ep = np.array([r["epoch"] for r in recs])
    ref = float(np.median(ep))
    p = moved(unit([r["ra"] for r in recs], [r["dec"] for r in recs]),
              velocity([r["ra"] for r in recs], [r["dec"] for r in recs], [r["pmra"] for r in recs],
                       [r["pmdec"] for r in recs]), ref - ep)
    # Separation at `ref` <= separation at the pair's midpoint + |dv| x |ref - midpoint|  (both tolerances capped)
    max_pm_tol = max(PM_MAX_TOL, PM_FLOOR, max(PM_FRAC * r["pm"] for r in recs))
    reach = MAX_POS_TOL_ARCSEC + max_pm_tol / 1000.0 * float(np.max(np.abs(ep - ref))) + 1.0
    chord = 2.0 * math.sin(reach / ARCSEC_PER_RAD / 2.0)
    order = np.argsort(p[:, 2], kind="stable")
    z = p[order, 2]
    pairs = []
    for ii in range(n):
        hi = int(np.searchsorted(z, z[ii] + chord, side="right"))
        if hi <= ii + 1:
            continue
        i = int(order[ii])
        js = order[ii + 1:hi]
        d = np.linalg.norm(p[js] - p[i], axis=1)
        for j in js[d <= chord]:
            j = int(j)
            pairs.append((min(i, j), max(i, j)))
    return sorted(set(pairs))


def find_duplicates(movers, require_neighbours: bool = True) -> dict:
    """Find movers (dicts with at least id, k5, ra, dec, epoch, pmra, pmdec; pm_err, pm_snr, n_visits used when
    present) from different tiles that are the same source.

    Returns {"drop": {dropped id: kept id}, "groups": {kept id: [dropped ids, best first]},
    "pairs": [{"a", "b", "sep_arcsec", "dpm", ...}], "n_checked": records used}. With require_neighbours the two
    tiles must touch; if astropy_healpix is missing that rule is skipped."""
    recs = []
    for m in movers:
        r = record(m)
        if r is not None and r["k5"] is not None:
            recs.append(r)
    parent = list(range(len(recs)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    pairs = []
    for i, j in _candidate_pairs(recs):
        a, b = recs[i], recs[j]
        if a["k5"] == b["k5"] or a["id"] == b["id"]:
            continue
        if require_neighbours and neighbours(a["k5"]) and not touching(a["k5"], b["k5"]):
            continue
        c = compare(a, b)
        if not c["same"]:
            continue
        pairs.append({"a": a["id"], "b": b["id"], "k5_a": a["k5"], "k5_b": b["k5"],
                      **{k: round(v, 3) for k, v in c.items() if k != "same"}})
        ri, rj = root(i), root(j)
        if ri != rj:
            parent[rj] = ri
    groups: dict[int, list[int]] = {}
    for i in range(len(recs)):
        groups.setdefault(root(i), []).append(i)
    drop, kept = {}, {}
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda i: better_key(recs[i]))
        best = recs[members[0]]["id"]
        kept[best] = [recs[i]["id"] for i in members[1:]]
        for i in members[1:]:
            drop[recs[i]["id"]] = best
    return {"drop": drop, "groups": kept, "pairs": pairs, "n_checked": len(recs)}


def merge(movers: list[dict], require_neighbours: bool = True) -> tuple[list[dict], dict]:
    """Movers with the duplicates removed (input order kept) and `duplicates` added to each kept mover that had
    any; plus the find_duplicates result."""
    res = find_duplicates(movers, require_neighbours=require_neighbours)
    out = []
    for m in movers:
        mid = str(m.get("id"))
        if mid in res["drop"]:
            continue
        if mid in res["groups"]:
            m = dict(m, duplicates=list(res["groups"][mid]))
        out.append(m)
    return out, res


# ---------------------------------------------------------------------------------------------- tile files
def records_from_tiles(tiles_dir) -> list[dict]:
    """One record per mover in every <k5>.json of a survey tiles folder (unreadable files are skipped)."""
    recs = []
    for path in sorted(Path(tiles_dir).glob("*.json")):
        if not path.stem.isdigit():
            continue
        try:
            tile = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(tile, dict):
            continue
        for m in tile.get("movers") or []:
            r = record(m, tile.get("k5", int(path.stem)))
            if r is not None:
                recs.append(r)
    return recs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Count movers found twice in neighbouring survey tiles.")
    ap.add_argument("tiles", nargs="?", default="app/data/survey/tiles", help="folder of <k5>.json tile files")
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    ns = ap.parse_args(argv)
    recs = records_from_tiles(ns.tiles)
    res = find_duplicates(recs)
    tiles = {r["k5"] for r in recs}
    touching_pairs = sum(1 for k in tiles for n in neighbours(k) if n in tiles and n > k)
    if ns.json:
        print(json.dumps({**res, "tiles": len(tiles), "touching_tile_pairs": touching_pairs}, indent=1))
    else:
        print(f"{len(recs)} movers in {len(tiles)} tiles ({touching_pairs} pairs of touching tiles): "
              f"{len(res['drop'])} duplicates in {len(res['groups'])} groups")
        for p in res["pairs"]:
            print(f"  {p['a']} = {p['b']}  {p['sep_arcsec']:.2f}\" apart, motions differ by {p['dpm']:.1f} mas/yr")
    return 0


if __name__ == "__main__":
    sys.exit(main())
