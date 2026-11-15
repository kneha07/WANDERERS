"""Runner tests with real worker processes (spawn) and a fake core: resume after a partial run or a kill -9,
failed-tile retry on the next run, network retries with backoff, per-tile timeout, worker crash, memory limit,
maxtasksperchild, real parallelism, --max-hours, disk guard, lock, periodic publishing, Ctrl-C and SIGTERM.
The fake core (tests/test_survey_run_fakes.py) logs every call, so the tests see exactly which tiles ran."""
import json
import os
import re
import signal
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "tests"))
from survey import run as R  # noqa: E402
import test_survey_run_fakes as fakes  # noqa: E402

GB = R.GB
RUN_PY = ROOT / "pipeline" / "survey" / "run.py"


@pytest.fixture
def env(tmp_path, monkeypatch):
    spec = tmp_path / "spec.json"
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("SURVEY_FAKE_SPEC", str(spec))
    fakes.write_spec(spec, log=str(log))
    fakes.XMATCH_CALLS.clear()
    ns = types.SimpleNamespace(tmp=tmp_path, out=tmp_path / "out", cache=tmp_path / "cache", log=log, spec=spec)
    ns.set_spec = lambda **kw: fakes.write_spec(spec, log=str(log), **kw)
    ns.starts = lambda tag=None: [c["k5"] for c in fakes.calls(log, "start", tag)]
    return ns


def make_cfg(env, tiles="list:1-6", **kw):
    base = dict(tiles=tiles, workers=2, out=env.out, cache=env.cache, no_gaia=True, publish_every=0,
                process_fn=fakes.process_tile, rank_fn=fakes.rank, xmatch_fn=fakes.crossmatch_gaia, log_file=None,
                backoff=0.01, read_backoff=0.01, heartbeat=3600, min_free_mem_gb=0, rss_check=0.1, disk_check=3600,
                manifest_every=0.2)
    base.update(kw)
    return R.Config(**base)


def run(env, deps=None, **kw):
    deps = dict(deps or {})
    deps.setdefault("disk_free", lambda p: 100 * GB)
    r = R.Runner(make_cfg(env, **kw), **deps)
    r.run()
    return r


def manifest(env):
    return json.loads((env.out / "manifest.json").read_text())


def tile_files(env):
    return sorted(int(p.stem) for p in (env.out / "tiles").glob("*.json"))


def intervals(env):
    starts = {c["k5"]: c["t"] for c in fakes.calls(env.log, "start")}
    ends = {c["k5"]: c["t"] for c in fakes.calls(env.log, "end")}
    return {k: (starts[k], ends[k]) for k in ends}


def overlapping(iv):
    xs = sorted(iv.values())
    return any(b[0] < a[1] for a, b in zip(xs, xs[1:]))


# ------------------------------------------------------------------------------------------------ basic runs
def test_run_processes_all_tiles_and_publishes(env):
    r = run(env)
    assert r.exit_code == 0 and sorted(r.processed) == [1, 2, 3, 4, 5, 6]
    assert tile_files(env) == [1, 2, 3, 4, 5, 6] and sorted(env.starts()) == [1, 2, 3, 4, 5, 6]
    m = manifest(env)
    assert sorted(map(int, m["done"])) == [1, 2, 3, 4, 5, 6] and m["failed"] == {}
    run1 = m["runs"][-1]
    assert run1["stopped"] == "complete" and run1["tiles"] == 6 and run1["detections"] == 6_021_000
    assert run1["ended"] and run1["wall_seconds"] > 0
    assert all(d["bytes"] == (env.out / "tiles" / f"{k}.json").stat().st_size for k, d in m["done"].items())
    s = json.loads((env.out / "summary.json").read_text())
    assert s["tiles_done"] == 6 and s["movers"] == 9 and s["tiles_per_hour"] > 0
    assert not (env.out / ".run.lock").exists()
    assert not list((env.out / "tiles").glob(".*tmp*"))


def test_rerun_skips_finished_tiles(env):
    run(env)
    env.set_spec(tag="again")
    r = run(env)
    assert r.exit_code == 0 and r.processed == [] and env.starts("again") == []
    m = manifest(env)
    assert len(m["runs"]) == 2 and m["runs"][-1]["tiles"] == 0


def test_resume_after_partial_run_processes_only_missing(env):
    r1 = run(env, tiles="list:1-10", max_tiles=4, workers=1)
    assert sorted(r1.processed) == [1, 2, 3, 4]
    env.set_spec(tag="resume")
    r2 = run(env, tiles="list:1-10")
    assert sorted(env.starts("resume")) == [5, 6, 7, 8, 9, 10]
    assert tile_files(env) == list(range(1, 11)) and r2.exit_code == 0


def test_resume_trusts_tile_files_over_a_lost_manifest(env):
    run(env, tiles="list:1-4")
    (env.out / "manifest.json").write_text("{ truncated")
    env.set_spec(tag="second")
    r = run(env, tiles="list:1-6")
    assert sorted(env.starts("second")) == [5, 6] and r.exit_code == 0
    assert list(env.out.glob("manifest.corrupt-*.json"))
    assert sorted(map(int, manifest(env)["done"])) == [1, 2, 3, 4, 5, 6]


def test_tile_deleted_by_hand_is_redone(env):
    run(env, tiles="list:1-3")
    (env.out / "tiles" / "2.json").unlink()
    env.set_spec(tag="redo")
    run(env, tiles="list:1-3")
    assert env.starts("redo") == [2]


def test_validation_order_runs_validation_tiles_first(env, monkeypatch):
    monkeypatch.setitem(sys.modules, "survey.tiles", None)
    r = run(env, tiles="list:1-3", order="validation-first", workers=1, max_tiles=10)
    assert env.starts()[:9] == [7945, 8545, 10226, 9509, 6865, 1355, 10397, 3325, 11391]
    expected_10th = R.order_tiles([1, 2, 3], "validation-first", 1)[9]  # seeded-random pick of the rest
    assert env.starts()[9:] == [expected_10th] and r.exit_code == 0     # --max-tiles 10


# ------------------------------------------------------------------------------------------------ failures
def test_failed_tile_recorded_then_retried_next_run(env):
    env.set_spec(fail=[3])
    r = run(env)
    assert r.exit_code == 1 and 3 not in tile_files(env) and len(tile_files(env)) == 5
    f = manifest(env)["failed"]["3"]
    assert f["kind"] == "error" and "ValueError: synthetic failure in tile 3" in f["error"] and f["attempts"] == 1
    assert manifest(env)["runs"][-1]["failed"] == 1
    env.set_spec(tag="retry")
    r = run(env)
    assert env.starts("retry") == [3] and r.exit_code == 0
    m = manifest(env)
    assert m["failed"] == {} and m["done"]["3"]["attempts"] == 2


def test_network_errors_retried_with_backoff_within_run(env):
    env.set_spec(net_fail={"4": 2})
    r = run(env, retries=3)
    assert r.exit_code == 0 and env.starts().count(4) == 3 and r.retried == [4, 4]
    assert manifest(env)["done"]["4"]["attempts"] == 3


def test_network_retries_exhausted_recorded_as_network(env):
    env.set_spec(net_fail={"4": 99})
    r = run(env, retries=1)
    f = manifest(env)["failed"]["4"]
    assert r.exit_code == 1 and f["kind"] == "network" and f["attempts"] == 2 and "SLOW_DOWN" in f["error"]
    assert env.starts().count(4) == 2 and len(tile_files(env)) == 5


def test_timeout_kills_stuck_tile_and_continues(env):
    env.set_spec(sleep={"2": 120})
    t0 = time.monotonic()
    r = run(env, tile_timeout=1.5)
    assert time.monotonic() - t0 < 30
    f = manifest(env)["failed"]["2"]
    assert f["kind"] == "timeout" and "timed out after" in f["error"] and "worker killed" in f["error"]
    assert tile_files(env) == [1, 3, 4, 5, 6] and r.exit_code == 1


def test_worker_crash_costs_only_its_tile(env):
    env.set_spec(crash=[3])
    r = run(env)
    f = manifest(env)["failed"]["3"]
    assert f["kind"] == "crash" and "exit code 3" in f["error"]
    assert tile_files(env) == [1, 2, 4, 5, 6] and r.exit_code == 1


def test_memory_limit_kills_oversized_worker(env):
    env.set_spec(sleep={"5": 60})
    t0 = time.monotonic()
    r = run(env, deps={"rss": lambda pids: {p: 50 * GB for p in pids}}, tiles="list:5", max_worker_gb=3.0)
    assert time.monotonic() - t0 < 20
    f = manifest(env)["failed"]["5"]
    assert f["kind"] == "memory" and "50.00 GB" in f["error"] and r.exit_code == 1


def test_low_memory_starts_tiles_one_at_a_time(env):
    env.set_spec(default_sleep=0.3)
    r = run(env, deps={"mem_available": lambda: 100 * 1024 ** 2}, tiles="list:1-4", workers=3, min_free_mem_gb=1.0)
    assert r.exit_code == 0 and tile_files(env) == [1, 2, 3, 4]
    assert not overlapping(intervals(env))


def test_too_many_consecutive_failures_stops_scheduling(env):
    r = run(env, tiles="list:1-20", workers=1, process_fn=fakes.process_tile_always_fails,
            max_consecutive_failures=3)
    m = manifest(env)
    assert len(m["failed"]) == 3 and m["runs"][-1]["stopped"] == "too-many-failures" and r.exit_code == 1


def test_setup_error_when_core_cannot_be_imported(env):
    r = run(env, process_fn="survey.no_such_core:process_tile")
    assert r.exit_code == R.EXIT_SETUP and not (env.out / "manifest.json").exists()


# ------------------------------------------------------------------------------------------------ pool behaviour
def test_maxtasksperchild_recycles_worker_processes(env):
    r = run(env, workers=1, maxtasksperchild=2)
    pids = [c["pid"] for c in fakes.calls(env.log, "start")]
    assert len(set(pids)) == 3 and r.exit_code == 0
    assert pids[0] == pids[1] and pids[2] == pids[3] and pids[1] != pids[2]


def test_workers_really_run_in_parallel(env):
    env.set_spec(default_sleep=1.0)
    r = run(env, tiles="list:1-4", workers=4)
    iv = intervals(env)
    assert r.exit_code == 0 and len(iv) == 4 and overlapping(iv)
    assert len({c["pid"] for c in fakes.calls(env.log, "start")}) == 4
    busy = sum(b - a for a, b in iv.values())                         # >= 4 s of tile work ...
    span = max(b for _, b in iv.values()) - min(a for a, _ in iv.values())
    assert span < 0.75 * busy                                         # ... done in much less wall time


def test_pool_size_never_exceeds_tiles(env):
    r = run(env, tiles="list:1", workers=6)
    assert r.exit_code == 0 and len({c["pid"] for c in fakes.calls(env.log, "start")}) == 1


def test_worker_pool_kill_and_replace_directly(env):
    env.set_spec(sleep={"9": 60})
    pool = R.WorkerPool(1, R.WorkerConfig(tiles_dir=str(env.tmp / "tiles"), process_fn=fakes.process_tile), 3)
    try:
        slot = pool.assign(pool.idle()[0], 9, 1)
        old_pid = slot.pid
        time.sleep(0.5)
        pool.kill(slot)
        assert not R._pid_alive(old_pid)
        new = pool.slots[0]
        assert new.pid != old_pid and new.task is None
        pool.assign(new, 1, 1)
        events = []
        deadline = time.monotonic() + 20
        while not events and time.monotonic() < deadline:
            events = [e for e in pool.poll(0.2) if e[0] == "done"]
        assert events and events[0][2] == 1 and events[0][4]["n_movers"] == 1
    finally:
        pool.shutdown()
    assert pool.slots == []


# ------------------------------------------------------------------------------------------------ limits & guards
def test_max_hours_stops_scheduling_and_finishes_cleanly(env):
    env.set_spec(default_sleep=0.4)
    r = run(env, tiles="list:1-30", workers=1, max_hours=1.5 / 3600)
    m = manifest(env)
    assert m["runs"][-1]["stopped"] == "max-hours" and r.exit_code == 0
    assert 1 <= len(r.processed) < 30 and len(tile_files(env)) == len(r.processed)
    started, ended = env.starts(), [c["k5"] for c in fakes.calls(env.log, "end")]
    assert sorted(started) == sorted(ended)                          # running tiles were finished, not killed
    assert json.loads((env.out / "summary.json").read_text())["tiles_done"] == len(r.processed)


def test_disk_guard_refuses_to_start(env):
    r = run(env, deps={"disk_free": lambda p: int(0.5 * GB)})
    assert r.exit_code == R.EXIT_DISK and env.starts() == []
    assert not (env.out / "manifest.json").exists() and tile_files(env) == []


def test_disk_filling_up_mid_run_stops_scheduling(env):
    env.set_spec(default_sleep=0.3)
    calls = []

    def disk(p):
        calls.append(p)
        return 100 * GB if len(calls) <= 3 else int(0.2 * GB)
    r = run(env, deps={"disk_free": disk}, tiles="list:1-20", workers=1, disk_check=0.25)
    m = manifest(env)
    assert r.exit_code == R.EXIT_DISK and m["runs"][-1]["stopped"] == "disk"
    assert 1 <= len(r.processed) < 20


def test_second_runner_on_same_out_is_refused(env):
    holder = subprocess.Popen(["sleep", "30"])
    try:
        env.out.mkdir(parents=True)
        (env.out / ".run.lock").write_text(f"{holder.pid} 2026-01-01T00:00:00Z\n")
        r = run(env)
        assert r.exit_code == R.EXIT_LOCKED and env.starts() == []
        assert (env.out / ".run.lock").exists()
    finally:
        holder.kill()
        holder.wait()


def test_stale_lock_is_taken_over(env):
    dead = subprocess.Popen(["true"])
    dead.wait()
    env.out.mkdir(parents=True)
    (env.out / ".run.lock").write_text(f"{dead.pid} 2026-01-01T00:00:00Z\n")
    r = run(env)
    assert r.exit_code == 0 and not (env.out / ".run.lock").exists()


def test_periodic_publishing_during_run(env):
    env.set_spec(default_sleep=0.25)
    r = run(env, tiles="list:1-8", workers=1, publish_every=0.4 / 60)
    assert r.n_publishes >= 3 and r.publish_errors == 0           # at least 2 mid-run + the final one
    assert json.loads((env.out / "summary.json").read_text())["tiles_done"] == 8


def test_heartbeat_logs_worker_memory(env):
    env.set_spec(default_sleep=1.2)
    logf = env.tmp / "run.log"
    R.setup_logging(logf)
    try:
        run(env, tiles="list:1-2", heartbeat=0.3, rss_check=0.1)
    finally:
        R.setup_logging(None)
    text = logf.read_text()
    status = [line for line in text.splitlines() if "status:" in line]
    assert status and all("GB free" in line for line in status)
    # e.g. "status: 2 running [1 1s 0.04GB, 2 1s 0.04GB] | ...": tile, elapsed and RSS of each worker
    assert any(re.search(r"running \[\d+ \d+s \d+\.\d\dGB", line) for line in status)
    assert re.search(r"tile 1 done in .* worker \d+ peak \d+\.\d\d GB", text)


def test_publish_failure_never_stops_the_run(env, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("publisher bug")
    monkeypatch.setattr(R, "publish", broken)
    r = run(env, tiles="list:1-3")
    assert r.exit_code == 0 and r.publish_errors == 1 and tile_files(env) == [1, 2, 3]


def test_run_with_gaia_crossmatches_at_the_end(env):
    run(env, tiles="list:1-3", no_gaia=False)
    s = json.loads((env.out / "summary.json").read_text())
    assert sorted(len(c) for c in fakes.XMATCH_CALLS) == [1, 2, 3] and s["unexplained"] == 2


# ------------------------------------------------------------------------------------------------ kill -9, SIGTERM, Ctrl-C
def cli(env, *extra, tiles="list:0-11", workers=2):
    return [sys.executable, str(RUN_PY), "--tiles", tiles, "--workers", str(workers), "--out", str(env.out),
            "--cache", str(env.cache), "--log-file", str(env.tmp / "run.log"), "--no-gaia", "--publish-every", "0",
            "--min-free-mem-gb", "0", "--min-free-disk-gb", "0.01", "--process-fn",
            "test_survey_run_fakes:process_tile", "--rank-fn", "test_survey_run_fakes:rank", *extra]


def popen(env, cmd):
    e = dict(os.environ, PYTHONPATH=str(ROOT / "tests"), SURVEY_FAKE_SPEC=str(env.spec))
    return subprocess.Popen(cmd, cwd=ROOT, env=e, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                            start_new_session=True)


def wait_for(cond, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.05)
    return False


def all_dead(pids, timeout=10.0):
    def gone():
        return not any(R._pid_alive(p) for p in pids)
    return wait_for(gone, timeout)


def test_kill_minus_9_mid_run_then_rerun_processes_only_missing(env):
    env.set_spec(default_sleep=0.4, tag="first")
    p = popen(env, cli(env))
    try:
        assert wait_for(lambda: len(list((env.out / "tiles").glob("*.json"))) >= 3 if (env.out / "tiles").exists()
                        else False)
    finally:
        os.killpg(p.pid, signal.SIGKILL)                              # main and workers, like a power cut
        p.wait()
    assert all_dead({c["pid"] for c in fakes.calls(env.log, "start")})
    for f in (env.out / "tiles").glob("*.json"):                      # no partial JSON
        json.loads(f.read_text())
    done_before = set(tile_files(env))
    assert 3 <= len(done_before) < 12
    env.set_spec(tag="second")
    p2 = popen(env, cli(env))
    assert p2.wait(timeout=60) == 0, p2.stderr.read()
    assert set(env.starts("second")) == set(range(12)) - done_before
    assert len(env.starts("second")) == len(set(env.starts("second")))
    assert tile_files(env) == list(range(12))
    runs = manifest(env)["runs"]
    assert len(runs) == 2 and runs[0]["ended"] is None and runs[1]["stopped"] == "complete"


def test_orphaned_workers_finish_their_tile_and_exit(env):
    env.set_spec(default_sleep=1.5)
    p = popen(env, cli(env, tiles="list:0-9"))
    assert wait_for(lambda: len(env.starts()) >= 2)
    started = set(env.starts())
    os.kill(p.pid, signal.SIGKILL)                                    # main only: workers lose their parent
    p.wait()
    pids = {c["pid"] for c in fakes.calls(env.log, "start")}
    assert all_dead(pids, timeout=20)                                 # nobody left running all night
    for f in (env.out / "tiles").glob("*.json"):
        json.loads(f.read_text())
    assert set(tile_files(env)) <= set(env.starts()) and started <= set(env.starts())
    assert len(env.starts()) <= len(started) + 2                      # no new tiles taken after the parent died


def test_sigterm_writes_manifest_and_stops_workers(env):
    env.set_spec(default_sleep=5.0)
    p = popen(env, cli(env, tiles="list:0-5"))
    assert wait_for(lambda: len(env.starts()) >= 2)
    p.send_signal(signal.SIGTERM)                                     # main process only
    assert p.wait(timeout=30) == R.EXIT_SIGTERM
    m = manifest(env)
    assert m["runs"][-1]["stopped"] == "signal" and m["runs"][-1]["ended"]
    assert all_dead({c["pid"] for c in fakes.calls(env.log, "start")})
    assert not (env.out / ".run.lock").exists() and tile_files(env) == []


def test_ctrl_c_finishes_running_tiles_then_publishes(env):
    env.set_spec(default_sleep=1.5)
    p = popen(env, cli(env, tiles="list:0-9"))
    assert wait_for(lambda: len(env.starts()) >= 2)
    os.killpg(p.pid, signal.SIGINT)                                   # the whole group, like a terminal
    assert p.wait(timeout=30) == R.EXIT_SIGINT
    started, ended = env.starts(), [c["k5"] for c in fakes.calls(env.log, "end")]
    assert sorted(started) == sorted(ended) and len(started) < 10    # workers ignored Ctrl-C and finished
    assert tile_files(env) == sorted(started)
    assert manifest(env)["runs"][-1]["stopped"] == "interrupted"
    assert json.loads((env.out / "summary.json").read_text())["tiles_done"] == len(started)
