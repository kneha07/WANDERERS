"""WANDERERS Sky Survey validation: evidence that the automated mover search works, and where it stops working.

Four checks, all against the interface in docs/survey-contract.md (`process_tile(k5, reader=..., years=...)`):

1. Injection-recovery. Synthetic movers with known motion and brightness are added to synthetic NEOWISE skies
   that use the real NEOWISE cadence (the exposure times, scan ids and frame numbers are copied from real data),
   the search is run blind, and we count how many come back (completeness vs motion and W2 magnitude).
2. Motion accuracy. For every recovered mover: |pm_found - pm_true| / pm_true, the position-angle error, and how
   well the reported pm_err describes the real error.
3. False positives. The search is run on "empty" synthetic skies: stars that barely move (< 60 mas/yr, far below
   the 150 mas/yr mover cut), red background galaxies, single-visit Solar-System-like objects, single spurious
   detections, and diffraction-spike artefacts around bright stars (most flagged, a few not). Every mover the
   search reports there is false.
4. Known movers (`--real`). The search runs on real NEOWISE detections around Kapteyn's Star and WISE 0855-0714
   (tests/fixtures) and, when survey results exist, on the validation tiles; the motions it finds are compared with
   Gaia DR3 and the literature.

Noise model (calibrated on the two real 4-arcmin NEOWISE fixtures, 2014-2024; see NOISE below):
- single-exposure SNR per band: 1/SNR^2 = (F/5)^2 + g F/25 + floor^2 with F = 10^(0.4 (m - m5)); W2 reaches
  SNR 5 at W2 = 14.34 and W1 at W1 = 16.02 (rms misfit 4 % and 1 %); SNR saturates near 60-70 for bright stars.
- reported position error sigra = 3.25"/SNR, sigdec = 3.55"/SNR, with SNR = sqrt(w1snr^2 + w2snr^2);
  the true scatter is larger: sqrt((1.15 sigma)^2 + 0.045"^2) (measured on 137 + 75 stationary stars), plus up to
  1" for saturated stars (W1 < 8, W2 < 6.5; Kapteyn's Star at W2 = 5.8 scatters by ~0.9" per exposure).
- a row is written when the combined measured SNR >= 3 (the real table has many rows below the SNR 5 quality cut).
So astrometry is ~0.06" per exposure at W2 = 10, ~0.15" at W2 = 14 (W1 - W2 = 0) and ~0.5-0.7" near the limit.

CLI:
    python pipeline/survey/validate.py --out app/data/survey/validation.json [--trials N] [--real]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import importlib
import importlib.util
import itertools
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

if __package__ in (None, ""):  # run as a script: make `survey` importable (pipeline/ on sys.path)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
DEFAULT_OUT = ROOT / "app" / "data" / "survey" / "validation.json"
DEFAULT_TILES_DIR = ROOT / "app" / "data" / "survey" / "tiles"

# ----------------------------------------------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------------------------------------------
PM_GRID_ARCSEC = (0.2, 0.5, 1.0, 2.0, 4.0, 8.0, 11.0)  # injected proper motions, arcsec/yr
W2_GRID = (8.0, 11.0, 13.0, 14.5, 15.5)                 # injected W2 magnitudes (Vega)
COLOURS = (0.0,)                                        # injected W1 - W2 (0 = star-like; 2 = cold brown dwarf)
YEAR_LABELS = [f"year{i}" for i in range(1, 12)] + ["addendum"]
NEOWISE_START_MJD = 56639.0       # 2013-12-13, start of NEOWISE-R year 1 (used only to split tables by "year")
NSIDE = 32
N_TILES = 12 * NSIDE * NSIDE
TILE_AREA_DEG2 = 4 * math.pi * (180 / math.pi) ** 2 / N_TILES  # 3.357 deg^2
MJD_J2000 = 51544.5
KM_S_PER_AU_YR = 4.740470446       # v_tan [km/s] = 4.74 * mu ["/yr] / plx ["]

COLUMNS = ["source_id", "ra", "dec", "sigra", "sigdec", "sigradec", "mjd", "w1mpro", "w1sigmpro", "w1snr",
           "w2mpro", "w2sigmpro", "w2snr", "cc_flags", "ph_qual", "nb", "na", "qual_frame", "qi_fact", "saa_sep",
           "moon_masked", "scan_id", "frame_num"]
_TYPES = {"source_id": pa.string(), "cc_flags": pa.string(), "ph_qual": pa.string(), "moon_masked": pa.string(),
          "scan_id": pa.string(), "nb": pa.int64(), "na": pa.int64(), "qual_frame": pa.int64(),
          "frame_num": pa.int64()}
SCHEMA = pa.schema([pa.field(c, _TYPES.get(c, pa.float64()), nullable=True) for c in COLUMNS])

# Noise model, calibrated on tests/fixtures (see module docstring). Change only with new measurements.
NOISE = {
    "w1": {"m5": 16.02, "src": 0.203, "floor": 0.0140, "sat": 8.0},
    "w2": {"m5": 14.34, "src": 0.0886, "floor": 0.0150, "sat": 6.5},
    "sig_ra_coeff": 3.25,      # reported sigra  ~ 3.25" / combined SNR
    "sig_dec_coeff": 3.55,     # reported sigdec ~ 3.55" / combined SNR
    "scatter_scale": 1.15,     # true scatter = sqrt((1.15 * reported)^2 + floor^2)
    "scatter_floor": 0.045,    # arcsec
    "sat_slope": 0.45,         # extra scatter per magnitude brighter than saturation, arcsec
    "sat_max": 1.0,            # arcsec
    "cov_frac": -0.3,          # sigradec ~ -0.3 * sigra (signed square root of the RA/Dec covariance)
    "detect_snr": 3.0,         # a row exists when sqrt(w1snr^2 + w2snr^2) >= 3
}

# Known fast movers: Gaia DR3 (epoch 2016.0) as stored in app/data/<target>/target.json; WISE 0855 and Luhman 16
# motions are from the literature (Luhman & Esplin 2016; Bedin et al. 2017) because Gaia lacks or mis-measures them.
KNOWN_STARS = [
    {"name": "Barnard's Star", "ra": 269.44850252543836, "dec": 4.739420051112412, "epoch": 2016.0,
     "pmra": -801.5509783684709, "pmdec": 10362.394206546573, "plx": 546.975939730948, "ref": "Gaia DR3"},
    {"name": "Kapteyn's Star", "ra": 77.9599373502188, "dec": -45.0438126993602, "epoch": 2016.0,
     "pmra": 6491.223339061598, "pmdec": -5708.614150045243, "plx": 254.19859326384577, "ref": "Gaia DR3",
     "fixture": "neowise_kapteyn_4arcmin.parquet"},
    {"name": "WISE 0855-0714", "ra": 133.79513, "dec": -7.24515, "epoch": 2010.5,
     "pmra": -8123.0, "pmdec": 673.0, "plx": 449.0, "ref": "Luhman & Esplin 2016",
     "fixture": "neowise_wise0855_4arcmin.parquet"},
    {"name": "Luhman 16", "ra": 162.3084022, "dec": -53.3180448, "epoch": 2016.0,
     "pmra": -2762.0, "pmdec": 357.0, "plx": 501.0, "ref": "Gaia DR3 position; Bedin et al. 2017 motion"},
    {"name": "Wolf 359", "ra": 164.10319030755974, "dec": 7.002726940984864, "epoch": 2016.0,
     "pmra": -3866.3382751436793, "pmdec": -2699.214987679166, "plx": 415.17941567802137, "ref": "Gaia DR3"},
    {"name": "Lalande 21185", "ra": 165.83095967577933, "dec": 35.948653032660104, "epoch": 2016.0,
     "pmra": -580.0570872139048, "pmdec": -4776.588719443488, "plx": 392.75294543876464, "ref": "Gaia DR3"},
    {"name": "Proxima Centauri", "ra": 217.39232147200883, "dec": -62.67607511676666, "epoch": 2016.0,
     "pmra": -3781.741008265163, "pmdec": 769.4650146478623, "plx": 768.0665391873573, "ref": "Gaia DR3"},
    {"name": "61 Cygni A", "ra": 316.7484792940004, "dec": 38.76386244649797, "epoch": 2016.0,
     "pmra": 4164.2086922846665, "pmdec": 3249.613883848584, "plx": 285.99494829578117, "ref": "Gaia DR3"},
    {"name": "Epsilon Indi B", "ra": 331.07645259656397, "dec": -56.79381206688221, "epoch": 2016.0,
     "pmra": 3981.97666296105, "pmdec": -2466.8318147663504, "plx": 270.6580324694526, "ref": "Gaia DR3"},
]


# ----------------------------------------------------------------------------------------------------------------
# Small astrometry helpers (degrees, arcsec, decimal years)
# ----------------------------------------------------------------------------------------------------------------
def mjd_to_year(mjd):
    """Decimal (Julian) year: 2000.0 + (MJD - 51544.5) / 365.25."""
    return 2000.0 + (np.asarray(mjd, dtype=float) - MJD_J2000) / 365.25


def year_to_mjd(year):
    return MJD_J2000 + (np.asarray(year, dtype=float) - 2000.0) * 365.25


def offset_radec(ra0, dec0, dx_arcsec, dy_arcsec):
    """Position offset by (dx east, dy north) arcsec on the gnomonic tangent plane at (ra0, dec0).
    Exact on the sphere, so it works across RA = 0/360 and next to the poles. Returns RA in [0, 360)."""
    a0, d0 = np.radians(ra0), np.radians(dec0)
    xi = np.radians(np.asarray(dx_arcsec, dtype=float) / 3600.0)
    eta = np.radians(np.asarray(dy_arcsec, dtype=float) / 3600.0)
    den = np.cos(d0) - eta * np.sin(d0)
    ra = np.degrees(a0 + np.arctan2(xi, den)) % 360.0
    dec = np.degrees(np.arctan2(np.sin(d0) + eta * np.cos(d0), np.hypot(xi, den)))
    return ra, dec


def tangent_offset(ra0, dec0, ra, dec):
    """Gnomonic (dx east, dy north) arcsec of (ra, dec) on the tangent plane at (ra0, dec0)."""
    a0, d0 = np.radians(ra0), np.radians(dec0)
    a, d = np.radians(ra), np.radians(dec)
    cosc = np.sin(d0) * np.sin(d) + np.cos(d0) * np.cos(d) * np.cos(a - a0)
    xi = np.cos(d) * np.sin(a - a0) / cosc
    eta = (np.cos(d0) * np.sin(d) - np.sin(d0) * np.cos(d) * np.cos(a - a0)) / cosc
    return np.degrees(xi) * 3600.0, np.degrees(eta) * 3600.0


def sep_arcsec(ra1, dec1, ra2, dec2):
    """Great-circle separation (haversine), arcsec."""
    a1, d1, a2, d2 = map(np.radians, (ra1, dec1, ra2, dec2))
    h = np.sin((d2 - d1) / 2) ** 2 + np.cos(d1) * np.cos(d2) * np.sin((a2 - a1) / 2) ** 2
    return np.degrees(2 * np.arcsin(np.sqrt(np.clip(h, 0, 1)))) * 3600.0


def destination(ra0, dec0, sep_deg, pa_deg):
    """Point at angular distance sep_deg and position angle pa_deg (east of north) from (ra0, dec0)."""
    d0, a0 = np.radians(dec0), np.radians(ra0)
    s, p = np.radians(sep_deg), np.radians(pa_deg)
    dec = np.arcsin(np.sin(d0) * np.cos(s) + np.cos(d0) * np.sin(s) * np.cos(p))
    ra = a0 + np.arctan2(np.sin(p) * np.sin(s) * np.cos(d0), np.cos(s) - np.sin(d0) * np.sin(dec))
    return np.degrees(ra) % 360.0, np.degrees(dec)


def propagate(ra, dec, epoch, pmra, pmdec, to_epoch):
    """Linear proper-motion propagation on the tangent plane (pmra includes cos dec, mas/yr). No parallax."""
    dt = np.asarray(to_epoch, dtype=float) - np.asarray(epoch, dtype=float)
    return offset_radec(ra, dec, np.asarray(pmra) / 1000.0 * dt, np.asarray(pmdec) / 1000.0 * dt)


def cap_area_deg2(radius_deg):
    """Area of a spherical cap of the given angular radius, deg^2."""
    return 2 * math.pi * (1 - math.cos(math.radians(radius_deg))) * (180 / math.pi) ** 2


def earth_xyz_au(mjd):
    """Barycentric Earth position (AU, ICRS axes) from astropy's built-in ephemeris (offline). Shape (3, n)."""
    from astropy.coordinates import get_body_barycentric
    from astropy.time import Time
    pos = get_body_barycentric("earth", Time(np.atleast_1d(np.asarray(mjd, dtype=float)), format="mjd", scale="tdb"),
                               ephemeris="builtin")
    return np.vstack([pos.x.to_value("AU"), pos.y.to_value("AU"), pos.z.to_value("AU")])


def parallax_factors(ra, dec, mjd, xyz=None):
    """(f_east, f_north): apparent displacement per unit parallax (east includes cos dec).
    d(ra*) = plx (X sin a - Y cos a); d(dec) = plx (X cos a sin d + Y sin a sin d - Z cos d),
    with (X, Y, Z) the Earth's barycentric position in AU (WISE orbits the Earth, so this is close enough)."""
    X, Y, Z = earth_xyz_au(mjd) if xyz is None else xyz
    a, d = np.radians(ra), np.radians(dec)
    fe = X * np.sin(a) - Y * np.cos(a)
    fn = X * np.cos(a) * np.sin(d) + Y * np.sin(a) * np.sin(d) - Z * np.cos(d)
    return fe, fn


def pm_from_vtan(pm_mas_yr, vtan_kms):
    """Parallax (mas) of a star with this proper motion and tangential velocity: plx = 4.74 mu / v_tan."""
    if not vtan_kms:
        return 0.0
    return KM_S_PER_AU_YR * float(pm_mas_yr) / float(vtan_kms)


# ----------------------------------------------------------------------------------------------------------------
# HEALPix tiles (from survey.tiles when present, else astropy-healpix, which reproject already requires)
# ----------------------------------------------------------------------------------------------------------------
def _healpix():
    from astropy_healpix import HEALPix
    return HEALPix(nside=NSIDE, order="nested")


def tile_of(ra, dec):
    try:
        from survey import tiles as _tiles  # noqa: PLC0415
        return int(_tiles.tile_of(ra, dec))
    except ImportError:
        import astropy.units as u
        return int(_healpix().lonlat_to_healpix(float(ra) * u.deg, float(dec) * u.deg))


def tile_center(k5):
    try:
        from survey import tiles as _tiles  # noqa: PLC0415
        ra, dec = _tiles.tile_center(int(k5))
        return float(ra), float(dec)
    except ImportError:
        lon, lat = _healpix().healpix_to_lonlat(int(k5))
        return float(lon.deg), float(lat.deg)


# ----------------------------------------------------------------------------------------------------------------
# Noise model
# ----------------------------------------------------------------------------------------------------------------
def snr_model(mag, band="w2", noise=NOISE):
    """Expected single-exposure SNR of a point source of this magnitude in band 'w1' or 'w2'."""
    p = noise[band]
    f = 10 ** (0.4 * (np.asarray(mag, dtype=float) - p["m5"]))
    return 1.0 / np.sqrt((f / 5.0) ** 2 + p["src"] * f / 25.0 + p["floor"] ** 2)


def reported_sigma(snr_comb, noise=NOISE):
    """(sigra, sigdec) the NEOWISE pipeline reports for a detection of this combined SNR, arcsec."""
    s = np.maximum(np.asarray(snr_comb, dtype=float), 1e-3)
    return noise["sig_ra_coeff"] / s, noise["sig_dec_coeff"] / s


def saturation_scatter(w1, w2, noise=NOISE):
    """Extra positional scatter (arcsec) of saturated stars, growing 0.45"/mag beyond saturation, up to 1"."""
    over = np.maximum(np.maximum(noise["w1"]["sat"] - np.asarray(w1, float), noise["w2"]["sat"] - np.asarray(w2, float)), 0)
    return np.minimum(noise["sat_slope"] * over, noise["sat_max"])


def true_sigma(w1, w2, noise=NOISE):
    """(sigma_ra, sigma_dec): the real per-exposure positional scatter (arcsec) at these magnitudes."""
    s1, s2 = snr_model(w1, "w1", noise), snr_model(w2, "w2", noise)
    sr, sd = reported_sigma(np.hypot(s1, s2), noise)
    extra = noise["scatter_floor"] ** 2 + saturation_scatter(w1, w2, noise) ** 2
    k = noise["scatter_scale"]
    return np.sqrt((k * sr) ** 2 + extra), np.sqrt((k * sd) ** 2 + extra)


def ph_qual_letter(snr):
    """WISE photometric quality: A (SNR >= 10), B (3 < SNR < 10), C (2 <= SNR <= 3), U (< 2)."""
    s = np.asarray(snr, dtype=float)
    return np.where(s >= 10, "A", np.where(s > 3, "B", np.where(s >= 2, "C", "U")))


# ----------------------------------------------------------------------------------------------------------------
# Cadence
# ----------------------------------------------------------------------------------------------------------------
def _col(table, name):
    return table.column(name).to_numpy(zero_copy_only=False)


def exposures(table, near=None, radius_arcsec=60.0):
    """The exposures (frames) in a detection table: dict of sorted, unique `mjd`, `scan_id`, `frame_num`.
    With `near=(ra, dec)` only frames holding a detection within `radius_arcsec` are used (they cover that spot;
    in the WISE 0855 fixture the count is flat at ~320-330 of 439 frames for radii of 30-60", and grows slowly
    beyond as frame edges come in); the radius doubles until something is found, else the whole table is used."""
    mjd = np.asarray(_col(table, "mjd"), dtype=float)
    rows = np.arange(len(mjd))
    if near is not None and len(mjd):
        ra, dec = np.asarray(_col(table, "ra"), float), np.asarray(_col(table, "dec"), float)
        ddec = np.abs(dec - float(near[1])) * 3600.0   # cheap pre-cut, so a 20M-row tile stays fast
        r = float(radius_arcsec)
        while True:
            cand = np.nonzero(ddec <= r)[0]
            sel = cand[sep_arcsec(near[0], near[1], ra[cand], dec[cand]) <= r]
            if len(sel) or r > 3600 * 5:
                break
            r *= 2
        if len(sel):
            rows = sel
    if not len(rows):
        return {"mjd": np.zeros(0), "scan_id": np.zeros(0, dtype=object), "frame_num": np.zeros(0, dtype=np.int64)}
    u, first = np.unique(mjd[rows], return_index=True)
    idx = pa.array(rows[first])
    names = table.column_names
    scan = np.asarray(table.column("scan_id").take(idx).to_numpy(zero_copy_only=False), dtype=object) \
        if "scan_id" in names else np.array([f"{70000 + i % 30000:05d}z" for i in range(len(u))], dtype=object)
    frame = np.asarray(table.column("frame_num").take(idx).to_numpy(zero_copy_only=False), dtype=np.int64) \
        if "frame_num" in names else np.full(len(u), 100, dtype=np.int64)
    return {"mjd": u, "scan_id": scan, "frame_num": frame}


def split_visits(mjd, gap_days=20.0):
    """Visit index per time (a new visit after a gap > gap_days), for bookkeeping in this module."""
    mjd = np.asarray(mjd, dtype=float)
    if not len(mjd):
        return np.zeros(0, dtype=int)
    o = np.argsort(mjd)
    v = np.zeros(len(mjd), dtype=int)
    v[o] = np.concatenate([[0], np.cumsum(np.diff(mjd[o]) > gap_days)])
    return v


def synthetic_cadence(rng=None, n_visits=21, start_mjd=56700.0, period_days=182.6, per_visit=14,
                      spacing_hours=1.574, overlap_fraction=0.1):
    """A NEOWISE-like cadence without real data: n_visits ~6 months apart, each `per_visit` exposures one orbit
    (1.574 h) apart, plus a few frame-overlap duplicates 11 s later in the same scan."""
    rng = np.random.default_rng(rng)
    mjd, scan, frame = [], [], []
    for v in range(n_visits):
        t0 = start_mjd + v * period_days + rng.uniform(-3, 3)
        for k in range(per_visit):
            t = t0 + k * spacing_hours / 24.0
            s = f"{60000 + (v * 100 + k) % 40000:05d}{'ab'[k % 2]}"
            f = int(rng.integers(10, 190))
            mjd.append(t), scan.append(s), frame.append(f)
            if rng.random() < overlap_fraction:
                mjd.append(t + 11.0 / 86400.0), scan.append(s), frame.append(f + 1)
    o = np.argsort(mjd)
    return {"mjd": np.asarray(mjd)[o], "scan_id": np.asarray(scan, dtype=object)[o],
            "frame_num": np.asarray(frame, dtype=np.int64)[o]}


# ----------------------------------------------------------------------------------------------------------------
# Detection simulation (vectorised over sources x exposures)
# ----------------------------------------------------------------------------------------------------------------
def _simulate(src, exp, rng, noise=True, noise_model=NOISE, detect_snr=None, exp_mask=None, xyz=None):
    """Detections of point sources in a list of exposures.
    src: dict of equal-length arrays ra, dec, epoch, pmra, pmdec, plx (mas), w1, w2.
    exp: dict of mjd, scan_id, frame_num. exp_mask: optional (n_src, n_exp) bool, exposures that see each source.
    Returns a dict of flat column arrays plus `src` (source index) and `exp` (exposure index)."""
    detect_snr = noise_model["detect_snr"] if detect_snr is None else detect_snr
    n_src, n_exp = len(src["ra"]), len(exp["mjd"])
    if n_src == 0 or n_exp == 0:
        return None
    t = mjd_to_year(exp["mjd"])[None, :]
    dt = t - np.asarray(src["epoch"], float)[:, None]
    dx = np.asarray(src["pmra"], float)[:, None] / 1000.0 * dt
    dy = np.asarray(src["pmdec"], float)[:, None] / 1000.0 * dt
    plx = np.asarray(src["plx"], float)
    if np.any(plx != 0):
        xyz = earth_xyz_au(exp["mjd"]) if xyz is None else xyz
        fe, fn = parallax_factors(np.asarray(src["ra"], float)[:, None], np.asarray(src["dec"], float)[:, None],
                                  None, xyz=(xyz[0][None, :], xyz[1][None, :], xyz[2][None, :]))
        dx = dx + plx[:, None] / 1000.0 * fe
        dy = dy + plx[:, None] / 1000.0 * fn
    w1 = np.asarray(src["w1"], float)[:, None] * np.ones((1, n_exp))
    w2 = np.asarray(src["w2"], float)[:, None] * np.ones((1, n_exp))
    s1t, s2t = snr_model(w1, "w1", noise_model), snr_model(w2, "w2", noise_model)
    if noise:
        s1 = s1t + rng.standard_normal(s1t.shape)
        s2 = s2t + rng.standard_normal(s2t.shape)
    else:
        s1, s2 = s1t.copy(), s2t.copy()
    comb = np.hypot(np.maximum(s1, 0), np.maximum(s2, 0))
    keep = comb >= detect_snr if noise else np.ones(comb.shape, bool)
    if exp_mask is not None:
        keep &= exp_mask
    si, ei = np.nonzero(keep)
    if not len(si):
        return None
    s1, s2, s1t, s2t, w1, w2 = (a[si, ei] for a in (s1, s2, s1t, s2t, w1, w2))
    dx, dy, comb = dx[si, ei], dy[si, ei], comb[si, ei]
    sig_ra, sig_dec = reported_sigma(comb, noise_model)
    if noise:
        tr, td = true_sigma(w1, w2, noise_model)
        rho = np.sign(noise_model["cov_frac"]) * noise_model["cov_frac"] ** 2
        e1 = rng.standard_normal(len(si))
        e2 = rho * e1 + math.sqrt(1 - rho ** 2) * rng.standard_normal(len(si))
        dx = dx + tr * e1
        dy = dy + td * e2
    ra, dec = offset_radec(np.asarray(src["ra"], float)[si], np.asarray(src["dec"], float)[si], dx, dy)
    out = {"src": si, "exp": ei, "ra": np.round(ra, 7), "dec": np.round(dec, 7),
           "sigra": np.round(sig_ra, 4), "sigdec": np.round(sig_dec, 4),
           "sigradec": np.round(noise_model["cov_frac"] * sig_ra, 4),
           "mjd": np.asarray(exp["mjd"], float)[ei],
           "scan_id": np.asarray(exp["scan_id"], dtype=object)[ei],
           "frame_num": np.asarray(exp["frame_num"], dtype=np.int64)[ei]}
    for band, s, st, m in (("w1", s1, s1t, w1), ("w2", s2, s2t, w2)):
        s = np.round(s, 1)
        det = s >= 2
        mag = np.where(det, m - 2.5 * np.log10(np.maximum(s, 1e-3) / st),
                       m - 2.5 * np.log10((np.maximum(s, 0) + 2.0) / st))   # 2-sigma upper limit
        out[f"{band}mpro"] = np.round(mag, 3)
        out[f"{band}sigmpro"] = np.where(det, np.round(1.0857 / np.maximum(s, 1e-3), 3), np.nan)
        out[f"{band}snr"] = s
    q1, q2 = ph_qual_letter(out["w1snr"]), ph_qual_letter(out["w2snr"])
    out["ph_qual"] = np.char.add(q1, q2).astype(object)
    n = len(si)
    out["cc_flags"] = np.full(n, "0000", dtype=object)
    out["moon_masked"] = np.full(n, "00", dtype=object)
    out["nb"] = np.ones(n, dtype=np.int64)
    out["na"] = np.zeros(n, dtype=np.int64)
    out["qual_frame"] = np.full(n, 10, dtype=np.int64)
    out["qi_fact"] = np.ones(n)
    out["saa_sep"] = np.full(n, 100.0)
    return out


def _concat_cols(parts):
    parts = [p for p in parts if p is not None]
    if not parts:
        return None
    keys = parts[0].keys()
    return {k: np.concatenate([p[k] for p in parts]) for k in keys}


def _source_ids(scan_id, frame_num, start=1, taken=None):
    """'<scan_id><frame:03d>-<NNNNNN>' with a running number per exposure; numbers in `taken` are skipped."""
    n = len(scan_id)
    if not n:
        return np.zeros(0, dtype=object)
    key = np.char.add(np.asarray(scan_id, dtype=str), np.char.zfill(np.asarray(frame_num).astype(str), 3))
    order = np.argsort(key, kind="stable")
    ks = key[order]
    first = np.r_[True, ks[1:] != ks[:-1]]
    grp_start = np.maximum.accumulate(np.where(first, np.arange(n), 0))
    rank = np.arange(n) - grp_start
    num = np.empty(n, dtype=np.int64)
    num[order] = start + rank
    ids = np.array([f"{k}-{c:06d}" for k, c in zip(key, num)], dtype=object)
    if taken:
        bump = n
        for i in range(n):
            while ids[i] in taken:
                num[i] += bump
                ids[i] = f"{key[i]}-{num[i]:06d}"
    return ids


def _to_table(cols, schema):
    """pyarrow table in `schema` from a dict of numpy columns (NaN -> null for floats)."""
    n = len(cols["ra"]) if cols else 0
    arrays = []
    for f in schema:
        v = cols.get(f.name) if cols else None
        if v is None:
            arrays.append(pa.nulls(n, type=f.type))
        elif pa.types.is_floating(f.type):
            arrays.append(pa.array(np.asarray(v, dtype=float), type=f.type, from_pandas=True))
        elif pa.types.is_integer(f.type):
            arrays.append(pa.array(np.asarray(v, dtype=np.int64), type=f.type))
        else:
            arrays.append(pa.array([None if x is None else str(x) for x in v], type=f.type))
    fields = [pa.field(f.name, f.type, nullable=f.nullable or a.null_count > 0, metadata=f.metadata)
              for f, a in zip(schema, arrays)]
    return pa.Table.from_arrays(arrays, schema=pa.schema(fields, metadata=schema.metadata))


def _concat_tables(tables, schema):
    """Concatenate tables whose fields may differ only in nullability; the result uses `schema` (made nullable
    where any input has nulls)."""
    loose = pa.schema([f.with_nullable(True) for f in schema], metadata=schema.metadata)
    out = pa.concat_tables([t.select(schema.names).cast(loose) for t in tables])
    final = pa.schema([f.with_nullable(f.nullable or out.column(f.name).null_count > 0) for f in schema],
                      metadata=schema.metadata)
    return out.cast(final)


# ----------------------------------------------------------------------------------------------------------------
# Injection
# ----------------------------------------------------------------------------------------------------------------
def normalize_spec(spec, exp=None):
    """Fill defaults of a mover spec. Keys: ra, dec (deg, at `epoch`); pmra, pmdec (mas/yr, pmra includes cos dec)
    or pm (mas/yr) + pa (deg east of north); w2; w1 or w1w2 (default 0); plx (mas, default 0); epoch (decimal
    year, default the mean epoch of the exposures, else 2019.0)."""
    s = dict(spec)
    if "ra" not in s or "dec" not in s:
        raise ValueError("mover spec needs ra and dec")
    if "pmra" not in s or "pmdec" not in s:
        pm, pa_deg = float(s.get("pm", 0.0)), float(s.get("pa", 0.0))
        s["pmra"], s["pmdec"] = pm * math.sin(math.radians(pa_deg)), pm * math.cos(math.radians(pa_deg))
    s["pm"] = float(math.hypot(s["pmra"], s["pmdec"]))
    s["pa"] = float(math.degrees(math.atan2(s["pmra"], s["pmdec"])) % 360.0)
    if "w2" not in s:
        raise ValueError("mover spec needs w2")
    if "w1" not in s:
        s["w1"] = float(s["w2"]) + float(s.get("w1w2", 0.0))
    s["w1w2"] = float(s["w1"]) - float(s["w2"])
    s.setdefault("plx", 0.0)
    if "epoch" not in s:
        s["epoch"] = float(np.mean(mjd_to_year(exp["mjd"]))) if exp is not None and len(exp["mjd"]) else 2019.0
    for k in ("ra", "dec", "pmra", "pmdec", "w1", "w2", "plx", "epoch"):
        s[k] = float(s[k])
    s["ra"] %= 360.0
    return s


def good_detection_mask(cols):
    """The contract's minimum astrometric quality cuts (survey/tiles.good_mask) on a dict of numpy columns."""
    cc = np.asarray(cols["cc_flags"], dtype=object)
    mm = np.asarray(cols["moon_masked"], dtype=object)
    w1 = np.nan_to_num(np.asarray(cols["w1snr"], float), nan=-1)
    w2 = np.nan_to_num(np.asarray(cols["w2snr"], float), nan=-1)
    return (np.array([str(c)[:2] == "00" for c in cc]) & (np.asarray(cols["qual_frame"]) > 0)
            & (np.asarray(cols["saa_sep"], float) > 0) & np.array([str(m)[:2] == "00" for m in mm])
            & (np.asarray(cols["nb"]) <= 2) & ((w1 >= 5) | (w2 >= 5)))


def inject(table, movers_spec, rng, *, cadence=None, local_radius_arcsec=60.0, noise=True, report=None,
           detect_snr=None, noise_model=NOISE):
    """Add synthetic detections of movers to a NEOWISE detection table and return the new table (same columns
    and types; the input rows come first, unchanged).

    The cadence is copied from the table: each mover is observed at the exposures (mjd, scan_id, frame_num) that
    hold detections within `local_radius_arcsec` of it, i.e. the frames that really covered that spot; pass
    `cadence` (dict of mjd, scan_id, frame_num) to force a cadence. Positions follow linear motion on the tangent
    plane plus parallax (`plx` in the spec), with per-exposure noise from NOISE; magnitudes, SNRs, errors and
    ph_qual are drawn consistently; quality columns are clean (cc_flags 0000, qual_frame 10, nb 1, na 0,
    saa_sep 100, moon_masked 00). Injected source_ids are unique ('<scan><frame>-9NNNNN').
    `report`: optional list; one dict per mover is appended (normalized spec, n_rows, n_good, n_visits_good)."""
    specs = [movers_spec] if isinstance(movers_spec, dict) else list(movers_spec)
    for c in ("ra", "dec", "mjd"):
        if c not in table.column_names:
            raise ValueError(f"table has no {c} column")
    if cadence is None and table.num_rows == 0:
        raise ValueError("empty table: pass cadence= to inject into it")
    parts, norm = [], []
    for spec in specs:
        exp = cadence if cadence is not None else exposures(table, near=(spec["ra"], spec["dec"]),
                                                             radius_arcsec=local_radius_arcsec)
        s = normalize_spec(spec, exp)
        norm.append(s)
        one = {k: np.array([s[k]]) for k in ("ra", "dec", "epoch", "pmra", "pmdec", "plx", "w1", "w2")}
        cols = _simulate(one, exp, rng, noise=noise, noise_model=noise_model, detect_snr=detect_snr)
        if report is not None:
            if cols is None:
                report.append({"spec": s, "n_rows": 0, "n_good": 0, "n_visits_good": 0})
            else:
                good = good_detection_mask(cols)
                v = split_visits(cols["mjd"])
                per_visit = np.bincount(v[good], minlength=v.max() + 1) if good.any() else np.zeros(1)
                report.append({"spec": s, "n_rows": int(len(cols["ra"])), "n_good": int(good.sum()),
                               "n_visits_good": int(np.sum(per_visit >= 2))})
        parts.append(cols)
    cols = _concat_cols(parts)
    if cols is None:
        return table
    taken = None
    if "source_id" in table.column_names and table.num_rows:
        import pyarrow.compute as pc  # only ids numbered like ours (>= 900000) can collide
        sid = table.column("source_id")
        taken = set(pc.filter(sid, pc.fill_null(pc.match_substring_regex(sid, r"-9\d{5,}$"), False)).to_pylist())
    cols["source_id"] = _source_ids(cols["scan_id"], cols["frame_num"], start=900000, taken=taken)
    new = _to_table(cols, table.schema)
    return _concat_tables([table, new], table.schema)


# ----------------------------------------------------------------------------------------------------------------
# Synthetic "empty" skies (no movers) for false-positive tests and as injection backgrounds
# ----------------------------------------------------------------------------------------------------------------
SKY_DEFAULTS = {
    "n15_per_deg2": 1100.0,     # sources brighter than W1 = 15 per deg^2 (fixtures, |b| ~ 25-35 deg: ~1000-1400)
    "alpha": 0.35,              # counts slope: N(<W1) ~ 10^(alpha W1) (fixtures: ~0.37 between W1 13 and 15)
    "w1_range": (7.0, 17.5),    # simulated W1 range (fainter sources still give occasional low-SNR rows)
    "galaxy_fraction": 0.10,    # red, stationary background galaxies (W1 - W2 ~ 0.8)
    "star_pm_sigma": 15.0,      # mas/yr per component for field stars
    "star_pm_max": 60.0,        # mas/yr cap: well below the 150 mas/yr mover cut, so any reported mover is false
    "transients_per_deg2": 5.0,  # single-visit Solar-System-like objects
    "artefacts_per_deg2_per_exposure": 30.0,  # single spurious clean detections
    "spike_w1": 9.5,            # stars brighter than this (W1) get diffraction-spike artefacts
    "unflagged_spike_fraction": 0.02,   # spike detections that escape cc_flags: around Kapteyn's Star (W1 ~ 6) the
                                        # fixture has ~2 flagged vs <= 0.04 clean detections /arcmin^2/exposure
                                        # 30-130" out, so at most ~2 % escape
}


def _sample_counts_mags(rng, n15, alpha, lo, hi, area):
    a, b = 10 ** (alpha * (lo - 15)), 10 ** (alpha * (hi - 15))
    n = rng.poisson(n15 * (b - a) * area)
    u = rng.random(n)
    return 15 + np.log10(a + u * (b - a)) / alpha


def _random_in_cap(rng, ra0, dec0, radius_deg, n):
    cos_r = math.cos(math.radians(radius_deg))
    sep = np.degrees(np.arccos(1 - rng.random(n) * (1 - cos_r)))
    return destination(ra0, dec0, sep, rng.uniform(0, 360, n))


def empty_sky(rng, cadence, center, radius_deg=0.25, *, density=1.0, noise=True, return_truth=False,
              chunk=1500, **kw):
    """A synthetic NEOWISE detection table with no movers over a circular patch, observed at `cadence`
    (dict of mjd, scan_id, frame_num; every exposure covers the whole patch).

    Contents: field stars and red galaxies with realistic counts (`density` scales them; 1 = high latitude, use
    ~5-10 for the Galactic plane), all with motion < 60 mas/yr; single-visit Solar-System-like objects moving
    1-200 arcsec/hour; single spurious detections with clean flags; diffraction-spike detections around bright
    stars whose pattern turns with the scan direction (98 % flagged 'D', 2 % not). Returns a pyarrow table in
    SCHEMA, or (table, truth) with `return_truth`."""
    p = dict(SKY_DEFAULTS, **kw)
    rng = np.random.default_rng(rng)
    ra0, dec0 = float(center[0]), float(center[1])
    area = cap_area_deg2(radius_deg)
    exp = cadence
    n_exp = len(exp["mjd"])
    visits = split_visits(exp["mjd"])
    epoch0 = float(np.mean(mjd_to_year(exp["mjd"]))) if n_exp else 2019.0
    # --- stationary sources
    w1 = _sample_counts_mags(rng, p["n15_per_deg2"] * density, p["alpha"], *p["w1_range"], area)
    n = len(w1)
    ra, dec = _random_in_cap(rng, ra0, dec0, radius_deg, n)
    gal = rng.random(n) < p["galaxy_fraction"]
    colour = np.where(gal, np.clip(rng.normal(0.8, 0.3, n), 0.2, 2.0), rng.normal(0.05, 0.08, n))
    pmra = np.where(gal, 0.0, rng.normal(0, p["star_pm_sigma"], n))
    pmdec = np.where(gal, 0.0, rng.normal(0, p["star_pm_sigma"], n))
    tot = np.hypot(pmra, pmdec)
    scale = np.where(tot > p["star_pm_max"], p["star_pm_max"] / np.maximum(tot, 1e-9), 1.0)
    pmra, pmdec = pmra * scale, pmdec * scale
    stars = {"ra": ra, "dec": dec, "epoch": np.full(n, epoch0), "pmra": pmra, "pmdec": pmdec,
             "plx": np.zeros(n), "w1": w1, "w2": w1 - colour}
    parts = []
    for i in range(0, n, chunk):
        sl = slice(i, i + chunk)
        parts.append(_simulate({k: v[sl] for k, v in stars.items()}, exp, rng, noise=noise))
    # --- single-visit Solar-System-like objects
    n_tr = rng.poisson(p["transients_per_deg2"] * area) if n_exp else 0
    tr_truth = []
    for _ in range(n_tr):
        v = int(rng.integers(0, visits.max() + 1))
        sel = np.nonzero(visits == v)[0]
        t_mid = float(np.mean(exp["mjd"][sel]))
        rate = 10 ** rng.uniform(0, math.log10(200.0))  # arcsec/hour
        pa_deg = rng.uniform(0, 360)
        tra, tdec = _random_in_cap(rng, ra0, dec0, radius_deg, 1)
        w2t = rng.uniform(10.0, 15.5)
        w1t = w2t + rng.uniform(0.5, 3.0)
        hours = (exp["mjd"][sel] - t_mid) * 24.0
        e_ = rate * hours * math.sin(math.radians(pa_deg))
        n_ = rate * hours * math.cos(math.radians(pa_deg))
        pra, pdec = offset_radec(tra[0], tdec[0], e_, n_)
        inside = sep_arcsec(ra0, dec0, pra, pdec) <= radius_deg * 3600
        sub = {k: np.asarray(exp[k])[sel][inside] for k in ("mjd", "scan_id", "frame_num")}
        if not inside.any():
            continue
        one = {"ra": pra[inside], "dec": pdec[inside], "epoch": mjd_to_year(sub["mjd"]),
               "pmra": np.zeros(inside.sum()), "pmdec": np.zeros(inside.sum()), "plx": np.zeros(inside.sum()),
               "w1": np.full(inside.sum(), w1t), "w2": np.full(inside.sum(), w2t)}
        # each "source" here is the object at one exposure: simulate it only in that exposure
        mask = np.eye(inside.sum(), dtype=bool)
        parts.append(_simulate(one, sub, rng, noise=noise, exp_mask=mask))
        tr_truth.append({"visit": v, "rate_arcsec_hr": rate, "w2": w2t})
    # --- single spurious detections (clean flags)
    n_art = rng.poisson(p["artefacts_per_deg2_per_exposure"] * area * n_exp) if n_exp else 0
    if n_art:
        ei = rng.integers(0, n_exp, n_art)
        ara, adec = _random_in_cap(rng, ra0, dec0, radius_deg, n_art)
        band2 = rng.random(n_art) < 0.5
        s_hi = rng.uniform(5.0, 8.0, n_art)
        s_lo = rng.normal(0.0, 1.0, n_art)
        cols = _artefact_cols(ara, adec, exp, ei, np.where(band2, s_lo, s_hi), np.where(band2, s_hi, s_lo),
                              rng.uniform(13.5, 16.0, n_art), "0000")
        parts.append(cols)
    # --- diffraction spikes around bright stars, turning with the scan direction
    bright = np.nonzero(w1 < p["spike_w1"])[0] if n_exp else np.zeros(0, int)
    if len(bright):
        theta_v = rng.uniform(0, 90) + 180.0 * (np.arange(visits.max() + 1) % 2) + \
            rng.normal(0, 1.5, visits.max() + 1)
        theta = theta_v[visits] + rng.normal(0, 0.3, n_exp)
        for b in bright:
            n_spk = int(np.clip(2 * (p["spike_w1"] - w1[b]), 1, 6))
            for arm in range(4):
                for k in range(n_spk):
                    dist = 25.0 + 20.0 * k
                    keep_e = rng.random(n_exp) < 0.7
                    if not keep_e.any():
                        continue
                    ei = np.nonzero(keep_e)[0]
                    sra, sdec = destination(ra[b], dec[b], dist / 3600.0, theta[ei] + 45.0 + 90.0 * arm)
                    jitter = rng.normal(0, 0.4, (2, len(ei)))
                    sra, sdec = offset_radec(sra, sdec, jitter[0], jitter[1])
                    flagged = rng.random(len(ei)) >= p["unflagged_spike_fraction"]
                    snr = rng.uniform(5, 10, len(ei))
                    cols = _artefact_cols(sra, sdec, exp, ei, snr, snr * 0.8, w1[b] + 6.0 + 0.1 * k,
                                          np.where(flagged, "DD00", "0000"))
                    parts.append(cols)
    cols = _concat_cols(parts)
    if cols is None:
        table = SCHEMA.empty_table()
    else:
        cols["source_id"] = _source_ids(cols["scan_id"], cols["frame_num"])
        table = _to_table(cols, SCHEMA)
    if return_truth:
        truth = {"n_stars": int(n), "n_galaxies": int(gal.sum()), "stars": stars, "transients": tr_truth,
                 "n_artefacts": int(n_art), "n_bright": int(len(bright)), "area_deg2": area,
                 "center": (ra0, dec0), "radius_deg": radius_deg}
        return table, truth
    return table


def _artefact_cols(ra, dec, exp, ei, snr1, snr2, mag, cc):
    n = len(ra)
    snr1, snr2 = np.round(np.asarray(snr1, float), 1), np.round(np.asarray(snr2, float), 1)
    comb = np.hypot(np.maximum(snr1, 0), np.maximum(snr2, 0))
    sr, sd = reported_sigma(comb)
    mag = np.broadcast_to(np.asarray(mag, float), (n,))
    cols = {"src": np.full(n, -1), "exp": np.asarray(ei), "ra": np.round(ra, 7), "dec": np.round(dec, 7),
            "sigra": np.round(sr, 4), "sigdec": np.round(sd, 4), "sigradec": np.round(NOISE["cov_frac"] * sr, 4),
            "mjd": np.asarray(exp["mjd"], float)[ei], "scan_id": np.asarray(exp["scan_id"], dtype=object)[ei],
            "frame_num": np.asarray(exp["frame_num"], dtype=np.int64)[ei]}
    for band, s in (("w1", snr1), ("w2", snr2)):
        cols[f"{band}mpro"] = np.round(mag + (0.3 if band == "w1" else 0.0), 3)
        cols[f"{band}sigmpro"] = np.where(s >= 2, np.round(1.0857 / np.maximum(s, 1e-3), 3), np.nan)
        cols[f"{band}snr"] = s
    cols["ph_qual"] = np.char.add(ph_qual_letter(snr1), ph_qual_letter(snr2)).astype(object)
    cols["cc_flags"] = np.broadcast_to(np.asarray(cc, dtype=object), (n,)).copy()
    cols["moon_masked"] = np.full(n, "00", dtype=object)
    cols["nb"] = np.ones(n, dtype=np.int64)
    cols["na"] = np.zeros(n, dtype=np.int64)
    cols["qual_frame"] = np.full(n, 10, dtype=np.int64)
    cols["qi_fact"] = np.ones(n)
    cols["saa_sep"] = np.full(n, 100.0)
    return cols


# ----------------------------------------------------------------------------------------------------------------
# Readers: serve one table to process_tile(k5, reader=...) year by year
# ----------------------------------------------------------------------------------------------------------------
def year_label(mjd):
    """NEOWISE 'year' folder of each MJD (365.25-day years from 2013-12-13; later than year11 -> addendum)."""
    i = np.floor((np.asarray(mjd, float) - NEOWISE_START_MJD) / 365.25).astype(int)
    i = np.clip(i, 0, 11)
    return np.array(YEAR_LABELS, dtype=object)[i]


def table_reader(table, k5=None):
    """reader(k5, year) -> table or None for process_tile. Rows are split into the YEAR_LABELS by MJD; when `k5`
    is given, other tiles read as missing (so a core that also reads neighbour tiles sees nothing twice)."""
    labels = year_label(_col(table, "mjd")) if table.num_rows else np.zeros(0, dtype=object)
    index = {y: np.nonzero(labels == y)[0] for y in YEAR_LABELS}

    def reader(tile, year, *args, **kwargs):
        if k5 is not None and int(tile) != int(k5):
            return None
        idx = index.get(year)
        if idx is None or not len(idx):
            return None
        return table.take(pa.array(idx))

    reader.table = table
    return reader


def fixture_reader(path, k5=None):
    return table_reader(pq.read_table(path), k5=k5)


def _movers_of(result):
    if result is None:
        return []
    if isinstance(result, dict):
        return list(result.get("movers") or [])
    return list(result)


def _call_core(process_tile_fn, k5, reader, process_kwargs=None):
    kwargs = dict(process_kwargs or {})
    kwargs.setdefault("years", list(YEAR_LABELS))
    return process_tile_fn(int(k5), reader=reader, **kwargs)


# ----------------------------------------------------------------------------------------------------------------
# Matching and bookkeeping
# ----------------------------------------------------------------------------------------------------------------
def angle_diff_deg(a, b):
    """Smallest absolute difference between two angles, degrees (0..180)."""
    d = (np.asarray(a, float) - np.asarray(b, float)) % 360.0
    return np.minimum(d, 360.0 - d)


def match_movers(truth, movers, radius_arcsec=5.0, pm_tol_frac=0.3, pm_tol_abs=100.0):
    """Pair injected movers (normalized specs) with reported movers.
    A reported mover is a candidate for an injected one when the injected position, carried to the reported
    epoch with the injected motion (parallax ignored), lies within `radius_arcsec` of the reported position AND
    the motion vectors differ by at most max(pm_tol_frac * pm_true, pm_tol_abs) mas/yr. Pairs are assigned
    greedily (best first), one-to-one. Returns (matches: list of mover index or None per truth,
    duplicates: mover indices that also fit an already-matched injection, spurious: the rest)."""
    nt, nm = len(truth), len(movers)
    cands = []
    for i, t in enumerate(truth):
        tol_pm = max(pm_tol_frac * t["pm"], pm_tol_abs)
        for j, m in enumerate(movers):
            try:
                ep = float(m["epoch"])
                mra, mdec, mpmra, mpmdec = float(m["ra"]), float(m["dec"]), float(m["pmra"]), float(m["pmdec"])
            except (KeyError, TypeError, ValueError):
                continue
            pra, pdec = propagate(t["ra"], t["dec"], t["epoch"], t["pmra"], t["pmdec"], ep)
            sep = float(sep_arcsec(pra, pdec, mra, mdec))
            dpm = math.hypot(mpmra - t["pmra"], mpmdec - t["pmdec"])
            if sep <= radius_arcsec and dpm <= tol_pm:
                cands.append((sep / radius_arcsec + dpm / tol_pm, i, j))
    cands.sort()
    match = [None] * nt
    used = set()
    fits = set()
    for _, i, j in cands:
        fits.add(j)
        if match[i] is None and j not in used:
            match[i] = j
            used.add(j)
    duplicates = sorted(fits - used)
    spurious = [j for j in range(nm) if j not in fits]
    return match, duplicates, spurious


def motion_errors(truth, mover):
    """Errors of a reported motion against the truth: fractional |pm| error, position-angle error (deg),
    vector error (mas/yr) and pull (pm_found - pm_true) / pm_err when the mover reports pm_err."""
    pm_t = float(truth["pm"])
    pmra, pmdec = float(mover["pmra"]), float(mover["pmdec"])
    pm_f = float(mover.get("pm", math.hypot(pmra, pmdec)) or math.hypot(pmra, pmdec))
    pa_f = math.degrees(math.atan2(pmra, pmdec)) % 360.0
    err = mover.get("pm_err")
    pull = (pm_f - pm_t) / float(err) if err not in (None, 0) and np.isfinite(float(err)) else None
    return {"pm_found": pm_f, "pmra_found": pmra, "pmdec_found": pmdec,
            "frac_error": abs(pm_f - pm_t) / pm_t if pm_t > 0 else None,
            "pa_error_deg": float(angle_diff_deg(pa_f, truth["pa"])),
            "vec_error": math.hypot(pmra - truth["pmra"], pmdec - truth["pmdec"]), "pull": pull}


def _cell_key(pm_arcsec, w2, colour):
    return (round(float(pm_arcsec), 4), round(float(w2), 3), round(float(colour), 3))


def completeness_table(records, pms=PM_GRID_ARCSEC, w2s=W2_GRID, colours=COLOURS):
    """One row per (W1-W2, pm, W2) cell: injected `trials`, `recovered`, `fraction` (3 decimals, None when no
    trials), and `detectable` (injections whose data had >= 6 visits with >= 2 good detections)."""
    cells = {}
    for r in records:
        k = _cell_key(r["pm_arcsec_yr"], r["w2"], r["w1w2"])
        c = cells.setdefault(k, [0, 0, 0])
        c[0] += 1
        c[1] += bool(r["recovered"])
        c[2] += bool(r.get("detectable", False))
    rows = []
    for colour, pm, w2 in itertools.product(colours, pms, w2s):
        n, rec, det = cells.get(_cell_key(pm, w2, colour), (0, 0, 0))
        rows.append({"pm_arcsec_yr": float(pm), "w2": float(w2), "w1w2": float(colour), "recovered": int(rec),
                     "trials": int(n), "fraction": round(rec / n, 3) if n else None, "detectable": int(det)})
    return rows


def _pct(values, q):
    v = [float(x) for x in values if x is not None and np.isfinite(x)]
    return float(np.percentile(v, q)) if v else None


def _r(x, nd=4):
    return None if x is None or not np.isfinite(x) else round(float(x), nd)


def pm_accuracy(records):
    """Motion accuracy over recovered injections: median and 90th percentile of |pm_found - pm_true| / pm_true,
    of the position-angle error, of the vector error; the median |pull| (0.674 if pm_err is honest and errors are
    Gaussian); and the same medians per injected pm and per W2."""
    rec = [r for r in records if r["recovered"]]

    def block(rs):
        pulls = [abs(r["pull"]) for r in rs if r.get("pull") is not None]
        return {"n": len(rs),
                "median_frac_error": _r(_pct([r["frac_error"] for r in rs], 50), 5),
                "p90_frac_error": _r(_pct([r["frac_error"] for r in rs], 90), 5),
                "median_pa_error_deg": _r(_pct([r["pa_error_deg"] for r in rs], 50), 3),
                "p90_pa_error_deg": _r(_pct([r["pa_error_deg"] for r in rs], 90), 3),
                "median_vec_error_mas_yr": _r(_pct([r["vec_error"] for r in rs], 50), 2),
                "median_abs_pull": _r(_pct(pulls, 50), 3) if pulls else None}

    out = block(rec)
    out["expected_abs_pull"] = 0.674
    out["by_pm"] = [dict(block([r for r in rec if math.isclose(r["pm_arcsec_yr"], pm)]), pm_arcsec_yr=pm)
                    for pm in sorted({r["pm_arcsec_yr"] for r in records})]
    out["by_w2"] = [dict(block([r for r in rec if math.isclose(r["w2"], w2)]), w2=w2)
                    for w2 in sorted({r["w2"] for r in records})]
    return out


def poisson_upper(n, cl=0.95):
    """One-sided upper limit on a Poisson mean after observing n events."""
    from scipy.stats import chi2
    return float(chi2.ppf(cl, 2 * (n + 1)) / 2)


def false_positive_summary(counts, areas_deg2, tile_area=TILE_AREA_DEG2):
    """counts: movers reported on each mover-free sky; areas_deg2: sky areas. `per_tile` scales the rate to one
    3.357 deg^2 survey tile; `upper95_per_tile` is the 95 % Poisson upper limit of that rate."""
    counts = [int(c) for c in counts]
    total, area = int(sum(counts)), float(sum(areas_deg2))
    per_deg2 = total / area if area > 0 else None
    return {"tiles": len(counts), "movers": total, "area_deg2": _r(area, 4),
            "per_sky": _r(total / len(counts), 4) if counts else None,
            "per_deg2": _r(per_deg2, 4),
            "per_tile": _r(per_deg2 * tile_area, 4) if per_deg2 is not None else None,
            "upper95_per_tile": _r(poisson_upper(total) / area * tile_area, 4) if area > 0 else None,
            "counts": counts}


# ----------------------------------------------------------------------------------------------------------------
# Injection-recovery
# ----------------------------------------------------------------------------------------------------------------
def default_cadences():
    """Real NEOWISE cadences: the frames of the two fixtures (Kapteyn's Star: 21 visits, 30-76 exposures each,
    high ecliptic latitude; WISE 0855: 21 visits, 15-37 exposures, near the ecliptic). Falls back to a synthetic
    cadence when the fixtures are missing."""
    out = []
    for name in ("neowise_wise0855_4arcmin.parquet", "neowise_kapteyn_4arcmin.parquet"):
        f = FIXTURES / name
        if f.exists():
            out.append(exposures(pq.read_table(f, columns=["mjd", "scan_id", "frame_num", "ra", "dec"])))
    return out or [synthetic_cadence(0)]


def grid_specs(rng, center, cells, epoch, spacing_arcmin=4.0, vtan_kms=80.0):
    """Mover specs for one sky: one per (pm ″/yr, W2, W1-W2) cell on a square grid `spacing_arcmin` apart (with a
    small random jitter), random direction of motion, parallax from the tangential velocity (None/0 = no
    parallax). Returns (specs, radius_deg needed to hold them)."""
    n = len(cells)
    side = max(1, math.ceil(math.sqrt(n)))
    slots = rng.permutation(side * side)[:n]
    half = (side - 1) / 2.0
    specs = []
    for (pm_as, w2, colour), slot in zip(cells, slots):
        gx, gy = slot % side - half, slot // side - half
        jx, jy = rng.uniform(-0.1, 0.1, 2) * spacing_arcmin
        dx, dy = (gx * spacing_arcmin + jx) * 60.0, (gy * spacing_arcmin + jy) * 60.0
        ra, dec = offset_radec(center[0], center[1], dx, dy)
        pm = pm_as * 1000.0
        specs.append({"ra": float(ra), "dec": float(dec), "epoch": float(epoch), "pm": pm,
                      "pa": float(rng.uniform(0, 360)), "w2": float(w2), "w1": float(w2 + colour),
                      "plx": pm_from_vtan(pm, vtan_kms), "pm_arcsec_yr": float(pm_as)})
    radius = (half * math.sqrt(2) * spacing_arcmin + spacing_arcmin) / 60.0
    return specs, radius


def sky_center(pick):
    """(k5, (ra, dec)) for a sky: an int is a tile (centred on it; skies up to 0.6 deg in radius then stay inside
    the tile, checked for all 12,288 tiles), a (ra, dec) pair is used as is (e.g. across RA 0 or at a pole)."""
    if isinstance(pick, (tuple, list)):
        ra, dec = float(pick[0]) % 360.0, float(pick[1])
        return tile_of(ra, dec), (ra, dec)
    return int(pick), tile_center(int(pick))


def recovery(process_tile_fn, *, pms=PM_GRID_ARCSEC, w2s=W2_GRID, colours=COLOURS, trials=3, n_empty=3, seed=1,
             cadences=None, centers=None, vtan_kms=80.0, spacing_arcmin=4.0, density=1.0, sky_kwargs=None,
             empty_radius_deg=0.3, match_kwargs=None, process_kwargs=None, log=None):
    """Injection-recovery and false-positive test of a mover search `process_tile_fn(k5, reader=..., years=...)`.

    Each trial builds, per W1-W2 colour, one synthetic sky (stars, galaxies, transients, artefacts; the real
    cadence of one of `cadences`, round robin) centred on a random survey tile, injects one mover per (pm, W2)
    cell on a grid (so `trials` injections per cell in total), runs the search blind and matches what it reports
    (match_movers). Reported movers that match no injection are counted as spurious (their rate is a second
    false-positive estimate; extra copies of an injected mover are counted as duplicates). Then `n_empty`
    mover-free skies of radius `empty_radius_deg` measure false positives. Deterministic for a given seed.
    `centers`: optional list of tiles (int) or (ra, dec) positions for the injection skies, used round robin.

    Returns {"completeness": rows, "pm_accuracy": {...}, "false_positives": {...}, "spurious_in_injected": {...},
    "records": per-injection dicts, "config": {...}, "timing": {...}}."""
    say = log or (lambda *a: None)
    cadences = cadences or default_cadences()
    sky_kwargs = dict(sky_kwargs or {})
    match_kwargs = dict(match_kwargs or {})
    records, spurious, dups, inj_areas, core_s = [], [], [], [], []
    for t in range(trials):
        for ci, colour in enumerate(colours):  # one sky per colour keeps each sky small
            rng = np.random.default_rng([seed, t, ci])
            cad = cadences[t % len(cadences)]
            pick = centers[(t * len(colours) + ci) % len(centers)] if centers else int(rng.integers(0, N_TILES))
            k5, center = sky_center(pick)
            epoch = float(np.mean(mjd_to_year(cad["mjd"])))
            specs, radius = grid_specs(rng, center, [(pm, w2, colour) for pm in pms for w2 in w2s], epoch,
                                       spacing_arcmin=spacing_arcmin, vtan_kms=vtan_kms)
            sky = empty_sky(rng, cad, center, radius, density=density, **sky_kwargs)
            report = []
            table = inject(sky, specs, rng, cadence=cad, report=report)
            del sky
            t0 = time.time()
            result = _call_core(process_tile_fn, k5, table_reader(table, k5=k5), process_kwargs)
            core_s.append(time.time() - t0)
            movers = _movers_of(result)
            truth = [r["spec"] for r in report]
            match, dup, spur = match_movers(truth, movers, **match_kwargs)
            for tr, rep, j in zip(truth, report, match):
                rec = {"trial": t, "k5": k5, "pm_arcsec_yr": tr["pm_arcsec_yr"], "w2": tr["w2"],
                       "w1w2": round(tr["w1w2"], 3), "pm_true": tr["pm"], "pa_true": tr["pa"], "plx": tr["plx"],
                       "n_rows": rep["n_rows"], "n_visits_good": rep["n_visits_good"],
                       "detectable": rep["n_visits_good"] >= 6, "recovered": j is not None}
                if j is not None:
                    rec.update(motion_errors(tr, movers[j]))
                records.append(rec)
            spurious.append(len(spur))
            dups.append(len(dup))
            inj_areas.append(cap_area_deg2(radius))
            say(f"trial {t + 1}/{trials} W1-W2={colour:g}: tile {k5}, {table.num_rows} rows, "
                f"{sum(m is not None for m in match)}/{len(truth)} recovered, {len(spur)} spurious, "
                f"{len(dup)} duplicate, {core_s[-1]:.1f} s")
    fp_counts, fp_areas = [], []
    for e in range(n_empty):
        rng = np.random.default_rng([seed, 100000 + e])
        cad = cadences[e % len(cadences)]
        k5 = int(rng.integers(0, N_TILES))
        center = tile_center(k5)
        sky = empty_sky(rng, cad, center, empty_radius_deg, density=density, **sky_kwargs)
        t0 = time.time()
        result = _call_core(process_tile_fn, k5, table_reader(sky, k5=k5), process_kwargs)
        core_s.append(time.time() - t0)
        fp_counts.append(len(_movers_of(result)))
        fp_areas.append(cap_area_deg2(empty_radius_deg))
        say(f"empty sky {e + 1}/{n_empty}: tile {k5}, {sky.num_rows} rows, {fp_counts[-1]} movers, "
            f"{core_s[-1]:.1f} s")
    return {
        "completeness": completeness_table(records, pms, w2s, colours),
        "pm_accuracy": pm_accuracy(records),
        "false_positives": false_positive_summary(fp_counts, fp_areas),
        "spurious_in_injected": dict(false_positive_summary(spurious, inj_areas), duplicates=int(sum(dups))),
        "records": records,
        "config": {"pms_arcsec_yr": list(pms), "w2": list(w2s), "w1w2": list(colours), "trials": trials,
                   "n_empty": n_empty, "seed": seed, "vtan_kms": vtan_kms, "spacing_arcmin": spacing_arcmin,
                   "density": density, "empty_radius_deg": empty_radius_deg,
                   "match": dict({"radius_arcsec": 5.0, "pm_tol_frac": 0.3, "pm_tol_abs": 100.0}, **match_kwargs)},
        "timing": {"core_seconds": round(float(sum(core_s)), 2), "core_calls": len(core_s)},
    }


# ----------------------------------------------------------------------------------------------------------------
# Known movers
# ----------------------------------------------------------------------------------------------------------------
def known_movers(results, known=KNOWN_STARS, radius_arcsec=10.0, pm_tol_frac=0.2):
    """Did the search find these known fast movers? `results`: TileResult dicts (with "movers"), or movers.
    A known star matches the nearest reported mover within `radius_arcsec` once the star is carried to the
    mover's epoch with its catalogue motion; it counts as recovered when the motion vectors also agree to
    `pm_tol_frac` of the catalogue pm. Returns {"known": [per star], "n_known", "n_recovered", "fraction"}."""
    movers = []
    for r in (results if isinstance(results, (list, tuple)) else [results]):
        if isinstance(r, dict) and "movers" in r:
            movers.extend(r.get("movers") or [])
        elif isinstance(r, dict):
            movers.append(r)
    rows = []
    for star in known:
        pm_true = math.hypot(star["pmra"], star["pmdec"])
        best, best_sep = None, None
        for m in movers:
            try:
                pra, pdec = propagate(star["ra"], star["dec"], star["epoch"], star["pmra"], star["pmdec"],
                                      float(m["epoch"]))
                sep = float(sep_arcsec(pra, pdec, float(m["ra"]), float(m["dec"])))
            except (KeyError, TypeError, ValueError):
                continue
            if sep <= radius_arcsec and (best_sep is None or sep < best_sep):
                best, best_sep = m, sep
        row = {"name": star["name"], "pm_true": round(pm_true, 1), "pm_found": None, "recovered": False,
               "error_pct": None, "pa_error_deg": None, "sep_arcsec": None, "mover_id": None, "ref": star.get("ref")}
        if best is not None:
            pmra, pmdec = float(best["pmra"]), float(best["pmdec"])
            pm_f = float(best.get("pm") or math.hypot(pmra, pmdec))
            dvec = math.hypot(pmra - star["pmra"], pmdec - star["pmdec"])
            pa_t = math.degrees(math.atan2(star["pmra"], star["pmdec"])) % 360
            pa_f = math.degrees(math.atan2(pmra, pmdec)) % 360
            row.update({"pm_found": round(pm_f, 1), "recovered": bool(dvec <= pm_tol_frac * pm_true),
                        "error_pct": round(100.0 * abs(pm_f - pm_true) / pm_true, 3),
                        "pa_error_deg": round(float(angle_diff_deg(pa_f, pa_t)), 3),
                        "sep_arcsec": round(best_sep, 3), "mover_id": best.get("id"),
                        "n_visits": best.get("n_visits")})
        rows.append(row)
    n_rec = sum(r["recovered"] for r in rows)
    return {"known": rows, "n_known": len(rows), "n_recovered": n_rec,
            "fraction": round(n_rec / len(rows), 3) if rows else None}


def run_real(process_tile_fn, tiles_dir=DEFAULT_TILES_DIR, fixtures_dir=FIXTURES, process_kwargs=None, log=None):
    """Known-mover checks on real data: the search run on the two NEOWISE fixtures (Kapteyn's Star, WISE 0855),
    plus any finished validation tiles in `tiles_dir`. Returns (known rows, real_fields, not_run names)."""
    say = log or (lambda *a: None)
    known_rows, fields, done = [], [], set()
    for star in KNOWN_STARS:
        if not star.get("fixture"):
            continue
        path = Path(fixtures_dir) / star["fixture"]
        if not path.exists():
            continue
        k5 = tile_of(star["ra"], star["dec"])
        t0 = time.time()
        result = _call_core(process_tile_fn, k5, fixture_reader(path, k5=k5), process_kwargs)
        movers = _movers_of(result)
        km = known_movers(movers, [star])
        row = dict(km["known"][0], data=f"real NEOWISE detections within 4′ of the star, {path.name}", k5=k5)
        known_rows.append(row)
        # target_tracks: reported movers that are this star (more than 1 = its track was split);
        # other_movers: everything else in this 4' field (a real, unlisted mover or a false one)
        n_target = sum(known_movers([m], [star])["n_recovered"] for m in movers)
        fields.append({"name": star["name"], "k5": k5, "movers": len(movers), "target_tracks": int(n_target),
                       "other_movers": len(movers) - int(n_target), "seconds": round(time.time() - t0, 2)})
        done.add(star["name"])
        say(f"real field {star['name']}: {len(movers)} movers, recovered={row['recovered']}, "
            f"pm {row['pm_found']} vs {row['pm_true']}")
    tiles_dir = Path(tiles_dir)
    for star in KNOWN_STARS:
        k5 = tile_of(star["ra"], star["dec"])
        f = tiles_dir / f"{k5}.json"
        if not f.exists():
            continue
        try:
            result = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        row = dict(known_movers([result], [star])["known"][0], data=f"survey tile {k5}", k5=k5)
        known_rows.append(row)
        done.add(star["name"])
    not_run = [s["name"] for s in KNOWN_STARS if s["name"] not in done]
    return known_rows, fields, not_run


# ----------------------------------------------------------------------------------------------------------------
# validation.json
# ----------------------------------------------------------------------------------------------------------------
def _pooled(rows, pm_min=None, pm_max=None, w2_min=None, w2_max=None, colour=0.0):
    sel = [r for r in rows if (pm_min is None or r["pm_arcsec_yr"] >= pm_min - 1e-9)
           and (pm_max is None or r["pm_arcsec_yr"] <= pm_max + 1e-9)
           and (w2_min is None or r["w2"] >= w2_min - 1e-9) and (w2_max is None or r["w2"] <= w2_max + 1e-9)
           and math.isclose(r.get("w1w2", 0.0), colour)]
    n = sum(r["trials"] for r in sel)
    return (sum(r["recovered"] for r in sel) / n, n) if n else (None, 0)


def _fmt_pct(x):
    return "n/a" if x is None else f"{100 * x:.0f}%"


def make_summary(rec, known=None):
    """One plain-English sentence (two with known movers) from the numbers."""
    rows = rec["completeness"]
    colours = sorted({r.get("w1w2", 0.0) for r in rows}) or [0.0]
    c0 = 0.0 if 0.0 in colours else colours[0]
    bright, nb = _pooled(rows, pm_min=1.0, w2_max=13.0, colour=c0)
    w145, _ = _pooled(rows, pm_min=1.0, w2_min=14.5, w2_max=14.5, colour=c0)
    w155, _ = _pooled(rows, pm_min=1.0, w2_min=15.5, w2_max=15.5, colour=c0)
    slow, _ = _pooled(rows, pm_max=0.2, w2_max=13.0, colour=c0)
    n_inj = sum(r["trials"] for r in rows)
    acc = rec["pm_accuracy"].get("median_frac_error")
    fp = rec["false_positives"]
    which = f" with W1−W2 = {c0:g}" if len(colours) > 1 else ""
    parts = [f"Of {n_inj} synthetic movers hidden in NEOWISE-like skies with the real NEOWISE cadence, the search "
             f"found {_fmt_pct(bright)} of those{which} moving at least 1″/yr with W2 ≤ 13"]
    extra = []
    if w145 is not None:
        extra.append(f"{_fmt_pct(w145)} at W2 = 14.5")
    if w155 is not None:
        extra.append(f"{_fmt_pct(w155)} at W2 = 15.5")
    if slow is not None:
        extra.append(f"{_fmt_pct(slow)} of bright ones moving only 0.2″/yr")
    if extra:
        parts.append(" (" + ", ".join(extra) + ")")
    if acc is not None:
        parts.append(f", measured their motion to {100 * acc:.1f}% (median)")
    if fp.get("per_tile") is not None:
        parts.append(f", and reported {fp['per_tile']:.2f} false movers per survey tile on mover-free skies")
    text = "".join(parts) + "."
    for c in colours:
        if c == c0:
            continue
        mid, _ = _pooled(rows, pm_min=1.0, w2_max=14.5, colour=c)
        faint, _ = _pooled(rows, pm_min=1.0, w2_min=15.5, w2_max=15.5, colour=c)
        if mid is not None:
            text += (f" For redder objects (W1−W2 = {c:g}, like cold brown dwarfs) it found {_fmt_pct(mid)} at "
                     f"W2 ≤ 14.5" + (f" and {_fmt_pct(faint)} at W2 = 15.5." if faint is not None else "."))
    if known:
        names = list(dict.fromkeys(r["name"] for r in known))
        found = [nm for nm in names if any(r["recovered"] for r in known if r["name"] == nm)]
        text += f" On real NEOWISE data it recovered {len(found)} of {len(names)} known fast-moving stars" + \
            (f" ({', '.join(found)})." if found else ".")
    return text


METHOD = ("Injection-recovery: we build synthetic NEOWISE single-exposure detection tables that copy the real "
          "NEOWISE observing pattern (exposure times, scan ids and frames of real data, about 21 visits from 2014 "
          "to 2024), fill them with field stars, galaxies, passing asteroids and spurious detections, hide movers "
          "of known speed, direction and brightness in them, and run the survey's mover search without telling it "
          "where they are. Noise, detection limits and positional errors follow a model measured on real NEOWISE "
          "detections. A hidden mover counts as recovered when the search reports a mover within 5″ of it with a "
          "motion within 30% (or 0.1″/yr). False positives are counted on skies with no movers at all, and the "
          "search is also run on real NEOWISE data around stars whose motion Gaia DR3 measured.")

LIMITS = [
    "Synthetic skies use high-Galactic-latitude source counts; crowded fields near the Galactic plane are not "
    "simulated at their full density.",
    "Every exposure covers the whole synthetic patch; real frame edges and gaps are only present when injecting "
    "into real tables.",
    "The noise model is calibrated on two real 4′ NEOWISE fields; it has no blending, no position-dependent "
    "systematics and a simple saturation model.",
    "Injected movers have parallaxes from a tangential velocity of 80 km/s and do not accelerate (no binaries).",
    "False-positive rates are measured on synthetic skies; real artefacts (latents, ghosts, scattered light) "
    "are more varied.",
    "Known-star checks use small 4′ cut-outs of real data and, when available, the survey's own tile results.",
]


# Bins of the web page's `injection` block (pm in mas/yr, W2 in mag); each holds one value of the default grid.
PM_BINS_MAS = (150.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0, 12000.0)
W2_BINS = (6.0, 10.0, 12.0, 14.0, 15.0, 16.5)


def _bins(records, key, edges, scale=1.0):
    """Completeness in [lo, hi) bins of records[key] * scale (the last bin includes hi); empty bins are left out."""
    out = []
    for i, (lo, hi) in enumerate(zip(edges[:-1], edges[1:])):
        last = i == len(edges) - 2
        sel = [r for r in records if lo <= r[key] * scale < hi or (last and r[key] * scale == hi)]
        if sel:
            k = sum(bool(r["recovered"]) for r in sel)
            out.append({"lo": lo, "hi": hi, "n": len(sel), "recovered": k, "completeness": round(k / len(sel), 3)})
    return out


def page_injection(records, colours=None):
    """The web page's view of injection-recovery: totals, completeness in pm bins (mas/yr) and W2 bins (all
    colours pooled), median |pm_found - pm_true| (mas/yr) and median relative pm error of recovered movers."""
    rec = [r for r in records if r["recovered"]]
    abs_err = [abs(r["pm_found"] - r["pm_true"]) for r in rec if r.get("pm_found") is not None]
    rel_err = [r["frac_error"] for r in rec if r.get("frac_error") is not None]
    return {"n_injected": len(records), "n_recovered": len(rec),
            "by_pm": _bins(records, "pm_arcsec_yr", PM_BINS_MAS, scale=1000.0),
            "by_mag": _bins(records, "w2", W2_BINS),
            "pm_error_median": _r(_pct(abs_err, 50), 2),
            "pm_rel_error_median": _r(_pct(rel_err, 50), 5),
            "pm_unit": "mas/yr", "mag": "W2 (Vega)",
            "w1w2": sorted({r["w1w2"] for r in records}) if colours is None else list(colours)}


def page_false_positives(fp):
    """Contract fields (tiles, movers, per_tile, ...) plus the page's `n` and a plain-English `note`."""
    out = {k: v for k, v in fp.items() if k != "counts"}
    out["n"] = fp["movers"]
    if fp["tiles"] and fp.get("area_deg2"):
        tiles_eq = fp["area_deg2"] / TILE_AREA_DEG2
        out["note"] = (f"{fp['movers']} mover(s) reported on {fp['tiles']} synthetic skies with no movers "
                       f"({fp['area_deg2']:.1f} deg², {tiles_eq:.1f} survey tiles of sky): {fp['per_tile']:.2f} "
                       f"false movers per tile (95% upper limit {fp['upper95_per_tile']:.2f}).")
    else:
        out["note"] = "No mover-free skies were run."
    return out


def known_note(row):
    """One plain sentence about a known-star check."""
    where = f" ({row['data']})" if row.get("data") else ""
    if row.get("pm_found") is None:
        return f"No mover reported within 10″ of the star's predicted position{where}."
    v = f", {row['n_visits']} visits" if row.get("n_visits") else ""
    if row.get("recovered"):
        return (f"Found {row['sep_arcsec']:.1f}″ from the predicted position; motion off by "
                f"{row['error_pct']:.2f}% and {row['pa_error_deg']:.1f}° in direction{v}{where}.")
    return (f"A mover was found {row['sep_arcsec']:.1f}″ away but its motion is off by {row['error_pct']:.1f}% "
            f"(not counted as recovered){where}.")


def build_document(rec, known_rows=None, real_fields=None, not_run=None, core_name=None, runtime_s=None):
    """validation.json as a plain dict (no NaN/inf, only JSON types). It carries the contract fields
    (completeness, pm_accuracy, false_positives {tiles, movers, per_tile}, known [{name, pm_true, pm_found,
    recovered, error_pct}], summary, method, limits) and, for the web page, `injection` plus the extra keys
    false_positives {n, note} and known [{pm_measured, note}] (pm in mas/yr)."""
    known_rows = list(known_rows or [])
    acc = {k: v for k, v in rec["pm_accuracy"].items()}
    doc = {
        "generated": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
        "completeness": [{k: r[k] for k in ("pm_arcsec_yr", "w2", "w1w2", "recovered", "trials", "fraction",
                                              "detectable")} for r in rec["completeness"]],
        "pm_accuracy": acc,
        "injection": page_injection(rec.get("records") or [], (rec.get("config") or {}).get("w1w2")),
        "false_positives": page_false_positives(rec["false_positives"]),
        "known": [dict({k: r.get(k) for k in ("name", "pm_true", "pm_found", "recovered", "error_pct",
                                              "pa_error_deg", "sep_arcsec", "data", "ref")},
                       pm_measured=r.get("pm_found"), note=known_note(r)) for r in known_rows],
        "summary": make_summary(rec, known_rows),
        "method": METHOD,
        "limits": list(LIMITS),
        "spurious_in_injected": {k: v for k, v in (rec.get("spurious_in_injected") or {}).items() if k != "counts"},
        "real_fields": list(real_fields or []),
        "known_not_run": list(not_run or []),
        "grid": rec.get("config"),
        "noise_model": {"w2_snr5_mag": NOISE["w2"]["m5"], "w1_snr5_mag": NOISE["w1"]["m5"],
                        "sigma_arcsec_at_w2_for_w1w2_0": {str(m): round(float(true_sigma(m, m)[0]), 3)
                                               for m in (8.0, 10.0, 12.0, 13.0, 14.0, 14.5, 15.0, 15.5)},
                        "calibration": "tests/fixtures (real NEOWISE, Kapteyn's Star and WISE 0855 fields)"},
        "units": {"pm": "mas/yr", "pm_arcsec_yr": "arcsec/yr", "w2": "Vega mag", "sep": "arcsec"},
        "core": core_name,
        "runtime_seconds": None if runtime_s is None else round(float(runtime_s), 1),
    }
    return sanitize(doc)


def sanitize(x):
    """Plain JSON types; NaN/inf -> None."""
    if isinstance(x, dict):
        return {str(k): sanitize(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [sanitize(v) for v in x]
    if isinstance(x, (np.bool_, bool)):
        return bool(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        return float(x) if np.isfinite(x) else None
    if isinstance(x, np.ndarray):
        return sanitize(x.tolist())
    return x


def write_validation(path, doc):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return path


# ----------------------------------------------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------------------------------------------
def load_core(spec="survey.link:process_tile"):
    """'module:function' or 'path/to/file.py:function' -> callable. Raises ImportError with a clear message."""
    mod_name, _, fn = spec.rpartition(":")
    if not mod_name:
        mod_name, fn = spec, "process_tile"
    if mod_name.endswith(".py"):
        p = Path(mod_name)
        s = importlib.util.spec_from_file_location(p.stem, p)
        if s is None or s.loader is None:
            raise ImportError(f"cannot load {p}")
        mod = importlib.util.module_from_spec(s)
        s.loader.exec_module(mod)
    else:
        mod = importlib.import_module(mod_name)
    if not hasattr(mod, fn):
        raise ImportError(f"{mod_name} has no {fn}")
    return getattr(mod, fn)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="WANDERERS sky survey validation (injection-recovery, false "
                                             "positives, known movers)")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="validation.json path")
    ap.add_argument("--trials", type=int, default=5, help="injections per (pm, W2, colour) cell")
    ap.add_argument("--empty", type=int, default=None, help="mover-free skies (radius 0.3 deg) for false "
                                                            "positives (default 24, about 2 survey tiles of area)")
    ap.add_argument("--real", action="store_true", help="also run the known-star checks on real NEOWISE data")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--colours", default="0,2", help="comma-separated W1-W2 colours to inject: 0 = star-like, "
                                                       "2 = cold brown dwarf (W1 adds little)")
    ap.add_argument("--density", type=float, default=1.0, help="source density relative to high latitude")
    ap.add_argument("--core", default="survey.link:process_tile", help="module:function of the mover search")
    ap.add_argument("--tiles-dir", default=str(DEFAULT_TILES_DIR), help="finished survey tiles (for --real)")
    ap.add_argument("--quick", action="store_true", help="tiny smoke run: 3 speeds x 2 magnitudes, sparse skies")
    a = ap.parse_args(argv)
    if a.trials < 1:
        ap.error("--trials must be >= 1")
    if a.empty is None:
        a.empty = 1 if a.quick else 24
    if a.empty < 0:
        ap.error("--empty must be >= 0")
    try:
        a.colours = tuple(float(c) for c in str(a.colours).split(",") if c.strip())
    except ValueError:
        ap.error("--colours must be numbers like 0,2")
    return a


def main(argv=None):
    a = parse_args(argv)
    say = lambda *m: print(*m, file=sys.stderr, flush=True)  # noqa: E731
    try:
        core = load_core(a.core)
    except ImportError as e:
        say(f"validate: the mover search {a.core!r} is not available ({e}). "
            "It lives in pipeline/survey/link.py (survey.link.process_tile).")
        return 2
    t0 = time.time()
    kw = dict(pms=PM_GRID_ARCSEC, w2s=W2_GRID, colours=a.colours, trials=a.trials, n_empty=a.empty, seed=a.seed,
              density=a.density, log=say)
    if a.quick:
        kw.update(pms=(1.0, 4.0, 11.0), w2s=(11.0, 14.5), density=min(a.density, 0.05), empty_radius_deg=0.1)
    rec = recovery(core, **kw)
    known_rows, fields, not_run = ([], [], [])
    if a.real:
        known_rows, fields, not_run = run_real(core, tiles_dir=a.tiles_dir, log=say)
    doc = build_document(rec, known_rows, fields, not_run if a.real else [], core_name=a.core,
                         runtime_s=time.time() - t0)
    out = write_validation(a.out, doc)
    say(doc["summary"])
    say(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
