# Brief and judging criteria: where WANDERERS stands

Status on 2026-11-14, `main` at `33adca6` plus the fixes in the pull request that added this file.
Words used: **Done** (built and checked), **Partial** (built, with a stated limit), **Open** (not done), **Unchecked** (documented by the team, but nobody
has run it for this list).

## The brief ([Planet X and SPHEREx](https://www.spaceappschallenge.org/2026/challenges/planet-x-and-spherex/))

**Required**

| Requirement | Status | Where | Notes |
|---|---|---|---|
| A public web tool that displays SPHEREx images and how they change over time | Partial | `app/` | Built. Whether a public link exists is **Open**: the README describes a local server and a static copy, not a deployed address. |
| The user enters RA/Dec and gets a series of images "like a little video" | Partial | coordinate box in `app/`, `fields.js`, `pipeline/` | The five prepared targets work on a static copy. Any other position needs `node server.js`, because IRSA cannot be called from a browser (no CORS). |
| Works on Barnard's Star, Epsilon Indi B, WISE 0855, RW Aurigae, R Draconis | Done | `app/data/<target>/` | All five are prepared and have evidence cards. |

**Optional ("you may, but are not required to")**

| Consideration | Status | Notes |
|---|---|---|
| Easy to update with new data releases | Partial | The pipeline can be re-run. The live mode asks IRSA for `spherex_dr1` and `spherex_qr3` (`docs/blink/README.md`). The page does not say which release you are looking at. |
| Show the 102 bands creatively | Done | A 0.75 to 5 µm spectrum, and an Aladin sky map with a slider through all 102 wavelengths. |
| Add up each of the six detector arrays | Partial | The WANDERERS flipbook uses two wavelength channels (4.4 to 5.0 µm and 3.0 to 3.8 µm). Per-detector frames belong to the live "Explore" tool (**Unchecked**). |
| Spectra on the fly | Partial | The pipeline builds a spectrum for any position (the test field below gave 148 measurements in 73 bins), but it takes about 12 minutes, not seconds. |
| Add or subtract images from different times | Done | The 2026 minus 2025 difference, and a user-chosen add or subtract (it works on the displayed, stretched images, so it is for spotting motion, not for measuring). |
| Choose the field of view | Done | 2′, 5′ or 10′. The 2′ size has been run for real; 10′ has not. |
| Overlay Gaia and WISE | Done | Gaia "ghost" circles and the WISE 2010 frames. |
| Coordinates in the URL | Done | `?target=`, `?ra=&dec=&fov=`, and the add/subtract options. |
| Metadata such as contamination flags | Done | The "Frame details and data flags" panel. It shows a flagged or not-flagged count, not a count per flag type, because the pipeline does not export one. |
| Astropy and Aladin | Done | Astropy in the pipeline; Aladin Lite in the page. |

## The five judging criteria

| Criterion | What we can show | What is missing |
|---|---|---|
| Impact | A way for students and amateur astronomers to look at SPHEREx data. | A stated audience and how they will reach it. |
| Creativity | The evidence card ("3 of 3 checks support it"), Gaia ghosts, WISE and SPHEREx matched by wavelength, the spectrum. | The blink comparator itself is an old idea. Lead with the evidence and the spectrum. |
| Validity | Measured motion matches the catalogue (Barnard's Star 10.39 vs 10.39 ″/yr; WISE 0855 8.27 vs 8.15 ″/yr). Honest limits on the page. Tests below. | No astronomer has reviewed it. Aperture photometry, not PSF fitting. Bright stars lose their whole spectrum. |
| Relevance | The required items above, and most optional ones. | Any coordinates on a public link (see the first table). |
| Presentation | `docs/demo-script.md`, the evidence wording, the footer credits. | A recorded demo video and the submission text. |

## What has really been run

| Check | Result |
|---|---|
| Node tests (`test/*.test.js`) | 116 pass on `main` |
| Python tests with the real packages from `pipeline/requirements.txt`, Python 3.14 | 70 pass (the 10 data-quality tests had never run before) |
| **Real pipeline run on a brand-new 2′ field** around WISE 0855 (`fetch.py`, then `analyze.py`, then `evidence.py`) | Worked end to end. The grid came out at exactly 120″ (60 px at 2″). 11 frames at 4.6 µm and 5 at 3.4 µm, a spectrum, and an evidence card (candidate, steady star, **low** confidence, which is the honest answer for a bare position). |
| The download inside that run | 148 of 150 cutouts in about 12 minutes of downloading (about 14 a minute) while IRSA was often answering "503 busy". The on-demand job allows 20 minutes per step, so that fits today with about 8 minutes to spare, and could fail on a slower day. |

**The first attempt of that run failed**, and that is now fixed: one cutout gave up after its retries and stopped the whole job at 29 of 150. `fetch.py` now skips a few failed cutouts, says how many, and stops only if fewer than half arrive.

**Not run by anyone for this list:** the live "Explore any patch" mode (`backend/`, `web/`); a 10′ field; independent checking of the learnt-trajectory results; Python 3.11 (only 3.14 was available, so a test checks the syntax instead); a public deployment.

## Open decisions

- Issue #9: two on-demand features are on `main` (`/api/lookup` and `/api/field`); the page uses only one.
- Issue #6: two Planet X tools live side by side; how they combine.
- Issue #2: the background PDF.
- Pull requests #4 (blocked), #19 and #20 (waiting for review).

## Before submitting

1. Decide the story for "any coordinates": host the servers, or say plainly that live mode needs the one-click local start, and show that in the video.
2. Record the demo from `docs/demo-script.md` and run it once on a clean machine first.
3. Write the submission text from the tables above. Keep every claim to what is marked Done here.
