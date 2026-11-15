#!/usr/bin/env python3
"""Promote Sky Survey candidates to full WANDERERS targets (the step from "ranked list" to "a human investigates").

A candidate on the survey leaderboard is a NEOWISE track and a few numbers. A full WANDERERS target has the
WISE 2010 -> NEOWISE 2014-2024 -> SPHEREx 2025-26 time-lapse in the explorer (observatory.html), a measured
motion, a spectrum and an evidence card. This script prints (by default) or runs (--run) the existing commands
that prepare one, the same ones the web server runs for typed coordinates (fields.js):

    pipeline/fetch.py --ra RA --dec DEC --fov FOV --name NAME   download Gaia, SPHEREx, AllWISE and NEOWISE images
    pipeline/analyze.py <target id>                             frames, motion, spectrum
    pipeline/evidence.py                                        evidence card and app/data/index.json

then the target opens at observatory.html?target=<target id>.

Run from the repo root:

    python pipeline/survey/promote.py --id 10226-0001              # dry run: prints the commands
    python pipeline/survey/promote.py --top 5 --unexplained        # the 5 best unexplained candidates
    python pipeline/survey/promote.py --id 10226-0001 --run        # runs them (network: NASA IRSA, ESA Gaia)

The candidate comes from app/data/survey/leaderboard.json, or from its tile file (tiles/<k5>.json) when it is not
in the top list. Its position is moved with its own measured motion to WINDOW_CENTRE (midway between AllWISE 2010.5
and SPHEREx 2026.5) and the field is made wide enough that the whole path from 2010 to 2026 stays in view, because
fetch.py centres every image of a position target on that one spot unless Gaia knows the star.
Fetching needs the network and takes minutes per target, so it only happens with --run.
Exit codes: 0 ok, 1 candidate not found or a command failed, 2 usage.
"""
from __future__ import annotations

import argparse
import json
import math
import shlex
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
PIPELINE = _HERE.parent
ROOT = PIPELINE.parent
if str(PIPELINE) not in sys.path:
    sys.path.insert(0, str(PIPELINE))

from fov import CHOICES, DEFAULT_FOV, MAX_FOV, clamp_fov, position_id  # noqa: E402
from survey.dedupe import propagate  # noqa: E402

DEFAULT_SURVEY = ROOT / "app" / "data" / "survey"
WISE_EPOCH = 2010.5           # AllWISE images (the time-lapse's first frame)
SPHEREX_LAST = 2026.5         # SPHEREx's second sky survey (its last frames)
WINDOW_CENTRE = (WISE_EPOCH + SPHEREX_LAST) / 2      # 2018.5
FIELD_MARGIN_ARCSEC = 30.0    # room left around the path on each side
FOV_STEPS = sorted({f for f in (DEFAULT_FOV, *CHOICES, MAX_FOV) if f >= DEFAULT_FOV})   # 300, 600, 900
EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


# ---------------------------------------------------------------------------------------------- reading
def load_board(path: Path) -> list[dict]:
    """Candidates of a leaderboard.json, in rank order ([] when the file is missing or unreadable)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = data.get("candidates") if isinstance(data, dict) else None
    rows = [m for m in rows or [] if isinstance(m, dict) and m.get("id") is not None]
    return sorted(rows, key=lambda m: (_num(m.get("rank")) is None, _num(m.get("rank")) or 0))


def tile_of_id(cid: str) -> int | None:
    """The tile number a survey id starts with ("10226-0001" -> 10226)."""
    head = str(cid).split("-", 1)[0]
    return int(head) if head.isdigit() else None


def find_candidate(cid: str, survey_dir: Path, board: list[dict] | None = None) -> dict | None:
    """The candidate with this id: from the leaderboard, else from its tile file (not ranked: no class/score)."""
    cid = str(cid).strip()
    for m in board if board is not None else load_board(Path(survey_dir) / "leaderboard.json"):
        if str(m.get("id")) == cid:
            return m
    k5 = tile_of_id(cid)
    if k5 is None:
        return None
    try:
        tile = json.loads((Path(survey_dir) / "tiles" / f"{k5}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for m in tile.get("movers") or [] if isinstance(tile, dict) else []:
        if isinstance(m, dict) and str(m.get("id")) == cid:
            return dict(m, k5=m.get("k5", k5))
    return None


def select_top(board: list[dict], n: int, unexplained: bool = False) -> list[dict]:
    """The first n candidates in rank order (only class "unexplained" ones with unexplained=True)."""
    rows = [m for m in board if not unexplained or m.get("class") == "unexplained"]
    return rows[:max(0, int(n))]


# ---------------------------------------------------------------------------------------------- the plan
def centre_position(m: dict, epoch: float = WINDOW_CENTRE) -> tuple[float, float]:
    """The candidate's (ra, dec) at `epoch`, moved with its own motion from its NEOWISE epoch (degrees, rounded to
    6 decimals: the exact numbers handed to fetch.py)."""
    ra, dec, ep = _num(m.get("ra")), _num(m.get("dec")), _num(m.get("epoch"))
    if ra is None or dec is None:
        raise ValueError(f"candidate {m.get('id')} has no position")
    pmra, pmdec = _num(m.get("pmra")) or 0.0, _num(m.get("pmdec")) or 0.0
    if ep is not None and (pmra or pmdec):
        ra, dec = propagate(ra, dec, pmra, pmdec, epoch - ep)
    return round(ra % 360.0, 6), round(dec, 6)


def field_for(m: dict, epoch: float = WINDOW_CENTRE) -> int:
    """Side of the field (arcsec) that keeps the path from WISE_EPOCH to SPHEREX_LAST in view around the centre:
    the default 300" unless the candidate moves too far, then 600" or 900" (fetch.py's limit)."""
    pm = _num(m.get("pm"))
    if pm is None:
        pm = math.hypot(_num(m.get("pmra")) or 0.0, _num(m.get("pmdec")) or 0.0)
    reach = abs(pm) / 1000.0 * max(epoch - WISE_EPOCH, SPHEREX_LAST - epoch)
    need = 2.0 * (reach + FIELD_MARGIN_ARCSEC)
    for f in FOV_STEPS:
        if f >= need:
            return int(f)
    return int(MAX_FOV)


def plan(m: dict, python: str = sys.executable, fov: float | None = None) -> dict:
    """What to run for one candidate: {id, class, ra, dec, epoch, fov, target, name, commands, open, notes}."""
    cid = str(m.get("id"))
    ra, dec = centre_position(m)
    f = clamp_fov(fov) if fov is not None else field_for(m)
    tid = position_id(ra, dec, f)                     # what fetch.py add_position() will call it
    name = f"Survey candidate {cid}"
    ra_s, dec_s = f"{ra:.6f}", f"{dec:.6f}"
    cls = m.get("class") or "not ranked"
    pm = _num(m.get("pm"))
    ep = _num(m.get("epoch"))
    g = m.get("gaia") if isinstance(m.get("gaia"), dict) else {}
    path_arcsec = (pm or 0.0) / 1000.0 * (SPHEREX_LAST - WISE_EPOCH)
    notes = [
        f"Position at {WINDOW_CENTRE:.2f} (midway between AllWISE {WISE_EPOCH} and SPHEREx {SPHEREX_LAST}), moved "
        f"with the survey's own motion from its NEOWISE epoch {ep:.2f}." if ep is not None else
        "The candidate has no epoch: its position is used as it is.",
        f"Field {f}\" so the {path_arcsec:.0f}\" path from {WISE_EPOCH:g} to {SPHEREX_LAST:g} stays in view.",
    ]
    if cls == "known (Gaia)" and g.get("source_id"):
        notes.append(f"Gaia DR3 {g['source_id']} matched in the survey: fetch.py finds it by its path and uses "
                     "Gaia's motion for every frame.")
    else:
        checked = bool(g.get("checked"))
        notes.append(("No Gaia DR3 match in the survey" if checked else "Not checked against Gaia DR3 in the survey")
                     + ": unless fetch.py finds a Gaia star whose path passes within 5\" of this spot, it keeps the "
                     "field fixed here (no catalogued motion). If it does report one, check that it is this "
                     "candidate and not a neighbour.")
    notes.append("Needs the network (NASA IRSA, ESA Gaia) and takes several minutes; analyze.py also needs the "
                 "packages in pipeline/requirements.txt.")
    return {
        "id": cid, "class": cls, "pm": pm, "ra": ra, "dec": dec, "epoch": WINDOW_CENTRE, "fov": f, "target": tid,
        "name": name,
        "commands": [
            [python, "pipeline/fetch.py", "--ra", ra_s, "--dec", dec_s, "--fov", str(f), "--name", name],
            [python, "pipeline/analyze.py", tid],
            [python, "pipeline/evidence.py"],
        ],
        "open": f"observatory.html?target={tid}",
        "notes": notes,
    }


def format_plan(p: dict) -> str:
    pm = f"{p['pm'] / 1000:.3f}\"/yr" if p.get("pm") is not None else "unknown motion"
    lines = [f"# {p['id']} ({p['class']}, {pm}) -> target {p['target']}"]
    lines += [f"#   {n}" for n in p["notes"]]
    lines += [" ".join(shlex.quote(a) for a in c) for c in p["commands"]]
    lines.append(f"# then open app/{p['open']} (e.g. node server.js, http://localhost:8000/{p['open']})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="promote.py",
        description="Prepare Sky Survey candidates as full WANDERERS targets (WISE -> NEOWISE -> SPHEREx "
                    "time-lapse in the explorer). Prints the commands unless --run is given.")
    ap.add_argument("--id", dest="ids", action="append", default=[], metavar="ID",
                    help="candidate id, e.g. 10226-0001 (repeat for several)")
    ap.add_argument("--top", type=int, metavar="N", help="the first N candidates of the leaderboard")
    ap.add_argument("--unexplained", action="store_true", help="with --top: only candidates Gaia does not explain")
    ap.add_argument("--survey", type=Path, default=DEFAULT_SURVEY,
                    help="survey output folder with leaderboard.json and tiles/ (default: app/data/survey)")
    ap.add_argument("--python", default=sys.executable, help="Python for the commands (default: this one)")
    ap.add_argument("--fov", type=float, help="field side in arcsec (default: wide enough for the whole path)")
    ap.add_argument("--run", action="store_true", help="run the commands (downloads data; needs the network)")
    ap.add_argument("--json", action="store_true", help="print the plan as JSON")
    return ap


def parse_args(argv=None) -> argparse.Namespace:
    ap = build_parser()
    ns = ap.parse_args(argv)
    if not ns.ids and ns.top is None:
        ap.error("give --id ID or --top N")
    if ns.top is not None and ns.top < 1:
        ap.error("--top must be at least 1")
    if ns.unexplained and ns.top is None:
        ap.error("--unexplained goes with --top")
    return ns


def run_plan(p: dict, runner=subprocess.run, root: Path = ROOT, out=sys.stdout) -> bool:
    """Run one plan's commands in order from the repo root; stop at the first failure. analyze.py can report a
    failure and still exit 0, so its output file is checked too."""
    for cmd in p["commands"]:
        print("$ " + " ".join(shlex.quote(a) for a in cmd), file=out, flush=True)
        res = runner(cmd, cwd=str(root))
        code = getattr(res, "returncode", res)
        if code:
            print(f"!! {p['id']}: {Path(cmd[1]).name} failed (exit {code})", file=out)
            return False
        if cmd[1].endswith("analyze.py") and not (Path(root) / "app" / "data" / p["target"] / "target.json").exists():
            print(f"!! {p['id']}: analyze.py wrote no app/data/{p['target']}/target.json", file=out)
            return False
    print(f"ready: app/{p['open']}", file=out)
    return True


def main(argv=None, runner=subprocess.run, root: Path = ROOT, out=sys.stdout) -> int:
    try:
        ns = parse_args(argv)
    except SystemExit as e:
        return EXIT_USAGE if e.code else EXIT_OK
    board = load_board(ns.survey / "leaderboard.json")
    chosen, missing = [], []
    for cid in ns.ids:
        m = find_candidate(cid, ns.survey, board)
        (chosen if m is not None else missing).append(m if m is not None else cid)
    if ns.top is not None:
        chosen += select_top(board, ns.top, ns.unexplained)
    seen, unique = set(), []
    for m in chosen:
        if str(m.get("id")) not in seen:
            seen.add(str(m.get("id")))
            unique.append(m)
    for cid in missing:
        print(f"!! no candidate {cid} in {ns.survey / 'leaderboard.json'} or its tile file", file=out)
    if not unique:
        if not missing:
            print("!! no candidates to promote" + (" (none unexplained)" if ns.unexplained else ""), file=out)
        return EXIT_FAILED
    try:
        plans = [plan(m, python=ns.python, fov=ns.fov) for m in unique]
    except ValueError as e:
        print(f"!! {e}", file=out)
        return EXIT_FAILED
    if ns.json:
        print(json.dumps({"dry_run": not ns.run, "plans": plans}, indent=1), file=out)
    elif not ns.run:
        print("# Dry run: nothing is downloaded. Add --run to run these (needs the network).", file=out)
        print("\n\n".join(format_plan(p) for p in plans), file=out)
    ok = True
    if ns.run:
        for p in plans:
            if not ns.json:
                print(format_plan(p), file=out)
            ok = run_plan(p, runner=runner, root=root, out=out) and ok
    return EXIT_OK if ok and not missing else EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
