"""Field-of-view helpers, kept free of heavy imports so they can be tested anywhere.

A target's field of view is the side of the square sky patch we download and show, in arcseconds.
It is stored in the target definition as "fov_arcsec". Larger fields catch faster-moving objects but
need more data from the archives, so the value is limited to a sensible range.
"""
DEFAULT_FOV = 300           # arcsec, the field every committed target uses
MIN_FOV, MAX_FOV = 60, 900  # arcsec, allowed range
CHOICES = (120, 300, 600)   # what the web page offers


def clamp_fov(value=None):
    """A whole number of arcseconds inside the allowed range; the default if value is missing or unusable."""
    if value is None:
        return DEFAULT_FOV
    try:
        v = float(value)
    except (TypeError, ValueError):
        return DEFAULT_FOV
    if v != v or v in (float("inf"), float("-inf")):   # NaN or infinity
        return DEFAULT_FOV
    return int(min(MAX_FOV, max(MIN_FOV, round(v))))


def fov_of(target):
    """Field of view of a target definition (a dict), with the default when it has none."""
    return clamp_fov(target.get("fov_arcsec", target.get("fov")))   # "fov" = the key WANDERERS lookups wrote before


def position_id(ra, dec, fov=None):
    """Target id for a user-chosen position. Matches the id the web server computes (fields.js).

    The default field keeps the original id format, so already-cached positions are still found.
    """
    tid = f"pos_{ra:.4f}_{dec:+.4f}".replace(".", "p").replace("+", "n").replace("-", "s")
    f = clamp_fov(fov)
    return tid if f == DEFAULT_FOV else f"{tid}_f{f}"


def npix_for(fov, grid_pix=2.0):
    """Pixels per side of the display grid for a field of view."""
    return int(clamp_fov(fov) / grid_pix)
