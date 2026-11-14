# WANDERERS

> Catch what moves in the infrared sky, then read what it is made of.

**NASA Space Apps 2026 · Challenge: Planet X and SPHEREx · Team Hello Universe (Seattle)**

**Live:** https://rajryadav4.github.io/wanderers/ · **Sky Compass (phone):** https://rajryadav4.github.io/wanderers/compass.html

Pluto was found by flipping between two photos of the sky and spotting the dot that moved. WANDERERS does
that with real infrared data spanning 2010 to 2026, then goes one step further: it uses SPHEREx's
102-colour spectrum to show *what* the moving or changing object is likely to be, with every piece of
evidence on screen. Unmatched objects are called **candidates, never discoveries**.

## What it does

1. **Flipbook across 16 years.** WISE (2010) and SPHEREx (2025, 2026) images of the same patch, matched by
   wavelength (4.6 µm and 3.4 µm channels), so you compare like with like.
2. **Gaia "ghosts".** Circles show where every star Gaia knows about *should* be in each frame. Anything that
   moves without a ghost is unexplained.
3. **Measured path.** The target's position is measured in every frame and compared with the catalogue motion.
4. **Infrared fingerprint.** Aperture photometry at the target in every SPHEREx image (hundreds of them), each
   placed at the wavelength that image recorded there, gives a 0.75–5 µm spectrum. Water, methane and CO/CO₂
   bands are marked.
5. **Brightness change.** The two SPHEREx sky surveys are compared wavelength by wavelength.
6. **Evidence card.** Simple, stated rules turn the measurements into a classification and a confidence
   ("3 of 3 checks support it"). No black-box score.
7. **Explanations by Claude.** Written from the measurements only, with rules against over-claiming.
8. **Independent checks from Gaia DR3.** Distance (parallax), temperature estimate and Gaia's own
   variable-star classification from ~3 years of its photometry (e.g. Gaia also calls R Draconis a
   long-period variable, agreeing with our SPHEREx measurement).
9. **Live sky map for any coordinates.** Aladin Lite on IRSA's SPHEREx DR1 all-sky cube with a slider
   through all 102 SPHEREx wavelengths (cold brown dwarfs appear only at the long end), plus AllWISE colour.
   Runs entirely in the browser, so it works on the public site for any RA/Dec.

The five challenge test targets are the five "missions": Barnard's Star, R Draconis, RW Aurigae,
Epsilon Indi B and WISE 0855. URLs are shareable and embeddable: `?target=wise0855&ch=w2`.

**Any coordinates.** Type an RA/Dec (degrees or `08h55m10.83s` / `-07d14m42.5s`). On the demo server
(`node server.js`) WANDERERS fetches a quick look of that patch (about 36 SPHEREx cutouts plus WISE and
Gaia), measures it and plays it as a flipbook in a few minutes. The public static site cannot do this by
itself because IRSA does not allow direct browser requests (no CORS), so it shows the prepared patches.

**Sky Compass.** On a phone, GPS + time + compass + tilt tell WANDERERS where the camera points; it guides
you to a target and opens its investigation. Works indoors; objects below the horizon are shown too.

## Run it

```bash
# one-time setup
python3 -m venv .venv && .venv/bin/pip install -r pipeline/requirements.txt

# 1. download and cache data (resumable; IRSA is busy during the hackathon, the script retries)
.venv/bin/python pipeline/fetch.py all
# 2. measure: frames, motion, spectrum, brightness change
.venv/bin/python pipeline/analyze.py all
# 3. independent Gaia facts, then evidence cards + target list
.venv/bin/python pipeline/gaia_facts.py
.venv/bin/python pipeline/evidence.py
# 4. plain-language explanations (Claude Code CLI, headless; no API key)
.venv/bin/python pipeline/explain.py

# view it
node server.js        # http://localhost:8000, live "Ask WANDERERS" via claude -p
# or any static server on app/, e.g.  python3 -m http.server -d app 8000
```

`app/` is a static site, so it can be deployed as-is (GitHub Pages, Netlify). The live question box only
appears when `server.js` is running.

### Add or subtract frames

Under the sky viewer, **Show** can subtract any two frames (later minus earlier, green = now, pink = before) or add
several together (average, to lower noise). It works in the browser on the displayed images, so it is for spotting
motion, not for measuring: the images are stretched, so the earlier frame's brightness is matched to the later one
first, with a light smoothing option and a threshold slider to hide speckle. Faint targets such as WISE 0855 look
noisy; the pipeline's raw-flux SPHEREx difference and the evidence card remain the measurements.

Links keep the choice: `?target=wise0855&mix=sub&a=0&b=3` (subtract), `?target=rw_aur&mix=add&set=1,2` (add),
with optional `th=0.6` and `sm=0`. Frame numbers count from 0 in the order of the frame slider.

```bash
node --test test/framemath.test.js   # includes checks on the real WISE 0855 and Barnard's Star frames
```

### Any coordinates, on demand (needs `server.js`)

With `server.js` running, typing coordinates that are not cached starts `fetch.py`, `analyze.py` and
`evidence.py` for that patch, shows progress in the coordinate box, and opens it when ready (first time:
several minutes). One field is prepared at a time, up to four can wait, and errors never show server paths.
It uses `.venv/bin/python` if present, or set `WANDERERS_PYTHON`. The static site does not have this; it
still shows the message that a teammate can add the field.

**Field of view.** The coordinate box has a size choice: 2′ (close-up), 5′ (standard, what the five test targets
use) or 10′ (wide). Larger fields can follow faster-moving objects but need more data and take longer. The size
is stored with the target (`fov_arcsec`, any whole number from 60 to 900 works from the command line), and each
size is cached separately: the standard size keeps the id `pos_<ra>_<dec>`, other sizes add `_f<arcsec>`.
Typed coordinates match a cached target only if the sizes agree; without the server, the nearest cached field is
shown with a note that the other size needs the local server. Links can carry it: `?ra=269.4479&dec=4.7461&fov=600`.

```bash
python .venv/bin/python pipeline/fetch.py --ra 133.795 --dec -7.245 --fov 600   # by hand, 10' field
node --test test/fields.test.js     # job handling, validation and HTTP checks (fake pipeline, no network)
python3 test/test_fov.py            # field-of-view helpers; no packages needed
```

### Frame details and data flags

Under the sky viewer, **Frame details and data flags** lists each frame of the chosen wavelength (year, source,
how many SPHEREx images were stacked, whether the object was seen and how strongly), how many SPHEREx spectrum
measurements were left out because of flagged pixels, and the SPHEREx visits at that position. It shows only what
the pipeline recorded: a flagged / not-flagged count, not a count per flag type.

```bash
node --test test/frameinfo.test.js   # includes checks on every committed target
```

## Data (all public)

| Source | Used for |
|---|---|
| NASA SPHEREx DR1 spectral images (IRSA) | 2025 and 2026 images, spectrum, brightness change |
| NASA WISE / AllWISE atlas (IRSA) | 2010 images at 3.4 and 4.6 µm |
| ESA Gaia DR3 | positions and motions of the targets and of every field star (ghosts) |
| Luhman & Esplin 2016, AJ 152, 78 | motion of WISE 0855, which is too cold for Gaia |
| IRSA HiPS: SPHEREx DR1 all-sky cube, AllWISE colour | live sky map in the browser (Aladin Lite 3.8.2, CDS) |
| NOAA/BGS World Magnetic Model 2025 | magnetic to true north in the Sky Compass |

Methods follow the IRSA SPHEREx tutorials: wavelength per pixel from the `WCS-WAVE` lookup table with SIP
turned off, the conservative bad-pixel flag set from the SPHEREx Explanatory Supplement, 3-pixel aperture
photometry with local background, and per-pixel solid angle from each image's WCS.

## Honest limits

- Bright stars (Barnard's Star) saturate SPHEREx at many wavelengths; those points are dropped and the card says so.
- AllWISE is a 2010–2011 coadd; we treat it as epoch 2010.5.
- Aperture photometry, not PSF fitting: good for the shape of a spectrum, not for precise absolute fluxes.
- Only the cached targets run in the browser; new coordinates need `pipeline/fetch.py`.

## Repo layout

```
pipeline/   fetch.py · analyze.py · evidence.py · explain.py · targets.py
app/        index.html · style.css · app.js · data/<target>/ (generated)
server.js   local demo server with live Claude answers
docs/field-shift/   our earlier Field Shift plan
```
