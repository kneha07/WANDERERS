"""Tests for linking the prepared targets into the star search list (pipeline/make_stars.py, pipeline/link_paths.py).

Run from the repository root:  .venv/bin/python -m unittest tests/test_link_paths.py -v
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import make_stars  # noqa: E402

DATA = ROOT / "app" / "data"


def rows():
    return [["Sirius", "Alpha Canis Majoris|HIP 32349", 101.28716, -16.71612, -1.44, "A0m...", 8.6, "Canis Major", "V"],
            ["Proxima Centauri", "Gliese 551|HIP 70890", 217.43977, -62.67948, 11.01, "M5Ve", 4.23, "Centaurus", "VN"],
            ["R Draconis", "", 248.16734, 66.75501, None, "", None, "", ""]]


class LinkTargetTests(unittest.TestCase):
    def test_links_by_name_and_position_and_adds_missing_targets(self):
        out = make_stars.link_targets(rows(), [
            {"id": "pos_217p4398_s62p6795", "name": "Proxima Centauri", "ra": 217.387, "dec": -62.6756},
            {"id": "pos_162p3288_s53p3194", "name": "Luhman 16", "ra": 162.30522, "dec": -53.3178}])
        prox = next(r for r in out if r[0] == "Proxima Centauri")
        self.assertEqual(prox[8], "VNW:pos_217p4398_s62p6795")
        luh = next(r for r in out if r[0] == "Luhman 16")
        self.assertEqual(luh[8], "W:pos_162p3288_s53p3194")
        self.assertEqual([r[0] for r in out], ["Sirius", "Proxima Centauri", "R Draconis", "Luhman 16"])   # by magnitude

    def test_running_again_changes_nothing(self):
        idx = [{"id": "pos_217p4398_s62p6795", "name": "Proxima Centauri", "ra": 217.387, "dec": -62.6756},
               {"id": "x1", "name": "Luhman 16", "ra": 162.3, "dec": -53.3}]
        once = make_stars.link_targets(rows(), idx)
        twice = make_stars.link_targets(json.loads(json.dumps(once)), idx)
        self.assertEqual(once, twice)

    def test_a_word_inside_another_name_is_not_a_match(self):
        # an unnamed typed position ("RA ...") next to R Draconis must not be taken for it ("ra" is in "draconis")
        out = make_stars.link_targets(rows(), [{"id": "pos_x", "name": "RA 248.1673, Dec +66.7550", "ra": 248.1673, "dec": 66.755}])
        self.assertEqual(next(r for r in out if r[0] == "R Draconis")[8], "")
        self.assertEqual(out[-1][0], "RA 248.1673, Dec +66.7550")

    def test_no_empty_alias_when_a_name_is_added(self):
        out = make_stars.link_targets(rows(), [{"id": "r_dra", "name": "R Draconis A", "ra": 248.16734, "dec": 66.75501}])
        self.assertEqual(next(r for r in out if r[0] == "R Draconis")[1], "R Draconis A")

    def test_common_names_are_added_once(self):
        out = [["Rigil Kentaurus", "Alpha 1 Centauri|HIP 71683", 219.9, -60.8, -0.01, "G2V", 4.3, "Centaurus", "N"],
               ["Luhman 16", "", 162.3, -53.3, None, "", None, "", "W:pos_162p3288_s53p3194"]]
        once = make_stars.add_names(json.loads(json.dumps(out)))
        self.assertEqual(once[0][1].split("|")[:2], ["Alpha 1 Centauri", "HIP 71683"])     # existing names stay first
        self.assertIn("Alpha Centauri", once[0][1].split("|"))
        self.assertIn("WISE 1049-5319", once[1][1].split("|"))
        self.assertEqual(make_stars.add_names(json.loads(json.dumps(once))), once)


@unittest.skipUnless((DATA / "stars.json").exists(), "no committed star list")
class ShippedListTests(unittest.TestCase):
    def test_every_prepared_target_can_be_found_by_name(self):
        stars = json.loads((DATA / "stars.json").read_text(encoding="utf-8"))
        linked = {}
        for r in stars:
            for tid in r[8].split("W:")[1:]:
                linked.setdefault(tid, []).append(r[0])
        for t in json.loads((DATA / "index.json").read_text()):
            self.assertEqual(len(linked.get(t["id"], [])), 1, t["name"])
            self.assertEqual(linked[t["id"]][0].lower(), t["name"].lower())

    def test_names_people_type_are_in_the_list(self):
        # the page matches names that start with what was typed (app/search.js)
        stars = json.loads((DATA / "stars.json").read_text(encoding="utf-8"))
        names = [n.lower() for r in stars for n in [r[0], *(r[1].split("|") if r[1] else [])]]
        for q in ("luhman", "luhman 16", "wise 1049", "alpha cen", "alpha centauri", "eps indi", "epsilon indi", "proxima"):
            self.assertTrue(any(n.startswith(q) for n in names), q)


if __name__ == "__main__":
    unittest.main()
