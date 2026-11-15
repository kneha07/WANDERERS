# SPHEREx data access for a browser blink tool

Research date: 2026-11-14. Challenge: [Planet X and SPHEREx](https://www.spaceappschallenge.org/2026/challenges/planet-x-and-spherex/).

Labels:

- **TESTED**: a live request that we ran on 2026-11-14 (curl, or `fetch()` in a browser).
- **UNVERIFIED**: not confirmed from a primary source or a test.

## Summary

```
RA/Dec ──> IRSA SIA2 (spherex_dr1 + spherex_qr3)  ──> list of exposures (time, detector, URL)
              no CORS: needs a backend proxy          │
                                                      ├─> IRSA cutout  ?center=..&size=..   (no CORS, ~4 MB each)
                                                      └─> AWS S3 same file + HTTP Range     (CORS *, ~250 KB for 30 rows)
```

| Item | Result |
|---|---|
| Public products | DR1 (Apr 2025 to May 2026) and QR3 (May 2026 onward, weekly). QR2 is retired from search. |
| Image | 2040 x 2040 px, 6.15"/px, about 66 MB MEF per detector exposure |
| Query | SIA2 `https://irsa.ipac.caltech.edu/SIA?COLLECTION=spherex_dr1&POS=circle+RA+DEC+0.001` (about 0.4 s) |
| Cutout | Yes: `<access_url>?center=RA,DEC&size=20px`. Every cutout is about 4 MB, because the full EPSF table comes with it. |
| CORS | IRSA SIA, TAP and cutouts: **no**. S3 bucket `nasa-irsa-spherex`: **yes** (`*`, Range allowed). IRSA HiPS: **yes**. CDS Sesame: **yes**. |
| Epochs | 3 or 4 survey passes per position so far. Each pass has about 100 to 150 exposures (all 6 detectors). |
| Motion | Barnard 1.7 px/yr, WISE 0855 1.3 px/yr, eps Ind B 0.76 px/yr. The PSF FWHM is about 1.2 px. The motion is small but measurable. |

## 1. Challenge Resources tab

Source: <https://www.spaceappschallenge.org/2026/challenges/planet-x-and-spherex/?tab=resources> (read in a browser, TESTED).

| Link | What it offers |
|---|---|
| [NASA/IPAC Infrared Science Archive](https://irsa.ipac.caltech.edu/Missions/spherex.html) | SPHEREx resources at IRSA: releases, docs, tools |
| [SPHEREx Tutorial Notebooks](https://caltech-ipac.github.io/irsa-tutorials/spherex/) | Python Jupyter notebooks that show how to get SPHEREx data |
| [WiseView](http://byw.tools/wiseview) | A blink viewer for WISE data. The page names it as a model or inspiration. |
| [Gaia Mission Data](https://archive.stsci.edu/missions-and-data/gaia) | Gaia data. The page says: use DR3. |
| [NEOSSat](https://www.asc-csa.gc.ca/eng/satellites/neossat/) | CSA page about the NEOSSat asteroid and debris telescope |
| [Canadian Astronomy Data Centre (CADC)](https://www.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/en/) | Archive of Canadian and international observations |
| [NEOSSat Data Tutorial](https://github.com/asc-csa/NEOSSAT_Tutorial) | Python tutorial for NEOSSat data |
| [NEOSSat Dataset](https://data.asc-csa.gc.ca/dataset/neossat) | NEOSSat observation dataset |

## 2. Public SPHEREx data products

Sources: [IRSA SPHEREx page](https://irsa.ipac.caltech.edu/Missions/spherex.html), [DR1 overview](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/overview_dr1.html), [QR overview](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/overview_qr.html), [Archive docs: Data Products](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-products), [Explanatory Supplement v2.1, 2026-11-10](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/SPHEREx_Expsupp.pdf).

### Releases

| Release | Released | Status | SIA collection |
|---|---|---|---|
| QR1 | Jul 2025 | Retired Feb 2026 | - |
| QR2 | Oct 2025 | Not searchable after DR1. Direct download until Feb 2027. | - |
| QR3 | Sep 2026 | Current. New Quick Release images are added **weekly**. | `spherex_qr3`, `spherex_qr3_deep` |
| DR1 | Nov 2026 | Reprocessed QR2. Use DR1 + QR3 as one uniform set. | `spherex_dr1`, `spherex_dr1_deep`, `spherex_dr1_cube` |

Observed time coverage (TESTED with SIA): DR1 images span 2025-04-24 to 2026-05-14. QR3 images start 2026-05-16. The newest QR3 image that we saw is from 2026-10-02.

### Level 2 Spectral Image (one file per detector per exposure)

- Size: 2040 x 2040 px. Pixel scale: 6.15" x 6.15". One detector covers about 3.5 x 3.5 deg.
- Exposure time: 113.58 s. Measured PSF FWHM: about 7.4" (header `PSF_FWHM` in D3).
- File size: 65,790,720 bytes (TESTED with HEAD). The docs say "about 70 MB".
- File name: `level2_[ObsID]D[Det]_spx_l2b-v[Ver]-[YYYY-DDD].fits`. ObsID = `[Planning period]_[Large slew]_[Small slew]`.
- HDUs (TESTED on a DR1 file):

| HDU | EXTNAME | Content |
|---|---|---|
| 0 | PRIMARY | Empty |
| 1 | IMAGE | float32, MJy/sr. Zodiacal light is **not** subtracted. |
| 2 | FLAGS | int32 bitmap (bits in Explanatory Supplement Table 16) |
| 3 | VARIANCE | float32, (MJy/sr)^2 |
| 4 | ZODI | float32 zodi model, MJy/sr. Subtract IMAGE - ZODI to remove it. |
| 5 | EPSF | Binary table of PSF models, about 3.9 MB (QR2 calls this `PSF`) |
| 6 | WCS-WAVE | Lookup table that maps pixel to wavelength and bandwidth |

- Time keywords in the IMAGE header: `DATE-OBS`, `MJD-OBS`, `MJD-AVG`, `DATE-END`, `XPOSURE`.
- Spatial WCS: `RA---TAN-SIP` / `DEC--TAN-SIP` (3rd-order SIP). The distortion is up to 13 px (80") in the corners. Astrometric RMS < 0.3" against Gaia DR3.
- The image axes are not north-up. Each frame needs reprojection before you blink it.

### Wavelength per pixel (LVF)

Each detector has a Linear Variable Filter, so the wavelength changes along one axis of the array.

| Detector | Range (um) | R |
|---|---|---|
| D1 | 0.75 - 1.09 | 39 |
| D2 | 1.10 - 1.62 | 41 |
| D3 | 1.63 - 2.41 | 41 |
| D4 | 2.42 - 3.82 | 35 |
| D5 | 3.83 - 4.41 | 112 |
| D6 | 4.42 - 5.00 | 128 |

- D1-D3 (SWIR) and D4-D6 (MWIR) see the same sky through a dichroic (pairs 1/4, 2/5, 3/6).
- The `WCS-WAVE` HDU holds control points (X 9, Y 14, VALUES 2x9x14). Use bilinear interpolation to get the central wavelength and bandwidth at a pixel (accurate to about 1 nm). The header keys are `CTYPE1W='WAVE-TAB'` and `PS1_0W='WCS-WAVE'`.
- 17 channels per detector, 102 channels in total.
- **Blink effect:** a fixed star falls on a different LVF wavelength in each exposure, so its brightness changes from frame to frame. Compare frames from the same detector, and if possible the same wavelength range. Otherwise brightness changes look like movement.

### Other products

- **All-Sky Cube (DR1 only)**: 12,288 HEALPix order-5 tiles, 512 x 512 px at 12.9"/px, 102 channels. Zodi is subtracted. It is a **co-add**, so it has no time series.
- Spectral WCS product: CWAVE/CBAND full-size images (about 32 MB per detector).

## 3. Query images that cover an RA/Dec

### SIA2 (recommended, fast)

Source: [Archive docs: Data Access](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-access), [IRSA SIA](https://irsa.ipac.caltech.edu/ibe/sia.html).

Example (WISE 0855 at its 2025.5 position, TESTED, 0.35 s, 258 rows):

```
https://irsa.ipac.caltech.edu/SIA?COLLECTION=spherex_dr1&POS=circle+133.7609+-7.2423+0.001&RESPONSEFORMAT=VOTABLE
```

- Run it once per collection: `spherex_dr1`, `spherex_qr3`, and the `_deep` variants. One request cannot hold several `COLLECTION` values (UNVERIFIED).
- Use `RESPONSEFORMAT=HTML` for a human-readable table.
- The response is a VOTable with ObsCore columns, one row per detector image:

| Column | Example | Use |
|---|---|---|
| `t_min`, `t_max` | 60800.700028 (MJD) | Observation time |
| `energy_bandpassname` | `SPHEREx-D3` | Detector |
| `em_min`, `em_max` | 1.63e-6, 2.43e-6 m | Wavelength range of the detector |
| `obs_id` | `2025W19_1B_0116_1` | Exposure ID |
| `access_url` | `https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/...fits` | Full MEF, also the cutout base URL |
| `cloud_access` | `{"aws": {"bucket_name": "nasa-irsa-spherex", "key": "dr1/level2/...fits", "region": "us-east-1"}}` | S3 copy |
| `access_estsize` | 65791 (kB) | File size |
| `s_region` | `POLYGON ICRS ...` | Image footprint |
| `s_xel1`, `s_xel2`, `s_pixel_scale` | 2040, 2040, 6.150 | Image size |
| `obs_release_date` | 2026-09-27 | Release date |

- SIA lags new ingestion by about 1 day.
- Stability: we saw some intermittent `502 Proxy Error` replies. A retry after 3 s worked.

### TAP

- Endpoint: `https://irsa.ipac.caltech.edu/TAP/sync`. Tables: `spherex.obscore`, `spherex.plane`, `spherex.artifact`, `spherex.observation`, `spherex.provenance_input` (TESTED).
- The [cutouts tutorial](https://caltech-ipac.github.io/irsa-tutorials/spherex-cutouts/) joins `spherex.artifact` and `spherex.plane` with `CONTAINS(POINT('ICRS',ra,dec), p.poly)`. The tutorial reports 20 s for this query.
- TESTED: the same spatial query on `spherex.plane` ran more than 10 min. A query on `spherex.obscore` timed out after 120 s. **Use SIA for live user queries.** TAP has new data immediately after the weekly ingestion.

### Python

`astroquery.ipac.irsa` (`Irsa.query_sia(pos=..., collection='spherex_dr1')`, `Irsa.query_tap(...)`). Source: [astroquery IRSA docs](https://astroquery.readthedocs.io/en/latest/ipac/irsa/irsa.html). We did not run astroquery (UNVERIFIED in this environment).

### Name resolution

CDS Sesame returns position and proper motion with CORS `*` (TESTED from a browser). Example: `https://cds.unistra.fr/cgi-bin/nph-sesame/-oxp/SNV?Barnard`. It redirects (302) to a mirror. The SIMBAD TAP and `sim-id` URLs returned a CDS "page unavailable" error on 2026-11-14.

## 4. Server-side cutouts

Yes. Sources: [IRSA cutout parameters](https://irsa.ipac.caltech.edu/ibe/cutouts.html), [SPHEREx Cutout Tool](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/cutout_tool.html).

```
https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/2025W19_1B/l2b-v27-2026-197/3/level2_2025W19_1B_0116_1D3_spx_l2b-v27-2026-197.fits?center=133.7609,-7.2423&size=2arcmin
```

- `center=x,y[deg|rad|px]`: the default is degrees, J2000.
- `size=x[,y][px|arcsec|arcmin|deg]`: full width. The default is degrees.
- SPHEREx cutouts are never gzipped.
- The result is a MEF with all 6 extensions cut the same way, plus the full EPSF table.
- The center can be off the image, but the box must overlap the image. No overlap returns HTTP 500.
- The axes stay in detector orientation (not north-up).

TESTED results:

| Request | HTTP | Bytes | IMAGE size |
|---|---|---|---|
| `size=10px` | 200 | 4,037,760 | 10 x 10 |
| `size=2arcmin` | 200 | 4,037,760 | about 20 x 20 |
| `size=0.05` | 200 | 4,049,280 | 29 x 29 |
| `size=0.2` | 200 | 4,256,640 | 117 x 117 |

- **Each cutout costs about 4 MB**, because the EPSF table (3,947,152 bytes) is always included. No parameter removes it (the docs list none).
- One position has about 250 to 450 exposures, so all the cutouts for one position total about 1 to 2 GB. Filter by detector first, for example D2 or D5 only.
- Rate limit: the first request often returned `503` with `retry-after: 5`. A retry worked. The tutorial also reports failures under 10 parallel workers.

### Alternative: HTTP Range on S3 (no EPSF cost)

- The S3 copy supports `Range` and CORS (TESTED: `206 Partial Content`, `Access-Control-Allow-Origin: *`, `Access-Control-Allow-Headers: range`).
- The IMAGE HDU is an uncompressed float32 array (row = 2040 x 4 = 8,160 bytes).
- A 30-row strip that holds the target costs about 245 KB. Get it with:
  1. Read the headers (first about 60 KB).
  2. Use the SIP WCS to get the pixel row of the target.
  3. Request only those rows.
- Bucket: `nasa-irsa-spherex`, region `us-east-1`. Key = `cloud_access.aws.key` from SIA. The bucket allows anonymous access with no egress charge ([IRSA cloud access](https://irsa.ipac.caltech.edu/cloud_access/)). HTTPS form: `https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/<key>`.
- The IRSA `/ibe/data/` URL also supports Range (206), but it has no CORS header.

### The bucket without IRSA (TESTED 2026-11-15, while IRSA SIA, TAP and cutouts answered 502)

Used by `pipeline/spherex_s3.py` and the fallbacks in `pipeline/fetch.py` and `pipeline/spherex_releases.py`.

- Top level: `dr1/`, `qr2/`, `qr3/` (plus `index.html`). Each has `level2/` and calibration folders (`sip/`, `epsf/`, ...); `dr1/` also `hips5_cube/`.
- `level2/` holds half-week folders named by ISO year and week: `qr3/level2/2026W20_2A/` ... `2026W40_2A/` (41 folders; a file in `2026W40_2A` has `MJD-OBS` 2026-10-01). `dr1/level2/` runs `2025W17_4B` ... `2026W20_1A` (110 folders) and `qr2/level2/` `2025W17_4B` ... `2026W29_2A` (129).
- In a week folder: `l2b-v27-<date>/<detector>/level2_<obs_id>D<det>_spx_l2b-v27-<date>.fits`, about 1,700-1,800 files per detector, and sometimes an `l2b_retry-v27-<date>/` folder with a few dozen images reprocessed after a failure (none of them repeats a main-folder image in `2026W40_2A`).
- HDU layout of a QR3 file (65,131,200 bytes): primary header 2,880 B; IMAGE header 25,920 B then 2040 x 2040 float32; **FLAGS is a RICE_1 tile-compressed table with one tile per row** (`ZTILE1=2040`, `ZTILE2=1`; 2040 row descriptors, then the heap); VARIANCE and ZODI uncompressed float32; EPSF table; WCS-WAVE (720-byte table) last. So the first 10 blocks (28,800 B) hold everything needed to place an image on the sky.
- The IMAGE header's `SPS_FLAGS` (a HIERARCH card) is `all_sky`, `deep_north` or `deep_south` (with modifiers such as `,downlink`). 120 sampled images that IRSA SIA listed in `spherex_dr1` / `spherex_qr3` (R Dra and two other targets) all say `all_sky`: the deep-field images belong to the `_deep` collections.
- Full QR3 footprint index (`python pipeline/spherex_s3.py index qr3`, 48 requests at a time, on a shared machine): 41 week folders, 448,824 images; 225,205 headers read (28,800 B each) and 223,619 dichroic partners inferred; 0 failures; 2,014 s (34 min); 6.66 GB downloaded; 274.8 MB of JSON lines; 191 MB peak memory. One half-week took 40 s on its own.
- Searching that index against IRSA SIA (`spherex_qr3`, asked on 2026-11-15 after IRSA SIA answered again, about 16:15 UTC): for Barnard's Star, eps Ind B, Proxima Cen, R Dra, RW Aur and WISE 0855 SIA lists 119, 120, 124, 126, 109 and 0 images; the index search finds all 598 and one more (Barnard, `2026W34_1A_0238_2D3`). IRSA's `s_region` is the 4 corner points of the image with straight edges, and its SIA circle sits at the 2025.9 position; the index tests the target at each image's own time against an 8-point footprint that follows the SIP-curved edge, with the same 7.2" margin. Barnard's Star there is 4" past that image's curved edge at the time of the image.
- Dichroic pairs: in 9 exposures (27 pairs) of three QR3 weeks, D1/D4, D2/D5 and D3/D6 have identical `MJD-BEG` and footprints that differ by 69-77" on average and 105" at most (12-17 px); neighbouring detectors D1/D2 are 3.86 deg apart.
- An IRSA cutout (`?center=..&size=Npx`) equals the full-file section `[y0:y0+N, x0:x0+N]` with `x0 = floor(px) - (N/2 - 1)` (px: the SIP-aware 0-based pixel of the centre), header cards unchanged except `NAXISn`, `CRPIXn`, `CRPIXnA` and `CRPIXnW` (shifted by the origin). Reading that section from S3 (IMAGE and VARIANCE rows, the FLAGS rows' compressed bytes, WCS-WAVE from the file end) reproduced 21 cached IRSA cutouts of six targets byte for byte in header and pixels, about 1.1 MB and 7 Range requests per cutout instead of about 4 MB.

## 5. CORS

TESTED with `curl -H "Origin: https://example.com"` and with `fetch()` from a page on `https://www.spaceappschallenge.org`:

| Endpoint | `Access-Control-Allow-Origin` | Browser `fetch()` |
|---|---|---|
| IRSA SIA `https://irsa.ipac.caltech.edu/SIA?...` | none | Failed to fetch |
| IRSA TAP `https://irsa.ipac.caltech.edu/TAP/sync` | none | not tried (no header) |
| IRSA cutout / full file `https://irsa.ipac.caltech.edu/ibe/data/...` | none. `OPTIONS` returns 405. | Failed to fetch |
| S3 `https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/...` | `*` (GET, HEAD, Range header) | 206 OK |
| S3 bucket listing `?list-type=2&prefix=dr1/level2/` | `*` | OK (curl) |
| IRSA HiPS `https://irsa.ipac.caltech.edu/data/hips/...` | `*` | 200 OK |
| CDS Sesame | `*` | 200 OK |

**Blocker:** a static page cannot call SIA or the cutout service directly. Options:

1. A small backend proxy (for example a serverless function) that calls SIA, and optionally the cutouts.
2. A backend only for SIA (small XML). The browser then reads pixels from S3 with Range requests.

## 6. HiPS and existing time-domain viewers

### HiPS

There is a HiPS of the DR1 All-Sky Cube (TESTED properties):

- URL: `https://irsa.ipac.caltech.edu/data/hips/SPHEREx/spherex_allsky_cube`
- `creator_did = ivo://IPAC/P/SPHEREx/DR1/cube`, order 5, 512 px tiles, PNG (also a `fits-cube` tile format at order 5).
- `hips_cube_depth = 102`. The frame index = 17*(band-1) + (channel-1). Frames 50 and 51 are blank.
- Pixel cut 0 to 40 MJy/sr, asinh stretch. CORS `*`.
- It is a co-add from MJD 60789.75 to 61174.49 (Apr 2025 to May 2026). It shows **no time series**, so it is useful only as a static background in Aladin Lite.
- Listed in `https://irsa.ipac.caltech.edu/data/hips/list`. Notebook: [HiPS Cubes](https://caltech-ipac.github.io/irsa-tutorials/spherex-hipscube/).

### Official tools (no blink viewer)

- [SPHEREx Data Explorer](https://irsa.ipac.caltech.edu/applications/spherex): search, view and download, with cutout download.
- [Spectrophotometry Tool](https://irsa.ipac.caltech.edu/applications/spherex/tool-spectrophotometry) and [Mosaic Tool](https://irsa.ipac.caltech.edu/applications/spherex/tool-mosaic).
- [MOST](https://irsa.ipac.caltech.edu/applications/MOST/): Moving Object Search Tool. It lists `spherex` as a dataset. It finds images of a solar-system object from its orbit. It does not handle stars with proper motion.
- We found no official IRSA or NASA blink or time-lapse viewer for SPHEREx.

### Community tools (other Space Apps 2026 teams, not primary sources, UNVERIFIED)

`pythonhack000/spherex-blink`, `ShivenKhurana1/spherex-timelapse`, `ahmedm12j/sphrx-deploy-probe`, `FearmessOp/blackhole-spherex`, `mateibut/SPHEREx`, `mekbuk/spaceapps` on GitHub. These are other teams' entries in this challenge.

## 7. Epochs and exposures per position

Survey design (Explanatory Supplement §1.4):

- SPHEREx covers the full sky in all channels **twice per year**.
- The nominal mission has 4 surveys:
  - Survey 1: first 12.5 months, PA 0
  - Survey 2: first 12.5 months, PA 180
  - Surveys 3 and 4: the second 12.5 months, shifted by half a channel
- A target group is 17 pointings spaced by one LVF channel. The rings and groups overlap.
- The deep fields (NEP, and near the SEP) get many more visits.

TESTED with SIA (radius 0.001 deg; counts are detector images, all 6 detectors):

| Target | Collection | Images | Survey passes (date span, images) |
|---|---|---|---|
| WISE 0855 | dr1 | 258 | 2025-05-05 (30), 2025-10-31..11-14 (110), 2025-12-11..13 (18), 2026-04-21..05-14 (100) |
| WISE 0855 | qr3 | 0 | Next pass expected about Nov 2026 (UNVERIFIED) |
| Barnard's Star | dr1 | 241 | 2025-08-15..10-01 (120), 2026-03-11..05-05 (121) |
| Barnard's Star | qr3 | 123 | 2026-08-16..09-22 |
| eps Ind B | dr1 | 345 | 2025-04-24..06-10 (124), 2025-09-28..11-12 (147), 2026-04-18..05-04 (74) |
| eps Ind B | qr3 | 120 | 2026-09-22..10-02 (D2, D3, D5, D6 only) |
| RW Aur | dr1 | 226 | 2025-09-01..20 (112), 2026-02-20..03-12 (114) |
| RW Aur | qr3 | 109 | 2026-09-02..16 |
| R Dra | dr1 | 413 | 2025-05-16..07-22, 2025-10-17..2026-01-13, 2026-04-22..05-13 |
| R Dra | qr3 | 126 | 2026-05-16..07-16 |
| R Dra | dr1_deep / qr3_deep | 1225 / 729 | R Dra is inside the NEP deep-field coverage |

Rule of thumb:

- Wide survey: **3 or 4 passes so far** (about every 6 months).
- Each pass has about 100 to 150 images, which is about 17 to 25 per detector. The exposures of a pass are spread over 1 to 3 weeks.
- One exposure gives one image on one SWIR detector and one on the paired MWIR detector.
- The number of passes grows by 1 about every 6 months. QR3 adds new images weekly.

## 8. Proper motion against the pixel scale

The motions come from CDS Sesame (Gaia DR3 for Barnard's Star and eps Ind B, Kirkpatrick+2021 for WISE 0855). Pixel = 6.15". PSF FWHM is about 7.4" (1.2 px).

| Target | Total PM ("/yr) | px/yr | Max baseline so far | Shift over baseline | Parallax (px, amplitude) |
|---|---|---|---|---|---|
| Barnard's Star | 10.39 | 1.69 | 2025-08 to 2026-09 (1.1 yr) | about 11.5" = **1.9 px** | 0.09 |
| WISE 0855 | 8.15 | 1.33 | 2025-05 to 2026-05 (1.0 yr) | about 8.2" = **1.3 px** | 0.07 |
| eps Ind B | 4.68 | 0.76 | 2025-04 to 2026-10 (1.45 yr) | about 6.8" = **1.1 px** | 0.04 |
| RW Aur | 0.022 | 0.004 | - | none | - |
| R Dra | 0.022 | 0.004 | - | none (R Dra is a Mira variable, so use it as a brightness-change test) | - |

Conclusions:

- **Motion is visible but small.** Between consecutive passes (6 months) the shift is 0.4 to 0.85 px. Over the full baseline it is 1 to 2 px. A blink of only 2 frames will be hard to see. Use the first and last pass, upsample the cutout and zoom in, or mark the centroid.
- Inside one pass (1 to 3 weeks) the motion is below 0.1 px, so you can stack the frames of one pass to reduce noise.
- **Coordinate epoch trap:** the challenge coordinates of WISE 0855 (`08h55m10.831s -7d14m42.53s` = 133.79513, -7.24515) are from about 2010. In 2025.5 the object is at about **133.7609, -7.2423, which is 123" (20 px) away**. A cutout centered on the given coordinates with a size smaller than about 4 arcmin can miss the object. Propagate the proper motion to each frame date, or use a box of 5 arcmin or more.
- Barnard's Star moved about 3.7' since J2000. Its 2026.0 position is about 269.4463, +4.7682.
- Barnard's Star (J about 5) is probably saturated in the SWIR bands (UNVERIFIED). WISE 0855 is very red (W2 about 14 Vega). It is likely detectable only in D5/D6 near 4.5 um (UNVERIFIED).
- **False movers:** the LVF wavelength changes from frame to frame. The detector orientation, distortion and PSF also change. Compare frames from the same detector, reproject to a common north-up grid, and subtract ZODI.

## 9. Libraries

### Browser

| Library | Use | Status |
|---|---|---|
| [Aladin Lite v3 (CDS)](https://github.com/cds-astro/aladin-lite) | HiPS viewer. FITS image overlay (`A.image` / `displayFITS`). HiPS cube support. | Active: GitHub release v3.8.1, npm `aladin-lite` 3.9.2-beta ([API docs](https://cds-astro.github.io/aladin-lite/)) |
| [fitsjs (astrojs)](https://github.com/astrojs/fitsjs) | Reads FITS images and tables in the browser | npm 0.6.6, last change 2022 (old, but it works for simple images) |
| [jsfitsio](https://www.npmjs.com/package/jsfitsio) | Reads and writes FITS in the browser and Node, with TypedArrays | Newer; npm 3.1.0 (UNVERIFIED quality) |
| [JS9](https://github.com/ericmandel/js9) | Full FITS display (DS9-like) | GitHub repo archived (Dec 2024) |
| Raw parsing | FITS is 2880-byte blocks of 80-char header cards plus big-endian float32. `DataView` with `getFloat32(off, false)` is enough for the IMAGE HDU. | Smallest option for S3 Range reads |

- WCS in the browser: the SIP distortion must be applied for an accurate position. Aladin Lite parses FITS WCS. For a simple tool, use the TAN core and accept up to 13 px of corner error, or evaluate SIP in about 30 lines (UNVERIFIED that Aladin Lite applies SIP).

### Backend (Python)

- `astropy` (`io.fits`, `wcs.WCS` with SIP, `nddata.Cutout2D`, `coordinates.SkyCoord.apply_space_motion` for proper motion).
- `astroquery.ipac.irsa` (SIA, TAP), `pyvo` (lower-level VO).
- `reproject` (astropy-affiliated) puts frames on a common north-up grid (UNVERIFIED version).
- IRSA tutorials: <https://caltech-ipac.github.io/irsa-tutorials/spherex/>.

## Blockers and risks

1. **No CORS on IRSA SIA, TAP and cutouts.** You need a backend proxy, at least for SIA. S3 and HiPS are CORS-open.
2. **Each cutout is about 4 MB** (EPSF table). There are many exposures per position, so filter by detector and pass. Alternatively, read only the IMAGE rows from S3 with Range requests.
3. **Rate limits:** IRSA returns intermittent 503 (`retry-after: 5`) and 502 errors. Retry, and keep concurrency low.
4. **TAP spatial queries are slow** (more than 2 min). Use SIA.
5. **Small motion:** 1 to 2 px total, with a PSF of about 1.2 px. Use the longest baseline, zoom in, and mark the predicted proper-motion track.
6. **Old input coordinates:** the given WISE 0855 position is 2' off for 2025-2026.
