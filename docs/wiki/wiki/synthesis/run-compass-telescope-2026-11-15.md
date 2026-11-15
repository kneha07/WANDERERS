---
tags: [run-record, work-lite, sky-compass, telescope-zoom]
sources: [docs/specs/sky-compass-telescope.md, artifacts/telescope-zoom/verify.md, artifacts/architecture/telescope-phase1.html]
updated: 2026-11-15
---

# Run record: Sky Compass telescope zoom, phase 1, 2026-11-15

Fable wrote the design (`docs/specs/sky-compass-telescope.md`). Opus built phase 1 with plan-and-advance and then work-lite. The branch is `feature/compass-telescope`. It is not pushed and not merged. It needs `feature/compass-pinch-zoom`, which is not merged either.

```mermaid
flowchart LR
  Z[pinch / wheel / 1x button / Escape] --> SZ[setZoom: S.zoom 0.5..300]
  SZ --> H{updateHold every frame}
  H -->|>=8x, phone steers, cover=1 if camera| HELD[Held: pose = S.manual, sidereal tracking, snap glide]
  H -->|<6x| FOL[Follow the phone]
  SZ --> RS[RealSky.draw: t = clamp((z-3)/3)]
  RS --> L[loadSurvey: 20 s limit, 30 s wait after any failure]
  RS --> C[cover: backdrop and Eye stars fade, #skyDeep opacity]
  RS --> N[note: survey, archive photograph, approximate direction, offline]
```

## Goal

Zooming in the Sky Compass should feel like moving from the eye to a telescope. Phase 1: zoom to 300x, fade into DSS2 photographs from 3x to 6x, hold mode with snap, honest note text, grid hidden above 6x.

## Shipped

- `app/compass.js`: `ZOOM_MAX` 300; hold mode (enter at 8x or more, leave below 6x); snap to a target within 6° with a 250 ms glide; sidereal tracking of the manual pose at 8x or more; `phoneSteers()`; arrow step divided by the zoom; the `1×` button and Escape; HELD marker; hint under the crosshair on the first hold; grid hidden above 6x; dark edge on the crosshair.
- `app/realsky.js`: telescope fade in every sky mode; `cover()`; one `loadSurvey` with a 20 s limit and a 30 s wait after any failure; `syncDeep` skip limits in pixels; note texts; `cancelDrag()`; `selfTest().compared`; offline keeps the drawn stars in Eye and Off.
- `app/compass.html`, `app/compass.css`: the `1×` button, the HELD marker, the hint pill, the note pill.
- Tests: `test/compass-flows.test.js` (hold, snap, tracking, grid, 1x), new `test/realsky-telescope.test.js`, browser part 1g in `test/browser/realsky.mjs`.
- Docs: the spec status, builder defaults and the "Built beyond the spec" list.

## Verify

- `node --test test/*.test.js`: 317 tests, 316 pass, 0 fail, 1 skipped (it was skipped before this work). `node --test test/` does not run on Node 24.
- `node test/browser/realsky.mjs`: 52 of 52 pass (record 6e42dbf). Registration is within 1.0 px at 150x and 300x while the view moves (the limit is 3 px). The old fixed-degree limits failed at 3.6 to 28.6 px.
- Orchestrator headless check: 12x Eye shows DSS2; on Capella, `selfTest` worst is 0.9 px at 300x. A first check with 0 compared stars gave an empty pass. All telescope checks now need `compared >= 1`.

## Review

- Round 1: tech_lead FAIL (H1: `syncDeep` limits too coarse at high zoom), project_manager FAIL (no real-phone test; no telescope browser check). All findings fixed or named.
- Round 2: tech_lead PASS (new N1 fixed in 7ab790d), project_manager PASS for a PR with "real-phone test pending (#71)".
- user_advocate: PASS. M1 to M4 fixed (note pill, HELD and hint under the crosshair, one accuracy claim, offline keeps the drawn stars).
- Review files: `artifacts/review-*-telescope-phase1*.md`.

## Architecture

Report: `artifacts/architecture/telescope-phase1.html`. Built: candidate 2 (one survey loader), 3 (`phoneSteers()`), 5 (hold count in `updateHold`). **Top recommendation:** candidate 1, the ladder as data in `Hips.CONFIG.surveys`, as the first commit of phase 2. Deferred with candidates 4 and 6 in #77.

## Leftovers

- #71: real iPhone and Android test (only a human can do it). Do not merge as done before it passes or the user waives it.
- #77: deferred architecture candidates 1, 4, 6.
- #78: low findings (survey switch lets go of the hold; Aladin updates every frame at 300x; grab drops the turn; star disc at 300x; tape span; fade haze; Android back).
- #68: open the PR for this branch.
- Phases 2 (Pan-STARRS) and 3 (Hubble and Webb) are not started.
- Environment: worktrees made in WSL need `git worktree repair` before Windows git works. The Claude Browser pane pauses `requestAnimationFrame` while it is hidden, so use Playwright for this page.
