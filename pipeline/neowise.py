"""Fill the 2010 -> 2025 gap: one NEOWISE image per sky visit (about every 6 months, Dec 2013 - mid 2024).

    python pipeline/neowise.py                 # every prepared target
    python pipeline/neowise.py kapteyn barnard # some targets (ids as in app/data/index.json)

NEOWISE (the reactivated WISE telescope) re-scanned the whole sky twice a year in the same two colours as our
2010 AllWISE frames: W1 (3.4 um) and W2 (4.6 um). Everything comes from NASA's IRSA archive on AWS (public,
no account), so it works even when IRSA's own web services are busy:

1. Which exposures cover the target: the NEOWISE-R Single-exposure Source Table (Parquet, partitioned by HEALPix
   order 5) lists every detection with the exposure it came from (scan_id, frame_num, mjd). We read only those
   5 columns of the one sky partition holding the target, for each mission year, and keep detections within
   3 arcmin of where the target was in 2019 (its proper motion is followed when the visit images are built).
2. Exposures are grouped into visits (a gap of more than 20 days starts a new one).
3. For each visit and band, up to MAX_PER_VISIT exposures are read from the Level-1b images on AWS with an HTTP
   byte-range request: the FITS header, then only the rows around the target (the images are uncompressed, so
   a 0.5 MB strip replaces the 4.2 MB file). Each strip is background-subtracted and reprojected onto a TAN grid
   centred on the target's position at that visit, and the strips are median-combined.

Output: data/cache/<id>/neowise/w{1,2}_<visit>.fits, each with MJD-OBS (mean of the exposures) and NFRAMES.
analyze.py adds them to the time-lapse between WISE 2010 and SPHEREx 2025, labelled "NEOWISE <month year>".
"""
import json, ssl, sys, urllib.request, warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import certifi
import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.time import Time
from astropy.wcs import WCS, FITSFixedWarning
from astropy_healpix import HEALPix
import pyarrow.fs as pfs
import pyarrow.parquet as pq
from reproject import reproject_interp

warnings.simplefilter("ignore", FITSFixedWarning)
ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
APP = ROOT / "app" / "data"
BUCKET = "nasa-irsa-wise"
CAT = BUCKET + "/wise/neowiser/catalogs/p1bs_psd/healpix_k5/{y}/neowiser-healpix_k5-{y}.parquet/healpix_k0={k0}/healpix_k5={k5}/part0.snappy.parquet"
IMG = "https://nasa-irsa-wise.s3.us-west-2.amazonaws.com/wise/neowiser/images/p1bm_frm/{g}/{s}/{f:03d}/{s}{f:03d}-w{b}-int-1b.fits"
YEARS = [f"year{i}" for i in range(1, 12)] + ["addendum"]
PIX = 2.75                  # arcsec, NEOWISE native pixel
MAX_PER_VISIT = 10          # exposures stacked per visit and band (spread through the visit)
CTX = ssl.create_default_context(cafile=certifi.where())


def get(url, rng=None, tries=4):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"Range": f"bytes={rng[0]}-{rng[1]}"} if rng else {})
            with urllib.request.urlopen(req, timeout=60, context=CTX) as r:
                return r.read()
        except Exception:
            if k == tries - 1:
                raise


def predict(ref, year):
    c = SkyCoord(ref["ra"] * u.deg, ref["dec"] * u.deg, pm_ra_cosdec=(ref.get("pmra") or 0) * u.mas / u.yr,
                 pm_dec=(ref.get("pmdec") or 0) * u.mas / u.yr, obstime=Time(ref.get("epoch", 2016.0), format="jyear"))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return c.apply_space_motion(new_obstime=Time(year, format="jyear"))


def exposures(ra, dec, radius_deg=3 / 60):
    """(scan_id, frame_num, mjd) of every NEOWISE exposure with detections near (ra, dec)."""
    k5 = int(HEALPix(nside=32, order="nested").lonlat_to_healpix(ra * u.deg, dec * u.deg))
    fs = pfs.S3FileSystem(anonymous=True, region="us-west-2")
    rdec, rra = radius_deg, radius_deg / max(0.05, np.cos(np.radians(dec)))
    flt = [("dec", ">", dec - rdec), ("dec", "<", dec + rdec), ("ra", ">", ra - rra), ("ra", "<", ra + rra)]

    def one(y):
        try:
            t = pq.read_table(CAT.format(y=y, k0=k5 >> 10, k5=k5), filesystem=fs, columns=["scan_id", "frame_num", "mjd"], filters=flt)
            return list(zip(t["scan_id"].to_pylist(), t["frame_num"].to_pylist(), t["mjd"].to_pylist()))
        except Exception as e:
            print(f"   {y}: {str(e)[:80]}", flush=True)
            return []
    rows = {}
    with ThreadPoolExecutor(6) as ex:
        for part in ex.map(one, YEARS):
            for s, f, m in part:
                rows.setdefault((s, int(f)), []).append(m)
    return sorted(((s, f, float(np.median(m))) for (s, f), m in rows.items()), key=lambda x: x[2])


def visits(exps, gap_days=20):
    out, cur = [], []
    for e in exps:
        if cur and e[2] - cur[-1][2] > gap_days:
            out.append(cur); cur = []
        cur.append(e)
    return out + ([cur] if cur else [])


def strip(scan, frame, band, c, half):
    """Background-subtracted pixels around sky position c from one L1b exposure, with their WCS (or None)."""
    url = IMG.format(g=scan[-2:], s=scan, f=frame, b=band)
    head = get(url, (0, 2880 * 14 - 1))
    end = head.find(b"END" + b" " * 77)
    if end < 0:
        return None
    hlen = (end // 2880 + 1) * 2880
    h = fits.Header.fromstring(head[:hlen].decode("ascii", "ignore"))
    nx, ny = h["NAXIS1"], h["NAXIS2"]
    w = WCS(h)
    x, y = w.world_to_pixel(c)
    if not (np.isfinite(x) and -half < x < nx + half and -half < y < ny + half):
        return None
    y0, y1 = max(0, int(y) - half), min(ny - 1, int(y) + half)
    x0, x1 = max(0, int(x) - half), min(nx - 1, int(x) + half)
    if y1 - y0 < 8 or x1 - x0 < 8:
        return None
    raw = get(url, (hlen + y0 * nx * 4, hlen + (y1 + 1) * nx * 4 - 1))
    a = np.frombuffer(raw, dtype=">f4").reshape(y1 - y0 + 1, nx)[:, x0:x1 + 1].astype(float)
    a -= np.nanmedian(a)
    return a, w[y0:y1 + 1, x0:x1 + 1]


def visit_image(group, band, ref, fov):
    """Median of up to MAX_PER_VISIT exposures of one visit, on a TAN grid centred on the target then."""
    mjd = float(np.mean([e[2] for e in group]))
    c = predict(ref, Time(mjd, format="mjd").jyear)
    n = int(round(fov * 1.6 / PIX)) | 1
    gw = WCS(naxis=2)
    gw.wcs.ctype = ["RA---TAN", "DEC--TAN"]; gw.wcs.crval = [c.ra.deg, c.dec.deg]
    gw.wcs.crpix = [n / 2 + 0.5, n / 2 + 0.5]; gw.wcs.cdelt = [-PIX / 3600, PIX / 3600]
    pick = [group[int(i)] for i in np.linspace(0, len(group) - 1, min(MAX_PER_VISIT, len(group)))]
    half = int(fov * 0.85 / PIX) + 4

    def one(e):
        try:
            return strip(e[0], e[1], band, c, half)
        except Exception:
            return None
    stack = []
    with ThreadPoolExecutor(6) as ex:
        for s in ex.map(one, pick):
            if s is not None:
                r, _ = reproject_interp((s[0], s[1]), gw, shape_out=(n, n))
                stack.append(r)
    if not stack:
        return None
    hdr = gw.to_header()
    hdr["MJD-OBS"] = round(mjd, 4); hdr["NFRAMES"] = len(stack); hdr["BAND"] = f"W{band}"
    hdr["ORIGIN"] = "NEOWISE-R L1b via NASA IRSA on AWS, stacked by WANDERERS"
    return fits.PrimaryHDU(np.nanmedian(np.array(stack), axis=0).astype("float32"), header=hdr)


def run(tid):
    meta = CACHE / tid / "gaia.json"
    if not meta.exists():
        print(f"!! {tid}: no reference (run fetch.py first)"); return
    ref = json.loads(meta.read_text())["ref"]
    tdef = CACHE / tid / "target_def.json"
    fov = json.loads(tdef.read_text()).get("fov_arcsec", 300) if tdef.exists() else 300
    c19 = predict(ref, 2019.0)
    exps = exposures(c19.ra.deg, c19.dec.deg)
    vs = [v for v in visits(exps) if len(v) >= 3]
    print(f"== {tid}: {len(exps)} NEOWISE exposures in {len(vs)} visits", flush=True)
    out = CACHE / tid / "neowise"
    out.mkdir(exist_ok=True)
    made = 0
    for i, v in enumerate(vs):
        for band in (2, 1):
            f = out / f"w{band}_{i:02d}.fits"
            if f.exists():
                made += 1; continue
            hdu = visit_image(v, band, ref, fov)
            if hdu is not None:
                hdu.writeto(f, overwrite=True); made += 1
        yr = Time(np.mean([e[2] for e in v]), format="mjd").datetime
        print(f"   visit {i + 1}/{len(vs)} {yr:%b %Y}: {len(v)} exposures", flush=True)
    print(f"   {made} visit images in {out}", flush=True)


if __name__ == "__main__":
    ids = sys.argv[1:] or [t["id"] for t in json.loads((APP / "index.json").read_text())]
    for tid in ids:
        try:
            run(tid)
        except Exception as e:
            print(f"!! {tid}: {e}", flush=True)
