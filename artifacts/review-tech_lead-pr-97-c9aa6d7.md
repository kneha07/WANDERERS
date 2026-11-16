# Tech lead review: PR #97 at c9aa6d7

Reviewer seat: tech_lead (independent, not the author of the fix). Date: 2026-11-15.
Diff: `git diff 357b8af c9aa6d7`. The previous head 357b8af had a PASS from this seat.
Line numbers refer to the files at c9aa6d7.

## Verdict: FAIL

| Severity | Count |
|---|---|
| High | 2 |
| Medium | 3 |
| Low | 4 |

```
node --test test/*.test.js        666 tests, 664 pass, 0 fail, 2 skipped   (as expected)
browser probe (headless Edge)     5 of 8 history scenarios fail  (see "Evidence")
```

The layer stack is a good design. One history entry per open layer is the correct model.
But the accounting breaks when a layer closes and another layer opens in the same task.
The two most common paths do exactly that: the Learn menu opens a mode, and Details opens Webb.
In those paths the back button and Esc leave the compass, and the × of the learn panel also leaves the compass.

## How the accounting fails

```
same task:  A.hidden = true ; B.hidden = false
                 │                    │
observer:   drop A: skipPops=1,       push B: history.pushState()   (sync)
            history.go(-1)  (async)
                 │
browser:    go(-1) runs AFTER the push and goes back past B's new entry
            popstate -> skipPops-- -> ignored
                 │
result:     layerStack = [B]   history entries for layers = 0   history.state = null
            back  -> leaves compass.html with B open
            Esc   -> closeTopLayer -> history.back() -> leaves compass.html
            B's × -> drop 1 -> history.go(-1) -> leaves compass.html
```

## Findings

### H1. Menu -> mode and Details -> Webb leave the layer with no history entry (High)

- Where: `app/compass.js:945` (`dropEntries`), `app/compass.js:954-955` (push after drop in one callback).
- Triggers:
  - `app/learn.js:73`: `open()` sets `learnMenu.hidden = true` and then `learnPanel.hidden = false` in one task. This is every mode that the user starts from the 🎓 menu.
  - `app/compass.js:735`: `openWebb()` sets `details.hidden = true` and then `webb.hidden = false` in one task.
  - Any close followed by an open before the `popstate` of the drop arrives. A `setTimeout(0)` gap is not enough (scenario E).
- Cause: the observer processes the close first. `history.go(-1)` is async. The `pushState` of the new layer runs before it. The pending `go(-1)` then removes the new entry, and the `popstate` is eaten by `skipPops`.
- Failure scenario (measured, scenario B): the user taps 🎓, then "My sky log". The panel shows. `history.state` is `null`. The phone's back button opens the previous page with the panel still open. The same happens for Details -> "See it with Webb" (scenario C).
- This is the exact bug that the commit claims to fix ("back closes the top layer"), on its main path. The commit makes the main path worse than before: before c9aa6d7, back left the page, but the × did not.

### H2. With a desynced stack, the × and Esc navigate away from the compass (High)

- Where: `app/compass.js:955` (close by × -> `dropEntries(1)`), `app/compass.js:964-965` (`closeTopLayer` -> `history.back()`), `app/compass.js:357`.
- Failure scenario (measured, scenario B2): after H1, the user taps × on the learn panel. The observer drops one entry that does not exist. `history.go(-1)` goes to the previous document. The user is thrown off the compass by a close button.
- Failure scenario (measured, scenario H): on a desktop, the user opens a mode from the menu and presses Esc. `closeTopLayer` sees a non-empty stack and calls `history.back()`. The page navigates away.
- When the compass is the first page in the tab, `go(-1)` does nothing and no `popstate` arrives. Then `skipPops` stays at 1 and eats the next real back press. The drift then grows with each layer.
- No guard exists. Nothing checks that the current entry is a layer entry (for example `history.state?.layer`) before it drops or goes back.

### M1. Closing a layer reverts the URL that a pick wrote while the layer was open (Medium)

- Where: `app/compass.js:799` and `app/compass.js:838` (`history.replaceState` on the current entry), with `app/compass.js:955` (`go(-1)`).
- Cause: while a layer is open, the current entry is the layer entry. `replaceState` writes `?target=…&star=…` into that entry. The drop then goes back to the older entry, which has the old URL.
- Failure scenario (measured, scenario F): the user searches "Vega" and picks it. `searchOpen(false)` and `selectStar()` run in one task. Directly after the pick the URL has `star=Vega`. 500 ms later the URL does not. A reload or a shared link loses the picked star. The same happens to a target picked in the list while any layer (for example the learn panel) is open, when that layer later closes.

### M2. The tests do not cover the broken paths, and one check passes on the broken state (Medium)

- `test/browser/realsky.mjs:296` opens the time machine with `WanderersLearn.open("time")` directly, with no menu open. So the menu -> mode path (H1) is never run. Details -> Webb is not run either.
- `test/browser/realsky.mjs:304` asserts `history.state === null` as proof that "no history entry is left behind". The broken state in H1 also has `history.state === null`. The check cannot tell the good state from the bad state. A better oracle: after all closes, one `history.back()` must leave the page, and with N layers open, N back presses must stay on the page.
- `test/compass-flows.test.js:79-80` stubs `pushState`, `back`, `go` as no-ops and `MutationObserver` as a class that never calls back. This does not hide a breakage in the old flow tests. But it removes all Node coverage of the layer stack, so the only oracle is the weak browser check above. This is not a false green on its own; together with the oracle at line 304 it lets H1 ship green.

### M3. #106 is fixed, but the issue asked for a test, and none exists (Medium)

- `app/learn.js:79` clears `next` in `close()`. `app/learn.js:179` clears it on Skip. `app/learn.js:190` keeps the id. This covers both cases in #106.
- No test checks it. `grep` finds no test of `learn.js` quiz timing or of the once-per-day sky log (`app/learn.js:273-279`). The issue text says "Add a test."
- Residual (pre-existing, not in #106): `open("quiz")` twice before `ready()` resolves (for example a double tap on "Play again", `app/learn.js:202`) starts two `setInterval(quizTick)`. Only the last id is kept in `timer`, so `close()` does not stop the first one. That orphan interval can call `log()` after close and then throw on `$("quizMsg")` being `null`. Record it as a follow-up; it does not block.

### L1. A reload with a layer open needs one extra back press (Low)

- Measured (scenario G): open Info, reload. All layers are hidden, but `history.state` is `{layer:"info"}`. The first back press stays on the compass and does nothing visible.
- A `history.state?.layer` check at start-up (for example `replaceState(null)` or one `back()`) would remove it.

### L2. Aim mode and "Drag the sky" are not layers (Low)

- `app/compass.js:862` (`startAim`) and `app/realsky.js:495` (`startDrag`) close the North sheet and show `aimBar` or `dragBar`. Those bars are not in `LAYERS` (`app/compass.js:937`).
- Back during aim mode or drag mode leaves the compass. The bar is a modal state that the user sees as a layer. This is a scope gap, not a regression.

### L3. `toLocaleDateString("sv")` is a de-facto format, not a contract (Low)

- `app/learn.js:273`. Chrome, Edge, Firefox and Safari give `YYYY-MM-DD` today.
- A browser without full ICU falls back to the default locale (for example `11/15/2026`). The once-per-day key still works, because both sides use the same function. But `app/learn.js:290` sorts by `last` with `localeCompare`, so such dates sort wrong across months and years, and old UTC entries mix with them.
- Building the string from `getFullYear()`, `getMonth()+1` and `getDate()` with `padStart` removes the dependency.
- Expected behaviour change, not a bug: entries saved before c9aa6d7 have a UTC `last`. Near local midnight a second sighting on the same local day can count once more. This happens once per object.

### L4. `closeLayer` for `learnPanel` depends on `WanderersLearn` (Low)

- `app/compass.js:941`. If `learn.js` fails to load, `?.close()` does nothing. Back pops the panel from `layerStack` but the panel stays open, with no entry. Only reachable if the module fails. Also: if `mode` is `null` while the panel is visible, `close()` returns early (`app/learn.js:78`). Today `open()` sets `mode` before it shows the panel, so this is not reachable.

## Questions from the dispatch, answered

| Question | Answer |
|---|---|
| Can pushed entries drift from the open-layer count? | Yes. Close-then-open in one task (H1), or within the async gap of `history.go`. |
| Can back leave the compass with a layer open? | Yes. Menu -> mode, Details -> Webb (H1). |
| Two presses with none open? | Yes, after a reload with a layer open (L1), and when `skipPops` is stuck at 1 (H2, first page in tab). |
| A layer reopened in the same task? | Safe. The observer sees the final state, and the entry stays. |
| `learn.js open()` calls `close()` then reopens? | Safe when a mode is already running (same-task hide/show of the panel is a no-op). Unsafe from the menu (H1). |
| `closeLayer(learnPanel)` -> `WanderersLearn.close()` toggles `hidden`? | Safe. The layer is already off the stack, so the second record is a no-op. |
| Other `hidden` writers that push history? | `openWebb` (H1). `startAim`/`startDrag` only drop (correct). `showCard(null)` only drops (correct). `showCard(pk)` on an open card makes no record (correct). `showDetails` pushes once (correct). |
| Esc fallback in `closeTopLayer`? | The fallback branch (layers visible but not on the stack) is correct and harmless. The main branch trusts the stack, so with H1 it navigates away (H2). |
| `toLocaleDateString("sv")` safe? | In current major browsers, yes. Not guaranteed (L3). |
| #106 fully covered? | Yes for the reported bug. No test (M3). One related pre-existing interval leak remains (M3). |
| Are the test stubs honest? | The Node stubs are honest but give no coverage. The browser check at `realsky.mjs:304` uses an oracle that passes on the broken state (M2). |

## Evidence

The probe ran in headless Edge against `app/` from this worktree, served from a local static server.
Each scenario loads `outside.html` first and then `compass.html?debug=1&go=1&intro=skip&cam=0&…`, so a back press that leaves the compass is visible. The script lived in the session scratchpad and is not in the repo.

| # | Steps | After | One back press |
|---|---|---|---|
| A | Info button | `info` open, `state={layer:"info"}` | stays on compass, Info closed (correct) |
| B | 🎓, then "My sky log" | `learnPanel` open, `state=null` | goes to `outside.html` (wrong) |
| B2 | as B, then × on the panel | page navigates away | (wrong) |
| C | `details` open; then same task `details.hidden=true; webb.hidden=false` | `webb` open, `state=null` | goes to `outside.html` (wrong) |
| D | `info` open; then same task `info` close, `north` open | `north` open, `state=null` | goes to `outside.html` (wrong) |
| E | as D, with `setTimeout(0)` between close and open | same as D | (wrong) |
| F | search open; same task: close + `replaceState(?star=Vega)` | URL has `star=Vega` at once, not 500 ms later | (wrong) |
| G | Info open, reload | nothing open, `state={layer:"info"}` | stays on compass, nothing to close (extra press) |
| H | 🎓, "My sky log", Esc | page navigates away | (wrong) |

The browser test `test/browser/realsky.mjs` was not run again. Its four new checks do not run paths B, C, D, F or H, so its 56 PASS does not change this verdict.

## What a PASS needs

- H1 and H2 fixed: no path may leave the compass by back, Esc or × while a layer is open.
- A browser check that runs the menu -> mode path and the Details -> Webb path, and that tests the result with real back presses (stay on the page while layers are open; leave on the first press when none is open).
- M1 fixed or recorded as an issue.
