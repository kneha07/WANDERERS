# Spec: real sky behind Sky Compass

Status: ready for implementation. Date: 2026-11-14. Base: `origin/main` at `35cb320`.
Files today: `app/compass.html`, `app/compass.js`, `app/compass.css`, `app/sky.js`.
Work in a new worktree `.worktrees/real-sky`, branch `feature/real-sky`, from `origin/main` (see the workspace `CLAUDE.md`).

## Goal

A person under clouds or city lights points the phone at the sky and sees the stars that are really in that direction. They choose between two views:

| View | Shows | Source | Honest label on screen |
|---|---|---|---|
| **Eye** (default) | What a human eye sees on a clear night: stars to a chosen faintness, the planets, Moon and Sun | Star catalogue and computed positions, drawn on the phone | "Drawn from measured star positions. Not a photograph." |
| **Deep** | Far more stars than an eye can see, plus the Milky Way and nebulae | Real survey photographs, loaded as tiles from the archive | "Survey photographs taken decades ago. Not a live view." |

Nothing is stored on our server. Deep tiles go from the archive straight to the phone and are kept there for a limited time.

## Two facts that shape the design

1. **A phone camera's live picture cannot show stars.** Under clouds it shows clouds, and under a clear dark sky it shows black. So the sky layer does not align star-for-star with camera pixels. The camera stays for what it is good at: the horizon, buildings, the Moon, and calibration.
2. **The radar is wider than the camera.** The radar circle shows 120° across. A phone camera shows about 50° by 65°, and the browser does not report the exact value. A pixel-exact overlay on the camera needs a per-phone zoom calibration. That is phase 2, not this spec.

So "merged with the camera" means **layered on one screen, with a blend slider**, in the radar's own projection.

## Layers (bottom to top)

1. `#cam` video, full screen (exists).
2. **Sky layer**, new, clipped to the radar circle and exactly the radar's size and position:
   - Deep view: a `<div id="skyDeep">` that holds Aladin Lite.
   - Eye view: drawn on the existing `#radar` canvas before the horizon line, so it needs no new element.
3. `#radar` canvas: horizon, N/E/S/W, named stars, targets, arrow (exists). Its dark fill `rgba(7,11,20,.55)` becomes fully transparent when Deep is on, and stays under the Eye stars.
4. Reticle, bars and sheets (exist).

Controls, in a new row under the top bar: a three-way switch **Off · Eye · Deep**, and a slider **Sky ↔ Camera** that sets the sky layer's opacity from 100% down to 20% (shown only when the camera is on). Eye view adds a second three-way switch **City · Suburb · Dark site**. Store every choice in `localStorage` with the existing `store`/`load` helpers (`wanderers.sky`, `wanderers.skyMix`, `wanderers.skyLimit`).

## One projection for everything

Today `project()` in `compass.js` is azimuthal equidistant (`r = d / FOV * R`). Aladin Lite 3.8.2 has no such projection; its bundle offers `TAN`, `STG`, `SIN`, `ZEA`, `FEYE`. Change the radar to **stereographic** (`STG`), in every view, so the canvas and the photographs always agree:

```
r(d) = R * tan(d / 2) / tan(FOV / 2)        // d = angle from the pointing direction, FOV = radius of the view in degrees
```

Replace the constant `FOV = 60` with `S.fov` (default 60, range 10 to 60) and add pinch-to-zoom and `+`/`−` keys. The ring circles, the horizon line, the drag scale (`120 / clientWidth` becomes `2 * S.fov / clientWidth`) and the off-screen arrow all use `r(d)`.

## Step 1. Inverse sky math in `sky.js`

Aladin needs the view centre in J2000 RA/Dec. `sky.js` only goes from RA/Dec to az/alt. Add, with the same style and the Node export:

- `Sky.unobserve(az, alt, date, lat, lon) → { ra, dec }` in J2000: remove refraction, invert `altAz`, invert `precess`.
- `Sky.zenithAngle(az, alt, date, lat, lon) → degrees`: the position angle, measured from celestial north through east, of the direction to the zenith at the pointed position. This is the rotation that puts "up" at the top.
- `Sky.planets(date) → [{ name, ra, dec, mag }]` for Mercury, Venus, Mars, Jupiter, Saturn, from JPL's "Approximate Positions of the Planets" Keplerian elements (valid 1800–2050), as geocentric RA/Dec of date. Magnitudes may be fixed typical values; they only set the dot size.

**Done when** a new `test/sky.test.js` passes with `node --test`:
- `unobserve(observe(star))` returns the star within 0.02° for all 16 named stars, at 3 dates and 3 latitudes (47.6, 0, −35), for altitudes above 5°.
- `Sky.planets` agrees with JPL Horizons within 0.1° for 3 dates between 2026 and 2030. Put the Horizons values and the query date in the test file as constants, with the URL in a comment.
- `zenithAngle` is 0° for a point due south on the meridian and 180° for a point between the pole and the zenith, in the northern hemisphere.

## Step 2. Eye view

**Data.** Add `pipeline/make_stars.py` (standard library only). It downloads the Yale Bright Star Catalogue (VizieR `V/50`, 9,110 stars) and writes `app/data/stars.json` as one array `[[ra_deg, dec_deg, vmag, b_v], ...]`, sorted bright to faint, RA/Dec to 3 decimals, magnitudes to 2. Use the mirror `https://vizier.cfa.harvard.edu/viz-bin/asu-tsv?-source=V/50/catalog&-out=RAJ2000,DEJ2000,Vmag,B-V&-out.max=unlimited` first and `vizier.cds.unistra.fr` second. (CDS was down during the hackathon; the CfA mirror answered.) Skip rows with no position. Commit the JSON; target size under 250 KB.

**Drawing.** In `draw()`, after the background fill and before the horizon:
- Limit: City 3.0, Suburb 4.5, Dark site 6.0 (visual magnitude). Because the array is sorted, stop at the first star fainter than the limit.
- Convert each star with `Sky.observe`, project, skip those outside the circle or below the horizon.
- Radius in canvas pixels: `max(1, 5.5 − 0.9 * vmag)`. Colour from B−V: below 0.0 `#b8ccff`, 0.0–0.6 `#ffffff`, 0.6–1.2 `#fff0c8`, above 1.2 `#ffc890`.
- Planets from `Sky.planets`: a filled dot of radius 6 with the name. Moon and Sun stay as they are.
- Cost: recompute star az/alt at most once per second (the sky turns 0.004° per second) into a cached array of unit vectors; per frame do only the dot products and the projection.

Proper motion is ignored: for stars this bright it is under 0.01° since 2000.

**Done when:** with the clock and place fixed (inject `now` and `loc` through a small seam in `compass.js`), the projected pixel of each of the 16 named stars equals the pixel of the same star found in `stars.json`, within 2 canvas pixels; and Dark site draws more stars than Suburb, which draws more than City, in a `node --test` case on the pure selection function.

## Step 3. Deep view

**Tiles.** HiPS (the tiled all-sky format the sky-map tab in `app/app.js` already uses). Verified on 2026-11-14:

| Fact | Value |
|---|---|
| Base URL | `https://irsa.ipac.caltech.edu/data/hips/CDS/DSS2/color` |
| Cross-site loading | `access-control-allow-origin: *` |
| Tiles | 512 px JPEG, orders 0 to 9, equatorial frame |
| Size | order 0 tile 54 KB, order 3 tile 33 KB; order 0 covers the whole sky in 12 tiles |
| Cache headers | `etag` and `last-modified` only, no `cache-control` |
| Credit (must be shown) | "Digitized Sky Survey – STScI/NASA, coloured and tiled by CDS, served by NASA/IPAC IRSA" |

Use IRSA as the primary host. `alasky.cds.unistra.fr` returned "Page unavailable" on the same day, so treat CDS as a fallback only.

At the default zoom one canvas pixel is about 0.11° to 0.17°, which is tile order 0 or 1. The whole visible sky is then 6 to 20 tiles, well under 1 MB. Higher orders load only when the user zooms in.

**Renderer.** Aladin Lite 3.8.2, the version `app/app.js` loads. Its script is 2.4 MB, so import it only the first time Deep is chosen, and show "Loading sky photographs…" until the first tile paints. Options: `projection: "STG"`, `cooFrame: "ICRSd"`, every control and the reticle off, no user pan or zoom inside Aladin (set `pointer-events: none` on `#skyDeep`; the radar keeps all gestures), black background.

**Sync, each animation frame:**
1. `c = Sky.unobserve(S.az, S.alt, now, lat, lon)` and `rot = Sky.zenithAngle(...)`.
2. Skip the update if the view moved less than 0.3° and rotated less than 0.5° since the last one sent.
3. `aladin.gotoRaDec(c.ra, c.dec)`, `aladin.setFoV(2 * S.fov)`, `aladin.setRotation(±rot)`.

The sign and zero point of `setRotation`, and whether `setFoV` means the full width in `STG`, are **not verified**. Settle both with the registration test below before any styling work.

**Done when**, on the page with the clock and place fixed:
- **Registration test** (Playwright or a page-level script): for each named star inside the circle, `aladin.world2pix(ra, dec)` and the radar's `project()` give the same point within 6 px on a 720 px radar (1°). Run it for 4 pointings: south at 30°, north at 60°, east at 10°, and the zenith.
- The Moon marker and Polaris sit on the right spots by eye in two screenshots saved to `artifacts/real-sky/`.
- With the network blocked for `irsa.ipac.caltech.edu`, Deep shows "Sky photographs are not reachable. Showing the Eye view." and falls back to Eye within 5 seconds.

## Step 4. Keep tiles on the phone, for a while

Add `app/sw.js` and register it from `compass.html` only. The site is served from a sub-path on GitHub Pages (`/wanderers/`), so register with a relative URL.

- Handle `fetch` only for URLs that start with the HiPS base URL. Let every other request pass through untouched, so a new deploy of the app is never served stale.
- Strategy: cache first, then network; store successful CORS responses in the cache `wanderers-sky-v1`.
- Limits: 40 MB or 1,200 entries, whichever comes first; delete the oldest entries first (`cache.keys()` is in insertion order). Delete the whole cache when it is older than 7 days (keep the creation time in a small `meta` entry).
- In the info sheet (`#info`), add a row "Saved sky: 12 MB, 310 pictures" with a **Clear** button. Read the numbers by messaging the service worker.
- Eye view needs no network after the first load: also cache `data/stars.json`, `data/index.json` and `data/declination.json` in the same worker, network first with a cache fallback.

**Done when:** load Deep, look around, go offline, reload: the same directions still show photographs; Clear empties the cache and the row reads "Saved sky: none"; a `node --test` case covers the eviction function (oldest first, both limits).

## Step 5. Honesty and failure states

- The view label from the table in **Goal** is always visible under the switch, in the `.small` style.
- Next to it, the pointing quality: "Direction good to about ±N°", where N is `webkitCompassAccuracy` on iOS, 3 after a star or landmark calibration, 10 otherwise. When N is 10, the text is a button that opens the calibration sheet.
- Add one calibration option to the sheet: **Drag the sky.** With Eye or Deep on, the user drags the sky until one thing they can see (the Moon, a planet, a bright star) sits where they see it; the drag sets `S.cal.dAz` and `S.cal.dAlt`, exactly as the existing "lock onto something real" step does.
- Deep view never shows the Moon, planets, aircraft or satellites in the photographs. The canvas markers for Moon, Sun and planets stay on top in both views.
- Below the horizon the sky layer is dimmed to 35%, so "under your feet" stays distinct.
- `prefers-reduced-motion`: no change needed, the layer follows the phone.

## Out of scope

- Pixel-exact overlay on the camera image (needs a per-phone field-of-view calibration).
- A photographic Eye view. A wide-angle all-sky photograph (Mellinger) would suit it, but its tiles could not be reached or checked on 2026-11-14.
- More Deep layers. IRSA also serves `CDS/2MASS/Color`, `CDS/AllWISE/RGB-W4-W2-W1` and `SPHEREx/spherex_allsky_cube` in the same format, so an "Infrared" choice is a small follow-up once this works.
- Constellation lines and star names beyond the 16 already drawn.

## Order of work and checks

Do the steps in order; each one ships alone. Before the pull request: `node --test test/*.test.js` passes, `node --check app/compass.js app/sw.js app/sky.js` passes, and the README's Sky Compass paragraph names the two views, the credit line and the 7-day cache. Test on one real Android phone and one iPhone if available; say in the pull request which were tested.
