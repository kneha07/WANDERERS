"""survey/link.py building blocks on synthetic data: visits, tangent plane, per-visit sources, track linking
(friends-of-friends and the fast-mover velocity search), motion fits and parallax. No network."""
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from survey import link  # noqa: E402
from test_survey_core_synth import (CENTER, make_table, sources_from_table, star_field,  # noqa: E402
                                    visit_starts)


# ============================================================================================ split_visits
def test_split_visits_empty():
    v = link.split_visits(np.array([]))
    assert v.shape == (0,) and v.dtype.kind == "i"


def test_split_visits_single():
    assert link.split_visits([58000.0]).tolist() == [0]


def test_split_visits_two_visits_unsorted():
    mjd = np.array([58180.5, 58000.0, 58180.0, 58001.0, 58000.5])
    assert link.split_visits(mjd).tolist() == [1, 0, 1, 0, 0]


def test_split_visits_exact_gap_is_same_visit():
    assert link.split_visits([0.0, 20.0, 40.0], gap_days=20.0, max_len_days=100).tolist() == [0, 0, 0]
    assert link.split_visits([0.0, 20.001, 40.002], gap_days=20.0, max_len_days=100).tolist() == [0, 1, 2]


def test_split_visits_pole_continuous_coverage():
    mjd = np.arange(0.0, 60.0, 0.066)        # every orbit for 60 days (ecliptic pole)
    v = link.split_visits(mjd)
    assert v.max() + 1 == 5
    for k in range(5):
        sel = mjd[v == k]
        assert sel.max() - sel.min() <= 12.0
    assert (np.diff(v) >= 0).all()           # windows in time order


def test_split_visits_exact_max_len_is_one_window():
    assert link.split_visits([0.0, 6.0, 12.0], max_len_days=12.0).tolist() == [0, 0, 0]


def test_split_visits_dense_after_empty_windows():
    # one 30-day stretch with an internal 15-day hole: equal 10-day windows, the middle one empty
    mjd = np.r_[np.arange(0, 8, 0.5), np.arange(23, 30, 0.5)]
    v = link.split_visits(mjd)
    assert set(v.tolist()) == {0, 1}


def test_split_visits_nan_gets_minus_one():
    assert link.split_visits([58000.0, np.nan, 58000.2]).tolist() == [0, -1, 0]


def test_split_visits_real_fixture_cadence():
    from survey import tiles
    t = tiles.read_fixture(Path(__file__).resolve().parent / "fixtures" / "neowise_kapteyn_4arcmin.parquet",
                           columns=["mjd"])
    v = link.split_visits(t["mjd"].to_numpy())
    assert v.max() + 1 == 21                 # 21 visits 2014-2024, as NEOWISE observed it


# ============================================================================================ tangent plane
@pytest.mark.parametrize("ra0,dec0", [(150.0, 20.0), (0.0, 0.0), (359.9999, -30.0), (77.96, -45.04),
                                      (10.0, 89.9), (200.0, -89.95)])
def test_tangent_round_trip(ra0, dec0):
    rng = np.random.default_rng(3)
    xi, eta = rng.uniform(-3000, 3000, 50), rng.uniform(-3000, 3000, 50)
    ra, dec = link.from_tangent(xi, eta, ra0, dec0)
    x2, y2 = link.to_tangent(ra, dec, ra0, dec0)
    assert np.allclose(x2, xi, atol=1e-6) and np.allclose(y2, eta, atol=1e-6)
    assert ((ra >= 0) & (ra < 360)).all()


def test_tangent_axes_east_and_north():
    x, y = link.to_tangent(10.0 + 1.0 / 3600 / math.cos(math.radians(60.0)), 60.0, 10.0, 60.0)
    assert x == pytest.approx(1.0, abs=1e-4) and abs(y) < 1e-3
    x, y = link.to_tangent(10.0, 60.0 + 1.0 / 3600, 10.0, 60.0)
    assert y == pytest.approx(1.0, abs=1e-6) and abs(x) < 1e-6


def test_tangent_point_across_ra_wrap_and_pole():
    ra0, dec0 = link.tangent_point([359.99, 0.01], [5.0, 5.0])
    assert min(ra0, 360 - ra0) < 1e-6 and dec0 == pytest.approx(5.0, abs=1e-6)
    ra0, dec0 = link.tangent_point([0.0, 90.0, 180.0, 270.0], [89.0] * 4)
    assert dec0 == pytest.approx(90.0, abs=1e-6)


# ============================================================================================ visit_sources
def _clustered(sources, **kw):
    return sources_from_table(make_table(sources, **kw))


def test_visit_sources_one_row_per_source_and_visit():
    vs = _clustered([dict(ra=150.0, dec=20.0), dict(ra=150.01, dec=20.0), dict(ra=150.0, dec=20.01)],
                    starts=visit_starts(3), n_exp=10)
    assert len(vs["ra"]) == 9
    assert (vs["n"] == 10).all()
    assert sorted(np.bincount(vs["visit"]).tolist()) == [3, 3, 3]
    for key in ("ra", "dec", "epoch", "w1", "w2", "n", "sig", "visit"):
        assert len(vs[key]) == 9


def test_visit_sources_mean_position_and_error():
    sig = 0.3
    vs = _clustered([dict(ra=150.0, dec=20.0, sig=sig)], starts=visit_starts(30), n_exp=16, seed=5)
    x, y = link.to_tangent(vs["ra"], vs["dec"], 150.0, 20.0)
    pull = np.r_[x, y] / np.r_[vs["sig"], vs["sig"]]
    assert np.std(pull) == pytest.approx(1.0, abs=0.3)
    assert np.median(vs["sig"]) == pytest.approx(sig / 4, rel=0.35)


def test_visit_sources_drops_single_detections():
    # one source seen in only one exposure per visit (cosmic ray / asteroid-like) gives no rows
    vs = _clustered([dict(ra=150.0, dec=20.0)], starts=visit_starts(4), n_exp=1)
    assert len(vs["ra"]) == 0


def test_visit_sources_splits_close_pair_seen_in_same_exposures():
    # two stars 1.8" apart are chained by the 2.5" linking length but appear in the same exposures
    vs = _clustered([dict(ra=150.0, dec=20.0, sig=0.1), dict(ra=150.0, dec=20.0 + 1.8 / 3600, sig=0.1)],
                    starts=visit_starts(1), n_exp=12)
    assert len(vs["ra"]) == 2
    y = np.sort((vs["dec"] - 20.0) * 3600)
    assert y[0] == pytest.approx(0.0, abs=0.15) and y[1] == pytest.approx(1.8, abs=0.15)


def test_visit_sources_empirical_error_beats_formal():
    # saturated-star case: catalogue errors tiny (0.02") but real scatter 1"
    t = make_table([dict(ra=150.0, dec=20.0, sig=1.0)], starts=visit_starts(1), n_exp=25, seed=2)
    d = {c: t[c].to_numpy(zero_copy_only=False) for c in t.column_names}
    s = np.full(len(d["ra"]), 0.02)
    vs = link.visit_sources(d["ra"], d["dec"], d["mjd"], d["w1mpro"], d["w2mpro"], d["w1sigmpro"],
                            d["w2sigmpro"], s, s, np.zeros(len(s), int))
    assert len(vs["ra"]) == 1
    assert vs["sig"][0] == pytest.approx(1.0 / 5.0, rel=0.4)


def test_visit_sources_magnitudes_and_limits():
    t = make_table([dict(ra=150.0, dec=20.0, w1=16.8, w2=14.0)], starts=visit_starts(1), n_exp=6)
    d = {c: t[c].to_numpy(zero_copy_only=False) for c in t.column_names}
    w1err = np.full(len(d["ra"]), np.nan)                    # W1 only upper limits (WISE 0855-like)
    vs = link.visit_sources(d["ra"], d["dec"], d["mjd"], d["w1mpro"], d["w2mpro"], w1err, d["w2sigmpro"],
                            d["sigra"], d["sigdec"], np.zeros(len(w1err), int))
    assert vs["w1lim"][0] and not vs["w2lim"][0]
    assert vs["w1"][0] == pytest.approx(16.8, abs=0.05) and vs["w2"][0] == pytest.approx(14.0, abs=0.05)


def test_visit_sources_epoch_is_mean_detection_time():
    t = make_table([dict(ra=150.0, dec=20.0)], starts=[58000.0], n_exp=5, visit_len=2.0)
    vs = sources_from_table(t)
    assert vs["epoch"][0] == pytest.approx(link.mjd_to_year(58001.0), abs=1e-6)
    assert link.mjd_to_year(51544.5) == 2000.0


def test_visit_sources_ra_wrap():
    vs = _clustered([dict(ra=0.0, dec=10.0, sig=0.3)], starts=visit_starts(1), n_exp=12)
    assert len(vs["ra"]) == 1
    x, y = link.to_tangent(vs["ra"], vs["dec"], 0.0, 10.0)
    assert math.hypot(x[0], y[0]) < 0.3


def test_visit_sources_near_pole():
    vs = _clustered([dict(ra=123.0, dec=89.99, sig=0.3)], starts=visit_starts(2), n_exp=12)
    assert len(vs["ra"]) == 2
    x, y = link.to_tangent(vs["ra"], vs["dec"], 123.0, 89.99)
    assert np.hypot(x, y).max() < 0.4


def test_visit_sources_asteroid_not_clustered():
    # 30"/hour inside a visit: every exposure lands far from the previous one
    ast = dict(ra=150.0, dec=20.0, pmra=30.0 * 1000 * 24 * 365.25, pmdec=0.0, visits=[0])
    vs = _clustered([ast, dict(ra=150.01, dec=20.0)], starts=[58484.25], n_exp=12)   # visit at 2019.0
    assert len(vs["ra"]) == 1 and vs["ra"][0] == pytest.approx(150.01, abs=1e-5)    # only the star


def test_visit_sources_empty_input():
    vs = link.visit_sources([], [], [], [], [], [], [], [], [], [])
    assert set(vs) >= {"ra", "dec", "epoch", "w1", "w2", "n", "sig", "visit"} and len(vs["ra"]) == 0


# ============================================================================================ link_tracks
def _tracks(sources, **kw):
    vs = _clustered(sources, **kw)
    return vs, link.link_tracks(vs)


def _one_per_visit(vs, tracks):
    return all(len(np.unique(vs["visit"][t])) == len(t) for t in tracks)


def test_stationary_field_links_every_star_once():
    stars = star_field(120, seed=4)
    vs, tracks = _tracks(stars, n_exp=8)
    full = [t for t in tracks if len(t) >= 15]
    assert len(full) == 120
    assert all(len(t) == 20 for t in full)
    assert _one_per_visit(vs, tracks)
    used = np.concatenate(tracks)
    assert len(used) == len(np.unique(used))


def test_two_stars_closer_than_link_length_are_separated():
    a = dict(ra=150.0, dec=20.0, sig=0.15)
    b = dict(ra=150.0, dec=20.0 + 2.0 / 3600, sig=0.15)
    vs, tracks = _tracks([a, b], n_exp=10)
    assert len(tracks) == 2 and all(len(t) == 20 for t in tracks)
    assert _one_per_visit(vs, tracks)
    for t in tracks:                               # no mixing of the two stars
        y = (vs["dec"][t] - 20.0) * 3600
        assert np.ptp(y) < 1.0


def test_one_row_per_visit_split_keeps_star_and_extra_detection():
    # a star plus a second source 1.5" away that appears in only 3 visits: the chain takes two rows from those
    # visits and must be split into the star (20 visits) and the extra source
    star = dict(ra=150.0, dec=20.0, sig=0.1)
    extra = dict(ra=150.0, dec=20.0 + 1.5 / 3600, sig=0.1, visits=[3, 9, 15])
    vs, tracks = _tracks([star, extra], n_exp=10)
    assert _one_per_visit(vs, tracks)
    lens = sorted(len(t) for t in tracks)
    assert lens[-1] == 20


def test_crowded_random_field_one_row_per_visit():
    stars = star_field(400, seed=9, radius_deg=0.03, sig=0.3)    # ~10" spacing: many chains
    vs, tracks = _tracks(stars, n_exp=6)
    assert _one_per_visit(vs, tracks)
    used = np.concatenate(tracks)
    assert len(used) == len(np.unique(used))


def test_single_visit_sources_do_not_form_tracks():
    rng = np.random.default_rng(11)
    ssos = []
    for k in range(200):     # Solar-System-like: each seen in one visit only, somewhere in the field
        ssos.append(dict(ra=150.0 + rng.uniform(-0.2, 0.2), dec=20.0 + rng.uniform(-0.2, 0.2), visits=[k % 20]))
    vs, tracks = _tracks(ssos + star_field(30, seed=12), n_exp=6)
    assert all(len(t) <= 2 for t in tracks if len(t) < 15)
    assert sum(len(t) >= 15 for t in tracks) == 30


def test_slow_mover_linked_by_fof():
    m = dict(ra=150.0, dec=20.0, pmra=1500.0, pmdec=-800.0, sig=0.15)
    vs, tracks = _tracks([m] + star_field(40, seed=13), n_exp=8)
    best = max(tracks, key=len)
    assert len(best) == 20
    f = link.fit_motion(vs["epoch"][best], vs["ra"][best], vs["dec"][best], vs["sig"][best] + 0.02)
    assert f["pmra"] == pytest.approx(1500.0, abs=30) and f["pmdec"] == pytest.approx(-800.0, abs=30)


@pytest.mark.parametrize("speed", [3.0, 8.0, 11.0])
def test_fast_mover_recovered(speed):
    ang = math.radians(35.0)
    m = dict(ra=150.0, dec=20.0, pmra=speed * 1000 * math.sin(ang), pmdec=speed * 1000 * math.cos(ang),
             sig=0.2, w2=14.0)
    vs, tracks = _tracks([m] + star_field(80, seed=14), n_exp=8, seed=3)
    x, y = link.to_tangent(vs["ra"], vs["dec"], 150.0, 20.0)
    dt = vs["epoch"] - 2019.0
    on = np.hypot(x - m["pmra"] / 1000 * dt, y - m["pmdec"] / 1000 * dt) < 1.0
    best = max(tracks, key=lambda t: on[t].sum())
    assert on[best].sum() >= 19 and on[best].all()
    f = link.fit_motion(vs["epoch"][best], vs["ra"][best], vs["dec"][best], vs["sig"][best])
    assert f["pm"] == pytest.approx(speed * 1000, rel=0.01)


@pytest.mark.parametrize("speed", [3.0, 8.0, 11.0])
def test_velocity_search_alone_finds_mover_in_noise(speed):
    """The velocity search by itself (all rows in the pool) on a mover plus random single-visit rows."""
    rng = np.random.default_rng(int(speed))
    starts = visit_starts(20)
    t = link.mjd_to_year(starts + 0.5)
    vx, vy = speed * 0.6, speed * 0.8
    x = list(vx * (t - 2019.0) + rng.normal(0, 0.2, 20))
    y = list(vy * (t - 2019.0) + rng.normal(0, 0.2, 20))
    tt, vis = list(t), list(range(20))
    for v in range(20):                       # 60 unrelated rows per visit within +-120" (~4x a real pool)
        x += list(rng.uniform(-120, 120, 60))
        y += list(rng.uniform(-120, 120, 60))
        tt += [t[v]] * 60
        vis += [v] * 60
    x, y, tt, vis = map(np.asarray, (x, y, tt, vis))
    n = len(x)
    found = link._velocity_search(x, y, tt, vis, np.full(n, 0.2), np.full(n, np.nan), np.full(n, np.nan),
                                  np.arange(n))
    assert len(found) == 1
    assert set(found[0].tolist()) >= set(range(18))      # (almost) all of the mover's 20 rows


def test_fast_mover_with_missing_visits():
    m = dict(ra=150.0, dec=20.0, pmra=-8000.0, pmdec=700.0, sig=0.25, visits=[0, 1, 3, 4, 6, 9, 10, 12, 15, 17, 19])
    vs, tracks = _tracks([m] + star_field(40, seed=15), n_exp=8)
    x, y = link.to_tangent(vs["ra"], vs["dec"], 150.0, 20.0)
    dt = vs["epoch"] - 2019.0
    on = np.hypot(x + 8.0 * dt, y - 0.7 * dt) < 1.0
    best = max(tracks, key=lambda t: on[t].sum())
    assert on[best].sum() == 11


def _mover_track(vs, tracks, m):
    """The track holding most rows on the mover's true path (within 1")."""
    x, y = link.to_tangent(vs["ra"], vs["dec"], m["ra"], m["dec"])
    dt = vs["epoch"] - 2019.0
    on = np.hypot(x - m["pmra"] / 1000 * dt, y - m["pmdec"] / 1000 * dt) < 1.0
    best = max(tracks, key=lambda t: on[t].sum())
    return best, on


def test_fast_mover_across_ra_wrap():
    m = dict(ra=0.0, dec=5.0, pmra=9000.0, pmdec=-2000.0, sig=0.2)
    vs, tracks = _tracks([m] + star_field(30, seed=16, center=(0.0, 5.0)), n_exp=8)
    best, on = _mover_track(vs, tracks, m)
    assert (vs["ra"][best] > 359.99).any() and (vs["ra"][best] < 0.01).any()     # the track crosses RA 0
    assert on[best].sum() >= 19 and on[best].all()
    f = link.fit_motion(vs["epoch"][best], vs["ra"][best], vs["dec"][best], vs["sig"][best])
    assert f["pm"] == pytest.approx(math.hypot(9000.0, 2000.0), rel=0.01)


def test_fast_mover_near_pole():
    m = dict(ra=40.0, dec=86.5, pmra=-6000.0, pmdec=5000.0, sig=0.2)
    vs, tracks = _tracks([m] + star_field(30, seed=17, center=(40.0, 86.5)), n_exp=8)
    best, on = _mover_track(vs, tracks, m)
    assert on[best].sum() >= 19 and on[best].all()
    f = link.fit_motion(vs["epoch"][best], vs["ra"][best], vs["dec"][best], vs["sig"][best])
    assert f["pm"] == pytest.approx(math.hypot(6000.0, 5000.0), rel=0.01)


def test_velocity_search_rejects_pure_noise():
    rng = np.random.default_rng(21)
    x = rng.uniform(-300, 300, 20 * 300)
    y = rng.uniform(-300, 300, 20 * 300)
    vis = np.repeat(np.arange(20), 300)
    t = link.mjd_to_year(visit_starts(20) + 0.5)[vis]
    n = len(x)
    found = link._velocity_search(x, y, t, vis, np.full(n, 0.3), np.full(n, np.nan), np.full(n, np.nan),
                                  np.arange(n))
    assert found == []


def test_velocity_search_needs_consistent_brightness():
    t = link.mjd_to_year(visit_starts(20) + 0.5)
    x = 8.0 * (t - 2019.0)
    y = np.zeros(20)
    w2 = np.where(np.arange(20) % 2 == 0, 10.0, 14.0)    # alternating 10 and 14 mag: not one object
    vis = np.arange(20)
    found = link._velocity_search(x, y, t, vis, np.full(20, 0.2), np.full(20, np.nan), w2, np.arange(20))
    assert all(len(f) <= 10 for f in found)
    found = link._velocity_search(x, y, t, vis, np.full(20, 0.2), np.full(20, np.nan), np.full(20, 14.0),
                                  np.arange(20))
    assert len(found) == 1 and len(found[0]) == 20


def test_too_fast_for_search_not_linked():
    m = dict(ra=150.0, dec=20.0, pmra=25000.0, pmdec=0.0, sig=0.2)        # 25"/yr > 12"/yr limit
    vs, tracks = _tracks([m], n_exp=8)
    assert tracks == [] or max(len(t) for t in tracks) < 5


def test_link_tracks_empty():
    assert link.link_tracks(link.visit_sources([], [], [], [], [], [], [], [], [], [])) == []


# ============================================================================================ fit_motion
def _track(pmra, pmdec, n=20, sig=0.0, ra=150.0, dec=20.0, plx=0.0, seed=0, t=None):
    """Positions moving linearly on the tangent plane at (ra, dec) at 2019.0. The default epochs are symmetric
    about 2019.0 so the fit's reference point (mean position) is (ra, dec) and pmra/pmdec are exact there."""
    rng = np.random.default_rng(seed)
    t = np.linspace(2014.05, 2023.95, n) if t is None else t
    dt = t - 2019.0
    xi, eta = pmra / 1000 * dt, pmdec / 1000 * dt
    if plx:
        px, py = link.parallax_factors(t, ra, dec)
        xi, eta = xi + plx / 1000 * px, eta + plx / 1000 * py
    r, d = link.from_tangent(xi + rng.normal(0, sig, n) if sig else xi, eta + rng.normal(0, sig, n) if sig else eta,
                             ra, dec)
    return t, r, d


def test_fit_motion_noiseless_exact():
    t, r, d = _track(6491.2, -5708.6, ra=77.96, dec=-45.04)
    f = link.fit_motion(t, r, d, np.full(len(t), 0.1))
    assert f["pmra"] == pytest.approx(6491.2, abs=1e-3) and f["pmdec"] == pytest.approx(-5708.6, abs=1e-3)
    assert f["pm"] == pytest.approx(math.hypot(6491.2, 5708.6), abs=1e-3)
    assert f["chi2r"] < 1e-8 and f["n_visits"] == 20 and f["span_yr"] == pytest.approx(9.9)


def test_fit_motion_components_refer_to_mean_position():
    # pmra/pmdec are along the local east/north at the fitted (mean-epoch) position; near the pole those axes
    # turn quickly along the track, but the total pm does not depend on the reference point
    t, r, d = _track(4000.0, -2500.0, ra=300.0, dec=89.5, t=np.linspace(2014.2, 2024.1, 20))
    f = link.fit_motion(t, r, d, np.full(len(t), 0.1))
    assert f["pm"] == pytest.approx(math.hypot(4000.0, 2500.0), abs=0.01)
    assert f["pmra"] == pytest.approx(4000.0, abs=5.0)


def test_fit_motion_reference_epoch_and_position():
    t, r, d = _track(1000.0, 500.0)
    f = link.fit_motion(t, r, d, np.full(len(t), 0.1))
    assert f["epoch0"] == pytest.approx(np.mean(t)) and f["epoch"] == f["epoch0"]
    x, y = link.to_tangent(f["ra"], f["dec"], 150.0, 20.0)
    assert x == pytest.approx(1.0 * (np.mean(t) - 2019.0), abs=1e-6)
    assert y == pytest.approx(0.5 * (np.mean(t) - 2019.0), abs=1e-6)


def test_fit_motion_pmra_includes_cos_dec():
    t, r, d = _track(1000.0, 0.0, dec=60.0)
    f = link.fit_motion(t, r, d, np.full(len(t), 0.1))
    assert f["pmra"] == pytest.approx(1000.0, abs=0.01)
    dra = (r[-1] - r[0]) * 3600 * 1000 / (t[-1] - t[0])          # raw RA rate is 2x larger at dec 60
    assert dra == pytest.approx(2000.0, rel=0.01)


def test_fit_motion_error_matches_theory():
    sig = 0.2
    t, r, d = _track(0.0, 0.0, sig=sig, seed=1)
    f = link.fit_motion(t, r, d, np.full(len(t), sig))
    expect = sig / math.sqrt(np.sum((t - t.mean()) ** 2)) * 1000
    assert f["pmra_err"] == pytest.approx(expect, rel=0.4 if f["chi2r"] > 1 else 1e-6)
    assert f["pmra_err"] >= expect * 0.999


def test_fit_motion_pulls_are_unit_normal():
    pulls = []
    for s in range(300):
        t, r, d = _track(800.0, -300.0, sig=0.3, seed=s)
        f = link.fit_motion(t, r, d, np.full(len(t), 0.3))
        pulls.append((f["pmra"] - 800.0) / f["pmra_err"])
    pulls = np.array(pulls)
    assert abs(np.mean(pulls)) < 0.2
    assert 0.8 < np.std(pulls) < 1.1          # errors scaled by sqrt(chi2r) only when > 1: slightly conservative


def test_pm_snr_stationary_is_small_and_mover_is_large():
    t, r, d = _track(0.0, 0.0, sig=0.3, seed=7)
    still = link.fit_motion(t, r, d, np.full(len(t), 0.3))
    assert still["pm_snr"] < 4.0
    t, r, d = _track(500.0, 0.0, sig=0.3, seed=7)
    mover = link.fit_motion(t, r, d, np.full(len(t), 0.3))
    assert mover["pm_snr"] > 15.0
    assert mover["pm_snr"] == pytest.approx(mover["pm"] / mover["pm_err"])


def test_chi2r_flags_bad_track_and_inflates_error():
    t, r, d = _track(300.0, 300.0, sig=0.1, seed=3)
    good = link.fit_motion(t, r, d, np.full(len(t), 0.1))
    d_bad = d.copy()
    d_bad[::3] += 5.0 / 3600                      # every third visit 5" off: a chimera
    bad = link.fit_motion(t, r, d_bad, np.full(len(t), 0.1))
    assert 0.3 < good["chi2r"] < 2.5
    assert bad["chi2r"] > 50
    assert bad["pm_err"] > 5 * good["pm_err"]
    assert bad["pm_snr"] < good["pm_snr"]


def test_fit_motion_across_ra_wrap():
    t, r, d = _track(-3000.0, 1000.0, ra=0.0005, dec=0.0)
    assert (r > 359).any() and (r < 1).any()
    f = link.fit_motion(t, r, d, np.full(len(t), 0.1))
    assert f["pmra"] == pytest.approx(-3000.0, abs=0.01) and 0 <= f["ra"] < 360


def test_fit_motion_near_pole():
    t, r, d = _track(4000.0, -2500.0, ra=300.0, dec=89.5)
    f = link.fit_motion(t, r, d, np.full(len(t), 0.1))
    assert f["pmra"] == pytest.approx(4000.0, abs=0.05) and f["pmdec"] == pytest.approx(-2500.0, abs=0.05)


def test_fit_motion_jackknife_robust_to_outlier():
    t, r, d = _track(200.0, 0.0, sig=0.1, seed=4)
    clean = link.fit_motion(t, r, d, np.full(len(t), 0.1), jackknife=True)
    assert clean["pm_err_jackknife"] < 3 * clean["pm_err"]
    d2 = d.copy()
    d2[-1] += 3.0 / 3600                          # one wild last visit
    f = link.fit_motion(t, r, d2, np.full(len(t), 0.1), jackknife=True)
    plain = link.fit_motion(t, r, d2, np.full(len(t), 0.1))
    assert f["pm_err"] >= plain["pm_err"] and f["pm_err"] >= f["pm_err_jackknife"] - 1e-9


def test_fit_motion_degenerate_inputs():
    f = link.fit_motion([2019.0], [150.0], [20.0], [0.1])
    assert f["n_visits"] == 1 and math.isnan(f["pm"]) and f["ra"] == pytest.approx(150.0)
    f = link.fit_motion([], [], [], [])
    assert f["n_visits"] == 0
    f = link.fit_motion([2019.0, 2019.0], [150.0, 150.0], [20.0, 20.0], [0.1, 0.1])
    assert math.isnan(f["pm"])


# ============================================================================================ parallax
def test_earth_position_is_one_au_with_yearly_period():
    t = np.linspace(2015.0, 2016.0, 50)
    X, Y, Z = link.earth_position(t)
    r = np.sqrt(X ** 2 + Y ** 2 + Z ** 2)
    assert ((r > 0.98) & (r < 1.02)).all()
    e0, e1 = link.earth_position(2015.3), link.earth_position(2016.3)
    assert np.allclose(e0, e1, atol=0.01)


def test_earth_at_march_equinox_is_opposite_vernal_point():
    X, Y, Z = link.earth_position(2019.0 + (79.4 - 0.5) / 365.25)      # 2019-03-20
    assert X < -0.98 and abs(Y) < 0.1 and abs(Z) < 0.05


def test_parallax_factors_match_direct_geometry():
    ra0, dec0, plx = 133.79, -7.24, 0.439                       # WISE 0855-like, arcsec
    t = np.linspace(2014.0, 2016.0, 9)
    px, py = link.parallax_factors(t, ra0, dec0)
    d_au = 206264.806 / plx
    star = d_au * link._unit(ra0, dec0)
    for i, ti in enumerate(t):
        app = star - link.earth_position(ti)                    # direction seen from the Earth
        ra_a = math.degrees(math.atan2(app[1], app[0])) % 360
        dec_a = math.degrees(math.asin(app[2] / np.linalg.norm(app)))
        x, y = link.to_tangent(ra_a, dec_a, ra0, dec0)
        assert x == pytest.approx(plx * px[i], abs=2e-4) and y == pytest.approx(plx * py[i], abs=2e-4)


def test_parallax_recovered_with_neowise_cadence():
    # two visits a year, ~6 months apart, as NEOWISE observes a field
    t = link.mjd_to_year(visit_starts(20) + 0.6)
    tt, r, d = _track(-8123.0, 673.0, sig=0.05, ra=133.79, dec=-7.24, plx=439.0, seed=2, t=t)
    f = link.fit_motion(tt, r, d, np.full(len(tt), 0.05), parallax=True)
    assert f["plx"] == pytest.approx(439.0, abs=4 * f["plx_err"])
    assert f["plx_err"] < 60
    assert f["pmra"] == pytest.approx(-8123.0, abs=15) and f["pmdec"] == pytest.approx(673.0, abs=15)
    nop = link.fit_motion(tt, r, d, np.full(len(tt), 0.05))
    assert nop["plx"] is None and nop["chi2r"] > 5 * max(f["chi2r"], 0.2)


def test_parallax_auto_needs_enough_visits():
    t, r, d = _track(500.0, 0.0, n=6)
    assert link.fit_motion(t, r, d, np.full(6, 0.1), parallax="auto")["plx"] is None
    t, r, d = _track(500.0, 0.0, n=12, plx=100.0, t=link.mjd_to_year(visit_starts(12) + 0.6))
    f = link.fit_motion(t, r, d, np.full(12, 0.05), parallax="auto")
    assert f["plx"] == pytest.approx(100.0, abs=1.0)


# ============================================================================================ helpers
def test_scan_angle():
    # at the ecliptic north pole's meridian the scan runs north-south through the pole
    assert link.scan_angle(270.0, 30.0, 0.0, 1000.0) == pytest.approx(0.0, abs=1e-6)
    assert link.scan_angle(270.0, 30.0, 1000.0, 0.0) == pytest.approx(90.0, abs=1e-6)
    assert 0.0 <= link.scan_angle(77.96, -45.04, 6491.2, -5708.6) <= 90.0
