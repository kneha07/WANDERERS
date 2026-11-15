# Position from: star solve (sky map) + iPhone gravity vector (AccelerationVector) + EXIF time. GPS is NOT read here.
import json, sys, numpy as np, warnings; warnings.filterwarnings('ignore')
from astropy.wcs import WCS
from astropy.io.fits import Header
from astropy.time import Time
from astropy.coordinates import SkyCoord, TETE
import astropy.units as u
S = json.load(open('heic/solves.json'))
def vec(ra, de): ra, de = np.radians(ra), np.radians(de); return np.c_[np.cos(de)*np.cos(ra), np.cos(de)*np.sin(ra), np.sin(de)]
def cam_to_sky(w, W, H):
    """rotation R with sky = R @ camera_ray; camera frame X right, Y down, Z forward (pinhole about CRPIX)"""
    f = 1 / np.radians(abs(w.proj_plane_pixel_scales()[0].value))       # focal length in pixels
    cx, cy = w.wcs.crpix - 1
    xs, ys = np.meshgrid(np.linspace(0, W, 9), np.linspace(0, H, 9)); xs, ys = xs.ravel(), ys.ravel()
    cam = np.c_[xs - cx, ys - cy, np.full(xs.size, f)]; cam /= np.linalg.norm(cam, axis=1)[:, None]
    s = w.pixel_to_world(xs, ys); sky = vec(s.ra.deg, s.dec.deg)
    U, _, Vt = np.linalg.svd(sky.T @ cam); d = np.sign(np.linalg.det(U @ Vt))
    return U @ np.diag([1, 1, d]) @ Vt
def up_cam(g, W, H):
    """CoreMotion gravity g (device x right, y top, z out of screen) -> 'up' in camera frame of the upright image"""
    gx, gy, gz = g
    if H >= W:   X, Y = gx, -gy            # portrait: image right = +x, image down = -y
    elif gx < 0: X, Y = -gy, -gx           # landscape, phone's left side down
    else:        X, Y = gy, gx             # landscape, phone's right side down
    gcam = np.array([X, Y, -gz]); return -gcam / np.linalg.norm(gcam)
res = {}
for name, r in S.items():
    if not r['solved']: continue
    w = WCS(Header.fromstring(open(f'heic/{name}.hdr').read()))
    z = cam_to_sky(w, r['W'], r['H']) @ up_cam(r['accel'], r['W'], r['H'])
    off = r['offset']; sign = 1 if off[0] == '+' else -1; hh, mm = map(int, off[1:].split(':'))
    t = Time(r['time'].replace(':', '-', 2)) - sign * (hh + mm/60) * u.hour      # local -> UTC
    zz = SkyCoord(*(np.degrees([np.arctan2(z[1], z[0]) % (2*np.pi), np.arcsin(z[2])])) * u.deg, frame='icrs').transform_to(TETE(obstime=t))
    lat = zz.dec.deg; lon = ((zz.ra - t.sidereal_time('apparent', 'greenwich')).wrap_at(180*u.deg)).deg
    # compass check: azimuth of the camera axis, from the solved zenith
    zc = vec(zz.ra.deg, lat)[0]                                       # (only for the az check, J2000 vs date is small here)
    c = cam_to_sky(w, r['W'], r['H']) @ np.array([0, 0, 1.0]); pole = np.array([0, 0, 1.0])
    north = pole - zc * np.dot(pole, z); east = np.cross(north, z)
    az = np.degrees(np.arctan2(np.dot(c, east), np.dot(c, north))) % 360; alt = 90 - np.degrees(np.arccos(np.dot(c, z)))
    res[name] = dict(utc=t.iso[:19], lat=round(lat, 2), lon=round(lon, 2), cam_alt=round(alt, 1), cam_az=round(az, 1), exif_heading=round(r['heading'], 1))
    print(f"{name}  UTC {t.iso[:19]}  lat {lat:7.2f}  lon {lon:8.2f}  | camera alt {alt:5.1f} az {az:5.1f}  EXIF heading {r['heading']:5.1f}")
json.dump(res, open('heic/fixes.json', 'w'), indent=1)
