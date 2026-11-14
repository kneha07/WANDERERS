# Project-manager review: PRs #4, #7, #8 (kneha07/WANDERERS)

Reviewer: project_manager (independent; not the author). Author: maevek092.
Pinned heads: #4 `a1175d3`, #7 `8db452f`, #8 `3c72267`. Base for all three: `main`.
Linked issues: none. No PR comments. All three report `MERGEABLE` (no conflicts) and none are drafts.

Test method: I copied each PR file into a temporary `tests/` folder on `integrate/2026-11-14`.
I ran the PR's own command, then deleted the folder. `git status` is clean after the runs.

## Verdicts

| PR | Verdict | Reason in one line |
|----|---------|--------------------|
| #4 | FAIL | The file is named `tests`, not `tests/server.test.js`. The run command fails. 2 of 8 tests fail on the current server. |
| #7 | PASS (with low notes) | 10/10 tests pass. Claims match the diff. |
| #8 | PASS (with medium/low notes) | 10/10 tests pass in the pipeline venv. The body says "pending verification". This review verifies it. |

## PR #4 "Add API Security and Input Validation Tests"

| Claim in body | Status | Evidence |
|---|---|---|
| Run with `node --test tests/server.test.js` | missing | Diff adds a single file at path `tests` (`diff --git a/tests b/tests`). No `tests/server.test.js` exists after merge. |
| Security / validation tests for server | partial | 8 tests. 6 pass when the file is placed at `tests/server.test.js`. |
| Test results | missing | Body says "Test results pending verification". The author did not run them. |
| "without modifying existing application functionality" | met | Only the test file changes. |

Findings:

- **high**: Wrong file path. The PR creates a file named `tests` at the repo root. The stated command `node --test tests/server.test.js` cannot run. A file named `tests` also blocks PR #7 and #8, which need a `tests/` folder. Merge order: whichever lands second conflicts (file vs directory).
- **high**: 2 of 8 tests fail against `server.js` on the integration branch. The run output:
  - `rejects invalid URL encoding without crashing`: `fetch failed ... ECONNRESET`. The server crashes. Cause: `server.js:97` calls `decodeURIComponent` on `/%ZZ` with no try/catch inside an async handler. The process dies.
  - `unknown target does not leak filesystem path`: `ECONNREFUSED`. The server is already dead from the test before. Separately, `server.js:85` catches the `ENOENT` from `readFileSync` and returns 400 with `String(e.message)`. That message holds the full file path. The test expects 404 with no path, so it fails even on a live server.
  These are real server bugs (a one-request crash and a path leak). The tests are good. But the PR is red, and nobody named the bugs. As written, the PR cannot be "done".
- **medium**: Folder split. The repo already has `test/` with `fields.test.js` and `framemath.test.js`. README lines 82 and 94 point to `test/`. This PR (and #7, #8) adds `tests/`. A judge or teammate sees two test folders and two run styles. Put the Node test in `test/server.test.js`, next to the existing ones.
- **medium**: Title says "security tests". The content is mostly input validation plus 2 real security checks (URL-decode crash, path leak). It does not test directory traversal on static files (`server.js:98` guard), `/api/lookup` bounds, or `/api/field`. The title over-claims a little. "API validation and robustness tests" is more honest.
- **low**: Each test is a single minified line. Hard to read or debug in a hackathon review.
- **low**: `/api/ask` tests with a valid target would call the real `claude` CLI. The current tests avoid that by sending only rejected bodies. Good, but not stated.

What makes #4 PASS: move to `test/server.test.js`, fix or file the two server bugs (the URL-decode crash and the path leak in the 400 body), and paste a green run in the body.

## PR #7 "Add evidence classification and confidence tests"

| Claim | Status | Evidence |
|---|---|---|
| 10 unit tests | met | `tests/test_evidence.py`, 10 `test_` methods. |
| Motion thresholds, methane, variability, catalogue match | met | Tests at lines 36-63 of the new file. |
| Confidence and saturation | met | `test_saturation_reduces_variable_star_confidence`. |
| Candidate vs known | met | Two status tests. |
| "10 tests passed" with the stated command | met | My run: `Ran 10 tests ... OK` (pipeline venv). `evidence.py` needs only stdlib. |
| No product change | met | One new file only. |

Findings:

- **medium**: Uses `tests/` while the repo convention is `test/` (see #4). Not documented in README, so a judge does not find it.
- **low**: Tests pin exact label strings like `'Steady star (no change in these snapshots)'`. A copy change in `pipeline/evidence.py` breaks the tests. That is acceptable for a regression net, but be aware.
- **low**: Body uses `python3`. On this Windows machine the command is `python`. Minor.

## PR #8 "Add Data Quality and Photometry Validation Tests"

| Claim | Status | Evidence |
|---|---|---|
| 10 unit tests | met | `tests/test_data_quality.py`, 10 tests. |
| Bad-pixel masking, flags | met | `bad_mask` tests with FITS headers. |
| Aperture photometry, background | met | 3 `photometry` tests. |
| Centroid, detection, missing data | met | `centroid`, `detection_snr`, `stretch` all-NaN tests. |
| Passing | met (by this review) | Body says "pending verification". My run in the pipeline venv: `Ran 10 tests ... OK`. |
| No product change | met | One new file only. |

Findings:

- **medium**: `setUpClass` turns any `ImportError` into `SkipTest`. Without the pipeline deps, the suite shows "skipped" and exits 0. A teammate can think it is green when nothing ran. Prefer a hard fail, or print the skip reason in the README run step.
- **medium**: Same `tests/` vs `test/` split. README does not list the command or the need for `pipeline/requirements.txt`.
- **low**: The body says verification is pending. Update it with the green run so the PR reads as done.

## Cross-PR scope and goal alignment

- All three PRs add tests only. They support the challenge goal (credible, reproducible evidence). No gold-plating.
- None updates README. The README test section lists only `test/`. A judge who follows the README never runs these 28 tests.
- Merge order risk: #4 adds a file `tests`. #7 and #8 add a folder `tests/`. They cannot all merge. Fix #4 first.
- Deferred work with no name: the two server bugs that #4 found. File them as issues or fix them in #4.

## Recommended single fix for the folder split

```
test/
  fields.test.js        (existing)
  framemath.test.js     (existing)
  server.test.js        (from #4)
pipeline/tests/  or  test/py/
  test_evidence.py      (from #7)
  test_data_quality.py  (from #8)
```

Then add one README line per runner.

ack: no numeric score given, per the evidence contract.
