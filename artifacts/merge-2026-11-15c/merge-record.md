# Merge record: integrate/2026-11-15d (rebuilt from integrate/2026-11-15c)

Status: DONE for #103 and #104. PR #97 is held (review FAIL). `main` is fast-forwarded to this branch. Nothing is pushed.

## Result

| Tip | SHA | Result |
|---|---|---|
| `main` (origin/main + security fixes, rebuilt by another session) | 4f52008 | base |
| `pages.yml` actions pinned | — | already on main: 9008ea5 |
| PR #103 feature/nasa-stars | ece4f42 | PASS, merged: d40695f |
| PR #104 docs/deploy-guide | 9cbe006 | PASS, merged: 3463b65 |
| doc drift: README credits HEASARC | — | 58056fa |
| PR #97 feature/compass-pullout-bars | 357b8af | **FAIL, not merged** |

Out of scope, left as is:
- `feature/chinese-version` (10fdbc4): no PR, Hong Kong wording check by the user is open.
- `docs/paid-features-plan` (144f147): local only by decision.
- Old remote branches with no PR (for example `docs/readme-honest`, `chore/unify-tests`): not requested.

## Rebuild

While this merge ran, another session reset `main` from d87dd53 to a new history: `origin/main` + the security merge (ad01df4) + its own pin commit (9008ea5) + a run record (4f52008). The code tree of 4f52008 equals my base 3873d3a. So I replayed only the PR merges and my commits on top of 4f52008, in a new branch `integrate/2026-11-15d`. The old `integrate/2026-11-15c` stays as evidence. The 3873d3a pin repair is not needed: 9008ea5 makes the same change.

## Contract audit

- Security contract (from ac766e3): every GitHub action is pinned to a commit SHA.
- `origin/main` #92 added `.github/workflows/pages.yml` with unpinned actions. The merge brought it in.
- Repair: 3873d3a pins the 4 actions. The pins are the same as the uncommitted diff in `.worktrees/security-review`. Each SHA exists upstream (checked with `gh api`).
- The dirty `pages.yml` in `.worktrees/security-review` stays in place, not touched. It is now redundant with 3873d3a.
- #103 changed the star source but left README credits on HYG. 58056fa fixes the doc drift. App credits (`app/skyview.js:72`) already named HEASARC.
- No PR changes `app/_headers`, `server.js` or `.github/`.

## Review panel

| PR | tech_lead | project_manager | user_advocate | Review file |
|---|---|---|---|---|
| #97 357b8af | PASS (0 H) | PASS (0 H) | **FAIL (3 H)** | `artifacts/review-pr-97-357b8af.md` |
| #103 ece4f42 | PASS (0 H) | PASS (0 H) | PASS (0 H) | `artifacts/review-pr-103-ece4f42.md` |
| #104 9cbe006 | PASS (0 H) | PASS (0 H) | PASS (0 H) | `artifacts/review-pr-104-9cbe006.md` |

The `gh` account is the PR author, so the PR summaries are comments, not change requests.

Why #97 waits: the skill rule says fix High findings before the merge. Agents do not push, so the fix on the PR branch needs the owner. Highs: back leaves the compass (H1), layers stack (H2), double tap logs twice (H3).

Issues filed:
- #106: learn quiz timer is not cancelled by `close()` (#97).
- #107: Cloudflare `.html` redirect breaks offline compass; deploy script has no prompt; Pages drops `_headers` (#104).

## Checks

Base tip 3873d3a: `baseline-checks.txt`. Tested tip 96a3fa4 (on integrate/2026-11-15c): `tip-checks.txt`. The rebuilt tip has the same tree except one run-record doc from main.
- `node --test test/*.test.js`: 670 pass, 0 fail, 2 skipped (base: 667 pass).
- `node --check` on app and server files: pass.
- Python `tests/` (with `PYTHONUTF8=1`): 1105 pass, 1 fail. The failure is `test_survey_rank_score.py::test_every_term_is_documented_in_the_table` (`tile_edge`). It fails on `origin/main` 58722d9 too: local Python 3.14 docstring change; CI uses 3.12.
- `test/test_fov.py`: OK.
- Not run on Windows: 4 survey test files import Unix-only `resource`; `backend/` needs `fastapi` and `aiohttp`; the browser test `realsky.mjs`; a real phone (#93). Ubuntu CI is the gate after push.

Post-merge audit: `git diff --check` clean, no unmerged files, no conflict markers, no unpinned `uses:`, 58722d9 / ece4f42 / 9cbe006 / 4f52008 are ancestors of the tip.

## Next steps (owner)

1. Push `main`. Then #103 and #104 close as merged on GitHub, and #90 closes.
2. Decide on #97: fix H1–H3 on the PR branch and review again, or accept the risk and merge 357b8af.
3. Optional: drop the now-redundant `pages.yml` diff in `.worktrees/security-review`.
