"""Offline tests for pipeline/fetch.py helpers (no network).

Run from the repository root:  .venv/bin/python -m unittest tests/test_fetch.py -v
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import fetch  # noqa: E402


class RefSummaryTests(unittest.TestCase):
    def test_gaia_source_without_proper_motion_does_not_crash(self):
        # A typed position can match a Gaia DR3 two-parameter source (position only): resolve() stores
        # pmra/pmdec/parallax as None, and the log line must not stop the download there.
        ref = {"source": "Gaia DR3", "ra": 10.0, "dec": 20.0, "pmra": None, "pmdec": None, "parallax": None}
        self.assertIn("pm=(0,0) mas/yr; 7 Gaia field stars", fetch.ref_summary(ref, 7))

    def test_summary_with_motion(self):
        ref = {"source": "Gaia DR3", "ra": 269.4485025, "dec": 4.7394201, "pmra": -801.55, "pmdec": 10362.39}
        self.assertEqual(fetch.ref_summary(ref, 3),
                         "   reference: Gaia DR3 ra=269.44850 dec=4.73942 pm=(-802,10362) mas/yr; 3 Gaia field stars")


class StarDatabaseTests(unittest.TestCase):
    def test_target_without_proper_motion_is_added_to_the_database(self):
        import json
        import tempfile
        import stardb
        import targets
        ref = {"source": "Gaia DR3", "epoch": 2016.0, "source_id": 1, "ra": 10.0, "dec": 20.0,
               "pmra": None, "pmdec": None, "parallax": None}
        old_root = stardb.ROOT
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "app" / "data" / "test_2p").mkdir(parents=True)
            (Path(d) / "app" / "data" / "test_2p" / "target.json").write_text(json.dumps({"reference": ref}))
            targets.TARGETS["test_2p"] = {"name": "Two-parameter test"}
            try:
                stardb.ROOT = Path(d)
                out = stardb.wanderers_targets([{"key": "hip1", "ra": 200.0, "dec": -40.0, "aliases": []}])
            finally:
                stardb.ROOT = old_root
                del targets.TARGETS["test_2p"]
        extra = next(s for s in out if s["key"] == "wanderers_test_2p")
        self.assertIsNone(extra["pmra"])
        self.assertIsNone(extra["dist_pc"])

    def test_negative_parallax_gives_no_distance(self):
        import json
        import tempfile
        import stardb
        import targets
        import link_paths
        ref = {"source": "Gaia DR3", "epoch": 2016.0, "source_id": 1, "ra": 10.0, "dec": 20.0,
               "pmra": 5.0, "pmdec": -3.0, "parallax": -0.8}         # a noisy faint source: parallax below zero
        old_root, old_data = stardb.ROOT, link_paths.DATA
        with tempfile.TemporaryDirectory() as d:
            data = Path(d) / "app" / "data"
            (data / "neg").mkdir(parents=True)
            (data / "stars" / "pred").mkdir(parents=True)
            (data / "neg" / "target.json").write_text(json.dumps({"reference": ref}))
            (data / "index.json").write_text(json.dumps([{"id": "neg", "name": "Faint thing", "ra": 10.0, "dec": 20.0}]))
            (data / "stars.json").write_text("[]")
            (data / "stars" / "index.json").write_text(json.dumps({"stars": []}))
            targets.TARGETS["neg"] = {"name": "Faint thing"}
            try:
                stardb.ROOT, link_paths.DATA = Path(d), data
                db = stardb.wanderers_targets([{"key": "hip1", "ra": 200.0, "dec": -40.0, "aliases": []}])
                link_paths.main()
                paths = json.loads((data / "paths.json").read_text())
            finally:
                stardb.ROOT, link_paths.DATA = old_root, old_data
                del targets.TARGETS["neg"]
        self.assertIsNone(next(s for s in db if s["key"] == "wanderers_neg")["dist_pc"])
        self.assertIsNone(paths["neg"]["state"]["plx"])


if __name__ == "__main__":
    unittest.main()
