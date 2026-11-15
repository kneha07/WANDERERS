## Verdict

PASS-with-findings. No high finding. No medium finding. Four low findings.

- Pinned head: `0382b8d` on `docs/project-explainer`.
- Compared with: `main` at `cfc0129`.
- Merge base: `184e071`. The three-dot diff uses this base.
- Files: `artifacts/project-explainer.html` (+402), `docs/wiki/wiki/log.md` (+7).

## Earlier findings (review at 64cb979)

| Id | Status at 0382b8d | Evidence |
|---|---|---|
| H1 stale pin | Closed | This review pins `0382b8d`. |
| M1 Star Fix missing | Closed | Audience row, use case "Find where a photo was taken", architecture box `POST /api/star-fix`, stack row, limit row. Matches `README.md:207-215`, `server.js:110`, `start.js:121-123`. |
| M2 SPHEREx survey stage missing | Closed | Requirement 5 row, astronomer use case step 4, data row 2025-2026. Matches `app/survey.html:133` ("SPHEREx-confirmed only"), `app/surveytools.js:115` (export columns), `pipeline/survey/spherex.py`, `pipeline/survey/rank.py:718`. |
| M3 spectrum claim too wide | Closed | Objective 2 and limits say "5 of 11". Matches `README.md:143`. 11 targets ship in `app/data/`. |
| M4 confidence rule wrong | Closed, one narrow gap (L1) | Ladder order matches `pipeline/evidence.py:114-131`. Rule text matches `evidence.py:139`. |
| L1 "5 practice stars" | Closed | Page says "Eleven targets ship ready". |
| L2 freezer claim | Closed | Text removed. |
| L3 text drifts | Closed | Barnard's dot "walks away from its Gaia ghost circles". NEOWISE starts 2014. Calibration text matches `README.md:202-203`. |
| L4 markup | Mostly closed | `<!doctype html>` and `<meta charset="utf-8">` added. SVG `var(--mono)` attribute removed. Tabs still have no `aria-controls`. |

## Checks done

- HTML: Python `html.parser` stack check. No unclosed or mismatched tag. No duplicate `id`.
- JS: one inline script. `node --check` passes. All `getElementById` targets (`tabs`, `case`, `sky`, `yr`) exist. `show(0)` runs at load.
- `innerHTML` uses only the static `CASES` array. No user input reaches it.
- External hosts: `fonts.googleapis.com` only, plus links to `rajryadav4.github.io/wanderers/` and the repo.
- Theme: light tokens on `:root`. Dark tokens under both guarded blocks. `prefers-reduced-motion` stops the canvas loop.

Claims checked and correct against `main`:

| Page claim | Source |
|---|---|
| 102 colours, 0.75-5.0 µm | `README.md:38`, `README.md:62` |
| 12,288 tiles, 10 billion+ detections | `README.md:52`; `app/data/survey/summary.json` `detections` = 10,115,601,754 |
| 22,049 JWST frames | `README.md:250` |
| Votes: 3 voters, 60 %, newest wins | `README.md:50`, `README.md:750-751` |
| High-confidence preset 12+ visits, S/N 10+ | `README.md:322`, `app/survey.html:155-158` |
| Field search 8 of 9, WISE 0855 missed | `README.md:786`, `docs/product-gaps.md:52` |
| Star Fix 50-150 km, needs plate solver | `README.md:207-213`, `start.js:121-123` |
| 12-15 minutes for new coordinates | `README.md:198` |
| HuberRegressor, up to 13 catalogues, 1900-2100 | `README.md:420-431` |
| Stack: cedar-solve, pillow-heif, PyArrow, astropy-healpix, reproject | `pipeline/requirements.txt`, `start.js:123` |
| FastAPI on 8001, React + Vite | `README.md:653`, `README.md:841` |
| "Nothing is simulated" | `README.md:27` badge "data real, not simulated" |

## Findings

### L1 (low): saturation step-down is wider on the page than in the code

- Page (evidence section): confidence "drops one step ... when most SPHEREx points are saturated".
- Code (`pipeline/evidence.py:141-146`): the step-down applies only to the classes Variable star, Steady star and Known variable quiet. It does not apply when Gaia confirms a variable. It does not apply at level low. The threshold is more than 80 %.
- Effect: a reader can think a saturated Barnard's Star (188 of 188 points flagged) gets a lower confidence. It does not. It is "high" in `app/data/barnard/target.json`.

### L2 (low): "Unexplained mover → candidate" joins two separate outputs

- Page ladder row 5: "Unexplained mover → candidate".
- Code (`pipeline/evidence.py:135`, `:147`): `status` is "candidate" only when the target is not in Gaia and not catalogued. `status` does not depend on the class. A catalogued target whose motion does not match its published motion gets class "Unexplained mover" and status "known".
- No shipped target hits this case today (all 11 are "known"). The same text in objective 4 ("Anything that Gaia or a catalogue does not explain is a candidate") is correct.

### L3 (low): log entry metadata is stale

- `docs/wiki/wiki/log.md` (branch entry): "branch: docs/project-explainer, 479d910" and "page is back to v1 (479d910 content)" and "source: ... at 184e071".
- The page at `0382b8d` is not v1 content. Its footer cites `cfc0129`. The log does not record the `0382b8d` fixes.

### L4 (low): small wording and markup gaps

- Requirement 5: "Each mover is checked against Gaia DR3". `app/data/survey/summary.json` limits: the Gaia check is pending for 148 of 647 tiles. "Each" is slightly too wide.
- No `<html lang="en">`. Tabs have no `aria-controls`, no `aria-labelledby` and no arrow-key support. Tab and Enter work.

## log.md merge check

- `git merge-tree --write-tree main 0382b8d` reports one conflict: `docs/wiki/wiki/log.md`. No other file conflicts.
- Base (`184e071`) has one entry (live explorer, 2026-11-14).
- `main` appends one entry after it: "[2026-11-15] run | star fix (work-lite)".
- Branch appends one entry at the same place: "[2026-11-15] run | project explainer page".
- Both sides only append. No base line changes on either side.
- Correct resolution: keep the base entry, then main's Star Fix entry, then the branch's explainer entry. Keep one blank line between entries. Do not drop either entry.

## Not checked

- No live browser render at this head. Checks are static (parser, `node --check`, source compare).
