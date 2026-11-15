# Catalogue survey: build spec

Date: 2026-11-15. For: the implementing agent (Opus). Design and evidence: [catalogue-survey.md](catalogue-survey.md) (read it first, 5 minutes). Issues: #59 (step 0), #60 (decision).

This page says what to build, where, and how to know it is done. When this page and the code disagree, measure, then change this page in the same commit and say why.

## 0. Rules for the implementer

- Work in a new worktree: `git.exe worktree add .worktrees/survey-build -b feature/catalogue-survey origin/main`. Then `git.exe checkout origin/docs/catalogue-survey -- docs/specs/catalogue-survey.md docs/specs/catalogue-survey-build.md artifacts/survey`. Use `git.exe` for every git command (WSL `git` breaks on these worktrees).
- Never push. Never commit on `main`. One commit for each phase in section 7. A human pushes after review.
- Logs, test output and screenshots go in `artifacts/survey/` inside the worktree.
- Do not add a paid service, an account, a key or a server. Everything here is free and static.
- Python in WSL has no numpy. Keep `survey.py` stages 0 to 2 pure standard library, so `python3 -m unittest tests.test_survey` runs anywhere. Stage 3 runs with the venv Python that has `pipeline/requirements.txt`.
- Say what the data supports. Never write "discovery". A row is a `candidate` until a human checks it. Print the limits (section 6 of the design) on the page.
- Do not edit `app/data/<target>/` of the eleven missions or any `explain.json`. Do not run `pipeline/explain.py` (it needs the Claude CLI).

## 1. Order of work

```
phase 0  issue #59: rebuild the five targets      (separate task, needs network and hours)
phase 1  pipeline/survey.py  scan + build         + tests/test_survey.py
phase 2  app/queue.html                           + test/queue.test.js
phase 3  survey.py verify, add_position motion    + vet.py ids filter
phase 4  scan more sky, control check, README
```

Phases 1 and 2 do not depend on phase 0. Phase 3 does: WISE 0855 can read `confirmed` only when `find_movers` has fresh data. If phase 0 is not done, build phase 3 and report the WISE 0855 acceptance test as "not run, blocked by #59".

## 2. The data source

Host: NOIRLab Astro Data Lab TAP, `https://datalab.noirlab.edu/tap/sync`. Table `catwise2020.main`. No account.

Request: `GET` with `REQUEST=doQuery&LANG=ADQL&FORMAT=csv&QUERY=<adql>`. A bad query returns HTTP 200 and a VOTable with `QUERY_STATUS` `ERROR`. Treat a body that starts with `<?xml` as an error, not as data.

Known on 2026-11-15 (measured):

- `CONTAINS(POINT(...),CIRCLE(...))` fails: use `ra BETWEEN ... AND dec BETWEEN ...`.
- Columns that work: `source_name, ra, dec, w1mpro_pm, w2mpro_pm, pmra, pmdec, sigpmra, sigpmdec`.
- A 4 by 4 degree box with the filter below takes about 20 s and returns tens of rows.

Not verified (check first, write the answer into section 2 of this page):

- Names of the flag columns (`ab_flags`, `cc_flags`, `w1flux_pm`, ...). Run `SELECT TOP 1 * FROM catwise2020.main` and read the header. If a confusion flag exists, add it to the rejection rules in section 4.
- Whether `pmra` includes the factor cos(dec). Test: at dec −56.8, Epsilon Indi B has 3.97 ″/yr west. If CatWISE shows about 2.2 there, it does not include cos(dec): multiply by 1/cos(dec) before use. Add a unit test for the answer.
- The reference epoch of the CatWISE positions. The design assumes 2015.4. Read it in the catalogue documentation and put the value in one constant `CATWISE_EPOCH`.
- Rate limits. Send tiles one at a time with a 2 s pause. On HTTP 429 or 5xx, back off (5, 20, 60 s), then stop with a clear message.

Second host, only if Data Lab is down: IRSA TAP table `catwise_2020`. Column names differ. Do not build it now. Leave a `# ponytail:` comment where the host is chosen.

## 3. Stage 0: scan

File: `pipeline/survey.py`. Command: `python pipeline/survey.py scan --box RA0 RA1 DEC0 DEC1 [--tile 4]`.

Tiles: bands of `--tile` degrees in Dec. Inside a band, the RA step is `tile / cos(max|dec| of the band)`, capped at 360. Boxes are half-open: `ra >= a AND ra < b AND dec >= c AND dec < d`. A box that crosses RA 0 is out of scope: reject it with a clear error.

Query for one tile (the filter is constant, keep it in one dict `FILTER`):

```sql
SELECT source_name, ra, dec, w1mpro_pm, w2mpro_pm, pmra, pmdec, sigpmra, sigpmdec
FROM catwise2020.main
WHERE ra >= {ra0} AND ra < {ra1} AND dec >= {dec0} AND dec < {dec1}
  AND w2mpro_pm < 15.5
  AND pmra*pmra + pmdec*pmdec > 0.09
  AND pmra*pmra + pmdec*pmdec > 36*(sigpmra*sigpmra + sigpmdec*sigpmdec)
```

The 8 mag bright limit is NOT in the query. Apply it in stage 1, so a rejected bright row stays visible in the CSV.

Also run, for each tile, `SELECT COUNT(*) FROM catwise2020.main WHERE <same box>` and store the number. It is the `rows_screened` of the tile. (Measured: about 20 s for 4 by 4 degrees at dec −7.)

Output, one file per tile: `data/cache/survey/tiles/ra{ra0:06.2f}_dec{dec0:+06.2f}.csv` (git-ignored). Write the CSV to `*.tmp`, then rename, so a stopped run never leaves a half file. A tile whose file exists is skipped. The tile's row count goes in `data/cache/survey/tiles/<same>.meta.json` with the box and the run date.

On timeout (120 s) or a server error about size: split the tile into four and retry each part. Stop splitting below 0.5 degrees and report the tile as failed.

Tile area in square degrees (exact): `d_ra_rad * (sin(dec1) - sin(dec0)) * (180/pi)**2`. Name it `tile_area_deg2`. Unit test: the tiling of the whole sky sums to 41,252.96 within 1 %.

## 4. Stage 1 and 2: build (match and rank)

Command: `python pipeline/survey.py build [--simbad-top 200]`. Reads every tile CSV and meta. Writes `app/data/survey/index.json`. All functions in this section are pure (no network) except `gaia_known` and `simbad_known`, which take a fetch function as argument so tests pass a fake.

### 4.1 Merge split rows

CatWISE splits a fast mover into several rows (WISE 0855 gives four rows within 25″). Merge rows that lie within `MERGE_ARCSEC = 30` of each other, single linkage. Use a grid hash with cells of 30″ (pure Python, no numpy). The sky distance uses the small-angle formula with cos(dec).

For each group: the representative is the row with the smallest `sqrt(sigpmra² + sigpmdec²)`. Keep `n_rows` and the list of member names. Do not average positions.

### 4.2 Reject artefacts

First matching rule wins. Each gives `grade: "rejected"` and a `reason` string a visitor can read:

| Rule | Reason text |
|---|---|
| representative `w2mpro_pm < 8.0` | "Too bright for WISE: a saturated star gives a false motion." |
| a confusion or artefact flag, if section 2 finds one | "Catalogue flags this row as an artefact." |

Measured example that must be rejected: `J085417.52-052602.9`, W2 = 5.5, motion −14.4 ″/yr.

### 4.3 Explain known objects

For rows not rejected:

1. **Gaia.** One TAP box query per tile: Gaia DR3 stars in the tile box (plus 0.1° margin) with `pmra*pmra + pmdec*pmdec > 90000` (above 300 mas/yr). Use `https://gea.esac.esa.int/tap-server/tap` (as `fetch.py` does). Move each star to `CATWISE_EPOCH`. Mark `known` when a star lies within 3″ and its motion is within 30 % of the catalogue motion. Reason: "Gaia DR3 star {source_id} moves along this path."
2. **SIMBAD.** Only for the best `--simbad-top` rows by score, and only the ones still `candidate`. Reuse `vet.simbad_cone(ra, dec, radius=10)` (it tries two hosts). Mark `known` when an object within 10″ has a motion within 30 % of the catalogue motion. Reason: same words as `vet.grade` ("SIMBAD lists {name} here, moving {pm} ″ per year."). Rows below the top-N get `simbad_checked: false` and the page says so.

Grade words are `candidate`, `known`, `rejected`. Same meaning as in `pipeline/vet.py`. Do not invent a fourth.

### 4.4 The score

```python
def score(c):
    pm = hypot(c.pmra, c.pmdec)                      # arcsec/yr
    err = hypot(c.sigpmra, c.sigpmdec)
    certainty = min(pm / err, 30) / 30
    colour = clip(w1 - w2, 0, 4) / 4                 # w1 missing: use W1_LIMIT = 18.0 and set w1_limit true
    reach = 1.0 if pm * (SPHEREX_YEAR - 2010.5) >= 12.3 else 0.0   # 2 SPHEREx pixels (6.15")
    return certainty + colour + reach                # 0 to 3
```

Constants at the top of the file with a comment each. `SPHEREX_YEAR = 2026.0`. `W1_LIMIT` is a guess: mark it `# ponytail:` and ask the owner. The score has no model and no weights. The page shows the three terms (hover or detail row), so a reader can check the sum.

Sort: `candidate` first, by score descending; then `known`; then `rejected`. Keep at most 500 rows in `index.json`: all candidates first, then known, then rejected up to the limit. Put the full counts in `counts`.

### 4.5 Tile borders

A mover group can cross a tile border. Load ALL tile CSVs first, then merge across them. Do not merge tile by tile. State this in a comment.

### 4.6 `app/data/survey/index.json`

```json
{
  "catalogue": "CatWISE2020",
  "catalogue_epoch": 2015.4,
  "host": "NOIRLab Astro Data Lab",
  "run_date": "2026-11-15",
  "tiles": 4,
  "rows_screened": 587016,
  "area_deg2": 16.0,
  "sky_fraction": 0.00039,
  "filter": {"w2_max": 15.5, "w2_min": 8.0, "pm_min": 0.3, "snr_min": 6, "merge_arcsec": 30},
  "counts": {"rows": 41, "objects": 25, "candidate": 3, "known": 8, "rejected": 14},
  "controls": {"found": 0, "of": 0},
  "items": [
    {"rank": 1, "name": "J085508.34-071439.2", "ra": 133.78476, "dec": -7.24425,
     "pmra": -7.97, "pmdec": 0.81, "pm": 8.01, "pm_snr": 25.0,
     "w1": 17.97, "w2": 13.82, "w1_limit": false,
     "score": 2.83, "terms": {"certainty": 0.83, "colour": 1.0, "reach": 1.0},
     "grade": "known", "reason": "SIMBAD lists WISE J085510.83-071442.5 here, moving 8.00 ″ per year.",
     "simbad_checked": true, "n_rows": 4,
     "spherex": null, "target": null}
  ]
}
```

`spherex` is `null`, `"confirmed"`, `"not_confirmed"`, `"too_slow"` or `"not_covered"` (phase 3). `target` is the field id or `null`.

`sky_fraction` is the sum of finished tile areas divided by 41,252.96. The page shows it. It is the honesty number: never round it up.

Size: keep the file under 300 KB. Write it with `indent=1` like the other data files. The 500-row cap keeps it small.

## 5. Phase 2: the queue page

Files: `app/queue.html`, `app/queue.js`, `app/queue.css`. Follow `app/index.html` for head, theme script, `brand.css`, `home.css`, header and footer. Use relative URLs only (the live site is under `/wanderers/`). Both themes must work: use the tokens of `brand.css`, no new colours.

Add "Candidates" to the main nav of `app/index.html` (`<nav class="site-nav">`) and the footer list. Check `app/sw.js`: if it lists files to cache, add the three files and bump its cache name. Bump `?v=` on any file you edit that has one.

Page content, top to bottom:

1. Heading "Candidate queue", one sentence: what it is. Beside it, the honesty line: "Screened {rows_screened} CatWISE2020 rows, {area_deg2} square degrees, {sky_fraction as percent} of the sky, on {run_date}."
2. A control line: "Control check: found {found} of {of} known brown dwarfs." Hide it when `of` is 0.
3. Filter buttons: Candidates (default), Known, Rejected, All. Show counts. A plain `<button>` group with `aria-pressed`.
4. A table (inside an `overflow-x:auto` box). Columns: rank, name, motion (″/yr, with the sentence "moves its own width in N years" is NOT needed), W1 − W2, score, status, SPHEREx, links. A row opens a detail line with the three score terms, the reason text, and `n_rows`.
5. Limits box, from section 6 of the design, word for word where possible.

Links for each row (build them in one pure function, `rowLinks(item)`, exported for the test):

- **Observatory**: `observatory.html?target=<target>`, only when `target` is set.
- **WiseView**: `http://byw.tools/wiseview#ra=<ra>&dec=<dec>&size=100` (not verified: check that the page opens at the position; if the fragment names are wrong, link the plain `http://byw.tools/wiseview`).
- **SIMBAD**: reuse the existing "Check it yourself" link builder. `grep -rn "simbad" app/*.js` to find it. It must use the harvard mirror host as the fallback documented in `docs/HANDOFF.md`.
- **Report**: `https://github.com/kneha07/WANDERERS/issues/new?labels=candidate-report&title=<name>&body=<text>`. The text has name, RA, Dec, motion, score, grade, the catalogue and the run date, and no personal data. Create the label first: `gh label create candidate-report --description "A visitor reports a catalogue candidate"`. A visitor without write access cannot set a label; that is fine.

Empty and error states: the page shows "No data yet" when `data/survey/index.json` fails to load, and "No candidates in this sky area" when a filter has no rows. Both are plain sentences, not alerts.

Accessibility: real `<table>`, `<th scope>`, buttons not divs, visible focus, no information in colour alone (status has a word).

Test, `test/queue.test.js`, in the style of `test/framemath.test.js` and `test/fakepage.js`: `rowLinks` for a verified and an unverified row; the Report URL is encoded and under 2,000 characters; the filter keeps counts; empty data gives the "No data yet" text. Run `node --test test/*.test.js` (all pass) and `node --check app/queue.js`.

Browser check: use the headless Edge recipe in `docs/HANDOFF.md`. Save a desktop and a 400 px screenshot in `artifacts/survey/`. Read both PNGs and say what you saw.

## 6. Phase 3: verify the top rows

Goal: a candidate row gets a SPHEREx result and a link to an Observatory page, with no hand-written target entry.

### 6.1 `fetch.py`: a field with a motion

`resolve()` already has a branch for a target with a `literature` block (`ra, dec, epoch, pmra, pmdec, parallax, ref`). It is used by WISE 0855. Reuse it. Do not touch the `position` branch.

Change `add_position(ra, dec, name=None, fov=None)` to also accept `motion=None`: a dict `{"epoch": 2015.4, "pmra": mas_per_yr, "pmdec": mas_per_yr, "ref": "CatWISE2020 <name>"}`. When set:

- write `"literature": {"ra": ra, "dec": dec, "epoch": ..., "pmra": ..., "pmdec": ..., "parallax": None, "ref": ...}` and do NOT write `"position"` (because `resolve` checks `position` first);
- keep `"story": "explore"` and `fov_arcsec`.

Units: CatWISE motion is ″/yr, `resolve` wants mas/yr. Multiply by 1000 (and by 1/cos(dec) if section 2 shows it is needed).

Check what `parallax: None` does downstream (`insights()` in `evidence.py`, `analyze.py`, `gaia_facts.py`). If anything fails on `None`, handle it where it fails. The honest value is "unknown", not 0.

CLI: add `--pmra --pmdec --epoch --ref` to the `--ra` branch of `fetch.py` `__main__`. Add a test in `tests/test_fetch.py`: `add_position` with a motion writes `literature`, no `position`, and the id is stable.

Field size: the SPHEREx date is about 2026. A mover at 8 ″/yr is 130″ from its 2010 place, so 300″ is the smallest sensible field. Use the default. Use `fetch.py --max 36` for survey fields (the quick look): fewer cutouts, faster. Measured on a real 2′ field: about 12 minutes with the full 150.

### 6.2 `vet.py` and `evidence.py`: run for chosen ids only

`vet.main()` loops over every `app/data/*/target.json` and calls SIMBAD for every mover each time. Add optional ids: `python pipeline/vet.py wise0855 pos_...`. With no ids, behave as now. Do the same for `evidence.py` if it has the same loop. Add one unit test for the ids filter.

Survey fields must not enter the home page list. Read `evidence.main()` and see how `app/data/index.json` is made (the six `pos_*` targets on main show it may include user fields). Decide with evidence, and make survey fields (id prefix `sv_`, set by `survey.py verify` through the position id, or a field `"survey": true` in `target_def.json`) stay out of `index.json`. Add a test.

### 6.3 `survey.py verify`

Command: `python pipeline/survey.py verify [--top 25] [--only NAME]`.

For each of the top K `candidate` rows without a `target`:

1. `fetch.add_position(ra_at_catalogue_epoch, dec, name, motion=...)` (via subprocess, same interpreter, one row at a time, in a try block: one failure must not stop the run; record it).
2. Run `fetch.py`, `analyze.py <id>`, `gaia_facts.py`, `evidence.py`, `vet.py <id>` in that order.
3. Read `app/data/<id>/target.json` and set `spherex`:

| Condition | `spherex` |
|---|---|
| fewer than 2 SPHEREx visits, or no SPHEREx cutout at the position | `not_covered` |
| `changes.target_recovered` is `true` | `confirmed` |
| `changes.target_recovered` is `false` | `not_confirmed` |
| `changes.target_recovered` is `null` (shift below 2 pixels) | `too_slow` |

4. Write `spherex` and `target` into `index.json`. Write the file after every row, so a stopped run keeps its work.

Honest wording on the page: `confirmed` means "the pipeline found a dot at the predicted place in SPHEREx", not "real". `not_confirmed` means "not found", not "not there" (the search can miss, see `changes.target_recovered` in README).

Size: a prepared field is about 3.6 MB. K = 25 adds about 90 MB to `app/data/`. Do not commit more than 10 fields without asking the owner. Default K = 10. Put the rest under `data/cache/` only and set `target` to `null`.

Acceptance test (needs phase 0 and network): run `verify --only J085508.34-071439.2`. The new field has a `sv_`/`pos_` id, not `wise0855`. `spherex` is `confirmed`. If it is `not_confirmed` after phase 0, do not tune the thresholds: write what you measured in the commit message and in `artifacts/survey/verify-wise0855.md`.

## 7. Phase 4: more sky, controls, docs

- Scan the 16 square degree test box (done: the CSV is in `artifacts/survey/`) plus the 8 boxes around it. Report the time for each tile. Do not start a full-sky scan.
- Control check: take about 10 known cool brown dwarfs near the scanned boxes from SIMBAD (object type `BD*` or `Y*`, motion above 0.5 ″/yr, W2 below 15). Save the list with the query in `pipeline/survey_controls.json`. `build` counts how many are in the queue (any grade) and writes `controls`. Report found and missed ones in the commit message. A miss is information, not a failure: say why it missed (cut, merge, artefact rule).
- README: add one short section "Catalogue survey" with the honest numbers and the limits. Add a row to `docs/architecture.md` section 3 (a new box in the diagram: `survey.py`). Link both specs.
- Update `docs/product-gaps.md`: gap "no sky-wide search" → what is done, what is not.

## 8. Tests (all must pass; list the results in the commit message)

```bash
python3 -m unittest tests.test_survey tests.test_evidence tests.test_vet
python3 test/test_fov.py
node --test test/*.test.js
node --check app/queue.js app/app.js server.js fields.js
# with a numpy Python (venv): tests/test_movers.py, tests/test_fetch.py, tests/test_data_quality.py
```

`tests/test_survey.py` (stdlib only). Copy `artifacts/survey/catwise-box-ra132-136-dec-9--5.csv` to `tests/fixtures/survey/catwise-box.csv` and use it. Assertions:

1. The four rows near WISE 0855 (`J085508.34-071439.2`, `J085506.91-071437.5`, `J085507.96-071439.3`, `J085507.45-071437.8`) merge into one object with `n_rows == 4`. Its representative is `J085508.34-071439.2`. (Smallest error: 0.19/0.26. Check by running.)
2. `J085417.52-052602.9` (W2 5.5) is `rejected` with the "Too bright" reason.
3. With fake Gaia and SIMBAD functions that return nothing, WISE 0855 has the highest score among the rows that are not rejected. (By hand: 0.83 + 1 + 1 = 2.83; the next is near 2.1. Check by running.)
4. With a fake SIMBAD that lists `WISE J085510.83-071442.5` at that place, WISE 0855 becomes `known` and drops below every `candidate`.
5. `tile_area_deg2` over a whole-sky tiling is within 1 % of 41,252.96. The tile list for one box is half-open and covers it with no gap and no overlap.
6. A tile CSV that is the VOTable error text raises an error and writes no tile file.
7. A stopped scan resumes: with one tile file present, `scan` makes no request for it (fake fetch counts calls).
8. `sky_fraction` in `index.json` equals the finished area, not the requested area, when one tile failed.

Run each new test once with the new code removed, to see it fail (a test that cannot fail is not a test).

## 9. Out of scope (do not build)

- Learnt ranker. No labels. Add at about 100 graded rows.
- Any server, database, vote system, login or hosted API.
- A scan of the whole sky. Estimate only: about 14 hours for one stream, from one measured tile.
- SPHEREx pixel-by-pixel search, asteroid check (the page says it is not done), IRSA/CDS second host.
- Changes to the eleven mission pages, `explain.json`, or the Observatory layout.

## 10. Report back

Finish with a short record in `artifacts/survey/run-<date>.md`: what you built, each test command and its result, what you could not run, each "not verified" item from this page and its answer, and any new issue you opened with `gh issue create`. Commit it on the branch.
