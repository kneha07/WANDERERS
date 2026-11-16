"""Offline tests for pipeline/spherex_releases.py, fetch.py's release list and the spherex-sync workflow (no network).

IRSA answers come from tests/fixtures/spherex_releases/ (hand-written in the shape of IRSA TAP answers; IRSA answered
502 when they were written). spherex_qr4 in those fixtures is hypothetical, to test a new release appearing.

Run from the repository root:  .venv/bin/python -m pytest -q tests/test_spherex_releases.py
"""
import importlib
import json
import os
import re
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import spherex_releases as sr  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "spherex_releases"
WORKFLOW = ROOT / ".github" / "workflows" / "spherex-sync.yml"
NOW = "2026-11-15T12:00:00Z"
LATER = "2026-11-22T12:00:00Z"


def no_git():
    return None


def fixture(name):
    return (FIX / name).read_bytes()


REAL_DISCOVER = sr.discover
REAL_DISCOVER_S3 = sr.discover_s3


def canned(name):
    """A fake IRSA that answers with a fixture through the normal discover() path."""
    return lambda: REAL_DISCOVER(list_collections=lambda: fixture(name), tap_get=None, timeout=5)


def down():
    raise sr.IrsaUnavailable("IRSA TAP answered HTTP 502")


def s3_down():
    raise OSError("S3 listing: connection refused")


@pytest.fixture(autouse=True)
def no_bucket(monkeypatch):
    """The command line lists the S3 bucket when IRSA is down; these tests never touch the network, so by default
    the bucket is down too (tests of the S3 fallback pass their own fake)."""
    monkeypatch.setattr(sr, "discover_s3", lambda *a, **k: s3_down())


def make_target(data_dir, tid, dates=(), frames=None, raw=None):
    d = Path(data_dir) / tid
    d.mkdir(parents=True, exist_ok=True)
    if raw is not None:
        (d / "target.json").write_text(raw)
        return
    t = {"id": tid, "name": tid.title(), "kind": "test", "story": "explore",
         "metadata": [{"image": f"img{i}", "date": x} for i, x in enumerate(dates)], "frames": frames or {}}
    (d / "target.json").write_text(json.dumps(t))


@pytest.fixture
def data(tmp_path):
    dd = tmp_path / "app" / "data"
    make_target(dd, "alpha", ["2025-08-15 20:46", "2026-03-22 08:47"])
    make_target(dd, "beta", ["2025-05-01 01:00", "2026-07-21 10:38"])
    return dd


@pytest.fixture
def status_file(tmp_path):
    return tmp_path / "spherex_release.json"


def names(entries):
    return [e["name"] for e in entries]


# ---------------------------------------------------------------- parsing IRSA answers --------------------------

def test_votable_answer_gives_releases_oldest_first():
    releases, other = sr.parse_collections(fixture("irsa_tap_collections.xml"))
    assert names(releases) == ["spherex_dr1", "spherex_qr3"]


def test_votable_answer_keeps_deep_and_cube_collections_apart():
    _, other = sr.parse_collections(fixture("irsa_tap_collections.xml"))
    assert other == ["spherex_dr1_cube", "spherex_dr1_deep", "spherex_qr3_deep"]


def test_csv_answer():
    releases, other = sr.parse_collections(fixture("irsa_tap_collections.csv"))
    assert names(releases) == ["spherex_dr1", "spherex_qr3"]
    assert "spherex_qr3_deep" in other


def test_astropy_table_answer_like_astroquery():
    import numpy as np
    from astropy.table import MaskedColumn, Table
    col = MaskedColumn([b"spherex_qr3", "spherex_dr1", "spherex_dr1_deep", "x"], mask=[False, False, False, True],
                       name="collection")
    releases, other = sr.parse_collections(Table([col]))
    assert names(releases) == ["spherex_dr1", "spherex_qr3"]
    assert other == ["spherex_dr1_deep"]
    assert np.ma.is_masked(col[3])


def test_plain_list_ignores_other_missions_case_and_spaces():
    releases, _ = sr.parse_collections(["wise_allwise", " SPHEREX_QR3 ", "spherex_dr1", "spherex_dr1", None])
    assert names(releases) == ["spherex_dr1", "spherex_qr3"]


def test_html_error_page_is_rejected():
    with pytest.raises(sr.IrsaAnswerError, match="not a VOTable"):
        sr.parse_collections(fixture("irsa_502.html"))


def test_tap_error_answer_is_rejected_with_its_reason():
    with pytest.raises(sr.IrsaAnswerError, match="exceeded the limit"):
        sr.parse_collections(fixture("irsa_tap_error.xml"))


def test_empty_table_is_rejected():
    with pytest.raises(sr.IrsaAnswerError, match="no SPHEREx image release"):
        sr.parse_collections(fixture("irsa_tap_empty.xml"))


def test_answer_without_collection_column_is_rejected():
    with pytest.raises(sr.IrsaAnswerError, match="collection"):
        sr.parse_collections(fixture("irsa_tap_wrong_column.xml"))


@pytest.mark.parametrize("answer", [b"", "  \n", None, 42, b"\x00\x01\x02", "<VOTABLE><broken", "a,b\n1,2\n"])
def test_garbage_is_rejected(answer):
    with pytest.raises(sr.IrsaAnswerError):
        sr.parse_collections(answer)


def test_deep_fields_alone_are_not_a_release():
    with pytest.raises(sr.IrsaAnswerError):
        sr.parse_collections(["spherex_qr3_deep", "spherex_dr1_cube"])


@pytest.mark.parametrize("name", ["spherex_dr1&x=1", "spherex_qr3;drop", "spherex_qr", "spherex_xr3", "spherex_qr1234",
                                  "SPHEREx_qr3", "spherex_qr3\n"])
def test_only_plain_release_names_count(name):
    assert not sr.is_release(name)


def test_unsafe_names_never_reach_other_collections():
    _, other = sr.parse_collections(["spherex_dr1", "spherex_x&y=1", "spherex_deep field"])
    assert other == []


# ---------------------------------------------------------------- order, labels, current ------------------------

def test_order_is_numeric_and_data_releases_come_first():
    assert sr.order_releases(["spherex_qr10", "spherex_qr9", "spherex_dr2", "spherex_qr3", "spherex_dr1", "bad"]) == \
        ["spherex_dr1", "spherex_dr2", "spherex_qr3", "spherex_qr9", "spherex_qr10"]


def test_labels():
    assert sr.release_label("spherex_qr3") == "SPHEREx Quick Release 3"
    assert sr.release_label("spherex_dr1") == "SPHEREx Data Release 1"
    assert sr.release_label("spherex_qr04") == "SPHEREx Quick Release 4"


def test_descriptions_only_for_documented_releases():
    releases, _ = sr.parse_collections(fixture("irsa_tap_new_release.xml"))
    by = {r["name"]: r for r in releases}
    assert "Quick Release 3" in by["spherex_qr3"]["description"]
    assert by["spherex_dr1"]["description_source"].startswith("docs/research/spherex-data-access.md")
    assert "description" not in by["spherex_qr4"]                      # nothing invented for an unknown release
    assert by["spherex_qr4"]["label"] == "SPHEREx Quick Release 4"


def test_current_is_the_newest_release(data, status_file):
    st, _, _ = sr.check(status_file, data_dir=data, now=NOW, ask=canned("irsa_tap_new_release.xml"), git=no_git)
    assert st["current"] == "spherex_qr4" and st["current_label"] == "SPHEREx Quick Release 4"
    assert st["current"] == st["releases"][-1]["name"]


def test_current_with_only_data_releases(data):
    st = sr.build_status(["spherex_dr2", "spherex_dr1"], releases_source="test", now=NOW, data_dir=data, git=no_git)
    assert st["current"] == "spherex_dr2"
    assert names(st["releases"]) == ["spherex_dr1", "spherex_dr2"]


# ---------------------------------------------------------------- new-release detection -------------------------

def test_new_release_is_detected(data, status_file):
    sr.check(status_file, data_dir=data, now=NOW, ask=canned("irsa_tap_collections.xml"), git=no_git)
    st, changed, online = sr.check(status_file, data_dir=data, now=LATER, ask=canned("irsa_tap_new_release.xml"),
                                   git=no_git)
    assert online and changed and st["new_release_available"]
    assert st["new_releases"] == [{"name": "spherex_qr4", "label": "SPHEREx Quick Release 4"}]
    assert st["targets_behind"] == {"alpha": ["spherex_qr4"], "beta": ["spherex_qr4"]}


def test_no_new_release_when_the_list_is_unchanged(data, status_file):
    st, _, _ = sr.check(status_file, data_dir=data, now=NOW, ask=canned("irsa_tap_collections.xml"), git=no_git)
    assert st["new_release_available"] is False and st["new_releases"] == [] and st["targets_behind"] == {}


def test_an_older_release_we_did_not_use_is_not_new():
    behind = sr.releases_behind(["spherex_dr1", "spherex_qr2", "spherex_qr3"], {}, ["spherex_dr1", "spherex_qr3"], ["a"])
    assert behind == {}


def test_targets_behind_come_from_the_cache(data, tmp_path, status_file):
    cache = tmp_path / "cache"
    (cache / "alpha").mkdir(parents=True)
    (cache / "alpha" / "spherex_sia.xml").write_text("<VOTABLE/>")              # searched in DR1 only
    (cache / "alpha" / "allwise_sia.xml").write_text("<VOTABLE/>")              # not SPHEREx
    (cache / "beta").mkdir()
    for f in ("spherex_sia.xml", "spherex_qr3_sia.xml"):
        (cache / "beta" / f).write_text("<VOTABLE/>")
    st, _, _ = sr.check(status_file, data_dir=data, cache_dir=cache, now=NOW, ask=canned("irsa_tap_collections.xml"),
                        git=no_git)
    assert st["searched_releases"] == {"alpha": ["spherex_dr1"], "beta": ["spherex_dr1", "spherex_qr3"]}
    assert st["targets_behind"] == {"alpha": ["spherex_qr3"]}
    assert st["new_release_available"] is True


def test_cache_record_is_carried_to_a_runner_without_cache(data, tmp_path, status_file):
    cache = tmp_path / "cache"
    (cache / "alpha").mkdir(parents=True)
    (cache / "alpha" / "spherex_sia.xml").write_text("<VOTABLE/>")
    sr.check(status_file, data_dir=data, cache_dir=cache, now=NOW, ask=canned("irsa_tap_collections.xml"), git=no_git)
    st, _, _ = sr.check(status_file, data_dir=data, cache_dir=None, now=LATER, ask=canned("irsa_tap_collections.xml"),
                        git=no_git)
    assert st["searched_releases"] == {"alpha": ["spherex_dr1"]}
    # beta has no record of its own, so it counts as built from the releases of the last rebuild (DR1 only)
    assert st["used_releases"] == ["spherex_dr1"]
    assert st["targets_behind"] == {"alpha": ["spherex_qr3"], "beta": ["spherex_qr3"]}


def test_a_target_with_no_record_uses_the_last_rebuild():
    behind = sr.releases_behind(["spherex_dr1", "spherex_qr3"], {"a": ["spherex_dr1", "spherex_qr3"]},
                                ["spherex_dr1"], ["a", "b"])
    assert behind == {"b": ["spherex_qr3"]}


def test_a_retired_release_does_not_hide_a_new_one():
    behind = sr.releases_behind(["spherex_dr1", "spherex_dr2"], {"a": ["spherex_dr1", "spherex_qr3"]}, [], ["a"])
    assert behind == {"a": ["spherex_dr2"]}


# ---------------------------------------------------------------- the check and IRSA failures -------------------

def test_successful_check_writes_the_file(data, status_file):
    st, changed, online = sr.check(status_file, data_dir=data, now=NOW, ask=canned("irsa_tap_collections.xml"),
                                   git=no_git)
    saved = json.loads(status_file.read_text())
    assert online and changed and saved == st
    assert saved["checked"] == NOW and saved["last_attempt"] == NOW and saved["error"] is None
    assert saved["releases_source"] == sr.SOURCE_ASTROQUERY
    assert saved["data_through"] == "2026-07-21" and saved["targets"] == 2


def test_network_failure_keeps_the_last_known_file(data, status_file):
    good, _, _ = sr.check(status_file, data_dir=data, now=NOW, ask=canned("irsa_tap_collections.xml"), git=no_git)
    make_target(data, "gamma", ["2026-10-01 00:00"])                       # new local data: not looked at on failure
    st, changed, online = sr.check(status_file, data_dir=data, now=LATER, ask=down, git=no_git)
    saved = json.loads(status_file.read_text())
    assert (changed, online) == (False, False)
    assert saved == st
    assert saved["last_attempt"] == LATER and "HTTP 502" in saved["error"] and "2026-11-22" in saved["error"]
    assert {k: v for k, v in saved.items() if k not in ("last_attempt", "error")} == \
           {k: v for k, v in good.items() if k not in ("last_attempt", "error")}
    assert saved["checked"] == NOW


def test_failure_with_no_file_writes_what_is_known_locally(data, status_file):
    st, changed, online = sr.check(status_file, data_dir=data, now=NOW, ask=down, git=lambda: "2026-11-15T06:10:33Z")
    assert not online and changed
    assert st["checked"] is None and "failed" in st["error"] and "failed" in st["releases_source"]
    assert names(st["releases"]) == sr.fetch_fallback_releases()
    assert st["data_through"] == "2026-07-21"
    assert st["synced"] == "2026-11-15T06:10:33Z" and st["synced_source"] == sr.SYNCED_FROM_GIT
    assert sr.read_status(status_file) == st


@pytest.mark.parametrize("broken", ["{", "[]", "null", '{"releases": []}', '{"releases": ["not_a_release"]}'])
def test_failure_with_a_broken_file_writes_a_usable_one(data, status_file, broken):
    status_file.write_text(broken)
    st, _, _ = sr.check(status_file, data_dir=data, now=NOW, ask=down, git=no_git)
    assert sr.read_status(status_file) == st and st["current"] == "spherex_qr3"


@pytest.mark.parametrize("fixture_name", ["irsa_502.html", "irsa_tap_empty.xml", "irsa_tap_error.xml",
                                          "irsa_tap_wrong_column.xml"])
def test_a_malformed_answer_keeps_the_last_known_file(data, status_file, fixture_name):
    good, _, _ = sr.check(status_file, data_dir=data, now=NOW, ask=canned("irsa_tap_new_release.xml"), git=no_git)
    st, changed, online = sr.check(status_file, data_dir=data, now=LATER, ask=canned(fixture_name), git=no_git)
    assert (changed, online) == (False, False)
    assert names(st["releases"]) == names(good["releases"]) == ["spherex_dr1", "spherex_qr3", "spherex_qr4"]
    assert st["error"] and st["checked"] == NOW


def test_first_success_after_failures_is_a_change(data, status_file):
    sr.check(status_file, data_dir=data, now=NOW, ask=down, git=no_git)
    _, changed, online = sr.check(status_file, data_dir=data, now=LATER, ask=canned("irsa_tap_collections.xml"),
                                  git=no_git)
    assert changed and online


def test_a_routine_check_is_not_a_change(data, status_file):
    sr.check(status_file, data_dir=data, now=NOW, ask=canned("irsa_tap_collections.xml"), git=no_git)
    st, changed, _ = sr.check(status_file, data_dir=data, now=LATER, ask=canned("irsa_tap_collections.xml"), git=no_git)
    assert not changed and st["checked"] == LATER


def test_new_local_data_is_a_change(data, status_file):
    sr.check(status_file, data_dir=data, now=NOW, ask=canned("irsa_tap_collections.xml"), git=no_git)
    make_target(data, "gamma", ["2026-10-01 00:00"])
    st, changed, _ = sr.check(status_file, data_dir=data, now=LATER, ask=canned("irsa_tap_collections.xml"), git=no_git)
    assert changed and st["data_through"] == "2026-10-01"


def test_write_is_atomic(data, status_file):
    sr.check(status_file, data_dir=data, now=NOW, ask=canned("irsa_tap_collections.xml"), git=no_git)
    assert [p.name for p in status_file.parent.iterdir() if p.name.startswith(status_file.name)] == [status_file.name]


def test_discover_falls_back_to_tap():
    def broken():
        raise RuntimeError("astroquery exploded")
    rel, other, source = sr.discover(list_collections=broken, tap_get=lambda t: fixture("irsa_tap_collections.xml"))
    assert names(rel) == ["spherex_dr1", "spherex_qr3"] and source == sr.SOURCE_TAP


def test_discover_reports_both_failures_without_urls():
    def a():
        raise RuntimeError("502 Server Error: Proxy Error for url: https://irsa.ipac.caltech.edu/TAP/sync?x=1")
    with pytest.raises(sr.IrsaUnavailable) as e:
        sr.discover(list_collections=a, tap_get=lambda t: fixture("irsa_502.html"))
    msg = str(e.value)
    assert "astroquery: 502 Server Error" in msg and "TAP: not a VOTable" in msg and "https://" not in msg


def test_discover_gives_up_after_the_timeout():
    t0 = time.time()
    with pytest.raises(sr.IrsaUnavailable, match="no answer within"):
        sr.discover(list_collections=lambda: time.sleep(5), tap_get=None, timeout=0.2)
    assert time.time() - t0 < 2


def test_cli_exits_cleanly_when_irsa_is_down(data, status_file, tmp_path, monkeypatch):
    monkeypatch.setattr(sr, "discover", down)
    out = tmp_path / "gh_output"
    rc = sr.main(["check", "--file", str(status_file), "--data", str(data), "--github-output", str(out)])
    assert rc == 0 and sr.read_status(status_file)["error"]
    assert out.read_text().splitlines() == ["new_release=false", "changed=false", "online=failed", "current=spherex_qr3"]


def test_cli_require_online_fails_when_irsa_is_down(data, status_file, monkeypatch):
    monkeypatch.setattr(sr, "discover", down)
    assert sr.main(["check", "--file", str(status_file), "--data", str(data), "--require-online"]) == 1


def test_cli_reports_a_new_release(data, status_file, tmp_path, monkeypatch):
    out = tmp_path / "gh_output"
    monkeypatch.setattr(sr, "discover", canned("irsa_tap_new_release.xml"))
    assert sr.main(["check", "--file", str(status_file), "--data", str(data), "--github-output", str(out)]) == 0
    lines = out.read_text().splitlines()
    assert "new_release=true" in lines and "changed=true" in lines and "online=ok" in lines


def test_cli_show_title(data, status_file, capsys):
    sr.check(status_file, data_dir=data, now=NOW, ask=canned("irsa_tap_collections.xml"), git=no_git)
    assert sr.main(["show", "--title", "--file", str(status_file)]) == 0
    assert capsys.readouterr().out.strip() == "SPHEREx data: SPHEREx Quick Release 3, data through 2026-07-21"


# ---------------------------------------------------------------- data_through from target data -----------------

def test_data_through_from_image_metadata(data):
    through, by = sr.data_through(data)
    assert through == "2026-07-21" and by == {"alpha": "2026-03-22", "beta": "2026-07-21"}


def test_data_through_from_spherex_frames_when_there_is_no_metadata(tmp_path):
    frames = {"d1": [{"year": 2025.5, "mission": "SPHEREx"}, {"year": 2026.0, "mission": "SPHEREx"}]}
    make_target(tmp_path, "t", frames=frames)
    assert sr.data_through(tmp_path) == ("2026-01-01", {"t": "2026-01-01"})


def test_wise_and_neowise_frames_do_not_count(tmp_path):
    frames = {"w2": [{"year": 2010.5, "mission": "WISE"}, {"year": 2027.0, "mission": "NEOWISE"},
                     {"year": 2025.6, "mission": "SPHEREx"}]}
    make_target(tmp_path, "t", ["2025-08-01 00:00"], frames=frames)
    assert sr.data_through(tmp_path)[0] == "2025-08-07"          # J2025.6 = 2025-08-07 21:36, after the metadata date


def test_odd_values_are_ignored(tmp_path):
    frames = {"d1": [{"year": "soon", "mission": "SPHEREx"}, {"year": None, "mission": "SPHEREx"}, "x"], "d2": "x"}
    make_target(tmp_path, "t", ["2026-02-30 00:00", "not a date", "2026-01-02 03:04"], frames=frames)
    assert sr.data_through(tmp_path)[0] == "2026-01-02"


def test_a_broken_target_file_is_skipped(data):
    make_target(data, "broken", raw="{not json")
    make_target(data, "list", raw="[]")
    through, by = sr.data_through(data)
    assert through == "2026-07-21" and set(by) == {"alpha", "beta"}


def test_no_targets_gives_no_date(tmp_path):
    assert sr.data_through(tmp_path / "nothing") == (None, {})


def test_year_to_date():
    assert str(sr.year_to_date(2026.0)) == "2026-01-01"
    assert str(sr.year_to_date(2000.0)) == "2000-01-01"


@pytest.mark.skipif(not (ROOT / "app" / "data" / "barnard" / "target.json").exists(), reason="target data not present")
def test_data_through_on_the_prepared_targets():
    newest = max(m["date"][:10] for p in (ROOT / "app" / "data").glob("*/target.json")
                 for m in json.loads(p.read_text())["metadata"])
    through, by = sr.data_through(ROOT / "app" / "data")
    assert through == newest and len(by) == len(list((ROOT / "app" / "data").glob("*/target.json")))


# ---------------------------------------------------------------- fetch.py's release list -----------------------

@pytest.fixture(scope="module")
def fetch():
    import fetch as f
    return f


def test_fetch_reads_the_release_order_from_the_file(fetch, tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"releases": [{"name": "spherex_qr3"}, {"name": "spherex_dr1"}, "spherex_qr3"]}))
    assert sr.load_release_names(p, fallback=fetch.FALLBACK_RELEASES) == ["spherex_qr3", "spherex_dr1"]


def test_fetch_falls_back_when_the_file_is_missing(fetch, tmp_path):
    assert sr.load_release_names(tmp_path / "none.json", fallback=fetch.FALLBACK_RELEASES) == \
        ["spherex_dr1", "spherex_qr3"]


@pytest.mark.parametrize("text", ["{", "[]", '"x"', '{"releases": []}', '{"releases": "spherex_dr1"}',
                                  '{"releases": [{"name": "spherex_dr1&COLLECTION=x"}, 7, null]}'])
def test_fetch_falls_back_when_the_file_is_broken(fetch, tmp_path, text):
    p = tmp_path / "s.json"
    p.write_text(text)
    assert sr.load_release_names(p, fallback=fetch.FALLBACK_RELEASES) == fetch.FALLBACK_RELEASES


def test_fetch_module_uses_the_status_file(tmp_path, monkeypatch):
    import fetch as f
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"releases": [{"name": "spherex_dr1"}, {"name": "spherex_qr3"}, {"name": "spherex_qr4"}]}))
    monkeypatch.setattr(sr, "STATUS_FILE", p)
    try:
        assert importlib.reload(f).RELEASES == ["spherex_dr1", "spherex_qr3", "spherex_qr4"]
        p.unlink()
        assert importlib.reload(f).RELEASES == f.FALLBACK_RELEASES == ["spherex_dr1", "spherex_qr3"]
    finally:
        monkeypatch.undo()
        importlib.reload(f)


def test_first_release_listed_wins_for_the_same_exposure(fetch):
    seen = set()
    dr1 = [{"obs_id": "2025W19_1B_0116_1", "energy_bandpassname": "SPHEREx-D3"},
           {"obs_id": "2025W19_1B_0116_1", "energy_bandpassname": "SPHEREx-D4"}]
    qr3 = [{"obs_id": "2025W19_1B_0116_1", "energy_bandpassname": "SPHEREx-D3"},     # in DR1 already: dropped
           {"obs_id": "2026W21_2A_0001_1", "energy_bandpassname": "SPHEREx-D3"},
           {"obs_id": "2026W21_2A_0001_1", "energy_bandpassname": "SPHEREx-D3"}]     # twice in one release: as before, both kept
    assert fetch.first_release_wins(dr1, seen) == [0, 1]
    assert fetch.first_release_wins(qr3, seen) == [1, 2]
    assert len(seen) == 3
    assert fetch.first_release_wins(qr3, seen) == []                                 # a third release adds nothing new


def test_sia_cache_names_match_what_fetch_has_always_written():
    assert sr.sia_cache_name("spherex_dr1") == "spherex_sia.xml"
    assert sr.sia_cache_name("spherex_qr3") == "spherex_qr3_sia.xml"
    for rel in ("spherex_dr1", "spherex_qr3", "spherex_dr2"):
        assert sr.release_of_cache_file(sr.sia_cache_name(rel)) == rel
    assert sr.release_of_cache_file("allwise_sia.xml") is None


def test_the_fallback_list_is_read_from_fetch_py(fetch):
    assert sr.fetch_fallback_releases() == fetch.FALLBACK_RELEASES == ["spherex_dr1", "spherex_qr3"]
    assert "sia_cache_name(rel)" in (ROOT / "pipeline" / "fetch.py").read_text()


def test_fallback_list_survives_a_missing_fetch_py(tmp_path):
    assert sr.fetch_fallback_releases(tmp_path / "nope.py") == sr.LAST_RESORT_RELEASES


# ---------------------------------------------------------------- after a rebuild: synced -----------------------

def test_mark_synced_records_the_time_and_the_rebuilt_targets(data, tmp_path, status_file):
    sr.check(status_file, data_dir=data, now=NOW, ask=canned("irsa_tap_collections.xml"), git=no_git)
    old = time.time() - 3600
    os.utime(data / "beta" / "target.json", (old, old))
    since = sr.iso(__import__("datetime").datetime.fromtimestamp(time.time() - 60, tz=__import__("datetime").timezone.utc))
    cache = tmp_path / "cache"
    for t in ("alpha", "beta"):
        (cache / t).mkdir(parents=True)
        for f in ("spherex_sia.xml", "spherex_qr3_sia.xml"):
            (cache / t / f).write_text("<VOTABLE/>")
    st, rebuilt = sr.mark_synced(status_file, since=since, data_dir=data, cache_dir=cache, now=LATER, git=no_git)
    assert rebuilt == ["alpha"] and st["not_rebuilt"] == ["beta"]
    assert st["synced"] == LATER and "rebuilt 1 of 2" in st["synced_source"]
    assert st["checked"] == NOW and st["last_attempt"] == NOW          # not an IRSA check
    assert st["targets_behind"] == {} and st["new_release_available"] is False


def test_mark_synced_without_a_rebuild_keeps_the_old_time(data, status_file):
    sr.check(status_file, data_dir=data, now=NOW, ask=down, git=lambda: "2026-11-15T06:10:33Z")
    st, rebuilt = sr.mark_synced(status_file, since="2999-01-01T00:00:00Z", data_dir=data, cache_dir=None,
                                 now=LATER, git=no_git)
    assert rebuilt == [] and st["synced"] == "2026-11-15T06:10:33Z"


def test_mark_synced_counts_only_the_targets_named(data, status_file):
    sr.check(status_file, data_dir=data, now=NOW, ask=down, git=no_git)
    st, rebuilt = sr.mark_synced(status_file, since="2000-01-01T00:00:00Z", data_dir=data, cache_dir=None,
                                 now=LATER, git=no_git, only=["beta"])
    assert rebuilt == ["beta"] and st["rebuilt_targets"] == ["beta"] and st["not_rebuilt"] == ["alpha"]
    assert "rebuilt 1 of 2" in st["synced_source"]


def test_target_definition_from_a_gaia_target():
    t = {"name": "Kapteyn's Star", "kind": "Halo star", "story": "explore", "fov_arcsec": 300.0,
         "reference": {"source": "Gaia DR3", "source_id": 4810594479418041856, "ra": 77.9, "dec": -45.0}}
    assert sr.target_definition(t) == {"name": "Kapteyn's Star", "kind": "Halo star", "story": "explore",
                                       "fov_arcsec": 300, "gaia_source_id": 4810594479418041856}


def test_target_definition_from_a_literature_target():
    ref = {"source": "Gaia DR3 5353626573555863424 position (2016.0); motion and parallax from Bedin et al. 2017",
           "epoch": 2016.0, "source_id": None, "ra": 162.3084022, "dec": -53.3180448, "pmra": -2762.0,
           "pmdec": 357.0, "parallax": 501.0}
    d = sr.target_definition({"name": "Luhman 16", "kind": "Brown dwarf pair", "reference": ref})
    assert d["literature"] == {"ra": 162.3084022, "dec": -53.3180448, "epoch": 2016.0, "pmra": -2762.0,
                               "pmdec": 357.0, "parallax": 501.0, "ref": ref["source"]}
    assert "gaia_source_id" not in d


def test_write_target_defs_skips_built_in_and_existing_ones(tmp_path):
    dd, cache = tmp_path / "data", tmp_path / "cache"
    ref = {"source": "Gaia DR3", "source_id": 7, "ra": 1.0, "dec": 2.0}
    for tid in ("barnard", "pos_1_n2", "pos_3_n4"):
        (dd / tid).mkdir(parents=True)
        (dd / tid / "target.json").write_text(json.dumps({"name": tid, "kind": "k", "reference": ref}))
    (cache / "pos_3_n4").mkdir(parents=True)
    (cache / "pos_3_n4" / "target_def.json").write_text('{"keep": true}')
    assert sr.write_target_defs(dd, cache, builtin={"barnard"}) == ["pos_1_n2"]
    assert json.loads((cache / "pos_1_n2" / "target_def.json").read_text())["gaia_source_id"] == 7
    assert json.loads((cache / "pos_3_n4" / "target_def.json").read_text()) == {"keep": True}
    assert not (cache / "barnard").exists()


def test_git_time_is_converted_to_utc():
    class R:
        returncode, stdout = 0, "2026-11-14T22:10:33-08:00\n"
    assert sr.git_last_commit(run=lambda *a, **k: R()) == "2026-11-15T06:10:33Z"


def test_no_git_gives_no_time():
    def boom(*a, **k):
        raise FileNotFoundError("git")
    assert sr.git_last_commit(run=boom) is None


# ---------------------------------------------------------------- the workflow ---------------------------------

@pytest.fixture(scope="module")
def wf():
    import yaml
    return yaml.safe_load(WORKFLOW.read_text())


def triggers(wf):
    return wf.get("on", wf.get(True))       # YAML 1.1 reads a bare `on` key as True


def all_steps(wf):
    return [s for job in wf["jobs"].values() for s in job["steps"]]


def scripts(wf):
    return "\n".join(s.get("run", "") for s in all_steps(wf))


def test_workflow_has_a_weekly_schedule_and_a_manual_run(wf):
    on = triggers(wf)
    cron = on["schedule"][0]["cron"].split()
    assert len(cron) == 5 and cron[2] == "*" and cron[3] == "*" and re.fullmatch(r"[0-6]", cron[4])
    rebuild = on["workflow_dispatch"]["inputs"]["rebuild"]
    assert rebuild["type"] == "boolean" and rebuild["default"] is False


def test_workflow_permissions_are_minimal(wf):
    assert wf["permissions"] == {"contents": "read"}
    assert wf["jobs"]["check"]["permissions"] == {"contents": "read", "pull-requests": "read"}
    assert wf["jobs"]["update"]["permissions"] == {"contents": "write", "pull-requests": "write"}
    assert "write-all" not in WORKFLOW.read_text()
    assert wf["jobs"]["check"]["steps"][0]["with"]["persist-credentials"] is False


def test_workflow_actions_are_pinned(wf):
    uses = [s["uses"] for s in all_steps(wf) if "uses" in s]
    # a full commit SHA: a tag such as v4 can be moved to other code; the YAML comment after it names the tag
    assert uses and all(re.fullmatch(r"actions/(checkout|setup-python)@[0-9a-f]{40}", u) for u in uses)


def test_workflow_never_pushes_to_main(wf):
    pushes = [line.strip() for line in scripts(wf).splitlines() if re.search(r"\bgit\s+push\b", line)]
    assert pushes == ['git push --force origin "HEAD:refs/heads/$BRANCH"']
    assert wf["jobs"]["update"]["env"]["BRANCH"] == "spherex-sync"
    assert "gh pr create" in scripts(wf)


def test_workflow_rebuilds_only_for_a_new_release_or_on_request(wf):
    cond = " ".join(wf["jobs"]["update"]["if"].split())
    assert "inputs.rebuild" in cond and "needs.check.outputs.new_release == 'true'" in cond
    assert "needs.check.outputs.open_pr == 'false'" in cond
    rebuild = next(s for s in wf["jobs"]["update"]["steps"] if s.get("name") == "Rebuild the prepared targets")
    assert rebuild["if"] == "env.REBUILD == 'true'"
    for script in ("spherex_releases.py targets --write-defs", "fetch.py $ids", "analyze.py $ids",
                   "spherex_releases.py synced --since"):
        assert script in rebuild["run"]
    assert "spherex_releases.py check --github-output" in scripts(wf)
    # the update job stops if IRSA is down, so no pull request ever records only a failed check
    assert "spherex_releases.py check --require-online" in "\n".join(s.get("run", "") for s in wf["jobs"]["update"]["steps"])


def test_workflow_scripts_exist(wf):
    for name in set(re.findall(r"pipeline/(\w+\.py)", scripts(wf))):
        assert (ROOT / "pipeline" / name).exists(), name


def test_readme_documents_the_sync():
    readme = (ROOT / "README.md").read_text()
    data = readme[readme.index("## Data (all public)"):readme.index("## Honest limits")]
    assert "spherex-sync.yml" in data and "spherex_releases.py" in data and "spherex_release.json" in data


# ---------------------------------------------------------------- the committed status file ---------------------

@pytest.mark.skipif(not sr.STATUS_FILE.exists(), reason="no status file yet")
def test_the_committed_status_file_is_consistent():
    st = sr.read_status(sr.STATUS_FILE)
    assert st is not None
    rel = names(st["releases"])
    assert rel == sr.order_releases(rel) and all(sr.is_release(n) for n in rel)
    assert st["current"] == rel[-1] and st["current_label"] == sr.release_label(rel[-1])
    assert st["data_through"] == sr.data_through(sr.DATA)[0]
    assert st["checked"] or "failed" in (st["error"] or "")            # never checked: it says the check failed
    assert st["new_release_available"] == bool(st["targets_behind"])
    assert sr.load_release_names(sr.STATUS_FILE) == rel
    assert st.get("checked_via") in (None, sr.VIA_IRSA, sr.VIA_S3)
    if st.get("checked_via") == sr.VIA_S3:
        assert st["s3_listing"]["folders"] and st["releases_source"] == sr.SOURCE_S3


# ---------------------------------------------------------------- the S3 bucket fallback -------------------------

BUCKET_NOW = "2026-11-15T12:00:05Z"


def bucket(folders=("dr1", "qr2", "qr3"), weeks=None):
    """A fake bucket listing, as discover_s3 returns it (no network)."""
    weeks = weeks if weeks is not None else {"dr1": "2026W20_1A", "qr2": "2026W29_2A", "qr3": "2026W40_2A"}
    weeks = {f: w for f, w in weeks.items() if f in folders}
    entries, superseded = sr.releases_from_bucket(folders, weeks)
    return lambda: {"releases": entries, "superseded": superseded, "folders": list(folders),
                    "newest_weeks": weeks, "listed": BUCKET_NOW}


def test_bucket_qr2_is_superseded_by_dr1():
    entries, superseded = sr.releases_from_bucket(["dr1", "qr2", "qr3"], {"qr3": "2026W40_2A"})
    assert names(entries) == ["spherex_dr1", "spherex_qr3"] and superseded == {"spherex_qr2": "spherex_dr1"}
    qr3 = entries[1]
    assert (qr3["newest_week"], qr3["newest_week_label"], qr3["newest_week_ends"]) == \
           ("2026W40_2A", "2026 week 40", "2026-10-04")
    assert "newest_week" not in entries[0]


def test_bucket_qr2_alone_is_still_a_release():
    entries, superseded = sr.releases_from_bucket(["qr2", "qr3"], {})
    assert names(entries) == ["spherex_qr2", "spherex_qr3"] and superseded == {}


def searched_everything(tmp_path, tids=("alpha", "beta")):
    cache = tmp_path / "cache"
    for tid in tids:
        (cache / tid).mkdir(parents=True)
        for f in ("spherex_sia.xml", "spherex_qr3_sia.xml"):
            (cache / tid / f).write_text("<VOTABLE/>")
    return cache


@pytest.mark.parametrize("new", ["qr4", "dr2"])
def test_bucket_a_newer_release_folder_counts_as_new_data(data, status_file, tmp_path, new):
    cache = searched_everything(tmp_path)
    weeks = {"dr1": "2026W20_1A", "qr3": "2026W40_2A", new: "2026W45_1A"}
    st, changed, online = sr.check(status_file, data_dir=data, cache_dir=cache, now=NOW, ask=down,
                                   s3=bucket(("dr1", "qr2", "qr3", new), weeks), git=no_git)
    assert f"spherex_{new}" in names(st["releases"]) and "spherex_qr2" not in names(st["releases"])
    assert st["new_release_available"] and [r["name"] for r in st["new_releases"]] == [f"spherex_{new}"]
    assert st["targets_behind"] == {"alpha": [f"spherex_{new}"], "beta": [f"spherex_{new}"]}
    assert not online


def test_bucket_superseded_release_is_never_new_data(data, status_file, tmp_path):
    cache = searched_everything(tmp_path)
    st, _, _ = sr.check(status_file, data_dir=data, cache_dir=cache, now=NOW, ask=down, s3=bucket(), git=no_git)
    assert not st["new_release_available"] and st["targets_behind"] == {}
    assert st["s3_listing"]["superseded"] == {"spherex_qr2": "spherex_dr1"}


def test_bucket_folders_that_are_not_releases_are_ignored():
    entries, _ = sr.releases_from_bucket(["dr1", "qr3", "index.html", "spherex_qr9", "qrx", "hips"], {})
    assert names(entries) == ["spherex_dr1", "spherex_qr3"]
    with pytest.raises(sr.IrsaAnswerError):
        sr.releases_from_bucket(["hips", "docs"], {})


def test_check_lists_the_bucket_when_irsa_is_down(data, status_file):
    report = {}
    st, changed, online = sr.check(status_file, data_dir=data, now=NOW, ask=down, s3=bucket(), git=no_git,
                                   report=report)
    saved = json.loads(status_file.read_text())
    assert saved == st and changed and not online and report == {"via": "S3 bucket"}
    assert st["checked"] == BUCKET_NOW and st["checked_via"] == "S3 bucket" and st["last_attempt"] == NOW
    assert st["releases_source"] == sr.SOURCE_S3 and names(st["releases"]) == ["spherex_dr1", "spherex_qr3"]
    assert "IRSA release check failed" in st["error"] and "HTTP 502" in st["error"]
    assert st["s3_listing"]["newest_weeks"]["qr3"] == "2026W40_2A"
    assert st["s3_listing"]["folders"] == ["dr1", "qr2", "qr3"]


def test_check_keeps_other_collections_from_the_last_irsa_answer(data, status_file):
    sr.check(status_file, data_dir=data, now=NOW, ask=canned("irsa_tap_collections.xml"), git=no_git)
    before = sr.read_status(status_file)["other_collections"]
    st, _, _ = sr.check(status_file, data_dir=data, now=LATER, ask=down, s3=bucket(), git=no_git)
    assert st["other_collections"] == before and before


def test_when_irsa_and_the_bucket_fail_the_last_file_is_kept(data, status_file):
    sr.check(status_file, data_dir=data, now=NOW, ask=down, s3=bucket(), git=no_git)
    report = {}
    st, changed, online = sr.check(status_file, data_dir=data, now=LATER, ask=down, s3=s3_down, git=no_git,
                                   report=report)
    assert (changed, online, report["via"]) == (False, False, None)
    assert st["checked"] == BUCKET_NOW and st["checked_via"] == "S3 bucket" and st["last_attempt"] == LATER
    assert "S3 bucket listing failed too" in st["error"] and "connection refused" in st["error"]


def test_with_no_file_and_both_down_it_says_the_check_failed(data, status_file):
    st, _, _ = sr.check(status_file, data_dir=data, now=NOW, ask=down, s3=s3_down, git=no_git)
    assert st["checked"] is None and st["checked_via"] is None and "S3 bucket listing failed too" in st["error"]


def test_a_later_irsa_answer_says_irsa_and_drops_the_bucket_details(data, status_file):
    sr.check(status_file, data_dir=data, now=NOW, ask=down, s3=bucket(), git=no_git)
    st, changed, online = sr.check(status_file, data_dir=data, now=LATER, ask=canned("irsa_tap_collections.xml"),
                                   s3=bucket(), git=no_git)
    assert online and changed and st["checked_via"] == "IRSA" and st["checked"] == LATER and st["error"] is None
    assert "s3_listing" not in st


def test_mark_synced_keeps_how_the_check_was_made(data, status_file):
    sr.check(status_file, data_dir=data, now=NOW, ask=down, s3=bucket(), git=no_git)
    st, _ = sr.mark_synced(status_file, data_dir=data, cache_dir=data.parent / "nocache", now=LATER, git=no_git)
    assert st["checked_via"] == "S3 bucket" and st["checked"] == BUCKET_NOW
    assert st["s3_listing"]["newest_weeks"]["qr3"] == "2026W40_2A"
    assert [r.get("newest_week") for r in st["releases"]] == ["2026W20_1A", "2026W40_2A"]


def test_a_complete_s3_search_answer_counts_as_searched(tmp_path):
    d = tmp_path / "alpha"
    d.mkdir()
    (d / "spherex_sia.xml").write_text("<VOTABLE/>")
    (d / sr.s3_answer_name("spherex_qr3")).write_text(json.dumps({"index_complete": True, "images": []}))
    assert sr.searched_releases(tmp_path, ["alpha"]) == {"alpha": ["spherex_dr1", "spherex_qr3"]}
    assert sr.release_of_cache_file("spherex_qr3_s3.json") == "spherex_qr3"
    assert sr.release_of_cache_file("notes_s3.json") is None


@pytest.mark.parametrize("text", ['{"index_complete": false}', "{", '{"images": []}', "[]"])
def test_a_partial_or_broken_s3_answer_does_not_count(tmp_path, text):
    d = tmp_path / "alpha"
    d.mkdir()
    (d / "spherex_sia.xml").write_text("<VOTABLE/>")
    (d / "spherex_qr3_s3.json").write_text(text)
    assert sr.searched_releases(tmp_path, ["alpha"]) == {"alpha": ["spherex_dr1"]}


def test_cli_lists_the_bucket_when_irsa_is_down(data, status_file, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sr, "discover", down)
    monkeypatch.setattr(sr, "discover_s3", bucket())
    out = tmp_path / "gh_output"
    rc = sr.main(["check", "--file", str(status_file), "--data", str(data), "--github-output", str(out)])
    text = capsys.readouterr().out
    assert rc == 0 and "answered by: S3 bucket" in text
    assert "Quick Release 3 at IRSA has images through 2026 week 40" in text
    assert out.read_text().splitlines() == ["new_release=false", "changed=false", "online=s3", "current=spherex_qr3"]
    assert sr.main(["check", "--file", str(status_file), "--data", str(data), "--require-online"]) == 1


def test_cli_no_s3_skips_the_bucket(data, status_file, monkeypatch):
    monkeypatch.setattr(sr, "discover", down)
    monkeypatch.setattr(sr, "discover_s3", lambda: pytest.fail("the bucket was listed"))
    assert sr.main(["check", "--no-s3", "--file", str(status_file), "--data", str(data)]) == 0
    assert sr.read_status(status_file)["checked"] is None


def test_discover_s3_with_a_fake_bucket():
    sys.path.insert(0, str(ROOT / "tests"))
    from _spherex_s3_fakes import FakeBucket
    b = FakeBucket({"dr1/level2/2026W20_1A/p/1/a.fits": b"1", "qr2/level2/2026W29_2A/p/1/a.fits": b"1",
                    "qr3/level2/2026W20_2A/p/1/a.fits": b"1", "qr3/level2/2026W40_2A/p/1/a.fits": b"1",
                    "index.html": b"<html>"})
    info = REAL_DISCOVER_S3(reader=b, now=lambda: BUCKET_NOW)
    assert info["folders"] == ["dr1", "qr2", "qr3"] and info["listed"] == BUCKET_NOW
    assert names(info["releases"]) == ["spherex_dr1", "spherex_qr3"]
    assert info["newest_weeks"] == {"dr1": "2026W20_1A", "qr2": "2026W29_2A", "qr3": "2026W40_2A"}
