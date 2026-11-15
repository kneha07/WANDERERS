# User advocate review: merges to main on 2026-11-15

Reviewer: user_advocate (last seat, post-merge). Scope: PR #65, #64, #66, #67.
Worktree: `.worktrees/merge-review` at `a88e63a`. No product file was changed.
I read `review-tech_lead-merges-2026-11-15.md` and `review-project_manager-merges-2026-11-15.md` first.
I do not repeat their findings. I add the user's view, and live evidence.

Users in this review:

- **Judge**: a NASA Space Apps judge with about 5 minutes. Starts at the README, clicks "Live".
- **Visitor**: a member of the public on the site, often on a phone.
- **Local user**: someone who clones the repo to try Star Fix with their own photos.

## Summary

```
PR   what                      verdict              high  medium  low
#65  SPHEREx DR1 survey stage  PASS-with-findings    0     2      2
#64  Star Fix                  FAIL                  1     1      2
#66  catalogue-survey specs    PASS                  0     0      0
#67  README accuracy           PASS-with-findings    0     1      1
```

```
README "Live" link ──► rajryadav4.github.io/wanderers ──► old build
                                                        ├─ starfix.html  404
                                                        └─ survey.html   no SPHEREx filter
local clone ──► node server.js ──► starfix.html ──► valid iPhone photo
                                                   └─► "Could not read this photo." + Try again  (server said: "Star Fix could not run")
```

## What I ran (live)

| Check | How | Result |
|---|---|---|
| Serve main | `PORT=8031 node server.js` in this worktree | up on 127.0.0.1:8031 |
| Survey, shipped data | Playwright (Chrome), 1280×900 and 375×812 | hero, filter, drawer, export read |
| Survey, SPHEREx results | Playwright route that injects 5 `spherex` objects into `leaderboard.json` and `summary.json` (the M1 case, a measured case, two error cases, a slow mover) | drawer text recorded per case |
| Home three-door hero | Playwright, desktop and phone | computed styles of the doors |
| Star Fix, own photo | Playwright upload of `star_image/20231125_203522413_iOS.heic` and of a text file named `.jpg` | see #64 H1 |
| Star Fix API | `curl -X POST --data-binary @star_image/20231125_203522413_iOS.heic http://localhost:8031/api/star-fix` | `HTTP 500 {"error":"Star Fix could not run. Start the app with start.cmd."}` |
| Star Fix, static host | Playwright route: every `/api/**` gives 404 | offline message shown, picker disabled |
| Public live site | `curl` of `https://rajryadav4.github.io/wanderers/…` | `starfix.html` 404; `survey.html` has no `fSpherex`; home has no `starfix` link |
| Skill stress walk | `stress-walk.mjs` (designing-ux-mechanics), two configs | tables below |

Screenshots are in the session scratchpad only (not committed): `survey-drawer-m1.png`, `survey-filter-empty.png`, `starfix-badfile.png`, `home-desk.png`, `survey-mobile-drawer.png`.

---

## PR #65: SPHEREx DR1 stage

**Verdict: PASS-with-findings.** With the shipped data the page is honest: the hero says "— SPHEREx check not run yet". The findings below show what a judge sees now, and what any user will see after the next publish.

### UA-65-M1 (medium): tech_lead M1 from the user's view. The drawer states a fact and shows no evidence for it

Live, with an injected row `confirmed: true, gone_from_2014: null, expected_offset: 14.0`:

```
SPHEREx 2025–26
Seen again in 2025–26, where its NEOWISE motion predicts, and gone from its 2014 spot.
Detected                         yes  signal-to-noise 14.2
Offset from the predicted spot   2.1″ ± 1.3″
Moved since 2014 (predicted)     14.0″
SPHEREx date                     2025.80
                                 <- no "Its 2014 spot" row
```

- The headline sentence (`app/survey.js:184`) says "gone from its 2014 spot". The row that would prove it is hidden, because `survey.js:208` shows it only for `true` or `false`.
- A careful user looks for the evidence of the claim and does not find it. A quick user trusts the claim. Both are wrong.
- With a measured case (`gone_from_2014: true`, 60″ move) the row "Its 2014 spot: empty now" shows. So the page can be honest; it is only the unmeasured case that is not.
- The same promise is in the page lede, for every mover: "checks that it is there (and gone from where it was in 2014)" (`app/survey.html:58`). For moves below about 40″ the program does not do that check.
- The export cannot carry the difference. `app/surveytools.js:115-116` exports `spherex_confirmed` but no "2014 spot" column. A judge who downloads the CSV gets `spherex_confirmed = true` with nothing to qualify it.
- The badge tooltip is honest ("SPHEREx sees it in 2025–26 where its NEOWISE motion predicts", `survey.js:156`). Only the drawer sentence and the lede overclaim.
- Severity: medium. Shipped data has 0 confirmed rows, so no user sees it today.

### UA-65-M2 (medium): the "SPHEREx-confirmed only" filter gives a false "nothing found"

- Live: I ticked "SPHEREx-confirmed only" on the shipped data. The page shows "0 of 1,000 candidates shown." and "No candidates match these filters." (`app/survey.js:739`).
- The URL becomes `survey.html?spherex=1`, so a shared link opens this empty list too.
- The filter is enabled, and its hint says "seen in 2025–26 where predicted" (`app/survey.html:133`). Nothing says that the SPHEREx check did not run.
- A judge reads this as "SPHEREx confirmed none of the movers". That is a false statement about the challenge feature. The truth is "not checked yet", and the hero 40 lines above says so, out of view.
- Severity: medium. The user does not get stuck (Reset works), but the user gets false information about the headline feature.

### UA-65-L1 (low): two sentences next to each other disagree

- Live drawer, shipped data: "Not looked up in SPHEREx for this build." and directly under it the fixed hint "Measured directly in SPHEREx's all-sky DR1 spectral cube (NASA/IPAC IRSA, read a few pixels at a time)" (`app/survey.html:240-241`).
- The second sentence shows for every candidate, also when nothing was measured.

### UA-65-L2 (low): raw error text, with no next step

- Live drawer: "Could not be measured: internal error: KeyError: 'flux'." and "Could not be measured: SPHEREx cube unreadable: HTTP 200 instead of 206." (`app/survey.js:198`).
- The network and time-budget cases say what happens next ("tried again at the next update"). These cases do not. With tech_lead L2 (these errors are cached for good), "tried again" would also be false for them, so the honest text is "not measured".

### What works (#65)

- Hero stat: "—" plus "SPHEREx check not run yet" (`survey.js:525`). Honest empty state.
- Badge "SPHEREx ✓": the word is in text, not colour only. Teal on a light tint, readable.
- Drawer: Escape closes it and focus goes back to the candidate button (checked for 5 rows).
- No page errors. No horizontal scroll at 375 px.

---

## PR #64: Star Fix

**Verdict: FAIL.** I agree with the #57 high from project_manager and tech_lead, and I do not repeat it. My FAIL has its own reason: H1 below.

### UA-64-H1 (high): the page hides the server's message and blames the photo

Live, `node server.js` in this worktree (README line 208 names this command as a valid way to start Star Fix):

```
curl POST /api/star-fix  ->  HTTP 500 {"error":"Star Fix could not run. Start the app with start.cmd."}
page shows               ->  "No place found from these photos."
                             "! 20231125_203522413_iOS.heic  Could not read this photo.  Try again"
```

- The server has a correct, recoverable message (`star-fix-solver.js:6`, `DOWN`). The page drops it: `app/starfix.js:17` maps every non-OK reply to `{status: "error"}`, and `starfixcore.js:57` turns that into "Could not read this photo."
- So a valid iPhone photo is reported as a bad photo. The user tries again, gets the same text, then tries other photos. Nothing on the page says the app is the problem or how to fix it.
- The same text also covers 409 (another photo is still running) and 504 (time limit). For 409, "Try again" works later; for a missing Python package it never works.
- Cause on this machine: the root `.venv` has no `pillow_heif` (tech_lead's run table says the same). `start.js` repairs that; `node server.js` does not.
- Severity: high. The user cannot complete the task, and the page gives false information about why (getting stuck).

### UA-64-M1 (medium): the home hero sends people to a door that the live site does not have

- `app/index.html` now has three equal doors: Observatory, Sky Compass, Star Fix (screenshot `home-desk.png`).
- On the public site that the README links as "Live", `starfix.html` gives 404. When the site is next deployed, the door opens a page whose picker is disabled, with "To use your own photos, start WANDERERS on a computer (start.cmd)." (checked with all `/api/**` blocked). Only the example result works there.
- The Sky Survey, which is the challenge's "large-scale discovery" and SPHEREx answer, is not a door. It is a nav link only.
- For a judge with 5 minutes, one third of the main call to action leads to a feature that is off-topic for the challenge and does not work in a browser.
- Severity: medium. This is a choice for the team. I report the cost to the judge's task.

### UA-64-L1 (low): the privacy text, from the user's view

- "Your photos stay on this computer." (`app/starfix.html:49`). For the upload this is true: the server listens on 127.0.0.1, the photo goes on stdin and is not written to disk.
- One gap: the result has "Open in OpenStreetMap" (`starfixcore.js:140`), which sends the found position to openstreetmap.org when clicked. The position is the stars' answer (to about 50 to 150 km), not the phone GPS, so the risk is small. The promise text does not say this.
- The page is also the opposite of what happened to the team's own photos (#57). A visitor who reads the repo sees place names next to a page that promises privacy. That is a trust cost, and it is the existing #57 high, not a new one.

### UA-64-L2 (low): "start.cmd" on the page too

- tech_lead L8 found "start.cmd" in the server message. The page has it as well (`app/starfix.html:47`, offline text). A Mac or Linux user gets a Windows-only step.

### tech_lead L7 from the user's view: no visible effect

- Live computed style: only the middle door has `justify-content: center`; the other two have `normal`. All three are the same size (196×65 desktop, 343×51 phone).
- Their content fills the width, so I saw no visual difference in the screenshots. Keep it at low (cosmetic).

### What works (#64)

- Picker responds at once ("Reading photo 1 of 1" within 150 ms).
- "Remove my photos" gives an Undo (Shneiderman: easy reversal).
- Example block loads with no layout shift (CLS 0.000) and is labelled "Example".
- No horizontal scroll at 375 px. Static host: picker disabled with a reason, not a silent failure.

---

## PR #66: catalogue-survey specs

**Verdict: PASS.**
`ack_zero_findings_reason`: docs and one sample CSV only; no page, command or message that a judge or visitor uses changed. The spec conflict (tech_lead M3, project_manager M1) is real, but it affects builders, not users.

---

## PR #67: README accuracy

**Verdict: PASS-with-findings.**

### UA-67-M1 (medium): the README's "Live" link shows none of today's merges

- README line 7: "**Live:** https://rajryadav4.github.io/wanderers/".
- `curl` today: `starfix.html` 404; `survey.html` has no `fSpherex` (no SPHEREx filter, drawer or hero stat); the home page has no `starfix` link.
- The README now describes Star Fix (line 208) and tells the judge to "see it live" for each row. A judge who follows the README sees an older site than the README describes.
- The README is more accurate after #67 (both earlier seats checked the numbers). This finding is about the path from the README to the product.

### UA-67-L1 (low): "Every page shows one line" is not true

- README line 47 (requirement 1): "Every page shows one line" for the SPHEREx release status.
- Live: the home page shows it ("SPHEREx Quick Release 3 · … · IRSA release check failed 15 Nov 2026New data available …"). `survey.html` and `starfix.html` have no status line.
- Small extra: in that line, "2026" and "New" run together with no space or separator.

---

## Interaction design (Shneiderman), across the changed surfaces

| Rule | Note |
|---|---|
| Consistency | Mostly good: same header, theme toggle and badges. Star Fix uses one error text for four different causes (UA-64-H1). |
| Shortcuts | Survey filters are kept in the URL, so a link works as a shortcut. Escape closes the drawer. |
| Informative feedback | Star Fix progress text is fast. The SPHEREx filter gives "no match" instead of "not run" (UA-65-M2). |
| Closure | Star Fix ends each night with one headline and a per-photo list. Good. |
| Simple error handling | Fails on Star Fix: the server's recovery step never reaches the user (UA-64-H1). Survey raw errors (UA-65-L2). |
| Easy reversal | Star Fix "Remove my photos" + Undo. Survey "Reset" clears all filters. Good. |
| Internal locus of control | User chooses photos; nothing uploads by itself. Good. |
| Short-term memory load | The SPHEREx "not run" state is only in the hero; the user must remember it when the filter is empty (UA-65-M2). |
| Clarity and honest wording | UA-65-M1, UA-65-L1. |
| Accessibility | Badge uses text plus colour. Drawer returns focus. Star Fix map has a text answer above it. I did not run a full screen-reader pass or a dark-mode contrast check. |
| Mobile | No horizontal scroll at 375 px on survey, drawer, home and Star Fix. |

## Stress walk (designing-ux-mechanics `stress-walk.mjs`, phone size, 2.5 s throttle)

Survey config (`home = /survey.html`, drawer via `#candBody .cid`, back `#dClose`, list `/data/survey/leaderboard.json`):

| # | Check | Target | Result | Detail |
|---|---|---|---|---|
| N2 | Back (system) reaches home within 2 presses | Survey candidate drawer | PASS | 0 press(es) |
| N2 | Back (on-screen) reaches home within 2 presses | Survey candidate drawer | PASS | 0 press(es) |
| N2 | Back (system) reaches home within 2 presses | Survey SPHEREx filter | PASS | 0 press(es) |
| N2 | Back (on-screen) reaches home within 2 presses | Survey SPHEREx filter | PASS | 0 press(es) |
| D1 | No empty state before the first answer | Ranked candidates | FAIL (script) | `#tEmpty` visible while loading |
| M1 | No layout shift when data lands (CLS ≤ 0.1) | Ranked candidates | PASS | CLS 0.002 |
| L1 | At most one layer over a screen | all walked steps | PASS | never more than one |

D1 judgement: **false positive, PASS**. The page reuses `#tEmpty` as its loading slot. While loading it reads "Loading the ranked list…" (`app/survey.js:726`), not an empty-state message. This D1 is not a high.

Home and Star Fix config (`home = /`):

| # | Check | Target | Result | Detail |
|---|---|---|---|---|
| N2 | Back (system) reaches home within 2 presses | Star Fix from home door | PASS | 1 press(es) |
| N0 | Every step can be done | Sky Survey from nav | FAIL (config) | `a[href='survey.html']` is inside the closed phone menu |
| D1 | No empty state before the first answer | Star Fix example | PASS | loading shown |
| M1 | No layout shift when data lands (CLS ≤ 0.1) | Star Fix example | PASS | CLS 0.000 |
| L1 | At most one layer over a screen | all walked steps | PASS | never more than one |

N0 judgement: my config error (at phone width the nav link is in the menu). The link works at desktop width. Not a finding.

No send action was configured: Star Fix sends through a file input, which the script cannot drive. I tested it by hand (below).

### Manual checklist

| # | Result | Note |
|---|---|---|
| N1 | PASS | Drawer close and browser back return to the list. |
| N3 | NOT TESTED | No form submit on these pages. |
| N4 | PASS | `survey.html?spherex=1` opens with the filter set. |
| N5 | PASS | Focus returns to the candidate button after Escape. |
| N6 | PASS | Filters are in the URL; reload keeps them. |
| L2 | PASS | Escape, ✕ and scrim all call `closeDrawer` (`survey.js:1000-1001`). |
| L3 | PASS | Focus returns to the trigger. Focus into the drawer not checked. |
| L4 | PASS | No confirm dialogs. Remove uses Undo. |
| D2 | NOT TESTED | No cache-first behaviour to test. |
| D3 | PASS | CLS 0.002 and 0.000. |
| D4 | FAIL | Star Fix: errors are in place with Try again, but they do not say what to do and give the wrong cause (UA-64-H1). |
| D5 | NOT TESTED | Offline mode not run. Static-host mode PASS. |
| A1 | PASS | Star Fix row shows "reading" within 150 ms. |
| A2 | PASS (code) | One solve at a time on the server (409). Not double-tapped live. |
| A3 | PASS | Failed photo keeps its row with Try again. |
| A4 | NOT TESTED | No optimistic actions on these pages. |
| A5 | NOT TESTED | Leaving mid-solve not tried. |
| A6 | NOT TESTED | No costly action. |
| M1–M5 | NOT TESTED | No live data or transitions in the changed screens, except M1 above. |

High-rule check: N2, N3, L1, D1 (after judgement), A2 have no FAIL.

## Things I did not check

- A successful own-photo solve (the local venv lacks `pillow_heif`; this is the H1 path).
- Dark mode contrast, screen reader output, and Sky Compass.
- The survey with a real SPHEREx publish (none exists; I injected data).
