# User advocate review: Star Fix (`feature/star-fix`, diff `1275527..HEAD`)

Reviewer: user_advocate (independent, runs last). Date: 2026-11-15.
Live build: `http://localhost:8010` (this branch). Browser: Playwright Chromium.
Screenshots: `artifacts/star-fix/ux-review/`. Stress walk: `artifacts/star-fix/ux-review/stress-walk/stress-walk.md`.

## Verdict: PASS

No high finding. Four medium findings and eight low findings.
The job is done: four original iPhone photos give a place sentence, a ±65 km claim and a GPS check in about 5 s.

## Job to be done

A person with original iPhone night-sky photos wants to see where on Earth they were, from the stars, and to trust how exact it is.

```
home --door 3--> Star Fix [example] --choose 4 HEIC--> rows "waiting" (<=100 ms)
     --> "Reading photo N of 4" --> headline + "Usually right to about 65 km." + GPS check + map
     --> Remove my photos --> example + "Photos removed. Undo" (8 s)
```

| Part of the job | Live result |
|---|---|
| Find the feature | Home door "Find where you were". Visible at 1366 px and up. Below the fold at 1280 x 720 (M1). |
| Get the place | PASS. "The stars place these photos about 130 km south-east of Geelong, Australia." ~5 s for 4 photos. |
| Trust how exact | Text PASS ("Usually right to about 65 km.", "✓ Your phone's GPS recorded a spot 61 km from here."). Map does not show it (M2). |
| Recover from a wrong file | PASS. Each refused file has its own row with a mark and words. Retry works. |

## What I ran live

| Step | Width | Result |
|---|---|---|
| Open `/` | 1280, 1000, 1366x768, 1280x720, 1440, 1920, 390 | Doors 3 across only from ~1366 px. Stacked at 1280 and below. |
| Open `/starfix.html`, first visit | 1280, 390 | Example renders, one primary button, "Your photos stay on this computer." |
| Upload 4 x `20260614_*.heic` | 1280, 390 | Rows "reading/waiting" at 102 ms (U1 PASS). Result after ~5 s. All 4 "Used · stars of ...". |
| Upload a duplicate | 1280 | Ignored. No feedback (L1). |
| Upload `notes.txt` | 1280 | No request sent (U8 PASS). Row "! notes.txt This file is not a photo." Count became "4 of 5 photos used" (L2). |
| Upload 32 MB `big.jpg` | 1280 | No request. "This file is too large (30 MB limit)." |
| Upload random-bytes `fake.jpg` | 1280 | Server row "This file is not a photo." |
| Block `/api/star-fix`, upload 2023 HEIC | 1280 | "Could not read this photo. Add it again." plus "Try again" button (L3). Try again: focus stays on the row, then success "near San Tung Chung Hang, Hong Kong". |
| Remove my photos, Undo | 1280 | Acts at once, focus to the file input, "Photos removed. Undo". Undo restores all rows. Undo is gone after 8 s. |
| Block `/api/health` | 1280 | Button disabled, "To use your own photos, start WANDERERS on a computer (start.cmd)." Example stays. U6 PASS. |
| Keyboard Tab | 1280 | Skip link, logo, theme, file input, "Which photos work?", OSM link, "4 photos used", "How does this work?". Focus ring 2 px on all. Enter and Space on the input open the file chooser. |
| Light theme | 390 | Same layout, readable (`starfix-390-light-done.png`). |
| Drag and drop | - | NOT TESTED live (Playwright cannot drop OS files here). Code shows "Drop to add" (`app/starfix.js:171`). |
| Screen reader | - | NOT TESTED with a real reader. Live regions present: progress `aria-live="polite"`, Undo `role="status"`, canvas `role="img"` with headline label. |

## Findings

### Medium

| # | Screen and step | What happens | Concrete fix |
|---|---|---|---|
| M1 | Home `/`, 1280 x 720 and any width below ~1366 px | The three doors stack (`app/home.css:22`, container ≤ 600 px). At 1280 x 720 the Star Fix door is at y 830-886: fully below the fold. A laptop visitor does not see the new feature. Phase-1 PM F1 said 900-1100 px; live, it is up to 1280 px (`home-1280.png`, `home-1000.png`). | Lower the stack point (for example 3 columns down to a ~520 px container) or let the hero text column grow so the doors fit 3 across at 1280 px. |
| M2 | Star Fix, result map (all widths) | The 65 km circle is ~9 px radius at 1280 px and smaller on phone. It is the same size as the reticle. The GPS ring overlaps it (`map-zoom-1280.png`). The map does not show "how exact". The planned "circle tightens" motion is not visible. Confirms TL M1 / PM F3. | Size the map window from the radius (for example 8 x radius wide) or add a scale bar ("100 km"). |
| M3 | Star Fix, "N photos used" list, add another file | U4 is broken. A `<details>` that the person opened or closed returns to the default when any file is added. Repro A: all used, open the list, add a duplicate: it closes. Repro B: list open because one failed, close it, add a duplicate: it opens again. Same element (not re-created). Code: `app/starfix.js:37`, `:68-69`. | Make the person's toggle stick: set `touched` from the summary click, not from the async `toggle` event compare. |
| M4 | Star Fix, first visit, 390 px, no font cache | Stress walk M1 FAIL: CLS 0.154. At ~300 ms "or drop them here" wraps to a second line (font swap), and the note, "Which photos work?" and the example move down ~34 px. 0.002 at 1280 px. | Reserve the second line in `.sf-upload` at narrow width (or always put the hint on its own line on phone), or use a metric-matched fallback font. |

### Low

| # | Screen and step | What happens | Concrete fix |
|---|---|---|---|
| L1 | Add a file that is already in the list | Silently ignored (U2 dedupe). The person sees no change and may think the click failed. | One status line: "Already added: <name>." |
| L2 | Add a non-photo or a refused file | It joins the current night: "4 of 5 photos used" on 14 June, and later "1 of 2 photos used" under 26 November 2023. A text file is counted as a photo of that night. | Show refused files in a separate "Not added" list, outside the night count. |
| L3 | Network or server error row | Text says "Add it again." The button beside it says "Try again". Two instructions for one action. | "Could not read this photo." + "Try again" button. |
| L4 | "This file is not a photo." / "This file is too large (30 MB limit)." | Says what is wrong, not what to do (spec 10.0 rule 4). | Add "Choose the original .heic or .jpg night-sky photo." |
| L5 | Only refused files in the list | The example is replaced by the largest text on the page: "No place found from these photos yet." "Yet" is false when nothing is pending. | Drop "yet" when no row is pending, and point to the rows ("See below for what to do."). |
| L6 | Remove my photos | Undo disappears after 8 s with no way to extend (WCAG 2.2.1). Keyboard and reader users may miss it. | Keep Undo until the next action, or 20 s. |
| L7 | Result for the 2023 photo | "near San Tung Chung Hang, Hong Kong" for a 150 km radius. The small place name means little to most people. | When the radius is large, prefer the largest city inside it. |
| L8 | No server, light theme | Disabled button: white text on pale blue, low contrast (`starfix-1280-noserver.png`). The line beside it explains, so impact is low. | Use the muted text token on the disabled button. |

### Phase-1 items checked

| Item | Live result |
|---|---|
| TL L7: no right gutter at 375 px | Not reproduced at 390 px. Canvas 16 px left and 16 px right of the 375 px content area (15 px is the desktop scrollbar). The full-page screenshot crops the scrollbar and looks edge-to-edge; the viewport shot does not (`starfix-390-dark-reading.png`). |
| PM F1: doors stack 900-1100 px | Worse: up to 1280 px. See M1. |
| TL M1 / PM F3: tiny circle | Confirmed. See M2. |
| TL L1: headline counts "Not used" photos | Not reproduced live (the test photos have no outlier). Kept as TL L1. |

## Automated stress walk (`stress-walk.mjs`, 390 px)

Config: home `/` ready `a[href='starfix.html']`; screen = door 3; list = `/starfix.html`, api `/api/health` delayed 2.5 s, empty `#offline:not([hidden])`.

| # | Check | Target | Result | Detail |
|---|---|---|---|---|
| N2 | Back (system) reaches home within 2 presses | Star Fix (door 3) | PASS | 1 press(es) |
| D1 | No empty state before the first answer | Star Fix health / example | PASS | skeleton, cache or loading shown |
| M1 | No layout shift when data lands (CLS ≤ 0.1) | Star Fix health / example | FAIL | CLS 0.154 (font swap, see M4) |
| L1 | At most one layer over a screen | all walked steps | PASS | never more than one |

No send button exists (upload is a file input), so A1/A2/N3 were not configured. A1 and A2 were checked by hand below.

## Manual checklist

| # | Result | Reason |
|---|---|---|
| N1 | PASS | One page. Back from Star Fix returns to home. |
| N2 | PASS | 1 press (stress walk). |
| N3 | PASS | No flow in history; no `pushState`. |
| N4 | PASS | Direct link `/starfix.html` opens the page; logo goes home. |
| N5 | NOT TESTED | No list-to-detail navigation on this page. |
| N6 | PASS | Reload shows the example, as spec 10.4 says (nothing is stored). |
| L1 | PASS | No layers. |
| L2 | PASS | No layers to close. |
| L3 | PASS | No layers; Remove moves focus to the file input; Try again keeps focus in its row. |
| L4 | PASS | No `confirm()`. Remove uses Undo. |
| D1 | PASS | Offline line shows only after health fails. |
| D2 | NOT TESTED | No cache by design. |
| D3 | FAIL | M4: 0.154 CLS on phone first visit. No spinner flash seen. |
| D4 | PASS | Each error in its row, with mark and words; network error has Try again. Wording gaps L3, L4. |
| D5 | PASS | No server: example stays, button disabled, one line says what to do. |
| A1 | PASS | Rows appear at 102 ms after choose. |
| A2 | PASS | Same file twice sends once (dedupe). No double send seen. |
| A3 | PASS | Failed request keeps the file; Try again succeeded. |
| A4 | NOT TESTED | No optimistic action. |
| A5 | NOT TESTED | Leaving mid-read was not tried. |
| A6 | PASS | Remove is cheap and has Undo. |
| M1 | PASS | Rows keep order; in-place updates. |
| M2 | PASS | Count "4 of 5 photos used" updates in place. |
| M3 | NOT TESTED | No page transitions. |
| M4 | NOT TESTED | Circle motion not observable at this map scale (M2). Code cancels the frame before a new one (`app/starfix.js:114`). |
| M5 | NOT TESTED | Code checks `prefers-reduced-motion` (`app/starfix.js:8`); not exercised. |

## Shneiderman rules

| Rule | Note |
|---|---|
| Consistency | Doors use the Sky Compass button style. Error text mixes "Add it again" and "Try again" (L3). |
| Shortcuts | Multi-select and drop on the whole page. Enough for a one-task page. |
| Informative feedback | Rows in 100 ms, "Reading photo N of M", progress bar. Duplicate add gives none (L1). |
| Closure | Progress ends; headline and "4 photos used" close the task. |
| Simple error handling | Per-row reason and retry. Two messages lack a next step (L4). |
| Easy reversal | Remove with Undo, no dialog. Undo has an 8 s limit (L6). |
| Internal locus of control | The list re-opens or re-closes on its own when a file is added (M3). |
| Short-term memory | Answer first; numbers and rows below and folded. Nothing to remember. |
| Clarity and hierarchy | Headline is the one strong element. Map is quiet but does not show precision (M2). |
| Accessibility | Focus ring on all controls; marks plus words, not colour only; canvas has a text label. Real reader not tested. |

## Screenshots

`artifacts/star-fix/ux-review/`: `home-1280.png`, `home-1000.png`, `home-1366x768.png`, `home-390-doors.png`, `starfix-1280-first.png`, `starfix-1280-done.png`, `map-zoom-1280.png`, `starfix-1280-nonphoto.png`, `starfix-1280-removed.png`, `starfix-1280-errors.png`, `starfix-1280-retry.png`, `starfix-1280-noserver.png`, `focus-upload-1280.png`, `starfix-390-dark-first.png`, `starfix-390-dark-reading.png`, `starfix-390-light-done.png`.
