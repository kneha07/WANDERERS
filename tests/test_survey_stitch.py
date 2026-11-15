"""Regression tests for three fixes to the survey core found by the injection-recovery validation:

1. stitch_tracks: a fast mover whose step between two visits exceeds the 2.5" linking length (a missed visit, a
   long gap, parallax on top of a few arcsec/yr) used to come out of friends-of-friends as two fragments, each
   failing the coverage vetting, so bright 4"/yr movers were lost. Fragments on one straight line are now joined.
2. _can_blend: the blend rejection counted any source within 8", so a W2 = 8 mover passing 6" from a W2 = 15 field
   star was thrown away. Only a neighbour no more than 2.5 mag fainter can shift a centroid by arcseconds.
3. VISIT_SYS = 0: on real tile 8545 the per-visit errors alone give chi2r 0.4-1.2; the extra 0.05" made the
   proper-motion errors of bright stars ~3x too large.

No network.  python -m pytest -q tests/test_survey_stitch.py
"""
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
from survey import link  # noqa: E402
from test_survey_core_synth import CENTER, make_table, sources_from_table, visit_starts  # noqa: E402

T = 2014.1 + 0.5 * np.arange(21)          # 21 NEOWISE-like visit epochs


def _mover_rows(v, pa_deg, n=21, x0=0.0, y0=0.0, noise=0.0, seed=0, t=T):
    rng = np.random.default_rng(seed)
    vx, vy = v * math.sin(math.radians(pa_deg)), v * math.cos(math.radians(pa_deg))
    dt = t[:n] - 2019.0
    return x0 + vx * dt + rng.normal(0, noise, n), y0 + vy * dt + rng.normal(0, noise, n), t[:n].copy()


def _arrays(*groups):
    """Concatenate (x, y, t) groups; visits = index of the epoch in T. Returns x, y, t, vis, sig, row ranges."""
    xs, ys, ts, ranges, k = [], [], [], [], 0
    for x, y, t in groups:
        xs.append(x); ys.append(y); ts.append(t)
        ranges.append(np.arange(k, k + len(x)))
        k += len(x)
    t = np.concatenate(ts)
    vis = np.searchsorted(T, t - 1e-6)
    return np.concatenate(xs), np.concatenate(ys), t, vis, np.full(len(t), 0.1), ranges


# ============================================================================== 1. stitch_tracks (unit)
@pytest.mark.parametrize("v", [1.0, 2.0, 4.0, 8.0, 11.0])
@pytest.mark.parametrize("cut", [4, 10, 16])
@pytest.mark.parametrize("pa_deg", [30.0, 200.0])
def test_two_fragments_of_one_mover_are_joined(v, cut, pa_deg):
    x, y, t, vis, sig, (r,) = _arrays(_mover_rows(v, pa_deg, noise=0.15, seed=int(v * 10) + cut))
    out = link.stitch_tracks([r[:cut], r[cut:]], x, y, t, vis, sig)
    assert len(out) == 1
    assert sorted(out[0].tolist()) == r.tolist()
    assert np.all(np.diff(t[out[0]]) > 0), "joined track is sorted by epoch"


@pytest.mark.parametrize("v", [1.0, 4.0, 9.0])
def test_three_fragments_are_joined(v):
    x, y, t, vis, sig, (r,) = _arrays(_mover_rows(v, 75.0, noise=0.1, seed=3))
    out = link.stitch_tracks([r[:6], r[6:13], r[13:]], x, y, t, vis, sig)
    assert len(out) == 1 and len(out[0]) == 21


@pytest.mark.parametrize("ratio", [0.6, 0.75, 1.3, 1.6])
def test_fragments_with_different_speeds_stay_apart(ratio):
    a = _mover_rows(4.0, 90.0, n=21)
    b = _mover_rows(4.0 * ratio, 90.0, n=21)
    x = np.concatenate([a[0][:10], b[0][10:]])
    y = np.concatenate([a[1][:10], b[1][10:]])
    xx, yy, t, vis, sig, (r,) = _arrays((x, y, T.copy()))
    out = link.stitch_tracks([r[:10], r[10:]], xx, yy, t, vis, sig)
    assert len(out) == 2


@pytest.mark.parametrize("turn", [40.0, 90.0, 180.0])
def test_fragments_with_different_directions_stay_apart(turn):
    a = _mover_rows(3.0, 10.0)
    b = _mover_rows(3.0, 10.0 + turn)
    x = np.concatenate([a[0][:11], b[0][11:]])
    y = np.concatenate([a[1][:11], b[1][11:]])
    xx, yy, t, vis, sig, (r,) = _arrays((x, y, T.copy()))
    assert len(link.stitch_tracks([r[:11], r[11:]], xx, yy, t, vis, sig)) == 2


@pytest.mark.parametrize("offset", [3.0, 6.0, 30.0])
def test_parallel_movers_offset_beyond_tolerance_stay_apart(offset):
    a = _mover_rows(2.0, 0.0)
    b = _mover_rows(2.0, 0.0, x0=offset)
    xx, yy, t, vis, sig, (ra, rb) = _arrays((a[0][:10], a[1][:10], a[2][:10]), (b[0][10:], b[1][10:], b[2][10:]))
    assert len(link.stitch_tracks([ra, rb], xx, yy, t, vis, sig)) == 2


def test_fragments_sharing_a_visit_stay_apart():
    x, y, t, vis, sig, (r,) = _arrays(_mover_rows(4.0, 45.0))
    a, b = r[:11], r[10:]                     # both claim visit 10
    out = link.stitch_tracks([a, b], x, y, t, vis, sig)
    assert len(out) == 2


@pytest.mark.parametrize("v", [0.0, 0.03, 0.08])
def test_slow_or_stationary_fragments_are_not_joined(v):
    x, y, t, vis, sig, (r,) = _arrays(_mover_rows(v, 120.0))
    assert len(link.stitch_tracks([r[:10], r[10:]], x, y, t, vis, sig)) == 2


def test_two_row_fragments_are_left_alone():
    x, y, t, vis, sig, (r,) = _arrays(_mover_rows(4.0, 45.0))
    out = link.stitch_tracks([r[:2], r[2:4], r[4:]], x, y, t, vis, sig)
    assert len(out) == 3


def test_a_kinked_join_is_refused():
    # with the velocity gate opened wide (pm_frac=0.6), lines that meet at the common epoch but differ by 40% in
    # speed pass every gate except the last: the joined track is > 2.5" from any straight line at its ends
    a = _mover_rows(8.0, 90.0)
    b = _mover_rows(8.0 * 1.4, 90.0)
    x = np.concatenate([a[0][:11], b[0][11:]])
    y = np.concatenate([a[1][:11], b[1][11:]])
    xx, yy, t, vis, sig, (r,) = _arrays((x, y, T.copy()))
    tr, x0, y0, vx, vy = (q[0] for q in link._line_fits([r], xx, yy, t, 1 / sig ** 2))
    assert np.hypot(xx - x0 - vx * (t - tr), yy - y0 - vy * (t - tr)).max() > link.STITCH_TOL
    assert len(link.stitch_tracks([r[:11], r[11:]], xx, yy, t, vis, sig, pm_frac=0.6)) == 2
    assert len(link.stitch_tracks([r[:11], r[11:]], xx, yy, t, vis, sig, pm_frac=0.6, tol=50.0)) == 1


def test_short_noisy_fragments_use_their_velocity_errors():
    # 4-visit fragment of a 1"/yr mover: its speed is only known to ~0.1"/yr, more than 15% of 1"/yr
    x, y, t, vis, sig, (r,) = _arrays(_mover_rows(1.0, 10.0, noise=0.15, seed=5))
    assert len(link.stitch_tracks([r[:4], r[4:]], x, y, t, vis, sig)) == 1
    assert len(link.stitch_tracks([r[:4], r[4:]], x, y, t, vis, sig, nsig=0.0, pm_frac=0.01, pm_abs=0.0)) == 2


def test_other_tracks_are_untouched_and_rows_conserved():
    m = _mover_rows(4.0, 300.0, noise=0.1)
    s1 = (np.full(21, 50.0), np.full(21, -20.0), T.copy())
    s2 = (np.full(21, -80.0), np.full(21, 10.0), T.copy())
    x, y, t, vis, sig, (r, a, b) = _arrays(m, s1, s2)
    tracks = [r[:9], a, r[9:], b]
    out = link.stitch_tracks(tracks, x, y, t, vis, sig)
    assert len(out) == 3
    assert sorted(np.concatenate(out).tolist()) == list(range(len(x)))
    assert any(np.array_equal(g, a) for g in out) and any(np.array_equal(g, b) for g in out)


def test_two_unrelated_movers_each_joined_separately():
    m1 = _mover_rows(4.0, 0.0, noise=0.1, seed=1)
    m2 = _mover_rows(5.0, 180.0, x0=40.0, noise=0.1, seed=2)
    x, y, t, vis, sig, (r1, r2) = _arrays(m1, m2)
    out = link.stitch_tracks([r1[:8], r2[:12], r1[8:], r2[12:]], x, y, t, vis, sig)
    assert sorted(len(g) for g in out) == [21, 21]


def test_empty_and_single_track_inputs():
    x, y, t, vis, sig, (r,) = _arrays(_mover_rows(4.0, 0.0))
    assert link.stitch_tracks([], x, y, t, vis, sig) == []
    assert len(link.stitch_tracks([r], x, y, t, vis, sig)) == 1


# ============================================================ 1b. through link_tracks and select_movers
@pytest.mark.parametrize("speed", [3.0, 4.0, 4.5])
@pytest.mark.parametrize("gap_at", [6, 10, 14])
def test_mover_split_by_a_long_gap_is_found_whole(speed, gap_at):
    # visits gap_at and gap_at+1 missing: a 1.5 yr gap, a 4.5-6.75" step, beyond the 2.5" linking length
    vis = [i for i in range(20) if i not in (gap_at, gap_at + 1)]
    pa = math.radians(250.0)
    mover = dict(ra=CENTER[0], dec=CENTER[1], pmra=speed * 1000 * math.sin(pa), pmdec=speed * 1000 * math.cos(pa),
                 w1=11.0, w2=10.8, sig=0.15, visits=vis)
    stars = [dict(ra=CENTER[0] + 0.01 * k, dec=CENTER[1] - 0.008 * k, w1=12.0, w2=11.9) for k in range(1, 8)]
    vs = sources_from_table(make_table([mover, *stars], n_exp=8, seed=int(speed * 10) + gap_at))
    tracks = link.link_tracks(vs)
    movers = link.select_movers(link._tiles.tile_of(*CENTER), vs, tracks)
    assert len(movers) == 1, movers
    m = movers[0]
    assert m["n_visits"] == len(vis)
    assert abs(m["pm"] / 1000.0 - speed) / speed < 0.02


# ============================================================================== 2. blend rule
def _mags(w2=(), w1=()):
    return np.array(w1, float), np.array(w2, float)


@pytest.mark.parametrize("cand,nb,expected", [
    (8.0, 15.0, False),     # 7 mag fainter: cannot pull a W2 = 8 centroid
    (8.0, 10.6, False),     # 2.6 mag fainter
    (8.0, 10.4, True),      # 2.4 mag fainter
    (8.0, 8.0, True),       # equal
    (12.0, 9.0, True),      # brighter neighbour
    (14.5, 15.0, True),     # faint pair: the classic chimera
    (15.0, 14.0, True),
])
def test_can_blend_by_w2(cand, nb, expected):
    m1 = np.array([np.nan, np.nan])
    m2 = np.array([cand, nb])
    assert link._can_blend(1, 0, m1, m2) is expected


def test_can_blend_falls_back_to_w1_when_w2_is_missing():
    m1 = np.array([9.0, 16.0])
    m2 = np.array([np.nan, np.nan])
    assert link._can_blend(1, 0, m1, m2) is False
    m1 = np.array([9.0, 10.0])
    assert link._can_blend(1, 0, m1, m2) is True


def test_can_blend_without_a_common_band_is_conservative():
    m1 = np.array([9.0, np.nan])
    m2 = np.array([np.nan, 16.0])
    assert link._can_blend(1, 0, m1, m2) is True


def test_can_blend_custom_threshold():
    m1 = np.array([np.nan, np.nan])
    m2 = np.array([8.0, 12.0])
    assert link._can_blend(1, 0, m1, m2, dmag=5.0) is True
    assert link._can_blend(1, 0, m1, m2, dmag=3.0) is False


@pytest.mark.parametrize("sep", [4.0, 6.0, 7.5])
def test_bright_slow_mover_next_to_faint_star_is_kept_and_flagged_crowded(sep):
    # 0.5"/yr for 9.5 yr: < 16" of motion, a faint (W2 15) star `sep` arcsec away in every visit
    mover = dict(ra=CENTER[0], dec=CENTER[1], pmra=0.0, pmdec=500.0, w1=8.2, w2=8.0, sig=0.05)
    faint = dict(ra=CENTER[0] + sep / 3600 / math.cos(math.radians(CENTER[1])), dec=CENTER[1],
                 w1=15.2, w2=15.0, sig=0.3)
    vs = sources_from_table(make_table([mover, faint], n_exp=10, seed=int(sep)))
    rej = []
    movers = link.select_movers(link._tiles.tile_of(*CENTER), vs, link.link_tracks(vs), rejected=rej)
    assert len(movers) == 1, rej
    assert "crowded" in movers[0]["flags"]
    assert abs(movers[0]["pm"] - 500.0) < 15.0


@pytest.mark.parametrize("sep", [4.0, 6.0])
def test_faint_slow_mover_next_to_comparable_star_is_still_a_blend(sep):
    mover = dict(ra=CENTER[0], dec=CENTER[1], pmra=300.0, pmdec=0.0, w1=13.2, w2=13.0, sig=0.15)
    twin = dict(ra=CENTER[0], dec=CENTER[1] + sep / 3600, w1=13.4, w2=13.2, sig=0.15)
    vs = sources_from_table(make_table([mover, twin], n_exp=10, seed=int(sep) + 7))
    rej = []
    movers = link.select_movers(link._tiles.tile_of(*CENTER), vs, link.link_tracks(vs), rejected=rej)
    assert movers == []
    assert "blend" in [r for r, _ in rej]


# ============================================================================== 3. honest errors
def test_visit_systematic_defaults_to_zero():
    assert link.VISIT_SYS == 0.0
    import inspect
    assert inspect.signature(link.process_tile).parameters["visit_sys"].default == link.VISIT_SYS
    assert inspect.signature(link.select_movers).parameters["visit_sys"].default == link.VISIT_SYS


def test_bright_mover_pm_errors_are_not_overstated():
    pulls = []
    for seed in range(12):
        rng = np.random.default_rng(seed)
        pa = rng.uniform(0, 2 * math.pi)
        pm = 400.0
        mover = dict(ra=CENTER[0], dec=CENTER[1], pmra=pm * math.sin(pa), pmdec=pm * math.cos(pa),
                     w1=9.2, w2=9.0, sig=0.06)
        vs = sources_from_table(make_table([mover], n_exp=12, seed=100 + seed))
        m = link.select_movers(link._tiles.tile_of(*CENTER), vs, link.link_tracks(vs))
        assert len(m) == 1
        pulls.append(abs(m[0]["pm"] - pm) / m[0]["pm_err"])
    med = float(np.median(pulls))
    assert 0.2 < med < 2.5, f"median |pull| {med:.2f} (0.674 for honest errors)"
