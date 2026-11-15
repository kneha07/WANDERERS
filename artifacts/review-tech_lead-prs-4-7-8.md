# Tech lead review: PRs #4, #7, #8 (kneha07/WANDERERS)

Pinned heads: #4 a1175d3, #7 8db452f, #8 3c72267. Base 1913aea. Run on integrate/2026-11-14 (files copied in, then removed; `git status` clean).

| PR | Verdict | Run result |
|----|---------|------------|
| #4 | FAIL | 6 pass, 2 fail (`node --test`) |
| #7 | PASS (with medium fix) | 10/10 pass (venv python) |
| #8 | PASS (with medium fix) | 10/10 pass (venv python) |

## PR #4 — API security tests

### high-1: file is committed as `tests`, not `tests/server.test.js`
The diff adds a file named `tests` with no extension (`diff --git a/tests b/tests`). The PR run command `node --test tests/server.test.js` cannot work. The file also blocks a `tests/` folder, which PRs #7 and #8 need. If #4 merges first, #7/#8 conflict (file vs directory). Repo convention is `test/` (fields.test.js, framemath.test.js). Move to `test/server.test.js`.

### high-2: test exposes a real crash bug (DoS) in server.js
`GET /%ZZ` -> ECONNRESET, then every later request -> ECONNREFUSED. The server process dies.
Cause: server.js:95 calls `decodeURIComponent` inside the `async` request handler with no try/catch. The URIError becomes an unhandled rejection and Node exits. Any client can stop the server with one request.
Product fix needed (server.js:95): wrap the decode in try/catch and return 400.

### high-3: unknown-target test reveals a path leak
server.js:85 `fs.readFileSync(path.join(ROOT,"data",target,"target.json"))` throws ENOENT. server.js:91 returns 400 with `String(e.message)`, which holds the absolute file path. The test expects 404 and no path. In this run the test failed with ECONNREFUSED (the server was already dead from high-2), so it never checked this; by code reading it fails on its own too.
Product fix needed (server.js:85-91): check that the target exists, return 404 with a generic message. Do not echo `e.message` to clients. Same pattern at server.js:71 (`/api/lookup`) is fine for validation text but must not carry fs errors.

### medium-1: test isolation
One crash cascades into all later tests (shared child). After the fix, this is acceptable. Keep the invalid-URL test last, or add a "server still alive" check after it, so a regression is named clearly.

### low
- `after` uses `child.kill()`; on Windows this is TerminateProcess; fine. Free-port probe has a small race; acceptable.
- One-line minified tests are hard to read; reformat.
- Valid-target `/api/ask` is not tested (it spawns `claude`); correct to avoid.

Security relevance: high. The tests find two real bugs. Merge them only together with the server.js fixes, else main goes red.

## PR #7 — evidence card tests
All 10 pass against pipeline/evidence.py on the integration tree. Assertions check real thresholds (inclusive motion, strict variability, saturation, catalogue status, no input mutation). No mocks, no skips.

### medium-1: location `tests/` vs existing `test/`
Repo has `test/` (Node). Python tests in `tests/` give two test folders. Pick one convention (for example `test/` or `pipeline/tests/`) and a single run command.
### low
- Docstring says `python3`; on Windows the command is `python`. Run needs pipeline deps only if evidence.py imports them; it worked in the venv.
- Literal classification strings couple tests to UI text; acceptable as regression guards.

## PR #8 — data quality tests
All 10 pass with the venv (numpy, astropy). Tests use synthetic data and check real behaviour (mask bits, background subtraction, NaN paths, centroid).

### medium-1: silent skip on missing deps
`setUpClass` turns ImportError into `SkipTest`. In CI without deps the suite reports OK with skips, which is a false green. Note also `import numpy` at module top fails before the skip guard, so the guard only covers analyze.py imports. Prefer a hard fail, or make CI install `pipeline/requirements.txt`.
### medium-2: same `tests/` vs `test/` folder issue as #7.
### low
- `test_detection_snr_returns_zero_without_background` and `test_centroid_returns_none_without_signal` test degenerate paths only; fine.
- PR body says "execution pending verification"; it is now verified here (10/10).

## Merge order
#4 conflicts structurally with #7/#8 (file `tests` vs dir `tests/`). Fix #4 first (rename to `test/server.test.js`), plus the server.js fixes.
