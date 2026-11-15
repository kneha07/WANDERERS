# Review: PR #4 at a1175d3

Verdict: **FAIL**. Reviewed on 2026-11-14 on branch `integrate/2026-11-14`.
Panel: tech_lead + project_manager (phase 1). The reviewers are independent of the author (maevek092).

- **High:** the PR adds one file named `tests` at the repo root. Its own run command, `node --test tests/server.test.js`, cannot work, and the file blocks the `tests/` folder of PRs #7 and #8. Fix: move it to `test/server.test.js`, next to `fields.test.js`.
- **High (now fixed outside the PR):** the tests found two real `server.js` bugs: `GET /%ZZ` crashed the server, and an unknown target leaked the file path. Commit `5e9a266` fixes both (#10). With that fix, 8/8 tests pass.
- **Medium:** the title says 'security tests', but most tests check input validation. There is no traversal test.
- No CI checks are configured.

Full role reviews:
- `artifacts/review-tech_lead-prs-4-7-8.md`
- `artifacts/review-project_manager-prs-4-7-8.md`

