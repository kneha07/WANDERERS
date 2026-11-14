"""SPHEREx blink pipeline: resolve a target, find images, align cutouts, make PNG frames.

resolve -> IRSA SIA (spherex_dr1 + spherex_qr3) -> group by survey epoch -> choose images
-> fsspec section reads from S3 -> SIP WCS -> north-up TAN grid -> stack, difference -> PNG -> disk cache
"""
import base64
import csv
import hashlib
import io
import json
import logging
import os
import re
import tempfile
import time
import warnings
import xml.etree.ElementTree as ET
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from itertools import groupby
from pathlib import Path
from urllib.parse import quote

import numpy as np
import requests
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.io.votable import parse as parse_votable
from astropy.time import Time
from astropy.wcs import WCS
from fastapi import HTTPException
from PIL import Image
from scipy.ndimage import binary_dilation, label, map_coordinates
from scipy.optimize import curve_fit

PIXEL_ARCSEC = 6.15
CENTER_MJD = 61041.0  # epoch J2026.0: cutouts are centered on the target's position at this date
J2016_MJD = 57388.5  # Gaia DR3 reference epoch
SESAME_URL = "https://cds.unistra.fr/cgi-bin/nph-sesame/-oxp/SNV?"
SIA_URL = "https://irsa.ipac.caltech.edu/SIA"
GAIA_TAP = "https://gea.esac.esa.int/tap-server/tap/sync"
S3_URL = "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/"
FSSPEC = {"block_size": 256 * 1024, "cache_type": "blockcache"}
# FLAGS bits that mark bad pixels (cosmic rays, hot/dead pixels, persistence). These show up as false blinkers.
BAD_FLAGS = 1 | 4 | 64 | 512 | 1024 | 2048 | 131072  # TRANSIENT SUR_ERROR NONFUNC MISSING_DATA HOT COLD PERSIST
OVERFLOW, BLOOM = 2, 67108864  # saturated pixel; pixel inside the bloom of a bright star
CACHE_DIR = Path(__file__).parent / "cache"
CACHE_VERSION = 3  # bump when the response gains fields, so old cache files are not served
# Centroid error floor, px (resampling, WCS, undersampled PSF): (clean core, core with no data). Measured in
# 2026-11: Gaia stars in the Kapteyn's Star and RW Aur fields sit a median 0.1 px from their fits; per-detector
# fits of saturated cores (Barnard's, Kapteyn's Star) scatter 0.1 to 0.35 px around the proper-motion track.
CENTROID_FLOOR_PX = 0.1, 0.3
NUMBER = r"([+-]?(?:\d+\.?\d*|\.\d+))"
DECIMAL = re.compile(rf"\s*{NUMBER}\s*[,\s]\s*{NUMBER}\s*")
SEXAGESIMAL = re.compile(r"\s*[+-]?\d[\d\s:hmsd°'\".,+-]*")
log = logging.getLogger(__name__)
# NaN means "no data" (off the detector, bad pixel); all-NaN pixels stay NaN without a warning.
warnings.filterwarnings("ignore", r"All-NaN slice|Mean of empty slice", RuntimeWarning)


def parse_coords(q):
    """RA/Dec text -> SkyCoord (ICRS). None if q looks like a name. ValueError for bad numbers."""
    hint = f"Could not read '{q.strip()}' as RA/Dec. Use for example 269.45 4.69 or 17h57m48.5s +04d41m36s."
    if m := DECIMAL.fullmatch(q):
        ra, dec = float(m[1]), float(m[2])
        if not (0 <= ra <= 360 and -90 <= dec <= 90):
            raise ValueError(f"{hint} RA must be 0 to 360 and Dec -90 to +90 degrees.")
        return SkyCoord(ra, dec, unit=u.deg)
    if SEXAGESIMAL.fullmatch(q):
        try:
            return SkyCoord(q, unit=(u.hourangle, u.deg))
        except ValueError:
            raise ValueError(hint) from None
    return None


def group_epochs(mjds):
    """Group observation times (MJD) into survey epochs. Returns lists of indices, in time order."""
    groups = []
    for i in sorted(range(len(mjds)), key=mjds.__getitem__):
        if groups and mjds[i] - mjds[groups[-1][-1]] <= 20:
            groups[-1].append(i)
        else:
            groups.append([i])
    epochs = []
    for g in groups:
        t0 = mjds[g[0]]
        if mjds[g[-1]] - t0 > 45:  # long pass (deep field): cut into consecutive 30-day bins
            epochs += [list(b) for _, b in groupby(g, key=lambda i: (mjds[i] - t0) // 30)]
        else:
            epochs.append(g)
    if len(epochs) > 12:  # keep 12, evenly spaced; first and last stay for the longest baseline
        epochs = [epochs[k] for k in np.linspace(0, len(epochs) - 1, 12).round().astype(int)]
    return epochs


def choose_images(images, n):
    """Pick up to n images, in time order: detectors take turns, and each detector's picks spread in time."""
    by_det = defaultdict(list)
    for img in sorted(images, key=lambda r: r["mjd"]):
        by_det[img["detector"]].append(img)
    take = dict.fromkeys(by_det, 0)
    left = min(n, len(images))
    while left:
        for d in sorted(by_det):
            if left and take[d] < len(by_det[d]):
                take[d] += 1
                left -= 1
    chosen = []
    for d, imgs in by_det.items():
        chosen += [imgs[i] for i in np.linspace(0, len(imgs) - 1, take[d]).round().astype(int)]
    return sorted(chosen, key=lambda r: r["mjd"])


def plan_epochs(images, per_group, det=""):
    """Survey epochs as lists of chosen images. With det (e.g. 'D6'), only that detector's images count."""
    if det:
        images = [im for im in images if im["detector"] == det]
    return [choose_images([images[i] for i in g], per_group) for g in group_epochs([im["mjd"] for im in images])]


def wavelength_range(images):
    """[min, max] wavelength in um over the detector bands of the images (SIA em_min / em_max)."""
    return [round(min(im["em_min"] for im in images), 3), round(max(im["em_max"] for im in images), 3)]


def epoch_label(mjds):
    """Date range of an epoch, e.g. '2025-08-15 to 09-13'. Unique, because epochs do not overlap."""
    first, last = (Time(t, format="mjd").strftime("%Y-%m-%d") for t in (min(mjds), max(mjds)))
    if first == last:
        return first
    return f"{first} to {last[5:] if first[:4] == last[:4] else last}"


def output_wcs(center, n):
    """North-up, east-left TAN grid of n x n pixels (6.15 arcsec) centered on center."""
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [center.ra.deg, center.dec.deg]
    w.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]
    w.wcs.cdelt = [-PIXEL_ARCSEC / 3600, PIXEL_ARCSEC / 3600]
    return w


def gaia_tracks(stars, grid, n, mjds):
    """Gaia DR3 stars (epoch 2016.0) moved by proper motion to each frame epoch: adds 'xy', PNG pixels per frame.

    A linear offset in the north-up grid is exact enough over a few arcmin and a few decades.
    """
    if not stars:
        return []
    x, y = grid.wcs_world2pix([s["ra"] for s in stars], [s["dec"] for s in stars], 0)
    tracks = []
    for s, sx, sy in zip(stars, x, y):
        px_yr = [(s.get(k) or 0.0) / (PIXEL_ARCSEC * 1000) for k in ("pmra", "pmdec")]  # mas/yr -> px/yr
        years = [(m - J2016_MJD) / 365.25 for m in mjds]
        tracks.append({**s, "xy": [[round(float(sx) + 0.5 - px_yr[0] * t, 2), round(n - 0.5 - float(sy) - px_yr[1] * t, 2)]
                                   for t in years]})
    return tracks


def gaia_overlay(stars, grid, n, mjds):
    """The response's 'gaia' field: at most 150 stars, brightest first, that are inside the view in at least one frame."""
    seen = [t for t in gaia_tracks(stars, grid, n, mjds) if any(0 <= x <= n and 0 <= y <= n for x, y in t["xy"])]
    return {"release": "Gaia DR3", "epoch_mjd": J2016_MJD, "stars": sorted(seen, key=lambda t: t["gmag"])[:150]}


def display_xy(grid, n, coord):
    """Sky position -> PNG pixel coordinates with the origin at the top-left corner.

    Grid row 0 is south, but PNG row 0 is north (the PNG is flipped), so y counts down from the top.
    """
    x, y = grid.wcs_world2pix(coord.ra.deg, coord.dec.deg, 0)
    return float(x) + 0.5, n - 0.5 - float(y)


def to_png(v):
    """Image with values in [0, 1] (row 0 = south) -> grayscale PNG data URL, north up. NaN is black."""
    buf = io.BytesIO()
    Image.fromarray(np.flipud(np.nan_to_num(v) * 255).round().astype(np.uint8)).save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def bad_pixels(flags):
    """Pixels to drop (NaN), from the FLAGS bits.

    Saturated (OVERFLOW) pixels hold unreliable values (R Dra's core reads dark), so they go; a NaN core
    inside a bright star is shown white later (saturated_holes). A bloomed star also carries TRANSIENT and
    SUR_ERROR as a side effect, so BLOOM pixels keep their values. OUTLIER is not used: it could hide a mover.
    """
    return ((flags & OVERFLOW) != 0) | (((flags & BAD_FLAGS) != 0) & ((flags & BLOOM) == 0))


def saturated_holes(img):
    """Mask of saturated star cores: NaN regions that do not touch the edge and whose rim median is at
    least 5% of the brightest pixel of the frame.

    Saturated pixels are NaN (see bad_pixels). Off-detector NaN touches the edge; a bad pixel on dark sky
    or next to a faint star has a rim near 1% of the maximum. Real cores (R Dra, Barnard's Star): 12-80%.
    """
    regions, n = label(np.isnan(img))
    holes = np.zeros(img.shape, bool)
    if not n or not np.isfinite(img).any():
        return holes
    bright = 0.05 * np.nanmax(img)
    edge = set(np.unique(np.r_[regions[0], regions[-1], regions[:, 0], regions[:, -1]]))
    for k in range(1, n + 1):
        region = regions == k
        if k not in edge and np.median(img[binary_dilation(region) & ~region]) >= bright:
            holes |= region
    return holes


def robust_sigma(img):
    """Noise level of an image from the median absolute deviation (stars and NaN do not disturb it)."""
    v = img[np.isfinite(img)]
    return float(1.4826 * np.median(np.abs(v - np.median(v)))) if v.size else 0.0


def gaussian(p, a, x0, y0, s, b):
    """Round 2-D Gaussian plus a constant at pixel positions p = (x, y)."""
    return a * np.exp(-((p[0] - x0) ** 2 + (p[1] - y0) ** 2) / (2 * s**2)) + b


def centroid(img, gx, gy, r=4.0):
    """Position of the source near grid position (gx, gy), or None when no source stands out (peak < 5 sigma).

    A round Gaussian is fitted to the pixels within r px. Unlike a flux-weighted mean, a fit is not pulled toward
    the window center, so the predicted position does not bias the result. NaN pixels (a saturated core) are
    skipped; the wings still fix the center. Returns {x, y, ex, ey} in PNG pixels (origin top-left, like the ring).
    ex, ey are 1-sigma errors: the fit error plus a floor for the resampling and WCS errors (CENTROID_FLOOR_PX).
    """
    yy, xx = np.indices(img.shape)
    d = np.hypot(xx - gx, yy - gy)
    ok = (d <= r) & np.isfinite(img)
    if img[ok & (d <= 3)].max(initial=-np.inf) <= 5 * robust_sigma(img):
        return None
    try:
        p, cov = curve_fit(gaussian, (xx[ok], yy[ok]), img[ok], p0=[img[ok].max(), gx, gy, 1.0, 0.0],
                           bounds=([0, gx - r, gy - r, 0.3, -np.inf], [np.inf, gx + r, gy + r, 5.0, np.inf]))
    except (RuntimeError, ValueError):  # no convergence: no position
        return None
    if not np.isfinite(cov[1:3, 1:3]).all():
        return None
    floor = CENTROID_FLOOR_PX[1] if (~np.isfinite(img[d <= r])).any() else CENTROID_FLOOR_PX[0]
    ex, ey = (float(np.hypot(np.sqrt(max(cov[i, i], 0.0)), floor)) for i in (1, 2))
    return {"x": round(float(p[1]) + 0.5, 3), "y": round(img.shape[0] - 0.5 - float(p[2]), 3),
            "ex": round(ex, 3), "ey": round(ey, 3)}


def mean_centroid(centroids):
    """Mean of the per-detector centroids of a frame (None entries skipped), or None if there are none.

    A frame is measured per detector, because the detectors see a star at different brightness (and saturate
    differently), so a stack of all detectors distorts the core. Each error is the larger of the propagated
    error and the standard error of the scatter: detectors that disagree widen the error bar.
    """
    cs = [c for c in centroids if c]
    if not cs:
        return None
    out = {}
    for k in ("x", "y"):
        v, e = np.array([c[k] for c in cs]), np.array([c["e" + k] for c in cs])
        sem = v.std(ddof=1) / np.sqrt(len(v)) if len(v) > 1 else 0.0
        out[k], out["e" + k] = round(float(v.mean()), 3), round(float(max(np.sqrt((e**2).sum()) / len(v), sem)), 3)
    return out


def aperture_photometry(img, gx, gy, r=2.5, r_in=4.0, r_out=7.0):
    """{flux, err} in mJy in a circle of radius r px around grid position (gx, gy), or None when a pixel in
    the circle has no data (saturated core, detector edge). The sky is the median of the r_in..r_out annulus;
    the error comes from the annulus scatter. Images are in MJy/sr; one pixel is (6.15 arcsec)^2.
    """
    yy, xx = np.indices(img.shape)
    d = np.hypot(xx - gx, yy - gy)
    ap, ann = img[d <= r], img[(d >= r_in) & (d <= r_out)]
    ann = ann[np.isfinite(ann)]
    if not np.isfinite(ap).all() or ann.size < 5:
        return None
    sky, sigma = np.median(ann), robust_sigma(ann)
    to_mjy = (PIXEL_ARCSEC / 206264.806) ** 2 * 1e9  # MJy/sr per pixel -> mJy
    flux = (ap - sky).sum() * to_mjy
    err = sigma * np.sqrt(ap.size + ap.size**2 * np.pi / 2 / ann.size) * to_mjy
    return {"flux": round(float(flux), 4), "err": round(float(err), 4)}


def stretch(img, lo, hi):
    """asinh stretch: lo -> 0 (black), hi -> 1 (white)."""
    v = np.clip((img - lo) / max(hi - lo, 1e-12), 0, 1)
    return np.arcsinh(v / 0.1) / np.arcsinh(10)


def http_get(url, stats=None, **params):
    """GET with up to 3 tries; back off on 5xx and network errors. HTTPException(502) if all fail.

    stats: optional dict; stats["retries"] counts the extra tries (reported in the response notes).
    """
    for attempt in range(3):
        try:
            r = requests.get(url, params=params or None, timeout=30)
            if r.ok:
                return r
            err = f"HTTP {r.status_code}"
            if r.status_code < 500:
                break
        except requests.RequestException as e:
            err = type(e).__name__
        if attempt < 2:
            if stats is not None:
                stats["retries"] += 1
            time.sleep(3 * (attempt + 1))
    raise HTTPException(502, f"{url.split('?')[0]} did not answer ({err}). Try again in a minute.")


def gaia_field(center, radius_deg):
    """Gaia DR3 stars brighter than G = 19 within radius_deg of center: the ESA archive TAP query that WANDERERS
    pipeline/fetch.py uses. Cached on disk, because the field does not change."""
    path = CACHE_DIR / f"gaia-{center.ra.deg:.4f}-{center.dec.deg:.4f}-{radius_deg:.4f}.json"
    if path.exists():
        return json.loads(path.read_text())
    query = ("SELECT TOP 2000 source_id, ra, dec, pmra, pmdec, phot_g_mean_mag FROM gaiadr3.gaia_source WHERE "
             f"1=CONTAINS(POINT('ICRS',ra,dec), CIRCLE('ICRS',{center.ra.deg},{center.dec.deg},{radius_deg})) "
             "AND phot_g_mean_mag < 19 ORDER BY phot_g_mean_mag")
    r = http_get(GAIA_TAP, REQUEST="doQuery", LANG="ADQL", FORMAT="csv", QUERY=query)
    num = lambda v: float(v) if v not in ("", None) else None  # noqa: E731 - masked Gaia values are empty
    stars = [{"source_id": row["source_id"], "ra": float(row["ra"]), "dec": float(row["dec"]), "pmra": num(row["pmra"]),
              "pmdec": num(row["pmdec"]), "gmag": num(row["phot_g_mean_mag"])}
             for row in csv.DictReader(io.StringIO(r.text))]
    write_json(path, stars)
    return stars


@lru_cache(maxsize=256)
def sesame(name):
    """Name -> (ra, dec, name, (pmra, pmdec) or None) from CDS Sesame; J2000 degrees, mas/yr. None if unknown."""
    hit = ET.fromstring(http_get(SESAME_URL + quote(name)).content).find(".//Resolver[jradeg]")
    if hit is None:
        return None
    try:
        pm = (float(hit.findtext("pm/pmRA")), float(hit.findtext("pm/pmDE")))
    except (TypeError, ValueError):  # no proper motion known
        pm = None
    oname = (hit.findtext("oname") or name).removeprefix("NAME ")
    return float(hit.findtext("jradeg")), float(hit.findtext("jdedeg")), oname, pm


def resolve(q):
    """Text -> (J2000 SkyCoord, name or None, (pmra, pmdec) mas/yr or None). HTTPException(400) if unknown."""
    if not q.strip():
        raise HTTPException(400, "Type a target name or RA and Dec, for example R Dra or 269.45 4.69.")
    try:
        c = parse_coords(q)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    if c is not None:
        return c, None, None
    hit = sesame(q.strip())
    if hit is None:
        raise HTTPException(400, f"Could not find '{q.strip()}'. Type RA and Dec instead, for example 269.45 4.69.")
    ra, dec, name, pm = hit
    return SkyCoord(ra, dec, unit=u.deg), name, pm


def at_epoch(coord, pm, mjd):
    """Move a J2000 position by its proper motion (mas/yr) to the given MJD (tangent-plane offset)."""
    years = (mjd - 51544.5) / 365.25
    return coord.spherical_offsets_by(pm[0] * years * u.mas, pm[1] * years * u.mas)


def s3_url(row):
    """HTTPS URL of the anonymous S3 copy of an image (supports Range); IRSA URL as fallback."""
    try:
        return S3_URL + json.loads(str(row["cloud_access"]))["aws"]["key"]
    except (ValueError, KeyError, TypeError):
        return str(row["access_url"])


def query_images(center, stats=None):
    """All Level-2 SPHEREx images (DR1 + QR3) that cover the position: dicts with mjd, detector, band
    edges em_min / em_max (um) and url."""
    images = []
    for collection in ("spherex_dr1", "spherex_qr3"):
        pos = f"circle {center.ra.deg} {center.dec.deg} 0.001"
        r = http_get(SIA_URL, stats=stats, COLLECTION=collection, POS=pos, RESPONSEFORMAT="VOTABLE")
        try:  # FIELD IDs are col_0..col_N, so ask for the names
            table = parse_votable(io.BytesIO(r.content)).get_first_table().to_table(use_names_over_ids=True)
        except Exception as e:  # an HTML error page or a broken VOTable
            raise HTTPException(502, f"IRSA sent an unreadable answer ({e}). Try again in a minute.") from None
        for row in table:
            if row["calib_level"] == 2 and row["dataproduct_type"] == "image" and row["dataproduct_subtype"] == "science":
                detector = str(row["energy_bandpassname"]).removeprefix("SPHEREx-")
                images.append({"mjd": float(row["t_min"]), "detector": detector, "url": s3_url(row),
                               "em_min": float(row["em_min"]) * 1e6, "em_max": float(row["em_max"]) * 1e6})
    return images


def read_cutout(url, ra, dec):
    """Read only the pixels under the output grid from one image and resample them onto the grid.

    ra, dec: sky position of every output pixel. Returns the aligned cutout minus its median,
    or None when the grid misses the image.
    """
    with fits.open(url, use_fsspec=True, fsspec_kwargs=FSSPEC) as hdul:
        hdu = hdul["IMAGE"]
        x, y = WCS(hdu.header).all_world2pix(ra, dec, 0, quiet=True)  # SIP-aware, 0-based
        ny, nx = hdu.shape
        x0, y0 = max(int(np.nanmin(x)) - 2, 0), max(int(np.nanmin(y)) - 2, 0)
        x1, y1 = min(int(np.nanmax(x)) + 3, nx), min(int(np.nanmax(y)) + 3, ny)
        if x0 >= x1 or y0 >= y1:
            return None
        data = hdu.section[y0:y1, x0:x1].astype(float)
        data[bad_pixels(hdul["FLAGS"].section[y0:y1, x0:x1])] = np.nan  # FLAGS is row-tiled RICE: a small read
    return subtract_background(map_coordinates(data, [y - y0, x - x0], order=1, cval=np.nan))


def subtract_background(cut):
    """Remove the sky level and its linear gradient (zodi, D1/D2 airglow) from an aligned cutout.

    The plane is fitted to the faintest 90% of the pixels, so stars do not pull it up.
    """
    # ponytail: plane background; the ZODI HDU does not hold airglow, a curved model if curved gradients show
    yy, xx = np.indices(cut.shape)
    a = np.c_[np.ones(cut.size), xx.ravel(), yy.ravel()]
    v = cut.ravel()
    ok = np.isfinite(v) & (v <= np.nanpercentile(v, 90))
    if ok.sum() < 3:
        return cut - np.nanmedian(cut)
    rest = cut - (a @ np.linalg.lstsq(a[ok], v[ok], rcond=None)[0]).reshape(cut.shape)
    return rest - np.nanmedian(rest)


def read_with_retry(url, ra, dec, stats=None):
    """read_cutout with up to 3 tries (S3 and network errors are usually short)."""
    for attempt in range(3):
        try:
            return read_cutout(url, ra, dec)
        except Exception:
            if attempt == 2:
                raise
            if stats is not None:
                stats["retries"] += 1
            time.sleep(2 * (attempt + 1))


def build(q, name, coord, center, pm, fov, per_group, det):
    """Find, read, align and stack the images; return the cached part of the response (no cached, gaia, quality)."""
    stats = {"retries": 0}
    epochs = plan_epochs(query_images(center, stats), per_group, det)
    if not epochs:
        raise HTTPException(404, f"No SPHEREx {det + ' ' if det else ''}images cover this position yet.")
    n = round(fov * 60 / PIXEL_ARCSEC)
    grid = output_wcs(center, n)
    ra, dec = grid.wcs_pix2world(*np.meshgrid(np.arange(n), np.arange(n)), 0)  # indexed [grid y, grid x]

    flat = [im for e in epochs for im in e]
    with ThreadPoolExecutor(12) as pool:
        futures = [pool.submit(read_with_retry, im["url"], ra, dec, stats) for im in flat]
    n_failed = 0
    for im, f in zip(flat, futures):
        try:
            im["cutout"] = f.result()
        except Exception as e:
            log.warning("skipped %s: %r", im["url"], e)
            im["cutout"] = None
            n_failed += 1

    frames, stacks, targets, by_det = [], [], [], defaultdict(list)
    for e in epochs:
        used = [im for im in e if im["cutout"] is not None and np.isfinite(im["cutout"]).any()]
        if not used:
            continue
        mjd = float(np.mean([im["mjd"] for im in used]))
        target = at_epoch(coord, pm, mjd) if pm else center
        ring = None
        if pm:
            x, y = display_xy(grid, n, target)
            ring = {"x": round(x, 2), "y": round(y, 2)}
        tx, ty = (float(v) for v in grid.wcs_world2pix(target.ra.deg, target.dec.deg, 0))
        names, dets = sorted({im["detector"] for im in used}), []
        for d in names:
            ims = [im for im in used if im["detector"] == d]
            img = np.nanmean([im["cutout"] for im in ims], axis=0)
            dets.append({"group_index": len(frames), "img": img, "n_images": len(ims), "wavelength_um": wavelength_range(ims),
                         "photometry": aperture_photometry(img, tx, ty), "centroid": centroid(img, tx, ty)})
            by_det[d].append(dets[-1])
        stack = np.nanmean([im["cutout"] for im in used], axis=0)
        stacks.append(stack)
        targets.append((tx, ty))
        # Measured per detector: the detectors see the target at different brightness and saturate differently,
        # so near a bright core the all-detector stack mixes different images in each pixel.
        frames.append({"label": epoch_label([im["mjd"] for im in used]), "mjd_mean": round(mjd, 4),
                       "date": Time(mjd, format="mjd").strftime("%Y-%m-%d"), "n_images": len(used), "ring": ring,
                       "detectors": names, "wavelength_um": wavelength_range(used),
                       "centroid": mean_centroid([it["centroid"] for it in dets]),
                       "photometry": aperture_photometry(stack, tx, ty) if all(it["photometry"] for it in dets) else None})
    if not frames:
        raise HTTPException(502, "Could not read any SPHEREx image for this position. Try again in a minute.")

    lo, hi = np.nanpercentile(stacks, [0.5, 99.7])  # one stretch for all frames, so blinking is fair
    holes = [saturated_holes(s) for s in stacks]
    yy, xx = np.indices((n, n))
    for frame, s, h, (tx, ty) in zip(frames, stacks, holes, targets):
        frame["saturated"] = bool((h & ((xx - tx) ** 2 + (yy - ty) ** 2 <= 9)).any())  # within 3 px
        frame["png"] = to_png(stretch(np.where(h, np.inf, s), lo, hi))  # a saturated core shows white
        if frame["saturated"]:  # no photometry; the centroid comes from the wings (docs/blink/api.md, Differences)
            frame["photometry"] = None
            if frame["centroid"]:
                frame["centroid"]["saturated"] = True
    detectors = {}
    for d, items in sorted(by_det.items()):
        lo_d, hi_d = np.nanpercentile([it["img"] for it in items], [0.5, 99.7])
        detectors[d] = [{"group_index": it["group_index"], "n_images": it["n_images"], "wavelength_um": it["wavelength_um"],
                         "photometry": it["photometry"],
                         "png": to_png(stretch(np.where(saturated_holes(it["img"]), np.inf, it["img"]), lo_d, hi_d))}
                        for it in items]

    notes = []
    if n_failed:
        notes.append(f"{n_failed} image{'s' if n_failed > 1 else ''} failed after retries.")
    if stats["retries"]:
        notes.append(f"IRSA or S3 needed {stats['retries']} retr{'ies' if stats['retries'] > 1 else 'y'}.")
    if k := sum(f["saturated"] for f in frames):
        notes.append(f"The target is saturated in {k} of {len(frames)} frames: centroids there come from the wings.")
    if k := sum(f["photometry"] is None for f in frames):
        notes.append(f"No photometry in {k} of {len(frames)} frames: in at least one detector the aperture has no data"
                     " (saturated core or detector edge). Per-detector photometry is given where it exists.")
    difference = None
    if len(stacks) >= 2:
        diff = stacks[-1] - stacks[0]  # a mover: dark where it was, bright where it is now
        diff[holes[0] | holes[-1]] = np.nan  # saturated cores have no measurement: gray, like no data
        s = np.nanpercentile(np.abs(diff), 99.7)
        v = 0.5 + 0.5 * np.sign(diff) * stretch(np.abs(diff), 0, s)
        difference = {"png": to_png(np.nan_to_num(v, nan=0.5)),  # no data -> gray (no change), not black
                      "from": frames[0]["label"], "to": frames[-1]["label"]}
    return {
        "query": q,
        "name": name,
        "center": {"ra": round(float(center.ra.deg), 6), "dec": round(float(center.dec.deg), 6)},
        "pm": {"pmra": pm[0], "pmdec": pm[1]} if pm else None,
        "det": det or None,
        "fov_arcmin": fov,
        "pixel_arcsec": PIXEL_ARCSEC,
        "size_px": n,
        "frames": frames,
        "detectors": detectors,
        "difference": difference,
        "photometry_unit": "mJy (aperture r = 2.5 px, sky from the 4-7 px annulus)",
        "notes": notes,
        "n_images_used": sum(f["n_images"] for f in frames),
        "n_failed": n_failed,
    }


def get_frames(q, fov=5.0, per_group=12, det=""):
    """API response for query q; served from the disk cache when the same view was built before.

    det: '' stacks all detectors; 'D1'..'D6' stacks only that detector (D6 suits cold brown dwarfs).
    """
    coord, name, pm = resolve(q)
    center = at_epoch(coord, pm, CENTER_MJD) if pm else coord
    fov, per_group = float(fov), int(per_group)
    key = json.dumps([CACHE_VERSION, round(center.ra.deg, 5), round(center.dec.deg, 5), fov, per_group, det])
    path = CACHE_DIR / (hashlib.sha256(key.encode()).hexdigest() + ".json")
    cached = path.exists()
    result = json.loads(path.read_text()) if cached else build(q, name, coord, center, pm, fov, per_group, det)
    if not cached:
        write_json(path, result)
    n, notes = result["size_px"], list(result["notes"])
    try:  # not cached with the frames, so a failed Gaia query is tried again on the next request
        stars = gaia_field(center, fov / 60 / 2 * 1.5)
        gaia = gaia_overlay(stars, output_wcs(center, n), n, [f["mjd_mean"] for f in result["frames"]])
    except Exception as e:  # fail soft: the frames work without the overlay
        gaia = None
        notes.append(f"Gaia DR3 query failed; overlay off ({getattr(e, 'detail', e)}).")
    quality = {"n_images_used": result["n_images_used"], "n_failed": result["n_failed"],
               "cache_age_s": round(time.time() - path.stat().st_mtime) if cached else 0}
    return {**result, "query": q, "cached": cached, "gaia": gaia, "notes": notes, "quality": quality}


def write_json(path, data):
    """Write JSON atomically (temp file, then rename), so a reader never sees half a file."""
    CACHE_DIR.mkdir(exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=CACHE_DIR, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)
