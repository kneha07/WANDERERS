# Merge record, 2026-11-15 (b)

Base: `main` = `origin/main` `cfc0129`. Integration branch: `integrate/2026-11-15b` (worktree `.worktrees/integrate-1115`).

```
cfc0129 ─┬─ f20cb73 merge feature/compass-telescope (PR #82, head 02c93d3)
         └─ 0e1c676 merge docs/project-explainer (head 6165b63)
```

## Tips merged

| Tip | Head merged | Review | Verdict |
|---|---|---|---|
| `feature/compass-telescope` (PR #82) | `02c93d3` | Panel to `bcc891f`: tech_lead r2 PASS, project_manager r2 PASS, user_advocate PASS (on the branch). Delta `bcc891f..34e410d`: `review-pr-82-34e410d.md`. `d3bbb71` is a merge of main (wiki append only); `02c93d3` adds `pr-body.md` only. | PASS-with-findings, no high or medium |
| `docs/project-explainer` | `6165b63` | `review-tech_lead-project-explainer-64cb979.md` (FAIL, M1-M4), fixes in `0382b8d`, re-review `review-tech_lead-project-explainer-0382b8d.md`. `6165b63` fixes re-review L1 (one sentence). | PASS-with-findings, no high or medium |

## Conflicts

- `docs/wiki/wiki/log.md`: append-only. Kept both sides. Main's star-fix and telescope entries first, then the explainer entry.

## Branches not merged (and why)

- `feature/real-sky`, `feature/real-sky-core`, `feature/real-sky-finish`, `feature/real-sky-main`: superseded by PRs #40 and #50. Their tips are older than main; a merge would regress main.
- `origin/chore/unify-tests` (#20), `origin/docs/architecture-diagram` (#30), `origin/docs/submission-and-credits` (#29): PRs closed without merge.
- `origin/docs/readme-honest`: superseded by #67.
- `feature/compass-pinch-zoom`: an ancestor of `feature/compass-telescope`, so merged with it.
- `origin/feature/star-database-ml`: patch-equivalent to main (no unique patches).
- Open PRs not in scope: #80 (fixes #79), #83 (new, unreviewed).
- Old branches cleanup: #68.

## Checks

- `node --test test/*.test.js` on `0e1c676`: 617 tests, 614 pass, 2 skipped, 1 fail. The fail is `classify.js points at the team repo's issue form ...`. It fails on `cfc0129` too (#79, fix in PR #80). Not caused by these merges.
- PR #82 CI: Node check red for the same reason (#79). No branch protection, so no required check. Python and browser checks were pending at merge time.
- `git diff --check`, `git ls-files -u`, conflict-marker scan: clean.
- Contract audit: no deleted files; no package, workflow or vendor change. `app/sw.js` adds the reviewed survey reissue check (orthogonal).
- Explainer page rendered in a browser (file://): tabs, Star Fix diagram label, UTF-8 charset OK.

## Open after merge

- Real-phone test of the telescope: #71.
- Low findings in both review files (not blockers).
- `main` is not pushed. A human pushes it.
