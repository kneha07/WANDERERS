"""Link every WANDERERS result to the star-path prediction model (past path and future path).

    python pipeline/link_paths.py          (after make_stars.py, stardb.py and star_ml.py)

1. app/data/stars.json (the name search, 9,265 stars) gains each star's motion from the star database
   (app/data/stars/index.json, HYG v4.1): proper motion, radial velocity and the database key, matched by
   Hipparcos number, then by name. Rows become [..., flags, pmra, pmdec, rv, key]. Every prepared target in
   app/data/index.json is linked to its row first ("W:<id>" in flags, see make_stars.link_targets).
2. app/data/paths.json maps each WANDERERS target to its starting state for the path model:
   the scikit-learn path (app/data/stars/pred/<key>.json) when one has been learnt, else the target's own
   reference (Gaia DR3 or the published motion), so a path can be drawn for every target.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_stars import link_targets

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "app" / "data"


def main():
    db = json.loads((DATA / "stars" / "index.json").read_text())["stars"]
    by_hip = {s["hip"]: s for s in db if s.get("hip")}
    by_name = {}
    for s in db:
        for n in [s["name"], *s.get("aliases", [])]:
            by_name.setdefault(n.lower(), s)
    preds = {p.stem for p in (DATA / "stars" / "pred").glob("*.json") if p.stem != "index"}

    # 1. motion for the name search, and every prepared target linked to its row (targets added with
    #    fetch.py --ra/--dec after make_stars.py ran would otherwise be missing from the search)
    rows = json.loads((DATA / "stars.json").read_text())
    for r in rows:
        r[:] = r[:9]                                   # idempotent: drop columns from an earlier run
    link_targets(rows, json.loads((DATA / "index.json").read_text()))
    hit = 0
    for r in rows:
        names = [r[0], *(r[1].split("|") if r[1] else [])]
        s = next((by_hip[int(n[4:])] for n in names if n.startswith("HIP ") and n[4:].isdigit() and int(n[4:]) in by_hip), None)
        s = s or next((by_name[n.lower()] for n in names if n.lower() in by_name), None)
        if s and s.get("pmra") is not None:
            r += [s["pmra"], s["pmdec"], s.get("rv"), s["key"]]
            hit += 1
    (DATA / "stars.json").write_text(json.dumps(rows, separators=(",", ":"), ensure_ascii=False))

    # 2. every WANDERERS target -> its path source
    paths = {}
    for t in json.loads((DATA / "index.json").read_text()):
        tj = json.loads((DATA / t["id"] / "target.json").read_text())
        ref = tj["reference"]
        key = f"wanderers_{t['id']}" if f"wanderers_{t['id']}" in preds else None
        if not key:
            s = by_name.get(t["name"].lower())
            if s is None and ref.get("source_id"):
                s = next((x for x in db if str(x.get("gaia_dr3") or "") == str(ref["source_id"])), None)
            key = s["key"] if s else None
        plx = ref.get("parallax")
        plx = plx if plx and plx > 0 else None          # a zero or negative (noisy Gaia) parallax gives no distance
        if not plx and key:
            s = next((x for x in db if x["key"] == key), None)
            plx = 1000 / s["dist_pc"] if s and s.get("dist_pc") else None
        paths[t["id"]] = {"name": t["name"], "key": key, "learnt": bool(key and key in preds),
                          "state": {"ra": ref["ra"], "dec": ref["dec"], "pmra": ref.get("pmra") or 0, "pmdec": ref.get("pmdec") or 0,
                                    "plx": plx, "rv": None, "epoch": ref.get("epoch", 2016.0), "source": ref.get("source", "")}}
        if key:
            s = next((x for x in db if x["key"] == key), None)
            if s and s.get("rv") is not None:
                paths[t["id"]]["state"]["rv"] = s["rv"]
    (DATA / "paths.json").write_text(json.dumps(paths, indent=1))
    print(f"name search: motion for {hit} of {len(rows)} stars")
    for tid, p in paths.items():
        print(f"  {p['name']:<18} key={p['key']!s:<22} learnt={p['learnt']}  plx={p['state']['plx']}")


if __name__ == "__main__":
    main()
