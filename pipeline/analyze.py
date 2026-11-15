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
  * Six-detector view. SPHEREx has six detectors, each covering one slice of 0.75-5.0 um. Besides one co-add per
    detector and survey visit ("d1".."d6"), the "all" channel stacks the six co-adds of a visit after putting each
    on the same footing: background subtracted and divided by its own robust noise (median and MAD). So no detector
    dominates because its sky is brighter, and an object seen by several detectors gains signal-to-noise. It mixes
    wavelengths, so it is a picture for finding things, never used for the wavelength-matched motion measurement.
  * Every displayed frame carries its observation metadata (mission, detector, wavelength at the target, dates,
    images stacked) and a contamination check from the SPHEREx FLAGS planes at the target, ending in a verdict
    (good / caution / poor) with its reason. Flag names and their meanings are read from each file's own header.
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


# ---- contamination metadata at the target ------------------------------------------------------------------
APERTURE_R = 3.0                      # photometry aperture radius in SPHEREx pixels (photometry(), flags_at())
SATURATION_FLAG = "OVERFLOW"          # header text: "Overflow detected during SUR"; the pixel's charge overflowed
INFO_FLAGS = {"SOURCE", "FULLSAMPLE"}  # informational planes (a known source is here; full sample history kept)
# The SPHEREx detectors and the slice of the spectrum each covers, in um (as labelled on the detector channels).
DETECTOR_BANDS = {1: (0.75, 1.09), 2: (1.10, 1.62), 3: (1.63, 2.41), 4: (2.42, 3.82), 5: (3.83, 4.41), 6: (4.42, 5.00)}
DETECTOR_ARRAY = {1: "SWIR", 2: "SWIR", 3: "SWIR", 4: "MWIR", 5: "MWIR", 6: "MWIR"}   # header: "1-3: SWIR, 4-6: MWIR"
COMBINED = "all"
COMBINED_LABEL = "All 6 detectors combined (0.75–5.0 µm)"
MIN_COMBINED_DETECTORS = 2            # a visit seen by one detector only has nothing to combine
QUALITY_RULES = [
    "One SPHEREx image is poor when the pixel at the target is saturated (OVERFLOW), blank, outside the image or "
    "carries a flag that makes a pixel unusable; caution when the target pixel is fine but another pixel within "
    "3 pixels of the target is flagged or blank (that image is then left out of the spectrum); otherwise good.",
    "A stacked frame is poor when at least half of its images are poor, or the stacked picture is blank at the "
    "target; caution when any image is saturated at the target, at least a quarter are poor, at least half have "
    "flagged or blank pixels within 3 pixels of the target, or an image did not pass the SPHEREx pipeline's own "
    "quality check (L2DQAFLG); otherwise good. A frame of one image takes that image's verdict.",
    "The combined frame is poor when at least half of its detector co-adds are poor; caution when any co-add is "
    "poor, any image is saturated at the target, or at least half of the co-adds need caution; otherwise good.",
    "WISE and NEOWISE frames come without flag planes here, so only blank pixels and a saturated (blanked) core "
    "are checked: poor when the core is saturated or the target pixel is blank, caution when a pixel within 3 "
    "pixels of the target is blank.",
]


def flag_planes(flags_hdu):
    """{name: (bitmask, description)} for every flag plane named in a SPHEREx FLAGS header
    (MSKNnnnn = name, MSKMnnnn = bitmask, MSKDnnnn = the pipeline's own description)."""
    h, out = flags_hdu.header, {}
    for k in h:
        if not k.startswith("MSKN"):
            continue
        m = h.get("MSKM" + k[4:])
        if m is None:
            continue
        out[str(h[k]).strip()] = (int(m), str(h.get("MSKD" + k[4:], "")).strip())
    return out


def _names(value, planes, skip=INFO_FLAGS):
    """Flag names whose bit is set in value, in bit order, informational planes left out."""
    return [n for n, (bit, _) in sorted(planes.items(), key=lambda p: p[1][0]) if value & bit and n not in skip]


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def image_quality(flags_hdu, img, x, y, r=APERTURE_R, dqa=None):
    """Contamination at the target in one SPHEREx image, from its FLAGS plane.

    x, y: the target's pixel position in this image (0-based). Counts use the photometry aperture (r pixels), and
    'bad' means what photometry() leaves out: a flag from BAD_NAMES, or a blank (non-finite) pixel.
    dqa: the pipeline's L2 data-quality outcome (header L2DQAFLG), if known."""
    planes = flag_planes(flags_hdu)
    d = np.asarray(flags_hdu.data).astype(np.int64)
    img = np.asarray(img, float)
    ny, nx = d.shape
    yy, xx = np.indices(d.shape)
    ap = np.hypot(xx - x, yy - y) <= r
    bad_bits = sum(bit for n, (bit, _) in planes.items() if n in BAD_NAMES)
    any_bits = sum(bit for n, (bit, _) in planes.items() if n not in INFO_FLAGS)
    bad = ((d & bad_bits) != 0) | ~np.isfinite(img)
    ix, iy = int(np.floor(x + 0.5)), int(np.floor(y + 0.5))
    inside = bool(0 <= ix < nx and 0 <= iy < ny)
    pix = int(d[iy, ix]) if inside else 0
    sat = bool(inside and SATURATION_FLAG in planes and pix & planes[SATURATION_FLAG][0])
    q = {"flags_aperture": _names(int(np.bitwise_or.reduce(d[ap])) if ap.any() else 0, planes),
         "flags_target_pixel": _names(pix, planes), "saturated": sat, "target_in_image": inside,
         "target_blank": bool(inside and not np.isfinite(img[iy, ix])),
         "aperture_px": int(ap.sum()), "bad_px_aperture": int((bad & ap).sum()),
         "flagged_px_aperture": int((((d & any_bits) != 0) & ap).sum()), "dqa": dqa}
    q["quality"], q["quality_reason"] = image_verdict(q)
    return q


# what image_quality() adds to each row of target.json -> "metadata" (flags_at_target is the older aperture list)
IMAGE_META_KEYS = ("flags_target_pixel", "saturated", "target_blank", "aperture_px", "bad_px_aperture",
                   "flagged_px_aperture", "dqa", "quality", "quality_reason")


def image_verdict(q):
    """(verdict, reason) for one SPHEREx image, from image_quality()'s fields. Rules: QUALITY_RULES[0]."""
    bad_at_pixel = [f for f in q.get("flags_target_pixel", []) if f in BAD_NAMES and f != SATURATION_FLAG]
    if not q.get("target_in_image", True):
        return "poor", "The target falls outside this image."
    if q.get("saturated"):
        return "poor", "The pixel at the target is saturated (OVERFLOW flag)."
    if q.get("target_blank"):
        return "poor", "The pixel at the target is blank (no value)."
    if bad_at_pixel:
        return "poor", f"The pixel at the target is flagged {', '.join(bad_at_pixel)}."
    n, of = q.get("bad_px_aperture", 0), q.get("aperture_px", 0)
    if n:
        return "caution", (f"{n} of {of} pixels within 3 pixels of the target {'is' if n == 1 else 'are'} flagged or blank, "
                           "so this image is left out of the spectrum.")
    return "good", "No flagged or blank pixel within 3 pixels of the target."


def _is(n, one="is", many="are"):
    return one if n == 1 else many


def _why_unusable(poor):
    """' (1 saturated, 2 flagged)': why the poor images are unusable at the target."""
    kinds = [("outside the image", lambda q: not q.get("target_in_image", True)), ("saturated", lambda q: q.get("saturated")),
             ("blank", lambda q: q.get("target_blank")), ("flagged", lambda q: True)]
    counts = {}
    for q in poor:
        k = next(name for name, test in kinds if test(q))
        counts[k] = counts.get(k, 0) + 1
    parts = [f"{counts[k]} {k}" for k, _ in kinds if counts.get(k)]
    return f" ({', '.join(parts)})" if parts else ""


def stack_quality(per_image, blank_at_target=False):
    """Verdict for a frame stacked from several SPHEREx images (QUALITY_RULES[1]), with the counts behind it.

    per_image: image_quality() results of the stacked images. blank_at_target: the stacked picture has no value
    at the target's position."""
    n = len(per_image)
    counts, pix_counts = {}, {}
    for q in per_image:
        for f in q.get("flags_aperture", []):
            counts[f] = counts.get(f, 0) + 1
        for f in q.get("flags_target_pixel", []):
            pix_counts[f] = pix_counts.get(f, 0) + 1
    poor = [q for q in per_image if q.get("quality") == "poor"]
    sat = sum(bool(q.get("saturated")) for q in per_image)
    with_bad = sum(q.get("bad_px_aperture", 0) > 0 for q in per_image)
    dqa_fail = sum(q.get("dqa") not in (None, "Pass") for q in per_image)
    worst = max(per_image, key=lambda q: (q.get("bad_px_aperture", 0), q.get("aperture_px", 0)), default={})
    out = {"flags_checked": True, "flag_counts": counts, "pixel_flag_counts": pix_counts, "n_saturated": sat,
           "aperture_px": worst.get("aperture_px", 0), "bad_px_worst": worst.get("bad_px_aperture", 0),   # the worst image's own counts
           "images_with_bad_px": with_bad, "n_poor": len(poor), "n_dqa_fail": dqa_fail}
    of = f"of {_plural(n, 'image')}"
    unusable = f"{len(poor)} {of} {_is(len(poor))} unusable at the target{_why_unusable(poor)}"
    if n == 0:
        out.update(verdict="poor", reason="No SPHEREx image went into this frame.")
    elif blank_at_target:
        outside = sum(not q.get("target_in_image", True) for q in per_image)
        out.update(verdict="poor", reason=("The target falls outside " + ("this image." if n == 1 else f"all {n} images.")
                                           if outside == n else "The stacked picture is blank at the target."))
    elif n == 1:                               # one image: its own verdict
        v, r = per_image[0].get("quality", "good"), per_image[0].get("quality_reason", "")
        if v == "good" and dqa_fail:
            v, r = "caution", "The image did not pass the SPHEREx pipeline's own quality check (L2DQAFLG)."
        out.update(verdict=v, reason=r)
    elif 2 * len(poor) >= n:
        out.update(verdict="poor", reason=f"{unusable}.")
    elif sat:
        out.update(verdict="caution", reason=f"{sat} {of} {_is(sat)} saturated at the target, so the object is near "
                                             "the brightest this detector can record.")
    elif 4 * len(poor) >= n:
        out.update(verdict="caution", reason=f"{unusable}.")
    elif 2 * with_bad >= n:
        out.update(verdict="caution", reason=f"{with_bad} {of} {_is(with_bad, 'has', 'have')} flagged or blank pixels "
                                             "within 3 pixels of the target.")
    elif dqa_fail:
        out.update(verdict="caution", reason=f"{dqa_fail} {of} did not pass the SPHEREx pipeline's own quality check "
                                             "(L2DQAFLG).")
    elif poor:
        out.update(verdict="good", reason=f"{unusable}: fewer than a quarter, the others are clean at the target.")
    elif with_bad:
        out.update(verdict="good", reason=f"The target pixel is clean in all {_plural(n, 'image')}; {with_bad} "
                                          f"{_is(with_bad, 'has', 'have')} a flagged or blank pixel nearby.")
    else:
        out.update(verdict="good", reason="No flagged or blank pixel within 3 pixels of the target in "
                                          f"{'the image' if n == 1 else f'any of the {n} images'}.")
    return out


def combined_quality(det_quality, per_image, blank_at_target=False):
    """Verdict for the combined frame (QUALITY_RULES[2]) from the verdicts of its detector co-adds
    ({detector: stack_quality()}), with the flag counts of all its images (per_image)."""
    out = stack_quality(per_image, blank_at_target)
    out["detector_verdicts"] = {str(d): q["verdict"] for d, q in sorted(det_quality.items())}
    nd = len(det_quality)
    poor = [d for d, q in sorted(det_quality.items()) if q["verdict"] == "poor"]
    warn = [d for d, q in sorted(det_quality.items()) if q["verdict"] == "caution"]
    names = lambda ds: ", ".join(f"D{d}" for d in ds)
    if blank_at_target:
        verdict, reason = "poor", "The stacked picture is blank at the target."
    elif nd == 0:
        verdict, reason = "poor", "No detector co-add went into this frame."
    elif 2 * len(poor) >= nd:
        verdict, reason = "poor", f"{len(poor)} of {nd} detector co-adds {_is(len(poor))} poor at the target ({names(poor)})."
    elif poor:
        verdict, reason = "caution", (f"Detector co-add {names(poor)} {_is(len(poor))} poor at the target"
                                      + (f" and {names(warn)} {_is(len(warn), 'needs', 'need')} caution" if warn else "")
                                      + "; the other detectors are usable.")
    elif out["n_saturated"]:
        verdict, reason = "caution", (f"{out['n_saturated']} of {_plural(len(per_image), 'image')} "
                                      f"{_is(out['n_saturated'])} saturated at the target.")
    elif 2 * len(warn) >= nd:
        verdict, reason = "caution", f"{len(warn)} of {nd} detector co-adds need caution ({names(warn)})."
    elif warn:
        verdict, reason = "good", f"{len(warn)} of {nd} detector co-adds {_is(len(warn), 'needs', 'need')} caution ({names(warn)}); the rest are good."
    else:
        verdict, reason = "good", f"All {nd} detector co-adds are good at the target."
    out.update(verdict=verdict, reason=reason)
    return out


def wise_quality(img, x, y, saturated_core=False, r=APERTURE_R):
    """Verdict for a WISE or NEOWISE frame (QUALITY_RULES[3]): no flag planes, so blank pixels only.
    img: the archive image; x, y: the target there (0-based pixels)."""
    img = np.asarray(img, float)
    ny, nx = img.shape
    yy, xx = np.indices(img.shape)
    ap = np.hypot(xx - x, yy - y) <= r
    ix, iy = int(np.floor(x + 0.5)), int(np.floor(y + 0.5))
    inside = bool(0 <= ix < nx and 0 <= iy < ny)
    blank = int((~np.isfinite(img) & ap).sum())
    out = {"flags_checked": False, "flag_counts": None, "pixel_flag_counts": None, "n_saturated": int(bool(saturated_core)),
           "aperture_px": int(ap.sum()), "bad_px_worst": blank, "images_with_bad_px": None, "n_poor": None, "n_dqa_fail": None}
    note = " WISE flag images are not used here, so only blank pixels are checked."
    if not inside:
        out.update(verdict="poor", reason="The target falls outside this image.")
    elif saturated_core:
        out.update(verdict="poor", reason="The star's core is saturated: the archive left it blank, so its position "
                                          "comes from the centre of the blank hole and its brightness cannot be measured." + note)
    elif not np.isfinite(img[iy, ix]):
        out.update(verdict="poor", reason="The pixel at the target is blank (no value)." + note)
    elif blank:
        out.update(verdict="caution", reason=f"{blank} of {out['aperture_px']} pixels within 3 pixels of the target "
                                             f"{'is' if blank == 1 else 'are'} blank." + note)
    else:
        out.update(verdict="good", reason="No blank pixel within 3 pixels of the target." + note)
    return out


def robust_scale(img):
    """(background, noise) of an image: median and 1.4826 x median absolute deviation of its finite pixels.
    None when there are too few pixels or no spread to divide by."""
    a = np.asarray(img, float)
    fin = a[np.isfinite(a)]
    if fin.size < 20:
        return None
    bg = float(np.median(fin))
    noise = float(1.4826 * np.median(np.abs(fin - bg)))
    return (bg, noise) if np.isfinite(noise) and noise > 0 else None


def combine_detectors(images, min_detectors=MIN_COMBINED_DETECTORS):
    """Stack per-detector images of one visit into one picture with more signal-to-noise.

    images: {detector: 2D array or None}, all on the same grid. Each image is background-subtracted and divided by
    its robust noise (robust_scale), so every detector counts in units of its own noise and none dominates because
    its sky is brighter or its units larger. The normalised images are summed and divided by sqrt(number of detectors
    with a value at that pixel), so the result is again in noise units: a source seen by several detectors gains.
    Pixels blank in every detector stay blank. Returns (image or None, [(detector, background, noise)] used)."""
    used, z = [], []
    for det in sorted(images):
        a = images[det]
        if a is None:
            continue
        sc = robust_scale(a)
        if sc is None:
            continue
        used.append((int(det), sc[0], sc[1]))
        z.append((np.asarray(a, float) - sc[0]) / sc[1])
    if len(used) < max(1, min_detectors):
        return None, used
    Z = np.array(z)
    n = np.isfinite(Z).sum(axis=0)
    total = np.nansum(Z, axis=0)
    return np.where(n > 0, total / np.sqrt(np.maximum(n, 1)), np.nan), used


def spherex_obs(sel, detectors=None):
    """Observation metadata of a frame stacked from SPHEREx images (load_spherex() entries)."""
    dets = sorted({s["det"] for s in sel}) if detectors is None else list(detectors)
    lams = [s["lam"] for s in sel if np.isfinite(s.get("lam", np.nan))]
    mjds = [s["mjd"] for s in sel]
    one = len(dets) == 1
    return {"mission": "SPHEREx",
            "instrument": (f"SPHEREx detector D{dets[0]} ({DETECTOR_ARRAY.get(dets[0], '?')} array)" if one
                           else f"SPHEREx detectors {', '.join(f'D{d}' for d in dets)}"),
            "detectors": dets,
            "band_um": ([DETECTOR_BANDS[dets[0]][0], DETECTOR_BANDS[dets[0]][1]] if one and dets[0] in DETECTOR_BANDS else
                        [min(DETECTOR_BANDS[d][0] for d in dets), max(DETECTOR_BANDS[d][1] for d in dets)]
                        if dets and all(d in DETECTOR_BANDS for d in dets) else None),
            "lam_um": [round(min(lams), 3), round(max(lams), 3)] if lams else None,
            "lam_note": "wavelength each image recorded at the target's pixel (WCS-WAVE)",
            "start": Time(min(mjds), format="mjd").iso[:16] if mjds else None,
            "end": Time(max(mjds), format="mjd").iso[:16] if mjds else None,
            "time_note": "mid-exposure times of the first and last image, UTC"}


def build_combined(det_frames, min_detectors=MIN_COMBINED_DETECTORS):
    """The combined frame of one survey visit from that visit's per-detector frames {detector: frame}, each with
    'img' (the detector co-add on the display grid) and '_sel' (its SPHEREx images). None if too few detectors."""
    img, used = combine_detectors({d: f.get("img") for d, f in det_frames.items()}, min_detectors)
    if img is None:
        return None
    sel = [s for d, _, _ in used for s in det_frames[d]["_sel"]]
    yr = float(np.mean([s["year"] for s in sel]))
    return {"year": yr, "label": f"SPHEREx {Time(yr, format='jyear').datetime:%b %Y}", "mission": "SPHEREx",
            "png": None, "img": img, "n_images": len(sel), "detectors": [d for d, _, _ in used],
            "normalisation": [{"det": d, "n_images": len(det_frames[d]["_sel"]), "background": float(f"{bg:.4g}"),
                               "noise": float(f"{nz:.4g}")} for d, bg, nz in used],
            "_sel": sel, "_parts": {d: det_frames[d] for d, _, _ in used}}

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


def last_visit(visits):
    """Visit to compare with the first one for a brightness change: the latest big one (30+ images), else the
    latest. Never the first visit itself, which would compare a visit with itself and always read as 'steady'."""
    return max(range(1, len(visits)), key=lambda i: (len(visits[i]) >= 30, i)) if len(visits) >= 2 else None


def east_arcsec(ca, cb, dec_deg):
    """Eastward offset from ca to cb in arcsec on the sky (RA difference x cos dec), the short way across RA 0h."""
    return float((cb.ra - ca.ra).wrap_at(180 * u.deg).to(u.arcsec).value * np.cos(np.radians(dec_deg)))


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
        dqa = hd.get("L2DQAFLG")
        out.append(dict(file=f, mjd=float(mjd), year=yr, det=det, lam=lam, x=float(x), y=float(y),
                        sr=pixel_sr(w, float(x), float(y)), bunit=hd.get("BUNIT", ""),
                        q=image_quality(h["FLAGS"], h["IMAGE"].data, float(x), float(y),
                                        dqa=str(dqa).strip() if dqa is not None else None),
                        planes=flag_planes(h["FLAGS"])))
    return out


def flag_legend(spx):
    """Every flag plane the SPHEREx headers define, with the header's own description, whether it makes a pixel
    unusable (BAD_NAMES) or is hidden in the pictures (DISPLAY_BAD), and in how many images it touches the target."""
    planes = {}
    for s in spx:
        for name, (bit, desc) in s.get("planes", {}).items():
            planes.setdefault(name, (bit, desc))
    n_ap = {n: sum(n in s["q"]["flags_aperture"] for s in spx) for n in planes}
    n_px = {n: sum(n in s["q"]["flags_target_pixel"] for s in spx) for n in planes}
    return [{"name": n, "bit": int(bit).bit_length() - 1, "description": desc, "bad": n in BAD_NAMES,
             "informational": n in INFO_FLAGS, "hidden_in_pictures": n in DISPLAY_BAD,
             "images_aperture": n_ap[n], "images_target_pixel": n_px[n]}
            for n, (bit, desc) in sorted(planes.items(), key=lambda p: p[1][0])]


def flags_at(flags_hdu, x, y, r=3.0):
    """Names of the SPHEREx flag planes set anywhere in the photometry aperture (contamination metadata)."""
    h, d = flags_hdu.header, flags_hdu.data
    yy, xx = np.indices(d.shape)
    v = int(np.bitwise_or.reduce(d[np.hypot(xx - x, yy - y) <= r].astype(np.int64))) if d.size else 0
    return [str(h[k]).strip() for k in h if k.startswith("MSKN") and v & int(h[k.replace("MSKN", "MSKM")])
            and str(h[k]).strip() not in INFO_FLAGS]


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


def blank_core(img, x0, y0, r):
    """The largest blank (NaN) region touching the predicted position: (x, y of its centre, pixels, touches the
    image border), or None. Archives blank pixels that saturated; for very bright stars that hole is the star."""
    bad = ~np.isfinite(np.asarray(img, float))
    if not bad.any():
        return None
    lab, n = ndimage.label(bad)
    yy, xx = np.indices(bad.shape)
    near = np.unique(lab[(np.hypot(xx - x0, yy - y0) <= r) & bad])
    near = near[near > 0]
    if not near.size:
        return None
    k = max(near, key=lambda i: (lab == i).sum())
    m = lab == k
    border = bool(m[0].any() or m[-1].any() or m[:, 0].any() or m[:, -1].any())
    return float(xx[m].mean()), float(yy[m].mean()), int(m.sum()), border


def saturated_core(img, x0, y0, r):
    """Centre of the blank (NaN) saturated core touching the predicted position, or None."""
    b = blank_core(img, x0, y0, r)
    if b is None or b[2] < 3 or b[2] > 400:   # a lone dead pixel or an image edge, not a star
        return None
    return b[0], b[1]


def core_has_pixels(img, x0, y0, r):
    """Is any pixel within r of (x0, y0) not blank? (detection_snr reports 0.0 when none is.)"""
    yy, xx = np.indices(np.shape(img))
    return bool(np.isfinite(np.asarray(img, float)[np.hypot(xx - x0, yy - y0) <= r]).any())


def saturated_beyond_measure(img, x0, y0, r):
    """A blank core too big (over 400 pixels) to take its centre as the position, but clearly a star: away from
    the image border. Such a frame shows the object (saturated), it just gives no position."""
    b = blank_core(img, x0, y0, r)
    return b is not None and b[2] > 400 and not b[3]


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
                       "pmra": east_arcsec(ca, cb, cb.dec.deg) * 1000 / dt,
                       "pmdec": float((cb.dec - ca.dec).to(u.mas).value / dt),
                       "gaia_source_id": gid, "explained_by_gaia": gid is not None})
    return movers


def _iso(s):
    """'2010-05-03T08:45:24.456' -> '2010-05-03 08:45' (minutes, like the per-image dates); None stays None."""
    return str(s).replace("T", " ")[:16] if s else None


def describe_frame(f, ch, gw, ref, wise_lam=None):
    """Add 'obs' (mission, instrument, detectors, wavelength at the target, dates) and 'quality' (contamination at
    the target and a good / caution / poor verdict with its reason) to one displayed frame. Reads the frame's
    internal keys: '_sel' (its SPHEREx images), 'img' or '_img' (the stacked picture), '_native' and '_header'."""
    def blank_at_target(fr):
        img = fr["img"] if fr.get("img") is not None else fr.get("_img")
        if img is None:
            return False
        px, py = gw.world_to_pixel(predict(ref, fr["year"]))
        ix, iy = int(np.floor(float(px) + .5)), int(np.floor(float(py) + .5))
        return bool(0 <= iy < img.shape[0] and 0 <= ix < img.shape[1] and not np.isfinite(img[iy, ix]))
    if f["mission"] == "SPHEREx":
        sel = f.get("_sel") or []
        f["obs"] = spherex_obs(sel, f.get("detectors"))
        if f.get("_parts"):                   # the combined frame: judged by its detector co-adds
            det_q = {d: stack_quality([s["q"] for s in pf.get("_sel") or []], blank_at_target(pf))
                     for d, pf in f["_parts"].items()}
            f["quality"] = combined_quality(det_q, [s["q"] for s in sel], blank_at_target(f))
        else:
            f["quality"] = stack_quality([s["q"] for s in sel], blank_at_target(f))
        return f
    hdr, band = f.get("_header"), f.get("_band", ch.upper())
    get = (lambda k: hdr.get(k)) if hdr is not None else (lambda k: None)
    if f["mission"] == "WISE":
        start, end = _iso(get("DATEOBS1")), _iso(get("DATEOBS2"))
        inst, note = f"WISE {band} band · AllWISE atlas image", "earliest and latest WISE frame of this atlas tile, UTC"
    else:
        mjd = get("MJD-OBS")
        start = end = Time(float(mjd), format="mjd").iso[:16] if mjd is not None else None
        inst, note = f"WISE {band} band · NEOWISE-R exposures stacked by WANDERERS", "mean time of the stacked exposures, UTC"
    f["obs"] = {"mission": f["mission"], "instrument": inst, "detectors": None, "band_um": None,
                "lam_um": [round(wise_lam, 3), round(wise_lam, 3)] if wise_lam else None,
                "lam_note": "effective wavelength of the WISE band (AllWISE header)",
                "start": start, "end": end, "time_note": note}
    if f.get("_native") is not None:
        data, wcs = f["_native"]
        x, y = wcs.world_to_pixel(predict(ref, f["year"]))
        f["quality"] = wise_quality(data, float(x), float(y), bool(f.get("saturated_core")))
    return f


def public(f):
    """A frame as saved in target.json: without the picture and the internal '_' keys."""
    return {k: v for k, v in f.items() if k != "img" and not k.startswith("_")}


def analyze(tid):
    global NPIX
    t = TARGETS[tid]
    NPIX = npix_for(fov_of(t), GRID_PIX)        # field of view chosen at lookup time (default 300"): one grid size for every step
    npix = NPIX                                 # local name used by the field-of-view code from main
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
    # Each SPHEREx detector covers one slice of the spectrum; adding all of a detector's images from a survey
    # together raises the signal-to-noise (suggested in the challenge brief).
    for k, (lo, hi) in DETECTOR_BANDS.items():
        channels[f"d{k}"] = {"label": f"Detector {k} · {lo}–{hi} µm co-add", "wise": None, "slices": False,
                             "spx": (lambda kk: (lambda s: s["det"] == kk))(k)}
    frames = {}      # one frame per epoch (WISE, each SPHEREx survey): used for measurements
    flip = {}        # what the flipbook plays: WISE, then short time slices inside each survey
    # Keys starting with "_" hold what the metadata step needs (the stacked images, the archive image); never saved.
    for ch, spec in channels.items():
        frames[ch], flip[ch] = [], []
        wf = CACHE / tid / spec["wise"] if spec["wise"] else None
        if wf is not None and wf.exists():
            h = fits.open(wf)[0]
            img, _ = reproject_interp((h.data, WCS(h.header).celestial), gw, shape_out=(npix, npix))
            name = f"{ch}_wise2010.png"; save_png(img, out / name)
            fr = {"year": 2010.5, "label": "WISE 2010", "mission": "WISE", "png": name, "img": img,
                  "_native": (h.data, WCS(h.header).celestial), "_header": h.header, "_band": ch.upper()}
            frames[ch].append(fr); flip[ch].append(fr)
        # NEOWISE: one stacked image per sky visit, Dec 2013 - 2024, same band (pipeline/neowise.py)
        band = {"w2": "w2", "w1": "w1"}.get(ch)
        for nf in sorted((CACHE / tid / "neowise").glob(f"{band}_*.fits")) if band else []:
            h = fits.open(nf)[0]
            img, _ = reproject_interp((h.data, WCS(h.header).celestial), gw, shape_out=(npix, npix))
            if not np.isfinite(img).any():
                continue
            yr = float(Time(h.header["MJD-OBS"], format="mjd").jyear)
            name = f"{ch}_neowise_{nf.stem.split('_')[1]}.png"; save_png(img, out / name)
            fr = {"year": yr, "label": f"NEOWISE {Time(yr, format='jyear').datetime:%b %Y}", "mission": "NEOWISE",
                  "png": name, "img": img, "n_images": int(h.header.get("NFRAMES", 0)),
                  "_native": (h.data, WCS(h.header).celestial), "_header": h.header, "_band": ch.upper()}
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
                  "mission": "SPHEREx", "png": name, "img": img, "n_images": len(sel), "_sel": sel, "_visit": i}
            frames[ch].append(vf)
            # Time slices: images taken within ~1.5 days of each other become one flipbook frame.
            groups, g = [], [0]
            for k in range(1, len(sel)):
                (groups.append(g), g := [k]) if (sel[k]["year"] - sel[k - 1]["year"]) * 365.25 > 1.5 else g.append(k)
            groups.append(g)
            if len(groups) < 2 or not spec.get("slices", True):
                flip[ch].append(vf); continue
            for j, gi in enumerate(groups):
                sub = np.nanmedian(np.array([stack[k] for k in gi]), axis=0)
                sy = float(np.mean([sel[k]["year"] for k in gi]))
                sname = f"{ch}_spherex_v{i + 1}_{j + 1}.png"; save_png(sub, out / sname)
                flip[ch].append({"year": sy, "label": f"SPHEREx {Time(sy, format='jyear').datetime:%d %b %Y}",
                                 "mission": "SPHEREx", "png": sname, "img": None, "n_images": len(gi),
                                 "survey": i + 1, "_sel": [sel[k] for k in gi], "_img": sub})

    # ---- all six detectors of a visit combined (noise-normalised stack, see combine_detectors) ---------------
    frames[COMBINED], flip[COMBINED] = [], []
    for i in range(len(visits)):
        per_det = {k: f for k in DETECTOR_BANDS for f in frames.get(f"d{k}", []) if f.get("_visit") == i}
        cf = build_combined(per_det)
        if cf is None:
            continue
        cf["png"] = f"{COMBINED}_spherex_v{i + 1}.png"; save_png(cf["img"], out / cf["png"])
        cf["_visit"] = i
        px, py = gw.world_to_pixel(predict(ref, cf["year"]))
        snr = detection_snr(cf["img"], float(px), float(py), 4.0)   # same rule as the 3.4 and 4.6 µm SPHEREx frames
        cf["detected"], cf["snr"] = snr >= 5, round(snr, 1)
        frames[COMBINED].append(cf); flip[COMBINED].append(cf)
    channels[COMBINED] = {"label": COMBINED_LABEL}

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
        wise = f["mission"] in ("WISE", "NEOWISE")
        hole = saturated_core(f["img"], float(px), float(py), rad + 2) if wise else None
        if hole is not None:                # very bright star: the archive blanks its saturated core,
            c, f["detected"], f["saturated_core"] = hole, True, True   # so the hole's centre is its position
        elif wise and saturated_beyond_measure(f["img"], float(px), float(py), rad + 2):
            f["detected"], f["saturated_core"] = True, True   # seen (saturated); the hole is too big for a position
        if f.get("saturated_core") and not core_has_pixels(f["img"], float(px), float(py), rad):
            f["snr"] = None                 # no unsaturated pixel at the target: a signal-to-noise cannot be measured
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
        dra = east_arcsec(ca, cb, ca.dec.deg)
        ddec = (cb.dec - ca.dec).to(u.arcsec).value
        expected = np.hypot(ref["pmra"] or 0, ref["pmdec"] or 0) / 1000
        motion = {"from_year": a["year"], "to_year": b["year"], "shift_arcsec": float(np.hypot(dra, ddec)),
                  "measured_arcsec_per_yr": float(np.hypot(dra, ddec) / dt),
                  "measured_pmra": float(dra / dt * 1000), "measured_pmdec": float(ddec / dt * 1000),
                  "expected_arcsec_per_yr": float(expected),
                  "shift_spherex_pixels": float(np.hypot(dra, ddec) / 6.15)}

    # ---- spectrum + brightness change from every SPHEREx image ----------------------------
    pts, images_meta = [], []
    for s in spx:
        h = fits.open(s["file"])
        im_, bad_ = h["IMAGE"].data.astype(float), bad_mask(h["FLAGS"])
        flux, nbad = photometry(im_, bad_, s["x"], s["y"])
        images_meta.append({"image": s["file"].stem, "date": Time(s["mjd"], format="mjd").iso[:16], "detector": s["det"],
                            "lam_um": round(s["lam"], 3) if np.isfinite(s["lam"]) else None,
                            "flags_at_target": flags_at(h["FLAGS"], s["x"], s["y"]), "used_in_spectrum": nbad == 0,
                            **{k: s["q"][k] for k in IMAGE_META_KEYS}})
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
        last = last_visit(visits)
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

    # ---- observation metadata and contamination check for every displayed frame ----------
    wise_lam = {}                  # effective wavelength of each WISE band, from the AllWISE header (NEOWISE: same band)
    for ch in ("w1", "w2"):
        f0 = next((f for f in frames.get(ch, []) if f["mission"] == "WISE"), None)
        if f0 is not None and f0["_header"].get("WAVELEN") is not None:
            wise_lam[ch] = float(f0["_header"]["WAVELEN"])
    for ch in flip:
        seen = {}
        for f in flip[ch] + frames.get(ch, []):
            seen[id(f)] = f
        for f in seen.values():
            describe_frame(f, ch, gw, ref, wise_lam.get(ch))

    # ---- Gaia ghosts: where every catalogued star should be in each frame -----------------
    ghosts = {}
    for ch in flip:
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
        "grid": {"npix": NPIX, "arcsec_per_pix": GRID_PIX, "centre_ra": mid.ra.deg, "centre_dec": mid.dec.deg},
        "frames": {ch: [public(f) for f in flip[ch]] for ch in flip if flip[ch]},
        "channels": {ch: channels[ch]["label"] for ch in flip if flip[ch]},
        "stacks": {ch: [public(f) for f in frames[ch]] for ch in ("w2", "w1") if ch in frames},
        "diff": {ch: frames.get(ch + "_diff") for ch in flip},
        "fov_arcsec": NPIX * GRID_PIX,
        "metadata": images_meta,
        "flag_legend": flag_legend(spx), "quality_rules": QUALITY_RULES,
        "detector_bands": {str(k): list(v) for k, v in DETECTOR_BANDS.items()},
        "combined": {"channel": COMBINED, "label": COMBINED_LABEL, "min_detectors": MIN_COMBINED_DETECTORS,
                     "method": "Each detector's co-add of a visit is background-subtracted and divided by its own robust "
                               "noise (median and 1.4826 x MAD); the co-adds are then summed and divided by the square root "
                               "of their number, so the picture is in units of the noise and no detector dominates. It "
                               "mixes wavelengths, so motion is still measured at 3.4 and 4.6 µm only."},
        "ghosts": ghosts, "track": track, "motion": motion, "movers_experimental": movers,
        "spectrum": spectrum, "spectrum_points": len(pts), "flagged_points": len(pts) - len(good),
        "variability": variability, "ir_color": color, "bands": BANDS,
        "spherex_visits": [{"year": y, "n_images": len(v)} for y, v in zip(vyear, visits)],
    }
    (out / "target.json").write_text(json.dumps(result, indent=1, default=float))
    print(f"   flipbook frames: {[(ch, len(flip.get(ch, []))) for ch in ('w2', 'w1', COMBINED)]}  spectrum bins: {len(spectrum)} "
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
