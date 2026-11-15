"""The SPHEREx stage inside the survey runner (publish, cache, budget, CLI) and the ranking. No network: the stage
is replaced by fakes with the same signature as survey.spherex.check_tile."""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "pipeline", ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import test_survey_run_fakes as fakes  # noqa: E402
from survey import rank as RK  # noqa: E402
from survey import run as R  # noqa: E402
from survey import spherex as SX  # noqa: E402

CALLS: list = []
TILES = [1, 2, 3, 7]                      # 1, 2, 3, 3 movers; even mover index = Gaia match (fakes.gaia_for)


def sx_result(k5, i, confirmed=None, **kw):
    d = SX.unchecked(None)
    d.update(checked=True, detected=True, confirmed=(i == 1) if confirmed is None else confirmed, snr=20.0,
             offset_arcsec=1.0, offset_err=2.0, expected_offset=30.0, at_predicted=True, epoch=2025.883, tile=k5,
             notes=["ok"])
    d.update(kw)
    return d


def fake_sx(k5, movers, deadline=None):
    CALLS.append((k5, [m["id"] for m in movers]))
    return [sx_result(k5, int(m["id"].split("-")[1])) for m in movers]


def fake_sx_network(k5, movers, deadline=None):
    CALLS.append((k5, [m["id"] for m in movers]))
    return [SX.unchecked("network: timed out") for _ in movers]


def fake_sx_raises(k5, movers, deadline=None):
    CALLS.append((k5, [m["id"] for m in movers]))
    raise RuntimeError("stage exploded")


@pytest.fixture
def env(tmp_path, monkeypatch):
    spec = tmp_path / "spec.json"
    monkeypatch.setenv("SURVEY_FAKE_SPEC", str(spec))
    fakes.write_spec(spec, log=str(tmp_path / "calls.jsonl"))
    fakes.XMATCH_CALLS.clear()
    CALLS.clear()
    ns = types.SimpleNamespace(tmp=tmp_path, out=tmp_path / "out", cache=tmp_path / "cache")
    for k in TILES:
        R.atomic_write_json(ns.out / "tiles" / f"{k}.json", R.compact_tile(fakes.fake_tile(k), k, 1.0))
    return ns


def publish(env, **kw):
    args = dict(cache_dir=env.cache, use_gaia=True, xmatch_fn=fakes.crossmatch_gaia, rank_fn=fakes.rank, runs=[],
                use_spherex=True, spherex_fn=fake_sx)
    args.update(kw)
    return R.publish(env.out, **args)


def board(env):
    return json.loads((env.out / "leaderboard.json").read_text())["candidates"]


def unexplained_ids():
    return sorted(f"{k}-{i:04d}" for k in TILES for i in range(fakes.n_movers_of(k)) if i % 2 == 1)


# ------------------------------------------------------------------------------------------- publish
def test_rows_get_a_spherex_dict_and_the_summary_counts_it(env):
    s = publish(env)
    rows = board(env)
    assert all(list(r["spherex"]) == R.SPHEREX_KEYS for r in rows)
    assert s["spherex_checked"] == len(unexplained_ids()) == 3
    assert s["spherex_confirmed"] == 3                          # every index-1 mover is "confirmed" by the fake
    assert list(s)[-2:] == ["spherex_checked", "spherex_confirmed"]
    assert R.SPHEREX_KEYS == SX.SPHEREX_KEYS


def test_only_movers_gaia_does_not_explain_are_looked_up(env):
    publish(env)
    sent = sorted(i for _, ids in CALLS for i in ids)
    assert sent == unexplained_ids()
    known = [r for r in board(env) if r["gaia"]["match"]]
    assert known and all(r["spherex"]["checked"] is False and r["spherex"]["error"] is None
                         and r["spherex"]["notes"] == [R.SPHEREX_SKIP_NOTE] for r in known)


def test_spherex_all_looks_up_every_mover(env):
    s = publish(env, spherex_all=True)
    assert sum(len(ids) for _, ids in CALLS) == sum(fakes.n_movers_of(k) for k in TILES)
    assert s["spherex_checked"] == 9


def test_answers_are_cached_per_tile(env):
    publish(env)
    n = len(CALLS)
    assert n == 3 and sorted((env.cache / "spherex_tiles").glob("*.json"))
    s = publish(env)
    assert len(CALLS) == n and s["spherex_checked"] == 3        # second publish: all from the cache


def test_cache_is_dropped_when_a_mover_changes(env):
    publish(env)
    t = json.loads((env.out / "tiles" / "3.json").read_text())
    t["movers"][1]["pmra"] += 100.0
    R.atomic_write_json(env.out / "tiles" / "3.json", t)
    CALLS.clear()
    publish(env)
    assert [k for k, _ in CALLS] == [3]


def test_network_failures_are_not_cached_and_stop_after_the_fail_limit(env):
    s = publish(env, spherex_fn=fake_sx_network, spherex_fail_limit=2)
    assert len(CALLS) == 2                                       # tiles 2 and 3 failed: tile 7 is left alone
    assert s["spherex_checked"] == 0
    assert any("SPHEREx check is still pending for 3 movers" in t for t in s["limits"])
    assert not (env.cache / "spherex_tiles").exists() or not list((env.cache / "spherex_tiles").glob("*.json"))
    CALLS.clear()
    publish(env)
    assert len(CALLS) == 3                                       # tried again at the next publish


def test_a_spent_budget_makes_no_calls_and_says_so(env):
    s = publish(env, spherex_budget_s=0)
    assert CALLS == []
    unex = [r for r in board(env) if not r["gaia"]["match"]]
    assert all(r["spherex"]["error"] == "time budget" for r in unex)
    assert any("still pending" in t for t in s["limits"])


def test_off_by_default_in_the_library_call(env):
    s = R.publish(env.out, cache_dir=env.cache, use_gaia=True, xmatch_fn=fakes.crossmatch_gaia, rank_fn=fakes.rank,
                  runs=[])
    assert CALLS == [] and all("spherex" not in r for r in board(env))
    assert s["spherex_checked"] == 0 and s["spherex_confirmed"] == 0
    assert any("SPHEREx check was switched off" in t for t in s["limits"])


def test_a_stage_that_raises_marks_movers_unchecked_and_is_retried(env):
    s = publish(env, spherex_fn=fake_sx_raises)
    unex = [r for r in board(env) if not r["gaia"]["match"]]
    assert all(r["spherex"]["checked"] is False and r["spherex"]["error"].startswith("stage failed") for r in unex)
    assert s["spherex_checked"] == 0
    CALLS.clear()
    publish(env)
    assert len(CALLS) == 3


def test_spherex_tile_helper_checks_the_answer_length():
    def short(k5, movers, deadline=None):
        return []
    out, complete = R.spherex_tile(short, 5, [{"id": "a"}], [True], None)
    assert complete is False and out[0]["error"].startswith("stage failed")
    out, complete = R.spherex_tile(short, 5, [{"id": "a"}], [False], None)
    assert complete is True and out[0]["notes"] == [R.SPHEREX_SKIP_NOTE]


def test_method_and_limits_describe_neowise_plus_spherex(env):
    s = publish(env)
    assert "SPHEREx" in s["method"] and "2025-26" in s["method"] and "NEOWISE" in s["method"]
    assert any("no public source catalogue" in t and "13 arcseconds" in t for t in s["limits"])


# ------------------------------------------------------------------------------------------- CLI and runner
def test_cli_switches():
    c = R.parse_args(["--tiles", "validation"])
    assert c.no_spherex is False and c.spherex_budget == 5.0 and c.spherex_all is False
    assert c.spherex_fn == "survey.spherex:check_tile"
    c = R.parse_args(["--tiles", "validation", "--no-spherex", "--spherex-budget", "2", "--spherex-all"])
    assert c.no_spherex and c.spherex_budget == 2.0 and c.spherex_all


def test_runner_passes_the_spherex_settings_to_publish(env, monkeypatch):
    seen = []
    monkeypatch.setattr(R, "publish", lambda out, **kw: seen.append(kw) or {})
    cfg = R.Config(tiles="list:1", out=env.out, cache=env.cache, log_file=None, spherex_budget=2.0)
    r = R.Runner(cfg)
    r._publish(final=False, runs=[])
    r._publish(final=True, runs=[])
    assert seen[0]["use_spherex"] is True and seen[0]["spherex_budget_s"] == 120.0
    assert seen[1]["spherex_budget_s"] is None and seen[0]["spherex_fn"] == "survey.spherex:check_tile"
    R.Runner(R.Config(tiles="list:1", out=env.out, cache=env.cache, log_file=None, no_spherex=True))._publish(True, [])
    assert seen[2]["use_spherex"] is False


# ------------------------------------------------------------------------------------------- ranking
def ranked_mover(**sx):
    m = {"id": "1-0001", "k5": 1, "ra": 10.0, "dec": 10.0, "epoch": 2019.0, "pmra": 900.0, "pmdec": 0.0, "pm": 900.0,
         "pm_err": 5.0, "pm_snr": 50.0, "chi2r": 1.0, "n_visits": 18, "span_yr": 10.0, "w1": 15.0, "w2": 13.5,
         "w1w2": 1.5, "flags": [], "gaia": {"checked": True, "match": False}}
    if sx:
        d = SX.unchecked(None)
        d.update(sx)
        m["spherex"] = d
    return m


def test_confirmed_adds_half_a_point_with_a_reason():
    base, _ = RK.score(ranked_mover())
    sc, reasons = RK.score(ranked_mover(checked=True, detected=True, at_predicted=True, confirmed=True,
                                        offset_arcsec=1.2, offset_err=2.0))
    assert sc == pytest.approx(base + 0.5)
    assert any(r.startswith("SPHEREx sees it in 2025–26 where its NEOWISE motion predicts (1″ ± 2″") for r in reasons)


def test_seen_but_too_slow_and_not_where_predicted_cost_nothing():
    base, _ = RK.score(ranked_mover())
    sc, reasons = RK.score(ranked_mover(checked=True, detected=True, at_predicted=True, confirmed=False))
    assert sc == base and any("moves too little" in r for r in reasons)
    sc, reasons = RK.score(ranked_mover(checked=True, detected=True, at_predicted=False))
    assert sc == base and any("does not see it where its motion predicts" in r for r in reasons)
    sc, reasons = RK.score(ranked_mover(checked=True, detected=False))
    assert sc == base and any("Too faint for SPHEREx" in r for r in reasons)


def test_methane_hint_is_a_reason_without_points():
    base, _ = RK.score(ranked_mover())
    sc, reasons = RK.score(ranked_mover(checked=True, detected=True, at_predicted=True,
                                        indices={"methane": True}))
    assert sc == base and any("methane" in r and "hint" in r for r in reasons)


def test_unchecked_or_missing_spherex_adds_no_term():
    names = {t["term"] for t in RK.score_terms(ranked_mover(checked=False, error="network: x"))}
    assert "spherex" not in names and "spherex_methane" not in names
    assert RK.score(ranked_mover())[0] == RK.score(ranked_mover(checked=False))[0]


def test_spherex_terms_are_documented_and_weighted():
    assert RK.WEIGHTS["spherex_confirmed"] == 0.5
    for name in ("spherex", "spherex_methane"):
        assert f"    {name} " in RK.score.__doc__


def test_confirmed_candidate_ranks_first_among_equals():
    a = ranked_mover(checked=True, detected=True, at_predicted=True, confirmed=False)
    b = dict(ranked_mover(checked=True, detected=True, at_predicted=True, confirmed=True), id="1-0002")
    out = RK.rank([a, b])
    assert [m["id"] for m in out] == ["1-0002", "1-0001"]


def test_real_rank_in_publish_carries_the_spherex_reason(env):
    publish(env, rank_fn=RK.rank)
    unex = [r for r in board(env) if r["spherex"]["confirmed"]]
    assert unex and all(any(x.startswith("SPHEREx sees it") for x in r["reasons"]) for r in unex)


# ------------------------------------------------- each stage spends only its own budget (a slow SPHEREx stage
# must not use up the Gaia budget: both run tile by tile in the same pass)
class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _slow_stages(clock, sx_cost, gaia_cost):
    def sx(k5, movers, deadline=None):
        CALLS.append((k5, [m["id"] for m in movers]))
        clock.t += sx_cost
        return [sx_result(k5, int(m["id"].split("-")[1])) for m in movers]

    def xmatch(movers, cache_dir, **kw):
        clock.t += gaia_cost
        return fakes.crossmatch_gaia(movers, cache_dir, **kw)
    return sx, xmatch


def test_a_slow_spherex_stage_does_not_use_up_the_gaia_budget(env):
    clock = FakeClock()
    sx, xmatch = _slow_stages(clock, sx_cost=500.0, gaia_cost=1.0)
    s = R.publish(env.out, cache_dir=env.cache, use_gaia=True, xmatch_fn=xmatch, rank_fn=fakes.rank, runs=[],
                  use_spherex=True, spherex_fn=sx, gaia_budget_s=60.0, spherex_budget_s=10_000.0, clock=clock)
    assert s["gaia_unchecked"] == 0, "every tile still got its Gaia check"


def test_a_slow_gaia_check_does_not_use_up_the_spherex_budget(env):
    clock = FakeClock()
    sx, xmatch = _slow_stages(clock, sx_cost=1.0, gaia_cost=500.0)
    R.publish(env.out, cache_dir=env.cache, use_gaia=True, xmatch_fn=xmatch, rank_fn=fakes.rank, runs=[],
              use_spherex=True, spherex_fn=sx, gaia_budget_s=10_000.0, spherex_budget_s=60.0, clock=clock)
    assert len(CALLS) == 3, "every tile with unexplained movers was looked up in SPHEREx"


def test_the_spherex_budget_still_stops_the_stage(env):
    clock = FakeClock()
    sx, xmatch = _slow_stages(clock, sx_cost=100.0, gaia_cost=0.0)
    R.publish(env.out, cache_dir=env.cache, use_gaia=True, xmatch_fn=xmatch, rank_fn=fakes.rank, runs=[],
              use_spherex=True, spherex_fn=sx, gaia_budget_s=None, spherex_budget_s=150.0, clock=clock)
    assert len(CALLS) == 2, "the budget is spent after the second tile"


def test_the_gaia_budget_still_stops_the_gaia_check(env):
    clock = FakeClock()
    sx, xmatch = _slow_stages(clock, sx_cost=0.0, gaia_cost=100.0)
    s = R.publish(env.out, cache_dir=env.cache, use_gaia=True, xmatch_fn=xmatch, rank_fn=fakes.rank, runs=[],
                  use_spherex=False, gaia_budget_s=150.0, clock=clock)
    assert s["gaia_unchecked"] > 0
