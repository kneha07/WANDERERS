# Project manager review: feat/star-info (fix loop round 2)

- Branch `feat/star-info` at `ff07364`. Scope: `git diff main...feat/star-info` (main = `cf24fdd`), 17 commits, 37 files.
- Reviewer: project_manager (independent; I did not write this work).
- Evidence read: the diff, the commit messages, `artifacts/star-info/live-checks.md`, `artifacts/star-info/stress-walk.md`,
  screenshots `1440-about-WISE.png` and `1440-switch-rdra-to-barnard.png`, issues #6, #24, #26, #28 and the open list.
- Not re-run by me: the test suites. The orchestrator reports pytest 100 pass, node --test 154 pass / 1 skip,
  web vitest 51 pass, build ok. I accept these as reported.

## Verdict

**PASS.** No high finding. Medium 2, low 6.

```
round-1 findings ──► fixed on branch ──► evidence
  PM  M3 M5 M6 M8      3 MET, M8 PARTIAL      live-checks.md, docs diff
  TL  M1..M6           5 MET, M6 PARTIAL      commits + tests
  UA  H1, M1..M8       H1 MET, 6 MET, 2 PARTIAL  screenshots, verify-ui 29 PASS
  #28 start.js .venv   MET (live run)         live-checks.md "start.js"
  About this star      MET (design of #6)     about.py, about.ts, panels.tsx
```

## 1. Round-1 project_manager and tech_lead mediums

| Finding | Status | Evidence |
|---|---|---|
| PM M3 WISE 0855 epoch hint | PARTIAL | Chip note `web/src/App.tsx:47` ("uses its 2026 position; the challenge coordinates are from 2010"). Typed-coordinate frames now say "no proper motion known: no predicted position" (`51b1cd8`, `backend/test_frames.py`). Not done: no hint when the user types the challenge coordinates, and no live re-test of the typed coordinates in `live-checks.md`. Named in `docs/blink/README.md:175-177`. (L2) |
| PM M5 stale docs | MET | `docs/demo-script.md:3,26-28,48-49`; `docs/blink/README.md:188` (gate and Gaia overlay marked done). `artifacts/ux-mechanics.md:3` still names `feat/explore-redesign`; acceptable as a dated record (low). |
| PM M6 cache never refreshes | MET | `38e9e64`: frames rebuilt after 7 days, degraded answers kept 1 hour; About 30 days and never cached on a failed source (`backend/about.py:286-295`). |
| PM M8 root README misleads | PARTIAL | Explore section rewritten (`README.md:437-468`: layout, Windows and macOS commands, test commands). Still wrong: `README.md:498` "new coordinates need `pipeline/fetch.py`" (contradicted by on-demand fields and `/explore/`), and `README.md:286` typo `python .venv/bin/python`. The commit `965b920` says "Explore section only", so the scope is honest, but the round-1 finding is not closed. (M1) |
| TL M1 cache pins degraded results | MET | `38e9e64` |
| TL M2 Windows rename race | MET | `4ba12fd` (retry, then serve uncached) |
| TL M3 detector mix | MET | `772c8dc`; stack note visible in `1440-about-WISE.png` ("stack only D2 D3 D5 D6") |
| TL M4 Gaia latency | MET | `8a81109` (one 8 s try, skip 10 min) |
| TL M5 proxy hang | MET | `b18ce1d`, `test/liveproxy.test.js` (+68) |
| TL M6 test gaps | PARTIAL | `backend/test_frames.py` (+246), `test/liveproxy.test.js`, `backend/test_about.py`. `start.js` still has no automated test; #28 is proven by one live run only. (L5) |

## 2. User advocate H1 and M1-M8

| Finding | Status | Evidence |
|---|---|---|
| H1 / #26 old target under new heading | MET | `1440-switch-rdra-to-barnard.png`: Motion, Brightness, Your sky now, Frames are skeletons; flipbook and Sky context say "Showing R Dra until Barnard's Star loads." verify-ui has a held-request check (`web/scripts/verify-ui.mjs`). Small gap: the timeline (9 R Dra epochs) and the "All 21" Gaia toggle still show R Dra values without the dim label (L4). |
| M1 Motion in expert notation | MET | `web/src/panels.tsx:413` plain sentence above the chart |
| M2 localhost share link | MET | Task tab text "This link opens only on this computer until the tool is hosted (issue #24)" (screenshot); report leaves the link out (`ba4ed25`) |
| M3 45 s name failure | MET | `/api/resolve` first; "No object called …" in 6.5 s cold, 0.1 s cached (`live-checks.md`); "Edit the name" offered |
| M4 strong verdict on probable artefact | MET | `ba4ed25`: D1/D2 → "May be scattered light (known issue #5)", ratio wording; `docs/blink/README.md:173-174` |
| M5 controls below fold at 1440 × 900 | MET | toolbar y 253-319, image y 327-897 (`1440-rdra.png`) |
| M6 375 px result off screen, toast covers it | PARTIAL | Chips scroll in one row; image at y 397-740 (`375-kapteyn.png`). Not done: the toast still says "See the Task tab" (`web/src/App.tsx:394`), and its position is unchanged (`web/src/index.css:1357` changes only font size). Not tracked in an issue. (M2) |
| M7 Gaia circles cover Barnard's Star | MET | `web/src/data.ts:207` (G < 17, at most 40, "All N" toggle) |
| M8 heading differs from typed name | MET | heading "typed name · catalog id" (`ba4ed25`) |

## 3. Issue #28 (start.cmd users and on-demand fields)

MET. `start.js` creates the root `.venv` and installs `pipeline/requirements.txt` when `import pyvo` fails, and passes
`WANDERERS_PYTHON` / `WANDERERS_PY` to `server.js` (read at `fields.js:21`, `server.js:22`). Live run in a scratch
worktree with no root `.venv`: `POST /api/field {"ra":150,"dec":2.2}` reached `done` (`live-checks.md`, last section).
#28 is still OPEN; close it on merge, then PR #19 is unblocked.

## 4. User request: "About this star" in 3 sentences

| Design point (issue #6 comment, 2026-11-14) | Status | Evidence |
|---|---|---|
| Sentence 1 from catalog values only | MET | `backend/about.py:115-123` `facts_sentence` builds from Sesame otype, spType, parallax (5 sigma rule `:99-103`) |
| Sentence 2 from our SPHEREx measurements | MET | `web/src/about.ts` `measuredSentence` uses only frames data |
| Sentence 3: one dated history sentence quoted from Wikipedia, CC BY-SA credit + link | MET | `about.py:126-132` (verb + year); credit "— Wikipedia, CC BY-SA 4.0" with link (`about.ts` `historyLine`, `1440-about-WISE.png`) |
| Fallback SIMBAD paper count | MET | `about.ts` `historyLine`; Barnard 924, Kapteyn 373, R Dra 154 papers (`live-checks.md`) |
| No LLM-written facts | MET | no model call in `backend/about.py`; Wikipedia page accepted only if it is about the object (`page_is_about`) |
| Card for current target and each clicked candidate | MET | `panels.tsx:111` `AboutCard({r, mark})`; candidate row in `live-checks.md` (Gaia nearest-star sentence, `375-about-candidate.png`) |

Note (L3): three of six showcase targets, including the first chip Barnard's Star, get the paper count, not a
history sentence. RW Aur's quote is about its B companion ("RW Aurigae B was discovered in 1944."). Both are inside
the agreed design and admitted in `docs/blink/README.md:178-179`, but a demo viewer who asks "the history" of
Barnard's Star gets a count.

## 5. Docs honest and current

| Doc | Status | Evidence |
|---|---|---|
| Root README "Explore any patch" | MET | `README.md:437-468` |
| `docs/blink/README.md` | MET | known limits `:162-184` include About, typed coordinates, scattered light; next steps `:188` |
| `docs/blink/api.md` | MET | `/api/resolve` `:115`, `/api/about` `:126-160` with fields, license and example |
| `docs/demo-script.md` | MET with L1 | `:3` says About is "on `main`": true only after the merge |

## Findings

### High

None.

### Medium

- **M1. Round-1 PM M8 is only partly closed.** `README.md:498` still says new coordinates need `pipeline/fetch.py`.
  `README.md:286` still has `python .venv/bin/python`. Fix: two one-line edits, or log them on #11.
- **M2. User advocate M6 is only partly closed.** At 375 px the toast still points to the Task tab two screens down
  (`web/src/App.tsx:394`), and the toast placement did not change (`web/src/index.css:1357`). No issue tracks it.
  Fix: change the toast text, or open an issue.

### Low

- **L1.** `docs/demo-script.md:3` claims "on `main`" before the merge.
- **L2.** Typed WISE 0855 challenge coordinates: no in-app epoch hint, no live re-test. Named in docs only.
- **L3.** History falls back to the paper count for Barnard's Star, Kapteyn's Star and R Dra; RW Aur quotes the
  companion. Admitted in docs; no issue.
- **L4.** During a target switch the timeline and the "All 21" Gaia toggle keep the old target's values without the
  dim label (`1440-switch-rdra-to-barnard.png`).
- **L5.** `start.js` (#28 fix) has no automated test; one live run only. #28 still OPEN.
- **L6.** `artifacts/ux-mechanics.md:3` still names `feat/explore-redesign` (dated record; acceptable).

## Known limits the branch admits, and tracking

| Limit | Where named | Issue |
|---|---|---|
| Live mode local only, share link local | Task tab text, `docs/blink/README.md` | #24 |
| D1/D2 scattered light | brightness label, docs | #5 |
| Centroid pull, RGB channel fill | API notes | #21 |
| Typed coordinates have no proper motion; WISE 0855 2010 coordinates | `docs/blink/README.md:175-177` | none (L2) |
| About depends on CDS and Wikipedia; many pages have no dated sentence | `docs/blink/README.md:178-179` | none (L3) |
| Saturated cores (R Dra, Barnard) | `docs/blink/README.md:167-168`, demo script | none (deliberate, #6 comment) |
| Toast and Task tab at 375 px | not named | none (M2) |

## Agreement with tech_lead

`artifacts/review-tech_lead-star-info.md` did not exist when I finished. No debate notes yet.
