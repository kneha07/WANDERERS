# Tech lead review: docs/project-explainer at 64cb979

- Branch: `docs/project-explainer` (kneha07/WANDERERS)
- Pinned head: `64cb979`. Base: `origin/main` `a88e63a`. Merge base: `184e071`.
- Diff (merge base to head): `artifacts/project-explainer.html` (+395), `docs/wiki/wiki/log.md` (+7). No product code changes.
- Reviewer: tech_lead. Date: 2026-11-15.

## Verdict

**FAIL** (one high finding: the pinned head is no longer the branch tip). If the merger re-pins to the
real tip and accepts the stale content as follow-up work, the content findings alone are **PASS-with-findings**.

```
184e071 ──(main: #64 Star Fix, #65 SPHEREx stage, #66, #67 README)──► a88e63a  (base)
   │
   └─ 479d910 v1 page ─ fa943eb log ─ 64cb979 kid-level text  (PINNED, reviewed)
                                          └─ 07fddb5 revert kid text ─ 8587114 log v3  (BRANCH TIP now)
```

## Findings

### H1 (high): the pinned head is not the branch tip

- The worktree `.worktrees/project-explainer` is at `8587114`, not `64cb979`.
- `07fddb5` reverts "Explainer page: rewrite text at kid level". `8587114` edits the log line to "v3: kid-level text reverted on user request".
- `git diff --quiet 479d910 8587114 -- artifacts/project-explainer.html` is true. So a merge of the branch now ships the v1 text, not the reviewed kid-level text.
- Effect: this review does not cover the text that a merge of the branch tip ships. A merge of `64cb979` ships text that the user asked to revert.
- Action for the merger: re-pin to `8587114` (or later) and review again. Spot checks show that v1 has the same stale items as M1 to M3 (no Star Fix, no SPHEREx survey stage, no "5 of 11" spectrum limit). v1 already fixes L1 ("Five test targets ship ready").

### M1 (medium): Star Fix (#64) is missing

- On main, Star Fix is one of the three "doors" on the home hero (`app/index.html:63`) and in the footer (`app/index.html:267`). README has a section on it (`README.md:208-217`).
- The page does not mention it in any place: not in audience, use cases (`CASES`, 6 entries), diagram, tech stack or limits.
- Missing facts: `app/starfix.html`; `POST /api/star-fix` in `server.js`; `pipeline/star_fix.py` (cedar-solve plate solve, astropy, pillow-heif); it needs `node start.js` or `node server.js`; one photo is right to about 50-150 km.
- The diagram box "Extra helper 1 / server.js" lists only "cooks any bit of sky, answers questions". It does not show the Star Fix route or `star-fix-solver.js`.

### M2 (medium): the SPHEREx survey stage (#65) is missing

- On main, the Sky Survey reads the SPHEREx DR1 all-sky cube to confirm movers in 2025-26 (`app/survey.html:52,57,61`), shows "Confirmed by SPHEREx" (`app/survey.html:69`), has a "SPHEREx-confirmed only" filter (`app/survey.html:133`), and exports the SPHEREx verdict in CSV/JSON (`54e487d`). Code: `pipeline/survey/spherex.py`.
- The page says the survey uses NEOWISE tracks and Gaia only. Task rows 5 and 6 and the data table ("SPHEREx: the newest pictures, in 102 colours") do not say that SPHEREx now confirms survey movers.
- The "Find the best mysteries" use case does not show the SPHEREx-confirmed filter.

### M3 (medium): the spectrum claim is wider than the data (stale after #67)

- Page: "Tell what it is made of. A special telescope sees 102 colours ... Water and other stuff leave their own pattern."
- Main README after #67 (`README.md:143-146`, `783-785`): "A usable spectrum exists for 5 of the 11 shipped targets." Barnard's Star, R Draconis and four more have none.
- The page's own rule is "Never fib" and "we say what the pictures cannot show". The limits list does not state the 5 of 11 limit. Only "The colour pattern shows the shape, but not exact amounts" is there.

### M4 (medium): the confidence rule on the page is not the code

- Page (evidence section): "3 or more clues: a strong guess. 2 clues: a medium guess. 0 or 1 clue: a weak guess."
- Code `pipeline/evidence.py:139`: `level = 2 if (n == len(support) and n >= 2) or n >= 3 else 1 if n == 2 else 0`. So "2 of 2 key checks" gives **high**, not medium.
- The page omits the step down when most SPHEREx data is saturated (`pipeline/evidence.py:143-145`, README flowchart).
- The page says "'3 of 3 clues agree' means a good guess". README after #67 (`README.md:149-155`) warns that the headline counts only the key checks for the chosen class, and says "Read the printed list, not the headline". The page teaches the reading that #67 removed.
- Word drift: the page says strong / medium / weak. The app and `evidence.py:148` say high / medium / low. Use the same words.

### L1 (low): "5 practice stars" and "8 of 9 tests" do not agree (pinned head only)

- Page: "5 practice stars ready to play with" and "The robot finds its own practice star in 8 of 9 tests."
- Main ships 11 targets (`README.md:143`; `app/data/` has 5 mission folders and 6 `pos_*` folders). The 8 fields (`docs/product-gaps.md:52`) are mostly not the 5 missions (Luhman 16, Wolf 359, Lalande 21185, Proxima, 61 Cygni, Kapteyn's Star). Five stars cannot give nine tests.
- "Misses WISE 0855" is correct (`docs/product-gaps.md:52`).
- The tip (`8587114`) already words this better ("Five test targets ship ready", "8 of 9 moving-target fields").

### L2 (low): "as cold as a home freezer" has no source in the repo

- No file on main gives a WISE 0855 temperature (`git grep` on README, `docs/demo-script.md`, `pipeline/targets.py`). Published values range from about 225 K to about 285 K. A freezer is about 255 K. Cite a source or remove the claim.

### L3 (low): small text drifts

- Sky Compass use case: "turn it slowly, three times". README (`README.md:203-204`): "lay the phone flat, hold, and give it three quarter turns".
- "Watch a star walk" use case, step 4: "Look for a dot with no circle. That dot is a mystery." Barnard's Star is in Gaia, so it has its own ghost circle. A reader who follows the steps finds no mystery dot. Say that Barnard's dot walks away from its circles.
- Idea step 1: "2010, every 6 months until 2024". NEOWISE starts in 2014 (the data table says so). The sentence reads as if there are visits from 2010 to 2014.
- Task 6: "A robot checks every piece". README (`README.md:52`) says the live page shows how much of the sky is done. The search is not complete.
- Log entry names `479d910` as the branch commit. The reviewed head is `64cb979`.

### L4 (low): render and markup

Checked (static, at `64cb979`; the shared Playwright browser was busy, so there is no live screenshot):

- Inline JS parses (`node --check` on the script block). No duplicate `id`. No `innerHTML` from user data (the `CASES` strings are static).
- External hosts: only `fonts.googleapis.com` / `fonts.gstatic.com` (allowed in the Artifact viewer, with font fallbacks), plus normal links to `rajryadav4.github.io/wanderers/` (same URLs as README). All link targets exist on main: `survey.html`, `observatory.html?target=barnard|wise0855`, `compass.html`.
- Theme: full light palette on `:root`, dark palette under both `prefers-color-scheme` guarded by `:not([data-theme="light"])` and `[data-theme="dark"]`, `color-scheme: dark` set, explicit `body` background. OK.
- Mobile: 16px side gutter with safe-area insets; hero stacks at 720px; the SVG (`min-width:720px`) and tables (`min-width:560px`) sit in `overflow-x:auto` boxes. `prefers-reduced-motion` stops the canvas loop. OK.
- Issue: the file has no `<!doctype>`, no `<meta charset>`, no `<html lang>`. That is correct for the Artifact publish path (the skeleton adds them). But the file is committed to the repo, and the other repo page (`artifacts/architecture/star-fix.html`) is a full document. Opened from the repo by file, it renders in quirks mode, and 12 lines of non-ASCII text (`·`, `→`, `○`, `–`) depend on charset guessing.
- Issue: in the SVG, `font-family="var(--mono)"` on the `.sub` code labels has no effect. The CSS rule `.diag text{font-family:var(--body)}` wins over a presentation attribute. The code names render in the body font.
- Issue: the tabs have `role="tab"` but no `aria-controls`, no `tabindex` roving and no arrow-key support. The panel has no `aria-labelledby`. Buttons still work with Tab and Enter.

## Facts checked and correct (at a88e63a)

| Page claim | Source on main |
|---|---|
| Six tasks, all done | `README.md:44-52` |
| Weekly sync every Monday | `README.md:730`, `.github/workflows/spherex-sync.yml` |
| Six SPHEREx detectors, single or combined | `README.md:48` |
| good / caution / poor with a reason | `README.md:49` |
| Votes: moving, variable, still, artefact, unsure; 3 people, 60% | `README.md:50` |
| 12,288 tiles; more than 10 billion detections | `README.md:52` |
| 102 colours, 0.75-5 µm | `README.md:62` |
| 12,244 star profiles | `README.md:574` |
| 42,000x speed-up; small stars sound higher | `README.md:496-499` |
| Evidence order (7 rules) | `README.md:160-176`, `pipeline/evidence.py:115-127` |
| Tech stack (Astropy, NumPy, scikit-learn, Aladin Lite, Node, FastAPI, React, Claude, GitHub Actions, node --test, unittest, pytest) | `README.md:23-25`, `653-673`, `817-819` |
| Footer sources exist | `README.md`, `docs/demo-script.md`, `BRAND.md` |
| "High-confidence" preset on survey | `app/survey.html:155` |

## Merge conflict: `docs/wiki/wiki/log.md`

`git merge-tree --write-tree a88e63a 64cb979` reports `CONFLICT (content)` in this file. Both sides append after
the same last line of the merge base (the 2026-11-14 live explorer entry).

Main side (`a88e63a`, added by the Star Fix merge):

```markdown
## [2026-11-15] run | star fix (work-lite)
- page: [[run-star-fix-2026-11-15]]
- branch: feature/star-fix 94381d1 (pushed, not merged)
- verdict: tech_lead PASS, project_manager PASS, user_advocate PASS (round 2)
```

Branch side (`64cb979`):

```markdown
## [2026-11-15] run | project explainer page
- file: artifacts/project-explainer.html (objectives, audience, use cases, architecture, stack)
- branch: docs/project-explainer, 479d910 (not pushed, not merged; needs review)
- artifact: https://claude.ai/code/artifact/8ef62b14-34ad-41c5-81ce-92aac295359a (private)
- source: README.md, docs/demo-script.md, BRAND.md at 184e071
- 2026-11-15 v2: text rewritten at kid level ("explain like I am 5"); technical names kept in small "Grown-up words" lines
```

How to combine: the log is append-only. Keep both entries, with no change to their text. Both have the date
2026-11-15. Put Star Fix first, because that run finished and reached main first. Put the explainer second.
Keep one blank line between entries.

Resolved file (for `64cb979`):

```markdown
# Log

## [2026-11-14] run | live explorer (work-lite)
- page: [[run-live-explorer-2026-11-14]]
- main: 0df4049 (pushed)
- verdict: tech_lead PASS, project_manager PASS, user_advocate PASS (fix-loop round 3)

## [2026-11-15] run | star fix (work-lite)
- page: [[run-star-fix-2026-11-15]]
- branch: feature/star-fix 94381d1 (pushed, not merged)
- verdict: tech_lead PASS, project_manager PASS, user_advocate PASS (round 2)

## [2026-11-15] run | project explainer page
- file: artifacts/project-explainer.html (objectives, audience, use cases, architecture, stack)
- branch: docs/project-explainer, 479d910 (not pushed, not merged; needs review)
- artifact: https://claude.ai/code/artifact/8ef62b14-34ad-41c5-81ce-92aac295359a (private)
- source: README.md, docs/demo-script.md, BRAND.md at 184e071
- 2026-11-15 v2: text rewritten at kid level ("explain like I am 5"); technical names kept in small "Grown-up words" lines
```

If the merge uses the tip `8587114`, use the same order. Its last explainer line is
`- 2026-11-15 v3: kid-level text reverted on user request; page is back to v1 (479d910 content)` in place of the v2 line.

Do not edit the old lines during the merge, because the log is append-only. To record the merge, append a new
line or a new entry after the conflict is resolved. Do not change the "not merged" text in the existing entry.
`docs/wiki/wiki/index.md` does not conflict (only main changed it).

## Not checked

- Live render in a browser (the Playwright browser was locked by another session). Static checks only.
- The published Artifact URL content (private; not read).
- Line-by-line review of the tip text (`8587114`). See H1.
