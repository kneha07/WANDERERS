# User advocate re-review, round 2: PR #97 at f7d15e5

Reviewer seat: user_advocate (independent, last seat, not the author). Date: 2026-11-15.
PR: kneha07/WANDERERS #97, branch `feature/compass-pullout-bars`.
Pinned head: `f7d15e5` (committed, not pushed). Previous reviewed head: `c9aa6d7`.
Previous review: `artifacts/review-user_advocate-pr-97-c9aa6d7.md` (FAIL: H1 partly fixed, new N1, N2).

## Verdict: PASS

| Finding | Status at f7d15e5 |
|---|---|
| H1 back leaves the compass (round 1) | **Fixed** on every layer in `LAYERS`. |
| H2 layers stack, Esc misses the Learn menu (round 1) | **Fixed** (still). |
| H3 double tap logs twice (round 1) | **Fixed** (still). |
| N1 × and Esc leave the compass (round 2, regression) | **Fixed.** |
| N2 aim bar is not a layer (round 2, not new in #97) | **Not fixed. Out of scope.** Moved to open issue #108. |

I pass the PR because every High that #97 caused is fixed with live evidence. One High stays open by the contract rule: N2, an N2 FAIL on the aim bar. It existed before #97. Issue #108 ("Sky Compass: back during aim mode or the drag-the-sky bar leaves the compass") is OPEN and tracks it. The owner accepted it as a follow-up. If the owner wants a strict rule that "no N2 FAIL is on the screen at merge", the verdict changes to FAIL on #108 alone.

## Method

```
git archive f7d15e5 app ──► scratchpad/pin/app ──► python http.server 127.0.0.1:8805   (pinned evidence)
worktree app/ ─────────────────────────────────► 127.0.0.1:8004                          (first run)
                                                         │
     Playwright MCP, 390 x 844, index.html first, then compass.html?debug=1&go=1&intro=skip&cam=0
     &at=2026-11-15T06:00:00Z&lat=47.6&lon=-122.3&sky=eye
     page.goBack() = system back · keyboard Escape · real clicks on ×, Done, 🎓, 🔎, "/"
     designing-ux-mechanics stress-walk.mjs (Playwright 1.64.1), same config as round 2
```

- The worktree changed again during this review. At 20:26:45 local time, `app/learn.js` and `app/compass.html` got uncommitted edits (`learn.js?v=20261118g`, a guard in `open()`). `app/compass.js` did not change after f7d15e5.
- Some of my first runs on port 8004 may have loaded that edit. To pin the evidence, I exported f7d15e5 (`compass.js?v=20261118l`, `learn.js?v=20261118f`) and ran every check again on port 8805. All tables below come from the 8805 run. The 8004 run gave the same results.
- I did not review the uncommitted edit.
- Desktop Chromium only. No real phone and no touch hardware. Swipe-down was sent as synthetic `TouchEvent`s. The phone test stays owed in #93.
- No page errors (`pageerror`) during the full walk.

## Stress walk (pinned f7d15e5, 390 x 844)

| # | Check | Target | Result | Detail |
|---|---|---|---|---|
| N2 | Back (system) reaches home within 2 presses | Learn menu | PASS | 1 press(es) |
| N2 | Back (system) reaches home within 2 presses | Time machine (from menu) | PASS | 1 press(es) |
| N2 | Back (system) reaches home within 2 presses | Quiz (from menu) | PASS | 1 press(es) |
| N2 | Back (system) reaches home within 2 presses | Search pane | PASS | 1 press(es) |
| N2 | Back (system) reaches home within 2 presses | Search then Learn menu | PASS | 1 press(es) |
| N2 | Back (system) reaches home within 2 presses | Search then Quiz | PASS | 1 press(es) |
| N2 | Back (system) reaches home within 2 presses | Info sheet (top bar) | PASS | 1 press(es) |
| L1 | At most one layer over a screen | all walked steps | PASS | never more than one |

8 PASS, 0 FAIL. The 3 rows that failed at c9aa6d7 (Time machine, Quiz, Search then Quiz, all from the menu) now PASS.

History of this table: 357b8af 0 PASS / 10 FAIL → c9aa6d7 5 PASS / 3 FAIL → f7d15e5 8 PASS / 0 FAIL.

## Live walk (pinned f7d15e5)

"compass:-" means the compass with no layer open. "INDEX" means the page left `compass.html` and showed `index.html`. A correct row closes one layer for each press and then leaves in one more press.

| Start state | Actions | Result |
|---|---|---|
| Nothing open | back | INDEX (1 press) |
| Time machine from 🎓 | back, back | learnPanel → compass:- → INDEX |
| Time machine from 🎓 | Esc, back | learnPanel → compass:- → INDEX |
| Time machine from 🎓 | Close ×, back | learnPanel → compass:- → INDEX |
| Quiz from 🎓 | back, back | learnPanel → compass:- → INDEX |
| Quiz from 🎓 | Close ×, back | learnPanel → compass:- → INDEX |
| Tour, Infrared, Sky log, Candidates from 🎓 | back, back | each: learnPanel → compass:- → INDEX |
| Learn menu | back, back | learnMenu → compass:- → INDEX |
| Learn menu | Esc, back | learnMenu → compass:- → INDEX |
| Search from "/" | back, back | searchPane → compass:- → INDEX |
| Search, then 🎓 | back, back | learnMenu only → compass:- → INDEX |
| Star sheet (sky tap) | back, back | details → compass:- → INDEX |
| Star sheet | Done, back | details → compass:- → INDEX |
| Star sheet → Webb | back, back | webb → compass:- → INDEX |
| Star sheet → Webb | Esc, back | webb → compass:- → INDEX |
| Star sheet → Webb | ×, back | webb → compass:- → INDEX |
| Learn menu, then sky tap | back, back | details (menu closed) → compass:- → INDEX |
| Time machine from 🎓, then sky tap | back ×3 | learnPanel+details → learnPanel → compass:- → INDEX |
| Time machine from 🎓, then ⓘ sheet | back ×3 | learnPanel+info → learnPanel → compass:- → INDEX |
| Info ×, then search in the same task | back, back | searchPane → compass:- → INDEX |
| Info ×, then search in the next task (drop in flight) | back, back | searchPane → compass:- → INDEX |
| 🎓 tapped 9 times fast | back, back | learnMenu → compass:- → INDEX |
| "/" then Esc, 5 times fast | back | INDEX (1 press: no left-over entry) |
| 🎓 → Time machine → ×, 4 times fast | back | INDEX (1 press: no left-over entry) |
| Search "Vega", Enter (picks the star) | back | INDEX (1 press) |
| Star sheet, swipe down 160 px | back | INDEX (1 press) |
| Quiz mid-round | back, wait 3 s, back | compass:-, `mode` stays `null`, no new round → INDEX |
| Star sheet open, then back | URL `star=` | `63 Ceti` before and after (the star stays in the URL) |
| "I saw it": double-click, then click | sky log | `{"63 Ceti":{…,"n":1}}` |
| Aim bar (⬆ North → "Vega") | back | **INDEX** (#108, out of scope) |
| Learn menu open, then reload | back, back | 1st back: no visible change; 2nd: INDEX (Low, as in round 2) |

## Per-finding status

### H1 / N1 (back, Esc and × leave the compass): FIXED

- All three exits (system back, Esc, ×) now close the top layer and keep the user on the sky. This is true for every Learn mode opened from the 🎓 menu and for the Webb sheet opened from the star sheet.
- A normal back with nothing open still leaves the page in one press. No back press is lost after a layer closes by ×, Done, swipe, Esc or a fast open and close.
- New test coverage: `test/browser/realsky.mjs` now opens a mode through the menu (`data-mode="log"`) and checks details → Webb. I did not run that suite in this round.

### H2 (layers stack): FIXED

Stress walk L1 PASS. Only one layer opens at a time, except that a Learn mode stays under one sheet, as the design states.

### H3 (double tap logs twice): FIXED

`n` stays `1`. The log date is the local calendar date (`2026-11-15` in the local evening).

### N2 (aim bar not a layer): NOT FIXED, out of scope (#108)

Aim bar open → back → `index.html`. Esc does nothing. This is the same as round 2. Issue #108 is OPEN.

## New findings

### High

None.

### Medium

None.

### Low

- **L-a (carried over).** After a reload with a layer open, the first back press does nothing visible.
- **L-b (carried over).** Webb replaces the star sheet, so back from Webb goes to the sky, not to the star. This follows the "one layer at a time" rule. Owner decision.
- **L-c (static reading, not reproduced).** In f7d15e5, `open()` checks only `opening !== me` after `await ready()`. If the user closes a tour or quiz while it shows "Loading the sky…", `close()` sets `mode = null` but does not change `opening`. When loading ends, `startQuiz()` or `startTour()` still runs with no mode. Its 100 ms timer can then run with the panel hidden, and a later `close()` returns early because `mode` is null. I could not reproduce it: the star data loads before the 🎓 menu is usable, even with a 4 s delay on `data/` requests. The uncommitted edit in the worktree (`|| mode !== m`) targets this case. It is not part of f7d15e5.

## Shneiderman notes (changes since c9aa6d7)

| Rule | Note |
|---|---|
| Consistency | Good now. Back, Esc, ×, Done and swipe close the same top layer on every layer walked. The aim bar (#108) is the one exception. |
| Internal locus of control | Fixed. No visible control navigates away from the compass. |
| Easy reversal | Unchanged. Closing a layer is always one action. |
| Short-term memory load | Good. One layer at a time, one history entry for each layer. |
| Informative feedback, closure, shortcuts, errors | Unchanged by this diff. |

## Checklist items touched by this fix

| # | Result | Evidence |
|---|---|---|
| N1 | PASS | Back from every walked layer returns to the sky. Aim bar is out of scope (#108). |
| N2 | PASS (in scope), FAIL (aim bar, #108) | Stress walk 7/7 N2 PASS. |
| N6 | PASS (Low note) | One dead back press after a reload (L-a). |
| L1 | PASS | Stress walk L1 PASS. |
| L2 | PASS | ×, Esc, back and swipe agree. |
| A2 | PASS | Double tap logs once. |
| Others | NOT TESTED | Not in the scope of this diff. |

## Not done

- No review of the uncommitted worktree edit made at 20:26:45 (`learn.js?v=20261118g`).
- `test/browser/realsky.mjs` and `test/compass-flows.test.js` were not run in this round (the worktree tests carry uncommitted edits).
- No real-phone test (#93): Android back gesture, iOS swipe-back, touch swipe-down.
- I wrote only this file. No commit, no push, no code change. I deleted my Playwright snapshot and console files.
