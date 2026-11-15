# What local (GMT+10) time makes the measured LST match a place inside the zone, and how dark is it then?
import numpy as np, warnings; warnings.filterwarnings('ignore')
from astropy.time import Time
from astropy.coordinates import get_sun, EarthLocation, AltAz
import astropy.units as u
day0 = Time('2026-06-15T00:00:00')
for name, lst in (('photos 2+3 (glow)', 10.97), ('photos 2+3 (image top)', 11.43), ('photos 1+4 (glow)', 9.97)):
    for lon, lat in ((145, -38), (151, -34)):
        ts = day0 + np.arange(5*60, 13*60) * u.min          # 05:00-13:00 UTC = 15:00-23:00 GMT+10
        l = ts.sidereal_time('mean', longitude=lon*u.deg).hour
        k = np.argmin(np.abs(((l - lst + 12) % 24) - 12)); t = ts[k]
        sun = get_sun(t).transform_to(AltAz(obstime=t, location=EarthLocation(lat=lat*u.deg, lon=lon*u.deg))).alt.deg
        print(f'{name}: to match {lon} E / {lat}, the photo time is {(t + 10*u.hour).strftime("%H:%M")} GMT+10, sun altitude {sun:.0f} deg')
loc = EarthLocation(lat=-36*u.deg, lon=148*u.deg)
for hh in ('17:30', '18:00', '18:30', '19:00'):
    t = Time(f'2026-06-15T{hh}:00') - 10*u.hour
    print(f'sun altitude at {hh} GMT+10, 36 S 148 E: {get_sun(t).transform_to(AltAz(obstime=t, location=loc)).alt.deg:.0f} deg')
