# Project manager review: Star Fix (round 1)

Reviewer: project_manager (independent). Branch `feature/star-fix`, diff `1275527..HEAD` (11 commits, 23 files).
Spec: `docs/specs/star-fix-build.md`. Builder report: `artifacts/star-fix/build-report.md` (checked, not trusted).

**Verdict: PASS.** No high finding. Two medium findings need an owner decision or a small follow-up. They do not block the merge.

## Commands run by this reviewer

| Command | Result |
|---|---|
| `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_star_fix.py"` | exit 0, `Ran 9 tests in 34.8s OK`, no skips |
| `node --test test/*.test.js` | exit 0, 317 tests, 316 pass, 0 fail, 1 skip (`fields.test.js` "python3 not available", on base too per report) |
| Static server `python -m http.server 8077 -d app`, Playwright 390 px, `starfix.html` | example visible with "Example · 14 June 2026"; upload disabled; offline line visible; 1 `.btn-primary`; `scrollWidth 375 = clientWidth 375` |
| `git merge-base --is-ancestor e191f88 main` | not on main; `git branch --contains` lists only `feature/star-fix` |
| grep of the diff for decimal coordinates | only Phillip Island (-38.5, 145.2), star estimates, Melbourne (city test), spec example values. No sample-photo GPS. |

## Per-criterion map

| # | Status | Evidence |
|---|---|---|
| A1 | PASS | `tests/test_star_fix.py:55` round trip, orientations 1/3/6/8; suite exit 0 |
| A2 | PASS | `tests/test_star_fix.py:81`; suite exit 0 (report: 33 km, Carina) |
| A3 | PASS | `tests/test_star_fix.py:91` (< 150 km from file's own GPS, distance only) |
| A4 | PASS | `tests/test_star_fix.py:121` `no_solve` |
| A5 | PASS | `tests/test_star_fix.py:126`, `:139` |
| A6 | PASS | `test/starfixcore.test.js:63` (one night, within 120 km, radius 50-150) |
| A7 | PASS | `test/starfixcore.test.js:15,27,42,51` |
| A8 | PASS | `test/starfix-server.test.js:37,41,51,56,61`; 413 path `server.js:138-143` |
| A9 | PASS | `server.js:23` `PY = process.env.WANDERERS_PY \|\| pickPython(__dirname)`; no `python3` (grep empty); test `starfix-server.test.js:73` |
| A10 | PASS | full `node --test test/*.test.js` exit 0; full Python run per report (only `test_star_fix.py` re-run here) |
| A11 | PARTIAL (low-medium) | Content matches: headline with place name, "Usually right to about 65 km.", GPS check line, map with two marks, answer above a closed "4 photos used" list (`page-light.png`, `page-dark.png`, `page-phone-dark.png`). Gap: no phone light shot; names differ from `page.png`/`page-phone.png`; taken on :8010, phone at 375 px not 390 px. See F2. |
| A12 | PASS | `test/compass-cta.test.js:37-51`: links `observatory.html, compass.html, starfix.html`, door words, How It Works in nav, footer link |
| A13 | PASS | Static-server half verified by this reviewer (above). Live half (example goes after first result, Remove brings it back) by code: `app/starfix.js` `sync()` (`exampleEl.hidden = any`) and the `remove` handler; unit tests `starfixcore.test.js:226,244`. No screenshot of the live half. |
| A14 | PASS | `test/starfixcore.test.js:77,150,264` |
| A15 | PASS | `app/data/starfix-sample.json`: 4 entries, every `gps` `{"lat": -38.5, "lon": 145.2}`; test `starfixcore.test.js:63` |
| A16 | PASS | 1 primary button and no horizontal scroll measured here; focus by builder Playwright only (not re-checked) |
| A17 | PASS | `tests/test_star_fix.py:96`; gate constants per report 4.2 |
| small_photo | PASS | `tests/test_star_fix.py:112`; text in `app/starfixcore.js` `WARN.small_photo` matches 10.5 |
| U1/U2 | PASS | `starfixcore.test.js:175,195`; `photoQueue.add` calls `onChange()` before `pump()` |
| U3 | PASS (75 s not run) | `photoQueue` `setTimeout(() => ctrl.abort(), 75e3)`; retry test `:212` |
| U4 | PASS (code) | keyed `blocks`/`rowEls` maps, `setText` only on change, `touched` flag in `makeBlock` |
| U5 | PASS (code) | `aspect-ratio`, `sf-reserve` removed in `finally` |
| U6 | PASS | upload disabled only in the `/api/health` catch; verified on static server |
| U7 | PASS | remove handler: `input.focus()`, `undoBox`, 8000 ms timer; no `confirm` (test `:278`) |
| U8 | PASS | `starfixcore.test.js:204`; drag state in `starfix.js` |
| U9 | PASS (code) | `draw()` cancels `b.anim`, starts from `b.drawn`; `still.matches` skips motion |
| U10 | PASS (code) | `aria-live="polite"` region, headline set once when the run ends |

## Scope, design and goal

- In scope only. Nothing from the "Out" column of spec section 3 is built. `app/sw.js` is not touched (spec 5).
- Docs: `README.md` and `docs/architecture.md` add the route, page and test commands, short. PASS.
- No TODOs, no mocked behaviour, no deleted tests. The `compass-cta` test was changed as spec 10.1 says (`#how` removed from the hero list), and it gained checks.
- Extra file `artifacts/star-fix/compress_test.py` is the measurement script that backs spec 10.5. It reads sample GPS at runtime and prints only distances. Acceptable.
- Privacy rule held: no sample-photo GPS in the diff. `starfix-sample.json` holds star estimates (34-155 km from truth), which the spec asked for.

## Builder deviations

| Deviation | Ruling |
|---|---|
| Map accent `#8AB6EF` in both themes (`--map-accent`) | Accept. Spec 10.3 says the map sits on `--viewer` in both themes, so it is always dark; one accent is consistent with that. It is a new literal colour, though it is the existing Night accent. Owner FYI, no decision needed. |
| List open while reading, closed after | Accept. Spec 10.2 wireframe "Working" shows "▾ Photos" open; A11 needs it closed at the end. Consistent with the spec. |
| `zone_mismatch` wrapped across 180° | Accept. Fixes a false flag of the literal formula (spec 6). Improvement, same intent. |
| `photoQueue` in `starfixcore.js` | Accept. Spec 10.4 U2 names `photoQueue` in `starfixcore.js`. Not a deviation. |
| Doors three across only at ≥600 px container | Medium, F1. Owner decision. |
| `warnings` also in `sky_only`/`no_solve` | Accept. Needed for `small_photo`; additive to the contract. |
| Untimed rows join the newest night | Accept. Matches the orchestrator rule cited in the report. |

## Findings

| ID | Severity | Finding | Action |
|---|---|---|---|
| F1 | medium | Home doors stack at common laptop widths (900-1100 px per report 4.2). Spec 10.1 wireframe shows three across; it only says "on a phone the doors stack". At a 1000 px laptop the hero is a column of three, not the drawn row. | Owner decides: accept stacking, or lower the threshold. No screenshot of the home hero exists, so the owner cannot judge it from evidence. |
| F2 | medium | A11 evidence gap: brief asks for `page.png` and `page-phone.png` in both themes. Present: `page-light.png`, `page-dark.png`, `page-phone-dark.png`. Missing: phone light. Phone shot is 375 px, not 390 px. The content check still passes on all three. | Add `page-phone-light.png` at 390 px, or the owner accepts three shots. Renaming is not needed; record the names in the build report. |
| F3 | low | Map scale: in the 40 x 20° window the 65 km circle is about 12 px on desktop and about 7 px on phone, and the GPS ring overlaps the reticle (`page-phone-dark.png`). It meets the spec (and the `ponytail:` comment names the limit) but the "circle tightens" motion is barely visible. | Follow-up idea for `user_advocate`; not a gap against the spec. |
| F4 | low | Not tested automatically: 504 after 60 s, 75 s browser abort, live A13 half, focus ring (A16). All are in code and named as not run in the report. | Named; accept. |
| F5 | low | `build-report.md` line 113 says the screenshot files are not done; they now exist (commit `02c5cf1`). Report is stale on that line. | Update the line when F2 is closed. |

## ack

No high finding. All required criteria are met by tests that this reviewer ran, or by code plus a direct browser check.
Open items are evidence coverage and one layout choice for the owner.

## Round 2

Scope: fix commits `3e3e6d3..HEAD` (7 commits, 19 files). This reviewer did not write them.

**Verdict: PASS.** No high finding. F1, F2 and F5 are closed. Two new low findings do not block the merge.

### Commands run by this reviewer

| Command | Result |
|---|---|
| `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_star_fix.py"` | exit 0, `Ran 10 tests in 41.2s OK` (new: 64 MP refusal) |
| `node --test test/*.test.js` | exit 0, 319 tests, 318 pass, 0 fail, 1 skip (`fields.test.js`, same as base) |
| PIL size of the screenshots | `home-1280` 1280x720; `page-light`/`page-dark` 1265x1254; `page-phone-light`/`page-phone-dark` 390x1099 |
| `gh issue view 57 -R kneha07/WANDERERS` | OPEN, "Privacy: star_image/ photos on public main hold exact GPS", names 3 owner options and the force-push approval |

### Round-1 findings

| ID | Status | Evidence |
|---|---|---|
| F1 doors | Closed | `app/home.css`: 3 columns, stack only at `@container (max-width: 469px)`; row moved under the lede (`app/index.html`, test regex `test/compass-cta.test.js:39`). `home-1280.png` (viewed): three doors in one row, bottom about 671 of 720 px, all above the fold. Spec 10.1 records the rule and the measurement. |
| F2 A11 shots | Closed | Four shots exist. `page-phone-light.png` (viewed) is 390 px wide: one block, headline with place, "Usually right to about 65 km.", check line 61 km, map with two marks and a legend, "4 photos used" closed. Names differ from the brief (`page.png`); the build report A11 row names them. Accepted. |
| F3 map scale | Improved | Window from the data (spec 10.2 map paragraph); circle visibly bigger than the reticle in `page-phone-light.png`. |
| F4 not automated | Unchanged, named | Build report section 5 names the 60 s kill. 75 s abort named under U3. |
| F5 stale report | Closed | `build-report.md` A11/A12 rows list the files that exist; F5 row in section 3. |

### Spec and code agreement (sections 6, 8, 10.1, 10.2, 10.4)

| Spec item | Code | Agree |
|---|---|---|
| 6: two 500 answers, "No module named" separates them | `server.js` `STAR_FIX_CRASH`, `/No module named/.test(err)`; test `starfix-server.test.js` "a crash after the start..." | Yes |
| 6: `bad_file` above 60 MP before decoding | `pipeline/star_fix.py` `MAX_PIXELS = 60_000_000`, check before `im.load()`; `tests/test_star_fix.py` 64 MP test | Yes |
| 6: `warnings` in fix/sky_only/no_solve, 180-degree wrap, `small_photo` | Matches round-1 builder deviations, now written in the spec | Yes |
| 8: `headline(..., example, pending)`, `night(rows)`, `add()` returns names | `app/starfixcore.js` `headline`, `night`, `photoQueue.add` `again` | Yes |
| 10.2 words table | `TEXT` in `starfixcore.js`; exact-text test `starfixcore.test.js:84-86` | Yes |
| 10.2 "No place found from these photos." / "yet" only while pending | `headline` and tests `starfixcore.test.js:134-135` | Yes |
| 10.2 / U2 "Already added: {name}" | `app/starfix.html:58` `dupBox`; test list includes "Already added:" | Yes |
| 10.4 U4 touched rule, U5 drop hint own line + CLS | Code per build report U4/U5 (Playwright, not re-run here) | Yes (code + builder evidence) |

### A14 on the changed words

All new strings checked against `/plate|solve|zenith|session|outlier|exif|makernote|gravity|fix/i` (after removing "Star Fix"):
"Could not read this photo.", "This file is not a photo. Choose a .heic or .jpg file.", "This file is too large (30 MB limit). Use the original photo.",
"No place found from these photos." (and "... yet."), "Already added:". None hits. The core test (`starfixcore.test.js:151`) and the page test (`:276`) run them and pass.
The `{name}` after "Already added:" is the person's own file name; it is not app text and is outside A14.

### Leftovers in `build-report.md` section 5

| Leftover | Listed |
|---|---|
| Orientation 3 and 8 without a photo test | Yes |
| 60 s kill (504) without an automatic test | Yes |
| Undo fixed at 8 s (WCAG 2.2.1) | Yes |
| Nearest-city choice with a large radius | Yes |
| star_image GPS privacy | Not in section 5, but issue #57 owns it (OPEN, owner decision, force-push needs approval) |

### New findings

| ID | Severity | Finding | Action |
|---|---|---|---|
| R2-1 | low | `build-report.md` section 6 commit list stops at `5d74369`; `b62b108` (16-degree map minimum) and `bcc72d0` are missing. Section 3 M1 row does name "then the 16 degree minimum". | Add the two lines when the report is next touched. |
| R2-2 | low | Spec `docs/specs/star-fix-build.md:491` A14 status column still says "not yet built" (other A rows probably too). Stale status, not a gap. | Update the status column or drop it. |
| R2-3 | low | Build report section 5 does not point at issue #57. The issue exists, so nothing is hidden. | Optional: add one line "GPS in star_image/: issue #57". |

ack: no high and no medium finding remains. All required criteria are met by tests run here (both suites exit 0) or by code plus viewed screenshots.
