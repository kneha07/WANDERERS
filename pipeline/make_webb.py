"""Every public JWST (Webb) imaging frame, for "what did Webb see here?" in the console and the Sky Compass.

    python pipeline/make_webb.py

Source: MAST (Mikulski Archive for Space Telescopes, STScI) CAOM table, through its public API: JWST,
science, calibrated level-3 mosaics (i2d), public data only. Frames of one programme, target and instrument
at the same spot (one per filter) are merged into one pointing; its outline is the convex hull of their
footprints (MAST `s_region`), which is what the apps test a star's coordinates against.

Output app/data/webb.json:
  {"updated": ISO date, "count": n frames,
   "programs": {id: title},
   "p": [[ra, dec, radius_deg, instrument, target, program, mjd, "F200W F444W", obs_id, [ra1, dec1, ra2, dec2, ...]], ...]}
"""
import json, ssl, sys, time, urllib.parse, urllib.request
from datetime import date
from pathlib import Path

import certifi
import numpy as np
from scipy.spatial import ConvexHull

ROOT = Path(__file__).resolve().parent.parent
CTX = ssl.create_default_context(cafile=certifi.where())
API = "https://mast.stsci.edu/api/v0/invoke"
COLS = "target_name,s_ra,s_dec,s_region,instrument_name,filters,t_min,obs_title,proposal_id,obs_id"
FILTERS = [{"paramName": "obs_collection", "values": ["JWST"]},
           {"paramName": "dataproduct_type", "values": ["image"]},
           {"paramName": "intentType", "values": ["science"]},
           {"paramName": "calib_level", "values": [3]},
           {"paramName": "dataRights", "values": ["PUBLIC"]}]
INST = {"NIRCAM": "NIRCam", "MIRI": "MIRI", "NIRISS": "NIRISS", "NIRSPEC": "NIRSpec", "FGS": "FGS"}


def mast(page, size=5000):
    req = {"service": "Mast.Caom.Filtered", "format": "json", "pagesize": size, "page": page,
           "params": {"columns": COLS, "filters": FILTERS}}
    body = urllib.parse.urlencode({"request": json.dumps(req)}).encode()
    for attempt in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(API, body), timeout=300, context=CTX) as r:
                return json.load(r)
        except Exception as e:                      # MAST is busy at times: back off and retry
            print(f"   retry {attempt + 1}: {e}", flush=True)
            time.sleep(10 * (attempt + 1))
    raise RuntimeError("MAST did not answer")


def polygons(s_region):
    """MAST s_region -> list of (N, 2) arrays of ra/dec vertices (handles several POLYGONs)."""
    out = []
    for part in (s_region or "").upper().split("POLYGON")[1:]:
        nums = [float(x) for x in part.replace("ICRS", " ").split() if x[0] in "-.0123456789"]
        if len(nums) >= 6:
            out.append(np.array(nums[: len(nums) // 2 * 2]).reshape(-1, 2))
    return out


def hull(points, ra0, dec0):
    """Convex hull on the tangent plane around (ra0, dec0); returns ra/dec vertices."""
    x = ((points[:, 0] - ra0 + 180) % 360 - 180) * np.cos(np.radians(dec0))
    y = points[:, 1] - dec0
    xy = np.c_[x, y]
    try:
        v = ConvexHull(xy).vertices
    except Exception:
        v = np.arange(len(xy))
    h = xy[v]
    ra = (ra0 + h[:, 0] / np.cos(np.radians(dec0))) % 360
    return np.c_[ra, dec0 + h[:, 1]], float(np.max(np.hypot(h[:, 0], h[:, 1])))


def main():
    rows, page = [], 1
    while True:
        d = mast(page)
        rows += d["data"]
        p = d["paging"]
        print(f"   MAST page {page}/{p['pagesFiltered']}: {len(rows)} frames", flush=True)
        if page >= p["pagesFiltered"]:
            break
        page += 1

    groups, programs = {}, {}
    for r in rows:
        if r["s_ra"] is None or r["s_dec"] is None:
            continue
        inst = INST.get((r["instrument_name"] or "").split("/")[0].upper(), r["instrument_name"] or "")
        key = (r["proposal_id"], r["target_name"], inst, round(r["s_ra"], 3), round(r["s_dec"], 3))
        g = groups.setdefault(key, {"pts": [], "filters": set(), "mjd": r["t_min"], "obs": r["obs_id"],
                                    "ra": r["s_ra"], "dec": r["s_dec"]})
        for poly in polygons(r["s_region"]):
            g["pts"].append(poly)
        g["filters"].update(f for f in (r["filters"] or "").replace(";", " ").split() if f.upper() != "CLEAR")
        if r["t_min"] and (g["mjd"] is None or r["t_min"] < g["mjd"]):
            g["mjd"] = r["t_min"]
        programs[r["proposal_id"]] = r["obs_title"] or ""

    out = []
    for (pid, target, inst, _, _), g in groups.items():
        if not g["pts"]:
            continue
        h, rad = hull(np.vstack(g["pts"]), g["ra"], g["dec"])
        flat = [round(float(v), 4) for xy in h for v in xy]
        out.append([round(g["ra"], 5), round(g["dec"], 5), round(rad, 4), inst, target, pid,
                    round(g["mjd"] or 0, 1), " ".join(sorted(g["filters"])), g["obs"], flat])
    out.sort(key=lambda p: p[0])                  # by RA, so the apps can binary-search a strip of sky
    data = {"updated": date.today().isoformat(), "count": len(rows), "programs": programs, "p": out}
    path = ROOT / "app" / "data" / "webb.json"
    path.write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False))
    print(f"webb.json: {len(rows)} frames -> {len(out)} pointings, {len(programs)} programmes, "
          f"{path.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
