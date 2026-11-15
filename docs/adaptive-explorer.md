# Adaptive Explorer: one universe, four ways to explore

How the four explorer modes are built, what each one changes, and the privacy and accuracy rules they follow.
If this page and the code disagree, the code is right: fix this page.

## Modes

| Mode | For | What changes |
|---|---|---|
| Kids Explorer | ages 6–12 (a preference, not an age check) | Story cards, missions, quick questions, constellation cards, Space Camera; the Observatory gets a guide, a before/after slider and fewer tools |
| Student Explorer | ages 13–17 | Same building blocks, more science in the words (proper motion vs parallax, spectra, 1σ) |
| General Explorer | adults | The original WANDERERS pages, unchanged, plus "Share a factual summary" in the Observatory |
| Research Mode | anyone | The original pages plus a research data table (filter, sort, CSV), per-epoch measurements and reproducible exports |

The only thing stored is the mode id (`localStorage["wanderers-mode"]`). `?mode=kids|teens|adults|research` applies a
mode for one visit without saving it. Every page that uses modes sets `<html data-mode>` in `<head>`, before first paint.

## Files

| File | Role |
|---|---|
| `app/explorer.js` | Mode config, chooser dialog, header switcher, explanation layers (`EXPLAIN`: motion, brightness, fingerprint, evidence, webb, starquake) |
| `app/explorer-home.js` | Shared `facts(target)` read from evidence cards, `load()` of `data/index.json` + every `target.json`; homepage stories, the "Where was it before?" mission, the research table |
| `app/explorer-learn.js` | Homepage missions board, quick questions, constellation cards |
| `app/discoveries.js` | Missions, quizzes and the discovery collection (`localStorage["wanderers-discoveries"]`: mission id → day) |
| `app/explorer-observatory.js` | Observatory layer. Watches `?target=` and `#tName`; never edits `app.js`. Does nothing if it cannot mount |
| `app/research.js` | Markdown summary, positions and spectrum CSV, research table filter/sort/CSV |
| `app/story-render.js` | Gnomonic projection, constellation figures, card templates and layout, phone pose and sky-to-screen projection |
| `app/stories.html`, `app/stories.js`, `app/stories.css` | Space Camera and Story Studio |
| `app/share.js` | Download, copy and Web Share with a download fallback |

All four modes read the same `app/data` files. Nothing in this layer computes new science: it reformats what the
pipeline wrote (`target.json`), converts units, and labels values as Measured, Catalogue or Interpretation.

## Privacy rules (enforced by tests)

- No account, no age, no name. Modes are preferences; Research Mode is open to everyone.
- The discovery collection stores mission ids and days only. No streaks, points or timers.
- Space Camera asks for the camera only when "Open camera" is tapped, and for motion sensors and location only when
  "Sky labels" is tapped. Location stays in memory, is used only to place the labels, and is never drawn on a card.
- Uploaded photos are redrawn on a canvas, so EXIF/GPS tags are dropped. Cards carry a day only.
- Nothing is uploaded. Stories are downloaded, shared through the device's share sheet (Web Share API, after a tap) or
  saved in this browser's IndexedDB ("My stories"), which the person can delete.
- Community classification (a public GitHub issue form) is not shown to Kids or Students; the free-text Ask box is not
  shown to Kids.

## Accuracy rules

- Sky labels on the camera are **estimates** from the phone's compass, tilt, clock and location, computed with the Sky
  Compass maths in `sky.js` (with the World Magnetic Model declination). They are labelled "(est.)" on screen, with a
  banner, and every card made from them says "Sky labels estimated from phone sensors, not identified in the photo".
- Pointing uses the Sky Compass orientation engine (`orient.js`): the gyroscope drives movement and the compass only
  sets north, so labels are steady, include roll and landscape, and survive the iPhone heading flip above 45°.
- Two ways to correct north: "Line up on the Moon or a star" is Sky Compass's sight check (aim the gold crosshair at the
  Moon, a planet or a bright star that is up, tap Set; an aim more than 20° off in height is rejected), and the
  "Labels look off?" slider turns the labels by ±30°. The Sun is never offered. A card made after a line-up adds
  "(north lined up by eye on …)" to its note.
- Constellation figures are drawn from real J2000 star positions but are labelled "illustration" on cards.
- Story and quiz numbers are read from each target's evidence card. A story or quiz whose fact is missing is not shown.
- Movement rings on story cards are drawn only for targets whose evidence card says they moved.
- Research summaries print the evidence checks beside raw measurements (for example R Draconis: measured 0.52″/yr, and
  "No measurable motion" from the evidence rule).

## Known limits

- Sky labels and the line-up were tested with simulated sensors (a synthetic camera stream, a fixed location and
  dispatched orientation events), and with the same engine's unit tests. They have not yet been checked on a real phone
  under the sky.
- Sky Compass's four-way flat calibration and its landmark list (Seattle) are not offered on the camera page: the
  line-up on a sky object covers the same need while the camera is open. Calibration is per page visit; it is not
  shared between Sky Compass and Space Camera, because the gyroscope's frame starts afresh on every page.
- The field of view is assumed (63° landscape, 48° portrait), so labels are approximate at the edges of the picture.
- Offline: `sw.js` keeps `stories.html`, its scripts and every `target.json` after one visit; the NASA pictures
  ("Use a NASA picture") still need a connection.
- Through Webb and Starquakes get a mode-specific introduction; their own panels are unchanged.
