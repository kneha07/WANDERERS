# Does browser-style compression (resize + JPEG quality) change the Star Fix answer?
# Same maths as artifacts/star-fix/win/probe.py. Metadata (time, gravity, orientation) comes from the original,
# as if the page copied the EXIF block into the compressed JPEG. Prints distances only, never coordinates.
import sys, io, glob, os, math, struct, time, warnings; warnings.filterwarnings('ignore')
import numpy as np; np.math = math
import pillow_heif, exifread, tetra3
from PIL import Image
from astropy.coordinates import SkyCoord, TETE
from astropy.time import Time
from astropy.utils import iers
import astropy.units as u
from astropy.wcs.utils import fit_wcs_from_points
iers.conf.auto_download = False; iers.conf.iers_degraded_accuracy = 'ignore'
pillow_heif.register_heif_opener(); t3 = tetra3.Tetra3()

def apple_makernote(raw):
    i = raw.find(b'Apple iOS\x00'); mn = raw[i:]; bo = '>' if mn[12:14] == b'MM' else '<'
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
    U, _, Vt = np.linalg.svd(sky.T @ cam); d = np.sign(np.linalg.det(U @ Vt)); return U @ np.diag([1, 1, d]) @ Vt
AXES = {6: lambda x, y: (x, -y), 1: lambda x, y: (-y, -x), 3: lambda x, y: (y, x), 8: lambda x, y: (-x, y)}
def up_cam(g, o): X, Y = AXES[o](g[0], g[1]); c = np.array([X, Y, -g[2]]); return -c / np.linalg.norm(c)
def km(a, b): return 6371 * math.acos(max(-1, min(1, float(vec(a[1], a[0])[0] @ vec(b[1], b[0])[0]))))

def fix(im, g, orient, utc):
    gray = im.convert('L'); W0, H0 = gray.size; k = 2048 / max(W0, H0)
    if k < 1: gray = gray.resize((round(W0*k), round(H0*k)), Image.LANCZOS)
    W, H = gray.size; r = {}; n = 0
    for frac in (0.5, 0.35, 1.0):
        cw, ch = int(W*frac), int(H*frac); ox, oy = (W-cw)//2, (H-ch)//2
        for sigma in (3, 2):
            cents = tetra3.get_centroids_from_image(gray.crop((ox, oy, ox+cw, oy+ch)), sigma=sigma, max_area=300, min_area=2)
            n = max(n, len(cents))
            if len(cents) < 6: continue
            r = t3.solve_from_centroids(cents[:60], (ch, cw), solve_timeout=5000, return_matches=True)
            if r.get('RA') is not None: break
        if r.get('RA') is not None: break
    if r.get('RA') is None or r['Matches'] < 8: return None, 0, n
    mc = np.array(r['matched_centroids']); ms = np.array(r['matched_stars']); px = (mc[:, 1] + ox, mc[:, 0] + oy)
    sk = SkyCoord(ms[:, 0]*u.deg, ms[:, 1]*u.deg); w = fit_wcs_from_points(px, sk, projection='TAN')
    for _ in range(3): w = fit_wcs_from_points(px, sk, projection='TAN', proj_point=w.pixel_to_world(W/2, H/2))
    z = cam_to_sky(w, W, H) @ up_cam(g, orient)
    zz = SkyCoord(np.degrees(np.arctan2(z[1], z[0])) % 360 * u.deg, np.degrees(np.arcsin(z[2])) * u.deg).transform_to(TETE(obstime=utc))
    return (zz.dec.deg, (zz.ra - utc.sidereal_time('apparent', 'greenwich')).wrap_at(180*u.deg).deg), r['Matches'], n

SIZES = (None, 3072, 2048, 1600, 1280, 1024)     # long side in px; None = original pixels
QUALS = (0.92, 0.8, 0.6, 0.4)
for f in sys.argv[1:]:
    im = Image.open(f); raw = im.info['exif']
    t = exifread.process_file(io.BytesIO(raw[6:] if raw[:4] == b'Exif' else raw), details=False)
    orient = im.info.get('original_orientation') or (t['Image Orientation'].values[0] if 'Image Orientation' in t else 1)
    g = apple_makernote(raw)[8]; off = str(t['EXIF OffsetTimeOriginal']); sign = 1 if off[0] == '+' else -1
    utc = Time(str(t['EXIF DateTimeOriginal']).replace(':', '-', 2)) - sign * (int(off[1:3]) + int(off[4:6])/60) * u.hour
    gp = lambda tg, ref: (lambda p: -p if str(t[ref]) in 'SW' else p)(sum(v.num / v.den / 60**i for i, v in enumerate(t[tg].values)))
    gps = (gp('GPS GPSLatitude', 'GPS GPSLatitudeRef'), gp('GPS GPSLongitude', 'GPS GPSLongitudeRef'))
    rgb = im.convert('RGB'); base, m0, n0 = fix(rgb, g, orient, utc)
    print(f"\n{os.path.basename(f)[:18]}  original {rgb.size[0]}x{rgb.size[1]} {os.path.getsize(f)/1e6:.1f} MB: "
          + (f"{m0} matches, {km(base, gps):.0f} km from phone GPS" if base else f"no solve ({n0} spots)"), flush=True)
    for s in SIZES:
        for q in QUALS:
            x = rgb if s is None else rgb.resize((round(rgb.size[0]*s/max(rgb.size)), round(rgb.size[1]*s/max(rgb.size))), Image.BILINEAR)
            b = io.BytesIO(); x.save(b, 'JPEG', quality=round(q*100)); mb = b.tell()/1e6
            p, m, n = fix(Image.open(io.BytesIO(b.getvalue())), g, orient, utc)
            res = (f"{m:3d} matches  {km(p, gps):5.0f} km from GPS  {km(p, base):5.1f} km from original answer" if p and base
                   else f"{m:3d} matches  {km(p, gps):5.0f} km from GPS" if p else f"no solve ({n} spots)")
            print(f"  long side {s or max(rgb.size):4d}  q {q:.2f}  {mb:5.2f} MB  {res}", flush=True)
