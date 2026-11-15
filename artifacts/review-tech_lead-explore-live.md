# Tech-lead review: WANDERERS "Explore any patch" live mode

- Seat: tech_lead (independent; I did not write this code).
- Repo: kneha07/WANDERERS, local `main`. Range `6a1b159..0def95a` (HEAD is now `9bb0981`; that commit adds only the round-2 record, outside this scope).
- Scope: `backend/`, `web/`, `start.js`, `start.cmd`, `start.command`, `docs/blink/`, `.gitignore`; in `server.js` and `app/app.js` only the `/explore/` route, the `/api/frames` + `/api/live-health` proxy and the "Explore this patch live" link.
- Date: 2026-11-14.

## Verdict

**PASS.** No high finding. 6 medium, 9 low.

The astronomy geometry is correct and consistent end to end (backend grid, PNG flip, ring, centroid, Gaia ghosts, front-end `pixelToSky`/`skyToPixel`). The trust boundaries hold. The open risks are: cache durability (degraded and stale results are pinned forever), a spectral mix in the blink and difference images, slow fail-soft paths, and no tests for the I/O orchestration.

## Evidence I gathered myself

| Check | Result |
|---|---|
| `backend/.venv/Scripts/python -m pytest backend -q` | 46 passed, 2.75 s |
| `/%ZZ`, `/explore/%ZZ` via :8000 | 400 `bad URL` / `bad url`; server stays up (issue #10 holds) |
| `/explore/..%2f..%2fserver.js`, `/explore/..%5c..%5cserver.js`, `/..%2fserver.js` | 403 |
| `/explore/%2e%2e/%2e%2e/server.js` | 404 (the URL parser folds `..` to `/server.js` under `app/`) |
| `/explore/foo/bar` → SPA fallback 200; `/explore/assets/nonexist.js` → 404 (no fallback for files) | correct |
| `/api/frames` with no q, empty q, `fov=999`, `12h99m 99d`, `1 2 3 4 5 6 7`, `nan nan`, `inf 0` | all 400 with a JSON `detail` |
| `/api/frames?q=0 90`, `q=360 -90` (poles) | 200, 94 KB and 180 KB |
| `/api/frames?q=%00` | 502 "Sesame did not answer (HTTP 502)" after about 9 s of retries (L3) |
| Proxy repro (scratch script, same code as `server.js:104`): upstream sends headers, then drops the socket | proxy does not crash, but the client response never ends (M5) |
| Windows: `os.replace(tmp, dst)` while another handle reads `dst` | `PermissionError(13)`, and the `.tmp` file stays (M2) |
| Cache scan (`backend/cache/*.json`, 37 files) | First vs last frame detector sets differ: Barnard's Star D1-D6 vs D2+D5; eps Ind B D1-D6 vs D2,D3,D5,D6; R Dra 5 different mixes (M3). Files from older `CACHE_VERSION`s stay on disk (L6). |

## Geometry and astronomy math (checked, no defect)

```
FITS image ──all_world2pix (SIP)──> map_coordinates ──> grid [row 0 = south]
                                                          │ np.flipud
grid (x, y) ── display_xy: (x+0.5, n-0.5-y) ──> PNG [row 0 = north] <── Gaia xy, ring, centroid
                                                          │
web pixelToSky / skyToPixel: center = n/2, xi = -(x-n/2)s, eta = (n/2-y)s   (matches crpix (n+1)/2)
```

- `output_wcs` (`backend/spherex.py:143-150`): `cdelt = [-s, +s]` gives east-left, north-up; `crpix (n+1)/2` puts the center at PNG `n/2`. The web gnomonic code (`web/src/sky.ts`) uses the same center. Correct.
- `display_xy` and `centroid` return values (`spherex.py:176-182`, `:289`): the same `+0.5` and `n-0.5-y` transform. Tests at `test_spherex.py:95-111` fail if the flip or the sign breaks.
- `gaia_tracks` (`spherex.py:153-167`): `-pmra*t` in x (east-left), `-pmdec*t` in PNG y (north-up). Gaia `pmra` already holds cos(dec). Test `:216` covers both signs.
- `at_epoch` (`spherex.py:406-409`): J2000 reference (MJD 51544.5) and Sesame `pmRA` (mu_alpha*, cos(dec) included) agree with `spherical_offsets_by`. Parallax is ignored: at most 0.09 px for Barnard's Star, under the 0.1 px floor. No test (M6).
- Photometry units (`spherex.py:323`): MJy/sr × (6.15″ in rad)² × 1e9 = mJy. Correct. Test `:203`.
- Lupton RGB (`spherex.py:204-221`): with Q = 3 and stretch = 0.3 (hi - lo), full scale is at I = sinh(3)/3 × 0.3 (hi - lo) ≈ hi - lo. The docstring is correct.
- `read_cutout` (`spherex.py:439-455`): the section bounds and the `[y - y0, x - x0]` order are correct. `cval=nan` keeps off-detector pixels as no data.

## Findings

### High

None.

### Medium

**M1. The disk cache pins degraded and stale results forever.** `backend/spherex.py:621-626`.
- Failure: a cold build where S3 throttles and 20 of 60 images fail (`n_failed > 0`), or where every image of one epoch fails (that epoch is dropped silently at `:511-513`), is written to the cache. Every later request serves the degraded answer. Nothing expires. New QR3 surveys never appear for a patch that was viewed once. The only way out is to delete files by hand or change `fov` a little.
- Fix direction: do not cache a result with `n_failed > 0` (or give it a short TTL), and add a maximum age for all entries.
- Agrees with project_manager M6. I add the partial-failure angle, which is a data-integrity problem, not only freshness.

**M2. On Windows the atomic cache write can fail while another request reads the file.** `spherex.py:639-645`, `:624`.
- Failure: two requests for the same cold key (two tabs, the precompute script plus the UI). Both build. The first writes. The second calls `os.replace` while a third request holds `path.read_text()`. Windows refuses the replace: `PermissionError(13)` (reproduced). The second request returns a plain-text 500 after a full build, and the `.tmp` file stays in `backend/cache/`. The same race in `gaia_field` only turns into a "Gaia failed" note.
- Fix direction: retry the replace briefly on `PermissionError`, and catch write errors so a failed write still returns the built result. Remove the temp file on failure. Per-key single-flight would also stop the double build.

**M3. The gray blink and the difference image compare different wavelength mixes.** `spherex.py:528`, `:586-592`.
- Failure: each frame's stack is the mean of whatever detectors that epoch had. In the cache, Barnard's Star goes from D1-D6 (first) to D2+D5 (last); R Dra has 5 different mixes. A fixed red or blue star then changes brightness between frames and leaves a bright/dark residual in `difference`. That looks like a variable or a mover to a citizen scientist. The photometry case is handled and documented (`docs/blink/api.md:74`), but the images are not.
- Fix direction: build the difference (and optionally the blink) from detectors that are present in both frames. Or add a note when the first and last frames have different detector sets, and show the detector set on each frame in the UI.

**M4. The Gaia fail-soft path can add up to about 100 s to every request, including cached ones.** `spherex.py:628-633`, `:335-354`, `:357-372`.
- Failure: the ESA TAP server is down or slow. `http_get` tries 3 times with a 30 s timeout, plus 3 s + 6 s sleeps. A Gaia failure is not cached (on purpose), so every cached request pays this again. This is close to the web 3-minute abort, and the user sees "Fetching from IRSA" for a cached patch. Sesame has the same retry budget on a cold name.
- Fix direction: a short timeout and a single try for Gaia (it is optional), or a negative cache for a few minutes.

**M5. The proxy leaves the browser hanging if the backend dies mid-response.** `server.js:103-106`.
- Failure: uvicorn crashes or is restarted while it streams a 2 MB answer. `r.pipe(res)` does not end `res` when the upstream aborts. The browser waits until its own 3-minute timeout (reproduced with a scratch server on Node 24.20). Also, a client abort does not cancel the upstream request (minor: the backend cannot cancel anyway).
- Fix direction: on `r` `aborted`/`error`, call `res.destroy()`; on `res` `close`, destroy the upstream request; set an upstream timeout.

**M6. The tests do not cover the I/O orchestration, where most failure handling lives.** `backend/test_spherex.py` (no reference to `at_epoch`, `read_cutout`, `build`, `get_frames`, `http_get`, `sesame`, `write_json`, `rgb_pngs`, `stretch`). No test for the `server.js` `/explore/` route or proxy, and none for `start.js`.
- What is good: the pure-geometry tests are real. They fail if the flip, the east sign, the Gaia direction, the centroid transform or the photometry unit breaks. No test is skipped, disabled or loosened in this range.
- Gaps that a bug could pass silently: the proper-motion epoch (a J2000 vs J2016 mix-up stays green); partial-failure notes and caching; the retry and 4xx-vs-5xx logic; SIP alignment of a synthetic FITS with a known star; the path-traversal and `%ZZ` guards (issue #10 has no regression test).
- Fix direction: one offline `build` test with a fake `query_images` and a synthetic FITS (a star at a known RA/Dec through a SIP header), one `at_epoch` test against a known Barnard's Star position, and one `node --test` file for the `/explore/` route.

### Low

- **L1. `read_with_retry` retries every exception** (`spherex.py:474-484`). A programming error (for example a missing `FLAGS` HDU or a `KeyError`) sleeps 6 s per image and then shows up only as "N images failed". Retry only network or OSError types; log the rest at error level.
- **L2. Non-HTTP exceptions become plain-text 500s.** Examples: an HTML page from Sesame makes `ET.fromstring` raise `ParseError` (`spherex.py:378`); M2's `PermissionError`. The web shows a generic message because `res.json()` fails. A global exception handler in `backend/app.py` that returns a JSON `detail` would keep the contract in `docs/blink/api.md:17`.
- **L3. User input errors can be reported as upstream outages.** `q=%00` takes about 9 s and returns 502 "try again in a minute", because Sesame answers 502 to that name. Reject control characters in `q` in `backend/app.py:28`.
- **L4. No end-to-end deadline or thread budget per request.** `ThreadPoolExecutor(12)` per request (`spherex.py:498`) inside FastAPI's 40-thread pool can reach about 480 threads. The fsspec/aiohttp default timeout is long (5 min), and there are 3 tries per image. A stuck S3 read can hold a request for many minutes. Local single-user use makes this low. Add a shared executor and a total timeout before any hosting.
- **L5. The cache key ignores `name` and `pm`** (`spherex.py:621`). A coordinate query that rounds to the same center as a named target gets that target's name, `pm` and ring. This is very unlikely. Add `pm` to the key at the next version bump.
- **L6. Old cache versions are never removed.** Files from older `CACHE_VERSION`s stay in `backend/cache/` (seen in the scan). Disk use grows without bound. Put the version in the file name or prune on start.
- **L7. `start.js` does not reinstall the venv when `requirements.txt` changes** (`start.js:99`). The header says "missing or out of date", but only `web/dist` is checked for age. After a dependency bump, uvicorn fails with an ImportError. Compare the mtime of `requirements.txt` with a marker file in the venv.
- **L8. `start.js` cleanup depends on graceful signals.** `taskkill /T /F` and `SIGTERM` (`start.js:72-91`) are correct for Ctrl+C, SIGHUP on a closed console window, and the `exit` event. If `node start.js` itself is force-killed (Task Manager, `taskkill /F` on node), the uvicorn and server.js children are orphaned and keep ports 8000/8001. The next run reuses them through `isOurs`, which also hides stale code from another checkout. Acceptable for a local demo.
- **L9. Main static route prefix check without a separator** (`server.js:125`, teammates' code, outside the explore lines). `p.startsWith(ROOT)` would accept a sibling folder named like `app2/`. No such folder exists today. The `/explore/` route does this correctly with `EXPLORE + path.sep` (`server.js:113`).

## Security summary

| Boundary | State |
|---|---|
| Query params (`backend/app.py:27-33`) | Length, range and pattern checks; bad input → 400 JSON |
| Sesame URL (`spherex.py:378`) | Fixed host; name passed through `quote()`; no SSRF |
| Proxy (`server.js:102-106`) | Fixed host and path; only the query string is forwarded; no request headers forwarded; no SSRF |
| Static `/explore/` (`server.js:110-121`) | Decode errors → 400; normalize + `EXPLORE + sep` guard → 403; verified with `%2f`, `%5c`, `%2e%2e` |
| Binding | server.js on 127.0.0.1; uvicorn default host 127.0.0.1 |
| Front end | React text rendering; backend notes include exception text but are not inserted as HTML; `app/app.js:361` link uses `encodeURIComponent` of numbers |

## Cross-check with project_manager

I read `artifacts/review-project_manager-explore-live.md`. It is PASS with 0 high, 9 medium, 7 low.

- **Agree:** M6 (cache never refreshes) = my M1. I rate it medium too and add that partial failures are pinned forever.
- **Agree:** M3 (the WISE 0855 coordinate query has `pm` null and no epoch hint). A technical addition: for a coordinate query, `centroid` searches only within 1 px of the center (`CENTROID_MAX_SHIFT_PX`, `spherex.py:58`). A fast mover at typed coordinates therefore gets no centroid in most frames, and the UI says "No source above 5σ at the target". That message is wrong for this case.
- **No conflict:** PM M1, M2, M4, M5, M7-M9 and L1-L7 are about delivery, docs and process. I did not re-check them. PM L1 (per-detector PNGs decoded but not shown) adds weight to my L4 on response size: the per-detector PNGs (up to 6 per frame, so up to 72 of about 97 PNGs with 12 frames) are sent and decoded but not shown.
- **Not in the PM review:** my M2 (Windows replace race), M3 (detector mix in the images), M4 (Gaia latency), M5 (proxy hang) and M6 (test gaps).
