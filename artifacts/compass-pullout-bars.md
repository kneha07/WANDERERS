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
