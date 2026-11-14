# User advocate review: PR #7 (8db452f) and PR #8 (3c72267)

Verdict: PR #7 PASS. PR #8 PASS (with medium findings). No high finding blocks the merge.

## Live run
- PR files copied with current `pipeline/*.py` into a scratch tree. Venv python: `python -m unittest discover -s tests` -> `Ran 20 tests ... OK`.
- System python (no numpy/astropy), PR #8 only: `Ran 0 tests ... OK (skipped=1)`. Confirms a false green.

## Job-to-be-done
- PR #7 guards what the public sees on evidence cards: classification text, high/medium confidence, the saturation note ("saturated" in `confidence_note`, a `warn` check), and candidate vs known status. This protects honest "candidate vs known" wording. Good.
- PR #8 guards the photometry that feeds the cards: bad-pixel masks, OVERFLOW kept for display, background subtraction, flagged-pixel exclusion, NaN paths.
- Gap: no test links PR #8 output (`nbad`) to PR #7 input (`flagged_points`). A unit change in one side would not fail. Low.

## Findings
### medium
1. PR #8 silent skip: `tests/test_data_quality.py` setUpClass turns ImportError into SkipTest. A teammate without deps sees `OK`. The skip text does say "Install pipeline dependencies first", which helps, but `OK` is the headline.
2. Discoverability: README (lines 82, 94) lists only `node --test test/...`. The Python tests and their run command are only in docstrings. A judge will not find them. Folder `tests/` next to `test/` adds confusion (also tech_lead medium).
### low
3. Docstrings say `python3`; on Windows the command is `python`.
4. Tests pin exact UI strings. Good as regression guards; a wording change needs a test update.

## Interaction design
No interactive surface (test files only). Feedback is unittest text: informative on fail (assert diffs), but misleading on skip (finding 1). Error recovery: skip message names the fix. Other Shneiderman rules not applicable.

## Note
`git status` of the integration worktree shows `M server.js`. This review did not change it.
