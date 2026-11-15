"""Download and cache everything WANDERERS needs for one target.

    python pipeline/fetch.py barnard            # one target
    python pipeline/fetch.py all                # every target in targets.py

Sources (all public, no login):
  * Gaia DR3 (ESA archive TAP)           -> target position, proper motion, field stars
  * SPHEREx spectral images (IRSA)        -> cutouts around the target, every wavelength, from every release in
                                            app/data/spherex_release.json (pipeline/spherex_releases.py)
  * AllWISE atlas images (IRSA)           -> W1 (3.4 um) and W2 (4.6 um) cutouts, epoch ~2010

IRSA is busy during the hackathon and sometimes answers 502/503, so every request retries
with backoff and every file is cached under data/cache/<target>/. Re-running only fetches
what is missing.

When IRSA's SIA or cutout service still fails after the retries, SPHEREx falls back to NASA IRSA's public S3 bucket
(pipeline/spherex_s3.py), with a log line saying so: images are found in the bucket's footprint index
(data/cache/spherex_s3_index/<release>.jsonl; build it with `python pipeline/spherex_s3.py index qr3`), and cutouts
are read from the files on S3 with HTTP Range requests, into the same files and format as IRSA's cutouts. The S3
search answer is saved as data/cache/<target>/<release>_s3.json (pipeline/spherex_releases.py reads it as "searched").
"""
import io, json, sys, time, warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pyvo
import requests
import astropy.units as u
from astropy.coordinates import SkyCoord, Distance
from astropy.io import fits
from astropy.io.votable import parse_single_table
from astropy.time import Time

sys.path.insert(0, str(Path(__file__).parent))
from targets import TARGETS
from fov import DEFAULT_FOV, fov_of, clamp_fov, position_id
from spherex_releases import load_release_names, sia_cache_name, s3_answer_name
import spherex_s3

warnings.simplefilter("ignore")
ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
GAIA_TAP = "https://gea.esac.esa.int/tap-server/tap"
SIA = "https://irsa.ipac.caltech.edu/SIA"
FIELD_ARCSEC = DEFAULT_FOV  # default side of the square field we analyse; a target can set its own (see fov.py)
SPX_PIX = 6.15              # SPHEREx pixel scale, arcsec
KEEP_HDUS = ("IMAGE", "FLAGS", "VARIANCE", "WCS-WAVE")
MAX_IMAGES = 150            # SPHEREx cutouts per target (see fetch())
# SPHEREx releases to search, oldest first. They come from app/data/spherex_release.json, which
# pipeline/spherex_releases.py keeps current from IRSA's collection list (a weekly GitHub Actions job runs it, see
# .github/workflows/spherex-sync.yml). FALLBACK_RELEASES is used when that file is missing or broken. Duplicate
# images of the same exposure are kept once: the first release listed wins (first_release_wins).
FALLBACK_RELEASES = ["spherex_dr1", "spherex_qr3"]
RELEASES = load_release_names(fallback=FALLBACK_RELEASES)

session = requests.Session()
session.headers["User-Agent"] = "wanderers-spaceapps/0.1"
# Set when an IRSA SPHEREx service failed after all retries in this run: later searches and cutouts go straight to the
# S3 bucket instead of waiting minutes for IRSA again. An SIA answer already cached is still used.
IRSA_DOWN = {"sia": False, "cutout": False}
S3_WORKERS = 8                       # S3 Range reads at a time (IRSA cutouts stay at 3)
_s3_reader = None


def s3_reader():
    global _s3_reader
    if _s3_reader is None:
        _s3_reader = spherex_s3.S3Reader(pool=32)
    return _s3_reader


def get(url, tries=6, timeout=120):
    """GET with retry on IRSA's transient 5xx answers and timeouts."""
    for k in range(tries):
        try:
            r = session.get(url, timeout=timeout)
            if r.status_code == 200 and r.content:
                return r.content
            err = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            err = type(e).__name__
        wait = min(60, 4 * 2 ** k)
        print(f"    retry {k + 1}/{tries} after {err}; waiting {wait}s", flush=True)
        time.sleep(wait)
    raise RuntimeError(f"gave up on {url[:120]}")


def num(x, default=0.0):
    """Gaia values can be masked (no measurement); turn them into plain floats."""
    try:
        if x is None or np.ma.is_masked(x):
            return default
        v = float(x)
        return default if not np.isfinite(v) else v
    except (TypeError, ValueError):
        return default


def gaia(query):
    return pyvo.dal.TAPService(GAIA_TAP).run_sync(query).to_table()


def resolve(tid, t):
    """Return the target's reference astrometry and the Gaia field stars around it."""
    if "gaia_source_id" in t:
        row = gaia(f"SELECT source_id, ra, dec, pmra, pmdec, parallax, phot_g_mean_mag "
                   f"FROM gaiadr3.gaia_source WHERE source_id={t['gaia_source_id']}")[0]
        ref = dict(source="Gaia DR3", epoch=2016.0)
    elif "position" in t:
        # A user-chosen position. Typed coordinates can come from any epoch (J2000, a discovery
        # paper, ...), and a fast-moving star can be a minute of arc away from them today. So follow
        # every Gaia star within 2' along its own motion from 1990 to 2026, keep the ones whose
        # path passes within 5" of the typed spot, and take the brightest of those.
        P = t["position"]
        rows = gaia(f"SELECT source_id, ra, dec, pmra, pmdec, parallax, phot_g_mean_mag FROM gaiadr3.gaia_source "
                    f"WHERE 1=CONTAINS(POINT('ICRS',ra,dec), CIRCLE('ICRS',{P['ra']},{P['dec']},{120/3600}))")
        typed = SkyCoord(P["ra"] * u.deg, P["dec"] * u.deg)
        years = Time(np.arange(1990.0, 2026.51, 0.5), format="jyear")
        best, best_d, best_g = None, None, 99.0
        for r in rows:
            c = SkyCoord(num(r["ra"]) * u.deg, num(r["dec"]) * u.deg, pm_ra_cosdec=num(r["pmra"]) * u.mas / u.yr,
                         pm_dec=num(r["pmdec"]) * u.mas / u.yr, obstime=Time(2016.0, format="jyear"))
            dd = float(np.min(c.apply_space_motion(new_obstime=years).separation(typed).arcsec))
            g = num(r["phot_g_mean_mag"], 99.0)
            if dd < 5.0 and g < best_g:
                best, best_d, best_g = r, dd, g
        if best is not None:
            row = best
            ref = dict(source="Gaia DR3", epoch=2016.0, match_arcsec=round(best_d, 2))
        else:
            row = dict(source_id=None, ra=P["ra"], dec=P["dec"], pmra=0.0, pmdec=0.0, parallax=None, phot_g_mean_mag=None)
            ref = dict(source="position entered by user (no Gaia source within 5\")", epoch=2016.0, catalogued=False)
    elif "seed" in t:
        s = t["seed"]
        c = SkyCoord(s["ra"] * u.deg, s["dec"] * u.deg, pm_ra_cosdec=s["pmra"] * u.mas / u.yr,
                     pm_dec=s["pmdec"] * u.mas / u.yr, obstime=Time(s["epoch"], format="jyear"))
        c16 = c.apply_space_motion(new_obstime=Time(2016.0, format="jyear"))
        rows = gaia(f"SELECT source_id, ra, dec, pmra, pmdec, parallax, phot_g_mean_mag FROM gaiadr3.gaia_source "
                    f"WHERE 1=CONTAINS(POINT('ICRS',ra,dec), CIRCLE('ICRS',{c16.ra.deg},{c16.dec.deg},{20/3600}))")
        if len(rows) == 0:
            raise RuntimeError(f"{tid}: no Gaia source near the expected position")
        # Prefer a source whose motion matches the seed; otherwise the brightest.
        if abs(s["pmra"]) + abs(s["pmdec"]) > 100:
            d = [np.hypot(num(r["pmra"], 1e9) - s["pmra"], num(r["pmdec"], 1e9) - s["pmdec"]) for r in rows]
            rows = rows[np.argsort(d)]
        else:
            rows.sort("phot_g_mean_mag")
        row = rows[0]
        ref = dict(source="Gaia DR3", epoch=2016.0)
    else:
        L = t["literature"]
        row = dict(source_id=None, ra=L["ra"], dec=L["dec"], pmra=L["pmra"], pmdec=L["pmdec"],
                   parallax=L["parallax"], phot_g_mean_mag=None)
        ref = dict(source=L["ref"], epoch=L["epoch"])
    for k in ("source_id", "ra", "dec", "pmra", "pmdec", "parallax", "phot_g_mean_mag"):
        v = row[k]
        ref[k] = None if v is None or np.ma.is_masked(v) else (int(v) if k == "source_id" else num(v))

    # Field stars: everything Gaia sees within the analysis field, for the "ghost" overlay.
    centre = predict(ref, 2025.7)
    rad = fov_of(t) * 0.75 / 3600
    field = gaia(f"SELECT source_id, ra, dec, pmra, pmdec, parallax, phot_g_mean_mag FROM gaiadr3.gaia_source "
                 f"WHERE 1=CONTAINS(POINT('ICRS',ra,dec), CIRCLE('ICRS',{centre.ra.deg},{centre.dec.deg},{rad})) "
                 f"AND phot_g_mean_mag < 19")
    stars = [{"source_id": int(r["source_id"]), "ra": float(r["ra"]), "dec": float(r["dec"]),
              "pmra": num(r["pmra"]), "pmdec": num(r["pmdec"]),
              "g": num(r["phot_g_mean_mag"], 99.0)} for r in field]
    return ref, stars


def predict(ref, year):
    """Where the target is at a given decimal year (proper motion + parallax ignored for display)."""
    c = SkyCoord(ref["ra"] * u.deg, ref["dec"] * u.deg,
                 pm_ra_cosdec=(ref["pmra"] or 0) * u.mas / u.yr, pm_dec=(ref["pmdec"] or 0) * u.mas / u.yr,
                 obstime=Time(ref["epoch"], format="jyear"))
    return c.apply_space_motion(new_obstime=Time(year, format="jyear"))


def sia(collection, c, out):
    if not out.exists():
        url = f"{SIA}?COLLECTION={collection}&POS=circle+{c.ra.deg}+{c.dec.deg}+0.002&RESPONSEFORMAT=VOTABLE"
        out.write_bytes(get(url))
    return parse_single_table(str(out)).to_table(use_names_over_ids=True)


SIA_COLUMNS = ("access_url", "t_min", "t_max", "energy_bandpassname", "obs_id", "dataproduct_subtype",
               "dataproduct_type", "calib_level", "em_min", "em_max", "obs_collection", "cloud_access", "s_region")


def s3_search(rel, ref, c25, d, reader=None, index_root=None, now=None):
    """IRSA SIA's answer for one release, from the S3 bucket's footprint index instead: the images whose footprint
    holds the target at that image's own time (predict() on the reference). Saves the answer as
    data/cache/<target>/<release>_s3.json and returns a table with the SIA columns fetch() uses."""
    from datetime import datetime, timezone
    short = rel.removeprefix("spherex_")
    if not spherex_s3.index_path(short, index_root).exists():
        raise RuntimeError(f"no S3 image index for {short} yet (python pipeline/spherex_s3.py index {short})")
    index = spherex_s3.load_index(short, index_root, near=(c25.ra.deg, c25.dec.deg, 3.0))
    reader = reader or s3_reader()

    def at(mjd):
        c = predict(ref, Time(mjd, format="mjd").jyear)
        return c.ra.deg, c.dec.deg

    recs = spherex_s3.search(index, at, c25.ra.deg, c25.dec.deg, reader=reader, release=short, root=index_root)
    weeks = spherex_s3.week_folders(reader, short)
    answer = spherex_s3.search_answer(
        short, recs, weeks, spherex_s3.index_coverage(short, index_root),
        position={"ra_2025_9": round(c25.ra.deg, 6), "dec_2025_9": round(c25.dec.deg, 6),
                  "rule": "target position at each image's MJD-BEG (fetch.py predict() on data/cache/<target>/gaia.json)"},
        searched=now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    if not answer["index_complete"]:
        print(f"   {rel}: the S3 index misses {len(answer['missing_weeks'])} of {len(weeks)} week folders; "
              f"this search is partial (run: python pipeline/spherex_s3.py index {short})", flush=True)
    out = d / s3_answer_name(rel)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(answer, indent=1) + "\n")
    tmp.rename(out)
    return sia_table(spherex_s3.sia_like_rows(recs, short))


# Column types as astropy reads IRSA's SIA VOTable, so the two kinds of table stack (vstack) together.
SIA_DTYPES = (object, "f8", "f8", object, object, object, object, "i2", "f8", "f8", object, object, object)


def sia_table(rows):
    """An astropy Table with the SIA_COLUMNS of SIA-like row dicts (spherex_s3.sia_like_rows)."""
    from astropy.table import Table
    t = Table(names=SIA_COLUMNS, dtype=SIA_DTYPES)
    for r in rows:
        t.add_row([r[c] for c in SIA_COLUMNS])
    return t


def say(msg):
    print(msg, flush=True)


def find_images(rel, ref, c25, d, log=say):
    """One release's images that cover the target: IRSA SIA (or its cached answer); when IRSA fails, the S3 index."""
    out = d / sia_cache_name(rel)
    if out.exists() or not IRSA_DOWN["sia"]:
        try:
            return sia(rel, c25, out), "IRSA SIA"
        except Exception as e:  # noqa: BLE001 - any IRSA failure: try the bucket
            IRSA_DOWN["sia"] = True
            log(f"   {rel}: IRSA SIA failed ({e}); falling back to the S3 bucket's image index")
    else:
        log(f"   {rel}: IRSA SIA failed earlier in this run; using the S3 bucket's image index")
    return s3_search(rel, ref, c25, d), "S3 index"


def s3_key(row):
    """The S3 key of an SIA row's image (cloud_access), or None."""
    try:
        return json.loads(str(row["cloud_access"]))["aws"]["key"]
    except (ValueError, KeyError, TypeError):
        return None


def get_cutout(row, c, size_px, from_s3=False, log=say):
    """FITS bytes of one SPHEREx cutout (the HDUs in KEEP_HDUS) centred on c: IRSA's cutout service, or the S3 bucket
    when IRSA fails (or failed earlier in this run, or the row came from the S3 index). None when the cutout box
    misses the image."""
    if not from_s3 and not IRSA_DOWN["cutout"]:
        try:   # SIA (same IRSA host) already failed in this run: two tries, not six minutes of them
            return trim(get(f"{row['access_url']}?center={c.ra.deg},{c.dec.deg}&size={size_px}px",
                            tries=2 if IRSA_DOWN["sia"] else 6))
        except Exception as e:  # noqa: BLE001
            if s3_key(row) is None:
                raise
            if not IRSA_DOWN["cutout"]:
                log(f"   IRSA cutouts failed ({e}); reading the cutouts from the S3 bucket instead")
            IRSA_DOWN["cutout"] = True
    key = s3_key(row)
    if key is None:
        raise RuntimeError(f"no S3 copy listed for {str(row['access_url'])[:100]}")
    return spherex_s3.cutout(s3_reader(), key, c.ra.deg, c.dec.deg, size_px, keep=KEEP_HDUS)


def select_images(spx, cached, max_images=None):
    """Indexes of the SPHEREx rows to use (spx sorted by detector, then time). Every cutout carries ~4 MB of PSF
    tables, so the count is capped: an equal share per detector (each covers a different wavelength range), spread
    evenly in time, so all 6 detectors and every survey pass are represented and spectral coverage stays complete.

    Images already on disk (stems in `cached`) are free, so they are always kept, and an evenly spread pick that is
    not on disk is replaced by an unused cached image of the same detector taken within 20 days of it (the same
    survey pass; backend/spherex.py groups passes the same way). A pick with no such stand-in is downloaded. So a
    target fetched before a new release keeps its cutouts, and the new release's passes still get their share."""
    max_images = MAX_IMAGES if max_images is None else max_images
    n_all = len(spx)
    if n_all <= max_images:
        return list(range(n_all))
    stem = lambda r: Path(str(r["access_url"]).split("?")[0]).stem
    quota = max_images // 6
    pick = set()
    for det in sorted(set(spx["energy_bandpassname"])):
        idx = [i for i, r in enumerate(spx) if r["energy_bandpassname"] == det]
        on_disk = [i for i in idx if stem(spx[i]) in cached]
        chosen, used = set(), set()
        for j in np.linspace(0, len(idx) - 1, min(quota, len(idx))).round().astype(int):
            i = idx[j]
            if i in chosen:
                continue
            if i not in on_disk:
                t = float(spx[i]["t_min"])
                near = [k for k in on_disk if k not in used and abs(float(spx[k]["t_min"]) - t) <= 20]
                if near:
                    i = min(near, key=lambda k: abs(float(spx[k]["t_min"]) - t))
            chosen.add(i)
            used.add(i)
        pick |= chosen
    # Anything already on disk is free to use, so keep it too.
    pick |= {i for i, r in enumerate(spx) if stem(r) in cached}
    return sorted(pick)


def first_release_wins(rows, seen):
    """Indexes of one release's rows whose exposure (obs_id, detector) no earlier release had, then add them to
    `seen`. Called once per release in RELEASES order, so an exposure that two releases both list is kept from the
    first one. Rows within one release are not compared with each other (as before this was a function)."""
    key = lambda r: (str(r["obs_id"]), str(r["energy_bandpassname"]))
    keep = [i for i, r in enumerate(rows) if key(r) not in seen]
    seen.update(key(rows[i]) for i in keep)
    return keep


def trim(content):
    """Keep only the HDUs we use, so 240 cutouts stay small on disk."""
    h = fits.open(io.BytesIO(content))
    keep = fits.HDUList([fits.PrimaryHDU(header=h[0].header)] + [h[n] for n in KEEP_HDUS if n in h])
    buf = io.BytesIO(); keep.writeto(buf); return buf.getvalue()


def ref_summary(ref, n_stars):
    """Log line for the reference. A Gaia DR3 two-parameter source has no proper motion (None): shown as 0."""
    pm = f"({ref['pmra'] or 0:.0f},{ref['pmdec'] or 0:.0f})"
    return f"   reference: {ref['source']} ra={ref['ra']:.5f} dec={ref['dec']:.5f} pm={pm} mas/yr; {n_stars} Gaia field stars"


def fetch(tid):
    t = TARGETS[tid]
    d = CACHE / tid; d.mkdir(parents=True, exist_ok=True)
    print(f"== {t['name']} ({tid})", flush=True)

    meta_f = d / "gaia.json"
    if meta_f.exists():
        meta = json.loads(meta_f.read_text())
    else:
        ref, stars = resolve(tid, t)
        meta = {"ref": ref, "field_stars": stars}
        meta_f.write_text(json.dumps(meta, indent=1))
    ref = meta["ref"]
    print(ref_summary(ref, len(meta["field_stars"])), flush=True)

    # --- SPHEREx (every release in RELEASES): one cutout per spectral image covering the target ---
    c25 = predict(ref, 2025.9)
    from astropy.table import vstack
    tabs, seen, s3_rows = [], set(), set()
    for rel in RELEASES:
        try:
            tb, how = find_images(rel, ref, c25, d)
        except Exception as e:
            print(f"   {rel}: not available ({e})"); continue
        if len(tb) == 0:
            print(f"   {rel}: 0 images ({how})")
            continue
        tb = tb[tb["dataproduct_subtype"] == "science"]
        keep = first_release_wins(tb, seen)
        if keep:
            tabs.append(tb[keep]); print(f"   {rel}: {len(keep)} images ({how})")
            if how == "S3 index":
                s3_rows |= {str(tb[i]["access_url"]) for i in keep}
    spx = vstack(tabs, metadata_conflicts="silent")
    spx.sort(["energy_bandpassname", "t_min"])
    n_all = len(spx)
    cached = {p.stem for p in (d / "spherex").glob("*.fits")}
    spx = spx[select_images(spx, cached)]
    print(f"   SPHEREx ({', '.join(RELEASES)}): {n_all} images, using {len(spx)}", flush=True)
    fov = fov_of(t)
    size_px = int(fov / SPX_PIX) + 4

    def one(row):
        f = d / "spherex" / (Path(str(row["access_url"]).split("?")[0]).stem + ".fits")
        if f.exists():
            return "cached"
        yr = Time(row["t_min"], format="mjd").jyear
        c = predict(ref, yr)
        content = get_cutout(row, c, size_px, from_s3=str(row["access_url"]) in s3_rows)
        if content is None:
            print(f"   {f.stem}: the cutout box misses the image; skipped", flush=True)
            return "missed"
        f.parent.mkdir(exist_ok=True)
        tmp = f.with_suffix(".part")
        tmp.write_bytes(content)
        tmp.rename(f)            # atomic: a killed run never leaves a half-written .fits
        return "new"

    # gentle on IRSA during the hackathon (3 at a time); the S3 bucket takes more
    with ThreadPoolExecutor(S3_WORKERS if (s3_rows or IRSA_DOWN["cutout"]) else 3) as ex:
        done = 0
        for status in ex.map(one, spx):
            done += 1
            if done % 6 == 0 or done == len(spx):
                print(f"   SPHEREx cutouts {done}/{len(spx)}", flush=True)

    # --- AllWISE atlas: W1 and W2, epoch ~2010.5 ---------------------------------------------
    c10 = predict(ref, 2010.5)
    cmid = predict(ref, 2018.4)     # centre the WISE cutout mid-way so a fast mover's 2026 spot is covered
    aw = sia("wise_allwise", c10, d / "allwise_sia.xml")
    for band in ("W1", "W2"):
        f = d / f"allwise_{band}.fits"
        if f.exists():
            continue
        rows = aw[(aw["energy_bandpassname"] == band) & (aw["dataproduct_subtype"] == "science")]
        if len(rows) == 0:
            print(f"   AllWISE {band}: none"); continue
        f.write_bytes(get(f"{rows[0]['access_url']}?center={cmid.ra.deg},{cmid.dec.deg}&size={int(fov * 1.6)}arcsec"))
    print(f"   AllWISE W1/W2 cached", flush=True)
    # NEOWISE 2014-2024: one stacked image per sky visit, from NASA IRSA's copy on AWS (pipeline/neowise.py)
    try:
        import neowise
        neowise.run(tid)
    except Exception as e:                      # optional: the time-lapse still works with WISE 2010 + SPHEREx
        print(f"   NEOWISE skipped: {e}", flush=True)


def add_position(ra, dec, name=None, fov=None):
    """Register a user-chosen sky position as a target and return its id.

    fov is the side of the square field in arcseconds (see fov.py). The default field keeps the
    original id; other sizes get a suffix, so each size is cached separately.
    """
    fov = clamp_fov(fov)
    tid = position_id(ra, dec, fov)
    t = {"name": name or f"RA {ra:.4f}, Dec {dec:+.4f}", "kind": "A sky position entered by a user",
         "position": {"ra": ra, "dec": dec}, "story": "explore", "fov_arcsec": fov}
    d = CACHE / tid; d.mkdir(parents=True, exist_ok=True)
    (d / "target_def.json").write_text(json.dumps(t, indent=1))
    TARGETS[tid] = t
    return tid


if __name__ == "__main__":
    if "--max" in sys.argv:                 # quick look: fewer SPHEREx cutouts per target
        MAX_IMAGES = max(12, int(sys.argv[sys.argv.index("--max") + 1]))
    if "--ra" in sys.argv:
        a = sys.argv
        ra, dec = float(a[a.index("--ra") + 1]), float(a[a.index("--dec") + 1])
        name = a[a.index("--name") + 1] if "--name" in a else None
        fov = float(a[a.index("--fov") + 1]) if "--fov" in a else None      # arcseconds per side
        tid = add_position(ra, dec, name, fov)
        print(f"target id: {tid}  (next: python pipeline/analyze.py {tid} && python pipeline/evidence.py)")
        fetch(tid)
        sys.exit()
    ids = list(TARGETS) if sys.argv[1:] in ([], ["all"]) else sys.argv[1:]
    for tid in ids:
        try:
            fetch(tid)
        except Exception as e:
            print(f"!! {tid} failed: {e}", flush=True)
