"""Regression tests for WANDERERS evidence cards. Run: python3 -m unittest discover -s tests -p 'test_evidence.py' -v"""
import importlib.util
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / 'pipeline' / 'evidence.py'
spec = importlib.util.spec_from_file_location('wanderers_evidence', MODULE)
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)


def target(**changes):
    t = {
        'target_in_gaia': True,
        'reference': {'source': 'Gaia DR3', 'source_id': '123', 'catalogued': True},
        'motion': None, 'variability': None, 'ir_color': None,
        'spectrum_points': 100, 'flagged_points': 0,
    }
    t.update(changes)
    return t


def motion(pixels=3, speed=1, expected=1):
    return {'shift_spherex_pixels': pixels, 'measured_arcsec_per_yr': speed,
            'expected_arcsec_per_yr': expected, 'shift_arcsec': 12,
            'from_year': 2025, 'to_year': 2026}


class EvidenceCardTests(unittest.TestCase):
    def test_steady_catalogued_star(self):
        c = evidence.card(target())
        self.assertEqual(c['classification'], 'Steady star (no change in these snapshots)')
        self.assertEqual((c['confidence'], c['checks_passed'], c['checks_needed']), ('high', 2, 2))

    def test_motion_thresholds_are_inclusive(self):
        c = evidence.card(target(motion=motion(pixels=2, speed=0.3, expected=0.3)))
        self.assertEqual(c['classification'], 'Nearby star with fast proper motion')
        self.assertEqual(c['confidence'], 'high')

    def test_motion_below_pixel_threshold(self):
        c = evidence.card(target(motion=motion(pixels=1.99)))
        self.assertEqual(c['classification'], 'Steady star (no change in these snapshots)')

    def test_motion_catalogue_mismatch_reduces_confidence(self):
        c = evidence.card(target(motion=motion(expected=2)))
        self.assertEqual(c['classification'], 'Nearby star with fast proper motion')
        self.assertEqual((c['checks_passed'], c['checks_needed'], c['confidence']), (2, 3, 'medium'))

    def test_methane_rich_mover(self):
        c = evidence.card(target(motion=motion(), ir_color={'ratio': 2, 'lower_limit': True}))
        self.assertEqual(c['classification'], 'Cold brown dwarf (methane-rich)')
        self.assertEqual(c['confidence'], 'high')

    def test_variability_threshold_is_strict(self):
        v = {'delta_mag': 0.3, 'uncertainty_mag': 0.1, 'from': '2025', 'to': '2026'}
        c = evidence.card(target(variability=v))
        self.assertEqual(c['classification'], 'Steady star (no change in these snapshots)')
        v['delta_mag'] = 0.31
        self.assertEqual(evidence.card(target(variability=v))['classification'], 'Variable star')

    def test_saturation_reduces_variable_star_confidence(self):
        v = {'delta_mag': 1, 'uncertainty_mag': 0.1, 'from': '2025', 'to': '2026'}
        c = evidence.card(target(variability=v, flagged_points=81))
        self.assertEqual(c['classification'], 'Variable star')
        self.assertEqual(c['confidence'], 'medium')
        self.assertIn('saturated', c['confidence_note'])
        self.assertTrue(any(x['state'] == 'warn' for x in c['checks']))

    def test_uncatalogued_target_is_candidate(self):
        c = evidence.card(target(target_in_gaia=False,
            reference={'source': 'Uncatalogued', 'source_id': None, 'catalogued': False}))
        self.assertEqual(c['status'], 'candidate')

    def test_non_gaia_catalogued_target_is_known(self):
        c = evidence.card(target(target_in_gaia=False,
            reference={'source': 'Published catalogue', 'catalogued': True}))
        self.assertEqual(c['status'], 'known')

    def test_card_does_not_mutate_input(self):
        t = target(motion=motion())
        original = repr(t)
        evidence.card(t)
        self.assertEqual(repr(t), original)


if __name__ == '__main__':
    unittest.main()
