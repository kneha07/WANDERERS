"""Validation harness, part 2: matching, completeness / accuracy / false-positive bookkeeping, known movers,
validation.json and the CLI. Uses fake mover searches and the naive reference search in
tests/_survey_reference.py (a stand-in until survey.link exists). No network."""
import json
import math
import sys
import unittest
from pathlib import Path

try:
    import pyarrow  # noqa: F401
    import pytest
except ImportError as e:  # e.g. `python -m unittest discover` without the survey's dependencies
    raise unittest.SkipTest(f"survey validation tests need pyarrow and pytest ({e})")
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "tests"))
from survey import validate as V  # noqa: E402
import _survey_reference as REF  # noqa: E402

REF_SPEC = str(ROOT / "tests" / "_survey_reference.py") + ":process_tile"
SMALL = dict(pms=(1.0, 4.0), w2s=(11.0, 14.5), trials=2, n_empty=2, density=0.02, empty_radius_deg=0.1)


def truth(ra=10.0, dec=20.0, pmra=3000.0, pmdec=-4000.0, epoch=2019.0, **kw):
    return V.normalize_spec(dict(ra=ra, dec=dec, pmra=pmra, pmdec=pmdec, epoch=epoch, w2=12.0, **kw))


def mover_at(t, epoch=2020.0, dra=0.0, ddec=0.0, scale=1.0, **kw):
    ra, dec = V.propagate(t["ra"], t["dec"], t["epoch"], t["pmra"], t["pmdec"], epoch)
    ra, dec = V.offset_radec(ra, dec, dra, ddec)
    m = {"ra": float(ra), "dec": float(dec), "epoch": epoch, "pmra": t["pmra"] * scale, "pmdec": t["pmdec"] * scale,
         "pm": t["pm"] * scale, "pm_err": 10.0}
    m.update(kw)
    return m


# ------------------------------------------------------------------ fake searches
class Capture:
    """Wraps validate.inject so a fake search can see what was injected (an oracle)."""

    def __init__(self, monkeypatch):
        self.specs = []
        real = V.inject

        def spy(table, specs, rng, **kw):
            rep = kw.setdefault("report", [])
            out = real(table, specs, rng, **kw)
            self.specs = [r["spec"] for r in rep]
            return out

        monkeypatch.setattr(V, "inject", spy)


def oracle(capture, scale=1.0, extra=0, skip_below=None, calls=None):
    def process_tile(k5, reader=None, years=None, **kw):
        if calls is not None:
            calls.append((k5, list(years or [])))
        movers = [mover_at(s, scale=scale) for s in capture.specs
                  if skip_below is None or s["pm"] >= skip_below]
        ra, dec = V.tile_center(k5)
        for i in range(extra):
            far = V.offset_radec(ra, dec, 3000.0 + 100 * i, 3000.0)
            movers.append({"ra": float(far[0]), "dec": float(far[1]), "epoch": 2019.0, "pmra": 500.0,
                           "pmdec": 0.0, "pm": 500.0})
        capture.specs = []  # an empty sky must not see the previous injections
        return {"k5": k5, "movers": movers}
    return process_tile


def null_search(k5, reader=None, years=None, **kw):
    return {"k5": k5, "movers": []}


# ------------------------------------------------------------------ matching maths
def test_match_exact():
    t = truth()
    match, dup, spur = V.match_movers([t], [mover_at(t)])
    assert match == [0] and dup == [] and spur == []


def test_match_rejects_position_outside_radius():
    t = truth()
    assert V.match_movers([t], [mover_at(t, dra=6.0)])[0] == [None]
    assert V.match_movers([t], [mover_at(t, dra=4.0)])[0] == [0]


def test_match_rejects_wrong_motion():
    t = truth()  # pm 5000 mas/yr: tolerance 30 % = 1500 mas/yr
    assert V.match_movers([t], [mover_at(t, scale=1.25)])[0] == [0]
    assert V.match_movers([t], [mover_at(t, scale=1.35)])[0] == [None]


def test_match_slow_mover_uses_absolute_tolerance():
    t = truth(pmra=200.0, pmdec=0.0)
    m = mover_at(t)
    m["pmra"] = 290.0  # 90 mas/yr off: more than 30 % of 200 but within 100 mas/yr
    assert V.match_movers([t], [m])[0] == [0]


def test_match_is_one_to_one_and_counts_duplicates_and_spurious():
    t1, t2 = truth(), truth(ra=10.5)
    far = mover_at(truth(ra=11.0))
    movers = [mover_at(t1, dra=2.0), mover_at(t1), mover_at(t2), far]
    match, dup, spur = V.match_movers([t1, t2], movers)
    assert match == [1, 2]
    assert dup == [0] and spur == [3]


def test_match_follows_the_motion_to_the_reported_epoch():
    t = truth(pmra=10000.0, pmdec=0.0, epoch=2015.0)
    m = mover_at(t, epoch=2024.0)  # 90" from the 2015 position
    assert V.match_movers([t], [m])[0] == [0]


def test_match_skips_malformed_movers():
    t = truth()
    match, dup, spur = V.match_movers([t], [{"ra": None}, mover_at(t)])
    assert match == [1] and spur == [0]


def test_angle_diff():
    assert V.angle_diff_deg(359.0, 1.0) == pytest.approx(2.0)
    assert V.angle_diff_deg(10.0, 190.0) == pytest.approx(180.0)
    assert V.angle_diff_deg(-5.0, 5.0) == pytest.approx(10.0)


def test_motion_errors():
    t = truth(pmra=0.0, pmdec=1000.0)
    m = {"pmra": 1000 * math.sin(math.radians(3)) * 1.02, "pmdec": 1000 * math.cos(math.radians(3)) * 1.02,
         "pm": 1020.0, "pm_err": 10.0}
    e = V.motion_errors(t, m)
    assert e["frac_error"] == pytest.approx(0.02)
    assert e["pa_error_deg"] == pytest.approx(3.0)
    assert e["pull"] == pytest.approx(2.0)
    assert e["vec_error"] == pytest.approx(math.hypot(m["pmra"], m["pmdec"] - 1000))
    assert V.motion_errors(t, dict(m, pm_err=None))["pull"] is None


# ------------------------------------------------------------------ bookkeeping
def rec(pm, w2, ok, colour=0.0, frac=0.0, pa=0.0, pull=None, det=True):
    r = {"pm_arcsec_yr": pm, "w2": w2, "w1w2": colour, "recovered": ok, "detectable": det}
    if ok:
        r.update(frac_error=frac, pa_error_deg=pa, vec_error=frac * pm * 1000, pull=pull)
    return r


def test_completeness_counts_and_rounding():
    rs = [rec(1.0, 11.0, True), rec(1.0, 11.0, False), rec(1.0, 11.0, True), rec(4.0, 11.0, False, det=False)]
    rows = V.completeness_table(rs, pms=(1.0, 4.0), w2s=(11.0, 14.5), colours=(0.0,))
    assert len(rows) == 4
    r = rows[0]
    assert (r["pm_arcsec_yr"], r["w2"], r["recovered"], r["trials"], r["fraction"], r["detectable"]) == \
        (1.0, 11.0, 2, 3, 0.667, 3)
    empty = rows[1]
    assert empty["trials"] == 0 and empty["fraction"] is None
    assert rows[2]["fraction"] == 0.0 and rows[2]["detectable"] == 0


def test_completeness_separates_colours():
    rs = [rec(1.0, 11.0, True, colour=0.0), rec(1.0, 11.0, False, colour=2.0)]
    rows = V.completeness_table(rs, pms=(1.0,), w2s=(11.0,), colours=(0.0, 2.0))
    assert [(r["w1w2"], r["fraction"]) for r in rows] == [(0.0, 1.0), (2.0, 0.0)]


def test_pm_accuracy_maths():
    rs = [rec(1.0, 11.0, True, frac=0.01, pa=1.0, pull=0.5), rec(1.0, 13.0, True, frac=0.03, pa=3.0, pull=-1.0),
          rec(4.0, 11.0, True, frac=0.02, pa=2.0, pull=2.0), rec(4.0, 13.0, False)]
    a = V.pm_accuracy(rs)
    assert a["n"] == 3
    assert a["median_frac_error"] == pytest.approx(0.02)
    assert a["median_pa_error_deg"] == pytest.approx(2.0)
    assert a["median_abs_pull"] == pytest.approx(1.0)
    assert a["p90_frac_error"] == pytest.approx(0.028)
    by_pm = {r["pm_arcsec_yr"]: r for r in a["by_pm"]}
    assert by_pm[1.0]["n"] == 2 and by_pm[1.0]["median_frac_error"] == pytest.approx(0.02)
    assert by_pm[4.0]["n"] == 1
    assert {r["w2"]: r["n"] for r in a["by_w2"]} == {11.0: 2, 13.0: 1}


def test_pm_accuracy_with_nothing_recovered():
    a = V.pm_accuracy([rec(1.0, 11.0, False)])
    assert a["n"] == 0 and a["median_frac_error"] is None and a["median_abs_pull"] is None


def test_poisson_upper_limits():
    assert V.poisson_upper(0) == pytest.approx(2.996, abs=1e-3)
    assert V.poisson_upper(1) == pytest.approx(4.744, abs=1e-3)


def test_false_positive_summary_scales_to_a_tile():
    fp = V.false_positive_summary([0, 2, 1], [0.5, 0.5, 0.5])
    assert fp["tiles"] == 3 and fp["movers"] == 3 and fp["per_sky"] == 1.0
    assert fp["per_deg2"] == pytest.approx(2.0)
    assert fp["per_tile"] == pytest.approx(2.0 * V.TILE_AREA_DEG2, abs=1e-3)
    assert fp["upper95_per_tile"] > fp["per_tile"]
    zero = V.false_positive_summary([0, 0], [V.TILE_AREA_DEG2, V.TILE_AREA_DEG2])
    assert zero["per_tile"] == 0.0 and zero["upper95_per_tile"] == pytest.approx(1.498, abs=1e-3)


def test_grid_specs_layout():
    rng = np.random.default_rng(0)
    cells = [(pm, w2, 0.0) for pm in V.PM_GRID_ARCSEC for w2 in V.W2_GRID]
    specs, radius = V.grid_specs(rng, (100.0, 50.0), cells, 2019.0, spacing_arcmin=4.0, vtan_kms=80.0)
    assert len(specs) == 35
    ra, dec = np.array([s["ra"] for s in specs]), np.array([s["dec"] for s in specs])
    sep = V.sep_arcsec(100.0, 50.0, ra, dec)
    assert sep.max() < radius * 3600 - 60  # every mover's whole track stays inside the sky
    d = V.sep_arcsec(ra[:, None], dec[:, None], ra[None, :], dec[None, :]) + np.eye(35) * 1e9
    assert d.min() > 0.75 * 4 * 60
    s = specs[0]
    assert s["plx"] == pytest.approx(4.74047 * s["pm"] / 80.0, rel=1e-4)
    assert sorted({(s["pm_arcsec_yr"], s["w2"]) for s in specs}) == sorted({(c[0], c[1]) for c in cells})


# ------------------------------------------------------------------ recovery() with fake searches
def test_recovery_with_a_blind_search_finds_nothing():
    r = V.recovery(null_search, **SMALL)
    assert all(row["recovered"] == 0 and row["trials"] == 2 for row in r["completeness"])
    assert len(r["records"]) == 2 * 4
    assert r["false_positives"]["movers"] == 0 and r["false_positives"]["tiles"] == 2
    assert r["pm_accuracy"]["n"] == 0


def test_recovery_with_an_oracle_is_complete_and_exact(monkeypatch):
    cap = Capture(monkeypatch)
    calls = []
    r = V.recovery(oracle(cap, calls=calls), **SMALL)
    assert all(row["fraction"] == 1.0 for row in r["completeness"])
    assert r["pm_accuracy"]["median_frac_error"] == pytest.approx(0.0, abs=1e-9)
    assert r["pm_accuracy"]["median_pa_error_deg"] == pytest.approx(0.0, abs=1e-6)
    assert r["false_positives"]["movers"] == 0 and r["spurious_in_injected"]["movers"] == 0
    # the search is called once per sky with the contract's year labels
    assert len(calls) == 2 + 2 and all(y == V.YEAR_LABELS for _, y in calls)


def test_recovery_measures_a_known_bias(monkeypatch):
    cap = Capture(monkeypatch)
    r = V.recovery(oracle(cap, scale=1.02), **SMALL)
    assert r["pm_accuracy"]["median_frac_error"] == pytest.approx(0.02, abs=1e-6)
    assert r["pm_accuracy"]["median_pa_error_deg"] == pytest.approx(0.0, abs=1e-6)
    assert r["pm_accuracy"]["median_abs_pull"] == pytest.approx(np.median([0.02 * pm * 1000 / 10 for pm in (1, 4)]), rel=0.5)


def test_recovery_partial_search_gives_exact_fractions(monkeypatch):
    cap = Capture(monkeypatch)
    r = V.recovery(oracle(cap, skip_below=2000.0), **SMALL)
    frac = {(row["pm_arcsec_yr"], row["w2"]): row["fraction"] for row in r["completeness"]}
    assert frac == {(1.0, 11.0): 0.0, (1.0, 14.5): 0.0, (4.0, 11.0): 1.0, (4.0, 14.5): 1.0}


def test_recovery_counts_false_positives(monkeypatch):
    cap = Capture(monkeypatch)
    r = V.recovery(oracle(cap, extra=2), **SMALL)
    fp = r["false_positives"]
    assert fp["movers"] == 4 and fp["per_sky"] == 2.0
    assert fp["per_tile"] == pytest.approx(2.0 * V.TILE_AREA_DEG2 / V.cap_area_deg2(0.1), rel=1e-3)
    assert r["spurious_in_injected"]["movers"] == 4
    assert all(row["fraction"] == 1.0 for row in r["completeness"])


def test_recovery_is_deterministic():
    a = V.recovery(null_search, **SMALL)
    b = V.recovery(null_search, **SMALL)
    assert a["records"] == b["records"]


def test_recovery_runs_one_sky_per_colour(monkeypatch):
    cap = Capture(monkeypatch)
    calls = []
    r = V.recovery(oracle(cap, calls=calls), **dict(SMALL, colours=(0.0, 2.0), n_empty=0))
    assert len(calls) == 2 * 2
    assert {row["w1w2"] for row in r["completeness"]} == {0.0, 2.0}
    assert all(row["trials"] == 2 for row in r["completeness"])


def test_recovery_hands_the_core_the_tile_it_reads():
    seen = []

    def search(k5, reader=None, years=None, **kw):
        t = [reader(k5, y) for y in years]
        rows = sum(x.num_rows for x in t if x is not None)
        other = [reader(k5 + 1, y) for y in years]
        seen.append((k5, rows, all(o is None for o in other)))
        return {"movers": []}

    V.recovery(search, **dict(SMALL, n_empty=1))
    assert all(rows > 0 and isolated for _, rows, isolated in seen)


def test_recovery_accepts_explicit_positions(monkeypatch):
    cap = Capture(monkeypatch)
    seen = []
    base = oracle(cap)

    def search(k5, reader=None, years=None, **kw):
        seen.append((k5, [(s["ra"], s["dec"]) for s in cap.specs]))
        return base(k5, reader=reader, years=years)

    r = V.recovery(search, **dict(SMALL, n_empty=0, centers=[(0.0, 10.0), (30.0, 89.9)]))
    assert all(row["fraction"] == 1.0 for row in r["completeness"])
    (k1, pos1), (k2, pos2) = seen
    assert k1 == V.tile_of(0.0, 10.0) and k2 == V.tile_of(30.0, 89.9)
    ras = [p[0] for p in pos1]
    assert min(ras) < 1.0 and max(ras) > 359.0          # the first sky straddles RA = 0
    assert all(V.sep_arcsec(30.0, 89.9, p[0], p[1]) < 0.3 * 3600 for p in pos2)


@pytest.mark.parametrize("k5", [0, 100, 3000, 4095, 4096, 6000, 8191, 8192, 12287])
def test_sky_of_0p6_deg_stays_inside_its_tile(k5):
    k, (ra, dec) = V.sky_center(k5)
    pra, pdec = V.destination(ra, dec, 0.6, np.linspace(0, 360, 90, endpoint=False))
    assert k == k5 and all(V.tile_of(a, d) == k5 for a, d in zip(pra, pdec))


# ------------------------------------------------------------------ recovery() with the naive reference search
@pytest.fixture(scope="module")
def ref_recovery():
    return V.recovery(REF.process_tile, pms=(1.0, 4.0, 11.0), w2s=(11.0, 13.0), trials=2, n_empty=2, density=0.1,
                      empty_radius_deg=0.15)


def test_reference_search_recovers_bright_fast_movers(ref_recovery):
    rows = ref_recovery["completeness"]
    n = sum(r["trials"] for r in rows)
    k = sum(r["recovered"] for r in rows)
    assert n == 12 and k >= 11
    assert all(r["detectable"] == r["trials"] for r in rows)


def test_reference_search_measures_motion_well(ref_recovery):
    acc = ref_recovery["pm_accuracy"]
    assert acc["median_frac_error"] < 0.01
    assert acc["median_pa_error_deg"] < 1.0


def test_reference_search_false_positive_rate_is_reported(ref_recovery):
    fp = ref_recovery["false_positives"]
    assert fp["tiles"] == 2 and fp["per_tile"] is not None and fp["upper95_per_tile"] > 0


# ------------------------------------------------------------------ known movers
KAPTEYN = next(s for s in V.KNOWN_STARS if s["name"] == "Kapteyn's Star")
WISE0855 = next(s for s in V.KNOWN_STARS if s["name"].startswith("WISE 0855"))


def star_mover(star, epoch=2019.5, scale=1.0, dra=0.0, **kw):
    t = V.normalize_spec(dict(star, w2=10.0))
    return dict(mover_at(t, epoch=epoch, scale=scale, dra=dra), **kw)


def test_known_movers_recovers_a_star_from_tile_results():
    res = [{"k5": 8545, "movers": [star_mover(KAPTEYN, scale=1.003, id="8545-0001", n_visits=21)]}]
    out = V.known_movers(res, [KAPTEYN])
    row = out["known"][0]
    assert out["n_recovered"] == 1 and out["fraction"] == 1.0
    assert row["recovered"] and row["mover_id"] == "8545-0001"
    assert row["error_pct"] == pytest.approx(0.3, abs=1e-3)
    assert row["pm_true"] == pytest.approx(8644.3, abs=0.1)
    assert row["sep_arcsec"] < 0.01


def test_known_movers_reports_a_missing_star():
    out = V.known_movers([{"movers": []}], [KAPTEYN, WISE0855])
    assert out["n_recovered"] == 0 and out["n_known"] == 2
    assert all(r["pm_found"] is None and not r["recovered"] for r in out["known"])


def test_known_movers_wrong_motion_is_not_recovered():
    out = V.known_movers([star_mover(KAPTEYN, scale=0.5)], [KAPTEYN])
    row = out["known"][0]
    assert not row["recovered"] and row["pm_found"] == pytest.approx(4322.2, abs=0.2)
    assert row["error_pct"] == pytest.approx(50.0, abs=0.01)


def test_known_movers_uses_the_nearest_and_the_movers_epoch():
    near = star_mover(WISE0855, epoch=2023.0, id="near")
    off = star_mover(WISE0855, epoch=2023.0, dra=6.0, id="off")
    out = V.known_movers([off, near], [WISE0855])  # 2023 is ~100" from the 2010.5 catalogue position
    assert out["known"][0]["mover_id"] == "near"


def test_known_movers_ignores_movers_out_of_radius():
    out = V.known_movers([star_mover(KAPTEYN, dra=12.0)], [KAPTEYN])
    assert out["known"][0]["pm_found"] is None


def test_known_star_list_is_the_validation_targets():
    names = {s["name"] for s in V.KNOWN_STARS}
    assert {"Barnard's Star", "Kapteyn's Star", "WISE 0855-0714", "Proxima Centauri", "Wolf 359"} <= names
    for s in V.KNOWN_STARS:
        assert math.hypot(s["pmra"], s["pmdec"]) > 1000


def test_reference_search_finds_kapteyn_and_wise0855_in_real_data():
    rows, fields, not_run = V.run_real(REF.process_tile, tiles_dir=ROOT / "no-such-dir")
    by = {r["name"]: r for r in rows}
    assert by["Kapteyn's Star"]["recovered"] and by["Kapteyn's Star"]["error_pct"] < 1.0
    assert by["WISE 0855-0714"]["recovered"] and by["WISE 0855-0714"]["error_pct"] < 1.0
    assert {f["name"] for f in fields} == {"Kapteyn's Star", "WISE 0855-0714"}
    assert all(f["target_tracks"] >= 1 for f in fields)
    assert "Barnard's Star" in not_run


def test_run_real_reads_finished_survey_tiles(tmp_path):
    k5 = V.tile_of(KAPTEYN["ra"], KAPTEYN["dec"])
    (tmp_path / f"{k5}.json").write_text(json.dumps({"k5": k5, "movers": [star_mover(KAPTEYN, id="t")]}))
    rows, _, not_run = V.run_real(null_search, tiles_dir=tmp_path, fixtures_dir=tmp_path)
    assert [r["data"] for r in rows] == [f"survey tile {k5}"]
    assert rows[0]["recovered"]
    assert "Kapteyn's Star" not in not_run and "WISE 0855-0714" in not_run


# ------------------------------------------------------------------ validation.json
@pytest.fixture(scope="module")
def doc():
    rec_ = V.recovery(null_search, **SMALL)
    known = V.known_movers([star_mover(KAPTEYN)], [KAPTEYN, WISE0855])["known"]
    return V.build_document(rec_, known, [{"name": "x", "movers": 1}], ["Barnard's Star"], core_name="fake",
                            runtime_s=1.234)


def test_document_has_the_contract_keys(doc):
    for k in ("generated", "completeness", "pm_accuracy", "false_positives", "known", "summary", "method", "limits"):
        assert k in doc, k
    assert {"tiles", "movers", "per_tile"} <= set(doc["false_positives"])
    for row in doc["completeness"]:
        assert {"pm_arcsec_yr", "w2", "recovered", "trials", "fraction"} <= set(row)
        assert isinstance(row["recovered"], int) and isinstance(row["trials"], int)
    for row in doc["known"]:
        assert {"name", "pm_true", "pm_found", "recovered", "error_pct"} <= set(row)
    assert isinstance(doc["summary"], str) and doc["summary"].endswith(".")
    assert isinstance(doc["limits"], list) and all(isinstance(x, str) for x in doc["limits"])
    assert doc["generated"].endswith("+00:00")


def test_document_has_both_the_contract_and_the_web_page_shapes(monkeypatch):
    cap = Capture(monkeypatch)
    rec_ = V.recovery(oracle(cap, scale=1.02, skip_below=2000.0, extra=1), **SMALL)
    known = V.known_movers([star_mover(KAPTEYN, n_visits=21)], [KAPTEYN, WISE0855])["known"]
    d = json.loads(json.dumps(V.build_document(rec_, known), allow_nan=False))
    # contract shape
    for k in ("completeness", "pm_accuracy", "summary", "method", "limits"):
        assert k in d
    assert {"tiles", "movers", "per_tile"} <= set(d["false_positives"])
    for row in d["known"]:
        assert {"name", "pm_true", "pm_found", "recovered", "error_pct"} <= set(row)
    # web-page shape (summary.validation)
    inj = d["injection"]
    assert {"n_injected", "n_recovered", "by_pm", "by_mag", "pm_error_median", "pm_rel_error_median"} <= set(inj)
    assert inj["n_injected"] == 8 and inj["n_recovered"] == 4
    for b in inj["by_pm"] + inj["by_mag"]:
        assert set(b) == {"lo", "hi", "n", "recovered", "completeness"} and b["lo"] < b["hi"]
    assert [(b["lo"], b["n"], b["completeness"]) for b in inj["by_pm"]] == [(1000.0, 4, 0.0), (4000.0, 4, 1.0)]
    assert [(b["lo"], b["hi"], b["n"]) for b in inj["by_mag"]] == [(10.0, 12.0, 4), (14.0, 15.0, 4)]
    assert inj["pm_rel_error_median"] == pytest.approx(0.02)
    assert inj["pm_error_median"] == pytest.approx(80.0)  # 2 % of 4000 mas/yr
    fp = d["false_positives"]
    assert {"n", "tiles", "note"} <= set(fp) and fp["n"] == fp["movers"] == 2 and fp["tiles"] == 2
    assert "per tile" in fp["note"]
    k = {r["name"]: r for r in d["known"]}
    for r in d["known"]:
        assert {"name", "recovered", "pm_true", "pm_measured", "note"} <= set(r)
    assert k["Kapteyn's Star"]["pm_measured"] == k["Kapteyn's Star"]["pm_found"] == pytest.approx(8644.3, abs=0.1)
    assert "21 visits" in k["Kapteyn's Star"]["note"]
    assert k["WISE 0855-0714"]["pm_measured"] is None and "No mover" in k["WISE 0855-0714"]["note"]


def test_injection_bins_cover_the_default_grid():
    rs = [rec(pm, w2, True, frac=0.0) | {"pm_true": pm * 1000, "pm_found": pm * 1000}
          for pm in V.PM_GRID_ARCSEC for w2 in V.W2_GRID]
    inj = V.page_injection(rs)
    assert sum(b["n"] for b in inj["by_pm"]) == sum(b["n"] for b in inj["by_mag"]) == len(rs)
    assert [b["n"] for b in inj["by_pm"]] == [5, 5, 5, 5, 5, 10]  # 8 and 11"/yr share the top bin
    assert [b["n"] for b in inj["by_mag"]] == [7] * 5
    assert inj["pm_error_median"] == 0.0


def test_document_is_strict_json(doc):
    text = json.dumps(doc, allow_nan=False)
    assert json.loads(text) == doc


def test_sanitize():
    out = V.sanitize({"a": np.float64("nan"), "b": np.int64(3), "c": [np.bool_(True), float("inf")],
                      "d": np.array([1.5, 2.5]), 4: (1, 2)})
    assert out == {"a": None, "b": 3, "c": [True, None], "d": [1.5, 2.5], "4": [1, 2]}


def test_summary_sentence_uses_the_numbers():
    rows = [{"pm_arcsec_yr": pm, "w2": w2, "w1w2": 0.0, "recovered": rec_, "trials": 10, "fraction": rec_ / 10}
            for pm, w2, rec_ in [(1.0, 11.0, 10), (4.0, 13.0, 9), (1.0, 14.5, 5), (1.0, 15.5, 1), (0.2, 11.0, 3)]]
    r = {"completeness": rows, "pm_accuracy": {"median_frac_error": 0.004},
         "false_positives": {"per_tile": 0.25}}
    s = V.make_summary(r, [{"name": "Kapteyn's Star", "recovered": True}, {"name": "X", "recovered": False}])
    assert "95%" in s and "50% at W2 = 14.5" in s and "10% at W2 = 15.5" in s and "30%" in s
    assert "0.4%" in s and "0.25 false movers" in s and "1 of 2" in s and "Kapteyn's Star" in s


def test_summary_reports_red_colours_and_counts_each_star_once():
    rows = [{"pm_arcsec_yr": 1.0, "w2": w2, "w1w2": c, "recovered": k, "trials": 4, "fraction": k / 4}
            for c, w2, k in [(0.0, 11.0, 4), (2.0, 11.0, 4), (2.0, 14.5, 2), (2.0, 15.5, 0)]]
    r = {"completeness": rows, "pm_accuracy": {}, "false_positives": {}}
    known = [{"name": "Kapteyn's Star", "recovered": True}, {"name": "Kapteyn's Star", "recovered": False}]
    s = V.make_summary(r, known)
    assert "with W1−W2 = 0" in s
    assert "W1−W2 = 2" in s and "found 75% at W2 ≤ 14.5 and 0% at W2 = 15.5" in s
    assert "1 of 1 known" in s


def test_write_validation(tmp_path, doc):
    p = V.write_validation(tmp_path / "a" / "validation.json", doc)
    assert json.loads(p.read_text(encoding="utf-8"))["summary"] == doc["summary"]


# ------------------------------------------------------------------ CLI
def test_parse_args_defaults():
    a = V.parse_args([])
    assert a.trials == 5 and a.empty == 24 and not a.real and a.colours == (0.0, 2.0)
    assert a.core == "survey.link:process_tile" and a.out.endswith("validation.json")
    q = V.parse_args(["--quick", "--trials", "2", "--colours", "0", "--real"])
    assert q.empty == 1 and q.trials == 2 and q.colours == (0.0,) and q.real


@pytest.mark.parametrize("bad", [["--trials", "0"], ["--colours", "red"], ["--empty", "-1"]])
def test_parse_args_rejects_bad_values(bad):
    with pytest.raises(SystemExit):
        V.parse_args(bad)


def test_load_core_by_module_and_by_file():
    assert V.load_core("_survey_reference:process_tile") is REF.process_tile
    assert callable(V.load_core(REF_SPEC))
    with pytest.raises(ImportError):
        V.load_core("_survey_reference:nope")
    with pytest.raises(ImportError):
        V.load_core("no_such_module_xyz:process_tile")


def test_cli_without_a_core_fails_cleanly(tmp_path, capsys):
    out = tmp_path / "v.json"
    assert V.main(["--out", str(out), "--core", "no_such_module_xyz:process_tile"]) == 2
    assert not out.exists()
    assert "not available" in capsys.readouterr().err


def test_cli_quick_run_writes_validation_json(tmp_path):
    out = tmp_path / "survey" / "validation.json"
    assert V.main(["--out", str(out), "--quick", "--trials", "1", "--colours", "0", "--core", REF_SPEC]) == 0
    d = json.loads(out.read_text(encoding="utf-8"))
    assert len(d["completeness"]) == 3 * 2
    assert d["false_positives"]["tiles"] == 1 and d["known"] == []
    assert d["core"] == REF_SPEC and d["grid"]["trials"] == 1


def test_cli_real_adds_known_movers(tmp_path):
    out = tmp_path / "validation.json"
    rc = V.main(["--out", str(out), "--quick", "--trials", "1", "--empty", "0", "--colours", "0", "--real",
                 "--core", REF_SPEC, "--tiles-dir", str(tmp_path)])
    assert rc == 0
    d = json.loads(out.read_text(encoding="utf-8"))
    names = {k["name"]: k for k in d["known"]}
    assert names["Kapteyn's Star"]["recovered"] and names["WISE 0855-0714"]["recovered"]
    assert "Barnard's Star" in d["known_not_run"]
    assert "known fast-moving stars" in d["summary"]
    assert d["false_positives"]["tiles"] == 0 and d["false_positives"]["per_tile"] is None
