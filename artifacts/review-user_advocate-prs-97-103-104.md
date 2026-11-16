# User advocate review: PRs #97, #103, #104

Reviewer seat: user_advocate (independent, last seat, not the author). Date: 2026-11-15.
Base: `integrate/2026-11-15c` @ `3873d3a`. I read the tech_lead and project_manager files first. I do not repeat their findings.

## Summary

| PR | Pinned head | Verdict | High | Medium | Low |
|---|---|---|---|---|---|
| #97 compass pull-out bars, Learn modes | `357b8af22b22bc7dbc1f0c959bd7af00bc543a3b` | **FAIL** | 3 | 5 | 6 |
| #103 NASA HEASARC stars | `ece4f42e54bc80912a9bd9db1c4d3ca15b4d6cdf` | PASS | 0 | 0 | 0 |
| #104 deploy guide and script | `9cbe006e175d60dc1339b8bf9ed0e7626dc5f7d9` | PASS | 0 | 0 | 3 |

The #97 FAIL comes from the review contract: a FAIL on N2, L1 or A2 is High. The first two (back button, layer stacking) are real problems for a phone user at night. The third (A2) is a local double count. Its real impact is low. The owner decides if the merge waits.

## Method and live evidence

```
git archive 4c68163 (tech_lead merged tree: base + #97 + #103 + #104) ──► scratch folder
        │
        ├─► python -m http.server 8791  (static, the same as GitHub Pages / the Worker)
        ├─► Playwright MCP, 390 x 844, ?at=2026-11-15T06:00:00Z&lat=47.6&lon=-122.3&go=1&intro=skip&cam=0&sky=eye
        │      (a desktop browser: no motion sensors, no camera, mouse clicks; some taps sent as synthetic pointer events)
        ├─► designing-ux-mechanics stress-walk.mjs (Playwright 1.64.1 in the scratch folder)
        └─► node scripts/deploy.js  (no argument, a bad argument, check)
```

- I did not change the worktree. All runs used a scratch copy.
- I did not test on a real phone. Touch swipes, the iOS home gesture, wake lock, the camera stop and restart, and the night-time calibration flow stay owed in **#93**.
- I did not run `node scripts/deploy.js pages` or `cloudflare`. Both act on live systems.

---

## PR #97: Sky Compass pull-out bars, hover names, camera power, Learn modes

Pinned SHA: `357b8af22b22bc7dbc1f0c959bd7af00bc543a3b`. Verdict: **FAIL** (contract rule: High on N2, L1, A2).

### Job to be done

A first-time visitor on a phone at night wants to: see the sky clearly, find a WANDERERS target, and learn something. The PR makes the sky cleaner and adds good teaching content (the time machine is clear and gives good feedback). But the new layers do not obey the back button, they can stack, and the main target list is now hidden behind a small grabber.

State map (what each exit does today):

```
            ┌──────────── sky (bars hidden) ────────────┐
            │  grabber top  grabber bottom  🎓   🔎      │
            └──┬───────────────┬─────────────┬────┬─────┘
               │tap/swipe      │tap/swipe    │    │tap or "/"
               ▼               ▼             ▼    ▼
          top bar         bottom bar      Learn  Search pane ──(× / Esc in input)──► sky
                          (🎓 hidden!)    menu ──(tap 🎓 again only)──► sky
                                           │ pick mode
                                           ▼
                                      Learn panel ──(× / Esc)──► sky
  system BACK from ANY layer above ───────────────────────────────► leaves the compass
```

### Stress walk result (merged tree, 390 x 844)

Command: `node stress-walk.mjs ux-walk.json --out out` (config: home = AR view with no layer open; layers = `.learn-menu`, `.learn-panel`, `.search-pane`, `.sheet`, each `:not([hidden])`).

| # | Check | Target | Result | Detail |
|---|---|---|---|---|
| N2 | Back (system) reaches home within 2 presses | Learn menu | FAIL | not home after 5 presses (left app or stuck) |
| N2 | Back (system) reaches home within 2 presses | Time machine | FAIL | not home after 5 presses (left app or stuck) |
| N2 | Back (system) reaches home within 2 presses | Quiz | FAIL | not home after 5 presses (left app or stuck) |
| N2 | Back (system) reaches home within 2 presses | Search pane | FAIL | not home after 5 presses (left app or stuck) |
| L1 | At most one layer over a screen | Search then Learn menu | FAIL | 2 layers open after {"click":"#learnBtn"} |
| N2 | Back (system) reaches home within 2 presses | Search then Learn menu | FAIL | not home after 5 presses (left app or stuck) |
| L1 | At most one layer over a screen | Search then Quiz | FAIL | 2 layers open after {"click":"#learnBtn"} |
| L1 | At most one layer over a screen | Search then Quiz | FAIL | 2 layers open after {"click":"#learnMenu [data-mode=quiz]","pause":2500} |
| N2 | Back (system) reaches home within 2 presses | Search then Quiz | FAIL | not home after 5 presses (left app or stuck) |
| N2 | Back (system) reaches home within 2 presses | Star sheet (bottom bar) | FAIL | not home after 5 presses (left app or stuck) |

0 PASS, 10 FAIL. The screenshot for each N2 FAIL is a blank page: the first back press left the compass. "Star sheet" is a baseline row: the old sheets have the same defect before #97. The script has no lists or sends for this screen, so D1, M1, A1 and the scripted A2 did not run. I tested A2 by hand (below).

### Manual checklist

| # | Result | Evidence |
|---|---|---|
| N1 | FAIL | Browser back with the Time machine open (year −14k) went to `index.html`, not to the sky. |
| N2 | FAIL | See the table. |
| N3 | NOT TESTED | No submit flow in this PR. |
| N4 | PASS | `?target=…&star=…` links open the compass with the target picked. |
| N5 | NOT TESTED | No scrolled list behind a layer. |
| N6 | PASS (partial) | The bar state survives a reload (localStorage). An open Learn mode does not (acceptable). |
| L1 | FAIL | See H2. |
| L2 | FAIL | See H1 and M5. |
| L3 | FAIL (Low) | Opening a Learn mode does not move focus into the panel. Closing it does not return focus to 🎓. The search pane does move focus into its input. |
| L4 | PASS | No confirm dialog. |
| D1 | PASS | Quiz and tour show "Loading the sky…". Candidates shows "Loading the survey candidates…". |
| D2 | NOT TESTED | Needs a second visit with a slow network. |
| D3 | NOT TESTED | Needs a throttled network. |
| D4 | FAIL (Low) | Candidates error text says "try again", but the panel has no Retry button. See L4. |
| D5 | NOT TESTED | Offline. The tech_lead M1 on #104 covers an offline risk. |
| A1 | PASS | Bars, menu, panel and "I saw it" change at once on click. |
| A2 | FAIL | See H3. |
| A3, A4, A6 | NOT TESTED / not applicable | No network send, no optimistic update, no costly action. |
| A5 | NOT TESTED | |
| M1, M2 | PASS | Time machine updates year and pole-star text in place. |
| M3 | PASS | Bars slide out the way they came in. |
| M4 | NOT TESTED | |
| M5 | PASS (code) | `flyTo` honours `reduced`. The nudge and bar transitions do not check reduced motion (Low, not raised). |

### High

**H1. System back leaves the compass from every new layer (N2, N1, L2 FAIL).**
- Evidence: stress walk rows above. Live: Time machine open → `page.goBack()` → `index.html`. No `popstate`, `pushState` or `hashchange` handler exists in `app/*.js` at the merged tree (`grep -n "popstate\|pushState\|hashchange" app/*.js` gives nothing).
- User impact: on Android the back gesture is the normal way to close a panel. One back press drops the user out of the compass. To come back they must press Go, allow the location again and calibrate again, outdoors, in the dark. The time-machine year and the quiz score are lost.
- Scope: the old sheets already had this defect. #97 adds four new layers (Learn menu, Learn panel, Search pane, swipe-closable sheets) and adds Esc and swipe-down to close, but not back. So the inconsistency grows.

**H2. Layers stack, and the Learn menu has no normal way to close (L1 FAIL).**
- Search pane + Learn menu + Learn panel can be open together (stress walk rows; screenshots show two × buttons, one at the top and one at the bottom). `app/compass.css`: `.learning` hides `.search-btn` but not `.search-pane`.
- With the Learn menu open, a tap on the sky (the usual way to dismiss a menu) picks a star and opens the full star sheet. The menu stays open under the sheet. After Esc closes the sheet, the menu is still open (live check: `learnMenu.hidden === false`).
- Esc does not close the Learn menu (`app/learn.js` closes only an open `mode`). Only a second tap on 🎓 closes it.
- User impact: on a small phone screen at night, panels pile up and cover the sky the user came to see. It is not clear which × closes what.

**H3. "I saw it" counts a double tap as two sightings (A2 FAIL).**
- Evidence: double-click on `#dLog` → `wanderers.skyLog` = `{"20 Ceti":{…,"n":2}}`. The sky log shows "2×". `app/learn.js` `log()` adds 1 on every call. A tap after the label changes to "✓ In your sky log" adds 1 again.
- Real impact is low: the data stays on the phone and reaches no other person. It is High only by the contract rule. The count is false information.

### Medium

**M1. 🎓 disappears while the bottom bar is open, and the open state is remembered.** `app/compass.css`: `.ar.bottom-open .learn-btn, .ar.bottom-open .learn-menu { display: none }`. `app/compass.js` stores `wanderers.bottom-open`. A user who likes the bottom bar open never sees the Learn modes again, on any later visit. The bottom bar has no link to them. Live: screenshot with the bottom bar open shows no 🎓.

**M2. The main job (find a target) is hidden, and the first-visit hint is likely missed on a phone.** The target list and "Pick a target" now sit behind the bottom grabber. The hint is a 3 × 1 s bounce (`.pull.nudge i { animation: … 3 }`). On a phone with sensors, `afterIntro()` opens the full-screen calibration 300 ms after the sky appears (`showCalibration`), so the bounce runs behind it and ends before the user sees the sky. `wanderers.barsSeen` is saved at page load (`app/compass.js:914`), even if the user never reaches the sky, so the hint never comes back. Confirm on a phone (#93).

**M3. Pull tabs are small and the bottom tab sits in the iOS home-gesture zone.** Live sizes at 390 x 844: top tab 76 × 24 px, bottom tab 76 × 30 px (both under the 44 px minimum). The bottom tab is at y = 814 to 844, the bottom edge of the screen, with no `env(safe-area-inset-bottom)` offset (`.pull-bottom { bottom: 100% }` on a guide moved down by 100%). On an iPhone, a swipe up there goes to the system home gesture, not to the tab. Cold hands or gloves at night make small targets harder. Confirm on a phone (#93).

**M4. The sky log stores the UTC date, so evening sightings in the Americas show the next day.** `app/learn.js` `log()` uses `new Date().toISOString().slice(0, 10)`. Live: the machine's local date was 15 Nov, in the evening. The log showed "2026-11-16". Night use is the main use, so for users west of Greenwich many entries get the wrong date.

**M5. Close actions are not consistent (L2).** Esc with a Learn mode open closes the mode and also resets the zoom to 1× (two `keydown` handlers, `app/compass.js` and `app/learn.js`). Esc does not close the search pane unless focus is in its input. Esc and a tap outside do not close the Learn menu. Swipe-down closes sheets but not the Learn panel. Back closes nothing (H1).

### Low

- **L1. No undo for "I saw it".** The sky log has no way to remove an entry. A wrong tap stays.
- **L2. Two magnifier icons mean two things.** The 🔎 button is star search. The "🔍 Candidates near here" menu item is a different feature.
- **L3. Desktop users get no "drag" hint in the quiz and the tour.** `.learning .guide { display: none }` hides the "drag the sky or use the arrow keys" line. The quiz says only "Point the crosshair at it."
- **L4. "Candidates near here" downloads 2.0 MB with no warning, and its error has no Retry.** `app/data/survey/leaderboard.json` is 2,064,875 bytes. On weak signal outdoors this is slow. The error text says "try again", but the user must close and reopen the mode.
- **L5. 🎓 and 🔎 have no visible text.** Screen readers get `aria-label`. A first-time sighted user must guess what 🎓 does.
- **L6. The top grabber overlaps the first telemetry row when the top bar is open** (screenshot at 390 x 844).

### Shneiderman and accessibility notes (#97)

| Rule | Note |
|---|---|
| Consistency | Weak. Back, Esc, ×, tap outside and swipe each close a different set of layers (H1, M5). |
| Shortcuts | Good. `/` opens search. Arrow keys look around. Bar state is remembered. |
| Informative feedback | Good in the time machine (year, pole star) and the tour ("Follow the arrow: turn right 11°"). The quiz "found" style never shows (tech_lead L1). |
| Closure | Good. The tour ends with "Finish". The quiz ends with a score and "Play again". |
| Simple error handling | Fair. Loading and error text exist. No Retry on Candidates (L4). |
| Easy reversal | Good for the time machine ("Today", and closing restores the sky). Weak for the sky log (L1). |
| Internal locus of control | Weak. One back press throws the user out (H1). A tap on the sky to close a menu opens a sheet (H2). |
| Short-term memory load | Fair. The user must remember that 🎓 lives only when the bottom bar is closed (M1). |
| Clarity and hierarchy | The sky is cleaner. The core target list is less visible (M2). |
| Accessibility | Pull tabs are real buttons with `aria-expanded` and a focus ring: good. Hit areas are small (M3). Badges use ★/☆ and colour, so not colour alone: good. The Learn panel uses `aria-live="polite"`. |

---

## PR #103: Sky Compass stars from NASA HEASARC Hipparcos

Pinned SHA: `ece4f42e54bc80912a9bd9db1c4d3ca15b4d6cdf`. Verdict: **PASS**. No new findings.

- Live: the drawn sky renders on the merged tree. The ⓘ sheet credit (`#skyCredit`) shows "Stars: Hipparcos (ESA) via NASA HEASARC; names and distances: HYG Database v4.1 …".
- The prior seats already cover the credit gaps (README, the star sheet "HYG v4.0" line) and the tolerance question.

`ack_zero_findings_reason`: #103 changes data and credit text only. It adds no control, no flow and no error path. The drawn sky looks the same to the user (0 magnitude changes, median shift 0″). The one user-visible change, the credit line, is present and correct in the ⓘ sheet.

---

## PR #104: Deployment guide and script

Pinned SHA: `9cbe006e175d60dc1339b8bf9ed0e7626dc5f7d9`. Verdict: **PASS**.

Surface: a CLI and a Markdown guide for a maintainer.

Live runs (scratch copy of the merged tree):

```
node scripts/deploy.js            → "Usage: node scripts/deploy.js check | pages | cloudflare"  exit 2
node scripts/deploy.js deploy     → same usage line                                              exit 2
node scripts/deploy.js check      → "app/ has its entry pages."                                  exit 0
```

The usage line and the `check` result are short and clear. The "Pages is not on" message gives the admin step (tech_lead L3 covers the wrong-cause case).

One-pass walk of `docs/deploy.md` (from reading; `pages` and `cloudflare` not run):

```
Before every deploy ──► git switch main && git pull ──► deploy.js check ──► pages | cloudflare ──► "Check a deploy" table
                         ▲ fails in a worktree (L1)                         ▲ gh run watch race (L2)    ▲ no way to see which commit is live (L3)
```

### Low

- **L1. `git switch main` fails from a worktree.** This repo requires all work in `.worktrees/`, and `main` is checked out in the main checkout (`git worktree list`). From any worktree, step 2 of "Before every deploy" stops with "already used by worktree". Git's message is clear, so the maintainer can recover. The guide does not say "run this in the main checkout".
- **L2. `gh run watch` right after `pages` can miss the new run.** `gh workflow run` returns before the run registers. An immediate `gh run watch` asks the user to pick a run, or finds none. The guide does not say to wait a few seconds or use `gh run list --workflow pages.yml`.
- **L3. The "Check a deploy" table cannot show which commit is live.** It checks status codes and the page title only. After a deploy, the maintainer cannot confirm that the new code is live (this links to project_manager L1, the stale deploy claim).

Shneiderman notes (#104): consistent verbs (`check`, `pages`, `cloudflare`); clear feedback and exit codes; `check` runs first by itself, which prevents a broken publish; reversal is documented (`npx wrangler@4 rollback`) for Cloudflare, but the guide has no undo step for Pages (re-run the workflow on an older commit). Not raised as a finding.

---

## Not done

- No real-phone test. #93 is still owed. It must cover: swipe on both tabs, the iOS home-gesture conflict (M3), the nudge behind calibration (M2), back gesture on Android (H1), wake lock and the camera restart (tech_lead L3).
- No throttled or offline run (D2, D3, D5).
- I wrote only this file. No commit, no push, no code change.
