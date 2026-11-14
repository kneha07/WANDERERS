# Project-manager review: WANDERERS "Explore any patch" live mode

- Reviewer seat: project_manager (independent; did not write this work).
- Repo: kneha07/WANDERERS, local `main`. Reviewed at `0def95a`; the round-2 record `9bb0981` landed during the review and is included.
- Range: `6a1b159..9bb0981`.
- Date: 2026-11-14, 15:20 PST.

## Verdict

**PASS.** No unresolved high finding. The 22:00 gate is met. Every required decision is met or deliberately deferred with a written reason. Nine medium findings and seven low findings remain. Most are about stale docs and work that is only on local `main`.

Counts: requirements 43 rows. MET 33, PARTIAL 10 (row 3.3 counts as PARTIAL: met locally, not on the remote), NOT MET 0. Findings: high 0, medium 9, low 7.

## Evidence that I checked myself

| Check | Result |
|---|---|
| `curl http://localhost:8000/api/frames?q=Barnard's Star` | 200; 6 frames; `difference` present; pm (-801.6, 10362.4) mas/yr; 3 notes (colour channels, saturated 6/6, no photometry 6/6) |
| `curl .../api/frames?q=08h55m10.831s -07d14m42.53s` | 200; 4 frames; `difference` present; `pm` null; `notes` empty |
| `curl -o /dev/null -w %{http_code} http://localhost:8000/explore/` | 200 |
| `git status -sb` after `git fetch` | `main...origin/main [ahead 20, behind 4]`; `?? background/planet-x-spherex.pdf` |
| `git worktree list` | `.worktrees/redesign` at `0def95a` (merged); `.worktrees/demo` at `f18c472` (before the redesign) |
| Screenshots read | `artifacts/ux-walk/redesign-barnard-1440.png`, `artifacts/ux-walk/redesign-kapteyn-realistic-1440.png` |
| Issues read | #2, #5, #6 (all comments), #9, #11, #18, #21; list of all issues |

I did not re-run pytest, node tests or the web build. I take those counts from the orchestrator (pytest 46, node 60/1 skip, web 24, build ok) and from `artifacts/ux-mechanics.md`.

## Requirements map

### 1. Challenge: Planet X and SPHEREx

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1.1 | Public web tool | PARTIAL | Static site is public (README.md:7). The live "any RA/Dec over time" mode runs only on a local machine (`docs/blink/README.md:137` "Cloud hosting later"). This follows the user's "local first" decision. No issue tracks the hosting decision. See M1. |
| 1.2 | User enters RA/Dec | MET | `docs/blink/README.md:93-96` (name, decimal, sexagesimal); live check with `08h55m10.831s -07d14m42.53s` returned 200 |
| 1.3 | SPHEREx images of the patch over time, like a little video | MET | Flipbook with play/step/2 per second and a time axis, `redesign-barnard-1440.png`; `web/src/viewer.tsx:41` |
| 1.4 | Moving objects stand out | MET | Ring + difference; round 1 Barnard "bright/dark pair" (`artifacts/target-tests/README.md:9`); Kapteyn measured 8.6" PA 128° vs predicted 8.5" PA 131° (`artifacts/target-tests/round-2.md:20`) |
| 1.5 | Test: Barnard's Star | MET | round-2.md:9 (6 frames, 6 centroids, 150 Gaia); screenshot shows ring, wing centroids, motion table |
| 1.6 | Test: Epsilon Indi B | MET | round-2.md:10 (5 frames, photometry 4) |
| 1.7 | Test: WISE 0855 by name | MET | round-2.md:11 (D6 stack, 3 centroids, photometry 0.31-0.86 mJy) |
| 1.8 | Test: WISE 0855 by the challenge coordinates (08h55m10.831s, -7d14m42.53s) | PARTIAL | Round 1 tested it (`artifacts/target-tests/README.md:12`). Round 2 does not (`round-2.md:7-14`). My live check: 200, 4 frames, `pm` null, `notes` empty. The UI does not say that these coordinates are from 2010 (`grep 2010 web/src/*.tsx` finds nothing). See M3. |
| 1.9 | Test: RW Aurigae | MET (with stated limit) | round-2.md:12; saturated surveys 2-3; decision "no wing-flux estimate" on #6 |
| 1.10 | Test: R Draconis | PARTIAL | round-2.md:13 (9 frames, all saturated). The round-1 FAIL is marked "Fixed" (round-2.md:29) but round 2 has no image of R Dra. `docs/demo-script.md:48` still says do not use R Dra. See M4. |
| 1.11 | Opt: easy updates with new data | PARTIAL | Live IRSA SIA query of DR1 + QR3 (`docs/blink/README.md:24`). The disk cache never expires (`backend/spherex.py:621-624`, key has no date). A cached patch does not get new surveys. The UI says "from the server cache" (`web/src/panels.tsx:177`). See M6. |
| 1.12 | Opt: 102 bands / per-detector stacking | MET | Detector select D1-D6 (`web/src/App.tsx:51-59`); brightness per detector (`web/src/panels.tsx:413-452`); 102-slice HiPS slider is in the missions page (README.md:30) |
| 1.13 | Opt: spectra | PARTIAL | Missions page has spectra for the 5 targets (README.md:20). The live mode has none. Not named as deferred in `docs/blink/README.md:136` ("Spectrum per pixel" is a next step - named). |
| 1.14 | Opt: add/subtract epochs | PARTIAL | Missions page: README.md:63-75. Live mode: last-minus-first difference only (`docs/blink/README.md:31`). |
| 1.15 | Opt: user-chosen field of view | MET | `web/src/App.tsx:684-689` (2-15'); URL `fov=` |
| 1.16 | Opt: Gaia overlay | MET | Gaia DR3 ghosts, `redesign-barnard-1440.png`; nearest-Gaia match on a mark (`artifacts/ux-mechanics.md:52`) |
| 1.17 | Opt: WISE overlay | PARTIAL | Live mode: WiseView link per candidate (`web/src/rail.tsx:164`); sky map has SPHEREx, 2MASS, DSS2 only (`web/src/SkyContext.tsx:10-13`). Missions page has WISE 2010 frames and AllWISE (README.md:15, 30). |
| 1.18 | Opt: coordinates in the URL | MET | `web/src/App.tsx:7` (`?q=&fov=&view=&det=&look=&c=`); browser check "mark survives a reload" (`artifacts/ux-mechanics.md:53`) |
| 1.19 | Opt: metadata such as contamination flags | MET | FLAGS mask (`docs/blink/README.md:29`); "Data quality" panel (`web/src/panels.tsx:143-165`); frames table with saturated column and notes |
| 1.20 | Opt: Astropy / Aladin | MET | `backend/requirements.txt:3` astropy 8.0.2; Aladin Lite 3.8.2 sky context (`web/src/SkyContext.tsx`) |

### 2. Decisions from the grilling (memory `challenge-choice.md`)

| # | Decision | Status | Evidence |
|---|---|---|---|
| 2.1 | Goal: a tool people keep using after the hackathon | PARTIAL | No hosting, no cache refresh, and no named maintainer in any repo doc (`git grep -i maintain` finds none). See M1, M6, M7. |
| 2.2 | Users: public + citizen scientists | MET | First-run tutorial, field guide with real examples, task rail (`web/src/rail.tsx:120-142`, `web/public/examples/`) |
| 2.3 | One page with a collapsed expert panel | MET | `<details className="expert">` (`web/src/App.tsx:678`); collapsed in `redesign-barnard-1440.png` |
| 2.4 | Local first | MET | `start.js`, `docs/blink/README.md:3-13` |
| 2.5 | FastAPI + astropy backend, React frontend | MET | `backend/requirements.txt:1,3`; `web/` Vite + React + TS |
| 2.6 | One stacked frame per survey | MET | Frames table, `redesign-barnard-1440.png` (6 epochs) |
| 2.7 | Per-detector frames in the expert panel | PARTIAL | Expert detector select gives a one-detector stack per epoch. The API's per-detector images (`r.detectors[*].png`) are decoded but never shown (`web/src/App.tsx:292`; no other use in `web/src`). See L1. |
| 2.8 | Difference image | MET | `difference` in my live check; Difference button in the screenshot |
| 2.9 | Proper-motion "where to look" ring | MET | Ring button; screenshot; round-2 Barnard offsets 0.5-2.9" |
| 2.10 | Share link | MET | "Copy share link" (`artifacts/ux-mechanics.md:54`) |
| 2.11 | SIMBAD / Gaia "is it known?" | MET | `web/src/rail.tsx:159-165`, buttons at `rail.tsx:251-258` |
| 2.12 | Backyard Worlds link | MET | `web/src/rail.tsx:11`, `rail.tsx:276` |
| 2.13 | No database | MET | Disk JSON cache only (`backend/spherex.py:50`) |
| 2.14 | MIT license | MET | `LICENSE:1`. The holder line says "the Field Shift team" (L5). |
| 2.15 | 22:00 gate: Barnard aligned blink + difference | MET | Round 1 PASS at 12:53 PST (`acdce86`, `artifacts/target-tests/README.md:9`, `sheet_barnard.png`); round 2 6/6 frames (`round-2.md:9`); my live check has `difference`. Met about 7 hours early. `docs/blink/README.md:135` still lists it as a next step (M5). |

### 3. Later requests

| # | Request | Status | Evidence |
|---|---|---|---|
| 3.1 | UX mechanics pass | MET | `artifacts/ux-mechanics.md` (stress walk 9/0, browser checks 23/0); manual items named as not tested (`ux-mechanics.md:100-101`) |
| 3.2 | ui-ux-pro-max visual pass | MET | `design-system/spherex-blink/MASTER.md`; pre-delivery checklist (`ux-mechanics.md:68-82`) |
| 3.3 | Integrate as "Explore any patch" of WANDERERS (#6): port 8001, `/explore/`, proxy, live link, no teammate flows deleted | PARTIAL (met locally, not on the remote) | `server.js:9-12,105,109-111`; `app/app.js:20,352-374`; `artifacts/ux-walk/wanderers-live-link.png`, `explore-live-server-down.png`. Local `main` is 20 commits ahead and 4 behind `origin/main`. See M2. |
| 3.4 | One-click boot script / button | MET (not re-run by me) | `start.js:3-6,116-135`, `start.cmd`, `start.command`; `docs/blink/README.md:3-13` |
| 3.5 | "NASA style, data rich, data driven", Backyard Worlds feel, not copied | MET | `MASTER.md` brand rule; footer "Not an official NASA product" (`web/src/App.tsx:805`); motion, brightness, frames table, data quality panels in the screenshot |
| 3.6 | "Google Earth style" animation of the angle between the user and the star | MET | Sky map fly 20' → 49° → 60° → 37° → 20' (`ux-mechanics.md:64`, `redesign-skymap-fly-1440.png`); "Your sky now" dome and side view with altitude (Barnard 46.3°, astropy 46.61°) |
| 3.7 | Image filters for a realistic star look | MET | `web/src/viewer.tsx:14,52`; honesty label in `redesign-kapteyn-realistic-1440.png` ("False-colour infrared · smoothed, with glow, for display · measurements use raw pixels") |
| 3.8 | Explore mode only; missions page restyle decided later | MET | Decision on #6 (3rd comment); `app/` style unchanged in this range except the live link |

### 4. Done-state questions from the brief

| Question | Answer |
|---|---|
| Known limits written down? | Mostly yes. #5 (scattered light, open), #21 (centroid pull, RGB shift, open), #18 (Windows on-demand fields, open), #9 (two on-demand features, open, no decision), #6 (decisions, open), #2 (challenge choice decided in a comment, still open), #10 (closed by `5e9a266`). Not tracked: public hosting (M1), cache freshness (M6), maintainer (M7). |
| Anything claimed done that is not? | Three overstated claims. `round-2.md:30` says the 2010-coordinates note is fixed; the chip note says only "(2026 position)" and typed coordinates get no note (M3). `round-2.md:29` says R Dra is fixed without a round-2 image (M4). `artifacts/ux-walk/stress-walk.md:13` points to a `checklist.md` that does not exist (L4). |
| Root README accurate for a new teammate? | No. See M8: stale limit, incomplete layout, POSIX-only setup, typo, no test list. |
| 5-target test re-recorded for round 2? | Yes, since `9bb0981` (`artifacts/target-tests/round-2.md`). It has gaps: no WISE 0855 coordinate query, all targets cached (no cold-call time), no images. It is local only, not pushed (M2). |
| 22:00 gate met? | Yes (row 2.15). |

## Findings

### High

None.

### Medium

- **M1. The "any patch" mode is not public.** The challenge asks for a public web tool (row 1.1). The live mode runs only locally. This follows the user's "local first" decision, so it is not hidden. But the only record is one line in `docs/blink/README.md:137`. No issue holds the hosting decision, its cost, or who approves it. Fix: open an issue "Public hosting for /explore/ (free tier, needs approval)" and say in the submission text that the live mode is local.
- **M2. The work is only on local `main`.** `main...origin/main [ahead 20, behind 4]`. The redesign, the round-2 record, the UX evidence and this review are not on the remote. Teammates' PR #22 (`4785b93`) is not merged in. The user rule says every review and report must be pushed. Fix: merge `origin/main`, re-run the checks, push.
- **M3. Challenge coordinates for WISE 0855 are not re-tested, and the UI gives no epoch hint.** Round 2 skips the exact coordinates that the challenge names. The live answer has `pm` null and empty `notes`. The object sits about 20 px west of center with no ring and no text that explains why. `round-2.md:30` says "Fixed: the chip note says so", but the chip note (`web/src/App.tsx:47`) says only "D6 stack (2026 position)". Fix: add the coordinate row to round 2, and either a note when a typed position matches a known high-motion object, or downgrade the claim.
- **M4. R Draconis "fixed" without round-2 evidence.** `round-2.md:29` marks the round-1 FAIL as fixed. There is no round-2 contact sheet or screenshot of R Dra. `docs/demo-script.md:48` still says the fix is in progress. Fix: add one R Dra screenshot from the merged stack, and update the demo script.
- **M5. Docs describe an older state.** `docs/demo-script.md:3` says the redesign is "in progress on branch feat/explore-redesign". `docs/demo-script.md:28` sends the demo to `.worktrees/demo`, which is detached at `f18c472`, before the redesign. A demo that follows the script shows the old UI. `docs/blink/README.md:133-136` lists the 22:00 gate and the Gaia overlay as next steps, but both are done. `artifacts/ux-mechanics.md:3,8-9` records branch `feat/explore-redesign` on ports 5183/8011, not the merged stack. Fix: update the three docs; move `.worktrees/demo` to the current good commit.
- **M6. The cache never refreshes.** The cache key has no date (`backend/spherex.py:621`). A patch that was built once never gets new SPHEREx surveys. This conflicts with "easy updates with new data" and with "a tool people keep using". It is not in "Known limits" (`docs/blink/README.md:113-127`). Fix: name it as a limit, or add a maximum age.
- **M7. No named maintainer.** The grilling decided "a named team member maintains the tool afterwards". No repo doc names one. Fix: one line in README.
- **M8. The root README misleads a new teammate.** `README.md:145` says new coordinates need `pipeline/fetch.py`, which the live mode and on-demand fields contradict. `README.md:147-154` repo layout omits `backend/`, `web/`, `start.js`, `fields.js`, `docs/blink/`, `test/`, `tests/`, `design-system/`. `README.md:50` setup is POSIX-only (Windows path is in `docs/blink/README.md` and #18). `README.md:101` has a typo, `python .venv/bin/python`. There is no list of all test commands (#11, open). The "Explore any patch" section (`README.md:117-123`) is accurate.
- **M9. The challenge text is not committed.** `background/planet-x-spherex.pdf` is untracked. Remote agents and teammates cannot see the source of the acceptance criteria. #2 is decided in a comment but still open. Fix: commit the PDF, close #2.

### Low

- **L1.** Per-detector images from the API are decoded but never shown (`web/src/App.tsx:292`). Either show them in the expert panel or stop sending and decoding them.
- **L2.** Round 2 has only cached timings (`round-2.md:16`). Round 1 had one cold call (25.8 s). The demo depends on a warm cache, which `docs/demo-script.md:44-46` says.
- **L3.** Barnard's Star shows 150 Gaia ghosts, busy at phone size. It is named in `round-2.md:37`.
- **L4.** `artifacts/ux-walk/stress-walk.md:13` refers to `checklist.md`, which does not exist. The checklist is section 3 of `artifacts/ux-mechanics.md`.
- **L5.** `LICENSE:3` names "the Field Shift team". The README does not say the license.
- **L6.** The memory index says "README still Field Shift (issue #2)". The README is now WANDERERS. The memory is stale.
- **L7.** Tidy rule: `.worktrees/redesign` is at `0def95a`, which is merged into `main`. Remove it (`git worktree remove`).

## Trade-offs and deferrals

| Deferred | Where it is named |
|---|---|
| Public hosting of the live mode | `docs/blink/README.md:137` only (M1) |
| Flux from saturated wings (RW Aur, Barnard, R Dra) | #6 comment; `ux-mechanics.md:88-92`; `round-2.md:35` |
| Scattered light D1/D2 | #5 |
| Centroid pull, RGB channel fill | #21; API notes |
| Missions page restyle | #6 |
| Windows on-demand fields | #18 |
| Which on-demand feature stays | #9 (no decision) |
| Spectrum, add/subtract, WISE overlay in the live mode | partly in `docs/blink/README.md:136`; add/subtract and WISE not named |

## Risk surface

- Demo risk: the demo script points to a pre-redesign build (M5) and IRSA can answer 502 on a cold call (L2). The cache mitigates the second.
- Team risk: the work is not on the remote (M2). A teammate who pulls sees none of it.
- Honesty risk: low. Every non-raw look has a label, saturated frames say so, and candidates are "never discoveries".

## Tech-lead cross-check

`artifacts/review-tech_lead-explore-live.md` did not exist when this review was finished. No agreement or disagreement is recorded.
