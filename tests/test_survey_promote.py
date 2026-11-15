"""Tests for pipeline/survey/promote.py: picking candidates from the leaderboard or a tile file, the arguments,
and the commands of the dry run (fetch.py --ra/--dec/--fov/--name, analyze.py <target id>, evidence.py). --run is
tested with a fake runner: nothing is downloaded, no network.

    .venv/bin/python -m pytest tests/test_survey_promote.py -q
"""
import io
import json
import shlex
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
from survey import promote as P  # noqa: E402
from survey.dedupe import propagate  # noqa: E402
from fov import position_id  # noqa: E402

WISE0855 = {"id": "10226-0001", "k5": 10226, "ra": 133.775209, "dec": -7.243461, "epoch": 2019.202, "pmra": -8125.0,
            "pmdec": 659.1, "pm": 8151.7, "pm_err": 14.28, "pm_snr": 571.0, "n_visits": 21, "w1": 16.7, "w2": 13.9,
            "w1w2": 2.86, "class": "unexplained", "rank": 1, "score": 4.2,
            "gaia": {"checked": True, "match": False, "source_id": None}}
KAPTEYN = {"id": "8545-0003", "k5": 8545, "ra": 77.95, "dec": -45.06, "epoch": 2019.2, "pmra": 6490.1,
           "pmdec": -5705.3, "pm": 8641.2, "class": "known (Gaia)", "rank": 2, "score": 1.0,
           "gaia": {"checked": True, "match": True, "source_id": "4810594479418041856"}}
SLOW = {"id": "1355-0004", "k5": 1355, "ra": 0.00001, "dec": 12.0, "epoch": 2019.0, "pmra": -300.0, "pmdec": 0.0,
        "pm": 300.0, "class": "unexplained", "rank": 3, "score": 3.0, "gaia": {"checked": True, "match": False}}
UNRANKED = {"id": "8545-0042", "k5": 8545, "ra": 78.1, "dec": -44.9, "epoch": 2019.0, "pmra": 200.0, "pmdec": 50.0,
            "pm": 206.2}


@pytest.fixture
def survey(tmp_path):
    d = tmp_path / "survey"
    (d / "tiles").mkdir(parents=True)
    (d / "leaderboard.json").write_text(json.dumps({"generated": "2026-11-15T00:00:00Z", "n_candidates": 3,
                                                    "candidates": [KAPTEYN, SLOW, WISE0855]}))
    (d / "tiles" / "8545.json").write_text(json.dumps({"k5": 8545, "movers": [dict(KAPTEYN), dict(UNRANKED)]}))
    return d


def run(argv, survey=None, runner=None, root=None):
    out = io.StringIO()
    args = list(argv) + (["--survey", str(survey)] if survey else []) + ["--python", "python3"]
    code = P.main(args, runner=runner or (lambda *a, **k: 0), root=root or ROOT, out=out)
    return code, out.getvalue()


# ---------------------------------------------------------------------------------------------- arguments
@pytest.mark.parametrize("argv", [[], ["--unexplained"], ["--top", "0"], ["--id", "1-1", "--unexplained"],
                                  ["--top", "x"], ["--bogus"]])
def test_bad_arguments_are_usage_errors(argv, capsys):
    assert P.main(argv, out=io.StringIO()) == P.EXIT_USAGE
    capsys.readouterr()


def test_parse_args_defaults():
    ns = P.parse_args(["--id", "10226-0001", "--id", "8545-0003"])
    assert ns.ids == ["10226-0001", "8545-0003"] and ns.top is None and not ns.run and not ns.json
    assert ns.survey == P.DEFAULT_SURVEY and ns.python == sys.executable


def test_help_exits_cleanly(capsys):
    assert P.main(["--help"], out=io.StringIO()) == P.EXIT_OK
    assert "--unexplained" in capsys.readouterr().out


# ---------------------------------------------------------------------------------------------- reading
def test_board_is_read_in_rank_order(survey):
    assert [m["id"] for m in P.load_board(survey / "leaderboard.json")] == ["10226-0001", "8545-0003", "1355-0004"]
    assert P.load_board(survey / "missing.json") == []


def test_candidate_from_the_leaderboard_or_its_tile_file(survey):
    assert P.find_candidate("10226-0001", survey)["rank"] == 1
    m = P.find_candidate(" 8545-0042 ", survey)
    assert m["pm"] == 206.2 and m["k5"] == 8545 and "rank" not in m
    assert P.find_candidate("8545-9999", survey) is None and P.find_candidate("nonsense", survey) is None
    assert P.find_candidate("9999-0001", survey) is None
    assert P.tile_of_id("10226-0001") == 10226 and P.tile_of_id("x-1") is None


def test_top_n_and_unexplained_only(survey):
    board = P.load_board(survey / "leaderboard.json")
    assert [m["id"] for m in P.select_top(board, 2)] == ["10226-0001", "8545-0003"]
    assert [m["id"] for m in P.select_top(board, 5, unexplained=True)] == ["10226-0001", "1355-0004"]


# ---------------------------------------------------------------------------------------------- the plan
def test_position_is_moved_to_the_middle_of_the_time_lapse():
    ra, dec = P.centre_position(WISE0855)
    want = propagate(WISE0855["ra"], WISE0855["dec"], WISE0855["pmra"], WISE0855["pmdec"], 2018.5 - 2019.202)
    assert P.WINDOW_CENTRE == 2018.5
    assert ra == pytest.approx(want[0], abs=1e-6) and dec == pytest.approx(want[1], abs=1e-6)
    assert ra > WISE0855["ra"], "moving west (pmra < 0), so it was further east 0.7 yr earlier"


def test_position_wraps_ra_and_keeps_motionless_candidates_in_place():
    ra, dec = P.centre_position(SLOW)                # 0.3"/yr west from RA 0.00001 for -0.5 yr -> east of 0
    assert 0 < ra < 0.001
    still = dict(SLOW, ra=10.0, pmra=0.0, pmdec=0.0)
    assert P.centre_position(still) == (10.0, 12.0)
    with pytest.raises(ValueError):
        P.centre_position({"id": "x", "ra": None, "dec": 1})


def test_field_is_wide_enough_for_the_whole_path():
    assert P.field_for(SLOW) == 300                   # 4.8" path: the default field
    assert P.field_for(WISE0855) == 300               # 130" path + margins fits 300"
    assert P.field_for(dict(WISE0855, pm=12000.0)) == 300
    assert P.field_for(dict(WISE0855, pm=20000.0)) == 600
    assert P.field_for(dict(WISE0855, pm=60000.0)) == 900
    assert P.field_for({"pmra": 30000.0, "pmdec": 0.0}) == 600


def test_dry_run_prints_the_existing_pipeline_commands(survey):
    code, out = run(["--id", "10226-0001"], survey)
    assert code == 0
    assert out.startswith("# Dry run: nothing is downloaded. Add --run to run these (needs the network).")
    lines = [ln for ln in out.splitlines() if not ln.startswith("#") and ln.strip()]
    assert len(lines) == 3
    fetch = shlex.split(lines[0])
    ra, dec = P.centre_position(WISE0855)
    assert fetch[:2] == ["python3", "pipeline/fetch.py"]
    assert fetch[2:] == ["--ra", f"{ra:.6f}", "--dec", f"{dec:.6f}", "--fov", "300", "--name",
                         "Survey candidate 10226-0001"]
    tid = position_id(float(fetch[3]), float(fetch[5]), 300)        # what fetch.py add_position() will compute
    assert lines[1] == f"python3 pipeline/analyze.py {tid}" and lines[2] == "python3 pipeline/evidence.py"
    assert f"observatory.html?target={tid}" in out and "No Gaia DR3 match in the survey" in out


def test_known_gaia_candidate_names_its_gaia_source(survey):
    code, out = run(["--id", "8545-0003"], survey)
    assert code == 0 and "Gaia DR3 4810594479418041856 matched in the survey" in out


def test_not_checked_candidate_says_so(survey):
    m = dict(WISE0855, **{"class": "not checked", "gaia": {"checked": False}})
    assert any(n.startswith("Not checked against Gaia DR3") for n in P.plan(m)["notes"])


def test_top_unexplained_plans_each_once(survey):
    code, out = run(["--top", "5", "--unexplained", "--id", "10226-0001"], survey)
    assert code == 0
    assert out.count("pipeline/fetch.py") == 2 and "1355-0004" in out and "8545-0003" not in out


def test_json_plan(survey):
    code, out = run(["--id", "8545-0003", "--id", "8545-0042", "--json", "--fov", "600"], survey)
    data = json.loads(out)
    assert code == 0 and data["dry_run"] is True and [p["id"] for p in data["plans"]] == ["8545-0003", "8545-0042"]
    p = data["plans"][0]
    assert p["fov"] == 600 and p["target"].endswith("_f600") and p["commands"][0][-1] == "Survey candidate 8545-0003"
    assert p["open"] == f"observatory.html?target={p['target']}"


def test_unknown_candidate_fails(survey):
    code, out = run(["--id", "1-0001"], survey)
    assert code == P.EXIT_FAILED and "no candidate 1-0001" in out
    code, out = run(["--id", "1-0001", "--id", "10226-0001"], survey)
    assert code == P.EXIT_FAILED and "pipeline/fetch.py" in out, "the known one is still planned"


def test_no_unexplained_candidates_says_so(tmp_path):
    (tmp_path / "leaderboard.json").write_text(json.dumps({"candidates": [KAPTEYN]}))
    code, out = run(["--top", "3", "--unexplained"], tmp_path)
    assert code == P.EXIT_FAILED and "none unexplained" in out


# ---------------------------------------------------------------------------------------------- --run
def test_run_executes_the_commands_in_order_from_the_repo_root(survey, tmp_path):
    calls = []
    root = tmp_path / "repo"

    def runner(cmd, cwd=None):
        calls.append((cmd, cwd))
        if cmd[1].endswith("analyze.py"):
            (root / "app" / "data" / cmd[2]).mkdir(parents=True)
            (root / "app" / "data" / cmd[2] / "target.json").write_text("{}")
        return 0
    code, out = run(["--id", "10226-0001", "--run"], survey, runner=runner, root=root)
    assert code == 0, out
    assert [Path(c[1]).name for c, _ in calls] == ["fetch.py", "analyze.py", "evidence.py"]
    assert all(cwd == str(root) for _, cwd in calls) and "ready: app/observatory.html?target=" in out
    assert "Dry run" not in out


def test_run_stops_at_the_first_failure(survey, tmp_path):
    calls = []

    def runner(cmd, cwd=None):
        calls.append(cmd)
        return 1
    code, out = run(["--id", "10226-0001", "--run"], survey, runner=runner, root=tmp_path)
    assert code == P.EXIT_FAILED and len(calls) == 1 and "fetch.py failed (exit 1)" in out


def test_run_notices_analyze_writing_nothing(survey, tmp_path):
    code, out = run(["--id", "10226-0001", "--run"], survey, runner=lambda c, cwd=None: 0, root=tmp_path)
    assert code == P.EXIT_FAILED and "analyze.py wrote no app/data/" in out
