"""Tests for pipeline/star_trajectory.py (needs astropy; offline).

Run from the repository root:  .venv/bin/python -m unittest tests/test_star_trajectory.py -v
"""
import json
import sys
import unittest
from pathlib import Path

import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord, GCRS, Distance
from astropy.time import Time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import star_trajectory as st  # noqa: E402

DATA = ROOT / "app" / "data"
TARGETS = [p.parent.name for p in sorted(DATA.glob("*/target.json"))]
BARNARD = {"ra": 269.44850252543836, "dec": 4.739420051112412, "epoch": 2016.0,
           "pmra": -801.5509783684709, "pmdec": 10362.394206546573, "parallax": 546.975939730948}


class ParallaxTests(unittest.TestCase):
    def test_matches_astropy_full_transform(self):
        """Our closed-form parallax equals the near-minus-far difference of astropy's GCRS transform
        (aberration and light bending cancel in that difference)."""
        for ra, dec in [(269.45, 4.74), (133.8, -7.2), (331.1, -56.8), (10.0, 80.0)]:
            for yr in (2010.5, 2025.3, 2025.8):
                t = Time(yr, format="jyear")
                near = SkyCoord(ra * u.deg, dec * u.deg, distance=Distance(parallax=500 * u.mas)).transform_to(GCRS(obstime=t))
                far = SkyCoord(ra * u.deg, dec * u.deg, distance=1e9 * u.pc).transform_to(GCRS(obstime=t))
                dra = (near.ra - far.ra).to(u.mas).value * np.cos(far.dec.rad)
                ddec = (near.dec - far.dec).to(u.mas).value
                a, d = st.parallax_offsets(ra, dec, [yr], 500)
                self.assertAlmostEqual(a[0], dra, delta=0.5, msg=(ra, dec, yr))
                self.assertAlmostEqual(d[0], ddec, delta=0.5, msg=(ra, dec, yr))

    def test_loop_size_is_the_parallax(self):
        """Over a year the shift never exceeds the parallax (Earth's orbit is ~1 AU)."""
        a, d = st.parallax_offsets(BARNARD["ra"], BARNARD["dec"], np.linspace(2025, 2026, 365), 547.0)
        peak = np.max(np.hypot(a, d))
        self.assertGreater(peak, 0.95 * 547.0)
        self.assertLess(peak, 1.02 * 547.0)

    def test_no_parallax_no_shift(self):
        for p in (0, None):
            a, d = st.parallax_offsets(10, 10, [2025.0, 2025.5], p)
            self.assertTrue(np.all(a == 0) and np.all(d == 0))


class PredictTests(unittest.TestCase):
    def test_reference_epoch_without_parallax_is_the_catalogue_position(self):
        ra, dec = st.predict(BARNARD, [2016.0], parallax=False)
        self.assertAlmostEqual(ra[0], BARNARD["ra"], places=9)
        self.assertAlmostEqual(dec[0], BARNARD["dec"], places=9)

    def test_barnard_moves_ten_arcsec_a_year_north(self):
        ra, dec = st.predict(BARNARD, [2016.0, 2026.0], parallax=False)
        self.assertAlmostEqual((dec[1] - dec[0]) * 3600, 103.6, delta=0.3)
        self.assertLess(ra[1], ra[0])                 # pmra is negative

    def test_stationary_star_stays_put(self):
        ref = {"ra": 76.956, "dec": 30.401, "epoch": 2016.0, "pmra": 0, "pmdec": 0, "parallax": None}
        ra, dec = st.predict(ref, [2010.5, 2030.0])
        self.assertTrue(np.allclose(ra, 76.956) and np.allclose(dec, 30.401))

    def test_ra_stays_in_range_across_0h(self):
        # a nearby star sitting on RA 0h: its yearly parallax loop takes it to both sides of the line
        for ra0 in (0.00001, 359.99999):
            ra, dec = st.predict({"ra": ra0, "dec": 10.0, "epoch": 2016.0, "pmra": 0, "pmdec": 0, "parallax": 500.0},
                                 np.linspace(2016.0, 2017.0, 13))
            self.assertTrue(np.all((ra >= 0) & (ra < 360)), ra)
            self.assertLess(np.max(np.minimum(ra, 360 - ra)) * 3600, 1.0)      # still within 1" of 0h


@unittest.skipUnless(TARGETS, "no committed targets in app/data")
class CommittedTargetTests(unittest.TestCase):
    def test_grid_matches_analyze_py(self):
        """With proper motion only, our pixels reproduce analyze.py's own pred_x/pred_y on every target."""
        for tid in TARGETS:
            t = json.loads((DATA / tid / "target.json").read_text())
            w = st.grid_wcs(t["grid"])
            for p in t["track"]:
                ra, dec = st.predict(t["reference"], [p["year"]], parallax=False)
                x, y = w.world_to_pixel(SkyCoord(ra * u.deg, dec * u.deg))
                self.assertAlmostEqual(float(x[0]), p["pred_x"], delta=0.01, msg=tid)
                self.assertAlmostEqual(float(y[0]), p["pred_y"], delta=0.01, msg=tid)

    def test_build_output_shape(self):
        for tid in TARGETS:
            t = json.loads((DATA / tid / "target.json").read_text())
            tr = st.build(t, forecast=(2030.0,))
            self.assertEqual(tr["id"], tid)
            self.assertEqual(len(tr["checks"]), len(t["track"]))
            self.assertEqual(len(tr["path"]["with_parallax"]), len(tr["path"]["proper_motion_only"]))
            years = [p[0] for p in tr["path"]["with_parallax"]]
            self.assertEqual(years, sorted(years))
            self.assertEqual(tr["forecast"][0]["year"], 2030.0)
            json.dumps(tr)                            # serialisable

    def test_fast_movers_cross_the_field_and_fit_the_measurements(self):
        """Barnard's Star, Epsilon Indi B and WISE 0855 move tens of arcsec; the prediction stays
        within one SPHEREx pixel (6.15") of what was measured at 4.6 um."""
        for tid in ("barnard", "eps_indi_b", "wise0855"):
            if tid not in TARGETS:
                continue
            tr = st.build(json.loads((DATA / tid / "target.json").read_text()))
            w2 = [c["resid_arcsec"] for c in tr["checks"] if c["ch"] == "w2"]
            self.assertTrue(w2, tid)
            self.assertLess(max(w2), 6.15, tid)
            self.assertGreater(tr["parallax_loop_arcsec"], 0.2, tid)


if __name__ == "__main__":
    unittest.main()
