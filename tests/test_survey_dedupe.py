"""Tests for pipeline/survey/dedupe.py and its use in run.publish: movers found twice, in two neighbouring HEALPix
tiles, are merged (better track kept, the other id under "duplicates") and counted once in summary.json.

Synthetic movers are placed on both sides of real tile boundaries (found with survey.tiles / astropy_healpix),
including across RA 0/360 and around both poles. No network.

    .venv/bin/python -m pytest tests/test_survey_dedupe.py -q
"""
import json
import math
import random
import sys
import types
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "tests"))
from survey import dedupe as D  # noqa: E402
from survey import run as R  # noqa: E402
from survey import tiles as T  # noqa: E402
import test_survey_run_fakes as fakes  # noqa: E402


# ---------------------------------------------------------------------------------------------- helpers
def east_north(ra, dec):
    a, d = math.radians(ra), math.radians(dec)
    return (np.array([-math.sin(a), math.cos(a), 0.0]),
            np.array([-math.sin(d) * math.cos(a), -math.sin(d) * math.sin(a), math.cos(d)]))


def toward(ra, dec, ra2, dec2, pm):
    """(pmra, pmdec) of a motion of `pm` mas/yr from (ra, dec) towards (ra2, dec2)."""
    p, q = D.unit(ra, dec), D.unit(ra2, dec2)
    t = q - p * float(p @ q)
    e, n = east_north(ra, dec)
    v = np.array([t @ e, t @ n])
    v = v / np.linalg.norm(v) * pm
    return float(v[0]), float(v[1])


def edge_point(k_a, k_b, steps=60):
    """A point on the boundary between touching tiles k_a and k_b: bisection along the great circle from one
    centre to the other. None when the line passes through a third tile there."""
    pa, pb = D.unit(*T.tile_center(k_a)), D.unit(*T.tile_center(k_b))

    def at(f):
        v = pa * (1 - f) + pb * f
        r, d = D.radec(v / np.linalg.norm(v))
        return float(r), float(d)
    lo, hi = 0.0, 1.0
    for _ in range(steps):
        mid = (lo + hi) / 2
        if T.tile_of(*at(mid)) == k_a:
            lo = mid
        else:
            hi = mid
    if T.tile_of(*at(hi)) != k_b:
        return None
    return at((lo + hi) / 2)


def edge_pair(k_a):
    """A touching tile k_b (sharing an edge with k_a) and a point on their common edge."""
    for k_b in sorted(D.neighbours(k_a)):
        p = edge_point(k_a, k_b)
        if p is not None:
            return k_b, p
    raise AssertionError(f"no edge neighbour found for tile {k_a}")


def mover(mid, k5, ra, dec, epoch, pmra, pmdec, pm_err=4.0, n_visits=10, pm_snr=50.0, **kw):
    return {"id": mid, "k5": k5, "ra": ra, "dec": dec, "epoch": epoch, "pmra": pmra, "pmdec": pmdec,
            "pm": math.hypot(pmra, pmdec), "pm_err": pm_err, "pm_snr": pm_snr, "n_visits": n_visits, **kw}


def split_source(k_a, k_b, point, pm=2000.0, ep_a=2016.8, ep_b=2022.2, t0=2019.5, nv=(12, 8), snr=(60.0, 40.0),
                 jitter=(0.0, 0.0), dpm=(0.0, 0.0)):
    """Two movers, one per tile, that are the same source: it sits on the shared edge at t0 and moves from k_a
    into k_b. Each copy is the source at its own epoch (plus optional position jitter in arcsec / motion offset)."""
    ra0, dec0 = point
    pmra, pmdec = toward(ra0, dec0, *T.tile_center(k_b), pm)
    a_ra, a_dec = D.propagate(ra0, dec0, pmra, pmdec, ep_a - t0)
    b_ra, b_dec = D.propagate(ra0, dec0, pmra, pmdec, ep_b - t0)
    b_ra += jitter[0] / 3600.0 / max(math.cos(math.radians(b_dec)), 1e-6)
    b_dec += jitter[1] / 3600.0
    a = mover(f"{k_a}-0001", k_a, a_ra, a_dec, ep_a, pmra, pmdec, n_visits=nv[0], pm_snr=snr[0])
    b = mover(f"{k_b}-0001", k_b, b_ra % 360.0, b_dec, ep_b, pmra + dpm[0], pmdec + dpm[1], n_visits=nv[1],
              pm_snr=snr[1])
    return a, b


K_EQ = T.tile_of(77.96, -45.04)          # Kapteyn's Star's tile, 8545
K_B, EDGE = edge_pair(K_EQ)


# ---------------------------------------------------------------------------------------------- geometry
def test_propagate_wraps_ra_through_zero():
    ra, dec = D.propagate(359.9999, 10.0, 1000.0, 0.0, 1.0)          # 1"/yr east for a year
    assert 0.0 <= ra < 0.001 and abs(dec - 10.0) < 1e-6
    assert abs(D.sep_arcsec(D.unit(ra, dec), D.unit(359.9999, 10.0)) - 1.0) < 1e-4


def test_propagate_through_the_pole_flips_ra():
    ra, dec = D.propagate(30.0, 89.99995, 0.0, 1000.0, 0.36)        # 0.18" from the pole, 0.36" further north
    assert abs(ra - 210.0) < 1e-6 and abs(dec - (90 - 0.18 / 3600)) < 1e-7


def test_velocity_is_frame_free_at_the_pole():
    """The same motion written in the east/north frames of two RAs near the pole is one 3D vector."""
    v1 = D.velocity(45.0, 89.9999, 300.0, 0.0)
    e45, _ = east_north(45.0, 89.9999)
    e135, n135 = east_north(135.0, 89.9999)
    pmra, pmdec = 300.0 * float(e45 @ e135), 300.0 * float(e45 @ n135)
    v2 = D.velocity(135.0, 89.9999, pmra, pmdec)
    assert np.linalg.norm(v1 - v2) < 0.01


def test_tolerances_have_floors_and_caps():
    a = D.record(mover("1-0001", 1, 10, 10, 2019.0, 200.0, 0.0, pm_err=0.5))
    b = D.record(mover("2-0001", 2, 10, 10, 2019.0, 200.0, 0.0, pm_err=0.5))
    t, pos, pmt = D.tolerances(a, b)
    assert t == 2019.0 and pos == pytest.approx(3.0 + 3 * math.hypot(0.15, 0.15)) and pmt == D.PM_FLOOR
    a["pm_err"] = b["pm_err"] = 5000.0
    a["epoch"], b["epoch"] = 2014.0, 2024.0
    t, pos, pmt = D.tolerances(a, b)
    assert pos == D.MAX_POS_TOL_ARCSEC and pmt == D.PM_MAX_TOL


def test_compare_is_symmetric():
    a, b = split_source(K_EQ, K_B, EDGE, jitter=(0.8, -0.5), dpm=(6.0, -4.0))
    ra_, rb_ = D.record(a), D.record(b)
    c1, c2 = D.compare(ra_, rb_), D.compare(rb_, ra_)
    assert c1["same"] and c2["same"]
    assert c1["sep_arcsec"] == pytest.approx(c2["sep_arcsec"]) and c1["dpm"] == pytest.approx(c2["dpm"])


# ---------------------------------------------------------------------------------------------- duplicates found
def test_synthetic_movers_sit_on_both_sides_of_a_real_boundary():
    a, b = split_source(K_EQ, K_B, EDGE)
    assert T.tile_of(a["ra"], a["dec"]) == K_EQ and T.tile_of(b["ra"], b["dec"]) == K_B
    assert D.touching(K_EQ, K_B)


def test_two_halves_of_one_track_are_merged_keeping_more_visits():
    a, b = split_source(K_EQ, K_B, EDGE, nv=(7, 13), jitter=(0.6, 0.4), dpm=(5.0, -3.0))
    res = D.find_duplicates([a, b])
    assert res["drop"] == {a["id"]: b["id"]} and res["groups"] == {b["id"]: [a["id"]]}
    (p,) = res["pairs"]
    assert p["sep_arcsec"] < 1.0 and p["dpm"] < 7.0 and {p["k5_a"], p["k5_b"]} == {K_EQ, K_B}


def test_equal_visits_keep_the_higher_pm_snr_then_the_smaller_id():
    a, b = split_source(K_EQ, K_B, EDGE, nv=(10, 10), snr=(30.0, 80.0))
    assert D.find_duplicates([a, b])["groups"] == {b["id"]: [a["id"]]}
    a, b = split_source(K_EQ, K_B, EDGE, nv=(10, 10), snr=(50.0, 50.0))
    keep = min(a["id"], b["id"])
    for order in ([a, b], [b, a]):
        assert list(D.find_duplicates(order)["groups"]) == [keep]


def test_different_epochs_are_compared_at_their_midpoint():
    a, b = split_source(K_EQ, K_B, EDGE, pm=6000.0, ep_a=2015.2, ep_b=2023.9)
    assert D.sep_arcsec(D.unit(a["ra"], a["dec"]), D.unit(b["ra"], b["dec"])) > 50      # 8.7 yr x 6"/yr apart
    res = D.find_duplicates([a, b])
    assert len(res["drop"]) == 1 and res["pairs"][0]["epoch"] == pytest.approx((2015.2 + 2023.9) / 2)


def test_slow_mover_sitting_on_the_edge_is_merged():
    a, b = split_source(K_EQ, K_B, EDGE, pm=160.0, ep_a=2019.1, ep_b=2019.3, jitter=(0.3, 0.2))
    assert D.same_source(a, b)


def test_fast_mover_with_loose_halves_is_merged_within_its_errors():
    a, b = split_source(K_EQ, K_B, EDGE, pm=9000.0, dpm=(400.0, 0.0))
    a["pm_err"] = b["pm_err"] = 150.0                        # 3 sigma combined = 636 mas/yr
    assert D.same_source(a, b)
    a["pm_err"] = b["pm_err"] = 5.0                          # now 400 mas/yr is 57 sigma, and over 3 % of 9"/yr
    assert not D.same_source(a, b)


def test_ra_wrap_pair_across_0_360_is_merged():
    dec = next(d for d in np.arange(0.05, 60.0, 0.05) if T.tile_of(359.9995, d) != T.tile_of(0.0005, d))
    k_w, k_e = T.tile_of(359.9995, dec), T.tile_of(0.0005, dec)
    assert D.touching(k_w, k_e)
    a = mover(f"{k_w}-0003", k_w, 359.9995, dec, 2017.0, 400.0, 10.0, n_visits=9)
    ra_b, dec_b = D.propagate(359.9995, dec, 400.0, 10.0, 4.0)
    assert 0.0 < ra_b < 1.0
    b = mover(f"{k_e}-0007", k_e, ra_b, dec_b, 2021.0, 405.0, 12.0, n_visits=11)
    assert T.tile_of(ra_b, dec_b) == k_e
    assert D.find_duplicates([a, b])["groups"] == {b["id"]: [a["id"]]}


@pytest.mark.parametrize("pole", [89.9996, -89.9996])
def test_pole_pair_from_two_polar_tiles_is_merged(pole):
    k1, k2 = T.tile_of(45.0, pole), T.tile_of(135.0, pole)
    assert k1 != k2 and D.touching(k1, k2)
    # one source crossing from (45, pole) in 2018 to (135, pole) in 2020, ~1"/yr; each copy writes the same
    # motion in its own east/north frame
    p1, p2 = D.unit(45.0, pole), D.unit(135.0, pole)
    v = (p2 - p1) / 2.0 * D.MAS_PER_RAD
    assert 500 < np.linalg.norm(v) < 1500
    recs = []
    for k5, ra, ep in ((k1, 45.0, 2018.0), (k2, 135.0, 2020.0)):
        e, n = east_north(ra, pole)
        recs.append(mover(f"{k5}-0002", k5, ra, pole, ep, float(v @ e), float(v @ n),
                          n_visits=8 if k5 == k1 else 6))
    assert abs(recs[0]["ra"] - recs[1]["ra"]) > 20             # RAs far apart, the sky positions are not
    assert D.find_duplicates(recs)["drop"] == {recs[1]["id"]: recs[0]["id"]}


def test_three_tiles_at_a_corner_make_one_group():
    a, b = split_source(K_EQ, K_B, EDGE, nv=(12, 8))
    k_c = next(k for k in sorted(D.neighbours(K_EQ) & D.neighbours(K_B)))
    c = dict(b, id=f"{k_c}-0009", k5=k_c, n_visits=6, pm_snr=20.0)
    res = D.find_duplicates([c, b, a])
    assert res["groups"] == {a["id"]: [b["id"], c["id"]]}
    assert res["drop"] == {b["id"]: a["id"], c["id"]: a["id"]}


def test_result_does_not_depend_on_input_order():
    movers = []
    for i, (jx, jy) in enumerate([(0.2, 0.1), (-0.4, 0.3)]):
        a, b = split_source(K_EQ, K_B, EDGE, pm=1500.0 + 900 * i, jitter=(jx, jy))
        a["id"], b["id"] = f"{K_EQ}-{i + 1:04d}", f"{K_B}-{i + 1:04d}"
        movers += [a, b]
    want = D.find_duplicates(movers)
    for seed in range(5):
        shuffled = movers[:]
        random.Random(seed).shuffle(shuffled)
        got = D.find_duplicates(shuffled)
        assert got["drop"] == want["drop"] and got["groups"] == want["groups"]
    assert len(want["drop"]) == 2


# ---------------------------------------------------------------------------------------------- kept apart
def test_same_place_different_motion_stays_two():
    a, b = split_source(K_EQ, K_B, EDGE, pm=1000.0, dpm=(200.0, 0.0))
    assert D.find_duplicates([a, b])["drop"] == {}


def test_same_motion_ten_arcsec_apart_stays_two():
    a, b = split_source(K_EQ, K_B, EDGE, pm=1000.0, jitter=(0.0, 10.0))
    assert not D.same_source(a, b)


def test_common_motion_pair_five_arcsec_apart_stays_two():
    a, b = split_source(K_EQ, K_B, EDGE, pm=500.0, jitter=(5.0, 0.0))
    assert D.compare(D.record(a), D.record(b))["sep_arcsec"] > 4.5
    assert D.find_duplicates([a, b])["drop"] == {}


def test_movers_of_the_same_tile_are_never_merged():
    a, b = split_source(K_EQ, K_B, EDGE)
    b = dict(b, k5=K_EQ, id=f"{K_EQ}-0002")
    assert D.find_duplicates([a, b])["drop"] == {} and not D.same_source(a, b)


def test_tiles_that_do_not_touch_are_not_merged_unless_asked():
    a, b = split_source(K_EQ, K_B, EDGE)
    far = next(k for k in range(T.N_TILES) if k != K_EQ and not D.touching(K_EQ, k))
    b = dict(b, k5=far, id=f"{far}-0001")
    assert D.find_duplicates([a, b])["drop"] == {}
    assert D.find_duplicates([a, b], require_neighbours=False)["drop"] == {b["id"]: a["id"]}


def test_incomplete_movers_are_skipped_not_fatal():
    a, b = split_source(K_EQ, K_B, EDGE)
    broken = [dict(b, pmra=None), dict(b, ra="nan", id="x-1"), {"id": "y"}, "not a mover", dict(b, k5=None, id="z")]
    res = D.find_duplicates([a, *broken])
    assert res["drop"] == {} and res["n_checked"] == 1
    assert D.record(dict(a, pm=None, pm_err=None))["pm"] == pytest.approx(a["pm"])
    assert D.record(dict(a, pm_err=None))["pm_err"] == D.DEFAULT_PM_ERR


def test_many_unrelated_movers_give_no_false_merges():
    rng = np.random.default_rng(7)
    n = 3000
    ra, dec = rng.uniform(0, 360, n), np.degrees(np.arcsin(rng.uniform(-1, 1, n)))
    k = T.tile_of(ra, dec)
    movers = [mover(f"{int(k[i])}-{i:04d}", int(k[i]), float(ra[i]), float(dec[i]), 2019.0 + rng.normal(0, 0.5),
                    float(rng.normal(0, 400)), float(rng.normal(0, 400))) for i in range(n)]
    res = D.find_duplicates(movers)
    assert res["drop"] == {} and res["n_checked"] == n


def test_merge_drops_copies_and_lists_them_on_the_kept_mover():
    a, b = split_source(K_EQ, K_B, EDGE, nv=(14, 7))
    other = mover("1-0001", 1, 10.0, 0.5, 2019.0, 300.0, 0.0)
    kept, res = D.merge([b, other, a])
    assert [m["id"] for m in kept] == ["1-0001", a["id"]]
    assert kept[1]["duplicates"] == [b["id"]] and "duplicates" not in kept[0]
    assert "duplicates" not in a, "the input is not changed"


def test_dedupe_cli_reads_a_tiles_folder(tmp_path, capsys):
    a, b = split_source(K_EQ, K_B, EDGE)
    for m in (a, b):
        (tmp_path / f"{m['k5']}.json").write_text(json.dumps({"k5": m["k5"], "movers": [m]}))
    (tmp_path / "notes.json").write_text("{}")
    (tmp_path / "77.json").write_text("not json")
    assert D.main([str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("2 movers in 2 tiles (1 pairs of touching tiles): 1 duplicates in 1 groups")
    assert f"{a['id']} = {b['id']}" in out or f"{b['id']} = {a['id']}" in out
    assert D.main([str(tmp_path), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["drop"] == {b["id"]: a["id"]} and data["touching_tile_pairs"] == 1


# ---------------------------------------------------------------------------------------------- publish
@pytest.fixture
def env(tmp_path, monkeypatch):
    spec = tmp_path / "spec.json"
    monkeypatch.setenv("SURVEY_FAKE_SPEC", str(spec))
    fakes.write_spec(spec, log=str(tmp_path / "calls.jsonl"))
    fakes.XMATCH_CALLS.clear()
    fakes.RANK_CALLS.clear()
    return types.SimpleNamespace(out=tmp_path / "out", cache=tmp_path / "cache")


def tile_with(k5, movers, n_extra=0):
    """A tile result holding the given movers plus n_extra unrelated ones near the tile centre."""
    ra0, dec0 = T.tile_center(k5)
    ms = [dict(m, w1=14.0, w2=13.0, w1w2=1.0, chi2r=1.1, span_yr=5.0, plx=None, plx_err=None,
               track=[[2015.0, m["ra"], m["dec"]], [2020.0, m["ra"], m["dec"]]], flags=["tile_edge"]) for m in movers]
    for i in range(n_extra):
        ms.append(dict(mover(f"{k5}-{len(ms) + 1:04d}", k5, ra0 + 0.01 * i, dec0, 2019.0, 300.0 + 10 * i, 0.0),
                       w1=12.0, w2=12.0, w1w2=0.0, chi2r=1.0, span_yr=9.0, plx=None, plx_err=None,
                       track=[[2015.0, ra0, dec0], [2020.0, ra0, dec0]], flags=[]))
    return {"k5": k5, "center": [ra0, dec0], "years": fakes.YEARS, "n_detections": 1000, "n_good": 900,
            "n_visits": 20, "n_visit_sources": 500, "n_tracks": 50, "n_movers": len(ms), "seconds": 1.0, "movers": ms}


def write_pair(env, nv=(12, 8)):
    """Tile K_EQ: the better copy (id ...-0001, odd index -> 'unexplained' with the fake Gaia) + 2 others;
    tile K_B: the other copy (...-0001) + 1 other."""
    a, b = split_source(K_EQ, K_B, EDGE, nv=nv)
    a["id"], b["id"] = f"{K_EQ}-0001", f"{K_B}-0001"
    for k5, ms, extra in ((K_EQ, [a], 2), (K_B, [b], 1)):
        R.atomic_write_json(env.out / "tiles" / f"{k5}.json", R.compact_tile(tile_with(k5, ms, extra), k5))
    return a, b


def publish(env, **kw):
    args = dict(cache_dir=env.cache, use_gaia=True, xmatch_fn=fakes.crossmatch_gaia, rank_fn=fakes.rank, runs=[])
    args.update(kw)
    return R.publish(env.out, **args)


def test_publish_counts_a_cross_tile_duplicate_once(env):
    a, b = write_pair(env)
    s = publish(env)
    lb = json.loads((env.out / "leaderboard.json").read_text())
    assert s["movers"] == 3 + 2 - 1 and lb["n_candidates"] == 4 and len(lb["candidates"]) == 4
    assert s["movers"] == sum(t[1] for t in s["tiles"]) and s["unexplained"] == sum(t[2] for t in s["tiles"])
    assert dict((t[0], t[1]) for t in s["tiles"]) == {K_EQ: 3, K_B: 1}
    ids = [c["id"] for c in lb["candidates"]]
    assert a["id"] in ids and b["id"] not in ids
    kept = next(c for c in lb["candidates"] if c["id"] == a["id"])
    assert kept["duplicates"] == [b["id"]] and list(kept)[-1] == "duplicates"
    assert all("duplicates" not in c for c in lb["candidates"] if c["id"] != a["id"])
    assert any("also found in a neighbouring tile" in t for t in s["limits"])


def test_publish_unexplained_count_does_not_double_count(env):
    write_pair(env)                       # both copies are index 1 -> "unexplained" with the fake Gaia check
    s = publish(env)
    lb = json.loads((env.out / "leaderboard.json").read_text())
    assert s["unexplained"] == sum(c["class"] == "unexplained" for c in lb["candidates"]) == 2   # the pair + -0003
    off = publish(env, dedupe=False)
    assert off["unexplained"] == 3 and off["movers"] == 5


def test_publish_without_dedupe_keeps_both_copies(env):
    a, b = write_pair(env)
    s = publish(env, dedupe=False)
    lb = json.loads((env.out / "leaderboard.json").read_text())
    assert s["movers"] == 5 and {a["id"], b["id"]} <= {c["id"] for c in lb["candidates"]}
    assert not any("duplicates" in c for c in lb["candidates"])
    assert not any("neighbouring tile" in t for t in s["limits"])


def test_publish_keeps_the_better_track_whichever_tile_it_is_in(env):
    a, b = write_pair(env, nv=(6, 15))
    s = publish(env)
    lb = json.loads((env.out / "leaderboard.json").read_text())
    ids = {c["id"] for c in lb["candidates"]}
    assert b["id"] in ids and a["id"] not in ids
    assert dict((t[0], t[1]) for t in s["tiles"]) == {K_EQ: 2, K_B: 2}


def test_gaia_is_still_asked_about_every_mover_so_its_cache_stays_valid(env):
    a, b = write_pair(env)
    publish(env)
    asked = {i for call in fakes.XMATCH_CALLS for i in call}
    assert {a["id"], b["id"]} <= asked
    fakes.XMATCH_CALLS.clear()
    s = publish(env)
    assert fakes.XMATCH_CALLS == [] and s["gaia_unchecked"] == 0       # second publish: all from the cache


def test_publish_survives_a_broken_dedupe(env, monkeypatch):
    write_pair(env)

    def boom(*a, **k):
        raise RuntimeError("dedupe exploded")
    monkeypatch.setattr(D, "find_duplicates", boom)
    s = publish(env)
    assert s["movers"] == 5


def test_leaderboard_row_with_duplicates_keeps_the_contract_keys_first(env):
    write_pair(env)
    publish(env)
    for c in json.loads((env.out / "leaderboard.json").read_text())["candidates"]:
        keys = list(c)
        assert keys[:len(R.MOVER_KEYS) + len(R.RANK_KEYS)] == R.MOVER_KEYS + R.RANK_KEYS
        assert keys[len(R.MOVER_KEYS) + len(R.RANK_KEYS):] in ([], ["duplicates"])


def test_find_tile_duplicates_reads_tile_files_and_can_abort(env):
    a, b = write_pair(env)
    files = sorted(R.scan_tiles(env.out / "tiles").items())
    assert R.find_tile_duplicates(files) == {"drop": {b["id"]: a["id"]}, "groups": {a["id"]: [b["id"]]}}
    with pytest.raises(R.PublishAborted):
        R.find_tile_duplicates(files, should_abort=lambda: True)
