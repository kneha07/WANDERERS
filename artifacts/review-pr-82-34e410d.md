# Review: tech_lead, compass telescope delta bcc891f..34e410d

- Branch: `feature/compass-telescope`, pinned head `34e410d`. Base `main` at `cfc0129`.
- Scope: only the delta `bcc891f..34e410d` (N1 fix, UA M1-M4 fixes, records).
- Earlier seats: `artifacts/review-tech_lead-telescope-phase1-r2.md` (N1), `artifacts/review-user_advocate-telescope-phase1.md` (M1-M4).

## Verdict

**PASS-with-findings.** No high finding. No medium finding. Four low findings.
Each fix resolves the finding it names. I found no regression in the delta.

## Fix by fix

| Finding | Commit | Status | Evidence |
|---|---|---|---|
| TL r2 N1: a start that throws after `loadSurvey` retries every frame | 7ab790d | Fixed, tested | `app/realsky.js:161-166`: the `startDeep` catch now sets `retryAt = now + 30 s` for every failure, sets `DEEP.aladin = null` and clears `#skyDeep`. New test `test/realsky-telescope.test.js` "Aladin itself failing (no WebGL2) waits 30 s as well": fake `A.aladin` throws; 20 frames give 1 build and 1 probe; `#skyDeep` children are empty; the note says "not reachable"; after 30 s, a second try. The test fails on the old code (old code gives 20 builds). |
| UA M1: note not readable on photographs | 5587a9f | Fixed, tested | `note()` toggles `.on-photo` when `cover() > 0` (`app/realsky.js:262-263`), cached in `PILL`. CSS pill `rgba(4,9,20,.72)` with `#e8eefb` (`app/compass.css:222`). Test computes contrast over white: about 7:1. Amber button about 4.8:1. Test for the toggle at 1x, 12x, 1x. |
| UA M2: HELD hard to see | 17107f6 | Fixed, tested | `#heldMark` under the `1×` button and `#holdHint` (`role="status"`) under the crosshair (`app/compass.html:79-80`). `updateHold` shows both on entry, hint only on `S.holds === 1`, 4 s timer, clears both and the timer on exit (`app/compass.js:271-277`). `S.hold` changes only in `updateHold`, so no other path leaves HELD shown. Test covers first hold, 4 s, exit, second hold, exit before 4 s. Hold text removed from the note; test asserts this. |
| UA M3: two accuracy claims | 057bb10 | Fixed, tested | `approx` computed once; `pt.text` ("Direction good to about ±N°") shows only when `!approx` (`app/realsky.js:257-261`). The "Sight check" button still shows, because `pt.needsCal` is separate. Test asserts one claim in each of 4 states. |
| UA M4: offline view black, text overstates | 226666a | Fixed, tested | `online()` gates `want`, `op` and `cover()` outside Deep (`app/realsky.js:205-215`). Offline the dark backdrop and drawn stars stay, and no probe runs. New text "No connection: telescope photographs are not available." Deep keeps its saved photographs and the old text. Test covers start offline, drop after load, reconnect, and Deep offline. |

## Findings

### L1 (low) N1 fix: a failed Aladin is dropped, not destroyed

- `app/realsky.js:165` sets `DEEP.aladin = null` and removes the DOM nodes. If `setBaseImageLayer` throws after a good build, the Aladin instance can keep its WebGL context and listeners.
- The 30 s wait limits this to one leaked instance per 30 s, only while zoomed in on a failing browser. No user-visible effect expected.

### L2 (low) M4 fix: `navigator.onLine` covers only "no network", and Eye now hides saved photographs offline

- `navigator.onLine` is `true` on a network with no internet (captive portal, LAN only). Then the old black view can still occur. The 20 s timeout and the 30 s wait still limit the cost.
- Offline in Eye at 3x+, saved coarse tiles are now never shown, even for a saved place. The comment at `app/realsky.js:203-204` states this choice. Accept it, but name it for the #71 phone test.

### L3 (low) The browser record adds no check for M1, M2 or M4

- `test/browser/realsky.mjs` at `34e410d` has no check for `.on-photo`, `#heldMark`, `#holdHint`, or the offline telescope view. The "52 of 52" record (6e42dbf) re-runs the existing checks and refreshes screenshots.
- The node tests cover the logic with a fake page. Real layout (hint position against the crosshair and target labels) has only screenshot evidence.

### L4 (low) Duplicate screenshot in the review evidence

- `artifacts/telescope-zoom/ux-loading-12x.png` and `ux-12x.png` are the same blob (`3154852`). The "loading" screenshot does not show a loading state. It came in with b0ce4dd (UA review record). It is not a code issue.

## Tests run

| Tree | Command | Result |
|---|---|---|
| `34e410d` (exported with `git archive` to the scratchpad) | `node --test test/*.test.js` | 317 tests, 316 pass, 0 fail, 1 skip (`pipeline/fov.py` parity: python3 not available) |
| Worktree `.worktrees/compass-telescope` | `node --test test/*.test.js` | 617 tests, 614 pass, **1 fail**, 2 skip |

- Note: the worktree HEAD is `d3bbb71`, not `34e410d`. `d3bbb71` is a merge of `origin/main` (`cfc0129`) into the branch. It changes no telescope file (`app/compass.*`, `app/realsky.js`) compared with `34e410d`.
- The one failure is `classify.js points at the team repo's issue form and the snapshot the workflow writes` (`test/classify-static.test.js`). It fails on `cfc0129` (main) alone too. It expects an empty `app/data/classifications.json`, but main has an `rw_aur` vote. It is not from this branch. Track it on main.

## Merge with main

`git merge-tree --write-tree --name-only cfc0129 34e410d` gives tree `e52b2dd` with conflicts in two files only:

- `docs/wiki/wiki/index.md`
- `docs/wiki/wiki/log.md`

Both are append-only. Main appended the star-fix run record; the branch appended the compass-telescope run record at the same place. README.md auto-merges.

How to combine: keep both appended blocks, main's first, then the branch's (date order).

- `index.md`: keep the `[[run-star-fix-2026-11-15]]` line, then the `[[run-compass-telescope-2026-11-15]]` line.
- `log.md`: keep the `## [2026-11-15] run | star fix (work-lite)` block, then the `## [2026-11-15] run | compass telescope phase 1 (work-lite)` block.

The branch already has this resolution in `d3bbb71`: `git diff cfc0129 d3bbb71 -- docs/wiki/wiki/` shows only the two compass additions after main's lines. That merge also changes the compass log line to "pushed, PR open, not merged". Merge `d3bbb71`, or use the same resolution.

## Path to merge (tech_lead seat)

- No blocker. L1-L4 can go to the PR as known leftovers.
- Fix the main-only `classify-static` test failure on main, separately.
