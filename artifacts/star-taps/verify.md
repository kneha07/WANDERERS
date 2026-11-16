# Sky Compass star taps: verify record

Issue: kneha07/WANDERERS#113. Branch: `fix/star-taps` (from origin/main 4cfafed). Date: 2026-11-16.

## Problem

Preset targets and searched stars opened a card, but most stars the user saw did not. Two causes:

1. Page boxes took the tap. `.skybar`, `.hud-buttons` and `.guide` had `pointer-events: auto` on the whole box, also on their empty and text parts.
2. Zoomed in or in Deep, the survey photograph replaces the drawn dots. Only the naked-eye list (V <= 6.5) could be picked, so almost every star in the photograph had no card, and nothing showed which stars could be tapped.

## Change

```
compass.css   container: pointer-events none  →  only buttons, links, inputs, lists, the target row and the radar take taps
pipeline      make_sky_stars.py --deep  →  app/data/skydeep/ra00..ra23.json  (NASA HEASARC Hipparcos, V > 6.5, 109,085 stars, 4 MB)
realsky.js    cover() > 0  →  load the RA slices in view  →  faint rings on the 300 brightest tappable stars
              tap  →  naked-eye star first  →  else the brightest deep star within 18 px  →  the same star sheet
compass.js    onStar fallback passes mag, spectral type and distance, so the sheet describes a star it has no record of
```

- The deep stars are not used in the time machine (they have no motion in the file).
- A slice that fails to load waits 30 s before the next try.
- Why a static file and not a live lookup: HEASARC, IRSA and SIMBAD answer with no CORS header (the browser blocks them), and VizieR timed out. The live site is a static Worker with no proxy.

## Evidence

| Check | Before | After |
|---|---|---|
| Star tap spots blocked by a box, desktop, both bars open | 36% | 6% (only real controls) |
| Same, phone 375x812, both bars open | 44% | 25% (only real controls: Webb button, search box, mode buttons, radar) |
| Controls still reachable (Deep, City, lines, Sight check, info, search, target card, pull tab) | yes | yes |
| Tap spots on a zoomed photograph (16 px grid, 1024x768) | 13 | 756 (743 deep stars) |
| Real click on a ring (HIP 15127, V 7.4) | no card | star sheet: K0III giant, 796 ly, nearest Webb frame |
| One `pickAt` call while zoomed | | 2.1 ms |
| Console errors | | none |
| `node --test test/*.test.js` | | 678 pass, 0 fail (new test: the 24 deep slices) |

## Not done

- `test/browser/realsky.mjs` was not run locally (needs Edge through WSL). CI runs it.
- The star sheet shows "No motion is known" for deep stars: the deep files carry no proper motion. Add pm_ra / pm_dec to the rows if the path view is wanted for them.
- The star sheet footer still says "Star data: HYG database v4.0". The text is a translation key in 6 language files, so it is unchanged.
- Not tested on a real phone with touch.
