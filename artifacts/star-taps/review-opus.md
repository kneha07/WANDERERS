# fix/star-taps: independent review (Opus) and fixes

Reviewed: `fix/star-taps` at cc7ebd7 against origin/main 4cfafed, read-only, 2026-11-16. Reviewer result: no crash or data bug; 2 defects, 3 risks, nits.

| # | Finding | Severity | Fix |
|---|---|---|---|
| 1 | `.guide` lost pointer events, but it is 92% opaque: a tap or hover on its text reached hidden sky objects; a drag on it moved the sky | risk | `.guide` keeps `pointer-events: auto` again. Only `.skybar` and `.hud-buttons` let taps through their empty parts. |
| 2 | `slicesInView` used `r / cos(dec)` for the RA half-width; near the poles (dec 75–79°, r 9–12°) a slice in view was missed | bug | New `SkyView.raSlices(ra, dec, r)` uses `asin(sin r / cos dec)`. A random-sampling unit test covers it (the old formula fails it). |
| 3 | Deep at 1x: `cover()` = 1, so all 24 slices (4 MB) loaded, and a 109k-star rebuild ran every second | risk | Deep slices load and count only when the view's half-diagonal is under 15° (`DEEP_R`). Measured: Deep at 1x fetches 0 files. |
| 4 | Ring positions were rebuilt once a second; at 300x they stepped about 16 px | risk | `starsInView` works out positions every frame from J2000 vectors, after a cheap cone test. |
| 5 | No offline copy of the slices; failing fetch every 30 s | risk | The service worker keeps `data/skydeep/*` cache-first (`pinned`); the URL has `?v=DEEP_V`. The fetch checks `r.ok`. |
| nit | CRLF writes on Windows | nit | `write_text(..., newline="\n")` |
| nit | Distance from any parallax > 1 mas (up to 3,229 ly from noise) | nit | Distance only when parallax > 5 × its error: 42,080 stars, largest 1,310 ly. |
| nit | Unversioned data URLs | nit | `?v=DEEP_V` |
| nit | No test for slice logic | nit | Test added. |

## Retest after the fixes

| Check | Result |
|---|---|
| `node --test test/*.test.js` | 679 pass, 0 fail |
| Guide text, desktop | takes the tap (`guideMain`), the top sky note lets it through |
| Deep at 1x | 0 deep files fetched, rings on naked-eye stars |
| Zoomed in | 2 slices fetched (ra02, ra03), rings on faint stars, one pick 3.3 ms |
| Real click on a ring (HIP 14460, V 8.5) | star sheet: F2V, 548 ly, nearest Webb frame; no console errors |
