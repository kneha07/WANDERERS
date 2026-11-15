# One bright body (Venus here; Sun and Moon work the same way) + gravity + time -> altitude -> circle of position.
import os, json, numpy as np, warnings; warnings.filterwarnings('ignore')
from PIL import Image, ImageFilter
import pillow_heif; pillow_heif.register_heif_opener()
from astropy.time import Time
from astropy.coordinates import get_body, EarthLocation, AltAz
import astropy.units as u
exec(open('fix_heic.py').read().split('def cam_to_sky')[0].split("S = json.load")[0])
S = json.load(open('heic/solves.json')); exec('def up_cam' + open('fix_heic.py').read().split('def up_cam')[1].split('res = {}')[0])
n = '20231125_211246181'; r = S[n]
im = Image.open(os.path.join(os.environ.get('PHOTO_DIR', '.'), f'{n}_iOS.heic')).convert('L'); W, H = im.size
a = np.asarray(im.filter(ImageFilter.GaussianBlur(3)), float); a[: H//2] = 0               # Venus is in the lower half
y, x = np.unravel_index(a.argmax(), a.shape)
import sys; f = float(sys.argv[1]) if len(sys.argv) > 1 else 26 * np.hypot(W, H) / 43.27   # focal length in px
ray = np.array([x - W/2, y - H/2, f]); ray /= np.linalg.norm(ray)
up = up_cam(r['accel'], W, H); alt_meas = 90 - np.degrees(np.arccos(ray @ up))
t = Time(r['time'].replace(':', '-', 2)) - 8*u.hour
K = json.load(open('answer_key.json'))[n]
def dms(s, ref):
    p = [eval(v) for v in s.strip('[]').split(',')]; v = p[0] + p[1]/60 + p[2]/3600; return -v if ref in ('S', 'W') else v
loc = EarthLocation(lat=dms(K['GPS GPSLatitude'], K['GPS GPSLatitudeRef'])*u.deg, lon=dms(K['GPS GPSLongitude'], K['GPS GPSLongitudeRef'])*u.deg)
v = get_body('venus', t, loc).transform_to(AltAz(obstime=t, location=loc, pressure=1013*u.hPa, temperature=25*u.deg_C, relative_humidity=0.7, obswl=0.55*u.micron))
gp = get_body('venus', t)                                                                    # geocentric: sub-Venus point
print(f'Venus pixel ({x}, {y}) of {W}x{H}; measured altitude {alt_meas:.2f} deg; true altitude at GPS {v.alt.deg:.2f} deg (az {v.az.deg:.0f})')
print(f'altitude error {alt_meas - v.alt.deg:+.2f} deg = {(alt_meas - v.alt.deg)*111:+.0f} km along the circle radius')
print(f'circle of position: centre (sub-Venus point) at Dec {gp.dec.deg:.2f}, GHA-based lon {((gp.ra - t.sidereal_time("apparent","greenwich")).wrap_at(180*u.deg)).deg*-1:.1f}... radius {90 - alt_meas:.2f} deg = {(90-alt_meas)*111:.0f} km')
