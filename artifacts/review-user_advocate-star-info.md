# User-advocate review: feat/star-info (fix-loop round 2, phase 2)

- Seat: user_advocate (independent; I did not write this code). Runs after tech_lead PASS and project_manager PASS.
- Branch `feat/star-info` at `991edbf`, worktree `.worktrees/star-info`.
- Live stack: `PORT=8061 LIVE_PORT=8062 node start.js --no-open` from the worktree. Headless Chrome (Playwright 1.64,
  `channel: 'chrome'`), fresh profile per walk, 1440 × 900 and 375 × 812 (touch, mobile).
- I did not touch the main checkout or its servers on 8000/8001. At the end, 8061 and 8062 are free (`netstat`).
- Date: 2026-11-14.

## Verdict

**FAIL.** 1 high (new), 2 medium (residual), 6 low.

All earlier UI findings that block a user are fixed. H1 (old target under the new heading) is fixed. The About card is
good. But the branch adds a server crash: when the browser drops a pending `/api/*` request, the web server exits and
takes the whole app down. The app itself drops a request whenever the user switches target during a cold load. That
is the exact flow H1 was about.

```
user: type cold A ──► loading A (IRSA, 15-45 s) ──► user clicks chip B
                                     │                       │
                         app aborts fetch(A) (App.tsx:245)   B shows (cached)
                                     │
             live API answers A ──► server.js:146 pipeline(r, res) on a closed res
                                     │
                       ERR_STREAM_UNABLE_TO_PIPE (uncaught) ──► node exits ──► start.js stops all servers
                                     │
             next search: "Could not reach the server. Check the connection and the backend, then try again."
```

## New finding: high

**NH1. A target switch during a cold load crashes the server (regression from `b18ce1d`).**
- Screen and step: `/explore/`, type `Gliese 412`, press Show. Wait for "Getting the SPHEREx images…". Click the R Dra
  chip. R Dra shows. 6 s later the server is gone. The next search shows "Could not reach the server … Retry". Retry
  cannot help; only a restart of `start.js` helps.
- Reproduced 4 times on this branch:
  1. Browser walk above (`ua-crash.mjs`): "server down after 6 s".
  2. `curl -s -m 2 "http://localhost:8061/api/frames?q=Gliese+445&fov=5"`, then poll `/explore/`: down after about 18 s.
  3. Two runs of the skill's `stress-walk.mjs`: each one killed the server at its "Second target" screen (RW Aur, then
     Barnard's Star).
- Log, each time: `Error [ERR_STREAM_UNABLE_TO_PIPE]: Cannot pipe to a closed or destroyed stream at ClientRequest.<anonymous> (server.js:146:129)`, then `[web] stopped (exit 1); stopping the rest.`
- Cause in one line: `server.js:146` calls `pipeline(r, res, …)` after the browser has closed `res`. Node throws
  synchronously, and nothing catches it. On `main` the same line is `r.pipe(res)`, which does not throw. The change came
  in `b18ce1d` ("Proxy: end the browser's response when the live API dies mid-answer").
- Why high: data loss for every open tab (unsaved marks on other tabs), and the user is stuck with no recovery in the
  UI. It also hits a common action: a user who gets bored of a 30 s cold load and clicks a chip. At a demo, one click
  stops the whole app.
- `verify-ui.mjs` does not catch it: its held-request test delays the request in the browser (`page.route`), so the
  server never sees an abort.

## Earlier findings (`review-user_advocate-explore-live.md`)

| Finding | Status | Screen + step (this walk) |
|---|---|---|
| H1 old target under new heading (#26) | FIXED | R Dra → type Barnard's Star; Barnard → type Ross 128 (1440) and Lalande 21185 (375). At 1 s, 5 s, 15 s: Motion, Brightness, Your sky now, Frames are skeletons. Flipbook and Sky context say "Showing Barnard's Star until Ross 128 loads." Residuals are NL4. |
| M1 Motion in expert notation | FIXED | Motion first line, live: "It moved 9.6″ (about 1.6 pixels) north-northwest in 13 months, as its catalogue motion predicts." Ross 128: "It did not move measurably in 12 months (less than 3.2″); its catalogue motion predicts 1.4″." Honest. |
| M2 localhost link in Talk report | FIXED | Talk report ends "Link: none yet (the tool runs on my computer only; the RA and Dec above find the field)." Task tab names issue #24. |
| M3 45 s failure for a nonsense name | FIXED | `zzqx not a star`: 6.4 s cold, 2.1 s warm, both widths. Wait text "Looking up … in CDS Sesame…". Error: "No object called 'zzqx not a star' found. Try another name or type RA/Dec …" with "Edit the name". |
| M4 strong verdict on a probable artefact | PARTIAL | eps Ind B now: "the brightest survey is 1.3× the faintest (24.28 to 31.55 mJy, 105.8σ)", no "larger than the noise". But see NM1 (typed WISE 0855). |
| M5 controls below the fold at 1440 | FIXED | Toolbar at y 253-319, above the image (y 327-897). Difference reachable without scroll. |
| M6 375 result off screen, toast on image | FIXED | Chips in one scroll row. After a mark the toast sits at y 8-65 and says "See Candidates below."; image at y 234-577 is free. At 1440 it says "See the Task tab." at y 72-113. |
| M7 Barnard's Star under Gaia circles | PARTIAL (low) | Default shows about 40 circles ("All 150" toggle). The mover and ring are clear; the field is still busy at 375. |
| M8 heading differs from typed name | FIXED | "Kapteyn's Star · HD 33793", "Lalande 21185 · HD 95735". |
| M9 WISE 0855 challenge coordinate, empty center | NOT FIXED | Typed `08h55m10.831s -07d14m42.53s`: "as entered", Ring off, center empty, no epoch hint in the result. The chip text helps only chip users. See NM1. |
| L1 discoverability from the missions page | NOT TESTED | Out of this branch's scope. |
| L2 Remove has no Undo | NOT FIXED | "Candidate 2 removed." No Undo button (0 found). |
| L3 tutorial covers a shared link | NOT FIXED | Fresh profile, link with `c=`: the tutorial dialog opens over it. |
| L4 click during loading, no message | NOT TESTED | – |
| L5 "your horizon" for default Seattle | NOT FIXED | "2° above your horizon, towards the west." with Place = Seattle. |
| L6 "to … to" in report frames | FIXED | "Frames: first 2025-08-15 to 09-05, last 2026-09-22". |
| L7 Kapteyn's Star has no chip | NOT FIXED | Chips: Barnard's Star, eps Ind B, WISE 0855, RW Aur, R Dra. |
| L8 black Sky context mid-flight | NOT TESTED | – |

## New findings: medium and low

- **NM1 (medium). A typed position with nothing at the center gets a "larger than the noise" brightness verdict.**
  WISE 0855 challenge coordinates (the object moved away after 2010): "Change: the brightest survey is 10.8× the
  faintest (0.0288 to 0.3114 mJy, 3.1σ) — larger than the noise". The center is empty sky in the screenshot. A lay
  user reads "something here blinks 10×". Same class as M4. Screenshot `1440-misc-08h55m10_831s_07d14m42_53s.png`.
- **NM2 (medium, = M9).** Still no hint in the result that a 2010 coordinate of a fast mover is out of date.
- **NL1.** Talk report: "Field: Barnard's Star (Barnard's star)". The same name twice, in two cases.
- **NL2.** One fact, two numbers: Motion says "9.6″ … in 13 months"; About says "about 8.9″ per year". Both are right
  (9.6 × 12/13), but a lay reader sees a conflict.
- **NL3.** Candidate About for a field star: "The nearest Gaia DR3 star, 0.7″ away, has G = 16.9." "G = 16.9" means
  nothing to a lay person; no distance when Gaia has no good parallax. Say "brightness G = 16.9 (faint)" or similar.
- **NL4.** During a switch, the "Showing A until B loads." label is below the image (off screen at 1440 × 900) and cut
  at 375 ("Showing Barnard's Star until Lalande …"). The timeline keeps A's dates and the toggle shows A's "All 150"
  (agrees with PM L4). The dim image plus "Loading B…" heading still keep the user honest, so low.
- **NL5.** "About this star" sits in the "Data" tab. Nothing on the Task tab or result points to it. Candidates have an
  "About" disclosure, which is easy to find.
- **NL6.** The 375 nonsense-name screen shows the chip row scrolled to its end (R Draconis), so Barnard's Star is off
  screen. Small.

## About this star: lay-person judgement

Three numbered sentences, live:

- Target (Barnard's Star, 0.04 s warm): "Barnard's Star is a red dwarf (spectral type M4V) about 6.0 light-years away.
  / In our SPHEREx frames it moves about 8.9″ per year toward the north-northwest. / SIMBAD lists 924 papers about it."
  Sources: CDS Sesame / SIMBAD · Wikipedia: Barnard's Star · SPHEREx measurements (this tool).
- Mark on Barnard's Star itself: the same card (the tie to the planet is fixed).
- Mark on a field star (2.9 s): "The nearest Gaia DR3 star, 0.7″ away, has G = 16.9. / This tool measures motion and
  brightness only at the target, so compare this mark between frames by eye. / Its history is unknown here."

Clear: yes; one idea per sentence, plain words ("red dwarf", "light-years"). Honest: yes; each sentence says where it
comes from, sources are links, and the card admits what it does not know. Weak spot: the history line often falls back
to a paper count, which tells a lay person little (PM L3). Skeleton bars while loading, no layout jump seen.

## UX stress walk (`designing-ux-mechanics/stress-walk.mjs`)

Config: `web/ux-walk.json` with `baseUrl` `http://localhost:8061`, plus an "About this star (Data tab)" screen.

| # | Check | Target | Result | Detail |
|---|---|---|---|---|
| – | whole walk | Result (chip), Second target | FAIL (could not finish) | Run 1 and run 2: the server exited at "Second target" with `ERR_STREAM_UNABLE_TO_PIPE` (NH1). The walk then failed on `ERR_CONNECTION_REFUSED`. No result table was produced. |

So this branch has **no valid stress-walk table** from me. The table in `artifacts/star-info/stress-walk.md` ran against
the Vite dev server (no `server.js` proxy), so it could not see NH1.

## Manual checklist (`designing-ux-mechanics/checklist.md`)

| Item | Result | Reason |
|---|---|---|
| N1 | PASS | Back from a target returns to the previous target (verify-ui; earlier walk) |
| N2 | NOT TESTED (script crashed) | Earlier round PASS; not re-measured on this build |
| N3 | PASS | Marks use replaceState; no form re-opens on Back |
| N4 | PASS | Deep link with `c=` opens the target with its marks |
| N5 | NOT TESTED | – |
| N6 | PASS | Reload keeps target, view and marks |
| L1 | PASS | Only the tutorial dialog; never two layers |
| L2 | PASS (partial) | Esc and close button close the tutorial; backdrop NOT TESTED |
| L3 | PASS | verify-ui: focus returns to "?" |
| L4 | PASS | No confirm dialogs |
| D1 | PASS | Skeletons during a load; no false empty state |
| D2 | PASS | Cached targets show at once (R Dra 0.15 s) |
| D3 | PASS | About card grows in place; no spinner flash seen |
| D4 | FAIL (medium, via NH1) | After the crash, "Could not reach the server … Retry" is in place, but Retry cannot work until a restart |
| D5 | NOT TESTED | – |
| A1 | NOT TESTED (script crashed) | – |
| A2 | NOT TESTED (script crashed) | Search button is disabled while busy ("Searching…") |
| A3-A5 | NOT TESTED | – |
| A6 | PASS (n/a) | No costly actions |
| M1 | PASS | CLS not re-measured; no shift seen when About loads |
| M2-M5 | NOT TESTED | – |

## Shneiderman's eight rules (one note each)

- Consistency: chips, typed names and coordinates use one flow and one heading form. OK.
- Shortcuts: Space and arrows for the flipbook; Enter marks the center. Difference needs 20 Tabs from the search field;
  no key for Blink/Difference. Low.
- Informative feedback: wait text names the real step and counts seconds. Good.
- Closure: "Report copied. Paste it into your Talk post." and Talk opens in a new tab. Good.
- Simple error handling: nonsense name fails fast with "Edit the name". The crash (NH1) breaks this.
- Easy reversal: Back works; Remove has no Undo (L2).
- Internal locus of control: the user can switch target at any time, but doing so crashes the app (NH1).
- Short-term memory: the stale label and dim image say what is on screen during a load. Good.
- Accessibility: text labels on every control, no information by colour alone (badges say "Known in Gaia DR3"), no
  horizontal scroll at 375. Contrast not measured.

## Problem solved?

For the UI: yes. A first-time user now reads honest panels while a target loads, plain motion text, and a three-line
About card with sources. A volunteer gets a usable Talk report. For the run as a whole: no, until NH1 is fixed,
because one natural click stops the app for everyone.

## Agreement with phase 1

Both tech_lead and project_manager passed. Neither ran the app through `server.js` with an aborted request; the
branch's own live checks used the Vite dev server. NH1 is live behaviour that contradicts "Proxy: … a client abort
destroys the upstream request" in `b18ce1d`. I agree with PM L4 (stale timeline) and PM L2 (WISE 0855 typed coords).

## Evidence files (scratchpad, not committed)

`C:\Users\user\AppData\Local\Temp\claude\e6e349967ae79c2f\9142796b-c37a-4076-8fed-41ca7800fa56\scratchpad\`:
`ua-walk.mjs`, `ua-walk2.mjs`, `ua-talk.mjs`, `ua-misc.mjs`, `ua-crash.mjs`, `walk-1440.log`, `walk-375.log`,
`walk2-1440.log`, `walk2-375.log`, `ua-server.log` … `ua-server4.log` (each ends in the crash), `ua-shots/*.png`.
