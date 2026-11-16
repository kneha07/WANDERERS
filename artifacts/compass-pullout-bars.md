# Run record: Sky Compass pull-out bars (2026-11-15)

Request: hide the top and bottom bars of the Sky Compass. Show them only when the user pulls them out.

## Change (commit d69c1ba)

- Top bar (telemetry, Sight check / Recalibrate / info, sky bar) and bottom bar (guide, search, targets, radar) start hidden.
- A grabber tab at each edge toggles its bar: tap, or swipe (down opens the top bar, up opens the bottom bar).
- The off-screen target arrow uses the larger clear area while a bar is hidden.
- Files: `app/compass.html`, `app/compass.css`, `app/compass.js`.

## Verification

- Browser pane at 375x812: tap and swipe open and close both bars; hidden bars have `visibility: hidden`; no console errors.
- `node --test test/compass-*.test.js test/realsky-telescope.test.js test/survey-static.test.js test/theme.test.js`: 80 pass, 0 fail.
- Not done: real-phone test.

## Open items

- https://github.com/kneha07/WANDERERS/issues/93: first-visit hint decision, and real-phone test.
- Branch not pushed (agents do not push).

## Follow-up: hover names and click to open (commit 988ceb5)

- A mouse over a star, planet, the Moon or a WANDERERS target shows its name next to the pointer. The cursor changes to a pointer.
- A click on a WANDERERS target (bracketed) now selects it and opens its sheet. A click on an Eye star already opened its sheet.
- Both go through `pickAt()` in `app/realsky.js`; `targetAt` and `onTarget` hooks come from `app/compass.js`.
- The hover check uses a 40 ms timer, not `requestAnimationFrame`: a hidden browser pane stops rAF.
- Verified with the real mouse in the browser pane: hover "Bunda" and "Barnard's Star", click opens both sheets. Tests: 80 pass.
- Touch phones have no hover. A tap opens the sheet, as before.
- Seen, not changed: `data/stars/pred/hip106786.json` (Bunda) is 404; the path view falls back. Tracked in https://github.com/kneha07/WANDERERS/issues/95.

## Follow-up: UX round 2 (2026-11-15)

Built (verified in the browser pane; tests 80 pass):

- Camera power: the camera stops when the photographs cover it fully (`RealSky.DEEP.op === 1`, ready), after 1.5 s. It restarts when they do not. Tested with a fake `getUserMedia`: Eye live, Deep + full Sky ended, slider 60 % live again. The last picture size is kept (`S.camSize`), so the lens geometry does not change.
- Crosshair name: `pickAt` at the screen center, every 250 ms, drawn above the reticle.
- Screen Wake Lock after the intro, taken again on `visibilitychange`.
- Esc closes open sheets (else back to 1x). A swipe down (> 90 px) from a sheet's top closes it.
- Webb frames: violet diamonds, not gold squares.
- First visit: the pull tabs bounce 3 times (`wanderers.barsSeen`). The bars' open state is kept in `wanderers.top-open` and `wanderers.bottom-open`.

Removed on user request: red night mode (built, then removed; the user did not like it).

Not tested: the real camera stop and restart, the wake lock and the swipe-down on a real phone (issue #93).

Assumption to confirm: the user asked to turn the camera off at "deep and move full z-score". This was read as Deep sky with the Camera/Sky slider at full Sky. The user was told and can correct it.

## Hand-off

- Pushed on user request and opened https://github.com/kneha07/WANDERERS/pull/97 (2026-11-15). Next: review and merge, then the real-phone test in #93.
- Codex review on #97 did not run: the Codex usage limit was reached (2026-11-15). A human review is needed; no automated findings exist.
- Crosshair name shows stars only (2026-11-15): the Moon, planets and targets already have labels, so the user saw "Moon" twice. Bars looked "not hiding" because a test left them open and the page remembers that state; reset in the browser pane.
- Search pane (2026-11-15): a 🔎 button (bottom right, hidden while the bottom bar is open) or the / key opens a live star search under the compass tape. It reuses StarSearch.attach() from app/search.js. Verified: typing "vega" lists Vega live, Enter selects it, Esc closes. Tests: 40 compass tests pass.
- Shining constellations and galaxies (2026-11-15): the constellation lines get a soft cyan glow that slowly brightens and dims (8 s; steady with reduced motion). 16 well-known galaxies (M31, M33, LMC, SMC, M51, M81, M82, M101, M104, NGC 5128, NGC 253, M87, M83, M63, M64, Milky Way centre) draw as glowing ellipses at their true size and tilt, coloured by type, with a dashed outline and name; in Deep only the outline. Hover or tap shows type, distance and size. Positions from the Messier / NGC catalogues, hard-coded in app/realsky.js (GALAXIES). Verified in the browser at M31 (Eye and Deep). Tests: 80 pass (test fakes gained pickAt and createRadialGradient).
- Learning modes and distances (2026-11-15): app/learn.js adds the 🎓 menu with Time machine (RealSky.setYears: linear Hipparcos proper motion from stars.json, lines follow their stars; verified Arcturus moves 6.30 deg in 10,000 years; Big Dipper shape visibly changes at +50k), Tonight's tour (5 stops by kind, verified: Andromeda Galaxy, Saturn, 61 Cygni, Vega, Cygnus) and Find it quiz (verified +10, +5 after hint). StarSearch.distanceLines(km) adds km, light time and Voyager 1 time to every card (verified Moon 404,173 km, Sun 148 million km, Jupiter 789 million km). learn.js added to the sw.js shell. Ceiling: straight-line star motion, no precession; noted in the panel. Full suite: 664 pass.
