# Tech lead review: merges to main on 2026-11-15

Reviewer: tech_lead (independent, post-merge). Scope: PR #65, #64, #66, #67 as pinned.
Worktree: `.worktrees/merge-review` at `a88e63a`. No product file was changed.

## Summary

```
PR   what                      verdict              high  medium  low
#65  SPHEREx DR1 survey stage  PASS-with-findings    0     1      3
#64  Star Fix                  PASS-with-findings    0     1      5
#66  catalogue-survey specs    PASS-with-findings    0     1      0
#67  README accuracy           PASS                  0     0      1
```

No high finding. Nothing found that loses data, leaks a secret or gives a false-green test.

## What I ran

| Check | Result |
|---|---|
| `node --test test/*.test.js` | 588 tests, 586 pass, 2 skip, 0 fail |
| `python -m unittest discover -s tests -p "test_star_fix.py"` | 10 OK, 46 s. Run with `.worktrees/star-fix/.venv` (Python 3.13). The root `.venv` has no `pillow_heif`, so it fails at import. `start.js` repairs that venv on its next start. |
| `pytest -k "spherex or survey"` | Not run. No local venv has `pytest` and `pyarrow`. I did not download packages. |
| CI `checks` on main | green at `f21f19d`, `c9c4e0c` and `a88e63a` (Python 3.12 pytest job included) |
| `git diff --check` per merge | only the known blank line at EOF in `artifacts/star-fix/fix_core.py:26` |
| Merge `0b558de`: lost changes | For every file that either side changed, I compared the result with each side. Only the 6 files changed on both sides differ, and each keeps both sides' intent (details under #64). |
| README numbers (#67) | Recomputed from `app/data/` (details under #67) |

## Where the workflows came from

`.github/workflows/classifications.yml`, `spherex-sync.yml` and `.github/ISSUE_TEMPLATE/classification.yml` did **not** come from these four PRs.
Commits `0606442` and `572f4dc` landed in merge `70ca9c7` (PR #62). They are on the first parent of #64 and #65.
I checked them anyway, because the brief asked:

| Workflow | Schedule | Permissions | Secrets | Cost | Finding |
|---|---|---|---|---|---|
| classifications | issue events + every 6 h | top `contents: read`; job `contents: write`, `issues: read` | `github.token` only | free on a public repo | Low W1 |
| spherex-sync | Mondays 07:23 UTC + manual | check job read-only; update job `contents: write`, `pull-requests: write` | `github.token` only | free on a public repo; the update job may run up to 340 min | none |

- Issue text never goes into a shell command. The script reads it as JSON from `gh`. The code comes from `main`, so an issue cannot run code.
- **W1 (low, out of scope, #62):** `classifications.yml:52` pushes a bot commit straight to `main`. The project rule (CLAUDE.md) says main gets only reviewed merges. Also, any GitHub account can open any number of vote issues, and each one starts a run. Failure scenario: a spam wave of issues makes many bot commits on main. The concurrency group stops parallel pushes, so there is no data race.

---

## PR #65: SPHEREx DR1 stage (merge `6be00e3`)

**Verdict: PASS-with-findings**

The architecture fits. The stage has the same shape as the Gaia step: one function per tile (`check_tile`), a per-tile cache, a time budget, a fail streak, and it never raises (`spherex.py:1194-1257`, `:1283-1290`).
The reader refuses a `200` reply, so it cannot download a 321 MB cube by mistake (`spherex.py:233-234`). Retries, timeouts and a bounded pool are set (`spherex.py:203-216`).
The cache key holds the Gaia result through `wanted`, so a later Gaia match drops the old answer (`run.py` `_spherex_key`). Ranking adds only +0.5 and never takes points away (`rank.py:852-871`).
The page works with the shipped data, which has no SPHEREx fields: it shows "SPHEREx check not run yet" (`app/survey.js:523-525`).

### M1 (medium): "Confirmed" says "gone from its 2014 spot" when that was not measured

- `pipeline/survey/spherex.py:1175`: `confirmed = resolved and res["gone_from_2014"] is not False`. So `gone_from_2014 = None` also gives `confirmed = True`.
- `gone_from_2014` is `None` when the 2014 spot is not measured. The old stamp is read only when the expected move is at least `2 × R_AP` pixels, about 40″ (`spherex.py:1035`). It is also `None` when the 2014 S/N is between 3 and 5 (`spherex.py:613-625`).
- `resolved` can be true at about 12″ (6σ with the 0.15 px floor). So a mover that moved 12″ to 40″ gets `confirmed: true` with no 2014 measurement at all.
- The user text still says the 2014 spot is empty: `rank.py:858` ("and gone from its 2014 spot") and `app/survey.js:184` ("and gone from its 2014 spot"). The PR body says the same thing. `docs/survey-contract.md:150-151` says "not still occupied", which matches the code, so the contract and the UI disagree.
- No test covers `confirmed` with `gone_from_2014 = None`. `tests/test_survey_spherex.py:291` tests only `gone = True`.
- Failure scenario: a 2″/yr mover gets +0.5, a "SPHEREx ✓" badge and the sentence "gone from its 2014 spot", but nobody measured the 2014 spot. The reader trusts a check that did not happen.
- Shipped data today has 0 confirmed rows, so nothing wrong is visible yet. The next survey publish will show it.

### L1 (low): the final publish has no SPHEREx time limit

- `run.py` `Runner` publish: `sx_budget = None if final else cfg.spherex_budget * 60`.
- The current snapshot has 939 unexplained movers in 647 tiles. Over 12,288 tiles that is about 18,000 movers. At about 2.6 MB per mover (PR body), that is about 45 GB of reads that are not cached yet.
- Failure scenario: a short whole-sky run ends, and its final publish runs for hours before `summary.json` says `done`. Periodic publishes cache much of it, so a long run suffers less.

### L2 (low): some errors are cached as final answers

- `run.py` `spherex_retryable` retries only `network: …`, `time budget` and `stage failed…`.
- `"read error: …"`, `"internal error: …"` and `"SPHEREx cube unreadable: …"` (`spherex.py:1213`, `:1246`, `:1253`) count as complete. They are written to `<cache>/spherex_tiles/<k5>.json`.
- Failure scenario: one odd reply from S3 makes a read error. That tile stays "not checked" for good, until someone bumps `STAGE_VERSION`.

### L3 (low): the PR body promised work that did not land

- The body lists "Coming in this PR: … The latest survey numbers, with SPHEREx results".
- `app/data/survey/summary.json` (generated `2026-11-15T14:29:46Z`, `status: running`) has no `spherex_checked` field. No leaderboard row has a `spherex` key.
- So the site shows none of the Kapteyn or WISE 0855 confirmations in the PR body. This is an honest-state item for project_manager. Code and tests are not affected.

---

## PR #64: Star Fix (merge `f21f19d`, head `0b558de`)

**Verdict: PASS-with-findings**

```
starfix.js -- POST raw bytes --> server.js /api/star-fix
                                  | 30 MB cap, one at a time (409), 400 / 413
                                  v
                             star-fix-solver.js
                                  | spawn(python, [script]) no shell, photo on stdin
                                  | 60 s -> kill tree (taskkill /T or kill -pgid) -> 504
                                  v
                             pipeline/star_fix.py -> one JSON line
```

Upload route security, checked:

- It listens on `127.0.0.1` only (`server.js:235`).
- The size limit stops buffering at 30 MB, then answers 413 and closes the socket (`server.js:88-99`, `:113-123`). A client that leaves frees the slot (`server.js:119`).
- There is no shell and no path from the client: the script path is fixed and the photo goes on stdin (`star-fix-solver.js:15`, `:34`). The photo is not written to disk.
- Errors are two fixed texts, with no path or stack (`star-fix-solver.js:5`, `:31`).
- The busy slot is freed only when Python has really ended, after a 504 too (`server.js:127`).
- A decompression bomb is refused before decode (`star_fix.py:197-200`).
- `PY = WANDERERS_PY || pickPython(__dirname)` fixes #27 on Windows (`server.js:24`, `fields.js:25-35`).

### M2 (medium): CI never runs the plate solve

- CI installs only `pipeline/requirements.txt` (`.github/workflows/checks.yml:29`). `cedar-solve` (tetra3) is not in that file. Only `start.js:123` installs it, with `--no-deps`.
- `tests/test_star_fix.py:73-76` then skips all six photo tests (A2, A3, A4, A5, A17, small photo). They do not fail.
- So the green Python job on main tests only the maths round trip and the bad-file paths. The solve gate (`MIN_MATCHES`, `MAX_RMSE_ARCSEC`, `MAX_FALSE_PROB`), the orientation table on real files and the 2,800 km false-solve guard are tested only on a developer machine.
- I ran them locally: 10 OK. So the code works today. The gap is regression protection.
- Failure scenario: a later change to `solve()` or a numpy or cedar-solve bump breaks the solve. CI stays green, and the first sign is a wrong position on the page.

### L4 (low): a crafted MakerNote can use gigabytes of memory

- `pipeline/star_fix.py:58`: `struct.unpack(bo + ("ii" ... ) * cnt, …)`. Here `cnt` is an unsigned 32-bit count from the file, and nothing limits it.
- A count near 2³² builds a format string of about 8 GB before `struct.error` can fire.
- Failure scenario: a small crafted JPEG with an "Apple iOS" note makes Python allocate gigabytes until the 60 s kill. The machine can swap or kill other processes. The route is local and needs the user to choose the file, so the risk is low.

### L5 (low): any web page can start the solver

- `/api/star-fix` does not check `Origin` or `Host`. A page the user visits can send a simple cross-origin `POST` to `http://127.0.0.1:8000/api/star-fix`. The browser does not let that page read the reply.
- Impact: CPU use, one solve at a time. `/api/lookup` behaves the same way, so this is not new.

### L6 (low): sample photos with exact GPS are still on public main (#57)

- `star_image/` came from `72ba60f`, which was on main before #64. #64 did not add it, but its tests need it (`tests/test_star_fix.py:72`).
- I checked the four committed `artifacts/star-fix/photo*_stars.jpg`: they have no EXIF and no GPS. `app/data/starfix-sample.json` shows only the public Phillip Island GPS, rounded to 0.01°.
- The PR listed #57 as "Before merge", and #57 is still open. The owner must decide. History needs a force-push.

### L7 (low): the merge left the Sky Compass door styled unlike the other two

- `0b558de` kept main's `.compass-cta` rules at the end of `app/home.css:222-225`. They were written for the old one-line button.
- `.hero .cta .btn` has higher specificity and wins for padding, gap and text-align. But `justify-content: center` from `.compass-cta` still applies, because the hero rule does not set it.
- Failure scenario: the middle door of the three is centred and the other two are left-aligned. This is cosmetic. I did not check it in a browser.

### L8 (low): the start message is wrong for Mac and Linux

- `star-fix-solver.js:5` says "Start the app with start.cmd" on every platform. On macOS the launcher is `start.command`, and on Linux it is `node start.js`.

### Conflict resolution in `0b558de`: correct

- `pipeline/requirements.txt` keeps both sides (pillow, pillow-heif + pyarrow, astropy-healpix, certifi, pytest).
- `README.md` layout keeps both sides (star_fix.py, starfix files + aggregate_votes.py, classify files).
- `app/index.html` takes the three-door hero from the branch. It also keeps main's `survey.html` nav link, `release.css`/`release.js`, `#spherexStatus` and the `?v=` bumps. Nothing from main is lost.
- `test/compass-cta.test.js` now asserts the wording for each page, instead of one shared string. This is stricter, not looser. It checks the exact three doors, the nav link "How It Works" and the footer link. It is not a loosened test.
- `docs/architecture.md` and `app/home.css` merged without a textual conflict. L7 is the one side effect.
- The merge message says "1,206 Python tests pass" and blames "Python 3.14" for two failures. My local Python is 3.13. The claim is consistent with the brief's known artefact, and CI on 3.12 is green.

---

## PR #66: catalogue-survey specs (merge `c9c4e0c`)

**Verdict: PASS-with-findings** (documents and one 41-row sample CSV only. No code runs.)

### M3 (medium): the build spec targets paths that collide with the Sky Survey already on main

- The spec is based on `ca220c7` (`docs/specs/catalogue-survey.md:3`). It tells the builder to create `pipeline/survey.py` (`catalogue-survey-build.md:21`, `:52`), `tests/test_survey.py` run as `python3 -m unittest tests.test_survey` (`:13`), and `app/data/survey/index.json` (`:79`, `:127`).
- Main already has the package `pipeline/survey/` (link, rank, run, spherex …) and writes `app/data/survey/{leaderboard,summary,validation}.json` plus `tiles/`. Neither spec mentions `pipeline/survey/`, `survey.html` or #65.
- Failure scenario: an agent follows the spec. `pipeline/survey.py` sits next to `pipeline/survey/`. With `pipeline` on `sys.path`, `import survey` loads the package, not the new module. So the new tests import the wrong code, or the new file shadows the package for scripts run from `pipeline/`. `app/data/survey/index.json` also mixes a second survey's output into the NEOWISE survey folder.
- Also, stage 3 "SPHEREx position and spectrum" repeats what `pipeline/survey/spherex.py` now does.
- The spec says "Status: design, not built", so nothing is broken yet. Update the spec before anyone builds it.

---

## PR #67: README accuracy (merge `a88e63a`)

**Verdict: PASS**

I recomputed the numbers from `app/data/`:

| README claim | Data | Match |
|---|---|---|
| 14 stars with a Gaia hold-out, median 210 mas, range 21 to 2,021 mas, 14-row table | 14 non-null `holdout_gaia.miss_mas` in `app/data/stars/pred/`; median (189.8 + 230.1) / 2 = 210; min 20.7, max 2020.9; every table value matches | yes |
| Sirius and Rigil Kentaurus carry no hold-out | `holdout_gaia: null` | yes |
| Usable spectrum for 5 of 11 targets: WISE 0855 117/158, Luhman 16 75/150, RW Aur 10/150, Wolf 359 1/60 | `used_in_spectrum` counts are the same | yes |
| Epsilon Indi B 111 of 180 | 112 of 181 in `metadata` (`spectrum_points` = 180) | nearly (L9) |
| Kapteyn's Star and R Draconis have none | `spectrum` list is empty for both | yes, but see L9 |
| Mover search re-finds the target in 8 of 9 fields | not recomputed | unchecked |

### L9 (low): two spectrum counts depend on which field you count

- `README.md` line 145 (in the #67 hunk): Kapteyn's Star has 61 of 150 frames with `used_in_spectrum: true`, and R Draconis has 1 of 155, but both have an empty `spectrum` list. Epsilon Indi B is 112/181 in `metadata`, and the README says 111/180.
- The claims "5 of 11" and "have none" match what the page draws (the `spectrum` list). The per-target counts mix two sources. A reader who checks `metadata` gets different numbers.

The new text about the measured path ("a consistency check, not an independent detection") and the evidence-card headline is a real accuracy fix. It removes an overclaim.

---

## Things I did not check

- The SPHEREx Python tests locally (no pytest or pyarrow). I relied on green CI at `6be00e3` and later.
- The Star Fix page and the home hero in a browser (L7 is from reading the CSS).
- The "8 of 9" mover-search claim in #67.
- The science in `spherex.py` (aperture photometry, centroid, spectral indices) beyond the verdict logic.

## Debate with project_manager

`artifacts/review-project_manager-merges-2026-11-15.md` did not exist when I wrote round 0. See round 1.

## Debate round 1

I read `artifacts/review-project_manager-merges-2026-11-15.md`. I checked its evidence myself.

### #65 H1 (three "Coming in this PR" items not delivered): accept the finding, re-rate to medium

- The evidence holds. `git diff 6be00e3^1 6be00e3 --stat -- app/data` is empty. `app/data/spherex_release.json` still holds `"IRSA release check failed … HTTP 502"`. My L3 is the same finding, so I raise L3 to medium.
- I do not rate it high. In this seat, high means data loss, a security hole, an irreversible bug or a false-green test. The code is correct and the page says "SPHEREx check not run yet" (`app/survey.js:525`). One tracking issue fixes the gap, and nothing has to be undone.
- I accept PM M1 (no real-data evidence in the repo for Kapteyn's Star, WISE 0855 and "28 of 30"). It matches my L3.
- I accept PM L2: `pipeline/survey/run.py:66` imports `resource`, so `tests/test_survey_spherex_run.py` cannot load on Windows. It is on main from before #65. Fold it into #11.

### #64 H1 (merged before the #57 gate): accept as high, change my verdict to FAIL

- I checked the evidence. The #64 diff adds "Hong Kong (Sha Tin area)" and "Gold Coast hinterland" to `docs/specs/star-fix.md`. It adds "near San Tung Chung Hang, Hong Kong" to `artifacts/review-user_advocate-star-fix.md` and to the build docs. #57 says that only Phillip Island was shared on purpose.
- My L6 said "#64 did not add it". That is true for the photos, but wrong for the text. #64 itself published new location text on a public repo. Taking it out of history needs a force-push. That is irreversible without the owner, so it meets my high bar (security and privacy, hard to undo).
- I accept the test-coupling point too. Main's tests now need the GPS-tagged files (`tests/test_star_fix.py:72`).
- The code findings (M2, L4–L8) stay as written.

### Other PM findings

- #66 M1: agree. It is the same as my M3.
- #67 M1 (the README does not describe the SPHEREx stage): accept as low. The README does not overclaim. It leaves the stage out. I change #67 to PASS-with-findings.
- #64 M1 (stale A9 cell, `docs/specs/star-fix-build.md:488`): accept as low.

### Final verdicts (tech_lead)

```
PR   verdict              open high
#65  PASS-with-findings   none (M1 confirmed-claim, M4 = old L3 promised work missing)
#64  FAIL                 H1 (PM): new private place names on public main, #57 gate skipped
#66  PASS-with-findings   none
#67  PASS-with-findings   none
```

Remaining disagreement: #65. PM says FAIL (high) and I say PASS-with-findings (medium). The disagreement is only about severity. We agree on the facts and on the fix: one tracking issue.
