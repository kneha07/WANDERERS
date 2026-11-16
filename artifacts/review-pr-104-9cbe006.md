# Review: PR #104 docs/deploy-guide @ 9cbe006

- Pinned head: 9cbe006e175d60dc1339b8bf9ed0e7626dc5f7d9. Base: main. No closing issue.
- Verdict: **PASS**. Merged as 2fc49d5 on `integrate/2026-11-15c`.
- CI on the head: Node, Python, web build and Sky Compass browser check pass.

| Seat | Verdict | High | Medium | Low |
|---|---|---|---|---|
| tech_lead | PASS | 0 | 2 | 3 |
| project_manager | PASS | 0 | 3 | 3 |
| user_advocate | PASS | 0 | 0 | 3 |

## Open findings (tracked in #107)

- M (tech_lead): `wrangler.jsonc` keeps the default `.html` redirect (live 307 `/compass.html` → `/compass`). The offline compass and the installed app do not open with no signal on the Cloudflare host.
- M (tech_lead): `scripts/deploy.js:45` publishes local `app/` to the live domain with no prompt and no branch or dirty-tree check. It cannot spend money or push code.
- M (project_manager): `docs/deploy.md` does not say that GitHub Pages ignores `app/_headers`, so the security headers are lost on Pages.
- M (project_manager): the README "Live" link is still the stale fork (#74). `wanderer.johnyc.com` depends on a personal Cloudflare account.
- L (user_advocate): `git switch main` fails from a worktree; `gh run watch` right after a push can miss the new run; no check shows which commit is live.

No workflow `uses:` line changes. The security contract stays.
