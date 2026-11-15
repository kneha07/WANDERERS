# WANDERERS Sky Survey: interface contract

The automated, sky-scale mover search ("billions of detections → automated processing → ranked candidates →
humans investigate"). Several people/agents build it in parallel against this contract; keep names and shapes
exactly as written. Python package: `pipeline/survey/` (import as `survey` with `pipeline/` on `sys.path`, like
the other pipeline modules). Units: degrees for positions, decimal years for epochs, mas/yr for proper motion,
arcsec for separations and errors on the sky, Vega magnitudes.

## Data source

NEOWISE-R Single-exposure (L1b) Source Table, Parquet, partitioned by HEALPix order 5 (nested, nside 32,
12,288 tiles of ~3.36 deg²), on NASA IRSA's public AWS bucket (anonymous, region us-west-2):

    nasa-irsa-wise/wise/neowiser/catalogs/p1bs_psd/healpix_k5/{year}/neowiser-healpix_k5-{year}.parquet/healpix_k0={k5 >> 10}/healpix_k5={k5}/part0.snappy.parquet

`{year}` is `year1` … `year11` and `addendum` (addendum is missing for some tiles: treat a missing file as empty).
Read with `pyarrow.parquet.read_table(path, filesystem=pyarrow.fs.S3FileSystem(anonymous=True, region="us-west-2"), columns=[...])`.
One tile-year is ~0.8–2 M rows and loads in ~2 s for ~17 columns. **Schemas differ in nullability between years**:
cast every table to an all-nullable schema before concatenating (`pa.schema([f.with_nullable(True) for f in t.schema])`).
Columns used (all exist): `source_id, ra, dec, sigra, sigdec, sigradec, mjd, w1mpro, w1sigmpro, w1snr, w2mpro,
w2sigmpro, w2snr, cc_flags, ph_qual, nb, na, qual_frame, qi_fact, saa_sep, moon_masked, scan_id, frame_num`.

Machine limits for the real run: 8 CPUs, ~8–9 GB RAM, < 9 GB free disk. **Never write raw tables to disk**;
process a tile year by year and keep only reduced per-visit source lists in memory (float32/float64 numpy arrays).

Test fixtures (real data, all 12 year folders, cone of 4′): `tests/fixtures/neowise_kapteyn_4arcmin.parquet`
(Kapteyn's Star, Gaia DR3 2016.0: RA 77.95994, Dec −45.04381, pmra 6491.2, pmdec −5708.6 mas/yr, W2≈5.8,
bright) and `tests/fixtures/neowise_wise0855_4arcmin.parquet` (WISE 0855−0714: RA 133.7864, Dec −7.2439 near
2017.0, pmra −8123, pmdec +673 mas/yr, W2≈14, W1 faint/undetected).

## Modules and functions

### `survey/tiles.py` (data access)
- `YEARS: list[str]`, `COLUMNS: list[str]`, `NSIDE = 32`, `N_TILES = 12288`, `TILE_AREA_DEG2 ≈ 3.357`
- `tile_of(ra, dec) -> int` (HEALPix nested order 5), `tile_center(k5) -> (ra, dec)`, `tile_corners(k5) -> [[ra, dec] x4]`
- `read_tile_year(k5, year, fs=None, columns=COLUMNS) -> pyarrow.Table | None` (None when the file is missing)
- `read_fixture(path) -> pyarrow.Table` (local parquet, same columns)
- `good_mask(table) -> numpy bool array`: quality cuts for astrometry (document each cut in the docstring), at least:
  `cc_flags` first two characters `'00'` (no W1/W2 artefact), `qual_frame > 0`, `saa_sep > 0`, `moon_masked` W1/W2 `'00'`,
  `nb <= 2`, and (`w1snr >= 5` or `w2snr >= 5`).

### `survey/link.py` (core: visits → sources → tracks → motions)
- `split_visits(mjd: ndarray, gap_days=20.0, max_len_days=12.0) -> ndarray[int]` visit index per detection
  (a new visit after a gap > gap_days; long continuous coverage near the ecliptic poles is cut into ≤ max_len_days windows).
- `visit_sources(ra, dec, mjd, w1, w2, w1err, w2err, sigra, sigdec, visit) -> dict of arrays`: within each visit,
  cluster detections of the same source (radius ~2.5″), require ≥ 2 detections, and return one row per
  (visit, source): `ra, dec, epoch (decimal year), w1, w2, n, sig (arcsec, position error of the mean), visit`.
- `link_tracks(vs) -> list[ndarray of row indices]`: link per-visit sources into tracks over the whole time span,
  (a) stationary and slow sources by friends-of-friends with a ~2.5″ linking length and at most one row per visit
  per track (split chains that take two rows from the same visit), and (b) **fast movers up to 12″/yr** (WISE 0855
  moves ~4″ per 6-month step) among rows left in short tracks, by a velocity search: candidate velocities from pairs
  of rows in different visits, accepted when ≥ 5 distinct visits agree within ~1.5″ of a straight line.
- `fit_motion(epoch, ra, dec, sig) -> dict`: weighted linear fit on the tangent plane about the mean position:
  `ra, dec` at `epoch0` (mean epoch), `pmra` (includes cos dec), `pmdec`, `pm`, `pm_err`, `pm_snr`, `chi2r`,
  `n_visits`, `span_yr`. Optionally a parallax term (Earth position from astropy's built-in ephemeris, offline);
  if fitted, add `plx`, `plx_err` (mas).
- `process_tile(k5, reader=read_tile_year, years=YEARS, min_visits=6, min_pm=150.0, min_pm_snr=5.0) -> dict`
  (TileResult below). `reader(k5, year)` returns a table or None, so tests can pass a fake reader built from fixtures
  or synthetic data. Movers = tracks with ≥ `min_visits` visits, `pm ≥ min_pm` mas/yr and `pm_snr ≥ min_pm_snr`,
  after rejecting obvious artefacts (huge chi2r, tracks along a scan direction only, saturated W1/W2 < ~6 if unreliable).

### `survey/rank.py` (catalogue check and ranking)
- `crossmatch_gaia(movers, cache_dir, tap_url="https://gea.esac.esa.int/tap-server/tap/sync", radius_arcsec=3.0, timeout=60) -> movers`
  Adds `gaia` (shape below) to each mover by comparing with Gaia DR3 sources propagated to the mover's epoch with their own
  proper motion. Batch the query (ADQL upload of the candidate list, or one cone per tile), cache answers on disk under
  `cache_dir`, and when the service fails set `gaia.checked = false` instead of raising.
- `score(mover) -> (float, list[str])`: higher = more interesting; reasons in plain words. Reward: no Gaia counterpart
  ("unexplained"), high `pm_snr`, red colour (W1−W2 ≥ 0.5 suggests a cold brown dwarf; ≥ 2 extreme), many visits,
  long span, good chi2r. Penalise: Gaia match, high chi2r, few visits, very bright (saturation), near a tile edge.
- `classify(mover) -> "unexplained" | "known (Gaia)" | "likely artefact" | "not checked"`
- `rank(movers, top=1000) -> list` sorted by score (desc) with `rank`, `score`, `reasons`, `class` added.

### `survey/run.py` (orchestration, sharded and resumable)
- CLI: `python pipeline/survey/run.py --tiles validation|random:N|list:1,2,3|all --workers 3 --out app/data/survey [--seed 1] [--max-hours H]`
- Processes tiles in a `multiprocessing` pool (each worker: `process_tile`), writes `out/tiles/<k5>.json` per tile as
  soon as it finishes, keeps `out/manifest.json` (done, failed with error text, timings) so a rerun skips finished tiles,
  then runs `crossmatch_gaia` + `rank` and writes `out/leaderboard.json` and `out/summary.json`. Logs progress with
  throughput (tiles/hour, detections/second).
- `validation` = the tiles holding the WANDERERS targets with known motion (Barnard's Star 269.452/+4.693,
  Kapteyn's Star 77.960/−45.044, WISE 0855 133.786/−7.244, Luhman 16 162.308/−53.318, Wolf 359 164.103/+7.003,
  Lalande 21185 165.831/+35.949, Proxima 217.429/−62.679, 61 Cygni 316.748/+38.764, Epsilon Indi 330.840/−56.786).

### `survey/validate.py` (injection–recovery and known-mover recovery)
- `inject(table, movers_spec, rng) -> table` adds synthetic detections of movers (given pm, position, magnitude, noise)
  into a real or synthetic detection table with realistic cadence (copy the visit epochs present in the table).
- `recovery(process_tile_fn, ...) -> dict` completeness vs pm and magnitude, false-positive count on mover-free data,
  pm accuracy; and `known_movers(results, known) -> dict` recovered/missed known high-motion stars with pm error.
- Writes `app/data/survey/validation.json`.

## Output files (`app/data/survey/`, read by the web page)

`tiles/<k5>.json` (TileResult):
```json
{"k5": 8545, "center": [77.6, -44.9], "years": ["year1", "..."], "n_detections": 21000000, "n_good": 15000000,
 "n_visits": 22, "n_visit_sources": 2400000, "n_tracks": 150000, "n_movers": 12, "seconds": 41.2,
 "movers": [Mover, ...]}
```
Mover:
```json
{"id": "8545-0003", "k5": 8545, "ra": 77.95, "dec": -45.06, "epoch": 2019.2, "pmra": 6490.1, "pmdec": -5705.3,
 "pm": 8641.2, "pm_err": 4.1, "pm_snr": 2100.0, "chi2r": 1.3, "n_visits": 21, "span_yr": 10.0,
 "w1": 6.1, "w2": 5.8, "w1w2": 0.3, "plx": null, "plx_err": null,
 "track": [[2014.12, 77.98, -45.04], ["… one per visit, at most 30 …"]], "flags": []}
```
After ranking (leaderboard rows) a mover also has
`"gaia": {"checked": true, "match": true, "source_id": "4810594479418041856", "sep_arcsec": 0.4, "pm": 8644.0, "g": 8.06}`,
`"score": 3.2, "reasons": ["…"], "class": "known (Gaia)", "rank": 1`.
A leaderboard row whose source was also found in a neighbouring tile ends with `"duplicates": ["8546-0007"]`
(the other copies' ids; see `survey/dedupe.py` below). Rows without duplicates have no such key.

`leaderboard.json`: `{"generated": "ISO time", "n_candidates": int, "candidates": [ranked movers, top 1000]}`

### Cross-tile duplicates (`survey/dedupe.py`, used by `run.publish`)
A source on a tile boundary can be linked in both tiles. Before ranking, publish finds movers from touching tiles
whose positions agree within 3″ (plus 3σ of the move, at most 8″) when each is moved with its own motion to the
midpoint of the two epochs, and whose motions agree (3D velocity difference below the largest of 20 mas/yr, 3σ of
the combined `pm_err`, 3 % of the motion). The track with more visits (then higher `pm_snr`, then smaller id) is
kept; the others are left out of the ranking and of every count (`movers`, `unexplained`, `tiles`,
`n_candidates`), and a limits line says how many were merged. Gaia is still asked about every mover of a tile, so
the per-tile Gaia cache stays valid. `python pipeline/survey/dedupe.py <out>/tiles` counts duplicates in tile files.

### Promoting a candidate (`survey/promote.py`)
`python pipeline/survey/promote.py --id <id> [--id …] [--top N [--unexplained]] [--run] [--json]` prints (default)
or runs the commands that make a candidate a full WANDERERS target: `fetch.py --ra --dec --fov --name`,
`analyze.py <target id>`, `evidence.py`, then `observatory.html?target=<target id>`. The position is the
candidate's, moved with its own motion to 2018.5 (midway between AllWISE 2010.5 and SPHEREx 2026.5); the field is
300″, or 600″/900″ when the 2010–2026 path needs it.

`summary.json`:
```json
{"generated": "ISO", "tiles_done": 120, "tiles_total": 12288, "sky_fraction": 0.0098, "sky_deg2": 402.8,
 "detections": 2400000000, "good_detections": 1700000000, "visit_sources": 280000000, "tracks": 18000000,
 "movers": 1500, "unexplained": 40, "runtime_hours": 1.6, "tiles_per_hour": 75, "detections_per_second": 410000,
 "tiles": [[8545, 12, 0], ["k5, movers, unexplained"]], "validation": {"…": "copy of validation.json summary"},
 "method": "plain-language description", "limits": ["…"]}
```

## Web page (`app/survey.html`, `app/survey.js`, styles in a versioned stylesheet)
Reads `data/survey/summary.json` and `data/survey/leaderboard.json`. Shows the scale (detections, tiles, sky
fraction), an all-sky map of processed tiles, the validation result, and the ranked candidate table (filters:
unexplained only, min pm, red only; sort), and for a selected candidate: its NEOWISE track on an Aladin Lite view
(IRSA SPHEREx HiPS `https://irsa.ipac.caltech.edu/data/hips/SPHEREx/spherex_allsky_cube` and AllWISE colour
`https://irsa.ipac.caltech.edu/data/hips/CDS/AllWISE/RGB-W4-W2-W1`), its numbers and reasons, and "investigate"
links: `observatory.html?ra=…&dec=…` (sky map), Through Webb, Backyard Worlds (https://www.zooniverse.org/projects/marckuchner/backyard-worlds-planet-9),
copy coordinates. Discovery tools (`app/surveytools.js`): filters for min visits, min motion S/N, hiding tile-edge /
crowded / saturated / likely-artefact rows, a "high-confidence" preset (≥ 12 visits, S/N ≥ 10, all four hidden) and
a sort menu, all kept in the address (`class, minpm, red, visits, snr, hide, q, tile, sort, dir`, plus
`preset=high` in a link); CSV and JSON download of the filtered, sorted list (Blob, no server); links to IRSA
Finder Chart, Aladin Lite and the Legacy Surveys viewer at today's predicted position, SIMBAD and VizieR at J2000
and Gaia DR3 in VizieR at 2016.0; the candidate's position in 2000, 2016, today and 2030; the `promote.py` command.
Same brand/theme rules as the other pages (theme bootstrap, `brand.css`, logo, theme toggle,
Day/Night tokens), mobile-friendly at 375 px with no sideways scroll, and every element id the script uses must exist.

## Rules for everyone
- Work only in your own files; don't edit other people's modules (stub/mock them in tests via the contract).
- At least **50 tests** for your part (pytest under `tests/` for Python, node:test under `test/` for the page).
  Tests must not need the network (use the fixtures or synthetic data); mark any optional network test with a skip.
- Commit on your branch with `git -c user.name=rajryadav4 commit`; never add Co-Authored-By/Claude attribution lines.
- Python: `"/Users/rajranjityadav04/Downloads/NASA HACKATHON/wanderers/.venv/bin/python"` (numpy, scipy, astropy, pyarrow, pytest).
