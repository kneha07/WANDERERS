# Run: security review and fixes, 2026-11-15

- Branch: `fix/security-2026-11-15` (worktree `.worktrees/security-review`), from `main` adc4eb8, then `origin/main` 58722d9 merged in.
- Merged into local `main` as ad01df4 (origin/main 58722d9 + this branch). Not pushed.
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
| Push `main` (ad01df4); the Pages workflow then deploys | human | local `main` |
| Restart every running `server.js` (one ran on port 8020) | human | laptop |
| Add a ruleset that protects `main` | kneha07 (admin) | kneha07/WANDERERS#105 |
| Exact GPS of the old photos stays in git history and in the fork rajryadav4/wanderers | photo owner decides | report section 2 |

Decision: the GPS history item has no public issue on purpose. A public issue tells readers where to find the location
data. Keep it in the report and decide it in private.

## Checks

- `node --test test/*.test.js`: 663 pass, 2 skipped.
- `python -m pytest tests`: 1103 pass; the failures are Windows-only and also fail on `main` (`resource` import,
  file encoding).
- Proof of the fix: the attack text given to `claude -p` with the new flags wrote no file.

## Deploy, 2026-11-15

- Worker `wanderers` redeployed from `git archive main app` (ad01df4): version 394aee12-05c5-42b2-9dcc-b097e611686f.
  Only `app.js` and `realsky.js` changed, so the live site was on 58722d9 before.
- Live check on https://wanderer.johnyc.com: `/`, `/compass`, `/survey`, `/app.js` give 200 with all 5 headers;
  `/_headers` gives 404 (not served). Observatory and Sky Compass load; the only console errors are the expected
  `/api/health` and `/api/live-health` 404s of the static site. Not checked: the Aladin sky map after Begin
  (the CSP has no `script-src`, so it cannot block it).
- Also pinned `.github/workflows/pages.yml` (new on origin/main) to commit SHAs.
