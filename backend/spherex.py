"""SPHEREx blink pipeline: resolve a target, find images, align cutouts, make PNG frames.

resolve -> IRSA SIA (spherex_dr1 + spherex_qr3) -> group by survey epoch -> choose images
-> fsspec section reads from S3 -> SIP WCS -> north-up TAN grid -> stack, difference -> PNG -> disk cache
"""
import base64
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
from scipy.ndimage import map_coordinates

PIXEL_ARCSEC = 6.15
CENTER_MJD = 61041.0  # epoch J2026.0: cutouts are centered on the target's position at this date
SESAME_URL = "https://cds.unistra.fr/cgi-bin/nph-sesame/-oxp/SNV?"
SIA_URL = "https://irsa.ipac.caltech.edu/SIA"
S3_URL = "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/"
FSSPEC = {"block_size": 256 * 1024, "cache_type": "blockcache"}
CACHE_DIR = Path(__file__).parent / "cache"
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


def output_wcs(center, n):
    """North-up, east-left TAN grid of n x n pixels (6.15 arcsec) centered on center."""
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [center.ra.deg, center.dec.deg]
    w.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]
    w.wcs.cdelt = [-PIXEL_ARCSEC / 3600, PIXEL_ARCSEC / 3600]
    return w


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


def stretch(img, lo, hi):
    """asinh stretch: lo -> 0 (black), hi -> 1 (white)."""
    v = np.clip((img - lo) / max(hi - lo, 1e-12), 0, 1)
    return np.arcsinh(v / 0.1) / np.arcsinh(10)


def http_get(url, **params):
    """GET with up to 3 tries; back off on 5xx and network errors. HTTPException(502) if all fail."""
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
            time.sleep(3 * (attempt + 1))
    raise HTTPException(502, f"{url.split('?')[0]} did not answer ({err}). Try again in a minute.")


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


def query_images(center):
    """All Level-2 SPHEREx images (DR1 + QR3) that cover the position: dicts with mjd, detector, url."""
    images = []
    for collection in ("spherex_dr1", "spherex_qr3"):
        pos = f"circle {center.ra.deg} {center.dec.deg} 0.001"
        r = http_get(SIA_URL, COLLECTION=collection, POS=pos, RESPONSEFORMAT="VOTABLE")
        try:  # FIELD IDs are col_0..col_N, so ask for the names
            table = parse_votable(io.BytesIO(r.content)).get_first_table().to_table(use_names_over_ids=True)
        except Exception as e:  # an HTML error page or a broken VOTable
            raise HTTPException(502, f"IRSA sent an unreadable answer ({e}). Try again in a minute.") from None
        for row in table:
            if row["calib_level"] == 2 and row["dataproduct_type"] == "image" and row["dataproduct_subtype"] == "science":
                detector = str(row["energy_bandpassname"]).removeprefix("SPHEREx-")
                images.append({"mjd": float(row["t_min"]), "detector": detector, "url": s3_url(row)})
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
    cut = map_coordinates(data, [y - y0, x - x0], order=1, cval=np.nan)
    # ponytail: median background, use the ZODI HDU if gradients show
    return cut - np.nanmedian(cut)


def read_with_retry(url, ra, dec):
    """read_cutout with up to 3 tries (S3 and network errors are usually short)."""
    for attempt in range(3):
        try:
            return read_cutout(url, ra, dec)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def build(q, name, coord, center, pm, fov, per_group):
    """Find, read, align and stack the images; return the API response (without 'cached')."""
    images = query_images(center)
    if not images:
        raise HTTPException(404, "No SPHEREx images cover this position yet.")
    epochs = [choose_images([images[i] for i in g], per_group) for g in group_epochs([im["mjd"] for im in images])]
    n = round(fov * 60 / PIXEL_ARCSEC)
    grid = output_wcs(center, n)
    ra, dec = grid.wcs_pix2world(*np.meshgrid(np.arange(n), np.arange(n)), 0)  # indexed [grid y, grid x]

    flat = [im for e in epochs for im in e]
    with ThreadPoolExecutor(12) as pool:
        futures = [pool.submit(read_with_retry, im["url"], ra, dec) for im in flat]
    n_failed = 0
    for im, f in zip(flat, futures):
        try:
            im["cutout"] = f.result()
        except Exception as e:
            log.warning("skipped %s: %r", im["url"], e)
            im["cutout"] = None
            n_failed += 1

    frames, stacks, by_det = [], [], defaultdict(list)
    for e in epochs:
        used = [im for im in e if im["cutout"] is not None and np.isfinite(im["cutout"]).any()]
        if not used:
            continue
        mjd = float(np.mean([im["mjd"] for im in used]))
        t = Time(mjd, format="mjd")
        ring = None
        if pm:
            x, y = display_xy(grid, n, at_epoch(coord, pm, mjd))
            ring = {"x": round(x, 2), "y": round(y, 2)}
        for d in sorted({im["detector"] for im in used}):
            cuts = [im["cutout"] for im in used if im["detector"] == d]
            by_det[d].append({"group_index": len(frames), "img": np.nanmean(cuts, axis=0), "n_images": len(cuts)})
        stacks.append(np.nanmean([im["cutout"] for im in used], axis=0))
        frames.append({"label": t.strftime("%Y-%m") + " survey", "mjd_mean": round(mjd, 4),
                       "date": t.strftime("%Y-%m-%d"), "n_images": len(used), "ring": ring})
    if not frames:
        raise HTTPException(502, "Could not read any SPHEREx image for this position. Try again in a minute.")

    lo, hi = np.nanpercentile(stacks, [0.5, 99.7])  # one stretch for all frames, so blinking is fair
    for frame, s in zip(frames, stacks):
        frame["png"] = to_png(stretch(s, lo, hi))
    detectors = {}
    for d, items in sorted(by_det.items()):
        lo_d, hi_d = np.nanpercentile([it["img"] for it in items], [0.5, 99.7])
        detectors[d] = [{"group_index": it["group_index"], "png": to_png(stretch(it["img"], lo_d, hi_d)),
                         "n_images": it["n_images"]} for it in items]
    difference = None
    if len(stacks) >= 2:
        diff = stacks[-1] - stacks[0]  # a mover: dark where it was, bright where it is now
        s = np.nanpercentile(np.abs(diff), 99.7)
        difference = {"png": to_png(0.5 + 0.5 * np.sign(diff) * stretch(np.abs(diff), 0, s)),
                      "from": frames[0]["label"], "to": frames[-1]["label"]}
    return {
        "query": q,
        "name": name,
        "center": {"ra": round(float(center.ra.deg), 6), "dec": round(float(center.dec.deg), 6)},
        "pm": {"pmra": pm[0], "pmdec": pm[1]} if pm else None,
        "fov_arcmin": fov,
        "pixel_arcsec": PIXEL_ARCSEC,
        "size_px": n,
        "frames": frames,
        "detectors": detectors,
        "difference": difference,
        "n_images_used": sum(f["n_images"] for f in frames),
        "n_failed": n_failed,
    }


def get_frames(q, fov=5.0, per_group=12):
    """API response for query q; served from the disk cache when the same view was built before."""
    coord, name, pm = resolve(q)
    center = at_epoch(coord, pm, CENTER_MJD) if pm else coord
    fov, per_group = float(fov), int(per_group)
    key = json.dumps([round(center.ra.deg, 5), round(center.dec.deg, 5), fov, per_group])
    path = CACHE_DIR / (hashlib.sha256(key.encode()).hexdigest() + ".json")
    if path.exists():
        return {**json.loads(path.read_text()), "query": q, "cached": True}
    result = build(q, name, coord, center, pm, fov, per_group)
    CACHE_DIR.mkdir(exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=CACHE_DIR, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(result, f)
    os.replace(tmp, path)
    return {**result, "cached": False}
