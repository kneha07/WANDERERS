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

**Sky Compass** (`app/compass.html`, an extra for phones). The intro uses only real imagery: the NASA Blue Marble /
Black Marble Earth with the real day/night line swings in to your location, then NASA GIBS imagery of your region
with your city, time zone and sidereal time. Calibration takes ~10 s: lay the phone flat, hold, and give it three
quarter turns. The gyroscope measures the turns, so if the compass disagrees the app reports magnetic interference
(magnetic cases, laptops, metal), and averaging four directions cancels the phone's own bias. A sight check on a
landmark (drawn in the camera view), the Sun, the Moon or a star sets north exactly and stops using the compass.

**Through Webb** (console tab and Sky Compass). WANDERERS matches any coordinates against the outlines of every
public JWST imaging frame in NASA's MAST archive (22,049 frames merged into ~5,500 pointings, `pipeline/make_webb.py`)
and shows the real Webb pixels there, with the frame outline on top: a MAST preview placed with its own WCS for our
targets and every catalogue star inside a Webb frame (`pipeline/make_webb_previews.py`), otherwise ESA ESASky's live
JWST maps where their coverage map says they have data, otherwise the outline alone with links to the full image and
the STScI programme page. In the Sky Compass, Webb pointings near where you aim appear as gold squares, and a chip
offers "Webb looked here" when one is inside the crosshair. Picking a star tells you whether Webb has imaged it
(WISE 0855, Fomalhaut, Vega, the Trapezium and 60+ others) or how far its nearest Webb frame is. For what Webb is
observing right now, the app links to Space Telescope Live (STScI), which has no public API.

Motion uses sensor fusion (`app/orient.js`): the gyroscope drives every movement and the compass only sets north,
averaged while the phone lies flat and corrected slowly after. `node tests/orient.sim.js` replays realistic sensor
streams (gyro drift, compass noise, tilt bias, declination, indoor magnetic distortion, Android spikes) through the
old and new engines, including the iPhone heading flip seen in a real test recording (the compass switches from the
phone's top to its camera at 45° tilt, so pointing above 45° flipped the old version by 180°). The new engine holds
0.1-0.5° error with 0.1° wobble; with a 12° magnetic case, four-direction calibration gives 0.1-0.8° (one direction:
5-9°) and flags the interference. A uniform bias from a steel building cannot be seen by any calibration on a table;
one sight check removes it.

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
# 5. star names and Webb frames for the search and "Through Webb"
.venv/bin/python pipeline/make_stars.py hygdata_v40.csv.gz
.venv/bin/python pipeline/make_webb.py
.venv/bin/python pipeline/make_webb_previews.py

# view it
node server.js        # http://localhost:8000, live "Ask WANDERERS" via claude -p
# or any static server on app/, e.g.  python3 -m http.server -d app 8000
```

`app/` is a static site, so it can be deployed as-is (GitHub Pages, Netlify). The live question box only
appears when `server.js` is running.

## Data (all public)

| Source | Used for |
|---|---|
| NASA SPHEREx DR1 spectral images (IRSA) | 2025 and 2026 images, spectrum, brightness change |
| NASA WISE / AllWISE atlas (IRSA) | 2010 images at 3.4 and 4.6 µm |
| ESA Gaia DR3 | positions and motions of the targets and of every field star (ghosts) |
| Luhman & Esplin 2016, AJ 152, 78 | motion of WISE 0855, which is too cold for Gaia |
| IRSA HiPS: SPHEREx DR1 all-sky cube, AllWISE colour | live sky map in the browser (Aladin Lite 3.8.2, CDS) |
| HYG database v4.0 (astronexus; Hipparcos, Yale Bright Star, Gliese), CC BY-SA 4.0 | the 9,265-star name search (`app/data/stars.json`, same licence) |
| MAST (STScI), JWST public level-3 images | Webb frame outlines (`s_region`) and previews for "Through Webb" |
| ESA ESASky JWST NIRCam / MIRI / NIRISS HiPS | live Webb pixels where covered |
| IRSA HiPS mirrors of 2MASS and DSS colour | sky underneath the Webb view |
| NOAA/BGS World Magnetic Model 2025 | magnetic to true north in the Sky Compass |

Methods follow the IRSA SPHEREx tutorials: wavelength per pixel from the `WCS-WAVE` lookup table with SIP
turned off, the conservative bad-pixel flag set from the SPHEREx Explanatory Supplement, 3-pixel aperture
photometry with local background, and per-pixel solid angle from each image's WCS.

## Honest limits

- Bright stars (Barnard's Star) saturate SPHEREx at many wavelengths; those points are dropped and the card says so.
- AllWISE is a 2010–2011 coadd; we treat it as epoch 2010.5.
- Aperture photometry, not PSF fitting: good for the shape of a spectrum, not for precise absolute fluxes.
- Only the cached targets run in the browser; new coordinates need `pipeline/fetch.py`.
- Through Webb: ESASky's Webb maps hold a subset of the data (to mid-2024), and MAST full previews are too large for
  phones, so many frames show the outline only, with a link to the full image. Frames are matched with the
  catalogue (J2000) position; a fast-moving star can sit a few arcseconds from where Webb saw it.
- Kapteyn's Star and Luhman 16 were first added with hand-typed coordinates that were 17-30″ off; they now use the
  Gaia DR3 position (Luhman 16: Gaia position with the published motion from Bedin et al. 2017).

## Repo layout

```
pipeline/   fetch.py · analyze.py · evidence.py · explain.py · targets.py · gaia_facts.py
            make_stars.py · make_webb.py · make_webb_previews.py · make_declination.py · describe_extras.py
app/        index.html · app.js · compass.html · compass.js · orient.js · sky.js · search.js · telescope.js · intro.js
            data/<target>/ · stars.json · webb.json · webb/ (generated)
server.js   local demo server with live Claude answers
docs/field-shift/   our earlier Field Shift plan
```
