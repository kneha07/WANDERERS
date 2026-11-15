# Review: tech_lead, telescope zoom phase 1

- Branch `feature/compass-telescope`, diff `33272f0..7058588`.
- Files read in full: `app/compass.js`, `app/realsky.js`, `app/compass.html`, `app/compass.css`, `test/compass-flows.test.js` (diff), plus the unchanged context in `realsky.js` (`syncDeep`, `setSurvey`, `follow`, `startDrag`, `endDrag`, `selfTest`, gesture wiring).
- Ran `node --test test/*.test.js`: 297 tests, 296 pass, 0 fail, 1 skipped. Confirmed.

## Verdict

**FAIL.** One high finding (H1): the photographs drift off the canvas at high zoom. The cause is fixed-degree thresholds in `syncDeep` that were safe at 8x and are not safe at 300x. The rest of the logic is sound.

## What I checked and found correct

| Area | Result | Where |
|---|---|---|
| Hold hysteresis | Enter at `>= 8` only when `S.sensors && !S.hold`. Leave at `< 6`. 6 to 8 keeps the state. All zoom changes go through `setZoom`. | `compass.js:253`, `:264`, `:242-247` |
| Sidereal sign and rate | Rotation of `-360.9856 deg / 86400 s` about the pole `[0, cos lat, sin lat]`. Hand check: a star on the east horizon rises. The test compares with `Sky.observe` after 10 minutes (< 0.01 deg). | `compass.js:227-233`, test "sidereal tracking" |
| Fixed `?at=` time | `nowDate()` returns `FIXED_AT`, so `dt = 0` and no drift. The first frame has `trackAt = 0`, so it is skipped. | `compass.js:22`, `:228` |
| Pinch versus drag | A second finger clears `drag` and cancels the realsky grab. | `compass.js:281` |
| Incremental drag | Correct. It keeps tracking that occurs between two moves. | `compass.js:301-305` |
| Late success after timeout | `failDeep` bumps `DEEP.start`. The success path checks `id !== DEEP.start` before it touches `DEEP` or makes the Aladin instance. The catch path checks the id too. `finally` clears the timer. | `realsky.js:137`, `:141`, `:151-152`, `:155-157` |
| Backoff | `retryAt` blocks `startDeep` for 30 s. Choosing Deep clears it. | `realsky.js:136`, `:223` |
| State restore on zoom out | `scope`, `cover` and `deepFrame` read `R.sky`, `R.mix`, `R.survey` and never write them. | `realsky.js:189-200` |
| Per-frame DOM writes | `#skyDeep` is written only when the `DEEP.op` key changes. `#skyNote` only when the `NOTE` key changes. `setSky` resets `DEEP.op`, so the next frame writes again. | `realsky.js:199`, `:249-251`, `:226` |
| `follow()` and `endDrag(true)` in hold | Treat hold as no-sensor: they aim `S.manual` and do not freeze the compass. Matches spec section 2. | `realsky.js:310-311`, `:322` |
| Off / Eye / Deep at 1x | Off: box hidden, no drawing, note still updated. Deep: opacity `R.mix` with camera, 1 without, same as before. Eye: unchanged at `cover() = 0`. | `realsky.js:196-200`, `:205-213` |

## Findings

### H1 (high): Aladin sync thresholds are in fixed degrees, so the photographs misregister by up to 38 px at 300x

- Where: `app/realsky.js:181-183` (unchanged lines, but `ZOOM_MAX = 300` at `compass.js:241` makes them wrong).
- `syncDeep` skips the update when the centre moved < 0.01 deg, the fov changed < 0.01 deg, and the rotation < 0.05 deg.
- Without a camera the scale is 12.76 px per deg per 1x zoom. Measured with `node`:

```
zoom   px/deg   0.01 deg in px   full fov
  12      153        1.5          2.547 deg
  60      765        7.7          0.510 deg
 150     1914       19.1          0.204 deg
 300     3827       38.3          0.102 deg
fov(280) - fov(300) = 0.0073 deg  (< 0.01: no update)
```

- Effect 1: the canvas (crosshair, targets, labels, snap target) and the photographs can disagree by up to 38 px at 300x and 19 px at 150x. The spec limit is 3 px.
- Effect 2: a pinch from 300x to 280x does not change the Aladin fov. The photographs stay at the 300x scale, about 14 px off at the screen edge.
- Effect 3: sidereal tracking moves the view 0.0042 deg/s. At 300x the photographs therefore stand still for about 2.4 s, then jump 38 px. The snap "lands on something real" in the canvas, but the photograph under it is off.
- Why the evidence missed it: the manual `selfTest` runs used a fixed `?at=` time and a static pose. The first frame after `setZoom` changes the fov by a lot, so Aladin got one exact sync, and nothing moved after it. 0.9 px at 300x is a best case, not a bound.
- Needed: thresholds relative to the current fov (or pixels), and a browser check that moves the pose by a sub-threshold step at 150x and 300x, then runs `selfTest`.

### M1 (medium): hold over a live camera with no photographs freezes the overlay over a moving picture

- Where: `compass.js:253-263`, `realsky.js:191`.
- With the camera on, the camera is covered only when `DEEP.state === "ready"`. When Aladin is loading, failed, or offline, `cover()` is 0 and the camera stays visible.
- At `>= 8x` the hold freezes `pose()`, but the camera picture still moves with the phone. The drawn stars, targets and crosshair then label the wrong things.
- The note says "View held", so it is not silent, but the overlay is still wrong. The offline case is a named scenario in spec section 5.

### M2 (medium): "Drag the sky" Cancel while held jumps the view to a stale pose

- Where: `realsky.js:315`, `:321`.
- `startDrag` stores `S.manual` at the time Drag the sky starts. On a phone that is not held, `S.manual` is stale (default `az 180, alt 25`, or the last held pose).
- If the user then zooms past 8x and taps Cancel, `endDrag(false)` copies that stale value into `S.manual`. The held view jumps away from the sky that was shown.
- Related, low: during a grab `follow()` sets `S.manual = g.manual + A` from the grab-start value (`realsky.js:311`). This drops the sidereal turn for the length of the grab (about 0.02 deg = 77 px for a 5 s grab at 300x).

### M3 (medium): the realsky.js half of the change has no automated test

- Where: `test/compass-flows.test.js:81` replaces `RealSky` with a stub (`cover: () => 0`).
- No test exercises `cover`, `deepFrame`, the 20 s timeout, the late success after the timeout, the 30 s backoff, the `retryAt` reset in `setSky`, the note honesty texts, or the hold branches in `follow`/`endDrag`.
- The race logic is correct by reading (see table), but nothing stops a regression.
- `selfTest` returns `worst: 0` when it compares no stars (`realsky.js:460`, `Math.max(0, ...[])`). Every check that uses it must also assert `stars.length >= 1`. The existing browser check does (`test/browser/realsky.mjs:171`). No telescope check exists.

### L1 (low): hold entry with no sensor pose keeps a stale `S.manual`

- `compass.js:253-255`. If `F.pointing()` is null and no snap applies, `S.manual` is not set. The view jumps to the old manual pose.

### L2 (low): any key cancels the snap glide but keeps `S.snapped = true`

- `compass.js:299`, `:310`. Shift, Tab or a screenshot key stops the glide halfway. The view is then not on the target, but `S.snapped` stays true, so the note hides the "approximate" warning (`realsky.js:239`).

### L3 (low): tracking skips gaps over 60 s

- `compass.js:229`. After a background tab or a lock screen the held view does not catch up with the sky. At 300x a 1 minute gap moves the star 0.25 deg, out of the 0.1 deg view. Name it.

### L4 (low): hold is checked only in `setZoom`

- `compass.js:246`. If the sensors start after the zoom is already `>= 8` (late permission), hold does not engage until the next zoom change.

### L5 (low): tiles are fetched at opacity 0 from 2x in every mode

- `realsky.js:195-200`. Declared extra. It works against spec section 5 "no prefetch on mobile data". Name it in the PR. Agree with project_manager L2.

## Operations and security

- No new hosts. `log: false` is kept on the Aladin start. No secrets. No destructive paths.
- Rollback: the change is front-end only. A revert restores the old behaviour. Cache-bust versions changed (`compass.html:17`, `:215-216`).

## Debate round 1 (project_manager artifact read)

| PM finding | My position |
|---|---|
| H1 device test missing | Concede as a done-state blocker for "phase 1 done". It is not a code-correctness defect. Only a human can close it. |
| H2 no browser check for hold and `selfTest` | Concede and widen. The check must also cover H1: move the pose by a sub-threshold step at 150x and 300x and assert `worst <= 3` with `stars.length >= 1`. A static check would pass with the current bug. |
| M1 spec status | Concede. Not my seat. |
| M2 note texts untested | Concede. Part of my M3. |
| L1 to L4 | Agree. |

My H1 is new evidence for the project_manager. It turns D4 ("registration within 3 px") from "partial" to "fails above about 24x" for any moving view.

## Path to PASS (tech_lead seat)

- H1 resolved and covered by a moving-pose browser check.
- M1 to M3 fixed or named as leftovers in the PR.
