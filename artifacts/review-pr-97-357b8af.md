# Review: PR #97 feature/compass-pullout-bars @ 357b8af

- Pinned head: 357b8af22b22bc7dbc1f0c959bd7af00bc543a3b. Base: main. Closes #95.
- Verdict on 357b8af: **FAIL** (user_advocate, 3 High). Not merged at this SHA.
- **Update:** the owner asked to fix the 3 Highs. Fixed on the PR branch and reviewed again (see "Fix rounds" below). Merged as 5c6b2d7 at reviewed code SHA f2c8b28.
- CI on the head: all checks pass. `git merge-tree` predicts no conflict.

| Seat | Verdict | High | Medium | Low |
|---|---|---|---|---|
| tech_lead | PASS | 0 | 2 | 5 |
| project_manager | PASS | 0 | 4 | 4 |
| user_advocate | FAIL | 3 | 5 | 6 |

## High findings (user_advocate; contract: a FAIL on N2, L1 or A2 counts as High)

- H1 (N2): one system back press from a new layer (Learn menu, time machine, quiz, search) leaves the compass. The user must press Go, allow location and calibrate again. No `app/*.js` has a `popstate`, `pushState` or `hashchange` handler. The old sheets had the same gap; #97 adds four more layers.
- H2 (L1): the search pane, the Learn menu and the Learn panel can be open at the same time. A sky tap with the Learn menu open opens the star sheet over it. Esc does not close the Learn menu.
- H3 (A2): a double tap on "I saw it" stores `n:2`. Data stays on the phone, so real impact is low.

## Medium findings

- tech_lead M1: `app/learn.js:190` quiz timer is not cancelled by `close()` (issue #106).
- tech_lead M2 / project_manager: about 500–650 new lines (`learn.js`, `realsky.js` time machine, `camPower`) have no unit test.
- project_manager: `README.md:226` still describes "Save the sky for a place", which this PR hides.
- project_manager: scope is wider than the title and #95. #99 is closed as done but #97 is not merged.
- user_advocate: 🎓 button hidden while the bottom bar is open (and the bar state is remembered); first-visit hint may play behind calibration and never return; pull tabs under 44 px; sky log uses the UTC date; back, Esc, ×, swipe and outside tap close different sets of layers.

## Low

"Closes #98" does not link. The PR body contradicts itself on precession. #93 real-phone test is still owed.

## Fix rounds

| Head | Change | tech_lead | user_advocate |
|---|---|---|---|
| c9aa6d7 | layer stack with history entries (H1), one layer at a time + Esc (H2), sky log once per local day (H3), quiz timer cancel (#106) | FAIL: 2 High (a layer that replaces another in the same task loses its entry) | FAIL: N1 (same race) |
| f7d15e5 | one net history change per observer batch; pushes wait for our own `history.go()`; star URL kept; quiz open token; local date by hand | FAIL: 1 new High (tour or quiz closed while loading still starts) | PASS (stress walk 8/8; N2 aim bar deferred to #108) |
| f2c8b28 | open() also checks that the mode is still the one it opened | PASS (0 High) | not re-run; delta is one line in `learn.js`, reviewed by tech_lead |

Review files: `review-tech_lead-pr-97-c9aa6d7.md`, `review-user_advocate-pr-97-c9aa6d7.md`, `review-tech_lead-pr-97-f7d15e5.md`, `review-user_advocate-pr-97-f7d15e5.md`, `review-tech_lead-pr-97-f2c8b28.md`.
Proof that the new browser checks catch the bugs: `realsky-old-c9aa6d7.txt`, `realsky-old-f7d15e5.txt`.

Checks on the merged tree (e60bf9a): `node --test test/*.test.js` 670 pass, 0 fail, 2 skipped; `node test/browser/realsky.mjs` 60 PASS, 0 FAIL. #97 changes no Python. GitHub CI has not run on the fix commits, because they are not pushed.

Open after the merge (none blocks):
- #108: aim mode and the drag bar are not layers (existed before #97; N2 by the review contract). Reload with a layer open needs one extra back press.
- #109: no test for the #106 timer fix; the Forward button on desktop; back from Webb goes to the sky, not the star sheet (owner decision).
- #93: real-phone test still owed.
- PR Medium items not fixed: 🎓 hidden while the bottom bar is open; first-visit hint may play behind calibration; pull tabs under 44 px; scope wider than #95; "Closes #98" does not link.
