# Project manager review: PRs #97, #103, #104

Date: 2026-11-15. Reviewer seat: project_manager (independent, not the author).
Base: `integrate/2026-11-15c` at `3873d3a` (local main with security fixes + origin/main + pinned `pages.yml` actions).
Method: `git diff HEAD...<sha>`, PR bodies, comments and reviews, closing issues, CI runs, unit tests on each
merge tree, a data diff of `app/data/skystars.json`, and HTTP checks of the live sites.

## Summary

```
PR    pinned SHA   verdict  High  Medium  Low
#97   357b8af      PASS     0     4       4
#103  ece4f42      PASS     0     1       2
#104  9cbe006      PASS     0     3       3
```

Shared evidence for all three PRs:

| Check | Result |
|---|---|
| Merge with `HEAD` (`git merge-tree`) | No conflicts for each PR. No conflicts for #97 + #103 and #97 + #104. |
| CI on the pinned SHA | All jobs pass. Run IDs 43790681423 (#97), 43791706339 (#103), 43791726776 (#104); `headSha` equals the pinned SHA. CI runs against origin/main, not against this integration base. |
| `node --test test/*.test.js` on `HEAD` alone | 669 tests, 667 pass, 0 fail, 2 skipped. |
| Same, on `HEAD` merged with #97 / #103 / #104 | 667 / 667 / 670 pass, 0 fail. |
| Human review on GitHub | None. The Codex review failed on all three PRs (usage limit). This review and the tech_lead review are the only reviews. |

---

## PR #97: Sky Compass pull-out bars, hover names, camera power and more

- Branch: `feature/compass-pullout-bars`. Pinned SHA: `357b8af22b22bc7dbc1f0c959bd7af00bc543a3b`.
- Closing issue (GitHub link): #95. The body also says "Closes ... #98", but GitHub does not link #98.
- Size: 15 files, +892 / -48. 21 commits.
- **Verdict: PASS.** The closing criterion (#95) is met. The phone test is named as not done (#93). Fix the Medium items before or right after the merge.

### Criteria

| # | Criterion (source) | Status | Evidence |
|---|---|---|---|
| 1 | #95: the star sheet does not ask for a missing prediction file (no 404). Option: check an index first. | Met | `app/pathview.js:27-35` loads `stars/pred/index.json` once and fetches `stars/pred/<key>.json` only for a listed key. `app/data/stars/pred/index.json` holds 20 keys (no `hip106786`). `pipeline/star_ml.py:779-783` rewrites the index after each run. Fallback: if the index fails, it fetches as before. |
| 2 | #95 browser evidence: Bunda loads only `index.json`, Vega still loads `hip91262.json` | Not verifiable by me | Claimed in the #95 comment and `artifacts/compass-pullout-bars.md`. I did not re-run the browser. The code path agrees with the claim. |
| 3 | Body: bars hide, tabs open them by tap and swipe, state kept, first-visit bounce | Not verifiable on a phone; desktop claim only | `app/compass.html`, `app/compass.css`, `app/compass.js`. No unit test covers the gestures. Phone test owed in #93. |
| 4 | Body: camera stops under full photographs and restarts | Not verifiable | Tested only with a fake `getUserMedia` (run record). Real phone owed (#93). |
| 5 | Body: wake lock, Esc and swipe-down close sheets | Partly verifiable | Esc: desktop claim. Wake lock and swipe: phone only (#93). |
| 6 | Body: Learn menu (time machine, tour, quiz, infrared, candidates, sky log) | Met in code, not tested | `app/learn.js` (318 new lines) and `app/realsky.js` (+196). No new unit test: the test count is the same with and without #97 (667). |
| 7 | Body: "Full suite: 664 pass, 0 fail" | Met (at the author's base) | On this base: 667 pass, 0 fail. The PR adds 0 tests. |
| 8 | Body: hidden features (`class="later"`) do not show; `?later=1` shows them | Met in code | `app/compass.css` `.later { display: none !important; }`; `app/compass.html:94` (Class link) and `:212` (save box). |
| 9 | README and docs agree with what ships | Not met | See M1. |
| 10 | #98 closes with this PR | Not met (automation) | `closingIssuesReferences` holds only #95. See L1. |

### Findings

**Medium**

- **M1. README describes a feature that this PR hides.** `README.md:226-227` says "Save the sky for a place" in the ⓘ sheet keeps pictures for a trip. #97 hides that box (`app/compass.html:212`, `class="save-box later"`). After the merge, users and judges read about a control they cannot see. The README also does not mention the pull-out bars or the 🎓 Learn menu. Fix: one sentence in the README.
- **M2. About 500 new lines of logic have no unit test.** `app/learn.js` (tour, quiz scoring, sky log) and the new `app/realsky.js` math (space motion, precession, pole star, galaxies) have no test. The only test edits add stubs (`test/compass-flows.test.js:81`, `test/realsky-telescope.test.js:65`). The run record has browser checks (Arcturus 6.30° in 10,000 years; Polaris 0.7°, Thuban 0.3°, Vega 4.4°). These numbers are good candidates for one small assert test.
- **M3. Scope is much wider than the title and the closing issue.** The title says pull-out bars. The PR also adds a search pane, galaxies, constellation glow, six learning modes, a time machine with precession, distance lines on every card, and Webb frame shapes. It closes #95 and claims #98 and #99. One PR with 21 commits is hard to review and hard to revert in part. The team goal is the Planet X and SPHEREx challenge; most learning modes are side work for that goal. I do not block for this, but record it.
- **M4. Issue #99 is closed before the code merges.** #99 says "Built in PR #97 ... Closed as done." PR #97 is still open. If #97 does not merge, #99 shows done with no shipped code. Fix: reopen #99 and close it on merge, or link it with "Closes #99".

**Low**

- **L1. #98 will not close on merge.** The body says "Closes #95 (...) and #98 (...)". GitHub links only #95. Add a separate "Closes #98" line.
- **L2. The PR body contradicts itself about precession.** The Time machine bullet says "Straight-line motion only; precession is not shown, and the panel says so." A later bullet and `app/learn.js:102-104` say precession is modelled. Delete the old sentence.
- **L3. Issue comments cite a commit that is not on the branch.** #95 and #98 comments and the run record cite `251d8e9`. The branch has `b524ca6` (same patch-id `b6cd34e8`, rewritten). `git merge-base --is-ancestor 251d8e9 357b8af` is false. Update the comments to `b524ca6`.
- **L4. Hidden code ships to production.** The Class link (place rounded to about 10 km) and offline sky packs ship hidden but work with `?later=1`. This is an owner decision and the body names it. Record it so the release step is not forgotten.

### Open follow-ups this PR leaves

- #93: real-phone test (bars, camera stop and restart, wake lock, swipe-down, Learn modes, search with the phone keyboard). Owed.
- #71: telescope zoom phone test. Still owed from PR #82.
- Release of the `class="later"` features: owner decision, no issue.

---

## PR #103: Sky Compass stars from NASA HEASARC Hipparcos

- Branch: `feature/nasa-stars`. Pinned SHA: `ece4f42e54bc80912a9bd9db1c4d3ca15b4d6cdf`.
- Closing issue: #90.
- Size: 7 files, +126 / -14.
- **Verdict: PASS.** Every required criterion in #90 is met and I reproduced the data claims.

### Criteria

| # | Criterion (#90) | Status | Evidence |
|---|---|---|---|
| 1 | Keep HYG for names, HIP keys, distances, constellations | Met | My diff of old and new `skystars.json`: 8,920 / 8,920 keys match; 0 name, 0 distance, 0 constellation changes. |
| 2 | Position, V mag, spectral letter from the HEASARC `hipparcos` table | Met | `pipeline/make_sky_stars.py` `hipparcos()` (xamin `format=text`, `vmag<=7`); `stars()` overrides ra, dec, mag, letter. `meta.source` names HEASARC. |
| 3 | Move J1991.25 positions to J2000 with proper motion | Met | `YEARS = 8.75`; ra step divides `pm_ra` by cos(dec). Sirius assert in `stars()`. Worst shift 16.2″ (Toliman), then 15.8″ (Rigil Kentaurus, Epsilon Indi): this agrees with the record. |
| 4 | The drawn sky and the tap links stay the same | Met | Same keys; mag changes 0; letter changes 0; median shift 0″. |
| 5 | Source line "Hipparcos, via NASA HEASARC" | Met | `app/skyview.js:72`, `app/explorer-learn.js:122`. |
| 6 | Stop if the answer is cut short | Met | `sys.exit` on `OVERFLOW` or under 15,000 rows. |
| 7 | Stdlib only, no new dependency | Met | `math`, `urllib`, `json` only. |
| 8 | Tests pass | Met | 667 pass on the merge tree. Tolerance in `test/skyview.test.js:34-36` moves from 0.001° raw RA/Dec to 0.01° on-sky angle; the largest real shift is 0.0045°. |
| 9 | Browser check (`RealSky.selfTest()` / `test/browser/realsky.mjs`) | Met by CI, not run locally | The record names it as not run. CI job "Sky Compass browser check" runs `node test/browser/realsky.mjs` and passed on `ece4f42`. |
| 10 | README credits | Not met | See M1. |

### Findings

**Medium**

- **M1. README still says the Eye stars come from HYG and does not credit HEASARC.** `README.md:220` says "Eye draws the stars ... (HYG via the star database ...)". The data table (`README.md:693-698`) has no HEASARC Hipparcos row. The goal of #90 is NASA data credit for the Space Apps entry. The README is what judges read. Fix: one line at `:220` and one row in the data table.

**Low**

- **L1. The data change is mostly a credit change.** Magnitudes and letters do not change. Median position shift is 0″. This is correct and cheap, and it serves the goal. Say this in the PR body so no reader expects a visible change.
- **L2. The pipeline now needs the network and a non-TAP HEASARC endpoint.** If xamin changes its text format, `make_sky_stars.py` stops (it does not write bad data). Accepted. `app/app.js:48` still says HYG v4.0; the record names it and leaves it, which is right for that tab.

---

## PR #104: Deployment guide and script (GitHub Pages or a Cloudflare Worker)

- Branch: `docs/deploy-guide`. Pinned SHA: `9cbe006e175d60dc1339b8bf9ed0e7626dc5f7d9`.
- Closing issue: none. Criteria come from the PR body. Related: #102 (Pages off), #74 (live site behind main).
- Size: 6 files, +201 / -1.
- **Verdict: PASS.** The guide, script, config and tests exist and work. The Pages path is honestly marked as not tested. The guide has gaps (M1-M3) that should be fixed in a follow-up.

### Criteria

| # | Criterion (PR body) | Status | Evidence |
|---|---|---|---|
| 1 | One guide that compares two methods and gives the steps | Met | `docs/deploy.md` (115 lines). |
| 2 | `scripts/deploy.js check \| pages \| cloudflare` | Met | `scripts/deploy.js`. `pages` stops with the admin step when `gh api repos/{owner}/{repo}/pages` fails. |
| 3 | `check` uses the same list as `pages.yml` | Met | `test/deploy.test.js:18-22` reads the list from `.github/workflows/pages.yml:44`; passes on this base (670 total). |
| 4 | `wrangler.jsonc`: Worker `wanderers`, `app/` as assets, no server code | Met | `wrangler.jsonc:5-9`. |
| 5 | README links the guide; `.gitignore` ignores `.wrangler/` | Met | `README.md:300-301`; `.gitignore:23-24`. |
| 6 | `node --test test/deploy.test.js`: 3 of 3 pass | Met | +3 tests on the merge tree (667 to 670). |
| 7 | Cloudflare: `/` 200, `/compass` 200, `/api/health` 404 | Met today | My HTTP checks on 2026-11-15: 200, 200, 404. |
| 8 | Cloudflare deploy was "`app/` of `main` 58722d9" | Not verifiable; evidence says otherwise | `58722d9` does not contain `app/_headers` (security commit `ac766e3` is not its ancestor). The live site sends the `_headers` values (HSTS, `X-Frame-Options`, CSP `frame-ancestors`). So the live site comes from a later deploy of another tree. See L1. |
| 9 | A real Pages publish | Not met, honestly named | `gh api repos/kneha07/WANDERERS/pages` gives 404 today; `https://kneha07.github.io/WANDERERS/` gives 404. Owner step in #102. |
| 10 | The guide agrees with how the live site is deployed | Partly met | Cloudflare steps agree with the live Worker. README "Live" link disagrees. See M2. |

### Findings

**Medium**

- **M1. The guide does not say that GitHub Pages drops the security headers.** The security review (`artifacts/security-review-2026-11-15.md:79`) says "GitHub Pages ignores the file" (`app/_headers`). `docs/deploy.md` compares the two methods but does not mention headers. A team that moves to Pages loses nosniff, frame-ancestors, referrer policy and HSTS with no warning. Fix: one row in the comparison table.
- **M2. The guide does not settle which link is the live demo.** `README.md:7` "Live:" points to the fork `rajryadav4.github.io/wanderers` (200, stale; #74 open). The guide names `kneha07.github.io/WANDERERS` (404, Pages off) and `wanderer.johnyc.com` (200). The PR's goal is "a permanent link that does not depend on a laptop". After this PR, a judge still gets the stale fork from the README. Fix: choose one link and put it on `README.md:7`, or record the choice in #74.
- **M3. The only working permanent link depends on one personal account.** The PR body says the Worker and `wanderer.johnyc.com` belong to John's Cloudflare account. `docs/deploy.md` does not say this. A teammate who follows the guide gets a different `*.workers.dev` address, and cannot update the live domain. Fix: state the owner in the guide, or make Pages (#102) the team link.

**Low**

- **L1. The PR body's deploy evidence is stale.** See criterion 8. The site works, but the claim "deployed `app/` of `main` 58722d9" does not match what is live. Update the body.
- **L2. `wrangler deploy` uploads the working tree, not a commit.** `.gitignore:19-21` ignores Sky Survey working files under `app/data/survey/`. Wrangler does not read `.gitignore`, and there is no `app/.assetsignore`. On a machine that ran the survey pipeline, those local files publish to Cloudflare but not to Pages. No such files exist in the main checkout today. The guide's "Before every deploy" steps reduce the risk but do not remove it.
- **L3. `pages` reports every `gh api` failure as "Pages is not on".** An auth or network error gives the same message (`scripts/deploy.js:26-29`). Accepted for a helper script.

---

## Risks across the three PRs

```
#97 merges  ──► README stale (save box)         ──► fix README:226
            ──► phone behaviour unproven        ──► #93 (human, real phone)
#103 merges ──► README credit still HYG         ──► fix README:220, data table
#104 merges ──► Pages still off                 ──► #102 (repo admin)
            ──► README "Live" still the fork    ──► #74 (choose one link)
            ──► Pages path has no headers       ──► note in docs/deploy.md
```

- No PR deletes a test. No PR leaves a TODO in shipped code. The `ponytail:` ceiling on precession (`app/realsky.js:77`) is named.
- Live site today has none of #97 (`/learn.js` gives 404) and none of #103 (`skyview.js` has no "HEASARC"). After a merge, someone must redeploy the Worker. The guide gives the command.
