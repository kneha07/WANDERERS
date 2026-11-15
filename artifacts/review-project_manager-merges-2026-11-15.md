# Post-merge review (project_manager): four PRs merged on 2026-11-15

Reviewer seat: project_manager (scope, acceptance, honest done-state).
Branch: `review/merges-2026-11-15` at `a88e63a`. No code changed.
Tech-lead file `artifacts/review-tech_lead-merges-2026-11-15.md` did not exist when this review was written.
None of the four PRs has a GitHub review (`gh pr view --json reviews` gives 0 for each).

## Summary

```
PR   what                         verdict              high  medium  low
#65  SPHEREx DR1 survey stage     FAIL                 1     1       2
#64  Star Fix                     FAIL (done-state)    1     1       3
#66  catalogue-survey spec        PASS-with-findings   0     1       1
#67  README accuracy              PASS-with-findings   0     1       1
```

Code quality is not the main problem. The main problem is done-state: two PRs merged with
items that their own bodies called "coming" or "before merge", and nothing tracks those items now.

## What I ran (local, Windows, Python 3.13.15, Node 24.20.0)

| Command | Result |
|---|---|
| `node --test test/*.test.js` on `a88e63a` | 588 tests, 586 pass, 0 fail, 2 skip |
| `pytest tests/test_survey_spherex.py` (root `.venv` + `backend/.venv` packages) | 55 passed |
| `node --test test/survey-spherex.test.js` (+ 2 new export tests in `survey-tools.test.js`) | 13 + 2 pass |
| `pytest tests/test_survey_spherex_run.py` | cannot run on Windows: `pipeline/survey/run.py:66 import resource` (POSIX only; already on main before #65) |
| `python -m unittest ... test_star_fix.py` | cannot run here: `pillow_heif` is not installed in `.venv` |
| full `pytest tests` | 630 pass, 2 fail, 10 collection errors (missing `pyarrow`, `pillow_heif`, `resource`). The 2 failures are in `tests/test_survey_rank_score.py` (see #65 L2). |

Because of the environment, the Star Fix Python criteria (A1-A7, A17) are **not verified by me**. I rely on
`artifacts/star-fix/build-report.md` and the two committed review rounds for those.

---

## PR #65: SPHEREx DR1 stage (merge `6be00e3`, head `54e487d`)

**Verdict: FAIL** (done-state honesty). The code and tests are good. The PR body claims more than landed.

### Claim map

| Claim in PR body | Status | Evidence |
|---|---|---|
| Stage reads DR1 cube stamps by HTTP Range, 102 channels, neighbour tile | met (code) | `pipeline/survey/spherex.py` (1,347 lines, new) |
| Runner switches `--no-spherex`, `--spherex-all`, summary `spherex_checked`/`spherex_confirmed` | met (code) | `pipeline/survey/run.py` diff (+194) |
| Ranking +0.5 when confirmed, reasons only otherwise | met | `pipeline/survey/rank.py:718`, `score_terms` diff |
| Page: drawer section, badge, filter, hero stat, CSV/JSON export | met (code) | `app/survey.js:153-235, 523-525, 708`; `app/survey.html:69,133,238` |
| "88 new tests, no network" | met | counted 55 (`test_survey_spherex.py`, incl. parametrize) + 20 (`test_survey_spherex_run.py`) + 13 (`survey-spherex.test.js`) = 88. Commit `48096c9` says 87; the 2 export tests in `survey-tools.test.js` explain the gap. |
| Kapteyn's Star S/N 166, confirmed | **unproven** | no shipped data and no committed log holds this number. `grep` over `app/data`, `artifacts`, `docs` finds no SPHEREx result. Tests use synthetic cubes only. |
| WISE 0855 S/N 13, confirmed | **unproven** | same as above |
| 28 of top 30 detected, 21 at predicted spot | **unproven** | same as above |
| Python 1,216 passed, Node 551 passed | not reproducible here | see L2; on Windows the run tests cannot import |
| "Coming in this PR": release check from S3 listing | **missing** | no commit in `6be00e3^1..6be00e3` touches it. `app/data/spherex_release.json` still has `"error": "IRSA release check failed on 2026-11-15 ... HTTP 502"` |
| "Coming in this PR": QR3 data for the 6 targets that lack it | **missing** | `spherex_release.json` `targets_behind` still lists barnard, eps_indi_b, pos_217p4398_s62p6795, r_dra, rw_aur, wise0855 |
| "Coming in this PR": latest survey numbers with SPHEREx results | **missing** | `git diff 6be00e3^1 6be00e3 --stat -- app/data` is empty. `app/data/survey/summary.json` has no `spherex_*` key. |

### Findings

- **H1 (high) - Merged with three "Coming in this PR" items not delivered, and no issue tracks them.**
  The body says the three items are part of this PR. None landed (table above). The issue list has no ticket for
  them. Result: the status line still shows "IRSA release check failed" and "QR3 not yet in 6 of 11 targets",
  which the PR said it would fix.
  Fix: file one issue with the three items, or edit the PR body to say "not in this PR".
- **M1 (medium) - The SPHEREx stage is invisible on the live page, and the real-data claims have no evidence in the repo.**
  The shipped survey data has no SPHEREx fields, so the page shows `"SPHEREx check not run yet"`
  (`app/survey.js:525`) and the badge and filter match nothing. The page degrades honestly, which is good.
  But the SPHEREx challenge differentiator does not show on `main`, and the Kapteyn / WISE 0855 / "28 of 30"
  numbers cannot be checked by a judge or a teammate.
  Fix: publish a survey snapshot with SPHEREx results, or commit the run log (`artifacts/survey/spherex-run-*.md`)
  that the numbers came from.
- **L1 (low) - Test count wording.** Commit says 87, PR says 88. Both are right for different sets. No action.
- **L2 (low) - The full-suite claim does not hold on the team's Windows machines.** `tests/test_survey_rank_score.py::test_every_term_is_documented_in_the_table`
  fails on Python 3.13 (3.13 strips docstring indent, so `^\s+term\s` no longer matches). It predates #65
  (`c7f50c3`), but #65 adds rows to the same docstring. `run.py` imports `resource`, so 3 survey test files cannot
  load on Windows. Fold into #11 (unify tests, fail on missing deps).

---

## PR #64: Star Fix (merge `f21f19d`, head `0b558de`)

**Verdict: FAIL (done-state).** The feature meets its spec with evidence. The merge skipped its own stated gate.

### Acceptance criteria (`docs/specs/star-fix-build.md` section 11 and 10.4)

| # | Status | Evidence |
|---|---|---|
| A1-A7, A17 (Python maths, sample photos, gate) | met per build report; **not re-run by me** | `artifacts/star-fix/build-report.md`; `tests/test_star_fix.py` needs `pillow_heif` |
| A8 server limits and codes | met | `test/starfix-server.test.js` passes in the full Node run |
| A9 no `python3`, same lookup as `fields.js` | met | `server.js:24` `PY = process.env.WANDERERS_PY \|\| pickPython(__dirname)`; `grep python3 server.js` empty; test `starfix-server.test.js:126` |
| A10 earlier tests still pass | met | 586/588 pass, 2 skip, 0 fail |
| A11-A16 page, hero doors, example, words, a11y | met per build report and screenshots | `artifacts/star-fix/ux-review/round2/*.png`; `test/starfixcore.test.js`, `test/compass-cta.test.js` pass |
| U1-U10 UX mechanics | met per reviews | `artifacts/review-user_advocate-star-fix.md` round 2 PASS |

### Issue bookkeeping

- **#27 closed correctly.** `server.js:24` uses `pickPython`; `/api/star-predict` (`server.js:60`) uses the same `PY`. Test A9 guards it. Closed 2026-11-15T18:00Z, reason COMPLETED.
- **#39 is still OPEN.** The PR says "Refs #39". The feature shipped. #39 should close after #57 is decided, with a comment that links #64.
- **#57 is OPEN with no comment and no owner decision.** See H1.
- **#58 is OPEN.** It holds the accepted low items. Correct.

### Findings

- **H1 (high) - Merged before the stated "Before merge" gate (#57), with no recorded owner decision.**
  The PR body lists #57 under "Before merge: owner decision". The last #39 comment says "Before the merge, decide #57".
  #57 has no comment and no decision. The merge happened anyway.
  The photos were already public on `main` (`72ba60f`, 2026-11-14), so #64 did not create the leak. But #64 makes it
  worse in two ways:
  1. Main's tests now depend on the 14 GPS-tagged files (A2, A3, A4, A6, A17). Removing them now also needs test changes.
  2. #64 adds public text that names two places that #57 says were **not** shared on purpose: "Hong Kong (Sha Tin area)"
     and "Gold Coast hinterland" (`docs/specs/star-fix.md`), and "near San Tung Chung Hang, Hong Kong"
     (`artifacts/review-user_advocate-star-fix.md`).
  This is a done-state honesty problem: a named precondition was skipped and nobody wrote down why.
  Fix: the owner decides #57 now (strip GPS, or remove files and skip tests). Then decide whether the place names
  in the two docs stay. History rewrite needs a force-push, so only the owner can approve it.
- **M1 (medium) - The spec status column is stale.** `docs/specs/star-fix-build.md:488` A9 says `#27 open`. #27 is closed and A9 passes.
  Other rows say "built: PASS". Update the cell.
- **L1 (low)** - Two env-var names for one thing: `server.js:24` reads `WANDERERS_PY`, `fields.js:27` reads `WANDERERS_PYTHON`. `start.js:144` sets both, so it works. Already noted in `artifacts/review-pr-19-8299018.md` L2; track under #49.
- **L2 (low)** - The PR body claims "Verify: 10 OK" for Python. That needs `pillow-heif`, which `pipeline/requirements.txt` adds, but the existing root `.venv` on this machine does not have it. `start.js` installs it on the next start. No action; README states the command.
- **L3 (low)** - `artifacts/star-fix/` ships about 20 probe scripts (`analyze.py`, `iphone/*.py`, `win/*`). They are research evidence, not product. Acceptable under `artifacts/`.

---

## PR #66: catalogue-survey spec, docs only (merge `c9c4e0c`)

**Verdict: PASS-with-findings.** Docs only, nothing breaks. But the spec is stale against what landed before it.

### Findings

- **M1 (medium) - The spec was written without the Sky Survey and conflicts with it. Do not build #60 from it as it is.**
  `git merge-base --is-ancestor 2c27cbb ce86d35` is false: the spec branch never contained the Sky Survey
  package. It merged after #65.
  - `docs/specs/catalogue-survey-build.md:21,52` tells the builder to create `pipeline/survey.py`. `pipeline/survey/`
    is already a package (`__init__.py`, `run.py`, `spherex.py`, ...). A module and a package with one name in one folder collide.
  - Line 79 writes `app/data/survey/index.json`, the folder that the Sky Survey page reads.
  - #60 says "WANDERERS analyses a field that a user selects" and calls the automated scan "the gap". On `main` the
    Sky Survey already scans NEOWISE tiles, checks Gaia, ranks, and (after #65) checks SPHEREx. README row 6 says so.
  - The goal overlap is large: both are "rank a billion objects and confirm with SPHEREx". CatWISE2020 may still be a
    cheaper second source, but the spec must say how it relates to `pipeline/survey/`.
  Fix: add a comment on #60 with this conflict. Revise the spec (new file names, reuse `rank.py` and
  `spherex.py`) before anyone builds it.
- **L1 (low)** - The PR body says "merges onto main with no conflicts". That is true for text only, not for design.

### Issue bookkeeping

- #60 (decide) stays OPEN, correct. Add the conflict note.
- #59: the data moved since the issue was filed. On `a88e63a` `target_recovered` is `true` for Barnard's Star and
  Epsilon Indi B, and still **`false` for WISE 0855** (`app/data/wise0855/target.json`). The "done when" is not met.
  Add a comment with the current values. Keep it OPEN.

---

## PR #67: README accuracy (merge `a88e63a`, commit `09604fc`)

**Verdict: PASS-with-findings.** Every figure I rechecked matches the shipped data. One gap: it does not describe #65.

### Claim map (recomputed from `app/data/` on `a88e63a`)

| README claim | Status | Evidence |
|---|---|---|
| 14 stars with a hold-out, median 210 mas, range 21-2,021 mas, table values | met | `app/data/stars/pred/*.json` `holdout_gaia.miss_mas`: 14 values, median 209.95, min 20.7 (R Dra), max 2020.9 (Proxima); all 14 table rows match |
| Usable spectrum for 5 of 11 targets (WISE 0855, Eps Indi B, Luhman 16, RW Aur, Wolf 359) | met | non-empty `spectrum` only for those 5 in `app/data/*/target.json` |
| Mover search re-finds the known mover in 8 of 9 moving fields | met | `target_recovered`: 8 `true`, WISE 0855 `false`, R Dra and RW Aur `null` (not moving) |
| "3 of 3 checks" counts key checks only | met (wording) | matches the rule description in the same section |
| Measured path is seeded at the Gaia position, not a blind search | met (wording) | README:135-139, 789-790 |
| Star Fix section (from #64) | met | README:208-217 matches `server.js` route, `star-fix-solver.js` stdin, spec |

### Findings

- **M1 (medium) - README does not describe the SPHEREx stage from #65.** README row 6 (line 52) and the Sky Survey
  section (line 318: "ranks the movers found in the NEOWISE archive") describe NEOWISE + Gaia only. No mention of
  `pipeline/survey/spherex.py`, "Confirmed by SPHEREx", the filter, or `--no-spherex`. This is the part that answers the
  SPHEREx challenge, and the PR says "Recomputed every figure from app/data/ on current main", which was after #65.
  Fix: add 3-4 lines to row 6 and the Sky Survey section. State that the shipped snapshot has no SPHEREx results yet
  (see #65 M1), so the README does not over-claim.
- **L1 (low)** - The "117 of 158 points" counts come from raw points; `target.json` ships binned points (67 for WISE 0855). Both can be right; a reader cannot check the raw count from shipped data. Optional note.

---

## Bookkeeping actions (for the orchestrator; I changed nothing on GitHub)

| Action | Why |
|---|---|
| File an issue: "#65 follow-ups: S3 release check, QR3 for 6 targets, survey snapshot with SPHEREx results, run log for the Kapteyn/WISE 0855 numbers" | #65 H1, M1 |
| Owner: decide #57 now; then close #39 with a link to #64 | #64 H1 |
| Comment on #60: spec conflicts with `pipeline/survey/` and `app/data/survey/` | #66 M1 |
| Comment on #59: Barnard now `true`, WISE 0855 still `false` | #66 bookkeeping |
| README update for the SPHEREx stage (small docs PR) | #67 M1 |
| Fix stale A9 cell in `docs/specs/star-fix-build.md:488` | #64 M1 |
| Add Python 3.13 docstring and `resource` import to #11 | #65 L2 |
| Nothing to reopen. #27 was closed correctly. | |

## Process note

All four PRs merged with zero GitHub reviews. #64 has committed agent reviews on its branch; #65, #66 and #67 have
none. The repo rule (CLAUDE.md: "main gets only merges of finished, reviewed branches") was not met for #65-#67.

## Debate round 1

Read `artifacts/review-tech_lead-merges-2026-11-15.md`.

| tech_lead finding | Response | Evidence |
|---|---|---|
| M1 #65: "Confirmed" when `gone_from_2014` is None | **Accept** (medium). It also makes the claim honesty worse: the badge and the reason text say "gone from its 2014 spot" for a check that was not measured. | `pipeline/survey/spherex.py:1175` `res["confirmed"] = bool(resolved and res["gone_from_2014"] is not False)` |
| M2 #64: CI skips the plate-solve tests | **Accept** (medium). The "10 OK" claim holds only where cedar-solve is installed by hand or by `start.js`. | `tests/test_star_fix.py:75-76` skips when `tetra3` is absent; `pipeline/requirements.txt` has no cedar-solve |
| M3 #66: spec conflicts with `pipeline/survey/` | Agree. Same as my #66 M1. | |

Both FAILs stand. They are done-state FAILs, not code-quality FAILs. tech_lead judges the code and I agree the code passes. My two highs are about honest scope and gates:
- #65 H1: three "Coming in this PR" items did not land, and nothing tracks them.
- #64 H1: the "Before merge" gate (#57) was skipped, and nobody recorded why.

Neither high needs a revert. Each one clears when its bookkeeping action is done: file the #65 follow-up issue, or get the owner's #57 decision on record. Then both PRs become PASS-with-findings.

Final verdicts: #65 FAIL (done-state), #64 FAIL (done-state), #66 PASS-with-findings, #67 PASS-with-findings.
