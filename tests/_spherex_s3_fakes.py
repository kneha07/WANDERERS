"""Synthetic SPHEREx Level-2 files and a fake S3 bucket for the offline tests of pipeline/spherex_s3.py,
pipeline/fetch.py's S3 fallback and pipeline/spherex_releases.py's bucket listing. No network.

make_level2() writes a small file laid out like the real ones (checked on S3, 2026-11-15): a 5-card primary header,
IMAGE (float32, TAN-SIP WCS plus the 'A' pixel and 'W' wavelength-table WCS), FLAGS (int32, RICE_1 tile-compressed one
row per tile), VARIANCE, ZODI, EPSF (a table) and WCS-WAVE (the last HDU). FakeBucket serves byte ranges and S3-style
listings from a dict and counts requests and bytes.
"""
import io
import math

import numpy as np
from astropy.io import fits

PIX_DEG = 6.15 / 3600


def level2_key(release, week, obs, det, proc="l2b-v27-2026-300"):
    return f"{release}/level2/{week}/{proc}/{det}/level2_{obs}D{det}_spx_{proc}.fits"


def image_header(nx, ny, ra, dec, det, obs, mjd, rot_deg=30.0, sip=True, flags="all_sky", extra_history=0):
    h = fits.Header()
    h["EXTNAME"] = ("IMAGE", "extension name")
    h["EXTTYPE"] = "IMAGE"
    h["BUNIT"] = "MJy / sr"
    h["DETECTOR"] = (det, "1-3: SWIR, 4-6: MWIR")
    h["OBSID"] = obs
    h["HIERARCH SPS_FLAGS"] = flags
    h["DETCOORD"] = "sky"
    h["RADESYS"] = "ICRS"
    h["WCSAXES"] = 2
    h["CRPIX1"] = (nx + 1) / 2
    h["CRPIX2"] = (ny + 1) / 2
    c, s = math.cos(math.radians(rot_deg)), math.sin(math.radians(rot_deg))
    h["PC1_1"], h["PC1_2"], h["PC2_1"], h["PC2_2"] = -PIX_DEG * c, PIX_DEG * s, PIX_DEG * s, PIX_DEG * c
    h["CDELT1"], h["CDELT2"] = 1.0, 1.0
    h["CUNIT1"], h["CUNIT2"] = "deg", "deg"
    h["CTYPE1"] = "RA---TAN-SIP" if sip else "RA---TAN"
    h["CTYPE2"] = "DEC--TAN-SIP" if sip else "DEC--TAN"
    h["CRVAL1"], h["CRVAL2"] = ra, dec
    h["LONPOLE"], h["LATPOLE"] = 180.0, dec
    if sip:
        h["A_ORDER"] = 2
        h["A_0_2"], h["A_1_1"], h["A_2_0"] = 2e-5, -1e-5, 3e-5
        h["B_ORDER"] = 2
        h["B_0_2"], h["B_1_1"], h["B_2_0"] = -2e-5, 1.5e-5, 1e-5
        h["AP_ORDER"] = 2
        h["AP_0_2"], h["AP_1_1"], h["AP_2_0"] = -2e-5, 1e-5, -3e-5
        h["BP_ORDER"] = 2
        h["BP_0_2"], h["BP_1_1"], h["BP_2_0"] = 2e-5, -1.5e-5, -1e-5
    h["WCSAXESA"] = 2
    h["CRPIX1A"], h["CRPIX2A"] = 1.0, 1.0
    h["CDELT1A"], h["CDELT2A"] = 1.0, 1.0
    h["CUNIT1A"], h["CUNIT2A"] = "pixel", "pixel"
    h["CTYPE1A"], h["CTYPE2A"] = "LINEAR", "LINEAR"
    h["CRVAL1A"], h["CRVAL2A"] = 0.0, 0.0
    h["WCSNAMEA"] = "0-based active pixel coordinates"
    h["TIMESYS"] = "UTC"
    h["MJD-OBS"], h["MJD-BEG"], h["MJD-END"] = mjd, mjd, mjd + 113.58 / 86400
    h["WCSAXESW"] = 2
    h["WCSNAMEW"] = "Approximated per-pixel wavelength and bandwidth"
    h["CNAME1W"], h["CNAME2W"] = "Wavelength", "Bandwidth"
    h["CRPIX1W"], h["CRPIX2W"] = 1, 1
    h["CDELT1W"], h["CDELT2W"] = 1, 1
    h["CUNIT1W"], h["CUNIT2W"] = "um", "um"
    h["CTYPE1W"], h["CTYPE2W"] = "WAVE-TAB", "WAVE-TAB"
    h["CRVAL1W"], h["CRVAL2W"] = 1, 1
    h["PV1_3W"], h["PV2_3W"] = 1, 2
    h["PS1_0W"], h["PS2_0W"] = "WCS-WAVE", "WCS-WAVE"
    h["PS1_1W"], h["PS2_1W"] = "VALUES", "VALUES"
    h["PS1_2W"], h["PS2_2W"] = "X", "Y"
    for i in range(extra_history):
        h.add_history(f"synthetic history card {i}")
    return h


def make_level2(nx=64, ny=48, ra=10.0, dec=20.0, det=1, obs="2026W33_1A_0001_1", mjd=61270.25, rot_deg=30.0,
                sip=True, flags="all_sky", seed=0, extra_history=0):
    """(file bytes, IMAGE header, {extname: data}) of a synthetic Level-2 file."""
    rng = np.random.default_rng(seed)
    h = image_header(nx, ny, ra, dec, det, obs, mjd, rot_deg, sip, flags, extra_history)
    img = rng.normal(5.0, 1.0, (ny, nx)).astype(">f4")
    var = rng.uniform(0.1, 0.2, (ny, nx)).astype(">f4")
    flg = (rng.integers(0, 4, (ny, nx)) * rng.choice([0, 1, 2048, 2097152], (ny, nx))).astype(">i4")
    zodi = np.full((ny, nx), 0.5, ">f4")
    prim = fits.PrimaryHDU()
    prim.header["VERSION"] = ("7.0.5", "SSDC Pipelines software version")
    fh = fits.Header()
    for k in ("WCSAXES", "CRPIX1", "CRPIX2", "PC1_1", "PC1_2", "PC2_1", "PC2_2", "CTYPE1", "CTYPE2", "CRVAL1",
              "CRVAL2", "CRPIX1A", "CRPIX2A", "CRPIX1W", "CRPIX2W", "MJD-OBS"):
        fh[k] = h[k]
    fh["EXTTYPE"] = "MASK"
    fh["MSKN0000"], fh["MSKM0000"] = "TRANSIENT", 1
    flags_hdu = fits.CompImageHDU(data=np.asarray(flg, dtype=np.int32), header=fh, name="FLAGS",
                                  compression_type="RICE_1", tile_shape=(1, nx))
    vh = fits.Header()
    vh["BUNIT"] = "MJy2 / sr2"
    for k in ("CRPIX1", "CRPIX2", "CRPIX1A", "CRPIX2A", "CRPIX1W", "CRPIX2W"):
        vh[k] = h[k]
    epsf = fits.BinTableHDU.from_columns([fits.Column("PSF", "100E", array=rng.normal(size=(5, 100)))], name="EPSF")
    wave = fits.BinTableHDU.from_columns([
        fits.Column("X", "9J", array=np.arange(9)[None] * 8),
        fits.Column("Y", "14J", array=np.arange(14)[None] * 4),
        fits.Column("VALUES", "252E", dim="(2,9,14)", array=rng.uniform(0.7, 1.1, (1, 14, 9, 2)).astype("f4"))],
        name="WCS-WAVE")
    wave.header["DETECTOR"] = str(det)
    hdul = fits.HDUList([prim, fits.ImageHDU(img, header=h, name="IMAGE"), flags_hdu,
                         fits.ImageHDU(var, header=vh, name="VARIANCE"), fits.ImageHDU(zodi, name="ZODI"), epsf,
                         wave])
    buf = io.BytesIO()
    hdul.writeto(buf)
    raw = buf.getvalue()
    written = fits.getheader(io.BytesIO(raw), "IMAGE")          # with NAXIS1/NAXIS2, as in a real file
    return raw, written, {"IMAGE": np.asarray(img), "FLAGS": np.asarray(flg), "VARIANCE": np.asarray(var)}


class FakeBucket:
    """The S3Reader interface over a dict {key: bytes}: read, read_suffix, list (with delimiter and pages)."""

    def __init__(self, objects=None, fail=()):
        self.objects = dict(objects or {})
        self.fail = set(fail)            # keys whose reads raise
        self.requests = 0
        self.bytes = 0
        self.reads = []                  # (key, start, stop)
        self.lists = []

    def put(self, key, data):
        self.objects[key] = data

    def _get(self, key):
        if key in self.fail:
            raise OSError(f"injected failure for {key}")
        if key not in self.objects:
            raise OSError(f"404 {key}")
        return self.objects[key]

    def read(self, key, start, stop):
        data = self._get(key)[start:stop]
        self.requests += 1
        self.bytes += len(data)
        self.reads.append((key, start, stop))
        return data

    def read_suffix(self, key, n):
        obj = self._get(key)
        data = obj[max(0, len(obj) - n):]
        self.requests += 1
        self.bytes += len(data)
        self.reads.append((key, -n, None))
        return data

    def list(self, prefix, delimiter=None):
        self.lists.append(prefix)
        prefixes, keys = set(), []
        for k in sorted(self.objects):
            if not k.startswith(prefix):
                continue
            rest = k[len(prefix):]
            if delimiter and delimiter in rest:
                prefixes.add(prefix + rest.split(delimiter, 1)[0] + delimiter)
            else:
                keys.append((k, len(self.objects[k])))
        return sorted(prefixes), keys
