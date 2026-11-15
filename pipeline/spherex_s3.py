"""SPHEREx Level-2 images straight from NASA IRSA's public S3 bucket, for when IRSA's web services are down.

    python pipeline/spherex_s3.py releases                         # release folders and the newest week of each
    python pipeline/spherex_s3.py index qr3                        # footprint index of every QR3 image (resumable)
    python pipeline/spherex_s3.py index qr3 --weeks 2026W33_1A,2026W33_2A --detectors 1,2,3,4,5,6
    python pipeline/spherex_s3.py search barnard --release qr3     # images that cover a target, from the index
    python pipeline/spherex_s3.py pairs qr3 2026W20_2A,2026W40_2A  # check the dichroic pairs on real headers

pipeline/fetch.py uses this module by itself when IRSA fails; the index must exist first (the `index` command).

IRSA finds SPHEREx images with SIA and cuts them with its cutout service (pipeline/fetch.py). When those answer HTTP 502,
the same Level-2 files can still be read from the anonymous bucket s3://nasa-irsa-spherex (us-east-1): folders
<release>/level2/<week>/<processing>/<detector>/level2_<obs_id>D<det>_spx_<processing>.fits, where <week> is a half-week
such as 2026W40_2A (ISO year and week, half 1 or 2, planning letter) and <processing> is l2b-v27-<date> or, for images
that were reprocessed after a failure, l2b_retry-v27-<date> (the two hold different images).

Finding images. Every file starts with a 2880-byte primary header and the IMAGE header (25,920 bytes in the files we
read), so one HTTP Range request for the first 10 FITS blocks gives the detector, the observation time and the
SIP-distorted TAN WCS. build_index() reads those headers for every image of the weeks asked for (32-64 requests at a
time, with retries) and keeps one JSON line per image in data/cache/spherex_s3_index/<release>.jsonl: key, detector,
MJD, centre, an 8-point footprint and the detector's wavelength range. It is resumable and incremental: images already
in the file are not read again, and weeks whose every image is indexed are not even listed again.

Dichroic pairs. SPHEREx splits each exposure with a dichroic: detectors 1/4, 2/5 and 3/6 see the same sky (the MWIR
images are flipped on X in the pipeline so their pixels match, header DETCOORD='sky'). Checked on real QR3 headers
(see PAIR_CHECK); with infer_pairs=True only detectors 1-3 are read and 4-6 get their partner's footprint, with the
partner file's own key from the bucket listing. Cutouts always read the real file's own header.

Cutouts. An image covers a target when the target's position at that image's time (pipeline/fetch.py's predict())
lies inside the footprint. cutout() then reads only the rows around it: IMAGE and VARIANCE are uncompressed float32
(8,160 bytes a row), FLAGS is a RICE_1 tile-compressed table with one tile per row (its row descriptors, then only
those rows' compressed bytes), and WCS-WAVE is the last 5,760 bytes of the file. The result has the same extensions,
header cards and pixel offsets as an IRSA cutout (?center=..&size=..px), which pipeline/analyze.py reads unchanged:
compare_with_irsa() checks this against cached IRSA cutouts.

Only the standard library, numpy, requests and astropy are used. Every network call goes through a reader object
(S3Reader here; tests pass a fake one), so nothing here needs the network to be tested.
"""
import argparse
import io
import json
import math
import os
import re
import sys
import threading
import time
import warnings
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
INDEX_DIR = CACHE / "spherex_s3_index"

BUCKET = "nasa-irsa-spherex"
REGION = "us-east-1"
BASE_URL = f"https://{BUCKET}.s3.{REGION}.amazonaws.com/"
IRSA_DATA_URL = "https://irsa.ipac.caltech.edu/ibe/data/spherex/"   # SIA access_url = this + the S3 key
S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
BLOCK = 2880
HEAD_BLOCKS = 10                     # primary header (1 block) + IMAGE header (9 blocks in DR1 and QR3 files)
RELEASE_DIR_RE = re.compile(r"^(dr|qr)(\d{1,3})$")
WEEK_RE = re.compile(r"^(\d{4})W(\d{2})_(\d)([A-Z])$")
FILE_RE = re.compile(r"/level2_(?P<obs>\d{4}W\d{2}_\d[A-Z]_\d{4}_\d)D(?P<det>\d)_spx_[^/]+\.fits$")
# Detector wavelength ranges in metres, as IRSA SIA reports them (em_min, em_max). Every SIA row of spherex_dr1 and
# spherex_qr3 cached in data/cache/*/ (1,000s of rows, 2026-11-14) has exactly these values for its detector.
DETECTOR_BANDS = {1: (7.455e-07, 1.1167e-06), 2: (1.1033e-06, 1.6499e-06), 3: (1.6301e-06, 2.4346e-06),
                  4: (2.4027e-06, 3.8473e-06), 5: (3.8113e-06, 4.43e-06), 6: (4.4115e-06, 5.0096e-06)}
PAIRS = {1: 4, 2: 5, 3: 6, 4: 1, 5: 2, 6: 3}
# Dichroic partners: same exposure (identical MJD-BEG), nearly the same sky. Measured on 2026-11-15 from real QR3
# headers of 9 exposures (3 each in weeks 2026W20_2A, 2026W33_1A, 2026W40_2A; all 6 detectors read): matching
# footprint points of a detector and its partner differ by 69-77" on average and 105.1" at most (about 12 and 17
# pixels), stable from exposure to exposure, while neighbouring detectors (D1/D2) are 3.86 deg apart. So a partner's
# footprint is the read detector's widened by PAIR_MARGIN_DEG for the first cut, and search() then reads the
# partner's own header for the exact test (refine_inferred), so no image is chosen on an inferred footprint alone.
PAIR_CHECK = {"exposures": 9, "pairs": 27, "mean_offset_arcsec": (69, 77), "max_offset_arcsec": 105.1}
PAIR_MARGIN_DEG = 0.035              # 126", above the 105" measured
SIA_RADIUS_DEG = 0.002               # fetch.py's SIA search circle: a footprint this close to the target still counts
INDEX_FIELDS = ("key", "release", "week", "obs_id", "detector", "mjd", "mjd_end", "ra", "dec", "corners",
                "em_min", "em_max", "naxis1", "naxis2", "sps_flags", "size", "inferred_from")


def log_default(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------- reading the bucket ----------------------------

class S3Error(RuntimeError):
    """The bucket could not be read (network, HTTP error, unexpected answer)."""


class S3Reader:
    """Anonymous HTTPS access to the bucket: byte ranges of one object, and folder listings.

    read(key, start, stop) gives bytes [start, stop); read_suffix(key, n) the last n bytes; list(prefix, delimiter)
    gives (sub-folders, [(key, size)]) over every page. Transient failures (5xx, 429, timeouts) are retried."""

    def __init__(self, base=BASE_URL, tries=5, timeout=60, pool=64, session=None):
        import requests
        from requests.adapters import HTTPAdapter
        self.base, self.tries, self.timeout = base, tries, timeout
        self.s = session or requests.Session()
        self.s.headers["User-Agent"] = "wanderers-spaceapps/0.1"
        ad = HTTPAdapter(pool_connections=4, pool_maxsize=pool)
        self.s.mount("https://", ad)
        self.requests = 0
        self.bytes = 0
        self._lock = threading.Lock()

    def _get(self, url, headers=None, params=None, ok=(200, 206)):
        import requests
        err = None
        for k in range(self.tries):
            try:
                r = self.s.get(url, headers=headers, params=params, timeout=self.timeout)
                if r.status_code in ok:
                    with self._lock:
                        self.requests += 1
                        self.bytes += len(r.content)
                    return r
                err = f"HTTP {r.status_code}"
                if r.status_code in (403, 404, 416):
                    break
            except requests.RequestException as e:
                err = type(e).__name__
            time.sleep(min(8.0, 0.5 * 2 ** k))
        raise S3Error(f"S3 {err} for {url[len(self.base):][:120] or 'bucket listing'}")

    def read(self, key, start, stop):
        if stop <= start:
            return b""
        r = self._get(self.base + key, headers={"Range": f"bytes={start}-{stop - 1}"})
        return r.content

    def read_suffix(self, key, n):
        r = self._get(self.base + key, headers={"Range": f"bytes=-{n}"})
        return r.content

    def list(self, prefix, delimiter=None):
        prefixes, keys, token = [], [], None
        while True:
            p = {"list-type": "2", "prefix": prefix}
            if delimiter:
                p["delimiter"] = delimiter
            if token:
                p["continuation-token"] = token
            r = self._get(self.base, params=p, ok=(200,))
            try:
                root = ET.fromstring(r.content)
            except ET.ParseError:
                raise S3Error("S3 listing is not XML") from None
            if not root.tag.endswith("ListBucketResult"):
                raise S3Error(f"unexpected S3 listing ({root.tag})")
            prefixes += [e.text for e in root.findall(f"{S3_NS}CommonPrefixes/{S3_NS}Prefix") if e.text]
            for c in root.findall(S3_NS + "Contents"):
                keys.append((c.find(S3_NS + "Key").text, int(c.find(S3_NS + "Size").text)))
            trunc = root.find(S3_NS + "IsTruncated")
            if trunc is not None and trunc.text == "true":
                token = root.find(S3_NS + "NextContinuationToken").text
            else:
                return prefixes, keys


# ---------------------------------------------------------------- releases and weeks ----------------------------

def release_dir_key(name):
    """Sort key for bucket release folders (dr1, qr2, ...): data releases first, then by number, as
    spherex_releases.release_key orders collection names."""
    m = RELEASE_DIR_RE.match(name)
    return (0 if m.group(1) == "dr" else 1, int(m.group(2)))


def release_folders(reader):
    """Top-level release folders of the bucket ('dr1', 'qr2', 'qr3', ...), oldest first. Other folders are ignored."""
    prefixes, _ = reader.list("", delimiter="/")
    names = {p.strip("/") for p in prefixes}
    return sorted((n for n in names if RELEASE_DIR_RE.match(n)), key=release_dir_key)


def week_key(name):
    m = WEEK_RE.match(name)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4))


def week_folders(reader, release):
    """The half-week folders of <release>/level2/, oldest first ('2026W20_2A', ...)."""
    prefixes, _ = reader.list(f"{release}/level2/", delimiter="/")
    names = {p.rstrip("/").rsplit("/", 1)[-1] for p in prefixes}
    return sorted((n for n in names if WEEK_RE.match(n)), key=week_key)


def week_label(name):
    """'2026W40_2A' -> '2026 week 40'."""
    y, w, _, _ = week_key(name)
    return f"{y} week {w}"


def week_end(name):
    """Last day (Sunday) of the ISO week of a week folder, as YYYY-MM-DD. The folders are ISO weeks: 2026W40_2A holds
    images from 2026-10-01 and 2025W33_2C images from 2025-08-15 (their MJD-OBS)."""
    y, w, _, _ = week_key(name)
    return date.fromisocalendar(y, w, 7).isoformat()


def newest_weeks(reader, releases):
    """{release folder: its newest week folder} (a release with no level2 week is left out)."""
    out = {}
    for rel in releases:
        weeks = week_folders(reader, rel)
        if weeks:
            out[rel] = weeks[-1]
    return out


def list_week(reader, release, week):
    """Every Level-2 image of one week folder: [(key, size)], from all its processing folders."""
    _, keys = reader.list(f"{release}/level2/{week}/")
    return [(k, n) for k, n in keys if FILE_RE.search(k)]


def parse_key(key):
    """(obs_id, detector) from a Level-2 key, or None."""
    m = FILE_RE.search(key)
    return (m.group("obs"), int(m.group("det"))) if m else None


# ---------------------------------------------------------------- FITS headers ----------------------------------

def find_end(buf):
    """Byte offset just after the END card of the header that starts at buf[0], or -1 if buf holds no END yet."""
    for i in range(0, len(buf) - 79, 80):
        if buf[i:i + 8] == b"END     " or (buf[i:i + 3] == b"END" and buf[i + 3:i + 80].strip() == b""):
            return i + 80
    return -1


def header_length(end):
    """Bytes a header takes on disk (whole 2880-byte blocks) given the offset just after its END card."""
    return -(-end // BLOCK) * BLOCK


def padded(n):
    return -(-n // BLOCK) * BLOCK


_NUM = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([EeDd][+-]?\d+)?$")


def parse_cards(buf, want=None):
    """A fast reader for the value cards of one header (bytes up to END): {keyword: value}. Strings are unquoted,
    T/F are booleans, numbers are int or float. HIERARCH cards give their long keyword (SPS_FLAGS); COMMENT and
    HISTORY are skipped. With `want` (a callable), only keywords it accepts are converted. About 10x faster than
    astropy's Header for the ~300-card SPHEREx headers, which matters for 100,000s of them."""
    out = {}
    for i in range(0, len(buf) - 79, 80):
        card = buf[i:i + 80]
        if card[:9] == b"HIERARCH " and b"=" in card:          # HIERARCH SPS_FLAGS = 'all_sky ' / ...
            k, _, rest = card[9:].decode("ascii", "replace").partition("=")
            k = k.strip()
            if want is not None and not want(k):
                continue
            v = rest.strip()
        elif card[8:10] != b"= ":
            if card[:3] == b"END" and card[3:].strip() == b"":
                break
            continue
        else:
            k = card[:8].decode("ascii", "replace").strip()
            if want is not None and not want(k):
                continue
            v = card[10:].decode("ascii", "replace").strip()
        if v.startswith("'"):
            j, s = 1, []
            while j < len(v):
                if v[j] == "'":
                    if v[j + 1:j + 2] == "'":
                        s.append("'")
                        j += 2
                        continue
                    break
                s.append(v[j])
                j += 1
            out[k] = "".join(s).rstrip()
            continue
        v = v.split("/", 1)[0].strip()
        if v in ("T", "F"):
            out[k] = v == "T"
        elif _NUM.match(v):
            v = v.replace("D", "E").replace("d", "e")
            out[k] = int(v) if re.fullmatch(r"[+-]?\d+", v) else float(v)
        else:
            out[k] = v
    return out


_WCS_WANT = re.compile(r"^(NAXIS[12]|CRPIX[12]|CRVAL[12]|CDELT[12]|PC[12]_[12]|CD[12]_[12]|CTYPE[12]|[AB]_ORDER|"
                       r"[AB]_\d_\d|DETECTOR|OBSID|MJD-OBS|MJD-BEG|MJD-END|MJD-AVG|EXTNAME|SPS_FLAGS|XTENSION|"
                       r"BITPIX|LONPOLE)$")


def head_cards(buf):
    """(primary cards, IMAGE cards, IMAGE header length, IMAGE header offset) from the first bytes of a Level-2 file.
    Raises ValueError when the bytes do not hold both headers (read more)."""
    e0 = find_end(buf)
    if e0 < 0:
        raise ValueError("no END in the primary header")
    h0 = header_length(e0)
    e1 = find_end(buf[h0:])
    if e1 < 0:
        raise ValueError("no END in the IMAGE header")
    prim = parse_cards(buf[:e0])
    img = parse_cards(buf[h0:h0 + e1], want=lambda k: _WCS_WANT.match(k) is not None)
    return prim, img, header_length(e1), h0


# ---------------------------------------------------------------- sky geometry ----------------------------------

def sip_tan_pix2world(c, x, y):
    """0-based pixel coordinates -> (ra, dec) in degrees with the header's TAN projection and SIP distortion (the
    forward A/B polynomials), as astropy's all_pix2world does. `c` is a dict of header cards."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    u = x + 1.0 - c["CRPIX1"]
    v = y + 1.0 - c["CRPIX2"]
    fu, fv = np.zeros_like(u), np.zeros_like(v)
    for name, acc in (("A", fu), ("B", fv)):
        order = int(c.get(f"{name}_ORDER", 0) or 0)
        for p in range(order + 1):
            for q in range(order + 1 - p):
                coef = c.get(f"{name}_{p}_{q}")
                if coef:
                    acc += coef * u ** p * v ** q
    u, v = u + fu, v + fv
    if "CD1_1" in c:
        cd = np.array([[c.get("CD1_1", 0.0), c.get("CD1_2", 0.0)], [c.get("CD2_1", 0.0), c.get("CD2_2", 0.0)]])
    else:
        pc = np.array([[c.get("PC1_1", 1.0), c.get("PC1_2", 0.0)], [c.get("PC2_1", 0.0), c.get("PC2_2", 1.0)]])
        cd = pc * np.array([[c.get("CDELT1", 1.0)], [c.get("CDELT2", 1.0)]])
    xi = np.radians(cd[0, 0] * u + cd[0, 1] * v)
    eta = np.radians(cd[1, 0] * u + cd[1, 1] * v)
    a0, d0 = math.radians(c["CRVAL1"]), math.radians(c["CRVAL2"])
    den = math.cos(d0) - eta * math.sin(d0)
    ra = np.degrees(a0 + np.arctan2(xi, den)) % 360.0
    dec = np.degrees(np.arctan2(math.sin(d0) + eta * math.cos(d0), np.hypot(xi, den)))
    return ra, dec


def footprint(c):
    """(centre ra, centre dec, 8 boundary points [[ra, dec], ...]) of an image, from its header cards. The points are
    the corners and edge midpoints of the outer pixel edges, going round the image."""
    nx, ny = c.get("NAXIS1", 2040), c.get("NAXIS2", 2040)
    lo_x, hi_x, mid_x = -0.5, nx - 0.5, (nx - 1) / 2
    lo_y, hi_y, mid_y = -0.5, ny - 0.5, (ny - 1) / 2
    px = [lo_x, mid_x, hi_x, hi_x, hi_x, mid_x, lo_x, lo_x]
    py = [lo_y, lo_y, lo_y, mid_y, hi_y, hi_y, hi_y, mid_y]
    ra, dec = sip_tan_pix2world(c, px + [mid_x], py + [mid_y])
    pts = [[round(float(a), 5), round(float(d), 5)] for a, d in zip(ra[:-1], dec[:-1])]
    return round(float(ra[-1]), 6), round(float(dec[-1]), 6), pts


def unit(ra, dec):
    ra, dec = np.radians(ra), np.radians(dec)
    return np.stack([np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)], axis=-1)


def tangent(ra0, dec0, ra, dec):
    """Gnomonic (TAN) projection of (ra, dec) about (ra0, dec0), in degrees on the tangent plane, and cos(distance).
    Works across RA 0/360 and near the poles: it uses only angle differences and unit vectors."""
    a0, d0 = math.radians(ra0), math.radians(dec0)
    a, d = np.radians(np.asarray(ra, float)), np.radians(np.asarray(dec, float))
    cosc = math.sin(d0) * np.sin(d) + math.cos(d0) * np.cos(d) * np.cos(a - a0)
    with np.errstate(divide="ignore", invalid="ignore"):
        xi = np.cos(d) * np.sin(a - a0) / cosc
        eta = (math.cos(d0) * np.sin(d) - math.sin(d0) * np.cos(d) * np.cos(a - a0)) / cosc
    return np.degrees(xi), np.degrees(eta), cosc


def _inside(px, py, xs, ys):
    """Point in polygon (even-odd rule)."""
    inside = False
    n = len(xs)
    j = n - 1
    for i in range(n):
        if (ys[i] > py) != (ys[j] > py):
            x_cross = xs[i] + (py - ys[i]) * (xs[j] - xs[i]) / (ys[j] - ys[i])
            if px < x_cross:
                inside = not inside
        j = i
    return inside


def _edge_distance(px, py, xs, ys):
    best = float("inf")
    n = len(xs)
    for i in range(n):
        x1, y1, x2, y2 = xs[i], ys[i], xs[(i + 1) % n], ys[(i + 1) % n]
        dx, dy = x2 - x1, y2 - y1
        t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
        best = min(best, math.hypot(px - (x1 + t * dx), py - (y1 + t * dy)))
    return best


def covers(rec, ra, dec, margin_deg=0.0):
    """True when (ra, dec) lies inside the image footprint of an index record, or within margin_deg of its edge."""
    xs, ys, cosc = tangent(rec["ra"], rec["dec"], [p[0] for p in rec["corners"]], [p[1] for p in rec["corners"]])
    if np.any(cosc <= 0):
        return False
    tx, ty, tc = tangent(rec["ra"], rec["dec"], ra, dec)
    if float(tc) <= 0.1:                    # more than ~84 degrees from the image centre
        return False
    tx, ty = float(tx), float(ty)
    if _inside(tx, ty, list(xs), list(ys)):
        return True
    return margin_deg > 0 and _edge_distance(tx, ty, list(xs), list(ys)) <= margin_deg


def separation_deg(ra1, dec1, ra2, dec2):
    """Angular distance in degrees (arrays broadcast). Vincenty's formula: exact for tiny and large separations."""
    a1, d1, a2, d2 = (np.radians(np.asarray(v, float)) for v in (ra1, dec1, ra2, dec2))
    da = a2 - a1
    num = np.hypot(np.cos(d2) * np.sin(da), np.cos(d1) * np.sin(d2) - np.sin(d1) * np.cos(d2) * np.cos(da))
    den = np.sin(d1) * np.sin(d2) + np.cos(d1) * np.cos(d2) * np.cos(da)
    return np.degrees(np.arctan2(num, den))


def jyear(mjd):
    """Julian year of an MJD, as astropy's Time(mjd, format='mjd').jyear."""
    return 2000.0 + (float(mjd) - 51544.5) / 365.25


# ---------------------------------------------------------------- the index -------------------------------------

def index_record(key, size, buf, release, week):
    """One index record from the first bytes of a Level-2 file (key, size from the listing)."""
    prim, c, _, _ = head_cards(buf)
    if c.get("EXTNAME") != "IMAGE":
        raise ValueError(f"second HDU is {c.get('EXTNAME')!r}, not IMAGE")
    if not str(c.get("CTYPE1", "")).startswith("RA---TAN"):
        raise ValueError(f"unexpected projection {c.get('CTYPE1')!r}")
    ra, dec, pts = footprint(c)
    det = int(c.get("DETECTOR") or parse_key(key)[1])
    mjd = c.get("MJD-BEG", c.get("MJD-OBS"))
    obs = c.get("OBSID") or parse_key(key)[0]
    lo, hi = DETECTOR_BANDS.get(det, (None, None))
    return {"key": key, "release": release, "week": week, "obs_id": obs, "detector": det, "mjd": mjd,
            "mjd_end": c.get("MJD-END"), "ra": ra, "dec": dec, "corners": pts, "em_min": lo, "em_max": hi,
            "naxis1": c.get("NAXIS1"), "naxis2": c.get("NAXIS2"), "sps_flags": c.get("SPS_FLAGS"), "size": size,
            "inferred_from": None}


def partner_record(rec, key, size):
    """The record of the dichroic partner of an indexed image: same exposure, same sky, its own key and band."""
    det = PAIRS[rec["detector"]]
    lo, hi = DETECTOR_BANDS[det]
    return {**rec, "key": key, "detector": det, "em_min": lo, "em_max": hi, "size": size, "inferred_from": rec["key"]}


def read_head(reader, key, nblocks=HEAD_BLOCKS):
    """The first bytes of a file, enough for the primary and IMAGE headers (reads more if a header is longer)."""
    buf = reader.read(key, 0, nblocks * BLOCK)
    for _ in range(4):
        try:
            head_cards(buf)
            return buf
        except ValueError:
            more = reader.read(key, len(buf), len(buf) + 8 * BLOCK)
            if not more:
                break
            buf += more
    head_cards(buf)
    return buf


def index_path(release, root=None):
    return Path(root or INDEX_DIR) / f"{release}.jsonl"


def state_path(release, root=None):
    return Path(root or INDEX_DIR) / f"{release}.state.json"


def open_for_append(path):
    """Open the index for appending lines. A run killed mid-write can leave a last line without its newline: end it
    first, so the next record starts on a line of its own (load_index skips the broken one)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a", encoding="utf-8")
    if path.stat().st_size:
        with open(path, "rb") as r:
            r.seek(-1, os.SEEK_END)
            if r.read(1) != b"\n":
                fh.write("\n")
    return fh


_CENTRE = re.compile(rb'"ra":(-?[0-9.eE+-]+),"dec":(-?[0-9.eE+-]+)')
_KEY = re.compile(rb'^\{"key":"([^"]+)"')


def load_index(release, root=None, near=None):
    """The index records of a release, one per key (later lines win). A broken line (a run killed mid-write) is
    skipped. near=(ra, dec, radius_deg) keeps only images whose centre is that close: the full QR3 index has about
    430,000 lines, so the centres are read with a regular expression first and only nearby lines are parsed (a few
    seconds and a few MB instead of a minute and a GB)."""
    p = index_path(release, root)
    recs = {}
    if not p.exists():
        return []
    with open(p, "rb") as fh:
        lines = fh.readlines()
    if near is not None:
        ras, decs, keep = [], [], []
        for i, line in enumerate(lines):
            m = _CENTRE.search(line)
            if m:
                ras.append(float(m.group(1)))
                decs.append(float(m.group(2)))
                keep.append(i)
        if not keep:
            return []
        d = separation_deg(np.array(ras), np.array(decs), near[0], near[1])
        lines = [lines[keep[j]] for j in np.nonzero(d <= near[2])[0]]
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("key"):
            recs[r["key"]] = r
    return list(recs.values())


def indexed_keys(release, root=None):
    """The keys already in the index (without parsing every record)."""
    p = index_path(release, root)
    if not p.exists():
        return set()
    with open(p, "rb") as fh:
        return {m.group(1).decode() for m in map(_KEY.match, fh) if m}


def load_state(release, root=None):
    try:
        s = json.loads(state_path(release, root).read_text(encoding="utf-8"))
        return s if isinstance(s, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(release, state, root=None):
    p = state_path(release, root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def plan_reads(keys, detectors, infer_pairs):
    """Which files of a week to read headers from: {key: size} to read, and {key read: [(partner key, size)]} whose
    footprint is inferred from it. With infer_pairs, an exposure's detector 1-3 is read and 4-6 inherit it; when
    the 1-3 file is missing (it can be in another processing folder, or absent), the 4-6 file is read itself."""
    detectors = set(detectors)
    by = {}
    for k, n in keys:
        p = parse_key(k)
        if p and p[1] in detectors | ({PAIRS[d] for d in detectors} if infer_pairs else set()):
            by[p] = (k, n)
    reads, inferred = {}, {}
    for (obs, det), (k, n) in sorted(by.items()):
        if not infer_pairs:
            if det in detectors:
                reads[k] = n
            continue
        partner = by.get((obs, PAIRS[det]))
        if det <= 3:
            if det in detectors or (partner and PAIRS[det] in detectors):
                reads[k] = n
                if partner and PAIRS[det] in detectors:
                    inferred.setdefault(k, []).append(partner)
        elif partner is None and det in detectors:
            reads[k] = n                      # a 4-6 image whose 1-3 partner is not in the bucket
    return reads, inferred


def build_index(reader, release, weeks=None, detectors=(1, 2, 3, 4, 5, 6), infer_pairs=True, workers=48,
                root=None, log=log_default, relist=False, max_seconds=None):
    """Read the headers of every image of `weeks` (default: all weeks of the release) and append one record per image
    to data/cache/spherex_s3_index/<release>.jsonl. Resumable: images already indexed are skipped, weeks finished
    earlier are not listed again (unless relist). Returns a summary dict (counts, seconds, bytes, file size)."""
    t0 = time.time()
    req0, bytes0 = getattr(reader, "requests", 0), getattr(reader, "bytes", 0)
    out = index_path(release, root)
    out.parent.mkdir(parents=True, exist_ok=True)
    have = indexed_keys(release, root)
    state = load_state(release, root)
    done_weeks = state.setdefault("complete_weeks", {})
    failed = state.setdefault("failed", {})
    all_weeks = week_folders(reader, release) if weeks is None else list(weeks)
    det_tag = ",".join(map(str, sorted(detectors)))
    stats = {"release": release, "weeks": len(all_weeks), "listed": 0, "read": 0, "inferred": 0, "skipped": 0,
             "failed": 0, "weeks_skipped": 0}
    lock = threading.Lock()
    with open_for_append(out) as fh:
        for week in all_weeks:
            if not relist and det_tag in done_weeks.get(week, {}).get("detectors", []):
                stats["weeks_skipped"] += 1
                continue
            keys = list_week(reader, release, week)
            stats["listed"] += len(keys)
            reads, inferred = plan_reads(keys, detectors, infer_pairs)
            todo = {k: n for k, n in reads.items()
                    if k not in have or any(pk not in have for pk, _ in inferred.get(k, []))}
            stats["skipped"] += len(reads) - len(todo)
            ok_week = True

            def one(k):
                return k, index_record(k, todo[k], read_head(reader, k), release, week)

            n_done = 0
            with ThreadPoolExecutor(max(1, workers)) as ex:
                futs = [ex.submit(one, k) for k in todo]
                for f in as_completed(futs):
                    try:
                        k, rec = f.result()
                    except Exception as e:  # noqa: BLE001 - one bad file must not stop the index
                        ok_week = False
                        stats["failed"] += 1
                        with lock:
                            failed[str(e)[:80]] = failed.get(str(e)[:80], 0) + 1
                        continue
                    lines = []
                    if k not in have:
                        lines.append(rec)
                    for pk, pn in inferred.get(k, []):
                        if pk not in have:
                            lines.append(partner_record(rec, pk, pn))
                            stats["inferred"] += 1
                    for r in lines:
                        fh.write(json.dumps(r, separators=(",", ":")) + "\n")
                        have.add(r["key"])
                    stats["read"] += 1
                    n_done += 1
                    if n_done % 500 == 0:
                        fh.flush()
                        log(f"   {release} {week}: {n_done}/{len(todo)} headers")
                    if max_seconds and time.time() - t0 > max_seconds:
                        for g in futs:
                            g.cancel()
                        ok_week = False
            fh.flush()
            if ok_week:
                rec = done_weeks.setdefault(week, {"detectors": []})
                rec["files"] = len(keys)
                if det_tag not in rec["detectors"]:
                    rec["detectors"].append(det_tag)
            save_state(release, state, root)
            log(f"   {release} {week}: {len(keys)} files listed, {len(todo)} headers read"
                f"{'' if ok_week else ' (incomplete: run again to finish)'}")
            if max_seconds and time.time() - t0 > max_seconds:
                break
    stats["seconds"] = round(time.time() - t0, 1)
    stats["requests"] = getattr(reader, "requests", 0) - req0
    stats["bytes_read"] = getattr(reader, "bytes", 0) - bytes0
    stats["records"] = len(have)
    stats["index_bytes"] = out.stat().st_size if out.exists() else 0
    state["last_run"] = {**stats, "finished": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    save_state(release, state, root)
    return stats


# ---------------------------------------------------------------- searching the index ---------------------------

def candidates(index, ra, dec, radius_deg=3.0):
    """Records whose centre is within radius_deg of (ra, dec): a cheap first cut before the exact footprint test (an
    image is 3.5 x 3.5 deg, so every image that covers a point has its centre within 2.6 deg of it)."""
    if not index:
        return []
    ras = np.array([r["ra"] for r in index], float)
    decs = np.array([r["dec"] for r in index], float)
    d = separation_deg(ras, decs, ra, dec)
    return [index[i] for i in np.nonzero(d <= radius_deg)[0]]


def in_survey(rec, survey="all_sky"):
    """True when an image was planned for `survey` (header SPS_FLAGS, e.g. 'all_sky' or 'all_sky,downlink').

    IRSA's spherex_dr1 / spherex_qr3 SIA collections are the wide survey; deep-field images ('deep_north',
    'deep_south') are in the separate *_deep collections, which fetch.py does not search. Checked on 2026-11-15: 40
    sampled S3 headers each of the images IRSA SIA had listed for R Dra (spherex_dr1, inside the north deep-field
    coverage) and for two other targets (spherex_qr3) all say all_sky (one 'all_sky,downlink')."""
    if survey is None:
        return True
    return survey in [s.strip() for s in str(rec.get("sps_flags") or "").split(",")]


def refine_inferred(reader, records, release, root=None, workers=16):
    """Replace inferred records (dichroic partner footprints) by exact ones read from each file's own header, and
    append the exact records to the index so the next search need not read them again."""
    todo = [r for r in records if r.get("inferred_from")]
    if not todo:
        return list(records)

    def one(r):
        return index_record(r["key"], r.get("size"), read_head(reader, r["key"]), r["release"], r["week"])

    with ThreadPoolExecutor(max(1, workers)) as ex:
        exact = dict(zip([r["key"] for r in todo], ex.map(one, todo)))
    p = index_path(release, root)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open_for_append(p) as fh:
        for rec in exact.values():
            fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
    return [exact.get(r["key"], r) for r in records]


def search(index, at, ra, dec, margin_deg=SIA_RADIUS_DEG, survey="all_sky", reader=None, release=None, root=None):
    """Index records whose footprint holds the target at that image's own time.

    at(mjd) -> (ra, dec) of the target at that MJD (fetch.py's predict() on the target's reference); (ra, dec) is a
    rough position for the first cut. margin_deg: a footprint edge this close still counts (fetch.py's SIA circle).
    survey: keep only images of that survey (in_survey). An inferred footprint (dichroic partner) first gets
    PAIR_MARGIN_DEG more margin; with a reader, those images' own headers are then read (refine_inferred) and tested
    exactly, so nothing is chosen on an inferred footprint."""
    first = []
    for r in candidates(index, ra, dec):
        if not in_survey(r, survey):
            continue
        tra, tdec = at(r["mjd"])
        m = margin_deg + (PAIR_MARGIN_DEG if r.get("inferred_from") else 0.0)
        if covers(r, tra, tdec, m):
            first.append((r, tra, tdec))
    if reader is not None and any(r.get("inferred_from") for r, _, _ in first):
        exact = refine_inferred(reader, [r for r, _, _ in first], release or first[0][0]["release"], root=root)
        first = [(e, tra, tdec) for e, (_, tra, tdec) in zip(exact, first)]
    out = [r for r, tra, tdec in first if (r.get("inferred_from") and reader is None) or covers(r, tra, tdec, margin_deg)]
    return sorted(out, key=lambda r: (r["mjd"], r["detector"], r["key"]))


def sia_like_rows(records, release):
    """Index records as rows with the SIA columns fetch.py uses (access_url, t_min, energy_bandpassname, obs_id,
    dataproduct_subtype, cloud_access, ...), as a list of dicts."""
    coll = f"spherex_{release}"
    rows = []
    for r in records:
        poly = " ".join(f"{a} {d}" for a, d in r["corners"][::2])
        rows.append({
            "access_url": IRSA_DATA_URL + r["key"], "t_min": float(r["mjd"]),
            "t_max": float(r["mjd_end"] if r.get("mjd_end") is not None else r["mjd"]),
            "energy_bandpassname": f"SPHEREx-D{r['detector']}", "obs_id": r["obs_id"],
            "dataproduct_subtype": "science", "dataproduct_type": "image", "calib_level": 2,
            "em_min": r["em_min"], "em_max": r["em_max"], "obs_collection": coll,
            "cloud_access": json.dumps({"aws": {"bucket_name": BUCKET, "key": r["key"], "region": REGION}}),
            "s_region": f"POLYGON ICRS {poly}"})
    return rows


def index_coverage(release, root=None):
    """The week folders of a release whose every image (all six detectors) is in the index, oldest first."""
    st = load_state(release, root)
    return sorted((w for w, v in (st.get("complete_weeks") or {}).items()
                   if "1,2,3,4,5,6" in (v.get("detectors") or [])), key=week_key)


def search_answer(release, records, bucket_weeks, indexed_weeks, position, searched, margin_deg=SIA_RADIUS_DEG):
    """The small JSON fetch.py saves as data/cache/<target>/spherex_<release>_s3.json: which images the S3 index gave
    for a target, and whether the index covered every week folder of the release (only then does
    pipeline/spherex_releases.py count the target as searched in that release)."""
    missing = sorted(set(bucket_weeks) - set(indexed_weeks), key=week_key)
    return {
        "about": "SPHEREx images found in NASA IRSA's S3 bucket (IRSA SIA did not answer): footprints from the FITS "
                 "headers (pipeline/spherex_s3.py index), target at each image's own time (fetch.py predict()).",
        "release": f"spherex_{release}", "searched": searched, "source": f"s3://{BUCKET}/{release}/level2/",
        "index": f"data/cache/spherex_s3_index/{release}.jsonl", "survey": "all_sky (SPS_FLAGS)",
        "margin_deg": margin_deg, "position": position,
        "bucket_weeks": len(bucket_weeks), "indexed_weeks": len([w for w in bucket_weeks if w in set(indexed_weeks)]),
        "newest_week": bucket_weeks[-1] if bucket_weeks else None, "missing_weeks": missing,
        "index_complete": bool(bucket_weeks) and not missing,
        "images": [{"key": r["key"], "obs_id": r["obs_id"], "detector": r["detector"], "t_min": r["mjd"]}
                   for r in records]}


# ---------------------------------------------------------------- cutouts ---------------------------------------

def cutout_box(px, py, size, nx, ny):
    """Pixel box (x0, x1, y0, y1), 0-based and end-exclusive, of a size x size cutout around 0-based pixel (px, py),
    clipped to the nx x ny image. None when the box misses the image.

    IRSA's cutout service puts floor(px) at index size//2 - 1 of the box: checked on cached IRSA cutouts, whose
    CRPIX1A/CRPIX2A give their origin (1 - CRPIXnA), and SIP-aware all_world2pix positions (px - x0 is always
    in [size/2 - 1, size/2) there, for size 52)."""
    if not (np.isfinite(px) and np.isfinite(py)):
        return None
    x0 = int(math.floor(px)) - (size // 2 - 1)
    y0 = int(math.floor(py)) - (size // 2 - 1)
    x1, y1 = x0 + size, y0 + size
    x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, nx), min(y1, ny)
    if x0 >= x1 or y0 >= y1:
        return None
    return x0, x1, y0, y1


def shift_header(h, x0, y0, nx, ny):
    """A full-image header made into a cutout header the way IRSA's cutout service does it: NAXIS1/2 become the
    cutout size and the reference pixels of the sky WCS, the 'A' (0-based pixel) and 'W' (wavelength lookup) WCS
    move by the cutout origin. Nothing else changes."""
    h = h.copy()
    h["NAXIS1"], h["NAXIS2"] = nx, ny
    for suffix in ("", "A", "W"):
        for ax, off in (("1", x0), ("2", y0)):
            k = f"CRPIX{ax}{suffix}"
            if k in h:
                h[k] = float(h[k]) - off
    return h


def _header(buf):
    from astropy.io import fits
    e = find_end(buf)
    if e < 0:
        raise ValueError("no END card")
    return fits.Header.fromstring(buf[:e].decode("ascii")), header_length(e)


def _read_header_at(reader, key, offset, first=4 * BLOCK, extra=b""):
    """(header, header length, bytes read from offset) for the header that starts at `offset`."""
    buf = extra or reader.read(key, offset, offset + first)
    while find_end(buf) < 0:
        more = reader.read(key, offset + len(buf), offset + len(buf) + 8 * BLOCK)
        if not more:
            raise ValueError(f"no END card for the header at byte {offset}")
        buf += more
    h, n = _header(buf)
    return h, n, buf


def data_size(h):
    """Bytes of the data unit (unpadded) described by a header."""
    nax = h.get("NAXIS", 0)
    if not nax:
        return 0
    n = abs(h["BITPIX"]) // 8
    for i in range(1, nax + 1):
        n *= h[f"NAXIS{i}"]
    return h.get("GCOUNT", 1) * (h.get("PCOUNT", 0) + n)


def _rows(reader, key, data_off, h, y0, y1, x0, x1):
    """Rows y0..y1 (columns x0..x1) of an uncompressed 2-D image HDU whose data starts at data_off."""
    nx, ny = h["NAXIS1"], h["NAXIS2"]
    item = abs(h["BITPIX"]) // 8
    dt = {-32: ">f4", -64: ">f8", 32: ">i4", 16: ">i2", 8: "u1", 64: ">i8"}[h["BITPIX"]]
    if not (0 <= y0 < y1 <= ny and 0 <= x0 < x1 <= nx):
        raise ValueError("section outside the image")
    raw = reader.read(key, data_off + y0 * nx * item, data_off + y1 * nx * item)
    if len(raw) != (y1 - y0) * nx * item:
        raise ValueError("short read")
    return np.frombuffer(raw, dtype=dt).reshape(y1 - y0, nx)[:, x0:x1].copy()


def _compressed_rows(reader, key, off, h, hlen, buf, y0, y1, x0, x1):
    """(image header, rows y0..y1 / columns x0..x1) of a tile-compressed image (FLAGS) with one tile per row.

    Reads the row descriptors, then the compressed bytes of only those rows, and lets astropy decompress them as a
    small compressed HDU of y1 - y0 rows, so every compression detail (RICE_1, BLANK, scaling) is astropy's."""
    from astropy.io import fits
    if not h.get("ZIMAGE"):
        raise ValueError("not a compressed image")
    if h.get("ZTILE2", 1) != 1 or h.get("ZTILE1", h["ZNAXIS1"]) != h["ZNAXIS1"] or h.get("ZNAXIS", 2) != 2:
        raise ValueError("FLAGS is not compressed one row per tile")
    tform = str(h["TFORM1"]).upper()
    if "Q" in tform:
        desc_dt, desc_size = ">i8", 16
    elif "P" in tform:
        desc_dt, desc_size = ">i4", 8
    else:
        raise ValueError(f"unexpected FLAGS column {tform}")
    if h["TFIELDS"] != 1 or h["NAXIS1"] != desc_size:
        raise ValueError("FLAGS table has more than the compressed-data column")
    table_off = off + hlen
    need = table_off + y1 * desc_size
    if off + len(buf) >= need:
        raw = buf[table_off - off + y0 * desc_size: table_off - off + y1 * desc_size]
    else:
        raw = reader.read(key, table_off + y0 * desc_size, need)
    desc = np.frombuffer(raw, dtype=desc_dt).reshape(-1, 2).astype(np.int64)
    heap0 = table_off + int(h.get("THEAP", h["NAXIS1"] * h["NAXIS2"]))
    lo, hi = int(desc[:, 1].min()), int((desc[:, 1] + desc[:, 0]).max())
    heap = reader.read(key, heap0 + lo, heap0 + hi)
    n = y1 - y0
    new = desc.copy()
    new[:, 1] -= lo
    hh = h.copy()
    hh["NAXIS2"] = n
    hh["ZNAXIS2"] = n
    hh["PCOUNT"] = hi - lo
    if "THEAP" in hh:
        hh["THEAP"] = desc_size * n
    table = new.astype(desc_dt).tobytes()
    blob = (fits.PrimaryHDU().header.tostring().encode("ascii") + hh.tostring().encode("ascii")
            + table + heap)
    blob += b"\0" * (padded(len(blob)) - len(blob))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with fits.open(io.BytesIO(blob)) as hd:
            comp = hd[1]
            data = np.asarray(comp.data)[:, x0:x1].copy()
            ih = comp.header.copy()
    ih["NAXIS2"] = h["ZNAXIS2"]
    return ih, data


def _wcs_wave(reader, key, size=None):
    """The WCS-WAVE table HDU as (header, data bytes), from the end of the file, or None if it is not the last HDU."""
    tail = reader.read_suffix(key, 4 * BLOCK)
    for i in range(len(tail) - BLOCK, -1, -BLOCK):
        blk = tail[i:]
        if blk.startswith(b"XTENSION= 'BINTABLE'"):
            e = find_end(blk)
            if e < 0:
                continue
            try:
                h, hl = _header(blk)
            except Exception:  # noqa: BLE001
                continue
            if h.get("EXTNAME") == "WCS-WAVE":
                n = data_size(h)
                return h, blk[hl:hl + n]
    return None


def cutout(reader, key, ra, dec, size_px, keep=("IMAGE", "FLAGS", "VARIANCE", "WCS-WAVE")):
    """A size_px x size_px cutout around (ra, dec) of one Level-2 file on S3, as FITS bytes with the PRIMARY, IMAGE,
    FLAGS, VARIANCE and WCS-WAVE HDUs that pipeline/fetch.py keeps from an IRSA cutout. None when the box misses the
    image. Reads the headers, then only the needed rows of each image, with HTTP Range requests."""
    return cutout_section(reader, key, box_for=lambda w, nx, ny: cutout_box(*_world2pix(w, ra, dec), size_px, nx, ny),
                          keep=keep)


_ALT_W = re.compile(r"^(WCSAXESW|WCSNAMEW|CNAME\dW|C[A-Z]+\dW|PS\d_\dW|PV\d_\dW)$")


def sky_header(h):
    """The header without its 'W' alternate WCS (the WAVE-TAB wavelength lookup, which needs the WCS-WAVE table to
    be parsed), for astropy's celestial WCS. The sky WCS and its SIP terms are untouched."""
    h = h.copy()
    for k in [k for k in h.keys() if _ALT_W.match(k)]:
        del h[k]
    return h


def _world2pix(w, ra, dec):
    x, y = w.all_world2pix(ra, dec, 0, quiet=True)
    return float(x), float(y)


def cutout_section(reader, key, box_for, keep=("IMAGE", "FLAGS", "VARIANCE", "WCS-WAVE")):
    """Like cutout(), with the pixel box chosen by box_for(wcs, nx, ny) -> (x0, x1, y0, y1) or None."""
    from astropy.io import fits
    from astropy.wcs import WCS
    head = read_head(reader, key)
    p_end = find_end(head)
    prim = fits.Header.fromstring(head[:p_end].decode("ascii"))
    off = header_length(p_end)
    img_h, img_hl = _header(head[off:])
    if img_h.get("EXTNAME") != "IMAGE":
        raise ValueError(f"{key}: second HDU is {img_h.get('EXTNAME')!r}")
    nx, ny = img_h["NAXIS1"], img_h["NAXIS2"]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        w = WCS(sky_header(img_h))
    box = box_for(w, nx, ny)
    if box is None:
        return None
    x0, x1, y0, y1 = box
    hdus = [fits.PrimaryHDU(header=prim)]
    img_data_off = off + img_hl
    sections = {"IMAGE": (shift_header(img_h, x0, y0, x1 - x0, y1 - y0),
                          _rows(reader, key, img_data_off, img_h, y0, y1, x0, x1))}
    pos = img_data_off + padded(data_size(img_h))
    need = [n for n in keep if n not in ("IMAGE", "WCS-WAVE")]
    while need:
        h, hl, buf = _read_header_at(reader, key, pos, first=12 * BLOCK)
        name = h.get("EXTNAME")
        if name in need:
            if h.get("ZIMAGE"):
                ih, data = _compressed_rows(reader, key, pos, h, hl, buf, y0, y1, x0, x1)
            else:
                ih, data = h, _rows(reader, key, pos + hl, h, y0, y1, x0, x1)
            sections[name] = (shift_header(ih, x0, y0, x1 - x0, y1 - y0), data)
            need.remove(name)
        pos += hl + padded(data_size(h))
    for name in keep:
        if name == "WCS-WAVE":
            ww = _wcs_wave(reader, key)
            if ww is not None:
                wh, wdata = ww
                raw = wh.tostring().encode("ascii") + wdata + b"\0" * (padded(len(wdata)) - len(wdata))
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    tb = fits.open(io.BytesIO(fits.PrimaryHDU().header.tostring().encode("ascii") + raw))
                    hdus.append(fits.BinTableHDU(data=tb[1].data.copy(), header=tb[1].header.copy()))
                    tb.close()
        elif name in sections:
            hdr, data = sections[name]
            hdus.append(fits.ImageHDU(data=data, header=hdr))
    buf = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fits.HDUList(hdus).writeto(buf)
    return buf.getvalue()


# ---------------------------------------------------------------- command line ----------------------------------

def _cli_releases(reader):
    rels = release_folders(reader)
    weeks = newest_weeks(reader, rels)
    for r in rels:
        w = weeks.get(r)
        print(f"{r}: newest week {w} ({week_label(w)}, ISO week ends {week_end(w)})" if w else f"{r}: no level2 weeks")


def check_pairs(reader, release, weeks, per_week=3, seed=1, log=log_default):
    """Read all six detectors' headers of a few exposures per week and measure how far each dichroic partner's
    footprint is from its 1-3 detector (the numbers behind PAIR_CHECK). Returns a summary dict."""
    import random
    rng = random.Random(seed)
    worst, means, dmjd, n = 0.0, [], 0.0, 0
    for week in weeks:
        by = {}
        for k, _ in list_week(reader, release, week):
            o, d = parse_key(k)
            by.setdefault(o, {})[d] = k
        full = sorted(o for o, v in by.items() if len(v) == 6)
        for o in rng.sample(full, min(per_week, len(full))):
            cards = {d: head_cards(read_head(reader, by[o][d]))[1] for d in range(1, 7)}
            for a in (1, 2, 3):
                pa, pb = np.array(footprint(cards[a])[2]), np.array(footprint(cards[PAIRS[a]])[2])
                sep = separation_deg(pa[:, 0], pa[:, 1], pb[:, 0], pb[:, 1]) * 3600
                worst, n = max(worst, float(sep.max())), n + 1
                means.append(float(sep.mean()))
                dmjd = max(dmjd, abs(cards[a]["MJD-BEG"] - cards[PAIRS[a]]["MJD-BEG"]) * 86400)
                log(f"   {o} D{a}/D{PAIRS[a]}: mean {sep.mean():.1f}\", max {sep.max():.1f}\"")
    return {"pairs": n, "max_offset_arcsec": round(worst, 1),
            "mean_offset_arcsec": [round(min(means), 1), round(max(means), 1)] if means else None,
            "max_mjd_difference_s": round(dmjd, 3)}


def _cli_search(reader, tid, release):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import fetch
    ref = json.loads((CACHE / tid / "gaia.json").read_text())["ref"]
    c = fetch.predict(ref, 2025.9)

    def at(mjd):
        p = fetch.predict(ref, jyear(mjd))
        return p.ra.deg, p.dec.deg
    recs = search(load_index(release), at, c.ra.deg, c.dec.deg, reader=reader, release=release)
    for r in recs:
        print(f"{r['mjd']:.5f}  D{r['detector']}  {r['obs_id']}  {r['key']}")
    print(f"{len(recs)} images; weeks {sorted({r['week'] for r in recs}, key=week_key)}")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("releases")
    a_s = sub.add_parser("search")
    a_s.add_argument("target")
    a_s.add_argument("--release", default="qr3")
    a_p = sub.add_parser("pairs")
    a_p.add_argument("release")
    a_p.add_argument("weeks")
    a_idx = sub.add_parser("index")
    a_idx.add_argument("release")
    a_idx.add_argument("--weeks", default=None, help="comma-separated week folders (default: all)")
    a_idx.add_argument("--detectors", default="1,2,3,4,5,6")
    a_idx.add_argument("--no-pairs", action="store_true", help="read every detector's header (no dichroic inference)")
    a_idx.add_argument("--workers", type=int, default=48)
    a_idx.add_argument("--max-seconds", type=float, default=None)
    a = p.parse_args(argv)
    reader = S3Reader(pool=max(64, getattr(a, "workers", 0) or 0))
    if a.cmd == "releases":
        _cli_releases(reader)
        return 0
    if a.cmd == "search":
        _cli_search(reader, a.target, a.release)
        return 0
    if a.cmd == "pairs":
        print(json.dumps(check_pairs(reader, a.release, a.weeks.split(",")), indent=1))
        return 0
    if a.cmd == "index":
        weeks = a.weeks.split(",") if a.weeks else None
        dets = tuple(int(x) for x in a.detectors.split(","))
        st = build_index(reader, a.release, weeks=weeks, detectors=dets, infer_pairs=not a.no_pairs,
                         workers=a.workers, max_seconds=a.max_seconds)
        print(json.dumps(st, indent=1))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
