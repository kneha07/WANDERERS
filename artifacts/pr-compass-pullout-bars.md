Sky Compass: the sky fills the screen. The bars hide until the user pulls them out, and more UX fixes.

## What changes

```
 ┌──────── 180° S ────────┐   heading tape (always on)
 │         ═════          │ ← top tab: tap or swipe down → readouts, buttons, sky bar
 │       Bunda            │ ← name of the star under the mouse / in the crosshair
 │     ✦     ◯     ✦      │
 │         ═════          │ ← bottom tab: tap or swipe up → radar, guide, search, targets
 └────────────────────────┘
```

- **Pull-out bars:** the top bar (telemetry, Sight check, Recalibrate, info, sky bar) and the bottom bar (guide, search, targets, radar) start hidden. A tab at each edge shows or hides its bar with a tap or a swipe. The bar state is kept for the next visit. On the first visit the tabs bounce, as a hint.
- **Hover and click:** a mouse over a star, planet, the Moon or a WANDERERS target shows its name. A click on a WANDERERS target now opens its sheet, the same as a click on a star.
- **Crosshair name:** the name of the star in the crosshair shows above it (stars only: the Moon, planets and targets have their own labels). On a phone, pointing works like hover.
- **Camera power:** the camera stops while the sky photographs cover it fully (Deep with the slider at Sky, or the telescope view). It starts again when they do not. The lens geometry is kept, so the view does not jump.
- **Screen stays on:** Screen Wake Lock while the sky is open.
- **Close sheets:** Esc closes an open sheet. A swipe down from the top of a sheet closes it.
- **Search pane:** a 🔎 button (bottom right) or the `/` key opens the live star search (`StarSearch.attach()`) under the compass tape, while the bars stay hidden.
- **Shining constellations:** the lines get a soft cyan glow that slowly brightens and dims (steady with reduced motion).
- **Galaxies:** 16 well-known galaxies (Andromeda, Triangulum, the Magellanic Clouds, Whirlpool, Sombrero, Centaurus A, M87 and more) draw at their true size and tilt, coloured by type. Hover or tap shows type, distance and size.
- **Webb frames:** violet diamonds, so they do not look like the amber target brackets.

## Verification

- Browser pane (375x812 and desktop): bars open and close with tap and swipe; hover names and click-to-open for a star (Bunda) and a target (Barnard's Star); crosshair name; Esc; remembered bars after a reload; first-visit hint.
- Camera power with a fake `getUserMedia`: Eye → live, Deep + full Sky → track ended, slider 60 % → live again.
- `node --test test/compass-*.test.js test/realsky-telescope.test.js test/survey-static.test.js test/theme.test.js`: 80 pass, 0 fail.

## Not verified

- A real phone: camera stop and restart, wake lock, swipe-down on sheets, tab gestures. Tracked in #93.

## Related

- #93: real-phone test list.
- #95: missing path prediction files (404), seen during testing; not changed here.
- Run record: `artifacts/compass-pullout-bars.md`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
