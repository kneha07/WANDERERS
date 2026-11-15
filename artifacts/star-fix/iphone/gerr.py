import json, numpy as np, warnings; warnings.filterwarnings('ignore')
exec(open('fix_heic.py').read().split('res = {}')[0])
from astropy.coordinates import EarthLocation, AltAz
K = json.load(open('answer_key.json')); F = json.load(open('heic/fixes.json'))
def dms(s, ref):
    p = [eval(x) for x in s.strip('[]').split(',')]; v = p[0] + p[1]/60 + p[2]/3600
    return -v if ref in ('S', 'W') else v
for n, r in S.items():
    if not r['solved']: continue
    k = K[n]; loc = EarthLocation(lat=dms(k['GPS GPSLatitude'], k['GPS GPSLatitudeRef'])*u.deg, lon=dms(k['GPS GPSLongitude'], k['GPS GPSLongitudeRef'])*u.deg)
    off = r['offset']; t = Time(r['time'].replace(':', '-', 2)) - (1 if off[0] == '+' else -1) * int(off[1:3]) * u.hour
    w = WCS(Header.fromstring(open(f'heic/{n}.hdr').read())); R = cam_to_sky(w, r['W'], r['H'])
    zen = SkyCoord(alt=90*u.deg, az=0*u.deg, frame=AltAz(obstime=t, location=loc)).transform_to('icrs')
    ut = R.T @ vec(zen.ra.deg, zen.dec.deg)[0]; mu = up_cam(r['accel'], r['W'], r['H'])
    c = SkyCoord(*w.wcs_pix2world([[r['W']/2, r['H']/2]], 0)[0], unit='deg').transform_to(AltAz(obstime=t, location=loc))
    dh = (r['heading'] - c.az.deg + 180) % 360 - 180
    print(f"{n}: gravity error {np.degrees(np.arccos(np.clip(ut @ mu, -1, 1))):4.1f} deg | camera true az {c.az.deg:5.1f} alt {c.alt.deg:4.1f} | EXIF heading {r['heading']:5.1f} (off by {dh:+6.1f})")
