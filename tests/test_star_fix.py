"""Tests for pipeline/star_fix.py: the maths round trip, then the sample photos in star_image/.

Run from the repository root:  .venv\\Scripts\\python.exe -m unittest discover -s tests -p "test_star_fix.py"
The photo tests skip (they do not fail) when a photo or the solver package is missing.
Only distances are checked and printed, never the GPS position of a sample photo.
"""
import importlib.util
import io
import math
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np
import astropy.units as u
from astropy.coordinates import AltAz, EarthLocation, SkyCoord
from astropy.time import Time
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import star_fix as sf  # noqa: E402


def km(a, b):
    (la1, lo1), (la2, lo2) = [(math.radians(p[0]), math.radians(p[1])) for p in (a, b)]
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def zenith(lat, lon, utc):
    """The zenith of a place as an ICRS unit vector, by a path that position() does not use (AltAz, alt 90)."""
    place = EarthLocation(lat=lat * u.deg, lon=lon * u.deg)
    z = SkyCoord(alt=90 * u.deg, az=0 * u.deg, frame=AltAz(obstime=Time(utc), location=place)).icrs
    return np.array([math.cos(z.dec.rad) * math.cos(z.ra.rad), math.cos(z.dec.rad) * math.sin(z.ra.rad), math.sin(z.dec.rad)])


def random_rotation(rng):
    q, r = np.linalg.qr(rng.normal(size=(3, 3)))
    q = q * np.sign(np.diag(r))
    if np.linalg.det(q) < 0:
        q[:, 0] *= -1
    return q


def gravity(up, orient):
    """The gravity vector a phone reports when "up" in the upright picture frame is `up` (design table 7.1, inverted)."""
    X, Y, Z = -up                        # "down" in the picture frame: right, down, forward (forward = -z of the device)
    gx, gy = {6: (X, -Y), 1: (-Y, -X), 3: (Y, X), 8: (-X, Y)}[orient]
    return [gx, gy, -Z]


class Position(unittest.TestCase):
    def test_round_trip_for_every_orientation(self):   # A1
        rng = np.random.default_rng(7)
        for lat, lon in ((-38.5, 145.2), (47.6, -122.3), (0.3, 10.0)):
            for utc in ("2026-06-14T08:20:51", "2023-11-25T20:43:26"):
                z = zenith(lat, lon, utc)
                for orient in (1, 3, 6, 8):
                    for _ in range(3):
                        R = random_rotation(rng)
                        p = sf.position(R, gravity(R.T @ z, orient), orient, utc)
                        d = km((p["lat"], p["lon"]), (lat, lon))
                        self.assertLess(d, 2, f"{lat}, {lon} at {utc}, orientation {orient}: {d:.2f} km")


PHILLIP_ISLAND = (-38.5, 145.2)   # the only public true place (owner input); never write a sample photo's own GPS here


def photo(name):
    p = ROOT / "star_image" / name
    if not p.exists():
        raise unittest.SkipTest(f"star_image/{name} is not here")
    if importlib.util.find_spec("tetra3") is None:
        raise unittest.SkipTest("cedar-solve (tetra3) is not installed")
    return p.read_bytes()


class Photos(unittest.TestCase):
    def test_carina_photo_lands_near_phillip_island(self):   # A2
        r = sf.star_fix(photo("20260614_082051102_iOS.heic"))
        self.assertEqual(r["status"], "fix")
        self.assertLess(km((r["lat"], r["lon"]), PHILLIP_ISLAND), 100)
        self.assertEqual(r["sky"]["constellation"], "Carina")
        self.assertGreaterEqual(r["sky"]["matches"], 8)
        self.assertEqual((r["utc"], r["local"], r["model"], r["warnings"]),
                         ("2026-06-14T08:20:51Z", "2026-06-14T18:20:51+10:00", "iPhone 17 Pro", []))
        self.assertEqual(sorted(r["gps"]), ["lat", "lon"])

    def test_photo_held_past_the_zenith_uses_the_stored_orientation(self):   # A3: a guessed orientation gives 7535 km
        r = sf.star_fix(photo("20231125_204326416_iOS.heic"))
        self.assertEqual(r["status"], "fix")
        self.assertLess(km((r["lat"], r["lon"]), (r["gps"]["lat"], r["gps"]["lon"])), 150)

    def test_weak_false_solve_of_a_recompressed_photo_is_refused(self):   # A17
        # A JPEG copy (quality 92) of this portrait photo loses the sigma 3 solve; a weak false match (15 stars,
        # RMSE 516", Prob 2e-7) then put it 2800 km off. The quality gate must skip that solve and find the right one.
        data = photo("20260614_081100956_iOS.heic")
        heic = Image.open(io.BytesIO(data))
        m = sf.read_meta(heic)
        jpeg = io.BytesIO()
        heic.convert("RGB").save(jpeg, "JPEG", quality=92)
        s = sf.solve(Image.open(jpeg))
        self.assertIn("R", s)
        p = sf.position(s["R"], m["g"], m["orient"], m["utc"])
        self.assertLess(km((p["lat"], p["lon"]), (m["gps"]["lat"], m["gps"]["lon"])), 150)
        r = sf.star_fix(data)
        self.assertEqual(r["status"], "fix")
        self.assertLess(km((r["lat"], r["lon"]), (r["gps"]["lat"], r["gps"]["lon"])), 150)

    def test_small_photo_is_flagged(self):   # below 1600 px on the long side the matches fall to 8-16
        im = Image.open(io.BytesIO(photo("20260614_082051102_iOS.heic"))).convert("RGB")
        im.thumbnail((1200, 1200))
        small = io.BytesIO()
        im.save(small, "JPEG", quality=95)
        r = sf.star_fix(small.getvalue())
        self.assertIn("small_photo", r["warnings"], r["status"])
        self.assertNotIn("small_photo", sf.star_fix(photo("20260614_082051102_iOS.heic"))["warnings"])

    def test_twilight_photo_has_too_few_stars(self):   # A4
        r = sf.star_fix(photo("20231125_211246181_iOS.heic"))
        self.assertEqual(r["status"], "no_solve")
        self.assertGreater(r["stars"], 0)

    def test_photo_saved_again_without_its_data_still_finds_the_stars(self):   # A5, second half
        im = Image.open(io.BytesIO(photo("20260614_082051102_iOS.heic"))).convert("RGB")
        jpeg = io.BytesIO()
        im.save(jpeg, "JPEG", quality=95)   # no exif= argument: the copy has no EXIF at all
        r = sf.star_fix(jpeg.getvalue())
        self.assertEqual(r["status"], "sky_only")
        self.assertEqual(r["sky"]["constellation"], "Carina")
        self.assertIn("gravity", r["missing"])
        self.assertIn("time", r["missing"])
        self.assertNotIn("utc", r)


class Files(unittest.TestCase):
    def test_random_bytes_are_not_a_photo(self):   # A5, first half
        noise = np.random.default_rng(1).integers(0, 256, 5000, dtype=np.uint8).tobytes()
        self.assertEqual(sf.star_fix(noise), {"status": "bad_file"})
        self.assertEqual(sf.star_fix(b""), {"status": "bad_file"})

    def test_command_reads_stdin_and_prints_one_json_line(self):   # the way server.js calls it
        p = subprocess.run([sys.executable, str(ROOT / "pipeline" / "star_fix.py")], input=b"not a photo",
                           capture_output=True, cwd=ROOT, timeout=120)
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout.decode("ascii").strip().splitlines(), ['{"status": "bad_file"}'])


if __name__ == "__main__":
    unittest.main()
