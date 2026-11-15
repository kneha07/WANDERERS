"""Validation of the REAL mover search (survey.link.process_tile) with the injection-recovery harness.

Skipped until pipeline/survey/link.py exists (it is written in parallel; see docs/survey-contract.md). Once it is
merged these tests run the real core, blind, on synthetic NEOWISE skies with the real cadence, on mover-free
skies, and on the two real NEOWISE fixtures. No network. Expect ~1-3 minutes.

Thresholds and why (numbers from the noise model in survey/validate.py, calibrated on the fixtures):
- >= 95 % completeness for pm >= 1"/yr at W2 <= 13 (both colours). Such a mover has W2 SNR >= 15 per exposure,
  ~0.1-0.2" per detection, >= 12 detections in each of ~21 visits over 10 years, and moves >= 10" over the span
  (>= 50x the per-visit error). Nothing in the data hides it; a miss is a linking or cut problem.
  60 injections: at most 3 misses.
- >= 90 % for the bright slow movers (0.2 and 0.5"/yr, W2 <= 13, star colour): friends-of-friends links them
  trivially (<= 0.25" per 6-month step); pm >= 200 mas/yr vs the 150 mas/yr cut with sigma_pm ~ 5 mas/yr.
- >= 85 % of all *detectable* injections with pm >= 1"/yr (the data hold >= 6 visits with >= 2 good detections,
  exactly what min_visits=6 needs), at any magnitude and colour. Not 95 %: at the faint end a visit with only
  2-3 noisy detections may not cluster, which can push a mover below 6 linked visits.
- median |pm_found - pm_true| / pm_true < 2 % (pm >= 1"/yr, W2 <= 13) and < 5 % over everything recovered;
  median direction error < 2 deg. Expected errors are ~0.1-1 % (sigma_pm ~ 3-10 mas/yr); 2-5 % catches unit
  slips (cos dec, mas vs arcsec, years vs days), sign errors and unmodelled parallax biasing the fit.
- median |(pm_found - pm_true) / pm_err| between 0.3 and 2.5 (0.674 if pm_err is honest): pm_snr ranks the
  candidates, so pm_err must not be wildly over- or under-stated.
- <= 1 false mover per survey tile (3.357 deg^2) on 12 mover-free skies (~3.4 deg^2: at most 1 false mover in
  all of them), and <= 1 per tile among unexplained movers in the injected skies; duplicates <= 5 % of recoveries.
  At 1 per tile a full-sky run makes ~12,000 false movers, about the number of real stars with pm > 150 mas/yr
  bright enough for NEOWISE single exposures, so anything worse would swamp the "unexplained" candidates.
- Real data: Kapteyn's Star (W2 5.8, saturated) recovered with |pm| within 2 % of Gaia DR3 and WISE 0855 (W2 ~14,
  W1 undetected) within 3 % of Luhman & Esplin (2016), each as exactly one track, with <= 1 other mover in each
  4' field (more would mean > 30 false movers per deg^2).
"""
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
from survey import validate as V  # noqa: E402

LINK = ROOT / "pipeline" / "survey" / "link.py"
pytestmark = pytest.mark.skipif(
    not LINK.exists(),
    reason="survey.link (pipeline/survey/link.py) is not merged yet; these tests validate the real mover search "
           "and run automatically once it exists")

if LINK.exists():
    from survey import link  # noqa: E402  (import errors must fail loudly, not skip)
else:
    link = None


@pytest.fixture(scope="module")
def rec():
    return V.recovery(link.process_tile, pms=V.PM_GRID_ARCSEC, w2s=V.W2_GRID, colours=(0.0, 2.0), trials=4,
                      n_empty=12, seed=2024)


def pooled(records, **cond):
    sel = [r for r in records if all(f(r[k]) for k, f in cond.items())]
    return sum(r["recovered"] for r in sel), len(sel)


def test_completeness_bright_movers(rec):
    k, n = pooled(rec["records"], pm_arcsec_yr=lambda v: v >= 1.0, w2=lambda v: v <= 13.0)
    assert n == 5 * 3 * 2 * 4
    assert k / n >= 0.95, f"{k}/{n} bright movers (pm >= 1\"/yr, W2 <= 13) recovered"


def test_completeness_bright_slow_movers(rec):
    k, n = pooled(rec["records"], pm_arcsec_yr=lambda v: v <= 0.5, w2=lambda v: v <= 13.0, w1w2=lambda v: v == 0.0)
    assert k / n >= 0.90, f"{k}/{n} bright slow movers recovered"


def test_completeness_of_detectable_movers(rec):
    k, n = pooled(rec["records"], pm_arcsec_yr=lambda v: v >= 1.0, detectable=lambda v: v)
    assert n > 0 and k / n >= 0.85, f"{k}/{n} detectable movers (pm >= 1\"/yr) recovered"


def test_completeness_falls_off_with_brightness_not_before(rec):
    rows = [r for r in rec["completeness"] if r["w1w2"] == 0.0 and r["pm_arcsec_yr"] >= 1.0]
    by_w2 = {}
    for r in rows:
        a = by_w2.setdefault(r["w2"], [0, 0])
        a[0] += r["recovered"]
        a[1] += r["trials"]
    frac = [by_w2[w][0] / by_w2[w][1] for w in sorted(by_w2)]
    assert frac[0] >= 0.95 and frac[1] >= 0.95  # W2 = 8 and 11


def test_pm_accuracy(rec):
    good = [r for r in rec["records"] if r["recovered"] and r["pm_arcsec_yr"] >= 1.0 and r["w2"] <= 13.0]
    assert np.median([r["frac_error"] for r in good]) < 0.02
    assert np.median([r["pa_error_deg"] for r in good]) < 2.0
    assert rec["pm_accuracy"]["median_frac_error"] < 0.05


def test_pm_errors_are_honest(rec):
    pull = rec["pm_accuracy"]["median_abs_pull"]
    if pull is None:
        pytest.skip("the movers carry no pm_err")
    assert 0.3 < pull < 2.5, f"median |pull| {pull} (0.674 expected for honest Gaussian errors)"


def test_false_positives_on_empty_skies(rec):
    fp = rec["false_positives"]
    assert fp["tiles"] == 12
    assert fp["per_tile"] <= 1.0, f"{fp['movers']} false movers on {fp['area_deg2']} deg^2 = {fp['per_tile']}/tile"


def test_no_extra_movers_in_injected_skies(rec):
    sp = rec["spurious_in_injected"]
    n_rec = sum(r["recovered"] for r in rec["records"])
    assert sp["per_tile"] <= 1.0, f"{sp['movers']} unexplained movers in the injected skies"
    assert sp["duplicates"] <= 0.05 * n_rec, f"{sp['duplicates']} duplicate tracks for {n_rec} recoveries"


@pytest.fixture(scope="module")
def real():
    return V.run_real(link.process_tile, tiles_dir=ROOT / "no-such-dir")


@pytest.mark.parametrize("name,max_pct", [("Kapteyn's Star", 2.0), ("WISE 0855-0714", 3.0)])
def test_known_star_in_real_neowise_data(real, name, max_pct):
    rows, fields, _ = real
    row = next(r for r in rows if r["name"] == name)
    assert row["recovered"], row
    assert row["error_pct"] < max_pct, row
    field = next(f for f in fields if f["name"] == name)
    assert field["target_tracks"] == 1, field
    assert field["other_movers"] <= 1, field


def test_movers_follow_the_contract(rec):
    reader = V.fixture_reader(ROOT / "tests" / "fixtures" / "neowise_kapteyn_4arcmin.parquet", k5=8545)
    res = link.process_tile(8545, reader=reader, years=V.YEAR_LABELS)
    for k in ("k5", "n_detections", "n_good", "n_visits", "n_movers", "movers"):
        assert k in res
    assert res["n_movers"] == len(res["movers"])
    for m in res["movers"]:
        for k in ("id", "ra", "dec", "epoch", "pmra", "pmdec", "pm", "pm_err", "pm_snr", "chi2r", "n_visits",
                  "span_yr", "w1", "w2", "track"):
            assert k in m, k
        assert m["pm"] == pytest.approx(math.hypot(m["pmra"], m["pmdec"]), rel=1e-3)
        assert m["pm"] >= 150.0 and m["n_visits"] >= 6


def test_an_empty_tile_gives_no_movers():
    res = link.process_tile(8545, reader=lambda k5, year: None, years=V.YEAR_LABELS)
    assert res["n_movers"] == 0 and res["movers"] == []


def test_movers_across_ra_zero_and_next_to_a_pole():
    # tile 4159 is centred on RA 0 (dec -20.7), tile 1023 touches the north pole (centre dec 88.5): each sky
    # (radius ~0.16 deg) lies inside its tile, so a core that keeps only movers inside its tile is not penalised
    r = V.recovery(link.process_tile, pms=(1.0, 4.0, 11.0), w2s=(11.0, 13.0), trials=2, n_empty=0, seed=7,
                   centers=[4159, 1023])
    k = sum(x["recovered"] for x in r["records"])
    assert k / len(r["records"]) >= 0.9, f"{k}/{len(r['records'])} recovered across RA 0 / next to the pole"
    assert r["pm_accuracy"]["median_frac_error"] < 0.02


def test_cli_writes_validation_json_with_the_real_core(tmp_path):
    out = tmp_path / "validation.json"
    assert V.main(["--out", str(out), "--quick", "--trials", "1", "--real", "--tiles-dir", str(tmp_path)]) == 0
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["core"] == "survey.link:process_tile" and d["known"]
