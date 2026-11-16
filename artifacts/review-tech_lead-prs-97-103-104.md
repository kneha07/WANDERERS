# Tech lead review: PRs #97, #103, #104

Reviewer seat: tech_lead (independent, not the author). Date: 2026-11-15.
Base: `integrate/2026-11-15c` @ `3873d3a` (local main + security fixes + origin/main + pinned `pages.yml`).
Method: `git diff HEAD...<sha>` for each pinned head. Line numbers refer to the files at that head.

## Summary

| PR | Pinned head | Verdict | High | Medium | Low |
|---|---|---|---|---|---|
| #97 compass pull-out bars | `357b8af22b22bc7dbc1f0c959bd7af00bc543a3b` | PASS | 0 | 2 | 5 |
| #103 NASA HEASARC stars | `ece4f42e54bc80912a9bd9db1c4d3ca15b4d6cdf` | PASS | 0 | 1 | 3 |
| #104 deploy guide + script | `9cbe006e175d60dc1339b8bf9ed0e7626dc5f7d9` | PASS | 0 | 2 | 3 |

No PR has a High finding. The Medium findings do not block a merge. Fix them, or record them as follow-up issues.

```
base 3873d3a ──merge #97──► C1 ──merge #103──► C2 ──merge #104──► tree 4c68163
                (clean)            (clean)             (clean)
node --test test/*.test.js on tree 4c68163:  672 tests, 670 pass, 0 fail, 2 skipped
(the 2 skips are old data-presence skips in test/chartlayout.test.js; no PR adds a skip)
```

## Security contract check (all three PRs)

| Contract from the base | #97 | #103 | #104 |
|---|---|---|---|
| SHA-pinned `uses:` in workflows | not touched | not touched | not touched |
| `app/_headers` (nosniff, frame-ancestors, HSTS) | not touched | not touched | kept: `wrangler.jsonc` serves `app/`, and the live site sends the headers (checked with `curl -I`) |
| `server.js` same-origin guard, `claude -p` with no tools | not touched | not touched | not touched |
| Coarse photo GPS | not touched; the hidden Class link rounds to 0.1° | not touched | not touched |
| New browser fetch to an outside host | none (`data/survey/leaderboard.json` is same-origin) | none (HEASARC is fetched only by the pipeline) | none |

No PR regresses the security contract.

## Merge of #97 and #103 (both touch `app/skyview.js`)

- #97 changes `starCard()` (`app/skyview.js:51-59`). #103 changes the `CREDITS.eye` line (`app/skyview.js:72`). The hunks do not touch.
- Semantics: the #97 time machine (`app/realsky.js` `setYears`) reads the positions in `skystars.json` as J2000 base positions. It adds the HYG proper motion and radial velocity from `stars.json`. After #103, those base positions are Hipparcos moved to J2000. This is the same epoch and frame, so the combined result is correct.
- Proper-motion coverage after the merge: 8,878 of 8,920 drawn stars have a motion in `stars.json`. The other 42 stay still in the time machine. That is acceptable.
- Credits after the merge: the compass info panel says "Hipparcos (ESA) via NASA HEASARC". The star sheet in `app/compass.html` still says "HYG database v4.0" (old text, see #103 L2).

---

## PR #97: Sky Compass pull-out bars and learning modes

Pinned SHA: `357b8af22b22bc7dbc1f0c959bd7af00bc543a3b`. Verdict: **PASS**.
Closing issue: #95 (GitHub links only #95; see L4).

### Acceptance criteria (#95)

| Criterion | Status | Evidence |
|---|---|---|
| No 404 for stars with no prediction file | Met | `app/pathview.js:27-35` reads `stars/pred/index.json` first. The file exists at the head (20 keys). `pipeline/star_ml.py:779-783` writes it. If the index does not load, the code tries the fetch (same behaviour as before). |
| The sheet still opens | Met | `pred()` still returns `null` for a missing star. |

### Medium

**M1. A quiz timeout from an old round runs after the user closes the quiz.** `app/learn.js:190` calls `setTimeout(nextRound, 2500)`. `close()` (`app/learn.js:77-84`) clears only the `setInterval` timer. It does not cancel this timeout and does not set `quiz = null`. `nextRound()` (`app/learn.js:193`) checks only `if (!quiz)`.
Failure scenarios:
- The user finds an object, then taps × and opens the Time machine in less than 2.5 s. The old timeout calls `showRound()`. The Time machine panel is replaced by "Find … Round 2", while the stars stay moved to the chosen year. No quiz tick runs, so the round cannot finish.
- The user taps Skip (`app/learn.js:179`) during the 2.5 s "Found it" message. `nextRound` runs two times, so one round is lost.
- The user starts a new quiz in less than 2.5 s. The old timeout skips round 1 of the new quiz.

**M2. No test covers about 650 new lines of logic.** The PR adds `app/learn.js` (318 lines), the time machine math in `app/realsky.js:75-160` (precession matrix, space motion, `poleStar`, `lineStars`), galaxy picking, `camPower` (`app/compass.js:121-137`), and the pred index check. The only test changes are two stub additions (`pickAt`, `createRadialGradient`). These are not loosened tests. But no test fails if the precession sign, the radial-velocity term or the pole-star result breaks. The PR body claims "Polaris today, Thuban in 2775 BCE, Vega in 14,026 CE". No test locks this claim. I checked the math by hand: the matrix `back·Rz(L)·toEcl` increases the ecliptic longitude, which is the correct sign, and `KMS_LY_YR = 3.3356e-6` is correct. A regression would ship silently.

### Low

- **L1. Quiz success style is never set.** `app/learn.js:189`: `$("quizMsg").classList.add("ok");` is inside the `//` comment at the end of the line, so it never runs.
- **L2. Canvas shadow on every frame.** `app/realsky.js:193` draws all constellation lines with `shadowBlur` 5-10 px on each frame. Canvas shadows are slow on phones. The PR stops the camera to save battery, but this shadow costs GPU time on every frame. It is not measured on a phone (#93).
- **L3. Camera restart loop on a phone is not verified.** `app/compass.js:133` calls `getUserMedia` again every 5 s while the photographs do not fully cover the view and the stream is stopped. If a browser asks for permission again on each call (some iOS versions do this), the user gets a prompt again and again. The PR body puts this under "Not verified" (#93).
- **L4. #98 does not close, and the precession model is simple.** `closingIssuesReferences` is `[95]` only. The body says "Closes #95 … and #98", but GitHub closes only the first reference. Also, `app/realsky.js:77-79` uses a constant 50.29″/yr rate and a fixed obliquity. The code comment marks this as a known limit ("good to a few degrees"). #98 suggests a long-period model. Decide if #98 is done, then close it by hand or keep it open.
- **L5. Target names go into `innerHTML` with no escape.** `renderTargets()` (old code) inserts `t.name`. `learn.js` `pointTo()` now adds names from galaxies, constellations and `Candidate ${c.id}` (from `data/survey/leaderboard.json`). All of these are first-party committed data, so the risk is low. It becomes a real risk if candidate IDs ever come from user input.

### Checked, no finding

- Esc and swipe-down hide sheets directly. The Done handlers of all four sheets (`north`, `details`, `webb`, `info`) only set `hidden = true`, so no cleanup is skipped.
- `learn.js` is in the service worker `SHELL`. Script order: both modules are deferred and `compass.js` has no top-level await, so `window.WanderersCompass` exists before `learn.js` runs.
- `learn.js` panel HTML escapes every data string with `esc()`. The hover name and the sky card use `textContent`.
- Time machine async races: `setYears` checks `R.years !== years` after the `await`. `open()` and `startNear()` check `mode` after their `await`.

---

## PR #103: Sky Compass stars from NASA HEASARC Hipparcos

Pinned SHA: `ece4f42e54bc80912a9bd9db1c4d3ca15b4d6cdf`. Verdict: **PASS**.
Closing issue: #90.

### Acceptance criteria (#90)

| Criterion | Status | Evidence |
|---|---|---|
| Keep HYG for names, HIP keys, distances, constellations | Met | `pipeline/make_sky_stars.py:69-80` still takes `con`, `dist_pc`, `name`, `key` from `stars/index.json`. |
| Position, V mag and spectral letter from HEASARC Hipparcos | Met | `hipparcos()` at `pipeline/make_sky_stars.py:34-50`; the override at lines 59-63. |
| Proper motion J1991.25 to J2000, `pm_ra` includes cos(dec) | Met | Lines 43-45. The Sirius assert at line 78-79 checks the result. The tolerance is 0.002° (7.2″), less than the Sirius shift of 10.7″ without proper motion, so a missing epoch step stops the build. |
| The drawn sky and the tap links stay the same | Met | I checked this myself: 8,920 stars before and after, the same key set, 0 V mag changes, 0 letter changes. |
| Source line changed | Met | `app/skyview.js:72`, `app/explorer-learn.js:122`, `meta.source` in `skystars.json`. |

My recomputation of the position shift against `app/data/stars/index.json`: worst 16.8″ (Toliman), 16.6″ (Rigil Kentaurus), 15.3″ (Beta Hydri), 15.2″ (Epsilon Indi), 12.2″ (Mu Cas). This agrees with `artifacts/nasa-stars/verify.md`.

### Medium

**M1. The test tolerance became 10 times wider, and no CI test locks the new behaviour.** `test/skyview.test.js:34-36` changed from 0.001° on raw RA/Dec to 0.01° (36″) on the sky angle.
- Why this is not an automatic FAIL: the old assertion said "positions equal HYG". This PR deliberately changes that contract. The new bound is about 2 times the measured worst case (16.8″). The new metric (angle on the sky) is more correct than raw RA near the poles.
- The gap: with 36″, the test does not detect the main risk of this change, a missing or wrong epoch step. Sirius without proper motion is off by only 10.7″. Only the pipeline assert (line 78) detects it, and CI never runs the pipeline. If a person edits `skystars.json` by another route, or removes the assert, CI stays green.

### Low

- **L1. The selection of stars is asymmetric.** HEASARC is queried for `vmag <= 7` (`pipeline/make_sky_stars.py:29`). A star with HYG mag ≤ 6.5 but Hipparcos V > 7 gets no Hipparcos row and keeps its HYG values. A star with Hipparcos V between 6.5 and 7 is dropped. Today this has no effect (the same 8,920 keys). It can change silently if HYG or HEASARC changes.
- **L2. Attribution is incomplete outside the compass.** The README data table (`README.md:688-702`) and the Eye description (`README.md:220`, "HYG via the star database") do not name NASA HEASARC or Hipparcos as the source of the drawn positions. The star sheet in `app/compass.html` and `app/app.js:48` still say "HYG v4.0". Licence: the Hipparcos catalogue (ESA SP-1200) is free to use with an acknowledgement, and HEASARC asks for a credit line. The UI credit "Hipparcos (ESA) via NASA HEASARC" meets the minimum. `skystars.json` still has HYG-derived names, so its CC BY-SA 4.0 share-alike still applies. The meta text keeps that licence.
- **L3. The build is not repeatable offline.** The star step now needs the network (the docstring says so). The HEASARC answer is not saved. A later rebuild can differ if HEASARC changes its table. The `OVERFLOW` check and the minimum row count (15,000) protect against a cut-short answer.

---

## PR #104: Deployment guide and script

Pinned SHA: `9cbe006e175d60dc1339b8bf9ed0e7626dc5f7d9`. Verdict: **PASS**.
No closing issue. Reviewed against the PR body.

### Deploy-script safety

| Question | Answer |
|---|---|
| Can it spend money? | No. `wrangler deploy` with `assets` only makes a static-asset Worker. Static asset requests are free on the Free and Paid plans. No paid add-on, domain or credit is created. |
| Can it `git push`? | No. `pages` runs `gh workflow run pages.yml --ref main` (`scripts/deploy.js:31`). This starts the reviewed workflow on `main`. It does not push code. |
| Does it ask before it acts? | No. See M2. |
| Shell injection | None. `shell: true` gets only fixed words (`scripts/deploy.js:18`). No user input reaches the command. |

### Medium

**M1. On the Cloudflare Worker, `.html` redirects break the offline compass and the installed app.** `wrangler.jsonc:5-9` keeps the default `html_handling`. So `/compass.html` answers `307 Location: /compass`. I checked this on the live site with `curl -I https://wanderer.johnyc.com/compass.html`. The service worker caches `compass.html` and `stories.html` (`app/sw.js:30`), and the PWA `start_url` is `compass.html` (`app/manifest.webmanifest:5`).
Failure scenario, offline:
1. A phone installs the app or opens `compass.html` one time with signal. At install time the worker stores the result of the redirect (a response with `redirected = true`) under the key `compass.html`.
2. Later, with no signal, the user opens the installed app (`start_url` = `compass.html`). `fresh()` fails on the network and returns the stored redirected response. The browser refuses a redirected response for a navigation ("a redirected response was used for a request whose redirect mode is not 'follow'"). The page does not open.
3. A visit to `/compass` is not in `SHELL`, so the worker does not cache it.

The `app/sw.js` header promises "each page opens with no signal after one visit". `docs/deploy.md:114` says new pages show at once, but it does not say that offline use fails on this host. GitHub Pages does not redirect, so this is specific to the Cloudflare method. The PR does not cause this on the current live Worker, but it makes this configuration the documented deploy path.

**M2. `cloudflare` publishes the local working tree to production, with no check and no prompt.** `scripts/deploy.js:36-46` checks only that 7 entry files exist. It does not check the branch, a clean tree, or that HEAD equals `origin/main`. Wrangler uploads every file in `app/`, including uncommitted edits and git-ignored files (for example `app/data/survey/tiles/*.json`, `app/data/survey/manifest.json` and `app/data/survey/.run.lock`, which `.gitignore` lists).
Failure scenario: an owner of the Cloudflare account runs `node scripts/deploy.js cloudflare` from a feature worktree. Unreviewed work then goes live on `wanderer.johnyc.com` at once. `docs/deploy.md:33` says "Deploy from `main` only", but nothing enforces it. GitHub Pages does not have this risk, because it builds from a checkout of `main`.

### Low

- **L1. Wrangler version is not pinned.** `scripts/deploy.js:45` runs `npx -y wrangler@4`. This installs the newest 4.x release with no prompt and no lockfile, and that release then holds the Cloudflare login token. The base pins every GitHub action to a commit SHA. An exact wrangler version would follow the same rule.
- **L2. GitHub Pages does not send the security headers.** GitHub Pages ignores `app/_headers` and serves it as a public file. So the Pages method has no `frame-ancestors`, `nosniff` or HSTS header from this file. This gap came with #92, not with this PR. But `docs/deploy.md` compares the two methods and does not say this.
- **L3. Wrong error message when `gh` has no default repository.** `scripts/deploy.js:25` runs `gh api repos/{owner}/{repo}/pages` with output hidden. In a clone with two remotes (fork and upstream) and no `gh repo set-default`, `gh` fails, and the script says "GitHub Pages is not on for this repository". The real cause is hidden.

### Checked, no finding

- `test/deploy.test.js` checks the real `app/`, a temp folder with one empty and one absent file, and that `ENTRY` is equal to the list in `pages.yml`. These are real assertions, not mocks. 3 of 3 pass in the merged tree.
- `.gitignore` adds `.wrangler/`. `wrangler.jsonc` has no secrets and no account ID.
- `run()` returns 127 on spawn error and 1 when a signal kills the process (`r.status ?? 1`).

---

## Debate round 1

This is the independent first pass. I did not read `artifacts/review-project_manager-*.md`.
Points for project_manager: #97 L4 (#98 done-state) and #104 M1 (documented "works offline" versus actual behaviour) are acceptance and honesty questions in your area.

## What I did not do

- I did not run `test/browser/realsky.mjs` or a real phone test.
- I did not run `pipeline/make_sky_stars.py`. It needs the network. I compiled it with `py_compile` and checked its output file.
- I created two temporary merge commits with `git commit-tree` to build the merged tree. They have no refs and change no branch.
