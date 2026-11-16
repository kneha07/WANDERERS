# User advocate re-review: PR #97 at c9aa6d7

Reviewer seat: user_advocate (independent, last seat, not the author). Date: 2026-11-15.
PR: kneha07/WANDERERS #97, branch `feature/compass-pullout-bars`.
Pinned head: `c9aa6d7` (local, not pushed). Previous reviewed head: `357b8af`.
Previous review: `main:artifacts/review-user_advocate-prs-97-103-104.md` (FAIL, H1 to H3).

## Verdict: FAIL

| Earlier High | Status at c9aa6d7 |
|---|---|
| H1 back leaves the compass (N2) | **Not fixed** for the main Learn path and for Webb. Fixed for the menu, search, info and star sheets. |
| H2 layers stack, Esc misses the Learn menu (L1) | **Fixed.** |
| H3 double tap on "I saw it" logs twice (A2) | **Fixed.** |

New High: the **Close** button and **Esc** on a Learn mode (or on the Webb sheet) now take the user out of the compass. Before this commit, they closed the layer. This is a regression.

## Method

```
git archive c9aa6d7 app ──► scratchpad/pin/app ──► python http.server 127.0.0.1:8805
                                                         │
     Playwright MCP, 390 x 844, index.html first, then compass.html?debug=1&go=1&intro=skip&cam=0
     &at=2026-11-15T06:00:00Z&lat=47.6&lon=-122.3&sky=eye
                                                         │
     page.goBack() = system back · keyboard Escape · real clicks on ×, Done, 🎓, 🔎, "/"
     designing-ux-mechanics stress-walk.mjs (Playwright 1.64.1)
```

- I first ran the checks on the given server (port 8004, worktree `app/`). At 20:15:14 local time, after those runs, the worktree got uncommitted edits to `app/compass.js`, `app/learn.js` and `app/compass.html` (`?v=20261118l`). These edits are not part of c9aa6d7. I did not review them.
- To pin the evidence, I exported c9aa6d7 (`compass.js?v=20261118k`) and ran every check again on port 8805. The results are the same on both servers.
- "INDEX" below means the back or the close left `compass.html` and showed `index.html`.
- Desktop Chromium only. No real phone, no touch hardware, no motion sensors. Swipe-down was sent as synthetic `TouchEvent`s. The phone test stays owed in #93.
- `node --test test/compass-flows.test.js`: 28 pass, 0 fail.

## Stress walk (pinned c9aa6d7, 390 x 844)

Config: home = compass with no `.learn-menu`, `.learn-panel`, `.search-pane`, `.sheet` or `.aim-bar` open. Layer selector = the same five classes, each `:not([hidden])`.

| # | Check | Target | Result | Detail |
|---|---|---|---|---|
| N2 | Back (system) reaches home within 2 presses | Learn menu | PASS | 1 press(es) |
| N2 | Back (system) reaches home within 2 presses | Time machine (from menu) | FAIL | not home after 5 presses (left app or stuck) |
| N2 | Back (system) reaches home within 2 presses | Quiz (from menu) | FAIL | not home after 5 presses (left app or stuck) |
| N2 | Back (system) reaches home within 2 presses | Search pane | PASS | 1 press(es) |
| N2 | Back (system) reaches home within 2 presses | Search then Learn menu | PASS | 1 press(es) |
| N2 | Back (system) reaches home within 2 presses | Search then Quiz | FAIL | not home after 5 presses (left app or stuck) |
| N2 | Back (system) reaches home within 2 presses | Info sheet (top bar) | PASS | 1 press(es) |
| L1 | At most one layer over a screen | all walked steps | PASS | never more than one |

5 PASS, 3 FAIL (was 0 PASS, 10 FAIL at 357b8af). The three FAIL rows open the mode the only way a user can: tap 🎓, then tap a mode.

## Live walk (pinned c9aa6d7)

| Start state | Action | Result |
|---|---|---|
| Nothing open | back | INDEX in 1 press (correct) |
| Learn menu | back, back | menu closes, then INDEX (correct) |
| Learn menu | Esc, back | menu closes, then INDEX (correct) |
| Search from "/" key | back, back | search closes, then INDEX (correct) |
| Search, then 🎓 | (state) | only the Learn menu is open (correct) |
| Star sheet from a sky tap | back, back | sheet closes, then INDEX (correct) |
| Info sheet, closed by × | back | INDEX in 1 press: no left-over entry (correct) |
| Info sheet, swipe down 160 px | back | sheet closes, then INDEX in 1 press (correct) |
| 🎓 tapped 9 times fast | back, back | menu closes, then INDEX (correct) |
| "/" then Esc, 5 times fast | back | INDEX in 1 press (correct) |
| Learn menu open, tap a star | (state), back | menu closes, sheet opens; back closes the sheet (correct) |
| Time machine opened by `WanderersLearn.open("time")`, then a sky tap | back, back, back | sheet closes, panel closes, then INDEX (correct) |
| Quiz opened by `WanderersLearn.open("quiz")`, mid-round | back, wait 3 s | panel closes, `mode` stays `null`, no round comes back (#106 timer: correct) |
| **Time machine from 🎓 menu** | back | **INDEX** |
| **Time machine from 🎓 menu** | Esc | **INDEX** |
| **Time machine from 🎓 menu** | tap Close (×) | **INDEX** |
| **Quiz from 🎓 menu** | back | **INDEX** |
| **Webb sheet from the star sheet** ("Show the nearest Webb frame") | back | **INDEX** |
| **Webb sheet from the star sheet** | Esc | **INDEX** |
| **Webb sheet from the star sheet** | tap × (`#wClose`) | **INDEX** |
| **Aim bar** (sight check: ⬆ North sheet, tap "Vega") | back | **INDEX** |
| Aim bar | Esc | nothing happens (aim bar stays) |
| Learn menu open, then page reload | back, back | 1st back does nothing visible, 2nd back leaves |
| "I saw it": double-click, then click again | sky log | `{"63 Ceti":{…,"n":1}}`, label "✓ In your sky log" (correct) |

History state that explains the failures (port 8004 run, same code):

```
tap 🎓                 history.state = {"layer":"learnMenu"}   stack = [learnMenu]
tap "Time machine"     history.state = null                    stack = [learnPanel]   ◄── no entry for the panel
back / Esc / Close     the stack thinks one entry exists, so it goes back one entry ──► leaves compass.html
```

## Per-High status

### H1. Back leaves the compass: NOT FIXED (partly fixed)

- Fixed: Learn menu, search pane, info sheet, star sheet (sky tap or search), swipe-closed sheets, Learn modes when one layer opens over another.
- Not fixed: a Learn mode opened from the 🎓 menu (time machine, quiz, and the other modes that use the same `open()`), and the Webb sheet opened from the star sheet. One back press shows `index.html`. Stress walk: 3 FAIL rows. Live walk: rows in bold.
- Cause, from the evidence: both paths hide one layer and show the next layer in the same task (`app/learn.js:73` in c9aa6d7: `$("learnMenu").hidden = true; $("learnPanel").hidden = false;`; `app/compass.js:736`: `$("details").hidden = true; $("webb").hidden = false;`). The observer queues `history.go(-1)` for the hidden layer and then calls `pushState` for the shown layer. The async `go(-1)` lands after the push. The new layer is on `layerStack` with no history entry.
- Test gap: `test/browser/realsky.mjs:296` opens the time machine with `WanderersLearn.open("time")`. That call does not open the menu first, so it does not hit the failing path. No check covers details → Webb.
- User impact: the 🎓 menu is the only user path into a Learn mode. On Android, back from any Learn mode drops the user out of the compass, as before this commit.

### H2. Layers stack, Esc misses the Learn menu: FIXED

- Stress walk L1: PASS on every walked step ("never more than one").
- Search, then 🎓: the search closes. Learn menu, then a star tap: the menu closes and the sheet opens. Esc closes the Learn menu (the second Esc resets zoom only).
- The double Esc handler is gone (`app/learn.js` no longer has its own `keydown`).
- Note: Esc now has a new defect on two paths (see N1). That defect is a new finding, not H2.

### H3. Double tap on "I saw it" logs twice: FIXED

- Double-click, then a third click on `#dLog`: `n` stays `1`.
- `log()` now uses the local date (`toLocaleDateString("sv")`). This also fixes the earlier M4 (UTC date in the sky log). The log showed `2026-11-15` in the local evening.

## New findings

### High

**N1. Close (×) and Esc on a Learn mode or the Webb sheet now leave the compass (regression; N2, L2).**
- Evidence: live walk rows "Time machine from 🎓 menu → Close (×) → INDEX", "→ Esc → INDEX", "Webb sheet → × → INDEX", "→ Esc → INDEX". At 357b8af these controls closed the layer and kept the user on the sky.
- Same cause as H1: the layer is on `layerStack` with no history entry. A × close drops one entry (`history.go(-1)`). Esc calls `history.back()` (`closeTopLayer`). Both leave the page.
- User impact: the visible Close button on every Learn mode takes the user out of the Sky Compass. The user loses the view, the time-machine year and the quiz score. To come back they must press Go, allow location and calibrate again, outdoors at night. This is worse than H1: a user who never uses the back gesture still hits it. It is also a false signal: the button says Close but it navigates away.

**N2. The aim bar (sight check) is not a layer, so back leaves the compass and Esc does nothing (N2 FAIL; not new in #97).**
- Evidence: ⬆ North sheet → tap "Vega" → aim bar open (`role="dialog"`). Back → INDEX. Esc → aim bar stays. `app/compass.js:939` `LAYERS` lists `.sheet`, `skyCard`, `searchPane`, `learnMenu`, `learnPanel`, not `aimBar`.
- The north sheet itself is correct: it drops its entry when the aim bar opens.
- This is High only by the contract rule (any N2 FAIL). It existed before #97 and was not in the earlier review. The owner can move it to a follow-up ticket. Impact on a phone: a back gesture mid-calibration exits the compass and loses the calibration in progress.

### Medium

None new. The earlier M1, M2, M3 and M5 were not in the scope of this fix and I did not re-test them, except: M4 is fixed (local date), and M5 is mostly fixed for back and Esc (they now close the same top layer), except on the N1 paths.

### Low

- **L-a. After a reload with a layer open, the first back press does nothing visible.** The old `{layer}` history entries survive the reload, but the new page has an empty stack. The second press leaves. A reload with a layer open is rare.
- **L-b. Webb from the star sheet replaces the sheet.** After the N1 fix, back from Webb will go to the sky, not to the star sheet the user came from. This follows the stated "one layer at a time" rule. A user may expect back to return to the star. Owner decision.

## Shneiderman notes (changes since 357b8af only)

| Rule | Note |
|---|---|
| Consistency | Better. Back, Esc, × and swipe now close the same top layer on most paths. N1 breaks it on the Learn modes and Webb. |
| Shortcuts | Unchanged. "/" opens search and back closes it. |
| Informative feedback | Unchanged. |
| Closure | Unchanged. |
| Simple error handling | Not applicable to this diff. |
| Easy reversal | Better: a double tap no longer adds a false sighting. Still no undo in the sky log (earlier L1). |
| Internal locus of control | Worse on N1 paths: the Close button navigates away from the page. |
| Short-term memory load | Better: only one layer at a time, so the user does not track two × buttons. |
| Accessibility | `aria-expanded` on 🎓 resets when another layer closes the menu (good). Focus return on close not re-tested. |

## Checklist items touched by this fix

| # | Result | Evidence |
|---|---|---|
| N1 | FAIL | Back from a Learn mode (menu path) and Webb goes to `index.html`. |
| N2 | FAIL | Stress walk: 3 FAIL. Aim bar also FAIL (N2 above). |
| N6 | PASS (Low note) | Reload keeps bar state. One dead back press after reload (L-a). |
| L1 | PASS | Stress walk L1 PASS. |
| L2 | FAIL | × and Esc leave the page on the N1 paths. |
| A2 | PASS | Double tap logs once. |
| M5 | NOT TESTED | No change to motion in this diff. |
| Others | NOT TESTED | Not in the scope of this diff. |

## Not done

- No review of the uncommitted worktree edits made at 20:15:14 (`?v=20261118l`). They seem to target this race. A new pinned commit needs a new run of the "Live walk" table and the stress walk above.
- No real-phone test (#93): Android back gesture, iOS swipe-back, touch swipe-down.
- I wrote only this file. No commit, no push, no code change. I deleted my Playwright snapshot and console files.
