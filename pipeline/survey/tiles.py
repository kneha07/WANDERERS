"""Data access for the WANDERERS sky survey: the NEOWISE-R single-exposure (L1b) source table on AWS.

The table is partitioned by HEALPix order 5 (nested, nside 32, 12,288 tiles of ~3.36 deg^2) and by data year,
on NASA IRSA's public bucket (anonymous access, region us-west-2):

    nasa-irsa-wise/wise/neowiser/catalogs/p1bs_psd/healpix_k5/{year}/neowiser-healpix_k5-{year}.parquet/
        healpix_k0={k5 >> 10}/healpix_k5={k5}/part0.snappy.parquet

A tile-year is ~0.8-2 M rows (~150-800 MB of parquet). 57 tiles around the ecliptic poles, which NEOWISE saw on
every orbit, are split into several `partN` files of 6 M rows each (up to 14 per year, ~18 GB);
`read_tile_year` reads one part (part0 by default) so memory stays bounded, and `tile_year_parts` says how many
there are. Nothing is ever written to disk.

Units follow docs/survey-contract.md: degrees for positions, arcsec for sigra/sigdec, Vega magnitudes.
"""
from __future__ import annotations

import math
import os
import threading
import time

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.fs as pfs
import pyarrow.parquet as pq

YEARS = [f"year{i}" for i in range(1, 12)] + ["addendum"]
COLUMNS = ["source_id", "ra", "dec", "sigra", "sigdec", "sigradec", "mjd", "w1mpro", "w1sigmpro", "w1snr", "w2mpro",
           "w2sigmpro", "w2snr", "cc_flags", "ph_qual", "nb", "na", "qual_frame", "qi_fact", "saa_sep", "moon_masked",
           "scan_id", "frame_num"]
# The subset process_tile needs (quality cuts + astrometry + photometry): ~30% less to download than COLUMNS.
CORE_COLUMNS = ["ra", "dec", "sigra", "sigdec", "mjd", "w1mpro", "w1sigmpro", "w1snr", "w2mpro", "w2sigmpro", "w2snr",
                "cc_flags", "nb", "qual_frame", "saa_sep", "moon_masked"]
NSIDE = 32
N_TILES = 12 * NSIDE * NSIDE                                    # 12,288
TILE_AREA_DEG2 = 4 * math.pi * (180 / math.pi) ** 2 / N_TILES   # 3.357 deg^2
BUCKET = "nasa-irsa-wise"
REGION = "us-west-2"
PATH = ("nasa-irsa-wise/wise/neowiser/catalogs/p1bs_psd/healpix_k5/{year}/neowiser-healpix_k5-{year}.parquet/"
        "healpix_k0={k0}/healpix_k5={k5}/part{part}.snappy.parquet")

# Approximate MJD start of each NEOWISE-R data year (years run from 13 December; the addendum holds what came
# after year11). Only used to split a local multi-year table (a fixture) into fake per-year reads.
YEAR_START_MJD = {f"year{i}": 56639.0 + 365.25 * (i - 1) for i in range(1, 12)}
YEAR_START_MJD["addendum"] = 56639.0 + 365.25 * 11

_HP = None
_FS = {}
_LOCK = threading.Lock()


def _healpix():
    global _HP
    if _HP is None:
        from astropy_healpix import HEALPix
        _HP = HEALPix(nside=NSIDE, order="nested")
    return _HP


def s3() -> pfs.S3FileSystem:
    """Anonymous S3 filesystem for the IRSA bucket, one per process (safe to use after a multiprocessing fork)."""
    pid = os.getpid()
    with _LOCK:
        if pid not in _FS:
            _FS[pid] = pfs.S3FileSystem(anonymous=True, region=REGION, connect_timeout=20, request_timeout=60)
        return _FS[pid]


# ---------------------------------------------------------------------------------------------------- HEALPix
def tile_of(ra, dec):
    """HEALPix order-5 nested tile of (ra, dec) in degrees: an int for scalars, an int64 array for arrays."""
    import astropy.units as u
    ra_a, dec_a = np.asarray(ra, float), np.asarray(dec, float)
    k = _healpix().lonlat_to_healpix(np.mod(ra_a, 360.0) * u.deg, dec_a * u.deg)
    k = np.asarray(k, dtype=np.int64)
    return int(k) if k.ndim == 0 else k


def tile_center(k5: int) -> tuple[float, float]:
    """(ra, dec) of the tile centre in degrees."""
    lon, lat = _healpix().healpix_to_lonlat(int(k5))
    return float(lon.deg) % 360.0, float(lat.deg)


def tile_corners(k5: int) -> list[list[float]]:
    """The four corners [[ra, dec] x4] of the tile in degrees (HEALPix order: N, W, S, E)."""
    lon, lat = _healpix().boundaries_lonlat(int(k5), step=1)
    return [[float(a) % 360.0, float(b)] for a, b in zip(np.ravel(lon.deg), np.ravel(lat.deg))]


def tile_neighbours(k5: int) -> list[int]:
    """The (up to 8) tiles touching this one."""
    nb = np.asarray(_healpix().neighbours(int(k5))).ravel()
    return sorted({int(x) for x in nb if x >= 0 and x != k5})


# ---------------------------------------------------------------------------------------------------- tables
def nullable(table: pa.Table) -> pa.Table:
    """Cast to the same schema with every field nullable (NEOWISE years differ in nullability)."""
    schema = pa.schema([f.with_nullable(True) for f in table.schema], metadata=None)
    if schema.equals(table.schema, check_metadata=False):
        return table.replace_schema_metadata(None)
    return table.cast(schema)


def concat_tables(tables) -> pa.Table | None:
    """Concatenate tables from different years: drops None, unifies nullability and (if needed) numeric types."""
    tables = [nullable(t) for t in tables if t is not None]
    if not tables:
        return None
    try:
        return pa.concat_tables(tables)
    except (pa.ArrowInvalid, pa.ArrowTypeError):
        return pa.concat_tables(tables, promote_options="permissive")


def tile_path(k5: int, year: str, part: int = 0) -> str:
    return PATH.format(year=year, k0=int(k5) >> 10, k5=int(k5), part=int(part))


def read_tile_year(k5: int, year: str, fs=None, columns=COLUMNS, part: int = 0, retries: int = 3) -> pa.Table | None:
    """One tile-year of detections as a pyarrow Table with an all-nullable schema, or None when the file is missing
    (e.g. no `addendum` for this tile). Transient network errors are retried; other errors are raised."""
    fs = fs or s3()
    path = tile_path(k5, year, part)
    for attempt in range(retries):
        try:
            return nullable(pq.read_table(path, filesystem=fs, columns=list(columns)))
        except FileNotFoundError:
            return None
        except OSError as e:
            msg = str(e).lower()
            if "not found" in msg or "does not exist" in msg or "nosuchkey" in msg:
                return None
            if attempt == retries - 1:
                raise
            time.sleep(1.5 * (attempt + 1))
    return None


def iter_tile_year(k5: int, year: str, fs=None, columns=COLUMNS, part: int = 0, retries: int = 3):
    """Like read_tile_year but yields the file one row group at a time (all-nullable tables), so a caller can
    reduce each piece before the next is read (ecliptic-pole files have 6 M rows in 3 row groups). Yields
    nothing when the file is missing."""
    fs = fs or s3()
    path = tile_path(k5, year, part)
    pf = None
    for attempt in range(retries):
        try:
            pf = pq.ParquetFile(path, filesystem=fs)
            break
        except FileNotFoundError:
            return
        except OSError as e:
            msg = str(e).lower()
            if "not found" in msg or "does not exist" in msg or "nosuchkey" in msg:
                return
            if attempt == retries - 1:
                raise
            time.sleep(1.5 * (attempt + 1))
    for rg in range(pf.metadata.num_row_groups):
        for attempt in range(retries):
            try:
                yield nullable(pf.read_row_group(rg, columns=list(columns)))
                break
            except OSError:
                if attempt == retries - 1:
                    raise
                time.sleep(1.5 * (attempt + 1))


def tile_year_parts(k5: int, year: str, fs=None) -> int:
    """How many partN files a tile-year has (0 when missing; >1 only for the 57 ecliptic-pole tiles)."""
    fs = fs or s3()
    d = tile_path(k5, year).rsplit("/", 1)[0]
    infos = fs.get_file_info(pfs.FileSelector(d, allow_not_found=True))
    return sum(1 for i in infos if i.type == pfs.FileType.File and i.base_name.endswith(".parquet"))


def read_fixture(path, columns=COLUMNS) -> pa.Table:
    """A local parquet file with the same columns (the test fixtures are 4' cones with all years together)."""
    t = pq.read_table(str(path))
    cols = [c for c in columns if c in t.column_names]
    return nullable(t.select(cols))


def year_of_mjd(mjd) -> np.ndarray:
    """Name of the NEOWISE-R data year for each MJD (approximate boundaries, see YEAR_START_MJD)."""
    starts = np.array([YEAR_START_MJD[y] for y in YEARS])
    idx = np.clip(np.searchsorted(starts, np.asarray(mjd, float), side="right") - 1, 0, len(YEARS) - 1)
    return np.asarray(YEARS)[idx]


def fixture_reader(tables, missing=()):
    """reader(k5, year) for tests: serves the rows of local tables (paths or Tables, all years mixed) that fall in
    each data year, ignoring k5. Years in `missing` (or with no rows) return None, like a missing S3 file."""
    if isinstance(tables, (str, os.PathLike, pa.Table)):
        tables = [tables]
    t = concat_tables([read_fixture(x) if not isinstance(x, pa.Table) else x for x in tables])
    years = year_of_mjd(t["mjd"].to_numpy(zero_copy_only=False))

    def reader(k5, year, **_):
        if year in missing:
            return None
        sel = np.flatnonzero(years == year)
        return t.take(pa.array(sel)) if len(sel) else None
    return reader


# ---------------------------------------------------------------------------------------------------- quality
SNR_MIN = 5.0
NB_MAX = 2


def _col(table, name):
    return table[name] if name in table.column_names else None


def good_mask(table: pa.Table) -> np.ndarray:
    """Detections good enough for astrometry (True = keep). A null in any tested column means "not good".

    Cuts (each from the NEOWISE explanatory supplement):
      1. `cc_flags[0:2] == '00'`: no W1/W2 contamination flag (D/d diffraction spike, P/p persistence (latent),
         H/h scattered-light halo, O/o optical ghost). Ghosts, latents and spikes are the main source of spurious
         single-visit detections around bright stars.
      2. `qual_frame > 0`: the frame is usable (0 = bad frame quality).
      3. `saa_sep > 0`: taken outside the South Atlantic Anomaly (negative = inside, many cosmic-ray hits).
      4. `moon_masked[0:2] == '00'`: W1/W2 not inside the scattered-moonlight mask.
      5. `nb <= 2`: at most two PSF components in the blend fit (deep blends have biased positions).
      6. `w1snr >= 5 or w2snr >= 5`: a real detection in at least one band (positions of 2-5 sigma blips are poor).
      7. `ra, dec, mjd, sigra, sigdec` finite and `sigra, sigdec > 0`: a usable position and error.
    """
    n = table.num_rows
    if n == 0:
        return np.zeros(0, bool)

    def str2(name, want):
        c = _col(table, name)
        if c is None:
            return pa.scalar(True)
        return pc.equal(pc.utf8_slice_codeunits(c, 0, 2), want)

    def gt(name, v):
        c = _col(table, name)
        return pa.scalar(True) if c is None else pc.greater(c, v)

    m = pc.and_(str2("cc_flags", "00"), gt("qual_frame", 0))
    m = pc.and_(m, gt("saa_sep", 0))
    m = pc.and_(m, str2("moon_masked", "00"))
    if _col(table, "nb") is not None:
        m = pc.and_(m, pc.less_equal(table["nb"], NB_MAX))
    snr = None
    for b in ("w1snr", "w2snr"):
        c = _col(table, b)
        if c is not None:
            s = pc.fill_null(pc.greater_equal(c, SNR_MIN), False)
            snr = s if snr is None else pc.or_(snr, s)
    if snr is not None:
        m = pc.and_(m, snr)
    m = np.asarray(pc.fill_null(m, False).to_numpy(zero_copy_only=False), bool) if not isinstance(m, pa.Scalar) \
        else np.ones(n, bool)
    for name in ("ra", "dec", "mjd", "sigra", "sigdec"):
        c = _col(table, name)
        if c is None:
            if name in ("ra", "dec", "mjd"):
                return np.zeros(n, bool)
            continue
        a = c.to_numpy(zero_copy_only=False).astype(float)
        m &= np.isfinite(a)
        if name.startswith("sig"):
            m &= a > 0
    return m
