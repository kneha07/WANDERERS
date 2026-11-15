# Star Fix build report

Status: **DONE**, fix round 1 included. Branch `feature/star-fix` (worktree `.worktrees/star-fix`). Nothing is pushed.
Brief: [`docs/specs/star-fix-build.md`](../../docs/specs/star-fix-build.md). Reviews of round 1: `artifacts/review-tech_lead-star-fix.md`,
`artifacts/review-project_manager-star-fix.md`, `artifacts/review-user_advocate-star-fix.md`.
Only distances are written here. No GPS position of a sample photo is in this file or in the repo.

## 1. Acceptance criteria

Commands (from the worktree root, Windows, Git Bash), after fix round 1:

```bash
.venv/Scripts/python.exe -m unittest discover -s tests -p "test_star_fix.py"   # exit 0, 10 tests
node --test test/*.test.js                                                    # exit 0, 319 tests, 318 pass, 1 skip
```

The one skip is in `fields.test.js` ("python3 not available"); it is also on the base commit.

| # | Result | Evidence |
|---|---|---|
| A1 | PASS | Round trip, 3 places x 2 times x orientations 1, 3, 6, 8 x 3 random rotations, all < 2 km. The zenith comes from astropy `AltAz`, a path that `position()` does not use. |
| A2 | PASS | `20260614_082051102`: `fix`, 33 km from (-38.5, 145.2), `Carina`. |
| A3 | PASS | `20231125_204326416` (past the zenith): `fix`, 55 km from its own GPS. |
| A4 | PASS | `20231125_211246181` (twilight): `no_solve`. |
| A5 | PASS | Random bytes, an empty body and a 64 MP picture: `bad_file`. A JPEG copy without EXIF: `sky_only`, `missing` = `["gravity", "time"]`. |
| A6 | PASS | The four 14 June results: one night, 61 km from (-38.5, 145.2), radius 65.5 km. |
| A7 | PASS | `combine`, `circle` and `sessions` unit tests in `test/starfixcore.test.js`. |
| A8 | PASS | `test/starfix-server.test.js`: 400 empty; 413 above 30 MB, then health 200; 200 `bad_file`; 500 "Star Fix could not run..." without Python or with a missing package; 500 "Could not read this photo." after a crash; 409 busy. No answer holds a path. |
| A9 | PASS | No `python3` in `server.js`; `PY = process.env.WANDERERS_PY \|\| pickPython(__dirname)`. |
| A10 | PASS | `node --test test/*.test.js` exit 0. Before round 1, each old JS and Python test file also passed one by one. |
| A11 | PASS | Screenshots after the four 14 June photos: `page-light.png`, `page-dark.png` (1280 px), `page-phone-light.png`, `page-phone-dark.png` (390 px, mobile emulation). One block, place sentence, "Usually right to about 65 km.", GPS check line 61 km, map with the circle and two marks, list closed. |
| A12 | PASS | `test/compass-cta.test.js`. `home-1280.png`: three doors in one row at 1280 x 720, all above the fold. |
| A13 | PASS (browser) | Playwright: example first; gone after the first result; back after "Remove my photos". Static server: example, upload disabled, one line. |
| A14 | PASS | Exact `describe()` texts (round 1 words). No forbidden word in core text or in the visible text of `starfix.html`. |
| A15 | PASS | `app/data/starfix-sample.json`: 4 entries, each `gps` exactly `{"lat": -38.5, "lon": 145.2}`, 61 km. |
| A16 | PASS | One `btn-primary` (test). 390 px: no horizontal scroll. Every control takes focus with a 2 px outline. |
| A17 | PASS | JPEG q92 copy of `20260614_081100956`: 84 km from its own GPS (2840 km without the gate). The HEIC: 83 km. |

## 2. UX rules U1 to U10

| # | Result | How it was checked |
|---|---|---|
| U1 | PASS | Unit test and Playwright: rows and "Reading photo 1 of 4" show before the first request. |
| U2 | PASS | Unit tests: one request at a time, in order, dedupe also against waiting rows. A duplicate gives the status line "Already added: {name}" (Playwright). |
| U3 | PASS | Unit test and Playwright: a failed request gives "Could not read this photo." and Try again with the same File. The 75 s abort is in `photoQueue` (not run: 75 s). |
| U4 | PASS | Round 1: a summary click (mouse, Enter or Space) makes the list the person's; the automatic rule stops. Playwright: open list stays open after a duplicate; closed list stays closed after a refused file. |
| U5 | PASS | CLS at 390 px, first visit, empty cache: 0.003 (light), 0.003 (dark), 0.006 with fonts 1.2 s late and health 2.5 s late. Was 0.154. |
| U6 | PASS | The line shows and the control is disabled only after `/api/health` fails (static server). |
| U7 | PASS | Unit tests for `clear()` and `restore()`. Playwright: focus to the upload control, "Photos removed. Undo" for 8 s, Undo restores 4 results with 0 requests. |
| U8 | PASS | Playwright: drop state with "Drop to add"; `notes.txt` and a 31 MB file get their rows without a request. |
| U9 | PASS | The window and the circle glide together (400 ms), a newer answer starts from the drawn state, no motion under reduced motion. Now visible: the 65 km circle is 22 px (desktop) or 13 px (phone) in radius. |
| U10 | PASS | `aria-live="polite"`: "Reading photo N of M", then the final headline once. |

## 3. Fix round 1

| Item | Fix | Evidence | Commit |
|---|---|---|---|
| M1 map | Window from the data: half-height = 4 x max(radius, GPS distance), 2:1, 16 to 40 degrees across (the 16 degree minimum keeps the coastline readable); crop of `day.jpg`, smooth upscale. Ponytail note: about 20 km per pixel of `day.jpg`. | 65 km circle: radius about 22 px at 608 px width, 13 px at 358 px (was 9 and 5 px); Victoria and Tasmania readable. | `10ff89b`, then the 16 degree minimum |
| M2 doors | Row right under the lede; one row from a 1024 px window (text column 470 px and up), compact text while narrow; stacked below. | Door 3 bottom: 671 of 720 px (1280 x 720), 615 of 768 (1024 x 768). `home-1280.png`. | `5db6315` |
| M3 U4 | `touched` from the summary click; no automatic change after that. | Playwright, see U4. | `10ff89b` |
| M4 CLS | The drop hint has its own line (as the wireframe). | CLS 0.003 to 0.006 at 390 px. | `10ff89b` |
| L-a | "Could not read this photo." next to "Try again". | A14 test. | `10ff89b` |
| L-b | "This file is not a photo. Choose a .heic or .jpg file." / "This file is too large (30 MB limit). Use the original photo." | A14 test. | `10ff89b` |
| L-c | `night(rows)`: refused files listed, not counted; an outlier counts but is not used; the headline count is the used photos. | Unit test "night". Playwright: "4 photos used" after a refused file. | `10ff89b` |
| L-d | "No place found from these photos." ("yet" only while photos wait or are read). | Unit test. | `10ff89b` |
| L-e | "Already added: {name}" in the existing status line. | Unit test (`add()` returns the names), Playwright. | `10ff89b` |
| L-f | Two 500 answers: setup missing (spawn error, "No module named") vs a crash on this photo. | Server tests with node as the interpreter and a shadowed `pillow_heif`. | `726c7a7` |
| L-g | Pictures above 60 MP are `bad_file` before decoding; Pillow's `DecompressionBombError` also gives `bad_file`. | Unit test (64 MP PNG); 144 MP answers in 0.0 s. | `16ba4bd` |
| F5 | This report now lists the screenshot files that exist. | Section 1, A11 and A12. | this commit |

The spec now matches the code: sections 6, 8, 10.1, 10.2 (words, lines, map) and 10.4 (U2, U4, U5).

## 4. Decisions kept from the build

- Map marks use the Night accent `#8AB6EF` in both themes (`--map-accent`): the map is always dark.
- `zone_mismatch` compares longitudes across 180 degrees.
- `warnings` is in `fix`, `sky_only` and `no_solve` (needed for `small_photo`).
- A result without a time (`no_solve`, `bad_file`, errors) joins the newest night (orchestrator rule 5b).
- A new night goes on top; blocks are not sorted again.
- The OpenStreetMap link opens a new tab, so the results stay.

## 5. Leftovers (not fixed in round 1)

- Orientation 3 and 8 have no photo test (TL M2). A2 covers orientation 1; A3, A17 and the other portrait photos cover 6. A1 checks the table for all four.
- No automatic test for the 60 s kill (504); the tech lead checked it by hand.
- The Undo line ends after 8 s (WCAG 2.2.1 asks for a way to extend it).
- With a large radius the nearest city can be a small place ("near San Tung Chung Hang"); a better rule would prefer the largest city inside the circle.

## 6. Commits

```
e191f88 step 1: pipeline/star_fix.py and tests A1-A5
0c3785c step 2: app/starfixcore.js, example data
6eb5247 step 3: POST /api/star-fix, pickPython (#27), server tests
9ae15d2 solve quality gate (A17) and small_photo
f41a4a1 step 4: start.js solver install, requirements
05ce9c4 step 5: the page
24f3515 step 6: home hero doors, footer link
32e81f1 step 7: README and architecture.md
502ad47 page: km number in mono
f41e46a build report
16ba4bd fix round 1 L-g: bad_file above 60 MP
726c7a7 fix round 1 L-f: two 500 answers
10ff89b fix round 1 M1, M3, M4, L-a to L-e
5db6315 fix round 1 M2: doors in one row from 1024 px
5d74369 fix round 1: new A11 screenshots
```
