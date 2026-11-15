# Score the estimates against the true place, and find which input was wrong: the time or the "up" direction.
import sys, numpy as np, warnings; warnings.filterwarnings('ignore')
from astropy.time import Time
from astropy.coordinates import EarthLocation, get_sun, AltAz
import astropy.units as u
exec(open('fix_core.py').read())            # P (photos, glow up), up_pred, vec, D
LAT, LON = -38.48, 145.23
def km(a, b, c, d):
    a, b, c, d = map(np.radians, (a, b, c, d))
    return 6371 * np.arccos(np.sin(a)*np.sin(c) + np.cos(a)*np.cos(c)*np.cos(b - d))
for name, la, lo in (('stars+glow', -53, 124), ('stars, up=image top', -35, 131), ('glow, inside GMT+10', -42, 141),
                     ('image top, inside GMT+10', -27, 141), ('combined answer', -35, 141)):
    print(f'{name:26s} {la:4.0f} {lo:4.0f}  -> {km(la, lo, LAT, LON):5.0f} km off')
print()
for hh in np.arange(17.0, 20.01, 0.25):
    t = Time('2026-06-15T00:00:00') + (hh - 10) * u.hour
    lst = t.sidereal_time('mean', longitude=LON*u.deg).deg; z = vec(lst, LAT)
    sun = get_sun(t).transform_to(AltAz(obstime=t, location=EarthLocation(lat=LAT*u.deg, lon=LON*u.deg))).alt.deg
    row = []
    for i, p in P.items():
        alt = 90 - np.degrees(np.arccos(np.dot(p['c'], z))); altb = 90 - np.degrees(np.arccos(np.dot(p['b'], z)))
        row.append(f'{i}: up {up_pred(p, z):+4.0f} (glow {p["up_obs"]:+4.0f}) alt {alt:3.0f}/{altb:3.0f}')
    print(f'{int(hh):02d}:{int(hh%1*60):02d} sun {sun:4.0f} | ' + ' | '.join(row))
