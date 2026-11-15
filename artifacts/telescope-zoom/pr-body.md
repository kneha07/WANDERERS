Phase 1 of `docs/specs/sky-compass-telescope.md`: zooming in the Sky Compass now feels like moving from the eye to a telescope.

**Status: phase 1 built and checked in a browser. The real-phone test is pending (#71).** Do not merge this as done until #71 passes, or until the owner waives the test in writing.

This branch also holds `feature/compass-pinch-zoom` (d938fb5: pinch to zoom and the daily survey check), which the telescope work needs.

## What changes

```
zoom 1x-3x     camera or drawn stars (as before)
zoom 3x-6x     cross-fade into DSS2 photographs, in every sky mode
zoom >= 8x     hold: the view stops following the phone and turns with the sky
               a target within 6 deg -> the view glides onto it (250 ms)
zoom < 6x      the view follows the phone again
1x button / Esc -> back to 1x in one step
```

- `app/compass.js`: zoom limit 300; hold mode with an 8x/6x gap; snap; sidereal tracking; `phoneSteers()`; arrow step divided by the zoom; 1x button and Escape; HELD marker; hint under the crosshair; grid hidden above 6x; dark edge on the crosshair.
- `app/realsky.js`: telescope fade and `cover()`; one survey loader with a 20 s limit and a 30 s wait after any failure; `syncDeep` skip limits in pixels; honest note text (survey name, archive photograph, approximate direction, offline); `selfTest().compared`.
- `app/compass.html`, `app/compass.css`: 1x button, HELD marker, hint pill, note pill.
- Spec: status, builder defaults for the open questions, and a "Built beyond the spec" list.

## Evidence

- `node --test test/*.test.js` on the branch before the merge of `main`: 317 tests, 316 pass, 0 fail, 1 skipped (it was skipped before this work).
- After merging `main`: 617 tests, 614 pass, 1 fail, 2 skipped. The failure is `test/classify-static.test.js` ("the shipped snapshot holds no invented votes"). It comes from `main` (a real vote in issue 70). #80 fixes it. This branch does not touch that test or the snapshot.
- `node test/browser/realsky.mjs`: 52 of 52 pass (record 6e42dbf). New part 1g: while the view moves at 150x and 300x, the photographs stay within 1.0 px of the drawn stars (limit 3 px; the old limits failed at 3.6 to 28.6 px). Every check compares at least 1 star. A held view stays still when the fed phone pose turns 3 deg.
- 42cc8a2 ("40 of 40 pass") was a regression run only. It is not telescope evidence.
- Screenshots: `artifacts/telescope-zoom/` (`eye-12x.png`, `final-40x.png`, `ux-*.png`).

## Review

- tech_lead: round 1 FAIL (alignment limits too coarse at high zoom), round 2 PASS.
- project_manager: round 1 FAIL, round 2 PASS for a PR on the condition "real-phone test pending #71".
- user_advocate: PASS; medium findings M1 to M4 fixed.
- Files: `artifacts/review-*-telescope-phase1*.md`. Architecture report: `artifacts/architecture/telescope-phase1.html`. Run record: `docs/wiki/wiki/synthesis/run-compass-telescope-2026-11-15.md`.

## Network use

The photographs start loading at 2x in every sky mode (at 3x on mobile data or Save-Data). Tiles are fetched only for the view on screen. There is no prefetch.

## Leftovers

- #71 real-phone test (pending; this PR does not close it).
- #77 deferred architecture candidates (the ladder as data, at the start of phase 2).
- #78 low review findings.
- Phases 2 (Pan-STARRS) and 3 (Hubble and Webb) are not started.

Part of #68 (this branch only; #68 also covers docs/project-explainer).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
