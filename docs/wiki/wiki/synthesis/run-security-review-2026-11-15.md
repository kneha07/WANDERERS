# Run: security review and fixes, 2026-11-15

- Branch: `fix/security-2026-11-15` (worktree `.worktrees/security-review`), from `main` adc4eb8. Not pushed, not merged.
- Report: [artifacts/security-review-2026-11-15.md](../../../../artifacts/security-review-2026-11-15.md)
- Request: "check critically about the security of this repo", then "fix them all".

## What changed

- `server.js`: Host and Origin guard; `claude -p` runs with no tools and no MCP servers (critical finding).
- `star_image/*.heic`: EXIF GPS rounded to 0.1 degree; new test `SamplePrivacy`.
- Workflows: actions pinned to commit SHAs; the pin test requires a SHA.
- `app/_headers`: security headers for the Cloudflare Worker.
- `app/realsky.js`, `app/app.js`: `Object.hasOwn` check and escaped star card.

## Open items

| Item | Owner | Where |
|------|-------|-------|
| Merge the branch to `main`, then push | human | this branch |
| Restart every running `server.js` (one ran on port 8020) | human | laptop |
| Redeploy the Worker `wanderers` so `app/_headers` applies | human approval | `scripts/deploy.js cloudflare` |
| Add a ruleset that protects `main` | kneha07 (admin) | kneha07/WANDERERS#105 |
| Exact GPS of the old photos stays in git history and in the fork rajryadav4/wanderers | photo owner decides | report section 2 |

Decision: the GPS history item has no public issue on purpose. A public issue tells readers where to find the location
data. Keep it in the report and decide it in private.

## Checks

- `node --test test/*.test.js`: 663 pass, 2 skipped.
- `python -m pytest tests`: 1103 pass; the failures are Windows-only and also fail on `main` (`resource` import,
  file encoding).
- Proof of the fix: the attack text given to `claude -p` with the new flags wrote no file.
