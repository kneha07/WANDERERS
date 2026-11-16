"""Build the small sky files the Sky Compass draws from. Standard library only; needs the network.

    python pipeline/make_sky_stars.py               # app/data/skystars.json from NASA HEASARC + the star database
    python pipeline/make_sky_stars.py --constellations # also refresh app/data/constellations.json (needs the network)
    python pipeline/make_sky_stars.py --deep        # also app/data/skydeep/raNN.json: every fainter Hipparcos star

Deep stars (--deep): every other star of the HEASARC Hipparcos table (V > 6.5, about 109,000), for taps on the survey
photographs when zoomed in. One file per 15 degrees of RA (ra00.json .. ra23.json), so the page loads only the slices
in view. Rows are sorted bright to faint: [ra_deg, dec_deg, vmag, spectral_type, hip_number, distance_ly_or_0].

Stars: every star a human eye can see (V <= 6.5). Position, V magnitude and spectral type come from the
Hipparcos Main Catalogue as served by NASA HEASARC (table "hipparcos"), moved from epoch J1991.25 to J2000
with each star's proper motion. Names, HIP keys, distances and constellations come from app/data/stars/index.json,
the team's star database (pipeline/stardb.py: HYG v4.1, CC BY-SA 4.0), so a star tapped in the compass opens the
same record in the Star database tab. A star without a Hipparcos row keeps its HYG values.
Rows are sorted bright to faint so the page can stop at the chosen faintness:

    [ra_deg, dec_deg, vmag, spectral_letter, hip_number_or_key, distance_ly_or_0, constellation_index, name?]

The name is left out when it is only "HIP <number>". Constellation names are listed once in meta.cons.

Constellation lines: d3-celestial (Olaf Frohn, BSD 3-Clause), https://github.com/ofrohn/d3-celestial.
"""
import json
import math
import sys
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "app" / "data"
NAKED_EYE = 6.5
LY_PER_PC = 3.26156
# the TAP endpoint answers only in binary VOTable; xamin's text query is plain "|"-separated rows
HEASARC = ("https://heasarc.gsfc.nasa.gov/xamin/query?table=hipparcos&fields=hip_number,ra_deg,dec_deg,vmag,pm_ra,pm_dec,spect_type,parallax,parallax_error"
           "&resultmax=0&format=text")
YEARS = 2000.0 - 1991.25
D3 = "https://raw.githubusercontent.com/ofrohn/d3-celestial/master/data/"


def hipparcos(constraint="", min_rows=15000):
    """{hip: (ra, dec, vmag, spectral type, parallax mas, parallax error mas)} at J2000 from NASA HEASARC; pm_ra already includes cos(dec)."""
    with urllib.request.urlopen(HEASARC + constraint, timeout=300) as r:
        text = r.read().decode("utf-8")
    out = {}
    for line in text.splitlines():
        f = ["" if x.strip() == "null" else x.strip() for x in line.split("|")]
        if len(f) != 9 or not f[0].isdigit() or not (f[1] and f[2] and f[3]):
            continue
        ra, dec, pmra, pmdec = float(f[1]), float(f[2]), float(f[4] or 0), float(f[5] or 0)
        dec2 = dec + pmdec * YEARS / 3.6e6
        ra2 = (ra + pmra * YEARS / 3.6e6 / max(1e-6, math.cos(math.radians(dec)))) % 360
        out[int(f[0])] = (ra2, dec2, float(f[3]), f[6], float(f[7] or 0), float(f[8] or 0))
    if "OVERFLOW" in text or len(out) < min_rows:
        sys.exit(f"HEASARC answer looks cut short ({len(out)} rows)")
    return out


def stars():
    hip_rows = hipparcos("&constraint=vmag%3C%3D7")
    db = json.loads((DATA / "stars" / "index.json").read_text(encoding="utf-8"))
    cons, rows, nasa, hyg_only = [], [], 0, 0
    for s in db["stars"]:
        hip = s.get("hip")
        h = hip_rows.get(hip) if hip else None
        if h:
            ra, dec, mag, letter = h[0], h[1], h[2], (h[3] or " ")[0].upper()
            nasa += 1
        else:
            ra, dec, mag, letter = s.get("ra"), s.get("dec"), s.get("mag"), (s.get("spect") or " ")[0].upper()
        if mag is None or mag > NAKED_EYE or ra is None or dec is None:
            nasa -= 1 if h else 0
            continue
        hyg_only += 0 if h else 1
        con = s.get("con") or ""
        if con not in cons:
            cons.append(con)
        dist = s.get("dist_pc")
        ly = round(dist * LY_PER_PC, 1 if dist and dist < 30 else 0) if dist and 0 < dist < 90000 else 0   # HYG writes 100000 for unknown
        row = [round(ra, 3), round(dec, 3), round(mag, 2), letter,
               hip if hip and s["key"] == f"hip{hip}" else s["key"], ly, cons.index(con)]
        if s.get("name") and s["name"] != f"HIP {hip}":
            row.append(s["name"])
        rows.append(row)
    sirius = next(r for r in rows if r[4] == 32349)
    assert abs(sirius[0] - 101.287) < 0.002 and abs(sirius[1] + 16.716) < 0.002, sirius   # proper motion applied
    rows.sort(key=lambda r: r[2])
    out = {"meta": {"source": "Hipparcos Main Catalogue (ESA) via NASA HEASARC, positions moved to J2000; names, keys and distances: HYG Database v4.1 (astronexus), CC BY-SA 4.0",
                    "fields": "ra, dec (deg, J2000), V mag, spectral letter, HIP number or key, distance (ly, 0 = unknown), constellation index, name",
                    "cons": cons}, "stars": rows}
    path = DATA / "skystars.json"
    path.write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"{nasa} from HEASARC Hipparcos, {hyg_only} HYG only")
    print(f"{len(rows)} stars -> {path} ({path.stat().st_size / 1024:.0f} KB); brightest {rows[0]}; "
          f"to 6.0: {sum(r[2] <= 6.0 for r in rows)}, to 4.5: {sum(r[2] <= 4.5 for r in rows)}, to 3.0: {sum(r[2] <= 3.0 for r in rows)}")


def deep():
    shown = {r[4] for r in json.loads((DATA / "skystars.json").read_text(encoding="utf-8"))["stars"]}
    rows = [[round(h[0], 3), round(h[1], 3), round(h[2], 2), h[3][:8], hip, round(LY_PER_PC * 1000 / h[4]) if h[4] > 5 * h[5] > 0 else 0]   # distance only from a parallax known to 20%
            for hip, h in hipparcos(min_rows=110000).items() if h[2] > NAKED_EYE and hip not in shown]
    rows.sort(key=lambda r: r[2])
    out = DATA / "skydeep"
    out.mkdir(exist_ok=True)
    for k in range(24):
        part = [r for r in rows if int(r[0] // 15) % 24 == k]
        (out / f"ra{k:02d}.json").write_text(json.dumps({"meta": {"source": "Hipparcos Main Catalogue (ESA) via NASA HEASARC, J2000",
            "fields": "ra, dec (deg), V mag, spectral type, HIP number, distance (ly, 0 = unknown)"}, "stars": part},
            separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
    size = sum(f.stat().st_size for f in out.glob("ra*.json"))
    print(f"{len(rows)} deep stars -> {out} (24 files, {size / 1024:.0f} KB together)")


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
    if "--deep" in sys.argv:
        deep()
    if "--constellations" in sys.argv:
        constellations()
