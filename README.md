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
Epsilon Indi B and WISE 0855. URLs are shareable and embeddable: `observatory.html?target=wise0855&ch=w2` (older links to `/?target=…` redirect there). Brand, logo files and the Day/Night palette: [BRAND.md](BRAND.md).

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
# 5. predicted star paths (proper motion + parallax; offline, seconds)
.venv/bin/python pipeline/star_trajectory.py

# view it
node server.js        # http://localhost:8000 (home), /observatory.html (workspace), live "Ask WANDERERS" via claude -p
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

### Predicted star path

Tick **Predicted path** under the sky viewer to see where the selected star should be. A green line shows the
predicted path over the years the frames cover, and a crosshair marks where the star should be in the frame you are
viewing. A dotted line continues the path to 2030, marked "2030?". The note under the toggles gives the motion rate
and the size of the parallax loop. It also says how closely the prediction matches the positions measured in the
frames and where the star should be in 2030.

This is the standard astrometric model, not a fitted or learned one. The catalogue position (Gaia DR3, or Luhman &
Esplin 2016 for WISE 0855) is moved along its proper motion. Then the yearly parallax shift is added: as Earth goes
around the Sun, a nearby star traces a small loop on the sky. Earth's position comes from astropy's built-in
ephemeris. WISE and SPHEREx orbit close to Earth, so Earth's centre stands in for them. Aberration and light bending
move every star in a small field by the same amount, so they are left out. The parallax formula matches astropy's
full coordinate transform to within 0.5 mas.

What the measurements show: the prediction matches the measured 4.6 µm positions to within one SPHEREx pixel (6.15″)
for every target. Barnard's Star matches to 0.9″ rms, Epsilon Indi B to 0.4″. The parallax loops (±0.55″ for
Barnard's Star, ±0.46″ for WISE 0855) are smaller than the noise of a position measured on 2″ display pixels. So
these frames show the proper motion clearly but cannot show the parallax itself. The output says so, and it gives
no error bars because the cached reference has no catalogue uncertainties.

```bash
.venv/bin/python pipeline/star_trajectory.py barnard --forecast 2027 2030   # writes app/data/barnard/trajectory.json
.venv/bin/python -m unittest tests/test_star_trajectory.py                 # model vs astropy, grid vs analyze.py
node --test test/starpath.test.js                                         # page helpers + every committed trajectory
```

### Star database and learnt trajectories

The **Star database** tab searches about 12,000 stars by proper name, Bayer/Flamsteed (`Alpha Lyrae`, `Alp Lyr`),
HIP, HD, HR or Gliese number (`Gl 699`). Pick a star to see its details and its path on the sky from 1900 to 2100: the
past as a solid line, the predicted future dashed, with a 68% uncertainty band, a table of positions and every
measured position used. Links open straight to a star: `?star=hip87937`.

**Data.** The search list comes from the HYG Database v4.1 (astronexus, CC BY-SA 4.0): every star with a name,
Bayer/Flamsteed or Gliese designation, or brighter than V = 6.5, plus the WANDERERS targets HYG lacks.
`pipeline/stardb.py` downloads it once to `data/cache/stars/` and writes `app/data/stars/index.json`.

**Model.** `pipeline/star_ml.py` learns each star's path from its measured positions, using a classical machine-learning
model: scikit-learn's `HuberRegressor`, a robust linear regression. The positions come from up to 13 catalogues with
their own observing dates, about 1950 to 2016: photographic plates (GSC 2.3), Hipparcos-2, Tycho-2, UCAC4, PPMXL,
2MASS, AllWISE, Pan-STARRS1, URAT1, CatWISE2020 and Gaia DR1/DR2/DR3. All are queried from the ESA Gaia archive. The
WANDERERS targets also use our own SPHEREx centroids. The model is fitted to each star separately; no weights were
trained beforehand. Four feature sets are compared by BIC: linear motion, plus parallax, plus acceleration, and both.
A parallax or acceleration term is only kept if it is a 3σ detection and physically possible. Uncertainty comes from a
parametric bootstrap, plus any acceleration too small to detect.

**Validation** is written into every result and shown on the page:
- **Gaia hold-out:** the model is retrained with no Gaia data and predicts where Gaia DR3 saw the star in 2016.0.
  The miss is 36 mas for Groombridge 1830, 108 mas for Groombridge 34 and 176 mas for Barnard's Star.
- **Learnt values vs Gaia DR3:** the learnt motion and parallax are compared with Gaia DR3's own. Proper motions agree
  to within a few mas/yr; Proxima's learnt parallax is 761 ± 103 mas against Gaia's 768.
- **Barnard's Star** gets an acceleration term of +1.33 mas/yr² in Dec. That is its known perspective acceleration.
- **WISE 0855:** the learnt motion is −8099, +712 mas/yr against Luhman & Esplin's −8123, +673. It uses mid-infrared
  data only, because the object is too faint for any optical catalogue.

**Known limit:** RW Aurigae is a binary inside nebulosity. Ground-based catalogues measure the blended light of both
stars, so its learnt motion differs from Gaia's.

```bash
.venv/bin/python pipeline/stardb.py                      # build the search list (downloads HYG once, 34 MB)
.venv/bin/python pipeline/star_ml.py --showcase          # the 18 stars shipped with the page
.venv/bin/python pipeline/star_ml.py "Tau Ceti" hip1475  # any other star, by name or key
.venv/bin/python -m unittest tests/test_star_ml.py       # synthetic stars: recovers motion, parallax, acceleration
node --test test/stardb.test.js                          # search, formatting, chart, every shipped prediction
```

**Over thousands of years.** Below the details, one year slider (±1,000 to ±50,000 years, with Play) drives three linked
views:
- **Sky:** a globe of the celestial sphere with a curved RA/Dec grid and real background stars. Switch to an
  RA/Dec atlas chart to see the curved track star atlases show.
- **3D map:** the Sun and Earth at the centre, the star's path through space, its closest approach and the nearest
  stars. Drag to rotate, scroll to zoom.
- **Distance through time,** with apparent brightness.

The learnt present-day state (position, motion, parallax when resolved) plus Gaia DR3's radial velocity is carried
through 3D space at constant velocity (`app/starcore.js`). That is the model behind astropy's `apply_space_motion`.
`test/starcore.test.js` checks it against astropy out to 30,000 CE; the fixture is in `test/fixtures/`.

Barnard's Star comes closest in 11,735 CE at 3.77 light-years. A cloud of 300 runs shows how the starting
uncertainties grow. The Galaxy's gravity and orbits around companions are not included. Links:
`?star=hip24186&span=50000&sky=radec&year=20000`.

With `node server.js` running, any star without a stored prediction can be learnt from the page (about a minute):
`POST /api/star-predict {"key": "hip1475"}`, then poll `GET /api/star-job/<n>`. One star is learnt at a time.

### Frame details and data flags

Under the sky viewer, **Frame details and data flags** lists each frame of the chosen wavelength (year, source,
how many SPHEREx images were stacked, whether the object was seen and how strongly), how many SPHEREx spectrum
measurements were left out because of flagged pixels, and the SPHEREx visits at that position. It shows only what
the pipeline recorded: a flagged / not-flagged count, not a count per flag type.

```bash
node --test test/frameinfo.test.js   # includes checks on every committed target
```

## Explore any patch (live mode)

Open <http://localhost:8000/explore/>, type any star name or sky position, and see its SPHEREx images as a blink
video, fetched live from IRSA. It needs the live API (`backend/`, port 8001) next to `node server.js`, and a build
of `web/`. The coordinate box links to it for positions outside the five missions.
Double-click `start.cmd` (Windows) or `start.command` (macOS), or run `node start.js`.
Setup and details: [docs/blink/README.md](docs/blink/README.md).

## Data (all public)

| Source | Used for |
|---|---|
| NASA SPHEREx DR1 spectral images (IRSA) | 2025 and 2026 images, spectrum, brightness change |
| NASA WISE / AllWISE atlas (IRSA) | 2010 images at 3.4 and 4.6 µm |
| ESA Gaia DR3 | positions and motions of the targets and of every field star (ghosts) |
| Luhman & Esplin 2016, AJ 152, 78 | motion of WISE 0855, which is too cold for Gaia |
| astropy built-in solar-system ephemeris | Earth's position, for the parallax term of the predicted star paths |
| HYG Database v4.1 (astronexus, CC BY-SA 4.0) | the searchable star list |
| ESA Gaia archive TAP (Gaia DR1-3, Hipparcos-2, Tycho-2, 2MASS, AllWISE, Pan-STARRS1, URAT1, UCAC4, PPMXL, GSC 2.3, CatWISE2020) | measured positions that train each star's trajectory model |
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
pipeline/   fetch.py · analyze.py · evidence.py · explain.py · targets.py · star_trajectory.py · stardb.py · star_ml.py
app/        index.html (home) · observatory.html · brand.css · theme.js · home.css · home.js · style.css · app.js · starpath.js · stardb.js · stars.js · starcore.js · longrange.js · data/<target>/ · data/stars/ (generated)
server.js   local demo server with live Claude answers
docs/field-shift/   our earlier Field Shift plan
```
