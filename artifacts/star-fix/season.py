# Which dates fit "LST seen in the photo" at about 19:00 local time, and is the sky dark then?
import numpy as np, warnings; warnings.filterwarnings('ignore')
from astropy.time import Time
from astropy.coordinates import get_sun, EarthLocation, AltAz
import astropy.units as u
days = Time('2026-01-01T19:00') + np.arange(0, 365, 1) * u.day      # 19:00 local MEAN time at longitude 0
lst = days.sidereal_time('mean', longitude=0*u.deg).hour            # LST at 19:00 local mean time
for name, lo, hi in (('photos 2+3', 10.51, 11.43), ('photos 1+4', 9.66, 10.50)):
    # civil 7pm can differ from local mean time by about +-1 h (time-zone edge, daylight saving): widen by 1 h
    ok = (lst > lo - 1) & (lst < hi + 1); core = (lst > lo) & (lst < hi)
    d = days[ok].strftime('%b %d'); c = days[core].strftime('%b %d')
    print(f'{name}: LST {lo}-{hi} h -> core dates {c[0]} .. {c[-1]}; with +-1 h zone slack {d[0]} .. {d[-1]}')
for lat in (-35, -45, -53, -60):
    loc = EarthLocation(lat=lat*u.deg, lon=0*u.deg)
    alt = get_sun(days).transform_to(AltAz(obstime=days, location=loc)).alt.deg
    for m in ('2026-04-15', '2026-05-15', '2026-06-15'):
        i = int((Time(m) - Time('2026-01-01')).jd)
        print(f'  lat {lat}: sun altitude at 19:00 on {m[5:]}: {alt[i]:.0f} deg')
