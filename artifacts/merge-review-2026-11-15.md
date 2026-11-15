# Post-merge review, 2026-11-15

Main moved from `184e071` to `a88e63a` while the merge check ran. Four PRs merged on GitHub with no independent review. This record reviews them after the fact.

## Merges reviewed

| PR | What | Merge | Head | tech_lead | project_manager | user_advocate |
|---|---|---|---|---|---|---|
| #65 | SPHEREx DR1 stage | `6be00e3` | `54e487d` | PASS-with-findings | FAIL (done-state) | PASS-with-findings |
| #64 | Star Fix | `f21f19d` | `0b558de` | FAIL (after debate) | FAIL (done-state) | FAIL |
| #66 | Catalogue-survey spec | `c9c4e0c` | `ff02bbb` | PASS-with-findings | PASS-with-findings | PASS |
| #67 | README accuracy | `a88e63a` | `09604fc` | PASS-with-findings | PASS-with-findings | PASS-with-findings |

The panel did one debate round. The reviewers agree on everything except the severity of #65. Nobody asks for a revert.

## Findings and where they are tracked

- #64: the PR adds private place names to public docs, and it merged before #57 was decided. Tracked in #57 (owner decision; removing the text needs a force-push).
- #64: the page hides the server error and blames the photo. Tracked in #73 (high).
- #64: CI skips the plate-solve tests, one spec doc still calls #27 open, and `fix_core.py` ends with a blank line. Tracked in #58.
- #65: "Confirmed" shows when nobody measured the 2014 spot. The PR's data snapshot is missing, and the empty filter misleads. Tracked in #72.
- #66: the spec's file paths clash with `pipeline/survey/`. Tracked in #60.
- #64 and #67: the live site is behind main (`starfix.html` gives 404). Tracked in #74.
- Old unmerged branches and open branches: tracked in #68.

## Branches not merged

- `feature/compass-telescope`: project_manager rates pinned head `7058588` FAIL. Another session is still working on the branch; its head is now `4e40a1d`. Review again at the final head after a PR is opened. Real-phone test: #71.
- `docs/project-explainer` (`64cb979`): see `review-tech_lead-project-explainer-64cb979.md`.

## Checks

- CI `checks` passes on `f21f19d`, `c9c4e0c` and `a88e63a`.
- `node --test test/*.test.js` on `a88e63a`: 588 tests, 586 pass, 2 skipped.
- `test_star_fix.py`: 10 OK, only with the star-fix worktree's venv.
- The SPHEREx and survey Python tests did not run locally, because `pytest` and `pyarrow` are missing.
- No conflict markers. `git diff --check` flags only the `fix_core.py` blank line at the end of the file.
