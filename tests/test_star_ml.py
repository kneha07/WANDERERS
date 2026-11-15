"""Tests for pipeline/star_ml.py (needs scikit-learn + astropy; offline: synthetic stars and committed files).

Run from the repository root:  .venv/bin/python -m unittest tests/test_star_ml.py -v
"""
import json
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import star_ml as M  # noqa: E402

PRED = ROOT / "app" / "data" / "stars" / "pred"
RA0, DEC0 = 120.0, 30.0


def synthetic(pm=(1500.0, -800.0), plx=0.0, acc=(0.0, 0.0), seed=0, kinds=None):
    """Observations of a made-up star from catalogues like the real ones (epoch, error, position type)."""
    rng = np.random.default_rng(seed)
    kinds = kinds or [("GSC", 1955.3, 300, "single"), ("Hip", 1991.25, 1, "bary"), ("Tyc", 1985.0, 25, "mean"),
                      ("2MASS", 1999.4, 70, "single"), ("2MASS-b", 2000.1, 70, "single"), ("AllWISE", 2010.5, 60, "mean"),
                      ("URAT", 2014.2, 10, "mean"), ("G1", 2015.0, 1, "bary"), ("G2", 2015.5, 1, "bary"), ("G3", 2016.0, 1, "bary")]
    truth = np.zeros(7); truth[2:4] = pm; truth[4] = plx; truth[5:7] = acc
    obs = []
    for name, t, s, kind in kinds:
        X = M.features(np.array([0, 1]), np.array([t, t]), np.array([kind == "single"] * 2), RA0, DEC0)
        xi, eta = X @ truth + rng.normal(0, s, 2)
        ra, dec = M.from_plane(xi, eta, RA0, DEC0)
        for axis in (0, 1):
            obs.append({"catalogue": name, "axis": axis, "epoch": t, "ra": float(ra), "dec": float(dec), "sigma_mas": float(s),
                        "floor_mas": 0.0, "plx": kind, "gaia": name.startswith("G"), "match_arcsec": 0.0})
    return obs, truth


class GeometryTests(unittest.TestCase):
    def test_tangent_plane_round_trip(self):
        for ra0, dec0 in [(0, 0), (269.45, 4.69), (217.4, -62.7), (10, 89)]:
            xi, eta = np.array([0.0, 1234.5, -98765.0]), np.array([0.0, -4321.0, 55555.0])
            ra, dec = M.from_plane(xi, eta, ra0, dec0)
            x2, y2 = M.to_plane(ra, dec, ra0, dec0)
            self.assertTrue(np.allclose(x2, xi, atol=1e-4) and np.allclose(y2, eta, atol=1e-4), (ra0, dec0))

    def test_epoch_conversions(self):
        self.assertAlmostEqual(float(M.jy_jd(2451545.0)), 2000.0)
        self.assertAlmostEqual(float(M.jy_mjd(51544.5)), 2000.0)


class LearningTests(unittest.TestCase):
    def test_recovers_linear_motion(self):
        obs, truth = synthetic(pm=(1500.0, -800.0))
        m, chosen, _, _ = M.fit_all(obs, RA0, DEC0)
        self.assertEqual(chosen, "linear")
        self.assertAlmostEqual(m.coef_[2], 1500.0, delta=0.5)
        self.assertAlmostEqual(m.coef_[3], -800.0, delta=0.5)

    def test_detects_a_real_acceleration(self):
        obs, truth = synthetic(pm=(-800.0, 10350.0), acc=(0.0, 1.3), seed=2)
        m, chosen, scores, _ = M.fit_all(obs, RA0, DEC0, plx_hint=547.0)
        self.assertTrue(chosen.startswith("accel"), scores)
        self.assertAlmostEqual(m.coef_[6], 1.3, delta=0.3)

    def test_rejects_an_impossible_acceleration(self):
        """A distant, slow star cannot accelerate by 5 mas/yr^2: the term is refused even if it fits."""
        obs, _ = synthetic(pm=(3.0, -27.0), acc=(5.0, 0.0), seed=3)
        _, chosen, scores, _ = M.fit_all(obs, RA0, DEC0, plx_hint=6.4)
        self.assertFalse(chosen.startswith("accel"), scores)
        self.assertTrue(any("physics allows" in w for w in scores["accel"]["rejected_because"]))

    def test_learns_parallax_when_single_epoch_data_constrain_it(self):
        kinds = [(f"plate{i}", 1990 + i * 0.37, 15, "single") for i in range(16)] + [("G3", 2016.0, 1, "bary"), ("Hip", 1991.25, 1, "bary")]
        obs, _ = synthetic(pm=(-3780.0, 770.0), plx=768.0, seed=4, kinds=kinds)
        m, chosen, scores, _ = M.fit_all(obs, RA0, DEC0, plx_hint=768.0)
        self.assertIn("parallax", chosen, scores)
        self.assertAlmostEqual(m.coef_[4], 768.0, delta=25)

    def test_negative_parallax_is_not_allowed(self):
        obs, _ = synthetic(pm=(100.0, 100.0), plx=-500.0, seed=5)
        _, chosen, _, _ = M.fit_all(obs, RA0, DEC0)
        self.assertNotIn("parallax", chosen)

    def test_robust_to_one_mismatched_catalogue(self):
        """Huber loss: one survey that picked up the wrong star 2 arcsec away barely moves the result."""
        obs, _ = synthetic(pm=(1500.0, -800.0), seed=6)
        for o in obs:
            if o["catalogue"] == "URAT":
                o["dec"] += 2.0 / 3600
        m, _, _, _ = M.fit_all(obs, RA0, DEC0)
        self.assertAlmostEqual(m.coef_[3], -800.0, delta=1.0)

    def test_bootstrap_errors_are_honest(self):
        """Parametric-bootstrap spread of the proper motion covers the truth."""
        obs, truth = synthetic(pm=(1500.0, -800.0), seed=7)
        X, y, sig, _ = M.training_set(obs, RA0, DEC0)
        coefs, k = M.param_bootstrap("linear", X, y, sig, n=100)
        err = np.diff(np.percentile(coefs[:, 2], [16, 84]))[0] / 2
        self.assertGreater(err, 0)
        self.assertLess(abs(np.median(coefs[:, 2]) - 1500.0), 5 * err + 0.5)

    def test_max_acceleration_matches_barnards_star(self):
        m = M.StarPathModel("linear+parallax"); m.coef_ = np.array([0, 0, -800, 10360, 547, 0, 0.0])
        lim = M.max_acceleration(m)
        self.assertGreater(lim, 1.3)          # Barnard's real perspective acceleration is ~1.3 mas/yr^2
        self.assertLess(lim, 4.0)


@unittest.skipUnless(PRED.exists(), "no committed predictions")
class CommittedPredictionTests(unittest.TestCase):
    """The shipped results agree with Gaia DR3, which is the independent check (except known blends)."""
    BLENDED = {"wanderers_rw_aur"}           # binary in nebulosity: ground catalogues see a shifted photocentre

    def test_learnt_motion_matches_gaia(self):
        n = 0
        for f in sorted(PRED.glob("*.json")):
            if f.stem == "index" or f.stem in self.BLENDED:
                continue
            p = json.loads(f.read_text()); g = p.get("gaia_dr3"); L = p["learnt"]
            if not g:
                continue
            n += 1
            mu = np.hypot(g["pmra"], g["pmdec"])
            miss = np.hypot(L["pmra_2016"] - g["pmra"], L["pmdec_2016"] - g["pmdec"])
            self.assertLess(miss, max(5.0, 0.005 * mu), f"{p['name']}: {miss:.1f} mas/yr")
        self.assertGreaterEqual(n, 8)

    def test_wise0855_matches_the_literature(self):
        p = json.loads((PRED / "wanderers_wise0855.json").read_text())
        self.assertAlmostEqual(p["learnt"]["pmra_mas_yr"], -8123.0, delta=0.01 * 8123)
        self.assertNotIn("2MASS", p["model"]["catalogues"])

    def test_wanderers_positions_are_labelled_by_mission(self):
        # the time-lapse now has NEOWISE frames (2014-2024): they must not be filed as SPHEREx measurements
        obs = M.wanderers_obs({"wanderers": "barnard", "dist_pc": 1.83})
        by = {}
        for o in obs:
            by.setdefault(o["catalogue"].rsplit(" ", 1)[0], []).append(o["epoch"])
        self.assertEqual(set(by), {"WANDERERS WISE", "WANDERERS NEOWISE", "WANDERERS SPHEREx"})
        self.assertTrue(all(2013 < y < 2025 for y in by["WANDERERS NEOWISE"]))
        self.assertTrue(all(y > 2025 for y in by["WANDERERS SPHEREx"]))

    def test_barnards_star_perspective_acceleration(self):
        p = json.loads((PRED / "hip87937.json").read_text())
        self.assertTrue(p["model"]["chosen_features"].startswith("accel"))
        self.assertAlmostEqual(p["learnt"]["acc_dec_mas_yr2"], 1.3, delta=0.3)


if __name__ == "__main__":
    unittest.main()
