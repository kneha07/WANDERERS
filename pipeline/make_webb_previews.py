"""Real Webb images for the "Through Webb" view, where the live ESASky Webb maps have no pixels.

    python pipeline/make_webb_previews.py          (after make_webb.py and make_stars.py)

1. Marks each Webb pointing in app/data/webb.json whose outline is covered by ESA ESASky's JWST HiPS maps
   (their Moc.fits), so the apps know when the live, zoomable map will show pixels (field "h": 1).
2. For every WANDERERS target and every catalogue star inside a Webb frame, downloads that frame's MAST preview
   (the i2d JPEG, which carries its own WCS from fitscut), shrinks it to at most 1400 px and writes
   app/data/webb/<obs_id>.jpg plus its WCS into app/data/webb_previews.json.
"""
import io, json, ssl, sys, urllib.request
from pathlib import Path

import certifi
import numpy as np
from astropy.io import fits
from astropy_healpix import HEALPix
import astropy.units as u
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app" / "data"
CTX = ssl.create_default_context(cafile=certifi.where())
ESA = "https://skies.esac.esa.int/JWST/"
MOCS = {"NIRCam": "NIRCam_Imaging", "MIRI": "MIRI_Imaging", "NIRISS": "NIRISS_Imaging"}
MAX_PX = 1400
MAX_BYTES = 120e6          # skip giant survey mosaics
Image.MAX_IMAGE_PIXELS = None


def get(url, timeout=300):        # url may be a Request
    with urllib.request.urlopen(url, timeout=timeout, context=CTX) as r:
        return r.read()


def load_moc(name):
    """MOC (NUNIQ cells) -> {order: set(nested pixel ids)}."""
    with fits.open(io.BytesIO(get(ESA + name + "/Moc.fits"))) as h:
        uniq = np.asarray(h[1].data.field(0), dtype=np.int64)
    order = (np.floor(np.log2(uniq / 4) / 2)).astype(int)
    ipix = uniq - 4 * 4 ** order.astype(np.int64)
    cells = {}
    for o, p in zip(order, ipix):
        cells.setdefault(int(o), set()).add(int(p))
    return cells


def covered(cells, ra, dec):
    for o, s in cells.items():
        if int(HEALPix(nside=2 ** o, order="nested").lonlat_to_healpix(ra * u.deg, dec * u.deg)) in s:
            return True
    return False


def inside(p, ra, dec):
    """Same test as app/telescope.js."""
    c = np.cos(np.radians(p[1]))
    tp = lambda a, d: (((a - p[0] + 540) % 360 - 180) * c, d - p[1])
    x, y = tp(ra, dec)
    h = p[9]
    n = len(h) // 2
    inn, j = False, n - 1
    for i in range(n):
        xi, yi = tp(h[2 * i], h[2 * i + 1]); xj, yj = tp(h[2 * j], h[2 * j + 1])
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inn = not inn
        j = i
    return inn


def blacken_border(path):
    """Blank (no-data) areas come out pure white in MAST's JPEGs; make the ones touching the edge black."""
    from scipy import ndimage
    a = np.asarray(Image.open(path).convert("L")).copy()
    lab, _ = ndimage.label(a >= 250)
    edge = np.unique(np.r_[lab[0], lab[-1], lab[:, 0], lab[:, -1]])
    edge = edge[edge > 0]
    if edge.size:
        a[np.isin(lab, edge)] = 0
        Image.fromarray(a).save(path, quality=84, optimize=True)


def sci_header(obs):
    """The i2d SCI header, read with a byte-range request (the JPEG's own WCS from fitscut drops the rotation)."""
    url = f"https://mast.stsci.edu/api/v0.1/Download/file?uri=mast:JWST/product/{obs}_i2d.fits"
    raw = get(urllib.request.Request(url, headers={"Range": "bytes=0-600000"}))
    pos = 0
    for _ in range(4):
        end = raw.find(b"END" + b" " * 77, pos)
        if end < 0:
            break
        hdr = fits.Header.fromstring(raw[pos:end + 80].decode("ascii", "ignore"))
        if hdr.get("EXTNAME") == "SCI":
            return hdr
        size = 0
        if hdr.get("NAXIS", 0):
            size = abs(hdr["BITPIX"]) // 8
            for i in range(hdr["NAXIS"]):
                size *= hdr[f"NAXIS{i + 1}"]
        pos += ((end + 80 - pos) + 2879) // 2880 * 2880 + (size + 2879) // 2880 * 2880
    return None


def add_rotation(wcs, obs):
    """Put the SCI header's PC matrix (and its exact reference) on a preview WCS scaled to the preview's size."""
    h = sci_header(obs)
    if h is None or "PC1_1" not in h:
        return False
    f = wcs["NAXIS1"] / h["NAXIS1"]
    wcs.update({"CRPIX1": (h["CRPIX1"] - 0.5) * f + 0.5, "CRPIX2": (h["CRPIX2"] - 0.5) * f + 0.5,
                "CRVAL1": h["CRVAL1"], "CRVAL2": h["CRVAL2"], "CDELT1": h["CDELT1"] / f, "CDELT2": h["CDELT2"] / f,
                "PC1_1": h["PC1_1"], "PC1_2": h.get("PC1_2", 0.0), "PC2_1": h.get("PC2_1", 0.0), "PC2_2": h["PC2_2"]})
    wcs.pop("CROTA2", None)
    return True


def score(p):
    """Prefer plain wide imaging (not coronagraph masks or tiny subarrays), NIRCam first, recent last."""
    obs = p[8]
    return (("mask" in obs) * 2 + ("sub" in obs) + {"NIRCam": 0, "MIRI": 1, "NIRISS": 1}.get(p[3], 3), -p[2])


def main():
    W = json.loads((APP / "webb.json").read_text())
    P = W["p"]

    # 1. live-map coverage
    for inst, name in MOCS.items():
        cells = load_moc(name)
        n = 0
        for p in P:
            if p[3] == inst and covered(cells, p[0], p[1]):
                if len(p) < 11:
                    p.append(1)
                n += 1
        print(f"   ESASky {name}: covers {n} pointings", flush=True)
    for p in P:
        if len(p) < 11:
            p.append(0)

    # 2. which pointings to preview: WANDERERS targets and catalogue stars inside a frame
    want = {}
    idx = json.loads((APP / "index.json").read_text())
    stars = json.loads((APP / "stars.json").read_text())
    things = [(t["name"], t["ra"], t["dec"], 2) for t in idx] + [(s[0], s[2], s[3], 1) for s in stars]
    for name, ra, dec, k in things:
        cand = [p for p in P if abs(p[1] - dec) <= p[2] + 0.01 and
                np.degrees(np.arccos(np.clip(np.sin(np.radians(dec)) * np.sin(np.radians(p[1])) + np.cos(np.radians(dec)) *
                                             np.cos(np.radians(p[1])) * np.cos(np.radians(ra - p[0])), -1, 1))) <= p[2] * 1.01
                and inside(p, ra, dec)]
        for p in sorted(cand, key=score)[:k]:
            want.setdefault(p[8], set()).add(name)
    print(f"   previews wanted: {len(want)}", flush=True)

    out_dir = APP / "webb"
    out_dir.mkdir(exist_ok=True)
    meta_path = APP / "webb_previews.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    for k, (obs, names) in enumerate(sorted(want.items())):
        if obs in meta and (out_dir / f"{obs}.jpg").exists():
            continue
        url = f"https://mast.stsci.edu/api/v0.1/Download/file?uri=mast:JWST/product/{obs}_i2d.jpg"
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=60, context=CTX) as r:
                size = int(r.headers.get("Content-Length") or 0)
            if size > MAX_BYTES:
                print(f"   skip {obs}: {size / 1e6:.0f} MB", flush=True); continue
            im = Image.open(io.BytesIO(get(url)))
            hdr = dict(line.split("=", 1) for line in im.info.get("comment", b"").decode(errors="ignore").splitlines() if "=" in line)
            hdr = {k.strip(): v.split("/")[0].strip().strip("'").strip() for k, v in hdr.items()}
            if "CRVAL1" not in hdr:
                print(f"   skip {obs}: no WCS", flush=True); continue
            w0, h0 = im.size
            f = min(1.0, MAX_PX / max(w0, h0))
            if f < 1:
                im = im.resize((max(1, round(w0 * f)), max(1, round(h0 * f))), Image.LANCZOS)
            im.convert("L").save(out_dir / f"{obs}.jpg", quality=84, optimize=True)
            blacken_border(out_dir / f"{obs}.jpg")
            wcs = {"NAXIS": 2, "NAXIS1": im.size[0], "NAXIS2": im.size[1], "CTYPE1": hdr["CTYPE1"], "CTYPE2": hdr["CTYPE2"],
                   "CRVAL1": float(hdr["CRVAL1"]), "CRVAL2": float(hdr["CRVAL2"]),
                   "CRPIX1": (float(hdr["CRPIX1"]) - 0.5) * f + 0.5, "CRPIX2": (float(hdr["CRPIX2"]) - 0.5) * f + 0.5,
                   "CDELT1": float(hdr["CDELT1"]) / f, "CDELT2": float(hdr["CDELT2"]) / f, "CROTA2": float(hdr.get("CROTA2", 0))}
            add_rotation(wcs, obs)
            meta[obs] = {"wcs": wcs, "for": sorted(names)}
            meta_path.write_text(json.dumps(meta, separators=(",", ":")))
            print(f"   [{k + 1}/{len(want)}] {obs} ({', '.join(sorted(names)[:3])}) {w0}x{h0} -> {im.size[0]}x{im.size[1]}", flush=True)
        except Exception as e:
            print(f"   fail {obs}: {e}", flush=True)
    for obs, m in meta.items():           # previews made before the rotation fix
        if "PC1_1" not in m["wcs"]:
            try:
                print(f"   rotation {obs}: {add_rotation(m['wcs'], obs)}", flush=True)
            except Exception as e:
                print(f"   rotation {obs} failed: {e}", flush=True)
    meta_path.write_text(json.dumps(meta, separators=(",", ":")))
    for p in P:
        if len(p) < 12:
            p.append(1 if p[8] in meta else 0)
        else:
            p[11] = 1 if p[8] in meta else 0
    (APP / "webb.json").write_text(json.dumps(W, separators=(",", ":"), ensure_ascii=False))
    print(f"previews: {len(meta)}; webb.json updated with live-map and preview flags")


if __name__ == "__main__":
    main()
