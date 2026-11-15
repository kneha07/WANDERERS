# Live checks: review fixes, user-advocate fixes and "About this star"

- Branch `feat/star-info`, 2026-11-14. Live API from this worktree on port 8031, Vite dev server on port 5193
  (`VITE_API_TARGET=http://127.0.0.1:8031`), headless Chrome (Playwright 1.64).
- The frames cache was cold (cache version 6). Cold builds: Barnard's Star 22.3 s, eps Ind B 18.8 s,
  WISE 0855 16.9 s (D6 8.5 s), RW Aur 16.9 s, R Dra 29.9 s, all with 0 failed images.

## About this star (`GET /api/about`)

The first answer waits 8 s for the CDS `-oxpI` mirror (it timed out all day), then the CfA mirror answers. After
that the CDS mirror is skipped for 10 minutes: each new answer took about 1 s, a cached one 3 ms.

| Target | Sentence 1 (catalog) | Sentence 3 (history) |
|---|---|---|
| Barnard's Star | Barnard's Star is a red dwarf (spectral type M4V) about 6.0 light-years away. | SIMBAD lists 924 papers about it. |
| Kapteyn's Star | Kapteyn's Star is a red subdwarf (spectral type M1VIp) about 12.8 light-years away. | SIMBAD lists 373 papers about it. |
| RW Aur | RW Aur is a young T Tauri star (spectral type K1/5e+K5e). (parallax 4 sigma: no distance) | "RW Aurigae B was discovered in 1944." — Wikipedia |
| R Dra | R Dra is a Mira variable, a pulsating red giant (spectral type M4.5-6+e) about 2,600 light-years away. | SIMBAD lists 154 papers about it. (no Wikipedia page) |
| eps Ind B | eps Ind B is a brown dwarf (spectral type T1V+T6V) about 12.1 light-years away. | "The brown dwarfs were discovered in 2003." — Wikipedia (page Epsilon Indi) |
| WISE 0855 | WISE J085510.83-071442.5 is a brown dwarf (spectral type Y2) about 7.4 light-years away. | "It is the fourth-closest ... discovered by Kevin Luhman in 2013 ..." — Wikipedia |
| Candidate in the Kapteyn field (78.00605, -45.05919) | SIMBAD: no object within 5″, so Gaia: "The nearest Gaia DR3 star, 0.5″ away, has G = 14.4 and lies about 16,000 light-years away (parallax 0.20 mas)." | Its history is unknown here. |

Sentence 2 (our SPHEREx frames): Barnard's Star 8.9″ per year toward the north-northwest (catalog 10.4″, PA 356°);
Kapteyn's Star 8.7″ per year toward the southeast (catalog 8.6″, PA 131°); WISE 0855 (all detectors) 9.2″ per year
toward the west-northwest; a candidate away from the target: "This tool measures motion and brightness only at the
target ...".

Card layout: at 1440 px the card grows from 163 to 182 px when the answer lands (CLS 0.003); at 375 px from 163 to
202 px (CLS 0.033). No horizontal scroll at 375 px. Screenshots: `1440-about-kapteyn.png`, `1440-about-WISE.png`,
`1440-about-loading.png`, `375-about-kapteyn.png`, `375-about-candidate.png`.

## Target switch A → B (issue #26, H1)

R Dra loaded, then Barnard's Star with its frames request held 6 s. While it loads, Motion, Brightness, Frames and
Your sky now show skeletons (no "R Dra", "16h 32m" or "+66°" in them) at 1440 and 375 px. The dimmed flipbook and
Sky context say "Showing R Dra until Barnard's Star loads." The wait text names the step. Screenshots:
`1440-switch-rdra-to-barnard.png`, `375-switch-top.png`.

## Layout (user-advocate M5, M6)

- 1440 × 900: the toolbar is one row at y 253-319, the image at y 327-897: both fit without scrolling (`1440-rdra.png`).
- 375 × 812: the test targets scroll in one row; the image is at y 397-740 (`375-kapteyn.png`).

## Browser checks

- `web/scripts/verify-ui.mjs` against port 5193: 29 checks, all PASS, exit 0 (final run). New checks: no data panel
  shows A while B loads; the dimmed flipbook names the old target; the wait text moves from "Looking up … in CDS
  Sesame" to "Getting the SPHEREx images …"; an unknown name fails with "No object called …" (6.5 s on a cold
  server, 0.1 s from its name cache); About has three sentences. The timeline step now scrolls the timeline into
  view first (the toolbar moved above the image).
- UX stress walk (`designing-ux-mechanics/stress-walk.mjs`, `web/ux-walk.json` with the search request counted at
  `/api/resolve`): 9 PASS, 0 FAIL, CLS 0.064. Record: `stress-walk.md`.

## start.js and the root .venv (issue #28)

A scratch worktree with no root `.venv` ran `PORT=8041 LIVE_PORT=8042 node start.js --no-open`. It created
`backend/.venv`, then the root `.venv` with `pipeline/requirements.txt` (pyvo 1.10.0 among them), then built the web
app and started both servers. `POST /api/field {"ra": 150, "dec": 2.2}` (10h00m00s +02d12m00s) went through
"Downloading images", "Measuring motion and spectrum" to `done`, tid `pos_150p0000_n2p2000`, with no
`No module named 'pyvo'`. The scratch worktree was removed afterwards.

## Round 2 fixes

- Toast after a mark (PM M2): at 375 × 812 it says "See Candidates below." and sits at y 8-65 over the search bar;
  the image (y 397-740) and the controls (y 846+) are free (`375-toast.png`). At 1440 × 900 it says "See the Task
  tab." and sits at y 72-113 under the top bar, off the image (y 327-897) and the toolbar (`1440-toast.png`).
- Position lookup (TL M1): SIMBAD rows are picked with planets last and the most studied object within 1" first;
  a mark on a Gaia star faster than 1"/yr is also looked for at J2000 (tests in `backend/test_about.py`).
- Live, CfA SIMBAD: `ra=269.452077&dec=4.693365` (the reproduction) now gives "Barnard's Star is a red dwarf (spectral
  type M4V) about 6.0 light-years away." (before: "Barnard's Star c is a planet ..."). The Gaia DR3 2016 position
  with `pmra=-801.551&pmdec=10362.394&epoch=2016` gives Barnard's Star; the same position without a proper motion
  finds no object within 5″.

## Round 3 (through server.js: `PORT=8071 LIVE_PORT=8072 node start.js --no-open`)

- NH1: `curl -m 2 "http://127.0.0.1:8071/api/frames?q=Gliese+445&fov=5"` (the client gives up after 2 s); 25 s later
  `/api/health` 200 and `/explore/` 200. Browser: Barnard's Star, then type Gliese 412 (1440) or Gliese 1 (375), Show,
  click R Dra while it loads; 8 s later the server answers 200 and R Dra shows. `ERR_STREAM` in the start.js log: 0.
  Screenshots: `1440-switch-server-js.png`, `375-switch-server-js.png`, `375-switch-server-js-done.png`.
- NM1, NM2: the WISE 0855 challenge coordinates show "A fast-moving star (WISEA J085510.74-071442.5, 8.2″/yr) is 127″
  from here. Typed coordinates from an old catalogue may miss it — search it by name." under the image, and the
  brightness panel says "No source at this position — the brightness numbers are sky noise." (`1440-typed-wise.png`).
- NL6: after a switch the phone chip row is at scrollLeft 0 (Barnard's Star first).
- Stress walk through server.js (`web/ux-walk.json`, baseUrl http://localhost:8071; the screen waits now wait for
  the loaded result, because the heading names the target while it loads):

| # | Check | Target | Result | Detail |
|---|---|---|---|---|
| N2 | Back (system) reaches home within 2 presses | Result (chip) | PASS | 1 press(es) |
| N2 | Back (system) reaches home within 2 presses | Second target | PASS | 2 press(es) |
| N2 | Back (system) reaches home within 2 presses | Candidate marked | PASS | 1 press(es) |
| N2 | Back (system) reaches home within 2 presses | Tutorial layer | PASS | 0 press(es) |
| D1 | No empty state before the first answer | Frames (deep link) | PASS | skeleton, cache or loading shown |
| M1 | No layout shift when data lands (CLS ≤ 0.1) | Frames (deep link) | PASS | CLS 0.047 |
| A1 | Press shows a response within 100 ms | Search button | PASS | 17 ms |
| A2 | A double tap sends once | Search button | PASS | 1 request(s) |
| L1 | At most one layer over a screen | all walked steps | PASS | never more than one |

9 PASS, 0 FAIL. The server stayed up for the whole walk.
