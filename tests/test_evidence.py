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

    def test_motion_years_are_calendar_years(self):
        # Kapteyn's Star: last SPHEREx frame at 2026.67 is still 2026, and WISE 2010.5 is 2010
        m = dict(motion(), from_year=2010.5, to_year=2026.6693)
        self.assertIn('between 2010 and 2026', evidence.card(target(motion=m))['checks'][0]['text'])
        m['shift_spherex_pixels'] = 1
        self.assertEqual(evidence.card(target(motion=m))['checks'][0]['text'], 'No measurable motion between 2010 and 2026')

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
        # a typed position with nothing catalogued there must not be called "catalogued in the literature"
        text = ' '.join(x['text'] for x in c['checks'])
        self.assertNotIn('Catalogued in the literature', text)
        self.assertIn('no published catalogue entry', text)

    def test_non_gaia_catalogued_target_is_known(self):
        c = evidence.card(target(target_in_gaia=False,
            reference={'source': 'Published catalogue', 'catalogued': True}))
        self.assertEqual(c['status'], 'known')
        self.assertTrue(any('Catalogued in the literature (Published catalogue)' in x['text'] for x in c['checks']))

    def test_motion_years_are_calendar_years(self):
        # SPHEREx in September 2026 (2026.67) is "2026", never a future "2027"; WISE 2010.5 stays "2010"
        m = dict(motion(), from_year=2010.5, to_year=2026.67)
        self.assertIn('between 2010 and 2026', evidence.card(target(motion=m))['checks'][0]['text'])
        still = dict(motion(pixels=1), from_year=2010.5, to_year=2026.67)
        self.assertEqual(evidence.card(target(motion=still))['checks'][0]['text'], 'No measurable motion between 2010 and 2026')

    def test_card_does_not_mutate_input(self):
        t = target(motion=motion())
        original = repr(t)
        evidence.card(t)
        self.assertEqual(repr(t), original)

    def test_known_variable_is_not_called_steady(self):
        c = evidence.card(target(story='variability'))
        self.assertEqual(c['classification'], 'Known variable star, quiet in these snapshots')
        self.assertTrue(any('Catalogued as a variable' in x['text'] for x in c['checks']))

    def test_motion_below_limit_is_labelled(self):
        c = evidence.card(target(motion=motion(pixels=1.1, speed=0.43, expected=0.02)))
        self.assertIn('below the detection limit', c['numbers'][0]['label'])
        self.assertEqual(evidence.card(target(motion=motion()))['numbers'][0]['label'], 'measured motion')


class ShippedExplanationTests(unittest.TestCase):
    """app/data/<id>/explain.json is written once (pipeline/explain.py); it must not contradict the current card."""

    def test_quoted_motion_and_years_match_the_data(self):
        import json
        import re
        data = MODULE.parents[1] / 'app' / 'data'
        for f in sorted(data.glob('*/explain.json')):
            t = json.loads((f.parent / 'target.json').read_text(encoding='utf-8'))
            e = json.loads(f.read_text(encoding='utf-8'))
            text = ' '.join([e['summary']] + [qa['a'] for qa in e['qa']])
            m = t.get('motion') or {}
            ok = {f"{m[k]:.2f}" for k in ('measured_arcsec_per_yr', 'expected_arcsec_per_yr') if k in m}
            for rate in re.findall(r'(\d+\.\d+)\s*(?:″|arcsec(?:onds)?)\s*(?:/|per )\s*(?:yr|year)', text):
                self.assertIn(rate, ok, f'{f.parent.name}: {rate}″/yr')
            if m:
                last = int(m['to_year'])
                for y in re.findall(r'\b(20[0-9]{2})\b', text):
                    self.assertLessEqual(int(y), last, f'{f.parent.name}: {y}')


class InsightTests(unittest.TestCase):
    def facts(self, **changes):
        return {f['id']: f for f in evidence.insights(target(**changes))['facts']}

    def test_speed_from_motion_and_parallax(self):
        # Barnard's Star: 10.40 arcsec/yr at parallax 0.547 arcsec is about 90 km/s
        m = {'shift_spherex_pixels': 26.6, 'measured_arcsec_per_yr': 10.40, 'expected_arcsec_per_yr': 10.39,
             'shift_arcsec': 163.5, 'from_year': 2010.5, 'to_year': 2026.2}
        f = self.facts(motion=m, reference={'source': 'Gaia DR3', 'parallax': 547.0})
        self.assertIn('About 90 km/s', f['speed']['headline'])
        self.assertIn('170 years', f['moon']['headline'])
        self.assertIn('6.0 light-years', f['distance']['headline'])

    def test_no_speed_without_real_motion_or_parallax(self):
        self.assertNotIn('speed', self.facts(motion=motion(pixels=1.1), reference={'parallax': 100.0}))
        f = self.facts(motion=motion(), reference={'parallax': None})
        self.assertNotIn('speed', f)
        self.assertIn('moon', f)

    def test_fade_in_percent(self):
        v = {'delta_mag': 0.34, 'uncertainty_mag': 0.06, 'from': 'Jun 2025', 'to': 'Nov 2025'}
        self.assertIn('Faded by about 27%', self.facts(variability=v)['change']['headline'])
        v['delta_mag'] = 0.03
        self.assertNotIn('change', self.facts(variability=v))

    def test_limits_state_the_motion_floor_and_asteroids(self):
        m = {'shift_spherex_pixels': 26.6, 'measured_arcsec_per_yr': 10.40, 'expected_arcsec_per_yr': 10.39,
             'shift_arcsec': 163.5, 'from_year': 2010.5, 'to_year': 2026.2}
        lim = evidence.insights(target(motion=m, spherex_visits=[{'year': 2025.66}, {'year': 2026.20}]))['limits']
        self.assertTrue(any('faster than 0.78″ per year' in x for x in lim))
        self.assertTrue(any('SPHEREx alone covers only 6 months' in x for x in lim))
        self.assertTrue(any('asteroids' in x for x in lim))

    def test_insights_do_not_mutate_input(self):
        t = target(motion=motion())
        original = repr(t)
        evidence.insights(t)
        self.assertEqual(repr(t), original)


if __name__ == '__main__':
    unittest.main()
