"""Tests for pipeline/starquake.py on synthetic light curves (offline), plus the committed Kepler results.

Run from the repository root:  .venv/bin/python -m unittest tests/test_starquake.py -v
"""
import json
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import starquake as Q  # noqa: E402

DT = 58.85


def synthetic(numax=2500.0, dnu=110.0, days=40, seed=0, trend=True, gaps=True):
    """Light curve (ppm) with solar-like modes on the asymptotic pattern, a slow 0.1 mHz trend, noise and gaps."""
    rng = np.random.default_rng(seed)
    t = np.arange(0, days * 86400, DT)
    y = np.zeros_like(t)
    sigma = 0.66 * numax ** 0.88 / 2.355
    for n in range(int((numax - 3 * sigma) / dnu), int((numax + 3 * sigma) / dnu) + 1):
        for l, vis in ((0, 1.0), (1, 1.5), (2, 0.5)):
            nu = dnu * (n + l / 2 + 1.4) - l * (l + 1) * dnu / 100
            a = 3.0 * np.sqrt(vis) * np.exp(-((nu - numax) ** 2) / (4 * sigma ** 2))
            y += a * np.sin(2 * np.pi * nu * 1e-6 * t + rng.uniform(0, 2 * np.pi))
    if trend:
        y += 200 * np.sin(2 * np.pi * 0.1e-3 * t)          # the "fake 0.1 mHz trend" the band-pass must remove
    y += rng.normal(0, 2.0, t.size)
    keep = np.ones(t.size, bool)
    if gaps:
        keep[1000:1010] = False                             # short gap (~10 min): interpolated
        keep[20000:22000] = False                           # long gap (~1.4 days): left silent
    return t[keep], y[keep]


class ProcessingTests(unittest.TestCase):
    def test_measures_numax_and_dnu(self):
        for numax, dnu in ((2500.0, 110.0), (1200.0, 61.0), (3600.0, 150.0)):
            t, y = synthetic(numax, dnu)
            g, yy, _, _ = Q.regrid(t, y, DT)
            nu, psd = Q.power_spectrum(yy, DT)
            m = Q.measure(nu, psd)
            self.assertAlmostEqual(m["dnu"], dnu, delta=0.02 * dnu, msg=(numax, dnu, m["dnu"]))
            self.assertAlmostEqual(m["numax"], numax, delta=0.08 * numax, msg=(numax, dnu, m["numax"]))

    def test_bandpass_removes_the_slow_trend(self):
        t, y = synthetic(trend=True, gaps=False)
        _, yy, _, _ = Q.regrid(t, y, DT)
        bp, (lo, hi) = Q.bandpass(yy, DT, 2500.0)
        nu, before = Q.power_spectrum(yy, DT)
        _, after = Q.power_spectrum(bp, DT)
        near = (nu > 50) & (nu < 150)                       # around the 100 uHz trend
        self.assertLess(after[near].sum(), 1e-4 * before[near].sum())
        band = (nu > 2300) & (nu < 2700)
        self.assertGreater(after[band].sum(), 0.9 * before[band].sum())   # the modes survive

    def test_short_gaps_interpolated_long_gaps_silent(self):
        t, y = synthetic(gaps=True)
        g, yy, filled, gap = Q.regrid(t, y, DT)
        self.assertTrue(np.all(np.isfinite(yy)))
        self.assertAlmostEqual(float(np.median(np.diff(g))), DT, places=6)
        self.assertGreaterEqual(int(filled.sum()), 9)       # the 10-point gap is filled
        self.assertGreater(int(gap.sum()), 1900)            # the 2000-point gap is not invented
        self.assertTrue(np.all(yy[gap] == 0))

    def test_clean_cuts_outliers_but_keeps_oscillations(self):
        t, y = synthetic(gaps=False, trend=False)
        y = y.copy(); y[500] += 1000; y[5000] -= 800
        t2, y2 = Q.clean(t, y)
        self.assertNotIn(t[500], t2); self.assertNotIn(t[5000], t2)      # both spikes are gone
        self.assertLess(len(y) - len(y2) - 2, 1e-4 * len(y))           # and almost nothing else (< 0.01%)

    def test_speed_up_maps_3mHz_to_126Hz(self):
        self.assertAlmostEqual(3e-3 * Q.SPEEDUP, 126.0)
        t = np.arange(0, 10 * 86400, DT)
        y = np.sin(2 * np.pi * 3e-3 * t)
        audio, native, _ = Q.to_audio(y, DT, seconds=15)
        self.assertAlmostEqual(native, Q.SPEEDUP / DT)
        f = np.fft.rfftfreq(len(audio), 1 / Q.AUDIO_FS)
        self.assertAlmostEqual(f[np.argmax(np.abs(np.fft.rfft(audio)))], 126.0, delta=0.2)

    def test_read_keeps_the_quarter_of_every_file(self):
        import tempfile
        from astropy.io import fits
        paths = []
        with tempfile.TemporaryDirectory() as d:
            for i, q in enumerate((6, 7)):
                cols = [fits.Column(name="TIME", format="D", array=np.arange(5.0) + 10 * i),
                        fits.Column(name="PDCSAP_FLUX", format="E", array=np.full(5, 100.0)),
                        fits.Column(name="SAP_QUALITY", format="J", array=np.zeros(5, int))]
                p = Path(d) / f"f{i}.fits"
                fits.HDUList([fits.PrimaryHDU(header=fits.Header({"QUARTER": q, "KEPLERID": 1})),
                              fits.BinTableHDU.from_columns(cols)]).writeto(p)
                paths.append(p)
            t, f, hdr = Q.read(paths)
        self.assertEqual(hdr["months"], [6, 7])
        self.assertEqual(len(t), 10)


@unittest.skipUnless((ROOT / "app" / "data" / "starquake").exists(), "no committed Kepler results")
class KeplerResultTests(unittest.TestCase):
    """Real data: what we measure matches the published Kepler LEGACY values (Lund et al. 2017)."""

    def test_measured_matches_published(self):
        files = sorted((ROOT / "app" / "data" / "starquake").glob("kic*.json"))
        self.assertGreaterEqual(len(files), 4)
        for f in files:
            r = json.loads(f.read_text())
            self.assertLess(abs(r["agreement"]["dnu_pct"]), 2.0, r["name"])
            self.assertLess(abs(r["agreement"]["numax_pct"]), 6.0, r["name"])
            self.assertTrue((ROOT / "app" / r["audio"]).exists())

    def test_smaller_denser_stars_sound_higher(self):
        rs = [json.loads(f.read_text()) for f in (ROOT / "app" / "data" / "starquake").glob("kic*.json")]
        rs.sort(key=lambda r: r["dnu"])                     # dnu grows with mean density
        self.assertEqual([r["pitch_hz"] for r in rs], sorted(r["pitch_hz"] for r in rs))


if __name__ == "__main__":
    unittest.main()
