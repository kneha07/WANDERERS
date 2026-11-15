"""Expected values for web/src/sky.test.ts, computed once with astropy (no refraction: pressure 0)."""
import warnings
import numpy as np
from astropy.utils import iers
iers.conf.auto_download = False
iers.conf.iers_degraded_accuracy = "warn"
warnings.simplefilter("ignore")
import astropy.units as u
from astropy.time import Time
from astropy.coordinates import SkyCoord, EarthLocation, AltAz, Angle
from astropy.wcs import WCS

seattle = EarthLocation(lat=47.6062 * u.deg, lon=-122.3321 * u.deg, height=0 * u.m)
tokyo = EarthLocation(lat=35.6762 * u.deg, lon=139.6503 * u.deg, height=0 * u.m)

t0 = Time("2000-01-01T12:00:00", scale="utc")
print("JD 2000-01-01T12Z", t0.jd)
for iso in ["2026-11-15T05:00:00", "2026-03-20T00:00:00"]:
    t = Time(iso, scale="utc")
    print("GMST", iso, t.sidereal_time("mean", "greenwich").deg, "JD", t.jd)

def altaz(name, ra, dec, loc, iso):
    t = Time(iso, scale="utc")
    aa = SkyCoord(ra * u.deg, dec * u.deg, frame="icrs").transform_to(AltAz(obstime=t, location=loc))
    print(f"ALTAZ {name} {iso} alt={aa.alt.deg:.4f} az={aa.az.deg:.4f}")

altaz("barnard seattle", 269.446268, 4.768204, seattle, "2026-11-15T01:00:00")
altaz("rwaur seattle", 76.956083, 30.401187, seattle, "2026-11-15T09:00:00")
altaz("rwaur tokyo", 76.956083, 30.401187, tokyo, "2026-11-14T12:00:00")
altaz("rdra seattle", 248.167343, 66.755011, seattle, "2026-11-15T05:00:00")

def events(name, ra, dec, loc, iso):
    t = Time(iso, scale="utc")
    grid = t + np.arange(0, 2 * 24 * 60 + 1) * u.min
    aa = SkyCoord(ra * u.deg, dec * u.deg, frame="icrs").transform_to(AltAz(obstime=grid, location=loc))
    alt = aa.alt.deg
    out = {}
    for i in range(len(alt) - 1):
        if "rise" not in out and alt[i] < 0 <= alt[i + 1]:
            f = -alt[i] / (alt[i + 1] - alt[i]); out["rise"] = (grid[i] + f * u.min).isot
        if "set" not in out and alt[i] >= 0 > alt[i + 1]:
            f = alt[i] / (alt[i] - alt[i + 1]); out["set"] = (grid[i] + f * u.min).isot
    # transit: first local maximum after t, refined with a parabola
    for i in range(1, len(alt) - 1):
        if alt[i] >= alt[i - 1] and alt[i] > alt[i + 1]:
            a, b, c = alt[i - 1], alt[i], alt[i + 1]
            off = 0.5 * (a - c) / (a - 2 * b + c)
            out["transit"] = (grid[i] + off * u.min).isot
            out["transit_alt"] = round(b - 0.25 * (a - c) * off, 4)
            break
    print("EVENTS", name, iso, out)

events("rwaur seattle", 76.956083, 30.401187, seattle, "2026-11-14T22:00:00")
events("barnard seattle", 269.446268, 4.768204, seattle, "2026-11-14T22:00:00")
events("rdra seattle", 248.167343, 66.755011, seattle, "2026-11-14T22:00:00")

# TAN grid like backend/spherex.py output_wcs + display_xy (PNG pixels, origin top-left)
def grid(ra, dec, n, s=6.15):
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]
    w.wcs.cdelt = [-s / 3600, s / 3600]
    return w

for (ra0, dec0, n, px, py) in [(269.446268, 4.768204, 49, 10.0, 40.0), (248.167343, 66.755011, 147, 3.0, 140.0)]:
    w = grid(ra0, dec0, n)
    ra, dec = w.wcs_pix2world(px - 0.5, n - 0.5 - py, 0)
    print(f"PIX2SKY center=({ra0},{dec0}) n={n} px=({px},{py}) -> ra={float(ra):.7f} dec={float(dec):.7f}")

a = SkyCoord(269.446268 * u.deg, 4.768204 * u.deg)
b = SkyCoord(269.447 * u.deg, 4.7695 * u.deg)
print("SEP arcsec", a.separation(b).arcsec)
c = SkyCoord(331.08130 * u.deg, -56.79546 * u.deg)
print("SEX", a.ra.to_string(u.hour, sep="hms", precision=2, pad=True), a.dec.to_string(sep="dms", precision=1, alwayssign=True, pad=True))
print("SEX", c.ra.to_string(u.hour, sep="hms", precision=2, pad=True), c.dec.to_string(sep="dms", precision=1, alwayssign=True, pad=True))
print("SEX carry", Angle(59.99999 / 3600 * 15 * u.deg + 15 * u.deg).to_string(u.hour, sep="hms", precision=2, pad=True))
