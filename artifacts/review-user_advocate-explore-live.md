# User-advocate review: WANDERERS "Explore any patch" live mode

- Seat: user_advocate (independent; I did not write this code). Phase 2, after tech_lead PASS and project_manager PASS.
- Repo: kneha07/WANDERERS, local `main` at `94e563b`. Live stack: `node start.js` (WANDERERS :8000 → proxy → live API :8001).
- Date: 2026-11-14.
- Method: live walks in headless Chrome (Playwright 1.64 from `web/node_modules`, `channel: 'chrome'`), fresh browser profile per walk, at 1440 × 900 and 375 × 812 (touch, mobile). The Claude Browser pane could not draw (window hidden), so I did not use it. Every number below comes from these walks, not from the docs.

## Verdict

**FAIL.** 1 high, 9 medium, 8 low.

The tool does the job for a volunteer who has a warm cache and reads the panels with care. The tutorial, the error text for a bad name, the mark → Gaia check → report flow, Back, and the share URL all work. One mechanics defect gives false information: while a new target loads, four panels show the previous target's data under the heading "Loading <new target>…". A small fix closes it (see H1). After that fix, the review would pass.

```
missions page ──"Explore any patch (live) →"──► /explore/ + tutorial (3 steps, Skip / Esc)
      │                                              │
      │                                    home: 5 chips + field guide
      │                                              │ chip / name / RA-Dec
      │                                              ▼
      │                          loading (5–45 s cold, <1 s warm)   ◄── H1: panels below show the OLD target
      │                              │                 │
      │                          result            error "Could not find …" + examples + Retry (45 s)
      │                              │ click / Enter on flipbook
      │                              ▼
      │                          mark → "Known in Gaia DR3 …" or "? Unexplained …"
      │                              │ Copy share link / Report on Talk (copies report)
      │                              ▼
      └──────────── Back ◄──── localhost URL in the report (M2)
```

## Live evidence

| Step | 1440 px | 375 px |
|---|---|---|
| Missions → "Explore any patch (live) →" | Link found and opens `/explore/`. It is a small text link under the coordinate "Search" button. | Same |
| First visit | Tutorial opens, 3 steps, "Skip tutorial", Back, Next, "Start exploring"; Esc closes | Same; fits the screen |
| 5 chips (warm cache) | 476–528 ms each to result | 474–596 ms |
| Gaia circles in the flipbook | Barnard 151, RW Aur 110, WISE 0855 29, R Dra 22, eps Ind B 21 | Same; Barnard's field is covered by circles |
| `Wolf 359` (cold) | 35.1 s; counter "1 s … 15 s"; text "first load … up to a minute" | `Ross 128` cold: 16.2 s |
| `08h55m10.831s -07d14m42.53s` | 1.1 s; label "as entered"; Ring off; nothing at the center | – |
| `zzqx not a star` / `qwerty12345` | Error after **45.5 s**; while waiting, the text says "Fetching SPHEREx images of zzqx not a star from IRSA" | 45.2 s |
| `banana` | 28 s; resolves to "Banana" at 17h45m −28°50′ (Galactic Centre) | – |
| `180 0` (empty sky) | 23.7 s; result "as entered", 3 frames | – |
| Empty input | Show button is disabled | Same |
| Difference | URL gets `view=diff`; caption explains the dipole | Same |
| Looks | Smooth, Infrared colour, Realistic each show an honesty label ("False-colour infrared · smoothed, with glow, for display · measurements use raw pixels") | Same |
| Mark (Enter on flipbook, then a click) | Toast "Candidate 1 marked at … See the Task tab."; badge "✓ Known in Gaia DR3: 4810594479418041856, G 8.1, 1.2″ away"; blank spot "? Unexplained: nearest Gaia DR3 star is 24.9″ away" | Same; toast covers the image |
| Copy share link | Toast "Link copied …"; clipboard = `http://localhost:8000/explore/?q=Kapteyn%27s+Star&fov=5&c=…` | Same |
| Report on Talk | Opens the Backyard Worlds Talk page; toast "Report copied. Paste it into your Talk post."; report ends `Link: http://localhost:8000/…` | Same |
| Share link in a new browser profile | Both marks restored; tutorial opens over it first; Back → `/explore/` | Same |
| Remove candidate | Toast "Candidate 2 removed."; no Undo | Same |
| Back × 4 after Kapteyn → RW Aur → eps Ind B | RW Aur → Kapteyn (with mark) → `/explore/` → leaves app | Same |
| Your sky now | Seattle default; Sydney: "14° above your horizon, towards the east", rise/set times in local zone; bad lat/lon: "Latitude is −90 to 90 and longitude is −180 to 180." | Same |
| Sky context | 120° Milky Way → black frame at 17° (tiles loading) → 20′ with the blue 5′ square, in about 8 s | Same |
| Click the flipbook while a cold target loads | No mark, no message | – |
| Page errors on `/explore/` | none | none |

### Stress walk (`designing-ux-mechanics/stress-walk.mjs`, run by me against :8000)

Config: `web/ux-walk.json` with `baseUrl` set to `http://localhost:8000`. Exit 0.

| # | Check | Target | Result | Detail |
|---|---|---|---|---|
| N2 | Back (system) reaches home within 2 presses | Result (chip) | PASS | 1 press(es) |
| N2 | Back (system) reaches home within 2 presses | Second target | PASS | 2 press(es) |
| N2 | Back (system) reaches home within 2 presses | Candidate marked | PASS | 1 press(es) |
| N2 | Back (system) reaches home within 2 presses | Tutorial layer | PASS | 0 press(es) |
| D1 | No empty state before the first answer | Frames (deep link) | PASS | skeleton, cache or loading shown |
| M1 | No layout shift when data lands (CLS ≤ 0.1) | Frames (deep link) | PASS | CLS 0.030 |
| A1 | Press shows a response within 100 ms | Search button | PASS | 9 ms |
| A2 | A double tap sends once | Search button | PASS | 1 request(s) |
| L1 | At most one layer over a screen | all walked steps | PASS | never more than one |

9 PASS, 0 FAIL. The script's D1 check loads from home only. It does not test a second target loaded over a first one, which is where H1 occurs.

### Manual checklist (`designing-ux-mechanics/checklist.md`)

| # | Result | Reason |
|---|---|---|
| N1 | PASS | Back from a target lands on the previous target, then home |
| N2 | PASS | Stress walk; at most 2 presses |
| N3 | PASS (n/a) | No in-app submit; the Talk report opens an external page |
| N4 | PASS | A shared deep link in a fresh profile: Back goes to `/explore/` home |
| N5 | NOT TESTED | Scroll restore after Back not measured |
| N6 | PASS | Share link restores target and marks; verify-ui shows reload keeps them |
| L1 | PASS | Stress walk |
| L2 | PASS (partial) | Esc, close and system Back close the tutorial; backdrop tap NOT TESTED |
| L3 | PASS | verify-ui: focus returns to "?"; I saw `data-autofocus` on Next |
| L4 | PASS | No confirm dialogs anywhere |
| D1 | **FAIL** | Second target loaded over a first: Motion, Brightness, Your sky now and Frames show the old target under "Loading Wolf 359…" (H1) |
| D2 | PASS (partial) | Warm targets show in under 0.6 s; no data age is shown (the disk cache never expires, tech_lead M1 / PM M6) |
| D3 | PASS | CLS 0.030; elapsed-seconds counter, no spinner flash |
| D4 | PASS (partial) | Bad name: in place, icon, examples, Retry, input kept. But it takes 45 s (M3). API-down state NOT TESTED by me (see `artifacts/ux-walk/explore-live-server-down.png`) |
| D5 | NOT TESTED | Offline not simulated |
| A1 | PASS | 9 ms |
| A2 | PASS | 1 request |
| A3 | PASS | The failed search keeps the typed text |
| A4 | PASS (n/a) | No optimistic server action |
| A5 | PASS | A new search during a load replaces it; the final target is correct (GJ 1061 walk) |
| A6 | PASS (n/a) | Reporting is a manual paste on an external site |
| M1 | PASS | Stress walk |
| M2 | PASS (n/a) | No live counters |
| M3 | PASS (n/a) | No page transitions |
| M4 | NOT TESTED | – |
| M5 | NOT TESTED by me | `artifacts/ux-mechanics.md` reports PASS |

## Findings

### High

**H1. While a new target loads, four panels show the previous target as if it were the new one.**
- Screen and step: `/explore/` with a result on screen (R Draconis), type `Wolf 359`, press Show. Cold load: 35 s.
- What the user sees: the heading says "Loading Wolf 359…" and only the flipbook is dimmed. Below it, Motion shows R Dra's 9-frame table, Brightness says "Saturated in surveys 1–9", Frames lists R Dra's 9 epochs, and Your sky now says "63° above your horizon, towards the north-west … never sets from here". That last sentence is R Dra's (Dec +66°). Wolf 359 (Dec +7°) does set from Seattle. No label says "previous target".
- Evidence: `App.tsx:184` (`const r = state.result`) keeps the old result during `loading`; the panels at `App.tsx:779-798` render `r` when it is set; `index.css:342` dims only `.viewer[data-status='loading'] .sky`. The Task rail, by contrast, shows "Load a target to mark candidates." Screenshot: scratchpad `walk/p1/1440-20-wait-Wolf_359.png`.
- Why high: the skill rule for D1 (false information before the first answer) and the brief's "honesty of labels". A lay person who scrolls during the wait reads a false altitude and false motion for the star that they asked about.
- Suggested fix: during `loading`, show the skeletons for these panels, or dim them and label them "Previous target: R Dra".

### Medium

**M1. The Motion panel is in expert notation only.** Live text: "ΔRA cos δ (″) · east ←", "Measured: 9.6″ toward PA 348°", "measured centroid ±1σ", "(wings)", and a table of pixel coordinates. East is on the left (sky convention) with no note. A member of the public cannot tell from this whether the star moved as predicted. Suggested fix: one plain sentence first, for example "Moved 9.6″ (about 1.6 pixels) north in one year; the catalogue predicts 11.2″. They agree." Keep the chart and table for experts.

**M2. The share link and the Talk report hold a `localhost` URL.** Clipboard and report: `Link: http://localhost:8000/explore/?q=Kapteyn%27s+Star&fov=5&c=…`. The toast says "Link copied. It holds the target, the view and your marks." Nobody else can open that link. A volunteer who pastes the report into Backyard Worlds Talk publishes a dead link. The coordinates in the report still work, so the report is usable. Suggested fix: while the tool is local, label it "Link works on this computer only" and leave it out of the Talk report, or link to the public WANDERERS page plus the coordinates. (This is the user-facing side of PM M1.)

**M3. A name that does not exist takes 45 s to fail, and the wait text is wrong.** `zzqx not a star` 45.5 s, `qwerty12345` 45.2 s, at both widths. During the wait the page says "Fetching SPHEREx images of zzqx not a star from IRSA. The first load of a target takes up to a minute". It is resolving the name, not fetching images. Then "Retry" repeats the same 45 s for an input error. Suggested fix: name the real step ("Looking up the name…"), fail a name lookup faster, and offer "Edit the name" instead of Retry for a not-found result. (Same root cause as tech_lead M4/L3, the Sesame retry budget.)

**M4. A strong "larger than the noise" brightness verdict on a probable artefact.** Epsilon Indi B, default series: "Change: 98% (397.8σ) from 13.1 to 35.97 mJy — larger than the noise · D2 1.10–1.65 µm". A 2.7× change in a brown dwarf binary at D2 is almost certainly the known D1/D2 scattered light (#5), not a real blinker. The σ counts only statistical errors. A lay user reads this as "this object blinks". Also, "98%" is peak-to-peak over the mean; for WISE 0855 "98% … from 0.3096 to 0.8602" reads as "98% brighter" while the ratio is 2.8×. Suggested fix: name D1/D2 as less reliable next to the verdict, and say "max/min = 2.7×" in words.

**M5. At 1440 × 900 the flipbook controls are below the fold.** The image spans y 222–862 px; the Play, Blink/Difference and Look toolbar starts below 900 px. To press Difference, the user scrolls, and then the top half of the image is under the sticky header (scratchpad `walk/p2/1440-02-diff.png`). Space and arrow keys exist for play and step, but not for Blink/Difference. This is the common laptop size and the demo size. Suggested fix: fit image + toolbar in one 900 px screen (smaller image or toolbar beside it), or add a key for Blink/Difference.

**M6. At 375 px the result is mostly off screen, and the toast covers it.** After a chip tap the page does not scroll. The 5 stacked chips push the flipbook to y 598–941 on an 812 px screen. After a mark, the toast (y 688–796) covers most of the visible image, the place of the next tap. The toast says "See the Task tab", which is at y 1499, two screens down. Screenshot: scratchpad `walk/p2m/375-viewport-after-mark.png`. Suggested fix: collapse the chips into one row or a menu after a target loads, scroll to the flipbook, and put the toast away from the image.

**M7. Barnard's Star, the first chip and the tutorial's lead example, is covered by Gaia circles.** 151 circles at 1440 and at 375. At 375 the field is a mat of circles; a mover would be hard to see. Gaia is on by default. I rate this medium, not low (PM L3), because it is the first impression of the first chip. Suggested fix: default Gaia off, or show only stars brighter than a limit with a "show all 150" toggle.

**M8. The heading shows a different name than the user typed.** `Kapteyn's Star` → heading "HD 33793"; `GJ 1061` → "L 372-58"; the chips show "V* RW Aur", "* eps Ind B". The report also says "Field: HD 33793". A first-time user thinks the search found the wrong star. Suggested fix: show the typed name as the heading, and the SIMBAD main identifier as a subtitle ("= HD 33793 in SIMBAD").

**M9. The challenge coordinate for WISE 0855 shows an empty center with no hint.** Typing `08h55m10.831s -07d14m42.53s` gives "as entered", Ring disabled, and nothing visible at the center (the all-detector stack hides it). There is no hint that the object has moved since 2010 or that the D6 stack is in Expert settings. A volunteer concludes "nothing here". Agrees with PM M3 and tech_lead's centroid note.

### Low

- **L1. Discoverability from the missions page.** "Explore any patch (live) →" is a small underlined link under the coordinate Search button. A first-time user can miss it. A button in the header (next to "Sky Compass") would find more users.
- **L2. Remove has no Undo.** "Candidate 2 removed." with no Undo; marks use `replaceState`, so Back does not bring it back. Re-marking at the exact spot is hard.
- **L3. The tutorial covers a shared link.** A recipient who opens a shared link with marks gets the tutorial first. Consider skipping it when the URL holds `c=`, or opening it after the result.
- **L4. A click on the flipbook during loading does nothing, with no message.** Tested with GJ 1061.
- **L5. "Your sky now" says "your horizon" for Seattle by default.** A user elsewhere reads a false "your". Say "From Seattle (change place)" until the user picks a place.
- **L6. Report text: "frames 2025-08-10 to 09-20 to 2026-08-07 to 09-07".** Two "to"s read badly; use "from … until …" or a dash.
- **L7. Field guide names Kapteyn's Star, but no chip loads it.** Consistency: add it as a chip, or link the guide image to it.
- **L8. Sky context shows a black frame mid-flight** (about 17°, tiles loading) before the target appears. Brief, but it looks like a failure.

## Shneiderman's eight rules

| Rule | Note |
|---|---|
| Consistency | Good: one toolbar, same label style, Back/Esc/close agree. Weak: heading name ≠ typed name (M8); field guide names a target with no chip (L7). |
| Shortcuts | Space, ←/→, Enter to mark at center. No key for Blink/Difference (M5). Share URL is a good shortcut for repeat visits. |
| Informative feedback | Good: elapsed-seconds counter, one toast per action, Gaia badge with ✓/?. Bad: stale panels during load (H1); wrong wait text for a name lookup (M3). |
| Closure | Good: mark → badge → copy → "Report copied. Paste it into your Talk post." Bad: the pasted link is dead for others (M2). |
| Error prevention and handling | Good: Show disabled when empty; bad lat/lon message says the valid range; name error gives examples and keeps input. Bad: 45 s to learn a name is unknown; Retry is the wrong recovery (M3). |
| Easy reversal | Back works across targets; Reset display in Expert settings. Remove has no Undo (L2). |
| User in control | Autoplay can be paused; looks and overlays are toggles; a new search cancels the old one. The tutorial over a shared link takes control first (L3). |
| Low memory load | Task steps are always visible in the rail; badges spell the result. At 375 the toast points to a tab two screens away (M6); Motion needs the user to remember astronomy notation (M1). |

Clarity and hierarchy: the home page and tutorial are clear and plain. Result pages are dense; at 375 the user scrolls about 7 screens (doc height 5751 px). Accessibility: contrast and focus are measured in `artifacts/ux-mechanics.md` §3 and I did not re-measure them. No information is by colour alone (✓/? glyphs, dashed ring, triangle markers). The toast is `role="status"`, `aria-live="polite"`.

## Problem solved?

For the Backyard Worlds volunteer: mostly yes. Type a position, flip, mark, see "Known in Gaia DR3 … 1.2″ away" or "? Unexplained", open SIMBAD/Gaia/WiseView, copy a report. That is the real job and it works in a few clicks on a warm cache. The gaps are the dead share link (M2), the WISE 0855 trap (M9) and the slow failure for a bad name (M3).

For a first-time member of the public: the tutorial and field guide teach "mover", "dipole" and "blinker" well, and the Looks with honesty labels deliver the "realistic star look" request without hiding that it is display-only. The "Google Earth style" fly-in and "angle from my location" work and read in plain words ("14° above your horizon, towards the east"). But the data panels speak to astronomers (M1, M4), the headings show catalogue names (M8), and the stale panels during a cold load (H1) can tell them something false.

## Agreement with phase 1

- **Agree** with PM M3 / tech_lead centroid note (WISE 0855 typed coordinates) → my M9, seen live.
- **Agree** with tech_lead M4 / L3 (Sesame and Gaia retry budget) → my M3; the user cost is 45 s per typo, measured live.
- **Agree** with PM M1 (not public) and add its user-facing effect: the share link and report carry `localhost` (M2).
- **Agree** with PM L2 (only cached timings in round 2). My cold timings: Wolf 359 35.1 s, Ross 128 16.2 s, `180 0` 23.7 s. All are inside the "up to a minute" promise, with a live counter, so I add no finding.
- **Disagree in severity** with PM L3 (150 Gaia ghosts): medium (M7), because it is the first chip and the tutorial's lead example.
- **Not in phase 1:** H1 (stale panels during load) is new. Both phase-1 reviews and the stress walk's D1 test loaded from home, where no previous result exists.
- I did not re-check geometry, security or docs, as the brief says.

## Evidence files

The walk scripts, logs and screenshots are in the session scratchpad, not in the repo. I was told to write only this file. Copy them into `artifacts/ux-walk/` if the team wants them kept:

`C:\Users\user\AppData\Local\Temp\claude\e6e349967ae79c2f\9142796b-c37a-4076-8fed-41ca7800fa56\scratchpad\walk\` (`walk1.mjs`, `walk2.mjs`, `walk3.mjs`, `walk4.mjs`, `p1-1440.log`, `p2-1440.log`, `p1-375.log`, `p2-375.log`, `p1/`, `p2/`, `p1m/`, `p2m/`, `stress-walk.md`).
