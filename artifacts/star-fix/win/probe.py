# Windows probe for the Star Fix design (docs/specs/star-fix-design.md).
# Runs the whole chain on original iPhone HEIC files and prints timings and the error against the file's own GPS.
# GPS is read only to score; only the distance in km is printed, never the coordinates.
#   .venv\Scripts\python.exe artifacts\star-fix\win\probe.py <folder with *.heic>
import sys, io, glob, os, json, math, struct, time, warnings; warnings.filterwarnings('ignore')
t0 = time.time()
import numpy as np; np.math = math          # cedar-solve still calls np.math (removed in numpy 2)
import pillow_heif, exifread, tetra3
from PIL import Image
from astropy.coordinates import SkyCoord, TETE
from astropy.time import Time
from astropy.utils import iers
import astropy.units as u
from astropy.wcs.utils import fit_wcs_from_points
iers.conf.auto_download = False; iers.conf.iers_degraded_accuracy = 'ignore'   # offline: UT1-UTC error < 0.9 s = 0.4 km
pillow_heif.register_heif_opener()
t_imp = time.time() - t0; t0 = time.time(); t3 = tetra3.Tetra3(); t_db = time.time() - t0
print(f'import {t_imp:.1f} s, database load {t_db:.1f} s', flush=True)

def apple_makernote(raw):
    i = raw.find(b'Apple iOS\x00')
    if i < 0: return {}
    mn = raw[i:]; bo = '>' if mn[12:14] == b'MM' else '<'
    n = struct.unpack(bo + 'H', mn[14:16])[0]; out = {}
    for k in range(n):
        tag, typ, cnt, val = struct.unpack(bo + 'HHII', mn[16 + 12*k: 28 + 12*k])
        if typ in (5, 10):
            nums = struct.unpack(bo + ('ii' if typ == 10 else 'II') * cnt, mn[val: val + 8*cnt])
            out[tag] = [nums[j] / nums[j+1] if nums[j+1] else None for j in range(0, len(nums), 2)]
    return out
def vec(ra, de): ra, de = np.radians(ra), np.radians(de); return np.c_[np.cos(de)*np.cos(ra), np.cos(de)*np.sin(ra), np.sin(de)]
def cam_to_sky(w, W, H):
    f = 1 / np.radians(abs(w.proj_plane_pixel_scales()[0].value)); cx, cy = w.wcs.crpix - 1
    xs, ys = np.meshgrid(np.linspace(0, W, 9), np.linspace(0, H, 9)); xs, ys = xs.ravel(), ys.ravel()
    cam = np.c_[xs - cx, ys - cy, np.full(xs.size, f)]; cam /= np.linalg.norm(cam, axis=1)[:, None]
    s = w.pixel_to_world(xs, ys); sky = vec(s.ra.deg, s.dec.deg)
    U, _, Vt = np.linalg.svd(sky.T @ cam); d = np.sign(np.linalg.det(U @ Vt))
    return U @ np.diag([1, 1, d]) @ Vt, f
# gravity (device x right, y top, z out of screen) -> (image right, image down) for each EXIF Orientation of the rear camera
AXES = {6: lambda x, y: (x, -y), 1: lambda x, y: (-y, -x), 3: lambda x, y: (y, x), 8: lambda x, y: (-x, y)}
def up_cam(g, orient):
    X, Y = AXES[orient](g[0], g[1]); c = np.array([X, Y, -g[2]]); return -c / np.linalg.norm(c)
def guess_orient(g, W, H):   # the rule of fix_heic.py: picture shape + sign of gx
    return (6 if g[1] < 0 else 8) if H >= W else (1 if g[0] < 0 else 3)
def dms(t, ref):
    p = [v.num / v.den for v in t.values]; v = p[0] + p[1]/60 + p[2]/3600; return -v if str(ref) in ('S', 'W') else v
def km(a, b):
    return 6371 * math.acos(max(-1, min(1, float(vec(a[1], a[0])[0] @ vec(b[1], b[0])[0]))))

sessions = {}
for f in sorted(glob.glob(os.path.join(sys.argv[1], '*.heic'))):
    name = os.path.basename(f)[:15]; t0 = time.time()
    data = open(f, 'rb').read(); im = Image.open(io.BytesIO(data)); raw = im.info.get('exif', b'')
    t = exifread.process_file(io.BytesIO(raw[6:] if raw[:4] == b'Exif' else raw), details=False)
    tag = t.get('Image Orientation'); tag = tag.values[0] if tag else None
    orig = im.info.get('original_orientation')
    g = apple_makernote(raw).get(8); gps = (dms(t['GPS GPSLatitude'], t['GPS GPSLatitudeRef']), dms(t['GPS GPSLongitude'], t['GPS GPSLongitudeRef']))
    gray = im.convert('L'); W0, H0 = gray.size; k = 2048 / max(W0, H0)
    gray = gray.resize((round(W0*k), round(H0*k)), Image.LANCZOS); W, H = gray.size
    r = {}; tries = 0
    for frac in (0.5, 0.35, 1.0):
        cw, ch = int(W*frac), int(H*frac); ox, oy = (W-cw)//2, (H-ch)//2
        for sigma in (3, 2):
            cents = tetra3.get_centroids_from_image(gray.crop((ox, oy, ox+cw, oy+ch)), sigma=sigma, max_area=300, min_area=2)
            if len(cents) < 6: continue
            tries += 1; r = t3.solve_from_centroids(cents[:60], (ch, cw), solve_timeout=5000, return_matches=True)
            if r.get('RA') is not None: break
        if r.get('RA') is not None: break
    head = f"{name} {str(t.get('Image Model'))} size {W0}x{H0} exifOrient {tag} heifOrig {orig} guess {guess_orient(g, W, H)} |g| {np.linalg.norm(g):.3f}"
    if r.get('RA') is None or r['Matches'] < 8:
        print(f"{head} | NOT SOLVED ({len(cents)} stars, {tries} tries, {time.time()-t0:.1f} s)", flush=True); continue
    mc = np.array(r['matched_centroids']); ms = np.array(r['matched_stars']); px = (mc[:, 1] + ox, mc[:, 0] + oy)
    sk = SkyCoord(ms[:, 0]*u.deg, ms[:, 1]*u.deg); w = fit_wcs_from_points(px, sk, projection='TAN')
    for _ in range(3): w = fit_wcs_from_points(px, sk, projection='TAN', proj_point=w.pixel_to_world(W/2, H/2))
    R, fpx = cam_to_sky(w, W, H)
    off = str(t['EXIF OffsetTimeOriginal']); sign = 1 if off[0] == '+' else -1
    utc = Time(str(t['EXIF DateTimeOriginal']).replace(':', '-', 2)) - sign * (int(off[1:3]) + int(off[4:6])/60) * u.hour
    out = []
    for o in (orig or tag, guess_orient(g, W, H)):
        z = R @ up_cam(g, o)
        zz = SkyCoord(np.degrees(np.arctan2(z[1], z[0])) % 360 * u.deg, np.degrees(np.arcsin(z[2])) * u.deg).transform_to(TETE(obstime=utc))
        out.append((zz.dec.deg, (zz.ra - utc.sidereal_time('apparent', 'greenwich')).wrap_at(180*u.deg).deg))
    cam_alt = 90 - np.degrees(np.arccos(np.clip((R @ np.array([0, 0, 1.0])) @ (R @ up_cam(g, orig or tag)), -1, 1)))
    print(f"{head} | matches {r['Matches']} crop {frac} f {fpx*max(W0,H0)/2048:.0f}px camAlt {cam_alt:.0f} | error by tag {km(out[0], gps):.0f} km, by guess {km(out[1], gps):.0f} km | {time.time()-t0:.1f} s", flush=True)
    sessions.setdefault(name[:8], []).append((out[0], gps))
for s, v in sessions.items():
    p = np.array([vec(o[1], o[0])[0] for o, _ in v]); m = np.median(p, axis=0); m /= np.linalg.norm(m)
    med = (math.degrees(math.asin(m[2])), math.degrees(math.atan2(m[1], m[0])))
    d = sorted(km(o, med) for o, _ in v)
    print(f"session {s}: {len(v)} photos, median fix error {km(med, v[0][1]):.0f} km, distances from the median {[round(x) for x in d]}")
