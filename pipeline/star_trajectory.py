"""Predict where each target star is on the sky at any moment, and check the prediction against
the positions WANDERERS measured in the WISE and SPHEREx frames.

    python pipeline/star_trajectory.py                 # every target in app/data/
    python pipeline/star_trajectory.py barnard wise0855
    python pipeline/star_trajectory.py --forecast 2027 2030 2035

Reads app/data/<target>/target.json (written by analyze.py) and writes
app/data/<target>/trajectory.json, which the web page draws over the time-lapse.
No image cache and no network are needed, so this runs on a fresh clone.

The model is the standard astrometric one used for Gaia stars:

  * Proper motion. The catalogue position at its reference epoch is carried along its space
    motion with astropy's apply_space_motion (straight line through space, so the slow curving
    of very fast stars' paths is included when a parallax is known).
  * Parallax. Earth goes round the Sun, so a nearby star traces a small yearly loop on the sky.
    The shift is  dRA* = plx (X sin a - Y cos a),  dDec = plx (X cos a sin d + Y sin a sin d - Z cos d),
    with (X, Y, Z) Earth's barycentric position in AU (astropy's built-in ephemeris, offline).
    WISE and SPHEREx orbit the Earth only ~600-700 km up, so the Earth's centre stands in for them
    (the error is below 0.0001 arcsec).

Aberration and light bending are left out on purpose: they shift every star in a small field by
the same amount, and the images' WCS is tied to those same stars, so they cancel.

Honest limits are written into the output: the AllWISE 2010 frame is a coadd of 2010-2011 scans
(its date is a stand-in, so its parallax term is only approximate), and no catalogue uncertainties
are propagated (the cached reference does not carry them), so forecasts are stated without error bars.
"""
import argparse, json, sys, warnings
from pathlib import Path

import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord, Distance, get_body_barycentric, solar_system_ephemeris
from astropy.time import Time
from astropy.wcs import WCS
from erfa import ErfaWarning


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "app" / "data"

PATH_START, PATH_END, PATH_STEP_DAYS = 2010.0, 2030.0, 5.0
DEFAULT_FORECAST = (2027.0, 2030.0, 2035.0)
MAS = 1 / 3.6e6          # degrees per milliarcsecond


def earth_xyz_au(years):
    """Earth's barycentric position (ICRS axes) in AU at each decimal year. Shape (3, n)."""
    t = Time(np.atleast_1d(np.asarray(years, float)), format="jyear")
    with solar_system_ephemeris.set("builtin"), warnings.catch_warnings():
        warnings.simplefilter("ignore", ErfaWarning)
        return get_body_barycentric("earth", t).xyz.to(u.au).value


def parallax_offsets(ra_deg, dec_deg, years, parallax_mas):
    """Parallax shift (dRA*cos(dec), dDec) in mas for a star at (ra, dec) seen from Earth."""
    X, Y, Z = earth_xyz_au(years)
    a, d = np.radians(ra_deg), np.radians(dec_deg)
    p = parallax_mas or 0.0
    dra = p * (X * np.sin(a) - Y * np.cos(a))
    ddec = p * (X * np.cos(a) * np.sin(d) + Y * np.sin(a) * np.sin(d) - Z * np.cos(d))
    return dra, ddec


def predict(ref, years, parallax=True):
    """Predicted (ra, dec) in degrees at each decimal year, from a reference dict with
    ra, dec, epoch, pmra, pmdec (mas/yr) and optionally parallax (mas) and radial_velocity (km/s)."""
    years = np.atleast_1d(np.asarray(years, float))
    plx = ref.get("parallax") or 0.0
    kw = {}
    if plx > 0:
        kw["distance"] = Distance(parallax=plx * u.mas)
        if ref.get("radial_velocity") is not None:
            kw["radial_velocity"] = ref["radial_velocity"] * u.km / u.s
    c = SkyCoord(ref["ra"] * u.deg, ref["dec"] * u.deg,
                 pm_ra_cosdec=(ref.get("pmra") or 0) * u.mas / u.yr, pm_dec=(ref.get("pmdec") or 0) * u.mas / u.yr,
                 obstime=Time(ref["epoch"], format="jyear"), **kw)
    with warnings.catch_warnings():
        # Expected notices: forecast dates lie past the last announced leap second (a ~1 s effect),
        # and a star without a parallax gets ERFA's stand-in distance (no effect on its direction).
        warnings.simplefilter("ignore", ErfaWarning)
        moved = c.apply_space_motion(new_obstime=Time(years, format="jyear"))
    ra, dec = moved.ra.deg, moved.dec.deg
    if parallax and plx > 0:
        dra, ddec = parallax_offsets(ra, dec, years, plx)
        dec = dec + ddec * MAS
        ra = ra + dra * MAS / np.cos(np.radians(dec))
    return np.asarray(ra, float), np.asarray(dec, float)


def grid_wcs(grid):
    """The display grid analyze.py drew the frames on (north up, TAN, arcsec_per_pix)."""
    n, s = grid["npix"], grid["arcsec_per_pix"]
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [grid["centre_ra"], grid["centre_dec"]]
    w.wcs.crpix = [n / 2 + 0.5, n / 2 + 0.5]
    w.wcs.cdelt = [-s / 3600, s / 3600]
    return w


def sep_arcsec(ra1, dec1, ra2, dec2):
    return SkyCoord(ra1 * u.deg, dec1 * u.deg).separation(SkyCoord(ra2 * u.deg, dec2 * u.deg)).arcsec


def rms(v):
    v = [x for x in v if x is not None and np.isfinite(x)]
    return float(np.sqrt(np.mean(np.square(v)))) if v else None


def build(t, start=PATH_START, end=PATH_END, step_days=PATH_STEP_DAYS, forecast=DEFAULT_FORECAST):
    """Trajectory for one target.json dict. Pure function of its reference, grid and track."""
    ref, grid = t["reference"], t["grid"]
    w = grid_wcs(grid)
    n = grid["npix"]

    # Sampled path in display pixels, with and without the yearly parallax loop.
    years = np.arange(start, end + 1e-9, step_days / 365.25)
    ra, dec = predict(ref, years)
    x, y = w.world_to_pixel(SkyCoord(ra * u.deg, dec * u.deg))
    ra0, dec0 = predict(ref, years, parallax=False)
    x0, y0 = w.world_to_pixel(SkyCoord(ra0 * u.deg, dec0 * u.deg))
    path = [[round(float(a), 4), round(float(b), 3), round(float(c), 3)] for a, b, c in zip(years, x, y)]
    path_pm = [[round(float(a), 4), round(float(b), 3), round(float(c), 3)] for a, b, c in zip(years, x0, y0)]

    # The measured positions, each compared with both models.
    checks = []
    for p in sorted(t.get("track") or [], key=lambda p: (p.get("ch", "w2"), p["year"])):
        (pra,), (pdec,) = predict(ref, [p["year"]])
        (qra,), (qdec,) = predict(ref, [p["year"]], parallax=False)
        px, py = w.world_to_pixel(SkyCoord(pra * u.deg, pdec * u.deg))
        checks.append({
            "year": p["year"], "ch": p.get("ch", "w2"), "mission": p["mission"],
            "measured_ra": p["ra"], "measured_dec": p["dec"],
            "pred_ra": float(pra), "pred_dec": float(pdec), "pred_x": float(px), "pred_y": float(py),
            "resid_arcsec": round(float(sep_arcsec(p["ra"], p["dec"], pra, pdec)), 3),
            "resid_pm_only_arcsec": round(float(sep_arcsec(p["ra"], p["dec"], qra, qdec)), 3),
            "epoch_approx": p["mission"] == "WISE",       # AllWISE coadd: 2010.5 is a stand-in date
        })

    # Size of the yearly loop over one year centred on the newest data.
    yr = np.linspace(2026.0, 2027.0, 73)
    dra, ddec = parallax_offsets(ref["ra"], ref["dec"], yr, ref.get("parallax") or 0)
    loop = float(np.max(np.hypot(dra, ddec)) / 1000)

    fc = []
    for fy in forecast:
        (fra,), (fdec,) = predict(ref, [fy])
        fx, fyp = w.world_to_pixel(SkyCoord(fra * u.deg, fdec * u.deg))
        fc.append({"year": float(fy), "ra": round(float(fra), 7), "dec": round(float(fdec), 7),
                   "x": round(float(fx), 2), "y": round(float(fyp), 2),
                   "in_field": bool(0 <= fx < n and 0 <= fyp < n),
                   "moved_since_ref_arcsec": round(float(sep_arcsec(ref["ra"], ref["dec"], fra, fdec)), 2)})

    by_model = lambda key, mission=None: rms([c[key] for c in checks if mission in (None, c["mission"])])
    pm_total = float(np.hypot(ref.get("pmra") or 0, ref.get("pmdec") or 0))
    return {
        "id": t["id"], "name": t["name"],
        "model": "proper motion + annual parallax (geocentric), astropy built-in ephemeris",
        "reference": {k: ref.get(k) for k in ("source", "epoch", "ra", "dec", "pmra", "pmdec", "parallax")},
        "proper_motion_arcsec_per_yr": round(pm_total / 1000, 4),
        "parallax_loop_arcsec": round(loop, 3),
        "path": {"start": start, "end": end, "step_days": step_days, "fields": ["year", "x", "y"],
                 "with_parallax": path, "proper_motion_only": path_pm},
        "checks": checks,
        "summary": {
            "n_measured": len(checks),
            "rms_arcsec": by_model("resid_arcsec"),
            "rms_pm_only_arcsec": by_model("resid_pm_only_arcsec"),
            "rms_spherex_arcsec": by_model("resid_arcsec", "SPHEREx"),
            "rms_spherex_pm_only_arcsec": by_model("resid_pm_only_arcsec", "SPHEREx"),
        },
        "forecast": fc,
        "limits": [
            "AllWISE 2010 is a coadd of 2010-2011 scans; its date (2010.5) is a stand-in, so the parallax term there is approximate.",
            "No catalogue uncertainties are propagated; forecasts are shown without error bars.",
            "Positions are measured on 2 arcsec display pixels from SPHEREx's 6.15 arcsec pixels; sub-arcsecond residuals are at the noise level.",
        ],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("targets", nargs="*", help="target ids (default: every app/data/<id>/target.json)")
    ap.add_argument("--forecast", nargs="+", type=float, default=list(DEFAULT_FORECAST), help="decimal years to forecast")
    a = ap.parse_args(argv)
    ids = a.targets or [p.parent.name for p in sorted(DATA.glob("*/target.json"))]
    for tid in ids:
        f = DATA / tid / "target.json"
        if not f.exists():
            print(f"!! {tid}: no {f.relative_to(ROOT)} (run analyze.py first)", flush=True)
            continue
        tr = build(json.loads(f.read_text()), forecast=a.forecast)
        (DATA / tid / "trajectory.json").write_text(json.dumps(tr, separators=(",", ":")))
        s = tr["summary"]
        fmt = lambda v: "n/a" if v is None else f"{v:.2f}\""
        print(f"== {tr['name']}: {tr['proper_motion_arcsec_per_yr']:.2f}\"/yr, parallax loop ±{tr['parallax_loop_arcsec']:.2f}\"  "
              f"rms vs measured {fmt(s['rms_arcsec'])} (proper motion only {fmt(s['rms_pm_only_arcsec'])}; "
              f"SPHEREx only {fmt(s['rms_spherex_arcsec'])} vs {fmt(s['rms_spherex_pm_only_arcsec'])})", flush=True)
        for c in tr["forecast"]:
            print(f"   {c['year']:.1f}: RA {c['ra']:.5f} Dec {c['dec']:+.5f}  ({'in' if c['in_field'] else 'outside'} this field)", flush=True)


if __name__ == "__main__":
    sys.exit(main())
