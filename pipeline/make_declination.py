"""Magnetic declination grid for the Sky Compass, from NOAA's World Magnetic Model 2025.

    python pipeline/make_declination.py

Phone compasses point to magnetic north. WMM2025 (NOAA NCEI / British Geological Survey, valid
2025-2030) gives the angle between magnetic and true north anywhere on Earth. We evaluate it on a
2-degree grid for the current date and ship it as app/data/declination.json; the phone
interpolates at its GPS position. Coefficients: WMM_2025.COF as distributed with pygeomag.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from pygeomag import GeoMag

ROOT = Path(__file__).resolve().parent.parent
now = datetime.now(timezone.utc)
year = now.year + (now.timetuple().tm_yday - 1) / 365.25
gm = GeoMag(coefficients_file="wmm/WMM_2025.COF")
lats = list(range(-88, 89, 2))
lons = list(range(-180, 181, 2))
grid = [[round(gm.calculate(glat=la, glon=lo, alt=0, time=year).d * 10) for lo in lons] for la in lats]
out = {"model": "WMM2025 (NOAA NCEI / BGS)", "epoch": round(year, 2), "units": "0.1 degree, east positive",
       "lat0": lats[0], "lon0": lons[0], "step": 2, "nlat": len(lats), "nlon": len(lons), "d": grid}
(ROOT / "app" / "data" / "declination.json").write_text(json.dumps(out, separators=(",", ":")))
print(f"WMM2025 declination grid for {year:.2f}: {len(lats)}x{len(lons)}")
