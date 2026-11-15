"""survey/link.py process_tile and select_movers: the two real NEOWISE fixtures through a fake reader (Kapteyn's
Star and WISE 0855 must come out with the right motion), the TileResult/Mover contract, missing years, schema
differences between years, and the mover vetting on synthetic tiles. No network."""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pyarrow as pa
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from survey import link, tiles  # noqa: E402
from test_survey_core_synth import CENTER, TILE, make_table, star_field, visit_starts  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
KAPTEYN = FIX / "neowise_kapteyn_4arcmin.parquet"
W0855 = FIX / "neowise_wise0855_4arcmin.parquet"
TILE_KEYS = {"k5", "center", "years", "n_detections", "n_good", "n_visits", "n_visit_sources", "n_tracks",
             "n_movers", "seconds", "movers"}
MOVER_KEYS = {"id", "k5", "ra", "dec", "epoch", "pmra", "pmdec", "pm", "pm_err", "pm_snr", "chi2r", "n_visits",
              "span_yr", "w1", "w2", "w1w2", "plx", "plx_err", "track", "flags"}


def _nearest(movers, pmra, pmdec):
    return min(movers, key=lambda m: math.hypot(m["pmra"] - pmra, m["pmdec"] - pmdec))


def _pm_close(m, pmra, pmdec, frac=0.02):
    return math.hypot(m["pmra"] - pmra, m["pmdec"] - pmdec) <= frac * math.hypot(pmra, pmdec)


@pytest.fixture(scope="module")
def kapteyn():
    return link.process_tile(8545, reader=tiles.fixture_reader(KAPTEYN))


@pytest.fixture(scope="module")
def wise0855():
    return link.process_tile(10226, reader=tiles.fixture_reader(W0855))


# ============================================================================================ real fixtures
def test_kapteyn_recovered(kapteyn):
    m = _nearest(kapteyn["movers"], 6491.2, -5708.6)
    assert _pm_close(m, 6491.2, -5708.6)
    assert abs(m["pmra"] - 6491.2) / 6491.2 < 0.02 and abs(m["pmdec"] + 5708.6) / 5708.6 < 0.02
    assert m["n_visits"] >= 18 and m["span_yr"] > 9
    assert "saturated" in m["flags"] and "fast_search" in m["flags"]
    assert m["plx"] is None                       # not reported for saturated stars (scan-direction centroid shifts)
    # its 2016.0 position from the fit agrees with Gaia DR3 to ~1" (the saturated NEOWISE centroid)
    dt = 2016.0 - m["epoch"]
    ra16, dec16 = link.from_tangent(m["pmra"] / 1000 * dt, m["pmdec"] / 1000 * dt, m["ra"], m["dec"])
    x, y = link.to_tangent(ra16, dec16, 77.95994, -45.04381)
    assert math.hypot(x, y) < 1.5


def test_kapteyn_is_the_only_mover_in_its_cone(kapteyn):
    assert kapteyn["n_movers"] == 1 and len(kapteyn["movers"]) == 1


def test_wise0855_recovered(wise0855):
    m = _nearest(wise0855["movers"], -8123.0, 673.0)
    assert _pm_close(m, -8123.0, 673.0)
    assert abs(m["pmra"] + 8123.0) / 8123.0 < 0.02
    assert m["n_visits"] >= 18 and "fast_search" in m["flags"]
    assert m["w1w2"] is not None and m["w1w2"] > 2.0          # very red: a Y dwarf
    assert m["plx"] is not None and abs(m["plx"] - 439.0) < 3 * m["plx_err"]


def test_wise0855_field_has_no_junk_movers(wise0855):
    # the other mover in the cone is a real 190 mas/yr star seen in every visit with a clean fit
    for m in wise0855["movers"]:
        assert m["n_visits"] >= 18 and m["chi2r"] < 3 and m["pm_snr"] > 10


def test_tile_result_contract(kapteyn):
    assert TILE_KEYS <= set(kapteyn)
    assert kapteyn["k5"] == 8545 and len(kapteyn["center"]) == 2
    assert kapteyn["years"] == tiles.YEARS[:-1] and kapteyn["missing_years"] == ["addendum"]
    assert kapteyn["n_detections"] == 86209
    assert 0 < kapteyn["n_good"] < kapteyn["n_detections"]
    assert kapteyn["n_visits"] == 21
    assert kapteyn["n_visit_sources"] > kapteyn["n_tracks"] > 0
    assert kapteyn["n_movers"] == len(kapteyn["movers"])
    json.dumps(kapteyn, allow_nan=False)                     # strict JSON (no NaN) for the web page


def test_mover_contract(kapteyn, wise0855):
    for res in (kapteyn, wise0855):
        for i, m in enumerate(res["movers"]):
            assert MOVER_KEYS <= set(m)
            assert m["id"] == f"{res['k5']}-{i + 1:04d}" and m["k5"] == res["k5"]
            assert 1 <= len(m["track"]) <= 30
            ep = [p[0] for p in m["track"]]
            assert ep == sorted(ep) and all(len(p) == 3 for p in m["track"])
            assert m["pm"] == pytest.approx(math.hypot(m["pmra"], m["pmdec"]), abs=0.2)
            assert isinstance(m["flags"], list)
        snr = [m["pm_snr"] for m in res["movers"]]
        assert snr == sorted(snr, reverse=True)


def test_missing_years_still_recover_kapteyn():
    gone = ("year2", "year5", "year6", "year9")
    res = link.process_tile(8545, reader=tiles.fixture_reader(KAPTEYN, missing=gone))
    assert set(res["missing_years"]) == set(gone) | {"addendum"}
    assert res["n_visits"] < 21
    m = _nearest(res["movers"], 6491.2, -5708.6)
    assert _pm_close(m, 6491.2, -5708.6)


def test_all_years_missing():
    res = link.process_tile(8545, reader=lambda k5, year: None)
    assert res["n_detections"] == 0 and res["n_visits"] == 0 and res["movers"] == [] and res["n_movers"] == 0
    assert res["missing_years"] == tiles.YEARS
    json.dumps(res, allow_nan=False)


def test_reader_called_once_per_year_in_order():
    calls = []
    base = tiles.fixture_reader(W0855)

    def reader(k5, year):
        calls.append((k5, year))
        return base(k5, year)
    link.process_tile(10226, reader=reader)
    assert calls == [(10226, y) for y in tiles.YEARS]


def test_prefetch_off_gives_same_result(wise0855):
    res = link.process_tile(10226, reader=tiles.fixture_reader(W0855), prefetch=False)
    strip = lambda r: [{k: v for k, v in m.items()} for m in r["movers"]]  # noqa: E731
    assert strip(res) == strip(wise0855)
    assert res["n_visit_sources"] == wise0855["n_visit_sources"]


def test_thresholds_are_respected():
    reader = tiles.fixture_reader(KAPTEYN)
    assert link.process_tile(8545, reader=reader, min_pm=10000.0)["movers"] == []
    assert link.process_tile(8545, reader=reader, min_visits=25)["movers"] == []
    assert link.process_tile(8545, reader=reader, min_pm_snr=1e6)["movers"] == []


def test_years_with_different_nullability():
    base = tiles.fixture_reader(W0855)

    def reader(k5, year):                    # odd years: columns without nulls come back non-nullable
        t = base(k5, year)
        if t is not None and int(year[4:] if year.startswith("year") else 0) % 2:
            t = t.cast(pa.schema([f.with_nullable(t[f.name].null_count > 0) for f in t.schema]))
        return t
    res = link.process_tile(10226, reader=reader)
    m = _nearest(res["movers"], -8123.0, 673.0)
    assert _pm_close(m, -8123.0, 673.0)


# ============================================================================================ synthetic tiles
def _synth(sources, **kw):
    return link.process_tile(TILE, reader=tiles.fixture_reader(make_table(sources, **kw)))


def test_stationary_field_has_no_movers():
    res = _synth(star_field(150, seed=31, sig=0.2), n_exp=8)
    assert res["movers"] == []
    assert res["n_visits"] == 20
    assert res["n_tracks"] == pytest.approx(150, abs=3)


def test_synthetic_movers_recovered_and_asteroids_ignored():
    rng = np.random.default_rng(5)
    slow = dict(ra=150.05, dec=20.05, pmra=300.0, pmdec=-400.0, sig=0.15, w1=13.0, w2=12.8)
    mid = dict(ra=149.95, dec=19.95, pmra=-2500.0, pmdec=1500.0, sig=0.15, w1=14.0, w2=13.5)
    fast = dict(ra=150.0, dec=20.1, pmra=7000.0, pmdec=-4000.0, sig=0.2, w1=16.5, w2=14.0)
    ssos = [dict(ra=150 + rng.uniform(-0.2, 0.2), dec=20 + rng.uniform(-0.2, 0.2), visits=[k % 20],
                 pmra=float(rng.uniform(-3e7, 3e7)), pmdec=float(rng.uniform(-3e7, 3e7))) for k in range(40)]
    # the asteroids' pm is huge but they are defined at 2019.0: put them in a visit near that epoch
    for s in ssos:
        s["visits"] = [10]
    res = _synth([slow, mid, fast] + star_field(100, seed=32, sig=0.2) + ssos, n_exp=8)
    assert res["n_movers"] == 3
    for truth in (slow, mid, fast):
        m = _nearest(res["movers"], truth["pmra"], truth["pmdec"])
        assert _pm_close(m, truth["pmra"], truth["pmdec"])
        assert m["n_visits"] == 20
    m_fast = _nearest(res["movers"], 7000.0, -4000.0)
    m_slow = _nearest(res["movers"], 300.0, -400.0)
    assert "fast_search" in m_fast["flags"] and "fast_search" not in m_slow["flags"]
    assert m_fast["w1w2"] == pytest.approx(2.5, abs=0.1)


def test_visit_across_year_boundary_counted_once():
    boundary = tiles.YEAR_START_MJD["year4"]
    starts = np.r_[visit_starts(6), boundary - 0.6, boundary + 182.6, boundary + 365.2]
    starts.sort()
    res = _synth(star_field(30, seed=33), starts=starts, n_exp=8, visit_len=1.2)
    assert res["n_visits"] == len(starts)
    assert res["movers"] == []


def test_pole_like_continuous_coverage():
    # an ecliptic-pole field: observed every orbit (~1.6 h) for 40 days twice a year -> 12-day windows
    starts = np.concatenate([s + np.arange(0, 40, 0.066) for s in visit_starts(4)])
    star = dict(ra=150.0, dec=20.0, sig=0.3)
    mover = dict(ra=150.02, dec=20.0, pmra=900.0, pmdec=0.0, sig=0.3)
    res = _synth([star, mover], starts=starts, n_exp=1, visit_len=0.0)
    assert res["n_visits"] == 4 * 4                         # 40 days -> 4 windows of 10 days, 4 seasons
    # n_exp=1 per "visit start" -> every orbit is one exposure; windows hold ~150 detections per source
    assert res["n_visit_sources"] == 2 * 16
    m = _nearest(res["movers"], 900.0, 0.0)
    assert _pm_close(m, 900.0, 0.0, frac=0.05)


# ============================================================================================ vetting
def _vs(rows, center=CENTER):
    """A visit_sources dict from rows (visit, x, y[, n, sig, w1, w2]) on the tangent plane at center."""
    starts = visit_starts(20)
    ep = link.mjd_to_year(starts + 0.6)
    v = np.array([r[0] for r in rows])
    x = np.array([r[1] for r in rows], float)
    y = np.array([r[2] for r in rows], float)
    ra, dec = link.from_tangent(x, y, *center)
    n = np.array([r[3] if len(r) > 3 else 10 for r in rows], np.int32)
    sig = np.array([r[4] if len(r) > 4 else 0.1 for r in rows])
    w1 = np.array([r[5] if len(r) > 5 else 12.0 for r in rows], np.float32)
    w2 = np.array([r[6] if len(r) > 6 else 12.0 for r in rows], np.float32)
    return {"ra": np.atleast_1d(ra), "dec": np.atleast_1d(dec), "epoch": ep[v], "w1": w1, "w2": w2, "n": n,
            "sig": sig, "visit": v, "w1lim": np.zeros(len(v), bool), "w2lim": np.zeros(len(v), bool)}


def _field_rows(n_stars=40, seed=0, start_index=0):
    rng = np.random.default_rng(seed)
    pos = rng.uniform(-200, 200, (n_stars, 2))
    rows = [(v, px + rng.normal(0, 0.05), py + rng.normal(0, 0.05)) for px, py in pos for v in range(20)]
    tracks = [np.arange(start_index + 20 * i, start_index + 20 * (i + 1)) for i in range(n_stars)]
    return rows, tracks


def test_vetting_accepts_clean_mover():
    rows, tracks = _field_rows()
    base = len(rows)
    rows += [(v, 0.5 * (link.mjd_to_year(visit_starts(20)[v] + 0.6) - 2019.0), 0.0) for v in range(20)]
    tracks.append(np.arange(base, base + 20))
    rej = []
    movers = link.select_movers(TILE, _vs(rows), tracks, rejected=rej)
    assert len(movers) == 1 and movers[0]["pm"] == pytest.approx(500.0, rel=0.02)


def test_vetting_rejects_chimera_of_stationary_sources():
    # two stationary stars A, B 5" apart; a third "track" sits on A for 10 visits then on B: fake 500 mas/yr
    rows, tracks = _field_rows()
    base = len(rows)
    rows += [(v, 0.0, 0.0) for v in range(20)] + [(v, 5.0, 0.0) for v in range(20)]
    rows += [(v, 0.0 if v < 10 else 5.0, 0.03) for v in range(20)]
    tracks += [np.arange(base, base + 20), np.arange(base + 20, base + 40), np.arange(base + 40, base + 60)]
    rej = []
    movers = link.select_movers(TILE, _vs(rows), tracks, rejected=rej)
    assert movers == []
    assert any(r[0] in ("stationary_rows", "halves", "chi2r", "blend") for r in rej)


def test_vetting_rejects_poor_coverage():
    rows, tracks = _field_rows()
    base = len(rows)
    seen = [0, 3, 6, 9, 12, 15, 17, 19]                      # 8 of 20 visits that observed the field
    ep = link.mjd_to_year(visit_starts(20) + 0.6)
    rows += [(v, 1.0 * (ep[v] - 2019.0), 0.0) for v in seen]
    tracks.append(np.arange(base, base + len(seen)))
    rej = []
    assert link.select_movers(TILE, _vs(rows), tracks, rejected=rej) == []
    assert [r[0] for r in rej] == ["coverage"]


def test_vetting_rejects_marginal_detections():
    rows, tracks = _field_rows()
    base = len(rows)
    ep = link.mjd_to_year(visit_starts(20) + 0.6)
    rows += [(v, 1.0 * (ep[v] - 2019.0), 0.0, 2) for v in range(20)]        # 2 detections per visit
    tracks.append(np.arange(base, base + 20))
    rej = []
    assert link.select_movers(TILE, _vs(rows), tracks, rejected=rej) == []
    assert [r[0] for r in rej] == ["few_detections"]


def test_vetting_rejects_huge_chi2r():
    rows, tracks = _field_rows()
    base = len(rows)
    ep = link.mjd_to_year(visit_starts(20) + 0.6)
    rng = np.random.default_rng(3)
    rows += [(v, 1.0 * (ep[v] - 2019.0) + rng.normal(0, 1.5), rng.normal(0, 1.5), 10, 0.05) for v in range(20)]
    tracks.append(np.arange(base, base + 20))
    rej = []
    assert link.select_movers(TILE, _vs(rows), tracks, max_chi2r=25.0, rejected=rej) == []
    assert rej and rej[0][0] in ("chi2r", "criteria", "jackknife")


def test_flags_saturated_and_limits():
    rows, tracks = _field_rows()
    base = len(rows)
    ep = link.mjd_to_year(visit_starts(20) + 0.6)
    rows += [(v, 0.8 * (ep[v] - 2019.0), 0.0, 20, 0.1, 4.0, 4.2) for v in range(20)]
    tracks.append(np.arange(base, base + 20))
    vs = _vs(rows)
    vs["w1lim"][base:] = False
    m = link.select_movers(TILE, vs, tracks)[0]
    assert "saturated" in m["flags"]
    vs["w1lim"][base:] = True
    m = link.select_movers(TILE, vs, tracks)[0]
    assert "w1_limit" in m["flags"]


def test_flag_tile_edge():
    # a 10"/yr mover heading for a tile corner, 20" inside it in 2019: it leaves the tile before 2024.7
    ra_c, dec_c = tiles.tile_center(TILE)
    corners = tiles.tile_corners(TILE)
    cra, cdec = corners[0]
    cx, cy = link.to_tangent(cra, cdec, ra_c, dec_c)
    ux, uy = cx / math.hypot(cx, cy), cy / math.hypot(cx, cy)
    start = (float(cx) - 20 * ux, float(cy) - 20 * uy)
    rows, tracks = _field_rows()
    base = len(rows)
    ep = link.mjd_to_year(visit_starts(20) + 0.6)
    rows += [(v, start[0] + 10.0 * ux * (ep[v] - 2019.0), start[1] + 10.0 * uy * (ep[v] - 2019.0)) for v in range(20)]
    tracks.append(np.arange(base, base + 20))
    m = link.select_movers(TILE, _vs(rows, center=(ra_c, dec_c)), tracks)
    assert len(m) == 1 and "tile_edge" in m[0]["flags"]


def test_select_movers_without_tracks():
    assert link.select_movers(TILE, _vs([(0, 0.0, 0.0)]), []) == []
