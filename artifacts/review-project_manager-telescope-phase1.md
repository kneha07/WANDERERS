# Review: project_manager, telescope zoom phase 1

- Branch: `feature/compass-telescope`, diff `33272f0..7058588`, plus verify record `798dcdc`.
- Spec: `docs/specs/sky-compass-telescope.md`, Phases row 1, sections 1, 2 and 5.
- Round 1 (independent). No tech_lead artifact existed when I wrote this.

## Verdict

**FAIL as "done".** The code for phase 1 is complete and the node tests are real.
Two required done-when items are not met: the device test and one browser check.
The spec still says "design only, nothing built".

## What I ran

- `node --test test/*.test.js`: 297 tests, 296 pass, 0 fail, 1 skipped. Confirmed.
- I read the full code diff (`app/compass.js`, `app/realsky.js`, `app/compass.html`, `app/compass.css`,
  `test/compass-flows.test.js`) and `artifacts/telescope-zoom/verify.md`.
- `test/browser/realsky.mjs` is not in the diff. Its 40/40 run is a regression run only.
  The `browser-checks.json` diff holds only timing and date noise.

## Per-criterion map (Phases row 1)

| # | Criterion | State | Evidence |
|---|---|---|---|
| W1 | Zoom limit 300 | met | `app/compass.js` `ZOOM_MAX = 300`; test "zoom stops at 300x" in `test/compass-flows.test.js` |
| W2 | Finder fade, camera and Eye into DSS2 | met (code), partly checked | `realsky.js` `scope()`, `cover()`, `deepFrame()`; backdrop fade in `compass.js` `draw()`; star fade in `drawEye`. Browser: verify.md, 12x Eye, cover 1, opacity 1. Camera-on fade not checked anywhere. |
| W3 | Hold mode with snap | met | `compass.js` `updateHold()`, `pose()` uses `!S.hold`; `realsky.js` `follow()` and `endDrag` treat hold as no-sensor (section 2 rule) |
| W4 | Note and telemetry text | partial | Telemetry `HELD` tested (regex on `ZOOM</b> 8.0× HELD`). Note texts in `realsky.js` `note()` have no automated test. Only the 12x "Archive photograph, not live" text was seen, by hand (verify.md). The "approximate" and "No connection" texts are not verified. |
| W5 | Grid hidden above 6x | met | `compass.js` `if (S.zoom <= 6)`; test "above 6x the altitude rings ... horizon line stays" |
| D1 | Node: hold enters at 8x, leaves under 6x | met | test "hold mode: from 8x ... below 6x it follows again" (7.9, 8, 6.5, 5.9) |
| D2 | Node: drag works while held | met | test "one finger and the arrow keys move the held view" |
| D3 | Node: snap centres a locked target | met | test "a selected target within 6 deg ... (snap)" with R Draconis at 1 to 6 deg |
| D4 | Browser: Eye 12x, photographs show, `selfTest` within 3 px | partial | verify.md: 0 px at 12x on Capella, 2 stars. Manual run only. No committed check. The default view compared 0 stars (empty pass). Not repeatable by the next agent. |
| D5 | Browser: fed sensor poses, view does not move while held | **missing** | No browser run. Only the node fake (D1 test, `aimPhone` + `frame`). The spec asks for a browser check. |
| D6 | Real iPhone and real Android phone | **missing** | verify.md "Not verified". Agents cannot do this. |

## Section alignment

- Section 1: matches, with these forks:
  - Finder uses the user's `R.survey`. With 2MASS chosen, the telescope view is infrared, not DSS2.
    The note names the real survey, so this is honest. Low.
  - Photographs also fade in when the sky mode is Off. Declared extra. Low.
- Section 2: matches. Forks:
  - The hint "View held. Drag to move. ..." shows in `#skyNote` every time while held.
    The spec says one hint under the crosshair, the first time only. Low.
  - Roll levels on entering hold. The spec asked the builder to confirm this with the user.
    No record of that confirmation. Folded into M1.
- Section 5:
  - Archive and survey name: met at zoom >= 3 with photographs ready.
  - Approximate text: present, shown only with sensors, no sight check and no snap. Not tested.
  - No connection text: present (`navigator.onLine === false`). Not tested.
  - "No prefetch on mobile data": Aladin now starts at 2x in every sky mode, with opacity 0.
    It fetches tiles for the current view before the user sees them. This is the declared "preload at 2x" extra.
    It is the view being looked at, so I rank it low. Name it in the PR.

## Findings

### H1 (high): phase-1 done-when needs a real iPhone and Android test. Not done.

- Evidence: spec Phases row 1, "Tried on a real iPhone and a real Android phone"; verify.md "Not verified".
- Hold mode, snap and vibrate exist only for sensor phones. No sensor phone ran them.
- Action: leftover. Only a human can do it. Do not call phase 1 done, and do not merge as done,
  until a person runs it on both phones, or the user waives it in writing (PR or spec).
  Name it in the PR body and the user report.

### H2 (high): the browser check "fed sensor poses, view does not move while held" is missing. D4 is not repeatable.

- Evidence: `test/browser/realsky.mjs` not in the diff; verify.md says "has no telescope check yet".
- Action: fix now. It is cheap. In `test/browser/realsky.mjs`:
  1. Aim at Capella, Eye mode, `setZoom(12)`. Assert DEEP ready, `#skyDeep` opacity 1,
     `selfTest().stars.length >= 1` and `worst <= 3`.
  2. Feed sensor events through `window.__wanderers.F` (already a debug handle), zoom to 12,
     change the fed pose, draw frames, and assert `pose()` is unchanged.
  Then rerun and commit `browser-checks.json`.

### M1 (medium): the spec still says "design only, nothing built".

- Evidence: `docs/specs/sky-compass-telescope.md:3`.
- The three open questions were answered by the builder (hold automatic, no vignette,
  Pan-STARRS deferred). The roll decision was not confirmed with the user. None of this is in the spec.
- Action: fix now. Set Status to "phase 1 built, device test pending". Record the answers
  as builder defaults that wait for the user. List the extras.

### M2 (medium): section 5 honesty texts have no automated test.

- Section 5 says "These are requirements, not polish". Only one text was seen, by hand.
- Action: fix now, or name as leftover. A node test on `realsky.js` `note()` with a stub `C`
  (zoom 12, DEEP ready, sensors on, not frozen, not snapped, then offline) is a few lines.

### L1 (low): the hold hint shows always, in the note, not once under the crosshair. Name it or match the spec.

### L2 (low): Aladin starts at 2x in Eye and Off modes, so zooming now uses the network in every mode. Name it in the PR (section 5, mobile data).

### L3 (low): at 300x on a bright star the white crosshair is not visible (verify.md). For user_advocate.

### L4 (low): commit `42cc8a2` "browser checks record ... 40 of 40 pass" can be read as telescope evidence. It is a regression run only. Say so in the PR.

## Scope honesty

- No TODOs, no deleted tests, no mocked app behaviour in the diff. One test change raises the 8x stop to 300x. That is correct.
- Extras are declared by the orchestrator. Sidereal tracking is the one with real value at 300x. It has a good test (Capella within 0.01 deg after 10 minutes).
- The other extras are small: 1x button, Escape, 20 s timeout, 30 s backoff, glide, vibrate. No gold-plating concern.
- The done-state report (verify.md) is honest. It names the device test, the empty pass and the missing browser check. The gap is that the spec and commit messages do not repeat it.

## Leftovers versus fix now

```
fix now (agent)              leftover (human / later)
-------------------          ------------------------
H2 browser checks            H1 iPhone + Android test
M1 spec status + answers     roll-levelling confirmation (user)
M2 note-text node test       L3 crosshair contrast (user_advocate)
L1/L2/L4 named in PR
```
