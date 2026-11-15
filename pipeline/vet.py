"""Vet the automatic mover search, so the page can list "what else changed in this field" honestly.

    python pipeline/vet.py             # all targets, with a SIMBAD look-up at both ends of each mover
    python pipeline/vet.py --offline   # image and Gaia checks only

analyze.py pairs a dot seen only in WISE 2010 with a dot seen only in SPHEREx (movers_experimental).
Most such pairs are not real movers. Each one is graded here by stated rules, first match wins:

    target     both ends lie on the mission target's own measured path
    rejected   one end is the target (wrong pairing), an end is at the field edge, or an end sits
               on a catalogued object that does not move (Gaia circle or SIMBAD entry)
    known      Gaia DR3 or SIMBAD has an object that moves along this path
    candidate  nothing above applies. Still unconfirmed: it needs a human look and a report.

Writes target.json -> "changes". Needs only the standard library. Run after analyze.py.
"""
import json
import math
import sys
import urllib.parse
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "app" / "data"
TOL = 4.0            # grid pixels: "same place", the tolerance analyze.py uses
GHOST_TOL = 3.0      # grid pixels: an end "sits on" a Gaia star
EDGE = 8.0           # grid pixels from the border
SIMBAD_RADIUS = 10.0     # arcsec, about 1.5 SPHEREx pixels
STATIC_PM = 0.2          # arcsec/yr: slower than this cannot explain a mover the search can find
FAST = 5.0               # arcsec/yr: faster than almost every known object
OLD_EPOCH = 2010.5       # AllWISE
SIMBAD = ["https://simbad.cds.unistra.fr/simbad/sim-tap/sync", "https://simbad.harvard.edu/simbad/sim-tap/sync"]


def start_radec(m):
    """Sky position of the 2010 end, from the 2025+ end and the motion analyze.py stored with it."""
    dt = m["year"] - OLD_EPOCH
    dec0 = m["dec"] - m["pmdec"] * dt / 3.6e6
    ra0 = m["ra"] - m["pmra"] * dt / 3.6e6 / math.cos(math.radians(m["dec"]))
    return ra0 % 360, dec0


def simbad_cone(ra, dec, radius=SIMBAD_RADIUS, timeout=30):
    """Catalogued objects near a position: [{name, otype, pm (arcsec/yr or None), sep (arcsec)}]. Raises if no mirror answers."""
    q = ("SELECT TOP 5 main_id, otype, ra, dec, pmra, pmdec FROM basic WHERE "
         f"CONTAINS(POINT('ICRS',ra,dec),CIRCLE('ICRS',{ra:.6f},{dec:.6f},{radius / 3600:.6f}))=1")
    body = urllib.parse.urlencode({"request": "doQuery", "lang": "adql", "format": "json", "query": q}).encode()
    err = None
    for url in SIMBAD:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=timeout) as r:
                rows = json.loads(r.read().decode())["data"]
            out = []
            for name, otype, r_, d_, pmra, pmdec in rows:
                sep = math.hypot((r_ - ra) * math.cos(math.radians(dec)), d_ - dec) * 3600
                pm = None if pmra is None or pmdec is None else math.hypot(pmra, pmdec) / 1000
                out.append({"name": " ".join(str(name).split()), "otype": otype, "pm": pm, "sep": round(sep, 1)})
            return sorted(out, key=lambda o: o["sep"])
        except Exception as e:      # the page was down at CDS during the hackathon: try the mirror
            err = e
    raise RuntimeError(f"SIMBAD did not answer: {err}")


def _near(x, y, pts, tol):
    return any(math.hypot(x - px, y - py) < tol for px, py in pts)


def grade(t, lookups=None):
    """Grade every mover of one target. lookups: {mover index: {"start": [...], "end": [...]}} from simbad_cone, or None."""
    npix = t["grid"]["npix"]
    track = sorted((p for p in t.get("track") or [] if (p.get("ch") or "w2") == "w2"), key=lambda p: p["year"])
    t_old = [(p["x"], p["y"]) for p in track if p.get("mission") == "WISE"]
    t_new = [(p["x"], p["y"]) for p in track if p.get("mission") != "WISE"]
    ghosts = t.get("ghosts") or {}
    old_png = {f["png"] for f in (t.get("frames") or {}).get("w2", []) if f.get("mission") == "WISE"}
    g_old = [tuple(g[:2]) for k, v in ghosts.items() if k in old_png for g in v]
    g_new = [tuple(g[:2]) for k, v in ghosts.items() if k not in old_png for g in v]
    out = []
    for i, m in enumerate(t.get("movers_experimental") or []):
        ra0, dec0 = start_radec(m)
        look = (lookups or {}).get(i)
        on_old, on_new = _near(m["x0"], m["y0"], t_old, TOL), _near(m["x1"], m["y1"], t_new, TOL)
        edge = min(m["x0"], m["y0"], m["x1"], m["y1"]) < EDGE or max(m["x0"], m["y0"], m["x1"], m["y1"]) > npix - 1 - EDGE
        # A Gaia star that is under this end in BOTH epochs does not move: the dot is that star.
        star0 = _near(m["x0"], m["y0"], g_old, GHOST_TOL) and _near(m["x0"], m["y0"], g_new, GHOST_TOL)
        star1 = _near(m["x1"], m["y1"], g_new, GHOST_TOL) and _near(m["x1"], m["y1"], g_old, GHOST_TOL)
        static = mover = None
        for end, objs in (look or {}).items():
            for o in objs:
                if o["pm"] is not None and abs(o["pm"] - m["arcsec_per_yr"]) < 0.3 * m["arcsec_per_yr"]:
                    mover = mover or o
                elif (o["pm"] or 0) < STATIC_PM:
                    static = static or dict(o, end=end)

        if on_old and on_new:
            status, reason = "target", "This is the mission target itself: both ends lie on its measured path."
        elif on_old or on_new:
            status, reason = "rejected", ("Wrong pairing: one end is the mission target, the other end is a different dot.")
        elif m.get("explained_by_gaia"):
            status, reason = "known", f"Gaia DR3 star {m['gaia_source_id']} moves along this path."
        elif mover:
            status, reason = "known", f"SIMBAD lists {mover['name']} here, moving {mover['pm']:.2f}″ per year."
        elif edge:
            status, reason = "rejected", "An end is at the edge of the picture, where a dot can appear or vanish without moving."
        elif star0 or star1:
            status, reason = "rejected", (f"The {'2010' if star0 else 'SPHEREx'} end sits on a Gaia star that does not move. "
                                          "The dot is that star, seen in one image and missed in the other.")
        elif static:
            status, reason = "rejected", (f"The {'2010' if static['end'] == 'start' else 'SPHEREx'} end sits on a catalogued object that does not move "
                                          f"({static['name']}, SIMBAD type {static['otype']}, {static['sep']:.0f}″ away).")
        else:
            status = "candidate"
            reason = "No catalogue explains this pair" + ("." if look is not None else " (SIMBAD was not checked).")
            if m["arcsec_per_yr"] >= FAST:
                reason += (f" Be sceptical: very few known objects move {FAST:.0f}″ per year or more, so two unrelated dots "
                           "paired by chance are far more likely than a real mover.")
            if m["snr"] < 8:
                reason += " The dots are faint (signal under 8 times the noise)."
        out.append({"n": i + 1, "status": status, "reason": reason, "arcsec_per_yr": round(m["arcsec_per_yr"], 2),
                    "snr": m["snr"], "x0": round(m["x0"], 1), "y0": round(m["y0"], 1), "x1": round(m["x1"], 1), "y1": round(m["y1"], 1),
                    "ra": round(m["ra"], 5), "dec": round(m["dec"], 5), "ra0": round(ra0, 5), "dec0": round(dec0, 5),
                    "year": round(m["year"], 2), "simbad_checked": look is not None})
    # Did the search find the mission target on its own? Only asked when the target moves far enough to be found.
    mo = t.get("motion") or {}
    recovered = any(c["status"] == "target" for c in out) if mo.get("shift_arcsec", 0) >= 2 * TOL * t["grid"]["arcsec_per_pix"] else None
    order = {"candidate": 0, "known": 1, "target": 2, "rejected": 3}
    out.sort(key=lambda c: (order[c["status"]], -c["snr"]))
    return {"found": len(out), "candidates": sum(c["status"] == "candidate" for c in out), "target_recovered": recovered, "items": out,
            "method": "Dots seen only in WISE 2010 are paired with dots seen only in SPHEREx at 4.6 µm, 8″ to 190″ apart "
                      "and of similar brightness. Each pair is then checked against the target's path, Gaia DR3 and SIMBAD.",
            "not_checked": "Asteroids and comets are not checked. An unconfirmed pair is not a discovery."}


def main():
    offline = "--offline" in sys.argv
    for f in sorted(DATA.glob("*/target.json")):
        t = json.loads(f.read_text(encoding="utf-8"))
        lookups = None
        if not offline:
            try:
                lookups = {}
                for i, m in enumerate(t.get("movers_experimental") or []):
                    lookups[i] = {"start": simbad_cone(*start_radec(m)), "end": simbad_cone(m["ra"], m["dec"])}
            except RuntimeError as e:
                print(f"   {e}; grading {t['id']} without SIMBAD", flush=True)
                lookups = None
        t["changes"] = grade(t, lookups)
        f.write_text(json.dumps(t, indent=1), encoding="utf-8")
        print(f"{t['name']:<18} movers {t['changes']['found']}, unconfirmed {t['changes']['candidates']}, "
              f"target recovered: {t['changes']['target_recovered']}")
        for c in t["changes"]["items"]:
            print(f"   #{c['n']} {c['status']:<9} {c['arcsec_per_yr']:5.2f}″/yr  {c['reason']}")


if __name__ == "__main__":
    # A Windows console is cp1252 by default and cannot print ″ (issue #46): write UTF-8, and never crash on a character.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
