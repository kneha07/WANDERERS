# Tech lead review: star-info, fix-loop round 3

Scope: `git diff a706670..96c5395` (8886346, 9827e37, 65dbe71, 96c5395).
Verdict: **PASS**. No high findings remain.

## What I checked

| Check | Method | Result |
|---|---|---|
| NH1 test fails on the old code | Old `server.js` (a706670) in a scratch copy, new `test/liveproxy.test.js` | FAIL: `ECONNREFUSED` after the abort (server crashed) |
| NH1 test passes on the new code | `node --test test/liveproxy.test.js` | 4/4 pass, mid-answer test included |
| Every abort path | Probe script: real `server.js` + fake upstream, 5 runs of each path | Server alive, next request 200, empty stderr |
| Upstream socket leak | Fake upstream records `res close` for each request | Every aborted request closed upstream at once (`:aborted`) |
| Backend about tests | `pytest backend/test_about.py` | 45 pass |

Abort paths covered by the probe:

```
client closes before upstream headers   -> res close -> up.destroy(); up error ignored (res.destroyed)
client closes mid-body                  -> pipeline destroys r and res; res close -> up.destroy()
upstream error after client close       -> error handler returns early (res.destroyed)
upstream never answers, client leaves   -> up.destroy() on res close; upstream socket closed
upstream dies mid-answer, client stays  -> pipeline destroys res (old fix kept; test still "broken")
```

The old probe run crashed `server.js` on the first path. That confirms the root cause and the fix.

## Findings

### medium

**M1. The fast-mover hint can be lost for 30 days.** `backend/about.py:216-241` returns `[]` when SIMBAD
fails, but `build_about` (`backend/about.py:354`) does not set `failed`. So `get_about` caches that answer
for 30 days (`backend/about.py:369-370`). A short SIMBAD failure removes the backend hint for that position.
`ABOUT_VERSION` (`backend/about.py:22`) also stays `1`. Position answers that are already in the cache
have no `fast_movers` key for up to 30 days. The web Gaia fallback (`web/src/about.ts:101-111`) covers
only stars in the frames' Gaia list. The hint is optional, and nothing false is shown. So this is not high.

**M2. A slow SIMBAD now makes a position About answer twice as slow.** `fast_movers` runs after
`simbad_near` in sequence. It can try both hosts with `TIMEOUT_S = 8` (`backend/about.py:25,28,221-225`).
When SIMBAD hangs, the worst case goes from about 16 s to about 32 s. The web client stops at 20 s
(`web/src/panels.tsx` `fetchAbout`, `AbortSignal.timeout(20_000)`). Then the About card shows an error
where before it showed the "SIMBAD did not answer" note.

### low

- **L1.** The proxy has no upstream timeout (`server.js:147`). A hung backend holds the browser until the
  browser leaves (probe: the client stopped at 4 s; the upstream socket closed then). This existed before.
  Cold loads are slow, so a timeout must be long if one is added.
- **L2.** No test covers the fail-soft path of `fast_movers` (SIMBAD error or bad rows -> `[]`).
  The tests cover only the success path (`backend/test_about.py:212-231`).
- **L3.** The hint also fires when the typed position is the current position of the fast mover
  ("is 0″ from here … may miss it"). This is true but a little confusing.
- **L4.** `path_near` uses 2026.0 as "now" (`backend/about.py:213`, `web/src/about.ts:96`). The error is
  under 1″ per year of drift at 8″/yr. This is acceptable for a hint.

## NM1 and NM2 correctness

- NM1: `brightestSeen` (`web/src/data.ts:205-211`) gates the change claim on the brightest point. It needs a
  centroid or flux >= 5 sigma. The same gate is used in the About sentence (`web/src/about.ts:31-33`) and in
  the Brightness panel (`web/src/panels.tsx:572-573,658`). So the two do not contradict each other.
- NM2, slow stars: the backend ADQL filters `pmra^2 + pmdec^2 > 1000^2` (`backend/about.py:220`). The web
  fallback filters `> 1000` mas/yr (`web/src/about.ts:105`). A slow star cannot cause the hint. Zero velocity
  cannot reach `path_near`. Null motions are dropped by SQL and by the `try` (`backend/about.py:232-235`).
- NM2, SSRF and injection: the hosts are the fixed `SIMBAD_TAP` tuple. `ra` and `dec` are FastAPI floats with
  range limits (`backend/app.py:58-59`), so NaN and text cannot enter the ADQL string.
- NM2, path window: the backend uses -10..+30 years from J2000. The web uses 1990..2030 minus the Gaia
  epoch. Both give the same 1990-2030 window.
- The typed-coordinate About request uses the same URL (`targetAboutUrl`) and the same promise map as the
  About card. So it sends one request, not two.

## Not checked

- I did not run `start.js` against live SIMBAD. The orchestrator ran it live on 8081. My probe used the real
  `server.js` with a fake upstream.
