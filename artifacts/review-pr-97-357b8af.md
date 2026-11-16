# Review: PR #97 feature/compass-pullout-bars @ 357b8af

- Pinned head: 357b8af22b22bc7dbc1f0c959bd7af00bc543a3b. Base: main. Closes #95.
- Verdict: **FAIL** (user_advocate, 3 High). **Not merged.** The owner decides: fix first, or accept the risk.
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
