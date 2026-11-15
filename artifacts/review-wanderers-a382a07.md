## Verdict

**FAIL** (one high finding). Fix the high finding, then the branch can merge as PASS-with-findings.

- Tip: `origin/wanderers` `a382a07` (author rajryadav4, no PR). Base: `origin/main` `82340ef`.
- Reviewer: tech_lead (independent). Read-only on the repo.

## What I inspected

- `git diff 82340ef...a382a07`: 627 files. 22 JSON, 609 PNG under `app/data`, plus code, docs and tests.
- Full code read: `pipeline/fetch.py`, `pipeline/spherex_releases.py`, `pipeline/survey/run.py`, `pipeline/survey/rank.py`, `app/release.js`, `app/index.html`, `app/observatory.html`, README, `docs/research/spherex-data-access.md`.
- `pipeline/spherex_s3.py`: S3Reader, listing, index load and append, search, cutout and Range-read code.
- `.github/workflows/spherex-sync.yml` on the branch (not changed) against the new `online` output values.
- Tests run on a `git archive` copy of `a382a07` in the scratchpad, on Windows 11, repo `.venv`:
  - `pytest tests/test_spherex_s3.py tests/test_fetch_s3.py tests/test_spherex_releases.py`: 187 passed, **2 failed**.
  - `node --test test/release.test.js test/frameinfo.test.js test/observatory.test.js`: 70 passed, 0 failed.
  - `tests/test_survey_spherex_run.py`: cannot import on Windows (`import resource` in `pipeline/survey/run.py:66`). This is on main too.
- JSON validity of all 22 changed JSON files. Target-to-PNG references. Survey counts.

## Findings

### High

**H1. S3 search answer cannot be rewritten on Windows. The test for the fallback fails.**
- `pipeline/fetch.py` `s3_search()`: `tmp.write_text(...)` then `tmp.rename(out)`.
- On Windows, `Path.rename` raises `FileExistsError` (WinError 183) when `out` exists.
- Result: the second S3 search for a target (any re-run, or `--s3` after an earlier fallback) raises.
  `fetch()` catches it as `spherex_qr3: not available` and drops the whole release.
  When no release is left, `vstack([])` raises `ValueError: no values provided to stack`.
- Evidence: `tests/test_fetch_s3.py::test_fetch_falls_back_to_s3_for_search_and_cutouts` fails on this machine with exactly this error.
- Linux CI does not show it, so the test is green there and red on the team's Windows machines.
- `spherex_s3.save_state()` uses `os.replace` and is correct. `s3_search()` does not follow the same pattern.

### Medium

**M1. Release check through S3 can flag "new release" from a bucket folder that IRSA does not serve yet.**
- `pipeline/spherex_releases.py` `releases_from_bucket()`: every `drN/` or `qrN/` folder that is not in `SUPERSEDED_BY` counts as a release.
- A staged folder (for example `dr2/` before IRSA SIA lists `spherex_dr2`) sets `new_release_available: true` in the committed status file and in the page note (`app/release.js`).
- The workflow is safe: `new_release` and `changed` are gated on `online` (IRSA). But a local `check` followed by a commit of `app/data/spherex_release.json` can show "New data available" on the public pages for data that fetch.py cannot get through SIA.
- No test covers a bucket folder that IRSA does not list.

**M2. Mixed search rules between IRSA rows and S3 rows in one target.**
- IRSA SIA uses one circle at the 2025.9 position. The S3 index tests the target at each image's own time against an 8-point SIP footprint (`spherex_s3.search`).
- `fetch()` stacks both kinds of rows (`find_images` per release). A target can get a different image set for the same release, depending on whether IRSA answered on that run.
- The docs say the two give 598 vs 599 images for six targets. The difference is small, but a rebuild is not reproducible across IRSA up/down runs. A partial S3 index still gives images (with only a log line) although `searched_releases` does not count it.

### Low

- **L1.** `pipeline/survey/rank.py`: `MIRROR_COOLDOWN_S` 30 min to 6 h. One failed burst on each Gaia service now skips Gaia for 6 h in a long survey run. Movers go to `gaia_unchecked`. Acceptable, but log it in the survey summary.
- **L2.** `pipeline/survey/run.py` `publish()`: the Gaia budget now counts only network time in `crossmatch_tile`. One slow call can overrun the budget. A run can take longer in wall time than before. Tests for this file do not run on Windows (`import resource`, pre-existing).
- **L3.** `S3Reader._get` accepts 200 for a Range request. If a proxy drops the Range header, `read_head` downloads the full 65 MB file. `_rows` catches it as "short read", so data is safe; only cost is wasted.
- **L4.** `refine_inferred()` appends to `data/cache/spherex_s3_index/<release>.jsonl` without a lock. Two fetch processes at the same time can interleave lines. `load_index` skips a broken line, so the effect is a missed record, not corruption.
- **L5.** `tests/test_spherex_releases.py::test_readme_documents_the_sync` fails on Windows (`read_text()` with no encoding, cp1252). Pre-existing, not from this branch.
- **L6.** All 21 `app/data/wise0855/w2_neowise_*.png` and other unchanged-content PNGs were re-encoded (small byte changes). Repo grows with no visible change.
- **L7.** `explain.json` text for six targets was regenerated (LLM text). The facts match the new counts (for example 41 of 160 flagged). README says CI does not regenerate `explain.json`; this commit did it locally. No contradiction, but reviewers must read the new prose.

## Contract audit

```
fetch.py SPHEREx search                release check (spherex_releases.py check)
  IRSA SIA (cached or live)  first       IRSA (astroquery / TAP)  first
     | fails                                | fails
     v                                      v
  S3 footprint index (needs local index)  S3 bucket listing (anonymous)
     | no index -> "not available"          | fails -> keep last file
cutouts: IRSA cutout first -> S3 Range reads on failure, or --s3
```

- IRSA paths are kept and tried first. `--s3` is opt-in. `--no-s3` turns off the S3 listing. `--require-online` still needs IRSA.
- The workflow `online` output now can be `s3`. The workflow only compares `new_release` and `changed`, which stay gated on IRSA. No bypass.
- README and `docs/research/spherex-data-access.md` match the code: bucket name, `qr2` exclusion, `checked_via: "S3 bucket"`, index path, `_s3.json` name, `--s3`.
- No credentials. All S3 access is anonymous HTTPS GET to `nasa-irsa-spherex.s3.us-east-1.amazonaws.com`. No secrets in the diff. Local paths come from target ids and fixed names; S3 keys are not used as local paths (cutout file names use the stem of `access_url`, as before).

## Data audit

- All 22 changed JSON files parse.
- No file is deleted under `app/data`. No page loses an asset. All PNGs that each `target.json` names exist. Four unreferenced PNGs in `app/data/pos_165p8345_n35p9699/` are on main too.
- `app/data/survey/summary.json`: `tiles_done` 1002, `len(tiles)` 1002, sum of tile movers 13,202 = `movers`, sum of unexplained 1,953 = `unexplained`, `detections` 15,957,550,627 (shown as "16.0 billion" by `app/survey.js`). `leaderboard.json` `n_candidates` 13,202, 1,000 rows listed.
- Main showed 647 tiles and 10,115,601,754 detections ("10.1 billion"). The survey page computes the number from `summary.json`; `app/survey.html` has no fixed number. README says "more than 10 billion", which stays true. No README number contradicts the data.
- `app/data/spherex_release.json`: `targets` 11, `checked_via` "IRSA", `rebuilt_targets` = the six targets in commit 710fbc3, `not_rebuilt` = the five position targets. This matches the commit message ("six targets"). `index.json` keeps 11 targets; coordinates moved by small proper-motion amounts (Barnard dec +2.3").
- Changed JS tests (`test/frameinfo.test.js`, `test/observatory.test.js`) update counts to the new data and keep the single-frame test with an in-memory fixture. They are not loosened: the assertions stay exact.

## Tests

- New tests use fakes (`tests/_spherex_s3_fakes.py`) and real FITS layouts. They exercise Range reads, compressed FLAGS rows, the index, search and the fallback in `fetch()`. Good coverage.
- Gap: no test for a bucket release folder that IRSA does not list (M1).
- Gap: the Windows run of the fallback test is red (H1). No CI runs on Windows.
