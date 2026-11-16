# Tech lead review: PR #97 at f2c8b28 (round 3)

Reviewer seat: tech_lead (independent, not the author of the fix). Date: 2026-11-15.
Diff: `git diff f7d15e5 f2c8b28`. Round 2: `artifacts/review-tech_lead-pr-97-f7d15e5.md` (FAIL, one High).
Line numbers refer to the files at f2c8b28.

## Verdict: PASS

| Severity | Count |
|---|---|
| High | 0 |
| Medium | 1 (carried, does not block) |
| Low | 4 (3 carried, 1 new; none blocks) |

```
round 2 High: a tour or quiz closed while it loads keeps running
   app/learn.js:75   if (opening !== me || mode !== m) return;
   -> closed while loading   : mode null, panel empty         (probe L3, L4, L6)
   -> opened again (same m)  : the second open wins, one start (probe L5)
   -> layer history          : unchanged, still correct       (probe B, E)
```

## The round-2 High: fixed

- `app/learn.js:75` now stops after `await ready()` when the mode was closed (`mode !== m`) or opened again (`opening !== me`).
- `close()` sets `mode = null`, so a close during "Loading the sky…" stops the start. A new `open()` changes `opening`, so the old start stops and only the new one runs.
- The edge case `close()` then `open(m)` with the same `m` is safe. `mode === m` again, but `opening` has changed.
- The diff touches no other code path. The `compass.js` history code is identical to f7d15e5.

## Repro and race cases, run again on f2c8b28

Headless Edge, against this worktree's `app/` on a local static server. Each case loads `outside.html`, then `compass.html?debug=1&go=1&intro=skip&cam=0&…`.

| Case | Steps | Result | Status |
|---|---|---|---|
| L3 | stars loaded; `open("quiz")`, `close()` at once, wait 1.5 s | `mode=null`, panel hidden, panel HTML length 0 | Fixed (f7d15e5: a quiz round in the hidden panel) |
| L4 | stars not loaded; `open("tour")`, `close()` in the next task, wait 9.5 s (past the 8 s `ready()` limit) | `mode=null`, panel empty, no learn target selected | Fixed |
| L5 | `open("quiz")`, `close()`, `open("quiz")` | one quiz, round 1 shows; a close and a new open later start a fresh round 1 | Correct |
| L6 | 🎓 -> quiz, then back at once, wait 1.5 s | `mode=null`, panel empty; the next back leaves the page | Correct |
| B | 🎓 -> My sky log; back, back | 1: stays on compass, panel closed. 2: leaves | Correct (no change) |
| E | Info close, `setTimeout(0)`, North open; back, back | 1: stays, North closed. 2: leaves | Correct (no change) |

- `node --test test/*.test.js`: 664 pass, 0 fail, 2 skipped (author's run; this round touched no Node test or Node-tested module).
- I did not run `test/browser/realsky.mjs` again. Its new check "a tour closed while it loads does not start" fails on f7d15e5 (`artifacts/realsky-old-f7d15e5.txt`, panel 582 characters). So the check can tell the bug from the fix. My probe gives the same result.

## Open items: blocking or not

| Item | Severity | Blocks? | Reason |
|---|---|---|---|
| #106 quiz timer has no test (`app/learn.js:79`, `:179`, `:190`) | Medium | No | The fix is three lines, and the code is easy to read as correct. The once-per-day half now has a browser check. Record the timer test as a follow-up issue. |
| Forward button closes a layer, stale entries stay | Low | No | Desktop only. Phones have no Forward button. It needs a direction index in `history.state`. Follow-up. |
| Reload with a layer open needs one extra back press | Low | No | One extra press once, then normal. Follow-up. |
| × and Esc not in the browser checks | Low | No | My probe B2 and H passed on f7d15e5, and this round did not change `compass.js`. Coverage gap only. |
| New: the "double tap" check calls `WanderersLearn.log()` twice, not the "I saw it" button (`test/browser/realsky.mjs`, the `vegaN` check) | Low | No | It tests the once-per-day rule in `log()`, which is the real guard. The check name says more than it tests. |

None of these is a High. Fix them or record them as issues.

## Summary for the debate

- Round 1 High 1 and High 2 (history): fixed in f7d15e5, still correct here.
- Round 2 High (close while loading): fixed in f2c8b28 and covered by a browser check that discriminates.
- No new High. PASS.

The probe script is in the session scratchpad, not in the repo.
