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
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).parent))
from targets import TARGETS
from fetch import predict, CACHE, ROOT, FIELD_ARCSEC
from fov import fov_of, npix_for

warnings.simplefilter("ignore")
from astropy import log as _astropy_log
_astropy_log.setLevel("WARNING")   # the spectral WCS triggers an expected SIP notice; SIP is turned off right after
OUT = ROOT / "app" / "data"
RECENTRE_ON_MOVERS = False         # experimental mover search; see find_movers()
GRID_PIX = 2.0                      # arcsec per display pixel
NPIX = int(FIELD_ARCSEC / GRID_PIX)         # default grid; a target with its own field of view uses npix_for()


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


def grid_wcs(centre, npix=NPIX):
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [centre.ra.deg, centre.dec.deg]
    w.wcs.crpix = [npix / 2 + 0.5, npix / 2 + 0.5]
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


def detection_snr(img, x0, y0, r=3.5):
    """Peak above the local background, in units of the image's robust noise."""
    yy, xx = np.indices(img.shape)
    d = np.hypot(xx - x0, yy - y0)
    ring = img[(d > 3 * r) & (d < 6 * r) & np.isfinite(img)]
    core = img[(d <= r) & np.isfinite(img)]
    if ring.size < 20 or core.size == 0:
        return 0.0
    noise = 1.4826 * np.median(np.abs(ring - np.median(ring))) or 1e-9
    return float((core.max() - np.median(ring)) / noise)


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


def find_sources(img, nsig=4.5):
    """Peaks above nsig x robust noise on the display grid. Returns [(x, y, peak/noise)]."""
    a = np.array(img, float)
    fin = a[np.isfinite(a)]
    if fin.size < 100:
        return []
    bg = np.median(fin); noise = 1.4826 * np.median(np.abs(fin - bg)) or 1e-9
    z = np.nan_to_num((ndimage.uniform_filter(np.nan_to_num(a, nan=bg), 3) - bg) / noise)
    peaks = (z == ndimage.maximum_filter(z, size=5)) & (z > nsig)
    out = []
    for y, x in zip(*np.nonzero(peaks)):
        c = centroid(a, float(x), float(y), r=2.5)
        if c:
            out.append((c[0], c[1], float(z[y, x])))
    return out


def find_movers(img_old, img_new, y_old, y_new, gw, stars, npix, middles=(), paths=()):
    """Sources present in one epoch but not the other, paired into movers.

    Static sources sit at the same place in both images and are ignored. A source that is only in
    the old image, paired with one that is only in the new image a plausible distance away, is a
    mover. Each mover is then checked against Gaia DR3: if a Gaia star's own motion carries it from
    the old to the new position, Gaia explains it; otherwise it is unexplained (a candidate).

    paths: known (x0, y0, x1, y1) paths on the grid, e.g. the target's reference motion. These and
    the Gaia paths are tried first, matched by position only: brightness ratios between WISE and
    SPHEREx peaks are unreliable for saturated stars, and a mover can sit on a background star in
    one epoch, so the free pairing below would lose it."""
    A, B = find_sources(img_old), find_sources(img_new)
    if not A or not B:
        return []
    dt = y_new - y_old
    # "Same static source" = close in position AND similar in brightness (a faint background
    # source should not hide a bright mover that happens to land next to it).
    near = lambda p, L, r: any(np.hypot(p[0] - q[0], p[1] - q[1]) < r and abs(np.log(p[2] / q[2])) < np.log(4) for q in L)
    a_only = [p for p in A if not near(p, B, 4) and np.isfinite(img_new[int(round(p[1])) % npix, int(round(p[0])) % npix])]
    b_only = [p for p in B if not near(p, A, 4) and np.isfinite(img_old[int(round(p[1])) % npix, int(round(p[0])) % npix])]
    a_only = [p for p in a_only if p[2] >= 6]; b_only = [p for p in b_only if p[2] >= 6]
    # Gaia positions at both epochs, for stars that move enough to matter
    gaia_paths = []
    for st in stars:
        if np.hypot(st["pmra"], st["pmdec"]) < 50:
            continue
        c = SkyCoord(st["ra"] * u.deg, st["dec"] * u.deg, pm_ra_cosdec=st["pmra"] * u.mas / u.yr,
                     pm_dec=st["pmdec"] * u.mas / u.yr, obstime=Time(2016.0, format="jyear"))
        p0 = gw.world_to_pixel(c.apply_space_motion(new_obstime=Time(y_old, format="jyear")))
        p1 = gw.world_to_pixel(c.apply_space_motion(new_obstime=Time(y_new, format="jyear")))
        gaia_paths.append((st["source_id"], float(p0[0]), float(p0[1]), float(p1[0]), float(p1[1])))
    def linked(a, b):
        # Linking test used in asteroid searches: a real mover must also be at the interpolated
        # position in every intermediate epoch we have. Chance pairings fail this.
        for img_mid, y_mid in middles:
            f = (y_mid - y_old) / (y_new - y_old)
            px, py = a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])
            if not (0 <= px < npix and 0 <= py < npix) or not np.isfinite(img_mid[int(py), int(px)]):
                continue
            if detection_snr(img_mid, px, py, 2.5) < 4:
                return False
        return True

    in_range = lambda a, b: 4 <= np.hypot(b[0] - a[0], b[1] - a[1]) <= 95   # 8" to 190": 0.5 to ~12 arcsec/yr over 16 years
    chosen = []                                  # (a, b) source pairs, in the order found
    # 1. Known paths first (target, then Gaia), by position alone. The ends may come from all
    #    detections, but at least one end must be absent from the other epoch, so a static star
    #    under both predicted spots cannot pass as the mover.
    a_all, b_all = [p for p in A if p[2] >= 6], [p for p in B if p[2] >= 6]
    for x0, y0, x1, y1 in list(paths) + [g[1:] for g in gaia_paths]:
        a = min((p for p in a_all if not any(p is q for q, _ in chosen)), key=lambda p: np.hypot(p[0] - x0, p[1] - y0), default=None)
        b = min((p for p in b_all if not any(p is q for _, q in chosen)), key=lambda p: np.hypot(p[0] - x1, p[1] - y1), default=None)
        if (a and b and np.hypot(a[0] - x0, a[1] - y0) < 4 and np.hypot(b[0] - x1, b[1] - y1) < 4 and in_range(a, b)
                and (a in a_only or b in b_only) and linked(a, b)):
            chosen.append((a, b))
    # 2. Free pairs among the leftovers, most similar brightness first.
    pairs = []
    for a in a_only:
        for b in b_only:
            if in_range(a, b):
                pairs.append((abs(np.log(b[2] / a[2])), a, b))
    pairs.sort(key=lambda p: p[0])
    for score, a, b in pairs:
        if score > np.log(4) or any(a is p or b is q for p, q in chosen) or not linked(a, b):
            continue
        chosen.append((a, b))
    movers = []
    for a, b in chosen:
        ca, cb = gw.pixel_to_world(a[0], a[1]), gw.pixel_to_world(b[0], b[1])
        gid = next((g for g, x0, y0, x1, y1 in gaia_paths
                    if np.hypot(x0 - a[0], y0 - a[1]) < 4 and np.hypot(x1 - b[0], y1 - b[1]) < 4), None)
        movers.append({"x0": a[0], "y0": a[1], "x1": b[0], "y1": b[1], "snr": round(min(a[2], b[2]), 1),
                       "arcsec_per_yr": float(ca.separation(cb).arcsec / dt),
                       "ra": float(cb.ra.deg), "dec": float(cb.dec.deg), "year": y_new,
                       "pmra": float((cb.ra - ca.ra).to(u.mas).value * np.cos(np.radians(cb.dec.deg)) / dt),
                       "pmdec": float((cb.dec - ca.dec).to(u.mas).value / dt),
                       "gaia_source_id": gid, "explained_by_gaia": gid is not None})
    return movers


def analyze(tid):
    t = TARGETS[tid]
    npix = npix_for(fov_of(t), GRID_PIX)        # pixels per side of this target's display grid
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
    gw = grid_wcs(mid, npix)

    # ---- flipbook frames, two wavelength-matched channels -------------------------------
    channels = {
        "w2": {"label": "4.6 µm", "wise": "allwise_W2.fits", "spx": lambda s: 4.40 <= s["lam"] <= 5.01},
        "w1": {"label": "3.4 µm", "wise": "allwise_W1.fits", "spx": lambda s: 3.00 <= s["lam"] <= 3.80},
    }
    frames = {}      # one frame per epoch (WISE, each SPHEREx survey): used for measurements
    flip = {}        # what the flipbook plays: WISE, then short time slices inside each survey
    for ch, spec in channels.items():
        frames[ch], flip[ch] = [], []
        wf = CACHE / tid / spec["wise"]
        if wf.exists():
            h = fits.open(wf)[0]
            img, _ = reproject_interp((h.data, WCS(h.header).celestial), gw, shape_out=(npix, npix))
            name = f"{ch}_wise2010.png"; save_png(img, out / name)
            fr = {"year": 2010.5, "label": "WISE 2010", "mission": "WISE", "png": name, "img": img}
            frames[ch].append(fr); flip[ch].append(fr)
        for i, v in enumerate(visits):
            sel = sorted([s for s in spx if visit_of(s["year"]) == i and spec["spx"](s)], key=lambda s: s["year"])
            if not sel:
                continue
            stack = []
            for s in sel:
                h = fits.open(s["file"])
                im = h["IMAGE"].data.astype(float)
                im[bad_mask(h["FLAGS"], DISPLAY_BAD)] = np.nan
                r, _ = reproject_interp((im, WCS(h["IMAGE"].header).celestial), gw, shape_out=(npix, npix))
                stack.append(r)
            img = np.nanmedian(np.array(stack), axis=0)
            yr = float(np.mean([s["year"] for s in sel]))
            name = f"{ch}_spherex_v{i + 1}.png"; save_png(img, out / name)
            vf = {"year": yr, "label": f"SPHEREx {Time(yr, format='jyear').datetime:%b %Y}",
                  "mission": "SPHEREx", "png": name, "img": img, "n_images": len(sel)}
            frames[ch].append(vf)
            # Time slices: images taken within ~1.5 days of each other become one flipbook frame.
            groups, g = [], [0]
            for k in range(1, len(sel)):
                (groups.append(g), g := [k]) if (sel[k]["year"] - sel[k - 1]["year"]) * 365.25 > 1.5 else g.append(k)
            groups.append(g)
            if len(groups) < 2:
                flip[ch].append(vf); continue
            for j, gi in enumerate(groups):
                sub = np.nanmedian(np.array([stack[k] for k in gi]), axis=0)
                sy = float(np.mean([sel[k]["year"] for k in gi]))
                sname = f"{ch}_spherex_v{i + 1}_{j + 1}.png"; save_png(sub, out / sname)
                flip[ch].append({"year": sy, "label": f"SPHEREx {Time(sy, format='jyear').datetime:%d %b %Y}",
                                 "mission": "SPHEREx", "png": sname, "img": None, "n_images": len(gi),
                                 "survey": i + 1})

    # ---- difference image between the two SPHEREx visits (same instrument, same band) ----
    for ch in list(frames):
        sp = [f for f in frames[ch] if f["mission"] == "SPHEREx"]
        if len(sp) >= 2:
            d = sp[-1]["img"] - sp[0]["img"]
            lim = np.nanpercentile(np.abs(d), 99.5) or 1
            plt.imsave(out / f"{ch}_diff.png", np.nan_to_num(d), cmap="PiYG", vmin=-lim, vmax=lim, origin="lower")
            frames[ch + "_diff"] = f"{ch}_diff.png"

    # ---- automatic mover search: WISE 2010 vs the fullest SPHEREx survey, same 4.6 um channel ----
    movers = []
    w2 = frames.get("w2", [])
    old = next((f for f in w2 if f["mission"] == "WISE"), None)
    news = [f for f in w2 if f["mission"] == "SPHEREx"]
    if old is not None and news:
        new = max(news, key=lambda f: (f.get("n_images", 0), f["year"]))
        mids = [(f["img"], f["year"]) for f in news if f is not new and f.get("n_images", 0) >= 3]
        p0, p1 = gw.world_to_pixel(predict(ref, old["year"])), gw.world_to_pixel(predict(ref, new["year"]))
        target_path = (float(p0[0]), float(p0[1]), float(p1[0]), float(p1[1]))
        movers = find_movers(old["img"], new["img"], old["year"], new["year"], gw, stars, npix, mids, [target_path])
    # For a typed-in position, an unexplained mover whose path passes within 10" of the spot is
    # almost certainly what the user meant (fast, cold objects are often missing from Gaia).
    # Experimental: chance pairings still slip through on noisy fields, so re-centring on an
    # unexplained mover is switched off until the linking test is stricter.
    if RECENTRE_ON_MOVERS and "position" in t:
        typed = gw.world_to_pixel(SkyCoord(t["position"]["ra"] * u.deg, t["position"]["dec"] * u.deg))
        tx, ty = float(typed[0]), float(typed[1])
        def path_dist(m):
            vx, vy = m["x1"] - m["x0"], m["y1"] - m["y0"]
            k = max(0.0, min(1.0, ((tx - m["x0"]) * vx + (ty - m["y0"]) * vy) / (vx * vx + vy * vy or 1)))
            return np.hypot(m["x0"] + k * vx - tx, m["y0"] + k * vy - ty) * GRID_PIX
        close = sorted([m for m in movers if not m["explained_by_gaia"] and path_dist(m) < 10], key=path_dist)
        if close:
            m = close[0]
            m["is_target"] = True
            ref = {"source": "measured by WANDERERS (WISE 2010 → SPHEREx), not in Gaia DR3", "catalogued": False,
                   "epoch": m["year"], "ra": m["ra"], "dec": m["dec"], "pmra": m["pmra"], "pmdec": m["pmdec"],
                   "parallax": None, "source_id": None, "phot_g_mean_mag": None, "from_movers": True}
            spx = load_spherex(tid, ref)
            print(f"   typed position matches an unexplained mover: {m['arcsec_per_yr']:.2f} arcsec/yr, re-centred on it", flush=True)
    print(f"   movers found: {len(movers)} ({sum(not m['explained_by_gaia'] for m in movers)} not explained by Gaia)", flush=True)

    # ---- measured positions vs Gaia prediction --------------------------------------------
    track = []
    for ch_name in ("w2", "w1"):
      for f in frames.get(ch_name, []):
        pred = predict(ref, f["year"])
        px, py = gw.world_to_pixel(pred)
        rad = 4.0 if f["mission"] == "SPHEREx" else 3.0
        snr = detection_snr(f["img"], float(px), float(py), rad)
        f["detected"] = snr >= 5            # only measure a position where the object is clearly there
        f["snr"] = round(snr, 1)
        c = centroid(f["img"], float(px), float(py), r=rad) if f["detected"] else None
        if c is None:
            continue
        meas = gw.pixel_to_world(*c)
        track.append({"year": f["year"], "mission": f["mission"], "ch": ch_name, "x": c[0], "y": c[1],
                      "pred_x": float(px), "pred_y": float(py),
                      "offset_arcsec": float(meas.separation(pred).arcsec),
                      "ra": float(meas.ra.deg), "dec": float(meas.dec.deg)})
    for ch_name in ("w2", "w1"):
        surveys = [f for f in frames.get(ch_name, []) if f["mission"] == "SPHEREx"]
        for f in flip.get(ch_name, []):
            if f.get("survey") and f["survey"] - 1 < len(surveys) + 5:
                st = next((x for x in surveys if x["png"].endswith(f"_v{f['survey']}.png")), None)
                if st is not None:
                    f["detected"] = st.get("detected")
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

    # Methane test: flux in the 4-4.75 um window vs the 3.3 um methane trough. A normal star is
    # simply fainter at longer wavelengths (ratio below 1); a methane-bearing brown dwarf is far
    # brighter in the 4 um window than in the 3.3 um band (ratio well above 2).
    def band_stats(lo, hi):
        v = np.array([p["flux_mjy"] for p in good if lo <= p["lam"] < hi])
        if v.size < 2:
            return None, None
        err = 1.2533 * np.std(v) / np.sqrt(v.size)      # standard error of a median
        return float(np.median(v)), float(err)
    # 3.85-4.75 um is the window where brown dwarfs shine between the CH4 (3.3) and CO (4.6+) bands.
    f40, e40 = band_stats(3.85, 4.75)
    f33, e33 = band_stats(3.20, 3.45)
    color = {"f4p0_mjy": f40, "f3p3_mjy": f33, "f3p3_err": e33, "ratio": None, "lower_limit": False}
    if f40 and f33 is not None and f40 > 3 * (e40 or 0):
        if f33 > 3 * e33:
            color["ratio"] = f40 / f33
        else:
            # 3.3 um not detected: only a lower limit on the ratio is honest.
            color["ratio"] = f40 / max(3 * e33, 1e-6)
            color["lower_limit"] = True

    # ---- Gaia ghosts: where every catalogued star should be in each frame -----------------
    ghosts = {}
    for ch in ("w2", "w1"):
        for f in flip.get(ch, []):
            pos = []
            for st in stars:
                if st["g"] > 17:      # keep the overlay readable: brighter Gaia stars only
                    continue
                c = SkyCoord(st["ra"] * u.deg, st["dec"] * u.deg, pm_ra_cosdec=st["pmra"] * u.mas / u.yr,
                             pm_dec=st["pmdec"] * u.mas / u.yr, obstime=Time(2016.0, format="jyear"))
                p = c.apply_space_motion(new_obstime=Time(f["year"], format="jyear"))
                x, y = gw.world_to_pixel(p)
                if 0 <= x < npix and 0 <= y < npix:
                    pos.append([round(float(x), 1), round(float(y), 1), round(st["g"], 1)])
            ghosts[f["png"]] = pos

    target_in_gaia = ref.get("source_id") is not None and not ref.get("from_movers")
    result = {
        "id": tid, "name": t["name"], "kind": t["kind"], "story": t["story"],
        "reference": ref, "target_in_gaia": target_in_gaia,
        "grid": {"npix": npix, "arcsec_per_pix": GRID_PIX, "centre_ra": mid.ra.deg, "centre_dec": mid.dec.deg},
        "frames": {ch: [{k: v for k, v in f.items() if k != "img"} for f in flip[ch]]
                   for ch in ("w2", "w1") if ch in flip},
        "stacks": {ch: [{k: v for k, v in f.items() if k != "img"} for f in frames[ch]]
                   for ch in ("w2", "w1") if ch in frames},
        "diff": {ch: frames.get(ch + "_diff") for ch in ("w2", "w1")},
        "ghosts": ghosts, "track": track, "motion": motion, "movers_experimental": movers,
        "spectrum": spectrum, "spectrum_points": len(pts), "flagged_points": len(pts) - len(good),
        "variability": variability, "ir_color": color, "bands": BANDS,
        "spherex_visits": [{"year": y, "n_images": len(v)} for y, v in zip(vyear, visits)],
    }
    (out / "target.json").write_text(json.dumps(result, indent=1, default=float))
    print(f"   flipbook frames: {[ (ch, len(flip.get(ch, []))) for ch in ("w2","w1")]}  spectrum bins: {len(spectrum)} "
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
