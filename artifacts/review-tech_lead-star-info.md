# Tech-lead review: feat/star-info (fix loop round 2)

- Seat: tech_lead (independent; I did not write this code).
- Range: `git diff main...feat/star-info` (main `cf24fdd`, head `ff07364`), 37 files, +2114 / -152.
- Date: 2026-11-14.

## Verdict

**PASS.** No high finding. 1 medium, 9 low.

All five round-1 mediums are fixed. The new `/api/about` holds its trust boundaries. The one medium is a wrong-object
answer from the SIMBAD cone search for a position.

## Evidence I gathered myself

| Check | Result |
|---|---|
| `pytest backend -q` (worktree) | 100 passed, 2.1 s |
| Backend on :8051 from the worktree, then stopped | `/api/about?q=Barnard's Star` 200: facts OK, `history_sentence` null (paper-count fallback) |
| `/api/about?ra=269.452077&dec=4.693365` (Barnard's Star J2000) | 200, **"Barnard's Star c is a planet about 6.0 light-years away."** (M1) |
| `/api/about?q=x&ra=1&dec=2`, `?ra=1`, `?ra=nan&dec=0`, `?q=%01` | all 400 with a JSON `detail` |
| `/api/resolve?q=zzqx not a star` | 400 plain message in 8.6 s (CDS skipped or slow, then CfA) |
| `/api/about?q=../../?#x`, `/api/resolve?q=../../etc` | Sesame host stays fixed (`quote`, name after `?`); 200 "does not know" / 400 |
| Removed / skipped / loosened tests | None. `verify-ui.mjs:89` regex changed to the new wording (`× the faintest`); the check is not weaker |
| Cleanup | My 3 probe answers in `backend/cache/about-*.json` (gitignored) deleted; server on :8051 stopped |

## Round-1 findings (artifacts/review-tech_lead-explore-live.md)

| Finding | State | Evidence |
|---|---|---|
| M1 cache pins degraded/stale results | FIXED | `spherex.py:709` `max_age_s`: 7 days, 1 hour when `n_failed` or `epochs_dropped`; `get_frames` rebuilds and falls back to the old answer with a note on 5xx; tests `test_frames.py:64,74,85` |
| M2 Windows replace race | FIXED | `spherex.py:749` retries `PermissionError` with backoff, returns False, removes the temp file; `read_cache:700` catches `OSError`; tests `test_frames.py:96,106`. No single-flight (L1) |
| M3 detector-set mismatch | FIXED | `spherex.py:605` gray stacks use the common detectors; `:666` the difference uses first/last common detectors; notes when none; UI shows `image:` sub-label and `difference.detectors`; tests `test_frames.py:124,138` |
| M4 Gaia slow failure | FIXED | `spherex.py:374-394` one 8 s try, then skipped 10 min (`_down_until`); test `test_frames.py:164`. Sesame: one 8 s try per mirror, failed mirror skipped 10 min (`:405`) |
| M5 proxy hang | FIXED | `server.js:146` `stream.pipeline`; `error` after headers destroys `res`; test `test/liveproxy.test.js:38` reproduces the drop. No upstream timeout (L5) |
| M6 I/O tests missing | PARTIAL | Offline `build` tests with fake `query_images`/`read_cutout` (`test_frames.py`), retry-type test `:185`, mirror tests `:210-242`, proxy tests. Still no `at_epoch` test and no `start.js` test |
| L1 retry all exceptions | FIXED | `spherex.py:535` `except NETWORK_ERRORS`; non-network errors log at ERROR with traceback |
| L2 plain-text 500 | FIXED | `app.py:26` global handler → JSON `detail`; test `test_app.py:37` |
| L3 control chars | FIXED | `app.py:34` `checked()` on `/api/frames`, `/api/resolve`, `/api/about`; test `test_app.py:31` |
| L4 no deadline / thread budget | NOT FIXED | Per-request `ThreadPoolExecutor(12)` unchanged. Local use only: still low |
| L5 cache key ignores name/pm | NOT FIXED | `spherex.py:722` key unchanged at `CACHE_VERSION = 6` bump |
| L6 old cache versions not pruned | NOT FIXED | Now also one `about-*.json` per clicked position, never deleted |
| L7 venv not refreshed on requirements change | NOT FIXED | `start.js:104` checks only `existsSync(VENV_PY)`. The new root `.venv` check (import `pyvo`) is better |
| L8 orphans on force-kill | Accepted | unchanged, local demo |
| L9 `startsWith(ROOT)` without separator | NOT FIXED | `server.js:170` (teammates' code) |

## New code

### High

None.

### Medium

**M1. A position lookup can name the wrong object, and it is shown as a catalog fact.** `backend/about.py:178-192`.
- Reproduced: `ra=269.452077, dec=4.693365` (Barnard's Star, J2000) → `"Barnard's Star c is a planet about 6.0
  light-years away."` The planet has the same catalog position as its star. `ORDER BY d` with `TOP 1` then picks either
  one; here it picked the planet.
- User path: the user types the coordinates of a star with a catalogued planet or companion. The card at
  `panels.tsx` `AboutCard` uses `aboutUrl(r.center)` when `r.name` is null. The first sentence then names the wrong object.
- Second case: SIMBAD positions are J2000; a mark on a fast mover is at its 2026 position. The 5″ cone misses it (Barnard's
  Star moves about 270″ since 2000), so the card falls back to Gaia (epoch-moved, correct) or names a neighbor.
- Fix direction (finding only): break distance ties away from planets and sub-components, or by reference count; or
  search with epoch-propagated SIMBAD positions. Add a test with two rows at the same distance.

### Low

- **L1. No single-flight per cache key.** Two cold requests for one key still both build (`spherex.py:714`). The write race is now safe; the cost is a double IRSA load.
- **L2. The stale fallback covers only `HTTPException` 5xx** (`get_frames`). A non-HTTP failure in a rebuild (for example a bug) gives a 500 although an old answer exists.
- **L3. A "not found" can be pinned while one mirror is down.** `sesame_resolver` returns None when the down mirror is skipped and the other says nothing. `sesame` (`spherex.py:430`, `lru_cache`) keeps that None for the process; `get_about` caches "does not know" for 30 days. The mirrors share data, so the risk is small.
- **L4. `/api/about` worst case is about 64 s, and the card has no timeout.** Serial tries: SIMBAD 2 × 8 s, Sesame 2 × 8 s, Wikipedia up to 4 titles × 8 s (`about.py:183,163,204`). `fetchAbout` (`panels.tsx`) has no abort or timeout; the skeleton stays up for that time.
- **L5. The proxy has no upstream timeout** (`server.js:146`). A hung (not dead) backend still holds the browser until its 3-minute abort. A client abort before the upstream headers does not cancel the upstream request.
- **L6. CC BY-SA attribution is minimal.** The credit links the article and names "CC BY-SA 4.0" (`about.ts` `historyLine`), but there is no link to the license text. `history_source.url` can be null if `content_urls` is missing (`about.py:266`), which renders an `<a>` without `href`.
- **L7. The card detects a source failure by string match** (`panels.tsx` `failed = notes.some(n => n.includes('did not answer'))`). A wording change in `about.py` breaks it silently. A boolean field would be durable.
- **L8. Test gaps in the about path.** No test for Sesame failing in `catalog_facts` (answer not cached); `test_about.py` does not reset `spherex._down_until`, so it depends on test order; no test for M1 ties. The fixture extract matches the history regex, but live Barnard's, Kapteyn's and R Dra get no history sentence (implementer admits this in `live-checks.md:15-18`).
- **L9. `start.js` (#28) has no automated test.** The logic reads correctly: soft failures, repair via `import pyvo`, `WANDERERS_PYTHON`/`WANDERERS_PY` set only when the root venv exists, `PORT`/`LIVE_PORT` passed through `WANDERERS_LIVE`. If port 8000 is reused from an older run, that server does not get `WANDERERS_PYTHON`.

## Security summary (new surfaces)

| Boundary | State |
|---|---|
| `/api/about` params (`app.py`) | `q` 1-200 chars, no control chars; `ra` [0,360), `dec` [-90,90], NaN/inf rejected; exactly one mode, else 400 |
| `/api/resolve` | same `checked(q)`; 400 for unknown names |
| Outbound hosts | Fixed: CDS, CfA, SIMBAD TAP (CDS, CfA), en.wikipedia.org. Names go through `quote()` (Wikipedia with `safe=""`); ADQL gets validated floats only. No SSRF |
| User-Agent | `WANDERERS-hackathon/0.1 (repo URL)`, no e-mail or personal data; test asserts no `@` |
| Rendered text | Wikipedia and catalog text rendered as React text, not HTML; links from fixed hosts or the Wikipedia API |
| `WANDERERS_LIVE` env in `server.js` | Local operator setting, not a request input |

## Agreement with project_manager

I read `artifacts/review-project_manager-star-info.md` (PASS, 0 high, 2 medium, 6 low).

- **Agree:** PM L3 (history falls back to the paper count for 3 of 5 targets) = my L8 note. Low for me too.
- **Agree:** PM L5 (`start.js` has no automated test) = my L9.
- **No conflict:** PM M1 (README lines 286, 498) and M2 (toast at 375 px) are docs and UX. I did not re-check them.
- **Not in the PM review:** my M1 (SIMBAD tie picks the planet). I rate it medium, not high: it shows only for typed
  coordinates or marks, and the card links SIMBAD for a check.
