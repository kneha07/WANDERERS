"""Mover pairing on synthetic images. Needs the pipeline packages (numpy, scipy, astropy, reproject):
    .venv/Scripts/python.exe -m unittest tests.test_movers -v"""
import sys
import unittest
from pathlib import Path

import numpy as np
from astropy.coordinates import SkyCoord

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline'))
import analyze  # noqa: E402

NPIX = 150


def sky(stars, seed):
    """Unit-noise image with Gaussian stars [(x, y, peak)]."""
    yy, xx = np.indices((NPIX, NPIX))
    img = np.random.default_rng(seed).normal(0, 1, (NPIX, NPIX))
    for x, y, peak in stars:
        img += peak * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 1.5 ** 2))
    return img


class PairingTests(unittest.TestCase):
    # The two ways the target was lost on real data: its SPHEREx end sits next to a background star
    # (WISE 0855), and its peak brightness differs more than 4x between WISE and SPHEREx (Barnard).
    static = [(30, 120, 60), (120, 30, 60), (100, 102, 25)]
    old = sky(static + [(40, 70, 300)], 1)               # target in 2010
    new = sky(static + [(100, 100, 25)], 2)              # target in 2025, 2 px from a static star
    path = (40.0, 70.0, 100.0, 100.0)
    gw = analyze.grid_wcs(SkyCoord(133.8, -7.2, unit='deg'), NPIX)

    def movers(self, paths=()):
        return analyze.find_movers(self.old, self.new, 2010.5, 2025.5, self.gw, [], NPIX, (), paths)

    def test_free_pairing_alone_loses_the_target(self):
        self.assertEqual(self.movers(), [])

    def test_known_path_recovers_the_target(self):
        m = self.movers([self.path])
        self.assertEqual(len(m), 1)
        self.assertAlmostEqual(m[0]['x0'], 40, delta=1)
        self.assertAlmostEqual(m[0]['y0'], 70, delta=1)
        self.assertAlmostEqual(m[0]['x1'], 100, delta=2)
        self.assertAlmostEqual(m[0]['y1'], 100, delta=2)

    def test_static_star_on_both_path_ends_is_not_a_mover(self):
        m = analyze.find_movers(self.old, self.new, 2010.5, 2025.5, self.gw, [], NPIX, (), [(30.0, 120.0, 120.0, 30.0)])
        self.assertEqual(m, [])


if __name__ == '__main__':
    unittest.main()
