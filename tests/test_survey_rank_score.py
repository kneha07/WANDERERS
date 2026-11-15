"""Scoring, classification and ranking of survey movers (pipeline/survey/rank.py): monotonicity properties over
seeded random movers, every classify branch, rank ordering/ties/top, and readable reasons. No network."""
import copy
import math
import random
import re
import sys
import urllib.error
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
from survey import rank as R  # noqa: E402

UNEXPLAINED = {"checked": True, "match": False, "source_id": None, "sep_arcsec": None, "pm": None, "g": None}
KNOWN = {"checked": True, "match": True, "source_id": "4810594479418041856", "sep_arcsec": 0.4, "pm": 8644.0,
         "g": 8.06}
KNOWN_2P = {"checked": True, "match": True, "source_id": "123456789", "sep_arcsec": 0.8, "pm": None, "g": 20.6}
NOT_CHECKED = {"checked": False, "match": None, "source_id": None, "sep_arcsec": None, "pm": None, "g": None}


def mover(**kw):
    """A clean, faint, moderately red mover away from any tile edge (k5=None), unexplained by Gaia."""
    m = {"id": "100-0001", "k5": None, "ra": 150.0, "dec": 20.0, "epoch": 2019.4, "pmra": 900.0, "pmdec": -400.0,
         "pm": math.hypot(900.0, -400.0), "pm_err": 12.0, "pm_snr": 80.0, "chi2r": 1.4, "n_visits": 18,
         "span_yr": 9.5, "w1": 15.2, "w2": 14.1, "w1w2": 1.1, "plx": None, "plx_err": None, "track": [],
         "flags": [], "gaia": dict(UNEXPLAINED)}
    m.update(kw)
    return m


def random_movers(seed, n=40):
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        w2 = float(rng.uniform(7.0, 16.0))
        c = float(rng.uniform(-0.3, 3.5))
        pm = float(rng.uniform(150, 11000))
        ang = float(rng.uniform(0, 2 * math.pi))
        gaia = [UNEXPLAINED, KNOWN, KNOWN_2P, NOT_CHECKED][int(rng.integers(4))]
        out.append(mover(id=f"r{seed}-{i:03d}", ra=float(rng.uniform(0, 360)), dec=float(rng.uniform(-89, 89)),
                         pmra=pm * math.sin(ang), pmdec=pm * math.cos(ang), pm=pm,
                         pm_snr=float(10 ** rng.uniform(0.7, 3.5)), chi2r=float(10 ** rng.uniform(-0.3, 1.3)),
                         n_visits=int(rng.integers(6, 30)), span_yr=float(rng.uniform(2.5, 10.5)),
                         w1=w2 + c, w2=w2, w1w2=c, gaia=dict(gaia)))
    return out


SEEDS = [1, 2, 3]


def s(m):
    return R.score(m)[0]


# --------------------------------------------------------------------------------------------- score basics
def test_score_returns_float_and_reasons():
    sc, reasons = R.score(mover())
    assert isinstance(sc, float) and isinstance(reasons, list) and reasons
    assert all(isinstance(r, str) for r in reasons)


def test_score_is_sum_of_terms_rounded():
    m = mover()
    assert s(m) == round(sum(t["points"] for t in R.score_terms(m)), 3)


def test_score_deterministic_and_does_not_modify_mover():
    m = mover()
    before = copy.deepcopy(m)
    assert R.score(m) == R.score(m)
    assert m == before


KAP_2019 = R.propagate(77.95994, -45.04381, 6491.2, -5708.6, 3.2)   # Kapteyn's Star in 2019.2


def kapteyn_like(**kw):
    m = mover(k5=8545, ra=KAP_2019[0], dec=KAP_2019[1], epoch=2019.2, pm=8641.2, pmra=6490.1, pmdec=-5705.3)
    m.update(kw)
    return m


def test_every_term_is_documented_in_the_table():
    doc = R.score.__doc__
    names = {t["term"] for m in random_movers(9) + [kapteyn_like(plx=120.0, plx_err=5.0, flags=["x"], n_visits=3,
                                                                 w1=None, w1w2=None, w2=5.0)]
             for t in R.score_terms(m)}
    assert {"catalogue", "colour", "motion_snr", "speed", "visits", "span", "fit", "parallax", "brightness",
            "tile_edge", "flag", "red_flags"} <= names
    for n in names:
        assert re.search(rf"^\s+{n}\s", doc, re.M), n


def test_minimal_mover_still_scores():
    sc, reasons = R.score({"id": "x"})
    assert sc == -2.0 and reasons == ["Looks like a false detection: missing measurements",
                                      "Not yet checked against the Gaia star catalogue"]
    assert R.classify({"id": "x"}) == "likely artefact"


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), "n/a"])
def test_missing_or_bad_numbers_are_ignored(bad):
    m = mover(chi2r=bad, pm_snr=bad, w1=bad, w1w2=bad, span_yr=bad, n_visits=bad, plx=bad)
    sc, reasons = R.score(m)
    assert math.isfinite(sc)
    assert not any(re.search(r"nan|inf|None", r) for r in reasons)


@pytest.mark.parametrize("seed", SEEDS)
def test_scores_stay_within_documented_range(seed):
    for m in random_movers(seed):
        assert -16.0 <= s(m) <= 14.0


# --------------------------------------------------------------------------------------------- monotonicity
def test_unexplained_beats_not_checked_beats_known():
    sc = {k: s(mover(gaia=dict(g))) for k, g in
          [("u", UNEXPLAINED), ("n", NOT_CHECKED), ("2p", KNOWN_2P), ("k", KNOWN)]}
    assert sc["u"] > sc["n"] > sc["2p"] > sc["k"]
    assert sc["u"] - sc["k"] == pytest.approx(6.0)


@pytest.mark.parametrize("seed", SEEDS)
def test_gaia_match_always_lowers_score(seed):
    for m in random_movers(seed):
        free = dict(m, gaia=dict(UNEXPLAINED))
        assert s(dict(m, gaia=dict(KNOWN))) < s(free)
        assert s(dict(m, gaia=dict(KNOWN_2P))) < s(free)


@pytest.mark.parametrize("seed", SEEDS)
def test_more_visits_never_lowers_score(seed):
    for m in random_movers(seed, 20):
        scores = [s(dict(m, n_visits=n)) for n in range(1, 41)]
        assert all(b >= a for a, b in zip(scores, scores[1:]))


def test_more_visits_strictly_higher_from_6_to_16():
    scores = [s(mover(n_visits=n)) for n in range(6, 17)]
    assert all(b > a for a, b in zip(scores, scores[1:]))


def test_too_few_visits_costs_a_lot():
    assert s(mover(n_visits=5)) < s(mover(n_visits=6)) - 2.0


@pytest.mark.parametrize("seed", SEEDS)
def test_redder_never_lowers_score(seed):
    for m in random_movers(seed, 20):
        scores = [s(dict(m, w1w2=c, w1=m["w2"] + c)) for c in np.linspace(-0.5, 4.0, 46)]
        assert all(b >= a for a, b in zip(scores, scores[1:]))


def test_redder_strictly_higher_in_brown_dwarf_range():
    scores = [s(mover(w1w2=c, w1=14.1 + c)) for c in np.linspace(0.3, 3.1, 15)]
    assert all(b > a for a, b in zip(scores, scores[1:]))


def test_missing_w1_counts_as_red():
    assert s(mover(w1=None, w1w2=None)) > s(mover(w1=14.2, w1w2=0.1))


def test_colour_counts_half_when_saturated():
    def colour_points(m):
        return sum(t["points"] for t in R.score_terms(m) if t["term"] == "colour")
    assert colour_points(mover(w2=6.0, w1=8.0, w1w2=2.0)) == pytest.approx(0.5 * colour_points(mover(w1w2=2.0)))


@pytest.mark.parametrize("seed", SEEDS)
def test_higher_chi2r_never_raises_score(seed):
    for m in random_movers(seed, 20):
        scores = [s(dict(m, chi2r=x)) for x in np.geomspace(0.3, 300, 40)]
        assert all(b <= a for a, b in zip(scores, scores[1:]))


def test_higher_chi2r_strictly_lower_above_1_5():
    scores = [s(mover(chi2r=x)) for x in [1.6, 2.5, 4, 8, 16, 25]]
    assert all(b < a for a, b in zip(scores, scores[1:]))


@pytest.mark.parametrize("seed", SEEDS)
def test_higher_pm_snr_never_lowers_score(seed):
    for m in random_movers(seed, 20):
        scores = [s(dict(m, pm_snr=x)) for x in np.geomspace(1, 10000, 40)]
        assert all(b >= a for a, b in zip(scores, scores[1:]))


@pytest.mark.parametrize("seed", SEEDS)
def test_longer_span_never_lowers_score(seed):
    for m in random_movers(seed, 20):
        scores = [s(dict(m, span_yr=x)) for x in np.linspace(0.2, 11, 30)]
        assert all(b >= a for a, b in zip(scores, scores[1:]))


@pytest.mark.parametrize("seed", SEEDS)
def test_faster_never_lowers_score_away_from_tile_edges(seed):
    for m in random_movers(seed, 20):
        scores = []
        for pm in np.linspace(150, 12000, 30):
            scores.append(s(dict(m, pm=pm, pmra=pm * 0.6, pmdec=pm * 0.8)))
        assert all(b >= a for a, b in zip(scores, scores[1:]))


def test_brighter_than_saturation_lowers_score():
    scores = [s(mover(w2=w2, w1=w2 + 1.1)) for w2 in [9.0, 7.0, 6.5, 6.0, 5.5, 4.5]]
    assert all(b <= a for a, b in zip(scores, scores[1:]))
    assert scores[-1] < scores[0]


def test_parallax_bonus_only_when_close_and_well_measured():
    base = s(mover())
    assert s(mover(plx=150.0, plx_err=10.0)) == pytest.approx(base + 0.5)
    assert s(mover(plx=150.0, plx_err=60.0)) == pytest.approx(base)
    assert s(mover(plx=20.0, plx_err=1.0)) == pytest.approx(base)


def test_near_tile_edge_lowers_score():
    # In 2019 Kapteyn's Star is ~40" from the edge of tile 8545 and moves 8.6"/yr toward it: its 2014-2024 path
    # crosses into the next tile.
    edge = kapteyn_like()
    assert R.tile_edge_distance_arcsec(edge["ra"], edge["dec"], 8545) < 50.0
    centre = dict(edge, ra=76.5, dec=-44.99388)
    slow = dict(edge, pm=200.0, pmra=150.0, pmdec=-132.0)
    assert R.near_tile_edge(edge) and not R.near_tile_edge(centre) and not R.near_tile_edge(slow)
    assert s(edge) == pytest.approx(s(centre) - 0.5)


def test_edge_flag_from_core_counts_as_near_edge():
    assert R.near_tile_edge(mover(flags=["tile_edge"]))


def test_flags_lower_score_but_capped():
    scores = [s(mover(flags=[f"note{i}" for i in range(k)])) for k in range(6)]
    assert all(b <= a for a, b in zip(scores, scores[1:]))
    assert scores[0] - scores[5] == pytest.approx(1.5)


# --------------------------------------------------------------------------------------------- reasons
def reasons(m):
    return R.score(m)[1]


def test_reason_unexplained():
    assert "No star in Gaia's billion-star catalogue explains it" in reasons(mover())


def test_reason_very_red():
    assert "Very red (W1−W2 = 2.4): typical of a cold brown dwarf" in reasons(mover(w1w2=2.4, w1=16.5))


@pytest.mark.parametrize("c,start", [(1.3, "Red (W1−W2 = 1.3)"), (0.7, "Reddish (W1−W2 = 0.7)"),
                                     (0.1, "Ordinary colour (W1−W2 = 0.1)")])
def test_reason_colour_wording(c, start):
    assert any(r.startswith(start) for r in reasons(mover(w1w2=c, w1=14.1 + c)))


def test_reason_visits_and_span():
    assert "Measured in 21 visits over 10 years" in reasons(mover(n_visits=21, span_yr=10.0))


def test_reason_few_visits():
    assert any(r.startswith("Seen in only 4 visits") for r in reasons(mover(n_visits=4)))


def test_reason_speed():
    rs = reasons(mover(pm=8100.0, pmra=8100.0, pmdec=0.0))
    assert any(r.startswith("Moves 8.1″ a year") for r in rs)
    assert any(r == "Moves 0.45″ a year" for r in reasons(mover(pm=450.0, pmra=450.0, pmdec=0.0)))


def test_reason_known_names_the_gaia_star():
    rs = reasons(mover(gaia=dict(KNOWN)))
    assert rs[0].startswith("Already known: Gaia DR3 4810594479418041856")


def test_reason_two_parameter_gaia_source():
    assert any("did not measure its motion" in r for r in reasons(mover(gaia=dict(KNOWN_2P))))


def test_reason_not_checked():
    assert "Not yet checked against the Gaia star catalogue" in reasons(mover(gaia=dict(NOT_CHECKED)))


def test_reason_red_flags_explained():
    rs = reasons(mover(n_visits=3, chi2r=80.0))
    assert any(r.startswith("Looks like a false detection") and "too few visits" in r for r in rs)


def test_reasons_strongest_first():
    rs = reasons(mover(w1w2=0.0, w1=14.1))
    assert rs[0] == "No star in Gaia's billion-star catalogue explains it"
    assert rs[-1].startswith("Ordinary colour")


@pytest.mark.parametrize("seed", SEEDS)
def test_reasons_are_readable_sentences(seed):
    for m in random_movers(seed) + [mover(n_visits=2, chi2r=99, flags=["scan_ghost"], plx=200.0, plx_err=4.0)]:
        rs = reasons(m)
        assert rs and len(rs) == len(set(rs))
        for r in rs:
            assert 15 <= len(r) <= 160, r
            assert r[0].isupper(), r
            assert not re.search(r"\bnan\b|\bNone\b|\binf\b|chi2|pm_snr|w1w2|_", r), r
            assert not r.endswith("."), r


# --------------------------------------------------------------------------------------------- classify
def test_classify_known():
    assert R.classify(mover(gaia=dict(KNOWN))) == "known (Gaia)"
    assert R.classify(mover(gaia=dict(KNOWN_2P))) == "known (Gaia)"


def test_classify_known_wins_over_red_flags():
    assert R.classify(mover(gaia=dict(KNOWN), chi2r=200.0, n_visits=4)) == "known (Gaia)"


@pytest.mark.parametrize("kw", [dict(chi2r=45.0), dict(n_visits=5), dict(pm_snr=2.0), dict(span_yr=0.6),
                                dict(pm=20000.0, pmra=20000.0, pmdec=0.0), dict(flags=["latent"]),
                                dict(flags=["diffraction spike"]), dict(ra=None),
                                dict(w1=5.2, w2=5.0, w1w2=0.2, chi2r=8.0),
                                dict(w1=5.2, w2=5.0, w1w2=0.2, pm_snr=7.0)])
def test_classify_likely_artefact(kw):
    assert R.classify(mover(**kw)) == "likely artefact"


def test_very_bright_with_clean_motion_is_not_an_artefact():
    assert R.classify(mover(w1=5.2, w2=5.0, w1w2=0.2, chi2r=1.2, pm_snr=500.0)) == "unexplained"


def test_harmless_flag_is_not_an_artefact():
    assert R.classify(mover(flags=["tile_edge"])) == "unexplained"


def test_classify_not_checked():
    assert R.classify(mover(gaia=dict(NOT_CHECKED))) == "not checked"
    no_gaia = mover()
    del no_gaia["gaia"]
    assert R.classify(no_gaia) == "not checked"


def test_artefact_wins_over_not_checked():
    assert R.classify(mover(gaia=dict(NOT_CHECKED), n_visits=4)) == "likely artefact"


def test_classify_unexplained():
    assert R.classify(mover()) == "unexplained"


@pytest.mark.parametrize("seed", SEEDS)
def test_classify_always_one_of_four(seed):
    for m in random_movers(seed):
        assert R.classify(m) in R.CLASSES


def test_artefacts_score_below_their_clean_twins():
    assert s(mover(chi2r=45.0)) < s(mover(chi2r=25.0)) - 2.0


# --------------------------------------------------------------------------------------------- rank
def test_rank_sorted_by_score_desc_with_rank_numbers():
    rows = R.rank(random_movers(1))
    scores = [r["score"] for r in rows]
    assert scores == sorted(scores, reverse=True)
    assert [r["rank"] for r in rows] == list(range(1, len(rows) + 1))


def test_rank_adds_fields_and_default_gaia():
    m = mover()
    del m["gaia"]
    (row,) = R.rank([m])
    assert row["class"] == "not checked" and row["gaia"]["checked"] is False
    assert {"score", "reasons", "class", "rank"} <= set(row)


def test_rank_keeps_existing_fields():
    (row,) = R.rank([mover(track=[[2014.1, 150.0, 20.0]])])
    assert row["track"] == [[2014.1, 150.0, 20.0]] and row["id"] == "100-0001"


def test_rank_top_truncates():
    rows = R.rank(random_movers(2), top=5)
    assert len(rows) == 5 and rows[-1]["rank"] == 5
    assert rows == R.rank(random_movers(2))[:5]


@pytest.mark.parametrize("top,n", [(1000, 40), (None, 40), (0, 0), (-3, 0), (40, 40), (41, 40)])
def test_rank_top_edge_cases(top, n):
    assert len(R.rank(random_movers(3), top=top)) == n


def test_rank_ties_broken_by_pm_snr_then_id():
    # pm_snr earns at most 2.5 points (reached at 316), so these three have the same score
    b, a, c = mover(id="b", pm_snr=500.0), mover(id="a", pm_snr=500.0), mover(id="c", pm_snr=400.0)
    z = mover(id="0", pm_snr=350.0)
    assert s(a) == s(b) == s(c) == s(z)
    assert [r["id"] for r in R.rank([c, z, b, a])] == ["a", "b", "c", "0"]


def test_rank_order_independent_of_input_order():
    movers = random_movers(4) + [mover(id=f"dup{i}") for i in range(5)]
    first = [r["id"] for r in R.rank(movers)]
    for k in range(3):
        shuffled = movers[:]
        random.Random(k).shuffle(shuffled)
        assert [r["id"] for r in R.rank(shuffled)] == first


def test_rank_does_not_modify_input():
    movers = random_movers(5, 10)
    before = copy.deepcopy(movers)
    R.rank(movers)
    assert movers == before


def test_rank_empty():
    assert R.rank([]) == [] and R.rank(None) == []


def test_rank_handles_missing_pm_snr_in_ties():
    a, b = mover(id="a", pm_snr=None), mover(id="b", pm_snr=None)
    assert [r["id"] for r in R.rank([b, a])] == ["a", "b"]


# --------------------------------------------------------------------------------------------- end to end
def test_crossmatch_then_rank_puts_the_cold_unknown_mover_first(monkeypatch, tmp_path):
    kapteyn = {"source_id": 4810594479418041856, "ra": 77.95994, "dec": -45.04381, "pmra": 6491.2,
               "pmdec": -5708.6, "parallax": 254.2, "phot_g_mean_mag": 8.06, "ref_epoch": 2016.0}

    def fake(tap_url, adql, timeout):
        return {"metadata": [{"name": c} for c in R.GAIA_COLUMNS],
                "data": [[kapteyn[c] for c in R.GAIA_COLUMNS]] if "77.9" in adql else []}
    monkeypatch.setattr(R, "_tap_query", fake)
    ra, dec = R.propagate(77.95994, -45.04381, 6491.2, -5708.6, 3.2)
    known = mover(id="8545-0003", k5=8545, ra=ra, dec=dec, epoch=2019.2, pmra=6490.1, pmdec=-5705.3, pm=8641.2,
                  pm_err=4.1, pm_snr=2100.0, chi2r=1.3, n_visits=21, span_yr=10.0, w1=6.1, w2=5.8, w1w2=0.3)
    cold = mover(id="10226-0001", k5=10226, ra=133.7864, dec=-7.2439, epoch=2017.0, pmra=-8123.0, pmdec=673.0,
                 pm=8151.0, pm_err=25.0, pm_snr=320.0, chi2r=3.0, n_visits=20, span_yr=10.0, w1=None, w2=14.0,
                 w1w2=None)
    junk = mover(id="300-0001", k5=300, ra=10.0, dec=10.0, n_visits=4, chi2r=60.0, w1w2=0.0, w1=12.0, w2=12.0)
    for m in (known, cold, junk):
        del m["gaia"]
    rows = R.rank(R.crossmatch_gaia([junk, known, cold], tmp_path))
    assert [r["id"] for r in rows] == ["10226-0001", "8545-0003", "300-0001"]
    assert [r["class"] for r in rows] == ["unexplained", "known (Gaia)", "likely artefact"]
    assert rows[1]["gaia"]["source_id"] == "4810594479418041856"


def test_crossmatch_failure_then_rank_marks_not_checked(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "RETRY_SLEEP_S", 0.0)

    def down(*a):
        raise urllib.error.URLError("down")
    monkeypatch.setattr(R, "_tap_query", down)
    m = mover()
    del m["gaia"]
    (row,) = R.rank(R.crossmatch_gaia([m], tmp_path))
    assert row["class"] == "not checked" and "Not yet checked against the Gaia star catalogue" in row["reasons"]
