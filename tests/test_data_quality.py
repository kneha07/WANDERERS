"""Unit tests for pipeline/analyze.py measurement and bad-pixel helpers.

Run from repository root after installing pipeline/requirements.txt:
    python3 -m unittest discover -s tests -p 'test_data_quality.py' -v
These tests use synthetic images, not downloaded NASA observations.
"""
import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / 'pipeline'


def load_analyze():
    if not (PIPELINE / 'analyze.py').exists():
        raise FileNotFoundError('Expected pipeline/analyze.py in repository root')
    spec = importlib.util.spec_from_file_location('wanderers_analyze', PIPELINE / 'analyze.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestDataQuality(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.analyze = load_analyze()
        except ImportError as exc:
            raise unittest.SkipTest(f'Install pipeline dependencies first: {exc}')

    def test_bad_mask_excludes_bad_flags(self):
        from astropy.io import fits
        hdu = fits.ImageHDU(data=np.array([[0, 1, 2, 3]], dtype=np.int16))
        hdu.header['MSKN0001'] = 'OVERFLOW'
        hdu.header['MSKM0001'] = 1
        hdu.header['MSKN0002'] = 'SOURCE'
        hdu.header['MSKM0002'] = 2
        np.testing.assert_array_equal(self.analyze.bad_mask(hdu), [[False, True, False, True]])

    def test_display_mask_keeps_overflow_visible(self):
        from astropy.io import fits
        hdu = fits.ImageHDU(data=np.array([[1, 2]], dtype=np.int16))
        hdu.header['MSKN0001'] = 'OVERFLOW'
        hdu.header['MSKM0001'] = 1
        hdu.header['MSKN0002'] = 'HOT'
        hdu.header['MSKM0002'] = 2
        np.testing.assert_array_equal(self.analyze.bad_mask(hdu, self.analyze.DISPLAY_BAD), [[False, True]])

    def test_photometry_removes_uniform_background(self):
        img = np.full((41, 41), 10.0)
        img[20, 20] = 110.0
        flux, nbad = self.analyze.photometry(img, np.zeros_like(img, dtype=bool), 20, 20)
        self.assertAlmostEqual(flux, 100.0)
        self.assertEqual(nbad, 0)

    def test_photometry_excludes_flagged_aperture_pixel(self):
        img = np.full((41, 41), 10.0)
        img[20, 20] = 1000.0
        bad = np.zeros_like(img, dtype=bool)
        bad[20, 20] = True
        flux, nbad = self.analyze.photometry(img, bad, 20, 20)
        self.assertAlmostEqual(flux, 0.0)
        self.assertEqual(nbad, 1)

    def test_photometry_outside_image_is_nan(self):
        img = np.ones((41, 41))
        flux, nbad = self.analyze.photometry(img, np.zeros_like(img, dtype=bool), -100, -100)
        self.assertTrue(np.isnan(flux))
        self.assertEqual(nbad, 0)

    def test_wing_flux_requires_sufficient_pixels(self):
        img = np.ones((15, 15))
        value = self.analyze.wing_flux(img, np.zeros_like(img, dtype=bool), 7, 7)
        self.assertTrue(np.isnan(value))

    def test_detection_snr_returns_zero_without_background(self):
        img = np.ones((10, 10))
        self.assertEqual(self.analyze.detection_snr(img, 5, 5), 0.0)

    def test_centroid_returns_none_without_signal(self):
        img = np.ones((31, 31))
        self.assertIsNone(self.analyze.centroid(img, 15, 15))

    def test_centroid_finds_synthetic_point(self):
        img = np.zeros((31, 31))
        img[12, 17] = 100
        x, y = self.analyze.centroid(img, 17, 12)
        self.assertAlmostEqual(x, 17)
        self.assertAlmostEqual(y, 12)

    def test_stretch_handles_all_nan(self):
        result = self.analyze.stretch(np.full((4, 4), np.nan))
        np.testing.assert_array_equal(result, np.zeros((4, 4)))

    def test_big_saturated_core_counts_as_seen_but_gives_no_position(self):
        # NEOWISE blanks the saturated core of a very bright star (R Draconis, 61 Cygni: 400-700 pixels on the grid)
        A = self.analyze
        img = np.random.default_rng(0).normal(0, 1, (150, 150))
        yy, xx = np.indices(img.shape)
        img[np.hypot(xx - 75, yy - 75) <= 13] = np.nan                  # ~530 blank pixels around the star
        self.assertIsNone(A.saturated_core(img, 76, 75, 5))             # too big to take its centre as the position
        self.assertTrue(A.saturated_beyond_measure(img, 76, 75, 5))      # but the star is there: seen, saturated
        self.assertFalse(A.core_has_pixels(img, 76, 75, 3))
        self.assertFalse(A.saturated_beyond_measure(img, 120, 120, 5))   # nothing blank at another position
        small = np.zeros((150, 150)); small[np.hypot(xx - 75, yy - 75) <= 5] = np.nan
        self.assertAlmostEqual(A.saturated_core(small, 76, 75, 5)[0], 75.0)   # a small core still gives the position
        self.assertFalse(A.saturated_beyond_measure(small, 76, 75, 5))
        edge = np.zeros((150, 150)); edge[:, :30] = np.nan                    # a strip with no data at the border
        self.assertFalse(A.saturated_beyond_measure(edge, 31, 75, 5))
        self.assertTrue(A.core_has_pixels(edge, 35, 75, 3))

    def test_shipped_saturated_frames_are_not_called_undetected(self):
        # R Draconis / 61 Cygni: NEOWISE frames over a huge blank (saturated) core were "not detected" with a 0.0 signal
        import json
        for f in sorted((ROOT / 'app' / 'data').glob('*/target.json')):
            t = json.loads(f.read_text(encoding='utf-8'))
            for ch, frames in t['frames'].items():
                for fr in frames:
                    if fr['mission'] in ('WISE', 'NEOWISE'):
                        self.assertFalse(fr.get('detected') is False and fr.get('snr') == 0.0, f'{f.parent.name} {fr["png"]}')
                        if fr.get('saturated_core'):
                            self.assertTrue(fr['detected'], f'{f.parent.name} {fr["png"]}')

    def test_brightness_change_never_compares_a_visit_with_itself(self):
        last = self.analyze.last_visit
        self.assertEqual(last([[0] * 40, [0] * 10]), 1)               # only the first visit is big: still compare with the later one
        self.assertEqual(last([[0] * 40, [0] * 35, [0] * 10]), 1)     # latest big visit preferred
        self.assertEqual(last([[0] * 20, [0] * 18, [0] * 22]), 2)
        self.assertIsNone(last([[0] * 40]))

    def test_east_offset_takes_the_short_way_across_ra_zero(self):
        from astropy.coordinates import SkyCoord
        import astropy.units as u
        a, b = SkyCoord(359.999 * u.deg, 10 * u.deg), SkyCoord(0.001 * u.deg, 10 * u.deg)
        self.assertAlmostEqual(self.analyze.east_arcsec(a, b, 10.0), 7.2 * np.cos(np.radians(10)), places=6)
        self.assertAlmostEqual(self.analyze.east_arcsec(b, a, 10.0), -7.2 * np.cos(np.radians(10)), places=6)

    def test_mover_crossing_ra_zero_has_a_sane_proper_motion(self):
        from astropy.coordinates import SkyCoord
        import astropy.units as u
        A = self.analyze
        npix = 150
        gw = A.grid_wcs(SkyCoord(0.0 * u.deg, 10.0 * u.deg), npix)
        yy, xx = np.indices((npix, npix))
        rng = np.random.default_rng(1)
        blob = lambda x, y: 60 * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 1.5 ** 2))
        old = rng.normal(0, 1, (npix, npix)) + blob(85, 75)            # west of RA 0h in 2010
        new = rng.normal(0, 1, (npix, npix)) + blob(65, 75)            # 40" east, past RA 0h, 15 years later
        movers = A.find_movers(old, new, 2010.5, 2025.5, gw, [], npix)
        self.assertEqual(len(movers), 1)
        m = movers[0]
        self.assertAlmostEqual(m['arcsec_per_yr'], 40 / 15, delta=0.1)
        self.assertAlmostEqual(m['pmra'], 40 / 15 * 1000, delta=100)      # mas/yr, not ~ -8.6e7
        self.assertAlmostEqual(m['pmdec'], 0, delta=100)


if __name__ == '__main__':
    unittest.main()
