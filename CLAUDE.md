## Agent skills

### Issue tracker

Issues live in GitHub Issues on kneha07/field-shift (use the `gh` CLI). See `docs/agents/issue-tracker.md`.

### Triage labels

Default labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Branches and worktrees

- Never commit directly on `main`. Do all work on a branch in its own worktree: `.worktrees/<task>` (or `.claude/worktrees/<task>`).
- `main` gets only merges of finished, reviewed branches (or reviewed pull requests).
- Agents never run `git push`. A human or the orchestrating session pushes after review.
- Review and record files (`artifacts/`) follow the same rule: write them on the branch, not in the main checkout.
