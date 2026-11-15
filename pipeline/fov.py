"""Field-of-view helpers, kept free of heavy imports so they can be tested anywhere.

A target's field of view is the side of the square sky patch we download and show, in arcseconds.
It is stored in the target definition as "fov_arcsec". Larger fields catch faster-moving objects but
need more data from the archives, so the value is limited to a sensible range.
"""
from decimal import Decimal, ROUND_HALF_UP

DEFAULT_FOV = 300           # arcsec, the field every committed target uses
MIN_FOV, MAX_FOV = 60, 900  # arcsec, allowed range
CHOICES = (120, 300, 600)   # what the web page offers


def clamp_fov(value=None):
    """A whole number of arcseconds inside the allowed range; the default if value is missing or unusable."""
    if value is None:
        return DEFAULT_FOV
    try:
        v = float(value)
    except (TypeError, ValueError, OverflowError):    # OverflowError: an integer too large for a float
        return DEFAULT_FOV
    if v != v or v in (float("inf"), float("-inf")):   # NaN or infinity
        return DEFAULT_FOV
    return int(min(MAX_FOV, max(MIN_FOV, round(v))))


def fov_of(target):
    """Field of view of a target definition (a dict), with the default when it has none."""
    return clamp_fov(target.get("fov_arcsec", target.get("fov")))   # "fov" = the key WANDERERS lookups wrote before


def _to_fixed(v, digits=4):
    """v with `digits` decimals exactly like JavaScript's v.toFixed(digits): a tie rounds away from zero
    (Python's format rounds it to even: 1.03125 -> 1.0312, JavaScript -> 1.0313) and -0 prints as 0."""
    v = float(v)
    q = Decimal(abs(v)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)   # exact binary value
    return ("-" if v < 0 else "") + f"{q:f}"


def position_id(ra, dec, fov=None):
    """Target id for a user-chosen position. Matches the id the web server computes (fields.js).

    The default field keeps the original id format, so already-cached positions are still found.
    """
    sign = "-" if float(dec) < 0 else "+"
    tid = f"pos_{_to_fixed(ra)}_{sign}{_to_fixed(abs(float(dec)))}".replace(".", "p").replace("+", "n").replace("-", "s")
    f = clamp_fov(fov)
    return tid if f == DEFAULT_FOV else f"{tid}_f{f}"


def npix_for(fov, grid_pix=2.0):
    """Pixels per side of the display grid for a field of view."""
    return int(clamp_fov(fov) / grid_pix)
