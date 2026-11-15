# Project-manager review: feat/star-info, fix-loop round 3

- Scope: `git diff a706670..96c5395` (4 commits: `8886346`, `9827e37`, `65dbe71`, `96c5395`).
- Input findings: `artifacts/review-user_advocate-star-info.md` (round 2, `a706670`).
- Orchestrator checks (taken as given, not re-run): pytest 110 pass, node --test 155 pass / 1 skip, web 61 pass,
  build ok, live through server.js: 4 aborted cold requests, then health 200 and frames 200, 0 `ERR_STREAM` lines.

## Verdict

**PASS.** No unresolved high finding. Two medium findings remain about documentation and closure. They do not block
the merge, but fix M-A before the merge, because the API contract is the source of truth for teammates.

## Per-finding map

| Finding | Status | Evidence |
|---|---|---|
| NH1 (high) server crash on target switch | FIXED | `server.js:147-157`: no pipe to a destroyed `res` (`if (res.destroyed \|\| res.writableEnded) return r.destroy()`), `error` handler guarded, `res.on("close")` destroys upstream. Regression test `test/liveproxy.test.js:70-85` (browser aborts at 200 ms, answer at 800 ms, then health 200 and a second frames call). Live: `artifacts/star-info/live-checks.md` round 3 (curl -m 2, then 200; browser switch at 1440 and 375; 0 `ERR_STREAM`); screenshots `1440-switch-server-js.png`, `375-switch-server-js*.png`. Stress walk through server.js 9/9 PASS (it failed in round 2). |
| NM1 (medium) "larger than the noise" for empty sky | FIXED | `web/src/data.ts` `sourceSeen` / `brightestSeen` (rule: the brightest survey must show a centroid or flux >= 5 sigma). Panel: `web/src/panels.tsx` "No source at this position — the brightness numbers are sky noise." About: `web/src/about.ts` `measuredSentence`. Tests in `web/src/data.test.ts`, `web/src/about.test.ts`. Live: `1440-typed-wise.png`. |
| NM2 (medium) no epoch hint for old fast-mover coordinates | FIXED (as a hint) | `backend/about.py:206-241` `path_near`, `fast_movers` (SIMBAD TAP, > 1″/yr, path 1990-2030 within 60″); fallback from Gaia stars `web/src/about.ts` `fastHint`; shown under the image `web/src/App.tsx:619`. Test `backend/test_about.py`. Live: WISE 0855 coordinates show "A fast-moving star (WISEA J085510.74-071442.5, 8.2″/yr) is 127″ from here …". The view is still not re-centred; that is honest, the text tells the user to search by name. |
| NL1 field name twice | FIXED | `web/src/rail.tsx` uses `titleOf(r).catalog`; test `web/src/rail.test.ts`. |
| NL2 two motion numbers | FIXED | One `motionClause` in `web/src/data.ts`, used by Motion and About. |
| NL3 "G = 16.9" unexplained | FIXED (minimal) | `web/src/about.ts` "(Gaia brightness; larger is fainter)". No distance when parallax is poor; that part stays. |
| NL4 "Showing A until B" label placement, old timeline/toggle | NOT FIXED, tracked | #47 body (PM L4) and #47 comment (label below image / cut at 375). |
| NL5 About only in Data tab | NOT FIXED, tracked | #47 comment. |
| NL6 phone chip row scrolled to end | FIXED | `web/src/App.tsx:299-301` `scrollTo({left: 0})` on a new query; live-checks round 3 (scrollLeft 0). |

## Stated deviations: honest?

- NM1 judged at the brightest survey: honest in code comments and commit `96c5395` body. **Not in docs.** See M-A.
- NM2 path-based search: honest in commit `9827e37` body and `about.py` docstrings. **`fast_movers` is a new field
  of `GET /api/about` and `docs/blink/api.md:126-142` (field table) does not list it.** See M-A.
- One motion number (per year) for Motion and About: consistent with `docs/blink/api.md:155` and
  `docs/blink/README.md:48` ("motion per year and direction"). The Motion panel now drops the "moved X″ in N
  months" wording; pixels stay in brackets. Acceptable.

## Findings

- **M-A (medium) API docs not updated.** `docs/blink/` has no change in `a706670..96c5395`. Missing: the
  `fast_movers` field in the About table (`docs/blink/api.md:126-142`), the "no source, so sky noise" rule for the
  brightness verdict, and the fast-mover hint under the image (`docs/blink/README.md:175-177` still says typed
  coordinates give no hint other than the chip). Docs now contradict the app. Cheap fix: 3 lines.
- **M-B (medium) closure is not automatic.** No commit on `main..HEAD` has `Closes #26` or `Closes #28`. #26 and #28
  are both OPEN. They close on merge only if the PR body says `Closes #26, Closes #28`, or someone closes them by
  hand. Evidence for both exists: #26 in `live-checks.md:32` and round-2 UA (H1 FIXED); #28 in `start.js:4,13-15,111-113`
  and `live-checks.md:54-60`. Both are closable on merge.
- **L-1 (low) #47 is stale.** Its body still lists "PM L2: typed WISE 0855 coordinates give no epoch hint", which NM2
  now fixes. Update #47 at merge.
- **L-2 (low) failed fast-mover lookup is cached.** `fast_movers` returns `[]` when SIMBAD does not answer
  (`backend/about.py:239-241`) and does not mark the source as failed, so the empty hint is cached 30 days. The Gaia
  fallback in `fastHint` reduces the impact. Add to #47.
- **L-3 (low) the hint replaces the difference-view note** (`web/src/App.tsx:619-621`). For typed coordinates in
  diff view, the user loses the "dark and bright pair" explanation. Small.

## Scope honesty and goal alignment

- No TODOs, no deleted tests, no mocked behaviour in the diff. Every change maps to a named finding. No gold-plating.
- `web/ux-walk.json` now points to port 8071 (server.js), so the walk covers the proxy. That closes the round-2 gap
  where the walk used the Vite server and missed NH1.
- Deferred items (NL4, NL5, earlier lows) are named in #47 and its comment.

## Merge readiness

Ready to merge after M-A (docs) and with `Closes #26` / `Closes #28` in the PR body (M-B). Nothing claimed in the
round-3 commits or `live-checks.md` is false, as far as the diff and evidence show.
