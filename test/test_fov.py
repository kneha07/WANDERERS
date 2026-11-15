"""Tests for pipeline/fov.py. No third-party packages needed.

Run from the repository root:  python3 test/test_fov.py -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import fov  # noqa: E402


class ClampTests(unittest.TestCase):
    def test_default_when_missing_or_unusable(self):
        for v in (None, "", "abc", float("nan"), float("inf"), float("-inf"), [], {}):
            self.assertEqual(fov.clamp_fov(v), fov.DEFAULT_FOV, repr(v))

    def test_inside_range_is_kept_as_whole_number(self):
        self.assertEqual(fov.clamp_fov(120), 120)
        self.assertEqual(fov.clamp_fov("600"), 600)
        self.assertEqual(fov.clamp_fov(299.6), 300)

    def test_limits(self):
        self.assertEqual(fov.clamp_fov(1), fov.MIN_FOV)
        self.assertEqual(fov.clamp_fov(-500), fov.MIN_FOV)
        self.assertEqual(fov.clamp_fov(10 ** 6), fov.MAX_FOV)

    def test_page_choices_are_all_allowed(self):
        for c in fov.CHOICES:
            self.assertEqual(fov.clamp_fov(c), c)
        self.assertIn(fov.DEFAULT_FOV, fov.CHOICES)


class TargetTests(unittest.TestCase):
    def test_fov_of_target(self):
        self.assertEqual(fov.fov_of({}), 300)
        self.assertEqual(fov.fov_of({"fov_arcsec": 600}), 600)
        self.assertEqual(fov.fov_of({"fov_arcsec": None}), 300)

    def test_npix(self):
        self.assertEqual(fov.npix_for(300), 150)      # what every committed target uses
        self.assertEqual(fov.npix_for(120), 60)
        self.assertEqual(fov.npix_for(600), 300)
        self.assertEqual(fov.npix_for(None), 150)


class PositionIdTests(unittest.TestCase):
    def test_default_field_keeps_the_original_id(self):
        # these must not change, or positions cached before this feature would be fetched again
        self.assertEqual(fov.position_id(133.7951, -7.2451), "pos_133p7951_s7p2451")
        self.assertEqual(fov.position_id(76.9564, 30.4014, 300), "pos_76p9564_n30p4014")
        self.assertEqual(fov.position_id(0, 0), "pos_0p0000_n0p0000")

    def test_other_fields_get_a_suffix(self):
        self.assertEqual(fov.position_id(133.7951, -7.2451, 600), "pos_133p7951_s7p2451_f600")
        self.assertEqual(fov.position_id(10.0, 20.0, 120), "pos_10p0000_n20p0000_f120")

    def test_out_of_range_values_share_the_clamped_id(self):
        self.assertEqual(fov.position_id(10, 20, 5000), fov.position_id(10, 20, 900))
        self.assertEqual(fov.position_id(10, 20, "junk"), fov.position_id(10, 20))

    def test_rounding_matches_javascript_tofixed(self):
        # fields.js uses toFixed(4), which rounds an exact tie away from zero; Python's format rounds it to even.
        # Odd multiples of 1/32 degree are exact ties in binary.
        self.assertEqual(fov.position_id(1.03125, -7.03125), "pos_1p0313_s7p0313")
        self.assertEqual(fov.position_id(10.09375, 0.15625), "pos_10p0938_n0p1563")
        self.assertEqual(fov.position_id(10.0, -0.0), "pos_10p0000_n0p0000")        # JS: -0 < 0 is false
        self.assertEqual(fov.position_id(10.0, -0.00004), "pos_10p0000_s0p0000")    # JS: "-" + "0.0000"

    def test_huge_numbers_fall_back_to_the_default(self):
        self.assertEqual(fov.clamp_fov(10 ** 400), fov.DEFAULT_FOV)

    def test_ids_are_safe_for_file_names_and_urls(self):
        import re
        for args in ((359.9999, -89.9999, 600), (0, 90, 120), (12.5, -0.00004, None)):
            self.assertRegex(fov.position_id(*args), r"^[A-Za-z0-9_]+$")


if __name__ == "__main__":
    unittest.main()
