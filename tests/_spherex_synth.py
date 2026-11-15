"""Small synthetic SPHEREx DR1 cubes for the tests (no network): the real file layout (primary with MJD-BEG/END and
BLANKCH; IMAGE float32 cube with the HPX WCS and the WAVE-TAB keywords; NHITS; SPECTRAL_CHANNELS; WCS-WAVE) on a
coarse n x n grid of the same HiPS tile, so files stay ~1-2 MB."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "pipeline") not in sys.path:
    sys.path.insert(0, str(ROOT / "pipeline"))

from astropy.io import fits  # noqa: E402

from survey import spherex as SX  # noqa: E402

MJD_BEG, MJD_END = 60887.68160853, 61109.114633466          # tile 8545's real dates (2025-07-31 .. 2026-03-10)
EPOCH = SX.mjd_to_year(0.5 * (MJD_BEG + MJD_END))

# 6 detectors x 17 channels with the real wavelength ranges (log-spaced inside each detector)
DET_RANGES = [(0.753, 1.102), (1.113, 1.631), (1.656, 2.399), (2.445, 3.768), (3.833, 4.405), (4.435, 4.988)]


def channels():
    det, sub, wl = [], [], []
    for d, (a, b) in enumerate(DET_RANGES, 1):
        w = np.geomspace(a, b, 17)
        det += [d] * 17
        sub += list(range(1, 18))
        wl += list(w)
    return np.array(det), np.array(sub), np.array(wl)


DETS, SUBS, WAVES = channels()


def flat(mjy):
    return lambda wl: np.full_like(np.asarray(wl, float), float(mjy))


def brown_dwarf(peak_mjy=5.0):
    """Toy cold brown dwarf: faint below 3.8 um, a strong 4-4.8 um peak, deep 3.3 um methane band."""
    def f(wl):
        wl = np.asarray(wl, float)
        s = 0.03 * peak_mjy + peak_mjy * np.exp(-0.5 * ((wl - 4.4) / 0.35) ** 2)
        return np.where((wl >= 3.15) & (wl <= 3.5), 0.2 * s, s)
    return f


def write_cube(path, k5, n=64, sources=(), noise=2e-5, bkg=0.001, seed=1, blankch="D3:17,D4:01",
               mjd=(MJD_BEG, MJD_END), psf_sigma_px=0.55, nhits=True):
    """sources: [(ra, dec, sed(wl) -> mJy)]. Writes the cube for tile k5 and returns its path."""
    rng = np.random.default_rng(seed)
    hdr = SX.hpx_tile_header(k5, n)
    w = SX.celestial_wcs(hdr, n, n)
    nz = len(WAVES)
    data = rng.normal(bkg, noise, (nz, n, n))
    pix_sr = SX.TILE_SR / (n * n)
    yy, xx = np.mgrid[0:n, 0:n]
    for ra, dec, sed in sources:
        x, y = w.world_to_pixel_values(ra, dec)
        if not (np.isfinite(x) and np.isfinite(y)):
            continue
        g = np.exp(-0.5 * ((xx - float(x)) ** 2 + (yy - float(y)) ** 2) / psf_sigma_px ** 2)
        g /= 2 * math.pi * psf_sigma_px ** 2
        flux = np.asarray(sed(WAVES), float)                 # mJy per channel
        data += (flux / (pix_sr * 1e9))[:, None, None] * g[None]
    blank = [(d, s) for d, s in SX.parse_blankch(blankch)]
    for d, s in blank:
        data[(DETS == d) & (SUBS == s)] = np.nan
    prim = fits.PrimaryHDU()
    prim.header["MJD-BEG"] = mjd[0]
    prim.header["MJD-END"] = mjd[1]
    prim.header["DATE-BEG"] = "2025-07-31T16:21:30.977"
    prim.header["DATE-END"] = "2026-03-10T02:45:04.331"
    prim.header["TELESCOP"] = "SPHEREx"
    if blankch:
        prim.header["BLANKCH"] = blankch
    img = fits.ImageHDU(data.astype(">f4"), name="IMAGE")
    for k, v in hdr.items():
        img.header[k] = v
    img.header["CTYPE3"] = "WAVE-TAB"
    img.header["CUNIT3"] = "um"
    img.header["PS3_0"] = "WCS-WAVE"
    img.header["PS3_1"] = "WAVELENGTHS"
    img.header["PS3_2"] = "PLANE"
    img.header["ORDER"] = 5
    img.header["NPIX"] = int(k5)
    img.header["BUNIT"] = "MJy/sr"
    hdus = [prim, img]
    if nhits:
        hdus.append(fits.ImageHDU(np.ones((nz, n, n), dtype=">i4"), name="NHITS"))
    cols = [fits.Column(name="DETECTOR", format="I", array=DETS), fits.Column(name="SUBCHAN", format="I", array=SUBS),
            fits.Column(name="WAVELENGTH", format="E", array=WAVES),
            fits.Column(name="WL_MIN", format="E", array=WAVES * 0.99), fits.Column(name="WL_MAX", format="E", array=WAVES * 1.01),
            fits.Column(name="R", format="E", array=np.full(nz, 40.0)), fits.Column(name="R_STD", format="E", array=np.ones(nz)),
            fits.Column(name="BANDWIDTH", format="E", array=WAVES / 40.0)]
    hdus.append(fits.BinTableHDU.from_columns(cols, name="SPECTRAL_CHANNELS"))
    ww = fits.BinTableHDU.from_columns([
        fits.Column(name="PLANE", format=f"{nz}J", array=np.arange(1, nz + 1)[None, :]),
        fits.Column(name="WAVELENGTHS", format=f"{nz}E", array=WAVES[None, :]),
        fits.Column(name="BANDWIDTHS", format=f"{nz}E", array=(WAVES / 40.0)[None, :])], name="WCS-WAVE")
    hdus.append(ww)
    fits.HDUList(hdus).writeto(path, overwrite=True)
    return Path(path)


class RecordingReader(SX.FileRangeReader):
    """FileRangeReader that remembers every (url, start, stop) and can be told to fail."""

    def __init__(self, files: dict, fail_after: int | None = None, error=None):
        super().__init__(lambda url: files.get(url))
        self.calls = []
        self.fail_after = fail_after
        self.error = error

    def read(self, url, start, stop):
        if self.fail_after is not None and len(self.calls) >= self.fail_after:
            raise self.error or SX.NetworkError("connection reset")
        self.calls.append((url, start, stop))
        return super().read(url, start, stop)


def url_for(k5):
    return f"synthetic://{int(k5)}"


def stage_for(files_by_k5: dict, **kw) -> tuple:
    files = {url_for(k): str(p) for k, p in files_by_k5.items()}
    reader = RecordingReader(files, **kw)
    return SX.SpherexStage(reader=reader, url_for=url_for, workers=4), reader


def mover(ra, dec, epoch=2019.0, pmra=0.0, pmdec=0.0, **kw):
    """A mover whose position at `epoch` is (ra, dec); first NEOWISE visit at 2014.3 unless track is given."""
    m = {"id": kw.pop("id", "t-0001"), "ra": ra, "dec": dec, "epoch": epoch, "pmra": pmra, "pmdec": pmdec,
         "pm": math.hypot(pmra, pmdec), "pm_err": 5.0, "w1": 12.0, "w2": 12.0, "span_yr": 10.0,
         "track": [[2014.3, ra, dec]]}
    m.update(kw)
    return m


def at_epoch(ra, dec, pmra, pmdec, t_from, t_to):
    from survey.rank import propagate
    return propagate(ra, dec, pmra, pmdec, t_to - t_from)
