# Product gaps: from data display to insight

Date: 2026-11-14. Base: `origin/main` at `35cb320`. Scope: the WANDERERS page (`app/`) and the live explorer (`web/` + `backend/`).

## What the challenge asks, and who uses it

The brief asks for a public tool that helps "as many people as possible pitch in to make discoveries". So the job is not "show SPHEREx images". The job is: **help a person decide whether something in a patch of sky moved or changed, whether it is already known, and what to do next.**

| User | Question they bring | What they need to leave with |
|---|---|---|
| Curious visitor, student | What am I looking at, and why does it matter? | One plain sentence of meaning per number (how fast, how far, how cold) |
| Citizen scientist (Backyard Worlds type) | Is there anything here that moved and is not known? | A short list of things that changed, each one checked against known objects, and a place to report it |
| Astronomer, teacher | Can I trust it, cite it, reuse it? | Method, limits, data release and date, a link and a download |

## Gaps (ranked)

1. **The page shows answers we already know.** All five missions are known objects, and the status never reads "candidate". The mover search exists (`movers_experimental` in each `target.json`), but the page does not show it, and its output is not vetted: in the WISE 0855 field it reports three "unexplained" movers, and one of them is WISE 0855 itself paired with the wrong second dot.
2. **Numbers without meaning.** "10.40″/yr" tells a visitor nothing. *Fixed in this branch, see below.*
3. **Statements a public site must not make.** RW Aurigae, a famous variable star, was labelled "Steady star". R Draconis showed "measured motion 0.43″/yr" beside a catalogue value of 0.02 with no warning (the shift is 1.1 pixels on a saturated core). *Both fixed in this branch.* Still open: "3 of 3 checks" counts "Gaia has this object" as support for the class, which is circular for a known object.
4. **No check against the Solar System.** Between SPHEREx visits days apart, the commonest moving dot is an asteroid. The page compares against Gaia stars only. *Now stated as a limit; not yet checked.*
5. **Two products, two designs.** `/` (precomputed, rich) and `/explore/` (live, thin) have separate looks, separate target lists and split features (issues #6, #9). The challenge's core flow, "type RA/Dec, get a video", works only with two local servers running.
6. **Nothing is hosted.** There is no public URL. The static page cannot serve a new position, and "Ask" needs a local Claude CLI.
7. **A 15-year hole in the time line.** Frames jump from WISE 2010 to SPHEREx 2025. NEOWISE imaged every position twice a year from 2014 to 2024, and there is no brightness-against-time chart at all, only a two-point difference.
8. **Production basics.** No CI, no methods or about page, no data-release stamp or "last updated", no social preview tags, no download of the measurements, Aladin loaded from a CDN with no pinned hash, tests split over `test/` and `tests/` (#11).

## Boundaries (what the tool cannot do, so the site must not imply it)

- **Motion.** A SPHEREx pixel is 6.15″. With SPHEREx alone (6 to 12 months) only motion above roughly 12 to 26″/yr passes the 2-pixel rule. Slower motion needs the 2010 WISE frame, which lowers the floor to 0.78″/yr. The page now prints this per target.
- **Planet X itself.** A distant planet is probably too faint for a single SPHEREx image (not verified here). The tool finds nearby stars, brown dwarfs and asteroids. The name is the challenge's, not a promise.
- **Bright stars.** Bright stars overflow the detector (RW Aurigae already does, at Gaia magnitude 12). Three of the five test targets have no usable spectrum.
- **Spectra.** Aperture photometry on 6″ pixels: good for the shape, not for absolute flux, and neighbours blend in (WISE 0855 below 1 µm).
- **Brightness change.** Two or three visits. A change between visits is not seen.
- **Live data.** Depends on IRSA. A cold call takes 25 s to minutes, and IRSA returns 502/503 under load.
- **AI text.** Written from `target.json` only. A public "ask anything" box costs money and invites abuse, so a hosted site should ship the pre-written answers only.
- **Branding.** A Space Apps project may not use the NASA logo or imply endorsement. "NASA data", not "NASA site".

## Done in this branch (`feature/insights`)

- `pipeline/evidence.py`: new `insights(t)`, stored as `target.json → insights`.
  - `facts`: sideways speed in km/s, time to cross the Moon's width, distance and light-travel time, temperature against the Sun, the methane meaning, brightness change in percent, "invisible to Gaia". Each has a `basis` line with the formula, and each is derived only from numbers already on the card.
  - `limits`: the motion floor for this target, what SPHEREx alone could catch, the number of visits, saturation, no asteroid check, pixel blending.
- Honest labels: "Known variable star, quiet in these snapshots" for a listed variable with no measured change; "apparent drift (below the detection limit, not a real motion)" for a sub-threshold shift.
- `app/`: "What this tells us", "What this view cannot show", and "Check it yourself" links (SIMBAD, Gaia, Backyard Worlds) at the latest measured position.
- Tests: 7 new cases in `tests/test_evidence.py`. Screenshots: `artifacts/insights/`.

### Vetted mover list (second commit)

- `pipeline/vet.py` grades every pair from the automatic mover search: `target`, `known`, `rejected` or `candidate`, first matching rule wins, each with its reason. Rules: both ends on the target's path; one end on it (wrong pairing); Gaia explains the path; SIMBAD has a matching mover; an end at the field edge; an end on a Gaia star that does not move; an end on a static SIMBAD object. SIMBAD answers are stored in `target.json → changes`, so the static site needs no network. `evidence.py` grades without SIMBAD when `changes` is missing, so on-demand fields get a list too.
- `app/`: "What else moved in this field?" under the viewer. **Show** draws the pair on the image; `?target=wise0855&pick=2` shares it.
- Result on the five fields: 6 pairs proposed, 0 left unexplained. Epsilon Indi B: the target found, one edge artefact. WISE 0855: one wrong pairing of the target, two static Gaia stars, one edge artefact.
- **What this exposed:** the search recovers its own target in 1 of the 3 fields where the target moves (not Barnard's Star, not WISE 0855). The page says so. Until `find_movers` is fixed, an empty list means "nothing found", not "nothing there".
- Tests: `tests/test_vet.py` (12 cases).

Still open for this feature: fix `find_movers` itself (needs the FITS cache, which is not in this checkout); an asteroid check (needs per-image times, which `target.json` does not keep); the same list in `/explore/`.

Not regenerated: `explain.json` (needs the Claude CLI). The five texts still agree with the new cards.

## Next, in order of value

1. **Make the mover search recover its own targets.** Fix the pairing in `find_movers` (try the Gaia-predicted and target paths first, then similar brightness), run it on SPHEREx-only pairs as well, and add the IMCCE SkyBoT asteroid check per image. The vetting and the list are done.
2. **One product.** Port the insight and evidence panels to the live explorer, or call the live API from the missions page, and close #6 and #9.
3. **Host it.** Static `app/` on GitHub Pages with the five missions, and the live API on a small host with its disk cache and a rate limit.
4. **Time line.** NEOWISE epochs between 2010 and 2025, plus a brightness-against-time chart per target.
5. **Production basics.** CI for the three test suites, a methods page, a data-release stamp, CSV download of the spectrum and track.
