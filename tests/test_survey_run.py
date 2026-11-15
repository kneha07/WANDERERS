"""Tests for pipeline/survey/run.py: tile selection, compaction, atomic files, manifest, publishing
(leaderboard/summary arithmetic, Gaia cache and failures, rank-only), JSON schemas against
docs/survey-contract.md, error classification and the CLI. Worker-pool and resume tests are in
tests/test_survey_run_pool.py. No network: the core and ranking are fakes (tests/test_survey_run_fakes.py).

    .venv/bin/python -m pytest tests/test_survey_run.py tests/test_survey_run_pool.py -q
"""
import errno
import json
import math
import os
import re
import subprocess
import sys
import time
import types
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "tests"))
from survey import run as R  # noqa: E402
import test_survey_run_fakes as fakes  # noqa: E402

VALIDATION = [7945, 8545, 10226, 9509, 6865, 1355, 10397, 3325, 11391]   # astropy_healpix, nested, nside 32
CLASSES = {"unexplained", "known (Gaia)", "likely artefact", "not checked"}


def is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def strict_load(path):
    def bad(c):
        raise ValueError(f"non-JSON constant {c}")
    return json.loads(Path(path).read_text(), parse_constant=bad)


@pytest.fixture
def env(tmp_path, monkeypatch):
    spec = tmp_path / "spec.json"
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("SURVEY_FAKE_SPEC", str(spec))
    fakes.write_spec(spec, log=str(log))
    fakes.XMATCH_CALLS.clear()
    fakes.RANK_CALLS.clear()
    ns = types.SimpleNamespace(tmp=tmp_path, out=tmp_path / "out", cache=tmp_path / "cache", log=log)
    ns.set_spec = lambda **kw: fakes.write_spec(spec, log=str(log), **kw)
    return ns


def write_tiles(out, ks, seconds=1.0):
    for k in ks:
        R.atomic_write_json(Path(out) / "tiles" / f"{k}.json", R.compact_tile(fakes.fake_tile(k), k, seconds))


def do_publish(env, **kw):
    args = dict(cache_dir=env.cache, use_gaia=True, xmatch_fn=fakes.crossmatch_gaia, rank_fn=fakes.rank, runs=[])
    args.update(kw)
    return R.publish(env.out, **args)


# ------------------------------------------------------------------------------------------------ selection
def test_validation_tiles_fallback_astropy(monkeypatch):
    monkeypatch.setitem(sys.modules, "survey.tiles", None)        # core not importable -> astropy_healpix
    assert R.validation_tiles() == VALIDATION


def test_kapteyn_is_the_contract_example_tile(monkeypatch):
    monkeypatch.setitem(sys.modules, "survey.tiles", None)
    assert R.tile_of(77.960, -45.044) == 8545
    assert len(R.KNOWN_MOVERS) == 9 and len(set(R.validation_tiles())) == 9


def test_validation_uses_core_tile_of_when_available(monkeypatch):
    seen = []
    mod = types.ModuleType("survey.tiles")
    mod.tile_of = lambda ra, dec: seen.append((ra, dec)) or 42
    monkeypatch.setitem(sys.modules, "survey.tiles", mod)
    assert R.validation_tiles() == [42]
    assert len(seen) == 9 and seen[1] == (77.960, -45.044)


def test_tile_center_fallback(monkeypatch):
    monkeypatch.setitem(sys.modules, "survey.tiles", None)
    ra, dec = R.tile_center(8545)
    assert abs(ra - 76.5) < 1e-6 and abs(dec + 44.99) < 0.01


def test_parse_all():
    ks = R.parse_tiles_spec("all")
    assert ks == list(range(12288))


def test_parse_random_deterministic_by_seed():
    a, b, c = R.parse_tiles_spec("random:50", 1), R.parse_tiles_spec("random:50", 1), R.parse_tiles_spec("random:50", 2)
    assert a == b and a != c
    assert len(set(a)) == 50 and all(0 <= k < 12288 for k in a)


def test_parse_list_ranges_and_dedupe():
    assert R.parse_tiles_spec("list:5,3,5,10-12, 4") == [5, 3, 10, 11, 12, 4]


def test_parse_validation_spec(monkeypatch):
    monkeypatch.setitem(sys.modules, "survey.tiles", None)
    assert R.parse_tiles_spec("validation") == VALIDATION


@pytest.mark.parametrize("spec", ["", "bogus", "list:", "list:abc", "list:12288", "list:-1", "list:12-3",
                                  "random:0", "random:12289", "random:x", "random:"])
def test_parse_tiles_errors(spec):
    with pytest.raises(ValueError):
        R.parse_tiles_spec(spec)


def test_order_given_keeps_selection():
    assert R.order_tiles([9, 3, 7], "given") == [9, 3, 7]


def test_order_random_is_seeded_permutation():
    sel = list(range(100))
    a, b, c = R.order_tiles(sel, "random", 1), R.order_tiles(sel, "random", 1), R.order_tiles(sel, "random", 2)
    assert a == b and a != c and sorted(a) == sel and a != sel


def test_order_validation_first_then_seeded_rest():
    sel = list(range(12288))
    a = R.order_tiles(sel, "validation-first", 1, VALIDATION)
    b = R.order_tiles(sel, "validation-first", 1, VALIDATION)
    c = R.order_tiles(sel, "validation-first", 2, VALIDATION)
    assert a[:9] == VALIDATION and a == b
    assert len(a) == 12288 and len(set(a)) == 12288
    assert c[:9] == VALIDATION and a[9:] != c[9:]
    assert a[9:30] != sorted(a[9:30])                                 # spread over the sky, not in index order


def test_order_validation_first_adds_validation_to_a_random_selection():
    sel = R.parse_tiles_spec("random:40", 3)
    a = R.order_tiles(sel, "validation-first", 3, VALIDATION)
    assert a[:9] == VALIDATION
    assert set(a) == set(sel) | set(VALIDATION) and len(a) == len(set(a))


def test_order_unknown_raises():
    with pytest.raises(ValueError):
        R.order_tiles([1], "sideways")


# ------------------------------------------------------------------------------------------------ compaction
def test_compact_tile_rounds_positions_6_and_pm_1():
    t = R.compact_tile(fakes.fake_tile(7), 7, 12.3456)
    m = t["movers"][0]
    assert m["ra"] == round(fakes.fake_tile(7)["movers"][0]["ra"], 6)
    for key, nd in (("ra", 6), ("dec", 6), ("pmra", 1), ("pmdec", 1), ("pm", 1), ("epoch", 4)):
        assert m[key] == round(m[key], nd)
    assert m["pmra"] == round(150.0 + 37.123456 + 7 % 13, 1)
    assert t["seconds"] == 12.35


def test_compact_track_capped_at_30_keeping_first_and_last():
    raw = fakes.fake_tile(3)["movers"][0]["track"]                 # 40 points
    t = R.compact_track(raw)
    assert len(t) == 30
    assert t[0][0] == round(raw[0][0], 4) and t[-1][0] == round(raw[-1][0], 4)
    epochs = [p[0] for p in t]
    assert epochs == sorted(epochs) and len(set(epochs)) == 30


def test_compact_track_short_kept_whole():
    t = R.compact_track([[2014.123456, 1.23456789, -2.3456789], [2015.0, 1.0, -2.0]])
    assert t == [[2014.1235, 1.234568, -2.345679], [2015.0, 1.0, -2.0]]


def test_compact_converts_numpy_and_nan_to_plain_json():
    tile = fakes.fake_tile(5)
    tile["movers"][0]["chi2r"] = np.float32("nan")
    tile["movers"][0]["pm_err"] = float("inf")
    t = R.compact_tile(tile, 5, 1.0)
    m = t["movers"][0]
    assert m["chi2r"] is None and m["pm_err"] is None
    assert type(t["n_detections"]) is int and type(m["n_visits"]) is int and type(m["pm_snr"]) is float
    json.dumps(t, allow_nan=False)                                  # strictly valid JSON


def test_compact_fills_missing_ids_k5_w1w2_and_seconds():
    res = {"center": [1.0, 2.0], "years": ["year1"], "n_detections": 10, "seconds": 3.21,
           "movers": [{"ra": 1.0, "dec": 2.0, "pmra": 300.0, "pmdec": 400.0, "w1": 15.5, "w2": 14.25}]}
    t = R.compact_tile(res, 77)
    m = t["movers"][0]
    assert m["id"] == "77-0000" and m["k5"] == 77 and m["pm"] == 500.0 and m["w1w2"] == 1.25
    assert t["seconds"] == 3.21 and t["n_good"] == 0 and t["n_movers"] == 1
    assert m["track"] == [] and m["flags"] == [] and m["plx"] is None


def test_compact_tile_rejects_non_dict():
    with pytest.raises(TypeError):
        R.compact_tile(None, 1)


def test_compact_gaia_source_id_becomes_string():
    g = R.compact_gaia({"checked": True, "match": True, "source_id": 4810594479418041856, "sep_arcsec": 0.41234,
                        "pm": 8644.04, "g": 8.0612})
    assert g == {"checked": True, "match": True, "source_id": "4810594479418041856", "sep_arcsec": 0.412,
                 "pm": 8644.0, "g": 8.061}
    assert R.compact_gaia(None) == R.GAIA_UNCHECKED


def test_compact_truncates_pathological_tiles(monkeypatch):
    monkeypatch.setattr(R, "MAX_MOVERS_PER_TILE", 2)
    t = R.compact_tile(fakes.fake_tile(3), 3, 1.0)                  # 3 movers
    assert t["n_movers"] == 3 and len(t["movers"]) == 2 and t["movers_truncated"] is True
    assert {m["id"] for m in t["movers"]} == {"3-0001", "3-0002"}  # the two highest pm_snr


def test_compact_keeps_scalar_extras_drops_bulky_ones():
    tile = fakes.fake_tile(1)
    tile["debug_arrays"] = np.zeros(1000)
    tile["note"] = "ok"
    tile["movers"][0]["edge_arcsec"] = 123.456789123
    tile["movers"][0]["debug"] = {"big": list(range(100))}
    t = R.compact_tile(tile, 1, 1.0)
    assert "debug_arrays" not in t and t["note"] == "ok"
    assert t["movers"][0]["edge_arcsec"] == 123.4568 and "debug" not in t["movers"][0]


# ------------------------------------------------------------------------------------------------ atomic files
def test_atomic_write_roundtrip_leaves_no_temp(tmp_path):
    p = tmp_path / "a" / "x.json"
    R.atomic_write_json(p, {"v": np.float64(1.5), "n": float("nan")})
    assert strict_load(p) == {"v": 1.5, "n": None}
    assert [f.name for f in p.parent.iterdir()] == ["x.json"]


def test_atomic_write_crash_before_rename_keeps_old_file(tmp_path, monkeypatch):
    p = tmp_path / "x.json"
    R.atomic_write_json(p, {"v": 1})

    def boom(*a, **k):
        raise KeyboardInterrupt("killed between write and rename")
    monkeypatch.setattr(R.os, "replace", boom)
    with pytest.raises(KeyboardInterrupt):
        R.atomic_write_json(p, {"v": 2, "big": "x" * 100000})
    monkeypatch.undo()
    assert strict_load(p) == {"v": 1}
    assert [f.name for f in tmp_path.iterdir()] == ["x.json"]


def test_atomic_write_disk_full_keeps_old_file(tmp_path, monkeypatch):
    p = tmp_path / "x.json"
    R.atomic_write_json(p, {"v": 1})

    def full(fd):
        raise OSError(errno.ENOSPC, "No space left on device")
    monkeypatch.setattr(R.os, "fsync", full)
    with pytest.raises(OSError) as ei:
        R.atomic_write_json(p, {"v": 2})
    assert R.classify_error(ei.value) == "disk"
    monkeypatch.undo()
    assert strict_load(p) == {"v": 1} and len(list(tmp_path.iterdir())) == 1


def test_cleanup_temp_files_removes_only_stale_ones(tmp_path):
    old = tmp_path / ".5.json.tmp-1-aaaa"
    new = tmp_path / ".6.json.tmp-1-bbbb"
    old.write_text("{")
    new.write_text("{")
    os.utime(old, (time.time() - 3600, time.time() - 3600))
    assert R.cleanup_temp_files(tmp_path) == 1
    assert not old.exists() and new.exists()


# ------------------------------------------------------------------------------------------------ manifest
def test_new_manifest_shape():
    m = R.new_manifest()
    assert m["done"] == {} and m["failed"] == {} and m["runs"] == [] and m["tiles_total"] == 12288


def test_corrupt_manifest_moved_aside(tmp_path):
    (tmp_path / "manifest.json").write_text('{"done": {"1": ')
    m = R.load_manifest(tmp_path)
    assert m["done"] == {}
    assert list(tmp_path.glob("manifest.corrupt-*.json"))
    assert not (tmp_path / "manifest.json").exists()


def test_manifest_with_wrong_types_is_rebuilt(tmp_path):
    (tmp_path / "manifest.json").write_text('{"done": [1, 2], "runs": []}')
    assert R.load_manifest(tmp_path)["done"] == {}


def test_reconcile_files_win(tmp_path):
    tiles = tmp_path / "tiles"
    write_tiles(tmp_path, [1, 3])
    (tiles / "2.json").write_text('{"k5": 2, "movers": [')       # truncated by something else
    (tiles / "4.json").write_text('{"k5": 5, "movers": []}')     # wrong tile
    (tiles / "notes.txt").write_text("x")
    m = R.new_manifest()
    m["done"]["99"] = {"bytes": 10}
    m["failed"]["1"] = {"error": "old", "attempts": 1}
    rec = R.reconcile(m, tiles)
    assert rec == {"added": 2, "dropped": 1, "bad": 2}
    assert set(m["done"]) == {"1", "3"} and m["failed"] == {}
    assert (tiles / "2.json.bad").exists() and not (tiles / "2.json").exists()
    assert m["done"]["1"]["n_detections"] == 1_001_000 and m["done"]["1"]["n_movers"] == 1


def test_read_tile_file_checks_name_and_shape(tmp_path):
    write_tiles(tmp_path, [6])
    assert R.read_tile_file(tmp_path / "tiles" / "6.json")["k5"] == 6
    (tmp_path / "7.json").write_text("[]")
    assert R.read_tile_file(tmp_path / "7.json") is None


# ------------------------------------------------------------------------------------------------ publishing
def test_summary_arithmetic(env):
    write_tiles(env.out, [1, 2, 3, 4])
    runs = [{"wall_seconds": 3600, "tiles": 3, "detections": 3_000_000},
            {"wall_seconds": 1800, "tiles": 1, "detections": 1_500_000}]
    s = do_publish(env, use_gaia=False, runs=runs)
    assert s["tiles_done"] == 4 and s["tiles_total"] == 12288
    assert s["sky_fraction"] == round(4 / 12288, 6)
    assert s["sky_deg2"] == round(4 * 41252.96124941928 / 12288, 1) == 13.4
    assert s["detections"] == 4 * 1_000_000 + 1000 * 10
    assert s["good_detections"] == 4 * 800_000 + 800 * 10
    assert s["visit_sources"] == 4 * 50_000 + 10 and s["tracks"] == 4 * 4_000 + 10
    assert s["movers"] == 1 + 2 + 3 + 0 and s["unexplained"] == 0
    assert s["runtime_hours"] == 1.5 and s["tiles_per_hour"] == round(4 / 1.5, 1)
    assert s["detections_per_second"] == round(4_500_000 / 5400)
    assert s["tiles"] == [[1, 1, 0], [2, 2, 0], [3, 3, 0], [4, 0, 0]]
    assert strict_load(env.out / "summary.json") == s


def test_summary_without_runs_has_zero_throughput(env):
    write_tiles(env.out, [2])
    s = do_publish(env, use_gaia=False, runs=[])
    assert s["runtime_hours"] == 0 and s["tiles_per_hour"] == 0 and s["detections_per_second"] == 0


def test_summary_reads_run_log_from_manifest_when_not_given(env):
    write_tiles(env.out, [2])
    R.atomic_write_json(env.out / "manifest.json", {"done": {}, "failed": {}, "runs": [
        {"wall_seconds": 7200, "tiles": 10, "detections": 72_000_000}]})
    s = do_publish(env, use_gaia=False, runs=None)
    assert s["runtime_hours"] == 2.0 and s["tiles_per_hour"] == 5.0 and s["detections_per_second"] == 10_000


def test_leaderboard_orders_across_tiles_with_global_ranks(env):
    write_tiles(env.out, [1, 2, 3, 5, 6, 7])
    do_publish(env)
    lb = strict_load(env.out / "leaderboard.json")
    c = lb["candidates"]
    assert lb["n_candidates"] == len(c) == 1 + 2 + 3 + 1 + 2 + 3
    scores = [x["score"] for x in c]
    assert scores == sorted(scores, reverse=True)
    assert [x["rank"] for x in c] == list(range(1, len(c) + 1))
    assert len({x["k5"] for x in c}) == 6 and all(x["id"].startswith(f"{x['k5']}-") for x in c)
    n_unexpl = sum(x["class"] == "unexplained" for x in c)
    assert all(x["class"] == "unexplained" for x in c[:n_unexpl])  # unexplained outrank Gaia matches


def test_leaderboard_top_cap_keeps_best(env):
    write_tiles(env.out, [3, 7, 11, 15])                            # 3 movers each
    do_publish(env, top=4)
    full = [(fakes.score_of({**m, "gaia": fakes.gaia_for(m["id"])}), m["pm_snr"], m["id"])
            for k in (3, 7, 11, 15) for m in R.compact_tile(fakes.fake_tile(k), k)["movers"]]
    lb = strict_load(env.out / "leaderboard.json")
    assert len(lb["candidates"]) == 4 and lb["n_candidates"] == 12   # n_candidates counts every ranked mover
    best = sorted(full, key=lambda t: (-t[0], -t[1], t[2]))[:4]
    assert [x["id"] for x in lb["candidates"]] == [i for _, _, i in best]


def test_n_candidates_is_all_ranked_movers_not_the_top(env):
    write_tiles(env.out, [1, 2, 3, 4, 5, 6, 7])                     # 1+2+3+0+1+2+3 movers
    do_publish(env, top=2)
    lb = strict_load(env.out / "leaderboard.json")
    assert lb["n_candidates"] == 12 and len(lb["candidates"]) == 2
    assert [x["rank"] for x in lb["candidates"]] == [1, 2]


def test_equal_scores_ordered_by_pm_snr_then_id(env):
    write_tiles(env.out, [3, 7])

    def flat_rank(movers, top=1000):
        return [dict(m, score=1.0, reasons=[], **{"class": "not checked"}) for m in movers]
    do_publish(env, rank_fn=flat_rank, use_gaia=False)
    c = strict_load(env.out / "leaderboard.json")["candidates"]
    keys = [(-x["pm_snr"], x["id"]) for x in c]
    assert keys == sorted(keys) and len(c) == 6


def test_summary_extra_fields_for_the_web_page(env):
    write_tiles(env.out, [1, 2, 3])
    runs = [{"wall_seconds": 60, "tiles": 3, "detections": 3e6, "planned": 40, "min_pm": 175.0}]
    s = do_publish(env, use_gaia=False, runs=runs)
    assert s["status"] == "done" and s["tiles_planned"] == 40 and s["min_pm"] == 175.0
    assert s["unique_sources"] == s["tracks"] == 3 * 4000 + 6
    assert "at least 175 mas per year" in s["method"] and any("slower than 175 mas" in t for t in s["limits"])
    s = do_publish(env, use_gaia=False, runs=runs, status="running", tiles_planned=2, min_pm=150.0)
    assert s["status"] == "running" and s["tiles_planned"] == 3    # never below tiles_done
    assert "at least 150 mas per year" in s["method"]


def test_summary_status_running_while_a_live_run_holds_the_lock(env):
    write_tiles(env.out, [1])
    holder = subprocess.Popen(["sleep", "30"])
    try:
        (env.out / ".run.lock").write_text(f"{holder.pid} 2026-01-01T00:00:00Z\n")
        assert do_publish(env, use_gaia=False)["status"] == "running"
    finally:
        holder.kill()
        holder.wait()
    assert do_publish(env, use_gaia=False)["status"] == "done"     # lock of a dead process


def test_min_pm_comes_from_the_core_signature(env, monkeypatch):
    assert R.core_min_pm(fakes.process_tile) == 150.0
    assert R.core_min_pm(fakes.process_tile_strict) == 200.0
    assert R.core_min_pm("survey.no_such_core:process_tile") == R.DEFAULT_MIN_PM == 150.0
    monkeypatch.setitem(sys.modules, "survey.link", None)
    write_tiles(env.out, [1])
    assert do_publish(env, use_gaia=False, runs=[])["min_pm"] == 150.0


def test_mark_not_running_flips_only_a_running_summary(env):
    write_tiles(env.out, [1])
    s = do_publish(env, use_gaia=False, status="running")
    R.mark_not_running(env.out)
    after = strict_load(env.out / "summary.json")
    assert after["status"] == "done" and {k: v for k, v in after.items() if k != "status"} == \
        {k: v for k, v in s.items() if k != "status"}
    R.mark_not_running(env.tmp / "nowhere")                          # no summary yet: nothing to do
    assert R.STATUSES == ("running", "done")                         # the two values the web page knows
    assert do_publish(env, use_gaia=False, status="bogus")["status"] == "done"


# ------------------------------------------------------------------------------------------------ real survey.rank
def test_publish_with_the_real_rank_module(env):
    rank_mod = pytest.importorskip("survey.rank")
    write_tiles(env.out, [1, 2, 3, 5, 6, 7])
    s = do_publish(env, use_gaia=False, rank_fn=rank_mod.rank)
    lb = strict_load(env.out / "leaderboard.json")
    assert lb["n_candidates"] == s["movers"] == 12 and len(lb["candidates"]) == 12
    for m in lb["candidates"]:
        check_mover(m, ranked=True, extra_ok=True)
        assert m["class"] in ("not checked", "likely artefact") and m["reasons"]
    keys = [(-x["score"], -x["pm_snr"], x["id"]) for x in lb["candidates"]]
    assert keys == sorted(keys)                                      # same order rule as survey.rank.rank


def test_real_crossmatch_offline_marks_not_checked_and_caches_nothing(env, monkeypatch):
    rank_mod = pytest.importorskip("survey.rank")
    import functools
    monkeypatch.setattr(rank_mod, "RETRY_SLEEP_S", 0.0)
    xmatch = functools.partial(rank_mod.crossmatch_gaia, tap_url="http://127.0.0.1:9/tap", timeout=2)
    write_tiles(env.out, [3])
    s = do_publish(env, xmatch_fn=xmatch, rank_fn=rank_mod.rank)
    lb = strict_load(env.out / "leaderboard.json")
    assert all(m["gaia"]["checked"] is False for m in lb["candidates"])
    assert s["unexplained"] == 0 and any("pending" in t for t in s["limits"])
    assert not list((env.cache / "run_tiles").glob("*.json")) if (env.cache / "run_tiles").exists() else True


def test_unexplained_counts_per_tile_and_total(env):
    write_tiles(env.out, [1, 2, 3, 4])
    s = do_publish(env)
    # fake Gaia: movers with an odd index have no counterpart
    assert s["tiles"] == [[1, 1, 0], [2, 2, 1], [3, 3, 1], [4, 0, 0]]
    assert s["unexplained"] == 2 and s["movers"] == 6


def test_no_gaia_skips_crossmatch_and_marks_not_checked(env):
    write_tiles(env.out, [3])
    s = do_publish(env, use_gaia=False)
    lb = strict_load(env.out / "leaderboard.json")
    assert fakes.XMATCH_CALLS == []
    assert {x["class"] for x in lb["candidates"]} == {"not checked"}
    assert all(x["gaia"] == R.GAIA_UNCHECKED for x in lb["candidates"])
    assert s["unexplained"] == 0 and any("switched off" in t for t in s["limits"])


def test_gaia_called_once_per_tile_then_cached(env):
    write_tiles(env.out, [1, 2, 3, 4])                              # tile 4 has no movers
    do_publish(env)
    assert sorted(len(c) for c in fakes.XMATCH_CALLS) == [1, 2, 3]
    assert len(list((env.cache / "run_tiles").glob("*.json"))) == 3
    fakes.XMATCH_CALLS.clear()
    s = do_publish(env)
    assert fakes.XMATCH_CALLS == [] and s["unexplained"] == 2


def test_gaia_cache_invalidated_when_tile_changes(env):
    write_tiles(env.out, [3])
    do_publish(env)
    t = strict_load(env.out / "tiles" / "3.json")
    t["movers"][0]["ra"] += 0.01
    R.atomic_write_json(env.out / "tiles" / "3.json", t)
    fakes.XMATCH_CALLS.clear()
    do_publish(env)
    assert len(fakes.XMATCH_CALLS) == 1


def test_gaia_outage_is_not_cached_and_is_retried(env):
    write_tiles(env.out, [2, 3])
    env.set_spec(gaia_down=True)
    s = do_publish(env)
    assert s["unexplained"] == 0 and any("still pending for 2 of 2" in t for t in s["limits"])
    assert not (env.cache / "run_tiles").exists() or not list((env.cache / "run_tiles").glob("*.json"))
    env.set_spec(gaia_down=False)
    fakes.XMATCH_CALLS.clear()
    s = do_publish(env)
    assert len(fakes.XMATCH_CALLS) == 2 and s["unexplained"] == 2
    assert not any("pending" in t for t in s["limits"])


def test_gaia_exceptions_open_the_breaker(env):
    write_tiles(env.out, [1, 2, 3, 5, 6, 7])                        # 6 tiles with movers
    env.set_spec(gaia_raise=True)
    s = do_publish(env, gaia_fail_limit=3)
    assert len(fakes.XMATCH_CALLS) == 3                             # then left alone until the next publish
    assert s["movers"] == 12 and s["unexplained"] == 0


def test_gaia_budget_zero_uses_cache_only(env):
    write_tiles(env.out, [2])
    s = do_publish(env, gaia_budget_s=0)
    assert fakes.XMATCH_CALLS == [] and any("pending" in t for t in s["limits"])


def test_rank_failure_falls_back_to_snr_order(env):
    write_tiles(env.out, [3])
    do_publish(env, rank_fn=fakes.rank_raises)
    c = strict_load(env.out / "leaderboard.json")["candidates"]
    assert [x["id"] for x in c] == ["3-0002", "3-0001", "3-0000"]
    assert "ranking module unavailable" in c[0]["reasons"][0]
    assert {x["class"] for x in c} == {"unexplained", "known (Gaia)"}


def test_missing_rank_module_falls_back(env):
    write_tiles(env.out, [2])
    s = do_publish(env, rank_fn="survey.no_such_module:rank", use_gaia=False)
    assert s["movers"] == 2 and strict_load(env.out / "leaderboard.json")["n_candidates"] == 2


def test_validation_json_summary_is_merged(env):
    write_tiles(env.out, [1])
    R.atomic_write_json(env.out / "validation.json", {"summary": {"recovered": 8, "known": 9},
                                                      "details": list(range(5000))})
    assert do_publish(env, use_gaia=False)["validation"] == {"recovered": 8, "known": 9}


def test_validation_json_without_summary_drops_bulky_parts(env):
    write_tiles(env.out, [1])
    R.atomic_write_json(env.out / "validation.json", {"completeness": 0.93, "curve": list(range(5000))})
    assert do_publish(env, use_gaia=False)["validation"] == {"completeness": 0.93}


def test_validation_absent_is_null(env):
    write_tiles(env.out, [1])
    assert do_publish(env, use_gaia=False)["validation"] is None


def test_publish_skips_unreadable_tile_files(env):
    write_tiles(env.out, [1, 2])
    (env.out / "tiles" / "3.json").write_text("{oops")
    s = do_publish(env, use_gaia=False)
    assert s["tiles_done"] == 2


def test_publish_abort_writes_nothing(env):
    write_tiles(env.out, [1, 2])
    with pytest.raises(R.PublishAborted):
        do_publish(env, should_abort=lambda: True)
    assert not (env.out / "summary.json").exists()


def test_publish_with_no_tiles(env):
    (env.out / "tiles").mkdir(parents=True)
    s = do_publish(env)
    assert s["tiles_done"] == 0 and s["tiles"] == [] and strict_load(env.out / "leaderboard.json")["candidates"] == []


# ------------------------------------------------------------------------------------------------ schemas
TILE_TYPES = {"k5": int, "n_detections": int, "n_good": int, "n_visits": int, "n_visit_sources": int,
              "n_tracks": int, "n_movers": int}
MOVER_NUM = ["ra", "dec", "epoch", "pmra", "pmdec", "pm", "pm_err", "pm_snr", "chi2r", "span_yr", "w1", "w2", "w1w2"]


def check_mover(m, ranked=False, extra_ok=False):
    """Contract keys in contract order; extra_ok allows scalar extras after them (e.g. the real Gaia check adds an
    'error' text to unchecked movers)."""
    want = R.MOVER_KEYS + (R.RANK_KEYS if ranked else [])
    if extra_ok:
        assert list(m)[:len(want)] == want and all(R._is_scalar(m[k]) for k in list(m)[len(want):])
        if ranked:
            assert list(m["gaia"])[:len(R.GAIA_KEYS)] == R.GAIA_KEYS
            m = dict(m, gaia={k: m["gaia"][k] for k in R.GAIA_KEYS})
    else:
        assert list(m) == want
    assert isinstance(m["id"], str) and type(m["k5"]) is int and type(m["n_visits"]) is int
    for k in MOVER_NUM:
        assert is_num(m[k]), k
    for k in ("plx", "plx_err"):
        assert m[k] is None or is_num(m[k])
    assert isinstance(m["track"], list) and len(m["track"]) <= 30
    assert all(len(p) == 3 and all(is_num(v) for v in p) for p in m["track"])
    assert isinstance(m["flags"], list) and all(isinstance(f, str) for f in m["flags"])
    if ranked:
        g = m["gaia"]
        assert list(g) == R.GAIA_KEYS and isinstance(g["checked"], bool)
        assert g["match"] is None or isinstance(g["match"], bool)
        assert g["source_id"] is None or isinstance(g["source_id"], str)
        for k in ("sep_arcsec", "pm", "g"):
            assert g[k] is None or is_num(g[k])
        assert is_num(m["score"]) and isinstance(m["reasons"], list) and all(isinstance(r, str) for r in m["reasons"])
        assert m["class"] in CLASSES and type(m["rank"]) is int


def test_tile_file_schema_matches_contract(env):
    write_tiles(env.out, [3], seconds=41.234)
    t = strict_load(env.out / "tiles" / "3.json")
    assert list(t) == R.TILE_KEYS
    for k, typ in TILE_TYPES.items():
        assert type(t[k]) is typ, k
    assert len(t["center"]) == 2 and all(is_num(v) for v in t["center"])
    assert t["years"] == fakes.YEARS and t["seconds"] == 41.23 and len(t["movers"]) == t["n_movers"] == 3
    for m in t["movers"]:
        check_mover(m)


def test_leaderboard_schema_matches_contract(env):
    write_tiles(env.out, [1, 2, 3])
    do_publish(env)
    lb = strict_load(env.out / "leaderboard.json")
    assert list(lb) == R.LEADERBOARD_KEYS and type(lb["n_candidates"]) is int
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", lb["generated"])
    assert lb["candidates"]
    for m in lb["candidates"]:
        check_mover(m, ranked=True)
    known = [m for m in lb["candidates"] if m["class"] == "known (Gaia)"]
    assert known and known[0]["gaia"]["source_id"].isdigit()


def test_summary_schema_matches_contract(env):
    write_tiles(env.out, [1, 2])
    R.atomic_write_json(env.out / "validation.json", {"summary": {"recovered": 9}})
    do_publish(env, runs=[{"wall_seconds": 60, "tiles": 2, "detections": 2_000_000}])
    s = strict_load(env.out / "summary.json")
    assert list(s) == R.SUMMARY_KEYS + R.SUMMARY_EXTRA_KEYS            # contract keys, then the page's additions
    assert R.SUMMARY_EXTRA_KEYS == ["status", "tiles_planned", "min_pm", "unique_sources"]
    assert s["status"] in ("running", "done") and type(s["tiles_planned"]) is int
    assert type(s["min_pm"]) is float and type(s["unique_sources"]) is int and s["tiles_planned"] >= s["tiles_done"]
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", s["generated"])
    for k in ("tiles_done", "tiles_total", "detections", "good_detections", "visit_sources", "tracks", "movers",
              "unexplained", "detections_per_second"):
        assert type(s[k]) is int, k
    for k in ("sky_fraction", "sky_deg2", "runtime_hours", "tiles_per_hour"):
        assert is_num(s[k]), k
    assert all(len(r) == 3 and all(type(v) is int for v in r) for r in s["tiles"])
    assert isinstance(s["validation"], dict) and isinstance(s["method"], str) and len(s["method"]) > 200
    assert isinstance(s["limits"], list) and all(isinstance(t, str) for t in s["limits"]) and len(s["limits"]) >= 5


# ------------------------------------------------------------------------------------------------ errors & retries
@pytest.mark.parametrize("exc, want", [
    (ConnectionError("reset"), True),
    (TimeoutError(), True),
    (OSError("AWS Error NETWORK_CONNECTION during GetObject operation: curlCode: 28, Timeout was reached"), True),
    (OSError("AWS Error SLOW_DOWN during GetObject operation: Please reduce your request rate."), True),
    (OSError("When reading information for key 'x': AWS Error UNKNOWN (HTTP status 503) during HeadObject"), True),
    (FileNotFoundError("no such parquet"), False),
    (OSError(errno.ENOSPC, "No space left on device"), False),
    (ValueError("timeout parameter is wrong"), False),
    (KeyError("ra"), False),
])
def test_is_network_error(exc, want):
    assert R.is_network_error(exc) is want


def test_network_error_found_in_cause_chain():
    try:
        try:
            raise ConnectionResetError("peer")
        except ConnectionResetError as e:
            raise RuntimeError("read failed") from e
    except RuntimeError as e:
        assert R.is_network_error(e)


def test_classify_error():
    assert R.classify_error(MemoryError()) == "memory"
    assert R.classify_error(OSError(errno.ENOSPC, "full")) == "disk"
    assert R.classify_error(ConnectionError()) == "network"
    assert R.classify_error(ValueError("bad")) == "error"


def test_retrying_reader_retries_network_errors_then_succeeds():
    calls, sleeps = [], []

    def base(k5, year, **kw):
        calls.append((k5, year, kw))
        if len(calls) < 3:
            raise OSError("AWS Error SLOW_DOWN")
        return "table"
    r = R.RetryingReader(base, attempts=5, backoff=2.0, sleep=sleeps.append)
    assert r(8545, "year3", columns=["ra"]) == "table"
    assert len(calls) == 3 and calls[0] == (8545, "year3", {"columns": ["ra"]}) and r.retries == 2
    assert 1.5 <= sleeps[0] <= 2.5 and 3.0 <= sleeps[1] <= 5.0


def test_retrying_reader_does_not_retry_other_errors():
    calls = []

    def base(k5, year, **kw):
        calls.append(1)
        raise ValueError("schema mismatch")
    with pytest.raises(ValueError):
        R.RetryingReader(base, attempts=5, sleep=lambda s: None)(1, "year1")
    assert len(calls) == 1


def test_retrying_reader_gives_up_after_attempts():
    calls = []

    def base(k5, year, **kw):
        calls.append(1)
        raise ConnectionError("down")
    with pytest.raises(ConnectionError):
        R.RetryingReader(base, attempts=3, sleep=lambda s: None)(1, "year1")
    assert len(calls) == 3


def test_retrying_reader_passes_worker_filesystem():
    seen = []
    r = R.RetryingReader(lambda k5, year, **kw: seen.append(kw) or None, make_fs=lambda: "FS")
    r(1, "year1")
    r(1, "year2")
    assert seen == [{"fs": "FS"}, {"fs": "FS"}]


def test_backoff_delay_doubles_with_jitter_and_cap():
    import random
    rng = random.Random(0)
    for attempt, lo, hi in ((1, 22.5, 37.5), (2, 45, 75), (3, 90, 150), (10, 450, 750)):
        d = R.backoff_delay(attempt, 30.0, 600.0, rng)
        assert lo <= d <= hi


def test_parse_ps_rss_and_live_rss():
    assert R.parse_ps_rss("  123  2048\n456 10\nbad line\n") == {123: 2048 * 1024, 456: 10 * 1024}
    assert R.rss_bytes([os.getpid()]).get(os.getpid(), 0) > 10 * 1024 * 1024
    assert R.rss_bytes([]) == {}


def test_machine_probes_return_sane_values(tmp_path):
    avail = R.available_memory_bytes()
    assert avail is None or avail > 0
    assert R.disk_free_bytes(tmp_path / "not" / "yet") > 0
    assert R.peak_rss_bytes() > 10 * 1024 * 1024


def test_load_callable():
    assert R.load_callable("os.path:join") is os.path.join
    assert R.load_callable(len) is len
    with pytest.raises(ValueError):
        R.load_callable("no_colon")
    with pytest.raises(ImportError):
        R.load_callable("survey.no_such_module:x")


# ------------------------------------------------------------------------------------------------ CLI
@pytest.mark.parametrize("argv", [
    [],
    ["--tiles", "bogus"],
    ["--tiles", "random:0"],
    ["--tiles", "list:99999"],
    ["--tiles", "validation", "--workers", "0"],
    ["--tiles", "all", "--workers", "two"],
    ["--tiles", "all", "--order", "sideways"],
    ["--tiles", "all", "--max-hours", "-1"],
    ["--tiles", "all", "--max-hours", "0"],
    ["--tiles", "all", "--retries", "-1"],
    ["--tiles", "all", "--publish-every", "-5"],
    ["--tiles", "all", "--no-such-flag"],
])
def test_cli_rejects_bad_arguments(argv, capsys):
    with pytest.raises(SystemExit) as ei:
        R.parse_args(argv)
    assert ei.value.code == 2
    assert "error" in capsys.readouterr().err


def test_cli_defaults():
    c = R.parse_args(["--tiles", "validation"])
    assert (c.workers, c.seed, c.order, c.max_hours, c.publish_every) == (3, 1, "given", None, 10.0)
    assert c.out == ROOT / "app" / "data" / "survey" and c.cache == ROOT / "data" / "cache" / "survey_gaia"
    assert c.process_fn == "survey.link:process_tile" and c.rank_fn == "survey.rank:rank"
    assert not c.no_gaia and not c.rank_only


def test_cli_full_contract_form():
    c = R.parse_args(["--tiles", "random:25", "--workers", "4", "--out", "x/y", "--seed", "7", "--max-hours", "2.5",
                      "--cache", "c", "--no-gaia", "--order", "validation-first", "--max-tiles", "3"])
    assert (c.tiles, c.workers, c.out, c.seed, c.max_hours) == ("random:25", 4, Path("x/y"), 7, 2.5)
    assert c.cache == Path("c") and c.no_gaia and c.order == "validation-first" and c.max_tiles == 3


def test_cli_rank_only_needs_no_tiles():
    c = R.parse_args(["--rank-only", "--out", "o"])
    assert c.rank_only and c.tiles is None


def test_rank_only_rebuilds_from_tile_files(env):
    write_tiles(env.out, [1, 2, 3])
    manifest = {"done": {}, "failed": {}, "runs": [{"run": 1, "wall_seconds": 600, "tiles": 3, "detections": 3e6}]}
    R.atomic_write_json(env.out / "manifest.json", manifest)
    before = (env.out / "tiles" / "1.json").read_bytes()
    code = R.main(["--rank-only", "--out", str(env.out), "--cache", str(env.cache), "--log-file", "",
                   "--process-fn", "no.such.core:process_tile", "--rank-fn", "test_survey_run_fakes:rank",
                   "--xmatch-fn", "test_survey_run_fakes:crossmatch_gaia"])
    assert code == 0
    s = strict_load(env.out / "summary.json")
    assert s["tiles_done"] == 3 and s["movers"] == 6 and s["unexplained"] == 2 and s["tiles_per_hour"] == 18.0
    assert s["status"] == "done" and s["tiles_planned"] == 3 and isinstance(s["min_pm"], float)
    assert strict_load(env.out / "leaderboard.json")["n_candidates"] == 6
    assert strict_load(env.out / "manifest.json")["runs"] == manifest["runs"]   # untouched
    assert (env.out / "tiles" / "1.json").read_bytes() == before


def test_docstring_smoke_command_runs(env):
    """The no-network smoke command from the module docstring, as a real subprocess."""
    out = env.tmp / "smoke"
    cmd = [sys.executable, str(ROOT / "pipeline" / "survey" / "run.py"), "--tiles", "list:1-6", "--workers", "2",
           "--no-gaia", "--publish-every", "0", "--out", str(out), "--cache", str(out / "cache"),
           "--log-file", str(out / "run.log"), "--process-fn", "test_survey_run_fakes:process_tile",
           "--rank-fn", "test_survey_run_fakes:rank"]
    assert "--process-fn test_survey_run_fakes:process_tile" in R.__doc__
    envv = dict(os.environ, PYTHONPATH=str(ROOT / "tests"))
    p = subprocess.run(cmd, cwd=ROOT, env=envv, capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr
    s = strict_load(out / "summary.json")
    assert s["tiles_done"] == 6 and s["movers"] == 9
    assert "tile 3 done" in (out / "run.log").read_text()
    assert sorted(int(f.stem) for f in (out / "tiles").glob("*.json")) == [1, 2, 3, 4, 5, 6]
