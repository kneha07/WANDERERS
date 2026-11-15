# Review: PR #20 at 5cbd519

## project_manager

Reviewer: project_manager (independent; not the author). Pinned head: `5cbd519632fd218df03a7a52ab32e6d6ec03213c`.
PR base: `35cb320`. Compared with local main `e24ab89`. Refs issue #11 (not "closes", which is correct).

### Requirements

| # | Goal or criterion (source) | Status | Evidence |
|---|---|---|---|
| 1 | Pick one test folder (issue #11) | PARTIAL | At head: `tests/` is gone, Python tests are in `test/`. But `backend/test_spherex.py` (pytest) is in the base tree and stays outside `test/`. On main, `web/src/data.test.ts` and `web/src/sky.test.ts` (vitest) are also outside. |
| 2 | README "Run the tests" section with every command (issue #11) | PARTIAL | `README.md:125-149` at head. Missing at its own base: `backend/.venv/bin/python -m pytest backend -q` (it is only in `docs/blink/README.md:72`). Missing on main: `starcore`, `stardb`, `starpath` Node tests, `npm test` in `web/`. Python rows use `python3`, which is the Store stub on Windows. |
| 3 | Fail, not skip, on ImportError in CI (issue #11) | PARTIAL | `test/test_data_quality.py:21,37-40`: strict re-raises. Verified: `CI=true node test/run-all.js` exit 1. No CI exists; the PR names this ("Not done"). The re-raise covers one file only. |
| 4 | "One command runs every test" (PR title, `test/run-all.js:2`) | NOT MET | The runner globs only `test/*.test.js` and `unittest discover -s test`. It does not run `backend/test_spherex.py` (in the base) or the `web/` vitest suite (on main). |
| 5 | Strict mode: "a skipped suite ... `--strict` makes it a failure" (PR body) | NOT MET for Node | `test/run-all.js:27-29` reads TAP lines `# pass N`. Node v24.20.0 prints spec lines `ℹ pass N`, also when piped. Every Node row prints `0 passed` at head. Proof: `parseNodeSummary` on real `test/fields.test.js` output gives `{"pass":0,"fail":0,"skipped":0}`; the real output says `skipped 1`. `verdict(..., strict=true)` then returns `ok:true`. This is a false green in strict mode, which is the exact bug issue #11 asks to remove (finding H1). |
| 6 | Quick mode passes with a warning on a machine without packages (PR body) | MET at head, NOT MET on main | Head: `node test/run-all.js` exit 0, "1 skipped" warning. Merged with main: exit 1, because `test/test_star_trajectory.py:11` and `test/test_star_ml.py` import `astropy`/`numpy` at module level and error, not skip. |
| 7 | `--strict`, `WANDERERS_STRICT=1`, `CI=true` fail without packages (PR body) | MET | `--strict` exit 1; `CI=true` exit 1 (this machine, no pipeline packages). |
| 8 | 8 new runner tests pass (PR body) | MET, but mocked | `node --test test/runall.test.js`: 8 pass. `test/runall.test.js:9,11` feed TAP fixtures, not the real reporter output, so they cannot catch H1. |
| 9 | "Every command in the README table runs as written" (PR body) | PARTIAL | Node rows run. `python3 -m unittest ...` (`README.md:149`) fails on this Windows machine: `Python was not found` (Store stub). |
| 10 | Merges into current main | NOT MET | `git merge-tree --write-tree main 5cbd519`: 2 conflicts, `CONFLICT (file location)` for `tests/test_star_ml.py` and `tests/test_star_trajectory.py`. After the move, `README.md:131,171` and the docstrings in both files still say `tests/` (stale docs). |

### Findings

- **high H1 - strict mode misses Node skips, and every Node count is 0.** `test/run-all.js:28` parses `^# pass`. Node 24 prints `ℹ pass`. Result at head: six rows say `ok ... 0 passed`, and the 1 skipped test in `test/fields.test.js` is not seen. With the Python packages installed, `--strict` would PASS with a skipped test. The PR's core promise ("no more false green") is not met for Node. The PR says the runner was run end to end; its own output shows `0 passed` on every line, which should have been seen. Fix: run `node --test --test-reporter=tap`, or parse `ℹ`, and add a test that uses real reporter output.
- **high H2 - "runs every test" is not true, at the base and on main.** `backend/test_spherex.py` existed at the base (`35cb320`) and is not run or listed. On main, the `web/` vitest suite and three Node files (`starcore`, `stardb`, `starpath`) are not in the README table. Either the runner covers them (with `notRun` warnings when their environment is missing), or the title, `test/run-all.js:2` and `README.md:127` must say "the tests in `test/`".
- **medium M1 - conflicts with main, and the merged tree fails quick mode.** Two file-location conflicts. After the obvious resolution, quick mode exits 1 on a machine without packages (row 6). Rebase on main, move the star tests, apply the same skip/strict rule to them, and fix `README.md:131,171` and their docstrings.
- **medium M2 - strict only for one file.** The skip-or-raise rule lives in `test/test_data_quality.py:37-40` only. Any other Python test that skips is caught by the runner's `skipped=` parse, but a test that does `import astropy` at module level becomes an error in quick mode (see M1). Name the rule in the README so new tests follow it.
- **medium M3 - Windows commands.** The README rows use `python3 -m unittest`. On Windows that is the Store stub. The runner itself handles Windows (`pythonFor`), but the table does not. Add the `python` form, as the setup line already does.
- **low L1 - fourth copy of the Python lookup.** `test/run-all.js:16` copies PR #19's `pickPython`. The PR says so. Record as debt; reuse after #19 merges.
- **low L2 - CI deferred.** Named honestly in "Not done". It is the team's call. Without CI, strict mode is only as good as H1 allows.

### Honest done-state

Good: "Refs #11", not "Closes"; CI and the unrun package tests are named. Not good: the title and `test/run-all.js:2` claim "every test", which is false (H2). The strict claim is false for Node tests (H1), and the runner tests are mocked with a format that Node 24 does not print.

### Verdict

**FAIL.** Two unresolved high findings (H1, H2). Fix H1 with a real-output test, fix or narrow the "every test" claim (H2), and rebase on main (M1).

## tech_lead

Reviewer: tech_lead (independent). Pinned head: `5cbd519632fd218df03a7a52ab32e6d6ec03213c`. Base: `35cb320`. Merge target checked: local `main` at `e24ab89`.

**Verdict: FAIL** (2 high, 2 medium, 4 low).

### Evidence

- Diff read: `test/run-all.js`, `test/runall.test.js`, `test/test_data_quality.py`, `test/test_evidence.py` (rename), `README.md`.
- Head, Windows 11, Node v24.20.0: `node test/run-all.js` prints `0 passed` for every Node file. Quick mode: PASS with a warning. `--strict`: FAIL (data-quality `ImportError`). The strict path in `test_data_quality.py` works.
- `git merge-tree main 5cbd519`: **conflict**. `tests/test_star_ml.py` and `tests/test_star_trajectory.py` were added on main inside the renamed folder.
- Merged state (with git's suggested move to `test/`): `node test/run-all.js` gives **Quick mode: FAIL**, `FAILED (errors=2, skipped=1)`, `ModuleNotFoundError: No module named 'astropy'`.
- `backend/.venv/Scripts/python -m pytest backend -q` in the merged state: 46 passed. run-all does not run it.
- Mutation check on `verdict`: 2 of 2 logic mutants killed. A mutant that removes the `--strict` flag in `main()` survives.

### Findings

| # | Sev | Where | Failure scenario | Fix |
|---|---|---|---|---|
| H1 | high | `test/run-all.js:27-30`, `:56-58`; `test/runall.test.js:8-12` | `parseNodeSummary` reads TAP lines (`# pass 9`). Node 24 uses the spec reporter for piped output too (`ℹ pass 7`). So every Node file reads 0 pass, 0 fail, 0 skipped. The exit code still catches failures, but **Node skips are invisible**. Proof: a file with `{ skip: true }` printed `ok test/zz_skip.test.js 0 passed` under `--strict`. Real case: `test/fields.test.js:186` skips on Windows (`python3` is the Store stub), and strict mode does not count it. The unit tests feed only a hand-written TAP string, so they pass while the real path is broken (false green). | Run `node --test --test-reporter=tap <file>`, or parse both formats. Add one test that runs the real `node --test` on a fixture file with a skip and asserts `skipped: 1`. |
| H2 | high | `test/run-all.js:55-71`; `README.md` "Run the tests" | The runner and README say "All tests live in `test/`" and "One command runs them all". It does not run `backend/test_spherex.py` (pytest, 46 tests, already on the PR base) or the `web/` vitest suite (`web/src/data.test.ts`, `web/src/sky.test.ts` on local main). The README table lists neither command, but issue #11 asks for every command. The PR proposes `run-all.js --strict` as the CI gate. That gate prints `STRICT mode: PASS` while two suites never run. | Add a pytest suite (run with `backend/.venv` Python, as `start.js:11` does) and an `npm test` suite in `web/`, with the same not-run and strict rules. Add both commands to the README table. If the team wants a narrower scope, change the claims to name the suites that run; then this becomes low. |
| M1 | medium | merge with main: `test/test_star_ml.py:3,14`, `test/test_star_trajectory.py:3,11-17`, `README.md:131,171` (merged) | The PR does not merge cleanly. After git's suggested move, README and docstrings still say `tests/...`, so those commands fail. The two star tests import `astropy` and `sklearn` at module level. On a machine without the packages, quick mode **fails** instead of warning. This breaks the PR's own quick-mode contract. | Rebase onto main. Move both files. Fix the paths. Give their imports the same skip/strict guard as `test_data_quality.py`. |
| M2 | medium | `test/run-all.js:16-24` | `pythonFor` copies PR #19's `pickPython`. With `start.js` and `server.js` there are four Python lookups. None of them picks `backend/.venv`, which is the only venv `start.js` makes. | After #19 merges, use one shared helper. Choose per suite which venv runs it. |
| L1 | low | `test/test_data_quality.py:12` | `import numpy as np` is at module level. Without numpy, the import fails before the skip/strict logic. The result is an error, not a skip. | Move the import into the guard. |
| L2 | low | `test/run-all.js:57,66-69` | `spawnSync` has no timeout and the default 1 MB `maxBuffer`. Output over 1 MB sets `p.error` (`ENOBUFS`). For Python this becomes "not run", which is only a warning in quick mode. A hung test blocks the run forever. | Set `timeout` and a larger `maxBuffer`. Treat `ENOBUFS` as a failure. |
| L3 | low | `test/run-all.js:51` | The strict switch in `main()` has no test (that mutant survived). | Export the flag logic and test it, or add one end-to-end test. |
| L4 | low | `README.md` "Run the tests" table, last row | `python3 -m unittest ...` exits 9009 on Windows (Store stub). | Add the Windows form (`python` or `.venv\Scripts\python`). |

### Acceptance (issue #11)

- One test folder: met at the head. Not met after the merge with main until M1 is fixed.
- README lists every test command: not met (H2).
- Fail, not skip, on a missing package in CI: met for `test_data_quality.py`. Not met for Node skips (H1).
