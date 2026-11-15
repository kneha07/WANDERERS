"""Real starquakes: turn a star's measured brightness flicker into sound (Path B of the Starquakes feature).

    python pipeline/starquake.py                 # the Kepler stars listed in STARS, 2 months each
    python pipeline/starquake.py kic6106415 --months 1

Method (after Stanford's SoSH project, which did this for the Sun's Doppler velocity):
  1. Data: Kepler short-cadence (58.85 s) light curves from NASA MAST (PDCSAP flux, cached in data/cache/starquake/).
  2. Clean: keep quality-0 points, convert to ppm, cut 5-sigma outliers.
  3. Gaps: put the data on a uniform grid; interpolate short gaps (< 30 min) linearly, leave longer ones silent (zero).
  4. Measure from the data itself: nu_max (peak oscillation frequency) and dnu (mode spacing) with the collapsed
     autocorrelation of the power spectrum (Mosser & Appourchaux 2009), checked against the published values.
  5. Filter: band-pass around nu_max (cosine-tapered, +/-1.5 envelope widths), which removes slow trends and
     granulation below and photon noise above.
  6. Speed up 42,000x (the same for every star, as in SoSH) and write a 16-bit WAV at 8 kHz.

Writes app/data/starquake/<key>.wav and <key>.json, and records the measurement in app/data/starquake_stars.json.
"""
import argparse, io, json, re, sys, urllib.request
from pathlib import Path

import numpy as np
from astropy.io import fits
from scipy import signal
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache" / "starquake"
OUT = ROOT / "app" / "data" / "starquake"
INFO = ROOT / "app" / "data" / "starquake_stars.json"
MAST = "https://archive.stsci.edu/missions/kepler/lightcurves"
SPEEDUP = 42000
AUDIO_FS = 8000
STARS = ["kic8006161", "kic6106415", "kic12258514", "kic3632418"]


# ---------- data ----------
def kic_dir(kic):
    k = f"{int(kic):09d}"
    return f"{MAST}/{k[:4]}/{k}/"


def sc_files(kic):
    html = urllib.request.urlopen(kic_dir(kic), timeout=120).read().decode()
    return sorted(set(re.findall(r"kplr\d+-\d+_slc\.fits", html)))


def fetch(kic, months=2, skip=4):
    """Download `months` consecutive short-cadence files (skipping the first few, early-mission ones)."""
    names = sc_files(kic)
    if not names:
        raise RuntimeError(f"no short-cadence data for KIC {kic}")
    names = names[skip:skip + months] if len(names) > skip + months else names[:months]
    paths = []
    for n in names:
        f = CACHE / f"{int(kic):09d}" / n
        if not f.exists():
            f.parent.mkdir(parents=True, exist_ok=True)
            print(f"   downloading {n}", flush=True)
            data = urllib.request.urlopen(kic_dir(kic) + n, timeout=300).read()
            f.with_suffix(".part").write_bytes(data); f.with_suffix(".part").replace(f)
        paths.append(f)
    return paths


def read(paths):
    """-> time (s), flux (ppm), header info. Each file is normalised by its own median."""
    t_all, f_all, hdr, quarters = [], [], {}, []
    for p in paths:
        with fits.open(p) as h:
            d = h[1].data
            hdr = {k: h[0].header.get(k) for k in ("OBJECT", "KEPLERID", "RA_OBJ", "DEC_OBJ", "KEPMAG", "TEFF", "QUARTER")}
            quarters.append(h[0].header.get("QUARTER"))
            hdr["months"] = list(quarters)          # every file's quarter, not just the last file's
            ok = (d["SAP_QUALITY"] == 0) & np.isfinite(d["PDCSAP_FLUX"]) & np.isfinite(d["TIME"])
            t, f = d["TIME"][ok] * 86400.0, d["PDCSAP_FLUX"][ok]
            t_all.append(t); f_all.append((f / np.median(f) - 1) * 1e6)
    return np.concatenate(t_all), np.concatenate(f_all), hdr


# ---------- processing (pure functions, tested on synthetic data) ----------
def clean(t, f, nsig=5.0):
    """Remove 5-sigma outliers from a 31-point running median. Sigma is the robust (MAD) scatter of that same
    residual, which includes the oscillations themselves, so real mode peaks are never cut as outliers."""
    med = signal.medfilt(f, 31) if len(f) > 31 else np.full_like(f, np.median(f))
    r = f - med
    s = 1.4826 * np.median(np.abs(r - np.median(r)))
    keep = np.abs(r) < nsig * max(s, 1e-9)
    return t[keep], f[keep]


def regrid(t, f, dt, max_gap=1800.0):
    """Uniform grid with step dt. Gaps up to max_gap seconds are interpolated linearly; longer gaps are set to 0
    (silence) and flagged. Returns (grid_time, flux, filled_mask, gap_mask)."""
    grid = np.arange(t[0], t[-1] + dt / 2, dt)
    y = np.interp(grid, t, f)
    idx = np.searchsorted(t, grid)
    idx = np.clip(idx, 1, len(t) - 1)
    span = t[idx] - t[idx - 1]                         # size of the data gap each grid point sits in
    near = np.minimum(np.abs(grid - t[idx]), np.abs(grid - t[idx - 1])) < dt / 2
    gap = (~near) & (span > max_gap)
    filled = (~near) & ~gap
    y = y - np.mean(y[~gap])
    y[gap] = 0.0
    return grid, y, filled, gap


def power_spectrum(y, dt):
    """One-sided power density in ppm^2/uHz on a uHz grid."""
    n = len(y)
    F = np.fft.rfft(y * signal.windows.tukey(n, 0.02))
    nu = np.fft.rfftfreq(n, dt) * 1e6
    df = nu[1] - nu[0]
    return nu, 2 * np.abs(F) ** 2 / n ** 2 / df


def dnu_guess(numax):
    return 0.263 * numax ** 0.772                      # Stello et al. 2009


def measure(nu, psd, lo=300.0, hi=None, step=None):
    """nu_max and dnu by the collapsed autocorrelation (Mosser & Appourchaux 2009): for each trial centre, the
    autocorrelation of the background-normalised spectrum in a window of a few dnu peaks at the mode spacing
    where modes are present. Returns {numax, dnu, score_curve}."""
    hi = hi or 0.9 * nu[-1]
    df = nu[1] - nu[0]
    # background: running median over 200 uHz, so modes stand out as ratio > 1
    w = max(3, int(200 / df) | 1)
    bg = signal.medfilt(psd, w) if len(psd) > w else np.full_like(psd, np.median(psd))
    snr = psd / np.maximum(bg, 1e-30)
    centres = np.arange(lo, hi, step or 25.0)
    scores, lags_best = [], []
    for c in centres:
        g = dnu_guess(c)
        sel = (nu > c - 3 * g) & (nu < c + 3 * g)
        x = snr[sel] - np.mean(snr[sel])
        if x.size < 20:
            scores.append(0); lags_best.append(np.nan); continue
        ac = signal.correlate(x, x, mode="full")[x.size - 1:] / (np.sum(x * x) or 1)
        lag = np.arange(ac.size) * df
        m = (lag > 0.75 * g) & (lag < 1.3 * g)
        if not m.any():
            scores.append(0); lags_best.append(np.nan); continue
        i = np.argmax(ac[m]); scores.append(ac[m][i]); lags_best.append(lag[m][i])
    scores = np.array(scores)
    sm = np.convolve(scores, np.ones(5) / 5, mode="same")
    k = int(np.argmax(sm))
    numax = float(np.sum(centres * np.maximum(sm - 0.5 * sm[k], 0)) / np.sum(np.maximum(sm - 0.5 * sm[k], 0)))
    # refine dnu around nu_max with a finer autocorrelation and a parabola through the peak
    g = lags_best[k] if np.isfinite(lags_best[k]) else dnu_guess(numax)
    sel = (nu > numax - 5 * g) & (nu < numax + 5 * g)
    x = snr[sel] - np.mean(snr[sel])
    ac = signal.correlate(x, x, mode="full")[x.size - 1:]
    lag = np.arange(ac.size) * df
    m = np.where((lag > 0.85 * g) & (lag < 1.15 * g))[0]
    j = m[np.argmax(ac[m])]
    if 0 < j < ac.size - 1:
        a, b, c3 = ac[j - 1], ac[j], ac[j + 1]
        j = j + 0.5 * (a - c3) / (a - 2 * b + c3)
    return {"numax": numax, "dnu": float(j * df), "centres": centres, "score": sm}


def bandpass(y, dt, numax, width=1.5):
    """Cosine-tapered band-pass: keep nu_max +/- width * envelope FWHM (FWHM = 0.66 nu_max^0.88 uHz)."""
    fw = 0.66 * numax ** 0.88
    lo, hi = max(numax - width * fw, 0.25 * numax), numax + width * fw
    taper = 0.25 * fw
    F = np.fft.rfft(y)
    nu = np.fft.rfftfreq(len(y), dt) * 1e6
    g = np.clip((nu - (lo - taper)) / taper, 0, 1) * np.clip(((hi + taper) - nu) / taper, 0, 1)
    g = 0.5 - 0.5 * np.cos(np.pi * g)
    return np.fft.irfft(F * g, n=len(y)), (lo, hi)


def to_audio(y, dt, speedup=SPEEDUP, fs=AUDIO_FS, seconds=45.0, gap=None):
    """Speed up and resample to fs. Takes the `seconds`-long stretch with the fewest gaps."""
    native = speedup / dt                              # audio sample rate of the sped-up series
    n_keep = int(seconds * native)
    start = 0
    if gap is not None and len(y) > n_keep:
        csum = np.concatenate([[0], np.cumsum(gap)])
        counts = csum[n_keep:] - csum[:-n_keep]
        start = int(np.argmin(counts[::max(1, n_keep // 50)]) * max(1, n_keep // 50))
    seg = y[start:start + n_keep]
    out = signal.resample(seg, int(round(len(seg) * fs / native)))
    peak = np.percentile(np.abs(out), 99.9) or 1.0
    out = np.clip(out / peak * 0.8, -1, 1)
    fade = int(0.4 * fs)
    ramp = np.minimum(1, np.minimum(np.arange(len(out)), np.arange(len(out))[::-1]) / fade)
    return (out * ramp).astype(np.float32), native, start


# ---------- run ----------
def load_info():
    return json.loads(INFO.read_text()) if INFO.exists() else {}


def run(key, months=2, seconds=45.0):
    info = load_info()
    entry = info.get(key, {})
    kic = int(entry.get("kic") or key.replace("kic", ""))
    print(f"== {entry.get('name', key)} (KIC {kic})", flush=True)
    t, f, hdr = read(fetch(kic, months))
    t, f = clean(t, f)
    dt = float(np.median(np.diff(t)))
    grid, y, filled, gap = regrid(t, f, dt)
    nu, psd = power_spectrum(y, dt)
    m = measure(nu, psd)
    bp, (lo, hi) = bandpass(y, dt, m["numax"])
    audio, native, start = to_audio(bp, dt, seconds=seconds, gap=gap)
    OUT.mkdir(parents=True, exist_ok=True)
    wavfile.write(OUT / f"{key}.wav", AUDIO_FS, (audio * 32767).astype(np.int16))

    # picture: power spectrum around the envelope, smoothed and binned (for the page)
    sel = (nu > max(0.3 * m["numax"], 100)) & (nu < 1.8 * m["numax"])
    k = max(1, sel.sum() // 600)
    nb = sel.sum() // k
    bnu = nu[sel][:nb * k].reshape(nb, k).mean(1)
    bps = psd[sel][:nb * k].reshape(nb, k).mean(1)
    pub = {k2: entry.get(k2) for k2 in ("published_numax", "published_dnu", "published_ref")}
    agree = None
    if pub["published_numax"] and pub["published_dnu"]:
        agree = {"numax_pct": round(100 * (m["numax"] / pub["published_numax"] - 1), 1),
                 "dnu_pct": round(100 * (m["dnu"] / pub["published_dnu"] - 1), 2)}
    days = (grid[-1] - grid[0]) / 86400
    res = {
        "key": key, "kic": kic, "name": entry.get("name", f"KIC {kic}"), "ra": hdr.get("RA_OBJ"), "dec": hdr.get("DEC_OBJ"),
        "kepmag": hdr.get("KEPMAG"), "quarters": hdr.get("months"), "source": "Kepler short cadence (58.85 s), PDCSAP flux, NASA MAST",
        "days": round(days, 1), "cadence_s": round(dt, 2), "points": int(len(t)),
        "gap_fraction": round(float(gap.mean()), 3), "interpolated_fraction": round(float(filled.mean()), 3),
        "numax": round(m["numax"], 1), "dnu": round(m["dnu"], 2), "band_uHz": [round(lo, 1), round(hi, 1)],
        **pub, "agreement": agree,
        "speedup": SPEEDUP, "audio": f"data/starquake/{key}.wav", "audio_fs": AUDIO_FS,
        "audio_seconds": round(len(audio) / AUDIO_FS, 1), "audio_from_day": round(start * dt / 86400, 1),
        "pitch_hz": round(m["numax"] * 1e-6 * SPEEDUP, 1), "beat_hz": round(m["dnu"] * 1e-6 * SPEEDUP, 2),
        "spectrum": {"nu": [round(x, 1) for x in bnu], "psd": [float(f"{x:.4g}") for x in bps]},
    }
    (OUT / f"{key}.json").write_text(json.dumps(res, separators=(",", ":")))
    # record the measurement for the page
    entry.update({"kic": kic, "numax": res["numax"], "dnu": res["dnu"], "recording": res["audio"], "recording_info": f"data/starquake/{key}.json",
                  "ra": res["ra"], "dec": res["dec"], "teff": entry.get("teff") or hdr.get("TEFF")})
    info[key] = entry
    INFO.write_text(json.dumps(info, indent=1, ensure_ascii=False) + "\n")
    print(f"   {res['days']} days, {res['points']} points, gaps {res['gap_fraction']:.1%}; nu_max {res['numax']} uHz, dnu {res['dnu']} uHz"
          + (f" (published {pub['published_numax']}, {pub['published_dnu']}: {agree['numax_pct']:+}%, {agree['dnu_pct']:+}%)" if agree else "")
          + f"; audio {res['audio_seconds']} s around {res['pitch_hz']} Hz, beats {res['beat_hz']} Hz", flush=True)
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description="Real starquakes from Kepler light curves")
    ap.add_argument("stars", nargs="*", default=STARS)
    ap.add_argument("--months", type=int, default=2)
    ap.add_argument("--seconds", type=float, default=45.0)
    a = ap.parse_args(argv)
    for k in a.stars:
        try:
            run(k, a.months, a.seconds)
        except Exception as e:
            print(f"!! {k}: {e}", flush=True)


if __name__ == "__main__":
    main()
