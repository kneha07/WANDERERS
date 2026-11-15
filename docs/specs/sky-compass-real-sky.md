# Spec: real sky behind Sky Compass

Status: **built** (2026-11-15), on branch `feature/real-sky-main` from `origin/main` at `cf24fdd`. Read "Built, measured, and left to do" first: where it and the original text below disagree, it wins.

**Ported to the AR compass.** PR #33 replaced the radar page with a full-screen AR view (`orient.js` sensor fusion,
a camera projection). The real sky now lives in `app/realsky.js` and draws in that view's projection:

- The AR view is a camera (gnomonic, Aladin's `TAN`), not the radar's stereographic `STG`. Deep uses `TAN` with the full
  width `2·atan(W / 2f)` and `setRotation(−(zenithAngle − roll))`. Measured: worst offset 0.2 to 1.8 px (1° = 12.8 px) at
  five dragged views and four leaning phone poses (roll up to 26°). Objects under 5° altitude are left out of the check:
  refraction lifts the drawn stars there (0.5° at the horizon) and photographs cannot follow it.
- Eye reads `data/skystars.json` (`pipeline/make_sky_stars.py`); main's `data/stars.json` stays the search file. A tapped
  star opens main's own star sheet, found by its star-database key. Planets, Moon and Sun get a small card.
- "Drag the sky" sets main's sight-check offsets (`F.fineAz`, `F.fineAlt`) and freezes the compass, like a sight check.
  It solves on a modelled pose, because the fused sensors apply new offsets only at the next (smoothed) event.
- `compass.js` loads `intro.js` (three.js from a CDN) on demand, and `sw.js` keeps that pinned three.js. Before, a failed
  CDN stopped the whole page.
- Not ported: the radar's zoom (+/−, pinch); the AR view has a fixed lens.

Files: `app/realsky.js`, `app/skyview.js`, `app/hips.js`, `app/sw.js`, `app/sky.js`, `app/compass.html|js|css`.

## Built, measured, and left to do

Reference for the look: <https://spacetelescopelive.org/webb> shows survey photographs edge to edge behind its panels. It uses the same engine as this spec (Aladin Lite 3 with HiPS tiles: DSS2 colour and 2MASS colour from ESA's `cdn.skies.esac.esa.int`). So the sky here is **edge to edge across the whole stage**, not clipped to the radar circle as first written. The circle is now only a compass drawn over the sky.

| Step | State | Proof |
|---|---|---|
| 1. Inverse sky maths, planets | done | `test/sky.test.js`: round trip under 0.02°, planets within 0.1° of JPL Horizons |
| One projection for canvas and photographs | done: the AR view's camera projection (`TAN`) | registration check below |
| 2. Eye view, City / Suburb / Dark site, constellation lines, taps | done | `test/skyview.test.js`; `artifacts/real-sky/eye-phone.png` |
| 3. Deep view | done | `node test/browser/realsky.mjs`: worst offset 1.8 px (limit 3 px; 1° = 12.8 px) at nine views, roll up to 26°, on a phone-shaped screen |
| 4. Recent pictures kept by `app/sw.js` | done | browser check: a test hook in `sw.js` shortens the limits; trim keeps the 5 newest, the age rule drops the cache |
| 5. Save the sky for a place | done for one detail level (Basic) | browser check: 60 tiles saved, Deep then works with the archive unreachable |
| 6. Labels, pointing note, fallback to Eye, ground dimmed | done | browser check: fallback in about 1 s |
| 6. "Drag the sky" calibration | done | browser check, phone leaning 22°: the grabbed point moves 60.0, 40.0 px for a 60 × 40 px drag; Done sets the sight check |
| Infrared background (2MASS colour) | done | browser check: same registration limit as the visible survey; switching back needs no reload |

Measured facts that replace guesses in the text below:

- Edge can sign a new test profile in with the Windows account and sync the user's extensions into it. The browser check therefore starts Edge with `--disable-sync --disable-extensions`, drives only its `about:blank` tab, and stops if an extension opens a page.
- 2MASS colour tiles average 59 KB (DSS2: 38 KB); its `Norder3/Allsky.jpg` is 1.0 MB.
- `aladin.setRotation(−Sky.zenithAngle(...))`: the sign is minus. `aladin.setFoV` is the full width of Aladin's box.
- Aladin draws wide views from `Norder3/Allsky.jpg` (0.8 MB) and, on a 3× phone screen, order-0 tiles; closer views ask for orders 1 and 2. `Hips.plan` therefore lists the all-sky file plus every tile order from 0.
- `Sky.planets` returns J2000 RA/Dec (not "of date"); pass each planet to `Sky.observe` like a star.
- Pass `log: false` to `A.aladin`: by default it reports the page address to a CDS server. `app/app.js` (the sky-map tab) now passes it too.
- Aladin sets `position: relative` on its container; our rule needs `!important`.
- Second host for the same survey, used when IRSA does not answer and nothing is saved: `https://cdn.skies.esac.esa.int/DSSColor`.

Left to do, in order:

1. Test on a real Android phone and a real iPhone: sensors, camera blend slider, frame rate with Deep on, and whether Safari keeps the service worker's pictures. None of this can run in headless Edge.
2. ~~"Drag the sky" calibration (step 6).~~ Done: the drag grabs the sky point under the finger and solves for the pointing that keeps it there.
3. Save: check Standard and Sharp in the browser; make Remove work per place (today it removes every saved place).
4. ~~Exercise the service worker's trim and 7-day expiry in `test/browser/realsky.mjs`.~~ Done.
5. ~~An "Infrared" background (`CDS/2MASS/Color` at IRSA).~~ Done, with the ESA host as the second host. A save stores the background chosen under Deep.

## Goal

A person under clouds or city lights points the phone at the sky and sees the stars that are really in that direction. They choose between two views:

| View | Shows | Source | Honest label on screen |
|---|---|---|---|
| **Eye** (default) | What a human eye sees on a clear night: stars to a chosen faintness, the planets, Moon and Sun | Star catalogue and computed positions, drawn on the phone | "Drawn from measured star positions. Not a photograph." |
| **Deep** | Far more stars than an eye can see, plus the Milky Way and nebulae | Real survey photographs, loaded as tiles from the archive | "Survey photographs taken decades ago. Not a live view." |

Nothing is stored on our server. Deep tiles go from the archive straight to the phone and are kept there for a limited time. Before a trip, the user can also save the Deep sky for a place in advance (step 5).

## Two facts that shape the design

1. **A phone camera's live picture cannot show stars.** Under clouds it shows clouds, and under a clear dark sky it shows black. So the sky layer does not align star-for-star with camera pixels. The camera stays for what it is good at: the horizon, buildings, the Moon, and calibration.
2. **The radar is wider than the camera.** The radar circle shows 120° across. A phone camera shows about 50° by 65°, and the browser does not report the exact value. A pixel-exact overlay on the camera needs a per-phone zoom calibration. That is phase 2, not this spec.

So "merged with the camera" means **layered on one screen, with a blend slider**, in the radar's own projection. Both the camera and the sky fill the stage edge to edge.

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
- Strategy: look in the saved cache of step 5 (`wanderers-sky-saved-v1`), then in `wanderers-sky-v1`, then the network; store successful CORS responses from the network in `wanderers-sky-v1`.
- Limits for `wanderers-sky-v1` only: 40 MB or 1,200 entries, whichever comes first; delete the oldest entries first (`cache.keys()` is in insertion order). Delete the whole cache when it is older than 7 days (keep the creation time in a small `meta` entry).
- In the info sheet (`#info`), add a row "Saved sky: 12 MB, 310 pictures" with a **Clear** button. Read the numbers by messaging the service worker.
- Eye view needs no network after the first load: also cache `data/stars.json`, `data/index.json` and `data/declination.json` in the same worker, network first with a cache fallback.

**Done when:** load Deep, look around, go offline, reload: the same directions still show photographs; Clear empties the cache and the row reads "Saved sky: none"; a `node --test` case covers the eviction function (oldest first, both limits).

## Step 5. Save the sky for a place, in advance

For a trip to somewhere with poor signal. The user saves the Deep photographs at home, then uses them at the place with no network.

**What a place needs.** Which stars can ever be seen depends only on the latitude of the place. Longitude and date change *when* a star is up, not *whether*. So a saved sky is a band of declination, and it works on any night:

```
latitude φ ≥ 0:  declination from φ − 90 to +90        latitude φ < 0:  declination from −90 to φ + 90
share of the whole sky = (1 + cos φ) / 2                 Seattle (47.6°): 84%      equator: 100%
```

Say this on screen in one line: "Saved for latitude 48° N. It also works anywhere near this latitude, on any night."

**Sizes.** Measured on 2026-11-14 from samples of 8 tiles per order (whole sky; multiply by the share above):

| Choice | Tile orders | Tiles, whole sky | Size, whole sky | Stays sharp for |
|---|---|---|---|---|
| Basic | 0–1 | 60 | about 2.5 MB | the default 120° view, down to about 40° |
| Standard (default) | 0–2 | 252 | about 9.5 MB | the closest zoom (20°) on a 720 px radar |
| Sharp | 0–3 | 1,020 | about 38 MB | the closest zoom on the sharpest screens |

**Which tiles.** A HiPS tile at order `k` is HEALPix pixel `n` in the NESTED scheme with `nside = 2^k`, at `Norder{k}/Dir{floor(n/10000)*10000}/Npix{n}.jpg`. Add a small pure module `app/hips.js` (browser global `Hips`, plus the Node export, like `sky.js`):

- `Hips.pixel(order, ra, dec) → n` (HEALPix `ang2pix`, nested) and `Hips.centre(order, n) → { ra, dec }` (`pix2ang`).
  One tile pixel covers `58.6° / (512 · 2^k)`, which is where the "stays sharp" column comes from.
- `Hips.tilesForLatitude(lat, order) → [n, ...]`, sorted: sample the band on a grid with a step of one quarter of a tile side (`58.6° / 2^k / 4`), widen the band by one step towards the horizon, and collect the distinct pixels.
- `Hips.url(base, order, n)` and `Hips.plan(lat, maxOrder) → { urls, tiles }`, which also lists `properties` and `Moc.fits`.

**Flow.** In the info sheet, under "Saved sky", a button **Save the sky for a place**:

1. Place: "Where I am now" (GPS) or typed coordinates, using the same parser as the landmark box (`#lmCoords`). Only the latitude is used; show the place back as "48° N".
2. Detail: Basic, Standard or Sharp, each with its size for this latitude from `Hips.plan`, and the free space from `navigator.storage.estimate()`.
3. If `navigator.connection?.saveData` is true or the connection type is `cellular`, ask once: "This uses about 8 MB of mobile data. Continue?"
4. Download in the page, not in the worker: 4 requests at a time, low orders first, skipping URLs already in `wanderers-sky-saved-v1`, `cache.put` for each. Show "132 of 212 pictures", with **Pause** and **Cancel**. Three failures in a row pause the download with "The archive is not answering. Your saved pictures are kept. Try again later." A second run resumes where the first stopped.
5. When it ends, call `navigator.storage.persist()` and record `{ lat, maxOrder, tiles, bytes, savedAt }` in `localStorage` (`wanderers.skySaved`).

**Keeping and removing.** The saved cache is separate from the automatic one: no size cap, no 7-day rule. The "Saved sky" row lists it ("Latitude 48° N, Standard, 8 MB, saved 14 Nov") with **Remove**. Saving a second place adds its missing tiles to the same cache and records both places; Remove for one place deletes only the tiles no other saved place needs. Note in the sheet: "On an iPhone, add this page to the Home Screen, or Safari may delete saved pictures after 7 days without a visit."

Eye view needs no download. Say so beside the button: "The Eye view already works without a connection."

**Done when:**
- `test/hips.test.js` passes with `node --test`:
  - order 0 has 12 pixels whose centres are at declination +41.81° (pixels 0–3, RA 45°, 135°, 225°, 315°), 0° (pixels 4–7, RA 0°, 90°, 180°, 270°) and −41.81° (pixels 8–11);
  - for 200 fixed sky positions and orders 1 to 3, `pixel(k, …) >> 2 === pixel(k − 1, …)` (a child lies inside its parent);
  - `tilesForLatitude(0, k)` returns all `12 · 4^k` pixels; for orders 2 and 3, `tilesForLatitude(90, k)` returns no pixel whose centre is below declination −20°; `tilesForLatitude(47.6, 2)` returns between 150 and 190 of 192;
  - the north pole is in pixel `b · 4^k + 4^k − 1` for a base pixel `b` in 0–3 (expected from the nested layout; if it fails, check against the next item before changing the test).
- **Ground truth:** in the browser, record every tile URL Aladin requests while the view sweeps the whole visible sky at the default zoom for latitude 47.6°. Every one of them is in `Hips.plan(47.6, 1).urls`. Save the two lists to `artifacts/real-sky/`.
- Save Standard for latitude 47.6°, switch the network off, reload, sweep the sky: no failed tile request, and no grey squares in a screenshot.
- Cancel half-way, save again: the count starts from the tiles already saved, not from zero.
- Remove leaves "Saved sky: none" and `navigator.storage.estimate()` drops.

## Step 6. Honesty and failure states

- The view label from the table in **Goal** is always visible under the switch, in the `.small` style.
- Next to it, the pointing quality: "Direction good to about ±N°", where N is `webkitCompassAccuracy` on iOS, 3 after a star or landmark calibration, 10 otherwise. When N is 10, the text is a button that opens the calibration sheet.
- Add one calibration option to the sheet: **Drag the sky.** With Eye or Deep on, the user drags the sky until one thing they can see (the Moon, a planet, a bright star) sits where they see it; the drag sets `S.cal.dAz` and `S.cal.dAlt`, exactly as the existing "lock onto something real" step does.
- Deep view never shows the Moon, planets, aircraft or satellites in the photographs. The canvas markers for Moon, Sun and planets stay on top in both views.
- Below the horizon the sky layer is dimmed to 35%, so "under your feet" stays distinct.
- `prefers-reduced-motion`: no change needed, the layer follows the phone.

## Out of scope

- Pixel-exact overlay on the camera image (needs a per-phone field-of-view calibration).
- Saving "tonight only" (a smaller download for one date), background downloads with the page closed, and a preview of the sky "as if I were there".
- A photographic Eye view. A wide-angle all-sky photograph (Mellinger) would suit it, but its tiles could not be reached or checked on 2026-11-14.
- More Deep layers. IRSA also serves `CDS/2MASS/Color`, `CDS/AllWISE/RGB-W4-W2-W1` and `SPHEREx/spherex_allsky_cube` in the same format, so an "Infrared" choice is a small follow-up once this works.
- Constellation lines and star names beyond the 16 already drawn.

## Order of work and checks

Do the steps in order; each one ships alone. Before the pull request: `node --test test/*.test.js` passes, `node --check app/compass.js app/sw.js app/sky.js` passes, and the README's Sky Compass paragraph names the two views, the credit line and the 7-day cache. Test on one real Android phone and one iPhone if available; say in the pull request which were tested.
