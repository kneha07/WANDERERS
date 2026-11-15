# Star Fix build report

Status: **DONE**. Branch `feature/star-fix` (worktree `.worktrees/star-fix`), 10 commits on top of `docs/star-fix-design`.
Nothing is pushed. Brief: [`docs/specs/star-fix-build.md`](../../docs/specs/star-fix-build.md).
Only distances are written here. No GPS position of a sample photo is in this file or in the repo.

## 1. Acceptance criteria

Commands (from the worktree root, Windows, Git Bash):

```bash
.venv/Scripts/python.exe -m unittest discover -s tests -p "test_star_fix.py"     # exit 0, 9 tests, 41 s
node --test test/starfixcore.test.js test/starfix-server.test.js test/compass-cta.test.js \
  test/home.test.js test/server.test.js test/fields.test.js                          # exit 0, 70 pass, 1 skip
```

| # | Result | Evidence |
|---|---|---|
| A1 | PASS | `test_round_trip_for_every_orientation`: 3 places x 2 times x orientations 1, 3, 6, 8 x 3 random rotations, all < 2 km. The zenith comes from astropy `AltAz` (alt 90), a path that `position()` does not use. A wrong axis table fails the test (checked). |
| A2 | PASS | `20260614_082051102`: `fix`, 33 km from (-38.5, 145.2), `Carina`, 53 matches. |
| A3 | PASS | `20231125_204326416` (past the zenith): `fix`, 55 km from its own GPS. |
| A4 | PASS | `20231125_211246181` (twilight): `no_solve`. `stars` is 381 now (see 4.2). |
| A5 | PASS | Random bytes and an empty body: `bad_file`. A JPEG copy without EXIF: `sky_only`, `missing` = `["gravity", "time"]`, `Carina`. |
| A6 | PASS | The four 14 June results: one night, 61 km (60.6) from (-38.5, 145.2), radius 65.5 km (shown as 65). |
| A7 | PASS | `combine` and `circle` tests in `test/starfixcore.test.js`: one far photo moves the answer < 50 km and is in `outliers`; 1 photo gives 150 km; 2 h apart gives two nights; every circle point is within 1 %. |
| A8 | PASS | `test/starfix-server.test.js`: empty 400; 31 MB 413 (`{"error":"photo too large"}`), then `/api/health` 200; random bytes 200 `bad_file`; no Python 500 with the fixed message; 409 while one is read. No answer holds a path. |
| A9 | PASS | `server.js` has no `python3`. `PY = process.env.WANDERERS_PY \|\| pickPython(__dirname)` (source test). |
| A10 | PASS | All 29 JS test files that passed on the base commit still pass, one by one (list in 3). All 10 Python test files pass. Nothing failed on the base commit. One skip in `fields.test.js` ("python3 not available") is also on the base commit. |
| A11 | not run (orchestrator) | Checked in Playwright, 1100 px, both themes: four 14 June files give one block; headline "about 130 km south-east of Geelong, Australia"; "Usually right to about 65 km."; check line "61 km"; map with two marks; the answer is above the list and the list is closed ("4 photos used"). No screenshot file was saved to the repo. |
| A12 | PASS | `test/compass-cta.test.js`: hero links `observatory.html`, `compass.html`, `starfix.html`, exact door words, How It Works in the top navigation, footer link. Doors are 56 px high (phone). |
| A13 | not run (orchestrator) | Checked in Playwright: the example shows first with "Example"; it goes after the first result; "Remove my photos" brings it back. On a static server (`python -m http.server -d app`) the example shows, the upload is disabled and the one line shows. |
| A14 | PASS | `describe()` exact text for every case, warnings included. No forbidden word in `describe()`, `headline()`, `photosLine()`, `reading()` or the visible text of `starfix.html` (templates and aria labels included). |
| A15 | PASS | `app/data/starfix-sample.json`: 4 entries, each `gps` is exactly `{"lat": -38.5, "lon": 145.2}`, combined 61 km from it. |
| A16 | PASS (source) + checked | One `btn-primary` (test). Playwright at 390 px: `scrollWidth` = `clientWidth`. Every control takes focus and shows a 2 px outline (the file input shows it on its label). |
| A17 | PASS | `test_weak_false_solve_of_a_recompressed_photo_is_refused`: JPEG q92 copy of `20260614_081100956` is 84 km from its own GPS (2840 km before the gate). The original HEIC: `fix`, 83 km. |

## 2. UX rules U1 to U10

| # | Result | How it was checked |
|---|---|---|
| U1 | PASS | Unit test: every row exists ("waiting") before the first request. Playwright: rows and "Reading photo 1 of 4" show at once. |
| U2 | PASS | Unit tests: one request at a time, in order; added files go to the end; the same name and size is skipped, also while it waits. Playwright: a second copy of a photo did not add a row. |
| U3 | PASS | Unit test: a failed request becomes `error`; Try again sends the same File object. Playwright: a forced network error shows "Could not read this photo. Add it again." and Try again; the retry gives the real answer. The 75 s abort is in `photoQueue` (not run: it needs 75 s). |
| U4 | PASS | Keyed blocks and rows, text set only when it changes, rows move only when their place changes. A new night goes on top. Note in 4.1. |
| U5 | PASS | Canvas has `aspect-ratio: 2 / 1`. The example slot keeps a reserved height until the sample and the city list load (within about 11 px of the real height). |
| U6 | PASS | The control stays on while `/api/health` is pending; it is disabled and the line shows only after a failure (Playwright, static server). |
| U7 | PASS | Unit tests for `clear()` and `restore()`. Playwright: Remove shows the example, focus goes to the upload control, "Photos removed. Undo" shows for 8 s; Undo brings 4 results back with 0 requests. No `confirm()` (source test). |
| U8 | PASS | Playwright: dragover shows the accent outline and "Drop to add"; dragleave and Escape remove it. `notes.txt` gives "This file is not a photo." and a 31 MB file gives the 30 MB text, both without a request. |
| U9 | PASS (code) | A newer answer cancels the running 400 ms glide and starts from the drawn circle; no motion under `prefers-reduced-motion`. No frame capture was made. |
| U10 | PASS | The progress region is `aria-live="polite"`: "Reading photo N of M", then the final headline once (visually hidden). Rows have a mark and words. |

## 3. Full test run (A10)

JS, each file on its own, exit 0: `aladinlink`, `chartlayout`, `compass-cta`, `compass-flows`, `compass-sightcheck`,
`compass-style`, `fields` (1 skip, also on base), `frameinfo`, `framemath`, `hips`, `home`, `liveproxy`, `observatory`,
`orient`, `pathview`, `physicspath`, `search-compass`, `search`, `server`, `sky-compass`, `sky`, `skyview`, `starcore`,
`stardb`, `starpath`, `starprofile`, `starquake`, `telescope`, `theme` (all `test/<name>.test.js`), plus the new
`starfix-server` (6) and `starfixcore` (23).

Python, exit 0: `tests/test_data_quality.py`, `test_evidence.py`, `test_fetch.py`, `test_link_paths.py`, `test_movers.py`,
`test_star_ml.py`, `test_star_trajectory.py`, `test_starquake.py`, `test_vet.py`, `test/test_fov.py`, plus the new
`tests/test_star_fix.py` (9).

All 14 sample photos with the gate (distance to each file's own GPS): 2023 night: 50 and 55 km, four `no_solve`;
14 June: 115, 84, 155, 34 km; 19 June: 94, 105, 44, 63 km.

## 4. Decisions and differences from the brief

### 4.1 Page

- The photo list and its queue are a pure function `photoQueue(send, onChange)` in `starfixcore.js`, so that dedupe,
  order, Try again and Undo have unit tests without a browser.
- The list of a night is open while photos are read or when a photo was not used, and closed when every photo was used.
  This rule stops when the person opens or closes the list. Exception (U4): a photo that becomes "not used" always opens it.
  Reason: U4 alone would keep the list open after a run, and A11 needs it closed.
- When files arrive, the new night block shows at once at the top with its rows. The example stays below it until the
  first result (brief 10.2.5), then it is hidden.
- A result without a time (`no_solve`, `bad_file`, errors) joins the newest night (orchestrator rule 5b). Example: a
  2023 twilight photo uploaded with 14 June photos shows in the 14 June list.
- Blocks are not sorted again by date: a new night goes on top (U4), so nothing moves under the person.
- Files with no `.heic`, `.heif`, `.jpg`, `.jpeg` or `.png` name get "This file is not a photo." without a request.
- The map marks use the Night Observatory accent `#8AB6EF` in both themes (`--map-accent` on `.sf-map`). The map is
  always dark; the Day accent was weak on the dark sea. The legend uses HTML text, so the A14 test reads it.
- The "Open in OpenStreetMap" link opens a new tab, so the results stay.
- Only the number of a km value is mono, so no wide mono space comes before "km".

### 4.2 Python and server

- `zone_mismatch` compares longitudes across 180 degrees (wrapped difference). The plain formula flags 179 W vs UTC+12.
- Quality gate (A17): `MIN_MATCHES 8`, `MAX_RMSE_ARCSEC 300`, `MAX_FALSE_PROB 1e-8`. A weak solve now tries the next
  sigma or crop. The first 14 June photo now takes its 51-match solve; the example JSON was made again (still 61 km).
- `stars` in `no_solve` is the spot count of the last try (whole picture, sigma 2), as in `probe.py`. With the gate the
  twilight photo reaches that try, so it reports 381 (11 before). The page does not show this number.
- `warnings` is in `fix`, `sky_only` and `no_solve` (needed for `small_photo`). `small_photo`: long side below 1600 px.
- 504 (60 s) is not in an automatic test: it needs 60 s.
- Home doors: three across when the hero text column is at least 600 px wide, else stacked (container query). At 1440 px
  they are three across; at 900 to 1100 px and on a phone they stack.

## 5. Commits

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
```

Not done here: the A11, A13 and A16 screenshot files (orchestrator), push, pull request.
