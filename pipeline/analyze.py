"""Turn cached data for one target into what the web app shows.

    python pipeline/analyze.py barnard        # or: all

Writes app/data/<target>/ : flipbook PNG frames + target.json (epochs, Gaia ghosts, measured
motion, spectrum, brightness change, evidence). Everything here is plain, explainable
measurement; no machine-learning model and no invented numbers.

Science choices, so they can be defended to judges:
  * Wavelength-matched flipbook. SPHEREx records a different wavelength at every point of a
    detector, so we never compare a 1 um image with a 4 um one. The "4.6 um" channel is
    WISE W2 (2010) next to SPHEREx detector 6 (4.4-5.0 um) in 2025 and 2026. The "3.4 um"
    channel is WISE W1 next to SPHEREx images whose wavelength at the target is 3.0-3.8 um.
  * Motion is measured from image centroids, then compared with Gaia's prediction.
  * The spectrum is aperture photometry at the target in every SPHEREx image, each placed
    at the wavelength that image recorded at the target's pixel (from the WCS-WAVE table).
  * Pixels flagged by the SPHEREx pipeline (e.g. saturation) are left out of photometry.
"""
import json, sys, warnings
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.time import Time
from astropy.wcs import WCS
from reproject import reproject_interp

sys.path.insert(0, str(Path(__file__).parent))
from targets import TARGETS
from fetch import predict, CACHE, ROOT, FIELD_ARCSEC

warnings.simplefilter("ignore")
from astropy import log as _astropy_log
_astropy_log.setLevel("WARNING")   # the spectral WCS triggers an expected SIP notice; SIP is turned off right after
OUT = ROOT / "app" / "data"
GRID_PIX = 2.0                      # arcsec per display pixel
NPIX = int(FIELD_ARCSEC / GRID_PIX)


def pixel_sr(w, x, y):
    """Solid angle of one pixel at (x, y), from the image's own WCS (includes distortion)."""
    c = w.pixel_to_world([x - .5, x + .5, x - .5], [y - .5, y - .5, y + .5])
    a = c[0].separation(c[1]).rad
    b = c[0].separation(c[2]).rad
    return float(a * b)

# SPHEREx flag planes that make a pixel unusable for photometry. The FLAGS extension names
# each plane in its header (MSKNnnnn = name, MSKMnnnn = bitmask), so we read them from the
# file instead of hard-coding bit numbers. SOURCE and FULLSAMPLE are informational, kept.
# This is the conservative "CONTAINS_BAD_PIXEL" set used in IRSA's SPHEREx source-discovery
# tutorial (SPHEREx Explanatory Supplement, Table 16).
BAD_NAMES = {"TRANSIENT", "OVERFLOW", "SUR_ERROR", "NONFUNC", "DICHROIC", "MISSING_DATA", "HOT", "COLD",
             "NONLINEAR", "PERSIST", "CROSSTALK", "GHOST", "GHOST_FPA", "GHOST_EXT", "STREAK",
             "BLOOM", "SNOWBALL", "HALO", "SATELLITE_HALO"}


# For the flipbook pictures only hide broken detector pixels; bright stars must stay visible.
DISPLAY_BAD = {"NONFUNC", "MISSING_DATA", "HOT", "COLD", "DICHROIC"}


def bad_mask(flags_hdu, names=BAD_NAMES):
    h = flags_hdu.header
    bits = sum(int(h[k.replace("MSKN", "MSKM")]) for k in h
               if k.startswith("MSKN") and str(h[k]).strip() in names)
    return (flags_hdu.data & bits) != 0

# Molecular absorption bands that matter for cold objects in SPHEREx's range (microns).
BANDS = [
    {"name": "H2O", "lo": 1.30, "hi": 1.50}, {"name": "H2O", "lo": 1.75, "hi": 2.05},
    {"name": "CH4", "lo": 1.60, "hi": 1.80}, {"name": "CH4", "lo": 2.20, "hi": 2.45},
    {"name": "H2O", "lo": 2.55, "hi": 3.00}, {"name": "CH4", "lo": 3.15, "hi": 3.45},
    {"name": "CO2", "lo": 4.20, "hi": 4.35}, {"name": "CO",  "lo": 4.50, "hi": 4.80},
]


def grid_wcs(centre):
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [centre.ra.deg, centre.dec.deg]
    w.wcs.crpix = [NPIX / 2 + 0.5, NPIX / 2 + 0.5]
    w.wcs.cdelt = [-GRID_PIX / 3600, GRID_PIX / 3600]
    return w


def year_of(mjd):
    return float(Time(mjd, format="mjd").jyear)


def load_spherex(tid, ref):
    """Read every cached SPHEREx cutout: epoch, detector, target pixel, wavelength there."""
    out = []
    for f in sorted((CACHE / tid / "spherex").glob("*.fits")):
        h = fits.open(f)
        hd = h["IMAGE"].header
        mjd = hd.get("MJD-AVG") or hd.get("MJD-OBS")
        if mjd is None:
            continue
        yr = year_of(mjd)
        w = WCS(hd).celestial
        c = predict(ref, yr)
        x, y = w.world_to_pixel(c)
        try:
            sw = WCS(hd, fobj=h, key="W"); sw.sip = None
            lam = sw.pixel_to_world(x, y)
            lam = float(lam[0].to(u.um).value if isinstance(lam, (list, tuple)) else lam.to(u.um).value)
        except Exception:
            lam = np.nan
        det = int(hd.get("DETECTOR", 0))
        out.append(dict(file=f, mjd=float(mjd), year=yr, det=det, lam=lam, x=float(x), y=float(y),
                        sr=pixel_sr(w, float(x), float(y)), bunit=hd.get("BUNIT", "")))
    return out


def photometry(img, bad, x, y, r=3.0, r_in=5.0, r_out=8.0):
    """Aperture sum minus local background. Returns (flux in image units * pix, n_bad)."""
    yy, xx = np.indices(img.shape)
    d = np.hypot(xx - x, yy - y)
    ap, ann = d <= r, (d >= r_in) & (d <= r_out)
    if ap.sum() == 0 or ann.sum() < 5:
        return np.nan, 0
    bad = bad | ~np.isfinite(img)
    n_bad = int((bad & ap).sum())
    bg = np.nanmedian(np.where(bad | ~ann, np.nan, img))
    return float(np.nansum(np.where(ap & ~bad, img - bg, 0))), n_bad


def wing_flux(img, bad, x, y, r_in=4.0, r_out=8.0, b_in=11.0, b_out=15.0):
    """Light in the outer wings of a star's image, for stars whose core is saturated.
    Wing light scales with total brightness, so ratios at the same wavelength between two
    epochs still measure a brightness change. Flagged pixels are skipped."""
    yy, xx = np.indices(img.shape)
    d = np.hypot(xx - x, yy - y)
    ok = ~(bad | ~np.isfinite(img))
    wing, bgr = (d >= r_in) & (d <= r_out) & ok, (d >= b_in) & (d <= b_out) & ok
    if wing.sum() < 20 or bgr.sum() < 20:
        return np.nan
    # mean per pixel (not sum) so a few extra flagged pixels do not bias the ratio
    return float(np.mean(img[wing]) - np.median(img[bgr]))


def centroid(img, x0, y0, r=3.5):
    yy, xx = np.indices(img.shape)
    m = np.hypot(xx - x0, yy - y0) <= r
    v = np.where(m & np.isfinite(img), img - np.nanmedian(img), 0)
    v[v < 0] = 0
    if v.sum() <= 0:
        return None
    return float((v * xx).sum() / v.sum()), float((v * yy).sum() / v.sum())


def stretch(a):
    """asinh stretch with robust limits, returns 0..1 float image."""
    a = np.array(a, float)
    fin = a[np.isfinite(a)]
    if fin.size == 0:
        return np.zeros_like(a)
    lo, hi = np.percentile(fin, 20), np.percentile(fin, 99.7)
    z = np.clip((a - lo) / max(hi - lo, 1e-9), 0, 1)
    z = np.arcsinh(z * 10) / np.arcsinh(10)
    return np.nan_to_num(z)


def save_png(a, path):
    plt.imsave(path, stretch(a), cmap="gray", origin="lower", vmin=0, vmax=1)


def analyze(tid):
    t = TARGETS[tid]
    meta = json.loads((CACHE / tid / "gaia.json").read_text())
    ref, stars = meta["ref"], meta["field_stars"]
    out = OUT / tid; out.mkdir(parents=True, exist_ok=True)
    print(f"== {t['name']}", flush=True)

    spx = load_spherex(tid, ref)
    years = sorted(s["year"] for s in spx)
    # SPHEREx visits: group images separated by more than ~60 days.
    visits, cur = [], [years[0]]
    for y in years[1:]:
        (visits.append(cur), cur := [y]) if y - cur[-1] > 60 / 365.25 else cur.append(y)
    visits.append(cur)
    visits = [v for v in visits if len(v) >= 6]          # drop tiny revisits
    vyear = [float(np.mean(v)) for v in visits]

    def visit_of(y):
        for i, v in enumerate(visits):
            if v[0] - 1e-6 <= y <= v[-1] + 1e-6:
                return i
        return None

    # Display grid centred between the first and last epoch, so the whole trail fits.
    mid = predict(ref, (2010.5 + vyear[-1]) / 2)
    gw = grid_wcs(mid)

    # ---- flipbook frames, two wavelength-matched channels -------------------------------
    channels = {
        "w2": {"label": "4.6 µm", "wise": "allwise_W2.fits", "spx": lambda s: 4.40 <= s["lam"] <= 5.01},
        "w1": {"label": "3.4 µm", "wise": "allwise_W1.fits", "spx": lambda s: 3.00 <= s["lam"] <= 3.80},
    }
    frames = {}
    for ch, spec in channels.items():
        frames[ch] = []
        wf = CACHE / tid / spec["wise"]
        if wf.exists():
            h = fits.open(wf)[0]
            img, _ = reproject_interp((h.data, WCS(h.header).celestial), gw, shape_out=(NPIX, NPIX))
            name = f"{ch}_wise2010.png"; save_png(img, out / name)
            frames[ch].append({"year": 2010.5, "label": "WISE 2010", "mission": "WISE", "png": name,
                               "img": img})
        for i, v in enumerate(visits):
            sel = [s for s in spx if visit_of(s["year"]) == i and spec["spx"](s)]
            if not sel:
                continue
            stack = []
            for s in sel:
                h = fits.open(s["file"])
                im = h["IMAGE"].data.astype(float)
                im[bad_mask(h["FLAGS"], DISPLAY_BAD)] = np.nan
                r, _ = reproject_interp((im, WCS(h["IMAGE"].header).celestial), gw, shape_out=(NPIX, NPIX))
                stack.append(r)
            img = np.nanmedian(np.array(stack), axis=0)
            yr = float(np.mean([s["year"] for s in sel]))
            name = f"{ch}_spherex_v{i + 1}.png"; save_png(img, out / name)
            frames[ch].append({"year": yr, "label": f"SPHEREx {Time(yr, format='jyear').datetime:%b %Y}",
                               "mission": "SPHEREx", "png": name, "img": img, "n_images": len(sel)})

    # ---- difference image between the two SPHEREx visits (same instrument, same band) ----
    for ch in list(frames):
        sp = [f for f in frames[ch] if f["mission"] == "SPHEREx"]
        if len(sp) >= 2:
            d = sp[-1]["img"] - sp[0]["img"]
            lim = np.nanpercentile(np.abs(d), 99.5) or 1
            plt.imsave(out / f"{ch}_diff.png", np.nan_to_num(d), cmap="PiYG", vmin=-lim, vmax=lim, origin="lower")
            frames[ch + "_diff"] = f"{ch}_diff.png"

    # ---- measured positions vs Gaia prediction --------------------------------------------
    track = []
    for ch_name in ("w2", "w1"):
      for f in frames.get(ch_name, []):
        pred = predict(ref, f["year"])
        px, py = gw.world_to_pixel(pred)
        c = centroid(f["img"], float(px), float(py), r=4.0 if f["mission"] == "SPHEREx" else 3.0)
        if c is None:
            continue
        meas = gw.pixel_to_world(*c)
        track.append({"year": f["year"], "mission": f["mission"], "ch": ch_name, "x": c[0], "y": c[1],
                      "pred_x": float(px), "pred_y": float(py),
                      "offset_arcsec": float(meas.separation(pred).arcsec),
                      "ra": float(meas.ra.deg), "dec": float(meas.dec.deg)})
    motion = None
    first = [p for p in track if p["mission"] == "WISE"]
    last = [p for p in track if p["mission"] == "SPHEREx"]
    if first and last:
        a, b = first[0], max(last, key=lambda p: p["year"])
        ca, cb = SkyCoord(a["ra"] * u.deg, a["dec"] * u.deg), SkyCoord(b["ra"] * u.deg, b["dec"] * u.deg)
        dt = b["year"] - a["year"]
        dra = (cb.ra - ca.ra).to(u.arcsec).value * np.cos(np.radians(ca.dec.deg))
        ddec = (cb.dec - ca.dec).to(u.arcsec).value
        expected = np.hypot(ref["pmra"] or 0, ref["pmdec"] or 0) / 1000
        motion = {"from_year": a["year"], "to_year": b["year"], "shift_arcsec": float(np.hypot(dra, ddec)),
                  "measured_arcsec_per_yr": float(np.hypot(dra, ddec) / dt),
                  "measured_pmra": float(dra / dt * 1000), "measured_pmdec": float(ddec / dt * 1000),
                  "expected_arcsec_per_yr": float(expected),
                  "shift_spherex_pixels": float(np.hypot(dra, ddec) / 6.15)}

    # ---- spectrum + brightness change from every SPHEREx image ----------------------------
    pts = []
    for s in spx:
        h = fits.open(s["file"])
        im_, bad_ = h["IMAGE"].data.astype(float), bad_mask(h["FLAGS"])
        flux, nbad = photometry(im_, bad_, s["x"], s["y"])
        if np.isfinite(flux) and np.isfinite(s["lam"]):
            # MJy/sr summed over pixels -> mJy
            pts.append({"lam": round(s["lam"], 4), "flux_mjy": flux * s["sr"] * 1e9, "year": s["year"],
                        "visit": visit_of(s["year"]), "flagged": nbad > 0, "det": s["det"],
                        "wing": wing_flux(im_, bad_, s["x"], s["y"])})
    good = [p for p in pts if not p["flagged"]]
    spectrum = []
    edges = np.arange(0.75, 5.05, 0.05)
    for lo, hi in zip(edges[:-1], edges[1:]):
        v = [p["flux_mjy"] for p in good if lo <= p["lam"] < hi]
        if v:
            spectrum.append({"lam": round((lo + hi) / 2, 3), "flux_mjy": float(np.median(v)), "n": len(v)})

    variability = None
    if len(visits) >= 2:
        # Use clean aperture photometry when most points are clean; for saturated stars fall back
        # to PSF-wing photometry. Compare the first and the last big visit, wavelength bin by bin.
        saturated = len(good) < 0.3 * max(len(pts), 1)
        key, use = ("wing", [p for p in pts if np.isfinite(p["wing"])]) if saturated else ("flux_mjy", good)
        last = max(range(len(visits)), key=lambda i: (len(visits[i]) >= 30, i))
        ratios = []
        for lo, hi in zip(edges[:-1], edges[1:]):
            a = [p[key] for p in use if lo <= p["lam"] < hi and p["visit"] == 0]
            b = [p[key] for p in use if lo <= p["lam"] < hi and p["visit"] == last]
            if a and b and np.median(a) > 0 and np.median(b) > 0:
                ratios.append(np.median(b) / np.median(a))
        if len(ratios) >= 5:
            dmag = -2.5 * np.log10(np.median(ratios))
            scatter = float(np.std(-2.5 * np.log10(ratios)) / np.sqrt(len(ratios)))
            variability = {"delta_mag": float(dmag), "uncertainty_mag": scatter, "n_wavelength_bins": len(ratios),
                           "method": "PSF-wing photometry (star's core is saturated)" if saturated else "aperture photometry",
                           "from": Time(vyear[0], format="jyear").datetime.strftime("%b %Y"),
                           "to": Time(vyear[last], format="jyear").datetime.strftime("%b %Y")}

    # Methane test: flux at the 4.0 um peak vs the 3.3 um methane trough. A normal star is simply
    # fainter at longer wavelengths (ratio ~0.7); a methane-bearing brown dwarf is far brighter at
    # 4.0 um than in the 3.3 um band (ratio well above 2). 4.5 um is avoided: CO/CO2 absorb there.
    def band_med(lo, hi):
        v = [p["flux_mjy"] for p in good if lo <= p["lam"] < hi]
        return float(np.median(v)) if v else None
    f40, f33 = band_med(3.85, 4.20), band_med(3.20, 3.45)
    color = {"f4p0_mjy": f40, "f3p3_mjy": f33,
             "ratio": (f40 / f33) if (f40 and f33 and f33 > 0) else None}

    # ---- Gaia ghosts: where every catalogued star should be in each frame -----------------
    ghosts = {}
    for ch in ("w2", "w1"):
        for f in frames.get(ch, []):
            pos = []
            for st in stars:
                if st["g"] > 17:      # keep the overlay readable: brighter Gaia stars only
                    continue
                c = SkyCoord(st["ra"] * u.deg, st["dec"] * u.deg, pm_ra_cosdec=st["pmra"] * u.mas / u.yr,
                             pm_dec=st["pmdec"] * u.mas / u.yr, obstime=Time(2016.0, format="jyear"))
                p = c.apply_space_motion(new_obstime=Time(f["year"], format="jyear"))
                x, y = gw.world_to_pixel(p)
                if 0 <= x < NPIX and 0 <= y < NPIX:
                    pos.append([round(float(x), 1), round(float(y), 1), round(st["g"], 1)])
            ghosts[f["png"]] = pos

    target_in_gaia = ref.get("source_id") is not None
    result = {
        "id": tid, "name": t["name"], "kind": t["kind"], "story": t["story"],
        "reference": ref, "target_in_gaia": target_in_gaia,
        "grid": {"npix": NPIX, "arcsec_per_pix": GRID_PIX, "centre_ra": mid.ra.deg, "centre_dec": mid.dec.deg},
        "frames": {ch: [{k: v for k, v in f.items() if k != "img"} for f in frames[ch]]
                   for ch in ("w2", "w1") if ch in frames},
        "diff": {ch: frames.get(ch + "_diff") for ch in ("w2", "w1")},
        "ghosts": ghosts, "track": track, "motion": motion,
        "spectrum": spectrum, "spectrum_points": len(pts), "flagged_points": len(pts) - len(good),
        "variability": variability, "ir_color": color, "bands": BANDS,
        "spherex_visits": [{"year": y, "n_images": len(v)} for y, v in zip(vyear, visits)],
    }
    (out / "target.json").write_text(json.dumps(result, indent=1, default=float))
    print(f"   frames: {[ (ch, len(frames.get(ch, []))) for ch in ('w2','w1')]}  spectrum bins: {len(spectrum)} "
          f"(points {len(pts)}, flagged {len(pts) - len(good)})", flush=True)
    if motion:
        print(f"   motion: measured {motion['measured_arcsec_per_yr']:.2f}\"/yr vs expected "
              f"{motion['expected_arcsec_per_yr']:.2f}\"/yr over {motion['to_year'] - motion['from_year']:.1f} yr", flush=True)
    if variability:
        print(f"   brightness change: {variability['delta_mag']:+.3f} ± {variability['uncertainty_mag']:.3f} mag", flush=True)
    print(f"   methane test 4.0/3.3 um: {color['ratio']}", flush=True)
    return result


if __name__ == "__main__":
    ids = list(TARGETS) if sys.argv[1:] in ([], ["all"]) else sys.argv[1:]
    for tid in ids:
        try:
            analyze(tid)
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"!! {tid} failed: {e}", flush=True)
