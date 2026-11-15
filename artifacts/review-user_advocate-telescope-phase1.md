# Review: user_advocate, telescope zoom phase 1

- Branch: `feature/compass-telescope` at `bcc891f`. Diff `33272f0..HEAD`. Spec: `docs/specs/sky-compass-telescope.md`.
- Phase 1 settled: tech_lead PASS, project_manager PASS (r2). N1 (Aladin retry loop) is out of scope here.
- Live run: headless Playwright Chromium, 390x844, `http://localhost:8003/compass.html?debug=1&go=1&intro=skip&cam=0&sky=eye&at=2026-11-15T06:00:00Z&lat=47.6&lon=-122.3`.
- Screenshots: `artifacts/telescope-zoom/ux-*.png` (not committed).

## Verdict

**PASS.** No high finding. The job works: the user zooms from drawn stars into DSS2 photographs, the note names the
survey and says "Archive photograph, not live", and the `1×` button and Escape return to 1× in one step.
Four medium findings weaken how well the user understands what they see. Fix them before a public demo.

## What I did

```
Capella aim (Sky.observe -> S.manual), S.sensors = false
  1x -> 4x -> 6x -> 12x -> 60x -> 300x      screenshots ux-1x .. ux-300x
fed phone poses (F.feed), S.sensors = true
  10x (HELD) -> 5x -> 10x (second hold)      ux-held-10x
  wheel out 5 notches, wheel in 10 notches, Escape, 60x + click #zoomReset   ux-after-escape
offline (context.setOffline) at 200x         ux-offline-200x
stress-walk.mjs (minimal config)
```

| Step | Zoom | `#skyDeep` opacity | Note (start) | HELD |
|---|---|---|---|---|
| Eye | 1x | 0 | "Drawn from measured star positions ... Not a photograph." | - |
| Finder fade | 4x | 0.33 | "Telescope view: Digitized Sky Survey 2 (visible light). Archive photograph, not live." | - |
| Finder | 6x, 12x, 60x, 300x | 1 | same | - |
| Held (sensors) | 10x | 1 | + "Your compass is good to a few degrees..." + "View held. Drag to move. Pinch out..." + "Direction good to about ±10°" | `ZOOM 10× HELD` |
| Second hold | 10x | 1 | hint shortens to "View held." | yes |
| Wheel out | 0.82x | 0 | back to Eye text | no |
| Wheel in | 300x | 1 | Finder text | yes |
| Escape | 1x | 0 | Eye text, `#zoomReset` hidden | no |
| `#zoomReset` click from 60x | 1x | 0 | Eye text | no |
| Offline | 200x | 1 | + "No connection: no finer photographs." | - |

## Findings

### M1 (medium) Finder rung, 60x step: the note is not readable on top of the photographs

- `#skyNote`: 11.2 px, colour `rgb(79, 96, 121)`, no background, only a 2 px text shadow.
- Contrast on pure black is about 3.2:1 (WCAG AA for small text needs 4.5:1). On photographs it is lower.
- `ux-60x.png`: on the Capella glare the note is grey on white and cannot be read. `ux-12x.png` and `ux-held-10x.png`: readable only with effort.
- Impact: the honesty text (survey name, "archive photograph", "approximate") is a spec requirement (section 5). It is present in the DOM but not readable when it matters most.

### M2 (medium) Hold, 10x held step: the HELD state is hard to see

- The hint "View held. Drag to move. Pinch out to follow the phone again." is clause 3 of a 4-clause paragraph at the top, in the same small grey text (`ux-held-10x.png`). The spec (section 2) asks for one hint line **under the crosshair**.
- The only other sign is the word `HELD` in the telemetry line (`ZOOM 10× HELD`), same size and colour as LAT and LON.
- The one buzz helps on a phone, but a user who turns the phone and sees the view not move can think the app froze.

### M3 (medium) Hold, 10x held step: two different accuracy claims in one note

- Live note: "Your compass is good to a few degrees, so this is near where you point, not exactly it. · ... · Direction good to about ±10° Sight check".
- "A few degrees" and "±10°" in the same line conflict. The user cannot tell which is true. Source: `app/realsky.js:254` plus the existing direction clause.

### M4 (medium) Finder rung, offline 200x step: the view is empty and the text implies it is not

- `ux-offline-200x.png`: the screen is black. The drawn stars are faded out (Finder fade), and no photograph tiles load.
- The note says "No connection: no finer photographs." That implies coarse photographs show. Here there is nothing at all (this place was not saved).
- The user sees a black screen with a crosshair and has no clear reason. Zooming back below 3x brings the drawn stars back, but nothing says so.

### L1 (low) Finder rung, 300x step on Capella: a blank grey field

- `ux-300x.png`: the whole view is the saturated star disc, flat grey-white. The "Capella" label is pale blue on white and almost invisible.
- Nothing tells the user that this is the star itself, not a failed load. The crosshair dark edge works: the crosshair is clearly visible (`de00872` confirmed live).

### L2 (low) All rungs above 6x: the gauges keep their 1x scale

- The compass tape always spans 90° and the tilt scale 50° (`app/compass.js:518`, `:544`). At 300x the view is about 0.1° wide.
- Constellation lines also stay drawn over the photographs. No line says how wide the view is. A user can read the 10° tilt ticks as the photograph scale.

### L3 (low) Finder fade, 4x step: the half fade looks like haze

- `ux-4x.png`: at opacity 0.33 the dark backdrop fades into a flat grey wash with few stars. It passes in one pinch, so the cost is small.

### L4 (low) Back on Android, any rung: system back leaves the page

- Escape and `#zoomReset` return to 1×. Zoom adds no history entry (`app/compass.js` uses only `replaceState`), so the Android back gesture at 300x leaves the compass instead of zooming out. Zoom is a mode, not a place, so this is acceptable. Note it for the #71 phone test.

## Questions from the brief

| Question | Answer |
|---|---|
| Does the user know what they see and from which telescope? | Yes in text (DSS2 named from 4x up). Weak in practice: M1. |
| Can they get back? | Yes. `1×` button (aria-label "Zoom back to 1×"), Escape, wheel, pinch. Android back: L4. |
| Is the note readable on the photographs? | No at 60x on a bright star: M1. |
| Does the crosshair show on a bright star? | Yes, at 12x, 60x and 300x. |
| Is HELD clear? | Partly: M2. |
| Is the text honest about archive photographs and approximate direction? | Yes in content. The accuracy claims conflict: M3. Offline text overstates: M4. |
| Is 300x confusing or cluttered? | Blank glare on Capella (L1). Gauges at the wrong scale (L2). Not cluttered otherwise. |

## Shneiderman

| Rule | Note |
|---|---|
| Consistency | Pinch, wheel and arrow keys all scale with zoom. The two accuracy phrasings break it (M3). |
| Shortcuts | Wheel, Escape and the `1×` button are good shortcuts. Ten wheel notches go from 0.8x to 300x. |
| Informative feedback | Zoom value in telemetry, survey in note. HELD and offline feedback are weak (M2, M4). |
| Closure | The `1×` button hides at 1x, so the user knows they are back. |
| Simple error handling | Offline text exists, but it does not explain the black view (M4). |
| Easy reversal | Yes: one tap or one key to 1x. Zooming out restores the user's mode (Eye stayed selected). |
| Internal locus of control | Auto-hold at 8x takes control from the user; the hint is the only explanation (M2). Accepted as builder default (spec question 2). |
| Short-term memory load | The note grows to 4 or 5 clauses at 10x held. Too much for one glance (M1, M2). |
| Clarity, hierarchy | The most important new state (held) has the lowest visual weight. |
| Accessibility | `#skyNote` has `aria-live="polite"`. Contrast below AA (M1). `#zoomReset` is a real button with a label. HELD is text, not colour only. |

## App UI mechanics (designing-ux-mechanics)

`stress-walk.mjs`, config: home = the compass URL above, one screen = info sheet (`#infoBtn`), no lists, no sends.
The telescope change has no navigation, no list and no send action, so most automated checks do not apply.

| # | Check | Target | Result | Detail |
|---|---|---|---|---|
| N2 | Back (system) reaches home within 2 presses | Info sheet | PASS | 0 press(es) |
| L1 | At most one layer over a screen | all walked steps | PASS | never more than one |

Manual checklist:

| # | Result | Reason |
|---|---|---|
| N1 | PASS | Zoom is a mode on one screen; Escape and `1×` return to the same view. |
| N2 | PASS | Script above. |
| N3 | NOT TESTED | No flow or form in this change. |
| N4 | NOT TESTED | No deep link to a zoom level. |
| N5 | NOT TESTED | No list. |
| N6 | PASS | Reload restores the page; zoom resets to 1x, which is the safe start. |
| L1 | PASS | Script above. The Webb chip is not a layer. |
| L2 | PASS | Escape is ignored while a sheet is open (`app/compass.js:319`), so it closes the sheet first. |
| L3 | NOT TESTED | No new layer. |
| L4 | PASS | No confirm dialog added. |
| D1 | PASS | No empty state. Photographs fade over drawn stars. |
| D2 | NOT TESTED | Tiles are cached by `sw.js`; not part of this change. |
| D3 | NOT TESTED | "Loading telescope photographs…" did not show in my run (tiles were cached); I did not see a flash. |
| D4 | FAIL (medium, M4) | Offline the view is black and the note does not explain it. |
| D5 | FAIL (medium, M4) | Same step. |
| A1 | PASS | Wheel and `1×` change the view in the next frame. |
| A2 | NOT TESTED | No send action. |
| A3 to A6 | NOT TESTED | No send action. |
| M1 to M3 | NOT TESTED | No list or navigation. |
| M4 | NOT TESTED | Snap glide (250 ms) not walked live. |
| M5 | NOT TESTED | Reduced motion not emulated. |

No FAIL on N2, N3, L1, D1 or A2.

## Not tested

- A real phone (issue #71). The jitter, the buzz and the real pinch feel need a person.
- Snap to a locked target in a live run (covered by Node tests only).
- The camera-on path (`cam=0` in all my runs).
- The bottom sheet said "No motion sensors here" while I fed poses. This is a side effect of forcing `S.sensors` in the test, not a finding.
