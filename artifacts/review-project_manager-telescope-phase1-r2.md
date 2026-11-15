# Review: project_manager, telescope zoom phase 1, round 2

- Branch: `feature/compass-telescope`, fixes `7058588..5fde083` (17 commits).
- Spec: `docs/specs/sky-compass-telescope.md`, Phases row 1.
- Round 1: `artifacts/review-project_manager-telescope-phase1.md`.
- `artifacts/review-tech_lead-telescope-phase1-r2.md` did not exist when I wrote this. No debate points to answer yet.

## Verdict

**PASS for a PR**, with the label "phase 1 built and verified in a browser; real-phone test pending (#71)".
**Not PASS as "done".** Merge to `main` as done needs #71 closed, or a written waiver from the user.

## What I ran

- `node --test test/*.test.js`: 313 tests, 312 pass, 0 fail, 1 skipped. Confirmed.
- `artifacts/real-sky/browser-checks.json` (commit `eec5f8c`): 52 checks, 52 ok. I read the 12 telescope rows.
  I did not rerun the browser script (it needs the network and long saves). I accept the committed record.
- `gh issue view 71`: OPEN, 8 test steps for each phone, names the roll levelling and the 0.9 px result.
- Read `test/realsky-telescope.test.js`, `test/browser/realsky.mjs` part 1g, spec diff `a8eecf0`.

## Round-1 findings

| Id | State | Evidence |
|---|---|---|
| H1 real phones | named leftover | Issue #71 (OPEN, steps 1 to 8). Spec "Built beyond the spec" last line. Not fixable by an agent. |
| H2 browser checks | fixed | `test/browser/realsky.mjs:249-290`. Record: 12x cover 1; 2 compared, 0 px. 150x 0.5 px, 300x 1 px, pinch 0.9 px, all `compared >= 1`. Held at 10x: view 316.5649, 26.9462 unchanged while the fed phone turned -3.00 deg. |
| M1 spec status | fixed | `docs/specs/sky-compass-telescope.md:3` "phase 1 built". Open questions 1 to 4 have builder defaults, roll levelling included. Extras listed. |
| M2 note texts | fixed | `test/realsky-telescope.test.js:178` (survey name, "Archive photograph, not live", "approximate" rule), `:205` ("No connection"), `:212` (hold hint). |
| L1 hold hint | fixed | `cce85e7`; test `:212`. |
| L2 2x preload | fixed | `7f7d92e`; test `:96` (cellular and Save-Data start at 3x). Named in the spec extras. |
| L3 crosshair | fixed | `de00872` dark edge. Visual check is for user_advocate. |
| L4 40/40 record | open, PR body | No PR exists yet. The PR body must say `42cc8a2` was a regression run only. |

## Per-criterion map (Phases row 1), round 2

| # | Criterion | State |
|---|---|---|
| W1 to W5 | Build items | met (round 1), W4 now tested |
| D1 to D3 | Node checks | met |
| D4 | Browser, Eye 12x, photographs, `selfTest` within 3 px | met, repeatable, non-empty |
| D5 | Browser, fed poses, held view does not move | met |
| D6 | Real iPhone and Android | missing, named leftover #71 |

## Is the leftover honest enough?

Yes, for a PR. Reasons:

- It is the only unmet criterion. Only a human can do it.
- It is tracked in a live issue with concrete steps, not in prose only.
- The spec, the issue and the planned report all say "pending". Nothing claims "done".

Conditions for this PASS:

1. The PR body states "real-phone test pending (#71)" and does not use `Closes #71`.
2. The PR is not merged as "phase 1 done" until #71 is closed or the user waives it in writing.
3. Roll levelling stays a builder default until the user confirms (spec question 4).

## New findings

### L5 (low): the spec status line does not say "device test pending".

- `docs/specs/sky-compass-telescope.md:3` says only "phase 1 built". The pending test is in the "Built beyond the spec" list, which is the wrong section.
- Action: add "real-phone test pending (#71)" to the status line. One line.

### L6 (low): `artifacts/telescope-zoom/verify.md:15-17` is stale.

- It says "`test/browser/realsky.mjs` has no telescope check yet". That is now false (part 1g).
- Action: append a round-2 line, or let the PR body point to `browser-checks.json` as the current record.

### L7 (low): issue #71 says "#68 (PR for this branch)". #68 is an issue about opening PRs, not the PR.

- Action: fix the link when the PR exists.

## Scope honesty

- No TODOs, no deleted tests, no mocked app behaviour. The node harness fakes the page and Aladin, which is correct for a unit test.
- The architecture commits (`0cea7fd`, `b5c4fd7`, `28edd61`) are refactors inside scope. The browser record was rerun after them (52 of 52).
- Extras are listed in the spec. No gold-plating concern.
