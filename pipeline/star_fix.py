"""Star Fix: where on Earth was this night-sky photo taken? From the stars, the phone's gravity sensor and its clock.

  python pipeline/star_fix.py            reads the photo from stdin (what server.js does)
  python pipeline/star_fix.py <file>     reads a file
Both print one JSON line and exit 0: status fix, sky_only, no_solve or bad_file (docs/specs/star-fix-build.md, section 6).
Ported from artifacts/star-fix/win/probe.py, which was checked on 14 original iPhone photos.
"""
import io
import json
import math
import struct
import sys
import warnings
from datetime import datetime, timedelta, timezone

import numpy as np
import astropy.units as u
import pillow_heif
from astropy.coordinates import SkyCoord, TETE, get_constellation
from astropy.time import Time
from astropy.utils import iers
from astropy.wcs.utils import fit_wcs_from_points
from PIL import Image, ImageOps

np.math = math                               # cedar-solve still calls np.math (removed in numpy 2); set before it loads
warnings.filterwarnings("ignore")
iers.conf.auto_download = False              # never wait for the network (firewall, offline demo)
iers.conf.iers_degraded_accuracy = "ignore"  # UT1-UTC error stays below 0.9 s = 0.4 km
pillow_heif.register_heif_opener()
EXIF, GPS = 0x8769, 0x8825                   # EXIF sub-directories
_t3 = None                                   # the solver with its star database, loaded on the first solve
# Solve quality gate, measured on 4 photos and 96 recompressed copies (2026-11-15): every right solve had RMSE <= 165"
# and Prob <= 2.6e-9 (the weakest: 8 matches, Prob 2.0e-9, RMSE 145", 1.2 km off). The false solves had RMSE 423-516"
# and Prob 2.3e-7 or 5.2e-6; one (15 matches) put a JPEG copy of 20260614_081100956 2800 km off.
MIN_MATCHES, MAX_RMSE_ARCSEC, MAX_FALSE_PROB = 8, 300, 1e-8
SMALL_PX = 1600   # long side below this: 8-16 matches at 1280 px and one false solve before the gate (measured)
MAX_PIXELS = 60_000_000   # the largest iPhone photo is 48 MP; a bigger picture (a decompression bomb) is refused, not decoded

# Gravity (device axes: x right of the screen, y top of the phone, z out of the screen) -> (picture right, picture down)
# of the upright picture, for each EXIF orientation of the rear camera.
AXES = {6: lambda x, y: (x, -y), 1: lambda x, y: (-y, -x), 3: lambda x, y: (y, x), 8: lambda x, y: (-x, y)}


def apple_makernote(raw):
    """Apple MakerNote bytes -> {tag: [rational, ...]}. Offsets count from the MakerNote start. Tag 8 is gravity."""
    i = raw.find(b"Apple iOS\x00")
    if i < 0:
        return {}
    mn = raw[i:]
    bo = ">" if mn[12:14] == b"MM" else "<"
    out = {}
    try:
        for k in range(struct.unpack(bo + "H", mn[14:16])[0]):
            tag, typ, cnt, val = struct.unpack(bo + "HHII", mn[16 + 12 * k: 28 + 12 * k])
            if typ in (5, 10):
                nums = struct.unpack(bo + ("ii" if typ == 10 else "II") * cnt, mn[val: val + 8 * cnt])
                out[tag] = [nums[j] / nums[j + 1] if nums[j + 1] else None for j in range(0, len(nums), 2)]
    except struct.error:   # cut or damaged note: keep what was read
        pass
    return out


def degrees(v, ref):
    d = float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
    return -d if str(ref).strip()[:1] in ("S", "W") else d


def read_meta(im):
    """Time, gravity, orientation, camera and GPS of an opened picture. Call it before the picture is turned upright."""
    ex = im.getexif()
    e = ex.get_ifd(EXIF)
    m = {"orient": im.info.get("original_orientation") or ex.get(274) or 1,   # pillow-heif resets 274 to 1
         "model": ex.get(272), "lens": str(e.get(42036) or ""), "focal35": e.get(41989),
         "utc": None, "local": None, "offset": None, "g": None, "gps": None}
    try:
        off = str(e[36881]).strip("\x00 ")
        hours = (1 if off[0] == "+" else -1) * (int(off[1:3]) + int(off[4:6]) / 60)
        local = datetime.strptime(str(e[36867]).strip("\x00 "), "%Y:%m:%d %H:%M:%S").replace(tzinfo=timezone(timedelta(hours=hours)))
        m.update(local=local.isoformat(), utc=local.astimezone(timezone.utc).replace(tzinfo=None), offset=hours)
    except (KeyError, IndexError, ValueError):
        pass
    g = apple_makernote(e.get(37500) or b"").get(8)
    if g and len(g) == 3 and None not in g and any(g):
        m["g"] = g
    gps = ex.get_ifd(GPS)
    try:
        lat, lon = degrees(gps[2], gps[1]), degrees(gps[4], gps[3])
        if math.isfinite(lat) and math.isfinite(lon):
            m["gps"] = {"lat": round(lat, 2), "lon": round(lon, 2)}
    except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError):
        pass
    return m


def unit(ra, dec):
    ra, dec = np.radians(ra), np.radians(dec)
    return np.c_[np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)]


def cam_to_sky(w, W, H):
    """Rotation camera frame -> ICRS that best matches the sky map on a 9 x 9 pixel grid (SVD)."""
    f = 1 / np.radians(abs(w.proj_plane_pixel_scales()[0].value))   # focal length in pixels, from the stars
    cx, cy = w.wcs.crpix - 1
    xs, ys = np.meshgrid(np.linspace(0, W, 9), np.linspace(0, H, 9))
    xs, ys = xs.ravel(), ys.ravel()
    cam = np.c_[xs - cx, ys - cy, np.full(xs.size, f)]
    cam /= np.linalg.norm(cam, axis=1)[:, None]
    s = w.pixel_to_world(xs, ys)
    U, _, Vt = np.linalg.svd(unit(s.ra.deg, s.dec.deg).T @ cam)
    return U @ np.diag([1, 1, np.sign(np.linalg.det(U @ Vt))]) @ Vt


def solve(im):
    """Upright picture -> {"R": camera-to-sky rotation, "sky": {...}}, or {"stars": spots found} when it does not solve."""
    global _t3
    import tetra3
    if _t3 is None:
        _t3 = tetra3.Tetra3()
    gray = im.convert("L")
    k = 2048 / max(gray.size)
    gray = gray.resize((round(gray.width * k), round(gray.height * k)), Image.LANCZOS)
    W, H = gray.size
    r = None
    for frac in (0.5, 0.35, 1.0):            # the star database covers 10-30 degree fields; a phone sees about 65
        cw, ch = int(W * frac), int(H * frac)
        ox, oy = (W - cw) // 2, (H - ch) // 2
        for sigma in (3, 2):
            cents = tetra3.get_centroids_from_image(gray.crop((ox, oy, ox + cw, oy + ch)), sigma=sigma, max_area=300, min_area=2)
            spots = len(cents)                   # reported from the last try: whole picture, sigma 2
            if len(cents) < 6:
                continue
            t = _t3.solve_from_centroids(cents[:60], (ch, cw), solve_timeout=5000, return_matches=True)
            if t.get("RA") is not None and t["Matches"] >= MIN_MATCHES and t["RMSE"] <= MAX_RMSE_ARCSEC and t["Prob"] <= MAX_FALSE_PROB:
                r = t                            # else: a weak or false solve, try the next sigma or crop
                break
        if r:
            break
    if not r:
        return {"stars": spots}
    mc, ms = np.array(r["matched_centroids"]), np.array(r["matched_stars"])
    px, sky = (mc[:, 1] + ox, mc[:, 0] + oy), SkyCoord(ms[:, 0] * u.deg, ms[:, 1] * u.deg)
    w = fit_wcs_from_points(px, sky, projection="TAN")
    for _ in range(3):   # tangent point at the picture centre (the lens axis), not at the centre of the stars
        w = fit_wcs_from_points(px, sky, projection="TAN", proj_point=w.pixel_to_world(W / 2, H / 2))
    c = w.pixel_to_world(W / 2, H / 2)
    return {"R": cam_to_sky(w, W, H), "sky": {"ra": round(float(c.ra.deg), 1), "dec": round(float(c.dec.deg), 1),
                                              "matches": int(r["Matches"]), "constellation": str(get_constellation(c))}}


def up_cam(g, orient):
    """Unit vector "up" in the camera frame (X right, Y down, Z forward = -z of the device)."""
    X, Y = AXES[orient](g[0], g[1])
    c = np.array([X, Y, -g[2]], dtype=float)
    return -c / np.linalg.norm(c)


def position(R, g, orient, utc):
    """Camera-to-sky rotation R (ICRS), gravity g, orientation and UTC -> {lat, lon, camera_alt} in degrees."""
    t = Time(utc, scale="utc")
    z = R @ up_cam(g, orient)                 # the zenith, ICRS unit vector
    zz = SkyCoord(math.degrees(math.atan2(z[1], z[0])) % 360 * u.deg, math.degrees(math.asin(np.clip(z[2], -1, 1))) * u.deg) \
        .transform_to(TETE(obstime=t))
    lon = (zz.ra - t.sidereal_time("apparent", "greenwich")).wrap_at(180 * u.deg).deg
    axis = R @ np.array([0, 0, 1.0])
    return {"lat": float(zz.dec.deg), "lon": float(lon), "camera_alt": 90 - math.degrees(math.acos(np.clip(axis @ z, -1, 1)))}


def star_fix(data):
    """Photo file bytes -> result dict (section 6 of the design)."""
    try:
        im = Image.open(io.BytesIO(data))   # reads the header only; Pillow's DecompressionBombError lands in the except
        if im.width * im.height > MAX_PIXELS:
            return {"status": "bad_file"}
        im.load()
    except Exception:   # not an image Pillow (or pillow-heif) can decode
        return {"status": "bad_file"}
    m = read_meta(im)
    warn = ["small_photo"] if max(im.size) < SMALL_PX else []
    s = solve(ImageOps.exif_transpose(im))
    if "R" not in s:
        return {"status": "no_solve", "stars": s["stars"], "warnings": warn}
    utc = m["utc"] and m["utc"].strftime("%Y-%m-%dT%H:%M:%SZ")
    missing = [k for k, gone in (("gravity", m["g"] is None), ("time", utc is None),
                                 ("rear_camera", m["orient"] not in AXES or "front" in m["lens"].lower())) if gone]
    if missing:   # mirrored orientations (2, 4, 5, 7) count as an unsupported camera
        return {"status": "sky_only", "sky": s["sky"], "model": m["model"], **({"utc": utc} if utc else {}), "missing": missing,
                "warnings": warn}
    p = position(s["R"], m["g"], m["orient"], m["utc"])
    if abs((p["lon"] - 15 * m["offset"] + 180) % 360 - 180) > 45:   # the photo time or the file is suspect
        warn.append("zone_mismatch")
    if m["focal35"] is not None and not 20 <= m["focal35"] <= 30:     # only the main camera is tested
        warn.append("untested_lens")
    return {"status": "fix", "lat": round(p["lat"], 2), "lon": round(p["lon"], 2), "utc": utc, "local": m["local"],
            "sky": s["sky"], "camera_alt": round(p["camera_alt"], 1), "model": m["model"], "gps": m["gps"], "warnings": warn}


if __name__ == "__main__":
    data = open(sys.argv[1], "rb").read() if len(sys.argv) > 1 else sys.stdin.buffer.read()
    print(json.dumps(star_fix(data)))   # ASCII only: Windows stdout is cp1252
