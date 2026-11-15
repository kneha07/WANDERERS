## What this adds

The real sky behind the Sky Compass AR view, so clouds and city lights do not matter. It ports the real-sky work (two branches, built on the old radar compass) onto the AR compass from #33.

| View | Shows | Label on screen |
|---|---|---|
| **Eye** | stars a person can see (HYG via the star database), City / Suburb / Dark, constellation lines, planets | "Drawn from measured star positions… Not a photograph." |
| **Deep** | DSS2 survey photographs, or 2MASS with **Infrared**, under the AR view | "Survey photographs taken decades ago. Not a live view…" |

- **One projection.** Deep uses Aladin's `TAN`, which is the camera projection the AR view already draws in. Stars land on their photographs within 1.8 px (1° = 12.8 px), including a leaning phone (roll up to 26°).
- **Taps.** A star opens the existing star sheet (found by its star-database key). A planet, the Moon or the Sun gets a small card.
- **Drag the sky** (in the Sight check sheet). The sky point under the finger stays under the finger; Done sets the sight-check offsets, like a sight check.
- **Offline.** `sw.js` keeps the page, so it opens with no signal after one visit. Recent sky pictures stay 7 days (40 MB cap). "Save the sky for a place" (ⓘ sheet) keeps them for a latitude.

## Changes a reviewer must know

1. `compass.js` now loads `intro.js` on demand. `intro.js` imports three.js from a CDN; with the static import, a CDN failure stopped the whole page.
2. Aladin Lite now starts with `log: false` in `app.js` and `telescope.js` too. By default it sends the page's full address to a CDS server.
3. Eye reads a new `app/data/skystars.json` (`pipeline/make_sky_stars.py`). Main's `app/data/stars.json` is not changed.
4. `compass.js` accepts `?at=`, `?lat=&lon=`, `?go=1`, `?intro=skip`, `?cam=0`, `?debug=1` for the checks.
5. Not ported: the old radar's zoom (+/−, pinch). The AR view has a fixed lens.

## Checks

| Command | Result |
|---|---|
| `node --test test/*.test.js` | 188 pass, 0 fail |
| `node test/browser/realsky.mjs` (headless Edge, needs the network) | 29 of 29 pass: `artifacts/real-sky/run.log`, screenshots in `artifacts/real-sky/` |

The browser check now starts Edge with `--disable-sync --disable-extensions`. Without them, Edge signed the fresh test profile in with the Windows account and synced the user's extensions into it.

## Not tested

- **No real phone was used.** Sensors were simulated by feeding orientation events. The camera blend slider, frame rate with Deep on, and Safari's storage of saved pictures are untested.
- Save: only Basic ran in the browser. Standard and Sharp did not. "Remove saved places" removes every place, not one.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
