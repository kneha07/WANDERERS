# Review: tech_lead, telescope zoom phase 1, round 2

- Branch `feature/compass-telescope`, fixes `7058588..5fde083`.
- Read: the full diff of `app/compass.js`, `app/realsky.js`, `test/compass-flows.test.js`, `test/browser/realsky.mjs`, and all of `test/realsky-telescope.test.js` (new).
- Ran `node --test test/*.test.js`: 313 tests, 312 pass, 0 fail, 1 skipped. Confirmed.
- Browser check: not run again. Read `artifacts/real-sky/browser-checks.json` part 1g (12 rows, all ok, `compared` 2 on each row, worst 0 to 1 px). No app or test change after commit `eec5f8c` that wrote it.
- Ran one probe in the scratchpad (not committed): the real `realsky.js` with a fake Aladin that throws. Result below (N1).

## Verdict

**PASS.** H1 is fixed and has real tests at two levels. M1, M2, M3, L1, L2, L4 and L5 are fixed with tests. One new medium regression (N1) came in with architecture candidate 2. It is not a blocker, but fix it or name it in the PR.

## Round-1 findings

| Id | Status | Evidence |
|---|---|---|
| H1 thresholds in degrees | Fixed | `realsky.js:221-222`. Limits are now 0.25 px for the centre and the corner turn, and 1e-4 relative for the fov. Node test "at 150x and 300x ... small steps and a pinch" checks that a 0.003 deg step syncs, a 1e-6 deg step is skipped, and 300x to 280x syncs. With the old limits the step asserts fail (0.003 deg < 0.01 deg). Browser part 1g: worst 0.5 px at 150x, 1 px at 300x, 0.9 px after the pinch, `compared >= 1` asserted (`realsky.mjs:329`, `:335`). |
| M1 hold over a live camera | Fixed | `compass.js:49-50`, `:66`: hold needs `!S.camOn || cover() === 1` and lets go when cover drops. Test "hold mode is checked every frame ..." (`compass-flows.test.js:384`). |
| M2 Cancel puts a stale pose back | Fixed | `updateHold` calls `RealSky.cancelDrag()` before it sets `S.manual`, on entry and on exit (`compass.js:52`, `:66`). Tests on both sides: `compass-flows.test.js:399` and `realsky-telescope.test.js` "cancelDrag() ends a running Drag the sky". |
| M2-low grab drops sidereal turn | Open, low | `realsky.js:323` still sets `m.az = g.manual.az + A`. Not named in the spec. |
| M3 realsky.js untested | Fixed | `test/realsky-telescope.test.js` runs the real file with a fake page, clock, archive and Aladin. It covers `cover`, opacity, 2x/3x start, 30 s backoff, `retryAt` reset by Deep, 20 s timeout, late success, survey-switch timeout, note texts, hold branches in `follow`/`endDrag`. `selfTest` now returns `compared`. |
| L1 hold with no pose | Fixed | `compass.js:50` needs a pose. Test `compass-flows.test.js:425`. |
| L2 key keeps `snapped` | Fixed | `stopGlide` (`compass.js:68`). Test covers key and pointerdown. |
| L3 60 s gap | Open, low | Not changed, not named in the spec. |
| L4 hold only in setZoom | Fixed | `updateHold()` runs each frame (`compass.js:98`). Test: sensors start after the zoom. |
| L5 prefetch on mobile data | Fixed | 3x on `cellular` or `saveData` (`realsky.js:239`). Test for both and for wifi. |

## Late-success guard after 0cea7fd (start id removed)

Holds. `loadSurvey` races the work against a 20 s reject. After the timer wins, `await Promise.race` has settled, so the code after it in `startDeep` and `setSurvey` cannot run for that start. `Promise.race` keeps a handler on the slow promise, so its late rejection is not unhandled. A new start after the timeout cannot be overwritten by the old one, which is stronger than the id check. Test "a start that hangs for 20 s ... late answer changes nothing" asserts `state` idle and `aladins === 0` after release. The survey-switch variant is tested too.

## New findings

### N1 (medium): a failure after `loadSurvey` has no 30 s wait, so a start that throws retries every frame

- Where: `app/realsky.js:157-165` (catch in `startDeep`). Came in with `0cea7fd`.
- Before, `failDeep()` set `retryAt` for every failure in `startDeep`. Now only `loadSurvey` sets it (`realsky.js:144`). `A.aladin(...)` and `setBaseImageLayer(...)` run after `loadSurvey` and outside it.
- If `A.aladin` throws, the catch sets `state = "idle"` and leaves `retryAt` at 0. The next frame calls `startDeep()` again.
- Probe result (real `realsky.js`, fake Aladin that throws, zoom 5, 20 frames): `probes 20 aladins 20`, `retryAt` in the past. One archive probe and one new Aladin build per frame cycle.
- Realistic cause: Aladin Lite v3 needs WebGL2. A browser without it (old device, GPU blocklist, locked-down profile) fails in the constructor. In Deep the code falls back to Eye, but Eye from 2x still wants the photographs, so the loop goes on while zoomed in. Each try also adds Aladin DOM nodes to `#skyDeep`.
- Test gap: the fake Aladin in `test/realsky-telescope.test.js` never throws, so no test covers the backoff for this path. The round-1 guarantee "a failure while zoomed in does not retry every frame" is now true only for network failures.

### N2 (low): with the camera on, a survey switch while held drops the hold and re-centres on the phone

- `setSurvey` sets `DEEP.state = "loading"` (`realsky.js:198`), so `cover()` is 0 and `updateHold` lets go (`compass.js:66`). When the switch ends, hold starts again at the noisy phone pose, with a buzz, and `S.holds` grows, so the first-hold hint logic is not affected, but the user's dragged position is lost. The old photographs stay on screen during the switch, so the release is not needed for M1's reason.

### N3 (low): at 300x, sidereal tracking now syncs Aladin almost every frame

- 0.0042 deg/s x 3827 px/deg = 16 px/s, about 0.27 px per frame, just over the 0.25 px limit. This is the intended cost of H1. Not measured on a phone. Watch frame time in the device test.

## Operations and security

- No new hosts, `log: false` kept, no secrets, front-end only, revert is clean.

## Debate round 2

- The project_manager r2 file (`artifacts/review-project_manager-telescope-phase1-r2.md`) did not exist when I wrote this.
- Round-1 positions stand: PM-H1 (device test) is a done-state item that only a human can close. It is not a code defect.
- If the project_manager ranks N1 high, my position: it is medium. No data loss, no wrong picture, only on browsers without WebGL2. It is a real regression of a round-1 guarantee, so it must be fixed or named before merge.

## Path to merge (tech_lead seat)

- N1 fixed with a test where the fake Aladin throws, or named in the PR as a known leftover.
- N2, N3, L3 and the grab low named in the PR.
