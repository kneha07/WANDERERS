"""Download and cache everything WANDERERS needs for one target.

    python pipeline/fetch.py barnard            # one target
    python pipeline/fetch.py all                # every target in targets.py

Sources (all public, no login):
  * Gaia DR3 (ESA archive TAP)           -> target position, proper motion, field stars
  * SPHEREx DR1 spectral images (IRSA)    -> cutouts around the target, every wavelength
  * AllWISE atlas images (IRSA)           -> W1 (3.4 um) and W2 (4.6 um) cutouts, epoch ~2010

IRSA is busy during the hackathon and sometimes answers 502/503, so every request retries
with backoff and every file is cached under data/cache/<target>/. Re-running only fetches
what is missing.
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

warnings.simplefilter("ignore")
ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
GAIA_TAP = "https://gea.esac.esa.int/tap-server/tap"
SIA = "https://irsa.ipac.caltech.edu/SIA"
FIELD_ARCSEC = 300          # side of the square field we analyse
SPX_PIX = 6.15              # SPHEREx pixel scale, arcsec
KEEP_HDUS = ("IMAGE", "FLAGS", "VARIANCE", "WCS-WAVE")
MAX_IMAGES = 150            # SPHEREx cutouts per target (see fetch())

session = requests.Session()
session.headers["User-Agent"] = "wanderers-spaceapps/0.1"


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
        # A user-chosen position: use the brightest Gaia source within 5 arcsec if there is one.
        P = t["position"]
        rows = gaia(f"SELECT source_id, ra, dec, pmra, pmdec, parallax, phot_g_mean_mag FROM gaiadr3.gaia_source "
                    f"WHERE 1=CONTAINS(POINT('ICRS',ra,dec), CIRCLE('ICRS',{P['ra']},{P['dec']},{5/3600}))")
        if len(rows):
            rows.sort("phot_g_mean_mag"); row = rows[0]
            ref = dict(source="Gaia DR3", epoch=2016.0)
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
    rad = FIELD_ARCSEC * 0.75 / 3600
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


def trim(content):
    """Keep only the HDUs we use, so 240 cutouts stay small on disk."""
    h = fits.open(io.BytesIO(content))
    keep = fits.HDUList([fits.PrimaryHDU(header=h[0].header)] + [h[n] for n in KEEP_HDUS if n in h])
    buf = io.BytesIO(); keep.writeto(buf); return buf.getvalue()


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
    print(f"   reference: {ref['source']} ra={ref['ra']:.5f} dec={ref['dec']:.5f} "
          f"pm=({ref['pmra']:.0f},{ref['pmdec']:.0f}) mas/yr; {len(meta['field_stars'])} Gaia field stars", flush=True)

    # --- SPHEREx DR1: one cutout per spectral image covering the target -------------------
    c25 = predict(ref, 2025.9)
    spx = sia("spherex_dr1", c25, d / "spherex_sia.xml")
    spx = spx[spx["dataproduct_subtype"] == "science"]
    spx.sort(["energy_bandpassname", "t_min"])
    n_all = len(spx)
    # Every cutout carries ~4 MB of PSF tables, so cap the count. Picking evenly through the list
    # sorted by (detector, time) keeps all 6 detectors and both sky surveys represented, and each
    # image samples a different wavelength at the target, so spectral coverage stays complete.
    if n_all > MAX_IMAGES:
        # Equal share per detector (each covers a different wavelength range), spread in time.
        cached = {p.stem for p in (d / "spherex").glob("*.fits")}
        stem = lambda r: Path(str(r["access_url"]).split("?")[0]).stem
        quota = MAX_IMAGES // 6
        pick = set()
        for det in sorted(set(spx["energy_bandpassname"])):
            idx = [i for i, r in enumerate(spx) if r["energy_bandpassname"] == det]
            have = [i for i in idx if stem(spx[i]) in cached][:quota]
            chosen = set(have)
            for j in np.linspace(0, len(idx) - 1, min(quota, len(idx))).round().astype(int):
                if len(chosen) >= quota:
                    break
                chosen.add(idx[j])
            pick |= chosen
        # Anything already on disk is free to use, so keep it too.
        pick |= {i for i, r in enumerate(spx) if stem(r) in cached}
        spx = spx[sorted(pick)]
    print(f"   SPHEREx DR1: {n_all} images, using {len(spx)}", flush=True)
    size_px = int(FIELD_ARCSEC / SPX_PIX) + 4

    def one(row):
        f = d / "spherex" / (Path(str(row["access_url"]).split("?")[0]).stem + ".fits")
        if f.exists():
            return "cached"
        yr = Time(row["t_min"], format="mjd").jyear
        c = predict(ref, yr)
        f.parent.mkdir(exist_ok=True)
        tmp = f.with_suffix(".part")
        tmp.write_bytes(trim(get(f"{row['access_url']}?center={c.ra.deg},{c.dec.deg}&size={size_px}px")))
        tmp.rename(f)            # atomic: a killed run never leaves a half-written .fits
        return "new"

    with ThreadPoolExecutor(3) as ex:   # gentle on IRSA during the hackathon
        done = 0
        for status in ex.map(one, spx):
            done += 1
            if done % 40 == 0 or done == len(spx):
                print(f"   SPHEREx cutouts {done}/{len(spx)}", flush=True)

    # --- AllWISE atlas: W1 and W2, epoch ~2010.5 ---------------------------------------------
    c10 = predict(ref, 2010.5)
    aw = sia("wise_allwise", c10, d / "allwise_sia.xml")
    for band in ("W1", "W2"):
        f = d / f"allwise_{band}.fits"
        if f.exists():
            continue
        rows = aw[(aw["energy_bandpassname"] == band) & (aw["dataproduct_subtype"] == "science")]
        if len(rows) == 0:
            print(f"   AllWISE {band}: none"); continue
        f.write_bytes(get(f"{rows[0]['access_url']}?center={c10.ra.deg},{c10.dec.deg}&size={FIELD_ARCSEC}arcsec"))
    print(f"   AllWISE W1/W2 cached", flush=True)


def add_position(ra, dec, name=None):
    """Register a user-chosen sky position as a target and return its id."""
    tid = f"pos_{ra:.4f}_{dec:+.4f}".replace(".", "p").replace("+", "n").replace("-", "s")
    t = {"name": name or f"RA {ra:.4f}, Dec {dec:+.4f}", "kind": "A sky position entered by a user",
         "position": {"ra": ra, "dec": dec}, "story": "explore"}
    d = CACHE / tid; d.mkdir(parents=True, exist_ok=True)
    (d / "target_def.json").write_text(json.dumps(t, indent=1))
    TARGETS[tid] = t
    return tid


if __name__ == "__main__":
    if "--ra" in sys.argv:
        a = sys.argv
        ra, dec = float(a[a.index("--ra") + 1]), float(a[a.index("--dec") + 1])
        name = a[a.index("--name") + 1] if "--name" in a else None
        tid = add_position(ra, dec, name)
        print(f"target id: {tid}  (next: python pipeline/analyze.py {tid} && python pipeline/evidence.py)")
        fetch(tid)
        sys.exit()
    ids = list(TARGETS) if sys.argv[1:] in ([], ["all"]) else sys.argv[1:]
    for tid in ids:
        try:
            fetch(tid)
        except Exception as e:
            print(f"!! {tid} failed: {e}", flush=True)
