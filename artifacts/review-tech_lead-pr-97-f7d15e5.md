# Tech lead review: PR #97 at f7d15e5 (round 2)

Reviewer seat: tech_lead (independent, not the author of the fix). Date: 2026-11-15.
Diff: `git diff c9aa6d7 f7d15e5`. Round 1: `artifacts/review-tech_lead-pr-97-c9aa6d7.md` (FAIL, H1 and H2).
Line numbers refer to the files at f7d15e5.

## Verdict: FAIL

| Severity | Count |
|---|---|
| High | 1 (new, a regression in `app/learn.js` from this round) |
| Medium | 1 |
| Low | 3 |

The history fix is correct. All round-1 history cases now pass, and the new race cases pass too.
One new High remains. The new `opening` token in `learn.js open()` removed the old guard against a close during "Loading the sky…".

```
round 1           round 2 (f7d15e5)
H1  menu->mode     fixed   (B, C, D, E pass)
H2  x / Esc leave  fixed   (B2, H pass)
M1  URL revert     fixed   (F, N pass)
M2  weak oracle    fixed   (new checks use history.state.layer and the page path)
M3  #106 no test   still open
L3  date format    fixed   (hand-built YYYY-MM-DD)
L4  no learn.js    fixed   (closeLayer falls back to hidden = true)
NEW H1 close while a tour or quiz loads -> hidden mode keeps running
```

## Round-1 findings: status

| Round 1 | Status | Evidence |
|---|---|---|
| H1 same-task close + open loses the entry | Fixed | `app/compass.js:947-952` and the observer sum `n` per batch: close + open in one batch is net 0, and the entry is reused. Probe B, C, D, E. |
| H2 × and Esc leave the compass | Fixed | It follows from H1. Probe B2 and H stay on the compass. |
| M1 star URL reverts | Fixed | `setUrl` / `keepUrl` (`app/compass.js:968-969`). Probe F and N keep `target=`. |
| M2 browser oracle passes on the bug | Fixed | `test/browser/realsky.mjs` now checks `history.state.layer` and the page path for menu -> mode and Details -> Webb. `artifacts/realsky-old-c9aa6d7.txt` shows that the old head fails it. |
| M3 #106 has no test | Open | See M1 below. |
| L1 reload with a layer open | Open (not claimed) | Probe A after a reload still shows `state={layer:1}` with nothing open. |
| L2 aim mode and drag bar | Deferred to #108 | Accepted. |
| L3 `toLocaleDateString("sv")` | Fixed | `app/learn.js` `today()` builds the date from local parts. |
| L4 `WanderersLearn` missing | Fixed | `app/compass.js` `closeLayer` falls back to `el.hidden = true`. |

## New findings

### H1. A tour or quiz closed while it loads keeps running with no panel (High, regression in f7d15e5)

- Where: `app/learn.js:73-75`. Round 1 used `if (mode !== m) return;` after `await ready()`. Round 2 uses `if (opening !== me) return;`. `close()` (`app/learn.js:78-84`) does not change `opening`, so a close no longer stops a pending open.
- Failure scenario (measured, probe L3):
  1. The user taps 🎓 and then "Find it: quiz" (or "Tonight's tour"). The panel shows "Loading the sky…". `ready()` can wait up to 8 s on a phone that has not loaded the stars yet.
  2. The user taps × or the back button. `close()` sets `mode = null` and hides the panel.
  3. `ready()` resolves. `opening === me`, so `startQuiz()` (or `startTour()`) still runs.
  4. Result, measured: `mode === null`, the panel is hidden, and the panel HTML holds a new quiz round.
- Effects:
  - `startQuiz` / `startTour` start `setInterval` (`app/learn.js:170`, `app/learn.js:134`). Nothing can clear it. `close()` returns at once because `mode` is `null` (`app/learn.js:79`). The next `open()` calls that same `close()` and then writes a new id over `timer`, so the old interval runs until a reload.
  - `startTour` calls `pointTo(stop)` (`app/learn.js:138`). This replaces the user's selected target with the hidden tour stop, and the compass arrow points at it with no panel to explain it.
  - `tourTick` / `quizTick` keep calling `log()`. This writes sky-log entries and badges to `localStorage` for objects that the user did not choose to find. That is persistent wrong user data.
- Why High: this round introduced it. Its own UI cannot stop it. It changes stored user data. It is reachable by the back button, which this PR now tells the user to use.
- Check that would catch it: open "quiz" with the stars not loaded, close it at once, wait for `ready()`, and then assert that `WanderersLearn.mode === null` and that `learnPanel.innerHTML === ""`.

### M1. #106 and the once-per-day log still have no test (Medium, carried from round 1 M3)

- `app/learn.js:79`, `:179`, `:190` (quiz `next` timer) and `today()` / `log()` (once per day). No Node or browser check exercises them. Issue #106 asks for a test.
- The double-open race from round 1 is now handled by `opening`. But that change caused H1, and no check covers either case. That shows the gap.

### L1. The browser Forward button closes a layer and leaves stale entries (Low)

- Where: `app/compass.js:970-978`. Every popstate that we did not cause is treated as "back".
- Measured (probe M): open the time machine, open Info, back (Info closes), Forward. The time machine closes too. Two layer entries now stay with no layer open. The next back press does nothing visible.
- Desktop only. Phones have no Forward button. A check of the entry direction (for example, an index in `history.state`) would fix it.

### L2. Reload with a layer open needs one extra back press (Low, carried)

- Same as round 1 L1. Not claimed in this round.

### L3. The new browser checks do not run × and Esc (Low)

- `test/browser/realsky.mjs` covers back after menu -> mode and after Details -> Webb. It does not cover × on the panel or Esc (round 1 B2 and H). My probe passes both on f7d15e5, so this is a coverage gap only.

## Race analysis of `moveEntries` / `skipPops` / `owedPushes`

| Race | Result | How checked |
|---|---|---|
| Close + open in one task | Net 0, entry reused | Probe B, C, D |
| Close, then open in the next task (go pending) | Push waits in `owedPushes` and runs on our popstate | Probe E |
| Drop while `owedPushes > 0` | Drop cancels the owed push, no `go()` | Probe K (back after leaves at once: correct) |
| Two opens while a go is pending | Second open closes the first, net still +1 owed | Probe K2 (2 presses: 1 closes, 1 leaves) |
| Two drops in two tasks (two `go(-1)` pending) | Both popstates arrive, `skipPops` returns to 0 | Probe I (later open + back still correct) |
| Script back while `skipPops > 0` | Both popstates counted, top layer closed | Probe J, J2 |
| Browser back (CDP `navigateToHistoryEntry`) right after a drop | Both layers closed, next back leaves | Probe O |
| `keepUrl` after a real back | Keeps the URL of the last pick | Probe N |
| `keepUrl` after our own go | Keeps the URL of the last pick | Probe F |

Notes:
- If a `go()` ever produced no popstate, `skipPops` would stay above 0 and pushes would wait forever. With a consistent stack every drop has a same-document entry below it, so this did not happen in any case. Reload (L2) does not create drops, because the stack starts empty.
- `keepUrl` writes `S.url` over any entry it lands on. Only `setUrl` sets `S.url`, and both URL writers in `compass.js` now use it. No other code writes the compass URL. Correct.

## Evidence

- `node --test test/*.test.js` on f7d15e5: 664 pass, 0 fail, 2 skipped (unchanged; the round touched no Node test).
- Headless Edge probe against this worktree's `app/`, from its own static server. Each case loads `outside.html` first, then `compass.html?debug=1&go=1&intro=skip&cam=0&…`. After the steps, the probe presses back and checks the path and the open layers.

| Case | Steps | After | Back presses |
|---|---|---|---|
| A | Info | `info`, `state.layer` | 1: compass, closed. 2: outside. Correct. |
| B | 🎓 -> My sky log | `learnPanel`, `state.layer` | 1: compass, closed. 2: outside. Correct. |
| B2 | B, then × | nothing open, `state=null` | 1: outside. Correct. |
| C | Details -> Webb (same task) | `webb`, `state.layer` | 1: compass, closed. 2: outside. Correct. |
| D | Info close + North open (same task) | North open | 1: compass, closed. 2: outside. Correct. |
| E | as D with `setTimeout(0)` between | North open | same as D. Correct. |
| F | search close + target pick (same task) | URL keeps `target=barnard` | 1: outside. Correct. |
| H | 🎓 -> My sky log -> Esc | stays on compass, `state=null` | 1: outside. Correct. |
| I | two drops in two tasks, then Info | Info open | 1: compass, closed. 2: outside. Correct. |
| J / J2 | drop, then script back (next task / same task) | panel closed | 1: outside. Correct. |
| K | close, open, close in three tasks | nothing open | 1: outside. Correct. |
| K2 | close, open North, open Details in three tasks | Details open | 1: compass, closed. 2: outside. Correct. |
| N | pick a target under Info, real back | URL keeps `target=` | 1: outside. Correct. |
| M | time machine + Info, back, Forward | both closed, `state.layer` left | 1: compass, nothing to close. Wrong (L1). |
| O | browser back (CDP) right after a drop | both closed | next back: outside. Correct. |
| L3 | stars loaded; `open("quiz")` then `close()` at once | `mode=null`, panel hidden, panel holds a quiz round | Wrong (H1). |

The probe script is in the session scratchpad, not in the repo. I did not run `test/browser/realsky.mjs` again. The author reports 58 PASS, and its checks do not cover H1.

## What a PASS needs

- H1 fixed: a `close()` during "Loading the sky…" must stop the pending start. Add a check for this case.
- M1: a check for the #106 timer and for once-per-day logging. A follow-up issue is acceptable if the team records it.
