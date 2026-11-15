# Telescope zoom phase 1: orchestrator verify record (2026-11-15)

Branch `feature/compass-telescope`, commits 5489620..7058588 (not pushed). Spec: `docs/specs/sky-compass-telescope.md`.

## Results

- `node --test test/*.test.js`: 297 tests, 296 pass, 0 fail, 1 skipped (skipped before this work).
  `node --test test/` does not run on Node 24. Use the glob.
- Headless browser (Playwright, 390x844), `compass.html?debug=1&go=1&intro=skip&cam=0&sky=eye&at=2026-11-15T06:00:00Z&lat=47.6&lon=-122.3`:
  - At 12x in Eye mode: DEEP `ready`, `cover()` 1, `#skyDeep` opacity 1. The note names DSS2 and says "Archive photograph, not live".
  - Registration with the view on Capella, `RealSky.selfTest()` worst offset: 0 px at 12x, 0.2 at 60x, 0.5 at 150x, 0.9 at 300x. Two stars compared each time. The limit is 3 px.
  - The default south view at 12x compared **0 stars**, so worst = 0 there is an empty pass. A check must assert `stars.length > 0`.
- Screenshots: `eye-12x.png`, `capella-300x.png`. At 300x on Capella the DSS2 field is saturated white. The white crosshair could not be seen on it; de00872 adds a dark edge.

## Not verified

- A real iPhone and a real Android phone. The spec asks for both in phase 1. Issue #71.
- Update after fix round 1: `test/browser/realsky.mjs` part 1g now checks the telescope view (52 of 52 pass). 42cc8a2 was a regression run only.

## Review

The review panel is running: tech_lead and project_manager first, then user_advocate. Its artifacts are `artifacts/review-*-telescope-phase1.md`.
