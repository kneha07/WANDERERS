# Spec: telescope zoom in Sky Compass

Status: **phase 1 built** on this branch (2026-11-15) and checked in a browser. The real-phone test is pending (#71). Phases 2 and 3 are not started. Branch `feature/compass-telescope`, worktree
`.worktrees/compass-telescope`, made from `feature/compass-pinch-zoom` at `d938fb5`. That branch is not merged yet,
and this work needs it (it adds `S.zoom`, `setZoom`, the pinch and wheel gestures, and the daily survey check).

## Goal

Zooming in the Sky Compass should feel like moving from the eye to a telescope. As the user keeps pinching, the
background changes from the camera (or the drawn stars) to survey photographs, then to deeper surveys, and at the
end to Hubble or Webb pictures where they exist. Every step says which telescope the picture is from.

## What exists today

Read these before changing anything.

| Piece | Where | What it does |
|---|---|---|
| Zoom | `app/compass.js`: `setZoom`, `ZOOM_MAX = 8`, `focalPx` | `S.zoom` multiplies the focal length. The camera picture gets `transform: scale(zoom)`. Range 1 to 8, or 0.5 to 8 with no camera. |
| Pointing | `app/compass.js`: `pose()`, `S.manual`, `S.sensors` | With motion sensors the pose is `F.pointing()`. Without them it is `S.manual` (drag or arrow keys). |
| Sky modes | `app/realsky.js`: `R.sky` = `off`, `eye`, `deep` | Eye draws stars on the canvas. Deep shows HiPS photographs in `#skyDeep` (Aladin Lite, `TAN`), kept under the canvas by `syncDeep`. |
| Surveys | `app/hips.js`: `CONFIG.surveys`, `CONFIG.tileRoots` | DSS2 visible and 2MASS infrared, two hosts each. `sw.js` only caches tiles under `tileRoots`. |
| Registration check | `RealSky.selfTest()`, `test/browser/realsky.mjs` | Compares where Aladin and the canvas put the same star. Limit 3 px. |
| Webb | `app/telescope.js`, the `#webbChip` in `compass.js` | Finds Webb frames near the crosshair and opens a separate Webb viewer sheet. |

## Facts checked on 2026-11-17

From the CDS MocServer (`https://alasky.cds.unistra.fr/MocServer/query?ID=<id>&get=record`). At zoom 1 on a phone
with no camera, 1° is 12.8 CSS pixels, so "native zoom" below is the zoom where one survey pixel is one CSS pixel.

| Survey (CDS ID) | Deepest order | Pixel | Sky covered | Native zoom | Tiles | Host |
|---|---|---|---|---|---|---|
| DSS2 colour (`CDS/P/DSS2/color`) | 9 | 0.8″ | 100% | about 350× | jpeg | IRSA, ESA (in use now) |
| Pan-STARRS DR1 colour (`CDS/P/PanSTARRS/DR1/color-z-zg-g`) | 11 | 0.2″ | 78% (north of Dec −30°) | about 1,400× | jpeg | `alasky.cds.unistra.fr/Pan-STARRS/DR1/color-z-zg-g` |
| DESI Legacy DR10 colour (`CDS/P/DESI-Legacy-Surveys/DR10/color`) | 11 | 0.2″ | 67% | about 1,400× | png | `alasky.cds.unistra.fr/DESI-legacy-surveys/DR10/CDS_P_DESI-Legacy-Surveys_DR10_color` |
| SDSS9 colour (`CDS/P/SDSS9/color`) | 10 | 0.4″ | 36% | about 700× | jpeg | alasky, IRSA, ESA |
| Hubble outreach (`CDS/P/HST/EPO`) | 14 | 0.025″ | 0.08% | about 11,000× | png | `alasky.cds.unistra.fr/HST-outreach/CDS_P_HST_EPO` |
| Webb NIRCam, MIRI, NIRISS | not checked | not checked | tiny | not checked | png | `skies.esac.esa.int/JWST/...` (already used by `telescope.js`) |

Not checked yet, and the builder must check before phase 2:

- Whether the `alasky` tile requests pass CORS from the page and from `sw.js` (the 404 answers carried
  `Access-Control-Allow-Origin: *`, real tiles were not fetched).
- Whether `alasky` is reliable enough to be the only host. Each new survey also has an `alaskybis` mirror.
- The credit line each survey asks for.

## Design

### 1. The ladder

One number, `S.zoom`, picks the rung. Rungs overlap so the change is a cross-fade, not a cut.

| Rung | Zoom | Width of view (phone) | Background | Label |
|---|---|---|---|---|
| Eye | 1 to 3× | 30° to 10° | Camera, or the user's chosen sky mode | as today |
| Finder | 3 to 6× fade, then to 60× | 10° to 0.5° | DSS2 photographs | "Telescope view: Digitized Sky Survey 2, photographs taken decades ago" |
| Observatory | 60 to 100× fade, then to 800× | 0.5° to 0.04° | Pan-STARRS DR1 where it covers, else DSS2 stays | "Pan-STARRS 1 telescope, Hawaii, 2010 to 2014" |
| Space telescope | from 300×, only inside a frame | under 0.1° | Hubble outreach or Webb layer over the rung below | "Hubble" or "Webb", with the frame name |

- Raise `ZOOM_MAX` from 8 to 800. Keep the lower limit as it is.
- The fade amount for a rung is a clamped linear ramp over its fade range, for example
  `clamp((zoom − 3) / 3, 0, 1)` for Finder.
- Rules for the lower rungs when Finder is fading in:
  - Camera on: `#skyDeep` opacity goes from the user's own mix to 1. The camera is underneath and is covered.
  - No camera, Eye mode: the dark canvas backdrop and the drawn stars fade out by the same amount.
  - Planets, Sun, Moon, targets and labels stay drawn. The photographs do not contain them.
- The user's chosen mode (`R.sky`, the mix slider) is not changed or stored by zooming. Zooming back out returns
  exactly what was there.
- Hide the altitude rings and azimuth lines above 6×. They are drawn as 5° chords and would be visibly wrong, and
  they are clutter in a telescope view. Keep the horizon line.

### 2. Hold mode (the mount)

Phone sensors jitter by more than the field of view at high zoom. So past a threshold the view stops following
the phone.

- Enter at zoom ≥ 8, leave at zoom < 6 (the gap stops flicker). Only matters when `S.sensors` is true.
- On entering: copy the current pose's `az` and `alt` into `S.manual`, set `S.hold = true`. `pose()` then uses
  `S.manual`, the same path as desktop drag mode. Drag and arrow keys must work while `S.hold` is true.
- Snap: if a target is selected and within 6° of the crosshair (the existing "Locked on" rule, `T._sep <= 6`),
  enter hold mode centred on the target, not on the noisy phone pose. This is what makes deep zoom land on
  something real.
- On leaving: `S.hold = false`. The view returns to where the phone points.
- Drag speed already divides by `S.zoom`.
- Show it: `HELD` next to the zoom in the telemetry line, and one hint line under the crosshair the first time,
  "View held. Drag to move. Pinch out to follow the phone again."
- `realsky.js` `follow()` ("Drag the sky" calibration) must treat hold mode as no-sensor mode, or it will change
  the sight-check offsets while the pose ignores them.

Decision for the builder to confirm with the user: the manual pose has no roll, so a phone held at a lean will
level itself on entering hold mode. Accept this for the first build.

### 3. More than one survey in Deep

- Add the new surveys to `Hips.CONFIG` with their hosts, fade ranges and credits. Add the `alasky` roots to
  `CONFIG.tileRoots` so `sw.js` keeps their tiles. `test/hips.test.js` checks that `sw.js` repeats no setting.
- Draw the Observatory rung as a second Aladin image layer over DSS2 (Aladin Lite 3 has overlay image layers with
  their own opacity). Set its opacity to the fade amount each frame, only when it changes.
- Coverage: a HiPS survey publishes `Moc.fits`. Where Pan-STARRS has no data its tiles are missing, so DSS2 simply
  stays visible underneath. The label must then say DSS2, so the code needs to know if the crosshair is covered.
  The simple first rule: Pan-STARRS covers Dec > −30°.
- A startup failure in telescope mode must not retry every frame. Wait 30 s between attempts, and keep whatever
  rung below is working.

### 4. Space telescope rung

- Reuse what `telescope.js` knows: `Webb.near` and `Webb.framesAt` say whether a Webb frame is under the
  crosshair. Above 300×, when one is, add the ESASky Webb layer over the rung below and name the frame.
- Hubble outreach is one HiPS for the whole sky with almost no coverage. Add it as a layer above 300× and name it
  only when the crosshair is inside its MOC.
- The `#webbChip` already tells the user "Webb looked here". Add "pinch in to see it" to that chip, and make a tap
  on it offer the zoom as well as the sheet.

### 5. Honesty rules

These are requirements, not polish.

- The note line (`#skyNote`) always names the survey on screen and that it is an archive photograph, not live.
- Unless a sight check or "Drag the sky" was done (`F.compassFrozen`), or the view snapped to a target, the note
  says the direction is approximate: "Your compass is good to a few degrees, so this is near where you point, not
  exactly it."
- Deep zoom needs the network. "Save the sky for a place" stores orders 0 to 3 only. With no signal, zoom still
  works but the photographs stay blurry; say "No connection: no finer photographs" instead of loading forever.
- On mobile data, deep tiles are fetched only for what is looked at. No prefetch.

## Phases

Each phase is one pull request and is useful alone.

| Phase | Work | Done when |
|---|---|---|
| 1. Telescope feel | Raise the zoom limit to 300. Finder fade (camera and Eye into DSS2). Hold mode with snap. Note and telemetry text. Hide the grid above 6×. | Node test: hold enters at 8×, leaves under 6×, drag works while held, snap centres a locked target. Browser check: in Eye mode at 12× the photographs show and `selfTest` is within 3 px; with fed sensor poses the view does not move while held. Tried on a real iPhone and a real Android phone. |
| 2. Observatory rung | Check CORS and credits. Pan-STARRS layer with cross-fade and coverage fallback. `sw.js` roots. Limit to 800. | Browser check: at 150× north of Dec −30° the Pan-STARRS layer is on and named; south of it DSS2 is named. Registration within 3 px at 150×. |
| 3. Space telescope rung | Webb and Hubble layers above 300× inside a frame. Chip text. | Browser check on one known Webb field and one Hubble field: the layer shows, the note names it, and one frame away it is gone. |

## Built beyond the spec (phase 1)

- Sidereal tracking: at 8× or more the manual or held view turns with the sky, so a target stays in view at 300×.
- A `1×` button and the Escape key return to 1× in one step.
- "Loading telescope photographs…" shows while the photographs load. A load that takes more than 20 s counts as
  failed. After a failure, the next try waits 30 s.
- The snap glides to the target in 250 ms. With reduced motion it jumps.
- One short buzz when hold mode starts.
- The arrow-key step is divided by the zoom.
- The photographs start loading at 2×, but at 3× on mobile data or Save-Data.
- With the camera on, hold mode needs the photographs to cover the view. Otherwise the camera picture and the held
  drawing would not agree.
- The hold hint shows on the first hold of a visit only.
- The white crosshair has a dark edge, so it shows on a saturated star.
- Real-phone test: still to do, see issue #71.

## Out of scope

- Native camera zoom (`applyConstraints({ zoom })`). The camera is faded out before it matters.
- Keeping the phone's roll in hold mode.
- Saving deep tiles for offline use.
- A calibration that makes the phone's pointing accurate enough for deep zoom without a sight check.

## Open questions for the user

1. Pan-STARRS (78% of the sky, jpeg) or DESI Legacy (67%, png, sharper colours) for the Observatory rung? This
   spec assumes Pan-STARRS.
   Builder default (the user can change it): the survey choice is deferred to phase 2, and Pan-STARRS stays the
   assumption.
2. Should entering hold mode be automatic at 8×, as written, or a button?
   Builder default (the user can change it): hold mode starts automatically at 8×.
3. Is an eyepiece look (a round dark vignette) wanted, or should the view stay full screen?
   Builder default (the user can change it): no eyepiece vignette. The view stays full screen.
4. The view levels its roll on entering hold mode.
   Builder default (the user can change it): accepted for the first build.
