"""Tests for the mover vetting rules. Run: python3 -m unittest discover -s tests -p 'test_vet.py' -v"""
import importlib.util
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / 'pipeline' / 'vet.py'
spec = importlib.util.spec_from_file_location('wanderers_vet', MODULE)
vet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vet)


def mover(x0=40, y0=40, x1=80, y1=80, **changes):
    m = {'x0': x0, 'y0': y0, 'x1': x1, 'y1': y1, 'snr': 20.0, 'arcsec_per_yr': 2.0, 'ra': 10.0, 'dec': 20.0,
         'year': 2025.5, 'pmra': 1500.0, 'pmdec': -1300.0, 'gaia_source_id': None, 'explained_by_gaia': False}
    m.update(changes)
    return m


def field(movers, **changes):
    t = {'grid': {'npix': 150, 'arcsec_per_pix': 2.0},
         'frames': {'w2': [{'png': 'old.png', 'mission': 'WISE'}, {'png': 'new.png', 'mission': 'SPHEREx'}]},
         'ghosts': {'old.png': [], 'new.png': []}, 'movers_experimental': movers,
         'motion': {'shift_arcsec': 130.0},
         'track': [{'year': 2010.5, 'mission': 'WISE', 'ch': 'w2', 'x': 20.0, 'y': 100.0},
                   {'year': 2025.5, 'mission': 'SPHEREx', 'ch': 'w2', 'x': 60.0, 'y': 110.0}]}
    t.update(changes)
    return t


def one(t, lookups=None):
    return vet.grade(t, lookups)['items'][0]


class VetTests(unittest.TestCase):
    def test_target_needs_both_ends_on_its_path(self):
        c = vet.grade(field([mover(20.5, 100.5, 60.5, 109.5)]))
        self.assertEqual(c['items'][0]['status'], 'target')
        self.assertTrue(c['target_recovered'])

    def test_one_end_on_the_target_is_a_wrong_pairing(self):
        c = vet.grade(field([mover(20.5, 100.5, 115, 29)]))
        self.assertEqual(c['items'][0]['status'], 'rejected')
        self.assertIn('Wrong pairing', c['items'][0]['reason'])
        self.assertIs(c['target_recovered'], False)

    def test_gaia_explained_is_known(self):
        self.assertEqual(one(field([mover(explained_by_gaia=True, gaia_source_id=42)]))['status'], 'known')

    def test_edge_is_rejected(self):
        self.assertEqual(one(field([mover(x1=143)]))['status'], 'rejected')
        self.assertEqual(one(field([mover(y0=5)]))['status'], 'rejected')

    def test_end_on_a_static_gaia_star_is_rejected(self):
        g = [[80.5, 79.5, 15.0]]
        self.assertEqual(one(field([mover()], ghosts={'old.png': g, 'new.png': g}))['status'], 'rejected')
        # a Gaia star that is under the end in one epoch only has moved, so it does not explain the dot away
        self.assertEqual(one(field([mover()], ghosts={'old.png': [], 'new.png': g}))['status'], 'candidate')

    def test_other_2010_and_neowise_frames_do_not_count_as_the_new_epoch(self):
        # A Gaia star under the 2010 end only in 2010 has moved away: the W1 2010 frame and the NEOWISE
        # frames (2014-2024) must not make it look like the same star sits there "in both epochs".
        frames = {'w2': [{'png': 'old.png', 'mission': 'WISE'}, {'png': 'neo.png', 'mission': 'NEOWISE'},
                         {'png': 'new.png', 'mission': 'SPHEREx'}],
                  'w1': [{'png': 'w1old.png', 'mission': 'WISE'}]}
        at_start = [[40.5, 39.5, 15.0]]
        ghosts = {'old.png': at_start, 'w1old.png': at_start, 'neo.png': [[41.5, 40.0, 15.0]], 'new.png': [[60.0, 60.0, 15.0]]}
        self.assertEqual(one(field([mover()], frames=frames, ghosts=ghosts))['status'], 'candidate')
        # a NEOWISE position of the mission target is not where SPHEREx saw it
        track = field([])['track'] + [{'year': 2018.0, 'mission': 'NEOWISE', 'ch': 'w2', 'x': 80.0, 'y': 80.0}]
        self.assertEqual(one(field([mover()], frames=frames, track=track))['status'], 'candidate')

    def test_simbad_static_object_rejects_and_matching_mover_is_known(self):
        static = {0: {'start': [], 'end': [{'name': 'LP 1-1', 'otype': 'PM*', 'pm': 0.19, 'sep': 4.7}]}}
        c = one(field([mover()]), static)
        self.assertEqual(c['status'], 'rejected')
        self.assertIn('LP 1-1', c['reason'])
        moving = {0: {'start': [{'name': 'X', 'otype': 'BD*', 'pm': 2.1, 'sep': 3.0}], 'end': []}}
        self.assertEqual(one(field([mover()]), moving)['status'], 'known')

    def test_survivor_is_an_unconfirmed_candidate_with_warnings(self):
        c = one(field([mover(arcsec_per_yr=9.7, snr=6.5)]), {0: {'start': [], 'end': []}})
        self.assertEqual(c['status'], 'candidate')
        self.assertIn('sceptical', c['reason'])
        self.assertIn('faint', c['reason'])
        self.assertIn('SIMBAD was not checked', one(field([mover()]))['reason'])

    def test_candidates_come_first_and_counts_add_up(self):
        c = vet.grade(field([mover(x1=143), mover()]))
        self.assertEqual([i['status'] for i in c['items']], ['candidate', 'rejected'])
        self.assertEqual((c['found'], c['candidates']), (2, 1))

    def test_no_recovery_question_for_a_target_that_does_not_move(self):
        self.assertIsNone(vet.grade(field([], motion={'shift_arcsec': 0.6}))['target_recovered'])

    def test_start_position_runs_the_motion_backwards(self):
        ra0, dec0 = vet.start_radec(mover(pmra=0.0, pmdec=3600.0, year=2020.5))   # 3.6 arcsec/yr north for 10 years
        self.assertAlmostEqual(dec0, 20.0 - 0.01, places=6)
        self.assertAlmostEqual(ra0, 10.0, places=6)

    def test_grade_does_not_mutate_input(self):
        t = field([mover()])
        before = repr(t)
        vet.grade(t)
        self.assertEqual(repr(t), before)

    def test_shipped_fields_are_graded_and_consistent(self):
        import json
        for f in sorted((MODULE.parents[1] / 'app' / 'data').glob('*/target.json')):
            t = json.loads(f.read_text(encoding='utf-8'))
            ch = t['changes']
            self.assertEqual(ch['found'], len(t['movers_experimental']), f.parent.name)
            self.assertEqual(ch['candidates'], sum(c['status'] == 'candidate' for c in ch['items']), f.parent.name)
            self.assertTrue(all(c['simbad_checked'] for c in ch['items']), f.parent.name)


if __name__ == '__main__':
    unittest.main()
