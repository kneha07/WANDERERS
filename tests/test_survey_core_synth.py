"""Synthetic NEOWISE-like detection tables for the survey-core tests (imported by test_survey_link.py and
test_survey_core_process.py), plus checks that the generator itself behaves like NEOWISE.

A source is a dict: ra, dec (deg at REF_EPOCH), pmra, pmdec (mas/yr, pmra includes cos dec), plx (mas),
w1, w2 (mag), sig (arcsec per detection and axis), p (detection probability per exposure), visits (indices of
the visits it appears in; default all)."""
import sys
from pathlib import Path

import numpy as np
import pyarrow as pa

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
from survey import link, tiles  # noqa: E402

REF_EPOCH = 2019.0
CENTER = (150.0, 20.0)           # a quiet spot; its tile is TILE
TILE = tiles.tile_of(*CENTER)


def visit_starts(n_visits=20, start=56700.0, cadence=182.6):
    """NEOWISE-like visit start MJDs: one short visit every ~6 months (Feb/Aug from 2014)."""
    return start + cadence * np.arange(n_visits)


def positions(src, mjd):
    """True (ra, dec) of a source at the given MJDs: linear motion on the tangent plane plus parallax."""
    t = link.mjd_to_year(mjd)
    dt = t - REF_EPOCH
    xi = src.get("pmra", 0.0) / 1000.0 * dt
    eta = src.get("pmdec", 0.0) / 1000.0 * dt
    if src.get("plx"):
        px, py = link.parallax_factors(t, src["ra"], src["dec"])
        xi = xi + src["plx"] / 1000.0 * px
        eta = eta + src["plx"] / 1000.0 * py
    return xi, eta


def make_table(sources, starts=None, n_exp=10, visit_len=1.2, seed=0, nonnull=False):
    """A pyarrow table with all tiles.COLUMNS: every source observed in n_exp exposures per visit."""
    rng = np.random.default_rng(seed)
    starts = visit_starts() if starts is None else np.asarray(starts, float)
    cols = {c: [] for c in ("ra", "dec", "mjd", "sig", "w1", "w2")}
    for s in sources:
        vis = range(len(starts)) if s.get("visits") is None else s["visits"]
        for v in vis:
            mjd = starts[v] + np.linspace(0.0, visit_len, n_exp)
            det = rng.random(n_exp) < s.get("p", 1.0)
            if not det.any():
                continue
            mjd = mjd[det]
            xi, eta = positions(s, mjd)
            sg = s.get("sig", 0.15)
            xi = xi + rng.normal(0, sg, len(mjd))
            eta = eta + rng.normal(0, sg, len(mjd))
            ra, dec = link.from_tangent(xi, eta, s["ra"], s["dec"])
            cols["ra"].append(np.atleast_1d(ra))
            cols["dec"].append(np.atleast_1d(dec))
            cols["mjd"].append(mjd)
            cols["sig"].append(np.full(len(mjd), sg))
            cols["w1"].append(np.full(len(mjd), s.get("w1", 12.0)) + rng.normal(0, 0.03, len(mjd)))
            cols["w2"].append(np.full(len(mjd), s.get("w2", 12.0)) + rng.normal(0, 0.03, len(mjd)))
    arr = {k: (np.concatenate(v) if v else np.zeros(0)) for k, v in cols.items()}
    return table_from_arrays(arr["ra"], arr["dec"], arr["mjd"], arr["sig"], arr["w1"], arr["w2"], nonnull=nonnull)


def table_from_arrays(ra, dec, mjd, sig, w1, w2, nonnull=False, **over):
    n = len(ra)
    data = {
        "source_id": pa.array([f"s{i}" for i in range(n)], pa.string()),
        "ra": pa.array(ra, pa.float64()), "dec": pa.array(dec, pa.float64()),
        "sigra": pa.array(sig, pa.float64()), "sigdec": pa.array(sig, pa.float64()),
        "sigradec": pa.array(np.zeros(n), pa.float64()), "mjd": pa.array(mjd, pa.float64()),
        "w1mpro": pa.array(w1, pa.float64()), "w1sigmpro": pa.array(np.full(n, 0.03), pa.float64()),
        "w1snr": pa.array(np.full(n, 30.0), pa.float64()),
        "w2mpro": pa.array(w2, pa.float64()), "w2sigmpro": pa.array(np.full(n, 0.03), pa.float64()),
        "w2snr": pa.array(np.full(n, 30.0), pa.float64()),
        "cc_flags": pa.array(["0000"] * n, pa.string()), "ph_qual": pa.array(["AA"] * n, pa.string()),
        "nb": pa.array(np.ones(n, np.int64)), "na": pa.array(np.zeros(n, np.int64)),
        "qual_frame": pa.array(np.full(n, 10, np.int64)), "qi_fact": pa.array(np.ones(n)),
        "saa_sep": pa.array(np.full(n, 50.0)), "moon_masked": pa.array(["00"] * n, pa.string()),
        "scan_id": pa.array(["00001a"] * n, pa.string()), "frame_num": pa.array(np.ones(n, np.int64)),
    }
    for k, v in over.items():
        data[k] = v if isinstance(v, (pa.Array, pa.ChunkedArray)) else pa.array(v)
    t = pa.table({c: data[c] for c in tiles.COLUMNS})
    if nonnull:
        t = t.cast(pa.schema([f.with_nullable(False) for f in t.schema]))
    return t


def star_field(n=150, seed=1, center=CENTER, radius_deg=0.25, **kw):
    """n stationary stars with random positions (min separation enforced loosely) and magnitudes."""
    rng = np.random.default_rng(seed)
    r = radius_deg * np.sqrt(rng.random(n))
    a = rng.random(n) * 2 * np.pi
    xi, eta = r * np.cos(a) * 3600, r * np.sin(a) * 3600
    ra, dec = link.from_tangent(xi, eta, *center)
    mags = rng.uniform(9, 14, n)
    return [dict(ra=float(ra[i]), dec=float(dec[i]), w1=float(mags[i]), w2=float(mags[i] - 0.1), **kw)
            for i in range(n)]


def sources_from_table(table, visit=None):
    """visit_sources of a whole synthetic table (visits from split_visits)."""
    d = {c: table[c].to_numpy(zero_copy_only=False) for c in table.column_names}
    vis = link.split_visits(d["mjd"]) if visit is None else visit
    return link.visit_sources(d["ra"], d["dec"], d["mjd"], d["w1mpro"], d["w2mpro"], d["w1sigmpro"],
                              d["w2sigmpro"], d["sigra"], d["sigdec"], vis)


# --------------------------------------------------------------------------------- the generator itself
def test_generator_makes_neowise_cadence():
    t = make_table([dict(ra=150.0, dec=20.0)], n_exp=8)
    mjd = np.sort(t["mjd"].to_numpy())
    gaps = np.diff(mjd)
    assert t.num_rows == 20 * 8
    assert (gaps[gaps > 20] > 150).all() and (gaps > 20).sum() == 19
    assert set(t.column_names) == set(tiles.COLUMNS)


def test_generator_motion_is_linear_on_the_sky():
    src = dict(ra=150.0, dec=20.0, pmra=1000.0, pmdec=-500.0, sig=1e-6)
    t = make_table([src], n_exp=2)
    f = link.fit_motion(link.mjd_to_year(t["mjd"].to_numpy()), t["ra"].to_numpy(), t["dec"].to_numpy(),
                        np.full(t.num_rows, 0.01))
    assert abs(f["pmra"] - 1000.0) < 0.5 and abs(f["pmdec"] + 500.0) < 0.5
