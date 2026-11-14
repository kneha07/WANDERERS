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


if __name__ == '__main__':
    unittest.main()
