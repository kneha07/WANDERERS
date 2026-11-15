#!/usr/bin/env python3
"""SPHEREx stage of the WANDERERS Sky Survey: is each NEOWISE mover where its motion says it is in 2025-26?

NEOWISE (2014-2024) gives every mover a position and a proper motion. SPHEREx observed the whole sky again in
2025-26. SPHEREx has no public source catalogue yet, but its first data release (DR1) includes an all-sky spectral
cube on NASA IRSA's public AWS bucket (anonymous, us-east-1), cut into the same HEALPix order-5 tiles as the survey:

    https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/dr1/hips5_cube/hips_20261026/Norder5/Dir{D}/Npix{k5}_cube.fits

(D = (k5 // 10000) * 10000). One file per tile, ~321 MB, laid out as (verified by reading the headers):

* primary HDU, no data: MJD-BEG / MJD-END / DATE-BEG / DATE-END of the inputs, BLANKCH = channels written as
  all-NaN planes (e.g. 'D3:17,D4:01' = detector 3 channel 17 and detector 4 channel 1);
* IMAGE: float32 big-endian, 512 x 512 pixels x 102 wavelength planes (0.753-4.988 um), MJy/sr, stored plane by
  plane (one plane = 1 MiB); celestial WCS is the HEALPix projection (RA---HPX / DEC--HPX, PV2_1=4, PV2_2=3) on
  the HEALPix order-14 grid (512 = 2^9 pixels per order-5 tile side), so every pixel covers the same solid angle,
  4 pi / (12 x 4^14) sr = 3.90e-9 sr (an equal-area pixel ~12.9" across; its shape varies over the sky);
* NHITS (int32 hit counts) and FLAGS (int32 bit masks), same shape; not read here (they would triple the bytes);
* SPECTRAL_CHANNELS (DETECTOR, SUBCHAN, WAVELENGTH, WL_MIN, WL_MAX, R, ...) and WCS-WAVE (the WAVE-TAB lookup
  table: PLANE, WAVELENGTHS, BANDWIDTHS). There is no uncertainty plane, so errors come from the local scatter.

Nothing is downloaded whole: the stage reads the headers and the two small tables (about 4 requests per tile),
then, for each mover, a few rows around its predicted pixel in every plane with HTTP Range requests (keep-alive
connection pool, ~16 concurrent requests, retries with backoff, timeouts). Nearby movers share reads.

For each mover (dict with ra, dec, epoch, pmra, pmdec, pm, pm_err, track, ...; see docs/survey-contract.md):

1. Predict its position at the cube's mean epoch with its own proper motion (survey.rank.propagate), find the
   SPHEREx tile that holds that position (a fast mover can cross into a neighbour), and project to pixels with
   astropy's WCS (HPX). The stamp may span several tiles: pixels outside the tile are mapped through the sky
   to the neighbouring tile's cube.
2. Aperture photometry in every channel: pixels whose centres lie within R_AP of the predicted position, minus
   the median of an annulus (R_IN-R_OUT); the error comes from the annulus scatter (1.4826 x MAD). Radii are
   in units of the equal-area pixel size, so the same code runs on small synthetic test cubes.
3. Detection S/N, summed over channels: a matched filter over the channels inside NEOWISE's W1 + W2 bands
   (2.8-5.0 um), each weighted by the flux the mover's own NEOWISE W1/W2 magnitudes predict there (a power law
   through W1 and W2). This measures the light NEOWISE tracked, so a blue neighbour that dominates the short
   wavelengths inside the same 13" pixels cannot make a mover look "detected". Detected = S/N >= 5. Errors
   include a 3 % per-channel allowance for calibration and PSF changes between channels.
4. Centroid of the background-subtracted image (same channel weights) within R_AP, iterated, its offset from
   the predicted position and a 1-sigma error = statistical centroid error, a 0.15-pixel floor for centroids on
   resampled, undersampled images, the motion during the cube's months of data (pm x span / sqrt(12)) and the
   NEOWISE motion error carried to the SPHEREx epoch, added in quadrature. at_predicted = detected and the
   offset is within 3 sigma (true); false when the light is centred well away (more than 3 sigma and half an
   aperture) or nothing is at the predicted spot while a source still sits at the 2014 position; null otherwise,
   and also when SPHEREx's 4-5 um flux differs from NEOWISE W2 by more than a factor 2.5 (1 mag; w2_ratio,
   skipped for saturated W2 < 6.7), the sign of another source inside the same pixels.
5. Fast movers: the 2014 position (first NEOWISE visit) is measured the same way when it is at least two
   apertures away. gone_from_2014 = true when nothing is there (S/N < 3) or what is there has under a tenth of
   the flux at the predicted spot; false when a source at least half as bright (S/N >= 5) is still there.
   confirmed = at_predicted, the 2014 and predicted positions are more than 2 x 3 sigma apart and the centroid is
   more than 3 sigma from the 2014 position (SPHEREx itself sees the motion), and the 2014 position is not
   still occupied. Slow movers (a few arcsec in 11 years) cannot be confirmed: SPHEREx's ~13" pixels cannot
   see such small motions, so for them SPHEREx only shows that a source is there.
6. A compact spectrum: each detector's 17 channels are combined into 4 bands (24 bands, inverse-variance
   weighted), flux density in mJy (MJy/sr x pixel solid angle x 1e9), errors and wavelengths.
7. Spectral indices (plain physics, cited; every result is a "hint", never a classification):
   * w1w2: a synthetic WISE W1-W2 colour (Vega) from the mean flux density in 2.8-3.8 um and 4.1-5.0 um with the
     WISE zero points of Jarrett et al. (2011): 309.540 Jy (W1), 171.787 Jy (W2). The same brackets as the
     ranking's NEOWISE colour (Kirkpatrick et al. 2011): >= 0.5 reddish, >= 1 red, >= 2 very red (cold brown
     dwarfs, whose flux peaks at 4-4.6 um). When the short band is not detected it is a lower limit (2 sigma).
   * ch4_depth: 1 - F(3.20-3.45 um) / continuum, the continuum a power law through 2.90-3.10 um and 3.70-3.95 um.
     Methane (CH4) absorbs at 3.3 um in T dwarfs and late L dwarfs (Noll et al. 2000, ApJ 541, L75). A power law
     follows any Rayleigh-Jeans photosphere exactly, and the Wien side bends the other way (negative depth), so
     a methane-free star gives depth <= 0. Methane hint = depth >= 3 sigma and >= 0.1; the 0.1 is a cautious
     allowance for channel-to-channel calibration, not a physical threshold.
   * peak_um: wavelength of the brightest band between 2.8 and 5.0 um (bands with S/N >= 3): ~4.2-4.6 um for
     cold brown dwarfs, the blue end for ordinary stars. Shorter wavelengths are left out because a blue
     neighbour inside the 13" pixels often dominates there.

Never raises on network trouble: a mover that could not be checked gets ``checked: false`` and an ``error``
("network: ..." for a network failure, which the runner retries on the next publish).

CLI (real data, used for the checks in the report):

    $PY pipeline/survey/spherex.py --tile-file app/data/survey/tiles/8545.json [--ids 8545-0001]
    $PY pipeline/survey/spherex.py --leaderboard app/data/survey/leaderboard.json --top 30 --class unexplained
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import math
import sys
import threading
import time
import warnings
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np

_HERE = Path(__file__).resolve().parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

log = logging.getLogger("survey.spherex")

# ---------------------------------------------------------------------------------------------- constants
BASE_URL = "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com"
CUBE_PREFIX = "dr1/hips5_cube/hips_20261026/Norder5"
RELEASE = "SPHEREx DR1 all-sky spectral cube (HiPS order 5, hips_20261026)"
USER_AGENT = "wanderers-survey/1.0 (+https://github.com/kneha07/WANDERERS)"
STAGE_VERSION = 1                    # bump to invalidate cached results when the measurement changes

NSIDE = 32                           # HEALPix order 5 (the survey's tiles)
N_TILES = 12 * NSIDE * NSIDE
TILE_SR = 4.0 * math.pi / N_TILES    # solid angle of one order-5 tile
ARCSEC_PER_RAD = 180.0 / math.pi * 3600.0
MAS_PER_ARCSEC = 1000.0
BLOCK = 2880

# Photometry geometry, in units of the equal-area pixel size (sqrt of the pixel solid angle; 12.9" for the real
# cube, so R_AP = 20", annulus 32-56").
R_AP = 1.55
R_IN = 2.5
R_OUT = 4.35
STAMP_MAX_HALF = 8                   # at most a 17 x 17 pixel stamp
MIN_BKG_PIXELS = 8

DETECT_SNR = 5.0                     # broadband S/N for "detected"
ABSENT_SNR = 3.0                     # below this at the 2014 position: nothing there
OFFSET_SIGMA = 3.0                   # at_predicted: offset within 3 sigma
CENTROID_FLOOR_PX = 0.15             # centroid floor (fraction of a pixel)
OLD_MIN_SEP_AP = 2.0                 # the 2014 position is measured when >= 2 apertures (R_AP) away
GONE_FRAC = 0.1                      # at the 2014 position: under a tenth of the flux = not the mover
STILL_FRAC = 0.5                     # ... at least half of it (and S/N >= 5) = a comparable source is still there
CHANNEL_SYS_FRAC = 0.03              # per-channel error allowance for calibration / PSF changes between channels
W2_SATURATION = 6.7                  # NEOWISE W2 brighter than this is saturated (survey.rank)
W2_RATIO_MAX = 2.5                   # SPHEREx 4-5 um flux within 1 mag (x2.5) of NEOWISE W2, else probably a blend
MERGE_GAP_ROWS = 3                   # rows between two stamps read as one request
BATCH_MOVERS = 8                     # movers whose reads are issued together

# Spectral bands and indices (micron)
BANDS_PER_DETECTOR = 4
W1_WINDOW = (2.8, 3.8)
W2_WINDOW = (4.1, 5.0)
WISE_WINDOW = (2.8, 5.0)             # SPHEREx channels inside NEOWISE's W1 + W2 bands
W1_UM, W2_UM = 3.3526, 4.6028        # WISE isophotal wavelengths (Wright et al. 2010)
W1_ZERO_MJY = 309540.0               # WISE W1 Vega zero point, 309.540 Jy (Jarrett et al. 2011)
W2_ZERO_MJY = 171787.0               # WISE W2 Vega zero point, 171.787 Jy
CH4_BAND = (3.20, 3.45)
CH4_BLUE = (2.90, 3.10)
CH4_RED = (3.70, 3.95)
CH4_MIN_DEPTH = 0.1                  # cautious calibration allowance (see the module docstring)
INDEX_SNR = 3.0                      # a window must be measured at >= 3 sigma to enter an index
COLOUR_MAX_ERR = 0.3                 # colours less certain than this (mag) are not interpreted
LIMIT_SIGMA = 2.0                    # lower limits use a 2-sigma upper limit on the short-band flux
RED_BRACKETS = ((2.0, "very red, like a cold brown dwarf"), (1.0, "red, like a brown dwarf"),
                (0.5, "reddish, could be a brown dwarf"))

SPHEREX_KEYS = ["checked", "detected", "confirmed", "snr", "offset_arcsec", "offset_err", "expected_offset",
                "at_predicted", "gone_from_2014", "old_snr", "w2_ratio", "epoch", "tile", "spectrum", "indices",
                "notes", "error"]
INDEX_KEYS = ["w1w2", "w1w2_err", "w1w2_lim", "ch4_depth", "ch4_err", "methane", "peak_um", "hints"]
SPECTRUM_KEYS = ["um", "mjy", "err"]
NETWORK = "network: "                # prefix of errors the runner should retry later
BUDGET = "time budget"               # error text of movers left unchecked when the time ran out


# ---------------------------------------------------------------------------------------------- errors & readers
class SpherexError(RuntimeError):
    """Problem with the SPHEREx data that is not the network's fault (bad file, unexpected layout)."""


class NetworkError(SpherexError):
    """The archive could not be reached or answered with an error; worth retrying later."""


class CubeMissing(SpherexError):
    """No cube file for this tile."""


class BudgetExceeded(Exception):
    pass


def cube_url(k5: int) -> str:
    k5 = int(k5)
    return f"{BASE_URL}/{CUBE_PREFIX}/Dir{(k5 // 10000) * 10000}/Npix{k5}_cube.fits"


class _Counter:
    def __init__(self):
        self._lock = threading.Lock()
        self.bytes = 0
        self.requests = 0

    def add(self, n: int) -> None:
        with self._lock:
            self.bytes += int(n)
            self.requests += 1


class HttpRangeReader:
    """HTTP Range reads with a keep-alive connection pool, retries with backoff and timeouts (urllib3)."""

    def __init__(self, workers: int = 16, timeout: float = 30.0, retries: int = 3, backoff: float = 0.5):
        import urllib3
        try:
            import certifi
            ca = certifi.where()
        except ImportError:   # pragma: no cover - certifi ships with requests in the project venv
            ca = None
        retry = urllib3.Retry(total=retries, connect=retries, read=retries, status=retries, backoff_factor=backoff,
                              status_forcelist=(429, 500, 502, 503, 504), allowed_methods=frozenset({"GET"}),
                              raise_on_status=False)
        self.pool = urllib3.PoolManager(num_pools=8, maxsize=workers, block=True, ca_certs=ca, retries=retry,
                                        timeout=urllib3.Timeout(connect=10.0, read=timeout),
                                        headers={"User-Agent": USER_AGENT})
        self.counter = _Counter()
        self.sizes: dict[str, int] = {}

    def read(self, url: str, start: int, stop: int) -> bytes:
        """Bytes [start, stop) of url (shorter at the end of the file)."""
        import urllib3
        if stop <= start:
            return b""
        try:
            r = self.pool.request("GET", url, headers={"Range": f"bytes={int(start)}-{int(stop) - 1}"},
                                  preload_content=False)
        except urllib3.exceptions.HTTPError as e:
            raise NetworkError(f"{type(e).__name__}: {str(e)[:160]}") from e
        try:
            if r.status == 404:
                raise CubeMissing(url)
            if r.status == 416:
                return b""
            if r.status != 206:            # 200 would be the whole 321 MB file: never read it
                raise NetworkError(f"HTTP {r.status} for a range request")
            cr = r.headers.get("Content-Range", "")
            if "/" in cr and cr.rsplit("/", 1)[1].isdigit():
                self.sizes[url] = int(cr.rsplit("/", 1)[1])
            try:
                data = r.read()
            except urllib3.exceptions.HTTPError as e:
                raise NetworkError(f"{type(e).__name__}: {str(e)[:160]}") from e
        finally:
            r.release_conn()
        self.counter.add(len(data))
        return data


class FileRangeReader:
    """Range reads from local files (tests, or cubes already on disk). `path_for(url)` maps a URL to a path;
    a missing file is CubeMissing."""

    def __init__(self, path_for: Callable[[str], Any] | dict):
        self.path_for = path_for if callable(path_for) else (lambda url: path_for.get(url))
        self.counter = _Counter()
        self.sizes: dict[str, int] = {}

    def read(self, url: str, start: int, stop: int) -> bytes:
        p = self.path_for(url)
        if p is None or not Path(p).exists():
            raise CubeMissing(url)
        with open(p, "rb") as fh:
            fh.seek(0, 2)
            self.sizes[url] = fh.tell()
            fh.seek(int(start))
            data = fh.read(max(0, int(stop) - int(start)))
        self.counter.add(len(data))
        return data


# ---------------------------------------------------------------------------------------------- cube layout
def _parse_cards(raw: bytes) -> tuple[dict, int] | None:
    """FITS header cards up to END -> ({key: value}, header length rounded to blocks); None if END is missing."""
    from astropy.io import fits
    n = len(raw) // 80
    for i in range(n):
        card = raw[i * 80:(i + 1) * 80]
        if card[:8] == b"END     " or card.rstrip() == b"END":
            text = raw[:(i + 1) * 80].decode("ascii", "replace")
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                hdr = fits.Header.fromstring(text)
            return hdr, int(math.ceil((i + 1) * 80 / BLOCK) * BLOCK)
    return None


def _data_bytes(hdr) -> int:
    naxis = int(hdr.get("NAXIS", 0))
    if naxis == 0:
        return 0
    n = 1
    for i in range(1, naxis + 1):
        n *= int(hdr.get(f"NAXIS{i}", 0))
    n = (n + int(hdr.get("PCOUNT", 0))) * int(hdr.get("GCOUNT", 1))
    return n * abs(int(hdr["BITPIX"])) // 8


def _padded(n: int) -> int:
    return int(math.ceil(n / BLOCK) * BLOCK)


def mjd_to_year(mjd: float) -> float:
    return 2000.0 + (float(mjd) - 51544.5) / 365.25


def parse_blankch(text: Any) -> list[tuple[int, int]]:
    """'D3:17,D4:01' -> [(3, 17), (4, 1)] (detector, channel); junk is ignored."""
    out = []
    for part in str(text or "").replace(";", ",").split(","):
        part = part.strip().upper()
        if not part.startswith("D") or ":" not in part:
            continue
        a, b = part[1:].split(":", 1)
        try:
            out.append((int(a), int(b)))
        except ValueError:
            continue
    return out


CEL_KEYS = ["CRPIX1", "CRPIX2", "PC1_1", "PC1_2", "PC2_1", "PC2_2", "CDELT1", "CDELT2", "CUNIT1", "CUNIT2",
            "CTYPE1", "CTYPE2", "CRVAL1", "CRVAL2", "PV2_1", "PV2_2", "LONPOLE", "LATPOLE", "RADESYS"]


def celestial_wcs(hdr, nx: int, ny: int):
    """The 2-D celestial WCS (HPX) of a cube header (the WAVE-TAB axis needs the file, so it is left out)."""
    from astropy.io import fits
    from astropy.wcs import WCS
    h = fits.Header()
    h["NAXIS"] = 2
    h["NAXIS1"], h["NAXIS2"] = int(nx), int(ny)
    for k in CEL_KEYS:
        if k in hdr:
            h[k] = hdr[k]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return WCS(h)


def hpx_tile_header(k5: int, n: int = 512) -> dict:
    """Celestial WCS keywords of HiPS tile k5 with n x n pixels (n = 512 for the real cube), as SPHEREx writes them:
    HPX projection, PC matrix rotated by 45 degrees, CRPIX placing the tile's corners at the array corners.
    Used by the tests to build synthetic cubes (and checked there against the real tile 8545 header)."""
    from astropy.wcs import WCS
    from astropy_healpix import HEALPix
    import astropy.units as u
    # In the HPX plane a base pixel is a square of diagonal 90 deg; an order-(5 + log2 n) pixel has diagonal
    # 90 / (32 n) deg, i.e. PC elements of +-90 / (32 n) / 2 deg along the rotated axes.
    step = 90.0 / (NSIDE * n) / 2.0
    h = {"CTYPE1": "RA---HPX", "CTYPE2": "DEC--HPX", "CRVAL1": 0.0, "CRVAL2": 0.0, "PV2_1": 4.0, "PV2_2": 3.0,
         "PC1_1": -step, "PC1_2": -step, "PC2_1": step, "PC2_2": -step, "CDELT1": 1.0, "CDELT2": 1.0,
         "CUNIT1": "deg", "CUNIT2": "deg", "LONPOLE": 0.0, "LATPOLE": 90.0, "RADESYS": "ICRS"}
    probe = dict(h, CRPIX1=0.0, CRPIX2=0.0)
    from astropy.io import fits
    hh = fits.Header()
    hh["NAXIS"] = 2
    hh["NAXIS1"] = hh["NAXIS2"] = n
    for k, v in probe.items():
        hh[k] = v
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        w = WCS(hh)
    hp = HEALPix(nside=NSIDE, order="nested")
    # the tile centre lands at the array centre; corners would sit on HPX seams for polar tiles
    lon, lat = hp.healpix_to_lonlat([int(k5)])
    cx, cy = w.world_to_pixel_values(lon.to_value(u.deg)[0], lat.to_value(u.deg)[0])
    # the 0-based pixel of a point moves by exactly the CRPIX change; the centre must land at (n-1)/2
    h["CRPIX1"] = round(float(-cx + (n - 1) / 2.0) * 2) / 2
    h["CRPIX2"] = round(float(-cy + (n - 1) / 2.0) * 2) / 2
    return h


@dataclass
class CubeLayout:
    k5: int
    url: str
    data_offset: int
    nx: int
    ny: int
    nplanes: int
    wcs: Any
    mjd_beg: float | None
    mjd_end: float | None
    blank: set = field(default_factory=set)
    wavelengths: np.ndarray | None = None
    detectors: np.ndarray | None = None
    subchans: np.ndarray | None = None
    bunit: str = "MJy/sr"

    @property
    def epoch(self) -> float | None:
        if self.mjd_beg is None or self.mjd_end is None:
            return None
        return mjd_to_year(0.5 * (self.mjd_beg + self.mjd_end))

    @property
    def span_yr(self) -> float:
        if self.mjd_beg is None or self.mjd_end is None:
            return 0.0
        return max(0.0, (self.mjd_end - self.mjd_beg) / 365.25)

    @property
    def pix_sr(self) -> float:
        return TILE_SR / (self.nx * self.ny)

    @property
    def pix_arcsec(self) -> float:
        return math.sqrt(self.pix_sr) * ARCSEC_PER_RAD

    def offset(self, plane: int, row: int, col: int) -> int:
        return self.data_offset + ((int(plane) * self.ny + int(row)) * self.nx + int(col)) * 4


def _table_from(hdr_bytes: bytes, data: bytes):
    from astropy.io import fits
    prim = fits.PrimaryHDU().header.tostring().encode("ascii")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        hdul = fits.open(io.BytesIO(prim + hdr_bytes + data + b"\0" * (_padded(len(data)) - len(data))))
        return hdul[1].data


def read_layout(reader, url: str, k5: int, chunk: int = 4 * BLOCK, max_hdus: int = 12) -> CubeLayout:
    """Walk the cube's HDU headers with Range reads (about 4 requests) and return where the IMAGE data is, its
    WCS, epochs, blank planes and wavelengths. Raises NetworkError / CubeMissing / SpherexError."""
    cache: dict[int, bytes] = {}

    def get(off: int, n: int) -> bytes:
        for s, b in cache.items():
            if s <= off and off + n <= s + len(b):
                return b[off - s: off - s + n]
        b = reader.read(url, off, off + max(n, chunk))
        cache[off] = b
        return b[:n]

    off, primary, image, tables = 0, None, None, {}
    size = None
    for _ in range(max_hdus):
        raw = b""
        parsed = None
        while parsed is None:
            more = get(off + len(raw), chunk)
            if not more:
                break
            raw += more
            parsed = _parse_cards(raw)
            if len(raw) > 40 * BLOCK:
                raise SpherexError("header without END")
        if parsed is None:
            break
        hdr, hlen = parsed
        size = getattr(reader, "sizes", {}).get(url, size)
        nbytes = _data_bytes(hdr)
        if primary is None:
            primary = hdr
        else:
            name = str(hdr.get("EXTNAME", "")).strip().upper()
            if name == "IMAGE" and image is None:
                image = (hdr, off + hlen)
            elif name in ("SPECTRAL_CHANNELS", "WCS-WAVE") and str(hdr.get("XTENSION", "")).strip() == "BINTABLE":
                tables[name] = _table_from(raw[:hlen], get(off + hlen, nbytes))
        off += hlen + _padded(nbytes)
        if image is not None and len(tables) == 2:
            break
        if size is not None and off >= size:
            break
    if primary is None or image is None:
        raise SpherexError("no IMAGE extension in the cube")
    ih, doff = image
    if int(ih.get("BITPIX", 0)) != -32 or int(ih.get("NAXIS", 0)) != 3:
        raise SpherexError(f"unexpected IMAGE layout (BITPIX {ih.get('BITPIX')}, NAXIS {ih.get('NAXIS')})")
    nx, ny, nz = int(ih["NAXIS1"]), int(ih["NAXIS2"]), int(ih["NAXIS3"])
    lay = CubeLayout(k5=int(k5), url=url, data_offset=doff, nx=nx, ny=ny, nplanes=nz, wcs=celestial_wcs(ih, nx, ny),
                     mjd_beg=_float(primary.get("MJD-BEG")), mjd_end=_float(primary.get("MJD-END")),
                     bunit=str(ih.get("BUNIT", "MJy/sr")).strip())
    sc = tables.get("SPECTRAL_CHANNELS")
    ww = tables.get("WCS-WAVE")
    if sc is not None and len(sc) == nz:
        lay.wavelengths = np.asarray(sc["WAVELENGTH"], dtype=float)
        lay.detectors = np.asarray(sc["DETECTOR"], dtype=int)
        lay.subchans = np.asarray(sc["SUBCHAN"], dtype=int)
    if ww is not None and len(ww):
        wl = np.ravel(np.asarray(ww["WAVELENGTHS"][0], dtype=float))
        planes = np.ravel(np.asarray(ww["PLANE"][0], dtype=int))
        if wl.size == nz:
            order = np.argsort(planes) if planes.size == nz else np.arange(nz)
            lay.wavelengths = wl[order]
    if lay.wavelengths is None:   # last resort: linear from the header range
        lo, hi = _float(ih.get("WLMIN")) or 0.753, _float(ih.get("WLMAX")) or 4.988
        lay.wavelengths = np.linspace(lo, hi, nz)
    if lay.detectors is None:
        per = max(1, nz // 6)
        lay.detectors = np.minimum(np.arange(nz) // per + 1, 6)
        lay.subchans = np.arange(nz) % per + 1
    for det, sub in parse_blankch(primary.get("BLANKCH")):
        hit = np.nonzero((lay.detectors == det) & (lay.subchans == sub))[0]
        lay.blank.update(int(i) for i in hit)
    return lay


def _float(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


# ---------------------------------------------------------------------------------------------- sky geometry
def _healpix():
    import astropy.units as u
    from astropy_healpix import lonlat_to_healpix
    return u, lonlat_to_healpix


def tiles_of(ra, dec) -> np.ndarray:
    """HEALPix nested order-5 tile of each position (-1 where not finite)."""
    u, lonlat_to_healpix = _healpix()
    ra = np.atleast_1d(np.asarray(ra, dtype=float))
    dec = np.atleast_1d(np.asarray(dec, dtype=float))
    out = np.full(ra.shape, -1, dtype=int)
    ok = np.isfinite(ra) & np.isfinite(dec)
    if ok.any():
        out[ok] = lonlat_to_healpix(ra[ok] * u.deg, np.clip(dec[ok], -90, 90) * u.deg, NSIDE, order="nested")
    return out


def tangent_offsets(ra, dec, ra0, dec0):
    """Gnomonic offsets (xi east, eta north) in arcsec of (ra, dec) about (ra0, dec0); NaN where undefined."""
    a, d = np.radians(np.asarray(ra, dtype=float)), np.radians(np.asarray(dec, dtype=float))
    a0, d0 = math.radians(ra0), math.radians(dec0)
    cosc = np.sin(d0) * np.sin(d) + np.cos(d0) * np.cos(d) * np.cos(a - a0)
    with np.errstate(invalid="ignore", divide="ignore"):
        xi = np.cos(d) * np.sin(a - a0) / cosc
        eta = (np.cos(d0) * np.sin(d) - np.sin(d0) * np.cos(d) * np.cos(a - a0)) / cosc
    bad = ~(cosc > 0)
    xi = np.where(bad, np.nan, xi) * ARCSEC_PER_RAD
    eta = np.where(bad, np.nan, eta) * ARCSEC_PER_RAD
    return xi, eta


def _propagate(ra, dec, pmra, pmdec, dt):
    from survey.rank import propagate
    return propagate(ra, dec, pmra, pmdec, dt)


def _sep(ra1, dec1, ra2, dec2) -> float:
    from survey.rank import separation_arcsec
    return float(separation_arcsec(ra1, dec1, ra2, dec2))


@dataclass
class Stamp:
    """Pixels around a sky position, possibly from several tiles: tile (-1 = no data), row, col, and the pixel
    centres' offsets (arcsec) from the position."""
    ra: float
    dec: float
    tile: np.ndarray
    row: np.ndarray
    col: np.ndarray
    xi: np.ndarray
    eta: np.ndarray
    pix_arcsec: float
    values: np.ndarray | None = None          # (nplanes, npix) MJy/sr once read

    @property
    def dist(self) -> np.ndarray:
        return np.hypot(self.xi, self.eta)


# ---------------------------------------------------------------------------------------------- measurements
def aperture_photometry(values: np.ndarray, xi: np.ndarray, eta: np.ndarray, pix_arcsec: float, pix_sr: float,
                        cx: float = 0.0, cy: float = 0.0) -> dict:
    """Per-channel aperture flux (mJy) and error at offset (cx, cy) arcsec. values: (C, P) MJy/sr.
    A channel is NaN unless every aperture pixel has data and the annulus has >= MIN_BKG_PIXELS pixels with data
    (a saturated or uncovered core gives a gap, never a wrong number)."""
    values = np.asarray(values, dtype=float)
    d = np.hypot(np.asarray(xi) - cx, np.asarray(eta) - cy)
    ap = d <= R_AP * pix_arcsec
    bk = (d >= R_IN * pix_arcsec) & (d <= R_OUT * pix_arcsec)
    C = values.shape[0]
    flux = np.full(C, np.nan)
    err = np.full(C, np.nan)
    bkg = np.full(C, np.nan)
    sig = np.full(C, np.nan)
    n_ap = int(ap.sum())
    if n_ap == 0 or not bk.any():
        return {"flux": flux, "err": err, "bkg": bkg, "sig": sig, "ap": ap, "n_ap": n_ap}
    A = values[:, ap]
    B = values[:, bk]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        n_b = np.sum(np.isfinite(B), axis=1)
        med = np.nanmedian(B, axis=1)
        mad = np.nanmedian(np.abs(B - med[:, None]), axis=1) * 1.4826
    ok = np.all(np.isfinite(A), axis=1) & (n_b >= MIN_BKG_PIXELS) & np.isfinite(mad) & (mad > 0)
    scale = pix_sr * 1e9                                   # MJy/sr x sr = MJy; x 1e9 = mJy
    f = np.sum(np.where(np.isfinite(A), A - med[:, None], 0.0), axis=1) * scale
    e = mad * np.sqrt(n_ap + (math.pi / 2.0) * n_ap ** 2 / np.maximum(n_b, 1)) * scale
    flux[ok], err[ok], bkg[ok], sig[ok] = f[ok], e[ok], med[ok], mad[ok]
    return {"flux": flux, "err": err, "bkg": bkg, "sig": sig, "ap": ap, "n_ap": n_ap}


def with_floor(phot: dict, frac: float = None) -> dict:
    """Add the per-channel systematic allowance (CHANNEL_SYS_FRAC of the flux) to the errors, in quadrature."""
    frac = CHANNEL_SYS_FRAC if frac is None else frac
    phot = dict(phot)
    phot["err"] = np.hypot(phot["err"], frac * np.abs(phot["flux"]))
    return phot


def gone_verdict(old_snr: float | None, f_old: float | None, f_new: float | None) -> bool | None:
    """Is the mover gone from its 2014 position? True: nothing there (S/N < 3) or whatever is there has under a
    tenth of the flux at the predicted spot; False: a source at least half as bright is still there (S/N >= 5);
    None: not measured or in between."""
    if old_snr is None:
        return None
    if old_snr < ABSENT_SNR:
        return True
    if f_new is not None and f_old is not None and f_new > 0 and f_old < GONE_FRAC * f_new:
        return True
    if old_snr >= DETECT_SNR and (f_new is None or f_new <= 0 or (f_old is not None and f_old >= STILL_FRAC * f_new)):
        return False
    return None


def w2_ratio(wl, flux, err, w2_mag: float | None) -> float | None:
    """SPHEREx mean flux density in 4.1-5.0 um divided by the NEOWISE W2 flux density (Vega zero point); None
    unless both are measured (SPHEREx at >= 3 sigma)."""
    if w2_mag is None:
        return None
    a = _window(np.asarray(wl, float), np.asarray(flux, float), np.asarray(err, float), *W2_WINDOW)
    if a is None or not (a[0] > 0 and a[0] / a[1] >= INDEX_SNR):
        return None
    return a[0] / (W2_ZERO_MJY * 10 ** (-0.4 * w2_mag))


def wise_template(wl, w1: float | None, w2: float | None) -> np.ndarray:
    """Relative flux density the mover should have in each channel, from its NEOWISE magnitudes: a power law
    through W1 (3.35 um) and W2 (4.60 um) inside WISE_WINDOW (2.8-5.0 um, the light NEOWISE measured), zero
    elsewhere. No W1: W1-W2 = 2 is assumed (W1 non-detections are red); no W2: flat."""
    wl = np.asarray(wl, dtype=float)
    sel = (wl >= WISE_WINDOW[0]) & (wl <= WISE_WINDOW[1])
    if w2 is None:
        return sel.astype(float)
    f2 = W2_ZERO_MJY * 10 ** (-0.4 * w2)
    f1 = W1_ZERO_MJY * 10 ** (-0.4 * w1) if w1 is not None else W1_ZERO_MJY * 10 ** (-0.4 * (w2 + 2.0))
    alpha = math.log(f2 / f1) / math.log(W2_UM / W1_UM)
    s = (wl / W2_UM) ** alpha
    s = np.where(sel, s, 0.0)
    return s / s.max() if s.max() > 0 else sel.astype(float)


def matched(flux: np.ndarray, err: np.ndarray, template: np.ndarray) -> tuple:
    """Matched-filter amplitude of `template` in the channel fluxes: (flux at the template's peak in mJy, error,
    S/N); Nones when no channel is usable."""
    flux, err, t = (np.asarray(x, dtype=float) for x in (flux, err, template))
    ok = np.isfinite(flux) & np.isfinite(err) & (err > 0) & np.isfinite(t) & (t > 0)
    if not ok.any():
        return None, None, None
    w = t[ok] ** 2 / err[ok] ** 2
    a = float(np.sum(t[ok] * flux[ok] / err[ok] ** 2) / np.sum(w))
    s = float(1.0 / math.sqrt(np.sum(w)))
    return a, s, a / s


def broadband(flux: np.ndarray, err: np.ndarray) -> tuple[float | None, float | None, float | None]:
    """Inverse-variance weighted mean flux over channels, its error and S/N (None when nothing was measured)."""
    flux, err = np.asarray(flux, dtype=float), np.asarray(err, dtype=float)
    ok = np.isfinite(flux) & np.isfinite(err) & (err > 0)
    if not ok.any():
        return None, None, None
    w = 1.0 / err[ok] ** 2
    f = float(np.sum(w * flux[ok]) / np.sum(w))
    s = float(1.0 / math.sqrt(np.sum(w)))
    return f, s, f / s


def centroid(values: np.ndarray, xi: np.ndarray, eta: np.ndarray, bkg: np.ndarray, sig: np.ndarray,
             pix_arcsec: float, iterations: int = 2, template: np.ndarray | None = None
             ) -> tuple[float, float, float] | None:
    """Centroid (arcsec offsets) of the background-subtracted broadband image within R_AP of the current centre,
    iterated from the predicted position; channels weighted by template / noise^2 (a matched filter; template
    None = flat). Returns (cx, cy, statistical 1-sigma per axis) or None."""
    values = np.asarray(values, dtype=float)
    tpl = np.ones(values.shape[0]) if template is None else np.asarray(template, dtype=float)
    ok_c = np.isfinite(bkg) & np.isfinite(sig) & (sig > 0) & np.isfinite(tpl) & (tpl > 0)
    if not ok_c.any():
        return None
    u = tpl[ok_c] / sig[ok_c] ** 2
    V = values[ok_c] - bkg[ok_c, None]
    fin = np.isfinite(V)
    wsum = np.sum(np.where(fin, u[:, None], 0.0), axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        D = np.sum(np.where(fin, V * u[:, None], 0.0), axis=0) / wsum
        sD = np.sqrt(np.sum(np.where(fin, (u * sig[ok_c])[:, None] ** 2, 0.0), axis=0)) / wsum
    good = (wsum > 0) & np.isfinite(xi) & np.isfinite(eta)
    cx = cy = 0.0
    res = None
    for _ in range(max(1, iterations)):
        sel = good & (np.hypot(xi - cx, eta - cy) <= R_AP * pix_arcsec)
        if sel.sum() < 2:
            return res
        F = float(np.sum(D[sel]))
        if not F > 0:
            return res
        nx = float(np.sum(D[sel] * xi[sel]) / F)
        ny = float(np.sum(D[sel] * eta[sel]) / F)
        ex = math.sqrt(float(np.sum(((xi[sel] - nx) * sD[sel]) ** 2))) / F
        ey = math.sqrt(float(np.sum(((eta[sel] - ny) * sD[sel]) ** 2))) / F
        res = (nx, ny, math.hypot(ex, ey) / math.sqrt(2.0))
        if math.hypot(nx - cx, ny - cy) < 0.01 * pix_arcsec:
            break
        cx, cy = nx, ny
        if math.hypot(cx, cy) > R_AP * pix_arcsec:          # wandered off the aperture: stop
            break
    return res


def band_groups(detectors: np.ndarray, subchans: np.ndarray, per_detector: int = BANDS_PER_DETECTOR) -> list:
    """Channel indices of each band: every detector's channels (by sub-channel) split into `per_detector` runs."""
    groups = []
    for det in sorted(set(int(d) for d in detectors)):
        idx = np.nonzero(detectors == det)[0]
        idx = idx[np.argsort(subchans[idx])]
        for g in np.array_split(idx, min(per_detector, len(idx))):
            if len(g):
                groups.append(g)
    return groups


def rebin_spectrum(wl: np.ndarray, flux: np.ndarray, err: np.ndarray, groups: list) -> dict:
    """Inverse-variance weighted band fluxes: {"um", "mjy", "err"} arrays (NaN where a band has no data)."""
    um, mjy, e = [], [], []
    for g in groups:
        f, s = flux[g], err[g]
        ok = np.isfinite(f) & np.isfinite(s) & (s > 0)
        if ok.any():
            w = 1.0 / s[ok] ** 2
            um.append(float(np.mean(wl[g][ok])))
            mjy.append(float(np.sum(w * f[ok]) / np.sum(w)))
            e.append(float(1.0 / math.sqrt(np.sum(w))))
        else:
            um.append(float(np.mean(wl[g])))
            mjy.append(float("nan"))
            e.append(float("nan"))
    return {"um": np.array(um), "mjy": np.array(mjy), "err": np.array(e)}


def _window(wl, flux, err, lo, hi):
    """Weighted mean flux, error and mean wavelength of the channels in [lo, hi] um."""
    sel = (wl >= lo) & (wl <= hi) & np.isfinite(flux) & np.isfinite(err) & (err > 0)
    if not sel.any():
        return None
    w = 1.0 / err[sel] ** 2
    return float(np.sum(w * flux[sel]) / np.sum(w)), float(1.0 / math.sqrt(np.sum(w))), float(np.mean(wl[sel]))


def synthetic_w1w2(wl, flux, err) -> dict:
    """Synthetic WISE W1-W2 (Vega) from SPHEREx: {"w1w2", "w1w2_err", "w1w2_lim"}; lim=True = lower limit."""
    out = {"w1w2": None, "w1w2_err": None, "w1w2_lim": False}
    a = _window(wl, flux, err, *W1_WINDOW)
    b = _window(wl, flux, err, *W2_WINDOW)
    if a is None or b is None:
        return out
    f1, s1, _ = a
    f2, s2, _ = b
    if not (f2 > 0 and f2 / s2 >= INDEX_SNR):
        return out
    if f1 > 0 and f1 / s1 >= INDEX_SNR:
        out["w1w2"] = -2.5 * math.log10(f1 / W1_ZERO_MJY) + 2.5 * math.log10(f2 / W2_ZERO_MJY)
        out["w1w2_err"] = 2.5 / math.log(10) * math.hypot(s1 / f1, s2 / f2)
    else:   # short band not detected: lower limit from a 2-sigma upper limit on it
        f1_up = max(f1, 0.0) + LIMIT_SIGMA * s1
        out["w1w2"] = -2.5 * math.log10(f1_up / W1_ZERO_MJY) + 2.5 * math.log10(f2 / W2_ZERO_MJY)
        out["w1w2_lim"] = True
    return out


def methane_depth(wl, flux, err) -> tuple[float | None, float | None]:
    """1 - F(3.20-3.45 um) / power-law continuum through 2.90-3.10 and 3.70-3.95 um, with its error."""
    band = _window(wl, flux, err, *CH4_BAND)
    blue = _window(wl, flux, err, *CH4_BLUE)
    red = _window(wl, flux, err, *CH4_RED)
    if band is None or blue is None or red is None:
        return None, None
    fb, sb, lb = blue
    fr, sr, lr = red
    fc, sc, lc = band
    if not (fb > 0 and fr > 0 and fb / sb >= INDEX_SNR and fr / sr >= INDEX_SNR):
        return None, None
    a = (math.log(lc) - math.log(lb)) / (math.log(lr) - math.log(lb))
    cont = math.exp((1 - a) * math.log(fb) + a * math.log(fr))
    depth = 1.0 - fc / cont
    var = (sc / cont) ** 2 + (fc / cont) ** 2 * (((1 - a) * sb / fb) ** 2 + (a * sr / fr) ** 2)
    return depth, math.sqrt(var)


def spectral_indices(wl, flux, err, bands: dict | None = None) -> dict:
    """The indices dict (INDEX_KEYS) with plain-words hints."""
    wl, flux, err = (np.asarray(x, dtype=float) for x in (wl, flux, err))
    out = {k: None for k in INDEX_KEYS}
    out.update(synthetic_w1w2(wl, flux, err))
    depth, derr = methane_depth(wl, flux, err)
    out["ch4_depth"], out["ch4_err"] = depth, derr
    out["methane"] = None if depth is None else bool(depth >= OFFSET_SIGMA * derr and depth >= CH4_MIN_DEPTH)
    if bands is not None:
        ok = np.isfinite(bands["mjy"]) & np.isfinite(bands["err"]) & (bands["err"] > 0)
        ok &= np.where(ok, bands["mjy"] / np.where(ok, bands["err"], 1.0), 0.0) >= INDEX_SNR
        ok &= (bands["um"] >= WISE_WINDOW[0]) & (bands["um"] <= WISE_WINDOW[1])
        if ok.sum() >= 3:
            i = int(np.argmax(np.where(ok, bands["mjy"], -np.inf)))
            out["peak_um"] = float(bands["um"][i])
    hints = []
    c = out["w1w2"]
    if c is not None and (out["w1w2_lim"] or (out["w1w2_err"] is not None and out["w1w2_err"] <= COLOUR_MAX_ERR)):
        word = next((t for lim, t in RED_BRACKETS if c >= lim), None)
        val = f"W1−W2 {'>' if out['w1w2_lim'] else '='} {c:.1f}"
        if word:
            hints.append(f"3–5 µm colour {word} ({val}, hint)")
        elif not out["w1w2_lim"]:
            hints.append(f"Ordinary star-like 3–5 µm colour ({val})")
    if out["methane"]:
        hints.append(f"Methane hint: a {100 * depth:.0f} ± {100 * derr:.0f} % dip at 3.3 µm, as in T dwarfs")
    if out["peak_um"] is not None and out["peak_um"] >= 4.0 and c is not None and c >= 1.0:
        hints.append(f"Brightest near {out['peak_um']:.1f} µm, where cold brown dwarfs peak")
    out["hints"] = hints
    return out


# ---------------------------------------------------------------------------------------------- result dicts
def _r(x, nd):
    v = _float(x)
    return None if v is None else round(v, nd)


def _sig(x, digits=3):
    v = _float(x)
    if v is None:
        return None
    if v == 0:
        return 0.0
    return float(f"{v:.{digits}g}")


def unchecked(error: str | None = None, note: str | None = None) -> dict:
    out = {k: None for k in SPHEREX_KEYS}
    out.update({"checked": False, "confirmed": False, "notes": [note] if note else [], "error": error})
    return out


def compact(d: Any) -> dict:
    """A SPHEREx dict in the fixed key order with rounded numbers (JSON-safe; also cleans foreign input)."""
    if not isinstance(d, dict):
        return unchecked(None)
    out = {}
    out["checked"] = bool(d.get("checked", False))
    for k in ("detected", "at_predicted", "gone_from_2014"):
        v = d.get(k)
        out[k] = None if v is None else bool(v)
    out["confirmed"] = bool(d.get("confirmed", False)) and out["checked"]
    out["snr"] = _r(d.get("snr"), 1)
    for k in ("offset_arcsec", "offset_err", "expected_offset"):
        out[k] = _r(d.get(k), 2)
    out["old_snr"] = _r(d.get("old_snr"), 1)
    out["w2_ratio"] = _r(d.get("w2_ratio"), 2)
    out["epoch"] = _r(d.get("epoch"), 3)
    t = d.get("tile")
    out["tile"] = int(t) if isinstance(t, (int, np.integer)) or (_float(t) is not None and float(t).is_integer()) else None
    sp = d.get("spectrum")
    if isinstance(sp, dict) and all(k in sp for k in SPECTRUM_KEYS):
        out["spectrum"] = {"um": [_r(v, 2) for v in sp["um"]], "mjy": [_sig(v, 3) for v in sp["mjy"]],
                           "err": [_sig(v, 2) for v in sp["err"]]}
    else:
        out["spectrum"] = None
    ix = d.get("indices")
    if isinstance(ix, dict):
        out["indices"] = {"w1w2": _r(ix.get("w1w2"), 2), "w1w2_err": _r(ix.get("w1w2_err"), 2),
                          "w1w2_lim": bool(ix.get("w1w2_lim", False)), "ch4_depth": _r(ix.get("ch4_depth"), 3),
                          "ch4_err": _r(ix.get("ch4_err"), 3),
                          "methane": None if ix.get("methane") is None else bool(ix.get("methane")),
                          "peak_um": _r(ix.get("peak_um"), 2),
                          "hints": [str(h) for h in (ix.get("hints") or [])][:4]}
    else:
        out["indices"] = None
    notes = d.get("notes") or []
    out["notes"] = [str(n) for n in notes][:6] if isinstance(notes, list) else [str(notes)]
    err = d.get("error")
    out["error"] = None if err in (None, "") else str(err)[:200]
    return {k: out[k] for k in SPHEREX_KEYS}


def is_retryable(d: Any) -> bool:
    """True for results the runner should not cache: network failures and movers cut by the time budget."""
    if not isinstance(d, dict) or d.get("checked"):
        return False
    e = str(d.get("error") or "")
    return e.startswith(NETWORK) or e == BUDGET


# ---------------------------------------------------------------------------------------------- the stage
@dataclass
class _Plan:
    idx: int
    mover: dict
    tile: int
    epoch: float
    pred: tuple
    old: tuple | None
    expected: float | None
    sigma_extra: float
    stamp: Stamp
    old_stamp: Stamp | None
    notes: list


class SpherexStage:
    """Reads SPHEREx cube data for movers and measures them. One instance keeps the tile layouts (headers) it has
    read and counts bytes/requests; `check_tile` never raises."""

    def __init__(self, reader=None, url_for: Callable[[int], str] = cube_url, workers: int = 16,
                 clock: Callable[[], float] = time.monotonic):
        self.reader = reader if reader is not None else HttpRangeReader(workers=workers)
        self.url_for = url_for
        self.workers = max(1, int(workers))
        self.clock = clock
        self.layouts: dict[int, CubeLayout] = {}
        self._missing: set[int] = set()
        self._lock = threading.Lock()
        self.stats = {"movers": 0, "seconds": 0.0}

    @property
    def bytes_read(self) -> int:
        return self.reader.counter.bytes

    @property
    def requests(self) -> int:
        return self.reader.counter.requests

    def layout(self, k5: int) -> CubeLayout:
        k5 = int(k5)
        with self._lock:
            if k5 in self.layouts:
                return self.layouts[k5]
            if k5 in self._missing:
                raise CubeMissing(self.url_for(k5))
        try:
            lay = read_layout(self.reader, self.url_for(k5), k5)
        except CubeMissing:
            with self._lock:
                self._missing.add(k5)
            raise
        with self._lock:
            self.layouts[k5] = lay
        return lay

    # ---- planning
    def _stamp(self, lay: CubeLayout, ra: float, dec: float) -> Stamp | None:
        x, y = lay.wcs.world_to_pixel_values(ra, dec)
        x, y = float(x), float(y)
        if not (math.isfinite(x) and math.isfinite(y)):
            return None
        px = lay.pix_arcsec
        # local axis scales (arcsec per pixel step) to size the stamp
        wx, wy = lay.wcs.pixel_to_world_values(np.array([x, x + 1.0, x]), np.array([y, y, y + 1.0]))
        sx = _sep(wx[0], wy[0], wx[1], wy[1]) if np.all(np.isfinite(wx[:2])) else px
        sy = _sep(wx[0], wy[0], wx[2], wy[2]) if np.all(np.isfinite([wx[0], wx[2]])) else px
        h = int(min(STAMP_MAX_HALF, math.ceil(R_OUT * px / max(min(sx, sy), 1e-6)) + 1))
        xc, yc = int(round(x)), int(round(y))
        gx, gy = np.meshgrid(np.arange(xc - h, xc + h + 1), np.arange(yc - h, yc + h + 1))
        gx, gy = gx.ravel(), gy.ravel()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            pra, pdec = lay.wcs.pixel_to_world_values(gx.astype(float), gy.astype(float))
        pra, pdec = np.asarray(pra, dtype=float), np.asarray(pdec, dtype=float)
        inside = (gx >= 0) & (gx < lay.nx) & (gy >= 0) & (gy < lay.ny)
        tile = np.where(inside, lay.k5, -1)
        row = np.where(inside, gy, -1)
        col = np.where(inside, gx, -1)
        out = ~inside & np.isfinite(pra) & np.isfinite(pdec)
        if out.any():
            other = tiles_of(pra[out], pdec[out])
            idx = np.nonzero(out)[0]
            for t in sorted(set(int(v) for v in other if v >= 0)):
                sel = idx[other == t]
                try:
                    lt = self.layout(t)
                except CubeMissing:
                    continue
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    lx, ly = lt.wcs.world_to_pixel_values(pra[sel], pdec[sel])
                lx, ly = np.asarray(lx, dtype=float), np.asarray(ly, dtype=float)
                rx, ry = np.round(lx), np.round(ly)
                good = (np.isfinite(lx) & np.isfinite(ly) & (np.abs(lx - rx) < 0.3) & (np.abs(ly - ry) < 0.3)
                        & (rx >= 0) & (rx < lt.nx) & (ry >= 0) & (ry < lt.ny))
                tile[sel[good]] = t
                row[sel[good]] = ry[good].astype(int)
                col[sel[good]] = rx[good].astype(int)
        xi, eta = tangent_offsets(pra, pdec, ra, dec)
        return Stamp(ra=ra, dec=dec, tile=tile, row=row, col=col, xi=xi, eta=eta, pix_arcsec=px)

    def _plan(self, idx: int, m: dict, home: CubeLayout) -> _Plan | dict:
        ra, dec = _float(m.get("ra")), _float(m.get("dec"))
        ep = _float(m.get("epoch"))
        pmra, pmdec = _float(m.get("pmra")), _float(m.get("pmdec"))
        if None in (ra, dec, ep, pmra, pmdec):
            return unchecked("missing position, epoch or motion")
        if home.epoch is None:
            return unchecked("the SPHEREx cube has no observing dates")
        notes = []
        lay = home
        pred = _propagate(ra, dec, pmra, pmdec, home.epoch - ep)
        t = int(tiles_of(*pred)[0])
        if t != home.k5 and t >= 0:
            lay = self.layout(t)
            if lay.epoch is not None:
                pred = _propagate(ra, dec, pmra, pmdec, lay.epoch - ep)
            notes.append(f"By {lay.epoch:.1f} it had moved into the neighbouring SPHEREx tile {t}")
        pm = _float(m.get("pm")) or math.hypot(pmra, pmdec)
        pm_err = _float(m.get("pm_err")) or 0.0
        dt = lay.epoch - ep
        smear = pm / MAS_PER_ARCSEC * lay.span_yr / math.sqrt(12.0)
        extra = math.hypot(CENTROID_FLOOR_PX * lay.pix_arcsec, math.hypot(smear, pm_err / MAS_PER_ARCSEC * abs(dt)))
        t_old = _first_epoch(m)
        old = _propagate(ra, dec, pmra, pmdec, t_old - ep) if t_old is not None else None
        expected = _sep(pred[0], pred[1], old[0], old[1]) if old is not None else None
        stamp = self._stamp(lay, *pred)
        if stamp is None:
            return unchecked("the predicted position is outside the SPHEREx cube")
        old_stamp = None
        if old is not None and expected is not None and expected >= OLD_MIN_SEP_AP * R_AP * lay.pix_arcsec:
            lo = lay
            t_o = int(tiles_of(*old)[0])
            if t_o != lay.k5 and t_o >= 0:
                try:
                    lo = self.layout(t_o)
                except CubeMissing:
                    lo = None
            old_stamp = self._stamp(lo, *old) if lo is not None else None
        return _Plan(idx=idx, mover=m, tile=lay.k5, epoch=lay.epoch, pred=pred, old=old, expected=expected,
                     sigma_extra=extra, stamp=stamp, old_stamp=old_stamp, notes=notes)

    # ---- reading
    def _fetch(self, stamps: list[Stamp], deadline: float | None) -> None:
        """Fill each stamp's values (nplanes, npix) with one Range request per (tile, plane, merged row span)."""
        needs: dict[int, dict[int, set]] = defaultdict(lambda: defaultdict(set))
        for s in stamps:
            for t, r, c in zip(s.tile, s.row, s.col):
                if t >= 0:
                    needs[int(t)][int(r)].add(int(c))
        tasks, bufs = [], {}
        for t, rows in needs.items():
            lay = self.layout(t)
            rs = sorted(rows)
            spans = [[rs[0], rs[0]]]
            for r in rs[1:]:
                if r - spans[-1][1] <= MERGE_GAP_ROWS + 1:
                    spans[-1][1] = r
                else:
                    spans.append([r, r])
            for r0, r1 in spans:
                cols = set().union(*(rows[r] for r in range(r0, r1 + 1) if r in rows))
                c0, c1 = min(cols), max(cols)
                bufs[(t, r0)] = (r0, r1, c0, c1, np.full((lay.nplanes, r1 - r0 + 1, c1 - c0 + 1), np.nan, np.float32))
                for p in range(lay.nplanes):
                    if p in lay.blank:
                        continue
                    tasks.append((t, r0, p, lay.offset(p, r0, c0), lay.offset(p, r1, c1) + 4))

        def run(task):
            t, r0, p, a, b = task
            if deadline is not None and self.clock() > deadline:
                raise BudgetExceeded()
            data = self.reader.read(self.layouts[t].url, a, b)
            if len(data) != b - a:
                raise SpherexError(f"short read from tile {t} ({len(data)} of {b - a} bytes)")
            return task, data

        if tasks:
            with ThreadPoolExecutor(max_workers=min(self.workers, len(tasks))) as ex:
                for (t, r0, p, a, b), data in ex.map(run, tasks):
                    _, r1, c0, c1, buf = bufs[(t, r0)]
                    lay = self.layouts[t]
                    nrow = r1 - r0 + 1
                    flat = np.full(nrow * lay.nx, np.nan, np.float32)
                    flat[c0:c0 + (b - a) // 4] = np.frombuffer(data, ">f4")
                    buf[p] = flat.reshape(nrow, lay.nx)[:, c0:c1 + 1]
        index = defaultdict(list)
        for (t, r0), v in bufs.items():
            index[t].append(v)
        for s in stamps:
            nplanes = max((self.layouts[int(t)].nplanes for t in set(s.tile.tolist()) if t >= 0), default=0)
            vals = np.full((nplanes, s.tile.size), np.nan)
            for i, (t, r, c) in enumerate(zip(s.tile, s.row, s.col)):
                if t < 0:
                    continue
                for r0, r1, c0, c1, buf in index[int(t)]:
                    if r0 <= r <= r1 and c0 <= c <= c1:
                        vals[:buf.shape[0], i] = buf[:, r - r0, c - c0]
                        break
            s.values = vals

    # ---- measuring
    def _measure(self, plan: _Plan) -> dict:
        lay = self.layouts[plan.tile]
        s = plan.stamp
        notes = list(plan.notes)
        phot = with_floor(aperture_photometry(s.values, s.xi, s.eta, s.pix_arcsec, lay.pix_sr))
        w1, w2 = _float(plan.mover.get("w1")), _float(plan.mover.get("w2"))
        tpl = wise_template(lay.wavelengths, w1, w2)
        f, fe, snr = matched(phot["flux"], phot["err"], tpl)
        n_ch = int(np.sum(np.isfinite(phot["flux"])))
        res = {k: None for k in SPHEREX_KEYS}
        res.update({"checked": True, "confirmed": False, "epoch": plan.epoch, "tile": plan.tile,
                    "expected_offset": plan.expected, "notes": notes, "error": None})
        if n_ch == 0:
            res["checked"] = False
            res["error"] = "no usable SPHEREx data at the predicted position (edge, gap or saturated)"
            return res
        # (channels the cube lists as blank, BLANKCH, are simply gaps in the spectrum: no note on every mover)
        if n_ch < lay.nplanes - len(lay.blank):
            notes.append(f"{lay.nplanes - len(lay.blank) - n_ch} channels unusable here (no data or saturated)")
        detected = snr is not None and snr >= DETECT_SNR
        res["snr"] = snr
        res["detected"] = bool(detected)
        cen = centroid(s.values, s.xi, s.eta, phot["bkg"], phot["sig"], s.pix_arcsec, template=tpl) \
            if detected else None
        sigma = None
        if cen is not None:
            cx, cy, ce = cen
            sigma = math.hypot(ce, plan.sigma_extra)
            res["offset_arcsec"] = math.hypot(cx, cy)
            res["offset_err"] = sigma
        # the 2014 position
        old_snr = f_old = None
        if plan.old_stamp is not None and plan.old_stamp.values is not None:
            o = plan.old_stamp
            op = with_floor(aperture_photometry(o.values, o.xi, o.eta, o.pix_arcsec, lay.pix_sr))
            f_old, _, old_snr = matched(op["flux"], op["err"], tpl)
        res["old_snr"] = old_snr
        res["gone_from_2014"] = gone_verdict(old_snr, f_old, f if detected else None)
        # NEOWISE vs SPHEREx brightness at 4-5 um (a brighter neighbour inside a 13" pixel shows up here)
        # (not for saturated NEOWISE photometry, which is unreliable: W2 < 6.7, as in survey.rank)
        res["w2_ratio"] = w2_ratio(lay.wavelengths, phot["flux"], phot["err"], w2) \
            if w2 is not None and w2 >= W2_SATURATION else None
        # verdicts
        at = None
        if detected and cen is not None:
            off = res["offset_arcsec"]
            if off <= OFFSET_SIGMA * sigma:
                at = True
            elif off > 0.5 * R_AP * s.pix_arcsec:
                at = False
                notes.append(f"The light near the predicted spot is centred {off:.0f}″ away: a neighbour, "
                             "or the motion is wrong")
        elif not detected and res["gone_from_2014"] is False:
            at = False
            notes.append("Nothing at the predicted spot, but a source sits at its 2014 position")
        r2 = res["w2_ratio"]
        if at and r2 is not None and not (1.0 / W2_RATIO_MAX <= r2 <= W2_RATIO_MAX):
            at = None
            notes.append(f"SPHEREx sees {r2:.1f}× the 4–5 µm light NEOWISE measured for it: probably another "
                         "source in SPHEREx's 13″ pixels, so this does not confirm it")
        res["at_predicted"] = at
        if at and plan.old is not None and cen is not None:
            # where is the centroid relative to the 2014 position?
            xo, yo = tangent_offsets(plan.old[0], plan.old[1], plan.pred[0], plan.pred[1])
            d_old = math.hypot(float(xo) - cen[0], float(yo) - cen[1])
            # SPHEREx sees the motion when the two positions are 3 sigma apart from each other's 3-sigma circle
            resolved = (plan.expected or 0.0) > 2 * OFFSET_SIGMA * sigma and d_old > OFFSET_SIGMA * sigma
            res["confirmed"] = bool(resolved and res["gone_from_2014"] is not False)
            if not resolved:
                notes.append("Too slow for SPHEREx's ~13″ pixels to see the motion; this only shows a source is there")
            elif res["gone_from_2014"] is False:
                notes.append("A source is also at its 2014 position (a background star, or the motion is wrong)")
        elif not detected:
            notes.append("Not detected by SPHEREx (S/N < 5 in the channels NEOWISE's bands cover): too faint, "
                         "or not there")
        if detected:
            groups = band_groups(lay.detectors, lay.subchans)
            bands = rebin_spectrum(lay.wavelengths, phot["flux"], phot["err"], groups)
            res["spectrum"] = {k: bands[k].tolist() for k in SPECTRUM_KEYS}
            if at:      # a spectrum of light centred elsewhere says nothing about the mover
                res["indices"] = spectral_indices(lay.wavelengths, phot["flux"], phot["err"], bands)
            else:
                notes.append("Spectral hints are given only for a source centred on the predicted spot")
        return res

    # ---- driver
    def check_tile(self, k5: int, movers: list[dict], deadline: float | None = None) -> list[dict]:
        """SPHEREx dicts for the movers of tile k5, in order. Never raises."""
        t0 = self.clock()
        n = len(movers)
        out: list[dict | None] = [None] * n
        try:
            home = self.layout(k5)
        except NetworkError as e:
            return [compact(unchecked(f"{NETWORK}{e}")) for _ in movers]
        except CubeMissing:
            return [compact(unchecked("no SPHEREx cube for this tile")) for _ in movers]
        except Exception as e:  # noqa: BLE001
            log.warning("SPHEREx tile %s unreadable (%s: %s)", k5, type(e).__name__, e)
            return [compact(unchecked(f"SPHEREx cube unreadable: {e}")) for _ in movers]
        plans = []
        for i, m in enumerate(movers):
            try:
                p = self._plan(i, m if isinstance(m, dict) else {}, home)
            except NetworkError as e:
                p = unchecked(f"{NETWORK}{e}")
            except CubeMissing:
                p = unchecked("no SPHEREx cube where it should be now")
            except Exception as e:  # noqa: BLE001
                log.warning("SPHEREx plan failed for %s (%s: %s)", m.get("id") if isinstance(m, dict) else i,
                            type(e).__name__, e)
                p = unchecked(f"internal error: {type(e).__name__}")
            if isinstance(p, dict):
                out[i] = p
            else:
                plans.append(p)
        for b in range(0, len(plans), BATCH_MOVERS):
            batch = plans[b:b + BATCH_MOVERS]
            if deadline is not None and self.clock() > deadline:
                for p in batch:
                    out[p.idx] = unchecked(BUDGET)
                continue
            stamps = [p.stamp for p in batch] + [p.old_stamp for p in batch if p.old_stamp is not None]
            try:
                self._fetch(stamps, deadline)
            except BudgetExceeded:
                for p in batch:
                    out[p.idx] = unchecked(BUDGET)
                continue
            except NetworkError as e:
                for p in batch:
                    out[p.idx] = unchecked(f"{NETWORK}{e}")
                continue
            except Exception as e:  # noqa: BLE001
                log.warning("SPHEREx read failed on tile %s (%s: %s)", k5, type(e).__name__, e)
                for p in batch:
                    out[p.idx] = unchecked(f"read error: {type(e).__name__}: {str(e)[:120]}")
                continue
            for p in batch:
                try:
                    out[p.idx] = self._measure(p)
                except Exception as e:  # noqa: BLE001
                    log.warning("SPHEREx measurement failed (%s: %s)", type(e).__name__, e)
                    out[p.idx] = unchecked(f"internal error: {type(e).__name__}")
        self.stats["movers"] += n
        self.stats["seconds"] += self.clock() - t0
        return [compact(r) for r in out]


def _first_epoch(m: dict) -> float | None:
    """Epoch of the first NEOWISE visit (track[0]); else epoch - span/2; else None."""
    tr = m.get("track")
    if isinstance(tr, list) and tr and isinstance(tr[0], (list, tuple)) and tr[0]:
        v = _float(tr[0][0])
        if v is not None:
            return v
    ep, span = _float(m.get("epoch")), _float(m.get("span_yr"))
    if ep is not None and span is not None:
        return ep - span / 2.0
    return None


_DEFAULT: SpherexStage | None = None


def default_stage() -> SpherexStage:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = SpherexStage()
    return _DEFAULT


def check_tile(k5: int, movers: list[dict], deadline: float | None = None, stage: SpherexStage | None = None) -> list:
    """Module-level entry point for the runner: SPHEREx dicts for the movers of tile k5 (never raises)."""
    try:
        return (stage or default_stage()).check_tile(k5, movers, deadline=deadline)
    except Exception as e:  # noqa: BLE001 - belt and braces: the stage itself should never raise
        log.warning("SPHEREx stage failed on tile %s (%s: %s)", k5, type(e).__name__, e)
        return [compact(unchecked(f"internal error: {type(e).__name__}")) for _ in movers]


# ---------------------------------------------------------------------------------------------- CLI
def _load_movers(ns) -> list[tuple[int, list[dict]]]:
    groups: dict[int, list] = defaultdict(list)
    if ns.tile_file:
        for p in ns.tile_file:
            t = json.loads(Path(p).read_text(encoding="utf-8"))
            for m in t.get("movers", []):
                groups[int(t["k5"])].append(m)
    if ns.leaderboard:
        lb = json.loads(Path(ns.leaderboard).read_text(encoding="utf-8"))
        rows = [c for c in lb.get("candidates", []) if not ns.cls or c.get("class") == ns.cls]
        for c in rows[:ns.top]:
            groups[int(c["k5"])].append(c)
    if ns.ids:
        want = set(ns.ids.split(","))
        groups = {k: [m for m in v if str(m.get("id")) in want] for k, v in groups.items()}
    return [(k, v) for k, v in groups.items() if v]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="SPHEREx check of survey movers (reads only small byte ranges).")
    ap.add_argument("--tile-file", action="append", help="tiles/<k5>.json (repeatable)")
    ap.add_argument("--leaderboard", help="leaderboard.json")
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--class", dest="cls", default=None, help="only leaderboard rows of this class")
    ap.add_argument("--ids", default=None, help="comma-separated mover ids")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--out", default=None, help="write the results as JSON here")
    ns = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stage = SpherexStage(workers=ns.workers)
    rows = []
    for k5, movers in _load_movers(ns):
        b0, q0, t0 = stage.bytes_read, stage.requests, time.monotonic()
        res = stage.check_tile(k5, movers)
        dt, db, dq = time.monotonic() - t0, stage.bytes_read - b0, stage.requests - q0
        for m, r in zip(movers, res):
            rows.append({"id": m.get("id"), "k5": k5, "pm": m.get("pm"), "w1w2": m.get("w1w2"),
                         "class": m.get("class"), "spherex": r,
                         "tile_seconds": round(dt, 2), "tile_bytes": db, "tile_requests": dq, "tile_movers": len(movers)})
            ix = r.get("indices") or {}
            print(f"{m.get('id'):>12} pm={m.get('pm')!s:>8} det={r['detected']!s:>5} snr={r['snr']!s:>7} "
                  f"off={r['offset_arcsec']!s:>6}±{r['offset_err']!s:<5} exp={r['expected_offset']!s:>7} "
                  f"at={r['at_predicted']!s:>5} gone={r['gone_from_2014']!s:>5} conf={r['confirmed']!s:>5} "
                  f"w1w2={ix.get('w1w2')!s}{'(lim)' if ix.get('w1w2_lim') else ''} ch4={ix.get('ch4_depth')!s} "
                  f"peak={ix.get('peak_um')!s} err={r['error']} | {dt:.1f}s {db / 1e6:.1f}MB {dq}req/{len(movers)}",
                  flush=True)
    if ns.out:
        Path(ns.out).write_text(json.dumps({"rows": rows, "bytes": stage.bytes_read, "requests": stage.requests},
                                           indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != _HERE]
    sys.exit(main())
