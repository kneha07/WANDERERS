# Merge record: integrate/2026-11-15c

Status: IN PROGRESS. The user_advocate seat runs. No PR is merged yet. Nothing is pushed.

## Scope

| Tip | SHA | Action |
|---|---|---|
| local `main` (security fixes) | d87dd53 | base |
| `origin/main` (#91, #92) | 58722d9 | merged: 8a6180d |
| PR #97 feature/compass-pullout-bars | 357b8af | review gate |
| PR #103 feature/nasa-stars | ece4f42 | review gate |
| PR #104 docs/deploy-guide | 9cbe006 | review gate |

Out of scope, left as is:
- `feature/chinese-version` (10fdbc4): no PR, Hong Kong wording check by the user is open.
- `docs/paid-features-plan` (144f147): local only by decision.
- Old remote branches with no PR (for example `docs/readme-honest`, `chore/unify-tests`): not requested.

## Contract audit

- Security contract (from ac766e3): every GitHub action is pinned to a commit SHA.
- `origin/main` #92 added `.github/workflows/pages.yml` with unpinned actions. The merge brought it in.
- Repair: 3873d3a pins the 4 actions. The pins are the same as the uncommitted diff in `.worktrees/security-review`. Each SHA exists upstream (checked with `gh api`).
- The dirty `pages.yml` in `.worktrees/security-review` stays in place, not touched.

## Prediction

`git merge-tree` shows no conflicts for #97, #103 and #104. Only `app/skyview.js` is shared (#97 and #103). The tech_lead seat checked that the two changes are in separate parts and work together.

## Review panel

| PR | tech_lead | project_manager | user_advocate |
|---|---|---|---|
| #97 357b8af | PASS (0 H, 2 M) | PASS (0 H, 4 M) | running |
| #103 ece4f42 | PASS (0 H, 1 M) | PASS (0 H, 1 M) | running |
| #104 9cbe006 | PASS (0 H, 2 M) | PASS (0 H, 3 M) | running |

Seat files: `artifacts/review-tech_lead-prs-97-103-104.md`, `artifacts/review-project_manager-prs-97-103-104.md`.

Issues filed for findings that stay open after the merge:
- #106: learn quiz timer is not cancelled by `close()` (#97, tech_lead M1).
- #107: Cloudflare `.html` redirect breaks offline compass; deploy script has no prompt; Pages drops `_headers` (#104).

## Checks on the base tip (3873d3a)

See `baseline-checks.txt`.
- `node --test test/*.test.js`: 667 pass, 0 fail, 2 skipped.
- `node --check` on app and server files: pass.
- Python `tests/`: 1104 pass. 2 fail, both environment only:
  - `test_spherex_releases.py::test_readme_documents_the_sync`: cp1252 read. Passes with `PYTHONUTF8=1` (117 pass).
  - `test_survey_rank_score.py::test_every_term_is_documented_in_the_table` (`tile_edge`): fails on `origin/main` 58722d9 too. Local Python 3.14 docstring change; CI uses 3.12.
- Not run on Windows: 4 survey test files import Unix-only `resource`; `backend/` needs `fastapi` and `aiohttp`. Ubuntu CI is the gate.

## Next steps

1. Wait for user_advocate.
2. Write `artifacts/review-pr-<n>-<sha>.md` per PR and post a summary comment on each PR.
3. Merge the reviewed SHAs, in order #97, #103, #104.
4. Fix doc drift found by project_manager (README credits for #103, README text for hidden feature in #97).
5. Run checks and the post-merge audit. Fast-forward `main`. Do not push.
