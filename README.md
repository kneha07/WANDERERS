# WANDERERS

> Catch what moves in the infrared sky, then read what it is made of.

**NASA Space Apps 2026 · Challenge: Planet X and SPHEREx · Team Hello Universe (Seattle)**

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

The five challenge test targets are the five "missions": Barnard's Star, R Draconis, RW Aurigae,
Epsilon Indi B and WISE 0855. URLs are shareable and embeddable: `?target=wise0855&ch=w2`.

## Run it

```bash
# one-time setup
python3 -m venv .venv && .venv/bin/pip install -r pipeline/requirements.txt

# 1. download and cache data (resumable; IRSA is busy during the hackathon, the script retries)
.venv/bin/python pipeline/fetch.py all
# 2. measure: frames, motion, spectrum, brightness change
.venv/bin/python pipeline/analyze.py all
# 3. evidence cards + target list
.venv/bin/python pipeline/evidence.py
# 4. plain-language explanations (Claude Code CLI, headless; no API key)
.venv/bin/python pipeline/explain.py

# view it
node server.js        # http://localhost:8000, live "Ask WANDERERS" via claude -p
# or any static server on app/, e.g.  python3 -m http.server -d app 8000
```

`app/` is a static site, so it can be deployed as-is (GitHub Pages, Netlify). The live question box only
appears when `server.js` is running.

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
