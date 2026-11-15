# Merge record, 2026-11-15 (c): origin/wanderers

Base: `main` = `origin/main` `82340ef`. Tip: `origin/wanderers` pinned at `a382a07` (rajryadav4, no PR).
Integration branch: `integrate/wanderers-a382a07`.

```
82340ef ── 4356dc9 merge a382a07 (+ test overlap fix) ── 77e602e fix H1 (Path.replace)
```

## What came in

- SPHEREx Quick Release 3 for Barnard's Star, eps Ind B, Proxima Cen, R Dra, RW Aur and WISE 0855.
- Survey snapshot: 1,002 tiles, 16.0 billion NEOWISE detections, 13,202 movers.
- SPHEREx without IRSA: S3 release check, header index, Range-request cutouts, `fetch.py --s3`.
- Survey publish: separate Gaia and SPHEREx time budgets; an unreachable Gaia service waits 6 h.

## Review

`artifacts/review-wanderers-a382a07.md` (tech_lead, fresh context): FAIL on H1, PASS-with-findings once H1 is fixed.

- H1 (high) fixed in `77e602e`: `Path.rename` fails on Windows when the file exists. All four uses in `pipeline/` now use `Path.replace`. `tests/test_fetch_s3.py` passes.
- M1, M2 (medium): open in #88.
- Lows: in the review file.

## Semantic overlap

The Adaptive Explorer tests (#83, #85) held Barnard's and R Draconis' numbers as literals (163″, 10.40″/yr, 0.34 mag).
QR3 adds 2026 epochs, so the evidence cards now say 170″, 10.55″/yr and 0.53 mag. The app reads them from the data, so
it is right. The tests in `test/discoveries.test.js`, `test/explorer.test.js` and `test/research.test.js` now read the
numbers from `target.json` and the evidence cards. Fixed in the merge commit `4356dc9`.

## Checks (Windows 11, Node 24, Python 3.13)

- `node --test test/*.test.js`: 662 tests, 660 pass, 2 skipped, 0 fail.
- `pytest tests` (venv from `pipeline/requirements.txt`, `backend/requirements.txt`): 1,097 pass, 8 skipped. Four files do not collect and two tests fail on Windows only; main `82340ef` fails the same way and Linux CI passes on it (#89).
- S3 and release tests: 189 of 189 pass with `PYTHONUTF8=1`.
- Pages on a local `server.js`: home, observatory (WISE 0855, Barnard, R Dra), survey, compass, Star Fix, stories. No script errors. Observatory pages show Quick Release 3. Survey shows 16 billion detections.
- Audit: no deleted files, no conflict markers, no workflow or package change. README already documents the S3 fallback.

## Open

- #88 (M1, M2), #89 (Windows test failures), #74 (live site deploys from the fork's gh-pages, not main).
