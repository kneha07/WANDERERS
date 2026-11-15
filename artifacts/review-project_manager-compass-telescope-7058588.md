# Review: project_manager, feature/compass-telescope at 7058588

- Repo: kneha07/WANDERERS. Branch `feature/compass-telescope`. Pinned head `7058588`.
- Base: `origin/main` `a88e63a`. Merge base `ca220c7`. 16 commits, 16 files, +711 / -79.
- Spec: `docs/specs/sky-compass-telescope.md` (Phases row 1 is the scope of this branch).
- Round 1, independent. No tech_lead artifact for this head existed when I wrote this.

## Verdict

**FAIL** for a merge of `7058588`.

The phase-1 code is mostly there and the node tests pass.
But at this head, two phase-1 "done when" items are missing, one known high bug is not fixed,
and the README and the spec say wrong things about what is built.

The branch has moved on. The worktree HEAD is `a8eecf0`, 11 commits after `7058588`.
Those commits name fixes for most findings below (TL-H1, PM-H2, PM-M1 and others).
They are **not** in the pinned head, so this review does not count them.
Action: re-pin the review to `a8eecf0` (or later) and review again. Do not merge `7058588`.

## What I ran and read

| Check | Result |
|---|---|
| `node --test test/*.test.js` on a `git archive 7058588` copy | 297 tests, 296 pass, 0 fail, 1 skipped |
| `git diff ca220c7 7058588` | read for README, specs, `test/browser/realsky.mjs`, `artifacts/real-sky/*` |
| `git diff d938fb5 7058588 -- test/` | only `test/compass-flows.test.js` changed. `test/browser/realsky.mjs` is unchanged after the pinch commit |
| `git show 7058588:app/realsky.js` | `syncDeep` still uses fixed-degree skip limits (line 181) |
| `artifacts/telescope-zoom/verify.md` | manual Playwright run, says real phones and a browser telescope check are not done |
| Earlier panel at this same head: `artifacts/review-project_manager-telescope-phase1.md`, `artifacts/review-tech_lead-telescope-phase1.md` | both FAIL. Both are untracked in the worktree, not committed |
| `gh issue list --search compass` / `--search zoom` | #71 (real-phone test, open), #68 (open PR for this branch, open), #42 (real-sky phone test, open) |

## Per-criterion map (spec Phases row 1)

| # | Criterion | State | Evidence |
|---|---|---|---|
| W1 | Zoom limit 300 | met | `app/compass.js:241` `ZOOM_MAX = 300`; node test "zoom stops at 300x" |
| W2 | Finder fade: camera and Eye into DSS2 | partial | `realsky.js` `scope()`, `cover()`. Eye at 12x seen by hand only (verify.md). Camera-on fade not checked |
| W3 | Hold mode with snap | met (code) | `compass.js:254-265` `updateHold()`; `pose()` uses `!S.hold` at `:214` |
| W4 | Note and telemetry text | partial | `HELD` at `compass.js:598`, node-tested. Note texts at `realsky.js:237-242` have no test at this head |
| W5 | Grid hidden above 6x | met | node test "above 6x the altitude rings ... horizon line stays" |
| D1 | Node: hold enters at 8x, leaves under 6x | met | `test/compass-flows.test.js` hold test |
| D2 | Node: drag works while held | met | `test/compass-flows.test.js` drag/arrow test |
| D3 | Node: snap centres a locked target | met | `test/compass-flows.test.js` snap test |
| D4 | Browser: Eye 12x, photographs show, `selfTest` within 3 px | **missing as a check** | Not in `test/browser/realsky.mjs`. Only a manual run in verify.md. And see H2: registration fails for a moving view above about 24x |
| D5 | Browser: fed sensor poses, view does not move while held | **missing** | No browser check exists at this head |
| D6 | Tried on a real iPhone and a real Android phone | **missing** | verify.md "Not verified"; issue #71 open |

## Findings

### H1 (high): the "browser checks record 40/40" is not evidence for the telescope feature

- Commit `42cc8a2` says "Telescope zoom: browser checks record ... 40 of 40 pass".
- `git diff d938fb5 7058588 -- test/browser/realsky.mjs` is empty. The only zoom checks are from the pinch commit, at **4x**
  (`artifacts/real-sky/run-zoom.log`: "zoomed in 4 times"; `deep-zoom-phone.png` is the 4x shot).
- No check runs at 12x, 60x, 150x or 300x. No check runs hold mode or snap in a browser.
- So D4 and D5 are missing. The commit title over-claims.

### H2 (high): photographs misregister at high zoom at this head (tech_lead H1, still open at 7058588)

- `git show 7058588:app/realsky.js`, line 181: `syncDeep` skips an update when the FoV change is `< 0.01` deg and the turn `< 0.05` deg.
- At 300x, 1 deg is about 3,800 px. These limits are safe at 8x, not at 300x. The tech_lead panel measured up to 38 px error.
- Spec rule "registration within 3 px" fails for a view that moves (tracking, drag).
- Fixed later in `b3312a3` (pixel limits). Not in the pinned head.

### H3 (high): real-phone test not done, and not waived

- Spec Phases row 1: "Tried on a real iPhone and a real Android phone".
- verify.md lists it as not verified. Issue #71 is open with `help wanted`.
- Hold mode, snap and sidereal tracking exist for sensor phones only. No sensor phone ran them.
- Only a human can do this. Either a person tests on both phones, or the user waives it in writing before the merge.
  If waived, the PR body must say "phase 1 merged without a device test, see #71".

### M1 (medium): README says the zoom stops at 8x

- `README.md:186` at `7058588`: "zoom in, up to 8 times". The code limit is 300 (`compass.js:241`).
- The README says nothing about the telescope view, hold mode, `HELD`, or tracking.
- This is still wrong at `a8eecf0` (same line).
- `docs/specs/sky-compass-real-sky.md` (diff, added lines) also says "1 to 8 times". It is wrong after `5489620`.

### M2 (medium): the spec says "design only, nothing built"

- `docs/specs/sky-compass-telescope.md:3` at `7058588`.
- The three open questions (lines 143-148) and the roll decision (line 90) have no recorded answer.
  The code picks: hold is automatic, no vignette, roll levels on hold. The user did not confirm these.
- `a8eecf0` updates the spec. Not in the pinned head.

### M3 (medium): section 5 honesty texts have no automated check at this head

- Spec section 5 says "These are requirements, not polish".
- `realsky.js:237-242` has the texts ("Archive photograph, not live", the "approximate" text, "No connection").
  No test reads them at `7058588`. `84ae142` adds tests later.

### M4 (medium): the branch carries an unreviewed second feature

- `d938fb5` holds pinch zoom **and** the daily reissued-survey check in `sw.js` (+55 lines).
- The spec says it needs `feature/compass-pinch-zoom`, which was never merged on its own (issue #68).
- That work has browser checks (`realsky.mjs` 1c2 and the saved-place renew check) and README text. That part looks honest.
- But the PR must name both features, so the review of `sw.js` cache deletion is not skipped.

### L1 (low): the phase-1 panel artifacts are not committed

- `artifacts/review-*-telescope-phase1.md` are untracked in the worktree. CLAUDE.md rule 5 says commit them on the branch.

### L2 (low): verify.md says the default south view at 12x compared 0 stars

- An empty pass. Any future check must assert `stars.length >= 1`.

## Design and goal alignment

- Goal: "zooming feels like a move from the eye to a telescope". Phase 1 moves the goal forward. It is not a side quest.
- The design is followed, with small forks named by the earlier panel:
  Finder uses the user's survey (2MASS if chosen), photographs also fade in with sky Off, early start at 2x.
- Phases 2 and 3 (Pan-STARRS, Hubble, Webb) are not claimed. That is honest. The spec goal text still names them, so the README must not.

## Path to PASS

1. Re-pin to `a8eecf0` or later. Check that `5e32882` adds real 12x/150x/300x and hold checks to `test/browser/realsky.mjs`, and re-run it.
2. Fix README line 186 and the real-sky spec "1 to 8 times" line. Add one sentence on the telescope view and hold.
3. Get the device test done, or a written waiver from the user that names #71.
4. Commit the panel artifacts on the branch.

## Tech_lead comparison

No `artifacts/review-tech_lead-compass-telescope-7058588.md` existed when I finished.
The earlier tech_lead panel at the same head (`artifacts/review-tech_lead-telescope-phase1.md`, untracked in the branch worktree) is FAIL with H1 = `syncDeep` thresholds.
I agree with it. I carry it as my H2.
