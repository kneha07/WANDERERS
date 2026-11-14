"""SPHEREx blink pipeline: resolve a target, find images, align cutouts, make PNG frames."""
import re
from collections import defaultdict
from itertools import groupby

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.wcs import WCS

NUMBER = r"([+-]?(?:\d+\.?\d*|\.\d+))"
DECIMAL = re.compile(rf"\s*{NUMBER}\s*[,\s]\s*{NUMBER}\s*")
PIXEL_ARCSEC = 6.15
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


def group_epochs(mjds):
    """Group observation times (MJD) into survey epochs. Returns lists of indices, in time order."""
    groups = []
    for i in sorted(range(len(mjds)), key=mjds.__getitem__):
        if groups and mjds[i] - mjds[groups[-1][-1]] <= 20:
            groups[-1].append(i)
        else:
            groups.append([i])
    epochs = []
    for g in groups:
        t0 = mjds[g[0]]
        if mjds[g[-1]] - t0 > 45:  # long pass (deep field): cut into consecutive 30-day bins
            epochs += [list(b) for _, b in groupby(g, key=lambda i: (mjds[i] - t0) // 30)]
        else:
            epochs.append(g)
    if len(epochs) > 12:  # keep 12, evenly spaced; first and last stay for the longest baseline
        epochs = [epochs[k] for k in np.linspace(0, len(epochs) - 1, 12).round().astype(int)]
    return epochs


def choose_images(images, n):
    """Pick up to n images, in time order: detectors take turns, and each detector's picks spread in time."""
    by_det = defaultdict(list)
    for img in sorted(images, key=lambda r: r["mjd"]):
        by_det[img["detector"]].append(img)
    take = dict.fromkeys(by_det, 0)
    left = min(n, len(images))
    while left:
        for d in sorted(by_det):
            if left and take[d] < len(by_det[d]):
                take[d] += 1
                left -= 1
    chosen = []
    for d, imgs in by_det.items():
        chosen += [imgs[i] for i in np.linspace(0, len(imgs) - 1, take[d]).round().astype(int)]
    return sorted(chosen, key=lambda r: r["mjd"])


def output_wcs(center, n):
    """North-up, east-left TAN grid of n x n pixels (6.15 arcsec) centered on center."""
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [center.ra.deg, center.dec.deg]
    w.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]
    w.wcs.cdelt = [-PIXEL_ARCSEC / 3600, PIXEL_ARCSEC / 3600]
    return w


def display_xy(grid, n, coord):
    """Sky position -> PNG pixel coordinates with the origin at the top-left corner.

    Grid row 0 is south, but PNG row 0 is north (the PNG is flipped), so y counts down from the top.
    """
    x, y = grid.wcs_world2pix(coord.ra.deg, coord.dec.deg, 0)
    return float(x) + 0.5, n - 0.5 - float(y)
