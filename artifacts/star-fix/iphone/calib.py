import json, numpy as np, warnings; warnings.filterwarnings('ignore')
exec(open('fix_heic.py').read().split('res = {}')[0])
from astropy.coordinates import EarthLocation, AltAz
loc = EarthLocation(lat=-38.48*u.deg, lon=145.23*u.deg)
for name, r in S.items():
    if not name.startswith('20260614'): continue
    w = WCS(Header.fromstring(open(f'heic/{name}.hdr').read())); R = cam_to_sky(w, r['W'], r['H'])
    t = Time(r['time'].replace(':', '-', 2)) - 10*u.hour
    zen = SkyCoord(alt=90*u.deg, az=0*u.deg, frame=AltAz(obstime=t, location=loc)).transform_to('icrs')
    ut = R.T @ vec(zen.ra.deg, zen.dec.deg)[0]
    print(f"{name} {'portrait ' if r['H']>=r['W'] else 'landscape'} true up (cam X right,Y down,Z fwd) {np.round(ut,3)}   gravity g {np.round(r['accel'],3)}  my up {np.round(up_cam(r['accel'], r['W'], r['H']),3)}")
print()
for name, r in S.items():
    if not (name.startswith('20260614') and r['solved']): continue
    w = WCS(Header.fromstring(open(f'heic/{name}.hdr').read())); R = cam_to_sky(w, r['W'], r['H'])
    t = Time(r['time'].replace(':', '-', 2)) - 10*u.hour
    zen = SkyCoord(alt=90*u.deg, az=0*u.deg, frame=AltAz(obstime=t, location=loc)).transform_to('icrs')
    ut = R.T @ vec(zen.ra.deg, zen.dec.deg)[0]; mu = up_cam(r['accel'], r['W'], r['H'])
    print(f"{name}: angle between true up and gravity up = {np.degrees(np.arccos(np.clip(ut @ mu, -1, 1))):.1f} deg; "
          f"tilt (alt) true {np.degrees(np.arcsin(ut[2])):.1f} vs gravity {np.degrees(np.arcsin(mu[2])):.1f}; "
          f"roll true {np.degrees(np.arctan2(ut[0], -ut[1])):.1f} vs gravity {np.degrees(np.arctan2(mu[0], -mu[1])):.1f}")
