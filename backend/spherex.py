"""SPHEREx blink pipeline: resolve a target, find images, align cutouts, make PNG frames."""
import re

from astropy import units as u
from astropy.coordinates import SkyCoord

NUMBER = r"([+-]?(?:\d+\.?\d*|\.\d+))"
DECIMAL = re.compile(rf"\s*{NUMBER}\s*[,\s]\s*{NUMBER}\s*")
SEXAGESIMAL = re.compile(r"\s*[+-]?\d[\d\s:hmsd°'\".,+-]*")


def parse_coords(q):
    """RA/Dec text -> SkyCoord (ICRS). None if q looks like a name. ValueError for bad numbers."""
    hint = f"Could not read '{q.strip()}' as RA/Dec. Use for example 269.45 4.69 or 17h57m48.5s +04d41m36s."
    if m := DECIMAL.fullmatch(q):
        ra, dec = float(m[1]), float(m[2])
        if not (0 <= ra <= 360 and -90 <= dec <= 90):
            raise ValueError(f"{hint} RA must be 0 to 360 and Dec -90 to +90 degrees.")
        return SkyCoord(ra, dec, unit=u.deg)
    if SEXAGESIMAL.fullmatch(q):
        try:
            return SkyCoord(q, unit=(u.hourangle, u.deg))
        except ValueError:
            raise ValueError(hint) from None
    return None
