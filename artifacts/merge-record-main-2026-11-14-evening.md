# Merge record: local main, 2026-11-14 evening

Operator: the orchestrator (Claude), on John's request "pull from main and merge from other branches to keep the repo up to date". Skill: merge-branches-to-master.

## Done

| Step | Commit | Result |
|---|---|---|
| Merge `origin/main` (PR #22 star database, PR #23 long-range view) into `main` | `e24ab89` | No conflicts and no conflict markers. Backend pytest 46 pass; `node --test test/*.test.js` 115 pass, 1 skipped. |

Contract audit: origin adds `/api/star-predict` and star-job code to `server.js`, plus README sections. It does not touch the live-mode routes (`/explore/`, `/api/frames`, `/api/live-health`), `start.js`, `backend/` or `web/`. This is an orthogonal change.

## In the review gate (not merged yet)

| PR | Pinned head | Status |
|---|---|---|
| #19 Windows Python lookup (closes #18) | `8299018` | tech_lead + project_manager review running → `artifacts/review-pr-19-8299018.md` |
| #20 Unify tests, one command, strict mode | `5cbd519` | tech_lead + project_manager review running → `artifacts/review-pr-20-5cbd519.md` |

Neither PR has CI checks.

## Not merged, with reasons

| Tip | Reason |
|---|---|
| PR #4 `tests/server.test.js` (`a1175d3`) | Earlier review FAIL (`artifacts/review-pr-4-a1175d3.md`). The head is unchanged, and the PR is CONFLICTING now. The author must fix it first. |
| `origin/wanderers` (`b13ced1`, +7 commits, 291 files) | Raj's active branch with no pull request. The team merges through PRs, so it waits for Raj's next PR and its review. |
| `origin/feature/star-database-ml` (`f4c42f8`, +1) | Redundant: its tree is the same as `4cbecc2`, which is in `origin/main` through PR #23. |
| `feature/insights` (local, `bec8a05`, +6) | Another session's unpushed work. It was left untouched. |
| `feat/star-info` (local) | Our work in progress (review fixes + "About this star"). It merges after its implementer finishes. |

Preserved and not touched: uncommitted edits in `.worktrees/real-sky` (`app/compass.*`, another session).

## Push

`main` is not pushed. The push waits for the PR #19/#20 reviews, the star-info merge and the user's go-ahead.

## Update: review results

| PR | tech_lead | project_manager | user_advocate | Decision |
|---|---|---|---|---|
| #19 (`8299018`) | PASS (0 high) | PASS (0 high) | running | Merge the pinned SHA if the user_advocate review passes. The `server.js` star-predict lookup has the same Windows bug: #27. |
| #20 (`5cbd519`) | FAIL (2 high) | FAIL (2 high) | not run (phase 1 failed) | Not merged. "Changes requested" is posted on the PR. |

The live explorer's phase-2 user_advocate review failed (H1, stale panels while loading): #26. The fix is in progress on `feat/star-info`.
