# Tech lead review: Star Fix build (`feature/star-fix`)

Scope: `git diff 1275527..HEAD` (23 files). Spec: `docs/specs/star-fix-build.md` sections 6-11, 10.4, 10.5.
Reference maths: `artifacts/star-fix/win/probe.py`. Builder report: `artifacts/star-fix/build-report.md` (checked, not trusted).

## Verdict: PASS

No high finding. Two medium findings and several low findings. None blocks a merge.

## What I ran

```
.venv/Scripts/python.exe -m unittest discover -s tests -p "test_star_fix.py"   -> 9 tests OK (33 s)
node --test test/*.test.js                                                    -> 317 tests, 316 pass, 1 skip (fields.test.js, python3 absent; on base too)
```

Live server checks (copy of the unchanged `server.js` + `fields.js` in the scratchpad, fake `pipeline/star_fix.py`):

| Check | Result |
|---|---|
| Solver that sleeps 150 s | second request `409 busy`; first request `504 {"error":"timed out"}` at 60 s |
| Process tree after the 504 | python.exe count back from 4 to 2: `taskkill /T` killed the launcher and its child |
| Busy flag after the 504 | next request accepted (not 409) |
| Client drops the request mid-body | next request `200`: busy flag released by `req` `close` |
| 31 MB body | `413`, then the next request `200` |

## Python: `pipeline/star_fix.py` against `probe.py`

Line-by-line match with the verified maths:

- `AXES` table (`star_fix.py:40`) is identical to `probe.py:40` and to spec 7.1.
- `up_cam` (`:149-153`) = `probe.py:41-42` (`up = -normalize([X, Y, -gz])`).
- TAN fit + 3 refits with `proj_point` at `(W/2, H/2)` (`:141-143`) = `probe.py:73-74`. Crop offset added (`:140`), and `ox, oy` are from the crop that solved (the loop breaks before they change).
- `cam_to_sky` (`:99-109`) = `probe.py:32-38` (9 x 9 grid, focal length from the WCS, SVD with det fix).
- `position` (`:156-164`): zenith to TETE, `lon = ra - GAST(apparent)`, wrap at 180 = `probe.py:80-82`. `camera_alt` = `probe.py:83`.
- Orientation source: `original_orientation or 274 or 1`, read before `exif_transpose` (`:71`, `:174-176`). I checked pillow-heif 1.8.1: it stores `original_orientation` only when it is not 1 and resets 274, so orientation 3 HEIC is also handled. Mirrored values go to `sky_only` (`:181`).
- Solve gate `Matches >= 8, RMSE <= 300, Prob <= 1e-8` (`:35`, `:132`) matches 10.5. A weak solve falls through to the next sigma/crop. A17 test proves the gate on the real false solve.
- IERS offline settings (`:27-28`) as spec 7.3.

## Server: `server.js` `/api/star-fix`

- 30 MB limit, busy flag, 60 s timeout, `taskkill /T /F` on win32, `p.stdin` error handler, stderr ignored, generic 500 text: all present (`server.js:101-145`) and verified live (table above).
- Busy flag is released on every path I traced: 400/413 (`:140-143`), client abort (`:139`), spawn error (`:118`), close (`:119`). The `reply` guard (`:132`) makes the late `close` after a 504 harmless.
- No path leaks: Python tracebacks go to stderr (ignored); a non-zero exit gives the fixed 500 text. The test regex `PATHLIKE` covers drive letters, home dirs and `.py`.

## Findings

### M1 (medium) - the error circle cannot be seen on the map; the spec's scale note is wrong

- Where: `app/starfix.js:131` (fixed 40 x 20 degree window), `:138-143` (circle, reticle ticks 5-9 px, dot 2.5 px), spec section 10.2 "Map".
- Scenario: 65 km = 0.585 degree of latitude. In the 608 x 304 px map (`page-light.png`) that is 8.9 px. The reticle ticks reach 9 px, so the circle sits on the tick ends. On a phone (`page-phone-dark.png`, about 358 px wide) the radius is about 5 px: the circle is inside the reticle and the 5 px GPS ring. With 4 photos the person cannot see the circle at all, and the 400 ms "circle tightens" motion (150 km -> 65 km = 20 px -> 9 px) is almost invisible.
- Judgement on the orchestrator note: the code follows the spec text (40 x 20 degrees). It is not an implementation defect. It is a spec defect: the spec comment says "20 km per pixel", but the real scale is about 7 km/px wide and 12 km/px on a phone, and at that scale the circle the spec asks for is drawn under the reticle. The design goal "the person sees the circle tighten" (10.2) is not met.
- Fix: size the window from the radius (for example half-height = max(4 x radius, 300 km), width = 2 x height), or draw the reticle inside the circle only when the circle is large. Update the spec line and the `ponytail:` comment to the true scale.

### M2 (medium) - the orientation table is physically proven for portrait only

- Where: `tests/test_star_fix.py:47-51` (`gravity()`), `:55-65` (A1); photo tests A2, A3, A17.
- Scenario: A1 builds `g` with a hand-written inverse of the same spec table. It catches a drift between `AXES` and the table (good), but if the table itself were wrong for orientation 1, 3 or 8, A1 still passes. The sample photos in the tests are portrait (orientation 6). A wrong landscape row gives a fix thousands of km off with status `fix` and no warning (the zone check catches only errors above 45 degrees of longitude).
- Fix: add one photo test per landscape orientation (1 and 3) if a sample exists; else write the probe evidence (which of the 14 photos had which orientation) into the build report so the claim "checked on 14 photos" covers each row.

### L1 (low) - outlier still counts in the headline

- Where: `app/starfixcore.js:41-42`, `app/starfix.js:47`.
- Scenario: `headline(..., fixes.length)` counts outliers. With 3 photos, one "Not used", the summary says "2 of 3 photos used" but the hint "Add 2 or more photos" is suppressed and the position still includes the outlier in the component median. The spec accepts the median; the count mismatch is cosmetic.
- Fix: pass the used count (`fixes.length - outliers.length`) to `headline`.

### L2 (low) - untested 60 s kill path

- Where: `server.js:107-113`; `test/starfix-server.test.js` has no timeout test (report 4.2 admits it).
- Scenario: a regression in the kill path (for example `p.kill()` only on Windows) leaves an orphan interpreter and a held busy flag; no test fails. I verified it manually (table above), so it works today.
- Fix: make the 60 s a module constant that an env var can lower in tests, and add one test with a sleeping fake script.

### L3 (low) - uncaught Python exceptions read as "could not run, start the app with start.cmd"

- Where: `pipeline/star_fix.py:67-91` (`read_meta` outside the try), `:112-146`.
- Scenario: an odd EXIF (MakerNote given as `str`, corrupt IFD) or a solver exception gives exit 1 -> 500 with the setup message, although setup is fine. The page shows "Could not read this photo" and offers Try again, which fails the same way.
- Fix: wrap `star_fix()` body after open in one `try` that returns `bad_file` (or a new `error` status) and still exits 0.

### L4 (low) - decompression bomb warning is muted

- Where: `pipeline/star_fix.py:26` (`warnings.filterwarnings("ignore")`).
- Scenario: a 30 MB PNG can decode to up to 179 MP (Pillow's hard limit) with no warning; RGBA + transpose + convert can need 1-2 GB. Local single-user tool, so low.
- Fix: set `Image.MAX_IMAGE_PIXELS` to about 60 MP (largest iPhone sensor 48 MP).

### L5 (low) - solver not in `requirements.txt`; photo tests skip silently elsewhere

- Where: `start.js:121-123` (`cedar-solve==0.5.1 --no-deps`), `pipeline/requirements.txt`.
- Scenario: on a machine that installs only `requirements.txt` (CI, Linux, a teammate without `start.js`), A2-A5 and A17 skip and the server test checks for `pillow_heif, PIL, astropy` only. Green without the solver. The reason for `--no-deps` (old Pillow pin) is sound and documented.
- Fix: none required for the hackathon; mention in README test notes that the photo tests need `cedar-solve`.

### L6 (low, pre-existing, out of diff) - sample photos with full GPS are tracked in git

- Where: `star_image/` (14 HEIC files, added in `72ba60f`, already on `origin/main`).
- Scenario: the spec says "Do not write a GPS coordinate of a sample photo into the repo", but the original files carry their exact GPS in EXIF. This diff does not add them and writes no coordinate itself (I grepped the diff: only Phillip Island, Melbourne and test points). Owner decision.

### L7 (low, UX, for user_advocate) - phone layout has no right gutter

- Where: `artifacts/star-fix/page-phone-dark.png`: map, upload box and dividers run to the right edge at 375 px.
- Not a correctness issue; flagged so the user-advocate seat checks it.

## Other items checked, no finding

- `starfixcore.js`: median of unit vectors + normalise (`:38-39`), radius rule (`:41`), outliers >300 km with 3+ photos (`:42`), destination-point circle (`:46-53`, test checks 1 % incl. pole and 180), `nearestCity` linear scan, `direction` bearing city -> answer (spec: "from the city to the answer"), `sessions` 60 min gap.
- `photoQueue`: one loop (`running`), 75 s abort, `gen` drops stale answers after `clear()`, `restore()` re-reads only unfinished rows, dedupe by name + size incl. waiting rows, retry only for `error`. Tests cover each, including restore right after clear.
- XSS: file names via `textContent` (`starfix.js:78`); all other text via `setText`/`setKm` (text nodes); `aria-label` via `setAttribute`; OSM link built from numbers, `rel="noopener noreferrer"`. No `innerHTML` in the page script.
- `start.js`: import check now includes `pillow_heif, tetra3`; `import tetra3` works with numpy 2.5 (verified, rc 0), so the check does not loop into a reinstall on every start.
- Tests are real: A1 uses an independent AltAz zenith; A17 reproduces the actual false solve; A14 forbidden-word check proves itself (`!clean("Fixed")`); server tests use real servers and a real missing interpreter.
