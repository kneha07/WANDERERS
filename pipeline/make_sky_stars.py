"""Build the small sky files the Sky Compass draws from. Standard library only, no network for the stars.

    python pipeline/make_sky_stars.py               # app/data/skystars.json from the star database
    python pipeline/make_sky_stars.py --constellations # also refresh app/data/constellations.json (needs the network)

Stars: every star a human eye can see (V <= 6.5) from app/data/stars/index.json, the team's star database
(pipeline/stardb.py: HYG v4.1, CC BY-SA 4.0). One source, so a star tapped in the compass opens the same
record in the Star database tab. Rows are sorted bright to faint so the page can stop at the chosen faintness:

    [ra_deg, dec_deg, vmag, spectral_letter, hip_number_or_key, distance_ly_or_0, constellation_index, name?]

The name is left out when it is only "HIP <number>". Constellation names are listed once in meta.cons.

Constellation lines: d3-celestial (Olaf Frohn, BSD 3-Clause), https://github.com/ofrohn/d3-celestial.
"""
import json
import sys
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "app" / "data"
NAKED_EYE = 6.5
LY_PER_PC = 3.26156
D3 = "https://raw.githubusercontent.com/ofrohn/d3-celestial/master/data/"


def stars():
    db = json.loads((DATA / "stars" / "index.json").read_text(encoding="utf-8"))
    cons, rows = [], []
    for s in db["stars"]:
        if s.get("mag") is None or s["mag"] > NAKED_EYE or s.get("ra") is None or s.get("dec") is None:
            continue
        con = s.get("con") or ""
        if con not in cons:
            cons.append(con)
        hip = s.get("hip")
        dist = s.get("dist_pc")
        ly = round(dist * LY_PER_PC, 1 if dist and dist < 30 else 0) if dist and 0 < dist < 90000 else 0   # HYG writes 100000 for unknown
        row = [round(s["ra"], 3), round(s["dec"], 3), round(s["mag"], 2), (s.get("spect") or " ")[0].upper(),
               hip if hip and s["key"] == f"hip{hip}" else s["key"], ly, cons.index(con)]
        if s.get("name") and s["name"] != f"HIP {hip}":
            row.append(s["name"])
        rows.append(row)
    rows.sort(key=lambda r: r[2])
    out = {"meta": {"source": "HYG Database v4.1 (astronexus), CC BY-SA 4.0, through app/data/stars/index.json",
                    "fields": "ra, dec (deg, J2000), V mag, spectral letter, HIP number or key, distance (ly, 0 = unknown), constellation index, name",
                    "cons": cons}, "stars": rows}
    path = DATA / "skystars.json"
    path.write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(rows)} stars -> {path} ({path.stat().st_size / 1024:.0f} KB); brightest {rows[0]}; "
          f"to 6.0: {sum(r[2] <= 6.0 for r in rows)}, to 4.5: {sum(r[2] <= 4.5 for r in rows)}, to 3.0: {sum(r[2] <= 3.0 for r in rows)}")


def constellations():
    def get(name):
        with urllib.request.urlopen(D3 + name, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    names = {f["id"]: f for f in get("constellations.json")["features"]}
    out = []
    for f in get("constellations.lines.json")["features"]:
        n = names.get(f["id"])
        if not n:
            continue
        cra, cdec = n["geometry"]["coordinates"]
        # one flat list per stroke: ra, dec, ra, dec, ... with RA in 0..360
        lines = [[round(v % 360 if i == 0 else v, 2) for pt in stroke for i, v in enumerate(pt)] for stroke in f["geometry"]["coordinates"]]
        # the Latin name, as in the star database ("in Piscis Austrinus")
        out.append({"id": f["id"], "name": n["properties"]["name"], "ra": round(cra % 360, 1), "dec": round(cdec, 1), "lines": lines})
    path = DATA / "constellations.json"
    path.write_text(json.dumps({"meta": {"source": "d3-celestial by Olaf Frohn, BSD 3-Clause, https://github.com/ofrohn/d3-celestial"},
                                "list": out}, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(out)} constellations, {sum(len(c['lines']) for c in out)} strokes -> {path} ({path.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    stars()
    if "--constellations" in sys.argv:
        constellations()
